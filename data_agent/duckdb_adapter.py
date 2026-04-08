"""
DuckDB Lightweight Adapter — local analytical queries without PostGIS (v20.0).

Provides a lightweight alternative database backend for:
- Offline / demo / lite deployments
- Local analytical queries on uploaded data
- Quick data exploration without PostgreSQL dependency

Integrates with db_engine.py via DB_BACKEND environment variable.
"""
from __future__ import annotations

import os
from typing import Optional

from .observability import get_logger

logger = get_logger("duckdb_adapter")

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

_conn: Optional[object] = None
_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "local.duckdb")


class DuckDBAdapter:
    """Lightweight spatial database adapter using DuckDB + spatial extension."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        if not HAS_DUCKDB:
            raise ImportError("duckdb package not installed. Run: pip install duckdb")
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self._load_extensions()
        logger.info("DuckDB adapter initialized: %s", db_path)

    def _load_extensions(self):
        """Load spatial extension for geometry support (non-blocking)."""
        try:
            self.conn.execute("SET extension_directory = ''")  # use default
            self.conn.load_extension("spatial")
            logger.info("DuckDB spatial extension loaded")
        except Exception as e:
            logger.debug("DuckDB spatial extension not available (non-fatal): %s", e)

    def execute(self, sql: str, params: dict | list | None = None) -> list:
        """Execute SQL and return rows as list of tuples."""
        try:
            if params:
                result = self.conn.execute(sql, params)
            else:
                result = self.conn.execute(sql)
            return result.fetchall()
        except Exception as e:
            logger.warning("DuckDB execute failed: %s", e)
            raise

    def execute_df(self, sql: str, params: dict | list | None = None):
        """Execute SQL and return as pandas DataFrame."""
        try:
            if params:
                return self.conn.execute(sql, params).fetchdf()
            return self.conn.execute(sql).fetchdf()
        except Exception as e:
            logger.warning("DuckDB execute_df failed: %s", e)
            raise

    def load_geodataframe(self, gdf, table_name: str) -> int:
        """Load a GeoPandas GeoDataFrame into DuckDB as a table.

        Returns number of rows loaded.
        """
        try:
            import pandas as pd

            # Convert geometry to WKT for DuckDB spatial
            df = pd.DataFrame(gdf.drop(columns="geometry", errors="ignore"))
            if hasattr(gdf, "geometry") and gdf.geometry is not None:
                df["geometry_wkt"] = gdf.geometry.to_wkt()

            self.conn.register(f"_temp_{table_name}", df)
            self.conn.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _temp_{table_name}"
            )
            self.conn.unregister(f"_temp_{table_name}")

            count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            logger.info("Loaded %d rows into DuckDB table '%s'", count, table_name)
            return count
        except Exception as e:
            logger.warning("load_geodataframe failed: %s", e)
            raise

    def query_to_geodataframe(self, sql: str, geometry_col: str = "geometry_wkt"):
        """Execute SQL and return as GeoDataFrame.

        Expects a WKT geometry column that will be parsed.
        """
        try:
            import geopandas as gpd
            from shapely import wkt

            df = self.execute_df(sql)
            if geometry_col in df.columns:
                geom = df[geometry_col].apply(
                    lambda x: wkt.loads(x) if x and isinstance(x, str) else None
                )
                gdf = gpd.GeoDataFrame(
                    df.drop(columns=[geometry_col]),
                    geometry=geom,
                    crs="EPSG:4326",
                )
                return gdf
            return gpd.GeoDataFrame(df)
        except Exception as e:
            logger.warning("query_to_geodataframe failed: %s", e)
            raise

    def list_tables(self) -> list[str]:
        """List all tables in the DuckDB database."""
        rows = self.conn.execute("SHOW TABLES").fetchall()
        return [r[0] for r in rows]

    def describe_table(self, table_name: str) -> list[dict]:
        """Get column info for a table."""
        rows = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
        return [
            {"column_name": r[0], "column_type": r[1], "null": r[2], "key": r[3]}
            for r in rows
        ]

    def close(self):
        """Close DuckDB connection."""
        if self.conn:
            self.conn.close()
            self.conn = None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def get_duckdb_adapter(db_path: str = _DEFAULT_DB_PATH) -> Optional[DuckDBAdapter]:
    """Get or create singleton DuckDB adapter. Returns None if duckdb not installed."""
    global _conn
    if not HAS_DUCKDB:
        return None
    if _conn is None:
        _conn = DuckDBAdapter(db_path)
    return _conn


def reset_duckdb_adapter():
    """Reset singleton — for testing."""
    global _conn
    if _conn:
        _conn.close()
    _conn = None
