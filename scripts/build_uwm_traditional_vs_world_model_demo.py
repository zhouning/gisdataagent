"""Build same-data traditional-vs-UWM livability demo artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_agent.uwm.traditional_livability_baseline import (
    build_traditional_livability_baseline,
)
from data_agent.uwm.traditional_vs_world_model_demo import (
    build_traditional_vs_world_model_demo,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "traditional_vs_world_model_demo_2026_07_07"
TRADITIONAL_PATH = OUTPUT_DIR / "uwm_traditional_livability_baseline.json"
DEMO_PATH = OUTPUT_DIR / "uwm_traditional_vs_world_model_demo.json"
SUMMARY_PATH = OUTPUT_DIR / "uwm_traditional_vs_world_model_demo_summary.md"
SCENE_PATH = (
    DATA_ROOT
    / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
)
DECISION_PACKAGE_PATH = (
    DATA_ROOT
    / "livability_decision_package_2026_07_07/uwm_livability_decision_package.json"
)


def main() -> None:
    scene = _read_json(SCENE_PATH)
    traditional = build_traditional_livability_baseline(
        baseline_id="uwm-traditional-livability-baseline-2026-07-07",
        created_at="2026-07-07T15:00:00Z",
        multisource_livability_scene=scene,
    )
    demo = build_traditional_vs_world_model_demo(
        demo_id="uwm-traditional-vs-world-model-demo-2026-07-07",
        created_at="2026-07-07T15:10:00Z",
        multisource_livability_scene=scene,
        traditional_livability_baseline=traditional,
        uwm_livability_decision_package=_read_json(DECISION_PACKAGE_PATH),
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(TRADITIONAL_PATH, traditional)
    _write_json(DEMO_PATH, demo)
    SUMMARY_PATH.write_text(_render_markdown(demo), encoding="utf-8")
    print(
        json.dumps(
            {
                "traditional_path": str(TRADITIONAL_PATH.relative_to(REPO_ROOT)),
                "demo_path": str(DEMO_PATH.relative_to(REPO_ROOT)),
                "summary_path": str(SUMMARY_PATH.relative_to(REPO_ROOT)),
                "demo_ready": demo["demo_ready"],
                "traditional_top_priority_units": demo[
                    "traditional_method_output"
                ]["top_priority_units"][:2],
                "uwm_target_units": demo["uwm_output"]["target_units"],
                "uwm_endpoint_advantage": demo["uwm_output"][
                    "endpoint_aligned_advantage_over_static"
                ],
                "uwm_empirical_p_value": demo["uwm_output"][
                    "empirical_p_value_vs_single_action_baselines"
                ],
                "uwm_trained_model_based_rl_ready": demo["uwm_output"][
                    "trained_model_based_rl_ready"
                ],
                "uwm_trained_model_based_rl_advantage": demo["uwm_output"][
                    "trained_model_based_rl_advantage_over_static"
                ],
                "uwm_trained_graph_drl_ready": demo["uwm_output"][
                    "trained_graph_drl_ready"
                ],
                "uwm_trained_graph_drl_advantage": demo["uwm_output"][
                    "trained_graph_drl_advantage_over_static"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _render_markdown(demo: dict[str, Any]) -> str:
    traditional = demo["traditional_method_output"]
    uwm = demo["uwm_output"]
    lines = [
        "# UWM Traditional vs World Model Demo",
        "",
        "## Shared Data Contract",
        "",
        f"- Scene ID: `{demo['shared_data_contract']['scene_id']}`",
        f"- Admin unit count: `{demo['shared_data_contract']['admin_unit_count']}`",
        f"- Same data basis: `{demo['shared_data_contract']['same_data_basis']}`",
        f"- Same livability scenario: `{demo['shared_data_contract']['same_livability_scenario']}`",
        "",
        "## Traditional Method Output",
        "",
        f"- Final output type: `{traditional['final_output_type']}`",
        f"- Top priority units: `{traditional['top_priority_units'][:2]}`",
        f"- Counterfactual output available: `{traditional['counterfactual_output_available']}`",
        "",
        "## UWM Output",
        "",
        f"- Final output type: `{uwm['final_output_type']}`",
        f"- Target units: `{uwm['target_units']}`",
        f"- Counterfactual output available: `{uwm['counterfactual_output_available']}`",
        f"- Endpoint advantage: `{uwm['endpoint_aligned_advantage_over_static']}`",
        f"- Risk-adjusted advantage: `{uwm['risk_adjusted_advantage_over_static']}`",
        f"- Neighbor delta advantage: `{uwm['neighbor_livability_delta_advantage']}`",
        f"- Empirical p-value vs single-action baselines: `{uwm['empirical_p_value_vs_single_action_baselines']}`",
        f"- Trained model-based RL ready: `{uwm['trained_model_based_rl_ready']}`",
        f"- Trained model-based RL algorithm: `{uwm['trained_model_based_rl_algorithm']}`",
        f"- Trained model-based RL advantage over static: `{uwm['trained_model_based_rl_advantage_over_static']}`",
        f"- Trained GraphDQN ready: `{uwm['trained_graph_drl_ready']}`",
        f"- Trained GraphDQN algorithm: `{uwm['trained_graph_drl_algorithm']}`",
        f"- Trained GraphDQN advantage over static: `{uwm['trained_graph_drl_advantage_over_static']}`",
        "",
        "## Capability Delta",
        "",
    ]
    for item in demo["capability_delta"]["uwm_only_outputs"]:
        lines.append(f"- `{item}`")
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            f"- Max claim level: `{demo['claim_boundary']['max_claim_level']}`",
            f"- Observed policy outcome superiority claim: `{demo['observed_policy_outcome_superiority_claim']}`",
            "",
        ]
    )
    return "\n".join(lines)


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
