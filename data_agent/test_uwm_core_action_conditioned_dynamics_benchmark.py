import copy
import json
from pathlib import Path

from data_agent.uwm.core_action_conditioned_dynamics_benchmark import (
    UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA,
    build_uwm_core_action_conditioned_dynamics_benchmark,
    validate_uwm_core_action_conditioned_dynamics_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
FULL_ADMIN_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)
ARTIFACT_PATH = (
    DATA_ROOT
    / "core_action_conditioned_dynamics_benchmark_2026_07_09/uwm_core_action_conditioned_dynamics_benchmark.json"
)

TARGETS = [
    "reward",
    "heat_risk_delta",
    "air_pollution_exposure_delta",
    "service_accessibility_delta",
    "equity_delta",
    "livability_delta",
]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_benchmark(**overrides) -> dict:
    replay = _read_json(FULL_ADMIN_REPLAY_PATH)
    replay.update(overrides)
    return build_uwm_core_action_conditioned_dynamics_benchmark(
        full_admin_graph_planner_replay=replay,
        benchmark_id="uwm-core-action-conditioned-dynamics-benchmark-test",
        created_at="2026-07-09T14:00:00Z",
        source_artifact_path=str(FULL_ADMIN_REPLAY_PATH.relative_to(ROOT)),
    )


def _assert_full_admin_core_claim(benchmark: dict) -> None:
    assert benchmark["schema"] == UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA
    assert benchmark["experiment_scope"] == "full_admin_graph"
    assert benchmark["supported_claim"] == (
        "core_action_conditioned_dynamics_beats_static_and_no_action_baselines"
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

    holdout = benchmark["holdout_summary"]
    assert holdout["holdout_stride"] == 7
    assert holdout["holdout_count"] == 973
    assert holdout["train_count"] == 5844

    assert benchmark["action_conditioning_gate"]["passed"] is True
    assert set(benchmark["target_names"]) == set(TARGETS)

    metrics = benchmark["variant_metrics"]
    full = metrics["full_action_state_graph"]["mae_by_target"]
    train_mean = metrics["train_mean_static"]["mae_by_target"]
    no_action = metrics["no_action_signal"]["mae_by_target"]
    shuffled = metrics["shuffled_action_signal"]["mae_by_target"]
    for target in TARGETS:
        assert full[target] < train_mean[target]
        assert full[target] < no_action[target]
        assert full[target] < shuffled[target]

    validation = validate_uwm_core_action_conditioned_dynamics_benchmark(benchmark)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_core_action_conditioned_dynamics_benchmark_uses_full_admin_holdout_and_beats_ablation_baselines():
    benchmark = _build_benchmark()

    _assert_full_admin_core_claim(benchmark)


def test_core_action_conditioned_dynamics_benchmark_rejects_smoke_sized_transition_scope():
    replay = _read_json(FULL_ADMIN_REPLAY_PATH)
    corrupted = copy.deepcopy(replay)
    corrupted["trajectory_dataset"]["transition_count"] = 36

    benchmark = build_uwm_core_action_conditioned_dynamics_benchmark(
        full_admin_graph_planner_replay=corrupted,
        benchmark_id="uwm-core-action-conditioned-dynamics-benchmark-smoke-reject-test",
        created_at="2026-07-09T14:05:00Z",
        source_artifact_path=str(FULL_ADMIN_REPLAY_PATH.relative_to(ROOT)),
    )

    assert benchmark["full_admin_scope_guard"]["passed"] is False
    assert benchmark["supported_claim"] == "no_core_action_conditioned_dynamics_claim_supported"
    assert benchmark["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert "full_admin_scope_guard_failed" in benchmark["remaining_gates"]
    assert benchmark["observed_policy_outcome_superiority_claim"] is False
    assert benchmark["empirical_superiority_claim"] is False

    validation = validate_uwm_core_action_conditioned_dynamics_benchmark(benchmark)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_core_action_conditioned_dynamics_benchmark_artifact_is_full_scope_and_claim_safe():
    assert ARTIFACT_PATH.exists()
    benchmark = _read_json(ARTIFACT_PATH)

    _assert_full_admin_core_claim(benchmark)
    assert benchmark["benchmark_id"] == "uwm-core-action-conditioned-dynamics-benchmark-2026-07-09"
    assert benchmark["audit_trace"]["source_artifact_path"] == str(
        FULL_ADMIN_REPLAY_PATH.relative_to(ROOT)
    )
