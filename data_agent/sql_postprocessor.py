"""SQL postprocessor for NL2SQL: AST safety check + identifier quoting + LIMIT injection."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import sqlglot
import sqlglot.expressions as exp

if TYPE_CHECKING:
    from .nl2sql_intent import IntentLabel


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

DEFAULT_LIMIT = 1000


def _get_outermost_select(parsed: exp.Expression) -> Optional[exp.Select]:
    if isinstance(parsed, exp.Select):
        return parsed
    if isinstance(parsed, exp.With):
        inner = parsed.this
        return inner if isinstance(inner, exp.Select) else None
    if isinstance(parsed, (exp.Union, exp.Intersect, exp.Except)):
        return parsed.this if isinstance(parsed.this, exp.Select) else None
    return None


def _is_safe_root(parsed: exp.Expression) -> bool:
    """A safe root must be a Select, With, or set operation (Union/Intersect/Except)."""
    if isinstance(parsed, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return True
    if isinstance(parsed, exp.With):
        return isinstance(parsed.this, (exp.Select, exp.Union, exp.Intersect, exp.Except))
    return False


def _has_write_node(parsed: exp.Expression) -> bool:
    """Walk the AST looking for any write-operation node."""
    for node in parsed.walk():
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, _WRITE_NODE_TYPES):
            return True
    return False


def _build_column_map(table_schemas: dict) -> dict[str, tuple[str, bool]]:
    """Build {lowercase_name -> (real_name, needs_quoting)} from table_schemas."""
    column_map: dict[str, tuple[str, bool]] = {}
    for cols in table_schemas.values():
        for col in cols:
            real = col["column_name"]
            needs_q = bool(col.get("needs_quoting", False))
            key = real.lower()
            if key in column_map:
                continue
            column_map[key] = (real, needs_q)
    return column_map


def _fix_identifiers(parsed: exp.Expression, column_map: dict) -> tuple[exp.Expression, list[str]]:
    """Walk AST and rewrite Column nodes to use real-cased + quoted names."""
    corrections: list[str] = []

    def transform(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Column):
            ident = node.this
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


def _references_large_table(parsed: exp.Expression, large_tables: set) -> bool:
    if not large_tables:
        return False
    for table in parsed.find_all(exp.Table):
        name = table.name
        if name in large_tables:
            return True
    return False


def _is_aggregation_only(parsed: exp.Expression) -> bool:
    """True if SELECT contains only aggregation functions and no GROUP BY."""
    select = _get_outermost_select(parsed)
    if select is None:
        return False
    if select.args.get("group"):
        return False
    expressions = select.expressions or []
    if not expressions:
        return False
    agg_types = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
    for e in expressions:
        target = e.this if isinstance(e, exp.Alias) else e
        if not isinstance(target, agg_types):
            return False
    return True


def _has_limit(parsed: exp.Expression) -> bool:
    select = _get_outermost_select(parsed)
    if select is None:
        return False
    return select.args.get("limit") is not None


def _inject_limit(parsed: exp.Expression, n: int) -> exp.Expression:
    select = _get_outermost_select(parsed)
    if isinstance(select, exp.Select):
        select.set("limit", exp.Limit(expression=exp.Literal.number(n)))
    return parsed


def _regex_fallback_fix(sql: str, column_map: dict) -> tuple[str, list[str]]:
    """Last-resort identifier fix using word-boundary regex.

    Only used when sqlglot parsing fails but we still want to attempt a safe rewrite.
    Skips identifiers inside single-quoted or double-quoted strings.
    """
    corrections: list[str] = []
    # Split on single-quoted strings to avoid corrupting literals
    parts = re.split(r"('(?:[^'\\]|\\.)*')", sql)
    for i in range(0, len(parts), 2):  # only process non-literal segments
        segment = parts[i]
        for lower_name, (real, needs_q) in column_map.items():
            if not needs_q:
                continue
            pattern = re.compile(rf'(?<!")\b{re.escape(lower_name)}\b(?!")', flags=re.IGNORECASE)
            new_segment, n = pattern.subn(f'"{real}"', segment)
            if n > 0:
                segment = new_segment
                corrections.append(f"Regex fallback fix: {lower_name} -> \"{real}\" ({n} occurrences)")
        parts[i] = segment
    return "".join(parts), corrections


def explain_row_estimate(sql: str, timeout_ms: int = 2000) -> Optional[int]:
    """Ask the PostgreSQL planner for estimated row count via EXPLAIN (FORMAT JSON).

    Returns None on parse, timeout, connection, or any other error. EXPLAIN
    itself does not execute the query -- safe to call on untrusted SQL as long
    as the SQL is syntactically parseable by PostgreSQL.

    The returned value is the planner's estimate for the ROOT plan node's
    output row count (a.k.a. "Plan Rows"), which represents how many rows
    the query would return to the client (not intermediate row counts).
    """
    try:
        from data_agent.db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if engine is None:
            return None
        with engine.connect() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            res = conn.execute(text(f"EXPLAIN (FORMAT JSON) {sql}")).fetchone()
        if not res or not res[0]:
            return None
        plan = res[0][0]["Plan"]
        return int(plan.get("Plan Rows", 0))
    except Exception:
        return None


def postprocess_sql(
    raw_sql: str,
    table_schemas: dict,
    large_tables: Optional[set] = None,
    intent: Optional["IntentLabel"] = None,
    explain_limit_threshold: Optional[int] = None,
) -> PostprocessResult:
    """Postprocess raw LLM-generated SQL: safety check, identifier fix, LIMIT injection.

    Args:
        raw_sql: SQL string from LLM.
        table_schemas: dict mapping table_name -> list of column dicts
            (each column dict has at least 'column_name' and 'needs_quoting').
        large_tables: set of table names that should auto-receive LIMIT 1000.
        intent: classified query intent; when ATTRIBUTE_FILTER (or other non-listing
            intents), LIMIT injection is suppressed even for large tables.
        explain_limit_threshold: when set and the SQL has no LIMIT and is not
            pure aggregation, consult PostgreSQL's planner via
            ``explain_row_estimate()``; if the estimated row count exceeds the
            threshold, inject ``LIMIT DEFAULT_LIMIT``. This is an additional
            safety net on top of the static ``large_tables`` guard and is off
            by default (``None`` -- behaviour unchanged).

    Returns:
        PostprocessResult with sql, corrections, rejected, reject_reason.
    """
    result = PostprocessResult(sql=raw_sql)

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

    # LIMIT injection for large tables.
    #
    # Large-table guard is an intent-independent safety mechanism: when a SELECT
    # references a known large table and has no LIMIT (and is not aggregation-
    # only), we inject LIMIT regardless of intent classification. This closes
    # the OOM Prevention gap where naturally phrased "show me all X" queries
    # classify as ATTRIBUTE_FILTER and bypass the original intent-gated guard.
    #
    # We keep the original intent-gated path (for non-large-table preview
    # queries) by checking intent only when large_tables is empty / does not
    # match the referenced tables.
    from .nl2sql_intent import IntentLabel as _IL
    refs_large_table = bool(large_tables) and _references_large_table(parsed, large_tables)
    _allow_limit = refs_large_table or (intent in (None, _IL.PREVIEW_LISTING, _IL.UNKNOWN))
    if (
        _allow_limit
        and large_tables
        and refs_large_table
        and not _is_aggregation_only(parsed)
    ):
        if not _has_limit(parsed):
            parsed = _inject_limit(parsed, DEFAULT_LIMIT)
            result.corrections.append(
                f"LIMIT {DEFAULT_LIMIT} injected (large-table guard: intent={intent})"
            )
        else:
            # Bump LLM-injected small LIMITs (<=100) to DEFAULT_LIMIT
            outermost = _get_outermost_select(parsed)
            if outermost:
                limit_node = outermost.args.get("limit")
                if limit_node:
                    limit_expr = limit_node.expression
                    if isinstance(limit_expr, exp.Literal) and limit_expr.is_int:
                        val = int(limit_expr.this)
                        if val <= 100:
                            limit_node.set("expression", exp.Literal.number(DEFAULT_LIMIT))
                            result.corrections.append(f"LIMIT {val} bumped to {DEFAULT_LIMIT} (large table)")

    # EXPLAIN-based OOM pre-check (Task 5).
    #
    # Additional safety net for tables NOT in the static `large_tables` set
    # (e.g., dynamically-discovered or cross-schema tables). When opted in via
    # `explain_limit_threshold`, ask the PostgreSQL planner for the estimated
    # row count of the current SQL; if it exceeds the threshold, inject
    # LIMIT DEFAULT_LIMIT. Pure aggregation queries and already-LIMITed queries
    # are skipped. Off by default (threshold=None) -- behaviour unchanged.
    if (
        explain_limit_threshold is not None
        and not result.rejected
        and not _has_limit(parsed)
        and not _is_aggregation_only(parsed)
    ):
        try:
            sql_for_explain = parsed.sql(dialect="postgres")
        except Exception:
            sql_for_explain = None
        if sql_for_explain:
            est = explain_row_estimate(sql_for_explain)
            if est is not None and est > explain_limit_threshold:
                parsed = _inject_limit(parsed, DEFAULT_LIMIT)
                result.corrections.append(
                    f"LIMIT {DEFAULT_LIMIT} injected (EXPLAIN row estimate "
                    f"{est} > threshold {explain_limit_threshold})"
                )

    result.sql = parsed.sql(dialect="postgres")
    return result
