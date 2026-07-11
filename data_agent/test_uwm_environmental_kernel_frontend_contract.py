from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "frontend/src/components/datapanel/UwmLivabilityEnvironmentalKernelPanel.tsx"
TAB = ROOT / "frontend/src/components/datapanel/LivabilityWorldModelTab.tsx"


def test_environmental_kernel_panel_exposes_evidence_bounded_contract():
    text = PANEL.read_text(encoding="utf-8")
    for required in [
        "/api/uwm/livability/environmental-kernel/scene",
        "/api/uwm/livability/environmental-kernel/evidence-gate",
        "/api/uwm/livability/environmental-kernel/rollout",
        "/api/uwm/livability/environmental-kernel/map",
        "观测时间范围",
        "时间动力学",
        "直接动作响应",
        "空间传播",
        "bounded_proxy",
        "unavailable",
        "not_a_causal_effect_estimate",
        "我确认代理差异不构成因果政策效果",
        "__handleMapUpdate",
    ]:
        assert required in text
    for forbidden in ["权威降温收益", "保证降低", "真实因果效果"]:
        assert forbidden not in text


def test_environmental_kernel_panel_is_registered_in_uwm_livability_tab():
    text = TAB.read_text(encoding="utf-8")
    assert "UwmLivabilityEnvironmentalKernelPanel" in text
    assert "<UwmLivabilityEnvironmentalKernelPanel />" in text
