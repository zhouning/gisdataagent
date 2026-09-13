"""Build UWM final livability endpoint suite from the multisource scene."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.livability_endpoint_suite import (
    build_uwm_livability_endpoint_suite,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "livability_endpoint_suite_2026_07_07"
OUTPUT_PATH = OUTPUT_DIR / "uwm_livability_endpoint_suite.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
MULTISOURCE_LIVABILITY_SCENE_PATH = (
    DATA_ROOT
    / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
)
BUILDING_FLOOR_MORPHOLOGY_PATH = (
    DATA_ROOT
    / "building_floor_morphology_2026_07_07/uwm_building_floor_morphology.json"
)


def main() -> None:
    suite = build_uwm_livability_endpoint_suite(
        suite_id="uwm-final-livability-endpoint-suite-2026-07-07",
        created_at="2026-07-07T09:30:00Z",
        multisource_livability_scene=_read_json(MULTISOURCE_LIVABILITY_SCENE_PATH),
        building_floor_morphology=_read_json(BUILDING_FLOOR_MORPHOLOGY_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, suite)
    manifest = {
        "snapshot_id": "uwm_livability_endpoint_suite_2026_07_07",
        "created_at": "2026-07-07T09:30:00Z",
        "suite_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_scene_path": str(
            MULTISOURCE_LIVABILITY_SCENE_PATH.relative_to(REPO_ROOT)
        ),
        "source_building_floor_morphology_path": str(
            BUILDING_FLOOR_MORPHOLOGY_PATH.relative_to(REPO_ROOT)
        ),
        "admin_unit_count": suite["admin_unit_count"],
        "building_floor_morphology_projected": suite[
            "building_floor_morphology_projected"
        ],
        "building_floor_matched_admin_units": suite[
            "building_floor_matched_admin_units"
        ],
        "endpoint_count": suite["endpoint_count"],
        "ready_endpoint_count": suite["ready_endpoint_count"],
        "mean_relative_mae_reduction_vs_best_traditional": suite[
            "mean_relative_mae_reduction_vs_best_traditional"
        ],
        "min_relative_mae_reduction_vs_best_traditional": suite[
            "min_relative_mae_reduction_vs_best_traditional"
        ],
        "supported_claim": suite["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "suite_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "admin_unit_count": suite["admin_unit_count"],
                "building_floor_morphology_projected": suite[
                    "building_floor_morphology_projected"
                ],
                "building_floor_matched_admin_units": suite[
                    "building_floor_matched_admin_units"
                ],
                "endpoint_count": suite["endpoint_count"],
                "ready_endpoint_count": suite["ready_endpoint_count"],
                "mean_relative_mae_reduction_vs_best_traditional": suite[
                    "mean_relative_mae_reduction_vs_best_traditional"
                ],
                "min_relative_mae_reduction_vs_best_traditional": suite[
                    "min_relative_mae_reduction_vs_best_traditional"
                ],
                "supported_claim": suite["supported_claim"],
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
