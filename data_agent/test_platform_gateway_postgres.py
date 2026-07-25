import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.platform_authorization import build_policy_decision_artifact
from data_agent.platform_contracts import (
    Artifact,
    FrameworkAttemptObservation,
    LineageEvent,
    PlatformRun,
    PolicyDecision,
    QualityResult,
    Resource,
    ResourceVersion,
    RunPolicyReferences,
    RunSuccessEvidence,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import (
    DefinitionRegistration,
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)


DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "095_platform_command_outbox.sql",
        "096_platform_success_verdict.sql",
    )
)
TENANT = "gateway-tenant"
RUN_ID = "10000000-0000-4000-8000-000000000020"
DEFINITION_ID = "10000000-0000-4000-8000-000000000010"


def _assert_rejected(connection, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.exec_driver_sql(statement)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_gateway_role_is_tenant_scoped_and_append_only():
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            is_superuser = connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one()
            connection.rollback()
            if not is_superuser:
                pytest.skip("gateway role DDL test requires a PostgreSQL superuser")

            transaction = connection.begin()
            try:
                connection.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS agent_app_users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(100) UNIQUE NOT NULL
                    )
                    """
                )
                for migration in MIGRATIONS:
                    connection.execute(text(migration.read_text(encoding="utf-8")))

                role = connection.exec_driver_sql(
                    """
                    SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                           rolinherit, rolbypassrls
                    FROM pg_roles
                    WHERE rolname = 'gda_control_gateway'
                    """
                ).one()
                assert role == (False, False, False, False, False, False)

                privileges = connection.exec_driver_sql(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.resource', 'SELECT,INSERT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.resource', 'UPDATE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.resource', 'DELETE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_run_event', 'INSERT'
                        )
                    """
                ).one()
                assert privileges == (True, False, False, False)

                command_privileges = connection.exec_driver_sql(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_command_outbox',
                            'SELECT,INSERT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_command_outbox', 'UPDATE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_command_outbox', 'DELETE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.claim_platform_commands(text,text,text,integer,integer)',
                            'EXECUTE'
                        )
                    """
                ).one()
                assert command_privileges == (True, False, False, True)

                success_privileges = connection.exec_driver_sql(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.quality_result', 'SELECT,INSERT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.quality_result', 'UPDATE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.quality_result', 'DELETE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.apply_platform_run_transition(text,uuid,integer,text,text,text,jsonb)',
                            'EXECUTE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.finalize_platform_run_success(text,uuid,integer,text,text,jsonb)',
                            'EXECUTE'
                        )
                    """
                ).one()
                assert success_privileges == (True, False, False, False, True)

                connection.exec_driver_sql(
                    f"SET LOCAL app.current_tenant = '{TENANT}'"
                )
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.resource (
                        tenant_id, resource_urn, resource_kind,
                        authority_system, authority_locator, owner_ref
                    ) VALUES
                        ('{TENANT}', 'gda://{TENANT}/definition/parcel-publish',
                         'definition', 'gda', 'definition/parcel-publish', 'dataops'),
                        ('{TENANT}', 'gda://{TENANT}/dataset/source-parcels',
                         'dataset', 'iceberg', 'geo.source_parcels', 'dataops')
                    """
                )
                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.resource_version (
                        tenant_id, resource_version_id, resource_urn,
                        version_key, content_sha256,
                        authority_version_ref, created_by
                    ) VALUES
                        ('{TENANT}', '{DEFINITION_ID}',
                         'gda://{TENANT}/definition/parcel-publish',
                         'v1', repeat('d', 64), '{{"revision": 1}}', 'dataops'),
                        ('{TENANT}', '10000000-0000-4000-8000-000000000030',
                         'gda://{TENANT}/dataset/source-parcels',
                         'snapshot-1', repeat('a', 64), '{{"snapshot": 1}}', 'dataops')
                    """
                )
                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.platform_definition_version (
                        tenant_id, definition_version_id, definition_urn,
                        orchestration_class, capability_id, portability_class,
                        definition_document, input_contract, output_contract,
                        definition_sha256
                    ) VALUES (
                        '{TENANT}', '{DEFINITION_ID}',
                        'gda://{TENANT}/definition/parcel-publish',
                        'dataops', 'land_use.publish', 'portable',
                        '{{"tasks": ["publish"]}}', '{{"source": "dataset"}}',
                        '{{"product": "dataset"}}', repeat('d', 64)
                    )
                    """
                )
                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.platform_run (
                        tenant_id, run_id, definition_version_id,
                        orchestration_class, subject_context,
                        idempotency_key, submitted_by
                    ) VALUES (
                        '{TENANT}', '{RUN_ID}', '{DEFINITION_ID}', 'dataops',
                        '{{"tenant_id":"{TENANT}","subject_id":"operator",'
                        '"subject_type":"workload","roles":["platform_operator"],'
                        '"purpose":"gateway-test"}}',
                        'gateway-test-run', 'workload:operator'
                    )
                    """
                )

                initial_event = connection.exec_driver_sql(
                    f"""
                    SELECT sequence_no, from_status, to_status
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = '{TENANT}' AND run_id = '{RUN_ID}'
                    """
                ).one()
                assert initial_event == (0, None, "accepted")

                _assert_rejected(
                    connection,
                    f"UPDATE gda_control.resource SET owner_ref = 'other' "
                    f"WHERE tenant_id = '{TENANT}'",
                )
                _assert_rejected(
                    connection,
                    f"""
                    INSERT INTO gda_control.platform_run_event (
                        tenant_id, run_id, sequence_no, from_status,
                        to_status, actor_subject, reason
                    ) VALUES (
                        '{TENANT}', '{RUN_ID}', 99, 'accepted',
                        'failed', 'forger', 'forged'
                    )
                    """,
                )
                _assert_rejected(
                    connection,
                    """
                    INSERT INTO gda_control.resource (
                        tenant_id, resource_urn, resource_kind,
                        authority_system, authority_locator, owner_ref
                    ) VALUES (
                        'other-tenant', 'gda://other-tenant/dataset/private',
                        'dataset', 'iceberg', 'private', 'other'
                    )
                    """,
                )

                next_version = connection.exec_driver_sql(
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT}', '{RUN_ID}', 0, 'dispatching',
                        'workload:operator', 'accepted by provider', '{{}}'
                    )
                    """
                ).scalar_one()
                assert next_version == 1
                _assert_rejected(
                    connection,
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT}', '{RUN_ID}', 1, 'succeeded',
                        'workload:operator', 'provider said success', '{{}}'
                    )
                    """,
                )
                _assert_rejected(
                    connection,
                    f"""
                    SELECT gda_control.apply_platform_run_transition(
                        '{TENANT}', '{RUN_ID}', 1, 'running',
                        'workload:operator', 'bypass attempt', '{{}}'
                    )
                    """,
                )
            finally:
                connection.exec_driver_sql("RESET ROLE")
                if connection.in_transaction():
                    transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_platform_gateway_service_writes_idempotent_control_chain():
    engine = create_engine(DATABASE_URL)
    tenant = f"gateway-service-{uuid4().hex[:12]}"
    definition_id = uuid4()
    source_version_id = uuid4()
    target_version_id = uuid4()
    run_id = uuid4()
    actor = "workload:gateway-test"
    now = datetime.now(timezone.utc)

    try:
        with engine.begin() as connection:
            is_superuser = connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one()
            if not is_superuser:
                pytest.skip("gateway service DDL test requires a PostgreSQL superuser")
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS agent_app_users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL
                )
                """
            )
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))

        gateway = PlatformGateway(engine)
        definition_document = {"tasks": ["publish"]}
        input_contract = {"source": "dataset"}
        output_contract = {"product": "dataset"}
        definition_sha256 = platform_definition_fingerprint(
            orchestration_class="dataops",
            capability_id="land_use.publish",
            portability_class="portable",
            definition_document=definition_document,
            input_contract=input_contract,
            output_contract=output_contract,
        )
        definition_urn = f"gda://{tenant}/definition/parcel-publish"
        definition_resource = Resource(
            tenant_id=tenant,
            resource_urn=definition_urn,
            resource_kind="definition",
            authority_system="gda",
            authority_locator="definition/parcel-publish",
            owner_ref="team:dataops",
        )
        definition_version = ResourceVersion(
            tenant_id=tenant,
            resource_urn=definition_urn,
            resource_version_id=definition_id,
            version_key="v1",
            content_sha256=definition_sha256,
            authority_version_ref={"revision": 1},
            created_by=actor,
            created_at=now,
        )
        registration = DefinitionRegistration(
            resource=definition_resource,
            resource_version=definition_version,
            definition={
                "tenant_id": tenant,
                "definition_urn": definition_urn,
                "definition_version_id": definition_id,
                "orchestration_class": "dataops",
                "capability_id": "land_use.publish",
                "portability_class": "portable",
                "definition_document": definition_document,
                "input_contract": input_contract,
                "output_contract": output_contract,
                "definition_sha256": definition_sha256,
            },
        )
        assert gateway.register_definition(registration).created is True
        assert gateway.register_definition(registration).created is False

        source_urn = f"gda://{tenant}/dataset/source-parcels"
        target_urn = f"gda://{tenant}/dataset/published-parcels"
        source_resource = Resource(
            tenant_id=tenant,
            resource_urn=source_urn,
            resource_kind="dataset",
            authority_system="iceberg",
            authority_locator="geo.source_parcels",
            owner_ref="team:data-platform",
        )
        target_resource = Resource(
            tenant_id=tenant,
            resource_urn=target_urn,
            resource_kind="dataset",
            authority_system="iceberg",
            authority_locator="geo.published_parcels",
            owner_ref="team:data-platform",
        )
        source_version = ResourceVersion(
            tenant_id=tenant,
            resource_urn=source_urn,
            resource_version_id=source_version_id,
            version_key="snapshot-1",
            content_sha256="a" * 64,
            authority_version_ref={"snapshot": 1},
            created_by=actor,
            created_at=now,
        )
        target_version = ResourceVersion(
            tenant_id=tenant,
            resource_urn=target_urn,
            resource_version_id=target_version_id,
            version_key="snapshot-2",
            content_sha256="b" * 64,
            authority_version_ref={"snapshot": 2},
            created_by=actor,
            created_at=now,
        )
        for resource in (source_resource, target_resource):
            assert gateway.register_resource(resource).created is True
            assert gateway.register_resource(resource).created is False
        for version in (source_version, target_version):
            assert gateway.register_resource_version(version).created is True
            assert gateway.register_resource_version(version).created is False

        plan_manifest = {"schema": "gda.gateway_test_execution_plan.v1"}
        execution_plan = Artifact(
            tenant_id=tenant,
            artifact_id=uuid4(),
            artifact_key="gateway-test-execution-plan",
            artifact_role="execution_plan",
            storage_uri=f"postgresql://gda-control/execution-plans/{tenant}/test",
            media_type="application/vnd.gda.test-plan+json",
            content_sha256=canonical_json_fingerprint(plan_manifest),
            size_bytes=len(b'{"schema":"gda.gateway_test_execution_plan.v1"}'),
            run_id=None,
            resource_version_id=definition_id,
            manifest=plan_manifest,
            created_by=actor,
            created_at=now,
        )
        assert gateway.record_artifact(execution_plan).created is True

        run_subject = SubjectContext(
            tenant_id=tenant,
            subject_id="gateway-test",
            subject_type="workload",
            roles=("platform_operator",),
            purpose="exercise the controlled write chain",
        )
        policy_artifact = build_policy_decision_artifact(
            PolicyDecision(
                tenant_id=tenant,
                run_id=run_id,
                subject_context=run_subject,
                action="dolphinscheduler.dispatch",
                definition_version_id=definition_id,
                resource_version_ids=(definition_id, source_version_id),
                execution_plan_artifact_id=execution_plan.artifact_id,
                effect="allow",
                policy_version_ref=f"gda://{tenant}/policy/dataops-dispatch:v1",
                evaluator_subject="workload:policy-evaluator",
                decided_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        assert gateway.record_artifact(policy_artifact).created is True

        run = PlatformRun(
            tenant_id=tenant,
            run_id=run_id,
            definition_version_id=definition_id,
            orchestration_class="dataops",
            subject_context=run_subject,
            input_bindings=(
                {
                    "binding_name": "source",
                    "resource_version_id": source_version_id,
                    "semantic_type": "gis.land_use.parcels",
                },
            ),
            idempotency_key=f"publish:{source_version_id}",
            policy_refs=RunPolicyReferences(
                policy_decision_artifact_id=policy_artifact.artifact_id
            ),
            submitted_at=now,
        )
        assert gateway.submit_run(run, request_dispatch=True).created is True
        replay = gateway.submit_run(run, request_dispatch=True)
        assert replay.created is False
        assert replay.value == run
        assert gateway.get_run(tenant, run_id).policy_refs == run.policy_refs

        assert gateway.claim_commands(
            tenant,
            "worker:wrong-subject",
            actor_subject="workload:other-adapter",
            limit=10,
            lease_seconds=5,
        ) == []
        claimed = gateway.claim_commands(
            tenant,
            "worker:first",
            actor_subject=actor,
            limit=10,
            lease_seconds=5,
        )
        assert len(claimed) == 1
        dispatch_command = claimed[0]
        assert dispatch_command.command_type.value == "dolphinscheduler.dispatch"
        assert dispatch_command.attempt_count == 1
        assert dispatch_command.claimed_by == "worker:first"
        assert gateway.claim_commands(
            f"other-{tenant}",
            "worker:other",
            actor_subject=actor,
            limit=10,
            lease_seconds=5,
        ) == []

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE gda_control.platform_command_outbox
                    SET claimed_until = now() - interval '1 second'
                    WHERE tenant_id = :tenant_id AND command_id = :command_id
                    """
                ),
                {"tenant_id": tenant, "command_id": dispatch_command.command_id},
            )
        reclaimed = gateway.claim_commands(
            tenant,
            "worker:replacement",
            actor_subject=actor,
            limit=10,
            lease_seconds=5,
        )
        assert len(reclaimed) == 1
        assert reclaimed[0].command_id == dispatch_command.command_id
        assert reclaimed[0].attempt_count == 2
        with pytest.raises(GatewayConflictError):
            gateway.complete_command(
                tenant,
                dispatch_command.command_id,
                worker_id="worker:first",
            )
        deferred = gateway.defer_dispatch_to_reconcile(
            reclaimed[0],
            worker_id="worker:replacement",
        )
        assert deferred.command_type.value == "dolphinscheduler.reconcile"
        completed_dispatch = gateway.get_command(
            tenant, dispatch_command.command_id
        )
        assert completed_dispatch.status.value == "done"
        replay_after_delivery = gateway.submit_run(run, request_dispatch=True)
        assert replay_after_delivery.created is False
        assert replay_after_delivery.value == run
        deferred_claim = gateway.claim_commands(
            tenant,
            "worker:deferred",
            actor_subject=actor,
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in deferred_claim] == [deferred.command_id]
        gateway.complete_command(
            tenant,
            deferred.command_id,
            worker_id="worker:deferred",
        )

        transitioned = gateway.transition_run(
            tenant,
            run_id,
            0,
            "dispatching",
            actor,
            "provider accepted dispatch",
        )
        assert transitioned.status.value == "dispatching"
        assert transitioned.state_version == 1
        assert gateway.get_run(tenant, run_id) == transitioned

        observation_id = uuid4()
        observation_evidence = {"provider_status": "submitted"}
        observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=observation_id,
            run_id=run_id,
            attempt_no=1,
            framework_kind="legacy",
            external_namespace="gateway-test",
            external_run_id=str(run_id),
            observed_state="submitted",
            observation_sha256=canonical_json_fingerprint(observation_evidence),
            evidence=observation_evidence,
            observed_at=now,
        )
        assert gateway.record_attempt(observation).created is True
        assert gateway.record_attempt(observation).created is False

        callback_id = uuid4()
        callback_evidence = {
            "schema": "gda.dolphinscheduler_callback.v1",
            "callback_id": str(callback_id),
            "provider_state": "RUNNING_EXECUTION",
        }
        callback = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=callback_id,
            run_id=run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="1001",
            external_run_id="901",
            observed_state="running_execution",
            observation_sha256=canonical_json_fingerprint(callback_evidence),
            evidence=callback_evidence,
            observed_at=now,
        )
        callback_result = gateway.record_attempt_and_enqueue_reconcile(
            callback,
            actor_subject=actor,
        )
        assert callback_result.created is True
        callback_replay = gateway.record_attempt_and_enqueue_reconcile(
            callback,
            actor_subject=actor,
        )
        assert callback_replay.created is False
        assert callback_replay.value == callback_result.value
        reconcile_commands = gateway.claim_commands(
            tenant,
            "worker:callback",
            actor_subject=actor,
            limit=10,
            lease_seconds=5,
        )
        assert len(reconcile_commands) == 1
        assert reconcile_commands[0].command_type.value == "dolphinscheduler.reconcile"
        assert reconcile_commands[0].trigger_observation_id == callback_id
        retry = gateway.fail_command(
            tenant,
            reconcile_commands[0].command_id,
            worker_id="worker:callback",
            error="provider temporarily unavailable",
            retry_delay_seconds=0,
        )
        assert retry.status.value == "pending"
        assert retry.last_error == "provider temporarily unavailable"
        retried = gateway.claim_commands(
            tenant,
            "worker:callback-retry",
            actor_subject=actor,
            limit=10,
            lease_seconds=5,
        )
        assert len(retried) == 1
        gateway.complete_command(
            tenant,
            retried[0].command_id,
            worker_id="worker:callback-retry",
        )
        callback_after_delivery = gateway.record_attempt_and_enqueue_reconcile(
            callback,
            actor_subject=actor,
        )
        assert callback_after_delivery.created is False
        assert callback_after_delivery.value.status.value == "done"

        running = gateway.transition_run(
            tenant,
            run_id,
            1,
            "running",
            actor,
            "provider correlation verified",
        )
        assert running.status.value == "running"
        assert running.state_version == 2

        success_observation_evidence = {
            "schema": "gda.dolphinscheduler_observation.v1",
            "provider_state": "SUCCESS",
        }
        success_observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="1001",
            external_run_id="901",
            observed_state="success",
            observation_sha256=canonical_json_fingerprint(
                success_observation_evidence
            ),
            evidence=success_observation_evidence,
            observed_at=now,
        )
        assert gateway.record_attempt(success_observation).created is True

        mismatched_artifact = Artifact(
            tenant_id=tenant,
            artifact_id=uuid4(),
            artifact_key="published-parcels-unbound",
            artifact_role="output",
            storage_uri=f"s3://gateway-test/{tenant}/unbound.parquet",
            media_type="application/vnd.apache.parquet",
            content_sha256="c" * 64,
            size_bytes=1024,
            run_id=run_id,
            resource_version_id=target_version_id,
            manifest={"row_count": 3},
            created_by=actor,
            created_at=now,
        )
        assert gateway.record_artifact(mismatched_artifact).created is True

        artifact = Artifact(
            tenant_id=tenant,
            artifact_id=uuid4(),
            artifact_key="published-parcels",
            artifact_role="output",
            storage_uri=f"s3://gateway-test/{tenant}/published.parquet",
            media_type="application/vnd.apache.parquet",
            content_sha256="b" * 64,
            size_bytes=1024,
            run_id=run_id,
            resource_version_id=target_version_id,
            manifest={"row_count": 3},
            created_by=actor,
            created_at=now,
        )
        assert gateway.record_artifact(artifact).created is True
        assert gateway.record_artifact(artifact).created is False
        assert gateway.get_artifact(tenant, artifact.artifact_id) == artifact
        with pytest.raises(GatewayNotFoundError, match="Artifact was not found"):
            gateway.get_artifact(f"other-{tenant}", artifact.artifact_id)

        quality_evaluator = "workload:quality-evaluator"
        quality_metrics = {"feature_count": 3, "geometry_errors": 0}
        quality_manifest = {
            "schema": "gda.quality_evidence.v1",
            "metrics": quality_metrics,
        }
        quality_evidence = Artifact(
            tenant_id=tenant,
            artifact_id=uuid4(),
            artifact_key="published-parcels-quality-evidence",
            artifact_role="evidence",
            storage_uri=f"s3://gateway-test/{tenant}/quality-result.json",
            media_type="application/vnd.gda.quality-evidence+json",
            content_sha256=canonical_json_fingerprint(quality_manifest),
            size_bytes=128,
            run_id=run_id,
            resource_version_id=target_version_id,
            manifest=quality_manifest,
            created_by=quality_evaluator,
            created_at=now,
        )
        assert gateway.record_artifact(quality_evidence).created is True

        same_actor_evidence = Artifact(
            tenant_id=tenant,
            artifact_id=uuid4(),
            artifact_key="same-actor-quality-evidence",
            artifact_role="evidence",
            storage_uri=f"s3://gateway-test/{tenant}/same-actor-quality.json",
            media_type="application/vnd.gda.quality-evidence+json",
            content_sha256=canonical_json_fingerprint(quality_manifest),
            size_bytes=128,
            run_id=run_id,
            resource_version_id=target_version_id,
            manifest=quality_manifest,
            created_by=actor,
            created_at=now,
        )
        assert gateway.record_artifact(same_actor_evidence).created is True

        def quality_result(
            verdict: str,
            *,
            evaluator=quality_evaluator,
            evidence_artifact=quality_evidence,
        ) -> QualityResult:
            quality_result_id = uuid4()
            return QualityResult(
                tenant_id=tenant,
                quality_result_id=quality_result_id,
                run_id=run_id,
                resource_version_id=target_version_id,
                rule_version_ref=f"gda://{tenant}/quality-rule/dltb-v1",
                verdict=verdict,
                metrics=quality_metrics,
                evidence_artifact_id=evidence_artifact.artifact_id,
                result_sha256=quality_result_fingerprint(
                    tenant_id=tenant,
                    run_id=run_id,
                    resource_version_id=target_version_id,
                    rule_version_ref=(
                        f"gda://{tenant}/quality-rule/dltb-v1"
                    ),
                    verdict=verdict,
                    metrics=quality_metrics,
                    evidence_artifact_id=evidence_artifact.artifact_id,
                    evaluated_by=evaluator,
                    evaluated_at=now,
                ),
                evaluated_by=evaluator,
                evaluated_at=now,
            )

        failed_quality = quality_result("failed")
        passed_quality = quality_result("passed")
        same_actor_quality = quality_result(
            "passed",
            evaluator=actor,
            evidence_artifact=same_actor_evidence,
        )
        assert gateway.record_quality_result(failed_quality).created is True
        assert gateway.record_quality_result(passed_quality).created is True
        assert gateway.record_quality_result(same_actor_quality).created is True
        assert (
            gateway.get_quality_result(tenant, passed_quality.quality_result_id)
            == passed_quality
        )

        lineage_facets = {"operation": "publish"}
        lineage = LineageEvent(
            tenant_id=tenant,
            lineage_event_id=uuid4(),
            event_type="publish",
            source_resource_version_id=source_version_id,
            target_resource_version_id=target_version_id,
            producer=actor,
            event_sha256=canonical_json_fingerprint(
                {
                    "source": str(source_version_id),
                    "target": str(target_version_id),
                    "run": str(run_id),
                    "facets": lineage_facets,
                }
            ),
            run_id=run_id,
            definition_version_id=definition_id,
            artifact_id=artifact.artifact_id,
            facets=lineage_facets,
            occurred_at=now,
        )
        assert gateway.record_lineage(lineage).created is True
        assert gateway.record_lineage(lineage).created is False

        def success_evidence(
            *,
            output_artifact_id=artifact.artifact_id,
            quality_result_id=passed_quality.quality_result_id,
            lineage_event_id=lineage.lineage_event_id,
        ) -> RunSuccessEvidence:
            fingerprint = run_success_evidence_fingerprint(
                tenant_id=tenant,
                run_id=run_id,
                attempt_observation_id=success_observation.observation_id,
                output_artifact_id=output_artifact_id,
                quality_result_id=quality_result_id,
                lineage_event_id=lineage_event_id,
            )
            return RunSuccessEvidence(
                tenant_id=tenant,
                run_id=run_id,
                attempt_observation_id=success_observation.observation_id,
                output_artifact_id=output_artifact_id,
                quality_result_id=quality_result_id,
                lineage_event_id=lineage_event_id,
                evidence_sha256=fingerprint,
            )

        with pytest.raises(GatewayValidationError, match="evidence-gated"):
            gateway.transition_run(
                tenant,
                run_id,
                2,
                "succeeded",
                actor,
                "provider said success",
            )
        with pytest.raises(GatewayValidationError):
            gateway.finalize_run_success(
                success_evidence(
                    output_artifact_id=mismatched_artifact.artifact_id
                ),
                expected_state_version=2,
                actor_subject=actor,
                reason="mismatched output must fail",
            )
        with pytest.raises(GatewayValidationError):
            gateway.finalize_run_success(
                success_evidence(
                    quality_result_id=failed_quality.quality_result_id
                ),
                expected_state_version=2,
                actor_subject=actor,
                reason="failed quality must fail",
            )
        with pytest.raises(GatewayValidationError):
            gateway.finalize_run_success(
                success_evidence(
                    quality_result_id=same_actor_quality.quality_result_id
                ),
                expected_state_version=2,
                actor_subject=actor,
                reason="same actor quality must fail",
            )
        with pytest.raises(GatewayValidationError):
            gateway.finalize_run_success(
                success_evidence(lineage_event_id=uuid4()),
                expected_state_version=2,
                actor_subject=actor,
                reason="missing lineage must fail",
            )

        valid_evidence = success_evidence()
        tampered_details = {
            "schema": "gda.run_success_evidence.v1",
            **valid_evidence.model_dump(mode="json"),
            "evidence_sha256": "0" * 64,
        }
        with pytest.raises(GatewayValidationError):
            with gateway._transaction(tenant) as connection:
                connection.execute(
                    text(
                        """
                        SELECT gda_control.finalize_platform_run_success(
                            :tenant_id, :run_id, :expected_state_version,
                            :actor_subject, :reason, CAST(:details AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "run_id": run_id,
                        "expected_state_version": 2,
                        "actor_subject": actor,
                        "reason": "tampered fingerprint must fail",
                        "details": json.dumps(tampered_details),
                    },
                ).scalar_one()

        succeeded = gateway.finalize_run_success(
            valid_evidence,
            expected_state_version=2,
            actor_subject=actor,
            reason="all success evidence passed",
        )
        assert succeeded.status.value == "succeeded"
        assert succeeded.state_version == 3
        replayed_success = gateway.finalize_run_success(
            valid_evidence,
            expected_state_version=2,
            actor_subject=actor,
            reason="all success evidence passed",
        )
        assert replayed_success == succeeded
    finally:
        engine.dispose()
