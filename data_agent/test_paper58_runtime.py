import json
from pathlib import Path

import numpy as np
import pytest


def test_runtime_metrics_compare_change_and_transition_quality():
    from data_agent.paper58_runtime.metrics import compute_prediction_metrics

    start = np.array([[1, 1, 2], [2, 2, 2]], dtype=np.int16)
    observed = np.array([[1, 2, 2], [2, 1, 2]], dtype=np.int16)
    predicted = np.array([[1, 2, 1], [2, 2, 2]], dtype=np.int16)
    valid = np.ones(start.shape, dtype=bool)

    metrics = compute_prediction_metrics(start, observed, predicted, valid)

    assert metrics["n_pixels"] == 6
    assert metrics["true_change_pixels"] == 2
    assert metrics["pred_change_pixels"] == 2
    assert metrics["change_precision"] == 0.5
    assert metrics["change_recall"] == 0.5
    assert metrics["change_f1"] == 0.5
    assert metrics["fom"] == pytest.approx(1 / 3)
    assert metrics["transition_accuracy"] == 0.5
    assert metrics["demand_residual_by_class"] == {"1": 0, "2": 0}


def test_runtime_metrics_reject_shape_mismatch():
    from data_agent.paper58_runtime.metrics import compute_prediction_metrics

    start = np.zeros((2, 2), dtype=np.int16)
    observed = np.zeros((2, 2), dtype=np.int16)
    predicted = np.zeros((3, 2), dtype=np.int16)

    try:
        compute_prediction_metrics(start, observed, predicted)
    except ValueError as exc:
        assert "same shape" in str(exc)
    else:
        raise AssertionError("expected shape mismatch")


def _write_case_fixture(root: Path) -> Path:
    labels = root / "inputs" / "labels"
    predictions = root / "inputs" / "predictions"
    labels.mkdir(parents=True)
    predictions.mkdir(parents=True)
    np.save(
        labels / "xiangzhen_record_000191_lulc_2020.npy",
        np.array([[1, 1], [2, 2]], dtype=np.int16),
    )
    np.save(
        labels / "xiangzhen_record_000191_lulc_2021.npy",
        np.array([[1, 2], [2, 2]], dtype=np.int16),
    )
    np.save(
        predictions / "xiangzhen_record_000191_lulc_pred_2020_2021.npy",
        np.array([[1, 2], [1, 2]], dtype=np.int16),
    )
    method_dir = root / "maps" / "paper58_spatial_demand_ratio_claim_robustness_v4"
    method_dir.mkdir(parents=True)
    np.save(
        method_dir
        / "xiangzhen_record_000191_2020_2021_paper58_spatial_demand_ratio_claim_robustness_v4.npy",
        np.array([[1, 2], [2, 2]], dtype=np.int16),
    )
    manifest = {
        "labels_dir": str(labels),
        "paper58_predictions_dir": str(predictions),
        "samples": [
            {
                "area": "xiangzhen_record_000191",
                "start_year": 2020,
                "end_year": 2021,
                "shape": [2, 2],
                "valid_pixels": 4,
                "changed_pixels": 1,
                "prediction_path": str(
                    predictions / "xiangzhen_record_000191_lulc_pred_2020_2021.npy"
                ),
            }
        ],
    }
    (root / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return root


def test_discover_runtime_cases_reads_manifest_and_methods(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases

    root = _write_case_fixture(tmp_path)
    cases = discover_runtime_cases(root)

    assert len(cases) == 1
    assert cases[0].area == "xiangzhen_record_000191"
    assert cases[0].shape == (2, 2)
    assert cases[0].methods == (
        "paper58_latent_dynamics",
        "paper58_spatial_demand_ratio_claim_robustness_v4",
    )


def test_discover_runtime_cases_rejects_mismatched_shape(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases

    root = _write_case_fixture(tmp_path)
    np.save(
        root / "inputs" / "labels" / "xiangzhen_record_000191_lulc_2021.npy",
        np.zeros((3, 2), dtype=np.int16),
    )

    try:
        discover_runtime_cases(root)
    except ValueError as exc:
        assert "shape mismatch" in str(exc)
    else:
        raise AssertionError("expected shape mismatch")


def test_paper58_adapter_materializes_selected_method(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases
    from data_agent.paper58_runtime.paper58_adapter import materialize_paper58_prediction

    root = _write_case_fixture(tmp_path / "benchmark")
    case = discover_runtime_cases(root)[0]
    result = materialize_paper58_prediction(
        root,
        case,
        "paper58_spatial_demand_ratio_claim_robustness_v4",
        tmp_path / "run",
    )

    assert result["method"] == "paper58_spatial_demand_ratio_claim_robustness_v4"
    assert Path(result["prediction_path"]).exists()
    assert np.load(result["prediction_path"]).tolist() == [[1, 2], [2, 2]]
    assert result["provenance"]["source_mode"] == "local_paper58_artifact"


def test_flus_adapter_uses_fake_console_and_collects_output(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases
    from data_agent.paper58_runtime.flus_adapter import run_geosos_flus

    root = _write_case_fixture(tmp_path / "benchmark")
    case = discover_runtime_cases(root)[0]

    def fake_runner(case_dir: Path) -> None:
        import rasterio
        from rasterio.transform import from_origin

        with rasterio.open(
            case_dir / "simresult.tif",
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            transform=from_origin(0, 2, 1, 1),
        ) as dataset:
            dataset.write(np.array([[1, 2], [2, 2]], dtype=np.uint8), 1)

    result = run_geosos_flus(
        case,
        tmp_path / "run",
        flus_executable=Path("/fake/flus_console"),
        console_runner=fake_runner,
    )

    assert result["method"] == "geosos_flus_console"
    assert Path(result["prediction_path"]).exists()
    assert np.load(result["prediction_npy_path"]).tolist() == [[1, 2], [2, 2]]
    assert result["return_code"] == 0


def test_runtime_runner_creates_completed_run_and_layers(tmp_path):
    from data_agent.paper58_runtime.runner import run_runtime_once

    root = _write_case_fixture(tmp_path / "benchmark")

    def fake_runner(case_dir: Path) -> None:
        import rasterio
        from rasterio.transform import from_origin

        with rasterio.open(
            case_dir / "simresult.tif",
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            transform=from_origin(0, 2, 1, 1),
        ) as dataset:
            dataset.write(np.array([[1, 2], [2, 2]], dtype=np.uint8), 1)

    run = run_runtime_once(
        benchmark_dir=root,
        output_root=tmp_path / "runs",
        area="xiangzhen_record_000191",
        method="paper58_spatial_demand_ratio_claim_robustness_v4",
        flus_executable=Path("/fake/flus_console"),
        console_runner=fake_runner,
    )

    assert run["status"] == "completed"
    assert run["metrics"]["paper58"]["change_f1"] == 1.0
    assert run["metrics"]["geosos_flus"]["change_f1"] == 1.0
    assert Path(run["output_dir"], "run_manifest.json").exists()
    assert [layer["name"] for layer in run["layers"]] == [
        "起始土地利用 2020",
        "真实土地利用 2021",
        "Paper58 预测土地利用 2021",
        "GeoSOS-FLUS 预测土地利用 2021",
        "Paper58 误差 2021",
        "GeoSOS-FLUS 误差 2021",
        "Paper58 与 GeoSOS-FLUS 分歧 2021",
    ]


def test_runtime_map_layers_emit_full_style_objects(tmp_path):
    from data_agent.paper58_runtime.runner import run_runtime_once

    root = _write_case_fixture(tmp_path / "benchmark")

    def fake_runner(case_dir: Path) -> None:
        import rasterio
        from rasterio.transform import from_origin

        with rasterio.open(
            case_dir / "simresult.tif",
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            transform=from_origin(0, 2, 1, 1),
        ) as dataset:
            dataset.write(np.array([[1, 2], [2, 2]], dtype=np.uint8), 1)

    run = run_runtime_once(
        benchmark_dir=root,
        output_root=tmp_path / "runs",
        area="xiangzhen_record_000191",
        method="paper58_spatial_demand_ratio_claim_robustness_v4",
        flus_executable=Path("/fake/flus_console"),
        console_runner=fake_runner,
    )

    first_layer = run["map_update"]["layers"][0]
    assert first_layer["category_column"] == "class_name"
    assert first_layer["category_labels"] == {
        key: key for key in first_layer["style_map"]
    }
    assert first_layer["style_map"]["水体"]["fillColor"] == "#4169E1"
    assert first_layer["style_map"]["水体"]["color"] == "#4169E1"
    assert first_layer["style_map"]["水体"]["fillOpacity"] > 0


def test_load_runtime_run_normalizes_legacy_string_style_map(tmp_path):
    from data_agent.paper58_runtime.runner import load_runtime_run

    run_dir = tmp_path / "runs" / "legacy_run"
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": "legacy_run",
                "status": "completed",
                "map_update": {
                    "layers": [
                        {
                            "name": "旧格式图层",
                            "type": "categorized",
                            "category_column": "class_name",
                            "style_map": {"水体": "#4169E1"},
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    run = load_runtime_run(tmp_path / "runs", "legacy_run")

    style = run["map_update"]["layers"][0]["style_map"]["水体"]
    assert style["fillColor"] == "#4169E1"
    assert style["color"] == "#4169E1"
    assert style["fillOpacity"] > 0
