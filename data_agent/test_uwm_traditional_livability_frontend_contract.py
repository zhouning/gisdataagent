from pathlib import Path

from data_agent.test_traditional_livability_s6_semantics import (
    authoritative_dictionary_fixture,
    human_selected_candidate,
)
from data_agent.uwm.traditional_livability_s6_semantics import (
    resolve_s6_facility_semantics,
    validate_human_confirmation,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PANEL = ROOT / "frontend" / "src" / "components" / "DataPanel.tsx"
TRADITIONAL_TAB = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "datapanel"
    / "TraditionalLivabilityTab.tsx"
)
S7_PANEL = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "datapanel"
    / "TraditionalLivabilityS7Panel.tsx"
)
S6_PANEL = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "datapanel"
    / "TraditionalLivabilityS6Panel.tsx"
)
S4_PANEL = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "datapanel"
    / "TraditionalLivabilityS4Panel.tsx"
)
MAP_PANEL = ROOT / "frontend" / "src" / "components" / "MapPanel.tsx"


def test_traditional_livability_tab_is_registered_in_datapanel():
    text = DATA_PANEL.read_text(encoding="utf-8")

    assert "TraditionalLivabilityTab" in text
    assert "traditional_livability" in text
    assert "城市宜居性分析（传统方法）" in text
    assert (
        "{activeTab === 'traditional_livability' && <TraditionalLivabilityTab />}"
        in text
    )
    assert text.index("{ key: 'traditional_livability'") < text.index(
        "{ key: 'worldmodel', label: '世界模型'"
    )


def test_traditional_livability_tab_uses_static_analysis_api_contract():
    text = TRADITIONAL_TAB.read_text(encoding="utf-8")

    assert "/api/uwm/traditional-livability" in text
    assert "/api/uwm/traditional-livability/map" in text
    assert "/api/map/pending" in text
    assert "__handleMapUpdate" in text
    assert "loadTraditionalAnalysis" in text
    assert "pushTraditionalLayerToMap" in text
    assert "城市宜居性分析（传统方法）" in text
    assert "综合宜居性得分" in text
    assert "静态优先级排名" in text
    assert "指标维度" in text
    assert "数据基础" in text
    assert "能力边界" in text
    assert "反事实预测" in text
    assert "规划器" in text
    assert "/api/uwm/traditional-livability/s1" in text
    assert "S1 设施供需评估" in text
    assert "每万人设施数" in text
    assert "权威 FP/FPP 标准未提供" in text
    assert "采样库存" in text
    assert "production_blockers" in text
    assert "not_assessed" in text
    assert "not_assessed: '未评估'" in text
    assert "not_assessed: '不达标'" not in text

    forbidden_static_tab_strings = [
        "counterfactual_state_delta",
        "predicted_delta",
        "rollout",
        "action_conditioned_future_state",
    ]
    for item in forbidden_static_tab_strings:
        assert item not in text


def test_traditional_livability_s7_panel_uses_distance_proxy_contract():
    text = S7_PANEL.read_text(encoding="utf-8")

    for required in [
        "/api/uwm/traditional-livability/s7",
        "福禄镇和平村与斑竹村",
        "住宅用地面积代理",
        "距离代理覆盖范围",
        "候选过滤漏斗",
        "新增覆盖面积",
        "重复覆盖面积",
        "candidate_policy_no_eligible_parcels",
        "__handleMapUpdate",
    ]:
        assert required in text
    assert "步行服务区" not in text
    assert "15分钟步行" not in text


def test_traditional_livability_s6_panel_uses_evidence_bounded_contract():
    panel = S6_PANEL.read_text(encoding="utf-8")
    tab = TRADITIONAL_TAB.read_text(encoding="utf-8")
    map_panel = MAP_PANEL.read_text(encoding="utf-8")

    assert "TraditionalLivabilityS6Panel" in tab
    for required in [
        "/api/uwm/traditional-livability/s6/resources",
        "/api/uwm/traditional-livability/s6/dictionary",
        "/api/uwm/traditional-livability/s6/analyze",
        "S6 超范围设施评估",
        "地图点选",
        "规划地块",
        "设施名称",
        "原始类型",
        "用途说明",
        "语义候选",
        "人工确认",
        "权威字典或规则不可用",
        "150 米空间初筛范围",
        "规划资源命中",
        "现状设施命中",
        "语义未解析对象",
        "潜在冲突、需人工复核",
        "采样库存",
        "max_claim_level",
        "production_blockers",
        "__handleMapUpdate",
        "traditional-livability-s6-request-point-selection",
        "traditional-livability-s6-point-selected",
    ]:
        assert required in panel

    assert "traditional-livability-s6-request-point-selection" in map_panel
    assert "traditional-livability-s6-point-selected" in map_panel
    assert "annotationMode || measureMode || drawMode" in map_panel
    assert "input_mode: inputMode === 'parcel' ? 'planning_parcel' : 'point'" in panel
    assert "confirmed_standard_class_id: selectedCandidateId || undefined" in panel
    assert "human_confirmation: confirmation" in panel
    assert "buildS6Confirmation" in panel
    assert "buildHumanSelectedCandidate" in panel
    assert "selected_candidate: selectedCandidateAudit" in panel
    assert "authority_level: 'human_confirmation'" in panel
    assert "match_method: 'human_selected'" in panel
    assert "confidence: 'human_confirmed'" in panel
    assert "human_confirmation_required: false" in panel
    assert "human_confirmed: true" in panel
    assert "evidence: [{ evidence_type: 'reviewer_reason', reason: reviewerReason }]" in panel
    assert "Promise.all" not in panel
    assert "resourcesSettled" in panel
    assert "authoritySettled" in panel
    assert "stale" in panel
    assert "traditional-livability-s6-point-selection-cancelled" in panel
    assert "traditional-livability-s6-point-selection-cancelled" in map_panel
    assert "map.off('click', s6PointSelectionHandlerRef.current)" in map_panel
    assert "reason === 'map_unavailable'" in map_panel
    assert "reason === 'request_rejected_active_mode'" in map_panel
    assert "geojson.unresolved_planning_resources" in panel
    assert "geojson.unresolved_current_facilities" in panel
    assert "unresolved_object_kind: kind" in panel
    assert "geojson.unresolved_planning_resources, 'planning_resource'" in panel
    assert "geojson.unresolved_current_facilities, 'current_facility'" in panel
    assert "语义未解析规划资源" in panel
    assert "语义未解析现状设施" in panel

    for forbidden in ["禁止建设", "审批通过", "法定退界", "安全距离", "步行服务区"]:
        assert forbidden not in panel


def test_traditional_livability_s4_panel_uses_project_alignment_contract():
    panel = S4_PANEL.read_text(encoding="utf-8")
    tab = TRADITIONAL_TAB.read_text(encoding="utf-8")

    assert "TraditionalLivabilityS4Panel" in tab
    for required in [
        "/api/uwm/traditional-livability/s4/resources",
        "/api/uwm/traditional-livability/s4/analyze",
        "S4 项目宜居性评估",
        "项目名称",
        "项目说明",
        "规划地块",
        "新增业态",
        "删除业态",
        "业态名称",
        "原始业态类型",
        "用途说明",
        "GFA",
        "GFA 证据构成",
        "地块直接关系",
        "150 米空间初筛",
        "需求未评估",
        "初步对齐分析，需人工复核",
        "语义证据",
        "S1 需求证据",
        "S6 空间证据",
        "project_blockers",
        "max_claim",
        "__handleMapUpdate",
    ]:
        assert required in panel

    assert "clientKey" in panel
    assert "crypto.randomUUID" in panel
    assert "Number.isFinite(gfa) && gfa > 0" in panel
    assert "confirmed_standard_class_id" in panel
    assert "human_confirmation" in panel
    assert "actor_id" not in panel
    assert "let stale = false" in panel
    assert "if (stale) return" in panel
    assert "return () => { stale = true; }" in panel
    assert "geojson.proposed_geometry" in panel
    assert "geojson.screening_buffer" in panel
    assert "geojson.planning_resource_hits" in panel
    assert "geojson.current_facility_hits" in panel
    assert "geojson.unresolved_planning_resources" in panel
    assert "geojson.unresolved_current_facilities" in panel

    for forbidden in [
        "审批通过",
        "禁止建设",
        "合理建设规模",
        "GFA即容量",
        "步行服务区",
        "正式对齐结论",
    ]:
        assert forbidden not in panel


def test_representative_frontend_human_selected_confirmation_validates():
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "新型邻里服务点",
        "raw_facility_type": "未分类设施",
        "use_description": "现场材料由审查员核验",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    selected_candidate_audit = human_selected_candidate(
        evidence=[
            {
                "evidence_type": "reviewer_reason",
                "reason": "审查员核验了本次申请材料。",
            }
        ]
    )
    confirmation = {
        "actor_id": "frontend_reviewer",
        "confirmed_at": "2026-07-11T02:00:00Z",
        "selected_standard_class_id": "facility.market",
        "original_input_digest": resolution["original_input_digest"],
        "dictionary_version": "liv-2.0-fixture-v1",
    }

    validated = validate_human_confirmation(
        confirmation,
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=selected_candidate_audit,
    )

    assert validated["valid"] is True
    assert validated["selected_candidate"] == selected_candidate_audit
