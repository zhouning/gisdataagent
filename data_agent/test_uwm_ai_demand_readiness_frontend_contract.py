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
    assert 'schema: "uwm.ai_demand_readiness_api.v2"' in source
    for field in (
        "primary_route",
        "implementation_level",
        "data_support",
        "evidence_level",
        "uncertainty",
        "max_claim_level",
        "route_availability",
        "implemented_outputs",
        "production_blockers",
        "registration_is_not_implementation",
        "production_complete_count",
        "observed_policy_outcome_superiority_claim",
        "source_provenance_server_side",
    ):
        assert field in source


def test_ai_demand_readiness_tab_guards_latest_abortable_request():
    source = READINESS_TAB.read_text(encoding="utf-8")

    assert "AbortController" in source
    assert "requestIdRef" in source
    assert "abortControllerRef" in source
    assert "signal: controller.signal" in source
    assert "abortControllerRef.current?.abort()" in source
    assert "requestId !== requestIdRef.current" in source
    assert "loadError.name === 'AbortError'" in source


def test_ai_demand_readiness_tab_validates_payload_and_http_errors():
    source = READINESS_TAB.read_text(encoding="utf-8")

    assert "function isReadinessPayload" in source
    assert "function isRequirementRow" in source
    assert "function isRouteRow" in source
    assert "value.livability_scenarios.every(isRequirementRow)" in source
    assert "value.customer_ai_demands.every(isRequirementRow)" in source
    assert "value.primary_routes.every(isRouteRow)" in source
    assert "value.summary.registered_requirement_count" in source
    assert "value.summary.production_complete_count" in source
    assert "value.claim_boundary.registration_is_not_implementation" in source
    assert "value.claim_boundary.observed_policy_outcome_superiority_claim" in source
    assert "response.text()" in source
    assert "JSON.parse" in source
    assert "HTTP ${response.status}" in source
    assert "响应不是有效 JSON" in source
    assert "响应结构不符合 readiness contract" in source
    assert "data as ReadinessPayload" not in source


def test_ai_demand_readiness_tab_renders_complete_ownership_scope():
    source = READINESS_TAB.read_text(encoding="utf-8")

    assert "livability_scenarios" in source
    assert "customer_ai_demands" in source
    assert "primary_routes" in source
    assert "{payload.livability_scenarios.length} 个宜居性场景" in source
    assert "{payload.customer_ai_demands.length} 项客户需求" in source
    assert "{payload.primary_routes.length} 条主技术路线" in source
    assert "注册不等于实现" in source
    assert "implemented_outputs" in source
    assert "production_blockers" in source
    assert "evidence_level" in source
    assert "uncertainty" in source
    assert "max_claim_level" in source
    assert "产品页面已存在" in source
    assert "产品页面规划中" in source
    assert "CheckCircle2" not in source


def test_ai_demand_readiness_tab_has_accessible_loading_errors_and_tables():
    source = READINESS_TAB.read_text(encoding="utf-8")

    assert 'aria-live="polite"' in source
    assert "aria-busy={loading}" in source
    assert 'role="alert"' in source
    assert "<caption>" in source
    assert 'scope="col"' in source


def test_ai_demand_readiness_routes_do_not_reuse_component_row_class():
    source = READINESS_TAB.read_text(encoding="utf-8")

    assert 'className="ai-demand-route-list"' in source
    assert "style={routeListStyle}" in source
    assert 'className="ai-demand-route-card"' in source
    assert 'className="uwm-component-row"' not in source
    assert 'className="uwm-evidence-grid"' not in source


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
