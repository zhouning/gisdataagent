"""Conservative PostgreSQL ranking commitments derived from the question.

No database names, expected answers, or benchmark examples belong here. This
pass does not choose the measure or entity: it corrects only missing-value
ordering and ties in an already grouped single-measure extremum. Source and
read-only guards remain the executor's responsibility after this pass.
"""
from __future__ import annotations

import os
import re


_RANKING = re.compile(
    r"\b(highest|lowest|largest|smallest|greatest|least|most|fastest|slowest|"
    r"shortest|longest|oldest|youngest|earliest|latest|maximum|minimum|top)\b"
    r"|最高|最低|最大|最小|最多|最少|最早|最晚|最短|最长", re.I)
_NUMBER = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|hundred)"
_BOUNDED = re.compile(
    rf"\b(?:top|first|last|only|exactly|at\s+(?:least|most))\s+{_NUMBER}\b"
    rf"|\b{_NUMBER}\s+(?:highest|lowest|largest|smallest|best|worst|shortest|longest)\b"
    r"|\b(?:one|single)\s+(?:row|record|result|entry|example)\b"
    r"|(?:前|后|仅|只要|只列|只返回)\s*[0-9一二三四五六七八九十百]+", re.I)
_NULL_REQUEST = re.compile(r"\b(?:null|missing|unknown|unavailable)\b|缺失|空值|未知", re.I)
_ORDINAL = r"(?:[1-9]\d{0,3}(?:st|nd|rd|th))"
_ORDINAL_SELECTION = re.compile(
    rf"(?P<selection>\b{_ORDINAL}(?:\s*(?:,|and|to|through|[-–])\s*{_ORDINAL})*)"
    r"\s+(?:(?:highest|lowest|largest|smallest|fastest|slowest|oldest|youngest)\b"
    r"|[a-z]+s\s+(?:with\s+the\s+|ranked\s+)(?:highest|lowest|largest|smallest|most|least)\b)", re.I)


def ordinal_result_slice(question: str) -> tuple[int, int] | None:
    """Recognize contiguous positions in an explicit ranking, not top-N.

    Keep ambiguous/disjoint positions, ordinal labels and per-group requests
    unchanged. This never chooses an ordering column or direction.
    """
    text = re.sub(r"(['\"]).*?\1", "", question or "")
    if re.search(r"\b(?:not|except|excluding|exclude|without|or)\b", text, re.I) or _BOUNDED.search(text):
        return None
    if re.search(r"\b(?:each|every|per|respective)\b|每(?:个|组|类)|各组", text, re.I):
        return None
    matches = list(_ORDINAL_SELECTION.finditer(text))
    if len(matches) != 1:
        return None
    selection = matches[0].group("selection")
    numbers = [int(re.match(r"\d+", value).group()) for value in re.findall(_ORDINAL, selection, re.I)]
    if len(numbers) != len(re.findall(_ORDINAL, text, re.I)):
        return None
    if len(numbers) == 2 and re.search(r"\b(?:to|through)\b|[-–]", selection, re.I):
        if numbers[1] < numbers[0]:
            return None
        return numbers[1] - numbers[0] + 1, numbers[0] - 1
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return None
    return len(numbers), numbers[0] - 1


def grouped_extremum_ties_enabled() -> bool:
    value = os.environ.get("GDA_NL2SQL_GROUPED_EXTREMUM_TIES", "0").strip().casefold()
    if value in {"0", "false", "off", "no", ""}:
        return False
    if value in {"1", "true", "on", "yes"}:
        return True
    raise ValueError("GDA_NL2SQL_GROUPED_EXTREMUM_TIES must be a boolean")


def apply_ranking_contract(question: str, sql: str, *, include_grouped_ties: bool | None = None) -> tuple[str, list[str]]:
    import sqlglot
    from sqlglot import exp

    if include_grouped_ties is None:
        include_grouped_ties = grouped_extremum_ties_enabled()
    if not _RANKING.search(question or ""):
        return sql, []
    try:
        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return sql, []
        tree = statements[0]
        order = tree.args.get("order")
        limit = tree.args.get("limit")
        requested_slice = ordinal_result_slice(question)
        if not order or (not requested_slice and (not limit or tree.args.get("offset"))):
            return sql, []
        # Inner rankings can implement a different population or time scope.
        # Only the outer answer's primary rank is changed.
        primary = order.expressions[0]
        if isinstance(primary.this, (exp.Boolean, exp.Predicate)):
            return sql, []
        corrections = []
        if requested_slice:
            # A window can implement a separate ranking population. Do not
            # replace its bounds using an outer LIMIT/OFFSET.
            if any(tree.find_all(exp.Window)):
                return sql, []
            offset = tree.args.get("offset")
            if any(bound and (not isinstance(bound.expression, exp.Literal)
                              or bound.expression.is_string or not bound.expression.this.isdigit())
                   for bound in (limit, offset)):
                return sql, []
            count, start = requested_slice
            current_count = int(limit.expression.this) if limit else None
            current_start = int(offset.expression.this) if offset else 0
            if (current_count, current_start) != (count, start):
                tree.set("limit", exp.Limit(expression=exp.Literal.number(count)))
                tree.set("offset", exp.Offset(expression=exp.Literal.number(start)) if start else None)
                limit = tree.args["limit"]
                corrections.append("ranking_explicit_ordinal_slice")
        if not _NULL_REQUEST.search(question) and primary.args.get("nulls_first") is True:
            primary.set("nulls_first", False)
            corrections.append("ranking_known_values_before_nulls")
        if (include_grouped_ties and tree.args.get("group") and len(order.expressions) == 1
                and not requested_slice and not _BOUNDED.search(question) and isinstance(limit, exp.Limit)
                and isinstance(limit.expression, exp.Literal) and not limit.expression.is_string
                and limit.expression.this == "1"):
            tree.set("limit", exp.Fetch(direction="FIRST", count=exp.Literal.number(1),
                limit_options=exp.LimitOptions(rows=True, with_ties=True)))
            corrections.append("ranking_preserve_grouped_extremum_ties")
        return (tree.sql(dialect="postgres"), corrections) if corrections else (sql, [])
    except sqlglot.errors.SqlglotError:
        return sql, []
