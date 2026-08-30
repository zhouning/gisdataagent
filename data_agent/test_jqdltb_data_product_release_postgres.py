"""Disposable PostgreSQL acceptance for the JQDLTB product release authority."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.data_product_registry import DataProductRegistry, DataProductRegistryError
from data_agent.jqdltb_data_product_release import (
    JqdltbDataProductReleaseService,
    build_jqdltb_data_product_release_plan,
)
from data_agent.platform_contracts import (
    ApprovalCaseStatus,
    FrameworkAttemptObservation,
    Resource,
    ResourceVersion,
    RunStatus,
    RunSuccessEvidence,
    build_jqdltb_transformation_approval_case,
    canonical_json_fingerprint,
    compile_jqdltb_executable_contract,
    platform_definition_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import DefinitionRegistration, PlatformGateway
from data_agent.test_jqdltb_data_product_release import _facts, _packet_for_contract
from data_agent.test_jqdltb_transformation_executor import _proposal

DATABASE_URL = os.environ.get("JQDLTB_RELEASE_DATABASE_URL")
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
        "230_jqdltb_data_product_release_authority.sql",
        "234_jqdltb_decision_packet_release_binding.sql",
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


@pytest.mark.skipif(not DATABASE_URL, reason="JQDLTB_RELEASE_DATABASE_URL is not configured")
def test_real_jqdltb_release_is_approval_and_evidence_bound() -> None:
    engine = create_engine(DATABASE_URL)
    gateway = PlatformGateway(engine)
    approvals = ApprovalCaseAuthority(engine)
    registry = DataProductRegistry(engine)
    service = JqdltbDataProductReleaseService(registry, approvals)
    facts = _facts()
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        _bootstrap(engine)
        proposal = _proposal(semantic_candidate_audit_sha256="a" * 64)
        transform_pending = build_jqdltb_transformation_approval_case(
            proposal,
            case_id="jqdltb-postgres-transform",
            requester_subject="workload:ar0-contract-builder",
            request_reason="certify approved JQDLTB transformation",
            requested_at=now - timedelta(minutes=2),
            expires_at=now + timedelta(hours=2),
        )
        approvals.create(transform_pending, owner_ref="team:cq-land-data")
        transform_case = approvals.decide(
            tenant_id=proposal.tenant_id,
            approval_case_ref=transform_pending.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:cq-land-data-steward",
            reason="transformation policy approved for certification",
        )
        contract = compile_jqdltb_executable_contract(
            proposal,
            approval_case=transform_case,
            created_by="workload:ar0-contract-compiler",
            created_at=datetime.now(UTC),
        )
        facts["decision_packet"] = _packet_for_contract(
            contract, facts["operating_contract"]
        )

        accepted_run = facts["run"].model_copy(
            update={"status": RunStatus.ACCEPTED, "state_version": 0}
        )
        definition_urn = (
            f"gda://{accepted_run.tenant_id}/definition/jqdltb-transformation"
        )
        definition_document = {"workflow": "chongqing-jqdltb-transformation"}
        input_contract = {"source": "gis.land_use.parcel.source"}
        output_contract = {"candidate": "gis.land_use.parcel.canonical"}
        definition_sha = platform_definition_fingerprint(
            orchestration_class="dataops",
            capability_id="jqdltb.transform",
            portability_class="portable",
            definition_document=definition_document,
            input_contract=input_contract,
            output_contract=output_contract,
        )
        gateway.register_definition(
            DefinitionRegistration(
                resource=Resource(
                    tenant_id=accepted_run.tenant_id,
                    resource_urn=definition_urn,
                    resource_kind="definition",
                    authority_system="gis-data-agent",
                    authority_locator="definition/jqdltb-transformation",
                    owner_ref="team:data-platform",
                ),
                resource_version=ResourceVersion(
                    tenant_id=accepted_run.tenant_id,
                    resource_urn=definition_urn,
                    resource_version_id=accepted_run.definition_version_id,
                    version_key="v1",
                    content_sha256=definition_sha,
                    authority_version_ref={"revision": 1},
                    created_by="workload:data-platform-controller",
                    created_at=accepted_run.submitted_at,
                ),
                definition={
                    "tenant_id": accepted_run.tenant_id,
                    "definition_urn": definition_urn,
                    "definition_version_id": accepted_run.definition_version_id,
                    "orchestration_class": "dataops",
                    "capability_id": "jqdltb.transform",
                    "portability_class": "portable",
                    "definition_document": definition_document,
                    "input_contract": input_contract,
                    "output_contract": output_contract,
                    "definition_sha256": definition_sha,
                },
            )
        )
        source_urn = contract.source_resource_urn
        output_urn = f"gda://{accepted_run.tenant_id}/dataset/jqdltb-canonical"
        for resource in (
            Resource(
                tenant_id=accepted_run.tenant_id,
                resource_urn=source_urn,
                resource_kind="dataset",
                authority_system="source-bundle",
                authority_locator="source/jqdltb",
                owner_ref="team:cq-land-data",
            ),
            Resource(
                tenant_id=accepted_run.tenant_id,
                resource_urn=output_urn,
                resource_kind="dataset",
                authority_system="gis-data-agent",
                authority_locator="products/jqdltb/layer-manifest.json",
                owner_ref="team:cq-land-data",
            ),
        ):
            gateway.register_resource(resource)
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=accepted_run.tenant_id,
                resource_urn=source_urn,
                resource_version_id=contract.source_resource_version_id,
                version_key="source-v1",
                content_sha256=contract.bundle_sha256,
                authority_version_ref={"archive_sha256": contract.archive_sha256},
                created_by="workload:source-onboarding",
                created_at=accepted_run.submitted_at,
            )
        )
        gateway.register_resource_version(
            ResourceVersion(
                tenant_id=accepted_run.tenant_id,
                resource_urn=output_urn,
                resource_version_id=facts[
                    "transformation_result"
                ].output_resource_version_id,
                version_key="candidate-v1",
                content_sha256=facts["output_artifact"].content_sha256,
                authority_version_ref={"contract_sha256": contract.contract_sha256},
                created_by="workload:dolphinscheduler-gda-dataops",
                created_at=facts["output_artifact"].created_at,
            )
        )
        gateway.submit_run(accepted_run)
        dispatched = gateway.transition_run(
            accepted_run.tenant_id,
            accepted_run.run_id,
            0,
            "dispatching",
            "workload:dolphinscheduler-gda-dataops",
            "provider accepted JQDLTB transformation",
        )
        running = gateway.transition_run(
            accepted_run.tenant_id,
            accepted_run.run_id,
            dispatched.state_version,
            "running",
            "workload:dolphinscheduler-gda-dataops",
            "provider correlation verified",
        )
        observation_evidence = {
            "schema": "gda.dolphinscheduler_observation.v1",
            "provider_state": "SUCCESS",
        }
        observation = FrameworkAttemptObservation(
            tenant_id=accepted_run.tenant_id,
            observation_id=uuid4(),
            run_id=accepted_run.run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="jqdltb-certification",
            external_run_id=str(accepted_run.run_id),
            observed_state="success",
            observation_sha256=canonical_json_fingerprint(observation_evidence),
            evidence=observation_evidence,
            observed_at=now,
        )
        gateway.record_attempt(observation)
        for artifact in (
            facts["output_artifact"],
            facts["quality_evidence_artifact"],
            facts["backup_restore_evidence_artifact"],
        ):
            gateway.record_artifact(artifact)
        gateway.record_quality_result(facts["quality_result"])
        gateway.record_lineage(facts["lineage_event"])
        success = RunSuccessEvidence(
            tenant_id=accepted_run.tenant_id,
            run_id=accepted_run.run_id,
            attempt_observation_id=observation.observation_id,
            output_artifact_id=facts["output_artifact"].artifact_id,
            quality_result_id=facts["quality_result"].quality_result_id,
            lineage_event_id=facts["lineage_event"].lineage_event_id,
            evidence_sha256=run_success_evidence_fingerprint(
                tenant_id=accepted_run.tenant_id,
                run_id=accepted_run.run_id,
                attempt_observation_id=observation.observation_id,
                output_artifact_id=facts["output_artifact"].artifact_id,
                quality_result_id=facts["quality_result"].quality_result_id,
                lineage_event_id=facts["lineage_event"].lineage_event_id,
            ),
        )
        succeeded_run = gateway.finalize_run_success(
            success,
            expected_state_version=running.state_version,
            actor_subject="workload:dolphinscheduler-gda-dataops",
            reason="JQDLTB provider, quality and lineage evidence passed",
        )

        published_at = now + timedelta(minutes=5)
        plan = build_jqdltb_data_product_release_plan(
            **facts
            | {
                "run": succeeded_run,
                "transformation_contract": contract,
                "published_at": published_at,
            }
        )
        requested = service.request_release(
            plan,
            requester_subject="workload:data-product-controller",
            request_reason="publish certified JQDLTB layered product",
            owner_ref="team:cq-land-data",
            requested_at=now,
            expires_at=now + timedelta(hours=1),
        )
        with pytest.raises(ValueError, match="not executable"):
            service.publish(
                plan,
                idempotency_key="publish-jqdltb-v1",
                reason="pending approval must fail",
                now=published_at,
            )
        approvals.decide(
            tenant_id=plan.tenant_id,
            approval_case_ref=requested.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:cq-land-release-owner",
            reason="release evidence and operating ownership approved",
        )

        with pytest.raises(DataProductRegistryError):
            registry.publish(
                plan.product,
                plan.data_product_version,
                idempotency_key="bypass-jqdltb-release",
                reason="direct registry bypass must fail",
            )
        def publish_once():
            return service.publish(
                plan,
                idempotency_key="publish-jqdltb-v1",
                reason="publish approved JQDLTB layered product",
                now=published_at,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_results = list(executor.map(lambda _index: publish_once(), range(2)))
        created_results = [item for item in concurrent_results if item["version_created"]]
        replay_results = [item for item in concurrent_results if item["idempotent_replay"]]
        assert len(created_results) == 1
        assert created_results[0]["pointer_changed"]
        assert created_results[0]["jqdltb_release_created"]
        assert len(replay_results) == 1
        assert not replay_results[0]["jqdltb_release_created"]

        replay = publish_once()
        assert replay["idempotent_replay"]
        assert not replay["jqdltb_release_created"]
        with engine.begin() as connection:
            counts = connection.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM gda_control.data_product_version) AS versions,
                      (SELECT count(*) FROM gda_control.jqdltb_data_product_release) AS releases,
                      (SELECT count(*) FROM gda_control.approval_case
                        WHERE status = 'approved') AS approvals
                    """
                )
            ).one()
            assert counts == (1, 1, 2)
            rls = connection.execute(
                text(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                      FROM pg_class
                     WHERE oid = 'gda_control.jqdltb_data_product_release'::regclass
                    """
                )
            ).one()
            assert rls == (True, True)
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE gda_control.jqdltb_data_product_release "
                            "SET bound_by = 'workload:tampered'"
                        )
                    )
        with engine.begin() as connection:
            connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": "other-tenant"},
            )
            assert connection.execute(
                text("SELECT count(*) FROM gda_control.jqdltb_data_product_release")
            ).scalar_one() == 0
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": str(plan.tenant_id)},
            )
            assert connection.execute(
                text("SELECT count(*) FROM gda_control.jqdltb_data_product_release")
            ).scalar_one() == 1
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE gda_control.jqdltb_data_product_release "
                            "SET bound_by = 'workload:tampered'"
                        )
                    )
    finally:
        engine.dispose()
