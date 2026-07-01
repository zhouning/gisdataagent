# TWM Dynamics Evaluation Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `territory_world_model.dynamics_evaluation_bundle.v1` as the first P2A evidence bundle that ties dataset MREP trace, readiness, evaluation, registry metadata and promotion blockers into one auditable report.

**Architecture:** Reuse existing TWM service reports instead of adding new model training behavior. The bundle should call or accept `dynamics_training_examples`, `dynamics_readiness_report`, `dynamics_evaluation_report` and `dynamics_model_registry_report`, then summarize the evidence in a stable machine-readable contract. API routing should mirror the existing dynamics report endpoints.

**Tech Stack:** Python 3.11+, pytest, existing `TerritoryWorldModelService`, Starlette JSON routes, existing TWM JSON helpers.

---

## Scope Check

This plan implements one narrow P2A roadmap slice:

- a dynamics evaluation bundle report;
- route exposure for the report;
- focused tests for report content and route wiring;
- a roadmap checkpoint.

It does not train a new MLP, graph, transformer, GeoFM or causal model. It does not change existing readiness/evaluation/registry semantics.

## File Structure

- Modify `data_agent/territory_world_model/service.py`
  - Add `dynamics_evaluation_bundle`.
  - Add private helpers for bundle evidence summary, split summary and promotion blockers.
- Modify `data_agent/api/territory_world_model_routes.py`
  - Add `twm_dynamics_evaluation_bundle`.
  - Add `/api/twm/states/{id}/dynamics-evaluation-bundle`.
- Modify `data_agent/test_territory_world_model.py`
  - Add service-level and route-level bundle tests.
- Modify `docs/twm-algorithm-model-roadmap-2026-06-30.md`
  - Add a short P2A checkpoint after the post-P0/P1 roadmap.

## Task 1: Add Dynamics Evaluation Bundle Service Report

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/territory_world_model/service.py`

- [ ] **Step 1: Write the failing service test**

Add this test after `test_dynamics_evaluation_report_passes_candidate_predictions_on_observed_holdout` in `data_agent/test_territory_world_model.py`:

```python
def test_dynamics_evaluation_bundle_links_trace_readiness_evaluation_and_registry():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "bundle_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
            "split": "temporal_holdout",
        },
    )
    dataset = _observed_dynamics_dataset(seed)
    predictions = {
        item["id"]: {
            "future_latent_state": item["targets"]["future_latent_state"],
            "constraint_violation_probability": item["targets"]["constraint_violation_probability"],
            "planning_utility_delta": item["targets"]["planning_utility_delta"],
            "uncertainty": {"confidence": 0.82},
            "action_mask": item["targets"]["action_mask"],
        }
        for item in dataset["examples"]
    }

    report = svc.dynamics_evaluation_bundle(
        state_id,
        {
            "dataset": dataset,
            "predictions": predictions,
            "candidate": {
                "model_name": "hierarchical_twm_candidate",
                "model_version": "bundle-v1",
                "model_family": "hierarchical_graph_dynamics",
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "evaluation_thresholds": {
                "min_ground_truth_examples": 3,
                "max_mean_transition_error": 0.001,
                "max_mean_constraint_error": 0.001,
                "max_mean_utility_error": 0.001,
                "min_ranking_correlation_proxy": 0.5,
            },
            "registry_metadata": {
                "training_run_id": "bundle-run-001",
                "model_artifact_uri": "file:///models/hierarchical_twm_candidate/bundle-v1",
                "training_dataset_snapshot": "pilot-package-dev",
                "state_contract_version": "territory_world_model.state_contract_report.v1",
                "evaluation_report_id": "eval-bundle-001",
            },
            "production_data_gate": {"status": "pass"},
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["schema"] == "territory_world_model.dynamics_evaluation_bundle.v1"
    assert report["status"] in {"review", "pass"}
    assert report["dataset"]["schema"] == "territory_world_model.dynamics_training_dataset.v1"
    assert report["dataset"]["mrep_trace"]["schema"] == "territory_world_model.mrep_trace.v1"
    assert report["dataset"]["mrep_trace"]["dataset_snapshot_hash"]
    assert report["readiness"]["schema"] == "territory_world_model.dynamics_readiness_report.v1"
    assert report["evaluation"]["schema"] == "territory_world_model.dynamics_evaluation_report.v1"
    assert report["registry"]["schema"] == "territory_world_model.dynamics_model_registry_report.v1"
    assert report["evidence_summary"]["dataset_snapshot_hash"] == report["dataset"]["mrep_trace"]["dataset_snapshot_hash"]
    assert report["evidence_summary"]["readiness_status"] == report["readiness"]["status"]
    assert report["evidence_summary"]["evaluation_status"] == report["evaluation"]["status"]
    assert report["evidence_summary"]["registry_promotion_decision"] == report["registry"]["promotion_decision"]
    assert report["split_summary"]["split"] == "temporal_holdout"
    assert report["promotion_blockers"] == report["registry"]["missing_for_promotion"]
    assert "full_future_geometry_generation" in report["claim_boundary"]["non_goals"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_dynamics_evaluation_bundle_links_trace_readiness_evaluation_and_registry -q
```

Expected: `FAIL` with `AttributeError: 'TerritoryWorldModelService' object has no attribute 'dynamics_evaluation_bundle'`.

- [ ] **Step 3: Add the minimal service implementation**

In `data_agent/territory_world_model/service.py`, add these helpers near `dynamics_evaluation_report`:

```python
    def dynamics_evaluation_bundle(self, state_version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        state = self.repository.get_state_version(state_version_id)
        if state is None or self.repository.get_state_bundle(state_version_id) is None:
            raise LookupError(f"state not found: {state_version_id}")
        dataset_payload = payload.get("dataset")
        dataset = dict(dataset_payload) if isinstance(dataset_payload, dict) else self.dynamics_training_examples(state_version_id, payload)
        readiness = self.dynamics_readiness_report(state_version_id, {"dataset": dataset, **payload})
        evaluation = self.dynamics_evaluation_report(state_version_id, {"dataset": dataset, **payload})
        registry = self.dynamics_model_registry_report(
            state_version_id,
            {
                "dynamics_training_dataset": dataset,
                "candidate_report": payload.get("candidate_report") or {
                    "candidate": evaluation.get("candidate") or {},
                    "status": evaluation.get("status", "review"),
                    "evidence_gate": evaluation.get("evidence_gate") or {},
                    "evaluation": evaluation,
                },
                "readiness_report": readiness,
                "evaluation_report": evaluation,
                "registry_metadata": payload.get("registry_metadata") or payload.get("metadata") or {},
                "production_data_gate": payload.get("production_data_gate") or payload.get("production_gate") or {},
                "current_registry_key": payload.get("current_registry_key") or payload.get("production_registry_key") or "",
            },
        )
        evidence_summary = self._dynamics_evaluation_bundle_evidence_summary(dataset, readiness, evaluation, registry)
        status = "pass" if not evidence_summary["blocking_missing"] else "review"
        if readiness.get("status") == "blocked" or evaluation.get("status") == "blocked":
            status = "blocked"
        return json.loads(_json({
            "schema": "territory_world_model.dynamics_evaluation_bundle.v1",
            "generated_at": now_utc_iso(),
            "state_version_id": state_version_id,
            "project_id": state.project_id,
            "status": status,
            "dataset": {
                "schema": dataset.get("schema"),
                "example_count": (dataset.get("summary") or {}).get("example_count", len(dataset.get("examples") or [])),
                "usable_example_count": (dataset.get("summary") or {}).get("usable_example_count", 0),
                "review_example_count": (dataset.get("summary") or {}).get("review_example_count", 0),
                "mrep_trace": (dataset.get("summary") or {}).get("mrep_trace") or {},
            },
            "readiness": readiness,
            "evaluation": evaluation,
            "registry": registry,
            "split_summary": self._dynamics_evaluation_bundle_split_summary(dataset),
            "evidence_summary": evidence_summary,
            "promotion_blockers": list(registry.get("missing_for_promotion") or []),
            "recommendations": self._dynamics_evaluation_bundle_recommendations(evidence_summary, registry),
            "claim_boundary": {
                "status": "review_only_until_promotion_gates_pass",
                "non_goals": [
                    "full_future_geometry_generation",
                    "broad_flus_geosos_superiority",
                    "autonomous_l3_self_evolution",
                ],
            },
        }))

    def _dynamics_evaluation_bundle_split_summary(self, dataset: dict[str, Any]) -> dict[str, Any]:
        summary = self._payload_mapping(dataset.get("summary"))
        mrep_trace = self._payload_mapping(summary.get("mrep_trace"))
        split_definition = self._payload_mapping(mrep_trace.get("split_definition"))
        examples = list(dataset.get("examples") or [])
        split_counts: dict[str, int] = {}
        for item in examples:
            split = compact_text(self._payload_mapping(item).get("split") or "unknown")
            split_counts[split] = split_counts.get(split, 0) + 1
        return {
            "split": split_definition.get("split") or "default",
            "temporal_holdout": split_definition.get("temporal_holdout") or summary.get("temporal_holdout") or {},
            "holdout_example_count": split_definition.get("holdout_example_count", sum(1 for item in examples if self._payload_mapping(item).get("split") == "holdout")),
            "split_counts": split_counts,
        }

    def _dynamics_evaluation_bundle_evidence_summary(
        self,
        dataset: dict[str, Any],
        readiness: dict[str, Any],
        evaluation: dict[str, Any],
        registry: dict[str, Any],
    ) -> dict[str, Any]:
        summary = self._payload_mapping(dataset.get("summary"))
        mrep_trace = self._payload_mapping(summary.get("mrep_trace"))
        registry_missing = list(registry.get("missing_for_promotion") or [])
        missing_registry_metadata = list(registry.get("missing_registry_metadata") or [])
        blocking_missing = sorted(set(registry_missing + missing_registry_metadata))
        return {
            "dataset_snapshot_hash": mrep_trace.get("dataset_snapshot_hash"),
            "mrep_trace_status": "pass" if mrep_trace.get("schema") == "territory_world_model.mrep_trace.v1" and mrep_trace.get("dataset_snapshot_hash") else "missing",
            "readiness_status": readiness.get("status", "review"),
            "evaluation_status": evaluation.get("status", "review"),
            "registry_promotion_decision": registry.get("promotion_decision", "review_only_not_promoted"),
            "registry_missing": registry_missing,
            "missing_registry_metadata": missing_registry_metadata,
            "blocking_missing": blocking_missing,
        }

    def _dynamics_evaluation_bundle_recommendations(self, evidence_summary: dict[str, Any], registry: dict[str, Any]) -> list[str]:
        recommendations = [
            "use this bundle as the required evidence packet for P2A dynamics model comparisons",
            "compare model families only when they share the same dataset snapshot hash and split summary",
        ]
        if evidence_summary.get("blocking_missing"):
            recommendations.append("resolve promotion blockers before nominating this candidate for controlled pilot")
        if registry.get("promotion_decision") != "candidate_for_registry_promotion":
            recommendations.append("keep this model review-only until registry promotion decision passes")
        return recommendations
```

- [ ] **Step 4: Run the service test**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_dynamics_evaluation_bundle_links_trace_readiness_evaluation_and_registry -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
git add data_agent/test_territory_world_model.py data_agent/territory_world_model/service.py
git commit -m "feat(twm): add dynamics evaluation bundle"
```

## Task 2: Expose Dynamics Evaluation Bundle Route

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/api/territory_world_model_routes.py`

- [ ] **Step 1: Write the failing route test**

In `data_agent/test_territory_world_model.py`, update `test_twm_dynamics_reports_routes_return_contracts` after the evaluation report assertions:

```python
    bundle_req = _fake_request(
        "POST",
        b'{"scenario":"route_bundle","evidence_coverage":0.72}',
        path_params={"id": state["state_version"]["id"]},
    )
    bundle_resp = asyncio.run(routes.twm_dynamics_evaluation_bundle(bundle_req))
    assert bundle_resp.status_code == 200
    bundle_payload = json.loads(bundle_resp.body)
    assert bundle_payload["schema"] == "territory_world_model.dynamics_evaluation_bundle.v1"
    assert bundle_payload["dataset"]["mrep_trace"]["schema"] == "territory_world_model.mrep_trace.v1"
```

Also add this assertion near the existing route tool listing assertions in `test_twm_agent_tool_registry_includes_twm_tools`:

```python
    assert "twm_dynamics_evaluation_bundle" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py::test_twm_dynamics_reports_routes_return_contracts \
  data_agent/test_territory_world_model.py::test_twm_agent_tool_registry_includes_twm_tools \
  -q
```

Expected: `FAIL` because `twm_dynamics_evaluation_bundle` is not exposed yet.

- [ ] **Step 3: Add the route function**

In `data_agent/api/territory_world_model_routes.py`, add this function after `twm_dynamics_evaluation_report`:

```python
async def twm_dynamics_evaluation_bundle(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.dynamics_evaluation_bundle(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
```

- [ ] **Step 4: Add the route registration**

In `data_agent/api/territory_world_model_routes.py`, add this route after `/dynamics-evaluation-report`:

```python
        Route("/api/twm/states/{id}/dynamics-evaluation-bundle", endpoint=twm_dynamics_evaluation_bundle, methods=["POST"]),
```

- [ ] **Step 5: Run the route tests**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py::test_twm_dynamics_reports_routes_return_contracts \
  data_agent/test_territory_world_model.py::test_twm_agent_tool_registry_includes_twm_tools \
  -q
```

Expected: both selected tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
git add data_agent/test_territory_world_model.py data_agent/api/territory_world_model_routes.py
git commit -m "feat(twm): expose dynamics evaluation bundle route"
```

## Task 3: Add Roadmap Checkpoint And Regression

**Files:**
- Modify: `docs/twm-algorithm-model-roadmap-2026-06-30.md`

- [ ] **Step 1: Append checkpoint**

Append this section to `docs/twm-algorithm-model-roadmap-2026-06-30.md`:

```markdown
## Implementation Checkpoint: P2A Dynamics Evaluation Bundle

The next TWM development slice creates `dynamics_evaluation_bundle.v1` as the
canonical evidence packet for model-family comparisons. It should connect MREP
trace, readiness, evaluation metrics, registry metadata and promotion blockers
without changing neural training behavior.
```

- [ ] **Step 2: Run focused regression**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py -k "dynamics_evaluation_bundle or dynamics_evaluation_report_passes_candidate_predictions or twm_dynamics_reports_routes_return_contracts or twm_agent_tool_registry_includes_twm_tools" \
  -q
git diff --check
```

Expected: all selected tests pass and `git diff --check` exits 0.

- [ ] **Step 3: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
git add docs/twm-algorithm-model-roadmap-2026-06-30.md
git commit -m "docs(twm): checkpoint dynamics evaluation bundle"
```

## Final Verification

After all tasks are complete, run:

```bash
cd /Users/zhouning/gisdataagent/.worktrees/twm-p2a-dynamics-evaluation-bundle
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py -k "dynamics_evaluation_bundle or dynamics_evaluation_report or dynamics_model_registry or mrep_trace" \
  -q
git diff --check
git status --short
```

Expected:

- selected tests pass;
- whitespace check exits 0;
- only intentional tracked changes are committed.
