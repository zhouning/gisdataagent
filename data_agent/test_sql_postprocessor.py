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
