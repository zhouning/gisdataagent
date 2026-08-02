"""Shared-runtime adapter for the conservative branching hydraulic operator."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from data_agent.uwm.geospatial_kernel.runtime import (
    KernelAction,
    KernelAdapterDescriptor,
    KernelConstraintProjection,
    KernelProvenance,
    KernelState,
    KernelTransitionCandidate,
)

from .branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportResult,
    ModeledTributaryBoundaryFlux,
    ObservedInternalBoundaryReplacement,
)
from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)

BRANCHING_HYDRAULIC_RUNTIME_ADAPTER = KernelAdapterDescriptor(
    adapter_id="gk-v2-branching-hydraulic-runtime-adapter",
    adapter_version="1.0.0",
    domain="conservative_hydraulic_reach_network",
    state_semantics="feature-aligned reach storage with fixed admitted hydraulic geometry",
    action_semantics="boundary release, distributed forcing and optional boundary replacements",
    transition_semantics="nonlinear conservative Manning transport on an authoritative reach DAG",
    constraint_semantics="finite nonnegative stock, component admission and global mass closure",
)


@dataclass(frozen=True)
class BranchingHydraulicRuntimeState:
    stock: StockState
    geometry: ReachHydraulicGeometry


@dataclass(frozen=True)
class BranchingHydraulicFluxAction:
    action: ActionBoundaryFlux | None = None
    forcing: ForcingFlux | None = None
    forcing_support: ReachForcingSupport | None = None
    tributary_boundary: ModeledTributaryBoundaryFlux | None = None
    internal_boundary: ObservedInternalBoundaryReplacement | None = None


class BranchingHydraulicRuntimeAdapter:
    """Execute the unchanged conservative solver behind the common contract."""

    descriptor = BRANCHING_HYDRAULIC_RUNTIME_ADAPTER

    def __init__(
        self,
        operator: BranchingManningNetworkTransportOperator,
        *,
        parameter_ref: str,
    ) -> None:
        if not str(parameter_ref).strip():
            raise ValueError("branching_hydraulic_parameter_ref_required")
        self.operator = operator
        self.parameter_ref = str(parameter_ref)

    def propose_transition(
        self,
        *,
        state: KernelState[BranchingHydraulicRuntimeState],
        action: KernelAction[BranchingHydraulicFluxAction],
        context: None,
    ) -> KernelTransitionCandidate[BranchingNetworkTransportResult]:
        del context
        if not isinstance(state.payload, BranchingHydraulicRuntimeState):
            raise TypeError("branching_hydraulic_runtime_state_invalid")
        if not isinstance(action.payload, BranchingHydraulicFluxAction):
            raise TypeError("branching_hydraulic_runtime_action_invalid")
        flux = action.payload
        result = self.operator.step(
            state.payload.stock,
            state.payload.geometry,
            action=flux.action,
            forcing=flux.forcing,
            forcing_support=flux.forcing_support,
            tributary_boundary=flux.tributary_boundary,
            internal_boundary=flux.internal_boundary,
        )
        return KernelTransitionCandidate(
            payload=result,
            diagnostics={
                "candidate_kind": "branching_network_transport_result",
                "feature_count": len(result.feature_ids),
                "outlet_mean_flow_m3s": result.outlet_mean_flow_m3s,
                "total_input_volume_m3": result.total_input_volume_m3,
                "outlet_volume_m3": result.outlet_volume_m3,
                "mass_balance_residual_m3": result.global_mass_balance_residual_m3,
                "mass_balance_tolerance_m3": result.numeric_mass_tolerance_m3,
            },
        )

    def project_constraints(
        self,
        *,
        state: KernelState[BranchingHydraulicRuntimeState],
        action: KernelAction[BranchingHydraulicFluxAction],
        candidate: KernelTransitionCandidate[BranchingNetworkTransportResult],
        context: None,
    ) -> KernelConstraintProjection[BranchingHydraulicRuntimeState]:
        del context
        result = candidate.payload
        if not isinstance(result, BranchingNetworkTransportResult):
            raise TypeError("branching_hydraulic_runtime_candidate_invalid")
        values = np.asarray(result.next_stock.values, dtype=float)
        finite_nonnegative = bool(np.isfinite(values).all() and (values >= 0.0).all())
        mass_balance_passed = bool(
            np.isfinite(result.global_mass_balance_residual_m3)
            and np.isfinite(result.numeric_mass_tolerance_m3)
            and abs(result.global_mass_balance_residual_m3) <= result.numeric_mass_tolerance_m3
        )
        provenance = KernelProvenance(
            model_id=self.operator.__class__.__name__,
            model_version=self.descriptor.adapter_version,
            parameter_ref=self.parameter_ref,
            evidence=state.evidence + action.evidence,
            metadata={
                "adapter_id": self.descriptor.adapter_id,
                "network_id": self.operator.network.network_id,
                "network_provenance_id": self.operator.network.provenance_id,
            },
        )
        violations = []
        if not finite_nonnegative:
            violations.append("hydraulic_next_stock_not_finite_nonnegative")
        if not mass_balance_passed:
            violations.append("hydraulic_global_mass_balance_exceeded")
        if violations:
            return KernelConstraintProjection(
                state_payload=None,
                status="rejected",
                state_ref=f"{state.state_ref}:{action.target_time}:rejected",
                provenance=provenance,
                violations=tuple(violations),
                diagnostics={
                    "finite_nonnegative_stock": finite_nonnegative,
                    "mass_balance_passed": mass_balance_passed,
                    "transport_admitted": result.nonlinear_transport_admitted,
                },
            )
        admitted = result.nonlinear_transport_admitted
        return KernelConstraintProjection(
            state_payload=BranchingHydraulicRuntimeState(
                stock=result.next_stock,
                geometry=state.payload.geometry,
            ),
            status="admitted" if admitted else "projected",
            state_ref=f"{state.state_ref}:{action.target_time}",
            provenance=provenance,
            violations=(() if admitted else ("hydraulic_components_diagnostic_only",)),
            diagnostics={
                "finite_nonnegative_stock": True,
                "mass_balance_passed": True,
                "transport_admitted": admitted,
                "diagnostic_only": result.diagnostic_only,
                "mass_balance_residual_m3": result.global_mass_balance_residual_m3,
                "mass_balance_tolerance_m3": result.numeric_mass_tolerance_m3,
            },
        )


def branching_hydraulic_runtime_state(
    *,
    stock: StockState,
    geometry: ReachHydraulicGeometry,
    time_id: str,
    state_ref: str,
) -> KernelState[BranchingHydraulicRuntimeState]:
    return KernelState(
        domain=BRANCHING_HYDRAULIC_RUNTIME_ADAPTER.domain,
        time_id=time_id,
        state_ref=state_ref,
        payload=BranchingHydraulicRuntimeState(stock=stock, geometry=geometry),
    )
