import zipfile
from pathlib import Path

from data_agent.uwm.tap_external_dynamics import (
    TAP_EXTERNAL_DYNAMICS_SCHEMA,
    build_tap_external_dynamics_report,
    validate_tap_external_dynamics_report,
)


def test_spatial_message_model_beats_static_and_non_spatial_baselines(tmp_path):
    tap_root = _write_spatial_diffusion_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
        ridge=0.001,
    )

    validation = validate_tap_external_dynamics_report(report)
    assert validation["valid"], validation["errors"]
    assert report["schema"] == TAP_EXTERNAL_DYNAMICS_SCHEMA
    assert report["model_id"] == "tap-external-dynamics-fixture"
    assert report["sampling_config"]["neighbor_mode"] == "lonlat_nearest_neighbors_v1"
    assert report["training_summary"]["series_count"] == 4
    assert report["training_summary"]["holdout_count"] == 12

    overall = report["overall_results"]
    assert overall["best_spatial_method"] == "spatial_message_ridge"
    assert "spatial_message_ridge" in report["spatial_world_model_results"]
    assert "spatial_residual_delta_ridge" in report["spatial_world_model_results"]
    assert overall["best_spatial_mae"] < overall["best_traditional_static_mae"]
    assert overall["best_spatial_mae"] < overall["best_non_spatial_dynamic_mae"]
    assert overall["paired_win_rate_vs_best_non_spatial_dynamic"] > 0.5
    assert report["negative_control_results"]["neighbor_shuffle_control"]["mae"] > overall["best_spatial_mae"]
    assert (
        report["negative_control_results"]["non_spatial_feature_ablation_control"]["mae"]
        > overall["best_spatial_mae"]
    )
    assert report["supported_claim"] == (
        "tap_external_spatiotemporal_dynamics_advantage_over_static_and_non_spatial_baselines"
    )
    assert report["claim_boundary"]["max_claim_level"] == "bounded_support"


def test_residual_delta_model_beats_direct_spatial_and_dynamic_when_velocity_matters(tmp_path):
    tap_root = _write_spatial_residual_delta_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-residual-delta-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=5,
        max_grid_series_per_period=4,
        neighbor_count=2,
        ridge=0.001,
        residual_delta_ridge=0.1,
        residual_delta_correction_clip=2.0,
    )

    residual = report["spatial_world_model_results"]["spatial_residual_delta_ridge"]
    direct = report["spatial_world_model_results"]["spatial_message_ridge"]
    overall = report["overall_results"]
    assert residual["case_count"] == 16
    assert residual["mae"] < direct["mae"]
    assert residual["mae"] < overall["best_non_spatial_dynamic_mae"]
    assert residual["paired_win_rate_vs_best_non_spatial_dynamic"] > 0.5
    assert overall["best_spatial_method"] == "spatial_residual_delta_ridge"
    assert overall["best_spatial_mae"] == residual["mae"]


def test_spatial_claim_downgrades_when_neighbors_do_not_help(tmp_path):
    tap_root = _write_no_spatial_signal_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-no-spatial-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
        ridge=0.001,
    )

    assert report["supported_claim"] in {
        "tap_external_temporal_dynamics_advantage_without_spatial_claim",
        "no_tap_external_dynamics_advantage_claim_supported",
    }
    assert report["overall_results"]["spatial_negative_control_passed"] is False
    assert (
        report["negative_control_results"]["non_spatial_feature_ablation_control"]["mae"]
        <= report["overall_results"]["best_spatial_mae"]
    )


def test_external_dynamics_keeps_policy_outcome_claims_false(tmp_path):
    tap_root = _write_spatial_diffusion_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
    )

    assert report["empirical_superiority_claim"] is False
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert "not_policy_intervention_outcome" in report["limitations"]
    assert "tap_gridded_product_not_station_observation" in report["limitations"]


def test_external_dynamics_feature_rows_do_not_use_current_or_future_labels(tmp_path):
    tap_root = _write_spatial_diffusion_fixture(tmp_path)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
        include_feature_audit=True,
    )

    leakage = report["negative_control_results"]["future_label_leakage_guard"]
    assert leakage["passed"] is True
    assert leakage["audited_feature_rows"] > 0
    assert leakage["feature_time_rule"] == "features_for_day_t_use_only_values_strictly_before_day_t"
    for row in report["feature_audit_sample"]:
        assert int(row["max_feature_doy"]) < int(row["target_doy"])


def test_external_dynamics_aggregates_paired_counts_across_periods(tmp_path):
    first_root = _write_spatial_diffusion_fixture(tmp_path / "first")
    second_root = _write_spatial_diffusion_fixture(tmp_path / "second")
    tap_root = tmp_path / "combined_tap"
    tap_root.mkdir()
    for period_dir in first_root.iterdir():
        period_dir.rename(tap_root / "chongqing_pm25_2024_07_01_07")
    for period_dir in second_root.iterdir():
        period_dir.rename(tap_root / "chongqing_pm25_2018_10_17_23")

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="tap-external-dynamics-two-period-fixture",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=4,
        neighbor_count=2,
        ridge=0.001,
    )

    spatial = report["spatial_world_model_results"]["spatial_message_ridge"]
    assert spatial["case_count"] == 24
    assert spatial["paired_win_count_vs_best_non_spatial_dynamic"] == 24
    assert spatial["paired_loss_count_vs_best_non_spatial_dynamic"] == 0
    assert spatial["paired_tie_count_vs_best_non_spatial_dynamic"] == 0


def _write_spatial_diffusion_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path,
        values_by_doy={
            "183": ["20", "20", "40", "0"],
            "184": ["30", "10", "10", "30"],
            "185": ["10", "30", "30", "10"],
            "186": ["30", "10", "10", "30"],
            "187": ["10", "30", "30", "10"],
            "188": ["30", "10", "10", "30"],
        },
    )


def _write_spatial_residual_delta_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path,
        values_by_doy={
            "183": ["20", "20", "20", "20"],
            "184": ["18", "22", "18", "22"],
            "185": ["20", "20", "20", "20"],
            "186": ["22", "18", "22", "18"],
            "187": ["20", "20", "20", "20"],
            "188": ["18", "22", "18", "22"],
            "189": ["20", "20", "20", "20"],
            "190": ["22", "18", "22", "18"],
            "191": ["20", "20", "20", "20"],
        },
    )


def _write_no_spatial_signal_fixture(tmp_path: Path) -> Path:
    return _write_fixture(
        tmp_path,
        values_by_doy={
            "183": ["10", "20", "30", "40"],
            "184": ["11", "21", "31", "41"],
            "185": ["12", "22", "32", "42"],
            "186": ["13", "23", "33", "43"],
            "187": ["14", "24", "34", "44"],
            "188": ["15", "25", "35", "45"],
        },
    )


def _write_fixture(tmp_path: Path, values_by_doy: dict[str, list[str]]) -> Path:
    tap_root = tmp_path / "tap_uwm"
    downloaded = tap_root / "chongqing_pm25_2024_07_01_07" / "downloaded"
    downloaded.mkdir(parents=True)
    _write_csv_zip(
        downloaded / "Tile_074_lonlat.csv.zip",
        "Tile_074_lonlat.csv",
        ["Longitude", "Latitude", "GridID", "TileID"],
        [
            ["103.0", "29.0", "1", "74"],
            ["103.1", "29.0", "2", "74"],
            ["103.0", "29.1", "3", "74"],
            ["103.1", "29.1", "4", "74"],
        ],
    )
    for doy, values in values_by_doy.items():
        _write_csv_zip(
            downloaded / f"China_PM25_1km_2024_{doy}_074.csv.zip",
            f"China_PM25_1km_2024_{doy}_074.csv",
            ["GridID", "PM2.5"],
            [["1", values[0]], ["2", values[1]], ["3", values[2]], ["4", values[3]]],
        )
    return tap_root


def _write_csv_zip(path: Path, inner_name: str, fieldnames: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(fieldnames)]
    lines.extend(",".join(row) for row in rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(inner_name, "\n".join(lines) + "\n")
