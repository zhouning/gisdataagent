import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "frontend/src/components/datapanel/UwmLivabilityEnvironmentalKernelPanel.tsx"
TAB = ROOT / "frontend/src/components/datapanel/LivabilityWorldModelTab.tsx"


def test_environmental_kernel_panel_exposes_evidence_bounded_contract():
    text = PANEL.read_text(encoding="utf-8")
    translations = json.loads(
        (ROOT / "frontend/src/i18n/locales/zh-CN/common.json").read_text(encoding="utf-8")
    )["uwmEnvironmentalKernel"]
    localized_text = json.dumps(translations, ensure_ascii=False)
    for required in [
        "/api/uwm/livability/environmental-kernel/scene",
        "/api/uwm/livability/environmental-kernel/evidence-gate",
        "/api/uwm/livability/environmental-kernel/rollout",
        "/api/uwm/livability/environmental-kernel/map",
        "not_a_causal_effect_estimate",
        "__handleMapUpdate",
    ]:
        assert required in text
    for localized in [
        "观测时间范围",
        "时间动力学",
        "直接动作响应",
        "空间传播",
        "bounded_proxy",
        "unavailable",
        "我确认代理差异不构成因果政策效果",
    ]:
        assert localized in localized_text
    for forbidden in ["权威降温收益", "保证降低", "真实因果效果"]:
        assert forbidden not in text
    assert "useTranslation" in text
    assert "getLocaleHeaders" in text
    assert "formatNumber" in text
    assert "localizedMapPayload" in text


def test_environmental_kernel_panel_is_registered_in_uwm_livability_tab():
    text = TAB.read_text(encoding="utf-8")
    assert "UwmLivabilityEnvironmentalKernelPanel" in text
    assert "<UwmLivabilityEnvironmentalKernelPanel />" in text
