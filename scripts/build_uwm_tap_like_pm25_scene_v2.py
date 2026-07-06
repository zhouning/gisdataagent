"""Build a CHAP-anchored TAP-like semi-synthetic PM2.5 scene for UWM."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.tap_like_air_quality_scene import build_tap_like_pm25_scene_v2


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAP_PROXY = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/chap_pm25_2024_07/chap_pm25_admin_proxy.json"
OPENMETEO_RAW = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/openmeteo_livability_admin_air_quality_2024_07_01_07/openmeteo_livability_admin_air_quality_raw.json"
)
OPENAQ_RAW = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_sensor_measurements_raw.json"
)
NOAA_PROXY = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/noaa_isd_weather_2024_07_01_07/noaa_isd_weather_proxy.json"
)
GEE_ZONAL_PROXY = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/gee_livability_admin_zonal_environment_2024_07_01_07/gee_livability_admin_zonal_environment_proxy.json"
)
OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/tap_like_pm25_scene_v2_2024_07_01_07"
OUTPUT_SCENE = OUTPUT_DIR / "uwm_tap_like_pm25_scene_v2.json"
OUTPUT_MANIFEST = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    scene = build_tap_like_pm25_scene_v2(
        chap_proxy=_load_json(CHAP_PROXY),
        openmeteo_raw=_load_json(OPENMETEO_RAW),
        openaq_raw=_load_json(OPENAQ_RAW),
        noaa_weather_proxy=_load_json(NOAA_PROXY),
        gee_zonal_proxy=_load_json(GEE_ZONAL_PROXY),
        scene_id="uwm-tap-like-pm25-scene-v2-2024-07-01-07",
        created_at="2026-07-05T20:30:00Z",
    )
    scene["source_paths"] = {
        "chap_proxy": str(CHAP_PROXY.relative_to(REPO_ROOT)),
        "openmeteo_raw": str(OPENMETEO_RAW.relative_to(REPO_ROOT)),
        "openaq_raw": str(OPENAQ_RAW.relative_to(REPO_ROOT)),
        "noaa_weather_proxy": str(NOAA_PROXY.relative_to(REPO_ROOT)),
        "gee_zonal_proxy": str(GEE_ZONAL_PROXY.relative_to(REPO_ROOT)),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_SCENE, scene)
    _write_json(
        OUTPUT_MANIFEST,
        {
            "schema": "uwm.synthetic_snapshot_manifest.v1",
            "dataset_id": "tap_like_pm25_scene_v2_2024_07",
            "synthetic_status": scene["synthetic_status"],
            "quality_status": scene["quality_status"],
            "source_dataset_ids": scene["source_dataset_ids"],
            "source_paths": scene["source_paths"],
            "files": {"scene": OUTPUT_SCENE.name},
            "record_counts": scene["record_counts"],
            "calibration_summary": scene["calibration_summary"],
            "summary": scene["summary"],
            "claim_boundary": scene["claim_boundary"],
            "limitations": scene["limitations"],
            "empirical_superiority_claim": False,
        },
    )
    print(
        json.dumps(
            {
                "output_scene": str(OUTPUT_SCENE.relative_to(REPO_ROOT)),
                "record_counts": scene["record_counts"],
                "calibration_summary": scene["calibration_summary"],
                "summary": scene["summary"],
                "claim_boundary": scene["claim_boundary"],
                "empirical_superiority_claim": scene["empirical_superiority_claim"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
