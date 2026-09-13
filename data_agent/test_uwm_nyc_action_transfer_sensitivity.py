import math
from pathlib import Path

import pandas as pd

from data_agent.uwm.nyc_action_transfer_sensitivity import build_metric_sensitivity


def test_metric_sensitivity_reproduces_formal_result_without_retuning(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    summary = build_metric_sensitivity(repo_root, tmp_path)

    assert summary["formal_metric_reproduced"] is True
    assert summary["specification_count"] == 7
    assert summary["calibrated_prediction_interval_ready"] is False

    scores = pd.read_csv(tmp_path / "metric_sensitivity_scores.csv")
    formal = scores.loc[
        scores["specification"].eq("reported_horizons_all_zones")
        & scores["metric_id"].eq("equal_event_normalized_mae")
        & scores["model_id"].eq("uwm_dam_gk_action_residual")
    ].iloc[0]
    assert math.isclose(formal["score"], 0.3683892390054193)

    horizons = pd.read_csv(tmp_path / "horizon_profile.csv")
    assert len(horizons) == 48
    assert set(horizons["horizon_week"]) == set(range(1, 13))

    targets = pd.read_csv(tmp_path / "target_profile.csv")
    assert len(targets) == 16

    audit = (tmp_path / "uncertainty_readiness.json").read_text(encoding="utf-8")
    assert '"calibrated_prediction_interval_ready": false' in audit
    assert "cannot be calibrated" in audit
