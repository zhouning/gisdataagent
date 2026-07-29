"""Evaluate the fail-closed production object-store readiness gate.

The checked profile binds the local Spark/MinIO interoperability evidence and
freezes the external decisions required for a production Iceberg warehouse.
It deploys nothing, accepts no credentials, and derives production claims only
from a fresh attestation bound to the exact profile and protected environment.
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
from . import metadata_fabric_spark_object_store_interoperability as local_interop


PROFILE_SCHEMA = "gda.metadata_fabric_object_store_production_profile.v1"
ATTESTATION_SCHEMA = "gda.metadata_fabric_object_store_attestation.v1"
REPORT_SCHEMA = "gda.metadata_fabric_object_store_readiness_report.v1"
ENVIRONMENT = "production"
REPOSITORY = "zhouning/gisdataagent"
PROTECTED_ENVIRONMENT = "production-object-store"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-object-store.production.yaml"
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-object-store-gate.sh"

LOCAL_EVIDENCE = {
    "path": "docs/evidence/metadata-fabric-spark-object-store-interoperability-2026-07-29.json",
    "evidence_fingerprint": (
        "05844457efb378581fb7fc2e7ed3c706819b2d8fa5a52b2f82577051d38c2cd1"
    ),
    "required_claim": "local_spark_object_store_interoperability_verified",
}
EXPECTED_ENGINES = {"spark": "3.5.0", "iceberg": "1.6.1", "gravitino": "1.3.0"}
ALLOWED_PROVIDERS = {
    "aws_s3",
    "huawei_obs_s3_compatible",
    "managed_s3_compatible",
}
ALLOWED_OPERATIONS = [
    "s3:AbortMultipartUpload",
    "s3:DeleteObject",
    "s3:GetBucketLocation",
    "s3:GetObject",
    "s3:ListBucket",
    "s3:ListBucketMultipartUploads",
    "s3:ListMultipartUploadParts",
    "s3:PutObject",
]
EXPECTED_CHECKS = {
    "provider_account_isolation",
    "bucket_outside_source_cluster",
    "multi_az_durability",
    "private_network_path",
    "tls_transport",
    "workload_identity_exchange",
    "static_credentials_absent",
    "least_privilege_allow",
    "administrative_action_denied",
    "cross_tenant_denial",
    "public_access_blocked",
    "kms_encrypt_decrypt",
    "kms_key_rotation",
    "versioning_enabled",
    "cross_region_replication",
    "read_after_write_consistency",
    "list_after_write_consistency",
    "multipart_abort_cleanup",
    "orphan_file_cleanup",
    "spark_gravitino_read_write",
    "commit_failure_recovery",
    "source_cluster_loss_recovery",
    "audit_log_delivery",
    "metrics_alert_delivery",
    "backup_restore",
    "rollback_rehearsal",
}
PROFILE_CLAIMS = {
    "object_store_decision_frozen",
    "protected_workload_identity_verified",
    "tls_verified",
    "kms_encryption_verified",
    "tenant_isolation_verified",
    "object_store_durability_verified",
    "object_store_failure_recovery_verified",
    "production_object_store_verified",
    "production_object_store_gate_passed",
    "production_ready",
}
REPORT_CLAIMS = PROFILE_CLAIMS - {"production_ready"}
BINDING_SECTIONS = (
    "provider",
    "identity",
    "transport",
    "encryption",
    "durability",
    "consistency",
    "tenancy",
    "operations",
)
REPORT_INVENTORY = {
    "schema",
    "environment",
    "profile_fingerprint",
    "local_evidence_fingerprint",
    "attestation_fingerprint",
    *{f"{name}_fingerprint" for name in BINDING_SECTIONS},
    "profile_valid",
    "profile_errors",
    "profile_blockers",
    "ready_for_protected_verification",
    "attestation_valid",
    "attestation_errors",
    *REPORT_CLAIMS,
    "production_ready",
    "report_fingerprint",
}

SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9.]{1,61}[a-z0-9])?$")
REGION_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
REFERENCE_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(
    r"(^|[-_.:/])(pending|placeholder|replace|tbd|todo|changeme)([-_.:/]|$)|"
    r"[<>]|\.example(?=[:/]|$)",
    re.IGNORECASE,
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[-_.])(password|passwd|secret|client[-_.]?secret|private[-_.]?key|"
    r"access[-_.]?key|access[-_.]?token|refresh[-_.]?token|authorization)"
    r"($|[-_.])",
    re.IGNORECASE,
)


class MetadataFabricObjectStoreGateError(RuntimeError):
    """The production object-store readiness contract failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_yaml_object(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("YAML document is not an object")
    return value


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document is not an object")
    return value


def _inventory_errors(
    value: Mapping[str, Any], expected: set[str], label: str
) -> list[str]:
    return [] if set(value) == expected else [f"{label} inventory does not match"]


def _placeholder(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip() or bool(
        PLACEHOLDER_PATTERN.search(value.strip())
    )


def _reference(value: Any) -> bool:
    return not _placeholder(value) and bool(REFERENCE_PATTERN.fullmatch(str(value)))


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
    if hostname in {"localhost", "0.0.0.0", "::1"} or hostname.endswith(
        (".localhost", ".local", ".svc", ".cluster.local")
    ):
        return False
    if hostname in {"example.com", "example.net", "example.org"} or hostname.endswith(
        (".example.com", ".example.net", ".example.org")
    ):
        return False
    try:
        if ipaddress.ip_address(hostname).is_private:
            return False
    except ValueError:
        pass
    return True


def _sensitive_paths(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            child = (*path, str(key))
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                found.append(".".join(child))
            found.extend(_sensitive_paths(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_sensitive_paths(nested, (*path, str(index))))
    return found


def _local_evidence_errors(value: Mapping[str, Any]) -> list[str]:
    errors = _inventory_errors(value, set(LOCAL_EVIDENCE), "local evidence")
    if dict(value) != LOCAL_EVIDENCE:
        errors.append("local object-store evidence binding does not match")
        return errors
    try:
        path = (REPO_ROOT / LOCAL_EVIDENCE["path"]).resolve()
        path.relative_to(REPO_ROOT)
        evidence = _load_json_object(path)
        integrity_errors = local_interop.verify_evidence_integrity(evidence)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        errors.append("local object-store evidence is unavailable")
        return errors
    if integrity_errors:
        errors.append("local object-store evidence integrity does not match")
    if (
        evidence.get("evidence_fingerprint")
        != LOCAL_EVIDENCE["evidence_fingerprint"]
        or evidence.get(LOCAL_EVIDENCE["required_claim"]) is not True
    ):
        errors.append("local object-store evidence claim does not match")
    for claim in (
        "production_object_store_verified",
        "spark_conformance_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"local object-store evidence overclaims {claim}")
    return errors


def _runbook_errors(value: Mapping[str, Any], label: str) -> list[str]:
    errors = _inventory_errors(value, {"uri", "version"}, label)
    if value.get("uri") is not None and not _production_https_url(value.get("uri")):
        errors.append(f"{label} URI is invalid")
    if value.get("version") is not None and _placeholder(value.get("version")):
        errors.append(f"{label} version is invalid")
    return errors


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if _sensitive_paths(profile):
        errors.append("object-store profile contains credential-bearing fields")
    errors.extend(
        _inventory_errors(
            profile,
            {
                "schema",
                "environment",
                "scope",
                *BINDING_SECTIONS,
                "claims",
            },
            "object-store profile",
        )
    )
    if profile.get("schema") != PROFILE_SCHEMA or profile.get("environment") != ENVIRONMENT:
        errors.append("object-store profile schema or environment does not match")

    scope = _mapping(profile.get("scope"))
    errors.extend(_inventory_errors(scope, {"engines", "local_evidence"}, "scope"))
    if dict(_mapping(scope.get("engines"))) != EXPECTED_ENGINES:
        errors.append("object-store engine version binding does not match")
    errors.extend(_local_evidence_errors(_mapping(scope.get("local_evidence"))))

    provider = _mapping(profile.get("provider"))
    provider_keys = {
        "decision_status",
        "provider_type",
        "account_reference",
        "region",
        "endpoint",
        "bucket",
        "warehouse_prefix",
        "infrastructure_reference",
        "failure_domain_reference",
        "recovery_region",
        "multi_az_required",
        "source_cluster_independent",
    }
    errors.extend(_inventory_errors(provider, provider_keys, "object-store provider"))
    if provider.get("decision_status") not in {"pending", "approved"}:
        errors.append("object-store provider decision status is invalid")
    if provider.get("provider_type") not in {None, *ALLOWED_PROVIDERS}:
        errors.append("object-store provider type is invalid")
    for key in (
        "account_reference",
        "infrastructure_reference",
        "failure_domain_reference",
    ):
        if provider.get(key) is not None and not _reference(provider.get(key)):
            errors.append(f"object-store provider {key} is invalid")
    for key in ("region", "recovery_region"):
        if provider.get(key) is not None and not REGION_PATTERN.fullmatch(
            str(provider.get(key))
        ):
            errors.append(f"object-store provider {key} is invalid")
    if provider.get("endpoint") is not None and not _production_https_url(
        provider.get("endpoint")
    ):
        errors.append("object-store provider endpoint is invalid")
    if provider.get("bucket") is not None and not DNS_LABEL_PATTERN.fullmatch(
        str(provider.get("bucket"))
    ):
        errors.append("object-store bucket name is invalid")
    prefix = provider.get("warehouse_prefix")
    if (
        not isinstance(prefix, str)
        or not prefix.endswith("/")
        or prefix.startswith("/")
        or ".." in prefix
    ):
        errors.append("object-store warehouse prefix is invalid")
    if (
        provider.get("region") is not None
        and provider.get("region") == provider.get("recovery_region")
    ):
        errors.append("object-store recovery region must be distinct")
    if (
        provider.get("multi_az_required") is not True
        or provider.get("source_cluster_independent") is not True
    ):
        errors.append("object-store provider failure-domain baseline does not match")

    identity = _mapping(profile.get("identity"))
    identity_keys = {
        "integration_mode",
        "workload_identity_reference",
        "kubernetes_service_account",
        "least_privilege_policy_reference",
        "bucket_policy_reference",
        "allowed_operations",
        "static_credentials_forbidden",
        "maximum_session_ttl_seconds",
    }
    errors.extend(_inventory_errors(identity, identity_keys, "object-store identity"))
    if identity.get("integration_mode") not in {None, "oidc_workload_federation"}:
        errors.append("object-store identity integration mode is invalid")
    for key in (
        "workload_identity_reference",
        "least_privilege_policy_reference",
        "bucket_policy_reference",
    ):
        if identity.get(key) is not None and not _reference(identity.get(key)):
            errors.append(f"object-store identity {key} is invalid")
    service_account = identity.get("kubernetes_service_account")
    if service_account is not None and not DNS_LABEL_PATTERN.fullmatch(str(service_account)):
        errors.append("object-store Kubernetes ServiceAccount is invalid")
    if identity.get("allowed_operations") != ALLOWED_OPERATIONS:
        errors.append("object-store least-privilege operation inventory does not match")
    if (
        identity.get("static_credentials_forbidden") is not True
        or identity.get("maximum_session_ttl_seconds") != 900
    ):
        errors.append("object-store credential baseline does not match")

    transport = _mapping(profile.get("transport"))
    transport_keys = {
        "tls_required",
        "minimum_version",
        "endpoint",
        "private_connectivity_reference",
        "dns_policy_reference",
        "trust_bundle_reference",
        "certificate_policy_reference",
    }
    errors.extend(_inventory_errors(transport, transport_keys, "object-store transport"))
    if (
        transport.get("tls_required") is not True
        or transport.get("minimum_version") not in {"TLSv1.2", "TLSv1.3"}
    ):
        errors.append("object-store TLS baseline does not match")
    if transport.get("endpoint") is not None and not _production_https_url(
        transport.get("endpoint")
    ):
        errors.append("object-store transport endpoint is invalid")
    if (
        provider.get("endpoint") is not None
        and transport.get("endpoint") != provider.get("endpoint")
    ):
        errors.append("object-store provider and transport endpoints differ")
    for key in transport_keys - {"tls_required", "minimum_version", "endpoint"}:
        if transport.get(key) is not None and not _reference(transport.get(key)):
            errors.append(f"object-store transport {key} is invalid")

    encryption = _mapping(profile.get("encryption"))
    encryption_keys = {
        "server_side_required",
        "mode",
        "key_reference",
        "key_policy_reference",
        "rotation_days",
        "bucket_key_enabled",
    }
    errors.extend(_inventory_errors(encryption, encryption_keys, "object-store encryption"))
    if (
        encryption.get("server_side_required") is not True
        or encryption.get("mode") != "kms"
        or encryption.get("bucket_key_enabled") is not True
    ):
        errors.append("object-store encryption baseline does not match")
    for key in ("key_reference", "key_policy_reference"):
        if encryption.get(key) is not None and not _reference(encryption.get(key)):
            errors.append(f"object-store encryption {key} is invalid")
    rotation = encryption.get("rotation_days")
    if rotation is not None and (
        not isinstance(rotation, int) or isinstance(rotation, bool) or not 1 <= rotation <= 365
    ):
        errors.append("object-store encryption rotation is invalid")

    durability = _mapping(profile.get("durability"))
    durability_keys = {
        "versioning_enabled",
        "delete_protection_mode",
        "retention_policy_reference",
        "replication_mode",
        "replication_policy_reference",
        "recovery_bucket_reference",
        "maximum_rpo_minutes",
        "maximum_rto_minutes",
    }
    errors.extend(_inventory_errors(durability, durability_keys, "object-store durability"))
    if (
        durability.get("versioning_enabled") is not True
        or durability.get("delete_protection_mode") != "versioned_recovery"
        or durability.get("replication_mode") != "asynchronous_cross_region"
        or durability.get("maximum_rpo_minutes") != 15
        or durability.get("maximum_rto_minutes") != 60
    ):
        errors.append("object-store durability baseline does not match")
    for key in (
        "retention_policy_reference",
        "replication_policy_reference",
        "recovery_bucket_reference",
    ):
        if durability.get(key) is not None and not _reference(durability.get(key)):
            errors.append(f"object-store durability {key} is invalid")

    consistency = _mapping(profile.get("consistency"))
    consistency_keys = {
        "strong_read_after_write_required",
        "strong_list_after_write_required",
        "atomic_rename_required",
        "multipart_upload_cleanup_reference",
        "orphan_file_cleanup_reference",
    }
    errors.extend(_inventory_errors(consistency, consistency_keys, "object-store consistency"))
    if (
        consistency.get("strong_read_after_write_required") is not True
        or consistency.get("strong_list_after_write_required") is not True
        or consistency.get("atomic_rename_required") is not False
    ):
        errors.append("object-store consistency baseline does not match")
    for key in ("multipart_upload_cleanup_reference", "orphan_file_cleanup_reference"):
        if consistency.get(key) is not None and not _reference(consistency.get(key)):
            errors.append(f"object-store consistency {key} is invalid")

    tenancy = _mapping(profile.get("tenancy"))
    tenancy_keys = {
        "isolation_mode",
        "tenant_prefix_template",
        "policy_reference",
        "cross_tenant_denial_required",
        "public_access_blocked",
    }
    errors.extend(_inventory_errors(tenancy, tenancy_keys, "object-store tenancy"))
    if (
        tenancy.get("isolation_mode") != "bucket_prefix_and_provider_policy"
        or "{tenant_id}" not in str(tenancy.get("tenant_prefix_template", ""))
        or tenancy.get("cross_tenant_denial_required") is not True
        or tenancy.get("public_access_blocked") is not True
    ):
        errors.append("object-store tenancy baseline does not match")
    if tenancy.get("policy_reference") is not None and not _reference(
        tenancy.get("policy_reference")
    ):
        errors.append("object-store tenancy policy reference is invalid")

    operations = _mapping(profile.get("operations"))
    operations_keys = {
        "platform_owner",
        "security_owner",
        "storage_owner",
        "incident_owner",
        "audit_log_reference",
        "metrics_alert_reference",
        "availability_slo_percent",
        "latency_slo_ms",
        "runbook",
        "recovery_runbook",
        "rollback_runbook",
        "attestation_environment",
        "attestation_policy_reference",
    }
    errors.extend(_inventory_errors(operations, operations_keys, "object-store operations"))
    for key in (
        "platform_owner",
        "security_owner",
        "storage_owner",
        "incident_owner",
        "audit_log_reference",
        "metrics_alert_reference",
        "attestation_policy_reference",
    ):
        if operations.get(key) is not None and not _reference(operations.get(key)):
            errors.append(f"object-store operations {key} is invalid")
    availability = operations.get("availability_slo_percent")
    if availability is not None and (
        not isinstance(availability, (int, float))
        or isinstance(availability, bool)
        or not 99.9 <= availability <= 100
    ):
        errors.append("object-store availability SLO is invalid")
    latency = operations.get("latency_slo_ms")
    if latency is not None and (
        not isinstance(latency, int) or isinstance(latency, bool) or not 1 <= latency <= 5000
    ):
        errors.append("object-store latency SLO is invalid")
    for name in ("runbook", "recovery_runbook", "rollback_runbook"):
        errors.extend(_runbook_errors(_mapping(operations.get(name)), name))
    if operations.get("attestation_environment") != PROTECTED_ENVIRONMENT:
        errors.append("object-store protected environment does not match")

    claims = _mapping(profile.get("claims"))
    errors.extend(_inventory_errors(claims, PROFILE_CLAIMS, "object-store claims"))
    for claim in PROFILE_CLAIMS:
        if claims.get(claim) is not False:
            errors.append(f"object-store profile may not self-assert {claim}")
    return errors


def _profile_blockers(profile: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    provider = _mapping(profile.get("provider"))
    if provider.get("decision_status") != "approved":
        blockers.append("provider.decision_status")
    required = {
        "provider": (
            "provider_type",
            "account_reference",
            "region",
            "endpoint",
            "bucket",
            "infrastructure_reference",
            "failure_domain_reference",
            "recovery_region",
        ),
        "identity": (
            "integration_mode",
            "workload_identity_reference",
            "kubernetes_service_account",
            "least_privilege_policy_reference",
            "bucket_policy_reference",
        ),
        "transport": (
            "endpoint",
            "private_connectivity_reference",
            "dns_policy_reference",
            "trust_bundle_reference",
            "certificate_policy_reference",
        ),
        "encryption": ("key_reference", "key_policy_reference", "rotation_days"),
        "durability": (
            "retention_policy_reference",
            "replication_policy_reference",
            "recovery_bucket_reference",
        ),
        "consistency": (
            "multipart_upload_cleanup_reference",
            "orphan_file_cleanup_reference",
        ),
        "tenancy": ("policy_reference",),
        "operations": (
            "platform_owner",
            "security_owner",
            "storage_owner",
            "incident_owner",
            "audit_log_reference",
            "metrics_alert_reference",
            "availability_slo_percent",
            "latency_slo_ms",
            "attestation_policy_reference",
        ),
    }
    for section, names in required.items():
        item = _mapping(profile.get(section))
        for name in names:
            value = item.get(name)
            if value is None or (isinstance(value, str) and _placeholder(value)):
                blockers.append(f"{section}.{name}")
    operations = _mapping(profile.get("operations"))
    for name in ("runbook", "recovery_runbook", "rollback_runbook"):
        runbook = _mapping(operations.get(name))
        for key in ("uri", "version"):
            value = runbook.get(key)
            if value is None or (isinstance(value, str) and _placeholder(value)):
                blockers.append(f"operations.{name}.{key}")
    return blockers


def _binding_fingerprints(profile: Mapping[str, Any]) -> dict[str, str]:
    return {
        f"{name}_fingerprint": recovery._canonical_sha256(
            dict(_mapping(profile.get(name)))
        )
        for name in BINDING_SECTIONS
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _attestation_errors(
    attestation: Mapping[str, Any],
    *,
    profile: Mapping[str, Any],
    profile_fingerprint: str,
    bindings: Mapping[str, str],
    now: datetime,
) -> list[str]:
    errors: list[str] = []
    expected_inventory = {
        "schema",
        "environment",
        "repository",
        "protected_environment",
        "source_revision",
        "profile_fingerprint",
        "local_evidence_fingerprint",
        "engine_versions",
        *bindings,
        "observed_at",
        "expires_at",
        "evidence_uri",
        "checks",
        "claims",
        "runbook_versions",
    }
    errors.extend(_inventory_errors(attestation, expected_inventory, "object-store attestation"))
    if _sensitive_paths(attestation):
        errors.append("object-store attestation contains credential-bearing fields")
    if (
        attestation.get("schema") != ATTESTATION_SCHEMA
        or attestation.get("environment") != ENVIRONMENT
        or attestation.get("repository") != REPOSITORY
        or attestation.get("protected_environment") != PROTECTED_ENVIRONMENT
    ):
        errors.append("object-store attestation authority does not match")
    if not SHA40_PATTERN.fullmatch(str(attestation.get("source_revision", ""))):
        errors.append("object-store attestation source revision is invalid")
    if attestation.get("profile_fingerprint") != profile_fingerprint:
        errors.append("object-store attestation does not bind the current profile")
    if (
        attestation.get("local_evidence_fingerprint")
        != LOCAL_EVIDENCE["evidence_fingerprint"]
        or dict(_mapping(attestation.get("engine_versions"))) != EXPECTED_ENGINES
    ):
        errors.append("object-store attestation dependency bindings do not match")
    for key, expected in bindings.items():
        if attestation.get(key) != expected:
            errors.append(f"object-store attestation binding does not match: {key}")
    observed = _parse_timestamp(attestation.get("observed_at"))
    expires = _parse_timestamp(attestation.get("expires_at"))
    if observed is None or observed > now or now - observed > timedelta(hours=24):
        errors.append("object-store attestation is outside the 24-hour freshness window")
    if (
        expires is None
        or expires <= now
        or observed is None
        or expires - observed > timedelta(days=7)
    ):
        errors.append("object-store attestation expiry is invalid")
    if not _production_https_url(attestation.get("evidence_uri")):
        errors.append("object-store attestation evidence URI is invalid")
    checks = _mapping(attestation.get("checks"))
    errors.extend(_inventory_errors(checks, EXPECTED_CHECKS, "object-store checks"))
    for check in EXPECTED_CHECKS:
        if checks.get(check) != "passed":
            errors.append(f"object-store attestation check did not pass: {check}")
    claims = _mapping(attestation.get("claims"))
    errors.extend(_inventory_errors(claims, PROFILE_CLAIMS, "object-store attestation claims"))
    for claim in PROFILE_CLAIMS - {"production_ready"}:
        if claims.get(claim) is not True:
            errors.append(f"object-store attestation claim did not pass: {claim}")
    if claims.get("production_ready") is not False:
        errors.append("object-store attestation may not claim overall production readiness")
    operations = _mapping(profile.get("operations"))
    expected_runbooks = {
        name: _mapping(operations.get(name)).get("version")
        for name in ("runbook", "recovery_runbook", "rollback_runbook")
    }
    if dict(_mapping(attestation.get("runbook_versions"))) != expected_runbooks:
        errors.append("object-store attestation runbook versions do not match")
    return errors


def _stable_report(
    *,
    profile_fingerprint: str | None,
    bindings: Mapping[str, str | None],
    profile_valid: bool,
    profile_errors: list[str],
    blockers: list[str],
    attestation_valid: bool,
    attestation_errors: list[str],
    attestation_fingerprint: str | None,
) -> dict[str, Any]:
    passed = profile_valid and not blockers and attestation_valid
    stable: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "environment": ENVIRONMENT,
        "profile_fingerprint": profile_fingerprint,
        "local_evidence_fingerprint": LOCAL_EVIDENCE["evidence_fingerprint"],
        "attestation_fingerprint": attestation_fingerprint,
        **bindings,
        "profile_valid": profile_valid,
        "profile_errors": profile_errors,
        "profile_blockers": blockers,
        "ready_for_protected_verification": profile_valid and not blockers,
        "attestation_valid": attestation_valid,
        "attestation_errors": attestation_errors,
        **{claim: passed for claim in REPORT_CLAIMS},
        "production_ready": False,
    }
    return {**stable, "report_fingerprint": recovery._canonical_sha256(stable)}


def build_object_store_readiness_report(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    attestation: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        profile = _load_yaml_object(profile_path.resolve())
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return _stable_report(
            profile_fingerprint=None,
            bindings={f"{name}_fingerprint": None for name in BINDING_SECTIONS},
            profile_valid=False,
            profile_errors=[f"object-store profile is invalid: {type(exc).__name__}"],
            blockers=[],
            attestation_valid=False,
            attestation_errors=["object-store profile is not ready for attestation"],
            attestation_fingerprint=None,
        )
    profile_errors = _profile_errors(profile)
    profile_valid = not profile_errors
    blockers = _profile_blockers(profile) if profile_valid else []
    profile_fingerprint = recovery._canonical_sha256(profile)
    bindings = _binding_fingerprints(profile)
    attestation_errors: list[str]
    attestation_valid = False
    attestation_fingerprint: str | None = None
    if attestation is None:
        attestation_errors = ["production object-store attestation is required"]
    elif not profile_valid or blockers:
        attestation_errors = ["object-store profile is not ready for attestation"]
    else:
        attestation_value = dict(attestation)
        attestation_fingerprint = recovery._canonical_sha256(attestation_value)
        attestation_errors = _attestation_errors(
            attestation_value,
            profile=profile,
            profile_fingerprint=profile_fingerprint,
            bindings=bindings,
            now=(now or datetime.now(UTC)).astimezone(UTC),
        )
        attestation_valid = not attestation_errors
    return _stable_report(
        profile_fingerprint=profile_fingerprint,
        bindings=bindings,
        profile_valid=profile_valid,
        profile_errors=profile_errors,
        blockers=blockers,
        attestation_valid=attestation_valid,
        attestation_errors=attestation_errors,
        attestation_fingerprint=attestation_fingerprint,
    )


def verify_report_integrity(report: Mapping[str, Any]) -> list[str]:
    errors = _inventory_errors(report, REPORT_INVENTORY, "object-store readiness report")
    stable = {key: value for key, value in report.items() if key != "report_fingerprint"}
    if report.get("report_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("object-store readiness report fingerprint does not match")
    if report.get("production_ready") is not False:
        errors.append("object-store gate may not claim overall production readiness")
    expected = (
        report.get("profile_valid") is True
        and report.get("ready_for_protected_verification") is True
        and report.get("attestation_valid") is True
    )
    for claim in REPORT_CLAIMS:
        if report.get(claim) is not expected:
            errors.append(f"object-store gate result is inconsistent: {claim}")
    if report.get("ready_for_protected_verification") is not (
        report.get("profile_valid") is True and not report.get("profile_blockers")
    ):
        errors.append("object-store readiness derivation is inconsistent")
    for key in (
        "profile_fingerprint",
        "local_evidence_fingerprint",
        *{f"{name}_fingerprint" for name in BINDING_SECTIONS},
    ):
        value = report.get(key)
        if value is not None and not SHA256_PATTERN.fullmatch(str(value)):
            errors.append(f"object-store report fingerprint field is invalid: {key}")
    return errors


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.add_argument("--output", type=Path)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    evaluate.add_argument("--attestation", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            report = _load_json_object(args.report)
            errors = verify_report_integrity(report)
            print(json.dumps({"verified": not errors, "errors": errors}, indent=2))
            return 0 if not errors else 1
        attestation = (
            _load_json_object(args.attestation) if args.command == "evaluate" else None
        )
        report = build_object_store_readiness_report(
            profile_path=args.profile,
            attestation=attestation,
        )
        _write_report(report, args.output)
        if args.command == "validate":
            return 0 if report["profile_valid"] else 1
        return 0 if report["production_object_store_gate_passed"] else 1
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"metadata fabric object-store gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
