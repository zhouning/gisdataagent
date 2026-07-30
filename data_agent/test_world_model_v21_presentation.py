import json


def test_parse_world_model_v21_tool_response_from_nested_result():
    from data_agent.world_model_v21_presentation import parse_world_model_v21_tool_response

    payload = {
        "status": "ok",
        "version": "2.1.0",
        "summary": {"n_selected": 50},
    }

    assert parse_world_model_v21_tool_response({"result": json.dumps(payload)}) == payload


def test_parse_world_model_v21_tool_response_keeps_pipeline_wrapper():
    from data_agent.world_model_v21_presentation import parse_world_model_v21_tool_response

    payload = {
        "status": "ok",
        "mode": "pipeline_a_to_d",
        "steps": [{"step": "prepare", "status": "skipped_reused"}],
        "plan_result": {
            "status": "ok",
            "mode": "tool4_mpc",
            "summary": {"steps_run": 100},
        },
    }

    assert parse_world_model_v21_tool_response({"result": json.dumps(payload)}) == payload


def test_parse_structured_tool_response_unwraps_adk_result():
    from data_agent.world_model_v21_presentation import parse_structured_tool_response

    payload = {"hard_constraint_passed": True, "next_action": "commit_verified_episode"}

    assert parse_structured_tool_response({"result": json.dumps(payload)}) == payload


def test_format_world_model_v21_result_uses_tool_n_selected_not_top_k():
    from data_agent.world_model_v21_presentation import format_world_model_v21_result_for_chat

    result = {
        "status": "ok",
        "version": "2.1.0",
        "mode": "tool4_mpc",
        "env_kind": "restoration",
        "summary": {
            "steps_run": 50,
            "n_blocks": 562,
            "n_selected": 50,
            "total_reward": 230.75136300693933,
        },
        "artifacts": {
            "summary_json": "mpc_summary.json",
            "land_use_npy": "mpc_land_use.npy",
            "map_layer": "world_model_v21/run/restoration_mpc_units.geojson",
        },
        "map_update": {
            "layers": [{"name": "World Model v2.1 optimized"}],
        },
    }

    text = format_world_model_v21_result_for_chat(
        result,
        tool_args={"horizon": "2", "top_k": "5"},
    )

    lines = set(text.splitlines())
    assert "- 每步候选行动数：5" in lines
    assert "- 选中决策单元：50" in lines
    assert "- 选中决策单元：5" not in lines
    assert "restoration_mpc_units.geojson" in text


def test_format_world_model_v21_county_result_uses_swaps_and_land_use_legend():
    from data_agent.world_model_v21_presentation import format_world_model_v21_result_for_chat

    result = {
        "status": "ok",
        "version": "2.1.0",
        "mode": "tool4_mpc",
        "env_kind": "county",
        "summary": {
            "steps_run": 100,
            "swaps_completed": 427,
            "n_selected": None,
            "n_blocks": 2640,
            "slope_change_pct": -1.7530763329854409,
            "cont_change": 0.012494941319304065,
            "baimu_area_change_ha": -483.9414482830465,
            "total_reward": 71.78351430451329,
        },
        "artifacts": {
            "summary_json": "mpc_summary.json",
            "land_use_npy": "mpc_land_use.npy",
            "optimized_shp": "optimized_dltb.shp",
            "map_layer": "world_model_v21/run/optimized_dltb.fgb",
        },
        "map_update": {
            "layers": [{"name": "World Model v2.1 optimized", "type": "fgb"}],
        },
    }

    text = format_world_model_v21_result_for_chat(
        result,
        tool_args={"horizon": "2", "top_k": "5"},
    )
    lines = set(text.splitlines())

    assert "- 完成双向置换：427 对" in lines
    assert not any(line.startswith("- 选中决策单元：") for line in lines)
    assert "- 平均坡度变化：-1.7531%" in lines
    assert "灰色为保持不变" in text
    assert "红色为耕地 → 林地" in text
    assert "绿色为林地 → 耕地" in text


def test_format_world_model_v21_pipeline_result_shows_abcd_steps():
    from data_agent.world_model_v21_presentation import (
        format_world_model_v21_progress_for_chat,
        format_world_model_v21_result_for_chat,
    )

    result = {
        "status": "ok",
        "version": "2.1.0",
        "mode": "pipeline_a_to_d",
        "steps": [
            {"step": "prepare", "status": "skipped_reused"},
            {"step": "sample", "status": "skipped_reused"},
            {"step": "train", "status": "skipped_reused"},
            {"step": "plan", "status": "ok"},
        ],
        "plan_result": {
            "status": "ok",
            "version": "2.1.0",
            "mode": "tool4_mpc",
            "env_kind": "county",
            "prepared_dir": "/app/dongxing-runs/prepared",
            "ensemble_dir": "/app/dongxing-runs/prepared/ensemble_seed0",
            "summary": {
                "steps_run": 100,
                "swaps_completed": 427,
                "n_blocks": 2640,
                "n_parcels": 53004,
                "total_reward": 71.78,
            },
            "artifacts": {"map_layer": "world_model_v21/run/optimized_dltb.fgb"},
            "map_update": {
                "layers": [{"name": "World Model v2.1 优化结果", "type": "fgb"}],
            },
        },
    }

    text = format_world_model_v21_result_for_chat(
        result,
        tool_args={"horizon": "1", "top_k": "1"},
    )

    assert "- MPC 前瞻步长：1" in text
    assert "- 每步候选行动数：1" in text
    assert "- 图斑数：53004" in text
    assert "- A / 数据准备：已复用（未重复执行）" in text
    assert "- B / 样本生成：已复用（未重复执行）" in text
    assert "- C / 状态转移模型训练：已复用（未重复执行）" in text
    assert "- D / MPC 规划执行：完成" in text
    assert text.startswith("### 规划结果尚未完成审计")
    assert "未捕获完整函数调用轨迹，请查看运行日志。" in text
    assert "/app/dongxing-runs" not in text

    progress = format_world_model_v21_progress_for_chat(result, "@WorldModelV21 (直接调用)")
    assert "**县域耕地规划 Agent** · Gemma 4 + Google ADK 受控自主闭环" in progress
    assert "✓ A / 数据准备：已复用（未重复执行）" in progress
    assert "✓ D / MPC 规划执行：完成" in progress


def test_format_world_model_v21_result_shows_verified_agent_loop():
    from data_agent.world_model_v21_presentation import (
        format_world_model_v21_progress_for_chat,
        format_world_model_v21_result_for_chat,
    )

    result = {
        "status": "ok",
        "version": "2.1.0",
        "mode": "tool4_mpc",
        "env_kind": "county",
        "summary": {
            "cultivated_area_change_ha": 0.2116,
            "slope_change_pct": -0.8154,
            "cont_change": 0.0284,
        },
        "artifacts": {},
    }
    status = {
        "paper9": {"package_version": "0.3.3", "algorithm_version": "2.2.3"},
        "finals": {"version_compatible": True},
    }
    audit = {
        "hard_constraint_passed": True,
        "next_action": "commit_verified_episode",
        "audit_path": "/run/paper9_agent_audit.json",
    }
    commit = {
        "status": "committed",
        "episode": {"episode_id": "episode-1"},
    }
    trace = [
        {"tool_name": "world_model_v21_status", "duration_s": 0.004},
        {"tool_name": "paper9_inspect_resources", "duration_s": 0.2},
        {"tool_name": "paper9_recall_verified_episodes", "duration_s": 0.1},
        {"tool_name": "world_model_v21_plan", "duration_s": 88.6},
        {"tool_name": "paper9_audit_run", "duration_s": 1.3},
        {"tool_name": "paper9_commit_verified_episode", "duration_s": 0.1},
    ]

    text = format_world_model_v21_result_for_chat(
        result,
        status_result=status,
        audit_result=audit,
        commit_result=commit,
        tool_trace=trace,
        total_duration_s=96.8,
    )
    progress = format_world_model_v21_progress_for_chat(
        result,
        audit_result=audit,
        commit_result=commit,
        tool_trace=trace,
        total_duration_s=96.8,
    )

    assert text.startswith("### 县域耕地受控规划完成")
    assert "**Gemma 4 + Google ADK** · 6 次原生函数调用" in text
    assert "总用时 96.8 秒" in text
    assert "MPC 规划 88.6 秒" in text
    assert "审计与经验提交 1.4 秒" in text
    assert "`world_model_v21_status` · 0.004 秒" in text
    assert "版本：适配器 2.1.0 · 引擎包 0.3.3 · 算法 2.2.3" in text
    assert "- 耕地面积变化：0.2116 ha" in text
    assert "- 硬约束校验：通过" in text
    assert "- 经验编号：episode-1" in text
    assert "**观察版本与运行状态** → 版本兼容" in text
    assert "**根据审计结果决定是否写入经验** → 已写入已验证经验库" in text
    assert "Paper9 Package:" not in text
    assert "Prepared Dir:" not in text
    assert "原生函数调用：6 次" in progress
    assert "总用时：96.8 秒" in progress
    assert "硬约束审计：通过" in progress
    assert "已验证经验库：已写入" in progress


def test_format_world_model_v21_result_fails_closed_after_bad_audit():
    from data_agent.world_model_v21_presentation import format_world_model_v21_result_for_chat

    text = format_world_model_v21_result_for_chat(
        {
            "status": "ok",
            "version": "2.1.0",
            "mode": "tool4_mpc",
            "env_kind": "county",
            "summary": {},
            "artifacts": {},
        },
        audit_result={
            "hard_constraint_passed": False,
            "next_action": "stop_and_request_human_review",
            "failure_reasons": ["cultivated area below floor"],
        },
    )

    assert text.startswith("### 县域耕地规划已停止")
    assert "- 硬约束校验：未通过" in text
    assert "cultivated area below floor" in text


def test_format_world_model_v21_result_does_not_claim_completion_before_commit():
    from data_agent.world_model_v21_presentation import format_world_model_v21_result_for_chat

    text = format_world_model_v21_result_for_chat(
        {
            "status": "ok",
            "version": "2.1.0",
            "mode": "tool4_mpc",
            "env_kind": "county",
            "summary": {},
            "artifacts": {},
        },
        audit_result={
            "hard_constraint_passed": True,
            "next_action": "commit_verified_episode",
        },
        tool_trace=["world_model_v21_status", "paper9_audit_run"],
    )

    assert text.startswith("### 规划已通过审计，尚未写入经验")
    assert "- 已验证经验库：未写入" in text
