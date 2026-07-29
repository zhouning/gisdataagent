from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from data_agent import metadata_fabric_object_store_gate as gate


NOW = datetime(2026, 7, 29, 14, 0, tzinfo=UTC)


def _write_profile(tmp_path: Path, profile: dict) -> Path:
    path = tmp_path / "object-store-profile.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return path


def _checked_profile() -> dict:
    return gate._load_yaml_object(gate.DEFAULT_PROFILE_PATH)


def _complete_profile(provider_type: str = "aws_s3") -> dict:
    profile = deepcopy(_checked_profile())
    profile["provider"].update(
        {
            "decision_status": "approved",
            "provider_type": provider_type,
            "account_reference": "cloud://aws/accounts/gda-production",
            "region": "ap-northeast-1",
            "endpoint": "https://s3.ap-northeast-1.amazonaws.com",
            "bucket": "gda-prod-lakehouse-01",
            "infrastructure_reference": "iac://gda-production/object-store/v1",
            "failure_domain_reference": "cloud://aws/failure-domains/ap-northeast-1",
            "recovery_region": "ap-northeast-3",
        }
    )
    profile["identity"].update(
        {
            "integration_mode": "oidc_workload_federation",
            "workload_identity_reference": "iam://gda-production/lakehouse-writer",
            "kubernetes_service_account": "gda-lakehouse-writer",
            "least_privilege_policy_reference": "policy://object-store/lakehouse-writer/v1",
            "bucket_policy_reference": "policy://object-store/bucket-boundary/v1",
        }
    )
    profile["transport"].update(
        {
            "endpoint": profile["provider"]["endpoint"],
            "private_connectivity_reference": "network://gda-production/object-store-private-path",
            "dns_policy_reference": "dns://gda-production/object-store/v1",
            "trust_bundle_reference": "pki://gda-production/object-store-ca/v1",
            "certificate_policy_reference": "pki://gda-production/object-store-certificate/v1",
        }
    )
    profile["encryption"].update(
        {
            "key_reference": "kms://gda-production/lakehouse-key/v1",
            "key_policy_reference": "policy://kms/lakehouse-key/v1",
            "rotation_days": 365,
        }
    )
    profile["durability"].update(
        {
            "retention_policy_reference": "policy://object-store/retention/v1",
            "replication_policy_reference": "policy://object-store/cross-region-replication/v1",
            "recovery_bucket_reference": "s3://gda-prod-lakehouse-recovery",
        }
    )
    profile["consistency"].update(
        {
            "multipart_upload_cleanup_reference": "policy://object-store/multipart-cleanup/v1",
            "orphan_file_cleanup_reference": "policy://iceberg/orphan-file-cleanup/v1",
        }
    )
    profile["tenancy"]["policy_reference"] = "policy://object-store/tenant-isolation/v1"
    profile["operations"].update(
        {
            "platform_owner": "owner://teams/data-platform",
            "security_owner": "owner://teams/security",
            "storage_owner": "owner://teams/storage-sre",
            "incident_owner": "owner://teams/platform-oncall",
            "audit_log_reference": "observability://object-store/audit/v1",
            "metrics_alert_reference": "observability://object-store/alerts/v1",
            "availability_slo_percent": 99.95,
            "latency_slo_ms": 250,
            "runbook": {
                "uri": "https://runbooks.gisdataagent.cn/object-store/operations",
                "version": "v1",
            },
            "recovery_runbook": {
                "uri": "https://runbooks.gisdataagent.cn/object-store/recovery",
                "version": "v1",
            },
            "rollback_runbook": {
                "uri": "https://runbooks.gisdataagent.cn/object-store/rollback",
                "version": "v1",
            },
            "attestation_policy_reference": "policy://protected-environments/object-store/v1",
        }
    )
    return profile


def _attestation(profile_path: Path, **overrides) -> dict:
    profile = gate._load_yaml_object(profile_path)
    report = gate.build_object_store_readiness_report(
        profile_path=profile_path, now=NOW
    )
    attestation = {
        "schema": gate.ATTESTATION_SCHEMA,
        "environment": gate.ENVIRONMENT,
        "repository": gate.REPOSITORY,
        "protected_environment": gate.PROTECTED_ENVIRONMENT,
        "source_revision": "a" * 40,
        "profile_fingerprint": report["profile_fingerprint"],
        "local_evidence_fingerprint": gate.LOCAL_EVIDENCE["evidence_fingerprint"],
        "engine_versions": dict(gate.EXPECTED_ENGINES),
        **{
            f"{name}_fingerprint": report[f"{name}_fingerprint"]
            for name in gate.BINDING_SECTIONS
        },
        "observed_at": (NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "evidence_uri": "https://evidence.gisdataagent.cn/object-store/run-20260729",
        "checks": {name: "passed" for name in sorted(gate.EXPECTED_CHECKS)},
        "claims": {
            name: name != "production_ready" for name in sorted(gate.PROFILE_CLAIMS)
        },
        "runbook_versions": {
            name: profile["operations"][name]["version"]
            for name in ("runbook", "recovery_runbook", "rollback_runbook")
        },
    }
    attestation.update(overrides)
    return attestation


def test_checked_profile_is_valid_pending_and_fail_closed():
    report = gate.build_object_store_readiness_report(now=NOW)

    assert report["profile_valid"] is True
    assert report["profile_errors"] == []
    assert len(report["profile_blockers"]) == 43
    assert report["ready_for_protected_verification"] is False
    assert report["attestation_valid"] is False
    assert report["production_object_store_gate_passed"] is False
    assert report["production_object_store_verified"] is False
    assert report["protected_workload_identity_verified"] is False
    assert report["tls_verified"] is False
    assert report["production_ready"] is False
    assert report["profile_fingerprint"] == (
        "668e194b3c688307014148391e7f389c9d6e9ca69c95d7b4cc92b4acae93181a"
    )
    assert report["report_fingerprint"] == (
        "85362dd10b7dc565f9fa567673d90b774cdec714bd1e70fb2c3c83c1af48b5ea"
    )
    assert gate.verify_report_integrity(report) == []


def test_checked_profile_binds_verified_local_interoperability_evidence():
    evidence = gate._load_json_object(gate.REPO_ROOT / gate.LOCAL_EVIDENCE["path"])

    assert gate.local_interop.verify_evidence_integrity(evidence) == []
    assert evidence[gate.LOCAL_EVIDENCE["required_claim"]] is True
    assert evidence["production_object_store_verified"] is False
    assert evidence["spark_conformance_verified"] is False
    assert evidence["production_ready"] is False


def test_complete_profile_is_ready_but_cannot_self_attest(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())

    report = gate.build_object_store_readiness_report(
        profile_path=profile_path, now=NOW
    )

    assert report["profile_valid"] is True
    assert report["profile_blockers"] == []
    assert report["ready_for_protected_verification"] is True
    assert report["attestation_valid"] is False
    assert report["production_object_store_gate_passed"] is False
    assert report["production_ready"] is False


def test_fresh_fully_bound_attestation_passes_only_object_store_gate(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())

    report = gate.build_object_store_readiness_report(
        profile_path=profile_path,
        attestation=_attestation(profile_path),
        now=NOW,
    )

    assert report["attestation_valid"] is True
    for claim in gate.REPORT_CLAIMS:
        assert report[claim] is True
    assert report["production_ready"] is False
    assert gate.verify_report_integrity(report) == []


@pytest.mark.parametrize("provider_type", sorted(gate.ALLOWED_PROVIDERS))
def test_profile_accepts_only_s3_compatible_provider_families(tmp_path, provider_type):
    profile_path = _write_profile(tmp_path, _complete_profile(provider_type))
    report = gate.build_object_store_readiness_report(
        profile_path=profile_path, now=NOW
    )
    assert report["profile_valid"] is True
    assert report["ready_for_protected_verification"] is True


def test_profile_rejects_native_non_s3_provider_without_new_conformance(tmp_path):
    profile = _complete_profile("gcs_native")
    report = gate.build_object_store_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )
    assert report["profile_valid"] is False
    assert "provider type is invalid" in "\n".join(report["profile_errors"])


def test_profile_rejects_static_credentials_http_public_access_and_same_region(tmp_path):
    profile = _complete_profile()
    profile["identity"]["static_credentials_forbidden"] = False
    profile["provider"]["endpoint"] = "http://localhost:9000"
    profile["transport"]["endpoint"] = "http://localhost:9000"
    profile["tenancy"]["public_access_blocked"] = False
    profile["provider"]["recovery_region"] = profile["provider"]["region"]

    report = gate.build_object_store_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )
    rendered = "\n".join(report["profile_errors"])
    assert report["profile_valid"] is False
    assert "credential baseline" in rendered
    assert "provider endpoint is invalid" in rendered
    assert "transport endpoint is invalid" in rendered
    assert "tenancy baseline" in rendered
    assert "recovery region must be distinct" in rendered


def test_profile_rejects_privilege_expansion_and_local_evidence_drift(tmp_path):
    profile = _complete_profile()
    profile["identity"]["allowed_operations"].append("s3:PutBucketPolicy")
    profile["scope"]["local_evidence"]["evidence_fingerprint"] = "0" * 64

    report = gate.build_object_store_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )
    rendered = "\n".join(report["profile_errors"])
    assert report["profile_valid"] is False
    assert "least-privilege operation inventory" in rendered
    assert "local object-store evidence binding" in rendered


def test_profile_rejects_sensitive_fields_and_self_asserted_claims(tmp_path):
    profile = _complete_profile()
    profile["identity"]["secret_access_key"] = "must-not-enter-profile"
    profile["claims"]["production_object_store_verified"] = True

    report = gate.build_object_store_readiness_report(
        profile_path=_write_profile(tmp_path, profile), now=NOW
    )
    rendered = "\n".join(report["profile_errors"])
    assert report["profile_valid"] is False
    assert "credential-bearing fields" in rendered
    assert "identity inventory" in rendered
    assert "may not self-assert production_object_store_verified" in rendered


@pytest.mark.parametrize(
    "binding",
    ["profile_fingerprint", *[f"{name}_fingerprint" for name in gate.BINDING_SECTIONS]],
)
def test_attestation_rejects_every_profile_binding_drift(tmp_path, binding):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation[binding] = "0" * 64

    report = gate.build_object_store_readiness_report(
        profile_path=profile_path, attestation=attestation, now=NOW
    )

    assert report["attestation_valid"] is False
    assert "does not bind the current profile" in "\n".join(
        report["attestation_errors"]
    ) or "binding does not match" in "\n".join(report["attestation_errors"])


def test_attestation_rejects_sensitive_material_expiry_and_dependency_drift(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(
        profile_path,
        observed_at=(NOW - timedelta(days=2)).isoformat(),
        expires_at=(NOW - timedelta(days=1)).isoformat(),
        secret_access_key="must-not-enter-attestation",
    )
    attestation["local_evidence_fingerprint"] = "0" * 64

    report = gate.build_object_store_readiness_report(
        profile_path=profile_path, attestation=attestation, now=NOW
    )
    rendered = "\n".join(report["attestation_errors"])
    assert report["attestation_valid"] is False
    assert "credential-bearing fields" in rendered
    assert "freshness window" in rendered
    assert "expiry is invalid" in rendered
    assert "dependency bindings" in rendered


@pytest.mark.parametrize(
    "check",
    [
        "static_credentials_absent",
        "administrative_action_denied",
        "cross_tenant_denial",
        "kms_key_rotation",
        "commit_failure_recovery",
        "source_cluster_loss_recovery",
        "rollback_rehearsal",
    ],
)
def test_attestation_requires_security_durability_and_recovery_checks(tmp_path, check):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation["checks"][check] = "failed"

    report = gate.build_object_store_readiness_report(
        profile_path=profile_path, attestation=attestation, now=NOW
    )

    assert report["attestation_valid"] is False
    assert check in "\n".join(report["attestation_errors"])
    assert report["production_object_store_verified"] is False


def test_attestation_rejects_runbook_version_and_overall_production_overclaim(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation["runbook_versions"]["recovery_runbook"] = "v2"
    attestation["claims"]["production_ready"] = True

    report = gate.build_object_store_readiness_report(
        profile_path=profile_path, attestation=attestation, now=NOW
    )
    rendered = "\n".join(report["attestation_errors"])
    assert report["attestation_valid"] is False
    assert "runbook versions do not match" in rendered
    assert "may not claim overall production readiness" in rendered


def test_report_integrity_rejects_tampering_inventory_and_production_overclaim():
    report = gate.build_object_store_readiness_report(now=NOW)
    report["production_ready"] = True
    report["tls_verified"] = True

    errors = gate.verify_report_integrity(report)

    assert "object-store readiness report fingerprint does not match" in errors
    assert "object-store gate may not claim overall production readiness" in errors
    assert "object-store gate result is inconsistent: tls_verified" in errors

    forged = gate.build_object_store_readiness_report(now=NOW)
    forged["unexpected_claim"] = False
    stable = {key: value for key, value in forged.items() if key != "report_fingerprint"}
    forged["report_fingerprint"] = gate.recovery._canonical_sha256(stable)
    assert "object-store readiness report inventory does not match" in (
        gate.verify_report_integrity(forged)
    )


def test_wrapper_is_fail_closed_and_malformed_profile_is_blocked(tmp_path):
    text = gate.DEFAULT_WRAPPER_PATH.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "metadata_fabric_object_store_gate" in text

    target = tmp_path / "profile.yaml"
    target.write_text("provider: [\n", encoding="utf-8")
    report = gate.build_object_store_readiness_report(profile_path=target, now=NOW)
    assert report["profile_valid"] is False
    assert report["production_object_store_gate_passed"] is False
    assert gate.verify_report_integrity(report) == []


def test_attestation_never_records_material_in_success_or_failure_report(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    successful = gate.build_object_store_readiness_report(
        profile_path=profile_path,
        attestation=_attestation(profile_path),
        now=NOW,
    )
    failed_attestation = _attestation(profile_path, secret_access_key="not-recorded")
    failed = gate.build_object_store_readiness_report(
        profile_path=profile_path,
        attestation=failed_attestation,
        now=NOW,
    )

    for report in (successful, failed):
        rendered = json.dumps(report, sort_keys=True)
        assert "secret_access_key" not in rendered
        assert "not-recorded" not in rendered
    assert successful["production_object_store_gate_passed"] is True
    assert failed["production_object_store_gate_passed"] is False
