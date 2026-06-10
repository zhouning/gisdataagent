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
    assert "- Top K: 5" in text
    assert "- N Selected: 50" in lines
    assert "- N Selected: 5" not in lines
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

    assert "- Swaps Completed: 427" in lines
    assert not any(line.startswith("- N Selected:") for line in lines)
    assert "- Slope Change: -1.7531%" in lines
    assert "CHG_FLAG" in text
    assert "灰色代表保持不变" in text
    assert "红色代表耕地 -> 林地" in text
    assert "绿色代表林地 -> 耕地" in text


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

    assert "- Mode: pipeline_a_to_d; plan=tool4_mpc" in text
    assert "- Prepared Dir: /app/dongxing-runs/prepared" in text
    assert "- Ensemble Dir: /app/dongxing-runs/prepared/ensemble_seed0" in text
    assert "- Horizon: 1（MPC 前瞻步长）" in text
    assert "- Top K: 1（每步候选动作数）" in text
    assert "- N Parcels: 53004" in text
    assert "- A / Tool 1 Prepare: skipped_reused" in text
    assert "- B / Tool 2 Sample: skipped_reused" in text
    assert "- C / Tool 3 Train: skipped_reused" in text
    assert "- D / Tool 4 Plan: ok" in text
    assert "world_model_v21_status -> world_model_v21_pipeline" in text

    progress = format_world_model_v21_progress_for_chat(result, "@WorldModelV21 (直接调用)")
    assert "**@WorldModelV21 (直接调用)** A/B/C/D 4 阶段完成" in progress
    assert "✓ A / Tool 1 Prepare: skipped_reused" in progress
    assert "✓ D / Tool 4 Plan: ok" in progress
