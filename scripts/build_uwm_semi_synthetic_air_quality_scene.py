"""Build a semi-synthetic scene-aligned air-quality panel for UWM stress tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ZONAL_PROXY = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/gee_livability_admin_zonal_environment_2024_07_01_07/gee_livability_admin_zonal_environment_proxy.json"
)
OPENAQ_RAW = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_sensor_measurements_raw.json"
OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/semi_synthetic_air_quality_scene_2024_07_01_07"


def main() -> None:
    zonal = _load_json(ZONAL_PROXY)
    openaq_raw = _load_json(OPENAQ_RAW)
    pm25_pattern = _pm25_anomaly_pattern(openaq_raw)
    hours = _hourly_scene_index("2024-07-01T00:00:00Z", 168)
    records = []
    fallback_pm25 = _float((zonal.get("summary") or {}).get("cams_pm25_ugm3_avg"))
    if fallback_pm25 is None:
        raise ValueError("zonal proxy has no CAMS PM2.5 summary for semi-synthetic base")
    for row in zonal.get("admin_environment_rows") or []:
        base_pm25 = _float(row.get("cams_pm25_ugm3"))
        base_source = "admin_zonal_value"
        if base_pm25 is None:
            base_pm25 = fallback_pm25
            base_source = "zonal_summary_fallback_for_null_admin_value"
        for hour_index, timestamp in enumerate(hours):
            anomaly = pm25_pattern[hour_index % len(pm25_pattern)]
            records.append(
                {
                    "timestamp": timestamp,
                    "admin_unit_id": row.get("admin_unit_id"),
                    "county": row.get("county"),
                    "township": row.get("township"),
                    "pm25_ugm3": round(max(0.0, base_pm25 + anomaly), 3),
                    "base_cams_zonal_pm25_ugm3": base_pm25,
                    "base_cams_zonal_source": base_source,
                    "openaq_temporal_anomaly_ugm3": round(anomaly, 3),
                }
            )
    payload = {
        "schema": "uwm.semi_synthetic_air_quality_scene.v1",
        "scene_id": "uwm-semi-synthetic-air-quality-scene-2024-07-01-07",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_dataset_ids": [
            "gee_livability_admin_zonal_environment_proxy",
            "openaq_air_quality_station_observation_proxy",
        ],
        "synthesis_method": {
            "base": "2024-07-01_to_2024-07-07 GEE CAMS simplified-polygon zonal PM2.5",
            "temporal_pattern": "OpenAQ 2018 observed PM2.5 hourly anomaly pattern centered to zero mean",
            "formula": "synthetic_pm25 = max(0, cams_zonal_pm25 + centered_openaq_pm25_anomaly)",
        },
        "time_range": {"start": hours[0], "end": hours[-1]},
        "record_counts": {
            "admin_units": len(zonal.get("admin_environment_rows") or []),
            "hours": len(hours),
            "records": len(records),
            "openaq_pm25_pattern_points": len(pm25_pattern),
        },
        "summary": {
            "pm25_ugm3_avg": round(mean(record["pm25_ugm3"] for record in records), 3) if records else None,
            "pm25_ugm3_min": round(min(record["pm25_ugm3"] for record in records), 3) if records else None,
            "pm25_ugm3_max": round(max(record["pm25_ugm3"] for record in records), 3) if records else None,
        },
        "records": records,
        "synthetic_flags": [
            {
                "dataset_id": "semi_synthetic_air_quality_scene_2024_07",
                "status": "semi_synthetic",
            }
        ],
        "claim_boundary": {
            "max_claim_level": "exploratory_only",
            "reason": "Scene-aligned PM2.5 panel is semi-synthetic because OpenAQ has no 2024-07 Chongqing measurements in this attempt.",
        },
        "limitations": [
            "not_observed_air_quality_holdout",
            "not_policy_intervention_outcome",
            "cams_model_proxy_plus_historical_openaq_temporal_pattern",
            "for_pipeline_stress_test_and_negative_control_only",
        ],
        "empirical_superiority_claim": False,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_DIR / "uwm_semi_synthetic_air_quality_scene.json", payload)
    _write_json(
        OUTPUT_DIR / "snapshot_manifest.json",
        {
            "schema": "uwm.synthetic_snapshot_manifest.v1",
            "dataset_id": "semi_synthetic_air_quality_scene_2024_07",
            "source_dataset_ids": payload["source_dataset_ids"],
            "files": {"scene": "uwm_semi_synthetic_air_quality_scene.json"},
            "record_counts": payload["record_counts"],
            "summary": payload["summary"],
            "claim_boundary": payload["claim_boundary"],
            "limitations": payload["limitations"],
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR.relative_to(REPO_ROOT)),
                "record_counts": payload["record_counts"],
                "summary": payload["summary"],
                "claim_boundary": payload["claim_boundary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _pm25_anomaly_pattern(raw: dict[str, Any]) -> list[float]:
    values = []
    for payload in raw.values():
        for row in payload.get("results") or []:
            parameter = row.get("parameter") or {}
            name = str(parameter.get("name") or "").lower().replace(".", "")
            if name not in {"pm25", "pm2_5"}:
                continue
            value = _float(row.get("value"))
            if value is not None:
                values.append(value)
    if not values:
        raise ValueError("OpenAQ raw payload contains no PM2.5 values for temporal anomaly synthesis")
    center = mean(values)
    return [0.35 * (value - center) for value in values]


def _hourly_scene_index(start: str, count: int) -> list[str]:
    current = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return [
        (current + timedelta(hours=index)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        for index in range(count)
    ]


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
