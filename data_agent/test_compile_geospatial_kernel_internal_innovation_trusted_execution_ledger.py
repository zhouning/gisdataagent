from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_agent.test_compile_geospatial_kernel_internal_innovation_execution_ledger import (
    _sealed_episode,
)
from scripts import (
    compile_geospatial_kernel_internal_innovation_trusted_execution_ledger as trusted,
)
from scripts import verify_geospatial_kernel_internal_innovation_rfc3161_timestamp as verify

REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT_LEDGER_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_trusted_execution_ledger.json"
)


def test_current_trusted_ledger_recomputes_with_zero_real_episodes() -> None:
    frozen = json.loads(CURRENT_LEDGER_PATH.read_text(encoding="utf-8"))

    assert frozen == trusted.compile_trusted_execution_ledger(
        (),
        generated_at=datetime.fromisoformat(frozen["generated_at"]),
    )
    assert frozen["status"] == "blocked_no_registered_rfc3161_timestamp_authority"
    assert frozen["submitted_manifest_count"] == 0
    assert frozen["timestamp_reconciliation"]["trusted_timestamp_count"] == 0
    assert frozen["diagnostic_fit_ready"] is False


def test_timestamped_sealed_episode_passes_external_gate_but_not_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    binding = _timestamp_binding(tmp_path, manifest)
    _install_ready_registry_and_verifier(monkeypatch, tmp_path)

    report = trusted.compile_trusted_execution_ledger(
        (manifest,),
        execution_report_paths=(execution_report,),
        timestamp_binding_paths=(binding,),
        repo_root=tmp_path,
        protocol_path=protocol,
        registry_path=tmp_path / "registry.json",
        generated_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
    )

    assert report["status"] == "accumulating_timestamped_cross_system_episodes"
    assert report["timestamp_reconciliation"]["trusted_timestamp_count"] == 1
    assert report["diagnostic_fit_gates"][
        "every_manifest_receipt_has_trusted_external_timestamp"
    ] is True
    assert report["diagnostic_fit_gates"]["base_diagnostic_fit_coverage_ready"] is False
    assert report["diagnostic_fit_ready"] is False
    assert report["claim_boundary"]["all_manifest_receipts_externally_timestamped"] is True
    assert report["data_isolation"]["outcome_values_loaded"] is False


def test_diagnostic_fit_opens_only_when_base_and_timestamp_gates_both_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    binding = _timestamp_binding(tmp_path, manifest)
    base_ready = trusted.base_ledger.compile_internal_innovation_execution_ledger(
        (manifest,),
        execution_report_paths=(execution_report,),
        repo_root=tmp_path,
        protocol_path=protocol,
    )
    base_ready["status"] = "diagnostic_fit_ready_outcomes_still_forbidden"
    base_ready["diagnostic_fit_ready"] = True
    base_ready["diagnostic_fit_gates"] = {
        name: True for name in base_ready["diagnostic_fit_gates"]
    }
    monkeypatch.setattr(
        trusted.base_ledger,
        "compile_internal_innovation_execution_ledger",
        lambda *args, **kwargs: base_ready,
    )
    _install_ready_registry_and_verifier(monkeypatch, tmp_path)

    report = trusted.compile_trusted_execution_ledger(
        (manifest,),
        execution_report_paths=(execution_report,),
        timestamp_binding_paths=(binding,),
        repo_root=tmp_path,
        protocol_path=protocol,
        registry_path=tmp_path / "registry.json",
        generated_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
    )

    assert report["status"] == (
        "diagnostic_fit_ready_with_trusted_external_timestamps"
    )
    assert report["diagnostic_fit_ready"] is True
    assert all(report["diagnostic_fit_gates"].values())
    assert report["claim_boundary"]["diagnostic_fit_authorized"] is True
    assert report["claim_boundary"]["innovation_fitted"] is False


def test_registered_authority_does_not_compensate_for_missing_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    _install_ready_registry_and_verifier(monkeypatch, tmp_path)

    report = trusted.compile_trusted_execution_ledger(
        (manifest,),
        execution_report_paths=(execution_report,),
        repo_root=tmp_path,
        protocol_path=protocol,
        registry_path=tmp_path / "registry.json",
    )

    assert report["status"] == "awaiting_complete_timestamp_binding_inventory"
    assert report["timestamp_reconciliation"]["missing_timestamp_binding_count"] == 1
    assert report["diagnostic_fit_gates"][
        "complete_one_to_one_timestamp_binding_inventory"
    ] is False
    assert report["diagnostic_fit_ready"] is False


def test_envelope_must_bind_exact_manifest_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    binding = _timestamp_binding(tmp_path, manifest)
    _install_ready_registry_and_verifier(
        monkeypatch,
        tmp_path,
        wrong_receipt_hash=True,
    )

    report = trusted.compile_trusted_execution_ledger(
        (manifest,),
        execution_report_paths=(execution_report,),
        timestamp_binding_paths=(binding,),
        repo_root=tmp_path,
        protocol_path=protocol,
        registry_path=tmp_path / "registry.json",
    )

    entry = report["timestamp_reconciliation"]["entries"][0]
    assert entry["status"] == "invalid_external_timestamp"
    assert entry["trusted_external_timestamp_verified"] is False
    assert "envelope_invalid" in entry["verification_error"]
    assert report["diagnostic_fit_ready"] is False


def test_duplicate_timestamp_binding_is_rejected(tmp_path: Path) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    binding = _timestamp_binding(tmp_path, manifest)
    registry = _copy_registry(tmp_path)

    with pytest.raises(ValueError, match="duplicate_binding_episode"):
        trusted.compile_trusted_execution_ledger(
            (manifest,),
            execution_report_paths=(execution_report,),
            timestamp_binding_paths=(binding, binding),
            repo_root=tmp_path,
            protocol_path=protocol,
            registry_path=registry,
        )


def test_timestamp_binding_recomputes_response_identity(tmp_path: Path) -> None:
    manifest, protocol, execution_report = _sealed_episode(tmp_path)
    binding = _timestamp_binding(tmp_path, manifest)
    binding_payload = json.loads(binding.read_text(encoding="utf-8"))
    response = tmp_path / binding_payload["timestamp_response_artifact"]["path"]
    response.write_bytes(response.read_bytes() + b"tamper")
    registry = _copy_registry(tmp_path)

    with pytest.raises(ValueError, match="artifact_identity_mismatch"):
        trusted.compile_trusted_execution_ledger(
            (manifest,),
            execution_report_paths=(execution_report,),
            timestamp_binding_paths=(binding,),
            repo_root=tmp_path,
            protocol_path=protocol,
            registry_path=registry,
        )


def _timestamp_binding(root: Path, manifest: Path) -> Path:
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    episode_id = manifest_payload["episode_id"]
    response = root / "episode-001.tsr"
    response.write_bytes(b"synthetic test response; cryptography is mocked in this test")
    manifest_body = manifest.read_bytes()
    binding = root / "episode-001-timestamp-binding.json"
    binding.write_text(
        json.dumps(
            {
                "schema": trusted.BINDING_SCHEMA,
                "episode_id": episode_id,
                "authority_id": "fixture-production-tsa",
                "manifest_artifact": {
                    "path": manifest.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(manifest_body).hexdigest(),
                    "size_bytes": len(manifest_body),
                },
                "timestamp_response_artifact": _artifact(root, response),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return binding


def _copy_registry(root: Path) -> Path:
    path = root / "registry.json"
    path.write_bytes(verify.REGISTRY_PATH.read_bytes())
    return path


def _install_ready_registry_and_verifier(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    wrong_receipt_hash: bool = False,
) -> None:
    registry_artifact = {
        "path": "registry.json",
        "sha256": "a" * 64,
        "size_bytes": 100,
    }

    def assess_registry(*, registry_path: Path, repo_root: Path):
        assert registry_path == root / "registry.json"
        assert repo_root == root
        return {
            "schema": verify.ASSESSMENT_SCHEMA,
            "status": "registered_rfc3161_timestamp_authority_ready",
            "registry_artifact": registry_artifact,
            "registered_authority_count": 1,
            "trusted_external_timestamp_verification_ready": True,
            "gates": {
                "frozen_registry_identity_verified": True,
                "at_least_one_authority_registered": True,
                "every_registered_authority_admitted_not_test_only": True,
            },
        }

    def verify_receipt(
        *,
        receipt_path: Path,
        timestamp_response_path: Path,
        authority_id: str,
        forecast_issue_time: datetime,
        registry_path: Path,
        repo_root: Path,
        verified_at: datetime,
    ):
        del forecast_issue_time
        assert authority_id == "fixture-production-tsa"
        assert registry_path == root / "registry.json"
        assert repo_root == root
        receipt_artifact = _artifact(root, receipt_path)
        if wrong_receipt_hash:
            receipt_artifact["sha256"] = "f" * 64
        return {
            "schema": verify.ENVELOPE_SCHEMA,
            "status": "source_receipt_rfc3161_timestamp_verified",
            "verified_at": verified_at.isoformat(),
            "authority_id": authority_id,
            "registry_artifact": registry_artifact,
            "source_receipt_artifact": receipt_artifact,
            "timestamp_response_artifact": _artifact(root, timestamp_response_path),
            "timestamp": {
                "token_time": "2026-07-31T23:59:00+00:00",
                "policy_oid": "1.2.3.4.1",
                "serial_number": "0x01",
            },
            "verification": {
                "signature_and_chain_verified": True,
                "exact_receipt_message_imprint_verified": True,
                "tsa_extended_key_usage_timestamping_verified": True,
                "tsa_certificate_valid_at_token_time": True,
                "policy_oid_allowlisted": True,
                "registered_authority_identity_verified": True,
                "token_time_not_before_receipt_issued_at": True,
                "token_time_not_after_forecast_issue_time": True,
            },
            "claim_boundary": {
                "trusted_external_timestamp_verified": True,
                "source_receipt_existence_no_later_than_token_time": True,
                "prospective_manifest_acquired": False,
                "outcomes_acquired": False,
                "innovation_fitted": False,
            },
        }

    monkeypatch.setattr(
        trusted.timestamp_verifier,
        "assess_timestamp_authority_registry",
        assess_registry,
    )
    monkeypatch.setattr(
        trusted.timestamp_verifier,
        "verify_receipt_timestamp",
        verify_receipt,
    )


def _artifact(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }
