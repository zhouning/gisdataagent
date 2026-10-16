"""Find provably constant aggregate ratios before a bounded generation repair.

This is a structural diagnosis, not an inferred business definition. The model
must still select numerator and denominator from the authorized question and
metadata; this module never broadens a source query itself.
"""
from __future__ import annotations

import re


def constant_population_ratios(question: str, sql: str) -> list[str]:
    if not re.search(r"\b(?:percentage|percent|proportion|ratio|share|rate)\b|百分比|占比|比例", question or "", re.I):
        return []
    import sqlglot
    from sqlglot import exp
    try:
        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) != 1 or statements[0] is None:
            return []
        tree = statements[0]
    except sqlglot.errors.SqlglotError:
        return []

    def unwrap(node):
        while isinstance(node, (exp.Paren, exp.Cast, exp.TryCast, exp.Alias)):
            node = node.this
        return node

    def numerator_aggregate(node):
        node = unwrap(node)
        while isinstance(node, exp.Mul):
            left, right = unwrap(node.this), unwrap(node.expression)
            if isinstance(left, exp.Literal) and not left.is_string:
                node = right
            elif isinstance(right, exp.Literal) and not right.is_string:
                node = left
            else:
                return None
        return node if isinstance(node, (exp.Count, exp.Sum)) else None

    def group_is_constant(select):
        group = select.args.get("group")
        if group is None:
            return True
        filters = [select.args[key] for key in ("where", "having") if select.args.get(key)]
        if not filters or select.args.get("grouping_sets"):
            return False
        def conjuncts(node):
            node = unwrap(node)
            if isinstance(node, exp.And):
                return conjuncts(node.this) + conjuncts(node.expression)
            return [node]
        fixed = set()
        for predicate in [p for clause in filters for p in conjuncts(clause.this)]:
            if isinstance(predicate, exp.EQ):
                left, right = predicate.this, predicate.expression
                if isinstance(left, exp.Literal):
                    left, right = right, left
                if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
                    fixed.add(left.sql(dialect="postgres"))
        return bool(group.expressions) and all(
            isinstance(key, exp.Column) and key.sql(dialect="postgres") in fixed
            for key in group.expressions
        ) and not any(group.args.get(key) for key in ("rollup", "cube", "grouping_sets", "totals"))

    issues = []
    for division in tree.find_all(exp.Div):
        numerator = numerator_aggregate(division.this)
        if numerator is None:
            continue
        denominator = unwrap(division.expression)
        if isinstance(denominator, exp.Nullif):
            denominator = unwrap(denominator.this)
        identical = denominator == numerator
        if isinstance(denominator, exp.Window):
            select = division.find_ancestor(exp.Select)
            if (select is not None and isinstance(denominator.this, exp.Sum)
                    and denominator.this.this == numerator
                    and not denominator.args.get("partition_by")
                    and not denominator.args.get("order")
                    and not denominator.args.get("spec")
                    and group_is_constant(select)):
                identical = True
        if identical:
            issues.append("Numerator and denominator aggregate the same already-filtered population; "
                          "the ratio is structurally 1 (or 100 after scaling), or NULL for zero. "
                          "Define the requested subset and base population separately. Keep only the "
                          "base-population conditions in WHERE; use a conditional aggregate or an "
                          "independently scoped denominator for the subset. Choose COUNT versus SUM "
                          "from the measure requested, without inventing filters. WHERE and HAVING "
                          "both run before window functions; moving a subset predicate to HAVING "
                          "does not repair the denominator. For this scalar subset percentage, "
                          "use a CASE/FILTER conditional aggregate with an unconditional base "
                          "aggregate, or an independent scalar subquery, rather than a window sum.")
    return list(dict.fromkeys(issues))
