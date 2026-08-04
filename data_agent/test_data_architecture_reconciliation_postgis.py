import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseConflictError,
    ApprovalCaseNotFoundError,
    ApprovalCaseValidationError,
)
from data_agent.architecture_change_approval import (
    ArchitectureChangeApprovalError,
    ArchitectureChangeApprovalService,
)
from data_agent.data_architecture_ledger import (
    ArchitectureReconciliationStatus,
    DataArchitectureRegistration,
    DataContractVersion,
    ResourceVersionArchitectureBinding,
    architecture_binding_fingerprint,
    data_contract_version_fingerprint,
)
from data_agent.platform_contracts import ApprovalCaseStatus, Resource, ResourceVersion
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    PlatformGateway,
)
from data_agent.postgis_architecture_harvester import (
    PostgisArchitectureTarget,
    harvest_postgis_architecture,
)

POSTGIS_DATABASE_URL = os.environ.get("POSTGIS_DATABASE_URL")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "113_data_architecture_version_authority.sql",
        "114_data_architecture_provider_observation.sql",
        "115_architecture_successor_adoption_lock.sql",
    )
)


def _assert_db_rejected(connection, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.exec_driver_sql(statement)


@pytest.mark.skipif(
    not POSTGIS_DATABASE_URL,
    reason="POSTGIS_DATABASE_URL is not configured",
)
def test_real_postgis_harvest_binding_drift_staleness_and_tombstone():
    engine = create_engine(POSTGIS_DATABASE_URL)
    tenant = f"postgis-arch-{uuid4().hex[:8]}"
    resource_version_id = uuid4()
    resource_urn = f"gda://{tenant}/dataset/parcels"
    actor = "workload:postgis-harvester"
    observed_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
    try:
        with engine.begin() as connection:
            if not connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one():
                pytest.skip("PostGIS architecture test requires a superuser")
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
            connection.exec_driver_sql(
                "CREATE INDEX parcels_geom_gix ON provider_geo.parcels USING gist (geom)"
            )
            connection.exec_driver_sql(
                "INSERT INTO provider_geo.parcels VALUES ("
                "1, 'residential', "
                "ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))', 4326))"
            )

        gateway = PlatformGateway(engine)
        approval_authority = ApprovalCaseAuthority(engine)
        approval_service = ArchitectureChangeApprovalService(
            gateway,
            approval_authority,
        )
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
                resource_version_id=resource_version_id,
                version_key="snapshot-1",
                content_sha256="a" * 64,
                authority_version_ref={"snapshot": "provider-snapshot:1"},
                created_by=actor,
                created_at=observed_at,
            )
        )
        target = PostgisArchitectureTarget(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            provider_ref="acceptance-postgis",
            schema_name="provider_geo",
            table_name="parcels",
            snapshot_ref="provider-snapshot:1",
            content_checksum="a" * 64,
        )

        unobserved = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=observed_at,
        )
        assert unobserved.status == ArchitectureReconciliationStatus.UNOBSERVED
        assert unobserved.required_actions == ("harvest_provider",)
        with pytest.raises(ArchitectureChangeApprovalError, match="not reviewable"):
            approval_service.request_review(
                tenant_id=tenant,
                resource_version_id=resource_version_id,
                requester_subject="agent:architecture-reviewer",
                request_reason="unobserved state must not enter drift approval",
                owner_ref="team:spatial-data",
                requested_at=observed_at,
                expires_at=observed_at + timedelta(hours=1),
                evaluated_at=observed_at,
            )

        first = harvest_postgis_architecture(
            engine,
            target,
            observed_by=actor,
            observed_at=observed_at,
            freshness_seconds=300,
        )
        assert first.schema_candidate is not None
        assert first.physical_location_candidate is not None
        assert "geometry(Polygon,4326)" not in first.observation.model_dump_json()
        assert gateway.record_architecture_provider_observation(first.observation).created
        assert not gateway.record_architecture_provider_observation(first.observation).created
        unbound = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=observed_at + timedelta(seconds=1),
        )
        assert unbound.status == ArchitectureReconciliationStatus.UNBOUND
        assert unbound.required_actions == ("register_architecture",)
        with pytest.raises(ArchitectureChangeApprovalError, match="not reviewable"):
            approval_service.request_review(
                tenant_id=tenant,
                resource_version_id=resource_version_id,
                requester_subject="agent:architecture-reviewer",
                request_reason="unbound state must not enter drift approval",
                owner_ref="team:spatial-data",
                requested_at=observed_at + timedelta(seconds=1),
                expires_at=observed_at + timedelta(hours=1),
                evaluated_at=observed_at + timedelta(seconds=1),
            )

        contract_values = {
            "tenant_id": tenant,
            "resource_version_id": resource_version_id,
            "contract_kind": "data_product_input",
            "enforcement_mode": "required",
            "authority_system": "openmetadata",
            "authority_namespace": "table",
            "authority_object_id": str(uuid4()),
            "authority_version_ref": "version:1",
        }
        contract = DataContractVersion(
            data_contract_version_id=uuid4(),
            contract_sha256=data_contract_version_fingerprint(**contract_values),
            created_by="workload:governance-harvester",
            created_at=observed_at,
            **contract_values,
        )
        binding_values = {
            "tenant_id": tenant,
            "resource_version_id": resource_version_id,
            "schema_version_id": first.schema_candidate.schema_version_id,
            "data_contract_version_id": contract.data_contract_version_id,
            "physical_location_id": (first.physical_location_candidate.physical_location_id),
        }
        binding = ResourceVersionArchitectureBinding(
            binding_sha256=architecture_binding_fingerprint(**binding_values),
            bound_by="workload:architecture-controller",
            bound_at=observed_at,
            **binding_values,
        )
        gateway.register_resource_version_architecture(
            DataArchitectureRegistration(
                schema_version=first.schema_candidate,
                data_contract_version=contract,
                physical_location=first.physical_location_candidate,
                binding=binding,
            )
        )
        in_sync = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=observed_at + timedelta(seconds=2),
        )
        assert in_sync.status == ArchitectureReconciliationStatus.IN_SYNC
        assert in_sync.schema_matches is True
        assert in_sync.location_matches is True
        assert in_sync.required_actions == ()
        with pytest.raises(ArchitectureChangeApprovalError, match="not reviewable"):
            approval_service.request_review(
                tenant_id=tenant,
                resource_version_id=resource_version_id,
                requester_subject="agent:architecture-reviewer",
                request_reason="synchronized state must not enter drift approval",
                owner_ref="team:spatial-data",
                requested_at=observed_at + timedelta(seconds=2),
                expires_at=observed_at + timedelta(hours=1),
                evaluated_at=observed_at + timedelta(seconds=2),
            )

        stale = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=observed_at + timedelta(seconds=301),
        )
        assert stale.status == ArchitectureReconciliationStatus.STALE
        assert stale.required_actions == ("refresh_observation",)
        with pytest.raises(ArchitectureChangeApprovalError, match="not reviewable"):
            approval_service.request_review(
                tenant_id=tenant,
                resource_version_id=resource_version_id,
                requester_subject="agent:architecture-reviewer",
                request_reason="stale evidence must be refreshed before review",
                owner_ref="team:spatial-data",
                requested_at=observed_at + timedelta(seconds=301),
                expires_at=observed_at + timedelta(hours=1),
                evaluated_at=observed_at + timedelta(seconds=301),
            )

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE provider_geo.parcels ADD COLUMN zoning_code text NOT NULL DEFAULT 'R'"
            )
        drifted_at = observed_at + timedelta(minutes=6)
        drifted = harvest_postgis_architecture(
            engine,
            target,
            observed_by=actor,
            observed_at=drifted_at,
            freshness_seconds=300,
        )
        assert drifted.schema_candidate is not None
        assert drifted.schema_candidate.schema_sha256 != (first.schema_candidate.schema_sha256)
        assert drifted.physical_location_candidate == (
            first.physical_location_candidate.model_copy(
                update={
                    "created_at": drifted_at,
                    "physical_location_id": (
                        drifted.physical_location_candidate.physical_location_id
                    ),
                }
            )
        )
        gateway.record_architecture_provider_observation(drifted.observation)
        drift = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=drifted_at + timedelta(seconds=1),
        )
        assert drift.status == ArchitectureReconciliationStatus.SCHEMA_DRIFT
        assert drift.schema_matches is False
        assert drift.location_matches is True
        assert drift.required_actions == ("review_schema_drift",)
        assert (
            drift.architecture.schema_version_record.schema_version_id
            == first.schema_candidate.schema_version_id
        )
        schema_review_at = drifted_at + timedelta(seconds=1)
        schema_case = approval_service.request_review(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            requester_subject="agent:architecture-reviewer",
            request_reason="PostGIS schema drift requires steward review",
            owner_ref="team:spatial-data",
            requested_at=schema_review_at,
            expires_at=schema_review_at + timedelta(hours=1),
            evaluated_at=schema_review_at,
        )
        assert schema_case.created
        assert schema_case.approval_case.target_resource_urn == resource_urn
        assert schema_case.approval_case.request_context["reconciliation_status"] == "schema_drift"
        assert not approval_service.request_review(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            requester_subject="agent:architecture-reviewer",
            request_reason="PostGIS schema drift requires steward review",
            owner_ref="team:spatial-data",
            requested_at=schema_review_at,
            expires_at=schema_review_at + timedelta(hours=1),
            evaluated_at=schema_review_at,
        ).created
        with pytest.raises(ApprovalCaseConflictError, match="different evidence"):
            approval_authority.create(
                schema_case.approval_case.model_copy(
                    update={"request_reason": "conflicting review request"}
                ),
                owner_ref="team:spatial-data",
            )
        for forbidden_approver in (
            "workload:architecture-controller",
            "agent:architecture-reviewer",
        ):
            with pytest.raises(
                ApprovalCaseValidationError,
                match="contract was rejected",
            ):
                approval_authority.decide(
                    tenant_id=tenant,
                    approval_case_ref=schema_case.approval_case.approval_case_ref,
                    expected_state_version=0,
                    verdict=ApprovalCaseStatus.APPROVED,
                    actor_subject=forbidden_approver,
                    reason="automated verdict is forbidden",
                )
        approved_schema_case = approval_authority.decide(
            tenant_id=tenant,
            approval_case_ref=schema_case.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:data-steward",
            reason="review accepted; create a new ResourceVersion separately",
        )
        assert approved_schema_case.status is ApprovalCaseStatus.APPROVED
        assert (
            len(
                approval_authority.events(
                    tenant,
                    schema_case.approval_case.approval_case_ref,
                )
            )
            == 2
        )
        with pytest.raises(ApprovalCaseNotFoundError):
            approval_authority.get(
                "another-tenant",
                schema_case.approval_case.approval_case_ref,
            )
        assert (
            gateway.get_resource_version_architecture(
                tenant,
                resource_version_id,
            ).binding
            == binding
        )

        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE provider_geo.parcels")
            connection.exec_driver_sql(
                "CREATE TABLE provider_geo.parcels ("
                "parcel_id bigint PRIMARY KEY, "
                "land_use text NOT NULL, "
                "geom geometry(Polygon, 4326) NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX parcels_geom_gix ON provider_geo.parcels USING gist (geom)"
            )
            connection.exec_driver_sql(
                "INSERT INTO provider_geo.parcels VALUES ("
                "1, 'residential', "
                "ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))', 4326))"
            )
        relocated_at = drifted_at + timedelta(minutes=1)
        relocated = harvest_postgis_architecture(
            engine,
            target,
            observed_by=actor,
            observed_at=relocated_at,
            freshness_seconds=300,
        )
        assert relocated.schema_candidate is not None
        assert relocated.physical_location_candidate is not None
        assert relocated.schema_candidate.schema_sha256 == first.schema_candidate.schema_sha256
        assert relocated.physical_location_candidate.location_sha256 != (
            first.physical_location_candidate.location_sha256
        )
        gateway.record_architecture_provider_observation(relocated.observation)
        location_drift = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=relocated_at + timedelta(seconds=1),
        )
        assert location_drift.status == ArchitectureReconciliationStatus.LOCATION_DRIFT
        assert location_drift.schema_matches is True
        assert location_drift.location_matches is False
        assert location_drift.required_actions == ("review_location_drift",)
        location_review_at = relocated_at + timedelta(seconds=1)
        location_case = approval_service.request_review(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            requester_subject="workload:architecture-controller",
            request_reason="PostGIS physical replacement requires steward review",
            owner_ref="team:spatial-data",
            requested_at=location_review_at,
            expires_at=location_review_at + timedelta(hours=1),
            evaluated_at=location_review_at,
        )
        assert location_case.created
        assert location_case.approval_case.approval_case_ref != (
            schema_case.approval_case.approval_case_ref
        )
        assert (
            location_case.approval_case.request_context["reconciliation_status"] == "location_drift"
        )

        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE provider_geo.parcels")
        tombstoned_at = relocated_at + timedelta(minutes=1)
        tombstone = harvest_postgis_architecture(
            engine,
            target,
            observed_by=actor,
            observed_at=tombstoned_at,
            freshness_seconds=300,
        )
        assert tombstone.schema_candidate is None
        assert tombstone.physical_location_candidate is None
        gateway.record_architecture_provider_observation(tombstone.observation)
        deleted = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=tombstoned_at + timedelta(seconds=1),
        )
        assert deleted.status == ArchitectureReconciliationStatus.TOMBSTONED
        assert deleted.required_actions == ("investigate_tombstone",)
        tombstone_review_at = tombstoned_at + timedelta(seconds=1)
        tombstone_case = approval_service.request_review(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            requester_subject="agent:architecture-reviewer",
            request_reason="PostGIS tombstone requires steward investigation",
            owner_ref="team:spatial-data",
            requested_at=tombstone_review_at,
            expires_at=tombstone_review_at + timedelta(hours=1),
            evaluated_at=tombstone_review_at,
        )
        assert tombstone_case.created
        assert tombstone_case.approval_case.approval_case_ref not in {
            schema_case.approval_case.approval_case_ref,
            location_case.approval_case.approval_case_ref,
        }
        assert tombstone_case.approval_case.request_context["candidate_schema_sha256"] is None
        assert tombstone_case.approval_case.request_context["candidate_location_sha256"] is None
        assert (
            gateway.get_resource_version_architecture(tenant, resource_version_id).binding
            == binding
        )

        with pytest.raises(GatewayConflictError, match="different immutable payload"):
            gateway.record_architecture_provider_observation(
                first.observation.model_copy(update={"observed_by": "attacker"})
            )
        with pytest.raises(GatewayNotFoundError):
            gateway.get_latest_architecture_provider_observation(
                "another-tenant", resource_version_id
            )

        with engine.connect() as connection:
            with connection.begin():
                _assert_db_rejected(
                    connection,
                    "UPDATE gda_control.architecture_provider_observation "
                    "SET observed_by = 'tampered' "
                    f"WHERE observation_id = '{first.observation.observation_id}'",
                )
                _assert_db_rejected(
                    connection,
                    "DELETE FROM gda_control.architecture_provider_observation "
                    f"WHERE observation_id = '{first.observation.observation_id}'",
                )
    finally:
        engine.dispose()
