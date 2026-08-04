import copy
import json
from pathlib import Path

import pytest

from data_agent.test_uwm_geospatial_state_prior_benchmark import (
    _build_benchmark,
    _dataset,
)
from data_agent.uwm.geospatial_kernel.state_prior_p1_failure_diagnostic import (
    STATE_PRIOR_P1_FAILURE_DIAGNOSTIC_SCHEMA,
    build_state_prior_p1_failure_diagnostic,
    compute_state_prior_p1_failure_diagnostic_sha256,
    validate_state_prior_p1_failure_diagnostic,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DATASET_PATH = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_dataset_2018_10_18_23"
    / "uwm_geospatial_state_prior_dataset.json"
)
BENCHMARK_PATH = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_benchmark_2018_10_18_23"
    / "uwm_geospatial_state_prior_benchmark.json"
)
DIAGNOSTIC_PATH = (
    DATA_ROOT
    / "geospatial_state_prior_p1_failure_diagnostic_2018_10_18_23"
    / "uwm_geospatial_state_prior_p1_failure_diagnostic.json"
)


def test_failed_p1_diagnostic_quantifies_shift_and_preserves_no_go():
    diagnostic = _build_real_diagnostic()

    assert diagnostic["schema"] == STATE_PRIOR_P1_FAILURE_DIAGNOSTIC_SCHEMA
    assert validate_state_prior_p1_failure_diagnostic(diagnostic) == {
        "valid": True,
        "errors": [],
    }
    assert diagnostic["p1_benchmark_ready"] is False
    assert diagnostic["p2_admission_permitted"] is False
    assert diagnostic["analysis_boundary"]["max_claim_level"] == "not_for_claim"
    assert diagnostic["diagnostic_summary"]["failed_readiness_gates"] == [
        "candidate_beats_required_baselines_on_every_split",
        "geometry_shuffle_negative_controls_passed",
        "split_conformal_coverage_passed",
    ]

    feature_diagnostics = diagnostic["feature_diagnostics"]
    assert feature_diagnostics["raster"]["overall_centered_rank"] == 2
    assert feature_diagnostics["admin"]["overall_centered_rank"] == 2
    assert feature_diagnostics["graph_object"]["overall_centered_rank"] == 1
    for route in feature_diagnostics.values():
        for feature in route["per_feature"].values():
            assert feature["correlation_interpretation"] == (
                "descriptive_only_not_feature_evidence"
            )

    deltas = diagnostic["performance_deltas"]
    raster_deltas = deltas["candidate_minus_required_baseline_mae_by_split"]
    assert raster_deltas["spatial_block"]["raster_only_ridge"] > 0.0
    assert raster_deltas["whole_admin"]["raster_only_ridge"] > 0.0
    assert raster_deltas["future_temporal"]["raster_only_ridge"] < 0.0
    negative_control = deltas["candidate_minus_negative_control_mae_by_split"]
    assert negative_control["spatial_block"]["shuffled_admin_alignment_ridge"] > 0.0
    assert negative_control["whole_admin"]["shuffled_admin_alignment_ridge"] > 0.0
    assert (
        diagnostic["conformal_coverage_deficits"]["by_split"]["spatial_block"]["coverage_deficit"]
        == 0.183333333
    )


def test_diagnostic_cannot_be_promoted_even_after_digest_is_recomputed():
    diagnostic = _build_real_diagnostic()
    forged = copy.deepcopy(diagnostic)
    forged["p1_benchmark_ready"] = True
    forged["p2_admission_permitted"] = True
    forged["analysis_boundary"]["p2_admission_permitted"] = True
    forged["analysis_boundary"]["scientific_result_claim"] = True
    forged["general_geospatial_world_model_validation_claim"] = True
    forged["diagnostic_sha256"] = compute_state_prior_p1_failure_diagnostic_sha256(forged)

    validation = validate_state_prior_p1_failure_diagnostic(forged)

    assert not validation["valid"]
    assert "p1_failure_diagnostic_analysis_boundary_invalid" in validation["errors"]
    assert "p1_failure_diagnostic_cannot_change_p1_readiness" in validation["errors"]
    assert "p1_failure_diagnostic_cannot_permit_p2_admission" in validation["errors"]
    assert (
        "p1_failure_diagnostic_general_geospatial_world_model_validation_claim_must_be_false"
        in validation["errors"]
    )
    assert "p1_failure_diagnostic_sha256_mismatch" not in validation["errors"]


def test_diagnostic_builder_rejects_a_successful_benchmark():
    dataset = _dataset(source_evidence_kind="observed_holdout")
    benchmark = _build_benchmark(source_evidence_kind="observed_holdout")

    with pytest.raises(ValueError, match="requires_failed_benchmark"):
        build_state_prior_p1_failure_diagnostic(
            diagnostic_id="successful-benchmark-is-not-a-failure-diagnostic",
            created_at="2026-08-04T22:00:00Z",
            dataset=dataset,
            benchmark=benchmark,
        )


def test_checked_in_failure_diagnostic_is_valid_and_fail_closed():
    diagnostic = _read_json(DIAGNOSTIC_PATH)

    assert validate_state_prior_p1_failure_diagnostic(diagnostic) == {
        "valid": True,
        "errors": [],
    }
    assert diagnostic["diagnostic_sha256"] == (
        "1aede01d5ab421d629aa9e43af7b7614046ce446ed37395fd839cfae504d933a"
    )
    assert diagnostic["p2_admission_permitted"] is False


def _build_real_diagnostic() -> dict:
    return build_state_prior_p1_failure_diagnostic(
        diagnostic_id="chongqing-observed-station-p1-failure-test",
        created_at="2026-08-04T22:00:00Z",
        dataset=_read_json(DATASET_PATH),
        benchmark=_read_json(BENCHMARK_PATH),
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
