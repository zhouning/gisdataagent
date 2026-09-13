# UWM Planner Causal Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce spatial causal-question binding inside UWM model-based planner search reports so candidate actions, replay transitions, best sequences, and static baselines are claim-safe before they reach decision packages.

**Architecture:** Reuse `data_agent.uwm.spatial_causal_action_binding` as the single binding implementation. `plan_with_model_based_graph_search` will accept a spatial causal registry, enrich every feasible action before search, emit a planner-level binding summary, and downgrade claims when binding is absent or unsafe. The full-admin build script will pass the existing 2026-07-09 registry artifact and regenerate the full-admin planner replay without reducing the 1017-node scope.

**Tech Stack:** Python, pytest, existing UWM JSON artifacts under `data/uwm_public_proxy/chongqing_central`, `uv run` for test and script execution.

---

## File Map

- Modify `data_agent/uwm/model_based_rl.py`
  - Add optional `spatial_causal_question_registry` input.
  - Bind feasible actions before beam search.
  - Emit `spatial_causal_contract_binding`.
  - Require binding readiness for supported planner claims.

- Modify `scripts/build_uwm_full_admin_graph_planner_replay.py`
  - Read `spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json`.
  - Pass registry into planner.
  - Include registry path and binding summary in manifest output.

- Modify `data_agent/test_uwm_data_calibrated_planner_replay.py`
  - Add a 36-node causally bound planner test.
  - Add a missing-registry claim downgrade test.

- Modify `data_agent/test_uwm_full_admin_graph_planner_replay.py`
  - Assert the stored 1017-node artifact has candidate-level binding for all 1137 actions.
  - Assert replay transition, best sequence, and static baseline actions include causal fields.

- Regenerate:
  - `data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json`
  - `data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/snapshot_manifest.json`

---

### Task 1: Add Failing Planner Causal-Binding Tests

**Files:**
- Modify: `data_agent/test_uwm_data_calibrated_planner_replay.py`

- [ ] **Step 1: Add the spatial causal registry fixture path**

Add this constant after `SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH`:

```python
SPATIAL_CAUSAL_REGISTRY_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
)
```

- [ ] **Step 2: Extend the test report builder to pass a registry when supplied**

Replace `_build_calibrated_report` with this signature and body:

```python
def _build_calibrated_report(
    *,
    air_quality_uncertainty_context: dict | None = None,
    spatial_causal_question_registry: dict | None = None,
) -> dict:
    graph = _load_json(ADMIN_GRAPH_PATH)
    panel = _load_json(ADMIN_PANEL_PATH)
    mechanism_table = _load_json(MECHANISM_TABLE_PATH)
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-data-calibrated-graph-mdp-test",
        created_at="2026-07-06T19:00:00Z",
        max_units=36,
        admin_spatial_graph=graph,
    )
    kwargs = {}
    if air_quality_uncertainty_context is not None:
        kwargs["air_quality_uncertainty_context"] = air_quality_uncertainty_context
    if spatial_causal_question_registry is not None:
        kwargs["spatial_causal_question_registry"] = spatial_causal_question_registry
    return plan_with_model_based_graph_search(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "data_calibrated_heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        beam_width=5,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=mechanism_table,
        **kwargs,
    )
```

- [ ] **Step 3: Add the failing test for successful registry binding**

Append this test after `test_data_calibrated_graph_search_uses_mechanism_table_and_beats_static`:

```python
def test_data_calibrated_graph_search_binds_actions_to_spatial_causal_contracts():
    registry = _load_json(SPATIAL_CAUSAL_REGISTRY_PATH)
    report = _build_calibrated_report(spatial_causal_question_registry=registry)

    binding = report["spatial_causal_contract_binding"]
    candidate_count = report["search_config"]["candidate_action_count"]
    assert binding["binding_ready"] is True
    assert binding["registry_ready"] is True
    assert binding["feasible_action_count"] == candidate_count
    assert binding["attached_action_count"] == candidate_count
    assert binding["missing_contract_action_count"] == 0
    assert binding["underidentified_policy_effect_action_count"] == candidate_count
    assert binding["identified_policy_effect_action_count"] == 0
    assert binding["policy_outcome_claim_allowed_action_count"] == 0

    for action in report["best_sequence"]["action_sequence"]:
        assert action["causal_question_id"]
        assert "do(" in action["causal_query"]
        assert action["primary_outcome"]
        assert action["identification_status"] == (
            "underidentified_for_observed_policy_effect"
        )
        assert action["required_authoritative_tables"] == [
            "policy_project_history",
            "action_constraint_cost_model",
            "observed_outcome_validation_panel",
            "causal_effect_calibration_panel",
            "human_governance_review_log",
        ]
        assert action["policy_outcome_claim_allowed"] is False
        assert action["observed_policy_outcome_superiority_claim"] is False
        assert action["empirical_superiority_claim"] is False

    static_action = report["static_single_step_baseline"]["action_sequence"][0]
    assert static_action["action_id"].startswith("static-")
    assert static_action["causal_question_id"]
    assert static_action["policy_outcome_claim_allowed"] is False

    first_transition_action = report["trajectory_dataset"]["transitions"][0]["action"]
    assert first_transition_action["causal_question_id"]
    assert first_transition_action["policy_outcome_claim_allowed"] is False
```

- [ ] **Step 4: Add the failing test for missing-registry claim downgrade**

Append this test after the binding test:

```python
def test_graph_search_without_spatial_causal_registry_blocks_planner_advantage_claim():
    report = _build_calibrated_report()

    assert report["advantage_over_static_single_step"] > 0
    binding = report["spatial_causal_contract_binding"]
    assert binding["binding_ready"] is False
    assert binding["registry_ready"] is False
    assert binding["missing_contract_action_count"] == report["search_config"][
        "candidate_action_count"
    ]
    assert report["supported_claim"] == (
        "no_model_based_graph_search_advantage_claim_supported"
    )
    assert report["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert "spatial_causal_question_registry_binding_required" in report[
        "remaining_gates"
    ]
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False
```

- [ ] **Step 5: Run the new tests and verify they fail for the expected reason**

Run:

```bash
uv run pytest data_agent/test_uwm_data_calibrated_planner_replay.py::test_data_calibrated_graph_search_binds_actions_to_spatial_causal_contracts data_agent/test_uwm_data_calibrated_planner_replay.py::test_graph_search_without_spatial_causal_registry_blocks_planner_advantage_claim -q
```

Expected: FAIL because `plan_with_model_based_graph_search` does not yet accept `spatial_causal_question_registry` and does not yet emit `spatial_causal_contract_binding`.

---

### Task 2: Implement Planner-Level Causal Binding

**Files:**
- Modify: `data_agent/uwm/model_based_rl.py`

- [ ] **Step 1: Import the binding helpers**

Add this import block near the existing UWM imports:

```python
from .spatial_causal_action_binding import (
    action_with_spatial_causal_contract,
    causal_contracts_by_action_type,
    spatial_causal_action_binding_summary,
)
```

- [ ] **Step 2: Add the registry parameter to the planner function**

Change the `plan_with_model_based_graph_search` signature so the tail of the argument list is:

```python
    spatial_spillover_kernel: dict[str, Any] | None = None,
    transition_storage: str = "full",
    spatial_causal_question_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

- [ ] **Step 3: Bind feasible actions immediately after Graph-MDP state construction**

Replace:

```python
    graph_state = build_graph_mdp_state(observation, action_types=action_types, thresholds=thresholds)
    candidates = list(graph_state["available_actions"])
```

with:

```python
    graph_state = build_graph_mdp_state(
        observation,
        action_types=action_types,
        thresholds=thresholds,
    )
    causal_contracts = causal_contracts_by_action_type(
        spatial_causal_question_registry or {}
    )
    candidates = [
        action_with_spatial_causal_contract(action, causal_contracts)
        for action in graph_state["available_actions"]
    ]
    graph_state = {
        **graph_state,
        "available_actions": candidates,
    }
    spatial_causal_binding = spatial_causal_action_binding_summary(
        spatial_causal_question_registry=spatial_causal_question_registry or {},
        actions=candidates,
        total_action_count_key="feasible_action_count",
    )
```

- [ ] **Step 4: Require binding readiness for supported planner claims**

Replace the existing `supported_claim = (...)` assignment with:

```python
    binding_ready = spatial_causal_binding["binding_ready"] is True
    planner_claim_ready = advantage > 0 and evidence_grade != "not_for_claim" and binding_ready
    supported_claim = (
        (
            "data_calibrated_model_based_graph_search_advantage_over_static_heuristic"
            if mechanism_summary["data_calibrated_mechanism_ready"]
            else "known_effect_model_based_graph_search_advantage"
        )
        if planner_claim_ready
        else "no_model_based_graph_search_advantage_claim_supported"
    )
```

- [ ] **Step 5: Emit the binding summary and downgraded claim boundary**

In the returned dictionary, add this top-level key after `air_quality_uncertainty_calibration_summary`:

```python
        "spatial_causal_contract_binding": spatial_causal_binding,
```

Replace the current claim boundary block with:

```python
        "claim_boundary": {
            "max_claim_level": evidence_grade if planner_claim_ready else "not_for_claim",
            "reason": (
                "model-based graph search uses data-calibrated simulator rollouts "
                "and every feasible planner action is bound to spatial causal "
                "question contracts; observed policy outcome gates remain open"
                if mechanism_summary["data_calibrated_mechanism_ready"]
                and binding_ready
                else (
                    "model-based graph search uses simulator rollouts and every "
                    "feasible planner action is bound to spatial causal question "
                    "contracts; observed policy outcome gates remain open"
                    if binding_ready
                    else "model-based graph search claim is blocked because spatial causal question registry binding is not ready"
                )
            ),
        },
```

Replace the existing `remaining_gates` list with:

```python
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "learned_dynamics_model_required",
            "offline_policy_evaluation_required",
            "causal_policy_effect_validation_required",
            *(
                []
                if binding_ready
                else ["spatial_causal_question_registry_binding_required"]
            ),
        ],
```

- [ ] **Step 6: Run the new planner tests and verify they pass**

Run:

```bash
uv run pytest data_agent/test_uwm_data_calibrated_planner_replay.py::test_data_calibrated_graph_search_binds_actions_to_spatial_causal_contracts data_agent/test_uwm_data_calibrated_planner_replay.py::test_graph_search_without_spatial_causal_registry_blocks_planner_advantage_claim -q
```

Expected: PASS.

- [ ] **Step 7: Run the existing calibrated planner tests**

Run:

```bash
uv run pytest data_agent/test_uwm_data_calibrated_planner_replay.py -q
```

Expected: PASS. Existing tests that build without a registry should now expect no planner advantage claim only where explicitly asserted by the new missing-registry test. If an older test still asserts the positive supported claim without passing a registry, change that test to pass `spatial_causal_question_registry=_load_json(SPATIAL_CAUSAL_REGISTRY_PATH)` because claim-ready replay now requires causal binding.

- [ ] **Step 8: Commit Task 1 and Task 2 together**

Run:

```bash
git add data_agent/uwm/model_based_rl.py data_agent/test_uwm_data_calibrated_planner_replay.py
git commit -m "feat: bind UWM planner search actions to causal contracts"
```

Expected: one commit containing the planner code and focused tests.

---

### Task 3: Wire The Full-Admin Build Script To The Registry

**Files:**
- Modify: `scripts/build_uwm_full_admin_graph_planner_replay.py`

- [ ] **Step 1: Add the registry path constant**

Add this constant after `SCENE_AIR_QUALITY_HOLDOUT_PATH`:

```python
SPATIAL_CAUSAL_REGISTRY_PATH = (
    DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
)
```

- [ ] **Step 2: Load the registry in `main`**

After:

```python
    air_quality_holdout = _read_json(SCENE_AIR_QUALITY_HOLDOUT_PATH)
```

add:

```python
    spatial_causal_registry = _read_json(SPATIAL_CAUSAL_REGISTRY_PATH)
```

- [ ] **Step 3: Pass the registry into planner search**

Add this keyword to the `plan_with_model_based_graph_search(...)` call:

```python
        spatial_causal_question_registry=spatial_causal_registry,
```

- [ ] **Step 4: Add registry lineage to the report**

After `report["source_air_quality_holdout_path"] = ...`, add:

```python
    report["source_spatial_causal_question_registry_path"] = str(
        SPATIAL_CAUSAL_REGISTRY_PATH.relative_to(REPO_ROOT)
    )
    report["source_spatial_causal_question_registry_summary"] = (
        spatial_causal_registry.get("summary") or {}
    )
```

- [ ] **Step 5: Add registry lineage and binding summary to the manifest**

Inside the manifest `source_artifacts` object, add:

```python
                "spatial_causal_question_registry": report[
                    "source_spatial_causal_question_registry_path"
                ],
```

After `"search_config": report["search_config"],`, add:

```python
            "spatial_causal_contract_binding": report[
                "spatial_causal_contract_binding"
            ],
```

- [ ] **Step 6: Run the full-admin builder**

Run:

```bash
uv run python scripts/build_uwm_full_admin_graph_planner_replay.py
```

Expected stdout includes:

```text
"node_count": 1017
"available_action_count": 1137
"edge_count": 7932
"transition_count": 6817
```

---

### Task 4: Add Full-Admin Artifact Tests

**Files:**
- Modify: `data_agent/test_uwm_full_admin_graph_planner_replay.py`

- [ ] **Step 1: Assert stored artifact candidate-level binding**

Append this test after `test_full_admin_graph_planner_replay_uses_all_admin_nodes`:

```python
def test_full_admin_graph_planner_replay_binds_all_feasible_actions_to_causal_contracts():
    assert REPORT_PATH.exists()
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    binding = report["spatial_causal_contract_binding"]
    assert binding["binding_ready"] is True
    assert binding["registry_ready"] is True
    assert binding["feasible_action_count"] == 1137
    assert binding["attached_action_count"] == 1137
    assert binding["missing_contract_action_count"] == 0
    assert binding["underidentified_policy_effect_action_count"] == 1137
    assert binding["identified_policy_effect_action_count"] == 0
    assert binding["policy_outcome_claim_allowed_action_count"] == 0
    assert binding["action_type_counts"] == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }
    assert binding["required_authoritative_tables"] == [
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    ]
    assert report["supported_claim"] == (
        "data_calibrated_model_based_graph_search_advantage_over_static_heuristic"
    )
    assert "spatial_causal_question_registry_binding_required" not in report[
        "remaining_gates"
    ]
```

- [ ] **Step 2: Assert transitions and sequences carry causal fields**

Append this test after the binding test:

```python
def test_full_admin_graph_planner_replay_action_traces_are_causally_auditable():
    assert REPORT_PATH.exists()
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    actions = []
    actions.extend(report["best_sequence"]["action_sequence"])
    actions.extend(report["static_single_step_baseline"]["action_sequence"])
    actions.append(report["trajectory_dataset"]["transitions"][0]["action"])

    for action in actions:
        assert action["causal_question_id"]
        assert "do(" in action["causal_query"]
        assert action["primary_outcome"]
        assert action["identification_status"] == (
            "underidentified_for_observed_policy_effect"
        )
        assert action["required_authoritative_tables"] == [
            "policy_project_history",
            "action_constraint_cost_model",
            "observed_outcome_validation_panel",
            "causal_effect_calibration_panel",
            "human_governance_review_log",
        ]
        assert action["policy_outcome_claim_allowed"] is False
        assert action["observed_policy_outcome_superiority_claim"] is False
        assert action["empirical_superiority_claim"] is False

    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False
```

- [ ] **Step 3: Run full-admin planner artifact tests**

Run:

```bash
uv run pytest data_agent/test_uwm_full_admin_graph_planner_replay.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit script, artifact, and artifact tests**

Run:

```bash
git add scripts/build_uwm_full_admin_graph_planner_replay.py data_agent/test_uwm_full_admin_graph_planner_replay.py data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/snapshot_manifest.json
git commit -m "feat: regenerate UWM full-admin planner causal trace"
```

Expected: one commit containing the full-admin builder wiring, regenerated artifacts, and artifact assertions.

---

### Task 5: Verify Downstream Evidence Gates Stay Claim-Safe

**Files:**
- Test only unless a downstream test exposes a missing assertion.

- [ ] **Step 1: Run full-admin decision package tests**

Run:

```bash
uv run pytest data_agent/test_uwm_full_admin_livability_decision_package.py -q
```

Expected: PASS. The final package should still report `full_admin_decision_package_ready is True`, `planner_governance_binding_ready is False`, `observed_policy_outcome_superiority_claim is False`, and `empirical_superiority_claim is False`.

- [ ] **Step 2: Run data foundation evidence gate tests**

Run:

```bash
uv run pytest data_agent/test_uwm_data_foundation_evidence_gate.py -q
```

Expected: PASS. The evidence gate should continue to support bounded claims only and should not emit observed policy-outcome superiority.

- [ ] **Step 3: Run focused UWM planner-related tests**

Run:

```bash
uv run pytest data_agent/test_uwm_data_calibrated_planner_replay.py data_agent/test_uwm_full_admin_graph_planner_replay.py data_agent/test_uwm_full_admin_livability_decision_package.py data_agent/test_uwm_data_foundation_evidence_gate.py -q
```

Expected: PASS.

- [ ] **Step 4: Inspect generated artifact diff for forbidden changes**

Run:

```bash
git diff -- data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/snapshot_manifest.json
```

Expected: diff adds causal binding fields, registry lineage, and binding summary. It must not reduce graph counts, action counts, transition counts, or flip observed/empirical superiority claims to true.

- [ ] **Step 5: Final status check**

Run:

```bash
git status --short
```

Expected: only unrelated pre-existing dirty files remain. No UWM implementation file touched by this plan should be unstaged after the task commits.

---

## Plan Self-Review

Spec coverage:

- Planner input registry is covered in Task 2.
- Candidate, transition, best sequence, and static baseline binding are covered in Task 2 and Task 4.
- Full-admin builder registry wiring is covered in Task 3.
- Missing-registry downgrade is covered in Task 1 and Task 2.
- Full-admin real-data counts are covered in Task 4 and Task 5.
- Claim safety is covered in Task 1, Task 4, and Task 5.

No reduced-data or smoke-only implementation path is included. No observed policy-outcome superiority claim is introduced.
