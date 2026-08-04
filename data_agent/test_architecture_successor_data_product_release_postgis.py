"""Real PostgreSQL acceptance for architecture-successor DataProduct release."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.architecture_successor_adoption import (
    build_architecture_successor_adoption_case,
    build_architecture_successor_plan,
)
from data_agent.architecture_successor_data_product_release import (
    ArchitectureSuccessorDataProductReleaseService,
    build_architecture_successor_data_product_release_plan,
)
from data_agent.data_architecture_ledger import DataArchitectureRegistration
from data_agent.data_product_registry import (
    DataProductConflictError,
    DataProductRegistry,
    DataProductRegistryError,
)
from data_agent.platform_contracts import (
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    Resource,
    ResourceVersion,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.test_architecture_successor_adoption import _facts
from data_agent.test_architecture_successor_data_product_release import _release_facts

POSTGIS_RELEASE_DATABASE_URL = os.environ.get(
    "POSTGIS_ARCHITECTURE_RELEASE_DATABASE_URL"
)
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "096_platform_success_verdict.sql",
        "100_data_product_registry.sql",
        "101_data_product_promotion.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "105_asset_distribution_grant.sql",
        "106_version_locked_distribution_grant.sql",
        "107_distribution_grant_package_quota.sql",
        "108_data_product_promotion_impact.sql",
        "113_data_architecture_version_authority.sql",
        "114_data_architecture_provider_observation.sql",
        "115_architecture_successor_adoption_lock.sql",
        "116_architecture_successor_data_product_release.sql",
    )
)


def _bootstrap(engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') "
            "THEN CREATE ROLE agent_user NOLOGIN; END IF; "
            "END $$"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE agent_data_assets (
                id SERIAL PRIMARY KEY,
                asset_name TEXT NOT NULL,
                operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE agent_data_requests (
                id SERIAL PRIMARY KEY,
                asset_id INTEGER NOT NULL REFERENCES agent_data_assets(id),
                requester VARCHAR(100) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'pending',
                approver VARCHAR(100),
                approved_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))


def _pending(case, *, requested_at: datetime):
    return case.model_copy(
        update={
            "status": ApprovalCaseStatus.PENDING,
            "state_version": 0,
            "requested_at": requested_at,
            "expires_at": requested_at + timedelta(hours=4),
            "decided_by": None,
            "decision_reason": None,
            "decided_at": None,
        }
    )


@pytest.mark.skipif(
    not POSTGIS_RELEASE_DATABASE_URL,
    reason="POSTGIS_ARCHITECTURE_RELEASE_DATABASE_URL is not configured",
)
def test_real_atomic_architecture_successor_product_release() -> None:
    engine = create_engine(POSTGIS_RELEASE_DATABASE_URL)
    gateway = PlatformGateway(engine)
    approvals = ApprovalCaseAuthority(engine)
    registry = DataProductRegistry(engine)
    release_service = ArchitectureSuccessorDataProductReleaseService(
        registry,
        approvals,
    )
    facts = _facts()
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        _bootstrap(engine)
        predecessor = facts["predecessor"]
        gateway.register_resource(
            Resource(
                tenant_id=predecessor.tenant_id,
                resource_urn=predecessor.resource_urn,
                resource_kind="dataset",
                authority_system="certification",
                authority_locator="postgis/public/parcels",
                owner_ref="team:spatial-data",
            )
        )
        gateway.register_resource_version(predecessor)
        gateway.register_resource_version_architecture(
            DataArchitectureRegistration(
                schema_version=(
                    facts["predecessor_architecture"].schema_version_record
                ),
                data_contract_version=(
                    facts["predecessor_architecture"].data_contract_version_record
                ),
                physical_location=facts["predecessor_architecture"].physical_location,
                binding=facts["predecessor_architecture"].binding,
            )
        )
        gateway.record_architecture_provider_observation(facts["observation"])
        gateway.record_artifact(facts["candidate_schema_artifact"])

        assessment_pending = _pending(
            facts["assessed_case"],
            requested_at=now - timedelta(minutes=2),
        )
        approvals.create(assessment_pending, owner_ref="team:spatial-data")
        assessed_case = approvals.decide(
            tenant_id=predecessor.tenant_id,
            approval_case_ref=assessment_pending.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:data-steward",
            reason="architecture assessment accepted",
        )
        architecture_plan = build_architecture_successor_plan(
            **facts | {"assessed_case": assessed_case}
        )
        adoption_pending = build_architecture_successor_adoption_case(
            architecture_plan,
            requester_subject="workload:architecture-controller",
            request_reason="adopt reviewed successor architecture",
            requested_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(hours=3),
        )
        approvals.create(adoption_pending, owner_ref="team:spatial-data")
        adoption_case = approvals.decide(
            tenant_id=predecessor.tenant_id,
            approval_case_ref=adoption_pending.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:architecture-owner",
            reason="architecture successor adoption accepted",
        )
        adopted = gateway.adopt_architecture_successor(
            architecture_plan,
            adoption_approval_case_ref=adoption_case.approval_case_ref,
            evaluated_at=architecture_plan.successor_resource_version.created_at
            + timedelta(seconds=1),
        )
        assert adopted.created

        release_facts = _release_facts(timeline_start=now)
        product = release_facts["product"]
        predecessor_product_version = release_facts[
            "predecessor_data_product_version"
        ]
        successor_product_version = release_facts[
            "successor_data_product_version"
        ]
        source_urn = f"gda://{product.tenant_id}/dataset/product-source"
        gateway.register_resource(
            Resource(
                tenant_id=product.tenant_id,
                resource_urn=source_urn,
                resource_kind="dataset",
                authority_system="certification",
                authority_locator="input/product-source",
                owner_ref="team:spatial-data",
            )
        )
        for source_version_id, version_key in (
            (predecessor_product_version.source_resource_version_id, "source-1"),
            (successor_product_version.source_resource_version_id, "source-2"),
        ):
            gateway.register_resource_version(
                ResourceVersion(
                    tenant_id=product.tenant_id,
                    resource_urn=source_urn,
                    resource_version_id=source_version_id,
                    version_key=version_key,
                    content_sha256=("2" if version_key == "source-1" else "3")
                    * 64,
                    authority_version_ref={"snapshot_ref": version_key},
                    created_by="workload:certifier",
                    created_at=predecessor_product_version.published_at,
                )
            )
        predecessor_quality = Artifact(
            tenant_id=product.tenant_id,
            artifact_id=predecessor_product_version.quality_evidence_artifact_id,
            artifact_key="quality.parcels-v1.json",
            artifact_role=ArtifactRole.EVIDENCE,
            storage_uri="s3://product-evidence/quality/parcels-v1.json",
            media_type="application/json",
            content_sha256="1" * 64,
            size_bytes=10,
            resource_version_id=predecessor.resource_version_id,
            manifest={"verdict": "passed"},
            created_by="workload:quality-controller",
            created_at=predecessor_product_version.published_at,
        )
        gateway.record_artifact(predecessor_quality)
        baseline = registry.publish(
            product,
            predecessor_product_version,
            idempotency_key="publish-parcels-v1",
            reason="publish baseline parcel product",
        )
        assert baseline["pointer_changed"]

        gateway.record_artifact(release_facts["quality_evidence_artifact"])
        for artifact in release_facts["distribution_artifacts"]:
            gateway.record_artifact(artifact)
        release_plan = build_architecture_successor_data_product_release_plan(
            **release_facts
            | {
                "architecture_successor_plan": architecture_plan,
                "architecture_adoption_case": adoption_case,
            }
        )

        with pytest.raises(DataProductRegistryError):
            registry.publish(
                product,
                successor_product_version,
                idempotency_key="bypass-release-approval",
                reason="attempt direct successor publication",
            )
        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM gda_control.data_product_version "
                    "WHERE data_product_version_id = :version_id"
                ),
                {
                    "version_id": successor_product_version.data_product_version_id
                },
            ).scalar_one() == 0

        release_request = release_service.request_release(
            release_plan,
            requester_subject="workload:data-product-controller",
            request_reason="release adopted parcel successor",
            owner_ref="team:spatial-data",
            requested_at=now,
            expires_at=now + timedelta(hours=3),
        )
        with pytest.raises(DataProductConflictError, match="not an approved plan"):
            release_service.publish(
                release_plan,
                release_approval_case_ref=(
                    release_request.approval_case.approval_case_ref
                ),
                idempotency_key="release-parcels-v2",
                reason="publish approved architecture successor",
            )
        approvals.decide(
            tenant_id=product.tenant_id,
            approval_case_ref=release_request.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:data-product-owner",
            reason="product release evidence accepted",
        )
        released = release_service.publish(
            release_plan,
            release_approval_case_ref=release_request.approval_case.approval_case_ref,
            idempotency_key="release-parcels-v2",
            reason="publish approved architecture successor",
        )
        assert released["version_created"]
        assert released["architecture_release_created"]
        assert released["pointer_changed"]
        assert not released["promotion_deferred"]

        replay = release_service.publish(
            release_plan,
            release_approval_case_ref=release_request.approval_case.approval_case_ref,
            idempotency_key="release-parcels-v2",
            reason="retry approved architecture successor",
        )
        assert replay["idempotent_replay"]
        assert not replay["architecture_release_created"]

        rolled_back = registry.rollback(
            product.tenant_id,
            product.product_slug,
            predecessor_product_version.version_key,
            actor_subject="human:data-product-owner",
            reason="exercise approved rollback pointer",
            idempotency_key="rollback-parcels-v2",
            occurred_at=successor_product_version.published_at + timedelta(minutes=1),
        )
        assert rolled_back["pointer_changed"]
        promoted = registry.promote(
            product.tenant_id,
            product.product_slug,
            successor_product_version.version_key,
            actor_subject="human:data-product-owner",
            reason="restore validated successor",
            idempotency_key="promote-parcels-v2",
            occurred_at=successor_product_version.published_at + timedelta(minutes=2),
        )
        assert promoted["pointer_changed"]

        with engine.begin() as connection:
            release_row = connection.execute(
                text(
                    "SELECT release_plan_sha256, rollback_target_version_id "
                    "FROM gda_control.data_product_architecture_release"
                )
            ).one()
            assert release_row.release_plan_sha256 == release_plan.plan_sha256
            assert release_row.rollback_target_version_id == (
                predecessor_product_version.data_product_version_id
            )
            assert connection.execute(
                text(
                    "SELECT count(*) FROM gda_control.data_product_event "
                    "WHERE event_type IN ('advanced', 'rolled_back', 'promoted')"
                )
            ).scalar_one() == 3
    finally:
        engine.dispose()
