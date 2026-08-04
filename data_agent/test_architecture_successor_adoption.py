"""Contract tests for approval-bound architecture successor adoption."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.architecture_change_assessment import (
    ASSESSED_ARCHITECTURE_CHANGE_ACTION,
    SUCCESSOR_BLOCKERS,
)
from data_agent.architecture_successor_adoption import (
    ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION,
    ArchitectureSuccessorAdoptionError,
    ArchitectureSuccessorPlan,
    build_architecture_successor_adoption_case,
    build_architecture_successor_plan,
)
from data_agent.data_architecture_ledger import (
    ArchitectureProviderObservation,
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ResourceVersionArchitecture,
    ResourceVersionArchitectureBinding,
    SchemaVersion,
    architecture_binding_fingerprint,
    architecture_provider_observation_fingerprint,
    data_contract_version_fingerprint,
    physical_location_fingerprint,
    schema_version_fingerprint,
)
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    ResourceVersion,
)
from data_agent.postgis_schema_evidence import (
    POSTGIS_SCHEMA_EVIDENCE_MEDIA_TYPE,
    POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
)

NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)
TENANT = "successor-contract"
RESOURCE_URN = f"gda://{TENANT}/dataset/parcels"
PREDECESSOR_ID = UUID("10000000-0000-4000-8000-000000000001")
SUCCESSOR_ID = UUID("10000000-0000-4000-8000-000000000002")
OBSERVATION_ID = UUID("20000000-0000-4000-8000-000000000001")
ARTIFACT_ID = UUID("30000000-0000-4000-8000-000000000001")


def _facts():
    predecessor = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_version_id=PREDECESSOR_ID,
        version_key="snapshot-1",
        content_sha256="a" * 64,
        authority_version_ref={"snapshot_ref": "snapshot:1"},
        created_by="workload:source-controller",
        created_at=NOW,
    )
    baseline_schema_values = {
        "tenant_id": TENANT,
        "resource_version_id": PREDECESSOR_ID,
        "schema_format": "postgresql",
        "authority_system": "provider",
        "authority_namespace": "postgis/gis",
        "authority_object_id": "public.parcels",
        "authority_version_ref": "schema-sha256:" + "1" * 64,
    }
    baseline_schema = SchemaVersion(
        schema_version_id=UUID("40000000-0000-4000-8000-000000000001"),
        schema_sha256=schema_version_fingerprint(**baseline_schema_values),
        created_by="workload:postgis-harvester",
        created_at=NOW,
        **baseline_schema_values,
    )
    baseline_contract_values = {
        "tenant_id": TENANT,
        "resource_version_id": PREDECESSOR_ID,
        "contract_kind": "data_product_input",
        "enforcement_mode": "required",
        "authority_system": "openmetadata",
        "authority_namespace": "table",
        "authority_object_id": "parcels-contract",
        "authority_version_ref": "version:1",
    }
    baseline_contract = DataContractVersion(
        data_contract_version_id=UUID("50000000-0000-4000-8000-000000000001"),
        contract_sha256=data_contract_version_fingerprint(**baseline_contract_values),
        created_by="workload:governance-harvester",
        created_at=NOW,
        **baseline_contract_values,
    )
    baseline_location_values = {
        "tenant_id": TENANT,
        "resource_version_id": PREDECESSOR_ID,
        "location_kind": "postgis_table",
        "provider_system": "postgis",
        "provider_namespace": "postgis/gis",
        "provider_locator": "postgresql://postgis/gis/public/parcels",
        "snapshot_ref": "snapshot:1",
        "revision_ref": "postgres-oid:10:filenode:20",
        "checksum_algorithm": "sha256",
        "content_checksum": "a" * 64,
    }
    baseline_location = PhysicalLocation(
        physical_location_id=UUID("60000000-0000-4000-8000-000000000001"),
        location_sha256=physical_location_fingerprint(**baseline_location_values),
        created_by="workload:postgis-harvester",
        created_at=NOW,
        **baseline_location_values,
    )
    baseline_binding_values = {
        "tenant_id": TENANT,
        "resource_version_id": PREDECESSOR_ID,
        "schema_version_id": baseline_schema.schema_version_id,
        "data_contract_version_id": baseline_contract.data_contract_version_id,
        "physical_location_id": baseline_location.physical_location_id,
    }
    baseline_binding = ResourceVersionArchitectureBinding(
        binding_sha256=architecture_binding_fingerprint(**baseline_binding_values),
        bound_by="workload:architecture-controller",
        bound_at=NOW,
        **baseline_binding_values,
    )
    predecessor_architecture = ResourceVersionArchitecture(
        tenant_id=TENANT,
        resource_version_id=PREDECESSOR_ID,
        architecture_ready=True,
        missing_components=(),
        schema_version_record=baseline_schema,
        data_contract_version_record=baseline_contract,
        physical_location=baseline_location,
        binding=baseline_binding,
    )

    candidate_schema_values = {
        **baseline_schema_values,
        "authority_version_ref": "schema-sha256:" + "2" * 64,
    }
    candidate_location_values = {
        **baseline_location_values,
        "snapshot_ref": "snapshot:2",
        "revision_ref": "postgres-oid:10:filenode:21",
        "content_checksum": "b" * 64,
    }
    observation_values = {
        "tenant_id": TENANT,
        "resource_version_id": PREDECESSOR_ID,
        "provider_system": "postgis",
        "provider_namespace": "postgis/gis",
        "provider_object_id": "public.parcels",
        "object_state": "present",
        "source_revision": candidate_schema_values["authority_version_ref"],
        "schema_content_sha256": "2" * 64,
        "schema_version_sha256": schema_version_fingerprint(
            **candidate_schema_values
        ),
        "physical_location_sha256": physical_location_fingerprint(
            **candidate_location_values
        ),
        "observed_at": NOW + timedelta(minutes=1),
        "fresh_until": NOW + timedelta(hours=1),
    }
    observation = ArchitectureProviderObservation(
        observation_id=OBSERVATION_ID,
        observation_sha256=architecture_provider_observation_fingerprint(
            **observation_values
        ),
        observed_by="workload:postgis-harvester",
        recorded_at=NOW + timedelta(minutes=1),
        **observation_values,
    )
    artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=ARTIFACT_ID,
        artifact_key=f"postgis-schema-{OBSERVATION_ID.hex}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri="s3://architecture-evidence/candidate.json",
        media_type=POSTGIS_SCHEMA_EVIDENCE_MEDIA_TYPE,
        content_sha256="c" * 64,
        size_bytes=1024,
        resource_version_id=PREDECESSOR_ID,
        manifest={
            "schema": POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
            "observation_id": str(OBSERVATION_ID),
            "observation_sha256": observation.observation_sha256,
            "snapshot_sha256": observation.schema_content_sha256,
        },
        created_by="workload:postgis-harvester",
        created_at=NOW + timedelta(minutes=1),
    )
    assessed_case = ApprovalCase(
        tenant_id=TENANT,
        approval_case_ref=(
            f"gda://{TENANT}/approval_case/architecture-assessment-{OBSERVATION_ID.hex}"
        ),
        target_resource_urn=RESOURCE_URN,
        target_fingerprint="d" * 64,
        action=ASSESSED_ARCHITECTURE_CHANGE_ACTION,
        requester_subject="agent:architecture-reviewer",
        request_reason="review compatibility and downstream impact",
        request_context={
            "resource_version_id": str(PREDECESSOR_ID),
            "observation_id": str(OBSERVATION_ID),
            "observation_sha256": observation.observation_sha256,
            "binding_sha256": baseline_binding.binding_sha256,
            "candidate_schema_artifact_id": str(ARTIFACT_ID),
            "successor_blockers": list(SUCCESSOR_BLOCKERS),
        },
        status=ApprovalCaseStatus.APPROVED,
        state_version=1,
        requested_at=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(hours=1),
        decided_by="human:data-steward",
        decision_reason="assessment evidence accepted",
        decided_at=NOW + timedelta(minutes=3),
    )

    successor_schema_values = {
        **candidate_schema_values,
        "resource_version_id": SUCCESSOR_ID,
    }
    successor_schema = SchemaVersion(
        schema_version_id=UUID("40000000-0000-4000-8000-000000000002"),
        schema_sha256=schema_version_fingerprint(**successor_schema_values),
        created_by="workload:postgis-harvester",
        created_at=NOW + timedelta(minutes=4),
        **successor_schema_values,
    )
    successor_contract_values = {
        **baseline_contract_values,
        "resource_version_id": SUCCESSOR_ID,
        "authority_version_ref": "version:2",
    }
    successor_contract = DataContractVersion(
        data_contract_version_id=UUID("50000000-0000-4000-8000-000000000002"),
        contract_sha256=data_contract_version_fingerprint(**successor_contract_values),
        created_by="workload:governance-harvester",
        created_at=NOW + timedelta(minutes=4),
        **successor_contract_values,
    )
    successor_location_values = {
        **candidate_location_values,
        "resource_version_id": SUCCESSOR_ID,
    }
    successor_location = PhysicalLocation(
        physical_location_id=UUID("60000000-0000-4000-8000-000000000002"),
        location_sha256=physical_location_fingerprint(**successor_location_values),
        created_by="workload:postgis-harvester",
        created_at=NOW + timedelta(minutes=4),
        **successor_location_values,
    )
    successor_binding_values = {
        "tenant_id": TENANT,
        "resource_version_id": SUCCESSOR_ID,
        "schema_version_id": successor_schema.schema_version_id,
        "data_contract_version_id": successor_contract.data_contract_version_id,
        "physical_location_id": successor_location.physical_location_id,
    }
    successor_binding = ResourceVersionArchitectureBinding(
        binding_sha256=architecture_binding_fingerprint(**successor_binding_values),
        bound_by="workload:architecture-successor-controller",
        bound_at=NOW + timedelta(minutes=4),
        **successor_binding_values,
    )
    successor_architecture = DataArchitectureRegistration(
        schema_version=successor_schema,
        data_contract_version=successor_contract,
        physical_location=successor_location,
        binding=successor_binding,
    )
    successor = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_version_id=SUCCESSOR_ID,
        version_key="snapshot-2",
        predecessor_version_id=PREDECESSOR_ID,
        content_sha256="b" * 64,
        authority_version_ref={
            "snapshot_ref": "snapshot:2",
            "revision_ref": "postgres-oid:10:filenode:21",
            "content_sha256": "b" * 64,
            "provider_observation_id": str(OBSERVATION_ID),
            "schema_evidence_artifact_id": str(ARTIFACT_ID),
        },
        created_by="workload:architecture-successor-controller",
        created_at=NOW + timedelta(minutes=4),
    )
    return {
        "predecessor": predecessor,
        "predecessor_architecture": predecessor_architecture,
        "observation": observation,
        "candidate_schema_artifact": artifact,
        "assessed_case": assessed_case,
        "successor_resource_version": successor,
        "successor_architecture": successor_architecture,
    }


def test_successor_plan_clears_blockers_and_builds_second_approval() -> None:
    plan = build_architecture_successor_plan(**_facts())
    case = build_architecture_successor_adoption_case(
        plan,
        requester_subject="workload:architecture-controller",
        request_reason="adopt reviewed provider snapshot and contract",
        requested_at=NOW + timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
    )

    assert case.action == ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION
    assert case.target_fingerprint == plan.plan_sha256
    assert case.approval_case_ref.endswith(SUCCESSOR_ID.hex)
    assert case.request_context["cleared_blockers"] == list(SUCCESSOR_BLOCKERS)
    assert case.request_context["successor_content_sha256"] == "b" * 64
    assert plan.lineage_event.source_resource_version_id == PREDECESSOR_ID
    assert plan.lineage_event.target_resource_version_id == SUCCESSOR_ID


def test_successor_plan_rejects_reused_content_or_contract() -> None:
    facts = _facts()
    reused_content = facts["successor_resource_version"].model_copy(
        update={"content_sha256": "a" * 64}
    )
    with pytest.raises(ValidationError, match="content hash"):
        build_architecture_successor_plan(
            **facts | {"successor_resource_version": reused_content}
        )

    facts = _facts()
    baseline_contract = facts[
        "predecessor_architecture"
    ].data_contract_version_record
    assert baseline_contract is not None
    successor_contract = facts["successor_architecture"].data_contract_version
    contract_values = successor_contract.model_dump(
        exclude={"contract_sha256", "authority_version_ref"}
    ) | {"authority_version_ref": baseline_contract.authority_version_ref}
    reused_contract = DataContractVersion(
        contract_sha256=data_contract_version_fingerprint(
            tenant_id=contract_values["tenant_id"],
            resource_version_id=contract_values["resource_version_id"],
            contract_kind=contract_values["contract_kind"],
            enforcement_mode=contract_values["enforcement_mode"],
            authority_system=contract_values["authority_system"],
            authority_namespace=contract_values["authority_namespace"],
            authority_object_id=contract_values["authority_object_id"],
            authority_version_ref=contract_values["authority_version_ref"],
        ),
        **contract_values,
    )
    registration = facts["successor_architecture"].model_copy(
        update={"data_contract_version": reused_contract}
    )
    with pytest.raises(
        ArchitectureSuccessorAdoptionError,
        match="distinct data-contract",
    ):
        build_architecture_successor_plan(
            **facts | {"successor_architecture": registration}
        )


def test_successor_plan_rejects_unapproved_assessment_and_tampering() -> None:
    facts = _facts()
    pending = facts["assessed_case"].model_copy(
        update={
            "status": ApprovalCaseStatus.PENDING,
            "state_version": 0,
            "decided_by": None,
            "decision_reason": None,
            "decided_at": None,
        }
    )
    with pytest.raises(
        ArchitectureSuccessorAdoptionError,
        match="independently approved",
    ):
        build_architecture_successor_plan(**facts | {"assessed_case": pending})

    plan = build_architecture_successor_plan(**_facts())
    with pytest.raises(ValidationError, match="plan_sha256"):
        ArchitectureSuccessorPlan.model_validate(
            plan.model_dump() | {"plan_sha256": "0" * 64}
        )


def test_adoption_lock_migration_covers_direct_observation_inserts() -> None:
    sql = (
        __import__("pathlib").Path(__file__).resolve().parent
        / "migrations"
        / "115_architecture_successor_adoption_lock.sql"
    ).read_text(encoding="utf-8")

    assert "pg_advisory_xact_lock" in sql
    assert "BEFORE INSERT ON gda_control.architecture_provider_observation" in sql
    assert "BEFORE INSERT ON gda_control.resource_version" in sql
    assert "already has a successor" in sql
    assert "lock_architecture_resource_version" in sql
