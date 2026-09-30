"""Acquire and audit public SmartMakani surface-support candidates.

The products in this module remain static diagnostic evidence.  They are not
compiled into an engineering DEM, a hydrologically conditioned surface, or a
SurfacePatch contract.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .smartmakani_acquisition import (
    TARGET_BBOX_WGS84,
    TARGET_CRS,
    SmartMakaniLayerSpec,
    _atomic_write_json,
    canonical_json_bytes,
    download_layer,
    sha256_bytes,
    sha256_file,
    utc_now,
)

CONTOUR_SERVICE = (
    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
    "Topography/2017_Contour/MapServer"
)
BATHYMETRY_SERVICE = (
    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
    "Topography/2017_Bathymetry/MapServer"
)
BUILDING_SERVICE = (
    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
    "SubAddressing/Building_Survey/FeatureServer"
)
NCCME_SERVICE = (
    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
    "Survey/NCCME_ObjectRecognition/MapServer"
)

SUPPORT_EVIDENCE_SCHEMA = "gwm.abu_dhabi_flood.surface_support_evidence.v1"
SUPPORT_AUDIT_SCHEMA = "gwm.abu_dhabi_flood.surface_support_audit.v1"

CONTOUR_FIELDS = ("OBJECTID", "Contour")
BATHYMETRY_FIELDS = ("OBJECTID", "ELEVATION")
BUILDING_FIELDS = (
    "OBJECTID",
    "BUILDINGNUMBEROFFLOORS",
    "BUILDINGHEIGHT",
    "PHYSICALSTATUS",
)

SUPPORTING_LAYER_SPECS = {
    "contour_2017_zone40": SmartMakaniLayerSpec(
        layer_id=1,
        role="static_2017_one_metre_contour_candidate",
        out_fields=CONTOUR_FIELDS,
        bbox_wgs84=TARGET_BBOX_WGS84,
        service_url=CONTOUR_SERVICE,
        dataset_key="contour_2017_zone40",
        snapshot_bbox_grid=(1, 1),
        snapshot_concurrency=1,
        snapshot_request_timeout_seconds=600.0,
        page_query_strategy="object_ids",
        page_concurrency=4,
        request_batch_size=1,
        page_request_timeout_seconds=120.0,
    ),
    "bathymetry_2017": SmartMakaniLayerSpec(
        layer_id=0,
        role="static_2017_coastal_bathymetry_candidate",
        out_fields=BATHYMETRY_FIELDS,
        bbox_wgs84=TARGET_BBOX_WGS84,
        service_url=BATHYMETRY_SERVICE,
        dataset_key="bathymetry_2017",
        page_query_strategy="auto",
        page_concurrency=1,
        nullable_out_fields=("ELEVATION",),
        required_non_null_fields=("ELEVATION",),
    ),
    "building_survey": SmartMakaniLayerSpec(
        layer_id=1,
        role="building_footprint_obstruction_candidate_privacy_minimized",
        out_fields=BUILDING_FIELDS,
        bbox_wgs84=TARGET_BBOX_WGS84,
        service_url=BUILDING_SERVICE,
        dataset_key="building_survey",
        snapshot_bbox_grid=(1, 1),
        snapshot_concurrency=1,
        snapshot_request_timeout_seconds=300.0,
        page_query_strategy="auto",
        page_concurrency=1,
    ),
}

_EXPECTED_GEOMETRY_TYPES = {
    "contour_2017_zone40": {"LineString", "MultiLineString"},
    "bathymetry_2017": {"LineString", "MultiLineString"},
    "building_survey": {"Polygon", "MultiPolygon"},
}

BUILDING_EXCLUDED_SOURCE_FIELDS = frozenset(
    {
        "BUILDINGID",
        "BUILDINGINTERNALID",
        "COMMUNITYNAMEARA",
        "COMMUNITYNAMEENG",
        "CONSTRUCTIONSITEID",
        "DISTRICTNAMEARA",
        "DISTRTICTNAMEENG",
        "ELMS_PLOTID",
        "GISID",
        "MUNICIPALITYNAME",
        "NAMEARABIC",
        "NAMEENGLISH",
        "NAMEPOPULARARABIC",
        "NAMEPOPULARENGLISH",
        "PLOT_PRIMARYLANDUSE",
        "PLOT_SECLANDUSE",
        "PRIMARYUSEENGDESC",
        "PRIMARYUSAGECATEGORYTYPE",
        "PRIMARYUSAGETYPE",
        "SECONDARYUSAGETYPE",
    }
)


async def _get_public_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("smartmakani_support_response_must_be_object")
    if error := payload.get("error"):
        raise RuntimeError(
            "smartmakani_support_query_failed:"
            f"{error.get('code')}:{error.get('message')}"
        )
    return payload


def _query_params(bbox: tuple[float, float, float, float]) -> dict[str, str]:
    return {
        "where": "1=1",
        "geometry": ",".join(str(value) for value in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "false",
        "returnCountOnly": "true",
        "f": "json",
    }


async def freeze_supporting_evidence(dataset_root: Path) -> dict[str, Any]:
    """Freeze layer metadata and target counts using read-only requests."""

    root = dataset_root.resolve()
    output_root = root / "online/smartmakani/supporting_evidence"
    manifest_path = output_root / "manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("schema") != SUPPORT_EVIDENCE_SCHEMA:
            raise ValueError("unsupported_surface_support_evidence_schema")
        if existing.get("write_operations_used") is not False:
            raise ValueError("surface_support_evidence_used_write_operation")
        for item in existing.get("layers", []):
            for path_key, hash_key in (
                ("metadata_path", "metadata_sha256"),
                ("target_count_path", "target_count_sha256"),
            ):
                path = root / item[path_key]
                if not path.is_file() or sha256_file(path) != item[hash_key]:
                    raise ValueError(
                        f"surface_support_evidence_checksum_mismatch:{path}"
                    )
        return existing
    layers: list[dict[str, Any]] = []
    for key, spec in SUPPORTING_LAYER_SPECS.items():
        metadata = await _get_public_json(spec.endpoint_url, {"f": "pjson"})
        count = await _get_public_json(
            f"{spec.endpoint_url}/query",
            _query_params(TARGET_BBOX_WGS84),
        )
        metadata_path = output_root / f"{key}_layer_metadata.json"
        count_path = output_root / f"{key}_target_count.json"
        _atomic_write_json(metadata_path, metadata)
        _atomic_write_json(count_path, count)
        layers.append(
            {
                "dataset_key": key,
                "endpoint_url": spec.endpoint_url,
                "metadata_path": str(metadata_path.relative_to(root)),
                "metadata_sha256": sha256_file(metadata_path),
                "target_count_path": str(count_path.relative_to(root)),
                "target_count_sha256": sha256_file(count_path),
                "target_count": int(count["count"]),
                "requests_used": ["layer_metadata_get", "query_return_count_only"],
                "access_mode": "query_only",
            }
        )

    nccme_endpoint = f"{NCCME_SERVICE}/0"
    nccme_metadata = await _get_public_json(nccme_endpoint, {"f": "pjson"})
    nccme_count = await _get_public_json(
        f"{nccme_endpoint}/query",
        _query_params(TARGET_BBOX_WGS84),
    )
    nccme_payload = {
        "schema": SUPPORT_EVIDENCE_SCHEMA,
        "dataset_key": "nccme_object_recognition_aggregate_only",
        "source_url": nccme_endpoint,
        "target_bbox_wgs84": list(TARGET_BBOX_WGS84),
        "target_count": int(nccme_count["count"]),
        "geometry_type": nccme_metadata.get("geometryType"),
        "service_extent": nccme_metadata.get("extent"),
        "source_field_names": [
            field.get("name") for field in nccme_metadata.get("fields", [])
        ],
        "source_rows_downloaded": False,
        "reason": "small_local_object_recognition_business_layer_not_a_surface_model_input",
        "contains_image_or_event_values": False,
        "access_mode": "query_only_aggregate_metadata",
        "calibration_admission": "not_admitted_for_calibration",
    }
    nccme_path = output_root / "nccme_object_recognition_aggregate.json"
    _atomic_write_json(nccme_path, nccme_payload)

    evidence = {
        "schema": SUPPORT_EVIDENCE_SCHEMA,
        "created_at": utc_now(),
        "target_bbox_wgs84": list(TARGET_BBOX_WGS84),
        "layers": layers,
        "aggregate_only_layers": [
            {
                "dataset_key": nccme_payload["dataset_key"],
                "path": str(nccme_path.relative_to(root)),
                "sha256": sha256_file(nccme_path),
                "target_count": nccme_payload["target_count"],
            }
        ],
        "credentials_used": False,
        "write_operations_used": False,
    }
    _atomic_write_json(manifest_path, evidence)
    return evidence


async def download_supporting_layers(
    dataset_root: Path,
    *,
    dataset_keys: tuple[str, ...] = tuple(SUPPORTING_LAYER_SPECS),
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    manifests = []
    for key in dataset_keys:
        try:
            spec = SUPPORTING_LAYER_SPECS[key]
        except KeyError as exc:
            raise ValueError(f"unsupported_supporting_surface_dataset:{key}") from exc
        manifests.append(
            await download_layer(dataset_root, spec, page_size=page_size)
        )
    return manifests


def _finite_summary(values: list[float]) -> dict[str, float | int | None]:
    import numpy as np

    array = np.asarray(values, dtype="float64")
    array = array[np.isfinite(array)]
    if not len(array):
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    return {
        "count": int(len(array)),
        "minimum": float(array.min()),
        "median": float(np.median(array)),
        "p95": float(np.quantile(array, 0.95)),
        "maximum": float(array.max()),
    }


def _source_count(root: Path, key: str) -> int | None:
    path = root / f"online/smartmakani/supporting_evidence/{key}_target_count.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return int(payload["count"])


def _audit_snapshot(root: Path, spec: SmartMakaniLayerSpec) -> dict[str, Any]:
    from shapely.geometry import shape

    layer_root = root / "online/smartmakani/features" / spec.storage_key
    manifest_path = layer_root / "snapshot_manifest.json"
    descriptor_path = layer_root / "snapshot.json"
    object_ids_path = layer_root / "object_ids.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    object_ids = json.loads(object_ids_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise ValueError(f"supporting_surface_snapshot_incomplete:{spec.storage_key}")
    if manifest.get("access_mode") != "query_only":
        raise ValueError(f"supporting_surface_access_mode_changed:{spec.storage_key}")
    if manifest.get("out_fields") != list(spec.out_fields):
        raise ValueError(f"supporting_surface_field_contract_changed:{spec.storage_key}")
    if descriptor.get("record_count") != len(object_ids):
        raise ValueError(f"supporting_surface_object_id_count_mismatch:{spec.storage_key}")
    if descriptor.get("object_ids_sha256") != sha256_file(object_ids_path):
        raise ValueError(f"supporting_surface_object_id_hash_mismatch:{spec.storage_key}")

    expected_fields = set(spec.out_fields)
    observed_fields: set[str] = set()
    geometry_types: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    null_geometry_count = 0
    empty_geometry_count = 0
    invalid_geometry_count = 0
    duplicate_object_id_count = 0
    seen_ids: set[Any] = set()
    numeric_values: dict[str, list[float]] = {
        field: [] for field in spec.out_fields if field != spec.object_id_field
    }
    measures: list[float] = []
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    row_count = 0

    expected_index = 0
    for page in manifest["pages"]:
        page_path = layer_root / page["path"]
        if page_path.stat().st_size != page["size_bytes"]:
            raise ValueError(f"supporting_surface_page_size_mismatch:{page_path}")
        if sha256_file(page_path) != page["sha256"]:
            raise ValueError(f"supporting_surface_page_hash_mismatch:{page_path}")
        payload = json.loads(page_path.read_text(encoding="utf-8"))
        features = payload.get("features")
        if not isinstance(features, list) or len(features) != page["record_count"]:
            raise ValueError(f"supporting_surface_page_count_mismatch:{page_path}")
        expected_page_ids = object_ids[expected_index : expected_index + len(features)]
        expected_index += len(features)
        page_ids = []
        for feature in features:
            properties = feature.get("properties") or {}
            observed_fields.update(properties)
            extra_fields = set(properties) - expected_fields
            if extra_fields:
                raise ValueError(
                    "supporting_surface_unexpected_fields:"
                    f"{spec.storage_key}:{','.join(sorted(extra_fields))}"
                )
            object_id = properties.get(spec.object_id_field)
            page_ids.append(object_id)
            if object_id in seen_ids:
                duplicate_object_id_count += 1
            seen_ids.add(object_id)
            row_count += 1

            for field, values in numeric_values.items():
                value = properties.get(field)
                if field == "PHYSICALSTATUS":
                    status_counts["<null>" if value is None else str(value)] += 1
                elif value is not None:
                    try:
                        values.append(float(value))
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"supporting_surface_non_numeric:{spec.storage_key}:{field}"
                        ) from None

            geometry = feature.get("geometry")
            if geometry is None:
                null_geometry_count += 1
                continue
            item = shape(geometry)
            geometry_types[item.geom_type] += 1
            if item.geom_type not in _EXPECTED_GEOMETRY_TYPES[spec.storage_key]:
                raise ValueError(
                    f"supporting_surface_geometry_type_changed:{spec.storage_key}:"
                    f"{item.geom_type}"
                )
            if item.is_empty:
                empty_geometry_count += 1
                continue
            if not item.is_valid:
                invalid_geometry_count += 1
            item_bounds = item.bounds
            bounds[0] = min(bounds[0], item_bounds[0])
            bounds[1] = min(bounds[1], item_bounds[1])
            bounds[2] = max(bounds[2], item_bounds[2])
            bounds[3] = max(bounds[3], item_bounds[3])
            measures.append(float(item.area if "building" in spec.storage_key else item.length))

        if page_ids != expected_page_ids:
            raise ValueError(f"supporting_surface_page_ids_changed:{page_path}")

    if expected_index != len(object_ids) or row_count != manifest["completed_record_count"]:
        raise ValueError(f"supporting_surface_total_count_mismatch:{spec.storage_key}")
    if observed_fields != expected_fields:
        missing = sorted(expected_fields - observed_fields)
        raise ValueError(
            f"supporting_surface_missing_fields:{spec.storage_key}:{','.join(missing)}"
        )
    source_count = _source_count(root, spec.storage_key)
    attributes = {
        field: _finite_summary(values)
        for field, values in numeric_values.items()
        if field != "PHYSICALSTATUS"
    }
    if spec.storage_key == "building_survey":
        attributes["physical_status_counts"] = dict(sorted(status_counts.items()))
    return {
        "dataset_key": spec.storage_key,
        "role": spec.role,
        "source_url": spec.endpoint_url,
        "record_count": row_count,
        "page_count": manifest["completed_page_count"],
        "target_crs": manifest["target_crs"],
        "spatial_selection": {
            "predicate": "esriSpatialRelIntersects",
            "request_bbox_wgs84": list(spec.bbox_wgs84),
            "returned_geometry_clipped_to_request_bbox": False,
            "geometry_may_extend_outside_request_bbox": True,
        },
        "source_target_count_before_id_freeze": source_count,
        "count_delta_after_id_freeze": (
            row_count - source_count if source_count is not None else None
        ),
        "field_contract": {
            "downloaded_fields": list(spec.out_fields),
            "unexpected_field_count": 0,
            "building_excluded_source_fields_present": bool(
                observed_fields.intersection(BUILDING_EXCLUDED_SOURCE_FIELDS)
            ),
        },
        "geometry": {
            "geometry_type_counts": dict(sorted(geometry_types.items())),
            "null_count": null_geometry_count,
            "empty_count": empty_geometry_count,
            "invalid_count": invalid_geometry_count,
            "duplicate_object_id_count": duplicate_object_id_count,
            "bounds_epsg32640": [
                None if not math.isfinite(value) else value for value in bounds
            ],
            "area_m2_summary" if "building" in spec.storage_key else "length_m_summary": (
                _finite_summary(measures)
            ),
        },
        "attributes": attributes,
        "manifest_path": str(manifest_path.relative_to(root)),
        "manifest_sha256": sha256_file(manifest_path),
        "snapshot_fingerprint": manifest["snapshot_fingerprint"],
        "content_fingerprint": manifest["content_fingerprint"],
        "calibration_admission": "not_admitted_for_calibration",
    }


def build_supporting_surface_audit(dataset_root: Path) -> dict[str, Any]:
    root = dataset_root.resolve()
    layers = [
        _audit_snapshot(root, SUPPORTING_LAYER_SPECS[key])
        for key in SUPPORTING_LAYER_SPECS
    ]
    by_key = {item["dataset_key"]: item for item in layers}
    contour = by_key["contour_2017_zone40"]
    bathymetry = by_key["bathymetry_2017"]
    buildings = by_key["building_survey"]
    return {
        "schema": SUPPORT_AUDIT_SCHEMA,
        "target_bbox_wgs84": list(TARGET_BBOX_WGS84),
        "target_crs": TARGET_CRS,
        "layers": layers,
        "surface_candidate_summary": {
            "contour_record_count": contour["record_count"],
            "contour_value_range_unverified_vertical_datum": [
                contour["attributes"]["Contour"]["minimum"],
                contour["attributes"]["Contour"]["maximum"],
            ],
            "bathymetry_record_count": bathymetry["record_count"],
            "bathymetry_value_range_unverified_vertical_datum": [
                bathymetry["attributes"]["ELEVATION"]["minimum"],
                bathymetry["attributes"]["ELEVATION"]["maximum"],
            ],
            "building_record_count": buildings["record_count"],
            "building_invalid_geometry_count": buildings["geometry"]["invalid_count"],
            "building_height_source_unit_verified": False,
            "returned_geometries_clipped_to_target_bbox": False,
            "vertical_datum_verified": False,
            "hydrologically_conditioned_surface_compiled": False,
            "surface_patch_contract_compiled": False,
        },
        "admission": {
            "static_surface_prior_candidate_available": True,
            "engineering_dem_admitted": False,
            "building_obstruction_layer_admitted": False,
            "coastal_boundary_time_series_admitted": False,
            "surface_patch_contract_compiled": False,
            "k0_opened": False,
        },
        "blockers": [
            "contour_and_bathymetry_vertical_datums_are_not_declared",
            "building_height_source_unit_is_not_declared",
            "contours_are_not_a_hydrologically_conditioned_bare_earth_surface",
            "roads_curbs_walls_and_drainage_surface_crosswalks_are_missing",
            "bathymetry_is_static_and_does_not_supply_event_tide_or_surge",
        ],
        "claim_boundary": [
            "downloaded_features_are_static_public_candidates_only",
            "features_were_selected_by_bbox_intersection_but_returned_with_complete_geometry",
            "no_engineering_dem_or_surface_patch_was_generated",
            "no_city_scale_flood_prediction_claim_is_allowed",
        ],
    }


def write_supporting_surface_audit(
    dataset_root: Path,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    root = dataset_root.resolve()
    destination = output_path or (
        root / "derived/smartmakani/supporting_surface_candidate_audit.json"
    )
    payload = build_supporting_surface_audit(root)
    _atomic_write_json(destination, payload)
    return {
        **payload,
        "output": {
            "path": str(destination.relative_to(root)),
            "size_bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "content_sha256": sha256_bytes(canonical_json_bytes(payload)),
        },
    }
