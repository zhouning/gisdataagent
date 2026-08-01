"""Compile public hydrography and raster evidence into a kernel fixture."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .coupled_junction_patch_reach_patch_friction import (
    JunctionPatchCellManningRoughness,
    JunctionPatchManningRoughnessField,
)
from .shallow_water_junction_patch import (
    JunctionPatchCellGeometry,
    JunctionPatchFace,
    JunctionPatchVertex,
    ShallowWaterJunctionPatchGeometry,
)


PUBLIC_CONFLUENCE_FIXTURE_SCHEMA = (
    "gwm.geospatial_kernel.public_confluence_fixture.v1"
)
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage21_center_hill_public_confluence"
)
EXPECTED_ACQUISITION_SCHEMA = (
    "gwm.geotransport.stage21_public_confluence_acquisition.v1"
)
TARGET_JUNCTION_ID = "18421703"
TARGET_FEATURES = {
    "18421705": "upstream",
    "18421707": "upstream",
    "18421703": "downstream",
}
TARGET_JUNCTION_COORDINATE = (-85.909170702, 36.178724498)
PATCH_APOTHEM_M = 15.0
PATCH_CORNER_TRIM_FRACTION = 0.22
REFERENCE_DISTANCE_M = 30.0
EARTH_RADIUS_M = 6_378_137.0
TERMINAL_SNAP_TOLERANCE_M = 0.5
OPENING_ALIGNMENT_TOLERANCE_DEGREES = 1e-8


LAND_COVER_ROUGHNESS_PRIORS = {
    111: {
        "label": "open_water",
        "manning_n": 0.030,
        "lower": 0.025,
        "upper": 0.040,
    },
    121: {
        "label": "developed_open_space",
        "manning_n": 0.050,
        "lower": 0.035,
        "upper": 0.080,
    },
    122: {
        "label": "developed_low_intensity",
        "manning_n": 0.060,
        "lower": 0.040,
        "upper": 0.100,
    },
    123: {
        "label": "developed_medium_intensity",
        "manning_n": 0.050,
        "lower": 0.035,
        "upper": 0.080,
    },
    124: {
        "label": "developed_high_intensity",
        "manning_n": 0.040,
        "lower": 0.030,
        "upper": 0.060,
    },
    131: {
        "label": "barren",
        "manning_n": 0.035,
        "lower": 0.025,
        "upper": 0.060,
    },
    141: {
        "label": "deciduous_forest",
        "manning_n": 0.100,
        "lower": 0.070,
        "upper": 0.160,
    },
    142: {
        "label": "evergreen_forest",
        "manning_n": 0.110,
        "lower": 0.075,
        "upper": 0.170,
    },
    143: {
        "label": "mixed_forest",
        "manning_n": 0.105,
        "lower": 0.070,
        "upper": 0.165,
    },
    152: {
        "label": "shrubland",
        "manning_n": 0.070,
        "lower": 0.045,
        "upper": 0.120,
    },
    176: {
        "label": "grassland_pasture",
        "manning_n": 0.050,
        "lower": 0.035,
        "upper": 0.085,
    },
    190: {
        "label": "woody_wetlands",
        "manning_n": 0.120,
        "lower": 0.080,
        "upper": 0.180,
    },
    195: {
        "label": "herbaceous_wetlands",
        "manning_n": 0.070,
        "lower": 0.050,
        "upper": 0.120,
    },
}


@dataclass(frozen=True)
class PublicConfluenceBranch:
    feature_id: str
    role: str
    junction_coordinate_wgs84: tuple[float, float]
    reference_coordinate_wgs84: tuple[float, float]
    sampled_reference_distance_m: float
    available_centerline_length_m: float
    terminal_snap_distance_m: float
    flow_azimuth_degrees: float
    opening_outward_azimuth_degrees: float

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "role": self.role,
            "junction_coordinate_wgs84": list(
                self.junction_coordinate_wgs84
            ),
            "reference_coordinate_wgs84": list(
                self.reference_coordinate_wgs84
            ),
            "sampled_reference_distance_m": self.sampled_reference_distance_m,
            "available_centerline_length_m": self.available_centerline_length_m,
            "terminal_snap_distance_m": self.terminal_snap_distance_m,
            "flow_azimuth_degrees": self.flow_azimuth_degrees,
            "opening_outward_azimuth_degrees": (
                self.opening_outward_azimuth_degrees
            ),
            "centerline_is_surveyed_cross_section": False,
        }


@dataclass(frozen=True)
class PublicConfluenceCellEvidence:
    cell_id: str
    vertex_ids: tuple[str, ...]
    support_area_m2: float
    terrain_sample_count: int
    terrain_nearest_fallback: bool
    terrain_minimum_m: float
    terrain_mean_m: float
    terrain_maximum_m: float
    land_cover_sample_count: int
    land_cover_nearest_fallback: bool
    land_cover_counts: tuple[tuple[int, int], ...]
    dominant_land_cover_code: int
    dominant_land_cover_label: str
    manning_n_prior: float
    manning_n_lower: float
    manning_n_upper: float

    def as_dict(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "vertex_ids_counterclockwise": list(self.vertex_ids),
            "support_area_m2": self.support_area_m2,
            "terrain": {
                "sample_count": self.terrain_sample_count,
                "nearest_sample_fallback": self.terrain_nearest_fallback,
                "minimum_m": self.terrain_minimum_m,
                "mean_m": self.terrain_mean_m,
                "maximum_m": self.terrain_maximum_m,
                "role": "bare_earth_surface_context_not_channel_bed",
            },
            "land_cover": {
                "sample_count": self.land_cover_sample_count,
                "nearest_sample_fallback": self.land_cover_nearest_fallback,
                "class_counts": {
                    str(code): count for code, count in self.land_cover_counts
                },
                "dominant_class_code": self.dominant_land_cover_code,
                "dominant_class_label": self.dominant_land_cover_label,
                "source_classification": "USDA_NASS_CDL_2024",
            },
            "roughness_prior": {
                "manning_n": self.manning_n_prior,
                "lower": self.manning_n_lower,
                "upper": self.manning_n_upper,
                "aggregation": "sample_count_weighted_class_lookup",
                "calibrated": False,
            },
        }


@dataclass(frozen=True)
class PublicConfluenceGauge:
    site_id: str
    station_name: str
    coordinate_wgs84: tuple[float, float]
    distance_from_junction_m: float
    observed_parameter_code: str
    observed_quantity: str
    observed_unit: str
    observation_count: int
    observation_start: str
    observation_end: str
    observation_artifact_path: str
    observation_artifact_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "station_name": self.station_name,
            "coordinate_wgs84": list(self.coordinate_wgs84),
            "distance_from_junction_m": self.distance_from_junction_m,
            "observed_parameter_code": self.observed_parameter_code,
            "observed_quantity": self.observed_quantity,
            "observed_unit": self.observed_unit,
            "observation_count": self.observation_count,
            "observation_start": self.observation_start,
            "observation_end": self.observation_end,
            "observation_artifact": {
                "path": self.observation_artifact_path,
                "sha256": self.observation_artifact_sha256,
            },
            "admissible_roles": [
                "scalar_discharge_boundary_or_outcome",
                "mass_transport_timing_evidence",
            ],
            "inadmissible_roles": [
                "two_dimensional_velocity_vector",
                "two_component_momentum_observation",
                "junction_reaction_observation",
            ],
        }


@dataclass(frozen=True)
class PublicConfluenceFixture:
    junction_id: str
    junction_coordinate_wgs84: tuple[float, float]
    branches: tuple[PublicConfluenceBranch, ...]
    diagnostic_horizontal_geometry: ShallowWaterJunctionPatchGeometry
    roughness_prior_field: JunctionPatchManningRoughnessField
    cell_evidence: tuple[PublicConfluenceCellEvidence, ...]
    gauge: PublicConfluenceGauge
    vertex_coordinates_wgs84: tuple[tuple[str, float, float], ...]
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def require_runtime_hydraulic_geometry(
        self,
    ) -> ShallowWaterJunctionPatchGeometry:
        raise ValueError("public_confluence_bathymetry_and_cross_sections_missing")

    def as_dict(self) -> dict[str, object]:
        branch_by_id = {value.feature_id: value for value in self.branches}
        opening_alignment = []
        for face in self.diagnostic_horizontal_geometry.branch_faces:
            _, normal, _ = self.diagnostic_horizontal_geometry.face_measure(face)
            actual = _vector_azimuth(normal)
            expected = branch_by_id[str(face.branch_id)].opening_outward_azimuth_degrees
            opening_alignment.append(
                {
                    "feature_id": str(face.branch_id),
                    "expected_outward_azimuth_degrees": expected,
                    "geometry_outward_azimuth_degrees": actual,
                    "absolute_error_degrees": _angular_difference(
                        actual, expected
                    ),
                }
            )
        return {
            "schema": PUBLIC_CONFLUENCE_FIXTURE_SCHEMA,
            "junction": {
                "junction_id": self.junction_id,
                "coordinate_wgs84": list(self.junction_coordinate_wgs84),
                "topology": {
                    "upstream_feature_ids": [
                        value.feature_id
                        for value in self.branches
                        if value.role == "upstream"
                    ],
                    "downstream_feature_id": next(
                        value.feature_id
                        for value in self.branches
                        if value.role == "downstream"
                    ),
                    "single_outlet": True,
                },
            },
            "branches": [value.as_dict() for value in self.branches],
            "computational_patch_support": {
                "geometry": self.diagnostic_horizontal_geometry.as_dict(),
                "vertex_coordinates_wgs84": [
                    {
                        "vertex_id": vertex_id,
                        "longitude": longitude,
                        "latitude": latitude,
                    }
                    for vertex_id, longitude, latitude in self.vertex_coordinates_wgs84
                ],
                "construction": {
                    "method": (
                        "three_branch_centerline_normal_half_planes_with_"
                        "trimmed_corners_and_triangular_fan_cells"
                    ),
                    "apothem_m": PATCH_APOTHEM_M,
                    "corner_trim_fraction": PATCH_CORNER_TRIM_FRACTION,
                    "local_projection": (
                        "WGS84_local_equirectangular_at_junction"
                    ),
                    "opening_normals_derived_from_nldi_centerlines": True,
                    "surveyed_bank_polygon": False,
                    "surveyed_opening_width": False,
                    "computational_support_only": True,
                    "bed_elevation_semantics": (
                        "local_placeholder_zero_not_terrain_or_channel_bed"
                    ),
                },
                "opening_alignment": opening_alignment,
            },
            "cell_evidence": [value.as_dict() for value in self.cell_evidence],
            "roughness_prior_field": self.roughness_prior_field.as_dict(),
            "gauge": self.gauge.as_dict(),
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "kernel_binding": {
                "stage17_horizontal_geometry_contract_compiles": True,
                "stage20_spatial_roughness_contract_compiles": True,
                "runtime_hydraulic_geometry_admitted": False,
                "runtime_refusal_reasons": [
                    "public_bathymetry_missing",
                    "surveyed_cross_sections_missing",
                    "land_cover_to_manning_mapping_not_calibrated",
                    "two_dimensional_momentum_observations_missing",
                ],
            },
            "claim_boundary": {
                "real_public_hydrography_bound": True,
                "real_public_terrain_context_bound": True,
                "real_public_land_cover_bound": True,
                "real_public_scalar_gauge_observation_bound": True,
                "roughness_calibrated": False,
                "terrain_treated_as_channel_bathymetry": False,
                "gauge_treated_as_vector_momentum": False,
                "public_vector_momentum_validation_completed": False,
                "operator_admitted": False,
            },
        }


def compile_public_confluence_fixture(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicConfluenceFixture:
    root = Path(source_root)
    repository = Path(repo_root).resolve()
    manifest = _read_json(root / "acquisition_manifest.json")
    _validate_manifest(manifest)
    verified = _verify_manifest_artifacts(manifest, repository)
    artifact_by_source = {
        str(value["source_id"]): value for value in manifest["artifacts"]
    }
    nldi = _read_json(
        _resolve_artifact_path(
            artifact_by_source["usgs_nldi_flowlines_2km"], repository
        )
    )
    terrain_samples = _read_json(
        _derived_path(manifest, "three_dep_elevation_samples.json", repository)
    )
    land_cover_samples = _read_json(
        _derived_path(manifest, "cdl_2024_samples.json", repository)
    )
    site = _parse_nwis_site(
        _resolve_artifact_path(
            artifact_by_source["usgs_nwis_site_03424860"], repository
        )
    )
    reused = manifest["reused_public_observation"]
    observation_path = _resolve_relative_path(str(reused["path"]), repository)
    observation = _read_json(observation_path)

    branches = _compile_branches(nldi)
    source_digest = hashlib.sha256(
        "|".join(
            sorted(str(value["sha256"]) for value in verified)
        ).encode("ascii")
    ).hexdigest()
    provenance_id = f"public-stage21:center-hill:{source_digest}"
    geometry = _compile_horizontal_geometry(branches, provenance_id)
    cells = _compile_cell_evidence(
        geometry,
        terrain_samples=terrain_samples,
        land_cover_samples=land_cover_samples,
    )
    roughness = JunctionPatchManningRoughnessField(
        geometry.junction_id,
        geometry.provenance_id,
        tuple(
            JunctionPatchCellManningRoughness(
                value.cell_id,
                value.manning_n_prior,
                value.support_area_m2,
                (
                    "usda-cdl-2024:class-count-weighted-prior:"
                    f"{value.cell_id}:{source_digest}"
                ),
            )
            for value in cells
        ),
        f"usda-cdl-2024:uncalibrated-manning-prior:{source_digest}",
    )
    gauge = _compile_gauge(site, observation, reused)
    vertices_wgs84 = tuple(
        (
            vertex.vertex_id,
            *_local_to_wgs84(
                vertex.east_m,
                vertex.north_m,
                TARGET_JUNCTION_COORDINATE,
            ),
        )
        for vertex in geometry.vertices
    )
    source_artifacts = tuple(
        {
            "path": str(value["path"]),
            "size_bytes": int(value["size_bytes"]),
            "sha256": str(value["sha256"]),
            "source_id": value.get("source_id", "derived_or_reused"),
            "role": value.get("role", "derived_spatial_evidence"),
            "identity_matches": True,
        }
        for value in verified
    )
    return PublicConfluenceFixture(
        TARGET_JUNCTION_ID,
        TARGET_JUNCTION_COORDINATE,
        branches,
        geometry,
        roughness,
        cells,
        gauge,
        vertices_wgs84,
        source_artifacts,
        provenance_id,
    )


def _validate_manifest(manifest: dict[str, Any]) -> None:
    boundary = manifest.get("request_boundary", {})
    claims = manifest.get("claim_boundary", {})
    if (
        manifest.get("schema") != EXPECTED_ACQUISITION_SCHEMA
        or manifest.get("mode") != "values"
        or int(manifest.get("artifact_count", -1)) != 6
        or int(manifest.get("total_downloaded_bytes", 1_000_001))
        > 1_000_000
        or boundary.get("workspace_or_private_data_sent") is not False
        or claims.get("terrain_is_channel_bathymetry") is not False
        or claims.get("land_cover_prior_is_calibrated_roughness") is not False
        or claims.get("gauge_discharge_is_two_dimensional_momentum") is not False
    ):
        raise ValueError("public_confluence_acquisition_manifest_invalid")


def _verify_manifest_artifacts(
    manifest: dict[str, Any], repo_root: Path
) -> tuple[dict[str, object], ...]:
    values = [
        *manifest["artifacts"],
        *manifest["derived_artifacts"],
        manifest["reused_public_observation"],
    ]
    verified = []
    for value in values:
        path = _resolve_relative_path(str(value["path"]), repo_root)
        body = path.read_bytes()
        actual = hashlib.sha256(body).hexdigest()
        expected_size = int(
            value.get("size_bytes", value.get("actual_size_bytes", -1))
        )
        expected_hash = str(value.get("sha256", value.get("actual_sha256", "")))
        if len(body) != expected_size or actual != expected_hash:
            raise ValueError("public_confluence_source_artifact_identity_mismatch")
        verified.append(
            {
                **value,
                "size_bytes": len(body),
                "sha256": actual,
                "identity_matches": True,
            }
        )
    return tuple(verified)


def _compile_branches(nldi: dict[str, Any]) -> tuple[PublicConfluenceBranch, ...]:
    feature_by_id = {
        str(feature["properties"]["nhdplus_comid"]): feature
        for feature in nldi.get("features", [])
    }
    branches = []
    for feature_id, role in TARGET_FEATURES.items():
        if feature_id not in feature_by_id:
            raise ValueError("public_confluence_target_flowline_missing")
        geometry = feature_by_id[feature_id].get("geometry", {})
        if geometry.get("type") != "LineString":
            raise ValueError("public_confluence_flowline_geometry_invalid")
        coordinates = tuple(
            (float(value[0]), float(value[1]))
            for value in geometry.get("coordinates", [])
        )
        if len(coordinates) < 2:
            raise ValueError("public_confluence_flowline_geometry_invalid")
        endpoint_index = min(
            (0, len(coordinates) - 1),
            key=lambda index: _distance_m(
                coordinates[index], TARGET_JUNCTION_COORDINATE
            ),
        )
        endpoint = coordinates[endpoint_index]
        snap = _distance_m(endpoint, TARGET_JUNCTION_COORDINATE)
        if snap > TERMINAL_SNAP_TOLERANCE_M:
            raise ValueError("public_confluence_terminal_snap_exceeded")
        reference, sampled, available = _sample_from_endpoint(
            coordinates, endpoint_index, REFERENCE_DISTANCE_M
        )
        outward = _bearing_degrees(TARGET_JUNCTION_COORDINATE, reference)
        flow = outward if role == "downstream" else (outward + 180.0) % 360.0
        branches.append(
            PublicConfluenceBranch(
                feature_id,
                role,
                TARGET_JUNCTION_COORDINATE,
                reference,
                sampled,
                available,
                snap,
                flow,
                outward,
            )
        )
    return tuple(branches)


def _compile_horizontal_geometry(
    branches: tuple[PublicConfluenceBranch, ...], provenance_id: str
) -> ShallowWaterJunctionPatchGeometry:
    sides = sorted(
        (
            (
                _azimuth_unit(value.opening_outward_azimuth_degrees),
                value,
            )
            for value in branches
        )
        ,
        key=lambda value: (
            math.atan2(value[0][1], value[0][0]) % (2.0 * math.pi)
        ),
    )
    if any(
        _ccw_angle_gap(sides[index][0], sides[(index + 1) % len(sides)][0])
        >= math.pi
        for index in range(len(sides))
    ):
        raise ValueError("public_confluence_opening_normals_do_not_bound_patch")
    full_vertices = []
    for index, (normal, _) in enumerate(sides):
        previous = sides[index - 1][0]
        following = sides[(index + 1) % len(sides)][0]
        start = _half_plane_intersection(previous, normal, PATCH_APOTHEM_M)
        end = _half_plane_intersection(normal, following, PATCH_APOTHEM_M)
        full_vertices.append((start, end))
    boundary: list[tuple[float, float]] = []
    for start, end in full_vertices:
        delta = (end[0] - start[0], end[1] - start[1])
        boundary.extend(
            (
                (
                    start[0] + PATCH_CORNER_TRIM_FRACTION * delta[0],
                    start[1] + PATCH_CORNER_TRIM_FRACTION * delta[1],
                ),
                (
                    end[0] - PATCH_CORNER_TRIM_FRACTION * delta[0],
                    end[1] - PATCH_CORNER_TRIM_FRACTION * delta[1],
                ),
            )
        )
    vertices = (
        JunctionPatchVertex("center", 0.0, 0.0),
        *tuple(
            JunctionPatchVertex(f"b{index:02d}", *coordinate)
            for index, coordinate in enumerate(boundary)
        ),
    )
    cell_count = len(boundary)
    cells = tuple(
        JunctionPatchCellGeometry(
            f"cell-{index:02d}",
            ("center", f"b{index:02d}", f"b{(index + 1) % cell_count:02d}"),
        )
        for index in range(cell_count)
    )
    faces = []
    for index, cell in enumerate(cells):
        faces.append(
            JunctionPatchFace(
                f"internal-radial-{index:02d}",
                cell.cell_id,
                "center",
                f"b{index:02d}",
                "internal",
                right_cell_id=cells[index - 1].cell_id,
            )
        )
        next_vertex = f"b{(index + 1) % cell_count:02d}"
        if index % 2 == 0:
            branch = sides[index // 2][1]
            faces.append(
                JunctionPatchFace(
                    f"opening-{branch.feature_id}",
                    cell.cell_id,
                    f"b{index:02d}",
                    next_vertex,
                    "branch_opening",
                    branch_id=branch.feature_id,
                    branch_role=branch.role,
                )
            )
        else:
            faces.append(
                JunctionPatchFace(
                    f"wall-{index:02d}",
                    cell.cell_id,
                    f"b{index:02d}",
                    next_vertex,
                    "solid_wall",
                )
            )
    geometry = ShallowWaterJunctionPatchGeometry(
        TARGET_JUNCTION_ID,
        0.0,
        vertices,
        cells,
        tuple(faces),
        f"{provenance_id}:diagnostic-horizontal-support",
    )
    branch_by_id = {value.feature_id: value for value in branches}
    for face in geometry.branch_faces:
        _, normal, _ = geometry.face_measure(face)
        error = _angular_difference(
            _vector_azimuth(normal),
            branch_by_id[str(face.branch_id)].opening_outward_azimuth_degrees,
        )
        if error > OPENING_ALIGNMENT_TOLERANCE_DEGREES:
            raise ValueError("public_confluence_opening_alignment_failed")
    return geometry


def _compile_cell_evidence(
    geometry: ShallowWaterJunctionPatchGeometry,
    *,
    terrain_samples: dict[str, Any],
    land_cover_samples: dict[str, Any],
) -> tuple[PublicConfluenceCellEvidence, ...]:
    if (
        terrain_samples.get("schema")
        != "gwm.geotransport.public_terrain_samples.v1"
        or terrain_samples.get("bathymetry") is not False
        or land_cover_samples.get("schema")
        != "gwm.geotransport.public_land_cover_samples.v1"
        or land_cover_samples.get("classification") != "USDA_NASS_CDL_2024"
    ):
        raise ValueError("public_confluence_raster_sample_contract_invalid")
    terrain = tuple(
        (
            *_wgs84_to_local(
                float(value["longitude"]),
                float(value["latitude"]),
                TARGET_JUNCTION_COORDINATE,
            ),
            float(value["elevation_m"]),
        )
        for value in terrain_samples["samples"]
    )
    land_cover = tuple(
        (
            *_wgs84_to_local(
                float(value["longitude"]),
                float(value["latitude"]),
                TARGET_JUNCTION_COORDINATE,
            ),
            int(value["class_code"]),
        )
        for value in land_cover_samples["samples"]
        if int(value["class_code"]) > 0
    )
    if not terrain or not land_cover:
        raise ValueError("public_confluence_raster_samples_empty")
    vertices = geometry.vertex_by_id
    areas = geometry.cell_areas_m2
    results = []
    for cell in geometry.cells:
        polygon = tuple(
            (vertices[value].east_m, vertices[value].north_m)
            for value in cell.vertex_ids
        )
        centroid = _polygon_centroid(polygon)
        selected_terrain = [
            value[2]
            for value in terrain
            if _point_in_polygon((value[0], value[1]), polygon)
        ]
        terrain_fallback = not selected_terrain
        if terrain_fallback:
            selected_terrain = [
                min(
                    terrain,
                    key=lambda value: _squared_distance(value, centroid),
                )[2]
            ]
        selected_cover = [
            value[2]
            for value in land_cover
            if _point_in_polygon((value[0], value[1]), polygon)
        ]
        cover_fallback = not selected_cover
        if cover_fallback:
            selected_cover = [
                min(
                    land_cover,
                    key=lambda value: _squared_distance(value, centroid),
                )[2]
            ]
        unknown = sorted(set(selected_cover) - set(LAND_COVER_ROUGHNESS_PRIORS))
        if unknown:
            raise ValueError(
                "public_confluence_land_cover_class_unmapped:" 
                + ",".join(str(value) for value in unknown)
            )
        counts = tuple(
            sorted(
                (code, selected_cover.count(code))
                for code in set(selected_cover)
            )
        )
        dominant = max(counts, key=lambda value: (value[1], -value[0]))[0]
        count = len(selected_cover)

        def weighted(key: str) -> float:
            return sum(
                float(LAND_COVER_ROUGHNESS_PRIORS[code][key]) * frequency
                for code, frequency in counts
            ) / count

        results.append(
            PublicConfluenceCellEvidence(
                cell.cell_id,
                cell.vertex_ids,
                areas[cell.cell_id],
                len(selected_terrain),
                terrain_fallback,
                min(selected_terrain),
                sum(selected_terrain) / len(selected_terrain),
                max(selected_terrain),
                len(selected_cover),
                cover_fallback,
                counts,
                dominant,
                str(LAND_COVER_ROUGHNESS_PRIORS[dominant]["label"]),
                weighted("manning_n"),
                weighted("lower"),
                weighted("upper"),
            )
        )
    return tuple(results)


def _compile_gauge(
    site: dict[str, str],
    observation: dict[str, Any],
    reused: dict[str, Any],
) -> PublicConfluenceGauge:
    series = observation.get("value", {}).get("timeSeries", [])
    if len(series) != 1:
        raise ValueError("public_confluence_gauge_series_invalid")
    value = series[0]
    variable = value["variable"]
    code = str(variable["variableCode"][0]["value"])
    samples = value.get("values", [{}])[0].get("value", [])
    if code != "00060" or not samples:
        raise ValueError("public_confluence_gauge_quantity_invalid")
    coordinate = (float(site["dec_long_va"]), float(site["dec_lat_va"]))
    return PublicConfluenceGauge(
        site["site_no"],
        site["station_nm"],
        coordinate,
        _distance_m(TARGET_JUNCTION_COORDINATE, coordinate),
        code,
        "scalar_stream_discharge",
        str(variable["unit"]["unitCode"]),
        len(samples),
        str(samples[0]["dateTime"]),
        str(samples[-1]["dateTime"]),
        str(reused["path"]),
        str(reused["sha256"]),
    )


def _parse_nwis_site(path: Path) -> dict[str, str]:
    rows = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    if len(rows) < 3:
        raise ValueError("public_confluence_nwis_site_invalid")
    header = rows[0].split("\t")
    values = next(
        (
            line.split("\t")
            for line in rows[2:]
            if "\t03424860\t" in f"\t{line}\t"
        ),
        None,
    )
    if values is None or len(values) != len(header):
        raise ValueError("public_confluence_nwis_site_invalid")
    result = dict(zip(header, values, strict=True))
    if result.get("agency_cd") != "USGS" or result.get("site_no") != "03424860":
        raise ValueError("public_confluence_nwis_site_identity_mismatch")
    return result


def _sample_from_endpoint(
    coordinates: tuple[tuple[float, float], ...],
    endpoint_index: int,
    requested_distance_m: float,
) -> tuple[tuple[float, float], float, float]:
    ordered = coordinates if endpoint_index == 0 else tuple(reversed(coordinates))
    segments = [
        _distance_m(left, right)
        for left, right in zip(ordered[:-1], ordered[1:], strict=True)
    ]
    available = sum(segments)
    target = min(requested_distance_m, available)
    elapsed = 0.0
    for left, right, length in zip(
        ordered[:-1], ordered[1:], segments, strict=True
    ):
        if elapsed + length >= target:
            fraction = 0.0 if length == 0.0 else (target - elapsed) / length
            return (
                (
                    left[0] + fraction * (right[0] - left[0]),
                    left[1] + fraction * (right[1] - left[1]),
                ),
                target,
                available,
            )
        elapsed += length
    return ordered[-1], available, available


def _half_plane_intersection(
    left: tuple[float, float],
    right: tuple[float, float],
    offset: float,
) -> tuple[float, float]:
    determinant = left[0] * right[1] - left[1] * right[0]
    if abs(determinant) <= 1e-12:
        raise ValueError("public_confluence_parallel_opening_normals")
    return (
        offset * (right[1] - left[1]) / determinant,
        offset * (left[0] - right[0]) / determinant,
    )


def _azimuth_unit(azimuth_degrees: float) -> tuple[float, float]:
    radians = math.radians(azimuth_degrees)
    return math.sin(radians), math.cos(radians)


def _vector_azimuth(vector: tuple[float, float]) -> float:
    return math.degrees(math.atan2(vector[0], vector[1])) % 360.0


def _ccw_angle_gap(
    left: tuple[float, float], right: tuple[float, float]
) -> float:
    left_angle = math.atan2(left[1], left[0]) % (2.0 * math.pi)
    right_angle = math.atan2(right[1], right[0]) % (2.0 * math.pi)
    return (right_angle - left_angle) % (2.0 * math.pi)


def _angular_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _bearing_degrees(
    start: tuple[float, float], end: tuple[float, float]
) -> float:
    east, north = _wgs84_to_local(end[0], end[1], start)
    return math.degrees(math.atan2(east, north)) % 360.0


def _distance_m(
    left: tuple[float, float], right: tuple[float, float]
) -> float:
    latitude_left = math.radians(left[1])
    latitude_right = math.radians(right[1])
    delta_latitude = latitude_right - latitude_left
    delta_longitude = math.radians(right[0] - left[0])
    value = (
        math.sin(delta_latitude / 2.0) ** 2
        + math.cos(latitude_left)
        * math.cos(latitude_right)
        * math.sin(delta_longitude / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(value)))


def _wgs84_to_local(
    longitude: float,
    latitude: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    return (
        math.radians(longitude - origin[0])
        * EARTH_RADIUS_M
        * math.cos(math.radians(origin[1])),
        math.radians(latitude - origin[1]) * EARTH_RADIUS_M,
    )


def _local_to_wgs84(
    east_m: float,
    north_m: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    return (
        origin[0]
        + math.degrees(
            east_m / (EARTH_RADIUS_M * math.cos(math.radians(origin[1])))
        ),
        origin[1] + math.degrees(north_m / EARTH_RADIUS_M),
    )


def _point_in_polygon(
    point: tuple[float, float], polygon: tuple[tuple[float, float], ...]
) -> bool:
    inside = False
    for left, right in zip(
        polygon, (*polygon[1:], polygon[0]), strict=True
    ):
        cross = (
            (right[0] - left[0]) * (point[1] - left[1])
            - (right[1] - left[1]) * (point[0] - left[0])
        )
        if abs(cross) <= 1e-9 and (
            min(left[0], right[0]) - 1e-9
            <= point[0]
            <= max(left[0], right[0]) + 1e-9
            and min(left[1], right[1]) - 1e-9
            <= point[1]
            <= max(left[1], right[1]) + 1e-9
        ):
            return True
        crosses = (left[1] > point[1]) != (right[1] > point[1])
        if crosses:
            x_intersection = left[0] + (
                (point[1] - left[1])
                * (right[0] - left[0])
                / (right[1] - left[1])
            )
            if point[0] < x_intersection:
                inside = not inside
    return inside


def _polygon_centroid(
    polygon: tuple[tuple[float, float], ...]
) -> tuple[float, float]:
    return (
        sum(value[0] for value in polygon) / len(polygon),
        sum(value[1] for value in polygon) / len(polygon),
    )


def _squared_distance(
    sample: tuple[float, float, object], point: tuple[float, float]
) -> float:
    return (sample[0] - point[0]) ** 2 + (sample[1] - point[1]) ** 2


def _derived_path(
    manifest: dict[str, Any], name: str, repo_root: Path
) -> Path:
    value = next(
        (
            item
            for item in manifest["derived_artifacts"]
            if Path(str(item["path"])).name == name
        ),
        None,
    )
    if value is None:
        raise ValueError("public_confluence_derived_artifact_missing")
    return _resolve_artifact_path(value, repo_root)


def _resolve_artifact_path(value: dict[str, Any], repo_root: Path) -> Path:
    return _resolve_relative_path(str(value["path"]), repo_root)


def _resolve_relative_path(relative: str, repo_root: Path) -> Path:
    path = (repo_root / relative).resolve()
    if path != repo_root and repo_root not in path.parents:
        raise ValueError("public_confluence_artifact_path_outside_repository")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

