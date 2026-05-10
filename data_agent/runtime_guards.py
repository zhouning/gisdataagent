"""Runtime SQL guards for NL2SQL evaluation pipeline.

Three lightweight post-hoc checks called between SQL extraction and execution.
They run for ALL families (defense-in-depth) but were motivated by DeepSeek
attribution buckets F (hallucinated table names) and G (give-up SQL).

These guards are NOT a substitute for proper prompt engineering — they catch
the residual cases where the model produces a syntactically valid but
semantically broken SQL. The first line of defence is the family-specific
system instruction (R5, R6 for DeepSeek).
"""
from __future__ import annotations

import re

# ----------------------------------------------------------------------------
# Give-up SQL detection (bucket G)
# ----------------------------------------------------------------------------

# Patterns matched against whitespace-collapsed lower-case SQL with trailing
# semicolons and LIMIT clauses stripped. Each pattern represents a placeholder
# query that the model emits when it cannot or chooses not to answer the
# question — typically `SELECT 1 AS test`, `SELECT 1`, or `SELECT 'placeholder'`.
_GIVE_UP_PATTERNS = [
    re.compile(r"^select\s+1(\s+as\s+\w+)?$"),
    re.compile(r"^select\s+'?(test|placeholder|todo|n/?a|tbd)'?(\s+as\s+\w+)?$"),
    re.compile(r"^select\s+null(\s+as\s+\w+)?$"),
]


def detect_give_up_sql(sql: str) -> bool:
    """Returns True if SQL is a placeholder like `SELECT 1 AS test`.

    A `SELECT 1` issued as a refusal for a destructive request (DELETE/UPDATE/etc)
    is a different scenario — the runner's robustness evaluator handles those.
    This guard is for non-robustness questions where SELECT 1 leaks through as
    a give-up signal from the agent loop.
    """
    if not sql:
        return False
    s = sql.strip().rstrip(";").strip()
    # collapse whitespace
    s = re.sub(r"\s+", " ", s).lower()
    # strip trailing LIMIT N (the postprocessor injects LIMIT 100000 universally)
    s = re.sub(r"\s+limit\s+\d+\s*$", "", s)
    # strip a parenthesized subquery wrapper if present
    s = re.sub(r"^select\s+\*\s+from\s*\(\s*", "", s)
    s = re.sub(r"\s*\)\s*(?:as\s+\w+\s*)?$", "", s)
    for pat in _GIVE_UP_PATTERNS:
        if pat.match(s):
            return True
    return False


# ----------------------------------------------------------------------------
# Hallucinated table-name detection (bucket F)
# ----------------------------------------------------------------------------

# These substrings, if they appear in a FROM/JOIN target, indicate the model
# tried to use a file path or cache key as a table name.
_HALLUCINATED_TOKENS = ("/", "\\", ".csv", "query_result_", "uploads")


def detect_hallucinated_table_name(
    sql: str, allowed_tables: set[str] | None = None
) -> str | None:
    """Returns the offending hallucinated table name, or None.

    Two failure modes covered:
      1. File-path-shaped tokens: any FROM/JOIN target containing slash,
         backslash, .csv, "query_result_", or "uploads".
      2. (When allowed_tables is provided) tokens not in the allow-list.

    Subqueries `FROM (...)`, CTE references, and quoted lower-case identifiers
    are not flagged.
    """
    if not sql:
        return None

    # Two-stage tokenization:
    # 1) Scan FROM/JOIN positions
    # 2) For each, capture the *next token*, which is either:
    #    - a quoted identifier "..."  (may contain anything except inner ")
    #    - a backquoted identifier `...`
    #    - a bare identifier (letters/digits/_/.)
    #    Subqueries `(` are skipped.
    targets: list[str] = []
    for m in re.finditer(r"\b(?:from|join)\s+", sql, re.IGNORECASE):
        rest = sql[m.end():]
        # Skip subqueries
        if rest.lstrip().startswith("("):
            continue
        # Quoted identifier
        if rest.startswith('"'):
            end = rest.find('"', 1)
            if end > 0:
                targets.append(rest[1:end])
            continue
        if rest.startswith("`"):
            end = rest.find("`", 1)
            if end > 0:
                targets.append(rest[1:end])
            continue
        # Bare identifier — letters / digits / _ / . / / / \ / -
        # (we deliberately include the dangerous chars so we can detect them)
        bare_match = re.match(r"[\w./\\\-]+", rest)
        if bare_match:
            targets.append(bare_match.group(0))

    for tok in targets:
        lo = tok.lower()
        if any(bad in lo for bad in _HALLUCINATED_TOKENS):
            return tok
        if allowed_tables:
            # Strip schema prefix: public.cq_buildings_2021 → cq_buildings_2021
            bare = tok
            if "." in tok:
                head, _, tail = tok.partition(".")
                if head.lower() == "public":
                    bare = tail
            if bare not in allowed_tables and tok not in allowed_tables:
                return tok
    return None


# ----------------------------------------------------------------------------
# Composite gate
# ----------------------------------------------------------------------------


def is_safe_sql(
    sql: str, allowed_tables: set[str] | None = None
) -> tuple[bool, str]:
    """Composite check: returns (ok, reason).

    Reasons when ok=False:
      - "give_up_placeholder" — bucket G
      - "hallucinated_table:<name>" — bucket F

    Use as the last gate before sending SQL to query_database. On rejection
    the runner can record the original SQL with valid=0 reason=<label>, OR
    optionally re-prompt the model for a corrected SQL.
    """
    if detect_give_up_sql(sql):
        return False, "give_up_placeholder"
    halluc = detect_hallucinated_table_name(sql, allowed_tables)
    if halluc:
        return False, f"hallucinated_table:{halluc}"
    return True, "ok"
