"""Hide proven sorting helpers behind an explicit physical output list.

The original query remains an unchanged inner query, including DISTINCT,
filters, ordering and LIMIT. No missing field or business meaning is inferred.
Only exact catalog aliases in a final output instruction are supported.
"""
from __future__ import annotations

import hashlib
import os
import re

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import build_scope

from .nl2sql_output_contract import _norm, _occurrences, _terms


def output_projection_enabled() -> bool:
    value = os.environ.get("GDA_NL2SQL_OUTPUT_PROJECTION", "1").strip().casefold()
    if value not in {"0", "false", "off", "no", "", "1", "true", "on", "yes"}:
        raise ValueError("GDA_NL2SQL_OUTPUT_PROJECTION must be a boolean")
    return value in {"1", "true", "on", "yes"}


def _output_terms(question: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"[.!?;。！？；]+", question or "") if s.strip()]
    if not sentences:
        return []
    match = re.fullmatch(
        r"(?:(?:please\s+)?(?:provide|return|give|state|show|list|indicate)\s+"
        r"(?:(?:only|just)\s+)?(?:the\s+)?|(?:请)?(?:仅|只)?(?:返回|列出|提供|给出|显示))(.+)",
        sentences[-1], re.I,
    )
    if not match:
        return []
    parts = re.split(r"\s*(?:[,，、]|\band\b|和|及|与)\s*", match[1], flags=re.I)
    terms = [_norm(re.sub(r"^the\s+", "", p.strip(), flags=re.I)) for p in parts if p.strip()]
    return terms if terms and len(terms) == len(set(terms)) else []


def _identifier(node):
    return node.name if node.args.get("quoted") else node.name.lower()


def apply_output_projection(question: str, sql: str, payload: dict) -> tuple[str, dict]:
    audit = {"status": "not_applicable", "reason": "no_exact_final_output_list"}
    if not output_projection_enabled():
        return sql, {**audit, "reason": "disabled"}
    terms = _output_terms(question)
    if not terms:
        return sql, audit

    def unchanged(reason):
        return sql, {**audit, "status": "unverified", "reason": reason}

    try:
        statements = sqlglot.parse(sql, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return unchanged("unsupported_query_shape")
        query = statements[0]
        if (query.args.get("with_") or query.args.get("into") or query.args.get("locks")
                or any(query.find_all(exp.Subquery, exp.Window, exp.AggFunc))
                or query.args.get("group") or query.args.get("having")
                or (query.args.get("distinct") and query.args["distinct"].args.get("on"))):
            return unchanged("complex_lineage_or_grain_unsupported")
        scope = build_scope(query)
        order = query.args.get("order")
        if scope is None or not order:
            return unchanged("sorting_helper_not_proven")
        tables = {t["table_name"]: t for t in payload.get("candidate_tables") or []}
        sources = {}
        for _, (_, source) in scope.selected_sources.items():
            if (not isinstance(source, exp.Table) or source.catalog
                    or source.args.get("alias") and source.args["alias"].args.get("columns")):
                return unchanged("physical_lineage_unsupported")
            name = _identifier(source.this)
            schema = _identifier(source.args["db"]) if source.db else None
            candidates = [t for t in tables if t == schema + "." + name] if schema else [
                t for t in tables if t.rsplit(".", 1)[-1] == name]
            if len(candidates) != 1:
                return unchanged("source_outside_authorized_catalog")
            alias = source.args["alias"].this if source.args.get("alias") else source.this
            key = _identifier(alias)
            if key in sources or candidates[0] in sources.values():
                return unchanged("ambiguous_source_role")
            sources[key] = candidates[0]

        projections = []
        output_names = set()
        for projection in query.selects:
            column = projection.this if isinstance(projection, exp.Alias) else projection
            if not isinstance(column, exp.Column) or column.is_star or column.catalog:
                return unchanged("direct_physical_outputs_required")
            possible = [sources.get(_identifier(column.args["table"]))] if column.table else list(sources.values())
            if column.db:
                possible = [t for t in possible if t == _identifier(column.args["db"]) + "." + _identifier(column.args["table"])]
            fields = [(t, c) for t in possible if t in tables for c in tables[t].get("columns") or []
                      if c["column_name"] == _identifier(column.this)]
            if len(fields) != 1:
                return unchanged("field_lineage_ambiguous_or_unauthorized")
            output_identifier = projection.args["alias"] if isinstance(projection, exp.Alias) else column.this
            output_name = _identifier(output_identifier)
            if output_name in output_names:
                return unchanged("duplicate_output_labels")
            output_names.add(output_name)
            projections.append({"column": column, "table": fields[0][0], "field": fields[0][1], "name": output_name})

        selected = []
        for term in terms:
            matches = [i for i, p in enumerate(projections) if term in _terms(p["field"])]
            if len(matches) != 1:
                return unchanged("requested_field_missing_or_ambiguous")
            selected.append(matches[0])
        if len(set(selected)) != len(selected):
            return unchanged("output_aliases_resolve_to_same_field")
        if selected == list(range(len(projections))):
            return sql, {**audit, "reason": "outputs_already_match"}
        # The visible fields must explicitly retain one source's complete
        # registered identity. A later "indicate publisher" instruction does
        # not authorize hiding the entity asked for by "which person".
        owners = {projections[i]["table"] for i in selected}
        if len(owners) != 1:
            return unchanged("one_identified_result_entity_required")
        owner = next(iter(owners))
        identity = tables[owner].get("primary_keys") or []
        visible_fields = {projections[i]["field"]["column_name"] for i in selected}
        if not identity or not set(identity) <= visible_fields:
            return unchanged("requested_entity_identity_not_complete")

        # Every ordering key must already be projected. Adding a hidden key
        # to DISTINCT could itself change row multiplicity and is forbidden.
        sorted_indices = []
        for ordered in order.expressions:
            key = ordered.this
            if isinstance(key, exp.Literal) and not key.is_string and str(key.this).isdigit():
                matches = [int(key.this) - 1] if 1 <= int(key.this) <= len(projections) else []
            else:
                # PostgreSQL resolves a bare ORDER BY name to the output
                # label before looking for a same-named input column.
                matches = []
                if isinstance(key, exp.Column) and not key.table:
                    matches = [i for i, p in enumerate(projections) if _identifier(key.this) == p["name"]]
                if not matches:
                    matches = [i for i, p in enumerate(projections) if key == p["column"]]
            if len(matches) != 1:
                return unchanged("ordering_key_not_projected_or_ambiguous")
            sorted_indices.append(matches[0])
        removed = [i for i in range(len(projections)) if i not in selected]
        if not removed or not set(removed) <= set(sorted_indices):
            return unchanged("extra_fields_not_exclusively_sorting_helpers")
        # An earlier request may explicitly need that value as an output.
        # In that case this narrow final-instruction proof is insufficient.
        normalized_question = _norm(question)
        if any(_occurrences(normalized_question, term) for i in removed for term in _terms(projections[i]["field"])):
            return unchanged("sorting_field_explicitly_mentioned")

        alias = "_gda_output"
        outer = exp.select(*[exp.column(projections[i]["name"], table=alias, quoted=True) for i in selected])
        outer = outer.from_(query.copy().subquery(alias))
        outer_order = []
        for ordered, index in zip(order.expressions, sorted_indices):
            item = ordered.copy()
            item.set("this", exp.column(projections[index]["name"], table=alias, quoted=True))
            outer_order.append(item)
        outer.set("order", exp.Order(expressions=outer_order))
        assert outer.args["from_"].this.this == query
        return outer.sql(dialect="postgres"), {
            "status": "applied", "reason": "hide_sorting_helpers_preserve_inner_query",
            "requested_terms": terms, "kept_positions": selected, "hidden_positions": removed,
            "inner_query_preserved": True, "row_deduplication_added": False,
            "retained_entity": owner, "retained_identity_fields": identity,
            "source_sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "not_verified": ["question_interpretation", "filter_meaning", "result_entity_grain"],
        }
    except (sqlglot.errors.SqlglotError, ValueError, KeyError, TypeError):
        return unchanged("projection_could_not_be_verified")
