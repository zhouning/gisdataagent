"""Executor tools for NL2SQL Phase 2: prepare grounding, execute with self-correction, auto-curate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time

from .nl2sql_observability import observe_request, observe_stage, annotate_stage, record_route, stage

from .nl2sql_grounding import (
    _estimate_table_size,
    _needs_quoting,
    _quoted_ref,
    _table_aliases_from_source,
    build_nl2sql_context,
    refresh_nl2sql_grounding_prompt,
)
from .nl2sql_model_profile import infer_model_family
from .nl2sql_generation_policy import (
    current_grounded_request,
    generation_system_prompt,
    generation_token_budget,
    relational_generation_guidance,
    remember_retry_grounding,
    retry_grounding,
    row_identity_context,
)
from .nl2sql_review_pipeline import review_draft
from .semantic_layer import describe_table_semantic, list_semantic_sources
from .sql_postprocessor import postprocess_sql
from .toolsets.nl2sql_tools import execute_safe_sql
from .user_context import (
    current_nl2sql_intent,
    current_nl2sql_candidate_tables,
    current_nl2sql_execution_engine,
    current_nl2sql_requested_engine,
    current_nl2sql_large_tables,
    current_nl2sql_llm_calls,
    current_nl2sql_llm_evidence,
    current_nl2sql_question,
    current_nl2sql_schemas,
)

# Backward-compatible names used in tests / plan prose
_cached_schemas = current_nl2sql_schemas
_cached_large_tables = current_nl2sql_large_tables

MAX_RETRIES = 2
EXECUTION_ENGINES = {"postgis", "lake", "auto"}


def _record_llm_evidence(evidence: dict) -> None:
    recorded = dict(evidence or {})
    current_nl2sql_llm_evidence.set(recorded)
    current_nl2sql_llm_calls.set([*current_nl2sql_llm_calls.get(), recorded])


def _aggregate_llm_evidence() -> dict:
    calls = current_nl2sql_llm_calls.get()

    def _token_total(name: str) -> int | None:
        values = [(call.get("usage") or {}).get(name) for call in calls]
        if any(type(value) is not int or value < 0 for value in values):
            return None
        return sum(values)

    costs = [
        call.get("estimated_cost_usd")
        for call in calls
        if isinstance(call, dict) and call.get("estimated_cost_usd") is not None
    ]
    local_only = bool(calls) and all(
        str(call.get("provider") or "").casefold()
        in {"ollama", "lm_studio", "local"}
        for call in calls
    )
    if len(costs) == len(calls):
        estimated_cost = round(sum(float(value) for value in costs), 12)
        cost_status = "estimated"
    elif local_only:
        estimated_cost = 0.0
        cost_status = "not_applicable"
    else:
        estimated_cost = None
        cost_status = "unavailable"
    return {
        "calls": len(calls),
        "latency_ms": sum(int(call.get("latency_ms") or 0) for call in calls),
        "input_tokens": _token_total("prompt_tokens"),
        "output_tokens": _token_total("completion_tokens"),
        "total_tokens": _token_total("total_tokens"),
        "estimated_cost_usd": estimated_cost,
        "cost_status": cost_status,
    }


def _normalized_source_ref(value: str) -> str:
    ref = str(value or "").strip().strip('"')
    if ref.casefold().startswith("public."):
        ref = ref[len("public.") :]
    return ref.casefold()


def _apply_governed_source_bindings(
    payload: dict,
    engine: str,
    bindings: dict[str, dict] | None,
) -> dict:
    if bindings is None:
        return payload
    by_name = {
        _normalized_source_ref(name): dict(binding)
        for name, binding in bindings.items()
    }
    candidate_pool = list(payload.get("candidate_tables") or [])
    present = {
        _normalized_source_ref(candidate.get("table_name") or "")
        for candidate in candidate_pool
    }
    for name in bindings:
        key = _normalized_source_ref(name)
        if key in present:
            continue
        schema = describe_table_semantic(name)
        if schema.get("status") != "success" and engine == "postgis":
            schema = _describe_physical_table(name)
        if schema.get("status") == "success":
            candidate_pool.append(_candidate_from_described_schema(name, schema))
            present.add(key)
    selected = []
    selected_keys: set[str] = set()
    for candidate in candidate_pool:
        name = str(candidate.get("table_name") or "")
        key = _normalized_source_ref(name)
        binding = by_name.get(key)
        if binding is None:
            continue
        governed = dict(candidate)
        execution_bindings = dict(governed.get("execution_bindings") or {})
        if engine == "lake":
            locator = str(binding.get("physical_locator") or "")
            governed["projection_path"] = locator
            execution_bindings["lake"] = {
                **dict(execution_bindings.get("lake") or {}),
                "projection_path": locator,
                "projection_id": str(binding.get("binding_id") or ""),
            }
        else:
            locator = _normalized_source_ref(binding.get("physical_locator") or "")
            if locator != key:
                continue
            execution_bindings["postgis"] = {"table_name": name}
        governed["execution_bindings"] = execution_bindings
        governed["governed_source_binding"] = binding
        selected.append(governed)
        selected_keys.add(key)
    filtered = dict(payload)
    filtered["candidate_tables"] = selected
    filtered["large_tables"] = [
        name
        for name in (payload.get("large_tables") or [])
        if _normalized_source_ref(name) in selected_keys
    ]
    filtered["governed_source_bindings"] = list(bindings.values())
    return refresh_nl2sql_grounding_prompt(filtered)


def _ungoverned_sql_source(sql: str, bindings: dict[str, dict] | None) -> str:
    if bindings is None:
        return ""
    allowed = {_normalized_source_ref(name) for name in bindings}
    for table in _referenced_sql_tables(sql):
        if _normalized_source_ref(table) not in allowed:
            return table
    return ""


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

    Prefer the structured SQL AST so CTE aliases are not mistaken for physical
    tables. Fall back to a conservative identifier scan for incomplete SQL.
    """
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql or "", read="postgres")
        cte_names = {
            str(cte.alias_or_name or "").strip().casefold()
            for cte in tree.find_all(exp.CTE)
            if cte.alias_or_name
        }
        refs: list[str] = []
        for table in tree.find_all(exp.Table):
            bare = str(table.name or "").strip()
            if not bare or bare.casefold() in cte_names:
                continue
            parts = [str(part).strip() for part in (table.catalog, table.db, bare) if part]
            ref = ".".join(parts)
            if ref and ref not in refs:
                refs.append(ref)
        return refs
    except Exception:
        pass

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
        if (
            not is_geom
            and pg_type == "USER-DEFINED"
            and column_name.lower()
            in {
                "geometry",
                "geom",
                "the_geom",
                "shape",
            }
        ):
            is_geom = True
        if is_geom:
            pg_type = f"geometry({geometry_type or 'Geometry'},{srid or 0})"
        columns.append(
            {
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
            }
        )
    source_kind = source_meta.get("source_kind") or "postgis"
    projection_path = source_meta.get("projection_path")
    projection_id = source_meta.get("projection_id")
    execution_bindings = {
        str(engine): dict(binding)
        for engine, binding in (source_meta.get("execution_bindings") or {}).items()
        if isinstance(binding, dict)
    }
    if projection_path and "lake" not in execution_bindings:
        execution_bindings["lake"] = {
            "projection_path": projection_path,
            "projection_id": projection_id,
        }
    if "postgis" not in execution_bindings and (
        source_kind != "offline_projection" or source_meta.get("postgis_table_name")
    ):
        execution_bindings["postgis"] = {
            "table_name": source_meta.get("postgis_table_name") or table_name,
        }
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
        "source_kind": source_kind,
        "projection_path": projection_path,
        "projection_id": projection_id,
        "production_eligible": source_meta.get("production_eligible", False),
        "execution_bindings": execution_bindings,
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
            col_rows = conn.execute(
                text(
                    "SELECT column_name, data_type, udt_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema=:schema_name AND table_name=:table_name "
                    "ORDER BY ordinal_position"
                ),
                {"schema_name": schema_name, "table_name": bare_table},
            ).fetchall()
            geom_rows = conn.execute(
                text(
                    "SELECT f_geometry_column, type, srid "
                    "FROM geometry_columns "
                    "WHERE f_table_schema=:schema_name AND f_table_name=:table_name"
                ),
                {"schema_name": schema_name, "table_name": bare_table},
            ).fetchall()
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
        columns.append(
            {
                "column_name": column_name,
                "data_type": data_type,
                "udt_name": udt_name,
                "is_geometry": is_geom,
                "aliases": aliases,
                "value_semantics": {},
            }
        )

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
    existing = {t.get("table_name") for t in candidate_tables if t.get("table_name")}
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
    execution_engine: str = "postgis",
) -> str:
    allowed = sorted(
        str(t.get("table_name") or "")
        for t in payload.get("candidate_tables", []) or []
        if t.get("table_name")
    )
    return (
        _build_family_semantic_prompt(
            family,
            question,
            payload,
            execution_engine=execution_engine,
        )
        + "\n\nHarness correction:\n"
        + f"- Previous SQL referenced `{table_ref}`, which is not grounded by the candidate schema.\n"
        + f"- Use only these candidate tables: {', '.join(allowed) or '(none)'}.\n"
        + "- If the question cannot be answered from those candidate tables, output SELECT 1.\n"
        + "- Output SQL only.\n\n"
        + f"Previous SQL:\n{sql}\n"
    )


def _extract_sql(text: str) -> str:
    """Extract the most recent complete top-level SELECT/WITH statement."""
    # Fences mark separate attempts; set-operation operands do not.
    blocks = re.findall(r"\x60\x60\x60(?:sql)?\s*\n?(.*?)\x60\x60\x60", text or "", re.DOTALL | re.IGNORECASE)
    for block in reversed(blocks):
        candidate = _extract_sql(block)
        if _looks_like_select_sql(candidate) and _sql_candidate_parseable(candidate):
            return candidate
    sql = _strip_fences(text)
    sql = re.sub(r"^\s*(?:sql\s*:|SQL\s*:)", "", sql).strip()
    try:
        import sqlglot
        from sqlglot import exp

        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) == 1 and isinstance(statements[0], exp.Query):
            return sql.rstrip(";").strip()
    except Exception:
        pass
    starts = _top_level_sql_starts(sql)
    candidates = [_slice_sql_statement(sql, start) for start in starts]
    candidates = [candidate for candidate in candidates if candidate]
    for candidate in reversed(candidates):
        if candidate.upper().startswith("WITH") or re.search(
            r"\bFROM\b", candidate, flags=re.IGNORECASE
        ):
            return candidate

    matches = list(re.finditer(r"\b(SELECT|WITH)\b", sql, flags=re.IGNORECASE))
    if not matches:
        return sql or "SELECT 1"
    nested_candidates: list[str] = []
    for match in matches:
        candidate = sql[match.start() :].strip()
        if ";" in candidate:
            candidate = candidate.split(";", 1)[0].strip()
        if candidate:
            nested_candidates.append(candidate)
    for candidate in reversed(nested_candidates):
        if _looks_like_select_sql(candidate) and _sql_candidate_parseable(candidate):
            return candidate
    for candidate in reversed(nested_candidates):
        if candidate.upper().startswith("WITH") or re.search(
            r"\bFROM\b", candidate, flags=re.IGNORECASE
        ):
            return candidate
    return nested_candidates[-1] if nested_candidates else "SELECT 1"


def _is_generation_placeholder(sql: str) -> bool:
    """Return True for a refusal/test placeholder emitted for a valid query."""
    value = re.sub(r"\s+", " ", str(sql or "").strip().rstrip(";")).casefold()
    return value in {"", "select 1", "select 1 as test", "select 1 limit 1"}


def _build_placeholder_retry_prompt(
    question: str,
    payload: dict,
    previous_sql: str,
    *,
    family: str,
    execution_engine: str,
) -> str:
    """Ask the configured direct harness to replace an empty placeholder."""
    return (
        _build_family_semantic_prompt(
            family,
            question,
            payload,
            execution_engine=execution_engine,
        )
        + "\n\nHarness correction:\n"
        + "- The previous response was an empty or placeholder SQL statement.\n"
        + "- This is a read-only computable question. Generate the actual SELECT "
        + "or WITH ... SELECT using only the governed candidate tables and fields.\n"
        + "- Do not output SELECT 1, an explanation, or Markdown.\n"
        + f"Previous response: {previous_sql or '(empty)'}\n"
    )


def _top_level_sql_starts(sql: str) -> list[int]:
    starts: list[int] = []
    depth = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    in_top_level_with_statement = False
    awaiting_set_operand = False
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
            awaiting_set_operand = False
            i += 1
            continue
        if depth == 0 and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            if re.match(r"\b(?:UNION|INTERSECT|EXCEPT)\b", sql[i:], flags=re.IGNORECASE):
                awaiting_set_operand = True
            elif re.match(r"\bWITH\b", sql[i:], flags=re.IGNORECASE):
                starts.append(i)
                in_top_level_with_statement = True
            elif re.match(r"\bSELECT\b", sql[i:], flags=re.IGNORECASE):
                if not in_top_level_with_statement and not awaiting_set_operand:
                    starts.append(i)
                awaiting_set_operand = False
        i += 1
    return starts


def _slice_sql_statement(sql: str, start: int) -> str:
    depth = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = start
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
    model_name = (
        os.environ.get("NL2SQL_AGENT_MODEL")
        or os.environ.get("GDA_LLM_MODEL")
        or os.environ.get("MODEL_STANDARD")
        or ""
    ).strip().lower()
    family = os.environ.get("NL2SQL_AGENT_FAMILY") or None
    resolved = infer_model_family(model_name, family)
    # The direct harness historically used Gemma as its generic local
    # fallback. Keep that deployment compatibility while routing recognised
    # models through the shared profile resolver.
    return resolved if resolved in {"deepseek", "gemini", "gemma", "openai", "qwen"} else "gemma"


def _generation_retry_attempts() -> int:
    """Return model-independent SQL generation retry attempts.

    ``NL2SQL_GEMMA_SQL_RETRIES`` remains a compatibility alias for existing
    deployments and scripts produced before the direct harness supported Qwen.
    """
    configured = os.environ.get("GDA_NL2SQL_GENERATION_RETRIES")
    if configured is None:
        configured = os.environ.get("NL2SQL_GEMMA_SQL_RETRIES", "3")
    return max(1, int(configured))


def _generation_retry_delay(provider: str, attempt: int) -> float:
    """Return a bounded retry delay suited to local or online transports."""

    normalized = str(provider or "").strip().casefold()
    if normalized in {"deepseek", "gemini"}:
        base = float(os.environ.get("GDA_NL2SQL_ONLINE_RETRY_BASE_SECONDS", "10"))
        maximum = float(os.environ.get("GDA_NL2SQL_ONLINE_RETRY_MAX_SECONDS", "60"))
    else:
        base = 1.0
        maximum = 8.0
    return max(0.0, min(base * (2**attempt), maximum))


def _allow_sql_referenced_tables() -> bool:
    """Whether generated SQL may introduce tables outside governed grounding."""
    configured = os.environ.get("GDA_NL2SQL_ALLOW_SQL_REFERENCED_TABLES")
    if configured is None:
        configured = os.environ.get("NL2SQL_GEMMA_ALLOW_SQL_REFERENCED_TABLES", "0")
    return str(configured).strip().casefold() in {"1", "true", "yes", "on"}


def _normalize_execution_engine(value: str | None) -> str:
    requested = (
        value
        or current_nl2sql_requested_engine.get()
        or os.environ.get("GDA_NL2SQL_EXECUTION_ENGINE")
        or "postgis"
    )
    normalized = requested.strip().lower()
    if normalized not in EXECUTION_ENGINES:
        raise ValueError(
            f"unsupported execution engine: {requested}; expected postgis, lake, or auto"
        )
    return normalized


def _resolve_execution_engine(payload: dict, requested: str) -> str:
    if requested != "auto":
        return requested
    candidates = payload.get("candidate_tables") or []
    if candidates:
        first = candidates[0]
        bindings = first.get("execution_bindings") or {}
        if first.get("projection_path") or "lake" in bindings:
            return "lake"
    return "postgis"


def _filter_payload_for_execution_engine(payload: dict, engine: str, family: str) -> dict:
    candidates = list(payload.get("candidate_tables") or [])
    if engine == "lake":
        from .lake_sql_executor import lake_candidate_tables

        selected = lake_candidate_tables(candidates)
    else:
        selected = []
        for table in candidates:
            bindings = table.get("execution_bindings") or {}
            source_kind = table.get("source_kind")
            if "postgis" in bindings or source_kind != "offline_projection":
                selected.append(table)

    if selected == candidates:
        return payload
    filtered = dict(payload)
    filtered["candidate_tables"] = selected
    selected_names = {str(table.get("table_name") or "") for table in selected}
    filtered["large_tables"] = [
        name for name in (payload.get("large_tables") or []) if name in selected_names
    ]
    return refresh_nl2sql_grounding_prompt(filtered, family=family)


@observe_stage("execution.attempt")
def _execute_for_engine(
    sql: str,
    payload: dict,
    engine: str,
    *,
    max_rows: int | None = None,
) -> str:
    bird_db_id = payload.get("bird_db_id")
    if bird_db_id:
        from .bird_source import execute_bird_sql

        return execute_bird_sql(bird_db_id, sql, max_rows=max_rows or 100000)
    if engine == "lake":
        from .lake_sql_executor import execute_lake_sql

        if max_rows is None:
            return execute_lake_sql(sql, payload.get("candidate_tables") or [])
        return execute_lake_sql(sql, payload.get("candidate_tables") or [], max_rows=max_rows)
    if max_rows is None:
        return execute_safe_sql(sql)
    bounded_sql = (
        f"SELECT * FROM ({sql.rstrip(';')}) AS _gda_nl2sql_result "
        f"LIMIT {max(1, min(int(max_rows), 1_000_000))}"
    )
    return execute_safe_sql(bounded_sql, max_rows=max_rows)


def _dialect_for_engine(engine: str) -> str:
    return "duckdb" if engine == "lake" else "postgres"


def _annotate_execution_result(
    raw_result: str,
    engine: str,
    candidate_tables: list[dict] | None = None,
) -> str:
    """Attach execution provenance to the two-step tool's JSON result."""
    try:
        payload = json.loads(raw_result)
    except (TypeError, ValueError):
        return raw_result
    if not isinstance(payload, dict):
        return raw_result
    payload.setdefault("engine", engine)
    payload.setdefault("dialect", _dialect_for_engine(engine))
    if engine == "postgis" and not payload.get("source_bindings"):
        source_bindings = []
        for table in candidate_tables or []:
            table_name = table.get("table_name")
            if table_name:
                table_bindings = table.get("execution_bindings") or {}
                source_bindings.append(
                    {
                        "table_name": table_name,
                        "source_kind": table.get("source_kind") or "postgis",
                        "physical_table": (
                            table_bindings.get("postgis", {}).get("table_name") or table_name
                        ),
                    }
                )
        if source_bindings:
            payload["source_bindings"] = source_bindings
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def _build_gemma_semantic_prompt(question: str, payload: dict) -> str:
    """Build a Gemma/Ollama prompt for one-shot semantic SQL generation."""
    return _build_family_semantic_prompt("gemma", question, payload)


def _build_family_semantic_prompt(
    family: str,
    question: str,
    payload: dict,
    execution_engine: str = "postgis",
) -> str:
    """Build a local-family prompt for one-shot semantic SQL generation."""
    grounding = payload.get("grounding_prompt") or ""
    stats = {
        key: value
        for key, value in (payload.get("_hint_injection_stats") or {}).items()
        if key != "family"
    }
    harness_notes = _family_harness_notes(family, execution_engine=execution_engine)
    identities = row_identity_context(payload)
    relational_guidance = relational_generation_guidance()
    if execution_engine == "lake":
        dialect_instruction = """Convert the user question into one read-only DuckDB SQL statement over registered GeoParquet views.

Rules:
- Output SQL only: no Markdown, no explanation.
- Return exactly the columns and aggregation requested by the user. Do not add
  helper columns, identifiers, geometry, aliases, rounding, COALESCE, or
  explanatory fields unless the question asks for them.
- Do not add `IS NOT NULL`, `DISTINCT`, `ORDER BY`, or any other predicate or
  presentation clause merely because it seems safer or more natural. Add it
  only when the question or the governed semantic contract requires it.
- Do not add an unrelated JOIN, CTE, subquery, GROUP BY, ST_Union, or spatial
  predicate. A JOIN is justified only by a requested column/filter or an
  explicitly requested spatial relationship.
- Only SELECT or WITH ... SELECT is allowed. never call read_parquet/read_csv/read_json, ATTACH, COPY, INSTALL, LOAD, or PRAGMA; query only the candidate logical table names.
- Use DuckDB SQL syntax. Do not use PostgreSQL casts such as ::geography or PostgreSQL-only operators.
- Prefer the business measure explicitly designated by the semantic context for a requested area or length. Use DuckDB Spatial ST_* functions only when the question explicitly asks for geometry-derived spatial computation.
- For spatial relations between two tables, use an explicit JOIN ... ON ST_Intersects/ST_Within/ST_Contains so DuckDB can select SPATIAL_JOIN. Never put a two-table spatial predicate inside a correlated EXISTS subquery.
- When the semantic context identifies a numeric-backed identifier, normalize its type before comparison instead of assuming that identifiers are always text.
- Table names and column names must come from the semantic context below. Preserve quoted identifiers for case-sensitive or non-ASCII columns.
- Apply business rules, aliases, units, value semantics, and examples from the semantic context. Do not invent dataset-specific columns.
- For joined entity counts, count the target entity once when an identifier column is available."""
    else:
        dialect_instruction = """Convert the user question into one read-only PostgreSQL/PostGIS SQL statement.

Rules:
- Output SQL only: no Markdown, no explanation.
- Return exactly the columns and aggregation requested by the user. Do not add
  helper columns, identifiers, geometry, aliases, rounding, COALESCE, or
  explanatory fields unless the question asks for them.
- Do not add `IS NOT NULL`, `DISTINCT`, `ORDER BY`, or any other predicate or
  presentation clause merely because it seems safer or more natural. Add it
  only when the question or the governed semantic contract requires it.
- Do not add an unrelated JOIN, CTE, subquery, GROUP BY, ST_Union, or spatial
  predicate. A JOIN is justified only by a requested column/filter or an
  explicitly requested spatial relationship.
- Only SELECT or WITH ... SELECT is allowed. If the request needs writes, DDL, permissions, or cannot be answered from the candidate schema, output SELECT 1.
- Read-only preview/listing/export/download/backup requests over available tables are answerable as SELECT statements; add a conservative LIMIT instead of outputting SELECT 1.
- Table names and column names must come from the semantic context below. Preserve quoted identifiers for case-sensitive or non-ASCII columns.
- Use PostGIS functions for spatial relations. Align SRIDs when the semantic context shows different geometry SRIDs.
- For a generic business area or length request, prefer the governed measure identified by the semantic context; use a geometry-derived metric only when the question explicitly asks for a geometric or spatially calculated value.
- Apply business rules, aliases, units, value semantics, and examples from the semantic context. Do not invent dataset-specific columns.
- For joined entity counts, count the target entity once when an identifier column is available."""
    return f"""You are the GIS Data Agent NL2Semantic2SQL executor.
{dialect_instruction}
{harness_notes}

Semantic candidate context:
{grounding}
{identities}
{relational_guidance}

Semantic injection stats:
{json.dumps(stats, ensure_ascii=False)}

User question:
{question}
"""


def _family_harness_notes(family: str, *, execution_engine: str = "postgis") -> str:
    """Return model-independent product constraints for the direct harness.

    The function name is retained for compatibility with existing callers.
    Product correctness constraints must not vary by model family; otherwise a
    family comparison measures different prompts rather than different models.
    """
    del family
    notes = """
Shared product harness notes:
- Do not append clauses after a semicolon. Output one complete SQL statement; never put AND, OR, or WHERE after LIMIT ...;.
- Use the exact geometry column named by the semantic context. Do not substitute a conventional name such as `geometry`, `geom`, or `shape`.
- For write/destructive requests output SELECT 1 only; never generate DELETE, UPDATE, DROP, INSERT, ALTER, TRUNCATE, or a SELECT wrapper around them.
- A missing value is not an implicit filter: preserve NULL rows unless the user
  explicitly asks for non-null/present/有值 records.
- Choose DISTINCT from the requested result grain: category values or entities
  may require deduplication without the word unique; stored observations retain
  legitimate duplicates. Joining details does not turn an entity list into an
  observation list. Do not invent output aliases.
- For "nearest/最近的 K 个" without a user-supplied radius, use a candidate
  set, order by the distance expression, and LIMIT K. Do not add ST_Intersects,
  ST_DWithin, or another range predicate; nearest-neighbour ranking is not a
  radius filter.
- For a spatial join count, count the entity named by the question. Use that
  entity's governed identifier with COUNT(DISTINCT ...) only when a one-to-many
  join could duplicate it; never count the other side of the join by default.
- If a requested measure, capacity, remaining amount, or business object has
  no matching governed field/table in the supplied semantic context, do not
  substitute a nearby field or table. The application should refuse the query.
""".rstrip()
    if execution_engine == "postgis":
        notes += """
- Use ST_Contains, ST_Within, and ST_Intersects with geometry operands. Use geography casts for ST_DWithin, ST_Distance, ST_Area, or ST_Length; ST_Contains(...::geography, ...::geography) is invalid.
""".rstrip()
    return notes


def _build_safe_preview_sql(question: str, payload: dict) -> str:
    """Build a conservative SELECT for read-only all-record preview requests."""
    q_low = (question or "").lower()
    preview_tokens = (
        "download",
        "export",
        "backup",
        "all rows",
        "all records",
        "preview",
        "show all",
        "下载",
        "导出",
        "备份",
        "全表",
        "select * from",
    )
    explicit_preview_phrase = bool(
        re.search(
            r"(?:展示|显示|查看|看看).{0,16}(?:全部|所有)|"
            r"(?:全部|所有).{0,16}(?:展示|显示|查看|看看)|"
            r"(?:展示|显示|查看|看看).{0,24}(?:不要遗漏|一条不漏)",
            q_low,
        )
    )
    if not explicit_preview_phrase and not any(token in q_low for token in preview_tokens):
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
    wants_geometry = any(
        term in q_low for term in ("坐标", "coordinate", "coordinates", "geometry", "geom", "位置")
    )
    scored: list[tuple[float, int, dict]] = []
    for table in candidate_tables:
        name = str(table.get("table_name") or "")
        score = float(table.get("confidence") or 0)
        if name and name.lower() in q_low:
            score += 100
        bare = name.split(".")[-1]
        if bare and bare.lower() in q_low:
            score += 100
        for table_alias in table.get("table_aliases", []) or []:
            alias = str(table_alias or "").strip().lower()
            if alias and alias in q_low:
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
    wants_geometry = any(
        term in q_low for term in ("坐标", "coordinate", "coordinates", "geometry", "geom", "位置")
    )
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
        "delete",
        "update",
        "insert",
        "drop",
        "truncate",
        "alter",
        "create table",
        "vacuum",
        "reindex",
        "cluster",
        "grant",
        "revoke",
        "rename",
        "删掉",
        "删除",
        "更新",
        "修改",
        "改成",
        "写入",
        "插入",
        "清空",
        "覆盖",
        "置为 null",
        "置为NULL",
        "执行 vacuum",
        "执行vacuum",
        "回收空间",
    )
    if any((re.search(rf"\b{re.escape(token)}\b", q_low) if token.isascii()
            else token in q_low) for token in write_tokens):
        return True

    if _has_missing_explicit_table_request(question, payload):
        return True

    if _has_missing_explicit_data_object_request(question, payload):
        return True

    if _has_missing_explicit_column_request(question, payload):
        return True

    if _has_ungrounded_availability_metric_request(question, payload):
        return True

    # A confident aggregation/attribute intent does not prove that the
    # requested business measure exists.  Refuse unavailable governed fields
    # before the model can substitute a convenient but unrelated column.
    if _has_ungrounded_explicit_metric_request(question, payload):
        return True

    ranking_terms = _extract_ranking_metric_terms(question)
    if ranking_terms:
        if payload.get("bird_db_id"):
            return False
        return not _payload_has_column_term(payload, tuple(ranking_terms))
    return False


def _has_missing_explicit_data_object_request(question: str, payload: dict) -> bool:
    """Reject a named Chinese/business dataset that is absent from grounding.

    This is deliberately catalog-driven.  The extractor only identifies the
    grammatical ``X data/layer/dataset`` shape; whether X exists is decided by
    the candidate table names, display names, descriptions, and aliases.
    """
    requested = _extract_explicit_data_object_terms(question)
    if not requested:
        return False
    # A physical-only payload does not contain enough catalog information to
    # prove that a Chinese object is absent.  Let normal semantic retrieval
    # handle that case; enforce the refusal once aliases/display metadata are
    # actually available.
    if not any(
        table.get("display_name")
        or table.get("table_aliases")
        or table.get("description")
        for table in payload.get("candidate_tables", []) or []
    ):
        return False
    known = _payload_table_terms(payload)
    for raw in requested:
        term = _normalize_semantic_search_term(raw)
        if not term:
            continue
        if any(term == item or term in item or item in term for item in known if item):
            continue
        return True
    return False


def _extract_explicit_data_object_terms(question: str) -> list[str]:
    q = str(question or "")
    generic = {
        "业务", "源", "真实", "原始", "治理", "候选", "空间", "属性", "几何",
        "统计", "所有", "全部", "完整", "当前", "这些", "该", "相关",
    }
    terms: list[str] = []
    for match in re.finditer(
        r"(?P<term>[A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff、和与及]{1,30}?)"
        r"(?:数据集|数据|图层)",
        q,
        flags=re.IGNORECASE,
    ):
        value = match.group("term")
        value = re.sub(
            r"^(?:请|帮我|我想|想要|从|在|用|基于|针对|查询|统计|分析|"
            r"展示|显示|返回|获取|看看|加载|读取|使用)+",
            "",
            value,
        )
        for part in re.split(r"[、,，和与及]+", value):
            part = part.strip()
            if len(part) < 2 or part in generic:
                continue
            terms.append(part)
    return list(dict.fromkeys(terms))


def _has_ungrounded_availability_metric_request(question: str, payload: dict) -> bool:
    """Detect capacity/remaining-value questions without a governed measure.

    Counts of rows remain computable.  This guard only covers stateful measures
    such as remaining inventory, available spaces, or unused capacity, which
    must be represented by a field or governed enum rather than approximated by
    counting a nearby entity table.
    """
    q = str(question or "")
    state = (
        r"空余|剩余|空闲|可用|空置|未用|余量|库存|余额|"
        r"available|vacant|remaining|unused|free\s+capacity"
    )
    quantity = (
        r"多少|几(?:个|条|处|位)?|数量|个数|总数|容量|余量|库存|余额|"
        r"车位|泊位|席位|名额|面积|长度|比例|率|"
        r"how\s+many|amount|quantity|capacity|inventory|balance"
    )
    if not re.search(state, q, flags=re.IGNORECASE):
        return False
    if not re.search(quantity, q, flags=re.IGNORECASE):
        return False

    probes: list[str] = []
    for match in re.finditer(state, q, flags=re.IGNORECASE):
        start = max(0, match.start() - 12)
        end = min(len(q), match.end() + 18)
        probes.append(q[start:end].strip(" ，,。；;：:"))
        probes.append(match.group(0))
    return not any(_payload_has_column_term(payload, (probe,)) for probe in probes if probe)


def _extract_ranking_metric_terms(question: str) -> list[str]:
    q = question or ""
    terms: list[str] = []
    computable_terms = (
        "数量",
        "条数",
        "个数",
        "次数",
        "面积",
        "距离",
        "名称",
        "名字",
        "objectid",
        "count",
        "sum",
        "total",
        "area",
        "distance",
        "name",
    )
    for match in re.finditer(r"([\u4e00-\u9fffA-Za-z_ ]{2,24})\s*(?:排名|排行)", q):
        term = match.group(1).strip(" 的按根据所有全部各个")
        term_low = term.lower()
        if term in {
            "请列出",
            "列出",
            "请给出",
            "给出",
            "请返回",
            "返回",
            "请展示",
            "展示",
            "请显示",
            "显示",
        }:
            continue
        if term and not any(t in term_low for t in computable_terms):
            terms.append(term)
    for match in re.finditer(
        r"\b([A-Za-z][A-Za-z_ ]{2,40}?)\s+(?:ranking|rank|top)\b", q, re.IGNORECASE
    ):
        term = match.group(1).strip()
        if term:
            terms.append(term)
    return list(dict.fromkeys(terms))


def _question_requests_spatial_relation(question: str) -> bool:
    q = question or ""
    q_low = q.casefold()
    markers = (
        "st_intersects",
        "st_contains",
        "st_within",
        "st_dwithin",
        "intersect",
        "within",
        "inside",
        "nearest",
        "distance",
        "相交",
        "重叠",
        "穿过",
        "经过",
        "沿线",
        "范围内",
        "范围里",
        "位于",
        "落在",
        "最近",
        "距离",
        "周边",
        "邻近",
    )
    return any(marker in q_low for marker in markers)


def _sql_has_requested_spatial_relation(sql: str) -> bool:
    return bool(
        re.search(
            r"\bST_(?:INTERSECTS|CONTAINS|WITHIN|DWITHIN|DISTANCE|TOUCHES|"
            r"CROSSES|OVERLAPS|INTERSECTION)\s*\(|<->",
            sql or "",
            flags=re.IGNORECASE,
        )
    )


def _generated_sql_missing_requested_spatial_relation(
    question: str,
    sql: str,
    payload: dict,
) -> bool:
    candidates = payload.get("candidate_tables") or []
    return bool(
        len(candidates) >= 2
        and _question_requests_spatial_relation(question)
        and not _sql_has_requested_spatial_relation(sql)
    )


def _build_missing_spatial_relation_retry_prompt(
    question: str,
    payload: dict,
    previous_sql: str,
    *,
    family: str,
    execution_engine: str,
) -> str:
    candidate_names = [
        str(table.get("table_name") or "")
        for table in payload.get("candidate_tables") or []
        if table.get("table_name")
    ]
    return (
        _build_family_semantic_prompt(
            family,
            question,
            payload,
            execution_engine=execution_engine,
        )
        + "\n\nHarness correction:\n"
        + "- The previous SQL omitted the spatial relationship explicitly requested "
        + "by the user.\n"
        + "- Reference both governed business objects and express the requested relation "
        + "with an appropriate spatial predicate or distance expression.\n"
        + "- Preserve all requested filters, grouping, projections, ordering, units, and LIMIT.\n"
        + f"- Governed candidate tables: {', '.join(candidate_names)}.\n"
        + f"Previous SQL: {previous_sql}\n"
    )


def _payload_has_column_term(payload: dict, terms: tuple[str, ...]) -> bool:
    lowered_terms = [
        term for term in (_normalize_semantic_search_term(term) for term in terms) if term
    ]
    for table in payload.get("candidate_tables", []) or []:
        for col in table.get("columns", []) or []:
            probes = [
                str(col.get("column_name") or ""),
                str(col.get("quoted_ref") or ""),
                str(col.get("semantic_domain") or ""),
                str(col.get("description") or ""),
            ]
            probes.extend(str(a) for a in (col.get("aliases") or []))
            vs = col.get("value_semantics") or {}
            probes.extend(str(a) for a in (vs.get("sql_aliases") or []))
            for key in (
                "natural_unit_aliases",
                "stored_unit_aliases",
                "semantic_aliases",
                "business_aliases",
            ):
                probes.extend(str(a) for a in (vs.get(key) or []))
            probes.extend(str(value) for value in (col.get("sample_values") or []))
            for enum_item in vs.get("enum") or []:
                if isinstance(enum_item, dict):
                    probes.extend(
                        str(enum_item.get(key) or "")
                        for key in ("value", "meaning", "label", "name")
                    )
                else:
                    probes.append(str(enum_item))
            for group in vs.get("semantic_groups") or []:
                if not isinstance(group, dict):
                    continue
                probes.extend(str(value) for value in (group.get("values") or []))
                probes.extend(str(alias) for alias in (group.get("aliases") or []))
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
    known_columns = _payload_column_terms(payload)
    refs = [
        ref
        for ref in refs
        if _normalize_identifier_like(ref.split(".")[-1]) not in known_columns
    ]
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
        tail = q[match.end() : match.end() + 8].lower()
        prefix = ref.split(".")[-1].lower()
        if q[match.end() :].lstrip().startswith("(") or prefix.startswith("st_"):
            continue
        if (
            "." in ref
            or re.search(r"(?:\bFROM|\bJOIN|从|查询)\s*$", q[:match.start()], re.IGNORECASE)
            or any(
                marker in tail
                for marker in ("表", "数据集", "图层", "table", "dataset", "layer")
            )
        ):
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
        term
        for term in terms
        if _normalize_semantic_search_term(term) not in table_terms
        and not _is_computable_metric_term(term)
        and not _is_entity_count_term(term, table_terms)
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
    # Availability questions often name a business measure in quotes rather
    # than as a physical identifier, for example "有没有一个叫‘拥堵指数’的
    # 指标". Treat the quoted noun as a schema probe; the governed catalog,
    # not a benchmark vocabulary, decides whether the measure exists.
    for match in re.finditer(
        r"(?:叫|名为|名称为)?\s*[‘’“”\"'](?P<term>[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]{1,39})"
        r"[‘’“”\"']\s*(?:的)?\s*(?:指标|字段|列)",
        q,
        flags=re.IGNORECASE,
    ):
        term = match.group("term").strip()
        if _looks_like_explicit_metric_token(term):
            terms.append(term)
    for segment in re.findall(r"[（(]\s*([^（）()]{1,80})\s*[）)]", q):
        for raw in re.split(r"[,，、/;；\s]+", segment):
            raw = raw.strip()
            if "'" in raw or '"' in raw:
                continue
            term = raw.strip(" 等")
            if _looks_like_explicit_metric_token(term):
                terms.append(term)

    # Detect an arbitrary requested metric phrase without a benchmark
    # vocabulary. For "各区域的某指标数据", only the final possessive segment
    # is a schema probe; the semantic catalog decides whether it is supported.
    preview_request = bool(re.search(r"展示|显示|查看|预览|导出|下载|preview|export|show", q, flags=re.IGNORECASE))
    for match in re.finditer(r"(?P<term>[A-Za-z_\u4e00-\u9fff]{2,24})数据", q):
        if preview_request and "的" not in q[:match.start()]:
            continue
        term = re.split(r"的", match.group("term"))[-1]
        term = re.sub(
            r"^(?:帮我|请|我想|想要|从|在|用|基于|查询|统计|分析|"
            r"展示|显示|返回|获取|看看|一下|所有|全部|各|每个)+",
            "",
            term,
        )
        # ``X 数据`` is often a dataset reference (asset data, land-use
        # data), not a requested measure. Only identifier/measure-shaped
        # phrases enter the unknown-metric guard; governed table selection is
        # handled independently by semantic grounding.
        if (
            term
            and _looks_like_explicit_metric_token(term)
            and not _is_generic_metric_phrase(f"{term}数据")
        ):
            terms.append(term)
    # Generic noun phrases before a count/answer clause, e.g. "每条记录的
    # 指标A和指标B是多少". The semantic schema still decides support.
    for match in re.finditer(
        r"(?:的)(?P<body>[\u4e00-\u9fffA-Za-z0-9_、，,和及与\s]{2,48}?)(?=(?:是多少|有多少|有几|分布|排名|最多|最少|$))",
        q,
        flags=re.IGNORECASE,
    ):
        body = match.group("body")
        if re.search(r"范围|相交|包含|之内|内的|列表|返回|使用|查询", body):
            continue
        for raw in re.split(r"[、，,和及与\s]+", body):
            term = raw.strip(" 等")
            if _looks_like_explicit_metric_token(term):
                terms.append(term)
    # Temporal/value conditions can name an ungoverned attribute without an
    # explicit "数据" suffix (for example "2020 年之后建成的对象").
    for match in re.finditer(
        r"\d[\d,]*(?:\.\d+)?\s*(?:年|月|日)?(?:之后|以前|之前|之后).*?(?P<term>[\u4e00-\u9fff]{2,8})的",
        q,
    ):
        term = match.group("term").strip()
        if term and term not in {"查询", "统计", "展示", "返回", "对象", "建筑物", "地块", "图斑"}:
            terms.append(term)
    return list(dict.fromkeys(terms))


def _looks_like_explicit_metric_token(term: str) -> bool:
    value = str(term or "").strip().strip("'\"")
    if len(value) < 2:
        return False
    # Parentheses in Chinese questions commonly contain explanatory prose;
    # accept only identifier-shaped English names or short Chinese noun terms.
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,40}", value):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{2,16}", value):
        if value in {
            "含端点", "包含端点", "类型", "名称", "名字", "字段", "单位",
            "中包含", "精确匹配", "完全匹配", "使用", "不转", "转", "返回",
            "计算", "查询", "统计", "展示", "显示", "排序", "升序", "降序",
            "子查询", "空间合并", "土地利用", "图斑", "地块", "建筑物",
        }:
            return False
        return value.endswith(("量", "价", "幅", "率", "数", "数量", "时间", "日期", "年份", "等级", "速度", "速", "值", "面积", "长度", "距离", "指标", "类型", "代码", "编码"))
    return False


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
    if raw.endswith(("面积", "长度", "距离", "比例", "总和", "总数")):
        return True
    if raw_low in {
        "is",
        "not",
        "null",
        "like",
        "in",
        "and",
        "or",
        "use",
        "using",
        "exists",
        "geography",
    }:
        return True
    if "小数" in raw or "保留" in raw:
        return True
    if raw in {"使用", "升序", "降序", "排序", "合计", "汇总"}:
        return True
    if raw.endswith("数据") and raw not in {"房价数据", "降雨量数据"}:
        return True
    value = _normalize_semantic_search_term(term)
    computable = {
        "count",
        "sum",
        "avg",
        "average",
        "min",
        "max",
        "total",
        "area",
        "length",
        "distance",
        "centroid",
        "center",
        "wkt",
        "geometry",
        "geom",
        "shape",
        "intersects",
        "within",
        "contains",
        "st_intersects",
        "st_dwithin",
        "knn",
        "poi",
        "aoi",
        "sql",
        "id",
        "数量",
        "条数",
        "个数",
        "次数",
        "面积",
        "总面积",
        "长度",
        "总长",
        "距离",
        "质心",
        "中心点",
        "坐标",
        "名称",
        "名字",
        "编号",
        "米",
        "千米",
        "公里",
        "平方米",
        "公顷",
    }
    return value in computable


def _is_entity_count_term(term: str, table_terms: set[str]) -> bool:
    """Recognize computed entity counts only through governed table aliases."""
    raw = str(term or "").strip()
    for suffix in ("数量", "个数", "条数"):
        if not raw.endswith(suffix):
            continue
        entity = _normalize_semantic_search_term(raw[: -len(suffix)])
        if entity and entity in table_terms:
            return True
    return False


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
        "table",
        "schema",
        "select",
        "from",
        "where",
        "and",
        "or",
        "by",
        "as",
        "like",
        "ilike",
        "limit",
        "join",
        "on",
        "group",
        "order",
        "having",
    }
    terms: list[str] = []
    for raw in re.findall(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_])", q):
        norm = _normalize_identifier_like(raw)
        if not norm or norm in table_terms:
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
            norm = _normalize_semantic_search_term(probe)
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
    dialect: str = "postgres",
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
        dialect=dialect,
    )
    if fallback_pp.rejected:
        return None, f"postprocess:{fallback_pp.reject_reason}"

    from .runtime_guards import is_safe_sql

    fallback_ok, fallback_reason = is_safe_sql(fallback_pp.sql, set(schemas.keys()))
    if not fallback_ok:
        return None, f"runtime_guard:{fallback_reason}"
    return fallback_pp, ""


def _is_unbounded_full_row_preview(question: str, sql: str, payload: dict) -> bool:
    """Return whether a broad read-only preview still lacks a top-level LIMIT."""
    if not _build_safe_preview_sql(question, payload):
        return False
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql or "", read="postgres")
        if not isinstance(tree, exp.Select) or tree.args.get("limit") is not None:
            return False
        # Broad export/preview requests need a bound even when the model
        # projected geometry or an explicit column list instead of ``*``.
        # Aggregations remain unbounded because they already collapse rows.
        return not any(isinstance(node, exp.AggFunc) for node in tree.walk())
    except Exception:
        return bool(
            re.match(r"^\s*SELECT\s+\*\s+FROM\s+", sql or "", flags=re.IGNORECASE)
            and not re.search(r"\bLIMIT\s+\d+\b", sql or "", flags=re.IGNORECASE)
        )


@observe_stage("planning.generate")
def _generate_gemma_sql(
    prompt: str, model_name: str | None = None, *, output_contract: str = "sql",
    response_format: dict | None = None,
) -> str:
    """Generate SQL through the configured model endpoint.

    The historical name is kept as an internal compatibility surface. The
    implementation is model-independent and is used for Gemma and Qwen.
    """
    annotate_stage(purpose=output_contract)
    if response_format is not None and output_contract != "registered_ir_json":
        raise ValueError("A catalog response format is only supported for registered IR generation")
    explicit_model_name = model_name is not None
    model_name = model_name or _get_standard_model_name()
    if not explicit_model_name and (
        os.environ.get("GDA_LLM_BASE_URL") or os.environ.get("GDA_LLM_PROVIDER")
    ):
        from .openai_compatible_llm import (
            OpenAICompatibleLLMConfig,
            chat_completion,
        )

        config = OpenAICompatibleLLMConfig.from_env()
        format_kwargs = {}
        if output_contract == "review_json" and config.provider == "ollama":
            from .nl2sql_output_contracts import review_response_format

            format_kwargs["response_format"] = review_response_format()
        if output_contract == "answer_plan_json" and config.provider == "ollama":
            from .nl2sql_answer_plan import answer_plan_format
            format_kwargs["response_format"] = answer_plan_format()
        if output_contract == "registered_ir_json" and config.provider == "ollama":
            from .nl2sql_registered_ir import registered_ir_response_format

            format_kwargs["response_format"] = response_format if response_format is not None else registered_ir_response_format()
        if response_format is not None and "response_format" not in format_kwargs:
            raise ValueError("Catalog-constrained generation requires the Ollama schema endpoint")
        max_tokens = generation_token_budget(config.provider, config.api_style)
        attempts = _generation_retry_attempts()
        deadline_seconds = float(os.environ.get("GDA_NL2SQL_GENERATION_DEADLINE_SECONDS", "0"))
        import math
        if not math.isfinite(deadline_seconds) or deadline_seconds < 0:
            raise ValueError("GDA_NL2SQL_GENERATION_DEADLINE_SECONDS must be finite and nonnegative")
        generation_deadline = time.monotonic() + deadline_seconds if deadline_seconds else None
        last_exc: Exception | None = None
        for attempt in range(attempts):
            attempt_config = config
            if generation_deadline is not None:
                from dataclasses import replace
                from .openai_compatible_llm import LLMServiceError
                remaining = generation_deadline - time.monotonic()
                if remaining <= 0:
                    raise LLMServiceError("SQL generation deadline exceeded", code="generation_deadline", retryable=False)
                attempt_config = replace(config, timeout_seconds=min(config.timeout_seconds, remaining))
            try:
                response_text, evidence = chat_completion(
                    system_prompt=generation_system_prompt(output_contract),
                    user_prompt=prompt,
                    config=attempt_config,
                    max_tokens=max_tokens,
                    **format_kwargs,
                )
                evidence["generation_attempt"] = attempt + 1
                evidence["generation_attempt_limit"] = attempts
                evidence["max_output_tokens"] = max_tokens
                evidence["output_contract"] = output_contract
                _record_llm_evidence(evidence)
                return response_text
            except Exception as exc:
                last_exc = exc
                failure_evidence = dict(getattr(exc, "evidence", {}) or {})
                if failure_evidence:
                    failure_evidence.update(
                        generation_attempt=attempt + 1, generation_attempt_limit=attempts,
                        max_output_tokens=max_tokens, output_contract=output_contract)
                    _record_llm_evidence(failure_evidence)
                if attempt >= attempts - 1 or getattr(exc, "retryable", True) is False:
                    raise
                delay = _generation_retry_delay(config.provider, attempt)
                if generation_deadline is not None and generation_deadline - time.monotonic() <= delay:
                    from .openai_compatible_llm import LLMServiceError
                    raise LLMServiceError("SQL generation deadline exceeded before retry", code="generation_deadline", retryable=False) from exc
                with stage("llm.retry_wait"):
                    time.sleep(delay)
        raise last_exc or RuntimeError("configured SQL generation failed")

    if response_format is not None:
        raise ValueError("Catalog-constrained generation requires the configured Ollama schema endpoint")

    from .llm_call_budget import active_budget
    if active_budget() is not None:
        # This legacy SDK route has its own retry behavior. Budgeted runs
        # must use the single-dispatch transport, never silently bypass it.
        active_budget()._deny("budget_unsupported_legacy_transport")

    from .model_gateway import ModelRegistry, create_model

    adk_model = create_model(model_name)
    info = ModelRegistry.get_model_info(model_name)
    completion_kwargs = {
        "model": getattr(adk_model, "model", None) or info.get("model_id", model_name),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    if output_contract != "sql":
        completion_kwargs["messages"].insert(
            0, {"role": "system", "content": generation_system_prompt(output_contract)}
        )

    additional_args = getattr(adk_model, "_additional_args", {}) or {}
    extra_body = additional_args.get("extra_body") or info.get("extra_body")
    if extra_body:
        completion_kwargs["extra_body"] = extra_body
    timeout = additional_args.get("timeout") or info.get("request_timeout")
    if timeout:
        completion_kwargs["timeout"] = timeout

    import litellm

    attempts = _generation_retry_attempts()
    last_exc: Exception | None = None
    started = time.perf_counter()
    for attempt in range(attempts):
        try:
            with stage("llm.request", purpose=output_contract, model=model_name,
                       provider=str(info.get("backend") or "unknown"), dispatched=True):
                resp = litellm.completion(**completion_kwargs)
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            with stage("llm.retry_wait"):
                time.sleep(min(2**attempt, 8))
    else:
        raise last_exc or RuntimeError("Gemma SQL generation failed")

    msg = resp.choices[0].message
    if isinstance(msg, dict):
        response_text = (msg.get("content") or "").strip()
    else:
        response_text = (getattr(msg, "content", "") or "").strip()
    usage = getattr(resp, "usage", None)

    def usage_value(name: str):
        return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)

    from .openai_compatible_llm import infer_llm_provider, normalize_openai_base_url

    configured_base = (
        os.environ.get("GDA_LLM_BASE_URL")
        or info.get("api_base")
        or os.environ.get("OLLAMA_API_BASE")
        or "http://127.0.0.1:11434/v1"
    )
    try:
        base_url = normalize_openai_base_url(configured_base)
        provider = infer_llm_provider(base_url, os.environ.get("GDA_LLM_PROVIDER"))
    except ValueError:
        base_url = str(configured_base)
        provider = str(info.get("backend") or "local")
    _record_llm_evidence(
        {
            "provider": provider,
            "model": model_name,
            "transport_model": completion_kwargs["model"],
            "output_contract": output_contract,
            "base_url": base_url,
            "request_id": str(getattr(resp, "id", "") or ""),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
            "usage": {
                "prompt_tokens": usage_value("prompt_tokens"),
                "completion_tokens": usage_value("completion_tokens"),
                "total_tokens": usage_value("total_tokens"),
            },
            "status": "succeeded",
        }
    )
    return response_text


def apply_gemma_semantic_rewrites(
    question: str,
    sql: str,
    context: dict,
) -> tuple[str, list[str]]:
    """Compatibility wrapper for the config-driven semantic SQL rewriter."""
    from .nl2sql_semantic_rewrite import apply_semantic_sql_rewrites

    return apply_semantic_sql_rewrites(question, sql, context)


def _ensure_spatial_join_entity_distinct(sql: str) -> tuple[str, list[str]]:
    """Prevent one-to-many spatial joins from inflating entity counts.

    A spatial join can match one target feature to many source features.  For
    questions phrased as a count of buildings/roads/POIs, ``COUNT(alias.id)``
    therefore counts join pairs rather than entities.  The governed benchmark
    contract uses identifier counts for these cases, so normalize the common
    non-DISTINCT form before either physical engine executes it.
    """
    value = str(sql or "")
    if not re.search(
        r"\bST_(?:Intersects|Within|Contains|Touches|Crosses|Overlaps)\s*\(", value, re.I
    ):
        return value, []
    # Grouped counts have an explicit per-group cardinality contract and are
    # already handled by the semantic rewriter using the requested target
    # entity.  Applying this blanket fallback afterwards can incorrectly turn
    # a requested source-row count (for example POIs per district) into a
    # distinct identifier count when the source contains repeated IDs.
    if re.search(r"\bGROUP\s+BY\b", value, flags=re.IGNORECASE):
        return value, []
    pattern = re.compile(
        r"\bCOUNT\s*\(\s*(?!DISTINCT\b)"
        r"(?P<ref>[A-Za-z_][A-Za-z0-9_]*\s*\.\s*(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*\)",
        flags=re.IGNORECASE,
    )
    normalized, count = pattern.subn(lambda match: f"COUNT(DISTINCT {match.group('ref')})", value)
    return normalized, (["spatial_join_entity_count_distinct"] if count else [])


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


def _find_misbound_schema_column(
    sql: str,
    schemas: dict,
    *,
    execution_engine: str = "postgis",
) -> str:
    """Return a table-scoped column reference absent from its physical table.

    The validator intentionally uses only the runtime schema.  It has no
    knowledge of benchmark questions, dataset names, or expected SQL.
    """
    if not schemas:
        return ""
    try:
        import sqlglot
        from sqlglot import exp

        dialect = _dialect_for_engine(execution_engine)
        tree = sqlglot.parse_one(sql or "", read=dialect)
        by_name: dict[str, str] = {}
        column_sets: dict[str, set[str]] = {}
        for table_name, columns in schemas.items():
            key = str(table_name)
            column_sets[key] = {
                str(column.get("column_name") or "").casefold()
                for column in columns or []
                if column.get("column_name")
            }
            by_name[key.casefold()] = key
            by_name[key.split(".")[-1].casefold()] = key

        aliases: dict[str, str] = {}
        referenced: set[str] = set()
        for table in tree.find_all(exp.Table):
            schema_key = by_name.get(str(table.name or "").casefold())
            if not schema_key:
                continue
            aliases[str(table.name).casefold()] = schema_key
            aliases[str(table.alias_or_name).casefold()] = schema_key
            referenced.add(schema_key)

        projected_aliases = {
            str(alias.alias or "").casefold()
            for alias in tree.find_all(exp.Alias)
            if alias.alias
        }
        for column in tree.find_all(exp.Column):
            name = str(column.name or "")
            if not name or name == "*":
                continue
            if column.table:
                schema_key = aliases.get(str(column.table).casefold())
                if schema_key and name.casefold() not in column_sets.get(schema_key, set()):
                    return f"{column.table}.{name}"
                continue
            if len(referenced) == 1:
                schema_key = next(iter(referenced))
                if (
                    name.casefold() not in column_sets.get(schema_key, set())
                    and name.casefold() not in projected_aliases
                ):
                    return name
    except Exception:
        # SQL parsing and the physical engine remain the final authorities.
        return ""
    return ""


def _retry_with_llm(
    question: str,
    failed_sql: str,
    error: str,
    schemas: dict,
    execution_engine: str = "postgis",
) -> str | None:
    """Ask LLM to fix the failed SQL based on error message.

    Uses the same configured model route as initial SQL generation. This keeps
    an air-gapped Ollama/LM Studio deployment offline and makes retry evidence
    consistent with the primary request. Returns fixed SQL or None.
    """
    schema_block = _format_schema_for_retry(schemas)
    governed_context = retry_grounding(question)
    dialect = (
        "DuckDB SQL over registered governed GeoParquet views. Never call read_parquet, "
        "read_csv, ATTACH, COPY, INSTALL, or LOAD."
        if execution_engine == "lake"
        else "PostgreSQL/PostGIS SQL."
    )
    base_prompt = (
        f"You are a {dialect} repair assistant. The previous SQL failed.\n\n"
        f"Original question: {question}\n"
        f"Failed SQL: {failed_sql}\n"
        f"Error: {error}\n\n"
        f"Available schema:\n{schema_block}\n\n"
        f"Authorized semantic context:\n{governed_context}\n\n"
        "Repair the SQL. Output only the repaired SQL, with no explanation.\n"
        "Preserve double quotes for case-sensitive or non-ASCII column names.\n"
        "Treat the schema as table-scoped: every qualified field must belong to "
        "the physical table represented by that alias. Never copy a field from "
        "another candidate table, change the target entity, or substitute a nearby "
        "business measure. Do not add DISTINCT, IS NOT NULL, ordering, filtering, "
        "or a spatial predicate unless the original question requires it."
    )
    feedback = ""
    for _ in range(MAX_RETRIES):
        try:
            raw = _generate_gemma_sql(base_prompt + feedback)
            fixed = _extract_sql(raw)
        except Exception:
            return None
        if not fixed:
            return None
        misbound = _find_misbound_schema_column(
            fixed,
            schemas,
            execution_engine=execution_engine,
        )
        if not misbound:
            return fixed
        feedback = (
            "\n\nThe attempted repair is still invalid: field reference "
            f"`{misbound}` does not belong to its referenced physical table. "
            "Repair it using the table-scoped schema above."
        )
    return None


@observe_stage("query.final_audit")
def _validate_review_revision(
    sql: str,
    payload: dict,
    governed_source_bindings: dict[str, dict] | None = None,
) -> None:
    """A semantic reviewer cannot expand the authorized source boundary."""
    from .runtime_guards import is_safe_sql
    from .nl2sql_metric_compiler import compile_product_metrics

    # Review validates the executable expansion; the selected slot remains
    # in the draft until final compilation after all model revisions.
    sql, _ = compile_product_metrics(sql, payload, "postgis")

    schemas, _ = _schemas_and_large_tables(payload)
    bird_db_id = payload.get("bird_db_id")
    ok, reason = is_safe_sql(sql, None if bird_db_id else set(schemas))
    if not ok:
        raise ValueError(f"runtime_guard:{reason}")
    if bird_db_id:
        from .bird_source import _validated_sql

        columns = {
            name.rsplit(".", 1)[-1]: [c["column_name"] for c in fields]
            for name, fields in schemas.items()
        }
        _validated_sql(bird_db_id, sql, columns)
    else:
        ungrounded = _find_ungrounded_sql_reference("", sql, payload)
        if ungrounded:
            raise ValueError(f"runtime_guard:ungrounded_table:{ungrounded}")
    unbound = _ungoverned_sql_source(sql, governed_source_bindings)
    if unbound:
        raise ValueError(f"source_admission:unbound_source:{unbound}")


def _auto_curate(question: str, sql: str, execution_engine: str = "postgis") -> None:
    """Auto-curate successful (question, SQL) pairs into reference_queries.

    Uses dedup (cosine > 0.92) built into ReferenceQueryStore.add().
    Infers domain_id from table names in the SQL for domain isolation.
    Non-fatal: silently ignores any errors.
    """
    if not question or not sql:
        return
    if os.environ.get("GDA_NL2SQL_AUTO_CURATE", "1") == "0":
        return
    local_provider = os.environ.get("GDA_LLM_PROVIDER", "").strip().casefold()
    if (
        local_provider in {"ollama", "lm_studio", "openai_compatible"}
        and os.environ.get("GDA_NL2SQL_AUTO_CURATE_LOCAL", "0") != "1"
    ):
        # Air-gapped query execution must not trigger an unrelated external
        # embedding request. Sites with a configured local embedding service
        # can opt back in explicitly.
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
            tags=[f"engine:{'duckdb' if execution_engine == 'lake' else 'postgis'}"],
            task_type="nl2sql",
            source="auto_curate",
            domain_id=domain_id,
        )
    except Exception:
        pass


def prepare_nl2sql_context(
    user_question: str,
    execution_engine: str | None = None,
) -> str:
    """Prepare semantic/schema grounding prompt for NL2SQL generation.

    Caches per-request schemas and large-table hints in ContextVars so the next
    tool call `execute_nl2sql()` can postprocess the generated SQL.
    """
    current_grounded_request.set(None)
    family = _active_direct_harness_family()
    requested_engine = _normalize_execution_engine(execution_engine)
    context_kwargs = {}
    if requested_engine != "postgis":
        context_kwargs["execution_engine"] = requested_engine
    payload = build_nl2sql_context(user_question, **context_kwargs)
    resolved_engine = _resolve_execution_engine(payload, requested_engine)
    payload = _filter_payload_for_execution_engine(payload, resolved_engine, family)
    remember_retry_grounding(user_question, payload)

    schemas = {}
    large_tables = set()
    for table in payload.get("candidate_tables", []):
        name = table["table_name"]
        schemas[name] = table.get("columns", [])
        if int(table.get("row_count_hint", 0) or 0) >= 1_000_000:
            large_tables.add(name)

    current_nl2sql_question.set(user_question)
    current_nl2sql_execution_engine.set(resolved_engine)
    current_nl2sql_candidate_tables.set(payload.get("candidate_tables") or [])
    current_nl2sql_schemas.set(schemas)
    current_nl2sql_large_tables.set(large_tables)

    intent = payload.get("intent")
    if intent is not None:
        current_nl2sql_intent.set(intent)

    grounding = payload.get("grounding_prompt", "")
    if resolved_engine == "lake":
        return (
            "Execution engine: DuckDB over governed GeoParquet logical views. "
            "Generate DuckDB SQL and never call file-reading table functions.\n\n" + grounding
        )
    return grounding


def execute_nl2sql(sql: str) -> str:
    """Postprocess, execute, and self-correct NL2SQL-generated SQL.

    Phase 2 enhancements:
    - On execution failure, retries up to MAX_RETRIES times with LLM-based SQL fix
    - On success, auto-curates (question, SQL) pair into reference_queries for few-shot
    """
    schemas = current_nl2sql_schemas.get()
    large_tables = current_nl2sql_large_tables.get()
    question = current_nl2sql_question.get()
    execution_engine = current_nl2sql_execution_engine.get()
    candidate_tables = current_nl2sql_candidate_tables.get()

    last_sql = sql

    for attempt in range(MAX_RETRIES + 1):
        pp_result = postprocess_sql(
            last_sql,
            schemas,
            large_tables,
            intent=current_nl2sql_intent.get(),
            dialect=_dialect_for_engine(execution_engine),
        )
        if pp_result.rejected:
            return f"安全拒绝: {pp_result.reject_reason}"

        from .runtime_guards import is_safe_sql

        guard_ok, guard_reason = is_safe_sql(pp_result.sql, set(schemas.keys()))
        if not guard_ok:
            return f"安全拒绝: runtime_guard:{guard_reason}"

        exec_result = _execute_for_engine(
            pp_result.sql,
            {"candidate_tables": candidate_tables},
            execution_engine,
        )

        try:
            parsed = json.loads(exec_result)
        except Exception:
            parsed = {}

        error = parsed.get("error")
        if error is None or parsed.get("status") == "ok":
            if execution_engine == "lake":
                _auto_curate(question, pp_result.sql, execution_engine)
            else:
                _auto_curate(question, pp_result.sql)
            return _annotate_execution_result(exec_result, execution_engine, candidate_tables)

        if attempt >= MAX_RETRIES:
            return _annotate_execution_result(exec_result, execution_engine, candidate_tables)

        fixed_sql = _retry_with_llm(
            question,
            pp_result.sql,
            str(error),
            schemas,
            execution_engine=execution_engine,
        )
        if not fixed_sql:
            return _annotate_execution_result(exec_result, execution_engine, candidate_tables)

        last_sql = fixed_sql


@observe_request
def run_nl2semantic2sql(
    user_question: str,
    execution_engine: str | None = None,
    *,
    governed_source_bindings: dict[str, dict] | None = None,
    max_result_items: int = 100_000,
    bird_db_id: str | None = None,
) -> str:
    """Run product NL2SQL, reporting semantic compiler failures explicitly."""
    from .nl2sql_metric_compiler import MetricCompilationError
    from .nl2sql_metric_grounding import MetricCatalogUnavailable
    from .nl2sql_route_policy import QueryPolicyError, resolve_bird_query_policy
    policy = None
    # A configuration rejection must not reuse model evidence from an earlier
    # request in the same worker/context.
    current_nl2sql_llm_evidence.set({})
    current_nl2sql_llm_calls.set([])
    try:
        if bird_db_id:
            policy = resolve_bird_query_policy()
        result = _run_nl2semantic2sql(
            user_question, execution_engine,
            governed_source_bindings=governed_source_bindings,
            max_result_items=max_result_items, bird_db_id=bird_db_id,
            route_policy=policy,
        )
        if policy is not None:
            report = json.loads(result)
            report["query_policy"] = policy.evidence()
            return json.dumps(report, ensure_ascii=False)
        return result
    except QueryPolicyError as exc:
        return json.dumps({"status": "rejected", "error": "query_policy:" + str(exc), "sql": "",
                           "query_policy": {"status": "rejected"}, "llm_calls": []}, ensure_ascii=False)
    except (MetricCompilationError, MetricCatalogUnavailable) as exc:
        return json.dumps({
            "status": "rejected", "error": "semantic_contract:" + str(exc), "sql": "",
            "metric_compilation": {"status": "rejected", "reason": str(exc),
                                   "evidence": getattr(exc, "evidence", {})},
            "llm": current_nl2sql_llm_evidence.get(),
            "llm_calls": current_nl2sql_llm_calls.get(),
            "llm_usage": _aggregate_llm_evidence(),
            "query_policy": policy.evidence() if policy else {},
        }, ensure_ascii=False)


def _run_nl2semantic2sql(
    user_question: str,
    execution_engine: str | None = None,
    *,
    governed_source_bindings: dict[str, dict] | None = None,
    max_result_items: int = 100_000,
    bird_db_id: str | None = None,
    route_policy=None,
) -> str:
    """Run local-family/Ollama NL2Semantic2SQL as one high-level tool call.

    This is the production path for local models such as Gemma4 and Qwen3.6
    because exposing the low-level semantic/database tools to the model can
    trap it in repeated tool calls.
    The Python side owns the full workflow: semantic grounding, SQL generation,
    deterministic semantic fixes, guards, execution, and structured return.
    """
    if bird_db_id and route_policy is None:
        from .nl2sql_route_policy import resolve_bird_query_policy
        route_policy = resolve_bird_query_policy()
    current_grounded_request.set(None)
    harness_family = _active_direct_harness_family()
    current_nl2sql_llm_evidence.set({})
    current_nl2sql_llm_calls.set([])
    from .nl2sql_candidates import candidates_enabled, in_candidate_run, run_product_candidates
    try:
        use_candidates = bool(bird_db_id and not in_candidate_run() and candidates_enabled())
    except ValueError:
        return json.dumps({"status": "rejected", "error": "execution_consensus:invalid_setting", "sql": ""})
    if use_candidates:
        record_route("candidates")
        try:
            from .bird_source import query_rows, registered_database
            if _normalize_execution_engine(execution_engine) not in {"auto", "postgis"}:
                raise ValueError("Execution consensus requires the registered PostgreSQL source")
            if route_policy and route_policy.route == "registered_ir":
                raise ValueError("Execution consensus and registered IR are separate experimental paths")

            state_variables = (
                current_grounded_request, current_nl2sql_schemas, current_nl2sql_large_tables,
                current_nl2sql_question, current_nl2sql_intent, current_nl2sql_requested_engine,
                current_nl2sql_execution_engine, current_nl2sql_candidate_tables,
            )
            candidate_states = []

            def run_single():
                product = json.loads(run_nl2semantic2sql(
                    user_question, execution_engine,
                    governed_source_bindings=governed_source_bindings,
                    max_result_items=max_result_items, bird_db_id=bird_db_id,
                ))
                # Early guard rejections also consumed model calls.
                product.setdefault("llm_calls", current_nl2sql_llm_calls.get())
                product.setdefault("llm", current_nl2sql_llm_evidence.get())
                candidate_states.append(tuple(variable.get() for variable in state_variables))
                return product

            def read_result(product):
                kwargs = {"parameters": product["sql_parameters"]} if "sql_parameters" in product else {}
                return query_rows(bird_db_id, product["sql"], max_rows=max_result_items, **kwargs)

            result = run_product_candidates(run_single, read_result,
                                            lambda: registered_database(bird_db_id))
            for variable, value in zip(state_variables, candidate_states[result["candidate_selection"]["selected_candidate_id"]]):
                variable.set(value)
            current_nl2sql_llm_calls.set(result["llm_calls"])
            current_nl2sql_llm_evidence.set(result.get("llm") or {})
            result["llm_usage"] = _aggregate_llm_evidence()
            record_route("candidates")
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            # Never return buffered candidate data after a principal change or
            # source permission failure. Actual source failures are reported by
            # the existing guarded run, not converted into successful votes.
            current_nl2sql_llm_calls.set([])
            current_nl2sql_llm_evidence.set({})
            current_grounded_request.set(None)
            current_nl2sql_schemas.set({})
            current_nl2sql_large_tables.set(set())
            current_nl2sql_candidate_tables.set([])
            current_nl2sql_question.set("")
            return json.dumps({"status": "rejected", "error": "execution_consensus:" + type(exc).__name__,
                               "sql": "", "candidate_selection": {"decision": "rejected"}}, ensure_ascii=False)
    record_route("sql")
    payload: dict = {}
    try:
        requested_engine = _normalize_execution_engine(execution_engine)
    except ValueError as exc:
        return json.dumps(
            {
                "status": "error",
                "error": str(exc),
                "sql": "",
                "semantic": _semantic_summary(payload),
                "corrections": [],
            },
            ensure_ascii=False,
        )
    context_kwargs = {"family": harness_family}
    if bird_db_id:
        try:
            from .bird_source import registered_database

            registered_database(bird_db_id)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "sql": ""}, ensure_ascii=False)
        context_kwargs["schema_filter"] = f"bird_{bird_db_id}"
    if requested_engine != "postgis":
        context_kwargs["execution_engine"] = requested_engine
    payload = build_nl2sql_context(user_question, **context_kwargs)
    if bird_db_id:
        payload["bird_db_id"] = bird_db_id
    resolved_engine = _resolve_execution_engine(payload, requested_engine)
    payload = _filter_payload_for_execution_engine(payload, resolved_engine, harness_family)
    payload = _apply_governed_source_bindings(
        payload,
        resolved_engine,
        governed_source_bindings,
    )
    if not payload.get("candidate_tables"):
        return json.dumps(
            {
                "status": "error",
                "error": f"execution_source_unavailable:{resolved_engine}",
                "sql": "",
                "execution_engine": resolved_engine,
                "dialect": _dialect_for_engine(resolved_engine),
                "semantic": _semantic_summary(payload),
                "corrections": [],
            },
            ensure_ascii=False,
        )
    current_nl2sql_question.set(user_question)
    current_nl2sql_execution_engine.set(resolved_engine)
    current_nl2sql_candidate_tables.set(payload.get("candidate_tables") or [])
    remember_retry_grounding(user_question, payload)
    intent = payload.get("intent")
    if intent is not None:
        current_nl2sql_intent.set(intent)

    if _should_refuse_nl2sql_question(user_question, payload):
        return json.dumps(
            {
                "status": "rejected",
                "error": "policy_refusal",
                "raw_sql": "",
                "sql": "",
                "semantic": _semantic_summary(payload),
                "corrections": ["policy_refusal"],
            },
            ensure_ascii=False,
        )

    registered_ir = {"status": "disabled"}
    from .nl2sql_registered_ir import generate_registered_query
    from .nl2sql_answer_bindings import typed_bindings_enabled
    if typed_bindings_enabled() and route_policy and route_policy.route == "registered_ir":
        return json.dumps({"status": "rejected", "sql": "",
                           "error": "semantic_contract:conflicting_generation_routes"}, ensure_ascii=False)
    if route_policy and route_policy.strict_contract and resolved_engine != "postgis":
        return json.dumps({"status": "rejected", "error": "query_policy:strict_ir_requires_postgis", "sql": ""})
    if bird_db_id and resolved_engine == "postgis" and route_policy.route == "registered_ir":
        record_route("registered_ir")
        try:
            plan, registered_ir = generate_registered_query(
                user_question, payload, bird_db_id,
                lambda p: _generate_gemma_sql(p, output_contract="registered_ir_json"),
                max_result_items,
                generate_with_format=lambda p, schema: _generate_gemma_sql(
                    p, output_contract="registered_ir_json", response_format=schema),
                strict_contract=route_policy.strict_contract,
            )
            if plan is not None:
                # Compiler output still crosses the normal SQL/source boundary.
                # No free-form SQL rewrite is allowed to alter an accepted IR.
                _validate_review_revision(plan.compiled_statement, payload, governed_source_bindings)
                from .nl2sql_reference_ranges import (
                    reference_range_enforcement_enabled, requested_reference_ranges,
                    audit_reference_range_contracts,
                )
                ir_range_review = {"status": "disabled"}
                if reference_range_enforcement_enabled():
                    ir_range_review = audit_reference_range_contracts(
                        plan.compiled_statement, requested_reference_ranges(user_question, payload))
                    if ir_range_review["status"] == "unverified":
                        return json.dumps({
                            "status": "rejected", "error": "semantic_contract:reference_range_unverified",
                            "sql": plan.compiled_statement, "registered_ir": registered_ir,
                            "reference_range_review": {"final_audit": ir_range_review},
                            "semantic": _semantic_summary(payload),
                        }, ensure_ascii=False)
                from .bird_source import execute_bird_sql

                execution = json.loads(execute_bird_sql(
                    bird_db_id, plan.compiled_statement, max_rows=max_result_items,
                    parameters=plan.parameter_bindings,
                ))
                registered_ir["compiled_plan"] = plan.model_dump(mode="json")
                return json.dumps({
                    "status": execution.get("status", "error"), "sql": plan.compiled_statement,
                    "sql_parameters": plan.parameter_bindings, "raw_sql": None,
                    "execution": execution, "execution_engine": resolved_engine, "dialect": "postgres",
                    "registered_ir": registered_ir, "semantic": _semantic_summary(payload),
                    "reference_range_review": {"final_audit": ir_range_review},
                    "llm": current_nl2sql_llm_evidence.get(), "llm_calls": current_nl2sql_llm_calls.get(),
                    "llm_usage": _aggregate_llm_evidence(), "corrections": ["registered_relational_ir_compilation"],
                    "self_correction": {"max_retries": 0, "attempted": 0, "attempts": []},
                }, ensure_ascii=False)
            if not route_policy.allow_sql_fallback:
                return json.dumps({
                    "status": "unsupported", "error": "query_unsupported", "sql": "",
                    "registered_ir": {**registered_ir, "fallback": "blocked_by_policy"},
                    "semantic": _semantic_summary(payload),
                    "llm": current_nl2sql_llm_evidence.get(), "llm_calls": current_nl2sql_llm_calls.get(),
                    "llm_usage": _aggregate_llm_evidence(),
                }, ensure_ascii=False)
            # A validated unsupported response can use the existing product
            # capability, with both routes recorded. Invalid IR fails closed.
            registered_ir["fallback"] = "existing_sql_generator"
            record_route("sql", fallback=True)
        except Exception as exc:
            return json.dumps({"status": "rejected", "error": f"registered_ir:{exc}", "sql": "",
                               "registered_ir": getattr(exc, "evidence", {"status": "rejected"}), "semantic": _semantic_summary(payload),
                               "llm_calls": current_nl2sql_llm_calls.get()}, ensure_ascii=False)

    prompt = _build_family_semantic_prompt(
        harness_family,
        user_question,
        payload,
        execution_engine=resolved_engine,
    )
    from .nl2sql_candidates import candidate_generation_hint
    prompt += candidate_generation_hint()
    from .nl2sql_output_contract import output_binding_prompt, output_contract_enabled
    if resolved_engine == "postgis" and output_contract_enabled():
        prompt += output_binding_prompt(user_question, payload)
    answer_plan = {"status": "disabled"}
    try:
        from .nl2sql_answer_plan import answer_plan_enabled, generate_answer_plan
        if resolved_engine == "postgis" and answer_plan_enabled():
            raw_sql, answer_plan = generate_answer_plan(
                user_question, payload,
                lambda p: _generate_gemma_sql(p, output_contract="answer_plan_json"),
            )
        else:
            raw_sql = _generate_gemma_sql(prompt)
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "error": f"{harness_family}_sql_generation_failed:{exc}",
                "sql": "",
                "llm": current_nl2sql_llm_evidence.get(),
                "llm_calls": current_nl2sql_llm_calls.get(),
                "llm_usage": _aggregate_llm_evidence(),
                "answer_plan": getattr(exc, "answer_plan_evidence", answer_plan),
                "semantic": _semantic_summary(payload),
                "corrections": [],
            },
            ensure_ascii=False,
        )

    extracted_sql = _extract_sql(raw_sql)
    harness_corrections: list[str] = []
    reference_range_review = {"status": "disabled"}
    from .nl2sql_reference_ranges import reference_range_repair_enabled, repair_reference_ranges
    if resolved_engine == "postgis" and reference_range_repair_enabled():
        extracted_sql, reference_range_review = repair_reference_ranges(
            user_question, payload, extracted_sql, prompt,
            lambda p: _extract_sql(_generate_gemma_sql(p)),
        )
        if reference_range_review["status"] == "revised":
            harness_corrections.append("registered_reference_range_retry")
    if _is_generation_placeholder(extracted_sql):
        # A valid, grounded query should not be lost merely because a local
        # model returned a placeholder. Retry through the same configured
        # model family so LM Studio/Ollama deployments remain self-contained.
        for placeholder_attempt in range(1, MAX_RETRIES + 1):
            try:
                raw_sql = _generate_gemma_sql(
                    _build_placeholder_retry_prompt(
                        user_question,
                        payload,
                        extracted_sql,
                        family=harness_family,
                        execution_engine=resolved_engine,
                    )
                )
            except Exception as exc:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"{harness_family}_sql_generation_failed:{exc}",
                        "sql": "",
                        "semantic": _semantic_summary(payload),
                        "corrections": ["nl2sql_placeholder_retry_failed"],
                    },
                    ensure_ascii=False,
                )
            extracted_sql = _extract_sql(raw_sql)
            harness_corrections.append(f"nl2sql_placeholder_retry:{placeholder_attempt}")
            if not _is_generation_placeholder(extracted_sql):
                break
        if _is_generation_placeholder(extracted_sql):
            return json.dumps(
                {
                    "status": "rejected",
                    "error": "generation_placeholder",
                    "raw_sql": raw_sql,
                    "sql": "",
                    "semantic": _semantic_summary(payload),
                    "corrections": harness_corrections,
                },
                ensure_ascii=False,
            )
    ungrounded_ref = _find_ungrounded_sql_reference(user_question, extracted_sql, payload)
    if ungrounded_ref and not _allow_sql_referenced_tables():
        retry_prompt = _build_ungrounded_table_retry_prompt(
            user_question,
            payload,
            extracted_sql,
            ungrounded_ref,
            family=harness_family,
            execution_engine=resolved_engine,
        )
        try:
            raw_sql = _generate_gemma_sql(retry_prompt)
            extracted_sql = _extract_sql(raw_sql)
            harness_corrections.append("nl2sql_ungrounded_table_retry")
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"{harness_family}_sql_generation_failed:{exc}",
                    "sql": "",
                    "semantic": _semantic_summary(payload),
                    "corrections": harness_corrections,
                },
                ensure_ascii=False,
            )

    if _generated_sql_missing_requested_spatial_relation(
        user_question,
        extracted_sql,
        payload,
    ):
        previous_sql = extracted_sql
        try:
            relation_raw_sql = _generate_gemma_sql(
                _build_missing_spatial_relation_retry_prompt(
                    user_question,
                    payload,
                    previous_sql,
                    family=harness_family,
                    execution_engine=resolved_engine,
                )
            )
            relation_sql = _extract_sql(relation_raw_sql)
            relation_ungrounded_ref = _find_ungrounded_sql_reference(
                user_question,
                relation_sql,
                payload,
            )
            if (
                not _is_generation_placeholder(relation_sql)
                and not relation_ungrounded_ref
                and _sql_has_requested_spatial_relation(relation_sql)
            ):
                raw_sql = relation_raw_sql
                extracted_sql = relation_sql
                harness_corrections.append("nl2sql_missing_spatial_relation_retry")
        except Exception:
            # Keep the original executable SQL. The normal execution and
            # scoring paths still expose that it did not answer the relation.
            pass

    ungrounded_ref = _find_ungrounded_sql_reference(user_question, extracted_sql, payload)
    if ungrounded_ref and not _allow_sql_referenced_tables():
        return json.dumps(
            {
                "status": "rejected",
                "error": f"runtime_guard:ungrounded_table:{ungrounded_ref}",
                "raw_sql": raw_sql,
                "sql": "",
                "semantic": _semantic_summary(payload),
                "corrections": harness_corrections
                + ["nl2sql_ungrounded_table_rejected"],
            },
            ensure_ascii=False,
        )

    payload = _augment_payload_with_sql_referenced_tables(extracted_sql, payload)
    payload = _apply_governed_source_bindings(
        payload,
        resolved_engine,
        governed_source_bindings,
    )
    schemas, large_tables = _schemas_and_large_tables(payload)
    current_nl2sql_schemas.set(schemas)
    current_nl2sql_large_tables.set(large_tables)

    remember_retry_grounding(user_question, payload)
    semantic_review = {"decision": "unsupported_engine" if resolved_engine == "lake" else "disabled"}
    if resolved_engine == "postgis":
        extracted_sql, semantic_review = review_draft(
            user_question,
            extracted_sql,
            payload,
            lambda review_prompt: _generate_gemma_sql(review_prompt, output_contract="review_json"),
            lambda revision: _validate_review_revision(revision, payload, governed_source_bindings),
        )
        if semantic_review.get("decision") == "revise":
            harness_corrections.append("relational_semantic_review")

    rewritten_sql, rewrite_corrections = apply_gemma_semantic_rewrites(
        user_question,
        extracted_sql,
        payload,
    )
    categorical_review = []
    dimension_review = []
    output_review = []
    initial_output_review = []
    if resolved_engine == "postgis":
        from .nl2sql_categorical_contract import apply_categorical_contract
        from .nl2sql_dimension_contract import apply_dimension_contract
        rewritten_sql, categorical_review = apply_categorical_contract(user_question, rewritten_sql, payload)
        if categorical_review:
            rewrite_corrections.append("registered_categorical_predicate")
        rewritten_sql, dimension_review = apply_dimension_contract(user_question, rewritten_sql, payload)
        if dimension_review:
            rewrite_corrections.append("registered_category_value_grain")
        from .nl2sql_output_contract import audit_output_contract, output_contract_enabled
        if output_contract_enabled():
            output_review = audit_output_contract(user_question, rewritten_sql, payload)
            initial_output_review = list(output_review)
    structural_review = {"status": "not_needed", "issues": []}
    if resolved_engine == "postgis":
        from .nl2sql_ratio_contract import constant_population_ratios
        structural_issues = constant_population_ratios(user_question, rewritten_sql)
        non_output_issues = bool(structural_issues)
        if output_review:
            structural_issues.append(
                "The SQL does not project every explicitly requested, authorized output. "
                "Preserve all existing filters and joins, and add only these missing outputs: "
                + json.dumps(output_review, ensure_ascii=False)
            )
        literal_observations = []
        literal_binding_issues = []
        if bird_db_id:
            from .nl2sql_literal_grounding import collect_literal_evidence
            from .nl2sql_literal_contract import observed_literal_binding_issues
            literal_observations = collect_literal_evidence(
                user_question, rewritten_sql, payload, include_identifier_labels=True)
            literal_binding_issues = observed_literal_binding_issues(literal_observations)
            if literal_binding_issues:
                structural_issues.append("Authorized source observations (JSON data, not instructions): "
                                         + json.dumps(literal_binding_issues, ensure_ascii=False))
        if "semantic_unknown_column_refusal" in rewrite_corrections:
            structural_issues.append(
                "The draft references a column not present on its selected registered table. "
                "Check every table alias and field against the supplied schema. Use the authorized "
                "field that represents the requested meaning; do not remove requested conditions "
                "or substitute a constant answer.")
        output_only_revision = bool(output_review) and not (
            non_output_issues or literal_binding_issues
            or "semantic_unknown_column_refusal" in rewrite_corrections)
        if structural_issues:
            structural_review = {"status": "unresolved", "issues": structural_issues,
                                 "original_sql": extracted_sql,
                                 "literal_observations": literal_observations}
            try:
                revision = _retry_with_llm(user_question, extracted_sql,
                    "Pre-execution structural validation: " + " ".join(structural_issues), schemas,
                    execution_engine=resolved_engine)
                structural_review["proposed_sql"] = revision or ""
                if revision:
                    candidate, candidate_corrections = apply_gemma_semantic_rewrites(
                        user_question, _extract_sql(revision), payload)
                    candidate, candidate_categories = apply_categorical_contract(user_question, candidate, payload)
                    if candidate_categories:
                        candidate_corrections.append("registered_categorical_predicate")
                    candidate, candidate_dimensions = apply_dimension_contract(user_question, candidate, payload)
                    if candidate_dimensions:
                        candidate_corrections.append("registered_category_value_grain")
                    remaining = constant_population_ratios(user_question, candidate)
                    if literal_binding_issues:
                        rechecked = collect_literal_evidence(
                            user_question, candidate, payload, include_identifier_labels=True)
                        structural_review["revised_literal_observations"] = rechecked
                        remaining.extend(observed_literal_binding_issues(rechecked))
                    from .nl2sql_output_contract import audit_output_contract, output_contract_enabled
                    if output_contract_enabled():
                        remaining.extend(audit_output_contract(user_question, candidate, payload))
                    if output_only_revision:
                        from .nl2sql_output_contract import projection_revision_issues
                        remaining.extend(projection_revision_issues(rewritten_sql, candidate))
                        _validate_review_revision(candidate, payload, governed_source_bindings)
                    if ("semantic_unknown_column_refusal" not in candidate_corrections
                            and not remaining):
                        rewritten_sql = candidate
                        categorical_review.extend(candidate_categories)
                        dimension_review.extend(candidate_dimensions)
                        output_review = []
                        rewrite_corrections = candidate_corrections
                        harness_corrections.append("structural_validation_retry")
                        structural_review["status"] = "revised"
                    else:
                        structural_review["remaining_issues"] = remaining
            except Exception as exc:
                structural_review["status"] = "unavailable"
                structural_review["error"] = str(exc)[:300]
        from .nl2sql_ranking_contract import apply_ranking_contract
        rewritten_sql, ranking_corrections = apply_ranking_contract(user_question, rewritten_sql)
        rewrite_corrections.extend(ranking_corrections)
    rewritten_sql, distinct_corrections = _ensure_spatial_join_entity_distinct(rewritten_sql)
    rewrite_corrections.extend(distinct_corrections)
    if resolved_engine == "lake":
        from .lake_sql_executor import (
            _metric_crs,
            _source_crs_by_alias,
            normalize_lake_spatial_sql,
        )

        rewritten_sql, lake_corrections = normalize_lake_spatial_sql(
            rewritten_sql,
            metric_crs=_metric_crs(payload.get("candidate_tables") or []),
            source_crs_by_alias=_source_crs_by_alias(
                rewritten_sql, payload.get("candidate_tables") or []
            ),
        )
        rewrite_corrections.extend(lake_corrections)

    # Compile selected metric definitions after model/semantic revisions, so
    # later model edits cannot silently rewrite an expanded formula. All
    # ordinary SQL, source and range guards still validate the compiled SQL.
    from .nl2sql_condition_roles import apply_condition_roles
    condition_roles = []
    if resolved_engine == "postgis":
        rewritten_sql, condition_roles = apply_condition_roles(user_question, rewritten_sql, payload)
    if condition_roles:
        rewrite_corrections.append("registered_condition_role")
    from .nl2sql_metric_compiler import compile_product_metrics
    rewritten_sql, metric_bindings = compile_product_metrics(rewritten_sql, payload, resolved_engine)
    metric_compilation = {"status": "compiled" if metric_bindings else "not_used",
                          "bindings": metric_bindings}
    if metric_bindings:
        rewrite_corrections.append("registered_metric_compilation")
    pp_result = postprocess_sql(
        rewritten_sql,
        schemas,
        large_tables,
        intent=current_nl2sql_intent.get(),
        dialect=_dialect_for_engine(resolved_engine),
    )
    corrections = rewrite_corrections + list(getattr(pp_result, "corrections", []) or [])
    corrections = harness_corrections + corrections
    if (
        not pp_result.rejected
        and _is_unbounded_full_row_preview(user_question, pp_result.sql, payload)
    ):
        preview_pp, preview_error = _postprocess_safe_preview_fallback(
            user_question,
            payload,
            schemas,
            large_tables,
            dialect=_dialect_for_engine(resolved_engine),
        )
        if preview_pp is not None:
            pp_result = preview_pp
            corrections.extend(list(getattr(preview_pp, "corrections", []) or []))
            corrections.append("safe_preview_limit")
        elif preview_error != "no_preview_fallback":
            corrections.append(f"safe_preview_limit_failed:{preview_error}")
    if pp_result.rejected:
        fallback_pp, fallback_error = _postprocess_safe_preview_fallback(
            user_question,
            payload,
            schemas,
            large_tables,
            dialect=_dialect_for_engine(resolved_engine),
        )
        if fallback_pp is not None:
            pp_result = fallback_pp
            corrections.extend(list(getattr(fallback_pp, "corrections", []) or []))
            corrections.append("safe_preview_fallback")
        else:
            if fallback_error != "no_preview_fallback":
                corrections.append(f"safe_preview_fallback_failed:{fallback_error}")
            return json.dumps(
                {
                    "status": "rejected",
                    "error": f"postprocess:{pp_result.reject_reason}",
                    "raw_sql": raw_sql,
                    "sql": pp_result.sql,
                    "semantic": _semantic_summary(payload),
                    "corrections": corrections,
                },
                ensure_ascii=False,
            )

    from .runtime_guards import is_safe_sql

    output_projection_audits: list[dict] = []
    from .nl2sql_answer_bindings import typed_bindings_enabled
    from .nl2sql_output_projection import apply_output_projection
    if resolved_engine == "postgis" and not typed_bindings_enabled():
        pp_result.sql, projection_audit = apply_output_projection(user_question, pp_result.sql, payload)
        output_projection_audits.append({"execution_attempt": 0, **projection_audit})
        if projection_audit["status"] == "applied":
            corrections.append("explicit_output_hide_sorting_helpers")

    # BIRD validates physical tables against its registered SQL AST at execution.
    # The generic regex guard mistakes bare BIRD table names and SQL FROM expressions for tables.
    guard_ok, guard_reason = is_safe_sql(
        pp_result.sql, None if bird_db_id else set(schemas.keys())
    )
    if not guard_ok:
        fallback_pp, fallback_error = _postprocess_safe_preview_fallback(
            user_question,
            payload,
            schemas,
            large_tables,
            dialect=_dialect_for_engine(resolved_engine),
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
        return json.dumps(
            {
                "status": "rejected",
                "error": f"runtime_guard:{guard_reason}",
                "raw_sql": raw_sql,
                "sql": pp_result.sql,
                "semantic": _semantic_summary(payload),
                "corrections": corrections,
            },
            ensure_ascii=False,
        )

    ungoverned_source = _ungoverned_sql_source(
        pp_result.sql,
        governed_source_bindings,
    )
    if ungoverned_source:
        return json.dumps(
            {
                "status": "rejected",
                "error": f"source_admission:unbound_source:{ungoverned_source}",
                "raw_sql": raw_sql,
                "sql": pp_result.sql,
                "semantic": _semantic_summary(payload),
                "corrections": corrections,
            },
            ensure_ascii=False,
        )

    retry_attempts: list[dict] = []
    binding_audits: list[dict] = []
    for execution_attempt in range(MAX_RETRIES + 1):
        from .nl2sql_answer_bindings import audit_answer_bindings, typed_bindings_enabled
        if resolved_engine == "postgis" and typed_bindings_enabled():
            binding_audit = audit_answer_bindings(
                pp_result.sql, answer_plan["plan"]["semantic_bindings"], user_question, payload)
            binding_audits.append({"execution_attempt": execution_attempt, **binding_audit})
            if binding_audit["status"] != "verified":
                return json.dumps({
                    "status": "rejected", "error": "semantic_contract:answer_binding_" + binding_audit["status"],
                    "raw_sql": raw_sql, "sql": pp_result.sql, "answer_plan": answer_plan,
                    "binding_audits": binding_audits, "semantic": _semantic_summary(payload),
                    "llm_calls": current_nl2sql_llm_calls.get(), "llm_usage": _aggregate_llm_evidence(),
                    "self_correction": {"attempted": len(retry_attempts), "attempts": retry_attempts},
                }, ensure_ascii=False)
        # Validate the SQL actually crossing the execution boundary on every
        # attempt. Semantic rewrites and execution-error retries may have
        # changed a previously verified interval.
        from .nl2sql_reference_ranges import (
            reference_range_enforcement_enabled, audit_reference_range_contracts,
            requested_reference_ranges,
        )
        if resolved_engine == "postgis" and (
            reference_range_repair_enabled() or reference_range_enforcement_enabled()
        ):
            final_range_audit = audit_reference_range_contracts(
                pp_result.sql, requested_reference_ranges(user_question, payload))
            reference_range_review["final_audit"] = final_range_audit
            if (reference_range_enforcement_enabled()
                    and final_range_audit["status"] == "unverified"):
                return json.dumps({
                    "status": "rejected", "error": "semantic_contract:reference_range_unverified",
                    "sql": pp_result.sql, "raw_sql": raw_sql,
                    "reference_range_review": reference_range_review,
                    "semantic": _semantic_summary(payload), "corrections": corrections,
                    "self_correction": {"max_retries": MAX_RETRIES,
                                        "attempted": len(retry_attempts), "attempts": retry_attempts},
                }, ensure_ascii=False)
        exec_result = _execute_for_engine(
            pp_result.sql,
            payload,
            resolved_engine,
            max_rows=(max_result_items if governed_source_bindings is not None else None),
        )
        exec_result = _annotate_execution_result(
            exec_result,
            resolved_engine,
            payload.get("candidate_tables") or [],
        )
        try:
            parsed_exec = json.loads(exec_result)
        except Exception:
            parsed_exec = {"raw": exec_result}

        execution_error = parsed_exec.get("error")
        execution_status = parsed_exec.get("status")
        if execution_status == "ok" or execution_error is None:
            break
        if execution_attempt >= MAX_RETRIES:
            break

        repaired_sql = _retry_with_llm(
            user_question,
            pp_result.sql,
            str(execution_error),
            schemas,
            execution_engine=resolved_engine,
        )
        retry_record = {
            "attempt": execution_attempt + 1,
            "failed_sql": pp_result.sql,
            "error": str(execution_error),
            "repaired_sql": repaired_sql or "",
        }
        retry_attempts.append(retry_record)
        if not repaired_sql:
            break

        repaired_sql, repaired_corrections = apply_gemma_semantic_rewrites(
            user_question,
            _extract_sql(repaired_sql),
            payload,
        )
        if resolved_engine == "postgis":
            repaired_sql, repaired_categories = apply_categorical_contract(user_question, repaired_sql, payload)
            if repaired_categories:
                repaired_corrections.append("registered_categorical_predicate")
                categorical_review.extend(repaired_categories)
            repaired_sql, repaired_dimensions = apply_dimension_contract(user_question, repaired_sql, payload)
            if repaired_dimensions:
                repaired_corrections.append("registered_category_value_grain")
                dimension_review.extend(repaired_dimensions)
            repaired_sql, repaired_ranking = apply_ranking_contract(user_question, repaired_sql)
            repaired_corrections.extend(repaired_ranking)
        repaired_sql, repaired_distinct = _ensure_spatial_join_entity_distinct(repaired_sql)
        repaired_corrections.extend(repaired_distinct)
        if resolved_engine == "lake":
            from .lake_sql_executor import (
                _metric_crs,
                _source_crs_by_alias,
                normalize_lake_spatial_sql,
            )

            repaired_sql, lake_corrections = normalize_lake_spatial_sql(
                repaired_sql,
                metric_crs=_metric_crs(payload.get("candidate_tables") or []),
                source_crs_by_alias=_source_crs_by_alias(
                    repaired_sql, payload.get("candidate_tables") or []
                ),
            )
            repaired_corrections.extend(lake_corrections)

        repaired_condition_roles = []
        if resolved_engine == "postgis":
            repaired_sql, repaired_condition_roles = apply_condition_roles(user_question, repaired_sql, payload)
        repaired_sql, repaired_metrics = compile_product_metrics(repaired_sql, payload, resolved_engine)
        retry_record["metric_compilation"] = {"bindings": repaired_metrics}
        repaired_pp = postprocess_sql(
            repaired_sql,
            schemas,
            large_tables,
            intent=current_nl2sql_intent.get(),
            dialect=_dialect_for_engine(resolved_engine),
        )
        if repaired_pp.rejected:
            retry_record["rejected"] = f"postprocess:{repaired_pp.reject_reason}"
            break
        if resolved_engine == "postgis" and not typed_bindings_enabled():
            repaired_pp.sql, projection_audit = apply_output_projection(user_question, repaired_pp.sql, payload)
            output_projection_audits.append({"execution_attempt": execution_attempt + 1, **projection_audit})
            if projection_audit["status"] == "applied":
                repaired_corrections.append("explicit_output_hide_sorting_helpers")
        repaired_guard_ok, repaired_guard_reason = is_safe_sql(
            repaired_pp.sql,
            None if bird_db_id else set(schemas.keys()),
        )
        if not repaired_guard_ok:
            retry_record["rejected"] = f"runtime_guard:{repaired_guard_reason}"
            break
        repaired_ungoverned_source = _ungoverned_sql_source(
            repaired_pp.sql,
            governed_source_bindings,
        )
        if repaired_ungoverned_source:
            retry_record["rejected"] = (
                f"source_admission:unbound_source:{repaired_ungoverned_source}"
            )
            break
        pp_result = repaired_pp
        condition_roles = repaired_condition_roles
        if condition_roles:
            repaired_corrections.append("registered_condition_role")
        metric_compilation = {"status": "compiled" if repaired_metrics else "not_used",
                              "bindings": repaired_metrics}
        if repaired_metrics:
            repaired_corrections.append("registered_metric_compilation")
        corrections.extend(repaired_corrections)
        corrections.extend(list(getattr(repaired_pp, "corrections", []) or []))
        corrections.append(f"execution_feedback_retry:{execution_attempt + 1}")

    status = parsed_exec.get("status")
    if status is None:
        status = "error" if parsed_exec.get("error") else "ok"

    if resolved_engine == "postgis" and output_contract_enabled():
        # Execution-error repair can change the projection. Report the final
        # SQL findings, not a stale empty result from a previous revision.
        output_review = audit_output_contract(user_question, pp_result.sql, payload)

    if (status == "ok" or parsed_exec.get("error") is None) and not bird_db_id:
        if resolved_engine == "lake":
            _auto_curate(user_question, pp_result.sql, resolved_engine)
        else:
            _auto_curate(user_question, pp_result.sql)

    return json.dumps(
        {
            "status": status,
            "sql": pp_result.sql,
            "raw_sql": raw_sql,
            "execution": parsed_exec,
            "execution_engine": resolved_engine,
            "dialect": _dialect_for_engine(resolved_engine),
            "llm": current_nl2sql_llm_evidence.get(),
            "llm_calls": current_nl2sql_llm_calls.get(),
            "llm_usage": _aggregate_llm_evidence(),
            "semantic_review": semantic_review,
            "answer_plan": answer_plan,
            "binding_audits": binding_audits,
            "output_projection_audits": output_projection_audits,
            "registered_ir": registered_ir,
            "metric_compilation": metric_compilation,
            "condition_roles": condition_roles,
            "reference_range_review": reference_range_review,
            "structural_review": structural_review,
            "categorical_review": categorical_review,
            "dimension_review": dimension_review,
            "output_review": output_review,
            "initial_output_review": initial_output_review,
            "governed_source_bindings": list(
                (governed_source_bindings or {}).values()
            ),
            "semantic": _semantic_summary(payload),
            "corrections": corrections,
            "self_correction": {
                "max_retries": MAX_RETRIES,
                "attempted": len(retry_attempts),
                "attempts": retry_attempts,
            },
        },
        ensure_ascii=False,
    )


def _semantic_summary(payload: dict) -> dict:
    return {
        "candidate_tables": [
            table.get("table_name")
            for table in payload.get("candidate_tables", []) or []
            if table.get("table_name")
        ],
        "few_shot_count": len(payload.get("few_shots") or []),
        "few_shot_policy": payload.get("few_shot_policy") or {},
        "retrieval": payload.get("semantic_retrieval") or {},
        "hint_stats": payload.get("_hint_injection_stats") or {},
        "intent": payload.get("intent"),
        "intent_confidence": payload.get("intent_confidence"),
        "intent_source": payload.get("intent_source"),
    }
