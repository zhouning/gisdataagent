from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "frontend/src/components/datapanel/UwmLivabilityS2Panel.tsx"
PARENT = ROOT / "frontend/src/components/datapanel/LivabilityWorldModelTab.tsx"


def test_s2_panel_is_registered_in_uwm_livability_page():
    parent = PARENT.read_text(encoding="utf-8")
    assert "UwmLivabilityS2Panel" in parent
    assert "<UwmLivabilityS2Panel />" in parent


def test_s2_panel_exposes_action_conditioned_world_model_contract():
    text = PANEL.read_text(encoding="utf-8")
    for endpoint in [
        "/api/uwm/livability/s2/catalog",
        "/api/uwm/livability/s2/parcels",
        "/api/uwm/livability/s2/validate-action",
        "/api/uwm/livability/s2/rollout",
    ]:
        assert endpoint in text
    for label in [
        "S2 用地性质变更推演", "村庄", "真实地块", "当前用途", "规划用途", "目标用途",
        "转换状态", "行动理由", "数据快照", "人工确认", "t0 当前状态", "t1 直接变更",
        "t2 邻域适应", "基线/干预差异", "直接状态变化", "空间传播信号", "村域聚合",
        "不可预测效果", "不确定性", "完整证据链", "50 米", "150 米", "300 米",
    ]:
        assert label in text
    assert "credentials: 'include'" in text
    assert "window.__handleMapUpdate" in text
    assert "alternative_land_use_class" in text
    assert "actor_id:" not in text


def test_s2_panel_does_not_claim_unsupported_outcomes():
    text = PANEL.read_text(encoding="utf-8")
    for forbidden in ["审批通过", "确定改善", "政策成功率", "房价增幅", "容量增量", "步行圈", "综合宜居性得分"]:
        assert forbidden not in text
