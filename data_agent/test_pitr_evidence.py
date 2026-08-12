from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.platform_runtime.deployment_profile import load_deployment_profile
from data_agent.platform_runtime.pitr_evidence import (
    PITREvidenceError,
    PITREvidenceSeal,
    build_pitr_evidence_seal,
    load_pitr_evidence_seal,
    verify_pitr_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "config" / "deployment_profiles" / "main-compose-dev.json"
SEAL_PATH = (
    REPO_ROOT
    / "config"
    / "recovery_sli_baselines"
    / "main-compose-dev-20260731-pitr.json"
)
REPORT_PATH = (
    SEAL_PATH.parent
    / "evidence"
    / "main-compose-dev-20260731-pitr-report.json"
)


def _report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


@pytest.mark.xfail(
    reason=(
        "AR-0 A0-5 未收口：2026-07-31 的 PITR 证据记录 migration_count=93 / "
        "fingerprint=53ddf178936f4b6ce909bf553e66f33270d9cf815a87458e60de332f69af9ee4，"
        "而 main-compose-dev profile 已推进到 count=156 / "
        "fingerprint=85c33b9811a5e4bdd17689ccf54d1ee24cf90aa7bea3da665c6cfd06b7e3b64b，"
        "触发 _validate_database_profile_identity 的 database.profile_identity fail closed。"
        "released_standard 仍完全一致，仅 migration 基线漂移。"
        "解除方式是对当前 migration 基线重跑 PITR 演练并重新冻结 seal，"
        "不得改写断言或刷新 fingerprint。"
    ),
    strict=True,
)
def test_versioned_pitr_seal_reproduces_and_never_promotes() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    seal = load_pitr_evidence_seal(SEAL_PATH)
    report = _report()

    verification = verify_pitr_evidence(
        seal=seal,
        profile=profile,
        report=report,
    )

    assert verification.technical_pass is True
    assert seal.observation.source_archive_mode == "off"
    assert seal.observation.sample_count == 1
    assert seal.proof.target_after_base_backup is True
    assert seal.proof.later_state_excluded is True
    assert seal.proof.continuous_archive_configured is False
    assert seal.governance.promotion_ready is False
    assert verification.to_dict()["promotion_ready"] is False


def test_versioned_pitr_inputs_are_non_secret_and_path_free() -> None:
    raw = SEAL_PATH.read_text(encoding="utf-8") + REPORT_PATH.read_text(
        encoding="utf-8"
    )

    assert "/Users/" not in raw
    assert "/private/" not in raw
    assert "/tmp/" not in raw
    assert "password" not in raw.lower()
    assert "object_key" not in raw
    assert "gda_pitr_probe_" not in raw


def test_report_drift_breaks_hash_and_full_reproduction() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    seal = load_pitr_evidence_seal(SEAL_PATH)
    report = _report()
    report["wal_stream"]["bytes"] += 1

    verification = verify_pitr_evidence(
        seal=seal,
        profile=profile,
        report=report,
    )

    assert verification.technical_pass is False
    assert verification.checks["report_evidence_identity"] is False
    assert verification.checks["evidence_reproducible"] is False


@pytest.mark.xfail(
    reason=(
        "AR-0 A0-5 未收口：与 test_versioned_pitr_seal_reproduces_and_never_promotes "
        "同一根因。该用例先要求陈旧证据能被正常封存，再验证篡改/乱序报告被拒绝；"
        "由于 migration 基线已从 93 漂移到 156，前置封存即 fail closed。"
        "解除方式同为重跑 PITR 演练并重新冻结 seal。"
    ),
    strict=True,
)
def test_failed_or_unordered_report_cannot_be_sealed() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    report = _report()
    report["technical_pass"] = False
    with pytest.raises(PITREvidenceError, match="envelope"):
        build_pitr_evidence_seal(
            seal_id="unit-compose-dev-pitr",
            profile=profile,
            report=report,
        )

    report = _report()
    report["wal_stream"]["target_timestamp"] = report["wal_stream"][
        "later_timestamp"
    ]
    with pytest.raises(PITREvidenceError, match="wal.timeline"):
        build_pitr_evidence_seal(
            seal_id="unit-compose-dev-pitr",
            profile=profile,
            report=report,
        )


def test_pitr_seal_rejects_rpo_or_rto_objectives() -> None:
    payload = json.loads(SEAL_PATH.read_text(encoding="utf-8"))
    payload["governance"]["rpo_seconds"] = 1.188492

    with pytest.raises(ValidationError, match="rpo_seconds"):
        PITREvidenceSeal.model_validate(payload)


def test_profile_only_verification_cannot_claim_evidence_pass() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    seal = load_pitr_evidence_seal(SEAL_PATH)

    verification = verify_pitr_evidence(
        seal=seal,
        profile=profile,
        report=None,
    )

    assert verification.checks["profile_identity"] is True
    assert verification.checks["report_evidence_identity"] is False
    assert verification.technical_pass is False


def test_cleanup_proof_cannot_be_downgraded_to_false() -> None:
    payload = json.loads(SEAL_PATH.read_text(encoding="utf-8"))
    payload["proof"]["replication_slot_removed"] = False

    with pytest.raises(ValidationError, match="replication_slot_removed"):
        PITREvidenceSeal.model_validate(payload)
