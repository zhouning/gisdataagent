import math

import pandas as pd

from data_agent.uwm.nyc_action_transfer_paper import build_frozen_evidence_tables


def test_build_frozen_evidence_tables_extracts_complete_v5_result(tmp_path):
    repo_root = tmp_path.parents[0]
    # pytest's tmp path is outside the repository, so resolve from this test file.
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    summary = build_frozen_evidence_tables(repo_root, tmp_path)

    assert summary["completion_status"] == (
        "PASS_V5_BENCHMARK_COMPLETE_ACTION_TRANSFER_NOT_SUPPORTED"
    )
    assert summary["model_count"] == 11
    assert summary["event_count"] == 4
    assert summary["control_count"] == 7
    assert summary["gate_count"] == 8
    assert summary["passed_gate_count"] == 0
    assert summary["all_inventory_hashes_match"] is True
    assert math.isclose(summary["mean_fold_skill"], -0.025239441518234873)

    scores = pd.read_csv(tmp_path / "primary_scores.csv")
    candidate = scores.loc[
        scores["model_id"] == "uwm_dam_gk_action_residual"
    ].iloc[0]
    assert candidate["rank"] == 7
    assert math.isclose(candidate["primary_error"], 0.3683892390054193)
    assert scores.iloc[0]["model_id"] == "effective_date_plus_4w"

    folds = pd.read_csv(tmp_path / "fold_skill.csv")
    assert int(folds["candidate_improves"].sum()) == 2
    assert set(folds["fold_id"]) == {
        "holdout_2015",
        "holdout_2019",
        "holdout_2022",
        "holdout_2025",
    }

