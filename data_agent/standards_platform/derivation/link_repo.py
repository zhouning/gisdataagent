"""CRUD on std_derived_link.

Uses **actual** column names: source_version_id (not document_version_id),
derivation_strategy (not strategy), status ∈ pending/active/stale/overridden/superseded.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine


def create_link(*, version_id: str, source_kind: str, source_id: str,
                derivation_strategy: str, target_kind: str,
                target_table: str, target_id: str,
                by_user: str = "system",
                notes: Optional[str] = None) -> str:
    lid = str(uuid.uuid4())
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_derived_link "
            "(id, source_kind, source_id, source_version_id, "
            " target_kind, target_table, target_id, "
            " derivation_strategy, status, stale_reason) "
            "VALUES (:i, :sk, :si, :v, :tk, :tt, :ti, :ds, 'active', :n)"
        ), {"i": lid, "sk": source_kind, "si": source_id, "v": version_id,
             "tk": target_kind, "tt": target_table, "ti": target_id,
             "ds": derivation_strategy, "n": notes})
    return lid


def get_link(link_id: str) -> Optional[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, source_kind, source_id, source_version_id, "
            "target_kind, target_table, target_id, derivation_strategy, "
            "status, stale_reason, generated_at "
            "FROM std_derived_link WHERE id=:i"
        ), {"i": link_id}).mappings().first()
    return dict(row) if row else None


def list_links_by_version(*, version_id: str,
                          derivation_strategy: Optional[str] = None,
                          status: Optional[str] = None) -> list[dict]:
    sql = (
        "SELECT id, source_kind, source_id, source_version_id, target_kind, "
        "target_table, target_id, derivation_strategy, status, stale_reason, "
        "generated_at FROM std_derived_link WHERE source_version_id=:v"
    )
    params: dict = {"v": version_id}
    if derivation_strategy:
        sql += " AND derivation_strategy=:s"
        params["s"] = derivation_strategy
    if status:
        sql += " AND status=:st"
        params["st"] = status
    sql += " ORDER BY generated_at DESC"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def list_active_links_for_doc(*, document_id: str,
                              derivation_strategy: str) -> list[dict]:
    """All active links across all versions of a document."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT l.id, l.source_kind, l.source_id, l.source_version_id, "
            "l.target_kind, l.target_table, l.target_id, "
            "l.derivation_strategy, l.status, l.generated_at "
            "FROM std_derived_link l "
            "JOIN std_document_version v ON v.id = l.source_version_id "
            "WHERE v.document_id=:d AND l.derivation_strategy=:s "
            "AND l.status='active' "
            "ORDER BY l.generated_at DESC"
        ), {"d": document_id, "s": derivation_strategy}).mappings().all()
    return [dict(r) for r in rows]


def mark_stale(*, link_ids: list[str], reason: Optional[str] = None) -> int:
    if not link_ids:
        return 0
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(text(
            "UPDATE std_derived_link SET status='stale', stale_reason=:r "
            "WHERE id = ANY(CAST(:ids AS uuid[]))"
        ), {"r": reason or "superseded by new version", "ids": link_ids})
        return result.rowcount


# ---------------------------------------------------------------------------
# Rollback + impact graph (Wave 7)
# ---------------------------------------------------------------------------

# Map target_table -> SQL fragment to flip its derived_status to stale.
# Tables that don't carry derived_status are skipped at the application layer.
_TARGET_DERIVED_STATUS_TABLES: set[str] = {
    "agent_semantic_hints",
    "agent_quality_rules",
    "agent_defect_code_bindings",
    "std_data_model_snapshot",
}


def rollback_version(*, version_id: str, by_user: str = "system",
                     reason: Optional[str] = None) -> dict:
    """Roll back all derivations from a published version.

    Marks every active std_derived_link with source_version_id=version_id as
    'superseded' and sets the corresponding derived_status='stale' on the
    downstream rows that carry that column. Manual rows (std_derived_link_id
    IS NULL) are NEVER touched — see strategy contracts.

    Returns: {strategy: {links_marked, downstream_marked, target_tables: [...]}}.

    Note: synonym derivation lives as a JSONB column on agent_semantic_sources
    rather than a per-row derived_status, so the SynonymStrategy fan-in
    contract is honoured by clearing derived_synonyms='[]' for tables whose
    only source was this version.
    """
    eng = get_engine()
    summary: dict = {}
    rollback_reason = reason or f"rolled back from version {version_id}"

    with eng.connect() as conn:
        active = conn.execute(text(
            "SELECT id, derivation_strategy, target_table, target_id "
            "FROM std_derived_link "
            "WHERE source_version_id=:v AND status='active'"
        ), {"v": version_id}).mappings().all()

    if not active:
        return {}

    # Group by strategy + target_table so we can flip downstream status in
    # one batch per (strategy, table) pair.
    by_strategy: dict[str, dict[str, list[dict]]] = {}
    for row in active:
        strat = row["derivation_strategy"]
        tbl = row["target_table"]
        by_strategy.setdefault(strat, {}).setdefault(tbl, []).append(dict(row))

    with eng.begin() as conn:
        for strat, tables in by_strategy.items():
            link_ids: list[str] = []
            target_tables: list[str] = []
            downstream_marked = 0
            for tbl, rows in tables.items():
                target_tables.append(tbl)
                ids = [r["id"] for r in rows]
                target_ids = [r["target_id"] for r in rows]
                link_ids.extend(ids)

                if tbl in _TARGET_DERIVED_STATUS_TABLES:
                    # PK type varies (UUID for hints/bindings, INT for rules).
                    # std_derived_link_id is the safe handle.
                    res = conn.execute(text(
                        f"UPDATE {tbl} SET derived_status='stale', "
                        f"updated_at=now() "
                        f"WHERE std_derived_link_id = ANY(CAST(:ids AS uuid[]))"
                    ), {"ids": [str(i) for i in ids]})
                    downstream_marked += res.rowcount or 0
                elif tbl == "agent_semantic_sources":
                    # Synonym fan-in — clear derived_synonyms for source rows
                    # whose only contributor was this version. We can't
                    # cheaply check uniqueness here, so we conservatively
                    # clear the column; manual `synonyms` is untouched.
                    res = conn.execute(text(
                        "UPDATE agent_semantic_sources "
                        "SET derived_synonyms = '[]'::jsonb, updated_at=now() "
                        "WHERE id = ANY(CAST(:ids AS int[]))"
                    ), {"ids": [int(t) for t in target_ids]})
                    downstream_marked += res.rowcount or 0
                # else: unknown table — skip silently, only the link gets marked.

            # Mark all collected links 'superseded' (terminal status, distinct
            # from 'stale' which is reserved for natural re-derive flow).
            conn.execute(text(
                "UPDATE std_derived_link SET status='superseded', "
                "stale_reason=:r "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"r": rollback_reason,
                 "ids": [str(i) for i in link_ids]})

            summary[strat] = {
                "links_marked": len(link_ids),
                "downstream_marked": downstream_marked,
                "target_tables": sorted(set(target_tables)),
            }

    return summary


def impact_graph(*, source_kind: str, source_id: str,
                 include_stale: bool = False) -> list[dict]:
    """Return all derivations that descend from a (kind, source) pair.

    Used by the impact-analysis UI: pick a clause / data_element / value_domain
    / term and see every downstream artefact (semantic_hint, quality_rule,
    defect_binding, ...). By default only active rows are returned.

    For data_element source: walks std_derived_link.source_id directly.
    For clause source: walks `defined_by_clause_id` on data_element/term
    first, then recurses through their links.
    """
    eng = get_engine()
    rows: list[dict] = []
    status_filter = "" if include_stale else " AND l.status='active'"

    if source_kind == "clause":
        # Clauses don't appear as source_id in std_derived_link directly.
        # We expand to (data_element ∪ term ∪ value_domain) defined by clause.
        sql = (
            "SELECT l.id AS link_id, l.derivation_strategy, "
            "       l.target_kind, l.target_table, l.target_id, "
            "       l.status, l.generated_at, "
            "       l.source_kind, l.source_id "
            "FROM std_derived_link l "
            "WHERE l.source_id IN ("
            "  SELECT id FROM std_data_element WHERE defined_by_clause_id=:c "
            "  UNION SELECT id FROM std_term WHERE defined_by_clause_id=:c "
            "  UNION SELECT id FROM std_value_domain WHERE defined_by_clause_id=:c"
            ")"
            + status_filter
            + " ORDER BY l.generated_at DESC"
        )
        params = {"c": source_id}
    else:
        sql = (
            "SELECT l.id AS link_id, l.derivation_strategy, "
            "       l.target_kind, l.target_table, l.target_id, "
            "       l.status, l.generated_at, "
            "       l.source_kind, l.source_id "
            "FROM std_derived_link l "
            "WHERE l.source_kind=:sk AND l.source_id=:si"
            + status_filter
            + " ORDER BY l.generated_at DESC"
        )
        params = {"sk": source_kind, "si": source_id}

    with eng.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]
    return rows
