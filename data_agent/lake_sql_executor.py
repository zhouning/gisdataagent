"""Read-only DuckDB SQL execution over governed lake projections."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|COPY|"
    r"ATTACH|DETACH|INSTALL|LOAD|PRAGMA|CALL|EXPORT|IMPORT|VACUUM)\b",
    flags=re.IGNORECASE,
)
_FORBIDDEN_TABLE_FUNCTIONS = re.compile(
    r"\b(?:read_csv|read_csv_auto|read_json|read_json_auto|read_ndjson|read_parquet|"
    r"parquet_scan|read_blob|read_text|read_text_auto|read_binary|"
    r"arrow_scan|delta_scan|iceberg_scan|glob|sqlite_scan|postgres_scan|"
    r"mysql_scan|httpfs|http_get|http_post)\s*\(",
    flags=re.IGNORECASE,
)
_SPATIAL_CALL = re.compile(
    r"\bST_(?:Intersects|Within|Contains|Touches|Crosses|Overlaps)\s*\(",
    flags=re.IGNORECASE,
)


def execute_lake_sql(
    sql: str,
    candidate_tables: list[dict[str, Any]],
    *,
    max_rows: int = 100_000,
    display_rows: int = 100,
    timeout_seconds: float = 60.0,
) -> str:
    """Execute a bounded SELECT against registered GeoParquet views.

    File paths are supplied by governed semantic projections, never by SQL.
    This prevents generated SQL from reading arbitrary local files while still
    allowing DuckDB to scan Parquet directly without loading records into a
    database first.
    """

    started = time.perf_counter()
    try:
        sources = _lake_sources(candidate_tables)
        if not sources:
            return _result_error("lake_source_unavailable", started)

        safe_sql, dialect_corrections = normalize_lake_spatial_sql(
            sql,
            metric_crs=_metric_crs(candidate_tables),
            source_crs_by_alias=_source_crs_by_alias(sql, candidate_tables),
        )
        safe_sql, rewrite_note = _rewrite_correlated_spatial_exists(safe_sql, candidate_tables)
        if rewrite_note:
            dialect_corrections.append(rewrite_note)
        safe_sql, safety_error = _validate_read_only_sql(safe_sql, set(sources))
        if safety_error:
            return _result_error(f"lake_sql_safety:{safety_error}", started)

        import duckdb

        connection = duckdb.connect(":memory:")
        timer: threading.Timer | None = None
        try:
            _configure_connection(connection)
            spatial_required = bool(re.search(r"\bST_[A-Za-z0-9_]+\s*\(", safe_sql, re.I))
            spatial_loaded, spatial_error = False, ""
            if spatial_required:
                spatial_loaded, spatial_error = _load_spatial_extension(connection)
            if spatial_required and not spatial_loaded:
                return _result_error(
                    "duckdb_spatial_extension_unavailable:" + (spatial_error or "not_loaded"),
                    started,
                    engine="lake",
                    dialect="duckdb",
                    spatial_extension_loaded=False,
                )

            # Spatial must be loaded before scanning GeoParquet so DuckDB can
            # honor its geometry metadata instead of exposing WKB as a blob.
            for table_name, binding in sources.items():
                relation = connection.read_parquet(binding["projection_path"])
                relation.create_view(table_name, replace=True)

            max_rows = max(1, min(int(max_rows), 1_000_000))
            display_rows = max(1, min(int(display_rows), max_rows))
            bounded_sql = f"SELECT * FROM ({safe_sql}) AS _gda_lake_result LIMIT {max_rows + 1}"
            timer = threading.Timer(max(0.1, float(timeout_seconds)), connection.interrupt)
            timer.daemon = True
            timer.start()
            cursor = connection.execute(bounded_sql)
            columns = [item[0] for item in cursor.description or []]
            rows = cursor.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]
            data = [
                {column: _json_value(value) for column, value in zip(columns, row, strict=True)}
                for row in rows[:display_rows]
            ]
            payload = {
                "status": "ok",
                "engine": "lake",
                "dialect": "duckdb",
                "rows": len(rows),
                "columns": columns,
                "data": data,
                "truncated": truncated,
                "displayed_rows": len(data),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "spatial_extension_loaded": spatial_loaded,
                "sql_rewrites": dialect_corrections,
                "source_bindings": [
                    {
                        "table_name": table_name,
                        "projection_id": binding.get("projection_id"),
                        "projection_path": binding["projection_path"],
                    }
                    for table_name, binding in sources.items()
                ],
                "message": f"数据湖查询成功，返回 {len(rows)} 行"
                + (f"（仅显示前 {len(data)} 行）" if len(rows) > len(data) else ""),
            }
            return json.dumps(payload, ensure_ascii=False, default=str)
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
    except Exception as exc:
        return _result_error(str(exc), started, engine="lake", dialect="duckdb")


def lake_candidate_tables(candidate_tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates backed by an existing governed Parquet projection."""

    selected = []
    for table in candidate_tables or []:
        path = _projection_path(table)
        if path and Path(path).expanduser().is_file():
            selected.append(table)
    return selected


def _lake_sources(candidate_tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for table in lake_candidate_tables(candidate_tables):
        table_name = str(table.get("table_name") or "").strip()
        if not _SAFE_IDENTIFIER.fullmatch(table_name):
            continue
        path = str(Path(_projection_path(table)).expanduser().resolve())
        sources[table_name] = {
            "projection_path": path,
            "projection_id": table.get("projection_id"),
        }
    return sources


def _projection_path(table: dict[str, Any]) -> str:
    bindings = table.get("execution_bindings") or {}
    lake_binding = bindings.get("lake") if isinstance(bindings, dict) else None
    if isinstance(lake_binding, dict) and lake_binding.get("projection_path"):
        return str(lake_binding["projection_path"])
    return str(table.get("projection_path") or "")


def _metric_crs(candidate_tables: list[dict[str, Any]]) -> str:
    for table in candidate_tables or []:
        bindings = table.get("execution_bindings") or {}
        lake = bindings.get("lake") if isinstance(bindings, dict) else None
        value = (lake.get("metric_crs") if isinstance(lake, dict) else None) or table.get(
            "metric_crs"
        )
        if value:
            return _normalize_crs_name(value)
    return _normalize_crs_name(os.environ.get("GDA_LAKE_METRIC_CRS", "EPSG:3857"))


def _source_crs_by_alias(sql: str, candidate_tables: list[dict[str, Any]]) -> dict[str, str]:
    table_srid = {
        str(item.get("table_name")): _normalize_crs_name(item.get("srid"))
        for item in candidate_tables or []
        if item.get("table_name") and item.get("srid")
    }
    aliases: dict[str, str] = {}
    pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(sql or ""):
        srid = table_srid.get(match.group("table"))
        if not srid:
            continue
        alias = match.group("alias") or match.group("table")
        if str(alias).upper() in {
            "WHERE", "JOIN", "LEFT", "RIGHT", "FULL", "INNER", "CROSS",
            "ON", "GROUP", "ORDER", "HAVING", "LIMIT", "UNION",
        }:
            alias = match.group("table")
        aliases[alias] = srid
    # Propagate the physical source CRS through simple one-table subqueries so
    # an outer alias such as ``target.shape`` retains the CRS of the governed
    # projection selected inside ``(SELECT ... FROM cq_dltb) AS target``.
    subquery_pattern = re.compile(
        r"\(\s*SELECT\b.*?\bFROM\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)\b.*?\)\s+"
        r"(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\b",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in subquery_pattern.finditer(sql or ""):
        srid = table_srid.get(match.group("table"))
        if srid:
            aliases[match.group("alias")] = srid
    referenced_srids = {
        value
        for key, value in aliases.items()
        if key != "__default__"
    }
    if len(referenced_srids) == 1:
        aliases.setdefault("__default__", next(iter(referenced_srids)))
    return aliases


def _normalize_crs_name(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.isdigit():
        return f"EPSG:{text}"
    return text or "EPSG:3857"


def normalize_lake_spatial_sql(
    sql: str,
    *,
    metric_crs: str | None = None,
    source_crs_by_alias: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Normalize PostGIS spatial remnants into executable DuckDB SQL."""
    value = (sql or "").strip().rstrip(";").strip()
    if not value:
        return value, []
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(value, read="postgres")
        corrections: list[str] = []
        target_crs = _normalize_crs_name(
            metric_crs or os.environ.get("GDA_LAKE_METRIC_CRS", "EPSG:3857")
        )
        source_crs_by_alias = source_crs_by_alias or {}

        def is_geography_cast(node: Any) -> bool:
            return isinstance(node, exp.Cast) and str(node.to.this).upper().endswith("GEOGRAPHY")

        def expression_source_crs(node: Any) -> str | None:
            if isinstance(node, exp.Column):
                return source_crs_by_alias.get(node.table or "") or source_crs_by_alias.get(
                    "__default__"
                )
            if isinstance(node, exp.Anonymous) and node.name.lower() == "st_transform":
                args = node.expressions
                output_index = 2 if len(args) >= 3 else 1
                if (
                    len(args) > output_index
                    and isinstance(args[output_index], exp.Literal)
                    and args[output_index].is_string
                ):
                    return _normalize_crs_name(
                        str(args[output_index].this).replace("EPSG:", "")
                    )
            if isinstance(node, exp.Anonymous) and node.name.lower() in {
                "st_union", "st_union_agg", "st_envelope", "st_centroid",
                "st_intersection",
            }:
                args = node.expressions
                if args:
                    return expression_source_crs(args[0])
            return None

        def transform_expression(node: Any, target: str):
            # Collapse an existing two-argument transform before projecting to
            # the governed metric CRS.  Wrapping ``ST_Transform(geom, 3857)``
            # in another transform would interpret 3857 coordinates as the
            # source CRS and produce incorrect distances.
            if (
                isinstance(node, exp.Anonymous)
                and node.name.lower() == "st_transform"
                and len(node.expressions) >= 2
                and isinstance(node.expressions[1], exp.Literal)
            ):
                base = node.expressions[0].copy()
                source = expression_source_crs(base)
                existing_target = expression_source_crs(node)
                if existing_target == target:
                    return node.copy()
                if source:
                    return exp.Anonymous(
                        this="ST_Transform",
                        expressions=[
                            base,
                            exp.Literal.string(source),
                            exp.Literal.string(target),
                            exp.Boolean(this=True),
                        ],
                    )
            source = expression_source_crs(node)
            if source == target:
                return node.copy()
            args = [node.copy(), exp.Literal.string(target)]
            if source and source != target:
                args = [
                    node.copy(),
                    exp.Literal.string(source),
                    exp.Literal.string(target),
                    exp.Boolean(this=True),
                ]
            return exp.Anonymous(this="ST_Transform", expressions=args)

        def normalize_transform(node: Any):
            if not isinstance(node, exp.Anonymous) or node.name.lower() != "st_transform":
                return node
            args = node.expressions
            if len(args) == 2 and isinstance(args[1], exp.Literal):
                target = (
                    f"EPSG:{args[1].this}"
                    if not args[1].is_string
                    else _normalize_crs_name(args[1].this)
                )
                base = args[0].this if is_geography_cast(args[0]) else args[0]
                source = expression_source_crs(base)
                if not args[1].is_string:
                    corrections.append("duckdb_transform_crs_string")
                if (not args[1].is_string) or is_geography_cast(args[0]) or (
                    source and source != target
                ):
                    return transform_expression(base, target)
            if (
                len(args) == 3
                and isinstance(args[1], exp.Literal)
                and isinstance(args[2], exp.Literal)
            ):
                source = _normalize_crs_name(args[1].this)
                target = _normalize_crs_name(args[2].this)
                corrections.append("duckdb_transform_always_xy")
                return exp.Anonymous(
                    this="ST_Transform",
                    expressions=[
                        args[0].copy(),
                        exp.Literal.string(source),
                        exp.Literal.string(target),
                        exp.Boolean(this=True),
                    ],
                )
            return node

        def metric_geometry(node: Any):
            node = normalize_transform(node)
            return transform_expression(node, target_crs)

        tree = tree.transform(normalize_transform)

        def normalize_binary_spatial_crs(node: Any):
            if not isinstance(node, exp.Anonymous):
                return node
            if node.name.lower() not in {
                "st_intersects",
                "st_intersection",
                "st_contains",
                "st_within",
                "st_touches",
                "st_crosses",
                "st_overlaps",
            }:
                return node
            args = node.expressions
            if len(args) != 2:
                return node
            left_crs = expression_source_crs(args[0])
            right_crs = expression_source_crs(args[1])
            if not left_crs or not right_crs or left_crs == right_crs:
                return node
            corrections.append("duckdb_spatial_binary_crs")
            return exp.Anonymous(
                this=node.name,
                expressions=[transform_expression(args[0], right_crs), args[1].copy()],
            )

        tree = tree.transform(normalize_binary_spatial_crs)

        def normalize_spatial_aggregates(node: Any):
            if isinstance(node, exp.Anonymous):
                name = node.name.lower()
                args = node.expressions
                if name == "st_union" and len(args) == 1:
                    corrections.append("duckdb_spatial_union_aggregate")
                    return exp.Anonymous(
                        this="ST_Union_Agg",
                        expressions=[args[0].copy()],
                    )
                if name == "st_collect" and len(args) == 1:
                    # DuckDB Spatial exposes the aggregate union primitive,
                    # while PostGIS permits ST_Collect(geometry) in the
                    # generated SQL used by the benchmark. For envelope and
                    # extent calculations, the governed union is equivalent
                    # and avoids a runtime binder error on scalar geometry.
                    corrections.append("duckdb_spatial_collect_aggregate")
                    return exp.Anonymous(
                        this="ST_Union_Agg",
                        expressions=[args[0].copy()],
                    )
            return node

        tree = tree.transform(normalize_spatial_aggregates)

        def normalize_geography_functions(node: Any):
            if isinstance(node, exp.Anonymous):
                name = node.name.lower()
                args = node.expressions
                if name in {"st_length", "st_area", "st_perimeter"}:
                    if len(args) == 1 and is_geography_cast(args[0]):
                        corrections.append(f"duckdb_metric_{name[3:]}")
                        return exp.Anonymous(
                            this=node.name,
                            expressions=[metric_geometry(args[0].this)],
                        )
                if name == "st_dwithin" and len(args) >= 3:
                    # PostGIS accepts both geography casts and geometry
                    # arguments for ST_DWithin.  The latter are common in
                    # generated SQL after semantic normalization.  When the
                    # governed catalog supplies a source CRS for either
                    # operand, normalize both operands into the configured
                    # metric CRS so the radius is interpreted in metres.
                    left_crs = expression_source_crs(args[0])
                    right_crs = expression_source_crs(args[1])
                    has_known_crs = bool(left_crs or right_crs)
                    if (
                        is_geography_cast(args[0])
                        and is_geography_cast(args[1])
                    ) or has_known_crs:
                        left_geometry = (
                            args[0].this if is_geography_cast(args[0]) else args[0]
                        )
                        right_geometry = (
                            args[1].this if is_geography_cast(args[1]) else args[1]
                        )
                        corrections.append("duckdb_metric_dwithin")
                        return exp.Anonymous(
                            this=node.name,
                            expressions=[
                                metric_geometry(left_geometry),
                                metric_geometry(right_geometry),
                                args[2].copy(),
                            ],
                        )
            if isinstance(node, exp.StDistance):
                if is_geography_cast(node.this) and is_geography_cast(node.expression):
                    corrections.append("duckdb_metric_distance")
                    return exp.Anonymous(
                        this="ST_Distance",
                        expressions=[
                            metric_geometry(node.this.this),
                            metric_geometry(node.expression.this),
                        ],
                    )
                left_crs = expression_source_crs(node.this)
                right_crs = expression_source_crs(node.expression)
                if (left_crs or right_crs) and (
                    left_crs != target_crs or right_crs != target_crs
                ):
                    corrections.append("duckdb_metric_distance")
                    return exp.Anonymous(
                        this="ST_Distance",
                        expressions=[
                            metric_geometry(node.this),
                            metric_geometry(node.expression),
                        ],
                    )
            if isinstance(node, exp.Distance):
                corrections.append("duckdb_knn_distance_operator")
                return exp.Anonymous(
                    this="ST_Distance",
                    expressions=[
                        metric_geometry(node.this),
                        metric_geometry(node.expression),
                    ],
                )
            return node

        tree = tree.transform(normalize_geography_functions)
        # The metric rewrite can wrap an inner ST_Transform node; normalize
        # that newly exposed child in a second pass.
        tree = tree.transform(normalize_transform)

        def remove_geography_cast(node: Any):
            if is_geography_cast(node):
                corrections.append("duckdb_remove_geography_cast")
                return node.this.copy()
            return node

        tree = tree.transform(remove_geography_cast)
        return tree.sql(dialect="duckdb"), list(dict.fromkeys(corrections))
    except Exception:
        return value, []


def _validate_read_only_sql(sql: str, allowed_tables: set[str]) -> tuple[str, str]:
    value = (sql or "").strip().rstrip(";").strip()
    if not value:
        return value, "empty_sql"
    if _has_statement_separator(value):
        return value, "multiple_statements"
    if not re.match(r"^(?:SELECT|WITH)\b", value, flags=re.IGNORECASE):
        return value, "select_only"
    if _FORBIDDEN_SQL.search(value):
        return value, "forbidden_operation"
    if _FORBIDDEN_TABLE_FUNCTIONS.search(value):
        return value, "external_table_function"

    from .runtime_guards import is_safe_sql

    ok, reason = is_safe_sql(value, allowed_tables)
    return (value, "") if ok else (value, reason)


def _has_statement_separator(value: str) -> bool:
    """Detect semicolons outside SQL string literals."""
    in_single = False
    in_double = False
    index = 0
    while index < len(value or ""):
        char = value[index]
        if char == "'" and not in_double:
            if in_single and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ";" and not in_single and not in_double:
            return True
        index += 1
    return False


def _matching_paren(value: str, opening: int) -> int | None:
    depth = 0
    quote = ""
    for index in range(opening, len(value)):
        char = value[index]
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _remove_spatial_predicate(conditions: str, start: int, end: int) -> str:
    left = conditions[:start].strip()
    right = conditions[end:].strip()
    if left.upper().endswith("AND"):
        left = left[:-3].rstrip()
    if right.upper().startswith("AND"):
        right = right[3:].lstrip()
    return " AND ".join(part for part in (left, right) if part)


def _top_level_keyword_positions(value: str, keyword: str) -> list[int]:
    """Return keyword offsets outside parentheses and SQL string literals."""
    positions: list[int] = []
    depth = 0
    quote = ""
    index = 0
    wanted = keyword.upper()
    while index < len(value):
        char = value[index]
        if quote:
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0 and value[index : index + len(wanted)].upper() == wanted:
            before = value[index - 1] if index else " "
            after_index = index + len(wanted)
            after = value[after_index] if after_index < len(value) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                positions.append(index)
                index = after_index
                continue
        index += 1
    return positions


def _rewrite_correlated_spatial_exists(
    sql: str,
    governed_sources: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Turn a common spatial EXISTS shape into DuckDB's SPATIAL_JOIN shape.

    DuckDB's optimizer recognizes ``JOIN ... ON ST_Intersects`` but not a
    correlated ``EXISTS`` predicate, which otherwise becomes a huge cross
    product over two GeoParquet scans.  This narrowly-scoped rewrite preserves
    the inner filters and leaves unsupported SQL untouched for the safety gate.
    """
    value = (sql or "").strip().rstrip(";").strip()
    exists_match = re.search(r"\bEXISTS\s*\(", value, flags=re.IGNORECASE)
    if not exists_match:
        return value, ""
    opening = value.find("(", exists_match.start())
    closing = _matching_paren(value, opening)
    if closing is None:
        return value, ""
    inner = value[opening + 1 : closing].strip()
    from_match = re.match(
        r"SELECT\s+1\s+FROM\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s+WHERE\s+",
        inner,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not from_match:
        return value, ""
    spatial_match = _SPATIAL_CALL.search(inner, from_match.end())
    if not spatial_match:
        return value, ""
    spatial_opening = inner.find("(", spatial_match.start())
    spatial_closing = _matching_paren(inner, spatial_opening)
    if spatial_closing is None:
        return value, ""
    spatial_call = inner[spatial_match.start() : spatial_closing + 1]
    conditions = inner[from_match.end() :]
    condition_start = spatial_match.start() - from_match.end()
    condition_end = spatial_closing + 1 - from_match.end()
    remaining_conditions = _remove_spatial_predicate(conditions, condition_start, condition_end)

    before_exists = value[: exists_match.start()]
    after_exists = value[closing + 1 :]
    scope_depth = _parenthesis_depth_at(value, exists_match.start())
    scoped_from = _keyword_positions_at_depth(before_exists, "FROM", scope_depth)
    if not scoped_from:
        return value, ""
    outer_from = re.match(
        r"FROM\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
        r"[A-Za-z_][A-Za-z0-9_]*\s+(?:AS\s+)?[A-Za-z_][A-Za-z0-9_]*",
        before_exists[scoped_from[-1] :],
        flags=re.IGNORECASE,
    )
    if not outer_from:
        return value, ""
    outer_end = scoped_from[-1] + outer_from.end()
    deduplicated = _rewrite_correlated_spatial_exists_as_deduplicated_join(
        value,
        before_exists,
        after_exists,
        spatial_call,
        remaining_conditions,
        outer_from,
        outer_end,
        from_match,
        governed_sources or [],
        scope_depth,
    )
    if deduplicated is not None:
        return deduplicated, "correlated_spatial_exists_to_deduplicated_join"
    joined_prefix = before_exists[:outer_end]
    joined_suffix = before_exists[outer_end:]
    # The EXISTS expression is replaced by its non-spatial filters; the
    # spatial predicate becomes the explicit JOIN condition.
    replacement = remaining_conditions or "TRUE"
    rewritten = (
        joined_prefix
        + f" JOIN {from_match.group('table')} {from_match.group('alias')} ON {spatial_call}"
        + joined_suffix
        + replacement
        + after_exists
    )
    return rewritten, "correlated_spatial_exists_to_explicit_join"


def _rewrite_correlated_spatial_exists_as_deduplicated_join(
    value: str,
    before_exists: str,
    after_exists: str,
    spatial_call: str,
    remaining_conditions: str,
    outer_from: re.Match[str],
    outer_end: int,
    inner_from: re.Match[str],
    governed_sources: list[dict[str, Any]],
    scope_depth: int,
) -> str | None:
    """Preserve EXISTS cardinality while retaining DuckDB's spatial join path.

    A plain JOIN multiplies a parcel once per intersecting road, which changes
    ``SUM(parcel_area)``.  For governed sources with an identifier, materialize
    one row per left entity before applying the outer aggregate.  This is much
    faster than a correlated EXISTS/SEMI JOIN on GeoParquet and is equivalent
    for existential spatial predicates.
    """
    select_positions = _keyword_positions_at_depth(before_exists, "SELECT", scope_depth)
    if not select_positions:
        return None
    select_start = select_positions[-1]
    query_prefix = before_exists[:select_start]
    select_fragment = before_exists[select_start:]
    select_match = re.match(
        r"^\s*SELECT\s+(?P<select>.+?)\s+FROM\s+",
        select_fragment,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not select_match:
        return None
    select_expr = select_match.group("select").strip()
    outer_table = outer_from.group(0).split()[1]
    outer_alias_match = re.search(
        r"\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*$",
        outer_from.group(0),
        flags=re.IGNORECASE,
    )
    if not outer_alias_match:
        return None
    outer_alias = outer_alias_match.group("alias")
    source_name = outer_table.split(".")[-1].strip('"')
    source = next(
        (
            item
            for item in governed_sources
            if str(item.get("table_name") or "").split(".")[-1].casefold()
            == source_name.casefold()
        ),
        None,
    )
    fields = (source or {}).get("fields") or {}
    identifier = ""
    for field_name, field in fields.items():
        if isinstance(field, dict) and (field.get("value_semantics") or {}).get("identifier") is True:
            identifier = str(field_name)
            break
    if not identifier:
        for candidate in ("BSM", "bsm", "ID", "id", "objectid", "fid"):
            if candidate in fields:
                identifier = candidate
                break
    if identifier:
        identifier_ref = f'{outer_alias}."{identifier}"'
    else:
        geometry_ref = re.search(
            rf"\b{re.escape(outer_alias)}\.(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)",
            spatial_call,
            flags=re.IGNORECASE,
        )
        if not geometry_ref:
            return None
        identifier_ref = geometry_ref.group(0)

    where_positions = _keyword_positions_at_depth(before_exists, "WHERE", scope_depth)
    outer_where = ""
    if where_positions:
        outer_where = before_exists[where_positions[-1] + len("WHERE") :].strip()
        outer_where = re.sub(r"(?:AND|OR)\s*$", "", outer_where, flags=re.IGNORECASE).strip()
    inner_where = remaining_conditions.strip()
    if inner_where:
        inner_where = re.sub(r"^\s*(?:AND|OR)\s+", "", inner_where, flags=re.IGNORECASE).strip()
    predicates = [part for part in (outer_where, inner_where) if part]
    where_clause = f" WHERE {' AND '.join(predicates)}" if predicates else ""
    right_table = inner_from.group("table")
    right_alias = inner_from.group("alias")
    join_sql = (
        f"FROM {outer_table} AS {outer_alias} JOIN {right_table} AS {right_alias} "
        f"ON {spatial_call}{where_clause}"
    )

    aggregate = re.fullmatch(
        r"SUM\s*\(\s*(?P<metric>.+)\s*\)(?P<alias>\s+AS\s+.+)?",
        select_expr,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if aggregate:
        metric = aggregate.group("metric").strip()
        if not re.search(rf"\b{re.escape(outer_alias)}\.", metric, flags=re.IGNORECASE):
            return None
        if re.search(rf"\b{re.escape(right_alias)}\.", metric, flags=re.IGNORECASE):
            return None
        alias = aggregate.group("alias") or ""
        inner_sql = (
            f"SELECT {identifier_ref} AS _gda_entity_id, "
            f"{metric} AS _gda_metric {join_sql} "
            f"GROUP BY {identifier_ref}, {metric}"
        )
        return f"{query_prefix}SELECT SUM(_gda_selected._gda_metric){alias} FROM ({inner_sql}) AS _gda_selected{after_exists}"

    if re.fullmatch(r"COUNT\s*\(\s*\*\s*\)(?:\s+AS\s+.+)?", select_expr, flags=re.IGNORECASE):
        alias_match = re.search(r"\s+AS\s+(.+)$", select_expr, flags=re.IGNORECASE)
        alias = f" AS {alias_match.group(1).strip()}" if alias_match else ""
        inner_sql = (
            f"SELECT DISTINCT {identifier_ref} AS _gda_entity_id "
            f"{join_sql}"
        )
        return f"{query_prefix}SELECT COUNT(*){alias} FROM ({inner_sql}) AS _gda_selected{after_exists}"
    projection = re.sub(r"^DISTINCT\s+", "", select_expr, flags=re.IGNORECASE).strip()
    if (
        projection
        and re.search(rf"\b{re.escape(outer_alias)}\.", projection, flags=re.IGNORECASE)
        and not re.search(r"\b(?:SUM|COUNT|AVG|MIN|MAX)\s*\(", projection, flags=re.IGNORECASE)
    ):
        return f"{query_prefix}SELECT DISTINCT {projection} {join_sql}{after_exists}"
    return None


def _parenthesis_depth_at(sql: str, end: int) -> int:
    depth = 0
    quote = ""
    index = 0
    limit = min(max(0, int(end)), len(sql or ""))
    while index < limit:
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < limit and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        index += 1
    return depth


def _keyword_positions_at_depth(sql: str, keyword: str, target_depth: int) -> list[int]:
    value = sql or ""
    positions: list[int] = []
    depth = 0
    quote = ""
    index = 0
    wanted = keyword.upper()
    while index < len(value):
        char = value[index]
        if quote:
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == target_depth and value[index : index + len(wanted)].upper() == wanted:
            before = value[index - 1] if index else " "
            after_index = index + len(wanted)
            after = value[after_index] if after_index < len(value) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                positions.append(index)
                index = after_index
                continue
        index += 1
    return positions


def _configure_connection(connection: Any) -> None:
    memory_limit = os.environ.get("GDA_DUCKDB_MEMORY_LIMIT", "2GB").strip() or "2GB"
    threads = max(1, min(int(os.environ.get("GDA_DUCKDB_THREADS", "4")), 32))
    escaped_limit = memory_limit.replace("'", "''")
    connection.execute(f"SET memory_limit='{escaped_limit}'")
    connection.execute(f"SET threads={threads}")


def _load_spatial_extension(connection: Any) -> tuple[bool, str]:
    configured_path = os.environ.get("GDA_DUCKDB_SPATIAL_EXTENSION_PATH", "").strip()
    try:
        if configured_path:
            path = str(Path(configured_path).expanduser().resolve()).replace("'", "''")
            connection.execute(f"LOAD '{path}'")
        else:
            connection.execute("LOAD spatial")
        return True, ""
    except Exception as exc:
        return False, str(exc).replace("\n", " ")[:500]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary:{len(value)} bytes>"
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _result_error(error: str, started: float, **extra: Any) -> str:
    payload = {
        "status": "error",
        "error": error,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, default=str)
