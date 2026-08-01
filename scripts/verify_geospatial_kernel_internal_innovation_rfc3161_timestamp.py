#!/usr/bin/env python3
"""Verify RFC 3161 time evidence for one source-availability receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_timestamp_authority_registry.json"
)
REGISTRY_SCHEMA = "gwm.geospatial_kernel.timestamp_authority_registry.v1"
EXPECTED_REGISTRY_FILE_SHA256 = (
    "1cd300deb5c8d981bda874304d946f311555fae4ef1f76288911658e8412be3c"
)
EXPECTED_REGISTRY_SEAL_SHA256 = (
    "92d192e89e6e3390a3d8ac5e7d869230b389e767ba6090af56d5e63f8d494a1c"
)
RECEIPT_SCHEMA = "gwm.geospatial_kernel.input_availability_receipts.v1"
ENVELOPE_SCHEMA = "gwm.geospatial_kernel.rfc3161_receipt_timestamp_envelope.v1"
ASSESSMENT_SCHEMA = "gwm.geospatial_kernel.timestamp_authority_readiness.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--timestamp-response", type=Path)
    parser.add_argument("--authority-id")
    parser.add_argument("--forecast-issue-time")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assess-registry-only", action="store_true")
    return parser.parse_args()


def assess_timestamp_authority_registry(
    *,
    registry_path: Path = REGISTRY_PATH,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    registry, artifact = _load_frozen_registry(registry_path, repo_root=repo_root)
    authorities = registry["registered_authorities"]
    ready = bool(authorities) and all(
        isinstance(value, dict)
        and value.get("status") == "admitted_before_first_real_receipt"
        and value.get("test_only") is False
        for value in authorities.values()
    )
    return {
        "schema": ASSESSMENT_SCHEMA,
        "generated_at": _now().isoformat(),
        "status": (
            "registered_rfc3161_timestamp_authority_ready"
            if ready
            else "blocked_no_registered_rfc3161_timestamp_authority"
        ),
        "registry_artifact": artifact,
        "registered_authority_count": len(authorities),
        "trusted_external_timestamp_verification_ready": ready,
        "gates": {
            "frozen_registry_identity_verified": True,
            "at_least_one_authority_registered": bool(authorities),
            "every_registered_authority_admitted_not_test_only": ready,
        },
        "execution_boundary": {
            "network_requests_performed": False,
            "timestamp_response_opened": False,
            "source_receipt_opened": False,
            "outcome_artifacts_opened": False,
            "physical_rollout_executed": False,
            "innovation_fit_executed": False,
        },
        "claim_boundary": {
            "trusted_external_timestamp_verified": False,
            "real_timestamp_token_acquired": False,
            "prospective_manifest_acquired": False,
            "geospatial_kernel_validated": False,
        },
    }


def verify_receipt_timestamp(
    *,
    receipt_path: Path,
    timestamp_response_path: Path,
    authority_id: str,
    forecast_issue_time: datetime,
    registry_path: Path = REGISTRY_PATH,
    repo_root: Path = REPO_ROOT,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    """Verify a token only against a pre-registered production authority."""

    root = Path(repo_root).resolve()
    registry, registry_artifact = _load_frozen_registry(
        registry_path,
        repo_root=root,
    )
    authority = registry["registered_authorities"].get(authority_id)
    if not isinstance(authority, dict):
        raise ValueError("internal_innovation_timestamp_authority_not_registered")
    if (
        authority.get("status") != "admitted_before_first_real_receipt"
        or authority.get("test_only") is not False
    ):
        raise ValueError("internal_innovation_timestamp_authority_not_admitted")
    issue_time = _aware_datetime(forecast_issue_time, "forecast_issue_time")
    verification_time = _aware_datetime(
        verified_at if verified_at is not None else _now(),
        "verified_at",
    )
    receipt = _inside_root(root, receipt_path)
    response = _inside_root(root, timestamp_response_path)
    receipt_body = receipt.read_bytes()
    receipt_payload = _strict_json_object(receipt_body)
    if receipt_payload.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("internal_innovation_timestamp_receipt_schema_invalid")
    receipt_issued_at = _time_text(receipt_payload.get("issued_at"), "receipt_issued_at")
    result = _verify_registered_token(
        root=root,
        receipt_path=receipt,
        timestamp_response_path=response,
        authority_id=authority_id,
        authority=authority,
    )
    token_time = result["token_time"]
    if (
        token_time < receipt_issued_at
        or token_time > issue_time
        or verification_time < token_time
    ):
        raise ValueError("internal_innovation_timestamp_temporal_ordering_invalid")
    return {
        "schema": ENVELOPE_SCHEMA,
        "status": "source_receipt_rfc3161_timestamp_verified",
        "verified_at": verification_time.isoformat(),
        "authority_id": authority_id,
        "registry_artifact": registry_artifact,
        "source_receipt_artifact": _artifact(root, receipt),
        "timestamp_response_artifact": _artifact(root, response),
        "tsa_certificate_artifact": result["tsa_certificate_artifact"],
        "ca_bundle_artifact": result["ca_bundle_artifact"],
        "timestamp": {
            "standard": "RFC3161",
            "token_time": token_time.isoformat(),
            "forecast_issue_time": issue_time.isoformat(),
            "receipt_issued_at": receipt_issued_at.isoformat(),
            "policy_oid": result["policy_oid"],
            "serial_number": result["serial_number"],
            "message_imprint_algorithm": "sha256",
            "message_imprint_sha256": hashlib.sha256(receipt_body).hexdigest(),
        },
        "verification": {
            "openssl_path": result["openssl_path"],
            "openssl_version": result["openssl_version"],
            "signature_and_chain_verified": True,
            "exact_receipt_message_imprint_verified": True,
            "tsa_extended_key_usage_timestamping_verified": True,
            "tsa_certificate_valid_at_token_time": True,
            "policy_oid_allowlisted": True,
            "registered_authority_identity_verified": True,
            "token_time_not_before_receipt_issued_at": True,
            "token_time_not_after_forecast_issue_time": True,
        },
        "data_isolation": {
            "network_requests_performed": False,
            "outcome_artifacts_opened": False,
            "outcome_values_loaded": False,
            "physical_rollout_executed": False,
            "innovation_fit_executed": False,
        },
        "claim_boundary": {
            "trusted_external_timestamp_verified": True,
            "source_receipt_contents_endorsed_by_tsa": False,
            "source_receipt_existence_no_later_than_token_time": True,
            "prospective_manifest_acquired": False,
            "physical_prediction_executed": False,
            "outcomes_acquired": False,
            "innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _verify_registered_token(
    *,
    root: Path,
    receipt_path: Path,
    timestamp_response_path: Path,
    authority_id: str,
    authority: dict[str, Any],
) -> dict[str, Any]:
    if set(authority) != {
        "status",
        "test_only",
        "service_name",
        "service_endpoint",
        "accepted_policy_oids",
        "tsa_certificate",
        "ca_bundle",
        "revocation_strategy",
    }:
        raise ValueError("internal_innovation_timestamp_authority_contract_invalid")
    if (
        not _nonempty_string(authority_id)
        or not _nonempty_string(authority.get("service_name"))
        or not _nonempty_string(authority.get("service_endpoint"))
        or not _nonempty_string(authority.get("revocation_strategy"))
    ):
        raise ValueError("internal_innovation_timestamp_authority_contract_invalid")
    policies = authority.get("accepted_policy_oids")
    if not isinstance(policies, list) or not policies or not all(
        _valid_oid(value) for value in policies
    ):
        raise ValueError("internal_innovation_timestamp_authority_policy_invalid")
    tsa_path, tsa_artifact = _registered_artifact(
        root,
        authority.get("tsa_certificate"),
    )
    ca_path, ca_artifact = _registered_artifact(root, authority.get("ca_bundle"))
    certificate = _load_tsa_certificate(tsa_path)
    try:
        eku = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound as error:
        raise ValueError("internal_innovation_timestamp_tsa_eku_missing") from error
    if ExtendedKeyUsageOID.TIME_STAMPING not in eku:
        raise ValueError("internal_innovation_timestamp_tsa_eku_invalid")
    openssl_path = shutil.which("openssl")
    if openssl_path is None:
        raise RuntimeError("internal_innovation_timestamp_openssl_unavailable")
    version = _run_openssl([openssl_path, "version"]).strip()
    _run_openssl(
        [
            openssl_path,
            "ts",
            "-verify",
            "-data",
            str(receipt_path),
            "-in",
            str(timestamp_response_path),
            "-CAfile",
            str(ca_path),
            "-untrusted",
            str(tsa_path),
        ]
    )
    detail = _run_openssl(
        [
            openssl_path,
            "ts",
            "-reply",
            "-in",
            str(timestamp_response_path),
            "-text",
        ]
    )
    parsed = _parse_timestamp_reply(detail)
    if parsed["policy_oid"] not in policies:
        raise ValueError("internal_innovation_timestamp_policy_not_allowlisted")
    if not (
        certificate.not_valid_before_utc
        <= parsed["token_time"]
        <= certificate.not_valid_after_utc
    ):
        raise ValueError("internal_innovation_timestamp_certificate_time_invalid")
    return {
        **parsed,
        "openssl_path": openssl_path,
        "openssl_version": version,
        "tsa_certificate_artifact": tsa_artifact,
        "ca_bundle_artifact": ca_artifact,
    }


def _parse_timestamp_reply(value: str) -> dict[str, Any]:
    fields = {}
    for line in value.splitlines():
        stripped = line.strip()
        for label, key in (
            ("Status:", "status"),
            ("Policy OID:", "policy_oid"),
            ("Hash Algorithm:", "hash_algorithm"),
            ("Serial number:", "serial_number"),
            ("Time stamp:", "token_time"),
        ):
            if stripped.startswith(label):
                if key in fields:
                    raise ValueError("internal_innovation_timestamp_reply_field_duplicate")
                fields[key] = stripped[len(label) :].strip()
    if set(fields) != {
        "status",
        "policy_oid",
        "hash_algorithm",
        "serial_number",
        "token_time",
    }:
        raise ValueError("internal_innovation_timestamp_reply_fields_invalid")
    if not str(fields["status"]).lower().startswith("granted"):
        raise ValueError("internal_innovation_timestamp_reply_not_granted")
    if str(fields["hash_algorithm"]).lower() != "sha256":
        raise ValueError("internal_innovation_timestamp_hash_algorithm_invalid")
    try:
        token_time = parsedate_to_datetime(str(fields["token_time"]))
    except (TypeError, ValueError) as error:
        raise ValueError("internal_innovation_timestamp_token_time_invalid") from error
    if token_time.tzinfo is None or token_time.utcoffset() is None:
        raise ValueError("internal_innovation_timestamp_token_time_invalid")
    return {
        "policy_oid": fields["policy_oid"],
        "serial_number": fields["serial_number"],
        "token_time": token_time.astimezone(UTC),
    }


def _load_frozen_registry(
    path_value: Path,
    *,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, object]]:
    root = Path(repo_root).resolve()
    path = _inside_root(root, path_value)
    body = path.read_bytes()
    payload = _strict_json_object(body)
    seal = payload.get("registry_seal")
    without_seal = dict(payload)
    without_seal.pop("registry_seal", None)
    canonical = json.dumps(
        without_seal,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if (
        hashlib.sha256(body).hexdigest() != EXPECTED_REGISTRY_FILE_SHA256
        or payload.get("schema") != REGISTRY_SCHEMA
        or not isinstance(seal, dict)
        or seal.get("algorithm") != "sha256_canonical_json_without_registry_seal"
        or seal.get("sha256") != EXPECTED_REGISTRY_SEAL_SHA256
        or hashlib.sha256(canonical).hexdigest() != EXPECTED_REGISTRY_SEAL_SHA256
        or not isinstance(payload.get("registered_authorities"), dict)
    ):
        raise ValueError("internal_innovation_timestamp_registry_identity_invalid")
    return payload, _artifact(root, path)


def _registered_artifact(
    root: Path,
    descriptor: object,
) -> tuple[Path, dict[str, object]]:
    if not isinstance(descriptor, dict) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise ValueError("internal_innovation_timestamp_registered_artifact_invalid")
    path = _inside_root(root, Path(str(descriptor.get("path"))))
    artifact = _artifact(root, path)
    if artifact != descriptor:
        raise ValueError("internal_innovation_timestamp_registered_artifact_mismatch")
    return path, artifact


def _load_tsa_certificate(path: Path) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except ValueError as error:
        raise ValueError("internal_innovation_timestamp_tsa_certificate_invalid") from error


def _run_openssl(command: list[str]) -> str:
    environment = dict(os.environ)
    environment.pop("OPENSSL_CONF", None)
    environment.pop("OPENSSL_MODULES", None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    if completed.returncode != 0:
        raise ValueError("internal_innovation_timestamp_openssl_verification_failed")
    return completed.stdout + completed.stderr


def _artifact(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _inside_root(root: Path, path_value: Path) -> Path:
    candidate = path_value if path_value.is_absolute() else root / path_value
    if candidate.is_symlink():
        raise ValueError("internal_innovation_timestamp_symlink_forbidden")
    path = candidate.resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("internal_innovation_timestamp_path_outside_repository") from error
    if not path.is_file():
        raise ValueError("internal_innovation_timestamp_artifact_missing")
    return path


def _strict_json_object(body: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("internal_innovation_timestamp_json_duplicate_key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"internal_innovation_timestamp_json_nonfinite:{value}")

    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("internal_innovation_timestamp_json_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("internal_innovation_timestamp_json_root_not_object")
    return payload


def _time_text(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"internal_innovation_timestamp_{name}_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"internal_innovation_timestamp_{name}_invalid") from error
    return _aware_datetime(parsed, name)


def _aware_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"internal_innovation_timestamp_{name}_invalid")
    return value


def _valid_oid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    if not (
        len(parts) >= 2
        and all(part.isdigit() and str(int(part)) == part for part in parts)
    ):
        return False
    values = [int(part) for part in parts]
    return values[0] <= 2 and (values[0] == 2 or values[1] <= 39)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _now() -> datetime:
    return datetime.now(UTC)


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError("internal_innovation_timestamp_output_conflict")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(body)
    except FileExistsError as error:
        raise FileExistsError("internal_innovation_timestamp_output_conflict") from error


def main() -> int:
    args = parse_args()
    if args.assess_registry_only:
        report = assess_timestamp_authority_registry(registry_path=args.registry)
    else:
        if (
            args.receipt is None
            or args.timestamp_response is None
            or args.authority_id is None
            or args.forecast_issue_time is None
        ):
            raise ValueError("internal_innovation_timestamp_verification_arguments_required")
        report = verify_receipt_timestamp(
            receipt_path=args.receipt,
            timestamp_response_path=args.timestamp_response,
            authority_id=args.authority_id,
            forecast_issue_time=_time_text(
                args.forecast_issue_time,
                "forecast_issue_time",
            ),
            registry_path=args.registry,
        )
    _write_once(args.output, report)
    print(args.output)
    print(f"status={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
