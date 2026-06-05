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
from .semantic_layer import describe_table_semantic
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
            continue
        schema = describe_table_semantic(table_name)
        if schema.get("status") != "success" and "." in table_name:
            schema = describe_table_semantic(table_name.split(".")[-1])
            table_name = table_name.split(".")[-1]
        if schema.get("status") != "success":
            continue
        candidate_tables.append(_candidate_from_described_schema(table_name, schema))
        existing.add(table_name)
        existing.add(table_name.split(".")[-1])
        added += 1
    if added:
        stats = payload.setdefault("_hint_injection_stats", {})
        stats["candidate_tables"] = len(candidate_tables)
        stats["sql_referenced_tables_added"] = added
    return payload


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


def _build_ungrounded_table_retry_prompt(question: str, payload: dict, sql: str, table_ref: str) -> str:
    allowed = sorted(
        str(t.get("table_name") or "")
        for t in payload.get("candidate_tables", []) or []
        if t.get("table_name")
    )
    return (
        _build_gemma_semantic_prompt(question, payload)
        + "\n\nHarness correction:\n"
        + f"- Previous SQL referenced `{table_ref}`, which is not grounded by the candidate schema.\n"
        + f"- Use only these candidate tables: {', '.join(allowed) or '(none)'}.\n"
        + "- If the question cannot be answered from those candidate tables, output SELECT 1.\n"
        + "- Output SQL only.\n\n"
        + f"Previous SQL:\n{sql}\n"
    )


def _extract_sql(text: str) -> str:
    """Extract the most recent complete SELECT/WITH statement from model text."""
    sql = _strip_fences(text)
    sql = re.sub(r"^\s*(?:sql\s*:|SQL\s*:)", "", sql).strip()
    matches = list(re.finditer(r"\b(SELECT|WITH)\b", sql, flags=re.IGNORECASE))
    if not matches:
        return sql or "SELECT 1"
    candidates: list[str] = []
    for match in matches:
        candidate = sql[match.start():].strip()
        if ";" in candidate:
            candidate = candidate.split(";", 1)[0].strip()
        if candidate:
            candidates.append(candidate)
    for candidate in reversed(candidates):
        if candidate.upper().startswith("WITH") or re.search(r"\bFROM\b", candidate, flags=re.IGNORECASE):
            return candidate
    return candidates[-1] if candidates else "SELECT 1"


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


def _build_gemma_semantic_prompt(question: str, payload: dict) -> str:
    """Build a Gemma/Ollama prompt for one-shot semantic SQL generation."""
    grounding = payload.get("grounding_prompt") or ""
    stats = payload.get("_hint_injection_stats") or {}
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

User question:
{question}

Semantic candidate context:
{grounding}

Semantic injection stats:
{json.dumps(stats, ensure_ascii=False)}
"""


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

    if _has_missing_explicit_column_request(question, payload):
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
    """Run Gemma4/Ollama NL2Semantic2SQL as one high-level tool call.

    This is the production path for Gemma4 because exposing the low-level
    semantic/database tools to the model can trap it in repeated tool calls.
    The Python side owns the full workflow: semantic grounding, SQL generation,
    deterministic semantic fixes, guards, execution, and structured return.
    """
    payload = build_nl2sql_context(user_question, family="gemma")
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

    prompt = _build_gemma_semantic_prompt(user_question, payload)
    try:
        raw_sql = _generate_gemma_sql(prompt)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"gemma_sql_generation_failed:{exc}",
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
        )
        try:
            raw_sql = _generate_gemma_sql(retry_prompt)
            extracted_sql = _extract_sql(raw_sql)
            harness_corrections.append("gemma_ungrounded_table_retry")
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"gemma_sql_generation_failed:{exc}",
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
            "corrections": harness_corrections + ["gemma_ungrounded_table_rejected"],
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
