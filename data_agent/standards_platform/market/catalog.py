"""Released standards market catalog and deterministic version diff."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine
from .listings import ensure_listing_table


ASSET_TYPES = ("clauses", "data_elements", "terms", "value_domains")
ZERO_COUNTS = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}


def list_market_standards(
    *, query: str | None = None, limit: int = 50, offset: int = 0,
    viewer_user_id: str | None = None, viewer_role: str | None = None,
    viewer_org_id: str | None = None,
) -> dict[str, Any]:
    """Return released standards as market catalog items."""
    ensure_listing_table()
    where = [
        "v.status = 'released'",
        "(l.id IS NULL OR l.status = 'approved')",
        """(
            l.id IS NULL
            OR l.visibility_scope = 'public'
            OR :viewer_is_admin
            OR (
                l.visibility_scope = 'organization'
                AND :viewer_org_id IS NOT NULL
                AND (
                    l.owner_org_id = :viewer_org_id
                    OR :viewer_org_id = ANY(COALESCE(l.allowed_org_ids, ARRAY[]::TEXT[]))
                )
            )
            OR (
                l.visibility_scope = 'private'
                AND :viewer_user_id IS NOT NULL
                AND (
                    d.owner_user_id = :viewer_user_id
                    OR l.submitted_by = :viewer_user_id
                )
            )
        )""",
    ]
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "viewer_user_id": viewer_user_id,
        "viewer_org_id": viewer_org_id,
        "viewer_is_admin": viewer_role == "admin",
    }
    normalized = (query or "").strip()
    if normalized:
        where.append(
            "(d.doc_code ILIKE :q OR d.title ILIKE :q "
            "OR v.version_label ILIKE :q)"
        )
        params["q"] = f"%{normalized}%"
    where_sql = " AND ".join(where)
    eng = get_engine()
    with eng.connect() as conn:
        total = conn.execute(text(f"""
            SELECT count(*)
              FROM std_document_version v
              JOIN std_document d ON d.id = v.document_id
              LEFT JOIN std_market_listing l ON l.version_id = v.id
             WHERE {where_sql}
        """), params).scalar() or 0
        rows = conn.execute(text(f"""
            SELECT v.id AS version_id,
                   v.document_id,
                   d.doc_code,
                   d.title,
                   d.source_type,
                   d.owner_user_id,
                   d.tags,
                   v.version_label,
                   v.released_at,
                   v.updated_by AS released_by,
                   v.supersedes_version_id,
                   l.id AS market_listing_id,
                   COALESCE(l.status, 'legacy_approved') AS market_status,
                   COALESCE(l.visibility_scope, 'public') AS visibility_scope,
                   l.owner_org_id,
                   l.allowed_org_ids,
                   l.submitted_by AS market_submitted_by,
                   l.submitted_at AS market_submitted_at,
                   l.reviewed_by AS market_reviewed_by,
                   l.reviewed_at AS market_reviewed_at,
                   (SELECT count(*) FROM std_clause c
                     WHERE c.document_version_id = v.id) AS clauses,
                   (SELECT count(*) FROM std_data_element e
                     WHERE e.document_version_id = v.id) AS data_elements,
                   (SELECT count(*) FROM std_term t
                     WHERE t.document_version_id = v.id) AS terms,
                   (SELECT count(*) FROM std_value_domain vd
                     WHERE vd.document_version_id = v.id) AS value_domains
              FROM std_document_version v
              JOIN std_document d ON d.id = v.document_id
              LEFT JOIN std_market_listing l ON l.version_id = v.id
             WHERE {where_sql}
             ORDER BY v.released_at DESC NULLS LAST, d.doc_code, v.version_label
             LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return {
        "items": [_market_item(dict(row)) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


def version_diff(source_version_id: str, target_version_id: str) -> dict[str, Any]:
    """Return a deterministic structural diff between two standard versions."""
    eng = get_engine()
    with eng.connect() as conn:
        source = _version_meta(conn, source_version_id)
        target = _version_meta(conn, target_version_id)
        if source is None or target is None:
            raise LookupError("version not found")

        source_assets = _version_assets(conn, source_version_id)
        target_assets = _version_assets(conn, target_version_id)

    changes: list[dict[str, Any]] = []
    by_asset_type: dict[str, dict[str, int]] = {}
    for asset_type in ASSET_TYPES:
        counts, asset_changes = _diff_asset_maps(
            asset_type,
            source_assets[asset_type],
            target_assets[asset_type],
        )
        by_asset_type[asset_type] = counts
        changes.extend(asset_changes)

    summary = {
        "added": sum(v["added"] for v in by_asset_type.values()),
        "removed": sum(v["removed"] for v in by_asset_type.values()),
        "changed": sum(v["changed"] for v in by_asset_type.values()),
        "unchanged": sum(v["unchanged"] for v in by_asset_type.values()),
        "by_asset_type": by_asset_type,
    }
    return {
        "source_version_id": source_version_id,
        "target_version_id": target_version_id,
        "source": source,
        "target": target,
        "summary": summary,
        "changes": changes,
    }


def _market_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "version_id": str(row["version_id"]),
        "document_id": str(row["document_id"]),
        "doc_code": row["doc_code"],
        "title": row["title"],
        "source_type": row["source_type"],
        "owner_user_id": row["owner_user_id"],
        "tags": list(row["tags"] or []),
        "version_label": row["version_label"],
        "released_at": (
            row["released_at"].isoformat() if row.get("released_at") else None
        ),
        "released_by": row.get("released_by"),
        "supersedes_version_id": (
            str(row["supersedes_version_id"])
            if row.get("supersedes_version_id") else None
        ),
        "market_listing_id": (
            str(row["market_listing_id"])
            if row.get("market_listing_id") else None
        ),
        "market_status": row.get("market_status") or "legacy_approved",
        "visibility_scope": row.get("visibility_scope") or "public",
        "owner_org_id": row.get("owner_org_id"),
        "allowed_org_ids": list(row.get("allowed_org_ids") or []),
        "market_submitted_by": row.get("market_submitted_by"),
        "market_submitted_at": (
            row["market_submitted_at"].isoformat()
            if row.get("market_submitted_at") else None
        ),
        "market_reviewed_by": row.get("market_reviewed_by"),
        "market_reviewed_at": (
            row["market_reviewed_at"].isoformat()
            if row.get("market_reviewed_at") else None
        ),
        "asset_counts": {
            "clauses": int(row["clauses"] or 0),
            "data_elements": int(row["data_elements"] or 0),
            "terms": int(row["terms"] or 0),
            "value_domains": int(row["value_domains"] or 0),
        },
    }


def _version_meta(conn, version_id: str) -> dict[str, Any] | None:
    row = conn.execute(text("""
        SELECT v.id AS version_id,
               v.document_id,
               v.version_label,
               v.status,
               v.released_at,
               d.doc_code,
               d.title,
               d.source_type
          FROM std_document_version v
          JOIN std_document d ON d.id = v.document_id
         WHERE v.id = :v
    """), {"v": version_id}).mappings().first()
    if row is None:
        return None
    return {
        "version_id": str(row["version_id"]),
        "document_id": str(row["document_id"]),
        "version_label": row["version_label"],
        "status": row["status"],
        "released_at": (
            row["released_at"].isoformat() if row.get("released_at") else None
        ),
        "doc_code": row["doc_code"],
        "title": row["title"],
        "source_type": row["source_type"],
    }


def _version_assets(conn, version_id: str) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "clauses": _asset_map(conn.execute(text("""
            SELECT COALESCE(NULLIF(clause_no, ''), ordinal_path::text) AS key,
                   CONCAT(
                       COALESCE(NULLIF(clause_no, ''), ordinal_path::text),
                       CASE WHEN heading IS NULL OR heading = ''
                            THEN '' ELSE CONCAT(' ', heading) END
                   ) AS label,
                   heading,
                   kind,
                   body_md
              FROM std_clause
             WHERE document_version_id = :v
        """), {"v": version_id}).mappings().all()),
        "data_elements": _asset_map(conn.execute(text("""
            SELECT code AS key,
                   CONCAT(code, ' ', name_zh) AS label,
                   name_zh,
                   name_en,
                   definition,
                   representation_class,
                   datatype,
                   unit,
                   obligation,
                   cardinality,
                   data_classification,
                   bound_table,
                   bound_column
              FROM std_data_element
             WHERE document_version_id = :v
        """), {"v": version_id}).mappings().all()),
        "terms": _asset_map(conn.execute(text("""
            SELECT term_code AS key,
                   CONCAT(term_code, ' ', name_zh) AS label,
                   name_zh,
                   name_en,
                   definition,
                   aliases
              FROM std_term
             WHERE document_version_id = :v
        """), {"v": version_id}).mappings().all()),
        "value_domains": _asset_map(conn.execute(text("""
            SELECT code AS key,
                   CONCAT(code, ' ', name) AS label,
                   name,
                   kind
              FROM std_value_domain
             WHERE document_version_id = :v
        """), {"v": version_id}).mappings().all()),
    }


def _asset_map(rows) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        data = dict(row)
        key = str(data.pop("key"))
        label = str(data.pop("label") or key)
        content = {k: _jsonable(v) for k, v in data.items()}
        out[key] = {
            "key": key,
            "label": label,
            "content": content,
            "digest": _digest(content),
        }
    return out


def _diff_asset_maps(
    asset_type: str,
    source: dict[str, dict[str, Any]],
    target: dict[str, dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    counts = dict(ZERO_COUNTS)
    changes: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        source_item = source.get(key)
        target_item = target.get(key)
        if source_item is None:
            change_type = "added"
        elif target_item is None:
            change_type = "removed"
        elif source_item["digest"] != target_item["digest"]:
            change_type = "changed"
        else:
            change_type = "unchanged"
        counts[change_type] += 1
        if change_type != "unchanged":
            changes.append({
                "asset_type": asset_type,
                "key": key,
                "change_type": change_type,
                "source_label": source_item["label"] if source_item else None,
                "target_label": target_item["label"] if target_item else None,
            })
    return counts, changes


def _digest(content: dict[str, Any]) -> str:
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return list(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
