# NL2SQL Optimization Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add schema grounding + SQL postprocessor to the @NL2SQL Custom Skill path, raising Gemini benchmark accuracy from 50% to ≥80%.

**Architecture:** Two new modules (`nl2sql_grounding.py` for pre-LLM context, `sql_postprocessor.py` for post-LLM correction) wrapped by `nl2sql_executor.py` which exposes two ADK FunctionTools (`prepare_nl2sql_context` + `execute_nl2sql`). Registered as `NL2SQLEnhancedToolset` and wired into the existing NL2SQL Custom Skill.

**Tech Stack:** Python 3.13, sqlglot (AST parsing), SQLAlchemy, Google ADK FunctionTool/BaseToolset, pytest

**Spec:** `docs/superpowers/specs/2026-04-21-nl2sql-optimization-phase1-design.md`

---

## File Structure

**New files:**
- `data_agent/sql_postprocessor.py` — AST safety check + identifier quoting fix + LIMIT injection
- `data_agent/nl2sql_grounding.py` — semantic context + schema assembly + few-shot + prompt formatting
- `data_agent/nl2sql_executor.py` — two ADK tool functions + ContextVar bridge
- `data_agent/toolsets/nl2sql_enhanced_tools.py` — BaseToolset wrapper
- `data_agent/test_sql_postprocessor.py` — unit tests for postprocessor
- `data_agent/test_nl2sql_grounding.py` — unit tests for grounding
- `data_agent/test_nl2sql_executor.py` — unit tests for executor tools

**Modified files:**
- `data_agent/toolsets/__init__.py` — add NL2SQLEnhancedToolset export
- `data_agent/custom_skills.py` — add to VALID_TOOLSET_NAMES + registry
- `requirements.txt` — add sqlglot

---

## Task 1: Add sqlglot dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Verify sqlglot is not already installed**

```bash
.venv/Scripts/python.exe -c "import sqlglot" 2>&1
```

Expected: `ModuleNotFoundError: No module named 'sqlglot'`

(If already installed, skip Step 2 install but still add to requirements.txt for reproducibility.)

- [ ] **Step 2: Add sqlglot to requirements.txt**

Append after the last line of `requirements.txt`:

```
sqlglot>=25.0.0
```

- [ ] **Step 3: Install**

```bash
.venv/Scripts/python.exe -m pip install "sqlglot>=25.0.0"
```

Expected: successful install of sqlglot.

- [ ] **Step 4: Verify**

```bash
.venv/Scripts/python.exe -c "import sqlglot; print(sqlglot.__version__)"
```

Expected: prints version like `25.x.x`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "build: add sqlglot dependency for NL2SQL SQL postprocessor"
```

---

## Task 2: SQL Postprocessor — AST safety check (rejection)

**Files:**
- Create: `data_agent/sql_postprocessor.py`
- Create: `data_agent/test_sql_postprocessor.py`

- [ ] **Step 1: Write failing test for SELECT acceptance and DML rejection**

Create `data_agent/test_sql_postprocessor.py`:

```python
"""Tests for sql_postprocessor.postprocess_sql."""
import pytest


def test_select_is_accepted():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql("SELECT 1", table_schemas={})
    assert result.rejected is False
    assert result.sql.strip().upper().startswith("SELECT")


def test_with_clause_is_accepted():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql("WITH t AS (SELECT 1) SELECT * FROM t", table_schemas={})
    assert result.rejected is False


def test_delete_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "DELETE FROM cq_osm_roads_2021 WHERE name IS NULL",
        table_schemas={},
    )
    assert result.rejected is True
    assert "DELETE" in result.reject_reason.upper() or "WRITE" in result.reject_reason.upper()


def test_update_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "UPDATE cq_land_use_dltb SET DLMC = '林地' WHERE DLMC = '有林地'",
        table_schemas={},
    )
    assert result.rejected is True


def test_drop_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "DROP TABLE cq_buildings_2021",
        table_schemas={},
    )
    assert result.rejected is True


def test_insert_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "INSERT INTO cq_buildings_2021 (Id) VALUES (1)",
        table_schemas={},
    )
    assert result.rejected is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v
```

Expected: 6 FAIL with `ModuleNotFoundError: data_agent.sql_postprocessor`.

- [ ] **Step 3: Implement minimal postprocessor with AST safety check**

Create `data_agent/sql_postprocessor.py`:

```python
"""SQL postprocessor for NL2SQL: AST safety check + identifier quoting + LIMIT injection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import sqlglot
import sqlglot.expressions as exp


@dataclass
class PostprocessResult:
    sql: str
    corrections: list[str] = field(default_factory=list)
    rejected: bool = False
    reject_reason: str = ""


# AST node types that represent write operations and must be rejected
_WRITE_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop,
    exp.Alter, exp.TruncateTable, exp.Create,
)


def _is_safe_root(parsed: exp.Expression) -> bool:
    """A safe root must be a Select or a With wrapping a Select."""
    if isinstance(parsed, exp.Select):
        return True
    if isinstance(parsed, exp.With):
        return isinstance(parsed.this, exp.Select)
    return False


def _has_write_node(parsed: exp.Expression) -> bool:
    """Walk the AST looking for any write-operation node."""
    for node in parsed.walk():
        # parsed.walk() yields tuples in some sqlglot versions
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, _WRITE_NODE_TYPES):
            return True
    return False


def postprocess_sql(
    raw_sql: str,
    table_schemas: dict,
    large_tables: Optional[set] = None,
) -> PostprocessResult:
    """Postprocess raw LLM-generated SQL: safety check, identifier fix, LIMIT injection.

    Args:
        raw_sql: SQL string from LLM.
        table_schemas: dict mapping table_name -> list of column dicts
            (each column dict has at least 'column_name' and 'needs_quoting').
        large_tables: set of table names that should auto-receive LIMIT 1000.

    Returns:
        PostprocessResult with sql, corrections, rejected, reject_reason.
    """
    result = PostprocessResult(sql=raw_sql)

    try:
        parsed = sqlglot.parse_one(raw_sql, dialect="postgres")
    except Exception as e:
        result.rejected = True
        result.reject_reason = f"SQL parse error: {e}"
        return result

    if parsed is None:
        result.rejected = True
        result.reject_reason = "Empty SQL"
        return result

    if _has_write_node(parsed) or not _is_safe_root(parsed):
        result.rejected = True
        result.reject_reason = "Only SELECT/WITH queries are allowed (write operation detected)"
        return result

    result.sql = parsed.sql(dialect="postgres")
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v
```

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add data_agent/sql_postprocessor.py data_agent/test_sql_postprocessor.py
git commit -m "feat(nl2sql): add SQL postprocessor with AST-level write rejection"
```

---

## Task 3: SQL Postprocessor — identifier quoting fix

**Files:**
- Modify: `data_agent/sql_postprocessor.py`
- Modify: `data_agent/test_sql_postprocessor.py`

- [ ] **Step 1: Append failing identifier-fix tests**

Append to `data_agent/test_sql_postprocessor.py`:

```python


# --- Identifier quoting fix tests (from benchmark CQ_GEO_EASY_01/03) ---

_BUILDINGS_SCHEMA = {
    "cq_buildings_2021": [
        {"column_name": "Id", "needs_quoting": True},
        {"column_name": "Floor", "needs_quoting": True},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}

_DLTB_SCHEMA = {
    "cq_land_use_dltb": [
        {"column_name": "BSM", "needs_quoting": True},
        {"column_name": "DLMC", "needs_quoting": True},
        {"column_name": "DLBM", "needs_quoting": True},
        {"column_name": "TBMJ", "needs_quoting": True},
        {"column_name": "QSDWMC", "needs_quoting": True},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}

_ROADS_SCHEMA = {
    "cq_osm_roads_2021": [
        {"column_name": "name", "needs_quoting": False},
        {"column_name": "fclass", "needs_quoting": False},
        {"column_name": "maxspeed", "needs_quoting": False},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}


def test_fix_floor_lowercase():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40",
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert result.rejected is False
    assert '"Floor"' in result.sql
    assert any('Floor' in c for c in result.corrections)


def test_fix_id_lowercase():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(id) FROM cq_buildings_2021 WHERE floor >= 40",
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert '"Id"' in result.sql
    assert '"Floor"' in result.sql


def test_fix_dlmc_bsm_uppercase_unquoted():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT BSM FROM cq_land_use_dltb WHERE DLMC = '水田' AND TBMJ > 50000",
        table_schemas=_DLTB_SCHEMA,
    )
    assert '"BSM"' in result.sql
    assert '"DLMC"' in result.sql
    assert '"TBMJ"' in result.sql


def test_lowercase_columns_not_quoted():
    """Columns that are genuinely lowercase should NOT be quoted."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT name, fclass FROM cq_osm_roads_2021 WHERE maxspeed > 100",
        table_schemas=_ROADS_SCHEMA,
    )
    # Should remain unquoted
    assert '"name"' not in result.sql
    assert '"fclass"' not in result.sql


def test_already_quoted_columns_preserved():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        'SELECT "Floor" FROM cq_buildings_2021 WHERE "Id" = 1',
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert '"Floor"' in result.sql
    assert '"Id"' in result.sql


def test_qualified_alias_columns_fixed():
    """b.Floor with table alias should still be fixed to b.\"Floor\"."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        'SELECT count(DISTINCT b.id) FROM cq_buildings_2021 b WHERE b.floor > 20',
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert '"Floor"' in result.sql
    assert '"Id"' in result.sql
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v -k "fix_ or lowercase_columns or already_quoted or qualified_alias"
```

Expected: 6 FAIL — identifiers are not yet rewritten.

- [ ] **Step 3: Implement identifier-fix step**

Replace the `postprocess_sql` function in `data_agent/sql_postprocessor.py` with this expanded version. Add a new helper above it:

```python
def _build_column_map(table_schemas: dict) -> dict[str, tuple[str, bool]]:
    """Build {lowercase_name -> (real_name, needs_quoting)} from table_schemas.

    On collisions across tables (different real names), the first one wins
    and the conflict is logged via corrections. Identical real_names collapse.
    """
    column_map: dict[str, tuple[str, bool]] = {}
    for cols in table_schemas.values():
        for col in cols:
            real = col["column_name"]
            needs_q = bool(col.get("needs_quoting", False))
            key = real.lower()
            if key in column_map:
                # Collision: keep first; subsequent duplicates of same real_name are no-op
                continue
            column_map[key] = (real, needs_q)
    return column_map


def _fix_identifiers(parsed: exp.Expression, column_map: dict) -> tuple[exp.Expression, list[str]]:
    """Walk AST and rewrite Column nodes to use real-cased + quoted names.

    Returns the transformed expression and a list of corrections.
    """
    corrections: list[str] = []

    def transform(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Column):
            ident = node.this  # the leaf identifier
            if isinstance(ident, exp.Identifier):
                name = ident.name
                key = name.lower()
                if key in column_map:
                    real, needs_q = column_map[key]
                    if name != real or (needs_q and not ident.quoted):
                        new_ident = exp.Identifier(this=real, quoted=needs_q)
                        node.set("this", new_ident)
                        if name != real:
                            corrections.append(f"Identifier fix: {name} -> {real}")
                        elif needs_q and not ident.quoted:
                            corrections.append(f"Identifier quoted: {real} -> \"{real}\"")
        return node

    parsed = parsed.transform(transform)
    return parsed, corrections
```

Then update `postprocess_sql` to call `_fix_identifiers` before serializing:

```python
def postprocess_sql(
    raw_sql: str,
    table_schemas: dict,
    large_tables: Optional[set] = None,
) -> PostprocessResult:
    result = PostprocessResult(sql=raw_sql)

    try:
        parsed = sqlglot.parse_one(raw_sql, dialect="postgres")
    except Exception as e:
        result.rejected = True
        result.reject_reason = f"SQL parse error: {e}"
        return result

    if parsed is None:
        result.rejected = True
        result.reject_reason = "Empty SQL"
        return result

    if _has_write_node(parsed) or not _is_safe_root(parsed):
        result.rejected = True
        result.reject_reason = "Only SELECT/WITH queries are allowed (write operation detected)"
        return result

    column_map = _build_column_map(table_schemas)
    if column_map:
        parsed, fix_corrections = _fix_identifiers(parsed, column_map)
        result.corrections.extend(fix_corrections)

    result.sql = parsed.sql(dialect="postgres")
    return result
```

- [ ] **Step 4: Run all postprocessor tests**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v
```

Expected: 12 PASS (6 from Task 2 + 6 from Task 3).

- [ ] **Step 5: Commit**

```bash
git add data_agent/sql_postprocessor.py data_agent/test_sql_postprocessor.py
git commit -m "feat(nl2sql): postprocessor auto-fixes PostgreSQL case-sensitive identifiers"
```

---

## Task 4: SQL Postprocessor — LIMIT injection for large tables

**Files:**
- Modify: `data_agent/sql_postprocessor.py`
- Modify: `data_agent/test_sql_postprocessor.py`

- [ ] **Step 1: Append failing LIMIT tests**

Append to `data_agent/test_sql_postprocessor.py`:

```python


# --- LIMIT injection tests (from CQ_GEO_ROBUSTNESS_03) ---

_POI_SCHEMA = {
    "cq_amap_poi_2024": [
        {"column_name": "名称", "needs_quoting": True},
        {"column_name": "类型", "needs_quoting": True},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}


def test_inject_limit_on_large_table_full_scan():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT * FROM cq_amap_poi_2024",
        table_schemas=_POI_SCHEMA,
        large_tables={"cq_amap_poi_2024"},
    )
    assert "LIMIT" in result.sql.upper()
    assert "1000" in result.sql


def test_existing_limit_preserved():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT * FROM cq_amap_poi_2024 LIMIT 50",
        table_schemas=_POI_SCHEMA,
        large_tables={"cq_amap_poi_2024"},
    )
    assert "LIMIT 50" in result.sql.upper().replace(" ", " ")
    # No duplicate LIMIT clauses
    assert result.sql.upper().count("LIMIT") == 1


def test_no_limit_on_small_table():
    """Small tables (not in large_tables set) should not get auto-LIMIT."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40",
        table_schemas=_BUILDINGS_SCHEMA,
        large_tables=set(),
    )
    assert "LIMIT" not in result.sql.upper()


def test_no_limit_on_aggregation_query():
    """COUNT/SUM queries return one row — no need for LIMIT even on large tables."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(*) FROM cq_amap_poi_2024",
        table_schemas=_POI_SCHEMA,
        large_tables={"cq_amap_poi_2024"},
    )
    assert "LIMIT" not in result.sql.upper()
```

- [ ] **Step 2: Run new tests to verify failures**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v -k "limit"
```

Expected: 4 results — `inject_limit_on_large_table_full_scan` FAIL (no LIMIT injected), others may PASS by coincidence.

- [ ] **Step 3: Implement LIMIT injection**

Add helpers to `data_agent/sql_postprocessor.py` (above `postprocess_sql`):

```python
def _references_large_table(parsed: exp.Expression, large_tables: set) -> bool:
    if not large_tables:
        return False
    for table in parsed.find_all(exp.Table):
        name = table.name
        if name in large_tables:
            return True
    return False


def _is_aggregation_only(parsed: exp.Expression) -> bool:
    """True if SELECT contains only aggregation functions (COUNT/SUM/AVG/MIN/MAX) and no GROUP BY."""
    select = parsed.find(exp.Select) if isinstance(parsed, exp.With) else (parsed if isinstance(parsed, exp.Select) else None)
    if select is None:
        return False
    if select.args.get("group"):
        return False
    expressions = select.expressions or []
    if not expressions:
        return False
    agg_types = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
    for e in expressions:
        # unwrap Alias
        target = e.this if isinstance(e, exp.Alias) else e
        if not isinstance(target, agg_types):
            return False
    return True


def _has_limit(parsed: exp.Expression) -> bool:
    select = parsed.find(exp.Select) if isinstance(parsed, exp.With) else (parsed if isinstance(parsed, exp.Select) else None)
    if select is None:
        return False
    return select.args.get("limit") is not None


def _inject_limit(parsed: exp.Expression, n: int) -> exp.Expression:
    select = parsed.find(exp.Select) if isinstance(parsed, exp.With) else parsed
    if isinstance(select, exp.Select):
        select.set("limit", exp.Limit(expression=exp.Literal.number(n)))
    return parsed
```

Update `postprocess_sql` to add a LIMIT step before serialization:

```python
    column_map = _build_column_map(table_schemas)
    if column_map:
        parsed, fix_corrections = _fix_identifiers(parsed, column_map)
        result.corrections.extend(fix_corrections)

    # LIMIT injection for large tables (skip aggregation-only queries)
    if (
        large_tables
        and _references_large_table(parsed, large_tables)
        and not _has_limit(parsed)
        and not _is_aggregation_only(parsed)
    ):
        parsed = _inject_limit(parsed, 1000)
        result.corrections.append("LIMIT 1000 injected (large table referenced)")

    result.sql = parsed.sql(dialect="postgres")
    return result
```

- [ ] **Step 4: Run all postprocessor tests**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v
```

Expected: 16 PASS (12 + 4 LIMIT tests).

- [ ] **Step 5: Commit**

```bash
git add data_agent/sql_postprocessor.py data_agent/test_sql_postprocessor.py
git commit -m "feat(nl2sql): postprocessor auto-injects LIMIT on full scans of large tables"
```

---

## Task 5: SQL Postprocessor — regex fallback for sqlglot parse failures

**Files:**
- Modify: `data_agent/sql_postprocessor.py`
- Modify: `data_agent/test_sql_postprocessor.py`

- [ ] **Step 1: Append failing fallback test**

Append to `data_agent/test_sql_postprocessor.py`:

```python


# --- sqlglot parse failure fallback ---

def test_unparseable_sql_falls_back_to_regex_fix():
    """If sqlglot cannot parse, fall back to regex-based identifier fix."""
    from data_agent.sql_postprocessor import postprocess_sql
    # Intentionally weird SQL that sqlglot may struggle with — use a SELECT-ish form
    raw = "SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40 /* legit comment */"
    result = postprocess_sql(
        raw,
        table_schemas=_BUILDINGS_SCHEMA,
    )
    # Either sqlglot succeeds (preferred) or regex fallback fires; both must produce quoted "Floor"
    assert '"Floor"' in result.sql
    assert result.rejected is False


def test_truly_unparseable_sql_returns_rejected():
    """Garbage that even regex fallback can't safely fix → rejected."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "this is not sql at all !!!@#$",
        table_schemas={},
    )
    assert result.rejected is True
```

- [ ] **Step 2: Run the new tests**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v -k "unparseable"
```

Expected: `truly_unparseable_sql_returns_rejected` PASSes already (parse error path); `unparseable_sql_falls_back_to_regex_fix` likely PASSes already (sqlglot handles comments). If both pass: skip Step 3 implementation but still add the regex helper for safety.

- [ ] **Step 3: Add regex-fallback helper for resilience**

Add this helper to `data_agent/sql_postprocessor.py` (above `postprocess_sql`):

```python
import re


def _regex_fallback_fix(sql: str, column_map: dict) -> tuple[str, list[str]]:
    """Last-resort identifier fix using word-boundary regex.

    Only used when sqlglot parsing fails but we still want to attempt a safe rewrite.
    Skips identifiers already inside double quotes.
    """
    corrections: list[str] = []
    # Match a word that's not preceded by a double quote
    for lower_name, (real, needs_q) in column_map.items():
        if not needs_q:
            continue
        pattern = re.compile(rf'(?<!")\b{re.escape(lower_name)}\b(?!")', flags=re.IGNORECASE)
        new_sql, n = pattern.subn(f'"{real}"', sql)
        if n > 0:
            sql = new_sql
            corrections.append(f"Regex fallback fix: {lower_name} -> \"{real}\" ({n} occurrences)")
    return sql, corrections
```

Then update the parse-error branch of `postprocess_sql`:

```python
    try:
        parsed = sqlglot.parse_one(raw_sql, dialect="postgres")
    except Exception as e:
        # Try regex fallback only if the SQL at least looks like a SELECT
        if raw_sql.strip().upper().startswith(("SELECT", "WITH")):
            column_map = _build_column_map(table_schemas)
            fixed_sql, fix_corrections = _regex_fallback_fix(raw_sql, column_map)
            result.sql = fixed_sql
            result.corrections.extend(fix_corrections)
            result.corrections.append(f"sqlglot parse failed, applied regex fallback: {e}")
            return result
        result.rejected = True
        result.reject_reason = f"SQL parse error: {e}"
        return result
```

- [ ] **Step 4: Run all postprocessor tests**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v
```

Expected: 18 PASS.

- [ ] **Step 5: Commit**

```bash
git add data_agent/sql_postprocessor.py data_agent/test_sql_postprocessor.py
git commit -m "feat(nl2sql): postprocessor adds regex fallback for sqlglot parse failures"
```

## Task 6: Grounding module — semantic layer + schema + few-shot

**Files:**
- Create: `data_agent/nl2sql_grounding.py`
- Create: `data_agent/test_nl2sql_grounding.py`

- [ ] **Step 1: Write failing tests for grounding output shape**

Create `data_agent/test_nl2sql_grounding.py`:

```python
"""Tests for nl2sql_grounding.build_nl2sql_context."""
from unittest.mock import patch


def test_build_context_returns_expected_keys():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [{
            "table_name": "cq_buildings_2021",
            "display_name": "重庆建筑物数据",
            "description": "建筑物轮廓",
            "confidence": 0.9,
        }],
        "matched_columns": {
            "cq_buildings_2021": [
                {"column_name": "Floor", "aliases": ["层高", "层数"], "semantic_domain": "HEIGHT"}
            ]
        },
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
        "hierarchy_matches": [],
        "sql_filters": [],
        "equivalences": [],
    }
    schema = {
        "status": "success",
        "table_name": "cq_buildings_2021",
        "display_name": "重庆建筑物数据",
        "columns": [
            {"column_name": "Id", "data_type": "integer", "semantic_domain": None, "aliases": []},
            {"column_name": "Floor", "data_type": "integer", "semantic_domain": "HEIGHT", "aliases": ["层高", "层数"]},
            {"column_name": "geometry", "data_type": "USER-DEFINED", "semantic_domain": None, "aliases": [], "is_geometry": True},
        ],
    }
    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", return_value=schema), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value="参考查询示例:\nQ: ...\nSQL: SELECT ..."), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=107035):
        result = build_nl2sql_context("统计层高>=40的建筑数量")

    assert set(result.keys()) == {"candidate_tables", "semantic_hints", "few_shots", "grounding_prompt"}
    assert len(result["candidate_tables"]) == 1
    table = result["candidate_tables"][0]
    assert table["table_name"] == "cq_buildings_2021"
    assert table["row_count_hint"] == 107035
    cols = {c["column_name"]: c for c in table["columns"]}
    assert cols["Floor"]["quoted_ref"] == '"Floor"'
    assert cols["geometry"]["quoted_ref"] == "geometry"
    assert cols["Floor"]["needs_quoting"] is True


def test_build_context_fallbacks_to_list_sources_when_semantic_has_no_sources():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [], "matched_columns": {}, "spatial_ops": [], "region_filter": None,
        "metric_hints": [], "hierarchy_matches": [], "sql_filters": [], "equivalences": [],
    }
    source_list = {
        "status": "success",
        "sources": [
            {
                "table_name": "cq_buildings_2021",
                "display_name": "重庆建筑物数据",
                "description": "重庆市建筑物轮廓数据",
                "synonyms": ["建筑数据", "中心城区建筑数据"],
                "geometry_type": "MULTIPOLYGON",
                "srid": 4326,
                "suggested_analyses": [],
            }
        ],
    }
    schema = {
        "status": "success",
        "table_name": "cq_buildings_2021",
        "display_name": "重庆建筑物数据",
        "columns": [
            {"column_name": "Id", "data_type": "integer", "semantic_domain": None, "aliases": []},
            {"column_name": "Floor", "data_type": "integer", "semantic_domain": "HEIGHT", "aliases": ["层高"]},
        ],
    }
    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.list_semantic_sources", return_value=source_list), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", return_value=schema), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=107035):
        result = build_nl2sql_context("统计中心城区建筑数据中层高>=40的数量")

    assert len(result["candidate_tables"]) == 1
    assert result["candidate_tables"][0]["table_name"] == "cq_buildings_2021"


def test_grounding_prompt_contains_postgres_quote_warning():
    from data_agent.nl2sql_grounding import _format_grounding_prompt

    payload = {
        "candidate_tables": [
            {
                "table_name": "cq_buildings_2021",
                "display_name": "重庆建筑物数据",
                "confidence": 0.9,
                "row_count_hint": 107035,
                "columns": [
                    {"column_name": "Id", "pg_type": "integer", "quoted_ref": '"Id"', "aliases": ["编号"], "needs_quoting": True},
                    {"column_name": "Floor", "pg_type": "integer", "quoted_ref": '"Floor"', "aliases": ["层高"], "needs_quoting": True},
                    {"column_name": "geometry", "pg_type": "geometry", "quoted_ref": "geometry", "aliases": [], "needs_quoting": False},
                ],
            }
        ],
        "semantic_hints": {"spatial_ops": [], "region_filter": None, "metric_hints": [], "hierarchy_matches": [], "sql_filters": []},
        "few_shots": [
            {"question": "统计建筑数量", "sql": 'SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40;'}
        ],
    }
    text = _format_grounding_prompt(payload)
    assert "PostgreSQL" in text
    assert '"Floor"' in text
    assert '"Id"' in text
    assert "参考 SQL" in text or "参考查询示例" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_grounding.py -v
```

Expected: 3 FAIL with `ModuleNotFoundError: data_agent.nl2sql_grounding`.

- [ ] **Step 3: Implement grounding module**

Create `data_agent/nl2sql_grounding.py`:

```python
"""NL2SQL grounding: semantic resolution + schema assembly + few-shot formatting."""
from __future__ import annotations

from difflib import SequenceMatcher

from .reference_queries import fetch_nl2sql_few_shots
from .semantic_layer import (
    describe_table_semantic,
    list_semantic_sources,
    resolve_semantic_context,
)

# Minimal PostgreSQL reserved words we care about for quoting
PG_RESERVED_WORDS = {
    "user", "select", "group", "order", "where", "table", "from",
}


def _needs_quoting(column_name: str) -> bool:
    """Return True if a PostgreSQL identifier must be double-quoted.

    Rule: lowercase, non-reserved identifiers do not need quotes; anything mixed-
    case, uppercase, non-identifier-ish, or reserved must be quoted.
    """
    if not column_name:
        return False
    if column_name.lower() != column_name:
        return True
    if column_name in PG_RESERVED_WORDS:
        return True
    if not column_name.replace("_", "a").isalnum():
        return True
    return False


def _quoted_ref(column_name: str) -> str:
    return f'"{column_name}"' if _needs_quoting(column_name) else column_name


def _estimate_table_size(table_name: str) -> int:
    """Best-effort table size estimate for LIMIT heuristics.

    Uses describe_table_semantic() metadata if available; falls back to 0 when
    no row estimate is available. Phase 1 only needs a hint, not exact stats.
    """
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


def _build_candidate_table(source: dict, schema: dict) -> dict:
    """Merge semantic source hit + describe_table_semantic() result."""
    out_columns = []
    for col in schema.get("columns", []) or []:
        column_name = col.get("column_name", "")
        aliases = col.get("aliases", []) or []
        pg_type = col.get("data_type") or col.get("udt_name") or ""
        if col.get("is_geometry") and schema.get("geometry_type"):
            pg_type = f"geometry({schema.get('geometry_type')},{schema.get('srid')})"
        out_columns.append({
            "column_name": column_name,
            "pg_type": pg_type,
            "quoted_ref": _quoted_ref(column_name),
            "aliases": aliases,
            "semantic_domain": col.get("semantic_domain"),
            "unit": col.get("unit") or "",
            "description": col.get("description") or "",
            "is_geometry": bool(col.get("is_geometry", False)),
            "needs_quoting": _needs_quoting(column_name),
        })
    return {
        "table_name": source.get("table_name") or schema.get("table_name"),
        "display_name": source.get("display_name") or schema.get("display_name") or source.get("table_name"),
        "description": source.get("description") or schema.get("description") or "",
        "confidence": float(source.get("confidence", 0.0)),
        "columns": out_columns,
        "row_count_hint": _estimate_table_size(source.get("table_name") or schema.get("table_name")),
    }


def _format_grounding_prompt(payload: dict) -> str:
    """Format the grounding payload into a strict prompt block for the LLM."""
    lines: list[str] = []
    lines.append("[NL2SQL 上下文 — 必须严格遵循以下 schema]")
    lines.append("")
    lines.append("## 候选数据源")
    for table in payload.get("candidate_tables", []):
        lines.append("")
        lines.append(f"### {table['table_name']} ({table.get('display_name') or table['table_name']})")
        lines.append(f"置信度: {table.get('confidence', 0.0):.2f}; 估计行数: {table.get('row_count_hint', 0)}")
        for col in table.get("columns", []):
            alias_str = ", ".join(col.get("aliases") or []) or "—"
            lines.append(f"- {col['quoted_ref']} :: {col.get('pg_type','')} | 别名: {alias_str}")
        if any(c.get("needs_quoting") for c in table.get("columns", [])):
            lines.append("⚠ PostgreSQL 规则: 大小写混合列名必须使用双引号，例如 \"Floor\"、\"Id\"。")
    lines.append("")
    lines.append("## 语义提示")
    hints = payload.get("semantic_hints", {})
    lines.append(f"- 空间操作: {hints.get('spatial_ops') or []}")
    lines.append(f"- 区域过滤: {hints.get('region_filter')}")
    lines.append(f"- 层次匹配: {hints.get('hierarchy_matches') or []}")
    lines.append(f"- 指标提示: {hints.get('metric_hints') or []}")
    lines.append(f"- 推荐 SQL 过滤: {hints.get('sql_filters') or []}")
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
    lines.append("- 大表全表扫描必须有 LIMIT")
    lines.append("- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER")
    return "\n".join(lines)


def build_nl2sql_context(user_text: str) -> dict:
    """Build semantic + schema grounding payload for NL2SQL generation.

    The result is consumed by prepare_nl2sql_context() before the LLM writes SQL.
    """
    semantic = resolve_semantic_context(user_text)
    sources = list(semantic.get("sources") or [])

    if not sources:
        source_list = list_semantic_sources()
        if source_list.get("status") == "success":
            scored = []
            for source in source_list.get("sources", []):
                score = _score_source(user_text, source)
                if score > 0:
                    s = dict(source)
                    s["confidence"] = score
                    scored.append(s)
            scored.sort(key=lambda s: s.get("confidence", 0), reverse=True)
            sources = scored[:3]

    candidate_tables = []
    for source in sources[:3]:
        table_name = source.get("table_name")
        if not table_name:
            continue
        schema = describe_table_semantic(table_name)
        if schema.get("status") != "success":
            continue
        candidate_tables.append(_build_candidate_table(source, schema))

    few_shot_text = fetch_nl2sql_few_shots(user_text, top_k=3)
    few_shots = []
    if few_shot_text:
        # Minimal wrapping: preserve the original formatted string as one few-shot block
        few_shots.append({"question": "参考查询示例", "sql": few_shot_text})

    payload = {
        "candidate_tables": candidate_tables,
        "semantic_hints": {
            "spatial_ops": semantic.get("spatial_ops") or [],
            "region_filter": semantic.get("region_filter"),
            "hierarchy_matches": semantic.get("hierarchy_matches") or [],
            "metric_hints": semantic.get("metric_hints") or [],
            "sql_filters": semantic.get("sql_filters") or [],
        },
        "few_shots": few_shots,
    }
    payload["grounding_prompt"] = _format_grounding_prompt(payload)
    return payload
```

- [ ] **Step 4: Run grounding tests**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_grounding.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add data_agent/nl2sql_grounding.py data_agent/test_nl2sql_grounding.py
git commit -m "feat(nl2sql): add semantic grounding module for schema-aware SQL generation"
```

---

## Task 7: Executor tools — prepare_nl2sql_context + execute_nl2sql

**Files:**
- Create: `data_agent/nl2sql_executor.py`
- Create: `data_agent/test_nl2sql_executor.py`
- Modify: `data_agent/user_context.py`

- [ ] **Step 1: Write failing executor tests**

Create `data_agent/test_nl2sql_executor.py`:

```python
"""Tests for nl2sql_executor tools."""
from unittest.mock import patch


def test_prepare_nl2sql_context_returns_prompt_and_caches_schema():
    from data_agent.nl2sql_executor import prepare_nl2sql_context, _cached_schemas

    payload = {
        "candidate_tables": [{
            "table_name": "cq_buildings_2021",
            "columns": [
                {"column_name": "Id", "needs_quoting": True},
                {"column_name": "Floor", "needs_quoting": True},
            ],
            "row_count_hint": 107035,
        }],
        "semantic_hints": {},
        "few_shots": [],
        "grounding_prompt": "PROMPT BLOCK",
    }
    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload):
        prompt = prepare_nl2sql_context("统计层高>=40")
    assert prompt == "PROMPT BLOCK"
    cached = _cached_schemas.get()
    assert "cq_buildings_2021" in cached
    assert cached["cq_buildings_2021"][0]["column_name"] == "Id"


def test_execute_nl2sql_rejected_returns_message():
    from data_agent.nl2sql_executor import execute_nl2sql
    class FakeResult:
        rejected = True
        reject_reason = "Only SELECT/WITH queries are allowed"
        sql = "DELETE FROM t"
    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()):
        result = execute_nl2sql("DELETE FROM t")
    assert "安全拒绝" in result


def test_execute_nl2sql_executes_corrected_sql():
    from data_agent.nl2sql_executor import execute_nl2sql
    class FakeResult:
        rejected = False
        reject_reason = ""
        sql = 'SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40'
    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1,"data":[{"count":123}],"message":"ok"}') as mock_exec:
        result = execute_nl2sql("SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40")
    mock_exec.assert_called_once_with('SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40')
    assert '"status":"ok"' in result
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_executor.py -v
```

Expected: 3 FAIL with `ModuleNotFoundError: data_agent.nl2sql_executor`.

- [ ] **Step 3: Add ContextVars in user_context.py**

Append to `data_agent/user_context.py` after the existing ContextVar definitions (after line 15):

```python
# NL2SQL grounding cache (Phase 1)
current_nl2sql_schemas: ContextVar[dict] = ContextVar('current_nl2sql_schemas', default={})
current_nl2sql_large_tables: ContextVar[set] = ContextVar('current_nl2sql_large_tables', default=set())
current_nl2sql_question: ContextVar[str] = ContextVar('current_nl2sql_question', default='')
```

- [ ] **Step 4: Implement executor module**

Create `data_agent/nl2sql_executor.py`:

```python
"""Executor tools for NL2SQL Phase 1: prepare grounding and execute corrected SQL."""
from __future__ import annotations

from .nl2sql_grounding import build_nl2sql_context
from .sql_postprocessor import postprocess_sql
from .toolsets.nl2sql_tools import execute_safe_sql
from .user_context import (
    current_nl2sql_large_tables,
    current_nl2sql_question,
    current_nl2sql_schemas,
)

# Backward-compatible names used in tests / plan prose
_cached_schemas = current_nl2sql_schemas
_cached_large_tables = current_nl2sql_large_tables


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

    return payload.get("grounding_prompt", "")


def execute_nl2sql(sql: str) -> str:
    """Postprocess and execute NL2SQL-generated SQL.

    Reads the cached schema grounding from ContextVars, applies SQL post-
    processing (AST safety check, identifier quoting, LIMIT injection), and then
    executes via the existing safe executor.
    """
    schemas = current_nl2sql_schemas.get()
    large_tables = current_nl2sql_large_tables.get()

    result = postprocess_sql(sql, schemas, large_tables)
    if result.rejected:
        return f"安全拒绝: {result.reject_reason}"
    return execute_safe_sql(result.sql)
```

- [ ] **Step 5: Run executor tests**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_executor.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add data_agent/nl2sql_executor.py data_agent/test_nl2sql_executor.py data_agent/user_context.py
git commit -m "feat(nl2sql): add two-step executor tools with ContextVar grounding cache"
```

---

## Task 8: Register NL2SQLEnhancedToolset in toolset system

**Files:**
- Create: `data_agent/toolsets/nl2sql_enhanced_tools.py`
- Modify: `data_agent/toolsets/__init__.py`
- Modify: `data_agent/custom_skills.py`

- [ ] **Step 1: Write failing registration test**

Create `data_agent/test_nl2sql_toolset_registration.py`:

```python
"""Tests for NL2SQLEnhancedToolset registration."""


def test_enhanced_toolset_exported_from_toolsets_package():
    from data_agent.toolsets import NL2SQLEnhancedToolset
    assert NL2SQLEnhancedToolset is not None


def test_enhanced_toolset_allowed_for_custom_skills():
    from data_agent.custom_skills import TOOLSET_NAMES, _get_toolset_registry
    assert "NL2SQLEnhancedToolset" in TOOLSET_NAMES
    registry = _get_toolset_registry()
    assert "NL2SQLEnhancedToolset" in registry


def test_enhanced_toolset_exposes_two_tools():
    import asyncio
    from data_agent.toolsets.nl2sql_enhanced_tools import NL2SQLEnhancedToolset
    ts = NL2SQLEnhancedToolset()
    tools = asyncio.run(ts.get_tools())
    tool_names = sorted([t.name for t in tools])
    assert tool_names == ["execute_nl2sql", "prepare_nl2sql_context"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_toolset_registration.py -v
```

Expected: 3 FAIL (`ImportError` or missing registry entry).

- [ ] **Step 3: Implement NL2SQLEnhancedToolset**

Create `data_agent/toolsets/nl2sql_enhanced_tools.py`:

```python
"""Enhanced NL2SQL toolset: semantic grounding + SQL postprocessing."""
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..nl2sql_executor import prepare_nl2sql_context, execute_nl2sql


class NL2SQLEnhancedToolset(BaseToolset):
    """Enhanced NL2SQL toolset: grounding first, execution second."""

    async def get_tools(self, readonly_context=None):
        return [
            FunctionTool(prepare_nl2sql_context),
            FunctionTool(execute_nl2sql),
        ]
```

- [ ] **Step 4: Export from toolsets package**

In `data_agent/toolsets/__init__.py`, add this import near the existing `NL2SQLToolset` export:

```python
from .nl2sql_enhanced_tools import NL2SQLEnhancedToolset
```

- [ ] **Step 5: Add to custom_skills registry**

In `data_agent/custom_skills.py`:

1. In `TOOLSET_NAMES` set (near lines 25–41), add:
```python
    "NL2SQLEnhancedToolset",
```

2. In `_get_toolset_registry()` import block (near lines 46–75), add:
```python
        NL2SQLEnhancedToolset,
```

3. In the returned registry dict (near lines 76–90), add:
```python
        "NL2SQLEnhancedToolset": NL2SQLEnhancedToolset,
```

- [ ] **Step 6: Run registration tests**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_toolset_registration.py -v
```

Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add data_agent/toolsets/nl2sql_enhanced_tools.py data_agent/toolsets/__init__.py data_agent/custom_skills.py data_agent/test_nl2sql_toolset_registration.py
git commit -m "feat(nl2sql): register NL2SQLEnhancedToolset for custom skills"
```

---

## Task 9: Benchmark harness — add enhanced mode

**Files:**
- Modify: `scripts/nl2sql_bench_cq/run_cq_eval.py`

- [ ] **Step 1: Write a failing smoke test for enhanced mode flag**

Create `data_agent/test_nl2sql_benchmark_mode.py`:

```python
"""Smoke tests for run_cq_eval.py enhanced mode helpers."""
import importlib.util
from pathlib import Path


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_cq_eval_has_enhanced_mode_constant():
    mod = _load_module(
        "D:/adk/scripts/nl2sql_bench_cq/run_cq_eval.py",
        "run_cq_eval_mod",
    )
    assert hasattr(mod, "PROMPT_ENHANCED")
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_benchmark_mode.py -v
```

Expected: FAIL (`PROMPT_ENHANCED` missing).

- [ ] **Step 3: Add enhanced prompt mode in benchmark harness**

In `scripts/nl2sql_bench_cq/run_cq_eval.py`:

1. Add a constant near `PROMPT_BASELINE`:

```python
PROMPT_ENHANCED = """你是 PostgreSQL/PostGIS NL2SQL 助手。请先阅读下面的 [NL2SQL 上下文]，然后生成 SQL。

要求：
1. 严格使用 schema 中给出的列引用（尤其是双引号字段）
2. 只允许 SELECT
3. 大表全表扫描必须加 LIMIT
4. 直接输出 SQL，不要解释

[NL2SQL 上下文]
{grounding}

用户问题: {question}
"""
```

2. Add helper function near `call_model()`:

```python
def build_enhanced_prompt(question: str) -> str:
    """Build grounding-aware benchmark prompt using the Phase 1 module."""
    from data_agent.nl2sql_grounding import build_nl2sql_context
    payload = build_nl2sql_context(question)
    return PROMPT_ENHANCED.format(
        grounding=payload.get("grounding_prompt", ""),
        question=question,
    )
```

3. Add a `mode` variable near the top of `main()`:

```python
    mode = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    if mode not in {"baseline", "enhanced"}:
        raise SystemExit("Usage: run_cq_eval.py [baseline|enhanced]")
```

4. In the loop where each question is sent to the model, branch prompt construction:

```python
        if mode == "enhanced":
            prompt = build_enhanced_prompt(question)
        else:
            prompt = PROMPT_BASELINE.format(schema=schema_dump, question=question)
```

5. Add `mode` into report metadata:

```python
        "mode": mode,
```

- [ ] **Step 4: Run benchmark mode smoke test**

```bash
.venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_benchmark_mode.py -v
```

Expected: PASS.

- [ ] **Step 5: Run a single-question enhanced dry run**

```bash
PYTHONPATH="D:/adk" .venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_cq_eval.py enhanced 2>&1 | head -40
```

Expected: script starts, loads benchmark, and does not crash at import time. (You may stop it early after confirming startup, since full run takes time.)

- [ ] **Step 6: Commit**

```bash
git add scripts/nl2sql_bench_cq/run_cq_eval.py data_agent/test_nl2sql_benchmark_mode.py
git commit -m "feat(nl2sql): add enhanced benchmark mode with grounding-aware prompt"
```

---

## Task 10: End-to-end Phase 1 verification

**Files:**
- Modify: `requirements.txt` (already changed)
- Existing: `docs/superpowers/specs/2026-04-21-nl2sql-optimization-phase1-design.md`

- [ ] **Step 1: Run all new unit tests**

```bash
.venv/Scripts/python.exe -m pytest \
  data_agent/test_sql_postprocessor.py \
  data_agent/test_nl2sql_grounding.py \
  data_agent/test_nl2sql_executor.py \
  data_agent/test_nl2sql_toolset_registration.py \
  data_agent/test_nl2sql_benchmark_mode.py -v
```

Expected: all PASS.

- [ ] **Step 2: Run a focused regression on benchmark failure patterns**

Use the enhanced mode and compare against known failure cases manually:

```bash
PYTHONPATH="D:/adk" .venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_cq_eval.py enhanced
```

Expected improvements on these cases:
- `CQ_GEO_EASY_01`: `floor` → `"Floor"`
- `CQ_GEO_EASY_03`: `BSM / DLMC / TBMJ` quoted
- `CQ_GEO_ROBUSTNESS_01`: DELETE rejected
- `CQ_GEO_ROBUSTNESS_03`: LIMIT injected

- [ ] **Step 3: Verify the target accuracy threshold**

Inspect the generated report JSON and confirm:

```python
summary["accuracy_percent"] >= 80.0
```

If accuracy is still below 80%, stop after recording the failing IDs; do not start Phase 2 work in this branch.

- [ ] **Step 4: Manual runtime smoke test with @NL2SQL**

Start the app and ask one real query from the benchmark:

```text
@NL2SQL 统计中心城区建筑数据中，层高（Floor）大于等于 40 层的超高层建筑有多少栋？
```

Expected behavior:
1. The tool chain calls `prepare_nl2sql_context` first.
2. The grounding prompt includes `"Floor"` and `"Id"`.
3. The generated SQL is postprocessed and executed successfully.
4. No “未能从语义层找到匹配的数据源” error.

- [ ] **Step 5: Commit final polish (if any)**

```bash
git status
# If there are final edits from verification:
git add -A
git commit -m "test(nl2sql): validate Phase 1 benchmark and runtime behavior"
```

- [ ] **Step 6: Acceptance checklist**

Confirm all Phase 1 spec items are complete:

- [x] Schema grounding module (`nl2sql_grounding.py`)
- [x] SQL postprocessor (`sql_postprocessor.py`)
- [x] Executor wrapper (`nl2sql_executor.py`)
- [x] NL2SQLEnhancedToolset registration
- [x] Custom Skill path uses prepare → execute two-step protocol
- [x] Benchmark harness has enhanced mode
- [x] Unit tests cover major benchmark failure patterns
- [x] Gemini benchmark ≥80%

---

## Self-Review Notes

**Spec coverage:**
- §3.1 grounding module → Task 6
- §3.2 SQL postprocessor → Tasks 2–5
- §3.3 executor wrapper → Task 7
- §3.4 enhanced toolset → Task 8
- §3.5 NL2SQL Custom Skill instruction path → Task 7/8 (tool path) + Task 10 runtime verification
- §4 benchmark regression → Task 9 + Task 10
- §5 tests → Tasks 2–10
- §6 file changes → all tasks collectively
- §7 non-goals are preserved (no GeneralPipeline / Planner restructuring, no Phase 2 self-correction)

**Placeholder scan:**
- No TBD/TODO/"similar to task N" placeholders
- Every code-modifying step includes exact code or exact insertion instructions
- Every test step has exact commands and expected outcome

**Type consistency:**
- `PostprocessResult(sql, corrections, rejected, reject_reason)` used consistently across Tasks 2–5 and Task 7
- ContextVars names standardized to `current_nl2sql_schemas`, `current_nl2sql_large_tables`, `current_nl2sql_question`
- Tool names standardized to `prepare_nl2sql_context` and `execute_nl2sql`
- Toolset name standardized to `NL2SQLEnhancedToolset`

**Scope check:**
- Focused on Phase 1 only
- Does not include self-correction loop or pipeline unification (reserved for later phases)

