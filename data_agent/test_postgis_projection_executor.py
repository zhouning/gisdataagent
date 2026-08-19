import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import POSTGIS_PROJECTION_REPAIR_EXECUTE
from data_agent.cross_store_projection_authority import (
    ProjectionCheckpointAuthorityConfigurationError,
)
from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionCheckpointConflictError,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.mcp_tool_registry import _mcp_execute_postgis_projection_repair
from data_agent.postgis_projection_executor import (
    PostGISColumnKind,
    PostGISColumnSpec,
    PostGISProjectionConfigurationError,
    PostGISProjectionRepairExecutor,
    PostGISProjectionRepairReceipt,
    PostGISProjectionTarget,
    PostGISProjectionTargetRegistry,
    PostGISProjectionValidationError,
    projection_rows_fingerprint,
)
from data_agent.postgis_projection_service import (
    PostGISProjectionRepairRequest,
    PostGISProjectionServiceConfigurationError,
    PostGISProjectionServiceConflictError,
    PostGISProjectionServiceForbiddenError,
    execute_postgis_projection_repair,
    load_postgis_projection_registry,
)
from data_agent.user_context import current_tenant_id, current_user_id, current_user_role

_TARGET_REF = "postgis://cq-db/public.land_parcel_current"
_CHECKPOINT_ACTOR = "workload:postgis-projection-test"


def _target() -> PostGISProjectionTarget:
    return PostGISProjectionTarget(
        tenant_id="cq-postgis-test",
        projection_id="cq.land_parcel",
        target_ref=_TARGET_REF,
        schema_name="public",
        table_name="land_parcel_current",
        columns=(
            PostGISColumnSpec(name="parcel_id", kind=PostGISColumnKind.BIGINT, nullable=False),
            PostGISColumnSpec(name="land_use", kind=PostGISColumnKind.TEXT, nullable=False),
        ),
        order_by=("parcel_id",),
    )


def _plan(*, action_rows: bool = True, source_sha256: str = "a" * 64):
    target = _target()
    rows = (
        ({"parcel_id": 2, "land_use": "forest"}, {"parcel_id": 1, "land_use": "farmland"})
        if action_rows
        else ()
    )
    expected_hash = projection_rows_fingerprint(target, rows)
    desired = ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref="gda://cq-postgis-test/data_product/parcel-v2",
        source_content_sha256=source_sha256,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=target.target_ref,
        target_exists=True,
        expected_target_content_sha256=expected_hash,
        expected_row_count=len(rows),
    )
    observation = ProjectionTargetObservation(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref=target.target_ref,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:postgis-projection-observer",
        observed_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    return target, rows, build_projection_repair_plan(desired, observation, None)


def _repair_request(
    plan,
    rows,
    *,
    checkpointed_by: str = _CHECKPOINT_ACTOR,
) -> PostGISProjectionRepairRequest:
    return PostGISProjectionRepairRequest(
        plan=plan,
        rows=rows,
        checkpointed_by=checkpointed_by,
    )


def _http_request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "postgis-projection-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, tenant_id: str = "cq-postgis-test"):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": "platform_operator", "tenant_id": tenant_id},
    )


class _FakePostGISExecutor:
    def __init__(
        self,
        target: PostGISProjectionTarget,
        observation: ProjectionTargetObservation,
    ) -> None:
        self.registry = PostGISProjectionTargetRegistry((target,))
        self.observation = observation
        self.execute_calls = 0
        self.observe_calls = 0
        self.receipts = {}

    def observe(self, target: PostGISProjectionTarget) -> ProjectionTargetObservation:
        self.observe_calls += 1
        assert target == self.registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        return self.observation

    def execute(self, plan, *, rows=()) -> PostGISProjectionRepairReceipt:
        self.execute_calls += 1
        desired = plan.desired_state
        observed_at = datetime.now(UTC)
        self.observation = ProjectionTargetObservation(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_engine=plan.target_engine,
            target_ref=plan.target_ref,
            target_exists=desired.target_exists,
            observed_content_sha256=desired.expected_target_content_sha256,
            observed_row_count=desired.expected_row_count,
            observed_by="workload:fake-postgis-provider",
            observed_at=observed_at,
        )
        receipt = PostGISProjectionRepairReceipt(
            status={
                "checkpoint": "checkpointed",
                "rebuild": "completed",
                "delete": "deleted",
            }[plan.action],
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref={
                "provider": "postgis",
                "provider_commit": f"test:{plan.next_checkpoint_version}",
                "plan_sha256": plan.plan_sha256,
                "idempotency_key": plan.plan_idempotency_key,
            },
            target_exists=desired.target_exists,
            target_content_sha256=desired.expected_target_content_sha256,
            target_row_count=desired.expected_row_count,
            observed_at=observed_at,
        )
        self.receipts[plan.plan_sha256] = receipt
        return receipt

    def recover_receipt(self, plan):
        return self.receipts.get(plan.plan_sha256)


class _ConcurrentRecordAuthority:
    def __init__(self) -> None:
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.record_calls = 0

    def current(self, **identity):
        return self.ledger.current(**identity)

    def history(self, **identity):
        return self.ledger.history(**identity)

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        self.record_calls += 1
        self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )
        raise ProjectionCheckpointConflictError("simulated concurrent checkpoint commit")


class _FailOnceRecordAuthority:
    def __init__(self) -> None:
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.failed = False

    def current(self, **identity):
        return self.ledger.current(**identity)

    def history(self, **identity):
        return self.ledger.history(**identity)

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        if not self.failed:
            self.failed = True
            raise ProjectionCheckpointAuthorityConfigurationError(
                "simulated checkpoint authority outage"
            )
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )


def test_target_registration_is_explicit_and_canonical():
    target = _target()
    registry = PostGISProjectionTargetRegistry((target,))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )

    with pytest.raises(PostGISProjectionValidationError, match="not explicitly registered"):
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref="postgis://cq-db/public.other_table",
        )


def test_target_registration_rejects_system_schema_and_mismatched_ref():
    with pytest.raises(ValueError, match="system schemas"):
        PostGISProjectionTarget(
            tenant_id="cq-postgis-test",
            projection_id="cq.land_parcel",
            target_ref="postgis://cq-db/pg_catalog.land_parcel_current",
            schema_name="pg_catalog",
            table_name="land_parcel_current",
            columns=(PostGISColumnSpec(name="id", kind=PostGISColumnKind.BIGINT),),
            order_by=("id",),
        )


def test_rows_fingerprint_is_order_independent():
    target = _target()
    first = ({"parcel_id": 1, "land_use": "farmland"}, {"parcel_id": 2, "land_use": "forest"})
    second = tuple(reversed(first))
    assert projection_rows_fingerprint(target, first) == projection_rows_fingerprint(target, second)


def test_executor_requires_postgresql_and_rejects_unbound_plan():
    with pytest.raises(PostGISProjectionConfigurationError, match="requires PostgreSQL"):
        PostGISProjectionRepairExecutor(
            create_engine("sqlite://"), PostGISProjectionTargetRegistry()
        )

    target, rows, plan = _plan()
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    executor = PostGISProjectionRepairExecutor(
        fake_engine, PostGISProjectionTargetRegistry((target,))
    )
    with pytest.raises(PostGISProjectionValidationError, match="not explicitly registered"):
        executor.execute(
            plan.model_copy(update={"target_ref": "postgis://cq-db/public.other"}), rows=rows
        )


def test_executor_checks_rebuild_rows_before_database_access():
    target, rows, plan = _plan()
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    executor = PostGISProjectionRepairExecutor(
        fake_engine, PostGISProjectionTargetRegistry((target,))
    )
    with pytest.raises(PostGISProjectionValidationError, match="do not match desired"):
        executor.execute(plan, rows=({"parcel_id": 1, "land_use": "tampered"},))


def test_service_contract_excludes_target_registration_and_loads_explicit_registry():
    target, rows, plan = _plan()
    request = _repair_request(plan, rows)
    assert request.plan == plan
    registry = load_postgis_projection_registry(json.dumps([target.model_dump(mode="json")]))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )
    with pytest.raises(PostGISProjectionServiceConfigurationError, match="not configured"):
        load_postgis_projection_registry("")


def test_service_records_provider_receipt_in_checkpoint_authority():
    target, rows, plan = _plan()
    executor = _FakePostGISExecutor(target, plan.observation)
    authority = InMemoryProjectionCheckpointLedger()

    result = execute_postgis_projection_repair(
        _repair_request(plan, rows),
        executor=executor,
        authority=authority,
    )

    assert result.status == "completed"
    assert result.checkpoint_created is True
    assert result.receipt.provider_commit_ref == result.checkpoint.target_commit_ref
    assert result.checkpoint.updated_by == _CHECKPOINT_ACTOR
    assert result.checkpoint.checkpoint_version == 1
    assert result.technical_baseline_status == "technical_baseline_unreviewed"
    assert result.decision_status == "assisted_precheck_not_for_production_decision"
    assert (
        authority.current(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_engine=plan.target_engine,
            target_ref=plan.target_ref,
        )
        == result.checkpoint
    )
    assert executor.execute_calls == 1


def test_service_rejects_stale_predecessor_before_provider_execution():
    target, rows, first_plan = _plan()
    authority = InMemoryProjectionCheckpointLedger()
    first_executor = _FakePostGISExecutor(target, first_plan.observation)
    execute_postgis_projection_repair(
        _repair_request(first_plan, rows),
        executor=first_executor,
        authority=authority,
    )
    _, stale_rows, stale_plan = _plan(source_sha256="b" * 64)
    stale_executor = _FakePostGISExecutor(target, first_executor.observation)

    with pytest.raises(PostGISProjectionServiceConflictError, match="predecessor"):
        execute_postgis_projection_repair(
            _repair_request(stale_plan, stale_rows),
            executor=stale_executor,
            authority=authority,
        )

    assert stale_executor.execute_calls == 0


def test_service_replay_reobserves_target_without_reexecuting_provider():
    target, rows, plan = _plan()
    executor = _FakePostGISExecutor(target, plan.observation)
    authority = InMemoryProjectionCheckpointLedger()
    first = execute_postgis_projection_repair(
        _repair_request(plan, rows),
        executor=executor,
        authority=authority,
    )

    replay = execute_postgis_projection_repair(
        _repair_request(plan, rows),
        executor=executor,
        authority=authority,
    )

    assert replay.status == "replayed"
    assert replay.checkpoint_created is False
    assert replay.checkpoint == first.checkpoint
    assert replay.receipt.status == "replayed"
    assert executor.execute_calls == 1
    assert executor.observe_calls == 1


def test_service_replay_rejects_postgis_target_drift():
    target, rows, plan = _plan()
    executor = _FakePostGISExecutor(target, plan.observation)
    authority = InMemoryProjectionCheckpointLedger()
    execute_postgis_projection_repair(
        _repair_request(plan, rows),
        executor=executor,
        authority=authority,
    )
    executor.observation = plan.observation

    with pytest.raises(PostGISProjectionServiceConflictError, match="has drifted"):
        execute_postgis_projection_repair(
            _repair_request(plan, rows),
            executor=executor,
            authority=authority,
        )

    assert executor.execute_calls == 1


def test_service_concurrent_checkpoint_conflict_converges_on_matching_evidence():
    target, rows, plan = _plan()
    executor = _FakePostGISExecutor(target, plan.observation)
    authority = _ConcurrentRecordAuthority()

    result = execute_postgis_projection_repair(
        _repair_request(plan, rows),
        executor=executor,
        authority=authority,
    )

    assert result.status == "replayed"
    assert result.checkpoint_created is False
    assert result.checkpoint.target_commit_ref == result.receipt.provider_commit_ref
    assert executor.execute_calls == 1
    assert executor.observe_calls == 1
    assert authority.record_calls == 1


def test_service_retry_after_authority_outage_recovers_receipt_without_provider_replay():
    target, rows, plan = _plan()
    executor = _FakePostGISExecutor(target, plan.observation)
    authority = _FailOnceRecordAuthority()

    with pytest.raises(PostGISProjectionServiceConfigurationError, match="outage"):
        execute_postgis_projection_repair(
            _repair_request(plan, rows),
            executor=executor,
            authority=authority,
        )

    result = execute_postgis_projection_repair(
        _repair_request(plan, rows),
        executor=executor,
        authority=authority,
    )

    assert result.status == "completed"
    assert result.checkpoint_created is True
    assert result.checkpoint.checkpoint_version == 1
    assert executor.execute_calls == 1


def test_capability_projects_one_checkpointed_result_contract():
    spec = POSTGIS_PROJECTION_REPAIR_EXECUTE

    assert spec.input.semantic_type == "gda.postgis-projection-repair-request.v1"
    assert "checkpointed_by" in spec.input.json_schema["required"]
    assert spec.output.semantic_type == "gda.postgis-projection-repair-result.v1"
    assert {
        "status",
        "receipt",
        "checkpoint",
        "checkpoint_created",
        "technical_baseline_status",
        "decision_status",
    }.issubset(spec.output.json_schema["properties"])
    openapi = spec.openapi_projection()["paths"]["/api/platform/v1/projections/postgis/repairs"][
        "post"
    ]
    mcp = spec.mcp_projection()
    assert openapi["requestBody"]["content"]["application/json"]["schema"] == (mcp["inputSchema"])
    assert (
        openapi["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["data"]
        == mcp["outputSchema"]
    )


def test_rest_route_binds_checkpoint_actor_and_returns_checkpointed_result():
    target, rows, plan = _plan()
    spoofed = _repair_request(
        plan,
        rows,
        checkpointed_by="human:spoofed",
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.execute_postgis_projection_repair_plan(
                _http_request(body=spoofed.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "checkpoint_actor_mismatch"

    submission = _repair_request(
        plan,
        rows,
        checkpointed_by="human:operator-1",
    )
    executor = _FakePostGISExecutor(target, plan.observation)
    result = execute_postgis_projection_repair(
        submission,
        executor=executor,
        authority=InMemoryProjectionCheckpointLedger(),
    )
    request = _http_request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "postgis-projection-request-1",
            "X-GDA-Capability-Fingerprint": (POSTGIS_PROJECTION_REPAIR_EXECUTE.fingerprint),
            "idempotency-key": plan.plan_idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "execute_postgis_projection_repair", return_value=result),
    ):
        response = asyncio.run(routes.execute_postgis_projection_repair_plan(request))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["data"]["checkpoint"]["updated_by"] == "human:operator-1"
    assert (
        POSTGIS_PROJECTION_REPAIR_EXECUTE.validate_output(payload["data"])["checkpoint_created"]
        is True
    )

    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "execute_postgis_projection_repair",
            side_effect=PostGISProjectionServiceForbiddenError("authority denied"),
        ),
    ):
        response = asyncio.run(routes.execute_postgis_projection_repair_plan(request))
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == (
        "postgis_projection_repair_forbidden"
    )


def test_mcp_binds_checkpoint_actor_and_executes_canonical_service():
    target, rows, plan = _plan()
    submission = _repair_request(
        plan,
        rows,
        checkpointed_by="agent:projection-agent",
    )
    executor = _FakePostGISExecutor(target, plan.observation)
    result = execute_postgis_projection_repair(
        submission,
        executor=executor,
        authority=InMemoryProjectionCheckpointLedger(),
    )
    tenant_token = current_tenant_id.set(plan.tenant_id)
    user_token = current_user_id.set("projection-agent")
    role_token = current_user_role.set("platform_operator")
    try:
        mismatch = json.loads(
            _mcp_execute_postgis_projection_repair(
                plan.model_dump(mode="json"),
                "agent:spoofed",
                list(rows),
            )
        )
        assert mismatch["code"] == "checkpoint_actor_mismatch"

        with patch(
            "data_agent.postgis_projection_service.execute_postgis_projection_repair",
            return_value=result,
        ):
            payload = json.loads(
                _mcp_execute_postgis_projection_repair(
                    plan.model_dump(mode="json"),
                    "agent:projection-agent",
                    list(rows),
                )
            )
        assert payload["checkpoint"]["updated_by"] == "agent:projection-agent"
        assert payload["technical_baseline_status"] == "technical_baseline_unreviewed"
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)
