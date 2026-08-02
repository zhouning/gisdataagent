from __future__ import annotations

from pathlib import Path

import numpy as np

from benchmarks.abu_dhabi_land_use_v1 import run_planning_scenarios as planning
from data_agent.uwm.geospatial_kernel import GEOSPATIAL_KERNEL_RUNTIME_SCHEMA


class _Inputs:
    def __init__(self) -> None:
        state = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
        self.states = {2024: state}
        self.valid = np.ones_like(state, dtype=bool)
        self.hard = {2024: np.zeros_like(state, dtype=bool)}
        self.reference = {}

    def features(self, state: np.ndarray, *, driver_year: int) -> np.ndarray:
        del driver_year
        return np.stack([state.astype(np.float32), np.ones_like(state)])


class _Model:
    classes_ = np.arange(1, 7)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        return np.full((len(features), 6), 1.0 / 6.0, dtype=np.float32)


def _scenario() -> dict[str, object]:
    counts = {str(value): 1 for value in range(1, 7)}
    return {
        "scenario_id": "bounded_test",
        "target_counts_by_year": {str(year): counts.copy() for year in range(2025, 2031)},
    }


def test_lu_planning_six_year_chain_executes_common_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(planning, "AbuDhabiInputs", _Inputs)
    monkeypatch.setattr(planning, "_load_scenarios", lambda: [_scenario()])
    monkeypatch.setattr(
        planning,
        "train_kernel",
        lambda inputs, seed: (_Model(), {"seed": seed, "fixture": True}),
    )
    monkeypatch.setattr(planning, "_write_state", lambda *args, **kwargs: None)

    report = planning.run_geospatial_kernel_scenarios(seeds=(31,), output_root=tmp_path)

    scenario = report["seeds"][0]["scenarios"][0]
    years = scenario["years"]
    assert report["kernel_runtime_schema"] == GEOSPATIAL_KERNEL_RUNTIME_SCHEMA
    assert report["kernel_capabilities"]["adapter_count"] == 1
    assert scenario["kernel_runtime_execution_summary"]["all_expected_steps_completed"] is True
    assert scenario["kernel_runtime_execution_summary"]["status_counts"] == {
        "admitted": 0,
        "projected": 6,
        "rejected": 0,
    }
    assert len(years) == 6
    assert [row["kernel_step"]["source"]["time_id"] for row in years] == [
        "2024",
        "2025",
        "2026",
        "2027",
        "2028",
        "2029",
    ]
    assert [row["kernel_step"]["action"]["target_time"] for row in years] == [
        "2025",
        "2026",
        "2027",
        "2028",
        "2029",
        "2030",
    ]
    assert all(
        row["kernel_step"]["constraint_projection"]["status"] == "projected" for row in years
    )
    assert all(row["allocation"]["hard_exclusion_changed_pixels"] == 0 for row in years)
