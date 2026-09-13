from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


SCRIPT = Path("scripts/run_twm_dynamic_world_flus_comparison.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("run_twm_dynamic_world_flus_comparison", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_raster(path: Path, array: np.ndarray, *, nodata: int | None = None) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs="EPSG:3857",
        transform=from_origin(0, 40, 10, 10),
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)


def _synthetic_case(module, tmp_path: Path):
    classes = (0, 1, 2)
    train_start = np.array(
        [
            [0, 0, 1, 2],
            [0, 1, 1, 2],
            [2, 2, 1, 0],
        ],
        dtype=np.int16,
    )
    train_end = np.array(
        [
            [0, 1, 1, 2],
            [0, 1, 2, 2],
            [2, 1, 1, 0],
        ],
        dtype=np.int16,
    )
    holdout = np.array(
        [
            [1, 1, 1, 2],
            [0, 2, 2, 2],
            [2, 1, 0, 0],
        ],
        dtype=np.int16,
    )
    train_start_path = tmp_path / "train_start.tif"
    train_end_path = tmp_path / "train_end.tif"
    holdout_path = tmp_path / "holdout.tif"
    _write_raster(train_start_path, train_start, nodata=-32768)
    _write_raster(train_end_path, train_end, nodata=-32768)
    _write_raster(holdout_path, holdout, nodata=-32768)
    return module.FlusComparisonCase(
        case_id="synthetic_2019_2020_2021",
        region_id="synthetic",
        train_start_year=2019,
        train_end_year=2020,
        holdout_year=2021,
        train_start=module.LandcoverFrame(year=2019, array=train_start, path=str(train_start_path), nodata=-32768),
        train_end=module.LandcoverFrame(year=2020, array=train_end, path=str(train_end_path), nodata=-32768),
        holdout=module.LandcoverFrame(year=2021, array=holdout, path=str(holdout_path), nodata=-32768),
        valid=np.ones(train_start.shape, dtype=bool),
        classes=classes,
        class_labels={0: "water", 1: "trees", 2: "grass"},
        cell_area_ha=1.0,
        target_counts={0: 3, 1: 4, 2: 5},
    )


def _synthetic_case_missing_class(module, tmp_path: Path):
    case = _synthetic_case(module, tmp_path)
    train_end = case.train_end.array.copy()
    train_end[train_end == 2] = 1
    train_end_path = tmp_path / "train_end_missing_class.tif"
    _write_raster(train_end_path, train_end, nodata=-32768)
    target_counts = dict(case.target_counts)
    target_counts[2] = 0
    return module.FlusComparisonCase(
        case_id="synthetic_missing_class_2019_2020_2021",
        region_id=case.region_id,
        train_start_year=case.train_start_year,
        train_end_year=case.train_end_year,
        holdout_year=case.holdout_year,
        train_start=case.train_start,
        train_end=module.LandcoverFrame(
            year=case.train_end.year,
            array=train_end,
            path=str(train_end_path),
            nodata=-32768,
        ),
        holdout=case.holdout,
        valid=case.valid,
        classes=case.classes,
        class_labels=case.class_labels,
        cell_area_ha=case.cell_area_ha,
        target_counts=target_counts,
    )


def _synthetic_region(module, tmp_path: Path, region_id: str):
    frames = []
    for offset, year in enumerate((2017, 2018, 2019, 2020)):
        arr = np.array(
            [
                [0, 0, 1],
                [1, 2, 2],
                [2, offset % 3, 0],
            ],
            dtype=np.int16,
        )
        path = tmp_path / f"{region_id}_{year}.tif"
        _write_raster(path, arr, nodata=-32768)
        frames.append(module.LandcoverFrame(year=year, array=arr, path=str(path), nodata=-32768))
    return module.BenchmarkRegion(
        region_id=region_id,
        frames=tuple(frames),
        classes=(0, 1, 2),
        class_labels={0: "water", 1: "trees", 2: "grass"},
        cell_area_ha=1.0,
        drivers={},
        source={},
    )


def _synthetic_region_with_holdout_nodata(module, tmp_path: Path, region_id: str):
    arrays = {
        2019: np.array([[0, 1], [1, 0]], dtype=np.int16),
        2020: np.array([[0, 1], [0, 1]], dtype=np.int16),
        2021: np.array([[-32768, 1], [1, 1]], dtype=np.int16),
    }
    frames = []
    for year, arr in arrays.items():
        path = tmp_path / f"{region_id}_{year}.tif"
        _write_raster(path, arr, nodata=-32768)
        frames.append(module.LandcoverFrame(year=year, array=arr, path=str(path), nodata=-32768))
    return module.BenchmarkRegion(
        region_id=region_id,
        frames=tuple(frames),
        classes=(0, 1),
        class_labels={0: "water", 1: "trees"},
        cell_area_ha=1.0,
        drivers={},
        source={},
    )


def test_dynamic_world_to_flus_class_mapping_round_trips_nodata():
    module = _load_module()
    arr = np.array([[0, 1, 8], [-32768, 4, 99]], dtype=np.int16)
    valid = np.isin(arr, np.arange(9))

    encoded = module.dynamic_world_to_flus_classes(arr, classes=list(range(9)), valid=valid)
    decoded = module.flus_to_dynamic_world_classes(encoded, classes=list(range(9)), valid=valid)

    assert encoded.dtype == np.uint8
    assert encoded.tolist() == [[1, 2, 9], [0, 5, 0]]
    assert decoded.dtype == np.int16
    assert decoded.tolist() == [[0, 1, 8], [0, 4, 0]]


def test_write_flus_case_package_creates_console_inputs(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)

    packaged = module.write_flus_case_package(case, tmp_path / "flus_case", max_iterations=11)

    assert packaged["status"] == "packaged"
    run_dir = Path(packaged["run_dir"])
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "CCregionMakovChain.csv",
        "CCregionsimlog.txt",
        "landuse.tif",
        "metadata.json",
        "probability.tif",
        "restrict.tif",
    ]
    assert (run_dir / "CCregionMakovChain.csv").read_text(encoding="utf-8") == "year,type1,type2,type3\n2021,3,4,5\n"
    config = (run_dir / "CCregionsimlog.txt").read_text(encoding="utf-8")
    assert "[Number of types]\n3\n" in config
    assert "[Maximum Number Of Iterations]\n11\n" in config
    assert "[Path of probability data]\nprobability.tif\n" in config
    with rasterio.open(run_dir / "landuse.tif") as src:
        assert src.read(1).tolist() == [
            [1, 2, 2, 3],
            [1, 2, 3, 3],
            [3, 2, 2, 1],
        ]
        assert src.count == 1
    with rasterio.open(run_dir / "probability.tif") as src:
        assert src.count == 3
        assert src.dtypes == ("float32", "float32", "float32")
    with rasterio.open(run_dir / "restrict.tif") as src:
        assert int(src.read(1).sum()) == int(case.valid.sum())


def test_write_flus_case_package_can_use_ann_training_backend(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)

    packaged = module.write_flus_case_package(case, tmp_path / "flus_case_ann", probability_backend="flus_ann_training")

    run_dir = Path(packaged["run_dir"])
    assert packaged["probability_backend"] == "flus_ann_training"
    assert (run_dir / "CCregiontrainlogCC.txt").exists()
    assert (run_dir / "driver_transition_features.tif").exists()
    train_config = (run_dir / "CCregiontrainlogCC.txt").read_text(encoding="utf-8")
    assert "[Path of land use data]\nann_landuse.tif\n" in train_config
    assert "[Path of saving data]\nprobability.tif\n" in train_config
    assert "[Number of driving data]\n1\n" in train_config
    assert "driver_transition_features.tif\n" in train_config
    assert "[Sample type]\nSampling in proportion\n" in train_config
    with rasterio.open(run_dir / "driver_transition_features.tif") as src:
        assert src.count >= len(case.classes) + 1
        assert src.dtypes == tuple(["float32"] * src.count)


def test_ann_training_landuse_anchors_missing_classes_without_expanding_eval_mask(tmp_path):
    module = _load_module()
    case = _synthetic_case_missing_class(module, tmp_path)

    packaged = module.write_flus_case_package(case, tmp_path / "flus_case_ann_missing", probability_backend="flus_ann_training")

    run_dir = Path(packaged["run_dir"])
    with rasterio.open(run_dir / "landuse.tif") as src:
        ca_landuse = src.read(1)
    with rasterio.open(run_dir / "ann_landuse.tif") as src:
        ann_landuse = src.read(1)
    assert set(np.unique(ca_landuse).tolist()) == {1, 2}
    assert set(np.unique(ann_landuse).tolist()) >= {1, 2, 3}
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["ann_anchor"]["enabled"] is True
    assert metadata["ann_anchor"]["anchor_cell_count"] > 0
    assert int(case.valid.sum()) == packaged["valid_cell_count"]


def test_evaluate_fake_flus_output_uses_existing_public_landcover_metrics(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)
    packaged = module.write_flus_case_package(case, tmp_path / "flus_case")
    output = Path(packaged["run_dir"]) / "simresult_2021.tif"
    fake = module.dynamic_world_to_flus_classes(case.holdout.array, classes=case.classes, valid=case.valid)

    with rasterio.open(Path(packaged["run_dir"]) / "landuse.tif") as src:
        profile = src.profile.copy()
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(fake, 1)

    evaluated = module.evaluate_flus_output(case, output)

    assert evaluated["candidate_id"] == "flus_console_direct"
    assert evaluated["status"] == "evaluated"
    assert evaluated["metrics"]["overall_accuracy"] == 1.0
    assert evaluated["metrics"]["oracle_total_demand_abs_error"] == 0


def test_run_flus_console_passes_fixed_seed_environment(tmp_path):
    module = _load_module()
    executable = tmp_path / "fake_flus.py"
    executable.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os",
                "from pathlib import Path",
                "Path('seed.txt').write_text(os.environ.get('FLUS_RANDOM_SEED', ''), encoding='utf-8')",
                "print('seed=' + os.environ.get('FLUS_RANDOM_SEED', ''))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = module.run_flus_console(tmp_path, flus_executable=executable, flus_seed=12345)

    assert result["status"] == "pass"
    assert result["flus_seed"] == 12345
    assert (tmp_path / "seed.txt").read_text(encoding="utf-8") == "12345"


def test_run_flus_ann_training_calls_train_mode_with_seed(tmp_path):
    module = _load_module()
    executable = tmp_path / "fake_flus.py"
    executable.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os, sys",
                "from pathlib import Path",
                "Path('train_args.txt').write_text(' '.join(sys.argv[1:]), encoding='utf-8')",
                "Path('train_seed.txt').write_text(os.environ.get('FLUS_RANDOM_SEED', ''), encoding='utf-8')",
                "Path('probability.tif').write_bytes(b'fake')",
                "print('train seed=' + os.environ.get('FLUS_RANDOM_SEED', ''))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = module.run_flus_ann_training(tmp_path, flus_executable=executable, flus_seed=12345)

    assert result["status"] == "pass"
    assert result["flus_seed"] == 12345
    assert (tmp_path / "train_args.txt").read_text(encoding="utf-8") == "train CCregiontrainlogCC.txt"
    assert (tmp_path / "train_seed.txt").read_text(encoding="utf-8") == "12345"


def test_ann_training_failure_prevents_fallback_flus_evaluation(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)
    package = module.write_flus_case_package(case, tmp_path / "flus_case_ann_failed", probability_backend="flus_ann_training")
    training = {"status": "failed", "returncode": -11}

    should_run = module.should_run_flus_simulation(package, probability_backend="flus_ann_training", ann_training=training)

    assert should_run is False


def test_case_experiment_places_flus_next_to_existing_twm_candidates(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)
    packaged = module.write_flus_case_package(case, tmp_path / "flus_case")
    output = Path(packaged["run_dir"]) / "simresult.tif"
    fake = module.dynamic_world_to_flus_classes(case.holdout.array, classes=case.classes, valid=case.valid)

    with rasterio.open(Path(packaged["run_dir"]) / "landuse.tif") as src:
        profile = src.profile.copy()
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(fake, 1)
    evaluation = module.evaluate_flus_output(case, output)

    experiment = module.build_case_experiment(case, packaged, evaluation)

    assert "flus_console_direct" in experiment["metrics"]
    assert "twm_independent_transition_forecast_demand" in experiment["metrics"]
    assert experiment["candidate_metadata"]["flus_console_direct"]["backend"] == "local_flus_console_direct"
    assert experiment["candidate_metadata"]["twm_independent_transition_forecast_demand"]["demand_mode"] == "forecast_demand"
    assert "twm_learned_suitability_forecast_demand" in experiment["metrics"]
    assert experiment["candidate_metadata"]["twm_learned_suitability_forecast_demand"]["backend"] == "pooled_source_conditioned_suitability_logit"
    assert experiment["candidate_metadata"]["twm_learned_suitability_forecast_demand"]["component_flags"]["learned_suitability"] is True
    assert experiment["metrics"]["twm_learned_suitability_forecast_demand"]["target_total_demand_abs_error"] == 0
    assert experiment["best_forecast_by_change_fom"] in experiment["metrics"]


def test_pixel_metrics_reports_transition_pair_diagnostics():
    module = _load_module()
    classes = [0, 1]
    initial = np.array([[0, 0, 1, 1]], dtype=np.int16)
    actual = np.array([[1, 0, 0, 1]], dtype=np.int16)
    prediction = np.array([[1, 1, 1, 0]], dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)

    metric = module.pixel_metrics(
        prediction=prediction,
        actual=actual,
        initial=initial,
        valid=valid,
        classes=classes,
        cell_area_ha=1.0,
        target_counts={0: 2, 1: 2},
    )

    rows = {
        (row["source_class"], row["target_class"]): row
        for row in metric["transition_pair_metrics"]
    }
    assert rows[(0, 1)]["actual_count"] == 1
    assert rows[(0, 1)]["predicted_count"] == 2
    assert rows[(0, 1)]["hit_count"] == 1
    assert rows[(0, 1)]["false_alarm_count"] == 1
    assert rows[(0, 1)]["miss_count"] == 0
    assert rows[(0, 1)]["precision"] == 0.5
    assert rows[(0, 1)]["recall"] == 1.0
    assert rows[(1, 0)]["actual_count"] == 1
    assert rows[(1, 0)]["predicted_count"] == 1
    assert rows[(1, 0)]["hit_count"] == 0
    assert rows[(1, 0)]["false_alarm_count"] == 1
    assert rows[(1, 0)]["miss_count"] == 1


def test_change_budget_candidate_preserves_forecast_demand_while_matching_train_change_budget(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)

    metrics, metadata = module.build_twm_case_metrics(case)

    candidate = "twm_change_budget_calibrated_forecast_demand"
    train_change_count = int(((case.train_start.array != case.train_end.array) & case.valid).sum())
    assert candidate in metrics
    assert metadata[candidate]["backend"] == "score_allocation_with_training_change_budget"
    assert metadata[candidate]["component_flags"]["change_budget_calibration"] is True
    assert metadata[candidate]["training_change_budget"]["target_min_change_count"] == train_change_count
    assert metrics[candidate]["target_total_demand_abs_error"] == 0
    assert metrics[candidate]["predicted_change_count"] >= train_change_count


def test_change_budget_scale_matrix_records_fixed_train_only_budgets(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)

    metrics, metadata = module.build_twm_case_metrics(case)

    expected = {
        "twm_change_budget_scale_025_forecast_demand": 0.25,
        "twm_change_budget_scale_050_forecast_demand": 0.5,
        "twm_change_budget_scale_075_forecast_demand": 0.75,
    }
    assert "twm_risk_guarded_change_budget_forecast_demand" not in metrics
    for candidate, scale in expected.items():
        assert candidate in metrics
        assert metadata[candidate]["backend"] == "score_allocation_with_fixed_training_change_budget_scale"
        assert metadata[candidate]["component_flags"]["change_budget_calibration"] is True
        assert metadata[candidate]["component_flags"]["fixed_change_budget_scale"] is True
        assert metadata[candidate]["uses_holdout_labels_for_training"] is False
        assert metadata[candidate]["training_change_budget"]["budget_scale"] == scale
        assert metrics[candidate]["predicted_change_count"] >= metadata[candidate]["training_change_budget"]["target_min_change_count"]
        assert metrics[candidate]["target_total_demand_abs_error"] == 0


def test_adaptive_change_budget_scale_is_train_only_and_records_selection_rule(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)

    metrics, metadata = module.build_twm_case_metrics(case)

    candidate = "twm_change_budget_adaptive_churn75_forecast_demand"
    assert candidate in metrics
    assert metadata[candidate]["backend"] == "score_allocation_with_adaptive_training_change_budget_scale"
    assert metadata[candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[candidate]["component_flags"]["adaptive_change_budget_scale"] is True
    budget = metadata[candidate]["training_change_budget"]
    assert budget["scale_selection_rule"] == "net_demand_change_plus_75pct_count_neutral_churn"
    assert 0.0 <= budget["budget_scale"] <= 1.0
    assert budget["observed_train_change_count"] == int(((case.train_start.array != case.train_end.array) & case.valid).sum())
    assert budget["train_count_neutral_churn_count"] >= 0
    assert metrics[candidate]["target_total_demand_abs_error"] == 0
    assert metrics[candidate]["predicted_change_count"] >= budget["target_min_change_count"]


def test_transition_reliability_score_penalizes_low_train_support_transition():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1, 2]
    train_start = np.array([[0, 0, 0, 0, 1, 1]], dtype=np.int16)
    train_end = np.array([[1, 1, 1, 1, 1, 2]], dtype=np.int16)
    initial = np.array([[0, 0, 0, 0, 1, 1]], dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_transition_reliability_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
    )

    source_zero_cell = (0, 0)
    assert adjusted[classes.index(1)][source_zero_cell] > adjusted[classes.index(2)][source_zero_cell]
    assert diagnostics["selection_metric"] == "train_start_train_end_source_target_empirical_reliability"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    rows = {
        (row["source_class"], row["target_class"]): row
        for row in diagnostics["transition_rows"]
    }
    assert rows[(0, 1)]["train_pair_count"] == 4
    assert rows[(0, 2)]["train_pair_count"] == 0
    assert rows[(0, 2)]["score_adjustment"] < rows[(0, 1)]["score_adjustment"]


def test_temporal_activity_score_boosts_recently_changed_cells_for_non_persistence():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.array([[0, 0, 1, 1]], dtype=np.int16)
    train_end = np.array([[1, 0, 0, 1]], dtype=np.int16)
    initial = train_end.copy()
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_temporal_activity_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
    )

    recent_source_one = (0, 0)
    stable_source_one = (0, 3)
    target_zero = classes.index(0)
    assert adjusted[target_zero][recent_source_one] > adjusted[target_zero][stable_source_one]
    assert adjusted[classes.index(1)][recent_source_one] == base_score[classes.index(1)][recent_source_one]
    assert diagnostics["selection_metric"] == "train_start_train_end_recent_cell_change_activity"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["recent_change_cell_count"] == 2


def test_temporal_activity_score_can_boost_neighbors_of_recently_changed_cells():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.array(
        [
            [1, 0, 1],
            [0, 0, 0],
            [0, 0, 0],
        ],
        dtype=np.int16,
    )
    train_end = np.zeros((3, 3), dtype=np.int16)
    initial = train_end.copy()
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_temporal_activity_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        activity_weight=0.0,
        neighborhood_activity_weight=0.08,
    )

    target_one = classes.index(1)
    assert adjusted[target_one, 0, 1] > adjusted[target_one, 2, 2]
    assert adjusted[classes.index(0), 0, 1] == base_score[classes.index(0), 0, 1]
    assert diagnostics["neighborhood_activity_weight"] == 0.08
    assert diagnostics["mean_recent_change_neighbor_density"] > 0


def test_train_replay_transition_precision_penalizes_low_precision_pairs():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1, 2]
    initial = np.array([[0, 0, 0, 1]], dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)
    transition_pair_metrics = [
        {
            "source_class": 0,
            "target_class": 1,
            "predicted_count": 20,
            "precision": 0.05,
        },
        {
            "source_class": 0,
            "target_class": 2,
            "predicted_count": 20,
            "precision": 0.60,
        },
    ]

    adjusted, diagnostics = benchmark.apply_train_replay_transition_precision_to_score(
        {
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        transition_pair_metrics,
        precision_floor=0.20,
        penalty_weight=0.10,
        min_predicted_count=5,
    )

    source_zero_cell = (0, 0)
    assert adjusted[classes.index(1)][source_zero_cell] < adjusted[classes.index(2)][source_zero_cell]
    assert diagnostics["selection_metric"] == "train_replay_source_target_transition_precision"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    rows = {
        (row["source_class"], row["target_class"]): row
        for row in diagnostics["transition_rows"]
    }
    assert rows[(0, 1)]["score_penalty"] > 0
    assert rows[(0, 2)]["score_penalty"] == 0


def test_train_replay_transition_overprediction_penalizes_low_precision_overpredicted_pairs():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1, 2]
    initial = np.array([[0, 0, 0, 1]], dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)
    transition_pair_metrics = [
        {
            "source_class": 0,
            "target_class": 1,
            "actual_count": 20,
            "predicted_count": 80,
            "precision": 0.1,
        },
        {
            "source_class": 0,
            "target_class": 2,
            "actual_count": 20,
            "predicted_count": 24,
            "precision": 0.4,
        },
    ]

    adjusted, diagnostics = benchmark.apply_train_replay_transition_overprediction_to_score(
        {
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        transition_pair_metrics,
        overprediction_ratio_ceiling=1.5,
        precision_floor=0.35,
        penalty_weight=0.15,
        min_predicted_count=10,
    )

    assert adjusted[classes.index(1), 0, 0] < adjusted[classes.index(2), 0, 0]
    assert diagnostics["selection_metric"] == "train_replay_source_target_transition_overprediction"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    rows = {
        (row["source_class"], row["target_class"]): row
        for row in diagnostics["transition_rows"]
    }
    assert rows[(0, 1)]["overprediction_ratio"] == 4.0
    assert rows[(0, 1)]["score_penalty"] > 0
    assert rows[(0, 2)]["score_penalty"] == 0


def test_target_transition_neighborhood_boosts_target_specific_recent_expansion():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.zeros((3, 3), dtype=np.int16)
    train_end = np.zeros((3, 3), dtype=np.int16)
    train_end[0, 0] = 1
    initial = np.zeros((3, 3), dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_target_transition_neighborhood_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        target_transition_neighborhood_weight=0.08,
    )

    target_one = classes.index(1)
    assert adjusted[target_one, 0, 1] > adjusted[target_one, 2, 2]
    assert adjusted[classes.index(0), 0, 1] == base_score[classes.index(0), 0, 1]
    assert diagnostics["selection_metric"] == "train_start_train_end_target_transition_neighborhood_activity"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    rows = {row["target_class"]: row for row in diagnostics["target_rows"]}
    assert rows[1]["train_transition_to_target_count"] == 1


def test_topology_stability_guard_penalizes_stable_interiors_but_preserves_frontiers():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.array(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1],
            [0, 0, 0, 1, 1],
        ],
        dtype=np.int16,
    )
    train_end = train_start.copy()
    train_end[2, 3] = 1
    initial = train_end.copy()
    valid = np.ones(initial.shape, dtype=bool)
    invalid_cell = (4, 4)
    valid[invalid_cell] = False
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_topology_stability_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        stable_interior_density_floor=0.65,
        stable_interior_penalty=0.20,
        frontier_support_weight=0.10,
        target_neighborhood_support_weight=0.08,
    )

    target_one = classes.index(1)
    stable_interior_cell = (1, 1)
    frontier_supported_cell = (2, 2)

    assert adjusted.dtype == np.float32
    assert np.all(adjusted[:, invalid_cell[0], invalid_cell[1]] == -1e9)
    assert adjusted[target_one, stable_interior_cell[0], stable_interior_cell[1]] < base_score[
        target_one, stable_interior_cell[0], stable_interior_cell[1]
    ]
    assert adjusted[target_one, frontier_supported_cell[0], frontier_supported_cell[1]] > adjusted[
        target_one, stable_interior_cell[0], stable_interior_cell[1]
    ]
    assert adjusted[classes.index(0), stable_interior_cell[0], stable_interior_cell[1]] == base_score[
        classes.index(0), stable_interior_cell[0], stable_interior_cell[1]
    ]
    assert diagnostics["schema"] == "territory_world_model.train_topology_stability_score_guard.v1"
    assert diagnostics["selection_metric"] == "train_stable_interior_frontier_target_neighborhood_support"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["stable_interior_cell_count"] > 0
    assert diagnostics["frontier_cell_count"] > 0


def test_unsupported_transition_pressure_penalizes_unsupported_non_persistence():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.array(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1],
            [0, 0, 0, 1, 1],
        ],
        dtype=np.int16,
    )
    train_end = train_start.copy()
    train_end[2, 3] = 1
    initial = train_end.copy()
    valid = np.ones(initial.shape, dtype=bool)
    invalid_cell = (4, 4)
    valid[invalid_cell] = False
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_unsupported_transition_pressure_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        support_floor=0.20,
        unsupported_penalty=0.15,
    )

    target_one = classes.index(1)
    unsupported_cell = (0, 0)
    supported_cell = (2, 2)

    assert adjusted.dtype == np.float32
    assert np.all(adjusted[:, invalid_cell[0], invalid_cell[1]] == -1e9)
    assert adjusted[target_one, unsupported_cell[0], unsupported_cell[1]] < base_score[
        target_one, unsupported_cell[0], unsupported_cell[1]
    ]
    assert adjusted[target_one, supported_cell[0], supported_cell[1]] > adjusted[
        target_one, unsupported_cell[0], unsupported_cell[1]
    ]
    assert adjusted[classes.index(0), unsupported_cell[0], unsupported_cell[1]] == base_score[
        classes.index(0), unsupported_cell[0], unsupported_cell[1]
    ]
    assert diagnostics["schema"] == "territory_world_model.train_unsupported_transition_pressure_score_guard.v1"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["unsupported_cell_count"] > 0
    assert diagnostics["support_floor"] == 0.2


def test_pair_unsupported_transition_pressure_targets_high_false_alarm_pairs():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.array(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1],
            [0, 0, 0, 1, 1],
        ],
        dtype=np.int16,
    )
    train_end = train_start.copy()
    train_end[2, 3] = 1
    initial = train_end.copy()
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)
    transition_pair_metrics = [
        {
            "source_class": 0,
            "target_class": 1,
            "predicted_count": 10,
            "hit_count": 2,
            "false_alarm_count": 8,
            "precision": 0.2,
        },
        {
            "source_class": 1,
            "target_class": 0,
            "predicted_count": 10,
            "hit_count": 8,
            "false_alarm_count": 2,
            "precision": 0.8,
        },
    ]

    adjusted, diagnostics = benchmark.apply_train_pair_unsupported_transition_pressure_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        transition_pair_metrics,
        support_floor=0.20,
        false_alarm_rate_floor=0.50,
        precision_floor=0.35,
        penalty_weight=0.12,
        min_predicted_count=5,
    )

    target_one = classes.index(1)
    target_zero = classes.index(0)
    unsupported_zero_to_one = (0, 0)
    supported_zero_to_one = (2, 2)
    one_to_zero_cell = (3, 3)

    assert adjusted[target_one, unsupported_zero_to_one[0], unsupported_zero_to_one[1]] < base_score[
        target_one, unsupported_zero_to_one[0], unsupported_zero_to_one[1]
    ]
    assert adjusted[target_one, supported_zero_to_one[0], supported_zero_to_one[1]] > adjusted[
        target_one, unsupported_zero_to_one[0], unsupported_zero_to_one[1]
    ]
    assert adjusted[target_zero, one_to_zero_cell[0], one_to_zero_cell[1]] == base_score[
        target_zero, one_to_zero_cell[0], one_to_zero_cell[1]
    ]
    assert diagnostics["schema"] == "territory_world_model.train_pair_unsupported_transition_pressure_score_guard.v1"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["penalized_transition_count"] == 1
    assert diagnostics["transition_rows"][0]["source_class"] == 0
    assert diagnostics["transition_rows"][0]["target_class"] == 1


def test_pair_topology_support_contrast_boosts_supported_high_false_alarm_pairs():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    train_start = np.array(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1],
            [0, 0, 0, 1, 1],
        ],
        dtype=np.int16,
    )
    train_end = train_start.copy()
    train_end[2, 3] = 1
    initial = train_end.copy()
    valid = np.ones(initial.shape, dtype=bool)
    base_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)
    transition_pair_metrics = [
        {
            "source_class": 0,
            "target_class": 1,
            "predicted_count": 10,
            "hit_count": 2,
            "false_alarm_count": 8,
            "precision": 0.2,
        },
        {
            "source_class": 1,
            "target_class": 0,
            "predicted_count": 10,
            "hit_count": 8,
            "false_alarm_count": 2,
            "precision": 0.8,
        },
    ]

    adjusted, diagnostics = benchmark.apply_train_pair_topology_support_contrast_to_score(
        {
            "train_start": train_start,
            "train_end": train_end,
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        base_score,
        transition_pair_metrics,
        support_floor=0.20,
        false_alarm_rate_floor=0.50,
        precision_floor=0.35,
        penalty_weight=0.12,
        bonus_weight=0.10,
        min_predicted_count=5,
    )

    target_one = classes.index(1)
    target_zero = classes.index(0)
    unsupported_zero_to_one = (0, 0)
    supported_zero_to_one = (2, 2)
    one_to_zero_cell = (3, 3)

    assert adjusted[target_one, unsupported_zero_to_one[0], unsupported_zero_to_one[1]] < base_score[
        target_one, unsupported_zero_to_one[0], unsupported_zero_to_one[1]
    ]
    assert adjusted[target_one, supported_zero_to_one[0], supported_zero_to_one[1]] > base_score[
        target_one, supported_zero_to_one[0], supported_zero_to_one[1]
    ]
    assert adjusted[target_zero, one_to_zero_cell[0], one_to_zero_cell[1]] == base_score[
        target_zero, one_to_zero_cell[0], one_to_zero_cell[1]
    ]
    assert diagnostics["schema"] == "territory_world_model.train_pair_topology_support_contrast_score_guard.v1"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["penalized_transition_count"] == 1
    assert diagnostics["boosted_transition_count"] == 1
    assert diagnostics["transition_rows"][0]["source_class"] == 0
    assert diagnostics["transition_rows"][0]["target_class"] == 1
    assert diagnostics["transition_rows"][0]["boosted_cell_count"] > 0


def test_markov_demand_projection_is_train_only_and_count_conserving():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1, 2]
    valid = np.ones((2, 4), dtype=bool)
    train_start = np.array(
        [
            [0, 0, 1, 1],
            [2, 2, 2, 0],
        ],
        dtype=np.int16,
    )
    train_end = np.array(
        [
            [1, 1, 1, 2],
            [2, 0, 2, 0],
        ],
        dtype=np.int16,
    )

    projected, diagnostics = benchmark.project_markov_class_counts(
        train_start,
        train_end,
        valid,
        classes,
        train_years=1,
        horizon_years=1,
    )

    assert sum(projected.values()) == int(valid.sum())
    assert set(projected) == set(classes)
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["demand_projection_source"] == "train_start_train_end_markov_transition_counts"
    assert diagnostics["horizon_steps"] == 1
    assert diagnostics["projected_raw_counts"]["2"] > benchmark.class_counts(train_end, valid, classes)[2]


def test_transition_reliability_change_budget_candidate_is_train_only(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)

    metrics, metadata = module.build_twm_case_metrics(case)

    candidate = "twm_transition_reliability_change_budget_forecast_demand"
    assert candidate in metrics
    assert metadata[candidate]["backend"] == "train_transition_reliability_calibrated_score_allocation"
    assert metadata[candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[candidate]["component_flags"]["transition_reliability_calibration"] is True
    assert metadata[candidate]["training_transition_reliability"]["uses_holdout_labels_for_training"] is False
    assert metrics[candidate]["target_total_demand_abs_error"] == 0
    conservative_candidate = "twm_conservative_map_mode_forecast_demand"
    independent_candidate = "twm_independent_transition_forecast_demand"
    assert conservative_candidate in metrics
    assert metadata[conservative_candidate]["backend"] == "conservative_map_mode_alias_of_independent_transition_forecast"
    assert metadata[conservative_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[conservative_candidate]["component_flags"]["conservative_map_mode"] is True
    assert metadata[conservative_candidate]["alias_of"] == independent_candidate
    assert metrics[conservative_candidate]["overall_accuracy"] == metrics[independent_candidate]["overall_accuracy"]
    assert metrics[conservative_candidate]["macro_f1"] == metrics[independent_candidate]["macro_f1"]
    assert metrics[conservative_candidate]["target_total_demand_abs_error"] == 0
    swap_candidate = "twm_transition_reliability_swap_change_budget_forecast_demand"
    assert swap_candidate in metrics
    assert metadata[swap_candidate]["backend"] == "train_transition_reliability_count_neutral_swap_allocation"
    assert metadata[swap_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[swap_candidate]["component_flags"]["transition_reliability_swap_scoring"] is True
    assert metadata[swap_candidate]["training_transition_reliability"]["uses_holdout_labels_for_training"] is False
    assert metrics[swap_candidate]["target_total_demand_abs_error"] == 0
    activity_candidate = "twm_temporal_activity_change_budget_forecast_demand"
    assert activity_candidate in metrics
    assert metadata[activity_candidate]["backend"] == "train_temporal_activity_calibrated_score_allocation"
    assert metadata[activity_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[activity_candidate]["component_flags"]["temporal_activity_calibration"] is True
    assert metadata[activity_candidate]["training_temporal_activity"]["uses_holdout_labels_for_training"] is False
    assert metrics[activity_candidate]["target_total_demand_abs_error"] == 0
    combined_candidate = "twm_temporal_activity_reliability_change_budget_forecast_demand"
    assert combined_candidate in metrics
    assert metadata[combined_candidate]["backend"] == "train_temporal_activity_and_transition_reliability_score_allocation"
    assert metadata[combined_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[combined_candidate]["component_flags"]["temporal_activity_calibration"] is True
    assert metadata[combined_candidate]["component_flags"]["transition_reliability_calibration"] is True
    assert metadata[combined_candidate]["training_temporal_activity"]["uses_holdout_labels_for_training"] is False
    assert metadata[combined_candidate]["training_transition_reliability"]["uses_holdout_labels_for_training"] is False
    assert metrics[combined_candidate]["target_total_demand_abs_error"] == 0
    precision_candidate = "twm_temporal_activity_replay_precision_change_budget_forecast_demand"
    assert precision_candidate in metrics
    assert metadata[precision_candidate]["backend"] == "train_temporal_activity_and_replay_precision_score_allocation"
    assert metadata[precision_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[precision_candidate]["component_flags"]["temporal_activity_calibration"] is True
    assert metadata[precision_candidate]["component_flags"]["train_replay_transition_precision_guard"] is True
    assert metadata[precision_candidate]["training_temporal_activity"]["uses_holdout_labels_for_training"] is False
    assert metadata[precision_candidate]["training_replay_transition_precision"]["uses_holdout_labels_for_training"] is False
    assert metrics[precision_candidate]["target_total_demand_abs_error"] == 0
    neighborhood_candidate = "twm_temporal_activity_neighborhood_change_budget_forecast_demand"
    assert neighborhood_candidate in metrics
    assert metadata[neighborhood_candidate]["backend"] == "train_temporal_activity_neighborhood_score_allocation"
    assert metadata[neighborhood_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[neighborhood_candidate]["component_flags"]["temporal_activity_calibration"] is True
    assert metadata[neighborhood_candidate]["component_flags"]["temporal_activity_neighborhood"] is True
    assert metadata[neighborhood_candidate]["training_temporal_activity"]["uses_holdout_labels_for_training"] is False
    assert metrics[neighborhood_candidate]["target_total_demand_abs_error"] == 0
    neighborhood_precision_candidate = "twm_temporal_activity_neighborhood_replay_precision_change_budget_forecast_demand"
    assert neighborhood_precision_candidate in metrics
    assert metadata[neighborhood_precision_candidate]["backend"] == (
        "train_temporal_activity_neighborhood_and_replay_precision_score_allocation"
    )
    assert metadata[neighborhood_precision_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[neighborhood_precision_candidate]["component_flags"]["temporal_activity_neighborhood"] is True
    assert metadata[neighborhood_precision_candidate]["component_flags"]["train_replay_transition_precision_guard"] is True
    assert metadata[neighborhood_precision_candidate]["training_temporal_activity"]["uses_holdout_labels_for_training"] is False
    assert metadata[neighborhood_precision_candidate]["training_replay_transition_precision"]["uses_holdout_labels_for_training"] is False
    assert metrics[neighborhood_precision_candidate]["target_total_demand_abs_error"] == 0
    target_neighborhood_candidate = "twm_temporal_activity_target_neighborhood_replay_precision_change_budget_forecast_demand"
    assert target_neighborhood_candidate in metrics
    assert metadata[target_neighborhood_candidate]["backend"] == (
        "train_temporal_activity_target_neighborhood_and_replay_precision_score_allocation"
    )
    assert metadata[target_neighborhood_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[target_neighborhood_candidate]["component_flags"]["temporal_activity_neighborhood"] is True
    assert metadata[target_neighborhood_candidate]["component_flags"]["target_transition_neighborhood"] is True
    assert metadata[target_neighborhood_candidate]["component_flags"]["train_replay_transition_precision_guard"] is True
    assert metadata[target_neighborhood_candidate]["training_target_transition_neighborhood"]["uses_holdout_labels_for_training"] is False
    assert metadata[target_neighborhood_candidate]["training_replay_transition_precision"]["uses_holdout_labels_for_training"] is False
    assert metrics[target_neighborhood_candidate]["target_total_demand_abs_error"] == 0
    target_neighborhood_reliability_candidate = (
        "twm_temporal_activity_target_neighborhood_replay_precision_reliability_change_budget_forecast_demand"
    )
    assert target_neighborhood_reliability_candidate in metrics
    assert metadata[target_neighborhood_reliability_candidate]["backend"] == (
        "train_temporal_activity_target_neighborhood_replay_precision_and_reliability_score_allocation"
    )
    assert metadata[target_neighborhood_reliability_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[target_neighborhood_reliability_candidate]["component_flags"]["temporal_activity_neighborhood"] is True
    assert metadata[target_neighborhood_reliability_candidate]["component_flags"]["target_transition_neighborhood"] is True
    assert metadata[target_neighborhood_reliability_candidate]["component_flags"]["train_replay_transition_precision_guard"] is True
    assert metadata[target_neighborhood_reliability_candidate]["component_flags"]["transition_reliability_calibration"] is True
    assert (
        metadata[target_neighborhood_reliability_candidate]["training_target_transition_neighborhood"][
            "uses_holdout_labels_for_training"
        ]
        is False
    )
    assert (
        metadata[target_neighborhood_reliability_candidate]["training_replay_transition_precision"][
            "uses_holdout_labels_for_training"
        ]
        is False
    )
    assert (
        metadata[target_neighborhood_reliability_candidate]["training_transition_reliability"][
            "uses_holdout_labels_for_training"
        ]
        is False
    )
    assert metrics[target_neighborhood_reliability_candidate]["target_total_demand_abs_error"] == 0
    strict_precision_candidate = (
        "twm_temporal_activity_target_neighborhood_strict_replay_precision_change_budget_forecast_demand"
    )
    assert strict_precision_candidate in metrics
    assert metadata[strict_precision_candidate]["backend"] == (
        "train_temporal_activity_target_neighborhood_strict_replay_precision_score_allocation"
    )
    assert metadata[strict_precision_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[strict_precision_candidate]["component_flags"]["temporal_activity_neighborhood"] is True
    assert metadata[strict_precision_candidate]["component_flags"]["target_transition_neighborhood"] is True
    assert metadata[strict_precision_candidate]["component_flags"]["train_replay_transition_precision_guard"] is True
    assert metadata[strict_precision_candidate]["component_flags"]["strict_train_replay_transition_precision_guard"] is True
    assert metadata[strict_precision_candidate]["training_target_transition_neighborhood"]["uses_holdout_labels_for_training"] is False
    assert metadata[strict_precision_candidate]["training_replay_transition_precision"]["uses_holdout_labels_for_training"] is False
    assert (
        metadata[strict_precision_candidate]["training_replay_transition_precision"]["precision_guard"]["precision_floor"]
        == 0.35
    )
    assert (
        metadata[strict_precision_candidate]["training_replay_transition_precision"]["precision_guard"]["penalty_weight"]
        == 0.2
    )
    assert metrics[strict_precision_candidate]["target_total_demand_abs_error"] == 0
    overprediction_candidate = (
        "twm_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_change_budget_forecast_demand"
    )
    assert overprediction_candidate in metrics
    assert metadata[overprediction_candidate]["backend"] == (
        "train_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_score_allocation"
    )
    assert metadata[overprediction_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[overprediction_candidate]["component_flags"]["temporal_activity_neighborhood"] is True
    assert metadata[overprediction_candidate]["component_flags"]["target_transition_neighborhood"] is True
    assert metadata[overprediction_candidate]["component_flags"]["strict_train_replay_transition_precision_guard"] is True
    assert metadata[overprediction_candidate]["component_flags"]["train_replay_transition_overprediction_guard"] is True
    assert metadata[overprediction_candidate]["training_target_transition_neighborhood"]["uses_holdout_labels_for_training"] is False
    assert metadata[overprediction_candidate]["training_replay_transition_precision"]["uses_holdout_labels_for_training"] is False
    assert metadata[overprediction_candidate]["training_replay_transition_overprediction"]["uses_holdout_labels_for_training"] is False
    assert metrics[overprediction_candidate]["target_total_demand_abs_error"] == 0
    balanced_candidates = {
        "twm_balanced_strict_overprediction_churn50_forecast_demand": 0.5,
        "twm_balanced_strict_overprediction_churn75_forecast_demand": 0.75,
        "twm_balanced_strict_overprediction_churn90_forecast_demand": 0.9,
    }
    for balanced_candidate, churn_fraction in balanced_candidates.items():
        assert balanced_candidate in metrics
        assert metadata[balanced_candidate]["backend"] == (
            f"train_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_adaptive_churn{int(churn_fraction * 100)}_score_allocation"
        )
        assert metadata[balanced_candidate]["uses_holdout_labels_for_training"] is False
        assert metadata[balanced_candidate]["component_flags"]["balanced_map_mode"] is True
        assert metadata[balanced_candidate]["component_flags"]["strict_train_replay_transition_precision_guard"] is True
        assert metadata[balanced_candidate]["component_flags"]["train_replay_transition_overprediction_guard"] is True
        assert metadata[balanced_candidate]["component_flags"]["adaptive_change_budget_scale"] is True
        assert metadata[balanced_candidate]["training_replay_transition_precision"]["uses_holdout_labels_for_training"] is False
        assert metadata[balanced_candidate]["training_replay_transition_overprediction"]["uses_holdout_labels_for_training"] is False
        assert metadata[balanced_candidate]["training_change_budget"]["scale_selection_source"] == "train_start_train_end_class_counts"
        assert metadata[balanced_candidate]["training_change_budget"]["churn_fraction"] == churn_fraction
        assert metrics[balanced_candidate]["target_total_demand_abs_error"] == 0
    markov_demand_candidate = "twm_balanced_strict_overprediction_churn75_markov_forecast_demand"
    assert markov_demand_candidate in metrics
    assert metadata[markov_demand_candidate]["backend"] == (
        "train_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_adaptive_churn75_markov_demand_score_allocation"
    )
    assert metadata[markov_demand_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[markov_demand_candidate]["component_flags"]["balanced_map_mode"] is True
    assert metadata[markov_demand_candidate]["component_flags"]["markov_demand_projection"] is True
    assert metadata[markov_demand_candidate]["training_demand_projection"]["uses_holdout_labels_for_training"] is False
    assert metadata[markov_demand_candidate]["training_demand_projection"]["demand_projection_source"] == (
        "train_start_train_end_markov_transition_counts"
    )
    assert metrics[markov_demand_candidate]["target_total_demand_abs_error"] == 0
    persistence_demand_candidates = {
        "twm_balanced_strict_overprediction_churn50_persistence_forecast_demand": 0.5,
        "twm_balanced_strict_overprediction_churn75_persistence_forecast_demand": 0.75,
        "twm_balanced_strict_overprediction_churn90_persistence_forecast_demand": 0.9,
    }
    for persistence_demand_candidate, churn_fraction in persistence_demand_candidates.items():
        assert persistence_demand_candidate in metrics
        assert metadata[persistence_demand_candidate]["backend"] == (
            f"train_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_adaptive_churn{int(churn_fraction * 100)}_persistence_demand_score_allocation"
        )
        assert metadata[persistence_demand_candidate]["uses_holdout_labels_for_training"] is False
        assert metadata[persistence_demand_candidate]["component_flags"]["balanced_map_mode"] is True
        assert metadata[persistence_demand_candidate]["component_flags"]["persistence_demand_projection"] is True
        assert metadata[persistence_demand_candidate]["training_demand_projection"]["uses_holdout_labels_for_training"] is False
        assert metadata[persistence_demand_candidate]["training_demand_projection"]["demand_projection_source"] == "train_end_class_counts"
        assert metadata[persistence_demand_candidate]["training_change_budget"]["churn_fraction"] == churn_fraction
        assert metadata[persistence_demand_candidate]["target_counts"] == module.class_counts(
            case.train_end.array,
            case.valid,
            list(case.classes),
        )
        assert metrics[persistence_demand_candidate]["target_total_demand_abs_error"] == 0
    region_guard_candidate = "twm_region_false_alarm_guarded_persistence_forecast_demand"
    assert region_guard_candidate in metrics
    assert metadata[region_guard_candidate]["backend"] == (
        "train_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_"
        "region_false_alarm_guarded_persistence_demand_score_allocation"
    )
    assert metadata[region_guard_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[region_guard_candidate]["component_flags"]["region_false_alarm_guard"] is True
    assert metadata[region_guard_candidate]["component_flags"]["persistence_demand_projection"] is True
    assert metadata[region_guard_candidate]["training_false_alarm_guard"]["uses_holdout_labels_for_training"] is False
    assert metadata[region_guard_candidate]["training_false_alarm_guard"]["base_churn_fraction"] == 0.9
    assert 0.5 <= metadata[region_guard_candidate]["training_change_budget"]["churn_fraction"] <= 0.9
    assert metadata[region_guard_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[region_guard_candidate]["target_total_demand_abs_error"] == 0
    pair_guard_candidate = "twm_pair_false_alarm_guarded_persistence_forecast_demand"
    assert pair_guard_candidate in metrics
    assert metadata[pair_guard_candidate]["backend"] == (
        "train_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_"
        "pair_false_alarm_guarded_persistence_demand_score_allocation"
    )
    assert metadata[pair_guard_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[pair_guard_candidate]["component_flags"]["train_replay_transition_false_alarm_guard"] is True
    assert metadata[pair_guard_candidate]["component_flags"]["persistence_demand_projection"] is True
    assert metadata[pair_guard_candidate]["training_replay_transition_false_alarm"]["uses_holdout_labels_for_training"] is False
    assert metadata[pair_guard_candidate]["training_change_budget"]["churn_fraction"] == 0.9
    assert metadata[pair_guard_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[pair_guard_candidate]["target_total_demand_abs_error"] == 0
    topology_candidate = "twm_topology_stability_guarded_persistence_forecast_demand"
    assert topology_candidate in metrics
    assert metadata[topology_candidate]["backend"] == "train_topology_stability_guarded_persistence_demand_score_allocation"
    assert metadata[topology_candidate]["demand_mode"] == "forecast_demand"
    assert metadata[topology_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_candidate]["component_flags"]["topology_stability_guard"] is True
    assert metadata[topology_candidate]["component_flags"]["train_replay_transition_false_alarm_guard"] is True
    assert metadata[topology_candidate]["component_flags"]["persistence_demand_projection"] is True
    assert (
        metadata[topology_candidate]["training_topology_stability"]["schema"]
        == "territory_world_model.train_topology_stability_score_guard.v1"
    )
    assert metadata[topology_candidate]["training_topology_stability"]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[topology_candidate]["target_total_demand_abs_error"] == 0
    topology_churn_guard_candidate = "twm_topology_stability_false_alarm_churn_guarded_persistence_forecast_demand"
    assert topology_churn_guard_candidate in metrics
    assert (
        metadata[topology_churn_guard_candidate]["backend"]
        == "train_topology_stability_false_alarm_churn_guarded_persistence_demand_score_allocation"
    )
    assert metadata[topology_churn_guard_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_churn_guard_candidate]["component_flags"]["topology_stability_guard"] is True
    assert metadata[topology_churn_guard_candidate]["component_flags"]["train_replay_false_alarm_churn_guard"] is True
    assert (
        metadata[topology_churn_guard_candidate]["training_churn_guard"]["schema"]
        == "territory_world_model.train_replay_false_alarm_guard.v1"
    )
    assert metadata[topology_churn_guard_candidate]["training_churn_guard"]["uses_holdout_labels_for_training"] is False
    assert 0.5 <= metadata[topology_churn_guard_candidate]["training_churn_guard"]["churn_fraction"] <= 0.9
    assert metadata[topology_churn_guard_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[topology_churn_guard_candidate]["target_total_demand_abs_error"] == 0
    topology_strict_churn_guard_candidate = (
        "twm_topology_stability_strict_false_alarm_churn_guarded_persistence_forecast_demand"
    )
    assert topology_strict_churn_guard_candidate in metrics
    assert (
        metadata[topology_strict_churn_guard_candidate]["backend"]
        == "train_topology_stability_strict_false_alarm_churn_guarded_persistence_demand_score_allocation"
    )
    assert metadata[topology_strict_churn_guard_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_strict_churn_guard_candidate]["component_flags"]["topology_stability_guard"] is True
    assert metadata[topology_strict_churn_guard_candidate]["component_flags"]["strict_train_replay_false_alarm_churn_guard"] is True
    assert metadata[topology_strict_churn_guard_candidate]["training_churn_guard"]["precision_target"] == 0.6
    assert metadata[topology_strict_churn_guard_candidate]["training_churn_guard"]["precision_floor"] == 0.3
    assert metadata[topology_strict_churn_guard_candidate]["training_churn_guard"]["min_churn_fraction"] == 0.45
    assert metadata[topology_strict_churn_guard_candidate]["training_churn_guard"]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_strict_churn_guard_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[topology_strict_churn_guard_candidate]["target_total_demand_abs_error"] == 0
    topology_support_strict_churn_guard_candidate = (
        "twm_topology_support_strict_false_alarm_churn_guarded_persistence_forecast_demand"
    )
    assert topology_support_strict_churn_guard_candidate in metrics
    assert (
        metadata[topology_support_strict_churn_guard_candidate]["backend"]
        == "train_topology_support_strict_false_alarm_churn_guarded_persistence_demand_score_allocation"
    )
    assert metadata[topology_support_strict_churn_guard_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[topology_support_strict_churn_guard_candidate]["component_flags"]["topology_stability_guard"] is True
    assert metadata[topology_support_strict_churn_guard_candidate]["component_flags"]["unsupported_transition_pressure_guard"] is True
    assert metadata[topology_support_strict_churn_guard_candidate]["component_flags"][
        "strict_train_replay_false_alarm_churn_guard"
    ] is True
    assert (
        metadata[topology_support_strict_churn_guard_candidate]["training_unsupported_transition_pressure"]["schema"]
        == "territory_world_model.train_unsupported_transition_pressure_score_guard.v1"
    )
    assert (
        metadata[topology_support_strict_churn_guard_candidate]["training_unsupported_transition_pressure"][
            "uses_holdout_labels_for_training"
        ]
        is False
    )
    assert metadata[topology_support_strict_churn_guard_candidate]["training_churn_guard"]["precision_target"] == 0.6
    assert metadata[topology_support_strict_churn_guard_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[topology_support_strict_churn_guard_candidate]["target_total_demand_abs_error"] == 0
    pair_topology_support_strict_churn_guard_candidate = (
        "twm_pair_topology_support_strict_false_alarm_churn_guarded_persistence_forecast_demand"
    )
    assert pair_topology_support_strict_churn_guard_candidate in metrics
    assert (
        metadata[pair_topology_support_strict_churn_guard_candidate]["backend"]
        == "train_pair_topology_support_strict_false_alarm_churn_guarded_persistence_demand_score_allocation"
    )
    assert metadata[pair_topology_support_strict_churn_guard_candidate]["uses_holdout_labels_for_training"] is False
    assert metadata[pair_topology_support_strict_churn_guard_candidate]["component_flags"]["topology_stability_guard"] is True
    assert metadata[pair_topology_support_strict_churn_guard_candidate]["component_flags"][
        "pair_unsupported_transition_pressure_guard"
    ] is True
    assert metadata[pair_topology_support_strict_churn_guard_candidate]["component_flags"][
        "strict_train_replay_false_alarm_churn_guard"
    ] is True
    assert (
        metadata[pair_topology_support_strict_churn_guard_candidate]["training_pair_unsupported_transition_pressure"][
            "schema"
        ]
        == "territory_world_model.train_pair_unsupported_transition_pressure_score_guard.v1"
    )
    assert (
        metadata[pair_topology_support_strict_churn_guard_candidate]["training_pair_unsupported_transition_pressure"][
            "uses_holdout_labels_for_training"
        ]
        is False
    )
    assert metadata[pair_topology_support_strict_churn_guard_candidate]["training_churn_guard"]["precision_target"] == 0.6
    assert metadata[pair_topology_support_strict_churn_guard_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[pair_topology_support_strict_churn_guard_candidate]["target_total_demand_abs_error"] == 0
    pair_topology_support_contrast_strict_churn_guard_candidate = (
        "twm_pair_topology_support_contrast_strict_false_alarm_churn_guarded_persistence_forecast_demand"
    )
    assert pair_topology_support_contrast_strict_churn_guard_candidate in metrics
    assert (
        metadata[pair_topology_support_contrast_strict_churn_guard_candidate]["backend"]
        == "train_pair_topology_support_contrast_strict_false_alarm_churn_guarded_persistence_demand_score_allocation"
    )
    assert metadata[pair_topology_support_contrast_strict_churn_guard_candidate]["uses_holdout_labels_for_training"] is False
    assert (
        metadata[pair_topology_support_contrast_strict_churn_guard_candidate]["component_flags"][
            "pair_topology_support_contrast_guard"
        ]
        is True
    )
    assert (
        metadata[pair_topology_support_contrast_strict_churn_guard_candidate]["component_flags"][
            "strict_train_replay_false_alarm_churn_guard"
        ]
        is True
    )
    assert (
        metadata[pair_topology_support_contrast_strict_churn_guard_candidate]["training_pair_topology_support_contrast"][
            "schema"
        ]
        == "territory_world_model.train_pair_topology_support_contrast_score_guard.v1"
    )
    assert (
        metadata[pair_topology_support_contrast_strict_churn_guard_candidate][
            "training_pair_topology_support_contrast"
        ]["uses_holdout_labels_for_training"]
        is False
    )
    assert (
        metadata[pair_topology_support_contrast_strict_churn_guard_candidate]["training_churn_guard"][
            "precision_target"
        ]
        == 0.6
    )
    assert metadata[pair_topology_support_contrast_strict_churn_guard_candidate]["target_counts"] == module.class_counts(
        case.train_end.array,
        case.valid,
        list(case.classes),
    )
    assert metrics[pair_topology_support_contrast_strict_churn_guard_candidate]["target_total_demand_abs_error"] == 0


def test_false_alarm_guarded_churn_fraction_uses_train_replay_precision_only():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    low_precision = benchmark.false_alarm_guarded_churn_fraction(
        {
            "change_hit_count": 10,
            "change_false_alarm_count": 90,
            "change_miss_count": 20,
        },
        base_churn_fraction=0.9,
        min_churn_fraction=0.5,
        precision_target=0.45,
        precision_floor=0.25,
    )
    high_precision = benchmark.false_alarm_guarded_churn_fraction(
        {
            "change_hit_count": 60,
            "change_false_alarm_count": 40,
            "change_miss_count": 20,
        },
        base_churn_fraction=0.9,
        min_churn_fraction=0.5,
        precision_target=0.45,
        precision_floor=0.25,
    )

    assert low_precision["schema"] == "territory_world_model.train_replay_false_alarm_guard.v1"
    assert low_precision["uses_holdout_labels_for_training"] is False
    assert low_precision["train_replay_change_precision"] == 0.1
    assert low_precision["churn_fraction"] == 0.5
    assert high_precision["train_replay_change_precision"] == 0.6
    assert high_precision["churn_fraction"] == 0.9


def test_pair_false_alarm_pressure_guard_penalizes_low_precision_transition_pairs():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    initial = np.array([[0, 0, 1, 1]], dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)
    classes = [0, 1, 2]
    score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    adjusted, diagnostics = benchmark.apply_train_replay_transition_false_alarm_pressure_to_score(
        {
            "initial": initial,
            "valid": valid,
            "classes": classes,
        },
        score,
        [
            {
                "source_class": 0,
                "target_class": 1,
                "predicted_count": 10,
                "hit_count": 2,
                "false_alarm_count": 8,
                "precision": 0.2,
            },
            {
                "source_class": 1,
                "target_class": 2,
                "predicted_count": 10,
                "hit_count": 8,
                "false_alarm_count": 2,
                "precision": 0.8,
            },
        ],
        false_alarm_rate_ceiling=0.6,
        precision_floor=0.35,
        penalty_weight=0.2,
        min_predicted_count=5,
    )

    assert diagnostics["schema"] == "territory_world_model.train_replay_transition_false_alarm_score_guard.v1"
    assert diagnostics["uses_holdout_labels_for_training"] is False
    assert diagnostics["penalized_transition_count"] == 1
    assert adjusted[classes.index(1), 0, 0] < score[classes.index(1), 0, 0]
    assert adjusted[classes.index(1), 0, 1] < score[classes.index(1), 0, 1]
    assert adjusted[classes.index(2), 0, 2] == score[classes.index(2), 0, 2]
    assert adjusted[classes.index(2), 0, 3] == score[classes.index(2), 0, 3]


def test_change_budget_allocator_can_keep_base_allocation_score_separate_from_swap_score():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1]
    initial = np.array([[0, 0, 1, 1]], dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)
    model_inputs = {
        "initial": initial,
        "valid": valid,
        "classes": classes,
    }
    target_counts = {0: 1, 1: 3}
    allocation_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)
    swap_score = np.zeros((len(classes), *initial.shape), dtype=np.float32)
    allocation_score[classes.index(1), 0, 0] = 10.0
    allocation_score[classes.index(1), 0, 1] = 1.0
    swap_score[classes.index(1), 0, 0] = 1.0
    swap_score[classes.index(1), 0, 1] = 10.0

    result = benchmark.allocate_score_projection_with_explicit_change_budget(
        model_inputs,
        target_counts,
        allocation_score=allocation_score,
        swap_score=swap_score,
        target_min_change_count=1,
    )

    assert result.tolist() == [[1, 0, 1, 1]]


def test_count_neutral_swaps_do_not_exhaust_one_class_pair_when_more_budget_is_reachable():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1, 2]
    initial = np.array([[0, 0, 1], [1, 2, 2]], dtype=np.int16)
    pred = initial.copy()
    valid = np.ones(initial.shape, dtype=bool)
    score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    result = benchmark.increase_change_count_with_count_neutral_swaps(
        pred=pred,
        initial=initial,
        valid=valid,
        classes=classes,
        score=score,
        target_min_change_count=6,
    )

    assert int(((result != initial) & valid).sum()) == 6
    assert benchmark.class_counts(result, valid, classes) == benchmark.class_counts(initial, valid, classes)


def test_count_neutral_swaps_keep_extra_common_class_candidates_across_pairs():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1, 2]
    initial = np.array([[0, 0, 1, 1, 1, 1, 2, 2]], dtype=np.int16)
    pred = initial.copy()
    valid = np.ones(initial.shape, dtype=bool)
    score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    result = benchmark.increase_change_count_with_count_neutral_swaps(
        pred=pred,
        initial=initial,
        valid=valid,
        classes=classes,
        score=score,
        target_min_change_count=8,
    )

    assert int(((result != initial) & valid).sum()) == 8
    assert benchmark.class_counts(result, valid, classes) == benchmark.class_counts(initial, valid, classes)


def test_count_neutral_swaps_use_changed_label_exchanges_after_unchanged_pairs_are_exhausted():
    from scripts import build_twm_public_landcover_benchmark as benchmark

    classes = [0, 1, 2, 3]
    initial = np.array([[0, 1, 1, 1, 2, 3]], dtype=np.int16)
    pred = np.array([[1, 1, 1, 1, 0, 2]], dtype=np.int16)
    valid = np.ones(initial.shape, dtype=bool)
    score = np.zeros((len(classes), *initial.shape), dtype=np.float32)

    result = benchmark.increase_change_count_with_count_neutral_swaps(
        pred=pred,
        initial=initial,
        valid=valid,
        classes=classes,
        score=score,
        target_min_change_count=5,
    )

    assert int(((result != initial) & valid).sum()) == 5
    assert benchmark.class_counts(result, valid, classes) == benchmark.class_counts(pred, valid, classes)


def test_select_cases_can_limit_cases_per_region_for_balanced_pilot(tmp_path):
    module = _load_module()
    regions = [_synthetic_region(module, tmp_path, f"region_{idx}") for idx in range(3)]

    cases = module.select_cases(regions, case_limit=None, case_limit_per_region=1)

    assert len(cases) == 3
    assert [case.region_id for case in cases] == ["region_0", "region_1", "region_2"]


def test_select_cases_separates_prediction_and_evaluation_masks(tmp_path):
    module = _load_module()
    region = _synthetic_region_with_holdout_nodata(module, tmp_path, "mask_split")

    case = module.select_cases([region], case_limit=None, case_limit_per_region=None)[0]

    assert int(case.valid.sum()) == 4
    assert int(module.case_evaluation_valid(case).sum()) == 3
    assert sum(case.target_counts.values()) == 4
    assert sum(case.evaluation_target_counts.values()) == 3

    packaged = module.write_flus_case_package(case, tmp_path / "flus_mask_split")
    experiment = module.build_case_experiment(case, packaged, None)

    assert packaged["valid_cell_count"] == 4
    assert experiment["prediction_valid_cell_count"] == 4
    assert experiment["evaluation_valid_cell_count"] == 3
    assert experiment["valid_cell_count"] == 3
    assert experiment["metrics"]["persistence"]["valid_cell_count"] == 3


def test_public_benchmark_reports_prediction_and_evaluation_valid_masks(tmp_path):
    from scripts import build_twm_public_landcover_benchmark as benchmark

    region = _synthetic_region_with_holdout_nodata(benchmark, tmp_path, "public_mask_split")

    experiment = benchmark.run_region_cases(region)[0]

    assert experiment["prediction_valid_cell_count"] == 4
    assert experiment["evaluation_valid_cell_count"] == 3
    assert experiment["valid_cell_count"] == 3
    assert experiment["metrics"]["persistence"]["valid_cell_count"] == 3


def test_formal_forecast_summary_excludes_oracle_and_no_demand_diagnostics(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)
    packaged = module.write_flus_case_package(case, tmp_path / "flus_case")
    output = Path(packaged["run_dir"]) / "simresult.tif"
    fake = module.dynamic_world_to_flus_classes(case.holdout.array, classes=case.classes, valid=case.valid)

    with rasterio.open(Path(packaged["run_dir"]) / "landuse.tif") as src:
        profile = src.profile.copy()
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(fake, 1)
    evaluation = module.evaluate_flus_output(case, output)
    experiment = module.build_case_experiment(case, packaged, evaluation)

    summary = module.build_formal_forecast_comparison([experiment])

    assert summary["schema"] == "territory_world_model.dynamic_world_formal_forecast_comparison.v1"
    candidate_ids = [row["candidate_id"] for row in summary["ranking_by_mean_change_fom"]]
    assert "flus_console_direct" in candidate_ids
    assert "twm_independent_transition_forecast_demand" in candidate_ids
    assert "twm_topology_stability_guarded_persistence_forecast_demand" in candidate_ids
    assert "twm_independent_transition_oracle_demand" not in candidate_ids
    assert "twm_ablation_no_demand_projection" not in candidate_ids
    paired = summary["paired_deltas_vs_flus"]["twm_independent_transition_forecast_demand"]
    assert paired["paired_case_count"] == 1
    assert set(paired) >= {
        "mean_change_fom_delta",
        "median_change_fom_delta",
        "change_fom_sign_test_p_value",
        "mean_overall_accuracy_delta",
        "median_overall_accuracy_delta",
        "overall_accuracy_sign_test_p_value",
        "wins_by_change_fom",
        "losses_by_change_fom",
    }


def test_formal_forecast_summary_recommends_product_modes():
    module = _load_module()

    def metric(*, oa: float, kappa: float, change_fom: float, change_f1: float, macro_f1: float) -> dict[str, float | int]:
        return {
            "overall_accuracy": oa,
            "kappa": kappa,
            "change_fom": change_fom,
            "change_f1": change_f1,
            "macro_f1": macro_f1,
            "target_total_demand_abs_error": 0,
            "oracle_total_demand_abs_error": 0,
        }

    experiments = []
    for idx in range(6):
        experiments.append(
            {
                "case_id": f"case_{idx}",
                "candidate_metadata": {
                    "flus_console_direct": {
                        "backend": "local_flus_console_direct",
                        "demand_mode": "forecast_demand",
                        "uses_holdout_labels_for_training": False,
                    },
                    "twm_change_discovery": {
                        "backend": "change_discovery",
                        "demand_mode": "forecast_demand",
                        "uses_holdout_labels_for_training": False,
                        "component_flags": {"balanced_map_mode": True},
                    },
                    "twm_map_aware": {
                        "backend": "map_aware",
                        "demand_mode": "forecast_demand",
                        "uses_holdout_labels_for_training": False,
                        "component_flags": {"balanced_map_mode": True},
                    },
                    "twm_conservative": {
                        "backend": "conservative",
                        "demand_mode": "forecast_demand",
                        "uses_holdout_labels_for_training": False,
                        "component_flags": {"conservative_map_mode": True},
                    },
                },
                "metrics": {
                    "flus_console_direct": metric(oa=0.90, kappa=0.80, change_fom=0.20, change_f1=0.30, macro_f1=0.50),
                    "twm_change_discovery": metric(oa=0.86, kappa=0.72, change_fom=0.33, change_f1=0.44, macro_f1=0.42),
                    "twm_map_aware": metric(oa=0.89, kappa=0.78, change_fom=0.22, change_f1=0.33, macro_f1=0.56),
                    "twm_conservative": metric(oa=0.92, kappa=0.84, change_fom=0.05, change_f1=0.09, macro_f1=0.58),
                },
            }
        )

    summary = module.build_formal_forecast_comparison(experiments)
    recommendations = summary["product_mode_recommendations"]

    assert recommendations["change_discovery"]["candidate_id"] == "twm_change_discovery"
    assert recommendations["map_aware_simulation"]["candidate_id"] == "twm_map_aware"
    assert recommendations["conservative_map"]["candidate_id"] == "twm_conservative"
    assert recommendations["map_aware_simulation"]["selection_rule"] == (
        "highest macro-F1 among TWM candidates with significant positive change-FoM delta versus FLUS"
    )


def test_formal_forecast_summary_reports_demand_projection_diagnostics_by_candidate_and_year():
    module = _load_module()

    def metric(*, change_fom: float) -> dict[str, float | int]:
        return {
            "overall_accuracy": 0.80,
            "kappa": 0.60,
            "change_fom": change_fom,
            "change_f1": 0.20,
            "macro_f1": 0.40,
            "target_total_demand_abs_error": 0,
            "oracle_total_demand_abs_error": 0,
        }

    experiment = {
        "case_id": "region_a_2021_2022_2023",
        "region_id": "region_a",
        "holdout_period": "2022->2023",
        "demand": {
            "forecast_counts": {"0": 8, "1": 2},
            "oracle_counts": {"0": 5, "1": 5},
        },
        "candidate_metadata": {
            "flus_console_direct": {
                "backend": "local_flus_console_direct",
                "demand_mode": "forecast_demand",
                "uses_holdout_labels_for_training": False,
                "target_counts": {"0": 8, "1": 2},
            },
            "twm_linear": {
                "backend": "linear",
                "demand_mode": "forecast_demand",
                "uses_holdout_labels_for_training": False,
                "component_flags": {"demand_projection": True},
                "target_counts": {"0": 8, "1": 2},
            },
            "twm_markov": {
                "backend": "markov",
                "demand_mode": "forecast_demand",
                "uses_holdout_labels_for_training": False,
                "component_flags": {"demand_projection": True, "markov_demand_projection": True},
                "training_demand_projection": {
                    "demand_projection_source": "train_start_train_end_markov_transition_counts",
                    "uses_holdout_labels_for_training": False,
                },
                "target_counts": {"0": 4, "1": 6},
            },
            "twm_persistence": {
                "backend": "persistence",
                "demand_mode": "forecast_demand",
                "uses_holdout_labels_for_training": False,
                "component_flags": {"demand_projection": True, "persistence_demand_projection": True},
                "training_demand_projection": {
                    "demand_projection_source": "train_end_class_counts",
                    "uses_holdout_labels_for_training": False,
                },
                "target_counts": {"0": 5, "1": 5},
            },
        },
        "metrics": {
            "flus_console_direct": metric(change_fom=0.10),
            "twm_linear": metric(change_fom=0.11),
            "twm_markov": metric(change_fom=0.12),
            "twm_persistence": metric(change_fom=0.13),
        },
    }

    summary = module.build_formal_forecast_comparison([experiment])
    diagnostics = summary["demand_projection_diagnostics"]

    assert diagnostics["schema"] == "territory_world_model.demand_projection_diagnostics.v1"
    assert diagnostics["baseline_candidate_id"] == "flus_console_direct"
    persistence = diagnostics["aggregate_by_candidate"]["twm_persistence"]
    assert persistence["demand_projection_source"] == "train_end_class_counts"
    assert persistence["total_projected_vs_oracle_abs_error"] == 0
    assert persistence["total_abs_error_delta_vs_flus_target"] == -6
    markov = diagnostics["aggregate_by_candidate"]["twm_markov"]
    assert markov["demand_projection_source"] == "train_start_train_end_markov_transition_counts"
    assert markov["total_projected_vs_oracle_abs_error"] == 2
    by_year = diagnostics["by_holdout_year"]["2023"]
    assert by_year["best_candidate_by_projected_vs_oracle_abs_error"] == "twm_persistence"
    assert by_year["aggregate_by_candidate"]["flus_console_direct"]["total_projected_vs_oracle_abs_error"] == 6


def test_formal_forecast_summary_reports_temporal_strata_paired_diagnostics():
    module = _load_module()

    def metric(
        *,
        change_fom: float,
        change_hit_count: int,
        change_false_alarm_count: int,
        change_miss_count: int,
    ) -> dict[str, float | int]:
        return {
            "overall_accuracy": 0.80,
            "kappa": 0.60,
            "change_fom": change_fom,
            "change_f1": 0.20,
            "macro_f1": 0.40,
            "target_total_demand_abs_error": 0,
            "oracle_total_demand_abs_error": 0,
            "change_hit_count": change_hit_count,
            "change_false_alarm_count": change_false_alarm_count,
            "change_miss_count": change_miss_count,
            "actual_change_count": change_hit_count + change_miss_count,
        }

    experiments = [
        {
            "case_id": "small_loss_2023",
            "region_id": "small_loss",
            "holdout_period": "2022->2023",
            "candidate_metadata": {
                "flus_console_direct": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
                "twm_candidate": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
            },
            "metrics": {
                "flus_console_direct": metric(
                    change_fom=0.40,
                    change_hit_count=4,
                    change_false_alarm_count=2,
                    change_miss_count=4,
                ),
                "twm_candidate": metric(
                    change_fom=0.20,
                    change_hit_count=3,
                    change_false_alarm_count=7,
                    change_miss_count=7,
                ),
            },
        },
        {
            "case_id": "large_win_2023",
            "region_id": "large_win",
            "holdout_period": "2022->2023",
            "candidate_metadata": {
                "flus_console_direct": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
                "twm_candidate": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
            },
            "metrics": {
                "flus_console_direct": metric(
                    change_fom=0.10,
                    change_hit_count=10,
                    change_false_alarm_count=40,
                    change_miss_count=50,
                ),
                "twm_candidate": metric(
                    change_fom=0.20,
                    change_hit_count=40,
                    change_false_alarm_count=80,
                    change_miss_count=80,
                ),
            },
        },
    ]

    summary = module.build_formal_forecast_comparison(experiments)
    diagnostics = summary["temporal_strata_vs_flus"]["twm_candidate"]["by_holdout_year"]["2023"]

    assert diagnostics["paired_case_count"] == 2
    assert diagnostics["mean_change_fom_delta"] == -0.05
    assert diagnostics["wins_by_change_fom"] == 1
    assert diagnostics["losses_by_change_fom"] == 1
    assert diagnostics["total_change_hit_delta"] == 29
    assert diagnostics["total_change_false_alarm_delta"] == 45
    assert diagnostics["total_change_miss_delta"] == 33
    assert diagnostics["candidate_micro_change_fom"] > diagnostics["flus_micro_change_fom"]
    assert diagnostics["weighted_vs_unweighted_pattern"] == "micro_positive_mean_negative"
    assert summary["temporal_strata_vs_flus"]["twm_candidate"]["worst_holdout_year_by_mean_change_fom_delta"] == "2023"


def test_formal_forecast_summary_reports_candidate_robustness_audit():
    module = _load_module()

    def metric(*, change_fom: float, oa: float = 0.8, macro_f1: float = 0.4) -> dict[str, float | int]:
        return {
            "overall_accuracy": oa,
            "kappa": 0.60,
            "change_fom": change_fom,
            "change_f1": 0.20,
            "macro_f1": macro_f1,
            "target_total_demand_abs_error": 0,
            "oracle_total_demand_abs_error": 0,
            "change_hit_count": 1,
            "change_false_alarm_count": 1,
            "change_miss_count": 1,
            "actual_change_count": 2,
        }

    experiments = [
        {
            "case_id": "region_a_2021",
            "region_id": "region_a",
            "holdout_period": "2020->2021",
            "candidate_metadata": {
                "flus_console_direct": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
                "twm_candidate": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
            },
            "metrics": {
                "flus_console_direct": metric(change_fom=0.20),
                "twm_candidate": metric(change_fom=0.30, oa=0.78, macro_f1=0.38),
            },
        },
        {
            "case_id": "region_a_2022",
            "region_id": "region_a",
            "holdout_period": "2021->2022",
            "candidate_metadata": {
                "flus_console_direct": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
                "twm_candidate": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
            },
            "metrics": {
                "flus_console_direct": metric(change_fom=0.24),
                "twm_candidate": metric(change_fom=0.18, oa=0.77, macro_f1=0.39),
            },
        },
        {
            "case_id": "region_b_2022",
            "region_id": "region_b",
            "holdout_period": "2021->2022",
            "candidate_metadata": {
                "flus_console_direct": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
                "twm_candidate": {"demand_mode": "forecast_demand", "uses_holdout_labels_for_training": False},
            },
            "metrics": {
                "flus_console_direct": metric(change_fom=0.20),
                "twm_candidate": metric(change_fom=0.35, oa=0.79, macro_f1=0.41),
            },
        },
    ]

    summary = module.build_formal_forecast_comparison(experiments)
    audit = summary["robustness_audit"]["twm_candidate"]

    assert audit["schema"] == "territory_world_model.forecast_candidate_robustness_audit.v1"
    assert audit["status"] == "review"
    assert audit["paired_case_count"] == 3
    assert audit["mean_change_fom_delta"] == 0.063333
    assert audit["min_holdout_year_mean_change_fom_delta"] == 0.045
    assert audit["min_region_mean_change_fom_delta"] == 0.02
    assert audit["negative_holdout_year_count"] == 0
    assert audit["negative_region_count"] == 0
    assert audit["overall_accuracy_mean_delta"] < 0
    assert audit["map_metric_gap"] is True
    assert audit["generalization_claim"] == "change_fom_positive_but_map_metrics_trail_flus"


def test_recompute_twm_experiments_reuses_existing_flus_metrics_without_rerunning_flus(tmp_path):
    module = _load_module()
    case = _synthetic_case(module, tmp_path)
    packaged = module.write_flus_case_package(case, tmp_path / "flus_case")
    output = Path(packaged["run_dir"]) / "simresult.tif"
    fake = module.dynamic_world_to_flus_classes(case.holdout.array, classes=case.classes, valid=case.valid)

    with rasterio.open(Path(packaged["run_dir"]) / "landuse.tif") as src:
        profile = src.profile.copy()
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(fake, 1)
    original = module.build_case_experiment(case, packaged, module.evaluate_flus_output(case, output))

    report = {
        "schema": "territory_world_model.dynamic_world_admin20_flus_comparison.v1",
        "source": {"fixture": True},
        "run_policy": {"probability_backend": "flus_ann_training", "flus_seed": 20260623},
        "experiments": [original],
    }
    recomputed = module.recompute_twm_experiments_from_existing_report(
        existing_report=report,
        cases=[case],
        output_path=tmp_path / "recomputed.json",
    )

    experiment = recomputed["experiments"][0]
    assert recomputed["recompute_policy"]["flus_metrics_source"] == "existing_report"
    assert recomputed["data_profile"]["case_count"] == 1
    assert experiment["metrics"]["flus_console_direct"] == original["metrics"]["flus_console_direct"]
    assert "twm_change_budget_scale_025_forecast_demand" in experiment["metrics"]
    assert "twm_risk_guarded_change_budget_forecast_demand" not in experiment["metrics"]
    assert experiment["candidate_metadata"]["flus_console_direct"]["reused_from_existing_report"] is True
