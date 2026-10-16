"""Preserve registered source-row measures across SQL joins.

Cardinality proofs use authorized primary keys and actual equality predicates,
never matching column names or model claims. Unknown shapes fail explicitly.
This verifies multiplicity only, not the question's population or join meaning.
"""
from __future__ import annotations

from sqlglot import exp


class MetricGrainError(ValueError):
    def __init__(self, reason: str, audit: dict):
        super().__init__(reason)
        self.audit = audit


def _key_preserving_joins(query, scope, catalog, physical_table, anchor: str) -> bool:
    sources = scope.selected_sources
    if len(sources) == 1:
        return True
    keys, alias_names = {}, {}
    for alias, (_, source) in sources.items():
        table = physical_table(source)
        if not table or source.args.get("alias") and source.args["alias"].args.get("columns"):
            return False
        primary = catalog[table].get("primary_keys") or []
        authorized = {c["column_name"] for c in catalog[table].get("columns") or []}
        keys[alias] = set(primary) if set(primary) <= authorized else set()
        identifier = source.args["alias"].this if source.args.get("alias") else source.this
        alias_names[identifier.name if identifier.args.get("quoted") else identifier.name.lower()] = alias
    # Only conjunctions guarantee every equality. An equality inside OR,
    # USING, a function, or a subquery cannot prove a target is unique.
    edges = {}
    for join in query.args.get("joins") or []:
        if join.args.get("method") or join.args.get("kind") in {"SEMI", "ANTI"}:
            return False
        if join.side and (join.side != "LEFT" or query.args["from_"].this.alias_or_name != anchor):
            return False
        on = join.args.get("on")
        if on is None:
            return False
        for predicate in on.flatten() if isinstance(on, exp.And) else [on]:
            predicate = predicate.unnest()
            if not isinstance(predicate, exp.EQ):
                continue
            a, b = predicate.this, predicate.expression
            if (not isinstance(a, exp.Column) or not isinstance(b, exp.Column)
                    or not a.table or not b.table or a.table == b.table
                    or a.db or b.db):
                continue
            a_name = a.table if a.args["table"].args.get("quoted") else a.table.lower()
            b_name = b.table if b.args["table"].args.get("quoted") else b.table.lower()
            if a_name not in alias_names or b_name not in alias_names:
                continue
            left, right = alias_names[a_name], alias_names[b_name]
            # A LEFT JOIN's ON clause only restricts its newly joined side.
            # Equalities involving earlier relations can be false while their
            # rows survive with NULLs, so they cannot prove those relations
            # unique. Inner joins may constrain either side.
            joined_alias = join.this.alias_or_name
            if not join.side or right == joined_alias:
                edges.setdefault((left, right), set()).add(b.name if b.this.args.get("quoted") else b.name.lower())
            if not join.side or left == joined_alias:
                edges.setdefault((right, left), set()).add(a.name if a.this.args.get("quoted") else a.name.lower())
    reached = {anchor}
    while True:
        added = {target for (origin, target), columns in edges.items()
                 if origin in reached and keys.get(target) and keys[target] <= columns}
        expanded = reached | added
        if expanded == reached:
            return reached == set(sources)
        reached = expanded


def preserve_metric_grain(formula, metric, query, scope, catalog, physical_table, bindings):
    """Return a copied formula and evidence, or reject an unproved measure.

    A source-row COUNT over the single registered primary key can be compiled
    to COUNT(DISTINCT key). SUM(DISTINCT value) is deliberately never used.
    """
    contract = (metric.get("semantic_contract") or {}).get("source_grain")
    if contract is None:
        return formula, {"status": "unverified", "reason": "source_grain_contract_missing"}
    audit = {"status": "unverified", "source_table": contract.get("table"),
             "policy": contract.get("multiplicity"), "reason": "invalid_source_grain_contract"}
    if (contract.get("version") != 1 or contract.get("multiplicity") != "preserve_source_rows"
            or contract.get("table") != metric.get("source_scope")
            or not isinstance(contract.get("identity_fields"), list)):
        raise MetricGrainError(audit["reason"], audit)
    table = contract["table"]
    if table not in catalog or contract["identity_fields"] != (catalog[table].get("primary_keys") or []):
        audit["reason"] = "source_grain_identity_changed"
        raise MetricGrainError(audit["reason"], audit)
    if {b["table"] for b in bindings} != {table}:
        audit["reason"] = "source_grain_requires_one_physical_source"
        raise MetricGrainError(audit["reason"], audit)
    alias = bindings[0]["alias"]
    ancestors = []
    # Scalar registered measures may be aggregated by the surrounding query.
    # The caller supplies the original slot for this purpose.
    slot = metric.get("_slot")
    parent = slot.parent if slot is not None else None
    while parent is not None and parent is not query:
        ancestors.append(parent)
        parent = parent.parent
    aggregates = [*formula.find_all(exp.AggFunc), *(n for n in ancestors if isinstance(n, exp.AggFunc))]
    if not aggregates:
        return formula, {**audit, "status": "not_applicable", "reason": "scalar_expression"}
    # MIN/MAX and distinct-value aggregates are invariant to row replication.
    sensitive = [a for a in aggregates if not isinstance(a, (exp.Min, exp.Max))
                 and not isinstance(a.this, exp.Distinct)]
    if not sensitive:
        return formula, {**audit, "status": "verified", "reason": "duplicate_invariant_aggregate"}
    if _key_preserving_joins(query, scope, catalog, physical_table, alias):
        return formula, {**audit, "status": "verified", "reason": "source_rows_not_multiplied"}
    # A window SUM of grouped counts consumes already aggregated values.
    # Correct their leaf counts, not the window roll-up or its population.
    leaves = [a for a in sensitive if not (
        isinstance(a.parent, exp.Window) and any(n is not a for n in a.find_all(exp.AggFunc)))]
    identity = contract["identity_fields"]
    if (leaves and len(identity) == 1 and all(
            isinstance(a, exp.Count) and isinstance(a.this, exp.Column)
            and a.this.name == identity[0] and a.this.table == alias
            and a in list(formula.walk()) and not isinstance(a.parent, exp.Window)
            for a in leaves)
            and not any(isinstance(n, exp.AggFunc) for n in ancestors)):
        result = formula.copy()
        for count in result.find_all(exp.Count):
            if isinstance(count.this, exp.Column) and count.this.table == alias and count.this.name == identity[0]:
                count.set("this", exp.Distinct(expressions=[count.this.copy()]))
        return result, {**audit, "status": "compiled", "reason": "count_source_identity_once",
                        "identity_fields": identity}
    audit["reason"] = "source_rows_may_repeat_use_exists_or_preaggregate"
    raise MetricGrainError(audit["reason"], audit)
