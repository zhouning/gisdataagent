"""Fail-closed shadow runtime for the frozen action-innovation candidate."""

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
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_FORMULA,
    ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
    ActionInnovationTransitionForecast,
    ActionInnovationTransitionParameters,
    CausalActionInnovationGeospatialKernel,
    action_innovation_transition_parameters_from_dict,
)

ISSUE_TIME_INPUT_ATTESTATION_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_issue_time_input_attestation.v1"
)
ACTION_INNOVATION_SHADOW_FORECAST_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_shadow_forecast.v1"
)
ACTION_INNOVATION_FREEZE_SCHEMA = (
    "gwm.geotransport.geospatial_kernel_action_innovation_candidate_freeze.v1"
)
REPO_ROOT = Path(__file__).resolve().parents[3]
SHADOW_RUNTIME_PATH = Path(__file__).resolve()
DEFAULT_FREEZE_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_candidate_freeze.json"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _valid_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class IssueTimeInputAttestation:
    """Bind each input vintage to what was available at one issue time."""

    issue_time: datetime
    network_id: str
    action_provenance_id: str
    action_plan_available_at: datetime
    forcing_provenance_id: str
    forcing_forecast_available_at: datetime
    outlet_state_provenance_id: str
    outlet_state_available_at: datetime
    verification_id: str

    def __post_init__(self) -> None:
        availability = (
            self.action_plan_available_at,
            self.forcing_forecast_available_at,
            self.outlet_state_available_at,
        )
        if not _aware(self.issue_time) or any(not _aware(value) for value in availability):
            raise ValueError("action_innovation_shadow_attestation_times_must_be_aware")
        if any(value > self.issue_time for value in availability):
            raise ValueError("action_innovation_shadow_input_not_available_at_issue")
        identifiers = (
            self.network_id,
            self.action_provenance_id,
            self.forcing_provenance_id,
            self.outlet_state_provenance_id,
            self.verification_id,
        )
        if any(not isinstance(value, str) or not value.strip() for value in identifiers):
            raise ValueError("action_innovation_shadow_attestation_identifiers_required")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ISSUE_TIME_INPUT_ATTESTATION_SCHEMA,
            "issue_time": self.issue_time.isoformat(),
            "network_id": self.network_id,
            "action_provenance_id": self.action_provenance_id,
            "action_plan_available_at": self.action_plan_available_at.isoformat(),
            "forcing_provenance_id": self.forcing_provenance_id,
            "forcing_forecast_available_at": self.forcing_forecast_available_at.isoformat(),
            "outlet_state_provenance_id": self.outlet_state_provenance_id,
            "outlet_state_available_at": self.outlet_state_available_at.isoformat(),
            "verification_id": self.verification_id,
        }


@dataclass(frozen=True)
class ActionInnovationShadowForecast:
    freeze_sha256: str
    parameter_sha256: str
    runtime_sha256: str
    input_attestation: IssueTimeInputAttestation
    forecast: ActionInnovationTransitionForecast

    def __post_init__(self) -> None:
        if not all(
            _valid_sha256(value)
            for value in (self.freeze_sha256, self.parameter_sha256, self.runtime_sha256)
        ):
            raise ValueError("action_innovation_shadow_artifact_hash_invalid")
        if not self.forecast.operational_vintages_verified or self.forecast.admitted:
            raise ValueError("action_innovation_shadow_forecast_claim_boundary_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_SHADOW_FORECAST_SCHEMA,
            "mode": "shadow",
            "network_id": self.input_attestation.network_id,
            "freeze_sha256": self.freeze_sha256,
            "parameter_sha256": self.parameter_sha256,
            "runtime_sha256": self.runtime_sha256,
            "input_attestation": self.input_attestation.as_dict(),
            "forecast": self.forecast.as_dict(),
            "operational_vintages_verified": True,
            "future_outlet_observations_used": False,
            "production_eligible": False,
            "runtime_default_enabled": False,
            "admitted": False,
        }


class FrozenActionInnovationShadowRuntime:
    """Execute the frozen candidate only behind an explicit shadow-mode switch."""

    def __init__(
        self,
        *,
        parameters: ActionInnovationTransitionParameters,
        freeze_sha256: str,
        parameter_sha256: str,
        runtime_sha256: str,
        enabled: bool = False,
    ) -> None:
        if not isinstance(parameters, ActionInnovationTransitionParameters):
            raise TypeError("action_innovation_shadow_parameters_required")
        if not isinstance(enabled, bool):
            raise TypeError("action_innovation_shadow_enabled_flag_must_be_boolean")
        if parameters.admitted or parameters.support.admitted:
            raise ValueError("action_innovation_shadow_cannot_load_admitted_parameters")
        if not all(
            _valid_sha256(value) for value in (freeze_sha256, parameter_sha256, runtime_sha256)
        ):
            raise ValueError("action_innovation_shadow_artifact_hash_invalid")
        self.parameters = parameters
        self.freeze_sha256 = freeze_sha256
        self.parameter_sha256 = parameter_sha256
        self.runtime_sha256 = runtime_sha256
        self.enabled = enabled
        self._kernel = CausalActionInnovationGeospatialKernel(parameters)

    def forecast(
        self,
        state: OutletTransitionState,
        inputs: HourlyActionForcingSeries,
        *,
        network_id: str,
        issue_time: datetime,
        target_valid_times: tuple[datetime, ...],
        input_attestation: IssueTimeInputAttestation,
    ) -> ActionInnovationShadowForecast:
        if not self.enabled:
            raise RuntimeError("action_innovation_shadow_runtime_disabled")
        if not isinstance(input_attestation, IssueTimeInputAttestation):
            raise TypeError("action_innovation_shadow_input_attestation_required")
        if (
            not isinstance(network_id, str)
            or not network_id.strip()
            or network_id != self.parameters.support.network_id
            or input_attestation.network_id != network_id
        ):
            raise ValueError("action_innovation_shadow_network_identity_mismatch")
        if input_attestation.issue_time != issue_time:
            raise ValueError("action_innovation_shadow_attestation_issue_mismatch")
        if not isinstance(state, OutletTransitionState) or not state.observed:
            raise ValueError("action_innovation_shadow_observed_outlet_state_required")
        if state.evidence_level != "authoritative":
            raise ValueError("action_innovation_shadow_authoritative_outlet_state_required")
        if not isinstance(inputs, HourlyActionForcingSeries):
            raise TypeError("action_innovation_shadow_hourly_inputs_required")
        if not inputs.action_plan_vintage_verified or not inputs.forcing_vintage_verified:
            raise ValueError("action_innovation_shadow_input_vintages_not_verified")
        if (
            input_attestation.action_provenance_id != inputs.action_provenance_id
            or input_attestation.forcing_provenance_id != inputs.forcing_provenance_id
            or input_attestation.outlet_state_provenance_id != state.provenance_id
            or input_attestation.outlet_state_available_at != state.available_at
        ):
            raise ValueError("action_innovation_shadow_attestation_provenance_mismatch")

        forecast = self._kernel.forecast(
            state,
            inputs,
            issue_time=issue_time,
            target_valid_times=target_valid_times,
        )
        if not forecast.operational_vintages_verified:
            raise ValueError("action_innovation_shadow_operational_boundary_not_verified")
        return ActionInnovationShadowForecast(
            freeze_sha256=self.freeze_sha256,
            parameter_sha256=self.parameter_sha256,
            runtime_sha256=self.runtime_sha256,
            input_attestation=input_attestation,
            forecast=forecast,
        )


def load_frozen_action_innovation_shadow_runtime(
    *,
    freeze_path: Path = DEFAULT_FREEZE_PATH,
    repository_root: Path = REPO_ROOT,
    enabled: bool = False,
) -> FrozenActionInnovationShadowRuntime:
    """Load and verify every artifact bound by the freeze before execution."""

    if not isinstance(enabled, bool):
        raise TypeError("action_innovation_shadow_enabled_flag_must_be_boolean")
    root = repository_root.resolve()
    freeze_body = freeze_path.read_bytes()
    freeze = json.loads(freeze_body)
    if not isinstance(freeze, Mapping):
        raise ValueError("action_innovation_shadow_freeze_document_required")
    _validate_freeze_contract(freeze)

    artifacts = freeze["candidate_artifacts"]
    verified = {name: _read_verified(descriptor, root) for name, descriptor in artifacts.items()}
    parameters = action_innovation_transition_parameters_from_dict(
        json.loads(verified["parameters"])
    )
    operator = freeze["operator_lock"]
    if (
        parameters.supported_forecast_horizons_hours != ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
        or parameters.as_dict()["formula"] != operator["formula"]
        or parameters.timestep_seconds != operator["timestep_seconds"]
        or parameters.training_data_start.isoformat() != operator["training_data_start"]
        or parameters.training_data_end.isoformat() != operator["training_data_end"]
        or parameters.training_sample_count != operator["training_sample_count"]
    ):
        raise ValueError("action_innovation_shadow_parameter_freeze_mismatch")

    return FrozenActionInnovationShadowRuntime(
        parameters=parameters,
        freeze_sha256=hashlib.sha256(freeze_body).hexdigest(),
        parameter_sha256=hashlib.sha256(verified["parameters"]).hexdigest(),
        runtime_sha256=hashlib.sha256(SHADOW_RUNTIME_PATH.read_bytes()).hexdigest(),
        enabled=enabled,
    )


def _validate_freeze_contract(freeze: Mapping[str, object]) -> None:
    operator = freeze.get("operator_lock") or {}
    causal = freeze.get("causal_runtime_contract") or {}
    inputs = freeze.get("issue_time_input_contract") or {}
    admission = freeze.get("admission_contract") or {}
    claims = freeze.get("claim_boundary") or {}
    artifacts = freeze.get("candidate_artifacts") or {}
    if (
        freeze.get("schema") != ACTION_INNOVATION_FREEZE_SCHEMA
        or freeze.get("status") != "frozen_bounded_candidate_not_admitted"
        or set(artifacts) != {"candidate_report", "core_operator", "evaluator", "parameters"}
        or operator.get("formula") != ACTION_INNOVATION_FORMULA
        or operator.get("supported_forecast_horizons_hours")
        != list(ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS)
        or operator.get("per_window_refit_permitted") is not False
        or operator.get("arbitrary_long_rollout_supported") is not False
        or causal.get("future_outlet_observations_permitted") is not False
        or causal.get("unregistered_horizon_policy") != "reject"
        or causal.get("parameter_or_support_refit_at_runtime") is not False
        or inputs.get("all_vintages_must_be_verified_for_operational_use") is not True
        or inputs.get("operational_forecast_claim_permitted") is not False
        or admission.get("runtime_default_enabled") is not False
        or admission.get("admission_gate_passed") is not False
        or admission.get("automatic_admission_from_posthoc_gate_results") is not False
        or claims.get("candidate_admitted") is not False
        or claims.get("runtime_default_enabled") is not False
    ):
        raise ValueError("action_innovation_shadow_freeze_contract_invalid")


def _read_verified(descriptor: object, repository_root: Path) -> bytes:
    if not isinstance(descriptor, Mapping) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise ValueError("action_innovation_shadow_artifact_descriptor_invalid")
    path = (repository_root / str(descriptor["path"])).resolve()
    try:
        path.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError("action_innovation_shadow_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("action_innovation_shadow_artifact_identity_mismatch")
    return body
