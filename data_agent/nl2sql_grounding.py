"""NL2SQL grounding: semantic resolution + schema assembly + few-shot formatting."""
from __future__ import annotations

import json
import logging
import os
import re
from difflib import SequenceMatcher

from .reference_queries import fetch_nl2sql_few_shots
from .semantic_model import SemanticModelStore
from .nl2sql_intent import classify_intent, IntentLabel

logger = logging.getLogger(__name__)

_COMPLEX_FEWSHOT_HINTS = (
    "面积", "距离", "交集", "相交", "缓冲", "占比", "最近", "前10", "前5", "排序", "联合", "周边"
)


def _should_fetch_few_shots(user_text: str, candidate_tables: list, semantic: dict) -> bool:
    """Decide when the paper's embedding-based few-shot stage should run.

    English warehouse prompts keep the historical complex-query gate. Chinese
    GIS/business prompts are retrieved whenever governed candidates exist,
    because their spatial intent is often not emitted as ST_* hints until the
    LLM grounding stage.
    """
    spatial_query = bool(semantic.get("spatial_ops") or semantic.get("region_filter"))
    complex_text = any(h in user_text for h in _COMPLEX_FEWSHOT_HINTS)
    if (
        not spatial_query
        and not complex_text
        and not _contains_cjk_text(user_text)
        and os.environ.get("GDA_NL2SQL_FEWSHOT_ALL", "0") != "1"
    ):
        return False
    high_conf_tables = [t for t in candidate_tables if t.get("confidence", 0) >= 0.6]
    if len(high_conf_tables) > 1:
        return True
    if complex_text:
        return True
    if semantic.get("spatial_ops") and (semantic.get("metric_hints") or semantic.get("sql_filters")):
        return True
    # Chinese GIS/business questions often express the operation in natural
    # language (e.g. “和桥梁有空间重叠”) before the lightweight semantic
    # resolver has emitted an ST_* hint. Keep the paper's retrieval stage live
    # for those requests whenever governed candidates exist; the embedding
    # score threshold still prevents unrelated examples from being injected.
    if _contains_cjk_text(user_text) and candidate_tables:
        return True
    if os.environ.get("GDA_NL2SQL_FEWSHOT_ALL", "0") == "1" and candidate_tables:
        return True
    return False
from .semantic_layer import (
    describe_table_semantic,
    list_semantic_sources,
    resolve_semantic_context,
)

# Minimal PostgreSQL reserved words we care about for quoting
PG_RESERVED_WORDS = {
    "user", "select", "group", "order", "where", "table", "from",
}

# ---------------------------------------------------------------------------
# Sensitivity-based access control for NL2SQL table selection
# ---------------------------------------------------------------------------

# Role → max sensitivity level allowed (ordered from most to least restrictive)
_SENSITIVITY_ORDER = ("public", "internal", "confidential", "restricted", "secret")
_ROLE_MAX_SENSITIVITY = {
    "viewer": "public",
    "analyst": "internal",
    "admin": "secret",
}

_sensitivity_cache: dict[str, str] = {}
_sensitivity_cache_ts: float = 0.0


def _load_sensitivity_map() -> dict[str, str]:
    """Load table_name → sensitivity mapping from agent_data_assets. Cached 60s."""
    import time
    global _sensitivity_cache, _sensitivity_cache_ts
    now = time.time()
    if _sensitivity_cache and (now - _sensitivity_cache_ts) < 60:
        return _sensitivity_cache
    try:
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return _sensitivity_cache
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT asset_name,
                       business_metadata->'classification'->>'sensitivity'
                FROM agent_data_assets
                WHERE business_metadata->'classification'->>'sensitivity' IS NOT NULL
            """)).fetchall()
            _sensitivity_cache = {r[0]: r[1] for r in rows}
            _sensitivity_cache_ts = now
    except Exception:
        pass
    return _sensitivity_cache


def _table_accessible(table_name: str, user_role: str) -> bool:
    """Check if a table's sensitivity level is accessible to the given role."""
    sens_map = _load_sensitivity_map()
    # Extract bare table name (strip schema prefix like "public.")
    bare = table_name.split(".")[-1] if "." in table_name else table_name
    table_sens = sens_map.get(bare)
    if not table_sens:
        return True  # unclassified tables are accessible to all
    max_allowed = _ROLE_MAX_SENSITIVITY.get(user_role, "public")
    max_idx = _SENSITIVITY_ORDER.index(max_allowed) if max_allowed in _SENSITIVITY_ORDER else 0
    table_idx = _SENSITIVITY_ORDER.index(table_sens) if table_sens in _SENSITIVITY_ORDER else 0
    return table_idx <= max_idx


def _needs_quoting(column_name: str) -> bool:
    """Return True if a PostgreSQL identifier must be double-quoted."""
    if not column_name:
        return False
    if column_name.lower() != column_name:
        return True
    if column_name in PG_RESERVED_WORDS:
        return True
    if not all(ch == "_" or (ch.isascii() and ch.isalnum()) for ch in column_name):
        return True
    return False


def _quoted_ref(column_name: str) -> str:
    return f'"{column_name}"' if _needs_quoting(column_name) else column_name


def _estimate_table_size(table_name: str) -> int:
    """Best-effort table size estimate via pg_class.reltuples.

    Returns approximate row count, or 0 if unavailable.
    Falls back to COUNT(*) when reltuples is -1 (table not yet ANALYZEd).
    """
    try:
        from .db_engine import get_engine
        from sqlalchemy import text as sa_text
        engine = get_engine()
        if not engine:
            return 0
        with engine.connect() as conn:
            r = conn.execute(sa_text(
                "SELECT reltuples::bigint FROM pg_class WHERE relname = :t"
            ), {"t": table_name})
            row = r.fetchone()
            val = int(row[0]) if row and row[0] is not None else -1
            if val >= 0:
                return val
            r2 = conn.execute(sa_text(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ))
            return int(r2.scalar() or 0)
    except Exception:
        return 0


def _score_source(user_text: str, source: dict) -> float:
    """Simple fuzzy score for fallback source matching."""
    text = user_text.lower()
    candidates = [
        str(source.get("table_name", "")),
        str(source.get("display_name", "")),
        str(source.get("description", "")),
    ] + list(source.get("synonyms", []) or [])
    best = 0.0
    for c in candidates:
        c_low = c.lower()
        if c_low and c_low in text:
            best = max(best, 0.8)
        elif c_low:
            best = max(best, SequenceMatcher(None, text, c_low).ratio() * 0.5)
    return best


def _is_ascii_heavy(text: str) -> bool:
    if not text:
        return False
    ascii_chars = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    alpha_chars = sum(1 for ch in text if ch.isalpha())
    return alpha_chars > 0 and ascii_chars / max(alpha_chars, 1) >= 0.6


def _contains_cjk_text(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


def _intent_requires_spatial_sources(intent: str) -> bool:
    return intent in {
        IntentLabel.SPATIAL_JOIN.value,
        IntentLabel.KNN.value,
    }


def _prune_cross_domain_noise(user_text: str, sources: list[dict]) -> list[dict]:
    """Drop low-confidence ASCII-only sources when CJK sources matched strongly."""
    if not _contains_cjk_text(user_text):
        return sources
    if not any(float(s.get("confidence") or 0) >= 0.65 for s in sources):
        return sources
    q_low = (user_text or "").lower()
    pruned = []
    for source in sources:
        confidence = float(source.get("confidence") or 0)
        table_name = str(source.get("table_name") or "")
        bare = table_name.split(".")[-1]
        source_text = " ".join(
            str(source.get(k) or "")
            for k in ("table_name", "display_name", "description")
        )
        if confidence >= 0.6:
            pruned.append(source)
            continue
        if table_name.lower() in q_low or bare.lower() in q_low:
            pruned.append(source)
            continue
        if _contains_cjk_text(source_text):
            pruned.append(source)
            continue
    return pruned


def _extract_schema_hint(user_text: str) -> str | None:
    m = re.search(r"schema\s+`([^`]+)`", user_text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"schema\s+([A-Za-z0-9_]+)", user_text, flags=re.IGNORECASE)
    return m.group(1) if m else None


def _rank_sources(user_text: str, sources: list[dict], semantic: dict) -> list[dict]:
    """Rank candidate sources to support both GIS and non-GIS queries.

    For non-spatial queries (any language), prefer non-geometry tables and
    tables with matched columns. For GIS queries with spatial signals, preserve
    existing confidence-driven behavior. The ASCII-heavy penalty for geometry
    tables is stronger because such queries are virtually never about spatial
    GIS data.
    """
    spatial_query = bool(semantic.get("spatial_ops") or semantic.get("region_filter"))
    ascii_heavy = _is_ascii_heavy(user_text)
    schema_hint = _extract_schema_hint(user_text)
    matched_columns = semantic.get("matched_columns") or {}

    ranked = []
    for source in sources:
        table_name = source.get("table_name", "")
        score = float(source.get("confidence", 0.0))
        score += max(-1.0, min(1.0, float(source.get("nl2sql_priority") or 0) / 100.0))
        has_geom = bool(source.get("geometry_type"))
        col_hits = len(matched_columns.get(table_name, []))

        if col_hits:
            score += min(0.25, 0.08 * col_hits)
        source_alias_hits = _source_alias_hits(user_text, source)
        if source_alias_hits:
            score += min(0.3, 0.12 * source_alias_hits)
        explicit_col_hits = _source_explicit_physical_column_hits(user_text, table_name, semantic)
        if explicit_col_hits:
            score += min(0.35, 0.18 * explicit_col_hits)

        if schema_hint and table_name.startswith(f"{schema_hint}."):
            score += 0.5
        if not spatial_query:
            if not has_geom:
                score += 0.1
            else:
                # Penalize geometry tables for non-spatial queries — but only
                # if the source confidence is below 0.7 (i.e. table name not
                # explicitly mentioned). This protects FloodSQL claims/county
                # which are key-only joins by spec yet carry geometry.
                base_conf = float(source.get("confidence", 0.0))
                if base_conf < 0.7:
                    score -= 0.25 if ascii_heavy else 0.12

        ranked.append((score, source))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in ranked]


def _source_alias_hits(user_text: str, source: dict) -> int:
    hits = 0
    seen: set[str] = set()
    table_name = str(source.get("table_name") or "")
    probes = [
        table_name,
        table_name.split(".")[-1],
        str(source.get("display_name") or ""),
        str(source.get("description") or ""),
    ]
    probes.extend(str(a) for a in (source.get("synonyms") or []))
    for part in re.split(r"[\W_]+", table_name.split(".")[-1]):
        if part and not part.isdigit():
            probes.append(part)
    for probe in probes:
        probe = probe.strip()
        key = probe.lower()
        if not probe or key in seen or key in {"cq", "bird", "public"}:
            continue
        seen.add(key)
        if _identifier_token_in_text(user_text, probe):
            hits += 1
    return hits


def _explicit_source_role_alias_hits(user_text: str, source: dict) -> int:
    """Count governed business-role aliases explicitly present in a question.

    This deliberately excludes table-name fragments and free-form
    descriptions.  It is used as a recall guarantee: an explicitly named
    role such as ``道路`` must reach the schema candidate stage even when an
    embedding hit for a nearby concept (for example POI) scores higher.
    """
    probes = [str(source.get("display_name") or "")]
    probes.extend(str(value) for value in (source.get("synonyms") or []))
    ignored = {
        "data",
        "dataset",
        "table",
        "数据",
        "信息",
        "图层",
        "空间",
        "名称",
        "数量",
    }
    hits = 0
    seen: set[str] = set()
    for raw in probes:
        value = raw.strip()
        key = value.casefold()
        if not value or key in seen or key in ignored:
            continue
        seen.add(key)
        if _identifier_token_in_text(user_text, value):
            hits += 1
    return hits


def _source_explicit_physical_column_hits(user_text: str, table_name: str, semantic: dict) -> int:
    hits = 0
    for col in (semantic.get("matched_columns") or {}).get(table_name, []) or []:
        name = str(col.get("column_name") or "")
        if name and _identifier_token_in_text(user_text, name):
            hits += 1
    return hits


def _sample_distinct_values(table_name: str, column_name: str, limit: int = 5) -> list[str]:
    """Fetch a few distinct values for low-cardinality text columns.

    Supports dotted schema-qualified table names. Best-effort only.
    """
    try:
        from .db_engine import get_engine
        from sqlalchemy import text as sa_text
        engine = get_engine()
        if not engine:
            return []

        if "." in table_name:
            schema_name, bare_table = table_name.rsplit(".", 1)
            from_clause = f'"{schema_name}"."{bare_table}"'
        else:
            from_clause = f'"{table_name}"'

        sql = (
            f'SELECT DISTINCT "{column_name}" FROM {from_clause} '
            f'WHERE "{column_name}" IS NOT NULL ORDER BY 1 LIMIT {int(limit)}'
        )
        with engine.connect() as conn:
            rows = conn.execute(sa_text(sql)).fetchall()
        values = []
        for row in rows:
            v = row[0]
            if isinstance(v, str) and v:
                values.append(v)
        return values
    except Exception:
        return []


def _rank_candidate_tables(user_text: str, candidate_tables: list[dict], semantic: dict) -> list[dict]:
    """Re-rank candidate tables after schema + sample values are available."""
    spatial_query = bool(semantic.get("spatial_ops") or semantic.get("region_filter"))
    ascii_heavy = _is_ascii_heavy(user_text)
    text_lower = user_text.lower()
    matched_columns = semantic.get("matched_columns") or {}

    ranked = []
    for table in candidate_tables:
        table_name = table.get("table_name", "")
        score = float(table.get("confidence", 0.0))
        score += max(-1.0, min(1.0, float(table.get("nl2sql_priority") or 0) / 100.0))
        has_geom = any(col.get("is_geometry") for col in table.get("columns", []))
        col_hits = len(matched_columns.get(table_name, []))
        if col_hits:
            score += min(0.3, 0.1 * col_hits)
        table_alias_hits = _explicit_table_alias_hits(user_text, table)
        if table_alias_hits:
            score += min(0.5, 0.2 * table_alias_hits)
        explicit_col_hits = _explicit_physical_column_hits(user_text, table)
        if explicit_col_hits:
            score += min(0.7, 0.28 * explicit_col_hits)
        if not spatial_query:
            if not has_geom:
                score += 0.1
            else:
                # Same conditional penalty as in _rank_sources: only penalize
                # geom tables when their base confidence is below 0.7 (i.e.
                # table name not explicitly mentioned in the question).
                base_conf = float(table.get("confidence", 0.0))
                if base_conf < 0.7:
                    score -= 0.25 if ascii_heavy else 0.12

            value_hits = 0
            for col in table.get("columns", []):
                for v in col.get("sample_values") or []:
                    if isinstance(v, str) and v and v.lower() in text_lower:
                        value_hits += 1
            if value_hits:
                score += min(0.6, 0.25 * value_hits)

        ranked.append((score, table))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in ranked]


def _explicit_physical_column_hits(user_text: str, table: dict) -> int:
    """Count exact physical column-name mentions in the question.

    Aliases are intentionally ignored here. This is a tie-breaker for cases
    where two tables share business aliases but only one has the exact physical
    identifiers the user typed, such as case-sensitive PostgreSQL columns.
    """
    hits = 0
    text = user_text or ""
    for col in table.get("columns", []) or []:
        name = str(col.get("column_name") or "")
        if not name:
            continue
        if _identifier_token_in_text(text, name):
            hits += 1
    return hits


def _explicit_table_alias_hits(user_text: str, table: dict) -> int:
    hits = 0
    seen: set[str] = set()
    table_name = str(table.get("table_name") or "")
    display_name = str(table.get("display_name") or "")
    probes = [table_name, table_name.split(".")[-1], display_name]
    probes.extend(str(a) for a in (table.get("table_aliases") or []))
    for part in re.split(r"[\W_]+", table_name.split(".")[-1]):
        if part and not part.isdigit():
            probes.append(part)
    for probe in probes:
        probe = probe.strip()
        key = probe.lower()
        if not probe or key in seen or key in {"cq", "bird", "public"}:
            continue
        seen.add(key)
        if _identifier_token_in_text(user_text, probe):
            hits += 1
    return hits


def _identifier_token_in_text(text: str, token: str) -> bool:
    if not token:
        return False
    if any(ch.isascii() and (ch.isalnum() or ch == "_") for ch in token):
        return bool(re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])",
            text,
        ))
    return token in text


def _build_candidate_table(source: dict, schema: dict) -> dict:
    """Merge semantic source hit + describe_table_semantic() result."""
    out_columns = []
    for col in schema.get("columns", []) or []:
        column_name = col.get("column_name", "")
        aliases = col.get("aliases", []) or []
        pg_type = col.get("data_type") or col.get("udt_name") or ""
        # Detect geometry column: explicit flag OR (USER-DEFINED type + geom-like name)
        is_geom = bool(col.get("is_geometry", False))
        if not is_geom and pg_type == "USER-DEFINED" and column_name.lower() in ("geometry", "geom", "the_geom", "shape"):
            is_geom = True
        if is_geom:
            gt = schema.get("geometry_type") or source.get("geometry_type") or "Geometry"
            srid = schema.get("srid") or source.get("srid") or 0
            pg_type = f"geometry({gt},{srid})"
        out_columns.append({
            "column_name": column_name,
            "pg_type": pg_type,
            "quoted_ref": _quoted_ref(column_name),
            "aliases": aliases,
            "semantic_domain": col.get("semantic_domain"),
            "unit": col.get("unit") or "",
            "description": col.get("description") or "",
            "is_geometry": is_geom,
            "needs_quoting": _needs_quoting(column_name),
            "value_semantics": col.get("value_semantics") or {},
            "sample_values": [],
        })
    source_meta = schema.get("source_metadata") or {}
    source_kind = source.get("source_kind") or source_meta.get("source_kind") or "postgis"
    projection_path = source.get("projection_path") or source_meta.get("projection_path")
    projection_id = source.get("projection_id") or source_meta.get("projection_id")
    explicit_bindings = source.get("execution_bindings") or source_meta.get(
        "execution_bindings"
    ) or {}
    execution_bindings = {
        str(engine): dict(binding)
        for engine, binding in explicit_bindings.items()
        if isinstance(binding, dict)
    }
    if projection_path and "lake" not in execution_bindings:
        execution_bindings["lake"] = {
            "projection_path": projection_path,
            "projection_id": projection_id,
        }
    postgis_table_name = source.get("postgis_table_name") or source_meta.get(
        "postgis_table_name"
    )
    if (
        "postgis" not in execution_bindings
        and (source_kind != "offline_projection" or postgis_table_name)
    ):
        execution_bindings["postgis"] = {
            "table_name": postgis_table_name
            or source.get("table_name")
            or schema.get("table_name"),
        }
    return {
        "table_name": source.get("table_name") or schema.get("table_name"),
        "display_name": source.get("display_name") or schema.get("display_name") or source.get("table_name"),
        "description": source.get("description") or schema.get("description") or "",
        "table_aliases": _table_aliases_from_source(source, schema),
        "confidence": float(source.get("confidence", 0.0)),
        "columns": out_columns,
        "row_count_hint": _estimate_table_size(source.get("table_name") or schema.get("table_name")),
        "schema_complete": True,
        "source_kind": source_kind,
        "projection_path": projection_path,
        "projection_id": projection_id,
        "srid": source.get("srid") or source_meta.get("srid"),
        "geometry_type": source.get("geometry_type") or source_meta.get("geometry_type"),
        "metric_crs": source.get("metric_crs") or source_meta.get("metric_crs"),
        "production_eligible": source.get(
            "production_eligible", source_meta.get("production_eligible", False)
        ),
        "nl2sql_enabled": source.get(
            "nl2sql_enabled", source_meta.get("nl2sql_enabled", True)
        ),
        "nl2sql_priority": int(
            source.get("nl2sql_priority", source_meta.get("nl2sql_priority", 0)) or 0
        ),
        "execution_bindings": execution_bindings,
    }


def _extract_sql_table_names(sql: str) -> list[str]:
    """Extract physical table identifiers referenced by a reviewed example.

    This is intentionally a conservative identifier scan, not an SQL parser:
    it only accepts names following FROM/JOIN. The
    extracted names are matched against the governed semantic-source catalog
    before they can affect grounding.
    """
    if not sql:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.]*)",
        str(sql),
        flags=re.IGNORECASE,
    ):
        identifier = match.group(1).strip().strip('"')
        bare = identifier.split(".")[-1].strip('"')
        if not bare:
            continue
        key = identifier.casefold()
        if key not in seen:
            seen.add(key)
            names.append(identifier)
    return names


def refresh_nl2sql_grounding_prompt(payload: dict, family: str | None = None) -> dict:
    """Re-render grounding after an execution adapter filters candidates."""

    payload["grounding_prompt"] = _format_grounding_prompt(payload, family=family)
    stats = payload.setdefault("_hint_injection_stats", {})
    stats["candidate_tables"] = len(payload.get("candidate_tables") or [])
    return payload


def _as_str_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return []


def _table_aliases_from_source(source: dict, schema: dict) -> list[str]:
    source_meta = schema.get("source_metadata") or {}
    table_name = source.get("table_name") or schema.get("table_name") or ""
    aliases: list[str] = []
    for key in ("table_aliases", "sql_aliases", "synonyms"):
        aliases.extend(_as_str_list(source.get(key)))
    aliases.extend(_as_str_list(source_meta.get("synonyms")))
    for label in (
        source.get("display_name"),
        schema.get("display_name"),
        source_meta.get("display_name"),
    ):
        if label:
            aliases.append(str(label))
    cleaned = []
    for alias in aliases:
        alias = str(alias).strip()
        if not alias or alias == table_name:
            continue
        cleaned.append(alias)
    return list(dict.fromkeys(cleaned))


def _merge_source_metadata(source: dict, source_list_item: dict | None) -> dict:
    if not source_list_item:
        return source
    merged = dict(source_list_item)
    merged.update(source)
    for key in ("synonyms", "suggested_analyses", "table_aliases", "sql_aliases"):
        if key not in source or not source.get(key):
            if source_list_item.get(key):
                merged[key] = source_list_item[key]
    return merged


def _resolve_major_project_kg_hints(user_text: str, semantic: dict, intent: str | None) -> dict:
    """Resolve major-project KG hints without letting resolver failures break grounding."""
    try:
        from .major_project_kg_resolver import resolve_major_project_kg_hints

        hints = resolve_major_project_kg_hints(
            user_text,
            semantic=semantic,
            intent=intent,
        )
        return hints if isinstance(hints, dict) else {}
    except Exception as exc:
        logger.warning("[NL2SQL grounding] major-project KG hint resolution failed: %s", exc)
        return {}


def _is_actionable_kg_hints(kg_hints: dict | None) -> bool:
    if not isinstance(kg_hints, dict):
        return False
    if _as_str_list(kg_hints.get("matched_entities")):
        return True
    if _as_str_list(kg_hints.get("required_edges")):
        return True
    return bool(
        _as_str_list(kg_hints.get("candidate_tables"))
        or _as_str_list(kg_hints.get("join_paths"))
    )


def _normalize_kg_hints(kg_hints: dict | None) -> dict:
    return dict(kg_hints) if _is_actionable_kg_hints(kg_hints) else {}


_MAJOR_PROJECT_KG_TABLES = {
    "mp_project_list",
    "mp_pre_review",
    "mp_conversion_expropriation",
    "mp_land_supply",
    "mp_parcel",
    "mp_relation_confidence",
    "mp_spatial_overlap",
    "kg_edges",
    "kg_nodes",
}

_KG_EDGE_TABLE_REQUIREMENTS = {
    "MISSING_STAGE": {"mp_project_list", "kg_edges", "kg_nodes"},
    "OCCUPIES_PARCEL": {"mp_project_list", "mp_relation_confidence", "mp_parcel"},
    "SPATIALLY_OVERLAPS": {
        "mp_project_list",
        "mp_relation_confidence",
        "mp_parcel",
        "mp_spatial_overlap",
    },
    "FUZZY_PROJECT_PARCEL_MATCH": {"mp_project_list", "mp_relation_confidence", "mp_parcel"},
    "HAS_PRE_REVIEW": {"mp_project_list", "mp_pre_review"},
    "HAS_CONVERSION": {"mp_project_list", "mp_conversion_expropriation"},
    "HAS_LAND_SUPPLY": {"mp_project_list", "mp_land_supply"},
}

_KG_PARCEL_EDGE_NAMES = {
    "OCCUPIES_PARCEL",
    "SPATIALLY_OVERLAPS",
    "FUZZY_PROJECT_PARCEL_MATCH",
}

_KG_SPATIAL_EDGE_NAMES = {
    "SPATIALLY_OVERLAPS",
    "FUZZY_PROJECT_PARCEL_MATCH",
}

_MAJOR_PROJECT_EXPLICIT_TOKENS = (
    "重大项目",
    "重点项目",
    "major project",
    "major_project",
    "mp_project",
    "mp_relation_confidence",
    "审批流程",
    "流程断点",
    "用地预审",
    "农转征",
    "农转用",
    "农用地转用",
    "土地征收",
    "土地供应",
)

_MAJOR_PROJECT_PROJECT_CONTEXT_TOKENS = (
    "占用",
    "耕地",
    "地块",
    "关系置信度",
    "置信度",
    "供地",
    "预审",
    "空间叠加",
    "叠加补全",
    "补全关联",
    "空间覆盖",
    "空间关联",
)


def _semantic_major_project_table_names(semantic: dict | None) -> set[str]:
    if not isinstance(semantic, dict):
        return set()

    names = set()
    for key in (
        "sources",
        "matched_tables",
        "matched_table_names",
        "source_tables",
        "matched_sources",
        "candidate_tables",
    ):
        value = semantic.get(key)
        if isinstance(value, str):
            names.add(value)
        elif isinstance(value, dict):
            for name, item in value.items():
                if isinstance(name, str):
                    names.add(name)
                if isinstance(item, dict):
                    table_name = item.get("table_name") or item.get("name")
                    if isinstance(table_name, str):
                        names.add(table_name)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, str):
                    names.add(item)
                elif isinstance(item, dict):
                    table_name = item.get("table_name") or item.get("name")
                    if isinstance(table_name, str):
                        names.add(table_name)
    return names


def _has_major_project_grounding_context(user_text: str, semantic: dict | None) -> bool:
    text = user_text or ""
    text_low = text.lower()
    if any(token in text or token.lower() in text_low for token in _MAJOR_PROJECT_EXPLICIT_TOKENS):
        return True
    if "项目" in text and any(
        token in text or token.lower() in text_low
        for token in _MAJOR_PROJECT_PROJECT_CONTEXT_TOKENS
    ):
        return True
    return False


def _is_major_project_kg_table_name(table_name: str) -> bool:
    bare = str(table_name or "").split(".")[-1]
    return bare in _MAJOR_PROJECT_KG_TABLES


def _question_mentions_physical_table_name(user_text: str, table_name: str) -> bool:
    table_ref = str(table_name or "")
    if not table_ref:
        return False
    bare = table_ref.split(".")[-1]
    return (
        _identifier_token_in_text(user_text, table_ref)
        or _identifier_token_in_text(user_text, bare)
    )


def _prune_unqualified_major_project_sources(user_text: str, sources: list[dict]) -> list[dict]:
    pruned = []
    for source in sources:
        table_name = str(source.get("table_name") or "")
        if (
            _is_major_project_kg_table_name(table_name)
            and not _question_mentions_physical_table_name(user_text, table_name)
        ):
            continue
        pruned.append(source)
    return pruned


def _schema_filter_allows_kg_table(table_name: str, schema_filter: str | None) -> bool:
    if not schema_filter:
        return True
    if "." not in table_name:
        return schema_filter == "public"
    return table_name.startswith(f"{schema_filter}.")


def _kg_priority_table_names(kg_hints: dict | None, schema_filter: str | None) -> set[str]:
    if not _is_actionable_kg_hints(kg_hints):
        return set()

    names: set[str] = set()
    for edge in _as_str_list(kg_hints.get("required_edges")):
        names.update(_KG_EDGE_TABLE_REQUIREMENTS.get(edge, set()))
    if not names:
        names.update(_as_str_list(kg_hints.get("candidate_tables")))
        for join_path in _as_str_list(kg_hints.get("join_paths")):
            names.update(_kg_join_path_tables(join_path))
    return {
        table_name
        for table_name in names
        if table_name and _schema_filter_allows_kg_table(table_name, schema_filter)
    }


def _select_with_kg_priority(
    ranked_items: list[dict],
    limit: int,
    kg_hints: dict | None,
    schema_filter: str | None,
) -> list[dict]:
    if limit <= 0:
        return []

    priority_names = _kg_priority_table_names(kg_hints, schema_filter)
    if not priority_names:
        return ranked_items[:limit]

    available_priority_names = {
        str(item.get("table_name") or "")
        for item in ranked_items
        if str(item.get("table_name") or "") in priority_names
    }
    effective_limit = max(limit, len(available_priority_names))
    selected: list[dict] = []
    selected_names: set[str] = set()

    for item in ranked_items:
        table_name = str(item.get("table_name") or "")
        if table_name in priority_names and table_name not in selected_names:
            selected.append(item)
            selected_names.add(table_name)

    for item in ranked_items:
        if len(selected) >= effective_limit:
            break
        table_name = str(item.get("table_name") or "")
        if table_name and table_name not in selected_names:
            selected.append(item)
            selected_names.add(table_name)

    return selected


def _kg_hint_sources(
    kg_hints: dict,
    sources: list[dict],
    schema_filter: str | None,
) -> list[dict]:
    existing = {str(source.get("table_name") or "") for source in sources}
    additions = []
    for table_name in _as_str_list(kg_hints.get("candidate_tables")):
        if not table_name or table_name in existing:
            continue
        if not _schema_filter_allows_kg_table(table_name, schema_filter):
            continue
        additions.append({
            "table_name": table_name,
            "display_name": table_name,
            "description": "KG hint candidate table",
            "confidence": 0.72,
        })
        existing.add(table_name)
    return additions


def _kg_join_path_tables(join_path: str) -> set[str]:
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*", join_path))


def _filter_kg_edges_for_candidate_tables(kg_hints: dict, final_names: set[str]) -> dict:
    filtered = dict(kg_hints)
    kept_edges = []
    removed_edges = []
    for edge in _as_str_list(filtered.get("required_edges")):
        required_tables = _KG_EDGE_TABLE_REQUIREMENTS.get(edge)
        if required_tables and not required_tables <= final_names:
            removed_edges.append(edge)
            continue
        kept_edges.append(edge)

    filtered["required_edges"] = kept_edges
    kept_edge_set = set(kept_edges)
    removed_edge_set = set(removed_edges)

    if removed_edge_set & _KG_PARCEL_EDGE_NAMES or "mp_relation_confidence" not in final_names:
        filtered["relation_confidence_filter"] = False
        filtered["min_relation_confidence"] = None

    if removed_edge_set & _KG_SPATIAL_EDGE_NAMES or not (kept_edge_set & _KG_SPATIAL_EDGE_NAMES):
        filtered["spatial_overlap_threshold"] = None

    return filtered


def _is_grounded_actionable_kg_hints(kg_hints: dict) -> bool:
    return bool(
        _as_str_list(kg_hints.get("required_edges"))
        or _as_str_list(kg_hints.get("join_paths"))
    )


def _normalize_kg_hints_for_candidate_tables(
    kg_hints: dict,
    candidate_table_names: set[str],
) -> dict:
    kg_hints = _normalize_kg_hints(kg_hints)
    if not kg_hints:
        return {}

    final_names = {str(name) for name in candidate_table_names if name}
    if not final_names:
        return {}

    normalized = dict(kg_hints)
    hinted_tables = _as_str_list(normalized.get("candidate_tables"))
    grounded_tables = [table_name for table_name in hinted_tables if table_name in final_names]
    if hinted_tables and not grounded_tables:
        return {}
    normalized["candidate_tables"] = grounded_tables

    grounded_join_paths = []
    for join_path in _as_str_list(normalized.get("join_paths")):
        path_tables = _kg_join_path_tables(join_path)
        if path_tables and path_tables <= final_names:
            grounded_join_paths.append(join_path)
    normalized["join_paths"] = grounded_join_paths
    normalized = _filter_kg_edges_for_candidate_tables(normalized, final_names)
    return normalized if _is_grounded_actionable_kg_hints(normalized) else {}


def _format_kg_hints_lines(kg_hints: dict | None) -> list[str]:
    """Render deterministic KG hints in a compact, prompt-safe form."""
    if not isinstance(kg_hints, dict):
        return []

    matched_entities = _as_str_list(kg_hints.get("matched_entities"))
    required_edges = _as_str_list(kg_hints.get("required_edges"))
    if not matched_entities and not required_edges:
        return []

    lines = ["KG hints:"]
    if matched_entities:
        lines.append(f"- matched entities: {', '.join(matched_entities[:8])}")
    if required_edges:
        lines.append(f"- required graph edges: {', '.join(required_edges[:8])}")

    graph_backend = kg_hints.get("graph_backend")
    neo4j_info = kg_hints.get("neo4j") if isinstance(kg_hints.get("neo4j"), dict) else {}
    if graph_backend:
        backend_parts = [f"graph backend: {graph_backend}"]
        if neo4j_info.get("status") == "ok" and neo4j_info.get("database"):
            backend_parts.append(f"database: {neo4j_info.get('database')}")
        lines.append(f"- {'; '.join(backend_parts)}")
        edge_counts = neo4j_info.get("edge_counts") if isinstance(neo4j_info, dict) else {}
        if isinstance(edge_counts, dict) and edge_counts:
            rendered_counts = [
                f"{edge_type}={count}"
                for edge_type, count in list(edge_counts.items())[:8]
            ]
            lines.append(f"- neo4j edge counts: {', '.join(rendered_counts)}")

    missing_stage = kg_hints.get("missing_stage")
    if kg_hints.get("missing_stage_filter") or missing_stage:
        suffix = f"; missing_stage: {missing_stage}" if missing_stage else ""
        lines.append(
            f"- lifecycle missing-stage filter: {bool(kg_hints.get('missing_stage_filter'))}{suffix}"
        )
        predicate = "kg_edges.edge_type = 'MISSING_STAGE'"
        if missing_stage:
            predicate += f"; kg_edges.evidence->>'missing_stage' = '{missing_stage}'"
        lines.append(f"- missing-stage SQL predicate: {predicate}")

    min_confidence = kg_hints.get("min_relation_confidence")
    if kg_hints.get("relation_confidence_filter") or min_confidence is not None:
        parts = [f"enabled: {bool(kg_hints.get('relation_confidence_filter'))}"]
        if min_confidence is not None:
            parts.append(f"min_relation_confidence: {min_confidence}")
        lines.append(f"- relation confidence filter: {'; '.join(parts)}")

    spatial_threshold = kg_hints.get("spatial_overlap_threshold")
    if spatial_threshold is not None:
        lines.append(f"- spatial overlap threshold: {spatial_threshold}")

    join_paths = _as_str_list(kg_hints.get("join_paths"))
    for join_path in join_paths[:5]:
        lines.append(f"- graph join path: {join_path}")

    candidate_tables = _as_str_list(kg_hints.get("candidate_tables"))
    joined_tables = ", ".join(candidate_tables)
    if candidate_tables and len(joined_tables) <= 180:
        lines.append(f"- candidate graph tables: {joined_tables}")

    return lines


def _format_grounding_prompt(payload: dict, family: str | None = None) -> str:
    """Format the grounding payload into a strict prompt block for the LLM.

    The Gemini-style rendering (legacy) is a long, narrative-heavy block with
    detailed rules per intent. DeepSeek's system_instruction.md already
    encodes those rules in R1-R7 strict form, so the DS rendering is a
    slim schema-and-hints block that omits redundant rule restatements.
    """
    if family in ("deepseek", "qwen", "gemma"):
        return _format_grounding_prompt_compact(payload)
    return _format_grounding_prompt_legacy(payload)


def _format_grounding_prompt_compact(payload: dict) -> str:
    """Slim grounding rendering for DS / Qwen — schema + hints only.

    Rationale: per-family system_instruction.md already encodes safety/KNN/
    aggregation/output-contract rules in compact R1-R7 form. Repeating them in
    the grounding prompt creates redundancy that DS instruction-following
    handles poorly (often produces over-engineered SQL that mixes both
    rule sources). This compact rendering ships only the per-question
    information that cannot live in the static system instruction:
    candidate schema, semantic hints, few-shots, and warehouse join paths.
    """
    lines: list[str] = []
    lines.append("[NL2SQL question context — use the schema and hints below]")

    # Candidate schema — same content as legacy, but tighter formatting
    cand = payload.get("candidate_tables") or []
    if cand:
        lines.append("")
        lines.append("## Candidate tables")
        geom_srids: dict[str, int] = {}
        for table in cand:
            lines.append("")
            lines.append(f"### {table['table_name']}"
                         f" (confidence {table.get('confidence', 0.0):.2f},"
                         f" ~{table.get('row_count_hint', 0)} rows)")
            priority = int(table.get("nl2sql_priority") or 0)
            if priority:
                lines.append(
                    f"- governed NL2SQL priority: {priority}; prefer this source over "
                    "lower-priority candidates for the same business object"
                )
            table_aliases = table.get("table_aliases") or []
            if table_aliases:
                lines.append(f"- table aliases: {', '.join(str(a) for a in table_aliases[:12])}")
            for col in table.get("columns", []):
                unit_str = f" [{col['unit']}]" if col.get("unit") else ""
                aliases = col.get("aliases") or []
                alias_str = f" aka {', '.join(aliases)}" if aliases else ""
                semantic_domain = str(col.get("semantic_domain") or "").strip()
                description = str(col.get("description") or "").strip()
                meaning_parts = []
                if semantic_domain:
                    meaning_parts.append(f"domain={semantic_domain}")
                if description:
                    meaning_parts.append(f"meaning={description}")
                meaning_str = f" {'; '.join(meaning_parts)}" if meaning_parts else ""
                sv = col.get("sample_values")
                sample_str = (
                    f" sample: {', '.join(str(v) for v in sv[:5])}"
                    if sv else ""
                )
                value_semantics = col.get("value_semantics") or {}
                value_semantics_str = (
                    f" semantics: {json.dumps(value_semantics, ensure_ascii=False)}"
                    if value_semantics else ""
                )
                lines.append(
                    f"- {col['quoted_ref']} :: {col.get('pg_type','')}"
                    f"{unit_str}{alias_str}{meaning_str}{sample_str}{value_semantics_str}"
                )
                if col.get("is_geometry"):
                    pg_type = col.get("pg_type", "")
                    srid = 0
                    if "," in pg_type:
                        try:
                            srid = int(pg_type.rsplit(",", 1)[1].rstrip(")"))
                        except (ValueError, IndexError):
                            pass
                    geom_srids[f"{table['table_name']}.{col['column_name']}"] = srid

        # SRID alignment warning (kept — this is per-question information,
        # not a static rule)
        if len(set(geom_srids.values())) > 1:
            lines.append("")
            lines.append("## SRID alignment required")
            for ref, srid in geom_srids.items():
                lines.append(f"- {ref}: SRID={srid}")
            lines.append("- ST_Transform geometries to a common SRID before "
                         "spatial operations.")

        # Make the semantic resolver's role assignment explicit. This is
        # intentionally derived from governed aliases, rather than a table-
        # name or question-id branch, so a model cannot silently reuse one
        # candidate table for two distinct entities in a spatial join.
        question = str(payload.get("user_question") or "")
        role_matches: dict[str, list[tuple[str, float, int]]] = {}
        for table in cand:
            table_name = str(table.get("table_name") or "")
            if not table_name:
                continue
            aliases = list(table.get("table_aliases") or [])
            aliases.extend([table.get("display_name") or ""])
            for alias in dict.fromkeys(str(item).strip() for item in aliases if item):
                if len(alias) < 2 or not _identifier_token_in_text(question, alias):
                    continue
                role_matches.setdefault(alias, []).append(
                    (table_name, float(table.get("confidence") or 0.0), int(table.get("nl2sql_priority") or 0))
                )
        bindings: list[tuple[str, str]] = []
        for alias, matches in role_matches.items():
            unique_tables = {item[0] for item in matches}
            ordered = sorted(matches, key=lambda item: (item[2], item[1]), reverse=True)
            # A lower-priority alias match must not override a governed source
            # for the same business object. Alias overlap scopes the comparison
            # so an unrelated high-priority table cannot suppress this role.
            alias_key = alias.casefold()
            competing_priority = max(
                (
                    int(table.get("nl2sql_priority") or 0)
                    for table in cand
                    if any(
                        alias_key in probe.casefold() or probe.casefold() in alias_key
                        for probe in [
                            str(table.get("display_name") or ""),
                            *(str(value) for value in (table.get("table_aliases") or [])),
                        ]
                        if len(probe.strip()) >= 2
                    )
                ),
                default=ordered[0][2],
            )
            if competing_priority > ordered[0][2]:
                continue
            if len(unique_tables) == 1:
                bindings.append((alias, matches[0][0]))
                continue
            # If two physical versions share an alias, emit it only when the
            # governed priority makes the choice unambiguous.
            if len(ordered) > 1 and (ordered[0][2] > ordered[1][2] or ordered[0][1] - ordered[1][1] >= 0.2):
                bindings.append((alias, ordered[0][0]))
        if bindings:
            lines.append("")
            lines.append("## Question-to-table role bindings (governed)")
            for alias, table_name in bindings[:8]:
                lines.append(f'- question term "{alias}" -> {table_name}')
            lines.append("- Use each bound physical table for that role; do not reuse a different candidate table unless the question explicitly requests a self-join.")

    # Semantic hints
    hints = payload.get("semantic_hints", {}) or {}
    interesting = {k: hints.get(k) for k in (
        "spatial_ops", "region_filter", "hierarchy_matches",
        "metric_hints", "sql_filters",
    ) if hints.get(k)}
    if interesting:
        lines.append("")
        lines.append("## Semantic hints")
        for k, v in interesting.items():
            lines.append(f"- {k}: {v}")

    kg_hint_lines = _format_kg_hints_lines(payload.get("kg_hints"))
    if kg_hint_lines:
        lines.append("")
        lines.extend(kg_hint_lines)

    # Business rules from agent_semantic_hints (data-driven).
    table_hints = payload.get("table_hints") or []
    column_hints = payload.get("column_hints") or {}
    if table_hints or column_hints:
        lines.append("")
        lines.append("## Business rules")
        for h in table_hints:
            mark = "!! " if h.get("severity") == "critical" else "- "
            text = h.get("hint_text_en") or h["hint_text_zh"]
            lines.append(f"{mark}{h['scope_ref']}: {text}")
        for colkey, hs in column_hints.items():
            for h in hs:
                mark = "!! " if h.get("severity") == "critical" else "- "
                text = h.get("hint_text_en") or h["hint_text_zh"]
                lines.append(f"{mark}{colkey}: {text}")

    # Dynamic large-table list.
    large_tables = payload.get("large_tables") or []
    if large_tables:
        lines.append("")
        lines.append("## Large tables (>=1M rows; bounded-output policy applies)")
        for t in large_tables:
            lines.append(f"- {t}")

    # Warehouse join paths (per-question, cannot live in system instruction)
    wh = payload.get("warehouse_join_hints")
    spatial_query = bool(hints.get("spatial_ops") or hints.get("region_filter"))
    if wh and not spatial_query:
        lines.append("")
        lines.append("## Warehouse join paths")
        for tbl, info in (wh.get("table_roles") or {}).items():
            role = "fact" if info.get("role") == "fact" else "dimension"
            entities = ", ".join(info.get("entities") or [])
            measures = ", ".join(info.get("measures") or [])
            parts = [f"{tbl}: {role}"]
            if entities:
                parts.append(f"entities={entities}")
            if measures:
                parts.append(f"measures={measures}")
            lines.append(f"- {'; '.join(parts)}")
        for jp in wh.get("join_paths") or []:
            lines.append(f"- JOIN: {jp}")

    # Few-shots — these are per-question retrieved examples, not static rules
    few_shots = payload.get("few_shots") or []
    if few_shots:
        lines.append("")
        lines.append("## Reference SQL examples")
        for shot in few_shots[:3]:  # tighter cap for DS
            lines.append(f"Q: {shot.get('question','')}")
            lines.append(f"SQL: {shot.get('sql','')}")

    return "\n".join(lines)


def _format_grounding_prompt_legacy(payload: dict) -> str:
    """Format the grounding payload into a strict prompt block for the LLM."""
    lines: list[str] = []
    lines.append("[NL2SQL 上下文 — 必须严格遵循以下 schema]")
    lines.append("")
    lines.append("## 候选数据源")
    geom_srids: dict[str, int] = {}  # table.column -> srid
    for table in payload.get("candidate_tables", []):
        lines.append("")
        lines.append(f"### {table['table_name']} ({table.get('display_name') or table['table_name']})")
        lines.append(f"置信度: {table.get('confidence', 0.0):.2f}; 估计行数: {table.get('row_count_hint', 0)}")
        priority = int(table.get("nl2sql_priority") or 0)
        if priority:
            lines.append(
                f"- 治理后的问数优先级: {priority}；若其他候选表示同一业务对象，优先使用本表。"
            )
        table_aliases = table.get("table_aliases") or []
        if table_aliases:
            lines.append(f"- table aliases: {', '.join(str(a) for a in table_aliases[:12])}")
        for col in table.get("columns", []):
            alias_str = ", ".join(col.get("aliases") or []) or "—"
            unit_str = f" [单位: {col['unit']}]" if col.get("unit") else ""
            sample_str = ""
            sv = col.get("sample_values")
            if sv:
                sample_str = f" | 示例值: {', '.join(str(v) for v in sv[:8])}"
            lines.append(f"- {col['quoted_ref']} :: {col.get('pg_type','')}{unit_str} | 别名: {alias_str}{sample_str}")
            if col.get("is_geometry"):
                pg_type = col.get("pg_type", "")
                srid = 0
                if "," in pg_type:
                    try:
                        srid = int(pg_type.rsplit(",", 1)[1].rstrip(")"))
                    except (ValueError, IndexError):
                        pass
                geom_srids[f"{table['table_name']}.{col['column_name']}"] = srid
        quoted_examples = [
            str(c.get("quoted_ref") or "")
            for c in table.get("columns", [])
            if c.get("needs_quoting") and c.get("quoted_ref")
        ][:2]
        if quoted_examples:
            lines.append(
                "⚠ PostgreSQL 规则: 大小写混合列名必须使用双引号；"
                f"当前 schema 中的示例: {', '.join(quoted_examples)}。"
            )

    if geom_srids:
        geographic_cols = {k: v for k, v in geom_srids.items() if v in (4326, 4490, 4610)}
        projected_cols = {k: v for k, v in geom_srids.items() if v not in (4326, 4490, 4610)}
        distinct_srids = set(geom_srids.values())

        if len(distinct_srids) > 1:
            lines.append("")
            lines.append("## ⚠ SRID 不一致警告")
            lines.append("- 候选表的几何列使用了不同的 SRID，跨表空间操作前**必须**用 ST_Transform 对齐:")
            for col_key, srid in geom_srids.items():
                lines.append(f"  - {col_key}: SRID={srid}")
            target_srid = max(geom_srids.values())
            if projected_cols:
                target_srid = next(iter(projected_cols.values()))
            lines.append(f"- 建议: 将其他列 ST_Transform 到 SRID={target_srid} 后再做空间运算")

        if geographic_cols:
            lines.append("")
            lines.append("## 空间几何字段规则 (地理坐标)")
            cols_list = ", ".join(geographic_cols.keys())
            lines.append(f"- 适用于: {cols_list}")
            lines.append("- 这些列是经纬度坐标（度），计算真实长度/面积必须先转 geography:")
            lines.append("  - 面积: `ST_Area(geom::geography)` → 平方米")
            lines.append("  - 距离: `ST_Distance(a::geography, b::geography)` → 米")
            lines.append("  - 范围: `ST_DWithin(a::geography, b::geography, 500)` → 500米")
            lines.append("- 空间关系（Intersects/Contains/Within）直接用 geometry，不需要 geography")

        if projected_cols:
            lines.append("")
            lines.append("## 空间几何字段规则 (投影坐标)")
            cols_list = ", ".join(projected_cols.keys())
            lines.append(f"- 适用于: {cols_list}")
            lines.append("- 这些列已经是投影坐标（米），ST_Area/ST_Length **直接返回平方米/米**")
            lines.append("- **禁止**对这些列使用 `::geography` 转换（会报错）")
            lines.append("- 面积: `ST_Area(geom)` → 平方米（直接使用）")
            lines.append("- 空间关系: `ST_Intersects(a, b)` 直接使用")
    lines.append("")
    lines.append("## 语义提示")
    hints = payload.get("semantic_hints", {})
    lines.append(f"- 空间操作: {hints.get('spatial_ops') or []}")
    lines.append(f"- 区域过滤: {hints.get('region_filter')}")
    lines.append(f"- 层次匹配: {hints.get('hierarchy_matches') or []}")
    lines.append(f"- 指标提示: {hints.get('metric_hints') or []}")
    lines.append(f"- 推荐 SQL 过滤: {hints.get('sql_filters') or []}")

    kg_hint_lines = _format_kg_hints_lines(payload.get("kg_hints"))
    if kg_hint_lines:
        lines.append("")
        lines.extend(kg_hint_lines)

    # Business rules (table- and column-scope) from agent_semantic_hints.
    # Previously lived hard-coded in prompts_nl2sql/*/system_instruction.md;
    # now data-driven so new customers configure via the semantic layer UI.
    table_hints = payload.get("table_hints") or []
    column_hints = payload.get("column_hints") or {}
    if table_hints or column_hints:
        lines.append("")
        lines.append("## [业务规则]")
        for h in table_hints:
            mark = "⚠⚠ " if h.get("severity") == "critical" else "- "
            lines.append(f"{mark}{h['scope_ref']}: {h['hint_text_zh']}")
        for colkey, hs in column_hints.items():
            for h in hs:
                mark = "⚠⚠ " if h.get("severity") == "critical" else "- "
                lines.append(f"{mark}{colkey}: {h['hint_text_zh']}")

    # Dynamic large-table list (replaces hard-coded names in system_instruction.md).
    large_tables = payload.get("large_tables") or []
    if large_tables:
        lines.append("")
        lines.append("## 大表（≥100万行，bounded-output policy 适用）")
        for t in large_tables:
            lines.append(f"- {t}")

    # Warehouse join-path hints (non-spatial only)
    wh = payload.get("warehouse_join_hints")
    spatial_query = bool(
        (payload.get("semantic_hints") or {}).get("spatial_ops")
        or (payload.get("semantic_hints") or {}).get("region_filter")
    )
    if wh and not spatial_query:
        lines.append("")
        lines.append("## 数据仓库 Join 路径提示")
        for tbl, info in (wh.get("table_roles") or {}).items():
            role = info.get("role", "unknown")
            role_cn = "事实表(fact)" if role == "fact" else "维度表(dimension)"
            entities = ", ".join(info.get("entities") or [])
            measures = ", ".join(info.get("measures") or [])
            parts = [f"{tbl}: {role_cn}"]
            if entities:
                parts.append(f"实体键: {entities}")
            if measures:
                parts.append(f"度量: {measures}")
            lines.append(f"- {'; '.join(parts)}")
        for jp in wh.get("join_paths") or []:
            lines.append(f"- JOIN: {jp}")
        for mhp in wh.get("multi_hop_paths") or []:
            lines.append(f"- MULTI-HOP JOIN (via bridge): {mhp}")

    few_shots = payload.get("few_shots") or []
    if few_shots:
        lines.append("")
        lines.append("## 参考 SQL")
        for shot in few_shots:
            lines.append(f"Q: {shot.get('question','')}")
            lines.append(f"SQL: {shot.get('sql','')}")
    lines.append("")
    lines.append("## 安全规则")
    lines.append("- 只允许 SELECT 查询")
    lines.append("- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER")

    from .nl2sql_intent import IntentLabel
    intent = payload.get("intent", IntentLabel.UNKNOWN)
    if not isinstance(intent, IntentLabel):
        try:
            intent = IntentLabel(intent)
        except (ValueError, KeyError):
            intent = IntentLabel.UNKNOWN

    if intent in (IntentLabel.PREVIEW_LISTING, IntentLabel.UNKNOWN):
        lines.append("- 大表全表扫描必须有 LIMIT")

    if intent in (IntentLabel.KNN, IntentLabel.UNKNOWN):
        lines.append("")
        lines.append("## KNN 排序规则")
        lines.append("- 最近邻必须使用 PostGIS 索引算子: ORDER BY a.geometry <-> b.geometry LIMIT K")
        lines.append("- 不允许使用 ORDER BY ST_Distance(...) 进行排序；ST_Distance 只在 SELECT 中报告距离值")

    # Aggregation / Warehouse semantics — apply when query has aggregation intent
    # or when warehouse join hints exist (i.e., non-spatial multi-table query).
    # Also apply on SPATIAL_JOIN: spatial joins with COUNT/SUM frequently need
    # DISTINCT to prevent row-multiplication when one parent contains many children
    # (e.g. count buildings per historic district).
    has_warehouse_hints = bool(payload.get("warehouse_join_hints"))
    if intent in (IntentLabel.AGGREGATION, IntentLabel.SPATIAL_JOIN) or has_warehouse_hints:
        lines.append("")
        lines.append("## 聚合语义规则")
        lines.append("- COUNT(*) 计入所有行（包含 NULL），COUNT(col) 只计 col 非 NULL 的行；二者结果常不同。")
        lines.append("- COUNT(DISTINCT col) 只在题目明确要求“不同/独立/去重”时使用；默认计数用 COUNT(*) 或 COUNT(主键)。")
        lines.append("- 计算占比/比例（如 “百分之多少 / ratio / percentage”）时使用 SUM(CASE WHEN ... THEN 1 ELSE 0 END) * 1.0 / COUNT(*) 或 AVG(CASE...)；勿用整除。")
        lines.append("- 多表聚合时，先在 fact 表做聚合再 JOIN dim 表，避免重复计数膨胀。")
        lines.append("- \"每个 / per / 各 / 按...统计\" 等措辞需要 GROUP BY；GROUP BY 中所有非聚合 SELECT 列必须出现。")

        lines.append("")
        lines.append("## DISTINCT 使用规则")
        lines.append("- 当 JOIN 产生一对多关系时，若问题要求返回左侧实体列表，应按该实体的治理主键去重；不要把关联明细行数当成实体数。")
        lines.append("- 只有在 SELECT 中包含聚合函数（COUNT/SUM/AVG/MAX/MIN）时才不需要 DISTINCT（聚合本身已去重）。")
        lines.append("- 多表列表查询只有在关联会复制目标实体时才使用 SELECT DISTINCT；去重键必须来自当前 schema 的治理实体键。")
        lines.append("- **单表 COUNT(*) 不得擅自改成 COUNT(DISTINCT col)**：只有问题明确要求“不同/几类/去重”或语义层声明实体去重口径时，才使用 COUNT(DISTINCT <治理实体键>)。")

        lines.append("")
        lines.append("## 避免过度 JOIN")
        lines.append("- 如果所需的所有列和过滤条件都在同一张表中，不要引入额外的 JOIN。")
        lines.append("- 只有当 WHERE 条件或 SELECT 列确实需要另一张表的字段时才 JOIN。")
        lines.append("- 当多张表存在同名字段时，必须依据候选表别名、字段别名、描述和关系路径确定归属；证据不足时不要猜测。")

        lines.append("")
        lines.append("## 输出列格式")
        lines.append("- 除非问题或语义层明确要求拼接展示值，否则保留 schema 中的原始字段，不要凭示例发明派生列。")
        lines.append("- LIMIT 1 场景：如果问题要求 'the highest / the oldest / the youngest'，使用 ORDER BY ... LIMIT 1 而非子查询 WHERE col = (SELECT MAX/MIN...)。")

        # Date / temporal handling — BIRD heavily uses TEXT-stored dates
        lines.append("")
        lines.append("## 日期 / 时间处理规则")
        lines.append("- 若日期列为 TEXT 类型，使用字符串前缀比较或 LIKE 'YYYY-MM%' 进行月/年过滤，而不是直接 EXTRACT。")
        lines.append("- 取年份: SUBSTR(date_col, 1, 4) 或 CAST(SUBSTR(date_col,1,4) AS INTEGER)。")
        lines.append("- 取月份: SUBSTR(date_col, 6, 2)。")
        lines.append("- 真实 date / timestamp 列才使用 EXTRACT(YEAR FROM ...) / DATE_TRUNC。")
        lines.append("- 排序日期 TEXT 列时直接 ORDER BY 字符串即可（ISO 格式自然有序）。")

    return "\n".join(lines)


def _build_warehouse_join_hints(candidate_tables: list[dict]) -> dict | None:
    """Look up SemanticModelStore for candidate tables and build join-path hints.

    Builds both 1-hop (direct shared entity) and multi-hop (transitive via a
    pivot table that may not be in candidate_tables) join paths. Multi-hop
    paths are useful when fact-vs-fact joins require a bridging dimension.

    Returns a dict with table_roles, join_paths (1-hop strings), and
    multi_hop_paths (transitive bridge suggestions), or None if no models found.
    """
    store = SemanticModelStore()
    table_roles: dict[str, dict] = {}
    entity_map: dict[str, list[str]] = {}  # entity_name -> [table_names]

    for table in candidate_tables:
        tname = table.get("table_name", "")
        model = store.get(tname)
        if not model:
            continue
        entities = [e.get("name", "") for e in (model.get("entities") or [])]
        measures = [m.get("name", "") for m in (model.get("measures") or [])]
        role = "fact" if measures else "dimension"
        info: dict = {"role": role, "entities": entities}
        if measures:
            info["measures"] = measures
        table_roles[tname] = info
        for ent in entities:
            entity_map.setdefault(ent, []).append(tname)

    if not table_roles:
        return None

    # Build 1-hop join paths by matching shared entities across candidate tables
    join_paths: list[str] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for ent, tables in entity_map.items():
        if len(tables) < 2:
            continue
        facts = [t for t in tables if table_roles[t]["role"] == "fact"]
        dims = [t for t in tables if table_roles[t]["role"] == "dimension"]
        for f in facts:
            for d in dims:
                short_f = f.rsplit(".", 1)[-1] if "." in f else f
                short_d = d.rsplit(".", 1)[-1] if "." in d else d
                key = tuple(sorted([f, d])) + (ent,)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                join_paths.append(f"{short_f}.{ent} -> {short_d}.{ent}")
        for i, f1 in enumerate(facts):
            for f2 in facts[i + 1:]:
                short1 = f1.rsplit(".", 1)[-1] if "." in f1 else f1
                short2 = f2.rsplit(".", 1)[-1] if "." in f2 else f2
                key = tuple(sorted([f1, f2])) + (ent,)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                join_paths.append(f"{short1}.{ent} -> {short2}.{ent}")

    # Multi-hop: for every pair of candidate tables that do NOT share an entity
    # directly, search the registered model store for a pivot table that
    # joins them via two distinct entities (typical bridging dimension).
    multi_hop_paths: list[str] = []
    candidate_names = list(table_roles.keys())
    candidate_set = set(candidate_names)
    direct_pairs: set[tuple[str, str]] = set()
    for ent, tables in entity_map.items():
        for i, t1 in enumerate(tables):
            for t2 in tables[i + 1:]:
                direct_pairs.add(tuple(sorted([t1, t2])))

    if len(candidate_names) >= 2:
        try:
            all_models = store.list_active() or []
        except Exception:
            all_models = []
        # Index: entity_name -> set of model names (across ALL registered models)
        global_entity_index: dict[str, set[str]] = {}
        for m in all_models:
            mname = m.get("name") or m.get("source_table") or ""
            if not mname:
                continue
            for e in (m.get("entities") or []):
                ent_name = e.get("name") or e.get("column") or ""
                if ent_name:
                    global_entity_index.setdefault(ent_name, set()).add(mname)

        for i, t1 in enumerate(candidate_names):
            for t2 in candidate_names[i + 1:]:
                pair_key = tuple(sorted([t1, t2]))
                if pair_key in direct_pairs:
                    continue
                ents1 = set(table_roles[t1]["entities"])
                ents2 = set(table_roles[t2]["entities"])
                # Find a pivot model that contains at least one entity from each
                pivot_candidates: list[tuple[str, str, str]] = []
                # ent_a in t1 and pivot, ent_b in t2 and pivot
                for ent_a in ents1:
                    pivot_for_a = global_entity_index.get(ent_a, set())
                    for ent_b in ents2:
                        if ent_a == ent_b:
                            continue
                        pivot_for_b = global_entity_index.get(ent_b, set())
                        common = pivot_for_a & pivot_for_b
                        # Exclude the candidates themselves
                        common -= {t1, t2}
                        for pivot in common:
                            pivot_candidates.append((pivot, ent_a, ent_b))
                # Pick at most 2 pivot suggestions per pair to avoid prompt bloat
                for pivot, ent_a, ent_b in pivot_candidates[:2]:
                    short_t1 = t1.rsplit(".", 1)[-1]
                    short_t2 = t2.rsplit(".", 1)[-1]
                    short_pv = pivot.rsplit(".", 1)[-1]
                    multi_hop_paths.append(
                        f"{short_t1}.{ent_a} -> {short_pv}.{ent_a}; {short_pv}.{ent_b} -> {short_t2}.{ent_b}"
                    )

    result: dict = {"table_roles": table_roles, "join_paths": join_paths}
    if multi_hop_paths:
        result["multi_hop_paths"] = multi_hop_paths
    return result


def build_nl2sql_context(
    user_text: str,
    schema_filter: str | None = None,
    family: str | None = None,
    execution_engine: str | None = None,
) -> dict:
    """Build semantic + schema grounding payload for NL2SQL generation.

    Args:
        user_text: The natural language question.
        schema_filter: If provided (e.g. "bird_debit_card_specializing"), forces
            all tables from this schema to be included as candidates regardless
            of semantic matching. Used for warehouse benchmarks where the target
            schema is known a priori.
        family: LLM family name ('gemini' | 'deepseek' | 'qwen' | ...). Affects
            only the intent classification stage — DS/Qwen bypass the LLM judge
            per v6 Phase 1 attribution evidence. If None, reads env var
            NL2SQL_AGENT_FAMILY (set by the runner); defaults to None which
            preserves legacy Gemini-style behaviour.
    """
    import os as _ablation_os
    if _ablation_os.environ.get("NL2SQL_DISABLE_SEMANTIC") == "1":
        return {"grounding_prompt": "", "candidate_tables": [], "semantic": {},
                "intent": "unknown", "intent_source": "disabled",
                "few_shots": [], "sql_filters": []}
    # Family resolution order: explicit arg > env var > None (legacy behaviour)
    if family is None:
        family = _ablation_os.environ.get("NL2SQL_AGENT_FAMILY") or None
    intent_result = classify_intent(user_text, family=family)
    intent_value = getattr(intent_result.primary, "value", intent_result.primary)
    semantic = resolve_semantic_context(user_text)
    sources = list(semantic.get("sources") or [])
    # When schema_filter is set, remove sources from other schemas
    if schema_filter:
        sources = [s for s in sources if str(s.get("table_name", "")).startswith(f"{schema_filter}.")]
    sources = _rank_sources(user_text, sources, semantic)

    # Supplement: fuzzy-match additional tables not already resolved by semantic layer
    source_table_names = {s.get("table_name") for s in sources}
    source_list = list_semantic_sources()
    schema_hint = _extract_schema_hint(user_text) or schema_filter
    if source_list.get("status") == "success":
        source_by_table = {
            str(s.get("table_name") or ""): s
            for s in source_list.get("sources", [])
            if s.get("table_name")
        }
        sources = [
            _merge_source_metadata(s, source_by_table.get(str(s.get("table_name") or "")))
            for s in sources
        ]
        # Preserve every business role explicitly named by the question.  The
        # fuzzy supplement below intentionally keeps only two extra sources;
        # without this recall pass a KNN question mentioning buildings and
        # roads can lose the road relation to embedding-near POI/AOI sources.
        existing_by_table = {
            str(source.get("table_name") or ""): source
            for source in sources
            if source.get("table_name")
        }
        for catalog_source in source_list.get("sources", []):
            table_name = str(catalog_source.get("table_name") or "")
            if not table_name:
                continue
            if schema_filter and not table_name.startswith(f"{schema_filter}."):
                continue
            role_hits = _explicit_source_role_alias_hits(user_text, catalog_source)
            if role_hits <= 0:
                continue
            existing = existing_by_table.get(table_name)
            if existing is not None:
                existing["confidence"] = max(
                    float(existing.get("confidence") or 0.0),
                    0.8,
                )
                existing["_explicit_role_hits"] = role_hits
                continue
            recalled = dict(catalog_source)
            recalled["confidence"] = max(
                float(recalled.get("confidence") or 0.0),
                0.8,
            )
            recalled["_explicit_role_hits"] = role_hits
            sources.append(recalled)
            existing_by_table[table_name] = recalled
        source_table_names = set(existing_by_table)
        scored = []
        for source in source_list.get("sources", []):
            if source.get("table_name") in source_table_names:
                continue
            tname = str(source.get("table_name", ""))
            # When schema_filter is set, skip tables from other schemas entirely
            if schema_filter and not tname.startswith(f"{schema_filter}."):
                continue
            score = _score_source(user_text, source)
            # Boost tables matching the schema_filter (known target schema)
            if schema_filter and tname.startswith(f"{schema_filter}."):
                score += 1.0  # strong boost for known-schema tables
            elif schema_hint and tname.startswith(f"{schema_hint}."):
                score += 0.5
            if score > 0.05:
                s = dict(source)
                s["confidence"] = score
                scored.append(s)
        scored.sort(key=lambda s: s.get("confidence", 0), reverse=True)
        # When schema_filter is set, include more candidates (up to 8)
        top_n = 8 if schema_filter else 2
        sources.extend(scored[:top_n])
        sources = _rank_sources(user_text, sources, semantic)

    # LLM Schema Mapper backfill (Monkuu-style, opt-in via env var):
    # When substring/fuzzy matching produces too few high-confidence sources
    # (or zero), invoke an LLM call with the
    # full schema dump to select top-K relevant tables. This catches cases
    # where a business source alias cannot be matched to a physical table name
    # by substring/SequenceMatcher.
    # Modes:
    #   backfill (default): only invoke when len(high_conf_sources) < min_required
    #   merge:              invoke always; merge LLM result with substring result
    #   replace:            invoke always; ignore substring result
    try:
        from . import llm_schema_mapper as _lsm  # noqa: WPS433
    except ImportError:
        _lsm = None
    if _lsm is not None and _lsm.schema_mapper_enabled():
        try:
            mode = _lsm.schema_mapper_mode()
            high_conf_count = sum(1 for s in sources if s.get("confidence", 0) >= 0.6)
            min_required = int(_ablation_os.environ.get("NL2SQL_LLM_SCHEMA_MAPPER_MIN", "3"))
            should_invoke = (
                mode in ("merge", "replace")
                or (mode == "backfill" and high_conf_count < min_required)
            )
            if should_invoke:
                # Lazy schema dump: only fetch when actually invoking
                from data_agent.semantic_layer import list_semantic_sources as _lss
                _src_list = _lss().get("sources", []) if _lss else []
                valid_names = {str(s.get("table_name", "")).split(".")[-1]
                               for s in _src_list if s.get("table_name")}
                # Build a lightweight schema (table-name + col-list) from the
                # already-loaded source list to feed the mapper. Falls back to
                # a comma-separated table-name list if column info unavailable.
                schema_lines = []
                for s in _src_list[:50]:  # cap to avoid context blowup
                    tname = str(s.get("table_name", "")).split(".")[-1]
                    desc = (s.get("description") or "")[:120]
                    if tname:
                        schema_lines.append(f"- {tname}: {desc}" if desc else f"- {tname}")
                schema_dump = "\n".join(schema_lines) or "(no schema info)"
                topk = int(_ablation_os.environ.get("NL2SQL_LLM_SCHEMA_MAPPER_TOPK", "5"))
                model = _ablation_os.environ.get("NL2SQL_LLM_SCHEMA_MAPPER_MODEL", "gemini-2.5-flash")
                llm_picks = _lsm.select_relevant_tables(
                    user_text, schema_dump, top_k=topk, model=model,
                    valid_table_names=valid_names,
                )
                if llm_picks:
                    if mode == "replace":
                        sources = []
                    existing_tnames = {str(s.get("table_name", "")).split(".")[-1] for s in sources}
                    src_by_short = {
                        str(s.get("table_name", "")).split(".")[-1]: s
                        for s in _src_list
                    }
                    backfill_count = 0
                    for tname in llm_picks:
                        if tname in existing_tnames:
                            continue
                        full_src = src_by_short.get(tname)
                        if not full_src:
                            continue
                        new_src = dict(full_src)
                        # Mark with high but not absolute confidence so it
                        # competes naturally with substring matches.
                        new_src["confidence"] = 0.65
                        new_src["_via_llm_mapper"] = True
                        sources.append(new_src)
                        backfill_count += 1
                    if backfill_count:
                        sources = _rank_sources(user_text, sources, semantic)
                        # Prefer LLM-mapped sources slightly: stable sort with
                        # _via_llm_mapper getting a small bonus on ties
        except Exception as _exc:  # never break grounding on mapper failure
            import logging as _lg
            _lg.getLogger(__name__).warning(f"[SchemaMapper] backfill failed: {_exc}")

    major_project_context = _has_major_project_grounding_context(user_text, semantic)
    kg_hints = {}
    if major_project_context:
        kg_hints = _normalize_kg_hints(
            _resolve_major_project_kg_hints(
                user_text,
                semantic=semantic,
                intent=intent_value,
            )
        )
    if kg_hints:
        kg_sources = _kg_hint_sources(kg_hints, sources, schema_filter)
        if kg_sources:
            sources.extend(kg_sources)
            sources = _rank_sources(user_text, sources, semantic)

    candidate_tables = []
    ascii_heavy = _is_ascii_heavy(user_text)
    spatial_query = bool(
        semantic.get("spatial_ops")
        or semantic.get("region_filter")
        or _intent_requires_spatial_sources(str(intent_value or ""))
    )
    if not schema_filter and not major_project_context:
        sources = _prune_unqualified_major_project_sources(user_text, sources)
    if not schema_filter:
        sources = _prune_cross_domain_noise(user_text, sources)
    # Spatial joins often need a subject layer, a relation layer, and one or
    # two semantic bridge layers (for example parcel + POI + road + admin).
    # Keep ordinary spatial prompts tight, but allow one additional governed
    # candidate for SPATIAL_JOIN so a valid relation is not discarded before
    # the LLM sees the schema.
    spatial_source_limit = 4 if intent_value == IntentLabel.SPATIAL_JOIN.value else 3
    source_limit = 5 if not spatial_query else spatial_source_limit
    if schema_filter:
        source_limit = 8  # warehouse benchmarks may have many tables per schema
    selected_sources = _select_with_kg_priority(sources, source_limit, kg_hints, schema_filter)
    for source in selected_sources:
        table_name = source.get("table_name")
        if not table_name:
            continue
        schema = describe_table_semantic(table_name)
        if schema.get("status") != "success":
            continue
        candidate_tables.append(_build_candidate_table(source, schema))

    # Enrich non-geometry text columns with sample values for warehouse queries
    if ascii_heavy and not spatial_query:
        _TEXT_TYPES = {"text", "character varying", "varchar"}
        for table in candidate_tables:
            tname = table.get("table_name", "")
            for col in table.get("columns", []):
                if col.get("is_geometry"):
                    continue
                pg_type = (col.get("pg_type") or "").lower()
                if any(t in pg_type for t in _TEXT_TYPES):
                    vals = _sample_distinct_values(tname, col["column_name"], limit=8)
                    if vals and len(vals) <= 20:
                        col["sample_values"] = vals

    # Limit candidate tables: more for warehouse (need full schema for join hints)
    max_candidates = 5 if schema_filter else spatial_source_limit if spatial_query else 3
    candidate_tables = _select_with_kg_priority(
        _rank_candidate_tables(user_text, candidate_tables, semantic),
        max_candidates,
        kg_hints,
        schema_filter,
    )

    # --- Sensitivity-based access control ---
    # Filter tables by user role. Admin sees all; analyst sees up to internal;
    # viewer sees only public. Anonymous/test contexts skip filtering.
    from .user_context import current_user_role
    role = current_user_role.get() or "anonymous"
    if role in _ROLE_MAX_SENSITIVITY and role != "admin":
        pre_filter_count = len(candidate_tables)
        candidate_tables = [
            t for t in candidate_tables
            if _table_accessible(t.get("table_name", ""), role)
        ]
        if len(candidate_tables) < pre_filter_count:
            logger.info(
                "[NL2SQL] Sensitivity filter: %d/%d tables accessible for role=%s",
                len(candidate_tables), pre_filter_count, role,
            )

    kg_hints = _normalize_kg_hints_for_candidate_tables(
        kg_hints,
        {str(t.get("table_name") or "") for t in candidate_tables},
    )

    # Build warehouse join hints from SemanticModelStore (non-spatial only)
    warehouse_join_hints = None
    if not spatial_query:
        warehouse_join_hints = _build_warehouse_join_hints(candidate_tables)

    few_shot_text = ""
    few_shot_hits: list[dict] = []
    import os as _abl_os

    local_provider = _abl_os.environ.get("GDA_LLM_PROVIDER", "").strip().casefold()
    few_shot_setting = _abl_os.environ.get("GDA_NL2SQL_LOCAL_FEWSHOT", "1").strip().casefold()
    # The paper's embedding-retrieval + few-shot step is part of the default
    # NL2Semantic2SQL contract, including local Qwen/Ollama deployments. Sites
    # with no embedding service can opt out explicitly; retrieval itself is
    # non-fatal and returns an empty section when the service is unavailable.
    local_few_shot_enabled = few_shot_setting not in {"0", "false", "off", "disabled"}
    if local_provider not in {"ollama", "lm_studio", "openai_compatible"}:
        local_few_shot_enabled = True
    if (
        _abl_os.environ.get("NL2SQL_DISABLE_FEWSHOT") != "1"
        and local_few_shot_enabled
        and _should_fetch_few_shots(user_text, candidate_tables, semantic)
    ):
        preferred_domain = (
            str(candidate_tables[0].get("table_name") or "")
            if candidate_tables
            else None
        )
        few_shot_bundle = fetch_nl2sql_few_shots(
            user_text,
            top_k=3,
            domain_id=preferred_domain,
            execution_engine=execution_engine or "postgis",
            include_metadata=True,
        )
        if isinstance(few_shot_bundle, dict):
            few_shot_text = str(few_shot_bundle.get("prompt") or "")
            few_shot_hits = list(few_shot_bundle.get("hits") or [])
        else:
            # Compatibility for custom providers and tests that still return
            # the historical formatted string.
            few_shot_text = str(few_shot_bundle or "")

        # A reviewed example is evidence for the logical relation, but it is
        # not permission to use an arbitrary physical table. Add only tables
        # that are present in the governed semantic-source catalog and are
        # enabled for this NL2SQL route. This closes the common gap where the
        # resolver finds the POI side of a spatial query while the reviewed
        # JOIN example correctly identifies the parcel side.
        referenced_by_fewshot: list[dict] = []
        if few_shot_hits and source_list.get("status") == "success":
            source_by_name = {
                str(item.get("table_name") or "").casefold(): item
                for item in source_list.get("sources", [])
                if item.get("table_name")
            }
            candidate_names = {
                str(item.get("table_name") or "").casefold()
                for item in candidate_tables
            }
            # Only the highest-scoring reviewed example may expand Schema
            # grounding. Lower-ranked examples remain useful demonstrations,
            # but forcing all their tables can re-introduce unrelated domains.
            for hit in few_shot_hits[:1]:
                hit_engine = {
                    str(tag).casefold().split(":", 1)[1]
                    for tag in (hit.get("tags") or [])
                    if str(tag).casefold().startswith("engine:") and ":" in str(tag)
                }
                if execution_engine and hit_engine and execution_engine.casefold() not in hit_engine:
                    continue
                for name in _extract_sql_table_names(str(hit.get("sql") or "")):
                    source = source_by_name.get(name.casefold())
                    if not source or source.get("nl2sql_enabled", True) is False:
                        continue
                    key = str(source.get("table_name") or "").casefold()
                    if key in candidate_names:
                        continue
                    schema = describe_table_semantic(str(source.get("table_name")))
                    if schema.get("status") != "success":
                        continue
                    enriched_source = dict(source)
                    enriched_source["confidence"] = max(
                        float(enriched_source.get("confidence") or 0), 0.72
                    )
                    enriched_source["_via_few_shot"] = True
                    candidate = _build_candidate_table(enriched_source, schema)
                    candidate["_via_few_shot"] = True
                    referenced_by_fewshot.append(candidate)
                    candidate_names.add(key)

            if referenced_by_fewshot:
                ranked = _rank_candidate_tables(
                    user_text,
                    candidate_tables + referenced_by_fewshot,
                    semantic,
                )
                forced = [item for item in ranked if item.get("_via_few_shot")]
                remaining = [item for item in ranked if not item.get("_via_few_shot")]
                candidate_tables = (forced + remaining)[:max_candidates]
                logger.info(
                    "[NL2SQL] Added %d governed few-shot table references to grounding",
                    len(forced),
                )
    few_shots = [
        {
            "question": hit.get("question") or "参考查询示例",
            "sql": hit.get("sql") or "",
            "score": hit.get("score"),
            "domain_id": hit.get("domain_id"),
            "source": hit.get("source"),
            "tags": hit.get("tags") or [],
        }
        for hit in few_shot_hits
        if hit.get("sql")
    ]
    if few_shot_text and not few_shots:
        few_shots.append({"question": "参考查询示例", "sql": few_shot_text})

    payload = {
        "user_question": user_text,
        "candidate_tables": candidate_tables,
        "semantic_hints": {
            "spatial_ops": semantic.get("spatial_ops") or [],
            "region_filter": semantic.get("region_filter"),
            "hierarchy_matches": semantic.get("hierarchy_matches") or [],
            "metric_hints": semantic.get("metric_hints") or [],
            "sql_filters": semantic.get("sql_filters") or [],
        },
        "table_hints": semantic.get("table_hints") or [],
        "column_hints": semantic.get("column_hints") or {},
        "large_tables": [
            t["table_name"] for t in candidate_tables
            if int(t.get("row_count_hint", 0) or 0) >= 1_000_000
        ],
        "few_shots": few_shots,
        "kg_hints": kg_hints,
        "intent": intent_result.primary,
        "intent_secondary": [lbl.value for lbl in intent_result.secondary],
        "intent_confidence": intent_result.confidence,
        "intent_source": intent_result.source,
        "few_shot_policy": {
            "enabled": local_few_shot_enabled
            and _abl_os.environ.get("NL2SQL_DISABLE_FEWSHOT") != "1",
            "setting": few_shot_setting,
            "provider": local_provider or "default",
            "execution_engine": execution_engine or "postgis",
            "triggered": _should_fetch_few_shots(user_text, candidate_tables, semantic),
            "retrieved": bool(few_shot_text),
            "domain_id": (
                str(candidate_tables[0].get("table_name") or "")
                if candidate_tables
                else None
            ),
            "hit_count": len(few_shot_hits) if few_shot_hits else len(few_shots),
            "hits": [
                {
                    "id": hit.get("id"),
                    "score": hit.get("score"),
                    "domain_id": hit.get("domain_id"),
                    "source": hit.get("source"),
                    "tags": hit.get("tags") or [],
                }
                for hit in few_shot_hits
            ],
        },
    }
    if warehouse_join_hints:
        payload["warehouse_join_hints"] = warehouse_join_hints

    # v7 P1 observability: surface how many data-driven hints were injected so
    # cross-family sanity probes can verify the semantic-layer path is live
    # BEFORE committing to the 12h matrix. Zero hints for a question that
    # names physical tables is a strong signal of a fallback / trigger-keyword
    # miss rather than model incompetence.
    _hint_stats = {
        "table_hints": len(payload.get("table_hints") or []),
        "column_hints": sum(len(v) for v in (payload.get("column_hints") or {}).values()),
        "large_tables": len(payload.get("large_tables") or []),
        "candidate_tables": len(candidate_tables),
        "few_shots": len(few_shots),
        "few_shot_enabled": bool(payload.get("few_shot_policy", {}).get("enabled")),
        "few_shot_triggered": bool(payload.get("few_shot_policy", {}).get("triggered")),
        "few_shot_retrieved": bool(payload.get("few_shot_policy", {}).get("retrieved")),
        "family": family or "default",
    }
    payload["_hint_injection_stats"] = _hint_stats
    logger.info(
        "[NL2SQL grounding] injected hints: tables=%d columns=%d large_tables=%d "
        "candidates=%d few_shots=%d family=%s",
        _hint_stats["table_hints"], _hint_stats["column_hints"],
        _hint_stats["large_tables"], _hint_stats["candidate_tables"],
        _hint_stats["few_shots"], _hint_stats["family"],
    )
    payload["grounding_prompt"] = _format_grounding_prompt(payload, family=family)
    return payload
