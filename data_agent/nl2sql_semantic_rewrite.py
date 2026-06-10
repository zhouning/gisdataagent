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
    tables = _build_tables(context)
    if not rewritten or not tables:
        rewritten2, n = _rewrite_round_numeric_cast(rewritten)
        return rewritten2, ["semantic_round_numeric_cast"] if n else []

    rewritten, changed = _normalize_versioned_table_refs(rewritten, tables)
    if changed:
        corrections.append("semantic_table_normalized")

    rewritten, changed = _prefer_versioned_candidate_refs(question, rewritten, tables)
    if changed:
        corrections.append("semantic_table_normalized")

    rewritten, changed = _collapse_duplicate_union(rewritten)
    if changed:
        corrections.append("semantic_duplicate_union")

    alias_map = _table_alias_map(rewritten, tables)

    rewritten, changed = _rewrite_column_aliases(rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_column_alias")
        alias_map = _table_alias_map(rewritten, tables)

    refused, changed = _refuse_unknown_columns(rewritten, alias_map)
    if changed:
        return refused, corrections + ["semantic_unknown_column_refusal"]

    rewritten, changed = _rewrite_value_groups(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_value_group")

    rewritten, changed = _rewrite_literal_column_overrides(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_literal_column_override")

    rewritten, changed = _rewrite_enum_filters(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_enum_filter")

    rewritten, changed = _rewrite_enum_case_display_to_raw_code(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_enum_display")

    rewritten, changed = _rewrite_enum_comparison_projection_and_filters(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_enum_comparison")

    rewritten, changed = _rewrite_unrequested_positive_aggregate_filters(question, rewritten)
    if changed:
        corrections.append("semantic_unrequested_positive_filter")

    rewritten, changed = _rewrite_unit_thresholds(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_unit_threshold")

    rewritten, changed = _rewrite_precomputed_area(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_area_metric")

    rewritten, changed = _qualify_unqualified_area_geometry(rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_area_geometry_qualified")

    rewritten, changed = _rewrite_st_union_geography_area(rewritten)
    if changed:
        corrections.append("semantic_st_union_geography")

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

    rewritten, changed = _rewrite_existential_spatial_join_aggregate(question, rewritten)
    if changed:
        corrections.append("semantic_existential_spatial_join")

    rewritten, changed = _rewrite_unrequested_unreferenced_spatial_joins(question, rewritten)
    if changed:
        corrections.append("semantic_unrequested_spatial_join_pruned")

    rewritten, changed = _rewrite_requested_spatial_predicate(question, rewritten)
    if changed:
        corrections.append("semantic_requested_spatial_predicate")

    rewritten, changed = _rewrite_distinct_name_not_null(question, rewritten, tables, alias_map)
    if changed:
        corrections.append("semantic_distinct_not_null")

    rewritten, changed = _rewrite_left_join_for_grouped_count(question, rewritten)
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


def _version_suffix_year(table_name: str) -> int:
    m = re.search(r"_(?P<year>(?:19|20)\d{2})$", table_name or "")
    return int(m.group("year")) if m else 0


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
        r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?",
        flags=re.IGNORECASE,
    )
    m = pattern.search(sql or "")
    if not m:
        return None
    alias = m.group("alias")
    if not alias or alias.upper() in {"ON", "WHERE", "JOIN", "GROUP", "ORDER", "LIMIT"}:
        return None
    return alias


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
    for table in tables:
        if table.table_name not in referenced_table_names:
            continue
        for col in table.columns:
            for token in col.ref_tokens:
                key = _strip_identifier_quotes(token).lower()
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
        rewritten, n = _replace_column_reference(
            rewritten,
            None,
            key,
            col.quoted_ref,
            unqualified=True,
        )
        changed = changed or bool(n)

    return rewritten, changed


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
    return rewritten, changed


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


def _rewrite_spatial_srid_transforms(
    sql: str,
    alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]],
) -> tuple[str, bool]:
    ref_re = r"[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)"
    pattern = re.compile(
        rf"ST_INTERSECTS\s*\(\s*(?P<a>{ref_re})\s*,\s*(?P<b>{ref_re})\s*\)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        a = match.group("a")
        b = match.group("b")
        a_col = _lookup_column_ref(a, alias_map)
        b_col = _lookup_column_ref(b, alias_map)
        if not a_col or not b_col or not a_col.is_geometry or not b_col.is_geometry:
            return match.group(0)
        if not a_col.srid or not b_col.srid or a_col.srid == b_col.srid:
            return match.group(0)
        if a_col.srid != b_col.srid:
            return f"ST_Intersects(ST_Transform({a}, {b_col.srid}), {b})"
        return match.group(0)

    rewritten, n = pattern.subn(repl, sql)
    return rewritten, bool(n and rewritten != sql)


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
    return rewritten, bool(n and rewritten != sql)


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
    distance_projection = _find_distance_projection(sql)
    if not distance_projection:
        return sql, False
    distance_alias, left_geom, right_geom = distance_projection
    left_ref = _geometry_ref_for_knn(left_geom)
    right_ref = _geometry_ref_for_knn(right_geom)
    if not left_ref or not right_ref:
        return sql, False

    alias_re = re.escape(distance_alias.strip('"'))
    pattern = re.compile(
        rf"\bORDER\s+BY\s+\"?{alias_re}\"?\s*(?:ASC|DESC)?\s*(?P<limit>\bLIMIT\s+\d+\b)",
        flags=re.IGNORECASE,
    )
    replacement = f"ORDER BY {left_ref} <-> {right_ref} \\g<limit>"
    rewritten, n = pattern.subn(replacement, sql or "", count=1)
    return rewritten, bool(n and rewritten != (sql or ""))


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
            r"\s+AS\s+(?P<alias>\"?[A-Za-z_][A-Za-z0-9_]*\"?)",
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
        r"CAST\s*\(\s*(?P<inner>[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))\s+AS\s+GEOGRAPHY\s*\)",
        value,
        flags=re.IGNORECASE,
    )
    if cast_match:
        return cast_match.group("inner")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)", value):
        return value
    return ""


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
        return sql, False
    ref = m.group("ref")
    col = _lookup_column_ref(ref, alias_map)
    if not col:
        return sql, False
    name_tokens = {col.column_name.lower(), _strip_identifier_quotes(col.quoted_ref).lower()}
    name_tokens.update(a.lower() for a in col.aliases)
    if not ({"name", "名称", "名字"} & name_tokens):
        return sql, False
    where = m.group("where").strip()
    if re.search(rf"{re.escape(ref)}\s+IS\s+NOT\s+NULL", where, re.IGNORECASE):
        return sql, False
    rewritten = (
        f"SELECT DISTINCT {ref} FROM {m.group('rest')} "
        f"WHERE {where} AND {ref} IS NOT NULL{m.group('limit') or ''}"
    )
    return rewritten, True


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
    if arg != "*" and not re.match(rf"{re.escape(left_alias)}\.", arg, flags=re.IGNORECASE):
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


def _normalize_table_ref(table_ref: str) -> str:
    parts = [part.strip() for part in (table_ref or "").split(".")]
    return ".".join(_strip_identifier_quotes(part) for part in parts if part)


def _first_geometry(table: TableInfo) -> ColumnInfo | None:
    geoms = table.geometry_columns()
    return geoms[0] if geoms else None


def _lookup_column_ref(ref: str, alias_map: dict[str, tuple[TableInfo, ColumnInfo | None]]) -> ColumnInfo | None:
    if "." not in ref:
        return None
    qualifier, col_name = ref.split(".", 1)
    table_entry = alias_map.get(qualifier)
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
    clause = re.search(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.IGNORECASE)
    if clause:
        head = sql[:clause.start()].rstrip()
        tail = sql[clause.start():]
    else:
        head = sql.rstrip()
        tail = ""
    if re.search(r"\bWHERE\b", head, re.IGNORECASE):
        return f"{head} AND {predicate} {tail}".rstrip()
    return f"{head} WHERE {predicate} {tail}".rstrip()


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
