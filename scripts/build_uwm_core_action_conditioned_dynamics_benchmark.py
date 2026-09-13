"""Build the full-admin UWM core action-conditioned dynamics benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.core_action_conditioned_dynamics_benchmark import (
    build_uwm_core_action_conditioned_dynamics_benchmark,
    validate_uwm_core_action_conditioned_dynamics_benchmark,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "core_action_conditioned_dynamics_benchmark_2026_07_09"
OUTPUT_PATH = OUTPUT_DIR / "uwm_core_action_conditioned_dynamics_benchmark.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)


def main() -> None:
    source_artifact_path = str(FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH.relative_to(REPO_ROOT))
    benchmark = build_uwm_core_action_conditioned_dynamics_benchmark(
        full_admin_graph_planner_replay=_read_json(FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH),
        benchmark_id="uwm-core-action-conditioned-dynamics-benchmark-2026-07-09",
        created_at="2026-07-09T14:00:00Z",
        source_artifact_path=source_artifact_path,
    )
    validation = validate_uwm_core_action_conditioned_dynamics_benchmark(benchmark)
    if validation["valid"] is not True:
        raise SystemExit(
            f"invalid UWM core action-conditioned dynamics benchmark: {validation['errors']}"
        )

    _write_json(OUTPUT_PATH, benchmark)
    manifest = {
        "schema": "uwm.snapshot_manifest.v1",
        "snapshot_id": "uwm_core_action_conditioned_dynamics_benchmark_2026_07_09",
        "created_at": "2026-07-09T14:00:00Z",
        "artifact_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_artifact_path": source_artifact_path,
        "supported_claim": benchmark["supported_claim"],
        "claim_boundary": benchmark["claim_boundary"],
        "full_admin_scope_guard": benchmark["full_admin_scope_guard"],
        "holdout_summary": benchmark["holdout_summary"],
        "action_conditioning_gate": benchmark["action_conditioning_gate"],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "supported_claim": benchmark["supported_claim"],
                "graph_node_count": benchmark["full_admin_scope_guard"][
                    "graph_node_count"
                ],
                "graph_edge_count": benchmark["full_admin_scope_guard"][
                    "graph_edge_count"
                ],
                "available_action_count": benchmark["full_admin_scope_guard"][
                    "available_action_count"
                ],
                "transition_count": benchmark["full_admin_scope_guard"][
                    "transition_count"
                ],
                "holdout_count": benchmark["holdout_summary"]["holdout_count"],
                "observed_policy_outcome_superiority_claim": False,
                "empirical_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
