import zipfile
from pathlib import Path

from data_agent.uwm.tap_temporal_benchmark import (
    TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA,
    build_tap_gridded_temporal_benchmark,
    validate_tap_gridded_temporal_benchmark,
)


def test_tap_benchmark_online_state_update_beats_static_baselines(tmp_path):
    tap_root = _write_benchmark_fixture(tmp_path)

    benchmark = build_tap_gridded_temporal_benchmark(
        tap_root=tap_root,
        benchmark_id="tap-benchmark-fixture",
        created_at="2026-07-06T00:30:00Z",
        train_days=3,
        max_grid_series_per_period=10,
    )

    validation = validate_tap_gridded_temporal_benchmark(benchmark)
    assert validation["valid"], validation["errors"]
    assert benchmark["schema"] == TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA
    assert benchmark["benchmark_id"] == "tap-benchmark-fixture"
    assert benchmark["traditional_baseline_suite"] == [
        "static_train_mean",
        "static_last_train_observation",
        "period_static_mean",
    ]
    assert benchmark["uwm_state_update_suite"] == [
        "online_persistence_state_update",
        "adaptive_online_state_update",
    ]
    assert benchmark["overall_results"]["series_count"] == 2
    assert benchmark["overall_results"]["holdout_count"] == 6
    assert benchmark["overall_results"]["best_uwm_method"] == "online_persistence_state_update"
    assert benchmark["overall_results"]["best_uwm_mae"] == 10.666667
    assert benchmark["overall_results"]["best_static_baseline_mae"] == 31.0
    assert benchmark["overall_results"]["best_uwm_mae_reduction"] == 20.333333
    assert benchmark["overall_results"]["beats_all_traditional_static_baselines"] is True
    assert benchmark["supported_claim"] == "tap_gridded_temporal_state_prediction_advantage_over_static_baseline"
    assert benchmark["claim_boundary"]["max_claim_level"] == "bounded_support"


def test_tap_benchmark_keeps_policy_outcome_claim_false(tmp_path):
    tap_root = _write_benchmark_fixture(tmp_path)

    benchmark = build_tap_gridded_temporal_benchmark(
        tap_root=tap_root,
        benchmark_id="tap-benchmark-fixture",
        created_at="2026-07-06T00:30:00Z",
        train_days=3,
        max_grid_series_per_period=10,
    )

    assert benchmark["empirical_superiority_claim"] is False
    assert benchmark["observed_policy_outcome_superiority_claim"] is False
    assert "not_policy_intervention_outcome" in benchmark["limitations"]
    assert "tap_gridded_product_not_station_observation" in benchmark["limitations"]


def test_tap_benchmark_supports_aggregate_advantage_without_per_series_dominance(tmp_path):
    tap_root = _write_mixed_series_benchmark_fixture(tmp_path)

    benchmark = build_tap_gridded_temporal_benchmark(
        tap_root=tap_root,
        benchmark_id="tap-benchmark-mixed-fixture",
        created_at="2026-07-06T00:30:00Z",
        train_days=3,
        max_grid_series_per_period=10,
    )

    overall = benchmark["overall_results"]
    assert overall["series_count"] == 2
    assert overall["series_beats_all_traditional_static_baselines_count"] == 1
    assert overall["series_beats_all_traditional_static_baselines_rate"] == 0.5
    assert overall["uwm_mae_by_method"]["online_persistence_state_update"] == 5.333333
    assert overall["static_baseline_mae_by_method"] == {
        "static_train_mean": 15.5,
        "static_last_train_observation": 15.5,
        "period_static_mean": 15.5,
    }
    assert overall["best_uwm_mae_reduction"] == 10.166667
    assert overall["beats_all_traditional_static_baselines"] is True
    assert benchmark["supported_claim"] == "tap_gridded_temporal_state_prediction_advantage_over_static_baseline"
    assert benchmark["claim_boundary"]["max_claim_level"] == "bounded_support"


def _write_benchmark_fixture(tmp_path: Path) -> Path:
    tap_root = tmp_path / "tap_uwm"
    downloaded = tap_root / "chongqing_pm25_2024_07_01_07" / "downloaded"
    downloaded.mkdir(parents=True)
    _write_csv_zip(
        downloaded / "Tile_074_lonlat.csv.zip",
        "Tile_074_lonlat.csv",
        ["Longitude", "Latitude", "GridID", "TileID"],
        [
            ["103.0", "29.0", "1", "74"],
            ["103.1", "29.1", "2", "74"],
        ],
    )
    values_by_doy = {
        "183": ["10", "20"],
        "184": ["10", "20"],
        "185": ["10", "20"],
        "186": ["40", "50"],
        "187": ["41", "51"],
        "188": ["42", "52"],
    }
    for doy, values in values_by_doy.items():
        _write_csv_zip(
            downloaded / f"China_PM25_1km_2024_{doy}_074.csv.zip",
            f"China_PM25_1km_2024_{doy}_074.csv",
            ["GridID", "PM2.5"],
            [["1", values[0]], ["2", values[1]]],
        )
    return tap_root


def _write_mixed_series_benchmark_fixture(tmp_path: Path) -> Path:
    tap_root = tmp_path / "tap_uwm"
    downloaded = tap_root / "chongqing_pm25_2024_07_01_07" / "downloaded"
    downloaded.mkdir(parents=True)
    _write_csv_zip(
        downloaded / "Tile_074_lonlat.csv.zip",
        "Tile_074_lonlat.csv",
        ["Longitude", "Latitude", "GridID", "TileID"],
        [
            ["103.0", "29.0", "1", "74"],
            ["103.1", "29.1", "2", "74"],
        ],
    )
    values_by_doy = {
        "183": ["10", "20"],
        "184": ["10", "20"],
        "185": ["10", "20"],
        "186": ["40", "20"],
        "187": ["41", "20"],
        "188": ["42", "20"],
    }
    for doy, values in values_by_doy.items():
        _write_csv_zip(
            downloaded / f"China_PM25_1km_2024_{doy}_074.csv.zip",
            f"China_PM25_1km_2024_{doy}_074.csv",
            ["GridID", "PM2.5"],
            [["1", values[0]], ["2", values[1]]],
        )
    return tap_root


def _write_csv_zip(path: Path, inner_name: str, fieldnames: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(fieldnames)]
    lines.extend(",".join(row) for row in rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(inner_name, "\n".join(lines) + "\n")
