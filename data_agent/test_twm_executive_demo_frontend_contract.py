from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TWM_TAB = ROOT / "frontend/src/components/datapanel/TerritoryWorldModelTab.tsx"
BRIEFING_PANEL = ROOT / "frontend/src/components/datapanel/TwmExecutiveDemoPanel.tsx"
DEMO_SCRIPT = ROOT / "docs/reports/twm_executive_demo_script_2026-07-22.md"


def test_twm_briefing_is_the_default_subtab_without_removing_existing_workspaces():
    source = TWM_TAB.read_text(encoding="utf-8")

    assert "type TwmSubTab = 'briefing' | 'overview' | 'data' | 'operate' | 'graph' | 'payload'" in source
    assert "{ id: 'briefing', label: '汇报演示', summary: '结论、证据和能力边界' }" in source
    assert "useState<TwmSubTab>('briefing')" in source
    assert "activeSubTab === 'briefing'" in source
    assert "<TwmExecutiveDemoPanel onNavigate={setActiveSubTab} onMapStage={syncTwmMap} />" in source
    for existing_tab in ("overview", "data", "operate", "graph", "payload"):
        assert f"activeSubTab === '{existing_tab}'" in source


def test_twm_briefing_exposes_evidence_and_claim_boundaries_in_business_language():
    source = BRIEFING_PANEL.read_text(encoding="utf-8")

    assert "/api/twm/executive-demo-report" in source
    assert "受控演示" in source
    assert "生产主张未开放" in source
    assert "GWM 在世界模型谱系中的位置" in source
    assert "地理空间世界模型的正式定义" in source
    assert "GWM Simulator 如何实现推演" in source
    assert "组合转移来源" in source
    assert "与其他 Simulator 的区别" in source
    assert "GWM 技术架构与 TWM 领域实例" in source
    assert "DAM-GK" in source
    assert "耕地空间布局优化" in source
    assert "GeoSOS-FLUS" in source
    assert "真实自然资源事件如何进入 Geospatial Kernel" in source
    assert "GWM-Bench：允许基准否定 Kernel" in source
    assert "当前不能宣称" in source
    assert "省级试点的最小数据闭环" in source
    assert "LLM + World Model + Evidence Gate" in source
    assert "进入地图联动" in source
    assert "进入操作推演" in source
    assert "查看数据依据" in source

    forbidden_overclaims = (
        "已实现省域真实政策效果预测",
        "当前精度已经优于 GeoSOS-FLUS",
        "可以替代法定审批",
        "DAM-GK 已通过通用世界模型验证",
    )
    for claim in forbidden_overclaims:
        assert claim not in source


def test_twm_demo_script_defines_one_reproducible_bishan_business_scenario():
    source = DEMO_SCRIPT.read_text(encoding="utf-8")

    assert "重庆市璧山区多行政单元受控样例——耕地保护与空间布局方案审查" in source
    assert "twm_bishan_multi_admin_eval" in source
    assert "业务场景为“耕地保护与占补平衡审查”" in source
    assert "依据完整度为 `0.78`" in source
    assert "验证期数为 `3`" in source
    assert "候选方案 `7`、合法可行 `3`、阻断方案 `4`" in source
    assert "不要临场任选入口" in source
    assert "自动审批通过或不通过" in source
