from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.gis_service_migration_rollback import (
    GIS_SERVICE_MIGRATION_ROLLBACK_APPROVAL_SCHEMA,
    GISServiceMigrationRollback,
    GISServiceMigrationRollbackRequest,
    gis_service_migration_rollback_approval_context,
    gis_service_migration_rollback_fingerprint,
    gis_service_migration_rollback_operation_fingerprint,
)


def _request_values() -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "rollback_id": UUID("00000000-0000-4000-8000-000000000001"),
        "cutover_id": UUID("00000000-0000-4000-8000-000000000002"),
        "cutover_sha256": "a" * 64,
        "service_urn": "gda://tenant-a/gis_service/parcels",
        "from_endpoint_revision_id": UUID(
            "00000000-0000-4000-8000-000000000003"
        ),
        "to_endpoint_revision_id": UUID(
            "00000000-0000-4000-8000-000000000004"
        ),
        "expected_state_version": 2,
        "authorization_kind": "incident",
        "authorization_ref": "00000000-0000-4000-8000-000000000005",
        "actor_subject": "service:gis-migration-controller",
        "reason": "restore the last certified release",
        "idempotency_key": "rollback-parcels-v2",
        "occurred_at": datetime(2026, 8, 21, 13, tzinfo=UTC),
    }


def _rollback_values() -> dict[str, object]:
    request = _request_values()
    return {
        "tenant_id": request["tenant_id"],
        "rollback_id": request["rollback_id"],
        "cutover_id": request["cutover_id"],
        "cutover_sha256": request["cutover_sha256"],
        "service_urn": request["service_urn"],
        "from_endpoint_revision_id": request["from_endpoint_revision_id"],
        "to_endpoint_revision_id": request["to_endpoint_revision_id"],
        "from_service_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000006"
        ),
        "from_service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000007"
        ),
        "to_service_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000008"
        ),
        "to_service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000009"
        ),
        "source_product_urn": "gda://tenant-a/data_product/parcels",
        "from_product_version_id": UUID(
            "00000000-0000-4000-8000-000000000010"
        ),
        "to_product_version_id": UUID(
            "00000000-0000-4000-8000-000000000011"
        ),
        "current_binding_count": 1,
        "current_consumer_count": 1,
        "rollback_binding_count": 1,
        "rollback_consumer_count": 1,
        "rollback_binding_set_sha256": "b" * 64,
        "from_state_version": request["expected_state_version"],
        "to_state_version": 3,
        "activation_event_id": UUID(
            "00000000-0000-4000-8000-000000000012"
        ),
        "cache_transition_mode": "release_namespace_rollover",
        "authorization_kind": request["authorization_kind"],
        "authorization_ref": request["authorization_ref"],
        "authorization_sha256": "c" * 64,
        "authorization_status": "open",
        "authorization_state_version": 0,
        "actor_subject": request["actor_subject"],
        "reason": request["reason"],
        "idempotency_key": request["idempotency_key"],
        "occurred_at": request["occurred_at"],
    }


def test_rollback_request_binds_cutover_direction_and_typed_authority() -> None:
    request = GISServiceMigrationRollbackRequest(**_request_values())
    assert request.expected_state_version == 2

    invalid = _request_values()
    invalid["to_endpoint_revision_id"] = invalid["from_endpoint_revision_id"]
    with pytest.raises(ValidationError, match="rollback endpoints must differ"):
        GISServiceMigrationRollbackRequest(**invalid)

    invalid = _request_values()
    invalid["authorization_ref"] = "not-an-incident"
    with pytest.raises(ValidationError, match="incident authorization_ref"):
        GISServiceMigrationRollbackRequest(**invalid)


def test_approval_fingerprint_covers_only_the_exact_rollback_operation() -> None:
    request = GISServiceMigrationRollbackRequest(**_request_values())
    context = gis_service_migration_rollback_approval_context(request)
    assert context["schema"] == GIS_SERVICE_MIGRATION_ROLLBACK_APPROVAL_SCHEMA

    changed_actor = request.model_copy(
        update={"actor_subject": "human:incident-commander"}
    )
    assert gis_service_migration_rollback_operation_fingerprint(
        changed_actor
    ) == gis_service_migration_rollback_operation_fingerprint(request)

    changed_state = request.model_copy(update={"expected_state_version": 3})
    assert gis_service_migration_rollback_operation_fingerprint(
        changed_state
    ) != gis_service_migration_rollback_operation_fingerprint(request)


def test_rollback_receipt_fingerprint_covers_authority_and_consumer_set() -> None:
    values = _rollback_values()
    fingerprint = gis_service_migration_rollback_fingerprint(values)
    rollback = GISServiceMigrationRollback(
        **values,
        rollback_sha256=fingerprint,
    )
    assert rollback.rollback_sha256 == fingerprint
    assert rollback.to_state_version == rollback.from_state_version + 1

    unequal = dict(values)
    unequal["rollback_binding_count"] = 0
    unequal["rollback_sha256"] = gis_service_migration_rollback_fingerprint(
        unequal
    )
    with pytest.raises(ValidationError, match="rollback release consumer bindings"):
        GISServiceMigrationRollback(**unequal)


def test_rollback_receipt_rejects_authority_status_drift() -> None:
    values = _rollback_values()
    values["authorization_status"] = "approved"
    values["rollback_sha256"] = gis_service_migration_rollback_fingerprint(values)
    with pytest.raises(ValidationError, match="Incident rollback authority"):
        GISServiceMigrationRollback(**values)
