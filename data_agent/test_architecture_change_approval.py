"""Contract tests for architecture drift admission into ApprovalCase."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.architecture_change_approval import (
    ARCHITECTURE_CHANGE_REVIEW_ACTION,
    ArchitectureChangeApprovalError,
    ArchitectureChangeReview,
    build_architecture_change_approval_case,
    build_architecture_change_review,
)
from data_agent.data_architecture_ledger import (
    ArchitectureProviderObservation,
    ArchitectureReconciliationStatus,
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ProviderObjectState,
    ResourceVersionArchitecture,
    ResourceVersionArchitectureBinding,
    ResourceVersionArchitectureReconciliation,
    SchemaVersion,
    architecture_binding_fingerprint,
    architecture_provider_observation_fingerprint,
    data_contract_version_fingerprint,
    physical_location_fingerprint,
    schema_version_fingerprint,
)
from data_agent.platform_contracts import ResourceVersion

NOW = datetime(2026, 8, 3, 9, tzinfo=UTC)
TENANT = "architecture-approval"
RESOURCE_URN = f"gda://{TENANT}/dataset/parcels"
RESOURCE_VERSION_ID = UUID("10000000-0000-4000-8000-000000000001")
OBSERVATION_ID = UUID("20000000-0000-4000-8000-000000000001")


def _registration() -> DataArchitectureRegistration:
    schema_values = {
        "tenant_id": TENANT,
        "resource_version_id": RESOURCE_VERSION_ID,
        "schema_format": "postgresql_catalog_v1",
        "authority_system": "provider",
        "authority_namespace": "postgis/public",
        "authority_object_id": "parcels",
        "authority_version_ref": "revision:1",
    }
    schema = SchemaVersion(
        schema_version_id=UUID("30000000-0000-4000-8000-000000000001"),
        schema_sha256=schema_version_fingerprint(**schema_values),
        created_by="workload:postgis-harvester",
        created_at=NOW,
        **schema_values,
    )
    contract_values = {
        "tenant_id": TENANT,
        "resource_version_id": RESOURCE_VERSION_ID,
        "contract_kind": "data_product_input",
        "enforcement_mode": "required",
        "authority_system": "openmetadata",
        "authority_namespace": "table",
        "authority_object_id": "parcels-contract",
        "authority_version_ref": "version:1",
    }
    contract = DataContractVersion(
        data_contract_version_id=UUID("40000000-0000-4000-8000-000000000001"),
        contract_sha256=data_contract_version_fingerprint(**contract_values),
        created_by="workload:governance-harvester",
        created_at=NOW,
        **contract_values,
    )
    location_values = {
        "tenant_id": TENANT,
        "resource_version_id": RESOURCE_VERSION_ID,
        "location_kind": "postgis_table",
        "provider_system": "postgis",
        "provider_namespace": "public",
        "provider_locator": "postgresql://provider/public/parcels",
        "snapshot_ref": "snapshot:1",
        "revision_ref": "relation:1",
        "checksum_algorithm": "sha256",
        "content_checksum": "a" * 64,
    }
    location = PhysicalLocation(
        physical_location_id=UUID("50000000-0000-4000-8000-000000000001"),
        location_sha256=physical_location_fingerprint(**location_values),
        created_by="workload:postgis-harvester",
        created_at=NOW,
        **location_values,
    )
    binding_values = {
        "tenant_id": TENANT,
        "resource_version_id": RESOURCE_VERSION_ID,
        "schema_version_id": schema.schema_version_id,
        "data_contract_version_id": contract.data_contract_version_id,
        "physical_location_id": location.physical_location_id,
    }
    binding = ResourceVersionArchitectureBinding(
        binding_sha256=architecture_binding_fingerprint(**binding_values),
        bound_by="workload:architecture-controller",
        bound_at=NOW,
        **binding_values,
    )
    return DataArchitectureRegistration(
        schema_version=schema,
        data_contract_version=contract,
        physical_location=location,
        binding=binding,
    )


def _resource_version() -> ResourceVersion:
    return ResourceVersion(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_version_id=RESOURCE_VERSION_ID,
        version_key="snapshot-1",
        content_sha256="a" * 64,
        authority_version_ref={"snapshot": "snapshot:1"},
        created_by="workload:source-controller",
        created_at=NOW,
    )


def _reconciliation(
    status: ArchitectureReconciliationStatus = ArchitectureReconciliationStatus.SCHEMA_DRIFT,
) -> ResourceVersionArchitectureReconciliation:
    registration = _registration()
    architecture = ResourceVersionArchitecture(
        tenant_id=TENANT,
        resource_version_id=RESOURCE_VERSION_ID,
        architecture_ready=True,
        missing_components=(),
        schema_version_record=registration.schema_version,
        data_contract_version_record=registration.data_contract_version,
        physical_location=registration.physical_location,
        binding=registration.binding,
    )
    tombstoned = status is ArchitectureReconciliationStatus.TOMBSTONED
    candidate_schema = None if tombstoned else "b" * 64
    candidate_location = None if tombstoned else registration.physical_location.location_sha256
    observation_values = {
        "tenant_id": TENANT,
        "resource_version_id": RESOURCE_VERSION_ID,
        "provider_system": "postgis",
        "provider_namespace": "public",
        "provider_object_id": "parcels",
        "object_state": (
            ProviderObjectState.TOMBSTONED if tombstoned else ProviderObjectState.PRESENT
        ),
        "source_revision": None if tombstoned else "relation:2",
        "schema_content_sha256": None if tombstoned else "c" * 64,
        "schema_version_sha256": candidate_schema,
        "physical_location_sha256": candidate_location,
        "observed_at": NOW + timedelta(minutes=1),
        "fresh_until": NOW + timedelta(minutes=6),
    }
    observation = ArchitectureProviderObservation(
        observation_id=OBSERVATION_ID,
        observation_sha256=architecture_provider_observation_fingerprint(**observation_values),
        observed_by="workload:postgis-harvester",
        recorded_at=NOW + timedelta(minutes=1),
        **observation_values,
    )
    actions = {
        ArchitectureReconciliationStatus.SCHEMA_DRIFT: ("review_schema_drift",),
        ArchitectureReconciliationStatus.TOMBSTONED: ("investigate_tombstone",),
    }.get(status, ("refresh_observation",))
    return ResourceVersionArchitectureReconciliation(
        tenant_id=TENANT,
        resource_version_id=RESOURCE_VERSION_ID,
        status=status,
        architecture=architecture,
        latest_observation=observation,
        schema_matches=False if not tombstoned else None,
        location_matches=True if not tombstoned else None,
        evaluated_at=NOW + timedelta(minutes=2),
        required_actions=actions,
    )


def test_schema_drift_builds_bounded_deterministic_approval_case() -> None:
    review = build_architecture_change_review(_resource_version(), _reconciliation())
    case = build_architecture_change_approval_case(
        review,
        requester_subject="agent:architecture-reviewer",
        request_reason="provider schema drift requires steward review",
        requested_at=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(hours=2),
    )

    assert case.action == ARCHITECTURE_CHANGE_REVIEW_ACTION
    assert case.target_resource_urn == RESOURCE_URN
    assert case.target_fingerprint == review.review_sha256
    assert case.approval_case_ref.endswith(OBSERVATION_ID.hex)
    assert set(case.request_context) == {
        "resource_version_id",
        "observation_id",
        "observation_sha256",
        "binding_sha256",
        "reconciliation_status",
        "candidate_schema_sha256",
        "candidate_location_sha256",
        "required_actions",
    }
    assert "schema_content" not in case.model_dump_json()
    assert case == build_architecture_change_approval_case(
        review,
        requester_subject="agent:architecture-reviewer",
        request_reason="provider schema drift requires steward review",
        requested_at=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(hours=2),
    )


def test_tombstone_has_a_distinct_case_without_candidate_fingerprints() -> None:
    review = build_architecture_change_review(
        _resource_version(),
        _reconciliation(ArchitectureReconciliationStatus.TOMBSTONED),
    )

    assert review.reconciliation_status is ArchitectureReconciliationStatus.TOMBSTONED
    assert review.candidate_schema_sha256 is None
    assert review.candidate_location_sha256 is None
    assert review.required_actions == ("investigate_tombstone",)


def test_tombstone_rejects_copied_component_match_flags() -> None:
    reconciliation = _reconciliation(ArchitectureReconciliationStatus.TOMBSTONED).model_copy(
        update={"schema_matches": False}
    )

    with pytest.raises(ArchitectureChangeApprovalError, match="component matches"):
        build_architecture_change_review(_resource_version(), reconciliation)


@pytest.mark.parametrize(
    "status",
    [
        ArchitectureReconciliationStatus.UNOBSERVED,
        ArchitectureReconciliationStatus.UNBOUND,
        ArchitectureReconciliationStatus.IN_SYNC,
        ArchitectureReconciliationStatus.STALE,
    ],
)
def test_non_drift_reconciliation_cannot_request_approval(status) -> None:
    reconciliation = _reconciliation().model_copy(
        update={"status": status, "required_actions": ("refresh_observation",)}
    )
    with pytest.raises(ArchitectureChangeApprovalError, match="not reviewable"):
        build_architecture_change_review(_resource_version(), reconciliation)


def test_review_rejects_a_tampered_fingerprint() -> None:
    review = build_architecture_change_review(_resource_version(), _reconciliation())
    with pytest.raises(ValidationError, match="review_sha256"):
        ArchitectureChangeReview.model_validate(review.model_dump() | {"review_sha256": "0" * 64})


def test_review_recomputes_status_instead_of_trusting_a_copied_projection() -> None:
    reconciliation = _reconciliation().model_copy(
        update={
            "status": ArchitectureReconciliationStatus.LOCATION_DRIFT,
            "required_actions": ("review_location_drift",),
            "schema_matches": True,
            "location_matches": False,
        }
    )
    with pytest.raises(ArchitectureChangeApprovalError, match="provider candidates"):
        build_architecture_change_review(_resource_version(), reconciliation)
