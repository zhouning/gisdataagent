"""Check declared relationship and entity contracts against executable SQL.

Only explicit INNER/LEFT joins and conjunctive, correlated EXISTS membership
are supported. Agreement proves SQL commitments, never question interpretation
or the meaning of local value predicates. No SQL or model calls are made here.
"""
from __future__ import annotations

from collections import Counter
import json
import os

from sqlglot import exp
from sqlglot.optimizer.scope import build_scope


def relational_bindings_enabled() -> bool:
    value = os.environ.get("GDA_NL2SQL_RELATIONAL_BINDINGS", "0").strip().casefold()
    if value not in {"0", "false", "off", "no", "", "1", "true", "on", "yes"}:
        raise ValueError("GDA_NL2SQL_RELATIONAL_BINDINGS must be a boolean")
    return value in {"1", "true", "on", "yes"}


def relational_schema() -> dict:
    def obj(properties):
        return {"type": "object", "additionalProperties": False,
                "properties": properties, "required": list(properties)}
    string = {"type": "string", "minLength": 1}
    edge = {"relationship_id": string, "source_alias": string, "target_alias": string}
    return obj({
        "version": {"const": 1},
        "joins": {"type": "array", "maxItems": 30, "items": obj({**edge,
            "joined_alias": string, "join_type": {"enum": ["inner", "left"]}, "source_quote": string})},
        "memberships": {"type": "array", "maxItems": 10, "items": obj({
            "source_quote": string, "polarity": {"enum": ["exists", "not_exists"]},
            "relations": {"type": "array", "minItems": 1, "maxItems": 30, "items": obj(edge)},
        })},
        "result_grain": obj({
            "kind": {"enum": ["joined_rows", "entity_rows", "aggregate"]},
            "source_quote": string, "table_id": {"type": ["string", "null"]},
            "alias": {"type": ["string", "null"]},
            "identity_field_ids": {"type": "array", "uniqueItems": True, "items": string},
        }),
    })


def relational_prompt(catalog: dict) -> str:
    return (
        "\nRelational contract version 1: declare every actual JOIN edge with its full relationship_id, "
        "exact SQL source_alias/target_alias, joined_alias and inner/left join_type. Aliases retain "
        "quoted case; unquoted aliases are lowercase. Quote the requested role verbatim from the question. "
        "memberships lists each top-level conjunctive EXISTS or NOT EXISTS: declare its polarity and "
        "all registered relation edges, including the correlation to the outer entity and internal bridge "
        "joins. Use SELECT 1 in these subqueries, explicit inner bridge joins, no alias shadowing, "
        "aggregation, ordering, nesting, LIMIT/OFFSET or OR around membership. Never replace absence with a "
        "nonmatching detail row. For entity_rows, bind the exact table, SQL alias and complete registered "
        "primary-key field IDs. Avoid detail fanout via EXISTS or key-preserving joins; DISTINCT on "
        "display values alone can collapse different entities. Entity lists support physical-column "
        "outputs only; repeated physical tables in the outer scope need alias-aware output bindings "
        "and are not yet verified. joined_rows/aggregate use null table_id "
        "and alias, and empty identity_field_ids. CTEs, preaggregation and denominator populations "
        "are not verified by this bounded contract; record unsupported intent as unresolved. "
        "These bindings share the existing plan+SQL response; no second review call.\n"
        "Authorized relationship IDs and roles: "
        + json.dumps(catalog["relationships"], ensure_ascii=False) + "\n"
    )


def validate_relational_selection(contract: dict, question: str, catalog: dict) -> None:
    relations = {r["id"]: r for r in catalog["relationships"]}
    for item in [*contract["joins"], *contract["memberships"], contract["result_grain"]]:
        if item["source_quote"] not in question:
            raise ValueError("relational_binding_quote_not_in_question")
    edges = [*contract["joins"], *(r for m in contract["memberships"] for r in m["relations"])]
    for edge in edges:
        if edge["relationship_id"] not in relations:
            raise ValueError("relationship_outside_authorized_catalog")
        if edge["source_alias"] == edge["target_alias"]:
            raise ValueError("relationship_requires_distinct_aliases")
    grain = contract["result_grain"]
    if grain["kind"] == "entity_rows":
        fields = {f: v for f, v in catalog["fields"].items() if v["table"] == grain["table_id"]}
        if not fields or not grain["alias"]:
            raise ValueError("entity_grain_outside_authorized_catalog")
        primary = next(iter(fields.values()))["primary_keys"]
        expected = {grain["table_id"] + "." + key for key in primary}
        if not expected or not expected <= fields.keys() or expected != set(grain["identity_field_ids"]):
            raise ValueError("entity_grain_requires_complete_authorized_primary_key")
    elif grain["table_id"] is not None or grain["alias"] is not None or grain["identity_field_ids"]:
        raise ValueError("non_entity_grain_has_entity_binding")


class _AuditStop(ValueError):
    def __init__(self, reason, status="unverified"):
        super().__init__(reason)
        self.status = status


def _identifier(node) -> str:
    return node.name if node.args.get("quoted") else node.name.lower()


def _conjuncts(expression):
    expression = expression.unnest()
    if isinstance(expression, exp.And):
        return [*_conjuncts(expression.this), *_conjuncts(expression.expression)]
    return [expression]


class _Sources:
    def __init__(self, query, tables, fields, parent=None):
        self.query, self.tables, self.fields, self.parent = query, tables, fields, parent
        self.aliases = {}
        self.scope = build_scope(query)
        if self.scope is None:
            raise _AuditStop("relationship_scope_missing")
        for _, (_, source) in self.scope.selected_sources.items():
            table = self.physical(source)
            if table is None:
                raise _AuditStop("relationship_source_unresolved")
            alias = _identifier(source.args["alias"].this if source.args.get("alias") else source.this)
            if parent and alias in parent.aliases:
                raise _AuditStop("membership_alias_shadowing_unsupported")
            if alias in self.aliases:
                raise _AuditStop("duplicate_source_alias_unsupported")
            self.aliases[alias] = table
        if not self.aliases:
            raise _AuditStop("relationship_source_missing")

    def physical(self, source):
        if (not isinstance(source, exp.Table) or source.catalog or
                source.args.get("alias") and source.args["alias"].args.get("columns")):
            return None
        name = _identifier(source.this)
        schema = _identifier(source.args["db"]) if source.db else None
        matches = [t for t in self.tables if t == schema + "." + name] if schema else [
            t for t in self.tables if t.rsplit(".", 1)[-1] == name]
        return matches[0] if len(matches) == 1 else None

    def ref(self, column):
        if column.is_star or column.catalog:
            raise _AuditStop("relationship_field_lineage_unsupported")
        name = _identifier(column.this)
        qualifier = _identifier(column.args["table"]) if column.table else None
        if qualifier:
            if qualifier not in self.aliases:
                if self.parent:
                    return self.parent.ref(column)
                raise _AuditStop("relationship_field_unavailable")
            candidates = [(qualifier, self.aliases[qualifier])]
            if column.db:
                qualified = _identifier(column.args["db"]) + "." + _identifier(column.args["table"])
                candidates = [(a, t) for a, t in candidates if t == qualified]
        else:
            candidates = list(self.aliases.items())
        matches = [(a, t + "." + name) for a, t in candidates if t + "." + name in self.fields]
        if not matches and not qualifier and self.parent:
            return self.parent.ref(column)
        if len(matches) != 1:
            raise _AuditStop("relationship_field_ambiguous_or_unavailable")
        return matches[0]


def audit_relational_bindings(query, contract: dict, catalog: dict, payload: dict) -> dict:
    """Fail closed on unsupported structure; never infer roles from question text."""
    def result(status, reason=None):
        return {"status": status, "findings": [{"reason": reason}] if reason else [],
                "coverage": ["declared_relationship_selection", "membership_polarity_and_correlation",
                             "declared_entity_grain"],
                "not_verified": ["question_interpretation", "filter_meaning", "join_business_role", "ranking_meaning"]}
    try:
        if query.args.get("with_") or any(query.find_all(exp.Subquery, exp.Window)):
            raise _AuditStop("relational_nested_or_window_shape_unsupported")
        tables = {t["table_name"]: t for t in payload.get("candidate_tables") or []}
        outer = _Sources(query, tables, catalog["fields"])
        if len(set(outer.aliases.values())) != len(outer.aliases):
            raise _AuditStop("repeated_physical_output_source_unsupported")
        relations = catalog["relationships"]

        def edge(predicate, sources):
            if not isinstance(predicate, exp.EQ) or not all(isinstance(c, exp.Column) for c in (predicate.this, predicate.expression)):
                raise _AuditStop("relationship_equality_unsupported")
            a, b = sources.ref(predicate.this), sources.ref(predicate.expression)
            matches = []
            for relation in relations:
                left = relation["source_table"] + "." + relation["source_field"]
                right = relation["target_table"] + "." + relation["target_field"]
                for x, y in ((a, b), (b, a)):
                    if x[1] == left and y[1] == right and x[0] != y[0]:
                        matches.append((relation["id"], x[0], y[0]))
            if len(matches) != 1:
                raise _AuditStop("relationship_equality_not_uniquely_registered")
            return matches[0]

        def joined_edges(sources, membership=False):
            selected = set()
            for join in sources.query.args.get("joins") or []:
                if (join.args.get("method") or join.args.get("using") or join.kind not in {"", "INNER", "OUTER"}
                        or join.side not in {"", "LEFT"} or (membership and join.side)):
                    raise _AuditStop("relationship_join_shape_unsupported")
                joined = _identifier(join.this.args["alias"].this if join.this.args.get("alias") else join.this.this)
                on = join.args.get("on")
                if on is None:
                    raise _AuditStop("relationship_join_requires_on")
                linked = False
                for predicate in _conjuncts(on):
                    refs = [sources.ref(c) for c in predicate.find_all(exp.Column)]
                    aliases = {a for a, _ in refs}
                    if isinstance(predicate, exp.Or) or any(predicate.find_all(exp.Select)):
                        raise _AuditStop("relationship_join_predicate_unsupported")
                    if len(aliases) > 1:
                        item = edge(predicate, sources)
                        if joined not in item[1:] or not set(item[1:]) <= sources.aliases.keys():
                            raise _AuditStop("relationship_join_endpoint_unsupported")
                        selected.add((*item, joined, "left" if join.side else "inner"))
                        linked = True
                if not linked:
                    raise _AuditStop("relationship_join_not_connected")
            return selected

        outer_edges = joined_edges(outer)
        declared = [(e["relationship_id"], e["source_alias"], e["target_alias"], e["joined_alias"], e["join_type"])
                    for e in contract["joins"]]
        if Counter(declared) != Counter(outer_edges):
            raise _AuditStop("declared_join_selection_changed", "violation")

        where = query.args.get("where")
        predicates = _conjuncts(where.this) if where else []
        membership_queries, actual_memberships = [], []
        for predicate in predicates:
            body = predicate.this.unnest() if isinstance(predicate, exp.Not) else predicate
            if not isinstance(body, exp.Exists):
                if any(predicate.find_all(exp.Select)):
                    raise _AuditStop("membership_must_be_conjunctive_exists")
                if len({a for c in predicate.find_all(exp.Column) for a, _ in [outer.ref(c)]}) > 1:
                    raise _AuditStop("cross_source_filter_unsupported")
                continue
            child = body.this
            if (not isinstance(child, exp.Select) or child.args.get("with_") or
                    any(child.args.get(k) for k in ("group", "having", "limit", "offset", "qualify", "distinct", "order")) or
                    any(child.find_all(exp.AggFunc)) or
                    len(child.selects) != 1 or not isinstance(child.selects[0], exp.Literal) or
                    child.selects[0].is_string or str(child.selects[0].this) != "1" or
                    len(list(child.find_all(exp.Select))) != 1):
                raise _AuditStop("membership_query_shape_unsupported")
            membership_queries.append(child)
            inner = _Sources(child, tables, catalog["fields"], outer)
            for column in child.find_all(exp.Column):
                inner.ref(column)
            child_edges = {e[:3] for e in joined_edges(inner, membership=True)}
            correlations = set()
            child_where = child.args.get("where")
            for condition in _conjuncts(child_where.this) if child_where else []:
                refs = [inner.ref(c) for c in condition.find_all(exp.Column)]
                aliases = {a for a, _ in refs}
                if aliases & outer.aliases.keys():
                    item = edge(condition, inner)
                    if not (set(item[1:]) & outer.aliases.keys() and set(item[1:]) & inner.aliases.keys()):
                        raise _AuditStop("membership_correlation_unsupported")
                    correlations.add(item)
                elif len(aliases) > 1:
                    raise _AuditStop("membership_cross_source_filter_unsupported")
            if not correlations:
                raise _AuditStop("membership_not_correlated")
            all_edges = child_edges | correlations
            reached = set(outer.aliases)
            while True:
                expanded = reached | {a for _, x, y in all_edges if x in reached or y in reached for a in (x, y)}
                if expanded == reached:
                    break
                reached = expanded
            if not inner.aliases.keys() <= reached:
                raise _AuditStop("membership_bridge_not_connected")
            actual_memberships.append(("not_exists" if isinstance(predicate, exp.Not) else "exists", tuple(sorted(all_edges))))
        if {id(q) for q in query.find_all(exp.Select)} != {id(query), *(id(q) for q in membership_queries)}:
            raise _AuditStop("relational_nested_select_unsupported")
        expected_memberships = [(m["polarity"], tuple(sorted((r["relationship_id"], r["source_alias"], r["target_alias"])
                                for r in m["relations"]))) for m in contract["memberships"]]
        if Counter(expected_memberships) != Counter(actual_memberships):
            raise _AuditStop("membership_polarity_or_relationship_changed", "violation")

        grain = contract["result_grain"]
        aggregate = any(p.find(exp.AggFunc) for p in query.selects)
        if grain["kind"] == "entity_rows":
            anchor = grain["alias"]
            if outer.aliases.get(anchor) != grain["table_id"]:
                raise _AuditStop("entity_grain_source_changed", "violation")
            if aggregate or query.args.get("group") or query.args.get("having"):
                raise _AuditStop("entity_grain_grouping_unsupported")
            # Metric compilation wraps even a row-level field in parentheses.
            # Parentheses preserve identity; functions and derived expressions
            # still require a separate cardinality proof.
            projections = [(p.this if isinstance(p, exp.Alias) else p).unnest() for p in query.selects]
            if any(not isinstance(p, exp.Column) for p in projections):
                raise _AuditStop("entity_grain_projection_unsupported")
            from .nl2sql_metric_grain import _key_preserving_joins
            # The shared proof uses scope spelling; map normalized aliases back.
            raw_anchor = next(a for a, (_, s) in outer.scope.selected_sources.items()
                              if _identifier(s.args["alias"].this if s.args.get("alias") else s.this) == anchor)
            preserving = _key_preserving_joins(query, outer.scope, tables, outer.physical, raw_anchor)
            distinct = query.args.get("distinct")
            if distinct and distinct.args.get("on"):
                raise _AuditStop("entity_grain_distinct_on_unsupported")
            if distinct:
                refs = []
                for column in projections:
                    refs.append(outer.ref(column))
                if {a for a, _ in refs} != {anchor} or not set(grain["identity_field_ids"]) <= {f for _, f in refs}:
                    raise _AuditStop("entity_grain_distinct_requires_projected_identity", "violation")
            elif not preserving:
                raise _AuditStop("entity_rows_may_repeat_use_exists_or_identity_distinct", "violation")
        elif (grain["kind"] == "aggregate") != bool(aggregate or query.args.get("group")):
            raise _AuditStop("result_grain_operation_changed", "violation")
        return result("verified")
    except _AuditStop as exc:
        return result(exc.status, str(exc))
    except (ValueError, KeyError, TypeError) as exc:
        return result("unverified", "relational_scope_unresolved:" + type(exc).__name__)
