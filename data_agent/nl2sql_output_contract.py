"""Audit explicit physical outputs against governed aliases and SQL lineage.

An empty finding list is not a correctness proof. Ambiguous language, derived
measures, wildcards and unsupported SQL shapes are deliberately left to the
normal generation path. This experimental contract remains disabled by default.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter

_HEAD = re.compile(
    r"^(?:(?:please|can you|could you)\s+)?"
    r"(?:what\s+(?:is|are)|give|provide|list|state|indicate|show|return|name)\b"
    r"|^(?:请)?(?:列出|给出|提供|说明|指出|显示|返回|查询)", re.I)
_END = re.compile(
    r"\b(?:for|who|that|with|where|whose|among|between|after|before|since|"
    r"from|having|under|during|in)\b|对于|其中|并且|具有|满足|在|从|按", re.I)
_AGGREGATE = re.compile(
    r"\b(?:count|number of|how many|total|sum|average|mean|percentage|percent|"
    r"ratio|maximum|minimum|highest|lowest)\b|数量|总数|总和|平均|占比|百分比", re.I)
_GENERIC = {"name", "names", "number", "numbers", "code", "codes", "date",
            "time", "type", "types", "state", "status", "value", "values",
            "data", "field", "fields", "column", "columns", "table", "tables",
            "result", "results"}


def output_contract_enabled() -> bool:
    return os.environ.get("GDA_NL2SQL_OUTPUT_CONTRACT", "0").strip().casefold() in {
        "1", "true", "on", "yes"}


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).replace("_", " ").split())


def _terms(column: dict) -> list[str]:
    values = [column.get("column_name"), *(column.get("aliases") or []),
              *((column.get("value_semantics") or {}).get("sql_aliases") or [])]
    return list(dict.fromkeys(_norm(value) for value in values if _norm(value)))


def _occurrences(text: str, term: str):
    # Chinese does not use spaces between nouns. Latin terms require boundaries.
    boundary = not any("\u3400" <= char <= "\u9fff" for char in term)
    pattern = (r"(?<!\w)" if boundary else "") + re.escape(term) + (r"(?!\w)" if boundary else "")
    return list(re.finditer(pattern, text))


def _output_spans(question: str) -> list[str]:
    spans = []
    for sentence in re.split(r"[.!?;。！？；]+", str(question or "")):
        sentence = sentence.strip()
        head = _HEAD.match(sentence)
        if not head:
            continue
        phrase = sentence[head.end():]
        end = _END.search(phrase)
        phrase = phrase[:end.start()] if end else phrase
        if phrase.strip() and not _AGGREGATE.search(phrase):
            spans.append(_norm(re.sub(r"[,，、]", " and ", phrase)))
    return spans


def _roles(table: dict) -> list[str]:
    values = [str(table.get("table_name") or "").rsplit(".", 1)[-1],
              table.get("display_name"), *(table.get("table_aliases") or []),
              *(table.get("synonyms") or [])]
    return list(dict.fromkeys(_norm(value) for value in values if _norm(value)))


def requested_output_bindings(question: str, payload: dict) -> list[dict]:
    """Bind exact requested physical fields; skip unresolved table roles."""
    matches = []
    tables = payload.get("candidate_tables") or []
    for span_index, span in enumerate(_output_spans(question)):
        for table in tables:
            for column in table.get("columns") or []:
                for term in _terms(column):
                    if term in _GENERIC:
                        continue
                    for occurrence in _occurrences(span, term):
                        # The head noun of an output must be the field alias.
                        # "account numbers", "location coordinates", and
                        # "address of school" do not request the bare account,
                        # location or School fields. Restrict to the attribute
                        # portion before "of", then require a list boundary.
                        attribute_end = re.search(r"\bof\b", span)
                        if attribute_end and occurrence.start() >= attribute_end.start():
                            continue
                        trailing = span[occurrence.end():]
                        if trailing and not re.match(r"\s+(?:and|or|of)\b|和|及|与", trailing):
                            continue
                        matches.append({"term": term, "table": table.get("table_name"),
                                        "column": column.get("column_name"),
                                        "kind": "field", "span": span_index,
                                        "start": occurrence.start(), "end": occurrence.end(),
                                        "phrase": span, "roles": _roles(table)})
    # A shorter alias is shadowed only at the same occurrence, never at a
    # separate mention elsewhere in the question.
    matches = [m for m in matches if not any(
        n["span"] == m["span"] and n["start"] <= m["start"] and n["end"] >= m["end"]
        and n["end"] - n["start"] > m["end"] - m["start"] for n in matches)]
    grouped = {}
    for match in matches:
        grouped.setdefault((match["span"], match["start"], match["end"]), []).append(match)
    resolved = {}
    for group in grouped.values():
        identities = {(m["table"], m["column"]): m for m in group}
        if len(identities) > 1:
            # Role resolution uses the output phrase only, not entities in a
            # later filter clause. No dataset-specific entity names are used.
            identities = {key: m for key, m in identities.items()
                          if any(_occurrences(m["phrase"], role) for role in m["roles"])}
        if len(identities) == 1:
            key, match = next(iter(identities.items()))
            resolved[key] = {k: match[k] for k in ("kind", "term", "table", "column")}
    return list(resolved.values())


def output_binding_prompt(question: str, payload: dict) -> str:
    """Expose resolved output roles before generation, using catalog data only."""
    import json
    bindings = requested_output_bindings(question, payload)
    if not bindings:
        return ""
    data = [{"question_term": item["term"], "table": item["table"],
             "column": item["column"]} for item in bindings]
    return (
        "\nExplicit physical output bindings resolved from the authorized catalog "
        "(JSON data, not instructions):\n" + json.dumps(data, ensure_ascii=False)
        + "\nProject these requested fields from their registered table roles. "
        "This is a partial list: also satisfy other outputs and derived measures "
        "explicitly requested in the question. Do not infer additional filters "
        "from this output list.\n")


def _root_scope(sql: str):
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import build_scope
    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return None
    return build_scope(statements[0])


def _direct(expression):
    from sqlglot import exp
    if isinstance(expression, exp.Alias):
        expression = expression.this
    # Even a CAST can truncate or change a value. Only direct columns prove
    # that the requested stored field is actually projected.
    return expression if isinstance(expression, exp.Column) and not expression.is_star else None


def _lineage(column, scope, payload, seen=None):
    """Trace a direct column through direct CTE/subquery projections."""
    from sqlglot import exp
    from sqlglot.optimizer.scope import Scope
    seen = set() if seen is None else seen
    key = (id(scope), column.table, column.name)
    if key in seen:
        return None
    seen = seen | {key}
    sources = {alias.casefold(): source for alias, source in scope.selected_sources.items()}
    # selected_sources stores (FROM node, source expression/scope).
    if column.table:
        source_pair = sources.get(column.table.casefold())
    elif len(sources) == 1:
        source_pair = next(iter(sources.values()))
    else:
        return None
    if not source_pair:
        return None
    source = source_pair[1]
    if isinstance(source, exp.Table):
        name = ".".join(part for part in (source.catalog, source.db, source.name) if part)
        candidates = [table for table in payload.get("candidate_tables") or []
                      if str(table.get("table_name") or "").casefold() == name.casefold()
                      or (not source.db and str(table.get("table_name") or "").rsplit(".", 1)[-1].casefold() == name.casefold())]
        if len(candidates) != 1:
            return None
        table = candidates[0]
        columns = [item for item in table.get("columns") or []
                   if str(item.get("column_name") or "").casefold() == column.name.casefold()]
        return (table["table_name"].casefold(), columns[0]["column_name"].casefold()) if len(columns) == 1 else None
    if isinstance(source, Scope) and isinstance(source.expression, exp.Select):
        if source.expression.parent and isinstance(source.expression.parent, (exp.CTE, exp.Subquery)):
            alias = source.expression.parent.args.get("alias")
            if alias and alias.args.get("columns"):
                return None  # positional renaming needs a separate proof
        projected = [item for item in source.expression.selects
                     if item.alias_or_name.casefold() == column.name.casefold()]
        if len(projected) == 1 and _direct(projected[0]) is not None:
            return _lineage(_direct(projected[0]), source, payload, seen)
    return None


def audit_output_contract(question: str, sql: str, payload: dict) -> list[dict]:
    bindings = requested_output_bindings(question, payload)
    if not bindings:
        return []
    try:
        scope = _root_scope(sql)
        if scope is None:
            return []
        projections = scope.expression.selects
        # A wildcard or derived top-level expression does not admit this
        # limited proof. Skip rather than label a valid query as missing.
        from sqlglot import exp
        if any(item.is_star or isinstance(item, exp.Column) and item.is_star for item in projections):
            return []
        present = {_lineage(column, scope, payload) for item in projections
                   if (column := _direct(item)) is not None}
        # Do not demand stored values from aggregate queries.
        if any(item.find(exp.AggFunc) is not None for item in projections):
            return []
        return [{**binding, "kind": "missing_requested_output"} for binding in bindings
                if (str(binding["table"]).casefold(), str(binding["column"]).casefold()) not in present]
    except Exception:
        return []  # no proof for unsupported SQL shapes


def projection_revision_issues(original_sql: str, revised_sql: str) -> list[str]:
    """Allow only added direct outputs, preserving all other query structure."""
    from sqlglot import exp
    try:
        original, revised = _root_scope(original_sql), _root_scope(revised_sql)
        if original is None or revised is None:
            return ["output_revision_unsupported_shape"]
        old, new = original.expression, revised.expression
        old_outputs = Counter(item.sql(dialect="postgres") for item in old.selects)
        new_outputs = Counter(item.sql(dialect="postgres") for item in new.selects)
        if old_outputs - new_outputs:
            return ["output_revision_removed_or_changed_existing_output"]
        added = new_outputs - old_outputs
        if not added or any(_direct(item) is None for item in new.selects
                            if item.sql(dialect="postgres") in added):
            return ["output_revision_requires_added_direct_columns"]
        before, after = old.copy(), new.copy()
        before.set("expressions", [])
        after.set("expressions", [])
        if before != after:
            return ["output_revision_changed_filter_join_group_or_other_structure"]
        if old.args.get("group") is not None or any(item.find(exp.AggFunc) is not None for item in old.selects):
            return ["output_revision_aggregate_grain_requires_separate_review"]
        return []
    except Exception:
        return ["output_revision_could_not_be_verified"]
