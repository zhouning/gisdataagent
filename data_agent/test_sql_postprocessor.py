"""Tests for sql_postprocessor.postprocess_sql."""
import pytest


def test_select_is_accepted():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql("SELECT 1", table_schemas={})
    assert result.rejected is False
    assert result.sql.strip().upper().startswith("SELECT")


def test_with_clause_is_accepted():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql("WITH t AS (SELECT 1) SELECT * FROM t", table_schemas={})
    assert result.rejected is False


def test_delete_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "DELETE FROM cq_osm_roads_2021 WHERE name IS NULL",
        table_schemas={},
    )
    assert result.rejected is True
    assert "DELETE" in result.reject_reason.upper() or "WRITE" in result.reject_reason.upper()


def test_update_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "UPDATE cq_land_use_dltb SET DLMC = '林地' WHERE DLMC = '有林地'",
        table_schemas={},
    )
    assert result.rejected is True


def test_drop_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "DROP TABLE cq_buildings_2021",
        table_schemas={},
    )
    assert result.rejected is True


def test_insert_is_rejected():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "INSERT INTO cq_buildings_2021 (Id) VALUES (1)",
        table_schemas={},
    )
    assert result.rejected is True


# --- Identifier quoting fix tests (from benchmark CQ_GEO_EASY_01/03) ---

_BUILDINGS_SCHEMA = {
    "cq_buildings_2021": [
        {"column_name": "Id", "needs_quoting": True},
        {"column_name": "Floor", "needs_quoting": True},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}

_DLTB_SCHEMA = {
    "cq_land_use_dltb": [
        {"column_name": "BSM", "needs_quoting": True},
        {"column_name": "DLMC", "needs_quoting": True},
        {"column_name": "DLBM", "needs_quoting": True},
        {"column_name": "TBMJ", "needs_quoting": True},
        {"column_name": "QSDWMC", "needs_quoting": True},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}

_ROADS_SCHEMA = {
    "cq_osm_roads_2021": [
        {"column_name": "name", "needs_quoting": False},
        {"column_name": "fclass", "needs_quoting": False},
        {"column_name": "maxspeed", "needs_quoting": False},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}


def test_fix_floor_lowercase():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40",
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert result.rejected is False
    assert '"Floor"' in result.sql
    assert any('Floor' in c for c in result.corrections)


def test_fix_id_lowercase():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(id) FROM cq_buildings_2021 WHERE floor >= 40",
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert '"Id"' in result.sql
    assert '"Floor"' in result.sql


def test_fix_dlmc_bsm_uppercase_unquoted():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT BSM FROM cq_land_use_dltb WHERE DLMC = '水田' AND TBMJ > 50000",
        table_schemas=_DLTB_SCHEMA,
    )
    assert '"BSM"' in result.sql
    assert '"DLMC"' in result.sql
    assert '"TBMJ"' in result.sql


def test_lowercase_columns_not_quoted():
    """Columns that are genuinely lowercase should NOT be quoted."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT name, fclass FROM cq_osm_roads_2021 WHERE maxspeed > 100",
        table_schemas=_ROADS_SCHEMA,
    )
    assert '"name"' not in result.sql
    assert '"fclass"' not in result.sql


def test_already_quoted_columns_preserved():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        'SELECT "Floor" FROM cq_buildings_2021 WHERE "Id" = 1',
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert '"Floor"' in result.sql
    assert '"Id"' in result.sql


def test_qualified_alias_columns_fixed():
    """b.Floor with table alias should still be fixed to b.\"Floor\"."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        'SELECT count(DISTINCT b.id) FROM cq_buildings_2021 b WHERE b.floor > 20',
        table_schemas=_BUILDINGS_SCHEMA,
    )
    assert '"Floor"' in result.sql
    assert '"Id"' in result.sql


# --- LIMIT injection tests (from CQ_GEO_ROBUSTNESS_03) ---

_POI_SCHEMA = {
    "cq_amap_poi_2024": [
        {"column_name": "名称", "needs_quoting": True},
        {"column_name": "类型", "needs_quoting": True},
        {"column_name": "geometry", "needs_quoting": False},
    ],
}


def test_inject_limit_on_large_table_full_scan():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT * FROM cq_amap_poi_2024",
        table_schemas=_POI_SCHEMA,
        large_tables={"cq_amap_poi_2024"},
    )
    assert "LIMIT" in result.sql.upper()
    assert "1000" in result.sql


def test_existing_limit_preserved():
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT * FROM cq_amap_poi_2024 LIMIT 50",
        table_schemas=_POI_SCHEMA,
        large_tables={"cq_amap_poi_2024"},
    )
    assert "LIMIT 50" in result.sql.upper().replace(" ", " ")
    # No duplicate LIMIT clauses
    assert result.sql.upper().count("LIMIT") == 1


def test_no_limit_on_small_table():
    """Small tables (not in large_tables set) should not get auto-LIMIT."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40",
        table_schemas=_BUILDINGS_SCHEMA,
        large_tables=set(),
    )
    assert "LIMIT" not in result.sql.upper()


def test_no_limit_on_aggregation_query():
    """COUNT/SUM queries return one row — no need for LIMIT even on large tables."""
    from data_agent.sql_postprocessor import postprocess_sql
    result = postprocess_sql(
        "SELECT count(*) FROM cq_amap_poi_2024",
        table_schemas=_POI_SCHEMA,
        large_tables={"cq_amap_poi_2024"},
    )
    assert "LIMIT" not in result.sql.upper()
