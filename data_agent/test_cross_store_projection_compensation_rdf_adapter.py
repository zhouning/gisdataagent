from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import data_agent.test_cross_store_projection_compensation_approval as approval_fixtures
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
from data_agent.cross_store_projection_compensation_rdf_adapter import (
    FederatedProjectionCompensationRDFAdapterValidationError,
    FederatedProjectionCompensationRDFMutationRequest,
    build_federated_compensation_rdf_mutation_request,
    execute_federated_compensation_rdf_mutation,
    federated_compensation_rdf_payload_fingerprint,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionEngine,
    build_projection_repair_plan,
)
from data_agent.rdf_projection_executor import (
    RDFProjectionRepairExecutor,
    RDFProjectionTargetRegistry,
)
from data_agent.rdf_projection_executor_rehearsal import (
    _DEFAULT_IMAGE,
    _DEFAULT_PACKAGE,
    _registered_target,
    _TemporaryFuseki,
)
from data_agent.rdf_projection_executor_rehearsal import (
    _desired as _rehearsal_desired,
)
from data_agent.test_cross_store_projection_compensation_provider_adapter import (
    _inputs,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    _coordinator,
    _dependencies,
    _plans,
)
from data_agent.test_rdf_projection_executor import (
    _desired,
    _missing,
    _provider_state,
    _transport,
    _write_package,
)


def _chain_for_plan(
    target,
    rdf_plan,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    original = _plans(tenant_id=target.tenant_id)
    plans = (original[0], rdf_plan, original[2])
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
            federated_compensation_rdf_payload_fingerprint(target, plan.action)
            if plan.target_engine is ProjectionEngine.RDF
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
    source_plan = rdf_plan
    binding = next(
        item for item in materialization.bindings if item.target_engine is ProjectionEngine.RDF
    )
    request = build_federated_compensation_rdf_mutation_request(
        intent,
        plan_set,
        materialization,
        source_plan,
        target,
        dispatched_by="workload:chongqing-compensation-dispatcher",
    )
    return SimpleNamespace(
        intent=intent,
        plan_set=plan_set,
        materialization=materialization,
        binding=binding,
        source_plan=source_plan,
        target=target,
        request=request,
    )


def _chain(tmp_path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    target, graph = _write_package(tmp_path)
    rdf_plan = build_projection_repair_plan(
        _desired(target, graph),
        _missing(target),
        None,
    )
    return _chain_for_plan(target, rdf_plan, monkeypatch)


def _fuseki_image_available() -> bool:
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


def test_rdf_request_is_deterministic_and_does_not_expose_transport_details(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    replay = build_federated_compensation_rdf_mutation_request(
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
        "graph_store_endpoint",
        "sparql_update_endpoint",
        "package_dir",
        "username",
        "password",
        "sql",
    ):
        assert forbidden not in document
    with pytest.raises(ValidationError):
        FederatedProjectionCompensationRDFMutationRequest(
            **chain.request.model_dump(mode="python"),
            graph_store_endpoint="http://attacker.invalid/data",
        )


def test_rdf_payload_and_engine_drift_are_rejected_before_provider_access(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    drifted_target = chain.target.model_copy(update={"package_id": "drifted-package"})
    with pytest.raises(
        FederatedProjectionCompensationRDFAdapterValidationError,
        match="payload differs",
    ):
        build_federated_compensation_rdf_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            chain.source_plan,
            drifted_target,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    with pytest.raises(
        FederatedProjectionCompensationRDFAdapterValidationError,
        match="source plan differs",
    ):
        build_federated_compensation_rdf_mutation_request(
            chain.intent,
            chain.plan_set,
            chain.materialization,
            _plans(tenant_id=chain.target.tenant_id)[0],
            chain.target,
            dispatched_by="workload:chongqing-compensation-dispatcher",
        )

    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((drifted_target,)),
        transport=_transport(state),
    )
    with pytest.raises(
        FederatedProjectionCompensationRDFAdapterValidationError,
        match="registered RDF package differs",
    ):
        execute_federated_compensation_rdf_mutation(
            chain.request,
            executor=executor,
        )
    assert state["update_calls"] == 0
    assert state["graph"] is None


def test_rdf_executor_transport_mutation_replay_and_receipt_validation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _chain(tmp_path, monkeypatch)
    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((chain.target,)),
        transport=_transport(state),
    )

    first = execute_federated_compensation_rdf_mutation(
        chain.request,
        executor=executor,
    )
    replay = execute_federated_compensation_rdf_mutation(
        chain.request,
        executor=executor,
    )

    assert first.provider_execution_status == "provider_mutation_committed"
    assert first.provider_mutation_performed is True
    assert replay.provider_execution_status == "provider_idempotent_replay"
    assert replay.provider_mutation_performed is False
    assert state["update_calls"] == 1
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
    not _fuseki_image_available(),
    reason="natural-resource-one-map 2.3.0 Fuseki image is unavailable",
)
def test_real_fuseki_container_mutation_receipt_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = _TemporaryFuseki(_DEFAULT_IMAGE)
    cleanup = (False, False)
    try:
        temporary.start()
        assert temporary.endpoint is not None
        assert temporary.update_endpoint is not None
        target = _registered_target(
            _DEFAULT_PACKAGE,
            temporary.endpoint,
            temporary.update_endpoint,
        )
        executor = RDFProjectionRepairExecutor(
            RDFProjectionTargetRegistry((target,)),
            timeout_seconds=600,
        )
        _, target_sha256, triple_count = executor._load_package(target)
        desired = _rehearsal_desired(
            target,
            target_content_sha256=target_sha256,
            triple_count=triple_count,
            source_content_sha256=target.package_content_sha256,
            source_version=target.semantic_version,
        )
        plan = build_projection_repair_plan(desired, _missing(target), None)
        chain = _chain_for_plan(target, plan, monkeypatch)

        first = execute_federated_compensation_rdf_mutation(
            chain.request,
            executor=executor,
        )
        replay = execute_federated_compensation_rdf_mutation(
            chain.request,
            executor=executor,
        )

        assert first.provider_execution_status == "provider_mutation_committed"
        assert first.receipt.provider_commit_ref["provider"] == "rdf_fuseki"
        assert first.receipt.provider_commit_ref["provider_atomicity"] == (
            "single_fuseki_update_request"
        )
        assert first.receipt.target_content_sha256 == target_sha256
        assert first.receipt.target_row_count == triple_count
        assert replay.provider_execution_status == "provider_idempotent_replay"
        assert executor.observe(target).observed_content_sha256 == target_sha256
        recovered = executor.recover_receipt(chain.request.execution_plan)
        assert recovered is not None
        assert recovered.provider_commit_ref == first.receipt.provider_commit_ref
    finally:
        cleanup = temporary.stop_and_verify()
    assert cleanup == (True, True)
