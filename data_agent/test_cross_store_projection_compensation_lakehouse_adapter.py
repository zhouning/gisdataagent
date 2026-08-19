from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import data_agent.test_cross_store_projection_compensation_approval as approval_fixtures
from data_agent.cross_store_projection_compensation_lakehouse_adapter import (
    FederatedProjectionCompensationLakehouseAdapterValidationError,
    FederatedProjectionCompensationLakehouseMutationRequest,
    build_federated_compensation_lakehouse_mutation_request,
    execute_federated_compensation_lakehouse_mutation,
    federated_compensation_lakehouse_payload_fingerprint,
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
from data_agent.lakehouse_projection_executor import (
    LakehouseProjectionRepairExecutor,
    LakehouseProjectionTargetRegistry,
)
from data_agent.lakehouse_projection_executor_rehearsal import (
    _DEFAULT_BUNDLE,
    _DEFAULT_MINIO_IMAGE,
    _DEFAULT_SPARK_IMAGE,
    _TemporaryLakehouse,
)
from data_agent.lakehouse_projection_executor_rehearsal import _target as _rehearsal_target
from data_agent.lakehouse_projection_spark_provider import (
    DockerSparkIcebergProjectionProvider,
)
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    _coordinator,
    _dependencies,
    _plans,
)
from data_agent.test_lakehouse_projection_executor import (
    _desired,
    _MemoryIceberg,
    _target,
)


def _chain_for_plan(target, lakehouse_plan, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    original = _plans(tenant_id=target.tenant_id)
    plans = (original[0], original[1], lakehouse_plan)
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
            federated_compensation_lakehouse_payload_fingerprint(target, plan.action)
            if plan.target_engine is ProjectionEngine.LAKEHOUSE
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
        if item.target_engine is ProjectionEngine.LAKEHOUSE
    )
    request = build_federated_compensation_lakehouse_mutation_request(
        intent,
        plan_set,
        materialization,
        lakehouse_plan,
        target,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )
    return SimpleNamespace(
        intent=intent,
        plan_set=plan_set,
        materialization=materialization,
        binding=binding,
        source_plan=lakehouse_plan,
        target=target,
        request=request,
    )


def _chain(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    target = _target()
    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(
        LakehouseProjectionTargetRegistry((target,)),
        provider=provider,
    )
    plan = build_projection_repair_plan(_desired(target), executor.observe(target), None)
    return _chain_for_plan(target, plan, monkeypatch)


def _images_available() -> bool:
    try:
        for image in (_DEFAULT_MINIO_IMAGE, _DEFAULT_SPARK_IMAGE):
            result = subprocess.run(
                ("docker", "image", "inspect", image),
                check=False,
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def test_lakehouse_request_is_deterministic_and_keeps_execution_material_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    replay = build_federated_compensation_lakehouse_mutation_request(
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
        "warehouse_uri",
        "bundle_manifest_path",
        "artifact_path",
        "access_key_id",
        "secret_access_key",
        "docker_network",
        "records",
    ):
        assert forbidden not in document
    with pytest.raises(ValidationError):
        FederatedProjectionCompensationLakehouseMutationRequest(
            **chain.request.model_dump(mode="python"),
            endpoint_url="http://attacker.invalid:9000",
        )


def test_lakehouse_artifact_and_engine_drift_are_rejected_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    drifted_target = chain.target.model_copy(
        update={"endpoint_url": "http://different-provider.test:9000"}
    )
    with pytest.raises(
        FederatedProjectionCompensationLakehouseAdapterValidationError,
        match="payload differs",
    ):
        build_federated_compensation_lakehouse_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            chain.source_plan,
            drifted_target,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    with pytest.raises(
        FederatedProjectionCompensationLakehouseAdapterValidationError,
        match="source plan differs",
    ):
        build_federated_compensation_lakehouse_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            _plans(tenant_id=chain.target.tenant_id)[1],
            chain.target,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(
        LakehouseProjectionTargetRegistry((drifted_target,)),
        provider=provider,
    )
    with pytest.raises(
        FederatedProjectionCompensationLakehouseAdapterValidationError,
        match="registered Lakehouse artifact differs",
    ):
        execute_federated_compensation_lakehouse_mutation(
            chain.request,
            executor=executor,
        )
    assert provider.replace_calls == 0
    assert provider.drop_calls == 0


def test_lakehouse_executor_snapshot_mutation_replay_and_receipt_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(monkeypatch)
    provider = _MemoryIceberg()
    executor = LakehouseProjectionRepairExecutor(
        LakehouseProjectionTargetRegistry((chain.target,)),
        provider=provider,
    )

    first = execute_federated_compensation_lakehouse_mutation(
        chain.request,
        executor=executor,
    )
    replay = execute_federated_compensation_lakehouse_mutation(
        chain.request,
        executor=executor,
    )

    assert first.provider_execution_status == "provider_mutation_committed"
    assert first.provider_mutation_performed is True
    assert first.receipt.provider_commit_ref["provider_atomicity"] == (
        "single_iceberg_commit_with_snapshot_receipt"
    )
    assert replay.provider_execution_status == "provider_idempotent_replay"
    assert replay.provider_mutation_performed is False
    assert provider.replace_calls == 1
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
    not _images_available(),
    reason="pinned MinIO and Spark/Iceberg images are unavailable",
)
def test_real_spark_iceberg_container_mutation_receipt_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = _TemporaryLakehouse(_DEFAULT_MINIO_IMAGE)
    bucket_removed = False
    cleanup = (False, False, False)
    try:
        temporary.start()
        target = _rehearsal_target(_DEFAULT_BUNDLE, temporary)
        provider = DockerSparkIcebergProjectionProvider(
            repository_root=Path(__file__).resolve().parents[1],
            image=_DEFAULT_SPARK_IMAGE,
            docker_network=temporary.network,
            access_key_id=temporary.access_key,
            secret_access_key=temporary.secret_key,
            java_home="/usr/lib/jvm/java-17-openjdk-arm64",
            timeout_seconds=900,
        )
        executor = LakehouseProjectionRepairExecutor(
            LakehouseProjectionTargetRegistry((target,)),
            provider=provider,
        )
        plan = build_projection_repair_plan(
            _desired(target),
            executor.observe(target),
            None,
        )
        chain = _chain_for_plan(target, plan, monkeypatch)

        first = execute_federated_compensation_lakehouse_mutation(
            chain.request,
            executor=executor,
        )
        restarted = LakehouseProjectionRepairExecutor(
            LakehouseProjectionTargetRegistry((target,)),
            provider=provider,
        )
        replay = execute_federated_compensation_lakehouse_mutation(
            chain.request,
            executor=restarted,
        )

        assert first.provider_execution_status == "provider_mutation_committed"
        assert first.receipt.provider_commit_ref["provider"] == "spark_iceberg"
        assert first.receipt.provider_commit_ref["provider_atomicity"] == (
            "single_iceberg_commit_with_snapshot_receipt"
        )
        assert first.receipt.target_row_count == 445
        assert first.receipt.target_content_sha256 == target.expected_table_content_sha256
        assert first.receipt.snapshot_id is not None
        assert replay.provider_execution_status == "provider_idempotent_replay"
        recovered = restarted.recover_receipt(chain.request.execution_plan)
        assert recovered is not None
        assert recovered.provider_commit_ref == first.receipt.provider_commit_ref
    finally:
        try:
            bucket_removed = temporary.delete_bucket_and_verify()
        finally:
            cleanup = temporary.stop_and_verify()
    assert bucket_removed
    assert cleanup == (True, True, True)
