from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    GeographicResponseSupport,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_scale_normalization import (
    ScaleNormalizedActionInnovationParameters,
    derive_system_action_scale,
    scale_normalized_action_innovation_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
SOURCE_SHA = "a" * 64
PARAMETER_SHA = "b" * 64


def _support(network_id: str, offset: int) -> GeographicResponseSupport:
    return GeographicResponseSupport(
        network_id=network_id,
        action_entry_feature_id=offset + 1,
        outlet_feature_id=offset + 3,
        path_feature_ids=(offset + 1, offset + 2, offset + 3),
        lag_hours=(5, 6, 7),
        lag_weights=(1.0 / 3.0,) * 3,
        provenance_id=f"{network_id}-path",
        evidence_level="candidate",
        admitted=False,
    )


def _scale(network_id: str, multiplier: float):
    times = tuple(START + timedelta(hours=value) for value in range(10))
    values = tuple(multiplier * float(value + 1) for value in range(10))
    return derive_system_action_scale(
        network_id=network_id,
        valid_times=times,
        action_release_m3s=values,
        quantile=0.9,
        minimum_scale_m3s=1.0,
        source_artifact_sha256=SOURCE_SHA,
        provenance_id=f"{network_id}-action-scale",
        evidence_level="candidate",
        operational_vintage_verified=False,
    )


def _parameters() -> ScaleNormalizedActionInnovationParameters:
    base = ActionInnovationTransitionParameters(
        support=_support("target-network", 100),
        baseline_drift_m3s_per_hour=-2.0,
        action_change_coefficient=0.3,
        forcing_coefficient=0.7,
        timestep_seconds=3600,
        supported_forecast_horizons_hours=(1, 3, 6, 12),
        maximum_discharge_m3s=1000.0,
        training_data_start=START,
        training_data_end=START + timedelta(hours=20),
        training_sample_count=160,
        provenance_id="source-fit-transferred-to-target-support",
        evidence_level="candidate",
        admitted=False,
        outcome_calibrated=True,
    )
    return ScaleNormalizedActionInnovationParameters(
        base_target_parameters=base,
        source_action_scale=_scale("source-network", 10.0),
        target_action_scale=_scale("target-network", 4.0),
        source_parameter_sha256=PARAMETER_SHA,
        provenance_id="scale-normalized-successor",
        admitted=False,
    )


def test_action_scale_is_deterministic_and_outcome_free() -> None:
    scale = _scale("source-network", 10.0)

    assert scale.scale_m3s == pytest.approx(91.0)
    assert scale.sample_count == 10
    assert scale.outcome_values_used is False
    assert scale.operational_vintage_verified is False


def test_scale_normalization_changes_only_baseline_drift() -> None:
    value = _parameters()
    runtime = value.runtime_parameters()

    assert value.scale_ratio == pytest.approx(0.4)
    assert runtime.baseline_drift_m3s_per_hour == pytest.approx(-0.8)
    assert runtime.action_change_coefficient == 0.3
    assert runtime.forcing_coefficient == 0.7
    assert runtime.support == value.base_target_parameters.support
    assert runtime.admitted is False


def test_scale_normalized_parameters_round_trip_without_refit() -> None:
    original = _parameters()

    loaded = scale_normalized_action_innovation_parameters_from_dict(
        original.as_dict()
    )

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()


def test_scale_normalized_parameters_reject_target_network_mismatch() -> None:
    original = _parameters()

    with pytest.raises(ValueError, match="target_network_identity_mismatch"):
        ScaleNormalizedActionInnovationParameters(
            base_target_parameters=original.base_target_parameters,
            source_action_scale=original.source_action_scale,
            target_action_scale=_scale("wrong-target", 4.0),
            source_parameter_sha256=PARAMETER_SHA,
            provenance_id="invalid-target-scale",
            admitted=False,
        )


def test_scale_normalized_loader_rejects_claim_inflation() -> None:
    payload = deepcopy(_parameters().as_dict())
    payload["target_outcome_values_used"] = True

    with pytest.raises(ValueError, match="document_claims_invalid"):
        scale_normalized_action_innovation_parameters_from_dict(payload)
