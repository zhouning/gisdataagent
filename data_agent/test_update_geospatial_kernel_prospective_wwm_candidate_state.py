from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from data_agent.test_run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    START,
    _write_inputs,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_wwm_candidate import (
    ProspectiveWwmCandidateState,
)
from scripts.run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    _json_body,
    compile_outcome_free_prospective_wwm_candidate,
)
from scripts.update_geospatial_kernel_online_expert_pair_matured_state import (
    OBSERVATION_SCHEMA,
)
from scripts.update_geospatial_kernel_prospective_wwm_candidate_state import (
    compile_prospective_wwm_candidate_state_update,
)


def test_sealed_run_advances_v4_and_v5_state_together(tmp_path: Path) -> None:
    issue_path, state_path = _write_inputs(tmp_path)
    output_path = tmp_path / "predictions.json"
    run_report_path = tmp_path / "run-report.json"
    output_body, run_report = compile_outcome_free_prospective_wwm_candidate(
        issue_path=issue_path,
        state_path=state_path,
        output_path=output_path,
        executed_at=START + timedelta(minutes=1),
    )
    output_path.write_bytes(output_body)
    run_report_path.write_bytes(_json_body(run_report))
    predictions = json.loads(output_body)["predictions"]
    retrieved_at = START + timedelta(hours=13)
    observations_path = tmp_path / "observations.json"
    observations_path.write_text(
        json.dumps(
            {
                "schema": OBSERVATION_SCHEMA,
                "system_id": "j_percy_priest",
                "retrieved_at_utc": retrieved_at.isoformat(),
                "source_id": "usgs-approved-test",
                "evidence_level": "authoritative",
                "values_imputed": False,
                "observations": [
                    {
                        "target_support_end_utc": row[
                            "target_support_end_utc"
                        ],
                        "observed_discharge_m3s": (
                            row["physical_open_loop_m3s"] + 5.0
                        ),
                        "observation_available_at_utc": (
                            _time(row["target_support_end_utc"])
                            + timedelta(minutes=30)
                        ).isoformat(),
                        "quality_status": "approved",
                    }
                    for row in predictions
                ],
            }
        ),
        encoding="utf-8",
    )

    state_body, report = compile_prospective_wwm_candidate_state_update(
        prediction_run_report_path=run_report_path,
        prior_state_path=state_path,
        observations_path=observations_path,
        output_state_path=tmp_path / "state-1.json",
        update_time=retrieved_at,
    )
    state = ProspectiveWwmCandidateState.from_dict(json.loads(state_body))

    assert state.physical_residual_state.sample_count_by_horizon() == {
        1: 1,
        3: 1,
        6: 1,
        12: 1,
    }
    assert state.expert_pair_state.sample_count_by_horizon() == {
        1: 1,
        3: 1,
        6: 1,
        12: 1,
    }
    assert report["execution"]["sealed_prediction_run_recomputed_exactly"] is True
    assert report["causal_boundary"]["v4_and_v5_updated_from_same_feedback"] is True
    assert report["causal_boundary"]["raw_observation_retained_in_output_state"] is False
    assert "observed_discharge_m3s" not in str(state.as_dict())


def _time(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
