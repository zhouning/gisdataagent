"""Gate protected re-execution of the checked real Chongqing feature input.

M3-26 composes the production identity and object-store readiness gates with
the immutable M3-25 predecessor. It never promotes local retained material and
never authorizes scheduler or provider mutations. A successful decision only
means that a separately approved execution may re-ingest the same content in a
protected environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import (
    metadata_fabric_identity_gate as identity_gate,
)
from . import (
    metadata_fabric_object_store_gate as object_store_gate,
)
from . import (
    metadata_fabric_retained_real_feature_restart_recovery as predecessor,
)

CONTRACT_SCHEMA = "gda.protected_real_feature_reexecution_contract.v1"
DECISION_SCHEMA = "gda.protected_real_feature_reexecution_decision.v1"
VALIDATION_SCHEMA = "gda.protected_real_feature_reexecution_validation.v1"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-retained-real-feature-restart-recovery-2026-07-31.json"
)
DEFAULT_DECISION_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-protected-real-feature-reexecution-gate-2026-07-31.json"
)

SOURCE_EVIDENCE_FILE_SHA256 = (
    "6880ff81dcde37f824ab3c7d04f62863375d5a6f1ada2a2dbfa832e77da7cfb1"
)
SOURCE_EVIDENCE_SHA256 = (
    "1b5a5ceeadee88868bab6237b3f3280c8b13793cc54193592fec7dbbfdd4e8a6"
)
SOURCE_RETENTION_ID = "m3-24-229740ac50ebb53b"

READY_STATUS = "ready_for_protected_reexecution"
BLOCKED_STATUS = "blocked_pending_protected_attestation"
SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[-_.])(password|passwd|secret|client[-_.]?secret|private[-_.]?key|"
    r"access[-_.]?key|access[-_.]?token|refresh[-_.]?token|authorization[-_.]?header)"
    r"($|[-_.])",
    re.IGNORECASE,
)

DECISION_INVENTORY = {
    "schema",
    "status",
    "evaluated_at",
    "contract_sha256",
    "source_binding",
    "identity_report",
    "object_store_report",
    "identity_attestation",
    "object_store_attestation",
    "blockers",
    "checked_real_feature_predecessor_verified",
    "production_profiles_valid",
    "protected_identity_attested",
    "protected_object_store_attested",
    "cross_gate_source_revision_aligned",
    "protected_tenant_controls_attested",
    "ready_for_protected_reexecution",
    "fresh_protected_ingestion_required",
    "local_retained_material_dependency",
    "source_payload_dependency",
    "local_material_promotion_allowed",
    "scheduler_submission_authorized",
    "provider_mutation_authorized",
    "production_ingestion_verified",
    "production_ready",
    "decision_sha256",
}


class ProtectedRealFeatureReexecutionGateError(RuntimeError):
    """The protected real-feature re-execution gate failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def canonical_json_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document is not an object")
    return value


def _parse_time(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtectedRealFeatureReexecutionGateError(
            f"{label} is not a valid timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProtectedRealFeatureReexecutionGateError(
            f"{label} must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _source_evidence(path: Path = DEFAULT_SOURCE_EVIDENCE_PATH) -> dict[str, Any]:
    if _file_sha256(path) != SOURCE_EVIDENCE_FILE_SHA256:
        raise ProtectedRealFeatureReexecutionGateError(
            "M3-25 source evidence file fingerprint does not match"
        )
    source = _load_json_object(path)
    errors = predecessor.validate_evidence(source)
    if errors:
        raise ProtectedRealFeatureReexecutionGateError(
            "M3-25 source evidence is invalid: " + "; ".join(errors)
        )
    if source.get("evidence_sha256") != SOURCE_EVIDENCE_SHA256:
        raise ProtectedRealFeatureReexecutionGateError(
            "M3-25 source evidence fingerprint does not match"
        )
    if source.get("retention_id") != SOURCE_RETENTION_ID:
        raise ProtectedRealFeatureReexecutionGateError(
            "M3-25 source retention identity does not match"
        )
    return source


def build_source_binding(
    path: Path = DEFAULT_SOURCE_EVIDENCE_PATH,
) -> dict[str, Any]:
    source = _source_evidence(path)
    material = _mapping(_mapping(source.get("material")).get("after"))
    quality = _mapping(_mapping(source.get("independent_quality")).get("after"))
    ledger = _mapping(_mapping(source.get("control_ledger")).get("after_terminal_replay"))
    return {
        "source_evidence_path": str(path.relative_to(REPO_ROOT)),
        "source_evidence_file_sha256": SOURCE_EVIDENCE_FILE_SHA256,
        "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
        "tenant_id": source.get("tenant_id"),
        "run_id": source.get("run_id"),
        "output_resource_version_id": source.get("output_resource_version_id"),
        "output_content_sha256": source.get("output_content_sha256"),
        "retention_id": source.get("retention_id"),
        "retention_expires_at": source.get("retention_expires_at"),
        "snapshot_id": material.get("snapshot_id"),
        "object_inventory_sha256": material.get("object_inventory_sha256"),
        "data_body_sha256": quality.get("data_body_sha256"),
        "row_set_sha256": quality.get("row_set_sha256"),
        "feature_count": _mapping(quality.get("metrics")).get("feature_count"),
        "control_facts_sha256": ledger.get("facts_sha256"),
        "platform_run_status": ledger.get("platform_run_status"),
        "platform_run_state_version": ledger.get("platform_run_state_version"),
    }


def build_contract_report() -> dict[str, Any]:
    source_binding = build_source_binding()
    identity_report = identity_gate.build_identity_readiness_report()
    object_store_report = object_store_gate.build_object_store_readiness_report()
    errors = [
        *identity_gate.verify_report_integrity(identity_report),
        *object_store_gate.verify_report_integrity(object_store_report),
    ]
    if identity_report.get("profile_valid") is not True:
        errors.append("production identity profile is invalid")
    if object_store_report.get("profile_valid") is not True:
        errors.append("production object-store profile is invalid")
    stable = {
        "schema": CONTRACT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "source_binding": source_binding,
        "identity_profile_fingerprint": identity_report.get("profile_fingerprint"),
        "object_store_profile_fingerprint": object_store_report.get(
            "profile_fingerprint"
        ),
        "requires_protected_identity_attestation": True,
        "requires_protected_object_store_attestation": True,
        "requires_cross_gate_source_revision_alignment": True,
        "requires_tenant_isolation_from_both_gates": True,
        "fresh_protected_ingestion_required": True,
        "local_material_promotion_forbidden": True,
        "scheduler_submission_authorized": False,
        "provider_mutation_authorized": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }
    return {**stable, "contract_sha256": canonical_json_fingerprint(stable)}


def _sensitive_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                findings.append(path)
            findings.extend(_sensitive_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_sensitive_paths(item, f"{prefix}[{index}]"))
    return findings


def _source_revision_alignment(
    identity_attestation: Mapping[str, Any] | None,
    object_store_attestation: Mapping[str, Any] | None,
) -> bool:
    if identity_attestation is None or object_store_attestation is None:
        return False
    identity_revision = str(identity_attestation.get("source_revision") or "")
    object_store_revision = str(object_store_attestation.get("source_revision") or "")
    return bool(
        SHA40_PATTERN.fullmatch(identity_revision)
        and identity_revision == object_store_revision
    )


def _blockers(
    identity_report: Mapping[str, Any],
    object_store_report: Mapping[str, Any],
    *,
    source_revision_aligned: bool,
) -> list[str]:
    blockers = [
        *(f"identity.profile:{item}" for item in identity_report.get("profile_blockers", [])),
        *(f"identity.attestation:{item}" for item in identity_report.get("attestation_errors", [])),
        *(
            f"object_store.profile:{item}"
            for item in object_store_report.get("profile_blockers", [])
        ),
        *(
            f"object_store.attestation:{item}"
            for item in object_store_report.get("attestation_errors", [])
        ),
    ]
    if (
        identity_report.get("attestation_valid") is True
        and object_store_report.get("attestation_valid") is True
        and not source_revision_aligned
    ):
        blockers.append("cross_gate:source_revision_mismatch")
    return sorted(set(str(item) for item in blockers))


def build_decision(
    *,
    identity_attestation: Mapping[str, Any] | None = None,
    object_store_attestation: Mapping[str, Any] | None = None,
    identity_profile_path: Path = identity_gate.DEFAULT_PROFILE_PATH,
    object_store_profile_path: Path = object_store_gate.DEFAULT_PROFILE_PATH,
    source_evidence_path: Path = DEFAULT_SOURCE_EVIDENCE_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    evaluated_at = (now or datetime.now(UTC)).astimezone(UTC)
    source_binding = build_source_binding(source_evidence_path)
    identity_report = identity_gate.build_identity_readiness_report(
        profile_path=identity_profile_path,
        attestation=identity_attestation,
        now=evaluated_at,
    )
    object_store_report = object_store_gate.build_object_store_readiness_report(
        profile_path=object_store_profile_path,
        attestation=object_store_attestation,
        now=evaluated_at,
    )
    aligned = _source_revision_alignment(
        identity_attestation, object_store_attestation
    )
    identity_passed = identity_report.get("production_identity_gate_passed") is True
    object_store_passed = (
        object_store_report.get("production_object_store_gate_passed") is True
    )
    tenant_attested = bool(
        identity_passed
        and object_store_passed
        and object_store_report.get("tenant_isolation_verified") is True
    )
    ready = bool(identity_passed and object_store_passed and aligned and tenant_attested)
    blockers = _blockers(
        identity_report,
        object_store_report,
        source_revision_aligned=aligned,
    )
    contract = build_contract_report()
    stable = {
        "schema": DECISION_SCHEMA,
        "status": READY_STATUS if ready else BLOCKED_STATUS,
        "evaluated_at": evaluated_at.isoformat().replace("+00:00", "Z"),
        "contract_sha256": contract["contract_sha256"],
        "source_binding": source_binding,
        "identity_report": identity_report,
        "object_store_report": object_store_report,
        "identity_attestation": (
            dict(identity_attestation) if identity_attestation is not None else None
        ),
        "object_store_attestation": (
            dict(object_store_attestation)
            if object_store_attestation is not None
            else None
        ),
        "blockers": blockers,
        "checked_real_feature_predecessor_verified": True,
        "production_profiles_valid": bool(
            identity_report.get("profile_valid") is True
            and object_store_report.get("profile_valid") is True
        ),
        "protected_identity_attested": identity_passed,
        "protected_object_store_attested": object_store_passed,
        "cross_gate_source_revision_aligned": aligned,
        "protected_tenant_controls_attested": tenant_attested,
        "ready_for_protected_reexecution": ready,
        "fresh_protected_ingestion_required": True,
        "local_retained_material_dependency": False,
        "source_payload_dependency": False,
        "local_material_promotion_allowed": False,
        "scheduler_submission_authorized": False,
        "provider_mutation_authorized": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }
    return {**stable, "decision_sha256": canonical_json_fingerprint(stable)}


def validate_decision(decision: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(decision) != DECISION_INVENTORY:
        errors.append("M3-26 decision inventory does not match")
    stable = {key: value for key, value in decision.items() if key != "decision_sha256"}
    if decision.get("decision_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-26 decision fingerprint does not match")
    try:
        evaluated_at = _parse_time(decision.get("evaluated_at"), label="evaluated_at")
        expected = build_decision(
            identity_attestation=(
                _mapping(decision.get("identity_attestation")) or None
            ),
            object_store_attestation=(
                _mapping(decision.get("object_store_attestation")) or None
            ),
            now=evaluated_at,
        )
    except (OSError, TypeError, ValueError, ProtectedRealFeatureReexecutionGateError) as exc:
        errors.append(f"M3-26 decision inputs are invalid: {exc}")
        expected = None
    if expected is not None and dict(decision) != expected:
        errors.append("M3-26 decision does not match current bound inputs")
    identity_report = _mapping(decision.get("identity_report"))
    object_store_report = _mapping(decision.get("object_store_report"))
    errors.extend(identity_gate.verify_report_integrity(identity_report))
    errors.extend(object_store_gate.verify_report_integrity(object_store_report))
    if _sensitive_paths(decision):
        errors.append("M3-26 decision contains credential-bearing fields")
    for claim in (
        "local_material_promotion_allowed",
        "scheduler_submission_authorized",
        "provider_mutation_authorized",
        "production_ingestion_verified",
        "production_ready",
    ):
        if decision.get(claim) is not False:
            errors.append(f"M3-26 decision may not claim {claim}")
    if decision.get("fresh_protected_ingestion_required") is not True:
        errors.append("M3-26 decision must require fresh protected ingestion")
    if decision.get("local_retained_material_dependency") is not False:
        errors.append("M3-26 decision may not depend on retained local material")
    if decision.get("source_payload_dependency") is not False:
        errors.append("M3-26 decision may not depend on deleted source payload")
    return sorted(set(errors))


def build_validation_report(
    decision_path: Path = DEFAULT_DECISION_PATH,
) -> dict[str, Any]:
    try:
        decision = _load_json_object(decision_path)
        errors = validate_decision(decision)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        decision = {}
        errors = [f"M3-26 decision is unreadable: {type(exc).__name__}"]
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "contract_sha256": decision.get("contract_sha256"),
        "decision_sha256": decision.get("decision_sha256"),
        "ready_for_protected_reexecution": decision.get(
            "ready_for_protected_reexecution"
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("contract")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--decision", type=Path, default=DEFAULT_DECISION_PATH)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output", type=Path, default=DEFAULT_DECISION_PATH)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--identity-attestation", type=Path, required=True)
    evaluate.add_argument("--object-store-attestation", type=Path, required=True)
    evaluate.add_argument(
        "--identity-profile",
        type=Path,
        default=identity_gate.DEFAULT_PROFILE_PATH,
    )
    evaluate.add_argument(
        "--object-store-profile",
        type=Path,
        default=object_store_gate.DEFAULT_PROFILE_PATH,
    )
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "contract":
            report = build_contract_report()
            exit_code = 0 if report["status"] == "valid" else 1
        elif args.command == "validate":
            report = build_validation_report(args.decision)
            exit_code = 0 if report["status"] == "valid" else 1
        elif args.command == "snapshot":
            report = build_decision()
            _write_json(args.output, report)
            exit_code = 0
        else:
            report = build_decision(
                identity_attestation=_load_json_object(args.identity_attestation),
                object_store_attestation=_load_json_object(
                    args.object_store_attestation
                ),
                identity_profile_path=args.identity_profile,
                object_store_profile_path=args.object_store_profile,
            )
            _write_json(args.output, report)
            exit_code = 0 if report["ready_for_protected_reexecution"] else 1
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ProtectedRealFeatureReexecutionGateError,
    ) as exc:
        print(f"protected real-feature re-execution gate: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
