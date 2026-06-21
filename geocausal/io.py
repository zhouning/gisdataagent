from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .config import GeoCausalConfig
from .errors import GeoCausalInputError


@dataclass(frozen=True)
class LoadedDataset:
    frame: Any
    path: Path
    format: str
    geometry_available: bool
    columns: set[str]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    preprocessing: dict[str, Any] = field(default_factory=dict)


def load_dataset(config: GeoCausalConfig) -> LoadedDataset:
    path = config.resolve_input_path()
    if not path.exists():
        raise GeoCausalInputError(f"Input file does not exist: {path}")

    if config.input.format == "csv":
        frame = _read_csv(path, config.variables.unit_id)
    elif config.input.format in {"gpkg", "geojson", "shp"}:
        frame = _read_spatial(path)
    else:
        raise GeoCausalInputError(f"Unsupported input format: {config.input.format}")

    frame = _ensure_unit_id(frame, config.variables.unit_id)
    frame, preprocessing = _apply_preprocessing(frame, config)
    geometry_available = _has_geometry(frame) if config.input.format != "csv" else False
    warnings = _geometry_warnings(frame, geometry_available)
    return LoadedDataset(
        frame=frame,
        path=path,
        format=config.input.format,
        geometry_available=geometry_available,
        columns=set(str(column) for column in frame.columns),
        warnings=warnings,
        preprocessing=preprocessing,
    )


def _read_csv(path: Path, unit_id: str | None = None) -> pd.DataFrame:
    try:
        dtype = {unit_id: "string"} if unit_id else None
        return pd.read_csv(path, encoding="utf-8-sig", dtype=dtype)
    except Exception as exc:
        raise GeoCausalInputError(f"Cannot read CSV input: {path}") from exc


def _read_spatial(path: Path) -> Any:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise GeoCausalInputError(
            "GeoPandas is required to read gpkg, geojson, or shp inputs."
        ) from exc

    try:
        return gpd.read_file(path)
    except Exception as exc:
        raise GeoCausalInputError(f"Cannot read spatial input: {path}") from exc


def _ensure_unit_id(frame: Any, unit_id: str) -> Any:
    if unit_id in frame.columns:
        frame = frame.copy()
        frame[unit_id] = frame[unit_id].astype(str)
        return frame
    if unit_id == "_gc_unit_id":
        frame = frame.copy()
        frame.insert(0, unit_id, [str(index) for index in range(1, len(frame) + 1)])
        return frame
    raise GeoCausalInputError(f"Configured unit_id column is missing: {unit_id}")


def _apply_preprocessing(frame: Any, config: GeoCausalConfig) -> tuple[Any, dict[str, Any]]:
    trim = config.preprocessing.exposure_trim
    if trim is None:
        return frame, {}
    exposure_column = config.variables.exposure
    if exposure_column not in frame.columns:
        return frame, {
            "exposure_trim": {
                "status": "skipped",
                "reason": f"Exposure column is missing: {exposure_column}",
            }
        }

    exposure = pd.to_numeric(frame[exposure_column], errors="coerce")
    lower_value = float(exposure.quantile(trim.lower_quantile))
    upper_value = float(exposure.quantile(trim.upper_quantile))
    keep = exposure.ge(lower_value) & exposure.le(upper_value)
    original_n = int(len(frame))
    trimmed = frame.loc[keep].copy()
    summary = {
        "exposure_trim": {
            "status": "applied",
            "column": exposure_column,
            "lower_quantile": trim.lower_quantile,
            "upper_quantile": trim.upper_quantile,
            "lower_value": lower_value,
            "upper_value": upper_value,
            "original_n": original_n,
            "kept_n": int(len(trimmed)),
            "removed_n": int(original_n - len(trimmed)),
        }
    }
    return trimmed, summary


def _has_geometry(frame: Any) -> bool:
    return "geometry" in frame.columns


def _geometry_warnings(frame: Any, geometry_available: bool) -> tuple[str, ...]:
    if geometry_available and getattr(frame, "crs", None) is None:
        return ("Spatial input has geometry but no CRS.",)
    return ()
