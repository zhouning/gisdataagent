"""Build the owner decision packet for protected production profiles.

M3-27 turns the exact M3-26 blocker inventory into an assignable dependency
graph. The checked packet records no production choices, credentials, or
attestations and grants no execution authority. Owners must materialize
approved values in the existing production profiles and produce fresh
protected attestations before M3-26 can be evaluated again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import metadata_fabric_protected_real_feature_reexecution_gate as reexecution

PACKET_SCHEMA = "gda.protected_profile_owner_decision_packet.v1"
VALIDATION_SCHEMA = "gda.protected_profile_owner_decision_packet_validation.v1"
PACKET_STATUS = "unresolved_owner_decisions"
GROUP_STATUS = "unresolved"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREDECESSOR_PATH = reexecution.DEFAULT_DECISION_PATH
DEFAULT_PACKET_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-protected-profile-decision-packet-2026-07-31.json"
)

PREDECESSOR_FILE_SHA256 = "62624b96d83b085cbb82d29d618042d7f4faa5193847c26af859ec1c87cd4f11"
PREDECESSOR_DECISION_SHA256 = "39246eacdd1793f23aecb71195cc4c9d8c63d7125aad8cd9bbb59a96c588cd73"
PREDECESSOR_CONTRACT_SHA256 = "39411248b37b7d8d43ac7ad37737de15d6b6d4c5e4feb2088f0a87cec888b5f9"

IDENTITY_PROFILE = "config/metadata-fabric-identity.production.yaml"
OBJECT_STORE_PROFILE = "config/metadata-fabric-object-store.production.yaml"
IDENTITY_VERIFY = (
    "python -m data_agent.metadata_fabric_identity_gate evaluate "
    f"--profile {IDENTITY_PROFILE} --attestation $GDA_IDENTITY_ATTESTATION"
)
OBJECT_STORE_VERIFY = (
    "python -m data_agent.metadata_fabric_object_store_gate evaluate "
    f"--profile {OBJECT_STORE_PROFILE} --attestation $GDA_OBJECT_STORE_ATTESTATION"
)

PACKET_INVENTORY = {
    "schema",
    "status",
    "generated_at",
    "predecessor_binding",
    "decision_groups",
    "blocker_summary",
    "resolution_policy",
    "claims",
    "packet_sha256",
}
GROUP_INVENTORY = {
    "decision_id",
    "title",
    "owner_roles",
    "depends_on",
    "blockers",
    "profile_paths",
    "allowed_choices",
    "forbidden_choices",
    "required_artifacts",
    "protected_verification_command",
    "status",
}
CLAIMS = {
    "owner_decisions_approved",
    "production_profiles_ready",
    "protected_identity_attested",
    "protected_object_store_attested",
    "ready_for_protected_reexecution",
    "scheduler_submission_authorized",
    "provider_mutation_authorized",
    "production_ingestion_verified",
    "production_ready",
}


def _profile_blockers(prefix: str, *paths: str) -> list[str]:
    return [f"{prefix}.profile:{path}" for path in paths]


DECISION_GROUP_SPECS: tuple[dict[str, Any], ...] = (
    {
        "decision_id": "identity-federation",
        "title": "Identity federation",
        "owner_roles": ["Security Architecture", "IAM Platform"],
        "depends_on": [],
        "blockers": _profile_blockers(
            "identity",
            "federation.audience",
            "federation.decision_status",
            "federation.discovery_uri",
            "federation.issuer",
            "federation.jwks_uri",
            "federation.token_exchange_mode",
            "federation.trust_policy_reference",
        ),
        "allowed_choices": [
            "An approved production OIDC authority with discovery and JWKS endpoints",
            (
                "A short-lived token exchange mode and reviewed trust-policy "
                "reference accepted by ADR-053"
            ),
        ],
        "forbidden_choices": [
            "Static or long-lived workload credentials",
            "Local, cluster-only, example, or unreviewed identity endpoints",
        ],
        "required_artifacts": [
            "Approved identity federation architecture decision",
            "OIDC authority ownership and trust-policy review evidence",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "openmetadata-identity-binding",
        "title": "OpenMetadata identity binding",
        "owner_roles": ["Metadata Platform", "IAM Platform"],
        "depends_on": ["identity-federation"],
        "blockers": _profile_blockers(
            "identity",
            "providers.openmetadata.authentication_component_reference",
            "providers.openmetadata.environment_binding",
            "providers.openmetadata.integration_mode",
            "providers.openmetadata.kubernetes_service_account",
            "providers.openmetadata.namespace_template",
            "providers.openmetadata.workload_identity_reference",
        ),
        "allowed_choices": [
            "Provider-native OIDC or an approved identity-aware proxy",
            "A tenant-bound workload identity and least-privilege service account",
        ],
        "forbidden_choices": [
            "Bootstrap administrator identity for production projection",
            "Direct provider access outside the attested workload identity path",
        ],
        "required_artifacts": [
            "OpenMetadata authentication component and environment binding references",
            "Service-account and workload-subject ownership review",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "gravitino-identity-binding",
        "title": "Gravitino identity binding",
        "owner_roles": ["Lakehouse Platform", "IAM Platform"],
        "depends_on": ["identity-federation"],
        "blockers": _profile_blockers(
            "identity",
            "providers.gravitino.authentication_component_reference",
            "providers.gravitino.environment_binding",
            "providers.gravitino.integration_mode",
            "providers.gravitino.kubernetes_service_account",
            "providers.gravitino.namespace_template",
            "providers.gravitino.workload_identity_reference",
        ),
        "allowed_choices": [
            "An approved OIDC authenticator or identity-aware proxy",
            "A tenant-bound workload identity and least-privilege service account",
        ],
        "forbidden_choices": [
            "Unauthenticated production catalog access",
            "Direct provider access outside the attested workload identity path",
        ],
        "required_artifacts": [
            "Gravitino authentication component and environment binding references",
            "Service-account and workload-subject ownership review",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "metadata-tls",
        "title": "Metadata transport security",
        "owner_roles": ["Security Architecture", "Platform SRE"],
        "depends_on": ["identity-federation"],
        "blockers": _profile_blockers(
            "identity",
            "tls.certificate_policy_reference",
            "tls.gravitino_endpoint",
            "tls.openmetadata_endpoint",
            "tls.trust_bundle_reference",
        ),
        "allowed_choices": [
            "Production HTTPS endpoints with reviewed certificate and trust-bundle policies",
            "TLS 1.2 or newer with mTLS on internal hops as frozen in the profile",
        ],
        "forbidden_choices": [
            "Plaintext provider endpoints",
            "Local, cluster-only, example, or certificate-bypass endpoints",
        ],
        "required_artifacts": [
            "Certificate lifecycle policy",
            "Trust-bundle ownership and endpoint inventory",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "persistent-catalog",
        "title": "Persistent catalog",
        "owner_roles": ["Lakehouse Platform", "Database SRE"],
        "depends_on": ["gravitino-identity-binding", "metadata-tls"],
        "blockers": _profile_blockers(
            "identity",
            "catalog.backup_policy_reference",
            "catalog.catalog_reference",
            "catalog.decision_status",
            "catalog.gravitino_backend",
            "catalog.persistence_reference",
        ),
        "allowed_choices": [
            "An approved Iceberg REST or JDBC catalog with persistent metadata storage",
            "A catalog binding with reviewed backup and restore policy",
        ],
        "forbidden_choices": [
            "In-memory catalog authority",
            "Ephemeral metadata storage or unverified backup claims",
        ],
        "required_artifacts": [
            "Approved catalog backend decision",
            "Persistence, backup, and restore ownership references",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "metadata-tenancy",
        "title": "Metadata tenancy",
        "owner_roles": ["Data Governance", "Security Architecture"],
        "depends_on": [
            "openmetadata-identity-binding",
            "gravitino-identity-binding",
        ],
        "blockers": _profile_blockers(
            "identity",
            "tenancy.isolation_mode",
            "tenancy.policy_reference",
        ),
        "allowed_choices": [
            "An explicit tenant-isolation mode bound to the gda_tenant_id claim",
            "A reviewed policy that includes cross-tenant denial probes",
        ],
        "forbidden_choices": [
            "Shared unscoped provider identity",
            "Tenant isolation based only on caller-supplied naming conventions",
        ],
        "required_artifacts": [
            "Tenant isolation policy",
            "Cross-tenant denial test plan",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "identity-operations",
        "title": "Identity operations and runbooks",
        "owner_roles": ["IAM Platform", "Security Operations", "Platform SRE"],
        "depends_on": [
            "identity-federation",
            "openmetadata-identity-binding",
            "gravitino-identity-binding",
            "metadata-tls",
            "persistent-catalog",
            "metadata-tenancy",
        ],
        "blockers": _profile_blockers(
            "identity",
            "operations.audit_log_reference",
            "operations.identity_owner",
            "operations.incident_owner",
            "operations.revocation_slo_minutes",
            "operations.rollback_runbook.uri",
            "operations.rollback_runbook.version",
            "operations.rotation_slo_minutes",
            "operations.runbook.uri",
            "operations.runbook.version",
            "operations.security_owner",
        ),
        "allowed_choices": [
            "Named ownership references, measurable rotation and revocation SLOs",
            "Versioned production runbooks and auditable identity events",
        ],
        "forbidden_choices": [
            "Unowned incident response or unversioned runbooks",
            "Manual credential rotation without a protected audit trail",
        ],
        "required_artifacts": [
            "Identity operations ownership record",
            "Versioned incident, rotation, revocation, and rollback runbooks",
            "Audit-log delivery reference",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "object-store-provider",
        "title": "Object-store provider",
        "owner_roles": ["Cloud Platform", "Storage Platform"],
        "depends_on": [],
        "blockers": _profile_blockers(
            "object_store",
            "provider.account_reference",
            "provider.bucket",
            "provider.decision_status",
            "provider.endpoint",
            "provider.failure_domain_reference",
            "provider.infrastructure_reference",
            "provider.provider_type",
            "provider.recovery_region",
            "provider.region",
        ),
        "allowed_choices": [
            "A production provider accepted by ADR-057 with independently owned infrastructure",
            "Distinct primary and recovery regions with multi-zone durability",
        ],
        "forbidden_choices": [
            "The retained local MinIO namespace as production authority",
            "A provider account, bucket, or failure domain selected without owner approval",
        ],
        "required_artifacts": [
            "Approved provider and region architecture decision",
            "Infrastructure, account, bucket, and failure-domain ownership references",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
    {
        "decision_id": "object-store-workload-identity",
        "title": "Object-store workload identity",
        "owner_roles": ["Cloud Platform", "IAM Platform", "Security Architecture"],
        "depends_on": ["identity-federation", "object-store-provider"],
        "blockers": _profile_blockers(
            "object_store",
            "identity.bucket_policy_reference",
            "identity.integration_mode",
            "identity.kubernetes_service_account",
            "identity.least_privilege_policy_reference",
            "identity.workload_identity_reference",
        ),
        "allowed_choices": [
            "OIDC workload federation with the frozen least-privilege operation inventory",
            "A tenant-bound service account with a maximum 900-second session",
        ],
        "forbidden_choices": [
            "Static access keys or node-wide provider credentials",
            "Bucket permissions broader than the checked operation inventory",
        ],
        "required_artifacts": [
            "Workload identity and service-account binding",
            "Least-privilege and bucket-policy reviews",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
    {
        "decision_id": "object-store-transport",
        "title": "Object-store transport",
        "owner_roles": ["Network Platform", "Security Architecture"],
        "depends_on": ["object-store-provider"],
        "blockers": _profile_blockers(
            "object_store",
            "transport.certificate_policy_reference",
            "transport.dns_policy_reference",
            "transport.endpoint",
            "transport.private_connectivity_reference",
            "transport.trust_bundle_reference",
        ),
        "allowed_choices": [
            "The approved provider HTTPS endpoint over reviewed private connectivity and DNS",
            "TLS 1.2 or newer with managed trust and certificate lifecycle",
        ],
        "forbidden_choices": [
            "Public or plaintext data paths not covered by the network policy",
            "Local, example, certificate-bypass, or split-horizon endpoints without review",
        ],
        "required_artifacts": [
            "Private connectivity and DNS policy references",
            "Certificate lifecycle and trust-bundle references",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
    {
        "decision_id": "object-store-encryption",
        "title": "Object-store encryption and KMS",
        "owner_roles": ["Cloud Security", "Key Management"],
        "depends_on": ["object-store-provider", "object-store-workload-identity"],
        "blockers": _profile_blockers(
            "object_store",
            "encryption.key_policy_reference",
            "encryption.key_reference",
            "encryption.rotation_days",
        ),
        "allowed_choices": [
            "A provider KMS key with reviewed key policy and rotation of at most 365 days",
            "Server-side KMS encryption with bucket-key support as frozen in the profile",
        ],
        "forbidden_choices": [
            "Unmanaged or shared encryption keys without tenant and workload controls",
            "Encryption claims without protected read/write verification",
        ],
        "required_artifacts": [
            "KMS key ownership and policy review",
            "Key rotation decision and recovery procedure",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
    {
        "decision_id": "object-store-durability-consistency",
        "title": "Object-store durability and consistency",
        "owner_roles": ["Storage Platform", "Platform SRE"],
        "depends_on": [
            "object-store-provider",
            "object-store-transport",
            "object-store-encryption",
        ],
        "blockers": _profile_blockers(
            "object_store",
            "consistency.multipart_upload_cleanup_reference",
            "consistency.orphan_file_cleanup_reference",
            "durability.recovery_bucket_reference",
            "durability.replication_policy_reference",
            "durability.retention_policy_reference",
        ),
        "allowed_choices": [
            (
                "Versioned recovery and asynchronous cross-region replication "
                "meeting the frozen RPO/RTO"
            ),
            "Reviewed multipart-upload and orphan-file cleanup controls",
        ],
        "forbidden_choices": [
            "Single-copy durability or same-region recovery authority",
            "Rename-based correctness assumptions for object storage",
        ],
        "required_artifacts": [
            "Retention and replication policies",
            "Recovery bucket ownership and cleanup-control references",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
    {
        "decision_id": "object-store-tenancy",
        "title": "Object-store tenancy",
        "owner_roles": ["Data Governance", "Cloud Security"],
        "depends_on": ["object-store-provider", "object-store-workload-identity"],
        "blockers": _profile_blockers(
            "object_store",
            "tenancy.policy_reference",
        ),
        "allowed_choices": [
            "Bucket-prefix and provider-policy isolation bound to tenants/{tenant_id}/warehouse/",
            "A policy with public-access blocking and cross-tenant denial probes",
        ],
        "forbidden_choices": [
            "Shared prefixes without provider-enforced tenant policy",
            "Public access or client-only tenant filtering",
        ],
        "required_artifacts": [
            "Tenant storage isolation policy",
            "Cross-tenant and public-access denial test plan",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
    {
        "decision_id": "object-store-operations",
        "title": "Object-store operations, SLOs, and runbooks",
        "owner_roles": ["Storage Platform", "Platform SRE", "Security Operations"],
        "depends_on": [
            "object-store-provider",
            "object-store-workload-identity",
            "object-store-transport",
            "object-store-encryption",
            "object-store-durability-consistency",
            "object-store-tenancy",
        ],
        "blockers": _profile_blockers(
            "object_store",
            "operations.attestation_policy_reference",
            "operations.audit_log_reference",
            "operations.availability_slo_percent",
            "operations.incident_owner",
            "operations.latency_slo_ms",
            "operations.metrics_alert_reference",
            "operations.platform_owner",
            "operations.recovery_runbook.uri",
            "operations.recovery_runbook.version",
            "operations.rollback_runbook.uri",
            "operations.rollback_runbook.version",
            "operations.runbook.uri",
            "operations.runbook.version",
            "operations.security_owner",
            "operations.storage_owner",
        ),
        "allowed_choices": [
            "Named ownership, measurable availability and latency SLOs, and actionable alerts",
            (
                "Versioned operation, recovery, and rollback runbooks tied to "
                "protected attestation policy"
            ),
        ],
        "forbidden_choices": [
            "Unowned incidents, unversioned runbooks, or synthetic-only alerts",
            "Availability or recovery claims without protected failure rehearsal",
        ],
        "required_artifacts": [
            "Operations and incident ownership record",
            "SLO, alert, audit-log, and attestation policy references",
            "Versioned operation, recovery, and rollback runbooks",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
    {
        "decision_id": "protected-identity-attestation",
        "title": "Protected identity attestation",
        "owner_roles": ["Security Operations", "Platform SRE"],
        "depends_on": ["identity-operations"],
        "blockers": [
            "identity.attestation:production identity attestation is missing",
        ],
        "allowed_choices": [
            "A fresh ADR-053 attestation emitted by the protected production identity environment",
            (
                "An attestation bound to the approved profile, exact source "
                "revision, tenant denial, and audit evidence"
            ),
        ],
        "forbidden_choices": [
            "A local, manually asserted, expired, or cross-revision attestation",
            "Reusing M3-24 or M3-25 retained material as production identity evidence",
        ],
        "required_artifacts": [
            "Fresh protected identity attestation",
            "Protected workflow and reviewer evidence URI",
        ],
        "protected_verification_command": IDENTITY_VERIFY,
    },
    {
        "decision_id": "protected-object-store-attestation",
        "title": "Protected object-store attestation",
        "owner_roles": ["Storage Platform", "Security Operations", "Platform SRE"],
        "depends_on": ["object-store-operations"],
        "blockers": [
            "object_store.attestation:production object-store attestation is required",
        ],
        "allowed_choices": [
            (
                "A fresh ADR-057 attestation emitted by the protected production "
                "object-store environment"
            ),
            (
                "An attestation bound to the approved profile, exact source "
                "revision, tenant controls, KMS, and recovery evidence"
            ),
        ],
        "forbidden_choices": [
            "A local, manually asserted, expired, or cross-revision attestation",
            "Treating the retained MinIO rehearsal as a production object-store attestation",
        ],
        "required_artifacts": [
            "Fresh protected object-store attestation",
            "Protected workflow and reviewer evidence URI",
        ],
        "protected_verification_command": OBJECT_STORE_VERIFY,
    },
)


class ProtectedProfileDecisionPacketError(RuntimeError):
    """The M3-27 decision packet failed closed."""


def canonical_json_fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
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


def _parse_time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtectedProfileDecisionPacketError("generated_at is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProtectedProfileDecisionPacketError("generated_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _load_predecessor(path: Path = DEFAULT_PREDECESSOR_PATH) -> dict[str, Any]:
    if _file_sha256(path) != PREDECESSOR_FILE_SHA256:
        raise ProtectedProfileDecisionPacketError(
            "M3-26 predecessor file fingerprint does not match"
        )
    decision = _load_json_object(path)
    errors = reexecution.validate_decision(decision)
    if errors:
        raise ProtectedProfileDecisionPacketError(
            "M3-26 predecessor is invalid: " + "; ".join(errors)
        )
    if (
        decision.get("decision_sha256") != PREDECESSOR_DECISION_SHA256
        or decision.get("contract_sha256") != PREDECESSOR_CONTRACT_SHA256
        or decision.get("status") != reexecution.BLOCKED_STATUS
        or decision.get("ready_for_protected_reexecution") is not False
    ):
        raise ProtectedProfileDecisionPacketError("M3-26 predecessor binding does not match")
    return decision


def _profile_paths(blockers: list[Any]) -> list[str]:
    paths: list[str] = []
    for blocker in blockers:
        if not isinstance(blocker, str):
            continue
        if blocker.startswith("identity.profile:"):
            paths.append(f"{IDENTITY_PROFILE}#{blocker.split(':', 1)[1]}")
        elif blocker.startswith("object_store.profile:"):
            paths.append(f"{OBJECT_STORE_PROFILE}#{blocker.split(':', 1)[1]}")
    return paths


def _decision_groups() -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for spec in DECISION_GROUP_SPECS:
        group = deepcopy(spec)
        group["profile_paths"] = _profile_paths(group["blockers"])
        group["status"] = GROUP_STATUS
        groups.append(group)
    return groups


def _blocker_domain(blocker: Any) -> str:
    if not isinstance(blocker, str):
        return "unknown"
    if blocker.startswith("identity.profile:"):
        return "identity_profile"
    if blocker.startswith("identity.attestation:"):
        return "identity_attestation"
    if blocker.startswith("object_store.profile:"):
        return "object_store_profile"
    if blocker.startswith("object_store.attestation:"):
        return "object_store_attestation"
    return "unknown"


def build_packet(
    *,
    predecessor_path: Path = DEFAULT_PREDECESSOR_PATH,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    decision = _load_predecessor(predecessor_path)
    timestamp = (generated_at or datetime.now(UTC)).astimezone(UTC)
    groups = _decision_groups()
    assigned = [blocker for group in groups for blocker in group["blockers"]]
    domains = Counter(_blocker_domain(blocker) for blocker in assigned)
    stable = {
        "schema": PACKET_SCHEMA,
        "status": PACKET_STATUS,
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "predecessor_binding": {
            "path": str(predecessor_path.relative_to(REPO_ROOT)),
            "file_sha256": PREDECESSOR_FILE_SHA256,
            "decision_sha256": PREDECESSOR_DECISION_SHA256,
            "contract_sha256": PREDECESSOR_CONTRACT_SHA256,
            "evaluated_at": decision.get("evaluated_at"),
            "status": decision.get("status"),
            "blocker_count": len(decision.get("blockers", [])),
            "ready_for_protected_reexecution": False,
        },
        "decision_groups": groups,
        "blocker_summary": {
            "expected": len(decision.get("blockers", [])),
            "assigned": len(assigned),
            "unique": len(set(assigned)),
            "decision_groups": len(groups),
            "unresolved_decision_groups": len(groups),
            "identity_profile": domains["identity_profile"],
            "identity_attestation": domains["identity_attestation"],
            "object_store_profile": domains["object_store_profile"],
            "object_store_attestation": domains["object_store_attestation"],
        },
        "resolution_policy": {
            "authoritative_profile_paths": [IDENTITY_PROFILE, OBJECT_STORE_PROFILE],
            "profile_changes_require_owner_approval": True,
            "attestations_must_be_fresh_protected_outputs": True,
            "attestations_must_share_source_revision": True,
            "credential_material_forbidden": True,
            "local_retained_material_promotion_forbidden": True,
            "packet_records_decisions": False,
            "packet_grants_execution_authority": False,
        },
        "claims": {claim: False for claim in sorted(CLAIMS)},
    }
    return {**stable, "packet_sha256": canonical_json_fingerprint(stable)}


def _sensitive_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if reexecution.SENSITIVE_KEY_PATTERN.search(str(key)):
                findings.append(path)
            findings.extend(_sensitive_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_sensitive_paths(item, f"{prefix}[{index}]"))
    return findings


def _dependency_errors(groups: list[Any]) -> list[str]:
    errors: list[str] = []
    mappings = [group for group in groups if isinstance(group, Mapping)]
    if len(mappings) != len(groups):
        errors.append("M3-27 decision group is not an object")
    ids = [str(group.get("decision_id")) for group in mappings]
    if len(ids) != len(set(ids)):
        errors.append("M3-27 decision IDs are not unique")
    known = set(ids)
    graph: dict[str, list[str]] = {}
    for group in mappings:
        decision_id = str(group.get("decision_id"))
        dependencies = group.get("depends_on")
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) for item in dependencies
        ):
            errors.append(f"M3-27 dependencies are invalid: {decision_id}")
            graph[decision_id] = []
            continue
        graph[decision_id] = dependencies
        unknown = sorted(set(dependencies) - known)
        if unknown:
            errors.append(f"M3-27 dependencies are unknown for {decision_id}: {','.join(unknown)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append("M3-27 dependency graph contains a cycle")
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for decision_id in graph:
        visit(decision_id)
    return errors


def validate_packet(packet: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(packet) != PACKET_INVENTORY:
        errors.append("M3-27 packet inventory does not match")
    stable = {key: value for key, value in packet.items() if key != "packet_sha256"}
    if packet.get("packet_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-27 packet fingerprint does not match")

    groups_value = packet.get("decision_groups")
    groups = groups_value if isinstance(groups_value, list) else []
    if not isinstance(groups_value, list):
        errors.append("M3-27 decision groups are not a list")
    errors.extend(_dependency_errors(groups))
    blockers: list[str] = []
    for group in groups:
        if not isinstance(group, Mapping):
            errors.append("M3-27 decision group is not an object")
            continue
        decision_id = str(group.get("decision_id"))
        if set(group) != GROUP_INVENTORY:
            errors.append(f"M3-27 group inventory does not match: {decision_id}")
        if group.get("status") != GROUP_STATUS:
            errors.append(f"M3-27 group is not unresolved: {decision_id}")
        for field in (
            "owner_roles",
            "blockers",
            "allowed_choices",
            "forbidden_choices",
            "required_artifacts",
        ):
            value = group.get(field)
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item for item in value)
            ):
                errors.append(f"M3-27 group {field} is invalid: {decision_id}")
        group_blockers = group.get("blockers")
        if isinstance(group_blockers, list):
            blockers.extend(str(item) for item in group_blockers)
            if group.get("profile_paths") != _profile_paths(group_blockers):
                errors.append(f"M3-27 profile paths do not match: {decision_id}")
        if not isinstance(group.get("protected_verification_command"), str):
            errors.append(f"M3-27 verification command is invalid: {decision_id}")

    try:
        expected_blockers = [str(item) for item in _load_predecessor()["blockers"]]
    except (OSError, TypeError, ValueError, ProtectedProfileDecisionPacketError) as exc:
        errors.append(f"M3-27 predecessor is invalid: {exc}")
        expected_blockers = []
    counts = Counter(blockers)
    duplicates = sorted(item for item, count in counts.items() if count != 1)
    if duplicates:
        errors.append("M3-27 blockers are not assigned exactly once")
    if set(blockers) != set(expected_blockers):
        errors.append("M3-27 blocker coverage does not match M3-26")

    claims = packet.get("claims")
    if not isinstance(claims, Mapping) or set(claims) != CLAIMS:
        errors.append("M3-27 claims inventory does not match")
    elif any(value is not False for value in claims.values()):
        errors.append("M3-27 packet may not assert production claims")
    if packet.get("status") != PACKET_STATUS:
        errors.append("M3-27 packet must remain unresolved")
    if _sensitive_paths(packet):
        errors.append("M3-27 packet contains credential-bearing fields")

    try:
        generated_at = _parse_time(packet.get("generated_at"))
        expected = build_packet(generated_at=generated_at)
    except (OSError, TypeError, ValueError, ProtectedProfileDecisionPacketError) as exc:
        errors.append(f"M3-27 packet inputs are invalid: {exc}")
        expected = None
    if expected is not None and dict(packet) != expected:
        errors.append("M3-27 packet does not match current bound inputs")
    return sorted(set(errors))


def build_validation_report(packet_path: Path = DEFAULT_PACKET_PATH) -> dict[str, Any]:
    try:
        packet = _load_json_object(packet_path)
        errors = validate_packet(packet)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        packet = {}
        errors = [f"M3-27 packet is unreadable: {type(exc).__name__}"]
    summary = packet.get("blocker_summary")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "packet_sha256": packet.get("packet_sha256"),
        "packet_status": packet.get("status"),
        "blocker_summary": dict(summary) if isinstance(summary, Mapping) else None,
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
    validate = subparsers.add_parser("validate")
    validate.add_argument("--packet", type=Path, default=DEFAULT_PACKET_PATH)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output", type=Path, default=DEFAULT_PACKET_PATH)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = build_validation_report(args.packet)
            exit_code = 0 if report["status"] == "valid" else 1
        else:
            report = build_packet()
            _write_json(args.output, report)
            exit_code = 0
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ProtectedProfileDecisionPacketError,
    ) as exc:
        print(f"protected profile decision packet: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
