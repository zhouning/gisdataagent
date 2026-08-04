"""Real PostGIS acceptance for atomic architecture successor adoption."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.architecture_change_assessment import ArchitectureChangeAssessmentService
from data_agent.architecture_successor_adoption import (
    ArchitectureSuccessorAdoptionService,
)
from data_agent.data_architecture_ledger import (
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ResourceVersionArchitectureBinding,
    SchemaVersion,
    architecture_binding_fingerprint,
    data_contract_version_fingerprint,
    physical_location_fingerprint,
    schema_version_fingerprint,
)
from data_agent.platform_contracts import (
    ApprovalCaseStatus,
    Resource,
    ResourceVersion,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayValidationError,
    PlatformGateway,
)
from data_agent.postgis_architecture_harvester import (
    PostgisArchitectureTarget,
    harvest_postgis_architecture,
)
from data_agent.postgis_schema_evidence import (
    build_postgis_schema_evidence_artifact,
    postgis_schema_snapshot_bytes,
)

POSTGIS_SUCCESSOR_DATABASE_URL = os.environ.get("POSTGIS_SUCCESSOR_DATABASE_URL")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "096_platform_success_verdict.sql",
        "100_data_product_registry.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "113_data_architecture_version_authority.sql",
        "114_data_architecture_provider_observation.sql",
        "115_architecture_successor_adoption_lock.sql",
        "116_architecture_successor_data_product_release.sql",
    )
)


def _record_schema_evidence(gateway, harvest, path: Path):
    assert harvest.schema_snapshot is not None
    content = postgis_schema_snapshot_bytes(harvest.schema_snapshot)
    path.write_bytes(content)
    artifact = build_postgis_schema_evidence_artifact(
        harvest.schema_snapshot,
        harvest.observation,
        artifact_id=uuid4(),
        storage_uri=path.resolve().as_uri(),
        created_by="workload:postgis-harvester",
    )
    assert artifact.content_sha256 == hashlib.sha256(content).hexdigest()
    assert gateway.record_artifact(artifact).created
    return artifact


def _successor_registration(
    *,
    tenant: str,
    resource_urn: str,
    predecessor_id,
    successor_id,
    observation,
    candidate,
    candidate_artifact,
    baseline_contract,
    created_at: datetime,
):
    assert candidate.schema_candidate is not None
    assert candidate.physical_location_candidate is not None
    candidate_schema = candidate.schema_candidate
    schema_values = {
        "tenant_id": tenant,
        "resource_version_id": successor_id,
        "schema_format": candidate_schema.schema_format,
        "authority_system": candidate_schema.authority_system,
        "authority_namespace": candidate_schema.authority_namespace,
        "authority_object_id": candidate_schema.authority_object_id,
        "authority_version_ref": candidate_schema.authority_version_ref,
    }
    schema = SchemaVersion(
        schema_version_id=uuid4(),
        schema_sha256=schema_version_fingerprint(**schema_values),
        created_by="workload:postgis-harvester",
        created_at=created_at,
        **schema_values,
    )
    contract_values = {
        "tenant_id": tenant,
        "resource_version_id": successor_id,
        "contract_kind": baseline_contract.contract_kind,
        "enforcement_mode": baseline_contract.enforcement_mode,
        "authority_system": baseline_contract.authority_system,
        "authority_namespace": baseline_contract.authority_namespace,
        "authority_object_id": baseline_contract.authority_object_id,
        "authority_version_ref": "version:2",
    }
    contract = DataContractVersion(
        data_contract_version_id=uuid4(),
        contract_sha256=data_contract_version_fingerprint(**contract_values),
        created_by="workload:governance-harvester",
        created_at=created_at,
        **contract_values,
    )
    candidate_location = candidate.physical_location_candidate
    location_values = {
        "tenant_id": tenant,
        "resource_version_id": successor_id,
        "location_kind": candidate_location.location_kind,
        "provider_system": candidate_location.provider_system,
        "provider_namespace": candidate_location.provider_namespace,
        "provider_locator": candidate_location.provider_locator,
        "snapshot_ref": candidate_location.snapshot_ref,
        "revision_ref": candidate_location.revision_ref,
        "checksum_algorithm": candidate_location.checksum_algorithm,
        "content_checksum": candidate_location.content_checksum,
    }
    location = PhysicalLocation(
        physical_location_id=uuid4(),
        location_sha256=physical_location_fingerprint(**location_values),
        created_by="workload:postgis-harvester",
        created_at=created_at,
        **location_values,
    )
    binding_values = {
        "tenant_id": tenant,
        "resource_version_id": successor_id,
        "schema_version_id": schema.schema_version_id,
        "data_contract_version_id": contract.data_contract_version_id,
        "physical_location_id": location.physical_location_id,
    }
    registration = DataArchitectureRegistration(
        schema_version=schema,
        data_contract_version=contract,
        physical_location=location,
        binding=ResourceVersionArchitectureBinding(
            binding_sha256=architecture_binding_fingerprint(**binding_values),
            bound_by="workload:architecture-successor-controller",
            bound_at=created_at,
            **binding_values,
        ),
    )
    successor = ResourceVersion(
        tenant_id=tenant,
        resource_urn=resource_urn,
        resource_version_id=successor_id,
        version_key="snapshot-2",
        predecessor_version_id=predecessor_id,
        content_sha256=candidate_location.content_checksum,
        authority_version_ref={
            "snapshot_ref": candidate_location.snapshot_ref,
            "revision_ref": candidate_location.revision_ref,
            "content_sha256": candidate_location.content_checksum,
            "provider_observation_id": str(observation.observation_id),
            "schema_evidence_artifact_id": str(candidate_artifact.artifact_id),
        },
        created_by="workload:architecture-successor-controller",
        created_at=created_at,
    )
    return successor, registration


@pytest.mark.skipif(
    not POSTGIS_SUCCESSOR_DATABASE_URL,
    reason="POSTGIS_SUCCESSOR_DATABASE_URL is not configured",
)
def test_real_postgis_atomic_successor_adoption(tmp_path: Path):
    engine = create_engine(POSTGIS_SUCCESSOR_DATABASE_URL)
    tenant = f"postgis-successor-{uuid4().hex[:8]}"
    predecessor_id = uuid4()
    successor_id = uuid4()
    resource_urn = f"gda://{tenant}/dataset/parcels"
    actor = "workload:postgis-harvester"
    baseline_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
    try:
        with engine.begin() as connection:
            if not connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one():
                pytest.skip("PostGIS successor test requires a superuser")
            connection.exec_driver_sql(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') "
                "THEN CREATE ROLE agent_user NOLOGIN; END IF; "
                "END $$"
            )
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS postgis")
            connection.exec_driver_sql("CREATE SCHEMA provider_geo")
            connection.exec_driver_sql(
                "CREATE TABLE provider_geo.parcels ("
                "parcel_id bigint PRIMARY KEY, "
                "land_use text NOT NULL, "
                "geom geometry(Polygon, 4326) NOT NULL)"
            )

        gateway = PlatformGateway(engine)
        approvals = ApprovalCaseAuthority(engine)
        assessment_service = ArchitectureChangeAssessmentService(gateway, approvals)
        adoption_service = ArchitectureSuccessorAdoptionService(gateway, approvals)
        gateway.register_resource(
            Resource(
                tenant_id=tenant,
                resource_urn=resource_urn,
                resource_kind="dataset",
                authority_system="postgis",
                authority_locator="provider_geo.parcels",
                owner_ref="team:spatial-data",
            )
        )
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=tenant,
                resource_urn=resource_urn,
                resource_version_id=predecessor_id,
                version_key="snapshot-1",
                content_sha256="a" * 64,
                authority_version_ref={"snapshot_ref": "provider-snapshot:1"},
                created_by=actor,
                created_at=baseline_at,
            )
        )
        baseline_target = PostgisArchitectureTarget(
            tenant_id=tenant,
            resource_version_id=predecessor_id,
            provider_ref="successor-postgis",
            schema_name="provider_geo",
            table_name="parcels",
            snapshot_ref="provider-snapshot:1",
            content_checksum="a" * 64,
        )
        baseline = harvest_postgis_architecture(
            engine,
            baseline_target,
            observed_by=actor,
            observed_at=baseline_at,
            freshness_seconds=3600,
        )
        assert baseline.schema_candidate is not None
        assert baseline.physical_location_candidate is not None
        gateway.record_architecture_provider_observation(baseline.observation)
        baseline_artifact = _record_schema_evidence(
            gateway,
            baseline,
            tmp_path / "baseline.json",
        )
        contract_values = {
            "tenant_id": tenant,
            "resource_version_id": predecessor_id,
            "contract_kind": "data_product_input",
            "enforcement_mode": "required",
            "authority_system": "openmetadata",
            "authority_namespace": "table",
            "authority_object_id": str(uuid4()),
            "authority_version_ref": "version:1",
        }
        baseline_contract = DataContractVersion(
            data_contract_version_id=uuid4(),
            contract_sha256=data_contract_version_fingerprint(**contract_values),
            created_by="workload:governance-harvester",
            created_at=baseline_at,
            **contract_values,
        )
        baseline_binding_values = {
            "tenant_id": tenant,
            "resource_version_id": predecessor_id,
            "schema_version_id": baseline.schema_candidate.schema_version_id,
            "data_contract_version_id": baseline_contract.data_contract_version_id,
            "physical_location_id": (
                baseline.physical_location_candidate.physical_location_id
            ),
        }
        gateway.register_resource_version_architecture(
            DataArchitectureRegistration(
                schema_version=baseline.schema_candidate,
                data_contract_version=baseline_contract,
                physical_location=baseline.physical_location_candidate,
                binding=ResourceVersionArchitectureBinding(
                    binding_sha256=architecture_binding_fingerprint(
                        **baseline_binding_values
                    ),
                    bound_by="workload:architecture-controller",
                    bound_at=baseline_at,
                    **baseline_binding_values,
                ),
            )
        )

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE provider_geo.parcels ADD COLUMN zoning_code text"
            )
        candidate_at = baseline_at + timedelta(minutes=1)
        candidate_target = baseline_target.model_copy(
            update={
                "snapshot_ref": "provider-snapshot:2",
                "content_checksum": "b" * 64,
            }
        )
        candidate = harvest_postgis_architecture(
            engine,
            candidate_target,
            observed_by=actor,
            observed_at=candidate_at,
            freshness_seconds=3600,
        )
        assert candidate.schema_snapshot is not None
        gateway.record_architecture_provider_observation(candidate.observation)
        candidate_artifact = _record_schema_evidence(
            gateway,
            candidate,
            tmp_path / "candidate.json",
        )
        assessment = assessment_service.request_review(
            tenant_id=tenant,
            resource_version_id=predecessor_id,
            baseline_snapshot=baseline.schema_snapshot,
            candidate_snapshot=candidate.schema_snapshot,
            baseline_schema_artifact_id=baseline_artifact.artifact_id,
            candidate_schema_artifact_id=candidate_artifact.artifact_id,
            requester_subject="agent:architecture-reviewer",
            request_reason="review successor schema and downstream impact",
            owner_ref="team:spatial-data",
            requested_at=candidate_at + timedelta(seconds=1),
            expires_at=candidate_at + timedelta(hours=1),
            evaluated_at=candidate_at + timedelta(seconds=1),
        )
        approvals.decide(
            tenant_id=tenant,
            approval_case_ref=assessment.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:data-steward",
            reason="compatibility and lineage impact accepted",
        )
        successor_created_at = candidate_at + timedelta(minutes=1)
        successor, registration = _successor_registration(
            tenant=tenant,
            resource_urn=resource_urn,
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            observation=candidate.observation,
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            baseline_contract=baseline_contract,
            created_at=successor_created_at,
        )
        adoption_request = adoption_service.request_adoption(
            tenant_id=tenant,
            assessed_approval_case_ref=assessment.approval_case.approval_case_ref,
            successor_resource_version=successor,
            successor_architecture=registration,
            requester_subject="workload:architecture-controller",
            request_reason="adopt immutable successor snapshot and contract",
            owner_ref="team:spatial-data",
            requested_at=successor_created_at,
            expires_at=successor_created_at + timedelta(hours=1),
        )
        with pytest.raises(GatewayValidationError, match="not an approved plan"):
            adoption_service.adopt(
                adoption_request.plan,
                adoption_approval_case_ref=(
                    adoption_request.approval_case.approval_case_ref
                ),
                evaluated_at=successor_created_at + timedelta(seconds=1),
            )
        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM gda_control.resource_version "
                    "WHERE tenant_id = :tenant_id AND resource_urn = :resource_urn"
                ),
                {"tenant_id": tenant, "resource_urn": resource_urn},
            ).scalar_one() == 1

        approvals.decide(
            tenant_id=tenant,
            approval_case_ref=adoption_request.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:architecture-owner",
            reason="successor snapshot and contract adoption approved",
        )
        written = adoption_service.adopt(
            adoption_request.plan,
            adoption_approval_case_ref=adoption_request.approval_case.approval_case_ref,
            evaluated_at=successor_created_at + timedelta(seconds=1),
        )
        assert written.created
        assert gateway.get_resource_version(tenant, successor_id) == successor
        adopted_architecture = gateway.get_resource_version_architecture(
            tenant,
            successor_id,
        )
        assert adopted_architecture.architecture_ready
        assert adopted_architecture.binding == registration.binding
        assert not adoption_service.adopt(
            adoption_request.plan,
            adoption_approval_case_ref=adoption_request.approval_case.approval_case_ref,
            evaluated_at=successor_created_at + timedelta(seconds=2),
        ).created

        later_observation = harvest_postgis_architecture(
            engine,
            candidate_target,
            observed_by=actor,
            observed_at=successor_created_at + timedelta(minutes=1),
            freshness_seconds=3600,
        )
        gateway.record_architecture_provider_observation(later_observation.observation)
        assert not adoption_service.adopt(
            adoption_request.plan,
            adoption_approval_case_ref=adoption_request.approval_case.approval_case_ref,
            evaluated_at=successor_created_at + timedelta(minutes=1, seconds=1),
        ).created
        with pytest.raises(GatewayConflictError, match="platform state conflict"):
            gateway.register_resource_version(
                ResourceVersion(
                    tenant_id=tenant,
                    resource_urn=resource_urn,
                    resource_version_id=uuid4(),
                    version_key="unauthorized-branch",
                    predecessor_version_id=predecessor_id,
                    content_sha256="c" * 64,
                    authority_version_ref={"snapshot_ref": "unreviewed-snapshot"},
                    created_by="workload:unreviewed-writer",
                    created_at=successor_created_at + timedelta(minutes=2),
                )
            )

        with engine.begin() as connection:
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM gda_control.resource_version "
                    " WHERE tenant_id = :tenant_id) AS versions, "
                    "(SELECT count(*) FROM gda_control.schema_version "
                    " WHERE tenant_id = :tenant_id) AS schemas, "
                    "(SELECT count(*) FROM gda_control.data_contract_version "
                    " WHERE tenant_id = :tenant_id) AS contracts, "
                    "(SELECT count(*) FROM gda_control.physical_location "
                    " WHERE tenant_id = :tenant_id) AS locations, "
                    "(SELECT count(*) FROM "
                    " gda_control.resource_version_architecture_binding "
                    " WHERE tenant_id = :tenant_id) AS bindings, "
                    "(SELECT count(*) FROM gda_control.lineage_event "
                    " WHERE tenant_id = :tenant_id) AS lineage_events"
                ),
                {"tenant_id": tenant},
            ).mappings().one()
            assert dict(counts) == {
                "versions": 2,
                "schemas": 2,
                "contracts": 2,
                "locations": 2,
                "bindings": 2,
                "lineage_events": 1,
            }
    finally:
        engine.dispose()
