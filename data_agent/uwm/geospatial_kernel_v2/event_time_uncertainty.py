"""Set-valued propagation of observation-support event-time uncertainty."""

from __future__ import annotations

import math
from dataclasses import dataclass

INTERVAL_SCHEMA = "gwm.geospatial.closed_temporal_interval.v1"
SUPPORT_SCHEMA = "gwm.geospatial.observation_support_uncertainty.v1"
ENVELOPE_SCHEMA = "gwm.geospatial.relative_event_delay_envelope.v1"
COMPATIBILITY_SCHEMA = (
    "gwm.geospatial.event_time_physics_compatibility.v1"
)
RECONCILIATION_SCHEMA = (
    "gwm.geospatial.event_time_uncertainty_reconciliation.v1"
)
PHYSICS_QUANTITIES = {
    "gravity_wave_time",
    "manning_kinematic_centroid_time",
    "advective_residence_time",
}


@dataclass(frozen=True)
class ClosedTemporalInterval:
    lower_hours: float
    upper_hours: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.lower_hours)
            or not math.isfinite(self.upper_hours)
            or self.lower_hours < 0.0
            or self.upper_hours < self.lower_hours
        ):
            raise ValueError("closed_temporal_interval_invalid")

    def intersection(
        self, other: ClosedTemporalInterval
    ) -> ClosedTemporalInterval | None:
        lower = max(self.lower_hours, other.lower_hours)
        upper = min(self.upper_hours, other.upper_hours)
        if lower > upper:
            return None
        return ClosedTemporalInterval(lower, upper)

    def minimum_gap_hours(self, other: ClosedTemporalInterval) -> float:
        if self.intersection(other) is not None:
            return 0.0
        if self.upper_hours < other.lower_hours:
            return other.lower_hours - self.upper_hours
        return self.lower_hours - other.upper_hours

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": INTERVAL_SCHEMA,
            "lower_hours": self.lower_hours,
            "upper_hours": self.upper_hours,
        }


@dataclass(frozen=True)
class ObservationSupportUncertainty:
    source_duration_hours: float
    target_duration_hours: float
    source_timestamp_position: str
    target_timestamp_position: str
    conservative_closure_used: bool

    def __post_init__(self) -> None:
        if (
            not all(
                math.isfinite(value) and value > 0.0
                for value in (
                    self.source_duration_hours,
                    self.target_duration_hours,
                )
            )
            or self.source_timestamp_position != "end"
            or self.target_timestamp_position != "end"
            or self.conservative_closure_used is not True
        ):
            raise ValueError("observation_support_uncertainty_invalid")

    @property
    def source_event_offset_hours(self) -> tuple[float, float]:
        return -self.source_duration_hours, 0.0

    @property
    def target_event_offset_hours(self) -> tuple[float, float]:
        return -self.target_duration_hours, 0.0

    def delay_interval_for_label_shift(
        self, lag_hours: int
    ) -> ClosedTemporalInterval:
        if (
            not isinstance(lag_hours, int)
            or isinstance(lag_hours, bool)
            or lag_hours < 0
        ):
            raise ValueError("nonnegative_integer_label_shift_required")
        return ClosedTemporalInterval(
            max(0.0, lag_hours - self.target_duration_hours),
            lag_hours + self.source_duration_hours,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SUPPORT_SCHEMA,
            "source_duration_hours": self.source_duration_hours,
            "target_duration_hours": self.target_duration_hours,
            "source_timestamp_position": self.source_timestamp_position,
            "target_timestamp_position": self.target_timestamp_position,
            "source_event_offset_hours": list(
                self.source_event_offset_hours
            ),
            "target_event_offset_hours": list(
                self.target_event_offset_hours
            ),
            "conservative_closure_used": self.conservative_closure_used,
            "delay_lower_formula": (
                "max(0,label_shift-target_duration)"
            ),
            "delay_upper_formula": "label_shift+source_duration",
        }


@dataclass(frozen=True)
class RelativeEventDelayEnvelope:
    relation_id: str
    path_id: str
    label_shifts_hours: tuple[int, ...]
    support_uncertainty: ObservationSupportUncertainty
    intervals: tuple[ClosedTemporalInterval, ...]
    provenance_id: str
    outcome_derived: bool

    def __post_init__(self) -> None:
        expected = _merge_intervals(
            tuple(
                self.support_uncertainty.delay_interval_for_label_shift(value)
                for value in self.label_shifts_hours
            )
        )
        if (
            not self.relation_id.strip()
            or not self.path_id.strip()
            or tuple(sorted(set(self.label_shifts_hours)))
            != self.label_shifts_hours
            or any(value < 0 for value in self.label_shifts_hours)
            or self.intervals != expected
            or not self.provenance_id.strip()
            or self.outcome_derived is not True
        ):
            raise ValueError("relative_event_delay_envelope_invalid")

    @property
    def nonempty(self) -> bool:
        return bool(self.intervals)

    def require_physical_event_delay(self) -> None:
        raise ValueError(
            "event_time_uncertainty_envelope_is_not_physical_delay"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ENVELOPE_SCHEMA,
            "relation_id": self.relation_id,
            "path_id": self.path_id,
            "label_shifts_hours": list(self.label_shifts_hours),
            "support_uncertainty": self.support_uncertainty.as_dict(),
            "relative_delay_intervals_hours": [
                [value.lower_hours, value.upper_hours]
                for value in self.intervals
            ],
            "nonempty": self.nonempty,
            "provenance_id": self.provenance_id,
            "outcome_derived": self.outcome_derived,
            "physical_event_delay_admitted": False,
        }


@dataclass(frozen=True)
class EventTimePhysicsCompatibility:
    empirical: RelativeEventDelayEnvelope
    physics_quantity: str
    physics_interval: ClosedTemporalInterval
    same_spatial_path: bool
    semantic_equivalence_admitted: bool
    candidate_physical_response_time_admitted: bool

    def __post_init__(self) -> None:
        if (
            self.physics_quantity not in PHYSICS_QUANTITIES
            or not isinstance(self.same_spatial_path, bool)
            or not isinstance(self.semantic_equivalence_admitted, bool)
            or not isinstance(
                self.candidate_physical_response_time_admitted, bool
            )
        ):
            raise ValueError("event_time_physics_compatibility_invalid")

    @property
    def overlapping_intervals(self) -> tuple[ClosedTemporalInterval, ...]:
        return _merge_intervals(
            tuple(
                intersection
                for interval in self.empirical.intervals
                if (
                    intersection := interval.intersection(
                        self.physics_interval
                    )
                )
                is not None
            )
        )

    @property
    def measurement_support_overlap(self) -> bool:
        return bool(self.overlapping_intervals)

    @property
    def minimum_separation_hours(self) -> float | None:
        if not self.empirical.intervals:
            return None
        return min(
            value.minimum_gap_hours(self.physics_interval)
            for value in self.empirical.intervals
        )

    @property
    def physical_comparison_admitted(self) -> bool:
        return (
            self.same_spatial_path
            and self.semantic_equivalence_admitted
            and self.candidate_physical_response_time_admitted
            and self.measurement_support_overlap
        )

    def require_physical_comparison(self) -> None:
        if not self.physical_comparison_admitted:
            raise ValueError(
                "event_time_uncertainty_physical_comparison_unadmitted"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": COMPATIBILITY_SCHEMA,
            "physics_quantity": self.physics_quantity,
            "physics_interval_hours": [
                self.physics_interval.lower_hours,
                self.physics_interval.upper_hours,
            ],
            "same_spatial_path": self.same_spatial_path,
            "semantic_equivalence_admitted": (
                self.semantic_equivalence_admitted
            ),
            "candidate_physical_response_time_admitted": (
                self.candidate_physical_response_time_admitted
            ),
            "measurement_support_overlap": self.measurement_support_overlap,
            "overlapping_intervals_hours": [
                [value.lower_hours, value.upper_hours]
                for value in self.overlapping_intervals
            ],
            "minimum_separation_hours": self.minimum_separation_hours,
            "physical_comparison_admitted": (
                self.physical_comparison_admitted
            ),
        }


@dataclass(frozen=True)
class EventTimeUncertaintyReconciliation:
    event_envelopes: tuple[RelativeEventDelayEnvelope, ...]
    empirical_union_envelope: RelativeEventDelayEnvelope
    compatibilities: tuple[EventTimePhysicsCompatibility, ...]
    original_common_empirical_support_admitted: bool

    def __post_init__(self) -> None:
        if (
            not self.event_envelopes
            or not self.compatibilities
            or any(
                value.empirical != self.empirical_union_envelope
                for value in self.compatibilities
            )
            or any(
                value.path_id != self.empirical_union_envelope.path_id
                for value in self.event_envelopes
            )
            or not isinstance(
                self.original_common_empirical_support_admitted, bool
            )
        ):
            raise ValueError("event_time_uncertainty_reconciliation_invalid")

    @property
    def all_events_have_nonempty_support(self) -> bool:
        return all(value.nonempty for value in self.event_envelopes)

    @property
    def common_event_delay_intervals(
        self,
    ) -> tuple[ClosedTemporalInterval, ...]:
        if not self.all_events_have_nonempty_support:
            return ()
        result = self.event_envelopes[0].intervals
        for envelope in self.event_envelopes[1:]:
            result = _intersect_interval_sets(result, envelope.intervals)
        return result

    @property
    def physical_response_time_admitted(self) -> bool:
        return (
            bool(self.common_event_delay_intervals)
            and any(
                value.physical_comparison_admitted
                for value in self.compatibilities
            )
        )

    def require_common_event_delay_intervals(
        self,
    ) -> tuple[ClosedTemporalInterval, ...]:
        if not self.common_event_delay_intervals:
            raise ValueError(
                "event_time_uncertainty_common_delay_unadmitted"
            )
        return self.common_event_delay_intervals

    def require_physical_response_time(self) -> None:
        if not self.physical_response_time_admitted:
            raise ValueError(
                "event_time_uncertainty_physical_response_unadmitted"
            )

    def promote_to_runtime_transition(self) -> None:
        raise ValueError(
            "event_time_uncertainty_runtime_transition_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": RECONCILIATION_SCHEMA,
            "event_envelopes": [
                value.as_dict() for value in self.event_envelopes
            ],
            "empirical_union_envelope": (
                self.empirical_union_envelope.as_dict()
            ),
            "compatibilities": [
                value.as_dict() for value in self.compatibilities
            ],
            "all_events_have_nonempty_support": (
                self.all_events_have_nonempty_support
            ),
            "common_event_delay_intervals_hours": [
                [value.lower_hours, value.upper_hours]
                for value in self.common_event_delay_intervals
            ],
            "original_common_empirical_support_admitted": (
                self.original_common_empirical_support_admitted
            ),
            "physical_response_time_admitted": (
                self.physical_response_time_admitted
            ),
            "runtime_transition_admitted": False,
        }


def compile_relative_event_delay_envelope(
    relation_id: str,
    path_id: str,
    label_shifts_hours: tuple[int, ...],
    support_uncertainty: ObservationSupportUncertainty,
    provenance_id: str,
) -> RelativeEventDelayEnvelope:
    intervals = _merge_intervals(
        tuple(
            support_uncertainty.delay_interval_for_label_shift(value)
            for value in label_shifts_hours
        )
    )
    return RelativeEventDelayEnvelope(
        relation_id,
        path_id,
        label_shifts_hours,
        support_uncertainty,
        intervals,
        provenance_id,
        True,
    )


def _merge_intervals(
    intervals: tuple[ClosedTemporalInterval, ...],
) -> tuple[ClosedTemporalInterval, ...]:
    if not intervals:
        return ()
    ordered = sorted(
        intervals, key=lambda value: (value.lower_hours, value.upper_hours)
    )
    result = [ordered[0]]
    for value in ordered[1:]:
        previous = result[-1]
        if value.lower_hours <= previous.upper_hours:
            result[-1] = ClosedTemporalInterval(
                previous.lower_hours,
                max(previous.upper_hours, value.upper_hours),
            )
        else:
            result.append(value)
    return tuple(result)


def _intersect_interval_sets(
    left: tuple[ClosedTemporalInterval, ...],
    right: tuple[ClosedTemporalInterval, ...],
) -> tuple[ClosedTemporalInterval, ...]:
    return _merge_intervals(
        tuple(
            intersection
            for first in left
            for second in right
            if (intersection := first.intersection(second)) is not None
        )
    )
