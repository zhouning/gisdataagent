"""Database connector — query external MySQL/PostgreSQL/SQLite databases (v15.0).

Users register external databases as virtual data sources. Queries execute
in a read-only, connection-pooled context with timeout enforcement.
"""

import logging
import math
import re
import warnings

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SAWarning

from . import BaseConnector, ConnectorRegistry

logger = logging.getLogger(__name__)

_READ_QUERY_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLE_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$"
)
_BLOCKED_SQL_RE = re.compile(
    r"\b(for\s+(update|share)|lock\s+table|pg_sleep|pg_terminate_backend|"
    r"pg_cancel_backend|pg_advisory_lock|pg_try_advisory_lock|set_config|"
    r"dblink_exec|lo_import|lo_export)\b",
    re.IGNORECASE,
)
_DEFAULT_DISCOVERY_LIMIT = 5000
_DEFAULT_STATEMENT_TIMEOUT_MS = 15_000
_DEFAULT_LOCK_TIMEOUT_MS = 2_000
_DEFAULT_MAX_ROWS = 1000
_ABSOLUTE_MAX_ROWS = 5000


def _connection_url(endpoint_url: str, auth_config: dict) -> str:
    """Apply runtime credentials without string interpolation or persistence."""
    if (auth_config or {}).get("type") != "basic":
        return endpoint_url
    username = auth_config.get("username")
    password = auth_config.get("password")
    url = make_url(endpoint_url)
    return url.set(
        username=str(username) if username is not None else url.username,
        password=str(password) if password is not None else url.password,
    ).render_as_string(hide_password=False)


def _read_only_sql(sql: str) -> str:
    statement = sql.strip()
    if not _READ_QUERY_RE.match(statement) or ";" in statement.rstrip(";"):
        raise ValueError("database connector only accepts one read-only SELECT query")
    return statement


def _allowed_schemas(query_config: dict | None) -> tuple[str, ...]:
    raw = (query_config or {}).get("allowed_schemas") or ()
    if isinstance(raw, str):
        raw = [raw]
    schemas = tuple(dict.fromkeys(str(value).strip() for value in raw if str(value).strip()))
    if any(not _IDENTIFIER_RE.fullmatch(schema) for schema in schemas):
        raise ValueError("allowed_schemas contains an invalid schema identifier")
    return schemas


def _bounded_int(
    value,
    *,
    default: int,
    minimum: int,
    maximum: int,
    field: str,
) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _runtime_limits(query_config: dict | None) -> tuple[int, int, int]:
    config = query_config or {}
    statement_timeout_ms = _bounded_int(
        config.get("statement_timeout_ms"),
        default=_DEFAULT_STATEMENT_TIMEOUT_MS,
        minimum=1000,
        maximum=120_000,
        field="statement_timeout_ms",
    )
    lock_timeout_ms = _bounded_int(
        config.get("lock_timeout_ms"),
        default=_DEFAULT_LOCK_TIMEOUT_MS,
        minimum=100,
        maximum=30_000,
        field="lock_timeout_ms",
    )
    max_rows = _bounded_int(
        config.get("max_rows"),
        default=_DEFAULT_MAX_ROWS,
        minimum=1,
        maximum=_ABSOLUTE_MAX_ROWS,
        field="max_rows",
    )
    return statement_timeout_ms, lock_timeout_ms, max_rows


def _runtime_query_request(
    query_config: dict | None,
    extra_params: dict | None,
) -> tuple[str, str, str]:
    """Resolve per-request SQL without allowing governance policy overrides."""
    config = query_config or {}
    request = extra_params or {}
    sql = str(request.get("sql") or config.get("sql") or "").strip()
    table = str(config.get("table") or "").strip()
    geom_column = str(
        request.get("geom_column") or config.get("geom_column") or ""
    ).strip()
    return sql, table, geom_column


def _runtime_query_parameters(extra_params: dict | None) -> dict[str, str | int | float | bool]:
    """Read compiler-produced bind values without accepting arbitrary objects.

    The virtual-source request remains responsible for selecting a statement,
    while this narrow channel is reserved for named parameters emitted by a
    deterministic compiler.  It deliberately rejects nested structures so a
    caller cannot smuggle an adapter-specific expression through the query
    interface.
    """

    request = extra_params or {}
    raw = request.get("sql_params") or {}
    if not isinstance(raw, dict):
        raise ValueError("database query parameters must be an object")
    values: dict[str, str | int | float | bool] = {}
    for name, value in raw.items():
        key = str(name)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
            raise ValueError("database query parameter name is invalid")
        if isinstance(value, bool):
            values[key] = value
        elif isinstance(value, int):
            values[key] = value
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("database query parameter float must be finite")
            values[key] = value
        elif isinstance(value, str):
            if len(value) > 512 or "\x00" in value:
                raise ValueError("database query parameter string is invalid")
            values[key] = value
        else:
            raise ValueError("database query parameter type is unsupported")
    return values


def _connect_args(
    endpoint_url: str,
    *,
    connect_timeout: int,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
) -> dict:
    backend = make_url(endpoint_url).get_backend_name()
    if backend == "postgresql":
        options = " ".join(
            (
                "-c default_transaction_read_only=on",
                f"-c statement_timeout={statement_timeout_ms}",
                f"-c lock_timeout={lock_timeout_ms}",
                f"-c idle_in_transaction_session_timeout={statement_timeout_ms}",
            )
        )
        return {"connect_timeout": connect_timeout, "options": options}
    if backend == "sqlite":
        return {"timeout": connect_timeout}
    return {"connect_timeout": connect_timeout}


def _set_transaction_read_only(
    conn,
    *,
    statement_timeout_ms: int = _DEFAULT_STATEMENT_TIMEOUT_MS,
    lock_timeout_ms: int = _DEFAULT_LOCK_TIMEOUT_MS,
) -> None:
    if conn.dialect.name == "postgresql":
        from sqlalchemy import text

        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {statement_timeout_ms}"))
        conn.execute(text(f"SET LOCAL lock_timeout = {lock_timeout_ms}"))


def _quote_table(table: str) -> str:
    if not _TABLE_RE.fullmatch(table):
        raise ValueError("invalid table identifier")
    return ".".join(f'"{part}"' for part in table.split("."))


def _governed_read_query(sql: str, allowed_schemas: tuple[str, ...], row_limit: int) -> str:
    """Validate one read query, enforce physical schema scope, and cap rows."""
    statement = _read_only_sql(sql).rstrip(";").strip()
    if _BLOCKED_SQL_RE.search(statement):
        raise ValueError("database query contains a blocked read-side-effect operation")

    try:
        from sqlglot import exp, parse_one

        expression = parse_one(statement, read="postgres")
    except Exception as exc:
        raise ValueError("database query could not be parsed safely") from exc

    blocked_nodes = (
        exp.Alter,
        exp.Command,
        exp.Create,
        exp.Delete,
        exp.Drop,
        exp.Insert,
        exp.Merge,
        exp.Update,
    )
    if any(expression.find(node) is not None for node in blocked_nodes):
        raise ValueError("database connector only accepts read-only SELECT queries")

    cte_names = {
        str(cte.alias_or_name).casefold()
        for cte in expression.find_all(exp.CTE)
        if cte.alias_or_name
    }
    physical_tables = []
    for table in expression.find_all(exp.Table):
        # sqlglot represents ``CROSS JOIN LATERAL
        # jsonb_array_elements(...) AS item`` as a table-like node.  It is a
        # governed PostgreSQL table function, not a physical relation, so it
        # must not be subjected to the schema-qualification check below. The
        # semantic/runtime guards validate its source field and JSON contract
        # separately before this connector is called.
        table_source = getattr(table, "this", None)
        if isinstance(table_source, exp.Anonymous) and str(
            getattr(table_source, "name", "") or ""
        ).casefold() == "jsonb_array_elements":
            continue
        table_name = str(table.name or "")
        schema_name = str(table.db or "")
        if not schema_name and table_name.casefold() in cte_names:
            continue
        if table.catalog:
            raise ValueError("catalog-qualified database references are not allowed")
        if not schema_name:
            raise ValueError("database queries must schema-qualify every physical table")
        if allowed_schemas and schema_name not in allowed_schemas:
            raise ValueError(f"database query references unauthorized schema: {schema_name}")
        physical_tables.append((schema_name, table_name))
    if not physical_tables:
        raise ValueError("database query must reference at least one governed table")

    return f"SELECT * FROM ({statement}) AS gda_bounded_query LIMIT {row_limit}"


def validate_database_read_query(
    sql: str,
    query_config: dict | None,
    *,
    limit: int = 1000,
) -> str:
    """Apply the same schema, AST, side-effect, and row guards used at execution."""
    allowed_schemas = _allowed_schemas(query_config)
    _, _, configured_max_rows = _runtime_limits(query_config)
    row_limit = min(max(int(limit), 1), configured_max_rows, _ABSOLUTE_MAX_ROWS)
    return _governed_read_query(sql, allowed_schemas, row_limit)


def _safe_inspector_call(callback, default):
    try:
        return callback()
    except Exception as exc:
        logger.debug("Database metadata inspection skipped: %s", exc)
        return default


def _database_capabilities(
    endpoint_url: str,
    auth_config: dict,
    *,
    target_table: str | None = None,
    allowed_schemas: tuple[str, ...] = (),
    discovery_limit: int = _DEFAULT_DISCOVERY_LIMIT,
    statement_timeout_ms: int = _DEFAULT_STATEMENT_TIMEOUT_MS,
    lock_timeout_ms: int = _DEFAULT_LOCK_TIMEOUT_MS,
) -> dict:
    from sqlalchemy import create_engine, inspect, text

    engine = None
    try:
        if target_table and not _TABLE_RE.fullmatch(target_table):
            return {"error": "invalid table identifier", "layers": []}
        if not target_table and not allowed_schemas:
            return {
                "error": "database discovery requires an allowed_schemas whitelist",
                "layers": [],
            }
        if any(not _IDENTIFIER_RE.fullmatch(schema) for schema in allowed_schemas):
            return {"error": "invalid allowed_schemas identifier", "layers": []}
        discovery_limit = _bounded_int(
            discovery_limit,
            default=_DEFAULT_DISCOVERY_LIMIT,
            minimum=1,
            maximum=20_000,
            field="discovery_limit",
        )
        engine = create_engine(
            _connection_url(endpoint_url, auth_config),
            pool_size=1,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args=_connect_args(
                endpoint_url,
                connect_timeout=5,
                statement_timeout_ms=statement_timeout_ms,
                lock_timeout_ms=lock_timeout_ms,
            ),
        )
        provider_version = "unknown"
        spatial_version = "not_applicable"
        geometry_types: dict[tuple[str, str, str], str] = {}
        estimated_rows: dict[tuple[str, str], int] = {}
        database_name = make_url(endpoint_url).database or "unknown"
        schema_access: dict[str, dict[str, bool]] = {}
        with engine.begin() as conn:
            _set_transaction_read_only(
                conn,
                statement_timeout_ms=statement_timeout_ms,
                lock_timeout_ms=lock_timeout_ms,
            )
            if conn.dialect.name == "postgresql":
                database_name = str(conn.execute(text("SELECT current_database()")).scalar())
                provider_version = str(
                    conn.execute(text("SELECT current_setting('server_version')")).scalar()
                )
                spatial_version = str(
                    conn.execute(
                        text(
                            "SELECT COALESCE(MAX(extversion), 'not_installed') "
                            "FROM pg_extension WHERE extname = 'postgis'"
                        )
                    ).scalar()
                )
                scoped_schemas = allowed_schemas
                if target_table:
                    scoped_schemas = (
                        target_table.split(".", 1)[0]
                        if "." in target_table
                        else "public",
                    )
                for schema in scoped_schemas:
                    row = conn.execute(
                        text(
                            "SELECT to_regnamespace(:schema)::text AS schema_name, "
                            "CASE WHEN to_regnamespace(:schema) IS NULL THEN FALSE "
                            "ELSE has_schema_privilege(current_user, :schema, 'USAGE') END "
                            "AS has_usage"
                        ),
                        {"schema": schema},
                    ).one()
                    schema_access[schema] = {
                        "exists": row[0] is not None,
                        "has_usage": bool(row[1]),
                    }
                if spatial_version != "not_installed":
                    geometry_schemas = allowed_schemas
                    if target_table:
                        geometry_schemas = (
                            target_table.split(".", 1)[0]
                            if "." in target_table
                            else "public",
                        )
                    for schema in geometry_schemas:
                        for row in conn.execute(
                            text(
                                "SELECT f_table_schema, f_table_name, "
                                "f_geometry_column, type, srid FROM geometry_columns "
                                "WHERE f_table_schema = :schema"
                            ),
                            {"schema": schema},
                        ):
                            geometry_types[(str(row[0]), str(row[1]), str(row[2]))] = (
                                f"geometry({row[3]},EPSG:{row[4]})"
                            )
                estimate_schemas = allowed_schemas
                if target_table:
                    estimate_schemas = (
                        target_table.split(".", 1)[0]
                        if "." in target_table
                        else "public",
                    )
                for schema in estimate_schemas:
                    for row in conn.execute(
                        text(
                            "SELECT n.nspname, c.relname, "
                            "GREATEST(c.reltuples::bigint, 0) "
                            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = :schema AND c.relkind IN ('r', 'p', 'v', 'm')"
                        ),
                        {"schema": schema},
                    ):
                        estimated_rows[(str(row[0]), str(row[1]))] = int(row[2])
            elif conn.dialect.server_version_info:
                provider_version = ".".join(str(part) for part in conn.dialect.server_version_info)

        inspector = inspect(engine)
        if target_table:
            if "." in target_table:
                schema, table = target_table.split(".", 1)
            else:
                schema, table = "public", target_table
            if allowed_schemas and schema not in allowed_schemas:
                return {
                    "error": f"governed source table is outside allowed_schemas: {target_table}",
                    "layers": [],
                }
            if not inspector.has_table(table, schema=schema):
                return {
                    "error": f"governed source table was not discovered: {target_table}",
                    "layers": [],
                }
            resource_refs = [(schema, table, "table")]
            total_tables = 1
            truncated = False
        else:
            missing = [
                schema
                for schema in allowed_schemas
                if not schema_access.get(schema, {}).get("exists", False)
            ]
            if missing:
                return {
                    "error": (
                        f"allowed schema does not exist in database {database_name}: "
                        + ", ".join(sorted(missing))
                    ),
                    "layers": [],
                    "authorized_schemas": list(allowed_schemas),
                    "database_name": database_name,
                    "schema_access": schema_access,
                }
            denied = [
                schema
                for schema in allowed_schemas
                if not schema_access.get(schema, {}).get("has_usage", False)
            ]
            if denied:
                return {
                    "error": (
                        f"database credential lacks USAGE in database {database_name} "
                        "on allowed schema: "
                        + ", ".join(sorted(denied))
                    ),
                    "layers": [],
                    "authorized_schemas": list(allowed_schemas),
                    "database_name": database_name,
                    "schema_access": schema_access,
                }
            all_resource_refs = []
            for schema in allowed_schemas:
                all_resource_refs.extend(
                    (schema, table, "table")
                    for table in inspector.get_table_names(schema=schema)
                )
                all_resource_refs.extend(
                    (schema, view, "view")
                    for view in inspector.get_view_names(schema=schema)
                )
            all_resource_refs.sort(key=lambda item: (item[0], item[1], item[2]))
            total_tables = len(all_resource_refs)
            resource_refs = all_resource_refs[:discovery_limit]
            truncated = total_tables > len(resource_refs)

        layers = []
        for schema, table, resource_type in resource_refs:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Did not recognize type 'geometry'.*",
                    category=SAWarning,
                )
                columns = inspector.get_columns(table, schema=schema)
            primary_key = _safe_inspector_call(
                lambda table=table, schema=schema: inspector.get_pk_constraint(
                    table, schema=schema
                ),
                {},
            )
            foreign_keys = _safe_inspector_call(
                lambda table=table, schema=schema: inspector.get_foreign_keys(
                    table, schema=schema
                ),
                [],
            )
            indexes = _safe_inspector_call(
                lambda table=table, schema=schema: inspector.get_indexes(
                    table, schema=schema
                ),
                [],
            )
            table_comment = _safe_inspector_call(
                lambda table=table, schema=schema: inspector.get_table_comment(
                    table, schema=schema
                ),
                {},
            )
            layers.append(
                {
                    "name": f"{schema}.{table}",
                    "type": resource_type,
                    "columns": [
                        {
                            "name": column["name"],
                            "type": geometry_types.get(
                                (schema, table, str(column["name"])),
                                str(column["type"]),
                            ),
                            "nullable": bool(column.get("nullable", True)),
                        }
                        for column in columns
                    ],
                    "primary_key": list(primary_key.get("constrained_columns") or []),
                    "foreign_keys": [
                        {
                            "name": item.get("name"),
                            "columns": list(item.get("constrained_columns") or []),
                            "referred_schema": item.get("referred_schema") or schema,
                            "referred_table": item.get("referred_table"),
                            "referred_columns": list(item.get("referred_columns") or []),
                        }
                        for item in foreign_keys
                    ],
                    "indexes": [
                        {
                            "name": item.get("name"),
                            "columns": list(item.get("column_names") or []),
                            "unique": bool(item.get("unique", False)),
                        }
                        for item in indexes
                    ],
                    "estimated_record_count": estimated_rows.get((schema, table)),
                    "comment": table_comment.get("text") if table_comment else None,
                }
            )
        return {
            "layers": layers,
            "service": "Database",
            "provider": ("PostgreSQL" if endpoint_url.startswith("postgresql") else "Database"),
            "provider_version": (
                f"{provider_version}; PostGIS {spatial_version}"
                if endpoint_url.startswith("postgresql")
                else provider_version
            ),
            "spatial_version": spatial_version,
            "table_count": total_tables,
            "truncated": truncated,
            "discovery_scope": target_table or "schema_whitelist",
            "authorized_schemas": list(allowed_schemas),
            "database_name": database_name,
            "schema_access": schema_access,
        }
    except Exception as exc:
        return {"error": str(exc)[:200], "layers": []}
    finally:
        if engine is not None:
            engine.dispose()


class DatabaseConnector(BaseConnector):
    SOURCE_TYPE = "database"

    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: list[float] | None = None,
        filter_expr: str | None = None,
        limit: int = 1000,
        extra_params: dict | None = None,
        target_crs: str | None = None,
    ):
        """Execute a SQL query against an external database.

        endpoint_url: connection string (e.g. postgresql://user:pass@host/db)
        query_config: {"sql": "SELECT ...", "table": "...", "geom_column": "geom"}
        filter_expr: optional WHERE clause addition
        """
        import geopandas as gpd
        import pandas as pd
        from sqlalchemy import create_engine, text

        conn_str = _connection_url(endpoint_url, auth_config)

        sql, table, geom_col = _runtime_query_request(query_config, extra_params)
        sql_params = _runtime_query_parameters(extra_params)

        engine = None
        try:
            allowed_schemas = _allowed_schemas(query_config)
            statement_timeout_ms, lock_timeout_ms, configured_max_rows = _runtime_limits(
                query_config
            )
            row_limit = min(max(int(limit), 1), configured_max_rows, _ABSOLUTE_MAX_ROWS)
            if not sql and table:
                quoted_table = _quote_table(table)
                where = f" WHERE {filter_expr}" if filter_expr else ""
                sql = f"SELECT * FROM {quoted_table}{where}"
            elif not sql:
                return {"status": "error", "message": "需要提供 sql 或 table 参数"}
            sql = _governed_read_query(sql, allowed_schemas, row_limit)
            engine = create_engine(
                conn_str,
                pool_size=1,
                max_overflow=0,
                pool_pre_ping=True,
                connect_args=_connect_args(
                    endpoint_url,
                    connect_timeout=10,
                    statement_timeout_ms=statement_timeout_ms,
                    lock_timeout_ms=lock_timeout_ms,
                ),
            )
            with engine.begin() as conn:
                _set_transaction_read_only(
                    conn,
                    statement_timeout_ms=statement_timeout_ms,
                    lock_timeout_ms=lock_timeout_ms,
                )
                if geom_col:
                    gdf = gpd.read_postgis(
                        sql,
                        conn,
                        geom_col=geom_col,
                        params=sql_params or None,
                    )
                    if target_crs and gdf.crs and str(gdf.crs) != target_crs:
                        gdf = gdf.to_crs(target_crs)
                    return gdf
                else:
                    df = pd.read_sql(text(sql), conn, params=sql_params or None)
                    return df
        except Exception as e:
            return {"status": "error", "message": str(e)[:300]}
        finally:
            if engine is not None:
                engine.dispose()

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        from sqlalchemy import create_engine, text

        engine = None
        try:
            statement_timeout_ms, lock_timeout_ms, _ = _runtime_limits({})
            engine = create_engine(
                _connection_url(endpoint_url, auth_config),
                pool_size=1,
                max_overflow=0,
                pool_pre_ping=True,
                connect_args=_connect_args(
                    endpoint_url,
                    connect_timeout=5,
                    statement_timeout_ms=statement_timeout_ms,
                    lock_timeout_ms=lock_timeout_ms,
                ),
            )
            with engine.begin() as conn:
                _set_transaction_read_only(
                    conn,
                    statement_timeout_ms=statement_timeout_ms,
                    lock_timeout_ms=lock_timeout_ms,
                )
                conn.execute(text("SELECT 1"))
            return {"health": "healthy", "message": "OK"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}
        finally:
            if engine is not None:
                engine.dispose()

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        """List tables in the database."""
        return _database_capabilities(endpoint_url, auth_config)

    async def discover(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict | None = None,
    ) -> dict:
        config = query_config or {}
        target_table = str(config.get("table") or "") or None
        try:
            allowed_schemas = _allowed_schemas(config)
            statement_timeout_ms, lock_timeout_ms, _ = _runtime_limits(config)
            discovery_limit = _bounded_int(
                config.get("discovery_limit"),
                default=_DEFAULT_DISCOVERY_LIMIT,
                minimum=1,
                maximum=20_000,
                field="discovery_limit",
            )
        except ValueError as exc:
            return {"error": str(exc), "layers": []}
        return _database_capabilities(
            endpoint_url,
            auth_config,
            target_table=target_table,
            allowed_schemas=allowed_schemas,
            discovery_limit=discovery_limit,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        )


ConnectorRegistry.register(DatabaseConnector())
