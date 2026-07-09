import copy
import json
from pathlib import Path

from data_agent.uwm.core_world_model_policy_improvement_benchmark import (
    UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA,
    build_uwm_core_world_model_policy_improvement_benchmark,
    validate_uwm_core_world_model_policy_improvement_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
FULL_ADMIN_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)
ARTIFACT_PATH = (
    DATA_ROOT
    / "core_world_model_policy_improvement_benchmark_2026_07_09/uwm_core_world_model_policy_improvement_benchmark.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_benchmark(**overrides) -> dict:
    replay = _read_json(FULL_ADMIN_REPLAY_PATH)
    replay.update(overrides)
    return build_uwm_core_world_model_policy_improvement_benchmark(
        full_admin_graph_planner_replay=replay,
        benchmark_id="uwm-core-world-model-policy-improvement-test",
        created_at="2026-07-09T15:00:00Z",
        source_artifact_path=str(FULL_ADMIN_REPLAY_PATH.relative_to(ROOT)),
    )


def _assert_policy_improvement_claim(benchmark: dict) -> None:
    assert benchmark["schema"] == UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA
    assert benchmark["experiment_scope"] == "full_admin_graph"
    assert benchmark["supported_claim"] == (
        "core_world_model_policy_improvement_beats_static_and_action_ablation_baselines"
    )
    assert benchmark["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert benchmark["observed_policy_outcome_superiority_claim"] is False
    assert benchmark["empirical_superiority_claim"] is False

    guard = benchmark["full_admin_scope_guard"]
    assert guard["passed"] is True
    assert guard["graph_node_count"] == 1017
    assert guard["graph_edge_count"] == 7932
    assert guard["available_action_count"] == 1137
    assert guard["transition_count"] == 6817
    assert guard["transition_row_count"] == 6817

    training = benchmark["training_summary"]
    assert training["row_count"] == 6817
    assert training["train_count"] == 5844
    assert training["holdout_count"] == 973
    assert training["holdout_stride"] == 7

    dynamics = benchmark["dynamics_holdout_metrics"]
    full_reward = dynamics["full_action_state_graph"]["mae_by_target"]["reward"]
    train_mean_reward = dynamics["train_mean_static"]["mae_by_target"]["reward"]
    no_action_reward = dynamics["no_action_signal"]["mae_by_target"]["reward"]
    shuffled_reward = dynamics["shuffled_action_signal"]["mae_by_target"]["reward"]
    assert full_reward < train_mean_reward
    assert full_reward < no_action_reward
    assert full_reward < shuffled_reward

    gate = benchmark["policy_improvement_gate"]
    assert gate["passed"] is True
    assert gate["required_policy_baselines"] == [
        "static_single_step_baseline",
        "one_step_world_model_greedy",
        "no_action_signal_world_model_policy",
        "shuffled_action_signal_world_model_policy",
    ]

    policies = benchmark["policy_variant_metrics"]
    expected_gamma = benchmark["policy_improvement_config"]["gamma"]
    for policy in policies.values():
        assert policy["return_convention"] == {
            "discount": "gamma",
            "gamma": expected_gamma,
        }

    improved = policies["world_model_policy_improvement"]
    assert improved["action_count"] == benchmark["policy_improvement_config"]["horizon"]
    assert improved["action_count"] == 2
    improved_return = improved["imagined_cumulative_conservative_return"]
    for baseline_id in gate["required_policy_baselines"]:
        baseline = policies[baseline_id]
        assert improved_return > baseline["imagined_cumulative_conservative_return"]
        comparison = baseline["relative_to_world_model_policy_improvement"]
        assert comparison["world_model_policy_improvement_advantage"] > 0

    assert "multi_step_beam_search" in policies
    assert "multi_step_beam_search" in gate["diagnostic_policy_baselines"]

    validation = validate_uwm_core_world_model_policy_improvement_benchmark(benchmark)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_core_world_model_policy_improvement_uses_full_admin_value_backup_and_beats_required_baselines():
    benchmark = _build_benchmark()

    _assert_policy_improvement_claim(benchmark)


def test_core_world_model_policy_improvement_rejects_smoke_sized_transition_scope():
    replay = _read_json(FULL_ADMIN_REPLAY_PATH)
    corrupted = copy.deepcopy(replay)
    corrupted["trajectory_dataset"]["transition_count"] = 36

    benchmark = build_uwm_core_world_model_policy_improvement_benchmark(
        full_admin_graph_planner_replay=corrupted,
        benchmark_id="uwm-core-world-model-policy-improvement-smoke-reject-test",
        created_at="2026-07-09T15:05:00Z",
        source_artifact_path=str(FULL_ADMIN_REPLAY_PATH.relative_to(ROOT)),
    )

    assert benchmark["full_admin_scope_guard"]["passed"] is False
    assert benchmark["supported_claim"] == "no_core_world_model_policy_improvement_claim_supported"
    assert benchmark["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert "full_admin_scope_guard_failed" in benchmark["remaining_gates"]
    assert benchmark["observed_policy_outcome_superiority_claim"] is False
    assert benchmark["empirical_superiority_claim"] is False

    validation = validate_uwm_core_world_model_policy_improvement_benchmark(benchmark)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_core_world_model_policy_improvement_artifact_is_full_scope_and_claim_safe():
    assert ARTIFACT_PATH.exists()
    benchmark = _read_json(ARTIFACT_PATH)

    _assert_policy_improvement_claim(benchmark)
    assert benchmark["benchmark_id"] == "uwm-core-world-model-policy-improvement-benchmark-2026-07-09"
    assert benchmark["audit_trace"]["source_artifact_path"] == str(
        FULL_ADMIN_REPLAY_PATH.relative_to(ROOT)
    )
