"""Build UWM station-aligned air-quality holdout from real OpenAQ and TAP data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.station_aligned_air_quality_holdout import (
    build_uwm_station_aligned_air_quality_holdout,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPENAQ_MEASUREMENTS_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_sensor_measurements_raw.json"
)
DEFAULT_OPENAQ_STATION_PROXY_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_station_observation_proxy.json"
)
DEFAULT_OPENAQ_SCENE_ATTEMPT_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations_2024_07_attempt/openaq_station_observation_proxy.json"
)
DEFAULT_TAP_ROOT = REPO_ROOT.parent / "Downloads/tap_uwm"
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/station_aligned_air_quality_holdout_2026_07_06"
)
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "uwm_station_aligned_air_quality_holdout.json"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "snapshot_manifest.json"


def build_station_aligned_air_quality_holdout(
    *,
    openaq_measurements_path: str | Path = DEFAULT_OPENAQ_MEASUREMENTS_PATH,
    openaq_station_proxy_path: str | Path = DEFAULT_OPENAQ_STATION_PROXY_PATH,
    openaq_scene_attempt_path: str | Path = DEFAULT_OPENAQ_SCENE_ATTEMPT_PATH,
    tap_root: str | Path = DEFAULT_TAP_ROOT,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    holdout_id: str = "uwm-station-aligned-air-quality-holdout-2026-07-06",
    created_at: str = "2026-07-06T14:20:00Z",
) -> dict[str, Any]:
    """Write station-aligned holdout evidence and a snapshot manifest."""

    measurements_path = Path(openaq_measurements_path)
    station_proxy_path = Path(openaq_station_proxy_path)
    scene_attempt_path = Path(openaq_scene_attempt_path)
    tap_root_path = Path(tap_root)
    for path in [measurements_path, station_proxy_path, scene_attempt_path, tap_root_path]:
        if not path.exists():
            raise FileNotFoundError(f"required source path not found: {path}")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    holdout = build_uwm_station_aligned_air_quality_holdout(
        openaq_measurements_path=measurements_path,
        openaq_station_proxy_path=station_proxy_path,
        openaq_scene_attempt_path=scene_attempt_path,
        tap_root=tap_root_path,
        holdout_id=holdout_id,
        created_at=created_at,
    )
    holdout_path = out / DEFAULT_OUTPUT_PATH.name
    manifest_path = out / DEFAULT_MANIFEST_PATH.name
    with holdout_path.open("w", encoding="utf-8") as handle:
        json.dump(holdout, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    manifest = {
        "schema": "uwm.station_aligned_air_quality_holdout_snapshot_manifest.v1",
        "created_at": created_at,
        "outputs": {
            "station_aligned_air_quality_holdout": str(
                holdout_path.relative_to(REPO_ROOT)
            ),
        },
        "source_artifacts": holdout["source_artifacts"],
        "source_dataset_ids": holdout["source_dataset_ids"],
        "historical_station_aligned_holdout_ready": holdout[
            "historical_station_aligned_holdout_ready"
        ],
        "scene_aligned_station_calibrated_air_quality_holdout_ready": holdout[
            "scene_aligned_station_calibrated_air_quality_holdout_ready"
        ],
        "observed_policy_outcome_superiority_claim": holdout[
            "observed_policy_outcome_superiority_claim"
        ],
        "limitations": holdout["limitations"],
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "holdout_path": str(holdout_path),
        "manifest_path": str(manifest_path),
        "holdout": holdout,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openaq-measurements-path", default=str(DEFAULT_OPENAQ_MEASUREMENTS_PATH))
    parser.add_argument("--openaq-station-proxy-path", default=str(DEFAULT_OPENAQ_STATION_PROXY_PATH))
    parser.add_argument("--openaq-scene-attempt-path", default=str(DEFAULT_OPENAQ_SCENE_ATTEMPT_PATH))
    parser.add_argument("--tap-root", default=str(DEFAULT_TAP_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--holdout-id",
        default="uwm-station-aligned-air-quality-holdout-2026-07-06",
    )
    parser.add_argument("--created-at", default="2026-07-06T14:20:00Z")
    args = parser.parse_args()
    result = build_station_aligned_air_quality_holdout(
        openaq_measurements_path=args.openaq_measurements_path,
        openaq_station_proxy_path=args.openaq_station_proxy_path,
        openaq_scene_attempt_path=args.openaq_scene_attempt_path,
        tap_root=args.tap_root,
        output_dir=args.output_dir,
        holdout_id=args.holdout_id,
        created_at=args.created_at,
    )
    holdout = result["holdout"]
    print(
        json.dumps(
            {
                "path": str(Path(result["holdout_path"]).relative_to(REPO_ROOT)),
                "manifest_path": str(Path(result["manifest_path"]).relative_to(REPO_ROOT)),
                "historical_station_aligned_holdout_ready": holdout[
                    "historical_station_aligned_holdout_ready"
                ],
                "scene_aligned_station_calibrated_air_quality_holdout_ready": holdout[
                    "scene_aligned_station_calibrated_air_quality_holdout_ready"
                ],
                "best_station_aligned_method": holdout["holdout_benchmark"][
                    "best_station_aligned_method"
                ],
                "raw_tap_mae": holdout["holdout_benchmark"]["raw_tap_mae"],
                "static_train_mean_mae": holdout["holdout_benchmark"][
                    "static_train_mean_mae"
                ],
                "remaining_gates": holdout["remaining_gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
