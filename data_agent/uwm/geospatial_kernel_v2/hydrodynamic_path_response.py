"""Typed hydrodynamic scales along a directed river path."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .branching_network import DirectedReachNetwork
from .contracts import ReachHydraulicGeometry
from .manning_path_response import (
    ManningPathResponseDiagnostic,
    ManningReachResponse,
)


HYDRODYNAMIC_PATH_RESPONSE_SCHEMA = (
    "gwm.geospatial_kernel.hydrodynamic_path_response_diagnostic.v1"
)
STANDARD_GRAVITY_MPS2 = 9.80665


@dataclass(frozen=True)
class HydrodynamicReachScale:
    feature_id: int
    effective_length_m: float
    discharge_m3s: float
    area_m2: float
    depth_m: float
    top_width_m: float
    mean_velocity_mps: float
    manning_dq_da_celerity_mps: float
    gravity_wave_celerity_mps: float
    froude_number: float | None
    hydraulic_diffusivity_m2s: float
    reach_peclet_number: float | None
    manning_centroid_travel_time_seconds: float | None
    gravity_wave_travel_time_seconds: float | None
    diffusive_first_passage_variance_seconds2: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "effective_length_m": self.effective_length_m,
            "discharge_m3s": self.discharge_m3s,
            "area_m2": self.area_m2,
            "depth_m": self.depth_m,
            "top_width_m": self.top_width_m,
            "mean_velocity_mps": self.mean_velocity_mps,
            "manning_dq_da_celerity_mps": self.manning_dq_da_celerity_mps,
            "gravity_wave_celerity_mps": self.gravity_wave_celerity_mps,
            "froude_number": self.froude_number,
            "hydraulic_diffusivity_m2s": self.hydraulic_diffusivity_m2s,
            "reach_peclet_number": self.reach_peclet_number,
            "manning_centroid_travel_time_seconds": (
                self.manning_centroid_travel_time_seconds
            ),
            "gravity_wave_travel_time_seconds": (
                self.gravity_wave_travel_time_seconds
            ),
            "diffusive_first_passage_variance_seconds2": (
                self.diffusive_first_passage_variance_seconds2
            ),
        }


@dataclass(frozen=True)
class HydrodynamicPathResponse:
    path_id: str
    start_feature_id: int
    end_feature_id: int
    feature_ids: tuple[int, ...]
    reaches: tuple[HydrodynamicReachScale, ...]
    total_effective_length_m: float
    manning_centroid_travel_time_seconds: float | None
    gravity_wave_travel_time_seconds: float | None
    diffusive_first_passage_standard_deviation_seconds: float | None
    gravity_to_manning_time_ratio: float | None
    diffusive_spread_to_manning_time_ratio: float | None
    maximum_froude_number: float | None
    minimum_reach_peclet_number: float | None
    nonpropagating_feature_ids: tuple[int, ...]
    supercritical_feature_ids: tuple[int, ...]
    supercritical_effective_length_fraction: float
    supercritical_manning_time_fraction: float | None
    supercritical_gravity_time_fraction: float | None
    outcome_calibrated: bool
    provenance_id: str
    evidence_level: str

    @property
    def finite_path_scales_available(self) -> bool:
        return (
            self.manning_centroid_travel_time_seconds is not None
            and self.gravity_wave_travel_time_seconds is not None
            and self.diffusive_first_passage_standard_deviation_seconds
            is not None
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HYDRODYNAMIC_PATH_RESPONSE_SCHEMA,
            "path_id": self.path_id,
            "start_feature_id": self.start_feature_id,
            "end_feature_id": self.end_feature_id,
            "feature_ids": list(self.feature_ids),
            "reach_count": len(self.reaches),
            "reaches": [value.as_dict() for value in self.reaches],
            "total_effective_length_m": self.total_effective_length_m,
            "manning_centroid_travel_time_seconds": (
                self.manning_centroid_travel_time_seconds
            ),
            "gravity_wave_travel_time_seconds": (
                self.gravity_wave_travel_time_seconds
            ),
            "diffusive_first_passage_standard_deviation_seconds": (
                self.diffusive_first_passage_standard_deviation_seconds
            ),
            "gravity_to_manning_time_ratio": self.gravity_to_manning_time_ratio,
            "diffusive_spread_to_manning_time_ratio": (
                self.diffusive_spread_to_manning_time_ratio
            ),
            "maximum_froude_number": self.maximum_froude_number,
            "minimum_reach_peclet_number": self.minimum_reach_peclet_number,
            "nonpropagating_feature_ids": list(
                self.nonpropagating_feature_ids
            ),
            "supercritical_feature_ids": list(self.supercritical_feature_ids),
            "supercritical_effective_length_fraction": (
                self.supercritical_effective_length_fraction
            ),
            "supercritical_manning_time_fraction": (
                self.supercritical_manning_time_fraction
            ),
            "supercritical_gravity_time_fraction": (
                self.supercritical_gravity_time_fraction
            ),
            "finite_path_scales_available": self.finite_path_scales_available,
            "gravity_wave_quantity": "linear_shallow_water_sqrt_gA_over_T",
            "diffusion_quantity": "linearized_diffusive_wave_Q_over_2_S0_T",
            "diffusive_centroid_quantity": "Manning_kinematic_wave_dQ_dA",
            "outcome_calibrated": self.outcome_calibrated,
            "gravity_wave_time_admitted_as_flood_wave_lag": False,
            "diffusive_spread_admitted_as_flood_wave_lag": False,
            "diagnostic_only": True,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


class HydrodynamicPathResponseDiagnostic:
    """Derive local-inertial and diffusive scales from a Manning base state."""

    def __init__(
        self,
        network: DirectedReachNetwork,
        geometry: ReachHydraulicGeometry,
    ) -> None:
        if geometry.feature_ids != network.feature_ids:
            raise ValueError("hydrodynamic_path_geometry_axis_mismatch")
        self.network = network
        self.geometry = geometry
        self._index = {
            feature: index for index, feature in enumerate(network.feature_ids)
        }
        self._manning = ManningPathResponseDiagnostic(network, geometry)

    def analyze(
        self,
        reach_discharge_m3s: tuple[float, ...],
        *,
        start_feature_id: int,
        end_feature_id: int | None = None,
        path_id: str,
        provenance_id: str,
        evidence_level: str,
        outcome_calibrated: bool,
    ) -> HydrodynamicPathResponse:
        manning = self._manning.analyze(
            reach_discharge_m3s,
            start_feature_id=start_feature_id,
            end_feature_id=end_feature_id,
            path_id=path_id,
            provenance_id=provenance_id,
            evidence_level=evidence_level,
            outcome_calibrated=outcome_calibrated,
        )
        reaches = tuple(self._reach_scale(value) for value in manning.reaches)
        nonpropagating = tuple(
            value.feature_id
            for value in reaches
            if value.gravity_wave_travel_time_seconds is None
            or value.diffusive_first_passage_variance_seconds2 is None
        )
        if nonpropagating:
            gravity_time = None
            diffusion_std = None
        else:
            gravity_time = float(
                sum(
                    value.gravity_wave_travel_time_seconds
                    for value in reaches
                    if value.gravity_wave_travel_time_seconds is not None
                )
            )
            diffusion_std = math.sqrt(
                sum(
                    value.diffusive_first_passage_variance_seconds2
                    for value in reaches
                    if value.diffusive_first_passage_variance_seconds2 is not None
                )
            )
        manning_time = manning.total_travel_time_seconds
        gravity_ratio = (
            None
            if gravity_time is None or manning_time is None
            else float(gravity_time / manning_time)
        )
        diffusion_ratio = (
            None
            if diffusion_std is None or manning_time is None
            else float(diffusion_std / manning_time)
        )
        froude = [
            value.froude_number
            for value in reaches
            if value.froude_number is not None
        ]
        peclet = [
            value.reach_peclet_number
            for value in reaches
            if value.reach_peclet_number is not None
        ]
        supercritical = tuple(
            value for value in reaches if (value.froude_number or 0.0) >= 1.0
        )
        supercritical_length = float(
            sum(value.effective_length_m for value in supercritical)
        )
        supercritical_manning_time = _fraction(
            sum(
                value.manning_centroid_travel_time_seconds or 0.0
                for value in supercritical
            ),
            manning_time,
        )
        supercritical_gravity_time = _fraction(
            sum(
                value.gravity_wave_travel_time_seconds or 0.0
                for value in supercritical
            ),
            gravity_time,
        )
        return HydrodynamicPathResponse(
            path_id=path_id,
            start_feature_id=start_feature_id,
            end_feature_id=manning.end_feature_id,
            feature_ids=manning.feature_ids,
            reaches=reaches,
            total_effective_length_m=manning.total_effective_length_m,
            manning_centroid_travel_time_seconds=manning_time,
            gravity_wave_travel_time_seconds=gravity_time,
            diffusive_first_passage_standard_deviation_seconds=diffusion_std,
            gravity_to_manning_time_ratio=gravity_ratio,
            diffusive_spread_to_manning_time_ratio=diffusion_ratio,
            maximum_froude_number=max(froude) if froude else None,
            minimum_reach_peclet_number=min(peclet) if peclet else None,
            nonpropagating_feature_ids=nonpropagating,
            supercritical_feature_ids=tuple(
                value.feature_id for value in supercritical
            ),
            supercritical_effective_length_fraction=(
                supercritical_length / manning.total_effective_length_m
            ),
            supercritical_manning_time_fraction=supercritical_manning_time,
            supercritical_gravity_time_fraction=supercritical_gravity_time,
            outcome_calibrated=outcome_calibrated,
            provenance_id=provenance_id,
            evidence_level=evidence_level,
        )

    def _reach_scale(self, response: ManningReachResponse) -> HydrodynamicReachScale:
        index = self._index[response.feature_id]
        area = response.manning_area_m2
        bottom_width = float(self.geometry.bottom_width_m[index])
        side_slope = float(
            self.geometry.side_slope_horizontal_per_vertical[index]
        )
        bed_slope = float(self.geometry.bed_slope[index])
        top_width = math.sqrt(bottom_width**2 + 4.0 * side_slope * area)
        depth = 0.0 if area == 0.0 else 2.0 * area / (bottom_width + top_width)
        velocity = 0.0 if area == 0.0 else response.discharge_m3s / area
        gravity_celerity = (
            0.0 if area == 0.0 else math.sqrt(STANDARD_GRAVITY_MPS2 * area / top_width)
        )
        froude = None if gravity_celerity == 0.0 else velocity / gravity_celerity
        diffusivity = (
            0.0
            if response.discharge_m3s == 0.0
            else response.discharge_m3s / (2.0 * bed_slope * top_width)
        )
        kinematic_celerity = response.manning_dq_da_celerity_mps
        peclet = (
            None
            if diffusivity == 0.0 or kinematic_celerity == 0.0
            else kinematic_celerity * response.effective_length_m / diffusivity
        )
        gravity_time = (
            None
            if gravity_celerity == 0.0
            else response.effective_length_m / gravity_celerity
        )
        first_passage_variance = (
            None
            if kinematic_celerity == 0.0
            else (
                2.0
                * diffusivity
                * response.effective_length_m
                / (kinematic_celerity**3)
            )
        )
        manning_time = (
            None
            if kinematic_celerity == 0.0
            else response.effective_length_m / kinematic_celerity
        )
        return HydrodynamicReachScale(
            feature_id=response.feature_id,
            effective_length_m=response.effective_length_m,
            discharge_m3s=response.discharge_m3s,
            area_m2=area,
            depth_m=depth,
            top_width_m=top_width,
            mean_velocity_mps=velocity,
            manning_dq_da_celerity_mps=kinematic_celerity,
            gravity_wave_celerity_mps=gravity_celerity,
            froude_number=froude,
            hydraulic_diffusivity_m2s=diffusivity,
            reach_peclet_number=peclet,
            manning_centroid_travel_time_seconds=manning_time,
            gravity_wave_travel_time_seconds=gravity_time,
            diffusive_first_passage_variance_seconds2=first_passage_variance,
        )


def _fraction(numerator: float, denominator: float | None) -> float | None:
    if denominator is None or denominator <= 0.0:
        return None
    return float(numerator / denominator)
