"""Typed contracts for the Geospatial Kernel 2.0 operator algebra.

The algebra keeps topology (B), hierarchy (H), metric/measure (M), and
evidence (E) independent.  Dynamic fields are also separated by semantic
role so observations and controls cannot silently become physical forcing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import numpy as np


GEOCOMPLEX_SCHEMA = "gwm.geospatial_kernel.geo_complex.v1"
TEMPORAL_SUPPORT_SCHEMA = "gwm.geospatial_kernel.temporal_support.v1"
LINEAR_REFERENCED_PATH_SCHEMA = "gwm.geospatial_kernel.linear_referenced_path.v1"
TRAVEL_TIME_PRIOR_SCHEMA = "gwm.geospatial_kernel.travel_time_prior.v1"
REACH_HYDRAULIC_STATE_SCHEMA = "gwm.geospatial_kernel.reach_hydraulic_state.v1"
REACH_HYDRAULIC_GEOMETRY_SCHEMA = (
    "gwm.geospatial_kernel.reach_hydraulic_geometry.v1"
)
REACH_FORCING_SUPPORT_SCHEMA = (
    "gwm.geospatial_kernel.reach_forcing_spatial_support.v1"
)

_TEMPORAL_KINDS = {
    "instantaneous",
    "interval_mean",
    "interval_sum",
    "interval_sample_mean",
}
_TIMESTAMP_POSITIONS = {"instant", "beginning", "center", "end"}
_TRAVEL_TIME_QUANTITIES = {
    "advective_residence_time",
    "flood_wave_travel_time",
}
_PROPAGATION_SPEED_QUANTITIES = {
    "river_velocity_proxy",
    "flood_wave_celerity",
}
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _nonempty_unique(values: tuple[str, ...], name: str) -> None:
    if not values or any(not value.strip() for value in values):
        raise ValueError(f"{name}_must_be_nonempty")
    if len(values) != len(set(values)):
        raise ValueError(f"{name}_must_be_unique")


def _finite_tuple(values: Iterable[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or not np.isfinite(np.asarray(result, dtype=float)).all():
        raise ValueError(f"{name}_must_be_nonempty_and_finite")
    return result


@dataclass(frozen=True)
class TemporalSupport:
    """Time support of a value, kept separate from its timestamp label."""

    kind: str
    duration_seconds: float
    timestamp_position: str
    provenance_id: str
    evidence_level: str

    def __post_init__(self) -> None:
        if self.kind not in _TEMPORAL_KINDS:
            raise ValueError("unsupported_temporal_support_kind")
        if self.timestamp_position not in _TIMESTAMP_POSITIONS:
            raise ValueError("unsupported_temporal_timestamp_position")
        duration = float(self.duration_seconds)
        if not np.isfinite(duration) or duration < 0.0:
            raise ValueError("temporal_duration_must_be_finite_nonnegative")
        object.__setattr__(self, "duration_seconds", duration)
        if self.kind == "instantaneous":
            if duration != 0.0 or self.timestamp_position != "instant":
                raise ValueError("instantaneous_support_requires_zero_duration_instant_label")
        elif duration <= 0.0 or self.timestamp_position == "instant":
            raise ValueError("interval_support_requires_positive_duration_and_interval_label")
        if not self.provenance_id.strip():
            raise ValueError("temporal_support_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_temporal_support_evidence_level")

    def bounds(self, timestamp: datetime) -> tuple[datetime, datetime]:
        if timestamp.tzinfo is None:
            raise ValueError("temporal_support_timestamp_must_be_timezone_aware")
        duration = timedelta(seconds=self.duration_seconds)
        if self.timestamp_position == "instant":
            return timestamp, timestamp
        if self.timestamp_position == "beginning":
            return timestamp, timestamp + duration
        if self.timestamp_position == "center":
            half = duration / 2
            return timestamp - half, timestamp + half
        return timestamp - duration, timestamp

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": TEMPORAL_SUPPORT_SCHEMA,
            "kind": self.kind,
            "duration_seconds": self.duration_seconds,
            "timestamp_position": self.timestamp_position,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


@dataclass(frozen=True)
class LinearReferencedPath:
    """Directed path with entry/exit offsets measured along each feature."""

    path_id: str
    feature_ids: tuple[int, ...]
    full_lengths_m: tuple[float, ...]
    entry_offsets_m: tuple[float, ...]
    exit_offsets_m: tuple[float, ...]
    provenance_id: str
    evidence_level: str

    def __post_init__(self) -> None:
        if not self.path_id.strip() or not self.provenance_id.strip():
            raise ValueError("linear_path_identity_required")
        if not self.feature_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.feature_ids
        ):
            raise ValueError("linear_path_feature_ids_must_be_positive_integers")
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("linear_path_feature_ids_must_be_unique")
        lengths = _finite_tuple(self.full_lengths_m, "linear_path_full_lengths")
        entries = _finite_tuple(self.entry_offsets_m, "linear_path_entry_offsets")
        exits = _finite_tuple(self.exit_offsets_m, "linear_path_exit_offsets")
        count = len(self.feature_ids)
        if len(lengths) != count or len(entries) != count or len(exits) != count:
            raise ValueError("linear_path_measure_count_mismatch")
        for length, entry, exit_ in zip(lengths, entries, exits, strict=True):
            if length <= 0.0 or entry < 0.0 or exit_ < entry or exit_ > length + 1e-6:
                raise ValueError("linear_path_offsets_outside_feature")
        object.__setattr__(self, "full_lengths_m", lengths)
        object.__setattr__(self, "entry_offsets_m", entries)
        object.__setattr__(self, "exit_offsets_m", exits)
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_linear_path_evidence_level")

    @property
    def effective_lengths_m(self) -> tuple[float, ...]:
        return tuple(
            exit_ - entry
            for entry, exit_ in zip(
                self.entry_offsets_m, self.exit_offsets_m, strict=True
            )
        )

    @property
    def total_effective_length_m(self) -> float:
        return float(sum(self.effective_lengths_m))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": LINEAR_REFERENCED_PATH_SCHEMA,
            "path_id": self.path_id,
            "feature_ids": list(self.feature_ids),
            "full_lengths_m": list(self.full_lengths_m),
            "entry_offsets_m": list(self.entry_offsets_m),
            "exit_offsets_m": list(self.exit_offsets_m),
            "effective_lengths_m": list(self.effective_lengths_m),
            "total_effective_length_m": self.total_effective_length_m,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


@dataclass(frozen=True)
class TravelTimePrior:
    """A physical travel-time quantity that must not silently become a lag."""

    path_id: str
    quantity: str
    method: str
    lower_seconds: float
    central_seconds: float
    upper_seconds: float
    state_dependent: bool
    outcome_calibrated: bool
    admitted_as_flood_wave_lag: bool
    provenance_id: str
    evidence_level: str

    def __post_init__(self) -> None:
        if not self.path_id.strip() or not self.method.strip() or not self.provenance_id.strip():
            raise ValueError("travel_time_prior_identity_required")
        if self.quantity not in _TRAVEL_TIME_QUANTITIES:
            raise ValueError("unsupported_travel_time_quantity")
        bounds = np.asarray(
            [self.lower_seconds, self.central_seconds, self.upper_seconds],
            dtype=float,
        )
        if (
            not np.isfinite(bounds).all()
            or (bounds <= 0.0).any()
            or not bounds[0] <= bounds[1] <= bounds[2]
        ):
            raise ValueError("travel_time_prior_bounds_invalid")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_travel_time_prior_evidence_level")
        if self.admitted_as_flood_wave_lag and self.quantity != "flood_wave_travel_time":
            raise ValueError("only_flood_wave_quantity_may_be_admitted_as_lag")
        if self.admitted_as_flood_wave_lag and self.evidence_level == "candidate":
            raise ValueError("candidate_travel_time_cannot_be_admitted_as_lag")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": TRAVEL_TIME_PRIOR_SCHEMA,
            "path_id": self.path_id,
            "quantity": self.quantity,
            "method": self.method,
            "lower_seconds": float(self.lower_seconds),
            "central_seconds": float(self.central_seconds),
            "upper_seconds": float(self.upper_seconds),
            "state_dependent": self.state_dependent,
            "outcome_calibrated": self.outcome_calibrated,
            "admitted_as_flood_wave_lag": self.admitted_as_flood_wave_lag,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


@dataclass(frozen=True)
class ReachHydraulicState:
    """Per-reach propagation speed with an explicit physical quantity."""

    feature_ids: tuple[int, ...]
    propagation_speed_mps: tuple[float, ...]
    quantity: str
    provenance_id: str
    evidence_level: str
    admitted_as_flood_wave_celerity: bool

    def __post_init__(self) -> None:
        if not self.feature_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.feature_ids
        ):
            raise ValueError("reach_hydraulic_feature_ids_must_be_positive_integers")
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("reach_hydraulic_feature_ids_must_be_unique")
        speeds = _finite_tuple(
            self.propagation_speed_mps, "reach_hydraulic_propagation_speed"
        )
        if len(speeds) != len(self.feature_ids):
            raise ValueError("reach_hydraulic_speed_count_mismatch")
        if (np.asarray(speeds) <= 0.0).any():
            raise ValueError("reach_hydraulic_speed_must_be_positive")
        object.__setattr__(self, "propagation_speed_mps", speeds)
        if self.quantity not in _PROPAGATION_SPEED_QUANTITIES:
            raise ValueError("unsupported_reach_hydraulic_quantity")
        if not self.provenance_id.strip():
            raise ValueError("reach_hydraulic_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_reach_hydraulic_evidence_level")
        if (
            self.admitted_as_flood_wave_celerity
            and self.quantity != "flood_wave_celerity"
        ):
            raise ValueError("only_wave_celerity_quantity_may_be_admitted")
        if (
            self.admitted_as_flood_wave_celerity
            and self.evidence_level == "candidate"
        ):
            raise ValueError("candidate_hydraulics_cannot_be_admitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": REACH_HYDRAULIC_STATE_SCHEMA,
            "feature_ids": list(self.feature_ids),
            "propagation_speed_mps": list(self.propagation_speed_mps),
            "quantity": self.quantity,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted_as_flood_wave_celerity": (
                self.admitted_as_flood_wave_celerity
            ),
        }


@dataclass(frozen=True)
class ReachHydraulicGeometry:
    """Per-reach Manning geometry with explicit evidence admission."""

    feature_ids: tuple[int, ...]
    bottom_width_m: tuple[float, ...]
    side_slope_horizontal_per_vertical: tuple[float, ...]
    bed_slope: tuple[float, ...]
    manning_n: tuple[float, ...]
    provenance_id: str
    evidence_level: str
    admitted_as_hydraulic_geometry: bool

    def __post_init__(self) -> None:
        if not self.feature_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.feature_ids
        ):
            raise ValueError(
                "reach_hydraulic_geometry_feature_ids_must_be_positive_integers"
            )
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("reach_hydraulic_geometry_feature_ids_must_be_unique")
        fields = {
            "bottom_width": _finite_tuple(
                self.bottom_width_m, "reach_hydraulic_geometry_bottom_width"
            ),
            "side_slope": _finite_tuple(
                self.side_slope_horizontal_per_vertical,
                "reach_hydraulic_geometry_side_slope",
            ),
            "bed_slope": _finite_tuple(
                self.bed_slope, "reach_hydraulic_geometry_bed_slope"
            ),
            "manning_n": _finite_tuple(
                self.manning_n, "reach_hydraulic_geometry_manning_n"
            ),
        }
        count = len(self.feature_ids)
        if any(len(values) != count for values in fields.values()):
            raise ValueError("reach_hydraulic_geometry_count_mismatch")
        if any((np.asarray(values) <= 0.0).any() for values in fields.values()):
            raise ValueError("reach_hydraulic_geometry_values_must_be_positive")
        object.__setattr__(self, "bottom_width_m", fields["bottom_width"])
        object.__setattr__(
            self,
            "side_slope_horizontal_per_vertical",
            fields["side_slope"],
        )
        object.__setattr__(self, "bed_slope", fields["bed_slope"])
        object.__setattr__(self, "manning_n", fields["manning_n"])
        if not self.provenance_id.strip():
            raise ValueError("reach_hydraulic_geometry_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_reach_hydraulic_geometry_evidence_level")
        if (
            self.admitted_as_hydraulic_geometry
            and self.evidence_level == "candidate"
        ):
            raise ValueError(
                "candidate_reach_geometry_cannot_be_admitted_as_hydraulic_geometry"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": REACH_HYDRAULIC_GEOMETRY_SCHEMA,
            "feature_ids": list(self.feature_ids),
            "bottom_width_m": list(self.bottom_width_m),
            "side_slope_horizontal_per_vertical": list(
                self.side_slope_horizontal_per_vertical
            ),
            "bed_slope": list(self.bed_slope),
            "manning_n": list(self.manning_n),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted_as_hydraulic_geometry": (
                self.admitted_as_hydraulic_geometry
            ),
        }


@dataclass(frozen=True)
class BoundaryOperator:
    """Directed boundary map from edges to nodes.

    ``incidence_matrix`` uses the conventional sign: -1 at an edge source
    and +1 at its target.  A non-negative edge flux therefore moves an
    extensive quantity only in the authoritative direction.
    """

    node_keys: tuple[str, ...]
    edge_keys: tuple[str, ...]
    source_indices: tuple[int, ...]
    target_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        _nonempty_unique(self.node_keys, "node_keys")
        _nonempty_unique(self.edge_keys, "edge_keys")
        edge_count = len(self.edge_keys)
        if len(self.source_indices) != edge_count or len(self.target_indices) != edge_count:
            raise ValueError("boundary_endpoint_count_mismatch")
        node_count = len(self.node_keys)
        for source, target in zip(self.source_indices, self.target_indices, strict=True):
            if source < 0 or source >= node_count or target < 0 or target >= node_count:
                raise ValueError("boundary_endpoint_out_of_range")
            if source == target:
                raise ValueError("boundary_self_loop_not_supported")

    @property
    def node_count(self) -> int:
        return len(self.node_keys)

    @property
    def edge_count(self) -> int:
        return len(self.edge_keys)

    def incidence_matrix(self) -> np.ndarray:
        incidence = np.zeros((self.node_count, self.edge_count), dtype=float)
        edge_indices = np.arange(self.edge_count)
        incidence[np.asarray(self.source_indices), edge_indices] = -1.0
        incidence[np.asarray(self.target_indices), edge_indices] = 1.0
        return incidence


@dataclass(frozen=True)
class HierarchyOperator:
    """Fine-node membership in explicitly named parent supports."""

    parent_keys: tuple[str, ...]
    node_parent_indices: tuple[int | None, ...]
    aggregation_weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.parent_keys:
            _nonempty_unique(self.parent_keys, "parent_keys")
        if len(self.node_parent_indices) != len(self.aggregation_weights):
            raise ValueError("hierarchy_weight_count_mismatch")
        parent_count = len(self.parent_keys)
        for parent in self.node_parent_indices:
            if parent is not None and (parent < 0 or parent >= parent_count):
                raise ValueError("hierarchy_parent_out_of_range")
        weights = np.asarray(self.aggregation_weights, dtype=float)
        if not np.isfinite(weights).all() or (weights < 0.0).any():
            raise ValueError("hierarchy_weights_must_be_finite_nonnegative")


@dataclass(frozen=True)
class MetricStructure:
    """Measures and hard edge limits compiled by GIS/domain tooling."""

    node_measure: tuple[float, ...]
    edge_capacity_per_second: tuple[float, ...]
    edge_travel_time_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        node_measure = np.asarray(self.node_measure, dtype=float)
        capacity = np.asarray(self.edge_capacity_per_second, dtype=float)
        travel_time = np.asarray(self.edge_travel_time_seconds, dtype=float)
        if not np.isfinite(node_measure).all() or (node_measure <= 0.0).any():
            raise ValueError("node_measure_must_be_finite_positive")
        if not np.isfinite(capacity).all() or (capacity < 0.0).any():
            raise ValueError("edge_capacity_must_be_finite_nonnegative")
        if not np.isfinite(travel_time).all() or (travel_time <= 0.0).any():
            raise ValueError("edge_travel_time_must_be_finite_positive")


@dataclass(frozen=True)
class EvidenceStructure:
    """Per-edge admission and provenance; non-admitted edges fail closed."""

    edge_admitted: tuple[bool, ...]
    edge_source_ids: tuple[str, ...]
    evidence_level: tuple[str, ...]

    def __post_init__(self) -> None:
        edge_count = len(self.edge_admitted)
        if len(self.edge_source_ids) != edge_count or len(self.evidence_level) != edge_count:
            raise ValueError("edge_evidence_count_mismatch")
        if any(not value.strip() for value in self.edge_source_ids):
            raise ValueError("edge_source_id_required")
        if any(level not in {"authoritative", "derived", "candidate"} for level in self.evidence_level):
            raise ValueError("unsupported_edge_evidence_level")


@dataclass(frozen=True)
class GeoComplex:
    """A typed geospatial complex ``(B, H, M, E)``."""

    B: BoundaryOperator
    H: HierarchyOperator
    M: MetricStructure
    E: EvidenceStructure
    crs: str

    def __post_init__(self) -> None:
        if not self.crs.strip():
            raise ValueError("geocomplex_crs_required")
        if len(self.H.node_parent_indices) != self.B.node_count:
            raise ValueError("hierarchy_node_count_mismatch")
        if len(self.M.node_measure) != self.B.node_count:
            raise ValueError("metric_node_count_mismatch")
        if len(self.M.edge_capacity_per_second) != self.B.edge_count:
            raise ValueError("metric_edge_capacity_count_mismatch")
        if len(self.M.edge_travel_time_seconds) != self.B.edge_count:
            raise ValueError("metric_edge_travel_time_count_mismatch")
        if len(self.E.edge_admitted) != self.B.edge_count:
            raise ValueError("evidence_edge_count_mismatch")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": GEOCOMPLEX_SCHEMA,
            "crs": self.crs,
            "B": {
                "node_keys": list(self.B.node_keys),
                "edge_keys": list(self.B.edge_keys),
                "source_indices": list(self.B.source_indices),
                "target_indices": list(self.B.target_indices),
            },
            "H": {
                "parent_keys": list(self.H.parent_keys),
                "node_parent_indices": list(self.H.node_parent_indices),
                "aggregation_weights": list(self.H.aggregation_weights),
            },
            "M": {
                "node_measure": list(self.M.node_measure),
                "edge_capacity_per_second": list(self.M.edge_capacity_per_second),
                "edge_travel_time_seconds": list(self.M.edge_travel_time_seconds),
            },
            "E": {
                "edge_admitted": list(self.E.edge_admitted),
                "edge_source_ids": list(self.E.edge_source_ids),
                "evidence_level": list(self.E.evidence_level),
            },
        }


@dataclass(frozen=True)
class StockState:
    values: tuple[float, ...]
    unit: str
    provenance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _finite_tuple(self.values, "stock_values"))
        if (np.asarray(self.values) < 0.0).any():
            raise ValueError("stock_values_must_be_nonnegative")
        _validate_field_identity(self.unit, self.provenance_id)


@dataclass(frozen=True)
class EdgeFlux:
    values: tuple[float, ...]
    unit: str
    provenance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _finite_tuple(self.values, "edge_flux_values"))
        if (np.asarray(self.values) < 0.0).any():
            raise ValueError("edge_flux_must_follow_nonnegative_authoritative_direction")
        _validate_field_identity(self.unit, self.provenance_id)


@dataclass(frozen=True)
class ActionBoundaryFlux:
    values: tuple[float, ...]
    unit: str
    provenance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _finite_tuple(self.values, "action_values"))
        _validate_field_identity(self.unit, self.provenance_id)


@dataclass(frozen=True)
class ForcingFlux:
    values: tuple[float, ...]
    unit: str
    provenance_id: str
    modeled: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _finite_tuple(self.values, "forcing_values"))
        _validate_field_identity(self.unit, self.provenance_id)


@dataclass(frozen=True)
class ReachForcingSupport:
    """Observed or compiled coverage of full-reach forcing on a path segment."""

    feature_ids: tuple[int, ...]
    coverage_fractions: tuple[float, ...]
    support_method: str
    provenance_id: str
    evidence_level: str
    admitted_as_spatial_support: bool

    def __post_init__(self) -> None:
        if not self.feature_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.feature_ids
        ):
            raise ValueError(
                "reach_forcing_support_feature_ids_must_be_positive_integers"
            )
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("reach_forcing_support_feature_ids_must_be_unique")
        fractions = _finite_tuple(
            self.coverage_fractions, "reach_forcing_support_coverage_fractions"
        )
        if len(fractions) != len(self.feature_ids):
            raise ValueError("reach_forcing_support_count_mismatch")
        if (np.asarray(fractions) < 0.0).any() or (
            np.asarray(fractions) > 1.0
        ).any():
            raise ValueError("reach_forcing_support_fraction_outside_unit_interval")
        object.__setattr__(self, "coverage_fractions", fractions)
        if not self.support_method.strip() or not self.provenance_id.strip():
            raise ValueError("reach_forcing_support_identity_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_reach_forcing_support_evidence_level")
        if not isinstance(self.admitted_as_spatial_support, bool):
            raise ValueError("reach_forcing_support_admission_must_be_boolean")
        if self.admitted_as_spatial_support and self.evidence_level == "candidate":
            raise ValueError(
                "candidate_reach_forcing_support_cannot_be_admitted"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": REACH_FORCING_SUPPORT_SCHEMA,
            "feature_ids": list(self.feature_ids),
            "coverage_fractions": list(self.coverage_fractions),
            "support_method": self.support_method,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted_as_spatial_support": self.admitted_as_spatial_support,
        }


@dataclass(frozen=True)
class SourceSinkFlux:
    values: tuple[float, ...]
    unit: str
    provenance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _finite_tuple(self.values, "source_sink_values"))
        _validate_field_identity(self.unit, self.provenance_id)


@dataclass(frozen=True)
class ObservationField:
    """Read-only evidence for evaluation; never a state-transition input."""

    values: tuple[float, ...]
    unit: str
    provenance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _finite_tuple(self.values, "observation_values"))
        _validate_field_identity(self.unit, self.provenance_id)


@dataclass(frozen=True)
class ControlSignal:
    """A decision variable that must be materialized as a boundary condition."""

    values: tuple[float, ...]
    unit: str
    provenance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _finite_tuple(self.values, "control_values"))
        _validate_field_identity(self.unit, self.provenance_id)


def _validate_field_identity(unit: str, provenance_id: str) -> None:
    if not unit.strip():
        raise ValueError("field_unit_required")
    if not provenance_id.strip():
        raise ValueError("field_provenance_required")
