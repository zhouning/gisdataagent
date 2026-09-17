#!/usr/bin/env python3
"""Extract a cloud-screened Sentinel-2 flood observation for external validation.

The output represents spectrally observed *new surface water* after a rainfall
event. It is intentionally kept outside the physical-label and GWM-training
paths. The product is suitable only for comparison over pixels with valid
before/after observations and must not be represented as observed water depth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

DEFAULT_GRID = Path(
    "/Users/zhouning/Downloads/阿布扎比/"
    "全市双向耦合试点_客户DTM_250m_20260910_v2高程门控/terrain_grid.npz"
)
DEFAULT_EVENT_FORCING = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_city_swmm_2d_coupled_labels_20260914_r1/events/"
    "noaa-isd-ae-202404151200-0327/forcing.json"
)
DEFAULT_OUTPUT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_sentinel2_observed_flood_202404_r1"
)
DEFAULT_STAC = "https://earth-search.aws.element84.com/v1/search"
SCHEMA = "gwm.abu_dhabi_flood.sentinel2_observed_flood.v1"
VALID_SCL_CLASSES = frozenset({4, 5, 6, 7})
NODATA_MASK = 255
OBSERVATION_PURPOSES = frozenset({"external_evaluation", "observation_operator_development"})


@dataclass(frozen=True)
class Grid:
    crs: str
    transform_10m: Affine
    width_10m: int
    height_10m: int
    x: np.ndarray
    y: np.ndarray
    cell_size_m: float

    @property
    def shape_250m(self) -> tuple[int, int]:
        return len(self.y) - 1, len(self.x) - 1


@dataclass(frozen=True)
class Scene:
    item_id: str
    datetime_utc: str
    cloud_cover_percent: float | None
    grid_code: str
    processing_baseline: str
    updated_utc: str
    assets: dict[str, str]
    reflectance_transforms: dict[str, tuple[float, float]]
    item: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("sentinel_observation_datetime_timezone_missing")
    return parsed.astimezone(UTC)


def _load_grid(path: Path) -> Grid:
    with np.load(path) as archive:
        x = np.asarray(archive["x"], dtype=np.float64)
        y = np.asarray(archive["y"], dtype=np.float64)
        values = np.asarray(archive["values"], dtype=np.float64)
    if x.ndim != 1 or y.ndim != 1 or values.shape != (len(y), len(x)):
        raise ValueError("sentinel_observation_model_grid_shape_invalid")
    if len(x) < 2 or len(y) < 2:
        raise ValueError("sentinel_observation_model_grid_empty")
    cell_size = float(x[1] - x[0])
    if (
        not math.isfinite(cell_size)
        or cell_size <= 0
        or not np.allclose(np.diff(x), cell_size)
        or not np.allclose(np.diff(y), -cell_size)
        or cell_size % 10 != 0
    ):
        raise ValueError("sentinel_observation_model_grid_spacing_invalid")
    width_10m = int(round((x[-1] - x[0]) / 10.0))
    height_10m = int(round((y[0] - y[-1]) / 10.0))
    if width_10m <= 0 or height_10m <= 0 or width_10m % 25 or height_10m % 25:
        raise ValueError("sentinel_observation_10m_grid_alignment_invalid")
    return Grid(
        crs="EPSG:32640",
        transform_10m=Affine(10.0, 0.0, float(x[0]), 0.0, -10.0, float(y[0])),
        width_10m=width_10m,
        height_10m=height_10m,
        x=x,
        y=y,
        cell_size_m=cell_size,
    )


def _wgs84_bbox(grid: Grid) -> list[float]:
    from pyproj import Transformer

    transformer = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    east = grid.transform_10m.c + grid.width_10m * grid.transform_10m.a
    south = grid.transform_10m.f + grid.height_10m * grid.transform_10m.e
    corners = [
        transformer.transform(grid.transform_10m.c, grid.transform_10m.f),
        transformer.transform(east, grid.transform_10m.f),
        transformer.transform(grid.transform_10m.c, south),
        transformer.transform(east, south),
    ]
    return [
        min(point[0] for point in corners),
        min(point[1] for point in corners),
        max(point[0] for point in corners),
        max(point[1] for point in corners),
    ]


def _stac_search(endpoint: str, bbox: list[float], start: str, end: str) -> dict[str, Any]:
    payload = json.dumps(
        {
            "collections": ["sentinel-2-l2a"],
            "bbox": bbox,
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "limit": 100,
        }
    ).encode("utf-8")
    request = Request(
        endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urlopen(request, timeout=90) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("sentinel_observation_stac_search_failed") from exc
    if not isinstance(value, dict) or not isinstance(value.get("features"), list):
        raise ValueError("sentinel_observation_stac_response_invalid")
    return value


def _bbox_intersects(left: list[float], right: list[float]) -> bool:
    return left[0] < right[2] and left[2] > right[0] and left[1] < right[3] and left[3] > right[1]


def _reflectance_transform(asset: dict[str, Any]) -> tuple[float, float]:
    bands = asset.get("raster:bands")
    if not isinstance(bands, list) or len(bands) != 1 or not isinstance(bands[0], dict):
        raise ValueError("sentinel_observation_reflectance_metadata_missing")
    scale = float(bands[0].get("scale"))
    offset = float(bands[0].get("offset"))
    if not math.isfinite(scale) or scale <= 0.0 or not math.isfinite(offset):
        raise ValueError("sentinel_observation_reflectance_metadata_invalid")
    return scale, offset


def _processing_baseline_key(value: str) -> tuple[int, ...]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise ValueError("sentinel_observation_processing_baseline_invalid") from exc
    if not parts:
        raise ValueError("sentinel_observation_processing_baseline_invalid")
    return parts


def _select_latest_processing_baseline(scenes: list[Scene]) -> list[Scene]:
    selected: dict[str, Scene] = {}
    for scene in scenes:
        current = selected.get(scene.grid_code)
        priority = (
            _processing_baseline_key(scene.processing_baseline),
            scene.updated_utc,
            scene.item_id,
        )
        if current is None or priority > (
            _processing_baseline_key(current.processing_baseline),
            current.updated_utc,
            current.item_id,
        ):
            selected[scene.grid_code] = scene
    return sorted(selected.values(), key=lambda scene: (scene.grid_code, scene.item_id))


def _scene_indices(
    green_dn: np.ndarray,
    nir_dn: np.ndarray,
    swir_dn: np.ndarray,
    scl: np.ndarray,
    scene: Scene,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    green_scale, green_offset = scene.reflectance_transforms["green"]
    nir_scale, nir_offset = scene.reflectance_transforms["nir"]
    swir_scale, swir_offset = scene.reflectance_transforms["swir16"]
    green_dn = np.asarray(green_dn)
    nir_dn = np.asarray(nir_dn)
    swir_dn = np.asarray(swir_dn)
    green = green_dn.astype(np.float32) * green_scale + green_offset
    nir = nir_dn.astype(np.float32) * nir_scale + nir_offset
    swir = swir_dn.astype(np.float32) * swir_scale + swir_offset
    source_valid = (
        (green_dn != 0) & (nir_dn != 0) & (swir_dn != 0) & np.isin(scl, tuple(VALID_SCL_CLASSES))
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        mndwi = (green - swir) / (green + swir)
        ndwi = (green - nir) / (green + nir)
    valid = source_valid & np.isfinite(mndwi) & np.isfinite(ndwi)
    return mndwi, ndwi, valid


def _scenes_for_date(
    catalog: dict[str, Any], date: str, bbox: list[float], *, epsg: int
) -> list[Scene]:
    required_assets = {"green", "nir", "swir16", "scl"}
    selected: list[Scene] = []
    for item in catalog["features"]:
        if not isinstance(item, dict):
            continue
        properties = item.get("properties")
        assets = item.get("assets")
        item_bbox = item.get("bbox")
        if (
            not isinstance(properties, dict)
            or not isinstance(assets, dict)
            or not isinstance(item_bbox, list)
        ):
            continue
        if not str(properties.get("datetime", "")).startswith(date):
            continue
        if int(properties.get("proj:epsg", -1)) != epsg or not _bbox_intersects(item_bbox, bbox):
            continue
        if not required_assets.issubset(assets):
            continue
        hrefs = {
            key: str(assets[key].get("href", ""))
            for key in required_assets
            if isinstance(assets[key], dict)
        }
        if set(hrefs) != required_assets or not all(hrefs.values()):
            continue
        transforms = {
            key: _reflectance_transform(assets[key]) for key in ("green", "nir", "swir16")
        }
        cloud = properties.get("eo:cloud_cover")
        selected.append(
            Scene(
                item_id=str(item.get("id", "")),
                datetime_utc=str(properties["datetime"]),
                cloud_cover_percent=None if cloud is None else float(cloud),
                grid_code=str(properties.get("grid:code", "")),
                processing_baseline=str(properties.get("s2:processing_baseline", "")),
                updated_utc=str(properties.get("updated", properties.get("created", ""))),
                assets=hrefs,
                reflectance_transforms=transforms,
                item=item,
            )
        )
    if not selected:
        raise ValueError(f"sentinel_observation_scene_unavailable:{date}")
    return _select_latest_processing_baseline(selected)


class _MosaicReader:
    def __init__(self, scenes: list[Scene], grid: Grid):
        self._stack = ExitStack()
        self._sources: list[tuple[Scene, dict[str, WarpedVRT]]] = []
        for scene in scenes:
            source: dict[str, WarpedVRT] = {}
            for key, href in scene.assets.items():
                dataset = self._stack.enter_context(rasterio.open(href))
                source[key] = self._stack.enter_context(
                    WarpedVRT(
                        dataset,
                        crs=grid.crs,
                        transform=grid.transform_10m,
                        width=grid.width_10m,
                        height=grid.height_10m,
                        resampling=Resampling.nearest if key == "scl" else Resampling.bilinear,
                        src_nodata=0,
                        nodata=0,
                    )
                )
            self._sources.append((scene, source))

    def close(self) -> None:
        self._stack.close()

    def __enter__(self) -> _MosaicReader:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def read_indices(self, window: Window) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        shape = int(window.height), int(window.width)
        mndwi = np.full(shape, np.nan, dtype=np.float32)
        ndwi = np.full(shape, np.nan, dtype=np.float32)
        valid = np.zeros(shape, dtype=bool)
        for scene, source in self._sources:
            green = source["green"].read(1, window=window)
            nir = source["nir"].read(1, window=window)
            swir = source["swir16"].read(1, window=window)
            scl = source["scl"].read(1, window=window)
            candidate_mndwi, candidate_ndwi, source_valid = _scene_indices(
                green, nir, swir, scl, scene
            )
            usable = (~valid) & source_valid
            if not np.any(usable):
                continue
            mndwi[usable] = candidate_mndwi[usable]
            ndwi[usable] = candidate_ndwi[usable]
            valid[usable] = True
        return mndwi, ndwi, valid


def _classify_new_surface_water(
    before_mndwi: np.ndarray,
    before_ndwi: np.ndarray,
    before_valid: np.ndarray,
    after_mndwi: np.ndarray,
    after_ndwi: np.ndarray,
    after_valid: np.ndarray,
    *,
    water_threshold: float,
    change_threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return observed-new-water, valid-pair mask, and MNDWI change."""

    if not (0.0 <= water_threshold < 1.0 and 0.0 <= change_threshold < 1.0):
        raise ValueError("sentinel_observation_threshold_invalid")
    paired_valid = np.asarray(before_valid, dtype=bool) & np.asarray(after_valid, dtype=bool)
    change = np.asarray(after_mndwi, dtype=np.float32) - np.asarray(before_mndwi, dtype=np.float32)
    before_water = (before_mndwi > water_threshold) & (before_ndwi > water_threshold)
    after_water = (after_mndwi > water_threshold) & (after_ndwi > water_threshold)
    observed = paired_valid & after_water & ~before_water & (change >= change_threshold)
    return observed, paired_valid, change


def _aggregate_to_model_grid(
    observed: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if (
        observed.shape != valid.shape
        or observed.ndim != 2
        or observed.shape[0] % 25
        or observed.shape[1] % 25
    ):
        raise ValueError("sentinel_observation_aggregation_shape_invalid")
    rows, columns = observed.shape[0] // 25, observed.shape[1] // 25
    valid_blocks = valid.reshape(rows, 25, columns, 25)
    observed_blocks = observed.reshape(rows, 25, columns, 25)
    valid_count = valid_blocks.sum(axis=(1, 3), dtype=np.int32)
    observed_count = observed_blocks.sum(axis=(1, 3), dtype=np.int32)
    valid_fraction = valid_count.astype(np.float32) / 625.0
    observed_fraction_of_all = observed_count.astype(np.float32) / 625.0
    observed_fraction_of_valid = np.divide(
        observed_count,
        valid_count,
        out=np.zeros((rows, columns), dtype=np.float32),
        where=valid_count > 0,
    )
    return valid_fraction, observed_fraction_of_all, observed_fraction_of_valid


def _raster_profile(grid: Grid, *, dtype: str, nodata: float | int) -> dict[str, Any]:
    return {
        "driver": "GTiff",
        "width": grid.width_10m,
        "height": grid.height_10m,
        "count": 1,
        "dtype": dtype,
        "crs": grid.crs,
        "transform": grid.transform_10m,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": "deflate",
        "predictor": 2 if dtype.startswith("float") else 1,
    }


def _purpose_contract(purpose: str) -> dict[str, Any]:
    if purpose not in OBSERVATION_PURPOSES:
        raise ValueError("sentinel_observation_purpose_invalid")
    if purpose == "external_evaluation":
        return {
            "external_holdout": True,
            "gwm_dynamics_training_forbidden": True,
            "observation_operator_training_allowed": False,
            "forcing_purpose": "external satellite-overpass evaluation only; forbidden from GWM training",
            "tail_filename": "satellite_overpass_external_evaluation_forcing.json",
            "use_claim": (
                "The event and all derived observations are forbidden from GWM training "
                "and validation selection."
            ),
        }
    return {
        "external_holdout": False,
        "gwm_dynamics_training_forbidden": True,
        "observation_operator_training_allowed": True,
        "forcing_purpose": (
            "post-hoc satellite observation-operator development only; forbidden from "
            "GWM dynamics training and confirmatory claims"
        ),
        "tail_filename": "satellite_overpass_observation_operator_forcing.json",
        "use_claim": (
            "This event is already exposed and may train or select only the satellite "
            "observation operator; it is forbidden from GWM dynamics training and new "
            "confirmatory claims."
        ),
    }


def _tail_forcing(
    event_forcing: Path,
    observation_time: datetime,
    output: Path,
    *,
    purpose: str = "external_evaluation",
) -> dict[str, Any]:
    forcing = json.loads(event_forcing.read_text(encoding="utf-8"))
    start = _parse_datetime(str(forcing["start_utc"]))
    hourly = [float(value) for value in forcing["hourly_precipitation_mm"]]
    if not hourly or any(not math.isfinite(value) or value < 0.0 for value in hourly):
        raise ValueError("sentinel_observation_event_forcing_invalid")
    offset_seconds = (observation_time - start).total_seconds()
    if offset_seconds <= 0:
        raise ValueError("sentinel_observation_precedes_event")
    target_hours = max(len(hourly), math.ceil(offset_seconds / 3600.0))
    tail_hours = target_hours - len(hourly)
    extended = dict(forcing)
    extended["hourly_precipitation_mm"] = hourly + [0.0] * tail_hours
    extended["purpose"] = _purpose_contract(purpose)["forcing_purpose"]
    extended["satellite_observation_utc"] = observation_time.isoformat().replace("+00:00", "Z")
    extended["satellite_observation_time_seconds_from_event_start"] = offset_seconds
    extended["nearest_300_second_model_frame_seconds"] = round(offset_seconds / 300.0) * 300
    extended["zero_rainfall_tail_hours"] = tail_hours
    _write_json(output, extended)
    return extended


def _binary_metrics(
    truth: np.ndarray, predicted: np.ndarray, eligible: np.ndarray
) -> dict[str, float | int | None]:
    truth_values = np.asarray(truth, dtype=bool)[eligible]
    predicted_values = np.asarray(predicted, dtype=bool)[eligible]
    if not len(truth_values):
        return {"eligible_cell_count": 0, "iou": None, "precision": None, "recall": None}
    tp = int(np.sum(truth_values & predicted_values))
    fp = int(np.sum(~truth_values & predicted_values))
    fn = int(np.sum(truth_values & ~predicted_values))
    union = tp + fp + fn
    return {
        "eligible_cell_count": int(len(truth_values)),
        "true_positive_cells": tp,
        "false_positive_cells": fp,
        "false_negative_cells": fn,
        "iou": float(tp / union) if union else 1.0,
        "precision": float(tp / (tp + fp)) if tp + fp else 0.0,
        "recall": float(tp / (tp + fn)) if tp + fn else 0.0,
    }


def _compare_model(
    model_labels: Path,
    observation: dict[str, np.ndarray],
    *,
    observation_seconds: float,
    minimum_valid_fraction: float,
    minimum_observed_fraction: float,
    depth_threshold_m: float,
) -> dict[str, Any]:
    with np.load(model_labels) as archive:
        depth = np.asarray(archive["depth_m"], dtype=np.float32)
        times = np.asarray(archive["time_seconds"], dtype=np.float64)
        land = np.asarray(archive["land_mask"], dtype=bool)
    if depth.ndim != 2 or depth.shape[1] != land.size:
        raise ValueError("sentinel_observation_model_label_shape_invalid")
    target_index = int(np.argmin(np.abs(times - observation_seconds)))
    chosen_seconds = float(times[target_index])
    if abs(chosen_seconds - observation_seconds) > 150.0:
        raise ValueError("sentinel_observation_model_label_does_not_cover_overpass")
    predicted = depth[target_index].reshape(land.shape) >= depth_threshold_m
    observed = observation["observed_fraction_of_valid"] >= minimum_observed_fraction
    eligible = (observation["valid_fraction"] >= minimum_valid_fraction) & land
    return {
        "model_depth_labels": str(model_labels),
        "model_frame_seconds": chosen_seconds,
        "satellite_observation_seconds": observation_seconds,
        "depth_threshold_m": depth_threshold_m,
        "observed_fraction_threshold": minimum_observed_fraction,
        "minimum_valid_fraction": minimum_valid_fraction,
        "metrics": _binary_metrics(observed, predicted, eligible),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    grid_path = args.grid.expanduser().resolve()
    output = args.output.expanduser().resolve()
    grid = _load_grid(grid_path)
    bbox = _wgs84_bbox(grid)
    before_date = args.before_date
    after_date = args.after_date
    if _parse_datetime(f"{before_date}T00:00:00Z") >= _parse_datetime(f"{after_date}T00:00:00Z"):
        raise ValueError("sentinel_observation_date_order_invalid")
    catalog = _stac_search(args.stac_endpoint, bbox, before_date, after_date)
    before_scenes = _scenes_for_date(catalog, before_date, bbox, epsg=32640)
    after_scenes = _scenes_for_date(catalog, after_date, bbox, epsg=32640)
    output.mkdir(parents=True, exist_ok=True)
    raw_catalog_path = output / "stac_search_response.json"
    _write_json(raw_catalog_path, catalog)
    observation_time = min(_parse_datetime(scene.datetime_utc) for scene in after_scenes)
    forcing_path = args.event_forcing.expanduser().resolve()
    purpose = _purpose_contract(args.observation_purpose)
    tail_path = output / str(purpose["tail_filename"])
    tail = _tail_forcing(
        forcing_path,
        observation_time,
        tail_path,
        purpose=args.observation_purpose,
    )

    observed_path = output / "observed_new_surface_water_10m.tif"
    paired_valid_path = output / "paired_valid_observation_10m.tif"
    change_path = output / "mndwi_change_10m.tif"
    valid_fraction = np.zeros(grid.shape_250m, dtype=np.float32)
    observed_fraction_all = np.zeros(grid.shape_250m, dtype=np.float32)
    observed_fraction_valid = np.zeros(grid.shape_250m, dtype=np.float32)
    chunk_rows = args.chunk_rows
    if chunk_rows <= 0 or chunk_rows % 25:
        raise ValueError("sentinel_observation_chunk_rows_must_be_multiple_of_25")

    with rasterio.Env(
        AWS_NO_SIGN_REQUEST="YES",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_MAX_RETRY="3",
        GDAL_HTTP_RETRY_DELAY="2",
    ):
        with (
            _MosaicReader(before_scenes, grid) as before_reader,
            _MosaicReader(after_scenes, grid) as after_reader,
            rasterio.open(
                observed_path, "w", **_raster_profile(grid, dtype="uint8", nodata=NODATA_MASK)
            ) as observed_dst,
            rasterio.open(
                paired_valid_path, "w", **_raster_profile(grid, dtype="uint8", nodata=NODATA_MASK)
            ) as valid_dst,
            rasterio.open(
                change_path, "w", **_raster_profile(grid, dtype="float32", nodata=-9999.0)
            ) as change_dst,
        ):
            for row_start in range(0, grid.height_10m, chunk_rows):
                height = min(chunk_rows, grid.height_10m - row_start)
                window = Window(0, row_start, grid.width_10m, height)
                before_mndwi, before_ndwi, before_valid = before_reader.read_indices(window)
                after_mndwi, after_ndwi, after_valid = after_reader.read_indices(window)
                observed, paired_valid, change = _classify_new_surface_water(
                    before_mndwi,
                    before_ndwi,
                    before_valid,
                    after_mndwi,
                    after_ndwi,
                    after_valid,
                    water_threshold=args.water_threshold,
                    change_threshold=args.change_threshold,
                )
                observed_raster = np.where(
                    paired_valid, observed.astype(np.uint8), NODATA_MASK
                ).astype(np.uint8)
                valid_raster = np.where(paired_valid, 1, NODATA_MASK).astype(np.uint8)
                change_raster = np.where(paired_valid, change, -9999.0).astype(np.float32)
                observed_dst.write(observed_raster, 1, window=window)
                valid_dst.write(valid_raster, 1, window=window)
                change_dst.write(change_raster, 1, window=window)
                slice_rows = slice(row_start // 25, (row_start + height) // 25)
                valid_part, observed_all_part, observed_valid_part = _aggregate_to_model_grid(
                    observed, paired_valid
                )
                valid_fraction[slice_rows, :] = valid_part
                observed_fraction_all[slice_rows, :] = observed_all_part
                observed_fraction_valid[slice_rows, :] = observed_valid_part

    observed_label = (valid_fraction >= args.minimum_valid_fraction) & (
        observed_fraction_valid >= args.minimum_observed_fraction
    )
    archive_path = output / "observed_flood_250m.npz"
    np.savez_compressed(
        archive_path,
        valid_fraction=valid_fraction,
        observed_new_surface_water_fraction_of_all_pixels=observed_fraction_all,
        observed_new_surface_water_fraction_of_valid_pixels=observed_fraction_valid,
        observed_flood_label=observed_label,
        x=grid.x,
        y=grid.y,
        observation_time_seconds_from_event_start=float(
            tail["satellite_observation_time_seconds_from_event_start"]
        ),
    )
    observation = {
        "valid_fraction": valid_fraction,
        "observed_fraction_of_all": observed_fraction_all,
        "observed_fraction_of_valid": observed_fraction_valid,
    }
    comparison = None
    if args.model_depth_labels is not None:
        comparison = _compare_model(
            args.model_depth_labels.expanduser().resolve(),
            observation,
            observation_seconds=float(tail["satellite_observation_time_seconds_from_event_start"]),
            minimum_valid_fraction=args.minimum_valid_fraction,
            minimum_observed_fraction=args.minimum_observed_fraction,
            depth_threshold_m=args.model_depth_threshold_m,
        )
        _write_json(output / "external_model_comparison.json", comparison)
    effective_valid_area_m2 = float(valid_fraction.sum() * grid.cell_size_m**2)
    observed_area_m2 = float((observed_fraction_all * grid.cell_size_m**2).sum())
    receipt = {
        "schema": SCHEMA,
        "status": "completed",
        "quality_passed": bool(np.any(valid_fraction >= args.minimum_valid_fraction)),
        "event": {
            "event_id": str(tail["event_id"]),
            "observation_purpose": args.observation_purpose,
            "external_holdout": purpose["external_holdout"],
            "training_forbidden": purpose["gwm_dynamics_training_forbidden"],
            "gwm_dynamics_training_forbidden": purpose["gwm_dynamics_training_forbidden"],
            "observation_operator_training_allowed": purpose[
                "observation_operator_training_allowed"
            ],
            "satellite_observation_utc": tail["satellite_observation_utc"],
            "observation_time_seconds_from_event_start": tail[
                "satellite_observation_time_seconds_from_event_start"
            ],
        },
        "method": {
            "source": "AWS Earth Search Sentinel-2 L2A COG/STAC",
            "before_date": before_date,
            "after_date": after_date,
            "bands": ["B03 green", "B08 NIR", "B11 SWIR1", "SCL"],
            "reflectance_conversion": {
                "formula": "reflectance = quantized_DN * asset raster:bands scale + offset",
                "metadata_source": "per-scene Earth Search STAC asset raster:bands",
            },
            "valid_scl_classes": sorted(VALID_SCL_CLASSES),
            "water_condition": (
                "MNDWI and NDWI above threshold in after image, absent in before image"
            ),
            "water_threshold": args.water_threshold,
            "mndwi_change_threshold": args.change_threshold,
            "minimum_250m_valid_fraction": args.minimum_valid_fraction,
            "minimum_250m_observed_water_fraction": args.minimum_observed_fraction,
        },
        "scenes": {
            "before": [
                {
                    "item_id": scene.item_id,
                    "datetime_utc": scene.datetime_utc,
                    "cloud_cover_percent": scene.cloud_cover_percent,
                    "grid_code": scene.grid_code,
                    "processing_baseline": scene.processing_baseline,
                    "updated_utc": scene.updated_utc,
                    "reflectance_transforms": scene.reflectance_transforms,
                }
                for scene in before_scenes
            ],
            "after": [
                {
                    "item_id": scene.item_id,
                    "datetime_utc": scene.datetime_utc,
                    "cloud_cover_percent": scene.cloud_cover_percent,
                    "grid_code": scene.grid_code,
                    "processing_baseline": scene.processing_baseline,
                    "updated_utc": scene.updated_utc,
                    "reflectance_transforms": scene.reflectance_transforms,
                }
                for scene in after_scenes
            ],
            "stac_response": raw_catalog_path.name,
        },
        "outputs": {
            "observed_new_surface_water_10m": observed_path.name,
            "paired_valid_observation_10m": paired_valid_path.name,
            "mndwi_change_10m": change_path.name,
            "observed_flood_250m": archive_path.name,
            "valid_observation_area_m2": effective_valid_area_m2,
            "observed_new_surface_water_area_m2": observed_area_m2,
            "valid_250m_cell_count": int(np.sum(valid_fraction >= args.minimum_valid_fraction)),
            "observed_flood_250m_cell_count": int(observed_label.sum()),
        },
        "external_evaluation": {
            "forcing_with_zero_rain_tail": tail_path.name,
            "comparison": comparison,
        },
        "claim_boundary": [
            (
                "Spectral new-surface-water observation, not observed water depth or a "
                "surveyed flood extent."
            ),
            (
                "Cloud, cloud-shadow, cirrus, snow and no-data Sentinel-2 classes are "
                "excluded; only paired valid pixels may be evaluated."
            ),
            purpose["use_claim"],
            (
                "A physics replay must include the generated zero-rainfall tail to the "
                "satellite overpass before any model comparison."
            ),
        ],
        "implementation": {
            "script_sha256": _sha256(Path(__file__)),
            "model_grid_path": str(grid_path),
            "model_grid_sha256": _sha256(grid_path),
            "event_forcing_path": str(forcing_path),
            "event_forcing_sha256": _sha256(forcing_path),
        },
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
    ).hexdigest()
    _write_json(output / "run_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    parser.add_argument("--event-forcing", type=Path, default=DEFAULT_EVENT_FORCING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stac-endpoint", default=DEFAULT_STAC)
    parser.add_argument("--before-date", default="2024-04-05")
    parser.add_argument("--after-date", default="2024-04-17")
    parser.add_argument("--water-threshold", type=float, default=0.0)
    parser.add_argument("--change-threshold", type=float, default=0.05)
    parser.add_argument("--minimum-valid-fraction", type=float, default=0.70)
    parser.add_argument("--minimum-observed-fraction", type=float, default=0.02)
    parser.add_argument("--model-depth-labels", type=Path)
    parser.add_argument("--model-depth-threshold-m", type=float, default=0.01)
    parser.add_argument("--chunk-rows", type=int, default=250)
    parser.add_argument(
        "--observation-purpose",
        choices=sorted(OBSERVATION_PURPOSES),
        default="external_evaluation",
    )
    args = parser.parse_args()
    if (
        not 0.0 < args.minimum_valid_fraction <= 1.0
        or not 0.0 < args.minimum_observed_fraction <= 1.0
    ):
        raise ValueError("sentinel_observation_fraction_threshold_invalid")
    result = run(args)
    print(
        json.dumps(
            {
                "status": result["status"],
                "event_id": result["event"]["event_id"],
                "observed_new_surface_water_area_m2": result["outputs"][
                    "observed_new_surface_water_area_m2"
                ],
                "valid_250m_cell_count": result["outputs"]["valid_250m_cell_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
