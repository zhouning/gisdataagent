import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.dataops_cancel import DataOpsCancelSpec
from data_agent.dataops_manual import (
    DataOpsManualTriggerSpec,
    dataops_manual_run_id,
)
from data_agent.dataops_schedule import (
    DataOpsScheduleWindowSpec,
    dataops_schedule_idempotency_key,
)
from data_agent.metadata_fabric import (
    MetadataFabricBinding,
    metadata_fabric_binding_fingerprint,
)
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
from data_agent.platform_openlineage import (
    OpenLineageRunEvent,
    openlineage_to_lineage_events,
)
from data_agent.spatial_anonymization_run import (
    SpatialAnonymizationRequest,
    SpatialAnonymizationRunSpec,
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
        "097_platform_cancel_command.sql",
        "098_platform_data_incident.sql",
        "099_platform_incident_notification_outbox.sql",
        "226_incident_notification_provider_receipt.sql",
        "112_metadata_fabric_binding_outbox.sql",
        "123_resource_bound_data_incident.sql",
        "129_platform_run_event_delivery_outbox.sql",
        "186_metadata_fabric_search_bridge.sql",
    )
)
DATA_PRODUCT_MIGRATION = (
    Path(__file__).resolve().parent / "migrations" / "100_data_product_registry.sql"
)
TENANT = "gateway-tenant"
RUN_ID = "10000000-0000-4000-8000-000000000020"
DEFINITION_ID = "10000000-0000-4000-8000-000000000010"


def _assert_rejected(connection, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.exec_driver_sql(statement)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_gateway_role_is_tenant_scoped_and_append_only(
    isolated_postgres_url: str,
):
    engine = create_engine(isolated_postgres_url)
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

                incident_privileges = connection.exec_driver_sql(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident', 'SELECT,INSERT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident', 'UPDATE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident', 'DELETE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident_event', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.transition_data_incident(text,uuid,integer,text,text,text,jsonb)',
                            'EXECUTE'
                        )
                    """
                ).one()
                assert incident_privileges == (True, False, False, False, True)

                notification_privileges = connection.exec_driver_sql(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident_notification_outbox', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident_notification_outbox', 'INSERT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident_notification_outbox', 'UPDATE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.data_incident_notification_outbox', 'DELETE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.claim_data_incident_notifications(text,text,integer,integer)',
                            'EXECUTE'
                        )
                    """
                ).one()
                assert notification_privileges == (True, False, False, False, True)

                run_event_delivery_privileges = connection.exec_driver_sql(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_run_event_delivery_outbox', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_run_event_delivery_outbox', 'INSERT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_run_event_delivery_outbox', 'UPDATE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.platform_run_event_delivery_outbox', 'DELETE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.claim_platform_run_event_deliveries(text,text,integer,integer)',
                            'EXECUTE'
                        )
                    """
                ).one()
                assert run_event_delivery_privileges == (
                    True,
                    False,
                    False,
                    False,
                    True,
                )

                connection.exec_driver_sql(f"SET LOCAL app.current_tenant = '{TENANT}'")
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
                    SELECT event_id, sequence_no, from_status, to_status
                    FROM gda_control.platform_run_event
                    WHERE tenant_id = '{TENANT}' AND run_id = '{RUN_ID}'
                    """
                ).one()
                assert initial_event[1:] == (0, None, "accepted")
                initial_delivery = connection.exec_driver_sql(
                    f"""
                    SELECT run_event_id, run_id, run_sequence_no, channel,
                           destination_ref, status, attempt_count
                    FROM gda_control.platform_run_event_delivery_outbox
                    WHERE tenant_id = '{TENANT}' AND run_id = '{RUN_ID}'
                    """
                ).one()
                assert initial_delivery == (
                    initial_event.event_id,
                    UUID(RUN_ID),
                    0,
                    "gda.platform-runs.status",
                    "cloudevents:platform-run-default",
                    "pending",
                    0,
                )

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
def test_platform_gateway_service_writes_idempotent_control_chain(
    isolated_postgres_url: str,
):
    engine = create_engine(isolated_postgres_url)
    tenant = f"gateway-service-{uuid4().hex[:12]}"
    definition_id = uuid4()
    source_version_id = uuid4()
    target_version_id = uuid4()
    second_target_version_id = uuid4()
    run_id = uuid4()
    actor = "workload:gateway-test"
    now = datetime.now(UTC)

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
            if connection.exec_driver_sql(
                "SELECT to_regclass('gda_control.data_product')"
            ).scalar_one() is None:
                connection.exec_driver_sql(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_roles WHERE rolname = 'agent_user'
                        ) THEN
                            CREATE ROLE agent_user NOLOGIN;
                        END IF;
                    END
                    $$
                    """
                )
                connection.execute(
                    text(DATA_PRODUCT_MIGRATION.read_text(encoding="utf-8"))
                )

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
        second_target_version = ResourceVersion(
            tenant_id=tenant,
            resource_urn=target_urn,
            resource_version_id=second_target_version_id,
            version_key="snapshot-3",
            content_sha256="c" * 64,
            authority_version_ref={"snapshot": 3},
            predecessor_version_id=target_version_id,
            created_by=actor,
            created_at=now,
        )
        for resource in (source_resource, target_resource):
            assert gateway.register_resource(resource).created is True
            assert gateway.register_resource(resource).created is False
        for version in (source_version, target_version, second_target_version):
            assert gateway.register_resource_version(version).created is True
            assert gateway.register_resource_version(version).created is False

        def metadata_binding(
            resource_urn: str,
            *,
            system: str,
            binding_kind: str,
            external_object_id: str,
            external_namespace: str = "catalog:gateway-test",
        ) -> MetadataFabricBinding:
            values = {
                "tenant_id": tenant,
                "binding_id": uuid4(),
                "resource_urn": resource_urn,
                "system": system,
                "binding_kind": binding_kind,
                "external_namespace": external_namespace,
                "external_object_id": external_object_id,
                "external_object_type": "table",
                "external_version_ref": "test-version",
                "created_by": actor,
                "created_at": now,
            }
            values["binding_sha256"] = metadata_fabric_binding_fingerprint(
                **{
                    key: values[key]
                    for key in (
                        "tenant_id",
                        "resource_urn",
                        "system",
                        "binding_kind",
                        "external_namespace",
                        "external_object_id",
                        "external_object_type",
                        "external_version_ref",
                    )
                }
            )
            return MetadataFabricBinding(**values)

        source_openmetadata = metadata_binding(
            source_urn,
            system="openmetadata",
            binding_kind="governance_entity",
            external_object_id="30000000-0000-4000-8000-000000000001",
        )
        target_openmetadata = metadata_binding(
            target_urn,
            system="openmetadata",
            binding_kind="governance_entity",
            external_object_id="30000000-0000-4000-8000-000000000002",
        )
        target_gravitino = metadata_binding(
            target_urn,
            system="gravitino",
            binding_kind="technical_object",
            external_object_id="gravitino-published-parcels",
        )
        for binding in (
            source_openmetadata,
            target_openmetadata,
            target_gravitino,
        ):
            assert gateway.register_metadata_fabric_binding(binding).created is True
            assert gateway.register_metadata_fabric_binding(binding).created is False
        assert gateway.list_metadata_fabric_bindings(
            tenant,
            target_urn,
        ) == (target_gravitino, target_openmetadata)
        assert gateway.list_metadata_fabric_bindings(
            tenant,
            target_urn,
            system="openmetadata",
        ) == (target_openmetadata,)
        search_page = gateway.search_metadata_fabric_bindings(
            tenant,
            query="published",
            system="gravitino",
            limit=1,
            offset=0,
        )
        assert search_page.items == (target_gravitino,)
        assert search_page.has_more is False

        conflicting_openmetadata = metadata_binding(
            source_urn,
            system="openmetadata",
            binding_kind="governance_entity",
            external_object_id="30000000-0000-4000-8000-000000000003",
        )
        with pytest.raises(GatewayConflictError):
            gateway.register_metadata_fabric_binding(conflicting_openmetadata)

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
        initial_run_events = gateway.claim_platform_run_event_deliveries(
            tenant,
            "worker:run-events",
            limit=10,
            lease_seconds=5,
        )
        assert len(initial_run_events) == 1
        initial_run_event = initial_run_events[0]
        assert initial_run_event.event.run_id == run_id
        assert initial_run_event.event.sequence_no == 0
        assert initial_run_event.event.to_status.value == "accepted"
        assert initial_run_event.delivery.run_event_id == initial_run_event.event.event_id
        retrying_run_event = gateway.fail_platform_run_event_delivery(
            tenant,
            initial_run_event.delivery.delivery_id,
            worker_id="worker:run-events",
            error="CloudEvents receiver returned HTTP 503",
            retry_delay_seconds=0,
        )
        assert retrying_run_event.status.value == "pending"
        retried_run_events = gateway.claim_platform_run_event_deliveries(
            tenant,
            "worker:run-events-replacement",
            limit=10,
            lease_seconds=5,
        )
        assert [item.delivery.delivery_id for item in retried_run_events] == [
            initial_run_event.delivery.delivery_id
        ]
        with pytest.raises(GatewayConflictError):
            gateway.complete_platform_run_event_delivery(
                tenant,
                initial_run_event.delivery.delivery_id,
                worker_id="worker:run-events",
            )
        completed_run_event = gateway.complete_platform_run_event_delivery(
            tenant,
            initial_run_event.delivery.delivery_id,
            worker_id="worker:run-events-replacement",
        )
        assert completed_run_event.status.value == "done"
        assert gateway.claim_platform_run_event_deliveries(
            f"other-{tenant}",
            "worker:other-run-events",
            limit=10,
            lease_seconds=5,
        ) == ()

        schedule_actor = "workload:schedule-gateway-test"
        schedule_values = {
            "tenant_id": tenant,
            "definition_version_id": definition_id,
            "schedule_ref": f"gda://{tenant}/schedule/parcel-publish-daily",
            "scheduled_for": now - timedelta(days=1),
            "logical_start": now - timedelta(days=2),
            "logical_end": now - timedelta(days=1),
            "input_bindings": (
                {
                    "binding_name": "source",
                    "resource_version_id": source_version_id,
                    "semantic_type": "gis.land_use.parcels",
                },
            ),
            "execution_plan_artifact_id": execution_plan.artifact_id,
            "workload_subject_id": "schedule-gateway-test",
            "purpose": "recover one governed daily parcel window",
            "policy_version_ref": f"gda://{tenant}/policy/dataops-schedule:v1",
            "policy_evaluator_subject": "workload:policy-evaluator",
        }
        rejected_window = DataOpsScheduleWindowSpec(
            **(
                schedule_values
                | {
                    "execution_plan_artifact_id": uuid4(),
                    "scheduled_for": now - timedelta(days=2),
                    "logical_start": now - timedelta(days=3),
                    "logical_end": now - timedelta(days=2),
                }
            )
        )
        with pytest.raises(GatewayValidationError, match="Execution plan"):
            gateway.submit_schedule_window(rejected_window)
        with engine.connect() as connection:
            rolled_back = (
                connection.execute(
                    text(
                        """
                    SELECT
                        (SELECT count(*) FROM gda_control.platform_run
                         WHERE tenant_id = :tenant_id
                           AND idempotency_key = :idempotency_key) AS run_count,
                        (SELECT count(*) FROM gda_control.resource
                         WHERE tenant_id = :tenant_id
                           AND resource_urn = :resource_urn) AS resource_count
                    """
                    ),
                    {
                        "tenant_id": tenant,
                        "idempotency_key": dataops_schedule_idempotency_key(rejected_window),
                        "resource_urn": f"gda://{tenant}/trigger/{definition_id}",
                    },
                )
                .mappings()
                .one()
            )
        assert dict(rolled_back) == {"run_count": 0, "resource_count": 0}

        schedule_window = DataOpsScheduleWindowSpec(**schedule_values)
        with ThreadPoolExecutor(max_workers=2) as pool:
            schedule_results = tuple(
                pool.map(
                    lambda _index: gateway.submit_schedule_window(schedule_window),
                    range(2),
                )
            )
        assert sum(result.run_created for result in schedule_results) == 1
        assert sum(result.command_created for result in schedule_results) == 1
        assert len({result.run.run_id for result in schedule_results}) == 1
        assert len({result.command.command_id for result in schedule_results}) == 1
        assert len({result.admitted_at for result in schedule_results}) == 1
        schedule_claims = gateway.claim_commands(
            tenant,
            "worker:schedule",
            actor_subject=schedule_actor,
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in schedule_claims] == [
            schedule_results[0].command.command_id
        ]
        gateway.complete_command(
            tenant,
            schedule_claims[0].command_id,
            worker_id="worker:schedule",
        )

        manual_values = {
            "tenant_id": tenant,
            "client_request_id": "gateway-manual-request-001",
            "definition_version_id": definition_id,
            "logical_start": now - timedelta(hours=2),
            "logical_end": now - timedelta(hours=1),
            "input_bindings": (
                {
                    "binding_name": "source",
                    "resource_version_id": source_version_id,
                    "semantic_type": "gis.land_use.parcels",
                },
            ),
            "execution_plan_artifact_id": execution_plan.artifact_id,
            "requester_subject": "human:gateway-operator",
            "workload_subject_id": "manual-gateway-test",
            "purpose": "execute one governed operator-requested parcel audit",
            "policy_version_ref": f"gda://{tenant}/policy/dataops-manual:v1",
            "policy_evaluator_subject": "workload:policy-evaluator",
        }
        rejected_manual = DataOpsManualTriggerSpec(
            **(
                manual_values
                | {
                    "client_request_id": "gateway-manual-missing-plan",
                    "execution_plan_artifact_id": uuid4(),
                }
            )
        )
        with pytest.raises(GatewayValidationError, match="Execution plan"):
            gateway.submit_manual_trigger(rejected_manual)
        with engine.connect() as connection:
            rolled_back_manual = (
                connection.execute(
                    text(
                        """
                    SELECT
                        (SELECT count(*) FROM gda_control.platform_run
                         WHERE tenant_id = :tenant_id
                           AND run_id = :run_id) AS run_count,
                        (SELECT count(*) FROM gda_control.resource_version
                         WHERE tenant_id = :tenant_id
                           AND authority_version_ref -> 'invocation'
                               ->> 'client_request_id' = :client_request_id)
                            AS invocation_version_count
                    """
                    ),
                    {
                        "tenant_id": tenant,
                        "run_id": dataops_manual_run_id(rejected_manual),
                        "client_request_id": rejected_manual.client_request_id,
                    },
                )
                .mappings()
                .one()
            )
        assert dict(rolled_back_manual) == {
            "run_count": 0,
            "invocation_version_count": 0,
        }

        manual_request = DataOpsManualTriggerSpec(**manual_values)
        with ThreadPoolExecutor(max_workers=2) as pool:
            manual_results = tuple(
                pool.map(
                    lambda _index: gateway.submit_manual_trigger(manual_request),
                    range(2),
                )
            )
        assert sum(result.run_created for result in manual_results) == 1
        assert sum(result.command_created for result in manual_results) == 1
        assert len({result.run.run_id for result in manual_results}) == 1
        assert len({result.command.command_id for result in manual_results}) == 1
        assert len({result.admitted_at for result in manual_results}) == 1
        assert manual_results[0].invocation.requested_by == "human:gateway-operator"
        assert manual_results[0].run.subject_context.delegated_by == ("human:gateway-operator")
        with pytest.raises(GatewayConflictError, match="different immutable binding"):
            gateway.submit_manual_trigger(
                DataOpsManualTriggerSpec(**(manual_values | {"logical_end": now}))
            )
        manual_claims = gateway.claim_commands(
            tenant,
            "worker:manual",
            actor_subject="workload:manual-gateway-test",
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in manual_claims] == [manual_results[0].command.command_id]
        gateway.complete_command(
            tenant,
            manual_claims[0].command_id,
            worker_id="worker:manual",
        )

        spatial_request_values = {
            "tenant_id": tenant,
            "client_request_id": "gateway-spatial-anonymization-001",
            "requester_subject": "human:gateway-operator",
            "source_asset_ref": "agent_data_assets:gateway-source-1",
            "source_schema": "restricted",
            "source_table": "parcel_source",
            "output_schema": "public",
            "output_table": "parcel_source_l3",
            "data_type": "polygon",
            "level": "L3",
            "k_anonymity": 5,
            "keep_attrs": ("land_use", "area_m2"),
            "agg_strategy": "area_weighted",
            "dp_epsilon": 1.0,
            "dp_numeric_fields": ("area_m2",),
        }
        spatial_spec_values = {
            "request": SpatialAnonymizationRequest(**spatial_request_values),
            "definition_version_id": definition_id,
            "execution_plan_artifact_id": execution_plan.artifact_id,
            "workload_subject_id": "spatial-gateway-test",
            "purpose": "produce a governed anonymized parcel output",
            "policy_version_ref": f"gda://{tenant}/policy/spatial-anonymization:v1",
            "policy_evaluator_subject": "workload:policy-evaluator",
        }
        spatial_spec = SpatialAnonymizationRunSpec(**spatial_spec_values)
        with ThreadPoolExecutor(max_workers=2) as pool:
            spatial_results = tuple(
                pool.map(
                    lambda _index: gateway.submit_spatial_anonymization_run(
                        spatial_spec
                    ),
                    range(2),
                )
            )
        assert sum(result.run_created for result in spatial_results) == 1
        assert sum(result.command_created for result in spatial_results) == 1
        assert sum(result.request_version_created for result in spatial_results) == 1
        assert len({result.run.run_id for result in spatial_results}) == 1
        assert len({result.command.command_id for result in spatial_results}) == 1
        assert len({result.admitted_at for result in spatial_results}) == 1
        assert spatial_results[0].run.subject_context.delegated_by == (
            "human:gateway-operator"
        )
        with pytest.raises(GatewayConflictError, match="different immutable binding"):
            gateway.submit_spatial_anonymization_run(
                SpatialAnonymizationRunSpec(
                    **(
                        spatial_spec_values
                        | {
                            "request": SpatialAnonymizationRequest(
                                **(spatial_request_values | {"k_anonymity": 10})
                            )
                        }
                    )
                )
            )
        with engine.connect() as connection:
            request_version_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.resource_version
                    WHERE tenant_id = :tenant_id
                      AND authority_version_ref ->> 'schema' =
                          'gda.security.spatial_anonymization_request_version.v1'
                      AND authority_version_ref -> 'request'
                          ->> 'client_request_id' = :client_request_id
                    """
                ),
                {
                    "tenant_id": tenant,
                    "client_request_id": spatial_spec.request.client_request_id,
                },
            ).scalar_one()
        assert request_version_count == 1
        spatial_claims = gateway.claim_commands(
            tenant,
            "worker:spatial",
            actor_subject="workload:spatial-gateway-test",
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in spatial_claims] == [
            spatial_results[0].command.command_id
        ]
        gateway.complete_command(
            tenant,
            spatial_claims[0].command_id,
            worker_id="worker:spatial",
        )

        manual_run_id = manual_results[0].run.run_id
        manual_actor = "workload:manual-gateway-test"
        dispatched_manual = gateway.transition_run(
            tenant,
            manual_run_id,
            0,
            "dispatching",
            manual_actor,
            "provider accepted the manual dispatch",
        )
        cancel_values = {
            "tenant_id": tenant,
            "run_id": manual_run_id,
            "client_request_id": "gateway-cancel-request-001",
            "expected_state_version": dispatched_manual.state_version,
            "requester_subject": "human:gateway-operator",
            "reason": "operator cancelled an obsolete source refresh",
            "workload_subject": manual_actor,
            "policy_version_ref": f"gda://{tenant}/policy/dataops-cancel:v1",
            "policy_evaluator_subject": "workload:policy-evaluator",
        }
        cancel_request = DataOpsCancelSpec(**cancel_values)
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancel_results = tuple(
                pool.map(
                    lambda _index: gateway.admit_dataops_cancel(cancel_request),
                    range(2),
                )
            )
        assert sum(result.command_created for result in cancel_results) == 1
        assert sum(result.policy_artifact_created for result in cancel_results) == 1
        assert len({result.command.command_id for result in cancel_results}) == 1
        assert len({result.admitted_at for result in cancel_results}) == 1
        assert cancel_results[0].run.status.value == "cancelling"
        assert cancel_results[0].run.state_version == 2
        assert cancel_results[0].command.payload["requester_subject"] == (
            "human:gateway-operator"
        )
        with pytest.raises(GatewayConflictError, match="different immutable binding"):
            gateway.admit_dataops_cancel(
                DataOpsCancelSpec(
                    **(
                        cancel_values
                        | {"reason": "a changed reason must not reuse request identity"}
                    )
                )
            )
        cancel_claims = gateway.claim_commands(
            tenant,
            "worker:cancel",
            actor_subject=manual_actor,
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in cancel_claims] == [
            cancel_results[0].command.command_id
        ]
        cancel_reconcile = gateway.complete_cancel_and_enqueue_reconcile(
            cancel_claims[0],
            worker_id="worker:cancel",
        )
        assert cancel_reconcile.command_type.value == "dolphinscheduler.reconcile"
        cancel_reconcile_claims = gateway.claim_commands(
            tenant,
            "worker:cancel-reconcile",
            actor_subject=manual_actor,
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in cancel_reconcile_claims] == [
            cancel_reconcile.command_id
        ]
        gateway.complete_command(
            tenant,
            cancel_reconcile.command_id,
            worker_id="worker:cancel-reconcile",
        )
        with engine.connect() as connection:
            cancel_requested_at, cancel_completed_at = connection.execute(
                text(
                    """
                    SELECT event.occurred_at, command.completed_at
                    FROM gda_control.platform_run_event AS event
                    JOIN gda_control.platform_command_outbox AS command
                      ON command.tenant_id = event.tenant_id
                     AND command.run_id = event.run_id
                    WHERE event.tenant_id = :tenant_id
                      AND event.run_id = :run_id
                      AND event.to_status = 'cancelling'
                      AND event.details ->> 'schema' =
                          'gda.dataops_cancel_admission.v1'
                      AND command.command_type = 'dolphinscheduler.cancel'
                    """
                ),
                {"tenant_id": tenant, "run_id": manual_run_id},
            ).one()
        provider_second_precision_terminal_at = cancel_requested_at.replace(
            microsecond=0
        )
        assert provider_second_precision_terminal_at <= cancel_requested_at
        assert provider_second_precision_terminal_at < cancel_completed_at

        stale_cancellation_evidence = {
            "schema": "gda.dolphinscheduler_observation.v1",
            "provider_state": "SUCCESS",
            "workflow_instance_id": 6,
        }
        stale_cancellation_observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=manual_run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="1001",
            external_run_id="6",
            observed_state="success",
            observation_sha256=canonical_json_fingerprint(
                stale_cancellation_evidence
            ),
            evidence=stale_cancellation_evidence,
            observed_at=now - timedelta(days=1),
        )
        with pytest.raises(GatewayValidationError, match="predates"):
            gateway.record_cancellation_terminal_mismatch(
                stale_cancellation_observation,
                actor_subject=manual_actor,
            )

        cancellation_failure_evidence = {
            "schema": "gda.dolphinscheduler_observation.v1",
            "provider_state": "FAILURE",
            "workflow_instance_id": 7,
        }
        cancellation_failure = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=manual_run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="1001",
            external_run_id="7",
            observed_state="failure",
            observation_sha256=canonical_json_fingerprint(
                cancellation_failure_evidence
            ),
            evidence=cancellation_failure_evidence,
            observed_at=provider_second_precision_terminal_at,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            incident_results = tuple(
                pool.map(
                    lambda _index: gateway.record_cancellation_terminal_mismatch(
                        cancellation_failure,
                        actor_subject=manual_actor,
                    ),
                    range(2),
                )
            )
        assert sum(result.incident_created for result in incident_results) == 1
        incident_result = incident_results[0]
        assert incident_result.incident.status.value == "open"
        assert incident_result.incident.severity.value == "high"
        assert incident_result.run.status.value == "failed"
        assert incident_result.run.status.value != "cancelled"
        replayed_incident = gateway.record_cancellation_terminal_mismatch(
            cancellation_failure,
            actor_subject=manual_actor,
        )
        assert replayed_incident.incident_created is False
        assert replayed_incident.incident == incident_result.incident
        assert gateway.get_incident(
            tenant, incident_result.incident.incident_id
        ) == incident_result.incident
        assert gateway.list_incidents(
            tenant,
            status="open",
            run_id=manual_run_id,
        ) == (incident_result.incident,)
        acknowledged_incident = gateway.transition_incident(
            tenant,
            incident_result.incident.incident_id,
            0,
            "acknowledged",
            "human:gateway-operator",
            "provider remediation assigned",
            {"ticket": "INC-GATEWAY-001"},
        )
        assert acknowledged_incident.status.value == "acknowledged"
        assert acknowledged_incident.state_version == 1
        resolved_incident = gateway.transition_incident(
            tenant,
            incident_result.incident.incident_id,
            1,
            "resolved",
            "human:gateway-operator",
            "provider failure retained and follow-up completed",
            {"resolution": "new Run required for semantic retry"},
        )
        assert resolved_incident.status.value == "resolved"
        assert resolved_incident.state_version == 2
        open_notifications = gateway.claim_incident_notifications(
            tenant,
            "worker:incident-alerts",
            limit=10,
            lease_seconds=5,
        )
        assert len(open_notifications) == 1
        assert open_notifications[0].event.sequence_no == 0
        assert open_notifications[0].event.to_status.value == "open"
        retrying_notification = gateway.fail_incident_notification(
            tenant,
            open_notifications[0].notification.notification_id,
            worker_id="worker:incident-alerts",
            error="Alertmanager returned HTTP 503",
            retry_delay_seconds=0,
        )
        assert retrying_notification.status.value == "pending"
        assert retrying_notification.attempt_count == 1
        retried_notifications = gateway.claim_incident_notifications(
            tenant,
            "worker:incident-alerts",
            limit=10,
            lease_seconds=5,
        )
        assert [
            item.notification.notification_id for item in retried_notifications
        ] == [open_notifications[0].notification.notification_id]
        completed_open = gateway.complete_incident_notification(
            tenant,
            retried_notifications[0].notification.notification_id,
            worker_id="worker:incident-alerts",
            provider_receipt={
                "schema": "gda.alertmanager_provider_receipt.v1",
                "provider": "alertmanager",
                "accepted": True,
                "http_status": 202,
                "destination_ref": "alertmanager:default",
                "accepted_at": "2026-08-01T12:00:00Z",
            },
        )
        assert completed_open.status.value == "done"
        assert completed_open.attempt_count == 2

        acknowledged_notifications = gateway.claim_incident_notifications(
            tenant,
            "worker:incident-alerts",
            limit=10,
            lease_seconds=5,
        )
        assert len(acknowledged_notifications) == 1
        assert acknowledged_notifications[0].event.sequence_no == 1
        assert acknowledged_notifications[0].event.to_status.value == "acknowledged"
        gateway.complete_incident_notification(
            tenant,
            acknowledged_notifications[0].notification.notification_id,
            worker_id="worker:incident-alerts",
            provider_receipt={
                "schema": "gda.alertmanager_provider_receipt.v1",
                "provider": "alertmanager",
                "accepted": True,
                "http_status": 202,
                "destination_ref": "alertmanager:default",
                "accepted_at": "2026-08-01T12:01:00Z",
            },
        )

        resolved_notifications = gateway.claim_incident_notifications(
            tenant,
            "worker:incident-alerts",
            limit=10,
            lease_seconds=5,
        )
        assert len(resolved_notifications) == 1
        assert resolved_notifications[0].event.sequence_no == 2
        assert resolved_notifications[0].event.to_status.value == "resolved"
        gateway.complete_incident_notification(
            tenant,
            resolved_notifications[0].notification.notification_id,
            worker_id="worker:incident-alerts",
            provider_receipt={
                "schema": "gda.alertmanager_provider_receipt.v1",
                "provider": "alertmanager",
                "accepted": True,
                "http_status": 202,
                "destination_ref": "alertmanager:default",
                "accepted_at": "2026-08-01T12:02:00Z",
            },
        )
        assert gateway.claim_incident_notifications(
            tenant,
            "worker:incident-alerts",
            limit=10,
            lease_seconds=5,
        ) == ()
        assert gateway.list_incidents(
            f"other-{tenant}",
            run_id=manual_run_id,
        ) == ()
        assert gateway.claim_incident_notifications(
            f"other-{tenant}",
            "worker:other-tenant",
            limit=10,
            lease_seconds=5,
        ) == ()

        timeout_manual = gateway.submit_manual_trigger(
            DataOpsManualTriggerSpec(
                **(
                    manual_values
                    | {"client_request_id": "gateway-manual-cancel-timeout-001"}
                )
            )
        )
        timeout_dispatch_claim = gateway.claim_commands(
            tenant,
            "worker:timeout-dispatch",
            actor_subject=manual_actor,
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in timeout_dispatch_claim] == [
            timeout_manual.command.command_id
        ]
        gateway.complete_command(
            tenant,
            timeout_manual.command.command_id,
            worker_id="worker:timeout-dispatch",
        )
        timeout_run = gateway.transition_run(
            tenant,
            timeout_manual.run.run_id,
            0,
            "dispatching",
            manual_actor,
            "provider accepted timeout rehearsal dispatch",
        )
        timeout_cancel = gateway.admit_dataops_cancel(
            DataOpsCancelSpec(
                **(
                    cancel_values
                    | {
                        "run_id": timeout_run.run_id,
                        "client_request_id": "gateway-cancel-timeout-001",
                        "expected_state_version": timeout_run.state_version,
                    }
                )
            )
        )
        timeout_cancel_claim = gateway.claim_commands(
            tenant,
            "worker:timeout-cancel",
            actor_subject=manual_actor,
            limit=10,
            lease_seconds=5,
        )
        assert [item.command_id for item in timeout_cancel_claim] == [
            timeout_cancel.command.command_id
        ]
        timeout_reconcile = gateway.complete_cancel_and_enqueue_reconcile(
            timeout_cancel_claim[0],
            worker_id="worker:timeout-cancel",
        )
        for attempt in range(timeout_reconcile.max_attempts):
            timeout_claim = gateway.claim_commands(
                tenant,
                f"worker:timeout-reconcile-{attempt}",
                actor_subject=manual_actor,
                limit=10,
                lease_seconds=5,
            )
            assert [item.command_id for item in timeout_claim] == [
                timeout_reconcile.command_id
            ]
            timeout_command = gateway.fail_command(
                tenant,
                timeout_reconcile.command_id,
                worker_id=f"worker:timeout-reconcile-{attempt}",
                error="provider cancellation is still READY_STOP",
                retry_delay_seconds=0,
            )
        assert timeout_command.status.value == "failed"
        assert gateway.get_run(tenant, timeout_run.run_id).status.value == "failed"
        timeout_incidents = gateway.list_incidents(
            tenant,
            status="open",
            run_id=timeout_run.run_id,
        )
        assert len(timeout_incidents) == 1
        assert timeout_incidents[0].incident_type == "cancellation_convergence_timeout"
        assert timeout_incidents[0].trigger_observation_id is None

        assert (
            gateway.claim_commands(
                tenant,
                "worker:wrong-subject",
                actor_subject="workload:other-adapter",
                limit=10,
                lease_seconds=5,
            )
            == []
        )
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
        assert (
            gateway.claim_commands(
                f"other-{tenant}",
                "worker:other",
                actor_subject=actor,
                limit=10,
                lease_seconds=5,
            )
            == []
        )

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
        completed_dispatch = gateway.get_command(tenant, dispatch_command.command_id)
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
        assert callback_result.observation_created is True
        assert callback_result.command_created is True
        assert callback_result.ignored_terminal is False
        callback_replay = gateway.record_attempt_and_enqueue_reconcile(
            callback,
            actor_subject=actor,
        )
        assert callback_replay.observation_created is False
        assert callback_replay.command_created is False
        assert callback_replay.command == callback_result.command
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
        assert callback_after_delivery.command_created is False
        assert callback_after_delivery.command.status.value == "done"

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
            observation_sha256=canonical_json_fingerprint(success_observation_evidence),
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
                    rule_version_ref=(f"gda://{tenant}/quality-rule/dltb-v1"),
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
            gateway.get_quality_result(tenant, passed_quality.quality_result_id) == passed_quality
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

        claimed_changes = gateway.claim_metadata_changes(
            tenant,
            "worker:metadata-fabric-test",
            limit=10,
            lease_seconds=30,
        )
        assert len(claimed_changes) == 1
        projection = claimed_changes[0]
        assert projection.lineage_event == lineage
        assert projection.source_binding == source_openmetadata
        assert projection.target_binding == target_openmetadata
        retrying_change = gateway.fail_metadata_change(
            tenant,
            projection.change.change_id,
            worker_id="worker:metadata-fabric-test",
            error="OpenMetadata unavailable",
            retry_delay_seconds=0,
        )
        assert retrying_change.status.value == "pending"
        replayed_changes = gateway.claim_metadata_changes(
            tenant,
            "worker:metadata-fabric-test",
            limit=10,
            lease_seconds=30,
        )
        assert len(replayed_changes) == 1
        assert replayed_changes[0].change.attempt_count == 2
        completed_change = gateway.complete_metadata_change(
            tenant,
            replayed_changes[0].change.change_id,
            worker_id="worker:metadata-fabric-test",
        )
        assert completed_change.status.value == "done"

        downstream = gateway.query_lineage(
            tenant,
            source_version_id,
            direction="downstream",
            max_depth=3,
            require_complete=True,
        )
        assert downstream.complete is True
        assert downstream.edge_count == 1
        assert downstream.edges[0].event == lineage
        assert downstream.edges[0].depth == 1
        assert {node.resource_version.resource_version_id for node in downstream.nodes} == {
            source_version_id,
            target_version_id,
        }

        upstream = gateway.query_lineage(
            tenant,
            target_version_id,
            direction="upstream",
            max_depth=3,
            require_complete=True,
        )
        assert upstream.edge_count == 1
        assert upstream.edges[0].traversal_from_resource_version_id == target_version_id
        assert upstream.edges[0].traversal_to_resource_version_id == source_version_id

        bidirectional = gateway.query_lineage(
            tenant,
            source_version_id,
            direction="both",
            max_depth=3,
            require_complete=True,
        )
        assert bidirectional.complete is True
        assert bidirectional.edge_count == 1
        assert bidirectional.edges[0].event == lineage

        latest_quality_time = now + timedelta(minutes=1)
        latest_quality_id = uuid4()
        latest_quality = QualityResult(
            tenant_id=tenant,
            quality_result_id=latest_quality_id,
            run_id=run_id,
            resource_version_id=target_version_id,
            rule_version_ref=f"gda://{tenant}/quality-rule/dltb-v1",
            verdict="passed",
            metrics=quality_metrics,
            evidence_artifact_id=quality_evidence.artifact_id,
            result_sha256=quality_result_fingerprint(
                tenant_id=tenant,
                run_id=run_id,
                resource_version_id=target_version_id,
                rule_version_ref=f"gda://{tenant}/quality-rule/dltb-v1",
                verdict="passed",
                metrics=quality_metrics,
                evidence_artifact_id=quality_evidence.artifact_id,
                evaluated_by=quality_evaluator,
                evaluated_at=latest_quality_time,
            ),
            evaluated_by=quality_evaluator,
            evaluated_at=latest_quality_time,
        )
        assert gateway.record_quality_result(latest_quality).created is True

        product_urn = f"gda://{tenant}/data_product/published-parcels"
        data_product_version_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product (
                        tenant_id, product_urn, product_slug, title, description,
                        domain, owner_ref, governance_ref, current_version_id,
                        created_at, updated_at
                    ) VALUES (
                        :tenant_id, :product_urn, 'published-parcels',
                        'Published parcels', 'Governed parcel product',
                        'planning', 'team:data-platform',
                        CAST(:governance_ref AS jsonb), NULL, :created_at, :created_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "product_urn": product_urn,
                    "governance_ref": json.dumps(
                        {
                            "classification": "internal",
                            "visibility": "private",
                            "license_id": "internal",
                            "attribution": "gateway-test",
                        }
                    ),
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_version (
                        tenant_id, data_product_version_id, product_urn,
                        version_key, predecessor_version_id,
                        source_resource_version_id, output_resource_version_id,
                        standard_version_ref, mapping_contract, quality_contract,
                        quality_verdict, quality_evidence_artifact_id,
                        distribution_manifest, manifest_sha256,
                        published_by, published_at
                    ) VALUES (
                        :tenant_id, :version_id, :product_urn, 'v1.0.0', NULL,
                        :source_version_id, :target_version_id,
                        'standard:test:v1', CAST(:mapping AS jsonb),
                        CAST(:quality AS jsonb), 'passed', :quality_artifact_id,
                        CAST(:distribution AS jsonb), :manifest_sha256,
                        :published_by, :published_at
                    )
                    """
                ),
                {
                    "tenant_id": tenant,
                    "version_id": data_product_version_id,
                    "product_urn": product_urn,
                    "source_version_id": source_version_id,
                    "target_version_id": target_version_id,
                    "mapping": json.dumps({"source": "target"}),
                    "quality": json.dumps({"verdict": "passed"}),
                    "quality_artifact_id": quality_evidence.artifact_id,
                    "distribution": json.dumps({"formats": ["parquet"]}),
                    "manifest_sha256": "f" * 64,
                    "published_by": actor,
                    "published_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE gda_control.data_product
                       SET current_version_id = :version_id,
                           updated_at = :updated_at
                     WHERE tenant_id = :tenant_id
                       AND product_urn = :product_urn
                    """
                ),
                {
                    "tenant_id": tenant,
                    "product_urn": product_urn,
                    "version_id": data_product_version_id,
                    "updated_at": latest_quality_time,
                },
            )

        impact = gateway.assess_lineage_impact(
            tenant,
            source_version_id,
            change_type="crs",
            max_depth=3,
        )
        assert impact.scope == "gda_control_ledger"
        assert impact.disposition.value == "review_required"
        assert impact.impacted_data_product_count == 1
        assert impact.impacted_data_products[0].data_product_version_id == (
            data_product_version_id
        )
        assert impact.quality_signal_count == 1
        assert impact.quality_signals[0].result == latest_quality
        assert len(impact.assessment_sha256) == 64

        openlineage = OpenLineageRunEvent.model_validate(
            {
                "eventType": "COMPLETE",
                "eventTime": now.isoformat(),
                "run": {
                    "runId": str(uuid4()),
                    "facets": {
                        "gda_platform": {
                            "tenantId": tenant,
                            "platformRunId": str(run_id),
                            "definitionVersionId": str(definition_id),
                            "artifactId": str(artifact.artifact_id),
                            "operation": "derive",
                        }
                    },
                },
                "job": {
                    "namespace": "dolphinscheduler://gateway-test",
                    "name": "publish-parcels",
                },
                "inputs": [
                    {
                        "namespace": "iceberg://gateway-test",
                        "name": "source-parcels",
                        "facets": {
                            "gda_resource": {
                                "resourceVersionId": str(source_version_id)
                            }
                        },
                    }
                ],
                "outputs": [
                    {
                        "namespace": "iceberg://gateway-test",
                        "name": "published-parcels",
                        "facets": {
                            "gda_resource": {
                                "resourceVersionId": str(target_version_id)
                            }
                        },
                    },
                    {
                        "namespace": "iceberg://gateway-test",
                        "name": "published-parcels-next",
                        "facets": {
                            "gda_resource": {
                                "resourceVersionId": str(second_target_version_id)
                            }
                        },
                    },
                ],
                "producer": "https://gateway-test/openlineage",
            }
        )
        openlineage_edges = openlineage_to_lineage_events(
            openlineage,
            authenticated_producer=actor,
        )
        first_ingestion = gateway.record_lineage_batch(openlineage_edges)
        assert [result.created for result in first_ingestion] == [True, True]
        replayed_ingestion = gateway.record_lineage_batch(openlineage_edges)
        assert [result.created for result in replayed_ingestion] == [False, False]

        tentative_event_id = uuid4()
        tentative = openlineage_edges[0].model_copy(
            update={
                "lineage_event_id": tentative_event_id,
                "event_sha256": canonical_json_fingerprint(
                    {"tentative_event_id": str(tentative_event_id)}
                ),
            }
        )
        conflicting = openlineage_edges[1].model_copy(
            update={
                "facets": {"tampered": True},
                "event_sha256": canonical_json_fingerprint(
                    {"conflict": str(openlineage_edges[1].lineage_event_id)}
                ),
            }
        )
        with pytest.raises(GatewayConflictError):
            gateway.record_lineage_batch((tentative, conflicting))
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM gda_control.lineage_event
                        WHERE tenant_id = :tenant_id
                          AND lineage_event_id = :lineage_event_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "lineage_event_id": tentative_event_id,
                    },
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM gda_control.metadata_change_outbox
                        WHERE tenant_id = :tenant_id
                          AND aggregate_id = :lineage_event_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "lineage_event_id": tentative_event_id,
                    },
                ).scalar_one()
                == 0
            )

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
                success_evidence(output_artifact_id=mismatched_artifact.artifact_id),
                expected_state_version=2,
                actor_subject=actor,
                reason="mismatched output must fail",
            )
        with pytest.raises(GatewayValidationError):
            gateway.finalize_run_success(
                success_evidence(quality_result_id=failed_quality.quality_result_id),
                expected_state_version=2,
                actor_subject=actor,
                reason="failed quality must fail",
            )
        with pytest.raises(GatewayValidationError):
            gateway.finalize_run_success(
                success_evidence(quality_result_id=same_actor_quality.quality_result_id),
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

        late_callback_evidence = {
            "schema": "gda.dolphinscheduler_callback.v1",
            "callback_id": str(uuid4()),
            "provider_state": "SUCCESS",
        }
        late_callback = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=UUID(late_callback_evidence["callback_id"]),
            run_id=run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="1001",
            external_run_id="901",
            observed_state="success",
            observation_sha256=canonical_json_fingerprint(
                late_callback_evidence
            ),
            evidence=late_callback_evidence,
            observed_at=now + timedelta(minutes=5),
        )
        ignored = gateway.record_attempt_and_enqueue_reconcile(
            late_callback,
            actor_subject=actor,
        )
        assert ignored.observation_created is True
        assert ignored.command is None
        assert ignored.command_created is False
        assert ignored.ignored_terminal is True
        ignored_replay = gateway.record_attempt_and_enqueue_reconcile(
            late_callback,
            actor_subject=actor,
        )
        assert ignored_replay.observation_created is False
        assert ignored_replay.command is None
        assert (
            gateway.claim_commands(
                tenant,
                "worker:late-callback",
                actor_subject=actor,
                limit=10,
                lease_seconds=5,
            )
            == []
        )
    finally:
        engine.dispose()
