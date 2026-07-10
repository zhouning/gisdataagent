from pathlib import Path


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
