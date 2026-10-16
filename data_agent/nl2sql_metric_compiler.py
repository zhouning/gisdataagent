"""Compile named, authorized metric expressions into an existing SQL scope.

The model selects a metric identifier; its registered formula is expanded by
the application. This is expression compilation, not a complete query planner:
the caller still validates population, grain, SQL permissions and execution.
"""
from __future__ import annotations

import hashlib
import json
import os

from .nl2sql_metric_grounding import metric_uses_authorized_fields
from .nl2sql_observability import observe_stage


class MetricCompilationError(ValueError):
    pass


def contains_metric_slots(sql: str) -> bool:
    """Recognize function nodes, never names in quoted data or comments."""
    import sqlglot
    from sqlglot import exp
    try:
        return any(node.name.casefold() == "gda_metric"
                   for tree in sqlglot.parse(sql, read="postgres") if tree is not None
                   for node in tree.find_all(exp.Anonymous))
    except sqlglot.errors.SqlglotError:
        # Malformed SQL is rejected by the normal parser. Do not interpret it.
        return False


@observe_stage("query.metric_compile")
def compile_product_metrics(sql: str, payload: dict, engine: str) -> tuple[str, list[dict]]:
    """Compile on the final SQL path, before the ordinary SQL/source guards."""
    if not contains_metric_slots(sql):
        return sql, []
    if not metric_compilation_enabled():
        raise MetricCompilationError("metric_compilation_disabled")
    if engine != "postgis":
        raise MetricCompilationError("metric_compilation_unsupported_engine")
    if "registered_metrics" not in payload:
        raise MetricCompilationError("metric_catalog_snapshot_missing")
    return compile_metric_slots(sql, payload, payload["registered_metrics"])


def metric_compilation_enabled() -> bool:
    return os.environ.get("GDA_NL2SQL_METRIC_COMPILATION", "0").casefold() in {"1", "true", "yes", "on"}


def metric_compilation_guidance(metrics: list[dict]) -> str:
    if not metrics:
        return ""
    return (
        "\nNamed metric compilation is available. For a requested registered "
        "metric, use GDA_METRIC('metric_name') in the SQL expression where its "
        "value belongs instead of retyping its formula. The application will "
        "compile the exact registered formula and bind it to the local table "
        "alias. The function takes exactly one literal metric name from the "
        "list below. Include the required source table once in that SELECT. "
        "It does not add joins, filters, grouping or change the population. "
        "A metric is usable only when its definition and unit answer the "
        "question; use ordinary SQL for other computations. Do not nest an "
        "aggregate metric within another aggregate or window.\n"
        "Available metric names (JSON data): "
        + json.dumps([metric["name"] for metric in metrics], ensure_ascii=False) + "\n"
    )


def compile_metric_slots(sql: str, payload: dict, metrics: list[dict]) -> tuple[str, list[dict]]:
    """Resolve each GDA_METRIC slot against a captured, ownership-filtered list.

    Only local physical tables can bind formula inputs. A CTE, self-join or
    correlated reference cannot silently change a metric's population. No new
    table, predicate or projection is introduced. All validation precedes the
    caller receiving a compiled query.
    """
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.SqlglotError as exc:
        raise MetricCompilationError("metric_query_parse_error") from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
        raise MetricCompilationError("metric_query_requires_one_select")
    tree = statements[0]
    slots = [node for node in tree.find_all(exp.Anonymous) if node.name.casefold() == "gda_metric"]
    if not slots:
        return sql, []
    if any(isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create,
                            exp.Drop, exp.Alter, exp.Command, exp.Into)) for node in tree.walk()):
        raise MetricCompilationError("metric_query_requires_read_only")
    catalog = {table["table_name"]: table for table in payload.get("candidate_tables") or []}

    def physical_table(table):
        if not isinstance(table, exp.Table) or table.catalog:
            return None
        ref = f"{table.db}.{table.name}" if table.db else table.name
        if table.db:
            return ref if ref in catalog else None
        matches = [name for name in catalog if name.rsplit(".", 1)[-1] == ref]
        return matches[0] if len(matches) == 1 else None

    def formula_field(column):
        if column.catalog or column.is_star:
            raise MetricCompilationError("metric_formula_unbound_field")
        if column.db:
            names = [f"{column.db}.{column.table}"]
        elif column.table:
            names = [name for name in catalog if name.rsplit(".", 1)[-1] == column.table]
        else:
            names = list(catalog)
        bound = [(name, field["column_name"]) for name in names if name in catalog
                 for field in catalog[name].get("columns") or [] if field["column_name"] == column.name]
        if len(bound) != 1:
            raise MetricCompilationError("metric_formula_unbound_field")
        return bound[0]

    scopes = {id(scope.expression): scope for scope in traverse_scope(tree)}
    audit = []
    for slot in slots:
        if isinstance(slot.parent, exp.Dot):
            raise MetricCompilationError("metric_slot_cannot_be_schema_qualified")
        if (len(slot.expressions) != 1 or not isinstance(slot.expressions[0], exp.Literal)
                or not slot.expressions[0].is_string):
            raise MetricCompilationError("metric_slot_requires_literal_name")
        name = slot.expressions[0].this
        matches = [metric for metric in metrics if metric.get("name") == name]
        if len(matches) != 1:
            raise MetricCompilationError("metric_name_unavailable_or_ambiguous")
        metric = matches[0]
        if not metric_uses_authorized_fields(metric.get("definition") or "", payload):
            raise MetricCompilationError("metric_formula_outside_source_scope")
        formula = sqlglot.parse_one(metric["definition"], read="postgres")
        if list(formula.find_all(exp.Anonymous)) and any(
                node.name.casefold() == "gda_metric" for node in formula.find_all(exp.Anonymous)):
            raise MetricCompilationError("recursive_metric_definition")
        query = slot.find_ancestor(exp.Select)
        scope = scopes.get(id(query))
        if scope is None:
            raise MetricCompilationError("metric_slot_has_no_local_scope")
        physical_aliases = {}
        for alias, (_, source) in scope.selected_sources.items():
            full_name = physical_table(source)
            if full_name:
                source_alias = source.args.get("alias")
                if source_alias and source_alias.args.get("columns"):
                    raise MetricCompilationError("metric_source_columns_renamed")
                physical_aliases.setdefault(full_name, []).append(alias)
        bindings = []
        for column in list(formula.find_all(exp.Column)):
            table, field = formula_field(column)
            aliases = physical_aliases.get(table) or []
            if len(aliases) != 1:
                raise MetricCompilationError("metric_requires_one_local_source_binding")
            bindings.append({"table": table, "column": field, "alias": aliases[0]})
            # An unquoted alias is folded by PostgreSQL, while a quoted alias
            # preserves case. Copy its identifier rather than quoting its text.
            source = scope.selected_sources[aliases[0]][1]
            source_alias = source.args.get("alias")
            identifier = source_alias.this if source_alias else source.this
            bound_column = exp.Column(this=exp.to_identifier(field, quoted=True),
                                      table=identifier.copy())
            # A row-level metric may consist entirely of one column. Replacing
            # a root node has no parent to update, so retain that replacement.
            if column is formula:
                formula = bound_column
            else:
                column.replace(bound_column)
        if not bindings:
            raise MetricCompilationError("metric_formula_requires_bound_fields")
        # Expanding SUM into AVG(SUM(...)) changes evaluation levels and is
        # invalid. Window-bearing definitions must also keep their own level.
        ancestors = []
        parent = slot.parent
        while parent is not None and parent is not query:
            ancestors.append(parent)
            parent = parent.parent
        if (list(formula.find_all(exp.AggFunc)) or list(formula.find_all(exp.Window))) and any(
                isinstance(node, (exp.AggFunc, exp.Window)) for node in ancestors):
            raise MetricCompilationError("metric_aggregate_level_conflict")
        from .nl2sql_metric_grain import MetricGrainError, preserve_metric_grain
        try:
            formula, grain_audit = preserve_metric_grain(
                formula, {**metric, "_slot": slot}, query, scope, catalog, physical_table, bindings)
        except MetricGrainError as exc:
            error = MetricCompilationError("metric_grain:" + str(exc))
            error.evidence = {"metric_name": name, **exc.audit}
            raise error from exc
        slot.replace(exp.Paren(this=formula))
        audit.append({"metric_name": name, "source_scope": metric.get("source_scope"),
                      "unit": metric.get("unit"),
                      "definition_sha256": hashlib.sha256(metric["definition"].encode()).hexdigest(),
                      "semantic_contract": metric.get("semantic_contract") or {},
                      "grain_audit": grain_audit,
                      "compiled_expression": formula.sql(dialect="postgres"),
                      "bindings": sorted({json.dumps(b, sort_keys=True) for b in bindings})})
    for item in audit:
        item["bindings"] = [json.loads(binding) for binding in item["bindings"]]
    return tree.sql(dialect="postgres"), audit
