import json


def test_parse_world_model_v21_tool_response_from_nested_result():
    from data_agent.world_model_v21_presentation import parse_world_model_v21_tool_response

    payload = {
        "status": "ok",
        "version": "2.1.0",
        "summary": {"n_selected": 50},
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
    assert "OPT_DLBM" in text
    assert "黄色代表 011" in text
    assert "绿色代表 031" in text
