"""Tests for DuckDB adapter (v20.0)."""
import os
import tempfile
import pytest
from unittest.mock import patch

from data_agent.duckdb_adapter import DuckDBAdapter, get_duckdb_adapter, reset_duckdb_adapter, HAS_DUCKDB


@pytest.fixture(autouse=True)
def _reset():
    reset_duckdb_adapter()
    yield
    reset_duckdb_adapter()


def _temp_db_path():
    """Get a temp path for DuckDB (file must NOT exist yet)."""
    d = tempfile.mkdtemp()
    return os.path.join(d, "test.duckdb")


# ---------------------------------------------------------------------------
# Basic operations
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")
def test_execute_simple():
    path = _temp_db_path()
    adapter = DuckDBAdapter(path)
    adapter.execute("CREATE TABLE test (id INTEGER, name VARCHAR)")
    adapter.execute("INSERT INTO test VALUES (1, 'alice'), (2, 'bob')")
    rows = adapter.execute("SELECT * FROM test ORDER BY id")
    assert len(rows) == 2
    assert rows[0] == (1, "alice")
    adapter.close()


@pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")
def test_execute_df():
    path = _temp_db_path()
    adapter = DuckDBAdapter(path)
    adapter.execute("CREATE TABLE nums (val INTEGER)")
    adapter.execute("INSERT INTO nums VALUES (10), (20), (30)")
    df = adapter.execute_df("SELECT * FROM nums")
    assert len(df) == 3
    assert "val" in df.columns
    adapter.close()


@pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")
def test_list_tables():
    path = _temp_db_path()
    adapter = DuckDBAdapter(path)
    adapter.execute("CREATE TABLE t1 (id INTEGER)")
    adapter.execute("CREATE TABLE t2 (id INTEGER)")
    tables = adapter.list_tables()
    assert "t1" in tables
    assert "t2" in tables
    adapter.close()


@pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")
def test_describe_table():
    path = _temp_db_path()
    adapter = DuckDBAdapter(path)
    adapter.execute("CREATE TABLE info (id INTEGER, name VARCHAR, area DOUBLE)")
    cols = adapter.describe_table("info")
    col_names = [c["column_name"] for c in cols]
    assert "id" in col_names
    assert "name" in col_names
    assert "area" in col_names
    adapter.close()


# ---------------------------------------------------------------------------
# GeoDataFrame integration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")
def test_load_geodataframe():
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError:
        pytest.skip("geopandas/shapely not installed")

    path = _temp_db_path()
    gdf = gpd.GeoDataFrame(
        {"name": ["A", "B"], "value": [1.0, 2.0]},
        geometry=[Point(120, 30), Point(121, 31)],
        crs="EPSG:4326",
    )
    adapter = DuckDBAdapter(path)
    count = adapter.load_geodataframe(gdf, "points")
    assert count == 2
    tables = adapter.list_tables()
    assert "points" in tables
    rows = adapter.execute("SELECT name, geometry_wkt FROM points ORDER BY name")
    assert rows[0][0] == "A"
    assert "POINT" in rows[0][1]
    adapter.close()


@pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")
def test_query_to_geodataframe():
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError:
        pytest.skip("geopandas/shapely not installed")

    path = _temp_db_path()
    gdf_in = gpd.GeoDataFrame(
        {"name": ["X"], "value": [42.0]},
        geometry=[Point(120, 30)],
        crs="EPSG:4326",
    )
    adapter = DuckDBAdapter(path)
    adapter.load_geodataframe(gdf_in, "geo_test")
    gdf_out = adapter.query_to_geodataframe("SELECT name, value, geometry_wkt FROM geo_test")
    assert len(gdf_out) == 1
    assert gdf_out.iloc[0]["name"] == "X"
    assert gdf_out.geometry.iloc[0] is not None
    adapter.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb not installed")
def test_singleton():
    a1 = get_duckdb_adapter()
    a2 = get_duckdb_adapter()
    assert a1 is a2
    reset_duckdb_adapter()
    a3 = get_duckdb_adapter()
    assert a3 is not a1


def test_no_duckdb():
    """When duckdb not installed, adapter returns None."""
    with patch("data_agent.duckdb_adapter.HAS_DUCKDB", False):
        reset_duckdb_adapter()
        result = get_duckdb_adapter()
        assert result is None
