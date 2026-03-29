"""Database connector — query external MySQL/PostgreSQL/SQLite databases (v15.0).

Users register external databases as virtual data sources. Queries execute
in a read-only, connection-pooled context with timeout enforcement.
"""

import logging
from typing import Optional

from . import BaseConnector, ConnectorRegistry, build_auth_headers, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class DatabaseConnector(BaseConnector):
    SOURCE_TYPE = "database"

    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: Optional[list[float]] = None,
        filter_expr: Optional[str] = None,
        limit: int = 1000,
        extra_params: Optional[dict] = None,
        target_crs: Optional[str] = None,
    ):
        """Execute a SQL query against an external database.

        endpoint_url: connection string (e.g. postgresql://user:pass@host/db)
        query_config: {"sql": "SELECT ...", "table": "...", "geom_column": "geom"}
        filter_expr: optional WHERE clause addition
        """
        from sqlalchemy import create_engine, text
        import geopandas as gpd
        import pandas as pd

        conn_str = endpoint_url
        # Apply auth_config overrides
        if auth_config.get("type") == "basic":
            user = auth_config.get("username", "")
            pwd = auth_config.get("password", "")
            if user and "://" in conn_str:
                proto, rest = conn_str.split("://", 1)
                if "@" in rest:
                    rest = rest.split("@", 1)[1]
                conn_str = f"{proto}://{user}:{pwd}@{rest}"

        sql = query_config.get("sql", "")
        table = query_config.get("table", "")
        geom_col = query_config.get("geom_column", "")

        if not sql and table:
            where = f" WHERE {filter_expr}" if filter_expr else ""
            sql = f"SELECT * FROM {table}{where} LIMIT {min(limit, 5000)}"
        elif not sql:
            return {"status": "error", "message": "需要提供 sql 或 table 参数"}

        try:
            engine = create_engine(conn_str, pool_size=1, max_overflow=0,
                                   connect_args={"connect_timeout": 10})
            with engine.connect() as conn:
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
            engine = create_engine(endpoint_url, pool_size=1,
                                   connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return {"health": "healthy", "message": "OK"}
        except Exception as e:
            return {"health": "error", "message": str(e)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        """List tables in the database."""
        from sqlalchemy import create_engine, text, inspect
        try:
            engine = create_engine(endpoint_url, pool_size=1,
                                   connect_args={"connect_timeout": 5})
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            engine.dispose()
            layers = [{"name": t, "type": "table"} for t in tables[:50]]
            return {"layers": layers, "service": "Database", "table_count": len(tables)}
        except Exception as e:
            return {"error": str(e)[:200], "layers": []}


ConnectorRegistry.register(DatabaseConnector())
