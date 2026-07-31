import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from data_agent import metadata_fabric_retained_real_feature_terminal_success as terminal
from data_agent.dolphinscheduler_adapter import DolphinSchedulerDefinitionBinding
from data_agent.platform_contracts import (
    FrameworkAttemptObservation,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayValidationError,
    PlatformGateway,
)

DATABASE_URL = os.environ.get("DATABASE_URL")


def _temporary_database_url(prefix: str) -> tuple[object, str, str]:
    admin_url = make_url(DATABASE_URL)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        if not connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one():
            admin_engine.dispose()
            pytest.skip("M3-24 PostgreSQL test requires a superuser")
        database_name = f"{prefix}_{uuid4().hex}"
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    database_url = admin_url.set(database=database_name).render_as_string(
        hide_password=False
    )
    return admin_engine, database_name, database_url


def _drop_temporary_database(admin_engine, database_name: str) -> None:
    with admin_engine.connect() as connection:
        connection.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :database_name
                  AND pid <> pg_backend_pid()
                """
            ),
            {"database_name": database_name},
        )
        connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
    admin_engine.dispose()


def _source() -> dict:
    return json.loads(terminal.DEFAULT_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _fixtures(now: datetime):
    source = _source()
    plan = terminal.m322.RealFeatureIngestionPlan.model_validate(
        source["observation"]["plan"]
    )
    request = terminal.build_execution_request(
        plan, retention_id="m3-24-postgres-retention"
    )
    definition = terminal.build_terminal_definition(
        "http://host.docker.internal:42424/execute",
        request,
        created_at=now,
    )
    binding = DolphinSchedulerDefinitionBinding(
        tenant_id=terminal.TENANT,
        definition_version_id=terminal.DEFINITION_VERSION_ID,
        project_code=2401,
        workflow_definition_code=2402,
        workflow_definition_version=1,
        compiled_sha256=definition.workflow.compiled_sha256,
    )
    authorization = terminal.build_terminal_authorization(
        source,
        definition,
        binding,
        authorized_at=now + timedelta(minutes=1),
    )
    base = terminal.m323.build_promotion(source)
    retention = terminal.build_retained_material_observation(
        tenant_id=terminal.TENANT,
        run_id=terminal.RUN_ID,
        output_resource_version_id=terminal.OUTPUT_RESOURCE_VERSION_ID,
        output_content_sha256=base.output_resource_version.content_sha256,
        storage_uri=base.output_artifact.storage_uri,
        retention_id="m3-24-postgres-retention",
        owner="team:metadata-platform",
        namespace="gda-metadata-spark-object-store",
        namespace_uid="00000000-0000-4000-8000-000000000024",
        control_database_ref="postgresql:gda-m3-24-postgres-test",
        object_inventory_sha256="1" * 64,
        metadata_body_sha256="2" * 64,
        row_set_sha256=base.output_artifact.manifest["row_set_sha256"],
        snapshot_id=base.output_artifact.manifest["snapshot_id"],
        feature_count=20,
        data_file_count=1,
        data_size_bytes=base.output_artifact.size_bytes,
        readable=True,
        source_payload_retained=False,
        materialized_at=now + timedelta(minutes=2),
        observed_at=now + timedelta(minutes=3),
        expires_at=now + timedelta(days=7),
    )
    promotion = terminal.build_terminal_promotion(source, retention)
    provider_evidence = {
        "api_profile": "3.4",
        "project_code": binding.project_code,
        "server_version": "3.4.2",
        "workflow_definition_code": binding.workflow_definition_code,
        "workflow_definition_version": binding.workflow_definition_version,
        "workflow_instance_id": 2403,
        "provider_state": "SUCCESS",
        "provider_start_time": (now + timedelta(minutes=1)).isoformat(),
        "provider_end_time": (now + timedelta(minutes=2)).isoformat(),
    }
    observation = FrameworkAttemptObservation(
        tenant_id=terminal.TENANT,
        observation_id=uuid5(terminal.RUN_ID, "m3-24-provider-success"),
        run_id=terminal.RUN_ID,
        attempt_no=1,
        framework_kind="dolphinscheduler",
        external_namespace=str(binding.project_code),
        external_run_id="2403",
        external_attempt_id=None,
        observed_state="success",
        observation_sha256=canonical_json_fingerprint(provider_evidence),
        evidence=provider_evidence,
        observed_at=now + timedelta(minutes=2),
    )
    return authorization, retention, promotion, observation


def _register_reconciling_run(gateway, authorization, observation):
    terminal.register_terminal_authorization(gateway, authorization)
    gateway.transition_run(
        terminal.TENANT,
        terminal.RUN_ID,
        0,
        "dispatching",
        terminal.RUNNER,
        "dispatching retained real-feature ingestion",
    )
    gateway.record_attempt(observation)
    return gateway.transition_run(
        terminal.TENANT,
        terminal.RUN_ID,
        1,
        "reconciling",
        terminal.RUNNER,
        "DolphinScheduler reached terminal provider state",
    )


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_retained_terminal_evidence_succeeds_and_exactly_replays():
    admin_engine, database_name, database_url = _temporary_database_url(
        "gda_retained_terminal_success"
    )
    engine = None
    try:
        now = datetime(2026, 7, 31, 4, tzinfo=UTC)
        authorization, retention, promotion, observation = _fixtures(now)
        engine = create_engine(database_url)
        terminal._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        _register_reconciling_run(gateway, authorization, observation)
        coordinator = terminal.RetainedTerminalSuccessCoordinator(
            gateway, material_probe=lambda observed: observed == retention
        )

        first_promotion, first_run = coordinator.finalize(
            promotion, retention, observation
        )
        replay_promotion, replay_run = coordinator.finalize(
            promotion, retention, observation
        )

        assert first_promotion.created is True
        assert replay_promotion.created is False
        assert first_run == replay_run
        assert first_run.status.value == "succeeded"
        assert first_run.state_version == 3
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        count(*) FILTER (WHERE artifact_role = 'execution_plan')
                            AS execution_plans,
                        count(*) FILTER (
                            WHERE media_type = 'application/vnd.gda.policy-decision+json'
                        ) AS policy_decisions,
                        count(*) FILTER (
                            WHERE media_type = 'application/vnd.gda.approval+json'
                        ) AS approvals,
                        count(*) FILTER (
                            WHERE created_by = :quality_evaluator
                              AND run_id = :run_id
                        ) AS evaluator_evidence
                    FROM gda_control.artifact
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {
                    "tenant_id": terminal.TENANT,
                    "run_id": terminal.RUN_ID,
                    "quality_evaluator": terminal.QUALITY_EVALUATOR,
                },
            ).one()
        assert tuple(row) == (1, 1, 1, 1)
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_unreadable_material_rejects_before_output_promotion():
    admin_engine, database_name, database_url = _temporary_database_url(
        "gda_unreadable_retained_material"
    )
    engine = None
    try:
        now = datetime(2026, 7, 31, 4, tzinfo=UTC)
        authorization, retention, promotion, observation = _fixtures(now)
        engine = create_engine(database_url)
        terminal._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        _register_reconciling_run(gateway, authorization, observation)
        coordinator = terminal.RetainedTerminalSuccessCoordinator(
            gateway, material_probe=lambda _observed: False
        )

        with pytest.raises(
            terminal.RetainedTerminalSuccessError,
            match="absent, expired, or unreadable",
        ):
            coordinator.finalize(promotion, retention, observation)

        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM gda_control.quality_result) AS quality,
                      (SELECT count(*) FROM gda_control.lineage_event) AS lineage,
                      (SELECT count(*) FROM gda_control.resource_version
                       WHERE resource_version_id = :output_id) AS output_versions
                    """
                ),
                {"output_id": terminal.OUTPUT_RESOURCE_VERSION_ID},
            ).one()
        assert tuple(counts) == (0, 0, 0)
        assert gateway.get_run(terminal.TENANT, terminal.RUN_ID).status.value == (
            "reconciling"
        )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_quality_creator_impersonation_and_wrong_provider_state_fail_closed():
    admin_engine, database_name, database_url = _temporary_database_url(
        "gda_retained_provenance_negative"
    )
    engine = None
    try:
        now = datetime(2026, 7, 31, 4, tzinfo=UTC)
        authorization, retention, promotion, observation = _fixtures(now)
        engine = create_engine(database_url)
        terminal._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        _register_reconciling_run(gateway, authorization, observation)
        coordinator = terminal.RetainedTerminalSuccessCoordinator(
            gateway, material_probe=lambda _observed: True
        )

        wrong_observation = observation.model_copy(update={"observed_state": "failed"})
        with pytest.raises(
            terminal.RetainedTerminalSuccessError,
            match="DolphinScheduler success",
        ):
            coordinator.finalize(promotion, retention, wrong_observation)

        values = promotion.model_dump(mode="python")
        values["quality_evidence_artifact"] = (
            promotion.quality_evidence_artifact.model_copy(
                update={"created_by": terminal.RUNNER}
            )
        )
        impersonated = terminal.m323.RunOutputLedgerPromotion.model_validate(values)
        with pytest.raises(
            terminal.RetainedTerminalSuccessError,
            match="independent evaluator",
        ):
            coordinator.finalize(impersonated, retention, observation)
        assert gateway.get_run(terminal.TENANT, terminal.RUN_ID).status.value == (
            "reconciling"
        )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_missing_policy_artifact_and_conflicting_terminal_reason_are_rejected():
    admin_engine, database_name, database_url = _temporary_database_url(
        "gda_retained_authority_negative"
    )
    engine = None
    try:
        now = datetime(2026, 7, 31, 4, tzinfo=UTC)
        authorization, retention, promotion, observation = _fixtures(now)
        engine = create_engine(database_url)
        terminal._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        gateway.register_resource(authorization.source_resource)
        gateway.register_resource_version(authorization.source_version)
        gateway.register_definition(authorization.definition_registration)
        gateway.register_resource(authorization.output_resource)
        gateway.record_artifact(authorization.execution_plan)
        gateway.record_artifact(authorization.approval)
        with pytest.raises(GatewayValidationError, match="Policy decision artifact"):
            gateway.submit_run(authorization.run)

        gateway.record_artifact(authorization.policy_decision)
        _register_reconciling_run(gateway, authorization, observation)
        coordinator = terminal.RetainedTerminalSuccessCoordinator(
            gateway, material_probe=lambda _observed: True
        )
        _promoted, succeeded = coordinator.finalize(
            promotion, retention, observation
        )
        assert succeeded.status.value == "succeeded"

        with pytest.raises(GatewayConflictError, match="platform state conflict"):
            coordinator.finalize(
                promotion,
                retention,
                observation,
                reason="conflicting terminal reason",
            )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)
