from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_agent.test_assess_geospatial_kernel_internal_innovation_episode_preflight import (
    _write_json,
)
from data_agent.test_run_geospatial_kernel_internal_innovation_manning_episode import (
    _executable_episode_fixture,
)
from scripts import compile_geospatial_kernel_internal_innovation_execution_ledger as ledger
from scripts import run_geospatial_kernel_internal_innovation_manning_episode as execute


def test_empty_inventory_is_integral_but_not_fit_ready(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    protocol.write_bytes(ledger.PROTOCOL_PATH.read_bytes())

    report = ledger.compile_internal_innovation_execution_ledger(
        (),
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["status"] == "awaiting_prospective_episode_manifests"
    assert report["ledger_integrity_passed"] is True
    assert report["diagnostic_fit_ready"] is False
    assert report["data_isolation"]["outcome_argument_accepted"] is False


def test_ready_manifest_without_report_is_pending(tmp_path: Path) -> None:
    manifest, protocol = _executable_episode_fixture(tmp_path)

    report = ledger.compile_internal_innovation_execution_ledger(
        (manifest,),
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["status"] == "awaiting_outcome_free_episode_execution"
    assert report["reconciliation"]["pending_execution_count"] == 1
    assert report["reconciliation"]["entries"][0]["reconciliation_status"] == (
        "pending_execution"
    )
    assert report["diagnostic_fit_ready"] is False


def test_sealed_episode_is_recomputed_and_counted(tmp_path: Path) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)

    report = ledger.compile_internal_innovation_execution_ledger(
        (manifest,),
        execution_report_paths=(execution_report,),
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["status"] == "accumulating_sealed_cross_system_episodes"
    assert report["reconciliation"]["executed_and_sealed_count"] == 1
    assert report["reconciliation"]["entries"][0]["reconciliation_status"] == (
        "executed_and_sealed"
    )
    coverage = report["coverage_by_system"]["center_hill"]
    assert coverage["sealed_episode_count"] == 1
    assert coverage["unique_issue_time_count"] == 1
    assert coverage["sealed_hourly_prediction_step_count"] == 24
    assert report["diagnostic_fit_ready"] is False
    assert report["diagnostic_fit_gates"]["all_episode_semantics_recomputed"] is True
    assert report["data_isolation"]["outcome_values_loaded"] is False


def test_invalid_manifest_is_reconciled_without_execution(tmp_path: Path) -> None:
    manifest, protocol = _executable_episode_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["claim_boundary"]["retrospective_replay"] = True
    _write_json(manifest, payload)

    report = ledger.compile_internal_innovation_execution_ledger(
        (manifest,),
        repo_root=tmp_path,
        protocol_path=protocol,
    )

    assert report["status"] == "blocked_invalid_prospective_episode_manifest"
    assert report["reconciliation"]["invalid_manifest_count"] == 1
    assert report["reconciliation"]["entries"][0]["reconciliation_status"] == "invalid"
    assert report["diagnostic_fit_gates"]["no_invalid_submitted_manifest"] is False
    assert report["ledger_integrity_passed"] is False


def test_duplicate_manifest_episode_and_issue_are_rejected(tmp_path: Path) -> None:
    manifest, protocol = _executable_episode_fixture(tmp_path)

    with pytest.raises(ValueError, match="duplicate_episode_id"):
        ledger.compile_internal_innovation_execution_ledger(
            (manifest, manifest),
            repo_root=tmp_path,
            protocol_path=protocol,
        )


def test_prediction_identity_tamper_is_rejected(tmp_path: Path) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    execution_payload = json.loads(execution_report.read_text(encoding="utf-8"))
    prediction = tmp_path / execution_payload["prediction_artifact"]["path"]
    prediction.write_bytes(prediction.read_bytes() + b" ")

    with pytest.raises(ValueError, match="artifact_identity_mismatch"):
        ledger.compile_internal_innovation_execution_ledger(
            (manifest,),
            execution_report_paths=(execution_report,),
            repo_root=tmp_path,
            protocol_path=protocol,
        )


def test_report_cannot_claim_outcome_access_or_fit(tmp_path: Path) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    payload = json.loads(execution_report.read_text(encoding="utf-8"))
    payload["data_isolation"]["outcome_values_loaded"] = True
    _write_json(execution_report, payload)

    with pytest.raises(ValueError, match="report_claim_invalid"):
        ledger.compile_internal_innovation_execution_ledger(
            (manifest,),
            execution_report_paths=(execution_report,),
            repo_root=tmp_path,
            protocol_path=protocol,
        )


def test_reused_prediction_or_telemetry_hash_is_rejected() -> None:
    descriptor = {"sha256": "a" * 64}
    records = [
        {
            "prediction_artifact": descriptor,
            "telemetry_artifacts": {"feature_axis_artifact": {"sha256": "b" * 64}},
        },
        {
            "prediction_artifact": {"sha256": "c" * 64},
            "telemetry_artifacts": {"feature_axis_artifact": descriptor},
        },
    ]

    with pytest.raises(ValueError, match="reused_output_hash"):
        ledger._reject_reused_output_hashes(records)


def test_noncompensatory_cross_system_coverage_thresholds() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    records = [
        {
            "system_id": system_id,
            "forecast_issue_time": (start + timedelta(days=index)).isoformat(),
            "step_count": 24,
        }
        for system_id in ledger.SYSTEM_IDS
        for index in range(28)
    ]

    coverage = ledger._system_coverage(records)

    for system_id in ledger.SYSTEM_IDS:
        assert coverage[system_id]["sealed_episode_count"] == 28
        assert coverage[system_id]["unique_issue_time_count"] == 28
        assert coverage[system_id]["sealed_hourly_prediction_step_count"] == 672
        assert coverage[system_id]["episode_minimum_met"] is True
        assert coverage[system_id]["unique_issue_time_minimum_met"] is True
        assert coverage[system_id]["hourly_prediction_step_minimum_met"] is True


def _sealed_episode(root: Path) -> tuple[Path, Path, Path]:
    manifest, protocol = _executable_episode_fixture(root)
    output = root / "sealed/episode-001"
    execute.execute_manning_episode(
        manifest_path=manifest,
        output_directory=output,
        repo_root=root,
        protocol_path=protocol,
    )
    return manifest, protocol, output / execute.REPORT_FILENAME
