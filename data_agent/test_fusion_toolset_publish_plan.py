"""Tests for the MMFE semantic product publish-plan ADK tool."""

import asyncio
import json
import os
import tempfile
import unittest


def _semantic_manifest() -> dict:
    return {
        "product_type": "semantic_fusion_product",
        "version": "1.1",
        "product_id": "sfp-toolset-plan-test",
        "business_output": {
            "path": "s3://geo-lake/curated/fusion/run-001/fused.parquet",
            "format": "GeoParquet",
            "row_count": 2,
            "column_count": 4,
            "crs": "EPSG:4326",
        },
        "sources": [
            {"path": "s3://geo-lake/raw/parcels/data.parquet", "data_type": "vector"},
            {"path": "s3://geo-lake/raw/zoning/data.parquet", "data_type": "vector"},
        ],
        "lineage": {"operation": "spatial_join"},
        "quality": {"score": 0.97, "warnings": []},
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


class TestPlanSemanticProductPublishTool(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_plan_semantic_product_publish_builds_valid_dry_run_from_json(self):
        from data_agent.toolsets.fusion_tools import plan_semantic_product_publish

        result_text = self._run(
            plan_semantic_product_publish(
                manifest_json=json.dumps(_semantic_manifest()),
                targets="iceberg,stac,lancedb",
                iceberg_catalog="prod",
                iceberg_namespace="gis.fusion",
                iceberg_table="semantic_products",
                iceberg_warehouse_uri="s3://geo-lake/warehouse",
                stac_collection="mmfe-fusion-products",
                stac_catalog_uri="s3://geo-lake/catalog/stac",
                vector_target="lancedb",
                vector_collection="mmfe_products",
                embedding_model="mock-embedder",
                iceberg_publisher_configured="true",
                stac_publisher_configured="true",
                vector_publisher_configured="true",
                embedder_configured="true",
            )
        )

        result = json.loads(result_text)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["plan"]["valid"])
        self.assertEqual(result["summary"]["target_count"], 3)
        self.assertEqual(result["summary"]["valid_step_count"], 3)
        self.assertEqual(result["summary"]["invalid_step_count"], 0)
        self.assertEqual(result["plan"]["targets"], ["iceberg", "stac", "lancedb"])
        self.assertEqual(
            [step["target"] for step in result["plan"]["steps"]],
            ["iceberg", "stac", "lancedb"],
        )
        self.assertEqual(result["plan"]["steps"][1]["depends_on"], ["iceberg"])
        self.assertEqual(result["plan"]["steps"][2]["depends_on"], ["iceberg"])
        self.assertEqual(result["plan"]["steps"][0]["schema"], "mmfe.iceberg_publish.v1")
        self.assertEqual(result["plan"]["steps"][1]["schema"], "mmfe.stac_publish.v1")
        self.assertEqual(result["plan"]["steps"][2]["schema"], "mmfe.semantic_vector_publish.v1")
        self.assertEqual(
            result["plan"]["steps"][0]["spec"]["table_identifier"],
            "prod.gis.fusion.semantic_products",
        )
        self.assertEqual(result["plan"]["steps"][2]["spec"]["target"], "lancedb")
        self.assertTrue(result["plan"]["steps"][2]["execution"]["embedder_configured"])

    def test_plan_semantic_product_publish_reads_manifest_path_and_reports_missing_backends(self):
        from data_agent.toolsets.fusion_tools import plan_semantic_product_publish

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = os.path.join(tmp, "product.semantic.json")
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(_semantic_manifest(), fh)

            result_text = self._run(
                plan_semantic_product_publish(
                    manifest_path=manifest_path,
                    targets="iceberg,pgvector",
                    iceberg_catalog="prod",
                    iceberg_namespace="gis.fusion",
                    iceberg_table="semantic_products",
                    iceberg_warehouse_uri="s3://geo-lake/warehouse",
                    vector_target="pgvector",
                    vector_collection="mmfe_products",
                    embedding_model="mock-embedder",
                )
            )

        result = json.loads(result_text)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["plan"]["valid"])
        self.assertEqual(result["summary"]["target_count"], 2)
        self.assertEqual(result["summary"]["invalid_step_count"], 2)
        self.assertTrue(
            any("publisher is required" in message for error in result["plan"]["errors"] for message in error["errors"])
        )
        self.assertTrue(
            any("embedder is required" in message for error in result["plan"]["errors"] for message in error["errors"])
        )

    def test_plan_semantic_product_publish_rejects_invalid_manifest_json(self):
        from data_agent.toolsets.fusion_tools import plan_semantic_product_publish

        result = json.loads(
            self._run(plan_semantic_product_publish(manifest_json="{not-json"))
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("invalid manifest_json", result["message"])

    def test_plan_semantic_product_publish_is_registered_in_fusion_toolset(self):
        from data_agent.toolsets.fusion_tools import FusionToolset, _ALL_FUNCS

        func_names = [func.__name__ for func in _ALL_FUNCS]
        self.assertIn("plan_semantic_product_publish", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("plan_semantic_product_publish", {tool.name for tool in tools})


if __name__ == "__main__":
    unittest.main()
