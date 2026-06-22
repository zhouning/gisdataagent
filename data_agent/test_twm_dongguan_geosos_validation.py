from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


SCRIPT = Path("scripts/run_twm_dongguan_geosos_validation.py")
SIMOPT_SCRIPT = Path("scripts/run_twm_dongguan_geosos_simulation_optimization.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("run_twm_dongguan_geosos_validation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_simopt_module():
    spec = importlib.util.spec_from_file_location("run_twm_dongguan_geosos_simulation_optimization", SIMOPT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_test_geosos_zip(path: Path) -> None:
    root = path.parent / "TutorialData_DongGuan_80m"
    config_dir = root / "Config Files"
    raster_dir = root / "Landuse Data"
    config_dir.mkdir(parents=True)
    raster_dir.mkdir(parents=True)
    (config_dir / "DefaultLanduseInfo.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<LandUseClassificationInfo>
  <ConvertValues>
    <StructLanduseInfo><LanduseTypeChsName>耕地</LanduseTypeChsName><LanduseTypeEnName>Arable Land</LanduseTypeEnName><LanduseTypeValue>1</LanduseTypeValue></StructLanduseInfo>
    <StructLanduseInfo><LanduseTypeChsName>未利用地</LanduseTypeChsName><LanduseTypeEnName>Unused Land</LanduseTypeEnName><LanduseTypeValue>6</LanduseTypeValue></StructLanduseInfo>
  </ConvertValues>
  <NotToConvertValues>
    <StructLanduseInfo><LanduseTypeChsName>水域</LanduseTypeChsName><LanduseTypeEnName>Water</LanduseTypeEnName><LanduseTypeValue>4</LanduseTypeValue></StructLanduseInfo>
    <StructLanduseInfo><LanduseTypeChsName>林地</LanduseTypeChsName><LanduseTypeEnName>Woodland</LanduseTypeEnName><LanduseTypeValue>2</LanduseTypeValue></StructLanduseInfo>
  </NotToConvertValues>
  <UrbanValues>
    <StructLanduseInfo><LanduseTypeChsName>城乡建设用地</LanduseTypeChsName><LanduseTypeEnName>Construction Land</LanduseTypeEnName><LanduseTypeValue>5</LanduseTypeValue></StructLanduseInfo>
  </UrbanValues>
  <AllTypes>
    <StructLanduseInfo><LanduseTypeChsName>耕地</LanduseTypeChsName><LanduseTypeEnName>Arable Land</LanduseTypeEnName><LanduseTypeValue>1</LanduseTypeValue></StructLanduseInfo>
    <StructLanduseInfo><LanduseTypeChsName>林地</LanduseTypeChsName><LanduseTypeEnName>Woodland</LanduseTypeEnName><LanduseTypeValue>2</LanduseTypeValue></StructLanduseInfo>
    <StructLanduseInfo><LanduseTypeChsName>水域</LanduseTypeChsName><LanduseTypeEnName>Water</LanduseTypeEnName><LanduseTypeValue>4</LanduseTypeValue></StructLanduseInfo>
    <StructLanduseInfo><LanduseTypeChsName>城乡建设用地</LanduseTypeChsName><LanduseTypeEnName>Construction Land</LanduseTypeEnName><LanduseTypeValue>5</LanduseTypeValue></StructLanduseInfo>
    <StructLanduseInfo><LanduseTypeChsName>未利用地</LanduseTypeChsName><LanduseTypeEnName>Unused Land</LanduseTypeEnName><LanduseTypeValue>6</LanduseTypeValue></StructLanduseInfo>
  </AllTypes>
  <NullValue><LanduseTypeValue>0</LanduseTypeValue></NullValue>
</LandUseClassificationInfo>
""",
        encoding="utf-8",
    )
    (config_dir / "SuitableMatrix.xml").write_text(
        """<?xml version="1.0"?>
<NewDataSet>
  <Table1><耕地>1</耕地><林地>1</林地><水域>0</水域><城乡建设用地>1</城乡建设用地><未利用地>1</未利用地></Table1>
  <Table1><耕地>1</耕地><林地>1</林地><水域>0</水域><城乡建设用地>0</城乡建设用地><未利用地>1</未利用地></Table1>
  <Table1><耕地>0</耕地><林地>0</林地><水域>1</水域><城乡建设用地>0</城乡建设用地><未利用地>0</未利用地></Table1>
  <Table1><耕地>0</耕地><林地>0</林地><水域>0</水域><城乡建设用地>1</城乡建设用地><未利用地>0</未利用地></Table1>
  <Table1><耕地>1</耕地><林地>0</林地><水域>0</水域><城乡建设用地>1</城乡建设用地><未利用地>1</未利用地></Table1>
</NewDataSet>
""",
        encoding="utf-8",
    )
    arrays = {
        2000: np.array([[1, 1, 2, 4], [1, 6, 1, 2], [1, 1, 6, 1], [2, 1, 1, 6]], dtype=np.uint8),
        2005: np.array([[5, 1, 2, 4], [1, 5, 1, 2], [1, 1, 6, 5], [2, 1, 1, 6]], dtype=np.uint8),
        2006: np.array([[5, 5, 2, 4], [1, 5, 5, 2], [1, 1, 6, 5], [2, 1, 5, 6]], dtype=np.uint8),
    }
    transform = from_origin(0, 320, 80, 80)
    for year, array in arrays.items():
        with rasterio.open(
            raster_dir / f"landuse{year}.tif",
            "w",
            driver="GTiff",
            height=array.shape[0],
            width=array.shape[1],
            count=1,
            dtype=array.dtype,
            crs="EPSG:3857",
            transform=transform,
            nodata=0,
        ) as dst:
            dst.write(array, 1)
    with zipfile.ZipFile(path, "w") as zf:
        for item in root.rglob("*"):
            zf.write(item, item.relative_to(path.parent))


def test_dongguan_geosos_runner_builds_twm_validation_report(tmp_path):
    module = _load_module()
    zip_path = tmp_path / "dongguan.zip"
    _write_test_geosos_zip(zip_path)

    report = module.run_dongguan_geosos_validation(
        zip_path,
        sample_stride=1,
        max_examples_per_transition=8,
    )

    assert report["schema"] == "territory_world_model.dongguan_geosos_validation_report.v1"
    assert report["claim_boundary"] == module.CLAIM_BOUNDARY
    assert report["data_profile"]["raster_profile"]["cell_area_m2"] == 6400.0
    assert report["data_profile"]["transition_summaries"][0]["changed_cell_count"] == 3
    assert report["dataset_summary"]["example_count"] > 0
    assert report["dataset_summary"]["holdout_ground_truth_example_count"] > 0
    assert report["readiness"]["status"] in {"pass", "review"}
    assert report["fit"]["prediction_count"] == report["dataset_summary"]["example_count"]
    assert "It does not prove TWM beats GeoSOS/FLUS pixel-level simulation." in report["comparison_interpretation"]["what_this_does_not_validate"]


def test_dongguan_geosos_simopt_runner_builds_pixel_simulation_and_planner_report(tmp_path):
    module = _load_simopt_module()
    zip_path = tmp_path / "dongguan.zip"
    _write_test_geosos_zip(zip_path)

    report = module.run_dongguan_geosos_simulation_optimization(
        zip_path,
        asset_dir=tmp_path / "assets",
        render=True,
    )

    assert report["schema"] == "territory_world_model.dongguan_geosos_simulation_optimization_report.v1"
    assert report["status"] == "pass"
    assert report["claim_boundary"] == "geosos_dongguan_pixel_benchmark_not_actual_flus_output"
    assert report["simulator"]["candidate_count"] >= 6
    assert "flus_like_proxy" in report["simulator"]["baseline_candidate_ids"]
    assert "twm_balanced" in report["simulator"]["twm_candidate_ids"]
    assert report["planner"]["selected_candidate_id"].startswith("twm_")
    assert report["renderer"]["rendered"] is True
    assert (tmp_path / "assets" / "twm_dongguan_simopt_metrics.png").exists()
    for metric in report["simulator"]["metrics"].values():
        assert 0.0 <= metric["overall_accuracy"] <= 1.0
        assert 0.0 <= metric["change_fom"] <= 1.0
        assert "suitability_violation_rate" in metric
    assert "It is not an actual GeoSOS/FLUS software run because no GeoSOS/FLUS predicted output map is available in the provided data." in report["comparison_interpretation"]["what_this_still_does_not_validate"]
