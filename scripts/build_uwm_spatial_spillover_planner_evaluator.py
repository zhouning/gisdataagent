"""Build UWM spatial spillover planner evaluator from real graph artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.spatial_spillover_planner_evaluator import (
    build_uwm_spatial_spillover_planner_evaluator,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "spatial_spillover_planner_evaluator_2026_07_07"
OUTPUT_PATH = OUTPUT_DIR / "uwm_spatial_spillover_planner_evaluator.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
DATA_CALIBRATED_PLANNER_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
)
ADMIN_SPATIAL_GRAPH_PATH = (
    DATA_ROOT / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)


def main() -> None:
    evaluator = build_uwm_spatial_spillover_planner_evaluator(
        evaluator_id="uwm-spatial-spillover-planner-evaluator-2026-07-07",
        created_at="2026-07-07T11:20:00Z",
        data_calibrated_planner_replay=_read_json(
            DATA_CALIBRATED_PLANNER_REPLAY_PATH
        ),
        admin_spatial_graph=_read_json(ADMIN_SPATIAL_GRAPH_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, evaluator)
    manifest = {
        "snapshot_id": "uwm_spatial_spillover_planner_evaluator_2026_07_07",
        "created_at": "2026-07-07T11:20:00Z",
        "evaluator_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_planner_replay_path": str(
            DATA_CALIBRATED_PLANNER_REPLAY_PATH.relative_to(REPO_ROOT)
        ),
        "source_admin_spatial_graph_path": str(
            ADMIN_SPATIAL_GRAPH_PATH.relative_to(REPO_ROOT)
        ),
        "planner_neighbor_benefited_unit_count": evaluator[
            "planner_neighbor_benefited_unit_count"
        ],
        "static_neighbor_benefited_unit_count": evaluator[
            "static_neighbor_benefited_unit_count"
        ],
        "neighbor_livability_delta_advantage": evaluator[
            "neighbor_livability_delta_advantage"
        ],
        "supported_claim": evaluator["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "evaluator_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "planner_neighbor_benefited_unit_count": evaluator[
                    "planner_neighbor_benefited_unit_count"
                ],
                "static_neighbor_benefited_unit_count": evaluator[
                    "static_neighbor_benefited_unit_count"
                ],
                "neighbor_livability_delta_advantage": evaluator[
                    "neighbor_livability_delta_advantage"
                ],
                "neighbor_livability_delta_advantage_ratio": evaluator[
                    "neighbor_livability_delta_advantage_ratio"
                ],
                "supported_claim": evaluator["supported_claim"],
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
