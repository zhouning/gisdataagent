"""Compile a local ANUGA diagnostic around the registered Makani SWMM subnet."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy.io import netcdf_file
from shapely.geometry import Polygon, box

REGISTERED_ANUGA_COMPILE_SCHEMA = (
    "gwm.abu_dhabi_flood.registered_anuga_surface_compile_receipt.v1"
)


@dataclass(frozen=True)
class RegisteredAnugaDiagnosticPolicy:
    """Resolution and forcing choices for the local public-proxy surface run."""

    domain_padding_m: float = 180.0
    mesh_cell_size_m: float = 20.0
    manning_friction: float = 0.03
    forcing_start_hour_index: int = 33
    forcing_hour_count: int = 10
    output_interval_seconds: float = 900.0
    fixed_boundary_stage_margin_m: float = 1.0

    def __post_init__(self) -> None:
        numeric = (
            self.domain_padding_m,
            self.mesh_cell_size_m,
            self.manning_friction,
            self.output_interval_seconds,
            self.fixed_boundary_stage_margin_m,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0.0
            for value in numeric
        ):
            raise ValueError("registered_anuga_policy_numeric_value_invalid")
        if (
            not isinstance(self.forcing_start_hour_index, int)
            or isinstance(self.forcing_start_hour_index, bool)
            or self.forcing_start_hour_index < 0
            or not isinstance(self.forcing_hour_count, int)
            or isinstance(self.forcing_hour_count, bool)
            or self.forcing_hour_count <= 0
        ):
            raise ValueError("registered_anuga_policy_forcing_window_invalid")
        duration = self.forcing_hour_count * 3600.0
        if not math.isclose(
            duration / self.output_interval_seconds,
            round(duration / self.output_interval_seconds),
        ):
            raise ValueError("registered_anuga_output_interval_must_divide_duration")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _path_label(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("registered_anuga_json_input_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("registered_anuga_json_object_required")
    return payload


def parse_swmm_node_coordinates(
    input_path: Path,
    *,
    expected_node_ids: set[str],
) -> dict[str, tuple[float, float]]:
    """Read the explicit SWMM coordinate section without accepting extra nodes."""

    try:
        lines = input_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("registered_anuga_swmm_input_invalid") from error
    section = ""
    coordinates: dict[str, tuple[float, float]] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].upper()
            continue
        if section != "COORDINATES":
            continue
        values = line.split()
        if len(values) != 3 or values[0] in coordinates:
            raise ValueError("registered_anuga_swmm_coordinates_invalid")
        try:
            x, y = float(values[1]), float(values[2])
        except ValueError as error:
            raise ValueError("registered_anuga_swmm_coordinates_invalid") from error
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("registered_anuga_swmm_coordinates_invalid")
        coordinates[values[0]] = (x, y)
    if set(coordinates) != expected_node_ids:
        raise ValueError("registered_anuga_swmm_node_set_mismatch")
    return dict(sorted(coordinates.items()))


def _aligned_domain_bounds(
    coordinates: dict[str, tuple[float, float]],
    policy: RegisteredAnugaDiagnosticPolicy,
) -> tuple[float, float, float, float]:
    x_values = [point[0] for point in coordinates.values()]
    y_values = [point[1] for point in coordinates.values()]
    size = policy.mesh_cell_size_m
    return (
        math.floor((min(x_values) - policy.domain_padding_m) / size) * size,
        math.floor((min(y_values) - policy.domain_padding_m) / size) * size,
        math.ceil((max(x_values) + policy.domain_padding_m) / size) * size,
        math.ceil((max(y_values) + policy.domain_padding_m) / size) * size,
    )


def _terrain_window(
    dem_path: Path,
    bounds: tuple[float, float, float, float],
) -> dict[str, object]:
    with rasterio.open(dem_path) as dataset:
        if dataset.crs is None or dataset.crs.to_epsg() != 32640 or dataset.count != 1:
            raise ValueError("registered_anuga_dem_grid_invalid")
        resolution_x = abs(float(dataset.transform.a))
        resolution_y = abs(float(dataset.transform.e))
        expanded = (
            bounds[0] - 2.0 * resolution_x,
            bounds[1] - 2.0 * resolution_y,
            bounds[2] + 2.0 * resolution_x,
            bounds[3] + 2.0 * resolution_y,
        )
        window = from_bounds(*expanded, transform=dataset.transform)
        window = window.round_offsets().round_lengths()
        data = dataset.read(1, window=window, masked=True)
        if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] < 2:
            raise ValueError("registered_anuga_dem_window_too_small")
        if bool(np.ma.getmaskarray(data).any()):
            raise ValueError("registered_anuga_dem_window_contains_nodata")
        values = np.asarray(data, dtype=np.float64)
        if not bool(np.isfinite(values).all()):
            raise ValueError("registered_anuga_dem_window_nonfinite")
        transform = dataset.window_transform(window)
        x_centres = np.asarray(
            [transform.c + (column + 0.5) * transform.a for column in range(values.shape[1])]
        )
        y_centres = np.asarray(
            [transform.f + (row + 0.5) * transform.e for row in range(values.shape[0])]
        )
        if not (
            x_centres[0] <= bounds[0] <= bounds[2] <= x_centres[-1]
            and y_centres[-1] <= bounds[1] <= bounds[3] <= y_centres[0]
        ):
            raise ValueError("registered_anuga_dem_window_does_not_cover_domain")
        return {
            "values": values,
            "x_centres": x_centres,
            "y_centres": y_centres,
            "source_crs": dataset.crs.to_string(),
            "source_resolution_m": [resolution_x, resolution_y],
        }


def _sample_dem(
    path: Path,
    coordinates: dict[str, tuple[float, float]],
) -> dict[str, float]:
    with rasterio.open(path) as dataset:
        if dataset.crs is None or dataset.crs.to_epsg() != 32640:
            raise ValueError("registered_anuga_comparison_dem_crs_invalid")
        samples = tuple(dataset.sample(coordinates.values(), masked=True))
    result: dict[str, float] = {}
    for node_id, sample in zip(coordinates, samples, strict=True):
        value = sample[0]
        if np.ma.is_masked(value) or not math.isfinite(float(value)):
            raise ValueError("registered_anuga_comparison_dem_sample_invalid")
        result[node_id] = float(value)
    return result


def audit_local_contours(
    contour_pages_root: Path,
    *,
    bounds: tuple[float, float, float, float],
) -> dict[str, object]:
    """Report the SmartMakani contour evidence intersecting the ANUGA domain."""

    contours = gpd.read_parquet(contour_pages_root)
    if contours.crs is None or contours.crs.to_epsg() != 32640 or "Contour" not in contours:
        raise ValueError("registered_anuga_contour_dataset_invalid")
    domain = box(*bounds)
    local = contours.loc[contours.geometry.intersects(domain)].copy()
    if local.empty:
        raise ValueError("registered_anuga_local_contours_missing")
    clipped = local.geometry.intersection(domain)
    clipped = clipped.loc[~clipped.is_empty]
    elevation_counts = {
        str(int(value)): int(count)
        for value, count in local.loc[clipped.index, "Contour"].value_counts().sort_index().items()
    }
    return {
        "source_record_count": int(len(contours)),
        "intersecting_record_count": int(len(clipped)),
        "source_page_indices": sorted(
            int(value) for value in local.loc[clipped.index, "source_page_index"].unique()
        ),
        "contour_elevation_minimum_m": float(local.loc[clipped.index, "Contour"].min()),
        "contour_elevation_maximum_m": float(local.loc[clipped.index, "Contour"].max()),
        "contour_elevation_record_counts": elevation_counts,
        "clipped_geometry_bounds_epsg32640": [float(value) for value in clipped.total_bounds],
    }


def build_anuga_maximum_depth_layer(
    sww_path: Path,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    """Convert a retained ANUGA SWW result to one maximum-depth triangle layer."""

    try:
        with netcdf_file(sww_path, "r", mmap=False) as dataset:
            x = np.asarray(dataset.variables["x"].data, dtype=np.float64).copy()
            y = np.asarray(dataset.variables["y"].data, dtype=np.float64).copy()
            volumes = np.asarray(dataset.variables["volumes"].data, dtype=np.int64).copy()
            elevation = np.asarray(
                dataset.variables["elevation_c"].data, dtype=np.float64
            ).copy()
            stage = np.asarray(dataset.variables["stage_c"].data, dtype=np.float64).copy()
            times = np.asarray(dataset.variables["time"].data, dtype=np.float64).copy()
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("registered_anuga_sww_invalid") from error
    if (
        x.ndim != 1
        or y.shape != x.shape
        or volumes.ndim != 2
        or volumes.shape[1] != 3
        or elevation.shape != (len(volumes),)
        or stage.ndim != 2
        or stage.shape[1] != len(volumes)
        or times.shape != (stage.shape[0],)
        or volumes.size == 0
        or volumes.min() < 0
        or volumes.max() >= len(x)
    ):
        raise ValueError("registered_anuga_sww_dimensions_invalid")
    if not all(bool(np.isfinite(values).all()) for values in (x, y, elevation, stage, times)):
        raise ValueError("registered_anuga_sww_nonfinite")
    depth = stage - elevation[None, :]
    peak_indices = np.argmax(depth, axis=0)
    cell_indices = np.arange(len(volumes), dtype=np.int64)
    maximum_depth = depth[peak_indices, cell_indices]
    final_depth = depth[-1]
    geometries = [
        Polygon([(float(x[index]), float(y[index])) for index in triangle])
        for triangle in volumes
    ]
    layer = gpd.GeoDataFrame(
        {
            "cell_id": cell_indices,
            "maximum_depth_m": maximum_depth,
            "maximum_depth_time_seconds": times[peak_indices],
            "final_depth_m": final_depth,
            "ever_ge_0_05m": maximum_depth >= 0.05,
            "ever_ge_0_10m": maximum_depth >= 0.10,
            "ever_ge_0_30m": maximum_depth >= 0.30,
        },
        geometry=geometries,
        crs="EPSG:32640",
    )
    areas = np.asarray(layer.geometry.area, dtype=np.float64)
    summary = {
        "feature_count": int(len(layer)),
        "bounds_epsg32640": [float(value) for value in layer.total_bounds],
        "maximum_depth_m": float(maximum_depth.max()),
        "maximum_depth_cell_id": int(np.argmax(maximum_depth)),
        "final_water_volume_m3": float(np.sum(final_depth * areas)),
        "maximum_depth_footprint_area_m2": {
            "ge_0_05m": float(areas[maximum_depth >= 0.05].sum()),
            "ge_0_10m": float(areas[maximum_depth >= 0.10].sum()),
            "ge_0_30m": float(areas[maximum_depth >= 0.30].sum()),
        },
    }
    return layer, summary


def _render_topography_function(terrain: dict[str, object]) -> list[str]:
    values = np.asarray(terrain["values"], dtype=np.float64)
    x_centres = np.asarray(terrain["x_centres"], dtype=np.float64)
    y_centres = np.asarray(terrain["y_centres"], dtype=np.float64)
    lines = [
        "def topography(x, y):",
        f"    result = 0.0 * x + {float(values.mean()):.12f}",
    ]
    for row in range(values.shape[0] - 1):
        north = float(y_centres[row])
        south = float(y_centres[row + 1])
        for column in range(values.shape[1] - 1):
            west = float(x_centres[column])
            east = float(x_centres[column + 1])
            north_west = float(values[row, column])
            north_east = float(values[row, column + 1])
            south_west = float(values[row + 1, column])
            south_east = float(values[row + 1, column + 1])
            lines.extend(
                [
                    (
                        "    selected = "
                        f"(x >= {west:.6f}) & (x <= {east:.6f}) & "
                        f"(y >= {south:.6f}) & (y <= {north:.6f})"
                    ),
                    f"    x_weight = (x[selected] - {west:.6f}) / {east - west:.12f}",
                    f"    y_weight = (y[selected] - {south:.6f}) / {north - south:.12f}",
                    (
                        "    result[selected] = "
                        f"{south_west:.12f} * (1.0 - x_weight) * (1.0 - y_weight) + "
                        f"{south_east:.12f} * x_weight * (1.0 - y_weight) + "
                        f"{north_west:.12f} * (1.0 - x_weight) * y_weight + "
                        f"{north_east:.12f} * x_weight * y_weight"
                    ),
                ]
            )
    lines.extend(["    return result", ""])
    return lines


def _render_model_script(
    *,
    bounds: tuple[float, float, float, float],
    terrain: dict[str, object],
    rainfall_mm: tuple[float, ...],
    policy: RegisteredAnugaDiagnosticPolicy,
) -> tuple[str, dict[str, object]]:
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    cells_x = int(round(width / policy.mesh_cell_size_m))
    cells_y = int(round(height / policy.mesh_cell_size_m))
    duration_seconds = float(policy.forcing_hour_count * 3600)
    values = np.asarray(terrain["values"], dtype=np.float64)
    fixed_boundary_stage = float(values.min() - policy.fixed_boundary_stage_margin_m)
    lines = [
        '"""Generated local Abu Dhabi ANUGA surface diagnostic; public proxies only."""',
        "",
        "import anuga",
        "",
        f"RAINFALL_MM = {tuple(float(value) for value in rainfall_mm)!r}",
        "",
    ]
    lines.extend(_render_topography_function(terrain))
    lines.extend(
        [
            "def rainfall_rate(t):",
            "    hour = int(t // 3600.0)",
            "    if 0 <= hour < len(RAINFALL_MM):",
            "        return RAINFALL_MM[hour] * 0.001 / 3600.0",
            "    return 0.0",
            "",
            "domain = anuga.rectangular_cross_domain(",
            f"    {cells_x}, {cells_y},",
            f"    len1={width:.6f}, len2={height:.6f},",
            f"    origin=({bounds[0]:.6f}, {bounds[1]:.6f}),",
            ")",
            'domain.set_name("registered_surface_openmeteo")',
            'domain.set_quantity("elevation", topography)',
            f'domain.set_quantity("friction", {policy.manning_friction:.12f})',
            'domain.set_quantity("stage", expression="elevation")',
            "print(domain.statistics())",
            f"open_boundary = anuga.Dirichlet_boundary([{fixed_boundary_stage:.12f}, 0.0, 0.0])",
            "domain.set_boundary({",
            '    "left": open_boundary, "right": open_boundary,',
            '    "top": open_boundary, "bottom": open_boundary,',
            "})",
            "rainfall_operator = anuga.Rate_operator(",
            '    domain, rate=rainfall_rate, label="openmeteo_peak_window_rainfall"',
            ")",
            (
                "for model_time in domain.evolve("
                f"yieldstep={policy.output_interval_seconds:.6f}, "
                f"finaltime={duration_seconds:.6f}):"
            ),
            "    pass",
            "",
        ]
    )
    script = "\n".join(lines)
    return script, {
        "mesh_cells_x": cells_x,
        "mesh_cells_y": cells_y,
        "expected_triangle_count": 4 * cells_x * cells_y,
        "expected_output_step_count": int(duration_seconds / policy.output_interval_seconds) + 1,
        "duration_seconds": duration_seconds,
        "fixed_boundary_stage_m": fixed_boundary_stage,
    }


def compile_registered_anuga_diagnostic(
    *,
    swmm_input_path: Path,
    swmm_compile_receipt_path: Path,
    forcing_path: Path,
    primary_dem_path: Path,
    comparison_dem_path: Path,
    contour_pages_root: Path,
    contour_manifest_path: Path,
    model_input_path_label: str,
    policy: RegisteredAnugaDiagnosticPolicy | None = None,
) -> tuple[str, dict[str, object]]:
    """Compile a self-contained ANUGA input and its provenance receipt."""

    active = policy or RegisteredAnugaDiagnosticPolicy()
    swmm_receipt = _read_json(swmm_compile_receipt_path)
    try:
        expected_node_ids = set(swmm_receipt["model_input"]["ledger"]["node_elevation_m"])
        selection = swmm_receipt["selection"]
    except (KeyError, TypeError) as error:
        raise ValueError("registered_anuga_swmm_compile_receipt_invalid") from error
    coordinates = parse_swmm_node_coordinates(
        swmm_input_path,
        expected_node_ids=expected_node_ids,
    )
    bounds = _aligned_domain_bounds(coordinates, active)
    terrain = _terrain_window(primary_dem_path, bounds)
    forcing = _read_json(forcing_path)
    try:
        hourly = tuple(float(value) for value in forcing["hourly"]["precipitation"])
        timestamps = tuple(str(value) for value in forcing["hourly"]["time"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("registered_anuga_forcing_invalid") from error
    start = active.forcing_start_hour_index
    end = start + active.forcing_hour_count
    rainfall_mm = hourly[start:end]
    forcing_times = timestamps[start:end]
    if (
        len(rainfall_mm) != active.forcing_hour_count
        or len(forcing_times) != active.forcing_hour_count
        or any(not math.isfinite(value) or value < 0.0 for value in rainfall_mm)
    ):
        raise ValueError("registered_anuga_forcing_window_invalid")
    script, model = _render_model_script(
        bounds=bounds,
        terrain=terrain,
        rainfall_mm=rainfall_mm,
        policy=active,
    )
    script_bytes = script.encode("ascii")
    primary_samples = _sample_dem(primary_dem_path, coordinates)
    comparison_samples = _sample_dem(comparison_dem_path, coordinates)
    differences = np.asarray(
        [primary_samples[node] - comparison_samples[node] for node in coordinates],
        dtype=np.float64,
    )
    contours = audit_local_contours(contour_pages_root, bounds=bounds)
    contour_manifest = _read_json(contour_manifest_path)
    terrain_values = np.asarray(terrain["values"], dtype=np.float64)
    coordinate_values = tuple(coordinates.values())
    node_bbox = (
        min(value[0] for value in coordinate_values),
        min(value[1] for value in coordinate_values),
        max(value[0] for value in coordinate_values),
        max(value[1] for value in coordinate_values),
    )
    receipt: dict[str, object] = {
        "schema": REGISTERED_ANUGA_COMPILE_SCHEMA,
        "status": "compiled_registered_subnetwork_local_surface_public_proxy_not_calibrated",
        "selection_link": {
            "selected_component_id": int(selection["selected_component_id"]),
            "root_outfall_node_id": str(selection["root_outfall_node_id"]),
            "selected_node_count": len(coordinates),
            "selected_pipeline_count": int(selection["selected_pipeline_count"]),
            "node_ids": list(coordinates),
            "node_coordinates_epsg32640": {
                node: [float(point[0]), float(point[1])] for node, point in coordinates.items()
            },
            "node_bbox_epsg32640": [float(value) for value in node_bbox],
            "source_swmm_input_sha256": _sha256_file(swmm_input_path),
            "source_swmm_compile_receipt_sha256": _sha256_file(swmm_compile_receipt_path),
        },
        "surface_domain": {
            "crs": "EPSG:32640",
            "bounds": [float(value) for value in bounds],
            "area_m2": float((bounds[2] - bounds[0]) * (bounds[3] - bounds[1])),
            "mesh_cell_size_m": active.mesh_cell_size_m,
            **model,
        },
        "terrain": {
            "primary_product": "Copernicus DEM GLO-30 public proxy",
            "primary_path": _path_label(primary_dem_path),
            "primary_sha256": _sha256_file(primary_dem_path),
            "primary_crs": terrain["source_crs"],
            "primary_resolution_m": terrain["source_resolution_m"],
            "embedded_window_shape": list(terrain_values.shape),
            "embedded_window_minimum_m": float(terrain_values.min()),
            "embedded_window_maximum_m": float(terrain_values.max()),
            "embedded_window_mean_m": float(terrain_values.mean()),
            "comparison_product": "SRTM 30 m public proxy",
            "comparison_path": _path_label(comparison_dem_path),
            "comparison_sha256": _sha256_file(comparison_dem_path),
            "node_sample_primary_minus_comparison_mean_m": float(differences.mean()),
            "node_sample_primary_minus_comparison_mae_m": float(np.abs(differences).mean()),
            "node_sample_primary_minus_comparison_maximum_absolute_m": float(
                np.abs(differences).max()
            ),
            "smartmakani_contours": {
                "manifest_path": _path_label(contour_manifest_path),
                "manifest_sha256": _sha256_file(contour_manifest_path),
                "role": contour_manifest.get("role"),
                **contours,
            },
            "evidence_class": "public_proxy_and_public_service_candidate",
            "vertical_datum_verified": False,
            "urban_microtopography_supported": False,
        },
        "forcing": {
            "source": "Open-Meteo Historical API archive point product",
            "source_path": _path_label(forcing_path),
            "source_sha256": _sha256_file(forcing_path),
            "time_standard": "GMT",
            "window_start": forcing_times[0],
            "window_end_interval_start": forcing_times[-1],
            "hourly_interval_count": len(rainfall_mm),
            "hourly_depth_mm": list(rainfall_mm),
            "total_depth_mm": float(sum(rainfall_mm)),
            "maximum_hourly_depth_mm": float(max(rainfall_mm)),
            "reported_al_ain_254_8_mm_used": False,
            "evidence_class": "public_proxy",
        },
        "model_input": {
            "path": model_input_path_label,
            "sha256": hashlib.sha256(script_bytes).hexdigest(),
            "size_bytes": len(script_bytes),
            "self_contained_embedded_terrain": True,
            "runtime_external_data_access_required": False,
        },
        "policy": asdict(active),
        "assumptions": {
            "rainfall_loss_or_infiltration_applied": False,
            "building_and_kerb_microtopography_applied": False,
            "surface_drain_inlet_abstraction_applied": False,
            "manning_friction_is_diagnostic_assumption": True,
            "fixed_low_stage_boundary_is_diagnostic_free_drainage_assumption": True,
            "copernicus_dem_is_dsm_not_engineering_dtm": True,
        },
        "admission": {
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "first_anuga_surface_run_spatially_linked_to_the_registered_candidate_subnetwork",
            "public_30m_dsm_cannot_resolve_urban_kerbs_roads_or_engineered_flow_paths",
            "no_infiltration_and_no_inlet_abstraction_make_depths_diagnostic_not_forecasts",
            "fixed_low_stage_edges_are_not_customer_tide_or_outfall_boundaries",
            "openmeteo_point_rainfall_is_not_local_gauge_or_radar_calibration_evidence",
            "reported_254_8_mm_at_al_ain_is_not_used_as_abu_dhabi_city_forcing",
        ],
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return script, receipt
