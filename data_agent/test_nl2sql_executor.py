"""Tests for nl2sql_executor tools."""
from unittest.mock import patch, MagicMock
import json
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _reset_nl2sql_contextvars():
    """Reset shared ContextVars between tests so a prior test's cached schema
    does not leak into the runtime_guard's allowed_tables check (which would
    flip a benign FROM clause into a hallucinated_table rejection)."""
    from data_agent.user_context import (
        current_nl2sql_schemas, current_nl2sql_large_tables,
        current_nl2sql_question, current_nl2sql_intent,
    )
    from data_agent.nl2sql_intent import IntentLabel
    s = current_nl2sql_schemas.set({})
    lt = current_nl2sql_large_tables.set(set())
    q = current_nl2sql_question.set("")
    i = current_nl2sql_intent.set(IntentLabel.UNKNOWN)
    yield
    current_nl2sql_schemas.reset(s)
    current_nl2sql_large_tables.reset(lt)
    current_nl2sql_question.reset(q)
    current_nl2sql_intent.reset(i)


def _col(
    name,
    *,
    aliases=(),
    needs_quoting=False,
    is_geometry=False,
    srid=0,
    semantic_domain=None,
    unit="",
    value_semantics=None,
):
    return {
        "column_name": name,
        "quoted_ref": f'"{name}"' if needs_quoting else name,
        "aliases": list(aliases),
        "needs_quoting": needs_quoting,
        "is_geometry": is_geometry,
        "pg_type": f"geometry(Geometry,{srid})" if is_geometry and srid else "",
        "semantic_domain": semantic_domain,
        "unit": unit,
        "value_semantics": value_semantics or {},
    }


def _cq_context(*table_names):
    configs = {
        "cq_osm_roads_2021": [
            _col("name"),
            _col("osm_id", semantic_domain="ID", value_semantics={"identifier": True}),
            _col(
                "fclass",
                aliases=("road_class",),
                value_semantics={
                    "semantic_groups": [{
                        "aliases": ["\u4e3b\u5e72\u9053", "main road"],
                        "values": ["primary", "motorway"],
                    }],
                },
            ),
            _col("maxspeed"),
            _col("bridge"),
            _col("tunnel"),
            _col("geometry", aliases=("shape", "geom"), is_geometry=True, srid=4326),
        ],
        "cq_buildings_2021": [
            _col("Id", needs_quoting=True, semantic_domain="ID", value_semantics={"identifier": True}),
            _col("Floor", needs_quoting=True),
            _col("geometry", aliases=("shape", "geom"), is_geometry=True, srid=4326),
        ],
        "cq_historic_districts": [
            _col("jqmc"),
            _col("shape", aliases=("geometry", "geom"), is_geometry=True, srid=4610),
        ],
        "cq_land_use_dltb": [
            _col("BSM", aliases=("bsm",), needs_quoting=True, semantic_domain="ID", value_semantics={"identifier": True}),
            _col("DLBM", aliases=("dlbm",), needs_quoting=True),
            _col("DLMC", aliases=("dlmc",), needs_quoting=True),
            _col("QSDWMC", aliases=("qsdwmc",), needs_quoting=True),
            _col("QSDWDM", aliases=("qsdwdm",), needs_quoting=True),
            _col(
                "TBMJ",
                aliases=("tbmj",),
                needs_quoting=True,
                value_semantics={
                    "geometry_area_column": "geometry",
                    "use_geometry_area_when_question_matches": [
                        "real", "spatial", "geometry", "\u771f\u5b9e", "\u7a7a\u95f4", "\u51e0\u4f55",
                    ],
                },
            ),
            _col("geometry", aliases=("geom",), is_geometry=True, srid=4326),
        ],
        "cq_amap_poi_2024": [
            _col("ID", aliases=("id",), needs_quoting=True, semantic_domain="ID", value_semantics={"identifier": True}),
            _col("\u540d\u79f0", aliases=("name",), needs_quoting=True),
            _col("\u5730\u5740", aliases=("address",), needs_quoting=True),
            _col("\u7c7b\u578b", aliases=("type",), needs_quoting=True),
            _col("geometry", aliases=("shape", "geom"), is_geometry=True, srid=4326),
        ],
        "cq_baidu_aoi_2024": [
            _col("\u540d\u79f0", aliases=("name",), needs_quoting=True),
            _col("\u8bc4\u5206", aliases=("score",), needs_quoting=True),
            _col("shape", aliases=("geometry", "geom"), is_geometry=True, srid=4326),
        ],
        "cq_dltb": [
            _col("bsm", aliases=("BSM",), semantic_domain="ID", value_semantics={"identifier": True}),
            _col("dlbm", aliases=("DLCB", "dlcb")),
            _col(
                "dlmc",
                aliases=("DLMC",),
                value_semantics={
                    "literal_column_overrides": [{
                        "value": "\u6751\u5e84",
                        "wrong_columns": ["dlbm"],
                    }],
                },
            ),
            _col("tbmj", aliases=("TBMJ",)),
            _col("shape", aliases=("geometry", "geom"), is_geometry=True, srid=4610),
        ],
        "cq_unicom_commuting_2023": [
            _col("\u5e74\u9f84", aliases=("age",), needs_quoting=True),
            _col(
                "\u6269\u6837\u540e\u4eba\u53e3",
                aliases=("sample_population", "\u6269\u6837\u540e\u603b\u4eba\u53e3"),
                needs_quoting=True,
            ),
        ],
        "cq_district_population": [
            _col("\u533a\u5212\u540d\u79f0", needs_quoting=True),
            _col(
                "\u6237\u7c4d\u603b\u4eba\u53e3_\u4e07\u4eba_",
                needs_quoting=True,
                unit="\u4e07\u4eba",
                value_semantics={
                    "stored_unit_multiplier": 10000,
                    "natural_unit_aliases": ["\u4eba", "people", "persons"],
                },
            ),
        ],
    }
    return {
        "candidate_tables": [
            {
                "table_name": name,
                "columns": configs.get(name, []),
                "schema_complete": True,
            }
            for name in table_names
        ],
    }


def test_prepare_nl2sql_context_returns_prompt_and_caches_schema():
    from data_agent.nl2sql_executor import prepare_nl2sql_context, _cached_schemas

    payload = {
        "candidate_tables": [{
            "table_name": "cq_buildings_2021",
            "columns": [
                {"column_name": "Id", "needs_quoting": True},
                {"column_name": "Floor", "needs_quoting": True},
            ],
            "row_count_hint": 107035,
        }],
        "semantic_hints": {},
        "few_shots": [],
        "grounding_prompt": "PROMPT BLOCK",
    }
    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload):
        prompt = prepare_nl2sql_context("统计层高>=40")
    assert prompt == "PROMPT BLOCK"
    cached = _cached_schemas.get()
    assert "cq_buildings_2021" in cached
    assert cached["cq_buildings_2021"][0]["column_name"] == "Id"


def test_execute_nl2sql_rejected_returns_message():
    from data_agent.nl2sql_executor import execute_nl2sql
    class FakeResult:
        rejected = True
        reject_reason = "Only SELECT/WITH queries are allowed"
        sql = "DELETE FROM t"
    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()):
        result = execute_nl2sql("DELETE FROM t")
    assert "安全拒绝" in result


def test_execute_nl2sql_executes_corrected_sql():
    from data_agent.nl2sql_executor import execute_nl2sql
    class FakeResult:
        rejected = False
        reject_reason = ""
        sql = 'SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40'
    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1,"data":[{"count":123}],"message":"ok"}') as mock_exec, \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = execute_nl2sql("SELECT count(*) FROM cq_buildings_2021 WHERE floor >= 40")
    mock_exec.assert_called_once_with('SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40')
    assert '"status":"ok"' in result


def test_gemma_semantic_prompt_treats_export_requests_as_safe_limited_selects():
    from data_agent.nl2sql_executor import _build_gemma_semantic_prompt

    prompt = _build_gemma_semantic_prompt(
        "download all rows from places",
        {"grounding_prompt": "Table places(name, geometry)", "_hint_injection_stats": {}},
    )

    assert "download" in prompt.lower()
    assert "export" in prompt.lower()
    assert "LIMIT" in prompt
    assert "SELECT 1" in prompt


def test_extract_sql_prefers_last_corrected_select_statement():
    from data_agent.nl2sql_executor import _extract_sql

    text = (
        "SELECT SUM(ST_XMax(geometry::geography)) FROM roads;\n\n"
        "Wait, the correct PostGIS length expression is:\n"
        "SELECT SUM(ST_Length(geometry::geography)) FROM roads;"
    )

    assert _extract_sql(text) == "SELECT SUM(ST_Length(geometry::geography)) FROM roads"


def test_extract_sql_keeps_exists_subquery_inside_outer_statement():
    from data_agent.nl2sql_executor import _extract_sql

    text = (
        'SELECT COUNT(DISTINCT b."Id") FROM cq_buildings_2021 AS b '
        "WHERE EXISTS(SELECT 1 FROM cq_osm_roads_2021 AS r "
        "WHERE ST_Intersects(b.geometry, r.geometry) AND r.bridge = 'T')"
    )

    assert _extract_sql(text) == text


def test_extract_sql_keeps_cte_with_final_select():
    from data_agent.nl2sql_executor import _extract_sql

    text = (
        "WITH longest_bridge AS ("
        "SELECT geometry FROM cq_osm_roads_2021 WHERE bridge = 'T' "
        "ORDER BY ST_Length(geometry::geography) DESC LIMIT 1"
        ") "
        'SELECT COUNT(DISTINCT p."ID") FROM cq_amap_poi_2024 AS p '
        "JOIN longest_bridge AS lb "
        "ON ST_DWithin(p.geometry::geography, lb.geometry::geography, 100)"
    )

    assert _extract_sql(text) == text


def test_safe_preview_fallback_selects_all_for_backup_request():
    from data_agent.nl2sql_executor import _build_safe_preview_sql

    sql = _build_safe_preview_sql(
        "download places table as a backup",
        {
            "candidate_tables": [{
                "table_name": "places",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                ],
            }],
        },
    )

    assert sql == "SELECT * FROM places LIMIT 1000"


def test_safe_preview_fallback_prefers_exact_table_mention_over_first_candidate():
    from data_agent.nl2sql_executor import _build_safe_preview_sql

    sql = _build_safe_preview_sql(
        "download cq_land_use_dltb as a backup",
        {
            "candidate_tables": [
                {"table_name": "unrelated_names", "columns": [{"column_name": "name", "quoted_ref": "name"}]},
                {"table_name": "cq_land_use_dltb", "columns": [{"column_name": "geometry", "quoted_ref": "geometry"}]},
            ],
        },
    )

    assert sql == "SELECT * FROM cq_land_use_dltb LIMIT 1000"


def test_safe_preview_fallback_selects_requested_name_and_geometry_columns():
    from data_agent.nl2sql_executor import _build_safe_preview_sql

    sql = _build_safe_preview_sql(
        "show all POI records with coordinates and name",
        {
            "candidate_tables": [{
                "table_name": "places",
                "columns": [
                    {"column_name": "name", "quoted_ref": "name", "aliases": ["title"], "needs_quoting": False},
                    {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                    {"column_name": "phone", "quoted_ref": "phone", "needs_quoting": False},
                ],
            }],
        },
    )

    assert sql == "SELECT name, geometry FROM places LIMIT 1000"


def test_safe_preview_fallback_prefers_geometry_table_for_coordinate_request():
    from data_agent.nl2sql_executor import _build_safe_preview_sql

    sql = _build_safe_preview_sql(
        "show all POI records with coordinates and name",
        {
            "candidate_tables": [
                {
                    "table_name": "school_names",
                    "columns": [{"column_name": "name", "quoted_ref": "name", "needs_quoting": False}],
                },
                {
                    "table_name": "city_poi",
                    "columns": [
                        {"column_name": "name", "quoted_ref": "name", "needs_quoting": False},
                        {"column_name": "geometry", "quoted_ref": "geometry", "is_geometry": True},
                    ],
                },
            ],
        },
    )

    assert sql == "SELECT name, geometry FROM city_poi LIMIT 1000"


def test_refuse_nl2sql_question_detects_write_intent():
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question

    assert _should_refuse_nl2sql_question("delete all rows where name is null", {}) is True
    assert _should_refuse_nl2sql_question("把道路表中没有名称的记录删掉", {}) is True


def test_refuse_nl2sql_question_detects_rewrite_and_maintenance_intents():
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question

    assert _should_refuse_nl2sql_question("把 POI 表里所有星巴克的名称改成瑞幸咖啡。", {}) is True
    assert _should_refuse_nl2sql_question("执行 VACUUM FULL cq_buildings_2021 来回收空间。", {}) is True


def test_refuse_nl2sql_question_detects_missing_explicit_column_request():
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question

    payload = {
        "candidate_tables": [{
            "table_name": "roads",
            "columns": [
                {"column_name": "name", "aliases": []},
                {"column_name": "maxspeed", "aliases": []},
            ],
        }],
    }

    assert _should_refuse_nl2sql_question(
        "查询道路表中的 speed_limit 和 lane_count 字段。",
        payload,
    ) is True

    payload["candidate_tables"][0]["columns"].append({
        "column_name": "speed_limit",
        "aliases": ["speed limit"],
    })
    payload["candidate_tables"][0]["columns"].append({
        "column_name": "lane_count",
        "aliases": ["lanes"],
    })

    assert _should_refuse_nl2sql_question(
        "查询道路表中的 speed_limit 和 lane_count 字段。",
        payload,
    ) is False


def test_refuse_nl2sql_question_allows_result_list_with_sql_filter_syntax():
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question

    payload = {
        "candidate_tables": [
            {
                "table_name": "land_use_polygons",
                "table_aliases": ["land-use parcels", "\u571f\u5730\u5229\u7528\u56fe\u6591"],
                "columns": [
                    {"column_name": "QSDWMC", "aliases": ["owner unit"]},
                    {"column_name": "geometry", "aliases": ["geometry"], "is_geometry": True},
                ],
            },
            {
                "table_name": "city_poi",
                "table_aliases": ["POI", "points of interest"],
                "columns": [
                    {"column_name": "\u540d\u79f0", "aliases": ["name", "POI name"]},
                    {"column_name": "geometry", "aliases": ["geometry"], "is_geometry": True},
                ],
            },
        ],
    }

    assert _should_refuse_nl2sql_question(
        "\u627e\u51fa QSDWMC LIKE '%Downtown%' \u7684\u571f\u5730\u5229\u7528\u56fe\u6591\u8303\u56f4\u5185\u7684 POI \u540d\u79f0\u5217\u8868",
        payload,
    ) is False


def test_refuse_nl2sql_question_treats_dataset_alias_as_table_not_missing_column():
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question

    payload = {
        "candidate_tables": [{
            "table_name": "city_aoi",
            "table_aliases": ["AOI", "AOI data"],
            "columns": [
                {"column_name": "name", "aliases": ["名称"]},
                {"column_name": "category1", "aliases": ["第一分类"]},
            ],
        }],
    }

    assert _should_refuse_nl2sql_question(
        "Find AOI names where category1 field is medical",
        payload,
    ) is False


def test_refuse_nl2sql_question_detects_unavailable_ranking_metric():
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question

    payload = {
        "candidate_tables": [{
            "table_name": "poi",
            "columns": [
                {"column_name": "name", "aliases": ["名称"]},
                {"column_name": "geometry", "aliases": []},
            ],
        }],
    }

    assert _should_refuse_nl2sql_question("列出所有地铁站点的客流量排名", payload) is True

    payload["candidate_tables"][0]["columns"].append({"column_name": "客流量", "aliases": ["ridership"]})
    assert _should_refuse_nl2sql_question("列出所有地铁站点的客流量排名", payload) is False


def test_refuse_nl2sql_question_allows_computable_count_ranking_and_sorting():
    from data_agent.nl2sql_executor import _should_refuse_nl2sql_question

    payload = {
        "candidate_tables": [{
            "table_name": "roads",
            "columns": [
                {"column_name": "fclass", "aliases": []},
                {"column_name": "objectid", "aliases": []},
            ],
        }],
    }

    assert _should_refuse_nl2sql_question("按道路等级分组，统计每种等级的道路总条数，并按条数从大到小排序。", payload) is False
    assert _should_refuse_nl2sql_question("按 objectid 排序取第一个图斑。", payload) is False


# --- Phase 2: self-correction tests ---


def test_execute_nl2sql_retries_on_failure():
    """First execution fails, LLM retry succeeds."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("test question")

    class FakeResult:
        rejected = False
        reject_reason = ""
        def __init__(self, sql):
            self.sql = sql

    call_count = [0]
    def fake_postprocess(sql, schemas, large_tables, **kwargs):
        return FakeResult(sql)

    def fake_execute(sql):
        call_count[0] += 1
        if call_count[0] == 1:
            return json.dumps({"status": "error", "error": 'column "dlmc" does not exist'})
        return json.dumps({"status": "ok", "rows": 1, "data": [{"count": 42}]})

    with patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=fake_postprocess), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", side_effect=fake_execute), \
         patch("data_agent.nl2sql_executor._retry_with_llm", return_value='SELECT COUNT(*) FROM t WHERE "DLMC" = \'x\''), \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = execute_nl2sql("SELECT COUNT(*) FROM t WHERE dlmc = 'x'")

    parsed = json.loads(result)
    assert parsed["status"] == "ok"
    assert call_count[0] == 2


def test_execute_nl2sql_max_retries_exceeded():
    """All retries fail, returns last error."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("test question")

    class FakeResult:
        rejected = False
        reject_reason = ""
        def __init__(self, sql):
            self.sql = sql

    error_json = json.dumps({"status": "error", "error": "persistent error"})

    with patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=lambda s, *a, **kw: FakeResult(s)), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value=error_json), \
         patch("data_agent.nl2sql_executor._retry_with_llm", return_value='SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40'):
        result = execute_nl2sql("SELECT bad_sql")

    parsed = json.loads(result)
    assert parsed["status"] == "error"


def test_execute_nl2sql_auto_curates_on_success():
    """Successful execution triggers auto-curate."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("count buildings")

    class FakeResult:
        rejected = False
        reject_reason = ""
        sql = "SELECT COUNT(*) FROM buildings"

    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1}'), \
         patch("data_agent.nl2sql_executor._auto_curate") as mock_curate:
        execute_nl2sql("SELECT COUNT(*) FROM buildings")

    mock_curate.assert_called_once_with("count buildings", "SELECT COUNT(*) FROM buildings")


def test_execute_nl2sql_skip_curate_on_reject():
    """Security rejection should not trigger auto-curate."""
    from data_agent.nl2sql_executor import execute_nl2sql

    class FakeResult:
        rejected = True
        reject_reason = "write operation"
        sql = "DELETE FROM t"

    with patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()), \
         patch("data_agent.nl2sql_executor._auto_curate") as mock_curate:
        execute_nl2sql("DELETE FROM t")

    mock_curate.assert_not_called()


def test_retry_with_llm_sets_timeout_and_retry_options():
    """Retry path should set explicit API timeout to avoid hanging the UI."""
    from data_agent.nl2sql_executor import _retry_with_llm

    mock_resp = MagicMock()
    mock_resp.text = 'SELECT 1'
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp

    with patch('google.genai.Client', return_value=mock_client):
        result = _retry_with_llm('q', 'bad sql', 'syntax error', {'t': []})

    assert result == 'SELECT 1'
    kwargs = mock_client.models.generate_content.call_args.kwargs
    config = kwargs['config']
    assert getattr(config, 'temperature', None) == 0.0
    assert getattr(config, 'http_options', None) is not None


def test_execute_nl2sql_no_retry_when_llm_returns_none():
    """If LLM retry returns None, return original error without further retries."""
    from data_agent.nl2sql_executor import execute_nl2sql, current_nl2sql_question

    current_nl2sql_question.set("test")

    class FakeResult:
        rejected = False
        reject_reason = ""
        def __init__(self, sql):
            self.sql = sql

    error_json = json.dumps({"status": "error", "error": "some error"})

    exec_calls = [0]
    def fake_exec(sql):
        exec_calls[0] += 1
        return error_json

    with patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=lambda s, *a, **kw: FakeResult(s)), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", side_effect=fake_exec), \
         patch("data_agent.nl2sql_executor._retry_with_llm", return_value=None):
        result = execute_nl2sql("SELECT bad")

    assert exec_calls[0] == 1


def test_prepare_nl2sql_context_caches_intent():
    from unittest.mock import patch
    from data_agent.nl2sql_intent import IntentLabel
    from data_agent import nl2sql_executor
    from data_agent.user_context import current_nl2sql_intent

    payload = {
        "candidate_tables": [],
        "intent": IntentLabel.KNN,
        "intent_source": "rule",
        "grounding_prompt": "...",
    }
    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload):
        nl2sql_executor.prepare_nl2sql_context("问题")
    assert current_nl2sql_intent.get() is IntentLabel.KNN


def test_gemma_semantic_rewrite_expands_main_roads():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_osm_roads_2021")
    sql = (
        "SELECT COUNT(*) FROM cq_osm_roads_2021 "
        "WHERE fclass = 'primary' AND maxspeed > 100"
    )
    rewritten, corrections = apply_gemma_semantic_rewrites(
        "统计主干道中限速大于100的道路数量",
        sql,
        context,
    )

    assert "fclass IN ('primary', 'motorway')" in rewritten
    assert "semantic_value_group" in corrections


def test_gemma_semantic_rewrite_preserves_explicit_primary_fclass():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_osm_roads_2021")
    sql = (
        "SELECT name FROM cq_osm_roads_2021 "
        "WHERE maxspeed > 100 AND fclass = 'primary'"
    )
    rewritten, corrections = apply_gemma_semantic_rewrites(
        "道路数据中，列出所有限速 maxspeed 大于 100 且 fclass 为 'primary' 的道路名称",
        sql,
        context,
    )

    assert "fclass = 'primary'" in rewritten
    assert "motorway" not in rewritten
    assert "semantic_value_group" not in corrections


def test_gemma_semantic_rewrite_counts_distinct_buildings_on_road_join():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_buildings_2021", "cq_osm_roads_2021")
    sql = (
        'SELECT COUNT(*) FROM cq_buildings_2021 b '
        'JOIN cq_osm_roads_2021 r ON ST_Intersects(b.geometry, r.geometry) '
        "WHERE r.bridge = 'yes'"
    )
    rewritten, corrections = apply_gemma_semantic_rewrites(
        "统计与桥梁相交的建筑物数量",
        sql,
        context,
    )

    assert 'COUNT(DISTINCT b."Id")' in rewritten
    assert "semantic_distinct_join_count" in corrections


def test_run_nl2semantic2sql_builds_gemma_context_and_executes():
    from data_agent import nl2sql_executor

    payload = _cq_context("cq_osm_roads_2021")
    payload.update({
        "grounding_prompt": "GROUNDING",
        "few_shots": [],
        "_hint_injection_stats": {"candidate_tables": 1, "few_shots": 0},
    })

    class FakeResult:
        rejected = False
        reject_reason = ""
        sql = (
            "SELECT COUNT(*) FROM cq_osm_roads_2021 "
            "WHERE fclass IN ('primary', 'motorway') AND maxspeed > 100"
        )

    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload) as mock_context, \
         patch("data_agent.nl2sql_executor._generate_gemma_sql", return_value="SELECT COUNT(*) FROM cq_osm_roads_2021 WHERE fclass = 'primary' AND maxspeed > 100") as mock_generate, \
         patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()) as mock_postprocess, \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1,"data":[{"count":7}]}') as mock_exec, \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = json.loads(nl2sql_executor.run_nl2semantic2sql("统计主干道中限速大于100的道路数量"))

    mock_context.assert_called_once_with("统计主干道中限速大于100的道路数量", family="gemma")
    assert "GROUNDING" in mock_generate.call_args.args[0]
    mock_postprocess.assert_called_once()
    mock_exec.assert_called_once_with(FakeResult.sql)
    assert result["status"] == "ok"
    assert result["sql"] == FakeResult.sql
    assert result["corrections"] == ["semantic_value_group"]


def test_run_nl2semantic2sql_hydrates_sql_referenced_table_for_alias_rewrite():
    from data_agent import nl2sql_executor

    payload = _cq_context("cq_buildings_2021")
    payload.update({
        "grounding_prompt": "GROUNDING",
        "few_shots": [],
        "_hint_injection_stats": {"candidate_tables": 1, "few_shots": 0},
    })
    amap_schema = {
        "status": "success",
        "display_name": "Amap POI",
        "geometry_type": "POINT",
        "srid": 4326,
        "columns": [
            {"column_name": "ID", "data_type": "integer", "is_geometry": False, "value_semantics": {"identifier": True}},
            {"column_name": "\u540d\u79f0", "data_type": "text", "is_geometry": False, "value_semantics": {"sql_aliases": ["name"]}},
            {"column_name": "\u7c7b\u578b", "data_type": "text", "is_geometry": False, "value_semantics": {"sql_aliases": ["type"]}},
            {"column_name": "geometry", "data_type": "USER-DEFINED", "is_geometry": True, "value_semantics": {}},
        ],
    }

    class FakeResult:
        rejected = False
        reject_reason = ""

        def __init__(self, sql):
            self.sql = sql

    def fake_postprocess(sql, schemas, large_tables, **kwargs):
        assert "cq_amap_poi_2024" in schemas
        return FakeResult(sql)

    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload), \
         patch("data_agent.nl2sql_executor._generate_gemma_sql", return_value="SELECT p.name FROM cq_amap_poi_2024 AS p WHERE p.type LIKE '%hospital%'"), \
         patch("data_agent.nl2sql_executor.describe_table_semantic", return_value=amap_schema, create=True), \
         patch("data_agent.nl2sql_executor._estimate_table_size", return_value=10, create=True), \
         patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=fake_postprocess), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1,"data":[]}') as mock_exec, \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = json.loads(nl2sql_executor.run_nl2semantic2sql("poi near buildings"))

    assert result["status"] == "ok"
    assert 'p."\u540d\u79f0"' in result["sql"]
    assert 'p."\u7c7b\u578b"' in result["sql"]
    mock_exec.assert_called_once_with(result["sql"])


def test_run_nl2semantic2sql_retries_ungrounded_sql_referenced_table():
    from data_agent import nl2sql_executor

    payload = _cq_context("cq_land_use_dltb")
    payload.update({
        "grounding_prompt": "GROUNDING",
        "few_shots": [],
        "_hint_injection_stats": {"candidate_tables": 1, "few_shots": 0},
    })

    class FakeResult:
        rejected = False
        reject_reason = ""
        corrections = []

        def __init__(self, sql):
            self.sql = sql

    generated = [
        "SELECT SUM(ST_Area(mp_parcel.geom::geography)) FROM mp_parcel WHERE land_use_type = '水田'",
        'SELECT SUM(ST_Area(l.geometry::geography)) FROM cq_land_use_dltb AS l WHERE l."DLMC" = \'水田\'',
    ]

    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload), \
         patch("data_agent.nl2sql_executor._generate_gemma_sql", side_effect=generated) as mock_generate, \
         patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=lambda sql, *a, **kw: FakeResult(sql)), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1,"data":[{"sum":1}]}'), \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = json.loads(nl2sql_executor.run_nl2semantic2sql("计算所有水田的真实空间总面积"))

    assert mock_generate.call_count == 2
    assert result["status"] == "ok"
    assert "mp_parcel" not in result["sql"]
    assert "cq_land_use_dltb" in result["sql"]
    assert "gemma_ungrounded_table_retry" in result["corrections"]


def test_candidate_from_described_schema_preserves_source_synonyms():
    from data_agent.nl2sql_executor import _candidate_from_described_schema

    candidate = _candidate_from_described_schema(
        "cq_amap_poi_2024",
        {
            "status": "success",
            "source_metadata": {
                "display_name": "高德 POI",
                "description": "兴趣点",
                "synonyms": ["POI", "学校", "医院"],
                "geometry_type": "POINT",
                "srid": 4326,
            },
            "columns": [
                {"column_name": "ID", "data_type": "integer", "value_semantics": {"identifier": True}},
            ],
        },
    )

    assert "POI" in candidate["table_aliases"]
    assert "学校" in candidate["table_aliases"]
    assert "高德 POI" in candidate["table_aliases"]


def test_run_nl2semantic2sql_uses_preview_fallback_when_postprocess_rejects_all_records_request():
    from data_agent import nl2sql_executor

    payload = _cq_context("cq_land_use_dltb")
    payload["candidate_tables"][0]["row_count_hint"] = 2_000_000
    payload.update({
        "grounding_prompt": "GROUNDING",
        "few_shots": [],
        "_hint_injection_stats": {"candidate_tables": 1, "few_shots": 0},
    })

    class RejectedResult:
        rejected = True
        reject_reason = "SQL parse error"
        sql = ""
        corrections = []

    class AcceptedResult:
        rejected = False
        reject_reason = ""
        corrections = ["LIMIT 1000 injected (large-table guard)"]

        def __init__(self, sql):
            self.sql = sql

    def fake_postprocess(sql, schemas, large_tables, **kwargs):
        if sql == "BROKEN SQL":
            return RejectedResult()
        return AcceptedResult(sql)

    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload), \
         patch("data_agent.nl2sql_executor._generate_gemma_sql", return_value="BROKEN SQL"), \
         patch("data_agent.nl2sql_executor.postprocess_sql", side_effect=fake_postprocess), \
         patch("data_agent.nl2sql_executor.execute_safe_sql", return_value='{"status":"ok","rows":1000,"data":[]}') as mock_exec, \
         patch("data_agent.nl2sql_executor._auto_curate"):
        result = json.loads(nl2sql_executor.run_nl2semantic2sql("show all land use records"))

    assert result["status"] == "ok"
    assert result["sql"] == "SELECT * FROM cq_land_use_dltb LIMIT 1000"
    assert "safe_preview_fallback" in result["corrections"]
    mock_exec.assert_called_once_with("SELECT * FROM cq_land_use_dltb LIMIT 1000")


def test_gemma_semantic_rewrite_center_building_dataset_is_not_area_filter():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_buildings_2021", "cq_historic_districts")
    sql = (
        'SELECT COUNT(DISTINCT b."Id") FROM cq_buildings_2021 AS b '
        'JOIN cq_historic_districts AS d ON ST_Intersects(b.geometry, d.shape) '
        'WHERE b."Floor" >= 40 AND d.jqmc = \'中心城区\''
    )
    rewritten, corrections = apply_gemma_semantic_rewrites(
        "统计中心城区建筑数据中，层高（Floor）大于等于 40 层的超高层建筑有多少栋？",
        sql,
        context,
    )

    assert "ST_Transform(b.geometry, 4610)" in rewritten
    assert "semantic_srid_transform" in corrections


def test_gemma_semantic_rewrite_land_use_area_uses_geography_for_cq_land_use():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_land_use_dltb")
    sql = 'SELECT SUM(TBMJ) / 10000 FROM cq_land_use_dltb WHERE "DLMC" = \'水田\''
    rewritten, corrections = apply_gemma_semantic_rewrites(
        "计算所有水田的真实空间总面积，以公顷为单位返回。",
        sql,
        context,
    )

    assert "SUM(ST_Area(cq_land_use_dltb.geometry::geography))" in rewritten
    assert "semantic_area_metric" in corrections


def test_gemma_semantic_rewrite_amap_poi_name_and_dwithin_geography():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_buildings_2021", "cq_amap_poi_2024")
    sql = (
        'SELECT AVG(b."Floor") FROM cq_buildings_2021 AS b '
        'JOIN cq_amap_poi_2024 AS p ON ST_DWITHIN(b.geometry, p.geometry, 500) '
        'WHERE (p."name" LIKE \'%三甲%\' OR p."类型" LIKE \'%三甲%\') '
        'AND (p."name" LIKE \'%医院%\' OR p."类型" LIKE \'%医院%\') '
        'AND b."Floor" >= 10'
    )
    rewritten, corrections = apply_gemma_semantic_rewrites(
        "寻找距离所有三甲医院500米范围内的住宅建筑物，返回平均层高。",
        sql,
        context,
    )

    assert 'p."名称"' in rewritten
    assert 'p."name"' not in rewritten
    assert "ST_DWithin(b.geometry::geography, p.geometry::geography, 500)" in rewritten
    assert "semantic_column_alias" in corrections
    assert "semantic_st_dwithin_geography" in corrections


def test_gemma_semantic_rewrite_unknown_congestion_level_refuses():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_osm_roads_2021")
    rewritten, corrections = apply_gemma_semantic_rewrites(
        "给我提取道路的拥堵指数（congestion_level）。",
        "SELECT congestion_level FROM cq_osm_roads_2021",
        context,
    )

    assert rewritten == "SELECT 1"
    assert "semantic_unknown_column_refusal" in corrections


def test_gemma_semantic_rewrite_bare_poi_name_columns():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    name_col = "\u540d\u79f0"
    address_col = "\u5730\u5740"
    context = _cq_context("cq_amap_poi_2024")
    sql = (
        'SELECT "name", p.id, p."address" FROM cq_amap_poi_2024 AS p '
        'WHERE "name" LIKE \'%大学%\' AND ST_Intersects(p.shape, h.shape) LIMIT 20'
    )

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "list university POI names", sql, context
    )

    assert f'"{name_col}"' in rewritten
    assert f'p."{address_col}"' in rewritten
    assert 'p."ID"' in rewritten
    assert "p.geometry" in rewritten
    assert '"name"' not in rewritten
    assert "p.shape" not in rewritten
    assert "semantic_column_alias" in corrections


def test_gemma_semantic_rewrite_baidu_aoi_name_and_shape_columns():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    name_col = "\u540d\u79f0"
    context = _cq_context("cq_baidu_aoi_2024")
    sql = (
        'SELECT "name" FROM cq_baidu_aoi_2024 AS a '
        'WHERE ST_Intersects(a.geometry, h.shape)'
    )

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "list Baidu AOI names", sql, context
    )

    assert f'"{name_col}"' in rewritten
    assert '"name"' not in rewritten
    assert "a.shape" in rewritten
    assert "a.geometry" not in rewritten
    assert "semantic_column_alias" in corrections


def test_gemma_semantic_rewrite_cq_dltb_lowercase_schema():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_dltb")
    sql = (
        'SELECT COUNT(*) FROM cq_dltb AS d '
        'WHERE d."DLMC" = \'村庄\' AND ST_Intersects(d.geometry, p.geometry)'
    )

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "count POIs inside cq_dltb village parcels", sql, context
    )

    assert "d.dlmc" in rewritten
    assert 'd."DLMC"' not in rewritten
    assert "d.shape" in rewritten
    assert "d.geometry" not in rewritten
    assert "semantic_column_alias" in corrections


def test_gemma_semantic_rewrite_land_use_uppercase_schema():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_land_use_dltb")
    sql = (
        "SELECT bsm FROM cq_land_use_dltb AS l "
        "WHERE l.dlmc = '水田' AND l.tbmj > 50000 "
        'AND l."QSDWMC" LIKE \'%街道%\''
    )

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "list land-use parcel ids", sql, context
    )

    assert 'SELECT "BSM"' in rewritten
    assert 'l."DLMC"' in rewritten
    assert 'l."TBMJ"' in rewritten
    assert 'l."QSDWMC" LIKE' in rewritten
    assert 'l."QSDWMC""' not in rewritten
    assert "semantic_column_alias" in corrections


def test_gemma_semantic_rewrite_preserves_tbmj_field_area_sum():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_land_use_dltb")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "sum the TBMJ parcel area field",
        "SELECT SUM(TBMJ) FROM cq_land_use_dltb",
        context,
    )

    assert 'SUM("TBMJ")' in rewritten
    assert "ST_Area" not in rewritten
    assert "semantic_column_alias" in corrections
    assert "semantic_area_metric" not in corrections


def test_gemma_semantic_rewrite_unqualified_poi_address_column():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    address_col = "\u5730\u5740"
    context = _cq_context("cq_amap_poi_2024")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "preview amap poi name address type",
        'SELECT "\u540d\u79f0", "address", "\u7c7b\u578b" FROM cq_amap_poi_2024 LIMIT 5',
        context,
    )

    assert f'"{address_col}"' in rewritten
    assert '"address"' not in rewritten
    assert "semantic_column_alias" in corrections


def test_gemma_semantic_rewrite_baidu_aoi_score_column():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    score_col = "\u8bc4\u5206"
    context = _cq_context("cq_baidu_aoi_2024")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "highest scoring baidu aoi",
        'SELECT a.score FROM cq_baidu_aoi_2024 AS a ORDER BY a.score DESC LIMIT 5',
        context,
    )

    assert f'a."{score_col}"' in rewritten
    assert "a.score" not in rewritten
    assert "semantic_column_alias" in corrections


def test_gemma_semantic_rewrite_rounds_spatial_area_as_numeric():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_dltb")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "round spatial area to two decimals",
        "SELECT ROUND(SUM(ST_AREA(CAST(shape AS GEOGRAPHY))) / 10000, 2) FROM cq_dltb",
        context,
    )

    assert "::numeric, 2)" in rewritten
    assert "semantic_round_numeric_cast" in corrections


def test_gemma_semantic_rewrite_amap_to_cq_dltb_srid_transform():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_amap_poi_2024", "cq_dltb")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "count amap poi in cq_dltb village parcels",
        'SELECT COUNT(DISTINCT p."ID") FROM cq_amap_poi_2024 AS p '
        "JOIN cq_dltb AS d ON ST_INTERSECTS(p.geometry, d.shape) "
        "WHERE d.dlmc = '\u6751\u5e84'",
        context,
    )

    assert "ST_Intersects(ST_Transform(p.geometry, 4610), d.shape)" in rewritten
    assert "semantic_srid_transform" in corrections


def test_gemma_semantic_rewrite_cq_dltb_village_uses_dlmc():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_amap_poi_2024", "cq_dltb")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "village parcels",
        "SELECT p.\"\u540d\u79f0\" FROM cq_amap_poi_2024 AS p "
        "JOIN cq_dltb AS d ON ST_INTERSECTS(p.geometry, d.shape) "
        "WHERE d.dlbm = '\u6751\u5e84'",
        context,
    )

    assert "d.dlmc = '\u6751\u5e84'" in rewritten
    assert "d.dlbm = '\u6751\u5e84'" not in rewritten
    assert "semantic_literal_column_override" in corrections


def test_gemma_semantic_rewrite_land_use_join_area_qualifies_geometry():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_land_use_dltb", "cq_osm_roads_2021")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "real spatial area for water parcels intersecting roads",
        "SELECT SUM(ST_AREA(CAST(geometry AS GEOGRAPHY))) "
        "FROM cq_land_use_dltb AS t JOIN cq_osm_roads_2021 AS r "
        "ON ST_INTERSECTS(t.geometry, r.geometry) WHERE t.\"\u0044\u004c\u004d\u0043\" = '\u6c34\u7530'",
        context,
    )

    assert "CAST(t.geometry AS GEOGRAPHY)" in rewritten
    assert "CAST(geometry AS GEOGRAPHY)" not in rewritten
    assert "semantic_area_geometry_qualified" in corrections


def test_gemma_semantic_rewrite_unicom_commuting_alias_columns():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    age_col = "\u5e74\u9f84"
    pop_col = "\u6269\u6837\u540e\u4eba\u53e3"
    context = _cq_context("cq_unicom_commuting_2023")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "group by age and sum sampled population",
        'SELECT CASE WHEN "age" <= 17 THEN \'\u9752\u5c11\u5e74\' ELSE \'\u8001\u5e74\' END, '
        'SUM("sample_population"), SUM("\u6269\u6837\u540e\u603b\u4eba\u53e3") '
        "FROM cq_unicom_commuting_2023 GROUP BY 1",
        context,
    )

    assert f'"{age_col}"' in rewritten
    assert f'SUM("{pop_col}")' in rewritten
    assert '"age"' not in rewritten
    assert '"sample_population"' not in rewritten
    assert '"\u6269\u6837\u540e\u603b\u4eba\u53e3"' not in rewritten
    assert "semantic_column_alias" in corrections


def test_gemma_semantic_rewrite_population_million_unit_threshold():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_district_population")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "\u7edf\u8ba1\u6237\u7c4d\u603b\u4eba\u53e3\u8d85\u8fc7 100 \u4e07\u4eba\u7684\u533a\u53bf",
        'SELECT "\u533a\u5212\u540d\u79f0" FROM cq_district_population '
        'WHERE "\u6237\u7c4d\u603b\u4eba\u53e3_\u4e07\u4eba_" > 1000000',
        context,
    )

    assert '> 1000000' not in rewritten
    assert '> 100' in rewritten
    assert "semantic_unit_threshold" in corrections


def test_gemma_semantic_rewrite_legacy_roads_table_name():
    from data_agent.nl2sql_executor import apply_gemma_semantic_rewrites

    context = _cq_context("cq_osm_roads_2021")

    rewritten, corrections = apply_gemma_semantic_rewrites(
        "roads with tunnel",
        "SELECT name, fclass FROM cq_osm_roads WHERE tunnel = 'T'",
        context,
    )

    assert "cq_osm_roads_2021" in rewritten
    assert "cq_osm_roads " not in rewritten
    assert "semantic_table_normalized" in corrections


def test_generate_gemma_sql_retries_transient_completion_error(monkeypatch):
    from data_agent.nl2sql_executor import _generate_gemma_sql

    monkeypatch.setenv("NL2SQL_GEMMA_SQL_RETRIES", "2")
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("transient ollama timeout")
        return SimpleNamespace(
            choices=[SimpleNamespace(message={"content": "SELECT COUNT(*) FROM cq_osm_roads_2021"})]
        )

    fake_model = SimpleNamespace(
        model="ollama_chat/Gemma4:26b",
        _additional_args={"extra_body": {"think": False}, "timeout": 600},
    )

    with patch("data_agent.model_gateway.create_model", return_value=fake_model), \
         patch("data_agent.model_gateway.ModelRegistry.get_model_info", return_value={}), \
         patch("litellm.completion", side_effect=fake_completion), \
         patch("data_agent.nl2sql_executor.time.sleep") as mock_sleep:
        sql = _generate_gemma_sql("prompt", model_name="gemma4-26b-host9")

    assert sql == "SELECT COUNT(*) FROM cq_osm_roads_2021"
    assert len(calls) == 2
    assert calls[0]["extra_body"] == {"think": False}
    assert calls[0]["timeout"] == 600
    mock_sleep.assert_called_once_with(1)
