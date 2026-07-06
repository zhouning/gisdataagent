"""NOAA ISD observed weather proxy for UWM."""

from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


NOAA_ISD_WEATHER_PROXY_SCHEMA = "uwm.noaa_isd_weather_proxy.v1"
SOURCE_DATASET_ID = "noaa_isd_chongqing_weather_observation_2024_07"


def parse_isd_record(line: str) -> dict[str, Any]:
    """Parse NOAA ISD fixed-width control and mandatory weather fields."""

    date = line[15:23]
    time = line[23:27]
    header_call_sign = line[51:56].strip()
    metar_call_sign = _metar_call_sign(line)
    return {
        "station_id": f"{line[4:10]}-{line[10:15]}",
        "timestamp_utc": _timestamp(date, time),
        "source_flag": line[27:28].strip(),
        "latitude": _signed_scaled(line[28:34], scale=1000, missing={"+99999", "-99999"}),
        "longitude": _signed_scaled(line[34:41], scale=1000, missing={"+999999", "-999999"}),
        "report_type": line[41:46].strip(),
        "elevation_m": _signed_scaled(line[46:51], scale=1, missing={"+9999", "-9999"}),
        "header_call_sign": header_call_sign,
        "metar_call_sign": metar_call_sign,
        "call_sign": _preferred_call_sign(header_call_sign, metar_call_sign),
        "wind_direction_degree": _unsigned_scaled(line[60:63], scale=1, missing={"999"}),
        "wind_direction_quality": line[63:64].strip(),
        "wind_type": line[64:65].strip(),
        "wind_speed_ms": _unsigned_scaled(line[65:69], scale=10, missing={"9999"}),
        "wind_speed_quality": line[69:70].strip(),
        "ceiling_height_m": _unsigned_scaled(line[70:75], scale=1, missing={"99999"}),
        "visibility_m": _unsigned_scaled(line[78:84], scale=1, missing={"999999"}),
        "air_temperature_c": _signed_scaled(line[87:92], scale=10, missing={"+9999", "-9999"}),
        "air_temperature_quality": line[92:93].strip(),
        "dew_point_c": _signed_scaled(line[93:98], scale=10, missing={"+9999", "-9999"}),
        "dew_point_quality": line[98:99].strip(),
        "sea_level_pressure_hpa": _unsigned_scaled(line[99:104], scale=10, missing={"99999"}),
        "sea_level_pressure_quality": line[104:105].strip(),
    }


def build_noaa_isd_weather_proxy(
    lines: Iterable[str],
    *,
    start_date: str,
    end_date: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Build a UWM observed weather proxy from NOAA ISD lines."""

    fetched_at = fetched_at or _utc_now()
    raw_records = [parse_isd_record(line.rstrip("\n")) for line in lines if line.strip()]
    window_records = [
        record
        for record in raw_records
        if _timestamp_in_window(record["timestamp_utc"], start_date=start_date, end_date=end_date)
    ]
    return {
        "schema": NOAA_ISD_WEATHER_PROXY_SCHEMA,
        "source": "NOAA NCEI Integrated Surface Database",
        "source_dataset_ids": [SOURCE_DATASET_ID],
        "source_ref": "https://www.ncei.noaa.gov/pub/data/noaa/2024/575160-99999-2024.gz",
        "time_range": {"start_date": start_date, "end_date": end_date, "time_zone": "UTC"},
        "fetched_at": fetched_at,
        "quality_status": "observed_station_weather_holdout_ready",
        "record_counts": {
            "raw_records_in_file": len(raw_records),
            "records_in_time_window": len(window_records),
            "records_with_temperature": _non_null_count(window_records, "air_temperature_c"),
            "records_with_pressure": _non_null_count(window_records, "sea_level_pressure_hpa"),
            "records_with_wind": _non_null_count(window_records, "wind_speed_ms"),
        },
        "station_summary": _station_summary(window_records),
        "report_type_counts": dict(Counter(record["report_type"] for record in window_records)),
        "summary": _summary(window_records),
        "weather_observation_rows": window_records,
        "synthetic_flags": [{"dataset_id": SOURCE_DATASET_ID, "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": (
                "NOAA ISD provides observed surface weather reports for station 575160-99999 "
                "over the UWM 2024-07 scene window. It can calibrate meteorology context, "
                "but it does not observe air pollution or intervention outcomes."
            ),
        },
        "limitations": [
            "observed_station_weather_not_reanalysis",
            "single_station_or_mixed_report_stream_not_full_city_grid",
            "mandatory_isd_fields_only_additional_sections_not_parsed",
            "not_air_quality_holdout",
            "not_policy_intervention_outcome",
        ],
        "empirical_superiority_claim": False,
    }


def write_noaa_isd_weather_proxy_snapshot(
    *,
    gz_path: str | Path,
    output_dir: str | Path,
    start_date: str,
    end_date: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Read a NOAA ISD gzip file and write the UWM weather proxy snapshot."""

    with gzip.open(gz_path, "rt", encoding="ascii", errors="replace") as handle:
        proxy = build_noaa_isd_weather_proxy(
            handle,
            start_date=start_date,
            end_date=end_date,
            fetched_at=fetched_at,
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "noaa_isd_weather_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "noaa_isd_chongqing_weather_observation_2024_07_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "source_ref": proxy["source_ref"],
        "source_file": str(Path(gz_path)),
        "fetched_at": proxy["fetched_at"],
        "time_range": proxy["time_range"],
        "files": {
            "raw_gzip": Path(gz_path).name,
            "normalized_proxy": "noaa_isd_weather_proxy.json",
        },
        "quality_status": proxy["quality_status"],
        "record_counts": proxy["record_counts"],
        "station_summary": proxy["station_summary"],
        "report_type_counts": proxy["report_type_counts"],
        "summary": proxy["summary"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "empirical_superiority_claim": False,
    }
    _write_json(output / "snapshot_manifest.json", manifest)
    return manifest


def _timestamp(date: str, time: str) -> str:
    parsed = datetime.strptime(f"{date}{time}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _metar_call_sign(line: str) -> str:
    match = re.search(r"METAR\s+([A-Z0-9]{4})\b", line)
    return match.group(1) if match else ""


def _preferred_call_sign(header_call_sign: str, metar_call_sign: str) -> str:
    if header_call_sign and header_call_sign != "99999":
        return header_call_sign
    return metar_call_sign or header_call_sign


def _timestamp_in_window(timestamp: str, *, start_date: str, end_date: str) -> bool:
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    start = datetime.fromisoformat(f"{start_date}T00:00:00+00:00")
    end = datetime.fromisoformat(f"{end_date}T23:59:59+00:00")
    return start <= value <= end


def _signed_scaled(value: str, *, scale: float, missing: set[str]) -> float | None:
    if value in missing:
        return None
    try:
        return float(int(value)) / scale
    except ValueError:
        return None


def _unsigned_scaled(value: str, *, scale: float, missing: set[str]) -> float | None:
    if value in missing:
        return None
    try:
        return float(int(value)) / scale
    except ValueError:
        return None


def _station_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "station_ids": sorted({record["station_id"] for record in records}),
        "call_signs": sorted(
            {
                record["call_sign"]
                for record in records
                if record["call_sign"] and record["call_sign"] != "99999"
            }
        ),
        "latitude_min": _rounded_min(record.get("latitude") for record in records),
        "latitude_max": _rounded_max(record.get("latitude") for record in records),
        "longitude_min": _rounded_min(record.get("longitude") for record in records),
        "longitude_max": _rounded_max(record.get("longitude") for record in records),
        "elevation_min_m": _rounded_min(record.get("elevation_m") for record in records),
        "elevation_max_m": _rounded_max(record.get("elevation_m") for record in records),
    }


def _summary(records: list[dict[str, Any]]) -> dict[str, float | None]:
    return {
        "air_temperature_avg_c": _rounded_mean(record.get("air_temperature_c") for record in records),
        "air_temperature_min_c": _rounded_min(record.get("air_temperature_c") for record in records),
        "air_temperature_max_c": _rounded_max(record.get("air_temperature_c") for record in records),
        "dew_point_avg_c": _rounded_mean(record.get("dew_point_c") for record in records),
        "sea_level_pressure_avg_hpa": _rounded_mean(record.get("sea_level_pressure_hpa") for record in records),
        "wind_speed_avg_ms": _rounded_mean(record.get("wind_speed_ms") for record in records),
        "visibility_avg_m": _rounded_mean(record.get("visibility_m") for record in records),
    }


def _non_null_count(records: list[dict[str, Any]], key: str) -> int:
    return len([record for record in records if record.get(key) is not None])


def _rounded_mean(values: Iterable[Any]) -> float | None:
    numbers = _numbers(values)
    return round(mean(numbers), 3) if numbers else None


def _rounded_min(values: Iterable[Any]) -> float | None:
    numbers = _numbers(values)
    return round(min(numbers), 3) if numbers else None


def _rounded_max(values: Iterable[Any]) -> float | None:
    numbers = _numbers(values)
    return round(max(numbers), 3) if numbers else None


def _numbers(values: Iterable[Any]) -> list[float]:
    return [float(value) for value in values if value is not None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
