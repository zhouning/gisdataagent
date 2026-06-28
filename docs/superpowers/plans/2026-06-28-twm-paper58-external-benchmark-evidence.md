# TWM Paper58 External Benchmark Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a report-only Paper58 external benchmark evidence intake to the TWM validation bundle without making Paper58 or AlphaEarth a TWM runtime dependency.

**Architecture:** Keep the implementation additive in `scripts/run_twm_validation_bundle.py` and the smoke wrapper. Parse only sanitized Paper58 metric summaries and manifests, expose the result under `paper58_external_benchmark`, and keep it outside production readiness and claim-ladder promotion.

**Tech Stack:** Python standard library, existing TWM validation-bundle script helpers, Bash smoke wrapper, pytest.

---

## File Map

- Modify `data_agent/test_twm_validation_bundle_smoke_script.py`
  - Adds TDD coverage for CLI wrapper exposure, missing Paper58 evidence, supplied sanitized fixtures, Markdown boundary wording, and no claim-ladder promotion.
- Modify `scripts/run_twm_validation_bundle.py`
  - Adds CLI argument, pure Paper58 evidence summarizer, JSON report field, Markdown section, and recommendations.
- Modify `scripts/smoke_twm_validation_bundle.sh`
  - Adds optional `TWM_PAPER58_BENCHMARK_DIR` env var wiring.
- Optionally regenerate `docs/reports/twm_validation_bundle.json` and `docs/reports/twm_validation_bundle.md`
  - Only after tests pass. These generated files should show the missing/non-blocking Paper58 boundary when no Paper58 artifact is supplied.

No core TWM model, planner, state builder, SCCA, or production-readiness modules should be edited.

---

### Task 1: Smoke Wrapper Contract

**Files:**
- Modify: `data_agent/test_twm_validation_bundle_smoke_script.py`
- Modify: `scripts/smoke_twm_validation_bundle.sh`

- [ ] **Step 1: Write the failing wrapper exposure test**

Add these assertions to `test_twm_validation_bundle_smoke_script_exposes_inner_network_controls`:

```python
    assert "TWM_PAPER58_BENCHMARK_DIR" in text
    assert "--paper58-benchmark-dir" in text
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_twm_validation_bundle_smoke_script_exposes_inner_network_controls
```

Expected: FAIL because the smoke wrapper does not yet mention `TWM_PAPER58_BENCHMARK_DIR` or `--paper58-benchmark-dir`.

- [ ] **Step 3: Add minimal smoke wrapper wiring**

In `scripts/smoke_twm_validation_bundle.sh`, add this variable after `NORMALIZED_PRODUCTION_OBSERVED_HISTORY_OUTPUT`:

```bash
PAPER58_BENCHMARK_DIR="${TWM_PAPER58_BENCHMARK_DIR:-}"
```

Add this argument block after the SCCA argument blocks:

```bash
if [ -n "${PAPER58_BENCHMARK_DIR}" ]; then
  ARGS+=("--paper58-benchmark-dir" "$PAPER58_BENCHMARK_DIR")
fi
```

Add this echo near the other validation context lines:

```bash
echo "[twm-validation] paper58_benchmark_dir=${PAPER58_BENCHMARK_DIR:-not_provided}"
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_twm_validation_bundle_smoke_script_exposes_inner_network_controls
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add data_agent/test_twm_validation_bundle_smoke_script.py scripts/smoke_twm_validation_bundle.sh
git commit -m "test: expose Paper58 benchmark option in TWM smoke wrapper"
```

---

### Task 2: Paper58 Evidence Summary Contract

**Files:**
- Modify: `data_agent/test_twm_validation_bundle_smoke_script.py`
- Modify: `scripts/run_twm_validation_bundle.py`

- [ ] **Step 1: Write missing-evidence and sanitized-fixture tests**

Append these tests to `data_agent/test_twm_validation_bundle_smoke_script.py`:

```python
def test_paper58_external_benchmark_missing_is_non_blocking():
    module = _load_validation_bundle_module()

    summary = module.build_paper58_external_benchmark(None)

    assert summary["schema"] == "territory_world_model.paper58_external_benchmark.v1"
    assert summary["status"] == "missing"
    assert summary["provided"] is False
    assert summary["claim_scope"] == "external_benchmark_support_only"
    assert summary["runtime_dependency"] == "none"
    assert summary["geofm_runtime_allowed"] is False
    assert summary["twm_generator_role"] == "not_a_runtime_generator"
    assert summary["primary_twm_route"] == "twm_native_generation_and_planning"
    assert summary["blocks_validation"] is False
    assert summary["can_promote_claim_ladder"] is False


def test_paper58_external_benchmark_fixture_is_supporting_evidence_only(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_fixture"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
                "geosos_flus_console,43,0.2688382600,0.1323193715,0.3423004034,0.0741466570",
                "paper58_semantic_keep_loo_selector,43,0.2928996378,0.1471426105,0.3520592721,0.0721105174",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "metrics_by_method.csv").write_text(
        "\n".join(
            [
                "method,area,change_f1,fom,transition_accuracy,allocation_disagreement",
                "geosos_flus_console,region_a,0.26,0.13,0.34,0.07",
                "paper58_semantic_keep_loo_selector,region_a,0.29,0.15,0.35,0.06",
                "geosos_flus_console,region_b,0.25,0.12,0.31,0.08",
                "paper58_semantic_keep_loo_selector,region_b,0.30,0.16,0.36,0.07",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps(
            {
                "method": "paper58_semantic_keep_loo_selector",
                "selection_rule": "leave-one-area-out selector over sanitized metrics",
                "summary": {
                    "n": 43,
                    "mean_change_f1": 0.2928996378,
                    "mean_fom": 0.1471426105,
                    "mean_transition_accuracy": 0.3520592721,
                    "mean_allocation_disagreement": 0.0721105174,
                },
            }
        ),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "supporting_evidence"
    assert summary["provided"] is True
    assert summary["metric_summary"]["area_count"] == 43
    assert summary["metric_summary"]["best_paper58_method"] == "paper58_semantic_keep_loo_selector"
    assert summary["metric_summary"]["baseline_method"] == "geosos_flus_console"
    assert summary["metric_summary"]["paper58_vs_baseline_wins"] == 4
    assert summary["metric_summary"]["deltas"]["mean_change_f1"] > 0
    assert summary["metric_summary"]["deltas"]["mean_fom"] > 0
    assert summary["metric_summary"]["deltas"]["mean_transition_accuracy"] > 0
    assert summary["metric_summary"]["deltas"]["mean_allocation_disagreement"] < 0
    assert summary["source_files"]["metric_summary_by_method"].endswith("metric_summary_by_method.csv")
    assert summary["source_files"]["metrics_by_method"].endswith("metrics_by_method.csv")
    assert summary["source_files"]["manifest"].endswith("manifest.json")
    assert "Paper58 is external benchmark support only" in summary["claim_boundary"]
    assert summary["runtime_dependency"] == "none"
    assert summary["geofm_runtime_allowed"] is False
    assert summary["can_promote_claim_ladder"] is False
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_paper58_external_benchmark_missing_is_non_blocking \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_paper58_external_benchmark_fixture_is_supporting_evidence_only
```

Expected: FAIL because `build_paper58_external_benchmark` is not defined.

- [ ] **Step 3: Import safe numeric helpers**

In `scripts/run_twm_validation_bundle.py`, change the utility import to:

```python
from data_agent.territory_world_model.utils import read_csv, read_json, safe_float, safe_int
```

- [ ] **Step 4: Add the Paper58 summary helpers**

Add these helpers after `build_scca_report_if_requested`:

```python
PAPER58_EXTERNAL_BENCHMARK_SCHEMA = "territory_world_model.paper58_external_benchmark.v1"


def build_paper58_external_benchmark(paper58_benchmark_dir: Path | str | None = None) -> dict[str, Any]:
    boundary = {
        "schema": PAPER58_EXTERNAL_BENCHMARK_SCHEMA,
        "claim_scope": "external_benchmark_support_only",
        "runtime_dependency": "none",
        "geofm_runtime_allowed": False,
        "twm_generator_role": "not_a_runtime_generator",
        "primary_twm_route": "twm_native_generation_and_planning",
        "blocks_validation": False,
        "can_promote_claim_ladder": False,
        "claim_boundary": (
            "Paper58 is external benchmark support only. It does not make AlphaEarth/GeoFM a TWM runtime "
            "dependency, does not replace TWM-native generation, and does not prove TWM production accuracy."
        ),
    }
    if paper58_benchmark_dir is None:
        return {
            **boundary,
            "status": "missing",
            "provided": False,
            "missing": ["paper58_benchmark_dir_not_provided"],
            "source_files": {},
            "metric_summary": {},
            "manifest_summary": {},
        }

    path = Path(paper58_benchmark_dir).expanduser()
    if not path.exists():
        return {
            **boundary,
            "status": "blocked",
            "provided": False,
            "missing": ["paper58_benchmark_path_not_found"],
            "source_files": {"paper58_benchmark_dir": str(path)},
            "metric_summary": {},
            "manifest_summary": {},
        }

    root = path.parent if path.is_file() else path
    manifest_path = path if path.is_file() and path.suffix.lower() == ".json" else root / "manifest.json"
    metric_summary_path = root / "metric_summary_by_method.csv"
    per_region_path = root / "metrics_by_method.csv"
    missing = []
    if not metric_summary_path.exists():
        missing.append("metric_summary_by_method.csv")
    metric_rows = read_csv(metric_summary_path) if metric_summary_path.exists() else []
    per_region_rows = read_csv(per_region_path) if per_region_path.exists() else []
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    if not manifest:
        missing.append("manifest.json")

    metric_summary = summarize_paper58_metric_rows(metric_rows, per_region_rows)
    status = "supporting_evidence" if metric_summary.get("best_paper58_method") and not missing else "review"
    return {
        **boundary,
        "status": status,
        "provided": True,
        "missing": missing,
        "source_files": {
            "paper58_benchmark_dir": str(root),
            "metric_summary_by_method": str(metric_summary_path) if metric_summary_path.exists() else None,
            "metrics_by_method": str(per_region_path) if per_region_path.exists() else None,
            "manifest": str(manifest_path) if manifest_path.exists() else None,
        },
        "metric_summary": metric_summary,
        "manifest_summary": summarize_paper58_manifest(manifest),
    }


def summarize_paper58_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not manifest:
        return {}
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    return {
        "method": manifest.get("method"),
        "selection_rule": manifest.get("selection_rule"),
        "summary": {
            "n": safe_int(summary.get("n"), 0),
            "mean_change_f1": safe_float(summary.get("mean_change_f1"), None),
            "mean_fom": safe_float(summary.get("mean_fom"), None),
            "mean_transition_accuracy": safe_float(summary.get("mean_transition_accuracy"), None),
            "mean_allocation_disagreement": safe_float(summary.get("mean_allocation_disagreement"), None),
        },
    }


def summarize_paper58_metric_rows(
    metric_rows: list[dict[str, Any]],
    per_region_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not metric_rows:
        return {}
    baseline = next((row for row in metric_rows if is_paper58_baseline_method(row.get("method"))), None)
    paper58_rows = [row for row in metric_rows if is_paper58_method(row.get("method"))]
    best = max(paper58_rows, key=paper58_metric_score, default=None)
    summary: dict[str, Any] = {
        "method_count": len(metric_rows),
        "per_region_row_count": len(per_region_rows),
        "baseline_method": baseline.get("method") if baseline else None,
        "best_paper58_method": best.get("method") if best else None,
        "area_count": safe_int((best or baseline or {}).get("n"), 0),
        "paper58_vs_baseline_wins": 0,
        "deltas": {},
        "best_paper58_metrics": sanitize_paper58_metrics(best or {}),
        "baseline_metrics": sanitize_paper58_metrics(baseline or {}),
    }
    if baseline and best:
        deltas = paper58_metric_deltas(best, baseline)
        summary["deltas"] = deltas
        summary["paper58_vs_baseline_wins"] = sum(
            1
            for key, value in deltas.items()
            if value is not None and ((key == "mean_allocation_disagreement" and value < 0) or (key != "mean_allocation_disagreement" and value > 0))
        )
    return summary


def is_paper58_baseline_method(method: Any) -> bool:
    text = str(method or "").lower()
    return "geosos" in text or "flus" in text


def is_paper58_method(method: Any) -> bool:
    return "paper58" in str(method or "").lower()


def paper58_metric_score(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        safe_float(row.get("mean_change_f1"), 0.0) or 0.0,
        safe_float(row.get("mean_fom"), 0.0) or 0.0,
        safe_float(row.get("mean_transition_accuracy"), 0.0) or 0.0,
        -(safe_float(row.get("mean_allocation_disagreement"), 999.0) or 999.0),
    )


def sanitize_paper58_metrics(row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "method": row.get("method"),
        "n": safe_int(row.get("n"), 0),
        "mean_change_f1": safe_float(row.get("mean_change_f1"), None),
        "mean_fom": safe_float(row.get("mean_fom"), None),
        "mean_transition_accuracy": safe_float(row.get("mean_transition_accuracy"), None),
        "mean_allocation_disagreement": safe_float(row.get("mean_allocation_disagreement"), None),
    }


def paper58_metric_deltas(best: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float | None]:
    keys = [
        "mean_change_f1",
        "mean_fom",
        "mean_transition_accuracy",
        "mean_allocation_disagreement",
    ]
    deltas: dict[str, float | None] = {}
    for key in keys:
        left = safe_float(best.get(key), None)
        right = safe_float(baseline.get(key), None)
        deltas[key] = None if left is None or right is None else left - right
    return deltas
```

- [ ] **Step 5: Run the Paper58 helper tests and verify they pass**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_paper58_external_benchmark_missing_is_non_blocking \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_paper58_external_benchmark_fixture_is_supporting_evidence_only
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add data_agent/test_twm_validation_bundle_smoke_script.py scripts/run_twm_validation_bundle.py
git commit -m "feat: summarize Paper58 external benchmark evidence"
```

---

### Task 3: Validation Bundle JSON Integration

**Files:**
- Modify: `data_agent/test_twm_validation_bundle_smoke_script.py`
- Modify: `scripts/run_twm_validation_bundle.py`

- [ ] **Step 1: Write a report-level non-promotion test**

Append this test to `data_agent/test_twm_validation_bundle_smoke_script.py`:

```python
def test_validation_bundle_includes_paper58_without_promoting_claims(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_fixture"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
                "geosos_flus_console,43,0.2688,0.1323,0.3423,0.0741",
                "paper58_semantic_keep_loo_selector,43,0.2929,0.1471,0.3520,0.0721",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    without_paper58 = module.run_validation_bundle(
        paper58_benchmark_dir=None,
        synthetic_experiment_foundation=None,
        production_scale_profile=None,
    )
    with_paper58 = module.run_validation_bundle(
        paper58_benchmark_dir=fixture,
        synthetic_experiment_foundation=None,
        production_scale_profile=None,
    )

    assert with_paper58["inputs"]["paper58_benchmark_dir"] == str(fixture)
    assert with_paper58["paper58_external_benchmark"]["status"] == "supporting_evidence"
    assert with_paper58["paper58_external_benchmark"]["claim_scope"] == "external_benchmark_support_only"
    assert with_paper58["paper58_external_benchmark"]["geofm_runtime_allowed"] is False
    assert with_paper58["claim_ladder"]["current_level"] == without_paper58["claim_ladder"]["current_level"]
    assert with_paper58["production_observed_history_preflight"]["status"] == without_paper58["production_observed_history_preflight"]["status"]
    assert with_paper58["production_readiness_gate"]["status"] == without_paper58["production_readiness_gate"]["status"]
```

- [ ] **Step 2: Run the report-level test and verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_validation_bundle_includes_paper58_without_promoting_claims
```

Expected: FAIL because `run_validation_bundle` does not accept `paper58_benchmark_dir`.

- [ ] **Step 3: Add CLI and function plumbing**

In `main()`, add this parser argument after the SCCA arguments:

```python
    parser.add_argument("--paper58-benchmark-dir", default="", help="Optional sanitized Paper58 benchmark summary directory or manifest path.")
```

Pass the value into `run_validation_bundle`:

```python
        paper58_benchmark_dir=Path(args.paper58_benchmark_dir).expanduser() if args.paper58_benchmark_dir else None,
```

Add this parameter to `run_validation_bundle` after `require_scca_pass`:

```python
    paper58_benchmark_dir: Path | str | None = None,
```

Normalize it near the other input paths:

```python
    paper58_benchmark_path = Path(paper58_benchmark_dir).expanduser() if paper58_benchmark_dir else None
```

Build the evidence summary after SCCA evidence is built:

```python
    paper58_external_benchmark = build_paper58_external_benchmark(paper58_benchmark_path)
```

Add this to `report["inputs"]`:

```python
            "paper58_benchmark_dir": str(paper58_benchmark_path) if paper58_benchmark_path else None,
```

Add this top-level report field after `scca_summary`:

```python
        "paper58_external_benchmark": paper58_external_benchmark,
```

Pass it into `validation_bundle_recommendations`:

```python
            paper58_external_benchmark,
```

- [ ] **Step 4: Update recommendation function signature**

Change `validation_bundle_recommendations` to accept the new argument after `require_scca_pass`:

```python
    paper58_external_benchmark: dict[str, Any] | None = None,
```

Add this recommendation block after the SCCA recommendations:

```python
    paper58_status = str((paper58_external_benchmark or {}).get("status") or "missing")
    if paper58_status == "supporting_evidence":
        recommendations.append("use Paper58 only as external benchmark support; keep TWM-native generation and planning as the runtime route")
    elif paper58_status == "blocked":
        recommendations.append("fix the sanitized Paper58 benchmark path or omit it; Paper58 evidence is optional and must not block TWM-native validation")
```

- [ ] **Step 5: Run the report-level test and verify it passes**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_validation_bundle_includes_paper58_without_promoting_claims
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add data_agent/test_twm_validation_bundle_smoke_script.py scripts/run_twm_validation_bundle.py
git commit -m "feat: include Paper58 evidence in TWM validation bundle"
```

---

### Task 4: Markdown Boundary Section

**Files:**
- Modify: `data_agent/test_twm_validation_bundle_smoke_script.py`
- Modify: `scripts/run_twm_validation_bundle.py`

- [ ] **Step 1: Write Markdown boundary test**

Append this test to `data_agent/test_twm_validation_bundle_smoke_script.py`:

```python
def test_validation_bundle_markdown_renders_paper58_external_boundary():
    module = _load_validation_bundle_module()
    report = {
        "inputs": {"paper58_benchmark_dir": "/tmp/paper58_fixture"},
        "production_observed_history_normalization": {"status": "not_requested", "field_mapping": {}},
        "production_observed_history_preflight": {
            "status": "review",
            "schema_audit": {"status": "review", "row_quality": {"production_candidate_row_count": 0}},
            "policy_history_quality": {"status": "review"},
            "temporal_validation_quality": {"status": "review"},
            "policy_history_alignment": {"status": "review"},
        },
        "production_scale_readiness": {"status": "not_provided", "observed": {}, "check_diagnostics": []},
        "production_readiness_gate": {"required": False, "status": "review", "missing": []},
        "deployment_punch_list": {"status": "review", "required": False, "open_action_count": 0, "blocking_action_count": 0, "actions": []},
        "paper58_external_benchmark": {
            "status": "supporting_evidence",
            "provided": True,
            "claim_scope": "external_benchmark_support_only",
            "runtime_dependency": "none",
            "geofm_runtime_allowed": False,
            "twm_generator_role": "not_a_runtime_generator",
            "primary_twm_route": "twm_native_generation_and_planning",
            "metric_summary": {
                "best_paper58_method": "paper58_semantic_keep_loo_selector",
                "baseline_method": "geosos_flus_console",
                "paper58_vs_baseline_wins": 4,
                "area_count": 43,
            },
            "claim_boundary": "Paper58 is external benchmark support only.",
        },
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

    assert "## External Benchmark Evidence" in markdown
    assert "Paper58 status: `supporting_evidence`" in markdown
    assert "Claim scope: `external_benchmark_support_only`" in markdown
    assert "Runtime dependency: `none`" in markdown
    assert "GeoFM runtime allowed: `False`" in markdown
    assert "TWM generator role: `not_a_runtime_generator`" in markdown
    assert "Best Paper58 method: `paper58_semantic_keep_loo_selector`" in markdown
    assert "Baseline method: `geosos_flus_console`" in markdown
    assert "Paper58 is external benchmark support only." in markdown
```

- [ ] **Step 2: Run the Markdown test and verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_validation_bundle_markdown_renders_paper58_external_boundary
```

Expected: FAIL because the Markdown renderer does not include an External Benchmark Evidence section.

- [ ] **Step 3: Add Paper58 Markdown rendering**

In `render_validation_bundle_markdown`, define `paper58` after `scca`:

```python
    paper58 = report.get("paper58_external_benchmark") or build_paper58_external_benchmark(None)
```

Add this input line after the SCCA output line:

```python
        f"- Paper58 external benchmark: `{inputs.get('paper58_benchmark_dir')}`",
```

Insert this section before `## Production Observed-History Preflight`:

```python
        "",
        "## External Benchmark Evidence",
        "",
        f"- Paper58 status: `{paper58.get('status')}`",
        f"- Provided: `{paper58.get('provided')}`",
        f"- Claim scope: `{paper58.get('claim_scope')}`",
        f"- Runtime dependency: `{paper58.get('runtime_dependency')}`",
        f"- GeoFM runtime allowed: `{paper58.get('geofm_runtime_allowed')}`",
        f"- TWM generator role: `{paper58.get('twm_generator_role')}`",
        f"- Primary TWM route: `{paper58.get('primary_twm_route')}`",
        f"- Best Paper58 method: `{((paper58.get('metric_summary') or {}).get('best_paper58_method'))}`",
        f"- Baseline method: `{((paper58.get('metric_summary') or {}).get('baseline_method'))}`",
        f"- Paper58 wins vs baseline: `{((paper58.get('metric_summary') or {}).get('paper58_vs_baseline_wins'))}`",
        f"- Area count: `{((paper58.get('metric_summary') or {}).get('area_count'))}`",
        f"- Boundary: {paper58.get('claim_boundary')}",
```

Keep this section visible for missing evidence because `build_paper58_external_benchmark(None)` returns the non-blocking boundary.

- [ ] **Step 4: Run the Markdown test and verify it passes**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py::test_validation_bundle_markdown_renders_paper58_external_boundary
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add data_agent/test_twm_validation_bundle_smoke_script.py scripts/run_twm_validation_bundle.py
git commit -m "docs: render Paper58 external benchmark boundary"
```

---

### Task 5: End-to-End Smoke and Generated Bundle Refresh

**Files:**
- Modify: `docs/reports/twm_validation_bundle.json`
- Modify: `docs/reports/twm_validation_bundle.md`

- [ ] **Step 1: Run all focused tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py
```

Expected: PASS for all tests in the module.

- [ ] **Step 2: Run diff check for edited source and tests**

Run:

```bash
git diff --check -- \
  data_agent/test_twm_validation_bundle_smoke_script.py \
  scripts/run_twm_validation_bundle.py \
  scripts/smoke_twm_validation_bundle.sh
```

Expected: no output and exit code 0.

- [ ] **Step 3: Refresh the default validation bundle**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/run_twm_validation_bundle.py
```

Expected: command writes:

- `docs/reports/twm_validation_bundle.json`
- `docs/reports/twm_validation_bundle.md`
- `docs/reports/twm_production_scale_profile_template.json`

The refreshed Markdown must include `## External Benchmark Evidence` with Paper58 status `missing` and the external-only boundary.

- [ ] **Step 4: Run a sanitized Paper58 fixture smoke**

Create a local fixture:

```bash
mkdir -p /private/tmp/twm_paper58_benchmark_fixture
cat > /private/tmp/twm_paper58_benchmark_fixture/metric_summary_by_method.csv <<'CSV'
method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement
geosos_flus_console,43,0.2688,0.1323,0.3423,0.0741
paper58_semantic_keep_loo_selector,43,0.2929,0.1471,0.3520,0.0721
CSV
cat > /private/tmp/twm_paper58_benchmark_fixture/metrics_by_method.csv <<'CSV'
method,area,change_f1,fom,transition_accuracy,allocation_disagreement
geosos_flus_console,region_a,0.26,0.13,0.34,0.07
paper58_semantic_keep_loo_selector,region_a,0.29,0.15,0.35,0.06
CSV
cat > /private/tmp/twm_paper58_benchmark_fixture/manifest.json <<'JSON'
{"method":"paper58_semantic_keep_loo_selector","selection_rule":"leave-one-area-out sanitized fixture","summary":{"n":43}}
JSON
```

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/run_twm_validation_bundle.py \
  --paper58-benchmark-dir /private/tmp/twm_paper58_benchmark_fixture \
  --output /private/tmp/twm_validation_bundle_paper58.json \
  --markdown-output /private/tmp/twm_validation_bundle_paper58.md
```

Expected: command exits 0, `/private/tmp/twm_validation_bundle_paper58.json` contains `"status": "supporting_evidence"` under `paper58_external_benchmark`, and the claim ladder remains review/offline rather than deployable.

- [ ] **Step 5: Inspect generated Paper58 fields**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -c "import json; p=json.load(open('/private/tmp/twm_validation_bundle_paper58.json')); print(p['paper58_external_benchmark']['status']); print(p['paper58_external_benchmark']['claim_scope']); print(p['paper58_external_benchmark']['geofm_runtime_allowed']); print(p['claim_ladder']['current_level'])"
```

Expected output lines:

```text
supporting_evidence
external_benchmark_support_only
False
L0
```

If the current local default bundle has a different claim level before Paper58 is supplied, the last line may match that existing level; it must not become `L4` because of Paper58.

- [ ] **Step 6: Commit Task 5**

```bash
git add docs/reports/twm_validation_bundle.json docs/reports/twm_validation_bundle.md
git commit -m "docs: refresh TWM validation bundle with Paper58 boundary"
```

---

### Task 6: Final Verification

**Files:**
- Test: `data_agent/test_twm_validation_bundle_smoke_script.py`
- Verify: `scripts/run_twm_validation_bundle.py`
- Verify: `scripts/smoke_twm_validation_bundle.sh`
- Verify: `docs/reports/twm_validation_bundle.json`
- Verify: `docs/reports/twm_validation_bundle.md`

- [ ] **Step 1: Run focused tests**

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py
```

Expected: PASS.

- [ ] **Step 2: Run Bash syntax check**

```bash
bash -n scripts/smoke_twm_validation_bundle.sh
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run source diff check**

```bash
git diff --check -- \
  data_agent/test_twm_validation_bundle_smoke_script.py \
  scripts/run_twm_validation_bundle.py \
  scripts/smoke_twm_validation_bundle.sh \
  docs/reports/twm_validation_bundle.json \
  docs/reports/twm_validation_bundle.md
```

Expected: no output and exit code 0.

- [ ] **Step 4: Confirm no unintended core TWM files changed**

```bash
git diff --name-only HEAD~5..HEAD
```

Expected changed files are limited to:

```text
data_agent/test_twm_validation_bundle_smoke_script.py
scripts/run_twm_validation_bundle.py
scripts/smoke_twm_validation_bundle.sh
docs/reports/twm_validation_bundle.json
docs/reports/twm_validation_bundle.md
```

The exact commit range may differ if tasks are squashed. The important check is that no core TWM model, planner, state builder, SCCA, or production-readiness module appears.

- [ ] **Step 5: Final commit if any verification-only artifact changed**

If verification generated or updated report files after Task 5, commit only those intended report changes:

```bash
git add docs/reports/twm_validation_bundle.json docs/reports/twm_validation_bundle.md
git commit -m "docs: update TWM validation bundle Paper58 evidence output"
```

Skip this commit when `git status --short -- docs/reports/twm_validation_bundle.json docs/reports/twm_validation_bundle.md` is empty.
