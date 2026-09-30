"""Compile target-clipped SmartMakani surface-support candidates.

The outputs remain diagnostic geometry candidates. Clipping and geometry repair
do not establish a vertical datum, an engineering DEM, or a SurfacePatch model.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .smartmakani_acquisition import (
    TARGET_BBOX_WGS84,
    TARGET_CRS,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .supporting_surfaces import SUPPORTING_LAYER_SPECS

SURFACE_CLIP_DATASET_SCHEMA = "gwm.abu_dhabi_flood.surface_clip_dataset.v1"
SURFACE_CLIP_BUNDLE_SCHEMA = "gwm.abu_dhabi_flood.surface_clip_bundle.v1"


@dataclass(frozen=True)
class SurfaceClipPolicy:
    """Deterministic geometry policy for diagnostic target-area clipping."""

    bbox_edge_segment_degrees: float = 0.001
    coverage_tolerance_m: float = 0.000001
    force_2d: bool = True
    repair_invalid_buildings: bool = True

    def __post_init__(self) -> None:
        if self.bbox_edge_segment_degrees <= 0:
            raise ValueError("bbox_edge_segment_degrees_must_be_positive")
        if self.coverage_tolerance_m <= 0 or self.coverage_tolerance_m > 0.001:
            raise ValueError("surface_clip_coverage_tolerance_out_of_range")
        if not self.force_2d:
            raise ValueError("surface_clip_requires_2d_output")
        if not self.repair_invalid_buildings:
            raise ValueError("surface_clip_requires_invalid_building_repair")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def _path_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def build_target_clip_geometry(
    *,
    bbox_wgs84: tuple[float, float, float, float] = TARGET_BBOX_WGS84,
    policy: SurfaceClipPolicy | None = None,
) -> Any:
    """Return a densified WGS84 rectangle transformed into the target CRS."""

    from pyproj import Transformer
    from shapely import segmentize
    from shapely.geometry import box
    from shapely.ops import transform

    active_policy = policy or SurfaceClipPolicy()
    geographic = segmentize(box(*bbox_wgs84), active_policy.bbox_edge_segment_degrees)
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    projected = transform(transformer.transform, geographic)
    if projected.is_empty or not projected.is_valid:
        raise ValueError("surface_clip_target_geometry_invalid")
    return projected


def _extract_expected_geometry(geometry: Any, dataset_key: str) -> Any | None:
    from shapely.geometry import MultiLineString, MultiPolygon

    expected = "polygon" if dataset_key == "building_survey" else "line"
    parts: list[Any] = []
    stack = [geometry]
    while stack:
        item = stack.pop()
        if item is None or item.is_empty:
            continue
        if expected == "line" and item.geom_type == "LineString":
            parts.append(item)
        elif expected == "polygon" and item.geom_type == "Polygon":
            parts.append(item)
        elif hasattr(item, "geoms"):
            stack.extend(reversed(item.geoms))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiPolygon(parts) if expected == "polygon" else MultiLineString(parts)


def _finite_measure(values: Any) -> float:
    total = 0.0
    for value in values:
        numeric = float(value)
        if math.isfinite(numeric):
            total += numeric
    return total


def clip_surface_frame(
    frame: Any,
    *,
    dataset_key: str,
    clip_geometry: Any,
    source_page_index: int = 0,
    coverage_tolerance_m: float = 0.000001,
) -> tuple[Any, dict[str, Any]]:
    """Repair and clip one source page while retaining source-row identity."""

    import geopandas as gpd
    import numpy as np
    import shapely

    if dataset_key not in SUPPORTING_LAYER_SPECS:
        raise ValueError(f"unsupported_surface_clip_dataset:{dataset_key}")
    if frame.crs is None:
        raise ValueError("surface_clip_source_crs_required")
    source = frame.to_crs(TARGET_CRS).copy().reset_index(drop=True)
    expected_fields = set(SUPPORTING_LAYER_SPECS[dataset_key].out_fields)
    missing_fields = sorted(expected_fields.difference(source.columns))
    if missing_fields:
        raise ValueError(
            f"surface_clip_missing_fields:{dataset_key}:{','.join(missing_fields)}"
        )

    geometries = shapely.force_2d(source.geometry.array)
    source.geometry = gpd.GeoSeries(geometries, index=source.index, crs=TARGET_CRS)
    present = source.geometry.notna() & ~source.geometry.is_empty
    invalid_before = present & ~source.geometry.is_valid
    repaired = np.zeros(len(source), dtype=bool)
    if invalid_before.any():
        if dataset_key != "building_survey":
            raise ValueError(f"surface_clip_invalid_nonbuilding_geometry:{dataset_key}")
        repaired[invalid_before.to_numpy()] = True
        fixed = shapely.make_valid(source.loc[invalid_before, "geometry"].array)
        source.loc[invalid_before, "geometry"] = fixed

    normalized_source = [
        _extract_expected_geometry(item, dataset_key) for item in source.geometry
    ]
    source.geometry = gpd.GeoSeries(
        normalized_source,
        index=source.index,
        crs=TARGET_CRS,
    )
    valid_for_clip = source.geometry.notna() & ~source.geometry.is_empty
    invalid_after_repair = valid_for_clip & ~source.geometry.is_valid
    if invalid_after_repair.any():
        raise ValueError(f"surface_clip_geometry_repair_failed:{dataset_key}")

    source_measure = (
        source.loc[valid_for_clip].geometry.area
        if dataset_key == "building_survey"
        else source.loc[valid_for_clip].geometry.length
    )
    clipped_raw = shapely.intersection(source.geometry.array, clip_geometry)
    clipped_geometry = [
        _extract_expected_geometry(item, dataset_key) for item in clipped_raw
    ]
    source.geometry = gpd.GeoSeries(
        clipped_geometry,
        index=source.index,
        crs=TARGET_CRS,
    )
    keep = source.geometry.notna() & ~source.geometry.is_empty
    output = source.loc[keep].copy().reset_index(drop=True)
    output["geometry_repaired"] = repaired[keep.to_numpy()]
    output["source_page_index"] = int(source_page_index)
    output_invalid = int((~output.geometry.is_valid).sum())
    if output_invalid:
        raise ValueError(f"surface_clip_invalid_output_geometry:{dataset_key}")
    output_outside_target = int(
        (
            ~shapely.covered_by(
                output.geometry.array,
                clip_geometry.buffer(coverage_tolerance_m),
            )
        ).sum()
    )
    if output_outside_target:
        raise ValueError(f"surface_clip_output_outside_target:{dataset_key}")
    output_has_z = int(shapely.has_z(output.geometry.array).sum())
    if output_has_z:
        raise ValueError(f"surface_clip_output_has_z:{dataset_key}")

    output_measure = (
        output.geometry.area
        if dataset_key == "building_survey"
        else output.geometry.length
    )
    geometry_types = Counter(str(value) for value in output.geometry.geom_type)
    return output, {
        "bbox_prefilter_record_count": len(frame),
        "output_record_count": len(output),
        "empty_after_exact_clip_count": int(len(frame) - len(output)),
        "invalid_before_repair_count": int(invalid_before.sum()),
        "geometry_repaired_count": int(repaired.sum()),
        "invalid_after_repair_count": int(invalid_after_repair.sum()),
        "output_invalid_geometry_count": output_invalid,
        "output_outside_target_count": output_outside_target,
        "output_has_z_count": output_has_z,
        "source_measure_after_repair": _finite_measure(source_measure),
        "output_clipped_measure": _finite_measure(output_measure),
        "output_geometry_type_counts": dict(sorted(geometry_types.items())),
    }


def _valid_completed_pages(
    manifest: dict[str, Any] | None,
    *,
    dataset_key: str,
    source_manifest_sha256: str,
    clip_geometry_sha256: str,
    policy: SurfaceClipPolicy,
    destination: Path,
    source_root: Path,
    source_pages: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    if not manifest:
        return {}
    if (
        manifest.get("schema") != SURFACE_CLIP_DATASET_SCHEMA
        or manifest.get("dataset_key") != dataset_key
        or manifest.get("source_manifest_sha256") != source_manifest_sha256
        or manifest.get("clip_geometry_sha256") != clip_geometry_sha256
        or manifest.get("policy") != asdict(policy)
    ):
        return {}
    valid: dict[int, dict[str, Any]] = {}
    for page in manifest.get("pages", []):
        page_index = page.get("page_index")
        source_page = source_pages.get(page_index)
        output_path = destination / page.get("path", "")
        source_path = (
            source_root / source_page.get("path", "")
            if source_page is not None
            else None
        )
        if (
            source_page is None
            or page.get("source_sha256") != source_page.get("sha256")
            or source_path is None
            or not source_path.is_file()
            or source_path.stat().st_size != source_page.get("size_bytes")
            or sha256_file(source_path) != source_page.get("sha256")
            or "output_outside_target_count" not in page
            or "output_has_z_count" not in page
            or not output_path.is_file()
            or output_path.stat().st_size != page.get("size_bytes")
            or sha256_file(output_path) != page.get("sha256")
        ):
            continue
        valid[int(page_index)] = page
    return valid


def _aggregate_pages(
    pages: list[dict[str, Any]],
    *,
    source_record_count: int,
) -> dict[str, Any]:
    geometry_types: Counter[str] = Counter()
    for page in pages:
        geometry_types.update(page["output_geometry_type_counts"])
    summary = {
        "source_record_count": source_record_count,
        "bbox_prefilter_record_count": sum(
            item["bbox_prefilter_record_count"] for item in pages
        ),
        "output_record_count": sum(item["output_record_count"] for item in pages),
        "outside_projected_bbox_prefilter_count": sum(
            item["source_record_count"] - item["bbox_prefilter_record_count"]
            for item in pages
        ),
        "empty_after_exact_clip_count": sum(
            item["empty_after_exact_clip_count"] for item in pages
        ),
        "invalid_before_repair_count": sum(
            item["invalid_before_repair_count"] for item in pages
        ),
        "geometry_repaired_count": sum(
            item["geometry_repaired_count"] for item in pages
        ),
        "invalid_after_repair_count": sum(
            item["invalid_after_repair_count"] for item in pages
        ),
        "output_invalid_geometry_count": sum(
            item["output_invalid_geometry_count"] for item in pages
        ),
        "output_outside_target_count": sum(
            item["output_outside_target_count"] for item in pages
        ),
        "output_has_z_count": sum(item["output_has_z_count"] for item in pages),
        "source_measure_after_repair": sum(
            item["source_measure_after_repair"] for item in pages
        ),
        "output_clipped_measure": sum(
            item["output_clipped_measure"] for item in pages
        ),
        "output_geometry_type_counts": dict(sorted(geometry_types.items())),
    }
    summary["dropped_after_selection_count"] = (
        source_record_count - summary["output_record_count"]
    )
    return summary


def compile_surface_clip_dataset(
    dataset_root: Path,
    dataset_key: str,
    *,
    output_root: Path | None = None,
    policy: SurfaceClipPolicy | None = None,
) -> dict[str, Any]:
    """Compile one frozen dataset into resumable target-clipped GeoParquet pages."""

    import geopandas as gpd
    import pyogrio
    import shapely

    try:
        spec = SUPPORTING_LAYER_SPECS[dataset_key]
    except KeyError as exc:
        raise ValueError(f"unsupported_surface_clip_dataset:{dataset_key}") from exc
    active_policy = policy or SurfaceClipPolicy()
    root = dataset_root.resolve()
    source_root = root / "online/smartmakani/features" / dataset_key
    source_manifest_path = source_root / "snapshot_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("status") != "complete":
        raise ValueError(f"surface_clip_source_incomplete:{dataset_key}")
    if source_manifest.get("target_crs") != TARGET_CRS:
        raise ValueError(f"surface_clip_source_crs_changed:{dataset_key}")
    if source_manifest.get("out_fields") != list(spec.out_fields):
        raise ValueError(f"surface_clip_source_fields_changed:{dataset_key}")

    destination_root = (
        output_root or root / "derived/smartmakani/surface_clip_candidate"
    ).resolve()
    destination = destination_root / dataset_key
    pages_root = destination / "pages"
    pages_root.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    source_manifest_hash = sha256_file(source_manifest_path)
    clip_geometry = build_target_clip_geometry(policy=active_policy)
    clip_geometry_hash = sha256_bytes(shapely.to_wkb(clip_geometry, hex=False))
    existing = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else None
    )
    source_pages = {
        int(item["page_index"]): item for item in source_manifest["pages"]
    }
    completed = _valid_completed_pages(
        existing,
        dataset_key=dataset_key,
        source_manifest_sha256=source_manifest_hash,
        clip_geometry_sha256=clip_geometry_hash,
        policy=active_policy,
        destination=destination,
        source_root=source_root,
        source_pages=source_pages,
    )

    base = {
        "schema": SURFACE_CLIP_DATASET_SCHEMA,
        "dataset_key": dataset_key,
        "role": spec.role,
        "status": "in_progress",
        "target_bbox_wgs84": list(TARGET_BBOX_WGS84),
        "target_crs": TARGET_CRS,
        "target_clip_bounds_epsg32640": list(clip_geometry.bounds),
        "target_clip_area_m2": float(clip_geometry.area),
        "clip_geometry_sha256": clip_geometry_hash,
        "source_manifest_path": _path_label(source_manifest_path, root),
        "source_manifest_sha256": source_manifest_hash,
        "source_snapshot_fingerprint": source_manifest["snapshot_fingerprint"],
        "source_record_count": source_manifest["completed_record_count"],
        "source_page_count": source_manifest["completed_page_count"],
        "policy": asdict(active_policy),
        "pages": list(completed.values()),
        "calibration_admission": "not_admitted_for_calibration",
    }
    _atomic_write_json(manifest_path, base)

    for page_index, source_page in sorted(source_pages.items()):
        if page_index in completed:
            continue
        source_path = source_root / source_page["path"]
        if source_path.stat().st_size != source_page["size_bytes"]:
            raise ValueError(f"surface_clip_source_page_size_mismatch:{source_path}")
        if sha256_file(source_path) != source_page["sha256"]:
            raise ValueError(f"surface_clip_source_page_hash_mismatch:{source_path}")
        frame = pyogrio.read_dataframe(
            source_path,
            columns=list(spec.out_fields),
            bbox=clip_geometry.bounds,
            use_arrow=True,
        )
        frame = gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs)
        clipped, metrics = clip_surface_frame(
            frame,
            dataset_key=dataset_key,
            clip_geometry=clip_geometry,
            source_page_index=page_index,
            coverage_tolerance_m=active_policy.coverage_tolerance_m,
        )
        output_path = pages_root / f"page_{page_index:06d}.parquet"
        temporary = output_path.with_name(f".{output_path.name}.tmp")
        if temporary.exists():
            temporary.unlink()
        clipped.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(output_path)
        output_page = {
            "page_index": page_index,
            "path": str(output_path.relative_to(destination)),
            "source_path": source_page["path"],
            "source_sha256": source_page["sha256"],
            "source_record_count": source_page["record_count"],
            "sha256": sha256_file(output_path),
            "size_bytes": output_path.stat().st_size,
            **metrics,
        }
        completed[page_index] = output_page
        base["pages"] = [completed[index] for index in sorted(completed)]
        _atomic_write_json(manifest_path, base)

    pages = [completed[index] for index in sorted(completed)]
    if len(pages) != source_manifest["completed_page_count"]:
        raise ValueError(f"surface_clip_page_count_mismatch:{dataset_key}")
    summary = _aggregate_pages(
        pages,
        source_record_count=source_manifest["completed_record_count"],
    )
    base.update(
        {
            "status": "complete",
            "completed_page_count": len(pages),
            "summary": summary,
            "content_fingerprint": sha256_bytes(
                canonical_json_bytes(
                    {
                        "dataset_key": dataset_key,
                        "clip_geometry_sha256": clip_geometry_hash,
                        "pages": [
                            {
                                "page_index": item["page_index"],
                                "sha256": item["sha256"],
                                "output_record_count": item["output_record_count"],
                            }
                            for item in pages
                        ],
                    }
                )
            ),
            "admission": {
                "engineering_dem_admitted": False,
                "surface_patch_contract_compiled": False,
                "k0_opened": False,
            },
            "claim_boundary": [
                "geometries_are_clipped_and_repaired_diagnostic_candidates_only",
                "vertical_datum_and_building_height_units_remain_unverified",
                "no_hydrologically_conditioned_surface_or_surface_patch_was_generated",
            ],
        }
    )
    _atomic_write_json(manifest_path, base)
    return base


def compile_surface_clip_bundle(
    dataset_root: Path,
    *,
    output_root: Path | None = None,
    dataset_keys: tuple[str, ...] = tuple(SUPPORTING_LAYER_SPECS),
    policy: SurfaceClipPolicy | None = None,
) -> dict[str, Any]:
    """Compile and bind all selected surface-support clip datasets."""

    active_policy = policy or SurfaceClipPolicy()
    root = dataset_root.resolve()
    destination = (
        output_root or root / "derived/smartmakani/surface_clip_candidate"
    ).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    datasets = []
    for key in dataset_keys:
        payload = compile_surface_clip_dataset(
            root,
            key,
            output_root=destination,
            policy=active_policy,
        )
        manifest_path = destination / key / "manifest.json"
        datasets.append(
            {
                "dataset_key": key,
                "manifest_path": _path_label(manifest_path, root),
                "manifest_sha256": sha256_file(manifest_path),
                "source_page_count": payload["source_page_count"],
                "source_record_count": payload["summary"]["source_record_count"],
                "output_record_count": payload["summary"]["output_record_count"],
                "dropped_after_selection_count": payload["summary"][
                    "dropped_after_selection_count"
                ],
                "geometry_repaired_count": payload["summary"][
                    "geometry_repaired_count"
                ],
                "output_invalid_geometry_count": payload["summary"][
                    "output_invalid_geometry_count"
                ],
                "output_outside_target_count": payload["summary"][
                    "output_outside_target_count"
                ],
                "output_has_z_count": payload["summary"]["output_has_z_count"],
                "content_fingerprint": payload["content_fingerprint"],
            }
        )
    by_key = {item["dataset_key"]: item for item in datasets}
    bundle = {
        "schema": SURFACE_CLIP_BUNDLE_SCHEMA,
        "target_bbox_wgs84": list(TARGET_BBOX_WGS84),
        "target_crs": TARGET_CRS,
        "policy": asdict(active_policy),
        "datasets": datasets,
        "summary": {
            "dataset_count": len(datasets),
            "source_page_count": sum(
                item["source_page_count"] for item in datasets
            ),
            "source_record_count": sum(
                item["source_record_count"] for item in datasets
            ),
            "output_record_count": sum(
                item["output_record_count"] for item in datasets
            ),
            "dropped_after_selection_count": sum(
                item["dropped_after_selection_count"] for item in datasets
            ),
            "building_geometry_repaired_count": by_key.get(
                "building_survey", {}
            ).get("geometry_repaired_count", 0),
            "output_invalid_geometry_count": sum(
                item["output_invalid_geometry_count"] for item in datasets
            ),
            "output_outside_target_count": sum(
                item["output_outside_target_count"] for item in datasets
            ),
            "output_has_z_count": sum(
                item["output_has_z_count"] for item in datasets
            ),
            "all_returned_geometries_clipped_to_target": True,
            "vertical_datum_verified": False,
            "hydrologically_conditioned_surface_compiled": False,
            "surface_patch_contract_compiled": False,
        },
        "admission": {
            "target_clipped_static_candidate_available": True,
            "engineering_dem_admitted": False,
            "building_obstruction_layer_admitted": False,
            "surface_patch_contract_compiled": False,
            "k0_opened": False,
        },
        "claim_boundary": [
            "the_target_clip_and_two_dimensional_geometry_repair_are_reproducible",
            "the_outputs_are_not_an_engineering_dem_or_hydraulic_surface",
            "bathymetry_does_not_supply_event_tide_or_surge",
            "no_city_scale_flood_prediction_claim_is_allowed",
        ],
    }
    manifest_path = destination / "surface_clip_candidate_manifest.json"
    _atomic_write_json(manifest_path, bundle)
    return {
        **bundle,
        "output": {
            "path": _path_label(manifest_path, root),
            "sha256": sha256_file(manifest_path),
            "size_bytes": manifest_path.stat().st_size,
        },
    }
