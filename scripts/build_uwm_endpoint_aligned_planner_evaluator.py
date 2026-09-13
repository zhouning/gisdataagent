"""Build UWM endpoint-aligned planner evaluator from real replay artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.endpoint_aligned_planner_evaluator import (
    build_uwm_endpoint_aligned_planner_evaluator,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "endpoint_aligned_planner_evaluator_2026_07_07"
OUTPUT_PATH = OUTPUT_DIR / "uwm_endpoint_aligned_planner_evaluator.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
DATA_CALIBRATED_PLANNER_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
)
LIVABILITY_ENDPOINT_SUITE_PATH = (
    DATA_ROOT
    / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json"
)


def main() -> None:
    evaluator = build_uwm_endpoint_aligned_planner_evaluator(
        evaluator_id="uwm-endpoint-aligned-planner-evaluator-2026-07-07",
        created_at="2026-07-07T10:20:00Z",
        data_calibrated_planner_replay=_read_json(
            DATA_CALIBRATED_PLANNER_REPLAY_PATH
        ),
        livability_endpoint_suite=_read_json(LIVABILITY_ENDPOINT_SUITE_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, evaluator)
    manifest = {
        "snapshot_id": "uwm_endpoint_aligned_planner_evaluator_2026_07_07",
        "created_at": "2026-07-07T10:20:00Z",
        "evaluator_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_planner_replay_path": str(
            DATA_CALIBRATED_PLANNER_REPLAY_PATH.relative_to(REPO_ROOT)
        ),
        "source_endpoint_suite_path": str(
            LIVABILITY_ENDPOINT_SUITE_PATH.relative_to(REPO_ROOT)
        ),
        "endpoint_count": evaluator["endpoint_count"],
        "planner_endpoint_aligned_score": evaluator[
            "planner_endpoint_aligned_score"
        ],
        "static_endpoint_aligned_score": evaluator["static_endpoint_aligned_score"],
        "endpoint_aligned_advantage_over_static": evaluator[
            "endpoint_aligned_advantage_over_static"
        ],
        "endpoint_aligned_advantage_ratio": evaluator[
            "endpoint_aligned_advantage_ratio"
        ],
        "supported_claim": evaluator["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "evaluator_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "endpoint_count": evaluator["endpoint_count"],
                "planner_endpoint_aligned_score": evaluator[
                    "planner_endpoint_aligned_score"
                ],
                "static_endpoint_aligned_score": evaluator[
                    "static_endpoint_aligned_score"
                ],
                "endpoint_aligned_advantage_over_static": evaluator[
                    "endpoint_aligned_advantage_over_static"
                ],
                "endpoint_aligned_advantage_ratio": evaluator[
                    "endpoint_aligned_advantage_ratio"
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
