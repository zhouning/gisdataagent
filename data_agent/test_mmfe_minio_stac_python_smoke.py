"""Tests for the Python MinIO STAC smoke script."""

import argparse
import unittest
from pathlib import Path

from scripts.smoke_mmfe_minio_stac_python import run_smoke


class TestMMFEMinioStacPythonSmoke(unittest.TestCase):
    def test_run_smoke_publishes_and_reads_back_twm_stac_item(self):
        manifest = Path(
            "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/"
            "twm_mmfe_semantic_product.json"
        )
        self.assertTrue(manifest.exists(), f"missing fixture: {manifest}")
        written = {}

        def publisher(spec):
            item_id = spec["item"]["id"]
            key = f"catalog/stac/mmfe-fusion-products/{item_id}.json"
            return {
                "published": True,
                "published_count": 1,
                "target": "stac",
                "collection": spec["collection"],
                "item_id": item_id,
                "bucket": "gis-agent-lakehouse",
                "key": key,
                "item_href": f"s3://gis-agent-lakehouse/{key}",
                "endpoint_url": "http://minio:9000",
                "bytes_written": 1024,
            }

        def reader(bucket, key):
            written["bucket"] = bucket
            written["key"] = key
            return {
                "type": "Feature",
                "stac_version": "1.0.0",
                "id": "sfp-twm-dc2a707aabda0c01",
                "collection": "mmfe-fusion-products",
                "bbox": [],
                "geometry": None,
                "properties": {"datetime": "2026-06-16T00:00:00Z"},
                "assets": {
                    "data": {
                        "href": "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/"
                        "twm_mmfe_business_view.csv",
                        "type": "text/csv",
                        "roles": ["data"],
                    }
                },
                "links": [],
            }

        args = argparse.Namespace(
            manifest=manifest,
            endpoint_url="http://minio:9000",
            access_key_id="minio_admin",
            secret_access_key="local_dev_minio_secret",
            region_name="us-east-1",
            catalog_uri="s3://gis-agent-lakehouse/catalog/stac",
            collection="mmfe-fusion-products",
            asset_href="",
            expect_product_id="sfp-twm-dc2a707aabda0c01",
        )

        summary = run_smoke(args, publisher=publisher, reader=reader)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["product_id"], "sfp-twm-dc2a707aabda0c01")
        self.assertEqual(summary["read_back_id"], "sfp-twm-dc2a707aabda0c01")
        self.assertEqual(summary["collection"], "mmfe-fusion-products")
        self.assertEqual(written["bucket"], "gis-agent-lakehouse")
        self.assertEqual(written["key"], "catalog/stac/mmfe-fusion-products/sfp-twm-dc2a707aabda0c01.json")


if __name__ == "__main__":
    unittest.main()
