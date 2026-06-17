"""Tests for host-side COG materialization of MMFE raster clips."""

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from scripts.smoke_mmfe_rasterio_cog_materialize import (
    COG_MEDIA_TYPE,
    build_cog_artifact,
    build_cog_stac_item,
    default_raster_alias_zh,
    discover_clip_files,
    parse_clip_filename,
    run_smoke,
    validate_cog_metadata,
)


def _project() -> dict:
    return {
        "project_id": "PRJ-DEMO-0046",
        "project_name": "璧山世界模型合成项目47",
        "XMDM": "XMDM0000000000000000000000000047",
        "XMMC": "璧山世界模型合成项目47",
        "risk_scenario": "planning_agricultural_conflict",
        "review_priority": "high",
    }


def _metadata() -> dict:
    return {
        "driver": "GTiff",
        "width": 9,
        "height": 9,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32648",
        "epsg": 32648,
        "nodata": -9999.0,
        "bounds": [620000.0, 3299000.0, 620540.0, 3299540.0],
        "transform": [60.0, 0.0, 620000.0, 0.0, -60.0, 3299540.0],
        "layout": "COG",
        "compression": "DEFLATE",
        "interleave": "BAND",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "overviews": [],
        "valid_pixel_count": 16,
        "min": 0.54,
        "mean": 0.78,
        "max": 0.99,
    }


class TestMMFERasterioCogMaterializeSmoke(unittest.TestCase):
    def test_parse_clip_filename_and_discovery_skip_existing_cogs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            clip = directory / "PRJ-DEMO-0046_REAL-S2-L2A-NDVI_ndvi_clip.tif"
            cog = directory / "PRJ-DEMO-0046_REAL-S2-L2A-NDVI_ndvi_clip.cog.tif"
            other = directory / "notes.txt"
            clip.write_bytes(b"II*\x00clip")
            cog.write_bytes(b"II*\x00cog")
            other.write_text("skip", encoding="utf-8")

            self.assertEqual(parse_clip_filename(clip), ("PRJ-DEMO-0046", "REAL-S2-L2A-NDVI"))
            self.assertEqual(discover_clip_files(directory, "*_ndvi_clip.tif"), [clip])

    def test_build_cog_artifact_and_stac_item_preserve_semantics(self):
        artifact = build_cog_artifact(
            source_path=Path("PRJ-DEMO-0046_REAL-S2-L2A-NDVI_ndvi_clip.tif"),
            cog_path=Path("PRJ-DEMO-0046_REAL-S2-L2A-NDVI_ndvi_clip.cog.tif"),
            project_id="PRJ-DEMO-0046",
            raster_product_id="REAL-S2-L2A-NDVI",
            project=_project(),
            raster_product={
                "product_id": "REAL-S2-L2A-NDVI",
                "type": "spectral_index",
                "formula": "NDVI=(NIR-Red)/(NIR+Red)",
            },
            cog_metadata=_metadata(),
            materialized={
                "target_uri": "s3://gis-agent-lakehouse/curated/mmfe/demo/cog/clip.cog.tif",
                "bucket": "gis-agent-lakehouse",
                "key": "curated/mmfe/demo/cog/clip.cog.tif",
                "sha256": "abc123",
                "bytes_written": 1826,
            },
            source_asset_base_uri="s3://gis-agent-lakehouse/curated/mmfe/demo/geotiff",
        )
        item = build_cog_stac_item(
            artifact,
            collection="mmfe-derived-raster-cog-assets",
            catalog_uri="s3://gis-agent-lakehouse/catalog/stac",
            item_datetime="2026-06-17T00:00:00Z",
        )

        self.assertEqual(artifact["raster_alias_zh"], "Sentinel-2 L2A NDVI观测栅格")
        self.assertEqual(item["id"], "PROJECT_NDVI_COG-PRJ-DEMO-0046-REAL-S2-L2A-NDVI")
        self.assertEqual(item["collection"], "mmfe-derived-raster-cog-assets")
        self.assertEqual(item["assets"]["data"]["href"], "s3://gis-agent-lakehouse/curated/mmfe/demo/cog/clip.cog.tif")
        self.assertEqual(item["assets"]["data"]["type"], COG_MEDIA_TYPE)
        self.assertIn("cog", item["assets"]["data"]["roles"])
        self.assertEqual(item["properties"]["proj:epsg"], 32648)
        self.assertEqual(item["properties"]["raster:layout"], "COG")
        self.assertEqual(item["properties"]["twm:project_name"], "璧山世界模型合成项目47")
        self.assertEqual(item["properties"]["ndvi:mean"], 0.78)
        self.assertEqual(item["properties"]["file:checksum_sha256"], "abc123")

    def test_run_smoke_converts_materializes_publishes_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "clips"
            output_dir = root / "cogs"
            data_dir = root / "data"
            source_dir.mkdir()
            data_dir.mkdir()
            source = source_dir / "PRJ-DEMO-0046_REAL-S2-L2A-NDVI_ndvi_clip.tif"
            source.write_bytes(b"plain geotiff bytes")
            (data_dir / "synthetic_projects.geojson").write_text(
                json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": _project()}]}),
                encoding="utf-8",
            )
            imagery_manifest = data_dir / "real_imagery_manifest.json"
            imagery_manifest.write_text(
                json.dumps(
                    {
                        "products": {
                            "sentinel2_l2a_ndvi": {
                                "product_id": "REAL-S2-L2A-NDVI",
                                "type": "spectral_index",
                                "formula": "NDVI=(NIR-Red)/(NIR+Red)",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            objects = {}
            stac_items = {}
            catalog_docs = {}

            def converter(source_path, target_path, **kwargs):
                self.assertEqual(source_path, source)
                target_path.write_bytes(b"optimized cog bytes")
                return dict(_metadata())

            def materializer(payload):
                body = Path(payload["source_path"]).read_bytes()
                key = "curated/mmfe/demo/cog/" + Path(payload["source_path"]).name
                objects[key] = body
                return {
                    "materialized": True,
                    "target_uri": payload["target_uri"],
                    "bucket": "gis-agent-lakehouse",
                    "key": key,
                    "sha256": "sha256-placeholder",
                    "bytes_written": len(body),
                }

            def object_reader(bucket, key):
                self.assertEqual(bucket, "gis-agent-lakehouse")
                return objects[key]

            def stac_publisher(spec):
                item = spec["item"]
                key = f"catalog/stac/{spec['collection']}/{item['id']}.json"
                stac_items[key] = item
                return {
                    "published": True,
                    "published_count": 1,
                    "target": "stac",
                    "collection": spec["collection"],
                    "item_id": item["id"],
                    "bucket": "gis-agent-lakehouse",
                    "key": key,
                    "item_href": f"s3://gis-agent-lakehouse/{key}",
                }

            def stac_reader(bucket, key):
                self.assertEqual(bucket, "gis-agent-lakehouse")
                return stac_items[key]

            def catalog_publisher(payload):
                collection_id = payload["collections"][0]["id"]
                catalog_key = "catalog/stac/catalog.json"
                collection_key = f"catalog/stac/{collection_id}/collection.json"
                item_links = [
                    {"rel": "item", "href": item["href"], "type": "application/geo+json", "title": item["id"]}
                    for item in payload["collections"][0]["items"]
                ]
                catalog_docs[catalog_key] = {
                    "type": "Catalog",
                    "stac_version": "1.0.0",
                    "id": payload["catalog_id"],
                    "description": payload["description"],
                    "links": [
                        {"rel": "self", "href": "s3://gis-agent-lakehouse/catalog/stac/catalog.json"},
                        {"rel": "child", "href": f"s3://gis-agent-lakehouse/{collection_key}"},
                    ],
                }
                catalog_docs[collection_key] = {
                    "type": "Collection",
                    "stac_version": "1.0.0",
                    "id": collection_id,
                    "description": payload["collections"][0]["description"],
                    "links": [
                        {"rel": "self", "href": f"s3://gis-agent-lakehouse/{collection_key}"},
                        *item_links,
                    ],
                }
                return {
                    "published": True,
                    "published_count": 2,
                    "target": "stac_static_catalog",
                    "bucket": "gis-agent-lakehouse",
                    "catalog_key": catalog_key,
                    "catalog_href": "s3://gis-agent-lakehouse/catalog/stac/catalog.json",
                    "collections": [
                        {
                            "collection": collection_id,
                            "key": collection_key,
                            "href": f"s3://gis-agent-lakehouse/{collection_key}",
                            "item_count": len(item_links),
                        }
                    ],
                }

            def catalog_reader(bucket, key):
                self.assertEqual(bucket, "gis-agent-lakehouse")
                return catalog_docs[key]

            args = argparse.Namespace(
                source_dir=source_dir,
                source_glob="*_ndvi_clip.tif",
                local_output_dir=output_dir,
                target_uri="s3://gis-agent-lakehouse/curated/mmfe/demo/cog",
                source_asset_base_uri="s3://gis-agent-lakehouse/curated/mmfe/demo/geotiff",
                data_dir=data_dir,
                projects_file="synthetic_projects.geojson",
                real_imagery_manifest=imagery_manifest,
                catalog_uri="s3://gis-agent-lakehouse/catalog/stac",
                collection="mmfe-derived-raster-cog-assets",
                endpoint_url="http://localhost:9000",
                access_key_id="minio_admin",
                secret_access_key="local_dev_minio_secret",
                region_name="us-east-1",
                compress="DEFLATE",
                blocksize=512,
                max_assets=0,
            )
            summary = run_smoke(
                args,
                converter=converter,
                materializer=materializer,
                object_reader=object_reader,
                stac_publisher=stac_publisher,
                stac_reader=stac_reader,
                catalog_publisher=catalog_publisher,
                catalog_reader=catalog_reader,
            )

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["cog_count"], 1)
        self.assertEqual(summary["materialized_count"], 1)
        self.assertEqual(summary["stac_published_count"], 1)
        self.assertEqual(summary["published"][0]["layout"], "COG")
        self.assertEqual(summary["published"][0]["proj_epsg"], 32648)
        self.assertIn("cog", summary["read_back_items"][0]["roles"])
        self.assertEqual(summary["static_catalog"]["published_count"], 2)
        self.assertEqual(summary["static_catalog"]["read_back_catalog_id"], "mmfe-local-static-stac")
        self.assertEqual(summary["static_catalog"]["collections"][0]["item_count"], 1)

    def test_default_raster_alias_zh_is_chinese_for_ndvi(self):
        alias = default_raster_alias_zh({"formula": "NDVI=(NIR-Red)/(NIR+Red)"}, "REAL-S2-L2A-NDVI")

        self.assertEqual(alias, "Sentinel-2 L2A NDVI观测栅格")

    @unittest.skipIf(importlib.util.find_spec("rasterio") is None, "rasterio is not installed")
    def test_real_rasterio_cog_conversion_metadata_validation(self):
        import numpy as np
        import rasterio
        from rasterio.shutil import copy as rio_copy
        from rasterio.transform import from_origin

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.tif"
            cog = Path(tmp) / "source.cog.tif"
            profile = {
                "driver": "GTiff",
                "height": 8,
                "width": 8,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:32648",
                "transform": from_origin(620000, 3300000, 60, 60),
                "nodata": -9999.0,
            }
            with rasterio.open(source, "w", **profile) as dataset:
                dataset.write(np.arange(64, dtype="float32").reshape(8, 8), 1)
            rio_copy(str(source), str(cog), driver="COG", compress="DEFLATE", blocksize=512)

            metadata = validate_cog_metadata(cog, source_path=source)

        self.assertEqual(metadata["layout"], "COG")
        self.assertTrue(metadata["tiled"])
        self.assertEqual(metadata["epsg"], 32648)
        self.assertEqual(metadata["width"], 8)
        self.assertEqual(metadata["height"], 8)


if __name__ == "__main__":
    unittest.main()
