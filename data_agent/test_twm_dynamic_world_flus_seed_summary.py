from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path("scripts/summarize_twm_dynamic_world_flus_seed_runs.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("summarize_twm_dynamic_world_flus_seed_runs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _seed_report(path: Path, *, seed: int, change_fom_delta: float, oa_delta: float) -> Path:
    payload = {
        "schema": "territory_world_model.dynamic_world_admin20_flus_comparison.v1",
        "status": "pass",
        "run_policy": {"flus_seed": seed, "max_iterations": 30},
        "data_profile": {"case_count": 2, "evaluated_case_count": 2},
        "formal_forecast_comparison": {
            "paired_deltas_vs_flus": {
                "twm_independent_transition_forecast_demand": {
                    "paired_case_count": 2,
                    "mean_change_fom_delta": change_fom_delta,
                    "median_change_fom_delta": change_fom_delta,
                    "change_fom_sign_test_p_value": 0.5,
                    "wins_by_change_fom": 2 if change_fom_delta > 0 else 0,
                    "losses_by_change_fom": 0 if change_fom_delta > 0 else 2,
                    "mean_overall_accuracy_delta": oa_delta,
                    "median_overall_accuracy_delta": oa_delta,
                    "overall_accuracy_sign_test_p_value": 0.5,
                    "wins_by_overall_accuracy": 2 if oa_delta > 0 else 0,
                    "losses_by_overall_accuracy": 0 if oa_delta > 0 else 2,
                }
            },
            "ranking_by_mean_change_fom": [
                {
                    "candidate_id": "twm_independent_transition_forecast_demand",
                    "mean_change_fom": 0.07 + change_fom_delta,
                    "mean_overall_accuracy": 0.9 + oa_delta,
                },
                {
                    "candidate_id": "flus_console_direct",
                    "mean_change_fom": 0.07,
                    "mean_overall_accuracy": 0.9,
                },
            ],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_seed_summary_aggregates_direction_and_range(tmp_path):
    module = _load_module()
    paths = [
        _seed_report(tmp_path / "seed1.json", seed=1, change_fom_delta=0.01, oa_delta=-0.02),
        _seed_report(tmp_path / "seed2.json", seed=2, change_fom_delta=0.03, oa_delta=-0.01),
    ]

    summary = module.summarize_seed_reports(paths)

    assert summary["schema"] == "territory_world_model.dynamic_world_flus_seed_stability.v1"
    assert summary["seed_count"] == 2
    assert summary["case_count_per_seed"] == 2
    candidate = summary["candidate_stability"]["twm_independent_transition_forecast_demand"]
    assert candidate["change_fom_delta"]["mean"] == 0.02
    assert candidate["change_fom_delta"]["min"] == 0.01
    assert candidate["change_fom_delta"]["max"] == 0.03
    assert candidate["change_fom_delta"]["positive_seed_count"] == 2
    assert candidate["overall_accuracy_delta"]["negative_seed_count"] == 2
