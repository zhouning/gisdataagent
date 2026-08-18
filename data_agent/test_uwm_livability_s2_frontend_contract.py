import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "frontend/src/components/datapanel/UwmLivabilityS2Panel.tsx"
PARENT = ROOT / "frontend/src/components/datapanel/LivabilityWorldModelTab.tsx"
CHAT_PANEL = ROOT / "frontend/src/components/ChatPanel.tsx"
MAP_PANEL = ROOT / "frontend/src/components/MapPanel.tsx"


def test_s2_panel_is_registered_in_uwm_livability_page():
    parent = PARENT.read_text(encoding="utf-8")
    assert "UwmLivabilityS2Panel" in parent
    assert "<UwmLivabilityS2Panel />" in parent


def test_s2_panel_exposes_action_conditioned_world_model_contract():
    text = PANEL.read_text(encoding="utf-8")
    translations = json.loads(
        (ROOT / "frontend/src/i18n/locales/zh-CN/common.json").read_text(encoding="utf-8")
    )["uwmS2"]
    localized_text = json.dumps(translations, ensure_ascii=False)
    for endpoint in [
        "/api/uwm/livability/s2/catalog",
        "/api/uwm/livability/s2/parcels",
        "/api/uwm/livability/s2/planning-projects",
        "/api/uwm/livability/s2/validate-action",
        "/api/uwm/livability/s2/rollout",
    ]:
        assert endpoint in text
    for label in [
        "S2 用地性质变更推演", "村庄", "真实地块", "当前用途", "规划用途", "目标用途",
            "转换状态", "行动理由", "数据快照", "人工确认", "t0 当前状态", "t1 情景变更",
        "t2 邻域适应", "覆盖代理差异", "直接状态变化", "空间传播信号", "村域聚合",
        "不可预测效果", "不确定性", "局部空间关系边", "技术归因账本", "50 米", "150 米", "300 米",
        "规划项目证据", "原表", "不作为现状设施坐标",
    ]:
        assert label in localized_text
    assert "credentials: 'include'" in text
    assert "window.__handleMapUpdate" in text
    assert "map_evidence" in text
    assert "uwmS2.map.affected" in text
    assert "uwmS2.map.planningResources" in text
    assert "uwmS2.map.facilities" in text
    assert "useTranslation" in text
    assert "getLocaleHeaders" in text
    assert "alternative_land_use_class" in text
    assert "actor_id:" not in text
    assert "setConfirmed(false)" in text
    assert "setValidation(null)" in text


def test_s2_panel_does_not_claim_unsupported_outcomes():
    text = PANEL.read_text(encoding="utf-8")
    for forbidden in ["审批通过", "确定改善", "政策成功率", "房价增幅", "容量增量", "步行圈", "综合宜居性得分"]:
        assert forbidden not in text


def test_chat_new_session_effect_avoids_unstable_chainlit_callback_dependencies():
    text = CHAT_PANEL.read_text(encoding="utf-8")
    assert "}, [connectMode, threadIdToResume]);" in text
    assert "[connectMode, threadIdToResume, clear, disconnect, connect" not in text


def test_chat_action_fetches_pending_map_updates_after_chainlit_callbacks():
    text = CHAT_PANEL.read_text(encoding="utf-8")
    assert "apiClient.callAction(action, sessionId)" in text
    assert "fetch('/api/map/pending'" in text
    assert "window.setTimeout(fetchPending, 300)" in text
    assert "window.setTimeout(fetchPending, 1800)" in text


def test_s2_map_selection_round_trips_into_chat_input():
    chat = CHAT_PANEL.read_text(encoding="utf-8")
    map_panel = MAP_PANEL.read_text(encoding="utf-8")
    assert "s2-map-parcel-selected" in map_panel
    assert "data-s2-parcel-id" not in map_panel
    assert "element.dataset.s2ParcelId" in map_panel
    assert "bindS2ParcelPopup" in map_panel
    assert "map.s2SelectHint" in map_panel
    assert "s2-map-parcel-selected" in chat
    assert "chat.s2SelectionPrompt" in chat
    assert "template.replace('{parcel_id}', parcelId)" in chat


def test_s2_geojson_layers_have_distinct_styles_and_safe_zoom():
    panel = PANEL.read_text(encoding="utf-8")
    map_panel = MAP_PANEL.read_text(encoding="utf-8")
    assert "case 'geojson':" in map_panel
    assert "L.circleMarker" in map_panel
    assert "containsS2Layers" in map_panel
    assert "containsS2Layers ? { maxZoom: 15 }" in map_panel
    assert "layerConfig.name.startsWith('S2 ')" in map_panel
    assert "selectedBounds.pad(1.2), { maxZoom: 15 }" in map_panel
    for color in [
        "#fbbf24",
        "#475569",
        "#fb923c",
        "#22c55e",
        "#ef4444",
        "#c084fc",
        "#14b8a6",
    ]:
        assert color in panel
