from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from data_agent.uwm.geospatial_kernel_v2.branching_kinematic_wave import (
    BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
    BranchingFiniteVolumeKinematicWaveOperator,
    BranchingKinematicWaveConfig,
)
from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    ReachHydraulicGeometry,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.instrumented_physical_rollout import (
    InstrumentedKinematicStepInput,
    InstrumentedManningStepInput,
    run_instrumented_kinematic_rollout,
    run_instrumented_manning_rollout,
)
from data_agent.uwm.geospatial_kernel_v2.internal_innovation_instrumentation import (
    InternalInnovationTelemetryConfig,
)

ISSUE = datetime(2026, 8, 1, tzinfo=UTC)


def _network() -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="instrumented-rollout-y",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(1000.0, 800.0, 900.0),
        effective_lengths_m=(1000.0, 800.0, 900.0),
        action_entry_feature_ids=(10, 20),
        provenance_id="instrumented-rollout:network",
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
        provenance_id="instrumented-rollout:geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _telemetry(operator_schema: str) -> InternalInnovationTelemetryConfig:
    return InternalInnovationTelemetryConfig(
        system_id="future-test-system",
        forecast_issue_time=ISSUE,
        operator_schema=operator_schema,
        provenance_id="instrumented-rollout:telemetry",
        evidence_level="derived",
        admitted=True,
    )


def test_manning_rollout_couples_predictions_and_internal_telemetry() -> None:
    operator = BranchingManningNetworkTransportOperator(
        _network(),
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    initial = StockState((8000.0, 5000.0, 6000.0), "m3", "initial")
    steps = tuple(
        InstrumentedManningStepInput(
            support_start=ISSUE + timedelta(hours=index + 1),
            support_end=ISSUE + timedelta(hours=index + 2),
            inputs_available_at=ISSUE,
            action=ActionBoundaryFlux(
                (0.0, 1.0, 2.0),
                "m3 s-1",
                f"action:{index}",
            ),
        )
        for index in range(2)
    )

    result = run_instrumented_manning_rollout(
        operator,
        _geometry(),
        initial,
        steps,
        telemetry_config=_telemetry(BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA),
    )

    assert len(result.prediction_rows) == 2
    assert result.telemetry.step_count == 2
    assert result.telemetry.alignment_assertions["state_transition_continuity_verified"] is True
    assert result.prediction_rows[-1]["physical_outlet_mean_flow_m3s"] >= 0.0
    assert result.as_dict()["data_isolation"]["outcome_argument_accepted"] is False


def test_kinematic_rollout_uses_the_same_outcome_free_contract() -> None:
    operator = BranchingFiniteVolumeKinematicWaveOperator(
        _network(),
        _geometry(),
        BranchingKinematicWaveConfig(
            timestep_seconds=3600.0,
            target_cell_length_m=500.0,
            operator_form_admitted=True,
        ),
    )
    initial = operator.discharge_state((3.0, 1.0, 2.0), provenance_id="initial")
    steps = (
        InstrumentedKinematicStepInput(
            support_start=ISSUE + timedelta(hours=1),
            support_end=ISSUE + timedelta(hours=2),
            inputs_available_at=ISSUE,
            next_state_provenance_id="kinematic:step:1",
            action=ActionBoundaryFlux(
                (0.0, 1.0, 2.0),
                "m3 s-1",
                "action:0",
            ),
        ),
    )

    result = run_instrumented_kinematic_rollout(
        operator,
        initial,
        steps,
        telemetry_config=_telemetry(BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA),
    )

    assert result.telemetry.step_count == 1
    assert result.telemetry.source_steps_admitted is True
    assert result.prediction_rows[0]["diagnostic_only"] is False


def test_rollout_entrypoints_have_no_outcome_or_observation_parameter() -> None:
    for function in (
        run_instrumented_manning_rollout,
        run_instrumented_kinematic_rollout,
    ):
        parameters = inspect.signature(function).parameters
        assert "outcome" not in parameters
        assert "observation" not in parameters
        assert "outcome_path" not in parameters
