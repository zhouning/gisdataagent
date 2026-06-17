"""Tests for the Sedona raster clipping smoke helpers."""

from scripts.smoke_mmfe_sedona_raster_clip import (
    _join_uri,
    _looks_like_tiff,
    _s3a_to_s3_uri,
    _safe_slug,
)


def test_join_uri_normalizes_slashes():
    assert _join_uri("s3a://bucket/prefix/", "/geotiff/", "a.tif") == "s3a://bucket/prefix/geotiff/a.tif"
    assert _join_uri("s3a://bucket/prefix") == "s3a://bucket/prefix"


def test_s3a_to_s3_uri_converts_scheme_only():
    assert _s3a_to_s3_uri("s3a://bucket/key.tif") == "s3://bucket/key.tif"
    assert _s3a_to_s3_uri("file:///tmp/key.tif") == "file:///tmp/key.tif"


def test_safe_slug_keeps_object_key_friendly_characters():
    assert _safe_slug("PRJ-DEMO-0046/REAL S2") == "PRJ-DEMO-0046-REAL-S2"
    assert _safe_slug("   ") == "item"


def test_looks_like_tiff_accepts_little_and_big_endian_headers():
    assert _looks_like_tiff(b"II*\x00rest")
    assert _looks_like_tiff(b"MM\x00*rest")
    assert not _looks_like_tiff(b"not-a-tiff")
