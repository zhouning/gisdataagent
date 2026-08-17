import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from data_agent.platform_contracts import (
    FrameworkAttemptObservation,
    QualityResult,
    RunSuccessEvidence,
    canonical_json_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import GatewayValidationError, PlatformGateway
from data_agent.public_dataops_run import (
    PublicDataOpsRequest,
    materialize_public_dataops,
    register_public_dataops,
)
from data_agent.public_source_landing import (
    PublicSourceLandingRequest,
    stage_public_source,
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
        "099_synchronous_success_profile.sql",
    )
)
NOW = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)
FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "Example"},
            "geometry": {"type": "Point", "coordinates": [106.55, 29.56]},
        }
    ],
}
FINALIZE_REASON = "public lightweight GeoJSON materialization passed content and quality gates"


@pytest.fixture(scope="module")
def postgres_engine():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL is not configured")
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            pytest.skip("public DataOps gateway test requires a PostgreSQL superuser")
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
    try:
        yield engine
    finally:
        engine.dispose()


def _bundle(tmp_path: Path, *, tenant: str, suffix: str):
    payload = json.dumps(FEATURE_COLLECTION, sort_keys=True).encode() + b"\n"
    source = tmp_path / f"source-{suffix}.geojson"
    source.write_bytes(payload)
    landing = stage_public_source(
        PublicSourceLandingRequest(
            tenant_id=tenant,
            dataset_id=f"source-{suffix}",
            source_uri=f"https://example.org/open/source-{suffix}.geojson",
            license_id="CC0-1.0",
            owner_ref="team:data-platform",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            media_type="application/geo+json",
            created_by="workload:public-source-ingest",
            created_at=NOW,
        ),
        source_path=source,
        landing_root=tmp_path / "landing",
    )
    request = PublicDataOpsRequest(
        executor="workload:public-dataops",
        quality_evaluator="workload:public-quality",
        output_dataset_id=f"serving-{suffix}",
        executed_at=NOW,
    )
    return (
        landing,
        request,
        materialize_public_dataops(landing, request, serving_root=tmp_path / "serving"),
    )


def _actor(result) -> str:
    return (
        f"{result.run.subject_context.subject_type.value}:{result.run.subject_context.subject_id}"
    )


def _prepare_running_bundle(
    gateway: PlatformGateway,
    result,
    *,
    attempt=None,
    quality_artifact=None,
    quality_result=None,
    lineage=None,
):
    gateway.register_landing(result.landing.registration)
    gateway.register_definition(result.definition_registration)
    gateway.register_resource(result.target_resource)
    gateway.register_resource_version(result.target_version)
    gateway.submit_run(result.run, request_dispatch=False)
    actor = _actor(result)
    gateway.transition_run(
        result.run.tenant_id,
        result.run.run_id,
        0,
        "dispatching",
        actor,
        "local lightweight profile accepted Run",
    )
    gateway.transition_run(
        result.run.tenant_id,
        result.run.run_id,
        1,
        "running",
        actor,
        "local lightweight executor started Run",
    )
    gateway.record_artifact(result.output_artifact)
    gateway.record_artifact(quality_artifact or result.quality_evidence_artifact)
    gateway.record_attempt(attempt or result.attempt_observation)
    gateway.record_quality_result(quality_result or result.quality_result)
    gateway.record_lineage(lineage or result.lineage_event)


def test_postgres_public_dataops_succeeds_once_and_replays(tmp_path, postgres_engine):
    tenant = f"public-run-{uuid4().hex[:12]}"
    landing, request, result = _bundle(tmp_path, tenant=tenant, suffix="countries")
    gateway = PlatformGateway(postgres_engine)

    completed = register_public_dataops(result, gateway)
    assert completed.final_run is not None
    assert completed.final_run.status.value == "succeeded"
    assert completed.final_run.state_version == 3
    assert completed.ledger_completed is True

    replay_bundle = materialize_public_dataops(landing, request, serving_root=tmp_path / "serving")
    assert replay_bundle.output_created is False
    assert replay_bundle.quality_created is False
    replay = register_public_dataops(replay_bundle, gateway)
    assert replay.final_run == completed.final_run

    with postgres_engine.connect() as connection:
        counts = connection.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM gda_control.platform_run
                   WHERE tenant_id = :tenant_id),
                  (SELECT count(*) FROM gda_control.platform_run_event
                   WHERE tenant_id = :tenant_id),
                  (SELECT count(*) FROM gda_control.artifact
                   WHERE tenant_id = :tenant_id AND run_id = :run_id),
                  (SELECT count(*) FROM gda_control.framework_attempt_observation
                   WHERE tenant_id = :tenant_id AND run_id = :run_id),
                  (SELECT count(*) FROM gda_control.quality_result
                   WHERE tenant_id = :tenant_id AND run_id = :run_id),
                  (SELECT count(*) FROM gda_control.lineage_event
                   WHERE tenant_id = :tenant_id AND run_id = :run_id)
                """
            ),
            {"tenant_id": tenant, "run_id": result.run.run_id},
        ).one()
        privilege = connection.execute(
            text(
                """
                SELECT has_function_privilege(
                    'gda_control_gateway',
                    'gda_control.finalize_synchronous_platform_run_success(text,uuid,integer,text,text,jsonb)',
                    'EXECUTE'
                )
                """
            )
        ).scalar_one()
    assert counts == (1, 4, 2, 1, 1, 1)
    assert privilege is True


def _attempt_with(result, **updates) -> FrameworkAttemptObservation:
    values = result.attempt_observation.model_dump(mode="python")
    evidence = updates.pop("evidence", values["evidence"])
    values.update(updates)
    values["evidence"] = evidence
    values["observation_sha256"] = canonical_json_fingerprint(evidence)
    return FrameworkAttemptObservation.model_validate(values)


def _success_with_output(result, artifact_id) -> RunSuccessEvidence:
    values = result.success_evidence.model_dump(mode="python")
    values["output_artifact_id"] = artifact_id
    values["evidence_sha256"] = run_success_evidence_fingerprint(
        tenant_id=values["tenant_id"],
        run_id=values["run_id"],
        attempt_observation_id=values["attempt_observation_id"],
        output_artifact_id=values["output_artifact_id"],
        quality_result_id=values["quality_result_id"],
        lineage_event_id=values["lineage_event_id"],
    )
    return RunSuccessEvidence.model_validate(values)


@pytest.mark.parametrize(
    "rejection",
    [
        "dolphinscheduler_observation",
        "wrong_observation_schema",
        "wrong_execution_mode",
        "same_quality_evaluator",
        "unbound_output",
        "unbound_lineage",
    ],
)
def test_postgres_synchronous_finalizer_rejects_unbound_or_wrong_profile_evidence(
    tmp_path, postgres_engine, rejection
):
    tenant = f"sync-reject-{uuid4().hex[:12]}"
    _, _, result = _bundle(tmp_path, tenant=tenant, suffix=rejection[:24])
    gateway = PlatformGateway(postgres_engine)
    attempt = result.attempt_observation
    quality_artifact = result.quality_evidence_artifact
    quality_result = result.quality_result
    lineage = result.lineage_event
    success = result.success_evidence

    if rejection == "dolphinscheduler_observation":
        attempt = _attempt_with(result, framework_kind="dolphinscheduler")
    elif rejection == "wrong_observation_schema":
        attempt = _attempt_with(
            result,
            evidence={**attempt.evidence, "schema": "gda.wrong.v1"},
        )
    elif rejection == "wrong_execution_mode":
        attempt = _attempt_with(
            result,
            evidence={**attempt.evidence, "execution_mode": "remote"},
        )
    elif rejection == "same_quality_evaluator":
        evaluator = _actor(result)
        quality_artifact = quality_artifact.model_copy(update={"created_by": evaluator})
        values = quality_result.model_dump(mode="python")
        values["evaluated_by"] = evaluator
        values["result_sha256"] = quality_result_fingerprint(
            tenant_id=values["tenant_id"],
            run_id=values["run_id"],
            resource_version_id=values["resource_version_id"],
            rule_version_ref=values["rule_version_ref"],
            verdict=values["verdict"],
            metrics=values["metrics"],
            evidence_artifact_id=values["evidence_artifact_id"],
            evaluated_by=evaluator,
            evaluated_at=values["evaluated_at"],
        )
        quality_result = QualityResult.model_validate(values)
    elif rejection == "unbound_output":
        success = _success_with_output(result, result.quality_evidence_artifact.artifact_id)
    else:
        lineage = lineage.model_copy(
            update={"artifact_id": result.quality_evidence_artifact.artifact_id}
        )

    _prepare_running_bundle(
        gateway,
        result,
        attempt=attempt,
        quality_artifact=quality_artifact,
        quality_result=quality_result,
        lineage=lineage,
    )
    with pytest.raises(GatewayValidationError, match="platform contract was rejected"):
        gateway.finalize_run_success(
            success,
            expected_state_version=2,
            actor_subject=_actor(result),
            reason=FINALIZE_REASON,
        )
