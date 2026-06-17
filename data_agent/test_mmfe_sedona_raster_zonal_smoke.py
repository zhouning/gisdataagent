"""Tests for the Sedona raster zonal smoke script helpers."""

from pathlib import Path

from scripts.smoke_mmfe_sedona_raster_zonal import (
    _default_raster_alias_zh,
    _find_raster_metadata,
)


def test_find_raster_metadata_matches_real_imagery_manifest():
    data_dir = Path("data_agent/test_data/twm_bishan_demo")
    metadata = _find_raster_metadata(data_dir, data_dir / "real_imagery/sentinel2_l2a_ndvi.tif")

    assert metadata["product_id"] == "REAL-S2-L2A-NDVI"
    assert metadata["type"] == "spectral_index"
    assert metadata["formula"] == "NDVI=(NIR-Red)/(NIR+Red)"


def test_find_raster_metadata_matches_synthetic_manifest():
    data_dir = Path("data_agent/test_data/twm_bishan_demo")
    metadata = _find_raster_metadata(data_dir, data_dir / "rasters/synthetic_ndvi_2026.tif")

    assert metadata["product_id"] == "RASTER-NDVI-2026"
    assert metadata["alias_zh"] == "合成NDVI观测栅格"
    assert metadata["synthetic"] is True


def test_default_raster_alias_prefers_ndvi_semantics():
    alias = _default_raster_alias_zh(
        {"type": "spectral_index"},
        Path("data_agent/test_data/twm_bishan_demo/real_imagery/sentinel2_l2a_ndvi.tif"),
    )

    assert alias == "Sentinel-2 L2A NDVI观测栅格"
