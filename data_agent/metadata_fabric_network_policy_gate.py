"""Evaluate the fail-closed production NetworkPolicy readiness contract.

The checked-in profile records decisions required before Metadata Fabric
provider traffic can be protected in production. Missing decisions are valid
blockers. The gate passes only with a complete profile and a fresh,
profile-bound protected-environment attestation. It does not apply policies,
modify providers, or claim that the whole platform is production ready.
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

PROFILE_SCHEMA = "gda.metadata_fabric_network_policy_production_profile.v1"
ATTESTATION_SCHEMA = "gda.metadata_fabric_network_policy_attestation.v1"
REPORT_SCHEMA = "gda.metadata_fabric_network_policy_readiness_report.v1"
ENVIRONMENT = "production"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-network-policy.production.yaml"

EXPECTED_PROVIDERS = {
    "openmetadata": "1.13.1",
    "gravitino": "1.3.0",
}
EXPECTED_WORKLOADS = {
    "gda_control",
    "metadata_observability",
    "metadata_backup",
    "openmetadata",
    "gravitino",
    "openmetadata_postgresql",
    "gravitino_postgresql",
    "opensearch",
}
EXPECTED_IDENTITY_LABELS = {
    "app.kubernetes.io/name",
    "gda.openai.com/environment",
    "gda.openai.com/workload-identity",
}
ALLOWED_PRODUCTION_CNIS = {
    "antrea",
    "calico",
    "cilium",
    "cloud_managed",
}
EXPECTED_DNS_PORTS = [
    {"protocol": "UDP", "port": 53},
    {"protocol": "TCP", "port": 53},
]
EXPECTED_FLOWS = {
    "gda-control-to-openmetadata-api": (
        "gda_control",
        "openmetadata",
        [8585],
        "provider_api",
    ),
    "gda-control-to-gravitino-api": (
        "gda_control",
        "gravitino",
        [8090],
        "provider_api",
    ),
    "observability-to-openmetadata-metrics": (
        "metadata_observability",
        "openmetadata",
        [8586],
        "provider_metrics",
    ),
    "observability-to-gravitino-metrics": (
        "metadata_observability",
        "gravitino",
        [8090],
        "provider_metrics",
    ),
    "openmetadata-to-postgresql": (
        "openmetadata",
        "openmetadata_postgresql",
        [5432],
        "provider_database",
    ),
    "openmetadata-to-opensearch": (
        "openmetadata",
        "opensearch",
        [9200],
        "provider_search",
    ),
    "gravitino-to-postgresql": (
        "gravitino",
        "gravitino_postgresql",
        [5432],
        "provider_database",
    ),
    "backup-to-openmetadata-postgresql": (
        "metadata_backup",
        "openmetadata_postgresql",
        [5432],
        "backup_read",
    ),
    "backup-to-gravitino-postgresql": (
        "metadata_backup",
        "gravitino_postgresql",
        [5432],
        "backup_read",
    ),
    "backup-to-opensearch": (
        "metadata_backup",
        "opensearch",
        [9200],
        "backup_read",
    ),
}
EXPECTED_ATTESTATION_CHECKS = {
    "rendered_policy_validation",
    "cni_ingress_enforcement",
    "cni_egress_enforcement",
    "workload_identity_label_admission",
    "default_deny_ingress",
    "default_deny_egress",
    "allowed_provider_api_paths",
    "allowed_provider_storage_paths",
    "allowed_observability_paths",
    "allowed_backup_paths",
    "denied_unauthorized_workload",
    "denied_cross_tenant_ingress",
    "denied_cross_tenant_egress",
    "dns_resolution",
    "policy_log_delivery",
    "rollback_rehearsal",
    "provider_health_preserved",
}
EXPECTED_CLAIMS = {
    "cluster_decision_frozen",
    "workload_identity_matrix_verified",
    "provider_traffic_matrix_verified",
    "network_policy_logging_verified",
    "production_network_policy_gate_passed",
    "production_network_policy_enforcement_verified",
    "metadata_provider_network_policy_verified",
    "tenant_isolation_verified",
    "production_ready",
}
EXPECTED_REPORT_FIELDS = {
    "schema",
    "environment",
    "profile_fingerprint",
    "workload_bindings_fingerprint",
    "traffic_matrix_fingerprint",
    "attestation_fingerprint",
    "profile_valid",
    "profile_errors",
    "profile_blockers",
    "attestation_valid",
    "attestation_errors",
    "ready_for_protected_verification",
    "production_network_policy_gate_passed",
    "production_network_policy_enforcement_verified",
    "metadata_provider_network_policy_verified",
    "tenant_isolation_verified",
    "production_ready",
    "report_fingerprint",
}

SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SEMVER_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
OCI_REFERENCE_PATTERN = re.compile(r"^oci://[A-Za-z0-9.-]+(?::\d+)?/[^\s@]+@sha256:[0-9a-f]{64}$")
PLACEHOLDER_PATTERN = re.compile(
    r"(^|[-_.:/])(pending|placeholder|replace|tbd|todo|changeme)([-_.:/]|$)|"
    r"[<>]|\.example(?=[:/]|$)",
    re.IGNORECASE,
)


class MetadataFabricNetworkPolicyGateError(RuntimeError):
    """The production NetworkPolicy readiness contract failed closed."""


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
    return (
        not isinstance(value, str)
        or not value.strip()
        or bool(PLACEHOLDER_PATTERN.search(value.strip()))
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


def _reference(value: Any, scheme: str) -> bool:
    if _placeholder(value):
        return False
    text = str(value)
    parsed = urlparse(text)
    return (
        parsed.scheme == scheme
        and bool(parsed.netloc)
        and "@" not in parsed.netloc
        and not parsed.query
        and not parsed.fragment
        and not any(character.isspace() for character in text)
    )


def _inventory_errors(value: Mapping[str, Any], expected: set[str], name: str) -> list[str]:
    return [] if set(value) == expected else [f"{name} inventory does not match"]


def _selector_valid(value: Any) -> bool:
    selector = _mapping(value)
    return bool(selector) and all(
        isinstance(key, str)
        and isinstance(item, str)
        and not _placeholder(key)
        and not _placeholder(item)
        for key, item in selector.items()
    )


def _workload_errors(workloads: Mapping[str, Any]) -> list[str]:
    errors = _inventory_errors(workloads, EXPECTED_WORKLOADS, "workload binding")
    for name in sorted(EXPECTED_WORKLOADS):
        item = _mapping(workloads.get(name))
        errors.extend(
            _inventory_errors(
                item,
                {
                    "namespace_template",
                    "service_account",
                    "identity_reference",
                    "selector_labels",
                },
                f"workload {name}",
            )
        )
        namespace = item.get("namespace_template")
        if namespace is not None and (
            _placeholder(namespace) or "{tenant_id}" not in str(namespace)
        ):
            errors.append(f"workload {name} namespace template must bind tenant_id")
        service_account = item.get("service_account")
        if service_account is not None and (
            not isinstance(service_account, str)
            or len(service_account) > 63
            or not DNS_LABEL_PATTERN.fullmatch(service_account)
        ):
            errors.append(f"workload {name} service account is invalid")
        identity = item.get("identity_reference")
        if identity is not None and not _reference(identity, "identity"):
            errors.append(f"workload {name} identity reference is invalid")
        selector = _mapping(item.get("selector_labels"))
        if selector and (
            set(selector) != EXPECTED_IDENTITY_LABELS
            or not _selector_valid(selector)
            or selector.get("gda.openai.com/environment") != ENVIRONMENT
            or selector.get("gda.openai.com/workload-identity") != service_account
        ):
            errors.append(f"workload {name} selector identity does not match")
    return errors


def _traffic_errors(traffic: Mapping[str, Any]) -> list[str]:
    errors = _inventory_errors(traffic, {"decision_status", "entries"}, "traffic matrix")
    if traffic.get("decision_status") not in {"pending", "approved"}:
        errors.append("traffic matrix decision status is invalid")
    entries = traffic.get("entries")
    if not isinstance(entries, list):
        return [*errors, "traffic matrix entries must be a list"]
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        entry = _mapping(raw)
        errors.extend(
            _inventory_errors(
                entry,
                {
                    "id",
                    "source",
                    "destination",
                    "protocol",
                    "ports",
                    "purpose",
                    "tenant_scoped",
                },
                f"traffic flow {index}",
            )
        )
        flow_id = entry.get("id")
        if not isinstance(flow_id, str) or flow_id in seen:
            errors.append(f"traffic flow {index} identity is missing or duplicated")
            continue
        seen.add(flow_id)
        expected = EXPECTED_FLOWS.get(flow_id)
        if expected is None:
            errors.append(f"traffic flow is outside the approved baseline: {flow_id}")
            continue
        source, destination, ports, purpose = expected
        if (
            entry.get("source") != source
            or entry.get("destination") != destination
            or entry.get("protocol") != "TCP"
            or entry.get("ports") != ports
            or entry.get("purpose") != purpose
            or entry.get("tenant_scoped") is not True
        ):
            errors.append(f"traffic flow contract does not match: {flow_id}")
    return errors


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(profile):
        errors.append("NetworkPolicy profile contains credential-bearing fields")
    errors.extend(
        _inventory_errors(
            profile,
            {
                "schema",
                "environment",
                "scope",
                "cluster",
                "policy",
                "workloads",
                "tenancy",
                "traffic_matrix",
                "operations",
                "claims",
            },
            "NetworkPolicy profile",
        )
    )
    if profile.get("schema") != PROFILE_SCHEMA or profile.get("environment") != ENVIRONMENT:
        errors.append("NetworkPolicy profile schema or environment does not match")

    scope = _mapping(profile.get("scope"))
    providers = _mapping(scope.get("providers"))
    errors.extend(_inventory_errors(scope, {"providers"}, "provider scope"))
    errors.extend(_inventory_errors(providers, set(EXPECTED_PROVIDERS), "provider"))
    for provider, version in EXPECTED_PROVIDERS.items():
        item = _mapping(providers.get(provider))
        errors.extend(_inventory_errors(item, {"version"}, f"provider {provider}"))
        if item.get("version") != version:
            errors.append(f"{provider} version does not match the approved baseline")

    cluster = _mapping(profile.get("cluster"))
    errors.extend(
        _inventory_errors(
            cluster,
            {
                "decision_status",
                "cluster_reference",
                "kubernetes_version",
                "cni",
                "dns",
            },
            "NetworkPolicy cluster",
        )
    )
    if cluster.get("decision_status") not in {"pending", "approved"}:
        errors.append("NetworkPolicy cluster decision status is invalid")
    cluster_reference = cluster.get("cluster_reference")
    if cluster_reference is not None and not _reference(cluster_reference, "cluster"):
        errors.append("NetworkPolicy cluster reference is invalid")
    kubernetes_version = cluster.get("kubernetes_version")
    if kubernetes_version is not None and not SEMVER_PATTERN.fullmatch(str(kubernetes_version)):
        errors.append("Kubernetes version is invalid")

    cni = _mapping(cluster.get("cni"))
    errors.extend(
        _inventory_errors(
            cni,
            {
                "provider",
                "version",
                "policy_api",
                "ingress_enforcement_required",
                "egress_enforcement_required",
            },
            "CNI",
        )
    )
    if cni.get("provider") is not None and cni.get("provider") not in ALLOWED_PRODUCTION_CNIS:
        errors.append("production CNI provider is invalid")
    if cni.get("version") is not None and not SEMVER_PATTERN.fullmatch(str(cni.get("version"))):
        errors.append("production CNI version is invalid")
    if (
        cni.get("policy_api") != "networking.k8s.io/v1"
        or cni.get("ingress_enforcement_required") is not True
        or cni.get("egress_enforcement_required") is not True
    ):
        errors.append("CNI enforcement contract does not match")

    dns = _mapping(cluster.get("dns"))
    errors.extend(
        _inventory_errors(
            dns,
            {"provider", "namespace_selector", "pod_selector", "ports"},
            "cluster DNS",
        )
    )
    if dns.get("provider") is not None and _placeholder(dns.get("provider")):
        errors.append("cluster DNS provider is invalid")
    for key in ("namespace_selector", "pod_selector"):
        selector = _mapping(dns.get(key))
        if selector and not _selector_valid(selector):
            errors.append(f"cluster DNS {key} is invalid")
    if dns.get("ports") != EXPECTED_DNS_PORTS:
        errors.append("cluster DNS port inventory does not match")

    policy = _mapping(profile.get("policy"))
    errors.extend(
        _inventory_errors(
            policy,
            {
                "default_deny_ingress",
                "default_deny_egress",
                "selector_identity_mode",
                "required_identity_labels",
                "label_admission_policy_reference",
                "policy_bundle_reference",
                "policy_owner",
            },
            "NetworkPolicy policy",
        )
    )
    labels = policy.get("required_identity_labels")
    if (
        policy.get("default_deny_ingress") is not True
        or policy.get("default_deny_egress") is not True
        or policy.get("selector_identity_mode") != "admission_bound_workload_labels"
        or not isinstance(labels, list)
        or not all(isinstance(label, str) for label in labels)
        or set(labels) != EXPECTED_IDENTITY_LABELS
        or len(labels) != len(EXPECTED_IDENTITY_LABELS)
    ):
        errors.append("NetworkPolicy default-deny or identity contract does not match")
    admission = policy.get("label_admission_policy_reference")
    if admission is not None and not _reference(admission, "policy"):
        errors.append("workload label admission policy reference is invalid")
    bundle = policy.get("policy_bundle_reference")
    if bundle is not None and not OCI_REFERENCE_PATTERN.fullmatch(str(bundle)):
        errors.append("NetworkPolicy bundle reference must be digest-pinned OCI")
    owner = policy.get("policy_owner")
    if owner is not None and not _reference(owner, "team"):
        errors.append("NetworkPolicy owner is invalid")

    workloads = _mapping(profile.get("workloads"))
    errors.extend(_workload_errors(workloads))

    tenancy = _mapping(profile.get("tenancy"))
    errors.extend(
        _inventory_errors(
            tenancy,
            {
                "isolation_mode",
                "namespace_tenant_label",
                "namespace_label_admission_policy_reference",
                "cross_tenant_default_deny_required",
            },
            "NetworkPolicy tenancy",
        )
    )
    if tenancy.get("isolation_mode") not in {None, "namespace_per_tenant"}:
        errors.append("NetworkPolicy tenant isolation mode is invalid")
    if (
        tenancy.get("namespace_tenant_label") != "gda.openai.com/tenant-id"
        or tenancy.get("cross_tenant_default_deny_required") is not True
    ):
        errors.append("NetworkPolicy tenant isolation contract does not match")
    namespace_admission = tenancy.get("namespace_label_admission_policy_reference")
    if namespace_admission is not None and not _reference(namespace_admission, "policy"):
        errors.append("namespace label admission policy reference is invalid")

    traffic = _mapping(profile.get("traffic_matrix"))
    errors.extend(_traffic_errors(traffic))

    operations = _mapping(profile.get("operations"))
    errors.extend(
        _inventory_errors(
            operations,
            {
                "policy_log_reference",
                "incident_owner",
                "runbook",
                "rollback_runbook",
            },
            "NetworkPolicy operations",
        )
    )
    log_reference = operations.get("policy_log_reference")
    if log_reference is not None and not _reference(log_reference, "logging"):
        errors.append("NetworkPolicy log reference is invalid")
    incident_owner = operations.get("incident_owner")
    if incident_owner is not None and not _reference(incident_owner, "team"):
        errors.append("NetworkPolicy incident owner is invalid")
    for key in ("runbook", "rollback_runbook"):
        runbook = _mapping(operations.get(key))
        errors.extend(_inventory_errors(runbook, {"uri", "version"}, key.replace("_", " ")))
        if runbook.get("uri") is not None and not _production_https_url(runbook.get("uri")):
            errors.append(f"NetworkPolicy {key} URI is invalid")
        if runbook.get("version") is not None and _placeholder(runbook.get("version")):
            errors.append(f"NetworkPolicy {key} version is invalid")

    claims = _mapping(profile.get("claims"))
    errors.extend(_inventory_errors(claims, EXPECTED_CLAIMS, "NetworkPolicy claim"))
    for claim in sorted(EXPECTED_CLAIMS):
        if claims.get(claim) is not False:
            errors.append(f"profile may not self-assert production claim: {claim}")
    return errors


def _profile_blockers(profile: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    cluster = _mapping(profile.get("cluster"))
    if cluster.get("decision_status") != "approved":
        blockers.append("cluster.decision_status")
    if not _reference(cluster.get("cluster_reference"), "cluster"):
        blockers.append("cluster.cluster_reference")
    if not SEMVER_PATTERN.fullmatch(str(cluster.get("kubernetes_version") or "")):
        blockers.append("cluster.kubernetes_version")
    cni = _mapping(cluster.get("cni"))
    if cni.get("provider") not in ALLOWED_PRODUCTION_CNIS:
        blockers.append("cluster.cni.provider")
    if not SEMVER_PATTERN.fullmatch(str(cni.get("version") or "")):
        blockers.append("cluster.cni.version")
    dns = _mapping(cluster.get("dns"))
    if _placeholder(dns.get("provider")):
        blockers.append("cluster.dns.provider")
    for key in ("namespace_selector", "pod_selector"):
        if not _selector_valid(dns.get(key)):
            blockers.append(f"cluster.dns.{key}")

    policy = _mapping(profile.get("policy"))
    if not _reference(policy.get("label_admission_policy_reference"), "policy"):
        blockers.append("policy.label_admission_policy_reference")
    if not OCI_REFERENCE_PATTERN.fullmatch(str(policy.get("policy_bundle_reference") or "")):
        blockers.append("policy.policy_bundle_reference")
    if not _reference(policy.get("policy_owner"), "team"):
        blockers.append("policy.policy_owner")

    workloads = _mapping(profile.get("workloads"))
    for name in sorted(EXPECTED_WORKLOADS):
        item = _mapping(workloads.get(name))
        if "{tenant_id}" not in str(item.get("namespace_template") or ""):
            blockers.append(f"workloads.{name}.namespace_template")
        service_account = item.get("service_account")
        if not isinstance(service_account, str) or not DNS_LABEL_PATTERN.fullmatch(service_account):
            blockers.append(f"workloads.{name}.service_account")
        if not _reference(item.get("identity_reference"), "identity"):
            blockers.append(f"workloads.{name}.identity_reference")
        if not _selector_valid(item.get("selector_labels")):
            blockers.append(f"workloads.{name}.selector_labels")

    tenancy = _mapping(profile.get("tenancy"))
    if tenancy.get("isolation_mode") != "namespace_per_tenant":
        blockers.append("tenancy.isolation_mode")
    if not _reference(tenancy.get("namespace_label_admission_policy_reference"), "policy"):
        blockers.append("tenancy.namespace_label_admission_policy_reference")

    traffic = _mapping(profile.get("traffic_matrix"))
    if traffic.get("decision_status") != "approved":
        blockers.append("traffic_matrix.decision_status")
    entries = traffic.get("entries")
    observed_flows = {
        str(_mapping(entry).get("id")) for entry in (entries if isinstance(entries, list) else [])
    }
    for flow_id in EXPECTED_FLOWS:
        if flow_id not in observed_flows:
            blockers.append(f"traffic_matrix.entries.{flow_id}")

    operations = _mapping(profile.get("operations"))
    if not _reference(operations.get("policy_log_reference"), "logging"):
        blockers.append("operations.policy_log_reference")
    if not _reference(operations.get("incident_owner"), "team"):
        blockers.append("operations.incident_owner")
    for key in ("runbook", "rollback_runbook"):
        runbook = _mapping(operations.get(key))
        if not _production_https_url(runbook.get("uri")):
            blockers.append(f"operations.{key}.uri")
        if _placeholder(runbook.get("version")):
            blockers.append(f"operations.{key}.version")
    return blockers


def _cluster_binding(profile: Mapping[str, Any]) -> dict[str, Any]:
    cluster = _mapping(profile.get("cluster"))
    return {
        "cluster_reference": cluster.get("cluster_reference"),
        "kubernetes_version": cluster.get("kubernetes_version"),
        "cni": dict(_mapping(cluster.get("cni"))),
        "dns": dict(_mapping(cluster.get("dns"))),
    }


def _runbook_versions(profile: Mapping[str, Any]) -> dict[str, Any]:
    operations = _mapping(profile.get("operations"))
    return {
        "runbook": _mapping(operations.get("runbook")).get("version"),
        "rollback_runbook": _mapping(operations.get("rollback_runbook")).get("version"),
    }


def _policy_bundle_digest(profile: Mapping[str, Any]) -> str | None:
    reference = _mapping(profile.get("policy")).get("policy_bundle_reference")
    if not isinstance(reference, str) or "@sha256:" not in reference:
        return None
    return reference.rsplit("@sha256:", maxsplit=1)[1]


def _attestation_errors(
    attestation: Mapping[str, Any] | None,
    *,
    profile: Mapping[str, Any],
    profile_fingerprint: str,
    workload_fingerprint: str,
    traffic_fingerprint: str,
    now: datetime,
    max_age: timedelta,
) -> list[str]:
    if attestation is None:
        return ["production NetworkPolicy attestation is missing"]
    errors: list[str] = []
    if recovery._sensitive_paths(attestation):
        errors.append("NetworkPolicy attestation contains credential-bearing fields")
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
                "cluster_binding",
                "policy_bundle_digest",
                "workload_bindings_fingerprint",
                "traffic_matrix_fingerprint",
                "runbook_versions",
                "checks",
            },
            "NetworkPolicy attestation",
        )
    )
    if (
        attestation.get("schema") != ATTESTATION_SCHEMA
        or attestation.get("environment") != ENVIRONMENT
    ):
        errors.append("NetworkPolicy attestation schema or environment does not match")
    if attestation.get("profile_fingerprint") != profile_fingerprint:
        errors.append("NetworkPolicy attestation is not bound to the current profile")
    if not SHA40_PATTERN.fullmatch(str(attestation.get("source_revision") or "")):
        errors.append("NetworkPolicy attestation source revision is invalid")
    if attestation.get("protected_environment") != ENVIRONMENT:
        errors.append(
            "NetworkPolicy attestation did not run in the protected production environment"
        )
    if not _reference(attestation.get("verifier_identity"), "identity"):
        errors.append("NetworkPolicy attestation verifier identity is invalid")
    if not _production_https_url(attestation.get("evidence_uri")):
        errors.append("NetworkPolicy attestation evidence URI is invalid")

    try:
        observed_at = datetime.fromisoformat(str(attestation.get("observed_at")))
        expires_at = datetime.fromisoformat(str(attestation.get("expires_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError
        age = now - observed_at
        if age < timedelta(seconds=-30) or age > max_age:
            errors.append("NetworkPolicy attestation is outside the freshness window")
        if expires_at <= now or expires_at <= observed_at:
            errors.append("NetworkPolicy attestation has expired or has invalid expiry")
        if expires_at - observed_at > timedelta(days=7):
            errors.append("NetworkPolicy attestation validity exceeds seven days")
    except ValueError:
        errors.append("NetworkPolicy attestation timestamps are invalid")

    if _mapping(attestation.get("provider_versions")) != EXPECTED_PROVIDERS:
        errors.append("NetworkPolicy attestation provider versions do not match")
    if _mapping(attestation.get("cluster_binding")) != _cluster_binding(profile):
        errors.append("NetworkPolicy attestation cluster binding does not match")
    if attestation.get("policy_bundle_digest") != _policy_bundle_digest(profile):
        errors.append("NetworkPolicy attestation policy bundle does not match")
    if attestation.get("workload_bindings_fingerprint") != workload_fingerprint:
        errors.append("NetworkPolicy attestation workload bindings do not match")
    if attestation.get("traffic_matrix_fingerprint") != traffic_fingerprint:
        errors.append("NetworkPolicy attestation traffic matrix does not match")
    if _mapping(attestation.get("runbook_versions")) != _runbook_versions(profile):
        errors.append("NetworkPolicy attestation runbook versions do not match")
    checks = _mapping(attestation.get("checks"))
    if set(checks) != EXPECTED_ATTESTATION_CHECKS:
        errors.append("NetworkPolicy attestation check inventory does not match")
    for check in sorted(EXPECTED_ATTESTATION_CHECKS):
        if checks.get(check) != "passed":
            errors.append(f"NetworkPolicy attestation check did not pass: {check}")
    return errors


def build_network_policy_readiness_report(
    *,
    profile_path: Path | None = None,
    attestation: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_attestation_age: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    """Build a deterministic readiness result from profile and optional evidence."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricNetworkPolicyGateError(
            "NetworkPolicy verification time must be timezone-aware"
        )
    if max_attestation_age <= timedelta(0):
        raise MetadataFabricNetworkPolicyGateError(
            "NetworkPolicy attestation freshness window must be positive"
        )
    path = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    try:
        profile = _load_yaml_object(path)
    except (OSError, TypeError, yaml.YAMLError) as exc:
        stable = {
            "schema": REPORT_SCHEMA,
            "environment": ENVIRONMENT,
            "profile_fingerprint": None,
            "workload_bindings_fingerprint": None,
            "traffic_matrix_fingerprint": None,
            "attestation_fingerprint": None,
            "profile_valid": False,
            "profile_errors": [f"NetworkPolicy profile is invalid: {type(exc).__name__}"],
            "profile_blockers": [],
            "attestation_valid": False,
            "attestation_errors": ["production NetworkPolicy attestation is missing"],
            "ready_for_protected_verification": False,
            "production_network_policy_gate_passed": False,
            "production_network_policy_enforcement_verified": False,
            "metadata_provider_network_policy_verified": False,
            "tenant_isolation_verified": False,
            "production_ready": False,
        }
        return {**stable, "report_fingerprint": recovery._canonical_sha256(stable)}

    profile_fingerprint = recovery._canonical_sha256(profile)
    workload_fingerprint = recovery._canonical_sha256(_mapping(profile.get("workloads")))
    traffic_fingerprint = recovery._canonical_sha256(_mapping(profile.get("traffic_matrix")))
    profile_errors = _profile_errors(profile)
    profile_blockers = _profile_blockers(profile)
    profile_valid = not profile_errors
    ready_for_verification = profile_valid and not profile_blockers
    attestation_errors = _attestation_errors(
        attestation,
        profile=profile,
        profile_fingerprint=profile_fingerprint,
        workload_fingerprint=workload_fingerprint,
        traffic_fingerprint=traffic_fingerprint,
        now=current,
        max_age=max_attestation_age,
    )
    attestation_valid = ready_for_verification and not attestation_errors
    gate_passed = ready_for_verification and attestation_valid
    stable = {
        "schema": REPORT_SCHEMA,
        "environment": ENVIRONMENT,
        "profile_fingerprint": profile_fingerprint,
        "workload_bindings_fingerprint": workload_fingerprint,
        "traffic_matrix_fingerprint": traffic_fingerprint,
        "attestation_fingerprint": (
            recovery._canonical_sha256(attestation) if attestation is not None else None
        ),
        "profile_valid": profile_valid,
        "profile_errors": profile_errors,
        "profile_blockers": profile_blockers,
        "attestation_valid": attestation_valid,
        "attestation_errors": attestation_errors,
        "ready_for_protected_verification": ready_for_verification,
        "production_network_policy_gate_passed": gate_passed,
        "production_network_policy_enforcement_verified": gate_passed,
        "metadata_provider_network_policy_verified": gate_passed,
        "tenant_isolation_verified": gate_passed,
        "production_ready": False,
    }
    return {**stable, "report_fingerprint": recovery._canonical_sha256(stable)}


def verify_report_integrity(report: Mapping[str, Any]) -> list[str]:
    """Reject modified reports and inconsistent or overall production claims."""
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("NetworkPolicy readiness report contains credential-bearing fields")
    errors.extend(
        _inventory_errors(
            report,
            EXPECTED_REPORT_FIELDS,
            "NetworkPolicy readiness report",
        )
    )
    if report.get("schema") != REPORT_SCHEMA or report.get("environment") != ENVIRONMENT:
        errors.append("NetworkPolicy readiness report schema or environment does not match")
    stable = {key: value for key, value in report.items() if key != "report_fingerprint"}
    if report.get("report_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("NetworkPolicy readiness report fingerprint does not match")
    for field in (
        "profile_fingerprint",
        "workload_bindings_fingerprint",
        "traffic_matrix_fingerprint",
        "attestation_fingerprint",
    ):
        value = report.get(field)
        if value is not None and not SHA256_PATTERN.fullmatch(str(value)):
            errors.append(f"NetworkPolicy readiness report {field} is invalid")

    list_fields = (
        "profile_errors",
        "profile_blockers",
        "attestation_errors",
    )
    for field in list_fields:
        value = report.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"NetworkPolicy readiness report {field} is invalid")
    bool_fields = (
        "profile_valid",
        "attestation_valid",
        "ready_for_protected_verification",
        "production_network_policy_gate_passed",
        "production_network_policy_enforcement_verified",
        "metadata_provider_network_policy_verified",
        "tenant_isolation_verified",
        "production_ready",
    )
    for field in bool_fields:
        if type(report.get(field)) is not bool:
            errors.append(f"NetworkPolicy readiness report {field} is invalid")

    if report.get("production_ready") is not False:
        errors.append("NetworkPolicy gate may not claim overall production readiness")
    expected_profile_valid = (
        isinstance(report.get("profile_errors"), list) and report.get("profile_errors") == []
    )
    if report.get("profile_valid") is not expected_profile_valid:
        errors.append("NetworkPolicy profile result is inconsistent")
    expected_ready = expected_profile_valid and report.get("profile_blockers") == []
    if report.get("ready_for_protected_verification") is not expected_ready:
        errors.append("NetworkPolicy protected verification readiness is inconsistent")
    expected_attestation = (
        expected_ready
        and isinstance(report.get("attestation_errors"), list)
        and report.get("attestation_errors") == []
    )
    if report.get("attestation_valid") is not expected_attestation:
        errors.append("NetworkPolicy attestation result is inconsistent")
    if expected_attestation and report.get("attestation_fingerprint") is None:
        errors.append("NetworkPolicy valid attestation fingerprint is missing")
    expected_gate = expected_ready and expected_attestation
    for claim in (
        "production_network_policy_gate_passed",
        "production_network_policy_enforcement_verified",
        "metadata_provider_network_policy_verified",
        "tenant_isolation_verified",
    ):
        if report.get(claim) is not expected_gate:
            errors.append(f"NetworkPolicy gate result is inconsistent: {claim}")
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
    evaluate_parser.add_argument("--output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            report = build_network_policy_readiness_report(profile_path=args.profile)
            _write_report(report, None)
            return 0 if report["profile_valid"] else 1
        if args.command == "evaluate":
            attestation = _load_json_object(args.attestation)
            report = build_network_policy_readiness_report(
                profile_path=args.profile,
                attestation=attestation,
            )
            _write_report(report, args.output)
            return 0 if report["production_network_policy_gate_passed"] else 1
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
        MetadataFabricNetworkPolicyGateError,
    ) as exc:
        print(f"metadata NetworkPolicy gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
