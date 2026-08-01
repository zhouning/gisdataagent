import json
from datetime import UTC, datetime

import pytest

from scripts import freeze_geospatial_kernel_horizon_selector_replication_design as freeze


def test_replication_design_removes_self_comparison_without_reopening_candidate() -> None:
    report = freeze.compile_replication_design(
        frozen_at=datetime(2026, 8, 1, tzinfo=UTC)
    )

    assert report["status"] == "design_frozen_awaiting_unused_window_adjudication"
    assert report["prior_candidate_boundary"] == {
        "candidate_id": "distance_localized_horizon_policy_v1",
        "prior_disposition": "rejected_for_promotion",
        "prior_disposition_final": True,
        "prior_candidate_reopened": False,
        "successful_replication_would_reverse_prior_rejection": False,
        "scientific_role": (
            "mechanism-level replication only; not a replacement score for "
            "the rejected candidate"
        ),
    }
    validity = report["comparison_validity"]
    assert validity["former_three_hour_self_comparison_removed"] is True
    assert validity["candidate_differing_horizons_by_uniform_mode"] == {
        "nominal": [1, 3, 6],
        "outlet_only_observation_update": [1, 3, 12],
        "linear_distance_localized_mainstem_update": [3, 6, 12],
        "quadratic_distance_localized_mainstem_update": [1, 6, 12],
    }
    assert report["scoring_design"]["per_horizon_strict_superiority_gate"] is False
    assert report["scoring_design"]["cross_system_compensation_permitted"] is False
    assert report["scoring_design"][
        "cross_horizon_aggregation_within_system_permitted"
    ]


def test_design_selects_no_window_and_authorizes_no_data_access() -> None:
    report = freeze.compile_replication_design()

    adjudication = report["window_adjudication_requirements"]
    assert adjudication["window_selected"] is False
    assert adjudication["window_start_utc"] is None
    assert adjudication["window_end_utc"] is None
    assert adjudication["nwm_time_chunk_index"] is None
    assert report["data_access_boundary"] == {
        "new_window_url_compiled": False,
        "new_window_request_count": 0,
        "new_window_values_requested": False,
        "new_window_values_loaded": False,
        "current_exposed_holdout_used_to_select_new_window": False,
    }
    assert report["next_gate"]["automatic_execution_authorized"] is False
    assert report["claim_boundary"]["replication_protocol_frozen"] is False


def test_design_rejects_nonfinal_candidate_disposition(tmp_path) -> None:
    payload = json.loads(freeze.DEFAULT_DISPOSITION.read_bytes())
    payload["decision"]["final_for_candidate_id"] = False
    path = tmp_path / "nonfinal-disposition.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="horizon_selector_design_input_disposition_invalid",
    ):
        freeze.compile_replication_design(disposition_path=path)
