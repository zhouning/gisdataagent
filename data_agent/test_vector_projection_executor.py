import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import VECTOR_PROJECTION_REPAIR_EXECUTE
from data_agent.cross_store_projection_authority import (
    ProjectionCheckpointAuthorityConfigurationError,
)
from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.mcp_tool_registry import _mcp_execute_vector_projection_repair
from data_agent.user_context import current_tenant_id, current_user_id, current_user_role
from data_agent.vector_projection_executor import (
    VectorProjectionConfigurationError,
    VectorProjectionRepairExecutor,
    VectorProjectionRepairReceipt,
    VectorProjectionRow,
    VectorProjectionTarget,
    VectorProjectionTargetRegistry,
    VectorProjectionValidationError,
    vector_rows_fingerprint,
)
from data_agent.vector_projection_service import (
    VectorProjectionRepairRequest,
    VectorProjectionServiceConfigurationError,
    VectorProjectionServiceConflictError,
    execute_vector_projection_repair,
    load_vector_projection_registry,
)

_TARGET_REF = "vector://cq-db/public.land_semantic_vectors"
_CHECKPOINT_ACTOR = "workload:vector-projection-test"


def _target() -> VectorProjectionTarget:
    return VectorProjectionTarget(
        tenant_id="cq-vector-test",
        projection_id="cq.land_semantic_vectors",
        target_ref=_TARGET_REF,
        schema_name="public",
        table_name="land_semantic_vectors",
        embedding_dimension=3,
    )


def _rows():
    return (
        {
            "record_id": "parcel-2",
            "product_id": "cq-parcel",
            "collection": "natural-resource-ontology-2.3.0",
            "content_text": "forest parcel",
            "embedding": [0.2, 0.3, 0.4],
            "metadata": {"land_use": "forest"},
            "source_manifest": {"dataset": "chongqing-customer"},
        },
        {
            "record_id": "parcel-1",
            "product_id": "cq-parcel",
            "collection": "natural-resource-ontology-2.3.0",
            "content_text": "farmland parcel",
            "embedding": [0.1, 0.2, 0.3],
            "metadata": {"land_use": "farmland"},
            "source_manifest": {"dataset": "chongqing-customer"},
        },
    )


def _plan(source_sha256: str = "a" * 64):
    target = _target()
    rows = _rows()
    desired = ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=("gda://cq-vector-test/data_product/chongqing-parcel-v2"),
        source_content_sha256=source_sha256,
        target_engine=ProjectionEngine.VECTOR,
        target_ref=target.target_ref,
        target_exists=True,
        expected_target_content_sha256=vector_rows_fingerprint(target, rows),
        expected_row_count=len(rows),
    )
    missing = ProjectionTargetObservation(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        target_engine=ProjectionEngine.VECTOR,
        target_ref=target.target_ref,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:vector-test",
        observed_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    return target, rows, build_projection_repair_plan(desired, missing, None)


def _request(plan, rows, checkpointed_by: str = _CHECKPOINT_ACTOR):
    return VectorProjectionRepairRequest(
        plan=plan,
        rows=rows,
        checkpointed_by=checkpointed_by,
    )


def _http_request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "vector-projection-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, tenant_id: str = "cq-vector-test"):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": "platform_operator", "tenant_id": tenant_id},
    )


class _FakeVectorExecutor:
    def __init__(
        self,
        target: VectorProjectionTarget,
        observation: ProjectionTargetObservation,
    ) -> None:
        self.registry = VectorProjectionTargetRegistry((target,))
        self.observation = observation
        self.execute_calls = 0
        self.observe_calls = 0
        self.receipts = {}

    def observe(self, target: VectorProjectionTarget) -> ProjectionTargetObservation:
        self.observe_calls += 1
        assert target == self.registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        return self.observation

    def execute(self, plan, *, rows=()) -> VectorProjectionRepairReceipt:
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
            observed_by="workload:fake-vector-provider",
            observed_at=observed_at,
        )
        receipt = VectorProjectionRepairReceipt(
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
                "provider": "pgvector",
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
    registry = VectorProjectionTargetRegistry((target,))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )
    with pytest.raises(VectorProjectionValidationError, match="not explicitly registered"):
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref="vector://cq-db/public.other_table",
        )


def test_target_registration_rejects_mismatched_ref_and_system_schema():
    with pytest.raises(ValueError, match="does not match"):
        VectorProjectionTarget(
            tenant_id="cq-vector-test",
            projection_id="cq.land_semantic_vectors",
            target_ref="vector://cq-db/public.other_table",
            schema_name="public",
            table_name="land_semantic_vectors",
            embedding_dimension=3,
        )
    with pytest.raises(ValueError, match="system schemas"):
        VectorProjectionTarget(
            tenant_id="cq-vector-test",
            projection_id="cq.land_semantic_vectors",
            target_ref="vector://cq-db/pg_catalog.land_semantic_vectors",
            schema_name="pg_catalog",
            table_name="land_semantic_vectors",
            embedding_dimension=3,
        )


def test_vector_fingerprint_is_order_independent_and_dimension_bound():
    target = _target()
    rows = _rows()
    assert vector_rows_fingerprint(target, rows) == vector_rows_fingerprint(
        target, tuple(reversed(rows))
    )
    with pytest.raises(VectorProjectionValidationError, match="dimension"):
        vector_rows_fingerprint(target, [{**rows[0], "embedding": [1.0, 2.0]}])


def test_vector_row_rejects_nonfinite_values():
    with pytest.raises(ValueError, match="finite"):
        VectorProjectionRow(
            record_id="x",
            product_id="p",
            collection="c",
            content_text="x",
            embedding=(float("nan"), 1.0, 2.0),
        )


def test_executor_requires_postgresql():
    with pytest.raises(VectorProjectionConfigurationError, match="requires PostgreSQL"):
        VectorProjectionRepairExecutor(create_engine("sqlite://"), VectorProjectionTargetRegistry())


def test_executor_rejects_wrong_engine_and_unbound_target_before_database_access():
    target, rows, plan = _plan()
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    executor = VectorProjectionRepairExecutor(
        fake_engine, VectorProjectionTargetRegistry((target,))
    )
    with pytest.raises(VectorProjectionValidationError, match="not explicitly registered"):
        executor.execute(
            plan.model_copy(update={"target_ref": "vector://cq-db/public.other"}),
            rows=rows,
        )


def test_executor_checks_rebuild_rows_before_database_access():
    target, rows, plan = _plan()
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    executor = VectorProjectionRepairExecutor(
        fake_engine, VectorProjectionTargetRegistry((target,))
    )
    with pytest.raises(VectorProjectionValidationError, match="do not match desired"):
        executor.execute(
            plan,
            rows=[{**rows[0], "embedding": [0.0, 0.0, 0.0]}, rows[1]],
        )


def test_executor_rejects_fail_closed_plans():
    target, rows, plan = _plan()
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    executor = VectorProjectionRepairExecutor(
        fake_engine, VectorProjectionTargetRegistry((target,))
    )
    with pytest.raises(VectorProjectionValidationError, match="fail-closed"):
        executor.execute(plan.model_copy(update={"action": "fail_closed"}), rows=rows)


def test_vector_service_records_checkpoint_and_reobserves_replay():
    target, rows, plan = _plan()
    executor = _FakeVectorExecutor(target, plan.observation)
    authority = InMemoryProjectionCheckpointLedger()

    first = execute_vector_projection_repair(
        _request(plan, rows),
        executor=executor,
        authority=authority,
    )
    replay = execute_vector_projection_repair(
        _request(plan, rows),
        executor=executor,
        authority=authority,
    )

    assert first.status == "completed"
    assert first.checkpoint_created is True
    assert first.checkpoint.updated_by == _CHECKPOINT_ACTOR
    assert first.receipt.provider_commit_ref == first.checkpoint.target_commit_ref
    assert replay.status == "replayed"
    assert replay.checkpoint_created is False
    assert replay.checkpoint == first.checkpoint
    assert executor.execute_calls == 1
    assert executor.observe_calls == 1
    assert first.technical_baseline_status == "technical_baseline_unreviewed"
    assert first.decision_status == "assisted_precheck_not_for_production_decision"


def test_vector_service_rejects_stale_predecessor_before_provider_execution():
    target, rows, plan = _plan()
    authority = InMemoryProjectionCheckpointLedger()
    first_executor = _FakeVectorExecutor(target, plan.observation)
    execute_vector_projection_repair(
        _request(plan, rows),
        executor=first_executor,
        authority=authority,
    )
    _, stale_rows, stale_plan = _plan(source_sha256="b" * 64)
    stale_executor = _FakeVectorExecutor(target, first_executor.observation)

    with pytest.raises(VectorProjectionServiceConflictError, match="predecessor"):
        execute_vector_projection_repair(
            _request(stale_plan, stale_rows),
            executor=stale_executor,
            authority=authority,
        )

    assert stale_executor.execute_calls == 0


def test_vector_service_retry_after_authority_outage_recovers_receipt_without_provider_replay():
    target, rows, plan = _plan()
    executor = _FakeVectorExecutor(target, plan.observation)
    authority = _FailOnceRecordAuthority()

    with pytest.raises(VectorProjectionServiceConfigurationError, match="outage"):
        execute_vector_projection_repair(
            _request(plan, rows),
            executor=executor,
            authority=authority,
        )

    result = execute_vector_projection_repair(
        _request(plan, rows),
        executor=executor,
        authority=authority,
    )

    assert result.status == "completed"
    assert result.checkpoint_created is True
    assert result.checkpoint.checkpoint_version == 1
    assert executor.execute_calls == 1


def test_vector_service_registry_and_capability_contract():
    target, rows, plan = _plan()
    request = _request(plan, rows)
    registry = load_vector_projection_registry(json.dumps([target.model_dump(mode="json")]))
    assert request.plan == plan
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )

    spec = VECTOR_PROJECTION_REPAIR_EXECUTE
    assert spec.input.semantic_type == "gda.vector-projection-repair-request.v1"
    assert "checkpointed_by" in spec.input.json_schema["required"]
    assert spec.output.semantic_type == "gda.vector-projection-repair-result.v1"
    openapi = spec.openapi_projection()["paths"]["/api/platform/v1/projections/vector/repairs"][
        "post"
    ]
    mcp = spec.mcp_projection()
    assert openapi["requestBody"]["content"]["application/json"]["schema"] == (mcp["inputSchema"])


def test_vector_rest_and_mcp_bind_checkpoint_actor():
    target, rows, plan = _plan()
    spoofed = _request(plan, rows, checkpointed_by="human:spoofed")
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.execute_vector_projection_repair_plan(
                _http_request(body=spoofed.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "checkpoint_actor_mismatch"

    submission = _request(plan, rows, checkpointed_by="human:operator-1")
    result = execute_vector_projection_repair(
        submission,
        executor=_FakeVectorExecutor(target, plan.observation),
        authority=InMemoryProjectionCheckpointLedger(),
    )
    request = _http_request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "vector-projection-request-1",
            "X-GDA-Capability-Fingerprint": VECTOR_PROJECTION_REPAIR_EXECUTE.fingerprint,
            "idempotency-key": plan.plan_idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "execute_vector_projection_repair", return_value=result),
    ):
        response = asyncio.run(routes.execute_vector_projection_repair_plan(request))
    assert response.status_code == 200
    assert json.loads(response.body)["data"]["checkpoint"]["updated_by"] == ("human:operator-1")

    tenant_token = current_tenant_id.set(plan.tenant_id)
    user_token = current_user_id.set("projection-agent")
    role_token = current_user_role.set("platform_operator")
    try:
        mismatch = json.loads(
            _mcp_execute_vector_projection_repair(
                plan.model_dump(mode="json"),
                "agent:spoofed",
                list(rows),
            )
        )
        assert mismatch["code"] == "checkpoint_actor_mismatch"
        with patch(
            "data_agent.vector_projection_service.execute_vector_projection_repair",
            return_value=result,
        ):
            payload = json.loads(
                _mcp_execute_vector_projection_repair(
                    plan.model_dump(mode="json"),
                    "agent:projection-agent",
                    list(rows),
                )
            )
        assert payload["checkpoint"]["updated_by"] == "human:operator-1"
        assert payload["technical_baseline_status"] == "technical_baseline_unreviewed"
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)
