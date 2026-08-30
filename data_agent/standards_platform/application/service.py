"""Database-backed application of released standard versions."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from ...database_tools import T_VIRTUAL_SOURCES, _inject_user_context
from ...db_engine import get_engine
from .contracts import (
    SourceFieldProfile,
    StandardDataElement,
    evaluate_mapping_quality_gate,
    mapping_publication_status,
    propose_standard_mapping,
)


def resolve_released_standard_version(
    *,
    doc_code: str,
    version_label: str,
) -> str:
    """Resolve one released logical standard identity to its database UUID."""
    doc_code = doc_code.strip()
    version_label = version_label.strip()
    if not doc_code or not version_label:
        raise ValueError("doc_code and version_label are required")
    eng = get_engine()
    if eng is None:
        raise RuntimeError("database unavailable")
    with eng.connect() as conn:
        rows = conn.execute(text("""
            SELECT v.id
              FROM std_document_version v
              JOIN std_document d ON d.id = v.document_id
             WHERE d.doc_code = :doc_code
               AND v.version_label = :version_label
               AND v.status = 'released'
             ORDER BY v.created_at DESC
        """), {
            "doc_code": doc_code,
            "version_label": version_label,
        }).scalars().all()
    if not rows:
        raise LookupError("released standard version not found")
    if len(rows) > 1:
        raise RuntimeError("released standard identity is not unique")
    return str(rows[0])


def propose_for_released_standard(
    *,
    standard_version_id: str,
    source_fields: Sequence[SourceFieldProfile],
    target_table: str | None = None,
) -> dict:
    """Load one released standard and generate a read-only mapping proposal."""
    version, elements = load_released_standard(standard_version_id)
    proposal = propose_standard_mapping(
        source_fields=source_fields,
        standard_version_id=standard_version_id,
        elements=elements,
        target_table=target_table,
        embedding_provider=_get_embeddings,
    )
    proposal["standard"] = version
    scoped_elements = [
        element for element in elements
        if target_table is None
        or element.bound_table.casefold() == target_table.strip().casefold()
    ]
    proposal["standard_elements"] = [
        {
            "target_data_element_id": element.id,
            "target_field": element.target_field,
            "code": element.code,
            "name_zh": element.name_zh,
            "datatype": element.datatype,
            "unit": element.unit,
            "obligation": element.obligation,
            "bound_table": element.bound_table,
        }
        for element in scoped_elements
    ]
    return proposal


def load_released_standard(
    standard_version_id: str,
) -> tuple[dict, list[StandardDataElement]]:
    standard_version_id = _uuid_text(
        standard_version_id, "standard_version_id",
    )
    eng = get_engine()
    if eng is None:
        raise RuntimeError("database unavailable")
    with eng.connect() as conn:
        version_row = conn.execute(text("""
            SELECT v.id, v.version_label, v.status, d.id AS document_id,
                   d.doc_code, d.title
              FROM std_document_version v
              JOIN std_document d ON d.id = v.document_id
             WHERE v.id = :version_id
        """), {"version_id": standard_version_id}).mappings().first()
        if version_row is None:
            raise LookupError("standard version not found")
        if version_row["status"] != "released":
            raise ValueError("standard version must be released")
        element_rows = conn.execute(text("""
            SELECT e.id, e.document_version_id, e.code, e.name_zh,
                   e.name_en, e.definition, e.representation_class,
                   e.datatype, e.unit, e.obligation, e.bound_table,
                   e.bound_column,
                   e.embedding,
                   COALESCE(t.aliases, ARRAY[]::TEXT[]) AS aliases
              FROM std_data_element e
              LEFT JOIN std_term t ON t.id = e.term_id
             WHERE e.document_version_id = :version_id
             ORDER BY e.code
        """), {"version_id": standard_version_id}).mappings().all()
    version = {
        "version_id": str(version_row["id"]),
        "document_id": str(version_row["document_id"]),
        "doc_code": version_row["doc_code"],
        "title": version_row["title"],
        "version_label": version_row["version_label"],
        "status": version_row["status"],
    }
    return version, [
        StandardDataElement(
            id=str(row["id"]),
            document_version_id=str(row["document_version_id"]),
            code=row["code"],
            name_zh=row["name_zh"],
            name_en=row["name_en"] or "",
            definition=row["definition"] or "",
            representation_class=row["representation_class"] or "",
            datatype=row["datatype"] or "",
            unit=row["unit"] or "",
            obligation=row["obligation"],
            bound_table=row["bound_table"] or "",
            bound_column=row["bound_column"] or "",
            aliases=tuple(row["aliases"] or ()),
            embedding=_embedding_tuple(row["embedding"]),
        )
        for row in element_rows
    ]


def confirm_virtual_source_mapping(
    *,
    source_id: int,
    owner_username: str,
    standard_version_id: str,
    source_profile_hash: str | None,
    schema_mapping: dict[str, str],
    field_bindings: Sequence[dict[str, Any]],
    confirmed_by: str,
    source_fields: Sequence[str] | None = None,
    review_decisions: Sequence[dict[str, Any]] | None = None,
    target_table: str | None = None,
) -> dict:
    """Atomically confirm a version-bound rename contract and apply it.

    Target names and data-element ownership are reloaded from PostgreSQL; the
    client cannot bind an element from a different standard version or invent
    a target column. This confirms a mapping artifact, not a DataProductVersion.
    """
    if not schema_mapping:
        raise ValueError("schema_mapping must not be empty")
    if not field_bindings:
        raise ValueError("field_bindings must not be empty")
    standard_version_id = _uuid_text(
        standard_version_id, "standard_version_id",
    )
    if source_profile_hash is not None and not re.fullmatch(
        r"[0-9a-f]{64}", source_profile_hash,
    ):
        raise ValueError("source_profile_hash must be a lowercase SHA-256 digest")
    normalized = _normalize_bindings(field_bindings)
    if set(schema_mapping) != {item["source_field"] for item in normalized}:
        raise ValueError("schema_mapping keys must match field_bindings source fields")

    normalized_target_table = str(target_table or "").strip() or None
    if review_decisions is not None:
        if not isinstance(review_decisions, (list, tuple)):
            raise ValueError("review_decisions must be an array")
        if not isinstance(source_fields, (list, tuple)):
            raise ValueError("source_fields are required with review_decisions")
    eng = get_engine()
    if eng is None:
        raise RuntimeError("database unavailable")
    source_ref = str(source_id)
    with eng.begin() as conn:
        _inject_user_context(conn)
        source = conn.execute(text(f"""
            SELECT id FROM {T_VIRTUAL_SOURCES}
             WHERE id = :source_id AND owner_username = :owner
               AND owner_username = current_setting('app.current_user', true)
             FOR UPDATE
        """), {
            "source_id": source_id,
            "owner": owner_username,
        }).first()
        if source is None:
            raise LookupError("virtual source not found or not owned by user")

        version_status = conn.execute(text("""
            SELECT status FROM std_document_version
             WHERE id = :version_id FOR SHARE
        """), {"version_id": standard_version_id}).scalar()
        if version_status is None:
            raise LookupError("standard version not found")
        if version_status != "released":
            raise ValueError("standard version must be released")

        target_ids = [item["target_data_element_id"] for item in normalized]
        rows = conn.execute(text("""
            SELECT id, document_version_id, code, name_zh, name_en,
                   definition, representation_class, datatype, unit,
                   obligation, bound_table, bound_column
              FROM std_data_element
             WHERE document_version_id = :version_id
               AND id = ANY(CAST(:target_ids AS uuid[]))
        """), {
            "version_id": standard_version_id,
            "target_ids": target_ids,
        }).mappings().all()
        target_by_id = {str(row["id"]): dict(row) for row in rows}
        if set(target_by_id) != set(target_ids):
            raise ValueError("all target data elements must belong to the standard version")
        if normalized_target_table and any(
            (row["bound_table"] or "").casefold()
            != normalized_target_table.casefold()
            for row in rows
        ):
            raise ValueError("all target data elements must belong to target_table")

        trusted_bindings = []
        for item in normalized:
            target = target_by_id[item["target_data_element_id"]]
            target_field = (target["bound_column"] or target["code"]).strip()
            if schema_mapping[item["source_field"]] != target_field:
                raise ValueError(
                    f"target field mismatch for {item['source_field']}: expected {target_field}"
                )
            trusted_bindings.append({**item, "target_field": target_field})
        if len({item["target_field"] for item in trusted_bindings}) != len(trusted_bindings):
            raise ValueError("multiple source fields cannot target the same field")

        if review_decisions is not None:
            mandatory_rows = conn.execute(text("""
                SELECT id, document_version_id, code, name_zh, name_en,
                       definition, representation_class, datatype, unit,
                       obligation, bound_table, bound_column
                  FROM std_data_element
                 WHERE document_version_id = :version_id
                   AND bound_table = :target_table
                   AND obligation = 'mandatory'
                 ORDER BY code
            """), {
                "version_id": standard_version_id,
                "target_table": normalized_target_table,
            }).mappings().all() if normalized_target_table else []
            mandatory_elements = [
                _standard_element_from_row(row) for row in mandatory_rows
            ]
            quality_gate = evaluate_mapping_quality_gate(
                source_fields=source_fields or (),
                field_bindings=trusted_bindings,
                review_decisions=review_decisions,
                mandatory_elements=mandatory_elements,
                source_profile_hash=source_profile_hash,
                target_table=normalized_target_table,
            )
        else:
            quality_gate = {
                "schema": "gis-data-agent.standard-mapping-quality-gate.v1",
                "status": "not_evaluated",
                "checks": [],
                "summary": {},
                "missing_mandatory_elements": [],
                "review_decisions": [],
                "target_table": normalized_target_table,
            }
        publication = mapping_publication_status(quality_gate)

        mapping_hash = _mapping_hash(
            source_ref=source_ref,
            standard_version_id=standard_version_id,
            source_profile_hash=source_profile_hash,
            bindings=trusted_bindings,
            review_decisions=quality_gate["review_decisions"] or None,
            target_table=normalized_target_table,
        )
        existing = conn.execute(text("""
            SELECT id FROM std_application_mapping_contract
             WHERE source_kind = 'virtual_source'
               AND source_ref = :source_ref
               AND mapping_hash = :mapping_hash
             FOR UPDATE
        """), {
            "source_ref": source_ref,
            "mapping_hash": mapping_hash,
        }).first()

        conn.execute(text("""
            UPDATE std_application_mapping_contract
               SET status = 'superseded', superseded_at = now()
             WHERE source_kind = 'virtual_source'
               AND source_ref = :source_ref
               AND status = 'confirmed'
               AND (:existing_id IS NULL OR id <> CAST(:existing_id AS uuid))
        """), {
            "source_ref": source_ref,
            "existing_id": str(existing[0]) if existing else None,
        })

        if existing:
            contract_id = str(existing[0])
            conn.execute(text("""
                UPDATE std_application_mapping_contract
                   SET status = 'confirmed', confirmed_by = :confirmed_by,
                       confirmed_at = now(), superseded_at = NULL
                 WHERE id = :contract_id
            """), {
                "contract_id": contract_id,
                "confirmed_by": confirmed_by,
            })
            idempotent = True
        else:
            contract_id = str(uuid.uuid4())
            conn.execute(text("""
                INSERT INTO std_application_mapping_contract (
                    id, source_kind, source_ref, source_snapshot_hash,
                    standard_version_id, status, mapping_hash,
                    created_by, confirmed_by, confirmed_at, metadata)
                VALUES (
                    :id, 'virtual_source', :source_ref, :source_snapshot_hash,
                    :version_id, 'confirmed', :mapping_hash,
                    :created_by, :confirmed_by, now(),
                    CAST(:metadata AS jsonb))
            """), {
                "id": contract_id,
                "source_ref": source_ref,
                "source_snapshot_hash": source_profile_hash,
                "version_id": standard_version_id,
                "mapping_hash": mapping_hash,
                "created_by": confirmed_by,
                "confirmed_by": confirmed_by,
                "metadata": json.dumps({
                    "schema": "gis-data-agent.standard-mapping-contract.v1",
                    "execution_scope": "rename_only",
                    "authoritative_write": False,
                    "target_table": normalized_target_table,
                    "quality_gate": quality_gate,
                    "publication": publication,
                }),
            })
            for item in trusted_bindings:
                conn.execute(text("""
                    INSERT INTO std_application_field_mapping (
                        contract_id, standard_version_id, source_field,
                        target_data_element_id, target_field, confidence,
                        match_method, evidence, transform_spec)
                    VALUES (
                        :contract_id, :version_id, :source_field,
                        :target_id, :target_field, :confidence,
                        :match_method, CAST(:evidence AS jsonb),
                        CAST(:transform_spec AS jsonb))
                """), {
                    "contract_id": contract_id,
                    "version_id": standard_version_id,
                    "source_field": item["source_field"],
                    "target_id": item["target_data_element_id"],
                    "target_field": item["target_field"],
                    "confidence": item["confidence"],
                    "match_method": item["match_method"],
                    "evidence": json.dumps(item["evidence"], ensure_ascii=False),
                    "transform_spec": json.dumps({"operation": "rename"}),
                })
            idempotent = False

        conn.execute(text(f"""
            UPDATE {T_VIRTUAL_SOURCES}
               SET schema_mapping = CAST(:mapping AS jsonb), updated_at = now()
             WHERE id = :source_id AND owner_username = :owner
        """), {
            "mapping": json.dumps(schema_mapping, ensure_ascii=False),
            "source_id": source_id,
            "owner": owner_username,
        })
    return {
        "contract_id": contract_id,
        "status": "confirmed",
        "mapping_hash": mapping_hash,
        "mapping_count": len(schema_mapping),
        "standard_version_id": standard_version_id,
        "source_profile_hash": source_profile_hash,
        "idempotent": idempotent,
        "execution_scope": "rename_only",
        "quality_gate": quality_gate,
        "publication": publication,
    }


def load_confirmed_virtual_source_mapping(
    *, source_id: int, owner_username: str,
) -> dict:
    """Load the current confirmed mapping as input to a read-only check."""
    eng = get_engine()
    if eng is None:
        raise RuntimeError("database unavailable")
    with eng.connect() as conn:
        _inject_user_context(conn)
        owned = conn.execute(text(f"""
            SELECT id FROM {T_VIRTUAL_SOURCES}
             WHERE id = :source_id AND owner_username = :owner
               AND owner_username = current_setting('app.current_user', true)
        """), {
            "source_id": source_id,
            "owner": owner_username,
        }).first()
        if owned is None:
            raise LookupError("virtual source not found or not owned by user")
        contract = conn.execute(text("""
            SELECT id, mapping_hash, source_snapshot_hash,
                   standard_version_id, metadata
              FROM std_application_mapping_contract
             WHERE source_kind = 'virtual_source'
               AND source_ref = :source_ref
               AND status = 'confirmed'
        """), {"source_ref": str(source_id)}).mappings().first()
        if contract is None:
            raise LookupError("confirmed standard mapping contract not found")
        rows = conn.execute(text("""
            SELECT fm.source_field, fm.target_data_element_id,
                   fm.target_field, e.datatype, e.representation_class,
                   e.obligation
              FROM std_application_field_mapping fm
              JOIN std_data_element e
                ON e.id = fm.target_data_element_id
               AND e.document_version_id = fm.standard_version_id
             WHERE fm.contract_id = :contract_id
             ORDER BY fm.source_field
        """), {"contract_id": str(contract["id"])}).mappings().all()

    metadata = contract["metadata"] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    quality_gate = metadata.get("quality_gate") or {}
    if quality_gate.get("status") != "passed":
        raise ValueError("standard mapping quality gate must pass before preflight")
    return {
        "contract_id": str(contract["id"]),
        "mapping_hash": contract["mapping_hash"],
        "source_snapshot_hash": contract["source_snapshot_hash"],
        "standard_version_id": str(contract["standard_version_id"]),
        "target_table": metadata.get("target_table"),
        "field_bindings": [dict(row) for row in rows],
    }


def _get_embeddings(texts: list[str]) -> list[list[float]]:
    from ...embedding_gateway import get_embeddings
    return get_embeddings(texts)


def _embedding_tuple(value: Any) -> tuple[float, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ()
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return ()


def _standard_element_from_row(row: Any) -> StandardDataElement:
    return StandardDataElement(
        id=str(row["id"]),
        document_version_id=str(row["document_version_id"]),
        code=row["code"],
        name_zh=row["name_zh"],
        name_en=row["name_en"] or "",
        definition=row["definition"] or "",
        representation_class=row["representation_class"] or "",
        datatype=row["datatype"] or "",
        unit=row["unit"] or "",
        obligation=row["obligation"],
        bound_table=row["bound_table"] or "",
        bound_column=row["bound_column"] or "",
    )


def _normalize_bindings(field_bindings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    source_fields: set[str] = set()
    target_ids: set[str] = set()
    for raw in field_bindings:
        if not isinstance(raw, dict):
            raise ValueError("each field binding must be an object")
        source_field = str(raw.get("source_field") or "").strip()
        raw_target_id = str(raw.get("target_data_element_id") or "").strip()
        target_id = _uuid_text(raw_target_id, "target_data_element_id")
        if not source_field or not target_id:
            raise ValueError("source_field and target_data_element_id are required")
        if source_field in source_fields:
            raise ValueError(f"duplicate source field: {source_field}")
        if target_id in target_ids:
            raise ValueError("multiple source fields cannot target the same data element")
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be numeric") from exc
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        evidence = raw.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise ValueError("evidence must be an object")
        source_fields.add(source_field)
        target_ids.add(target_id)
        normalized.append({
            "source_field": source_field,
            "target_data_element_id": target_id,
            "confidence": confidence,
            "match_method": str(raw.get("match_method") or "human_confirmed"),
            "evidence": evidence,
        })
    return sorted(normalized, key=lambda item: item["source_field"])


def _uuid_text(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _mapping_hash(
    *,
    source_ref: str,
    standard_version_id: str,
    source_profile_hash: str | None,
    bindings: Sequence[dict[str, Any]],
    review_decisions: Sequence[dict[str, Any]] | None = None,
    target_table: str | None = None,
) -> str:
    payload = {
        "schema": "gis-data-agent.standard-mapping-contract.v1",
        "source_kind": "virtual_source",
        "source_ref": source_ref,
        "source_profile_hash": source_profile_hash,
        "standard_version_id": standard_version_id,
        "bindings": [
            {
                "source_field": item["source_field"],
                "target_data_element_id": item["target_data_element_id"],
                "target_field": item["target_field"],
                "transform": "rename",
            }
            for item in bindings
        ],
    }
    if review_decisions is not None:
        payload["review_decisions"] = list(review_decisions)
        payload["target_table"] = target_table
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
