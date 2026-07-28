import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from data_agent import metadata_fabric_observability_gate as gate


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _write_profile(tmp_path: Path, profile: dict) -> Path:
    target = tmp_path / "observability-profile.yaml"
    target.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return target


def _default_profile() -> dict:
    return yaml.safe_load(gate.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))


def _complete_profile() -> dict:
    profile = _default_profile()
    providers = profile["scope"]["providers"]
    providers["openmetadata"]["environment_binding"] = (
        "environment://production/openmetadata"
    )
    providers["gravitino"]["environment_binding"] = (
        "environment://production/gravitino"
    )
    profile["backend"].update(
        {
            "decision_status": "approved",
            "type": "managed_prometheus",
            "write_endpoint": "https://metrics-write.gda.internal/api/v1/write",
            "query_endpoint": "https://metrics-query.gda.internal/api/v1/query",
            "durable_storage": True,
            "retention_days": 90,
        }
    )
    profile["security"]["workload_identity_reference"] = (
        "identity://production/metadata-observability-writer"
    )
    profile["tenancy"].update(
        {
            "isolation_mode": "label_policy_enforced",
            "tenant_label": "gda_tenant_id",
        }
    )
    operations = profile["operations"]
    operations.update(
        {
            "dashboard_owner": "team://metadata-platform",
            "alert_owner": "team://sre-metadata-oncall",
            "slo_owner": "team://metadata-platform",
            "notification_channel_reference": "pager://sre-metadata-primary",
            "slos": [
                {
                    "id": "openmetadata-metrics-availability",
                    "provider": "openmetadata",
                    "objective": "scrape_availability",
                    "target_percent": 99.9,
                    "window_days": 30,
                    "threshold": {
                        "operator": "lt",
                        "value": 1,
                        "unit": "up",
                    },
                    "recovery_notification_required": True,
                },
                {
                    "id": "gravitino-metrics-availability",
                    "provider": "gravitino",
                    "objective": "scrape_availability",
                    "target_percent": 99.9,
                    "window_days": 30,
                    "threshold": {
                        "operator": "lt",
                        "value": 1,
                        "unit": "up",
                    },
                    "recovery_notification_required": True,
                },
                {
                    "id": "metadata-metrics-freshness",
                    "provider": "metadata_fabric",
                    "objective": "metrics_freshness",
                    "target_percent": 99.5,
                    "window_days": 30,
                    "threshold": {
                        "operator": "gt",
                        "value": 120,
                        "unit": "seconds",
                    },
                    "recovery_notification_required": True,
                },
            ],
            "runbook": {
                "uri": "https://runbooks.gda.internal/metadata-fabric-observability",
                "version": "2026.07.28",
            },
        }
    )
    return profile


def _attestation(profile_path: Path, **changes: object) -> dict:
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    preliminary = gate.build_observability_readiness_report(
        profile_path=profile_path,
        now=NOW,
    )
    payload = {
        "schema": gate.ATTESTATION_SCHEMA,
        "environment": gate.ENVIRONMENT,
        "profile_fingerprint": preliminary["profile_fingerprint"],
        "source_revision": "a" * 40,
        "observed_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "protected_environment": gate.ENVIRONMENT,
        "verifier_identity": "identity://github/metadata-observability-verifier",
        "evidence_uri": (
            "https://evidence.gda.internal/metadata-observability/run-42"
        ),
        "provider_versions": deepcopy(gate.EXPECTED_PROVIDERS),
        "backend_binding": {
            key: profile["backend"][key]
            for key in (
                "type",
                "write_endpoint",
                "query_endpoint",
                "retention_days",
            )
        },
        "runbook_version": profile["operations"]["runbook"]["version"],
        "checks": {
            check: "passed" for check in gate.EXPECTED_ATTESTATION_CHECKS
        },
    }
    payload.update(changes)
    return payload


def test_checked_in_profile_is_valid_but_production_readiness_is_blocked():
    report = gate.build_observability_readiness_report(now=NOW)

    assert report["profile_valid"] is True
    assert report["profile_errors"] == []
    assert report["ready_for_protected_verification"] is False
    assert report["production_observability_gate_passed"] is False
    assert report["production_ready"] is False
    assert "backend.decision_status" in report["profile_blockers"]
    assert "operations.alert_owner" in report["profile_blockers"]
    assert "operations.slos.metadata-metrics-freshness" in report[
        "profile_blockers"
    ]
    assert gate.verify_report_integrity(report) == []


def test_complete_profile_without_attestation_is_ready_only_for_verification(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())

    report = gate.build_observability_readiness_report(
        profile_path=profile_path,
        now=NOW,
    )

    assert report["profile_valid"] is True
    assert report["profile_blockers"] == []
    assert report["ready_for_protected_verification"] is True
    assert report["attestation_valid"] is False
    assert report["production_observability_gate_passed"] is False


def test_fresh_bound_attestation_passes_only_the_observability_gate(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)

    report = gate.build_observability_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is True
    assert report["production_observability_gate_passed"] is True
    assert report["production_ready"] is False
    assert gate.verify_report_integrity(report) == []


def test_placeholder_http_and_loopback_values_are_invalid(tmp_path):
    profile = _complete_profile()
    profile["backend"]["write_endpoint"] = "http://localhost:9090/api/v1/write"
    profile["backend"]["query_endpoint"] = "https://127.0.0.1:9090/api/v1/query"
    profile["operations"]["alert_owner"] = "TBD"

    report = gate.build_observability_readiness_report(
        profile_path=_write_profile(tmp_path, profile),
        now=NOW,
    )

    assert report["profile_valid"] is False
    rendered = "\n".join(report["profile_errors"])
    assert "write_endpoint" in rendered
    assert "query_endpoint" in rendered
    assert "alert_owner is a placeholder" in rendered
    assert report["production_observability_gate_passed"] is False


def test_missing_owner_slo_and_runbook_are_valid_explicit_blockers(tmp_path):
    profile = _complete_profile()
    profile["operations"]["alert_owner"] = None
    profile["operations"]["slos"] = []
    profile["operations"]["runbook"] = {"uri": None, "version": None}

    report = gate.build_observability_readiness_report(
        profile_path=_write_profile(tmp_path, profile),
        now=NOW,
    )

    assert report["profile_valid"] is True
    assert "operations.alert_owner" in report["profile_blockers"]
    assert "operations.slos.openmetadata-metrics-availability" in report[
        "profile_blockers"
    ]
    assert "operations.runbook.uri" in report["profile_blockers"]


def test_profile_rejects_sensitive_fields_and_self_asserted_claims(tmp_path):
    profile = _complete_profile()
    profile["security"]["client_secret"] = "must-not-be-here"
    profile["claims"]["production_observability_gate_passed"] = True

    report = gate.build_observability_readiness_report(
        profile_path=_write_profile(tmp_path, profile),
        now=NOW,
    )

    assert report["profile_valid"] is False
    rendered = "\n".join(report["profile_errors"])
    assert "credential-bearing fields" in rendered
    assert "metrics security inventory" in rendered
    assert "may not self-assert" in rendered


def test_expired_attestation_fails_closed(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(
        profile_path,
        observed_at=(NOW - timedelta(days=2)).isoformat(),
        expires_at=(NOW - timedelta(days=1)).isoformat(),
    )

    report = gate.build_observability_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is False
    assert any("freshness window" in error for error in report["attestation_errors"])
    assert any("expired" in error for error in report["attestation_errors"])


def test_attestation_must_bind_profile_provider_backend_and_runbook(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation["profile_fingerprint"] = "0" * 64
    attestation["provider_versions"]["gravitino"] = "9.9.9"
    attestation["backend_binding"]["retention_days"] = 30
    attestation["runbook_version"] = "stale"

    report = gate.build_observability_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    rendered = "\n".join(report["attestation_errors"])
    assert report["attestation_valid"] is False
    assert "current profile" in rendered
    assert "provider versions" in rendered
    assert "backend binding" in rendered
    assert "runbook version" in rendered


def test_firing_and_recovery_notifications_are_both_required(tmp_path):
    profile_path = _write_profile(tmp_path, _complete_profile())
    attestation = _attestation(profile_path)
    attestation["checks"]["recovery_notification_delivery"] = "failed"

    report = gate.build_observability_readiness_report(
        profile_path=profile_path,
        attestation=attestation,
        now=NOW,
    )

    assert report["attestation_valid"] is False
    assert "recovery_notification_delivery" in "\n".join(
        report["attestation_errors"]
    )


def test_report_integrity_rejects_tampering_and_overall_production_overclaim():
    report = gate.build_observability_readiness_report(now=NOW)
    report["production_ready"] = True

    errors = gate.verify_report_integrity(report)

    assert "observability readiness report fingerprint does not match" in errors
    assert "observability gate may not claim overall production readiness" in errors


def test_malformed_profile_fails_closed(tmp_path):
    target = tmp_path / "profile.yaml"
    target.write_text("backend: [\n", encoding="utf-8")

    report = gate.build_observability_readiness_report(
        profile_path=target,
        now=NOW,
    )

    assert report["profile_valid"] is False
    assert any("profile is invalid" in error for error in report["profile_errors"])
    assert report["production_observability_gate_passed"] is False
