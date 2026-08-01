#!/usr/bin/env python3
"""Assess RFC 3161 authority dossiers without network access or registration."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

try:
    from scripts import (
        verify_geospatial_kernel_internal_innovation_rfc3161_timestamp as timestamp_verifier,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import verify_geospatial_kernel_internal_innovation_rfc3161_timestamp as timestamp_verifier

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_timestamp_authority_candidate_assessment.json"
)
DOSSIER_SCHEMA = "gwm.geospatial_kernel.timestamp_authority_candidate_dossier.v1"
ASSESSMENT_SCHEMA = "gwm.geospatial_kernel.timestamp_authority_candidate_assessment.v1"
CANDIDATE_FIELDS = {
    "schema",
    "candidate_id",
    "test_only",
    "service_identity",
    "accepted_policy_oids",
    "prospective_campaign",
    "artifacts",
    "revocation_strategy",
    "canary",
}
ARTIFACT_FIELDS = {
    "legal_identity_evidence",
    "service_policy",
    "certification_practice_statement",
    "revocation_policy",
    "tsa_certificate",
    "ca_bundle",
    "canary_receipt",
    "canary_timestamp_response",
}
SERVICE_IDENTITY_FIELDS = {
    "legal_entity_name",
    "service_name",
    "service_endpoint",
    "independent_of_gwm_runtime",
}
CAMPAIGN_FIELDS = {"starts_at", "ends_at"}
REVOCATION_FIELDS = {
    "mechanisms",
    "check_before_registration",
    "check_before_each_token_verification",
    "failure_mode",
    "maximum_status_age_seconds",
}
CANARY_FIELDS = {
    "acquisition_mode",
    "acquired_at",
    "external_service_response",
    "test_only",
}
GATE_NAMES = (
    "dossier_contract_valid",
    "candidate_identity_valid",
    "service_identity_documented",
    "https_endpoint_valid",
    "independent_of_gwm_runtime",
    "policy_oid_allowlist_valid",
    "prospective_campaign_interval_valid",
    "all_declared_artifacts_hash_bound",
    "legal_identity_evidence_hash_bound",
    "service_policy_hash_bound",
    "certification_practice_statement_hash_bound",
    "revocation_policy_hash_bound",
    "revocation_strategy_documented",
    "production_candidate_not_test_only",
    "canary_declared_external_not_test_only",
    "tsa_leaf_certificate_parsed",
    "tsa_leaf_not_ca",
    "tsa_leaf_not_self_signed",
    "tsa_leaf_distinct_from_ca_bundle",
    "timestamping_eku_present",
    "certificate_valid_at_assessment",
    "certificate_covers_prospective_campaign",
    "canary_signature_and_chain_verified",
    "canary_exact_receipt_imprint_verified",
    "canary_policy_oid_allowlisted",
    "canary_acquisition_time_consistent",
    "candidate_id_unique_within_inventory",
)
_CANDIDATE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,127}\Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-dossier",
        action="append",
        default=[],
        type=Path,
        help="Hash-bound candidate dossier; may be supplied more than once.",
    )
    parser.add_argument(
        "--assessed-at",
        help="Aware ISO-8601 assessment time; defaults to the current UTC time.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def assess_timestamp_authority_candidates(
    candidate_dossiers: list[Path] | tuple[Path, ...],
    *,
    repo_root: Path = REPO_ROOT,
    assessed_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a fail-closed assessment; never register or contact a candidate."""

    root = Path(repo_root).resolve()
    assessment_time = _aware_datetime(
        assessed_at if assessed_at is not None else datetime.now(UTC),
        "assessed_at",
    ).astimezone(UTC)
    candidates = [
        _assess_candidate(root, Path(path), assessment_time)
        for path in candidate_dossiers
    ]
    candidate_id_counts = Counter(row["candidate_id"] for row in candidates)
    for row in candidates:
        unique = candidate_id_counts[row["candidate_id"]] == 1
        row["gates"]["candidate_id_unique_within_inventory"] = unique
        _finalize_candidate(row)

    ready = [row for row in candidates if row["candidate_registration_ready"]]
    submitted_production = sum(
        row["declarations"].get("test_only") is False for row in candidates
    )
    if not candidates:
        status = "awaiting_timestamp_authority_candidate_dossier"
        blocker = "no_candidate_dossiers_submitted"
    elif not ready:
        status = "blocked_no_admissible_timestamp_authority_candidate"
        blocker = "no_candidate_passes_every_non_compensatory_gate"
    else:
        status = "timestamp_authority_candidate_ready_for_manual_registration"
        blocker = None
    return {
        "schema": ASSESSMENT_SCHEMA,
        "generated_at": assessment_time.isoformat(),
        "status": status,
        "blocker": blocker,
        "candidate_dossier_count": len(candidates),
        "submitted_production_candidate_count": submitted_production,
        "registration_ready_candidate_count": len(ready),
        "registration_ready_candidate_ids": [row["candidate_id"] for row in ready],
        "candidate_registration_ready": bool(ready),
        "candidates": candidates,
        "inventory_gates": {
            "candidate_dossier_submitted": bool(candidates),
            "candidate_ids_unique": all(count == 1 for count in candidate_id_counts.values()),
            "at_least_one_candidate_passes_every_non_compensatory_gate": bool(ready),
        },
        "execution_boundary": {
            "network_requests_performed": False,
            "timestamp_authority_contacted": False,
            "registry_opened_for_write": False,
            "registry_modified": False,
            "outcome_artifacts_opened": False,
            "outcome_values_loaded": False,
            "physical_rollout_executed": False,
            "innovation_fit_executed": False,
        },
        "claim_boundary": {
            "candidate_assessment_is_registration": False,
            "production_authority_registered": False,
            "real_prospective_receipt_timestamped": False,
            "trusted_external_timestamp_verified_for_prospective_episode": False,
            "prospective_manifest_acquired": False,
            "innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }


def _assess_candidate(
    root: Path,
    dossier_path: Path,
    assessed_at: datetime,
) -> dict[str, Any]:
    gates = {name: False for name in GATE_NAMES}
    gates["candidate_id_unique_within_inventory"] = True
    errors: list[str] = []
    try:
        path = timestamp_verifier._inside_root(root, dossier_path)
        dossier_artifact = timestamp_verifier._artifact(root, path)
        payload = timestamp_verifier._strict_json_object(path.read_bytes())
    except (OSError, ValueError) as error:
        return _invalid_candidate(
            candidate_id=f"unparsed:{dossier_path.name}",
            dossier_path=str(dossier_path),
            gates=gates,
            error=_error_code(error),
        )

    candidate_id_value = payload.get("candidate_id")
    candidate_id = (
        candidate_id_value
        if isinstance(candidate_id_value, str) and candidate_id_value
        else f"unparsed:{path.name}"
    )
    gates["dossier_contract_valid"] = (
        set(payload) == CANDIDATE_FIELDS and payload.get("schema") == DOSSIER_SCHEMA
    )
    gates["candidate_identity_valid"] = bool(_CANDIDATE_ID.fullmatch(candidate_id))

    identity = payload.get("service_identity")
    identity_shape_valid = isinstance(identity, dict) and set(identity) == SERVICE_IDENTITY_FIELDS
    identity = identity if isinstance(identity, dict) else {}
    endpoint = identity.get("service_endpoint")
    gates["service_identity_documented"] = identity_shape_valid and all(
        _nonempty_string(identity.get(key))
        for key in ("legal_entity_name", "service_name", "service_endpoint")
    )
    gates["https_endpoint_valid"] = _valid_https_endpoint(endpoint)
    gates["independent_of_gwm_runtime"] = (
        identity.get("independent_of_gwm_runtime") is True
    )

    policies = payload.get("accepted_policy_oids")
    gates["policy_oid_allowlist_valid"] = (
        isinstance(policies, list)
        and bool(policies)
        and len(policies) == len(set(_hashable_strings(policies)))
        and all(timestamp_verifier._valid_oid(value) for value in policies)
    )

    campaign = payload.get("prospective_campaign")
    campaign_shape_valid = isinstance(campaign, dict) and set(campaign) == CAMPAIGN_FIELDS
    campaign = campaign if isinstance(campaign, dict) else {}
    campaign_start = _optional_time(campaign.get("starts_at"))
    campaign_end = _optional_time(campaign.get("ends_at"))
    gates["prospective_campaign_interval_valid"] = (
        campaign_shape_valid
        and campaign_start is not None
        and campaign_end is not None
        and campaign_start < campaign_end
    )

    artifacts = payload.get("artifacts")
    artifacts_shape_valid = isinstance(artifacts, dict) and set(artifacts) == ARTIFACT_FIELDS
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    artifact_paths: dict[str, Path] = {}
    verified_artifacts: dict[str, dict[str, object]] = {}
    for name in ARTIFACT_FIELDS:
        try:
            artifact_path, artifact = timestamp_verifier._registered_artifact(
                root,
                artifacts.get(name),
            )
        except (OSError, ValueError) as error:
            errors.append(f"{name}:{_error_code(error)}")
            continue
        artifact_paths[name] = artifact_path
        verified_artifacts[name] = artifact
    gates["all_declared_artifacts_hash_bound"] = (
        artifacts_shape_valid and set(verified_artifacts) == ARTIFACT_FIELDS
    )
    for artifact_name, gate_name in (
        ("legal_identity_evidence", "legal_identity_evidence_hash_bound"),
        ("service_policy", "service_policy_hash_bound"),
        (
            "certification_practice_statement",
            "certification_practice_statement_hash_bound",
        ),
        ("revocation_policy", "revocation_policy_hash_bound"),
    ):
        artifact = verified_artifacts.get(artifact_name)
        gates[gate_name] = isinstance(artifact, dict) and artifact.get("size_bytes", 0) > 0

    revocation = payload.get("revocation_strategy")
    gates["revocation_strategy_documented"] = _valid_revocation_strategy(revocation)
    gates["production_candidate_not_test_only"] = payload.get("test_only") is False

    canary = payload.get("canary")
    canary_shape_valid = isinstance(canary, dict) and set(canary) == CANARY_FIELDS
    canary = canary if isinstance(canary, dict) else {}
    canary_acquired_at = _optional_time(canary.get("acquired_at"))
    gates["canary_declared_external_not_test_only"] = (
        canary_shape_valid
        and canary.get("acquisition_mode") == "real_external_rfc3161_service"
        and canary.get("external_service_response") is True
        and canary.get("test_only") is False
        and canary_acquired_at is not None
    )

    certificate: x509.Certificate | None = None
    tsa_path = artifact_paths.get("tsa_certificate")
    if tsa_path is not None:
        try:
            certificate = timestamp_verifier._load_tsa_certificate(tsa_path)
            gates["tsa_leaf_certificate_parsed"] = True
        except (OSError, ValueError) as error:
            errors.append(f"tsa_certificate:{_error_code(error)}")
    if certificate is not None:
        try:
            basic_constraints = certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value
            gates["tsa_leaf_not_ca"] = basic_constraints.ca is False
        except x509.ExtensionNotFound:
            errors.append("tsa_certificate:basic_constraints_missing")
        gates["tsa_leaf_not_self_signed"] = certificate.subject != certificate.issuer
        try:
            eku = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            gates["timestamping_eku_present"] = ExtendedKeyUsageOID.TIME_STAMPING in eku
        except x509.ExtensionNotFound:
            errors.append("tsa_certificate:timestamping_eku_missing")
        gates["certificate_valid_at_assessment"] = (
            certificate.not_valid_before_utc <= assessed_at <= certificate.not_valid_after_utc
        )
        gates["certificate_covers_prospective_campaign"] = (
            campaign_start is not None
            and campaign_end is not None
            and certificate.not_valid_before_utc <= campaign_start
            and campaign_end <= certificate.not_valid_after_utc
        )
    tsa_artifact = verified_artifacts.get("tsa_certificate")
    ca_artifact = verified_artifacts.get("ca_bundle")
    gates["tsa_leaf_distinct_from_ca_bundle"] = (
        isinstance(tsa_artifact, dict)
        and isinstance(ca_artifact, dict)
        and tsa_artifact.get("sha256") != ca_artifact.get("sha256")
    )

    cryptographic_verification: dict[str, Any] | None = None
    crypto_inputs_ready = (
        all(
            name in artifact_paths
            for name in (
                "tsa_certificate",
                "ca_bundle",
                "canary_receipt",
                "canary_timestamp_response",
            )
        )
        and gates["service_identity_documented"]
        and gates["policy_oid_allowlist_valid"]
    )
    if crypto_inputs_ready:
        authority = {
            "status": "candidate_not_registered",
            "test_only": payload.get("test_only"),
            "service_name": identity.get("service_name"),
            "service_endpoint": endpoint,
            "accepted_policy_oids": policies,
            "tsa_certificate": verified_artifacts["tsa_certificate"],
            "ca_bundle": verified_artifacts["ca_bundle"],
            "revocation_strategy": "offline_candidate_dossier_assessment",
        }
        try:
            result = timestamp_verifier._verify_registered_token(
                root=root,
                receipt_path=artifact_paths["canary_receipt"],
                timestamp_response_path=artifact_paths["canary_timestamp_response"],
                authority_id=candidate_id,
                authority=authority,
            )
        except (OSError, RuntimeError, ValueError) as error:
            errors.append(f"canary:{_error_code(error)}")
        else:
            gates["canary_signature_and_chain_verified"] = True
            gates["canary_exact_receipt_imprint_verified"] = True
            gates["canary_policy_oid_allowlisted"] = True
            token_time = result["token_time"]
            gates["canary_acquisition_time_consistent"] = (
                canary_acquired_at is not None
                and token_time <= canary_acquired_at <= assessed_at
            )
            cryptographic_verification = {
                "policy_oid": result["policy_oid"],
                "serial_number": result["serial_number"],
                "token_time": token_time.isoformat(),
                "openssl_version": result["openssl_version"],
                "signature_chain_exact_imprint_and_policy_verified": True,
            }

    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "status": "candidate_assessment_incomplete",
        "candidate_registration_ready": False,
        "dossier_artifact": dossier_artifact,
        "declarations": {
            "test_only": payload.get("test_only"),
            "service_endpoint": endpoint,
            "accepted_policy_oids": policies,
        },
        "verified_artifacts": verified_artifacts,
        "cryptographic_verification": cryptographic_verification,
        "gates": gates,
        "blockers": [],
        "verification_errors": sorted(set(errors)),
    }
    _finalize_candidate(row)
    return row


def _invalid_candidate(
    *,
    candidate_id: str,
    dossier_path: str,
    gates: dict[str, bool],
    error: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "status": "candidate_rejected",
        "candidate_registration_ready": False,
        "dossier_artifact": None,
        "dossier_path": dossier_path,
        "declarations": {},
        "verified_artifacts": {},
        "cryptographic_verification": None,
        "gates": gates,
        "blockers": [],
        "verification_errors": [error],
    }
    _finalize_candidate(row)
    return row


def _finalize_candidate(row: dict[str, Any]) -> None:
    blockers = [name for name in GATE_NAMES if row["gates"].get(name) is not True]
    ready = not blockers
    row["candidate_registration_ready"] = ready
    row["status"] = (
        "candidate_eligible_for_manual_registry_admission"
        if ready
        else "candidate_rejected"
    )
    row["blockers"] = blockers


def _valid_https_endpoint(value: object) -> bool:
    if not _nonempty_string(value):
        return False
    try:
        parsed = urlsplit(str(value))
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
    )


def _valid_revocation_strategy(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != REVOCATION_FIELDS:
        return False
    mechanisms = value.get("mechanisms")
    maximum_age = value.get("maximum_status_age_seconds")
    return (
        isinstance(mechanisms, list)
        and bool(mechanisms)
        and len(mechanisms) == len(set(_hashable_strings(mechanisms)))
        and all(item in {"ocsp", "crl"} for item in mechanisms)
        and value.get("check_before_registration") is True
        and value.get("check_before_each_token_verification") is True
        and value.get("failure_mode") == "fail_closed"
        and isinstance(maximum_age, int)
        and not isinstance(maximum_age, bool)
        and 0 < maximum_age <= 604800
    )


def _hashable_strings(values: list[object]) -> list[str]:
    return [value for value in values if isinstance(value, str)]


def _optional_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _aware_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"internal_innovation_timestamp_candidate_{name}_invalid")
    return value


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _error_code(error: BaseException) -> str:
    return str(error) or error.__class__.__name__


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError("internal_innovation_timestamp_candidate_output_conflict")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(body)
    except FileExistsError as error:
        raise FileExistsError(
            "internal_innovation_timestamp_candidate_output_conflict"
        ) from error


def main() -> int:
    args = parse_args()
    assessed_at = None
    if args.assessed_at is not None:
        assessed_at = _optional_time(args.assessed_at)
        if assessed_at is None:
            raise ValueError("internal_innovation_timestamp_candidate_assessed_at_invalid")
    report = assess_timestamp_authority_candidates(
        args.candidate_dossier,
        assessed_at=assessed_at,
    )
    _write_once(args.output, report)
    print(args.output)
    print(f"status={report['status']}")
    print(f"candidate_dossier_count={report['candidate_dossier_count']}")
    print(f"candidate_registration_ready={report['candidate_registration_ready']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
