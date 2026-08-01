"""Release-only support gate for blind transport-response experiments."""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics

import numpy as np


SCHEMA = "gwm.geospatial.release_excitation_identifiability.v1"
INCLUSIVE_WINDOW_HOURS = 73
STEP_INDEX = 24
LAG_CANDIDATES_HOURS = tuple(range(13))
REFERENCE_START_OFFSET_HOURS = -24
REFERENCE_END_OFFSET_HOURS = -6
MAXIMUM_EXCURSION_SUPPORT_HOURS = 12
EXCURSION_STEP_FRACTION = 0.25
MINIMUM_EXCURSION_SUPPORT_HOURS = 3
MINIMUM_NORMALIZED_VOLUME_STEP_HOURS = 3.0
MINIMUM_RELEASE_STANDARD_DEVIATION_M3S = 30.0
MAXIMUM_ABSOLUTE_LAG_AUTOCORRELATION = 0.97
MAXIMUM_LAG_DESIGN_CONDITION_NUMBER = 50.0


@dataclass(frozen=True)
class ReleaseExcitationIdentifiability:
    """Outcome-free diagnostics for whether a release event can excite a test."""

    signed_primary_step_m3s: float
    reference_release_m3s: float
    excitation_mode: str
    excitation_sign: int
    excursion_support_hours: int
    normalized_excitation_volume_step_hours: float
    release_standard_deviation_m3s: float
    max_absolute_lag_autocorrelation: float
    lag_design_condition_number: float
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.signed_primary_step_m3s == 0.0
            or self.excitation_mode not in {"onset", "recovery"}
            or self.excitation_sign not in {-1, 1}
            or not 0 <= self.excursion_support_hours <= 12
            or self.normalized_excitation_volume_step_hours < 0.0
            or self.release_standard_deviation_m3s < 0.0
            or self.max_absolute_lag_autocorrelation < 0.0
            or self.lag_design_condition_number < 1.0
        ):
            raise ValueError("release_excitation_identifiability_invalid")

    @property
    def blind_response_test_admissible(self) -> bool:
        return not self.rejection_reasons

    def require_blind_response_test_support(self) -> None:
        if self.rejection_reasons:
            raise ValueError(
                "release_excitation_support_not_admissible:"
                + ",".join(self.rejection_reasons)
            )

    def require_observed_downstream_response(self) -> None:
        raise ValueError(
            "release_excitation_input_support_is_not_observed_response"
        )

    def require_exact_lag_identification(self) -> None:
        raise ValueError(
            "release_excitation_input_support_does_not_identify_exact_lag"
        )

    def require_physical_travel_time(self) -> None:
        raise ValueError(
            "release_excitation_input_support_is_not_physical_travel_time"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "input_support_only": True,
            "signed_primary_step_m3s": self.signed_primary_step_m3s,
            "reference_release_m3s": self.reference_release_m3s,
            "reference_support_offsets_hours": [
                REFERENCE_START_OFFSET_HOURS,
                REFERENCE_END_OFFSET_HOURS,
            ],
            "excitation_mode": self.excitation_mode,
            "excitation_sign": self.excitation_sign,
            "excursion_threshold_fraction_of_primary_step": (
                EXCURSION_STEP_FRACTION
            ),
            "excursion_support_hours": self.excursion_support_hours,
            "normalized_excitation_volume_step_hours": (
                self.normalized_excitation_volume_step_hours
            ),
            "release_standard_deviation_m3s": (
                self.release_standard_deviation_m3s
            ),
            "max_absolute_lag_autocorrelation": (
                self.max_absolute_lag_autocorrelation
            ),
            "lag_design_condition_number": (
                self.lag_design_condition_number
            ),
            "thresholds": {
                "minimum_excursion_support_hours": (
                    MINIMUM_EXCURSION_SUPPORT_HOURS
                ),
                "minimum_normalized_volume_step_hours": (
                    MINIMUM_NORMALIZED_VOLUME_STEP_HOURS
                ),
                "minimum_release_standard_deviation_m3s": (
                    MINIMUM_RELEASE_STANDARD_DEVIATION_M3S
                ),
                "maximum_absolute_lag_autocorrelation": (
                    MAXIMUM_ABSOLUTE_LAG_AUTOCORRELATION
                ),
                "maximum_lag_design_condition_number": (
                    MAXIMUM_LAG_DESIGN_CONDITION_NUMBER
                ),
            },
            "rejection_reasons": list(self.rejection_reasons),
            "blind_response_test_admissible": (
                self.blind_response_test_admissible
            ),
            "observed_downstream_response_admitted": False,
            "exact_lag_identified": False,
            "physical_travel_time_admitted": False,
        }


def compile_release_excitation_identifiability(
    inclusive_release_values_m3s: tuple[float, ...],
) -> ReleaseExcitationIdentifiability:
    """Compile the frozen Stage 31 gate from one 73-value release window."""

    if (
        len(inclusive_release_values_m3s) != INCLUSIVE_WINDOW_HOURS
        or any(not math.isfinite(value) for value in inclusive_release_values_m3s)
    ):
        raise ValueError("release_excitation_73_finite_values_required")
    values = np.asarray(inclusive_release_values_m3s, dtype=float)
    primary_step = float(values[STEP_INDEX] - values[STEP_INDEX - 1])
    absolute_step = abs(primary_step)
    if absolute_step == 0.0:
        raise ValueError("release_excitation_nonzero_primary_step_required")

    reference = float(statistics.median(values[0:18].tolist()))
    previous_distance = abs(float(values[STEP_INDEX - 1]) - reference)
    current_distance = abs(float(values[STEP_INDEX]) - reference)
    onset = current_distance >= previous_distance
    mode = "onset" if onset else "recovery"
    departure = float(
        values[STEP_INDEX] if onset else values[STEP_INDEX - 1]
    )
    excitation_sign = 1 if departure - reference >= 0.0 else -1
    threshold = EXCURSION_STEP_FRACTION * absolute_step
    indexes = (
        range(STEP_INDEX, STEP_INDEX + MAXIMUM_EXCURSION_SUPPORT_HOURS)
        if onset
        else range(STEP_INDEX - 1, STEP_INDEX - 13, -1)
    )
    duration = 0
    volume = 0.0
    for index in indexes:
        signed_excursion = excitation_sign * (float(values[index]) - reference)
        if signed_excursion < threshold:
            break
        duration += 1
        volume += signed_excursion

    release = values[1:]
    release_std = float(np.std(release))
    autocorrelations = []
    for lag in LAG_CANDIDATES_HOURS[1:]:
        left = release[:-lag]
        right = release[lag:]
        if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
            autocorrelations.append(1.0)
        else:
            autocorrelations.append(
                abs(float(np.corrcoef(left, right)[0, 1]))
            )
    max_autocorrelation = max(autocorrelations)
    design = np.column_stack(
        [
            release[12 - lag : len(release) - lag]
            for lag in LAG_CANDIDATES_HOURS
        ]
    )
    column_std = np.std(design, axis=0)
    if np.any(column_std == 0.0):
        condition_number = math.inf
    else:
        standardized = (design - np.mean(design, axis=0)) / column_std
        singular_values = np.linalg.svd(
            standardized, compute_uv=False
        )
        condition_number = float(
            singular_values[0] / max(float(singular_values[-1]), 1e-12)
        )

    normalized_volume = volume / absolute_step
    reasons = []
    if duration < MINIMUM_EXCURSION_SUPPORT_HOURS:
        reasons.append("excursion_support_below_three_hours")
    if normalized_volume < MINIMUM_NORMALIZED_VOLUME_STEP_HOURS:
        reasons.append("normalized_excitation_volume_below_three_step_hours")
    if release_std < MINIMUM_RELEASE_STANDARD_DEVIATION_M3S:
        reasons.append("release_standard_deviation_below_30_m3s")
    if max_autocorrelation > MAXIMUM_ABSOLUTE_LAG_AUTOCORRELATION:
        reasons.append("absolute_lag_autocorrelation_above_0_97")
    if condition_number > MAXIMUM_LAG_DESIGN_CONDITION_NUMBER:
        reasons.append("lag_design_condition_number_above_50")
    return ReleaseExcitationIdentifiability(
        primary_step,
        reference,
        mode,
        excitation_sign,
        duration,
        normalized_volume,
        release_std,
        max_autocorrelation,
        condition_number,
        tuple(reasons),
    )
