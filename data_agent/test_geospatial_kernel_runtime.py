from __future__ import annotations

from dataclasses import replace

import torch

from data_agent.uwm.dam_geospatial_kernel import (
    DAM_GK_RUNTIME_ADAPTER,
    DAMGKBatch,
    DAMGKConfig,
    DAMGKRuntimeAdapter,
    DynamicActionConditionedMultiscaleKernel,
    dam_gk_runtime_state,
)
from data_agent.uwm.geospatial_kernel import (
    GEOSPATIAL_KERNEL_ROLLOUT_SCHEMA,
    GeospatialKernelRuntime,
    KernelAction,
    KernelAdapterDescriptor,
    KernelConstraintProjection,
    KernelProvenance,
    KernelState,
    KernelTransitionCandidate,
    build_kernel_capability_report,
    summarize_kernel_steps,
)

NUMERIC_ADAPTER = KernelAdapterDescriptor(
    adapter_id="numeric-test-adapter",
    adapter_version="1.0.0",
    domain="bounded_numeric_world",
    state_semantics="bounded integer state",
    action_semantics="integer increment",
    transition_semantics="additive proposal",
    constraint_semantics="upper-bound projection",
)


class _NumericAdapter:
    descriptor = NUMERIC_ADAPTER

    def propose_transition(self, *, state, action, context):
        del context
        return KernelTransitionCandidate(payload=state.payload + action.payload)

    def project_constraints(self, *, state, action, candidate, context):
        del state, context
        projected = min(10, candidate.payload)
        return KernelConstraintProjection(
            state_payload=projected,
            status="projected" if projected != candidate.payload else "admitted",
            state_ref=f"numeric-{action.target_time}",
            provenance=KernelProvenance(
                model_id="numeric-test",
                model_version="1",
                parameter_ref="fixed",
            ),
            diagnostics={"upper_bound": 10},
        )


def test_common_runtime_executes_recursive_state_writeback_and_audit() -> None:
    runtime = GeospatialKernelRuntime(_NumericAdapter())
    initial = KernelState(
        domain=NUMERIC_ADAPTER.domain,
        time_id="t0",
        state_ref="numeric-t0",
        payload=2,
    )
    actions = (
        KernelAction(
            action_id="add-3",
            domain=NUMERIC_ADAPTER.domain,
            source_time="t0",
            target_time="t1",
            payload=3,
        ),
        KernelAction(
            action_id="add-20",
            domain=NUMERIC_ADAPTER.domain,
            source_time="t1",
            target_time="t2",
            payload=20,
        ),
    )

    trace = runtime.rollout(
        initial_state=initial,
        steps=((actions[0], None), (actions[1], None)),
    )

    assert trace.final_state.payload == 10
    assert [step.next_state.payload for step in trace.steps] == [5, 10]
    assert trace.steps[1].projection.status == "projected"
    assert trace.audit()["schema"] == GEOSPATIAL_KERNEL_ROLLOUT_SCHEMA
    assert trace.audit()["step_count"] == 2
    summary = summarize_kernel_steps(
        adapter=NUMERIC_ADAPTER,
        expected_step_count=2,
        steps=trace.steps,
    )
    assert summary["completed_step_count"] == 2
    assert summary["status_counts"] == {
        "admitted": 1,
        "projected": 1,
        "rejected": 0,
    }
    assert summary["all_expected_steps_completed"] is True
    assert summary["all_steps_admitted"] is False
    assert summary["claim_boundary"] == {
        "execution_completed_does_not_imply_domain_validation": True,
        "projected_steps_are_not_admitted": True,
    }


def test_common_runtime_rejects_cross_domain_or_stale_action() -> None:
    runtime = GeospatialKernelRuntime(_NumericAdapter())
    state = KernelState(
        domain=NUMERIC_ADAPTER.domain,
        time_id="t0",
        state_ref="numeric-t0",
        payload=2,
    )
    wrong_domain = KernelAction(
        action_id="wrong-domain",
        domain="other",
        source_time="t0",
        target_time="t1",
        payload=1,
    )
    stale = KernelAction(
        action_id="stale",
        domain=NUMERIC_ADAPTER.domain,
        source_time="older",
        target_time="t1",
        payload=1,
    )

    for action, message in (
        (wrong_domain, "geospatial_kernel_domain_mismatch"),
        (stale, "geospatial_kernel_action_source_time_mismatch"),
    ):
        try:
            runtime.step(state=state, action=action, context=None)
        except ValueError as exc:
            assert str(exc) == message
        else:
            raise AssertionError("invalid common-kernel action was admitted")


def _dam_batch() -> DAMGKBatch:
    return DAMGKBatch(
        node_state=torch.tensor([[0.2, 0.8], [0.4, 0.6], [0.7, 0.3]], dtype=torch.float32),
        node_action=torch.tensor([[1.0], [0.0], [0.0]], dtype=torch.float32),
        edge_index=torch.tensor([[0, 1], [1, 2]], dtype=torch.long),
        edge_features=torch.ones((2, 1), dtype=torch.float32),
        edge_types=torch.zeros(2, dtype=torch.long),
    )


def test_dam_adapter_preserves_existing_deterministic_forward_result() -> None:
    torch.manual_seed(19)
    model = DynamicActionConditionedMultiscaleKernel(
        DAMGKConfig(
            node_state_dim=2,
            action_dim=1,
            edge_feature_dim=1,
            relation_type_count=1,
            hidden_dim=8,
            horizon=2,
            state_writeback_mode="additive",
        )
    )
    original = _dam_batch()
    state = dam_gk_runtime_state(
        original,
        time_id="2026-08-02T00:00:00Z",
        state_ref="deterministic-dam-state",
    )
    action = KernelAction(
        action_id="release-schedule-1",
        domain=DAM_GK_RUNTIME_ADAPTER.domain,
        source_time="2026-08-02T00:00:00Z",
        target_time="2026-08-02T02:00:00Z",
        payload=original.node_action,
    )
    model.eval()
    with torch.no_grad():
        direct = model(replace(state.payload, node_action=action.payload))

    result = GeospatialKernelRuntime(
        DAMGKRuntimeAdapter(model, parameter_ref="in-memory:test-seed-19")
    ).step(state=state, action=action, context=None)

    assert torch.equal(result.candidate.payload.predicted_state, direct.predicted_state)
    assert torch.equal(result.candidate.payload.rolled_state, direct.rolled_state)
    assert torch.equal(
        result.next_state.payload.node_state,
        direct.rolled_state[:, -1, :],
    )
    assert torch.count_nonzero(result.next_state.payload.node_action) == 0
    assert result.projection.diagnostics["finite_state_admission"] is True


def test_capability_report_states_two_adapters_share_contract_not_algorithm() -> None:
    report = build_kernel_capability_report([NUMERIC_ADAPTER, DAM_GK_RUNTIME_ADAPTER])

    assert report["adapter_count"] == 2
    assert report["claim_boundary"] == {
        "shared_execution_semantics": True,
        "shared_learning_algorithm": False,
        "shared_parameters": False,
        "cross_domain_skill_transfer_proven": False,
    }
