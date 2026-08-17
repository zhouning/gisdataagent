import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from data_agent import metadata_fabric_identity_gate as gate


NOW = datetime(2026, 7, 28, 16, 0, tzinfo=UTC)


def _default_profile() -> dict:
    return yaml.safe_load(gate.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))


def _write_profile(tmp_path: Path, profile: dict) -> Path:
    target = tmp_path / "identity-profile.yaml"
    target.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return target


def _complete_profile() -> dict:
    profile = _default_profile()
    profile["federation"].update(
        {
            "decision_status": "approved",
            "issuer": "https://identity.gda.internal",
            "discovery_uri": (
                "https://identity.gda.internal/.well-known/openid-configuration"
            ),
            "jwks_uri": "https://identity.gda.internal/oauth2/jwks",
            "audience": "audience://metadata-fabric/production",
            "token_exchange_mode": "oidc_workload_federation",
            "trust_policy_reference": "policy://production/metadata-federation-v1",
        }
    )
    for provider, mode in (
        ("openmetadata", "provider_native_oidc"),
        ("gravitino", "custom_oidc_authenticator"),
    ):
        item = profile["providers"][provider]
        item.update(
            {
                "integration_mode": mode,
                "environment_binding": f"environment://production/{provider}",
                "workload_identity_reference": (
                    f"identity://production/metadata/{provider}"
                ),
                "kubernetes_service_account": provider,
                "namespace_template": "gda-{tenant_id}",
            }
        )
        digest_character = "a" if provider == "openmetadata" else "b"
        item["authentication_component_reference"] = (
            f"oci://registry.gda.internal/metadata/{provider}-identity@sha256:"
            f"{digest_character * 64}"
        )
    profile["tls"].update(
        {
            "minimum_version": "TLSv1.3",
            "openmetadata_endpoint": "https://openmetadata.gda.internal/api",
            "gravitino_endpoint": "https://gravitino.gda.internal/api",
            "trust_bundle_reference": "pki://production/metadata-fabric-ca-v1",
            "certificate_policy_reference": (
                "policy://production/metadata-certificate-v1"
            ),
        }
    )
    profile["catalog"].update(
        {
            "decision_status": "approved",
            "gravitino_backend": "iceberg_rest",
            "catalog_reference": "catalog://production/lakehouse",
            "persistence_reference": "storage://production/metadata-catalog",
            "backup_policy_reference": "policy://production/metadata-backup-v1",
        }
    )
    profile["tenancy"].update(
        {
            "isolation_mode": "namespace_and_provider_policy",
            "policy_reference": "policy://production/metadata-tenant-isolation-v1",
        }
    )
    profile["operations"].update(
        {
            "identity_owner": "team://metadata-platform",
            "security_owner": "team://security-platform",
            "incident_owner": "team://metadata-oncall",
            "audit_log_reference": "logging://production/metadata-identity-audit",
            "rotation_slo_minutes": 30,
            "revocation_slo_minutes": 10,
            "runbook": {
                "uri": "https://runbooks.gda.internal/metadata-identity",
                "version": "2026.07.28",
            },
            "rollback_runbook": {
                "uri": "https://runbooks.gda.internal/metadata-identity-rollback",
                "version": "2026.07.28",
            },
        }
    )
    return profile


def _attestation(profile_path: Path, **changes: object) -> dict:
    report = gate.build_identity_readiness_report(profile_path=profile_path, now=NOW)
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    payload = {
        "schema": gate.ATTESTATION_SCHEMA,
        "environment": gate.ENVIRONMENT,
        "profile_fingerprint": report["profile_fingerprint"],
        "source_revision": "c" * 40,
        "observed_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "protected_environment": gate.ENVIRONMENT,
        "verifier_identity": "identity://github/metadata-identity-verifier",
        "evidence_uri": "https://evidence.gda.internal/metadata-identity/run-42",
        "provider_versions": deepcopy(gate.EXPECTED_PROVIDERS),
        "local_evidence_fingerprints": {
            provider: item["evidence_fingerprint"]
            for provider, item in gate.EXPECTED_LOCAL_EVIDENCE.items()
        },
        "federation_fingerprint": report["federation_fingerprint"],
        "provider_bindings_fingerprint": report["provider_bindings_fingerprint"],
        "authorization_fingerprint": report["authorization_fingerprint"],
        "tls_fingerprint": report["tls_fingerprint"],
        "catalog_fingerprint": report["catalog_fingerprint"],
        "tenancy_fingerprint": report["tenancy_fingerprint"],
        "runbook_versions": {
            name: profile["operations"][name]["version"]
            for name in ("runbook", "rollback_runbook")
        },
        "checks": {name: "passed" for name in gate.EXPECTED_ATTESTATION_CHECKS},
    }
    payload.update(changes)
    return payload


def test_checked_in_profile_is_valid_but_production_identity_is_blocked():
    report = gate.build_identity_readiness_report(now=NOW)

    assert report["profile_valid"] is True
    assert report["profile_errors"] == []
    assert report["ready_for_protected_verification"] is False
    assert report["production_identity_gate_passed"] is False
    assert report["provider_minimum_privilege_verified"] is False
    assert report["protected_workload_identity_verified"] is False
    assert report["oidc_verified"] is False
    assert report["tls_verified"] is False
    assert report["production_identity_verified"] is False
    assert report["production_ready"] is False
    assert len(report["profile_blockers"]) == 40
    assert "federation.decision_status" in report["profile_blockers"]
    assert "providers.gravitino.integration_mode" in report["profile_blockers"]
    assert "catalog.gravitino_backend" in report["profile_blockers"]
    assert gate.verify_report_integrity(report) == []


def test_complete_profile_without_attestation_is_only_ready_for_verification(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())

    report = gate.build_identity_readiness_report(profile_path=profile_path, now=NOW)

    assert report["profile_valid"] is True
    assert report["profile_errors"] == []
    assert report["profile_blockers"] == []
    assert report["ready_for_protected_verification"] is True
    assert report["attestation_valid"] is False
    assert report["production_identity_gate_passed"] is False


def test_fresh_bound_attestation_passes_only_the_identity_gate(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())

    report = gate.build_identity_readiness_report(
        profile_path=profile_path,
        attestation=_attestation(profile_path),
        now=NOW,
    )

    assert report["attestation_valid"] is True
    assert report["production_identity_gate_passed"] is True
    assert report["provider_minimum_privilege_verified"] is True
    assert report["protected_workload_identity_verified"] is True
    assert report["oidc_verified"] is True
    assert report["tls_verified"] is True
    assert report["credential_rotation_verified"] is True
    assert report["credential_revocation_verified"] is True
    assert report["persistent_catalog_identity_binding_verified"] is True
    assert report["production_identity_verified"] is True
    assert report["production_ready"] is False
    assert gate.verify_report_integrity(report) == []


@pytest.mark.parametrize(
    ("provider", "mode"),
    [
        ("openmetadata", "static_jwt"),
        ("gravitino", "simple"),
        ("gravitino", "basic"),
    ],
)
def test_profile_rejects_local_or_unvalidated_authenticators(tmp_path, provider, mode):
    profile = _complete_profile()
    profile["providers"][provider]["integration_mode"] = mode

    report = gate.build_identity_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )

    assert report["profile_valid"] is False
    assert f"{provider} identity integration mode is invalid" in "\n".join(
        report["profile_errors"]
    )
    assert report["production_identity_gate_passed"] is False


def test_profile_rejects_static_credentials_unpinned_component_and_http(tmp_path):
    profile = _complete_profile()
    profile["providers"]["gravitino"]["static_credentials_forbidden"] = False
    profile["providers"]["openmetadata"]["authentication_component_reference"] = (
        "oci://registry.gda.internal/metadata/openmetadata-identity:latest"
    )
    profile["tls"]["gravitino_endpoint"] = "http://localhost:8090/api"

    report = gate.build_identity_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )

    rendered = "\n".join(report["profile_errors"])
    assert report["profile_valid"] is False
    assert "static_credentials_forbidden" in rendered
    assert "digest-pinned OCI" in rendered
    assert "gravitino_endpoint is invalid" in rendered


def test_profile_rejects_authorization_and_local_evidence_drift(tmp_path):
    profile = _complete_profile()
    profile["authorization"]["gravitino"]["securable_objects"][1][
        "privileges"
    ].append("MODIFY_TABLE")
    profile["scope"]["local_evidence"]["openmetadata"][
        "evidence_fingerprint"
    ] = "0" * 64

    report = gate.build_identity_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )

    rendered = "\n".join(report["profile_errors"])
    assert report["profile_valid"] is False
    assert "minimum-privilege authorization contract" in rendered
    assert "openmetadata local identity evidence binding" in rendered


def test_profile_rejects_sensitive_fields_and_self_asserted_claims(tmp_path):
    profile = _complete_profile()
    profile["federation"]["client_secret"] = "must-not-enter-profile"
    profile["claims"]["production_identity_gate_passed"] = True

    report = gate.build_identity_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )

    rendered = "\n".join(report["profile_errors"])
    assert report["profile_valid"] is False
    assert "credential-bearing fields" in rendered
    assert "federation inventory" in rendered
    assert "may not self-assert" in rendered


@pytest.mark.parametrize(
    "binding",
    [
        "profile_fingerprint",
        "federation_fingerprint",
        "provider_bindings_fingerprint",
        "authorization_fingerprint",
        "tls_fingerprint",
        "catalog_fingerprint",
        "tenancy_fingerprint",
    ],
)
def test_attestation_rejects_every_profile_binding_drift(tmp_path, binding):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation[binding] = "0" * 64

    report = gate.build_identity_readiness_report(
        profile_path=profile_path, attestation=attestation, now=NOW
    )

    assert report["attestation_valid"] is False
    assert "current profile" in "\n".join(report["attestation_errors"]) or (
        f"binding does not match: {binding}" in "\n".join(report["attestation_errors"])
    )


def test_attestation_rejects_sensitive_fields_expiry_and_local_evidence_drift(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(
        profile_path,
        observed_at=(NOW - timedelta(days=2)).isoformat(),
        expires_at=(NOW - timedelta(days=1)).isoformat(),
        access_token="must-not-enter-attestation",
    )
    attestation["local_evidence_fingerprints"]["gravitino"] = "0" * 64

    report = gate.build_identity_readiness_report(
        profile_path=profile_path, attestation=attestation, now=NOW
    )

    rendered = "\n".join(report["attestation_errors"])
    assert report["attestation_valid"] is False
    assert "credential-bearing fields" in rendered
    assert "freshness window" in rendered
    assert "expired" in rendered
    assert "local evidence bindings" in rendered


@pytest.mark.parametrize(
    "check",
    [
        "gravitino_administrative_deny",
        "provider_direct_access_denied",
        "credential_revocation",
        "persistent_catalog_restart",
        "cross_tenant_denial",
        "rollback_rehearsal",
    ],
)
def test_attestation_requires_denial_lifecycle_persistence_and_rollback(tmp_path, check):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation["checks"][check] = "failed"

    report = gate.build_identity_readiness_report(
        profile_path=profile_path, attestation=attestation, now=NOW
    )

    assert report["attestation_valid"] is False
    assert check in "\n".join(report["attestation_errors"])


def test_report_integrity_rejects_tampering_inventory_and_production_overclaim():
    report = gate.build_identity_readiness_report(now=NOW)
    report["production_ready"] = True
    report["oidc_verified"] = True

    errors = gate.verify_report_integrity(report)

    assert "identity readiness report fingerprint does not match" in errors
    assert "identity gate may not claim overall production readiness" in errors
    assert "identity gate result is inconsistent: oidc_verified" in errors

    forged = gate.build_identity_readiness_report(now=NOW)
    forged["unexpected_claim"] = False
    stable = {
        key: value for key, value in forged.items() if key != "report_fingerprint"
    }
    forged["report_fingerprint"] = gate.recovery._canonical_sha256(stable)
    assert "identity readiness report inventory does not match" in (
        gate.verify_report_integrity(forged)
    )


def test_wrapper_is_fail_closed_and_malformed_profile_is_blocked(tmp_path):
    wrapper = gate.REPO_ROOT / "scripts/metadata-fabric-identity-gate.sh"
    text = wrapper.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "metadata_fabric_identity_gate" in text

    target = tmp_path / "profile.yaml"
    target.write_text("providers: [\n", encoding="utf-8")
    report = gate.build_identity_readiness_report(profile_path=target, now=NOW)
    assert report["profile_valid"] is False
    assert report["production_identity_gate_passed"] is False
    assert gate.verify_report_integrity(report) == []


def test_attestation_never_records_material_in_success_report(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    report = gate.build_identity_readiness_report(
        profile_path=profile_path,
        attestation=_attestation(profile_path),
        now=NOW,
    )
    rendered = json.dumps(report, sort_keys=True)
    assert "client_secret" not in rendered
    assert "access_token" not in rendered
    assert report["production_identity_gate_passed"] is True
