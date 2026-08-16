"""Evaluate the fail-closed production observability readiness contract.

The checked-in profile records decisions that must exist before a durable
Metadata Fabric metrics stack can be promoted. Missing external decisions are
valid blockers. Production observability passes only when a complete profile
is paired with a fresh, profile-bound protected-environment attestation. This
module does not deploy a backend or claim that the whole platform is ready.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from . import metadata_fabric_recovery_rehearsal as recovery

PROFILE_SCHEMA = "gda.metadata_fabric_observability_production_profile.v1"
ATTESTATION_SCHEMA = "gda.metadata_fabric_observability_attestation.v1"
REPORT_SCHEMA = "gda.metadata_fabric_observability_readiness_report.v1"
ENVIRONMENT = "production"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-observability.production.yaml"
)

EXPECTED_PROVIDERS = {
    "openmetadata": "1.13.1",
    "gravitino": "1.3.0",
}
ALLOWED_BACKENDS = {
    "managed_prometheus",
    "mimir",
    "prometheus_compatible",
    "thanos",
}
EXPECTED_LABELS = {
    "gda_environment",
    "gda_provider",
    "gda_tenant_id",
}
EXPECTED_SLOS = {
    "openmetadata-metrics-availability": (
        "openmetadata",
        "scrape_availability",
    ),
    "gravitino-metrics-availability": (
        "gravitino",
        "scrape_availability",
    ),
    "metadata-metrics-freshness": (
        "metadata_fabric",
        "metrics_freshness",
    ),
}
EXPECTED_ATTESTATION_CHECKS = {
    "continuous_collection",
    "persistent_storage",
    "historical_query",
    "tls_transport",
    "workload_identity",
    "tenant_isolation",
    "dashboard_access",
    "firing_notification_delivery",
    "recovery_notification_delivery",
    "data_slo_evaluation",
    "runbook_response",
}
EXPECTED_CLAIMS = {
    "backend_decision_frozen",
    "persistent_metrics_backend_verified",
    "metrics_tls_verified",
    "workload_identity_verified",
    "tenant_isolation_verified",
    "dashboard_ownership_verified",
    "alert_delivery_verified",
    "slo_verified",
    "runbook_verified",
    "production_observability_gate_passed",
    "production_ready",
}
SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PLACEHOLDER_PATTERN = re.compile(
    r"(^|[-_.:/])(pending|placeholder|replace|tbd|todo|changeme)([-_.:/]|$)|"
    r"[<>]|\.example(?=[:/]|$)",
    re.IGNORECASE,
)


class MetadataFabricObservabilityGateError(RuntimeError):
    """The production observability readiness contract failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_yaml_object(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("YAML document is not an object")
    return payload


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON document is not an object")
    return payload


def _placeholder(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip() or bool(
        PLACEHOLDER_PATTERN.search(value.strip())
    )


def _production_https_url(value: Any) -> bool:
    if _placeholder(value):
        return False
    parsed = urlparse(str(value))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return False
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "0.0.0.0", "::1"}:
        return False
    if hostname.endswith((".localhost", ".local", ".svc", ".cluster.local")):
        return False
    reserved_domains = ("example.com", "example.net", "example.org")
    if hostname in reserved_domains or hostname.endswith(
        tuple(f".{domain}" for domain in reserved_domains)
    ):
        return False
    try:
        if ipaddress.ip_address(hostname).is_loopback:
            return False
    except ValueError:
        pass
    return True


def _inventory_errors(
    value: Mapping[str, Any], expected: set[str], name: str
) -> list[str]:
    return [] if set(value) == expected else [f"{name} inventory does not match"]


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(profile):
        errors.append("observability profile contains credential-bearing fields")
    errors.extend(
        _inventory_errors(
            profile,
            {
                "schema",
                "environment",
                "scope",
                "backend",
                "security",
                "tenancy",
                "operations",
                "claims",
            },
            "observability profile",
        )
    )
    if (
        profile.get("schema") != PROFILE_SCHEMA
        or profile.get("environment") != ENVIRONMENT
    ):
        errors.append("observability profile schema or environment does not match")

    scope = _mapping(profile.get("scope"))
    providers = _mapping(scope.get("providers"))
    errors.extend(_inventory_errors(scope, {"providers"}, "provider scope"))
    errors.extend(_inventory_errors(providers, set(EXPECTED_PROVIDERS), "provider"))
    for provider, version in EXPECTED_PROVIDERS.items():
        item = _mapping(providers.get(provider))
        errors.extend(
            _inventory_errors(item, {"version", "environment_binding"}, f"{provider} binding")
        )
        if item.get("version") != version:
            errors.append(f"{provider} version does not match the approved baseline")
        binding = item.get("environment_binding")
        if binding is not None and _placeholder(binding):
            errors.append(f"{provider} environment binding is a placeholder")

    backend = _mapping(profile.get("backend"))
    errors.extend(
        _inventory_errors(
            backend,
            {
                "decision_status",
                "type",
                "write_endpoint",
                "query_endpoint",
                "durable_storage",
                "retention_days",
            },
            "metrics backend",
        )
    )
    if backend.get("decision_status") not in {"pending", "approved"}:
        errors.append("metrics backend decision status is invalid")
    backend_type = backend.get("type")
    if backend_type is not None and backend_type not in ALLOWED_BACKENDS:
        errors.append("metrics backend type is invalid")
    for key in ("write_endpoint", "query_endpoint"):
        endpoint = backend.get(key)
        if endpoint is not None and not _production_https_url(endpoint):
            errors.append(f"metrics backend {key} is not a production HTTPS endpoint")
    if backend.get("durable_storage") not in {True, False}:
        errors.append("metrics backend durable_storage must be boolean")
    retention = backend.get("retention_days")
    if retention is not None and (
        not isinstance(retention, int) or isinstance(retention, bool) or retention < 30
    ):
        errors.append("metrics retention must be at least 30 days")

    security = _mapping(profile.get("security"))
    errors.extend(
        _inventory_errors(
            security,
            {"tls_required", "minimum_tls_version", "workload_identity_reference"},
            "metrics security",
        )
    )
    if security.get("tls_required") is not True:
        errors.append("production metrics transport must require TLS")
    if security.get("minimum_tls_version") not in {"TLSv1.2", "TLSv1.3"}:
        errors.append("production metrics minimum TLS version is invalid")
    identity = security.get("workload_identity_reference")
    if identity is not None and _placeholder(identity):
        errors.append("workload identity reference is a placeholder")

    tenancy = _mapping(profile.get("tenancy"))
    errors.extend(
        _inventory_errors(
            tenancy,
            {"isolation_mode", "tenant_label", "required_labels"},
            "metrics tenancy",
        )
    )
    if tenancy.get("isolation_mode") not in {None, "label_policy_enforced"}:
        errors.append("tenant isolation mode is invalid")
    tenant_label = tenancy.get("tenant_label")
    if tenant_label is not None and tenant_label != "gda_tenant_id":
        errors.append("tenant label must be gda_tenant_id")
    labels = tenancy.get("required_labels")
    if (
        not isinstance(labels, list)
        or any(not isinstance(label, str) for label in labels)
        or set(labels) != EXPECTED_LABELS
        or len(labels) != len(EXPECTED_LABELS)
    ):
        errors.append("required metrics label inventory does not match")

    operations = _mapping(profile.get("operations"))
    errors.extend(
        _inventory_errors(
            operations,
            {
                "dashboard_owner",
                "alert_owner",
                "slo_owner",
                "notification_channel_reference",
                "slos",
                "runbook",
            },
            "observability operations",
        )
    )
    for key in (
        "dashboard_owner",
        "alert_owner",
        "slo_owner",
        "notification_channel_reference",
    ):
        value = operations.get(key)
        if value is not None and _placeholder(value):
            errors.append(f"observability operations {key} is a placeholder")
    slos = operations.get("slos")
    if not isinstance(slos, list):
        errors.append("data SLO inventory must be a list")
        slos = []
    seen: set[str] = set()
    for index, raw in enumerate(slos):
        item = _mapping(raw)
        errors.extend(
            _inventory_errors(
                item,
                {
                    "id",
                    "provider",
                    "objective",
                    "target_percent",
                    "window_days",
                    "threshold",
                    "recovery_notification_required",
                },
                f"data SLO {index}",
            )
        )
        slo_id = item.get("id")
        if not isinstance(slo_id, str) or slo_id in seen:
            errors.append(f"data SLO {index} identity is missing or duplicated")
        else:
            seen.add(slo_id)
        expected = EXPECTED_SLOS.get(str(slo_id))
        if (
            expected is None
            or (item.get("provider"), item.get("objective")) != expected
        ):
            errors.append(f"data SLO {index} provider or objective does not match")
        target = item.get("target_percent")
        if (
            not isinstance(target, (int, float))
            or isinstance(target, bool)
            or not 0 < target <= 100
        ):
            errors.append(f"data SLO {index} target_percent is invalid")
        window = item.get("window_days")
        if (
            not isinstance(window, int)
            or isinstance(window, bool)
            or not 7 <= window <= 90
        ):
            errors.append(f"data SLO {index} window_days is invalid")
        threshold = _mapping(item.get("threshold"))
        if set(threshold) != {"operator", "value", "unit"}:
            errors.append(f"data SLO {index} threshold inventory does not match")
        if threshold.get("operator") not in {"gt", "gte", "lt", "lte"}:
            errors.append(f"data SLO {index} threshold operator is invalid")
        value = threshold.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            errors.append(f"data SLO {index} threshold value is invalid")
        if _placeholder(threshold.get("unit")):
            errors.append(f"data SLO {index} threshold unit is invalid")
        if item.get("recovery_notification_required") is not True:
            errors.append(f"data SLO {index} must require recovery notification")

    runbook = _mapping(operations.get("runbook"))
    errors.extend(_inventory_errors(runbook, {"uri", "version"}, "runbook"))
    uri = runbook.get("uri")
    if uri is not None and not _production_https_url(uri):
        errors.append("runbook URI is not a production HTTPS URL")
    version = runbook.get("version")
    if version is not None and _placeholder(version):
        errors.append("runbook version is a placeholder")

    claims = _mapping(profile.get("claims"))
    errors.extend(_inventory_errors(claims, EXPECTED_CLAIMS, "observability claim"))
    for claim in sorted(EXPECTED_CLAIMS):
        if claims.get(claim) is not False:
            errors.append(f"profile may not self-assert production claim: {claim}")
    return errors


def _profile_blockers(profile: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    providers = _mapping(_mapping(profile.get("scope")).get("providers"))
    for provider in EXPECTED_PROVIDERS:
        if _placeholder(_mapping(providers.get(provider)).get("environment_binding")):
            blockers.append(f"providers.{provider}.environment_binding")

    backend = _mapping(profile.get("backend"))
    if backend.get("decision_status") != "approved":
        blockers.append("backend.decision_status")
    if backend.get("type") not in ALLOWED_BACKENDS:
        blockers.append("backend.type")
    for key in ("write_endpoint", "query_endpoint"):
        if not _production_https_url(backend.get(key)):
            blockers.append(f"backend.{key}")
    if backend.get("durable_storage") is not True:
        blockers.append("backend.durable_storage")
    retention = backend.get("retention_days")
    if not isinstance(retention, int) or isinstance(retention, bool) or retention < 30:
        blockers.append("backend.retention_days")

    security = _mapping(profile.get("security"))
    if _placeholder(security.get("workload_identity_reference")):
        blockers.append("security.workload_identity_reference")

    tenancy = _mapping(profile.get("tenancy"))
    if tenancy.get("isolation_mode") != "label_policy_enforced":
        blockers.append("tenancy.isolation_mode")
    if tenancy.get("tenant_label") != "gda_tenant_id":
        blockers.append("tenancy.tenant_label")

    operations = _mapping(profile.get("operations"))
    for key in (
        "dashboard_owner",
        "alert_owner",
        "slo_owner",
        "notification_channel_reference",
    ):
        if _placeholder(operations.get(key)):
            blockers.append(f"operations.{key}")
    slos = operations.get("slos")
    if isinstance(slos, list):
        slo_ids = {
            str(_mapping(item).get("id"))
            for item in slos
            if isinstance(item, Mapping)
        }
    else:
        slo_ids = set()
    for slo_id in EXPECTED_SLOS:
        if slo_id not in slo_ids:
            blockers.append(f"operations.slos.{slo_id}")
    runbook = _mapping(operations.get("runbook"))
    if not _production_https_url(runbook.get("uri")):
        blockers.append("operations.runbook.uri")
    if _placeholder(runbook.get("version")):
        blockers.append("operations.runbook.version")
    return blockers


def _attestation_errors(
    attestation: Mapping[str, Any] | None,
    *,
    profile: Mapping[str, Any],
    profile_fingerprint: str,
    expected_source_revision: str | None,
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    if attestation is None:
        return ["production observability attestation is missing"]
    errors: list[str] = []
    if recovery._sensitive_paths(attestation):
        errors.append("observability attestation contains credential-bearing fields")
    errors.extend(
        _inventory_errors(
            attestation,
            {
                "schema",
                "environment",
                "profile_fingerprint",
                "source_revision",
                "observed_at",
                "expires_at",
                "protected_environment",
                "verifier_identity",
                "evidence_uri",
                "provider_versions",
                "backend_binding",
                "runbook_version",
                "checks",
            },
            "observability attestation",
        )
    )
    if (
        attestation.get("schema") != ATTESTATION_SCHEMA
        or attestation.get("environment") != ENVIRONMENT
    ):
        errors.append("observability attestation schema or environment does not match")
    if attestation.get("profile_fingerprint") != profile_fingerprint:
        errors.append("observability attestation is not bound to the current profile")
    source_revision = str(attestation.get("source_revision") or "")
    if not SHA40_PATTERN.fullmatch(str(expected_source_revision or "")):
        errors.append("expected source revision is invalid")
    if not SHA40_PATTERN.fullmatch(source_revision):
        errors.append("observability attestation source revision is invalid")
    elif source_revision != expected_source_revision:
        errors.append(
            "observability attestation source revision does not match the "
            "protected verification target"
        )
    if attestation.get("protected_environment") != ENVIRONMENT:
        errors.append(
            "observability attestation did not run in the protected production "
            "environment"
        )
    if _placeholder(attestation.get("verifier_identity")):
        errors.append("observability attestation verifier identity is missing")
    if not _production_https_url(attestation.get("evidence_uri")):
        errors.append("observability attestation evidence URI is invalid")

    try:
        observed_at = datetime.fromisoformat(str(attestation.get("observed_at")))
        expires_at = datetime.fromisoformat(str(attestation.get("expires_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError
        age = now - observed_at
        if age < timedelta(seconds=-30) or age > max_age:
            errors.append("observability attestation is outside the accepted freshness window")
        if expires_at <= now or expires_at <= observed_at:
            errors.append("observability attestation has expired or has an invalid expiry")
        if expires_at - observed_at > timedelta(days=7):
            errors.append("observability attestation validity exceeds seven days")
    except ValueError:
        errors.append("observability attestation timestamps are invalid")

    if _mapping(attestation.get("provider_versions")) != EXPECTED_PROVIDERS:
        errors.append("observability attestation provider versions do not match")
    backend = _mapping(profile.get("backend"))
    expected_backend = {
        "type": backend.get("type"),
        "write_endpoint": backend.get("write_endpoint"),
        "query_endpoint": backend.get("query_endpoint"),
        "retention_days": backend.get("retention_days"),
    }
    if _mapping(attestation.get("backend_binding")) != expected_backend:
        errors.append("observability attestation backend binding does not match")
    runbook = _mapping(_mapping(profile.get("operations")).get("runbook"))
    if attestation.get("runbook_version") != runbook.get("version"):
        errors.append("observability attestation runbook version does not match")
    checks = _mapping(attestation.get("checks"))
    if set(checks) != EXPECTED_ATTESTATION_CHECKS:
        errors.append("observability attestation check inventory does not match")
    for check in sorted(EXPECTED_ATTESTATION_CHECKS):
        if checks.get(check) != "passed":
            errors.append(f"observability attestation check did not pass: {check}")
    return errors


def build_observability_readiness_report(
    *,
    profile_path: Path | None = None,
    attestation: Mapping[str, Any] | None = None,
    expected_source_revision: str | None = None,
    now: datetime | None = None,
    max_attestation_age: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    """Build a deterministic readiness result from profile and optional evidence."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricObservabilityGateError(
            "readiness verification time must be timezone-aware"
        )
    if max_attestation_age <= timedelta(0):
        raise MetadataFabricObservabilityGateError(
            "attestation freshness window must be positive"
        )
    path = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    try:
        profile = _load_yaml_object(path)
    except (OSError, TypeError, yaml.YAMLError) as exc:
        stable = {
            "schema": REPORT_SCHEMA,
            "environment": ENVIRONMENT,
            "profile_fingerprint": None,
            "attestation_fingerprint": None,
            "profile_valid": False,
            "profile_errors": [f"observability profile is invalid: {type(exc).__name__}"],
            "profile_blockers": [],
            "attestation_valid": False,
            "attestation_errors": ["production observability attestation is missing"],
            "ready_for_protected_verification": False,
            "production_observability_gate_passed": False,
            "production_ready": False,
        }
        return {**stable, "report_fingerprint": recovery._canonical_sha256(stable)}

    profile_fingerprint = recovery._canonical_sha256(profile)
    profile_errors = _profile_errors(profile)
    profile_blockers = _profile_blockers(profile)
    profile_valid = not profile_errors
    ready_for_verification = profile_valid and not profile_blockers
    attestation_errors = _attestation_errors(
        attestation,
        profile=profile,
        profile_fingerprint=profile_fingerprint,
        expected_source_revision=expected_source_revision,
        now=current,
        max_age=max_attestation_age,
    )
    attestation_valid = ready_for_verification and not attestation_errors
    gate_passed = ready_for_verification and attestation_valid
    stable = {
        "schema": REPORT_SCHEMA,
        "environment": ENVIRONMENT,
        "profile_fingerprint": profile_fingerprint,
        "attestation_fingerprint": (
            recovery._canonical_sha256(attestation) if attestation is not None else None
        ),
        "profile_valid": profile_valid,
        "profile_errors": profile_errors,
        "profile_blockers": profile_blockers,
        "attestation_valid": attestation_valid,
        "attestation_errors": attestation_errors,
        "ready_for_protected_verification": ready_for_verification,
        "production_observability_gate_passed": gate_passed,
        "production_ready": False,
    }
    return {**stable, "report_fingerprint": recovery._canonical_sha256(stable)}


def verify_report_integrity(report: Mapping[str, Any]) -> list[str]:
    """Reject modified readiness reports and any overall production overclaim."""
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("observability readiness report contains credential-bearing fields")
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("observability readiness report schema does not match")
    stable = {key: value for key, value in report.items() if key != "report_fingerprint"}
    if report.get("report_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("observability readiness report fingerprint does not match")
    if report.get("production_ready") is not False:
        errors.append("observability gate may not claim overall production readiness")
    expected_gate = (
        report.get("profile_valid") is True
        and report.get("profile_blockers") == []
        and report.get("attestation_valid") is True
    )
    if report.get("production_observability_gate_passed") is not expected_gate:
        errors.append("observability gate result is inconsistent")
    return errors


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    evaluate_parser.add_argument("--attestation", type=Path, required=True)
    evaluate_parser.add_argument("--source-revision", required=True)
    evaluate_parser.add_argument("--output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            report = build_observability_readiness_report(profile_path=args.profile)
            _write_report(report, None)
            return 0 if report["profile_valid"] else 1
        if args.command == "evaluate":
            attestation = _load_json_object(args.attestation)
            report = build_observability_readiness_report(
                profile_path=args.profile,
                attestation=attestation,
                expected_source_revision=args.source_revision,
            )
            _write_report(report, args.output)
            return 0 if report["production_observability_gate_passed"] else 1
        report = _load_json_object(args.input)
        errors = verify_report_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
        MetadataFabricObservabilityGateError,
    ) as exc:
        print(f"metadata observability gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
