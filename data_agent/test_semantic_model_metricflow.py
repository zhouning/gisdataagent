"""Tests for semantic_model module (v19.0)."""
import json
import pytest
from unittest.mock import patch, MagicMock

from data_agent.semantic_model import (
    SemanticModelStore,
    SemanticModelGenerator,
    validate_model,
)


SAMPLE_YAML = """
semantic_models:
  - name: land_parcels
    description: 土地地块数据语义模型
    source_table: agent_dltb
    srid: 4326
    geometry_type: Polygon
    entities:
      - name: id
        type: primary
        column: id
    dimensions:
      - name: land_use
        type: categorical
        column: dlmc
      - name: geom
        type: spatial
        column: geom
        srid: 4326
    measures:
      - name: area_sqm
        agg: sum
        column: zmj
    metrics:
      - name: total_area
        type: simple
        measure: area_sqm
"""

SIMPLE_YAML = """
name: simple_model
source_table: test_table
dimensions:
  - name: category
    type: categorical
    column: cat
measures:
  - name: value
    agg: avg
    column: val
"""


def _mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------


def test_load_from_yaml_wrapped():
    store = SemanticModelStore()
    parsed = store.load_from_yaml(SAMPLE_YAML)
    assert parsed["name"] == "land_parcels"
    assert parsed["srid"] == 4326
    assert len(parsed["dimensions"]) == 2
    assert len(parsed["measures"]) == 1
    assert len(parsed["metrics"]) == 1


def test_load_from_yaml_simple():
    store = SemanticModelStore()
    parsed = store.load_from_yaml(SIMPLE_YAML)
    assert parsed["name"] == "simple_model"
    assert parsed["source_table"] == "test_table"


def test_load_from_yaml_invalid():
    store = SemanticModelStore()
    with pytest.raises(ValueError, match="Invalid YAML"):
        store.load_from_yaml("{{invalid yaml")


def test_load_from_yaml_no_name():
    store = SemanticModelStore()
    with pytest.raises(ValueError, match="name is required"):
        store.load_from_yaml("description: no name here")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_model_valid():
    errors = validate_model({"name": "test", "dimensions": [{"name": "d", "type": "categorical"}]})
    assert errors == []


def test_validate_model_invalid_dim_type():
    errors = validate_model({"name": "test", "dimensions": [{"name": "d", "type": "invalid"}]})
    assert len(errors) == 1
    assert "invalid type" in errors[0]


def test_validate_model_invalid_agg():
    errors = validate_model({"name": "test", "measures": [{"name": "m", "agg": "median"}]})
    assert len(errors) == 1
    assert "invalid agg" in errors[0]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@patch("data_agent.semantic_model.get_engine")
def test_save(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = (1,)

    store = SemanticModelStore()
    model_id = store.save("land_parcels", SAMPLE_YAML, "test model")
    assert model_id == 1
    conn.commit.assert_called_once()


@patch("data_agent.semantic_model.get_engine")
def test_save_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    store = SemanticModelStore()
    assert store.save("test", SIMPLE_YAML) is None


@patch("data_agent.semantic_model.get_engine")
def test_get(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    from datetime import datetime

    conn.execute.return_value.fetchone.return_value = (
        1, "land_parcels", "desc", SAMPLE_YAML,
        "agent_dltb", 4326, "Polygon",
        "[]", "[]", "[]", "[]",
        1, True, "alice", datetime(2026, 4, 8),
    )

    store = SemanticModelStore()
    item = store.get("land_parcels")
    assert item is not None
    assert item["name"] == "land_parcels"
    assert item["srid"] == 4326


@patch("data_agent.semantic_model.get_engine")
def test_get_not_found(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchone.return_value = None

    store = SemanticModelStore()
    assert store.get("nonexistent") is None


@patch("data_agent.semantic_model.get_engine")
def test_list_active(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    conn.execute.return_value.fetchall.return_value = []

    store = SemanticModelStore()
    items = store.list_active()
    assert items == []


@patch("data_agent.semantic_model.get_engine")
def test_delete(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    store = SemanticModelStore()
    assert store.delete("land_parcels") is True
    conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@patch("data_agent.semantic_model.get_engine")
def test_generate_from_table(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    # Mock column info
    col_result = MagicMock()
    col_result.fetchall.return_value = [
        ("id", "integer", "NO"),
        ("dlmc", "character varying", "YES"),
        ("zmj", "numeric", "YES"),
        ("geom", "USER-DEFINED", "YES"),
        ("created_at", "timestamp without time zone", "YES"),
    ]

    # Mock geometry info
    geom_result = MagicMock()
    geom_result.fetchone.return_value = ("geom", 4326, "Polygon")

    conn.execute.side_effect = [col_result, geom_result]

    gen = SemanticModelGenerator()
    yaml_text = gen.generate_from_table("agent_dltb")
    assert "agent_dltb" in yaml_text
    assert "spatial" in yaml_text
    assert "4326" in yaml_text


@patch("data_agent.semantic_model.get_engine")
def test_generate_from_table_not_found(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    col_result = MagicMock()
    col_result.fetchall.return_value = []
    conn.execute.return_value = col_result

    gen = SemanticModelGenerator()
    with pytest.raises(ValueError, match="not found"):
        gen.generate_from_table("nonexistent")


@patch("data_agent.semantic_model.get_engine")
def test_generate_no_db(mock_get_engine):
    mock_get_engine.return_value = None
    gen = SemanticModelGenerator()
    with pytest.raises(RuntimeError, match="No database"):
        gen.generate_from_table("test")
