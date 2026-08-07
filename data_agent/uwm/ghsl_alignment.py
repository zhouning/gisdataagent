"""Align downloaded GHSL proxy rasters to UWM administrative units."""

from __future__ import annotations

import csv
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


GHSL_ADMIN_ALIGNMENT_SCHEMA = "uwm.ghsl_admin_alignment.v1"
GHSL_ADMIN_ALIGNMENT_VERSION = "0.1"


def align_ghsl_tiles_to_admin_units(
    *,
    ghsl_manifest_path: str | Path,
    admin_geojson_path: str | Path,
    output_dir: str | Path,
    created_at: str | None = None,
    max_features: int | None = None,
) -> dict[str, Any]:
    """Create an auditable GHSL population/built-surface proxy alignment artifact."""

    import geopandas as gpd

    ghsl_manifest_path = Path(ghsl_manifest_path)
    admin_geojson_path = Path(admin_geojson_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ghsl_manifest = _read_json(ghsl_manifest_path)
    admins = gpd.read_file(admin_geojson_path)
    if admins.empty:
        raise ValueError("admin_geojson_path contains no administrative features")
    crs_warning = None
    if admins.crs is None:
        admins = admins.set_crs("EPSG:4326")
        crs_warning = "admin input CRS was missing and was assumed to be EPSG:4326"
    else:
        admins = admins.to_crs("EPSG:4326")
    if max_features is not None:
        admins = admins.head(max_features).copy()

    ghsl_root = ghsl_manifest_path.parent
    layer_specs = {
        "population": _tile_specs(ghsl_manifest, ghsl_root, "population_tiles"),
        "built_surface": _tile_specs(ghsl_manifest, ghsl_root, "built_surface_tiles"),
    }

    with tempfile.TemporaryDirectory(prefix="uwm_ghsl_alignment_") as tmp:
        extracted_layers = {
            layer: _extract_tile_tifs(specs, Path(tmp) / layer)
            for layer, specs in layer_specs.items()
        }
        rows = _build_zonal_rows(admins, extracted_layers)

    zonal_csv = output_dir / "ghsl_admin_zonal_proxy.csv"
    _write_zonal_csv(zonal_csv, rows)
    artifact = {
        "schema": GHSL_ADMIN_ALIGNMENT_SCHEMA,
        "version": GHSL_ADMIN_ALIGNMENT_VERSION,
        "dataset_id": "ghsl_admin_zonal_proxy_alignment",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "source_dataset_ids": [
            str(ghsl_manifest.get("dataset_id") or "ghsl_population_built_proxy"),
            "chongqing_township_admin_units_local",
        ],
        "input_files": {
            "ghsl_manifest": str(ghsl_manifest_path),
            "admin_geojson": str(admin_geojson_path),
        },
        "alignment_status": "proxy_zonal_stats_available",
        "admin_feature_count": len(rows),
        "raster_layers": {
            layer: {
                "tile_count": len(specs),
                "zip_files": [str(spec["zip_path"]) for spec in specs],
                "aggregation": "sum_of_valid_pixels_inside_admin_geometry",
            }
            for layer, specs in layer_specs.items()
        },
        "files": {
            "zonal_stats_csv": zonal_csv.name,
        },
        "mmfe_target_roles": [
            "population_vulnerability",
            "urban_form",
            "remote_sensing_state",
            "equity_evaluation",
            "renderer_alignment",
        ],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "GHSL is a reproducible public proxy aligned to administrative units. "
                "It supports UWM state construction, but does not replace authoritative "
                "population, building, or observed health/environment holdout data."
            ),
        },
        "limitations": _limitations(crs_warning),
        "empirical_superiority_claim": False,
    }
    _write_json(output_dir / "ghsl_admin_alignment_manifest.json", artifact)
    return artifact


def validate_ghsl_admin_alignment(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the GHSL-to-administrative-unit alignment artifact contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != GHSL_ADMIN_ALIGNMENT_SCHEMA:
        errors.append(f"schema must be {GHSL_ADMIN_ALIGNMENT_SCHEMA}")
    if not payload.get("dataset_id"):
        errors.append("dataset_id is required")
    if payload.get("alignment_status") != "proxy_zonal_stats_available":
        errors.append("alignment_status must be proxy_zonal_stats_available")
    if int(payload.get("admin_feature_count") or 0) <= 0:
        errors.append("admin_feature_count must be positive")
    if not isinstance(payload.get("raster_layers"), dict):
        errors.append("raster_layers must be an object")
    files = payload.get("files") or {}
    if not isinstance(files, dict) or not files.get("zonal_stats_csv"):
        errors.append("files.zonal_stats_csv is required")
    if (payload.get("claim_boundary") or {}).get("max_claim_level") == "core_support":
        errors.append("GHSL proxy alignment cannot use core_support claim level")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must remain false for GHSL proxy alignment")
    return {"valid": not errors, "errors": errors}


def build_mmfe_state_input_from_ghsl_admin_alignment(
    alignment_manifest: dict[str, Any],
    zonal_rows: list[dict[str, Any]],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert a validated GHSL-admin alignment artifact into MMFE UWM state input."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    validation = validate_ghsl_admin_alignment(alignment_manifest)
    if not validation["valid"]:
        raise ValueError(f"invalid GHSL admin alignment: {validation['errors']}")

    rows = list(zonal_rows)
    admin_feature_count = int(alignment_manifest.get("admin_feature_count") or len(rows))
    population_nonzero_units = sum(_safe_float(row.get("population_proxy_sum")) > 0 for row in rows)
    built_surface_nonzero_units = sum(_safe_float(row.get("built_surface_proxy_sum")) > 0 for row in rows)
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": "mmfe-ghsl-admin-alignment-2020",
            "product_type": "semantic_fusion_product",
            "version": GHSL_ADMIN_ALIGNMENT_VERSION,
            "quality": {"score": 0.62},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "admin_unit_has_population_proxy",
                "uwm_usage": "population_vulnerability",
                "relation_count": population_nonzero_units,
            },
            {
                "semantic_relation_type": "admin_unit_has_built_surface_proxy",
                "uwm_usage": "urban_form",
                "relation_count": built_surface_nonzero_units,
            },
            {
                "semantic_relation_type": "admin_unit_defines_governance_unit",
                "uwm_usage": "administrative_units",
                "relation_count": admin_feature_count,
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "township_admin_unit",
                "crs": "EPSG:4326",
                "feature_count": admin_feature_count,
                "source": "chongqing_township_admin_units_local",
            },
            "role_bindings": [
                {
                    "role": "ghsl_population_2020_zonal_sum",
                    "uwm_role": "population_vulnerability",
                    "object_type": "admin_unit_numeric_attribute",
                    "source_dataset_id": str(alignment_manifest.get("dataset_id")),
                    "synthetic_status": "public_proxy",
                    "geometry_type": "polygon",
                    "spatial_support": {
                        "support_type": "admin_unit",
                        "support_id_field": "admin_unit_id",
                        "crs": "EPSG:4326",
                    },
                    "temporal_support": {
                        "resolution": "annual",
                        "valid_from": "2020",
                        "valid_to": "2020",
                    },
                    "aggregation_semantics": "total",
                    "observation_semantics": "derived",
                },
                {
                    "role": "ghsl_built_surface_2020_zonal_sum",
                    "uwm_role": "urban_form",
                    "object_type": "admin_unit_numeric_attribute",
                    "source_dataset_id": str(alignment_manifest.get("dataset_id")),
                    "synthetic_status": "public_proxy",
                    "geometry_type": "polygon",
                    "spatial_support": {
                        "support_type": "admin_unit",
                        "support_id_field": "admin_unit_id",
                        "crs": "EPSG:4326",
                    },
                    "temporal_support": {
                        "resolution": "annual",
                        "valid_from": "2020",
                        "valid_to": "2020",
                    },
                    "aggregation_semantics": "total",
                    "observation_semantics": "derived",
                },
                {
                    "role": "ghsl_built_surface_2020_remote_sensing_proxy",
                    "uwm_role": "remote_sensing_state",
                    "object_type": "admin_unit_numeric_attribute",
                    "source_dataset_id": str(alignment_manifest.get("dataset_id")),
                    "synthetic_status": "public_proxy",
                    "geometry_type": "polygon",
                    "spatial_support": {
                        "support_type": "admin_unit",
                        "support_id_field": "admin_unit_id",
                        "crs": "EPSG:4326",
                    },
                    "temporal_support": {
                        "resolution": "annual",
                        "valid_from": "2020",
                        "valid_to": "2020",
                    },
                    "aggregation_semantics": "total",
                    "observation_semantics": "derived",
                },
                {
                    "role": "chongqing_township_admin_unit",
                    "uwm_role": "administrative_units",
                    "object_type": "polygon",
                    "source_dataset_id": "chongqing_township_admin_units_local",
                    "synthetic_status": "real",
                    "geometry_type": "polygon",
                    "spatial_support": {
                        "support_type": "admin_unit",
                        "support_id_field": "admin_unit_id",
                        "crs": "EPSG:4326",
                    },
                    "aggregation_semantics": "category",
                    "observation_semantics": "observed",
                },
            ],
        },
        timestamp=timestamp,
    )
    payload["source_alignment"] = {
        "dataset_id": alignment_manifest.get("dataset_id"),
        "alignment_status": alignment_manifest.get("alignment_status"),
        "claim_boundary": alignment_manifest.get("claim_boundary"),
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "GHSL proxy state input supports UWM state construction but not empirical superiority claims without observed holdout validation"
    )
    return payload


def _tile_specs(manifest: dict[str, Any], root: Path, manifest_key: str) -> list[dict[str, Any]]:
    specs = []
    for entry in ((manifest.get("files") or {}).get(manifest_key) or []):
        zip_path = root / str(entry.get("file") or "")
        entries = [name for name in entry.get("zip_entries") or [] if str(name).lower().endswith(".tif")]
        if not zip_path.exists():
            raise FileNotFoundError(f"GHSL tile zip not found: {zip_path}")
        if not entries:
            raise ValueError(f"GHSL tile zip has no GeoTIFF entry in manifest: {zip_path}")
        with zipfile.ZipFile(zip_path) as archive:
            archive_names = set(archive.namelist())
        missing_entries = [name for name in entries if name not in archive_names]
        if missing_entries:
            raise ValueError(f"GHSL tile zip missing entries {missing_entries}: {zip_path}")
        specs.append({"zip_path": zip_path, "tif_entry": entries[0]})
    if not specs:
        raise ValueError(f"GHSL manifest does not contain {manifest_key}")
    return specs


def _extract_tile_tifs(specs: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for spec in specs:
        with zipfile.ZipFile(spec["zip_path"]) as archive:
            extracted = Path(archive.extract(spec["tif_entry"], output_dir))
        paths.append(extracted)
    return paths


def _build_zonal_rows(admins: Any, extracted_layers: dict[str, list[Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, feature in admins.iterrows():
        geometry = feature.geometry
        row = {
            "admin_unit_id": _admin_unit_id(feature, index),
            "county": str(feature.get("county") or ""),
            "township": str(feature.get("township") or ""),
            "feature_index": int(index) if isinstance(index, int) else str(index),
        }
        for layer, tif_paths in extracted_layers.items():
            stats = _sum_layer_for_geometry(geometry, tif_paths)
            prefix = "population" if layer == "population" else "built_surface"
            row[f"{prefix}_proxy_sum"] = round(stats["sum"], 6)
            row[f"{prefix}_valid_pixel_count"] = stats["valid_pixel_count"]
            row[f"{prefix}_intersecting_tile_count"] = stats["intersecting_tile_count"]
        rows.append(row)
    return rows


def _sum_layer_for_geometry(geometry: Any, tif_paths: list[Path]) -> dict[str, Any]:
    import rasterio
    from rasterio.features import geometry_mask
    from shapely.geometry import box, mapping

    total = 0.0
    valid_pixel_count = 0
    intersecting_tile_count = 0
    geom_bounds = geometry.bounds
    for tif_path in tif_paths:
        with rasterio.open(tif_path) as dataset:
            if not box(*dataset.bounds).intersects(box(*geom_bounds)):
                continue
            window = dataset.window(*geom_bounds)
            window = window.round_offsets().round_lengths()
            try:
                window = window.intersection(rasterio.windows.Window(0, 0, dataset.width, dataset.height))
            except rasterio.errors.WindowError:
                continue
            if window.width <= 0 or window.height <= 0:
                continue
            array = dataset.read(1, window=window, masked=True)
            if array.size == 0:
                continue
            transform = dataset.window_transform(window)
            inside = geometry_mask(
                [mapping(geometry)],
                out_shape=array.shape,
                transform=transform,
                invert=True,
                all_touched=False,
            )
            valid = inside & ~np.ma.getmaskarray(array)
            if dataset.nodata is not None:
                valid &= np.asarray(array.filled(dataset.nodata)) != dataset.nodata
            count = int(valid.sum())
            if count == 0:
                continue
            total += float(np.asarray(array.filled(0), dtype="float64")[valid].sum())
            valid_pixel_count += count
            intersecting_tile_count += 1
    return {
        "sum": total,
        "valid_pixel_count": valid_pixel_count,
        "intersecting_tile_count": intersecting_tile_count,
    }


def _admin_unit_id(feature: Any, index: Any) -> str:
    county = str(feature.get("county") or "unknown_county").strip() or "unknown_county"
    township = str(feature.get("township") or "unknown_township").strip() or "unknown_township"
    return f"{county}|{township}|{index}"


def _write_zonal_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "admin_unit_id",
        "county",
        "township",
        "feature_index",
        "population_proxy_sum",
        "population_valid_pixel_count",
        "population_intersecting_tile_count",
        "built_surface_proxy_sum",
        "built_surface_valid_pixel_count",
        "built_surface_intersecting_tile_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _limitations(crs_warning: str | None) -> list[str]:
    limitations = [
        "aggregation uses pixel-center inclusion, not fractional area weighting",
        "GHSL population and built-surface layers are public proxies, not local census or cadastral authority data",
        "administrative boundary license, vintage, topology, and modern district crosswalk still require verification",
        "this artifact supports MMFE/UWM state construction but is not an observed holdout validation dataset",
        "GHSL CC BY 4.0 attribution and derived-product change notices are required",
    ]
    if crs_warning:
        limitations.append(crs_warning)
    return limitations


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
