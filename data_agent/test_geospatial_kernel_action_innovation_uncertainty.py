from copy import deepcopy
from datetime import timedelta

import pytest

from data_agent.test_geospatial_kernel_action_innovation_transition import (
    _fit,
    _inputs,
    _training_series,
)
from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    CausalActionInnovationGeospatialKernel,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty import (
    apply_horizon_residual_envelope,
    fit_horizon_residual_envelope,
    horizon_residual_envelope_parameters_from_dict,
)


def _envelope():
    point = _fit().parameters
    rows = []
    start = point.training_data_end + timedelta(hours=1)
    for index in range(120):
        for horizon in (1, 3, 6, 12):
            predicted = 100.0 + float(index % 5)
            signed_error = float((index % 20) - 10) * horizon / 10.0
            rows.append(
                (
                    start + timedelta(hours=index + horizon),
                    horizon,
                    predicted + signed_error,
                    predicted,
                )
            )
    return fit_horizon_residual_envelope(
        point_parameters=point,
        point_parameter_artifact_sha256="a" * 64,
        calibration_target_times=tuple(row[0] for row in rows),
        calibration_horizon_hours=tuple(row[1] for row in rows),
        observed_discharge_m3s=tuple(row[2] for row in rows),
        predicted_discharge_m3s=tuple(row[3] for row in rows),
        target_marginal_coverage=0.9,
        provenance_id="synthetic-post-training-residual-envelope",
    )


def test_fit_builds_horizon_specific_finite_sample_radii() -> None:
    parameters = _envelope()

    assert parameters.calibration_sample_count == (120, 120, 120, 120)
    assert parameters.absolute_error_radius_m3s == pytest.approx((0.9, 2.7, 5.4, 10.8))
    assert parameters.as_dict()["time_series_exchangeability_claimed"] is False
    assert parameters.as_dict()["finite_sample_coverage_guarantee_claimed"] is False
    assert parameters.admitted is False


def test_uncertainty_parameters_round_trip_without_claim_inflation() -> None:
    original = _envelope()

    loaded = horizon_residual_envelope_parameters_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()


def test_uncertainty_parameter_loader_rejects_coverage_claim() -> None:
    payload = deepcopy(_envelope().as_dict())
    payload["finite_sample_coverage_guarantee_claimed"] = True

    with pytest.raises(ValueError, match="document_claims_invalid"):
        horizon_residual_envelope_parameters_from_dict(payload)


def test_apply_envelope_wraps_matching_point_forecast() -> None:
    fit = _fit()
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue,
        discharge_m3s=_training_series()[1][-1],
        provenance_id="synthetic-latest-observation",
        evidence_level="candidate",
        observed=True,
    )
    point = CausalActionInnovationGeospatialKernel(fit.parameters).forecast(
        state,
        _inputs(),
        issue_time=issue,
        target_valid_times=tuple(issue + timedelta(hours=value) for value in (1, 3, 6, 12)),
    )

    result = apply_horizon_residual_envelope(point, _envelope())

    assert len(result.lower_discharge_m3s) == 4
    assert len(result.upper_discharge_m3s) == 4
    assert all(
        lower <= prediction <= upper
        for lower, prediction, upper in zip(
            result.lower_discharge_m3s,
            point.target_discharge_m3s,
            result.upper_discharge_m3s,
            strict=True,
        )
    )
    assert result.as_dict()["admitted"] is False


def test_calibration_must_follow_point_training_window() -> None:
    point = _fit().parameters
    times = tuple(point.training_data_end + timedelta(hours=index - 1) for index in range(400))

    with pytest.raises(ValueError, match="calibration_values_invalid"):
        fit_horizon_residual_envelope(
            point_parameters=point,
            point_parameter_artifact_sha256="a" * 64,
            calibration_target_times=times,
            calibration_horizon_hours=(1, 3, 6, 12) * 100,
            observed_discharge_m3s=(100.0,) * 400,
            predicted_discharge_m3s=(100.0,) * 400,
            target_marginal_coverage=0.9,
            provenance_id="invalid-overlapping-calibration",
        )
