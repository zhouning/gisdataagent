"""Download and persist small public proxy snapshots for UWM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .openmeteo_proxy import build_openmeteo_environmental_proxy


OPENMETEO_WEATHER_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "surface_pressure",
    "wind_speed_10m",
]

OPENMETEO_AIR_QUALITY_FIELDS = [
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
]


def build_openmeteo_urls(*, latitude: float, longitude: float) -> dict[str, str]:
    """Build Open-Meteo URLs matching the savemyself runtime field set."""

    weather_query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(OPENMETEO_WEATHER_FIELDS),
        },
        safe=",",
    )
    air_query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(OPENMETEO_AIR_QUALITY_FIELDS),
        },
        safe=",",
    )
    return {
        "weather": f"https://api.open-meteo.com/v1/forecast?{weather_query}",
        "air_quality": f"https://air-quality-api.open-meteo.com/v1/air-quality?{air_query}",
    }


def write_openmeteo_snapshot(
    *,
    output_dir: str | Path,
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any],
    requested_location: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    """Persist raw Open-Meteo payloads, normalized proxy and snapshot manifest."""

    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    _write_json(path / "openmeteo_weather_raw.json", weather_payload)
    _write_json(path / "openmeteo_air_quality_raw.json", air_quality_payload)
    normalized = build_openmeteo_environmental_proxy(
        weather_payload,
        air_quality_payload,
        requested_location=requested_location,
    )
    _write_json(path / "openmeteo_environmental_proxy.json", normalized)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "openmeteo_environmental_proxy_snapshot",
        "source_dataset_ids": normalized["source_dataset_ids"],
        "fetched_at": fetched_at,
        "requested_location": requested_location,
        "files": {
            "weather_raw": "openmeteo_weather_raw.json",
            "air_quality_raw": "openmeteo_air_quality_raw.json",
            "normalized_proxy": "openmeteo_environmental_proxy.json",
        },
        "claim_boundary": normalized["claim_boundary"],
        "limitations": normalized["limitations"],
        "mmfe_target_roles": normalized["mmfe_target_roles"],
    }
    _write_json(path / "snapshot_manifest.json", manifest)
    return manifest


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
