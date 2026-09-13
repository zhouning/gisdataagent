# UWM Full-Admin World-Model Superiority Dossier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a machine-checkable full-admin UWM superiority dossier that aggregates the real 1017-node UWM evidence chain and supports only a bounded same-scene world-model advantage claim over traditional methods.

**Architecture:** Add a focused dossier builder that consumes existing real full-admin artifacts, extracts full-data guards, traditional baseline comparisons, world-model advantages, endpoint superiority, causal binding coverage, governance blockers, and claim boundaries into one deterministic JSON object. Add a script to regenerate the ignored data artifact and tests that fail on smoke-sized or claim-unsafe inputs.

**Tech Stack:** Python, JSON artifacts under `data/uwm_public_proxy/chongqing_central`, pytest through `/Users/zhouning/gisdataagent/.venv/bin/pytest`, repository-local imports with `PYTHONPATH=.` when running scripts from linked worktrees.

---

## File Map

- Create `data_agent/uwm/full_admin_world_model_superiority_dossier.py`
  - Defines the dossier schema.
  - Builds the full-admin evidence dossier from already-loaded artifacts.
  - Validates top-level readiness, required counts, supported claim, and forbidden claims.

- Create `data_agent/test_uwm_full_admin_world_model_superiority_dossier.py`
  - Tests generation from real local full-admin artifacts.
  - Tests that corrupting a full-admin count downgrades the claim.
  - Tests the regenerated stored artifact.

- Create `scripts/build_uwm_full_admin_world_model_superiority_dossier.py`
  - Reads existing local UWM artifacts.
  - Writes the dossier JSON and snapshot manifest under the ignored `data/` tree.

- Regenerate ignored artifacts:
  - `data/uwm_public_proxy/chongqing_central/full_admin_world_model_superiority_dossier_2026_07_09/uwm_full_admin_world_model_superiority_dossier.json`
  - `data/uwm_public_proxy/chongqing_central/full_admin_world_model_superiority_dossier_2026_07_09/snapshot_manifest.json`

---

### Task 1: Add Failing Full-Admin Dossier Tests

**Files:**
- Create: `data_agent/test_uwm_full_admin_world_model_superiority_dossier.py`

- [ ] **Step 1: Write the failing test file**

Create `data_agent/test_uwm_full_admin_world_model_superiority_dossier.py`:

```python
import copy
import json
from pathlib import Path

from data_agent.uwm.full_admin_world_model_superiority_dossier import (
    UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA,
    build_uwm_full_admin_world_model_superiority_dossier,
    validate_uwm_full_admin_world_model_superiority_dossier,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "full_admin_world_model_superiority_dossier_2026_07_09/uwm_full_admin_world_model_superiority_dossier.json"
)

SOURCE_PATHS = {
    "full_admin_graph_planner_replay": DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json",
    "full_admin_graph_drl_training_report": DATA_ROOT
    / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json",
    "full_admin_learned_world_model_rollout": DATA_ROOT
    / "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json",
    "full_admin_energy_regularized_planner_report": DATA_ROOT
    / "energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json",
    "full_admin_livability_decision_package": DATA_ROOT
    / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json",
    "livability_endpoint_suite": DATA_ROOT
    / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json",
    "full_admin_service_accessibility_surface": DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json",
    "geographic_similarity_kernel": DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json",
    "spatial_causal_question_registry": DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json",
    "production_governance_planner_binding_gate": DATA_ROOT
    / "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_payloads() -> dict:
    return {name: _read_json(path) for name, path in SOURCE_PATHS.items()}


def _build_dossier(**overrides) -> dict:
    payloads = _source_payloads()
    payloads.update(overrides)
    return build_uwm_full_admin_world_model_superiority_dossier(
        dossier_id="uwm-full-admin-world-model-superiority-dossier-test",
        created_at="2026-07-09T13:00:00Z",
        source_artifact_paths={
            name: str(path.relative_to(ROOT)) for name, path in SOURCE_PATHS.items()
        },
        **payloads,
    )


def test_full_admin_world_model_superiority_dossier_proves_bounded_system_advantage():
    dossier = _build_dossier()

    assert dossier["schema"] == UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA
    assert dossier["experiment_scope"] == "full_admin_graph"
    assert dossier["supported_claim"] == (
        "bounded_full_admin_world_model_advantage_over_traditional_methods"
    )
    assert dossier["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert dossier["observed_policy_outcome_superiority_claim"] is False
    assert dossier["empirical_superiority_claim"] is False

    guard = dossier["full_admin_scope_guard"]
    assert guard["passed"] is True
    assert guard["graph_node_count"] == 1017
    assert guard["graph_edge_count"] == 7932
    assert guard["admin_boundary_edge_count"] == 2847
    assert guard["geographic_similarity_edge_count"] == 5085
    assert guard["available_action_count"] == 1137
    assert guard["transition_count"] == 6817
    assert guard["service_surface_admin_unit_count"] == 1017
    assert guard["local_poi_point_count"] == 1194351
    assert guard["local_road_count"] == 50366
    assert guard["service_missing_admin_count"] == 0

    endpoint = dossier["endpoint_superiority_matrix"]
    assert endpoint["endpoint_suite_ready"] is True
    assert endpoint["endpoint_count"] == 3
    assert endpoint["ready_endpoint_count"] == 3
    assert endpoint["all_endpoints_beat_best_traditional"] is True
    assert endpoint["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert endpoint["min_relative_mae_reduction_vs_best_traditional"] == 0.003047
    assert {row["endpoint_id"] for row in endpoint["endpoint_rows"]} == {
        "air_quality_pm25",
        "service_point_accessibility",
        "essential_service_accessibility",
    }
    assert all(row["policy_outcome_claim"] is False for row in endpoint["endpoint_rows"])

    world = dossier["world_model_system_matrix"]
    assert world["all_required_world_model_advantages_positive"] is True
    assert world["components"]["planner_replay"]["advantage_over_static"] == 0.001436437
    assert world["components"]["risk_adjusted_planner"]["advantage_over_static"] == 0.0013756
    assert world["components"]["graph_dqn"]["advantage_over_traditional_static"] == 0.000812622
    assert world["components"]["learned_rollout_static"]["advantage_over_static"] == 0.00121167
    assert world["components"]["learned_rollout_one_step"]["advantage_over_one_step_policy"] == 0.000900135
    assert world["components"]["energy_regularized_planner"]["advantage_over_traditional_static"] == 0.001073357
    assert world["components"]["full_admin_decision_package"]["ready"] is True

    baselines = dossier["traditional_baseline_matrix"]
    assert baselines["baseline_family_count"] >= 5
    assert "final_endpoint_best_traditional_baselines" in baselines["baseline_families"]
    assert "same_scene_static_heuristic" in baselines["baseline_families"]
    assert "traditional_static_graph_mdp_policy" in baselines["baseline_families"]

    causal = dossier["causal_and_governance_gate"]
    assert causal["causal_governance_gate_ready_for_bounded_claim"] is True
    assert causal["planner_candidate_causal_binding_ready"] is True
    assert causal["planner_feasible_action_count"] == 1137
    assert causal["planner_attached_action_count"] == 1137
    assert causal["planner_missing_contract_action_count"] == 0
    assert causal["planner_policy_outcome_claim_allowed_action_count"] == 0
    assert causal["final_output_causal_binding_ready"] is True
    assert causal["final_recommended_action_count"] == 6
    assert causal["production_governance_gate_ready"] is True
    assert causal["authoritative_governance_data_closure_ready"] is False
    assert causal["production_deployment_ready"] is False
    assert causal["missing_authoritative_table_count"] == 5
    assert causal["observed_policy_outcome_superiority_claim"] is False

    claim = dossier["claim_ladder"][0]
    assert claim["claim"] == "bounded_full_admin_world_model_advantage_over_traditional_methods"
    assert claim["claim_level"] == "bounded_support"
    assert claim["allowed_in_report"] is True
    assert claim["policy_outcome_claim"] is False

    assert "observed_policy_outcome_superiority" in dossier["forbidden_claims"]
    assert "empirical_policy_superiority" in dossier["forbidden_claims"]
    assert "observed_policy_outcome_holdout_required" in dossier["remaining_gates"]
    assert "authoritative_governance_data_closure_required" in dossier["remaining_gates"]

    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_full_admin_world_model_superiority_dossier_rejects_smoke_sized_scope():
    payloads = _source_payloads()
    planner = copy.deepcopy(payloads["full_admin_graph_planner_replay"])
    planner["graph_mdp_state"]["graph_statistics"]["node_count"] = 36
    planner["full_data_guard"]["rendered_node_count"] = 36
    dossier = _build_dossier(full_admin_graph_planner_replay=planner)

    assert dossier["full_admin_scope_guard"]["passed"] is False
    assert dossier["supported_claim"] == (
        "no_full_admin_world_model_superiority_claim_supported"
    )
    assert dossier["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert "full_admin_scope_guard_failed" in dossier["remaining_gates"]
    assert dossier["observed_policy_outcome_superiority_claim"] is False
    assert dossier["empirical_superiority_claim"] is False

    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    assert validation["valid"] is True


def test_full_admin_world_model_superiority_dossier_artifact_is_full_scope_and_claim_safe():
    assert ARTIFACT_PATH.exists()
    dossier = _read_json(ARTIFACT_PATH)

    assert dossier["schema"] == UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA
    assert dossier["experiment_scope"] == "full_admin_graph"
    assert dossier["full_admin_scope_guard"]["passed"] is True
    assert dossier["full_admin_scope_guard"]["graph_node_count"] == 1017
    assert dossier["full_admin_scope_guard"]["available_action_count"] == 1137
    assert dossier["full_admin_scope_guard"]["transition_count"] == 6817
    assert dossier["full_admin_scope_guard"]["local_poi_point_count"] == 1194351
    assert dossier["world_model_system_matrix"][
        "all_required_world_model_advantages_positive"
    ] is True
    assert dossier["causal_and_governance_gate"]["planner_attached_action_count"] == 1137
    assert dossier["causal_and_governance_gate"][
        "planner_policy_outcome_claim_allowed_action_count"
    ] == 0
    assert dossier["supported_claim"] == (
        "bounded_full_admin_world_model_advantage_over_traditional_methods"
    )
    assert dossier["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert dossier["observed_policy_outcome_superiority_claim"] is False
    assert dossier["empirical_superiority_claim"] is False
    assert all(
        path.startswith("data/uwm_public_proxy/chongqing_central/")
        for path in dossier["audit_trace"]["source_artifact_paths"].values()
    )

    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    assert validation["valid"] is True
    assert validation["errors"] == []
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_full_admin_world_model_superiority_dossier.py -q
```

Expected: FAIL with `ModuleNotFoundError` because `data_agent.uwm.full_admin_world_model_superiority_dossier` does not exist yet.

- [ ] **Step 3: Commit the failing tests**

Run:

```bash
git add data_agent/test_uwm_full_admin_world_model_superiority_dossier.py
git commit -m "test: define UWM full-admin superiority dossier contract"
```

---

### Task 2: Implement The Dossier Builder

**Files:**
- Create: `data_agent/uwm/full_admin_world_model_superiority_dossier.py`

- [ ] **Step 1: Create the module with schema, builder, and validation**

Create `data_agent/uwm/full_admin_world_model_superiority_dossier.py`:

```python
"""Full-admin UWM world-model superiority dossier."""

from __future__ import annotations

from typing import Any


UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA = (
    "uwm.full_admin_world_model_superiority_dossier.v1"
)

_SUPPORTED_CLAIM = "bounded_full_admin_world_model_advantage_over_traditional_methods"
_NO_CLAIM = "no_full_admin_world_model_superiority_claim_supported"

_FORBIDDEN_CLAIMS = [
    "observed_policy_outcome_superiority",
    "empirical_policy_superiority",
    "causal_effect_identification_from_current_proxy_scene",
    "authoritative_governance_deployment_readiness",
]


def build_uwm_full_admin_world_model_superiority_dossier(
    *,
    dossier_id: str,
    created_at: str,
    full_admin_graph_planner_replay: dict[str, Any],
    full_admin_graph_drl_training_report: dict[str, Any],
    full_admin_learned_world_model_rollout: dict[str, Any],
    full_admin_energy_regularized_planner_report: dict[str, Any],
    full_admin_livability_decision_package: dict[str, Any],
    livability_endpoint_suite: dict[str, Any],
    full_admin_service_accessibility_surface: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
    spatial_causal_question_registry: dict[str, Any],
    production_governance_planner_binding_gate: dict[str, Any],
    source_artifact_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a claim-safe superiority dossier over real full-admin artifacts."""

    _require_dicts(
        {
            "full_admin_graph_planner_replay": full_admin_graph_planner_replay,
            "full_admin_graph_drl_training_report": full_admin_graph_drl_training_report,
            "full_admin_learned_world_model_rollout": full_admin_learned_world_model_rollout,
            "full_admin_energy_regularized_planner_report": full_admin_energy_regularized_planner_report,
            "full_admin_livability_decision_package": full_admin_livability_decision_package,
            "livability_endpoint_suite": livability_endpoint_suite,
            "full_admin_service_accessibility_surface": full_admin_service_accessibility_surface,
            "geographic_similarity_kernel": geographic_similarity_kernel,
            "spatial_causal_question_registry": spatial_causal_question_registry,
            "production_governance_planner_binding_gate": production_governance_planner_binding_gate,
        }
    )
    scope_guard = _full_admin_scope_guard(
        full_admin_graph_planner_replay,
        full_admin_graph_drl_training_report,
        full_admin_learned_world_model_rollout,
        full_admin_energy_regularized_planner_report,
        full_admin_service_accessibility_surface,
        geographic_similarity_kernel,
    )
    endpoint_matrix = _endpoint_superiority_matrix(livability_endpoint_suite)
    world_matrix = _world_model_system_matrix(
        full_admin_graph_planner_replay,
        full_admin_graph_drl_training_report,
        full_admin_learned_world_model_rollout,
        full_admin_energy_regularized_planner_report,
        full_admin_livability_decision_package,
        livability_endpoint_suite,
    )
    baseline_matrix = _traditional_baseline_matrix(
        full_admin_graph_planner_replay,
        full_admin_graph_drl_training_report,
        full_admin_learned_world_model_rollout,
        full_admin_energy_regularized_planner_report,
        livability_endpoint_suite,
    )
    causal_gate = _causal_and_governance_gate(
        full_admin_graph_planner_replay,
        full_admin_livability_decision_package,
        spatial_causal_question_registry,
        production_governance_planner_binding_gate,
    )
    ready = (
        scope_guard["passed"] is True
        and endpoint_matrix["endpoint_suite_ready"] is True
        and world_matrix["all_required_world_model_advantages_positive"] is True
        and causal_gate["causal_governance_gate_ready_for_bounded_claim"] is True
    )
    remaining_gates = _remaining_gates(
        scope_guard=scope_guard,
        endpoint_matrix=endpoint_matrix,
        world_matrix=world_matrix,
        causal_gate=causal_gate,
    )
    return {
        "schema": UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA,
        "dossier_id": dossier_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "full_admin_scope_guard": scope_guard,
        "traditional_baseline_matrix": baseline_matrix,
        "world_model_system_matrix": world_matrix,
        "endpoint_superiority_matrix": endpoint_matrix,
        "causal_and_governance_gate": causal_gate,
        "claim_ladder": _claim_ladder(ready),
        "supported_claim": _SUPPORTED_CLAIM if ready else _NO_CLAIM,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "Full-admin dossier aggregates real prepared renderer, Graph-MDP, "
                "simulator, planner, learned value/rollout, endpoint and governance "
                "evidence. It supports bounded same-scene world-model advantage over "
                "traditional methods, not observed policy-outcome superiority."
            ),
        },
        "forbidden_claims": list(_FORBIDDEN_CLAIMS),
        "remaining_gates": remaining_gates,
        "audit_trace": _audit_trace(source_artifact_paths or {}),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_uwm_full_admin_world_model_superiority_dossier(
    dossier: dict[str, Any],
) -> dict[str, Any]:
    """Validate the dossier contract without requiring the claim to be supported."""

    errors: list[str] = []
    if not isinstance(dossier, dict):
        return {"valid": False, "errors": ["dossier must be a dictionary"]}
    if dossier.get("schema") != UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA:
        errors.append("schema must be uwm.full_admin_world_model_superiority_dossier.v1")
    if dossier.get("experiment_scope") != "full_admin_graph":
        errors.append("experiment_scope must be full_admin_graph")
    if dossier.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must be false")
    if dossier.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false")
    forbidden = set(dossier.get("forbidden_claims") or [])
    for claim in _FORBIDDEN_CLAIMS:
        if claim not in forbidden:
            errors.append(f"forbidden_claims missing {claim}")
    supported = dossier.get("supported_claim")
    if supported == _SUPPORTED_CLAIM:
        if (dossier.get("full_admin_scope_guard") or {}).get("passed") is not True:
            errors.append("supported claim requires full_admin_scope_guard.passed")
        if (dossier.get("endpoint_superiority_matrix") or {}).get("endpoint_suite_ready") is not True:
            errors.append("supported claim requires endpoint suite readiness")
        if (
            (dossier.get("world_model_system_matrix") or {}).get(
                "all_required_world_model_advantages_positive"
            )
            is not True
        ):
            errors.append("supported claim requires positive world-model advantages")
        if (
            (dossier.get("causal_and_governance_gate") or {}).get(
                "causal_governance_gate_ready_for_bounded_claim"
            )
            is not True
        ):
            errors.append("supported claim requires causal governance gate")
    elif supported != _NO_CLAIM:
        errors.append("supported_claim has unknown value")
    return {"valid": not errors, "errors": errors}


def _full_admin_scope_guard(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    energy_planner: dict[str, Any],
    service_surface: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
) -> dict[str, Any]:
    planner_graph = ((planner.get("graph_mdp_state") or {}).get("graph_statistics") or {})
    planner_guard = planner.get("full_data_guard") or {}
    graph_training = graph_dqn.get("training_summary") or {}
    learned_training = learned_rollout.get("training_summary") or {}
    energy_guard = energy_planner.get("full_data_guard") or {}
    service_counts = service_surface.get("source_feature_counts") or {}
    service_coverage = service_surface.get("coverage") or {}
    similarity_summary = geographic_similarity_kernel.get("summary") or {}
    values = {
        "graph_node_count": _int(planner_graph.get("node_count")),
        "graph_edge_count": _int(planner_graph.get("edge_count")),
        "admin_boundary_edge_count": _int(planner_guard.get("source_admin_boundary_edge_count")),
        "geographic_similarity_edge_count": _int(similarity_summary.get("similarity_edge_count")),
        "available_action_count": _int(planner_graph.get("available_action_count")),
        "transition_count": _int((planner.get("trajectory_dataset") or {}).get("transition_count")),
        "service_surface_admin_unit_count": _int(service_surface.get("admin_unit_count")),
        "local_poi_point_count": _int(service_counts.get("poi_points")),
        "local_road_count": _int(service_counts.get("roads")),
        "service_missing_admin_count": _int(service_coverage.get("service_missing_admin_count")),
    }
    required = {
        "graph_node_count": 1017,
        "graph_edge_count": 7932,
        "admin_boundary_edge_count": 2847,
        "geographic_similarity_edge_count": 5085,
        "available_action_count": 1137,
        "transition_count": 6817,
        "service_surface_admin_unit_count": 1017,
        "local_poi_point_count": 1194351,
        "local_road_count": 50366,
        "service_missing_admin_count": 0,
    }
    mismatches = [
        {"metric": key, "expected": expected, "observed": values[key]}
        for key, expected in required.items()
        if values[key] != expected
    ]
    passed = (
        not mismatches
        and planner.get("experiment_scope") == "full_admin_graph"
        and graph_dqn.get("experiment_scope") == "full_admin_graph"
        and learned_rollout.get("experiment_scope") == "full_admin_graph"
        and energy_planner.get("experiment_scope") == "full_admin_graph"
        and service_surface.get("experiment_scope") == "full_admin_graph"
        and (planner.get("full_data_guard") or {}).get("passed") is True
        and (learned_rollout.get("full_data_guard") or {}).get("passed") is True
        and (energy_planner.get("full_data_guard") or {}).get("passed") is True
        and _int(graph_training.get("real_data_graph_node_count")) == 1017
        and _int(graph_training.get("real_data_available_action_count")) == 1137
        and _int(learned_training.get("source_graph_node_count")) == 1017
        and _int(learned_training.get("source_available_action_count")) == 1137
        and _int(energy_guard.get("available_action_count")) == 1137
    )
    return {
        "passed": passed,
        "required_scope": "full_admin_graph",
        **values,
        "mismatches": mismatches,
    }


def _traditional_baseline_matrix(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    energy_planner: dict[str, Any],
    endpoint_suite: dict[str, Any],
) -> dict[str, Any]:
    endpoint_baselines = [
        {
            "endpoint_id": endpoint.get("endpoint_id"),
            "best_traditional_baseline": endpoint.get("best_traditional_baseline"),
            "best_traditional_baseline_mae": _float(endpoint.get("best_traditional_baseline_mae")),
            "uwm_mae": _float(endpoint.get("uwm_mae")),
        }
        for endpoint in endpoint_suite.get("endpoint_evaluations") or []
    ]
    families = {
        "final_endpoint_best_traditional_baselines": endpoint_baselines,
        "same_scene_static_heuristic": {
            "static_single_step_reward": _float(
                (planner.get("static_single_step_baseline") or {}).get("cumulative_reward")
            ),
        },
        "traditional_static_graph_mdp_policy": {
            "traditional_static_cumulative_reward": _float(
                (graph_dqn.get("baseline_evaluation") or {}).get(
                    "traditional_static_cumulative_reward"
                )
            ),
        },
        "learned_rollout_static_and_one_step_baselines": {
            "imagined_advantage_over_static_single_step": _float(
                (learned_rollout.get("learned_rollout_planner") or {}).get(
                    "imagined_advantage_over_static_single_step"
                )
            ),
            "imagined_advantage_over_one_step_policy": _float(
                (learned_rollout.get("learned_rollout_planner") or {}).get(
                    "imagined_advantage_over_one_step_policy"
                )
            ),
        },
        "energy_regularized_traditional_static": {
            "advantage_over_traditional_static": _float(
                (energy_planner.get("selected_sequence") or {}).get(
                    "advantage_over_traditional_static"
                )
            ),
        },
    }
    return {
        "baseline_family_count": len(families),
        "baseline_families": families,
    }


def _world_model_system_matrix(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    energy_planner: dict[str, Any],
    decision_package: dict[str, Any],
    endpoint_suite: dict[str, Any],
) -> dict[str, Any]:
    risk = planner.get("risk_adjusted_planner_evaluation") or {}
    graph_learned = graph_dqn.get("learned_policy_evaluation") or {}
    learned_planner = learned_rollout.get("learned_rollout_planner") or {}
    energy_selected = energy_planner.get("selected_sequence") or {}
    components = {
        "planner_replay": {
            "ready": planner.get("supported_claim") == "full_admin_graph_planner_replay_advantage_over_static_heuristic",
            "advantage_over_static": _float(planner.get("advantage_over_static_single_step")),
            "observed_policy_outcome_superiority_claim": False,
        },
        "risk_adjusted_planner": {
            "ready": risk.get("risk_calibrated_planner_replay_ready") is True,
            "advantage_over_static": _float(risk.get("risk_adjusted_advantage_over_static_single_step")),
            "observed_policy_outcome_superiority_claim": False,
        },
        "graph_dqn": {
            "ready": graph_dqn.get("experiment_scope") == "full_admin_graph",
            "advantage_over_traditional_static": _float(
                graph_learned.get("advantage_over_traditional_static")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "learned_rollout_static": {
            "ready": learned_rollout.get("experiment_scope") == "full_admin_graph",
            "advantage_over_static": _float(
                learned_planner.get("imagined_advantage_over_static_single_step")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "learned_rollout_one_step": {
            "ready": learned_rollout.get("experiment_scope") == "full_admin_graph",
            "advantage_over_one_step_policy": _float(
                learned_planner.get("imagined_advantage_over_one_step_policy")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "energy_regularized_planner": {
            "ready": energy_planner.get("full_admin_energy_regularized_planner_ready") is True,
            "advantage_over_traditional_static": _float(
                energy_selected.get("advantage_over_traditional_static")
            ),
            "observed_policy_outcome_superiority_claim": False,
        },
        "full_admin_decision_package": {
            "ready": decision_package.get("full_admin_decision_package_ready") is True,
            "supported_claim": decision_package.get("supported_claim"),
            "observed_policy_outcome_superiority_claim": False,
        },
        "final_endpoint_suite": {
            "ready": endpoint_suite.get("all_endpoints_beat_traditional_baselines") is True,
            "supported_claim": endpoint_suite.get("supported_claim"),
            "observed_policy_outcome_superiority_claim": False,
        },
    }
    required_positive = [
        components["planner_replay"]["advantage_over_static"],
        components["risk_adjusted_planner"]["advantage_over_static"],
        components["graph_dqn"]["advantage_over_traditional_static"],
        components["learned_rollout_static"]["advantage_over_static"],
        components["learned_rollout_one_step"]["advantage_over_one_step_policy"],
        components["energy_regularized_planner"]["advantage_over_traditional_static"],
    ]
    return {
        "components": components,
        "all_required_world_model_advantages_positive": all(
            value > 0.0 for value in required_positive
        )
        and all(component.get("ready") is True for component in components.values()),
    }


def _endpoint_superiority_matrix(endpoint_suite: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "endpoint_id": endpoint.get("endpoint_id"),
            "domain": endpoint.get("domain"),
            "uwm_model": endpoint.get("uwm_model"),
            "uwm_mae": _float(endpoint.get("uwm_mae")),
            "best_traditional_baseline": endpoint.get("best_traditional_baseline"),
            "best_traditional_baseline_mae": _float(endpoint.get("best_traditional_baseline_mae")),
            "relative_mae_reduction_vs_best_traditional": _float(
                endpoint.get("relative_mae_reduction_vs_best_traditional")
            ),
            "beats_traditional_baselines": bool(
                endpoint.get("beats_traditional_baselines")
            ),
            "policy_outcome_claim": bool(endpoint.get("policy_outcome_claim")),
        }
        for endpoint in endpoint_suite.get("endpoint_evaluations") or []
    ]
    all_ready = (
        endpoint_suite.get("schema") == "uwm.livability_endpoint_suite.v1"
        and _int(endpoint_suite.get("endpoint_count")) >= 3
        and _int(endpoint_suite.get("endpoint_count")) == len(rows)
        and _int(endpoint_suite.get("ready_endpoint_count")) == len(rows)
        and bool(rows)
        and all(row["beats_traditional_baselines"] is True for row in rows)
        and all(row["policy_outcome_claim"] is False for row in rows)
        and _float(endpoint_suite.get("mean_relative_mae_reduction_vs_best_traditional")) > 0.0
        and _float(endpoint_suite.get("min_relative_mae_reduction_vs_best_traditional")) > 0.0
    )
    return {
        "endpoint_suite_ready": all_ready,
        "endpoint_count": _int(endpoint_suite.get("endpoint_count")),
        "ready_endpoint_count": _int(endpoint_suite.get("ready_endpoint_count")),
        "all_endpoints_beat_best_traditional": all(
            row["beats_traditional_baselines"] is True for row in rows
        ),
        "mean_relative_mae_reduction_vs_best_traditional": _float(
            endpoint_suite.get("mean_relative_mae_reduction_vs_best_traditional")
        ),
        "min_relative_mae_reduction_vs_best_traditional": _float(
            endpoint_suite.get("min_relative_mae_reduction_vs_best_traditional")
        ),
        "endpoint_rows": rows,
        "observed_policy_outcome_superiority_claim": False,
    }


def _causal_and_governance_gate(
    planner: dict[str, Any],
    decision_package: dict[str, Any],
    spatial_causal_question_registry: dict[str, Any],
    governance_gate: dict[str, Any],
) -> dict[str, Any]:
    planner_binding = planner.get("spatial_causal_contract_binding") or {}
    final_binding = decision_package.get("spatial_causal_contract_binding") or {}
    governance_summary = governance_gate.get("summary") or {}
    planner_ready = (
        planner_binding.get("binding_ready") is True
        and _int(planner_binding.get("feasible_action_count")) == 1137
        and _int(planner_binding.get("attached_action_count")) == 1137
        and _int(planner_binding.get("missing_contract_action_count")) == 0
        and _int(planner_binding.get("policy_outcome_claim_allowed_action_count")) == 0
    )
    final_ready = (
        final_binding.get("binding_ready") is True
        and _int(final_binding.get("recommended_action_count")) == _int(
            final_binding.get("attached_action_count")
        )
        and _int(final_binding.get("missing_contract_action_count")) == 0
        and _int(final_binding.get("policy_outcome_claim_allowed_action_count")) == 0
    )
    governance_ready = (
        governance_gate.get("schema") == "uwm.production_governance_planner_binding_gate.v1"
        and governance_gate.get("experiment_scope") == "full_admin_graph"
        and governance_gate.get("binding_gate_ready") is True
        and _int(governance_summary.get("required_gate_count")) == 9
    )
    return {
        "causal_governance_gate_ready_for_bounded_claim": (
            planner_ready
            and final_ready
            and governance_ready
            and spatial_causal_question_registry.get("registry_ready") is True
        ),
        "spatial_causal_registry_ready": spatial_causal_question_registry.get("registry_ready") is True,
        "planner_candidate_causal_binding_ready": planner_ready,
        "planner_feasible_action_count": _int(planner_binding.get("feasible_action_count")),
        "planner_attached_action_count": _int(planner_binding.get("attached_action_count")),
        "planner_missing_contract_action_count": _int(planner_binding.get("missing_contract_action_count")),
        "planner_underidentified_policy_effect_action_count": _int(
            planner_binding.get("underidentified_policy_effect_action_count")
        ),
        "planner_policy_outcome_claim_allowed_action_count": _int(
            planner_binding.get("policy_outcome_claim_allowed_action_count")
        ),
        "final_output_causal_binding_ready": final_ready,
        "final_recommended_action_count": _int(final_binding.get("recommended_action_count")),
        "final_attached_action_count": _int(final_binding.get("attached_action_count")),
        "production_governance_gate_ready": governance_ready,
        "authoritative_governance_data_closure_ready": bool(
            governance_gate.get("authoritative_governance_data_closure_ready")
        ),
        "production_planner_governance_binding_ready": bool(
            governance_gate.get("planner_governance_binding_ready")
        ),
        "production_deployment_ready": bool(
            governance_gate.get("authoritative_governance_data_closure_ready")
        )
        and bool(governance_gate.get("planner_governance_binding_ready")),
        "missing_authoritative_table_count": _int(
            governance_summary.get("missing_table_count")
        ),
        "accepted_authoritative_row_count": _int(
            governance_summary.get("accepted_authoritative_row_count")
        ),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _claim_ladder(ready: bool) -> list[dict[str, Any]]:
    return [
        {
            "claim": _SUPPORTED_CLAIM,
            "scope": "full_admin_graph_same_scene",
            "claim_level": "bounded_support" if ready else "not_for_claim",
            "allowed_in_report": ready,
            "policy_outcome_claim": False,
            "spatial_attribution_claim": False,
        }
    ]


def _remaining_gates(
    *,
    scope_guard: dict[str, Any],
    endpoint_matrix: dict[str, Any],
    world_matrix: dict[str, Any],
    causal_gate: dict[str, Any],
) -> list[str]:
    gates = [
        "observed_policy_outcome_holdout_required",
        "off_policy_evaluation_on_real_intervention_logs_required",
        "causal_policy_effect_validation_required",
        "authoritative_governance_data_closure_required",
    ]
    if scope_guard.get("passed") is not True:
        gates.append("full_admin_scope_guard_failed")
    if endpoint_matrix.get("endpoint_suite_ready") is not True:
        gates.append("endpoint_superiority_matrix_failed")
    if world_matrix.get("all_required_world_model_advantages_positive") is not True:
        gates.append("world_model_system_matrix_failed")
    if causal_gate.get("causal_governance_gate_ready_for_bounded_claim") is not True:
        gates.append("causal_and_governance_gate_failed")
    if causal_gate.get("production_deployment_ready") is not True:
        gates.append("production_deployment_readiness_blocked")
    return gates


def _audit_trace(source_artifact_paths: dict[str, str]) -> dict[str, Any]:
    return {
        "source_artifact_paths": dict(sorted(source_artifact_paths.items())),
        "artifact_path_policy": "local_prepared_full_admin_artifacts_no_network_download",
        "data_claim_policy": (
            "bounded same-scene world-model superiority only; observed policy "
            "outcome superiority remains forbidden"
        ),
    }


def _require_dicts(payloads: dict[str, Any]) -> None:
    for name, payload in payloads.items():
        if not isinstance(payload, dict):
            raise TypeError(f"{name} must be a dictionary")


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return round(float(value), 9)
    except (TypeError, ValueError):
        return default
```

- [ ] **Step 2: Run the focused tests and verify GREEN for generated object tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_full_admin_world_model_superiority_dossier.py::test_full_admin_world_model_superiority_dossier_proves_bounded_system_advantage data_agent/test_uwm_full_admin_world_model_superiority_dossier.py::test_full_admin_world_model_superiority_dossier_rejects_smoke_sized_scope -q
```

Expected: PASS for the first two tests. The stored artifact test still fails until Task 3 regenerates the artifact.

- [ ] **Step 3: Commit the builder module**

Run:

```bash
git add data_agent/uwm/full_admin_world_model_superiority_dossier.py
git commit -m "feat: build UWM full-admin superiority dossier"
```

---

### Task 3: Add The Artifact Builder Script

**Files:**
- Create: `scripts/build_uwm_full_admin_world_model_superiority_dossier.py`

- [ ] **Step 1: Write the script**

Create `scripts/build_uwm_full_admin_world_model_superiority_dossier.py`:

```python
"""Build the full-admin UWM world-model superiority dossier."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.full_admin_world_model_superiority_dossier import (
    build_uwm_full_admin_world_model_superiority_dossier,
    validate_uwm_full_admin_world_model_superiority_dossier,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "full_admin_world_model_superiority_dossier_2026_07_09"
OUTPUT_PATH = OUTPUT_DIR / "uwm_full_admin_world_model_superiority_dossier.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

SOURCE_PATHS = {
    "full_admin_graph_planner_replay": DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json",
    "full_admin_graph_drl_training_report": DATA_ROOT
    / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json",
    "full_admin_learned_world_model_rollout": DATA_ROOT
    / "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json",
    "full_admin_energy_regularized_planner_report": DATA_ROOT
    / "energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json",
    "full_admin_livability_decision_package": DATA_ROOT
    / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json",
    "livability_endpoint_suite": DATA_ROOT
    / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json",
    "full_admin_service_accessibility_surface": DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json",
    "geographic_similarity_kernel": DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json",
    "spatial_causal_question_registry": DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json",
    "production_governance_planner_binding_gate": DATA_ROOT
    / "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    sources = {name: _read_json(path) for name, path in SOURCE_PATHS.items()}
    dossier = build_uwm_full_admin_world_model_superiority_dossier(
        dossier_id="uwm-full-admin-world-model-superiority-dossier-2026-07-09",
        created_at="2026-07-09T13:00:00Z",
        source_artifact_paths={
            name: str(path.relative_to(REPO_ROOT)) for name, path in SOURCE_PATHS.items()
        },
        **sources,
    )
    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    if validation["valid"] is not True:
        raise SystemExit(f"invalid UWM superiority dossier: {validation['errors']}")
    _write_json(OUTPUT_PATH, dossier)
    manifest = {
        "schema": "uwm.snapshot_manifest.v1",
        "snapshot_id": "uwm_full_admin_world_model_superiority_dossier_2026_07_09",
        "created_at": "2026-07-09T13:00:00Z",
        "artifact_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_artifact_paths": {
            name: str(path.relative_to(REPO_ROOT)) for name, path in SOURCE_PATHS.items()
        },
        "supported_claim": dossier["supported_claim"],
        "claim_boundary": dossier["claim_boundary"],
        "full_admin_scope_guard": dossier["full_admin_scope_guard"],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "supported_claim": dossier["supported_claim"],
                "graph_node_count": dossier["full_admin_scope_guard"]["graph_node_count"],
                "available_action_count": dossier["full_admin_scope_guard"]["available_action_count"],
                "transition_count": dossier["full_admin_scope_guard"]["transition_count"],
                "planner_attached_action_count": dossier["causal_and_governance_gate"]["planner_attached_action_count"],
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script**

Run:

```bash
env PYTHONPATH=. /Users/zhouning/gisdataagent/.venv/bin/python scripts/build_uwm_full_admin_world_model_superiority_dossier.py
```

Expected output includes:

```text
"graph_node_count": 1017
"available_action_count": 1137
"transition_count": 6817
"planner_attached_action_count": 1137
"observed_policy_outcome_superiority_claim": false
```

- [ ] **Step 3: Run the focused artifact tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_full_admin_world_model_superiority_dossier.py -q
```

Expected: `3 passed`.

- [ ] **Step 4: Commit the script**

Run:

```bash
git add scripts/build_uwm_full_admin_world_model_superiority_dossier.py
git commit -m "feat: regenerate UWM full-admin superiority dossier"
```

Do not force-add the generated `data/` artifact unless the user explicitly asks for large ignored artifacts to be versioned.

---

### Task 4: Verify Integration With Existing UWM Evidence Gates

**Files:**
- Modify only if tests reveal a real gate omission:
  - `data_agent/test_uwm_overall_system_superiority.py`
  - `data_agent/uwm/world_model_evidence_readiness.py`
  - `data_agent/uwm/data_foundation_evidence_gate.py`

- [ ] **Step 1: Run the existing system-level tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_overall_system_superiority.py data_agent/test_uwm_data_foundation_evidence_gate.py data_agent/test_uwm_full_admin_livability_decision_package.py -q
```

Expected: PASS. If these fail because of the new dossier contract, inspect the failing assertion before changing code. The dossier should be additive; it should not weaken existing evidence gates.

- [ ] **Step 2: Check whether the readiness summary should mention the dossier**

Run:

```bash
rg -n "full_admin_world_model_superiority|bounded_final_system_superiority|full_admin_livability_decision_package" data_agent/uwm data_agent/test_uwm_*.py
```

Expected: The new dossier appears only in its test and builder unless Task 4 Step 1 reveals a real integration need. Do not add broad evidence-gate wiring unless a test demonstrates that the existing readiness output is now incomplete or inconsistent.

- [ ] **Step 3: Commit any integration change, or skip commit if no code changed**

If changes are required, run:

```bash
git add data_agent/test_uwm_overall_system_superiority.py data_agent/uwm/world_model_evidence_readiness.py data_agent/uwm/data_foundation_evidence_gate.py
git commit -m "feat: surface UWM full-admin superiority dossier readiness"
```

If no changes are required, record that the dossier is additive and leave the repository unchanged for this task.

---

### Task 5: Full Verification And Cleanup

**Files:**
- No new source files expected.

- [ ] **Step 1: Run the full UWM suite**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_*.py -q
```

Expected: all UWM tests pass. On the current baseline before this plan, the suite reported `261 passed`; after adding this test file the expected count is at least `264 passed`, plus any unrelated existing skipped tests.

- [ ] **Step 2: Inspect git status for scoped changes only**

Run:

```bash
git status --short data_agent/uwm/full_admin_world_model_superiority_dossier.py data_agent/test_uwm_full_admin_world_model_superiority_dossier.py scripts/build_uwm_full_admin_world_model_superiority_dossier.py docs/superpowers/plans/2026-07-09-uwm-full-admin-world-model-superiority-dossier.md docs/superpowers/specs/2026-07-09-uwm-full-admin-world-model-superiority-dossier-design.md
```

Expected: tracked source/docs changes are committed or intentionally staged. The ignored generated dossier under `data/` is not listed.

- [ ] **Step 3: Summarize evidence without overclaiming**

Report:

- focused dossier test result;
- full UWM test result;
- generated artifact path and key counts;
- supported bounded claim;
- forbidden observed policy / empirical policy claims;
- remaining gates for true observed policy superiority.

Do not state that UWM has factual observed policy superiority unless authoritative intervention and outcome validation data are actually present and the governance gate supports that upgrade.
