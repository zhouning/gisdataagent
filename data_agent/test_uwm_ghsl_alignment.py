import csv
import json
import zipfile

import numpy as np
import rasterio
from rasterio.transform import from_origin

from data_agent.uwm.ghsl_alignment import (
    GHSL_ADMIN_ALIGNMENT_SCHEMA,
    align_ghsl_tiles_to_admin_units,
    build_mmfe_state_input_from_ghsl_admin_alignment,
    validate_ghsl_admin_alignment,
)


def test_align_ghsl_tiles_to_admin_units_writes_zonal_proxy_artifact(tmp_path):
    ghsl_dir = tmp_path / "ghsl"
    tiles_dir = ghsl_dir / "tiles"
    tiles_dir.mkdir(parents=True)
    pop_zip = _write_zipped_raster(
        tiles_dir / "pop.zip",
        "pop.tif",
        np.array([[1, 2], [3, 4]], dtype="float32"),
    )
    built_zip = _write_zipped_raster(
        tiles_dir / "built.zip",
        "built.tif",
        np.array([[10, 20], [30, 40]], dtype="float32"),
    )
    ghsl_manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "toy_ghsl_snapshot",
        "files": {
            "population_tiles": [{"file": f"tiles/{pop_zip.name}", "zip_entries": ["pop.tif"]}],
            "built_surface_tiles": [{"file": f"tiles/{built_zip.name}", "zip_entries": ["built.tif"]}],
        },
        "license": "CC BY 4.0",
    }
    ghsl_manifest_path = ghsl_dir / "snapshot_manifest.json"
    ghsl_manifest_path.write_text(json.dumps(ghsl_manifest), encoding="utf-8")
    admin_path = tmp_path / "admin.geojson"
    admin_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"county": "A", "township": "left_half"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [0, 0],
                                [1, 0],
                                [1, 2],
                                [0, 2],
                                [0, 0],
                            ]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    artifact = align_ghsl_tiles_to_admin_units(
        ghsl_manifest_path=ghsl_manifest_path,
        admin_geojson_path=admin_path,
        output_dir=tmp_path / "aligned",
        created_at="2026-07-05T00:00:00Z",
    )

    validation = validate_ghsl_admin_alignment(artifact)
    assert validation["valid"], validation["errors"]
    assert artifact["schema"] == GHSL_ADMIN_ALIGNMENT_SCHEMA
    assert artifact["alignment_status"] == "proxy_zonal_stats_available"
    assert artifact["empirical_superiority_claim"] is False
    assert artifact["admin_feature_count"] == 1
    assert artifact["raster_layers"]["population"]["tile_count"] == 1
    assert artifact["raster_layers"]["built_surface"]["tile_count"] == 1
    assert artifact["files"]["zonal_stats_csv"] == "ghsl_admin_zonal_proxy.csv"

    with (tmp_path / "aligned" / "ghsl_admin_zonal_proxy.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["admin_unit_id"] == "A|left_half|0"
    assert float(rows[0]["population_proxy_sum"]) == 4.0
    assert float(rows[0]["built_surface_proxy_sum"]) == 40.0
    assert int(rows[0]["population_valid_pixel_count"]) == 2
    assert int(rows[0]["built_surface_valid_pixel_count"]) == 2


def test_validate_ghsl_admin_alignment_rejects_empirical_claim_for_proxy_product():
    payload = {
        "schema": GHSL_ADMIN_ALIGNMENT_SCHEMA,
        "dataset_id": "bad_alignment",
        "alignment_status": "proxy_zonal_stats_available",
        "admin_feature_count": 1,
        "raster_layers": {},
        "files": {"zonal_stats_csv": "ghsl_admin_zonal_proxy.csv"},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "empirical_superiority_claim": True,
    }

    validation = validate_ghsl_admin_alignment(payload)

    assert not validation["valid"]
    assert "empirical_superiority_claim must remain false for GHSL proxy alignment" in validation["errors"]


def test_build_mmfe_state_input_from_ghsl_admin_alignment_keeps_proxy_claim_boundary():
    alignment = {
        "schema": GHSL_ADMIN_ALIGNMENT_SCHEMA,
        "dataset_id": "ghsl_admin_zonal_proxy_alignment",
        "alignment_status": "proxy_zonal_stats_available",
        "admin_feature_count": 2,
        "raster_layers": {"population": {"tile_count": 1}, "built_surface": {"tile_count": 1}},
        "files": {"zonal_stats_csv": "ghsl_admin_zonal_proxy.csv"},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "empirical_superiority_claim": False,
    }
    zonal_rows = [
        {"population_proxy_sum": "4", "built_surface_proxy_sum": "0"},
        {"population_proxy_sum": "0", "built_surface_proxy_sum": "40"},
    ]

    payload = build_mmfe_state_input_from_ghsl_admin_alignment(
        alignment,
        zonal_rows,
        timestamp="2026-07-05T00:00:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["source_product"]["product_id"] == "mmfe-ghsl-admin-alignment-2020"
    assert payload["urban_spatial_unit"]["unit_type"] == "township_admin_unit"
    assert payload["urban_spatial_unit"]["feature_count"] == 2
    assert payload["state_components"]["population_vulnerability"]["role_count"] == 1
    assert payload["state_components"]["urban_form"]["role_count"] == 1
    assert payload["state_components"]["remote_sensing_state"]["role_count"] == 1
    assert payload["state_components"]["administrative_units"]["role_count"] == 1
    assert payload["graph_summary"]["relation_type_distribution"]["admin_unit_has_population_proxy"] == 1
    assert payload["graph_summary"]["relation_type_distribution"]["admin_unit_has_built_surface_proxy"] == 1
    assert payload["native_geometry_contract"]["metadata_complete"] is True
    assert payload["native_geometry_contract"]["complete_role_count"] == 4
    assert payload["native_geometry_contract"]["geometry_types"] == ["polygon"]
    assert payload["native_geometry_contract"]["observation_semantics"] == ["derived", "observed"]
    assert payload["object_role_registry"][0]["aggregation_semantics"] == "total"
    assert payload["object_role_registry"][0]["spatial_support"]["support_type"] == "admin_unit"
    assert payload["production_policy"]["authoritative_data_required_for_production"] is True
    assert any("GHSL proxy" in warning for warning in payload["warnings"])


def test_align_ghsl_tiles_to_admin_units_skips_admin_units_that_only_touch_tile_edge(tmp_path):
    ghsl_dir = tmp_path / "ghsl"
    tiles_dir = ghsl_dir / "tiles"
    tiles_dir.mkdir(parents=True)
    pop_zip = _write_zipped_raster(
        tiles_dir / "pop.zip",
        "pop.tif",
        np.array([[1, 2], [3, 4]], dtype="float32"),
    )
    built_zip = _write_zipped_raster(
        tiles_dir / "built.zip",
        "built.tif",
        np.array([[10, 20], [30, 40]], dtype="float32"),
    )
    ghsl_manifest_path = ghsl_dir / "snapshot_manifest.json"
    ghsl_manifest_path.write_text(
        json.dumps(
            {
                "schema": "uwm.public_proxy_snapshot_manifest.v1",
                "dataset_id": "toy_ghsl_snapshot",
                "files": {
                    "population_tiles": [{"file": f"tiles/{pop_zip.name}", "zip_entries": ["pop.tif"]}],
                    "built_surface_tiles": [{"file": f"tiles/{built_zip.name}", "zip_entries": ["built.tif"]}],
                },
            }
        ),
        encoding="utf-8",
    )
    admin_path = tmp_path / "admin_touching_edge.geojson"
    admin_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"county": "A", "township": "north_edge"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [0, 2],
                                [1, 2],
                                [1, 3],
                                [0, 3],
                                [0, 2],
                            ]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    artifact = align_ghsl_tiles_to_admin_units(
        ghsl_manifest_path=ghsl_manifest_path,
        admin_geojson_path=admin_path,
        output_dir=tmp_path / "aligned",
        created_at="2026-07-05T00:00:00Z",
    )

    assert artifact["admin_feature_count"] == 1
    with (tmp_path / "aligned" / "ghsl_admin_zonal_proxy.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert float(rows[0]["population_proxy_sum"]) == 0.0
    assert int(rows[0]["population_valid_pixel_count"]) == 0


def _write_zipped_raster(zip_path, inner_name, array):
    tif_path = zip_path.with_suffix(".tif")
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=str(array.dtype),
        crs="EPSG:4326",
        transform=from_origin(0, 2, 1, 1),
        nodata=-200,
    ) as dataset:
        dataset.write(array, 1)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(tif_path, arcname=inner_name)
    tif_path.unlink()
    return zip_path
