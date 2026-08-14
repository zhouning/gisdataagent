from __future__ import annotations

import pytest

from data_agent.irrigation_hydrodynamic_model import run_dynamic_wave_scenario


PARAMETERS = {
    "supply_drop_percent": 20.0,
    "west_shift_hours": 6,
    "candidate_east_ratio_percent": 45.0,
    "horizon_hours": 6,
}


@pytest.mark.parametrize("mode", ["baseline", "candidateA", "candidateB"])
def test_dynamic_wave_scenario_executes_finite_volume_rollout(mode: str):
    result = run_dynamic_wave_scenario(mode, PARAMETERS)

    assert result["numerical"]["equations"] == "continuity_equation_with_kinematic_wave_storage_closure"
    assert result["numerical"]["scheme"].startswith("exact_linear_storage_route")
    assert result["numerical"]["timestep_count"] > 0
    assert result["numerical"]["state_count"] == 3
    assert result["numerical"]["operator_admitted"] is False
    assert len(result["reaches"]) == 3
    assert all(abs(reach["numerical_volume_residual_m3"]) < 1e-8 for reach in result["reaches"])
    assert result["waterBalance"]["boundaryVolumeM3"] > 0.0
    assert len(result["timeline"]) == 2


def test_action_conditioning_changes_hydrodynamic_outcome():
    baseline = run_dynamic_wave_scenario("baseline", PARAMETERS)
    candidate = run_dynamic_wave_scenario("candidateB", PARAMETERS)

    assert candidate["branchRatio"] != baseline["branchRatio"]
    assert candidate["reaches"][2]["final_storage_m3"] != pytest.approx(
        baseline["reaches"][2]["final_storage_m3"]
    )
    assert candidate["waterBalance"]["junctionUnallocatedVolumeM3"] != pytest.approx(
        baseline["waterBalance"]["junctionUnallocatedVolumeM3"]
    )
