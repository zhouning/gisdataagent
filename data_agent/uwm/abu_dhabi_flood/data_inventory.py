"""Auditable data inventory for the Abu Dhabi stormwater candidate.

The compiler is intentionally offline.  Network acquisition is a separate
step: this module only reads frozen local artifacts and never contacts a
source system while deciding whether the K0 data gate is open.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INVENTORY_SCHEMA = "gwm.abu_dhabi_stormwater.data_inventory.v1"
DATASET_ID = "abu-dhabi-stormwater-data-v1"
EVENT_WINDOW_UTC = ("2024-04-15T00:00:00Z", "2024-04-18T00:00:00Z")
TARGET_BBOX_WGS84 = (54.2971553, 24.2810331, 54.7659108, 24.601854)
SMARTMAKANI_MAPSERVER = (
    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
    "Survey/Rain_Incidents/MapServer"
)
OPENMETEO_SOURCE_URL = (
    "https://archive-api.open-meteo.com/v1/archive?latitude=24.429&longitude=54.377"
    "&start_date=2024-04-15&end_date=2024-04-17&hourly=precipitation,rain"
    "&timezone=GMT"
)
NASA_POWER_HOURLY_SOURCE_URL = (
    "https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=PRECTOTCORR"
    "&community=RE&longitude=54.377&latitude=24.429&start=20240415&end=20240417"
    "&format=JSON"
)
NASA_POWER_DAILY_SOURCE_URL = NASA_POWER_HOURLY_SOURCE_URL.replace(
    "/hourly/", "/daily/"
)
COPERNICUS_TILE_SOURCE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N24_00_E054_00_DEM/"
    "Copernicus_DSM_COG_10_N24_00_E054_00_DEM.tif"
)
SRTM_TILE_SOURCE_URL = (
    "https://s3.amazonaws.com/elevation-tiles-prod/skadi/N24/N24E054.hgt.gz"
)

_WEATHER_FILES = {
    "openmeteo": "online/weather/openmeteo_archive_abu_dhabi_20240415_20240417.json",
    "nasa_hourly": (
        "online/weather/"
        "nasa_power_hourly_prectotcorr_abu_dhabi_20240415_20240417.json"
    ),
    "nasa_daily": (
        "online/weather/"
        "nasa_power_daily_prectotcorr_abu_dhabi_20240415_20240417.json"
    ),
}
_RASTER_FILES = {
    "srtm_30m": "online/terrain/abu_dhabi_srtm_30m_epsg32640.tif",
    "copernicus_30m": "online/terrain/abu_dhabi_copernicus_30m_epsg32640.tif",
}
_SMARTMAKANI_LAYER_IDS = (2, 3, 16, 30, 31, 32, 33, 36, 37, 38)
_KEY_RUNTIME_STORMWATER_RESOURCES = (
    "layer.st_pipeline",
    "layer.st_inlet",
    "layer.st_catchbasin",
    "layer.st_sw_node",
    "layer.st_sw_junction",
    "layer.st_outfall",
    "layer.st_ps_pump",
    "layer.st_sw_pumpingstationstructure",
    "layer.st_sw_reservoirstructure",
    "layer.st_soakaway",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_inventory(
    dataset_root: Path,
    *,
    repository_root: Path | None = None,
    created_at: str,
) -> dict[str, Any]:
    """Compile the frozen data artifacts without performing network I/O."""

    root = dataset_root.resolve()
    repo = (repository_root or root.parents[1]).resolve()
    weather = _weather_inventory(root)
    terrain = _terrain_inventory(root)
    smartmakani = _smartmakani_inventory(root)
    runtime_catalog = _runtime_stormwater_catalog(repo)
    postgres_audit = _postgres_source_audit(root)
    liveability_postgres_audit = _liveability_postgres_source_audit(root)
    cross_source_geography_audit = _cross_source_geography_audit(root)
    registered_snapshot = _registered_makani_snapshot_inventory(root)
    public_pipeline_count = _layer_by_id(smartmakani["layers"], 37)["feature_count"]
    public_frozen_pipeline_count = _layer_by_id(smartmakani["layers"], 37)[
        "frozen_feature_snapshot"
    ]["record_count"]
    runtime_pipeline = next(
        (
            item
            for item in runtime_catalog["key_resources"]
            if item["physical_resource"] == "layer.st_pipeline"
        ),
        None,
    )
    runtime_pipeline_count = (
        runtime_pipeline["estimated_record_count"] if runtime_pipeline else None
    )
    cross_source = {
        "smartmakani_public_layer_id": 37,
        "smartmakani_public_feature_count": public_pipeline_count,
        "registered_makani_resource": "layer.st_pipeline",
        "registered_makani_estimated_record_count": runtime_pipeline_count,
        "absolute_count_delta": (
            abs(runtime_pipeline_count - public_pipeline_count)
            if runtime_pipeline_count is not None
            else None
        ),
        "counts_match": runtime_pipeline_count == public_pipeline_count,
        "alignment_status": "unresolved_different_snapshots_or_scopes",
        "admission_effect": "do_not_merge_or_substitute_without_record_level_crosswalk",
    }
    if registered_snapshot.get("available"):
        registered_pipeline = next(
            (
                layer
                for layer in registered_snapshot["layers"]
                if layer["resource_name"] == "layer.st_pipeline"
            ),
            None,
        )
        crosswalk = registered_snapshot.get("crosswalk_candidate") or {}
        cross_source.update(
            {
                "registered_target_feature_count": (
                    registered_pipeline["record_count"]
                    if registered_pipeline is not None
                    else None
                ),
                "target_count_delta": (
                    registered_pipeline["record_count"] - public_frozen_pipeline_count
                    if registered_pipeline is not None
                    else None
                ),
                "public_frozen_target_feature_count": public_frozen_pipeline_count,
                "geometry_crosswalk_candidate_count": crosswalk.get(
                    "accepted_crosswalk_count"
                ),
                "public_geometry_crosswalk_coverage_percent": crosswalk.get(
                    "public_coverage_percent"
                ),
                "explicit_identifier_match_available": registered_snapshot.get(
                    "explicit_identifier_match_available"
                ),
                "alignment_status": "candidate_geometry_crosswalk_available_not_authoritative",
            }
        )
    k0 = _k0_gate(
        weather,
        terrain,
        smartmakani,
        runtime_catalog,
        registered_snapshot,
    )
    return {
        "schema": INVENTORY_SCHEMA,
        "dataset_id": DATASET_ID,
        "created_at": created_at,
        "inventory_mode": "offline_frozen_artifacts_no_network_io",
        "target": {
            "place": "Abu Dhabi urban study area",
            "event_window_utc": list(EVENT_WINDOW_UTC),
            "bbox_wgs84": list(TARGET_BBOX_WGS84),
            "target_crs": "EPSG:32640",
            "bbox_epsg32640": terrain["common_grid"]["bounds"],
        },
        "artifacts": _artifact_inventory(root, repo),
        "weather": weather,
        "terrain": terrain,
        "smartmakani": smartmakani,
        "registered_makani_runtime_catalog": runtime_catalog,
        "makani_postgres_source_audit": postgres_audit,
        "liveability_postgres_source_audit": liveability_postgres_audit,
        "cross_source_geography_audit": cross_source_geography_audit,
        "registered_makani_spatial_snapshot": registered_snapshot,
        "public_vs_registered_pipeline": cross_source,
        "k0_data_gate": k0,
        "model_admission": {
            "diagnostic_only": True,
            "operator_admitted": False,
            "calibration_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "public_endpoint_access_does_not_establish_reuse_licence_or_data_authority",
            "static_incident_points_are_not_water_depth_or_duration_time_series",
            "pipeline_geometry_and_attributes_are_not_yet_a_validated_hydraulic_graph",
            "reanalysis_precipitation_is_not_local_gauge_or_radar_observation",
            "thirty_metre_dem_is_not_engineering_grade_urban_surface_elevation",
        ],
    }


def _weather_inventory(root: Path) -> dict[str, Any]:
    openmeteo = _read_json(root / _WEATHER_FILES["openmeteo"])
    open_values = _finite_values(openmeteo["hourly"]["precipitation"])
    open_times = list(openmeteo["hourly"]["time"])
    if len(open_times) != len(open_values):
        raise ValueError("openmeteo_time_value_length_mismatch")

    nasa_hourly = _read_json(root / _WEATHER_FILES["nasa_hourly"])
    nasa_hourly_values = nasa_hourly["properties"]["parameter"]["PRECTOTCORR"]
    nasa_source_values = _finite_values(nasa_hourly_values.values())
    nasa_hourly_unit = nasa_hourly["parameters"]["PRECTOTCORR"]["units"]
    if nasa_hourly_unit != "mm/day":
        raise ValueError("nasa_power_hourly_unit_contract_changed")
    # POWER's hourly endpoint reports the hourly precipitation rate in mm/day.
    # One hourly interval therefore contributes rate / 24 millimetres.
    nasa_interval_depths = tuple(value / 24.0 for value in nasa_source_values)

    nasa_daily = _read_json(root / _WEATHER_FILES["nasa_daily"])
    nasa_daily_values = _finite_values(
        nasa_daily["properties"]["parameter"]["PRECTOTCORR"].values()
    )
    daily_unit = nasa_daily["parameters"]["PRECTOTCORR"]["units"]
    if daily_unit != "mm/day":
        raise ValueError("nasa_power_daily_unit_contract_changed")

    open_total = sum(open_values)
    nasa_hourly_total = sum(nasa_interval_depths)
    nasa_daily_total = sum(nasa_daily_values)
    return {
        "event_window_utc": list(EVENT_WINDOW_UTC),
        "products": [
            {
                "product_id": "openmeteo_archive_point_hourly",
                "path": _WEATHER_FILES["openmeteo"],
                "source_url": OPENMETEO_SOURCE_URL,
                "location": {
                    "latitude": openmeteo["latitude"],
                    "longitude": openmeteo["longitude"],
                    "elevation_m": openmeteo.get("elevation"),
                },
                "time_standard": openmeteo.get("timezone"),
                "interval_count": len(open_values),
                "interval_support": "1 hour",
                "source_unit": openmeteo["hourly_units"]["precipitation"],
                "interval_depth_unit": "mm",
                "total_interval_depth_mm": _rounded(open_total),
                "maximum_interval_depth_mm": _rounded(max(open_values)),
                "evidence_class": "reanalysis_candidate",
                "calibration_admission": "not_admitted_for_calibration",
                "limitation": "single_public_grid_point_not_local_gauge_observation",
            },
            {
                "product_id": "nasa_power_merra2_point_hourly",
                "path": _WEATHER_FILES["nasa_hourly"],
                "source_url": NASA_POWER_HOURLY_SOURCE_URL,
                "location": _geojson_point(nasa_hourly),
                "time_standard": nasa_hourly["header"]["time_standard"],
                "interval_count": len(nasa_source_values),
                "interval_support": "1 hour",
                "source_unit": nasa_hourly_unit,
                "unit_interpretation": "hourly_rate_expressed_as_mm_per_day",
                "conversion_to_interval_depth": "interval_depth_mm = source_value / 24",
                "raw_value_sum_not_a_depth": _rounded(sum(nasa_source_values)),
                "total_interval_depth_mm": _rounded(nasa_hourly_total),
                "maximum_interval_depth_mm": _rounded(max(nasa_interval_depths)),
                "direct_raw_sum_forcing_forbidden": True,
                "evidence_class": "reanalysis_candidate",
                "calibration_admission": "not_admitted_for_calibration",
            },
            {
                "product_id": "nasa_power_merra2_point_daily",
                "path": _WEATHER_FILES["nasa_daily"],
                "source_url": NASA_POWER_DAILY_SOURCE_URL,
                "location": _geojson_point(nasa_daily),
                "time_standard": nasa_daily["header"]["time_standard"],
                "interval_count": len(nasa_daily_values),
                "interval_support": "1 day",
                "source_unit": daily_unit,
                "total_interval_depth_mm": _rounded(nasa_daily_total),
                "maximum_interval_depth_mm": _rounded(max(nasa_daily_values)),
                "evidence_class": "reanalysis_candidate",
                "calibration_admission": "not_admitted_for_calibration",
            },
        ],
        "cross_product_check": {
            "nasa_hourly_converted_minus_daily_total_mm": _rounded(
                nasa_hourly_total - nasa_daily_total
            ),
            "nasa_internal_total_consistent_with_rounding": (
                abs(nasa_hourly_total - nasa_daily_total) <= 0.02
            ),
            "openmeteo_minus_nasa_daily_total_mm": _rounded(
                open_total - nasa_daily_total
            ),
            "products_interchangeable_for_calibration": False,
        },
        "observed_rainfall_available": False,
        "admission": "not_admitted_for_calibration",
    }


def _terrain_inventory(root: Path) -> dict[str, Any]:
    srtm = _raster_summary(root / _RASTER_FILES["srtm_30m"])
    copernicus = _raster_summary(root / _RASTER_FILES["copernicus_30m"])
    comparison = _compare_rasters(
        root / _RASTER_FILES["srtm_30m"],
        root / _RASTER_FILES["copernicus_30m"],
    )
    return {
        "rasters": [
            {
                "product_id": "srtm_30m_clipped_epsg32640",
                "path": _RASTER_FILES["srtm_30m"],
                "derived_from": "online/terrain/N24E054.hgt",
                "source_url": SRTM_TILE_SOURCE_URL,
                **srtm,
                "evidence_class": "public_proxy",
                "calibration_admission": "not_admitted_for_calibration",
            },
            {
                "product_id": "copernicus_dem_30m_clipped_epsg32640",
                "path": _RASTER_FILES["copernicus_30m"],
                "derived_from": (
                    "online/terrain/Copernicus_DSM_COG_10_N24_00_E054_00_DEM.tif"
                ),
                "source_url": COPERNICUS_TILE_SOURCE_URL,
                **copernicus,
                "evidence_class": "public_proxy",
                "calibration_admission": "not_admitted_for_calibration",
            },
        ],
        "common_grid": {
            "crs": srtm["crs"],
            "width": srtm["width"],
            "height": srtm["height"],
            "resolution": srtm["resolution"],
            "bounds": srtm["bounds"],
            "same_grid": (
                srtm["crs"] == copernicus["crs"]
                and srtm["width"] == copernicus["width"]
                and srtm["height"] == copernicus["height"]
                and srtm["bounds"] == copernicus["bounds"]
            ),
        },
        "srtm_minus_copernicus": comparison,
        "vertical_datum_verified": False,
        "engineering_control_points_verified": False,
        "sea_land_mask_verified": False,
        "urban_microtopography_supported": False,
        "admission": "not_admitted_for_calibration",
    }


def _raster_summary(path: Path) -> dict[str, Any]:
    try:
        import numpy as np
        import rasterio
    except ImportError as exc:  # pragma: no cover - depends on optional GIS extra
        raise RuntimeError("rasterio_and_numpy_required_for_dem_inventory") from exc

    with rasterio.open(path) as dataset:
        data = dataset.read(1, masked=True)
        values = np.asarray(data.compressed(), dtype="float64")
        if values.size == 0:
            raise ValueError(f"raster_has_no_valid_pixels:{path}")
        return {
            "crs": str(dataset.crs),
            "width": dataset.width,
            "height": dataset.height,
            "resolution": [float(abs(dataset.res[0])), float(abs(dataset.res[1]))],
            "bounds": [
                float(dataset.bounds.left),
                float(dataset.bounds.bottom),
                float(dataset.bounds.right),
                float(dataset.bounds.top),
            ],
            "nodata": float(dataset.nodata) if dataset.nodata is not None else None,
            "valid_pixel_count": int(values.size),
            "total_pixel_count": int(data.size),
            "valid_pixel_percent": _rounded(values.size / data.size * 100.0),
            "minimum_m": _rounded(float(values.min())),
            "maximum_m": _rounded(float(values.max())),
            "mean_m": _rounded(float(values.mean())),
            "standard_deviation_m": _rounded(float(values.std())),
        }


def _compare_rasters(first: Path, second: Path) -> dict[str, Any]:
    import numpy as np
    import rasterio

    with rasterio.open(first) as first_dataset, rasterio.open(second) as second_dataset:
        if (
            first_dataset.shape != second_dataset.shape
            or first_dataset.crs != second_dataset.crs
            or first_dataset.transform != second_dataset.transform
        ):
            return {"comparable": False, "reason": "grid_mismatch"}
        first_data = first_dataset.read(1, masked=True)
        second_data = second_dataset.read(1, masked=True)
        first_values = np.asarray(first_data, dtype="float64")
        second_values = np.asarray(second_data, dtype="float64")
        mask = (
            np.ma.getmaskarray(first_data)
            | np.ma.getmaskarray(second_data)
            | ~np.isfinite(first_values)
            | ~np.isfinite(second_values)
        )
        difference = (first_values - second_values)[~mask]
        absolute = np.abs(difference)
        return {
            "comparable": True,
            "valid_pair_count": int(difference.size),
            "mean_difference_m": _rounded(float(difference.mean())),
            "median_difference_m": _rounded(float(np.median(difference))),
            "mean_absolute_error_m": _rounded(float(absolute.mean())),
            "root_mean_square_error_m": _rounded(
                float(np.sqrt(np.mean(difference**2)))
            ),
            "absolute_difference_p95_m": _rounded(float(np.percentile(absolute, 95))),
            "maximum_absolute_difference_m": _rounded(float(absolute.max())),
            "products_interchangeable_without_vertical_validation": False,
        }


def _smartmakani_inventory(root: Path) -> dict[str, Any]:
    snapshot_root = root / "online/smartmakani"
    service = _read_json(snapshot_root / "rain_incidents_mapserver.json")
    layers = []
    for layer_id in _SMARTMAKANI_LAYER_IDS:
        metadata = _read_json(snapshot_root / f"rain_incidents_layer_{layer_id}.json")
        count = _read_json(
            snapshot_root / f"rain_incidents_layer_{layer_id}_count.json"
        )["count"]
        target_count_path = (
            snapshot_root / f"rain_incidents_layer_{layer_id}_target_bbox_count.json"
        )
        target_count = (
            _read_json(target_count_path)["count"] if target_count_path.exists() else None
        )
        fields = metadata.get("fields") or []
        field_names = [str(field["name"]) for field in fields]
        date_fields = [
            str(field["name"])
            for field in fields
            if field.get("type") == "esriFieldTypeDate"
        ]
        incident_measure_fields = [
            name
            for name in field_names
            if any(
                token in name.upper()
                for token in ("WATER_DEPTH", "FLOOD_DEPTH", "DURATION", "WATER_LEVEL")
            )
        ]
        record: dict[str, Any] = {
            "layer_id": layer_id,
            "name": metadata.get("name"),
            "geometry_type": metadata.get("geometryType"),
            "feature_count": int(count),
            "target_bbox_feature_count": (
                int(target_count) if target_count is not None else None
            ),
            "source_spatial_reference_wkid": _wkid(
                metadata.get("sourceSpatialReference")
            ),
            "service_extent": _extent(metadata.get("extent")),
            "field_count": len(fields),
            "date_fields": date_fields,
            "incident_measure_fields": incident_measure_fields,
            "definition_expression": metadata.get("definitionExpression"),
            "max_record_count": metadata.get("maxRecordCount"),
            "evidence_class": "public_proxy",
            "calibration_admission": "not_admitted_for_calibration",
        }
        date_stats_path = (
            snapshot_root / f"rain_incidents_layer_{layer_id}_date_stats.json"
        )
        if date_stats_path.exists():
            attributes = _query_statistics(date_stats_path)
            record["case_creation_time_range_utc"] = [
                _epoch_ms_to_iso(attributes.get("min_date")),
                _epoch_ms_to_iso(attributes.get("max_date")),
            ]
            record["covers_target_2024_event"] = _time_range_overlaps(
                record["case_creation_time_range_utc"], EVENT_WINDOW_UTC
            )
        if layer_id == 37:
            record["hydraulic_candidate_fields_present"] = sorted(
                set(field_names)
                & {
                    "ASSET_DIAMETER",
                    "End_X",
                    "End_Y",
                    "HYDROID",
                    "INVERT_LEVEL_DOWN",
                    "INVERT_LEVEL_UP",
                    "OUTFALL_NAME",
                    "PIPE_MATERIAL",
                    "Start_X",
                    "Start_Y",
                }
            )
            record["field_statistics"] = _query_statistics(
                snapshot_root / "rain_incidents_layer_37_field_stats.json"
            )
            field_stats = record["field_statistics"]
            record["data_quality_flags"] = {
                "zero_diameter_present": field_stats["diameter_min"] == 0,
                "invert_sentinel_or_outlier_present": (
                    field_stats["invert_up_min"] <= -999
                    or field_stats["invert_down_min"] <= -999
                    or field_stats["invert_up_max"] > 1000
                    or field_stats["invert_down_max"] > 1000
                ),
                "source_geometry_is_wgs84_but_service_extent_is_epsg32640": (
                    record["source_spatial_reference_wkid"] == 4326
                    and record["service_extent"]["wkid"] == 32640
                ),
                "stored_shape_length_must_be_recomputed_in_projected_crs": True,
            }
        layers.append(record)

    feature_snapshots = []
    for layer_id in (2, 3, 30, 32, 37):
        layer_root = snapshot_root / "features" / f"layer_{layer_id}"
        manifest_path = layer_root / "snapshot_manifest.json"
        descriptor_path = layer_root / "snapshot.json"
        if not manifest_path.exists() or not descriptor_path.exists():
            continue
        manifest = _read_json(manifest_path)
        descriptor = _read_json(descriptor_path)
        layer = _layer_by_id(layers, layer_id)
        baseline_count = (
            layer["target_bbox_feature_count"]
            if descriptor["request_contract"]["bbox_wgs84"] is not None
            else layer["feature_count"]
        )
        snapshot = {
            "layer_id": layer_id,
            "status": manifest["status"],
            "record_count": manifest["completed_record_count"],
            "page_count": manifest["completed_page_count"],
            "page_size": manifest["page_size"],
            "page_content_sha256": hashlib.sha256(
                json.dumps(
                    [page["sha256"] for page in manifest["pages"]],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "null_geometry_count": _snapshot_null_geometry_count(
                layer_root,
                manifest,
            ),
            "target_crs": manifest["target_crs"],
            "out_fields": manifest["out_fields"],
            "snapshot_fingerprint": manifest["snapshot_fingerprint"],
            "content_fingerprint": manifest.get("content_fingerprint"),
            "object_ids_sha256": descriptor["object_ids_sha256"],
            "truncated": descriptor["truncated"],
            "baseline_metadata_count": baseline_count,
            "record_count_delta_from_baseline": (
                manifest["completed_record_count"] - baseline_count
            ),
            "public_feature_rows": manifest["public_feature_rows"],
            "contains_personal_fields": manifest["contains_personal_fields"],
            "calibration_admission": manifest["calibration_admission"],
            "manifest_path": str(manifest_path.relative_to(root)),
            "manifest_sha256": sha256_file(manifest_path),
        }
        layer["frozen_feature_snapshot"] = snapshot
        feature_snapshots.append(snapshot)

    mims = [_layer_by_id(layers, layer_id) for layer_id in (30, 31, 32)]
    mims_same_counts = len({layer["feature_count"] for layer in mims}) == 1
    mims_same_times = len(
        {tuple(layer["case_creation_time_range_utc"]) for layer in mims}
    ) == 1
    mims_no_filters = all(layer["definition_expression"] is None for layer in mims)
    frozen_mims = {
        item["layer_id"]: item
        for item in feature_snapshots
        if item["layer_id"] in {30, 32}
    }
    frozen_mims_rows_identical = (
        set(frozen_mims) == {30, 32}
        and frozen_mims[30]["object_ids_sha256"]
        == frozen_mims[32]["object_ids_sha256"]
        and frozen_mims[30]["page_content_sha256"]
        == frozen_mims[32]["page_content_sha256"]
    )
    contour = _read_json(snapshot_root / "contour_2017_mapserver.json")
    bathymetry = _read_json(snapshot_root / "bathymetry_2017_mapserver.json")
    imagery = _read_json(snapshot_root / "satellite_2024_q3_15cm_imageserver.json")
    surface_support = _surface_support_inventory(root)
    target_clipped_surface = _target_clipped_surface_inventory(root)
    return {
        "source_url": SMARTMAKANI_MAPSERVER,
        "server_version": service.get("currentVersion"),
        "capabilities": service.get("capabilities"),
        "supported_query_formats": service.get("supportedQueryFormats"),
        "service_crs_wkid": _wkid(service.get("spatialReference")),
        "snapshot_contains_feature_rows": bool(feature_snapshots),
        "feature_snapshots": feature_snapshots,
        "download_authorization": "user_confirmed_prior_authorization",
        "licence_or_reuse_terms_established": False,
        "layers": layers,
        "mims_display_sublayer_warning": {
            "layer_ids": [30, 31, 32],
            "same_feature_count": mims_same_counts,
            "same_case_creation_time_range": mims_same_times,
            "all_definition_expressions_null": mims_no_filters,
            "frozen_layers_compared": [30, 32],
            "frozen_object_ids_and_feature_rows_identical": (
                frozen_mims_rows_identical
            ),
            "treat_as_independent_datasets": False,
            "reason": "same_unfiltered_business_view_exposed_with_different_renderers",
        },
        "supporting_services": [
            {
                "service_id": "topography_2017_contour",
                "url": (
                    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                    "Topography/2017_Contour/MapServer"
                ),
                "layers": [layer["name"] for layer in contour.get("layers") or []],
                "nominal_contour_interval_m": 1.0,
                "vertical_datum_declared_in_service_metadata": False,
                "evidence_class": "public_proxy",
                "calibration_admission": "not_admitted_for_calibration",
            },
            {
                "service_id": "topography_2017_bathymetry",
                "url": (
                    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                    "Topography/2017_Bathymetry/MapServer"
                ),
                "layers": [layer["name"] for layer in bathymetry.get("layers") or []],
                "time_varying_tide_or_sea_level": False,
                "evidence_class": "public_proxy",
                "calibration_admission": "not_admitted_for_calibration",
            },
            {
                "service_id": "subaddressing_building_survey",
                "url": (
                    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                    "SubAddressing/Building_Survey/FeatureServer"
                ),
                "downloaded_fields": [
                    "OBJECTID",
                    "BUILDINGNUMBEROFFLOORS",
                    "BUILDINGHEIGHT",
                    "PHYSICALSTATUS",
                ],
                "source_edit_capabilities_ignored": True,
                "access_mode": "query_only",
                "evidence_class": "public_proxy",
                "calibration_admission": "not_admitted_for_calibration",
            },
            {
                "service_id": "images_2024_q3_satellite_15cm",
                "url": (
                    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                    "Images/2024_Q3_SatImg_15cm_All/ImageServer"
                ),
                "band_count": imagery.get("bandCount"),
                "service_crs_wkid": _wkid(imagery.get("spatialReference")),
                "nominal_resolution_m": 0.15,
                "is_elevation_surface": False,
                "evidence_class": "public_proxy",
                "calibration_admission": "not_admitted_for_calibration",
            },
        ],
        "supporting_surface_candidate": surface_support,
        "target_clipped_surface_candidate": target_clipped_surface,
        "pipeline_topology_candidate": _pipeline_topology_inventory(root),
    }


def _snapshot_null_geometry_count(
    layer_root: Path,
    manifest: dict[str, Any],
) -> int:
    count = 0
    for page in manifest["pages"]:
        payload = _read_json(layer_root / page["path"])
        count += sum(
            feature.get("geometry") is None
            for feature in payload.get("features", [])
        )
    return count


def _surface_support_inventory(root: Path) -> dict[str, Any]:
    audit_path = root / "derived/smartmakani/supporting_surface_candidate_audit.json"
    if not audit_path.exists():
        return {
            "available": False,
            "admitted": False,
            "reason": "supporting_surface_candidate_audit_missing",
        }
    audit = _read_json(audit_path)
    if audit.get("schema") != "gwm.abu_dhabi_flood.surface_support_audit.v1":
        raise ValueError("unsupported_surface_support_audit_schema")
    admission = audit["admission"]
    if admission.get("k0_opened") is not False:
        raise ValueError("surface_support_audit_opened_k0")
    if admission.get("surface_patch_contract_compiled") is not False:
        raise ValueError("surface_support_audit_compiled_surface_patch")
    return {
        "available": True,
        "audit_path": str(audit_path.relative_to(root)),
        "audit_sha256": sha256_file(audit_path),
        "layers": audit["layers"],
        "surface_candidate_summary": audit["surface_candidate_summary"],
        "admission": admission,
        "blockers": audit["blockers"],
        "claim_boundary": audit["claim_boundary"],
    }


def _target_clipped_surface_inventory(root: Path) -> dict[str, Any]:
    manifest_path = (
        root
        / "derived/smartmakani/surface_clip_candidate/"
        "surface_clip_candidate_manifest.json"
    )
    if not manifest_path.exists():
        return {
            "available": False,
            "admitted": False,
            "reason": "target_clipped_surface_candidate_missing",
        }
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "gwm.abu_dhabi_flood.surface_clip_bundle.v1":
        raise ValueError("unsupported_surface_clip_bundle_schema")
    admission = manifest["admission"]
    if admission.get("k0_opened") is not False:
        raise ValueError("surface_clip_bundle_opened_k0")
    if admission.get("surface_patch_contract_compiled") is not False:
        raise ValueError("surface_clip_bundle_compiled_surface_patch")
    for dataset in manifest["datasets"]:
        dataset_manifest_path = root / dataset["manifest_path"]
        if sha256_file(dataset_manifest_path) != dataset["manifest_sha256"]:
            raise ValueError(
                f"surface_clip_dataset_manifest_hash_mismatch:"
                f"{dataset['dataset_key']}"
            )
    return {
        "available": True,
        "manifest_path": str(manifest_path.relative_to(root)),
        "manifest_sha256": sha256_file(manifest_path),
        "policy": manifest["policy"],
        "datasets": manifest["datasets"],
        "summary": manifest["summary"],
        "admission": admission,
        "claim_boundary": manifest["claim_boundary"],
    }


def _pipeline_topology_inventory(root: Path) -> dict[str, Any]:
    topology_path = root / "derived/smartmakani/pipeline_topology_manifest.json"
    audit_path = root / "derived/smartmakani/network_audit.json"
    if not topology_path.exists() or not audit_path.exists():
        return {
            "available": False,
            "admitted": False,
            "reason": "frozen_pipeline_topology_not_compiled",
        }
    topology = _read_json(topology_path)
    audit = _read_json(audit_path)
    return {
        "available": True,
        "schema": topology["schema"],
        "network_id": topology["network_id"],
        "source_snapshot_fingerprint": topology["source_snapshot_fingerprint"],
        "pipeline_count": topology["pipeline_count"],
        "node_count": topology["node_count"],
        "connected_component_count": audit["topology"]["connected_component_count"],
        "largest_component_node_count": audit["topology"][
            "largest_component_node_count"
        ],
        "self_loop_count": audit["topology"]["self_loops_after_snap"]["count"],
        "duplicate_node_pair_group_count": audit["topology"][
            "duplicate_node_pair_group_count"
        ],
        "near_zero_length_count": audit["geometry"]["zero_length"]["count"],
        "geometry_z_both_zero_percent": audit["geometry"][
            "z_both_endpoints_zero"
        ]["percent"],
        "geometry_z_match_percent_of_comparable_rows": audit["geometry"][
            "z_match_percent_of_comparable_rows"
        ],
        "geometry_z_source_unit_or_datum_verified": audit["geometry"][
            "z_source_unit_or_datum_verified"
        ],
        "both_inverts_plausible_candidate_percent": audit["attributes"][
            "both_inverts_plausible_candidate"
        ]["percent"],
        "flow_direction_conflict_percent": audit["attributes"][
            "flow_direction_conflict"
        ]["percent"],
        "attribute_endpoint_within_5m_percent": audit["attributes"][
            "attribute_endpoints"
        ]["within_tolerance"]["percent"],
        "outputs": topology["outputs"],
        "audit_path": str(audit_path.relative_to(root)),
        "audit_sha256": sha256_file(audit_path),
        "evidence_level": topology["evidence_level"],
        "admitted": topology["admitted"],
        "diagnostic_only": topology["diagnostic_only"],
        "flood_network_contract_compiled": topology[
            "flood_network_contract_compiled"
        ],
        "claim_boundary": topology["claim_boundary"],
    }


def _runtime_stormwater_catalog(repo: Path) -> dict[str, Any]:
    path = (
        repo
        / "docs/customer/abu_dhabi_liveability_site_validation/"
        "makani_pg_dictionary_mapping.csv"
    )
    if not path.exists():
        return {
            "available": False,
            "reason": "makani_runtime_mapping_catalog_missing",
            "resources": [],
            "key_resources": [],
        }
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row.get("network_family_candidate") == "stormwater"
        ]
    resources = []
    for row in rows:
        resources.append(
            {
                "physical_resource": row["physical_resource"],
                "resource_type": row["resource_type"],
                "field_count": int(row["field_count"]),
                "foreign_key_count": int(row["foreign_key_count"]),
                "geometry_types": row["geometry_types"],
                "estimated_record_count": int(row["estimated_record_count"]),
                "dictionary_match_status": row["dictionary_match_status"],
                "dictionary_candidate": row["dictionary_candidate"],
                "live_field_coverage": float(row["live_field_coverage"]),
                "evidence_boundary": row["evidence_boundary"],
            }
        )
    by_name = {item["physical_resource"]: item for item in resources}
    key_resources = [
        by_name[name] for name in _KEY_RUNTIME_STORMWATER_RESOURCES if name in by_name
    ]
    return {
        "available": True,
        "source_path": str(path.relative_to(repo)),
        "source_sha256": sha256_file(path),
        "metadata_only": True,
        "contains_source_rows": False,
        "stormwater_resource_count": len(resources),
        "declared_foreign_key_count": sum(
            item["foreign_key_count"] for item in resources
        ),
        "resources": resources,
        "key_resources": key_resources,
        "admission": "candidate_review_required",
        "limitation": (
            "dictionary measured against makani_sync_full while runtime discovery remains "
            "authoritative; no declared foreign keys"
        ),
    }


def _postgres_source_audit(root: Path) -> dict[str, Any]:
    """Load the row-free audit produced from the customer PostgreSQL source."""
    audit_path = root / "derived/makani_pg_audit/stormwater_source_audit.json"
    mapping_path = root / "derived/makani_pg_audit/dictionary_to_database_mapping.json"
    gap_path = root / "derived/makani_pg_audit/k0_data_gap_report.md"
    if not audit_path.exists():
        return {
            "available": False,
            "reason": "makani_postgres_source_audit_missing",
            "admission": "candidate_review_required",
        }
    audit = _read_json(audit_path)
    if audit.get("schema") != "gwm.abu_dhabi_stormwater.postgres_source_audit.v1":
        raise ValueError("unsupported_makani_postgres_source_audit_schema")
    if audit.get("source", {}).get("source_rows_persisted") is not False:
        raise ValueError("makani_postgres_audit_source_rows_boundary_changed")
    if audit.get("k0_status") != "closed_not_admitted":
        raise ValueError("makani_postgres_audit_opened_k0")
    return {
        "available": True,
        "audit_path": str(audit_path.relative_to(root)),
        "audit_sha256": sha256_file(audit_path),
        "mapping_path": str(mapping_path.relative_to(root)) if mapping_path.exists() else None,
        "mapping_sha256": sha256_file(mapping_path) if mapping_path.exists() else None,
        "gap_report_path": str(gap_path.relative_to(root)) if gap_path.exists() else None,
        "tables": audit.get("tables", []),
        "relationships": audit.get("relationships", []),
        "pipeline_endpoint_facility_probe": audit.get("pipeline_endpoint_facility_probe", {}),
        "observations": audit.get("observations", []),
        "quality_signals": audit.get("quality_signals", []),
        "summary": audit.get("summary", {}),
        "dictionary": audit.get("dictionary", {}),
        "k0_status": audit["k0_status"],
        "k0_gates": audit.get("k0_gates", []),
        "admission": audit.get("admission", {}),
        "contains_source_rows": False,
            "evidence_boundary": (
                "runtime PostgreSQL aggregates are authoritative for this audit; "
                "dictionary is candidate semantics; customer review required"
            ),
    }


def _liveability_postgres_source_audit(root: Path) -> dict[str, Any]:
    """Load the row-free audit produced from the Liveability PostgreSQL source."""
    audit_path = root / "derived/liveability_pg_audit/liveability_source_audit.json"
    mapping_path = root / "derived/liveability_pg_audit/dictionary_to_database_mapping.json"
    gap_path = root / "derived/liveability_pg_audit/impact_data_gap_report.md"
    if not audit_path.exists():
        return {
            "available": False,
            "reason": "liveability_postgres_source_audit_missing",
            "admission": "candidate_review_required",
        }
    audit = _read_json(audit_path)
    if audit.get("schema") != "gwm.abu_dhabi_stormwater.liveability_postgres_source_audit.v1":
        raise ValueError("unsupported_liveability_postgres_source_audit_schema")
    if audit.get("source", {}).get("source_rows_persisted") is not False:
        raise ValueError("liveability_postgres_audit_source_rows_boundary_changed")
    if audit.get("k0_status") != "closed_not_admitted":
        raise ValueError("liveability_postgres_audit_opened_k0")
    return {
        "available": True,
        "audit_path": str(audit_path.relative_to(root)),
        "audit_sha256": sha256_file(audit_path),
        "mapping_path": str(mapping_path.relative_to(root)) if mapping_path.exists() else None,
        "mapping_sha256": sha256_file(mapping_path) if mapping_path.exists() else None,
        "gap_report_path": str(gap_path.relative_to(root)) if gap_path.exists() else None,
        "resources": audit.get("resources", []),
        "relationship_probes": audit.get("relationship_probes", []),
        "summary": audit.get("summary", {}),
        "observations": audit.get("observations", []),
        "dictionary": audit.get("dictionary", {}),
        "k0_status": audit["k0_status"],
        "k0_gates": audit.get("k0_gates", []),
        "admission": audit.get("admission", {}),
        "contains_source_rows": False,
        "evidence_boundary": (
            "runtime PostgreSQL aggregates are authoritative for this audit; "
            "dictionary is an older candidate snapshot; customer review required"
        ),
    }


def _cross_source_geography_audit(root: Path) -> dict[str, Any]:
    """Load the row-free aggregate-only Makani--Liveability overlap audit."""
    audit_path = (
        root / "derived/cross_source_geography_audit/cross_source_geography_audit.json"
    )
    report_path = (
        root / "derived/cross_source_geography_audit/cross_source_geography_audit.md"
    )
    if not audit_path.exists():
        return {
            "available": False,
            "reason": "cross_source_geography_audit_missing",
            "admission": "candidate_review_required",
        }
    audit = _read_json(audit_path)
    if audit.get("schema") != "gwm.abu_dhabi_stormwater.cross_source_geography_audit.v1":
        raise ValueError("unsupported_cross_source_geography_audit_schema")
    if audit.get("source_rows_persisted") is not False:
        raise ValueError("cross_source_geography_source_rows_boundary_changed")
    if audit.get("source_identifier_values_persisted") is not False:
        raise ValueError("cross_source_geography_identifier_boundary_changed")
    if audit.get("k0_status") != "closed_not_admitted":
        raise ValueError("cross_source_geography_audit_opened_k0")
    return {
        "available": True,
        "audit_path": str(audit_path.relative_to(root)),
        "audit_sha256": sha256_file(audit_path),
        "report_path": str(report_path.relative_to(root)) if report_path.exists() else None,
        "report_sha256": sha256_file(report_path) if report_path.exists() else None,
        "results": audit.get("results", []),
        "observations": audit.get("observations", []),
        "k0_status": audit["k0_status"],
        "admission": audit.get("admission", {}),
        "contains_source_rows": False,
        "contains_source_identifier_values": False,
        "evidence_boundary": (
            "trim-and-uppercase aggregate overlap only; no source values persisted; "
            "does not establish entity identity or hydraulic connectivity"
        ),
    }


def _registered_makani_snapshot_inventory(root: Path) -> dict[str, Any]:
    pointer_path = root / "online/makani_registered/latest_snapshot.json"
    if not pointer_path.exists():
        return {
            "available": False,
            "reason": "registered_makani_snapshot_missing",
            "layers": [],
        }
    pointer = _read_json(pointer_path)
    snapshot_path = root / pointer["path"] / "snapshot.json"
    if not snapshot_path.exists():
        raise ValueError("registered_makani_snapshot_pointer_broken")
    if sha256_file(snapshot_path) != pointer["snapshot_sha256"]:
        raise ValueError("registered_makani_snapshot_checksum_mismatch")
    snapshot = _read_json(snapshot_path)
    if snapshot.get("admission", {}).get("admitted") is not False:
        raise ValueError("registered_makani_snapshot_admission_changed")
    if snapshot.get("privacy", {}).get("contains_personal_fields") is not False:
        raise ValueError("registered_makani_snapshot_contains_personal_fields")

    result = {
        "available": True,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_path": str(snapshot_path.relative_to(root)),
        "snapshot_sha256": pointer["snapshot_sha256"],
        "source_binding": snapshot["source_binding"],
        "record_count": snapshot["record_count"],
        "page_count": snapshot["page_count"],
        "layer_count": len(snapshot["layers"]),
        "layers": snapshot["layers"],
        "privacy": snapshot["privacy"],
        "admission": snapshot["admission"],
        "download_authorized_by_user": snapshot["authorization"][
            "download_authorized_by_user"
        ],
    }

    probe_path = root / "derived/makani_registered/makani_relationship_probe.json"
    if probe_path.exists():
        probe = _read_json(probe_path)
        probe_results = {item["probe_id"]: item for item in probe["results"]}
        field_quality = probe_results["pipeline_field_quality"]
        quality_row = dict(
            zip(field_quality["columns"], field_quality["rows"][0], strict=True)
        )
        outfall_rows = probe_results["outfall_identifier_matches"]["rows"]
        pump_rows = probe_results["pump_station_identifier_matches"]["rows"]
        result["relationship_probe"] = {
            "path": str(probe_path.relative_to(root)),
            "sha256": sha256_file(probe_path),
            "aggregate_only": True,
            "raw_identifiers_persisted": False,
            "pipeline_field_quality": quality_row,
            "outfall_identifier_match_count": sum(int(row[3]) for row in outfall_rows),
            "pump_station_identifier_match_count": sum(
                int(row[2]) for row in pump_rows
            ),
            "admitted": False,
        }

    audit_path = root / "derived/makani_registered/registered_network_crosswalk_audit.json"
    if audit_path.exists():
        audit = _read_json(audit_path)
        geometry = audit["geometry_crosswalk"]
        attachments = audit["facility_attachments"]
        result["explicit_identifier_match_available"] = audit[
            "identifier_crosswalk"
        ]["any_explicit_identifier_match"]
        result["crosswalk_candidate"] = {
            "path": str(audit_path.relative_to(root)),
            "sha256": sha256_file(audit_path),
            "accepted_crosswalk_count": geometry["accepted_crosswalk_count"],
            "public_coverage_percent": geometry["public_coverage_percent"],
            "registered_coverage_percent": geometry["registered_coverage_percent"],
            "authoritative_identity_established": geometry[
                "authoritative_identity_established"
            ],
            "facility_attachment_count": attachments["attachment_count"],
            "attachment_percent_of_valid_references": attachments[
                "attachment_percent_of_valid_references"
            ],
            "within_1m_count": attachments["within_1m_count"],
            "orientation_diagnostic": attachments[
                "geometry_orientation_diagnostic"
            ],
            "authoritative_connectivity_established": attachments[
                "authoritative_connectivity_established"
            ],
            "admitted": False,
        }

    network_manifest_path = (
        root
        / "derived/makani_registered/registered_network_candidate_manifest.json"
    )
    if network_manifest_path.exists():
        network_manifest = _read_json(network_manifest_path)
        if network_manifest["registered_snapshot_id"] != snapshot["snapshot_id"]:
            raise ValueError("registered_network_candidate_snapshot_mismatch")
        network_audit_path = root / network_manifest["audit"]["path"]
        if sha256_file(network_audit_path) != network_manifest["audit"]["sha256"]:
            raise ValueError("registered_network_candidate_audit_checksum_mismatch")
        network_audit = _read_json(network_audit_path)
        topology = network_audit["topology"]
        facilities = network_audit["facility_semantics"]
        result["network_candidate"] = {
            "path": str(network_manifest_path.relative_to(root)),
            "sha256": sha256_file(network_manifest_path),
            "network_id": network_manifest["network_id"],
            "pipeline_count": network_manifest["pipeline_count"],
            "node_count": network_manifest["node_count"],
            "connected_component_count": topology["topology"][
                "connected_component_count"
            ],
            "largest_component_node_count": topology["topology"][
                "largest_component_node_count"
            ],
            "self_loop_count": topology["topology"]["self_loops_after_snap"][
                "count"
            ],
            "duplicate_node_pair_group_count": topology["topology"][
                "duplicate_node_pair_group_count"
            ],
            "flow_direction_conflict_percent": topology["attributes"][
                "flow_direction_conflict"
            ]["percent"],
            "geometry_z_both_zero_percent": topology["geometry"][
                "z_both_endpoints_zero"
            ]["percent"],
            "node_facility_candidate_count": facilities[
                "node_facility_candidate_count"
            ],
            "distinct_facility_count": facilities["distinct_facility_count"],
            "nodes_with_candidate_facility_count": facilities[
                "nodes_with_candidate_facility_count"
            ],
            "mapped_pipeline_endpoint_count": facilities[
                "mapped_pipeline_endpoint_count"
            ],
            "mapped_pipeline_endpoint_percent": facilities[
                "mapped_pipeline_endpoint_percent"
            ],
            "residual_unmatched_pipeline_endpoint_count": facilities[
                "residual_unmatched_pipeline_endpoint_count"
            ],
            "nodes_with_surface_intake_candidate_count": facilities[
                "nodes_with_surface_intake_candidate_count"
            ],
            "nodes_with_outfall_candidate_count": facilities[
                "nodes_with_outfall_candidate_count"
            ],
            "nodes_with_pump_candidate_count": facilities[
                "nodes_with_pump_candidate_count"
            ],
            "source_target_node_labels_are_verified_hydraulic_direction": facilities[
                "source_target_node_labels_are_verified_hydraulic_direction"
            ],
            "outfall_or_pump_connectivity_authoritative": facilities[
                "outfall_or_pump_connectivity_authoritative"
            ],
            "nodes_are_surface_patches": facilities["nodes_are_surface_patches"],
            "outputs": network_manifest["outputs"],
            "admitted": network_manifest["admitted"],
            "diagnostic_only": network_manifest["diagnostic_only"],
            "flood_network_contract_compiled": network_manifest[
                "flood_network_contract_compiled"
            ],
        }
    readiness_path = root / "derived/makani_registered/hybrid_readiness_audit.json"
    if readiness_path.exists():
        readiness = _read_json(readiness_path)
        result["hybrid_readiness"] = {
            "path": str(readiness_path.relative_to(root)),
            "sha256": sha256_file(readiness_path),
            "schema": readiness["schema"],
            "engineering_field_audit": readiness["engineering_field_audit"],
            "blocker_count": len(readiness["blockers"]),
            "gates": readiness["gates"],
            "architecture_contract": readiness["architecture_contract"],
            "target_clipped_surface_candidate_summary": readiness[
                "target_clipped_surface_candidate_summary"
            ],
            "admission": readiness["admission"],
        }
    return result


def _k0_gate(
    weather: dict[str, Any],
    terrain: dict[str, Any],
    smartmakani: dict[str, Any],
    runtime_catalog: dict[str, Any],
    registered_snapshot: dict[str, Any],
) -> dict[str, Any]:
    pipeline = _layer_by_id(smartmakani["layers"], 37)
    topology = smartmakani["pipeline_topology_candidate"]
    registered_network = registered_snapshot.get("network_candidate", {})
    surface_support = smartmakani.get("supporting_surface_candidate", {})
    surface_summary = surface_support.get("surface_candidate_summary", {})
    clipped_surface = smartmakani.get("target_clipped_surface_candidate", {})
    clipped_datasets = {
        item["dataset_key"]: item for item in clipped_surface.get("datasets", [])
    }
    incident_layers = [
        _layer_by_id(smartmakani["layers"], layer_id) for layer_id in (2, 3, 30, 32)
    ]
    criteria = [
        {
            "criterion": "observed_event_rainfall",
            "status": "blocked",
            "evidence": "Open-Meteo and NASA POWER/MERRA2 are public gridded candidates only",
            "passed": weather["observed_rainfall_available"],
        },
        {
            "criterion": "stormwater_hydraulic_topology_and_sections",
            "status": "partial",
            "evidence": (
                f"SmartMakani layer 37 has a frozen target snapshot of "
                f"{pipeline.get('frozen_feature_snapshot', {}).get('record_count', 0)} lines; "
                f"the diagnostic compiler produced {topology.get('node_count', 0)} snapped "
                f"nodes in {topology.get('connected_component_count', 0)} components; "
                f"registered Makani compilation has "
                f"{registered_network.get('pipeline_count', 0)} pipelines, "
                f"{registered_network.get('node_count', 0)} nodes and "
                f"{registered_network.get('node_facility_candidate_count', 0)} "
                "candidate node-facility relations"
            ),
            "passed": False,
            "remaining": (
                "verify engineering units and vertical datum; validate residual unmatched "
                "endpoints, outfall/pump relations and surface catchments; keep public versus "
                "registered geometry crosswalk candidate-only"
            ),
        },
        {
            "criterion": "pump_gate_and_outfall_event_operations",
            "status": "blocked",
            "evidence": (
                "static pump and outfall candidate resources exist but no 2024 event action log, "
                "pump curve, gate state, or measured discharge is admitted"
            ),
            "passed": False,
        },
        {
            "criterion": "matched_event_inundation_observations",
            "status": "blocked",
            "evidence": (
                "incident layers lack depth/duration measurements; MIMS records end in 2022 and "
                "do not overlap the April 2024 target event"
            ),
            "passed": any(
                layer.get("covers_target_2024_event")
                and bool(layer["incident_measure_fields"])
                for layer in incident_layers
            ),
        },
        {
            "criterion": "engineering_surface_and_vertical_datum",
            "status": "partial",
            "evidence": (
                "two complete 30 m proxy DEMs exist; frozen public support now contains "
                f"{surface_summary.get('contour_record_count', 0)} contour lines and "
                f"{surface_summary.get('building_record_count', 0)} building footprints; exact "
                "target clipping retained "
                f"{clipped_datasets.get('contour_2017_zone40', {}).get('output_record_count', 0)} "
                "contours and repaired two invalid buildings, but vertical datum, hydrological "
                "conditioning, roads, curbs, control points and surface-to-network crosswalks "
                "remain unverified"
            ),
            "passed": terrain["vertical_datum_verified"],
        },
        {
            "criterion": "coastal_outfall_boundary_time_series",
            "status": "blocked",
            "evidence": (
                "2017 bathymetry is discoverable but no target-event tide, surge, or sea-level "
                "boundary time series is admitted"
            ),
            "passed": False,
        },
        {
            "criterion": "source_authority_reuse_and_snapshot_provenance",
            "status": "partial",
            "evidence": (
                "user-confirmed download authorization and checksummed local feature snapshots "
                "are recorded; authoritative source version and formal reuse terms remain open"
            ),
            "passed": False,
        },
    ]
    return {
        "gate_id": "K0",
        "passed": all(item["passed"] for item in criteria),
        "status": "closed_not_admitted",
        "criteria": criteria,
        "registered_stormwater_resource_count": runtime_catalog.get(
            "stormwater_resource_count", 0
        ),
        "next_gate_allowed": False,
    }


def _artifact_inventory(root: Path, repo: Path) -> list[dict[str, Any]]:
    artifacts = []
    for subtree in ("online", "derived"):
        subtree_root = root / subtree
        if not subtree_root.exists():
            continue
        for path in sorted(subtree_root.rglob("*")):
            if not path.is_file() or path.name == ".gitkeep":
                continue
            artifacts.append(
                {
                    "path": str(path.relative_to(root)),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    **_artifact_origin(path),
                }
            )
    mapping_path = (
        repo
        / "docs/customer/abu_dhabi_liveability_site_validation/"
        "makani_pg_dictionary_mapping.csv"
    )
    if mapping_path.exists():
        artifacts.append(
            {
                "path": str(mapping_path.relative_to(repo)),
                "size_bytes": mapping_path.stat().st_size,
                "sha256": sha256_file(mapping_path),
                "origin": "registered_source_metadata_snapshot",
                "contains_source_rows": False,
            }
        )
    return artifacts


def _artifact_origin(path: Path) -> dict[str, Any]:
    relative = path.as_posix()
    if "/online/makani_registered/" in relative:
        contains_rows = path.suffix.lower() == ".parquet"
        return {
            "origin": (
                "registered_makani_field_minimized_feature_snapshot"
                if contains_rows
                else "registered_makani_snapshot_control"
            ),
            "contains_source_rows": contains_rows,
            "contains_raw_asset_identifiers": contains_rows,
            "contains_personal_fields": False,
            "credentials_persisted": False,
            "calibration_admission": "not_admitted_for_calibration",
        }
    if "/derived/makani_registered/" in relative:
        is_parquet = path.suffix.lower() == ".parquet"
        is_aggregate_probe = path.name == "makani_relationship_probe.json"
        contains_source_rows = path.name == "registered_stormwater_pipelines.parquet"
        is_network_candidate = path.name.startswith("registered_stormwater_") or path.name in {
            "registered_node_facility_candidates.parquet",
            "registered_network_candidate_audit.json",
            "registered_network_candidate_manifest.json",
        }
        if path.name == "hybrid_readiness_audit.json":
            return {
                "origin": "derived_abu_dhabi_hybrid_readiness_audit",
                "contains_source_rows": False,
                "contains_raw_asset_identifiers": False,
                "contains_personal_fields": False,
                "calibration_admission": "not_admitted_for_calibration",
            }
        return {
            "origin": (
                "derived_registered_makani_network_candidate"
                if is_network_candidate
                else (
                    "derived_registered_makani_row_crosswalk_candidate"
                    if is_parquet
                    else "registered_makani_aggregate_or_audit_candidate"
                )
            ),
            "contains_source_rows": contains_source_rows,
            "contains_raw_asset_identifiers": is_parquet,
            "aggregate_only": is_aggregate_probe,
            "contains_personal_fields": False,
            "calibration_admission": "not_admitted_for_calibration",
        }
    feature_match = re.search(r"/smartmakani/features/layer_(\d+)/", relative)
    if feature_match:
        layer_id = int(feature_match.group(1))
        contains_rows = "/pages/" in relative
        return {
            "origin": (
                "downloaded_public_arcgis_feature_snapshot"
                if contains_rows
                else "public_arcgis_feature_snapshot_control"
            ),
            "contains_source_rows": contains_rows,
            "public_feature_rows": contains_rows,
            "contains_personal_fields": False,
            "calibration_admission": "not_admitted_for_calibration",
            "source_url": f"{SMARTMAKANI_MAPSERVER}/{layer_id}/query",
        }
    supporting_feature_match = re.search(
        r"/smartmakani/features/"
        r"(contour_2017_zone40|bathymetry_2017|building_survey)/",
        relative,
    )
    if supporting_feature_match:
        dataset_key = supporting_feature_match.group(1)
        source_urls = {
            "contour_2017_zone40": (
                "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                "Topography/2017_Contour/MapServer/1/query"
            ),
            "bathymetry_2017": (
                "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                "Topography/2017_Bathymetry/MapServer/0/query"
            ),
            "building_survey": (
                "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                "SubAddressing/Building_Survey/FeatureServer/1/query"
            ),
        }
        contains_rows = "/pages/" in relative
        return {
            "origin": (
                "downloaded_public_surface_support_snapshot"
                if contains_rows
                else "public_surface_support_snapshot_control"
            ),
            "contains_source_rows": contains_rows,
            "public_feature_rows": contains_rows,
            "contains_personal_fields": False,
            "access_mode": "query_only",
            "calibration_admission": "not_admitted_for_calibration",
            "source_url": source_urls[dataset_key],
        }
    if "/smartmakani/supporting_evidence/" in relative:
        if path.name.startswith("contour_2017_zone40"):
            source_url = (
                "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                "Topography/2017_Contour/MapServer/1"
            )
        elif path.name.startswith("bathymetry_2017"):
            source_url = (
                "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                "Topography/2017_Bathymetry/MapServer/0"
            )
        elif path.name.startswith("building_survey"):
            source_url = (
                "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                "SubAddressing/Building_Survey/FeatureServer/1"
            )
        elif path.name.startswith("nccme_object_recognition"):
            source_url = (
                "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
                "Survey/NCCME_ObjectRecognition/MapServer/0"
            )
        else:
            source_url = "https://geosmart.dmt.gov.ae/arcgis/rest/services"
        return {
            "origin": "anonymous_arcgis_rest_metadata_or_aggregate_snapshot",
            "contains_source_rows": False,
            "contains_personal_fields": False,
            "access_mode": "query_only",
            "calibration_admission": "not_admitted_for_calibration",
            "source_url": source_url,
        }
    if "/derived/smartmakani/surface_clip_candidate/" in relative:
        dataset_match = re.search(
            r"/surface_clip_candidate/"
            r"(contour_2017_zone40|bathymetry_2017|building_survey)/",
            relative,
        )
        dataset_key = dataset_match.group(1) if dataset_match else None
        contains_rows = path.suffix.lower() == ".parquet"
        derived_from = (
            f"online/smartmakani/features/{dataset_key}/snapshot_manifest.json"
            if dataset_key
            else [
                "derived/smartmakani/surface_clip_candidate/"
                "contour_2017_zone40/manifest.json",
                "derived/smartmakani/surface_clip_candidate/"
                "bathymetry_2017/manifest.json",
                "derived/smartmakani/surface_clip_candidate/"
                "building_survey/manifest.json",
            ]
        )
        return {
            "origin": (
                "derived_target_clipped_surface_candidate"
                if contains_rows
                else "derived_target_clipped_surface_candidate_control"
            ),
            "contains_source_rows": contains_rows,
            "public_feature_rows": contains_rows,
            "contains_raw_asset_identifiers": contains_rows,
            "contains_personal_fields": False,
            "calibration_admission": "not_admitted_for_calibration",
            "derived_from": derived_from,
        }
    if "/derived/smartmakani/" in relative:
        if path.name == "supporting_surface_candidate_audit.json":
            return {
                "origin": "derived_static_surface_support_audit",
                "contains_source_rows": False,
                "public_feature_rows": False,
                "contains_personal_fields": False,
                "calibration_admission": "not_admitted_for_calibration",
                "derived_from": [
                    "online/smartmakani/features/contour_2017_zone40/"
                    "snapshot_manifest.json",
                    "online/smartmakani/features/bathymetry_2017/"
                    "snapshot_manifest.json",
                    "online/smartmakani/features/building_survey/"
                    "snapshot_manifest.json",
                ],
            }
        contains_rows = path.suffix.lower() in {".parquet", ".gpkg"}
        return {
            "origin": "derived_local_hydraulic_candidate",
            "contains_source_rows": contains_rows,
            "public_feature_rows": False,
            "contains_personal_fields": False,
            "calibration_admission": "not_admitted_for_calibration",
            "derived_from": (
                "online/smartmakani/features/layer_37/snapshot_manifest.json"
            ),
        }
    if "/smartmakani/" in relative:
        return {
            "origin": "anonymous_arcgis_rest_metadata_or_aggregate_snapshot",
            "contains_source_rows": False,
            "source_url": _smartmakani_artifact_url(path.name),
        }
    if path.name == "Copernicus_DSM_COG_10_N24_00_E054_00_DEM.tif":
        return {
            "origin": "downloaded_public_raster",
            "contains_source_rows": False,
            "source_url": COPERNICUS_TILE_SOURCE_URL,
        }
    if path.name == "N24E054.hgt.gz":
        return {
            "origin": "downloaded_public_raster",
            "contains_source_rows": False,
            "source_url": SRTM_TILE_SOURCE_URL,
        }
    if path.name == "N24E054.hgt":
        return {
            "origin": "derived_local_raster",
            "contains_source_rows": False,
            "derived_from": "online/terrain/N24E054.hgt.gz",
        }
    if path.suffix.lower() in {".tif", ".hgt", ".gz"}:
        derived_from = None
        if "srtm" in path.name:
            derived_from = "online/terrain/N24E054.hgt"
        elif "copernicus" in path.name.lower():
            derived_from = (
                "online/terrain/Copernicus_DSM_COG_10_N24_00_E054_00_DEM.tif"
            )
        return {
            "origin": "derived_local_raster",
            "contains_source_rows": False,
            "derived_from": derived_from,
        }
    if "/weather/" in relative:
        source_url = {
            "openmeteo_archive_abu_dhabi_20240415_20240417.json": (
                OPENMETEO_SOURCE_URL
            ),
            "nasa_power_hourly_prectotcorr_abu_dhabi_20240415_20240417.json": (
                NASA_POWER_HOURLY_SOURCE_URL
            ),
            "nasa_power_daily_prectotcorr_abu_dhabi_20240415_20240417.json": (
                NASA_POWER_DAILY_SOURCE_URL
            ),
        }.get(path.name)
        return {
            "origin": "downloaded_public_weather_response",
            "contains_source_rows": False,
            "source_url": source_url,
        }
    derived_from = path.name.removesuffix(".aux.xml") if path.name.endswith(".aux.xml") else None
    return {
        "origin": "local_sidecar",
        "contains_source_rows": False,
        "derived_from": f"online/terrain/{derived_from}" if derived_from else None,
    }


def _smartmakani_artifact_url(name: str) -> str:
    if name.startswith("services_"):
        folder = name.removeprefix("services_").removesuffix(".json")
        return f"https://geosmart.dmt.gov.ae/arcgis/rest/services/{folder}?f=pjson"
    if name == "rain_incidents_mapserver.json":
        return f"{SMARTMAKANI_MAPSERVER}?f=pjson"
    if name.startswith("rain_incidents_layer_"):
        stem = name.removeprefix("rain_incidents_layer_").removesuffix(".json")
        layer_id = stem.split("_", 1)[0]
        suffix = stem.removeprefix(layer_id)
        if not suffix:
            return f"{SMARTMAKANI_MAPSERVER}/{layer_id}?f=pjson"
        return f"{SMARTMAKANI_MAPSERVER}/{layer_id}/query"
    service_urls = {
        "contour_2017_mapserver.json": (
            "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
            "Topography/2017_Contour/MapServer?f=pjson"
        ),
        "bathymetry_2017_mapserver.json": (
            "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
            "Topography/2017_Bathymetry/MapServer?f=pjson"
        ),
        "satellite_2024_q3_15cm_imageserver.json": (
            "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
            "Images/2024_Q3_SatImg_15cm_All/ImageServer?f=pjson"
        ),
    }
    if name not in service_urls:
        raise ValueError(f"unmapped_smartmakani_artifact:{name}")
    return service_urls[name]


def render_inventory_markdown(inventory: dict[str, Any]) -> str:
    weather = {item["product_id"]: item for item in inventory["weather"]["products"]}
    terrain = {item["product_id"]: item for item in inventory["terrain"]["rasters"]}
    smart_layers = inventory["smartmakani"]["layers"]
    frozen_pipeline = _layer_by_id(smart_layers, 37)["frozen_feature_snapshot"]
    topology = inventory["smartmakani"]["pipeline_topology_candidate"]
    surface_support = inventory["smartmakani"].get(
        "supporting_surface_candidate", {}
    )
    surface_summary = surface_support.get("surface_candidate_summary", {})
    target_clip = inventory["smartmakani"].get(
        "target_clipped_surface_candidate", {}
    )
    target_clip_summary = target_clip.get("summary", {})
    postgres_audit = inventory.get("makani_postgres_source_audit", {})
    liveability_postgres_audit = inventory.get(
        "liveability_postgres_source_audit", {}
    )
    cross_source_geography_audit = inventory.get("cross_source_geography_audit", {})
    clipped_contour_count = next(
        (
            item["output_record_count"]
            for item in target_clip.get("datasets", [])
            if item["dataset_key"] == "contour_2017_zone40"
        ),
        0,
    )
    key_resources = inventory["registered_makani_runtime_catalog"]["key_resources"]
    registered = inventory["registered_makani_spatial_snapshot"]
    orientation = registered.get("crosswalk_candidate", {}).get(
        "orientation_diagnostic",
        {},
    )
    registered_network = registered.get("network_candidate", {})
    readiness = registered.get("hybrid_readiness", {})
    engineering = readiness.get("engineering_field_audit", {})
    if readiness:
        length_alignment = engineering["pipe_length"][
            "within_1_percent_if_source_unit_is_m"
        ]
        z_both_zero = engineering["geometry_z"]["both_zero"]
        gradient_outliers = engineering["gradient"][
            "absolute_ge_1_candidate_outlier"
        ]
        readiness_summary = (
            "本轮 readiness 审计将候选数据基础标记为 `candidate_ready`（仅诊断）；"
            "传统水动力基线为 `blocked`，GWM 训练为 `blocked`，混合规划仅为"
            f" `contract_ready_not_executable`。当前共记录 `{readiness['blocker_count']}` "
            "项阻断，未改变 K0 的关闭状态。"
        )
        engineering_summary = (
            "在仅用于诊断的米制假设下，源 `pipe_length` 与投影几何长度相差不超过 "
            f"1% 的记录为 `{length_alignment['count']:,}` 条"
            f"（`{length_alignment['percent']:.2f}%`）；这不能替代源单位确认。"
            f"登记几何两端 Z 同为 0 的比例为 `{z_both_zero['percent']:.2f}%`，"
            f"坡度绝对值不小于 1 的候选异常记录为 `{gradient_outliers['count']:,}` 条。"
        )
    else:
        readiness_summary = "传统模型/GWM readiness 审计尚未生成。"
        engineering_summary = "登记管网工程字段审计尚未生成。"
    lines = [
        "# 阿布扎比暴雨内涝可用数据盘点",
        "",
        f"生成时间：`{inventory['created_at']}`  ",
        "状态：`K0 closed`、`diagnostic_only=true`、`operator_admitted=false`。",
        "",
        "## 结论",
        "",
        (
            "SmartMakani 确实补充了有价值的数据：阿布扎比雨水线图层公开了管径、"
            "上下游管底标高、起终点坐标和外排口字段；本次冻结目标范围内 "
            f"{frozen_pipeline['record_count']:,} 条相交线段，并完成页级校验。"
        ),
        (
            "但公开服务尚未提供 2024-04-15 至 2024-04-17 的地面雨量观测、泵闸动作、"
            "潮位边界和带水深/持续时间的同事件积水观测，因此不能据此开放 K0 或宣称"
            "城市尺度预测能力。"
        ),
        "",
        "## 降雨候选",
        "",
        "| 产品 | 时间支持 | 正确累计量 | 准入 |",
        "|---|---:|---:|---|",
        (
            "| Open-Meteo archive 点产品 | 72 小时 | "
            f"{weather['openmeteo_archive_point_hourly']['total_interval_depth_mm']:.2f} mm | "
            "reanalysis_candidate / not admitted |"
        ),
        (
            "| NASA POWER MERRA2 小时产品 | 72 小时 | "
            f"{weather['nasa_power_merra2_point_hourly']['total_interval_depth_mm']:.5f} mm | "
            "reanalysis_candidate / not admitted |"
        ),
        (
            "| NASA POWER MERRA2 日产品 | 3 日 | "
            f"{weather['nasa_power_merra2_point_daily']['total_interval_depth_mm']:.2f} mm | "
            "reanalysis_candidate / not admitted |"
        ),
        "",
        (
            "NASA 小时字段单位是 `mm/day`。清单按每小时 `value / 24` 积分；原始值直接"
            "求和得到 "
            f"{weather['nasa_power_merra2_point_hourly']['raw_value_sum_not_a_depth']:.2f}，"
            "该数值不是 72 小时累计降雨，禁止作为模型强迫。"
        ),
        "",
        "## 地形候选",
        "",
        "| DEM | 网格 | 有效像元 | 高程范围 | 均值 | 准入 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for product_id in (
        "srtm_30m_clipped_epsg32640",
        "copernicus_dem_30m_clipped_epsg32640",
    ):
        item = terrain[product_id]
        lines.append(
            f"| {product_id} | {item['width']} x {item['height']} @ 30 m | "
            f"{item['valid_pixel_percent']:.2f}% | {item['minimum_m']:.3f}.."
            f"{item['maximum_m']:.3f} m | {item['mean_m']:.3f} m | public_proxy / not admitted |"
        )
    difference = inventory["terrain"]["srtm_minus_copernicus"]
    lines.extend(
        [
            "",
            (
                "同网格比较（SRTM - Copernicus）："
                f"MAE `{difference['mean_absolute_error_m']:.4f} m`，"
                f"RMSE `{difference['root_mean_square_error_m']:.4f} m`，"
                f"绝对差 P95 `{difference['absolute_difference_p95_m']:.4f} m`。"
                "在垂直基准、海陆掩膜和工程控制点校核前，两者不可互换。"
            ),
            "",
            "## 静态地表与建筑阻挡候选",
            "",
            (
                f"已冻结 `{surface_summary.get('contour_record_count', 0):,}` 条 2017 年"
                f"等高线、`{surface_summary.get('bathymetry_record_count', 0):,}` 条静态"
                f"测深线和 `{surface_summary.get('building_record_count', 0):,}` 个建筑"
                "轮廓。建筑仅保留 ObjectID、层数、高度、物理状态和几何；名称、地址、"
                "社区、地块及业务标识字段均未下载。"
            ),
            (
                "这些数据改善了静态地表和阻挡物先验，但等高线/测深垂直基准、建筑高度"
                "单位、道路缘石、墙体、地表汇流调平和地表到管网绑定仍未核定。因此未生成"
                "工程 DEM 或 `SurfacePatch`，K0 保持关闭。"
            ),
            (
                "空间查询按目标 bbox 相交关系选择要素，但 ArcGIS 服务返回相交要素的完整"
                "几何，并未按 bbox 裁切；尤其测深线可延伸到目标区外，不能解释为已完成"
                "目标区海底面裁切。建筑中另有 "
                f"`{surface_summary.get('building_invalid_geometry_count', 0):,}` "
                "个无效几何，进入阻挡层前必须修复并保留修复审计。"
            ),
            (
                "本地精确裁切与二维几何修复候选现已编译：目标区内等高线为 "
                f"`{clipped_contour_count:,}` 条，较服务 ObjectID 快照少 "
                f"`{target_clip_summary.get('dropped_after_selection_count', 0):,}` "
                "条；2 个无效建筑均已修复，输出越界、无效和带 Z 几何均为 0。该产物仍未"
                "建立垂直基准、水文调平或地表—管网绑定，不能视为工程 DEM。"
            ),
            "",
            "## SmartMakani 关键图层",
            "",
            "| 图层 | 元数据全量 | 元数据目标范围 | 本次冻结 | 时间/水力信息 | 结论 |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for layer_id in (2, 3, 30, 32, 37):
        layer = _layer_by_id(smart_layers, layer_id)
        if layer_id == 37:
            info = "管径、上下游管底标高、端点、材质、外排口"
            conclusion = "高价值网络候选；需清洗哨兵值、重建拓扑和核定单位"
        elif layer.get("case_creation_time_range_utc"):
            time_range = layer["case_creation_time_range_utc"]
            info = f"{time_range[0][:10]}..{time_range[1][:10]}；无深度/持续时间"
            conclusion = "不覆盖 2024 目标事件"
        else:
            null_geometry_count = layer.get("frozen_feature_snapshot", {}).get(
                "null_geometry_count",
                0,
            )
            info = (
                "无日期字段；无深度/持续时间；"
                f"空几何 {null_geometry_count} 条"
            )
            conclusion = "静态易涝/事件位置代理"
        target_count = layer["target_bbox_feature_count"]
        frozen_count = layer.get("frozen_feature_snapshot", {}).get("record_count")
        lines.append(
            f"| {layer_id} {layer['name']} | {layer['feature_count']:,} | "
            f"{target_count if target_count is not None else '-'} | "
            f"{frozen_count if frozen_count is not None else '-'} | {info} | {conclusion} |"
        )
    lines.extend(
        [
            "",
            (
                "图层 30、31、32 的要素数和日期范围相同，且均无 definition expression。"
                "它们是同一未过滤业务视图的不同渲染入口，不能当作三个独立数据集叠加计数。"
            ),
            (
                "本次冻结进一步确认图层 30 与 32 的 ObjectID 和要素页内容完全一致。"
                "图层 3 的 12 条源几何全部为空，`POINT_X/POINT_Y` 只能作为待核坐标，"
                "不能直接当作已验证空间观测。"
            ),
            (
                "图层 37 的源几何 CRS 是 EPSG:4326，而服务返回范围可投影到 EPSG:32640；"
                "`SHAPE_Length` 不能直接按米使用，必须在目标投影下重算。管底标高同时出现"
                " `-999` 和异常大值，进入图编译前必须执行哨兵值和单位审计。"
            ),
            (
                f"旧目标范围计数为 `{frozen_pipeline['baseline_metadata_count']:,}`，本次 "
                f"ObjectID 冻结为 `{frozen_pipeline['record_count']:,}`，变化 "
                f"`{frozen_pipeline['record_count_delta_from_baseline']:+,}`。这两个时点的"
                "公开服务快照不可混作同一版本。"
            ),
            "",
            "## 管网拓扑候选审计",
            "",
            (
                f"1 m 端点吸附后得到 `{topology['node_count']:,}` 个节点和 "
                f"`{topology['connected_component_count']:,}` 个连通分量；最大分量含 "
                f"`{topology['largest_component_node_count']:,}` 个节点。"
            ),
            (
                f"发现 `{topology['self_loop_count']:,}` 条吸附后自环、"
                f"`{topology['duplicate_node_pair_group_count']:,}` 组重复节点对和 "
                f"`{topology['near_zero_length_count']:,}` 条近零长度线。上下游管底标高"
                f"同时落入候选合理范围的比例为 "
                f"`{topology['both_inverts_plausible_candidate_percent']:.2f}%`，其中 "
                f"`{topology['flow_direction_conflict_percent']:.2f}%` 与标称流向冲突。"
            ),
            (
                f"虽然几何全部带 Z，但 `{topology['geometry_z_both_zero_percent']:.2f}%` "
                "的线两端 Z 都为 0；在 Z 与候选有效管底标高均可比较的记录中，仅 "
                f"`{topology['geometry_z_match_percent_of_comparable_rows']:.2f}%` 能在任一"
                "方向以 0.01 容差匹配。Z 的单位和垂直基准未验证，禁止直接作为高程。"
            ),
            (
                "该产物是 `admitted=false` 的管线拓扑诊断候选。管线节点不是地表汇水"
                "单元；登记快照虽已补充设施候选关系，但尚未成为权威汇水区、泵、外排口"
                "或地表到管网绑定，因此没有强行编译 `FloodNetwork`。"
            ),
            "",
            "## 已登记 Makani 雨水资源候选",
            "",
            "| 资源 | 估计记录数 | 字段数 | 声明外键 |",
            "|---|---:|---:|---:|",
        ]
    )
    for item in key_resources:
        lines.append(
            f"| {item['physical_resource']} | {item['estimated_record_count']:,} | "
            f"{item['field_count']} | {item['foreign_key_count']} |"
        )
    if postgres_audit.get("available"):
        postgres_tables = {
            item.get("table"): item
            for item in postgres_audit.get("tables", [])
            if item.get("row_count") is not None
        }
        lines.extend(
            [
                "",
                "## 客户 PostgreSQL 运行库新增审计",
                "",
                (
                    "客户提供的 `makani_sync_full.public` 已完成只读元数据与聚合审计；"
                    "审计不导出业务行、不创建源端对象，字典只作为候选语义。"
                    f"本次检查 `{postgres_audit['summary'].get('tables_inspected', 0)}` 张候选表，"
                    f"其中 `{postgres_audit['summary'].get('tables_without_foreign_key', 0)}` "
                    "张无声明外键，"
                    "K0 仍保持 `closed_not_admitted`。"
                ),
                "",
                "| 运行表 | 记录数 | 几何 | 当前判断 |",
                "|---|---:|---|---|",
            ]
        )
        for name in (
            "pipeline",
            "inlet",
            "catchbasin",
            "manholechamber",
            "outfall",
            "ps_pump",
            "sw_pumpingstationstructure",
            "sw_flowmeter",
            "m_ncms_met_stations",
            "udm_floodwaterline",
        ):
            item = postgres_tables.get(name)
            if not item:
                continue
            geometry = ", ".join(
                f"{field} SRID {details.get('srid_min')}..{details.get('srid_max')}"
                for field, details in item.get("geometry", {}).get("columns", {}).items()
            ) or "无有效几何"
            role = item.get("readiness_role", "candidate")
            lines.append(
                f"| `{name}` | {item['row_count']:,} | {geometry} | {role} |"
            )
        endpoint_rows = postgres_audit.get("pipeline_endpoint_facility_probe", {}).get("rows", [])
        for row in endpoint_rows:
            lines.append(
                f"`pipeline.{row['side']}` 与候选设施 `unitid` 的聚合匹配覆盖 "
                f"`{row['matched_row_rate']:.2%}`；这是候选 crosswalk，不是声明外键或水力连通证明。"
            )
        lines.extend(
            [
                "管底/盖面标高存在 `-999` 哨兵、零值和极端值，`pipe_length` 存在零值，"
                "必须先核定单位、垂直基准、版本状态和异常规则，不能直接编译 SWMM/ANUGA。",
                "详细产物位于 `derived/makani_pg_audit/`，包括运行库审计、字典映射和 K0 缺口报告。",
            ]
        )
    if liveability_postgres_audit.get("available"):
        liveability_resources = {
            item.get("resource"): item
            for item in liveability_postgres_audit.get("resources", [])
            if item.get("row_count") is not None
        }
        liveability_summary = liveability_postgres_audit["summary"]
        liveability_requested = liveability_summary.get("resources_requested", 0)
        liveability_found = liveability_summary.get("resources_found", 0)
        liveability_fk_count = liveability_summary.get(
            "declared_foreign_key_count", 0
        )
        lines.extend(
            [
                "",
                "## 客户 Liveability PostgreSQL 运行库新增审计",
                "",
                (
                    "客户提供的 `liveability_data_20260730.public` 已完成只读元数据与聚合审计；"
                    "审计不导出业务行、设施名称、地址或几何，旧字典只作为候选语义。"
                    f"本次检查 `{liveability_requested}` 个候选对象，"
                    f"运行库找到 `{liveability_found}` 个，"
                    f"声明外键 `{liveability_fk_count}` 个；"
                    "K0 仍保持 `closed_not_admitted`。"
                ),
                "",
                "| 运行对象 | 记录数 | 几何 | 内涝世界模型角色 |",
                "|---|---:|---|---|",
            ]
        )
        for name in (
            "dim_districts",
            "dim_facilities",
            "dim_udm_plots",
            "fact_population",
            "fact_population_ultimate",
            "fact_facilities",
            "fact_facilities_his",
            "fact_facility_provision",
            "fact_residential_plots",
            "fact_infrastructure_completion",
            "fact_qol_district_scores",
            "fact_qol_facility_scores",
            "fact_prioritization_runs",
            "fact_prioritization_cost_outputs",
            "fact_prioritization_district_classification",
            "fact_prioritization_gap_outputs",
            "fact_prioritization_processed_scores",
            "fact_prioritization_export_log",
            "nrn_road_edges",
            "view_all_facility_points",
            "vw_point_facilities",
            "vw_line_facilities",
            "vw_polygon_facilities",
        ):
            item = liveability_resources.get(name)
            if not item:
                continue
            geometry = ", ".join(
                f"{field} SRID {details.get('srid_min')}..{details.get('srid_max')}"
                for field, details in item.get("geometry", {}).items()
            ) or "无有效几何"
            lines.append(
                f"| `{name}` | {item['row_count']:,} | {geometry} | "
                f"{item.get('readiness_role', 'context_candidate')} |"
            )
        lines.extend(
            [
                "",
                "该库的有效角色是行政区聚合、关键设施/地块/人口暴露、道路中断影响和规划优先级后处理"
                "（impact/exposure and decision context）；"
                "它不是降雨强迫、潮位边界、泵闸运行、积水观测或工程排水拓扑来源。",
                "`sim_*` 对象在当前运行库为空或属于既有宜居业务情景，"
                "不能解释为内涝水动力模拟结果或 GWM 训练样本。",
                "旧字典来自早期数据库快照，当前运行库行数以本次审计为准；"
                "跨源实体不得依据同名、猜测 ID 或邻近关系直接绑定。",
                "详细产物位于 `derived/liveability_pg_audit/`，包括运行库审计、"
                "字典映射和影响层缺口报告。",
            ]
        )
    if cross_source_geography_audit.get("available"):
        relationships = {
            (item.get("left"), item.get("right")): item
            for item in cross_source_geography_audit.get("results", [])
        }
        plot_link = relationships.get(
            (
                "makani.public.udm_plot.plotid",
                "liveability.public.dim_udm_plots.plotid",
            )
        )
        district_link = relationships.get(
            (
                "makani.public.udm_plot.districtid",
                "liveability.public.dim_districts.district_id",
            )
        )
        pipeline_district_link = relationships.get(
            (
                "makani.public.pipeline.zone_or_district_code",
                "liveability.public.dim_districts.district_id",
            )
        )
        lines.extend(
            [
                "",
                "## Makani--Liveability 跨源地理候选审计",
                "",
                (
                    "本审计只在进程内对规范化 ID 集合执行 trim/uppercase 后的聚合交集计算；"
                    "不落盘任何源 ID、要素记录或几何。交集只能用于发现候选 crosswalk，"
                    "不能证明实体同一性、水力连通或授权关联。"
                ),
                "",
                "| 候选关系 | 左侧 distinct | 右侧 distinct | 共享 distinct | "
                "左侧覆盖 | 右侧覆盖 |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in (pipeline_district_link, district_link, plot_link):
            if not item or item.get("status") != "available":
                continue
            lines.append(
                f"| `{item['left']}` -> `{item['right']}` | "
                f"{item['left_distinct_values']:,} | {item['right_distinct_values']:,} | "
                f"{item['overlapping_distinct_values']:,} | "
                f"{item['left_distinct_overlap_rate']:.2%} | "
                f"{item['right_distinct_overlap_rate']:.2%} |"
            )
        lines.extend(
            [
                "",
                (
                    "雨水管线 `zone_or_district_code` 与 Liveability `district_id` 的直接交集为 0，"
                    "禁止把该字段用作管网区级汇总键。"
                ),
                (
                    "Makani `udm_plot.plotid` 与 Liveability `dim_udm_plots.plotid` 的高覆盖交集"
                    "是优先核验的地块级 crosswalk 候选；在客户确认共同版本、权威关系、"
                    "输出粒度和隐私规则前，`per_asset_identity_admitted=false`。"
                ),
                "详细产物位于 `derived/cross_source_geography_audit/`；"
                "`aggregate_impact_overlay_admitted=false`，K0 不变。",
            ]
        )
    comparison = inventory["public_vs_registered_pipeline"]
    lines.extend(
        [
            "",
            (
                f"SmartMakani 图层 37 为 {comparison['smartmakani_public_feature_count']:,} 条，"
                f"已登记 `layer.st_pipeline` 为 "
                f"{comparison['registered_makani_estimated_record_count']:,} 条，差 "
                f"{comparison['absolute_count_delta']:,} 条。两者快照或范围未对齐，不能互相替代。"
            ),
            "",
            "## 登记 Makani 空间快照与关系证据",
            "",
            (
                f"已通过 source 13 的 `layer` 白名单下载字段最小化快照："
                f"`{registered['layer_count']}` 个图层、`{registered['record_count']:,}` 条"
                f"要素、`{registered['page_count']}` 个 GeoParquet 页。页级 SHA-256、列合同"
                "和 EPSG:32640 已校验；快照包含原始资产标识与几何，但不含地址、编辑用户、"
                "图片、评论或道路名称。"
            ),
            (
                f"目标范围登记管线为 `{comparison['registered_target_feature_count']:,}` 条，"
                f"比公共冻结管线多 `{comparison['target_count_delta']:,}` 条。八种显式 ID "
                "组合均无交集；严格几何规则得到 "
                f"`{comparison['geometry_crosswalk_candidate_count']:,}` 条候选交叉映射，"
                f"覆盖公共管线 `{comparison['public_geometry_crosswalk_coverage_percent']:.2f}%`。"
                "该映射不是权威资产同一性。"
            ),
            (
                f"`unitid` 精确关系得到 "
                f"`{registered['crosswalk_candidate']['facility_attachment_count']:,}` 条管线端点"
                f"设施附着，覆盖有效引用 "
                f"`{registered['crosswalk_candidate']['attachment_percent_of_valid_references']:.2f}%`；"
                f"其中 `{registered['crosswalk_candidate']['within_1m_count']:,}` 条在 1 m 内。"
                "`outfallid` 与 outfall 候选字段、`pump_station_id` 与泵站候选字段的精确匹配"
                "均为 0，禁止把这两列当作已证实外键。"
            ),
            (
                "两端均附着的管线中，"
                f"`{orientation['before_start_after_end_preferred_count']:,}` "
                "条支持 asset_before 对应几何起点、asset_after 对应终点，"
                f"`{orientation['before_end_after_start_preferred_count']:,}` "
                "条支持反向。该统计是方向诊断，不能替代源系统关系声明。"
            ),
            (
                "登记管线全量拓扑候选包含 "
                f"`{registered_network['pipeline_count']:,}` 条边、"
                f"`{registered_network['node_count']:,}` 个 1 m 吸附节点和 "
                f"`{registered_network['connected_component_count']:,}` 个连通分量；"
                f"`{registered_network['node_facility_candidate_count']:,}` 条去重后的"
                "节点-设施候选关系覆盖 "
                f"`{registered_network['mapped_pipeline_endpoint_count']:,}` 个管线端点"
                f"（`{registered_network['mapped_pipeline_endpoint_percent']:.2f}%`）。"
            ),
            (
                f"仍有 `{registered_network['residual_unmatched_pipeline_endpoint_count']:,}` "
                "个管线端点没有 1 m 内设施候选。候选 outfall 节点为 "
                f"`{registered_network['nodes_with_outfall_candidate_count']:,}` 个，候选 pump "
                f"节点为 `{registered_network['nodes_with_pump_candidate_count']:,}` 个；"
                "二者都未建立权威连通，source/target 也只表示几何方向而非已验证水流方向。"
            ),
            readiness_summary,
            engineering_summary,
            "",
            "## K0 准入门",
            "",
            "| 条件 | 状态 |",
            "|---|---|",
        ]
    )
    for criterion in inventory["k0_data_gate"]["criteria"]:
        lines.append(f"| {criterion['criterion']} | {criterion['status']} |")
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "1. 固化公开快照的正式版本标识和复用条款，并解释旧计数与本次冻结差异。",
            "2. 人工复核残余未匹配端点和几何交叉映射，核定 outfall、泵站及地表汇水区关系。",
            "3. 核定管径、容量和管底标高单位及垂直基准，处置自环、重复边和方向冲突。",
            "4. 获取 2024 目标事件的雨量计/雷达、潮位、泵闸运行与带时间的积水深度观测。",
            "5. K0 通过后再进入 SWMM/二维地表模型编译、事件校准和独立盲测。",
            "",
        ]
    )
    return "\n".join(lines)


def _finite_values(values: Any) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or any(not math.isfinite(value) for value in result):
        raise ValueError("weather_values_must_be_nonempty_and_finite")
    return result


def _geojson_point(payload: dict[str, Any]) -> dict[str, float]:
    longitude, latitude, *height = payload["geometry"]["coordinates"]
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "elevation_m": float(height[0]) if height else None,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("error"):
        raise ValueError(f"arcgis_snapshot_contains_error:{path.name}")
    return payload


def _query_statistics(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    features = payload.get("features") or []
    if not features:
        raise ValueError(f"arcgis_statistics_missing:{path.name}")
    return dict(features[0].get("attributes") or {})


def _wkid(spatial_reference: dict[str, Any] | None) -> int | None:
    if not spatial_reference:
        return None
    value = spatial_reference.get("latestWkid", spatial_reference.get("wkid"))
    return int(value) if value is not None else None


def _extent(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        "xmin": float(payload["xmin"]),
        "ymin": float(payload["ymin"]),
        "xmax": float(payload["xmax"]),
        "ymax": float(payload["ymax"]),
        "wkid": _wkid(payload.get("spatialReference")),
    }


def _epoch_ms_to_iso(value: int | float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _time_range_overlaps(
    candidate: list[str | None], target: tuple[str, str]
) -> bool:
    if len(candidate) != 2 or candidate[0] is None or candidate[1] is None:
        return False
    candidate_start = datetime.fromisoformat(candidate[0].replace("Z", "+00:00"))
    candidate_end = datetime.fromisoformat(candidate[1].replace("Z", "+00:00"))
    target_start = datetime.fromisoformat(target[0].replace("Z", "+00:00"))
    target_end = datetime.fromisoformat(target[1].replace("Z", "+00:00"))
    return candidate_start < target_end and candidate_end >= target_start


def _layer_by_id(layers: list[dict[str, Any]], layer_id: int) -> dict[str, Any]:
    try:
        return next(layer for layer in layers if layer["layer_id"] == layer_id)
    except StopIteration as exc:
        raise ValueError(f"smartmakani_layer_missing:{layer_id}") from exc


def _rounded(value: float, digits: int = 6) -> float:
    return round(float(value), digits)
