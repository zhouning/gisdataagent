"""Real PostGIS acceptance for compatibility- and lineage-bound review."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseNotFoundError,
    ApprovalCaseValidationError,
)
from data_agent.architecture_change_assessment import (
    SUCCESSOR_BLOCKERS,
    ArchitectureChangeAssessmentService,
)
from data_agent.data_architecture_ledger import (
    ArchitectureReconciliationStatus,
    DataArchitectureRegistration,
    DataContractVersion,
    ResourceVersionArchitectureBinding,
    architecture_binding_fingerprint,
    data_contract_version_fingerprint,
)
from data_agent.platform_contracts import (
    ApprovalCaseStatus,
    LineageEvent,
    Resource,
    ResourceVersion,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import GatewayNotFoundError, PlatformGateway
from data_agent.postgis_architecture_harvester import (
    PostgisArchitectureTarget,
    harvest_postgis_architecture,
)
from data_agent.postgis_schema_evidence import (
    SchemaCompatibilityVerdict,
    build_postgis_schema_evidence_artifact,
    postgis_schema_snapshot_bytes,
)

POSTGIS_ASSESSMENT_DATABASE_URL = os.environ.get("POSTGIS_ASSESSMENT_DATABASE_URL")
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
    assert artifact.content_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert gateway.record_artifact(artifact).created
    return artifact


def _assert_db_rejected(connection, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.exec_driver_sql(statement)


@pytest.mark.skipif(
    not POSTGIS_ASSESSMENT_DATABASE_URL,
    reason="POSTGIS_ASSESSMENT_DATABASE_URL is not configured",
)
def test_real_postgis_compatibility_lineage_and_assessed_approval(tmp_path: Path):
    engine = create_engine(POSTGIS_ASSESSMENT_DATABASE_URL)
    tenant = f"postgis-assessment-{uuid4().hex[:8]}"
    resource_version_id = uuid4()
    downstream_version_id = uuid4()
    resource_urn = f"gda://{tenant}/dataset/parcels"
    downstream_urn = f"gda://{tenant}/dataset/parcels-derived"
    actor = "workload:postgis-harvester"
    observed_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
    try:
        with engine.begin() as connection:
            if not connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one():
                pytest.skip("PostGIS architecture test requires a superuser")
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
            connection.exec_driver_sql(
                "CREATE INDEX parcels_geom_gix ON provider_geo.parcels USING gist (geom)"
            )

        gateway = PlatformGateway(engine)
        approval_authority = ApprovalCaseAuthority(engine)
        assessment_service = ArchitectureChangeAssessmentService(
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
            provider_ref="assessment-postgis",
            schema_name="provider_geo",
            table_name="parcels",
            snapshot_ref="provider-snapshot:1",
            content_checksum="a" * 64,
        )
        baseline = harvest_postgis_architecture(
            engine,
            target,
            observed_by=actor,
            observed_at=observed_at,
            freshness_seconds=300,
        )
        assert baseline.schema_snapshot is not None
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
            "schema_version_id": baseline.schema_candidate.schema_version_id,
            "data_contract_version_id": contract.data_contract_version_id,
            "physical_location_id": (baseline.physical_location_candidate.physical_location_id),
        }
        binding = ResourceVersionArchitectureBinding(
            binding_sha256=architecture_binding_fingerprint(**binding_values),
            bound_by="workload:architecture-controller",
            bound_at=observed_at,
            **binding_values,
        )
        gateway.register_resource_version_architecture(
            DataArchitectureRegistration(
                schema_version=baseline.schema_candidate,
                data_contract_version=contract,
                physical_location=baseline.physical_location_candidate,
                binding=binding,
            )
        )

        gateway.register_resource(
            Resource(
                tenant_id=tenant,
                resource_urn=downstream_urn,
                resource_kind="dataset",
                authority_system="postgis",
                authority_locator="provider_geo.parcels_derived",
                owner_ref="team:analytics",
            )
        )
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=tenant,
                resource_urn=downstream_urn,
                resource_version_id=downstream_version_id,
                version_key="snapshot-1",
                content_sha256="b" * 64,
                authority_version_ref={"snapshot": "derived-snapshot:1"},
                created_by="workload:analytics-pipeline",
                created_at=observed_at,
            )
        )
        lineage_values = {
            "source": str(resource_version_id),
            "target": str(downstream_version_id),
            "operation": "derive",
        }
        lineage = LineageEvent(
            tenant_id=tenant,
            lineage_event_id=uuid4(),
            event_type="derive",
            source_resource_version_id=resource_version_id,
            target_resource_version_id=downstream_version_id,
            producer="workload:analytics-pipeline",
            event_sha256=canonical_json_fingerprint(lineage_values),
            facets={"operation": "derive"},
            occurred_at=observed_at,
        )
        gateway.record_lineage(lineage)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE provider_geo.parcels ADD COLUMN zoning_code text"
            )
        additive_at = observed_at + timedelta(minutes=1)
        additive = harvest_postgis_architecture(
            engine,
            target,
            observed_by=actor,
            observed_at=additive_at,
            freshness_seconds=300,
        )
        assert additive.schema_snapshot is not None
        gateway.record_architecture_provider_observation(additive.observation)
        additive_artifact = _record_schema_evidence(
            gateway,
            additive,
            tmp_path / "additive.json",
        )
        additive_reconciliation = gateway.reconcile_resource_version_architecture(
            tenant,
            resource_version_id,
            evaluated_at=additive_at + timedelta(seconds=1),
        )
        assert additive_reconciliation.status is ArchitectureReconciliationStatus.SCHEMA_DRIFT
        additive_result = assessment_service.request_review(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            baseline_snapshot=baseline.schema_snapshot,
            candidate_snapshot=additive.schema_snapshot,
            baseline_schema_artifact_id=baseline_artifact.artifact_id,
            candidate_schema_artifact_id=additive_artifact.artifact_id,
            requester_subject="agent:architecture-reviewer",
            request_reason="review additive PostGIS schema change and impact",
            owner_ref="team:spatial-data",
            requested_at=additive_at + timedelta(seconds=1),
            expires_at=additive_at + timedelta(hours=1),
            evaluated_at=additive_at + timedelta(seconds=1),
            max_lineage_depth=3,
            max_lineage_edges=20,
        )
        assert additive_result.created
        assert (
            additive_result.compatibility.verdict is SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE
        )
        assert additive_result.impact.lineage.edge_count == 1
        assert additive_result.impact.impacted_resource_version_count == 2
        assert additive_result.review.successor_blockers == SUCCESSOR_BLOCKERS
        assert "zoning_code" not in additive_result.approval_case.model_dump_json()
        assert not assessment_service.request_review(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            baseline_snapshot=baseline.schema_snapshot,
            candidate_snapshot=additive.schema_snapshot,
            baseline_schema_artifact_id=baseline_artifact.artifact_id,
            candidate_schema_artifact_id=additive_artifact.artifact_id,
            requester_subject="agent:architecture-reviewer",
            request_reason="review additive PostGIS schema change and impact",
            owner_ref="team:spatial-data",
            requested_at=additive_at + timedelta(seconds=1),
            expires_at=additive_at + timedelta(hours=1),
            evaluated_at=additive_at + timedelta(seconds=1),
            max_lineage_depth=3,
            max_lineage_edges=20,
        ).created
        with pytest.raises(ApprovalCaseValidationError):
            approval_authority.decide(
                tenant_id=tenant,
                approval_case_ref=additive_result.approval_case.approval_case_ref,
                expected_state_version=0,
                verdict=ApprovalCaseStatus.APPROVED,
                actor_subject="agent:architecture-reviewer",
                reason="agent verdict is forbidden",
            )
        approved = approval_authority.decide(
            tenant_id=tenant,
            approval_case_ref=additive_result.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:data-steward",
            reason="assessment accepted; successor prerequisites remain blocked",
        )
        assert approved.status is ApprovalCaseStatus.APPROVED

        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE provider_geo.parcels DROP COLUMN land_use")
        breaking_at = additive_at + timedelta(minutes=1)
        breaking = harvest_postgis_architecture(
            engine,
            target,
            observed_by=actor,
            observed_at=breaking_at,
            freshness_seconds=300,
        )
        assert breaking.schema_snapshot is not None
        gateway.record_architecture_provider_observation(breaking.observation)
        breaking_artifact = _record_schema_evidence(
            gateway,
            breaking,
            tmp_path / "breaking.json",
        )
        breaking_result = assessment_service.request_review(
            tenant_id=tenant,
            resource_version_id=resource_version_id,
            baseline_snapshot=baseline.schema_snapshot,
            candidate_snapshot=breaking.schema_snapshot,
            baseline_schema_artifact_id=baseline_artifact.artifact_id,
            candidate_schema_artifact_id=breaking_artifact.artifact_id,
            requester_subject="workload:architecture-controller",
            request_reason="review breaking PostGIS schema change and impact",
            owner_ref="team:spatial-data",
            requested_at=breaking_at + timedelta(seconds=1),
            expires_at=breaking_at + timedelta(hours=1),
            evaluated_at=breaking_at + timedelta(seconds=1),
            max_lineage_depth=3,
            max_lineage_edges=20,
        )
        assert breaking_result.created
        assert breaking_result.compatibility.verdict is SchemaCompatibilityVerdict.BREAKING
        assert breaking_result.compatibility.breaking_change_count >= 1
        assert breaking_result.approval_case.approval_case_ref != (
            additive_result.approval_case.approval_case_ref
        )

        assert (
            gateway.get_resource_version_architecture(
                tenant,
                resource_version_id,
            ).binding
            == binding
        )
        with engine.begin() as connection:
            original_version_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control.resource_version "
                        "WHERE tenant_id = :tenant_id "
                        "AND resource_urn = :resource_urn"
                    ),
                    {"tenant_id": tenant, "resource_urn": resource_urn},
                ).scalar_one()
            )
            assert original_version_count == 1
            _assert_db_rejected(
                connection,
                "UPDATE gda_control.artifact SET size_bytes = 0 "
                f"WHERE artifact_id = '{baseline_artifact.artifact_id}'",
            )
        with pytest.raises(GatewayNotFoundError):
            gateway.get_artifact("another-tenant", baseline_artifact.artifact_id)
        with pytest.raises(ApprovalCaseNotFoundError):
            approval_authority.get(
                "another-tenant",
                additive_result.approval_case.approval_case_ref,
            )
    finally:
        engine.dispose()
