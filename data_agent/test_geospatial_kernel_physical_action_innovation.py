from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_action_innovation import (
    PhysicalActionInnovationParameters,
    fit_physical_action_innovation,
    physical_action_innovation_parameters_from_dict,
)

START = datetime(2024, 1, 1, tzinfo=UTC)


def _fit() -> PhysicalActionInnovationParameters:
    issue_times = tuple(START + timedelta(hours=index // 2) for index in range(20))
    horizons = tuple(1 if index % 2 == 0 else 3 for index in range(20))
    physical = tuple(50.0 + index for index in range(20))
    persistence = tuple(45.0 + index for index in range(20))
    innovations = tuple((-1.0) ** index * (1.0 + index / 10.0) for index in range(20))
    wwm = tuple(
        baseline + innovation for baseline, innovation in zip(persistence, innovations, strict=True)
    )
    observed = tuple(
        routed + 2.0 * innovation for routed, innovation in zip(physical, innovations, strict=True)
    )
    return fit_physical_action_innovation(
        issue_times=issue_times,
        forecast_horizons_hours=horizons,
        physical_discharge_m3s=physical,
        action_innovation_wwm_m3s=wwm,
        causal_persistence_m3s=persistence,
        observed_discharge_m3s=observed,
        supported_forecast_horizons_hours=(1, 3),
        source_system_id="source",
        source_physical_operator="sealed-router",
        source_physical_prediction_sha256="a" * 64,
        source_wwm_prediction_sha256="b" * 64,
        source_wwm_parameter_sha256="c" * 64,
        source_outcome_sha256="d" * 64,
        provenance_id="synthetic-physics-first-innovation",
    )


def test_physical_action_innovation_recovers_global_source_scale() -> None:
    parameters = _fit()

    assert parameters.innovation_scale_coefficient == pytest.approx(2.0)
    assert parameters.training_pair_count == 20
    assert parameters.supported_forecast_horizons_hours == (1, 3)
    assert parameters.admitted is False


def test_physical_action_innovation_adds_only_wwm_departure_from_persistence() -> None:
    step = _fit().correct(
        physical_target_m3s=100.0,
        action_innovation_wwm_target_m3s=90.0,
        causal_persistence_target_m3s=85.0,
        forecast_horizon_hours=3,
    )

    assert step.raw_action_innovation_m3s == pytest.approx(5.0)
    assert step.scaled_action_innovation_m3s == pytest.approx(10.0)
    assert step.corrected_prediction_m3s == pytest.approx(110.0)
    assert step.clipped is False


def test_physical_action_innovation_document_round_trips() -> None:
    original = _fit()

    loaded = physical_action_innovation_parameters_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()


def test_physical_action_innovation_loader_rejects_target_fit_claim() -> None:
    payload = deepcopy(_fit().as_dict())
    payload["target_outcomes_used_for_fit"] = True

    with pytest.raises(ValueError, match="document_claims_invalid"):
        physical_action_innovation_parameters_from_dict(payload)


def test_physical_action_innovation_loader_rejects_boolean_coefficient() -> None:
    payload = deepcopy(_fit().as_dict())
    payload["innovation_scale_coefficient"] = True

    with pytest.raises(ValueError, match="document_invalid"):
        physical_action_innovation_parameters_from_dict(payload)


def test_physical_action_innovation_rejects_invalid_forecast_inputs() -> None:
    with pytest.raises(ValueError, match="forecast_inputs_invalid"):
        _fit().correct(
            physical_target_m3s=-1.0,
            action_innovation_wwm_target_m3s=90.0,
            causal_persistence_target_m3s=85.0,
            forecast_horizon_hours=3,
        )
