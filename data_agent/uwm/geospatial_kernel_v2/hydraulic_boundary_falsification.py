"""Post-outcome attribution for a frozen hydraulic-boundary target gate."""

from __future__ import annotations

import math
from dataclasses import dataclass

from data_agent.uwm.geospatial_kernel_v2 import (
    hydraulic_boundary_perturbation as perturbation,
)

SCHEMA = "gwm.geospatial.hydraulic_boundary_falsification_attribution.v1"


@dataclass(frozen=True)
class PersistentDepartureFalsificationAttribution:
    """Explain a frozen gate result without defining an alternative gate."""

    target_report: perturbation.FirstPersistentDownstreamDeparture
    robust_mad_threshold_component_m3s: float
    relative_threshold_component_m3s: float
    absolute_threshold_component_m3s: float
    dominant_threshold_component: str
    maximum_single_sample_departure_m3s: float
    maximum_single_sample_threshold_ratio: float
    strongest_persistent_start_offset_minutes: int | None
    strongest_persistent_direction: str | None
    strongest_persistent_magnitude_m3s: float | None
    strongest_persistent_threshold_ratio: float | None

    def __post_init__(self) -> None:
        finite_nonnegative = (
            self.robust_mad_threshold_component_m3s,
            self.relative_threshold_component_m3s,
            self.absolute_threshold_component_m3s,
            self.maximum_single_sample_departure_m3s,
            self.maximum_single_sample_threshold_ratio,
        )
        persistent = (
            self.strongest_persistent_start_offset_minutes,
            self.strongest_persistent_direction,
            self.strongest_persistent_magnitude_m3s,
            self.strongest_persistent_threshold_ratio,
        )
        if (
            not all(math.isfinite(value) and value >= 0.0 for value in finite_nonnegative)
            or self.dominant_threshold_component
            not in {"robust_mad", "relative_baseline", "absolute_floor"}
            or (
                all(value is None for value in persistent)
                and self.target_report.detected
            )
            or (
                any(value is None for value in persistent)
                and not all(value is None for value in persistent)
            )
            or (
                self.strongest_persistent_start_offset_minutes is not None
                and self.strongest_persistent_start_offset_minutes
                not in range(30, 661, 30)
            )
            or (
                self.strongest_persistent_direction is not None
                and self.strongest_persistent_direction
                not in {"increase", "decrease"}
            )
            or (
                self.strongest_persistent_magnitude_m3s is not None
                and (
                    not math.isfinite(self.strongest_persistent_magnitude_m3s)
                    or self.strongest_persistent_magnitude_m3s <= 0.0
                )
            )
            or (
                self.strongest_persistent_threshold_ratio is not None
                and (
                    not math.isfinite(self.strongest_persistent_threshold_ratio)
                    or self.strongest_persistent_threshold_ratio <= 0.0
                )
            )
        ):
            raise ValueError("persistent_departure_falsification_invalid")

    @property
    def frozen_gate_detected(self) -> bool:
        return self.target_report.detected

    @property
    def failure_mode(self) -> str:
        if self.frozen_gate_detected:
            return "frozen_gate_passed"
        if self.strongest_persistent_magnitude_m3s is None:
            return "no_complete_same_direction_triplet"
        return "persistent_departure_below_frozen_threshold"

    @property
    def persistent_threshold_shortfall_m3s(self) -> float | None:
        if self.strongest_persistent_magnitude_m3s is None:
            return None
        return max(
            0.0,
            self.target_report.departure_threshold_m3s
            - self.strongest_persistent_magnitude_m3s,
        )

    def require_alternative_detector(self) -> None:
        raise ValueError(
            "falsification_attribution_does_not_admit_alternative_detector"
        )

    def require_causal_response(self) -> None:
        raise ValueError(
            "falsification_attribution_does_not_admit_causal_response"
        )

    def require_physical_response_time(self) -> None:
        raise ValueError(
            "falsification_attribution_does_not_admit_physical_time"
        )

    def promote_to_runtime_operator(self) -> None:
        raise ValueError(
            "falsification_attribution_runtime_operator_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "role": "post_outcome_frozen_gate_falsification_attribution",
            "target_report": self.target_report.as_dict(),
            "threshold_components_m3s": {
                "robust_mad": self.robust_mad_threshold_component_m3s,
                "relative_baseline": self.relative_threshold_component_m3s,
                "absolute_floor": self.absolute_threshold_component_m3s,
            },
            "dominant_threshold_component": self.dominant_threshold_component,
            "maximum_single_sample_departure_m3s": (
                self.maximum_single_sample_departure_m3s
            ),
            "maximum_single_sample_threshold_ratio": (
                self.maximum_single_sample_threshold_ratio
            ),
            "strongest_persistent_start_offset_minutes": (
                self.strongest_persistent_start_offset_minutes
            ),
            "strongest_persistent_direction": (
                self.strongest_persistent_direction
            ),
            "strongest_persistent_magnitude_m3s": (
                self.strongest_persistent_magnitude_m3s
            ),
            "strongest_persistent_threshold_ratio": (
                self.strongest_persistent_threshold_ratio
            ),
            "persistent_threshold_shortfall_m3s": (
                self.persistent_threshold_shortfall_m3s
            ),
            "frozen_gate_detected": self.frozen_gate_detected,
            "failure_mode": self.failure_mode,
            "missing_values_filled": False,
            "alternative_threshold_or_detector_admitted": False,
            "causal_response_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        }


def compile_persistent_departure_falsification(
    inclusive_discharge_values_m3s: tuple[float | None, ...],
) -> PersistentDepartureFalsificationAttribution:
    """Attribute the frozen detector result on its original search support."""

    report = perturbation.compile_first_persistent_downstream_departure(
        inclusive_discharge_values_m3s
    )
    robust = (
        perturbation.TARGET_ROBUST_THRESHOLD_MULTIPLIER
        * perturbation.TARGET_MAD_SCALE
        * report.baseline_mad_m3s
    )
    relative = (
        perturbation.TARGET_RELATIVE_THRESHOLD_FRACTION
        * abs(report.baseline_median_m3s)
    )
    absolute = perturbation.TARGET_ABSOLUTE_THRESHOLD_M3S
    components = {
        "robust_mad": robust,
        "relative_baseline": relative,
        "absolute_floor": absolute,
    }
    dominant = max(components, key=components.__getitem__)
    if abs(components[dominant] - report.departure_threshold_m3s) > 1e-12:
        raise ValueError("persistent_departure_threshold_decomposition_invalid")

    search_start = perturbation.TARGET_SOURCE_MARKER_INDEX + 1
    search_end = perturbation.TARGET_SEARCH_END_INDEX
    departures = tuple(
        None if value is None else float(value) - report.baseline_median_m3s
        for value in inclusive_discharge_values_m3s[
            search_start : search_end + 1
        ]
    )
    real_departures = tuple(abs(value) for value in departures if value is not None)
    maximum_single = max(real_departures, default=0.0)
    best_start: int | None = None
    best_direction: str | None = None
    best_magnitude: float | None = None
    for local_start in range(
        len(departures) - perturbation.TARGET_MINIMUM_PERSISTENCE_INTERVALS + 1
    ):
        window = departures[
            local_start :
            local_start + perturbation.TARGET_MINIMUM_PERSISTENCE_INTERVALS
        ]
        if any(value is None or value == 0.0 for value in window):
            continue
        values = tuple(float(value) for value in window if value is not None)
        signs = {1 if value > 0.0 else -1 for value in values}
        if len(signs) != 1:
            continue
        magnitude = min(abs(value) for value in values)
        if best_magnitude is None or magnitude > best_magnitude:
            best_start = local_start
            best_direction = "increase" if signs == {1} else "decrease"
            best_magnitude = magnitude
    best_offset = None if best_start is None else (best_start + 1) * 30
    best_ratio = (
        None
        if best_magnitude is None
        else best_magnitude / report.departure_threshold_m3s
    )
    computed_detected = best_ratio is not None and best_ratio >= 1.0
    if computed_detected != report.detected:
        raise ValueError("persistent_departure_falsification_detector_mismatch")
    return PersistentDepartureFalsificationAttribution(
        report,
        robust,
        relative,
        absolute,
        dominant,
        maximum_single,
        maximum_single / report.departure_threshold_m3s,
        best_offset,
        best_direction,
        best_magnitude,
        best_ratio,
    )
