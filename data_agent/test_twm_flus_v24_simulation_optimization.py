from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_twm_flus_v24_simulation_optimization import (
    DEFAULT_V24_ZIP,
    run_twm_flus_v24_simulation_optimization,
)


@pytest.mark.skipif(not DEFAULT_V24_ZIP.exists(), reason="GeoSOS-FLUS V2.4 sample zip is not available")
def test_twm_flus_v24_independent_logit_candidate_exceeds_official_change_fom() -> None:
    report = run_twm_flus_v24_simulation_optimization(
        Path(DEFAULT_V24_ZIP),
        asset_dir=None,
        render=False,
    )
    metrics = report["simulator"]["metrics"]
    best_official = report["simulator"]["best_official_flus_by_change_fom"]
    independent = "twm_independent_logit_change_seeking"

    assert report["status"] == "pass"
    assert report["simulator"]["candidate_metadata"][independent]["uses_flus_probability"] is False
    assert metrics[independent]["change_fom"] > metrics[best_official]["change_fom"]
    assert metrics[independent]["full_raster_total_demand_abs_error"] == 0
    assert metrics[independent]["restricted_change_violation_count"] == 0
    assert metrics[independent]["cost_matrix_violation_count"] == 0
