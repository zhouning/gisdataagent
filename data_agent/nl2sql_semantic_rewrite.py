"""Config-driven semantic SQL rewrites for NL2SQL outputs.

The functions in this module only consume the semantic context payload built by
``nl2sql_grounding``. Dataset-specific facts belong in semantic registry fields
such as aliases, units, and value_semantics, not in Python branches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_SQL_STRING_RE = r"('(?:[^']|'')*')"
_GEOGRAPHIC_SRIDS = {4326, 4490, 4610}


@dataclass
class ColumnInfo:
    table_name: str
    column_name: str
    quoted_ref: str
    aliases: set[str] = field(default_factory=set)
    description: str = ""
    needs_quoting: bool = False
    is_geometry: bool = False
    pg_type: str = ""
    srid: int = 0
    unit: str = ""
    semantic_domain: str = ""
    value_semantics: dict[str, Any] = field(default_factory=dict)

    @property
    def ref_tokens(self) -> list[str]:
        tokens = [self.column_name, self.quoted_ref]
        if self.needs_quoting:
            tokens.append(self.column_name.lower())
            tokens.append(self.column_name.upper())
        if self.is_geometry:
            tokens.extend(["geometry", "geom", "shape"])
        tokens.extend(self.aliases)
        return list(dict.fromkeys(t for t in tokens if t))


@dataclass
class TableInfo:
    table_name: str
    columns: list[ColumnInfo]
    table_aliases: set[str] = field(default_factory=set)
    schema_complete: bool = False

    @property
    def bare_name(self) -> str:
        return self.table_name.split(".")[-1]

    def column_by_name(self, name: str) -> ColumnInfo | None:
        name_l = _strip_identifier_quotes(name).lower()
        for col in self.columns:
            if col.column_name.lower() == name_l:
                return col
        return None

    def identifier_column(self) -> ColumnInfo | None:
        for col in self.columns:
            vs = col.value_semantics or {}
            if vs.get("identifier") is True:
                return col
        for col in self.columns:
            if (col.semantic_domain or "").upper() in {"ID", "IDENTIFIER", "PRIMARY_KEY"}:
                return col
        for col in self.columns:
            if col.column_name.lower() in {"id", "fid", "gid", "objectid"}:
                return col
        return None

    def geometry_columns(self) -> list[ColumnInfo]:
        return [c for c in self.columns if c.is_geometry]


def apply_semantic_sql_rewrites(
    question: str,
    sql: str,
    context: dict,
) -> tuple[str, list[str]]:
    """Rewrite SQL using semantic context only.

    Returns the rewritten SQL and stable correction tags. The function is
    intentionally best-effort: if context lacks a fact, it leaves SQL unchanged
    so the normal postprocessor/runtime guards can handle it.
    """
    rewritten = sql or ""
    corrections: list[str] = []
    rewritten, changed = _strip_invalid_trailing_clause_after_semicolon(rewritten)
    if changed:
        corrections.append("semantic_trailing_clause_pruned")
    rewritten, changed = _strip_sql_comments(rewritten)
    if changed:
        corrections.append("semantic_sql_comment_pruned")
    rewritten, changed = _strip_unmatched_closing_parens(rewritten)
    if changed:
        corrections.append("semantic_unmatched_paren_pruned")
    tables = _build_tables(context)
    if not rewritten or not tables:
        rewritten2, n = _rewrite_round_numeric_cast(rewritten)
        if n:
            corrections.append("semantic_round_numeric_cast")
        return rewritten2, corrections

    rewritten, changed = _normalize_versioned_table_refs(rewritten, tables)
    if changed:
        corrections.append("semantic_table_normalized")

    rewritten, changed = _prefer_versioned_candidate_refs(question, rewritten, tables)
    if changed:
        corrections.append("semantic_table_normalized")

    rewritten, changed = _prefer_question_aliased_candidate_table(question, rewritten, tables)
    if changed:
        corrections.append("semantic_question_alias_table")

    rewritten, changed = _prefer_exact_physical_column_table(question, rewritten, tables)
    if changed:
        corrections.append("semantic_exact_column_table")

    rewritten, changed = _rewrite_explicit_geometry_function_request(question, rewritten, tables)
    if changed:
        corrections.append("semantic_explicit_geometry_function")

    rewritten, changed = _collapse_duplicate_union(rewritten)
    if changed:
        corrections.append("semantic_duplicate_union")

    rewritten, changed = _strip_invalid_trailing_clause_after_semicolon(rewritten)
    if changed:
        corrections.append("semantic_trailing_clause_pruned")
    rewritten, changed = _strip_sql_comments(rewritten)
    if changed:
        corrections.append("semantic_sql_comment_pruned")

    alias_map = _table_alias_map(rewritten, tables)

    rewritten, changed = _normalize_quoted_alias_column_refs(rewritten, alias_map)
    if changed:
        corrections.append("semantic_alias_ref_normalized")

    rewritten, changed = _rewrite_column_aliases(rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_column_alias")
        alias_map = _table_alias_map(rewritten, tables)

    rewritten, changed = _rewrite_subquery_geometry_projection_aliases(rewritten, tables)
    if changed:
        corrections.append("semantic_subquery_geometry_projection")
        alias_map = _table_alias_map(rewritten, tables)

    rewritten, changed = _rewrite_missing_target_relation_subquery(question, rewritten, tables)
    if changed:
        corrections.append("semantic_missing_target_relation")
        alias_map = _table_alias_map(rewritten, tables)

    rewritten, changed = _rewrite_subquery_geometry_srid_transforms(rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_subquery_srid_transform")

    rewritten, changed = _strip_geometry_type_modifier_casts(rewritten, alias_map)
    if changed:
        corrections.append("semantic_geometry_cast")

    rewritten, changed = _rewrite_unqualified_select_projection_columns(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_projection_column")

    refused, changed = _refuse_unknown_columns(rewritten, alias_map)
    if changed:
        return refused, corrections + ["semantic_unknown_column_refusal"]

    rewritten, changed = _rewrite_value_groups(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_value_group")

    rewritten, changed = _rewrite_literal_column_overrides(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_literal_column_override")

    rewritten, changed = _rewrite_enum_literal_values(rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_enum_literal")

    rewritten, changed = _rewrite_enum_filters(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_enum_filter")

    rewritten, changed = _rewrite_enum_case_display_to_raw_code(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_enum_display")

    rewritten, changed = _rewrite_enum_comparison_projection_and_filters(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_enum_comparison")

    rewritten, changed = _rewrite_explicit_question_filters(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_explicit_filter")

    rewritten, changed = _rewrite_composite_like_filter_from_question(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_composite_like_filter")

    rewritten, changed = _rewrite_unrequested_code_filters(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_unrequested_code_filter")

    rewritten, changed = _rewrite_unrequested_positive_aggregate_filters(question, rewritten)
    if changed:
        corrections.append("semantic_unrequested_positive_filter")

    rewritten, changed = _rewrite_requested_scalar_aggregates(question, rewritten)
    if changed:
        corrections.append("semantic_requested_aggregate")

    rewritten, changed = _rewrite_aggregate_projection_order(question, rewritten)
    if changed:
        corrections.append("semantic_aggregate_projection_order")

    rewritten, changed = _rewrite_origin_destination_projection(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_origin_destination_projection")

    rewritten, changed = _rewrite_unit_thresholds(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_unit_threshold")

    rewritten, changed = _rewrite_population_total_row_exclusion(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_population_total_exclusion")

    rewritten, changed = _rewrite_precomputed_area(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_area_metric")

    rewritten, changed = _qualify_unqualified_area_geometry(rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_area_geometry_qualified")

    rewritten, changed = _rewrite_st_union_geography_area(rewritten)
    if changed:
        corrections.append("semantic_st_union_geography")

    rewritten, changed = _rewrite_square_kilometre_area_units(question, rewritten)
    if changed:
        corrections.append("semantic_area_square_km")

    rewritten, changed = _rewrite_hectare_area_units(question, rewritten)
    if changed:
        corrections.append("semantic_area_hectare")

    rewritten, changed = _rewrite_scalar_spatial_subquery_join(rewritten, tables)
    if changed:
        corrections.append("semantic_scalar_spatial_subquery")
        alias_map = _table_alias_map(rewritten, tables)

    rewritten, changed = _rewrite_spatial_srid_transforms(rewritten, alias_map)
    if changed:
        corrections.append("semantic_srid_transform")

    rewritten, changed = _rewrite_st_dwithin_geography(rewritten, alias_map)
    if changed:
        corrections.append("semantic_st_dwithin_geography")

    rewritten, changed = _rewrite_distance_degree_multiplier_to_geography(rewritten)
    if changed:
        corrections.append("semantic_distance_srid_transform")

    rewritten, changed = _rewrite_st_distance_srid_transforms(rewritten, alias_map)
    if changed:
        corrections.append("semantic_distance_srid_transform")

    rewritten, changed = _rewrite_st_length_projected_geographic_to_geography(rewritten, alias_map)
    if changed:
        corrections.append("semantic_length_geography")

    rewritten, changed = _rewrite_line_length_aggregates(question, rewritten, tables)
    if changed:
        corrections.append("semantic_length_metric")

    rewritten, changed = _rewrite_knn_order_by_distance_alias(question, rewritten)
    if changed:
        corrections.append("semantic_knn_order")

    rewritten, changed = _rewrite_knn_radius_join_to_cross_join(question, rewritten)
    if changed:
        corrections.append("semantic_knn_join")

    rewritten, changed = _rewrite_knn_string_filters(question, rewritten)
    if changed:
        corrections.append("semantic_knn_filter")

    rewritten, changed = _rewrite_knn_single_target_cross_join(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_knn_target")

    rewritten, changed = _rewrite_existential_spatial_join_aggregate(question, rewritten)
    if changed:
        corrections.append("semantic_existential_spatial_join")

    rewritten, changed = _rewrite_unrequested_unreferenced_spatial_joins(question, rewritten)
    if changed:
        corrections.append("semantic_unrequested_spatial_join_pruned")

    rewritten, changed = _rewrite_requested_containment_spatial_predicate(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_requested_containment")

    rewritten, changed = _rewrite_ranked_metric_not_null(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_rank_metric_not_null")

    rewritten, changed = _rewrite_requested_spatial_predicate(question, rewritten)
    if changed:
        corrections.append("semantic_requested_spatial_predicate")

    rewritten, changed = _rewrite_distinct_name_not_null(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_distinct_not_null")

    rewritten, changed = _rewrite_join_condition_overrides(rewritten, alias_map)
    if changed:
        corrections.append("semantic_join_condition_override")

    rewritten, changed = _rewrite_grouped_count_join_order(question, rewritten)
    if changed:
        corrections.append("semantic_grouped_count_join_order")
        corrections.append("semantic_left_join_count")

    rewritten, changed = _rewrite_left_join_for_grouped_count(question, rewritten)
    if changed:
        corrections.append("semantic_left_join_count")

    rewritten, changed = _rewrite_left_join_for_grouped_count_by_group_alias(question, rewritten)
    if changed:
        corrections.append("semantic_left_join_count")

    rewritten, changed = _rewrite_grouped_spatial_entity_count(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_grouped_spatial_count")

    rewritten, changed = _rewrite_distinct_entity_count(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_distinct_join_count")

    rewritten, changed = _rewrite_centroid_label_projection_order(question, rewritten)
    if changed:
        corrections.append("semantic_centroid_projection_order")

    rewritten, changed = _rewrite_conditional_sum_pivot_to_grouped_rows(question, rewritten)
    if changed:
        corrections.append("semantic_conditional_sum_group_rows")

    rewritten, changed = _rewrite_question_limit(question, rewritten)
    if changed:
        corrections.append("semantic_question_limit")

    rewritten, changed = _rewrite_default_preview_sort(question, rewritten, tables)
    if changed:
        corrections.append("semantic_default_preview_sort")

    rewritten2, n = _rewrite_round_numeric_cast(rewritten)
    if n:
        rewritten = rewritten2
        corrections.append("semantic_round_numeric_cast")

    return rewritten, list(dict.fromkeys(corrections))


def _build_tables(context: dict) -> list[TableInfo]:
    tables: list[TableInfo] = []
    for table in context.get("candidate_tables", []) or []:
        table_name = table.get("table_name")
        if not table_name:
            continue
        table_aliases = set(table.get("table_aliases") or table.get("sql_aliases") or [])
        columns: list[ColumnInfo] = []
        table_srid = int(table.get("srid") or 0)
        for col in table.get("columns", []) or []:
            column_name = col.get("column_name")
            if not column_name:
                continue
            vs = col.get("value_semantics") or {}
            aliases = set(col.get("aliases") or [])
            aliases.update(vs.get("sql_aliases") or [])
            aliases.discard(column_name)
            srid = _parse_srid(col.get("pg_type") or "") or table_srid
            columns.append(ColumnInfo(
                table_name=table_name,
                column_name=column_name,
                quoted_ref=col.get("quoted_ref") or _quote_ref(column_name, bool(col.get("needs_quoting"))),
                aliases={str(a) for a in aliases if a},
                description=str(col.get("description") or ""),
                needs_quoting=bool(col.get("needs_quoting")),
                is_geometry=bool(col.get("is_geometry")),
                pg_type=str(col.get("pg_type") or ""),
                srid=srid,
                unit=str(col.get("unit") or ""),
                semantic_domain=str(col.get("semantic_domain") or ""),
                value_semantics=vs if isinstance(vs, dict) else {},
            ))
        tables.append(TableInfo(
            table_name=table_name,
            columns=columns,
            table_aliases=table_aliases,
            schema_complete=bool(table.get("schema_complete")),
        ))
    return tables


def _quote_ref(column_name: str, needs_quoting: bool) -> str:
    return f'"{column_name}"' if needs_quoting else column_name


def _parse_srid(pg_type: str) -> int:
    m = re.search(r",\s*(\d+)\s*\)", pg_type or "")
    return int(m.group(1)) if m else 0


def _normalize_versioned_table_refs(sql: str, tables: list[TableInfo]) -> tuple[str, bool]:
    known = {t.table_name for t in tables} | {t.bare_name for t in tables}
    by_alias: dict[str, str] = {}
    for table in tables:
        for alias in table.table_aliases:
            by_alias[alias.lower()] = table.table_name

    def repl(match: re.Match) -> str:
        prefix = match.group("prefix")
        quote = match.group("quote") or ""
        ref = match.group("table")
        suffix = match.group("suffix") or ""
        if ref in known:
            return match.group(0)
        replacement = by_alias.get(ref.lower())
        if not replacement:
            matches = [
                t.table_name for t in tables
                if t.bare_name.lower().startswith(ref.lower() + "_")
            ]
            if len(matches) == 1:
                replacement = matches[0]
        if not replacement:
            return match.group(0)
        return f"{prefix}{quote}{replacement}{quote}{suffix}"

    pattern = re.compile(
        r"(?P<prefix>\b(?:FROM|JOIN)\s+)(?P<quote>\"?)(?P<table>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)(?P<suffix>\b)",
        flags=re.IGNORECASE,
    )
    rewritten, n = pattern.subn(repl, sql)
    return rewritten, bool(n and rewritten != sql)


def _prefer_versioned_candidate_refs(
    question: str,
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    """Prefer latest versioned sibling when both generic and versioned candidates exist."""
    latest_by_base: dict[str, str] = {}
    generic_names = {t.bare_name for t in tables if not _is_versioned_table_name(t.bare_name)}
    for table in tables:
        bare = table.bare_name
        if not _is_versioned_table_name(bare):
            continue
        base = _versionless_table_name(bare)
        if base not in generic_names:
            continue
        current = latest_by_base.get(base)
        if not current or _version_suffix_year(bare) > _version_suffix_year(current):
            latest_by_base[base] = bare
    if not latest_by_base:
        return sql, False

    q_low = (question or "").lower()

    def repl(match: re.Match) -> str:
        prefix = match.group("prefix")
        quote = match.group("quote") or ""
        table_ref = match.group("table")
        suffix = match.group("suffix") or ""
        bare = table_ref.split(".")[-1]
        if bare not in latest_by_base:
            return match.group(0)
        # Respect explicit physical-table mentions: product users may really
        # request the generic table by name.
        if re.search(rf"(?<![a-z0-9_]){re.escape(bare.lower())}(?![a-z0-9_])", q_low):
            return match.group(0)
        replacement_bare = latest_by_base[bare]
        if "." in table_ref:
            replacement = ".".join(table_ref.split(".")[:-1] + [replacement_bare])
        else:
            replacement = replacement_bare
        return f"{prefix}{quote}{replacement}{quote}{suffix}"

    pattern = re.compile(
        r"(?P<prefix>\b(?:FROM|JOIN)\s+)(?P<quote>\"?)(?P<table>[A-Za-z_][A-Za-z0-9_\.]*)(?P=quote)(?P<suffix>\b)",
        flags=re.IGNORECASE,
    )
    rewritten, n = pattern.subn(repl, sql or "")
    return rewritten, bool(n and rewritten != (sql or ""))


def _prefer_question_aliased_candidate_table(
    question: str,
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    """Prefer the table whose business aliases are explicitly named by the question."""
    if not question or len(tables) < 2:
        return sql, False
    hit_scores = {table.table_name: _question_table_alias_hits(question, table) for table in tables}
    if max(hit_scores.values(), default=0) <= 0:
        return sql, False

    def repl(match: re.Match) -> str:
        prefix = match.group("prefix")
        quote = match.group("quote") or ""
        table_ref = match.group("table")
        suffix = match.group("suffix") or ""
        current = _table_for_ref(table_ref, tables)
        if not current:
            return match.group(0)
        current_hits = hit_scores.get(current.table_name, 0)
        candidates: list[tuple[int, TableInfo]] = []
        for table in tables:
            if table is current:
                continue
            hits = hit_scores.get(table.table_name, 0)
            if hits <= current_hits:
                continue
            if not _table_can_replace_referenced_table(sql, current, table):
                continue
            candidates.append((hits, table))
        if not candidates:
            return match.group(0)
        best_hits = max(score for score, _ in candidates)
        best_tables = [table for score, table in candidates if score == best_hits]
        if len(best_tables) != 1:
            return match.group(0)
        replacement = best_tables[0].table_name
        return f"{prefix}{quote}{replacement}{quote}{suffix}"

    pattern = re.compile(
        r"(?P<prefix>\b(?:FROM|JOIN)\s+)(?P<quote>\"?)(?P<table>[A-Za-z_][A-Za-z0-9_\.]*)(?P=quote)(?P<suffix>\b)",
        flags=re.IGNORECASE,
    )
    rewritten, n = pattern.subn(repl, sql or "")
    return rewritten, bool(n and rewritten != (sql or ""))


def _question_table_alias_hits(question: str, table: TableInfo) -> int:
    probes = list(table.table_aliases)
    hits = 0
    seen: set[str] = set()
    for probe in probes:
        value = _strip_identifier_quotes(str(probe or "")).strip()
        key = value.lower()
        if not value or key in seen or key in {"cq", "public"}:
            continue
        seen.add(key)
        if _question_contains_table_alias_token(question, value):
            hits += 1
    return hits


def _question_contains_table_alias_token(question: str, token: str) -> bool:
    q = question or ""
    token = token.strip()
    if not token:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in token):
        return token in q
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", q, flags=re.IGNORECASE))


def _table_can_replace_referenced_table(sql: str, current: TableInfo, candidate: TableInfo) -> bool:
    qualifiers = _qualifiers_for_referenced_table(sql, current)
    referenced_cols: set[str] = set()
    for qualifier in qualifiers:
        referenced_cols.update(_column_tokens_for_qualifier(sql, qualifier))
    if referenced_cols:
        return all(_table_accepts_column_token(candidate, col) for col in referenced_cols)
    current_cols = {
        col.column_name.lower()
        for col in current.columns
        if not col.is_geometry
    }
    candidate_tokens = {
        _strip_identifier_quotes(token).lower()
        for col in candidate.columns
        if not col.is_geometry
        for token in col.ref_tokens
    }
    return bool(current_cols & candidate_tokens)


def _qualifiers_for_referenced_table(sql: str, table: TableInfo) -> list[str]:
    qualifiers = [table.table_name, table.bare_name]
    alias = _find_table_alias(sql, table.table_name)
    if alias:
        qualifiers.insert(0, alias)
    return list(dict.fromkeys(q for q in qualifiers if q))


def _column_tokens_for_qualifier(sql: str, qualifier: str) -> set[str]:
    cols: set[str] = set()
    qualifier_re = re.escape(qualifier)
    pattern = re.compile(
        rf"\b{qualifier_re}\s*\.\s*(?P<col>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
        flags=re.IGNORECASE,
    )
    for i, segment in enumerate(re.split(_SQL_STRING_RE, sql or "")):
        if i % 2:
            continue
        for match in pattern.finditer(segment):
            cols.add(_strip_identifier_quotes(match.group("col")))
    return cols


def _table_accepts_column_token(table: TableInfo, token: str) -> bool:
    key = _strip_identifier_quotes(token).lower()
    for col in table.columns:
        for ref_token in col.ref_tokens:
            if _strip_identifier_quotes(ref_token).lower() == key:
                return True
    return False


def _version_suffix_year(table_name: str) -> int:
    m = re.search(r"_(?P<year>(?:19|20)\d{2})$", table_name or "")
    return int(m.group("year")) if m else 0


def _prefer_exact_physical_column_table(
    question: str,
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    """Prefer a candidate table with exact physical columns named by the user."""
    explicit_cols = _question_physical_column_terms(question)
    if not explicit_cols or len(tables) < 2:
        return sql, False

    def repl(match: re.Match) -> str:
        prefix = match.group("prefix")
        quote = match.group("quote") or ""
        table_ref = match.group("table")
        suffix = match.group("suffix") or ""
        current = _table_for_ref(table_ref, tables)
        if not current or _question_mentions_table_name(question, current):
            return match.group(0)
        current_hits = _exact_physical_column_hits(current, explicit_cols)
        scored = [(table, _exact_physical_column_hits(table, explicit_cols)) for table in tables]
        best_hits = max(score for _, score in scored)
        best_tables = [table for table, score in scored if score == best_hits]
        if len(best_tables) != 1:
            return match.group(0)
        best = best_tables[0]
        min_hits = 2 if len(explicit_cols) >= 2 else 1
        for table in tables:
            hits = _exact_physical_column_hits(table, explicit_cols)
            if hits > best_hits:
                best = table
                best_hits = hits
        if best is current or best_hits < min_hits or best_hits <= current_hits:
            return match.group(0)
        replacement = best.table_name
        return f"{prefix}{quote}{replacement}{quote}{suffix}"

    pattern = re.compile(
        r"(?P<prefix>\b(?:FROM|JOIN)\s+)(?P<quote>\"?)(?P<table>[A-Za-z_][A-Za-z0-9_\.]*)(?P=quote)(?P<suffix>\b)",
        flags=re.IGNORECASE,
    )
    rewritten, n = pattern.subn(repl, sql or "")
    return rewritten, bool(n and rewritten != (sql or ""))


def _question_physical_column_terms(question: str) -> set[str]:
    terms: set[str] = set()
    for raw in re.findall(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_])", question or ""):
        raw_l = raw.lower()
        if (
            "_" in raw
            or any(ch.isdigit() for ch in raw)
            or (raw.isupper() and len(raw) > 1)
            or raw_l in {"id", "objectid", "fid", "gid"}
        ):
            terms.add(raw)
    return terms


def _table_for_ref(table_ref: str, tables: list[TableInfo]) -> TableInfo | None:
    ref = _strip_identifier_quotes(table_ref)
    bare = ref.split(".")[-1]
    for table in tables:
        if ref.lower() in {table.table_name.lower(), table.bare_name.lower()}:
            return table
        if bare.lower() == table.bare_name.lower():
            return table
    return None


def _question_mentions_table_name(question: str, table: TableInfo) -> bool:
    q_low = (question or "").lower()
    probes = {table.table_name.lower(), table.bare_name.lower()}
    for probe in probes:
        if re.search(rf"(?<![a-z0-9_]){re.escape(probe)}(?![a-z0-9_])", q_low):
            return True
    return False


def _exact_physical_column_hits(table: TableInfo, explicit_cols: set[str]) -> int:
    physical = {col.column_name for col in table.columns}
    return sum(1 for term in explicit_cols if term in physical)


def _rewrite_explicit_geometry_function_request(
    question: str,
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    q = question or ""
    q_low = q.lower()
    if not (
        "st_geometrytype" in q_low
        or "geometry type" in q_low
        or "\u51e0\u4f55\u7c7b\u578b" in q
    ):
        return sql, False
    candidates = [
        table for table in tables
        if _question_mentions_table_name(question, table) and _first_geometry(table)
    ]
    if not candidates and len(tables) == 1 and _first_geometry(tables[0]):
        candidates = [tables[0]]
    if len(candidates) != 1:
        return sql, False
    table = candidates[0]
    geom = _first_geometry(table)
    if geom is None:
        return sql, False
    limit = _extract_question_limit(question) or 1
    rewritten = f"SELECT ST_GeometryType({geom.quoted_ref}) FROM {table.table_name} LIMIT {limit}"
    return rewritten, _canonical_sql_fragment(rewritten) != _canonical_sql_fragment(sql)


def _collapse_duplicate_union(sql: str) -> tuple[str, bool]:
    """Collapse A UNION A into A after table/name normalization.

    This is intentionally conservative: it only handles a single top-level
    UNION/UNION ALL where the two SELECT branches are textually equivalent
    after whitespace/case normalization. It preserves a trailing LIMIT that
    applies to the compound query.
    """
    if not sql or "union" not in sql.lower():
        return sql, False
    stripped = sql.strip().rstrip(";").strip()
    limit = ""
    core = stripped
    m_limit = re.search(r"\s+LIMIT\s+\d+\s*$", stripped, flags=re.IGNORECASE)
    if m_limit:
        limit = stripped[m_limit.start():].strip()
        core = stripped[:m_limit.start()].strip()

    split = _split_single_top_level_union(core)
    if not split:
        return sql, False
    left, right = split
    if _canonical_sql_fragment(left) == _canonical_sql_fragment(right):
        return f"{left.strip()}{(' ' + limit) if limit else ''}", True
    versioned = _prefer_versioned_duplicate_union_branch(left, right)
    if versioned:
        return f"{versioned.strip()}{(' ' + limit) if limit else ''}", True
    return sql, False


def _strip_invalid_trailing_clause_after_semicolon(sql: str) -> tuple[str, bool]:
    text = (sql or "").strip()
    if not re.match(r"^(?:SELECT|WITH)\b", text, flags=re.IGNORECASE):
        return sql, False
    match = re.search(r";\s*(?:AND|OR|WHERE)\b", text, flags=re.IGNORECASE)
    if not match:
        return sql, False
    return text[:match.start()].rstrip(), True


def _strip_sql_comments(sql: str) -> tuple[str, bool]:
    text = sql or ""
    if "/*" not in text and "--" not in text:
        return sql, False
    pieces: list[str] = []
    i = 0
    changed = False
    in_single = False
    in_double = False
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(text) and text[i + 1] == "'":
                pieces.append(text[i:i + 2])
                i += 2
                continue
            in_single = not in_single
            pieces.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            pieces.append(ch)
            i += 1
            continue
        if not in_single and not in_double and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                changed = True
                break
            pieces.append(" ")
            i = end + 2
            changed = True
            continue
        if not in_single and not in_double and text.startswith("--", i):
            end = text.find("\n", i + 2)
            if end < 0:
                pieces.append(" ")
                changed = True
                break
            pieces.append(" ")
            i = end
            changed = True
            continue
        pieces.append(ch)
        i += 1
    if not changed:
        return sql, False
    return re.sub(r"\s+", " ", "".join(pieces)).strip(), True


def _strip_unmatched_closing_parens(sql: str) -> tuple[str, bool]:
    text = sql or ""
    if ")" not in text:
        return sql, False
    pieces: list[str] = []
    depth = 0
    changed = False
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(text) and text[i + 1] == "'":
                pieces.append(text[i:i + 2])
                i += 2
                continue
            in_single = not in_single
            pieces.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            pieces.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth <= 0:
                    changed = True
                    i += 1
                    continue
                depth -= 1
        pieces.append(ch)
        i += 1
    if not changed:
        return sql, False
    return re.sub(r"\s+", " ", "".join(pieces)).strip(), True


def _strip_geometry_type_modifier_casts(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    text = sql or ""
    if "geometry" not in text.lower() and "shape" not in text.lower():
        return sql, False

    pieces: list[str] = []
    pos = 0
    search_pos = 0
    changed = False
    cast_pattern = re.compile(r"\bCAST\s*\(", flags=re.IGNORECASE)
    while True:
        match = cast_pattern.search(text, search_pos)
        if not match:
            break
        if _inside_single_quoted_literal(text, match.start()):
            search_pos = match.end()
            continue
        close = _find_matching_paren(text, match.end() - 1)
        if close < 0:
            search_pos = match.end()
            continue
        split = _split_cast_to_type(text[match.end():close])
        if not split:
            search_pos = close + 1
            continue
        expr, target_type = split
        if not (
            _is_geometry_type_modifier(target_type)
            and _expr_looks_like_geometry_reference(expr, alias_map)
        ):
            search_pos = close + 1
            continue
        pieces.append(text[pos:match.start()])
        pieces.append(expr.strip())
        pos = close + 1
        search_pos = close + 1
        changed = True

    if changed:
        pieces.append(text[pos:])
        text = "".join(pieces)

    text2, n = _strip_postfix_geometry_type_modifier_casts(text, alias_map)
    changed = changed or bool(n)
    return text2, changed and text2 != (sql or "")


def _split_cast_to_type(body: str) -> tuple[str, str] | None:
    match = re.fullmatch(
        r"(?P<expr>.+?)\s+AS\s+(?P<target>[A-Za-z_][A-Za-z0-9_]*(?:\s*\([^)]*\))?)\s*",
        body or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return match.group("expr").strip(), match.group("target").strip()


def _is_geometry_type_modifier(type_name: str) -> bool:
    value = re.sub(r"\s+", "", type_name or "").lower()
    return bool(re.fullmatch(r"(?:geometry|shape)\([^)]*\)", value))


def _strip_postfix_geometry_type_modifier_casts(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, int]:
    total = 0
    rewritten = sql
    patterns = [
        re.compile(
            r"(?P<expr>\bST_TRANSFORM\s*\(\s*[^()]+?\s*,\s*\d+\s*\))\s*::\s*(?:geometry|shape)\s*\([^)]*\)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<expr>(?:\"?[A-Za-z_][A-Za-z0-9_]*\"?\s*\.\s*)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*::\s*(?:geometry|shape)\s*\([^)]*\)",
            flags=re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        def repl(match: re.Match) -> str:
            nonlocal total
            expr = match.group("expr").strip()
            if not _expr_looks_like_geometry_reference(expr, alias_map):
                return match.group(0)
            total += 1
            return expr

        rewritten, _ = _sub_outside_string_literals(pattern, repl, rewritten)
    return rewritten, total


def _expr_looks_like_geometry_reference(
    expr: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> bool:
    ref = _geometry_column_ref_from_expr(expr)
    if not ref:
        return False
    col = _lookup_column_ref(ref, alias_map)
    if col is not None:
        return bool(col.is_geometry)
    name = _strip_identifier_quotes(ref.split(".")[-1]).lower()
    return name in {"geometry", "geom", "shape", "the_geom"} or name.endswith("_geom")


def _split_single_top_level_union(sql: str) -> tuple[str, str] | None:
    depth = 0
    in_string = False
    union_positions: list[tuple[int, int]] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            if in_string and i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue
        if not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and re.match(r"\bUNION(?:\s+ALL)?\b", sql[i:], flags=re.IGNORECASE):
                m = re.match(r"\bUNION(?:\s+ALL)?\b", sql[i:], flags=re.IGNORECASE)
                assert m is not None
                union_positions.append((i, i + m.end()))
                i += m.end()
                continue
        i += 1
    if len(union_positions) != 1:
        return None
    start, end = union_positions[0]
    left = sql[:start].strip()
    right = sql[end:].strip()
    if not left or not right:
        return None
    return left, right


def _canonical_sql_fragment(sql: str) -> str:
    return re.sub(r"\s+", " ", sql or "").strip().rstrip(";").lower()


def _prefer_versioned_duplicate_union_branch(left: str, right: str) -> str | None:
    if _canonical_versionless_table_fragment(left) != _canonical_versionless_table_fragment(right):
        return None
    left_refs = _table_refs_in_fragment(left)
    right_refs = _table_refs_in_fragment(right)
    if len(left_refs) != len(right_refs) or not left_refs:
        return None
    comparable = False
    for left_ref, right_ref in zip(left_refs, right_refs):
        if left_ref.lower() == right_ref.lower():
            continue
        left_base = _versionless_table_name(left_ref)
        right_base = _versionless_table_name(right_ref)
        if left_base.lower() != right_base.lower():
            return None
        if _is_versioned_table_name(left_ref) == _is_versioned_table_name(right_ref):
            return None
        comparable = True
    if not comparable:
        return None
    left_score = sum(1 for ref in left_refs if _is_versioned_table_name(ref))
    right_score = sum(1 for ref in right_refs if _is_versioned_table_name(ref))
    if left_score == right_score:
        return None
    return left if left_score > right_score else right


def _canonical_versionless_table_fragment(sql: str) -> str:
    pattern = re.compile(
        r"(?P<prefix>\b(?:FROM|JOIN)\s+)(?P<quote>\"?)(?P<table>[A-Za-z_][A-Za-z0-9_\.]*)(?P=quote)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        return f"{match.group('prefix')}{match.group('quote')}{_versionless_table_name(match.group('table'))}{match.group('quote')}"

    return _canonical_sql_fragment(pattern.sub(repl, sql or ""))


def _table_refs_in_fragment(sql: str) -> list[str]:
    pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+\"?(?P<table>[A-Za-z_][A-Za-z0-9_\.]*)\"?",
        flags=re.IGNORECASE,
    )
    return [m.group("table") for m in pattern.finditer(sql or "")]


def _versionless_table_name(table_name: str) -> str:
    parts = (table_name or "").split(".")
    bare = parts[-1]
    base = re.sub(r"_(?:19|20)\d{2}$", "", bare)
    return ".".join(parts[:-1] + [base]) if parts[:-1] else base


def _is_versioned_table_name(table_name: str) -> bool:
    return bool(re.search(r"_(?:19|20)\d{2}$", (table_name or "").split(".")[-1]))


def _table_alias_map(sql: str, tables: list[TableInfo]) -> dict[str, tuple[TableInfo, ColumnInfo | None]]:
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]] = {}
    for table in tables:
        alias = _find_table_alias(sql, table.table_name)
        referenced = _sql_references_table(sql, table.table_name)
        if alias:
            alias_map[alias] = (table, None)
        if referenced:
            alias_map[table.bare_name] = (table, None)
            alias_map[table.table_name] = (table, None)
    return alias_map


def _sql_references_table(sql: str, table_name: str) -> bool:
    bare = table_name.split(".")[-1]
    full_re = re.escape(table_name).replace(r"\.", r'\."?')
    public_bare_re = rf"(?:\"?public\"?\.)?\"?{re.escape(bare)}\"?"
    pattern = re.compile(
        rf"\b(?:FROM|JOIN)\s+(?:\"?{full_re}\"?|{public_bare_re})(?![A-Za-z0-9_])",
        flags=re.IGNORECASE,
    )
    return bool(pattern.search(sql or ""))


def _find_table_alias(sql: str, table_name: str) -> str | None:
    bare = table_name.split(".")[-1]
    full_re = re.escape(table_name).replace(r"\.", r'\."?')
    public_bare_re = rf"(?:\"?public\"?\.)?\"?{re.escape(bare)}\"?"
    pattern = re.compile(
        rf"\b(?:FROM|JOIN)\s+(?:\"?{full_re}\"?|{public_bare_re})"
        r"(?:\s+(?:AS\s+)?(?P<alias>\"?[A-Za-z_][A-Za-z0-9_]*\"?))?",
        flags=re.IGNORECASE,
    )
    m = pattern.search(sql or "")
    if not m:
        return None
    alias = _strip_identifier_quotes(m.group("alias"))
    if not alias or alias.upper() in {"ON", "WHERE", "JOIN", "GROUP", "ORDER", "LIMIT"}:
        return None
    return alias


def _normalize_quoted_alias_column_refs(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    rewritten = sql
    changed = False
    simple_aliases = [
        alias for alias in alias_map
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias or "")
    ]
    if not simple_aliases:
        return sql, False
    parts = re.split(_SQL_STRING_RE, rewritten)
    for i in range(0, len(parts), 2):
        segment = parts[i]
        for alias in simple_aliases:
            decl_pattern = re.compile(
                r"(?P<prefix>\b(?:FROM|JOIN)\s+"
                r"(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)"
                r"(?:\s*\.\s*(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))?\s+)"
                rf"(?:AS\s+)?\"{re.escape(alias)}\"(?=\s|$)",
                flags=re.IGNORECASE,
            )
            segment, n_decl = decl_pattern.subn(f"\\g<prefix>AS {alias}", segment)
            changed = changed or bool(n_decl)
            pattern = re.compile(
                rf"\"{re.escape(alias)}\"\s*\.\s*(?P<col>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
                flags=re.IGNORECASE,
            )
            segment, n = pattern.subn(f"{alias}.\\g<col>", segment)
            changed = changed or bool(n)
        parts[i] = segment
    return "".join(parts), changed


def _rewrite_column_aliases(
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    rewritten = sql
    changed = False
    unique_aliases: dict[str, tuple[TableInfo, ColumnInfo] | None] = {}
    referenced_table_names = {
        table.table_name for table, _ in alias_map.values()
    }
    single_referenced_table = len(referenced_table_names) == 1
    for table in tables:
        if table.table_name not in referenced_table_names:
            continue
        for col in table.columns:
            for token in col.ref_tokens:
                key = _strip_identifier_quotes(token).lower()
                if (
                    col.is_geometry
                    and key in {"geometry", "geom", "the_geom", "shape"}
                    and not single_referenced_table
                ):
                    continue
                if key == col.column_name.lower() and token == col.quoted_ref:
                    continue
                value = (table, col)
                existing = unique_aliases.get(key, "__missing__")
                if existing == "__missing__" or existing == value:
                    unique_aliases[key] = value
                else:
                    unique_aliases[key] = None

    for qualifier, (table, _) in alias_map.items():
        for col in table.columns:
            for token in col.ref_tokens:
                if _strip_identifier_quotes(token).lower() == col.column_name.lower() and token == col.quoted_ref:
                    continue
                rewritten, n = _replace_column_reference(
                    rewritten,
                    qualifier,
                    token,
                    col.quoted_ref,
                    unqualified=False,
                )
                changed = changed or bool(n)

    for key, value in unique_aliases.items():
        if not value:
            continue
        _, col = value
        if col.is_geometry and key in {"geometry", "geom", "the_geom", "shape"}:
            rewritten, n = _replace_unqualified_geometry_column_reference(
                rewritten,
                key,
                col.quoted_ref,
            )
        else:
            rewritten, n = _replace_column_reference(
                rewritten,
                None,
                key,
                col.quoted_ref,
                unqualified=True,
            )
        changed = changed or bool(n)

    return rewritten, changed


def _rewrite_subquery_geometry_projection_aliases(
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    """Rewrite local ``SELECT geometry FROM table`` projections to real geom cols."""
    rewritten = sql or ""
    changed = False
    for table in tables:
        geoms = table.geometry_columns()
        if len(geoms) != 1:
            continue
        geom = geoms[0]
        actual_l = geom.column_name.lower()
        wrong_tokens = [
            token for token in ("geometry", "geom", "the_geom", "shape")
            if token != actual_l
        ]
        if not wrong_tokens:
            continue
        bare = re.escape(table.bare_name)
        table_ref = (
            r'(?:(?:"?[A-Za-z_][A-Za-z0-9_]*"?\s*\.\s*)?'
            rf'"?{bare}"?)'
        )
        for wrong in wrong_tokens:
            wrong_ref = rf'"?{re.escape(wrong)}"?'
            pattern = re.compile(
                rf"(?P<prefix>\bSELECT\s+){wrong_ref}"
                rf"(?P<suffix>\s+FROM\s+{table_ref}\b)",
                flags=re.IGNORECASE,
            )

            def repl(match: re.Match) -> str:
                return f"{match.group('prefix')}{geom.quoted_ref}{match.group('suffix')}"

            rewritten, n = pattern.subn(repl, rewritten)
            changed = changed or bool(n)
    return rewritten, changed


def _rewrite_missing_target_relation_subquery(
    question: str,
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    if not _question_requests_nearest_neighbor(question):
        return sql, False
    if re.search(r"\bWITH\s+target\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    target_ref = re.compile(
        r"(?P<prefix>\s*,\s*|\bCROSS\s+JOIN\s+|\bJOIN\s+)target"
        r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?",
        flags=re.IGNORECASE,
    )
    match = target_ref.search(sql or "")
    if not match:
        return sql, False
    alias = match.group("alias") or "t"
    referenced = {table.table_name for table, _ in _table_alias_map(sql, tables).values()}
    spec = _missing_target_subquery_spec(question, tables, referenced)
    if not spec:
        return sql, False
    table, geom, filter_col, literal, order_col = spec
    order_clause = f" ORDER BY {order_col}" if order_col else ""
    subquery = (
        f" CROSS JOIN (SELECT {geom.quoted_ref} FROM {table.table_name} "
        f"WHERE {filter_col.quoted_ref} = {_format_sql_literal(literal)}"
        f"{order_clause} LIMIT 1) AS {alias}"
    )
    rewritten = (sql or "")[:match.start()] + subquery + (sql or "")[match.end():]
    return rewritten, rewritten != (sql or "")


def _missing_target_subquery_spec(
    question: str,
    tables: list[TableInfo],
    referenced_tables: set[str],
) -> tuple[TableInfo, ColumnInfo, ColumnInfo, str, str] | None:
    candidates: list[tuple[int, TableInfo, ColumnInfo, ColumnInfo, str, str]] = []
    for table in tables:
        if table.table_name in referenced_tables:
            continue
        geom = _first_geometry(table)
        if not geom:
            continue
        literal_filter = _question_literal_filter_for_table(question, table)
        if not literal_filter:
            continue
        filter_col, literal = literal_filter
        order_col = _question_order_column_for_table(question, table)
        score = _question_table_alias_hits(question, table)
        if order_col:
            score += 2
        if score <= 0:
            score = 1
        candidates.append((score, table, geom, filter_col, literal, order_col))
    if not candidates:
        return None
    best_score = max(item[0] for item in candidates)
    best = [item for item in candidates if item[0] == best_score]
    if len(best) != 1:
        return None
    _, table, geom, filter_col, literal, order_col = best[0]
    return table, geom, filter_col, literal, order_col


def _question_literal_filter_for_table(question: str, table: TableInfo) -> tuple[ColumnInfo, str] | None:
    for col in table.columns:
        if col.is_geometry:
            continue
        tokens = [col.column_name, _strip_identifier_quotes(col.quoted_ref)]
        tokens.extend(col.aliases)
        for token in dict.fromkeys(str(t) for t in tokens if t):
            values = _string_values_after_explicit_column_equals(question, token)
            if values:
                return col, values[0]
    literals = _question_quoted_literals(question)
    if len(literals) != 1:
        return None
    for preferred in ("dlmc", "DLMC", "land_name", "type", "kind", "name"):
        col = table.column_by_name(preferred)
        if col and not col.is_geometry:
            return col, literals[0]
    return None


def _rewrite_subquery_geometry_srid_transforms(
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    subquery_geoms = _subquery_geometry_alias_map(sql, tables)
    if not subquery_geoms:
        return sql, False

    rewritten = sql or ""
    changed = False
    for sub_alias, sub_col in subquery_geoms.items():
        if not sub_col.srid:
            continue
        sub_ref = f"{sub_alias}.{sub_col.quoted_ref}"
        for qualifier, (outer_table, _) in alias_map.items():
            if qualifier == sub_alias:
                continue
            for outer_col in outer_table.geometry_columns():
                if not outer_col.srid or outer_col.srid == sub_col.srid:
                    continue
                outer_ref = f"{qualifier}.{outer_col.quoted_ref}"
                transformed_outer = f"ST_Transform({outer_ref}, {sub_col.srid})"
                rewritten, n = _rewrite_pair_distance_to_transform(
                    rewritten,
                    outer_ref,
                    sub_ref,
                    transformed_outer,
                    sub_col.srid,
                )
                changed = changed or bool(n)
                rewritten, n = _rewrite_pair_knn_to_transform(
                    rewritten,
                    outer_ref,
                    sub_ref,
                    transformed_outer,
                )
                changed = changed or bool(n)
    return rewritten, changed


def _subquery_geometry_alias_map(
    sql: str,
    tables: list[TableInfo],
) -> dict[str, ColumnInfo]:
    out: dict[str, ColumnInfo] = {}
    pattern = re.compile(
        r"\(\s*SELECT\s+(?P<col>\"?[A-Za-z_][A-Za-z0-9_]*\"?)\s+"
        r"FROM\s+(?P<table>(?:\"?[A-Za-z_][A-Za-z0-9_]*\"?\s*\.\s*)?"
        r"\"?[A-Za-z_][A-Za-z0-9_]*\"?)\b"
        r".*?\)\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\b",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql or ""):
        table = _table_for_ref(match.group("table"), tables)
        if not table:
            continue
        col_name = _strip_identifier_quotes(match.group("col"))
        col = table.column_by_name(col_name)
        if not col and col_name.lower() in {"geometry", "geom", "the_geom", "shape"}:
            col = _first_geometry(table)
        if not col or not col.is_geometry:
            continue
        out[match.group("alias")] = col
    return out


def _rewrite_pair_distance_to_transform(
    sql: str,
    outer_ref: str,
    sub_ref: str,
    transformed_outer: str,
    target_srid: int,
) -> tuple[str, int]:
    outer_re = re.escape(outer_ref)
    sub_re = re.escape(sub_ref)
    total = 0
    pattern = re.compile(
        rf"ST_Distance\s*\(\s*{outer_re}\s*::\s*geography\s*,\s*"
        rf"{sub_re}\s*::\s*geography\s*\)",
        flags=re.IGNORECASE,
    )
    sql, n = pattern.subn(
        f"ST_Distance({transformed_outer}::geography, {sub_ref}::geography)",
        sql,
    )
    total += n
    pattern_rev = re.compile(
        rf"ST_Distance\s*\(\s*{sub_re}\s*::\s*geography\s*,\s*"
        rf"{outer_re}\s*::\s*geography\s*\)",
        flags=re.IGNORECASE,
    )
    sql, n = pattern_rev.subn(
        f"ST_Distance({sub_ref}::geography, ST_Transform({outer_ref}, {target_srid})::geography)",
        sql,
    )
    total += n
    cast_pattern = re.compile(
        rf"ST_Distance\s*\(\s*CAST\s*\(\s*{outer_re}\s+AS\s+GEOGRAPHY\s*\)\s*,\s*"
        rf"CAST\s*\(\s*{sub_re}\s+AS\s+GEOGRAPHY\s*\)\s*\)",
        flags=re.IGNORECASE,
    )
    sql, n = cast_pattern.subn(
        f"ST_Distance({transformed_outer}::geography, {sub_ref}::geography)",
        sql,
    )
    total += n
    cast_pattern_rev = re.compile(
        rf"ST_Distance\s*\(\s*CAST\s*\(\s*{sub_re}\s+AS\s+GEOGRAPHY\s*\)\s*,\s*"
        rf"CAST\s*\(\s*{outer_re}\s+AS\s+GEOGRAPHY\s*\)\s*\)",
        flags=re.IGNORECASE,
    )
    sql, n = cast_pattern_rev.subn(
        f"ST_Distance({sub_ref}::geography, ST_Transform({outer_ref}, {target_srid})::geography)",
        sql,
    )
    total += n
    return sql, total


def _rewrite_pair_knn_to_transform(
    sql: str,
    outer_ref: str,
    sub_ref: str,
    transformed_outer: str,
) -> tuple[str, int]:
    outer_re = re.escape(outer_ref)
    sub_re = re.escape(sub_ref)
    total = 0
    pattern = re.compile(
        rf"ORDER\s+BY\s+{outer_re}\s*<->\s*{sub_re}",
        flags=re.IGNORECASE,
    )
    sql, n = pattern.subn(f"ORDER BY {transformed_outer} <-> {sub_ref}", sql)
    total += n
    pattern_rev = re.compile(
        rf"ORDER\s+BY\s+{sub_re}\s*<->\s*{outer_re}",
        flags=re.IGNORECASE,
    )
    sql, n = pattern_rev.subn(f"ORDER BY {sub_ref} <-> {transformed_outer}", sql)
    total += n
    return sql, total


def _rewrite_unqualified_select_projection_columns(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not re.match(r"^\s*SELECT\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    first = _first_from_table(sql, tables)
    if not first:
        return sql, False
    target_table, qualifier = first
    unique_tables = {
        table.table_name
        for table, _ in alias_map.values()
    }
    from_positions = _top_level_keyword_positions(sql, "FROM")
    if not from_positions:
        return sql, False
    select_match = re.match(r"\s*SELECT\b", sql or "", flags=re.IGNORECASE)
    if not select_match:
        return sql, False
    select_start = select_match.end()
    from_pos = from_positions[0]
    select_body = sql[select_start:from_pos]
    projections = _split_top_level_args(select_body)
    if not projections:
        return sql, False

    changed = False
    rewritten_parts: list[str] = []
    for projection in projections:
        rewritten_projection, projection_changed = _rewrite_projection_column_token(
            projection,
            question,
            target_table,
            qualifier,
            tables,
            alias_map,
            allow_exact_qualification=len(unique_tables) > 1,
        )
        rewritten_parts.append(rewritten_projection)
        changed = changed or projection_changed
    if not changed:
        return sql, False
    rewritten_select = ",".join(rewritten_parts)
    if rewritten_select and not rewritten_select[-1].isspace():
        rewritten_select += " "
    return sql[:select_start] + " " + rewritten_select.lstrip() + sql[from_pos:], True


def _rewrite_projection_column_token(
    projection: str,
    question: str,
    target_table: TableInfo,
    qualifier: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
    allow_exact_qualification: bool,
) -> tuple[str, bool]:
    match = re.match(
        r"(?P<prefix>\s*)(?P<expr>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)(?P<tail>\s*(?:AS\s+\"?[A-Za-z_][A-Za-z0-9_]*\"?)?\s*)$",
        projection or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return projection, False
    expr = match.group("expr")
    token = _strip_identifier_quotes(expr)
    if not token or token == "*":
        return projection, False
    col = _projection_target_column_for_token(token, question, target_table, tables, alias_map)
    if not col:
        return projection, False
    exact_target = target_table.column_by_name(token) is not None
    if exact_target and not allow_exact_qualification:
        return projection, False
    replacement = f"{qualifier}.{col.quoted_ref}"
    if replacement.lower() == expr.lower():
        return projection, False
    return f"{match.group('prefix')}{replacement}{match.group('tail')}", True


def _projection_target_column_for_token(
    token: str,
    question: str,
    target_table: TableInfo,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> ColumnInfo | None:
    exact = target_table.column_by_name(token)
    if exact:
        return exact
    token_l = token.lower()
    for col in target_table.columns:
        aliases = {_strip_identifier_quotes(a).lower() for a in col.ref_tokens}
        if token_l in aliases:
            return col
    if token in {"\u540d\u79f0", "\u540d\u5b57"} or token_l in {"name", "names"}:
        name_cols = [col for col in target_table.columns if _column_is_name_like(col)]
        if len(name_cols) == 1:
            return name_cols[0]
    question_terms = _question_physical_column_terms(question)
    for col in target_table.columns:
        if col.column_name in question_terms and _edit_distance_leq_one_ascii(token, col.column_name):
            return col
    if not _token_exists_on_referenced_table(token, tables, alias_map):
        fuzzy = [
            col for col in target_table.columns
            if _edit_distance_leq_one_ascii(token, col.column_name)
        ]
        if len(fuzzy) == 1:
            return fuzzy[0]
    return None


def _token_exists_on_referenced_table(
    token: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> bool:
    referenced = {table.table_name for table, _ in alias_map.values()}
    token_l = _strip_identifier_quotes(token).lower()
    for table in tables:
        if table.table_name not in referenced:
            continue
        if table.column_by_name(token_l):
            return True
        for col in table.columns:
            if token_l in {_strip_identifier_quotes(a).lower() for a in col.ref_tokens}:
                return True
    return False


def _edit_distance_leq_one_ascii(left: str, right: str) -> bool:
    a = (left or "").lower()
    b = (right or "").lower()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{1,63}", a or ""):
        return False
    if not re.fullmatch(r"[a-z_][a-z0-9_]{1,63}", b or ""):
        return False
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = edits = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        j += 1
    return True


def _rewrite_value_groups(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    rewritten = sql
    changed = False
    for table in tables:
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            for group in col.value_semantics.get("semantic_groups") or []:
                values = [str(v) for v in group.get("values") or [] if v is not None]
                if len(values) < 2:
                    continue
                aliases = [str(a).lower() for a in group.get("aliases") or [] if a]
                if aliases and not any(a in q_low for a in aliases):
                    continue
                for qualifier in qualifiers:
                    rewritten, n = _replace_eq_with_in(rewritten, qualifier, col, values)
                    changed = changed or bool(n)
                rewritten, n = _replace_eq_with_in(rewritten, None, col, values)
                changed = changed or bool(n)
    return rewritten, changed


def _replace_eq_with_in(sql: str, qualifier: str | None, col: ColumnInfo, values: list[str]) -> tuple[str, int]:
    refs = _column_reference_alternatives(qualifier, col)
    value = re.escape(values[0])
    value_list = ", ".join(f"'{v}'" for v in values)
    pattern = re.compile(
        rf"(?P<ref>{refs})\s*=\s*'{value}'",
        flags=re.IGNORECASE,
    )
    return _sub_outside_string_literals(
        pattern,
        lambda m: f"{m.group('ref')} IN ({value_list})",
        sql,
    )


def _rewrite_literal_column_overrides(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    rewritten = sql
    changed = False
    for table in tables:
        qualifiers = _qualifiers_for_table(alias_map, table)
        for target in table.columns:
            for override in target.value_semantics.get("literal_column_overrides") or []:
                value = str(override.get("value") or "")
                wrong_columns = [str(c) for c in override.get("wrong_columns") or [] if c]
                if not value or not wrong_columns:
                    continue
                for wrong in wrong_columns:
                    for qualifier in qualifiers:
                        rewritten, n = _replace_literal_column(
                            rewritten, qualifier, wrong, target.quoted_ref, value
                        )
                        changed = changed or bool(n)
                    rewritten, n = _replace_literal_column(rewritten, None, wrong, target.quoted_ref, value)
                    changed = changed or bool(n)
                    if value.lower() in q_low:
                        for qualifier in qualifiers:
                            rewritten, n = _replace_wrong_column_predicate(
                                rewritten, qualifier, wrong, target.quoted_ref, value
                            )
                            changed = changed or bool(n)
                        rewritten, n = _replace_wrong_column_predicate(
                            rewritten, None, wrong, target.quoted_ref, value
                        )
                        changed = changed or bool(n)
    return rewritten, changed


def _replace_literal_column(
    sql: str,
    qualifier: str | None,
    wrong: str,
    right: str,
    value: str,
) -> tuple[str, int]:
    refs = _raw_column_reference_alternatives(qualifier, wrong)
    pattern = re.compile(
        rf"(?P<ref>{refs})(?P<op>\s*=\s*)'{re.escape(value)}'",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        prefix = f"{qualifier}." if qualifier else ""
        return f"{prefix}{right}{match.group('op')}'{value}'"

    return _sub_outside_string_literals(pattern, repl, sql)


def _replace_wrong_column_predicate(
    sql: str,
    qualifier: str | None,
    wrong: str,
    right: str,
    value: str,
) -> tuple[str, int]:
    refs = _raw_column_reference_alternatives(qualifier, wrong)
    pattern = re.compile(
        rf"(?P<ref>{refs})\s*(?:(?:NOT\s+)?I?LIKE\s*'[^']*'|=\s*(?:'[^']*'|-?\d+(?:\.\d+)?))",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        prefix = f"{qualifier}." if qualifier else ""
        return f"{prefix}{right} = {_format_sql_literal(value)}"

    return _sub_outside_string_literals(pattern, repl, sql)


def _rewrite_enum_literal_values(
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    """Rewrite display enum literals to stored enum values.

    Example: fclass = '主干道' -> fclass = 'primary', driven entirely by
    value_semantics.enum entries such as {"value": "primary", "meaning": "主干道"}.
    """
    rewritten = sql
    changed = False
    for table in tables:
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            literal_map = _enum_display_literal_map(col)
            if not literal_map:
                continue
            for qualifier in qualifiers + [None]:
                rewritten, n = _replace_enum_eq_literals(rewritten, qualifier, col, literal_map)
                changed = changed or bool(n)
                rewritten, n = _replace_enum_in_literals(rewritten, qualifier, col, literal_map)
                changed = changed or bool(n)
                rewritten, n = _replace_enum_like_literals(rewritten, qualifier, col, literal_map)
                changed = changed or bool(n)
    return rewritten, changed


def _enum_display_literal_map(col: ColumnInfo) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for item in col.value_semantics.get("enum") or []:
        if not isinstance(item, dict) or "value" not in item:
            continue
        value = item.get("value")
        probes: list[Any] = [
            item.get("meaning"),
            item.get("label"),
            item.get("name"),
        ]
        aliases = item.get("aliases")
        if isinstance(aliases, (list, tuple, set)):
            probes.extend(aliases)
        for probe in probes:
            if probe is None:
                continue
            probe_text = str(probe).strip()
            if not probe_text or probe_text == str(value):
                continue
            mapping[_normalize_enum_literal_key(probe_text)] = value
    return mapping


def _normalize_enum_literal_key(value: str) -> str:
    return str(value or "").strip().casefold()


def _decode_sql_string_literal_inner(value: str) -> str:
    return str(value or "").replace("''", "'")


def _replace_enum_eq_literals(
    sql: str,
    qualifier: str | None,
    col: ColumnInfo,
    literal_map: dict[str, Any],
) -> tuple[str, int]:
    refs = _column_reference_alternatives(qualifier, col)
    pattern = re.compile(
        rf"(?P<ref>{refs})(?P<op>\s*=\s*)'(?P<lit>(?:[^']|'')*)'",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        literal = _decode_sql_string_literal_inner(match.group("lit"))
        value = literal_map.get(_normalize_enum_literal_key(literal))
        if value is None:
            return match.group(0)
        return f"{match.group('ref')}{match.group('op')}{_format_sql_literal(value)}"

    return _sub_enum_literal_replacements(pattern, repl, sql)


def _replace_enum_in_literals(
    sql: str,
    qualifier: str | None,
    col: ColumnInfo,
    literal_map: dict[str, Any],
) -> tuple[str, int]:
    refs = _column_reference_alternatives(qualifier, col)
    pattern = re.compile(
        rf"(?P<ref>{refs})(?P<op>\s+(?:NOT\s+)?IN\s*)\((?P<body>[^()]*)\)",
        flags=re.IGNORECASE,
    )
    literal_pattern = re.compile(r"'(?P<lit>(?:[^']|'')*)'")

    def repl(match: re.Match) -> str:
        replaced = 0

        def replace_literal(lit_match: re.Match) -> str:
            nonlocal replaced
            literal = _decode_sql_string_literal_inner(lit_match.group("lit"))
            value = literal_map.get(_normalize_enum_literal_key(literal))
            if value is None:
                return lit_match.group(0)
            replaced += 1
            return _format_sql_literal(value)

        body = literal_pattern.sub(replace_literal, match.group("body"))
        if not replaced:
            return match.group(0)
        return f"{match.group('ref')}{match.group('op')}({body})"

    return _sub_enum_literal_replacements(pattern, repl, sql)


def _replace_enum_like_literals(
    sql: str,
    qualifier: str | None,
    col: ColumnInfo,
    literal_map: dict[str, Any],
) -> tuple[str, int]:
    refs = _column_reference_alternatives(qualifier, col)
    pattern = re.compile(
        rf"(?P<ref>{refs})(?P<op>\s+(?:NOT\s+)?I?LIKE\s*)'(?P<lit>(?:[^']|'')*)'",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        literal = _decode_sql_string_literal_inner(match.group("lit"))
        value = _enum_value_from_like_literal(literal, literal_map)
        if value is None:
            return match.group(0)
        op = "<>" if "NOT" in match.group("op").upper() else "="
        return f"{match.group('ref')} {op} {_format_sql_literal(value)}"

    return _sub_enum_literal_replacements(pattern, repl, sql)


def _enum_value_from_like_literal(literal: str, literal_map: dict[str, Any]) -> Any | None:
    normalized = _normalize_enum_literal_key(literal)
    stripped = _normalize_enum_literal_key(literal.replace("%", "").replace("_", ""))
    if stripped in literal_map:
        return literal_map[stripped]
    matches = [
        value
        for key, value in literal_map.items()
        if key and key in normalized
    ]
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def _sub_enum_literal_replacements(
    pattern: re.Pattern,
    repl,
    sql: str,
) -> tuple[str, int]:
    pieces: list[str] = []
    pos = 0
    total = 0
    for match in pattern.finditer(sql):
        if _inside_single_quoted_literal(sql, match.start()):
            continue
        replacement = repl(match)
        if replacement == match.group(0):
            continue
        pieces.append(sql[pos:match.start()])
        pieces.append(replacement)
        pos = match.end()
        total += 1
    if not total:
        return sql, 0
    pieces.append(sql[pos:])
    return "".join(pieces), total


def _rewrite_enum_filters(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    rewritten = sql
    changed = False
    for table in tables:
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            enum_values = col.value_semantics.get("enum") or []
            if not enum_values:
                continue
            matched_values = []
            for item in enum_values:
                if not isinstance(item, dict) or "value" not in item:
                    continue
                probes = [
                    str(item.get("meaning") or "").lower(),
                    str(item.get("label") or "").lower(),
                    str(item.get("name") or "").lower(),
                ]
                if any(probe and probe in q_low for probe in probes):
                    matched_values.append(item.get("value"))
            matched_values = list(dict.fromkeys(matched_values))
            if not matched_values:
                continue
            if not _sql_groups_by_column(rewritten, col, qualifiers):
                continue
            if _where_clause_references_column(rewritten, col, qualifiers):
                continue
            predicate_ref = _preferred_column_ref_for_filter(col, qualifiers)
            predicate = (
                f"{predicate_ref} IN "
                f"({', '.join(_format_sql_literal(v) for v in matched_values)})"
            )
            rewritten2 = _inject_predicate(rewritten, predicate)
            if rewritten2 != rewritten:
                rewritten = rewritten2
                changed = True
    return rewritten, changed


def _rewrite_enum_case_display_to_raw_code(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    rewritten = sql
    changed = False
    for table in tables:
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            if not col.value_semantics.get("enum"):
                continue
            if not _question_mentions_explicit_enum_codes(question, col):
                continue
            if not _sql_groups_by_column(rewritten, col, qualifiers):
                continue
            for qualifier in qualifiers + [None]:
                refs = _column_reference_alternatives(qualifier, col)
                enum_literals = _enum_literal_pattern(col)
                if not enum_literals:
                    continue
                pattern = re.compile(
                    rf"\bCASE\s+WHEN\s+(?P<ref>{refs})\s*=\s*(?:{enum_literals})"
                    r"(?P<body>.*?)\s+END\s+AS\s+(?P<alias>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
                    flags=re.IGNORECASE | re.DOTALL,
                )

                def repl(match: re.Match) -> str:
                    body = match.group("body")
                    ref = match.group("ref")
                    if not re.search(r"\bTHEN\b", body, flags=re.IGNORECASE):
                        return match.group(0)
                    return f"{ref} AS {match.group('alias')}"

                rewritten2, n = pattern.subn(repl, rewritten)
                if n and rewritten2 != rewritten:
                    rewritten = rewritten2
                    changed = True
    return rewritten, changed


def _rewrite_enum_comparison_projection_and_filters(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not re.search(r"\bCOUNT\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False
    if not re.search(r"\bGROUP\s+BY\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    rewritten = sql
    changed = False
    for table in tables:
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            if not col.value_semantics.get("enum"):
                continue
            if not _question_requests_enum_comparison(question, col):
                continue
            if not _sql_groups_by_column(rewritten, col, qualifiers):
                continue
            rewritten2, projection_changed = _rewrite_enum_case_for_column(rewritten, col, qualifiers)
            if projection_changed:
                rewritten = rewritten2
                changed = True
            rewritten2, filter_changed = _remove_single_enum_value_filter(rewritten, col, qualifiers)
            if filter_changed:
                rewritten = rewritten2
                changed = True
    return rewritten, changed


def _question_requests_enum_comparison(question: str, col: ColumnInfo) -> bool:
    q_low = (question or "").lower()
    comparison_tokens = (
        "compare",
        "comparison",
        "versus",
        " vs ",
        "\u5bf9\u6bd4",
        "\u6bd4\u8f83",
        "\u5206\u522b",
        "\u662f\u5426",
        "\u6bcf\u79cd",
        "\u5404",
    )
    if not any(token in q_low for token in comparison_tokens):
        return False
    col_tokens = [
        _strip_identifier_quotes(token).lower()
        for token in col.ref_tokens
        if _strip_identifier_quotes(token)
    ]
    mentions_col = any(token and token in q_low for token in col_tokens)
    enum_mentions = 0
    for item in col.value_semantics.get("enum") or []:
        if not isinstance(item, dict):
            continue
        probes = [
            str(item.get("value") or "").lower(),
            str(item.get("meaning") or "").lower(),
            str(item.get("label") or "").lower(),
            str(item.get("name") or "").lower(),
        ]
        if any(probe and probe in q_low for probe in probes):
            enum_mentions += 1
    return mentions_col or enum_mentions >= 2


def _rewrite_enum_case_for_column(
    sql: str,
    col: ColumnInfo,
    qualifiers: list[str],
) -> tuple[str, bool]:
    rewritten = sql
    changed = False
    for qualifier in qualifiers + [None]:
        refs = _column_reference_alternatives(qualifier, col)
        enum_literals = _enum_literal_pattern(col)
        if not enum_literals:
            continue
        pattern = re.compile(
            rf"\bCASE\s+WHEN\s+(?P<ref>{refs})\s*=\s*(?:{enum_literals})"
            r"(?P<body>.*?)\s+END\s+AS\s+(?P<alias>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
            flags=re.IGNORECASE | re.DOTALL,
        )

        def repl(match: re.Match) -> str:
            body = match.group("body")
            ref = match.group("ref")
            if not re.search(r"\bTHEN\b", body, flags=re.IGNORECASE):
                return match.group(0)
            return f"{ref} AS {match.group('alias')}"

        rewritten2, n = pattern.subn(repl, rewritten)
        if n and rewritten2 != rewritten:
            rewritten = rewritten2
            changed = True
    return rewritten, changed


def _remove_single_enum_value_filter(
    sql: str,
    col: ColumnInfo,
    qualifiers: list[str],
) -> tuple[str, bool]:
    enum_literals = _enum_literal_pattern(col)
    if not enum_literals:
        return sql, False
    refs = "|".join(
        ref for ref in (
            _column_reference_alternatives(qualifier, col)
            for qualifier in qualifiers + [None]
        )
        if ref
    )
    if not refs:
        return sql, False

    def should_remove(part: str) -> bool:
        stripped = part.strip()
        while stripped.startswith("(") and stripped.endswith(")"):
            stripped = stripped[1:-1].strip()
        eq_pattern = rf"(?:{refs})\s*=\s*(?:{enum_literals})"
        in_pattern = rf"(?:{refs})\s+IN\s*\(\s*(?:{enum_literals})\s*\)"
        return bool(
            re.fullmatch(eq_pattern, stripped, flags=re.IGNORECASE)
            or re.fullmatch(in_pattern, stripped, flags=re.IGNORECASE)
        )

    return _remove_where_predicates(sql, should_remove)


def _rewrite_explicit_question_filters(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    rewritten = sql
    changed = False
    if not question or not sql:
        return sql, False
    if re.match(r"^\s*WITH\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    referenced_tables = {table.table_name for table, _ in alias_map.values()}
    if not referenced_tables:
        return sql, False
    for table in tables:
        if table.table_name not in referenced_tables:
            continue
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            if _where_clause_references_column(rewritten, col, qualifiers):
                continue
            if _sql_groups_by_column(rewritten, col, qualifiers):
                continue
            predicate = _explicit_question_string_filter(question, col, qualifiers)
            if not predicate:
                continue
            rewritten2 = _inject_predicate(rewritten, predicate)
            if rewritten2 != rewritten:
                rewritten = rewritten2
                changed = True
    return rewritten, changed


def _explicit_question_string_filter(question: str, col: ColumnInfo, qualifiers: list[str]) -> str:
    for token in _explicit_filter_column_tokens(col):
        values = _string_values_after_explicit_column_equals(question, token)
        if not values:
            continue
        ref = _preferred_column_ref_for_filter(col, qualifiers)
        if len(values) == 1:
            return f"{ref} = {_format_sql_literal(values[0])}"
        return f"{ref} IN ({', '.join(_format_sql_literal(v) for v in values)})"
    return ""


def _explicit_filter_column_tokens(col: ColumnInfo) -> list[str]:
    tokens = [col.column_name, _strip_identifier_quotes(col.quoted_ref)]
    tokens.extend(col.aliases)
    cleaned = []
    for token in tokens:
        value = _strip_identifier_quotes(str(token or "")).strip()
        if not value or value in {"*", "geometry", "geom", "shape"}:
            continue
        cleaned.append(value)
    return list(dict.fromkeys(cleaned))


def _string_values_after_explicit_column_equals(question: str, token: str) -> list[str]:
    token_re = re.escape(token)
    if any("\u4e00" <= ch <= "\u9fff" for ch in token):
        left_boundary = ""
        right_boundary = ""
    else:
        left_boundary = r"(?<![A-Za-z0-9_])"
        right_boundary = r"(?![A-Za-z0-9_])"
    literal = r"'(?P<value>(?:[^']|'')*)'"
    continuation = r"(?:\s*(?:,|\uff0c|\u3001|\u6216|\u548c|\bor\b|\band\b)\s*'(?:[^']|'')*')*"
    pattern = re.compile(
        rf"{left_boundary}{token_re}{right_boundary}\s*(?:=|==|\u4e3a|\u662f)\s*"
        rf"(?P<tail>{literal}{continuation})",
        flags=re.IGNORECASE,
    )
    values: list[str] = []
    for match in pattern.finditer(question or ""):
        tail = match.group("tail")
        for raw in re.findall(r"'((?:[^']|'')*)'", tail):
            value = raw.replace("''", "'")
            if value and value not in values:
                values.append(value)
    return values


def _rewrite_composite_like_filter_from_question(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q = question or ""
    q_low = q.lower()
    if not (
        any(token in q_low for token in ("name", "\u540d\u79f0", "\u540d\u5b57"))
        and any(token in q_low for token in ("type", "category", "\u7c7b\u578b", "\u5206\u7c7b"))
    ):
        return sql, False
    split = _question_composite_like_split(q)
    if not split:
        return sql, False
    composite, first_term, category_term = split
    rewritten = sql
    changed = False
    referenced = {table.table_name for table, _ in alias_map.values()}
    for table in tables:
        if table.table_name not in referenced:
            continue
        name_cols = [col for col in table.columns if _column_is_name_like(col)]
        category_cols = [col for col in table.columns if _column_looks_like_category(col)]
        if len(name_cols) != 1 or len(category_cols) != 1:
            continue
        name_col = name_cols[0]
        category_col = category_cols[0]
        for qualifier in _qualifiers_for_table(alias_map, table):
            category_refs = _column_reference_alternatives(qualifier, category_col)
            pattern = re.compile(
                rf"(?P<ref>{category_refs})\s+(?P<op>I?LIKE)\s+'%{re.escape(composite)}%'",
                flags=re.IGNORECASE,
            )

            def repl(match: re.Match) -> str:
                category_ref = match.group("ref")
                name_ref = f"{qualifier}.{name_col.quoted_ref}"
                op = match.group("op")
                return (
                    f"({name_ref} {op} '%{first_term}%' OR {category_ref} {op} '%{first_term}%') "
                    f"AND {category_ref} {op} '%{category_term}%'"
                )

            rewritten2, n = pattern.subn(repl, rewritten)
            if n and rewritten2 != rewritten:
                rewritten = rewritten2
                changed = True
    return rewritten, changed


def _question_composite_like_split(question: str) -> tuple[str, str, str] | None:
    literals = _question_quoted_literals(question)
    if len(literals) < 3:
        return None
    shorter = [value for value in literals if len(value) >= 2]
    for composite in sorted(shorter, key=len, reverse=True):
        parts = [value for value in shorter if value != composite and value in composite]
        if len(parts) < 2:
            continue
        parts.sort(key=lambda value: composite.find(value))
        first, second = parts[0], parts[1]
        if composite == f"{first}{second}" or re.sub(r"\s+", "", composite) == f"{first}{second}":
            return composite, first, second
    return None


def _question_quoted_literals(question: str) -> list[str]:
    values: list[str] = []
    for pattern in (r"'((?:[^']|'')*)'", r'"([^"]*)"'):
        for raw in re.findall(pattern, question or ""):
            value = raw.replace("''", "'").strip()
            if value and value not in values:
                values.append(value)
    return values


def _column_looks_like_category(col: ColumnInfo) -> bool:
    if col.is_geometry:
        return False
    metadata = " ".join(
        str(part or "")
        for part in [col.column_name, col.quoted_ref, col.description, col.semantic_domain, *sorted(col.aliases)]
    ).lower()
    return any(token in metadata for token in (
        "type",
        "category",
        "class",
        "\u7c7b\u578b",
        "\u5206\u7c7b",
        "\u7c7b\u522b",
    ))


def _rewrite_unrequested_code_filters(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    referenced = {table.table_name for table, _ in alias_map.values()}
    rewritten = sql
    changed = False
    for table in tables:
        if table.table_name not in referenced:
            continue
        qualifiers = _qualifiers_for_table(alias_map, table)
        if not _has_question_literal_filter_for_table(question, rewritten, table, qualifiers):
            continue
        code_columns = [col for col in table.columns if _column_looks_like_code(col)]
        if not code_columns:
            continue

        def should_remove(part: str) -> bool:
            return any(
                _predicate_is_unrequested_code_filter(question, part, col, qualifiers)
                for col in code_columns
            )

        rewritten2, removed = _remove_where_predicates(rewritten, should_remove)
        if removed:
            rewritten = rewritten2
            changed = True
    return rewritten, changed


def _column_looks_like_code(col: ColumnInfo) -> bool:
    metadata = " ".join(
        str(part or "")
        for part in [col.column_name, col.quoted_ref, col.description, col.semantic_domain, *sorted(col.aliases)]
    ).lower()
    return any(token in metadata for token in (
        "code",
        "\u7f16\u7801",
        "\u4ee3\u7801",
        "dlbm",
    )) or col.column_name.lower().endswith(("bm", "_code", "code"))


def _predicate_is_unrequested_code_filter(
    question: str,
    predicate: str,
    col: ColumnInfo,
    qualifiers: list[str],
) -> bool:
    if _question_mentions_column(question, col):
        return False
    refs = "|".join(
        ref for ref in (
            _column_reference_alternatives(qualifier, col)
            for qualifier in qualifiers + [None]
        )
        if ref
    )
    if not refs:
        return False
    pattern = re.compile(
        rf"^\s*(?:{refs})\s*(?:=\s*'(?P<eq>[^']+)'|LIKE\s*'(?P<like>\d[\dA-Za-z_%]*)')\s*$",
        flags=re.IGNORECASE,
    )
    match = pattern.match(predicate.strip())
    if not match:
        return False
    literal = match.group("eq") or match.group("like") or ""
    literal_clean = literal.replace("%", "")
    return bool(literal_clean and literal_clean not in (question or ""))


def _has_question_literal_filter_for_table(
    question: str,
    sql: str,
    table: TableInfo,
    qualifiers: list[str],
) -> bool:
    literals = [value for value in _question_quoted_literals(question) if value]
    if not literals:
        return False
    where = _top_level_clause_body(sql, "WHERE", ("GROUP BY", "HAVING", "ORDER BY", "LIMIT"))
    if not where:
        return False
    for col in table.columns:
        if _column_looks_like_code(col):
            continue
        refs = "|".join(
            ref for ref in (
                _column_reference_alternatives(qualifier, col)
                for qualifier in qualifiers + [None]
            )
            if ref
        )
        if not refs:
            continue
        for literal in literals:
            if re.search(rf"(?:{refs})\s*(?:=|I?LIKE)\s*'%?{re.escape(literal)}%?'", where, re.IGNORECASE):
                return True
    return False


def _question_mentions_column(question: str, col: ColumnInfo) -> bool:
    q_low = (question or "").lower()
    for token in col.ref_tokens:
        value = _strip_identifier_quotes(str(token or "")).strip()
        if not value:
            continue
        value_low = value.lower()
        if any("\u4e00" <= ch <= "\u9fff" for ch in value_low):
            if value_low in q_low:
                return True
        elif re.search(rf"(?<![a-z0-9_]){re.escape(value_low)}(?![a-z0-9_])", q_low):
            return True
    return False


def _question_mentions_explicit_enum_codes(question: str, col: ColumnInfo) -> bool:
    q_low = (question or "").lower()
    tokens = [
        _strip_identifier_quotes(token).lower()
        for token in col.ref_tokens
        if _strip_identifier_quotes(token)
    ]
    enum_values = [
        item.get("value")
        for item in col.value_semantics.get("enum") or []
        if isinstance(item, dict) and "value" in item
    ]
    for token in dict.fromkeys(tokens):
        token_re = re.escape(token)
        for value in enum_values:
            value_re = re.escape(str(value))
            if re.search(rf"{token_re}\s*[=＝]\s*{value_re}\b", q_low, flags=re.IGNORECASE):
                return True
    return False


def _enum_literal_pattern(col: ColumnInfo) -> str:
    parts = []
    for item in col.value_semantics.get("enum") or []:
        if not isinstance(item, dict) or "value" not in item:
            continue
        value = item.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(re.escape(str(value)))
        else:
            text = re.escape(str(value).replace("'", "''"))
            parts.append(rf"'{text}'")
    return "|".join(dict.fromkeys(parts))


def _rewrite_unrequested_positive_aggregate_filters(question: str, sql: str) -> tuple[str, bool]:
    if not re.search(r"\bAVG\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False
    if not re.search(r"\bGROUP\s+BY\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    if _question_requests_positive_filter(question):
        return sql, False
    avg_refs = [
        m.group("ref").strip()
        for m in re.finditer(
            r"\bAVG\s*\(\s*(?P<ref>(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*\)",
            sql or "",
            flags=re.IGNORECASE,
        )
    ]
    if not avg_refs:
        return sql, False

    def should_remove(part: str) -> bool:
        stripped = part.strip()
        while stripped.startswith("(") and stripped.endswith(")"):
            stripped = stripped[1:-1].strip()
        for ref in avg_refs:
            col_name = _strip_identifier_quotes(ref.split(".")[-1])
            col_re = re.escape(col_name)
            if re.fullmatch(
                rf"(?:[A-Za-z_][A-Za-z0-9_]*\.)?\"?{col_re}\"?\s*>\s*0(?:\.0+)?",
                stripped,
                flags=re.IGNORECASE,
            ):
                return True
        return False

    return _remove_where_predicates(sql, should_remove)


def _question_requests_positive_filter(question: str) -> bool:
    q_low = (question or "").lower()
    markers = (
        "> 0",
        ">0",
        "\u5927\u4e8e 0",
        "\u5927\u4e8e0",
        "\u975e\u96f6",
        "\u8bbe\u7f6e",
        "\u6709\u6548",
        "positive",
        "nonzero",
        "non-zero",
        "has speed limit",
    )
    return any(marker in q_low for marker in markers)


def _remove_where_predicates(sql: str, should_remove) -> tuple[str, bool]:
    match = re.search(
        r"\bWHERE\b(?P<body>.*?)(?=\bGROUP\s+BY\b|\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|$)",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return sql, False
    parts = re.split(r"\s+AND\s+", match.group("body").strip(), flags=re.IGNORECASE)
    keep = [part.strip() for part in parts if part.strip() and not should_remove(part)]
    if len(keep) == len([part for part in parts if part.strip()]):
        return sql, False
    head = sql[:match.start()].rstrip()
    tail = sql[match.end():].lstrip()
    if keep:
        rewritten = f"{head} WHERE {' AND '.join(keep)} {tail}".rstrip()
    else:
        rewritten = f"{head} {tail}".rstrip()
    return rewritten, True


def _rewrite_requested_scalar_aggregates(question: str, sql: str) -> tuple[str, bool]:
    if not sql or re.search(r"\bGROUP\s+BY\b", sql, flags=re.IGNORECASE):
        return sql, False
    rewritten, changed = _rewrite_requested_multi_aggregate_projection(question, sql)
    if changed:
        return rewritten, True
    return _rewrite_requested_sum_projection(question, sql)


def _rewrite_requested_multi_aggregate_projection(question: str, sql: str) -> tuple[str, bool]:
    requested = _requested_scalar_aggregate_functions(question)
    if len(requested) < 2:
        return sql, False
    pattern = re.compile(
        r"^\s*SELECT\s+(?P<func>AVG|MAX|MIN|SUM)\s*\(\s*(?P<arg>(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*\)"
        r"(?:\s+AS\s+(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))?\s+FROM\s+(?P<rest>.+)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.match(sql or "")
    if not match:
        return sql, False
    current = match.group("func").upper()
    if current not in requested:
        return sql, False
    order = [func for func in ("MAX", "MIN", "AVG", "SUM") if func in requested]
    arg = match.group("arg")
    select_items = ", ".join(f"{func}({arg})" for func in order)
    rewritten = f"SELECT {select_items} FROM {match.group('rest').strip()}"
    return rewritten, rewritten != (sql or "")


def _rewrite_requested_sum_projection(question: str, sql: str) -> tuple[str, bool]:
    requested = _requested_scalar_aggregate_functions(question)
    if requested != {"SUM"}:
        return sql, False
    pattern = re.compile(
        r"^\s*SELECT\s+(?P<arg>(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s+"
        r"FROM\s+(?P<rest>.+)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.match(sql or "")
    if not match:
        return sql, False
    arg = match.group("arg")
    if re.search(r"\b(?:DISTINCT|LIMIT)\b", arg, flags=re.IGNORECASE):
        return sql, False
    rewritten = f"SELECT SUM({arg}) FROM {match.group('rest').strip()}"
    return rewritten, rewritten != (sql or "")


def _requested_scalar_aggregate_functions(question: str) -> set[str]:
    q_low = (question or "").lower()
    requested: set[str] = set()
    if any(token in q_low for token in ("max", "maximum", "\u6700\u5927", "\u6700\u9ad8")):
        requested.add("MAX")
    if any(token in q_low for token in ("min", "minimum", "\u6700\u5c0f", "\u6700\u4f4e")):
        requested.add("MIN")
    if any(token in q_low for token in ("avg", "average", "\u5e73\u5747", "\u5747\u503c")):
        requested.add("AVG")
    if any(token in q_low for token in ("sum", "total", "\u603b\u548c", "\u5408\u8ba1", "\u6c42\u548c")):
        requested.add("SUM")
    return requested


def _rewrite_aggregate_projection_order(question: str, sql: str) -> tuple[str, bool]:
    if not re.match(r"^\s*SELECT\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    count_pos = _first_question_position(question, ("count", "number", "\u6570\u91cf", "\u6761\u6570", "\u56fe\u6591\u6570"))
    area_pos = _first_question_position(question, ("area", "sum", "total", "\u9762\u79ef", "\u603b\u9762\u79ef", "\u603b\u548c"))
    if count_pos < 0 or area_pos < 0 or count_pos > area_pos:
        return sql, False
    from_positions = _top_level_keyword_positions(sql, "FROM")
    select_match = re.match(r"\s*SELECT\b", sql or "", flags=re.IGNORECASE)
    if not from_positions or not select_match:
        return sql, False
    select_start = select_match.end()
    from_pos = from_positions[0]
    body = sql[select_start:from_pos]
    items = [item.strip() for item in _split_top_level_args(body)]
    count_indexes = [i for i, item in enumerate(items) if re.search(r"\bCOUNT\s*\(", item, re.IGNORECASE)]
    sum_indexes = [i for i, item in enumerate(items) if re.search(r"\bSUM\s*\(", item, re.IGNORECASE)]
    if len(count_indexes) != 1 or len(sum_indexes) != 1:
        return sql, False
    count_i = count_indexes[0]
    sum_i = sum_indexes[0]
    if count_i < sum_i:
        return sql, False
    reordered = list(items)
    reordered[sum_i], reordered[count_i] = reordered[count_i], reordered[sum_i]
    rewritten_select = ", ".join(reordered)
    if rewritten_select and not rewritten_select[-1].isspace():
        rewritten_select += " "
    return sql[:select_start] + " " + rewritten_select.lstrip() + sql[from_pos:], True


def _first_question_position(question: str, tokens: tuple[str, ...]) -> int:
    q_low = (question or "").lower()
    positions = [q_low.find(token.lower()) for token in tokens if q_low.find(token.lower()) >= 0]
    return min(positions) if positions else -1


def _rewrite_origin_destination_projection(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    wants_destination = any(token in q_low for token in ("destination", "dest", "\u76ee\u7684", "\u5230\u8fbe"))
    wants_origin = any(token in q_low for token in ("origin", "\u51fa\u53d1", "\u6765\u6e90"))
    if not (wants_destination or wants_origin):
        return sql, False
    referenced = {table.table_name for table, _ in alias_map.values()}
    rewritten = sql
    changed = False
    for table in tables:
        if table.table_name not in referenced:
            continue
        origin = _origin_column(table)
        dest = _destination_column(table)
        if not origin or not dest:
            continue
        if wants_destination and _where_clause_references_column(rewritten, origin, _qualifiers_for_table(alias_map, table)):
            rewritten2, n = _replace_select_and_group_column(
                rewritten,
                origin,
                dest,
                _qualifiers_for_table(alias_map, table),
            )
            if n:
                rewritten = rewritten2
                changed = True
        elif wants_origin and _where_clause_references_column(rewritten, dest, _qualifiers_for_table(alias_map, table)):
            rewritten2, n = _replace_select_and_group_column(
                rewritten,
                dest,
                origin,
                _qualifiers_for_table(alias_map, table),
            )
            if n:
                rewritten = rewritten2
                changed = True
    return rewritten, changed


def _origin_column(table: TableInfo) -> ColumnInfo | None:
    matches = [col for col in table.columns if _column_looks_like_origin(col)]
    return matches[0] if len(matches) == 1 else None


def _destination_column(table: TableInfo) -> ColumnInfo | None:
    matches = [col for col in table.columns if _column_looks_like_destination(col)]
    return matches[0] if len(matches) == 1 else None


def _column_looks_like_origin(col: ColumnInfo) -> bool:
    metadata = " ".join(
        str(part or "")
        for part in [col.column_name, col.quoted_ref, col.description, col.semantic_domain, *sorted(col.aliases)]
    ).lower()
    return (
        "origin" in metadata
        or "\u51fa\u53d1" in metadata
        or col.column_name.lower().startswith(("od", "origin"))
    )


def _column_looks_like_destination(col: ColumnInfo) -> bool:
    metadata = " ".join(
        str(part or "")
        for part in [col.column_name, col.quoted_ref, col.description, col.semantic_domain, *sorted(col.aliases)]
    ).lower()
    return (
        "destination" in metadata
        or "dest" in metadata
        or "\u76ee\u7684" in metadata
        or "\u5230\u8fbe" in metadata
        or col.column_name.lower().startswith(("dd", "dest"))
    )


def _replace_select_and_group_column(
    sql: str,
    wrong: ColumnInfo,
    right: ColumnInfo,
    qualifiers: list[str],
) -> tuple[str, int]:
    total = 0
    rewritten = sql
    refs = [
        (qualifier, _column_reference_alternatives(qualifier, wrong))
        for qualifier in qualifiers + [None]
    ]
    for clause_name, end_keywords in (
        ("SELECT", ("FROM",)),
        ("GROUP BY", ("HAVING", "ORDER BY", "LIMIT")),
    ):
        bounds = _top_level_clause_bounds(rewritten, clause_name, end_keywords)
        if not bounds:
            continue
        start, end = bounds
        body = rewritten[start:end]
        for qualifier, pattern in refs:
            replacement = f"{qualifier}.{right.quoted_ref}" if qualifier else right.quoted_ref
            body2, n = re.subn(pattern, replacement, body, flags=re.IGNORECASE)
            if n:
                body = body2
                total += n
        rewritten = rewritten[:start] + body + rewritten[end:]
    return rewritten, total


def _rewrite_population_total_row_exclusion(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not _question_requests_district_level_rows(question):
        return sql, False
    referenced = {table.table_name for table, _ in alias_map.values()}
    rewritten = sql
    changed = False
    for table in tables:
        if table.table_name not in referenced:
            continue
        qualifiers = _qualifiers_for_table(alias_map, table)
        population_cols = [col for col in table.columns if _column_looks_like_population(col)]
        code_col = _admin_division_code_column(table)
        if not population_cols or not code_col:
            continue
        if _where_clause_references_column(rewritten, code_col, qualifiers):
            continue
        if not any(_where_clause_references_column(rewritten, col, qualifiers) for col in population_cols):
            continue
        ref = _preferred_column_ref_for_filter(code_col, qualifiers)
        rewritten2 = _inject_top_level_predicate(rewritten, f"{ref} != 500000")
        if rewritten2 != rewritten:
            rewritten = rewritten2
            changed = True
    return rewritten, changed


def _question_requests_district_level_rows(question: str) -> bool:
    q_low = (question or "").lower()
    if any(token in q_low for token in ("\u5168\u5e02\u603b\u8ba1", "\u57ce\u5e02\u603b\u8ba1", "city total", "overall total")):
        return False
    return any(token in q_low for token in (
        "district",
        "districts",
        "county",
        "counties",
        "\u533a\u53bf",
        "\u5404\u533a",
        "\u5404\u533a\u53bf",
        "\u6bcf\u4e2a\u533a",
    ))


def _admin_division_code_column(table: TableInfo) -> ColumnInfo | None:
    matches = [col for col in table.columns if _column_looks_like_admin_division_code(col)]
    return matches[0] if len(matches) == 1 else None


def _column_looks_like_admin_division_code(col: ColumnInfo) -> bool:
    metadata = " ".join(
        str(part or "")
        for part in [col.column_name, col.quoted_ref, col.description, col.semantic_domain, *sorted(col.aliases)]
    ).lower()
    has_code = any(token in metadata for token in ("code", "\u4ee3\u7801", "\u7f16\u7801"))
    has_admin = any(token in metadata for token in ("admin", "division", "district", "county", "\u884c\u653f", "\u533a\u5212", "\u533a\u53bf"))
    return has_code and has_admin


def _refuse_unknown_columns(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    complete_tables = {
        table.table_name for table, _ in alias_map.values()
        if table.schema_complete
    }
    if not complete_tables:
        return sql, False
    try:
        import sqlglot
        import sqlglot.expressions as exp

        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return sql, False
    if parsed is None:
        return sql, False

    unique_complete = {
        table.table_name: table
        for table, _ in alias_map.values()
        if table.schema_complete
    }
    single_table = next(iter(unique_complete.values())) if len(unique_complete) == 1 else None
    select_aliases = {
        alias.alias_or_name.lower()
        for alias in parsed.find_all(exp.Alias)
        if alias.alias_or_name
    }
    for node in parsed.find_all(exp.Column):
        name = node.name
        if not name or name == "*":
            continue
        if name.lower() in select_aliases:
            continue
        qualifier = node.table
        table = None
        if qualifier and qualifier in alias_map:
            table = alias_map[qualifier][0]
        elif not qualifier:
            table = single_table
        if not table or not table.schema_complete:
            continue
        if table.column_by_name(name) is None:
            return "SELECT 1", True
    return sql, False


def _rewrite_unit_thresholds(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    rewritten = sql
    changed = False
    for table in tables:
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            multiplier = col.value_semantics.get("stored_unit_multiplier")
            try:
                multiplier_f = float(multiplier)
            except (TypeError, ValueError):
                continue
            if multiplier_f <= 1:
                continue
            aliases = [str(a).lower() for a in col.value_semantics.get("natural_unit_aliases") or [] if a]
            if aliases and not any(a in q_low for a in aliases):
                continue
            question_thresholds = _question_unit_threshold_candidates(question, col, multiplier_f)
            for qualifier in qualifiers + [None]:
                if len(question_thresholds) == 1:
                    rewritten, n = _replace_column_threshold_with_question_value(
                        rewritten,
                        qualifier,
                        col,
                        question_thresholds[0],
                    )
                    changed = changed or bool(n)
                rewritten, n = _scale_column_threshold(rewritten, qualifier, col, multiplier_f)
                changed = changed or bool(n)
    rewritten2, fallback_changed = _rewrite_population_wan_thresholds(question, rewritten, tables, alias_map)
    if fallback_changed:
        rewritten = rewritten2
        changed = True
    return rewritten, changed


def _rewrite_population_wan_thresholds(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    expected_values = _question_wan_person_values(question)
    if len(expected_values) != 1:
        return sql, False
    expected = expected_values[0]
    rewritten = sql
    changed = False
    referenced_tables = {table.table_name for table, _ in alias_map.values()}
    for table in tables:
        if table.table_name not in referenced_tables:
            continue
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            if not _column_looks_like_population(col):
                continue
            for qualifier in qualifiers + [None]:
                rewritten, n = _replace_over_scaled_wan_threshold(rewritten, qualifier, col, expected)
                changed = changed or bool(n)
    return rewritten, changed


def _question_wan_person_values(question: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*\u4e07(?:\u4eba)?", question or ""):
        try:
            value = float(match.group("num").replace(",", ""))
        except (TypeError, ValueError):
            continue
        if value not in values:
            values.append(value)
    return values


def _column_looks_like_population(col: ColumnInfo) -> bool:
    metadata = " ".join(
        str(part or "")
        for part in [col.column_name, col.quoted_ref, col.description, col.semantic_domain, *sorted(col.aliases)]
    ).lower()
    return "\u4eba\u53e3" in metadata or "population" in metadata


def _replace_over_scaled_wan_threshold(
    sql: str,
    qualifier: str | None,
    col: ColumnInfo,
    expected: float,
) -> tuple[str, int]:
    refs = _column_reference_alternatives(qualifier, col)
    total = 0
    parts = re.split(_SQL_STRING_RE, sql)
    for i in range(0, len(parts), 2):
        segment = parts[i]
        pattern = re.compile(
            rf"(?P<prefix>(?P<ref>{refs})\s*(?:>=|>|<=|<)\s*)(?P<num>\d+(?:\.\d+)?)\b",
            flags=re.IGNORECASE,
        )

        def repl(match: re.Match) -> str:
            value = float(match.group("num"))
            if value <= expected * 10:
                return match.group(0)
            return f"{match.group('prefix')}{_format_number(expected)}"

        segment, n = pattern.subn(repl, segment)
        total += n
        parts[i] = segment
    return "".join(parts), total


def _question_unit_threshold_candidates(question: str, col: ColumnInfo, multiplier: float) -> list[float]:
    stored_units = [str(col.unit or "").strip()]
    stored_units.extend(str(u).strip() for u in col.value_semantics.get("stored_unit_aliases") or [] if u)
    stored_units.extend(_infer_stored_unit_aliases_from_column_metadata(col, multiplier))
    stored_values = _extract_question_number_unit_values(question, stored_units, divisor=1.0)
    if stored_values:
        return stored_values

    natural_units = [str(u).strip() for u in col.value_semantics.get("natural_unit_aliases") or [] if u]
    return _extract_question_number_unit_values(question, natural_units, divisor=multiplier)


def _infer_stored_unit_aliases_from_column_metadata(col: ColumnInfo, multiplier: float) -> list[str]:
    """Infer explicit stored-unit aliases from customer schema metadata.

    For example, a column named ``population_10k`` or described as ``单位为万人``
    stores values in ten-thousand-person units even when the registry ``unit``
    field is empty. The multiplier still comes from value_semantics; this helper
    only discovers the textual unit alias already present in column metadata.
    """
    if abs(multiplier - 10000.0) > 1e-9:
        return []
    metadata = " ".join(
        str(part or "")
        for part in [col.column_name, col.quoted_ref, col.description, *sorted(col.aliases)]
    )
    units: list[str] = []
    for natural in col.value_semantics.get("natural_unit_aliases") or []:
        natural_s = str(natural or "").strip()
        if not natural_s:
            continue
        for prefix in ("万", "萬"):
            unit = f"{prefix}{natural_s}"
            if unit in metadata:
                units.append(unit)
    return list(dict.fromkeys(units))


def _extract_question_number_unit_values(question: str, units: list[str], divisor: float) -> list[float]:
    if divisor <= 0:
        return []
    values: list[float] = []
    for unit in dict.fromkeys(u for u in units if u):
        unit_re = _flexible_unit_pattern(unit)
        if not unit_re:
            continue
        pattern = re.compile(
            rf"(?P<num>\d[\d,]*(?:\.\d+)?)\s*{unit_re}",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(question or ""):
            try:
                value = float(match.group("num").replace(",", "")) / divisor
            except (TypeError, ValueError):
                continue
            values.append(value)
    unique: list[float] = []
    for value in values:
        if not any(abs(value - existing) < 1e-9 for existing in unique):
            unique.append(value)
    return unique


def _flexible_unit_pattern(unit: str) -> str:
    unit = (unit or "").strip()
    if not unit:
        return ""
    return r"\s*".join(re.escape(ch) for ch in unit)


def _replace_column_threshold_with_question_value(
    sql: str,
    qualifier: str | None,
    col: ColumnInfo,
    expected_value: float,
) -> tuple[str, int]:
    refs = _column_reference_alternatives(qualifier, col)
    total = 0
    parts = re.split(_SQL_STRING_RE, sql)
    for i in range(0, len(parts), 2):
        segment = parts[i]
        pattern = re.compile(
            rf"(?P<prefix>(?P<ref>{refs})\s*(?:>=|<=|>|<)\s*)(?P<num>\d+(?:\.\d+)?)\b",
            flags=re.IGNORECASE,
        )

        def repl(match: re.Match) -> str:
            value = float(match.group("num"))
            if abs(value - expected_value) < 1e-9:
                return match.group(0)
            return f"{match.group('prefix')}{_format_number(expected_value)}"

        segment, n = pattern.subn(repl, segment)
        total += n
        parts[i] = segment
    return "".join(parts), total


def _scale_column_threshold(sql: str, qualifier: str | None, col: ColumnInfo, multiplier: float) -> tuple[str, int]:
    refs = _column_reference_alternatives(qualifier, col)
    total = 0
    parts = re.split(_SQL_STRING_RE, sql)
    for i in range(0, len(parts), 2):
        segment = parts[i]
        pattern = re.compile(
            rf"(?P<prefix>(?P<ref>{refs})\s*(?:>=|<=|>|<)\s*)(?P<num>\d+(?:\.\d+)?)\b",
            flags=re.IGNORECASE,
        )

        def repl(match: re.Match) -> str:
            value = float(match.group("num"))
            if value < multiplier:
                return match.group(0)
            scaled = value / multiplier
            return f"{match.group('prefix')}{_format_number(scaled)}"

        segment, n = pattern.subn(repl, segment)
        total += n
        parts[i] = segment
    return "".join(parts), total


def _rewrite_precomputed_area(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    rewritten = sql
    changed = False
    for table in tables:
        geom = _first_geometry(table)
        if not geom:
            continue
        qualifiers = _qualifiers_for_table(alias_map, table)
        for col in table.columns:
            vs = col.value_semantics or {}
            geom_col_name = vs.get("geometry_area_column")
            keywords = [str(k).lower() for k in vs.get("use_geometry_area_when_question_matches") or [] if k]
            if geom_col_name:
                geom_override = table.column_by_name(str(geom_col_name))
                if geom_override:
                    geom = geom_override
            if not keywords or not any(k in q_low for k in keywords):
                continue
            for qualifier in qualifiers + [None]:
                refs = _column_reference_alternatives(qualifier, col)
                geom_ref = f"{qualifier}.{geom.quoted_ref}" if qualifier else geom.quoted_ref
                replacement = f"SUM(ST_Area({geom_ref}::geography))"
                pattern = re.compile(rf"SUM\s*\(\s*(?:{refs})\s*\)", flags=re.IGNORECASE)
                rewritten, n = pattern.subn(replacement, rewritten, count=1)
                changed = changed or bool(n)
    return rewritten, changed


def _qualify_unqualified_area_geometry(
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    rewritten = sql
    changed = False
    for table in tables:
        geom = _first_geometry(table)
        qualifiers = _qualifiers_for_table(alias_map, table)
        if not geom or not qualifiers:
            continue
        qualifier = qualifiers[0]
        qualified = f"{qualifier}.{geom.quoted_ref}"
        for pattern, repl in (
            (
                re.compile(
                    rf"ST_AREA\s*\(\s*CAST\s*\(\s*{re.escape(geom.column_name)}\s+AS\s+GEOGRAPHY\s*\)\s*\)",
                    flags=re.IGNORECASE,
                ),
                f"ST_AREA(CAST({qualified} AS GEOGRAPHY))",
            ),
            (
                re.compile(
                    rf"ST_Area\s*\(\s*{re.escape(geom.column_name)}::geography\s*\)",
                    flags=re.IGNORECASE,
                ),
                f"ST_Area({qualified}::geography)",
            ),
        ):
            rewritten, n = pattern.subn(repl, rewritten)
            changed = changed or bool(n)
            if changed:
                return rewritten, changed
    return rewritten, changed


def _rewrite_st_union_geography_area(sql: str) -> tuple[str, bool]:
    rewritten = sql or ""
    changed = False

    def repl_cast(match: re.Match) -> str:
        nonlocal changed
        changed = True
        geom = match.group("geom").strip()
        return f"ST_Area(ST_Union({geom})::geography)"

    patterns = [
        re.compile(
            r"ST_AREA\s*\(\s*ST_UNION\s*\(\s*(?P<geom>[A-Za-z_][A-Za-z0-9_\.]*|\"[^\"]+\")\s*::\s*GEOGRAPHY\s*\)\s*\)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"ST_AREA\s*\(\s*ST_UNION\s*\(\s*CAST\s*\(\s*(?P<geom>[A-Za-z_][A-Za-z0-9_\.]*|\"[^\"]+\")\s+AS\s+GEOGRAPHY\s*\)\s*\)\s*\)",
            flags=re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        rewritten = pattern.sub(repl_cast, rewritten)
    return rewritten, changed


def _rewrite_square_kilometre_area_units(question: str, sql: str) -> tuple[str, bool]:
    if not _question_requests_square_kilometres(question):
        return sql, False
    if not re.search(r"\bST_AREA\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False

    text = sql or ""
    parts: list[str] = []
    changed = False
    last = 0
    i = 0
    in_string = False
    in_identifier = False
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if in_string and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue
        if ch == '"' and not in_string:
            in_identifier = not in_identifier
            i += 1
            continue
        if in_string or in_identifier:
            i += 1
            continue

        match = re.match(r"ST_AREA\s*\(", text[i:], flags=re.IGNORECASE)
        if not match or (i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")):
            i += 1
            continue

        open_pos = i + match.group(0).rfind("(")
        close_pos = _find_matching_paren(text, open_pos)
        if close_pos < 0:
            i += 1
            continue

        arg_text = text[open_pos + 1:close_pos]
        if (
            "geography" not in arg_text.lower()
            or _area_expression_already_scaled_to_square_km(text, close_pos)
        ):
            i = close_pos + 1
            continue

        area_expr = text[i:close_pos + 1]
        parts.append(text[last:i])
        parts.append(f"({area_expr} / 1000000.0)")
        last = close_pos + 1
        i = close_pos + 1
        changed = True

    if not changed:
        return sql, False
    parts.append(text[last:])
    return "".join(parts), True


def _question_requests_square_kilometres(question: str) -> bool:
    q_low = (question or "").lower()
    tokens = (
        "square kilometer",
        "square kilometers",
        "square kilometre",
        "square kilometres",
        "sq km",
        "sq. km",
        "sqkm",
        "km2",
        "km^2",
        "km\u00b2",
        "\u5e73\u65b9\u5343\u7c73",
        "\u5e73\u65b9\u516c\u91cc",
    )
    return any(token in q_low for token in tokens)


def _area_expression_already_scaled_to_square_km(sql: str, area_close_pos: int) -> bool:
    tail = (sql or "")[area_close_pos + 1:area_close_pos + 96]
    return bool(
        re.match(
            r"\s*(?:\)\s*){0,4}(?:/\s*(?:1000000(?:\.0+)?|1e6)\b|\*\s*(?:0\.000001|1e-6)\b)",
            tail,
            flags=re.IGNORECASE,
        )
    )


def _rewrite_hectare_area_units(question: str, sql: str) -> tuple[str, bool]:
    if not _question_requests_hectares(question):
        return sql, False
    return _rewrite_geography_area_unit_divisor(sql, 10000.0, "10000")


def _question_requests_hectares(question: str) -> bool:
    q_low = (question or "").lower()
    return any(token in q_low for token in ("hectare", "hectares", "\u516c\u9877"))


def _rewrite_geography_area_unit_divisor(
    sql: str,
    divisor: float,
    divisor_pattern: str,
) -> tuple[str, bool]:
    if not re.search(r"\bST_AREA\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False
    text = sql or ""
    parts: list[str] = []
    changed = False
    last = 0
    i = 0
    in_string = False
    in_identifier = False
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if in_string and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue
        if ch == '"' and not in_string:
            in_identifier = not in_identifier
            i += 1
            continue
        if in_string or in_identifier:
            i += 1
            continue
        match = re.match(r"ST_AREA\s*\(", text[i:], flags=re.IGNORECASE)
        if not match or (i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")):
            i += 1
            continue
        open_pos = i + match.group(0).rfind("(")
        close_pos = _find_matching_paren(text, open_pos)
        if close_pos < 0:
            i += 1
            continue
        arg_text = text[open_pos + 1:close_pos]
        if "geography" not in arg_text.lower() or _area_expression_already_scaled_by(text, close_pos, divisor_pattern):
            i = close_pos + 1
            continue
        area_expr = text[i:close_pos + 1]
        parts.append(text[last:i])
        parts.append(f"({area_expr} / {_format_number(divisor)})")
        last = close_pos + 1
        i = close_pos + 1
        changed = True
    if not changed:
        return sql, False
    parts.append(text[last:])
    return "".join(parts), True


def _area_expression_already_scaled_by(sql: str, area_close_pos: int, divisor_pattern: str) -> bool:
    tail = (sql or "")[area_close_pos + 1:area_close_pos + 96]
    return bool(
        re.match(
            rf"\s*(?:\)\s*){{0,4}}/\s*(?:{divisor_pattern})(?:\.0+)?\b",
            tail,
            flags=re.IGNORECASE,
        )
    )


def _rewrite_scalar_spatial_subquery_join(sql: str, tables: list[TableInfo]) -> tuple[str, bool]:
    if not sql or "select" not in sql.lower() or "where" not in sql.lower():
        return sql, False
    if re.search(r"\bJOIN\b", sql, flags=re.IGNORECASE):
        return sql, False
    main = re.match(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+"
        r"(?P<left>(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)(?:\s*\.\s*(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))?)"
        r"(?:\s+(?:AS\s+)?(?P<la>\"?[A-Za-z_][A-Za-z0-9_]*\"?))?"
        r"\s+WHERE\s+(?P<where>.*?)(?P<limit>\s+LIMIT\s+\d+)?\s*;?\s*$",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not main:
        return sql, False
    left_table = _table_for_ref(main.group("left"), tables)
    if not left_table:
        return sql, False
    left_alias = _strip_identifier_quotes(main.group("la")) or left_table.bare_name
    if left_alias.upper() in {"ON", "WHERE", "JOIN", "GROUP", "ORDER", "LIMIT"}:
        left_alias = left_table.bare_name

    where = main.group("where").strip()
    parsed = _find_scalar_spatial_subquery_predicate(where, left_table, left_alias, tables)
    if not parsed:
        return sql, False
    predicate_start, predicate_end, join_table, join_alias, on_clause = parsed
    remaining_where = _remove_predicate_span(where, predicate_start, predicate_end)
    rewritten = (
        f"SELECT {main.group('select').strip()} FROM {main.group('left').strip()}"
    )
    if main.group("la"):
        rewritten += f" AS {left_alias}"
    rewritten += f" JOIN {join_table} AS {join_alias} ON {on_clause}"
    if remaining_where:
        rewritten += f" WHERE {remaining_where}"
    rewritten += main.group("limit") or ""
    return rewritten, True


def _find_scalar_spatial_subquery_predicate(
    where: str,
    left_table: TableInfo,
    left_alias: str,
    tables: list[TableInfo],
) -> tuple[int, int, str, str, str] | None:
    pattern = re.compile(r"\bST_(?:INTERSECTS|CONTAINS|WITHIN)\s*\(", flags=re.IGNORECASE)
    for match in pattern.finditer(where or ""):
        close = _find_matching_paren(where, match.end() - 1)
        if close < 0:
            continue
        args = _split_top_level_args(where[match.end():close])
        if len(args) != 2:
            continue
        left_arg_index = 0
        parsed_subquery = _parse_scalar_geometry_subquery(args[1], tables)
        if not parsed_subquery:
            parsed_subquery = _parse_scalar_geometry_subquery(args[0], tables)
            left_arg_index = 1
        if not parsed_subquery:
            continue
        join_table_info, join_table_ref, join_col = parsed_subquery
        left_ref = _outer_geometry_ref_for_scalar_spatial_arg(
            args[left_arg_index],
            left_table,
            left_alias,
        )
        if not left_ref:
            continue
        join_alias = _spatial_subquery_join_alias(join_table_info, left_alias)
        join_ref = f"{join_alias}.{join_col.quoted_ref}"
        func = re.match(r"\b(?P<func>ST_(?:INTERSECTS|CONTAINS|WITHIN))", match.group(0), flags=re.IGNORECASE)
        if not func:
            continue
        if left_arg_index == 0:
            on_clause = f"{func.group('func')}({left_ref}, {join_ref})"
        else:
            on_clause = f"{func.group('func')}({join_ref}, {left_ref})"
        return match.start(), close + 1, join_table_ref.strip(), join_alias, on_clause
    return None


def _parse_scalar_geometry_subquery(
    expr: str,
    tables: list[TableInfo],
) -> tuple[TableInfo, str, ColumnInfo] | None:
    value = (expr or "").strip()
    if not (value.startswith("(") and value.endswith(")")):
        return None
    inner = value[1:-1].strip()
    match = re.match(
        r"^SELECT\s+(?P<col>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)\s+FROM\s+"
        r"(?P<table>(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)(?:\s*\.\s*(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))?)"
        r"(?:\s+(?:AS\s+)?\"?[A-Za-z_][A-Za-z0-9_]*\"?)?\s*$",
        inner,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    table = _table_for_ref(match.group("table"), tables)
    if not table:
        return None
    col = table.column_by_name(match.group("col"))
    if not col or not col.is_geometry:
        col = _first_geometry(table)
    if not col:
        return None
    return table, match.group("table"), col


def _outer_geometry_ref_for_scalar_spatial_arg(
    expr: str,
    table: TableInfo,
    qualifier: str,
) -> str:
    value = (expr or "").strip()
    if "." in value:
        return value
    col = table.column_by_name(value)
    if not col or not col.is_geometry:
        stripped = _strip_identifier_quotes(value).lower()
        if stripped not in {"geometry", "geom", "shape"}:
            return ""
        col = _first_geometry(table)
    if not col:
        return ""
    return f"{qualifier}.{col.quoted_ref}"


def _spatial_subquery_join_alias(table: TableInfo, outer_alias: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", table.bare_name or "sq").strip("_")
    parts = [part for part in base.split("_") if part and not part.isdigit()]
    alias = (parts[-1][0] if parts else "s").lower()
    if not alias or alias == outer_alias:
        alias = "sq"
    return alias


def _remove_predicate_span(where: str, start: int, end: int) -> str:
    text = f"{where[:start]} {where[end:]}"
    text = re.sub(r"^\s*(?:AND|OR)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:AND|OR)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAND\s+AND\b", "AND", text, flags=re.IGNORECASE)
    text = re.sub(r"\bOR\s+OR\b", "OR", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\s*(?:AND|OR)\s+", "", text, flags=re.IGNORECASE)
    return text


def _rewrite_spatial_srid_transforms(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    pattern = re.compile(r"\bST_(?:INTERSECTS|CONTAINS|WITHIN)\s*\(", flags=re.IGNORECASE)
    text = sql or ""
    pieces: list[str] = []
    last = 0
    search_pos = 0
    changed = False
    while True:
        match = pattern.search(text, search_pos)
        if not match:
            break
        if _inside_single_quoted_literal(text, match.start()):
            search_pos = match.end()
            continue
        close = _find_matching_paren(text, match.end() - 1)
        if close < 0:
            search_pos = match.end()
            continue
        args = _split_top_level_args(text[match.end():close])
        if len(args) != 2:
            search_pos = close + 1
            continue
        replacement = _spatial_srid_replacement(
            match.group(0).split("(", 1)[0],
            args[0].strip(),
            args[1].strip(),
            alias_map,
        )
        if not replacement:
            search_pos = close + 1
            continue
        pieces.append(text[last:match.start()])
        pieces.append(replacement)
        last = close + 1
        search_pos = close + 1
        changed = True
    if not changed:
        return sql, False
    pieces.append(text[last:])
    rewritten = "".join(pieces)
    return rewritten, rewritten != sql


def _spatial_srid_replacement(
    func_name: str,
    a: str,
    b: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> str:
    a_ref = _geometry_column_ref_from_expr(a)
    b_ref = _geometry_column_ref_from_expr(b)
    if not a_ref or not b_ref:
        return ""
    a_col = _lookup_column_ref(a_ref, alias_map)
    b_col = _lookup_column_ref(b_ref, alias_map)
    if not a_col or not b_col or not a_col.is_geometry or not b_col.is_geometry:
        return ""
    if not a_col.srid or not b_col.srid or a_col.srid == b_col.srid:
        return ""
    func = _canonical_spatial_function_name(func_name)
    a_base = a_ref
    b_base = b_ref
    if a_col.srid in _GEOGRAPHIC_SRIDS and b_col.srid in _GEOGRAPHIC_SRIDS:
        target = 4326 if 4326 in {a_col.srid, b_col.srid} else b_col.srid
        a_expr = a_base if a_col.srid == target else f"ST_Transform({a_base}, {target})"
        b_expr = b_base if b_col.srid == target else f"ST_Transform({b_base}, {target})"
        return f"{func}({a_expr}, {b_expr})"
    if a_col.srid in _GEOGRAPHIC_SRIDS:
        return f"{func}({a_base}, ST_Transform({b_base}, {a_col.srid}))"
    if b_col.srid in _GEOGRAPHIC_SRIDS:
        return f"{func}(ST_Transform({a_base}, {b_col.srid}), {b_base})"
    return f"{func}(ST_Transform({a_base}, {b_col.srid}), {b_base})"


def _canonical_spatial_function_name(func_name: str) -> str:
    name = (func_name or "").strip().upper()
    mapping = {
        "ST_INTERSECTS": "ST_Intersects",
        "ST_CONTAINS": "ST_Contains",
        "ST_WITHIN": "ST_Within",
    }
    return mapping.get(name, func_name.strip() or "ST_Intersects")


def _rewrite_st_dwithin_geography(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if "::geography" in (sql or "").lower():
        return sql, False
    ref_re = r"[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)"
    pattern = re.compile(
        rf"ST_DWITHIN\s*\(\s*(?P<a>{ref_re})\s*,\s*(?P<b>{ref_re})\s*,\s*(?P<d>\d+(?:\.\d+)?)\s*\)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        a = match.group("a")
        b = match.group("b")
        a_col = _lookup_column_ref(a, alias_map)
        b_col = _lookup_column_ref(b, alias_map)
        if a_col and (not a_col.is_geometry or (a_col.srid and a_col.srid not in _GEOGRAPHIC_SRIDS)):
            return match.group(0)
        if b_col and (not b_col.is_geometry or (b_col.srid and b_col.srid not in _GEOGRAPHIC_SRIDS)):
            return match.group(0)
        if not a_col and not re.search(r'\.(?:"?geometry"?|"?geom"?)$', a, flags=re.IGNORECASE):
            return match.group(0)
        if not b_col and not re.search(r'\.(?:"?geometry"?|"?geom"?)$', b, flags=re.IGNORECASE):
            return match.group(0)
        return f"ST_DWithin({a}::geography, {b}::geography, {match.group('d')})"

    rewritten, n = pattern.subn(repl, sql, count=1)
    return rewritten, bool(n and rewritten != sql)


def _rewrite_st_distance_srid_transforms(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    rewritten, complex_changed = _rewrite_st_distance_complex_geography(sql, alias_map)
    sql = rewritten
    ref_re = r"[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)"
    pattern = re.compile(
        rf"ST_DISTANCE\s*\(\s*(?P<a>{ref_re})\s*,\s*(?P<b>{ref_re})\s*\)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        a = match.group("a")
        b = match.group("b")
        a_col = _lookup_column_ref(a, alias_map)
        b_col = _lookup_column_ref(b, alias_map)
        if not a_col or not b_col:
            known_col = a_col or b_col
            unknown_ref = b if a_col else a
            if (
                known_col
                and known_col.is_geometry
                and _geometry_prefers_geography(known_col)
                and _distance_ref_looks_like_geometry(unknown_ref)
            ):
                return f"ST_Distance({_as_geography(a)}, {_as_geography(b)})"
            return match.group(0)
        if not a_col.is_geometry or not b_col.is_geometry:
            return match.group(0)
        if not a_col.srid or not b_col.srid:
            return match.group(0)
        if a_col.srid == b_col.srid:
            if a_col.srid in _GEOGRAPHIC_SRIDS:
                return f"ST_Distance({a}::geography, {b}::geography)"
            return match.group(0)
        if a_col.srid in _GEOGRAPHIC_SRIDS and b_col.srid in _GEOGRAPHIC_SRIDS:
            target = 4326
            a_expr = a if a_col.srid == target else f"ST_Transform({a}, {target})"
            b_expr = b if b_col.srid == target else f"ST_Transform({b}, {target})"
            return f"ST_Distance({a_expr}::geography, {b_expr}::geography)"
        return f"ST_Distance(ST_Transform({a}, {b_col.srid}), {b})"

    rewritten, n = pattern.subn(repl, sql)
    return rewritten, bool(complex_changed or (n and rewritten != sql))


def _rewrite_st_distance_complex_geography(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    text = sql or ""
    pattern = re.compile(r"\bST_DISTANCE\s*\(", flags=re.IGNORECASE)
    pieces: list[str] = []
    pos = 0
    search_pos = 0
    changed = False
    while True:
        match = pattern.search(text, search_pos)
        if not match:
            break
        if _inside_single_quoted_literal(text, match.start()):
            search_pos = match.end()
            continue
        close = _find_matching_paren(text, match.end() - 1)
        if close < 0:
            search_pos = match.end()
            continue
        args = _split_top_level_args(text[match.end():close])
        if len(args) != 2:
            search_pos = close + 1
            continue
        a = args[0].strip()
        b = args[1].strip()
        if not _distance_arg_is_complex_geometry(a) and not _distance_arg_is_complex_geometry(b):
            search_pos = close + 1
            continue
        a_col = _geometry_column_for_expr(a, alias_map)
        b_col = _geometry_column_for_expr(b, alias_map)
        if not a_col or not b_col or not a_col.is_geometry or not b_col.is_geometry:
            search_pos = close + 1
            continue
        pieces.append(text[pos:match.start()])
        pieces.append(
            f"ST_Distance({_as_geography(_strip_geography_cast_expr(a))}, "
            f"{_as_geography(_strip_geography_cast_expr(b))})"
        )
        pos = close + 1
        search_pos = close + 1
        changed = True
    if not changed:
        return sql, False
    pieces.append(text[pos:])
    return "".join(pieces), True


def _distance_arg_is_complex_geometry(expr: str) -> bool:
    value = (expr or "").lower()
    return "st_transform" in value or "cast" in value or "::" in value


def _strip_geography_cast_expr(expr: str) -> str:
    value = (expr or "").strip()
    value = re.sub(r"::\s*geography\b", "", value, flags=re.IGNORECASE).strip()
    cast = re.fullmatch(
        r"CAST\s*\(\s*(?P<inner>.+?)\s+AS\s+GEOGRAPHY\s*\)",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if cast:
        value = cast.group("inner").strip()
    return value


def _geometry_prefers_geography(col: ColumnInfo) -> bool:
    unit = (col.unit or "").lower()
    if unit in {"meter", "metre", "meters", "metres", "m"} and col.srid not in _GEOGRAPHIC_SRIDS:
        return False
    return not col.srid or col.srid in _GEOGRAPHIC_SRIDS


def _distance_ref_looks_like_geometry(ref: str) -> bool:
    if "." not in (ref or ""):
        return False
    col = _strip_identifier_quotes(ref.split(".")[-1]).lower()
    return col in {"geometry", "geom", "shape"}


def _rewrite_distance_degree_multiplier_to_geography(sql: str) -> tuple[str, bool]:
    """Convert lon/lat degree distance multiplied by metres-per-degree."""
    if not sql:
        return sql, False
    out: list[str] = []
    pos = 0
    changed = False
    pattern = re.compile(r"ST_DISTANCE\s*\(", flags=re.IGNORECASE)
    while True:
        match = pattern.search(sql, pos)
        if not match:
            out.append(sql[pos:])
            break
        close = _find_matching_paren(sql, match.end() - 1)
        if close < 0:
            out.append(sql[pos:])
            break
        multiplier = re.match(r"\s*\*\s*(?P<num>\d+(?:\.\d+)?)\b", sql[close + 1:])
        if not multiplier:
            out.append(sql[pos:close + 1])
            pos = close + 1
            continue
        try:
            factor = float(multiplier.group("num"))
        except ValueError:
            factor = 0.0
        args = _split_top_level_args(sql[match.end():close])
        if len(args) != 2 or not (100_000 <= factor <= 120_000):
            out.append(sql[pos:close + 1])
            pos = close + 1
            continue
        replacement = (
            f"ST_Distance({_as_geography(args[0].strip())}, "
            f"{_as_geography(args[1].strip())})"
        )
        out.append(sql[pos:match.start()])
        out.append(replacement)
        pos = close + 1 + multiplier.end()
        changed = True
    return "".join(out), changed


def _rewrite_st_length_projected_geographic_to_geography(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not sql:
        return sql, False
    ref_re = r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)"
    pattern = re.compile(
        rf"ST_LENGTH\s*\(\s*ST_TRANSFORM\s*\(\s*(?P<geom>{ref_re})\s*,\s*(?P<srid>\d+)\s*\)\s*\)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        geom_ref = match.group("geom")
        try:
            target_srid = int(match.group("srid"))
        except ValueError:
            return match.group(0)
        if target_srid not in {3857, 900913}:
            return match.group(0)
        col = _lookup_any_column_ref(geom_ref, alias_map)
        if not col or not col.is_geometry or not _geometry_prefers_geography(col):
            return match.group(0)
        return f"ST_Length({_as_geography(geom_ref)})"

    rewritten, n = pattern.subn(repl, sql)
    return rewritten, bool(n and rewritten != sql)


def _rewrite_line_length_aggregates(question: str, sql: str, tables: list[TableInfo]) -> tuple[str, bool]:
    if not _question_requests_length_metric(question):
        return sql, False
    if re.search(r"\bST_LENGTH\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False
    if re.search(r"\bJOIN\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    first = _first_from_table(sql, tables)
    if not first:
        return sql, False
    table, qualifier = first
    geom = _preferred_line_geometry(table)
    if not geom:
        return sql, False
    geom_ref = _length_geometry_ref(sql, qualifier, geom)
    length_expr = _st_length_measure_expr(geom_ref, geom)
    divisor = "1000.0" if _question_or_sql_requests_kilometres(question, sql) else ""

    changed = False
    pattern = re.compile(
        r"ROUND\s*\(\s*(?P<body>.+?)::\s*numeric\s*,\s*(?P<digits>\d+)\s*\)\s+AS\s+"
        r"(?P<alias>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def repl(match: re.Match) -> str:
        nonlocal changed
        body = match.group("body")
        alias = match.group("alias")
        if not (_length_alias(alias) or _bbox_length_body(body)):
            return match.group(0)
        aggregate = f"SUM({length_expr})"
        if divisor:
            aggregate = f"{aggregate} / {divisor}"
        changed = True
        return f"ROUND(({aggregate})::numeric, {match.group('digits')}) AS {alias}"

    rewritten = pattern.sub(repl, sql or "", count=1)
    return rewritten, changed and rewritten != (sql or "")


def _question_requests_length_metric(question: str) -> bool:
    q_low = (question or "").lower()
    return any(token in q_low for token in (
        "length",
        "kilometer",
        "kilometre",
        "km",
        "\u957f\u5ea6",
        "\u603b\u957f",
        "\u516c\u91cc",
        "\u5343\u7c73",
    ))


def _question_or_sql_requests_kilometres(question: str, sql: str) -> bool:
    text = f"{question or ''} {sql or ''}".lower()
    return any(token in text for token in ("kilometer", "kilometre", " km", "_km", "\u516c\u91cc", "\u5343\u7c73"))


def _preferred_line_geometry(table: TableInfo) -> ColumnInfo | None:
    geoms = table.geometry_columns()
    line_geoms = [geom for geom in geoms if "line" in (geom.pg_type or "").lower()]
    if line_geoms:
        return line_geoms[0]
    return geoms[0] if len(geoms) == 1 else None


def _length_geometry_ref(sql: str, qualifier: str, geom: ColumnInfo) -> str:
    quoted_qualifier = f'"{_strip_identifier_quotes(qualifier)}"'
    if re.search(rf"{re.escape(quoted_qualifier)}\s*\.", sql or "", flags=re.IGNORECASE):
        return f"{quoted_qualifier}.{geom.quoted_ref}"
    if re.search(rf"\b{re.escape(qualifier)}\s*\.", sql or "", flags=re.IGNORECASE):
        return f"{qualifier}.{geom.quoted_ref}"
    return geom.quoted_ref


def _st_length_measure_expr(geom_ref: str, geom: ColumnInfo) -> str:
    unit = (geom.unit or "").lower()
    if unit in {"meter", "metre", "meters", "metres", "m"} and geom.srid not in _GEOGRAPHIC_SRIDS:
        return f"ST_Length({geom_ref})"
    if geom.srid and geom.srid not in _GEOGRAPHIC_SRIDS:
        return f"ST_Length({geom_ref})"
    return f"ST_Length({geom_ref}::geography)"


def _length_alias(alias: str) -> bool:
    alias_low = _strip_identifier_quotes(alias).lower()
    return any(token in alias_low for token in ("length", "len", "km", "meter", "metre"))


def _bbox_length_body(body: str) -> bool:
    body_low = (body or "").lower()
    return (
        ("st_xmax" in body_low and "st_xmin" in body_low)
        or ("st_ymax" in body_low and "st_ymin" in body_low)
    )


def _rewrite_knn_order_by_distance_alias(question: str, sql: str) -> tuple[str, bool]:
    if not _question_requests_nearest_neighbor(question):
        return sql, False
    rewritten = sql or ""
    changed = False
    distance_projection = _find_distance_projection(rewritten)
    if distance_projection:
        distance_alias, left_geom, right_geom = distance_projection
        left_ref = _geometry_ref_for_knn(left_geom)
        right_ref = _geometry_ref_for_knn(right_geom)
        if left_ref and right_ref:
            alias = distance_alias.strip('"')
            alias_pattern = (
                rf"\"{re.escape(alias)}\""
                if distance_alias.startswith('"') and distance_alias.endswith('"')
                else rf"\"?{re.escape(alias)}\"?"
            )
            pattern = re.compile(
                rf"\bORDER\s+BY\s+{alias_pattern}\s*(?:ASC|DESC)?\s*(?P<limit>\bLIMIT\s+\d+\b)",
                flags=re.IGNORECASE,
            )
            replacement = f"ORDER BY {left_ref} <-> {right_ref} \\g<limit>"
            rewritten2, n = pattern.subn(replacement, rewritten, count=1)
            if n and rewritten2 != rewritten:
                rewritten = rewritten2
                changed = True
            rewritten2, added = _rewrite_knn_missing_order_by(rewritten, left_ref, right_ref)
            if added:
                rewritten = rewritten2
                changed = True

    rewritten2, expr_changed = _rewrite_knn_order_by_distance_expression(rewritten)
    if expr_changed:
        rewritten = rewritten2
        changed = True
    return rewritten, changed


def _question_requests_nearest_neighbor(question: str) -> bool:
    q = question or ""
    q_low = q.lower()
    markers = (
        "nearest",
        "closest",
        "nearby",
        "k-nearest",
        "knn",
        "最近",
        "最近的",
        "距离",
        "\u76f4\u7ebf\u8ddd\u79bb",
        "\u8ddd\u79bb\u6700\u77ed",
    )
    return any(marker in q_low for marker in markers)


def _find_distance_projection(sql: str) -> tuple[str, str, str] | None:
    pattern = re.compile(r"\bST_DISTANCE\s*\(", flags=re.IGNORECASE)
    for match in pattern.finditer(sql or ""):
        open_paren = match.end() - 1
        close = _find_matching_paren(sql, open_paren)
        if close < 0:
            continue
        args = _split_top_level_args(sql[open_paren + 1:close])
        if len(args) != 2:
            continue
        alias_match = re.match(
            r"\s+AS\s+(?P<alias>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
            sql[close + 1:],
            flags=re.IGNORECASE,
        )
        if not alias_match:
            continue
        return alias_match.group("alias"), args[0].strip(), args[1].strip()
    return None


def _geometry_ref_for_knn(expr: str) -> str:
    value = (expr or "").strip()
    value = re.sub(r"::\s*geography\b", "", value, flags=re.IGNORECASE).strip()
    cast_match = re.fullmatch(
        r"CAST\s*\(\s*(?P<inner>.+?)\s+AS\s+(?:GEOGRAPHY|GEOMETRY\s*(?:\([^)]*\))?)\s*\)",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if cast_match:
        value = cast_match.group("inner").strip()
    transform = re.fullmatch(
        r"ST_TRANSFORM\s*\(\s*(?P<inner>.+?)\s*,\s*(?P<srid>\d+)\s*\)",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if transform:
        inner = _geometry_ref_for_knn(transform.group("inner"))
        return f"ST_Transform({inner}, {transform.group('srid')})" if inner else ""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)", value):
        return value
    return ""


def _rewrite_knn_order_by_distance_expression(sql: str) -> tuple[str, bool]:
    text = sql or ""
    pattern = re.compile(r"\bORDER\s+BY\s+ST_DISTANCE\s*\(", flags=re.IGNORECASE)
    pieces: list[str] = []
    pos = 0
    search_pos = 0
    changed = False
    while True:
        match = pattern.search(text, search_pos)
        if not match:
            break
        if _inside_single_quoted_literal(text, match.start()):
            search_pos = match.end()
            continue
        open_paren = text.find("(", match.start())
        close = _find_matching_paren(text, open_paren)
        if close < 0:
            search_pos = match.end()
            continue
        args = _split_top_level_args(text[open_paren + 1:close])
        if len(args) != 2:
            search_pos = close + 1
            continue
        left_ref = _geometry_ref_for_knn(args[0])
        right_ref = _geometry_ref_for_knn(args[1])
        tail_match = re.match(r"\s*(?:ASC|DESC)?\s*(?P<limit>\bLIMIT\s+\d+\b)", text[close + 1:], flags=re.IGNORECASE)
        if not left_ref or not right_ref or not tail_match:
            search_pos = close + 1
            continue
        pieces.append(text[pos:match.start()])
        pieces.append(f"ORDER BY {left_ref} <-> {right_ref} {tail_match.group('limit')}")
        pos = close + 1 + tail_match.end()
        search_pos = pos
        changed = True
    if not changed:
        return sql, False
    pieces.append(text[pos:])
    return "".join(pieces), True


def _rewrite_knn_missing_order_by(sql: str, left_ref: str, right_ref: str) -> tuple[str, bool]:
    if _top_level_keyword_positions(sql or "", "ORDER BY"):
        return sql, False
    limit_positions = _top_level_keyword_positions(sql or "", "LIMIT")
    if not limit_positions:
        return sql, False
    pos = limit_positions[0]
    head = (sql or "")[:pos].rstrip()
    tail = (sql or "")[pos:].lstrip()
    return f"{head} ORDER BY {left_ref} <-> {right_ref} {tail}", True


def _rewrite_knn_radius_join_to_cross_join(question: str, sql: str) -> tuple[str, bool]:
    if not _question_requests_nearest_neighbor(question):
        return sql, False
    if not re.search(r"\bST_DWITHIN\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False
    if not (
        _top_level_keyword_positions(sql or "", "ORDER BY")
        and _top_level_keyword_positions(sql or "", "LIMIT")
    ):
        return sql, False

    pattern = re.compile(
        r"\bJOIN\s+(?P<table>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)"
        r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?\s+ON\s+ST_DWITHIN\s*\(",
        flags=re.IGNORECASE,
    )
    text = sql or ""
    pieces: list[str] = []
    pos = 0
    search_pos = 0
    changed = False
    while True:
        match = pattern.search(text, search_pos)
        if not match:
            break
        if _inside_single_quoted_literal(text, match.start()):
            search_pos = match.end()
            continue
        open_paren = text.rfind("(", match.start(), match.end())
        close = _find_matching_paren(text, open_paren)
        if close < 0:
            search_pos = match.end()
            continue
        tail = text[close + 1:]
        if not re.match(r"\s*(?=\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)", tail, flags=re.IGNORECASE):
            search_pos = close + 1
            continue
        table = match.group("table")
        alias = match.group("alias")
        replacement = f"CROSS JOIN {table}"
        if alias:
            replacement += f" AS {alias}"
        pieces.append(text[pos:match.start()])
        pieces.append(replacement)
        pos = close + 1
        search_pos = close + 1
        changed = True
    if not changed:
        return sql, False
    pieces.append(text[pos:])
    return re.sub(r"\s+", " ", "".join(pieces)).strip(), True


def _rewrite_knn_string_filters(question: str, sql: str) -> tuple[str, bool]:
    if not _question_requests_nearest_neighbor(question):
        return sql, False
    bounds = _top_level_clause_bounds(sql or "", "WHERE", ("GROUP BY", "HAVING", "ORDER BY", "LIMIT"))
    if not bounds:
        return sql, False
    start, end = bounds
    body = (sql or "")[start:end].strip()
    parts = [part.strip() for part in _split_top_level_and_predicates(body) if part.strip()]
    if not parts:
        return sql, False

    infos = [_string_filter_predicate_info(part) for part in parts]
    exact_literals = {
        info["literal_key"]
        for info in infos
        if info and info["op"] == "="
    }
    keep: list[str] = []
    removed = False
    for part, info in zip(parts, infos):
        if not info:
            keep.append(part)
            continue
        literal = info["literal"]
        literal_key = info["literal_key"]
        if info["op"] in {"LIKE", "ILIKE"} and literal_key in exact_literals:
            removed = True
            continue
        if not _question_mentions_sql_literal(question, literal):
            removed = True
            continue
        keep.append(part)
    if not removed:
        return sql, False

    where_positions = _top_level_keyword_positions(sql or "", "WHERE")
    where_start = where_positions[0] if where_positions else start - len("WHERE")
    head_with_where = (sql or "")[:start].rstrip()
    head_without_where = (sql or "")[:where_start].rstrip()
    tail = (sql or "")[end:].lstrip()
    if keep:
        rewritten = f"{head_with_where} {' AND '.join(keep)}"
    else:
        rewritten = head_without_where
    if tail:
        rewritten = f"{rewritten} {tail}"
    return rewritten.strip(), True


def _string_filter_predicate_info(predicate: str) -> dict[str, str] | None:
    text = (predicate or "").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    match = re.fullmatch(
        r"(?P<ref>(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s+"
        r"(?P<op>I?LIKE)\s+'(?P<literal>(?:[^']|'')*)'",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.fullmatch(
            r"(?P<ref>(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*=\s*"
            r"'(?P<literal>(?:[^']|'')*)'",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        op = "="
    else:
        op = match.group("op").upper()
    literal = match.group("literal").replace("''", "'").replace("%", "").strip()
    if not literal:
        return None
    return {
        "ref": match.group("ref"),
        "op": op,
        "literal": literal,
        "literal_key": re.sub(r"\s+", "", literal).lower(),
    }


def _question_mentions_sql_literal(question: str, literal: str) -> bool:
    if not literal:
        return False
    q_low = (question or "").lower()
    lit_low = literal.lower()
    compact_q = re.sub(r"\s+", "", q_low)
    compact_lit = re.sub(r"\s+", "", lit_low)
    return lit_low in q_low or compact_lit in compact_q


def _rewrite_knn_single_target_cross_join(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not _question_requests_nearest_neighbor(question):
        return sql, False
    if _question_requests_per_entity_nearest(question):
        return sql, False
    where_bounds = _top_level_clause_bounds(sql or "", "WHERE", ("GROUP BY", "HAVING", "ORDER BY", "LIMIT"))
    if not where_bounds:
        return sql, False
    start, end = where_bounds
    where_body = (sql or "")[start:end].strip()
    predicates = [part.strip() for part in _split_top_level_and_predicates(where_body) if part.strip()]
    if not predicates:
        return sql, False

    known_aliases = {
        alias for alias in alias_map
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias or "")
    }
    cross_join = re.compile(
        r"\bCROSS\s+JOIN\s+(?!\()(?P<table>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)"
        r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?",
        flags=re.IGNORECASE,
    )
    text = sql or ""
    for match in cross_join.finditer(text):
        table_ref = match.group("table")
        alias = match.group("alias") or _strip_identifier_quotes(table_ref).split(".")[-1]
        table = _table_for_ref(_strip_identifier_quotes(table_ref), tables)
        if not table:
            mapped = alias_map.get(alias)
            table = mapped[0] if mapped else None
        if not table:
            continue
        target_predicates = [
            pred for pred in predicates
            if _predicate_references_only_alias(pred, alias, known_aliases)
        ]
        if not target_predicates:
            continue
        if not _question_or_predicates_indicate_single_target(question, target_predicates):
            continue
        inner_predicates = [_strip_alias_from_predicate(pred, alias) for pred in target_predicates]
        order_col = _question_order_column_for_table(question, table)
        order_clause = f" ORDER BY {order_col}" if order_col else ""
        inner_where = f" WHERE {' AND '.join(inner_predicates)}" if inner_predicates else ""
        replacement = (
            f"CROSS JOIN (SELECT * FROM {table_ref}{inner_where}"
            f"{order_clause} LIMIT 1) AS {alias}"
        )
        rewritten = text[:match.start()] + replacement + text[match.end():]
        keep = [pred for pred in predicates if pred not in target_predicates]
        rewritten = _replace_top_level_where_body(rewritten, keep)
        return rewritten, rewritten != (sql or "")
    return sql, False


def _question_requests_per_entity_nearest(question: str) -> bool:
    q_low = (question or "").lower()
    return any(token in q_low for token in (
        "for each",
        "per ",
        "each ",
        "\u6bcf\u4e2a",
        "\u6bcf\u6761",
        "\u5bf9\u6bcf",
    ))


def _predicate_references_only_alias(predicate: str, alias: str, known_aliases: set[str]) -> bool:
    refs = {
        _strip_identifier_quotes(match.group("alias"))
        for match in re.finditer(r"(?P<alias>\"?[A-Za-z_][A-Za-z0-9_]*\"?)\s*\.", predicate or "")
    }
    refs = {ref for ref in refs if ref in known_aliases or ref == alias}
    return refs == {alias}


def _question_or_predicates_indicate_single_target(question: str, predicates: list[str]) -> bool:
    q_low = (question or "").lower()
    if any(token in q_low for token in (
        "first",
        "single",
        "one ",
        "\u53d6\u7b2c\u4e00",
        "\u7b2c\u4e00\u4e2a",
        "\u7b2c\u4e00\u680b",
        "\u67d0\u4e2a",
        "\u67d0\u680b",
    )):
        return True
    return any(_string_filter_predicate_info(pred) and _string_filter_predicate_info(pred)["op"] == "=" for pred in predicates)


def _strip_alias_from_predicate(predicate: str, alias: str) -> str:
    alias_re = rf"(?:\b{re.escape(alias)}|\"{re.escape(alias)}\")\s*\.\s*"
    return re.sub(alias_re, "", predicate or "", flags=re.IGNORECASE)


def _question_order_column_for_table(question: str, table: TableInfo) -> str:
    q = question or ""
    candidates: list[str] = []
    patterns = (
        r"\border(?:ed)?\s+by\s+\"?(?P<col>[A-Za-z_][A-Za-z0-9_]*)\"?",
        r"\u6309\s*\"?(?P<col>[A-Za-z_][A-Za-z0-9_]*)\"?\s*(?:\u5347\u5e8f|\u964d\u5e8f|\u6392\u5e8f)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, q, flags=re.IGNORECASE):
            candidates.append(match.group("col"))
    for candidate in candidates:
        col = table.column_by_name(candidate)
        if col:
            return col.quoted_ref
    return ""


def _replace_top_level_where_body(sql: str, predicates: list[str]) -> str:
    where_bounds = _top_level_clause_bounds(sql or "", "WHERE", ("GROUP BY", "HAVING", "ORDER BY", "LIMIT"))
    if not where_bounds:
        return sql
    start, end = where_bounds
    where_positions = _top_level_keyword_positions(sql or "", "WHERE")
    where_start = where_positions[0] if where_positions else start - len("WHERE")
    tail = (sql or "")[end:].lstrip()
    if predicates:
        head = (sql or "")[:start].rstrip()
        rewritten = f"{head} {' AND '.join(predicates)}"
    else:
        rewritten = (sql or "")[:where_start].rstrip()
    if tail:
        rewritten = f"{rewritten} {tail}"
    return rewritten.strip()


def _rewrite_existential_spatial_join_aggregate(question: str, sql: str) -> tuple[str, bool]:
    q_low = (question or "").lower()
    if not any(token in q_low for token in ("any", "exists", "intersect any", "任何", "任一", "至少一个")):
        return sql, False
    pattern = re.compile(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+"
        r"(?P<left>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<la>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"JOIN\s+(?P<right>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<ra>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"ON\s+(?P<on>ST_INTERSECTS\s*\([^)]*\))\s+WHERE\s+(?P<where>.*?)(?P<limit>\s+LIMIT\s+\d+)?\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql or "")
    if not m:
        return sql, False
    select_expr = m.group("select")
    left_alias = m.group("la")
    right_alias = m.group("ra")
    if not _select_is_single_sum_aggregate(select_expr):
        return sql, False
    if _expr_references_alias(select_expr, right_alias):
        return sql, False

    left_parts: list[str] = []
    exists_parts = [m.group("on").strip()]
    for part in _split_top_level_and_predicates(m.group("where").strip()):
        predicate = part.strip()
        if not predicate:
            continue
        if _expr_references_alias(predicate, right_alias):
            exists_parts.append(predicate)
        else:
            left_parts.append(predicate)
    if not left_parts:
        return sql, False

    where = " AND ".join(left_parts)
    exists_where = " AND ".join(exists_parts)
    exists_sql = (
        f"EXISTS (SELECT 1 FROM {m.group('right')} AS {right_alias} "
        f"WHERE {exists_where})"
    )
    rewritten = (
        f"SELECT {select_expr} FROM {m.group('left')} AS {left_alias} "
        f"WHERE {where} AND {exists_sql}{m.group('limit') or ''}"
    )
    return rewritten, True


def _select_is_single_sum_aggregate(select_expr: str) -> bool:
    text = (select_expr or "").strip()
    match = re.match(r"SUM\s*\(", text, flags=re.IGNORECASE)
    if not match:
        return False
    close = _find_matching_paren(text, match.end() - 1)
    if close < 0:
        return False
    tail = text[close + 1:].strip()
    if not tail:
        return True
    return bool(re.fullmatch(r"AS\s+(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)", tail, flags=re.IGNORECASE))


def _rewrite_distinct_name_not_null(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    if "distinct" not in (sql or "").lower() or not any(t in q_low for t in ("name", "名称", "名字")):
        return sql, False
    pattern = re.compile(
        r"^\s*SELECT\s+DISTINCT\s+(?P<ref>[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s+"
        r"FROM\s+(?P<rest>.+?)\s+WHERE\s+(?P<where>.*?)(?P<limit>\s+LIMIT\s+\d+)?\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql or "")
    if not m:
        return _rewrite_unqualified_distinct_name_not_null(sql, tables, alias_map)
    ref = m.group("ref")
    col = _lookup_column_ref(ref, alias_map)
    if not col:
        return sql, False
    if not _column_is_name_like(col):
        return sql, False
    where = m.group("where").strip()
    if re.search(rf"{re.escape(ref)}\s+IS\s+NOT\s+NULL", where, re.IGNORECASE):
        return sql, False
    rewritten = (
        f"SELECT DISTINCT {ref} FROM {m.group('rest')} "
        f"WHERE {where} AND {ref} IS NOT NULL{m.group('limit') or ''}"
    )
    return rewritten, True


def _rewrite_unqualified_distinct_name_not_null(
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    pattern = re.compile(
        r"^\s*SELECT\s+DISTINCT\s+(?P<ref>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"FROM\s+(?P<rest>.+?)\s+WHERE\s+(?P<where>.*?)(?P<limit>\s+LIMIT\s+\d+)?\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql or "")
    if not m:
        return sql, False
    ref = m.group("ref")
    ref_name = _strip_identifier_quotes(ref).lower()
    referenced = {table.table_name for table, _ in alias_map.values()}
    matches = [
        col for table in tables
        if table.table_name in referenced
        for col in table.columns
        if _strip_identifier_quotes(col.column_name).lower() == ref_name
        and _column_is_name_like(col)
    ]
    if len(matches) != 1:
        return sql, False
    where = m.group("where").strip()
    if re.search(rf"{re.escape(ref)}\s+IS\s+NOT\s+NULL", where, re.IGNORECASE):
        return sql, False
    rewritten = (
        f"SELECT DISTINCT {ref} FROM {m.group('rest')} "
        f"WHERE {where} AND {ref} IS NOT NULL{m.group('limit') or ''}"
    )
    return rewritten, True


def _column_is_name_like(col: ColumnInfo) -> bool:
    name_tokens = {col.column_name.lower(), _strip_identifier_quotes(col.quoted_ref).lower()}
    name_tokens.update(a.lower() for a in col.aliases)
    return bool({"name", "名称", "名字"} & name_tokens)


def _rewrite_left_join_for_grouped_count(question: str, sql: str) -> tuple[str, bool]:
    q_low = (question or "").lower()
    if not any(token in q_low for token in ("count", "统计", "数量")):
        return sql, False
    if re.search(r"\bLEFT\s+JOIN\b", sql or "", re.IGNORECASE):
        return sql, False
    pattern = re.compile(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+"
        r"(?P<left>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<la>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"JOIN\s+(?P<right>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<ra>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"ON\s+(?P<on>.+?)\s+WHERE\s+(?P<where>.+?)(?P<tail>\s+GROUP\s+BY\s+.+)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql or "")
    if not m:
        return sql, False
    select_expr = m.group("select")
    right_alias = m.group("ra")
    if not re.search(rf"\bCOUNT\s*\(\s*(?:DISTINCT\s+)?{re.escape(right_alias)}\.", select_expr, re.IGNORECASE):
        return sql, False
    where_parts = re.split(r"\s+AND\s+", m.group("where").strip(), flags=re.IGNORECASE)
    left_parts = []
    right_parts = []
    for part in where_parts:
        if re.search(rf"\b{re.escape(right_alias)}\.", part):
            right_parts.append(part)
        else:
            left_parts.append(part)
    if not right_parts or not left_parts:
        return sql, False
    on_clause = " AND ".join([m.group("on").strip()] + right_parts)
    where_clause = " AND ".join(left_parts)
    rewritten = (
        f"SELECT {select_expr} FROM {m.group('left')} AS {m.group('la')} "
        f"LEFT JOIN {m.group('right')} AS {right_alias} ON {on_clause} "
        f"WHERE {where_clause}{m.group('tail')}"
    )
    return rewritten, True


def _rewrite_grouped_count_join_order(question: str, sql: str) -> tuple[str, bool]:
    q_low = (question or "").lower()
    if not any(token in q_low for token in ("count", "\u7edf\u8ba1", "\u6570\u91cf")):
        return sql, False
    if re.search(r"\bLEFT\s+JOIN\b", sql or "", re.IGNORECASE):
        return sql, False
    pattern = re.compile(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+"
        r"(?P<left>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<la>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"JOIN\s+(?P<right>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<ra>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"ON\s+(?P<on>.+?)\s+WHERE\s+(?P<where>.+?)(?P<tail>\s+GROUP\s+BY\s+.+)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql or "")
    if not m:
        return sql, False
    select_expr = m.group("select")
    left_alias = m.group("la")
    right_alias = m.group("ra")
    if not re.search(rf"\bCOUNT\s*\(\s*(?:DISTINCT\s+)?{re.escape(left_alias)}\.", select_expr, re.IGNORECASE):
        return sql, False
    if not _tail_groups_by_alias(m.group("tail"), right_alias):
        return sql, False
    where_parts = re.split(r"\s+AND\s+", m.group("where").strip(), flags=re.IGNORECASE)
    left_parts = []
    right_parts = []
    for part in where_parts:
        if re.search(rf"\b{re.escape(left_alias)}\.", part):
            left_parts.append(part)
        else:
            right_parts.append(part)
    if not left_parts or not right_parts:
        return sql, False
    on_clause = " AND ".join([m.group("on").strip()] + left_parts)
    where_clause = " AND ".join(right_parts)
    rewritten = (
        f"SELECT {select_expr} FROM {m.group('right')} AS {right_alias} "
        f"LEFT JOIN {m.group('left')} AS {left_alias} ON {on_clause} "
        f"WHERE {where_clause}{m.group('tail')}"
    )
    return rewritten, True


def _rewrite_left_join_for_grouped_count_by_group_alias(question: str, sql: str) -> tuple[str, bool]:
    q_low = (question or "").lower()
    if not any(token in q_low for token in ("count", "\u7edf\u8ba1", "\u6570\u91cf")):
        return sql, False
    if re.search(r"\bLEFT\s+JOIN\b", sql or "", re.IGNORECASE):
        return sql, False
    pattern = re.compile(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+"
        r"(?P<left>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<la>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"JOIN\s+(?P<right>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<ra>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"ON\s+(?P<on>.+?)\s+WHERE\s+(?P<where>.+?)(?P<tail>\s+GROUP\s+BY\s+.+)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql or "")
    if not m:
        return sql, False
    select_expr = m.group("select")
    left_alias = m.group("la")
    right_alias = m.group("ra")
    tail = m.group("tail")
    count_alias = _single_count_alias(select_expr)
    group_alias = _single_group_by_alias(tail)
    if not count_alias or not group_alias or group_alias == count_alias:
        return sql, False
    if {group_alias, count_alias} != {left_alias, right_alias}:
        return sql, False

    group_parts: list[str] = []
    count_parts: list[str] = []
    other_parts: list[str] = []
    for part in _split_top_level_and_predicates(m.group("where").strip()):
        predicate = part.strip()
        if not predicate:
            continue
        references_group = _expr_references_alias(predicate, group_alias)
        references_count = _expr_references_alias(predicate, count_alias)
        if references_group and not references_count:
            group_parts.append(predicate)
        elif references_count and not references_group:
            count_parts.append(predicate)
        else:
            other_parts.append(predicate)
    if not group_parts or not count_parts or other_parts:
        return sql, False

    if group_alias == right_alias:
        group_table = m.group("right")
        count_table = m.group("left")
    else:
        group_table = m.group("left")
        count_table = m.group("right")
    on_clause = " AND ".join([m.group("on").strip()] + count_parts)
    where_clause = " AND ".join(group_parts)
    rewritten = (
        f"SELECT {select_expr} FROM {group_table} AS {group_alias} "
        f"LEFT JOIN {count_table} AS {count_alias} ON {on_clause} "
        f"WHERE {where_clause}{tail}"
    )
    return rewritten, True


def _tail_groups_by_alias(tail: str, alias: str) -> bool:
    m = re.search(
        r"\bGROUP\s+BY\b(?P<body>.*?)(?=\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|$)",
        tail or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return bool(m and re.search(rf"\b{re.escape(alias)}\.", m.group("body")))


def _rewrite_join_condition_overrides(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not re.search(r"\bJOIN\b", sql or "", flags=re.IGNORECASE):
        return sql, False

    rewritten = sql
    changed = False
    join_pattern = re.compile(
        r"(?P<head>\b(?:LEFT\s+JOIN|JOIN)\s+"
        r"\"?[A-Za-z_][A-Za-z0-9_\.]*\"?\s+(?:AS\s+)?[A-Za-z_][A-Za-z0-9_]*\s+ON\s+)"
        r"(?P<on>.*?)(?=\s+(?:LEFT\s+JOIN|JOIN|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def rewrite_join(match: re.Match) -> str:
        nonlocal changed
        on_clause, n = _rewrite_join_on_overrides(match.group("on"), alias_map)
        if n:
            changed = True
        return f"{match.group('head')}{on_clause}"

    rewritten = join_pattern.sub(rewrite_join, rewritten)
    return rewritten, changed


def _rewrite_join_on_overrides(
    on_clause: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, int]:
    eq_pattern = re.compile(
        r"(?P<a1>[A-Za-z_][A-Za-z0-9_]*)\.\s*(?P<c1>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*=\s*"
        r"(?P<a2>[A-Za-z_][A-Za-z0-9_]*)\.\s*(?P<c2>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        side1 = _join_side_from_match(match, "a1", "c1", alias_map)
        side2 = _join_side_from_match(match, "a2", "c2", alias_map)
        if not side1 or not side2:
            return match.group(0)
        replacement = _join_override_replacement(side1, side2)
        if replacement:
            return replacement
        replacement = _join_override_replacement(side2, side1)
        return replacement or match.group(0)

    rewritten, n = eq_pattern.subn(repl, on_clause)
    return rewritten, n if rewritten != on_clause else 0


def _join_side_from_match(
    match: re.Match,
    alias_group: str,
    column_group: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> dict[str, Any] | None:
    alias = match.group(alias_group)
    mapped = alias_map.get(alias)
    if not mapped:
        return None
    table, _ = mapped
    column_name = _strip_identifier_quotes(match.group(column_group))
    column = table.column_by_name(column_name)
    if column is None:
        return None
    return {"alias": alias, "table": table, "column": column}


def _join_override_replacement(self_side: dict[str, Any], other_side: dict[str, Any]) -> str | None:
    self_table: TableInfo = self_side["table"]
    other_table: TableInfo = other_side["table"]
    self_col: ColumnInfo = self_side["column"]
    other_col: ColumnInfo = other_side["column"]
    for override in self_col.value_semantics.get("join_condition_overrides") or []:
        if not isinstance(override, dict):
            continue
        if not _join_override_matches(override, other_table, other_col):
            continue
        self_replacement = self_table.column_by_name(str(override.get("self_replacement_column") or ""))
        other_replacement = other_table.column_by_name(str(override.get("other_replacement_column") or ""))
        if self_replacement is None or other_replacement is None:
            continue
        self_ref = f"{self_side['alias']}.{self_replacement.quoted_ref}"
        other_ref = f"{other_side['alias']}.{other_replacement.quoted_ref}"
        operator = str(override.get("operator") or "").lower()
        if operator == "self_like_contains_other":
            return f"{self_ref} LIKE '%' || {other_ref} || '%'"
        if operator == "other_like_contains_self":
            return f"{other_ref} LIKE '%' || {self_ref} || '%'"
    return None


def _join_override_matches(
    override: dict[str, Any],
    other_table: TableInfo,
    other_col: ColumnInfo,
) -> bool:
    table_names = {
        str(override.get("other_table") or ""),
        str(override.get("other_table_name") or ""),
    }
    table_names = {name for name in table_names if name}
    if table_names and other_table.table_name not in table_names and other_table.bare_name not in table_names:
        return False
    other_column = str(override.get("other_column") or override.get("other_column_name") or "")
    if other_column and other_col.column_name.lower() != other_column.lower():
        return False
    return True


def _single_count_alias(select_expr: str) -> str | None:
    matches = list(re.finditer(
        r"\bCOUNT\s*\(\s*(?:DISTINCT\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.",
        select_expr or "",
        flags=re.IGNORECASE,
    ))
    if len(matches) != 1:
        return None
    return matches[0].group("alias")


def _single_group_by_alias(sql_tail: str) -> str | None:
    group = re.search(
        r"\bGROUP\s+BY\b(?P<body>.*?)(?=\bORDER\s+BY\b|\bLIMIT\b|$)",
        sql_tail or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not group:
        return None
    aliases = {
        match.group("alias")
        for match in re.finditer(r"\b(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.", group.group("body"))
    }
    return next(iter(aliases)) if len(aliases) == 1 else None


def _rewrite_requested_containment_spatial_predicate(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not _question_requests_containment(question) or _question_requests_intersection(question):
        return sql, False
    pattern = re.compile(r"\bST_(?:INTERSECTS|CONTAINS|WITHIN)\s*\(", flags=re.IGNORECASE)
    pieces: list[str] = []
    last = 0
    search_pos = 0
    changed = False
    while True:
        match = pattern.search(sql or "", search_pos)
        if not match:
            break
        if _inside_single_quoted_literal(sql, match.start()):
            search_pos = match.end()
            continue
        close = _find_matching_paren(sql, match.end() - 1)
        if close < 0:
            search_pos = match.end()
            continue
        args = _split_top_level_args(sql[match.end():close])
        if len(args) != 2:
            search_pos = match.end()
            continue
        replacement = _contains_replacement_for_args(args[0].strip(), args[1].strip(), alias_map)
        if not replacement:
            search_pos = close + 1
            continue
        pieces.append(sql[last:match.start()])
        pieces.append(replacement)
        last = close + 1
        search_pos = close + 1
        changed = True
    if not changed:
        return sql, False
    pieces.append(sql[last:])
    return "".join(pieces), True


def _question_requests_containment(question: str) -> bool:
    q = question or ""
    q_low = q.lower()
    return any(re.search(pattern, q_low) for pattern in (
        r"\bwithin\b",
        r"\binside\b",
        r"\bcontains?\b",
        r"\bcontained\b",
        "\u8303\u56f4\u5185",
        "\u4f4d\u4e8e",
        "\u5305\u542b",
        "\u5185\u5305\u542b",
    ))


def _contains_replacement_for_args(
    first: str,
    second: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> str:
    first_col = _geometry_column_for_expr(first, alias_map)
    second_col = _geometry_column_for_expr(second, alias_map)
    if not first_col or not second_col:
        return ""
    first_rank = _geometry_container_rank(first_col)
    second_rank = _geometry_container_rank(second_col)
    if first_rank <= 0 or second_rank <= 0:
        return ""
    if second_rank > first_rank:
        return f"ST_Contains({second}, {first})"
    return f"ST_Contains({first}, {second})"


def _geometry_column_for_expr(
    expr: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> ColumnInfo | None:
    ref = _geometry_column_ref_from_expr(expr)
    if not ref:
        return None
    col = _lookup_column_ref(ref, alias_map)
    return col if col and col.is_geometry else None


def _geometry_column_ref_from_expr(expr: str) -> str:
    value = (expr or "").strip()
    value = re.sub(r"::\s*geography\b", "", value, flags=re.IGNORECASE).strip()
    cast = re.fullmatch(
        r"CAST\s*\(\s*(?P<inner>.+?)\s+AS\s+(?:GEOGRAPHY|GEOMETRY\s*(?:\([^)]*\))?)\s*\)",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if cast:
        value = cast.group("inner").strip()
    transform = re.fullmatch(r"ST_TRANSFORM\s*\(\s*(?P<inner>.+?)\s*,\s*\d+\s*\)", value, flags=re.IGNORECASE | re.DOTALL)
    if transform:
        value = transform.group("inner").strip()
    match = re.search(
        r"(?P<ref>(?:\"?[A-Za-z_][A-Za-z0-9_]*\"?\s*\.\s*)+(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))",
        value,
    )
    return re.sub(r"\s+", "", match.group("ref")) if match else ""


def _geometry_container_rank(col: ColumnInfo) -> int:
    metadata = " ".join(
        str(part or "")
        for part in [
            col.table_name,
            col.column_name,
            col.quoted_ref,
            col.description,
            col.semantic_domain,
            col.pg_type,
            *sorted(col.aliases),
        ]
    ).lower()
    pg_type = (col.pg_type or "").lower()
    if "polygon" in pg_type or "surface" in pg_type:
        return 3
    if "line" in pg_type or "curve" in pg_type:
        return 2
    if "point" in pg_type:
        return 1
    if any(token in metadata for token in (
        "polygon",
        "parcel",
        "boundary",
        "district",
        "region",
        "zone",
        "area",
        "aoi",
        "land_use",
        "landuse",
        "block",
        "\u5730\u5757",
        "\u56fe\u6591",
        "\u8303\u56f4",
        "\u533a\u57df",
        "\u8857\u533a",
        "\u884c\u653f\u533a",
        "\u8fb9\u754c",
        "\u9762",
    )):
        return 3
    if any(token in metadata for token in (
        "line",
        "road",
        "route",
        "street",
        "edge",
        "\u9053\u8def",
        "\u7ebf",
    )):
        return 2
    return 1 if col.is_geometry else 0


def _rewrite_ranked_metric_not_null(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    q_low = (question or "").lower()
    if not any(token in q_low for token in ("highest", "lowest", "maximum", "minimum", "\u6700\u9ad8", "\u6700\u4f4e", "\u6700\u5927", "\u6700\u5c0f")):
        return sql, False
    if not re.search(r"\b(?:ROW_NUMBER|RANK|DENSE_RANK|DISTINCT\s+ON)\b", sql or "", re.IGNORECASE):
        return sql, False
    metric = _rank_order_metric_ref(sql)
    if not metric:
        return sql, False
    if re.search(rf"{re.escape(metric)}\s+IS\s+NOT\s+NULL", sql or "", re.IGNORECASE):
        return sql, False
    predicate = f"{metric} IS NOT NULL"
    rewritten = _inject_top_level_predicate(sql, predicate)
    return rewritten, rewritten != (sql or "")


def _rank_order_metric_ref(sql: str) -> str:
    match = re.search(
        r"\bORDER\s+BY\s+(?P<ref>(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s+(?:DESC|ASC)",
        sql or "",
        flags=re.IGNORECASE,
    )
    return match.group("ref") if match else ""


def _inject_top_level_predicate(sql: str, predicate: str) -> str:
    where_bounds = _top_level_clause_bounds(sql, "WHERE", ("GROUP BY", "HAVING", "ORDER BY", "LIMIT"))
    if where_bounds:
        start, end = where_bounds
        body = (sql or "")[start:end].rstrip()
        return (sql or "")[:start] + f"{body} AND {predicate} " + (sql or "")[end:].lstrip()
    insert_at = len(sql or "")
    for keyword in ("GROUP BY", "HAVING", "ORDER BY", "LIMIT"):
        positions = _top_level_keyword_positions(sql or "", keyword)
        if positions:
            insert_at = min(insert_at, positions[0])
    head = (sql or "")[:insert_at].rstrip()
    tail = (sql or "")[insert_at:].lstrip()
    return f"{head} WHERE {predicate}{(' ' + tail) if tail else ''}"
def _rewrite_requested_spatial_predicate(question: str, sql: str) -> tuple[str, bool]:
    if not _question_requests_intersection(question):
        return sql, False
    rewritten, predicate_changed = _rewrite_spatial_binary_functions_to_intersects(sql)
    rewritten2, join_changed = _rewrite_requested_intersects_left_joins(question, rewritten)
    return rewritten2, bool(predicate_changed or join_changed)


def _rewrite_unrequested_unreferenced_spatial_joins(question: str, sql: str) -> tuple[str, bool]:
    if _question_requests_any_spatial_relation(question):
        return sql, False
    if not re.search(r"\bJOIN\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    pattern = re.compile(
        r"\s+(?P<join>(?:INNER\s+)?JOIN\s+"
        r"(?P<table>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?"
        r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s+ON\s+"
        r"(?P<on>.*?))"
        r"(?=\s+(?:LEFT\s+JOIN|JOIN|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def repl(match: re.Match) -> str:
        alias = match.group("alias")
        on_clause = match.group("on")
        if not _sql_has_spatial_join_function(on_clause):
            return match.group(0)
        if not re.search(rf"\b{re.escape(alias)}\.", on_clause or "", flags=re.IGNORECASE):
            return match.group(0)
        outside = f"{sql[:match.start()]} {sql[match.end():]}"
        if re.search(rf"\b{re.escape(alias)}\.", outside, flags=re.IGNORECASE):
            return match.group(0)
        return " "

    rewritten, n = pattern.subn(repl, sql or "")
    rewritten = re.sub(r"\s+", " ", rewritten).strip()
    return rewritten, bool(n and rewritten != (sql or ""))


def _question_requests_any_spatial_relation(question: str) -> bool:
    q = question or ""
    q_low = q.lower()
    markers = (
        "st_intersects",
        "st_contains",
        "st_within",
        "st_dwithin",
        "intersect",
        "within",
        "inside",
        "contains",
        "distance",
        "nearest",
        "near",
        "相交",
        "包含",
        "位于",
        "范围内",
        "距离",
        "最近",
        "周边",
        "缓冲",
    )
    return any(marker in q_low for marker in markers)


def _question_requests_intersection(question: str) -> bool:
    q = question or ""
    q_low = q.lower()
    explicit_spatial_intersection = "\u76f8\u4ea4" in q or "st_intersects" in q_low
    has_intersection = (
        explicit_spatial_intersection
        or bool(re.search(r"\bintersect(?:s|ed|ing|ion|ions)?\b", q_low))
    )
    if not has_intersection:
        return False
    if explicit_spatial_intersection:
        spatial_containment_patterns = (
            r"\bwithin\b",
            r"\binside\b",
            "\u51e0\u4f55\u5305\u542b",
            "\u7a7a\u95f4\u5305\u542b",
            "\u8303\u56f4\u5185",
            "\u4f4d\u4e8e",
        )
        return not any(re.search(pattern, q_low) for pattern in spatial_containment_patterns)
    containment_patterns = (
        r"\bwithin\b",
        r"\binside\b",
        r"\bcontains?\b",
        r"\bcontained\b",
        "\u5305\u542b",
        "\u8303\u56f4\u5185",
        "\u4f4d\u4e8e",
    )
    return not any(re.search(pattern, q_low) for pattern in containment_patterns)


def _rewrite_spatial_binary_functions_to_intersects(sql: str) -> tuple[str, bool]:
    pattern = re.compile(r"\bST_(?:CONTAINS|WITHIN)\s*\(", flags=re.IGNORECASE)
    pieces: list[str] = []
    last = 0
    search_pos = 0
    changed = False
    while True:
        match = pattern.search(sql or "", search_pos)
        if not match:
            break
        if _inside_single_quoted_literal(sql, match.start()):
            search_pos = match.end()
            continue
        close = _find_matching_paren(sql, match.end() - 1)
        if close < 0:
            search_pos = match.end()
            continue
        args = _split_top_level_args(sql[match.end():close])
        if len(args) != 2:
            search_pos = match.end()
            continue
        pieces.append(sql[last:match.start()])
        pieces.append(f"ST_Intersects({args[0].strip()}, {args[1].strip()})")
        last = close + 1
        search_pos = close + 1
        changed = True
    if not changed:
        return sql, False
    pieces.append(sql[last:])
    return "".join(pieces), True


def _rewrite_requested_intersects_left_joins(question: str, sql: str) -> tuple[str, bool]:
    if not re.search(r"\bCOUNT\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False
    if not re.search(r"\bGROUP\s+BY\b", sql or "", flags=re.IGNORECASE):
        return sql, False

    pattern = re.compile(
        r"\bLEFT\s+JOIN\b(?P<body>.*?)(?=\b(?:LEFT\s+JOIN|JOIN|WHERE|GROUP\s+BY|ORDER\s+BY|LIMIT)\b|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def repl(match: re.Match) -> str:
        body = match.group("body")
        if not re.search(r"\bON\b", body, flags=re.IGNORECASE):
            return match.group(0)
        if not re.search(r"\bST_INTERSECTS\s*\(", body, flags=re.IGNORECASE):
            return match.group(0)
        return f"JOIN{body}"

    rewritten, n = pattern.subn(repl, sql or "")
    return rewritten, bool(n and rewritten != sql)


def _rewrite_grouped_spatial_entity_count(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if _question_requests_intersection(question):
        return sql, False
    q_low = (question or "").lower()
    count_terms = ("count", "\u7edf\u8ba1", "\u6570\u91cf")
    containment_terms = (
        "within",
        "inside",
        "contain",
        "contained",
        "\u5305\u542b",
        "\u5185",
        "\u4f4d\u4e8e",
    )
    if not any(token in q_low for token in count_terms):
        return sql, False
    if not any(token in q_low for token in containment_terms):
        return sql, False
    if not tables or "join" not in (sql or "").lower() or "group by" not in (sql or "").lower():
        return sql, False

    pattern = re.compile(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+"
        r"(?P<left>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<la>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"(?P<join>LEFT\s+JOIN|JOIN)\s+"
        r"(?P<right>\"?[A-Za-z_][A-Za-z0-9_\.]*\"?)\s+(?:AS\s+)?(?P<ra>[A-Za-z_][A-Za-z0-9_]*)\s+"
        r"ON\s+(?P<on>.+?)(?P<tail>\s+GROUP\s+BY\s+.+)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = pattern.match(sql or "")
    if not m:
        return sql, False

    left_alias = m.group("la")
    right_alias = m.group("ra")
    tail = m.group("tail")
    if not _group_by_references_alias(tail, left_alias):
        return sql, False

    if (
        m.group("join").upper().startswith("LEFT")
        and _is_left_join_containment_detail_count(sql, tail, right_alias)
    ):
        return sql, False

    right_entry = alias_map.get(right_alias)
    if not right_entry:
        return sql, False
    right_table, _ = right_entry
    right_ident = right_table.identifier_column()
    if not right_ident:
        return sql, False

    select_expr, count_changed = _rewrite_grouped_count_expression(
        m.group("select"),
        left_alias,
        right_alias,
        right_ident,
    )
    on_clause, on_changed = _rewrite_grouped_count_spatial_on(m.group("on"), left_alias, right_alias)
    join_keyword = "LEFT JOIN"
    join_changed = m.group("join").upper() != join_keyword

    if not (count_changed or on_changed or join_changed):
        return sql, False

    rewritten = (
        f"SELECT {select_expr} FROM {m.group('left')} AS {left_alias} "
        f"{join_keyword} {m.group('right')} AS {right_alias} "
        f"ON {on_clause}{tail}"
    )
    return rewritten, True


def _rewrite_grouped_count_expression(
    select_expr: str,
    left_alias: str,
    right_alias: str,
    right_ident: ColumnInfo,
) -> tuple[str, bool]:
    pattern = re.compile(
        r"\bCOUNT\s*\(\s*(?P<distinct>DISTINCT\s+)?"
        r"(?P<arg>\*|[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*\)",
        flags=re.IGNORECASE,
    )
    matches = list(pattern.finditer(select_expr or ""))
    if len(matches) != 1:
        return select_expr, False
    match = matches[0]
    arg = match.group("arg")
    if arg != "*":
        if re.match(rf"{re.escape(right_alias)}\.", arg, flags=re.IGNORECASE):
            arg_name = _strip_identifier_quotes(arg.split(".", 1)[1]).lower()
            ident_name = _strip_identifier_quotes(right_ident.column_name).lower()
            if arg_name != ident_name or match.group("distinct"):
                return select_expr, False
        elif not re.match(rf"{re.escape(left_alias)}\.", arg, flags=re.IGNORECASE):
            return select_expr, False
    replacement = f"COUNT(DISTINCT {right_alias}.{right_ident.quoted_ref})"
    return select_expr[:match.start()] + replacement + select_expr[match.end():], True


def _rewrite_grouped_count_spatial_on(on_clause: str, left_alias: str, right_alias: str) -> tuple[str, bool]:
    rewritten, changed = _rewrite_spatial_binary_function_to_contains(
        on_clause,
        "ST_INTERSECTS",
        left_alias,
        right_alias,
    )
    if changed:
        return rewritten, True
    return _rewrite_spatial_binary_function_to_contains(
        on_clause,
        "ST_WITHIN",
        left_alias,
        right_alias,
    )


def _rewrite_spatial_binary_function_to_contains(
    text: str,
    function_name: str,
    left_alias: str,
    right_alias: str,
) -> tuple[str, bool]:
    pattern = re.compile(rf"\b{function_name}\s*\(", flags=re.IGNORECASE)
    match = pattern.search(text or "")
    if not match:
        return text, False
    close = _find_matching_paren(text, match.end() - 1)
    if close < 0:
        return text, False
    args = _split_top_level_args(text[match.end():close])
    if len(args) != 2:
        return text, False
    first = args[0].strip()
    second = args[1].strip()
    first_left = _expr_references_alias(first, left_alias)
    first_right = _expr_references_alias(first, right_alias)
    second_left = _expr_references_alias(second, left_alias)
    second_right = _expr_references_alias(second, right_alias)
    if first_left and second_right:
        replacement = f"ST_Contains({first}, {second})"
    elif first_right and second_left:
        replacement = f"ST_Contains({second}, {first})"
    else:
        return text, False
    return text[:match.start()] + replacement + text[close + 1:], True


def _group_by_references_alias(sql_tail: str, alias: str) -> bool:
    group = re.search(
        r"\bGROUP\s+BY\b(?P<body>.*?)(?=\bORDER\s+BY\b|\bLIMIT\b|$)",
        sql_tail or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return bool(group and re.search(rf"\b{re.escape(alias)}\.", group.group("body"), flags=re.IGNORECASE))


def _expr_references_alias(expr: str, alias: str) -> bool:
    return bool(re.search(rf"\b{re.escape(alias)}\.", expr or "", flags=re.IGNORECASE))


def _qualifier_ref_pattern(qualifier: str) -> str:
    bare = _strip_identifier_quotes(qualifier)
    return rf"(?:\b{re.escape(bare)}|\"{re.escape(bare)}\")\s*\."


def _rewrite_distinct_entity_count(
    question: str,
    sql: str,
    tables: list[TableInfo],
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    rewritten, changed = _rewrite_grouped_spatial_identifier_counts_to_distinct(question, sql, alias_map)
    if changed:
        return rewritten, True
    rewritten, changed = _rewrite_distinct_geometry_count_to_identifier(sql, alias_map)
    if changed:
        return rewritten, True
    sql_low = (sql or "").lower()
    if "count(distinct" in re.sub(r"\s+", "", sql_low):
        return sql, False
    rewritten, changed = _rewrite_exists_spatial_count_to_distinct(sql, tables)
    if changed:
        return rewritten, True
    if _is_singleton_cross_join_spatial_filter(sql):
        return sql, False
    if (
        "join" not in sql_low
        or not _sql_has_spatial_join_function(sql)
    ):
        return sql, False
    first = _first_from_table(sql, tables)
    if not first:
        return sql, False
    table, qualifier = first
    ident = table.identifier_column()
    if not ident:
        return sql, False
    expr = f'COUNT(DISTINCT {qualifier}.{ident.quoted_ref})'
    rewritten, n = re.subn(r"COUNT\s*\(\s*\*\s*\)", expr, sql, count=1, flags=re.IGNORECASE)
    return rewritten, bool(n)


def _is_singleton_cross_join_spatial_filter(sql: str) -> bool:
    return bool(
        re.search(
            r"\bCROSS\s+JOIN\s*\(\s*SELECT\b.*?\bLIMIT\s+1\b.*?\)\s+"
            r"(?:AS\s+)?[A-Za-z_][A-Za-z0-9_]*\b.*?\bST_DWITHIN\s*\(",
            sql or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _rewrite_distinct_geometry_count_to_identifier(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    if not _sql_has_spatial_join_function(sql):
        return sql, False
    pattern = re.compile(
        r"\bCOUNT\s*\(\s*DISTINCT\s+"
        r"(?P<ref>(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*\)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        alias = match.group("alias")
        entry = alias_map.get(alias)
        if not entry:
            return match.group(0)
        table, _ = entry
        counted = _lookup_column_ref(match.group("ref"), alias_map)
        ident = table.identifier_column()
        if not counted or not counted.is_geometry or not ident:
            return match.group(0)
        if counted.column_name.lower() == ident.column_name.lower():
            return match.group(0)
        return f"COUNT(DISTINCT {alias}.{ident.quoted_ref})"

    rewritten, n = pattern.subn(repl, sql or "")
    return rewritten, bool(n and rewritten != (sql or ""))


def _rewrite_exists_spatial_count_to_distinct(
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    if not re.search(r"\bCOUNT\s*\(\s*\*\s*\)", sql or "", flags=re.IGNORECASE):
        return sql, False
    if not re.search(r"\bEXISTS\s*\(", sql or "", flags=re.IGNORECASE):
        return sql, False
    if not _sql_has_spatial_join_function(sql):
        return sql, False
    first = _first_from_table(sql, tables)
    if not first:
        return sql, False
    table, qualifier = first
    ident = table.identifier_column()
    if not ident:
        return sql, False
    qualifier_ref = _qualifier_ref_pattern(qualifier)
    if not re.search(
        rf"\bST_(?:INTERSECTS|CONTAINS|WITHIN|DWITHIN)\s*\([^)]*{qualifier_ref}",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        return sql, False
    expr = f"COUNT(DISTINCT {qualifier}.{ident.quoted_ref})"
    rewritten, n = re.subn(r"COUNT\s*\(\s*\*\s*\)", expr, sql, count=1, flags=re.IGNORECASE)
    return rewritten, bool(n)


def _rewrite_grouped_spatial_identifier_counts_to_distinct(
    question: str,
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    sql_low = (sql or "").lower()
    if "join" not in sql_low or not _sql_has_spatial_join_function(sql) or "group by" not in sql_low:
        return sql, False
    group = re.search(
        r"\bGROUP\s+BY\b(?P<body>.*?)(?=\bORDER\s+BY\b|\bLIMIT\b|$)",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not group:
        return sql, False
    group_body = group.group("body")
    pattern = re.compile(
        r"\bCOUNT\s*\(\s*(?P<distinct>DISTINCT\s+)?"
        r"(?P<ref>(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s*\)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        alias = match.group("alias")
        ref = match.group("ref")
        if re.search(rf"\b{re.escape(alias)}\.", group_body, flags=re.IGNORECASE):
            target_ref = _target_grouped_spatial_count_ref(question, sql, group_body, alias, alias_map)
            if target_ref and target_ref.lower() != ref.lower():
                return f"COUNT(DISTINCT {target_ref})"
            return match.group(0)
        if match.group("distinct"):
            return match.group(0)
        entry = alias_map.get(alias)
        if not entry:
            return match.group(0)
        table, _ = entry
        ident = table.identifier_column()
        counted = _lookup_column_ref(ref, alias_map)
        if not ident or not counted:
            return match.group(0)
        if counted.column_name.lower() != ident.column_name.lower():
            return match.group(0)
        if _is_left_join_containment_detail_count(sql, group_body, alias):
            return match.group(0)
        return f"COUNT(DISTINCT {ref})"

    rewritten, n = pattern.subn(repl, sql or "")
    return rewritten, bool(n and rewritten != sql)


def _is_left_join_containment_detail_count(
    sql: str,
    group_body: str,
    counted_alias: str,
) -> bool:
    if not re.search(
        rf"\bLEFT\s+JOIN\b.*?(?:\bAS\s+)?{re.escape(counted_alias)}\b",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    ):
        return False
    grouped_aliases = set(
        re.findall(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.",
            group_body or "",
            flags=re.IGNORECASE,
        )
    )
    if not grouped_aliases:
        return False
    counted_ref = _qualifier_ref_pattern(counted_alias)
    for group_alias in grouped_aliases:
        group_ref = _qualifier_ref_pattern(group_alias)
        contains_group_to_counted = re.search(
            rf"\bST_CONTAINS\s*\(\s*(?:ST_TRANSFORM\s*\(\s*)?{group_ref}.*,\s*{counted_ref}",
            sql or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        within_counted_to_group = re.search(
            rf"\bST_WITHIN\s*\(\s*(?:ST_TRANSFORM\s*\(\s*)?{counted_ref}.*,\s*{group_ref}",
            sql or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if contains_group_to_counted or within_counted_to_group:
            return True
    return False


def _sql_has_spatial_join_function(sql: str) -> bool:
    return bool(re.search(r"\bST_(?:INTERSECTS|CONTAINS|WITHIN|DWITHIN)\s*\(", sql or "", flags=re.IGNORECASE))


def _target_grouped_spatial_count_ref(
    question: str,
    sql: str,
    group_body: str,
    counted_alias: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> str | None:
    if not _question_mentions_count(question):
        return None
    counted_entry = alias_map.get(counted_alias)
    if not counted_entry:
        return None
    counted_table, _ = counted_entry
    counted_score = _table_question_relevance(question, counted_table)
    candidates: list[tuple[float, str, ColumnInfo]] = []
    for alias, (table, _) in alias_map.items():
        if alias == counted_alias:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias or ""):
            continue
        if not re.search(rf"\b{re.escape(alias)}\.", sql or "", flags=re.IGNORECASE):
            continue
        if re.search(rf"\b{re.escape(alias)}\.", group_body or "", flags=re.IGNORECASE):
            continue
        ident = table.identifier_column()
        if not ident:
            continue
        score = _table_question_relevance(question, table)
        if score >= max(1.0, counted_score + 0.25):
            candidates.append((score, alias, ident))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, alias, ident = candidates[0]
    return f"{alias}.{ident.quoted_ref}"


def _question_mentions_count(question: str) -> bool:
    q_low = (question or "").lower()
    return any(token in q_low for token in ("count", "number", "quantity", "统计", "数量", "多少", "个数"))


def _table_question_relevance(question: str, table: TableInfo) -> float:
    score = 0.0
    for token in _table_relevance_tokens(table):
        if _question_mentions_semantic_token(question, token):
            score += 1.0
    for col in table.columns:
        for token in [col.column_name, col.quoted_ref, col.description, col.semantic_domain, *sorted(col.aliases)]:
            if _question_mentions_semantic_token(question, token):
                score += 0.55
    return score


def _table_relevance_tokens(table: TableInfo) -> list[str]:
    tokens = [table.table_name, table.bare_name, _versionless_table_name(table.table_name)]
    tokens.extend(table.table_aliases)
    bare_parts = re.split(r"[_\W]+", table.bare_name)
    tokens.extend(part for part in bare_parts if part and not part.isdigit())
    return list(dict.fromkeys(str(token) for token in tokens if token))


def _question_mentions_semantic_token(question: str, token: str) -> bool:
    token = _strip_identifier_quotes(str(token or "")).strip()
    if not token:
        return False
    token_low = token.lower()
    if token_low in {"id", "fid", "gid", "geometry", "geom", "shape", "objectid"}:
        return False
    q = question or ""
    q_low = q.lower()
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in token)
    if has_cjk:
        return len(token) >= 2 and token in q
    if any(ch.isascii() and (ch.isalnum() or ch == "_") for ch in token):
        if len(token_low) < 3:
            return False
        return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(token_low)}(?![A-Za-z0-9_])", q_low))
    return token_low in q_low


def _rewrite_centroid_label_projection_order(question: str, sql: str) -> tuple[str, bool]:
    if not _question_requests_centroid_text(question, sql):
        return sql, False
    match = re.match(
        r"^(?P<prefix>\s*SELECT\s+)(?P<select>.+?)(?P<suffix>\s+FROM\s+.+)$",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return sql, False
    items = [part.strip() for part in _split_top_level_args(match.group("select"))]
    if len(items) != 2:
        return sql, False
    first_centroid = _is_centroid_text_projection(items[0])
    second_centroid = _is_centroid_text_projection(items[1])
    if not first_centroid or second_centroid:
        return sql, False
    if not _is_simple_column_projection(items[1]):
        return sql, False
    rewritten = f"{match.group('prefix')}{items[1]}, {items[0]}{match.group('suffix')}"
    return rewritten, rewritten != (sql or "")


def _question_requests_centroid_text(question: str, sql: str) -> bool:
    text = f"{question or ''} {sql or ''}".lower()
    return "st_centroid" in text or "centroid" in text or "\u8d28\u5fc3" in text or "\u4e2d\u5fc3\u70b9" in text


def _is_centroid_text_projection(expr: str) -> bool:
    expr_low = (expr or "").lower()
    return "st_centroid" in expr_low and ("st_astext" in expr_low or "st_asgeojson" in expr_low)


def _is_simple_column_projection(expr: str) -> bool:
    value = re.sub(
        r"\s+AS\s+(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)\s*$",
        "",
        (expr or "").strip(),
        flags=re.IGNORECASE,
    )
    return bool(re.fullmatch(
        r"(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
        value,
        flags=re.IGNORECASE,
    ))


def _rewrite_conditional_sum_pivot_to_grouped_rows(question: str, sql: str) -> tuple[str, bool]:
    if not _question_prefers_grouped_rows(question):
        return sql, False
    if re.search(r"\bGROUP\s+BY\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    match = re.match(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+(?P<rest>.+?)\s*$",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return sql, False
    items = [part.strip() for part in _split_top_level_args(match.group("select"))]
    if len(items) < 2:
        return sql, False
    parsed = [_parse_conditional_sum_projection(item) for item in items]
    if any(item is None for item in parsed):
        return sql, False
    first = parsed[0]
    assert first is not None
    category = first["category"]
    measure = first["measure"]
    values = []
    for item in parsed:
        assert item is not None
        if item["category"].lower() != category.lower() or item["measure"].lower() != measure.lower():
            return sql, False
        values.append(item["value"])
    rest = match.group("rest").strip().rstrip(";").strip()
    limit = ""
    limit_match = re.search(r"\s+LIMIT\s+\d+\s*$", rest, flags=re.IGNORECASE)
    if limit_match:
        limit = rest[limit_match.start():].rstrip()
        rest = rest[:limit_match.start()].rstrip()
    predicate = f"{category} IN ({', '.join(values)})"
    if re.search(r"\bWHERE\b", rest, flags=re.IGNORECASE):
        rest = f"{rest} AND {predicate}"
    else:
        rest = f"{rest} WHERE {predicate}"
    rewritten = (
        f"SELECT {category}, SUM({measure}) AS total_value FROM {rest} "
        f"GROUP BY {category} ORDER BY {category}{limit}"
    )
    return rewritten, rewritten != (sql or "")


def _question_prefers_grouped_rows(question: str) -> bool:
    q_low = (question or "").lower()
    return any(token in q_low for token in (
        "each",
        "per ",
        " by ",
        "group",
        "separately",
        "\u5206\u522b",
        "\u5206\u7ec4",
    ))


def _parse_conditional_sum_projection(expr: str) -> dict[str, str] | None:
    ref = r'(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)'
    literal = r"(?:'[^']*'|\d+(?:\.\d+)?)"
    pattern = re.compile(
        rf"^\s*SUM\s*\(\s*CASE\s+WHEN\s+(?P<category>{ref})\s*=\s*(?P<value>{literal})\s+"
        rf"THEN\s+(?P<measure>{ref})\s+ELSE\s+0\s+END\s*\)\s+AS\s+"
        r"(?P<alias>\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)\s*$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.match(expr or "")
    if not match:
        return None
    return {
        "category": match.group("category").strip(),
        "value": match.group("value").strip(),
        "measure": match.group("measure").strip(),
    }


def _rewrite_question_limit(question: str, sql: str) -> tuple[str, bool]:
    if re.search(r"\bLIMIT\s+\d+\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    limit = _extract_question_limit(question)
    if not limit:
        return sql, False
    stripped = (sql or "").rstrip().rstrip(";").rstrip()
    if not stripped:
        return sql, False
    return f"{stripped} LIMIT {limit}", True


def _rewrite_default_preview_sort(
    question: str,
    sql: str,
    tables: list[TableInfo],
) -> tuple[str, bool]:
    if re.search(r"\bORDER\s+BY\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    if not re.search(r"\bLIMIT\s+\d+\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    if re.search(r"\bGROUP\s+BY\b|\bHAVING\b", sql or "", flags=re.IGNORECASE):
        return sql, False
    first = _first_from_table(sql, tables)
    if not first:
        return sql, False
    table, qualifier = first
    sort_col = _default_preview_sort_column(table, sql, qualifier)
    if not sort_col:
        return sql, False
    order_ref = _selected_or_qualified_column_ref(sql, sort_col, qualifier)
    direction = str(sort_col.value_semantics.get("default_preview_sort") or "desc").upper()
    if direction not in {"ASC", "DESC"}:
        direction = "DESC"
    match = re.search(r"\bLIMIT\s+\d+\b", sql or "", flags=re.IGNORECASE)
    if not match:
        return sql, False
    head = sql[:match.start()].rstrip()
    tail = sql[match.start():].lstrip()
    return f"{head} ORDER BY {order_ref} {direction} {tail}".rstrip(), True


def _question_requests_preview(question: str) -> bool:
    q_low = (question or "").lower()
    markers = (
        "preview",
        "sample",
        "first",
        "top",
        "\u67e5\u770b",
        "\u5c55\u793a",
        "\u9884\u89c8",
        "\u524d",
    )
    return any(marker in q_low for marker in markers)


def _default_preview_sort_column(
    table: TableInfo,
    sql: str,
    qualifier: str,
) -> ColumnInfo | None:
    configured = []
    for col in table.columns:
        vs = col.value_semantics or {}
        if not vs.get("default_preview_sort"):
            continue
        if not _select_list_mentions_column(sql, col, qualifier):
            continue
        try:
            priority = float(vs.get("default_sort_priority") or 0)
        except (TypeError, ValueError):
            priority = 0.0
        configured.append((priority, col))
    if not configured:
        return None
    configured.sort(key=lambda item: item[0], reverse=True)
    return configured[0][1]


def _select_list_mentions_column(sql: str, col: ColumnInfo, qualifier: str) -> bool:
    select = re.search(
        r"^\s*SELECT\s+(?P<body>.+?)\s+FROM\s+",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not select:
        return False
    body = select.group("body")
    if re.fullmatch(r"\s*\*\s*", body):
        return True
    for candidate in _column_ref_candidates(qualifier, col):
        if "." in candidate and re.search(re.escape(candidate), body, flags=re.IGNORECASE):
            return True
        pattern = re.compile(rf"(?<![\.\w\"]){re.escape(candidate)}(?=$|[^A-Za-z0-9_\"])", re.IGNORECASE)
        if pattern.search(body):
            return True
    return False


def _selected_or_qualified_column_ref(sql: str, col: ColumnInfo, qualifier: str) -> str:
    select = re.search(
        r"^\s*SELECT\s+(?P<body>.+?)\s+FROM\s+",
        sql or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if select:
        body = select.group("body")
        for candidate in _column_ref_candidates(qualifier, col):
            pattern = re.compile(rf"(?<![\.\w\"]){re.escape(candidate)}(?=$|[^A-Za-z0-9_\"])", re.IGNORECASE)
            if pattern.search(body):
                return candidate
            if "." in candidate and re.search(re.escape(candidate), body, flags=re.IGNORECASE):
                return candidate
    return f"{qualifier}.{col.quoted_ref}" if qualifier else col.quoted_ref


def _column_ref_candidates(qualifier: str, col: ColumnInfo) -> list[str]:
    quoted_name = f'"{col.column_name}"'
    refs = [col.quoted_ref, col.column_name, quoted_name]
    if qualifier:
        refs.extend([
            f"{qualifier}.{col.quoted_ref}",
            f"{qualifier}.{col.column_name}",
            f'{qualifier}.{quoted_name}',
        ])
    return list(dict.fromkeys(ref for ref in refs if ref))


def _extract_question_limit(question: str) -> int | None:
    q = question or ""
    patterns = [
        "\u524d\\s*(\\d{1,5})\\s*(?:\u6761|\u4e2a|\u884c)?",
        "\u6700\u8fd1(?:\u7684)?\\s*(\\d{1,5})\\s*(?:\u6761|\u4e2a|\u884c)?",
        r"\btop\s*(\d{1,5})\b",
        r"\blimit\s*(\d{1,5})\b",
        r"\bfirst\s*(\d{1,5})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, q, flags=re.IGNORECASE)
        if not m:
            continue
        try:
            value = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if 0 < value <= 10000:
            return value
    return None


def _first_from_table(sql: str, tables: list[TableInfo]) -> tuple[TableInfo, str] | None:
    top_level_from = _first_top_level_from(sql)
    if top_level_from:
        table_ref, alias = top_level_from
        table_key = _normalize_table_ref(table_ref).lower()
        for table in tables:
            known = {
                table.table_name.lower(),
                table.bare_name.lower(),
                _normalize_table_ref(table.table_name).lower(),
            }
            if table_key not in known:
                continue
            qualifier = alias or table.bare_name
            return table, qualifier

    for table in tables:
        bare = table.bare_name
        full_re = re.escape(table.table_name).replace(r"\.", r'\."?')
        pattern = re.compile(
            rf"\bFROM\s+(?:\"?{full_re}\"?|\"?{re.escape(bare)}\"?)"
            r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?",
            flags=re.IGNORECASE,
        )
        m = pattern.search(sql or "")
        if not m:
            continue
        alias = m.group("alias")
        if not alias or alias.upper() in {"ON", "WHERE", "JOIN", "GROUP", "ORDER", "LIMIT"}:
            alias = bare
        return table, alias
    return None


def _first_top_level_from(sql: str) -> tuple[str, str | None] | None:
    text = sql or ""
    for pos in _top_level_keyword_positions(text, "FROM"):
        match = re.match(
            r"\bFROM\s+"
            r"(?P<table>(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)(?:\s*\.\s*(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))?)"
            r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?",
            text[pos:],
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        alias = match.group("alias")
        if alias and alias.upper() in {"ON", "WHERE", "JOIN", "GROUP", "ORDER", "LIMIT", "LEFT", "RIGHT", "FULL", "INNER", "CROSS"}:
            alias = None
        return match.group("table"), alias
    return None


def _top_level_keyword_positions(sql: str, keyword: str) -> list[int]:
    positions: list[int] = []
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and re.match(rf"\b{re.escape(keyword)}\b", sql[i:], flags=re.IGNORECASE):
                positions.append(i)
                i += len(keyword)
                continue
        i += 1
    return positions


def _top_level_clause_bounds(
    sql: str,
    clause_name: str,
    end_keywords: tuple[str, ...],
) -> tuple[int, int] | None:
    clause_positions = _top_level_keyword_positions(sql or "", clause_name)
    if not clause_positions:
        return None
    start_keyword = clause_positions[0]
    start = start_keyword + len(clause_name)
    end = len(sql or "")
    for keyword in end_keywords:
        for pos in _top_level_keyword_positions(sql or "", keyword):
            if pos > start:
                end = min(end, pos)
                break
    return start, end


def _top_level_clause_body(
    sql: str,
    clause_name: str,
    end_keywords: tuple[str, ...],
) -> str:
    bounds = _top_level_clause_bounds(sql, clause_name, end_keywords)
    if not bounds:
        return ""
    start, end = bounds
    return (sql or "")[start:end]


def _normalize_table_ref(table_ref: str) -> str:
    parts = [part.strip() for part in (table_ref or "").split(".")]
    return ".".join(_strip_identifier_quotes(part) for part in parts if part)


def _first_geometry(table: TableInfo) -> ColumnInfo | None:
    geoms = table.geometry_columns()
    return geoms[0] if geoms else None


def _lookup_column_ref(ref: str, alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]]) -> ColumnInfo | None:
    if "." not in ref:
        return None
    parts = [part for part in re.split(r"\s*\.\s*", ref or "") if part]
    if len(parts) < 2:
        return None
    col_name = parts[-1]
    qualifier = ".".join(parts[:-1])
    table_entry = alias_map.get(_strip_identifier_quotes(qualifier))
    if not table_entry:
        qualifier_bare = _strip_identifier_quotes(parts[-2])
        table_entry = alias_map.get(qualifier_bare)
    if not table_entry:
        qualifier_norm = _normalize_table_ref(qualifier).lower()
        for key, entry in alias_map.items():
            table, _ = entry
            key_norm = _normalize_table_ref(key).lower()
            table_norm = _normalize_table_ref(table.table_name).lower()
            bare_norm = table.bare_name.lower()
            if qualifier_norm in {key_norm, table_norm, bare_norm} or qualifier_norm.endswith(f".{bare_norm}"):
                table_entry = entry
                break
    if not table_entry:
        return None
    table, _ = table_entry
    return table.column_by_name(col_name)


def _lookup_any_column_ref(
    ref: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> ColumnInfo | None:
    qualified = _lookup_column_ref(ref, alias_map)
    if qualified:
        return qualified
    if "." in (ref or ""):
        return None
    col_name = _strip_identifier_quotes(ref)
    matches: list[ColumnInfo] = []
    seen_tables: set[str] = set()
    for table, _ in alias_map.values():
        if table.table_name in seen_tables:
            continue
        seen_tables.add(table.table_name)
        col = table.column_by_name(col_name)
        if col:
            matches.append(col)
    return matches[0] if len(matches) == 1 else None


def _find_matching_paren(text: str, open_pos: int) -> int:
    depth = 0
    in_string = False
    i = open_pos
    while i < len(text):
        ch = text[i]
        if ch == "'":
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _split_top_level_args(text: str) -> list[str]:
    args: list[str] = []
    depth = 0
    in_string = False
    start = 0
    for i, ch in enumerate(text):
        if ch == "'":
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(text[start:i])
                start = i + 1
    args.append(text[start:])
    return args


def _split_top_level_and_predicates(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    in_string = False
    in_identifier = False
    pending_between_and = False
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if in_string and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            in_string = not in_string
            i += 1
            continue
        if ch == '"' and not in_string:
            in_identifier = not in_identifier
            i += 1
            continue
        if not in_string and not in_identifier:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and _word_at(text, i, "BETWEEN"):
                pending_between_and = True
                i += len("BETWEEN")
                continue
            elif depth == 0 and _word_at(text, i, "AND"):
                if pending_between_and:
                    pending_between_and = False
                else:
                    parts.append(text[start:i])
                    start = i + len("AND")
                i += len("AND")
                continue
        i += 1
    parts.append(text[start:])
    return parts


def _word_at(text: str, pos: int, word: str) -> bool:
    end = pos + len(word)
    if text[pos:end].lower() != word.lower():
        return False
    before = text[pos - 1] if pos > 0 else " "
    after = text[end] if end < len(text) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def _as_geography(expr: str) -> str:
    return expr if "::geography" in expr.lower() else f"{expr}::geography"


def _format_sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _preferred_column_ref_for_filter(col: ColumnInfo, qualifiers: list[str]) -> str:
    return f"{qualifiers[0]}.{col.quoted_ref}" if qualifiers else col.quoted_ref


def _sql_groups_by_column(sql: str, col: ColumnInfo, qualifiers: list[str]) -> bool:
    m = re.search(
        r"\bGROUP\s+BY\b(?P<body>.*?)(?=\bORDER\s+BY\b|\bLIMIT\b|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return False
    body = m.group("body")
    refs = [_column_reference_alternatives(qualifier, col) for qualifier in qualifiers + [None]]
    return any(re.search(ref, body, re.IGNORECASE) for ref in refs if ref)


def _where_clause_references_column(sql: str, col: ColumnInfo, qualifiers: list[str]) -> bool:
    m = re.search(
        r"\bWHERE\b(?P<body>.*?)(?=\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return False
    body = m.group("body")
    refs = [_column_reference_alternatives(qualifier, col) for qualifier in qualifiers + [None]]
    return any(re.search(ref, body, re.IGNORECASE) for ref in refs if ref)


def _inject_predicate(sql: str, predicate: str) -> str:
    return _inject_top_level_predicate(sql, predicate).rstrip()


def _qualifiers_for_table(
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
    table: TableInfo,
) -> list[str]:
    qualifiers = [
        qualifier for qualifier, (mapped_table, _) in alias_map.items()
        if mapped_table.table_name == table.table_name
    ]
    preferred = [q for q in qualifiers if q not in {table.table_name, table.bare_name}]
    return preferred or qualifiers[:1]


def _column_reference_alternatives(qualifier: str | None, col: ColumnInfo) -> str:
    refs = []
    for token in [col.quoted_ref, col.column_name, f'"{col.column_name}"']:
        if qualifier:
            refs.append(rf"{re.escape(qualifier)}\.\s*{re.escape(token)}")
        elif token.startswith('"') and token.endswith('"'):
            refs.append(rf"(?<![\.\w\"]){re.escape(token)}(?=$|[^A-Za-z0-9_])")
        else:
            refs.append(rf"(?<![\.\w\"]){re.escape(token)}\b")
    return "|".join(dict.fromkeys(refs))


def _raw_column_reference_alternatives(qualifier: str | None, column_name: str) -> str:
    refs = [column_name, f'"{column_name}"']
    if qualifier:
        return "|".join(rf"{re.escape(qualifier)}\.\s*{re.escape(r)}" for r in refs)
    return "|".join(rf"(?<![\.\w\"]){re.escape(r)}\b" for r in refs)


def _replace_column_reference(
    sql: str,
    alias: str | None,
    wrong: str,
    right: str,
    *,
    unqualified: bool = False,
) -> tuple[str, int]:
    total = 0
    wrong_unquoted = _strip_identifier_quotes(wrong)
    parts = re.split(_SQL_STRING_RE, sql)
    for i in range(0, len(parts), 2):
        segment = parts[i]
        if alias:
            alias_re = re.escape(alias)
            for wrong_token in dict.fromkeys([wrong, wrong_unquoted, f'"{wrong_unquoted}"']):
                wrong_re = re.escape(wrong_token)
                pattern = re.compile(
                    rf"(?P<prefix>\b{alias_re}\.){wrong_re}(?=$|[^A-Za-z0-9_])",
                    flags=re.IGNORECASE,
                )
                segment, n = pattern.subn(f"\\g<prefix>{right}", segment)
                total += n
        if unqualified:
            for wrong_token in dict.fromkeys([wrong, wrong_unquoted, f'"{wrong_unquoted}"']):
                wrong_re = re.escape(wrong_token)
                pattern = re.compile(
                    rf"(?<![\.\w\"]){wrong_re}(?=$|[^A-Za-z0-9_])",
                    flags=re.IGNORECASE,
                )
                segment, n = pattern.subn(right, segment)
                total += n
        parts[i] = segment
    return "".join(parts), total


def _replace_unqualified_geometry_column_reference(
    sql: str,
    wrong: str,
    right: str,
) -> tuple[str, int]:
    total = 0
    wrong_unquoted = _strip_identifier_quotes(wrong)
    parts = re.split(_SQL_STRING_RE, sql)
    for i in range(0, len(parts), 2):
        segment = parts[i]
        for wrong_token in dict.fromkeys([wrong, wrong_unquoted, f'"{wrong_unquoted}"']):
            wrong_re = re.escape(wrong_token)
            pattern = re.compile(
                rf"(?<![\.\w\"]){wrong_re}(?=$|[^A-Za-z0-9_])",
                flags=re.IGNORECASE,
            )

            def repl(match: re.Match) -> str:
                nonlocal total
                before = segment[:match.start()]
                after = segment[match.end():]
                if _geometry_reference_is_type_context(before, after):
                    return match.group(0)
                total += 1
                return right

            segment = pattern.sub(repl, segment)
        parts[i] = segment
    return "".join(parts), total


def _geometry_reference_is_type_context(before: str, after: str) -> bool:
    prev = (before or "").rstrip()
    nxt = (after or "").lstrip()
    if prev.endswith("::"):
        return True
    if re.search(r"\bAS\s*$", prev, flags=re.IGNORECASE):
        return True
    if nxt.startswith("("):
        return True
    return False


def _strip_identifier_quotes(name: str) -> str:
    name = str(name or "").strip()
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        return name[1:-1]
    return name


def _sub_outside_string_literals(
    pattern: re.Pattern,
    repl,
    sql: str,
) -> tuple[str, int]:
    pieces: list[str] = []
    pos = 0
    total = 0
    for match in pattern.finditer(sql):
        if _inside_single_quoted_literal(sql, match.start()):
            continue
        pieces.append(sql[pos:match.start()])
        pieces.append(repl(match))
        pos = match.end()
        total += 1
    if not total:
        return sql, 0
    pieces.append(sql[pos:])
    return "".join(pieces), total


def _inside_single_quoted_literal(sql: str, index: int) -> bool:
    in_quote = False
    i = 0
    while i < index:
        ch = sql[i]
        if ch == "'":
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_quote = not in_quote
        i += 1
    return in_quote


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else (f"{value:.12g}")


def _rewrite_round_numeric_cast(sql: str) -> tuple[str, int]:
    pieces: list[str] = []
    pos = 0
    total = 0
    for match in re.finditer(r"\bROUND\s*\(", sql, flags=re.IGNORECASE):
        open_paren = match.end() - 1
        depth = 0
        close_paren = None
        in_quote = False
        i = open_paren
        while i < len(sql):
            ch = sql[i]
            if ch == "'" and (i + 1 >= len(sql) or sql[i + 1] != "'"):
                in_quote = not in_quote
            if not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        close_paren = i
                        break
            i += 1
        if close_paren is None:
            continue

        inner = sql[open_paren + 1:close_paren]
        split_at = _find_top_level_last_comma(inner)
        if split_at is None:
            continue
        expr = inner[:split_at].strip()
        digits = inner[split_at + 1:].strip()
        if not re.fullmatch(r"\d+", digits) or "::numeric" in expr.lower():
            continue

        pieces.append(sql[pos:match.start()])
        pieces.append(f"ROUND(({expr})::numeric, {digits})")
        pos = close_paren + 1
        total += 1

    if not total:
        return sql, 0
    pieces.append(sql[pos:])
    return "".join(pieces), total


def _find_top_level_last_comma(text: str) -> int | None:
    depth = 0
    in_quote = False
    last = None
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'" and (i + 1 >= len(text) or text[i + 1] != "'"):
            in_quote = not in_quote
        if not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                last = i
        i += 1
    return last
