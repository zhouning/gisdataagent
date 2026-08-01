"""Typed reconciliation of empirical and physics temporal support."""

from __future__ import annotations

from dataclasses import dataclass
import math


DISCRETE_SCHEMA = "gwm.geospatial.discrete_temporal_support.v1"
CONTINUOUS_SCHEMA = "gwm.geospatial.continuous_temporal_support.v1"
COMPATIBILITY_SCHEMA = "gwm.geospatial.temporal_support_compatibility.v1"
RECONCILIATION_SCHEMA = (
    "gwm.geospatial.temporal_support_reconciliation.v1"
)
PHYSICS_QUANTITIES = {
    "gravity_wave_time",
    "manning_kinematic_centroid_time",
    "advective_residence_time",
}


@dataclass(frozen=True)
class DiscreteTemporalSupport:
    relation_id: str
    quantity: str
    supported_hours: tuple[int, ...]
    provenance_id: str
    outcome_derived: bool

    def __post_init__(self) -> None:
        if (
            not self.relation_id.strip()
            or self.quantity != "empirical_downstream_response_lag"
            or not self.supported_hours
            or tuple(sorted(set(self.supported_hours)))
            != self.supported_hours
            or any(value < 0 for value in self.supported_hours)
            or not self.provenance_id.strip()
            or self.outcome_derived is not True
        ):
            raise ValueError("discrete_temporal_support_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": DISCRETE_SCHEMA,
            "relation_id": self.relation_id,
            "quantity": self.quantity,
            "supported_hours": list(self.supported_hours),
            "provenance_id": self.provenance_id,
            "outcome_derived": self.outcome_derived,
            "physical_time_admitted": False,
        }


@dataclass(frozen=True)
class ContinuousTemporalSupport:
    support_id: str
    path_id: str
    quantity: str
    lower_hours: float
    central_hours: float
    upper_hours: float
    provenance_id: str
    state_dependent: bool
    outcome_calibrated: bool
    admitted_as_physical_time: bool

    def __post_init__(self) -> None:
        if (
            not self.support_id.strip()
            or not self.path_id.strip()
            or self.quantity not in PHYSICS_QUANTITIES
            or not all(
                math.isfinite(value) and value >= 0.0
                for value in (
                    self.lower_hours,
                    self.central_hours,
                    self.upper_hours,
                )
            )
            or not (
                self.lower_hours
                <= self.central_hours
                <= self.upper_hours
            )
            or not self.provenance_id.strip()
            or not isinstance(self.state_dependent, bool)
            or not isinstance(self.outcome_calibrated, bool)
            or not isinstance(self.admitted_as_physical_time, bool)
        ):
            raise ValueError("continuous_temporal_support_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONTINUOUS_SCHEMA,
            "support_id": self.support_id,
            "path_id": self.path_id,
            "quantity": self.quantity,
            "support_interval_hours": [
                self.lower_hours,
                self.upper_hours,
            ],
            "central_hours": self.central_hours,
            "provenance_id": self.provenance_id,
            "state_dependent": self.state_dependent,
            "outcome_calibrated": self.outcome_calibrated,
            "admitted_as_physical_time": self.admitted_as_physical_time,
        }


@dataclass(frozen=True)
class TemporalSupportCompatibility:
    empirical: DiscreteTemporalSupport
    physics: ContinuousTemporalSupport
    same_spatial_path: bool
    overlapping_empirical_hours: tuple[int, ...]
    minimum_separation_hours: float

    def __post_init__(self) -> None:
        expected_overlap = tuple(
            value
            for value in self.empirical.supported_hours
            if self.physics.lower_hours <= value <= self.physics.upper_hours
        )
        expected_gap = _minimum_gap_hours(
            self.empirical.supported_hours,
            self.physics.lower_hours,
            self.physics.upper_hours,
        )
        if (
            not isinstance(self.same_spatial_path, bool)
            or self.overlapping_empirical_hours != expected_overlap
            or not math.isfinite(self.minimum_separation_hours)
            or self.minimum_separation_hours < 0.0
            or abs(self.minimum_separation_hours - expected_gap) > 1e-12
        ):
            raise ValueError("temporal_support_compatibility_invalid")

    @property
    def numerical_overlap(self) -> bool:
        return bool(self.overlapping_empirical_hours)

    @property
    def physical_consistency_admitted(self) -> bool:
        return (
            self.same_spatial_path
            and self.physics.admitted_as_physical_time
            and self.numerical_overlap
        )

    def require_physical_consistency(self) -> tuple[int, ...]:
        if not self.physical_consistency_admitted:
            raise ValueError(
                "temporal_support_physical_consistency_unadmitted"
            )
        return self.overlapping_empirical_hours

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": COMPATIBILITY_SCHEMA,
            "empirical_support": self.empirical.as_dict(),
            "physics_support": self.physics.as_dict(),
            "same_spatial_path": self.same_spatial_path,
            "overlapping_empirical_hours": list(
                self.overlapping_empirical_hours
            ),
            "numerical_overlap": self.numerical_overlap,
            "minimum_separation_hours": self.minimum_separation_hours,
            "physical_consistency_admitted": (
                self.physical_consistency_admitted
            ),
        }


@dataclass(frozen=True)
class GeospatialTemporalSupportReconciliation:
    relation_id: str
    path_id: str
    empirical: DiscreteTemporalSupport
    compatibilities: tuple[TemporalSupportCompatibility, ...]
    all_event_common_empirical_support: bool

    def __post_init__(self) -> None:
        if (
            self.relation_id != self.empirical.relation_id
            or not self.path_id.strip()
            or not self.compatibilities
            or any(
                value.empirical != self.empirical
                or value.physics.path_id != self.path_id
                for value in self.compatibilities
            )
            or len(
                {value.physics.support_id for value in self.compatibilities}
            )
            != len(self.compatibilities)
            or not isinstance(self.all_event_common_empirical_support, bool)
        ):
            raise ValueError("geospatial_temporal_reconciliation_invalid")

    @property
    def physics_consistency_admitted(self) -> bool:
        return (
            self.all_event_common_empirical_support
            and any(
                value.physical_consistency_admitted
                for value in self.compatibilities
            )
        )

    def require_physics_consistent_support(self) -> tuple[int, ...]:
        if not self.physics_consistency_admitted:
            raise ValueError(
                "geospatial_temporal_physics_consistency_unadmitted"
            )
        return tuple(
            sorted(
                {
                    hour
                    for value in self.compatibilities
                    if value.physical_consistency_admitted
                    for hour in value.overlapping_empirical_hours
                }
            )
        )

    def promote_to_runtime_transition(self) -> None:
        raise ValueError(
            "geospatial_temporal_runtime_transition_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": RECONCILIATION_SCHEMA,
            "relation_id": self.relation_id,
            "path_id": self.path_id,
            "empirical_support": self.empirical.as_dict(),
            "compatibilities": [
                value.as_dict() for value in self.compatibilities
            ],
            "all_event_common_empirical_support": (
                self.all_event_common_empirical_support
            ),
            "physics_consistency_admitted": (
                self.physics_consistency_admitted
            ),
            "runtime_transition_admitted": False,
        }


def compile_temporal_support_compatibility(
    empirical: DiscreteTemporalSupport,
    physics: ContinuousTemporalSupport,
    *,
    same_spatial_path: bool,
) -> TemporalSupportCompatibility:
    overlap = tuple(
        value
        for value in empirical.supported_hours
        if physics.lower_hours <= value <= physics.upper_hours
    )
    return TemporalSupportCompatibility(
        empirical,
        physics,
        same_spatial_path,
        overlap,
        _minimum_gap_hours(
            empirical.supported_hours,
            physics.lower_hours,
            physics.upper_hours,
        ),
    )


def _minimum_gap_hours(
    discrete_hours: tuple[int, ...],
    lower_hours: float,
    upper_hours: float,
) -> float:
    return min(
        0.0
        if lower_hours <= value <= upper_hours
        else lower_hours - value
        if value < lower_hours
        else value - upper_hours
        for value in discrete_hours
    )
