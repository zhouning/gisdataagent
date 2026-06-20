from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

try:
    import geopandas as gpd
except Exception:  # pragma: no cover - optional in some environments
    gpd = None  # type: ignore[assignment]


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def read_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_geojson_records(path: str | Path) -> list[dict[str, Any]]:
    if gpd is None:
        raise RuntimeError("geopandas is required to read geospatial fixtures")
    gdf = gpd.read_file(path)
    return [dict(row) for row in gdf.to_dict(orient="records")]


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def compact_text(value: Any) -> str:
    return str(value or "").strip()

