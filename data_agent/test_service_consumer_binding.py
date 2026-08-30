"""Contracts for exact-release GIS service consumer authorization."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from data_agent.service_consumer_binding import (
    ServiceConsumerBinding,
    service_consumer_binding_fingerprint,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _payload() -> dict:
    values = {
        "tenant_id": "planning",
        "service_consumer_binding_id": UUID("00000000-0000-4000-8000-000000000901"),
        "service_urn": "gda://planning/gis_service/district-features",
        "service_definition_version_id": UUID("00000000-0000-4000-8000-000000000902"),
        "service_release_binding_id": UUID("00000000-0000-4000-8000-000000000903"),
        "consumer_ref": "human:analyst-01",
        "action": "mvt.read",
        "purpose": "gis_mvt_read",
        "scope": {"operations": ["read"]},
        "credential_ref": "credential:district-map-reader",
        "expires_at": NOW + timedelta(days=1),
        "compatibility_fingerprint": "a" * 64,
        "compatibility_evidence": {
            "schema": "gda.service_consumer_binding_compatibility.v1",
            "release_key": "v1.0.0",
        },
        "created_by": "human:data-steward",
        "created_at": NOW,
    }
    values["binding_sha256"] = service_consumer_binding_fingerprint(values)
    return values


def test_exact_release_service_binding_is_tamper_evident() -> None:
    binding = ServiceConsumerBinding.model_validate(_payload())

    assert service_consumer_binding_fingerprint(binding) == binding.binding_sha256

    tampered = binding.model_dump(mode="python")
    tampered["service_release_binding_id"] = UUID(
        "00000000-0000-4000-8000-000000000904"
    )
    with pytest.raises(ValueError, match="binding_sha256"):
        ServiceConsumerBinding.model_validate(tampered)


def test_mapping_fingerprint_normalizes_uuid_and_timestamp_values() -> None:
    payload = _payload()

    assert service_consumer_binding_fingerprint(payload) == payload["binding_sha256"]


def test_ogc_features_profile_has_its_own_action_and_purpose() -> None:
    payload = _payload()
    payload["action"] = "ogc_features.read"
    payload["purpose"] = "ogc_features_read"
    payload["binding_sha256"] = service_consumer_binding_fingerprint(payload)

    binding = ServiceConsumerBinding.model_validate(payload)
    assert binding.action == "ogc_features.read"
    assert binding.purpose == "ogc_features_read"


def test_ogc_features_profile_rejects_mismatched_purpose() -> None:
    payload = _payload()
    payload["action"] = "ogc_features.read"
    payload["purpose"] = "gis_mvt_read"
    payload["binding_sha256"] = service_consumer_binding_fingerprint(payload)

    with pytest.raises(ValueError, match="action and purpose"):
        ServiceConsumerBinding.model_validate(payload)


def test_service_binding_migration_is_rls_guarded_and_recorder_only() -> None:
    migration = (
        Path(__file__).parent / "migrations/212_gis_service_consumer_binding.sql"
    ).read_text(encoding="utf-8")

    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "guard_service_consumer_binding_insert" in migration
    assert "record_service_consumer_binding" in migration
    assert "set_config('gda.service_consumer_binding_allowed', '1', true)" in migration
    assert "REVOKE ALL ON TABLE gda_control.service_consumer_binding" in migration
    assert "GRANT SELECT ON TABLE gda_control.service_consumer_binding" in migration
    assert "GRANT EXECUTE ON FUNCTION gda_control.record_service_consumer_binding" in migration


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("service_urn", "gda://planning/data_product/districts", "GIS service"),
        ("scope", {"operations": ["metadata.read"]}, "scope"),
        ("expires_at", NOW, "expires_at"),
    ],
)
def test_service_binding_rejects_non_mvt_or_invalid_lifetime(
    field: str, value: object, message: str
) -> None:
    payload = _payload()
    payload[field] = value
    payload["binding_sha256"] = service_consumer_binding_fingerprint(payload)

    with pytest.raises(ValueError, match=message):
        ServiceConsumerBinding.model_validate(payload)
