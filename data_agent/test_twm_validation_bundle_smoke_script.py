"""Tests for the TWM validation-bundle smoke entrypoint."""

import json
import os
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/smoke_twm_validation_bundle.sh")


def test_twm_validation_bundle_smoke_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_twm_validation_bundle_smoke_script_exposes_inner_network_controls():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "TWM_PRODUCTION_OBSERVED_HISTORY" in text
    assert "TWM_NORMALIZE_PRODUCTION_OBSERVED_HISTORY_SOURCE" in text
    assert "TWM_NORMALIZED_PRODUCTION_OBSERVED_HISTORY_OUTPUT" in text
    assert "TWM_PRODUCTION_SCALE_PROFILE" in text
    assert "TWM_REQUIRE_PRODUCTION_READINESS" in text
    assert "TWM_FAIL_ON_BLOCKED" in text
    assert "TWM_REQUIRE_SCCA_PASS" in text
    assert "--production-observed-history" in text
    assert "--normalize-production-observed-history-source" in text
    assert "--normalized-production-observed-history-output" in text
    assert "--production-scale-profile" in text
    assert "--require-production-readiness" in text
    assert "--fail-on-blocked" in text
    assert ".venv/bin/python" in text


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
