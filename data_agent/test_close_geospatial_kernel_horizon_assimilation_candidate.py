import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import close_geospatial_kernel_horizon_assimilation_candidate as close


def test_failed_candidate_is_closed_and_runtime_is_unreachable() -> None:
    report = close.compile_disposition(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC)
    )

    assert report["status"] == (
        "candidate_rejected_after_verified_historical_holdout"
    )
    assert report["decision"] == {
        "disposition": "rejected_for_promotion",
        "final_for_candidate_id": True,
        "formal_support_gate_passed": False,
        "passed_group_count": 3,
        "failed_group_count": 5,
        "structural_self_comparison_groups": [
            "center_hill:3h",
            "j_percy_priest:3h",
        ],
        "reason_codes": [
            "formal_noncompensatory_support_gate_failed",
            "performance_not_stable_across_both_systems_and_all_horizons",
            "three_hour_candidate_equals_fixed_quadratic_comparator",
        ],
    }
    containment = report["runtime_containment"]
    assert containment["production_runtime_reachable"] is False
    assert containment["production_entrypoint_scan"][
        "no_production_entrypoint_reference_found"
    ]
    assert containment["production_entrypoint_scan"]["matching_source_files"] == []
    assert report["post_score_controls"]["same_candidate_id_reopen_permitted"] is False
    assert report["claim_boundary"]["superiority_claim_supported"] is False


def test_disposition_rejects_score_not_bound_by_independent_verification(
    tmp_path,
) -> None:
    payload = json.loads(close.DEFAULT_SCORE.read_bytes())
    payload["aggregate_gate"]["candidate_support_gate_passed"] = True
    path = tmp_path / "tampered-score.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="horizon_candidate_disposition_failed_gate_not_verified",
    ):
        close.compile_disposition(score_path=path)


def test_runtime_audit_fails_closed_on_any_matching_entrypoint() -> None:
    this_file = Path(__file__).resolve()

    with pytest.raises(
        ValueError,
        match="horizon_candidate_disposition_runtime_reference_found",
    ):
        close._audit_runtime_reachability(
            scan_roots=(),
            scan_files=(this_file,),
        )
