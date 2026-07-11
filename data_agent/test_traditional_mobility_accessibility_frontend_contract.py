from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PANEL=ROOT/"frontend/src/components/datapanel/TraditionalLivabilityMobilityPanel.tsx"
TAB=ROOT/"frontend/src/components/datapanel/TraditionalLivabilityTab.tsx"

def test_panel_exposes_complete_evidence_bounded_demand8_contract():
    text=PANEL.read_text(encoding="utf-8")
    for required in ["/api/uwm/traditional-livability/mobility/overview","/api/uwm/traditional-livability/mobility/admin-units","/api/uwm/traditional-livability/mobility/admin-units/","/api/uwm/traditional-livability/mobility/map","需求8 · 出行、步行性与可达性","network_proxy_not_observed_walk_time","implemented","proxy_only","unavailable","public_transport","road_safety","shaded_routes","universal_accessibility","parking_pressure","cycling_routes","pedestrian_crossings","可达性缺口排名","人工核查候选","__handleMapUpdate"]:
        assert required in text
    for forbidden in ["观测步行时间","安全路径已验证","公交覆盖率","权威投资优先级","综合步行性得分"]:
        assert forbidden not in text

def test_panel_is_registered_in_traditional_tab():
    text=TAB.read_text(encoding="utf-8")
    assert "TraditionalLivabilityMobilityPanel" in text
    assert "<TraditionalLivabilityMobilityPanel />" in text
