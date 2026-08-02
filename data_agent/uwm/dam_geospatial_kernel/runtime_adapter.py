"""Thin DAM-GK adapter for the shared Geospatial Kernel runtime."""

from __future__ import annotations

from dataclasses import replace

import torch

from data_agent.uwm.geospatial_kernel.runtime import (
    KernelAction,
    KernelAdapterDescriptor,
    KernelConstraintProjection,
    KernelProvenance,
    KernelState,
    KernelTransitionCandidate,
)

from .contracts import DAMGKBatch, DAMGKOutput
from .model import DynamicActionConditionedMultiscaleKernel

DAM_GK_RUNTIME_ADAPTER = KernelAdapterDescriptor(
    adapter_id="dam-gk-runtime-adapter",
    adapter_version="1.0.0",
    domain="dam_hydraulic_network",
    state_semantics="typed hydraulic graph state and exogenous context",
    action_semantics="node-aligned reservoir release action tensor",
    transition_semantics="dynamic action-conditioned multiscale graph forecast",
    constraint_semantics="DAM-GK configured state-writeback and finite-state admission",
)


class DAMGKRuntimeAdapter:
    """Expose the unchanged DAM-GK forward pass through the common contract."""

    descriptor = DAM_GK_RUNTIME_ADAPTER

    def __init__(
        self,
        model: DynamicActionConditionedMultiscaleKernel,
        *,
        parameter_ref: str,
    ) -> None:
        if not str(parameter_ref).strip():
            raise ValueError("dam_gk_parameter_ref_required")
        self.model = model
        self.parameter_ref = str(parameter_ref)

    def propose_transition(
        self,
        *,
        state: KernelState[DAMGKBatch],
        action: KernelAction[torch.Tensor],
        context: None,
    ) -> KernelTransitionCandidate[DAMGKOutput]:
        del context
        if not isinstance(state.payload, DAMGKBatch):
            raise TypeError("dam_gk_runtime_state_must_be_batch")
        if not isinstance(action.payload, torch.Tensor):
            raise TypeError("dam_gk_runtime_action_must_be_tensor")
        if action.payload.shape != state.payload.node_action.shape:
            raise ValueError("dam_gk_runtime_action_shape_mismatch")
        batch = replace(state.payload, node_action=action.payload)
        batch.validate(self.model.config)
        self.model.eval()
        with torch.no_grad():
            output = self.model(batch)
        return KernelTransitionCandidate(
            payload=output,
            diagnostics={
                "native_horizon": self.model.config.horizon,
                "node_count": int(batch.node_state.shape[0]),
                "edge_count": int(batch.edge_index.shape[1]),
                "state_writeback_mode": self.model.config.state_writeback_mode,
                "candidate_kind": "dam_gk_output",
            },
        )

    def project_constraints(
        self,
        *,
        state: KernelState[DAMGKBatch],
        action: KernelAction[torch.Tensor],
        candidate: KernelTransitionCandidate[DAMGKOutput],
        context: None,
    ) -> KernelConstraintProjection[DAMGKBatch]:
        del context
        output = candidate.payload
        if not isinstance(output, DAMGKOutput):
            raise TypeError("dam_gk_runtime_candidate_must_be_output")
        tensors = (
            output.predicted_state,
            output.rolled_state,
            output.state_delta_mean,
            output.state_delta_scale,
        )
        finite = all(bool(torch.isfinite(value).all()) for value in tensors)
        provenance = KernelProvenance(
            model_id=self.model.__class__.__name__,
            model_version=self.descriptor.adapter_version,
            parameter_ref=self.parameter_ref,
            evidence=state.evidence + action.evidence,
            metadata={
                "domain_adapter": self.descriptor.adapter_id,
                "native_horizon": self.model.config.horizon,
            },
        )
        if not finite:
            return KernelConstraintProjection(
                state_payload=None,
                status="rejected",
                state_ref=f"{state.state_ref}:{action.target_time}:rejected",
                provenance=provenance,
                violations=("dam_gk_nonfinite_forecast",),
                diagnostics={"finite_state_admission": False},
            )
        next_batch = replace(
            state.payload,
            node_state=output.rolled_state[:, -1, :].clone(),
            node_action=torch.zeros_like(state.payload.node_action),
            teacher_state_by_step=None,
        )
        return KernelConstraintProjection(
            state_payload=next_batch,
            status="admitted",
            state_ref=f"{state.state_ref}:{action.target_time}",
            provenance=provenance,
            diagnostics={
                "finite_state_admission": True,
                "state_writeback_mode": self.model.config.state_writeback_mode,
                "writeback_source": "rolled_state_final_native_step",
            },
        )


def dam_gk_runtime_state(
    batch: DAMGKBatch,
    *,
    time_id: str,
    state_ref: str,
) -> KernelState[DAMGKBatch]:
    """Separate the current DAM state from the action supplied at execution time."""

    return KernelState(
        domain=DAM_GK_RUNTIME_ADAPTER.domain,
        time_id=time_id,
        state_ref=state_ref,
        payload=replace(batch, node_action=torch.zeros_like(batch.node_action)),
    )
