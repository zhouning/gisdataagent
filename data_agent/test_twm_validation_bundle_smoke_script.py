"""Tests for the TWM validation-bundle smoke entrypoint."""

import json
import os
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/smoke_twm_validation_bundle.sh")
RUNNER = Path("scripts/run_twm_validation_bundle.py")


def _load_validation_bundle_module():
    import importlib.util

    script = Path("scripts/run_twm_validation_bundle.py")
    spec = importlib.util.spec_from_file_location("run_twm_validation_bundle", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_twm_validation_bundle_smoke_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_twm_validation_bundle_smoke_script_exposes_inner_network_controls():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "TWM_PRODUCTION_OBSERVED_HISTORY" in text
    assert "TWM_NORMALIZE_PRODUCTION_OBSERVED_HISTORY_SOURCE" in text
    assert "TWM_NORMALIZED_PRODUCTION_OBSERVED_HISTORY_OUTPUT" in text
    assert "TWM_PAPER58_BENCHMARK_DIR" in text
    assert "TWM_PRODUCTION_SCALE_PROFILE" in text
    assert "TWM_REQUIRE_PRODUCTION_READINESS" in text
    assert "TWM_FAIL_ON_BLOCKED" in text
    assert "TWM_REQUIRE_SCCA_PASS" in text
    assert "--production-observed-history" in text
    assert "--normalize-production-observed-history-source" in text
    assert "--normalized-production-observed-history-output" in text
    assert "--paper58-benchmark-dir" in text
    assert "--production-scale-profile" in text
    assert "--require-production-readiness" in text
    assert "--fail-on-blocked" in text
    assert ".venv/bin/python" in text


def test_twm_validation_bundle_runner_exposes_paper58_benchmark_cli_option():
    text = RUNNER.read_text(encoding="utf-8")

    assert "--paper58-benchmark-dir" in text


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
            "temporal_validation_quality": {
                "status": "review",
                "missing_temporal_gates": ["explicit_train_holdout_split"],
            },
            "policy_history_alignment": {
                "status": "review",
                "missing": ["production_policy_history_quality"],
            },
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
        "production_readiness_gate": {
            "required": False,
            "status": "review",
            "missing": ["production_scale_readiness_pass"],
        },
        "deployment_punch_list": {
            "status": "review",
            "required": False,
            "open_action_count": 1,
            "blocking_action_count": 0,
            "actions": [],
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

    assert "## Production Scale Check Diagnostics" in markdown
    assert "| `partition_strategy` | `missing` |" in markdown
    assert "Add administrative, temporal, or spatial partition columns." in markdown


def test_validation_bundle_preserves_observed_history_gate_diagnostics_for_incomplete_export(tmp_path):
    module = _load_validation_bundle_module()
    raw_path = tmp_path / "raw_incomplete_approval_export.csv"
    normalized_path = tmp_path / "normalized_incomplete_observed_history.csv"
    raw_path.write_text(
        "\n".join(
            [
                "AJBH,XMDM,review_result,observed_utility_delta,DKMJ,synthetic,not_for_prod",
                "APR-1,PRJ-1,approved,0.31,1000,False,False",
                "APR-2,PRJ-2,in_review,0.08,1200,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    prepared_path, normalization = module.prepare_production_observed_history_for_bundle(
        normalize_production_observed_history_source=raw_path,
        normalized_production_observed_history_output=normalized_path,
    )
    preflight = module.build_production_observed_history_preflight(
        production_observed_history=prepared_path,
        synthetic_experiment_foundation=None,
    )

    normalization_diagnostics = normalization["audit"]["gate_diagnostics"]
    preflight_diagnostics = preflight["schema_audit"]["gate_diagnostics"]

    assert normalization_diagnostics
    assert preflight_diagnostics
    assert any(
        "spatial support" in str(item.get("remediation", "")).lower()
        or "holdout" in str(item.get("remediation", "")).lower()
        for item in preflight_diagnostics
    )


def test_twm_validation_bundle_smoke_script_can_normalize_raw_production_history(tmp_path):
    raw_path = tmp_path / "raw_approval_export.csv"
    normalized_path = tmp_path / "normalized_production_observed_history.csv"
    output_path = tmp_path / "twm_validation_bundle.json"
    markdown_path = tmp_path / "twm_validation_bundle.md"
    raw_path.write_text(
        "\n".join(
            [
                "AJBH,XMDM,review_result,observed_utility_delta,DKXZQDM,DKMJ,quality_score,decision_action,policy_code,feasibility_label,year,dataset_split,rule_version,synthetic,not_for_prod",
                "APR-1,PRJ-1,approved,0.31,PROD-R01,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,allowed,2026Q1,training,RULE-2026-A,False,False",
                "APR-2,PRJ-2,approved,0.28,PROD-R02,1100,0.80,protect,mixed_risk_protect_allowed,allowed,2026Q1,training,RULE-2026-B,False,False",
                "APR-3,PRJ-3,approved,0.34,PROD-R03,1200,0.78,restore,mixed_risk_restore_allowed,allowed,2026Q2,training,RULE-2026-C,False,False",
                "APR-4,PRJ-4,in_review,0.08,PROD-R04,1300,0.76,approve_with_conditions,mixed_risk_blocked_condition_review,blocked,2026Q2,training,RULE-2026-D,False,False",
                "APR-5,PRJ-5,in_review,0.07,PROD-R05,1400,0.74,protect,mixed_risk_protect_blocked,blocked,2026Q3,training,RULE-2026-E,False,False",
                "APR-6,PRJ-6,approved,0.36,PROD-R06,1500,0.73,approve_with_conditions,mixed_risk_allowed_with_conditions,allowed,2026Q3,holdout,RULE-2026-F,False,False",
                "APR-7,PRJ-7,approved,0.37,PROD-R07,1600,0.72,protect,mixed_risk_protect_allowed,allowed,2026Q4,holdout,RULE-2026-G,False,False",
                "APR-8,PRJ-8,approved,0.38,PROD-R08,1700,0.71,restore,mixed_risk_restore_allowed,allowed,2026Q4,holdout,RULE-2026-H,False,False",
                "APR-9,PRJ-9,in_review,0.09,PROD-R09,1800,0.70,approve_with_conditions,mixed_risk_blocked_condition_review,blocked,2026Q4,holdout,RULE-2026-I,False,False",
                "APR-10,PRJ-10,in_review,0.06,PROD-R10,1900,0.69,protect,mixed_risk_protect_blocked,blocked,2026Q4,holdout,RULE-2026-J,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "TWM_NORMALIZE_PRODUCTION_OBSERVED_HISTORY_SOURCE": str(raw_path),
            "TWM_NORMALIZED_PRODUCTION_OBSERVED_HISTORY_OUTPUT": str(normalized_path),
            "TWM_VALIDATION_OUTPUT": str(output_path),
            "TWM_VALIDATION_MARKDOWN_OUTPUT": str(markdown_path),
        }
    )

    subprocess.run(["bash", str(SCRIPT)], cwd=Path("/Users/zhouning/gisdataagent"), env=env, check=True)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert normalized_path.exists()
    assert markdown_path.exists()
    assert payload["inputs"]["normalize_production_observed_history_source"] == str(raw_path)
    assert payload["inputs"]["normalized_production_observed_history_output"] == str(normalized_path)
    assert payload["production_observed_history_normalization"]["status"] == "pass"
    assert payload["production_observed_history_preflight"]["status"] == "pass"
    assert payload["production_observed_history_preflight"]["production_observed_history"] == str(normalized_path)


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


def test_paper58_external_benchmark_bad_path_is_non_blocking_diagnostic(tmp_path):
    module = _load_validation_bundle_module()
    missing_path = tmp_path / "does_not_exist"

    summary = module.build_paper58_external_benchmark(missing_path)

    assert summary["status"] == "blocked"
    assert summary["provided"] is False
    assert "paper58_benchmark_path_not_found" in summary["missing"]
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


def test_paper58_external_benchmark_manifest_is_optional_for_sanitized_summary(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_no_manifest"
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

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "supporting_evidence"
    assert "manifest.json" not in summary["missing"]
    assert summary["source_files"]["manifest"] is None
    assert summary["manifest_summary"] == {}
    assert summary["blocks_validation"] is False
    assert summary["can_promote_claim_ladder"] is False


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
    assert (
        with_paper58["production_observed_history_preflight"]["status"]
        == without_paper58["production_observed_history_preflight"]["status"]
    )
    assert with_paper58["production_readiness_gate"]["status"] == without_paper58["production_readiness_gate"]["status"]
    selected_plan_text = json.dumps(with_paper58["selected_plan_evaluation_bundle"], default=str).lower()
    assert "paper58_external_benchmark" not in selected_plan_text
    assert "paper58_benchmark_dir" not in selected_plan_text
    assert (
        "use Paper58 only as external benchmark support; keep TWM-native generation and planning as the runtime route"
        in with_paper58["recommendations"]
    )


def test_validation_bundle_recommendations_preserve_legacy_positional_production_args():
    module = _load_validation_bundle_module()

    recommendations = module.validation_bundle_recommendations(
        {"recommendations": []},
        {"summary": {}},
        {},
        False,
        {"status": "blocked"},
        {"status": "pass"},
        {"status": "blocked"},
    )

    assert "fix the production observed-history path before running production readiness gates" in recommendations
    assert (
        "production readiness is blocked; use the production_readiness_gate missing list as the deployment punch list"
        in recommendations
    )
    assert not any("Paper58 evidence is optional" in recommendation for recommendation in recommendations)


def test_paper58_external_benchmark_malformed_manifest_returns_review(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_bad_manifest"
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
    (fixture / "manifest.json").write_text("{bad json", encoding="utf-8")

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert summary["provided"] is True
    assert "manifest.json_unreadable" in summary["missing"]
    assert summary["blocks_validation"] is False


def test_paper58_external_benchmark_malformed_manifest_shape_stays_review(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_bad_manifest_shape"
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
        json.dumps({"method": "not_paper58", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert "manifest_method_not_paper58" in summary["missing"]
    assert summary["blocks_validation"] is False


def test_paper58_external_benchmark_without_baseline_stays_review(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_no_baseline"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
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

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert summary["metric_summary"]["best_paper58_method"] == "paper58_semantic_keep_loo_selector"
    assert summary["metric_summary"]["baseline_method"] is None
    assert "baseline_method_not_found" in summary["missing"]
    assert summary["metric_summary"]["paper58_vs_baseline_wins"] == 0


def test_paper58_external_benchmark_paper58_flus_method_is_not_baseline(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_overlap_method"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
                "paper58_flus_selector,43,0.2929,0.1471,0.3520,0.0721",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_flus_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert summary["metric_summary"]["best_paper58_method"] == "paper58_flus_selector"
    assert summary["metric_summary"]["baseline_method"] is None
    assert "baseline_method_not_found" in summary["missing"]
    assert summary["metric_summary"]["paper58_vs_baseline_wins"] == 0


def test_paper58_external_benchmark_malformed_metric_summary_reports_diagnostic(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_bad_metrics"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n",
                "geosos_flus_console,43",
                "paper58_semantic_keep_loo_selector,43",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert "metric_summary_required_columns_missing" in summary["missing"]
    assert summary["blocks_validation"] is False


def test_paper58_external_benchmark_malformed_per_region_metrics_stay_review(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_bad_per_region_metrics"
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
    (fixture / "metrics_by_method.csv").write_text(
        "\n".join(
            [
                "method,area",
                "geosos_flus_console,region_a",
                "paper58_semantic_keep_loo_selector,region_a",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert "metrics_by_method_required_columns_missing" in summary["missing"]
    assert summary["blocks_validation"] is False


def test_paper58_external_benchmark_invalid_metric_values_stay_review(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_bad_values"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
                "geosos_flus_console,43,0.2688,0.1323,0.3423,0.0741",
                "paper58_semantic_keep_loo_selector,43,bad,0.1471,0.3520,0.0721",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert "metric_summary_invalid_numeric_values" in summary["missing"]
    assert summary["blocks_validation"] is False


def test_paper58_external_benchmark_non_finite_per_region_metrics_stay_review(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_bad_per_region_values"
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
    (fixture / "metrics_by_method.csv").write_text(
        "\n".join(
            [
                "method,area,change_f1,fom,transition_accuracy,allocation_disagreement",
                "geosos_flus_console,region_a,0.26,0.13,0.34,0.07",
                "paper58_semantic_keep_loo_selector,region_a,NaN,0.15,0.35,0.06",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert "metrics_by_method_invalid_numeric_values" in summary["missing"]
    assert summary["blocks_validation"] is False
    json.dumps(summary, allow_nan=False)


def test_paper58_external_benchmark_non_finite_metric_values_stay_review(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_non_finite_values"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
                "geosos_flus_console,43,0.2688,0.1323,0.3423,0.0741",
                "paper58_semantic_keep_loo_selector,43,NaN,0.1471,0.3520,0.0721",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["status"] == "review"
    assert "metric_summary_invalid_numeric_values" in summary["missing"]
    assert summary["blocks_validation"] is False
    json.dumps(summary, allow_nan=False)


def test_paper58_external_benchmark_selects_strongest_baseline_row(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_multi_baseline"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
                "geosos_flus_weak,43,0.1000,0.0500,0.1000,0.2000",
                "paper58_semantic_keep_loo_selector,43,0.2929,0.1471,0.3520,0.0721",
                "geosos_flus_strong,43,0.3000,0.1500,0.3600,0.0700",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["metric_summary"]["baseline_method"] == "geosos_flus_strong"
    assert summary["metric_summary"]["paper58_vs_baseline_wins"] == 0
    assert summary["metric_summary"]["deltas"]["mean_change_f1"] < 0


def test_paper58_external_benchmark_tied_baseline_selection_is_deterministic(tmp_path):
    module = _load_validation_bundle_module()
    fixture = tmp_path / "paper58_tied_baseline"
    fixture.mkdir()
    (fixture / "metric_summary_by_method.csv").write_text(
        "\n".join(
            [
                "method,n,mean_change_f1,mean_fom,mean_transition_accuracy,mean_allocation_disagreement",
                "geosos_flus_b,43,0.2688,0.1323,0.3423,0.0741",
                "paper58_semantic_keep_loo_selector,43,0.2929,0.1471,0.3520,0.0721",
                "geosos_flus_a,43,0.2688,0.1323,0.3423,0.0741",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (fixture / "manifest.json").write_text(
        json.dumps({"method": "paper58_semantic_keep_loo_selector", "summary": {"n": 43}}),
        encoding="utf-8",
    )

    summary = module.build_paper58_external_benchmark(fixture)

    assert summary["metric_summary"]["baseline_method"] == "geosos_flus_a"


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
