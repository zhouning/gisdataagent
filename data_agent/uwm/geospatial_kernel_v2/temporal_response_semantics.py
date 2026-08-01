"""Typed observation and process semantics for geospatial response time."""

from __future__ import annotations

from dataclasses import dataclass
import math

from data_agent.uwm.geospatial_kernel_v2.contracts import TemporalSupport


FIELD_SCHEMA = "gwm.geospatial.temporal_field_semantics.v1"
PROCESS_SCHEMA = "gwm.geospatial.response_time_semantics.v1"
COMPATIBILITY_SCHEMA = "gwm.geospatial.response_semantic_compatibility.v1"
RECONCILIATION_SCHEMA = "gwm.geospatial.response_semantic_reconciliation.v1"

FIELD_STATISTICS = {"interval_average", "instantaneous_sample_mean"}
PROCESS_SEMANTICS = {
    "empirical_downstream_response_lag": (
        "discharge_series",
        "interval_end_label_step",
        "windowed_linear_association_peak",
    ),
    "gravity_wave_time": (
        "hydraulic_disturbance",
        "physical_boundary_perturbation",
        "first_signal_arrival",
    ),
    "manning_kinematic_centroid_time": (
        "discharge_perturbation",
        "physical_boundary_perturbation",
        "response_centroid",
    ),
    "advective_residence_time": (
        "water_mass",
        "material_injection",
        "material_exit_centroid",
    ),
}


@dataclass(frozen=True)
class TemporalFieldSemantics:
    field_id: str
    spatial_role: str
    variable: str
    unit: str
    statistic: str
    temporal_support: TemporalSupport
    native_sampling_interval_seconds: float | None
    native_samples_per_compiled_support: int | None
    provenance_id: str

    def __post_init__(self) -> None:
        sampling = self.native_sampling_interval_seconds
        count = self.native_samples_per_compiled_support
        if (
            not self.field_id.strip()
            or not self.spatial_role.strip()
            or self.variable != "discharge"
            or self.unit != "m3/s"
            or self.statistic not in FIELD_STATISTICS
            or not self.provenance_id.strip()
            or (sampling is not None and (
                not math.isfinite(sampling) or sampling <= 0.0
            ))
            or (count is not None and (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            ))
        ):
            raise ValueError("temporal_field_semantics_invalid")
        if self.statistic == "interval_average":
            valid = (
                self.temporal_support.kind == "interval_mean"
                and self.temporal_support.evidence_level == "authoritative"
                and sampling is None
                and count is None
            )
        else:
            valid = (
                self.temporal_support.kind == "interval_sample_mean"
                and self.temporal_support.evidence_level == "derived"
                and sampling is not None
                and count is not None
                and abs(sampling * count - self.temporal_support.duration_seconds)
                < 1e-9
            )
        if not valid:
            raise ValueError("temporal_field_statistic_support_mismatch")

    def label_shift_compatible_with(
        self, other: TemporalFieldSemantics
    ) -> bool:
        return (
            self.variable == other.variable
            and self.unit == other.unit
            and self.temporal_support.duration_seconds
            == other.temporal_support.duration_seconds
            and self.temporal_support.timestamp_position == "end"
            and other.temporal_support.timestamp_position == "end"
        )

    def require_label_shift_grid(
        self, other: TemporalFieldSemantics
    ) -> float:
        if not self.label_shift_compatible_with(other):
            raise ValueError("temporal_field_label_shift_grid_unadmitted")
        return self.temporal_support.duration_seconds

    def require_physical_observation_equivalence(
        self, other: TemporalFieldSemantics
    ) -> None:
        if (
            not self.label_shift_compatible_with(other)
            or self.statistic != other.statistic
            or self.temporal_support.kind != other.temporal_support.kind
        ):
            raise ValueError(
                "temporal_field_physical_observation_equivalence_unadmitted"
            )

    def require_actuation_instant(self) -> None:
        raise ValueError("temporal_field_actuation_instant_unadmitted")

    def require_continuous_interval_average(self) -> None:
        if self.statistic != "interval_average":
            raise ValueError(
                "temporal_field_continuous_interval_average_unadmitted"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FIELD_SCHEMA,
            "field_id": self.field_id,
            "spatial_role": self.spatial_role,
            "variable": self.variable,
            "unit": self.unit,
            "statistic": self.statistic,
            "temporal_support": self.temporal_support.as_dict(),
            "native_sampling_interval_seconds": (
                self.native_sampling_interval_seconds
            ),
            "native_samples_per_compiled_support": (
                self.native_samples_per_compiled_support
            ),
            "provenance_id": self.provenance_id,
            "actuation_instant_admitted": False,
            "continuous_interval_average_admitted": (
                self.statistic == "interval_average"
            ),
        }


@dataclass(frozen=True)
class ResponseTimeSemantics:
    quantity: str
    path_id: str
    carrier: str
    source_event_marker: str
    target_response_functional: str
    state_dependent: bool
    outcome_derived: bool
    admitted_as_physical_response_time: bool
    provenance_id: str

    def __post_init__(self) -> None:
        expected = PROCESS_SEMANTICS.get(self.quantity)
        if (
            expected is None
            or expected
            != (
                self.carrier,
                self.source_event_marker,
                self.target_response_functional,
            )
            or not self.path_id.strip()
            or not isinstance(self.state_dependent, bool)
            or not isinstance(self.outcome_derived, bool)
            or not isinstance(self.admitted_as_physical_response_time, bool)
            or not self.provenance_id.strip()
            or (
                self.quantity == "empirical_downstream_response_lag"
                and (
                    self.outcome_derived is not True
                    or self.admitted_as_physical_response_time is not False
                )
            )
            or (
                self.quantity != "empirical_downstream_response_lag"
                and self.outcome_derived is not False
            )
        ):
            raise ValueError("response_time_semantics_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PROCESS_SCHEMA,
            "quantity": self.quantity,
            "path_id": self.path_id,
            "carrier": self.carrier,
            "source_event_marker": self.source_event_marker,
            "target_response_functional": (
                self.target_response_functional
            ),
            "state_dependent": self.state_dependent,
            "outcome_derived": self.outcome_derived,
            "admitted_as_physical_response_time": (
                self.admitted_as_physical_response_time
            ),
            "time_dimension_only_does_not_imply_substitutability": True,
            "provenance_id": self.provenance_id,
        }


@dataclass(frozen=True)
class ResponseSemanticCompatibility:
    empirical: ResponseTimeSemantics
    candidate: ResponseTimeSemantics
    same_spatial_path: bool
    numerical_overlap: bool

    def __post_init__(self) -> None:
        if (
            self.empirical.quantity
            != "empirical_downstream_response_lag"
            or self.candidate.quantity
            == "empirical_downstream_response_lag"
            or not isinstance(self.same_spatial_path, bool)
            or not isinstance(self.numerical_overlap, bool)
        ):
            raise ValueError("response_semantic_compatibility_invalid")

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        reasons = []
        if not self.same_spatial_path:
            reasons.append("spatial_path_mismatch")
        if self.empirical.carrier != self.candidate.carrier:
            reasons.append("transport_carrier_mismatch")
        if (
            self.empirical.source_event_marker
            != self.candidate.source_event_marker
        ):
            reasons.append("source_event_marker_mismatch")
        if (
            self.empirical.target_response_functional
            != self.candidate.target_response_functional
        ):
            reasons.append("target_response_functional_mismatch")
        if not self.candidate.admitted_as_physical_response_time:
            reasons.append("candidate_physical_response_time_unadmitted")
        if not self.numerical_overlap:
            reasons.append("numerical_support_disjoint")
        return tuple(reasons)

    @property
    def semantic_equivalence_admitted(self) -> bool:
        semantic_reasons = {
            "spatial_path_mismatch",
            "transport_carrier_mismatch",
            "source_event_marker_mismatch",
            "target_response_functional_mismatch",
            "candidate_physical_response_time_unadmitted",
        }
        return not semantic_reasons.intersection(self.rejection_reasons)

    @property
    def physical_response_comparison_admitted(self) -> bool:
        return not self.rejection_reasons

    def require_physical_response_comparison(self) -> None:
        if not self.physical_response_comparison_admitted:
            raise ValueError(
                "response_semantic_physical_comparison_unadmitted:"
                + ",".join(self.rejection_reasons)
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": COMPATIBILITY_SCHEMA,
            "empirical_quantity": self.empirical.quantity,
            "candidate_quantity": self.candidate.quantity,
            "same_spatial_path": self.same_spatial_path,
            "same_time_dimension": True,
            "same_transport_carrier": (
                self.empirical.carrier == self.candidate.carrier
            ),
            "same_source_event_marker": (
                self.empirical.source_event_marker
                == self.candidate.source_event_marker
            ),
            "same_target_response_functional": (
                self.empirical.target_response_functional
                == self.candidate.target_response_functional
            ),
            "candidate_physical_response_time_admitted": (
                self.candidate.admitted_as_physical_response_time
            ),
            "numerical_overlap": self.numerical_overlap,
            "rejection_reasons": list(self.rejection_reasons),
            "semantic_equivalence_admitted": (
                self.semantic_equivalence_admitted
            ),
            "physical_response_comparison_admitted": (
                self.physical_response_comparison_admitted
            ),
        }


@dataclass(frozen=True)
class GeospatialResponseSemanticReconciliation:
    source_field: TemporalFieldSemantics
    target_field: TemporalFieldSemantics
    empirical: ResponseTimeSemantics
    compatibilities: tuple[ResponseSemanticCompatibility, ...]
    all_event_common_empirical_support: bool

    def __post_init__(self) -> None:
        if (
            not self.compatibilities
            or any(
                value.empirical != self.empirical
                for value in self.compatibilities
            )
            or not isinstance(self.all_event_common_empirical_support, bool)
        ):
            raise ValueError("response_semantic_reconciliation_invalid")

    @property
    def label_shift_diagnostic_admitted(self) -> bool:
        return self.source_field.label_shift_compatible_with(
            self.target_field
        )

    @property
    def physical_response_time_admitted(self) -> bool:
        return (
            self.all_event_common_empirical_support
            and any(
                value.physical_response_comparison_admitted
                for value in self.compatibilities
            )
        )

    def require_label_shift_grid_seconds(self) -> float:
        return self.source_field.require_label_shift_grid(self.target_field)

    def require_physical_response_time(self) -> None:
        if not self.physical_response_time_admitted:
            raise ValueError(
                "geospatial_response_physical_time_unadmitted"
            )

    def promote_to_runtime_transition(self) -> None:
        raise ValueError(
            "geospatial_response_runtime_transition_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": RECONCILIATION_SCHEMA,
            "source_field": self.source_field.as_dict(),
            "target_field": self.target_field.as_dict(),
            "empirical_response_semantics": self.empirical.as_dict(),
            "compatibilities": [
                value.as_dict() for value in self.compatibilities
            ],
            "all_event_common_empirical_support": (
                self.all_event_common_empirical_support
            ),
            "label_shift_diagnostic_admitted": (
                self.label_shift_diagnostic_admitted
            ),
            "physical_observation_equivalence_admitted": False,
            "physical_response_time_admitted": (
                self.physical_response_time_admitted
            ),
            "runtime_transition_admitted": False,
        }


def compile_response_semantic_compatibility(
    empirical: ResponseTimeSemantics,
    candidate: ResponseTimeSemantics,
    *,
    same_spatial_path: bool,
    numerical_overlap: bool,
) -> ResponseSemanticCompatibility:
    return ResponseSemanticCompatibility(
        empirical,
        candidate,
        same_spatial_path,
        numerical_overlap,
    )
