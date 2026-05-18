"""CRUD on std_publish_event + version status machine + fork."""
from __future__ import annotations

import re
import uuid
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine
from ..outbox import enqueue as _outbox_enqueue


_VERSION_LABEL_RE = re.compile(r"^v\d+\.\d+(?:\.\d+)?$")


def publish_version(*, version_id: str, by_user: str) -> dict:
    """Atomically: status approved->released + insert publish_event +
    enqueue 'version_released' outbox event.

    Returns: {version_id, status, released_at, outbox_event_id}
    Raises:
      LookupError if version not found
      ValueError if status != 'approved' or already released
    """
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i FOR UPDATE"
        ), {"i": version_id}).first()
        if row is None:
            raise LookupError("version not found")
        if row[0] == "released":
            raise ValueError("version already released")
        if row[0] != "approved":
            raise ValueError(f"version status must be approved (got {row[0]})")
        conn.execute(text(
            "UPDATE std_document_version SET status='released', "
            "released_at=now(), updated_at=now(), updated_by=:u "
            "WHERE id=:i"
        ), {"u": by_user, "i": version_id})
        conn.execute(text(
            "INSERT INTO std_publish_event "
            "(document_version_id, event_type, actor_user_id) "
            "VALUES (:v, 'published', :u)"
        ), {"v": version_id, "u": by_user})
        released_at = conn.execute(text(
            "SELECT released_at FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).scalar()
    # Enqueue OUTSIDE the publish transaction (outbox.enqueue manages its own).
    outbox_id = _outbox_enqueue(
        "version_released", {"version_id": version_id}
    )
    return {
        "version_id": version_id,
        "status": "released",
        "released_at": released_at.isoformat() if released_at else None,
        "outbox_event_id": outbox_id,
    }


def fork_version(*, source_version_id: str, new_label: str,
                 by_user: str) -> str:
    """Copy clause/data_element/term/value_domain/reference rows from a
    released source version into a new draft version.

    new_label must match v\\d+\\.\\d+(\\.\\d+)?  (e.g. 'v1.1', 'v2.0').

    Returns new_version_id.
    Raises:
      LookupError if source not found
      ValueError on label format / source-not-released / label-exists
    """
    if not _VERSION_LABEL_RE.match(new_label):
        raise ValueError(
            f"new_label '{new_label}' must match v<major>.<minor>(.<patch>)"
        )
    parts = new_label.lstrip("v").split(".")
    semver = {
        "major": int(parts[0]),
        "minor": int(parts[1]),
        "patch": int(parts[2]) if len(parts) > 2 else 0,
    }

    new_vid = str(uuid.uuid4())
    eng = get_engine()
    with eng.begin() as conn:
        src = conn.execute(text(
            "SELECT document_id, status FROM std_document_version "
            "WHERE id=:i FOR UPDATE"
        ), {"i": source_version_id}).first()
        if src is None:
            raise LookupError("source version not found")
        if src[1] != "released":
            raise ValueError(f"source must be released (got {src[1]})")
        doc_id = str(src[0])

        dup = conn.execute(text(
            "SELECT 1 FROM std_document_version "
            "WHERE document_id=:d AND version_label=:l"
        ), {"d": doc_id, "l": new_label}).first()
        if dup:
            raise ValueError(f"version_label {new_label!r} already exists for doc")

        # 1. New version row
        conn.execute(text(
            "INSERT INTO std_document_version "
            "(id, document_id, version_label, semver_major, semver_minor, "
            " semver_patch, status, supersedes_version_id, "
            " created_by, updated_by) "
            "VALUES (:i, :d, :l, :ma, :mi, :pa, 'draft', :s, :u, :u)"
        ), {"i": new_vid, "d": doc_id, "l": new_label,
             "ma": semver["major"], "mi": semver["minor"],
             "pa": semver["patch"], "s": source_version_id, "u": by_user})

        # 2. Copy std_value_domain (no FK to clause yet, so do first)
        old_vds = conn.execute(text(
            "SELECT id, code, name, kind, defined_by_clause_id "
            "FROM std_value_domain WHERE document_version_id=:v"
        ), {"v": source_version_id}).mappings().all()
        vd_id_map: dict[str, str] = {}
        for vd in old_vds:
            new_vd_id = str(uuid.uuid4())
            vd_id_map[str(vd["id"])] = new_vd_id
            conn.execute(text(
                "INSERT INTO std_value_domain "
                "(id, document_version_id, code, name, kind, defined_by_clause_id) "
                "VALUES (:i, :v, :c, :n, :k, :dc)"
            ), {"i": new_vd_id, "v": new_vid, "c": vd["code"],
                 "n": vd["name"], "k": vd["kind"],
                 "dc": vd["defined_by_clause_id"]})

        # 3. Copy std_clause + build clause_id_map. Two passes because
        #    parent_clause_id may reference a sibling that hasn't been
        #    inserted yet — first insert without parent, then UPDATE.
        old_clauses = conn.execute(text(
            "SELECT id, parent_clause_id, ordinal_path, heading, clause_no, "
            "kind, body_md, body_html, checksum, source_origin "
            "FROM std_clause WHERE document_version_id=:v "
            "ORDER BY ordinal_path"
        ), {"v": source_version_id}).mappings().all()
        clause_id_map: dict[str, str] = {}
        for c in old_clauses:
            new_cid = str(uuid.uuid4())
            clause_id_map[str(c["id"])] = new_cid
            conn.execute(text(
                "INSERT INTO std_clause "
                "(id, document_id, document_version_id, "
                " ordinal_path, heading, clause_no, kind, "
                " body_md, body_html, checksum, source_origin, "
                " created_by, updated_by) "
                "VALUES (:i, :d, :v, :op, :h, :cn, :k, :bm, :bh, :ck, :so, "
                "        :u, :u)"
            ), {"i": new_cid, "d": doc_id, "v": new_vid,
                 "op": c["ordinal_path"], "h": c["heading"],
                 "cn": c["clause_no"], "k": c["kind"],
                 "bm": c["body_md"], "bh": c["body_html"],
                 "ck": c["checksum"], "so": c["source_origin"],
                 "u": by_user})
        # Second pass: set parent_clause_id
        for c in old_clauses:
            if c["parent_clause_id"]:
                new_parent = clause_id_map.get(str(c["parent_clause_id"]))
                if new_parent:
                    conn.execute(text(
                        "UPDATE std_clause SET parent_clause_id=:p "
                        "WHERE id=:i"
                    ), {"p": new_parent, "i": clause_id_map[str(c["id"])]})
        # Update value_domain.defined_by_clause_id with map
        for old_vd_id, new_vd_id in vd_id_map.items():
            row = conn.execute(text(
                "SELECT defined_by_clause_id FROM std_value_domain "
                "WHERE id=:i"
            ), {"i": new_vd_id}).first()
            if row and row[0] and str(row[0]) in clause_id_map:
                conn.execute(text(
                    "UPDATE std_value_domain SET defined_by_clause_id=:c "
                    "WHERE id=:i"
                ), {"c": clause_id_map[str(row[0])], "i": new_vd_id})

        # 4. Copy std_term
        old_terms = conn.execute(text(
            "SELECT id, term_code, name_zh, name_en, definition, aliases, "
            "defined_by_clause_id "
            "FROM std_term WHERE document_version_id=:v"
        ), {"v": source_version_id}).mappings().all()
        term_id_map: dict[str, str] = {}
        for t in old_terms:
            new_tid = str(uuid.uuid4())
            term_id_map[str(t["id"])] = new_tid
            new_dc = (
                clause_id_map.get(str(t["defined_by_clause_id"]))
                if t["defined_by_clause_id"] else None
            )
            conn.execute(text(
                "INSERT INTO std_term "
                "(id, document_version_id, term_code, name_zh, name_en, "
                " definition, aliases, defined_by_clause_id) "
                "VALUES (:i, :v, :tc, :nz, :ne, :df, :al, :dc)"
            ), {"i": new_tid, "v": new_vid, "tc": t["term_code"],
                 "nz": t["name_zh"], "ne": t["name_en"],
                 "df": t["definition"], "al": t["aliases"], "dc": new_dc})

        # 5. Copy std_data_element (preserve binding, remap clause + value_domain + term FKs)
        old_des = conn.execute(text(
            "SELECT id, code, name_zh, name_en, definition, "
            "representation_class, datatype, unit, value_domain_id, "
            "obligation, cardinality, defined_by_clause_id, term_id, "
            "data_classification, bound_table, bound_column "
            "FROM std_data_element WHERE document_version_id=:v"
        ), {"v": source_version_id}).mappings().all()
        de_id_map: dict[str, str] = {}
        for de in old_des:
            new_de_id = str(uuid.uuid4())
            de_id_map[str(de["id"])] = new_de_id
            new_dc = (
                clause_id_map.get(str(de["defined_by_clause_id"]))
                if de["defined_by_clause_id"] else None
            )
            new_vd = (
                vd_id_map.get(str(de["value_domain_id"]))
                if de["value_domain_id"] else None
            )
            new_term = (
                term_id_map.get(str(de["term_id"]))
                if de["term_id"] else None
            )
            conn.execute(text(
                "INSERT INTO std_data_element "
                "(id, document_version_id, code, name_zh, name_en, "
                " definition, representation_class, datatype, unit, "
                " value_domain_id, obligation, cardinality, "
                " defined_by_clause_id, term_id, data_classification, "
                " bound_table, bound_column) "
                "VALUES (:i, :v, :c, :nz, :ne, :df, :rc, :dt, :u, :vd, "
                "        :ob, :ca, :dc, :tm, :dcl, :bt, :bc)"
            ), {"i": new_de_id, "v": new_vid, "c": de["code"],
                 "nz": de["name_zh"], "ne": de["name_en"],
                 "df": de["definition"], "rc": de["representation_class"],
                 "dt": de["datatype"], "u": de["unit"], "vd": new_vd,
                 "ob": de["obligation"], "ca": de["cardinality"],
                 "dc": new_dc, "tm": new_term,
                 "dcl": de["data_classification"],
                 "bt": de["bound_table"], "bc": de["bound_column"]})

        # 6. Copy std_reference (remap source/target FKs by maps)
        old_refs = conn.execute(text(
            "SELECT id, source_clause_id, source_data_element_id, target_kind, "
            "target_clause_id, target_document_id, target_url, target_doi, "
            "snapshot_id, citation_text, confidence, target_data_element_id, "
            "target_term_id, inserted_by, verification_status "
            "FROM std_reference "
            "WHERE source_clause_id IN ("
            "  SELECT id FROM std_clause WHERE document_version_id=:v"
            ")"
        ), {"v": source_version_id}).mappings().all()
        for r in old_refs:
            new_rid = str(uuid.uuid4())
            new_src_clause = clause_id_map.get(str(r["source_clause_id"])) \
                if r["source_clause_id"] else None
            new_src_de = de_id_map.get(str(r["source_data_element_id"])) \
                if r["source_data_element_id"] else None
            # target_clause_id: same-doc → remap; cross-doc → keep
            new_tgt_clause = r["target_clause_id"]
            if new_tgt_clause and str(new_tgt_clause) in clause_id_map:
                new_tgt_clause = clause_id_map[str(new_tgt_clause)]
            # target_data_element_id / target_term_id → remap if same-doc
            new_tgt_de = r["target_data_element_id"]
            if new_tgt_de and str(new_tgt_de) in de_id_map:
                new_tgt_de = de_id_map[str(new_tgt_de)]
            new_tgt_term = r["target_term_id"]
            if new_tgt_term and str(new_tgt_term) in term_id_map:
                new_tgt_term = term_id_map[str(new_tgt_term)]
            conn.execute(text(
                "INSERT INTO std_reference "
                "(id, source_clause_id, source_data_element_id, target_kind, "
                " target_clause_id, target_document_id, target_url, target_doi, "
                " snapshot_id, citation_text, confidence, target_data_element_id, "
                " target_term_id, inserted_by, verification_status) "
                "VALUES (:i, :sc, :sde, :tk, :tc, :td, :tu, :tdoi, :sn, :ct, "
                "        :cf, :tde, :tt, :ib, :vs)"
            ), {"i": new_rid, "sc": new_src_clause, "sde": new_src_de,
                 "tk": r["target_kind"], "tc": new_tgt_clause,
                 "td": r["target_document_id"], "tu": r["target_url"],
                 "tdoi": r["target_doi"], "sn": r["snapshot_id"],
                 "ct": r["citation_text"], "cf": r["confidence"],
                 "tde": new_tgt_de, "tt": new_tgt_term,
                 "ib": by_user, "vs": "pending"})

        # 7. Publish event (forked)
        conn.execute(text(
            "INSERT INTO std_publish_event "
            "(document_version_id, event_type, actor_user_id, notes) "
            "VALUES (:v, 'forked', :u, :n)"
        ), {"v": new_vid, "u": by_user,
             "n": f"forked from {source_version_id}"})

    return new_vid


def list_published_versions(*, document_id: Optional[str] = None) -> list[dict]:
    """released versions; optional filter by document_id."""
    sql = (
        "SELECT id, document_id, version_label, semver_major, semver_minor, "
        "semver_patch, released_at, updated_by AS released_by, "
        "supersedes_version_id "
        "FROM std_document_version WHERE status='released'"
    )
    params: dict = {}
    if document_id:
        sql += " AND document_id=:d"
        params["d"] = document_id
    sql += " ORDER BY released_at DESC NULLS LAST"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def get_publish_timeline(*, version_id: str) -> list[dict]:
    """std_publish_event timeline for a single version."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, event_type, actor_user_id, occurred_at, notes "
            "FROM std_publish_event WHERE document_version_id=:v "
            "ORDER BY occurred_at DESC"
        ), {"v": version_id}).mappings().all()
    return [dict(r) for r in rows]
