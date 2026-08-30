from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.gis_service_migration_cutover import (
    GISServiceMigrationCutover,
    GISServiceMigrationCutoverRequest,
    gis_service_migration_cutover_fingerprint,
)


def _request_values() -> dict[str, object]:
    return {
        "tenant_id": "planning",
        "cutover_id": UUID("00000000-0000-4000-8000-000000000001"),
        "service_urn": "gda://planning/gis_service/districts",
        "source_endpoint_revision_id": UUID(
            "00000000-0000-4000-8000-000000000002"
        ),
        "target_endpoint_revision_id": UUID(
            "00000000-0000-4000-8000-000000000003"
        ),
        "source_service_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000004"
        ),
        "source_service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000005"
        ),
        "target_service_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000006"
        ),
        "target_service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000007"
        ),
        "source_product_urn": "gda://planning/data_product/districts",
        "from_product_version_id": UUID(
            "00000000-0000-4000-8000-000000000008"
        ),
        "to_product_version_id": UUID(
            "00000000-0000-4000-8000-000000000009"
        ),
        "expected_state_version": 4,
        "actor_subject": "service:gis-migration-controller",
        "reason": "cut over acknowledged consumers",
        "idempotency_key": "districts-v1-to-v2",
        "occurred_at": datetime(2026, 8, 21, 12, 30, tzinfo=UTC),
    }


def _cutover_values() -> dict[str, object]:
    request = _request_values()
    request.pop("expected_state_version")
    return {
        **request,
        "source_binding_count": 2,
        "impact_count": 2,
        "acknowledged_count": 2,
        "target_binding_count": 2,
        "impact_set_sha256": "a" * 64,
        "acknowledgement_set_sha256": "b" * 64,
        "target_binding_set_sha256": "c" * 64,
        "from_state_version": 4,
        "to_state_version": 5,
        "activation_event_id": UUID(
            "00000000-0000-4000-8000-000000000010"
        ),
        "cache_transition_mode": "release_namespace_rollover",
    }


def test_cutover_request_requires_distinct_exact_release_lineage() -> None:
    request = GISServiceMigrationCutoverRequest.model_validate(_request_values())
    assert request.expected_state_version == 4

    invalid = _request_values()
    invalid["target_endpoint_revision_id"] = invalid[
        "source_endpoint_revision_id"
    ]
    with pytest.raises(ValidationError, match="cutover endpoints must differ"):
        GISServiceMigrationCutoverRequest.model_validate(invalid)


def test_cutover_fingerprint_covers_complete_equal_consumer_sets() -> None:
    values = _cutover_values()
    fingerprint = gis_service_migration_cutover_fingerprint(values)
    cutover = GISServiceMigrationCutover(
        **values,
        cutover_sha256=fingerprint,
    )

    assert cutover.cutover_sha256 == fingerprint
    assert cutover.to_state_version == cutover.from_state_version + 1

    unequal = {**values, "target_binding_count": 1}
    unequal["cutover_sha256"] = gis_service_migration_cutover_fingerprint(
        unequal
    )
    with pytest.raises(ValidationError, match="same set"):
        GISServiceMigrationCutover.model_validate(unequal)


def test_cutover_rejects_a_stale_fingerprint() -> None:
    values = _cutover_values()
    with pytest.raises(ValidationError, match="cutover_sha256"):
        GISServiceMigrationCutover(
            **values,
            cutover_sha256="f" * 64,
        )
