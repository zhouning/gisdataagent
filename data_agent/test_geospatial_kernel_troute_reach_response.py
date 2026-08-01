from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from scripts.diagnose_geotransport_troute_mc_reach_response import (
    DEFAULT_REPORT,
    _summarize_reach_response,
)


def test_reach_response_summary_preserves_negative_lobes_and_float32_scale() -> None:
    response = np.asarray([0.0, 0.25, -0.125, -0.25, 0.125], dtype=float)

    summary = _summarize_reach_response(
        response,
        feature_id=101,
        reach_index=0,
        warmed_flow_m3s=2.0,
        timestep_seconds=4.0,
        input_volume_m3=100.0,
    )

    assert summary["minimum_response_m3s"] == -0.25
    assert summary["positive_response_volume_m3"] == pytest.approx(1.5)
    assert summary["negative_response_volume_m3"] == pytest.approx(1.5)
    assert summary["negative_lobe_above_tolerance"] is True
    assert summary["negative_sample_below_threshold_count"] == 2
    assert summary["first_negative_sample_interval_end_seconds"] == 12.0
    assert summary["reference_float32_ulp_m3s"] == float(
        np.spacing(np.float32(2.0))
    )
    assert summary["absolute_minimum_response_to_reference_float32_ulp"] > 1e5


def test_reach_response_summary_rejects_nonfinite_vectors() -> None:
    with pytest.raises(ValueError, match="t_route_mc_reach_response_vector_invalid"):
        _summarize_reach_response(
            [0.0, float("nan")],
            feature_id=101,
            reach_index=0,
            warmed_flow_m3s=2.0,
            timestep_seconds=300.0,
            input_volume_m3=3600.0,
        )


def test_reach_response_report_freezes_default_and_short_ts_adjudication() -> None:
    body = DEFAULT_REPORT.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "394e6a0cbf2f0fcde2148841322d0a67f6cc67f7e2fd4d8bf7af505b7a0b3481"
    )
    default = report["mode_summaries"]["default_current_upstream"]
    short = report["mode_summaries"]["short_previous_upstream"]
    assert len(report["cases"]) == 54
    assert default["outlet_negative_lobe_case_count"] == 24
    assert default["timestep_stability"]["passed_count"] == 26
    assert default["first_negative_lobe_feature_counts"] == {
        "1622687": 1,
        "1622797": 21,
        "1623573": 2,
        "none": 3,
    }
    assert short["outlet_negative_lobe_case_count"] == 0
    assert short["timestep_stability"]["passed_count"] == 9
    default_negative_ulp = [
        reach["absolute_minimum_response_to_reference_float32_ulp"]
        for case in report["cases"]
        if not case["assume_short_timestep"]
        for reach in case["reaches"]
        if reach["negative_lobe_above_tolerance"]
    ]
    assert min(default_negative_ulp) == 240.0
    assert report["claim_boundary"]["short_timestep_mode_promoted"] is False


def test_call_order_sensitivity_report_freezes_initialization_failure() -> None:
    path = DEFAULT_REPORT.with_name("t_route_mc_call_order_sensitivity_report.json")
    body = path.read_bytes()
    report = json.loads(body)

    assert hashlib.sha256(body).hexdigest() == (
        "7092f7b648809b7819ce0665dcac71a2b79a8191768ac0156c970f483e520ca1"
    )
    assert report["status"] == (
        "fixed_commit_cold_process_trace_sensitivity_detected"
    )
    assert report["warmup"]["mc_only"]["outlet_flow_m3s"] == report["warmup"][
        "manning_interleaved"
    ]["t_route_mc_outlet_flow_m3s"]
    assert report["call_order_invariance"]["passed"] is False
    assert abs(
        report["metric_differences_mc_only_minus_interleaved"][
            "net_outlet_volume_m3"
        ]
    ) > 400.0
    assert report["claim_boundary"]["undefined_initialization_path_found"]
    assert not report["claim_boundary"][
        "all_negative_lobes_explained_by_initialization_defect"
    ]
