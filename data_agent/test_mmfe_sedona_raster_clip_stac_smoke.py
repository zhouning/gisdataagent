"""Tests for STAC registration of Sedona-derived raster clips."""

import argparse
import unittest

from scripts.smoke_mmfe_sedona_raster_clip_stac import build_raster_clip_stac_item, run_smoke


def _artifact() -> dict:
    return {
        "relation_id": "PROJECT_NDVI_CLIP-PRJ-DEMO-0046-REAL-S2-L2A-NDVI",
        "project_id": "PRJ-DEMO-0046",
        "project_name": "璧山世界模型合成项目47",
        "risk_scenario": "planning_agricultural_conflict",
        "review_priority": "high",
        "raster_product_id": "REAL-S2-L2A-NDVI",
        "raster_alias_zh": "Sentinel-2 L2A NDVI观测栅格",
        "raster_srid": 32648,
        "clipped_width": 9,
        "clipped_height": 9,
        "ndvi_valid_pixel_count": 16.0,
        "ndvi_mean": 0.7790635526180267,
        "ndvi_min": 0.541849672794342,
        "ndvi_max": 0.9969075322151184,
        "geotiff_size_bytes": 708,
        "relation_type": "PROJECT_NDVI_CLIPPED_GEOTIFF",
        "left_role": "territorial_project",
        "right_role": "remote_sensing_ndvi_observation",
        "semantic_metric": "project_ndvi_clipped_geotiff",
        "source_crs": "EPSG:4326",
        "raster_crs": "EPSG:32648",
        "computed_by": "apache_sedona_rs_clip_as_geotiff",
        "artifact_href": "s3://gis-agent-lakehouse/curated/mmfe/demo/geotiff/clip.tif",
        "content_type": "image/tiff; application=geotiff",
        "not_for_production": True,
    }


class TestMMFESedonaRasterClipStacSmoke(unittest.TestCase):
    def test_build_raster_clip_stac_item_maps_artifact_semantics(self):
        item = build_raster_clip_stac_item(
            _artifact(),
            collection="mmfe-derived-raster-assets",
            catalog_uri="s3://gis-agent-lakehouse/catalog/stac",
            clip_summary={
                "output_uri": "s3a://gis-agent-lakehouse/curated/mmfe/demo",
                "manifest_uri": "s3a://gis-agent-lakehouse/curated/mmfe/demo/manifest",
                "raster_file": "real_imagery/sentinel2_l2a_ndvi.tif",
            },
            item_datetime="2026-06-17T00:00:00Z",
        )

        self.assertEqual(item["id"], "PROJECT_NDVI_CLIP-PRJ-DEMO-0046-REAL-S2-L2A-NDVI")
        self.assertEqual(item["collection"], "mmfe-derived-raster-assets")
        self.assertEqual(item["assets"]["data"]["href"], "s3://gis-agent-lakehouse/curated/mmfe/demo/geotiff/clip.tif")
        self.assertEqual(item["assets"]["data"]["roles"], ["data", "derived", "raster", "ndvi"])
        self.assertEqual(item["properties"]["proj:epsg"], 32648)
        self.assertEqual(item["properties"]["twm:project_id"], "PRJ-DEMO-0046")
        self.assertEqual(item["properties"]["ndvi:mean"], 0.7790635526180267)
        self.assertEqual(item["properties"]["mmfe:semantic_metric"], "project_ndvi_clipped_geotiff")

    def test_run_smoke_publishes_and_reads_back_clip_items(self):
        written = {}

        def publisher(spec):
            item = spec["item"]
            key = f"catalog/stac/{spec['collection']}/{item['id']}.json"
            written[key] = item
            return {
                "published": True,
                "published_count": 1,
                "target": "stac",
                "collection": spec["collection"],
                "item_id": item["id"],
                "bucket": "gis-agent-lakehouse",
                "key": key,
                "item_href": f"s3://gis-agent-lakehouse/{key}",
                "bytes_written": 123,
            }

        def reader(bucket, key):
            self.assertEqual(bucket, "gis-agent-lakehouse")
            return written[key]

        args = argparse.Namespace(
            collection="mmfe-derived-raster-assets",
            catalog_uri="s3://gis-agent-lakehouse/catalog/stac",
            endpoint_url="http://minio:9000",
            access_key_id="minio_admin",
            secret_access_key="local_dev_minio_secret",
            region_name="us-east-1",
        )
        summary = run_smoke(
            args,
            clip_summary={
                "status": "ok",
                "output_uri": "s3a://gis-agent-lakehouse/curated/mmfe/demo",
                "manifest_uri": "s3a://gis-agent-lakehouse/curated/mmfe/demo/manifest",
                "raster_file": "real_imagery/sentinel2_l2a_ndvi.tif",
                "artifacts": [_artifact()],
            },
            publisher=publisher,
            reader=reader,
        )

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["published_count"], 1)
        self.assertEqual(summary["published"][0]["asset_href"], _artifact()["artifact_href"])
        self.assertEqual(summary["read_back_items"][0]["proj_epsg"], 32648)


if __name__ == "__main__":
    unittest.main()
