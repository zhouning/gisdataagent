"""Tests for the Python MinIO materialization smoke script."""

import argparse
import hashlib
import mimetypes
import unittest
from pathlib import Path

from scripts.smoke_mmfe_minio_materialize import run_smoke


class TestMMFEMinioMaterializeSmoke(unittest.TestCase):
    def test_run_smoke_materializes_manifest_and_business_output_with_injected_executor(self):
        manifest = Path(
            "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/"
            "twm_mmfe_semantic_product.json"
        )
        self.assertTrue(manifest.exists(), f"missing fixture: {manifest}")
        stored = {}

        def executor(payload):
            source = Path(payload["source_path"])
            body = source.read_bytes()
            target_uri = payload["target_uri"]
            bucket, key = target_uri[5:].split("/", 1)
            stored[(bucket, key)] = body
            return {
                "materialized": True,
                "published_count": 1,
                "target": "s3",
                "source_path": str(source),
                "target_uri": target_uri,
                "bucket": bucket,
                "key": key,
                "endpoint_url": "http://minio:9000",
                "bytes_written": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "content_type": "application/json" if source.suffix == ".json" else "text/csv",
            }

        def reader(bucket, key):
            return stored[(bucket, key)]

        args = argparse.Namespace(
            manifest=manifest,
            endpoint_url="http://minio:9000",
            access_key_id="minio_admin",
            secret_access_key="local_dev_minio_secret",
            region_name="us-east-1",
            bucket="gis-agent-lakehouse",
            prefix="curated/mmfe",
            include_geoparquet=False,
        )

        summary = run_smoke(args, executor=executor, reader=reader)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["product_id"], "sfp-twm-dc2a707aabda0c01")
        self.assertEqual(summary["uploaded_count"], 2)
        self.assertEqual(summary["prefix"], "curated/mmfe/sfp-twm-dc2a707aabda0c01")
        target_uris = {upload["target_uri"] for upload in summary["uploads"]}
        self.assertIn(
            "s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
            "twm_mmfe_semantic_product.json",
            target_uris,
        )
        self.assertIn(
            "s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
            "twm_mmfe_business_view.csv",
            target_uris,
        )

    def test_run_smoke_can_materialize_generated_geoparquet_fixture(self):
        manifest = Path(
            "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/"
            "twm_mmfe_semantic_product.json"
        )
        self.assertTrue(manifest.exists(), f"missing fixture: {manifest}")
        stored = {}

        def executor(payload):
            source = Path(payload["source_path"])
            body = source.read_bytes()
            target_uri = payload["target_uri"]
            bucket, key = target_uri[5:].split("/", 1)
            stored[(bucket, key)] = body
            content_type, _ = mimetypes.guess_type(str(source))
            if source.suffix.lower() in {".parquet", ".geoparquet", ".parq"}:
                content_type = "application/vnd.apache.parquet"
            return {
                "materialized": True,
                "published_count": 1,
                "target": "s3",
                "source_path": str(source),
                "target_uri": target_uri,
                "bucket": bucket,
                "key": key,
                "endpoint_url": "http://minio:9000",
                "bytes_written": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "content_type": content_type or "application/octet-stream",
            }

        def reader(bucket, key):
            return stored[(bucket, key)]

        args = argparse.Namespace(
            manifest=manifest,
            endpoint_url="http://minio:9000",
            access_key_id="minio_admin",
            secret_access_key="local_dev_minio_secret",
            region_name="us-east-1",
            bucket="gis-agent-lakehouse",
            prefix="curated/mmfe",
            include_geoparquet=True,
        )

        summary = run_smoke(args, executor=executor, reader=reader)

        self.assertEqual(summary["status"], "ok")
        self.assertTrue(summary["geoparquet_included"])
        self.assertEqual(summary["uploaded_count"], 3)
        geoparquet_uploads = [
            upload for upload in summary["uploads"] if upload["target_uri"].endswith(".geoparquet")
        ]
        self.assertEqual(len(geoparquet_uploads), 1)
        self.assertEqual(geoparquet_uploads[0]["content_type"], "application/vnd.apache.parquet")
        bucket, key = geoparquet_uploads[0]["target_uri"][5:].split("/", 1)
        self.assertIn((bucket, key), stored)
        self.assertGreater(len(stored[(bucket, key)]), 0)


if __name__ == "__main__":
    unittest.main()
