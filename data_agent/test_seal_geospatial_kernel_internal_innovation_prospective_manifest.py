from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest

from data_agent.test_assess_geospatial_kernel_internal_innovation_episode_preflight import (
    ISSUE,
    START,
    _write_json,
)
from data_agent.test_run_geospatial_kernel_internal_innovation_manning_episode import (
    _executable_episode_fixture,
)
from scripts import compile_geospatial_kernel_internal_innovation_execution_ledger as ledger
from scripts import run_geospatial_kernel_internal_innovation_manning_episode as execute
from scripts import seal_geospatial_kernel_internal_innovation_prospective_manifest as seal


def test_sealer_publishes_preflighted_manifest_and_full_execution_chain(
    tmp_path: Path,
) -> None:
    inputs = _issuer_fixture(tmp_path)
    output = tmp_path / "issued-manifest.json"

    report = _seal(inputs, output=output)

    assert report["status"] == "prospective_manifest_sealed_preflight_ready"
    assert report["preflight"]["episode_execution_ready"] is True
    assert report["data_isolation"]["outcome_values_loaded"] is False
    assert report["claim_boundary"]["trusted_external_timestamp_verified"] is False
    body = output.read_bytes()
    assert hashlib.sha256(body).hexdigest() == report["manifest_artifact"]["sha256"]
    manifest = json.loads(body)
    assert manifest["issuance"]["input_inventory_complete"] is True
    assert manifest["issuance"]["outcome_argument_accepted"] is False
    assert manifest["execution_addendum"]["addendum_seal_sha256"]

    execution_directory = tmp_path / "sealed/episode-001"
    execute.execute_manning_episode(
        manifest_path=output,
        output_directory=execution_directory,
        repo_root=tmp_path,
        protocol_path=inputs["protocol"],
    )
    execution_report = execution_directory / execute.REPORT_FILENAME
    compiled = ledger.compile_internal_innovation_execution_ledger(
        (output,),
        execution_report_paths=(execution_report,),
        repo_root=tmp_path,
        protocol_path=inputs["protocol"],
    )
    assert compiled["reconciliation"]["executed_and_sealed_count"] == 1
    assert compiled["coverage_by_system"]["center_hill"][
        "sealed_hourly_prediction_step_count"
    ] == 24


def test_sealer_requires_explicit_prospective_acknowledgement(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="sealing_disabled"):
        seal.seal_prospective_manifest(
            episode_id="episode-001",
            system_id="center_hill",
            forecast_issue_time=ISSUE,
            support_start=START,
            input_artifact_paths={},
            input_availability_receipts_path=tmp_path / "missing.json",
            output_path=tmp_path / "manifest.json",
        )


@pytest.mark.parametrize(
    "sealed_at",
    [ISSUE - timedelta(seconds=1), ISSUE + timedelta(minutes=15, seconds=1)],
)
def test_sealer_rejects_out_of_window_issuance(
    tmp_path: Path,
    sealed_at,
) -> None:
    with pytest.raises(ValueError, match="ordering_invalid"):
        seal.seal_prospective_manifest(
            episode_id="episode-001",
            system_id="center_hill",
            forecast_issue_time=ISSUE,
            support_start=START,
            input_artifact_paths={},
            input_availability_receipts_path=tmp_path / "missing.json",
            output_path=tmp_path / "manifest.json",
            enable_prospective_manifest_sealing=True,
            sealed_at=sealed_at,
        )


def test_sealer_rejects_source_hash_not_bound_by_receipt(tmp_path: Path) -> None:
    inputs = _issuer_fixture(tmp_path)
    receipts = json.loads(inputs["receipts"].read_text(encoding="utf-8"))
    receipts["receipts"][0]["artifact_sha256"] = "0" * 64
    _write_json(inputs["receipts"], receipts)
    output = tmp_path / "manifest.json"

    with pytest.raises(ValueError, match="source_receipt_mismatch"):
        _seal(inputs, output=output)
    assert not output.exists()


def test_sealer_rejects_receipt_issued_after_forecast_issue(tmp_path: Path) -> None:
    inputs = _issuer_fixture(tmp_path)
    receipts = json.loads(inputs["receipts"].read_text(encoding="utf-8"))
    receipts["issued_at"] = (ISSUE + timedelta(seconds=1)).isoformat()
    _write_json(inputs["receipts"], receipts)
    output = tmp_path / "manifest.json"

    with pytest.raises(ValueError, match="receipt_ordering_invalid"):
        _seal(inputs, output=output)
    assert not output.exists()


def test_sealer_rejects_outcome_content_even_when_receipt_hash_matches(
    tmp_path: Path,
) -> None:
    inputs = _issuer_fixture(tmp_path)
    forcing_path = inputs["artifacts"]["distributed_forcing_forecast"]
    forcing = json.loads(forcing_path.read_text(encoding="utf-8"))
    forcing["outcome_values"] = [1.0]
    _write_json(forcing_path, forcing)
    receipts = json.loads(inputs["receipts"].read_text(encoding="utf-8"))
    for row in receipts["receipts"]:
        if row["artifact_name"] == "distributed_forcing_forecast":
            row["artifact_sha256"] = hashlib.sha256(forcing_path.read_bytes()).hexdigest()
    _write_json(inputs["receipts"], receipts)
    output = tmp_path / "manifest.json"

    with pytest.raises(ValueError, match="outcome_content_forbidden"):
        _seal(inputs, output=output)
    assert not output.exists()


def test_failed_preflight_leaves_no_manifest_or_temporary_file(tmp_path: Path) -> None:
    inputs = _issuer_fixture(tmp_path)
    action_path = inputs["artifacts"]["reservoir_action_schedule"]
    action = json.loads(action_path.read_text(encoding="utf-8"))
    action["known_at_issue"] = False
    _write_json(action_path, action)
    receipts = json.loads(inputs["receipts"].read_text(encoding="utf-8"))
    for row in receipts["receipts"]:
        if row["artifact_name"] == "reservoir_action_schedule":
            row["artifact_sha256"] = hashlib.sha256(action_path.read_bytes()).hexdigest()
    _write_json(inputs["receipts"], receipts)
    output = tmp_path / "manifest.json"

    with pytest.raises(ValueError, match="preflight_failed"):
        _seal(inputs, output=output)
    assert not output.exists()
    assert not list(tmp_path.glob(".manifest.json.*.preflight"))


def test_sealer_refuses_existing_output(tmp_path: Path) -> None:
    inputs = _issuer_fixture(tmp_path)
    output = tmp_path / "manifest.json"
    output.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="output_conflict"):
        _seal(inputs, output=output)
    assert output.read_text(encoding="utf-8") == "existing\n"


def _issuer_fixture(root: Path) -> dict[str, object]:
    manifest_path, protocol = _executable_episode_fixture(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt_path = root / manifest["artifacts"]["input_availability_receipts"]["path"]
    receipts = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipts["issued_at"] = (ISSUE - timedelta(minutes=1)).isoformat()
    receipts["issuer_id"] = "fixture:source-availability-issuer"
    _write_json(receipt_path, receipts)
    return {
        "episode_id": manifest["episode_id"],
        "system_id": manifest["system_id"],
        "protocol": protocol,
        "addendum": root / manifest["execution_addendum"]["path"],
        "receipts": receipt_path,
        "artifacts": {
            name: root / descriptor["path"]
            for name, descriptor in manifest["artifacts"].items()
            if name != "input_availability_receipts"
        },
    }


def _seal(inputs: dict[str, object], *, output: Path) -> dict[str, object]:
    return seal.seal_prospective_manifest(
        episode_id=str(inputs["episode_id"]),
        system_id=str(inputs["system_id"]),
        forecast_issue_time=ISSUE,
        support_start=START,
        input_artifact_paths=inputs["artifacts"],
        input_availability_receipts_path=inputs["receipts"],
        output_path=output,
        protocol_path=inputs["protocol"],
        execution_addendum_path=inputs["addendum"],
        repo_root=output.parent,
        enable_prospective_manifest_sealing=True,
        sealed_at=ISSUE + timedelta(minutes=5),
    )
