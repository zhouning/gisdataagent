"""Build UWM Track 2 readiness report artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.track2_submission import build_uwm_default_track2_readiness_matrix


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/reports/uwm_track2_readiness_2026_07_06"


def build_track2_readiness_report(
    *,
    repo_root: str | Path,
    output_dir: str | Path,
    current_date: str,
) -> dict[str, str]:
    root = Path(repo_root)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    matrix = build_uwm_default_track2_readiness_matrix(root, current_date=current_date)
    json_path = out / "uwm_track2_readiness_matrix.json"
    markdown_path = out / "uwm_track2_readiness_summary.md"
    _write_json(json_path, matrix)
    markdown_path.write_text(_render_markdown(matrix), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UWM Track 2 readiness report artifacts.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--current-date", default="2026-07-06")
    args = parser.parse_args()

    result = build_track2_readiness_report(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        current_date=args.current_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _render_markdown(matrix: dict[str, Any]) -> str:
    readiness = matrix.get("world_model_evidence_readiness") or {}
    observed = matrix.get("observed_validation_readiness") or {}
    renderer = (readiness.get("architecture_evidence") or {}).get("renderer") or {}
    final_endpoint = (
        (readiness.get("architecture_evidence") or {}).get(
            "final_livability_endpoint_evaluator"
        )
        or {}
    )
    final_decision = (
        (readiness.get("architecture_evidence") or {}).get(
            "final_livability_decision_package"
        )
        or {}
    )
    graph_drl = (
        (readiness.get("architecture_evidence") or {}).get(
            "graph_drl_training"
        )
        or {}
    )
    planner = (readiness.get("architecture_evidence") or {}).get("planner") or {}
    lines = [
        "# UWM Track 2 Readiness Summary",
        "",
        f"- Current date: `{matrix.get('days_to_initial_review_deadline')}` days to initial review deadline",
        f"- Ready for initial submission: `{matrix.get('ready_for_initial_submission')}`",
        f"- System-level superiority summary: `{readiness.get('system_level_superiority_summary')}`",
        f"- Overall claim ceiling: `{readiness.get('overall_claim_ceiling')}`",
        f"- Traditional method comparison ready: `{readiness.get('traditional_method_comparison_ready')}`",
        f"- Bounded final system superiority ready: `{readiness.get('bounded_final_system_superiority_ready')}`",
        f"- Policy outcome superiority ready: `{readiness.get('policy_outcome_superiority_ready')}`",
        f"- Empirical superiority claim: `{readiness.get('empirical_superiority_claim')}`",
        "",
        "## Observed Validation",
        "",
        f"- Temporal state suite ready: `{observed.get('temporal_state_prediction_suite_ready')}`",
        f"- Temporal negative control passed: `{observed.get('temporal_order_negative_control_passed')}`",
        f"- Policy outcome superiority ready: `{observed.get('policy_outcome_superiority_ready')}`",
        "",
        "## Renderer Evidence",
        "",
        f"- Multisource livability scene ready: `{renderer.get('multisource_livability_scene_ready')}`",
        f"- OSM admin mobility crosswalk projected in scene: `{renderer.get('osm_admin_mobility_crosswalk_projected_in_scene')}`",
        f"- OSM assigned road segments in scene: `{renderer.get('osm_assigned_road_segment_count_in_scene')}`",
        f"- OSM service accessibility MAE reduction: `{renderer.get('osm_service_accessibility_mae_reduction')}`",
        f"- Building floor 2.5D morphology ready: `{renderer.get('building_floor_morphology_ready')}`",
        f"- Building floor assigned buildings: `{renderer.get('building_floor_assigned_building_count')}`",
        f"- Building floor total floors: `{renderer.get('building_floor_total_floor_count')}`",
        f"- Building floor max floor: `{renderer.get('building_floor_max_floor')}`",
        f"- Building floor true 3D claim: `{renderer.get('building_floor_true_3d_claim')}`",
        "",
        "## Final Endpoint Evidence",
        "",
        f"- Final livability endpoint suite ready: `{final_endpoint.get('ready')}`",
        f"- Final endpoint count: `{final_endpoint.get('endpoint_count')}`",
        f"- Final endpoint ready count: `{final_endpoint.get('ready_endpoint_count')}`",
        f"- Final endpoint mean relative MAE reduction: `{final_endpoint.get('mean_relative_mae_reduction_vs_best_traditional')}`",
        "",
        "## Final Decision Evidence",
        "",
        f"- Final livability decision package ready: `{final_decision.get('ready')}`",
        f"- Final decision action count: `{final_decision.get('action_count')}`",
        f"- Final decision target unit count: `{final_decision.get('target_unit_count')}`",
        f"- Final decision endpoint advantage: `{final_decision.get('endpoint_aligned_advantage_over_static')}`",
        f"- Final decision best single-action advantage: `{final_decision.get('advantage_vs_best_single_action')}`",
        f"- Final decision single-action win rate: `{final_decision.get('single_action_win_rate')}`",
        f"- Final decision single-action empirical p-value: `{final_decision.get('empirical_p_value_vs_single_action_baselines')}`",
        f"- Final decision endpoint weight sensitivity min advantage: `{final_decision.get('endpoint_weight_sensitivity_min_advantage')}`",
        f"- Final decision risk-adjusted advantage: `{final_decision.get('risk_adjusted_advantage_over_static')}`",
        f"- Final decision neighbor delta advantage: `{final_decision.get('neighbor_livability_delta_advantage')}`",
        f"- Final decision GraphDQN ready: `{final_decision.get('graph_drl_training_ready')}`",
        f"- Final decision GraphDQN advantage: `{final_decision.get('graph_drl_advantage_over_traditional_static')}`",
        "",
        "## GraphDQN Training Evidence",
        "",
        f"- GraphDQN training ready: `{graph_drl.get('ready')}`",
        f"- GraphDQN algorithm: `{graph_drl.get('algorithm')}`",
        f"- GraphDQN is deep RL: `{graph_drl.get('is_deep_rl')}`",
        f"- GraphDQN uses graph message passing: `{graph_drl.get('uses_graph_message_passing')}`",
        f"- GraphDQN value network trained: `{graph_drl.get('policy_or_value_network_trained')}`",
        f"- GraphDQN training samples: `{graph_drl.get('training_sample_count')}`",
        f"- GraphDQN holdout q-return MAE: `{graph_drl.get('q_return_mae')}`",
        f"- GraphDQN train-mean return MAE: `{graph_drl.get('train_mean_return_mae')}`",
        f"- GraphDQN advantage over static: `{graph_drl.get('advantage_over_traditional_static')}`",
        "",
        "## Planner Evidence",
        "",
        f"- Risk-calibrated planner replay ready: `{planner.get('risk_calibrated_planner_replay_ready')}`",
        f"- Endpoint-aligned planner evaluator ready: `{planner.get('endpoint_aligned_planner_evaluator_ready')}`",
        f"- Endpoint-aligned planner advantage: `{planner.get('endpoint_aligned_advantage_over_static')}`",
        f"- Endpoint-aligned planner advantage ratio: `{planner.get('endpoint_aligned_advantage_ratio')}`",
        f"- Spatial spillover planner evaluator ready: `{planner.get('spatial_spillover_planner_evaluator_ready')}`",
        f"- Spatial neighbor benefited units: `{planner.get('planner_neighbor_benefited_unit_count')}` vs static `{planner.get('static_neighbor_benefited_unit_count')}`",
        f"- Spatial neighbor livability delta advantage: `{planner.get('neighbor_livability_delta_advantage')}`",
        "",
        "## Claim Ladder",
        "",
    ]
    for claim in readiness.get("claim_ladder") or []:
        lines.append(
            "- "
            f"`{claim.get('claim')}` | scope `{claim.get('scope')}` | "
            f"level `{claim.get('claim_level')}` | allowed `{claim.get('allowed_in_report')}`"
        )
    lines.extend(
        [
            "",
            "## Forbidden Claims",
            "",
        ]
    )
    for claim in readiness.get("forbidden_claims") or []:
        lines.append(f"- `{claim}`")
    lines.extend(
        [
            "",
            "## Remaining Gates",
            "",
        ]
    )
    for gate in readiness.get("remaining_gates") or []:
        lines.append(f"- `{gate}`")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
