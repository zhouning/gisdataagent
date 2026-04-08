"""Tests for cross-system lineage (v21.0)."""
import json
import pytest
from unittest.mock import patch, MagicMock

from data_agent.data_catalog import (
    register_external_asset,
    add_lineage_edge,
    get_cross_system_lineage,
    list_external_systems,
    delete_lineage_edge,
)


def _mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# register_external_asset
# ---------------------------------------------------------------------------


@patch("data_agent.data_catalog.get_engine")
def test_register_external_asset(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = (42,)

    result = register_external_asset(
        system="tableau",
        external_id="workbook:123",
        name="Sales Dashboard",
        url="https://tableau.example.com/views/123",
        description="Monthly sales overview",
        owner="alice",
    )
    assert result == 42
    conn.commit.assert_called_once()


@patch("data_agent.data_catalog.get_engine")
def test_register_external_asset_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    assert register_external_asset("sys", "id", "name") is None


# ---------------------------------------------------------------------------
# add_lineage_edge
# ---------------------------------------------------------------------------


@patch("data_agent.data_catalog.get_engine")
def test_add_lineage_edge_internal(mock_get_engine):
    """Internal → Internal lineage edge."""
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = (1,)

    edge_id = add_lineage_edge(
        source_asset_id=10,
        target_asset_id=20,
        relationship="derives_from",
        tool_name="spatial_join",
    )
    assert edge_id == 1


@patch("data_agent.data_catalog.get_engine")
def test_add_lineage_edge_external(mock_get_engine):
    """Internal → External lineage edge."""
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = (2,)

    edge_id = add_lineage_edge(
        source_asset_id=10,
        target_external=("airflow", "dag:etl_pipeline"),
        relationship="feeds_into",
    )
    assert edge_id == 2


@patch("data_agent.data_catalog.get_engine")
def test_add_lineage_edge_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    assert add_lineage_edge(source_asset_id=1, target_asset_id=2) is None


# ---------------------------------------------------------------------------
# get_cross_system_lineage
# ---------------------------------------------------------------------------


@patch("data_agent.data_catalog.get_engine")
def test_get_cross_system_lineage(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    # First call: get asset
    asset_result = MagicMock()
    asset_result.fetchone.return_value = (1, "parcels.shp", None, None, None)

    # Second call: get lineage edges
    edges_result = MagicMock()
    edges_result.fetchall.return_value = [
        (10, 1, None, None, None, "tableau", "wb:1", "feeds_into", "export"),
    ]

    conn.execute.side_effect = [asset_result, edges_result]

    result = get_cross_system_lineage(1, depth=3)
    assert len(result["nodes"]) >= 1
    assert "edges" in result


@patch("data_agent.data_catalog.get_engine")
def test_get_cross_system_lineage_not_found(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = None

    result = get_cross_system_lineage(999)
    assert result["error"] == "asset not found"


@patch("data_agent.data_catalog.get_engine")
def test_get_cross_system_lineage_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    result = get_cross_system_lineage(1)
    assert result["error"] == "no database"


# ---------------------------------------------------------------------------
# list_external_systems
# ---------------------------------------------------------------------------


@patch("data_agent.data_catalog.get_engine")
def test_list_external_systems(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchall.return_value = [
        ("tableau", 5),
        ("airflow", 3),
    ]

    systems = list_external_systems()
    assert len(systems) == 2
    assert systems[0]["system"] == "tableau"
    assert systems[0]["asset_count"] == 5


@patch("data_agent.data_catalog.get_engine")
def test_list_external_systems_empty(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchall.return_value = []

    assert list_external_systems() == []


# ---------------------------------------------------------------------------
# delete_lineage_edge
# ---------------------------------------------------------------------------


@patch("data_agent.data_catalog.get_engine")
def test_delete_lineage_edge(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    assert delete_lineage_edge(1) is True
    conn.commit.assert_called_once()


@patch("data_agent.data_catalog.get_engine")
def test_delete_lineage_edge_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    assert delete_lineage_edge(1) is False


# ---------------------------------------------------------------------------
# Route count
# ---------------------------------------------------------------------------


def test_route_count_updated():
    """Route count should include new lineage endpoints."""
    from data_agent.frontend_api import get_frontend_api_routes
    routes = get_frontend_api_routes()
    assert len(routes) == 271  # 266 + 5 lineage
