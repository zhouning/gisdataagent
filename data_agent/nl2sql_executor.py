"""Executor tools for NL2SQL Phase 2: prepare grounding, execute with self-correction, auto-curate."""
from __future__ import annotations

import json
import os
import re
import time

from .nl2sql_grounding import (
    _estimate_table_size,
    _needs_quoting,
    _quoted_ref,
    _table_aliases_from_source,
    build_nl2sql_context,
)
from .semantic_layer import describe_table_semantic, list_semantic_sources
from .sql_postprocessor import postprocess_sql
from .toolsets.nl2sql_tools import execute_safe_sql
from .user_context import (
    current_nl2sql_intent,
    current_nl2sql_large_tables,
    current_nl2sql_question,
    current_nl2sql_schemas,
)

# Backward-compatible names used in tests / plan prose
_cached_schemas = current_nl2sql_schemas
_cached_large_tables = current_nl2sql_large_tables

MAX_RETRIES = 2


def _strip_fences(s: str) -> str:
    """Strip markdown code fences from LLM output."""
    s = (s or "").strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s


def _schemas_and_large_tables(payload: dict) -> tuple[dict, set[str]]:
    """Extract postprocessor inputs from an NL2SQL grounding payload."""
    schemas = {}
    large_tables: set[str] = set()
    for table in payload.get("candidate_tables", []) or []:
        name = table.get("table_name")
        if not name:
            continue
        schemas[name] = table.get("columns", [])
        if int(table.get("row_count_hint", 0) or 0) >= 1_000_000:
            large_tables.add(name)
    return schemas, large_tables


def _referenced_sql_tables(sql: str) -> list[str]:
    """Extract FROM/JOIN table references from generated SQL.

    Best-effort and conservative: CTE names or subqueries may be returned, but
    later describe_table_semantic() validation filters out non-real tables.
    """
    refs: list[str] = []
    pattern = re.compile(
        r'\b(?:FROM|JOIN)\s+(?!\()(?P<table>(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)(?:\.(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*))?)',
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(sql or ""):
        raw = match.group("table")
        parts = [p.strip().strip('"') for p in raw.split(".") if p.strip()]
        if not parts:
            continue
        table = ".".join(parts)
        if table.lower() in {"select", "with", "where", "lateral"}:
            continue
        if table not in refs:
            refs.append(table)
    return refs


def _candidate_from_described_schema(table_name: str, schema: dict) -> dict:
    source_meta = schema.get("source_metadata") or {}
    geometry_type = schema.get("geometry_type") or source_meta.get("geometry_type")
    srid = schema.get("srid") or source_meta.get("srid") or 0
    columns = []
    for col in schema.get("columns", []) or []:
        column_name = col.get("column_name", "")
        if not column_name:
            continue
        pg_type = col.get("data_type") or col.get("udt_name") or ""
        is_geom = bool(col.get("is_geometry", False))
        if not is_geom and pg_type == "USER-DEFINED" and column_name.lower() in {
            "geometry", "geom", "the_geom", "shape",
        }:
            is_geom = True
        if is_geom:
            pg_type = f"geometry({geometry_type or 'Geometry'},{srid or 0})"
        columns.append({
            "column_name": column_name,
            "pg_type": pg_type,
            "quoted_ref": _quoted_ref(column_name),
            "aliases": col.get("aliases") or [],
            "semantic_domain": col.get("semantic_domain"),
            "unit": col.get("unit") or "",
            "description": col.get("description") or "",
            "is_geometry": is_geom,
            "needs_quoting": _needs_quoting(column_name),
            "value_semantics": col.get("value_semantics") or {},
            "sample_values": [],
        })
    return {
        "table_name": table_name,
        "display_name": source_meta.get("display_name") or schema.get("display_name") or table_name,
        "description": source_meta.get("description") or schema.get("description") or "",
        "table_aliases": _table_aliases_from_source({"table_name": table_name}, schema),
        "confidence": 0.5,
        "columns": columns,
        "row_count_hint": _estimate_table_size(table_name),
        "schema_complete": True,
        "_via_sql_reference": True,
    }


def _describe_physical_table(table_name: str) -> dict:
    """Describe a real PostgreSQL table when semantic registry lookup fails."""
    cleaned = str(table_name or "").strip().strip('"')
    if not cleaned:
        return {"status": "error", "error": "empty table name"}
    if "." in cleaned:
        schema_name, bare_table = [part.strip().strip('"') for part in cleaned.rsplit(".", 1)]
    else:
        schema_name, bare_table = "public", cleaned

    try:
        from data_agent.db_engine import get_engine
        from sqlalchemy import text

        engine = get_engine()
        if engine is None:
            return {"status": "error", "error": "database engine unavailable"}

        with engine.connect() as conn:
            col_rows = conn.execute(text(
                "SELECT column_name, data_type, udt_name "
                "FROM information_schema.columns "
                "WHERE table_schema=:schema_name AND table_name=:table_name "
                "ORDER BY ordinal_position"
            ), {"schema_name": schema_name, "table_name": bare_table}).fetchall()
            geom_rows = conn.execute(text(
                "SELECT f_geometry_column, type, srid "
                "FROM geometry_columns "
                "WHERE f_table_schema=:schema_name AND f_table_name=:table_name"
            ), {"schema_name": schema_name, "table_name": bare_table}).fetchall()
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300]}

    if not col_rows:
        return {"status": "error", "error": f"table not found: {schema_name}.{bare_table}"}

    geom_meta = {
        row[0]: {"geometry_type": row[1], "srid": int(row[2] or 0)}
        for row in geom_rows
        if row and row[0]
    }
    columns = []
    for column_name, data_type, udt_name in col_rows:
        is_geom = column_name in geom_meta or (
            str(data_type).upper() == "USER-DEFINED"
            and str(column_name).lower() in {"geometry", "geom", "the_geom", "shape"}
        )
        aliases: list[str] = []
        if is_geom:
            for alias in ("geometry", "geom", "shape"):
                if alias != str(column_name).lower():
                    aliases.append(alias)
        columns.append({
            "column_name": column_name,
            "data_type": data_type,
            "udt_name": udt_name,
            "is_geometry": is_geom,
            "aliases": aliases,
            "value_semantics": {},
        })

    first_geom = next(iter(geom_meta.values()), {})
    return {
        "status": "success",
        "table_name": bare_table,
        "geometry_type": first_geom.get("geometry_type"),
        "srid": first_geom.get("srid") or 0,
        "columns": columns,
    }


def _augment_payload_with_sql_referenced_tables(sql: str, payload: dict) -> dict:
    """Add real SQL-referenced tables missing from the initial top-k context."""
    candidate_tables = payload.setdefault("candidate_tables", [])
    existing = {
        t.get("table_name")
        for t in candidate_tables
        if t.get("table_name")
    }
    existing.update(t.split(".")[-1] for t in list(existing))
    added = 0
    for table_name in _referenced_sql_tables(sql):
        if table_name in existing or table_name.split(".")[-1] in existing:
            added += _add_versioned_sibling_candidate(table_name, candidate_tables, existing)
            continue
        schema = describe_table_semantic(table_name)
        if schema.get("status") != "success" and "." in table_name:
            schema = describe_table_semantic(table_name.split(".")[-1])
            table_name = table_name.split(".")[-1]
        if schema.get("status") != "success":
            schema = _describe_physical_table(table_name)
        if schema.get("status") != "success":
            continue
        candidate_tables.append(_candidate_from_described_schema(table_name, schema))
        existing.add(table_name)
        existing.add(table_name.split(".")[-1])
        added += 1
        added += _add_versioned_sibling_candidate(table_name, candidate_tables, existing)
    if added:
        stats = payload.setdefault("_hint_injection_stats", {})
        stats["candidate_tables"] = len(candidate_tables)
        stats["sql_referenced_tables_added"] = added
    return payload


def _add_versioned_sibling_candidate(
    table_name: str,
    candidate_tables: list[dict],
    existing: set[str],
) -> int:
    """Hydrate latest registered versioned sibling for a generic SQL table ref.

    If the model emits FROM roads while the semantic layer also knows
    roads_2021, adding the sibling lets the existing versioned-table
    rewrite prefer the registered snapshot without hardcoding CQ table names.
    """
    sibling = _latest_registered_versioned_sibling(table_name)
    if not sibling or sibling in existing or sibling.split(".")[-1] in existing:
        return 0
    schema = describe_table_semantic(sibling)
    if schema.get("status") != "success":
        return 0
    candidate_tables.append(_candidate_from_described_schema(sibling, schema))
    existing.add(sibling)
    existing.add(sibling.split(".")[-1])
    return 1


def _latest_registered_versioned_sibling(table_name: str) -> str | None:
    bare = table_name.split(".")[-1]
    if _version_suffix_year(bare):
        return None
    try:
        sources = list_semantic_sources()
    except Exception:
        return None
    if sources.get("status") != "success":
        return None
    prefix = f"{bare}_"
    matches: list[tuple[int, str]] = []
    for source in sources.get("sources", []) or []:
        source_name = str(source.get("table_name") or "")
        source_bare = source_name.split(".")[-1]
        if not source_bare.startswith(prefix):
            continue
        year = _version_suffix_year(source_bare)
        if year:
            matches.append((year, source_name))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _version_suffix_year(table_name: str) -> int:
    m = re.search(r"_(?P<year>(?:19|20)\d{2})$", table_name or "")
    return int(m.group("year")) if m else 0


def _find_ungrounded_sql_reference(question: str, sql: str, payload: dict) -> str:
    """Return a SQL table reference not grounded by the original semantic context.

    Gemma/Ollama can name a real table from model memory even when the semantic
    context chose a different table. A real table is not automatically a
    grounded table, so this harness check runs before SQL-referenced table
    hydration. It stays productized by relying on candidate tables and explicit
    table-token mentions rather than dataset-specific names.
    """
    allowed = _payload_table_ref_terms(payload)
    for table_ref in _referenced_sql_tables(sql):
        terms = _table_ref_terms(table_ref)
        if terms & allowed:
            continue
        if _question_mentions_table_ref(question, table_ref):
            continue
        return table_ref
    return ""


def _payload_table_ref_terms(payload: dict) -> set[str]:
    terms: set[str] = set()
    for table in payload.get("candidate_tables", []) or []:
        table_name = str(table.get("table_name") or "")
        terms.update(_table_ref_terms(table_name))
    return terms


def _table_ref_terms(table_ref: str) -> set[str]:
    ref = str(table_ref or "").strip().strip('"')
    if not ref:
        return set()
    bare = ref.split(".")[-1]
    terms = {_normalize_identifier_like(ref), _normalize_identifier_like(bare)}
    versionless = re.sub(r"_(?:19|20)\d{2}$", "", bare)
    terms.add(_normalize_identifier_like(versionless))
    return {term for term in terms if term}


def _question_mentions_table_ref(question: str, table_ref: str) -> bool:
    q_low = (question or "").lower()
    for term in _table_ref_terms(table_ref):
        if term and re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", q_low):
            return True
    bare = str(table_ref or "").split(".")[-1].lower()
    for token in re.split(r"[_\W]+", bare):
        if len(token) < 3 or token.isdigit() or token in {"public", "data"}:
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])", q_low):
            return True
    return False


def _build_ungrounded_table_retry_prompt(
    question: str,
    payload: dict,
    sql: str,
    table_ref: str,
    family: str = "gemma",
) -> str:
    allowed = sorted(
        str(t.get("table_name") or "")
        for t in payload.get("candidate_tables", []) or []
        if t.get("table_name")
    )
    return (
        _build_family_semantic_prompt(family, question, payload)
        + "\n\nHarness correction:\n"
        + f"- Previous SQL referenced `{table_ref}`, which is not grounded by the candidate schema.\n"
        + f"- Use only these candidate tables: {', '.join(allowed) or '(none)'}.\n"
        + "- If the question cannot be answered from those candidate tables, output SELECT 1.\n"
        + "- Output SQL only.\n\n"
        + f"Previous SQL:\n{sql}\n"
    )


def _extract_sql(text: str) -> str:
    """Extract the most recent complete top-level SELECT/WITH statement."""
    sql = _strip_fences(text)
    sql = re.sub(r"^\s*(?:sql\s*:|SQL\s*:)", "", sql).strip()
    starts = _top_level_sql_starts(sql)
    candidates = [_slice_sql_statement(sql, start) for start in starts]
    candidates = [candidate for candidate in candidates if candidate]
    for candidate in reversed(candidates):
        if candidate.upper().startswith("WITH") or re.search(r"\bFROM\b", candidate, flags=re.IGNORECASE):
            return candidate

    matches = list(re.finditer(r"\b(SELECT|WITH)\b", sql, flags=re.IGNORECASE))
    if not matches:
        return sql or "SELECT 1"
    nested_candidates: list[str] = []
    for match in matches:
        candidate = sql[match.start():].strip()
        if ";" in candidate:
            candidate = candidate.split(";", 1)[0].strip()
        if candidate:
            nested_candidates.append(candidate)
    for candidate in reversed(nested_candidates):
        if _looks_like_select_sql(candidate) and _sql_candidate_parseable(candidate):
            return candidate
    for candidate in reversed(nested_candidates):
        if candidate.upper().startswith("WITH") or re.search(r"\bFROM\b", candidate, flags=re.IGNORECASE):
            return candidate
    return nested_candidates[-1] if nested_candidates else "SELECT 1"


def _top_level_sql_starts(sql: str) -> list[int]:
    starts: list[int] = []
    depth = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    in_top_level_with_statement = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
            elif ch == "'":
                in_single = False
                i += 1
            else:
                i += 1
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
            elif ch == '"':
                in_double = False
                i += 1
            else:
                i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if ch == ";" and depth == 0:
            in_top_level_with_statement = False
            i += 1
            continue
        if depth == 0:
            if re.match(r"\bWITH\b", sql[i:], flags=re.IGNORECASE):
                starts.append(i)
                in_top_level_with_statement = True
            elif (
                not in_top_level_with_statement
                and re.match(r"\bSELECT\b", sql[i:], flags=re.IGNORECASE)
            ):
                starts.append(i)
        i += 1
    return starts


def _slice_sql_statement(sql: str, start: int) -> str:
    depth = 0
    in_single = False
    in_double = False
    i = start
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            return sql[start:i].strip()
        i += 1
    return sql[start:].strip()


def _looks_like_select_sql(sql: str) -> bool:
    text = (sql or "").lstrip()
    return bool(
        text.upper().startswith("WITH")
        or (text.upper().startswith("SELECT") and re.search(r"\bFROM\b", text, flags=re.IGNORECASE))
    )


def _sql_candidate_parseable(sql: str) -> bool:
    try:
        import sqlglot

        return sqlglot.parse_one(sql, dialect="postgres") is not None
    except Exception:
        return False


def _get_standard_model_name() -> str:
    eval_model = os.environ.get("NL2SQL_AGENT_MODEL")
    if eval_model:
        return eval_model
    try:
        from .model_config import get_config_manager
        model_name = get_config_manager().get_tier_model("standard")
        if model_name:
            return model_name
    except Exception:
        pass
    return os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")


def _active_direct_harness_family() -> str:
    """Return the family namespace for the direct NL2Semantic2SQL harness."""
    family = (os.environ.get("NL2SQL_AGENT_FAMILY") or "").strip().lower()
    if family in {"gemma", "qwen"}:
        return family
    model_name = (os.environ.get("NL2SQL_AGENT_MODEL") or "").strip().lower()
    if "qwen" in model_name:
        return "qwen"
    return "gemma"


def _build_gemma_semantic_prompt(question: str, payload: dict) -> str:
    """Build a Gemma/Ollama prompt for one-shot semantic SQL generation."""
    return _build_family_semantic_prompt("gemma", question, payload)


def _build_family_semantic_prompt(family: str, question: str, payload: dict) -> str:
    """Build a local-family prompt for one-shot semantic SQL generation."""
    grounding = payload.get("grounding_prompt") or ""
    stats = payload.get("_hint_injection_stats") or {}
    family_notes = _family_harness_notes(family)
    return f"""You are the GIS Data Agent NL2Semantic2SQL executor.
Convert the user question into one read-only PostgreSQL/PostGIS SQL statement.

Rules:
- Output SQL only: no Markdown, no explanation.
- Only SELECT or WITH ... SELECT is allowed. If the request needs writes, DDL, permissions, or cannot be answered from the candidate schema, output SELECT 1.
- Read-only preview/listing/export/download/backup requests over available tables are answerable as SELECT statements; add a conservative LIMIT instead of outputting SELECT 1.
- Table names and column names must come from the semantic context below. Preserve quoted identifiers for case-sensitive or non-ASCII columns.
- Use PostGIS functions for spatial relations. Align SRIDs when the semantic context shows different geometry SRIDs.
- Apply business rules, aliases, units, value semantics, and examples from the semantic context. Do not invent dataset-specific columns.
- For joined entity counts, count the target entity once when an identifier column is available.
{family_notes}

User question:
{question}

Semantic candidate context:
{grounding}

Semantic injection stats:
{json.dumps(stats, ensure_ascii=False)}
"""


def _family_harness_notes(family: str) -> str:
    family_l = (family or "").lower()
    if family_l != "qwen":
        return ""
    return """
Qwen family harness notes:
- Do not append clauses after a semicolon. Output one complete SQL statement; never put AND, OR, or WHERE after LIMIT ...;.
- If the semantic context says the geometry column is `shape`, use `shape`, not `geometry`; if it says `geometry`, use `geometry`.
- Use ST_Contains, ST_Within, and ST_Intersects with geometry operands. Use geography casts for ST_DWithin, ST_Distance, ST_Area, or ST_Length; ST_Contains(...::geography, ...::geography) is invalid, not geography.
- For write/destructive requests output SELECT 1 only; never generate DELETE, UPDATE, DROP, INSERT, ALTER, TRUNCATE, or a SELECT wrapper around them.
""".rstrip()


def _build_safe_preview_sql(question: str, payload: dict) -> str:
    """Build a conservative SELECT for read-only all-record preview requests."""
    q_low = (question or "").lower()
    preview_tokens = (
        "download", "export", "backup", "all rows", "all records", "preview",
        "show all", "下载", "导出", "备份", "全部", "所有", "全表", "看看", "查看",
        "展示",
    )
    if not any(token in q_low for token in preview_tokens):
        return ""
    candidate_tables = payload.get("candidate_tables", []) or []
    if not candidate_tables:
        return ""
    table = _select_preview_table(question, candidate_tables)
    if not table:
        return ""
    table_name = table.get("table_name")
    if not table_name:
        return ""
    columns = _select_preview_columns(question, table)
    limit = _extract_preview_limit(question) or 1000
    return f"SELECT {columns} FROM {table_name} LIMIT {limit}"


def _select_preview_table(question: str, candidate_tables: list[dict]) -> dict | None:
    if len(candidate_tables) == 1:
        return candidate_tables[0]
    q_low = (question or "").lower()
    wants_geometry = any(term in q_low for term in ("坐标", "coordinate", "coordinates", "geometry", "geom", "位置"))
    scored: list[tuple[float, int, dict]] = []
    for table in candidate_tables:
        name = str(table.get("table_name") or "")
        score = float(table.get("confidence") or 0)
        if name and name.lower() in q_low:
            score += 100
        bare = name.split(".")[-1]
        if bare and bare.lower() in q_low:
            score += 100
        if "poi" in q_low and "poi" in name.lower():
            score += 25
        if wants_geometry and any(col.get("is_geometry") for col in table.get("columns", []) or []):
            score += 20
        preview_cols = _select_preview_columns(question, table)
        if preview_cols and preview_cols != "*":
            score += len(preview_cols.split(",")) * 2
        if score > 0:
            scored.append((score, -len(scored), table))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[0][2]


def _select_preview_columns(question: str, table: dict) -> str:
    q_low = (question or "").lower()
    column_terms = ("name", "名称", "坐标", "coordinate", "coordinates", "geometry", "geom", "位置")
    has_column_request = any(term in q_low for term in column_terms)
    if not has_column_request:
        return "*"

    selected_non_geom: list[str] = []
    selected_geom: list[str] = []
    wants_geometry = any(term in q_low for term in ("坐标", "coordinate", "coordinates", "geometry", "geom", "位置"))
    for col in table.get("columns", []) or []:
        col_name = str(col.get("column_name") or "")
        if not col_name:
            continue
        ref = col.get("quoted_ref") or _quoted_ref(col_name)
        if col.get("is_geometry"):
            if wants_geometry:
                selected_geom.append(ref)
            continue
        probes = [col_name, str(col.get("quoted_ref") or "")]
        probes.extend(str(a) for a in (col.get("aliases") or []))
        vs = col.get("value_semantics") or {}
        probes.extend(str(a) for a in (vs.get("sql_aliases") or []))
        if any(probe and len(probe) >= 2 and probe.lower().strip('"') in q_low for probe in probes):
            selected_non_geom.append(ref)

    selected = list(dict.fromkeys(selected_non_geom + selected_geom))
    return ", ".join(selected) if selected else "*"


def _extract_preview_limit(question: str) -> int | None:
    patterns = [
        r"\bLIMIT\s+(\d{1,5})\b",
        r"\btop\s+(\d{1,5})\b",
        r"\bfirst\s+(\d{1,5})\b",
        r"前\s*(\d{1,5})\s*(?:条|个|行)?",
    ]
    for pattern in patterns:
        m = re.search(pattern, question or "", flags=re.IGNORECASE)
        if not m:
            continue
        try:
            value = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if 0 < value <= 10000:
            return value
    return None


def _should_refuse_nl2sql_question(question: str, payload: dict) -> bool:
    q_low = (question or "").lower()
    write_tokens = (
        "delete", "update", "insert", "drop", "truncate", "alter", "create table",
        "vacuum", "reindex", "cluster", "grant", "revoke", "rename",
        "删掉", "删除", "更新", "修改", "改成", "写入", "插入", "清空", "覆盖",
        "置为 null", "置为NULL", "执行 vacuum", "执行vacuum", "回收空间",
    )
    if any(token in q_low for token in write_tokens):
        return True

    if _has_missing_explicit_table_request(question, payload):
        return True

    if _has_missing_explicit_column_request(question, payload):
        return True

    if (
        _payload_intent_is_unknown(payload)
        and not _build_safe_preview_sql(question, payload)
        and _has_ungrounded_explicit_metric_request(question, payload)
    ):
        return True

    ranking_terms = _extract_ranking_metric_terms(question)
    if ranking_terms:
        return not _payload_has_column_term(payload, tuple(ranking_terms))
    return False


def _extract_ranking_metric_terms(question: str) -> list[str]:
    q = question or ""
    terms: list[str] = []
    computable_terms = (
        "数量", "条数", "个数", "次数", "面积", "距离", "名称", "名字", "objectid",
        "count", "sum", "total", "area", "distance", "name",
    )
    for match in re.finditer(r"([\u4e00-\u9fffA-Za-z_ ]{2,24})\s*(?:排名|排行)", q):
        term = match.group(1).strip(" 的按根据所有全部各个")
        term_low = term.lower()
        if term and not any(t in term_low for t in computable_terms):
            terms.append(term)
    for match in re.finditer(r"\b([A-Za-z][A-Za-z_ ]{2,40}?)\s+(?:ranking|rank|top)\b", q, re.IGNORECASE):
        term = match.group(1).strip()
        if term:
            terms.append(term)
    return list(dict.fromkeys(terms))


def _payload_has_column_term(payload: dict, terms: tuple[str, ...]) -> bool:
    lowered_terms = [
        term for term in (_normalize_semantic_search_term(term) for term in terms)
        if term
    ]
    for table in payload.get("candidate_tables", []) or []:
        for col in table.get("columns", []) or []:
            probes = [str(col.get("column_name") or ""), str(col.get("quoted_ref") or "")]
            probes.extend(str(a) for a in (col.get("aliases") or []))
            vs = col.get("value_semantics") or {}
            probes.extend(str(a) for a in (vs.get("sql_aliases") or []))
            for probe in probes:
                p = _normalize_semantic_search_term(probe)
                if not p:
                    continue
                if any(term in p or p in term for term in lowered_terms):
                    return True
    return False


def _has_missing_explicit_table_request(question: str, payload: dict) -> bool:
    refs = _extract_explicit_table_request_terms(question)
    if not refs:
        return False
    return any(not _known_table_ref(ref, payload) for ref in refs)


def _extract_explicit_table_request_terms(question: str) -> list[str]:
    q = question or ""
    refs: list[str] = []
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])"
        r"((?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+)"
        r"(?![A-Za-z0-9_])"
    )
    for match in pattern.finditer(q):
        ref = match.group(1).strip()
        tail = q[match.end():match.end() + 4].lower()
        prefix = ref.split(".")[-1].lower()
        if "." in ref or prefix.startswith(("cq_", "mp_", "kg_", "bird_")) or "表" in tail or "table" in tail:
            refs.append(ref)
    return list(dict.fromkeys(refs))


def _known_table_ref(table_ref: str, payload: dict) -> bool:
    terms = _payload_table_terms(payload)
    ref_terms = _table_ref_terms(table_ref)
    if terms & ref_terms:
        return True
    try:
        from .semantic_layer import describe_table_semantic, list_semantic_sources

        probes = [table_ref]
        if "." in table_ref:
            probes.append(table_ref.split(".")[-1])
        for probe in probes:
            schema = describe_table_semantic(probe)
            if schema.get("status") == "success":
                return True
        sources = list_semantic_sources()
        if sources.get("status") == "success":
            known = {
                _normalize_identifier_like(str(src.get("table_name") or ""))
                for src in sources.get("sources", []) or []
                if src.get("table_name")
            }
            known.update(name.split("_", 1)[-1] for name in list(known) if "." in name)
            if known & ref_terms:
                return True
    except Exception:
        pass
    return False


def _has_ungrounded_explicit_metric_request(question: str, payload: dict) -> bool:
    terms = _extract_explicit_metric_request_terms(question)
    if not terms:
        return False
    table_terms = _payload_table_terms(payload)
    terms = [
        term for term in terms
        if _normalize_semantic_search_term(term) not in table_terms
        and not _is_computable_metric_term(term)
    ]
    if not terms:
        return False
    return any(not _payload_has_column_term(payload, (term,)) for term in terms)


def _payload_intent_is_unknown(payload: dict) -> bool:
    intent = payload.get("intent")
    value = getattr(intent, "value", intent)
    text = str(value or "").lower()
    return not text or text in {"unknown", "intentlabel.unknown"}


def _extract_explicit_metric_request_terms(question: str) -> list[str]:
    q = question or ""
    terms: list[str] = []
    for segment in re.findall(r"[（(]\s*([^（）()]{1,80})\s*[）)]", q):
        for raw in re.split(r"[,，、/;；\s]+", segment):
            raw = raw.strip()
            if "'" in raw or '"' in raw:
                continue
            term = raw.strip(" 等")
            if _looks_like_explicit_metric_token(term):
                terms.append(term)

    metric_markers = (
        "房价", "均价", "涨幅", "二手房成交量", "成交量", "空气质量指数",
        "降雨量", "客流量", "土壤含水量", "能耗等级", "风险等级",
        "空位数", "评估价格", "人均价格",
    )
    for marker in metric_markers:
        if marker in q and not _is_generic_metric_phrase(marker):
            terms.append(marker)
    return list(dict.fromkeys(terms))


def _looks_like_explicit_metric_token(term: str) -> bool:
    value = str(term or "").strip().strip("'\"")
    if len(value) < 2:
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,40}", value):
        return True
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,12}", value))


def _is_generic_metric_phrase(term: str) -> bool:
    value = str(term or "").strip()
    return value in {
        "空间数据",
        "几何数据",
        "全部数据",
        "所有数据",
        "完整数据",
        "统计数据",
    }


def _is_computable_metric_term(term: str) -> bool:
    raw = str(term or "").strip()
    raw_low = raw.lower()
    if raw_low.startswith("st_"):
        return True
    if raw_low in {
        "is", "not", "null", "like", "in", "and", "or", "use", "using",
    }:
        return True
    if "小数" in raw or "保留" in raw:
        return True
    if raw in {"使用", "升序", "降序", "排序", "高德数据", "百度数据"}:
        return True
    if raw.endswith("数据") and raw not in {"房价数据", "降雨量数据"}:
        return True
    value = _normalize_semantic_search_term(term)
    computable = {
        "count", "sum", "avg", "average", "min", "max", "total",
        "area", "length", "distance", "centroid", "center", "wkt",
        "geometry", "geom", "shape", "intersects", "within", "contains",
        "st_intersects", "st_dwithin", "knn", "poi", "aoi", "sql", "id",
        "数量", "条数", "个数", "次数", "面积", "总面积", "长度", "总长",
        "距离", "质心", "中心点", "坐标", "名称", "名字", "编号",
        "米", "千米", "公里", "平方米", "公顷",
    }
    return value in computable


def _has_missing_explicit_column_request(question: str, payload: dict) -> bool:
    terms = _extract_explicit_column_request_terms(question)
    if not terms:
        return False
    table_terms = _payload_table_terms(payload)
    terms = [term for term in terms if term not in table_terms]
    if not terms:
        return False
    known_columns = _payload_column_terms(payload)
    if not known_columns:
        return True
    return any(term not in known_columns for term in terms)


def _extract_explicit_column_request_terms(question: str) -> list[str]:
    q = question or ""
    q_low = q.lower()
    markers = ("字段", "列名", "column", "columns", "field", "fields")
    if not any(marker in q_low for marker in markers):
        return []

    table_terms = {
        "table", "schema", "select", "from", "where", "and", "or", "by", "as",
        "like", "ilike", "limit", "join", "on", "group", "order", "having",
    }
    terms: list[str] = []
    for raw in re.findall(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_])", q):
        norm = _normalize_identifier_like(raw)
        if not norm or norm in table_terms:
            continue
        if norm.startswith("cq_") or norm.startswith("public_"):
            continue
        if not _looks_like_explicit_column_identifier(raw):
            continue
        terms.append(norm)
    return list(dict.fromkeys(terms))


def _looks_like_explicit_column_identifier(raw: str) -> bool:
    token = str(raw or "").strip()
    if not token:
        return False
    if "_" in token or any(ch.isdigit() for ch in token):
        return True
    return token.isupper() and len(token) > 1


def _payload_column_terms(payload: dict) -> set[str]:
    terms: set[str] = set()
    for table in payload.get("candidate_tables", []) or []:
        for col in table.get("columns", []) or []:
            probes = [str(col.get("column_name") or ""), str(col.get("quoted_ref") or "")]
            probes.extend(str(a) for a in (col.get("aliases") or []))
            vs = col.get("value_semantics") or {}
            probes.extend(str(a) for a in (vs.get("sql_aliases") or []))
            for probe in probes:
                norm = _normalize_identifier_like(probe)
                if norm:
                    terms.add(norm)
    return terms


def _payload_table_terms(payload: dict) -> set[str]:
    terms: set[str] = set()
    for table in payload.get("candidate_tables", []) or []:
        probes = [
            str(table.get("table_name") or ""),
            str(table.get("display_name") or ""),
            str(table.get("description") or ""),
        ]
        probes.extend(str(a) for a in (table.get("table_aliases") or []))
        for probe in probes:
            norm = _normalize_identifier_like(probe)
            if norm:
                terms.add(norm)
    return terms


def _table_ref_terms(table_ref: str) -> set[str]:
    ref = str(table_ref or "").strip().strip('"')
    if not ref:
        return set()
    bare = ref.split(".")[-1]
    terms = {_normalize_identifier_like(ref), _normalize_identifier_like(bare)}
    versionless = re.sub(r"_(?:19|20)\d{2}$", "", bare)
    terms.add(_normalize_identifier_like(versionless))
    return {term for term in terms if term}


def _normalize_identifier_like(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("'").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _normalize_semantic_search_term(value: str) -> str:
    ident = _normalize_identifier_like(value)
    if ident:
        return ident
    return str(value or "").strip().strip('"').strip("'").lower()


def _postprocess_safe_preview_fallback(
    question: str,
    payload: dict,
    schemas: dict,
    large_tables: set[str],
) -> tuple[object | None, str]:
    """Return a validated bounded preview query for read-only preview requests."""
    fallback_sql = _build_safe_preview_sql(question, payload)
    if not fallback_sql:
        return None, "no_preview_fallback"
    fallback_pp = postprocess_sql(
        fallback_sql,
        schemas,
        large_tables,
        intent=current_nl2sql_intent.get(),
    )
    if fallback_pp.rejected:
        return None, f"postprocess:{fallback_pp.reject_reason}"

    from .runtime_guards import is_safe_sql
    fallback_ok, fallback_reason = is_safe_sql(fallback_pp.sql, set(schemas.keys()))
    if not fallback_ok:
        return None, f"runtime_guard:{fallback_reason}"
    return fallback_pp, ""


def _generate_gemma_sql(prompt: str, model_name: str | None = None) -> str:
    """Generate SQL with the configured Gemma/Ollama model via LiteLLM."""
    model_name = model_name or _get_standard_model_name()
    from .model_gateway import ModelRegistry, create_model

    adk_model = create_model(model_name)
    info = ModelRegistry.get_model_info(model_name)
    completion_kwargs = {
        "model": getattr(adk_model, "model", None) or info.get("model_id", model_name),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }

    additional_args = getattr(adk_model, "_additional_args", {}) or {}
    extra_body = additional_args.get("extra_body") or info.get("extra_body")
    if extra_body:
        completion_kwargs["extra_body"] = extra_body
    timeout = additional_args.get("timeout") or info.get("request_timeout")
    if timeout:
        completion_kwargs["timeout"] = timeout

    import litellm

    attempts = max(1, int(os.environ.get("NL2SQL_GEMMA_SQL_RETRIES", "3")))
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = litellm.completion(**completion_kwargs)
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            time.sleep(min(2 ** attempt, 8))
    else:
        raise last_exc or RuntimeError("Gemma SQL generation failed")

    msg = resp.choices[0].message
    if isinstance(msg, dict):
        return (msg.get("content") or "").strip()
    return (getattr(msg, "content", "") or "").strip()


def apply_gemma_semantic_rewrites(
    question: str,
    sql: str,
    context: dict,
) -> tuple[str, list[str]]:
    """Compatibility wrapper for the config-driven semantic SQL rewriter."""
    from .nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    return apply_semantic_sql_rewrites(question, sql, context)

def _format_schema_for_retry(schemas: dict) -> str:
    """Format cached schemas into a compact block for the retry prompt."""
    lines = []
    for table_name, columns in schemas.items():
        col_strs = []
        for col in columns:
            name = col.get("column_name", "")
            needs_q = col.get("needs_quoting", False)
            ref = f'"{name}"' if needs_q else name
            pg_type = col.get("pg_type", "")
            col_strs.append(f"  {ref} {pg_type}")
        lines.append(f"-- {table_name}")
        lines.extend(col_strs)
    return "\n".join(lines) if lines else "(no schema available)"


def _retry_with_llm(
    question: str, failed_sql: str, error: str, schemas: dict
) -> str | None:
    """Ask LLM to fix the failed SQL based on error message.

    Uses Gemini 2.0 Flash for fast, cheap retry. Returns fixed SQL or None.
    """
    schema_block = _format_schema_for_retry(schemas)
    prompt = (
        "You are a PostgreSQL SQL repair assistant. The previous SQL failed.\n\n"
        f"Original question: {question}\n"
        f"Failed SQL: {failed_sql}\n"
        f"Error: {error}\n\n"
        f"Available schema:\n{schema_block}\n\n"
        "Repair the SQL. Output only the repaired SQL, with no explanation.\n"
        "Preserve double quotes for case-sensitive or non-ASCII column names."
    )
    try:
        from .llm_client import generate_text, strip_fences
        raw = generate_text(prompt, tier="fast", timeout_ms=20_000)
        fixed = strip_fences(raw)
        return fixed if fixed else None
    except Exception:
        return None


def _auto_curate(question: str, sql: str) -> None:
    """Auto-curate successful (question, SQL) pairs into reference_queries.

    Uses dedup (cosine > 0.92) built into ReferenceQueryStore.add().
    Infers domain_id from table names in the SQL for domain isolation.
    Non-fatal: silently ignores any errors.
    """
    if not question or not sql:
        return
    try:
        # Infer domain from table names in SQL
        import re
        domain_id = None
        table_match = re.findall(r'\bFROM\s+"?(\w+)"?', sql, re.IGNORECASE)
        if table_match:
            domain_id = table_match[0]

        from .reference_queries import ReferenceQueryStore
        store = ReferenceQueryStore()
        store.add(
            query_text=question,
            response_summary=sql,
            task_type="nl2sql",
            source="auto_curate",
            domain_id=domain_id,
        )
    except Exception:
        pass


def prepare_nl2sql_context(user_question: str) -> str:
    """Prepare semantic/schema grounding prompt for NL2SQL generation.

    Caches per-request schemas and large-table hints in ContextVars so the next
    tool call `execute_nl2sql()` can postprocess the generated SQL.
    """
    payload = build_nl2sql_context(user_question)

    schemas = {}
    large_tables = set()
    for table in payload.get("candidate_tables", []):
        name = table["table_name"]
        schemas[name] = table.get("columns", [])
        if int(table.get("row_count_hint", 0) or 0) >= 1_000_000:
            large_tables.add(name)

    current_nl2sql_question.set(user_question)
    current_nl2sql_schemas.set(schemas)
    current_nl2sql_large_tables.set(large_tables)

    intent = payload.get("intent")
    if intent is not None:
        current_nl2sql_intent.set(intent)

    return payload.get("grounding_prompt", "")


def execute_nl2sql(sql: str) -> str:
    """Postprocess, execute, and self-correct NL2SQL-generated SQL.

    Phase 2 enhancements:
    - On execution failure, retries up to MAX_RETRIES times with LLM-based SQL fix
    - On success, auto-curates (question, SQL) pair into reference_queries for few-shot
    """
    schemas = current_nl2sql_schemas.get()
    large_tables = current_nl2sql_large_tables.get()
    question = current_nl2sql_question.get()

    last_sql = sql

    for attempt in range(MAX_RETRIES + 1):
        pp_result = postprocess_sql(last_sql, schemas, large_tables, intent=current_nl2sql_intent.get())
        if pp_result.rejected:
            return f"安全拒绝: {pp_result.reject_reason}"

        from .runtime_guards import is_safe_sql
        guard_ok, guard_reason = is_safe_sql(pp_result.sql, set(schemas.keys()))
        if not guard_ok:
            return f"安全拒绝: runtime_guard:{guard_reason}"

        exec_result = execute_safe_sql(pp_result.sql)

        try:
            parsed = json.loads(exec_result)
        except Exception:
            parsed = {}

        error = parsed.get("error")
        if error is None or parsed.get("status") == "ok":
            _auto_curate(question, pp_result.sql)
            return exec_result

        if attempt >= MAX_RETRIES:
            return exec_result

        fixed_sql = _retry_with_llm(question, pp_result.sql, str(error), schemas)
        if not fixed_sql:
            return exec_result

        last_sql = fixed_sql


def run_nl2semantic2sql(user_question: str) -> str:
    """Run local-family/Ollama NL2Semantic2SQL as one high-level tool call.

    This is the production path for local models such as Gemma4 and Qwen3.6
    because exposing the low-level semantic/database tools to the model can
    trap it in repeated tool calls.
    The Python side owns the full workflow: semantic grounding, SQL generation,
    deterministic semantic fixes, guards, execution, and structured return.
    """
    harness_family = _active_direct_harness_family()
    payload = build_nl2sql_context(user_question, family=harness_family)
    current_nl2sql_question.set(user_question)
    intent = payload.get("intent")
    if intent is not None:
        current_nl2sql_intent.set(intent)

    if _should_refuse_nl2sql_question(user_question, payload):
        return json.dumps({
            "status": "rejected",
            "error": "policy_refusal",
            "raw_sql": "",
            "sql": "",
            "semantic": _semantic_summary(payload),
            "corrections": ["policy_refusal"],
        }, ensure_ascii=False)

    prompt = _build_family_semantic_prompt(harness_family, user_question, payload)
    try:
        raw_sql = _generate_gemma_sql(prompt)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"{harness_family}_sql_generation_failed:{exc}",
            "sql": "",
            "semantic": _semantic_summary(payload),
            "corrections": [],
        }, ensure_ascii=False)

    extracted_sql = _extract_sql(raw_sql)
    harness_corrections: list[str] = []
    ungrounded_ref = _find_ungrounded_sql_reference(user_question, extracted_sql, payload)
    if ungrounded_ref and os.environ.get("NL2SQL_GEMMA_ALLOW_SQL_REFERENCED_TABLES") != "1":
        retry_prompt = _build_ungrounded_table_retry_prompt(
            user_question,
            payload,
            extracted_sql,
            ungrounded_ref,
            family=harness_family,
        )
        try:
            raw_sql = _generate_gemma_sql(retry_prompt)
            extracted_sql = _extract_sql(raw_sql)
            harness_corrections.append(f"{harness_family}_ungrounded_table_retry")
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"{harness_family}_sql_generation_failed:{exc}",
                "sql": "",
                "semantic": _semantic_summary(payload),
                "corrections": harness_corrections,
            }, ensure_ascii=False)

    ungrounded_ref = _find_ungrounded_sql_reference(user_question, extracted_sql, payload)
    if ungrounded_ref and os.environ.get("NL2SQL_GEMMA_ALLOW_SQL_REFERENCED_TABLES") != "1":
        return json.dumps({
            "status": "rejected",
            "error": f"runtime_guard:ungrounded_table:{ungrounded_ref}",
            "raw_sql": raw_sql,
            "sql": "",
            "semantic": _semantic_summary(payload),
            "corrections": harness_corrections + [f"{harness_family}_ungrounded_table_rejected"],
        }, ensure_ascii=False)

    payload = _augment_payload_with_sql_referenced_tables(extracted_sql, payload)
    schemas, large_tables = _schemas_and_large_tables(payload)
    current_nl2sql_schemas.set(schemas)
    current_nl2sql_large_tables.set(large_tables)

    rewritten_sql, rewrite_corrections = apply_gemma_semantic_rewrites(
        user_question,
        extracted_sql,
        payload,
    )

    pp_result = postprocess_sql(
        rewritten_sql,
        schemas,
        large_tables,
        intent=current_nl2sql_intent.get(),
    )
    corrections = rewrite_corrections + list(getattr(pp_result, "corrections", []) or [])
    corrections = harness_corrections + corrections
    if pp_result.rejected:
        fallback_pp, fallback_error = _postprocess_safe_preview_fallback(
            user_question,
            payload,
            schemas,
            large_tables,
        )
        if fallback_pp is not None:
            pp_result = fallback_pp
            corrections.extend(list(getattr(fallback_pp, "corrections", []) or []))
            corrections.append("safe_preview_fallback")
        else:
            if fallback_error != "no_preview_fallback":
                corrections.append(f"safe_preview_fallback_failed:{fallback_error}")
            return json.dumps({
                "status": "rejected",
                "error": f"postprocess:{pp_result.reject_reason}",
                "raw_sql": raw_sql,
                "sql": pp_result.sql,
                "semantic": _semantic_summary(payload),
                "corrections": corrections,
            }, ensure_ascii=False)

    from .runtime_guards import is_safe_sql
    guard_ok, guard_reason = is_safe_sql(pp_result.sql, set(schemas.keys()))
    if not guard_ok:
        fallback_pp, fallback_error = _postprocess_safe_preview_fallback(
            user_question,
            payload,
            schemas,
            large_tables,
        )
        if fallback_pp is not None:
            pp_result = fallback_pp
            corrections.extend(list(getattr(fallback_pp, "corrections", []) or []))
            corrections.append("safe_preview_fallback")
            guard_ok = True
        else:
            if fallback_error != "no_preview_fallback":
                corrections.append(f"safe_preview_fallback_failed:{fallback_error}")
    if not guard_ok:
        return json.dumps({
            "status": "rejected",
            "error": f"runtime_guard:{guard_reason}",
            "raw_sql": raw_sql,
            "sql": pp_result.sql,
            "semantic": _semantic_summary(payload),
            "corrections": corrections,
        }, ensure_ascii=False)

    exec_result = execute_safe_sql(pp_result.sql)
    try:
        parsed_exec = json.loads(exec_result)
    except Exception:
        parsed_exec = {"raw": exec_result}

    status = parsed_exec.get("status")
    if status is None:
        status = "error" if parsed_exec.get("error") else "ok"

    if status == "ok" or parsed_exec.get("error") is None:
        _auto_curate(user_question, pp_result.sql)

    return json.dumps({
        "status": status,
        "sql": pp_result.sql,
        "raw_sql": raw_sql,
        "execution": parsed_exec,
        "semantic": _semantic_summary(payload),
        "corrections": corrections,
    }, ensure_ascii=False)


def _semantic_summary(payload: dict) -> dict:
    return {
        "candidate_tables": [
            table.get("table_name")
            for table in payload.get("candidate_tables", []) or []
            if table.get("table_name")
        ],
        "few_shot_count": len(payload.get("few_shots") or []),
        "hint_stats": payload.get("_hint_injection_stats") or {},
    }
