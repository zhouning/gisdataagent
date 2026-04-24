"""Semantic Drafting — auto-generate semantic metadata drafts from dataset profiles.

Uses LLM (Gemini Flash) to infer display names, aliases, semantic domains,
join candidates, and risk flags from raw schema + sample values.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)

_KNOWN_DOMAINS = {
    "id": "ID", "name": "NAME", "address": "ADDRESS",
    "area": "AREA", "length": "LENGTH", "perimeter": "PERIMETER",
    "category": "CATEGORY", "type": "CATEGORY",
    "lat": "LATITUDE", "lng": "LONGITUDE", "lon": "LONGITUDE",
    "longitude": "LONGITUDE", "latitude": "LATITUDE",
    "elevation": "ELEVATION", "height": "HEIGHT",
    "population": "POPULATION", "code": "CODE",
    "date": "TEMPORAL", "time": "TEMPORAL", "year": "TEMPORAL",
}


def _infer_domain(col_name: str) -> Optional[str]:
    """Rule-based domain inference from column name."""
    import re as _re
    lower = col_name.lower()
    # Exact match first
    if lower in _KNOWN_DOMAINS:
        return _KNOWN_DOMAINS[lower]
    # Word-boundary match for longer patterns (avoid "lat" matching "population")
    for pattern, domain in _KNOWN_DOMAINS.items():
        if len(pattern) >= 4 and _re.search(r'\b' + _re.escape(pattern) + r'\b', lower):
            return domain
        if len(pattern) >= 4 and lower.startswith(pattern) or lower.endswith(pattern):
            return domain
    return None


def _needs_quoting(col_name: str) -> bool:
    if not col_name:
        return False
    if col_name.lower() != col_name:
        return True
    if col_name in {"user", "select", "group", "order", "where", "table", "from"}:
        return True
    return False


def _generate_aliases_rule_based(col_name: str, col_comment: str, data_type: str) -> list[str]:
    """Generate candidate aliases from column name, comment, and type."""
    aliases = []
    if col_comment:
        aliases.append(col_comment.strip())
    if col_name != col_name.lower():
        aliases.append(col_name)
    parts = re.split(r'[_\-]', col_name)
    if len(parts) > 1:
        aliases.append(" ".join(parts))
    return list(dict.fromkeys(aliases))[:5]


def generate_draft(profile_id: int, use_llm: bool = True) -> Optional[dict]:
    """Generate a semantic draft for a dataset profile.

    Args:
        profile_id: ID of the dataset profile to draft.
        use_llm: If True, use Gemini Flash to enhance aliases and descriptions.

    Returns:
        Draft dict or None on failure.
    """
    engine = get_engine()
    if not engine:
        return None

    with engine.begin() as conn:
        profile = conn.execute(text(
            "SELECT id, table_name, schema_name, row_count, geometry_type, srid, "
            "columns_json, sample_values, table_comment, risk_tags, primary_key_candidates "
            "FROM agent_dataset_profiles WHERE id = :pid"
        ), {"pid": profile_id}).fetchone()
        if not profile:
            return None

        pid, table_name, schema_name, row_count, geom_type, srid, \
            columns_raw, samples_raw, table_comment, risks_raw, pks_raw = profile

        columns = json.loads(columns_raw) if isinstance(columns_raw, str) else columns_raw
        samples = json.loads(samples_raw) if isinstance(samples_raw, str) else (samples_raw or {})
        risks = json.loads(risks_raw) if isinstance(risks_raw, str) else (risks_raw or [])

        # Rule-based draft
        columns_draft = []
        for col in columns:
            cn = col["column_name"]
            dt = col.get("data_type", "")
            udt = col.get("udt_name", "")
            comment = col.get("comment", "")
            is_geom = udt in ("geometry", "geography")

            domain = _infer_domain(cn)
            aliases = _generate_aliases_rule_based(cn, comment, dt)

            columns_draft.append({
                "column_name": cn,
                "data_type": dt,
                "udt_name": udt,
                "semantic_domain": domain,
                "aliases": aliases,
                "is_geometry": is_geom,
                "needs_quoting": _needs_quoting(cn),
                "description": comment or "",
                "sample_values": samples.get(cn, []),
            })

        display_name = table_comment or table_name
        description = f"Table {table_name}"
        if geom_type:
            description += f" ({geom_type}, SRID={srid})"
        if row_count:
            description += f", ~{row_count} rows"

        # Join candidates: find tables with matching column names
        join_candidates = _find_join_candidates(conn, table_name, columns)

        # LLM enhancement
        confidence = 0.5
        if use_llm:
            llm_result = _enhance_with_llm(table_name, display_name, columns_draft, samples, geom_type)
            if llm_result:
                display_name = llm_result.get("display_name", display_name)
                description = llm_result.get("description", description)
                for cd in columns_draft:
                    llm_col = llm_result.get("columns", {}).get(cd["column_name"])
                    if llm_col:
                        if llm_col.get("aliases"):
                            existing = set(cd["aliases"])
                            cd["aliases"].extend(a for a in llm_col["aliases"] if a not in existing)
                        if llm_col.get("description") and not cd["description"]:
                            cd["description"] = llm_col["description"]
                        if llm_col.get("semantic_domain") and not cd["semantic_domain"]:
                            cd["semantic_domain"] = llm_col["semantic_domain"]
                confidence = 0.8

        # Check existing version
        existing = conn.execute(text(
            "SELECT COALESCE(MAX(version), 0) FROM agent_semantic_drafts WHERE profile_id = :pid"
        ), {"pid": profile_id}).scalar()
        new_version = (existing or 0) + 1

        # Insert draft
        conn.execute(text("""
            INSERT INTO agent_semantic_drafts
                (profile_id, table_name, version, display_name, description,
                 aliases_json, columns_draft, join_candidates, risk_flags,
                 confidence, status)
            VALUES (:pid, :tbl, :ver, :dn, :desc,
                    CAST(:aliases AS jsonb), CAST(:cols AS jsonb), CAST(:joins AS jsonb), CAST(:risks AS jsonb),
                    :conf, 'drafted')
        """), {
            "pid": profile_id, "tbl": table_name, "ver": new_version,
            "dn": display_name, "desc": description,
            "aliases": json.dumps([display_name, table_name], ensure_ascii=False),
            "cols": json.dumps(columns_draft, ensure_ascii=False),
            "joins": json.dumps(join_candidates, ensure_ascii=False),
            "risks": json.dumps(risks, ensure_ascii=False),
            "conf": confidence,
        })

        # Transition profile status
        conn.execute(text(
            "UPDATE agent_dataset_profiles SET status = 'drafted', updated_at = NOW() WHERE id = :pid"
        ), {"pid": profile_id})

    return {
        "status": "ok",
        "profile_id": profile_id,
        "table_name": table_name,
        "version": new_version,
        "display_name": display_name,
        "columns_count": len(columns_draft),
        "join_candidates": len(join_candidates),
        "confidence": confidence,
    }


def _find_join_candidates(conn, table_name: str, columns: list) -> list[dict]:
    """Find potential join targets by matching column names across tables."""
    col_names = {c["column_name"].lower() for c in columns
                 if c.get("udt_name") not in ("geometry", "geography")}
    candidates = []
    try:
        other_tables = conn.execute(text("""
            SELECT DISTINCT table_name FROM agent_dataset_profiles
            WHERE table_name != :tbl AND status != 'discovered'
        """), {"tbl": table_name}).fetchall()
        for (other_tbl,) in other_tables:
            other_cols_raw = conn.execute(text(
                "SELECT columns_json FROM agent_dataset_profiles WHERE table_name = :t ORDER BY id DESC LIMIT 1"
            ), {"t": other_tbl}).fetchone()
            if not other_cols_raw:
                continue
            other_cols = json.loads(other_cols_raw[0]) if isinstance(other_cols_raw[0], str) else other_cols_raw[0]
            other_names = {c["column_name"].lower() for c in other_cols
                          if c.get("udt_name") not in ("geometry", "geography")}
            shared = col_names & other_names
            if shared:
                candidates.append({
                    "target_table": other_tbl,
                    "shared_columns": list(shared),
                    "join_type": "attribute",
                })
            # Spatial join candidate
            has_geom_self = any(c.get("udt_name") in ("geometry", "geography") for c in columns)
            has_geom_other = any(c.get("udt_name") in ("geometry", "geography") for c in other_cols)
            if has_geom_self and has_geom_other:
                candidates.append({
                    "target_table": other_tbl,
                    "shared_columns": ["geometry"],
                    "join_type": "spatial",
                })
    except Exception as e:
        logger.debug("Join candidate search failed: %s", e)
    return candidates


def _enhance_with_llm(table_name: str, display_name: str,
                      columns_draft: list, samples: dict,
                      geom_type: Optional[str]) -> Optional[dict]:
    """Use Gemini Flash to enhance semantic metadata."""
    col_summary = []
    for c in columns_draft[:20]:
        sv = c.get("sample_values", [])[:3]
        sv_str = ", ".join(str(v) for v in sv) if sv else "N/A"
        col_summary.append(f"  {c['column_name']} ({c['data_type']}): samples=[{sv_str}]")

    prompt = (
        "你是数据目录专家。根据以下表结构和样例值，生成语义元数据。\n\n"
        f"表名: {table_name}\n"
        f"几何类型: {geom_type or '无'}\n"
        f"字段:\n" + "\n".join(col_summary) + "\n\n"
        "请输出 JSON（不要 markdown 代码块），格式如下：\n"
        '{"display_name": "中文显示名", "description": "一句话描述",\n'
        ' "columns": {"col_name": {"aliases": ["别名1","别名2"], '
        '"description": "字段描述", "semantic_domain": "AREA|NAME|ID|..."}}}\n'
        "只输出 JSON，不要解释。"
    )
    try:
        from .llm_client import generate_text, strip_fences
        raw = generate_text(prompt, tier="fast", timeout_ms=20_000)
        raw = strip_fences(raw)
        return json.loads(raw)
    except Exception as e:
        logger.debug("LLM enhancement failed: %s", e)
        return None


def get_draft(table_name: str, version: Optional[int] = None) -> Optional[dict]:
    """Get a semantic draft for a table."""
    engine = get_engine()
    if not engine:
        return None
    with engine.connect() as conn:
        if version:
            row = conn.execute(text(
                "SELECT * FROM agent_semantic_drafts WHERE table_name = :t AND version = :v"
            ), {"t": table_name, "v": version}).fetchone()
        else:
            row = conn.execute(text(
                "SELECT * FROM agent_semantic_drafts WHERE table_name = :t ORDER BY version DESC LIMIT 1"
            ), {"t": table_name}).fetchone()
        if not row:
            return None
        keys = row._fields if hasattr(row, '_fields') else row.keys()
        return dict(zip(keys, row))
