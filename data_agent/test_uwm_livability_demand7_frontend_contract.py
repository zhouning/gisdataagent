from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demand7_panel_is_registered_with_evidence_boundaries():
    panel = (ROOT / "frontend/src/components/datapanel/UwmLivabilityDemand7Panel.tsx").read_text(encoding="utf-8")
    tab = (ROOT / "frontend/src/components/datapanel/LivabilityWorldModelTab.tsx").read_text(encoding="utf-8")
    assert "<UwmLivabilityDemand7Panel />" in tab
    for endpoint in [
        "/api/uwm/livability/demand7/overview",
        "/api/uwm/livability/demand7/units",
        "/api/uwm/livability/demand7/plan",
    ]:
        assert endpoint in panel
    for boundary in [
        "模型步不等于24个月或5年",
        "这不是政策实施效果",
        "24个月预测证据不足",
        "5年预测证据不足",
    ]:
        assert boundary in panel
    assert "window.__handleMapUpdate" in panel
