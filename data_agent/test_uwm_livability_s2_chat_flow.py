from pathlib import Path

from data_agent.mention_registry import build_registry
from data_agent.uwm.livability_s2.chat_flow import (
    action_response_value,
    build_s2_chat_draft,
    execute_s2_chat_draft,
    draft_map_update,
    format_confirmation_summary,
    format_evidence_gap_summary,
    format_parcel_location_summary,
    format_result_summary,
    format_run_audit_summary,
    is_s2_chat_message,
    is_s2_map_selection_request,
    is_s2_parcel_location_request,
    newly_covered_map_update,
    parcel_location_map_update,
    parcel_selection_map_update,
    result_map_update,
    s2_followup_radius,
    s2_map_selection_prompt_template,
)
from data_agent.uwm.livability_s2.scenario_service import S2ScenarioService


PRODUCT_DIR = (
    Path(__file__).resolve().parents[1]
    / "data/uwm_public_proxy/chongqing_central/uwm_livability_s2_fulu"
)
PROMPT = "@S2 帮我判断地块 parcel_79bb3178da33949459fc 改成公共服务用地并新增养老服务站是否同意"


def test_s2_mention_is_registered_and_detected():
    assert is_s2_chat_message(PROMPT)
    assert is_s2_chat_message("@宜居性S2 在地图上选择地块")
    target = next(item for item in build_registry("admin", "admin") if item["handle"] == "S2")
    assert target["pipeline"] == "S2"


def test_s2_map_selection_and_radius_followup_are_deterministic():
    request = "@S2 在地图上选择地块，改成公共服务用地并新增养老服务站是否同意"
    assert is_s2_map_selection_request(request)
    template = s2_map_selection_prompt_template(request)
    assert template == "@S2 地块 {parcel_id}，改成公共服务用地并新增养老服务站是否同意"
    assert s2_followup_radius("如果改成300米呢？") == "300"
    assert s2_followup_radius("换成800米情景重新算") == "800"
    assert s2_followup_radius("这里有300米道路") == ""

    selection_map = parcel_selection_map_update(S2ScenarioService(PRODUCT_DIR))
    assert selection_map["metadata"]["interaction_mode"] == "s2_parcel_selection"
    assert selection_map["metadata"]["parcel_count"] == 2216
    assert len(selection_map["layers"][0]["geojsonData"]["features"]) == 2216


def test_s2_parcel_location_is_a_fast_map_only_command_with_or_without_mention():
    service = S2ScenarioService(PRODUCT_DIR)
    for prompt in [
        "@S2 帮我在地图上加载地块：parcel_79bb3178da33949459fc",
        "帮我在地图上加载地块：parcel_79bb3178da33949459fc",
        "请定位地块 parcel_79bb3178da33949459fc",
    ]:
        assert is_s2_parcel_location_request(prompt)
    assert not is_s2_parcel_location_request(PROMPT)

    parcel = service.parcel_detail("parcel_79bb3178da33949459fc")["parcel"]
    map_update = parcel_location_map_update(parcel)
    assert map_update["metadata"] == {
        "view_mode": "s2_parcel_location",
        "selected_parcel_id": "parcel_79bb3178da33949459fc",
        "evidence_only": True,
    }
    assert map_update["zoom"] == 15
    assert map_update["layers"][0]["style"]["fillColor"] == "#fbbf24"
    assert [layer["name"] for layer in map_update["layers"]] == [
        "S2 目标真实地块",
        "S2 目标地块位置标记",
    ]
    assert len(map_update["layers"][0]["geojsonData"]["features"]) == 1
    assert map_update["layers"][1]["style"]["radius"] == 10
    assert map_update["layers"][1]["geojsonData"]["features"][0]["geometry"]["type"] == "Point"
    summary = format_parcel_location_summary(parcel)
    assert "已在地图上加载真实地块" in summary
    assert "宅基地（村居住用地）" in summary
    assert "没有启动用途变更、设施覆盖或UWM反事实推演" in summary
    assert f"@S2 帮我判断地块 parcel_79bb3178da33949459fc" in summary


def test_chainlit_action_response_reads_nested_payload_value():
    assert action_response_value({"payload": {"value": "500"}, "label": "500米情景"}) == "500"
    assert action_response_value({"value": "confirm"}) == "confirm"
    assert action_response_value(None) == ""


def test_exact_user_prompt_runs_real_s2_instead_of_world_model_gee():
    service = S2ScenarioService(PRODUCT_DIR)
    draft = build_s2_chat_draft(PROMPT, service)

    assert draft["blockers"] == []
    assert draft["parcel_id"] == "parcel_79bb3178da33949459fc"
    assert draft["target_land_use_class"] == "village_public_service_land"
    assert draft["action_type"] == "add_facility"
    assert draft["facility_class"] == "eldercare.station"
    assert draft["planning_project"]["project_name"] == "养老服务站"
    confirmation = format_confirmation_summary(draft, "500")
    assert "村庄住宅用地" in confirmation
    assert "村庄公共服务用地" in confirmation
    assert "养老服务站" in confirmation
    draft_map = draft_map_update(draft)
    assert 29.61 < draft_map["center"][0] < 29.63
    assert 106.12 < draft_map["center"][1] < 106.14
    assert draft_map["zoom"] == 15
    assert draft_map["layers"][0]["style"]["color"] == "#f59e0b"
    assert draft_map["layers"][0]["style"]["fillColor"] == "#fbbf24"

    run = execute_s2_chat_draft(
        draft,
        service=service,
        actor_id="admin",
        service_radius_m=500,
    )
    assessment = run["business_assessment"]
    assert assessment["recommendation"] == "conditional_agree"
    assert assessment["intervention"]["covered_parcel_count"] == 125
    assert assessment["coverage_delta_percentage_points"] == 18.910741
    result_summary = format_result_summary(run)
    assert "有条件同意" in result_summary
    assert "GIS确定性覆盖计算" in result_summary
    assert "UWM反事实传播" in result_summary
    assert "不是人口覆盖率" in result_summary
    assert "住宅用地转公共服务用地仍需规划专业复核" in result_summary
    assert "空间传播信号不是新增覆盖地块数量" in result_summary
    result_map = result_map_update(run)
    assert len(result_map["layers"]) == 8
    assert result_map["center"] == draft_map["center"]
    assert result_map["zoom"] == 15
    styles = {layer["name"]: layer["style"] for layer in result_map["layers"]}
    assert styles["S2 目标真实地块"]["fillColor"] == "#fbbf24"
    assert styles["S2 基线服务范围"]["color"] == "#475569"
    assert styles["S2 干预服务范围"]["color"] == "#ea580c"
    assert styles["S2 基线服务范围"]["color"] != styles["S2 干预服务范围"]["color"]
    assert styles["S2 新增覆盖地块"]["fillColor"] == "#22c55e"
    assert styles["S2 失去覆盖地块"]["fillColor"] == "#ef4444"
    assert styles["S2 规划资源证据"]["fillColor"] == "#c084fc"
    assert styles["S2 设施证据"]["fillColor"] == "#14b8a6"
    focused_map = newly_covered_map_update(run)
    assert [layer["name"] for layer in focused_map["layers"]] == [
        "S2 目标真实地块",
        "S2 干预服务范围",
        "S2 新增覆盖地块",
    ]
    focused_styles = {layer["name"]: layer["style"] for layer in focused_map["layers"]}
    assert focused_styles["S2 目标真实地块"]["fillColor"] == "#fbbf24"
    assert focused_styles["S2 干预服务范围"]["fillColor"] == "#fb923c"
    assert focused_styles["S2 新增覆盖地块"]["fillColor"] == "#22c55e"
    assert "S2证据缺口" in format_evidence_gap_summary(run)
    assert "文字位置证据" in format_evidence_gap_summary(run)
    assert "不是人口覆盖率" in format_evidence_gap_summary(run)
    assert run["run_id"] in format_run_audit_summary(run)
    assert run["snapshot_digest"] in format_run_audit_summary(run)
    audit_summary = format_run_audit_summary(run)
    assert "地理空间世界模型归因" in audit_summary
    assert "action_conditioned_scenario_state" in audit_summary
    assert "覆盖代理与t2消息混同" in audit_summary
    assert "经验干预效果" in audit_summary


def test_land_use_only_prompt_fails_closed_before_chat_rollout():
    draft = build_s2_chat_draft(
        "@S2 把 parcel_79bb3178da33949459fc 改成公共服务用地并判断是否同意",
        S2ScenarioService(PRODUCT_DIR),
    )
    assert "facility_action_required_for_coverage_decision" in draft["blockers"]


def test_app_intercepts_s2_before_custom_mention_and_world_model_routing():
    source = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
    locate_intercept = source.index("if is_s2_parcel_location_request(user_text):", source.index("# Construct User Prompt"))
    intercept = source.index("if is_s2_chat_message(user_text):")
    custom_mention = source.index("# --- Custom Skill @mention detection")
    assert locate_intercept < intercept
    assert intercept < custom_mention
    assert "await _handle_s2_parcel_location_message(user_text, user_id)" in source
    assert '"pipeline_name": "S2真实地块快速定位"' in source
    assert "await _handle_s2_chat_message(user_text, user_id)" in source
    assert '@cl.action_callback("s2_show_new_coverage")' in source
    assert '@cl.action_callback("s2_show_evidence_gaps")' in source
    assert '@cl.action_callback("s2_show_run_audit")' in source
    assert "await _handle_s2_radius_followup(user_text, user_id, s2_radius_value)" in source
    assert '"s2_parcel_selection"' in source
