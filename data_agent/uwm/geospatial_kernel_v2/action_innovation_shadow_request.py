"""Strict request contract for frozen action-innovation shadow forecasts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HOURLY_ACTION_FORCING_SERIES_SCHEMA,
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    ISSUE_TIME_INPUT_ATTESTATION_SCHEMA,
    ActionInnovationShadowForecast,
    FrozenActionInnovationShadowRuntime,
    IssueTimeInputAttestation,
)

ACTION_INNOVATION_SHADOW_REQUEST_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_shadow_request.v1"
)
SHADOW_REQUEST_ADAPTER_PATH = Path(__file__).resolve()


@dataclass(frozen=True)
class ActionInnovationShadowRequest:
    request_id: str
    network_id: str
    shadow_only_acknowledged: bool
    issue_time: datetime
    target_valid_times: tuple[datetime, ...]
    outlet_state: OutletTransitionState
    hourly_inputs: HourlyActionForcingSeries
    input_attestation: IssueTimeInputAttestation

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("action_innovation_shadow_request_id_required")
        if not isinstance(self.network_id, str) or not self.network_id.strip():
            raise ValueError("action_innovation_shadow_network_id_required")
        if self.shadow_only_acknowledged is not True:
            raise ValueError("action_innovation_shadow_only_acknowledgement_required")
        if self.input_attestation.issue_time != self.issue_time:
            raise ValueError("action_innovation_shadow_request_attestation_issue_mismatch")
        if self.input_attestation.network_id != self.network_id:
            raise ValueError("action_innovation_shadow_request_attestation_network_mismatch")
        targets = tuple(self.target_valid_times)
        if not targets:
            raise ValueError("action_innovation_shadow_request_targets_required")
        object.__setattr__(self, "target_valid_times", targets)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_SHADOW_REQUEST_SCHEMA,
            "request_id": self.request_id,
            "network_id": self.network_id,
            "shadow_only_acknowledged": self.shadow_only_acknowledged,
            "issue_time": self.issue_time.isoformat(),
            "target_valid_times": [value.isoformat() for value in self.target_valid_times],
            "outlet_state": self.outlet_state.as_dict(),
            "hourly_inputs": self.hourly_inputs.as_dict(),
            "input_attestation": self.input_attestation.as_dict(),
        }

    def normalized_sha256(self) -> str:
        body = json.dumps(
            self.as_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def execute(
        self, runtime: FrozenActionInnovationShadowRuntime
    ) -> ActionInnovationShadowForecast:
        if not isinstance(runtime, FrozenActionInnovationShadowRuntime):
            raise TypeError("action_innovation_frozen_shadow_runtime_required")
        return runtime.forecast(
            self.outlet_state,
            self.hourly_inputs,
            network_id=self.network_id,
            issue_time=self.issue_time,
            target_valid_times=self.target_valid_times,
            input_attestation=self.input_attestation,
        )


def action_innovation_shadow_request_from_dict(
    payload: Mapping[str, object],
) -> ActionInnovationShadowRequest:
    if not isinstance(payload, Mapping):
        raise TypeError("action_innovation_shadow_request_document_mapping_required")
    expected = {
        "schema",
        "request_id",
        "network_id",
        "shadow_only_acknowledged",
        "issue_time",
        "target_valid_times",
        "outlet_state",
        "hourly_inputs",
        "input_attestation",
    }
    if set(payload) != expected:
        raise ValueError("action_innovation_shadow_request_document_fields_invalid")
    if payload["schema"] != ACTION_INNOVATION_SHADOW_REQUEST_SCHEMA:
        raise ValueError("action_innovation_shadow_request_document_schema_invalid")
    acknowledgement = payload["shadow_only_acknowledged"]
    if not isinstance(acknowledgement, bool):
        raise ValueError("action_innovation_shadow_request_acknowledgement_invalid")
    raw_targets = payload["target_valid_times"]
    if not isinstance(raw_targets, list):
        raise ValueError("action_innovation_shadow_request_targets_invalid")
    return ActionInnovationShadowRequest(
        request_id=_text(payload["request_id"], "request_id"),
        network_id=_text(payload["network_id"], "network_id"),
        shadow_only_acknowledged=acknowledgement,
        issue_time=_time(payload["issue_time"], "issue_time"),
        target_valid_times=tuple(_time(value, "target_valid_time") for value in raw_targets),
        outlet_state=_outlet_state(payload["outlet_state"]),
        hourly_inputs=_hourly_inputs(payload["hourly_inputs"]),
        input_attestation=_attestation(payload["input_attestation"]),
    )


def _outlet_state(value: object) -> OutletTransitionState:
    payload = _mapping(value, "outlet_state")
    expected = {
        "valid_at",
        "available_at",
        "discharge_m3s",
        "provenance_id",
        "evidence_level",
        "observed",
    }
    if set(payload) != expected:
        raise ValueError("action_innovation_shadow_outlet_state_fields_invalid")
    observed = payload["observed"]
    if not isinstance(observed, bool):
        raise ValueError("action_innovation_shadow_outlet_state_observed_invalid")
    return OutletTransitionState(
        valid_at=_time(payload["valid_at"], "outlet_state_valid_at"),
        available_at=_time(payload["available_at"], "outlet_state_available_at"),
        discharge_m3s=_number(payload["discharge_m3s"], "outlet_state_discharge"),
        provenance_id=_text(payload["provenance_id"], "outlet_state_provenance"),
        evidence_level=_text(payload["evidence_level"], "outlet_state_evidence_level"),
        observed=observed,
    )


def _hourly_inputs(value: object) -> HourlyActionForcingSeries:
    payload = _mapping(value, "hourly_inputs")
    expected = {
        "schema",
        "valid_times",
        "action_release_m3s",
        "nwm_lateral_inflow_m3s",
        "action_provenance_id",
        "forcing_provenance_id",
        "action_plan_vintage_verified",
        "forcing_vintage_verified",
    }
    if set(payload) != expected:
        raise ValueError("action_innovation_shadow_hourly_inputs_fields_invalid")
    if payload["schema"] != HOURLY_ACTION_FORCING_SERIES_SCHEMA:
        raise ValueError("action_innovation_shadow_hourly_inputs_schema_invalid")
    times = _list(payload["valid_times"], "hourly_input_times")
    action = _list(payload["action_release_m3s"], "hourly_input_action")
    forcing = _list(payload["nwm_lateral_inflow_m3s"], "hourly_input_forcing")
    action_verified = payload["action_plan_vintage_verified"]
    forcing_verified = payload["forcing_vintage_verified"]
    if not isinstance(action_verified, bool) or not isinstance(forcing_verified, bool):
        raise ValueError("action_innovation_shadow_hourly_input_vintage_flags_invalid")
    return HourlyActionForcingSeries(
        valid_times=tuple(_time(item, "hourly_input_valid_time") for item in times),
        action_release_m3s=tuple(_number(item, "hourly_input_action") for item in action),
        nwm_lateral_inflow_m3s=tuple(_number(item, "hourly_input_forcing") for item in forcing),
        action_provenance_id=_text(
            payload["action_provenance_id"], "hourly_input_action_provenance"
        ),
        forcing_provenance_id=_text(
            payload["forcing_provenance_id"], "hourly_input_forcing_provenance"
        ),
        action_plan_vintage_verified=action_verified,
        forcing_vintage_verified=forcing_verified,
    )


def _attestation(value: object) -> IssueTimeInputAttestation:
    payload = _mapping(value, "input_attestation")
    expected = {
        "schema",
        "issue_time",
        "network_id",
        "action_provenance_id",
        "action_plan_available_at",
        "forcing_provenance_id",
        "forcing_forecast_available_at",
        "outlet_state_provenance_id",
        "outlet_state_available_at",
        "verification_id",
    }
    if set(payload) != expected:
        raise ValueError("action_innovation_shadow_attestation_fields_invalid")
    if payload["schema"] != ISSUE_TIME_INPUT_ATTESTATION_SCHEMA:
        raise ValueError("action_innovation_shadow_attestation_schema_invalid")
    return IssueTimeInputAttestation(
        issue_time=_time(payload["issue_time"], "attestation_issue_time"),
        network_id=_text(payload["network_id"], "attestation_network_id"),
        action_provenance_id=_text(
            payload["action_provenance_id"], "attestation_action_provenance"
        ),
        action_plan_available_at=_time(
            payload["action_plan_available_at"], "attestation_action_available_at"
        ),
        forcing_provenance_id=_text(
            payload["forcing_provenance_id"], "attestation_forcing_provenance"
        ),
        forcing_forecast_available_at=_time(
            payload["forcing_forecast_available_at"],
            "attestation_forcing_available_at",
        ),
        outlet_state_provenance_id=_text(
            payload["outlet_state_provenance_id"], "attestation_state_provenance"
        ),
        outlet_state_available_at=_time(
            payload["outlet_state_available_at"], "attestation_state_available_at"
        ),
        verification_id=_text(payload["verification_id"], "attestation_verification_id"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"action_innovation_shadow_{name}_mapping_required")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"action_innovation_shadow_{name}_list_required")
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"action_innovation_shadow_{name}_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"action_innovation_shadow_{name}_time_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"action_innovation_shadow_{name}_time_invalid")
    return parsed


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"action_innovation_shadow_{name}_text_invalid")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"action_innovation_shadow_{name}_number_invalid")
    return float(value)
