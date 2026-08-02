from __future__ import annotations

from data_agent.uwm.geospatial_kernel import GeospatialKernelRuntime, KernelAction
from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachHydraulicGeometry,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.runtime_adapter import (
    BRANCHING_HYDRAULIC_RUNTIME_ADAPTER,
    BranchingHydraulicFluxAction,
    BranchingHydraulicRuntimeAdapter,
    branching_hydraulic_runtime_state,
)


def _network() -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="runtime-test-y",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(1000.0, 800.0, 900.0),
        effective_lengths_m=(1000.0, 800.0, 900.0),
        action_entry_feature_ids=(10,),
        provenance_id="runtime-test:topology",
        evidence_level="derived",
        admitted=True,
    )


def _geometry() -> ReachHydraulicGeometry:
    return ReachHydraulicGeometry(
        feature_ids=(30, 10, 20),
        bottom_width_m=(10.0, 8.0, 9.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.001, 0.0015, 0.0012),
        manning_n=(0.04, 0.045, 0.042),
        provenance_id="runtime-test:geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _operator(*, admitted: bool = True) -> BranchingManningNetworkTransportOperator:
    return BranchingManningNetworkTransportOperator(
        _network(),
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=admitted,
            allow_unadmitted_components_for_diagnostics=not admitted,
        ),
    )


def _stock() -> StockState:
    return StockState(
        values=(8000.0, 5000.0, 6000.0),
        unit="m3",
        provenance_id="runtime-test:stock",
    )


def _flux() -> BranchingHydraulicFluxAction:
    return BranchingHydraulicFluxAction(
        action=ActionBoundaryFlux(
            values=(0.0, 2.0, 0.0),
            unit="m3 s-1",
            provenance_id="runtime-test:release",
        ),
        forcing=ForcingFlux(
            values=(1.0, 0.5, 0.25),
            unit="m3 s-1",
            provenance_id="runtime-test:forcing",
            modeled=True,
        ),
    )


def _execute(*, admitted: bool = True):
    operator = _operator(admitted=admitted)
    state = branching_hydraulic_runtime_state(
        stock=_stock(),
        geometry=_geometry(),
        time_id="2026-08-02T00:00:00Z",
        state_ref="runtime-test-state",
    )
    action = KernelAction(
        action_id="runtime-test-release",
        domain=BRANCHING_HYDRAULIC_RUNTIME_ADAPTER.domain,
        source_time="2026-08-02T00:00:00Z",
        target_time="2026-08-02T01:00:00Z",
        payload=_flux(),
    )
    direct = operator.step(
        _stock(),
        _geometry(),
        action=_flux().action,
        forcing=_flux().forcing,
    )
    result = GeospatialKernelRuntime(
        BranchingHydraulicRuntimeAdapter(operator, parameter_ref="runtime-test:fixed-config")
    ).step(state=state, action=action, context=None)
    return direct, result


def test_v2_runtime_adapter_is_bitwise_identical_to_direct_conservative_step() -> None:
    direct, result = _execute()

    assert result.candidate.payload.as_dict() == direct.as_dict()
    assert result.next_state.payload.stock == direct.next_stock
    assert result.next_state.payload.geometry == _geometry()
    assert result.projection.status == "admitted"
    assert result.projection.diagnostics["mass_balance_passed"] is True
    assert result.audit()["result"]["provenance"]["parameter_ref"] == ("runtime-test:fixed-config")


def test_v2_runtime_adapter_preserves_explicit_diagnostic_only_status() -> None:
    direct, result = _execute(admitted=False)

    assert direct.diagnostic_only is True
    assert result.projection.status == "projected"
    assert result.projection.violations == ("hydraulic_components_diagnostic_only",)
    assert result.projection.diagnostics["mass_balance_passed"] is True
