from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import data_agent.test_cross_store_projection_compensation_approval as approval_fixtures
from data_agent.cross_store_projection_compensation_object_adapter import (
    FederatedProjectionCompensationObjectAdapterValidationError,
    FederatedProjectionCompensationObjectMutationRequest,
    build_federated_compensation_object_mutation_request,
    execute_federated_compensation_object_mutation,
    federated_compensation_object_payload_fingerprint,
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
    ProjectionEngine,
    build_projection_repair_plan,
)
from data_agent.object_projection_executor import (
    ObjectProjectionRepairExecutor,
    ObjectProjectionTargetRegistry,
)
from data_agent.object_projection_executor_rehearsal import (
    _DEFAULT_BUNDLE,
    _DEFAULT_IMAGE,
    _TemporaryMinio,
)
from data_agent.object_projection_executor_rehearsal import _desired as _rehearsal_desired
from data_agent.object_projection_executor_rehearsal import _target as _rehearsal_target
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    _coordinator,
    _dependencies,
    _plans,
)
from data_agent.test_object_projection_executor import (
    _desired,
    _MemoryS3,
    _write_bundle,
)


def _chain_for_plan(target, object_plan, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    original = _plans(tenant_id=target.tenant_id)
    plans = (original[0], original[1], object_plan)
    providers, authorities = _dependencies(
        plans,
        provider_modes={0: "unknown_without_receipt"},
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
            federated_compensation_object_payload_fingerprint(target, plan.action)
            if plan.target_engine is ProjectionEngine.OBJECT_STORE
            else f"{binding.position + 17:064x}"
        )
        desired = plan.desired_state
        materialization_inputs.append(
            FederatedProjectionCompensationProviderMaterializationInput(
                position=binding.position,
                projection_id=plan.projection_id,
                payload_sha256=payload_sha256,
                expected_target_exists=desired.target_exists,
                expected_target_content_sha256=desired.expected_target_content_sha256,
                expected_target_row_count=desired.expected_row_count,
            )
        )
    materialization = build_federated_compensation_provider_materialization_set(
        plan_set,
        tuple(materialization_inputs),
        materialized_by="workload:chongqing-compensation-materializer",
    )
    binding = next(
        item
        for item in materialization.bindings
        if item.target_engine is ProjectionEngine.OBJECT_STORE
    )
    request = build_federated_compensation_object_mutation_request(
        intent,
        plan_set,
        materialization,
        object_plan,
        target,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )
    return SimpleNamespace(
        intent=intent,
        plan_set=plan_set,
        materialization=materialization,
        binding=binding,
        source_plan=object_plan,
        target=target,
        request=request,
    )


def _chain(tmp_path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    target, _ = _write_bundle(tmp_path)
    client = _MemoryS3()
    executor = ObjectProjectionRepairExecutor(
        ObjectProjectionTargetRegistry((target,)),
        client=client,
    )
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    return _chain_for_plan(target, plan, monkeypatch)


def _image_available() -> bool:
    try:
        result = subprocess.run(
            ("docker", "image", "inspect", _DEFAULT_IMAGE),
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def test_object_request_is_deterministic_and_keeps_execution_material_private(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    replay = build_federated_compensation_object_mutation_request(
        chain.intent,
        chain.plan_set,
        chain.materialization,
        chain.source_plan,
        chain.target,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )

    assert replay == chain.request
    document = json.dumps(chain.request.model_dump(mode="json"), sort_keys=True)
    for forbidden in (
        "endpoint_url",
        "bucket",
        "key",
        "bundle_manifest_path",
        "artifact_path",
        "access_key_id",
        "secret_access_key",
        "payload",
    ):
        assert f'"{forbidden}":' not in document
    with pytest.raises(ValidationError):
        FederatedProjectionCompensationObjectMutationRequest(
            **chain.request.model_dump(mode="python"),
            endpoint_url="http://attacker.invalid:9000",
        )


def test_object_artifact_and_engine_drift_are_rejected_before_provider_access(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    drifted_target = chain.target.model_copy(
        update={"endpoint_url": "http://different-provider.test:9000"}
    )
    with pytest.raises(
        FederatedProjectionCompensationObjectAdapterValidationError,
        match="payload differs",
    ):
        build_federated_compensation_object_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            chain.source_plan,
            drifted_target,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    with pytest.raises(
        FederatedProjectionCompensationObjectAdapterValidationError,
        match="source plan differs",
    ):
        build_federated_compensation_object_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            _plans(tenant_id=chain.target.tenant_id)[1],
            chain.target,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    client = _MemoryS3()
    executor = ObjectProjectionRepairExecutor(
        ObjectProjectionTargetRegistry((drifted_target,)),
        client=client,
    )
    with pytest.raises(
        FederatedProjectionCompensationObjectAdapterValidationError,
        match="registered object artifact differs",
    ):
        execute_federated_compensation_object_mutation(
            chain.request,
            executor=executor,
        )
    assert client.counter == 0
    assert client.versions == {}


def test_object_executor_versioned_mutation_replay_and_receipt_validation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    client = _MemoryS3()
    registry = ObjectProjectionTargetRegistry((chain.target,))
    executor = ObjectProjectionRepairExecutor(registry, client=client)

    first = execute_federated_compensation_object_mutation(
        chain.request,
        executor=executor,
    )
    restarted = ObjectProjectionRepairExecutor(registry, client=client)
    replay = execute_federated_compensation_object_mutation(
        chain.request,
        executor=restarted,
    )

    assert first.provider_execution_status == "provider_mutation_committed"
    assert first.provider_mutation_performed is True
    assert first.receipt.provider_commit_ref["provider_atomicity"] == (
        "target_payload_and_plan_metadata_single_put_object"
    )
    assert first.receipt.object_version_id is not None
    assert replay.provider_execution_status == "provider_idempotent_replay"
    assert replay.provider_mutation_performed is False
    assert client.counter == 1
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


@pytest.mark.skipif(
    not _image_available(),
    reason="pinned MinIO image is unavailable",
)
def test_real_minio_versioned_mutation_receipt_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = _TemporaryMinio(_DEFAULT_IMAGE)
    bucket_removed = False
    cleanup = (False, False)
    try:
        temporary.start()
        assert temporary.endpoint is not None
        assert temporary.client is not None
        target = _rehearsal_target(
            _DEFAULT_BUNDLE,
            temporary.endpoint,
            temporary.bucket,
        )
        registry = ObjectProjectionTargetRegistry((target,))
        executor = ObjectProjectionRepairExecutor(
            registry,
            client=temporary.client,
            timeout_seconds=600,
        )
        plan = build_projection_repair_plan(
            _rehearsal_desired(
                target,
                source_sha256=target.artifact_sha256,
                source_version=target.bundle_version,
            ),
            executor.observe(target),
            None,
        )
        chain = _chain_for_plan(target, plan, monkeypatch)

        first = execute_federated_compensation_object_mutation(
            chain.request,
            executor=executor,
        )
        restarted = ObjectProjectionRepairExecutor(
            registry,
            client=temporary.client,
            timeout_seconds=600,
        )
        replay = execute_federated_compensation_object_mutation(
            chain.request,
            executor=restarted,
        )

        assert first.provider_execution_status == "provider_mutation_committed"
        assert first.receipt.provider_commit_ref["provider"] == "s3_object_store"
        assert first.receipt.provider_commit_ref["provider_atomicity"] == (
            "target_payload_and_plan_metadata_single_put_object"
        )
        assert first.receipt.target_content_sha256 == target.artifact_sha256
        assert first.receipt.target_size_bytes == target.artifact_size_bytes
        assert first.receipt.object_version_id is not None
        assert replay.provider_execution_status == "provider_idempotent_replay"
        recovered = restarted.recover_receipt(chain.request.execution_plan)
        assert recovered is not None
        assert recovered.provider_commit_ref == first.receipt.provider_commit_ref
        versions = temporary.client.list_object_versions(
            Bucket=target.bucket,
            Prefix=target.key,
            MaxKeys=1000,
        )
        target_versions = [
            item for item in versions.get("Versions", []) if item["Key"] == target.key
        ]
        assert len(target_versions) == 1
    finally:
        try:
            bucket_removed = temporary.delete_bucket_and_verify()
        finally:
            cleanup = temporary.stop_and_verify()
    assert bucket_removed
    assert cleanup == (True, True)
