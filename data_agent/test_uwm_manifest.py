from pathlib import Path

from data_agent.uwm.manifest import (
    UWM_MANIFEST_REQUIRED_COLUMNS,
    audit_uwm_manifest,
    validate_manifest_row,
)


def test_validate_manifest_row_accepts_public_proxy_with_claim_boundary():
    row = {
        "dataset_id": "era5_meteorology_chongqing",
        "dataset_name": "ERA5 meteorology for Chongqing",
        "source_type": "public",
        "source_ref": "https://cds.climate.copernicus.eu/",
        "access_status": "planned_public_download",
        "spatial_extent": "Chongqing central urban area",
        "temporal_extent": "2021-2024",
        "geometry_type": "raster",
        "crs": "EPSG:4326",
        "license": "Copernicus terms",
        "lineage": "public reanalysis",
        "quality_status": "planned",
        "synthetic_status": "public_proxy",
        "used_by": "uwm_air;uwm_heat",
        "claim_boundary": "bounded_support",
    }

    validation = validate_manifest_row(row)

    assert validation["valid"], validation["errors"]


def test_validate_manifest_row_accepts_fitted_proxy_but_not_core_claim():
    row = {
        "dataset_id": "uwm_fitted_admin_population_downscaling_2021",
        "dataset_name": "UWM fitted admin population downscaling proxy",
        "source_type": "synthetic",
        "source_ref": "data/uwm_public_proxy/chongqing_central/fitted_gap_filling_2026_07_05/snapshot_manifest.json",
        "access_status": "available",
        "spatial_extent": "Chongqing township and street admin units",
        "temporal_extent": "2021",
        "geometry_type": "admin_tabular_panel",
        "crs": "EPSG:4326",
        "license": "internal_fitted_proxy_from_local_population_and_GHSL_terms",
        "lineage": "district population total-preserving downscaling using GHSL weights",
        "quality_status": "fitted_proxy_not_census_microdata",
        "synthetic_status": "fitted_proxy",
        "used_by": "population_vulnerability;simulator_context",
        "claim_boundary": "exploratory_only",
    }

    validation = validate_manifest_row(row)

    assert validation["valid"], validation["errors"]

    row["claim_boundary"] = "core_support"
    validation = validate_manifest_row(row)
    assert not validation["valid"]
    assert "synthetic/fitted rows cannot use core_support claim_boundary" in validation["errors"]


def test_validate_manifest_row_rejects_synthetic_core_claim():
    row = {column: "x" for column in UWM_MANIFEST_REQUIRED_COLUMNS}
    row["dataset_id"] = "synthetic_air_quality"
    row["synthetic_status"] = "synthetic"
    row["claim_boundary"] = "core_support"

    validation = validate_manifest_row(row)

    assert not validation["valid"]
    assert "synthetic/fitted rows cannot use core_support claim_boundary" in validation["errors"]


def test_audit_manifest_counts_public_restricted_and_synthetic_rows(tmp_path: Path):
    path = tmp_path / "manifest.csv"
    path.write_text(
        ",".join(UWM_MANIFEST_REQUIRED_COLUMNS)
        + "\n"
        + "chongqing_buildings,Chongqing buildings,restricted_local,/data/buildings,available,central urban,2021,polygon,EPSG:4490,restricted,planning sample,usable,real,renderer,bounded_support\n"
        + "era5_meteorology,ERA5 meteorology,public,https://cds.climate.copernicus.eu/,planned_public_download,central urban,2021-2024,raster,EPSG:4326,Copernicus,public reanalysis,planned,public_proxy,simulator,bounded_support\n"
        + "synthetic_air,Synthetic air placeholder,synthetic,generated,available,central urban,2024,grid,EPSG:4490,internal,seeded generator,smoke_only,synthetic,uwm_air,exploratory_only\n",
        encoding="utf-8",
    )

    audit = audit_uwm_manifest(path)

    assert audit["valid"], audit["errors"]
    assert audit["row_count"] == 3
    assert audit["source_type_counts"]["public"] == 1
    assert audit["source_type_counts"]["restricted_local"] == 1
    assert audit["synthetic_status_counts"]["synthetic"] == 1
