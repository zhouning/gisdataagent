"""Governed, bounded content-presence conditions, independent of model plans.

A registered field meaning and an explicit product NULL policy are required.
Only affirmative content filters and direct IS NOT NULL proofs are supported.
No SQL is rewritten, no reference answers are read, and no calls are made.
"""
from __future__ import annotations

import hashlib
import json
import re

from sqlglot import exp
import sqlglot


def presence_catalog(payload: dict) -> list[dict]:
    result = []
    for table in payload.get("candidate_tables") or []:
        for column in table.get("columns") or []:
            rule = (column.get("value_semantics") or {}).get("value_presence")
            if rule is None:
                continue
            provenance = (rule.get("provenance") or {}) if isinstance(rule, dict) else {}
            if (not isinstance(rule, dict) or rule.get("version") != 1
                    or set(rule) != {"version", "present_when", "meaning", "request_terms", "provenance"}
                    or rule.get("present_when") != "not_null"
                    or not isinstance(rule.get("meaning"), str) or not rule["meaning"].strip()
                    or not isinstance(rule.get("request_terms"), list) or not rule["request_terms"]
                    or not all(isinstance(t, str) and t.strip() and len(t) <= 80 for t in rule["request_terms"])
                    or not isinstance(provenance, dict)
                    or not str(provenance.get("url", "")).startswith("https://")
                    or not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("artifact_sha256", "")))):
                raise ValueError("invalid_registered_value_presence_contract")
            result.append({**rule, "field_id": table["table_name"] + "." + column["column_name"],
                           "table": table["table_name"], "column": column["column_name"],
                           "contract_sha256": hashlib.sha256(
                               json.dumps(rule, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
    return result


def requested_value_presence(question: str, payload: dict) -> list[dict]:
    """Recognize a small affirmative grammar; keep competing fields ambiguous.

    Modifiers (e.g. a language adjective) are opaque question text, never a
    source of fixed filter values. Negation, disjunction and optional annotations
    are outside this grammar and do not become mandatory population filters.
    """
    requests = []
    for rule in presence_catalog(payload):
        quotes = set()
        for term in rule["request_terms"]:
            term = term.strip()
            if re.search(r"[\u4e00-\u9fff]", term):
                pattern = r"(?:具有|拥有|含有|有)(?:[\u4e00-\u9fff]{0,6})" + re.escape(term)
            else:
                pattern = (r"\b(?:has|have|having|with)\s+(?:(?:a|an|the)\s+)?"
                           r"(?:[\w-]+\s+){0,2}" + re.escape(term) + r"(?!\w)")
            for match in re.finditer(pattern, question or "", re.I):
                prefix = (question or "")[:match.start()]
                clause = re.split(r"[.;!?。；！？]", prefix)[-1]
                suffix = (question or "")[match.end():]
                tail = re.split(r"[.;!?。；！？]", suffix)[0]
                if (re.search(r"\b(?:or|whether)\b|或者|是否", tail, re.I)
                        or re.match(r"\s+(?:history|records?|rows?|logs?|status|table)\b|记录|历史", suffix, re.I)):
                    continue
                if re.search(r"\b(?:not|no|without|whether|if|or|mark|flag|indicate)\b|没|无|不|是否|标记|标注|或者", clause, re.I):
                    continue
                if re.search(r"\b(?:no|not|missing|any|or|and|whether|if)\b|没有|无|不|是否|或者", match.group(), re.I):
                    continue
                quotes.add(match.group())
        if quotes:
            requests.append({**rule, "source_quotes": sorted(quotes)})
    return requests


def value_presence_guidance(requests: list[dict]) -> str:
    if not requests:
        return ""
    return ("\nGoverned content-presence requests (independent of your answer plan):\n"
            "A detail row existing does not prove its content exists. present_when=not_null "
            "requires IS NOT NULL on the specified content field in the SAME qualifying row, "
            "with any requested language/category conditions. Empty strings remain present under "
            "this policy; do not invent a nonblank condition. Use a direct conjunctive WHERE "
            "predicate, in the main query or a directly correlated positive EXISTS. Other SQL "
            "proof shapes are not supported. Competing field meanings require clarification.\n"
            + json.dumps([{k: r[k] for k in ("field_id", "meaning", "present_when", "source_quotes",
                                             "contract_sha256")} for r in requests], ensure_ascii=False) + "\n")


def audit_value_presence(sql: str, question: str, payload: dict) -> dict:
    requests = requested_value_presence(question, payload)
    audit = {"status": "not_applicable", "requests": requests, "findings": [],
             "coverage": [], "limitations": "Proves a necessary non-NULL condition only, not qualifier values, absence of extra filters, or full question interpretation."}
    if not requests:
        return audit

    def fail(reason, status="unverified"):
        return {**audit, "status": status, "findings": [{"reason": reason}]}

    # The same literal content phrase cannot choose between two meanings.
    for request in requests:
        if any(set(request["source_quotes"]) & set(other["source_quotes"])
               for other in requests if other["field_id"] != request["field_id"]):
            return fail("value_presence_field_ambiguous")
    from .nl2sql_relational_bindings import _Sources, _AuditStop, _conjuncts
    from .nl2sql_relationship_retrieval import relationship_catalog
    tables = {t["table_name"]: t for t in payload.get("candidate_tables") or []}
    fields = {t["table_name"] + "." + c["column_name"]: c for t in tables.values() for c in t.get("columns") or []}
    try:
        trees = sqlglot.parse(sql, read="postgres")
        if len(trees) != 1 or not isinstance(trees[0], exp.Select):
            return fail("value_presence_query_shape_unsupported")
        query = trees[0]
        if query.args.get("with_") or any(query.find_all(exp.Subquery, exp.Window)):
            return fail("value_presence_query_shape_unsupported")
        outer = _Sources(query, tables, fields)
        scopes = [outer]
        where = query.args.get("where")
        for predicate in _conjuncts(where.this) if where else []:
            if not isinstance(predicate, exp.Exists):
                if any(predicate.find_all(exp.Select)):
                    return fail("value_presence_membership_shape_unsupported")
                continue
            child = predicate.this
            if (not isinstance(child, exp.Select) or child.args.get("joins")
                    or any(child.args.get(k) for k in ("with_", "group", "having", "limit", "offset", "qualify"))
                    or any(child.find_all(exp.AggFunc)) or len(list(child.find_all(exp.Select))) != 1):
                return fail("value_presence_membership_shape_unsupported")
            inner = _Sources(child, tables, fields, outer)
            # A true but uncorrelated EXISTS says nothing about this entity.
            relations = relationship_catalog(payload.get("candidate_tables") or [])
            edges = {frozenset((r["source_table"] + "." + r["source_field"],
                                r["target_table"] + "." + r["target_field"])) for r in relations}
            correlated = False
            child_where = child.args.get("where")
            for condition in _conjuncts(child_where.this) if child_where else []:
                if not isinstance(condition, exp.EQ) or not all(isinstance(c.unnest(), exp.Column)
                        for c in (condition.this, condition.expression)):
                    continue
                left, right = inner.ref(condition.this.unnest()), inner.ref(condition.expression.unnest())
                if (bool(left[0] in inner.aliases) != bool(right[0] in inner.aliases)
                        and frozenset((left[1], right[1])) in edges):
                    correlated = True
            if not correlated:
                return fail("value_presence_membership_not_registered_correlation")
            scopes.append(inner)
        if {id(s.query) for s in scopes} != {id(q) for q in query.find_all(exp.Select)}:
            return fail("value_presence_nested_query_unsupported")
        for request in requests:
            candidates = [(s, a) for s in scopes for a, t in s.aliases.items() if t == request["table"]]
            if len(candidates) != 1:
                return fail("value_presence_source_missing_or_ambiguous")
            scope, alias = candidates[0]
            where = scope.query.args.get("where")
            proven = False
            for condition in _conjuncts(where.this) if where else []:
                predicate = condition.this.unnest() if isinstance(condition, exp.Not) else condition
                # sqlglot versions encode IS NOT either with Is.negate or
                # with an enclosing Not. A double negation proves absence.
                negated = isinstance(condition, exp.Not) != bool(predicate.args.get("negate"))
                if (not negated or not isinstance(predicate, exp.Is)
                        or not isinstance(predicate.expression, exp.Null)):
                    continue
                column = predicate.this.unnest()
                if isinstance(column, exp.Column) and scope.ref(column) == (alias, request["field_id"]):
                    proven = True
            if not proven:
                return fail("required_content_value_not_proven_present", "violation")
        return {**audit, "status": "verified", "coverage": ["required_nonnull_predicate_on_qualifying_source"]}
    except (sqlglot.errors.SqlglotError, _AuditStop, ValueError, KeyError, TypeError):
        return fail("value_presence_scope_unresolved")
