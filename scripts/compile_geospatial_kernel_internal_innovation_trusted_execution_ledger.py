#!/usr/bin/env python3
"""Add trusted RFC 3161 receipt gates to the frozen Manning execution ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts import (
        compile_geospatial_kernel_internal_innovation_execution_ledger as base_ledger,
    )
    from scripts import (
        verify_geospatial_kernel_internal_innovation_rfc3161_timestamp as timestamp_verifier,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import compile_geospatial_kernel_internal_innovation_execution_ledger as base_ledger
    import verify_geospatial_kernel_internal_innovation_rfc3161_timestamp as timestamp_verifier

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "gwm.geospatial_kernel.trusted_internal_innovation_execution_ledger.v1"
BINDING_SCHEMA = "gwm.geospatial_kernel.prospective_receipt_timestamp_binding.v1"
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_trusted_execution_ledger.json"
)
_BINDING_FIELDS = {
    "schema",
    "episode_id",
    "authority_id",
    "manifest_artifact",
    "timestamp_response_artifact",
}
_ARTIFACT_FIELDS = {"path", "sha256", "size_bytes"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--execution-report", type=Path, action="append", default=[])
    parser.add_argument("--timestamp-binding", type=Path, action="append", default=[])
    parser.add_argument("--protocol", type=Path, default=base_ledger.PROTOCOL_PATH)
    parser.add_argument("--registry", type=Path, default=timestamp_verifier.REGISTRY_PATH)
    parser.add_argument(
        "--generated-at",
        help="Aware ISO-8601 compilation time; defaults to current UTC time.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_trusted_execution_ledger(
    manifest_paths: Sequence[Path],
    *,
    execution_report_paths: Sequence[Path] = (),
    timestamp_binding_paths: Sequence[Path] = (),
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = base_ledger.PROTOCOL_PATH,
    registry_path: Path = timestamp_verifier.REGISTRY_PATH,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Recompute both physical execution and external timestamp evidence."""

    root = Path(repo_root).resolve()
    compilation_time = _aware_datetime(
        generated_at if generated_at is not None else datetime.now(UTC),
        "generated_at",
    ).astimezone(UTC)
    base = base_ledger.compile_internal_innovation_execution_ledger(
        tuple(manifest_paths),
        execution_report_paths=tuple(execution_report_paths),
        repo_root=root,
        protocol_path=protocol_path,
    )
    registry = timestamp_verifier.assess_timestamp_authority_registry(
        registry_path=registry_path,
        repo_root=root,
    )
    bindings = [_load_binding(root, Path(path)) for path in timestamp_binding_paths]
    _reject_duplicate_bindings(bindings)

    manifests = [_load_manifest(root, Path(path)) for path in manifest_paths]
    manifest_ids = [record["episode_id"] for record in manifests]
    binding_ids = [record["episode_id"] for record in bindings]
    extra_binding_ids = sorted(set(binding_ids) - set(manifest_ids))
    if extra_binding_ids:
        raise ValueError(
            "internal_innovation_trusted_ledger_unbound_timestamp_binding"
        )
    bindings_by_episode = {record["episode_id"]: record for record in bindings}
    base_entries = {
        entry["episode_id"]: entry for entry in base["reconciliation"]["entries"]
    }

    entries = []
    for manifest in manifests:
        entry = _timestamp_entry(
            root=root,
            manifest=manifest,
            base_entry=base_entries.get(manifest["episode_id"], {}),
            binding=bindings_by_episode.get(manifest["episode_id"]),
            registry=registry,
            registry_path=registry_path,
            verified_at=compilation_time,
        )
        entries.append(entry)
    entries.sort(
        key=lambda value: (
            str(value.get("system_id") or ""),
            str(value.get("forecast_issue_time") or ""),
            str(value.get("episode_id") or ""),
        )
    )

    binding_inventory_complete = (
        bool(manifests)
        and len(bindings) == len(manifests)
        and set(binding_ids) == set(manifest_ids)
    )
    all_timestamped = bool(entries) and all(
        entry["trusted_external_timestamp_verified"] is True for entry in entries
    )
    gates = {
        "base_execution_ledger_integrity_passed": (
            base["ledger_integrity_passed"] is True
        ),
        "base_diagnostic_fit_coverage_ready": base["diagnostic_fit_ready"] is True,
        "frozen_timestamp_authority_registry_identity_verified": registry["gates"][
            "frozen_registry_identity_verified"
        ]
        is True,
        "registered_production_timestamp_authority_available": registry[
            "trusted_external_timestamp_verification_ready"
        ]
        is True,
        "complete_one_to_one_timestamp_binding_inventory": binding_inventory_complete,
        "every_manifest_receipt_has_trusted_external_timestamp": all_timestamped,
        "outcome_values_never_loaded": True,
        "innovation_fit_never_executed": True,
    }
    diagnostic_fit_ready = all(gates.values())
    invalid_timestamp_count = sum(
        entry["status"] == "invalid_external_timestamp" for entry in entries
    )
    missing_timestamp_count = sum(
        entry["status"] == "missing_timestamp_binding" for entry in entries
    )
    if not gates["base_execution_ledger_integrity_passed"]:
        status = "blocked_base_execution_ledger_integrity_failure"
    elif not gates["registered_production_timestamp_authority_available"]:
        status = "blocked_no_registered_rfc3161_timestamp_authority"
    elif not manifests:
        status = "awaiting_prospective_episode_manifests"
    elif missing_timestamp_count:
        status = "awaiting_complete_timestamp_binding_inventory"
    elif invalid_timestamp_count or not all_timestamped:
        status = "blocked_invalid_external_receipt_timestamp"
    elif diagnostic_fit_ready:
        status = "diagnostic_fit_ready_with_trusted_external_timestamps"
    else:
        status = "accumulating_timestamped_cross_system_episodes"

    return {
        "schema": SCHEMA,
        "generated_at": compilation_time.isoformat(),
        "status": status,
        "base_execution_ledger": _base_summary(base),
        "timestamp_authority_registry": _registry_summary(registry),
        "submitted_manifest_count": len(manifests),
        "submitted_execution_report_count": len(execution_report_paths),
        "submitted_timestamp_binding_count": len(bindings),
        "timestamp_reconciliation": {
            "trusted_timestamp_count": sum(
                entry["trusted_external_timestamp_verified"] is True
                for entry in entries
            ),
            "missing_timestamp_binding_count": missing_timestamp_count,
            "invalid_external_timestamp_count": invalid_timestamp_count,
            "entries": entries,
        },
        "diagnostic_fit_gates": gates,
        "diagnostic_fit_ready": diagnostic_fit_ready,
        "ledger_integrity_passed": (
            gates["base_execution_ledger_integrity_passed"]
            and gates["frozen_timestamp_authority_registry_identity_verified"]
        ),
        "data_isolation": {
            "manifest_and_execution_artifacts_recomputed": True,
            "timestamp_binding_artifacts_recomputed": bool(bindings),
            "timestamp_response_artifacts_opened_for_identity_recomputation": any(
                entry["timestamp_response_artifact"] is not None for entry in entries
            ),
            "timestamp_responses_cryptographically_verified": any(
                entry["trusted_external_timestamp_verified"] is True
                for entry in entries
            ),
            "network_requests_performed": False,
            "outcome_argument_accepted": False,
            "outcome_artifacts_opened": False,
            "outcome_values_loaded": False,
            "innovation_fit_executed": False,
        },
        "claim_boundary": {
            "base_execution_coverage_sufficient": base["diagnostic_fit_ready"],
            "all_manifest_receipts_externally_timestamped": all_timestamped,
            "diagnostic_fit_authorized": diagnostic_fit_ready,
            "outcomes_acquired": False,
            "innovation_fitted": False,
            "candidate_outperformed_raw_physical": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _timestamp_entry(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    base_entry: Mapping[str, Any],
    binding: Mapping[str, Any] | None,
    registry: Mapping[str, Any],
    registry_path: Path,
    verified_at: datetime,
) -> dict[str, Any]:
    common = {
        "episode_id": manifest["episode_id"],
        "system_id": manifest["system_id"],
        "forecast_issue_time": manifest["forecast_issue_time_text"],
        "manifest_artifact": manifest["artifact"],
        "source_receipt_artifact": manifest["source_receipt_artifact"],
        "base_reconciliation_status": base_entry.get("reconciliation_status"),
    }
    if binding is None:
        return {
            **common,
            "status": "missing_timestamp_binding",
            "authority_id": None,
            "timestamp_binding_artifact": None,
            "timestamp_response_artifact": None,
            "timestamp_verification": None,
            "verification_error": None,
            "trusted_external_timestamp_verified": False,
        }
    if (
        binding["manifest_artifact"] != manifest["artifact"]
        or binding["episode_id"] != manifest["episode_id"]
    ):
        return _invalid_timestamp_entry(
            common,
            binding,
            "internal_innovation_trusted_ledger_manifest_binding_mismatch",
        )
    if registry["trusted_external_timestamp_verification_ready"] is not True:
        return _invalid_timestamp_entry(
            common,
            binding,
            "internal_innovation_trusted_ledger_timestamp_registry_not_ready",
        )
    if base_entry.get("manifest_preflight_ready") is not True:
        return _invalid_timestamp_entry(
            common,
            binding,
            "internal_innovation_trusted_ledger_manifest_preflight_not_ready",
        )
    try:
        envelope = timestamp_verifier.verify_receipt_timestamp(
            receipt_path=manifest["source_receipt_path"],
            timestamp_response_path=binding["timestamp_response_path"],
            authority_id=binding["authority_id"],
            forecast_issue_time=manifest["forecast_issue_time"],
            registry_path=registry_path,
            repo_root=root,
            verified_at=verified_at,
        )
        _validate_envelope(
            envelope,
            manifest=manifest,
            binding=binding,
            registry=registry,
        )
    except (OSError, RuntimeError, ValueError) as error:
        return _invalid_timestamp_entry(common, binding, str(error))
    return {
        **common,
        "status": "trusted_external_timestamp_verified",
        "authority_id": binding["authority_id"],
        "timestamp_binding_artifact": binding["binding_artifact"],
        "timestamp_response_artifact": binding["timestamp_response_artifact"],
        "timestamp_verification": {
            "schema": envelope["schema"],
            "verified_at": envelope["verified_at"],
            "token_time": envelope["timestamp"]["token_time"],
            "policy_oid": envelope["timestamp"]["policy_oid"],
            "serial_number": envelope["timestamp"]["serial_number"],
            "signature_and_chain_verified": True,
            "exact_receipt_message_imprint_verified": True,
            "registered_authority_identity_verified": True,
        },
        "verification_error": None,
        "trusted_external_timestamp_verified": True,
    }


def _invalid_timestamp_entry(
    common: Mapping[str, Any],
    binding: Mapping[str, Any],
    error: str,
) -> dict[str, Any]:
    return {
        **common,
        "status": "invalid_external_timestamp",
        "authority_id": binding["authority_id"],
        "timestamp_binding_artifact": binding["binding_artifact"],
        "timestamp_response_artifact": binding["timestamp_response_artifact"],
        "timestamp_verification": None,
        "verification_error": error,
        "trusted_external_timestamp_verified": False,
    }


def _load_binding(root: Path, path_value: Path) -> dict[str, Any]:
    path = _inside_root(root, path_value)
    body = path.read_bytes()
    payload = _strict_json_object(body)
    if (
        set(payload) != _BINDING_FIELDS
        or payload.get("schema") != BINDING_SCHEMA
        or not _nonempty_string(payload.get("episode_id"))
        or not _nonempty_string(payload.get("authority_id"))
    ):
        raise ValueError("internal_innovation_trusted_ledger_binding_contract_invalid")
    manifest_artifact, _ = _bound_artifact(root, payload.get("manifest_artifact"))
    timestamp_response_artifact, timestamp_response_path = _bound_artifact(
        root,
        payload.get("timestamp_response_artifact"),
    )
    return {
        "episode_id": payload["episode_id"],
        "authority_id": payload["authority_id"],
        "manifest_artifact": manifest_artifact,
        "timestamp_response_artifact": timestamp_response_artifact,
        "timestamp_response_path": timestamp_response_path,
        "binding_artifact": _artifact(root, path, body),
    }


def _load_manifest(root: Path, path_value: Path) -> dict[str, Any]:
    path = _inside_root(root, path_value)
    body = path.read_bytes()
    payload = _strict_json_object(body)
    episode_id = payload.get("episode_id")
    system_id = payload.get("system_id")
    issue_time = _time_text(payload.get("forecast_issue_time"), "forecast_issue_time")
    artifacts = payload.get("artifacts")
    receipt_descriptor = (
        artifacts.get("input_availability_receipts")
        if isinstance(artifacts, dict)
        else None
    )
    if not _nonempty_string(episode_id) or not _nonempty_string(system_id):
        raise ValueError("internal_innovation_trusted_ledger_manifest_identity_invalid")
    receipt_artifact, receipt_path = _bound_manifest_receipt(root, receipt_descriptor)
    return {
        "episode_id": episode_id,
        "system_id": system_id,
        "forecast_issue_time": issue_time,
        "forecast_issue_time_text": issue_time.isoformat(),
        "artifact": _artifact(root, path, body),
        "source_receipt_artifact": receipt_artifact,
        "source_receipt_path": receipt_path,
    }


def _bound_manifest_receipt(
    root: Path,
    descriptor: object,
) -> tuple[dict[str, object], Path]:
    if not isinstance(descriptor, dict) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
        "schema",
        "available_at",
        "provenance_id",
    }:
        raise ValueError(
            "internal_innovation_trusted_ledger_receipt_descriptor_invalid"
        )
    artifact, path = _bound_artifact(
        root,
        {name: descriptor[name] for name in _ARTIFACT_FIELDS},
    )
    if descriptor.get("schema") != timestamp_verifier.RECEIPT_SCHEMA:
        raise ValueError("internal_innovation_trusted_ledger_receipt_schema_invalid")
    return artifact, path


def _bound_artifact(
    root: Path,
    descriptor: object,
) -> tuple[dict[str, object], Path]:
    if not isinstance(descriptor, dict) or set(descriptor) != _ARTIFACT_FIELDS:
        raise ValueError("internal_innovation_trusted_ledger_artifact_descriptor_invalid")
    path = _inside_root(root, Path(str(descriptor.get("path"))))
    body = path.read_bytes()
    artifact = _artifact(root, path, body)
    if artifact != descriptor:
        raise ValueError("internal_innovation_trusted_ledger_artifact_identity_mismatch")
    return artifact, path


def _validate_envelope(
    envelope: object,
    *,
    manifest: Mapping[str, Any],
    binding: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> None:
    if not isinstance(envelope, dict):
        raise ValueError("internal_innovation_trusted_ledger_envelope_invalid")
    verification = envelope.get("verification")
    claims = envelope.get("claim_boundary")
    if (
        envelope.get("schema") != timestamp_verifier.ENVELOPE_SCHEMA
        or envelope.get("status") != "source_receipt_rfc3161_timestamp_verified"
        or envelope.get("authority_id") != binding["authority_id"]
        or envelope.get("registry_artifact") != registry["registry_artifact"]
        or envelope.get("source_receipt_artifact")
        != manifest["source_receipt_artifact"]
        or envelope.get("timestamp_response_artifact")
        != binding["timestamp_response_artifact"]
        or not isinstance(verification, dict)
        or any(
            verification.get(name) is not True
            for name in (
                "signature_and_chain_verified",
                "exact_receipt_message_imprint_verified",
                "tsa_extended_key_usage_timestamping_verified",
                "tsa_certificate_valid_at_token_time",
                "policy_oid_allowlisted",
                "registered_authority_identity_verified",
                "token_time_not_before_receipt_issued_at",
                "token_time_not_after_forecast_issue_time",
            )
        )
        or not isinstance(claims, dict)
        or claims.get("trusted_external_timestamp_verified") is not True
        or claims.get("source_receipt_existence_no_later_than_token_time") is not True
        or claims.get("prospective_manifest_acquired") is not False
        or claims.get("outcomes_acquired") is not False
        or claims.get("innovation_fitted") is not False
    ):
        raise ValueError("internal_innovation_trusted_ledger_envelope_invalid")


def _reject_duplicate_bindings(records: Sequence[Mapping[str, Any]]) -> None:
    episode_ids = [record["episode_id"] for record in records]
    response_hashes = [
        record["timestamp_response_artifact"]["sha256"] for record in records
    ]
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("internal_innovation_trusted_ledger_duplicate_binding_episode")
    if len(response_hashes) != len(set(response_hashes)):
        raise ValueError("internal_innovation_trusted_ledger_reused_timestamp_response")


def _base_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": report["schema"],
        "status": report["status"],
        "protocol": report["protocol"],
        "submitted_manifest_count": report["submitted_manifest_count"],
        "submitted_execution_report_count": report[
            "submitted_execution_report_count"
        ],
        "reconciliation": report["reconciliation"],
        "coverage_by_system": report["coverage_by_system"],
        "diagnostic_fit_gates": report["diagnostic_fit_gates"],
        "diagnostic_fit_ready": report["diagnostic_fit_ready"],
        "ledger_integrity_passed": report["ledger_integrity_passed"],
    }


def _registry_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": report["schema"],
        "status": report["status"],
        "registry_artifact": report["registry_artifact"],
        "registered_authority_count": report["registered_authority_count"],
        "trusted_external_timestamp_verification_ready": report[
            "trusted_external_timestamp_verification_ready"
        ],
        "gates": report["gates"],
    }


def _artifact(root: Path, path: Path, body: bytes) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _inside_root(root: Path, path_value: Path) -> Path:
    candidate = path_value if path_value.is_absolute() else root / path_value
    if candidate.is_symlink():
        raise ValueError("internal_innovation_trusted_ledger_symlink_forbidden")
    path = candidate.resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("internal_innovation_trusted_ledger_path_outside_repository") from error
    if not path.is_file():
        raise ValueError("internal_innovation_trusted_ledger_artifact_missing")
    return path


def _strict_json_object(body: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("internal_innovation_trusted_ledger_json_duplicate_key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"internal_innovation_trusted_ledger_json_nonfinite:{value}")

    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("internal_innovation_trusted_ledger_json_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("internal_innovation_trusted_ledger_json_root_not_object")
    return payload


def _time_text(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"internal_innovation_trusted_ledger_{name}_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"internal_innovation_trusted_ledger_{name}_invalid"
        ) from error
    return _aware_datetime(parsed, name).astimezone(UTC)


def _aware_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"internal_innovation_trusted_ledger_{name}_invalid")
    return value


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _write_once(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError("internal_innovation_trusted_ledger_output_conflict")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(body)
    except FileExistsError as error:
        raise FileExistsError(
            "internal_innovation_trusted_ledger_output_conflict"
        ) from error


def main() -> int:
    args = parse_args()
    compilation_time = None
    if args.generated_at is not None:
        compilation_time = _time_text(args.generated_at, "generated_at")
    report = compile_trusted_execution_ledger(
        tuple(args.manifest),
        execution_report_paths=tuple(args.execution_report),
        timestamp_binding_paths=tuple(args.timestamp_binding),
        protocol_path=args.protocol,
        registry_path=args.registry,
        generated_at=compilation_time,
    )
    _write_once(args.output, report)
    print(args.output)
    print(f"status={report['status']}")
    print(f"diagnostic_fit_ready={report['diagnostic_fit_ready']}")
    return 0 if report["ledger_integrity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
