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
from .nl2sql_observability import observe_stage

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
_GOVERNED_TABLE_FUNCTIONS = {"jsonb_array_elements"}


def _extract_cte_names(sql: str) -> set[str]:
    """Best-effort extraction of WITH-query CTE aliases."""
    if not sql:
        return set()
    try:
        import sqlglot
        import sqlglot.expressions as exp

        parsed = sqlglot.parse_one(sql, dialect="postgres")
        if parsed is None:
            return set()
        return {cte.alias for cte in parsed.find_all(exp.CTE) if cte.alias}
    except Exception:
        names: set[str] = set()
        for cte_match in re.finditer(
            r"(?:\bWITH\b|,)\s*(?P<name>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(",
            sql,
            re.IGNORECASE,
        ):
            names.add(cte_match.group("name").strip('"'))
        return names


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
    cte_names = _extract_cte_names(sql)
    for m in re.finditer(r"\b(?:from|join)\s+", sql, re.IGNORECASE):
        # EXTRACT(YEAR FROM expression) uses FROM as an expression separator.
        if re.search(
            r"\bextract\s*\(\s*(?:year|month|day|hour|minute|second|epoch)\s*$",
            sql[: m.start()],
            re.IGNORECASE,
        ):
            continue
        # ``FROM`` is also part of PostgreSQL's null-safe comparison syntax.
        # It does not introduce a relation and must not enter the table
        # allow-list check.
        if re.search(
            r"\bis\s+(?:not\s+)?distinct\s*$",
            sql[: m.start()],
            re.IGNORECASE,
        ):
            continue
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
        if lo == "lateral":
            continue
        if tok in cte_names or lo in {name.lower() for name in cte_names}:
            continue
        # PostgreSQL table-valued functions are not physical tables. They are
        # admitted only by the semantic SQL validator; this guard merely must
        # not misclassify the compiler/model's governed JSONB array function
        # as a hallucinated table name.
        function_name = lo.split("(", 1)[0]
        if function_name in _GOVERNED_TABLE_FUNCTIONS:
            continue
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


_PRIVILEGED_SQL_FUNCTIONS = frozenset({
    "pg_read_file", "pg_read_binary_file", "pg_stat_file", "pg_ls_dir",
    "pg_write_file", "pg_file_write", "pg_file_rename", "pg_file_unlink",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile",
    "pg_notify", "pg_sleep", "pg_sleep_for", "pg_sleep_until", "set_config",
    "lo_import", "lo_export", "lo_unlink",
})


def detect_privileged_sql_function(sql: str) -> str | None:
    """Reject administrative calls in query drafts, including nested calls.

    Inspect function nodes, never words in comments, strings or field names.
    Database read-only transactions and least-privilege roles remain required.
    """
    import sqlglot
    from sqlglot import exp

    try:
        for statement in sqlglot.parse(sql, read="postgres"):
            if statement is None:
                continue
            for function in statement.find_all(exp.Func):
                name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
                name = name.casefold()
                if (name in _PRIVILEGED_SQL_FUNCTIONS or name.startswith("dblink")
                        or name.startswith("pg_advisory_") or name.startswith("pg_ls_")):
                    return name
    except sqlglot.errors.SqlglotError:
        pass  # The SQL parser and execution adapter own syntax rejection.
    return None


@observe_stage("query.runtime_guard", rejected_when=lambda result: not result[0])
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
    from .nl2sql_metric_compiler import contains_metric_slots
    if contains_metric_slots(sql):
        return False, "uncompiled_semantic_metric"
    privileged = detect_privileged_sql_function(sql)
    if privileged:
        return False, f"privileged_function:{privileged}"
    if detect_give_up_sql(sql):
        return False, "give_up_placeholder"
    halluc = detect_hallucinated_table_name(sql, allowed_tables)
    if halluc:
        return False, f"hallucinated_table:{halluc}"
    return True, "ok"
