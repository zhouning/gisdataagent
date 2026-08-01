"""System-scale adaptation for frozen action-innovation transitions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
    action_innovation_transition_parameters_from_dict,
)

SYSTEM_ACTION_SCALE_SCHEMA = "gwm.geospatial_kernel.system_action_scale.v1"
SCALE_NORMALIZED_PARAMETERS_SCHEMA = (
    "gwm.geospatial_kernel.scale_normalized_action_innovation_parameters.v1"
)
SCALE_NORMALIZED_FORMULA = (
    "q[t] = q[t-1] + target_action_scale*(source_drift/source_action_scale) + "
    "action_change_beta*(sum(w_lag*action[t-lag]) - "
    "sum(w_lag*action[t-1-lag])) + forcing_beta*nwm_lateral[t]"
)
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


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
class SystemActionScale:
    """A flow scale derived from action values without consulting outcomes."""

    network_id: str
    scale_m3s: float
    quantile: float
    sample_count: int
    sample_start: datetime
    sample_end: datetime
    source_artifact_sha256: str
    provenance_id: str
    evidence_level: str
    outcome_values_used: bool
    operational_vintage_verified: bool

    def __post_init__(self) -> None:
        scale = float(self.scale_m3s)
        quantile = float(self.quantile)
        if not isinstance(self.network_id, str) or not self.network_id.strip():
            raise ValueError("system_action_scale_network_id_required")
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError("system_action_scale_value_invalid")
        if not math.isfinite(quantile) or not 0.0 < quantile <= 1.0:
            raise ValueError("system_action_scale_quantile_invalid")
        if (
            not isinstance(self.sample_count, int)
            or isinstance(self.sample_count, bool)
            or self.sample_count < 8
        ):
            raise ValueError("system_action_scale_sample_count_invalid")
        if (
            not _aware(self.sample_start)
            or not _aware(self.sample_end)
            or self.sample_end < self.sample_start
        ):
            raise ValueError("system_action_scale_sample_window_invalid")
        expected_end = self.sample_start + timedelta(hours=self.sample_count - 1)
        if self.sample_end != expected_end:
            raise ValueError("system_action_scale_hourly_window_invalid")
        if not _valid_sha256(self.source_artifact_sha256):
            raise ValueError("system_action_scale_source_sha256_invalid")
        if not isinstance(self.provenance_id, str) or not self.provenance_id.strip():
            raise ValueError("system_action_scale_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("system_action_scale_evidence_level_invalid")
        if not isinstance(self.outcome_values_used, bool) or not isinstance(
            self.operational_vintage_verified, bool
        ):
            raise ValueError("system_action_scale_claim_flags_invalid")
        if self.outcome_values_used:
            raise ValueError("system_action_scale_outcome_values_forbidden")
        object.__setattr__(self, "scale_m3s", scale)
        object.__setattr__(self, "quantile", quantile)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SYSTEM_ACTION_SCALE_SCHEMA,
            "network_id": self.network_id,
            "scale_m3s": self.scale_m3s,
            "quantile": self.quantile,
            "sample_count": self.sample_count,
            "sample_start": self.sample_start.isoformat(),
            "sample_end": self.sample_end.isoformat(),
            "source_artifact_sha256": self.source_artifact_sha256,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "outcome_values_used": self.outcome_values_used,
            "operational_vintage_verified": self.operational_vintage_verified,
        }


def derive_system_action_scale(
    *,
    network_id: str,
    valid_times: tuple[datetime, ...],
    action_release_m3s: tuple[float, ...],
    quantile: float,
    minimum_scale_m3s: float,
    source_artifact_sha256: str,
    provenance_id: str,
    evidence_level: str,
    operational_vintage_verified: bool,
) -> SystemActionScale:
    """Derive one deterministic scale from an hourly, outcome-free action series."""

    times = tuple(valid_times)
    values = np.asarray(action_release_m3s, dtype=float)
    minimum = float(minimum_scale_m3s)
    if (
        len(times) < 8
        or values.shape != (len(times),)
        or any(not _aware(value) for value in times)
        or tuple(sorted(set(times))) != times
        or any(
            second - first != timedelta(hours=1)
            for first, second in zip(times, times[1:], strict=False)
        )
    ):
        raise ValueError("system_action_scale_hourly_axis_invalid")
    if (
        not np.isfinite(values).all()
        or bool((values < 0.0).any())
        or not math.isfinite(minimum)
        or minimum <= 0.0
    ):
        raise ValueError("system_action_scale_input_values_invalid")
    scale = max(
        minimum,
        float(np.quantile(values, float(quantile), method="linear")),
    )
    return SystemActionScale(
        network_id=network_id,
        scale_m3s=scale,
        quantile=quantile,
        sample_count=len(times),
        sample_start=times[0],
        sample_end=times[-1],
        source_artifact_sha256=source_artifact_sha256,
        provenance_id=provenance_id,
        evidence_level=evidence_level,
        outcome_values_used=False,
        operational_vintage_verified=operational_vintage_verified,
    )


@dataclass(frozen=True)
class ScaleNormalizedActionInnovationParameters:
    """Adapt only the source drift while preserving action and forcing responses."""

    base_target_parameters: ActionInnovationTransitionParameters
    source_action_scale: SystemActionScale
    target_action_scale: SystemActionScale
    source_parameter_sha256: str
    provenance_id: str
    admitted: bool

    def __post_init__(self) -> None:
        if not isinstance(
            self.base_target_parameters, ActionInnovationTransitionParameters
        ):
            raise TypeError("scale_normalized_base_target_parameters_required")
        if not isinstance(self.source_action_scale, SystemActionScale) or not isinstance(
            self.target_action_scale, SystemActionScale
        ):
            raise TypeError("scale_normalized_action_scales_required")
        if (
            self.base_target_parameters.support.network_id
            != self.target_action_scale.network_id
        ):
            raise ValueError("scale_normalized_target_network_identity_mismatch")
        if (
            self.source_action_scale.network_id
            == self.target_action_scale.network_id
        ):
            raise ValueError("scale_normalized_cross_system_scales_required")
        if not _valid_sha256(self.source_parameter_sha256):
            raise ValueError("scale_normalized_source_parameter_sha256_invalid")
        if not isinstance(self.provenance_id, str) or not self.provenance_id.strip():
            raise ValueError("scale_normalized_provenance_required")
        if not isinstance(self.admitted, bool):
            raise ValueError("scale_normalized_admitted_flag_invalid")
        if self.admitted or self.base_target_parameters.admitted:
            raise ValueError("scale_normalized_candidate_cannot_be_admitted")

    @property
    def scale_ratio(self) -> float:
        return self.target_action_scale.scale_m3s / self.source_action_scale.scale_m3s

    @property
    def normalized_baseline_drift_per_hour(self) -> float:
        return (
            self.base_target_parameters.baseline_drift_m3s_per_hour
            / self.source_action_scale.scale_m3s
        )

    @property
    def scaled_baseline_drift_m3s_per_hour(self) -> float:
        return self.normalized_baseline_drift_per_hour * self.target_action_scale.scale_m3s

    def runtime_parameters(self) -> ActionInnovationTransitionParameters:
        """Materialize the bounded base operator with the locked scaled drift."""

        return replace(
            self.base_target_parameters,
            baseline_drift_m3s_per_hour=self.scaled_baseline_drift_m3s_per_hour,
            provenance_id=(
                f"{self.provenance_id}|runtime-scale-ratio={self.scale_ratio:.17g}"
            ),
            evidence_level="candidate",
            admitted=False,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCALE_NORMALIZED_PARAMETERS_SCHEMA,
            "formula": SCALE_NORMALIZED_FORMULA,
            "base_target_parameters": self.base_target_parameters.as_dict(),
            "source_action_scale": self.source_action_scale.as_dict(),
            "target_action_scale": self.target_action_scale.as_dict(),
            "source_parameter_sha256": self.source_parameter_sha256,
            "scale_ratio": self.scale_ratio,
            "normalized_baseline_drift_per_hour": (
                self.normalized_baseline_drift_per_hour
            ),
            "scaled_baseline_drift_m3s_per_hour": (
                self.scaled_baseline_drift_m3s_per_hour
            ),
            "action_change_coefficient_unchanged": True,
            "forcing_coefficient_unchanged": True,
            "lag_support_unchanged": True,
            "target_outcome_values_used": False,
            "provenance_id": self.provenance_id,
            "admitted": self.admitted,
        }


def scale_normalized_action_innovation_parameters_from_dict(
    payload: Mapping[str, object],
) -> ScaleNormalizedActionInnovationParameters:
    if not isinstance(payload, Mapping):
        raise TypeError("scale_normalized_parameter_document_mapping_required")
    expected = {
        "schema",
        "formula",
        "base_target_parameters",
        "source_action_scale",
        "target_action_scale",
        "source_parameter_sha256",
        "scale_ratio",
        "normalized_baseline_drift_per_hour",
        "scaled_baseline_drift_m3s_per_hour",
        "action_change_coefficient_unchanged",
        "forcing_coefficient_unchanged",
        "lag_support_unchanged",
        "target_outcome_values_used",
        "provenance_id",
        "admitted",
    }
    if set(payload) != expected:
        raise ValueError("scale_normalized_parameter_document_fields_invalid")
    if (
        payload["schema"] != SCALE_NORMALIZED_PARAMETERS_SCHEMA
        or payload["formula"] != SCALE_NORMALIZED_FORMULA
        or payload["action_change_coefficient_unchanged"] is not True
        or payload["forcing_coefficient_unchanged"] is not True
        or payload["lag_support_unchanged"] is not True
        or payload["target_outcome_values_used"] is not False
        or payload["admitted"] is not False
    ):
        raise ValueError("scale_normalized_parameter_document_claims_invalid")
    parameters = ScaleNormalizedActionInnovationParameters(
        base_target_parameters=action_innovation_transition_parameters_from_dict(
            _mapping(payload["base_target_parameters"], "base_target_parameters")
        ),
        source_action_scale=_system_action_scale_from_dict(
            _mapping(payload["source_action_scale"], "source_action_scale")
        ),
        target_action_scale=_system_action_scale_from_dict(
            _mapping(payload["target_action_scale"], "target_action_scale")
        ),
        source_parameter_sha256=_text(
            payload["source_parameter_sha256"], "source_parameter_sha256"
        ),
        provenance_id=_text(payload["provenance_id"], "provenance_id"),
        admitted=False,
    )
    numeric = (
        ("scale_ratio", parameters.scale_ratio),
        (
            "normalized_baseline_drift_per_hour",
            parameters.normalized_baseline_drift_per_hour,
        ),
        (
            "scaled_baseline_drift_m3s_per_hour",
            parameters.scaled_baseline_drift_m3s_per_hour,
        ),
    )
    if any(
        not math.isclose(
            _number(payload[name], name), expected_value, rel_tol=0.0, abs_tol=1e-15
        )
        for name, expected_value in numeric
    ):
        raise ValueError("scale_normalized_parameter_document_derived_values_invalid")
    return parameters


def _system_action_scale_from_dict(
    payload: Mapping[str, object],
) -> SystemActionScale:
    expected = {
        "schema",
        "network_id",
        "scale_m3s",
        "quantile",
        "sample_count",
        "sample_start",
        "sample_end",
        "source_artifact_sha256",
        "provenance_id",
        "evidence_level",
        "outcome_values_used",
        "operational_vintage_verified",
    }
    if set(payload) != expected or payload["schema"] != SYSTEM_ACTION_SCALE_SCHEMA:
        raise ValueError("system_action_scale_document_invalid")
    if payload["outcome_values_used"] is not False:
        raise ValueError("system_action_scale_document_claims_invalid")
    verified = payload["operational_vintage_verified"]
    if not isinstance(verified, bool):
        raise ValueError("system_action_scale_document_claims_invalid")
    return SystemActionScale(
        network_id=_text(payload["network_id"], "scale_network_id"),
        scale_m3s=_number(payload["scale_m3s"], "scale_m3s"),
        quantile=_number(payload["quantile"], "scale_quantile"),
        sample_count=_integer(payload["sample_count"], "scale_sample_count"),
        sample_start=_time(payload["sample_start"], "scale_sample_start"),
        sample_end=_time(payload["sample_end"], "scale_sample_end"),
        source_artifact_sha256=_text(
            payload["source_artifact_sha256"], "scale_source_sha256"
        ),
        provenance_id=_text(payload["provenance_id"], "scale_provenance_id"),
        evidence_level=_text(payload["evidence_level"], "scale_evidence_level"),
        outcome_values_used=False,
        operational_vintage_verified=verified,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"scale_normalized_{name}_mapping_required")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"scale_normalized_{name}_text_invalid")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"scale_normalized_{name}_number_invalid")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"scale_normalized_{name}_number_invalid")
    return number


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"scale_normalized_{name}_integer_invalid")
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"scale_normalized_{name}_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"scale_normalized_{name}_time_invalid") from exc
    if not _aware(parsed):
        raise ValueError(f"scale_normalized_{name}_time_invalid")
    return parsed
