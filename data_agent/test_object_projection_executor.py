import asyncio
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import OBJECT_PROJECTION_REPAIR_EXECUTE
from data_agent.cross_store_projection_authority import (
    ProjectionCheckpointAuthorityConfigurationError,
)
from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    build_projection_repair_plan,
)
from data_agent.mcp_tool_registry import _mcp_execute_object_projection_repair
from data_agent.object_projection_executor import (
    ObjectProjectionRepairExecutor,
    ObjectProjectionTarget,
    ObjectProjectionTargetRegistry,
    ObjectProjectionValidationError,
)
from data_agent.object_projection_service import (
    ObjectProjectionRepairRequest,
    ObjectProjectionServiceConfigurationError,
    ObjectProjectionServiceConflictError,
    execute_object_projection_repair,
    load_object_projection_registry,
)
from data_agent.user_context import current_tenant_id, current_user_id, current_user_role

_TENANT = "cq-object-test"
_BUNDLE_ID = "natural-resource-ontology-customer-demo-v1"
_PACKAGE_ID = "natural-resource-one-map:2.3.0:587915868b1221af"
_PACKAGE_SHA = "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"


class _S3Error(Exception):
    def __init__(self, code: str):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _MemoryS3:
    def __init__(self) -> None:
        self.versions: dict[tuple[str, str], list[dict]] = {}
        self.counter = 0

    def get_bucket_versioning(self, *, Bucket):
        return {"Status": "Enabled"}

    def _next(self) -> str:
        self.counter += 1
        return f"version-{self.counter}"

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        payload = Body.read() if hasattr(Body, "read") else bytes(Body)
        version_id = self._next()
        etag = hashlib.md5(payload, usedforsecurity=False).hexdigest()
        entry = {
            "version_id": version_id,
            "etag": etag,
            "payload": payload,
            "content_type": ContentType,
            "metadata": dict(Metadata),
            "delete_marker": False,
        }
        self.versions.setdefault((Bucket, Key), []).append(entry)
        return {"VersionId": version_id, "ETag": f'"{etag}"'}

    def delete_object(self, *, Bucket, Key):
        version_id = self._next()
        self.versions.setdefault((Bucket, Key), []).append(
            {"version_id": version_id, "delete_marker": True}
        )
        return {"VersionId": version_id, "DeleteMarker": True}

    def get_object(self, *, Bucket, Key):
        entries = self.versions.get((Bucket, Key), [])
        if not entries or entries[-1]["delete_marker"]:
            raise _S3Error("NoSuchKey")
        entry = entries[-1]
        return {
            "Body": io.BytesIO(entry["payload"]),
            "VersionId": entry["version_id"],
            "ETag": f'"{entry["etag"]}"',
            "ContentLength": len(entry["payload"]),
            "ContentType": entry["content_type"],
            "Metadata": entry["metadata"],
        }

    def list_object_versions(self, *, Bucket, Prefix, MaxKeys):
        entries = self.versions.get((Bucket, Prefix), [])
        markers = []
        versions = []
        for index, entry in enumerate(entries):
            record = {
                "Key": Prefix,
                "VersionId": entry["version_id"],
                "IsLatest": index == len(entries) - 1,
            }
            if entry["delete_marker"]:
                markers.append(record)
            else:
                versions.append(record)
        return {"DeleteMarkers": markers, "Versions": versions}


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


def _write_bundle(root: Path) -> tuple[ObjectProjectionTarget, bytes]:
    payload = b'{"type":"FeatureCollection","features":[]}\n'
    artifact = root / "heping_changed_parcels.geojson"
    artifact.write_bytes(payload)
    artifact_sha = hashlib.sha256(payload).hexdigest()
    manifest = {
        "bundle": {
            "id": _BUNDLE_ID,
            "version": "1.0.0",
        },
        "ontology": {
            "key": "natural-resource-one-map",
            "version": "2.3.0",
            "package_id": _PACKAGE_ID,
            "sha256": _PACKAGE_SHA,
        },
        "files": [
            {
                "name": artifact.name,
                "size": len(payload),
                "sha256": artifact_sha,
            }
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    target = ObjectProjectionTarget(
        tenant_id=_TENANT,
        projection_id="cq.customer.heping_changed_parcels",
        target_ref=("s3://cq-object-test/projections/heping_changed_parcels.geojson"),
        endpoint_url="http://minio.test:9000",
        region_name="us-east-1",
        bucket="cq-object-test",
        key="projections/heping_changed_parcels.geojson",
        bundle_manifest_path=str(manifest_path),
        bundle_manifest_sha256=manifest_sha,
        bundle_id=_BUNDLE_ID,
        bundle_version="1.0.0",
        artifact_path=str(artifact),
        artifact_name=artifact.name,
        artifact_sha256=artifact_sha,
        artifact_size_bytes=len(payload),
        media_type="application/geo+json",
        ontology_package_id=_PACKAGE_ID,
        ontology_package_content_sha256=_PACKAGE_SHA,
    )
    return target, payload


def _desired(target: ObjectProjectionTarget, source_sha: str | None = None):
    return ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=(
            "gda://cq-object-test/customer-bundle/heping-changed-parcels/v1"
        ),
        source_content_sha256=source_sha or target.artifact_sha256,
        target_engine=ProjectionEngine.OBJECT_STORE,
        target_ref=target.target_ref,
        target_exists=True,
        expected_target_content_sha256=target.artifact_sha256,
        expected_row_count=1,
    )


def _request(plan, actor: str = "workload:object-projection-test"):
    return ObjectProjectionRepairRequest(plan=plan, checkpointed_by=actor)


def _http_request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "object-projection-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, tenant_id: str = _TENANT):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": "platform_operator", "tenant_id": tenant_id},
    )


def test_object_target_registry_and_customer_bundle_boundary(tmp_path):
    target, _ = _write_bundle(tmp_path)
    registry = ObjectProjectionTargetRegistry((target,))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )
    with pytest.raises(ObjectProjectionValidationError, match="not explicitly registered"):
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref="s3://cq-object-test/other.geojson",
        )
    with pytest.raises(ValueError, match="credential-free"):
        ObjectProjectionTarget.model_validate(
            {
                **target.model_dump(mode="json"),
                "endpoint_url": "http://user:secret@minio.test:9000",
            }
        )
    with pytest.raises(ValueError, match="sealed Chongqing customer bundle"):
        ObjectProjectionTarget.model_validate(
            {
                **target.model_dump(mode="json"),
                "bundle_version": "2.0.0",
            }
        )


def test_object_executor_rebuild_replay_drift_and_delete(tmp_path):
    target, payload = _write_bundle(tmp_path)
    client = _MemoryS3()
    executor = ObjectProjectionRepairExecutor(
        ObjectProjectionTargetRegistry((target,)),
        client=client,
    )
    initial = executor.observe(target)
    rebuild = build_projection_repair_plan(_desired(target), initial, None)
    first = executor.execute(rebuild)
    replay = executor.execute(rebuild)
    assert first.status == "completed"
    assert first.object_version_id == "version-1"
    assert first.target_content_sha256 == target.artifact_sha256
    assert first.target_size_bytes == len(payload)
    assert replay.status == "replayed"
    assert replay.object_version_id == "version-1"

    client.put_object(
        Bucket=target.bucket,
        Key=target.key,
        Body=b"tampered",
        ContentType=target.media_type,
        Metadata={},
    )
    with pytest.raises(ObjectProjectionValidationError, match="changed"):
        executor.execute(rebuild)
    client.put_object(
        Bucket=target.bucket,
        Key=target.key,
        Body=payload,
        ContentType=target.media_type,
        Metadata={"sha256": target.artifact_sha256},
    )

    current = executor.observe(target)
    deleted = ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref="gda://cq-object-test/customer-bundle/deleted",
        source_content_sha256="c" * 64,
        target_engine=ProjectionEngine.OBJECT_STORE,
        target_ref=target.target_ref,
        target_exists=False,
        expected_target_content_sha256=None,
        expected_row_count=0,
    )
    delete_plan = build_projection_repair_plan(deleted, current, None)
    receipt = executor.execute(delete_plan)
    assert receipt.status == "deleted"
    assert receipt.delete_marker_version_id == "version-5"
    assert receipt.provider_commit_ref["provider_atomicity"] == (
        "versioned_intent_then_delete_marker_chain"
    )
    assert receipt.provider_commit_ref["receipt_sha256"]
    assert executor.observe(target).target_exists is False


def test_object_executor_recovers_native_receipts_without_provider_replay(tmp_path):
    target, _ = _write_bundle(tmp_path)
    client = _MemoryS3()
    registry = ObjectProjectionTargetRegistry((target,))
    first_executor = ObjectProjectionRepairExecutor(registry, client=client)
    rebuild = build_projection_repair_plan(
        _desired(target),
        first_executor.observe(target),
        None,
    )
    first = first_executor.execute(rebuild)
    target_identity = (target.bucket, target.key)
    target_version_count = len(client.versions[target_identity])

    restarted = ObjectProjectionRepairExecutor(registry, client=client)
    recovered = restarted.recover_receipt(rebuild)
    replayed = restarted.execute(rebuild)
    assert recovered is not None
    assert recovered.object_version_id == first.object_version_id
    assert recovered.provider_commit_ref["receipt_sha256"] == (
        first.provider_commit_ref["receipt_sha256"]
    )
    assert replayed.status == "replayed"
    assert len(client.versions[target_identity]) == target_version_count

    deleted = ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref="gda://cq-object-test/customer-bundle/deleted-recovery",
        source_content_sha256="d" * 64,
        target_engine=ProjectionEngine.OBJECT_STORE,
        target_ref=target.target_ref,
        target_exists=False,
        expected_target_content_sha256=None,
        expected_row_count=0,
    )
    delete_plan = build_projection_repair_plan(
        deleted,
        restarted.observe(target),
        None,
    )
    deletion = restarted.execute(delete_plan)
    deleted_target_version_count = len(client.versions[target_identity])
    receipt_key = deletion.provider_commit_ref["receipt_object_key"]
    assert client.versions[(target.bucket, receipt_key)][-1]["metadata"][
        "gda-receipt-sha256"
    ] == deletion.provider_commit_ref["receipt_sha256"]

    second_restart = ObjectProjectionRepairExecutor(registry, client=client)
    recovered_delete = second_restart.recover_receipt(delete_plan)
    delete_replay = second_restart.execute(delete_plan)
    assert recovered_delete is not None
    assert recovered_delete.delete_marker_version_id == deletion.delete_marker_version_id
    assert delete_replay.status == "replayed"
    assert len(client.versions[target_identity]) == deleted_target_version_count


def test_object_service_retry_after_authority_outage_recovers_receipt_without_replay(tmp_path):
    target, _ = _write_bundle(tmp_path)
    client = _MemoryS3()
    registry = ObjectProjectionTargetRegistry((target,))
    first_executor = ObjectProjectionRepairExecutor(registry, client=client)
    authority = _FailOnceRecordAuthority()
    plan = build_projection_repair_plan(
        _desired(target),
        first_executor.observe(target),
        None,
    )
    request = _request(plan)

    with pytest.raises(ObjectProjectionServiceConfigurationError, match="outage"):
        execute_object_projection_repair(
            request,
            executor=first_executor,
            authority=authority,
        )

    second_executor = ObjectProjectionRepairExecutor(registry, client=client)
    result = execute_object_projection_repair(
        request,
        executor=second_executor,
        authority=authority,
    )
    assert result.status == "completed"
    assert result.checkpoint_created is True
    assert result.receipt.provider_commit_ref["provider_atomicity"] == (
        "target_payload_and_plan_metadata_single_put_object"
    )
    assert len(client.versions[(target.bucket, target.key)]) == 1


def test_object_service_rejects_receipt_fingerprint_tampering(tmp_path):
    target, _ = _write_bundle(tmp_path)
    client = _MemoryS3()
    registry = ObjectProjectionTargetRegistry((target,))
    executor = ObjectProjectionRepairExecutor(registry, client=client)
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    receipt = executor.execute(plan)
    tampered = receipt.model_copy(
        update={
            "provider_commit_ref": {
                **receipt.provider_commit_ref,
                "receipt_sha256": "0" * 64,
            }
        }
    )
    provider = SimpleNamespace(
        registry=registry,
        recover_receipt=lambda _plan: tampered,
    )
    with pytest.raises(ObjectProjectionServiceConflictError, match="not bound"):
        execute_object_projection_repair(
            _request(plan),
            executor=provider,
            authority=InMemoryProjectionCheckpointLedger(),
        )


def test_object_service_checkpoints_and_rejects_same_content_new_version(tmp_path):
    target, payload = _write_bundle(tmp_path)
    client = _MemoryS3()
    executor = ObjectProjectionRepairExecutor(
        ObjectProjectionTargetRegistry((target,)),
        client=client,
    )
    authority = InMemoryProjectionCheckpointLedger()
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    first = execute_object_projection_repair(
        _request(plan),
        executor=executor,
        authority=authority,
    )
    replay = execute_object_projection_repair(
        _request(plan),
        executor=executor,
        authority=authority,
    )
    assert first.status == "completed"
    assert first.checkpoint_created
    assert first.checkpoint.target_commit_ref["provider"] == "s3_object_store"
    assert replay.status == "replayed"
    assert not replay.checkpoint_created

    client.put_object(
        Bucket=target.bucket,
        Key=target.key,
        Body=payload,
        ContentType=target.media_type,
        Metadata={"sha256": target.artifact_sha256},
    )
    with pytest.raises(ObjectProjectionServiceConflictError, match="drifted"):
        execute_object_projection_repair(
            _request(plan),
            executor=executor,
            authority=authority,
        )


def test_object_request_contract_has_no_payload_target_or_credentials(tmp_path):
    target, _ = _write_bundle(tmp_path)
    executor = ObjectProjectionRepairExecutor(
        ObjectProjectionTargetRegistry((target,)),
        client=_MemoryS3(),
    )
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    request = _request(plan, "agent:object-test")
    for forbidden in (
        "payload",
        "endpoint_url",
        "bucket",
        "key",
        "access_key_id",
        "secret_access_key",
        "artifact_path",
    ):
        with pytest.raises(ValidationError):
            ObjectProjectionRepairRequest.model_validate(
                {**request.model_dump(mode="json"), forbidden: "attacker-controlled"}
            )
    registry = load_object_projection_registry(json.dumps([target.model_dump(mode="json")]))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )

    spec = OBJECT_PROJECTION_REPAIR_EXECUTE
    assert spec.input.semantic_type == "gda.object-projection-repair-request.v1"
    assert set(spec.input.json_schema["required"]) == {"checkpointed_by", "plan"}
    assert spec.output.semantic_type == "gda.object-projection-repair-result.v1"
    openapi = spec.openapi_projection()["paths"][
        "/api/platform/v1/projections/object-store/repairs"
    ]["post"]
    mcp = spec.mcp_projection()
    assert openapi["requestBody"]["content"]["application/json"]["schema"] == (mcp["inputSchema"])
    schema_text = json.dumps(spec.input.json_schema, sort_keys=True)
    for forbidden in (
        "endpoint_url",
        "access_key_id",
        "secret_access_key",
        "artifact_path",
        "payload",
    ):
        assert forbidden not in schema_text


def test_object_rest_and_mcp_bind_checkpoint_actor(tmp_path):
    target, _ = _write_bundle(tmp_path)
    client = _MemoryS3()
    executor = ObjectProjectionRepairExecutor(
        ObjectProjectionTargetRegistry((target,)),
        client=client,
    )
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    spoofed = _request(plan, "human:spoofed")
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.execute_object_projection_repair_plan(
                _http_request(body=spoofed.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "checkpoint_actor_mismatch"

    submission = _request(plan, "human:operator-1")
    result = execute_object_projection_repair(
        submission,
        executor=executor,
        authority=InMemoryProjectionCheckpointLedger(),
    )
    request = _http_request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "object-projection-request-1",
            "X-GDA-Capability-Fingerprint": OBJECT_PROJECTION_REPAIR_EXECUTE.fingerprint,
            "idempotency-key": plan.plan_idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "execute_object_projection_repair", return_value=result),
    ):
        response = asyncio.run(routes.execute_object_projection_repair_plan(request))
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
            _mcp_execute_object_projection_repair(
                plan.model_dump(mode="json"),
                "agent:spoofed",
            )
        )
        assert mismatch["code"] == "checkpoint_actor_mismatch"
        with patch(
            "data_agent.object_projection_service.execute_object_projection_repair",
            return_value=result,
        ):
            payload = json.loads(
                _mcp_execute_object_projection_repair(
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
