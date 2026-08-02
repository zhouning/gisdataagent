from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_adapter import (
    build_hydrocontrol_dam_gk_dataset,
    inverse_signed_log_state,
    select_hydrocontrol_samples,
)
from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_benchmark import (
    HYDROCONTROL_DAM_GK_BENCHMARK_SCHEMA,
    _new_model,
    _predict,
    run_hydrocontrol_dam_gk_benchmark,
)
from data_agent.uwm.geospatial_kernel import GEOSPATIAL_KERNEL_RUNTIME_SCHEMA


def _synthetic_panel() -> pd.DataFrame:
    rows = []
    systems = ("alpha", "beta", "gamma")
    for year, split in ((2024, "train"), (2025, "development_test")):
        timestamps = pd.date_range(f"{year}-01-01", periods=72, freq="h")
        for system_index, system_id in enumerate(systems):
            release = 100.0 + system_index * 20.0
            flow = 200.0 + system_index * 30.0
            previous_release = None
            previous_flow = None
            for hour_index, timestamp in enumerate(timestamps):
                release = release + np.sin(hour_index / 4.0) * 3.0
                release_change = np.nan if previous_release is None else release - previous_release
                flow = 0.92 * flow + 0.08 * (release * 1.4)
                flow_change = np.nan if previous_flow is None else flow - previous_flow
                rows.append(
                    {
                        "system_id": system_id,
                        "timestamp": timestamp,
                        "effective_release_cfs": release,
                        "downstream_flow_cfs": flow,
                        "effective_release_change_cfs": release_change,
                        "downstream_flow_change_cfs": flow_change,
                        "temporal_split": split,
                        "admitted_current_state_action": True,
                        "dst_transition_day": False,
                    }
                )
                previous_release = release
                previous_flow = flow
    return pd.DataFrame(rows)


def test_hydrocontrol_benchmark_builds_leave_one_system_out_real_action_report():
    report = run_hydrocontrol_dam_gk_benchmark(
        _synthetic_panel(),
        horizons=[3],
        seed=31,
        epochs=1,
        batch_size=64,
    )

    assert report["schema"] == HYDROCONTROL_DAM_GK_BENCHMARK_SCHEMA
    assert report["protocol_id"] == "dam-gk-hydro-h1-h5-v0.1"
    assert report["training"]["seed"] == 31
    assert report["kernel_runtime_schema"] == GEOSPATIAL_KERNEL_RUNTIME_SCHEMA
    assert report["kernel_capabilities"]["adapters"][0]["adapter_id"] == ("dam-gk-runtime-adapter")
    assert len(report["horizons"]) == 1
    horizon = report["horizons"][0]
    assert horizon["horizon_hours"] == 3
    assert len(horizon["folds"]) == 3
    assert {fold["held_out_system"] for fold in horizon["folds"]} == {
        "alpha",
        "beta",
        "gamma",
    }
    for fold in horizon["folds"]:
        assert fold["kernel_runtime_adapter"] == "dam-gk-runtime-adapter"
        assert set(fold["kernel_runtime_execution"]) == {
            "observed_action",
            "no_action_model",
            "zero_action_control",
            "action_shuffle_control",
            "time_shift_control",
        }
        for execution in fold["kernel_runtime_execution"].values():
            assert execution["adapter_id"] == "dam-gk-runtime-adapter"
            assert execution["batch_count"] == len(execution["steps"])
            assert execution["execution_summary"]["all_expected_steps_completed"] is True
            assert execution["execution_summary"]["all_steps_admitted"] is True
            assert all(
                step["constraint_projection"]["status"] == "admitted" for step in execution["steps"]
            )
        assert fold["held_out_system"] not in fold["train_systems"]
        assert fold["train_sample_count"] > fold["test_sample_count"]
        assert set(fold["metrics"]) == {
            "dam_gk",
            "dam_gk_no_action",
            "action_shuffle",
            "temporal_shift_168",
            "persistence",
            "historical_mean",
            "target_only_ridge",
            "action_conditioned_no_graph_ridge",
        }
        assert (
            fold["mechanism_sensitivity"]["mean_absolute_edge_gate_change_observed_vs_zero_action"]
            > 0.0
        )
        assert (
            fold["mechanism_sensitivity"][
                "mean_absolute_prediction_state_change_observed_vs_zero_action"
            ]
            > 0.0
        )
    assert report["claim_boundary"]["real_executed_actions_used"] is True
    assert report["claim_boundary"]["identified_causal_release_effect"] is False
    assert report["claim_boundary"]["h2_h3_h6_evaluated"] is False
    assert report["claim_boundary"]["shared_runtime_contract_executed"] is True


def test_hydrocontrol_runtime_prediction_is_identical_to_direct_forward() -> None:
    dataset = build_hydrocontrol_dam_gk_dataset(
        _synthetic_panel(),
        horizon_hours=3,
        systems=["alpha"],
        temporal_split="development_test",
        target_before="2026-01-01",
    )
    torch.manual_seed(101)
    model = _new_model(use_action_conditioning=True)
    expected_predictions = []
    expected_gates = []
    model.eval()
    with torch.no_grad():
        for start in range(0, dataset.sample_count, 17):
            indices = torch.arange(start, min(start + 17, dataset.sample_count))
            sample = select_hydrocontrol_samples(dataset, indices)
            output = model(sample.batch)
            expected_predictions.append(
                inverse_signed_log_state(
                    output.predicted_state[sample.target_node_index, 0, 0]
                ).clamp(min=0.0, max=1_000_000.0)
            )
            expected_gates.append(output.effective_edge_gate)

    prediction, gates, audit = _predict(model, dataset, 17, parameter_ref="test:direct-equivalence")

    assert torch.equal(prediction, torch.cat(expected_predictions))
    assert torch.equal(gates, torch.cat(expected_gates))
    assert audit["batch_count"] == len(expected_predictions)
    assert audit["execution_summary"]["status_counts"] == {
        "admitted": len(expected_predictions),
        "projected": 0,
        "rejected": 0,
    }
    assert all(
        step["result"]["provenance"]["parameter_ref"] == "test:direct-equivalence"
        for step in audit["steps"]
    )


def test_hydrocontrol_benchmark_is_reproducible_for_fixed_seed():
    arguments = {
        "horizons": [3],
        "seed": 47,
        "epochs": 1,
        "batch_size": 128,
    }
    first = run_hydrocontrol_dam_gk_benchmark(_synthetic_panel(), **arguments)
    second = run_hydrocontrol_dam_gk_benchmark(_synthetic_panel(), **arguments)

    assert first == second
