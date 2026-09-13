# TWM Pilot Package Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `territory_world_model.pilot_package.v1` so P2B model comparisons can reference one canonical pilot package, trajectory dataset manifest, MREP trace, same-case baseline gate and optional Lance sidecar contract.

**Architecture:** Reuse existing TWM reports instead of changing training behavior. The new service method calls `state_contract_report`, `dynamics_training_examples` and `dynamics_evaluation_bundle`, then derives a lightweight `trajectory_dataset_manifest.v1` and package gate summary. API and ADK toolset exposure mirror existing dynamics report endpoints.

**Tech Stack:** Python 3.11+, pytest, existing `TerritoryWorldModelService`, Starlette JSON routes, ADK `FunctionTool` / `LongRunningFunctionTool`.

---

## File Structure

- Modify `data_agent/territory_world_model/service.py`
  - Add `pilot_package_report`.
  - Add helpers `_pilot_package_trajectory_dataset_manifest`, `_pilot_package_gate_summary`, `_pilot_package_same_case_gate`, `_pilot_package_production_gate`, `_pilot_package_lance_sidecar_manifest`, `_pilot_package_recommendations`.
- Modify `data_agent/test_territory_world_model.py`
  - Add service tests near the dynamics bundle tests.
  - Add route/toolset assertions near existing TWM tool and route tests.
- Modify `data_agent/api/territory_world_model_routes.py`
  - Add `twm_pilot_package_report`.
  - Add `/api/twm/states/{id}/pilot-package-report`.
- Modify `data_agent/toolsets/territory_world_model_tools.py`
  - Add `twm_pilot_package_report` and async wrapper.
  - Register both in `_SYNC_FUNCS` and `_LONG_RUNNING_FUNCS`.

## Task 1: Add Pilot Package Service Report

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/territory_world_model/service.py`

- [ ] **Step 1: Write failing service tests**

Add these tests after `test_dynamics_evaluation_bundle_links_trace_readiness_evaluation_and_registry`:

```python
def test_pilot_package_report_links_mrep_bundle_trajectory_and_lance_sidecar():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {"scenario": "pilot_package_seed", "horizon": 2, "evidence_coverage": 0.72, "split": "temporal_holdout"},
    )
    dataset = _observed_dynamics_dataset(seed)
    baseline_validation = {
        "schema": "territory_world_model.baseline_export_validation_report.v1",
        "status": "pass",
        "coverage": {"coverage_ratio": 0.9, "overlap_count": 6},
        "blocking_errors": [],
        "warnings": [],
        "claim": {"claim_id": "C1_state_conflict_recall", "baseline_id": "manual_gis_overlay"},
    }

    report = svc.pilot_package_report(
        state_id,
        {
            "package_id": "bishan-pilot-package-v1",
            "dataset": dataset,
            "baseline_export_validation_report": baseline_validation,
            "production_data_gate": {"status": "pass", "source": "unit_test_gate"},
            "include_lance_sidecar": True,
            "spatial_split": {"strategy": "admin_holdout", "holdout_region": "500227"},
        },
    )

    assert report["schema"] == "territory_world_model.pilot_package.v1"
    assert report["package_id"] == "bishan-pilot-package-v1"
    assert report["state_contract"]["schema"] == "territory_world_model.state_contract_report.v1"
    assert report["dynamics_evaluation_bundle"]["schema"] == "territory_world_model.dynamics_evaluation_bundle.v1"
    assert report["trajectory_dataset_manifest"]["schema"] == "territory_world_model.trajectory_dataset_manifest.v1"
    assert report["trajectory_dataset_manifest"]["dataset_snapshot_hash"] == report["mrep_trace"]["dataset_snapshot_hash"]
    assert report["trajectory_dataset_manifest"]["example_count"] == len(dataset["examples"])
    assert "future_latent_state" in report["trajectory_dataset_manifest"]["target_heads"]
    assert report["package_gates"]["same_case_baseline"]["status"] == "pass"
    assert report["package_gates"]["production_data"]["status"] == "pass"
    assert report["lance_sidecar_manifest"]["schema"] == "territory_world_model.lance_sidecar_manifest.v1"
    assert report["lance_sidecar_manifest"]["storage_boundary"] == "derived_sidecar_not_authoritative"
    assert report["evidence_summary"]["dataset_snapshot_hash"] == report["mrep_trace"]["dataset_snapshot_hash"]


def test_pilot_package_report_blocks_when_required_same_case_baseline_missing():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)

    report = svc.pilot_package_report(
        state["state_version"]["id"],
        {"scenario": "pilot_package_missing_same_case", "require_same_case_baseline": True},
    )

    assert report["schema"] == "territory_world_model.pilot_package.v1"
    assert report["status"] == "blocked"
    assert report["package_gates"]["same_case_baseline"]["status"] == "missing"
    assert "same_case_baseline_evidence" in report["promotion_blockers"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py::test_pilot_package_report_links_mrep_bundle_trajectory_and_lance_sidecar \
  data_agent/test_territory_world_model.py::test_pilot_package_report_blocks_when_required_same_case_baseline_missing \
  -q
```

Expected: both fail with `AttributeError: 'TerritoryWorldModelService' object has no attribute 'pilot_package_report'`.

- [ ] **Step 3: Implement service report**

Add `pilot_package_report` after `dynamics_evaluation_bundle` in `data_agent/territory_world_model/service.py`. The implementation must:

- load the state and state bundle or raise `LookupError`;
- accept `dataset` from payload or build it via `dynamics_training_examples`;
- call `state_contract_report` and `dynamics_evaluation_bundle`;
- derive `mrep_trace` from `dataset["summary"]["mrep_trace"]`;
- build `trajectory_dataset_manifest` from examples, target heads, split counts and source lineage;
- build package gates for MREP, state contract, dynamics bundle, production data and same-case baseline;
- mark missing optional production/same-case evidence as `promotion_blockers`, and mark status `blocked` when a required production/same-case gate is missing or blocked;
- emit `lance_sidecar_manifest` only when `include_lance_sidecar` is truthy.

- [ ] **Step 4: Run service tests**

Run the same command from Step 2. Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add data_agent/test_territory_world_model.py data_agent/territory_world_model/service.py
git commit -m "feat(twm): add pilot package report"
```

## Task 2: Expose Pilot Package Route And Tool

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/api/territory_world_model_routes.py`
- Modify: `data_agent/toolsets/territory_world_model_tools.py`

- [ ] **Step 1: Write failing route/tool tests**

Add `"twm_pilot_package_report"` and `"twm_pilot_package_report_async"` to `test_twm_toolset_lists_sync_and_long_running_tools`.

Add this route/tool test near `test_twm_dynamics_reports_routes_return_contracts`:

```python
def test_twm_pilot_package_route_and_tool_return_manifest_contract(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)

    route_req = _fake_request(
        "POST",
        b'{"scenario":"route_pilot_package","include_lance_sidecar":true}',
        path_params={"id": state_id},
    )
    route_resp = asyncio.run(routes.twm_pilot_package_report(route_req))
    route_payload = json.loads(route_resp.body)
    assert route_resp.status_code == 200
    assert route_payload["schema"] == "territory_world_model.pilot_package.v1"
    assert route_payload["trajectory_dataset_manifest"]["schema"] == "territory_world_model.trajectory_dataset_manifest.v1"
    assert route_payload["lance_sidecar_manifest"]["storage_boundary"] == "derived_sidecar_not_authoritative"

    tool_payload = json.loads(tools.twm_pilot_package_report(
        state_id,
        json.dumps({"scenario": "tool_pilot_package"}),
    ))
    assert tool_payload["schema"] == "territory_world_model.pilot_package.v1"
    assert tool_payload["trajectory_dataset_manifest"]["dataset_snapshot_hash"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py::test_twm_toolset_lists_sync_and_long_running_tools \
  data_agent/test_territory_world_model.py::test_twm_pilot_package_route_and_tool_return_manifest_contract \
  -q
```

Expected: failure because `twm_pilot_package_report` is not exposed.

- [ ] **Step 3: Add API route and toolset wrappers**

Mirror `twm_dynamics_evaluation_bundle` in the route file and toolset file, calling `svc.pilot_package_report`.

- [ ] **Step 4: Run route/tool tests**

Run the same command from Step 2. Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add data_agent/test_territory_world_model.py data_agent/api/territory_world_model_routes.py data_agent/toolsets/territory_world_model_tools.py
git commit -m "feat(twm): expose pilot package report"
```

## Task 3: Regression Verification

**Files:**
- No required source changes.

- [ ] **Step 1: Run focused regression**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py -k "pilot_package_report or dynamics_evaluation_bundle or twm_pilot_package_route_and_tool_return_manifest_contract or twm_toolset_lists_sync_and_long_running_tools" \
  -q
git diff --check
git status --short
```

Expected: selected tests pass, whitespace check exits 0, only intentional committed changes remain.

## Final Verification

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py -k "pilot_package_report or dynamics_evaluation_bundle or dynamics_readiness_report_passes_with_evidence_supported_observed_dataset or twm_pilot_package_route_and_tool_return_manifest_contract" \
  -q
git diff --check
git status --short
```

Expected: tests pass; no unstaged tracked changes remain except deliberate uncommitted work during active implementation.
