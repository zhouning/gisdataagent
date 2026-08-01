from datetime import datetime, timedelta, timezone

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    AutoregressiveLogBoundaryParameters,
    CausalAutoregressiveLogBoundaryHydrograph,
    CausalDischargeObservation,
)


UTC = timezone.utc


def _parameters() -> AutoregressiveLogBoundaryParameters:
    return AutoregressiveLogBoundaryParameters(
        feature_id=101,
        intercept=0.01,
        lag1_coefficient=1.4,
        lag2_coefficient=-0.5,
        timestep_seconds=3600,
        maximum_discharge_m3s=10_000.0,
        training_data_start=datetime(2020, 1, 1, tzinfo=UTC),
        training_data_end=datetime(2020, 12, 1, tzinfo=UTC),
        provenance_id="synthetic-boundary-fit",
        evidence_level="candidate",
        admitted=False,
        outlet_target_calibrated=False,
    )


def _observation(valid_at: datetime, value: float) -> CausalDischargeObservation:
    return CausalDischargeObservation(
        feature_id=101,
        discharge_m3s=value,
        valid_at=valid_at,
        available_at=valid_at + timedelta(hours=1),
        quality_status="approved",
        provenance_id=f"synthetic:{valid_at.isoformat()}",
        evidence_level="candidate",
    )


def test_boundary_hydrograph_is_causal_recursive_and_bounded() -> None:
    issue = datetime(2021, 1, 1, 3, tzinfo=UTC)
    observations = (
        _observation(issue - timedelta(hours=3), 20.0),
        _observation(issue - timedelta(hours=2), 30.0),
        _observation(issue + timedelta(hours=1), 9999.0),
    )
    targets = tuple(issue + timedelta(hours=value) for value in range(1, 5))
    result = CausalAutoregressiveLogBoundaryHydrograph(_parameters()).forecast(
        observations,
        issue_time=issue,
        target_valid_times=targets,
    )
    assert len(result.discharge_m3s) == 4
    assert all(0.0 <= value <= 10_000.0 for value in result.discharge_m3s)
    assert result.latest_observation_valid_at == issue - timedelta(hours=2)
    assert result.future_observations_used is False
    assert result.admitted is False


def test_boundary_hydrograph_rejects_unstable_or_outlet_calibrated_parameters() -> None:
    values = _parameters().__dict__
    with pytest.raises(ValueError, match="stationary"):
        AutoregressiveLogBoundaryParameters(
            **{**values, "lag1_coefficient": 1.5, "lag2_coefficient": 0.2}
        )
    with pytest.raises(ValueError, match="outlet_target_calibration_forbidden"):
        AutoregressiveLogBoundaryParameters(
            **{**values, "outlet_target_calibrated": True}
        )


def test_boundary_hydrograph_rejects_future_training_and_gapped_history() -> None:
    issue = datetime(2021, 1, 1, 3, tzinfo=UTC)
    target = (issue + timedelta(hours=1),)
    future_training = AutoregressiveLogBoundaryParameters(
        **{
            **_parameters().__dict__,
            "training_data_end": issue,
        }
    )
    with pytest.raises(ValueError, match="training_must_precede"):
        CausalAutoregressiveLogBoundaryHydrograph(future_training).forecast(
            (
                _observation(issue - timedelta(hours=3), 20.0),
                _observation(issue - timedelta(hours=2), 30.0),
            ),
            issue_time=issue,
            target_valid_times=target,
        )
    with pytest.raises(ValueError, match="latest_history_must_be_consecutive"):
        CausalAutoregressiveLogBoundaryHydrograph(_parameters()).forecast(
            (
                _observation(issue - timedelta(hours=4), 20.0),
                _observation(issue - timedelta(hours=2), 30.0),
            ),
            issue_time=issue,
            target_valid_times=target,
        )
