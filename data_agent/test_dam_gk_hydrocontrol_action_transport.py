from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_action_transport import (
    HYDROCONTROL_ACTION_TRANSPORT_SCHEMA,
    HydroControlActionTransportKernel,
)
from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_action_transport_benchmark import (
    HYDROCONTROL_ACTION_TRANSPORT_BENCHMARK_SCHEMA,
    evaluate_action_transport_kernel,
    prepare_action_transport_panel,
)


def _panel() -> pd.DataFrame:
    rows = []
    for year in (2022, 2023, 2024, 2025):
        for system_index, system_id in enumerate(("alpha", "beta", "gamma")):
            release = 100.0 + system_index * 10.0
            flow = 200.0 + system_index * 20.0
            previous_release = None
            for index, timestamp in enumerate(
                pd.date_range(f"{year}-01-01", periods=96, freq="h")
            ):
                release += np.sin(index / 3.0) * 4.0
                action_change = (
                    np.nan
                    if previous_release is None
                    else release - previous_release
                )
                flow = 0.95 * flow + 0.05 * release * 1.5
                rows.append(
                    {
                        "system_id": system_id,
                        "timestamp": timestamp,
                        "effective_release_change_cfs": action_change,
                        "downstream_flow_cfs": flow,
                        "admitted_current_state_action": True,
                        "dst_transition_day": False,
                    }
                )
                previous_release = release
    return pd.DataFrame(rows)


def test_action_transport_kernel_has_structural_action_sensitive_gate():
    action = np.array([-20.0, -5.0, 0.0, 5.0, 20.0])
    outcome = action * 2.0
    kernel = HydroControlActionTransportKernel.fit(
        action_change_cfs=action,
        future_flow_change_cfs=outcome,
    )
    gate = kernel.edge_gate(action)
    prediction = kernel.predict(
        current_flow_cfs=np.full(5, 100.0),
        action_change_cfs=action,
    )

    assert kernel.to_dict()["schema"] == HYDROCONTROL_ACTION_TRANSPORT_SCHEMA
    assert gate[2] == 0.0
    assert gate[0] > gate[1] > gate[2]
    assert gate[4] > gate[3] > gate[2]
    assert prediction[0] < 100.0 < prediction[4]


def test_action_transport_kernel_fails_closed_without_action_variation():
    with pytest.raises(ValueError, match="nonzero_training_action_required"):
        HydroControlActionTransportKernel.fit(
            action_change_cfs=np.zeros(5),
            future_flow_change_cfs=np.ones(5),
        )


def test_action_transport_panel_resolves_exact_future_timestamp():
    panel = _panel()
    missing = (panel["system_id"] == "alpha") & (
        panel["timestamp"] == pd.Timestamp("2022-01-01T03:00:00")
    )
    prepared = prepare_action_transport_panel(
        panel.loc[~missing], horizon_hours=3
    )
    row = prepared.loc[
        (prepared["system_id"] == "alpha")
        & (prepared["timestamp"] == pd.Timestamp("2022-01-01T00:00:00"))
    ].iloc[0]

    assert pd.isna(row["target_flow_cfs"])


def test_action_transport_benchmark_uses_only_prior_years_for_training():
    report = evaluate_action_transport_kernel(
        _panel(), evaluation_year=2024, horizons=[3], seed=31
    )

    assert report["schema"] == HYDROCONTROL_ACTION_TRANSPORT_BENCHMARK_SCHEMA
    assert report["role"] == "internal_model_selection"
    assert len(report["horizons"][0]["folds"]) == 3
    for fold in report["horizons"][0]["folds"]:
        assert fold["held_out_system"] not in fold["train_systems"]
        assert fold["train_sample_count"] > fold["test_sample_count"]
        assert fold["mechanism_sensitivity"][
            "mean_absolute_edge_gate_change_observed_vs_zero_action"
        ] > 0.0
    assert report["claim_boundary"]["identified_causal_release_effect"] is False


def test_action_transport_benchmark_is_reproducible():
    first = evaluate_action_transport_kernel(
        _panel(), evaluation_year=2024, horizons=[3], seed=47
    )
    second = evaluate_action_transport_kernel(
        _panel(), evaluation_year=2024, horizons=[3], seed=47
    )

    assert first == second
