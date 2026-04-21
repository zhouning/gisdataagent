"""SQL postprocessor for NL2SQL: AST safety check + identifier quoting + LIMIT injection."""
from __future__ import annotations

import re
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


def _regex_fallback_fix(sql: str, column_map: dict) -> tuple[str, list[str]]:
    """Last-resort identifier fix using word-boundary regex.

    Only used when sqlglot parsing fails but we still want to attempt a safe rewrite.
    Skips identifiers already inside double quotes.
    """
    corrections: list[str] = []
    for lower_name, (real, needs_q) in column_map.items():
        if not needs_q:
            continue
        pattern = re.compile(rf'(?<!")\b{re.escape(lower_name)}\b(?!")', flags=re.IGNORECASE)
        new_sql, n = pattern.subn(f'"{real}"', sql)
        if n > 0:
            sql = new_sql
            corrections.append(f"Regex fallback fix: {lower_name} -> \"{real}\" ({n} occurrences)")
    return sql, corrections


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
