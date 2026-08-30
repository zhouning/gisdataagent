import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds, from_origin

from data_agent.frontend_api import _pending_lock, pending_map_updates


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_tif(path: Path, data: np.ndarray, *, transform=None, crs: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        transform=transform or from_origin(0, data.shape[0], 1, 1),
        crs=crs,
    ) as dataset:
        dataset.write(data, 1)


def _paper58_fixture(root: Path, *, georeferenced: bool = False) -> None:
    area = "xiangzhen_record_000191"
    method = "paper58_spatial_demand_ratio_claim_robustness_v4"
    metric_rows = [
        {
            "method": "geosos_flus_console",
            "n": 1,
            "mean_change_f1": 0.2,
            "mean_fom": 0.1,
            "mean_transition_accuracy": 0.3,
            "mean_allocation_disagreement": 0.05,
        },
        {
            "method": method,
            "n": 1,
            "mean_change_f1": 0.4,
            "mean_fom": 0.2,
            "mean_transition_accuracy": 0.5,
            "mean_allocation_disagreement": 0.03,
        },
    ]
    per_area_rows = [
        {
            "method": method,
            "area": area,
            "start_year": 2020,
            "end_year": 2021,
            "source": "fixture",
            "tier": "same_grid",
            "stratum": "fixture",
            "n_pixels": 6,
            "true_change_pixels": 2,
            "pred_change_pixels": 2,
            "change_precision": 0.5,
            "change_recall": 0.5,
            "change_f1": 0.4,
            "fom": 0.2,
            "transition_accuracy": 0.5,
            "quantity_disagreement": 0.01,
            "allocation_disagreement": 0.03,
        },
        {
            "method": "geosos_flus_console",
            "area": area,
            "start_year": 2020,
            "end_year": 2021,
            "source": "fixture",
            "tier": "same_grid",
            "stratum": "fixture",
            "n_pixels": 6,
            "true_change_pixels": 2,
            "pred_change_pixels": 1,
            "change_precision": 0.2,
            "change_recall": 0.2,
            "change_f1": 0.2,
            "fom": 0.1,
            "transition_accuracy": 0.3,
            "quantity_disagreement": 0.02,
            "allocation_disagreement": 0.05,
        },
    ]
    _write_csv(root / "metric_summary_by_method.csv", metric_rows)
    _write_csv(root / "metrics_by_method.csv", per_area_rows)

    case_dir = root / "flus_cases" / f"{area}_2020_2021"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "class_mapping.json").write_text(
        json.dumps({"encoded_to_original": {"1": 0, "2": 1, "3": 2}}),
        encoding="utf-8",
    )
    _write_tif(case_dir / "landuse.tif", np.array([[1, 2, 2], [3, 3, 1]], dtype=np.uint8))

    paper58_dir = root / "maps" / method
    paper58_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        paper58_dir / f"{area}_2020_2021_{method}.npy",
        np.array([[0, 1, 1], [2, 1, 0]], dtype=np.uint8),
    )
    _write_tif(
        root / "maps" / "geosos_flus_console" / f"{area}_2020_2021_flus.tif",
        np.array([[0, 1, 1], [2, 2, 0]], dtype=np.uint8),
    )

    if georeferenced:
        input_root = root / "paper58_inputs"
        labels_dir = input_root / "labels"
        labels_dir.mkdir(parents=True, exist_ok=True)
        (root / "run_manifest.json").write_text(
            json.dumps({"labels_dir": str(labels_dir)}),
            encoding="utf-8",
        )
        _write_tif(
            input_root / "downloads" / area / f"{area}_esri_lulc_2020.tif",
            np.array([[1, 2, 2], [3, 3, 1]], dtype=np.uint8),
            transform=from_bounds(113.0, 34.7, 113.1, 34.8, 3, 2),
            crs="EPSG:4326",
        )


def test_build_paper58_visualization_reads_metrics_and_selection(tmp_path):
    from data_agent.paper58_visualization import build_paper58_visualization

    _paper58_fixture(tmp_path)

    payload = build_paper58_visualization(tmp_path)

    assert payload["schema"] == "territory_world_model.paper58_visualization.v1"
    assert payload["status"] == "ready"
    assert payload["selected_area"] == "xiangzhen_record_000191"
    assert payload["selected_method"] == "paper58_spatial_demand_ratio_claim_robustness_v4"
    assert payload["baseline_method"] == "geosos_flus_console"
    assert payload["years"] == [2020, 2021]
    assert payload["areas"][0]["paper58_delta_change_f1"] == 0.2
    assert payload["areas"][0]["paper58_wins"] is True
    assert payload["selected_area_metrics"]["deltas"]["allocation_disagreement"] == -0.02
    assert payload["visualization"]["available_layers"] == [
        "Paper58 土地利用 2020",
        "Paper58 土地利用 2021",
        "GeoSOS-FLUS 土地利用 2021",
        "Paper58 与 GeoSOS-FLUS 差异 2021",
    ]


def test_queue_paper58_visualization_map_writes_geojson_and_pending_update(tmp_path):
    from data_agent.paper58_visualization import queue_paper58_visualization_map

    _paper58_fixture(tmp_path)
    with _pending_lock:
        pending_map_updates.pop("alice", None)

    payload = queue_paper58_visualization_map(tmp_path, "alice")

    assert payload["status"] == "queued"
    assert payload["map_update_queued"] is True
    assert [layer["name"] for layer in payload["map_update"]["layers"]] == [
        "Paper58 土地利用 2020",
        "Paper58 土地利用 2021",
        "GeoSOS-FLUS 土地利用 2021",
        "Paper58 与 GeoSOS-FLUS 差异 2021",
    ]
    assert all(layer["type"] == "categorized" for layer in payload["map_update"]["layers"])
    assert payload["map_update"]["center"] == [0.333333, 0.5]

    upload_dir = Path(__file__).resolve().parent / "uploads" / "alice"
    for layer in payload["map_update"]["layers"]:
        geojson_path = upload_dir / layer["geojson"]
        assert geojson_path.exists()
        geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
        assert geojson["type"] == "FeatureCollection"
        assert geojson["features"]
        assert "class_name" in geojson["features"][0]["properties"]

    with _pending_lock:
        queued = pending_map_updates.pop("alice", None)
    assert queued == payload["map_update"]


def test_queue_paper58_visualization_map_uses_manifest_download_georeference(tmp_path):
    from data_agent.paper58_visualization import queue_paper58_visualization_map

    _paper58_fixture(tmp_path, georeferenced=True)
    with _pending_lock:
        pending_map_updates.pop("bob", None)

    payload = queue_paper58_visualization_map(tmp_path, "bob")

    assert payload["status"] == "queued"
    assert payload["map_update"]["georeferenced"] is True
    assert payload["map_update"]["display_crs"] == "EPSG:4326"
    assert payload["map_update"]["center"] == [34.75, 113.05]

    upload_dir = Path(__file__).resolve().parent / "uploads" / "bob"
    geojson_path = upload_dir / payload["map_update"]["layers"][0]["geojson"]
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert geojson["properties"]["display_crs"] == "EPSG:4326"
    coordinates = geojson["features"][0]["geometry"]["coordinates"][0]
    longitudes = [point[0] for point in coordinates]
    latitudes = [point[1] for point in coordinates]
    assert min(longitudes) >= 113.0
    assert max(longitudes) <= 113.1
    assert min(latitudes) >= 34.7
    assert max(latitudes) <= 34.8
