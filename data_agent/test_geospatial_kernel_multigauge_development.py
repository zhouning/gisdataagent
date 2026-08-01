from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

from scripts.acquire_geotransport_center_hill_multigauge_development import (
    compile_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_multigauge_development_inputs_report.json"
)
DIAGNOSTIC_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_graph_multigauge_development_report.json"
)


def _read_descriptor(descriptor: dict[str, object]) -> bytes:
    body = (REPO_ROOT / str(descriptor["path"])).read_bytes()
    assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
    assert len(body) == descriptor["size_bytes"]
    return body


def test_multigauge_plan_is_in_domain_and_pre_d3() -> None:
    plan, feature_ids, _ = compile_plan()

    assert plan["window"] == {
        "start_inclusive_utc": "2021-12-09T01:00:00Z",
        "end_exclusive_utc": "2022-01-06T01:00:00Z",
        "hour_count": 672,
        "role": "pre_d3_public_development_only",
    }
    assert len(feature_ids) == 435
    assert plan["outlet"] == {"site_id": "03424860", "feature_id": 18421703}
    assert plan["data_isolation"]["d3_outcomes_read"] is False
    assert plan["data_isolation"]["two_system_blind_outcomes_read"] is False


def test_multigauge_public_artifacts_are_hash_verified_and_not_vintage_claimed() -> None:
    report = json.loads(REPORT.read_bytes())

    assert report["status"] == "pass_public_multigauge_development_inputs_acquired"
    assert report["station_screening"]["in_domain_site_count"] == 28
    assert report["station_screening"]["in_domain_feature_count"] == 26
    assert report["station_screening"]["eligible_site_count"] == 2
    sites = report["station_screening"]["eligible_sites"]
    assert [row["site_id"] for row in sites] == ["03424730", "03424860"]
    assert [row["feature_id"] for row in sites] == [18421273, 18421703]
    assert all(row["native_cadence_seconds"] == 1800 for row in sites)
    assert report["semantics"]["operational_vintage_availability_verified"] is False
    assert report["claim_boundary"]["multigauge_state_estimation_validated"] is False
    for descriptor in report["sources"].values():
        _read_descriptor(descriptor)
    rows = list(
        csv.DictReader(
            io.StringIO(
                _read_descriptor(report["hourly_observations"]).decode("utf-8")
            )
        )
    )
    assert len(rows) == 672
    assert rows[0]["support_start_utc"] == "2021-12-09T01:00:00Z"
    assert rows[-1]["support_end_utc"] == "2022-01-06T01:00:00Z"


def test_graph_multigauge_diagnostic_is_outcome_free_conservative_and_claim_closed() -> None:
    report = json.loads(DIAGNOSTIC_REPORT.read_bytes())

    assert report["status"] == "public_development_graph_multigauge_diagnostic_complete"
    assert report["graph_parameterization"]["rank"] == 1
    assert report["graph_parameterization"]["free_outcome_parameter_count"] == 0
    assert report["graph_parameterization"]["observation_feature_id"] == 18421273
    assert report["data_isolation"]["graph_gain_uses_usgs_values"] is False
    assert report["data_isolation"]["d3_outcomes_used"] is False
    assert report["data_isolation"]["two_system_blind_outcomes_used"] is False
    assert report["conservation"]["all_scenarios_passed"] is True
    assert report["claim_boundary"]["untouched_multi_system_window_consumed"] is False
    assert report["claim_boundary"]["graph_state_estimation_validated"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    parameter_body = _read_descriptor(report["outputs"]["graph_parameters"])
    parameters = json.loads(parameter_body)["graph_state_update_parameters"]
    assert parameters["rank"] == 1
    assert parameters["outcome_calibrated"] is False
    predictions = _read_descriptor(report["outputs"]["predictions"])
    rows = list(csv.DictReader(io.StringIO(predictions.decode("utf-8"))))
    assert len(rows) == 503
