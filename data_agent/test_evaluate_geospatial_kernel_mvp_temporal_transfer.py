import csv
import hashlib
import io

import pytest

from scripts.evaluate_geospatial_kernel_mvp_temporal_transfer import (
    HORIZONS,
    compile_temporal_transfer,
)


def test_fixed_parameters_are_replayed_on_two_public_temporal_windows(tmp_path) -> None:
    january_path = tmp_path / "january.csv"
    d3_path = tmp_path / "d3.csv"

    january_body, d3_body, report = compile_temporal_transfer(
        january_prediction_path=january_path,
        d3_prediction_path=d3_path,
    )
    january_rows = list(csv.DictReader(io.StringIO(january_body.decode("utf-8"))))
    d3_rows = list(csv.DictReader(io.StringIO(d3_body.decode("utf-8"))))

    assert len(january_rows) == 1_990
    assert len(d3_rows) == 2_638
    assert {int(row["horizon_hours"]) for row in january_rows} == set(HORIZONS)
    assert {int(row["horizon_hours"]) for row in d3_rows} == set(HORIZONS)
    parameter_lock = report["parameter_lock"]
    assert parameter_lock["parameter_refit_performed"] is False
    assert parameter_lock["hash_unchanged"] is True
    assert all(
        row["parameter_sha256"] == parameter_lock["loaded_parameter_sha256"]
        for row in january_rows + d3_rows
    )
    assert all(row["future_outcome_observation_used"] == "False" for row in january_rows + d3_rows)
    assert all(
        float(row["target_state_writeback_m3s"]) == float(row["kernel_mvp_m3s"])
        for row in january_rows + d3_rows
    )
    assert report["data_isolation"]["new_target_data_acquired"] is False


def test_transfer_metrics_fail_noncompensatory_gate_without_claim_inflation(tmp_path) -> None:
    _, _, report = compile_temporal_transfer(
        january_prediction_path=tmp_path / "january.csv",
        d3_prediction_path=tmp_path / "d3.csv",
    )

    january = report["windows"]["january_temporal_holdout"]
    d3 = report["windows"]["february_d3"]
    expected_counts = {
        "january_temporal_holdout": {"1": 502, "3": 500, "6": 497, "12": 491},
        "february_d3": {"1": 664, "3": 662, "6": 659, "12": 653},
    }
    assert (
        january["scoring"]["common_complete_case_count_by_horizon"]
        == expected_counts["january_temporal_holdout"]
    )
    assert d3["scoring"]["common_complete_case_count_by_horizon"] == expected_counts["february_d3"]
    assert january["metrics_by_horizon"]["1"]["kernel_mvp"]["rmse_m3s"] == pytest.approx(
        15.568735652984346
    )
    assert d3["metrics_by_horizon"]["12"]["kernel_mvp"]["rmse_m3s"] == pytest.approx(
        86.78940729571139
    )
    assert january["diagnostic_hard_gate"]["all_horizons_beat_causal_persistence"] is False
    assert (
        d3["diagnostic_hard_gate"]["per_horizon"]["1"]["candidate_beats_causal_persistence_rmse"]
        is False
    )
    assert (
        d3["diagnostic_hard_gate"]["per_horizon"]["3"]["candidate_beats_causal_persistence_rmse"]
        is True
    )
    assert report["aggregate_gate"]["all_windows_transfer_gate_passed"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False
    assert report["claim_boundary"]["action_conditioned_closure_admitted_as_default"] is False


def test_prediction_descriptors_cover_exact_compiled_bodies(tmp_path) -> None:
    january_path = tmp_path / "january.csv"
    d3_path = tmp_path / "d3.csv"

    january_body, d3_body, report = compile_temporal_transfer(
        january_prediction_path=january_path,
        d3_prediction_path=d3_path,
    )

    for window_id, path, body in (
        ("january_temporal_holdout", january_path, january_body),
        ("february_d3", d3_path, d3_body),
    ):
        descriptor = report["windows"][window_id]["predictions"]
        assert descriptor["path"] == str(path.resolve())
        assert descriptor["sha256"] == hashlib.sha256(body).hexdigest()
        assert descriptor["size_bytes"] == len(body)
