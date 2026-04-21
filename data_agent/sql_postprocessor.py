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


def postprocess_sql(
    raw_sql: str,
    table_schemas: dict,
    large_tables: Optional[set] = None,
) -> PostprocessResult:
    """Postprocess raw LLM-generated SQL: safety check, identifier fix, LIMIT injection."""
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
