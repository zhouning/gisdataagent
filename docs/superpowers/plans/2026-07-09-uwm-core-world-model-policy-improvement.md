# UWM Core World-Model Policy Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-admin UWM benchmark proving that a learned action-conditioned world model can drive RL-style finite-horizon policy improvement over static, one-step and action-ablation policy baselines.

**Architecture:** Add a focused policy-improvement benchmark module that trains ridge action-conditioned dynamics from the 6817-transition full-admin replay, runs deterministic value-backup policy improvement over the 1137-action full-admin graph action space, and emits claim-safe policy and ablation metrics. Add a builder script that regenerates the ignored JSON artifact from the real full-admin planner replay.

**Tech Stack:** Python, NumPy, pytest, existing UWM full-admin replay JSON under `data/uwm_public_proxy/chongqing_central`, `/Users/zhouning/gisdataagent/.venv/bin/pytest`.

---

## Execution Setup

Before Task 1, execute in an isolated worktree. Do not implement on the dirty main checkout.

Use:

```bash
cd /Users/zhouning/gisdataagent
git worktree add .worktrees/uwm-core-world-model-policy-improvement -b feat/uwm-core-world-model-policy-improvement
cd .worktrees/uwm-core-world-model-policy-improvement
mkdir -p data/uwm_public_proxy .tmp
cp -R /Users/zhouning/gisdataagent/data/uwm_public_proxy/chongqing_central data/uwm_public_proxy/
cp -R /Users/zhouning/gisdataagent/.tmp/twm_standard_1128 .tmp/
```

Run the baseline suite before editing:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_*.py -q
```

Expected: all UWM tests pass before new work begins.

---

## File Map

- Create `data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py`
  - Defines the claim contract against the real full-admin replay.
  - Checks scope guard, dynamics holdout, policy-improvement gate, no-claim downgrade, and generated artifact.

- Create `data_agent/uwm/core_world_model_policy_improvement_benchmark.py`
  - Trains action-conditioned ridge dynamics variants.
  - Runs finite-horizon value-backup policy improvement.
  - Evaluates static, one-step, no-action, shuffled-action and beam-search policy variants under claim-safe rules.
  - Validates the JSON contract.

- Create `scripts/build_uwm_core_world_model_policy_improvement_benchmark.py`
  - Reads the full-admin planner replay.
  - Writes benchmark JSON and snapshot manifest under ignored `data/`.

---

### Task 1: Failing Policy-Improvement Contract Tests

**Files:**
- Create: `data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py`

- [ ] **Step 1: Write the failing tests**

Create `data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py` with this structure:

```python
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
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py -q
```

Expected: FAIL during collection with:

```text
ModuleNotFoundError: No module named 'data_agent.uwm.core_world_model_policy_improvement_benchmark'
```

- [ ] **Step 3: Commit tests**

```bash
git add data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py
git commit -m "test: define UWM core policy improvement benchmark contract"
```

---

### Task 2: Policy-Improvement Benchmark Module

**Files:**
- Create: `data_agent/uwm/core_world_model_policy_improvement_benchmark.py`
- Test: `data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py`

- [ ] **Step 1: Implement the module**

Create `data_agent/uwm/core_world_model_policy_improvement_benchmark.py`.

Required public API constants and signatures:

```python
UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA = (
    "uwm.core_world_model_policy_improvement_benchmark.v1"
)
```

Implement:

- `build_uwm_core_world_model_policy_improvement_benchmark(*, full_admin_graph_planner_replay: dict[str, Any], benchmark_id: str, created_at: str, source_artifact_path: str | None = None, horizon: int = 2, gamma: float = 0.9, beam_width: int = 8, holdout_stride: int = 7, ridge: float = 0.001, uncertainty_penalty: float = 0.5, shuffle_offset: int = 137) -> dict[str, Any]`
- `validate_uwm_core_world_model_policy_improvement_benchmark(benchmark: dict[str, Any]) -> dict[str, Any]`

Required imports:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .offline_world_model_policy import (
    FEATURE_NAMES,
    TARGET_NAMES,
    _degree_by_unit,
    _fit_ridge_multi_output,
    _holdout_indices,
    _mae_by_target,
    _node_features_by_unit,
    _training_row,
)
```

Use these constants:

```python
_SUPPORTED_CLAIM = (
    "core_world_model_policy_improvement_beats_static_and_action_ablation_baselines"
)
_NO_CLAIM = "no_core_world_model_policy_improvement_claim_supported"

_REQUIRED_FULL_ADMIN_COUNTS = {
    "graph_node_count": 1017,
    "graph_edge_count": 7932,
    "available_action_count": 1137,
    "transition_count": 6817,
    "transition_row_count": 6817,
}

_ACTION_SIGNAL_FEATURES = {
    "intensity",
    "mask_heat_risk",
    "mask_air_pollution",
    "mask_service_gap",
}
```

Required top-level output fields:

```python
{
    "schema": UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA,
    "benchmark_id": benchmark_id,
    "created_at": created_at,
    "experiment_scope": "full_admin_graph",
    "source_report_schema": full_admin_graph_planner_replay.get("schema"),
    "feature_names": list(FEATURE_NAMES),
    "target_names": list(TARGET_NAMES),
    "full_admin_scope_guard": scope_guard,
    "training_summary": training_summary,
    "dynamics_holdout_metrics": dynamics_holdout_metrics,
    "policy_improvement_config": policy_improvement_config,
    "policy_variant_metrics": policy_variant_metrics,
    "policy_improvement_gate": policy_improvement_gate,
    "supported_claim": _SUPPORTED_CLAIM if ready else _NO_CLAIM,
    "claim_boundary": {
        "max_claim_level": "bounded_support" if ready else "not_for_claim",
        "reason": "same-scene full-admin learned world-model finite-horizon policy improvement; observed policy outcome gates remain open",
    },
    "remaining_gates": remaining_gates,
    "audit_trace": audit_trace,
    "observed_policy_outcome_superiority_claim": False,
    "empirical_superiority_claim": False,
}
```

Implementation requirements:

- Build `feature_matrix` and `targets` from `trajectory_dataset.transitions`.
- Use `_holdout_indices(len(transitions), holdout_stride)`; with 6817 rows and stride 7 this must produce 973 holdout rows and 5844 train rows.
- Fit dynamics coefficients for:
  - `full_action_state_graph`;
  - `no_action_signal`;
  - `shuffled_action_signal`.
- Include `train_mean_static` holdout MAE as a dynamics baseline.
- For `no_action_signal`, zero all feature columns whose name starts with `action_`, plus `intensity`, `mask_heat_risk`, `mask_air_pollution`, and `mask_service_gap`.
- For `shuffled_action_signal`, roll the same columns by `shuffle_offset=137`.
- Compute reward residual standard deviation by action type on train rows and a global reward residual std for conservative scoring.
- Use conservative step score:

```python
conservative_reward = predicted_reward - uncertainty_penalty * residual_std_for_action_type
discounted_conservative_return += (gamma ** step_index) * conservative_reward
```

- Use predicted dynamics to update only target-unit latent state fields:
  - `heat_risk`;
  - `air_pollution_exposure`;
  - `service_accessibility`;
  - `equity`;
  - `livability`.
- Clamp each latent state field to `[0.0, 1.0]`.
- Use the full real `graph_mdp_state.available_actions` list as the candidate action inventory.
- Prevent repeated actions within a selected sequence.

Required private helpers and return contracts:

```python
@dataclass(frozen=True)
class DynamicsVariant:
    variant_id: str
    coefficients: np.ndarray
    train_predictions: np.ndarray
    holdout_predictions: np.ndarray
    train_residuals: np.ndarray
    holdout_mae_by_target: dict[str, float]
    reward_residual_std_by_action_type: dict[str, float]
    global_reward_residual_std: float
```

Implement these helpers:

- `_training_matrices(graph_state: dict[str, Any], transitions: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]`
  - Returns feature and target matrices using `_training_row`.
- `_fit_dynamics_variant(variant_id: str, x_train: np.ndarray, y_train: np.ndarray, x_holdout: np.ndarray, y_holdout: np.ndarray, ridge: float, train_rows: list[dict[str, Any]]) -> DynamicsVariant`
  - Returns coefficients, train/holdout predictions, MAE and reward residual uncertainty.
- `_policy_improvement_sequence(actions: list[dict[str, Any]], initial_state_features: dict[str, dict[str, float]], degree_by_unit: dict[str, int], node_count: int, dynamics: DynamicsVariant, horizon: int, gamma: float, beam_width: int, uncertainty_penalty: float) -> dict[str, Any]`
  - Returns the best value-backup action sequence and imagined steps.
- `_one_step_greedy_sequence(actions: list[dict[str, Any]], initial_state_features: dict[str, dict[str, float]], degree_by_unit: dict[str, int], node_count: int, dynamics: DynamicsVariant, uncertainty_penalty: float) -> dict[str, Any]`
  - Returns the best immediate conservative reward action as a one-step sequence.
- `_static_single_step_sequence(static_action: dict[str, Any], initial_state_features: dict[str, dict[str, float]], degree_by_unit: dict[str, int], node_count: int, dynamics: DynamicsVariant, uncertainty_penalty: float) -> dict[str, Any]`
  - Returns the source static action evaluated under full learned dynamics.
- `_beam_search_sequence(actions: list[dict[str, Any]], initial_state_features: dict[str, dict[str, float]], degree_by_unit: dict[str, int], node_count: int, dynamics: DynamicsVariant, horizon: int, beam_width: int, uncertainty_penalty: float) -> dict[str, Any]`
  - Returns a diagnostic multi-step beam-search sequence.
- `_evaluate_fixed_sequence(actions: list[dict[str, Any]], initial_state_features: dict[str, dict[str, float]], degree_by_unit: dict[str, int], node_count: int, dynamics: DynamicsVariant, gamma: float, uncertainty_penalty: float) -> dict[str, Any]`
  - Returns predicted and conservative discounted returns for a fixed action list.
- `_imagine_action_step(action: dict[str, Any], state_features: dict[str, dict[str, float]], degree_by_unit: dict[str, int], node_count: int, dynamics: DynamicsVariant, step_index: int, uncertainty_penalty: float) -> tuple[dict[str, Any], dict[str, dict[str, float]]]`
  - Returns one imagined step plus updated latent state.
- `_policy_improvement_gate(policy_variant_metrics: dict[str, Any], dynamics_holdout_metrics: dict[str, Any], scope_guard: dict[str, Any], horizon: int) -> dict[str, Any]`
  - Returns pass/fail rows for required policy baselines.

The `policy_variant_metrics` keys must be:

```python
[
    "world_model_policy_improvement",
    "static_single_step_baseline",
    "one_step_world_model_greedy",
    "multi_step_beam_search",
    "no_action_signal_world_model_policy",
    "shuffled_action_signal_world_model_policy",
]
```

Each policy metric row must include:

```python
{
    "policy_variant": policy_variant_id,
    "dynamics_variant": dynamics_variant_id,
    "action_count": len(action_sequence),
    "action_sequence": action_sequence,
    "imagined_steps": imagined_steps,
    "imagined_cumulative_predicted_return": round(predicted_return, 9),
    "imagined_cumulative_conservative_return": round(conservative_return, 9),
    "relative_to_world_model_policy_improvement": {
        "world_model_policy_improvement_advantage": round(
            improved_return - this_return, 9
        )
    },
}
```

Gate logic:

```python
required_policy_baselines = [
    "static_single_step_baseline",
    "one_step_world_model_greedy",
    "no_action_signal_world_model_policy",
    "shuffled_action_signal_world_model_policy",
]
diagnostic_policy_baselines = ["multi_step_beam_search"]
passed = (
    scope_guard["passed"] is True
    and full_reward_mae < train_mean_reward_mae
    and full_reward_mae < no_action_reward_mae
    and full_reward_mae < shuffled_reward_mae
    and improved_action_count == horizon
    and all(improved_return > policy_variant_metrics[baseline]["imagined_cumulative_conservative_return"] for baseline in required_policy_baselines)
)
```

Validation requirements:

- Reject unknown `supported_claim`.
- Supported claim requires:
  - scope guard pass;
  - policy-improvement gate pass;
  - claim boundary `bounded_support`;
  - observed and empirical flags false.
- No-claim requires claim boundary `not_for_claim`.

- [ ] **Step 2: Verify object-level GREEN**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest \
  data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py::test_core_world_model_policy_improvement_uses_full_admin_value_backup_and_beats_required_baselines \
  data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py::test_core_world_model_policy_improvement_rejects_smoke_sized_transition_scope \
  -q
```

Expected: PASS for the two object-level tests.

- [ ] **Step 3: Commit module**

```bash
git add data_agent/uwm/core_world_model_policy_improvement_benchmark.py
git commit -m "feat: benchmark UWM world-model policy improvement"
```

---

### Task 3: Artifact Builder

**Files:**
- Create: `scripts/build_uwm_core_world_model_policy_improvement_benchmark.py`
- Test: `data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py`

- [ ] **Step 1: Implement builder script**

Create `scripts/build_uwm_core_world_model_policy_improvement_benchmark.py`:

```python
"""Build the full-admin UWM core world-model policy improvement benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from data_agent.uwm.core_world_model_policy_improvement_benchmark import (
    build_uwm_core_world_model_policy_improvement_benchmark,
    validate_uwm_core_world_model_policy_improvement_benchmark,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data/uwm_public_proxy/chongqing_central"
OUTPUT_DIR = DATA_ROOT / "core_world_model_policy_improvement_benchmark_2026_07_09"
OUTPUT_PATH = OUTPUT_DIR / "uwm_core_world_model_policy_improvement_benchmark.json"
MANIFEST_PATH = OUTPUT_DIR / "snapshot_manifest.json"

FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH = (
    DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
)


def main() -> None:
    source_artifact_path = str(FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH.relative_to(REPO_ROOT))
    benchmark = build_uwm_core_world_model_policy_improvement_benchmark(
        full_admin_graph_planner_replay=_read_json(FULL_ADMIN_GRAPH_PLANNER_REPLAY_PATH),
        benchmark_id="uwm-core-world-model-policy-improvement-benchmark-2026-07-09",
        created_at="2026-07-09T15:00:00Z",
        source_artifact_path=source_artifact_path,
    )
    validation = validate_uwm_core_world_model_policy_improvement_benchmark(benchmark)
    if validation["valid"] is not True:
        raise SystemExit(
            f"invalid UWM core world-model policy improvement benchmark: {validation['errors']}"
        )

    _write_json(OUTPUT_PATH, benchmark)
    manifest = {
        "schema": "uwm.snapshot_manifest.v1",
        "snapshot_id": "uwm_core_world_model_policy_improvement_benchmark_2026_07_09",
        "created_at": "2026-07-09T15:00:00Z",
        "artifact_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "source_artifact_path": source_artifact_path,
        "supported_claim": benchmark["supported_claim"],
        "claim_boundary": benchmark["claim_boundary"],
        "full_admin_scope_guard": benchmark["full_admin_scope_guard"],
        "training_summary": benchmark["training_summary"],
        "policy_improvement_config": benchmark["policy_improvement_config"],
        "policy_improvement_gate": benchmark["policy_improvement_gate"],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }
    _write_json(MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
                "supported_claim": benchmark["supported_claim"],
                "graph_node_count": benchmark["full_admin_scope_guard"]["graph_node_count"],
                "graph_edge_count": benchmark["full_admin_scope_guard"]["graph_edge_count"],
                "available_action_count": benchmark["full_admin_scope_guard"]["available_action_count"],
                "transition_count": benchmark["full_admin_scope_guard"]["transition_count"],
                "holdout_count": benchmark["training_summary"]["holdout_count"],
                "policy_improvement_gate_passed": benchmark["policy_improvement_gate"]["passed"],
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
```

- [ ] **Step 2: Generate artifact from real full-admin replay**

Run:

```bash
env PYTHONPATH=. /Users/zhouning/gisdataagent/.venv/bin/python scripts/build_uwm_core_world_model_policy_improvement_benchmark.py
```

Expected output includes:

```text
"graph_node_count": 1017
"graph_edge_count": 7932
"available_action_count": 1137
"transition_count": 6817
"holdout_count": 973
"policy_improvement_gate_passed": true
"supported_claim": "core_world_model_policy_improvement_beats_static_and_action_ablation_baselines"
```

- [ ] **Step 3: Run focused tests including artifact**

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py -q
```

Expected: all focused tests pass.

- [ ] **Step 4: Commit script**

```bash
git add scripts/build_uwm_core_world_model_policy_improvement_benchmark.py
git commit -m "feat: regenerate UWM core policy improvement benchmark"
```

Do not force-add ignored `data/` artifacts unless explicitly requested.

---

### Task 4: Full Verification And Evidence

**Files:**
- No new source files expected.

- [ ] **Step 1: Run full UWM suite**

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_*.py -q
```

Expected: all UWM tests pass.

- [ ] **Step 2: Extract artifact evidence**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -c "import json; from pathlib import Path; p=Path('data/uwm_public_proxy/chongqing_central/core_world_model_policy_improvement_benchmark_2026_07_09/uwm_core_world_model_policy_improvement_benchmark.json'); b=json.loads(p.read_text(encoding='utf-8')); print(json.dumps({'supported_claim': b['supported_claim'], 'claim_boundary': b['claim_boundary']['max_claim_level'], 'full_admin_scope_guard': {k: b['full_admin_scope_guard'][k] for k in ['passed','graph_node_count','graph_edge_count','available_action_count','transition_count','transition_row_count']}, 'training_summary': b['training_summary'], 'policy_improvement_config': b['policy_improvement_config'], 'policy_improvement_gate': b['policy_improvement_gate'], 'policy_returns': {k: v['imagined_cumulative_conservative_return'] for k, v in b['policy_variant_metrics'].items()}, 'observed_policy_outcome_superiority_claim': b['observed_policy_outcome_superiority_claim'], 'empirical_superiority_claim': b['empirical_superiority_claim']}, ensure_ascii=False, indent=2, sort_keys=True))"
```

Report:

- focused benchmark test count;
- full UWM suite count;
- full-admin counts;
- dynamics reward MAE for full, train mean, no-action and shuffled-action;
- policy-improvement conservative return versus static, one-step, no-action and shuffled-action baselines;
- claim boundary remains bounded support only;
- observed policy and empirical superiority remain false.

- [ ] **Step 3: Finish branch**

Use `superpowers:finishing-a-development-branch`.

If the user chooses local merge:

1. Merge `feat/uwm-core-world-model-policy-improvement` back to `feat/v12-extensible-platform`.
2. Regenerate ignored artifact in the main worktree:

```bash
env PYTHONPATH=. /Users/zhouning/gisdataagent/.venv/bin/python scripts/build_uwm_core_world_model_policy_improvement_benchmark.py
```

3. Re-run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/pytest data_agent/test_uwm_*.py -q
```

4. Remove the implementation worktree and delete the merged branch.
