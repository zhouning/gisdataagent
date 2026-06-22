from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_twm_dongguan_geosos_validation import DEFAULT_INPUT
from scripts.run_twm_dongguan_independent_dynamics import run_independent_dynamics


@pytest.mark.skipif(not DEFAULT_INPUT.exists(), reason="GeoSOS DongGuan 80m tutorial zip is not available")
def test_twm_dongguan_independent_dynamics_beats_markov_change_fom() -> None:
    report = run_independent_dynamics(
        Path(DEFAULT_INPUT),
        asset_dir=None,
        render=False,
    )
    metrics = report["simulator"]["metrics"]
    best_twm = report["simulator"]["best_twm_by_change_fom"]
    best_baseline = report["simulator"]["best_baseline_by_change_fom"]

    assert report["status"] == "pass"
    assert best_twm.startswith("twm_independent_transition")
    assert metrics[best_twm]["change_fom"] > metrics[best_baseline]["change_fom"]
    assert metrics[best_twm]["suitability_violation_count"] == 0
