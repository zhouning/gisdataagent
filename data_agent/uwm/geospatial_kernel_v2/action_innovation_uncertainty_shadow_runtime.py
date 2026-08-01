"""Fail-closed shadow runtime for the frozen action-innovation uncertainty candidate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    REPO_ROOT,
    ActionInnovationShadowForecast,
    FrozenActionInnovationShadowRuntime,
    IssueTimeInputAttestation,
    load_frozen_action_innovation_shadow_runtime,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty import (
    ACTION_INNOVATION_UNCERTAINTY_METHOD,
    HorizonResidualEnvelopeForecast,
    HorizonResidualEnvelopeParameters,
    apply_horizon_residual_envelope,
    horizon_residual_envelope_parameters_from_dict,
)

ACTION_INNOVATION_UNCERTAINTY_FREEZE_SCHEMA = (
    "gwm.geotransport.geospatial_kernel_action_innovation_uncertainty_freeze.v1"
)
ACTION_INNOVATION_UNCERTAINTY_SHADOW_FORECAST_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_uncertainty_shadow_forecast.v1"
)
UNCERTAINTY_SHADOW_RUNTIME_PATH = Path(__file__).resolve()
UNCERTAINTY_OPERATOR_PATH = UNCERTAINTY_SHADOW_RUNTIME_PATH.with_name(
    "action_innovation_uncertainty.py"
)
DEFAULT_UNCERTAINTY_FREEZE_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_uncertainty_freeze.json"
)


@dataclass(frozen=True)
class ActionInnovationUncertaintyShadowForecast:
    uncertainty_freeze_sha256: str
    uncertainty_parameter_sha256: str
    uncertainty_runtime_sha256: str
    point_shadow_forecast: ActionInnovationShadowForecast
    interval_forecast: HorizonResidualEnvelopeForecast

    def __post_init__(self) -> None:
        identities = (
            self.uncertainty_freeze_sha256,
            self.uncertainty_parameter_sha256,
            self.uncertainty_runtime_sha256,
        )
        if not all(_valid_sha256(value) for value in identities):
            raise ValueError("action_innovation_uncertainty_shadow_artifact_hash_invalid")
        if self.interval_forecast.point_forecast is not self.point_shadow_forecast.forecast:
            raise ValueError("action_innovation_uncertainty_shadow_point_forecast_mismatch")
        if (
            self.point_shadow_forecast.forecast.admitted
            or self.interval_forecast.parameters.admitted
        ):
            raise ValueError("action_innovation_uncertainty_shadow_cannot_be_admitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_UNCERTAINTY_SHADOW_FORECAST_SCHEMA,
            "mode": "uncertainty_shadow",
            "network_id": self.point_shadow_forecast.input_attestation.network_id,
            "uncertainty_freeze_sha256": self.uncertainty_freeze_sha256,
            "uncertainty_parameter_sha256": self.uncertainty_parameter_sha256,
            "uncertainty_runtime_sha256": self.uncertainty_runtime_sha256,
            "point_shadow_forecast": self.point_shadow_forecast.as_dict(),
            "interval_forecast": self.interval_forecast.as_dict(),
            "calibration_outcomes_used": True,
            "time_series_exchangeability_claimed": False,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "production_eligible": False,
            "runtime_default_enabled": False,
            "admitted": False,
        }


class FrozenActionInnovationUncertaintyShadowRuntime:
    """Apply a frozen uncertainty envelope to the frozen point shadow forecast."""

    def __init__(
        self,
        *,
        point_runtime: FrozenActionInnovationShadowRuntime,
        uncertainty_parameters: HorizonResidualEnvelopeParameters,
        uncertainty_freeze_sha256: str,
        uncertainty_parameter_sha256: str,
        uncertainty_runtime_sha256: str,
        enabled: bool = False,
    ) -> None:
        if not isinstance(point_runtime, FrozenActionInnovationShadowRuntime):
            raise TypeError("action_innovation_uncertainty_shadow_point_runtime_required")
        if not isinstance(uncertainty_parameters, HorizonResidualEnvelopeParameters):
            raise TypeError("action_innovation_uncertainty_shadow_parameters_required")
        if not isinstance(enabled, bool):
            raise TypeError("action_innovation_uncertainty_shadow_enabled_flag_must_be_boolean")
        identities = (
            uncertainty_freeze_sha256,
            uncertainty_parameter_sha256,
            uncertainty_runtime_sha256,
        )
        if not all(_valid_sha256(value) for value in identities):
            raise ValueError("action_innovation_uncertainty_shadow_artifact_hash_invalid")
        if uncertainty_parameters.admitted or point_runtime.parameters.admitted:
            raise ValueError("action_innovation_uncertainty_shadow_cannot_load_admitted_parameters")
        if uncertainty_parameters.point_parameter_artifact_sha256 != point_runtime.parameter_sha256:
            raise ValueError("action_innovation_uncertainty_shadow_point_parameter_mismatch")
        if point_runtime.enabled is not enabled:
            raise ValueError("action_innovation_uncertainty_shadow_enablement_mismatch")
        self.point_runtime = point_runtime
        self.uncertainty_parameters = uncertainty_parameters
        self.uncertainty_freeze_sha256 = uncertainty_freeze_sha256
        self.uncertainty_parameter_sha256 = uncertainty_parameter_sha256
        self.uncertainty_runtime_sha256 = uncertainty_runtime_sha256
        self.enabled = enabled

    def forecast(
        self,
        state: OutletTransitionState,
        inputs: HourlyActionForcingSeries,
        *,
        network_id: str,
        issue_time: datetime,
        target_valid_times: tuple[datetime, ...],
        input_attestation: IssueTimeInputAttestation,
    ) -> ActionInnovationUncertaintyShadowForecast:
        if not self.enabled:
            raise RuntimeError("action_innovation_uncertainty_shadow_runtime_disabled")
        point = self.point_runtime.forecast(
            state,
            inputs,
            network_id=network_id,
            issue_time=issue_time,
            target_valid_times=target_valid_times,
            input_attestation=input_attestation,
        )
        interval = apply_horizon_residual_envelope(
            point.forecast,
            self.uncertainty_parameters,
        )
        return ActionInnovationUncertaintyShadowForecast(
            uncertainty_freeze_sha256=self.uncertainty_freeze_sha256,
            uncertainty_parameter_sha256=self.uncertainty_parameter_sha256,
            uncertainty_runtime_sha256=self.uncertainty_runtime_sha256,
            point_shadow_forecast=point,
            interval_forecast=interval,
        )


def load_frozen_action_innovation_uncertainty_shadow_runtime(
    *,
    uncertainty_freeze_path: Path = DEFAULT_UNCERTAINTY_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    enabled: bool = False,
) -> FrozenActionInnovationUncertaintyShadowRuntime:
    """Verify both freezes and every bound artifact before shadow execution."""

    if not isinstance(enabled, bool):
        raise TypeError("action_innovation_uncertainty_shadow_enabled_flag_must_be_boolean")
    root = repository_root.resolve()
    freeze_body = uncertainty_freeze_path.read_bytes()
    freeze = json.loads(freeze_body)
    if not isinstance(freeze, Mapping):
        raise ValueError("action_innovation_uncertainty_shadow_freeze_document_required")
    _validate_freeze_contract(freeze)

    artifacts = freeze["candidate_artifacts"]
    verified = {name: _read_verified(descriptor, root) for name, descriptor in artifacts.items()}
    if verified["uncertainty_operator"] != UNCERTAINTY_OPERATOR_PATH.read_bytes():
        raise ValueError("action_innovation_uncertainty_shadow_operator_identity_mismatch")

    parameters = horizon_residual_envelope_parameters_from_dict(
        json.loads(verified["uncertainty_parameters"])
    )
    lock = freeze["uncertainty_lock"]
    if (
        parameters.target_marginal_coverage != lock["target_marginal_coverage"]
        or list(parameters.horizons_hours) != lock["horizons_hours"]
        or list(parameters.absolute_error_radius_m3s) != lock["absolute_error_radius_m3s"]
        or list(parameters.calibration_sample_count) != lock["calibration_sample_count"]
        or parameters.calibration_target_start.isoformat() != lock["calibration_target_start"]
        or parameters.calibration_target_end.isoformat() != lock["calibration_target_end"]
        or parameters.point_parameter_artifact_sha256 != lock["point_parameter_artifact_sha256"]
    ):
        raise ValueError("action_innovation_uncertainty_shadow_parameter_freeze_mismatch")

    point_freeze_path = _descriptor_path(artifacts["point_candidate_freeze"], root)
    point_runtime = load_frozen_action_innovation_shadow_runtime(
        freeze_path=point_freeze_path,
        repository_root=root,
        enabled=enabled,
    )
    if (
        hashlib.sha256(verified["point_candidate_freeze"]).hexdigest()
        != point_runtime.freeze_sha256
    ):
        raise ValueError("action_innovation_uncertainty_shadow_point_freeze_mismatch")

    return FrozenActionInnovationUncertaintyShadowRuntime(
        point_runtime=point_runtime,
        uncertainty_parameters=parameters,
        uncertainty_freeze_sha256=hashlib.sha256(freeze_body).hexdigest(),
        uncertainty_parameter_sha256=hashlib.sha256(verified["uncertainty_parameters"]).hexdigest(),
        uncertainty_runtime_sha256=hashlib.sha256(
            UNCERTAINTY_SHADOW_RUNTIME_PATH.read_bytes()
        ).hexdigest(),
        enabled=enabled,
    )


def _validate_freeze_contract(freeze: Mapping[str, object]) -> None:
    artifacts = freeze.get("candidate_artifacts") or {}
    lock = freeze.get("uncertainty_lock") or {}
    statistical = freeze.get("statistical_claim_boundary") or {}
    prospective = freeze.get("prospective_evaluation_contract") or {}
    admission = freeze.get("admission_contract") or {}
    if (
        freeze.get("schema") != ACTION_INNOVATION_UNCERTAINTY_FREEZE_SCHEMA
        or freeze.get("status") != "frozen_uncertainty_candidate_not_admitted"
        or set(artifacts)
        != {
            "point_candidate_freeze",
            "uncertainty_report",
            "uncertainty_operator",
            "uncertainty_evaluator",
            "uncertainty_parameters",
            "development_intervals",
            "january_temporal_holdout_intervals",
            "february_d3_intervals",
        }
        or lock.get("method") != ACTION_INNOVATION_UNCERTAINTY_METHOD
        or lock.get("horizons_hours") != [1, 3, 6, 12]
        or lock.get("per_window_recalibration_permitted") is not False
        or lock.get("bounds_clipped_to_physical_discharge_range") is not True
        or statistical.get("calibration_outcomes_used") is not True
        or statistical.get("time_series_exchangeability_claimed") is not False
        or statistical.get("finite_sample_coverage_guarantee_claimed") is not False
        or statistical.get("conditional_coverage_guarantee_claimed") is not False
        or statistical.get("january_or_d3_coverage_counts_as_validation") is not False
        or prospective.get("same_point_candidate_freeze_required") is not True
        or prospective.get("same_uncertainty_parameters_required") is not True
        or prospective.get("fresh_prospective_window_required") is not True
        or prospective.get("multi_system_evaluation_required") is not True
        or admission.get("uncertainty_candidate_admitted") is not False
        or admission.get("operational_forecast_validated") is not False
        or admission.get("multi_system_uncertainty_validated") is not False
        or admission.get("runtime_default_enabled") is not False
        or admission.get("automatic_admission_from_posthoc_coverage") is not False
    ):
        raise ValueError("action_innovation_uncertainty_shadow_freeze_contract_invalid")


def _read_verified(descriptor: object, repository_root: Path) -> bytes:
    path = _descriptor_path(descriptor, repository_root)
    body = path.read_bytes()
    assert isinstance(descriptor, Mapping)
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("action_innovation_uncertainty_shadow_artifact_identity_mismatch")
    return body


def _descriptor_path(descriptor: object, repository_root: Path) -> Path:
    if not isinstance(descriptor, Mapping) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise ValueError("action_innovation_uncertainty_shadow_artifact_descriptor_invalid")
    path = (repository_root / str(descriptor["path"])).resolve()
    try:
        path.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError(
            "action_innovation_uncertainty_shadow_artifact_outside_repository"
        ) from exc
    return path


def _valid_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )
