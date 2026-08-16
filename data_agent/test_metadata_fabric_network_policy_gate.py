from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from data_agent import metadata_fabric_network_policy_gate as gate

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _write_profile(tmp_path: Path, profile: dict) -> Path:
    target = tmp_path / "network-policy-profile.yaml"
    target.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return target


def _default_profile() -> dict:
    return yaml.safe_load(gate.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))


def _complete_profile() -> dict:
    profile = _default_profile()
    profile["cluster"].update(
        {
            "decision_status": "approved",
            "cluster_reference": "cluster://production/metadata-primary",
            "kubernetes_version": "1.36.1",
        }
    )
    profile["cluster"]["cni"].update(
        {
            "provider": "cilium",
            "version": "1.19.0",
        }
    )
    profile["cluster"]["dns"].update(
        {
            "provider": "coredns",
            "namespace_selector": {
                "kubernetes.io/metadata.name": "kube-system",
            },
            "pod_selector": {"k8s-app": "kube-dns"},
        }
    )
    profile["policy"].update(
        {
            "label_admission_policy_reference": ("policy://production/workload-identity-labels-v1"),
            "policy_bundle_reference": (
                f"oci://ghcr.io/zhouning/gisdataagent/network-policy@sha256:{'a' * 64}"
            ),
            "policy_owner": "team://metadata-platform",
        }
    )
    for name, workload in profile["workloads"].items():
        service_account = name.replace("_", "-")
        workload.update(
            {
                "namespace_template": "gda-{tenant_id}",
                "service_account": service_account,
                "identity_reference": (f"identity://production/{service_account}"),
                "selector_labels": {
                    "app.kubernetes.io/name": service_account,
                    "gda.openai.com/environment": "production",
                    "gda.openai.com/workload-identity": service_account,
                },
            }
        )
    profile["tenancy"].update(
        {
            "isolation_mode": "namespace_per_tenant",
            "namespace_label_admission_policy_reference": (
                "policy://production/tenant-namespace-labels-v1"
            ),
        }
    )
    profile["traffic_matrix"] = {
        "decision_status": "approved",
        "entries": [
            {
                "id": flow_id,
                "source": source,
                "destination": destination,
                "protocol": "TCP",
                "ports": ports,
                "purpose": purpose,
                "tenant_scoped": True,
            }
            for flow_id, (source, destination, ports, purpose) in (gate.EXPECTED_FLOWS.items())
        ],
    }
    profile["operations"] = {
        "policy_log_reference": "logging://production/network-policy-audit",
        "incident_owner": "team://sre-metadata-oncall",
        "runbook": {
            "uri": "https://runbooks.gda.internal/metadata-network-policy",
            "version": "2026.07.28",
        },
        "rollback_runbook": {
            "uri": ("https://runbooks.gda.internal/metadata-network-policy-rollback"),
            "version": "2026.07.28",
        },
    }
    return profile


def _attestation(profile_path: Path, **changes: object) -> dict:
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    preliminary = gate.build_network_policy_readiness_report(
        profile_path=profile_path,
        now=NOW,
    )
    bundle_reference = profile["policy"]["policy_bundle_reference"]
    payload = {
        "schema": gate.ATTESTATION_SCHEMA,
        "environment": gate.ENVIRONMENT,
        "profile_fingerprint": preliminary["profile_fingerprint"],
        "source_revision": "b" * 40,
        "observed_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "protected_environment": gate.ENVIRONMENT,
        "verifier_identity": "identity://github/network-policy-verifier",
        "evidence_uri": ("https://evidence.gda.internal/metadata-network-policy/run-42"),
        "provider_versions": deepcopy(gate.EXPECTED_PROVIDERS),
        "cluster_binding": deepcopy(profile["cluster"]),
        "policy_bundle_digest": bundle_reference.rsplit("@sha256:", 1)[1],
        "workload_bindings_fingerprint": preliminary["workload_bindings_fingerprint"],
        "traffic_matrix_fingerprint": preliminary["traffic_matrix_fingerprint"],
        "runbook_versions": {
            "runbook": profile["operations"]["runbook"]["version"],
            "rollback_runbook": profile["operations"]["rollback_runbook"]["version"],
        },
        "checks": {check: "passed" for check in gate.EXPECTED_ATTESTATION_CHECKS},
    }
    payload["cluster_binding"].pop("decision_status")
    payload.update(changes)
    return payload


def test_checked_in_profile_is_valid_but_production_readiness_is_blocked():
    report = gate.build_network_policy_readiness_report(now=NOW)

    assert report["profile_valid"] is True
    assert report["profile_errors"] == []
    assert report["ready_for_protected_verification"] is False
    assert report["production_network_policy_gate_passed"] is False
    assert report["production_network_policy_enforcement_verified"] is False
    assert report["metadata_provider_network_policy_verified"] is False
    assert report["tenant_isolation_verified"] is False
    assert report["production_ready"] is False
    assert "cluster.cni.provider" in report["profile_blockers"]
    assert "traffic_matrix.entries.gda-control-to-openmetadata-api" in report["profile_blockers"]
    assert gate.verify_report_integrity(report) == []


def test_complete_profile_without_attestation_is_ready_only_for_verification(
    tmp_path,
):
    profile_path = _write_profile(tmp_path, _complete_profile())

    report = gate.build_network_policy_readiness_report(
        profile_path=profile_path,
        now=NOW,
    )

    assert report["profile_valid"] is True
    assert report["profile_blockers"] == []
    assert report["ready_for_protected_verification"] is True
    assert report["attestation_valid"] is False
    assert report["production_network_policy_gate_passed"] is False


def test_fresh_bound_attestation_passes_only_the_network_policy_gate(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)

    report = gate.build_network_policy_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is True
    assert report["production_network_policy_gate_passed"] is True
    assert report["production_network_policy_enforcement_verified"] is True
    assert report["metadata_provider_network_policy_verified"] is True
    assert report["tenant_isolation_verified"] is True
    assert report["production_ready"] is False
    assert gate.verify_report_integrity(report) == []


@pytest.mark.parametrize(
    ("binding_path", "changed_value"),
    [
        (("cluster_reference",), "cluster://production/metadata-secondary"),
        (("cni", "provider"), "calico"),
        (("dns", "provider"), "node-local-dns"),
    ],
)
def test_attestation_rejects_cluster_cni_and_dns_drift(
    tmp_path,
    binding_path,
    changed_value,
):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    target = attestation["cluster_binding"]
    for key in binding_path[:-1]:
        target = target[key]
    target[binding_path[-1]] = changed_value

    report = gate.build_network_policy_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is False
    assert "cluster binding does not match" in "\n".join(report["attestation_errors"])


@pytest.mark.parametrize("drift", ["identity", "selector", "admission"])
def test_attestation_rejects_workload_identity_selector_and_admission_drift(
    tmp_path,
    drift,
):
    profile = _complete_profile()
    profile_path = _write_profile(tmp_path, profile)
    attestation = _attestation(profile_path)
    if drift == "identity":
        profile["workloads"]["openmetadata"]["identity_reference"] = (
            "identity://production/openmetadata-v2"
        )
    elif drift == "selector":
        profile["workloads"]["openmetadata"]["selector_labels"]["app.kubernetes.io/name"] = (
            "openmetadata-v2"
        )
    else:
        profile["policy"]["label_admission_policy_reference"] = (
            "policy://production/workload-identity-labels-v2"
        )
    _write_profile(tmp_path, profile)

    report = gate.build_network_policy_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is False
    assert "current profile" in "\n".join(report["attestation_errors"])
    if drift != "admission":
        assert "workload bindings do not match" in "\n".join(report["attestation_errors"])


@pytest.mark.parametrize(
    "drift",
    ["missing", "extra", "port", "source", "destination"],
)
def test_traffic_matrix_rejects_missing_extra_and_changed_flows(tmp_path, drift):
    profile = _complete_profile()
    entries = profile["traffic_matrix"]["entries"]
    if drift == "missing":
        entries.pop()
    elif drift == "extra":
        extra = deepcopy(entries[0])
        extra["id"] = "unapproved-provider-path"
        entries.append(extra)
    elif drift == "port":
        entries[0]["ports"] = [443]
    elif drift == "source":
        entries[0]["source"] = "metadata_backup"
    else:
        entries[0]["destination"] = "gravitino"

    report = gate.build_network_policy_readiness_report(
        profile_path=_write_profile(tmp_path, profile),
        now=NOW,
    )

    assert report["production_network_policy_gate_passed"] is False
    if drift == "missing":
        assert report["profile_valid"] is True
        assert any(
            blocker.startswith("traffic_matrix.entries.") for blocker in report["profile_blockers"]
        )
    else:
        assert report["profile_valid"] is False
        assert "traffic flow" in "\n".join(report["profile_errors"])


@pytest.mark.parametrize(
    "check",
    [
        "denied_cross_tenant_ingress",
        "denied_cross_tenant_egress",
        "policy_log_delivery",
        "rollback_rehearsal",
    ],
)
def test_attestation_requires_cross_tenant_logging_and_rollback_checks(
    tmp_path,
    check,
):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation["checks"][check] = "failed"

    report = gate.build_network_policy_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is False
    assert check in "\n".join(report["attestation_errors"])


def test_placeholder_http_loopback_and_unpinned_bundle_are_invalid(tmp_path):
    profile = _complete_profile()
    profile["cluster"]["cluster_reference"] = "cluster://production/TBD"
    profile["operations"]["runbook"]["uri"] = "http://localhost/runbook"
    profile["operations"]["rollback_runbook"]["uri"] = "https://127.0.0.1/rollback"
    profile["policy"]["policy_bundle_reference"] = (
        "oci://ghcr.io/zhouning/gisdataagent/network-policy:latest"
    )
    profile["policy"]["policy_owner"] = "team://"

    report = gate.build_network_policy_readiness_report(
        profile_path=_write_profile(tmp_path, profile),
        now=NOW,
    )

    assert report["profile_valid"] is False
    rendered = "\n".join(report["profile_errors"])
    assert "cluster reference is invalid" in rendered
    assert "runbook URI is invalid" in rendered
    assert "rollback_runbook URI is invalid" in rendered
    assert "digest-pinned OCI" in rendered
    assert "NetworkPolicy owner is invalid" in rendered


def test_profile_rejects_sensitive_fields_and_self_asserted_claims(tmp_path):
    profile = _complete_profile()
    profile["policy"]["client_secret"] = "must-not-be-here"
    profile["policy"]["required_identity_labels"] = [{}]
    profile["claims"]["production_network_policy_gate_passed"] = True

    report = gate.build_network_policy_readiness_report(
        profile_path=_write_profile(tmp_path, profile),
        now=NOW,
    )

    assert report["profile_valid"] is False
    rendered = "\n".join(report["profile_errors"])
    assert "credential-bearing fields" in rendered
    assert "policy inventory" in rendered
    assert "identity contract does not match" in rendered
    assert "may not self-assert" in rendered


def test_attestation_rejects_sensitive_fields_and_expiry(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(
        profile_path,
        observed_at=(NOW - timedelta(days=2)).isoformat(),
        expires_at=(NOW - timedelta(days=1)).isoformat(),
        access_token="must-not-be-here",
    )

    report = gate.build_network_policy_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is False
    rendered = "\n".join(report["attestation_errors"])
    assert "credential-bearing fields" in rendered
    assert "freshness window" in rendered
    assert "expired" in rendered


def test_report_integrity_rejects_tampering_and_production_overclaim():
    report = gate.build_network_policy_readiness_report(now=NOW)
    report["production_ready"] = True
    report["tenant_isolation_verified"] = True

    errors = gate.verify_report_integrity(report)

    assert "NetworkPolicy readiness report fingerprint does not match" in errors
    assert "NetworkPolicy gate may not claim overall production readiness" in errors
    assert "NetworkPolicy gate result is inconsistent: tenant_isolation_verified" in errors

    forged = gate.build_network_policy_readiness_report(now=NOW)
    forged["unexpected_claim"] = False
    stable = {key: value for key, value in forged.items() if key != "report_fingerprint"}
    forged["report_fingerprint"] = gate.recovery._canonical_sha256(stable)

    assert "NetworkPolicy readiness report inventory does not match" in (
        gate.verify_report_integrity(forged)
    )


def test_malformed_profile_fails_closed(tmp_path):
    target = tmp_path / "profile.yaml"
    target.write_text("traffic_matrix: [\n", encoding="utf-8")

    report = gate.build_network_policy_readiness_report(
        profile_path=target,
        now=NOW,
    )

    assert report["profile_valid"] is False
    assert any("profile is invalid" in error for error in report["profile_errors"])
    assert report["production_network_policy_gate_passed"] is False
