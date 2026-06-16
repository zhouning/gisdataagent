"""Tests for MMFE analytical lakehouse publisher contracts."""

import unittest


def _semantic_manifest() -> dict:
    return {
        "product_type": "semantic_fusion_product",
        "version": "1.1",
        "product_id": "sfp-lakehouse-test",
        "business_output": {
            "path": "s3://geo-lake/curated/fusion/run-001/fused.parquet",
            "format": "GeoParquet",
            "row_count": 2,
            "column_count": 4,
            "crs": "EPSG:4326",
        },
        "sources": [
            {"path": "s3://geo-lake/raw/parcels/date=2026-06-16/data.parquet", "data_type": "vector"},
            {"path": "s3://geo-lake/raw/zoning/date=2026-06-16/data.parquet", "data_type": "vector"},
        ],
        "lineage": {
            "operation": "spatial_join",
            "source_count": 2,
        },
        "quality": {
            "score": 0.97,
            "warnings": [],
        },
        "ai_metadata": {
            "embedding_ready": True,
            "chunks": [
                {
                    "chunk_id": "fusion:product",
                    "text": "Semantic fusion product generated with spatial_join.",
                    "metadata": {"strategy": "spatial_join"},
                }
            ],
        },
    }


class TestLakehousePublisher(unittest.TestCase):
    def test_build_iceberg_publish_spec_from_semantic_manifest(self):
        from data_agent.fusion.lakehouse_publisher import (
            ICEBERG_PUBLISH_SCHEMA,
            build_iceberg_publish_spec,
        )

        spec = build_iceberg_publish_spec(
            _semantic_manifest(),
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
            object_store="s3",
            spatial_engine="sedona",
            partition_by=["product_id"],
            metadata={"run_id": "lakehouse-test"},
        )

        self.assertEqual(spec["schema"], ICEBERG_PUBLISH_SCHEMA)
        self.assertEqual(spec["target"], "iceberg")
        self.assertEqual(spec["object_store"], "s3")
        self.assertEqual(spec["warehouse_uri"], "s3://geo-lake/warehouse")
        self.assertEqual(spec["catalog"], "prod")
        self.assertEqual(spec["namespace"], "gis.fusion")
        self.assertEqual(spec["table"], "semantic_products")
        self.assertEqual(spec["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(spec["spatial_engine"], "sedona")
        self.assertEqual(spec["partition_by"], ["product_id"])
        self.assertEqual(spec["product_id"], "sfp-lakehouse-test")
        self.assertEqual(spec["business_output"]["format"], "GeoParquet")
        self.assertEqual(spec["business_output"]["path"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")
        self.assertEqual(spec["lineage"]["operation"], "spatial_join")
        self.assertEqual(spec["metadata"]["run_id"], "lakehouse-test")

    def test_run_iceberg_publish_uses_injected_executor(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            run_iceberg_publish,
        )

        spec = build_iceberg_publish_spec(
            _semantic_manifest(),
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
            spatial_engine="sedona",
        )
        calls = []

        def executor(payload):
            calls.append(payload)
            return {"committed": True, "snapshot_id": "snap-001", "rows_written": payload["row_count"]}

        publisher = build_iceberg_publisher(executor=executor)

        result = run_iceberg_publish(spec, publisher=publisher)

        self.assertTrue(result["valid"])
        self.assertEqual(result["target"], "iceberg")
        self.assertEqual(result["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(calls[0]["target"], "iceberg")
        self.assertEqual(calls[0]["storage_layer"], "analytical_lakehouse")
        self.assertEqual(calls[0]["object_store"], "s3")
        self.assertEqual(calls[0]["spatial_engine"], "sedona")
        self.assertEqual(calls[0]["source_path"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")
        self.assertEqual(calls[0]["source_format"], "GeoParquet")
        self.assertEqual(calls[0]["row_count"], 2)
        self.assertEqual(calls[0]["lineage"]["operation"], "spatial_join")
        self.assertEqual(result["backend_result"]["snapshot_id"], "snap-001")

    def test_iceberg_publish_requires_executor_and_valid_spec(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            run_iceberg_publish,
            validate_iceberg_publish_spec,
        )

        invalid_errors = validate_iceberg_publish_spec(
            {
                "schema": "mmfe.iceberg_publish.v1",
                "target": "iceberg",
                "catalog": "",
                "namespace": "",
                "table": "",
                "warehouse_uri": "",
                "business_output": {"path": "", "format": ""},
            }
        )

        self.assertTrue(any("catalog" in error for error in invalid_errors))
        self.assertTrue(any("namespace" in error for error in invalid_errors))
        self.assertTrue(any("table" in error for error in invalid_errors))
        self.assertTrue(any("warehouse_uri" in error for error in invalid_errors))
        self.assertTrue(any("business_output.path" in error for error in invalid_errors))

        spec = build_iceberg_publish_spec(
            _semantic_manifest(),
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
        )
        publisher = build_iceberg_publisher()

        result = run_iceberg_publish(spec, publisher=publisher)

        self.assertFalse(result["valid"])
        self.assertTrue(any("executor is required" in error for error in result["errors"]))

    def test_lakehouse_publisher_helpers_are_reexported(self):
        from data_agent.fusion import (
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            run_iceberg_publish,
        )
        from data_agent.fusion_engine import (
            build_iceberg_publish_spec as proxy_build_iceberg_publish_spec,
            build_iceberg_publisher as proxy_build_iceberg_publisher,
            run_iceberg_publish as proxy_run_iceberg_publish,
        )

        self.assertTrue(callable(build_iceberg_publish_spec))
        self.assertTrue(callable(build_iceberg_publisher))
        self.assertTrue(callable(run_iceberg_publish))
        self.assertTrue(callable(proxy_build_iceberg_publish_spec))
        self.assertTrue(callable(proxy_build_iceberg_publisher))
        self.assertTrue(callable(proxy_run_iceberg_publish))


if __name__ == "__main__":
    unittest.main()
