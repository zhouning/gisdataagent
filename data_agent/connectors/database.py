"""Database connector — query external MySQL/PostgreSQL/SQLite databases (v15.0).

Users register external databases as virtual data sources. Queries execute
in a read-only, connection-pooled context with timeout enforcement.
"""

import logging
import re
import warnings

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SAWarning

from . import BaseConnector, ConnectorRegistry

logger = logging.getLogger(__name__)

_READ_QUERY_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


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


def _set_transaction_read_only(conn) -> None:
    if conn.dialect.name == "postgresql":
        from sqlalchemy import text

        conn.execute(text("SET TRANSACTION READ ONLY"))


def _database_capabilities(
    endpoint_url: str,
    auth_config: dict,
    *,
    target_table: str | None = None,
) -> dict:
    from sqlalchemy import create_engine, inspect, text

    engine = None
    try:
        if target_table and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?",
            target_table,
        ):
            return {"error": "invalid table identifier", "layers": []}
        engine = create_engine(
            _connection_url(endpoint_url, auth_config),
            pool_size=1,
            connect_args={"connect_timeout": 5},
        )
        provider_version = "unknown"
        spatial_version = "not_applicable"
        geometry_types: dict[tuple[str, str, str], str] = {}
        with engine.begin() as conn:
            _set_transaction_read_only(conn)
            if conn.dialect.name == "postgresql":
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
                if spatial_version != "not_installed":
                    geometry_types = {
                        (str(row[0]), str(row[1]), str(row[2])): (
                            f"geometry({row[3]},EPSG:{row[4]})"
                        )
                        for row in conn.execute(
                            text(
                                "SELECT f_table_schema, f_table_name, "
                                "f_geometry_column, type, srid FROM geometry_columns"
                            )
                        )
                    }
            elif conn.dialect.server_version_info:
                provider_version = ".".join(str(part) for part in conn.dialect.server_version_info)

        inspector = inspect(engine)
        if target_table:
            if "." in target_table:
                schema, table = target_table.split(".", 1)
            else:
                schema, table = "public", target_table
            if not inspector.has_table(table, schema=schema):
                return {
                    "error": f"governed source table was not discovered: {target_table}",
                    "layers": [],
                }
            table_refs = [(schema, table)]
            total_tables = 1
            truncated = False
        else:
            schemas = [
                schema
                for schema in inspector.get_schema_names()
                if schema not in {"information_schema"} and not schema.startswith("pg_")
            ]
            all_table_refs = [
                (schema, table)
                for schema in schemas
                for table in inspector.get_table_names(schema=schema)
            ]
            total_tables = len(all_table_refs)
            table_refs = all_table_refs[:50]
            truncated = total_tables > len(table_refs)

        layers = []
        for schema, table in table_refs:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Did not recognize type 'geometry'.*",
                    category=SAWarning,
                )
                columns = inspector.get_columns(table, schema=schema)
            layers.append(
                {
                    "name": f"{schema}.{table}",
                    "type": "table",
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
            "discovery_scope": target_table or "database",
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

        sql = query_config.get("sql", "")
        table = query_config.get("table", "")
        geom_col = query_config.get("geom_column", "")

        if not sql and table:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", table):
                return {"status": "error", "message": "invalid table identifier"}
            where = f" WHERE {filter_expr}" if filter_expr else ""
            sql = f"SELECT * FROM {table}{where} LIMIT {min(limit, 5000)}"
        elif not sql:
            return {"status": "error", "message": "需要提供 sql 或 table 参数"}

        try:
            sql = _read_only_sql(sql)
            engine = create_engine(
                conn_str, pool_size=1, max_overflow=0, connect_args={"connect_timeout": 10}
            )
            with engine.begin() as conn:
                _set_transaction_read_only(conn)
                if geom_col:
                    gdf = gpd.read_postgis(sql, conn, geom_col=geom_col)
                    if target_crs and gdf.crs and str(gdf.crs) != target_crs:
                        gdf = gdf.to_crs(target_crs)
                    return gdf
                else:
                    df = pd.read_sql(text(sql), conn)
                    return df
        except Exception as e:
            return {"status": "error", "message": str(e)[:300]}
        finally:
            try:
                engine.dispose()
            except Exception:
                pass

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        from sqlalchemy import create_engine, text

        try:
            engine = create_engine(
                _connection_url(endpoint_url, auth_config),
                pool_size=1,
                connect_args={"connect_timeout": 5},
            )
            with engine.begin() as conn:
                _set_transaction_read_only(conn)
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return {"health": "healthy", "message": "OK"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        """List tables in the database."""
        return _database_capabilities(endpoint_url, auth_config)

    async def discover(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict | None = None,
    ) -> dict:
        target_table = str((query_config or {}).get("table") or "") or None
        return _database_capabilities(
            endpoint_url,
            auth_config,
            target_table=target_table,
        )


ConnectorRegistry.register(DatabaseConnector())
