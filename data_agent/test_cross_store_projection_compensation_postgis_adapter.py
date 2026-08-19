from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import text

import data_agent.test_cross_store_projection_compensation_approval as approval_fixtures
from data_agent.cross_store_projection_compensation_postgis_adapter import (
    FederatedProjectionCompensationPostGISAdapterValidationError,
    FederatedProjectionCompensationPostGISMutationRequest,
    build_federated_compensation_postgis_mutation_request,
    execute_federated_compensation_postgis_mutation,
    federated_compensation_postgis_payload_fingerprint,
)
from data_agent.cross_store_projection_compensation_proposal import (
    build_federated_projection_compensation_proposal,
)
from data_agent.cross_store_projection_compensation_provider_adapter import (
    resolve_federated_compensation_provider_adapter,
)
from data_agent.cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationInput,
    build_federated_compensation_provider_materialization_set,
)
from data_agent.cross_store_projection_compensation_provider_plan import (
    build_federated_compensation_provider_plan_set,
)
from data_agent.cross_store_projection_compensation_provider_receipt import (
    build_federated_compensation_provider_receipt_candidate,
    validate_federated_compensation_provider_receipt_candidate,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.postgis_projection_executor import (
    PostGISColumnKind,
    PostGISColumnSpec,
    PostGISProjectionRepairExecutor,
    PostGISProjectionTarget,
    PostGISProjectionTargetRegistry,
    projection_rows_fingerprint,
)
from data_agent.postgis_projection_executor_rehearsal import _TemporaryPostgres
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    NOW,
    _coordinator,
    _dependencies,
    _plans,
)

_TARGET_REF = "postgis://temporary/public.cq_federated_postgis"
_ROWS = (
    {
        "feature_id": 710001,
        "land_use": "farmland",
        "geom": "POINT(106.5 29.5)",
    },
    {
        "feature_id": 710002,
        "land_use": "forest",
        "geom": "POINT(106.6 29.6)",
    },
)


def _target() -> PostGISProjectionTarget:
    return PostGISProjectionTarget(
        tenant_id="cq-federated-recovery",
        projection_id="cq.federated.postgis",
        target_ref=_TARGET_REF,
        schema_name="public",
        table_name="cq_federated_postgis",
        columns=(
            PostGISColumnSpec(
                name="feature_id",
                kind=PostGISColumnKind.BIGINT,
                nullable=False,
            ),
            PostGISColumnSpec(
                name="land_use",
                kind=PostGISColumnKind.TEXT,
                nullable=False,
            ),
            PostGISColumnSpec(
                name="geom",
                kind=PostGISColumnKind.GEOMETRY,
                geometry_srid=4326,
            ),
        ),
        order_by=("feature_id",),
    )


def _source_plans(target: PostGISProjectionTarget):
    original = _plans()
    desired = ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=(f"gda://{target.tenant_id}/data_product/federated-source-v1"),
        source_content_sha256="4" * 64,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=target.target_ref,
        target_exists=True,
        expected_target_content_sha256=projection_rows_fingerprint(target, _ROWS),
        expected_row_count=len(_ROWS),
    )
    observation = ProjectionTargetObservation(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=target.target_ref,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:chongqing-postgis-compensation-observer",
        observed_at=NOW,
    )
    return (
        build_projection_repair_plan(desired, observation, None),
        original[1],
        original[2],
    )


def _chain(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    target = _target()
    plans = _source_plans(target)
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )
    snapshot = _coordinator(plans, providers, authorities).advance()
    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    monkeypatch.setattr(approval_fixtures, "_proposal", lambda: proposal)

    intent, _, registry, resolution_request = _inputs()
    resolution = resolve_federated_compensation_provider_adapter(
        intent,
        resolution_request,
        registry,
    )
    plan_set = build_federated_compensation_provider_plan_set(intent, resolution)
    by_sha256 = {plan.plan_sha256: plan for plan in plans}
    materialization_inputs = []
    for binding in plan_set.plan_bindings:
        plan = by_sha256[binding.source_plan_sha256]
        payload_sha256 = (
            federated_compensation_postgis_payload_fingerprint(
                target,
                plan.action,
                _ROWS,
            )
            if plan.target_engine is ProjectionEngine.POSTGIS
            else f"{binding.position + 17:064x}"
        )
        desired = plan.desired_state
        materialization_inputs.append(
            FederatedProjectionCompensationProviderMaterializationInput(
                position=binding.position,
                projection_id=plan.projection_id,
                payload_sha256=payload_sha256,
                expected_target_exists=desired.target_exists,
                expected_target_content_sha256=(desired.expected_target_content_sha256),
                expected_target_row_count=desired.expected_row_count,
            )
        )
    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        tuple(materialization_inputs),
        materialized_by="workload:chongqing-compensation-materializer",
    )
    source_plan = plans[0]
    binding = next(
        item for item in materialization.bindings if item.target_engine is ProjectionEngine.POSTGIS
    )
    request = build_federated_compensation_postgis_mutation_request(
        intent,
        plan_set,
        materialization,
        source_plan,
        target,
        _ROWS,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )
    return SimpleNamespace(
        intent=intent,
        plan_set=plan_set,
        materialization=materialization,
        binding=binding,
        source_plan=source_plan,
        non_postgis_plan=plans[1],
        target=target,
        request=request,
    )


def test_request_is_deterministic_and_excludes_private_execution_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)

    replay = build_federated_compensation_postgis_mutation_request(
        chain.intent,
        chain.plan_set,
        chain.materialization,
        chain.source_plan,
        chain.target,
        _ROWS,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )

    assert replay == chain.request
    assert replay.request_sha256 == chain.request.request_sha256
    document = json.dumps(chain.request.model_dump(mode="json"), sort_keys=True)
    assert "credentials" not in document
    assert "endpoint" not in document
    assert "sql" not in document
    with pytest.raises(ValidationError):
        FederatedProjectionCompensationPostGISMutationRequest(
            **chain.request.model_dump(mode="python"),
            sql="DELETE FROM public.cq_federated_postgis",
            credentials="secret",
            endpoint="postgresql://unregistered",
        )


def test_payload_drift_is_rejected_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    drifted_rows = (
        {
            "feature_id": 710001,
            "land_use": "construction",
            "geom": "POINT(106.5 29.5)",
        },
        _ROWS[1],
    )

    with pytest.raises(
        FederatedProjectionCompensationPostGISAdapterValidationError,
        match="payload differs",
    ):
        build_federated_compensation_postgis_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            chain.source_plan,
            chain.target,
            drifted_rows,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    engine = MagicMock()
    engine.dialect.name = "postgresql"
    executor = PostGISProjectionRepairExecutor(
        engine,
        PostGISProjectionTargetRegistry((chain.target,)),
    )
    tampered = chain.request.model_copy(update={"rows": drifted_rows})
    with pytest.raises(
        FederatedProjectionCompensationPostGISAdapterValidationError,
        match="sealed contract",
    ):
        execute_federated_compensation_postgis_mutation(
            tampered,
            executor=executor,
        )
    engine.begin.assert_not_called()


def test_non_postgis_source_plan_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)

    with pytest.raises(
        FederatedProjectionCompensationPostGISAdapterValidationError,
        match="source plan differs",
    ):
        build_federated_compensation_postgis_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            chain.non_postgis_plan,
            chain.target,
            _ROWS,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgis_mutation_replay_and_receipt_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    temporary = _TemporaryPostgres(os.environ["DATABASE_URL"])
    try:
        temporary.create()
        assert temporary.engine is not None
        executor = PostGISProjectionRepairExecutor(
            temporary.engine,
            PostGISProjectionTargetRegistry((chain.target,)),
        )

        first = execute_federated_compensation_postgis_mutation(
            chain.request,
            executor=executor,
        )
        replay = execute_federated_compensation_postgis_mutation(
            chain.request,
            executor=executor,
        )

        assert first.provider_execution_status == "provider_mutation_committed"
        assert first.provider_mutation_performed is True
        assert replay.provider_execution_status == "provider_idempotent_replay"
        assert replay.provider_mutation_performed is False
        assert replay.receipt.model_copy(update={"status": "completed"}) == first.receipt
        assert first.provider_execution_performed_by_adapter is True
        assert first.checkpoint_authority_write_performed_by_adapter is False
        assert first.compensation_completion_recorded_by_adapter is False

        candidate = build_federated_compensation_provider_receipt_candidate(
            chain.materialization,
            chain.binding,
            first.receipt.model_dump(mode="python"),
        )
        validation = validate_federated_compensation_provider_receipt_candidate(
            chain.materialization,
            candidate,
        )
        assert validation.validation_state == "validated_not_authority_admitted"
        assert validation.provider_plan_sha256 == chain.binding.provider_plan_sha256
        assert validation.authority_write_allowed is False

        with temporary.engine.connect() as connection:
            target_count = connection.execute(
                text('SELECT count(*) FROM public."cq_federated_postgis"')
            ).scalar_one()
            receipt_count = connection.execute(
                text("SELECT count(*) FROM gda_provider.postgis_projection_repair_receipt")
            ).scalar_one()
            checkpoint_count = connection.execute(
                text("SELECT count(*) FROM gda_control.cross_store_projection_checkpoint_history")
            ).scalar_one()
        assert target_count == len(_ROWS)
        assert receipt_count == 1
        assert checkpoint_count == 0
    finally:
        temporary.drop()
