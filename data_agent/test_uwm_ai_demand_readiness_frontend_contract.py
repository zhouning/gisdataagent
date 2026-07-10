from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PANEL = ROOT / "frontend/src/components/DataPanel.tsx"
READINESS_TAB = ROOT / "frontend/src/components/datapanel/AiDemandReadinessTab.tsx"


def test_ai_demand_readiness_tab_is_registered_after_uwm_livability():
    source = DATA_PANEL.read_text(encoding="utf-8")

    assert "import AiDemandReadinessTab" in source
    assert "| 'ai_demand_readiness'" in source
    assert "label: 'AI应用需求矩阵'" in source
    assert source.index("key: 'uwm_livability'") < source.index(
        "key: 'ai_demand_readiness'"
    ) < source.index("key: 'worldmodel'")
    assert (
        "activeTab === 'ai_demand_readiness' && <AiDemandReadinessTab />"
        in source
    )


def test_ai_demand_readiness_tab_uses_canonical_api_and_required_fields():
    source = READINESS_TAB.read_text(encoding="utf-8")

    assert "/api/uwm/ai-demand-readiness" in source
    for field in (
        "primary_route",
        "implementation_level",
        "data_support",
        "route_availability",
        "implemented_outputs",
        "production_blockers",
        "registration_is_not_implementation",
        "production_complete_count",
        "observed_policy_outcome_superiority_claim",
    ):
        assert field in source


def test_ai_demand_readiness_tab_renders_complete_ownership_scope():
    source = READINESS_TAB.read_text(encoding="utf-8")

    assert "livability_scenarios" in source
    assert "customer_ai_demands" in source
    assert "primary_routes" in source
    assert "5 个宜居性场景" in source
    assert "25 项客户需求" in source
    assert "7 条主技术路线" in source
    assert "注册不等于实现" in source
    assert "implemented_outputs" in source
    assert "production_blockers" in source


def test_ai_demand_readiness_tab_does_not_use_obsolete_phase_counts():
    combined_source = "\n".join(
        (
            DATA_PANEL.read_text(encoding="utf-8"),
            READINESS_TAB.read_text(encoding="utf-8"),
        )
    )

    assert "complete_in_livability_case_count" not in combined_source
    assert "phase1_partial_count" not in combined_source
    assert "phase_counts" not in combined_source
