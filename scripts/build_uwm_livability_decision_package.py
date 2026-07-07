"""Build final UWM livability decision package."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.livability_decision_package import (
    build_uwm_livability_decision_package,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "livability_decision_package_2026_07_07"
OUTPUT_PATH = OUTPUT_DIR / "uwm_livability_decision_package.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"
DATA_CALIBRATED_PLANNER_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
)
LIVABILITY_ENDPOINT_SUITE_PATH = (
    DATA_ROOT
    / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json"
)
ENDPOINT_ALIGNED_PLANNER_EVALUATOR_PATH = (
    DATA_ROOT
    / "endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json"
)
SPATIAL_SPILLOVER_PLANNER_EVALUATOR_PATH = (
    DATA_ROOT
    / "spatial_spillover_planner_evaluator_2026_07_07/uwm_spatial_spillover_planner_evaluator.json"
)
SPATIAL_SPILLOVER_KERNEL_PATH = (
    DATA_ROOT
    / "data_calibrated_spatial_spillover_kernel_2026_07_07/uwm_data_calibrated_spatial_spillover_kernel.json"
)
RL_TRAINING_REPORT_PATH = (
    DATA_ROOT
    / "livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json"
)
LIVABILITY_GRAPH_DRL_TRAINING_REPORT_PATH = (
    DATA_ROOT
    / "livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json"
)


def main() -> None:
    package = build_uwm_livability_decision_package(
        package_id="uwm-livability-decision-package-2026-07-07",
        created_at="2026-07-07T13:30:00Z",
        data_calibrated_planner_replay=_read_json(
            DATA_CALIBRATED_PLANNER_REPLAY_PATH
        ),
        livability_endpoint_suite=_read_json(LIVABILITY_ENDPOINT_SUITE_PATH),
        endpoint_aligned_planner_evaluator=_read_json(
            ENDPOINT_ALIGNED_PLANNER_EVALUATOR_PATH
        ),
        spatial_spillover_planner_evaluator=_read_json(
            SPATIAL_SPILLOVER_PLANNER_EVALUATOR_PATH
        ),
        spatial_spillover_kernel=_read_json(SPATIAL_SPILLOVER_KERNEL_PATH),
        rl_training_report=_read_json(RL_TRAINING_REPORT_PATH),
        graph_drl_training_report=_read_json(LIVABILITY_GRAPH_DRL_TRAINING_REPORT_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, package)
    manifest = {
        "snapshot_id": "uwm_livability_decision_package_2026_07_07",
        "created_at": "2026-07-07T13:30:00Z",
        "package_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_planner_replay_path": str(
            DATA_CALIBRATED_PLANNER_REPLAY_PATH.relative_to(REPO_ROOT)
        ),
        "source_livability_endpoint_suite_path": str(
            LIVABILITY_ENDPOINT_SUITE_PATH.relative_to(REPO_ROOT)
        ),
        "source_endpoint_aligned_planner_evaluator_path": str(
            ENDPOINT_ALIGNED_PLANNER_EVALUATOR_PATH.relative_to(REPO_ROOT)
        ),
        "source_spatial_spillover_planner_evaluator_path": str(
            SPATIAL_SPILLOVER_PLANNER_EVALUATOR_PATH.relative_to(REPO_ROOT)
        ),
        "source_spatial_spillover_kernel_path": str(
            SPATIAL_SPILLOVER_KERNEL_PATH.relative_to(REPO_ROOT)
        ),
        "source_rl_training_report_path": str(
            RL_TRAINING_REPORT_PATH.relative_to(REPO_ROOT)
        ),
        "source_graph_drl_training_report_path": str(
            LIVABILITY_GRAPH_DRL_TRAINING_REPORT_PATH.relative_to(REPO_ROOT)
        ),
        "decision_package_ready": package["decision_package_ready"],
        "action_count": package["action_portfolio"]["action_count"],
        "target_unit_count": package["action_portfolio"]["target_unit_count"],
        "spatial_spillover_kernel_ready": package[
            "spatial_spillover_kernel_evidence"
        ]["ready"],
        "rl_training_ready": package["rl_training_evidence"]["ready"],
        "rl_training_advantage_over_traditional_static": package[
            "rl_training_evidence"
        ]["advantage_over_traditional_static"],
        "graph_drl_training_ready": package["graph_drl_training_evidence"]["ready"],
        "graph_drl_advantage_over_traditional_static": package[
            "graph_drl_training_evidence"
        ]["advantage_over_traditional_static"],
        "supported_claim": package["supported_claim"],
        "observed_policy_outcome_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    comparison = package["comparison_against_traditional_static_heuristic"]
    print(
        json.dumps(
            {
                "package_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "decision_package_ready": package["decision_package_ready"],
                "action_count": package["action_portfolio"]["action_count"],
                "target_units": package["action_portfolio"]["target_units"],
                "endpoint_aligned_advantage_over_static": comparison[
                    "endpoint_aligned_advantage_over_static"
                ],
                "advantage_vs_best_single_action": package[
                    "replay_baseline_suite"
                ]["advantage_vs_best_single_action"],
                "single_action_win_rate": package["replay_baseline_suite"][
                    "single_action_win_rate"
                ],
                "single_action_empirical_p_value": package[
                    "replay_baseline_suite"
                ]["empirical_one_sided_p_value"],
                "endpoint_weight_sensitivity_min_advantage": package[
                    "endpoint_weight_sensitivity"
                ]["min_advantage_over_static"],
                "risk_adjusted_advantage_over_static": comparison[
                    "risk_adjusted_advantage_over_static"
                ],
                "neighbor_livability_delta_advantage": comparison[
                    "neighbor_livability_delta_advantage"
                ],
                "spatial_spillover_kernel_ready": package[
                    "spatial_spillover_kernel_evidence"
                ]["ready"],
                "spatial_spillover_kernel_directional_edge_count": package[
                    "spatial_spillover_kernel_evidence"
                ]["directional_edge_count"],
                "rl_training_ready": package["rl_training_evidence"]["ready"],
                "rl_training_advantage_over_traditional_static": package[
                    "rl_training_evidence"
                ]["advantage_over_traditional_static"],
                "graph_drl_training_ready": package[
                    "graph_drl_training_evidence"
                ]["ready"],
                "graph_drl_algorithm": package["graph_drl_training_evidence"][
                    "algorithm"
                ],
                "graph_drl_advantage_over_traditional_static": package[
                    "graph_drl_training_evidence"
                ]["advantage_over_traditional_static"],
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
