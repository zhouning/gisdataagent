# UWM Livability Requirement Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LIV 2.0 scenarios and the customer 25 AI demands first-class, testable contracts across the traditional livability tab, the UWM livability tab, and a new AI demand readiness tab.

**Architecture:** Add one deterministic backend requirement registry, then inject its method split into the existing traditional and UWM APIs. Add one small readiness API and one dense frontend matrix tab, while preserving the UWM production evidence gates and claim boundaries.

**Tech Stack:** Python 3, Starlette routes, pytest, React 18, TypeScript, Vite, lucide-react, existing `frontend/src/styles/layout.css`.

---

## File Structure

- Create `data_agent/uwm/livability_requirement_registry.py`
  - Owns LIV 2.0 scenario classification, 25-demand classification, method split, production blocker labels, and helper filters.
- Create `data_agent/api/uwm_ai_demand_readiness_routes.py`
  - Exposes `GET /api/uwm/ai-demand-readiness`.
- Create `data_agent/test_uwm_livability_requirement_registry.py`
  - Tests scenario and demand classification directly against the registry.
- Create `data_agent/test_uwm_ai_demand_readiness_routes.py`
  - Tests route registration and payload shape.
- Modify `data_agent/uwm/__init__.py`
  - Exports registry builder functions.
- Modify `data_agent/api/uwm_traditional_livability_routes.py`
  - Adds registry coverage to `GET /api/uwm/traditional-livability`.
- Modify `data_agent/api/uwm_livability_decision_routes.py`
  - Adds UWM-only scenario coverage, demand coverage, and production blockers to `GET /api/uwm/livability-decision`.
- Modify `data_agent/frontend_api.py`
  - Mounts the new AI demand readiness route.
- Modify `data_agent/test_uwm_traditional_livability_analysis.py`
  - Asserts traditional output has registry coverage and no UWM rollout fields.
- Modify `data_agent/test_uwm_livability_decision_routes.py`
  - Asserts UWM output has registry coverage without upgrading production claims.
- Modify `data_agent/test_uwm_traditional_livability_frontend_contract.py`
  - Asserts traditional tab exposes scenario and demand coverage labels.
- Modify `data_agent/test_uwm_livability_world_model_frontend_contract.py`
  - Asserts UWM tab exposes UWM-only scenario coverage and production blockers.
- Create `data_agent/test_uwm_ai_demand_readiness_frontend_contract.py`
  - Asserts DataPanel registers the new tab and component.
- Create `frontend/src/components/datapanel/AiDemandReadinessTab.tsx`
  - Dense matrix for the customer 25 AI demands.
- Modify `frontend/src/components/DataPanel.tsx`
  - Adds `ai_demand_readiness` tab after `uwm_livability`.
- Modify `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
  - Displays traditional scenario and demand coverage.
- Modify `frontend/src/components/datapanel/LivabilityWorldModelTab.tsx`
  - Displays UWM scenario coverage and production blockers.
- Modify `frontend/src/styles/layout.css`
  - Adds compact, responsive styles for coverage matrices.

## Task 1: Requirement Registry

**Files:**
- Create: `data_agent/uwm/livability_requirement_registry.py`
- Create: `data_agent/test_uwm_livability_requirement_registry.py`
- Modify: `data_agent/uwm/__init__.py`

- [ ] **Step 1: Write the failing registry tests**

Add `data_agent/test_uwm_livability_requirement_registry.py`:

```python
from data_agent.uwm.livability_requirement_registry import (
    UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA,
    build_livability_requirement_registry,
    livability_coverage_for_method,
)


def _by_id(rows):
    return {row["id"]: row for row in rows}


def test_livability_registry_classifies_liv_2_scenarios_by_method():
    registry = build_livability_requirement_registry()

    assert registry["schema"] == UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA
    scenarios = _by_id(registry["livability_scenarios"])

    assert scenarios["S1"]["traditional_support"]["status"] == "supported"
    assert scenarios["S1"]["uwm_support"]["status"] == "not_required_for_static_question"
    assert scenarios["S1"]["recommended_tab"] == "traditional_livability"

    assert scenarios["S2"]["traditional_support"]["status"] == "insufficient_for_impact_claim"
    assert scenarios["S2"]["uwm_support"]["status"] == "required"
    assert scenarios["S2"]["recommended_tab"] == "uwm_livability"
    assert "action_conditioned_transition" in scenarios["S2"]["uwm_support"]["requires"]

    assert scenarios["S4"]["traditional_support"]["status"] == "partial_static_fit_only"
    assert scenarios["S4"]["uwm_support"]["status"] == "required_for_future_contribution"

    assert scenarios["S6"]["traditional_support"]["status"] == "partial_conflict_check_ready"
    assert "facility_category_mapping_chain" in scenarios["S6"]["production_blockers"]

    assert scenarios["S7"]["traditional_support"]["status"] == "partial_static_candidate_ranking"
    assert scenarios["S7"]["uwm_support"]["status"] == "required_for_dynamic_siting"
    assert "multi_step_planning" in scenarios["S7"]["uwm_support"]["requires"]


def test_livability_registry_classifies_customer_25_demands():
    registry = build_livability_requirement_registry()
    demands = _by_id(registry["customer_ai_demands"])

    for demand_id in ["7", "8", "15", "21"]:
        row = demands[demand_id]
        assert row["phase"] == "complete_in_livability_case"
        assert row["livability_relevance"] == "direct"
        assert row["implementation_status"] == "route_to_livability_tabs"

    for demand_id in ["1", "2", "3", "4", "5", "6", "9", "10", "11", "12", "13", "14", "16", "17"]:
        row = demands[demand_id]
        assert row["phase"] == "phase1_partial_data_query_statistics"
        assert row["implementation_status"] == "readiness_matrix_only"

    for demand_id in ["18", "19", "20", "22", "23", "24", "25"]:
        row = demands[demand_id]
        assert row["phase"] == "phase2_standalone_case"
        assert row["standalone_tab_candidate"] is True

    assert demands["24"]["uwm_capabilities"] == [
        "livability_impact_counterfactual",
        "priority_scoring_when_backed_by_rollout",
        "implementation_sequence_when_backed_by_planner_trace",
    ]
    assert demands["24"]["implementation_status"] == "phase2_full_scope_with_livability_uwm_reference"


def test_registry_filters_for_traditional_and_uwm_views():
    registry = build_livability_requirement_registry()

    traditional = livability_coverage_for_method(registry, method="traditional")
    uwm = livability_coverage_for_method(registry, method="uwm")

    assert {row["id"] for row in traditional["scenario_coverage"]} == {"S1", "S4", "S6", "S7"}
    assert "S2" in {row["id"] for row in traditional["unsupported_dynamic_requirements"]}
    assert {row["id"] for row in uwm["uwm_only_scenario_coverage"]} == {"S2", "S4", "S7"}
    assert "observed_policy_outcome_panel" in uwm["production_blockers"]
    assert uwm["production_world_model_readiness"]["production_world_model_ready"] is False
```

- [ ] **Step 2: Run registry tests to verify they fail**

Run:

```bash
uv run pytest data_agent/test_uwm_livability_requirement_registry.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'data_agent.uwm.livability_requirement_registry'`.

- [ ] **Step 3: Implement the registry module**

Create `data_agent/uwm/livability_requirement_registry.py` with these public functions and constants:

```python
"""Requirement registry for UWM urban livability customer scenarios."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA = "uwm.livability_requirement_registry.v1"

METHOD_SPLIT = {
    "traditional": {
        "method_id": "traditional_static_livability",
        "tab_key": "traditional_livability",
        "can_answer": [
            "current_state_indicator_summary",
            "facility_count_and_distribution_gap",
            "buffer_or_service_area_coverage",
            "static_deficit_ranking",
            "static_candidate_ranking",
            "rule_based_current_state_recommendation",
        ],
        "cannot_answer": [
            "action_conditioned_future_state",
            "land_use_change_counterfactual",
            "multi_step_policy_sequence",
            "spatial_spillover_effect",
            "risk_adjusted_counterfactual_benefit",
            "observed_policy_outcome_superiority",
        ],
    },
    "uwm": {
        "method_id": "geospatial_world_model_livability",
        "tab_key": "uwm_livability",
        "can_answer": [
            "action_conditioned_transition",
            "land_use_or_facility_change_counterfactual",
            "rollout_trace",
            "spatial_spillover_effect",
            "uncertainty_aware_benefit",
            "planner_action_sequence",
            "learned_policy_or_value_evidence",
        ],
        "must_expose": [
            "renderer_trace",
            "simulator_trace",
            "planner_trace",
            "evidence_readiness",
            "production_blockers",
            "claim_boundary",
        ],
    },
}

PRODUCTION_BLOCKERS = [
    "observed_travel_time_or_mobility_surface",
    "station_calibrated_scene_holdout",
    "observed_policy_outcome_panel",
    "planner_governance_binding",
    "authoritative_population_vulnerability_panel",
]

LIVABILITY_SCENARIOS = [
    {
        "id": "S1",
        "title": "区级设施评估",
        "requirement_source": "宜居性专项分析.docx",
        "required_outputs": ["pass_fail_conclusion", "positive_negative_gap_list", "fp_fpp_metric_basis"],
        "recommended_tab": "traditional_livability",
        "traditional_support": {
            "status": "supported",
            "supports": ["facility_count_gap", "facility_distribution_gap", "current_coverage_gap"],
            "evidence_level": "current_state_static_support",
        },
        "uwm_support": {
            "status": "not_required_for_static_question",
            "requires": [],
            "evidence_level": "not_required",
        },
        "data_basis": ["service_accessibility_surface", "admin_units", "facility_or_poi_inventory"],
        "production_blockers": ["authoritative_fp_fpp_threshold_table"] ,
        "claim_boundary": "traditional_current_state_claim",
    },
    {
        "id": "S2",
        "title": "用地性质变更",
        "requirement_source": "宜居性专项分析.docx",
        "required_outputs": ["agree_disagree_recommendation", "before_after_coverage_delta", "reason_trace"],
        "recommended_tab": "uwm_livability",
        "traditional_support": {
            "status": "insufficient_for_impact_claim",
            "supports": ["current_baseline_coverage_only"],
            "evidence_level": "insufficient_for_counterfactual",
        },
        "uwm_support": {
            "status": "required",
            "requires": ["action_conditioned_transition", "counterfactual_state_delta", "simulator_trace"],
            "evidence_level": "bounded_world_model_support",
        },
        "data_basis": ["current_scene_state", "candidate_action", "service_accessibility_surface", "spatial_graph"],
        "production_blockers": PRODUCTION_BLOCKERS,
        "claim_boundary": "bounded_support_until_policy_outcome_validation",
    },
    {
        "id": "S4",
        "title": "项目宜居性评估",
        "requirement_source": "宜居性专项分析.docx",
        "required_outputs": ["use_by_use_judgement", "overall_alignment", "future_contribution_when_requested"],
        "recommended_tab": "split_traditional_and_uwm",
        "traditional_support": {
            "status": "partial_static_fit_only",
            "supports": ["current_service_demand", "duplicate_supply", "static_resource_conflict"],
            "evidence_level": "current_state_static_support",
        },
        "uwm_support": {
            "status": "required_for_future_contribution",
            "requires": ["project_as_action_sequence", "rollout_trace", "planner_or_simulator_evidence"],
            "evidence_level": "bounded_world_model_support",
        },
        "data_basis": ["project_use_mix", "gfa", "current_service_gap", "spatial_graph"],
        "production_blockers": ["approved_project_schema", *PRODUCTION_BLOCKERS],
        "claim_boundary": "split_static_and_counterfactual_claims",
    },
    {
        "id": "S6",
        "title": "超范围设施评估",
        "requirement_source": "宜居性专项分析.docx",
        "required_outputs": ["conflict_conclusion", "affected_parcels", "category_mapping_when_available"],
        "recommended_tab": "traditional_livability",
        "traditional_support": {
            "status": "partial_conflict_check_ready",
            "supports": ["static_buffer_conflict_check", "affected_resource_list"],
            "evidence_level": "current_state_static_support",
        },
        "uwm_support": {
            "status": "not_required_for_conflict_check",
            "requires": [],
            "evidence_level": "not_required",
        },
        "data_basis": ["facility_location", "reserved_livability_resources", "parcel_layer"],
        "production_blockers": ["facility_category_mapping_chain", "standard_43_facility_taxonomy_binding"],
        "claim_boundary": "partial_static_support",
    },
    {
        "id": "S7",
        "title": "设施选址",
        "requirement_source": "宜居性专项分析.docx",
        "required_outputs": ["primary_site", "backup_sites", "coverage_lift_estimate", "dynamic_benefit_when_requested"],
        "recommended_tab": "split_traditional_and_uwm",
        "traditional_support": {
            "status": "partial_static_candidate_ranking",
            "supports": ["current_gap_filter", "candidate_static_coverage_lift_proxy"],
            "evidence_level": "current_state_static_support",
        },
        "uwm_support": {
            "status": "required_for_dynamic_siting",
            "requires": ["action_conditioned_transition", "spatial_spillover_effect", "uncertainty", "multi_step_planning"],
            "evidence_level": "bounded_world_model_support",
        },
        "data_basis": ["candidate_parcels", "land_use_compatibility", "service_gap_surface", "spatial_graph"],
        "production_blockers": ["authoritative_candidate_parcel_inventory", *PRODUCTION_BLOCKERS],
        "claim_boundary": "split_static_ranking_and_world_model_planning",
    },
]

DEMAND_PHASES = {
    "complete_in_livability_case": ["7", "8", "15", "21"],
    "phase1_partial_data_query_statistics": ["1", "2", "3", "4", "5", "6", "9", "10", "11", "12", "13", "14", "16", "17"],
    "phase2_standalone_case": ["18", "19", "20", "22", "23", "24", "25"],
}

DEMAND_TITLES = {
    "1": "区域与片区识别",
    "2": "总体规划",
    "3": "用地与地块状态",
    "4": "基础设施与市政管网",
    "5": "资产",
    "6": "人口与人口结构",
    "7": "宜居性与社区需求",
    "8": "出行、步行性与可达性",
    "9": "公共空间与场所营造",
    "10": "安全、治安与舒适",
    "11": "环境质量与气候舒适",
    "12": "社会基础设施与社区设施",
    "13": "住房与社区构成",
    "14": "经济活力与日常便利",
    "15": "社区之声与舆情",
    "16": "文化、标识与片区特色",
    "17": "数字化与智慧片区就绪度",
    "18": "运维与服务质量",
    "19": "韧性与面向未来就绪度",
    "20": "DED 执照与经济活动",
    "21": "政府机构与公共服务",
    "22": "设计参数与开发要求",
    "23": "财务与投资分析",
    "24": "影响评估与优先级排序",
    "25": "建议与实施路线图",
}


def build_livability_requirement_registry() -> dict[str, Any]:
    demands = [_build_demand_row(str(index)) for index in range(1, 26)]
    return {
        "schema": UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA,
        "registry_id": "uwm-livability-requirement-registry-2026-07-09",
        "source_documents": [
            "/Users/zhouning/Downloads/宜居性专项分析.docx",
            "/Users/zhouning/Downloads/客户侧25个AI应用需求的回复.docx",
        ],
        "method_split": deepcopy(METHOD_SPLIT),
        "livability_scenarios": deepcopy(LIVABILITY_SCENARIOS),
        "customer_ai_demands": demands,
        "production_world_model_readiness": _production_world_model_readiness(),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def livability_coverage_for_method(registry: dict[str, Any], *, method: str) -> dict[str, Any]:
    scenarios = list(registry.get("livability_scenarios") or [])
    demands = list(registry.get("customer_ai_demands") or [])
    if method == "traditional":
        return {
            "method": registry["method_split"]["traditional"],
            "scenario_coverage": [
                row for row in scenarios
                if row.get("traditional_support", {}).get("status") in {
                    "supported",
                    "partial_static_fit_only",
                    "partial_conflict_check_ready",
                    "partial_static_candidate_ranking",
                }
            ],
            "customer_demand_coverage": [
                row for row in demands
                if row["phase"] in {
                    "complete_in_livability_case",
                    "phase1_partial_data_query_statistics",
                }
            ],
            "unsupported_dynamic_requirements": [
                row for row in scenarios
                if row.get("uwm_support", {}).get("status") in {
                    "required",
                    "required_for_future_contribution",
                    "required_for_dynamic_siting",
                }
            ],
        }
    if method == "uwm":
        return {
            "method": registry["method_split"]["uwm"],
            "uwm_only_scenario_coverage": [
                row for row in scenarios
                if row.get("uwm_support", {}).get("status") in {
                    "required",
                    "required_for_future_contribution",
                    "required_for_dynamic_siting",
                }
            ],
            "customer_demand_coverage": [
                row for row in demands
                if row["phase"] in {
                    "complete_in_livability_case",
                    "phase2_standalone_case",
                }
            ],
            "production_world_model_readiness": deepcopy(registry["production_world_model_readiness"]),
            "production_blockers": list(PRODUCTION_BLOCKERS),
        }
    raise ValueError(f"Unsupported livability coverage method: {method}")


def _build_demand_row(demand_id: str) -> dict[str, Any]:
    phase = _phase_for_demand(demand_id)
    row = {
        "id": demand_id,
        "title": DEMAND_TITLES[demand_id],
        "requirement_source": "客户侧25个AI应用需求的回复.docx",
        "phase": phase,
        "livability_relevance": "direct" if demand_id in {"7", "8", "15", "21"} else "adjacent",
        "current_data_support": _current_data_support(phase),
        "traditional_capabilities": _traditional_capabilities(demand_id, phase),
        "uwm_capabilities": _uwm_capabilities(demand_id),
        "standalone_tab_candidate": phase == "phase2_standalone_case",
        "implementation_status": _implementation_status(demand_id, phase),
        "recommended_tab": _recommended_tab(demand_id, phase),
        "production_blockers": _demand_blockers(demand_id, phase),
    }
    if demand_id in {"24", "25"}:
        row["livability_relevance"] = "uwm_livability_reference_only"
    return row


def _phase_for_demand(demand_id: str) -> str:
    for phase, ids in DEMAND_PHASES.items():
        if demand_id in ids:
            return phase
    raise ValueError(f"Unknown customer demand id: {demand_id}")


def _current_data_support(phase: str) -> str:
    if phase == "complete_in_livability_case":
        return "supported_by_livability_case_artifacts"
    if phase == "phase1_partial_data_query_statistics":
        return "data_query_statistics_only"
    return "requires_phase2_case_design"


def _traditional_capabilities(demand_id: str, phase: str) -> list[str]:
    if demand_id in {"7", "8", "12", "15", "21"}:
        return ["current_inventory", "coverage_or_buffer_analysis", "gap_statistics", "map_layer"]
    if phase == "phase1_partial_data_query_statistics":
        return ["data_access", "query", "statistics", "map_layer_when_geometry_exists"]
    return []


def _uwm_capabilities(demand_id: str) -> list[str]:
    if demand_id == "24":
        return [
            "livability_impact_counterfactual",
            "priority_scoring_when_backed_by_rollout",
            "implementation_sequence_when_backed_by_planner_trace",
        ]
    if demand_id == "25":
        return [
            "livability_intervention_sequence_when_backed_by_planner_trace",
            "roadmap_reference_when_scope_is_livability_only",
        ]
    if demand_id in {"7", "8", "21"}:
        return ["counterfactual_service_or_accessibility_improvement", "planner_sequence_when_actions_are_defined"]
    return []


def _implementation_status(demand_id: str, phase: str) -> str:
    if phase == "complete_in_livability_case":
        return "route_to_livability_tabs"
    if demand_id in {"24", "25"}:
        return "phase2_full_scope_with_livability_uwm_reference"
    if phase == "phase1_partial_data_query_statistics":
        return "readiness_matrix_only"
    return "phase2_standalone_case_required"


def _recommended_tab(demand_id: str, phase: str) -> str:
    if phase == "complete_in_livability_case":
        return "traditional_livability_or_uwm_livability"
    if demand_id in {"24", "25"}:
        return "ai_demand_readiness_with_uwm_reference"
    return "ai_demand_readiness"


def _demand_blockers(demand_id: str, phase: str) -> list[str]:
    if phase == "complete_in_livability_case":
        return []
    if demand_id in {"24", "25"}:
        return ["full_phase2_business_rules", "cross_domain_cost_and_governance_inputs", *PRODUCTION_BLOCKERS]
    if phase == "phase1_partial_data_query_statistics":
        return ["advanced_business_rules", "authoritative_domain_data", "case_specific_model_algorithm"]
    return ["phase2_case_design", "authoritative_data_source", "business_rule_model"]


def _production_world_model_readiness() -> dict[str, Any]:
    return {
        "production_world_model_ready": False,
        "bounded_research_ready": True,
        "blocking_gate_count": len(PRODUCTION_BLOCKERS),
        "blocking_gates": list(PRODUCTION_BLOCKERS),
        "claim_boundary": "bounded_support_until_authoritative_policy_outcome_and_governance_gates_pass",
    }
```

- [ ] **Step 4: Export registry functions from `data_agent/uwm/__init__.py`**

Add imports near the other livability imports:

```python
from .livability_requirement_registry import (
    UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA,
    build_livability_requirement_registry,
    livability_coverage_for_method,
)
```

Add these names to `__all__`:

```python
    "UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA",
    "build_livability_requirement_registry",
    "livability_coverage_for_method",
```

- [ ] **Step 5: Run registry tests to verify they pass**

Run:

```bash
uv run pytest data_agent/test_uwm_livability_requirement_registry.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add data_agent/uwm/livability_requirement_registry.py data_agent/uwm/__init__.py data_agent/test_uwm_livability_requirement_registry.py
git commit -m "feat: add UWM livability requirement registry"
```

## Task 2: Traditional API Requirement Coverage

**Files:**
- Modify: `data_agent/api/uwm_traditional_livability_routes.py`
- Modify: `data_agent/uwm/traditional_livability_analysis.py`
- Modify: `data_agent/test_uwm_traditional_livability_analysis.py`

- [ ] **Step 1: Write failing tests for traditional registry coverage**

Append assertions to `test_traditional_livability_analysis_is_complete_static_same_data_output`:

```python
    registry = analysis["requirement_registry"]
    assert registry["method"]["method_id"] == "traditional_static_livability"
    assert {row["id"] for row in registry["scenario_coverage"]} == {"S1", "S4", "S6", "S7"}
    assert "S2" in {row["id"] for row in registry["unsupported_dynamic_requirements"]}
    assert {row["id"] for row in registry["customer_demand_coverage"]}.issuperset(
        {"1", "2", "3", "4", "5", "6", "7", "8", "15", "21"}
    )
    assert "action_conditioned_future_state" in registry["method"]["cannot_answer"]
```

- [ ] **Step 2: Run the focused traditional test to verify it fails**

Run:

```bash
uv run pytest data_agent/test_uwm_traditional_livability_analysis.py::test_traditional_livability_analysis_is_complete_static_same_data_output -q
```

Expected: FAIL with `KeyError: 'requirement_registry'`.

- [ ] **Step 3: Add optional registry injection to traditional analysis**

Modify `data_agent/uwm/traditional_livability_analysis.py`:

```python
from .livability_requirement_registry import (
    build_livability_requirement_registry,
    livability_coverage_for_method,
)
```

Inside `build_traditional_livability_analysis`, before the `return`, add:

```python
    requirement_registry = livability_coverage_for_method(
        build_livability_requirement_registry(),
        method="traditional",
    )
```

Add this key to the returned dictionary:

```python
        "requirement_registry": requirement_registry,
```

- [ ] **Step 4: Keep the route unchanged except for payload passthrough**

No route-level code is needed because `_load_default_analysis()` returns the enriched analysis. Open `data_agent/api/uwm_traditional_livability_routes.py` and confirm it still calls `build_traditional_livability_analysis` with `analysis_id`, `created_at`, `multisource_livability_scene`, and `top_n`.

- [ ] **Step 5: Run traditional analysis tests**

Run:

```bash
uv run pytest data_agent/test_uwm_traditional_livability_analysis.py data_agent/test_uwm_traditional_livability_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

Run:

```bash
git add data_agent/uwm/traditional_livability_analysis.py data_agent/test_uwm_traditional_livability_analysis.py
git commit -m "feat: expose traditional livability requirement coverage"
```

## Task 3: UWM Decision API Requirement Coverage

**Files:**
- Modify: `data_agent/api/uwm_livability_decision_routes.py`
- Modify: `data_agent/test_uwm_livability_decision_routes.py`

- [ ] **Step 1: Write failing tests for UWM registry coverage**

Append a new test to `data_agent/test_uwm_livability_decision_routes.py`:

```python
def test_livability_decision_payload_exposes_requirement_coverage_without_upgrading_claims():
    payload = routes.load_uwm_livability_decision_payload()

    registry = payload["requirement_registry"]
    assert registry["method"]["method_id"] == "geospatial_world_model_livability"
    assert {row["id"] for row in registry["uwm_only_scenario_coverage"]} == {"S2", "S4", "S7"}
    assert registry["production_world_model_readiness"]["production_world_model_ready"] is False
    assert registry["production_world_model_readiness"]["bounded_research_ready"] is True
    assert "observed_policy_outcome_panel" in registry["production_blockers"]

    demand_coverage = {row["id"]: row for row in registry["customer_demand_coverage"]}
    assert demand_coverage["24"]["implementation_status"] == "phase2_full_scope_with_livability_uwm_reference"
    assert demand_coverage["25"]["implementation_status"] == "phase2_full_scope_with_livability_uwm_reference"

    assert payload["observed_policy_outcome_superiority_claim"] is False
    assert payload["empirical_superiority_claim"] is False
```

- [ ] **Step 2: Run the new focused test to verify it fails**

Run:

```bash
uv run pytest data_agent/test_uwm_livability_decision_routes.py::test_livability_decision_payload_exposes_requirement_coverage_without_upgrading_claims -q
```

Expected: FAIL with `KeyError: 'requirement_registry'`.

- [ ] **Step 3: Inject UWM registry coverage into the decision payload**

Modify `data_agent/api/uwm_livability_decision_routes.py`:

```python
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
    livability_coverage_for_method,
)
```

Inside `load_uwm_livability_decision_payload`, after the line that assigns `world_model_readiness = build_world_model_evidence_readiness(data_foundation_gate)`, add:

```python
    requirement_registry = livability_coverage_for_method(
        build_livability_requirement_registry(),
        method="uwm",
    )
```

Add this key to the returned dictionary:

```python
        "requirement_registry": requirement_registry,
        "production_world_model_readiness": requirement_registry["production_world_model_readiness"],
        "production_blockers": requirement_registry["production_blockers"],
```

- [ ] **Step 4: Run UWM route tests**

Run:

```bash
uv run pytest data_agent/test_uwm_livability_decision_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add data_agent/api/uwm_livability_decision_routes.py data_agent/test_uwm_livability_decision_routes.py
git commit -m "feat: expose UWM livability requirement coverage"
```

## Task 4: AI Demand Readiness API

**Files:**
- Create: `data_agent/api/uwm_ai_demand_readiness_routes.py`
- Create: `data_agent/test_uwm_ai_demand_readiness_routes.py`
- Modify: `data_agent/frontend_api.py`

- [ ] **Step 1: Write failing route tests**

Create `data_agent/test_uwm_ai_demand_readiness_routes.py`:

```python
from data_agent.api import uwm_ai_demand_readiness_routes as routes


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def test_ai_demand_readiness_route_is_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = routes.get_uwm_ai_demand_readiness_routes()
    frontend_route_list = get_frontend_api_routes()

    assert "GET" in _route_methods(route_list, "/api/uwm/ai-demand-readiness")
    assert "GET" in _route_methods(frontend_route_list, "/api/uwm/ai-demand-readiness")


def test_ai_demand_readiness_payload_exposes_25_demands_and_method_split():
    payload = routes.load_uwm_ai_demand_readiness_payload()

    assert payload["schema"] == routes.UWM_AI_DEMAND_READINESS_API_SCHEMA
    assert len(payload["customer_ai_demands"]) == 25
    assert payload["summary"]["complete_in_livability_case_count"] == 4
    assert payload["summary"]["phase1_partial_count"] == 14
    assert payload["summary"]["phase2_standalone_count"] == 7
    assert payload["method_split"]["traditional"]["tab_key"] == "traditional_livability"
    assert payload["method_split"]["uwm"]["tab_key"] == "uwm_livability"
    assert payload["production_world_model_readiness"]["production_world_model_ready"] is False
    assert payload["observed_policy_outcome_superiority_claim"] is False
    assert payload["empirical_superiority_claim"] is False
```

- [ ] **Step 2: Run route tests to verify they fail**

Run:

```bash
uv run pytest data_agent/test_uwm_ai_demand_readiness_routes.py -q
```

Expected: FAIL with import error for `uwm_ai_demand_readiness_routes`.

- [ ] **Step 3: Implement AI demand readiness routes**

Create `data_agent/api/uwm_ai_demand_readiness_routes.py`:

```python
"""Routes for UWM customer AI demand readiness matrix."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
)


UWM_AI_DEMAND_READINESS_API_SCHEMA = "uwm.ai_demand_readiness_api.v1"


def load_uwm_ai_demand_readiness_payload() -> dict[str, Any]:
    registry = build_livability_requirement_registry()
    demands = list(registry["customer_ai_demands"])
    return {
        "schema": UWM_AI_DEMAND_READINESS_API_SCHEMA,
        "registry_id": registry["registry_id"],
        "source_documents": list(registry["source_documents"]),
        "method_split": dict(registry["method_split"]),
        "livability_scenarios": list(registry["livability_scenarios"]),
        "customer_ai_demands": demands,
        "summary": {
            "demand_count": len(demands),
            "complete_in_livability_case_count": _count_phase(demands, "complete_in_livability_case"),
            "phase1_partial_count": _count_phase(demands, "phase1_partial_data_query_statistics"),
            "phase2_standalone_count": _count_phase(demands, "phase2_standalone_case"),
        },
        "production_world_model_readiness": dict(registry["production_world_model_readiness"]),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


async def uwm_ai_demand_readiness(request: Request):
    """GET /api/uwm/ai-demand-readiness"""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(await asyncio.to_thread(load_uwm_ai_demand_readiness_payload))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def get_uwm_ai_demand_readiness_routes() -> list:
    return [
        Route(
            "/api/uwm/ai-demand-readiness",
            uwm_ai_demand_readiness,
            methods=["GET"],
        ),
    ]


def _count_phase(rows: list[dict[str, Any]], phase: str) -> int:
    return sum(1 for row in rows if row.get("phase") == phase)
```

- [ ] **Step 4: Mount the new route in `frontend_api.py`**

Inside `get_frontend_api_routes`, add import:

```python
    from .api.uwm_ai_demand_readiness_routes import get_uwm_ai_demand_readiness_routes
```

Add the route after `*get_uwm_livability_decision_routes(),`:

```python
        # UWM customer AI demand readiness matrix
        *get_uwm_ai_demand_readiness_routes(),
```

- [ ] **Step 5: Run route tests**

Run:

```bash
uv run pytest data_agent/test_uwm_ai_demand_readiness_routes.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add data_agent/api/uwm_ai_demand_readiness_routes.py data_agent/frontend_api.py data_agent/test_uwm_ai_demand_readiness_routes.py
git commit -m "feat: add UWM AI demand readiness route"
```

## Task 5: AI Demand Readiness Frontend Tab

**Files:**
- Create: `frontend/src/components/datapanel/AiDemandReadinessTab.tsx`
- Modify: `frontend/src/components/DataPanel.tsx`
- Create: `data_agent/test_uwm_ai_demand_readiness_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract tests**

Create `data_agent/test_uwm_ai_demand_readiness_frontend_contract.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PANEL = ROOT / "frontend" / "src" / "components" / "DataPanel.tsx"
AI_TAB = (
    ROOT
    / "frontend"
    / "src"
    / "components"
    / "datapanel"
    / "AiDemandReadinessTab.tsx"
)


def test_ai_demand_readiness_tab_is_registered_after_uwm_livability():
    text = DATA_PANEL.read_text(encoding="utf-8")

    assert "AiDemandReadinessTab" in text
    assert "ai_demand_readiness" in text
    assert "AI应用需求矩阵" in text
    assert "{activeTab === 'ai_demand_readiness' && <AiDemandReadinessTab />}" in text
    assert text.index("{ key: 'uwm_livability'") < text.index("{ key: 'ai_demand_readiness'")


def test_ai_demand_readiness_tab_uses_readiness_api_contract():
    text = AI_TAB.read_text(encoding="utf-8")

    assert "/api/uwm/ai-demand-readiness" in text
    assert "AI应用需求矩阵" in text
    assert "complete_in_livability_case_count" in text
    assert "phase1_partial_count" in text
    assert "phase2_standalone_count" in text
    assert "production_world_model_ready" in text
    assert "observed_policy_outcome_superiority_claim" in text
    assert "customer_ai_demands" in text
    assert "recommended_tab" in text
```

- [ ] **Step 2: Run frontend contract tests to verify they fail**

Run:

```bash
uv run pytest data_agent/test_uwm_ai_demand_readiness_frontend_contract.py -q
```

Expected: FAIL because `AiDemandReadinessTab.tsx` is missing.

- [ ] **Step 3: Add `AiDemandReadinessTab.tsx`**

Create `frontend/src/components/datapanel/AiDemandReadinessTab.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Database, FileText, RefreshCw, Shield } from 'lucide-react';

type AnyRecord = Record<string, any>;

function isRecord(value: unknown): value is AnyRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asArray<T = AnyRecord>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function phaseLabel(value: unknown): string {
  const text = String(value || '');
  const labels: Record<string, string> = {
    complete_in_livability_case: '宜居性 case 完整覆盖',
    phase1_partial_data_query_statistics: '一期数据查询统计',
    phase2_standalone_case: '二期独立 case',
  };
  return labels[text] || text || '-';
}

export default function AiDemandReadinessTab() {
  const [payload, setPayload] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadReadiness = async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch('/api/uwm/ai-demand-readiness', { credentials: 'include' });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || 'AI应用需求矩阵加载失败');
        return;
      }
      setPayload(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'AI应用需求矩阵加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReadiness();
  }, []);

  const summary = isRecord(payload?.summary) ? payload.summary : {};
  const readiness = isRecord(payload?.production_world_model_readiness)
    ? payload.production_world_model_readiness
    : {};
  const demands = asArray<AnyRecord>(payload?.customer_ai_demands);
  const sourceDocuments = asArray<string>(payload?.source_documents);
  const phaseGroups = useMemo(() => {
    const groups: Record<string, AnyRecord[]> = {};
    demands.forEach(row => {
      const phase = String(row.phase || 'unknown');
      groups[phase] = groups[phase] || [];
      groups[phase].push(row);
    });
    return groups;
  }, [demands]);

  return (
    <div className="ai-demand-readiness-tab">
      <div className="datapanel-section-header">
        <div>
          <h3>AI应用需求矩阵</h3>
          <p>客户侧 25 个 AI 应用需求的当前数据支撑、宜居性归属和二期 case 边界。</p>
        </div>
        <button className="secondary-button" onClick={loadReadiness} disabled={loading}>
          <RefreshCw size={14} />
          刷新
        </button>
      </div>

      {error && <div className="ai-demand-message error"><AlertTriangle size={15} />{error}</div>}
      {loading && !payload && <div className="ai-demand-empty">正在加载 AI 应用需求矩阵</div>}

      {payload && (
        <>
          <div className="ai-demand-kpi-grid">
            <div><span>需求总数</span><strong>{summary.demand_count || 0}</strong></div>
            <div><span>宜居性完整覆盖</span><strong>{summary.complete_in_livability_case_count || 0}</strong></div>
            <div><span>一期部分覆盖</span><strong>{summary.phase1_partial_count || 0}</strong></div>
            <div><span>二期独立 case</span><strong>{summary.phase2_standalone_count || 0}</strong></div>
          </div>

          <div className="ai-demand-panel">
            <div className="ai-demand-panel-title">
              <Shield size={15} />
              <strong>生产证据门</strong>
            </div>
            <div className="ai-demand-boundary-grid">
              <div>
                <span>production_world_model_ready</span>
                <strong>{String(Boolean(readiness.production_world_model_ready))}</strong>
              </div>
              <div>
                <span>observed_policy_outcome_superiority_claim</span>
                <strong>{String(Boolean(payload.observed_policy_outcome_superiority_claim))}</strong>
              </div>
              <div>
                <span>claim_boundary</span>
                <strong>{readiness.claim_boundary || '-'}</strong>
              </div>
              <div>
                <span>source_documents</span>
                <strong>{sourceDocuments.join(' / ') || '-'}</strong>
              </div>
            </div>
          </div>

          {Object.entries(phaseGroups).map(([phase, rows]) => (
            <div className="ai-demand-panel" key={phase}>
              <div className="ai-demand-panel-title">
                <Database size={15} />
                <strong>{phaseLabel(phase)}</strong>
              </div>
              <div className="ai-demand-table-wrap">
                <table className="ai-demand-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>主题</th>
                      <th>当前支撑</th>
                      <th>传统方法</th>
                      <th>UWM</th>
                      <th>推荐 tab</th>
                      <th>阻塞项</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(row => (
                      <tr key={row.id}>
                        <td>{row.id}</td>
                        <td>{row.title}</td>
                        <td>{row.current_data_support || '-'}</td>
                        <td>{asArray<string>(row.traditional_capabilities).join(' / ') || '-'}</td>
                        <td>{asArray<string>(row.uwm_capabilities).join(' / ') || '-'}</td>
                        <td>{row.recommended_tab || '-'}</td>
                        <td>{asArray<string>(row.production_blockers).join(' / ') || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <div className="ai-demand-panel">
            <div className="ai-demand-panel-title">
              <FileText size={15} />
              <strong>边界说明</strong>
            </div>
            <div className="ai-demand-note">
              <span>需求 24/25 可引用 UWM 的宜居性影响和行动序列结果，但完整客户范围仍属于二期独立 case。</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Register the new tab in `DataPanel.tsx`**

Add import:

```tsx
import AiDemandReadinessTab from './datapanel/AiDemandReadinessTab';
```

Add `ai_demand_readiness` to `TabKey` immediately after `uwm_livability`.

Add the tab immediately after the UWM livability tab definition:

```tsx
      { key: 'ai_demand_readiness', label: 'AI应用需求矩阵', icon: <FileText size={ICON_SIZE} /> },
```

Add render branch after `<LivabilityWorldModelTab />`:

```tsx
        {activeTab === 'ai_demand_readiness' && <AiDemandReadinessTab />}
```

- [ ] **Step 5: Run frontend contract tests**

Run:

```bash
uv run pytest data_agent/test_uwm_ai_demand_readiness_frontend_contract.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add frontend/src/components/datapanel/AiDemandReadinessTab.tsx frontend/src/components/DataPanel.tsx data_agent/test_uwm_ai_demand_readiness_frontend_contract.py
git commit -m "feat: add AI demand readiness tab"
```

## Task 6: Existing Livability Tab Coverage Panels

**Files:**
- Modify: `frontend/src/components/datapanel/TraditionalLivabilityTab.tsx`
- Modify: `frontend/src/components/datapanel/LivabilityWorldModelTab.tsx`
- Modify: `data_agent/test_uwm_traditional_livability_frontend_contract.py`
- Modify: `data_agent/test_uwm_livability_world_model_frontend_contract.py`

- [ ] **Step 1: Write failing frontend contract assertions**

Append to `test_traditional_livability_tab_uses_static_analysis_api_contract`:

```python
    assert "需求场景覆盖" in text
    assert "客户需求覆盖" in text
    assert "unsupported_dynamic_requirements" in text
    assert "scenario_coverage" in text
    assert "customer_demand_coverage" in text
```

Append to `test_uwm_livability_tab_exposes_world_model_decision_contract`:

```python
    assert "UWM-only 场景覆盖" in text
    assert "生产阻塞项" in text
    assert "uwm_only_scenario_coverage" in text
    assert "production_world_model_readiness" in text
    assert "production_blockers" in text
```

- [ ] **Step 2: Run focused frontend contract tests to verify they fail**

Run:

```bash
uv run pytest data_agent/test_uwm_traditional_livability_frontend_contract.py data_agent/test_uwm_livability_world_model_frontend_contract.py -q
```

Expected: FAIL on missing UI strings.

- [ ] **Step 3: Add traditional coverage rendering**

In `TraditionalLivabilityTab.tsx`, add derived values after the line `const actionPlan = isRecord(analysis?.static_action_plan) ? analysis.static_action_plan : {};`:

```tsx
  const requirementRegistry = isRecord(analysis?.requirement_registry) ? analysis.requirement_registry : {};
  const scenarioCoverage = asArray<AnyRecord>(requirementRegistry.scenario_coverage);
  const customerDemandCoverage = asArray<AnyRecord>(requirementRegistry.customer_demand_coverage);
  const unsupportedDynamicRequirements = asArray<AnyRecord>(requirementRegistry.unsupported_dynamic_requirements);
```

Add this panel after the KPI grid:

```tsx
          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <Shield size={15} />
              <strong>需求场景覆盖</strong>
            </div>
            <div className="traditional-coverage-grid">
              {scenarioCoverage.map(row => (
                <div key={row.id}>
                  <span>{row.id} · {row.title}</span>
                  <strong>{isRecord(row.traditional_support) ? row.traditional_support.status : '-'}</strong>
                </div>
              ))}
            </div>
            <div className="traditional-coverage-note">
              <span>unsupported_dynamic_requirements</span>
              <strong>{unsupportedDynamicRequirements.map(row => row.id).join(' / ') || '-'}</strong>
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <Database size={15} />
              <strong>客户需求覆盖</strong>
            </div>
            <div className="traditional-demand-chip-row">
              {customerDemandCoverage.map(row => (
                <span key={row.id}>{row.id}. {row.title}</span>
              ))}
            </div>
          </div>
```

- [ ] **Step 4: Add UWM coverage rendering**

In `LivabilityWorldModelTab.tsx`, add derived values near other registry-like data:

```tsx
  const requirementRegistry = isRecord(payload?.requirement_registry) ? payload.requirement_registry : {};
  const uwmOnlyScenarioCoverage = asArray<AnyRecord>(requirementRegistry.uwm_only_scenario_coverage);
  const productionWorldModelReadiness = isRecord(payload?.production_world_model_readiness)
    ? payload.production_world_model_readiness
    : isRecord(requirementRegistry.production_world_model_readiness)
      ? requirementRegistry.production_world_model_readiness
      : {};
  const productionBlockers = asArray<string>(payload?.production_blockers || requirementRegistry.production_blockers);
```

Add this panel after the world-model chain panel:

```tsx
          <div className="uwm-livability-two-col">
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <Target size={15} />
                <strong>UWM-only 场景覆盖</strong>
              </div>
              <div className="uwm-capability-tags">
                {uwmOnlyScenarioCoverage.map(row => (
                  <span key={row.id}>{row.id} · {row.title}</span>
                ))}
              </div>
            </div>

            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title">
                <AlertTriangle size={15} />
                <strong>生产阻塞项</strong>
              </div>
              <div className="uwm-boundary-grid">
                <div>
                  <span>production_world_model_ready</span>
                  <strong>{String(Boolean(productionWorldModelReadiness.production_world_model_ready))}</strong>
                </div>
                <div>
                  <span>bounded_research_ready</span>
                  <strong>{String(Boolean(productionWorldModelReadiness.bounded_research_ready))}</strong>
                </div>
              </div>
              <div className="uwm-capability-tags">
                {productionBlockers.map(item => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            </div>
          </div>
```

- [ ] **Step 5: Run frontend contract tests**

Run:

```bash
uv run pytest data_agent/test_uwm_traditional_livability_frontend_contract.py data_agent/test_uwm_livability_world_model_frontend_contract.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add frontend/src/components/datapanel/TraditionalLivabilityTab.tsx frontend/src/components/datapanel/LivabilityWorldModelTab.tsx data_agent/test_uwm_traditional_livability_frontend_contract.py data_agent/test_uwm_livability_world_model_frontend_contract.py
git commit -m "feat: show livability requirement coverage in tabs"
```

## Task 7: Styling And Frontend Build

**Files:**
- Modify: `frontend/src/styles/layout.css`

- [ ] **Step 1: Add compact coverage styles**

Append to `frontend/src/styles/layout.css`:

```css
.traditional-coverage-grid,
.ai-demand-kpi-grid,
.ai-demand-boundary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.traditional-coverage-grid > div,
.traditional-coverage-note,
.ai-demand-kpi-grid > div,
.ai-demand-boundary-grid > div {
  min-width: 0;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--surface);
  padding: 8px;
}

.traditional-coverage-grid span,
.traditional-coverage-note span,
.ai-demand-kpi-grid span,
.ai-demand-boundary-grid span,
.ai-demand-note span {
  display: block;
  margin-bottom: 3px;
  font-size: 11px;
  line-height: 1.3;
  color: var(--text-secondary);
}

.traditional-coverage-grid strong,
.traditional-coverage-note strong,
.ai-demand-kpi-grid strong,
.ai-demand-boundary-grid strong {
  display: block;
  min-width: 0;
  font-size: 12.5px;
  line-height: 1.35;
  color: var(--text);
  overflow-wrap: anywhere;
}

.traditional-coverage-note {
  margin-top: 8px;
}

.traditional-demand-chip-row,
.uwm-capability-tags,
.ai-demand-note {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.traditional-demand-chip-row span,
.ai-demand-note span {
  border-radius: 6px;
  background: rgba(15, 118, 110, 0.10);
  color: #0f766e;
  padding: 3px 7px;
  font-size: 11px;
  line-height: 1.3;
}

.ai-demand-readiness-tab {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  padding-bottom: 12px;
}

.ai-demand-panel {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-elevated);
  padding: 10px;
}

.ai-demand-panel-title {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 9px;
  color: var(--text);
}

.ai-demand-panel-title strong {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  line-height: 1.35;
}

.ai-demand-message,
.ai-demand-empty {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.45;
}

.ai-demand-message.error {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.22);
  color: #b91c1c;
}

.ai-demand-empty {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
}

.ai-demand-table-wrap {
  overflow-x: auto;
}

.ai-demand-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 960px;
}

.ai-demand-table th,
.ai-demand-table td {
  border-bottom: 1px solid var(--border-light);
  padding: 7px 6px;
  text-align: left;
  vertical-align: top;
  font-size: 12px;
  line-height: 1.35;
}

.ai-demand-table th {
  color: var(--text-secondary);
  font-weight: 700;
  white-space: nowrap;
}

.ai-demand-table td {
  color: var(--text);
  overflow-wrap: anywhere;
}

@media (max-width: 960px) {
  .traditional-coverage-grid,
  .ai-demand-kpi-grid,
  .ai-demand-boundary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
```

- [ ] **Step 2: Run frontend build**

Run:

```bash
npm run build
```

from `frontend/`.

Expected: TypeScript and Vite build complete without errors.

- [ ] **Step 3: Commit Task 7**

Run:

```bash
git add frontend/src/styles/layout.css
git commit -m "style: add livability requirement coverage styles"
```

## Task 8: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run all UWM tests**

Run:

```bash
uv run pytest data_agent/test_uwm*.py -q
```

Expected: all UWM tests pass. The previous baseline was `271 passed`; the count should increase by the new tests.

- [ ] **Step 2: Run frontend build again**

Run:

```bash
npm run build
```

from `frontend/`.

Expected: build passes.

- [ ] **Step 3: Check only intended files changed**

Run:

```bash
git status --short
```

Expected: no unstaged changes from this plan. Existing unrelated dirty files from before the plan may remain; do not revert them.

- [ ] **Step 4: Final implementation summary**

Report:

```text
Implemented:
- Backend LIV 2.0 and 25-demand registry.
- Traditional and UWM API requirement coverage.
- AI demand readiness API and tab.
- Frontend coverage panels and styles.

Verified:
- uv run pytest data_agent/test_uwm*.py -q
- npm run build

Claim boundary:
- production_world_model_ready remains false.
- observed_policy_outcome_superiority_claim remains false.
- empirical_superiority_claim remains false except explicitly scoped bounded evidence already present in artifacts.
```

## Self-Review

- Spec coverage: Tasks 1-4 implement the backend registry, traditional/UWM API split, and AI demand readiness route. Tasks 5-7 implement the three frontend surfaces. Task 8 verifies the full UWM regression and frontend build.
- Scope control: This plan does not download new data, fabricate missing travel-time or policy outcome panels, or claim production world-model readiness.
- Type consistency: The registry key is always `requirement_registry`; traditional coverage uses `scenario_coverage`, `customer_demand_coverage`, and `unsupported_dynamic_requirements`; UWM coverage uses `uwm_only_scenario_coverage`, `production_world_model_readiness`, and `production_blockers`.
