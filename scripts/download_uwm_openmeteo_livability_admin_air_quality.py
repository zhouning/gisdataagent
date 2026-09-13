"""Download Open-Meteo historical air-quality proxies for UWM livability admin units."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlencode

import httpx
from shapely.geometry import shape


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_GEOJSON = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/admin_units/chongqing_township_admin_units.geojson"
LIVABILITY_PANEL = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/openmeteo_livability_admin_air_quality_2024_07_01_07"
)
AIR_FIELDS = ["pm10", "pm2_5", "carbon_monoxide", "nitrogen_dioxide", "sulphur_dioxide", "ozone"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2024-07-01")
    parser.add_argument("--end-date", default="2024-07-07")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    selected = _selected_admin_points()
    client_kwargs: dict[str, Any] = {"timeout": 60.0}
    if args.proxy:
        client_kwargs["proxy"] = args.proxy
    payloads = {}
    rows = []
    with httpx.Client(**client_kwargs) as client:
        for unit in selected:
            url = _openmeteo_air_url(
                latitude=unit["latitude"],
                longitude=unit["longitude"],
                start_date=args.start_date,
                end_date=args.end_date,
            )
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
            payloads[unit["admin_unit_id"]] = payload
            rows.append(_row_from_payload(unit, payload))

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    proxy = {
        "schema": "uwm.openmeteo_livability_admin_air_quality_proxy.v1",
        "source": "Open-Meteo Air Quality API",
        "source_dataset_ids": ["openmeteo_livability_admin_air_quality_proxy"],
        "time_range": {"start_date": args.start_date, "end_date": args.end_date},
        "fetched_at": fetched_at,
        "record_counts": {
            "admin_units": len(rows),
            "hourly_records": sum(row["hourly_record_count"] for row in rows),
        },
        "coverage": {
            "requested_admin_units": len(selected),
            "sampled_admin_units": len(rows),
            "sampling_geometry": "admin_representative_point",
        },
        "admin_air_quality_rows": rows,
        "summary": {
            "pm25_avg_ugm3": _rounded_mean(row.get("pm25_avg_ugm3") for row in rows),
            "pm25_min_avg_ugm3": _rounded_min(row.get("pm25_avg_ugm3") for row in rows),
            "pm25_max_avg_ugm3": _rounded_max(row.get("pm25_avg_ugm3") for row in rows),
            "no2_avg_ugm3": _rounded_mean(row.get("no2_avg_ugm3") for row in rows),
            "o3_avg_ugm3": _rounded_mean(row.get("o3_avg_ugm3") for row in rows),
        },
        "synthetic_flags": [
            {"dataset_id": "openmeteo_livability_admin_air_quality_proxy", "status": "public_proxy"}
        ],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "Open-Meteo historical air-quality estimates are reproducible public model proxies, not station-calibrated observed holdout.",
        },
        "limitations": [
            "public_model_proxy_not_station_observation",
            "admin_representative_point_not_polygon_zonal_mean",
            "not_policy_intervention_outcome",
        ],
        "empirical_superiority_claim": False,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "openmeteo_livability_admin_air_quality_raw.json", payloads)
    _write_json(output_dir / "openmeteo_livability_admin_air_quality_proxy.json", proxy)
    _write_json(
        output_dir / "snapshot_manifest.json",
        {
            "schema": "uwm.public_proxy_snapshot_manifest.v1",
            "dataset_id": "openmeteo_livability_admin_air_quality_proxy_snapshot",
            "source_dataset_ids": proxy["source_dataset_ids"],
            "fetched_at": fetched_at,
            "time_range": proxy["time_range"],
            "files": {
                "raw": "openmeteo_livability_admin_air_quality_raw.json",
                "normalized_proxy": "openmeteo_livability_admin_air_quality_proxy.json",
            },
            "record_counts": proxy["record_counts"],
            "coverage": proxy["coverage"],
            "summary": proxy["summary"],
            "claim_boundary": proxy["claim_boundary"],
            "limitations": proxy["limitations"],
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir.relative_to(REPO_ROOT)),
                "record_counts": proxy["record_counts"],
                "coverage": proxy["coverage"],
                "summary": proxy["summary"],
                "claim_boundary": proxy["claim_boundary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _selected_admin_points() -> list[dict[str, Any]]:
    panel = _load_json(LIVABILITY_PANEL)
    selected_ids = {str(row.get("admin_unit_id")) for row in panel.get("admin_livability_target_rows") or []}
    admin_geojson = _load_json(ADMIN_GEOJSON)
    units = []
    for index, feature in enumerate(admin_geojson.get("features") or []):
        props = feature.get("properties") or {}
        admin_unit_id = str(props.get("admin_unit_id") or _fallback_admin_unit_id(props, index))
        if admin_unit_id not in selected_ids:
            continue
        point = shape(feature.get("geometry")).representative_point()
        units.append(
            {
                "admin_unit_id": admin_unit_id,
                "county": str(props.get("county") or ""),
                "township": str(props.get("township") or ""),
                "longitude": float(point.x),
                "latitude": float(point.y),
            }
        )
    return units


def _openmeteo_air_url(*, latitude: float, longitude: float, start_date: str, end_date: str) -> str:
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ",".join(AIR_FIELDS),
            "timezone": "Asia/Shanghai",
        },
        safe=",/",
    )
    return f"https://air-quality-api.open-meteo.com/v1/air-quality?{query}"


def _row_from_payload(unit: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    hourly = payload.get("hourly") or {}
    return {
        **unit,
        "resolved_latitude": _float(payload.get("latitude")),
        "resolved_longitude": _float(payload.get("longitude")),
        "hourly_record_count": len(hourly.get("time") or []),
        "pm10_avg_ugm3": _rounded_mean(hourly.get("pm10")),
        "pm25_avg_ugm3": _rounded_mean(hourly.get("pm2_5")),
        "co_avg_ugm3": _rounded_mean(hourly.get("carbon_monoxide")),
        "no2_avg_ugm3": _rounded_mean(hourly.get("nitrogen_dioxide")),
        "so2_avg_ugm3": _rounded_mean(hourly.get("sulphur_dioxide")),
        "o3_avg_ugm3": _rounded_mean(hourly.get("ozone")),
        "non_null_counts": {
            field: len([value for value in hourly.get(field) or [] if value is not None])
            for field in AIR_FIELDS
        },
    }


def _fallback_admin_unit_id(props: dict[str, Any], index: int) -> str:
    return f"{str(props.get('county') or '')}|{str(props.get('township') or '')}|{index}"


def _rounded_mean(values: Any) -> float | None:
    numbers = [number for number in (_float(value) for value in values or []) if number is not None]
    return round(mean(numbers), 3) if numbers else None


def _rounded_min(values: Any) -> float | None:
    numbers = [number for number in (_float(value) for value in values or []) if number is not None]
    return round(min(numbers), 3) if numbers else None


def _rounded_max(values: Any) -> float | None:
    numbers = [number for number in (_float(value) for value in values or []) if number is not None]
    return round(max(numbers), 3) if numbers else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
