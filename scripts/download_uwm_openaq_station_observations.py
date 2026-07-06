"""Download a small OpenAQ v3 station observation proxy snapshot for UWM.

The OpenAQ API key must be supplied at runtime via OPENAQ_API_KEY or stdin.
The key is used only in the request header and is never persisted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from data_agent.uwm.openaq_station_observations import (
    build_mmfe_state_input_from_openaq_station_proxy,
    build_openaq_locations_url,
    build_openaq_sensor_measurements_url,
    write_openaq_station_snapshot,
)


PREFERRED_PARAMETERS = {"pm25", "pm2_5", "pm10", "no2", "so2", "o3", "co"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latitude", type=float, default=29.563)
    parser.add_argument("--longitude", type=float, default=106.551)
    parser.add_argument("--label", default="Chongqing central")
    parser.add_argument("--radius-m", type=int, default=25000)
    parser.add_argument("--location-limit", type=int, default=20)
    parser.add_argument("--sensor-limit", type=int, default=6)
    parser.add_argument("--measurement-limit", type=int, default=100)
    parser.add_argument("--scene-start-date", default="2024-07-01")
    parser.add_argument("--scene-end-date", default="2024-07-07")
    parser.add_argument("--proxy")
    parser.add_argument("--api-key-stdin", action="store_true")
    parser.add_argument(
        "--output-dir",
        default="data/uwm_public_proxy/chongqing_central/openaq_station_observations",
    )
    args = parser.parse_args()

    api_key = _api_key(args.api_key_stdin)
    headers = {"X-API-Key": api_key}
    client_kwargs: dict[str, Any] = {"timeout": 60.0}
    if args.proxy:
        client_kwargs["proxy"] = args.proxy

    with httpx.Client(**client_kwargs) as client:
        locations_url = build_openaq_locations_url(
            latitude=args.latitude,
            longitude=args.longitude,
            radius_m=args.radius_m,
            limit=args.location_limit,
        )
        locations_payload = _get_json(client, locations_url, headers)
        sensor_ids = _choose_sensor_ids(locations_payload, args.sensor_limit)
        date_from, date_to = scene_measurement_datetime_bounds(args.scene_start_date, args.scene_end_date)
        measurement_payloads = {}
        for sensor_id in sensor_ids:
            url = build_openaq_sensor_measurements_url(
                sensor_id=sensor_id,
                date_from=date_from,
                date_to=date_to,
                limit=args.measurement_limit,
            )
            measurement_payloads[str(sensor_id)] = _get_json(client, url, headers)

    fetched_at = datetime.now(timezone.utc).isoformat()
    output_dir = Path(args.output_dir)
    manifest = write_openaq_station_snapshot(
        output_dir=output_dir,
        locations_payload=locations_payload,
        sensor_measurement_payloads=measurement_payloads,
        requested_location={"latitude": args.latitude, "longitude": args.longitude, "label": args.label},
        scene_time_range={"start_date": args.scene_start_date, "end_date": args.scene_end_date},
        fetched_at=fetched_at,
    )
    proxy = json.loads((output_dir / "openaq_station_observation_proxy.json").read_text(encoding="utf-8"))
    state_input = build_mmfe_state_input_from_openaq_station_proxy(proxy, timestamp=fetched_at)
    _write_json(output_dir / "mmfe_uwm_state_input_openaq_station.json", state_input)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "manifest": "snapshot_manifest.json",
                "record_counts": manifest["record_counts"],
                "observed_time_range": manifest["observed_time_range"],
                "scene_holdout_ready": manifest["scene_holdout_ready"],
                "sensor_ids": sensor_ids,
            },
            ensure_ascii=False,
        )
    )


def _api_key(read_stdin: bool) -> str:
    if read_stdin:
        key = sys.stdin.readline().strip()
    else:
        key = os.environ.get("OPENAQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("OpenAQ API key is required via OPENAQ_API_KEY or --api-key-stdin")
    return key


def scene_measurement_datetime_bounds(scene_start_date: str, scene_end_date: str) -> tuple[str, str]:
    """Convert inclusive scene dates to OpenAQ UTC measurement datetime bounds."""

    start = datetime.fromisoformat(scene_start_date).date()
    end_exclusive = datetime.fromisoformat(scene_end_date).date() + timedelta(days=1)
    return f"{start.isoformat()}T00:00:00Z", f"{end_exclusive.isoformat()}T00:00:00Z"


def _get_json(client: httpx.Client, url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def _choose_sensor_ids(locations_payload: dict[str, Any], limit: int) -> list[int]:
    locations = locations_payload.get("results") or []
    ordered_locations = sorted(locations, key=lambda row: _float(row.get("distance")) or float("inf"))
    sensor_ids = []
    for location in ordered_locations:
        for sensor in location.get("sensors") or []:
            parameter = sensor.get("parameter") or {}
            name = str(parameter.get("name") or "").lower().replace(".", "")
            if name in PREFERRED_PARAMETERS and sensor.get("id") is not None:
                sensor_ids.append(int(sensor["id"]))
            if len(sensor_ids) >= limit:
                return sensor_ids
    return sensor_ids


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
