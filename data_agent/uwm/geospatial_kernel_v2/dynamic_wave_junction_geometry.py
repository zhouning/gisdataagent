"""Geographic junction geometry and evidence-gated energy-loss binding."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
import re
from typing import Mapping

from pyproj import Geod

from .dynamic_wave_junction_energy import DynamicWaveJunctionEnergyLoss


GEOGRAPHIC_JUNCTION_GEOMETRY_SCHEMA = (
    "gwm.geospatial_kernel.geographic_junction_geometry.v1"
)
GEOGRAPHIC_JUNCTION_LOSS_ADMISSION_SCHEMA = (
    "gwm.geospatial_kernel.geographic_junction_loss_admission.v1"
)
STAGE8_LOSS_COEFFICIENT_SEMANTICS = "dimensionless_velocity_head_multiplier"

_WGS84 = Geod(ellps="WGS84")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_BRANCH_ROLES = frozenset(("upstream", "downstream"))
_STRUCTURE_CLASSIFICATIONS = frozenset(
    ("natural_confluence", "culvert", "gate", "weir", "bridge", "unknown")
)
_ADMISSIBLE_DERIVATION_METHODS = frozenset(
    ("site_specific_engineering_assessment", "documented_structure_loss_model")
)


@dataclass(frozen=True)
class GeographicJunctionBranchSource:
    """One public or engineered branch centerline with immutable lineage."""

    branch_id: str
    role: str
    source_feature_id: str
    coordinates: tuple[tuple[float, float], ...]
    source_uri: str
    source_sha256: str
    source_crs: str = "EPSG:4326"

    def __post_init__(self) -> None:
        coordinates = tuple(_coordinate(value) for value in self.coordinates)
        digest = str(self.source_sha256).lower()
        if (
            not isinstance(self.branch_id, str)
            or not self.branch_id.strip()
            or self.role not in _BRANCH_ROLES
            or not isinstance(self.source_feature_id, str)
            or not self.source_feature_id.strip()
            or len(coordinates) < 2
            or not isinstance(self.source_uri, str)
            or not self.source_uri.strip()
            or _SHA256.fullmatch(digest) is None
            or not isinstance(self.source_crs, str)
            or not self.source_crs.strip()
        ):
            raise ValueError("geographic_junction_branch_source_invalid")
        object.__setattr__(self, "coordinates", coordinates)
        object.__setattr__(self, "source_sha256", digest)


@dataclass(frozen=True)
class JunctionStructureEvidence:
    classification: str
    source_uri: str
    source_sha256: str
    source_record_id: str

    def __post_init__(self) -> None:
        digest = str(self.source_sha256).lower()
        if (
            self.classification not in _STRUCTURE_CLASSIFICATIONS - {"unknown"}
            or not isinstance(self.source_uri, str)
            or not self.source_uri.strip()
            or _SHA256.fullmatch(digest) is None
            or not isinstance(self.source_record_id, str)
            or not self.source_record_id.strip()
        ):
            raise ValueError("geographic_junction_structure_evidence_invalid")
        object.__setattr__(self, "source_sha256", digest)

    def as_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "source_record_id": self.source_record_id,
        }


@dataclass(frozen=True)
class GeographicJunctionBranch:
    branch_id: str
    role: str
    source_feature_id: str
    flow_azimuth_degrees: float
    junction_endpoint: tuple[float, float]
    local_reference_coordinate: tuple[float, float]
    terminal_snap_distance_m: float
    requested_window_length_m: float
    sampled_window_length_m: float
    available_terminal_path_length_m: float
    coordinate_count: int
    source_uri: str
    source_sha256: str
    source_crs: str

    def __post_init__(self) -> None:
        endpoint = _coordinate(self.junction_endpoint)
        reference = _coordinate(self.local_reference_coordinate)
        azimuth = float(self.flow_azimuth_degrees)
        snap = float(self.terminal_snap_distance_m)
        requested = float(self.requested_window_length_m)
        sampled = float(self.sampled_window_length_m)
        available = float(self.available_terminal_path_length_m)
        digest = str(self.source_sha256).lower()
        if (
            not isinstance(self.branch_id, str)
            or not self.branch_id.strip()
            or self.role not in _BRANCH_ROLES
            or not isinstance(self.source_feature_id, str)
            or not self.source_feature_id.strip()
            or not math.isfinite(azimuth)
            or not 0.0 <= azimuth < 360.0
            or not math.isfinite(snap)
            or snap < 0.0
            or not math.isfinite(requested)
            or requested <= 0.0
            or not math.isfinite(sampled)
            or not 0.0 < sampled <= requested
            or not math.isfinite(available)
            or available < sampled
            or not isinstance(self.coordinate_count, int)
            or self.coordinate_count < 2
            or not isinstance(self.source_uri, str)
            or not self.source_uri.strip()
            or _SHA256.fullmatch(digest) is None
            or self.source_crs.upper() != "EPSG:4326"
        ):
            raise ValueError("geographic_junction_branch_invalid")
        object.__setattr__(self, "flow_azimuth_degrees", azimuth)
        object.__setattr__(self, "junction_endpoint", endpoint)
        object.__setattr__(self, "local_reference_coordinate", reference)
        object.__setattr__(self, "terminal_snap_distance_m", snap)
        object.__setattr__(self, "requested_window_length_m", requested)
        object.__setattr__(self, "sampled_window_length_m", sampled)
        object.__setattr__(self, "available_terminal_path_length_m", available)
        object.__setattr__(self, "source_sha256", digest)

    def as_dict(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "role": self.role,
            "source_feature_id": self.source_feature_id,
            "flow_azimuth_degrees": self.flow_azimuth_degrees,
            "junction_endpoint": list(self.junction_endpoint),
            "local_reference_coordinate": list(
                self.local_reference_coordinate
            ),
            "terminal_snap_distance_m": self.terminal_snap_distance_m,
            "requested_window_length_m": self.requested_window_length_m,
            "sampled_window_length_m": self.sampled_window_length_m,
            "available_terminal_path_length_m": (
                self.available_terminal_path_length_m
            ),
            "window_truncated_by_feature_length": (
                self.sampled_window_length_m < self.requested_window_length_m
            ),
            "coordinate_count": self.coordinate_count,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "source_crs": self.source_crs,
            "azimuth_method": "WGS84_ellipsoidal_geodesic",
        }


@dataclass(frozen=True)
class GeographicJunctionGeometry:
    junction_id: str
    junction_coordinate: tuple[float, float]
    upstream_branches: tuple[GeographicJunctionBranch, ...]
    downstream_branch: GeographicJunctionBranch
    upstream_to_downstream_deflection_degrees: tuple[float, ...]
    upstream_pair_angles_degrees: tuple[tuple[str, str, float], ...]
    terminal_snap_tolerance_m: float
    minimum_terminal_path_length_m: float
    structure_classification: str
    structure_evidence: JunctionStructureEvidence | None
    geometry_admitted: bool = True

    def __post_init__(self) -> None:
        coordinate = _coordinate(self.junction_coordinate)
        upstream = tuple(self.upstream_branches)
        deflections = tuple(
            float(value)
            for value in self.upstream_to_downstream_deflection_degrees
        )
        pairs = tuple(self.upstream_pair_angles_degrees)
        expected_pairs = tuple(
            (left.branch_id, right.branch_id)
            for left, right in itertools.combinations(upstream, 2)
        )
        tolerance = float(self.terminal_snap_tolerance_m)
        minimum_path = float(self.minimum_terminal_path_length_m)
        branches = (*upstream, self.downstream_branch)
        if (
            not isinstance(self.junction_id, str)
            or not self.junction_id.strip()
            or len(upstream) < 2
            or any(
                not isinstance(value, GeographicJunctionBranch)
                or value.role != "upstream"
                for value in upstream
            )
            or not isinstance(self.downstream_branch, GeographicJunctionBranch)
            or self.downstream_branch.role != "downstream"
            or len({value.branch_id for value in branches}) != len(branches)
            or len(deflections) != len(upstream)
            or any(
                not math.isfinite(value) or not 0.0 <= value <= 180.0
                for value in deflections
            )
            or tuple((left, right) for left, right, _ in pairs)
            != expected_pairs
            or any(
                not math.isfinite(float(angle))
                or not 0.0 <= float(angle) <= 180.0
                for _, _, angle in pairs
            )
            or not math.isfinite(tolerance)
            or tolerance < 0.0
            or any(value.terminal_snap_distance_m > tolerance for value in branches)
            or not math.isfinite(minimum_path)
            or minimum_path <= 0.0
            or any(value.sampled_window_length_m < minimum_path for value in branches)
            or self.structure_classification not in _STRUCTURE_CLASSIFICATIONS
            or (
                self.structure_evidence is None
                and self.structure_classification != "unknown"
            )
            or (
                self.structure_evidence is not None
                and (
                    not isinstance(
                        self.structure_evidence, JunctionStructureEvidence
                    )
                    or self.structure_evidence.classification
                    != self.structure_classification
                )
            )
            or not isinstance(self.geometry_admitted, bool)
        ):
            raise ValueError("geographic_junction_geometry_invalid")
        object.__setattr__(self, "junction_coordinate", coordinate)
        object.__setattr__(self, "upstream_branches", upstream)
        object.__setattr__(
            self,
            "upstream_to_downstream_deflection_degrees",
            deflections,
        )
        object.__setattr__(self, "upstream_pair_angles_degrees", pairs)
        object.__setattr__(self, "terminal_snap_tolerance_m", tolerance)
        object.__setattr__(self, "minimum_terminal_path_length_m", minimum_path)

    @property
    def upstream_branch_ids(self) -> tuple[str, ...]:
        return tuple(value.branch_id for value in self.upstream_branches)

    @property
    def downstream_branch_id(self) -> str:
        return self.downstream_branch.branch_id

    def as_dict(self) -> dict[str, object]:
        branches = (*self.upstream_branches, self.downstream_branch)
        return {
            "schema": GEOGRAPHIC_JUNCTION_GEOMETRY_SCHEMA,
            "junction_id": self.junction_id,
            "junction_coordinate": list(self.junction_coordinate),
            "source_crs": "EPSG:4326",
            "upstream_branches": [
                value.as_dict() for value in self.upstream_branches
            ],
            "downstream_branch": self.downstream_branch.as_dict(),
            "upstream_to_downstream_deflection_degrees": dict(
                zip(
                    self.upstream_branch_ids,
                    self.upstream_to_downstream_deflection_degrees,
                    strict=True,
                )
            ),
            "upstream_pair_angles": [
                {
                    "branch_ids": [left, right],
                    "angle_degrees": angle,
                }
                for left, right, angle in self.upstream_pair_angles_degrees
            ],
            "structure_classification": self.structure_classification,
            "structure_evidence": (
                None
                if self.structure_evidence is None
                else self.structure_evidence.as_dict()
            ),
            "quality": {
                "geometry_admitted": self.geometry_admitted,
                "terminal_snap_tolerance_m": self.terminal_snap_tolerance_m,
                "maximum_terminal_snap_distance_m": max(
                    value.terminal_snap_distance_m for value in branches
                ),
                "minimum_required_terminal_path_length_m": (
                    self.minimum_terminal_path_length_m
                ),
                "minimum_sampled_terminal_path_length_m": min(
                    value.sampled_window_length_m for value in branches
                ),
                "branch_ids_unique": len(branches)
                == len({value.branch_id for value in branches}),
                "one_downstream_branch": True,
                "at_least_two_upstream_branches": True,
            },
            "semantic_limits": {
                "centerline_geometry_determines_loss_coefficient": False,
                "cross_sections_present": False,
                "flow_partition_present": False,
                "vector_momentum_closure_present": False,
            },
        }


@dataclass(frozen=True)
class JunctionEnergyLossCoefficientEvidence:
    junction_id: str
    upstream_branch_ids: tuple[str, ...]
    downstream_branch_id: str
    upstream_loss_coefficients: tuple[float, ...]
    downstream_loss_coefficient: float
    coefficient_semantics: str
    derivation_method: str
    applicability_confirmed: bool
    structure_classification: str
    source_uri: str
    source_sha256: str
    source_record_id: str

    def __post_init__(self) -> None:
        branch_ids = tuple(self.upstream_branch_ids)
        coefficients = tuple(
            float(value) for value in self.upstream_loss_coefficients
        )
        downstream = float(self.downstream_loss_coefficient)
        digest = str(self.source_sha256).lower()
        if (
            not isinstance(self.junction_id, str)
            or not self.junction_id.strip()
            or not branch_ids
            or len(branch_ids) != len(set(branch_ids))
            or len(branch_ids) != len(coefficients)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in branch_ids
            )
            or not isinstance(self.downstream_branch_id, str)
            or not self.downstream_branch_id.strip()
            or self.downstream_branch_id in branch_ids
            or any(
                not math.isfinite(value) or value < 0.0
                for value in coefficients
            )
            or not math.isfinite(downstream)
            or downstream < 0.0
            or not isinstance(self.coefficient_semantics, str)
            or not self.coefficient_semantics.strip()
            or not isinstance(self.derivation_method, str)
            or not self.derivation_method.strip()
            or not isinstance(self.applicability_confirmed, bool)
            or self.structure_classification not in _STRUCTURE_CLASSIFICATIONS
            or not isinstance(self.source_uri, str)
            or not self.source_uri.strip()
            or _SHA256.fullmatch(digest) is None
            or not isinstance(self.source_record_id, str)
            or not self.source_record_id.strip()
        ):
            raise ValueError("geographic_junction_loss_evidence_invalid")
        object.__setattr__(self, "upstream_branch_ids", branch_ids)
        object.__setattr__(self, "upstream_loss_coefficients", coefficients)
        object.__setattr__(self, "downstream_loss_coefficient", downstream)
        object.__setattr__(self, "source_sha256", digest)

    def as_dict(self) -> dict[str, object]:
        return {
            "junction_id": self.junction_id,
            "upstream_loss_coefficients": dict(
                zip(
                    self.upstream_branch_ids,
                    self.upstream_loss_coefficients,
                    strict=True,
                )
            ),
            "downstream_branch_id": self.downstream_branch_id,
            "downstream_loss_coefficient": self.downstream_loss_coefficient,
            "coefficient_semantics": self.coefficient_semantics,
            "derivation_method": self.derivation_method,
            "applicability_confirmed": self.applicability_confirmed,
            "structure_classification": self.structure_classification,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "source_record_id": self.source_record_id,
        }


@dataclass(frozen=True)
class GeographicJunctionEnergyLossAdmission:
    junction_id: str
    status: str
    reason_codes: tuple[str, ...]
    coefficient_evidence: JunctionEnergyLossCoefficientEvidence | None
    energy_loss: DynamicWaveJunctionEnergyLoss | None

    def __post_init__(self) -> None:
        reasons = tuple(self.reason_codes)
        admitted = self.status == "admitted"
        if (
            not isinstance(self.junction_id, str)
            or not self.junction_id.strip()
            or self.status not in {"admitted", "not_admitted"}
            or len(reasons) != len(set(reasons))
            or any(not isinstance(value, str) or not value for value in reasons)
            or (
                admitted
                and (
                    reasons
                    or not isinstance(
                        self.coefficient_evidence,
                        JunctionEnergyLossCoefficientEvidence,
                    )
                    or not isinstance(
                        self.energy_loss, DynamicWaveJunctionEnergyLoss
                    )
                )
            )
            or (
                not admitted
                and (not reasons or self.energy_loss is not None)
            )
            or (
                admitted
                and (
                    self.coefficient_evidence.junction_id != self.junction_id
                    or self.energy_loss.upstream_branch_ids
                    != self.coefficient_evidence.upstream_branch_ids
                    or self.energy_loss.upstream_loss_coefficients
                    != self.coefficient_evidence.upstream_loss_coefficients
                    or self.energy_loss.downstream_loss_coefficient
                    != self.coefficient_evidence.downstream_loss_coefficient
                )
            )
        ):
            raise ValueError("geographic_junction_loss_admission_invalid")
        object.__setattr__(self, "reason_codes", reasons)

    @property
    def admitted(self) -> bool:
        return self.status == "admitted"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": GEOGRAPHIC_JUNCTION_LOSS_ADMISSION_SCHEMA,
            "junction_id": self.junction_id,
            "status": self.status,
            "admitted": self.admitted,
            "reason_codes": list(self.reason_codes),
            "coefficient_evidence": (
                None
                if self.coefficient_evidence is None
                else self.coefficient_evidence.as_dict()
            ),
            "energy_loss": (
                None if self.energy_loss is None else self.energy_loss.as_dict()
            ),
            "implicit_zero_loss_assumed": False,
            "centerline_angle_used_as_loss_formula": False,
        }


def compile_geographic_junction_geometry(
    junction_id: str,
    junction_coordinate: tuple[float, float],
    branch_sources: tuple[GeographicJunctionBranchSource, ...],
    *,
    geometry_window_length_m: float,
    terminal_snap_tolerance_m: float,
    minimum_terminal_path_length_m: float,
    structure_evidence: JunctionStructureEvidence | None = None,
) -> GeographicJunctionGeometry:
    """Resolve centerline endpoints and directions on the WGS84 ellipsoid."""

    coordinate = _coordinate(junction_coordinate)
    window = float(geometry_window_length_m)
    snap_tolerance = float(terminal_snap_tolerance_m)
    minimum_path = float(minimum_terminal_path_length_m)
    sources = tuple(branch_sources)
    upstream_sources = tuple(
        value for value in sources if value.role == "upstream"
    )
    downstream_sources = tuple(
        value for value in sources if value.role == "downstream"
    )
    if (
        not isinstance(junction_id, str)
        or not junction_id.strip()
        or len(upstream_sources) < 2
        or len(downstream_sources) != 1
        or len(sources) != len(upstream_sources) + 1
        or len({value.branch_id for value in sources}) != len(sources)
        or any(value.source_crs.upper() != "EPSG:4326" for value in sources)
        or not math.isfinite(window)
        or window <= 0.0
        or not math.isfinite(snap_tolerance)
        or snap_tolerance < 0.0
        or not math.isfinite(minimum_path)
        or minimum_path <= 0.0
        or minimum_path > window
    ):
        raise ValueError("geographic_junction_geometry_contract_invalid")
    upstream = tuple(
        _compile_branch(
            value,
            coordinate,
            geometry_window_length_m=window,
            terminal_snap_tolerance_m=snap_tolerance,
            minimum_terminal_path_length_m=minimum_path,
        )
        for value in upstream_sources
    )
    downstream = _compile_branch(
        downstream_sources[0],
        coordinate,
        geometry_window_length_m=window,
        terminal_snap_tolerance_m=snap_tolerance,
        minimum_terminal_path_length_m=minimum_path,
    )
    deflections = tuple(
        _azimuth_difference_degrees(
            value.flow_azimuth_degrees, downstream.flow_azimuth_degrees
        )
        for value in upstream
    )
    pair_angles = tuple(
        (
            left.branch_id,
            right.branch_id,
            _azimuth_difference_degrees(
                left.flow_azimuth_degrees, right.flow_azimuth_degrees
            ),
        )
        for left, right in itertools.combinations(upstream, 2)
    )
    return GeographicJunctionGeometry(
        junction_id=junction_id,
        junction_coordinate=coordinate,
        upstream_branches=upstream,
        downstream_branch=downstream,
        upstream_to_downstream_deflection_degrees=deflections,
        upstream_pair_angles_degrees=pair_angles,
        terminal_snap_tolerance_m=snap_tolerance,
        minimum_terminal_path_length_m=minimum_path,
        structure_classification=(
            "unknown"
            if structure_evidence is None
            else structure_evidence.classification
        ),
        structure_evidence=structure_evidence,
    )


def adjudicate_geographic_junction_energy_loss(
    geometry: GeographicJunctionGeometry,
    evidence: JunctionEnergyLossCoefficientEvidence | None = None,
) -> GeographicJunctionEnergyLossAdmission:
    """Admit only coefficients with exact Stage 8 semantics and applicability."""

    if not isinstance(geometry, GeographicJunctionGeometry):
        raise TypeError("geographic_junction_geometry_required")
    if evidence is None:
        reasons = []
        if geometry.structure_classification == "unknown":
            reasons.append("structure_classification_unknown")
        reasons.extend(
            (
                "loss_coefficient_evidence_missing",
                "centerline_geometry_does_not_determine_loss_coefficient",
            )
        )
        return GeographicJunctionEnergyLossAdmission(
            geometry.junction_id, "not_admitted", tuple(reasons), None, None
        )
    if (
        evidence.junction_id != geometry.junction_id
        or evidence.upstream_branch_ids != geometry.upstream_branch_ids
        or evidence.downstream_branch_id != geometry.downstream_branch_id
    ):
        raise ValueError("geographic_junction_loss_evidence_misattached")
    reasons = []
    if geometry.structure_classification == "unknown":
        reasons.append("structure_classification_unknown")
    if evidence.structure_classification != geometry.structure_classification:
        reasons.append("structure_classification_mismatch")
    if evidence.coefficient_semantics != STAGE8_LOSS_COEFFICIENT_SEMANTICS:
        reasons.append("loss_coefficient_semantics_not_stage8_compatible")
    if evidence.derivation_method not in _ADMISSIBLE_DERIVATION_METHODS:
        reasons.append("loss_derivation_method_not_admitted")
    if not evidence.applicability_confirmed:
        reasons.append("loss_model_applicability_not_confirmed")
    if reasons:
        return GeographicJunctionEnergyLossAdmission(
            geometry.junction_id,
            "not_admitted",
            tuple(reasons),
            evidence,
            None,
        )
    loss = DynamicWaveJunctionEnergyLoss(
        evidence.upstream_branch_ids,
        evidence.upstream_loss_coefficients,
        evidence.downstream_loss_coefficient,
    )
    return GeographicJunctionEnergyLossAdmission(
        geometry.junction_id, "admitted", (), evidence, loss
    )


def bind_admitted_geographic_losses_to_dag(
    topology: object,
    admissions: Mapping[str, GeographicJunctionEnergyLossAdmission],
) -> dict[str, DynamicWaveJunctionEnergyLoss]:
    """Create the Stage 8 DAG map, rejecting missing or non-admitted nodes."""

    from .dynamic_wave_dag import DynamicWaveDendriticTopology

    if not isinstance(topology, DynamicWaveDendriticTopology):
        raise TypeError("dynamic_wave_dendritic_topology_required")
    by_id = dict(admissions)
    if set(by_id) != set(topology.junction_reach_ids):
        raise ValueError("geographic_junction_energy_loss_dag_binding_invalid")
    result: dict[str, DynamicWaveJunctionEnergyLoss] = {}
    for junction_id in topology.junction_reach_ids:
        admission = by_id[junction_id]
        if (
            not isinstance(admission, GeographicJunctionEnergyLossAdmission)
            or not admission.admitted
            or admission.energy_loss is None
            or admission.junction_id != junction_id
            or admission.energy_loss.upstream_branch_ids
            != topology.upstream_reach_ids(junction_id)
        ):
            raise ValueError(
                "geographic_junction_energy_loss_dag_binding_not_admitted"
            )
        result[junction_id] = admission.energy_loss
    return result


def _compile_branch(
    source: GeographicJunctionBranchSource,
    junction_coordinate: tuple[float, float],
    *,
    geometry_window_length_m: float,
    terminal_snap_tolerance_m: float,
    minimum_terminal_path_length_m: float,
) -> GeographicJunctionBranch:
    first_distance = _distance_m(source.coordinates[0], junction_coordinate)
    last_distance = _distance_m(source.coordinates[-1], junction_coordinate)
    nearest = min(first_distance, last_distance)
    if nearest > terminal_snap_tolerance_m:
        raise ValueError("geographic_junction_branch_endpoint_not_snapped")
    if abs(first_distance - last_distance) <= 1e-9:
        raise ValueError("geographic_junction_branch_endpoint_ambiguous")
    terminal_path = (
        source.coordinates
        if first_distance < last_distance
        else tuple(reversed(source.coordinates))
    )
    segment_lengths = tuple(
        _distance_m(left, right)
        for left, right in zip(
            terminal_path[:-1], terminal_path[1:], strict=True
        )
    )
    available = sum(segment_lengths)
    if available < minimum_terminal_path_length_m:
        raise ValueError("geographic_junction_branch_terminal_path_too_short")
    sampled = min(geometry_window_length_m, available)
    reference = _point_along_path(terminal_path, segment_lengths, sampled)
    endpoint = terminal_path[0]
    azimuth = (
        _forward_azimuth_degrees(reference, endpoint)
        if source.role == "upstream"
        else _forward_azimuth_degrees(endpoint, reference)
    )
    return GeographicJunctionBranch(
        branch_id=source.branch_id,
        role=source.role,
        source_feature_id=source.source_feature_id,
        flow_azimuth_degrees=azimuth,
        junction_endpoint=endpoint,
        local_reference_coordinate=reference,
        terminal_snap_distance_m=nearest,
        requested_window_length_m=geometry_window_length_m,
        sampled_window_length_m=sampled,
        available_terminal_path_length_m=available,
        coordinate_count=len(source.coordinates),
        source_uri=source.source_uri,
        source_sha256=source.source_sha256,
        source_crs=source.source_crs,
    )


def _point_along_path(
    path: tuple[tuple[float, float], ...],
    segment_lengths_m: tuple[float, ...],
    distance_m: float,
) -> tuple[float, float]:
    remaining = distance_m
    for start, end, length in zip(
        path[:-1], path[1:], segment_lengths_m, strict=True
    ):
        if length <= 0.0:
            continue
        if remaining <= length:
            azimuth, _, _ = _WGS84.inv(start[0], start[1], end[0], end[1])
            longitude, latitude, _ = _WGS84.fwd(
                start[0], start[1], azimuth, remaining
            )
            return float(longitude), float(latitude)
        remaining -= length
    return path[-1]


def _coordinate(values: tuple[float, float]) -> tuple[float, float]:
    if len(values) != 2:
        raise ValueError("geographic_junction_coordinate_invalid")
    longitude, latitude = (float(value) for value in values)
    if (
        not math.isfinite(longitude)
        or not math.isfinite(latitude)
        or not -180.0 <= longitude <= 180.0
        or not -90.0 <= latitude <= 90.0
    ):
        raise ValueError("geographic_junction_coordinate_invalid")
    return longitude, latitude


def _distance_m(
    left: tuple[float, float], right: tuple[float, float]
) -> float:
    _, _, distance = _WGS84.inv(left[0], left[1], right[0], right[1])
    return float(distance)


def _forward_azimuth_degrees(
    origin: tuple[float, float], target: tuple[float, float]
) -> float:
    azimuth, _, distance = _WGS84.inv(
        origin[0], origin[1], target[0], target[1]
    )
    if distance <= 0.0:
        raise ValueError("geographic_junction_branch_direction_undefined")
    return float(azimuth % 360.0)


def _azimuth_difference_degrees(left: float, right: float) -> float:
    return abs((right - left + 180.0) % 360.0 - 180.0)
