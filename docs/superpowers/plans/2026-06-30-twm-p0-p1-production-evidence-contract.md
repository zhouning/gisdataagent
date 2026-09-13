# TWM P0/P1 Production Evidence Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TWM production observed-history, same-case baseline evidence, and MREP-style traceability first-class strict gates for P0/P1 algorithm-model promotion.

**Architecture:** Keep existing demo and scaffold workflows working by default. Add strict production gates only when requested through readiness thresholds or onboarding flags, and reuse existing TWM service contracts for dynamics datasets, baseline export validation, and production onboarding. The work hardens promotion evidence without changing neural model behavior.

**Tech Stack:** Python 3.11+, pytest, existing `TerritoryWorldModelService`, existing CSV/JSON utilities, existing `scripts/run_twm_production_onboarding.py`.

---

## Scope Check

This plan covers only roadmap P0/P1:

- production observed-history gate;
- same-case baseline gate;
- state/action/next-state trace requirements;
- onboarding summary/report integration.

It does not train new MLP, graph, transformer, suitability, FLUS, GeoFM, or causal models. Those belong to the P2/P3 roadmap after this gate layer is stable.

## File Structure

- Modify `data_agent/territory_world_model/service.py`
  - Add MREP trace metadata to `dynamics_training_examples`.
  - Add strict optional readiness gates for production observed-history and same-case baseline evidence.
  - Keep default readiness behavior unchanged when strict gates are not requested.
- Modify `data_agent/test_territory_world_model.py`
  - Add focused tests for MREP trace, strict production observed-history gate, and strict same-case baseline gate.
- Modify `scripts/run_twm_production_onboarding.py`
  - Add optional same-case baseline CLI inputs.
  - Add baseline evidence pipeline output to onboarding JSON and Markdown.
- Modify `data_agent/test_twm_production_onboarding.py`
  - Add script-level tests for same-case baseline onboarding integration and argument validation.
- Modify `docs/twm-algorithm-model-roadmap-2026-06-30.md`
  - Add a short implementation checkpoint linking this P0/P1 plan.

## Task 1: Add MREP Trace To Dynamics Dataset

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/territory_world_model/service.py`

- [ ] **Step 1: Write the failing test**

Add this test after `test_dynamics_training_examples_define_multi_head_training_contract` in `data_agent/test_territory_world_model.py`:

```python
def test_dynamics_training_examples_emit_mrep_trace_for_reproducibility():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    dataset = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "mrep_trace",
            "horizon": 2,
            "evidence_coverage": 0.72,
            "split": "temporal_holdout",
        },
    )

    trace = dataset["summary"]["mrep_trace"]
    assert trace["schema"] == "territory_world_model.mrep_trace.v1"
    assert trace["state_version_id"] == state_id
    assert trace["dataset_snapshot_hash"]
    assert trace["state_contract_version"] == "territory_world_model.state_contract_report.v1"
    assert trace["split_definition"]["split"] == "temporal_holdout"
    assert trace["baseline_version"] == "deterministic_twm_scaffold_current"
    assert trace["boundary_conditions"]["synthetic_or_not_for_production_rows"] >= 1
    assert trace["failure_taxonomy"]["review_only_examples"] >= 1
    assert "future_latent_state" in trace["target_heads"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_dynamics_training_examples_emit_mrep_trace_for_reproducibility -q
```

Expected: `FAIL` with `KeyError: 'mrep_trace'`.

- [ ] **Step 3: Add the MREP helper**

In `data_agent/territory_world_model/service.py`, add this helper near `_dynamics_sample_inventory`:

```python
    def _dynamics_dataset_mrep_trace(
        self,
        *,
        state: TwmStateVersion,
        payload: dict[str, Any],
        examples: list[TwmDynamicsTrainingExample],
        state_contract: dict[str, Any],
    ) -> dict[str, Any]:
        examples_payload = [item.to_dict() for item in examples]
        review_only_count = sum(1 for item in examples if item.not_for_training_reasons)
        synthetic_or_not_for_production = sum(
            1
            for item in examples
            if item.provenance.get("synthetic") or item.provenance.get("not_for_production")
        )
        holdout_count = sum(1 for item in examples if item.split == "holdout")
        target_heads = sorted(
            {
                head
                for item in examples
                for head in item.targets.keys()
            }
        )
        source_counts: dict[str, int] = {}
        for item in examples:
            source = str(item.labels.get("supervision_source") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
        return {
            "schema": "territory_world_model.mrep_trace.v1",
            "state_version_id": state.id,
            "project_id": state.project_id,
            "dataset_snapshot_hash": _stable_sha256(examples_payload),
            "state_contract_version": state_contract.get("schema", ""),
            "state_contract_status": state_contract.get("status", "review"),
            "rule_version": str(payload.get("rule_version") or payload.get("policy_version") or "current_repository_rules"),
            "model_version": str(payload.get("model_version") or "deterministic_twm_scaffold_current"),
            "baseline_version": str(payload.get("baseline_version") or "deterministic_twm_scaffold_current"),
            "random_seed": payload.get("random_seed"),
            "split_definition": {
                "split": str(payload.get("split") or "default"),
                "temporal_holdout": payload.get("temporal_holdout") or {},
                "holdout_example_count": holdout_count,
            },
            "target_heads": target_heads,
            "source_counts": source_counts,
            "failure_taxonomy": {
                "review_only_examples": review_only_count,
                "not_for_training_reasons": sorted(
                    {
                        str(reason)
                        for item in examples
                        for reason in item.not_for_training_reasons
                    }
                ),
            },
            "tail_statistics": {
                "example_count": len(examples),
                "holdout_example_count": holdout_count,
                "review_only_example_count": review_only_count,
            },
            "boundary_conditions": {
                "synthetic_or_not_for_production_rows": synthetic_or_not_for_production,
                "claim_boundary": "dataset trace supports reproducibility; it does not certify production accuracy",
            },
        }
```

- [ ] **Step 4: Attach the trace to the dataset summary**

In `dynamics_training_examples`, immediately before constructing `TwmDynamicsTrainingDataset`, compute the state contract:

```python
        state_contract = self.state_contract_report(state_version_id, payload)
```

Then add this field to the `summary` dictionary passed into `TwmDynamicsTrainingDataset`:

```python
                "mrep_trace": self._dynamics_dataset_mrep_trace(
                    state=state,
                    payload=payload,
                    examples=examples,
                    state_contract=state_contract,
                ),
```

- [ ] **Step 5: Run the focused test**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_dynamics_training_examples_emit_mrep_trace_for_reproducibility -q
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent
git add data_agent/test_territory_world_model.py data_agent/territory_world_model/service.py
git commit -m "feat(twm): add mrep trace to dynamics dataset"
```

## Task 2: Add Strict Production Observed-History Gate

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/territory_world_model/service.py`

- [ ] **Step 1: Write failing tests**

Add these tests near the existing dynamics readiness tests:

```python
def test_dynamics_readiness_report_blocks_strict_production_gate_when_history_missing():
    svc = _build_service()
    project, state_version = _save_lightweight_twm_state(svc)
    dataset = _minimal_observed_dynamics_dataset(state_version.id, project.id)

    report = svc.dynamics_readiness_report(
        state_version.id,
        {
            "dataset": dataset,
            "require_production_observed_history": True,
        },
    )

    assert report["status"] == "blocked"
    gate = report["gate_results"]["production_observed_history"]
    assert gate["required"] is True
    assert gate["passed"] is False
    assert gate["status"] == "missing"
    assert "production_observed_history" in report["gate_results"]["summary"]["blocked_gates"]


def test_dynamics_readiness_report_passes_strict_production_gate_with_preflight():
    svc = _build_service()
    project, state_version = _save_lightweight_twm_state(svc)
    dataset = _minimal_observed_dynamics_dataset(state_version.id, project.id)

    report = svc.dynamics_readiness_report(
        state_version.id,
        {
            "dataset": dataset,
            "require_production_observed_history": True,
            "production_observed_history_preflight": {
                "schema": "territory_world_model.production_observed_history_preflight.v1",
                "status": "pass",
                "schema_audit": {
                    "status": "pass",
                    "row_quality": {
                        "production_candidate_row_count": 10,
                        "production_treated_count": 5,
                        "production_control_count": 5,
                        "rows_with_outcome": 10,
                        "rows_with_spatial_support": 10,
                        "rows_with_covariates": 10,
                    },
                    "temporal_validation_quality": {
                        "status": "pass",
                        "period_count": 4,
                        "train_row_count": 5,
                        "holdout_row_count": 5,
                        "rows_with_policy_effective_version": 10,
                    },
                    "policy_history_quality": {
                        "status": "pass",
                        "allowed_count": 5,
                        "blocked_count": 5,
                    },
                },
            },
        },
    )

    gate = report["gate_results"]["production_observed_history"]
    assert report["status"] == "pass"
    assert gate["passed"] is True
    assert gate["status"] == "pass"
    assert gate["production_ready_observed_history_rows"] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "strict_production_gate" -q
```

Expected: `FAIL` because `production_observed_history` gate is absent.

- [ ] **Step 3: Extend readiness thresholds**

In `_dynamics_readiness_thresholds`, add these keys to the returned dict:

```python
            "require_production_observed_history": (
                truthy(raw.get("require_production_observed_history"))
                or truthy(payload.get("require_production_observed_history"))
                or truthy(payload.get("require_production_readiness"))
            ),
            "min_production_ready_observed_history_rows": safe_int(
                raw.get("min_production_ready_observed_history_rows"),
                1,
            ) or 1,
```

- [ ] **Step 4: Add the production gate helper**

Add this helper near `_dynamics_should_compute_causal_gate`:

```python
    def _dynamics_production_observed_history_gate(
        self,
        payload: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        required = bool(thresholds.get("require_production_observed_history"))
        preflight = self._payload_mapping(
            payload.get("production_observed_history_preflight")
            or payload.get("observed_history_preflight")
            or payload.get("production_history_preflight")
        )
        if not preflight:
            return {
                "passed": not required,
                "required": required,
                "status": "missing" if required else "not_required",
                "source": "payload",
                "missing": ["production_observed_history_preflight"] if required else [],
                "production_ready_observed_history_rows": 0,
            }
        schema_audit = self._payload_mapping(preflight.get("schema_audit") or preflight.get("audit"))
        row_quality = self._payload_mapping(schema_audit.get("row_quality"))
        temporal_quality = self._payload_mapping(schema_audit.get("temporal_validation_quality"))
        policy_quality = self._payload_mapping(schema_audit.get("policy_history_quality"))
        production_rows = safe_int(row_quality.get("production_candidate_row_count"), 0)
        missing: list[str] = []
        if preflight.get("status") != "pass" or schema_audit.get("status") != "pass":
            missing.append("preflight_pass")
        if production_rows < safe_int(thresholds.get("min_production_ready_observed_history_rows"), 1):
            missing.append("production_ready_observed_history_rows")
        if safe_int(row_quality.get("production_treated_count"), 0) <= 0:
            missing.append("production_treated_rows")
        if safe_int(row_quality.get("production_control_count"), 0) <= 0:
            missing.append("production_control_rows")
        if temporal_quality.get("status") != "pass":
            missing.append("temporal_holdout_support")
        if policy_quality.get("status") != "pass":
            missing.append("policy_action_history")
        status = "pass" if not missing else "blocked"
        return {
            "passed": status == "pass" or not required,
            "required": required,
            "status": status,
            "source": "payload",
            "missing": missing,
            "production_ready_observed_history_rows": production_rows,
            "policy_history_status": policy_quality.get("status", "not_provided"),
            "temporal_validation_status": temporal_quality.get("status", "not_provided"),
        }
```

- [ ] **Step 5: Wire the gate into readiness**

In `_dynamics_readiness_gates`, after the causal gate block, add:

```python
        production_gate = self._dynamics_production_observed_history_gate(payload, thresholds)
        gates["production_observed_history"] = production_gate
```

Then append the gate when strict mode is requested:

```python
        if thresholds["require_production_observed_history"]:
            trainable_gates.append("production_observed_history")
```

In `_dynamics_readiness_status`, change the hard set to:

```python
        hard = {"sample_volume", "usable_volume", "multi_head_targets", "loss_contract", "production_observed_history"}
```

In `_dynamics_readiness_recommendations`, add:

```python
        if "production_observed_history" in blocked:
            recommendations.append("provide production observed-history preflight with real treated/control rows, temporal holdout and policy-action labels before strict model promotion")
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "strict_production_gate or dynamics_readiness_report_passes_with_evidence_supported_observed_dataset" -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent
git add data_agent/test_territory_world_model.py data_agent/territory_world_model/service.py
git commit -m "feat(twm): require production history for strict readiness"
```

## Task 3: Add Strict Same-Case Baseline Gate

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/territory_world_model/service.py`

- [ ] **Step 1: Write failing tests**

Add these tests near the strict production gate tests:

```python
def test_dynamics_readiness_report_blocks_strict_same_case_baseline_when_missing():
    svc = _build_service()
    project, state_version = _save_lightweight_twm_state(svc)
    dataset = _minimal_observed_dynamics_dataset(state_version.id, project.id)

    report = svc.dynamics_readiness_report(
        state_version.id,
        {
            "dataset": dataset,
            "require_same_case_baseline": True,
        },
    )

    gate = report["gate_results"]["same_case_baseline"]
    assert report["status"] == "blocked"
    assert gate["required"] is True
    assert gate["passed"] is False
    assert gate["status"] == "missing"
    assert "same_case_baseline" in report["gate_results"]["summary"]["blocked_gates"]


def test_dynamics_readiness_report_passes_strict_same_case_baseline_with_validation_report():
    svc = _build_service()
    project, state_version = _save_lightweight_twm_state(svc)
    dataset = _minimal_observed_dynamics_dataset(state_version.id, project.id)
    baseline_report = svc.baseline_evidence_pipeline_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
        }
    )

    report = svc.dynamics_readiness_report(
        state_version.id,
        {
            "dataset": dataset,
            "require_same_case_baseline": True,
            "baseline_evidence_pipeline_report": baseline_report,
        },
    )

    gate = report["gate_results"]["same_case_baseline"]
    assert gate["passed"] is True
    assert gate["status"] == "pass"
    assert gate["overlap_count"] == 10
    assert gate["coverage_ratio"] == 1.0
    assert report["status"] == "pass"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "strict_same_case_baseline" -q
```

Expected: `FAIL` because `same_case_baseline` gate is absent.

- [ ] **Step 3: Extend readiness thresholds**

In `_dynamics_readiness_thresholds`, add:

```python
            "require_same_case_baseline": (
                truthy(raw.get("require_same_case_baseline"))
                or truthy(payload.get("require_same_case_baseline"))
                or truthy(payload.get("require_production_readiness"))
            ),
            "min_same_case_overlap_ratio": float(safe_float(raw.get("min_same_case_overlap_ratio"), 0.8) or 0.8),
```

- [ ] **Step 4: Add the same-case baseline gate helper**

Add this helper near `_dynamics_production_observed_history_gate`:

```python
    def _dynamics_same_case_baseline_gate(
        self,
        payload: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> dict[str, Any]:
        required = bool(thresholds.get("require_same_case_baseline"))
        pipeline = self._payload_mapping(payload.get("baseline_evidence_pipeline_report"))
        validation = self._payload_mapping(
            payload.get("baseline_export_validation_report")
            or pipeline.get("export_validation")
            or (pipeline.get("steps") or {}).get("export_validation")
        )
        if not validation:
            return {
                "passed": not required,
                "required": required,
                "status": "missing" if required else "not_required",
                "source": "payload",
                "missing": ["baseline_evidence_pipeline_report"] if required else [],
                "coverage_ratio": 0.0,
                "overlap_count": 0,
            }
        coverage = self._payload_mapping(validation.get("coverage"))
        blocking_errors = list(validation.get("blocking_errors") or [])
        coverage_ratio = float(safe_float(coverage.get("coverage_ratio"), 0.0) or 0.0)
        overlap_count = safe_int(coverage.get("overlap_count"), 0)
        missing: list[str] = []
        if validation.get("status") != "pass":
            missing.append("same_case_validation_pass")
        if blocking_errors:
            missing.extend(str(item) for item in blocking_errors)
        if coverage_ratio < float(thresholds.get("min_same_case_overlap_ratio") or 0.8):
            missing.append("same_case_overlap_ratio")
        status = "pass" if not missing else "blocked"
        return {
            "passed": status == "pass" or not required,
            "required": required,
            "status": status,
            "source": "payload",
            "missing": sorted(set(missing)),
            "coverage_ratio": coverage_ratio,
            "overlap_count": overlap_count,
            "claim_id": validation.get("claim", {}).get("claim_id") or pipeline.get("claim_id"),
            "baseline_id": validation.get("claim", {}).get("baseline_id") or pipeline.get("baseline_id"),
        }
```

- [ ] **Step 5: Wire the gate into readiness**

In `_dynamics_readiness_gates`, after adding `production_observed_history`, add:

```python
        same_case_gate = self._dynamics_same_case_baseline_gate(payload, thresholds)
        gates["same_case_baseline"] = same_case_gate
```

Then append the gate when strict mode is requested:

```python
        if thresholds["require_same_case_baseline"]:
            trainable_gates.append("same_case_baseline")
```

In `_dynamics_readiness_status`, change the hard set to:

```python
        hard = {
            "sample_volume",
            "usable_volume",
            "multi_head_targets",
            "loss_contract",
            "production_observed_history",
            "same_case_baseline",
        }
```

In `_dynamics_readiness_recommendations`, add:

```python
        if "same_case_baseline" in blocked:
            recommendations.append("provide same-case baseline export validation with sufficient overlap before strict model promotion")
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "strict_same_case_baseline or strict_production_gate or dynamics_readiness_report_passes_with_evidence_supported_observed_dataset" -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent
git add data_agent/test_territory_world_model.py data_agent/territory_world_model/service.py
git commit -m "feat(twm): gate strict readiness on same-case baselines"
```

## Task 4: Add Same-Case Baseline Inputs To Production Onboarding

**Files:**
- Modify: `data_agent/test_twm_production_onboarding.py`
- Modify: `scripts/run_twm_production_onboarding.py`

- [ ] **Step 1: Write failing script tests**

Add this helper after `_write_normalized_observed_history` in `data_agent/test_twm_production_onboarding.py`:

```python
def _write_same_case_baseline_exports(output_dir: Path) -> tuple[Path, Path]:
    twm_path = output_dir / "twm_case_outputs.csv"
    baseline_path = output_dir / "manual_overlay_case_outputs.csv"
    twm_path.write_text(
        "\n".join(
            [
                "case_id,ground_truth_conflict,detected_conflict,evidence_linked,unsupported_recommendation,not_for_production,sanitization_level",
                "c001,true,true,true,false,false,real_sanitized",
                "c002,true,true,true,false,false,real_sanitized",
                "c003,false,false,true,false,false,real_sanitized",
                "c004,true,false,true,false,false,real_sanitized",
                "c005,false,false,true,false,false,real_sanitized",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    baseline_path.write_text(
        "\n".join(
            [
                "case_id,ground_truth_conflict,detected_conflict,evidence_linked,unsupported_recommendation,not_for_production,sanitization_level",
                "c001,true,true,true,false,false,real_sanitized",
                "c002,true,false,true,false,false,real_sanitized",
                "c003,false,false,true,false,false,real_sanitized",
                "c004,true,false,true,false,false,real_sanitized",
                "c005,false,false,true,false,false,real_sanitized",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return twm_path, baseline_path
```

Add this test after `test_twm_production_onboarding_accepts_already_normalized_observed_history`:

```python
def test_twm_production_onboarding_runs_same_case_baseline_pipeline(tmp_path):
    production_path = tmp_path / "production_observed_history.csv"
    output_dir = tmp_path / "onboarding_with_baseline"
    output_dir.mkdir()
    _write_normalized_observed_history(production_path)
    twm_path, baseline_path = _write_same_case_baseline_exports(output_dir)

    subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--production-observed-history",
            str(production_path),
            "--output-dir",
            str(output_dir),
            "--claim-id",
            "C1_state_conflict_recall",
            "--baseline-id",
            "manual_gis_overlay_checklist",
            "--twm-case-output",
            str(twm_path),
            "--baseline-case-output",
            str(baseline_path),
        ],
        cwd=Path("/Users/zhouning/gisdataagent"),
        check=True,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert summary["baseline_evidence"]["status"] == "review"
    assert summary["baseline_evidence"]["export_validation_status"] == "pass"
    assert summary["baseline_evidence"]["overlap_count"] == 5
    assert summary["baseline_evidence"]["coverage_ratio"] == 1.0
    assert "baseline_evidence_pipeline_report" in summary["outputs"]
    markdown = (output_dir / "twm_production_onboarding_summary.md").read_text(encoding="utf-8")
    assert "## Same-Case Baseline Evidence" in markdown
    assert "manual_gis_overlay_checklist" in markdown
```

Add this argument-validation test near the existing input validation tests:

```python
def test_twm_production_onboarding_requires_complete_baseline_arguments(tmp_path):
    production_path = tmp_path / "production_observed_history.csv"
    output_dir = tmp_path / "onboarding_incomplete_baseline"
    _write_normalized_observed_history(production_path)

    completed = subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--production-observed-history",
            str(production_path),
            "--output-dir",
            str(output_dir),
            "--claim-id",
            "C1_state_conflict_recall",
        ],
        cwd=Path("/Users/zhouning/gisdataagent"),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 2
    assert "baseline evidence requires --claim-id, --baseline-id, --twm-case-output and --baseline-case-output together" in completed.stdout
    assert not (output_dir / "twm_production_onboarding_summary.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_twm_production_onboarding.py -k "same_case_baseline_pipeline or complete_baseline_arguments" -q
```

Expected: `FAIL` because the CLI arguments are unknown.

- [ ] **Step 3: Add onboarding output path and CLI arguments**

In `scripts/run_twm_production_onboarding.py`, add this import:

```python
from data_agent.territory_world_model.service import get_territory_world_model_service
```

Add parser arguments in `main()`:

```python
    parser.add_argument("--claim-id", default="", help="Optional same-case baseline claim id.")
    parser.add_argument("--baseline-id", default="", help="Optional same-case baseline id.")
    parser.add_argument("--twm-case-output", default="", help="Optional TWM same-case CSV output.")
    parser.add_argument("--baseline-case-output", default="", help="Optional baseline same-case CSV output.")
```

Extend `onboarding_output_paths`:

```python
        "baseline_evidence_pipeline_report": output_dir / "twm_baseline_evidence_pipeline.json",
```

- [ ] **Step 4: Validate and run the baseline pipeline**

Add this function before `run_command`:

```python
def build_baseline_evidence_pipeline_report(
    *,
    claim_id: str,
    baseline_id: str,
    twm_case_output: Path | None,
    baseline_case_output: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    provided = [bool(claim_id), bool(baseline_id), twm_case_output is not None, baseline_case_output is not None]
    if not any(provided):
        return {
            "schema": "territory_world_model.baseline_evidence_pipeline_report.v1",
            "status": "not_requested",
            "pipeline_decision": "not_requested",
        }
    if not all(provided):
        raise ValueError(
            "baseline evidence requires --claim-id, --baseline-id, --twm-case-output and --baseline-case-output together"
        )
    svc = get_territory_world_model_service()
    report = svc.baseline_evidence_pipeline_report(
        {
            "claim_id": claim_id,
            "baseline_id": baseline_id,
            "twm_case_output_path": str(twm_case_output),
            "baseline_case_output_path": str(baseline_case_output),
        }
    )
    write_json(output_path, report)
    return report
```

In `main()`, after loading the validation bundle report and before `build_onboarding_summary`, add:

```python
    try:
        baseline_evidence_report = build_baseline_evidence_pipeline_report(
            claim_id=args.claim_id,
            baseline_id=args.baseline_id,
            twm_case_output=Path(args.twm_case_output).expanduser() if args.twm_case_output else None,
            baseline_case_output=Path(args.baseline_case_output).expanduser() if args.baseline_case_output else None,
            output_path=outputs["baseline_evidence_pipeline_report"],
        )
    except ValueError as exc:
        parser.error(str(exc))
```

Pass `baseline_evidence_report=baseline_evidence_report` into `build_onboarding_summary`.

- [ ] **Step 5: Add baseline evidence to the summary and Markdown**

Update the `build_onboarding_summary` signature:

```python
    baseline_evidence_report: dict[str, Any],
```

Inside `build_onboarding_summary`, before `summary = {`, add:

```python
    export_validation = baseline_evidence_report.get("export_validation") or {}
    coverage = export_validation.get("coverage") or {}
```

Add this block to the `summary` dict:

```python
        "baseline_evidence": {
            "status": baseline_evidence_report.get("status", "not_requested"),
            "pipeline_decision": baseline_evidence_report.get("pipeline_decision", "not_requested"),
            "claim_id": baseline_evidence_report.get("claim_id"),
            "baseline_id": baseline_evidence_report.get("baseline_id"),
            "export_validation_status": export_validation.get("status"),
            "overlap_count": coverage.get("overlap_count", 0),
            "coverage_ratio": coverage.get("coverage_ratio", 0.0),
        },
```

Add this output:

```python
            "baseline_evidence_pipeline_report": (
                str(outputs["baseline_evidence_pipeline_report"])
                if baseline_evidence_report.get("status") != "not_requested"
                else None
            ),
```

In `render_onboarding_markdown`, add:

```python
    baseline = summary.get("baseline_evidence") or {}
```

Add this section after the validation bundle section:

```python
        "## Same-Case Baseline Evidence",
        "",
        f"- Status: `{baseline.get('status')}`",
        f"- Pipeline decision: `{baseline.get('pipeline_decision')}`",
        f"- Claim: `{baseline.get('claim_id')}`",
        f"- Baseline: `{baseline.get('baseline_id')}`",
        f"- Export validation: `{baseline.get('export_validation_status')}`",
        f"- Overlap count: `{baseline.get('overlap_count', 0)}`",
        f"- Coverage ratio: `{baseline.get('coverage_ratio', 0.0)}`",
        "",
```

- [ ] **Step 6: Run focused onboarding tests**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_twm_production_onboarding.py -k "same_case_baseline_pipeline or complete_baseline_arguments or accepts_already_normalized" -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent
git add data_agent/test_twm_production_onboarding.py scripts/run_twm_production_onboarding.py
git commit -m "feat(twm): include same-case baseline in onboarding"
```

## Task 5: Feed Onboarding Evidence Into Strict Readiness

**Files:**
- Modify: `data_agent/test_twm_production_onboarding.py`
- Modify: `scripts/run_twm_production_onboarding.py`

- [ ] **Step 1: Write failing test**

Add this test after `test_twm_production_onboarding_runs_same_case_baseline_pipeline`:

```python
def test_twm_production_onboarding_strict_model_gate_uses_history_and_baseline(tmp_path):
    production_path = tmp_path / "production_observed_history.csv"
    output_dir = tmp_path / "onboarding_strict_model_gate"
    output_dir.mkdir()
    _write_normalized_observed_history(production_path)
    twm_path, baseline_path = _write_same_case_baseline_exports(output_dir)

    subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--production-observed-history",
            str(production_path),
            "--output-dir",
            str(output_dir),
            "--claim-id",
            "C1_state_conflict_recall",
            "--baseline-id",
            "manual_gis_overlay_checklist",
            "--twm-case-output",
            str(twm_path),
            "--baseline-case-output",
            str(baseline_path),
            "--require-production-readiness",
        ],
        cwd=Path("/Users/zhouning/gisdataagent"),
        check=True,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert summary["model_promotion_gate"]["schema"] == "territory_world_model.model_promotion_gate.v1"
    assert summary["model_promotion_gate"]["production_observed_history_status"] == "pass"
    assert summary["model_promotion_gate"]["same_case_baseline_status"] == "pass"
    assert summary["model_promotion_gate"]["decision"] == "blocked_by_production_scale_or_other_bundle_gates"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_twm_production_onboarding.py::test_twm_production_onboarding_strict_model_gate_uses_history_and_baseline -q
```

Expected: `FAIL` because `model_promotion_gate` is absent.

- [ ] **Step 3: Add the model promotion gate builder**

In `scripts/run_twm_production_onboarding.py`, add this function before `build_onboarding_summary`:

```python
def build_model_promotion_gate(
    *,
    validation_bundle_report: dict[str, Any],
    baseline_evidence_report: dict[str, Any],
    require_production_readiness: bool,
) -> dict[str, Any]:
    preflight = validation_bundle_report.get("production_observed_history_preflight") or {}
    readiness = validation_bundle_report.get("production_readiness_gate") or {}
    export_validation = baseline_evidence_report.get("export_validation") or {}
    baseline_coverage = export_validation.get("coverage") or {}
    production_status = preflight.get("status", "not_provided")
    baseline_status = "not_requested"
    if baseline_evidence_report.get("status") != "not_requested":
        baseline_status = "pass" if export_validation.get("status") == "pass" and not export_validation.get("blocking_errors") else "blocked"
    missing: list[str] = []
    if production_status != "pass":
        missing.append("production_observed_history_preflight")
    if require_production_readiness and baseline_status != "pass":
        missing.append("same_case_baseline")
    if readiness.get("status") == "blocked":
        missing.extend(str(item) for item in readiness.get("missing") or [])
    decision = "strict_model_promotion_inputs_pass"
    if readiness.get("status") == "blocked":
        decision = "blocked_by_production_scale_or_other_bundle_gates"
    elif missing:
        decision = "blocked_by_missing_model_promotion_inputs"
    return {
        "schema": "territory_world_model.model_promotion_gate.v1",
        "required": require_production_readiness,
        "status": "pass" if not missing else "blocked",
        "decision": decision,
        "missing": sorted(set(missing)),
        "production_observed_history_status": production_status,
        "same_case_baseline_status": baseline_status,
        "same_case_overlap_count": baseline_coverage.get("overlap_count", 0),
        "same_case_coverage_ratio": baseline_coverage.get("coverage_ratio", 0.0),
        "claim_boundary": "strict promotion gate checks data and baseline evidence; production deployment still requires bundle readiness and human audit",
    }
```

- [ ] **Step 4: Add the gate to the summary**

Update `build_onboarding_summary` signature:

```python
    require_production_readiness: bool,
```

Before `summary = {`, add:

```python
    model_promotion_gate = build_model_promotion_gate(
        validation_bundle_report=validation_bundle_report,
        baseline_evidence_report=baseline_evidence_report,
        require_production_readiness=require_production_readiness,
    )
```

Add this summary field:

```python
        "model_promotion_gate": model_promotion_gate,
```

In `main()`, pass:

```python
        require_production_readiness=bool(args.require_production_readiness),
```

In `render_onboarding_markdown`, add:

```python
    promotion = summary.get("model_promotion_gate") or {}
```

Add this section after Same-Case Baseline Evidence:

```python
        "## Model Promotion Gate",
        "",
        f"- Status: `{promotion.get('status')}`",
        f"- Decision: `{promotion.get('decision')}`",
        f"- Missing: `{promotion.get('missing', [])}`",
        f"- Production observed history: `{promotion.get('production_observed_history_status')}`",
        f"- Same-case baseline: `{promotion.get('same_case_baseline_status')}`",
        "",
```

- [ ] **Step 5: Run focused test**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_twm_production_onboarding.py::test_twm_production_onboarding_strict_model_gate_uses_history_and_baseline -q
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent
git add data_agent/test_twm_production_onboarding.py scripts/run_twm_production_onboarding.py
git commit -m "feat(twm): summarize strict model promotion gate"
```

## Task 6: Documentation Checkpoint And Verification

**Files:**
- Modify: `docs/twm-algorithm-model-roadmap-2026-06-30.md`

- [ ] **Step 1: Update the roadmap checkpoint**

Append this section to `docs/twm-algorithm-model-roadmap-2026-06-30.md`:

```markdown
## Implementation Checkpoint: P0/P1 Gate Hardening

Plan: `docs/superpowers/plans/2026-06-30-twm-p0-p1-production-evidence-contract.md`

The first implementation slice is intentionally gate-focused. It should make
production observed-history preflight, same-case baseline evidence and MREP
traceability visible in strict readiness and onboarding reports before adding
more model architecture complexity.
```

- [ ] **Step 2: Run the focused regression set**

Run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py -k "mrep_trace or strict_production_gate or strict_same_case_baseline or baseline_export_validation_passes_same_case_manual_overlay_fixture" \
  data_agent/test_twm_production_onboarding.py -k "same_case_baseline_pipeline or complete_baseline_arguments or strict_model_gate_uses_history_and_baseline" \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run whitespace validation**

Run:

```bash
cd /Users/zhouning/gisdataagent
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 4: Commit**

Run:

```bash
cd /Users/zhouning/gisdataagent
git add docs/twm-algorithm-model-roadmap-2026-06-30.md
git commit -m "docs(twm): link p0 p1 gate hardening plan"
```

## Final Verification

After all tasks are implemented, run:

```bash
cd /Users/zhouning/gisdataagent
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py -k "dynamics_readiness or mrep_trace or baseline_export" \
  data_agent/test_twm_production_onboarding.py \
  data_agent/test_twm_deployment_punch_list.py \
  -q
git diff --check
```

Expected:

- all selected tests pass;
- `git diff --check` exits with `0`;
- unrelated untracked report files remain uncommitted unless the user explicitly requests them.

## Handoff Notes

- Strict gates must be opt-in through `require_production_observed_history`, `require_same_case_baseline`, or `require_production_readiness`.
- Existing demo, scaffold, public benchmark and non-strict readiness behavior must remain compatible.
- Baseline evidence can remain `review` at the comparison level because production claim gates may still block upgrade; the strict same-case gate only requires export validation to pass.
- Do not change neural dynamics training behavior in this plan.
