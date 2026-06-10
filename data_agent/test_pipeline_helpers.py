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


def test_clean_cot_leakage_removes_optimization_summary_reasoning_trace():
    from data_agent.pipeline_helpers import clean_cot_leakage

    leaked = (
        "已成功结项。The user wants to see the results of the "
        "\"Farmland Spatial Layout Optimization Analysis\". The previous steps "
        "have successfully completed.\n"
        "The interactive map has been generated. Now I need to present the "
        "final report to the user.\n"
        "Key info to communicate:\n"
        "Title: 《斑竹村耕地空间布局优化决策报告》\n"
        "Section 1: 执行摘要\n"
        "Check against constraints: Is it Scenario A? Yes.\n"
        "# 《斑竹村耕地空间布局优化决策报告》\n"
        "📌 执行摘要 (Executive Summary)\n"
        "针对斑竹村现有耕地空间分布进行优化分析。\n"
        "🔬 分析方法 (Analysis Method)\n"
        "核心算法：采用深度强化学习模型。\n"
    )

    cleaned = clean_cot_leakage(leaked)

    assert cleaned.startswith("# 《斑竹村耕地空间布局优化决策报告》")
    assert "The user wants" not in cleaned
    assert "The previous steps" not in cleaned
    assert "The interactive map has been generated" not in cleaned
    assert "Now I need" not in cleaned
    assert "Key info to communicate" not in cleaned
    assert "Title:" not in cleaned
    assert "Section 1:" not in cleaned
    assert "Check against constraints" not in cleaned
    assert "分析方法" in cleaned


def test_format_drl_optimization_result_for_chat_uses_tool_metrics():
    from data_agent.pipeline_helpers import format_drl_optimization_result_for_chat

    response = {
        "summary": (
            "Optimization Complete (v7).\n"
            "Conversions: 200\n"
            "Pairs: 0\n"
            "Net Change: -130\n"
            "Result SHP: /app/data_agent/uploads/admin/optimized_data_demo.shp\n"
            "Visualization: /app/data_agent/uploads/admin/optimized_map_demo.png"
        ),
        "optimized_data_path": "/app/data_agent/uploads/admin/optimized_data_demo.shp",
        "output_path": "/app/data_agent/uploads/admin/optimized_map_demo.png",
    }

    text = format_drl_optimization_result_for_chat(
        response,
        artifacts=["/app/data_agent/uploads/admin/interactive_map_demo.html"],
    )

    assert "Conversions: 200" in text
    assert "Pairs: 0（本次运行未形成成对置换）" in text
    assert "Net Change: -130" in text
    assert "optimized_data_demo.shp" in text
    assert "optimized_map_demo.png" in text
    assert "interactive_map_demo.html" in text
    assert "成对置换成功" not in text
    assert "完美面积守恒" not in text
    assert "边界移动" not in text


def test_should_force_drl_optimization_for_farmland_layout_request():
    from data_agent.pipeline_helpers import should_force_drl_optimization

    assert should_force_drl_optimization("基于斑竹村10000数据进行耕地空间布局优化分析")
    assert should_force_drl_optimization("请做 farmland land use optimization")
    assert not should_force_drl_optimization("统计重庆道路中桥梁总长度")


def test_find_drl_optimization_input_path_prefers_requested_upload(tmp_path):
    from unittest.mock import patch

    from data_agent.pipeline_helpers import find_drl_optimization_input_path

    upload_dir = tmp_path / "uploads" / "admin"
    source_dir = upload_dir / "斑竹村10000"
    source_dir.mkdir(parents=True)
    source = source_dir / "斑竹村10000.shp"
    source.write_text("dummy", encoding="utf-8")

    lisa = upload_dir / "lisa_cluster_a722ab80.shp"
    lisa.write_text("dummy", encoding="utf-8")
    enhanced = upload_dir / "enhanced_89c15731.shp"
    enhanced.write_text("dummy", encoding="utf-8")

    prompt = "基于斑竹村10000数据进行耕地空间布局优化分析"
    response_text = f"交付物: {lisa}"

    with patch("data_agent.user_context.get_user_upload_dir", return_value=str(upload_dir)):
        selected = find_drl_optimization_input_path(prompt, response_text=response_text)

    assert selected == str(source)
