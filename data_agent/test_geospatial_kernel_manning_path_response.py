from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    DirectedReachNetwork,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ReachHydraulicGeometry,
)
from data_agent.uwm.geospatial_kernel_v2.manning_path_response import (
    MANNING_PATH_RESPONSE_SCHEMA,
    ManningPathResponseDiagnostic,
)


def _network() -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="manning-path-test",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(2000.0, 1000.0, 1500.0),
        effective_lengths_m=(2000.0, 1000.0, 1500.0),
        action_entry_feature_ids=(10, 20),
        provenance_id="manning-path-test:network",
        evidence_level="derived",
        admitted=True,
    )


def _geometry() -> ReachHydraulicGeometry:
    return ReachHydraulicGeometry(
        feature_ids=(30, 10, 20),
        bottom_width_m=(10.0, 8.0, 6.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.002, 0.003, 0.004),
        manning_n=(0.035, 0.035, 0.035),
        provenance_id="manning-path-test:geometry",
        evidence_level="authoritative",
        admitted_as_hydraulic_geometry=True,
    )


def _diagnostic() -> ManningPathResponseDiagnostic:
    return ManningPathResponseDiagnostic(_network(), _geometry())


def _analyze(discharge: tuple[float, ...]):
    return _diagnostic().analyze(
        discharge,
        start_feature_id=10,
        end_feature_id=30,
        path_id="test:10-to-30",
        provenance_id="manning-path-test:state",
        evidence_level="candidate",
        outcome_calibrated=False,
    )


def test_manning_path_response_follows_directed_path_and_builds_prior() -> None:
    result = _analyze((20.0, 10.0, 30.0))

    assert result.feature_ids == (10, 30)
    assert result.total_effective_length_m == 3000.0
    assert result.total_travel_time_seconds == pytest.approx(
        sum(value.travel_time_seconds or 0.0 for value in result.reaches)
    )
    assert result.effective_celerity_mps == pytest.approx(
        3000.0 / result.total_travel_time_seconds
    )
    assert result.as_dict()["schema"] == MANNING_PATH_RESPONSE_SCHEMA
    assert result.as_dict()["admitted_as_flood_wave_lag"] is False

    prior = result.travel_time_prior()
    assert prior.quantity == "flood_wave_travel_time"
    assert prior.central_seconds == result.total_travel_time_seconds
    assert prior.state_dependent is True
    assert prior.outcome_calibrated is False
    assert prior.admitted_as_flood_wave_lag is False


def test_manning_path_response_is_state_dependent() -> None:
    low = _analyze((5.0, 5.0, 5.0))
    high = _analyze((50.0, 50.0, 50.0))

    assert low.total_travel_time_seconds is not None
    assert high.total_travel_time_seconds is not None
    assert high.total_travel_time_seconds < low.total_travel_time_seconds
    assert high.effective_celerity_mps > low.effective_celerity_mps


def test_manning_path_response_keeps_zero_flow_nonpropagating() -> None:
    result = _analyze((20.0, 0.0, 30.0))

    assert result.nonpropagating_feature_ids == (10,)
    assert result.finite_travel_time_available is False
    assert result.total_travel_time_seconds is None
    assert result.effective_celerity_mps is None
    assert result.reaches[0].travel_time_seconds is None
    assert result.as_dict()["finite_travel_time_available"] is False
    with pytest.raises(
        ValueError, match="manning_path_response_finite_travel_time_required"
    ):
        result.travel_time_prior()


def test_manning_path_response_rejects_non_downstream_target() -> None:
    with pytest.raises(
        ValueError, match="manning_path_response_target_not_downstream"
    ):
        _diagnostic().analyze(
            (20.0, 10.0, 30.0),
            start_feature_id=10,
            end_feature_id=20,
            path_id="invalid",
            provenance_id="manning-path-test:state",
            evidence_level="candidate",
            outcome_calibrated=False,
        )


def test_manning_path_response_rejects_axis_and_geometry_mismatch() -> None:
    with pytest.raises(
        ValueError, match="manning_path_response_discharge_axis_invalid"
    ):
        _analyze((1.0, 2.0))

    mismatched = ReachHydraulicGeometry(
        feature_ids=(10, 20, 30),
        bottom_width_m=(8.0, 6.0, 10.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.003, 0.004, 0.002),
        manning_n=(0.035, 0.035, 0.035),
        provenance_id="manning-path-test:mismatched",
        evidence_level="authoritative",
        admitted_as_hydraulic_geometry=True,
    )
    with pytest.raises(
        ValueError, match="manning_path_response_geometry_axis_mismatch"
    ):
        ManningPathResponseDiagnostic(_network(), mismatched)
