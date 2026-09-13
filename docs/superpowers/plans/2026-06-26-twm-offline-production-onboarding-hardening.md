# TWM Offline Production Onboarding Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TWM offline production-onboarding diagnostics stricter, clearer, and safer while real authoritative data remains unavailable.

**Architecture:** Keep changes in the existing script/report layer. Add additive diagnostic fields to observed-history schema audits, production scale readiness, onboarding summaries, and deployment punch lists without touching core TWM simulator, planner, causal, or claim-ladder behavior.

**Tech Stack:** Python, csv/json, pytest, existing TWM validation scripts.

---

## File Structure

- Modify: `scripts/validate_twm_data_foundation.py`
  - Add remediation metadata for observed-history missing field groups and data gates.
  - Expose additive `gate_diagnostics` on `audit_observed_history_schema()`.
- Modify: `scripts/run_twm_validation_bundle.py`
  - Preserve additive observed-history diagnostics in validation-bundle summaries.
  - Add scale-profile check diagnostics and remediation rows to Markdown output.
- Modify: `scripts/run_twm_production_onboarding.py`
  - Include data-owner-focused diagnostic summaries in the combined onboarding report and Markdown.
- Modify: `data_agent/territory_world_model/deployment_punch_list.py`
  - Add phase-level counts and severity while preserving the current `actions` contract.
- Modify: `data_agent/test_twm_data_foundation_validation.py`
  - Add focused unit tests for incomplete, synthetic, and production-ready observed-history diagnostics.
- Modify: `data_agent/test_twm_validation_bundle_smoke_script.py`
  - Add validation-bundle tests for scale-profile diagnostics and Markdown rendering.
- Modify: `data_agent/test_twm_production_onboarding.py`
  - Add onboarding summary assertions for grouped diagnostics and remediation text.

## Task 1: Observed-History Diagnostic Contract

**Files:**
- Modify: `data_agent/test_twm_data_foundation_validation.py`
- Modify: `scripts/validate_twm_data_foundation.py`

- [ ] **Step 1: Add failing tests for observed-history gate diagnostics**

Append these tests after `test_normalize_production_observed_history_export_keeps_incomplete_exports_review_only`:

```python
def test_audit_observed_history_schema_reports_gate_diagnostics_for_incomplete_export(tmp_path):
    module = _load_script_module()
    path = tmp_path / "production_missing_spatial_temporal.csv"
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_status,outcome,area_m2,synthetic,not_for_production",
                "P-1,approved,0.31,1000,False,False",
                "P-2,in_review,0.08,1200,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)
    diagnostics = {item["gate"]: item for item in audit["gate_diagnostics"]}

    assert audit["status"] == "review"
    assert diagnostics["spatial_support"]["status"] == "missing"
    assert diagnostics["spatial_support"]["phase"] == "observed_history_schema"
    assert "cluster" in diagnostics["spatial_support"]["accepted_fields"]
    assert "Provide at least one spatial support field" in diagnostics["spatial_support"]["remediation"]
    assert diagnostics["temporal_holdout_support"]["status"] == "missing"
    assert diagnostics["explicit_production_flags"]["status"] == "pass"
    assert diagnostics["production_usable_rows"]["observed"] == 2


def test_audit_observed_history_schema_reports_synthetic_rows_as_non_production(tmp_path):
    module = _load_script_module()
    path = tmp_path / "synthetic_rows.csv"
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_status,outcome,cluster,area_m2,period,split,policy_version,synthetic,not_for_production",
                "P-1,approved,0.31,R01,1000,2026Q1,train,V1,True,True",
                "P-2,in_review,0.08,R02,1200,2026Q2,holdout,V1,True,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = module.audit_observed_history_schema(path)
    diagnostics = {item["gate"]: item for item in audit["gate_diagnostics"]}

    assert audit["status"] == "review"
    assert diagnostics["production_usable_rows"]["status"] == "missing"
    assert diagnostics["production_usable_rows"]["observed"] == 0
    assert diagnostics["production_usable_rows"]["remediation"].startswith("Set synthetic=false")
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_data_foundation_validation.py::test_audit_observed_history_schema_reports_gate_diagnostics_for_incomplete_export \
  data_agent/test_twm_data_foundation_validation.py::test_audit_observed_history_schema_reports_synthetic_rows_as_non_production
```

Expected: FAIL with `KeyError: 'gate_diagnostics'`.

- [ ] **Step 3: Implement observed-history diagnostic helpers**

Add these helpers near `audit_observed_history_schema()` in `scripts/validate_twm_data_foundation.py`:

```python
OBSERVED_HISTORY_GROUP_REMEDIATIONS: dict[str, str] = {
    "causal_unit_identity": "Provide unit_id, project_id, approval_id, AJBH, XMDM, or another stable causal unit identifier.",
    "treatment_assignment": "Provide approval_status, treatment, review_result, decision_result, approved_area_m2, or another treatment/status field.",
    "observed_outcome": "Provide outcome, observed_utility_delta, approved_area_m2, DKMJ, or another audited outcome/proxy field.",
    "production_flags": "Provide explicit synthetic and not_for_production flags for every row.",
    "spatial_support": "Provide at least one spatial support field such as cluster, region_code, DKXZQDM, neighbors, x/y, or lon/lat.",
    "adjustment_covariates": "Provide at least one numeric pre-decision covariate such as area_m2, DKMJ, quality_score, risk_score, rule_hit_count, or review_task_count.",
}

OBSERVED_HISTORY_DATA_GATE_REMEDIATIONS: dict[str, str] = {
    "production_usable_rows": "Set synthetic=false and not_for_production=false only for real production-usable rows; synthetic/demo rows must remain review-only.",
    "production_treated_rows": "Include at least one approved, passed, granted, or treated production row.",
    "production_control_rows": "Include at least one in_review, returned, rejected, pending, or untreated production row.",
    "observed_outcome": "Populate an audited outcome or acceptable area/utility proxy for production candidate rows.",
    "spatial_support": "Populate spatial support with region, cluster, neighbor IDs, or complete coordinates.",
    "adjustment_covariates": "Populate numeric adjustment covariates that were known before or at decision time.",
    "explicit_production_flags": "Every row must explicitly include synthetic and not_for_production flags.",
    "production_temporal_rows": "Production rows need period, time_index, approval_date, decision_date, year, or quarter.",
    "temporal_holdout_support": "Provide explicit train and holdout/test splits across at least two periods.",
    "policy_effective_version": "Provide policy_effective_date, policy_version, rule_version, planning_version, or standard_version.",
}

def _observed_history_gate_diagnostics(
    *,
    group_reports: list[dict[str, Any]],
    missing_data_gates: list[str],
    row_quality: dict[str, Any],
    temporal_quality: dict[str, Any],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for group in group_reports:
        gate = str(group.get("group") or "")
        diagnostics.append(
            {
                "gate": gate,
                "phase": "observed_history_schema",
                "status": "pass" if group.get("status") == "pass" else "missing",
                "observed": list(group.get("matched_fields") or []),
                "accepted_fields": list(group.get("accepted_aliases") or []),
                "remediation": OBSERVED_HISTORY_GROUP_REMEDIATIONS.get(gate, f"Provide fields for {gate}."),
            }
        )
    observed_values = {
        "production_usable_rows": row_quality.get("production_candidate_row_count", 0),
        "production_treated_rows": row_quality.get("production_treated_count", 0),
        "production_control_rows": row_quality.get("production_control_count", 0),
        "observed_outcome": row_quality.get("rows_with_outcome", 0),
        "spatial_support": row_quality.get("rows_with_spatial_support", 0),
        "adjustment_covariates": row_quality.get("rows_with_covariates", 0),
        "explicit_production_flags": row_quality.get("explicit_production_flag_row_count", 0),
        "production_temporal_rows": temporal_quality.get("production_temporal_row_count", 0),
        "temporal_holdout_support": {
            "period_count": temporal_quality.get("period_count", 0),
            "train_row_count": temporal_quality.get("train_row_count", 0),
            "holdout_row_count": temporal_quality.get("holdout_row_count", 0),
        },
        "policy_effective_version": temporal_quality.get("rows_with_policy_effective_version", 0),
    }
    missing = set(missing_data_gates)
    for gate, remediation in OBSERVED_HISTORY_DATA_GATE_REMEDIATIONS.items():
        diagnostics.append(
            {
                "gate": gate,
                "phase": "observed_history_data",
                "status": "missing" if gate in missing else "pass",
                "observed": observed_values.get(gate),
                "remediation": remediation,
            }
        )
    return diagnostics
```

Then add `"gate_diagnostics": _observed_history_gate_diagnostics(...)` to the return payload of `audit_observed_history_schema()`:

```python
"gate_diagnostics": _observed_history_gate_diagnostics(
    group_reports=group_reports,
    missing_data_gates=missing_data_gates,
    row_quality=row_quality,
    temporal_quality=temporal_validation_quality,
),
```

- [ ] **Step 4: Run focused tests for Task 1**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_data_foundation_validation.py::test_audit_observed_history_schema_reports_gate_diagnostics_for_incomplete_export \
  data_agent/test_twm_data_foundation_validation.py::test_audit_observed_history_schema_reports_synthetic_rows_as_non_production \
  data_agent/test_twm_data_foundation_validation.py::test_audit_observed_history_schema_accepts_production_ready_rows \
  data_agent/test_twm_data_foundation_validation.py::test_audit_observed_history_schema_reviews_demo_flags
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add scripts/validate_twm_data_foundation.py data_agent/test_twm_data_foundation_validation.py
git commit -m "feat(twm): add observed history preflight diagnostics"
```

## Task 2: Validation Bundle Scale And Preflight Summary

**Files:**
- Modify: `data_agent/test_twm_validation_bundle_smoke_script.py`
- Modify: `scripts/run_twm_validation_bundle.py`

- [ ] **Step 1: Add failing tests for scale diagnostics and Markdown remediation**

Append these tests to `data_agent/test_twm_validation_bundle_smoke_script.py`:

```python
def _load_validation_bundle_module():
    import importlib.util

    script = Path("scripts/run_twm_validation_bundle.py")
    spec = importlib.util.spec_from_file_location("run_twm_validation_bundle", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_production_scale_readiness_reports_check_diagnostics_for_partial_profile(tmp_path):
    module = _load_validation_bundle_module()
    profile = tmp_path / "partial_scale_profile.json"
    profile.write_text(
        json.dumps(
            {
                "schema": "territory_world_model.production_scale_profile.v1",
                "example_only": False,
                "not_for_production": False,
                "layers": [{"name": "parcel", "row_count": 12000000, "storage_format": "csv"}],
                "compute": {"engine": "single_node_python", "distributed": False},
            }
        ),
        encoding="utf-8",
    )

    readiness = module.build_production_scale_readiness(production_scale_profile=profile)
    diagnostics = {item["gate"]: item for item in readiness["check_diagnostics"]}

    assert readiness["status"] == "review"
    assert diagnostics["lakehouse_storage"]["phase"] == "production_scale"
    assert diagnostics["partition_strategy"]["status"] == "missing"
    assert "partitioning" in diagnostics["partition_strategy"]["remediation"]
    assert diagnostics["distributed_compute"]["status"] == "missing"
    assert readiness["data_owner_summary"]["missing_gate_count"] >= 3


def test_validation_bundle_markdown_lists_scale_diagnostic_table():
    module = _load_validation_bundle_module()
    report = {
        "inputs": {},
        "production_observed_history_normalization": {"status": "not_requested", "field_mapping": {}},
        "production_observed_history_preflight": {
            "status": "review",
            "schema_audit": {"status": "review", "row_quality": {"production_candidate_row_count": 0}},
            "policy_history_quality": {"status": "review"},
            "temporal_validation_quality": {"status": "review", "missing_temporal_gates": ["explicit_train_holdout_split"]},
            "policy_history_alignment": {"status": "review", "missing": ["production_policy_history_quality"]},
        },
        "production_scale_readiness": {
            "status": "review",
            "scale_tier": "ten_million_scale",
            "observed": {"max_layer_row_count": 12000000, "total_row_count": 12000000, "layer_count": 1},
            "missing": ["partition_strategy"],
            "check_diagnostics": [
                {
                    "gate": "partition_strategy",
                    "phase": "production_scale",
                    "status": "missing",
                    "observed": [],
                    "requirement": "million-scale layers require explicit partitioning",
                    "remediation": "Add administrative, temporal, or spatial partition columns.",
                }
            ],
        },
        "production_readiness_gate": {"required": False, "status": "review", "missing": ["production_scale_readiness_pass"]},
        "deployment_punch_list": {"status": "review", "required": False, "open_action_count": 1, "blocking_action_count": 0, "actions": []},
        "state_summary": {},
        "rule_summary": {},
        "audit_summary": {},
        "selected_plan_evaluation_bundle": {},
        "validation_summary": {},
        "claim_ladder": {},
        "scca_summary": {},
        "claim_boundary": {},
        "recommendations": [],
    }

    markdown = module.render_validation_bundle_markdown(report)

    assert "## Production Scale Check Diagnostics" in markdown
    assert "| `partition_strategy` | `missing` |" in markdown
    assert "Add administrative, temporal, or spatial partition columns." in markdown
```

- [ ] **Step 2: Run Task 2 tests to verify they fail**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_production_scale_readiness_reports_check_diagnostics_for_partial_profile \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_validation_bundle_markdown_lists_scale_diagnostic_table
```

Expected: FAIL with `KeyError: 'check_diagnostics'` or missing Markdown section.

- [ ] **Step 3: Add scale diagnostic helpers**

Add this helper near `build_production_scale_readiness()` in `scripts/run_twm_validation_bundle.py`:

```python
PRODUCTION_SCALE_REMEDIATIONS: dict[str, str] = {
    "production_scale_profile_provided": "Provide a sanitized metadata-only production_scale_profile.json.",
    "production_scale_profile_readable": "Fix the supplied production scale profile path so the file can be read.",
    "production_scale_profile_not_example": "Replace the example template values and set example_only=false and not_for_production=false only for sanitized real metadata.",
    "production_layer_inventory": "List every relevant production layer or table with sanitized names and row counts.",
    "lakehouse_storage": "Use GeoParquet, Iceberg, Delta, Hudi, ORC, or another columnar lakehouse-compatible layout for million-scale layers.",
    "partition_strategy": "Add administrative, temporal, or spatial partition columns.",
    "spatial_index_strategy": "Add a spatial index or grid strategy such as S2, H3, Hilbert, quadkey, or tile index.",
    "distributed_compute": "Use distributed compute such as Spark/Sedona, Flink, Dask, Ray, Trino, or distributed SQL for ten-million-scale layers.",
    "national_scale_sampling_or_tiling": "Add tiling, sampling, chunking, or pyramid strategy for hundred-million-scale validation and serving.",
}

def production_scale_check_diagnostics(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for check in checks:
        gate = str(check.get("gate") or "")
        diagnostics.append(
            {
                "gate": gate,
                "phase": "production_scale",
                "status": "pass" if check.get("status") == "pass" else "missing",
                "observed": check.get("observed"),
                "requirement": check.get("requirement"),
                "remediation": PRODUCTION_SCALE_REMEDIATIONS.get(gate, f"Resolve the {gate} production-scale readiness gap."),
            }
        )
    return diagnostics

def production_scale_data_owner_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics = production_scale_check_diagnostics(checks)
    missing = [item for item in diagnostics if item["status"] != "pass"]
    return {
        "schema": "territory_world_model.production_scale_data_owner_summary.v1",
        "missing_gate_count": len(missing),
        "missing_gates": [item["gate"] for item in missing],
        "remediations": [item["remediation"] for item in missing],
    }
```

In every return path of `build_production_scale_readiness()`, assign local `checks = [...]` first and include:

```python
"check_diagnostics": production_scale_check_diagnostics(checks),
"data_owner_summary": production_scale_data_owner_summary(checks),
```

- [ ] **Step 4: Add validation-bundle Markdown scale diagnostic table**

In `render_validation_bundle_markdown()`, after the current Production Scale Readiness section, add:

```python
    lines.extend(
        [
            "",
            "## Production Scale Check Diagnostics",
            "",
            "| Gate | Status | Requirement | Remediation |",
            "|---|---|---|---|",
        ]
    )
    for item in scale.get("check_diagnostics") or []:
        requirement = str(item.get("requirement") or "").replace("|", "\\|")
        remediation = str(item.get("remediation") or "").replace("|", "\\|")
        lines.append(f"| `{item.get('gate')}` | `{item.get('status')}` | {requirement} | {remediation} |")
```

- [ ] **Step 5: Run focused tests for Task 2**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_production_scale_readiness_reports_check_diagnostics_for_partial_profile \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_validation_bundle_markdown_lists_scale_diagnostic_table \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_twm_validation_bundle_smoke_script_can_normalize_raw_production_history
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add scripts/run_twm_validation_bundle.py data_agent/test_twm_validation_bundle_smoke_script.py
git commit -m "feat(twm): report production scale readiness diagnostics"
```

## Task 3: Onboarding Summary And Punch-List Grouping

**Files:**
- Modify: `data_agent/test_twm_production_onboarding.py`
- Modify: `scripts/run_twm_production_onboarding.py`
- Modify: `data_agent/territory_world_model/deployment_punch_list.py`

- [ ] **Step 1: Add failing onboarding assertions**

In `test_twm_production_onboarding_writes_summary_when_strict_readiness_blocks()`, add these assertions after `punch_list = summary["deployment_punch_list"]`:

```python
    assert punch_list["phase_counts"]["production_scale"] >= 1
    assert punch_list["severity_counts"]["blocking"] >= 1
    assert "production_scale" in summary["data_owner_next_steps"]
    assert any("sanitized production scale profile" in item for item in summary["data_owner_next_steps"]["production_scale"])
    markdown = (output_dir / "twm_production_onboarding_summary.md").read_text(encoding="utf-8")
    assert "## Data Owner Next Steps" in markdown
    assert "### production_scale" in markdown
```

- [ ] **Step 2: Run the updated onboarding test to verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_production_onboarding.py::test_twm_production_onboarding_writes_summary_when_strict_readiness_blocks
```

Expected: FAIL with `KeyError: 'phase_counts'`.

- [ ] **Step 3: Add punch-list phase and severity counts**

Modify `build_deployment_punch_list()` in `data_agent/territory_world_model/deployment_punch_list.py`:

```python
    phase_counts: dict[str, int] = {}
    severity_counts = {"blocking": 0, "review": 0}
    for action in actions:
        phase = str(action.get("phase") or "deployment")
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        severity = "blocking" if action.get("blocks_current_run") else "review"
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
```

Add these fields to the returned dictionary:

```python
"phase_counts": phase_counts,
"severity_counts": severity_counts,
```

- [ ] **Step 4: Add onboarding data-owner next steps**

Add this helper to `scripts/run_twm_production_onboarding.py` near `build_onboarding_summary()`:

```python
def build_data_owner_next_steps(deployment_punch_list: dict[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for action in deployment_punch_list.get("actions") or []:
        phase = str(action.get("phase") or "deployment")
        resolution = str(action.get("resolution") or "").strip()
        if not resolution:
            resolution = f"Resolve {action.get('gate')} before production readiness can be promoted."
        grouped.setdefault(phase, [])
        if resolution not in grouped[phase]:
            grouped[phase].append(resolution)
    return grouped
```

In `build_onboarding_summary()`, after `deployment_punch_list = ...`, add:

```python
    data_owner_next_steps = build_data_owner_next_steps(deployment_punch_list)
```

Then include this in the summary payload:

```python
"data_owner_next_steps": data_owner_next_steps,
```

- [ ] **Step 5: Render next steps in onboarding Markdown**

In `render_onboarding_markdown()`, after the Deployment Punch List table loop, add:

```python
    next_steps = summary.get("data_owner_next_steps") or {}
    lines.extend(["", "## Data Owner Next Steps", ""])
    if not next_steps:
        lines.append("- No open data-owner next steps.")
    for phase, items in next_steps.items():
        lines.append(f"### {phase}")
        lines.append("")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
```

- [ ] **Step 6: Run focused onboarding tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_production_onboarding.py::test_twm_production_onboarding_writes_summary_when_strict_readiness_blocks \
  data_agent/test_twm_production_onboarding.py::test_twm_production_onboarding_runs_foundation_and_bundle_from_raw_export
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add scripts/run_twm_production_onboarding.py data_agent/territory_world_model/deployment_punch_list.py data_agent/test_twm_production_onboarding.py
git commit -m "feat(twm): group onboarding deployment next steps"
```

## Task 4: Regression And Final Verification

**Files:**
- Test: `data_agent/test_twm_data_foundation_validation.py`
- Test: `data_agent/test_twm_validation_bundle_smoke_script.py`
- Test: `data_agent/test_twm_production_onboarding.py`

- [ ] **Step 1: Run targeted regression suite**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_data_foundation_validation.py \
  data_agent/test_twm_validation_bundle_smoke_script.py \
  data_agent/test_twm_production_onboarding.py
```

Expected: PASS.

- [ ] **Step 2: Run compile check for touched scripts**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m compileall -q \
  scripts/validate_twm_data_foundation.py \
  scripts/run_twm_validation_bundle.py \
  scripts/run_twm_production_onboarding.py \
  data_agent/territory_world_model/deployment_punch_list.py
```

Expected: exit code 0.

- [ ] **Step 3: Inspect scoped diff and untracked reports**

Run:

```bash
git status --short
git diff --stat HEAD~3..HEAD
```

Expected: implementation commits include only the planned script/test files. Pre-existing untracked `docs/reports/twm_*` files remain untracked unless the user separately asks to add them.

- [ ] **Step 4: Final implementation commit if any verification-only fix was needed**

If Step 1 or Step 2 required a small fix, commit only the touched files:

```bash
git add scripts/validate_twm_data_foundation.py scripts/run_twm_validation_bundle.py scripts/run_twm_production_onboarding.py data_agent/territory_world_model/deployment_punch_list.py data_agent/test_twm_data_foundation_validation.py data_agent/test_twm_validation_bundle_smoke_script.py data_agent/test_twm_production_onboarding.py
git commit -m "test(twm): verify offline onboarding hardening"
```

If no fix was needed, do not create an empty commit.
