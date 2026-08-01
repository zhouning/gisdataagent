"""Source-only support gate for observed hydraulic-boundary perturbations."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

SCHEMA = "gwm.geospatial.observed_hydraulic_boundary_perturbation.v1"
SAMPLE_INTERVAL_MINUTES = 30
INCLUSIVE_WINDOW_SAMPLE_COUNT = 145
EVENT_SAMPLE_INDEX = 48
MAXIMUM_EXCURSION_SUPPORT_INTERVALS = 24
EXCURSION_CHANGE_FRACTION = 0.25
MINIMUM_ABSOLUTE_PRIMARY_CHANGE_M = 0.25
MINIMUM_EXCURSION_SUPPORT_INTERVALS = 6
MINIMUM_NORMALIZED_EXCURSION_INTERVALS = 6.0
MINIMUM_POST_EVENT_STANDARD_DEVIATION_M = 0.10
TARGET_FUNCTIONAL_SCHEMA = (
    "gwm.geospatial.first_persistent_downstream_departure.v1"
)
TARGET_INCLUSIVE_WINDOW_SAMPLE_COUNT = 97
TARGET_SOURCE_MARKER_INDEX = 48
TARGET_BASELINE_END_INDEX = 36
TARGET_MINIMUM_BASELINE_SAMPLE_COUNT = 30
TARGET_SEARCH_END_INDEX = 72
TARGET_MINIMUM_PERSISTENCE_INTERVALS = 3
TARGET_MAD_SCALE = 1.4826
TARGET_ROBUST_THRESHOLD_MULTIPLIER = 4.0
TARGET_RELATIVE_THRESHOLD_FRACTION = 0.05
TARGET_ABSOLUTE_THRESHOLD_M3S = 1.0


@dataclass(frozen=True)
class ObservedHydraulicBoundaryPerturbation:
    """Outcome-free evidence that a tailwater-stage change can support a test."""

    signed_primary_change_m: float
    pre_event_elevation_m: float
    perturbation_sign: int
    excursion_support_intervals: int
    normalized_excursion_intervals: float
    post_event_standard_deviation_m: float
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (
            self.signed_primary_change_m,
            self.pre_event_elevation_m,
            self.normalized_excursion_intervals,
            self.post_event_standard_deviation_m,
        )
        if (
            not all(math.isfinite(value) for value in values)
            or self.signed_primary_change_m == 0.0
            or self.perturbation_sign not in {-1, 1}
            or not 0
            <= self.excursion_support_intervals
            <= MAXIMUM_EXCURSION_SUPPORT_INTERVALS
            or self.normalized_excursion_intervals < 0.0
            or self.post_event_standard_deviation_m < 0.0
        ):
            raise ValueError("observed_hydraulic_boundary_perturbation_invalid")

    @property
    def absolute_primary_change_m(self) -> float:
        return abs(self.signed_primary_change_m)

    @property
    def direction(self) -> str:
        return "rise" if self.perturbation_sign > 0 else "fall"

    @property
    def blind_target_test_admissible(self) -> bool:
        return not self.rejection_reasons

    def require_blind_target_test_support(self) -> None:
        if self.rejection_reasons:
            raise ValueError(
                "hydraulic_boundary_perturbation_not_admissible:"
                + ",".join(self.rejection_reasons)
            )

    def require_release_action(self) -> None:
        raise ValueError(
            "hydraulic_boundary_observation_is_not_release_action"
        )

    def require_release_discharge(self) -> None:
        raise ValueError(
            "hydraulic_boundary_elevation_is_not_release_discharge"
        )

    def require_observed_downstream_response(self) -> None:
        raise ValueError(
            "hydraulic_boundary_input_support_is_not_downstream_response"
        )

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "hydraulic_boundary_source_marker_is_not_physical_travel_time"
        )

    def promote_to_runtime_transition(self) -> None:
        raise ValueError(
            "hydraulic_boundary_perturbation_runtime_transition_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "source_state_observation_only": True,
            "sample_interval_minutes": SAMPLE_INTERVAL_MINUTES,
            "source_event_time_support_offset_minutes": [-30, 0],
            "signed_primary_change_m": self.signed_primary_change_m,
            "absolute_primary_change_m": self.absolute_primary_change_m,
            "pre_event_elevation_m": self.pre_event_elevation_m,
            "perturbation_sign": self.perturbation_sign,
            "direction": self.direction,
            "excursion_threshold_fraction_of_primary_change": (
                EXCURSION_CHANGE_FRACTION
            ),
            "excursion_support_intervals": (
                self.excursion_support_intervals
            ),
            "normalized_excursion_intervals": (
                self.normalized_excursion_intervals
            ),
            "post_event_standard_deviation_m": (
                self.post_event_standard_deviation_m
            ),
            "thresholds": {
                "minimum_absolute_primary_change_m": (
                    MINIMUM_ABSOLUTE_PRIMARY_CHANGE_M
                ),
                "minimum_excursion_support_intervals": (
                    MINIMUM_EXCURSION_SUPPORT_INTERVALS
                ),
                "minimum_normalized_excursion_intervals": (
                    MINIMUM_NORMALIZED_EXCURSION_INTERVALS
                ),
                "minimum_post_event_standard_deviation_m": (
                    MINIMUM_POST_EVENT_STANDARD_DEVIATION_M
                ),
            },
            "rejection_reasons": list(self.rejection_reasons),
            "blind_target_test_admissible": (
                self.blind_target_test_admissible
            ),
            "release_action_admitted": False,
            "release_discharge_admitted": False,
            "observed_downstream_response_admitted": False,
            "physical_travel_time_admitted": False,
            "runtime_transition_admitted": False,
        }


def compile_observed_hydraulic_boundary_perturbation(
    inclusive_elevation_values_m: tuple[float, ...],
) -> ObservedHydraulicBoundaryPerturbation:
    """Compile the frozen source-only gate from one 72-hour stage window."""

    if (
        len(inclusive_elevation_values_m) != INCLUSIVE_WINDOW_SAMPLE_COUNT
        or any(
            not math.isfinite(value)
            for value in inclusive_elevation_values_m
        )
    ):
        raise ValueError(
            "hydraulic_boundary_145_finite_elevation_values_required"
        )
    values = inclusive_elevation_values_m
    before = float(values[EVENT_SAMPLE_INDEX - 1])
    primary_change = float(values[EVENT_SAMPLE_INDEX]) - before
    absolute_change = abs(primary_change)
    if absolute_change == 0.0:
        raise ValueError("hydraulic_boundary_nonzero_primary_change_required")

    sign = 1 if primary_change > 0.0 else -1
    threshold = EXCURSION_CHANGE_FRACTION * absolute_change
    support = 0
    normalized_excursion = 0.0
    for index in range(
        EVENT_SAMPLE_INDEX,
        EVENT_SAMPLE_INDEX + MAXIMUM_EXCURSION_SUPPORT_INTERVALS,
    ):
        signed_excursion = sign * (float(values[index]) - before)
        if signed_excursion < threshold:
            break
        support += 1
        normalized_excursion += signed_excursion / absolute_change

    diagnostic_values = values[
        EVENT_SAMPLE_INDEX - 1 :
        EVENT_SAMPLE_INDEX + MAXIMUM_EXCURSION_SUPPORT_INTERVALS
    ]
    post_event_standard_deviation = statistics.pstdev(diagnostic_values)
    reasons = []
    if absolute_change < MINIMUM_ABSOLUTE_PRIMARY_CHANGE_M:
        reasons.append("absolute_primary_change_below_0_25_m")
    if support < MINIMUM_EXCURSION_SUPPORT_INTERVALS:
        reasons.append("excursion_support_below_six_half_hours")
    if normalized_excursion < MINIMUM_NORMALIZED_EXCURSION_INTERVALS:
        reasons.append("normalized_excursion_below_six_intervals")
    if post_event_standard_deviation < MINIMUM_POST_EVENT_STANDARD_DEVIATION_M:
        reasons.append("post_event_standard_deviation_below_0_10_m")
    return ObservedHydraulicBoundaryPerturbation(
        primary_change,
        before,
        sign,
        support,
        normalized_excursion,
        post_event_standard_deviation,
        tuple(reasons),
    )


@dataclass(frozen=True)
class FirstPersistentDownstreamDeparture:
    """Frozen statistical target functional, not a physical arrival claim."""

    baseline_median_m3s: float
    baseline_mad_m3s: float
    departure_threshold_m3s: float
    first_departure_offset_minutes: int | None
    direction: str | None
    baseline_sample_count: int
    search_missing_sample_count: int

    def __post_init__(self) -> None:
        if (
            not all(
                math.isfinite(value) and value >= 0.0
                for value in (
                    self.baseline_mad_m3s,
                    self.departure_threshold_m3s,
                )
            )
            or not math.isfinite(self.baseline_median_m3s)
            or self.baseline_sample_count < TARGET_MINIMUM_BASELINE_SAMPLE_COUNT
            or self.search_missing_sample_count < 0
            or (
                self.first_departure_offset_minutes is None
                and self.direction is not None
            )
            or (
                self.first_departure_offset_minutes is not None
                and (
                    self.first_departure_offset_minutes
                    not in range(30, 721, 30)
                    or self.direction not in {"increase", "decrease"}
                )
            )
        ):
            raise ValueError("first_persistent_downstream_departure_invalid")

    @property
    def detected(self) -> bool:
        return self.first_departure_offset_minutes is not None

    def require_causal_release_response(self) -> None:
        raise ValueError(
            "persistent_downstream_departure_is_not_causal_release_response"
        )

    def require_physical_first_arrival(self) -> None:
        raise ValueError(
            "persistent_downstream_departure_is_not_physical_first_arrival"
        )

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "persistent_downstream_departure_is_not_physical_travel_time"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": TARGET_FUNCTIONAL_SCHEMA,
            "target_functional": "first_persistent_downstream_departure",
            "sample_interval_minutes": SAMPLE_INTERVAL_MINUTES,
            "baseline_support_offsets_hours": [-24.0, -6.5],
            "baseline_median_m3s": self.baseline_median_m3s,
            "baseline_mad_m3s": self.baseline_mad_m3s,
            "baseline_sample_count": self.baseline_sample_count,
            "minimum_baseline_sample_count": (
                TARGET_MINIMUM_BASELINE_SAMPLE_COUNT
            ),
            "departure_threshold_m3s": self.departure_threshold_m3s,
            "threshold_formula": (
                "max(4*1.4826*MAD,0.05*abs(baseline_median),1.0_m3s)"
            ),
            "search_offsets_minutes": [30, 720],
            "minimum_persistence_intervals": (
                TARGET_MINIMUM_PERSISTENCE_INTERVALS
            ),
            "missing_sample_policy": "break_run_without_filling",
            "search_missing_sample_count": self.search_missing_sample_count,
            "detected": self.detected,
            "first_departure_offset_minutes": (
                self.first_departure_offset_minutes
            ),
            "first_departure_time_support_offset_minutes": (
                [-30, 0] if self.detected else None
            ),
            "direction": self.direction,
            "causal_release_response_admitted": False,
            "physical_first_arrival_admitted": False,
            "physical_travel_time_admitted": False,
        }


def compile_first_persistent_downstream_departure(
    inclusive_discharge_values_m3s: tuple[float | None, ...],
) -> FirstPersistentDownstreamDeparture:
    """Apply the frozen target functional without filling missing samples."""

    if len(inclusive_discharge_values_m3s) != TARGET_INCLUSIVE_WINDOW_SAMPLE_COUNT:
        raise ValueError("downstream_departure_97_samples_required")
    if any(
        value is not None and not math.isfinite(value)
        for value in inclusive_discharge_values_m3s
    ):
        raise ValueError("downstream_departure_finite_or_missing_values_required")
    baseline = tuple(
        float(value)
        for value in inclusive_discharge_values_m3s[:TARGET_BASELINE_END_INDEX]
        if value is not None
    )
    if len(baseline) < TARGET_MINIMUM_BASELINE_SAMPLE_COUNT:
        raise ValueError("downstream_departure_baseline_support_insufficient")
    baseline_median = float(statistics.median(baseline))
    baseline_mad = float(
        statistics.median(abs(value - baseline_median) for value in baseline)
    )
    threshold = max(
        TARGET_ROBUST_THRESHOLD_MULTIPLIER * TARGET_MAD_SCALE * baseline_mad,
        TARGET_RELATIVE_THRESHOLD_FRACTION * abs(baseline_median),
        TARGET_ABSOLUTE_THRESHOLD_M3S,
    )
    run_start: int | None = None
    run_sign = 0
    run_length = 0
    first_offset: int | None = None
    direction: str | None = None
    missing_count = 0
    for index in range(TARGET_SOURCE_MARKER_INDEX + 1, TARGET_SEARCH_END_INDEX + 1):
        value = inclusive_discharge_values_m3s[index]
        if value is None:
            missing_count += 1
            run_start = None
            run_sign = 0
            run_length = 0
            continue
        departure = float(value) - baseline_median
        sign = 1 if departure >= threshold else -1 if departure <= -threshold else 0
        if sign == 0:
            run_start = None
            run_sign = 0
            run_length = 0
            continue
        if sign != run_sign:
            run_start = index
            run_sign = sign
            run_length = 1
        else:
            run_length += 1
        if run_length >= TARGET_MINIMUM_PERSISTENCE_INTERVALS:
            if run_start is None:
                raise ValueError("downstream_departure_run_state_invalid")
            first_offset = (
                run_start - TARGET_SOURCE_MARKER_INDEX
            ) * SAMPLE_INTERVAL_MINUTES
            direction = "increase" if run_sign > 0 else "decrease"
            break
    return FirstPersistentDownstreamDeparture(
        baseline_median,
        baseline_mad,
        threshold,
        first_offset,
        direction,
        len(baseline),
        missing_count,
    )
