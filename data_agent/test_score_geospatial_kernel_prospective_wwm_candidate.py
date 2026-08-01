from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from data_agent.test_run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    START,
    _issue,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_wwm_candidate import (
    ProspectiveWwmCandidateState,
)
from scripts.run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    _artifact,
    _json_body,
    compile_outcome_free_prospective_wwm_candidate,
)
from scripts.score_geospatial_kernel_online_expert_pair_prospective import (
    ProspectiveOnlineExpertPairScoreConfig,
)
from scripts.score_geospatial_kernel_prospective_wwm_candidate import (
    CAMPAIGN_SCHEMA,
    StrongBaselineScoreRecord,
    _score_strong_baselines,
    compile_prospective_wwm_candidate_score,
)
from scripts.update_geospatial_kernel_online_expert_pair_matured_state import (
    OBSERVATION_SCHEMA,
)


def test_integrated_campaign_uses_frozen_go_no_go_scorer(tmp_path: Path) -> None:
    entries = {}
    evaluation_time = START + timedelta(hours=13)
    for system in ("center_hill", "j_percy_priest"):
        system_dir = tmp_path / system
        system_dir.mkdir()
        prefix = f"{system}-issue-0"
        issue = _issue()
        issue["system_id"] = system
        issue["forecast_id_prefix"] = prefix
        for row in issue["forecasts"]:  # type: ignore[union-attr]
            horizon = row["horizon_hours"]
            row["forecast_id"] = f"{prefix}:{horizon}h"
        issue_path = system_dir / "issue.json"
        state_path = system_dir / "state.json"
        output_path = system_dir / "predictions.json"
        run_report_path = system_dir / "run-report.json"
        observations_path = system_dir / "observations.json"
        issue_path.write_text(json.dumps(issue), encoding="utf-8")
        state = ProspectiveWwmCandidateState.empty(
            system_id=system,
            state_as_of=START - timedelta(hours=1),
        )
        state_path.write_text(json.dumps(state.as_dict()), encoding="utf-8")
        output_body, run_report = (
            compile_outcome_free_prospective_wwm_candidate(
                issue_path=issue_path,
                state_path=state_path,
                output_path=output_path,
                executed_at=START + timedelta(minutes=1),
            )
        )
        output_path.write_bytes(output_body)
        run_report_path.write_bytes(_json_body(run_report))
        rows = json.loads(output_body)["predictions"]
        observations_path.write_text(
            json.dumps(
                {
                    "schema": OBSERVATION_SCHEMA,
                    "system_id": system,
                    "retrieved_at_utc": evaluation_time.isoformat(),
                    "source_id": f"usgs-{system}",
                    "evidence_level": "authoritative",
                    "values_imputed": False,
                    "observations": [
                        {
                            "target_support_end_utc": row[
                                "target_support_end_utc"
                            ],
                            "observed_discharge_m3s": (
                                row["physical_open_loop_m3s"] + 2.0
                            ),
                            "observation_available_at_utc": (
                                _time(row["target_support_end_utc"])
                                + timedelta(minutes=30)
                            ).isoformat(),
                            "quality_status": "approved",
                        }
                        for row in rows
                    ],
                }
            ),
            encoding="utf-8",
        )
        entries[system] = [
            {
                "prediction_run_report": _artifact(
                    run_report_path,
                    run_report_path.read_bytes(),
                ),
                "authoritative_observations": _artifact(
                    observations_path,
                    observations_path.read_bytes(),
                ),
            }
        ]
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(
        json.dumps(
            {
                "schema": CAMPAIGN_SCHEMA,
                "campaign_id": "integrated-test",
                "evaluation_time_utc": evaluation_time.isoformat(),
                "expected_systems": ["center_hill", "j_percy_priest"],
                "systems": entries,
                "values_imputed": False,
            }
        ),
        encoding="utf-8",
    )

    report = compile_prospective_wwm_candidate_score(
        campaign_index_path=campaign_path,
        config=ProspectiveOnlineExpertPairScoreConfig(
            minimum_complete_case_count_per_system_horizon=1
        ),
    )

    assert report["status"] == "prospective_wwm_candidate_score_complete"
    assert report["execution"]["prediction_record_count"] == 8
    assert report["execution"]["every_prediction_run_recomputed_exactly"] is True
    assert report["execution"]["v4_predictions_generated_inside_sealed_runtime"] is True
    assert report["prospective_incremental_value_gate"]["minimum_coverage_passed"] is True
    assert report["prospective_incremental_value_gate"]["passed"] is False
    assert "selector_incremental_value_gate" in report
    strong = report["strong_traditional_baseline_comparison"]
    assert strong["gate"]["minimum_coverage_passed"] is True
    assert strong["gate"]["passed"] is False
    assert report["claim_boundary"]["integrated_promotion_gate_passed"] is False
    assert report["claim_boundary"]["strong_traditional_baseline_gate_passed"] is False
    for system in ("center_hill", "j_percy_priest"):
        for horizon in ("1", "3", "6", "12"):
            result = strong["systems"][system]["horizons"][horizon]
            assert set(result["v5_to_baseline_mse_ratio"]) == {
                "raw_physical",
                "causal_persistence",
                "classical_arx",
            }
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_strong_baseline_gate_can_pass_only_with_per_system_hac_support() -> None:
    records = [
        StrongBaselineScoreRecord(
            system_id=system,
            forecast_id=f"{system}:{horizon}h",
            issue_time=START,
            forecast_horizon_hours=horizon,
            v5_prediction_m3s=100.0,
            raw_physical_m3s=110.0,
            causal_persistence_m3s=120.0,
            classical_arx_m3s=130.0,
            observed_discharge_m3s=100.0,
        )
        for system in ("center_hill", "j_percy_priest")
        for horizon in (1, 3, 6, 12)
    ]

    result = _score_strong_baselines(
        records,
        config=ProspectiveOnlineExpertPairScoreConfig(
            minimum_complete_case_count_per_system_horizon=1
        ),
    )

    assert result["gate"] == {
        "minimum_coverage_passed": True,
        "all_system_horizon_strong_baseline_nonregression_passed": True,
        "every_system_has_hac_supported_improvement_over_best_strong_baseline": True,
        "passed": True,
    }


def _time(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
