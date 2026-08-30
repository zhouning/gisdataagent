import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import LAKEHOUSE_PROJECTION_REPAIR_EXECUTE
from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    build_projection_repair_plan,
)
from data_agent.lakehouse_projection_executor import (
    LakehouseProjectionRepairExecutor,
    LakehouseProjectionTarget,
    LakehouseProjectionTargetRegistry,
    LakehouseSnapshotEvidence,
    lakehouse_projection_drop_evidence_sha256,
    lakehouse_projection_receipt_fingerprint,
    lakehouse_projection_stable_commit_ref,
    lakehouse_records_from_artifact,
)
from data_agent.lakehouse_projection_service import (
    LakehouseProjectionRepairRequest,
    LakehouseProjectionServiceConflictError,
    LakehouseProjectionServiceValidationError,
    execute_lakehouse_projection_repair,
    load_lakehouse_projection_registry,
)
from data_agent.mcp_tool_registry import _mcp_execute_lakehouse_projection_repair
from data_agent.user_context import current_tenant_id, current_user_id, current_user_role

_ROOT = Path(__file__).resolve().parent
_BUNDLE = _ROOT / "demo_data" / "natural_resource_ontology_customer_v1"
_ARTIFACT = _BUNDLE / "heping_changed_parcels.geojson"
_MANIFEST = _BUNDLE / "manifest.json"
_TENANT = "cq-lakehouse-test"
_BUNDLE_ID = "natural-resource-ontology-customer-demo-v1"
_PACKAGE_ID = "natural-resource-one-map:2.3.0:587915868b1221af"
_PACKAGE_SHA = "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"


class _MemoryIceberg:
    def __init__(self) -> None:
        self.evidence = LakehouseSnapshotEvidence(
            target_exists=False,
            row_count=0,
        )
        self.records: tuple[dict, ...] = ()
        self.snapshot_counter = 0
        self.replace_calls = 0
        self.drop_calls = 0

    def observe(self, target):
        return self.evidence

    def replace(
        self,
        target,
        records,
        *,
        plan_sha256,
        idempotency_key,
        receipt_sha256=None,
    ):
        self.replace_calls += 1
        self.snapshot_counter += 1
        self.records = tuple(records)
        commit_ref = lakehouse_projection_stable_commit_ref(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
            table_identifier=target.table_identifier,
            warehouse_uri=target.warehouse_uri,
            artifact_sha256=target.artifact_sha256,
            action="rebuild",
            plan_sha256=plan_sha256,
            idempotency_key=idempotency_key,
        )
        expected_receipt = lakehouse_projection_receipt_fingerprint(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
            action="rebuild",
            plan_sha256=plan_sha256,
            idempotency_key=idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=True,
            target_content_sha256=_content(self.records),
            target_row_count=len(self.records),
        )
        if receipt_sha256 is not None:
            assert receipt_sha256 == expected_receipt
        self.evidence = LakehouseSnapshotEvidence(
            target_exists=True,
            content_sha256=_content(self.records),
            row_count=len(self.records),
            snapshot_id=self.snapshot_counter,
            provider_receipt_schema="gda.iceberg-provider-receipt.v1",
            provider_receipt_action="rebuild",
            provider_receipt_plan_sha256=plan_sha256,
            provider_receipt_idempotency_key=idempotency_key,
            provider_receipt_sha256=expected_receipt,
        )
        return self.evidence

    def drop(
        self,
        target,
        *,
        plan_sha256,
        idempotency_key,
        receipt_sha256=None,
    ):
        self.drop_calls += 1
        deleted = self.evidence.snapshot_id
        if deleted is None:
            raise RuntimeError("cannot drop a missing table")
        drop_evidence = lakehouse_projection_drop_evidence_sha256(
            table_identifier=target.table_identifier,
            deleted_snapshot_id=deleted,
            plan_sha256=plan_sha256,
            idempotency_key=idempotency_key,
        )
        commit_ref = lakehouse_projection_stable_commit_ref(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
            table_identifier=target.table_identifier,
            warehouse_uri=target.warehouse_uri,
            artifact_sha256=target.artifact_sha256,
            action="delete",
            plan_sha256=plan_sha256,
            idempotency_key=idempotency_key,
            deleted_snapshot_id=deleted,
            drop_evidence_sha256=drop_evidence,
        )
        expected_receipt = lakehouse_projection_receipt_fingerprint(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
            action="delete",
            plan_sha256=plan_sha256,
            idempotency_key=idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=False,
            target_content_sha256=None,
            target_row_count=0,
        )
        if receipt_sha256 is not None:
            assert receipt_sha256 == expected_receipt
        self.evidence = LakehouseSnapshotEvidence(
            target_exists=False,
            row_count=0,
            deleted_snapshot_id=deleted,
            drop_evidence_sha256=drop_evidence,
            tombstone_plan_sha256=plan_sha256,
            tombstone_idempotency_key=idempotency_key,
            provider_receipt_schema="gda.iceberg-provider-receipt.v1",
            provider_receipt_action="delete",
            provider_receipt_plan_sha256=plan_sha256,
            provider_receipt_idempotency_key=idempotency_key,
            provider_receipt_sha256=expected_receipt,
        )
        return self.evidence


def _content(records):
    from data_agent.platform_contracts import canonical_json_fingerprint

    return canonical_json_fingerprint(records)


def _target() -> LakehouseProjectionTarget:
    artifact_bytes = _ARTIFACT.read_bytes()
    records, content = lakehouse_records_from_artifact(_ARTIFACT)
    return LakehouseProjectionTarget(
        tenant_id=_TENANT,
        projection_id="cq.customer.heping_changed_parcels_lakehouse",
        target_ref="iceberg://lakehouse/cq_customer/heping_changed_parcels",
        catalog="lakehouse",
        namespace="cq_customer",
        table="heping_changed_parcels",
        warehouse_uri="s3://cq-lakehouse-test/warehouse",
        endpoint_url="http://minio.test:9000",
        region_name="us-east-1",
        bucket="cq-lakehouse-test",
        bundle_manifest_path=str(_MANIFEST),
        bundle_manifest_sha256=hashlib.sha256(_MANIFEST.read_bytes()).hexdigest(),
        bundle_id=_BUNDLE_ID,
        bundle_version="1.0.0",
        artifact_path=str(_ARTIFACT),
        artifact_name=_ARTIFACT.name,
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        artifact_size_bytes=len(artifact_bytes),
        expected_table_content_sha256=content,
        expected_row_count=len(records),
        ontology_package_id=_PACKAGE_ID,
        ontology_package_content_sha256=_PACKAGE_SHA,
    )


def _desired(target, *, source_sha=None, version="1.0.0", exists=True):
    return ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=f"gda://{target.tenant_id}/customer-bundle/{version}",
        source_content_sha256=source_sha or target.artifact_sha256,
        target_engine=ProjectionEngine.LAKEHOUSE,
        target_ref=target.target_ref,
        target_exists=exists,
        expected_target_content_sha256=(target.expected_table_content_sha256 if exists else None),
        expected_row_count=target.expected_row_count if exists else 0,
    )


def _http_request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "lakehouse-projection-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, tenant_id: str = _TENANT):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": "platform_operator", "tenant_id": tenant_id},
    )


def test_lakehouse_records_preserve_duplicate_parcel_features():
    records, content = lakehouse_records_from_artifact(_ARTIFACT)
    assert len(records) == 445
    assert len({row["feature_id"] for row in records}) == 445
    assert len({row["parcel_id"] for row in records}) == 439
    assert len(content) == 64


def test_lakehouse_executor_rebuild_replay_snapshot_drift_checkpoint_and_delete():
    target = _target()
    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(
        LakehouseProjectionTargetRegistry((target,)), provider=provider
    )
    authority = InMemoryProjectionCheckpointLedger()
    initial = executor.observe(target)
    rebuild = build_projection_repair_plan(_desired(target), initial, None)
    first = execute_lakehouse_projection_repair(
        LakehouseProjectionRepairRequest(plan=rebuild, checkpointed_by="workload:lakehouse-test"),
        executor=executor,
        authority=authority,
    )
    replay = execute_lakehouse_projection_repair(
        LakehouseProjectionRepairRequest(plan=rebuild, checkpointed_by="workload:lakehouse-test"),
        executor=executor,
        authority=authority,
    )
    assert first.status == "completed"
    assert first.receipt.snapshot_id == 1
    assert replay.status == "replayed"
    assert replay.checkpoint == first.checkpoint

    records, _ = lakehouse_records_from_artifact(_ARTIFACT)
    provider.replace(target, records, plan_sha256="a" * 64, idempotency_key="b" * 64)
    with pytest.raises(LakehouseProjectionServiceConflictError, match="drifted"):
        execute_lakehouse_projection_repair(
            LakehouseProjectionRepairRequest(
                plan=rebuild, checkpointed_by="workload:lakehouse-test"
            ),
            executor=executor,
            authority=authority,
        )

    advanced = build_projection_repair_plan(
        _desired(target, source_sha="c" * 64, version="checkpoint-2"),
        executor.observe(target),
        first.checkpoint,
    )
    checkpoint = execute_lakehouse_projection_repair(
        LakehouseProjectionRepairRequest(plan=advanced, checkpointed_by="workload:lakehouse-test"),
        executor=executor,
        authority=authority,
    )
    assert checkpoint.receipt.status == "checkpointed"
    assert checkpoint.receipt.snapshot_id == 2

    stale = build_projection_repair_plan(
        _desired(target, source_sha="d" * 64, version="stale"),
        initial,
        None,
    )
    with pytest.raises(LakehouseProjectionServiceConflictError, match="predecessor"):
        execute_lakehouse_projection_repair(
            LakehouseProjectionRepairRequest(plan=stale, checkpointed_by="workload:lakehouse-test"),
            executor=executor,
            authority=authority,
        )

    deleted = build_projection_repair_plan(
        _desired(target, source_sha="e" * 64, version="deleted", exists=False),
        executor.observe(target),
        checkpoint.checkpoint,
    )
    deletion = execute_lakehouse_projection_repair(
        LakehouseProjectionRepairRequest(plan=deleted, checkpointed_by="workload:lakehouse-test"),
        executor=executor,
        authority=authority,
    )
    assert deletion.receipt.status == "deleted"
    assert deletion.receipt.deleted_snapshot_id == 2
    assert deletion.checkpoint.checkpoint_version == 3
    assert (
        execute_lakehouse_projection_repair(
            LakehouseProjectionRepairRequest(
                plan=deleted, checkpointed_by="workload:lakehouse-test"
            ),
            executor=executor,
            authority=authority,
        ).status
        == "replayed"
    )


def test_lakehouse_request_and_registry_contracts_are_server_bound():
    target = _target()
    registry = load_lakehouse_projection_registry(json.dumps([target.model_dump(mode="json")]))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )
    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(registry, provider=provider)
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    request = LakehouseProjectionRepairRequest(
        plan=plan,
        checkpointed_by="agent:lakehouse-test",
    )
    for forbidden in ("endpoint_url", "catalog", "namespace", "table", "warehouse_uri", "records"):
        with pytest.raises(ValidationError):
            LakehouseProjectionRepairRequest.model_validate(
                {**request.model_dump(mode="json"), forbidden: "attacker-controlled"}
            )
    spec = LAKEHOUSE_PROJECTION_REPAIR_EXECUTE
    assert spec.input.semantic_type == "gda.lakehouse-projection-repair-request.v1"
    assert set(spec.input.json_schema["required"]) == {"checkpointed_by", "plan"}
    assert spec.output.semantic_type == "gda.lakehouse-projection-repair-result.v1"
    openapi = spec.openapi_projection()["paths"]["/api/platform/v1/projections/lakehouse/repairs"][
        "post"
    ]
    assert (
        openapi["requestBody"]["content"]["application/json"]["schema"]
        == (spec.mcp_projection()["inputSchema"])
    )
    schema_text = json.dumps(spec.input.json_schema, sort_keys=True)
    for forbidden in (
        "endpoint_url",
        "warehouse_uri",
        "access_key_id",
        "secret_access_key",
        "artifact_path",
        "records",
    ):
        assert forbidden not in schema_text


def test_lakehouse_delete_recovers_when_provider_commits_before_authority():
    target = _target()
    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(
        LakehouseProjectionTargetRegistry((target,)), provider=provider
    )
    authority = InMemoryProjectionCheckpointLedger()
    rebuild = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    first = execute_lakehouse_projection_repair(
        LakehouseProjectionRepairRequest(
            plan=rebuild,
            checkpointed_by="workload:lakehouse-test",
        ),
        executor=executor,
        authority=authority,
    )
    delete_plan = build_projection_repair_plan(
        _desired(target, source_sha="e" * 64, version="deleted", exists=False),
        executor.observe(target),
        first.checkpoint,
    )
    committed = provider.drop(
        target,
        plan_sha256=delete_plan.plan_sha256,
        idempotency_key=delete_plan.plan_idempotency_key,
    )
    recovered = execute_lakehouse_projection_repair(
        LakehouseProjectionRepairRequest(
            plan=delete_plan,
            checkpointed_by="workload:lakehouse-test",
        ),
        executor=executor,
        authority=authority,
    )
    assert recovered.status == "completed"
    assert recovered.receipt.status == "replayed"
    assert recovered.receipt.deleted_snapshot_id == committed.deleted_snapshot_id
    assert recovered.receipt.drop_evidence_sha256 == committed.drop_evidence_sha256
    assert recovered.checkpoint_created


def test_lakehouse_rebuild_receipt_recovers_across_executor_without_provider_replay():
    target = _target()
    provider = _MemoryIceberg()
    registry = LakehouseProjectionTargetRegistry((target,))
    first_executor = LakehouseProjectionRepairExecutor(registry, provider=provider)
    plan = build_projection_repair_plan(_desired(target), first_executor.observe(target), None)

    committed = first_executor.execute(plan)
    assert committed.status == "completed"
    assert provider.replace_calls == 1

    restarted = LakehouseProjectionRepairExecutor(registry, provider=provider)
    recovered = execute_lakehouse_projection_repair(
        LakehouseProjectionRepairRequest(
            plan=plan,
            checkpointed_by="workload:lakehouse-test",
        ),
        executor=restarted,
        authority=InMemoryProjectionCheckpointLedger(),
    )
    assert recovered.status == "completed"
    assert recovered.receipt.status == "replayed"
    assert recovered.receipt.snapshot_id == committed.snapshot_id
    assert recovered.receipt.provider_commit_ref["receipt_sha256"] == (
        committed.provider_commit_ref["receipt_sha256"]
    )
    assert recovered.checkpoint_created
    assert provider.replace_calls == 1


def test_lakehouse_same_content_without_plan_receipt_fails_closed():
    target = _target()
    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(
        LakehouseProjectionTargetRegistry((target,)), provider=provider
    )
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    records, _ = lakehouse_records_from_artifact(_ARTIFACT)
    provider.replace(
        target,
        records,
        plan_sha256="a" * 64,
        idempotency_key="b" * 64,
    )
    provider.evidence = provider.evidence.model_copy(
        update={
            "provider_receipt_schema": None,
            "provider_receipt_action": None,
            "provider_receipt_plan_sha256": None,
            "provider_receipt_idempotency_key": None,
            "provider_receipt_sha256": None,
        }
    )

    with pytest.raises(
        LakehouseProjectionServiceValidationError,
        match="lacks a plan-bound",
    ):
        execute_lakehouse_projection_repair(
            LakehouseProjectionRepairRequest(
                plan=plan,
                checkpointed_by="workload:lakehouse-test",
            ),
            executor=executor,
            authority=InMemoryProjectionCheckpointLedger(),
        )
    assert provider.replace_calls == 1


def test_lakehouse_rest_and_mcp_bind_checkpoint_actor():
    target = _target()
    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(
        LakehouseProjectionTargetRegistry((target,)), provider=provider
    )
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    spoofed = LakehouseProjectionRepairRequest(
        plan=plan,
        checkpointed_by="human:spoofed",
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.execute_lakehouse_projection_repair_plan(
                _http_request(body=spoofed.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "checkpoint_actor_mismatch"

    submission = LakehouseProjectionRepairRequest(
        plan=plan,
        checkpointed_by="human:operator-1",
    )
    result = execute_lakehouse_projection_repair(
        submission,
        executor=executor,
        authority=InMemoryProjectionCheckpointLedger(),
    )
    request = _http_request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "lakehouse-projection-request-1",
            "X-GDA-Capability-Fingerprint": LAKEHOUSE_PROJECTION_REPAIR_EXECUTE.fingerprint,
            "idempotency-key": plan.plan_idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "execute_lakehouse_projection_repair", return_value=result),
    ):
        response = asyncio.run(routes.execute_lakehouse_projection_repair_plan(request))
    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["checkpoint"]["updated_by"] == "human:operator-1"
    assert payload["technical_baseline_status"] == "technical_baseline_unreviewed"
    assert payload["decision_status"] == "assisted_precheck_not_for_production_decision"

    tenant_token = current_tenant_id.set(plan.tenant_id)
    user_token = current_user_id.set("projection-agent")
    role_token = current_user_role.set("platform_operator")
    try:
        mismatch = json.loads(
            _mcp_execute_lakehouse_projection_repair(
                plan.model_dump(mode="json"),
                "agent:spoofed",
            )
        )
        assert mismatch["code"] == "checkpoint_actor_mismatch"
        with patch(
            "data_agent.lakehouse_projection_service.execute_lakehouse_projection_repair",
            return_value=result,
        ):
            payload = json.loads(
                _mcp_execute_lakehouse_projection_repair(
                    plan.model_dump(mode="json"),
                    "agent:projection-agent",
                )
            )
        assert payload["checkpoint"]["updated_by"] == "human:operator-1"
        assert payload["technical_baseline_status"] == "technical_baseline_unreviewed"
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)
