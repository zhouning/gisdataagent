import json


def test_extract_map_update_from_direct_json_string():
    from data_agent.pipeline_helpers import extract_map_update_from_tool_response

    map_update = {
        "layers": [{"name": "demo", "geojson": "demo.geojson"}],
        "center": [37.315, -82.09],
        "zoom": 9,
    }

    assert extract_map_update_from_tool_response(json.dumps({"map_update": map_update})) == map_update


def test_extract_map_update_from_nested_result_json_string():
    from data_agent.pipeline_helpers import extract_map_update_from_tool_response

    map_update = {
        "layers": [{"name": "World Model v2.1 optimized", "geojson": "world_model_v21/run/restoration_mpc_units.geojson"}],
    }
    response = {"result": json.dumps({"status": "ok", "map_update": map_update})}

    assert extract_map_update_from_tool_response(response) == map_update


def test_extract_map_update_from_pipeline_plan_result():
    from data_agent.pipeline_helpers import extract_map_update_from_tool_response

    map_update = {
        "layers": [{"name": "World Model v2.1 优化结果", "fgb": "world_model_v21/run/optimized_dltb.fgb"}],
    }
    response = {
        "status": "ok",
        "mode": "pipeline_a_to_d",
        "plan_result": {"status": "ok", "map_update": map_update},
    }

    assert extract_map_update_from_tool_response(response) == map_update


def test_extract_map_update_returns_none_for_invalid_payloads():
    from data_agent.pipeline_helpers import extract_map_update_from_tool_response

    assert extract_map_update_from_tool_response("not json") is None
    assert extract_map_update_from_tool_response({"map_update": {"layers": "bad"}}) is None
    assert extract_map_update_from_tool_response({"result": {"status": "ok"}}) is None


def test_clean_cot_leakage_removes_world_model_planning_trace():
    from data_agent.pipeline_helpers import clean_cot_leakage

    leaked = (
        "The user wants to perform two main actions:\n"
        "Check the status of World Model v2.1.\n"
        "Plan:\n"
        "Step 1: Call world_model_v21_status.\n"
        "Ah, I made a typo in env_kind.\n"
        "Corrected parameters:\n"
        "env_kind: \"restoration\"\n"
        "规划已完成。以下是本次运行结果的简要总结：\n"
        "状态 (Status): ok\n"
        "工具调用轨迹 world_model_v21_status -> world_model_v21_plan"
    )

    cleaned = clean_cot_leakage(leaked)

    assert cleaned.startswith("规划已完成")
    assert "The user wants" not in cleaned
    assert "I made a typo" not in cleaned
    assert "env_kind:" not in cleaned
    assert "状态 (Status): ok" in cleaned


def test_clean_cot_leakage_removes_memory_recall_reasoning_trace():
    from data_agent.pipeline_helpers import clean_cot_leakage

    leaked = (
        "The user wants to retrieve a memory with the keyword \"Gemma4空间演示\". "
        "I should use the recall_memories tool.\n"
        "Parameters for recall_memories:\n"
        "keyword: \"Gemma4空间演示\"\n"
        "memory_type: (optional, I'll leave it empty to search all)\n"
        "The user provided context that includes a summary of what was just saved.\n"
        "已检索到与关键词 “Gemma4空间演示” 相关的 3 条记忆：\n"
        "1. 核心配置与上下文 (Custom)\n"
        "键名: Gemma4空间演示\n"
        "更新时间: 2026-06-10 10:38:12\n"
    )

    cleaned = clean_cot_leakage(leaked)

    assert cleaned.startswith("已检索到")
    assert "The user wants" not in cleaned
    assert "I should use" not in cleaned
    assert "Parameters for" not in cleaned
    assert "keyword:" not in cleaned
    assert "memory_type:" not in cleaned
    assert "核心配置与上下文" in cleaned


def test_clean_cot_leakage_does_not_return_pure_reasoning_trace():
    from data_agent.pipeline_helpers import clean_cot_leakage

    leaked = (
        "The user wants to retrieve a memory with the keyword \"Gemma4空间演示\". "
        "I should use the recall_memories tool.\n"
        "Parameters for recall_memories:\n"
        "keyword: \"Gemma4空间演示\"\n"
    )

    cleaned = clean_cot_leakage(leaked)

    assert "The user wants" not in cleaned
    assert "I should use" not in cleaned
    assert cleaned == ""
