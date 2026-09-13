"""Build scene-aligned gridded air-quality holdout artifacts for UWM."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.scene_aligned_gridded_air_quality_holdout import (
    build_uwm_scene_aligned_gridded_air_quality_holdout,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/scene_aligned_gridded_air_quality_holdout_2026_07_06"
)
OUTPUT_PATH = OUTPUT_DIR / "uwm_scene_aligned_gridded_air_quality_holdout.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
CHAP_ADMIN_PROXY_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/chap_pm25_2024_07/chap_pm25_admin_proxy.json"
)
TAP_ROOT = Path("/Users/zhouning/Downloads/tap_uwm")


def main() -> None:
    chap = _load_json(CHAP_ADMIN_PROXY_PATH)
    holdout = build_uwm_scene_aligned_gridded_air_quality_holdout(
        chap_admin_proxy=chap,
        tap_root=TAP_ROOT,
        benchmark_id="uwm-scene-aligned-gridded-air-quality-holdout-2026-07-06",
        created_at="2026-07-06T21:20:00Z",
        train_days=3,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, holdout)
    snapshot = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "snapshot_id": "uwm_scene_aligned_gridded_air_quality_holdout_2026_07_06",
        "created_at": "2026-07-06T21:20:00Z",
        "holdout_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_chap_admin_proxy_path": str(CHAP_ADMIN_PROXY_PATH.relative_to(REPO_ROOT)),
        "source_tap_root": str(TAP_ROOT),
        "source_dataset_ids": holdout["source_dataset_ids"],
        "admin_unit_count": holdout["admin_unit_count"],
        "holdout_count": holdout["holdout_count"],
        "scene_aligned_gridded_air_quality_holdout_ready": holdout[
            "scene_aligned_gridded_air_quality_holdout_ready"
        ],
        "scene_aligned_station_calibrated_air_quality_holdout_ready": holdout[
            "scene_aligned_station_calibrated_air_quality_holdout_ready"
        ],
        "supported_claim": holdout["supported_claim"],
        "uncertainty_calibration": holdout["uncertainty_calibration"],
        "claim_boundary": holdout["claim_boundary"],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, snapshot)
    overall = holdout["overall_results"]
    uncertainty = holdout["uncertainty_calibration"]
    print(
        json.dumps(
            {
                "holdout_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "admin_unit_count": holdout["admin_unit_count"],
                "holdout_count": holdout["holdout_count"],
                "best_uwm_method": overall["best_uwm_method"],
                "best_uwm_mae": overall["best_uwm_mae"],
                "best_static_baseline_method": overall[
                    "best_static_baseline_method"
                ],
                "best_static_baseline_mae": overall["best_static_baseline_mae"],
                "best_uwm_mae_reduction": overall["best_uwm_mae_reduction"],
                "spatial_shuffle_negative_control_passed": holdout[
                    "spatial_message_negative_control_summary"
                ]["spatial_shuffle_negative_control_passed"],
                "uwm_uncertainty_calibration_ready": uncertainty[
                    "uwm_uncertainty_calibration_ready"
                ],
                "uwm_interval_score": uncertainty["uwm_interval_score"],
                "static_interval_score": uncertainty["static_interval_score"],
                "uwm_interval_score_reduction": uncertainty[
                    "uwm_interval_score_reduction"
                ],
                "supported_claim": holdout["supported_claim"],
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
