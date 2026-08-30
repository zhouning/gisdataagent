from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from data_agent.agentops_specialist_providers import (
    GWM_PROVIDER_REF,
    GWM_RENDER_OPERATION,
    MMFE_FUSION_OPERATION,
    MMFE_PROVIDER_REF,
    BoundSpecialistExecutor,
    FilesystemArtifactContentBackend,
    FilesystemSpecialistArtifactStore,
    InMemorySpecialistCancellationAdapter,
    InMemorySpecialistOperationAuthority,
    PostgresArtifactAuthoritySpecialistStore,
    S3ArtifactContentBackend,
    SpecialistOperationStatus,
    SpecialistProviderCancellationStatus,
    SpecialistProviderError,
    SpecialistReconciliationVerdict,
    UnsupportedSpecialistCancellationAdapter,
    build_gwm_provider_spec,
    build_mmfe_provider_spec,
    reconcile_unknown_specialist_activity,
)
from data_agent.agentops_temporal_adapter import TemporalProviderActivityResult
from data_agent.agentops_temporal_contracts import (
    TemporalActivityOutcome,
    TemporalActivityRequest,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_reconciliation import (
    TemporalHistoryReconciliationError,
    TemporalProviderActivityHistoryObservation,
    TemporalProviderActivityHistoryStatus,
    activity_evidence_from_history,
    reconcile_specialist_activity_history,
)
from data_agent.platform_contracts import Artifact, ArtifactRole
from data_agent.platform_gateway import GatewayWriteResult
from data_agent.test_agentops_temporal_adapter import _activity_request


def _request_with_spec(spec, *, input_artifact_ids: tuple[UUID, ...]) -> TemporalActivityRequest:
    _harness, _workflow_id, _call, request = _activity_request()
    values = request.model_dump(mode="python")
    values["input_artifact_ids"] = input_artifact_ids
    values["provider_spec"] = spec
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    return TemporalActivityRequest(**values)


def _write_geojson(path: Path, *, offset: float) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": 1},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[offset, 0], [offset + 1, 0], [offset + 1, 1], [offset, 1], [offset, 0]]
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_mmfe_provider_executes_real_fusion_and_replays_idempotently(tmp_path, monkeypatch):
    source_a = tmp_path / "a.geojson"
    source_b = tmp_path / "b.geojson"
    _write_geojson(source_a, offset=0)
    _write_geojson(source_b, offset=0.25)
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    artifact_a = UUID("00000000-0000-4000-8000-000000007101")
    artifact_b = UUID("00000000-0000-4000-8000-000000007102")
    store.register_input(
        tenant_id="planning",
        artifact_id=artifact_a,
        source_path=source_a,
        media_type="application/geo+json",
    )
    store.register_input(
        tenant_id="planning",
        artifact_id=artifact_b,
        source_path=source_b,
        media_type="application/geo+json",
    )
    spec = build_mmfe_provider_spec(
        input_artifact_ids=(artifact_a, artifact_b), strategy="spatial_join"
    )
    request = _request_with_spec(spec, input_artifact_ids=(artifact_a, artifact_b))
    output_path = tmp_path / "fused.geojson"
    monkeypatch.setattr(
        "data_agent.fusion.execution._generate_output_path", lambda *_args: str(output_path)
    )

    executor = BoundSpecialistExecutor(store)
    result = asyncio.run(executor(request))
    assert isinstance(result, TemporalProviderActivityResult)
    assert result.outcome is TemporalActivityOutcome.SUCCEEDED
    assert result.output_artifact_id is not None
    output = store.resolve_input("planning", result.output_artifact_id)
    assert output.storage_path.read_bytes() == output_path.read_bytes()
    assert output.manifest["provider_ref"] == MMFE_PROVIDER_REF
    assert output.manifest["operation_ref"] == MMFE_FUSION_OPERATION
    assert output.manifest["lineage"]["source_artifact_ids"] == [str(artifact_a), str(artifact_b)]
    assert output.manifest["quality"]["score"] is not None

    replay = asyncio.run(executor(request))
    assert replay == result
    output_files = [
        path
        for path in (tmp_path / "artifacts" / "outputs").iterdir()
        if ".manifest." not in path.name
    ]
    assert len(output_files) == 1


def test_gwm_provider_renders_mmfe_state_input_and_preserves_claim_boundary(tmp_path):
    state = {
        "schema": "mmfe.uwm_state_input.v1",
        "version": "0.1",
        "source_product": {"product_id": "mmfe-product-v1"},
        "urban_spatial_unit": {"unit_type": "district"},
        "object_role_registry": [],
        "state_components": {},
        "graph_summary": {},
        "production_policy": {"authoritative_data_required_for_production": True},
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    input_id = UUID("00000000-0000-4000-8000-000000007103")
    store.register_input(
        tenant_id="planning",
        artifact_id=input_id,
        source_path=state_path,
        media_type="application/json",
    )
    spec = build_gwm_provider_spec(input_artifact_ids=(input_id,), observation_id="obs-1")
    request = _request_with_spec(spec, input_artifact_ids=(input_id,))
    result = asyncio.run(BoundSpecialistExecutor(store)(request))
    assert result.outcome is TemporalActivityOutcome.SUCCEEDED
    output = store.resolve_input("planning", result.output_artifact_id)
    payload = json.loads(output.storage_path.read_text(encoding="utf-8"))
    assert payload["observation_id"] == "obs-1"
    assert payload["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert output.manifest["provider_ref"] == GWM_PROVIDER_REF
    assert output.manifest["operation_ref"] == GWM_RENDER_OPERATION


def test_filesystem_output_can_be_rehydrated_by_a_replacement_worker(tmp_path):
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    output_id = UUID("00000000-0000-4000-8000-000000007104")
    content = b'{"observation_id":"recovery"}'
    manifest = {
        "schema": "gda.specialist_provider_output_manifest.v1",
        "provider_ref": GWM_PROVIDER_REF,
        "operation_ref": GWM_RENDER_OPERATION,
        "request_sha256": "a" * 64,
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }
    store.write_output(
        tenant_id="planning",
        artifact_id=output_id,
        content=content,
        media_type="application/json",
        manifest=manifest,
    )

    replacement_store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    recovered = replacement_store.resolve_input("planning", output_id)

    assert recovered.artifact_id == output_id
    assert recovered.storage_path.read_bytes() == content
    assert recovered.content_sha256 == hashlib.sha256(content).hexdigest()
    assert recovered.manifest == manifest


def test_provider_binding_mismatch_fails_closed(tmp_path):
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    spec = build_mmfe_provider_spec()
    request = _request_with_spec(spec, input_artifact_ids=())
    result = asyncio.run(BoundSpecialistExecutor(store)(request))
    assert result.outcome is TemporalActivityOutcome.FAILED
    assert result.failure_type == "SpecialistProviderError"


def test_unknown_after_provider_commit_reconciles_from_receipt_and_artifact_without_reexecution(
    tmp_path, monkeypatch
):
    source_a = tmp_path / "a.geojson"
    source_b = tmp_path / "b.geojson"
    _write_geojson(source_a, offset=0)
    _write_geojson(source_b, offset=0.25)
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    artifact_a = UUID("00000000-0000-4000-8000-000000007131")
    artifact_b = UUID("00000000-0000-4000-8000-000000007132")
    store.register_input(
        tenant_id="planning",
        artifact_id=artifact_a,
        source_path=source_a,
        media_type="application/geo+json",
    )
    store.register_input(
        tenant_id="planning",
        artifact_id=artifact_b,
        source_path=source_b,
        media_type="application/geo+json",
    )
    spec = build_mmfe_provider_spec(
        input_artifact_ids=(artifact_a, artifact_b), strategy="spatial_join"
    )
    request = _request_with_spec(spec, input_artifact_ids=(artifact_a, artifact_b))
    output_path = tmp_path / "fused.geojson"
    monkeypatch.setattr(
        "data_agent.fusion.execution._generate_output_path", lambda *_args: str(output_path)
    )
    authority = InMemorySpecialistOperationAuthority()
    executor = BoundSpecialistExecutor(
        store, operation_authority=authority, unknown_after_commit=True
    )
    unknown = asyncio.run(executor(request))
    assert unknown.outcome is TemporalActivityOutcome.UNKNOWN
    assert unknown.output_artifact_id is None
    assert (
        authority.observe(unknown.provider_operation_ref).status
        is SpecialistOperationStatus.SUCCEEDED
    )

    reconciled, settled = reconcile_unknown_specialist_activity(
        request, unknown, artifact_store=store, operation_authority=authority
    )
    assert reconciled.verdict is SpecialistReconciliationVerdict.MATCHED_SUCCEEDED
    assert settled.outcome is TemporalActivityOutcome.SUCCEEDED
    assert settled.output_artifact_id is not None

    # Re-running the same activity observes the terminal provider receipt and does not
    # invoke MMFE a second time or create a second output Artifact.
    def _must_not_execute(*_args, **_kwargs):
        raise AssertionError("provider was re-executed after an uncertain commit")

    monkeypatch.setattr("data_agent.fusion.profile_source", _must_not_execute)
    replay = asyncio.run(executor(request))
    assert replay == settled
    assert len(authority.history) == 2


def test_unknown_cancellation_stays_pending_and_never_fabricates_success(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema": "mmfe.uwm_state_input.v1",
                "version": "0.1",
                "source_product": {"product_id": "cancel-test"},
                "urban_spatial_unit": {"unit_type": "district"},
                "object_role_registry": [],
                "state_components": {},
                "graph_summary": {},
                "production_policy": {"authoritative_data_required_for_production": True},
            }
        ),
        encoding="utf-8",
    )
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    input_id = UUID("00000000-0000-4000-8000-000000007133")
    store.register_input(
        tenant_id="planning",
        artifact_id=input_id,
        source_path=state_path,
        media_type="application/json",
    )
    spec = build_gwm_provider_spec(input_artifact_ids=(input_id,), observation_id="cancel-obs")
    request = _request_with_spec(spec, input_artifact_ids=(input_id,))
    authority = InMemorySpecialistOperationAuthority()
    unknown = asyncio.run(
        BoundSpecialistExecutor(
            store,
            operation_authority=authority,
            cancellation_timeout_before_execution=True,
        )(request)
    )
    assert unknown.outcome is TemporalActivityOutcome.UNKNOWN
    assert unknown.output_artifact_id is None
    observation = authority.observe(unknown.provider_operation_ref)
    assert observation is not None
    assert observation.status is SpecialistOperationStatus.UNKNOWN
    assert observation.cancellation_requested is True

    reconciled, settled = reconcile_unknown_specialist_activity(
        request, unknown, artifact_store=store, operation_authority=authority
    )
    assert reconciled.verdict is SpecialistReconciliationVerdict.UNKNOWN_PENDING
    assert settled.outcome is TemporalActivityOutcome.UNKNOWN
    assert settled.output_artifact_id is None
    assert not any((tmp_path / "artifacts" / "outputs").glob("*"))


def test_provider_cancellation_adapter_is_hash_bound_and_explicitly_fail_closed():
    _harness, _workflow_id, _call, request = _activity_request()
    values = request.model_dump(mode="python")
    spec = build_gwm_provider_spec()
    values["provider_spec"] = spec
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    request = TemporalActivityRequest(**values)
    operation_ref = f"{spec.operation_ref}://{request.activity_id}"
    receipt_ref = f"provider://specialist/{request.activity_id}/{request.attempt_no}"

    adapter = InMemorySpecialistCancellationAdapter()
    accepted = adapter.request_cancellation(
        request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
    )
    assert accepted.status is SpecialistProviderCancellationStatus.ACCEPTED
    assert adapter.observe_cancellation(
        request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
    ) == accepted
    with pytest.raises(SpecialistProviderError, match="identity is already bound differently"):
        adapter.request_cancellation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=f"{receipt_ref}:drift",
        )
    confirmed = adapter.confirm(
        request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
    )
    assert confirmed.status is SpecialistProviderCancellationStatus.CONFIRMED
    assert confirmed.failure_type == "ProviderCancellationConfirmed"

    unsupported = UnsupportedSpecialistCancellationAdapter().request_cancellation(
        request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
    )
    assert unsupported.status is SpecialistProviderCancellationStatus.UNSUPPORTED
    assert unsupported.failure_type is None


def test_temporal_cancellation_requests_provider_and_replay_converges_after_confirmation(
    tmp_path,
):
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    spec = build_gwm_provider_spec()
    request = _request_with_spec(spec, input_artifact_ids=())
    authority = InMemorySpecialistOperationAuthority()
    operation_ref = f"{spec.operation_ref}://{request.activity_id}"
    receipt_ref = f"provider://specialist/{request.activity_id}/{request.attempt_no}"
    authority.submit(
        request,
        provider_ref=spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=receipt_ref,
    )
    adapter = InMemorySpecialistCancellationAdapter()
    executor = BoundSpecialistExecutor(
        store, operation_authority=authority, cancellation_adapter=adapter
    )

    def _bounded_block(_request):
        time.sleep(0.2)

    executor._execute = _bounded_block

    async def _cancel_activity():
        task = asyncio.create_task(executor(request))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_cancel_activity())
    pending = authority.observe(operation_ref)
    assert pending is not None
    assert pending.status is SpecialistOperationStatus.UNKNOWN
    assert pending.cancellation_requested is True
    provider_pending = adapter.observe_cancellation(
        request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
    )
    assert provider_pending is not None
    assert provider_pending.status is SpecialistProviderCancellationStatus.ACCEPTED

    adapter.confirm(
        request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
    )
    replay = asyncio.run(
        BoundSpecialistExecutor(
            store, operation_authority=authority, cancellation_adapter=adapter
        )(request)
    )
    assert replay.outcome is TemporalActivityOutcome.FAILED
    assert replay.failure_type == "ProviderCancellationConfirmed"
    terminal = authority.observe(operation_ref)
    assert terminal is not None
    assert terminal.status is SpecialistOperationStatus.CANCELLED


def test_unknown_reconciliation_rejects_conflicting_output_manifest(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"schema": "mmfe.uwm_state_input.v1"}), encoding="utf-8")
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    input_id = UUID("00000000-0000-4000-8000-000000007134")
    store.register_input(
        tenant_id="planning",
        artifact_id=input_id,
        source_path=state_path,
        media_type="application/json",
    )
    spec = build_gwm_provider_spec(input_artifact_ids=(input_id,), observation_id="conflict-obs")
    request = _request_with_spec(spec, input_artifact_ids=(input_id,))
    authority = InMemorySpecialistOperationAuthority()
    unknown = asyncio.run(
        BoundSpecialistExecutor(
            store,
            operation_authority=authority,
            cancellation_timeout_before_execution=True,
        )(request)
    )
    output_id = UUID("00000000-0000-4000-8000-000000007199")
    store._artifacts[("planning", output_id)] = store.register_input(
        tenant_id="planning",
        artifact_id=output_id,
        source_path=state_path,
        media_type="application/json",
    )
    authority._transition(
        unknown.provider_operation_ref,
        SpecialistOperationStatus.SUCCEEDED,
        output_artifact_id=output_id,
    )
    with pytest.raises(SpecialistProviderError, match="output Artifact identity conflicts"):
        reconcile_unknown_specialist_activity(
            request, unknown, artifact_store=store, operation_authority=authority
        )


def test_temporal_timeout_does_not_override_pending_specialist_operation(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema": "mmfe.uwm_state_input.v1",
                "version": "0.1",
                "source_product": {"product_id": "temporal-timeout"},
                "urban_spatial_unit": {"unit_type": "district"},
                "object_role_registry": [],
                "state_components": {},
                "graph_summary": {},
                "production_policy": {"authoritative_data_required_for_production": True},
            }
        ),
        encoding="utf-8",
    )
    store = FilesystemSpecialistArtifactStore(tmp_path / "artifacts")
    input_id = UUID("00000000-0000-4000-8000-000000007135")
    store.register_input(
        tenant_id="planning",
        artifact_id=input_id,
        source_path=state_path,
        media_type="application/json",
    )
    spec = build_gwm_provider_spec(input_artifact_ids=(input_id,), observation_id="timeout-obs")
    request = _request_with_spec(spec, input_artifact_ids=(input_id,))
    authority = InMemorySpecialistOperationAuthority()
    operation_ref = f"{spec.operation_ref}://{request.activity_id}"
    authority.submit(
        request,
        provider_ref=spec.provider_ref,
        operation_ref=operation_ref,
        provider_receipt_ref=f"provider://specialist/{request.activity_id}/{request.attempt_no}",
    )
    values = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request": request,
        "request_sha256": request.request_sha256,
        "status": TemporalProviderActivityHistoryStatus.TIMED_OUT,
        "scheduled_event_id": 5,
        "started_event_id": 6,
        "terminal_event_id": 7,
        "timeout_type": "TIMEOUT_TYPE_START_TO_CLOSE",
        "failure_type": None,
        "provider_result": None,
    }
    values["observation_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityHistoryObservation.schema_id, values, "observation_sha256"
    )
    observation = TemporalProviderActivityHistoryObservation(**values)
    with pytest.raises(
        TemporalHistoryReconciliationError,
        match="requires specialist receipt reconciliation",
    ):
        activity_evidence_from_history(observation)
    joined, specialist, settled = reconcile_specialist_activity_history(
        observation, artifact_store=store, operation_authority=authority
    )
    assert specialist.verdict.value == "unknown_pending"
    assert settled.outcome is TemporalActivityOutcome.UNKNOWN
    assert joined.temporal_status is TemporalProviderActivityHistoryStatus.TIMED_OUT
    assert joined.resulting_outcome is TemporalActivityOutcome.UNKNOWN


@dataclass
class _MemoryGateway:
    artifacts: dict[tuple[str, UUID], Artifact]

    def get_artifact(self, tenant_id: str, artifact_id: UUID) -> Artifact:
        try:
            return self.artifacts[(tenant_id, artifact_id)]
        except KeyError as exc:
            from data_agent.platform_gateway import GatewayNotFoundError

            raise GatewayNotFoundError("Artifact was not found") from exc

    def record_artifact(self, artifact: Artifact) -> GatewayWriteResult:
        key = (artifact.tenant_id, artifact.artifact_id)
        existing = self.artifacts.get(key)
        if existing is not None:
            if existing != artifact:
                from data_agent.platform_gateway import GatewayConflictError

                raise GatewayConflictError("Artifact identity already has a different payload")
            return GatewayWriteResult(existing, False)
        self.artifacts[key] = artifact
        return GatewayWriteResult(artifact, True)


def test_postgres_authority_adapter_binds_checksum_and_replays_without_local_authority(tmp_path):
    content_backend = FilesystemArtifactContentBackend(tmp_path / "content")
    gateway = _MemoryGateway({})
    store = PostgresArtifactAuthoritySpecialistStore(
        "planning",
        gateway=gateway,
        content_backend=content_backend,
        materialization_root=tmp_path / "materialized",
    )
    input_id = UUID("00000000-0000-4000-8000-000000007111")
    content = b'{"type":"FeatureCollection","features":[]}'
    storage_uri = content_backend.uri_for(
        tenant_id="planning", artifact_id=input_id, media_type="application/geo+json"
    )
    content_backend.write(
        storage_uri=storage_uri, content=content, media_type="application/geo+json"
    )
    with pytest.raises(SpecialistProviderError, match="different bytes"):
        content_backend.write(
            storage_uri=storage_uri,
            content=b"different",
            media_type="application/geo+json",
        )
    import hashlib

    input_artifact = Artifact(
        tenant_id="planning",
        artifact_id=input_id,
        artifact_key="input-7111",
        artifact_role=ArtifactRole.INPUT,
        storage_uri=storage_uri,
        media_type="application/geo+json",
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        manifest={"schema": "test.input.v1"},
        created_by="workload:test",
        created_at=datetime.now(UTC),
    )
    gateway.record_artifact(input_artifact)
    resolved = store.resolve_input("planning", input_id)
    assert resolved.storage_path.read_bytes() == content
    assert resolved.content_sha256 == input_artifact.content_sha256

    content_backend.write(
        storage_uri=storage_uri, content=content, media_type="application/geo+json"
    )
    # Simulate an authority row whose content was changed behind its checksum.
    tampered_uri = content_backend.uri_for(
        tenant_id="planning",
        artifact_id=UUID("00000000-0000-4000-8000-000000007114"),
        media_type="application/json",
    )
    content_backend.write(
        storage_uri=tampered_uri, content=b"tampered", media_type="application/json"
    )
    tampered = input_artifact.model_copy(
        update={
            "artifact_id": UUID("00000000-0000-4000-8000-000000007114"),
            "storage_uri": tampered_uri,
            "media_type": "application/json",
            "content_sha256": hashlib.sha256(b"original").hexdigest(),
            "size_bytes": len(b"original"),
        }
    )
    gateway.record_artifact(tampered)
    with pytest.raises(SpecialistProviderError, match="checksum"):
        store.resolve_input("planning", tampered.artifact_id)

    output_id = UUID("00000000-0000-4000-8000-000000007112")
    manifest = {
        "schema": "gda.specialist_provider_output_manifest.v1",
        "lineage": {"source": [str(input_id)]},
    }
    output = store.write_output(
        tenant_id="planning",
        artifact_id=output_id,
        content=b"output",
        media_type="application/json",
        manifest=manifest,
    )
    replay = store.write_output(
        tenant_id="planning",
        artifact_id=output_id,
        content=b"output",
        media_type="application/json",
        manifest=manifest,
    )
    assert replay == output
    assert len(gateway.artifacts) == 3
    assert gateway.artifacts[("planning", output_id)].artifact_role is ArtifactRole.OUTPUT
    with pytest.raises(SpecialistProviderError, match="different content"):
        store.write_output(
            tenant_id="planning",
            artifact_id=output_id,
            content=b"different-output",
            media_type="application/json",
            manifest=manifest,
        )

    with pytest.raises(SpecialistProviderError, match="tenant differs"):
        store.resolve_input("other-tenant", input_id)


class _FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str, str], bytes] = {}
        self.latest: dict[tuple[str, str], str] = {}
        self.counter = 0
        self.versioning_status = "Enabled"
        self.object_lock_enabled = "Enabled"
        self.default_retention: dict[str, Any] = {"Mode": "GOVERNANCE", "Days": 1}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict[str, str]:
        self.counter += 1
        version = f"v{self.counter}"
        self.objects[(Bucket, Key, version)] = Body
        self.latest[(Bucket, Key)] = version
        return {"VersionId": version}

    def get_object(self, *, Bucket: str, Key: str, VersionId: str | None = None) -> dict[str, Any]:
        version = VersionId or self.latest[(Bucket, Key)]
        return {"Body": _BytesBody(self.objects[(Bucket, Key, version)])}

    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, str]:
        return {"Status": self.versioning_status}

    def get_object_lock_configuration(self, *, Bucket: str) -> dict[str, Any]:
        return {
            "ObjectLockConfiguration": {
                "ObjectLockEnabled": self.object_lock_enabled,
                "Rule": {"DefaultRetention": dict(self.default_retention)},
            }
        }


@pytest.mark.parametrize("missing", ["versioning", "lock", "retention"])
def test_s3_backend_probe_requires_versioning_and_object_lock_retention(missing: str):
    client = _FakeS3Client()
    if missing == "versioning":
        client.versioning_status = "Suspended"
    elif missing == "lock":
        client.object_lock_enabled = "Disabled"
    else:
        client.default_retention = {}
    backend = S3ArtifactContentBackend(
        client,
        bucket="gda-test",
        prefix="agentops",
        require_version_id=True,
        require_object_lock_retention=True,
    )
    with pytest.raises(SpecialistProviderError):
        backend.probe()


def test_s3_backend_probe_returns_immutable_bucket_contract():
    backend = S3ArtifactContentBackend(
        _FakeS3Client(),
        bucket="gda-test",
        prefix="agentops",
        require_version_id=True,
        require_object_lock_retention=True,
    )
    assert backend.probe() == {
        "versioning": "Enabled",
        "object_lock": "Enabled",
        "retention_mode": "GOVERNANCE",
        "retention_unit": "Days",
        "retention_duration": 1,
    }


class _BytesBody:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


def test_s3_backend_requires_and_honors_immutable_version_id():
    client = _FakeS3Client()
    backend = S3ArtifactContentBackend(
        client, bucket="gda-test", prefix="agentops", require_version_id=True
    )
    artifact_id = UUID("00000000-0000-4000-8000-000000007113")
    uri = backend.uri_for(
        tenant_id="planning", artifact_id=artifact_id, media_type="application/json"
    )
    metadata = backend.write(storage_uri=uri, content=b"v1", media_type="application/json")
    assert metadata == {"version_id": "v1"}
    import hashlib

    artifact = Artifact(
        tenant_id="planning",
        artifact_id=artifact_id,
        artifact_key="s3-7113",
        artifact_role=ArtifactRole.INPUT,
        storage_uri=uri,
        media_type="application/json",
        content_sha256=hashlib.sha256(b"v1").hexdigest(),
        size_bytes=2,
        manifest={"storage": metadata},
        created_by="workload:test",
        created_at=datetime.now(UTC),
    )
    assert backend.read(artifact) == b"v1"
    missing_version = artifact.model_copy(update={"manifest": {}})
    with pytest.raises(SpecialistProviderError, match="VersionId"):
        backend.read(missing_version)


def test_postgres_artifact_store_replays_exact_s3_version_across_worker_instances(tmp_path):
    client = _FakeS3Client()
    backend = S3ArtifactContentBackend(
        client, bucket="gda-test", prefix="agentops", require_version_id=True
    )
    gateway = _MemoryGateway({})
    input_id = UUID("00000000-0000-4000-8000-000000007115")
    input_uri = backend.uri_for(
        tenant_id="planning", artifact_id=input_id, media_type="application/json"
    )
    input_storage = backend.write(
        storage_uri=input_uri, content=b"v1", media_type="application/json"
    )
    input_artifact = Artifact(
        tenant_id="planning",
        artifact_id=input_id,
        artifact_key="s3-7115",
        artifact_role=ArtifactRole.INPUT,
        storage_uri=input_uri,
        media_type="application/json",
        content_sha256=hashlib.sha256(b"v1").hexdigest(),
        size_bytes=2,
        manifest={"storage": input_storage},
        created_by="workload:test",
        created_at=datetime.now(UTC),
    )
    gateway.record_artifact(input_artifact)

    first = PostgresArtifactAuthoritySpecialistStore(
        "planning",
        gateway=gateway,
        content_backend=backend,
        materialization_root=tmp_path / "materialized-a",
    )
    assert first.resolve_input("planning", input_id).storage_path.read_bytes() == b"v1"

    # A later object version must not change what a replacement worker reads.
    backend.write(storage_uri=input_uri, content=b"v2", media_type="application/json")
    replacement = PostgresArtifactAuthoritySpecialistStore(
        "planning",
        gateway=gateway,
        content_backend=backend,
        materialization_root=tmp_path / "materialized-b",
    )
    assert replacement.resolve_input("planning", input_id).storage_path.read_bytes() == b"v1"

    output_id = UUID("00000000-0000-4000-8000-000000007116")
    output = first.write_output(
        tenant_id="planning",
        artifact_id=output_id,
        content=b"output-v1",
        media_type="application/json",
        manifest={"schema": "gda.test.output.v1"},
    )
    put_count = client.counter
    replay = replacement.write_output(
        tenant_id="planning",
        artifact_id=output_id,
        content=b"output-v1",
        media_type="application/json",
        manifest={"schema": "gda.test.output.v1"},
    )
    assert replay.storage_path.read_bytes() == b"output-v1"
    assert replay.artifact_id == output.artifact_id
    assert replay.content_sha256 == output.content_sha256
    assert replay.manifest == output.manifest
    assert client.counter == put_count
