from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from data_agent.planning_monitoring import (
    MonitoringConfig,
    discover_materialized_inputs,
    run_monitoring_evaluation,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target(path: Path, name: str) -> dict[str, object]:
    return {
        "target_path": str(path),
        "target_name": name,
        "target_id": f"target:{name}",
        "source_asset_id": f"asset:{name}",
        "target_sha256": _hash(path),
        "execution_status": "succeeded",
    }


def _make_fixture(tmp_path: Path, *, include_optional: bool = True) -> Path:
    crs = "EPSG:4326"
    buildings = gpd.GeoDataFrame(
        {"Id": [1, 2, 3, 4], "Floor": [2, 4, 6, 8]},
        geometry=[
            box(106.50, 29.50, 106.52, 29.52),
            box(106.53, 29.50, 106.55, 29.52),
            box(106.50, 29.55, 106.52, 29.57),
            box(106.53, 29.55, 106.55, 29.57),
        ],
        crs=crs,
    )
    building_path = tmp_path / "buildings.parquet"
    buildings.to_parquet(building_path, index=False)
    outputs: list[dict[str, object]] = [_target(building_path, "中心城区建筑数据带层高")]
    if include_optional:
        poi = gpd.GeoDataFrame(
            geometry=[Point(106.51, 29.51), Point(106.54, 29.56), Point(106.54, 29.56)],
            crs=crs,
        )
        poi_path = tmp_path / "poi.parquet"
        poi.to_parquet(poi_path, index=False)
        roads = gpd.GeoDataFrame(
            geometry=[LineString([(106.49, 29.49), (106.56, 29.58)])], crs=crs
        )
        road_path = tmp_path / "roads.parquet"
        roads.to_parquet(road_path, index=False)
        outputs.extend(
            [_target(poi_path, "高德地图POI数据2024年"), _target(road_path, "OSM_roads")]
        )

        transform = from_origin(106.4, 29.7, 0.002, 0.002)
        for filename, values in (
            ("CLCD_test.tif", np.ones((150, 150), dtype="uint8") * 8),
            ("test_DEM.tif", np.arange(150 * 150, dtype="int16").reshape(150, 150)),
        ):
            path = tmp_path / filename
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=150,
                height=150,
                count=1,
                dtype=values.dtype,
                crs=crs,
                transform=transform,
                nodata=15 if values.dtype == np.dtype("uint8") else -9999,
            ) as dataset:
                dataset.write(values, 1)
            outputs.append(_target(path, filename))
    materialization = tmp_path / "materialization.json"
    materialization.write_text(
        json.dumps({"outputs": outputs}, ensure_ascii=False), encoding="utf-8"
    )
    return materialization


def _write_binding(
    materialization: Path,
    destination: Path,
    *,
    production: bool = False,
    tamper_building_hash: bool = False,
) -> Path:
    payload = json.loads(materialization.read_text(encoding="utf-8"))
    codes = {
        "中心城区建筑数据带层高": ("CQNFWJZA", "gda:nr:class:Building"),
        "高德地图POI数据2024年": ("POI", "gda:nr:class:PublicFacility"),
        "OSM_roads": ("LCTL", "gda:nr:class:Road"),
        "CLCD_test.tif": ("CLCD", "gda:nr:class:SpatialUnit"),
        "test_DEM.tif": (
            "SZGCMX",
            "gda:nr:standard:feature:02:9489a4e2cc7493ed00eb2865",
        ),
    }
    bindings = []
    for target in payload["outputs"]:
        code, concept_id = codes[target["target_name"]]
        target_hash = target["target_sha256"]
        if tamper_building_hash and code == "CQNFWJZA":
            target_hash = "0" * 64
        bindings.append(
            {
                "target_id": target["target_id"],
                "canonical_dataset": code,
                "target_path": target["target_path"],
                "target_sha256": target_hash,
                "source_asset_id": target["source_asset_id"],
                "ontology_concept_id": concept_id,
                "binding_mode": (
                    "reference_only" if production else "reference_only_rehearsal"
                ),
                "mapping_status": "accepted",
                "mapping_authority": "runtime_baseline" if production else "rehearsal_test",
                "production_eligible": production,
            }
        )
    destination.write_text(
        json.dumps(
            {
                "binding_id": "binding-test",
                "ontology_version": "2.3.0",
                "ontology_content_sha256": (
                    "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"
                ),
                "status": "accepted" if production else "accepted_for_rehearsal",
                "binding_mode": "production" if production else "rehearsal",
                "production_eligible": production,
                "bindings": bindings,
                "skipped": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return destination


def test_discovery_maps_governed_targets_to_roles(tmp_path):
    materialization = _make_fixture(tmp_path)
    inputs = discover_materialized_inputs(materialization)
    assert set(inputs["roles"]) == {"building", "poi", "road", "land_cover", "dem"}


def test_model_writes_metrics_quality_and_lineage(tmp_path):
    materialization = _make_fixture(tmp_path)
    output = tmp_path / "model"
    report = run_monitoring_evaluation(
        materialization,
        output,
        config=MonitoringConfig(cell_size_m=5000, analysis_crs="EPSG:32648"),
    )
    assert report["status"] == "succeeded_with_review"
    assert report["unit_count"] >= 1
    assert report["production_eligible"] is False
    assert (output / "spatial_units.parquet").is_file()
    assert (output / "spatial_units.geojson").is_file()
    assert (output / "indicators.csv").is_file()
    assert len(json.loads((output / "lineage.json").read_text())["edges"]) == 13
    quality = json.loads((output / "quality_report.json").read_text())
    assert quality["checks"]["input_hashes"]["building"] is True
    assert quality["semantic_gate"]["status"] == "review"
    assert (
        quality["semantic_gate"]["roles"]["building"]["role_resolution"]
        == "name_alias_rehearsal"
    )


def test_missing_optional_sources_is_review_and_does_not_fake_zero(tmp_path):
    materialization = _make_fixture(tmp_path, include_optional=False)
    output = tmp_path / "model"
    report = run_monitoring_evaluation(
        materialization,
        output,
        config=MonitoringConfig(cell_size_m=5000, analysis_crs="EPSG:32648"),
    )
    assert report["status"] == "succeeded_with_review"
    assert set(report["role_quality"]) == {"building"}
    row = gpd.read_parquet(output / "spatial_units.parquet").iloc[0]
    assert np.isnan(row["poi_count"])


def test_rehearsal_binding_resolves_roles_without_name_alias(tmp_path):
    materialization = _make_fixture(tmp_path)
    binding = _write_binding(materialization, tmp_path / "binding.json")
    report = run_monitoring_evaluation(
        materialization,
        tmp_path / "model",
        config=MonitoringConfig(
            cell_size_m=5000,
            analysis_crs="EPSG:32648",
            authority_mode="rehearsal",
            ontology_binding_path=str(binding),
            validate_ontology=False,
        ),
    )
    assert report["status"] == "succeeded_with_review"
    roles = report["semantic_gate"]["roles"]
    assert {roles[role]["role_resolution"] for role in roles if roles[role]["target_id"]} == {
        "ontology_binding"
    }
    assert report["metric_semantics"][0]["source_concepts"] == ["gda:nr:class:Building"]


def test_production_without_binding_is_blocked_before_computation(tmp_path):
    materialization = _make_fixture(tmp_path)
    output = tmp_path / "model"
    report = run_monitoring_evaluation(
        materialization,
        output,
        config=MonitoringConfig(
            cell_size_m=5000,
            analysis_crs="EPSG:32648",
            authority_mode="production",
            validate_ontology=False,
        ),
    )
    assert report["status"] == "blocked"
    assert "ontology_binding_required_in_production" in report["semantic_gate"]["errors"]
    assert not (output / "spatial_units.parquet").exists()


def test_production_target_hash_mismatch_is_blocked(tmp_path):
    materialization = _make_fixture(tmp_path)
    binding = _write_binding(
        materialization,
        tmp_path / "binding.json",
        production=True,
        tamper_building_hash=True,
    )
    report = run_monitoring_evaluation(
        materialization,
        tmp_path / "model",
        config=MonitoringConfig(
            cell_size_m=5000,
            analysis_crs="EPSG:32648",
            authority_mode="production",
            ontology_binding_path=str(binding),
            validate_ontology=False,
        ),
    )
    assert report["status"] == "blocked"
    assert any(
        item.startswith("target_hash_mismatch:building")
        for item in report["semantic_gate"]["errors"]
    )


def test_production_valid_binding_and_ontology_package_is_eligible(tmp_path):
    materialization = _make_fixture(tmp_path)
    binding = _write_binding(materialization, tmp_path / "binding.json", production=True)
    report = run_monitoring_evaluation(
        materialization,
        tmp_path / "model",
        config=MonitoringConfig(
            cell_size_m=5000,
            analysis_crs="EPSG:32648",
            authority_mode="production",
            ontology_binding_path=str(binding),
            ontology_package_dir=(
                Path(__file__).parent
                / "ontology"
                / "packages"
                / "natural_resource_one_map"
                / "2.3.0"
            ).as_posix(),
        ),
    )
    assert report["status"] == "pass"
    assert report["production_eligible"] is True
    assert report["semantic_gate"]["ontology"]["status"] == "available"
    assert {
        value["role_resolution"]
        for value in report["semantic_gate"]["roles"].values()
        if value["target_id"]
    } == {"ontology_binding"}
