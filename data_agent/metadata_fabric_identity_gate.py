"""Evaluate the fail-closed production Metadata Fabric identity gate.

The checked-in profile freezes the decisions and protected-environment checks
required to promote the local OpenMetadata and Gravitino identity rehearsals.
Missing decisions are explicit blockers. A production identity result requires
a fresh attestation bound to the exact profile and all derived bindings. This
module deploys nothing, accepts no credentials, and never claims that the whole
platform is production ready.
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


PROFILE_SCHEMA = "gda.metadata_fabric_identity_production_profile.v1"
ATTESTATION_SCHEMA = "gda.metadata_fabric_identity_attestation.v1"
REPORT_SCHEMA = "gda.metadata_fabric_identity_readiness_report.v1"
ENVIRONMENT = "production"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-identity.production.yaml"

EXPECTED_PROVIDERS = {"openmetadata": "1.13.1", "gravitino": "1.3.0"}
EXPECTED_LOCAL_EVIDENCE = {
    "openmetadata": {
        "path": "docs/evidence/metadata-fabric-provider-identity-2026-07-28.json",
        "evidence_fingerprint": (
            "61b6a3429ae948f563bfc2bd012d8b586be581704cec646fd5e74b991243f03f"
        ),
    },
    "gravitino": {
        "path": "docs/evidence/metadata-fabric-gravitino-identity-2026-07-28.json",
        "evidence_fingerprint": (
            "f0b0de1f80f079d43318937e0a0cc151a8546e9e307bef204738b1367f9b29fd"
        ),
    },
}
EXPECTED_AUTHORIZATION = {
    "openmetadata": {
        "mandatory_roles": ["DefaultBotRole"],
        "project_role": "GdaMetadataTableProjectionRole",
        "project_permissions": [{"resource": "table", "operations": ["Create"]}],
        "denied_probe": {"resource": "policy", "operation": "Create"},
    },
    "gravitino": {
        "role": "gda-table-projection",
        "securable_objects": [
            {
                "full_name": "lakehouse",
                "type": "CATALOG",
                "privileges": ["USE_CATALOG"],
            },
            {
                "full_name": "lakehouse.published",
                "type": "SCHEMA",
                "privileges": ["CREATE_TABLE", "USE_SCHEMA"],
            },
        ],
        "denied_probe": {"resource": "METALAKE", "operation": "CREATE_CATALOG"},
    },
}
ALLOWED_INTEGRATION_MODES = {
    "openmetadata": {"provider_native_oidc", "identity_aware_proxy"},
    "gravitino": {"custom_oidc_authenticator", "identity_aware_proxy"},
}
ALLOWED_CATALOG_BACKENDS = {"iceberg_rest", "jdbc"}
EXPECTED_ATTESTATION_CHECKS = {
    "oidc_discovery",
    "token_exchange",
    "workload_subject_binding",
    "tenant_claim_binding",
    "openmetadata_authenticated_allow",
    "openmetadata_administrative_deny",
    "gravitino_authenticated_allow",
    "gravitino_administrative_deny",
    "provider_direct_access_denied",
    "static_credential_absence",
    "credential_rotation",
    "credential_revocation",
    "tls_transport",
    "mtls_internal_hops",
    "persistent_catalog_restart",
    "cross_tenant_denial",
    "audit_log_delivery",
    "rollback_rehearsal",
}
EXPECTED_CLAIMS = {
    "identity_decision_frozen",
    "provider_minimum_privilege_verified",
    "protected_workload_identity_verified",
    "oidc_verified",
    "tls_verified",
    "credential_rotation_verified",
    "credential_revocation_verified",
    "persistent_catalog_identity_binding_verified",
    "production_identity_verified",
    "production_identity_gate_passed",
    "production_ready",
}
REPORT_CLAIMS = {
    "provider_minimum_privilege_verified",
    "protected_workload_identity_verified",
    "oidc_verified",
    "tls_verified",
    "credential_rotation_verified",
    "credential_revocation_verified",
    "persistent_catalog_identity_binding_verified",
    "production_identity_verified",
    "production_identity_gate_passed",
}
REPORT_INVENTORY = {
    "schema",
    "environment",
    "profile_fingerprint",
    "attestation_fingerprint",
    "federation_fingerprint",
    "provider_bindings_fingerprint",
    "authorization_fingerprint",
    "tls_fingerprint",
    "catalog_fingerprint",
    "tenancy_fingerprint",
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
DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
REFERENCE_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$", re.IGNORECASE)
PINNED_OCI_PATTERN = re.compile(r"^oci://[^\s@]+@sha256:[0-9a-f]{64}$")
PLACEHOLDER_PATTERN = re.compile(
    r"(^|[-_.:/])(pending|placeholder|replace|tbd|todo|changeme)([-_.:/]|$)|"
    r"[<>]|\.example(?=[:/]|$)",
    re.IGNORECASE,
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[-_.])(password|passwd|secret|client[-_.]?secret|private[-_.]?key|"
    r"access[-_.]?key|access[-_.]?token|refresh[-_.]?token|id[-_.]?token|"
    r"authorization[-_.]?header)($|[-_.])",
    re.IGNORECASE,
)


class MetadataFabricIdentityGateError(RuntimeError):
    """The production identity readiness contract failed closed."""


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
            key_text = str(key)
            child = (*path, key_text)
            if SENSITIVE_KEY_PATTERN.search(key_text):
                found.append(".".join(child))
            found.extend(_sensitive_paths(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_sensitive_paths(nested, (*path, str(index))))
    return found


def _local_evidence_errors(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(
        _inventory_errors(value, set(EXPECTED_LOCAL_EVIDENCE), "local evidence")
    )
    for provider, expected in EXPECTED_LOCAL_EVIDENCE.items():
        item = _mapping(value.get(provider))
        errors.extend(
            _inventory_errors(
                item, {"path", "evidence_fingerprint"}, f"{provider} local evidence"
            )
        )
        if dict(item) != expected:
            errors.append(f"{provider} local identity evidence binding does not match")
            continue
        path = (REPO_ROOT / expected["path"]).resolve()
        try:
            path.relative_to(REPO_ROOT)
            evidence = _load_json_object(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            errors.append(f"{provider} local identity evidence is unavailable")
            continue
        if evidence.get("evidence_fingerprint") != expected["evidence_fingerprint"]:
            errors.append(f"{provider} local identity evidence fingerprint drifted")
        if evidence.get("production_identity_verified") is not False:
            errors.append(f"{provider} local evidence overclaims production identity")
        if provider == "openmetadata":
            if (
                evidence.get("local_openmetadata_bounded_identity_verified") is not True
                or evidence.get("local_openmetadata_minimum_privilege_verified") is not True
            ):
                errors.append("OpenMetadata local identity evidence is not verified")
        elif (
            evidence.get("local_gravitino_basic_identity_verified") is not True
            or evidence.get("local_gravitino_minimum_privilege_verified") is not True
        ):
            errors.append("Gravitino local identity evidence is not verified")
    return errors


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if _sensitive_paths(profile):
        errors.append("identity profile contains credential-bearing fields")
    errors.extend(
        _inventory_errors(
            profile,
            {
                "schema",
                "environment",
                "scope",
                "federation",
                "providers",
                "authorization",
                "tls",
                "catalog",
                "tenancy",
                "operations",
                "claims",
            },
            "identity profile",
        )
    )
    if profile.get("schema") != PROFILE_SCHEMA or profile.get("environment") != ENVIRONMENT:
        errors.append("identity profile schema or environment does not match")

    scope = _mapping(profile.get("scope"))
    errors.extend(
        _inventory_errors(scope, {"providers", "local_evidence"}, "identity scope")
    )
    providers = _mapping(scope.get("providers"))
    if set(providers) != set(EXPECTED_PROVIDERS):
        errors.append("identity provider version inventory does not match")
    for provider, version in EXPECTED_PROVIDERS.items():
        if _mapping(providers.get(provider)) != {"version": version}:
            errors.append(f"{provider} version binding does not match")
    errors.extend(_local_evidence_errors(_mapping(scope.get("local_evidence"))))

    federation = _mapping(profile.get("federation"))
    federation_keys = {
        "decision_status",
        "issuer",
        "discovery_uri",
        "jwks_uri",
        "audience",
        "token_exchange_mode",
        "trust_policy_reference",
        "workload_subject_claim",
        "tenant_claim",
        "maximum_token_ttl_seconds",
    }
    errors.extend(_inventory_errors(federation, federation_keys, "identity federation"))
    if federation.get("decision_status") not in {"pending", "approved"}:
        errors.append("identity federation decision status is invalid")
    for key in ("issuer", "discovery_uri", "jwks_uri"):
        value = federation.get(key)
        if value is not None and not _production_https_url(value):
            errors.append(f"identity federation {key} is not a production HTTPS URL")
    for key in ("audience", "trust_policy_reference"):
        value = federation.get(key)
        if value is not None and not _reference(value):
            errors.append(f"identity federation {key} is invalid")
    if federation.get("token_exchange_mode") not in {
        None,
        "oidc_workload_federation",
    }:
        errors.append("identity token exchange mode is invalid")
    if federation.get("workload_subject_claim") != "sub":
        errors.append("identity workload subject claim must remain sub")
    if federation.get("tenant_claim") != "gda_tenant_id":
        errors.append("identity tenant claim must remain gda_tenant_id")
    maximum_ttl = federation.get("maximum_token_ttl_seconds")
    if (
        not isinstance(maximum_ttl, int)
        or isinstance(maximum_ttl, bool)
        or not 300 <= maximum_ttl <= 900
    ):
        errors.append("identity maximum token TTL must be between 300 and 900 seconds")

    provider_bindings = _mapping(profile.get("providers"))
    errors.extend(
        _inventory_errors(provider_bindings, set(EXPECTED_PROVIDERS), "provider binding")
    )
    provider_keys = {
        "integration_mode",
        "authentication_component_reference",
        "environment_binding",
        "workload_identity_reference",
        "kubernetes_service_account",
        "namespace_template",
        "direct_access_policy",
        "credential_delivery",
        "static_credentials_forbidden",
        "rotation_mode",
        "revocation_mode",
    }
    for provider in EXPECTED_PROVIDERS:
        item = _mapping(provider_bindings.get(provider))
        errors.extend(_inventory_errors(item, provider_keys, f"{provider} identity binding"))
        mode = item.get("integration_mode")
        if mode is not None and mode not in ALLOWED_INTEGRATION_MODES[provider]:
            errors.append(f"{provider} identity integration mode is invalid")
        component = item.get("authentication_component_reference")
        if component is not None and not PINNED_OCI_PATTERN.fullmatch(str(component)):
            errors.append(f"{provider} authentication component must be digest-pinned OCI")
        for key in ("environment_binding", "workload_identity_reference"):
            value = item.get(key)
            if value is not None and not _reference(value):
                errors.append(f"{provider} {key} is invalid")
        service_account = item.get("kubernetes_service_account")
        if service_account is not None and not DNS_LABEL_PATTERN.fullmatch(
            str(service_account)
        ):
            errors.append(f"{provider} Kubernetes ServiceAccount is invalid")
        namespace = item.get("namespace_template")
        if namespace is not None and (
            _placeholder(namespace) or "{tenant_id}" not in str(namespace)
        ):
            errors.append(f"{provider} namespace template must bind tenant_id")
        expected_static = {
            "direct_access_policy": "deny_except_attested_identity_path",
            "credential_delivery": "short_lived_token_exchange",
            "static_credentials_forbidden": True,
            "rotation_mode": "automatic_before_expiry",
            "revocation_mode": "idp_subject_disable",
        }
        for key, expected in expected_static.items():
            if item.get(key) != expected:
                errors.append(f"{provider} identity control does not match: {key}")

    if _mapping(profile.get("authorization")) != EXPECTED_AUTHORIZATION:
        errors.append("provider minimum-privilege authorization contract does not match")

    tls = _mapping(profile.get("tls"))
    tls_keys = {
        "required",
        "minimum_version",
        "openmetadata_endpoint",
        "gravitino_endpoint",
        "trust_bundle_reference",
        "certificate_policy_reference",
        "mtls_for_internal_hops",
    }
    errors.extend(_inventory_errors(tls, tls_keys, "identity TLS"))
    if (
        tls.get("required") is not True
        or tls.get("minimum_version") not in {"TLSv1.2", "TLSv1.3"}
        or tls.get("mtls_for_internal_hops") is not True
    ):
        errors.append("identity TLS baseline does not match")
    for key in ("openmetadata_endpoint", "gravitino_endpoint"):
        value = tls.get(key)
        if value is not None and not _production_https_url(value):
            errors.append(f"identity TLS {key} is invalid")
    for key in ("trust_bundle_reference", "certificate_policy_reference"):
        value = tls.get(key)
        if value is not None and not _reference(value):
            errors.append(f"identity TLS {key} is invalid")
    if (
        tls.get("openmetadata_endpoint") is not None
        and tls.get("openmetadata_endpoint") == tls.get("gravitino_endpoint")
    ):
        errors.append("metadata providers must have distinct TLS endpoints")

    catalog = _mapping(profile.get("catalog"))
    catalog_keys = {
        "decision_status",
        "gravitino_backend",
        "catalog_reference",
        "persistence_reference",
        "backup_policy_reference",
        "persistent_required",
    }
    errors.extend(_inventory_errors(catalog, catalog_keys, "identity catalog"))
    if catalog.get("decision_status") not in {"pending", "approved"}:
        errors.append("identity catalog decision status is invalid")
    if catalog.get("gravitino_backend") not in {None, *ALLOWED_CATALOG_BACKENDS}:
        errors.append("production Gravitino catalog backend is invalid")
    for key in ("catalog_reference", "persistence_reference", "backup_policy_reference"):
        value = catalog.get(key)
        if value is not None and not _reference(value):
            errors.append(f"production catalog {key} is invalid")
    if catalog.get("persistent_required") is not True:
        errors.append("production Gravitino catalog must require persistence")

    tenancy = _mapping(profile.get("tenancy"))
    tenancy_keys = {
        "isolation_mode",
        "policy_reference",
        "tenant_claim",
        "cross_tenant_denial_required",
    }
    errors.extend(_inventory_errors(tenancy, tenancy_keys, "identity tenancy"))
    if tenancy.get("isolation_mode") not in {None, "namespace_and_provider_policy"}:
        errors.append("identity tenant isolation mode is invalid")
    if tenancy.get("policy_reference") is not None and not _reference(
        tenancy.get("policy_reference")
    ):
        errors.append("identity tenant policy reference is invalid")
    if (
        tenancy.get("tenant_claim") != "gda_tenant_id"
        or tenancy.get("cross_tenant_denial_required") is not True
    ):
        errors.append("identity tenant contract does not match")

    operations = _mapping(profile.get("operations"))
    operation_keys = {
        "identity_owner",
        "security_owner",
        "incident_owner",
        "audit_log_reference",
        "rotation_slo_minutes",
        "revocation_slo_minutes",
        "runbook",
        "rollback_runbook",
    }
    errors.extend(_inventory_errors(operations, operation_keys, "identity operations"))
    for key in ("identity_owner", "security_owner", "incident_owner", "audit_log_reference"):
        value = operations.get(key)
        if value is not None and not _reference(value):
            errors.append(f"identity operations {key} is invalid")
    for key, maximum in (("rotation_slo_minutes", 60), ("revocation_slo_minutes", 15)):
        value = operations.get(key)
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= maximum
        ):
            errors.append(f"identity operations {key} is invalid")
    for name in ("runbook", "rollback_runbook"):
        runbook = _mapping(operations.get(name))
        errors.extend(_inventory_errors(runbook, {"uri", "version"}, name))
        if runbook.get("uri") is not None and not _production_https_url(
            runbook.get("uri")
        ):
            errors.append(f"identity {name} URI is invalid")
        if runbook.get("version") is not None and _placeholder(runbook.get("version")):
            errors.append(f"identity {name} version is invalid")

    claims = _mapping(profile.get("claims"))
    errors.extend(_inventory_errors(claims, EXPECTED_CLAIMS, "identity claim"))
    for claim in sorted(EXPECTED_CLAIMS):
        if claims.get(claim) is not False:
            errors.append(f"identity profile may not self-assert production claim: {claim}")
    return errors


def _profile_blockers(profile: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    federation = _mapping(profile.get("federation"))
    if federation.get("decision_status") != "approved":
        blockers.append("federation.decision_status")
    for key in (
        "issuer",
        "discovery_uri",
        "jwks_uri",
        "audience",
        "token_exchange_mode",
        "trust_policy_reference",
    ):
        if federation.get(key) is None:
            blockers.append(f"federation.{key}")

    providers = _mapping(profile.get("providers"))
    for provider in EXPECTED_PROVIDERS:
        item = _mapping(providers.get(provider))
        for key in (
            "integration_mode",
            "authentication_component_reference",
            "environment_binding",
            "workload_identity_reference",
            "kubernetes_service_account",
            "namespace_template",
        ):
            if item.get(key) is None:
                blockers.append(f"providers.{provider}.{key}")

    tls = _mapping(profile.get("tls"))
    for key in (
        "openmetadata_endpoint",
        "gravitino_endpoint",
        "trust_bundle_reference",
        "certificate_policy_reference",
    ):
        if tls.get(key) is None:
            blockers.append(f"tls.{key}")

    catalog = _mapping(profile.get("catalog"))
    if catalog.get("decision_status") != "approved":
        blockers.append("catalog.decision_status")
    for key in (
        "gravitino_backend",
        "catalog_reference",
        "persistence_reference",
        "backup_policy_reference",
    ):
        if catalog.get(key) is None:
            blockers.append(f"catalog.{key}")

    tenancy = _mapping(profile.get("tenancy"))
    for key in ("isolation_mode", "policy_reference"):
        if tenancy.get(key) is None:
            blockers.append(f"tenancy.{key}")

    operations = _mapping(profile.get("operations"))
    for key in (
        "identity_owner",
        "security_owner",
        "incident_owner",
        "audit_log_reference",
        "rotation_slo_minutes",
        "revocation_slo_minutes",
    ):
        if operations.get(key) is None:
            blockers.append(f"operations.{key}")
    for name in ("runbook", "rollback_runbook"):
        runbook = _mapping(operations.get(name))
        for key in ("uri", "version"):
            if runbook.get(key) is None:
                blockers.append(f"operations.{name}.{key}")
    return blockers


def _binding_fingerprints(profile: Mapping[str, Any]) -> dict[str, str]:
    return {
        "federation_fingerprint": recovery._canonical_sha256(
            _mapping(profile.get("federation"))
        ),
        "provider_bindings_fingerprint": recovery._canonical_sha256(
            _mapping(profile.get("providers"))
        ),
        "authorization_fingerprint": recovery._canonical_sha256(
            _mapping(profile.get("authorization"))
        ),
        "tls_fingerprint": recovery._canonical_sha256(_mapping(profile.get("tls"))),
        "catalog_fingerprint": recovery._canonical_sha256(
            _mapping(profile.get("catalog"))
        ),
        "tenancy_fingerprint": recovery._canonical_sha256(
            _mapping(profile.get("tenancy"))
        ),
    }


def _attestation_errors(
    attestation: Mapping[str, Any] | None,
    *,
    profile: Mapping[str, Any],
    profile_fingerprint: str,
    bindings: Mapping[str, str],
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    if attestation is None:
        return ["production identity attestation is missing"]
    errors: list[str] = []
    if _sensitive_paths(attestation):
        errors.append("identity attestation contains credential-bearing fields")
    expected_inventory = {
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
        "local_evidence_fingerprints",
        *bindings.keys(),
        "runbook_versions",
        "checks",
    }
    errors.extend(
        _inventory_errors(attestation, expected_inventory, "identity attestation")
    )
    if (
        attestation.get("schema") != ATTESTATION_SCHEMA
        or attestation.get("environment") != ENVIRONMENT
    ):
        errors.append("identity attestation schema or environment does not match")
    if attestation.get("profile_fingerprint") != profile_fingerprint:
        errors.append("identity attestation is not bound to the current profile")
    if not SHA40_PATTERN.fullmatch(str(attestation.get("source_revision") or "")):
        errors.append("identity attestation source revision is invalid")
    if attestation.get("protected_environment") != ENVIRONMENT:
        errors.append("identity attestation did not run in protected production")
    if not _reference(attestation.get("verifier_identity")):
        errors.append("identity attestation verifier identity is invalid")
    if not _production_https_url(attestation.get("evidence_uri")):
        errors.append("identity attestation evidence URI is invalid")

    try:
        observed_at = datetime.fromisoformat(str(attestation.get("observed_at")))
        expires_at = datetime.fromisoformat(str(attestation.get("expires_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError
        age = now - observed_at
        if age < timedelta(seconds=-30) or age > max_age:
            errors.append("identity attestation is outside the accepted freshness window")
        if expires_at <= now or expires_at <= observed_at:
            errors.append("identity attestation has expired or has invalid expiry")
        if expires_at - observed_at > timedelta(days=7):
            errors.append("identity attestation validity exceeds seven days")
    except ValueError:
        errors.append("identity attestation timestamps are invalid")

    if _mapping(attestation.get("provider_versions")) != EXPECTED_PROVIDERS:
        errors.append("identity attestation provider versions do not match")
    local_fingerprints = {
        provider: item["evidence_fingerprint"]
        for provider, item in EXPECTED_LOCAL_EVIDENCE.items()
    }
    if _mapping(attestation.get("local_evidence_fingerprints")) != local_fingerprints:
        errors.append("identity attestation local evidence bindings do not match")
    for key, fingerprint in bindings.items():
        if attestation.get(key) != fingerprint:
            errors.append(f"identity attestation binding does not match: {key}")
    operations = _mapping(profile.get("operations"))
    expected_runbooks = {
        name: _mapping(operations.get(name)).get("version")
        for name in ("runbook", "rollback_runbook")
    }
    if _mapping(attestation.get("runbook_versions")) != expected_runbooks:
        errors.append("identity attestation runbook versions do not match")
    checks = _mapping(attestation.get("checks"))
    if set(checks) != EXPECTED_ATTESTATION_CHECKS:
        errors.append("identity attestation check inventory does not match")
    for check in sorted(EXPECTED_ATTESTATION_CHECKS):
        if checks.get(check) != "passed":
            errors.append(f"identity attestation check did not pass: {check}")
    return errors


def _invalid_report(error: str) -> dict[str, Any]:
    stable: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "environment": ENVIRONMENT,
        "profile_fingerprint": None,
        "attestation_fingerprint": None,
        "federation_fingerprint": None,
        "provider_bindings_fingerprint": None,
        "authorization_fingerprint": None,
        "tls_fingerprint": None,
        "catalog_fingerprint": None,
        "tenancy_fingerprint": None,
        "profile_valid": False,
        "profile_errors": [error],
        "profile_blockers": [],
        "ready_for_protected_verification": False,
        "attestation_valid": False,
        "attestation_errors": ["production identity attestation is missing"],
        **{claim: False for claim in REPORT_CLAIMS},
        "production_ready": False,
    }
    return {**stable, "report_fingerprint": recovery._canonical_sha256(stable)}


def build_identity_readiness_report(
    *,
    profile_path: Path | None = None,
    attestation: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_attestation_age: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    """Build a deterministic identity readiness report."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricIdentityGateError(
            "identity readiness verification time must be timezone-aware"
        )
    if max_attestation_age <= timedelta(0):
        raise MetadataFabricIdentityGateError(
            "identity attestation freshness window must be positive"
        )
    path = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    try:
        profile = _load_yaml_object(path)
    except (OSError, TypeError, yaml.YAMLError) as exc:
        return _invalid_report(f"identity profile is invalid: {type(exc).__name__}")

    profile_fingerprint = recovery._canonical_sha256(profile)
    bindings = _binding_fingerprints(profile)
    profile_errors = _profile_errors(profile)
    profile_blockers = _profile_blockers(profile)
    profile_valid = not profile_errors
    ready_for_verification = profile_valid and not profile_blockers
    attestation_errors = _attestation_errors(
        attestation,
        profile=profile,
        profile_fingerprint=profile_fingerprint,
        bindings=bindings,
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
        **bindings,
        "profile_valid": profile_valid,
        "profile_errors": profile_errors,
        "profile_blockers": profile_blockers,
        "ready_for_protected_verification": ready_for_verification,
        "attestation_valid": attestation_valid,
        "attestation_errors": attestation_errors,
        **{claim: gate_passed for claim in REPORT_CLAIMS},
        "production_ready": False,
    }
    return {**stable, "report_fingerprint": recovery._canonical_sha256(stable)}


def verify_report_integrity(report: Mapping[str, Any]) -> list[str]:
    """Reject modified identity reports and overall production overclaims."""
    errors: list[str] = []
    if _sensitive_paths(report):
        errors.append("identity readiness report contains credential-bearing fields")
    errors.extend(_inventory_errors(report, REPORT_INVENTORY, "identity readiness report"))
    if report.get("schema") != REPORT_SCHEMA or report.get("environment") != ENVIRONMENT:
        errors.append("identity readiness report schema or environment does not match")
    stable = {key: value for key, value in report.items() if key != "report_fingerprint"}
    if report.get("report_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("identity readiness report fingerprint does not match")
    if report.get("production_ready") is not False:
        errors.append("identity gate may not claim overall production readiness")
    expected_gate = (
        report.get("profile_valid") is True
        and report.get("profile_blockers") == []
        and report.get("attestation_valid") is True
    )
    for claim in sorted(REPORT_CLAIMS):
        if report.get(claim) is not expected_gate:
            errors.append(f"identity gate result is inconsistent: {claim}")
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
    validate = subparsers.add_parser("validate")
    validate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    evaluate.add_argument("--attestation", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = build_identity_readiness_report(profile_path=args.profile)
            _write_report(report, None)
            return 0 if report["profile_valid"] else 1
        if args.command == "evaluate":
            attestation = _load_json_object(args.attestation)
            report = build_identity_readiness_report(
                profile_path=args.profile,
                attestation=attestation,
            )
            _write_report(report, args.output)
            return 0 if report["production_identity_gate_passed"] else 1
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
        MetadataFabricIdentityGateError,
    ) as exc:
        print(f"metadata identity gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
