"""Smoke tests for the TWM production onboarding runner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/run_twm_production_onboarding.py"


def _write_raw_approval_export(path: Path) -> None:
    path.write_text(
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


def _write_normalized_observed_history(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "unit_id,approval_id,project_id,approval_status,outcome,cluster,neighbors,x,y,area_m2,quality_score,action_type,action_mask_policy,action_mask_allowed,region_code,period,split,policy_effective_date,policy_version,synthetic,not_for_production",
                "PRJ-1,APR-1,PRJ-1,approved,0.31,PROD-R01,,106.20,29.60,1000,0.82,approve_with_conditions,mixed_risk_allowed_with_conditions,True,PROD-R01,2026Q1,training,2026Q1,RULE-2026-A,False,False",
                "PRJ-2,APR-2,PRJ-2,approved,0.28,PROD-R02,,106.21,29.61,1100,0.80,protect,mixed_risk_protect_allowed,True,PROD-R02,2026Q1,training,2026Q1,RULE-2026-B,False,False",
                "PRJ-3,APR-3,PRJ-3,approved,0.34,PROD-R03,,106.22,29.62,1200,0.78,restore,mixed_risk_restore_allowed,True,PROD-R03,2026Q2,training,2026Q2,RULE-2026-C,False,False",
                "PRJ-4,APR-4,PRJ-4,in_review,0.08,PROD-R04,,106.23,29.63,1300,0.76,approve_with_conditions,mixed_risk_blocked_condition_review,False,PROD-R04,2026Q2,training,2026Q2,RULE-2026-D,False,False",
                "PRJ-5,APR-5,PRJ-5,in_review,0.07,PROD-R05,,106.24,29.64,1400,0.74,protect,mixed_risk_protect_blocked,False,PROD-R05,2026Q3,training,2026Q3,RULE-2026-E,False,False",
                "PRJ-6,APR-6,PRJ-6,approved,0.36,PROD-R06,,106.25,29.65,1500,0.73,approve_with_conditions,mixed_risk_allowed_with_conditions,True,PROD-R06,2026Q3,holdout,2026Q3,RULE-2026-F,False,False",
                "PRJ-7,APR-7,PRJ-7,approved,0.37,PROD-R07,,106.26,29.66,1600,0.72,protect,mixed_risk_protect_allowed,True,PROD-R07,2026Q4,holdout,2026Q4,RULE-2026-G,False,False",
                "PRJ-8,APR-8,PRJ-8,approved,0.38,PROD-R08,,106.27,29.67,1700,0.71,restore,mixed_risk_restore_allowed,True,PROD-R08,2026Q4,holdout,2026Q4,RULE-2026-H,False,False",
                "PRJ-9,APR-9,PRJ-9,in_review,0.09,PROD-R09,,106.28,29.68,1800,0.70,approve_with_conditions,mixed_risk_blocked_condition_review,False,PROD-R09,2026Q4,holdout,2026Q4,RULE-2026-I,False,False",
                "PRJ-10,APR-10,PRJ-10,in_review,0.06,PROD-R10,,106.29,29.69,1900,0.69,protect,mixed_risk_protect_blocked,False,PROD-R10,2026Q4,holdout,2026Q4,RULE-2026-J,False,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_same_case_baseline_exports(output_dir: Path) -> tuple[Path, Path]:
    twm_path = output_dir / "twm_case_outputs.csv"
    baseline_path = output_dir / "manual_overlay_case_outputs.csv"
    twm_path.write_text(
        "\n".join(
            [
                "case_id,ground_truth_conflict,detected_conflict,evidence_linked,unsupported_recommendation,not_for_production,sanitization_level",
                "c001,true,true,true,false,true,real_sanitized",
                "c002,true,true,true,false,true,real_sanitized",
                "c003,false,false,true,false,true,real_sanitized",
                "c004,true,false,true,false,true,real_sanitized",
                "c005,false,false,true,false,true,real_sanitized",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    baseline_path.write_text(
        "\n".join(
            [
                "case_id,ground_truth_conflict,detected_conflict,evidence_linked,unsupported_recommendation,not_for_production,sanitization_level",
                "c001,true,true,true,false,true,real_sanitized",
                "c002,true,false,true,false,true,real_sanitized",
                "c003,false,false,true,false,true,real_sanitized",
                "c004,true,false,true,false,true,real_sanitized",
                "c005,false,false,true,false,true,real_sanitized",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return twm_path, baseline_path


def _write_case_output(path: Path, case_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "case_id,ground_truth_conflict,detected_conflict,evidence_linked,unsupported_recommendation,not_for_production,sanitization_level"
    ]
    rows.extend(f"{case_id},true,true,true,false,true,real_sanitized" for case_id in case_ids)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_twm_production_onboarding_runs_foundation_and_bundle_from_raw_export(tmp_path):
    raw_path = tmp_path / "raw_approval_export.csv"
    output_dir = tmp_path / "onboarding"
    normalized_path = output_dir / "normalized_production_observed_history.csv"
    _write_raw_approval_export(raw_path)

    subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--raw-production-observed-history",
            str(raw_path),
            "--normalized-production-observed-history-output",
            str(normalized_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    summary_path = output_dir / "twm_production_onboarding_summary.json"
    markdown_path = output_dir / "twm_production_onboarding_summary.md"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert normalized_path.exists()
    assert markdown_path.exists()
    assert summary["schema"] == "territory_world_model.production_onboarding_summary.v1"
    assert summary["status"] == "review"
    assert summary["observed_history"]["normalized_output"] == str(normalized_path)
    assert summary["observed_history"]["same_normalized_output"] is True
    assert summary["data_foundation"]["production_schema_status"] == "pass"
    assert summary["validation_bundle"]["production_preflight_status"] == "pass"
    assert summary["validation_bundle"]["readiness_gate_status"] == "review"
    assert summary["outputs"]["data_foundation_report"] == str(output_dir / "twm_data_foundation_validation.json")
    assert summary["outputs"]["validation_bundle_report"] == str(output_dir / "twm_validation_bundle.json")
    punch_list = summary["deployment_punch_list"]
    assert punch_list["schema"] == "territory_world_model.production_onboarding_punch_list.v1"
    assert punch_list["status"] == "review"
    gates = {item["gate"]: item for item in punch_list["actions"]}
    assert "production_scale_readiness_pass" in gates
    assert gates["production_scale_readiness_pass"]["phase"] == "production_scale"
    assert gates["production_scale_readiness_pass"]["blocks_current_run"] is False
    assert "production_observed_history_preflight_pass" not in gates
    assert "## Deployment Punch List" in markdown
    assert "production_scale_readiness_pass" in markdown


def test_twm_production_onboarding_accepts_already_normalized_observed_history(tmp_path):
    production_path = tmp_path / "production_observed_history.csv"
    output_dir = tmp_path / "onboarding_normalized"
    _write_normalized_observed_history(production_path)

    subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--production-observed-history",
            str(production_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "review"
    assert summary["observed_history"]["raw_source"] is None
    assert summary["observed_history"]["production_observed_history"] == str(production_path)
    assert summary["observed_history"]["normalized_output"] is None
    assert summary["observed_history"]["same_normalized_output"] is None
    assert summary["data_foundation"]["production_schema_status"] == "pass"
    assert summary["validation_bundle"]["production_preflight_status"] == "pass"
    assert summary["validation_bundle"]["production_preflight_history"] == str(production_path)


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
        cwd=REPO_ROOT,
        check=True,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert summary["baseline_evidence"]["status"] == "review"
    assert summary["baseline_evidence"]["export_validation_status"] == "pass"
    assert summary["baseline_evidence"]["overlap_count"] == 5
    assert summary["baseline_evidence"]["coverage_ratio"] == 1.0
    assert "baseline_evidence_pipeline_report" in summary["outputs"]
    pipeline_report = json.loads((output_dir / "twm_baseline_evidence_pipeline.json").read_text(encoding="utf-8"))
    assert summary["baseline_evidence"]["export_validation_status"] == pipeline_report["export_validation"]["status"]
    markdown = (output_dir / "twm_production_onboarding_summary.md").read_text(encoding="utf-8")
    assert "## Same-Case Baseline Evidence" in markdown
    assert "manual_gis_overlay_checklist" in markdown


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
        cwd=REPO_ROOT,
        check=True,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert summary["model_promotion_gate"]["schema"] == "territory_world_model.model_promotion_gate.v1"
    assert summary["model_promotion_gate"]["production_observed_history_status"] == "pass"
    assert summary["model_promotion_gate"]["same_case_baseline_status"] == "pass"
    assert summary["model_promotion_gate"]["decision"] == "blocked_by_production_scale_or_other_bundle_gates"


def test_twm_production_onboarding_same_basename_external_files_do_not_collide(tmp_path):
    production_path = tmp_path / "production_observed_history.csv"
    output_dir = tmp_path / "onboarding_same_basename"
    twm_path = tmp_path / "twm" / "cases.csv"
    baseline_path = tmp_path / "baseline" / "cases.csv"
    _write_normalized_observed_history(production_path)
    _write_case_output(twm_path, ["t001", "t002"])
    _write_case_output(baseline_path, ["b001", "b002"])

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
        cwd=REPO_ROOT,
        check=True,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert summary["baseline_evidence"]["status"] == "blocked"
    assert summary["baseline_evidence"]["pipeline_decision"] == "export_validation_blocked"
    assert summary["baseline_evidence"]["export_validation_status"] == "blocked"
    assert summary["baseline_evidence"]["overlap_count"] == 0


def test_twm_production_onboarding_writes_summary_when_strict_readiness_blocks(tmp_path):
    raw_path = tmp_path / "raw_approval_export.csv"
    output_dir = tmp_path / "onboarding_strict"
    normalized_path = output_dir / "normalized_production_observed_history.csv"
    _write_raw_approval_export(raw_path)

    subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--raw-production-observed-history",
            str(raw_path),
            "--normalized-production-observed-history-output",
            str(normalized_path),
            "--output-dir",
            str(output_dir),
            "--require-production-readiness",
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "blocked"
    assert summary["validation_bundle"]["readiness_gate_status"] == "blocked"
    assert "production_scale_readiness_pass" in summary["validation_bundle"]["readiness_missing"]
    punch_list = summary["deployment_punch_list"]
    assert punch_list["phase_counts"]["production_scale"] >= 1
    assert punch_list["severity_counts"]["blocking"] >= 1
    assert "production_scale" in summary["data_owner_next_steps"]
    assert any("sanitized production scale profile" in item for item in summary["data_owner_next_steps"]["production_scale"])
    markdown = (output_dir / "twm_production_onboarding_summary.md").read_text(encoding="utf-8")
    assert "## Data Owner Next Steps" in markdown
    assert "### production_scale" in markdown
    assert punch_list["status"] == "blocked"
    assert punch_list["blocking_action_count"] >= 1
    assert any(
        item["gate"] == "production_scale_readiness_pass" and item["blocks_current_run"] is True
        for item in punch_list["actions"]
    )
    assert summary["commands"][1]["returncode"] == 2


def test_twm_production_onboarding_fail_on_blocked_returns_nonzero_after_summary(tmp_path):
    raw_path = tmp_path / "raw_approval_export.csv"
    output_dir = tmp_path / "onboarding_fail_on_blocked"
    normalized_path = output_dir / "normalized_production_observed_history.csv"
    _write_raw_approval_export(raw_path)

    completed = subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--raw-production-observed-history",
            str(raw_path),
            "--normalized-production-observed-history-output",
            str(normalized_path),
            "--output-dir",
            str(output_dir),
            "--require-production-readiness",
            "--fail-on-blocked",
        ],
        cwd=REPO_ROOT,
        check=False,
    )

    summary = json.loads((output_dir / "twm_production_onboarding_summary.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert summary["status"] == "blocked"
    assert summary["validation_bundle"]["readiness_gate_status"] == "blocked"


def test_twm_production_onboarding_rejects_ambiguous_raw_and_normalized_inputs(tmp_path):
    raw_path = tmp_path / "raw_approval_export.csv"
    production_path = tmp_path / "production_observed_history.csv"
    output_dir = tmp_path / "onboarding_ambiguous"
    _write_raw_approval_export(raw_path)
    _write_normalized_observed_history(production_path)

    completed = subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--raw-production-observed-history",
            str(raw_path),
            "--production-observed-history",
            str(production_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 2
    assert "choose exactly one observed-history input" in completed.stdout
    assert not (output_dir / "twm_production_onboarding_summary.json").exists()


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
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 2
    assert "baseline evidence requires --claim-id, --baseline-id, --twm-case-output and --baseline-case-output together" in completed.stdout
    assert not (output_dir / "twm_production_onboarding_summary.json").exists()


def test_twm_production_onboarding_missing_external_baseline_file_errors_cleanly(tmp_path):
    production_path = tmp_path / "production_observed_history.csv"
    output_dir = tmp_path / "onboarding_missing_external_baseline"
    twm_path = tmp_path / "twm" / "cases.csv"
    missing_baseline_path = tmp_path / "baseline" / "missing_cases.csv"
    _write_normalized_observed_history(production_path)
    _write_case_output(twm_path, ["c001", "c002"])

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
            "--baseline-id",
            "manual_gis_overlay_checklist",
            "--twm-case-output",
            str(twm_path),
            "--baseline-case-output",
            str(missing_baseline_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 2
    assert "baseline evidence file not found" in completed.stdout
    assert str(missing_baseline_path) in completed.stdout
    assert not (output_dir / "twm_production_onboarding_summary.json").exists()


def test_twm_production_onboarding_requires_explicit_normalized_output_for_raw_input(tmp_path):
    raw_path = tmp_path / "raw_approval_export.csv"
    output_dir = tmp_path / "onboarding_missing_normalized_output"
    _write_raw_approval_export(raw_path)

    completed = subprocess.run(
        [
            "/Users/zhouning/gisdataagent/.venv/bin/python",
            str(SCRIPT),
            "--raw-production-observed-history",
            str(raw_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 2
    assert "--normalized-production-observed-history-output is required" in completed.stdout
    assert not (output_dir / "twm_production_onboarding_summary.json").exists()
