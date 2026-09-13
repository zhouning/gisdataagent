"""Build full-admin learned world-model rollout evidence from compact replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.offline_world_model_policy import plan_with_offline_world_model_rollouts


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
SOURCE_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)
OUTPUT_DIR = DATA_ROOT / "learned_world_model_rollout_full_admin_graph_2026_07_08"
OUTPUT_PATH = OUTPUT_DIR / "uwm_full_admin_graph_learned_world_model_rollout.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"


def main() -> None:
    replay = _read_json(SOURCE_REPLAY_PATH)
    _validate_full_admin_replay(replay)

    report = plan_with_offline_world_model_rollouts(
        replay,
        model_id="uwm-full-admin-graph-learned-world-model-rollout-2026-07-08",
        created_at="2026-07-08T13:20:00Z",
        horizon=2,
        beam_width=5,
        holdout_stride=7,
        ridge=0.001,
        uncertainty_penalty=0.5,
    )
    graph_stats = (replay.get("graph_mdp_state") or {}).get("graph_statistics") or {}
    full_guard = replay.get("full_data_guard") or {}
    report["experiment_scope"] = "full_admin_graph"
    report["source_full_admin_graph_planner_replay_path"] = str(
        SOURCE_REPLAY_PATH.relative_to(REPO_ROOT)
    )
    report["full_data_guard"] = {
        "required_scope": "full_admin_graph",
        "required_graph_node_count": 1017,
        "observed_graph_node_count": _int(graph_stats.get("node_count")),
        "source_replay_full_data_guard_passed": full_guard.get("passed") is True,
        "passed": (
            full_guard.get("passed") is True
            and _int(graph_stats.get("node_count")) == 1017
        ),
    }
    report["training_summary"]["source_graph_node_count"] = _int(
        graph_stats.get("node_count")
    )
    report["training_summary"]["source_graph_edge_count"] = _int(
        graph_stats.get("edge_count")
    )
    report["training_summary"]["source_available_action_count"] = _int(
        graph_stats.get("available_action_count")
    )
    if report["full_data_guard"]["passed"] is not True:
        raise SystemExit(f"full-admin learned rollout guard failed: {report['full_data_guard']}")

    if report.get("supported_claim") == (
        "learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
    ):
        report[
            "supported_claim"
        ] = "full_admin_graph_learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
        report["claim_boundary"]["reason"] = (
            "full-admin learned rollout uses compact simulator replay aggregate dynamics "
            "over the 1017-node admin graph; observed policy outcome gates remain open"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, report)
    _write_json(
        MANIFEST_PATH,
        {
            "snapshot_id": "uwm_full_admin_graph_learned_world_model_rollout_2026_07_08",
            "created_at": report["created_at"],
            "schema": "uwm.snapshot_manifest.v1",
            "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
            "source_replay_path": report["source_full_admin_graph_planner_replay_path"],
            "experiment_scope": report["experiment_scope"],
            "full_data_guard": report["full_data_guard"],
            "training_summary": report["training_summary"],
            "holdout_metrics": report["holdout_metrics"],
            "baseline_metrics": report["baseline_metrics"],
            "learned_rollout_planner": report["learned_rollout_planner"],
            "supported_claim": report["supported_claim"],
            "observed_policy_outcome_superiority_claim": report[
                "observed_policy_outcome_superiority_claim"
            ],
            "empirical_superiority_claim": report["empirical_superiority_claim"],
            "remaining_gates": report["remaining_gates"],
        },
    )
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "experiment_scope": report["experiment_scope"],
                "full_data_guard": report["full_data_guard"],
                "transition_count": report["training_summary"]["transition_count"],
                "source_graph_node_count": report["training_summary"][
                    "source_graph_node_count"
                ],
                "source_available_action_count": report["training_summary"][
                    "source_available_action_count"
                ],
                "reward_mae": report["holdout_metrics"]["reward_mae"],
                "train_mean_reward_mae": report["baseline_metrics"][
                    "train_mean_reward_mae"
                ],
                "imagined_advantage_over_static": report[
                    "learned_rollout_planner"
                ]["imagined_advantage_over_static_single_step"],
                "imagined_advantage_over_one_step": report[
                    "learned_rollout_planner"
                ]["imagined_advantage_over_one_step_policy"],
                "supported_claim": report["supported_claim"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _validate_full_admin_replay(replay: dict[str, Any]) -> None:
    graph_stats = (replay.get("graph_mdp_state") or {}).get("graph_statistics") or {}
    if replay.get("experiment_scope") != "full_admin_graph":
        raise SystemExit("source replay experiment_scope must be full_admin_graph")
    if (replay.get("full_data_guard") or {}).get("passed") is not True:
        raise SystemExit("source replay full_data_guard must pass")
    if _int(graph_stats.get("node_count")) != 1017:
        raise SystemExit("source replay must contain 1017 full-admin graph nodes")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    main()
