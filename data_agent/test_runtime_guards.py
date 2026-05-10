"""Tests for data_agent/runtime_guards.py."""
from __future__ import annotations

import pytest

from data_agent.runtime_guards import (
    detect_give_up_sql,
    detect_hallucinated_table_name,
    is_safe_sql,
)


# ----------------------------------------------------------------------------
# detect_give_up_sql
# ----------------------------------------------------------------------------


class TestGiveUpSQL:
    def test_select_1_as_test(self):
        assert detect_give_up_sql("SELECT 1 AS test") is True

    def test_select_1_with_limit(self):
        assert detect_give_up_sql("SELECT 1 LIMIT 100000") is True

    def test_select_1_as_test_with_limit(self):
        assert detect_give_up_sql("SELECT 1 AS test LIMIT 100000") is True

    def test_select_1_with_semicolon(self):
        assert detect_give_up_sql("SELECT 1;") is True

    def test_select_placeholder(self):
        assert detect_give_up_sql("SELECT 'placeholder'") is True
        assert detect_give_up_sql("SELECT 'todo' AS x") is True

    def test_real_count_query_is_safe(self):
        assert detect_give_up_sql(
            "SELECT COUNT(*) FROM cq_buildings_2021 WHERE \"Floor\" >= 40"
        ) is False

    def test_real_select_with_value_1_is_safe(self):
        # SELECT 1 inside a real query is fine
        assert detect_give_up_sql(
            "SELECT 1 + 1 AS two FROM dual"
        ) is False

    def test_select_with_from_clause_is_safe(self):
        assert detect_give_up_sql("SELECT 1 FROM cq_buildings_2021 LIMIT 1") is False

    def test_select_one_real_use(self):
        # A real "SELECT 1 FROM table WHERE EXISTS" is not give-up
        assert detect_give_up_sql(
            "SELECT 1 FROM cq_amap_poi_2024 WHERE \"名称\" = 'X' LIMIT 1"
        ) is False

    def test_empty_sql(self):
        assert detect_give_up_sql("") is False

    def test_select_null(self):
        assert detect_give_up_sql("SELECT NULL") is True
        assert detect_give_up_sql("SELECT NULL AS x") is True

    def test_case_insensitive(self):
        assert detect_give_up_sql("select 1 as test") is True
        assert detect_give_up_sql("Select 1 As Test") is True

    def test_extra_whitespace(self):
        assert detect_give_up_sql("  SELECT   1   AS   test  ") is True


# ----------------------------------------------------------------------------
# detect_hallucinated_table_name
# ----------------------------------------------------------------------------


class TestHallucinated:
    def test_csv_file_path(self):
        sql = (
            r'SELECT * FROM "D:\\adk\\data_agent\\uploads\\cq_benchmark\\'
            r'query_result_4f04bb0d.csv" LIMIT 5'
        )
        result = detect_hallucinated_table_name(sql)
        assert result is not None
        assert ".csv" in result.lower() or "uploads" in result.lower()

    def test_query_result_cache_table(self):
        sql = "SELECT * FROM public.cq_query_result_5f273c3a LIMIT 100000"
        result = detect_hallucinated_table_name(sql)
        assert result is not None
        assert "query_result_" in result.lower()

    def test_unix_style_path(self):
        sql = "SELECT * FROM /tmp/results.csv"
        result = detect_hallucinated_table_name(sql)
        assert result is not None

    def test_real_table_name_is_safe(self):
        sql = "SELECT COUNT(*) FROM cq_buildings_2021 WHERE \"Floor\" >= 40"
        assert detect_hallucinated_table_name(sql) is None

    def test_real_table_with_schema_prefix(self):
        sql = "SELECT * FROM public.cq_amap_poi_2024 LIMIT 100"
        assert detect_hallucinated_table_name(sql) is None

    def test_join_clause_real_tables(self):
        sql = (
            "SELECT b.\"Floor\" FROM cq_buildings_2021 b "
            "JOIN cq_amap_poi_2024 p ON ST_Intersects(b.geometry, p.geometry)"
        )
        assert detect_hallucinated_table_name(sql) is None

    def test_subquery_not_flagged(self):
        sql = (
            "SELECT * FROM (SELECT \"DLMC\" FROM cq_land_use_dltb) sub LIMIT 100"
        )
        assert detect_hallucinated_table_name(sql) is None

    def test_allow_list_rejects_unknown(self):
        sql = "SELECT * FROM made_up_table"
        allowed = {"cq_buildings_2021", "cq_amap_poi_2024"}
        result = detect_hallucinated_table_name(sql, allowed)
        assert result == "made_up_table"

    def test_allow_list_accepts_known(self):
        sql = "SELECT * FROM cq_buildings_2021"
        allowed = {"cq_buildings_2021", "cq_amap_poi_2024"}
        assert detect_hallucinated_table_name(sql, allowed) is None

    def test_allow_list_with_schema_prefix(self):
        sql = "SELECT * FROM public.cq_buildings_2021"
        allowed = {"cq_buildings_2021"}
        assert detect_hallucinated_table_name(sql, allowed) is None

    def test_empty_sql(self):
        assert detect_hallucinated_table_name("") is None
        assert detect_hallucinated_table_name(None) is None


# ----------------------------------------------------------------------------
# is_safe_sql composite gate
# ----------------------------------------------------------------------------


class TestIsSafeSQL:
    def test_real_query_is_safe(self):
        ok, reason = is_safe_sql(
            "SELECT COUNT(*) FROM cq_buildings_2021 WHERE \"Floor\" >= 40"
        )
        assert ok is True
        assert reason == "ok"

    def test_give_up_rejected(self):
        ok, reason = is_safe_sql("SELECT 1 AS test LIMIT 100000")
        assert ok is False
        assert reason == "give_up_placeholder"

    def test_hallucinated_rejected(self):
        ok, reason = is_safe_sql(
            "SELECT * FROM public.cq_query_result_xxx LIMIT 100"
        )
        assert ok is False
        assert reason.startswith("hallucinated_table:")

    def test_give_up_takes_priority_over_hallucinated(self):
        # If both could match, give-up takes priority
        # (SELECT 1 has no FROM so hallucinated wouldn't fire anyway)
        ok, reason = is_safe_sql("SELECT 1")
        assert ok is False
        assert reason == "give_up_placeholder"

    def test_with_allow_list(self):
        sql = "SELECT * FROM nope_table"
        allowed = {"cq_buildings_2021"}
        ok, reason = is_safe_sql(sql, allowed)
        assert ok is False
        assert reason == "hallucinated_table:nope_table"
