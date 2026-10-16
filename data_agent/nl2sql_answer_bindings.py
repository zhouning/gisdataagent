"""Versioned output bindings for the answer-plan generation route.

Checks declared field identity, registered formula and aggregate multiplicity.
It does not prove natural-language interpretation, filters or ranking. Complex
lineage is explicitly unverified rather than guessed from matching names.
"""
from __future__ import annotations

import hashlib
import json
import os

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import build_scope
from .nl2sql_observability import observe_stage


def typed_bindings_enabled() -> bool:
    from .nl2sql_relational_bindings import relational_bindings_enabled
    if relational_bindings_enabled():
        return True
    value = os.environ.get("GDA_NL2SQL_TYPED_BINDINGS", "0").strip().casefold()
    if value not in {"0", "false", "off", "no", "", "1", "true", "on", "yes"}:
        raise ValueError("GDA_NL2SQL_TYPED_BINDINGS must be a boolean")
    return value in {"1", "true", "on", "yes"}


def binding_catalog(payload: dict) -> dict:
    from .nl2sql_metric_grounding import metric_uses_authorized_fields

    fields = {}
    for table in payload.get("candidate_tables") or []:
        for field in table.get("columns") or []:
            identity = table["table_name"] + "." + field["column_name"]
            if identity in fields:
                raise ValueError("Duplicate authorized field identity")
            fields[identity] = {"table": table["table_name"], "column": field["column_name"],
                "type": field.get("pg_type") or field.get("data_type"),
                "description": field.get("description"), "value_semantics": field.get("value_semantics") or {},
                "primary_keys": table.get("primary_keys") or []}
    metrics = {}
    for metric in payload.get("registered_metrics") or []:
        if not metric_uses_authorized_fields(metric.get("definition") or "", payload):
            continue
        identity = metric["source_scope"] + ":" + metric["name"]
        if identity in metrics:
            raise ValueError("Duplicate authorized metric identity")
        metrics[identity] = metric
    from .nl2sql_relational_bindings import relational_bindings_enabled
    contents = {"version": 1, "fields": fields, "metrics": metrics}
    if relational_bindings_enabled():
        from .nl2sql_relationship_retrieval import relationship_catalog
        contents.update(version=2, relationships=relationship_catalog(payload.get("candidate_tables") or []))
    serialized = json.dumps(contents, sort_keys=True, ensure_ascii=False)
    return {**contents, "sha256": hashlib.sha256(serialized.encode()).hexdigest()}


def bindings_schema() -> dict:
    def obj(properties):
        return {"type": "object", "additionalProperties": False,
                "properties": properties, "required": list(properties)}
    string = {"type": "string", "minLength": 1}
    schema = obj({
        "catalog_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "outputs": {"type": "array", "minItems": 1, "maxItems": 30, "items": obj({
            "source_quote": string,
            "field_ids": {"type": "array", "minItems": 1, "maxItems": 20, "uniqueItems": True, "items": string},
            "metric_id": {"type": ["string", "null"]},
            "operation": {"enum": ["scalar", "count", "count_distinct", "sum", "avg", "min", "max", "metric"]},
            "population": {"enum": ["source_rows", "joined_rows", "not_applicable"]},
        })},
        "unresolved_ambiguities": {"type": "array", "maxItems": 20, "items": string},
    })
    from .nl2sql_relational_bindings import relational_bindings_enabled, relational_schema
    if relational_bindings_enabled():
        schema["properties"]["relational"] = relational_schema()
        schema["required"].append("relational")
    return schema


def binding_prompt(payload: dict, *, include_schema: bool = True) -> str:
    catalog = binding_catalog(payload)
    from .nl2sql_field_roles import field_role_candidates
    prompt = (
        ("\nReturn semantic_bindings inside plan using this JSON schema:\n"
         + json.dumps(bindings_schema(), ensure_ascii=False) if include_schema else
         "\nReturn semantic_bindings inside plan using the RESPONSE JSON SCHEMA above.\n")
        + "\nCopy catalog_sha256 exactly: " + catalog["sha256"]
        + "\nBind every output in order. field_ids are exact table_name.column_name identifiers "
        "from the authorized catalog, including every input to a derived value. source_quote "
        "must be verbatim question text. Select by the documented entity/observation role, "
        "not lexical similarity. For a registered formula use operation=metric and its "
        "source_scope:name metric_id. Other outputs have metric_id=null. Scalar means "
        "a row expression; declare count/count_distinct/sum/avg/min/max for a single aggregate. "
        "population describes aggregation: for an aggregate over source records choose "
        "source_rows; joined_rows means the question explicitly requests joined combinations. "
        "Row expressions use not_applicable, including operation=metric when its registered "
        "formula has no aggregate. A stored per-record counter is not an aggregate merely "
        "because it is called a measure or metric. "
        "Do not silently select one meaning when the question does not distinguish alternatives: "
        "record the issue in unresolved_ambiguities. Selection consistency is not evidence "
        "that the question itself is unambiguous. No additional model review is requested.\n"
        + "Available metric IDs: " + json.dumps(sorted(catalog["metrics"]))
        + "\nField role alternatives: " + json.dumps(field_role_candidates(payload), ensure_ascii=False) + "\n"
    )
    from .nl2sql_relational_bindings import relational_bindings_enabled, relational_prompt
    from .nl2sql_value_presence import requested_value_presence, value_presence_guidance
    prompt += value_presence_guidance(requested_value_presence(payload.get("user_question") or "", payload))
    return prompt + relational_prompt(catalog) if relational_bindings_enabled() else prompt


def validate_binding_selection(bindings: dict, question: str, payload: dict) -> None:
    from jsonschema import validate
    validate(bindings, bindings_schema())
    catalog = binding_catalog(payload)
    if bindings["catalog_sha256"] != catalog["sha256"]:
        raise ValueError("semantic_binding_catalog_version_changed")
    for output in bindings["outputs"]:
        if output["source_quote"] not in question:
            raise ValueError("semantic_binding_quote_not_in_question")
        if not set(output["field_ids"]) <= catalog["fields"].keys():
            raise ValueError("semantic_binding_field_outside_authorized_catalog")
        metric = output["metric_id"]
        if (output["operation"] == "metric") != (metric is not None):
            raise ValueError("semantic_binding_metric_operation_mismatch")
        if metric is not None and metric not in catalog["metrics"]:
            raise ValueError("semantic_binding_metric_outside_authorized_catalog")
        if metric is not None:
            formula = sqlglot.parse_one(catalog["metrics"][metric]["definition"], read="postgres")
            if bool(list(formula.find_all(exp.AggFunc))) == (output["population"] == "not_applicable"):
                # Fail while a bounded generation retry can still repair the
                # declaration, rather than only after compilation/execution.
                raise ValueError("semantic_binding_metric_population_mismatch")
    if "relational" in bindings:
        from .nl2sql_relational_bindings import validate_relational_selection
        validate_relational_selection(bindings["relational"], question, catalog)


@observe_stage("planning.binding_validate", rejected_when=lambda result: result["status"] != "verified")
def audit_answer_bindings(sql: str, bindings: dict, question: str, payload: dict) -> dict:
    """Three-state audit of the SQL actually about to execute, without rewrites."""
    findings = []
    audit = {"status": "unverified", "findings": findings,
             "coverage": ["output_field_identity", "registered_formula", "aggregate_multiplicity"],
             "not_verified": ["question_interpretation", "filter_meaning", "join_business_role", "ranking_meaning"]}
    def fail(reason, status="violation", output=None):
        findings.append({"reason": reason, "output": output})
        return {**audit, "status": status}
    from jsonschema import ValidationError
    try:
        validate_binding_selection(bindings, question, payload)
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        return fail(str(exc))
    from .nl2sql_value_presence import audit_value_presence
    presence = audit_value_presence(sql, question, payload)
    if presence["status"] != "not_applicable":
        audit["value_presence"] = presence
        audit["coverage"] += presence["coverage"]
        if presence["status"] != "verified":
            findings.extend(presence["findings"])
            return {**audit, "status": presence["status"]}
    if bindings["unresolved_ambiguities"]:
        return fail("question_has_unresolved_ambiguities", "unverified")
    try:
        trees = sqlglot.parse(sql, read="postgres")
        if len(trees) != 1 or not isinstance(trees[0], exp.Select):
            return fail("query_shape_unsupported", "unverified")
        query = trees[0]
        catalog = binding_catalog(payload)
        if "relational" in bindings:
            from .nl2sql_relational_bindings import audit_relational_bindings
            relational = audit_relational_bindings(query, bindings["relational"], catalog, payload)
            audit["relational"] = relational
            audit["coverage"] += relational["coverage"]
            if relational["status"] != "verified":
                findings.extend(relational["findings"])
                return {**audit, "status": relational["status"]}
        elif (query.args.get("with_") or any(query.find_all(exp.Subquery, exp.Window))
                or len(list(query.find_all(exp.Select))) != 1):
            return fail("nested_or_window_lineage_unsupported", "unverified")
        scope = build_scope(query)
        if scope is None:
            return fail("query_scope_missing", "unverified")
        tables = {t["table_name"]: t for t in payload.get("candidate_tables") or []}

        def physical(source):
            if not isinstance(source, exp.Table) or source.catalog:
                return None
            if source.args.get("alias") and source.args["alias"].args.get("columns"):
                return None
            # Quoted names retain case; unquoted names follow PostgreSQL folding.
            name = source.name if source.this.args.get("quoted") else source.name.lower()
            schema = source.db
            if schema and not source.args["db"].args.get("quoted"):
                schema = schema.lower()
            matches = [n for n in tables if n == schema + "." + name] if schema else [n for n in tables if n.rsplit(".", 1)[-1] == name]
            return matches[0] if len(matches) == 1 else None

        aliases = {}
        for alias, (_, source) in scope.selected_sources.items():
            name = physical(source)
            if name is None:
                return fail("physical_source_unresolved", "unverified")
            identifier = source.args["alias"].this if source.args.get("alias") else source.this
            aliases[identifier.name if identifier.args.get("quoted") else identifier.name.lower()] = name

        def ref(column, formula=False):
            if column.is_star or column.catalog:
                raise ValueError("field_lineage_unsupported")
            if formula:
                candidates = [n for n in tables if not column.table or
                              (n == column.db + "." + column.table if column.db else n.rsplit(".", 1)[-1] == column.table)]
                name = column.name
            else:
                name = column.name if column.this.args.get("quoted") else column.name.lower()
                qualifier = column.table
                if qualifier and not column.args["table"].args.get("quoted"):
                    qualifier = qualifier.lower()
                candidates = [aliases[qualifier]] if qualifier in aliases else ([] if qualifier else list(aliases.values()))
                if column.db:
                    candidates = [n for n in candidates if n == column.db + "." + column.table]
            ids = [table + "." + name for table in candidates if table + "." + name in catalog["fields"]]
            if len(ids) != 1:
                raise ValueError("field_lineage_ambiguous_or_unavailable")
            return ids[0]

        def canonical(expression, formula=False):
            result = expression.copy()
            for c in list(result.find_all(exp.Column)):
                c.replace(exp.column(ref(c, formula), quoted=True))
            # Compare AST structure. Serializing after dropping parentheses
            # could conflate (a+b)*c with a+b*c.
            return result.transform(lambda n: n.this if isinstance(n, exp.Paren) else n)

        if len(query.selects) != len(bindings["outputs"]):
            return fail("output_count_changed")
        for index, (projection, binding) in enumerate(zip(query.selects, bindings["outputs"])):
            expression = projection.this if isinstance(projection, exp.Alias) else projection
            expression = expression.unnest()
            actual = {ref(c) for c in expression.find_all(exp.Column)}
            if actual != set(binding["field_ids"]):
                return fail("output_field_identity_changed", output=index)
            operation = binding["operation"]
            has_aggregate = bool(list(expression.find_all(exp.AggFunc)))
            if has_aggregate == (binding["population"] == "not_applicable"):
                return fail("aggregate_population_not_declared", output=index)
            aggregate_types = {"count": exp.Count, "count_distinct": exp.Count, "sum": exp.Sum,
                               "avg": exp.Avg, "min": exp.Min, "max": exp.Max}
            if operation == "metric":
                metric = catalog["metrics"][binding["metric_id"]]
                # Compare the exact registered expansion in the actual scope,
                # including a sanctioned identity-count compilation.
                from .nl2sql_metric_compiler import compile_metric_slots, MetricCompilationError
                expected_query = query.copy()
                expected_query.expressions[index].replace(exp.Anonymous(
                    this="GDA_METRIC", expressions=[exp.Literal.string(metric["name"])]))
                try:
                    expected_sql, _ = compile_metric_slots(expected_query.sql(dialect="postgres"), payload, [metric])
                except MetricCompilationError as exc:
                    return fail(str(exc), output=index)
                expected = sqlglot.parse_one(expected_sql, read="postgres").selects[index].unnest()
                if canonical(expression) != canonical(expected):
                    return fail("registered_metric_expression_changed", output=index)
            elif operation == "scalar":
                if list(expression.find_all(exp.AggFunc)):
                    return fail("output_aggregation_changed", output=index)
            elif not isinstance(expression, aggregate_types[operation]):
                return fail("output_aggregation_changed", output=index)
            elif (operation == "count_distinct") != isinstance(expression.this, exp.Distinct):
                return fail("output_distinct_policy_changed", output=index)
            if binding["population"] == "source_rows" and list(expression.find_all(exp.AggFunc)):
                # Ad-hoc fields and registered formulas share one cardinality
                # proof. An audit never silently changes a generated query.
                from .nl2sql_metric_grain import preserve_metric_grain, MetricGrainError
                source_tables = {catalog["fields"][f]["table"] for f in actual}
                if len(source_tables) != 1:
                    return fail("multi_source_measure_unsupported", "unverified", index)
                table = next(iter(source_tables))
                source_aliases = [a for a, (_, source) in scope.selected_sources.items() if physical(source) == table]
                if len(source_aliases) != 1:
                    return fail("self_join_measure_unsupported", "unverified", index)
                metric = {"source_scope": table, "semantic_contract": {"source_grain": {
                    "version": 1, "table": table, "identity_fields": tables[table].get("primary_keys") or [],
                    "multiplicity": "preserve_source_rows"}}}
                try:
                    revised, grain = preserve_metric_grain(expression, metric, query, scope, tables, physical,
                        [{"table": table, "alias": source_aliases[0]}])
                    if revised != expression:
                        return fail("source_row_count_requires_distinct_identity", output=index)
                    if grain["status"] == "unverified":
                        return fail(grain["reason"], "unverified", index)
                except MetricGrainError as exc:
                    return fail(str(exc), output=index)
        return {**audit, "status": "verified"}
    except (sqlglot.errors.SqlglotError, ValueError, KeyError) as exc:
        return fail(str(exc), "unverified")
