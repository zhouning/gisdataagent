from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.platform_runtime.deployment_profile import load_deployment_profile
from data_agent.platform_runtime.recovery_rehearsal import RECOVERY_LIMITATIONS
from data_agent.platform_runtime.recovery_sli_baseline import (
    RecoverySLIBaseline,
    RecoverySLIBaselineError,
    build_recovery_sli_baseline,
    load_recovery_sli_baseline,
    verify_recovery_sli_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "config" / "deployment_profiles" / "main-compose-dev.json"
BASELINE_PATH = (
    REPO_ROOT
    / "config"
    / "recovery_sli_baselines"
    / "main-compose-dev-20260731.json"
)
EVIDENCE_PATH = (
    BASELINE_PATH.parent
    / "evidence"
    / "main-compose-dev-20260731-recovery-report.json"
)


def _report() -> dict:
    profile = load_deployment_profile(PROFILE_PATH)
    source = {
        "database_bytes": 1000,
        "migration_count": profile.migrations.count,
        "migration_fingerprint": profile.migrations.fingerprint,
        "standard": {
            "doc_code": profile.released_standard.doc_code,
            "version_label": profile.released_standard.version_label,
            "status": "released",
            "element_count": profile.released_standard.element_count,
            "elements_sha256": profile.released_standard.elements_sha256,
        },
        "representative_table_counts": {"twm_state_object": 10},
    }
    restored = deepcopy(source)
    restored["database_bytes"] = 900
    object_facts = {
        "object_count": 2,
        "bytes": 20,
        "inventory_sha256": "a" * 64,
    }
    blockers = list(
        dict.fromkeys(
            (*profile.governance.promotion_blockers, *RECOVERY_LIMITATIONS)
        )
    )
    return {
        "schema": "gis-data-agent.recovery-rehearsal.v1",
        "generated_at": "2026-07-31T12:08:14+00:00",
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "scope": "compose_isolated_logical_recovery",
        "technical_pass": True,
        "promotion_ready": False,
        "promotion_blockers": blockers,
        "deployment": {
            "technical_pass": True,
            "profile_contamination": False,
        },
        "database": {
            "dump_bytes": 500,
            "backup_duration_seconds": 10.0,
            "restore_duration_seconds": 8.0,
            "source": source,
            "restored": restored,
        },
        "object_storage": {
            "rehearsal_duration_seconds": 2.0,
            "buckets": [
                {
                    "bucket": "test-bucket",
                    "source": object_facts,
                    "restored": deepcopy(object_facts),
                }
            ],
        },
        "observed_total_seconds": 21.0,
        "slo_status": "observed_not_approved",
    }


def test_versioned_recovery_sli_baseline_is_strict_non_secret_and_unapproved() -> None:
    baseline = load_recovery_sli_baseline(BASELINE_PATH)
    profile = load_deployment_profile(PROFILE_PATH)
    raw = BASELINE_PATH.read_text(encoding="utf-8")

    assert baseline.profile_id == profile.profile_id
    assert baseline.observation.compose_config_sha256 == profile.compose.config_sha256
    assert baseline.observation.sample_count == 1
    assert baseline.governance.interpretation == "single_observation_not_objective"
    assert baseline.governance.promotion_ready is False
    assert baseline.governance.slo_status == "not_approved"
    assert "/Users/" not in raw
    assert "password" not in raw.lower()
    assert "object_key" not in raw


@pytest.mark.xfail(
    reason=(
        "AR-0 A0-5 未收口：2026-07-31 的演练证据记录 migration_count=93 / "
        "fingerprint=53ddf178936f4b6ce909bf553e66f33270d9cf815a87458e60de332f69af9ee4，"
        "而 main-compose-dev profile 已推进到 count=156 / "
        "fingerprint=85c33b9811a5e4bdd17689ccf54d1ee24cf90aa7bea3da665c6cfd06b7e3b64b。"
        "observation_reproducible 因此 fail closed，这是正确行为，不是回归。"
        "解除方式是对当前 migration 基线重跑 recovery 演练并重新冻结 baseline，"
        "不得改写断言或刷新 fingerprint。"
    ),
    strict=True,
)
def test_versioned_baseline_reproduces_from_versioned_evidence() -> None:
    baseline = load_recovery_sli_baseline(BASELINE_PATH)
    profile = load_deployment_profile(PROFILE_PATH)
    report = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    evidence_raw = EVIDENCE_PATH.read_text(encoding="utf-8")

    verification = verify_recovery_sli_baseline(
        baseline=baseline,
        profile=profile,
        report=report,
    )

    assert verification.technical_pass is True
    assert "/Users/" not in evidence_raw
    assert "/private/" not in evidence_raw
    assert "/tmp/" not in evidence_raw
    assert "password" not in evidence_raw.lower()
    assert "object_key" not in evidence_raw


def test_build_and_verify_recovery_sli_observation() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    report = _report()
    baseline = build_recovery_sli_baseline(
        baseline_id="unit-compose-dev-20260731",
        profile=profile,
        report=report,
    )

    verification = verify_recovery_sli_baseline(
        baseline=baseline,
        profile=profile,
        report=report,
    )

    assert verification.technical_pass is True
    assert baseline.observation.database.source_database_bytes == 1000
    assert baseline.observation.object_storage.object_count == 2
    assert baseline.governance.promotion_ready is False
    assert set(RECOVERY_LIMITATIONS).issubset(
        baseline.governance.promotion_blockers
    )
    assert verification.to_dict()["promotion_ready"] is False


def test_verifier_fails_closed_when_report_content_drifts() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    report = _report()
    baseline = build_recovery_sli_baseline(
        baseline_id="unit-compose-dev-20260731",
        profile=profile,
        report=report,
    )
    drifted = deepcopy(report)
    drifted["object_storage"]["buckets"][0]["source"]["object_count"] = 3
    drifted["object_storage"]["buckets"][0]["restored"]["object_count"] = 3

    verification = verify_recovery_sli_baseline(
        baseline=baseline,
        profile=profile,
        report=drifted,
    )

    assert verification.technical_pass is False
    assert verification.checks["report_evidence_identity"] is False
    assert verification.checks["observation_reproducible"] is False
    assert verification.to_dict()["promotion_ready"] is False


def test_failed_or_promotion_ready_report_cannot_become_a_baseline() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    report = _report()
    report["technical_pass"] = False
    report["promotion_ready"] = True

    with pytest.raises(RecoverySLIBaselineError, match="report.envelope"):
        build_recovery_sli_baseline(
            baseline_id="unit-compose-dev-20260731",
            profile=profile,
            report=report,
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("database_password", "must-not-leak"),
        ("object_keys", ["lake/raw/data.parquet"]),
        ("debug_location", "/Users/operator/private/report.json"),
    ],
)
def test_sensitive_report_evidence_is_rejected(key: str, value: object) -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    report = _report()
    report[key] = value

    with pytest.raises(RecoverySLIBaselineError, match="sensitive_evidence"):
        build_recovery_sli_baseline(
            baseline_id="unit-compose-dev-20260731",
            profile=profile,
            report=report,
        )


def test_baseline_schema_rejects_slo_or_rto_objectives() -> None:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    payload["governance"]["rto_seconds"] = 459.499

    with pytest.raises(ValidationError, match="rto_seconds"):
        RecoverySLIBaseline.model_validate(payload)


def test_profile_only_check_cannot_claim_evidence_verification() -> None:
    baseline = load_recovery_sli_baseline(BASELINE_PATH)
    profile = load_deployment_profile(PROFILE_PATH)

    verification = verify_recovery_sli_baseline(
        baseline=baseline,
        profile=profile,
        report=None,
    )

    assert verification.checks["profile_identity"] is True
    assert verification.checks["report_evidence_identity"] is False
    assert verification.technical_pass is False
