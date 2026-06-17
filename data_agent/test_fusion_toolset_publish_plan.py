"""Tests for the MMFE semantic product publish-plan ADK tool."""

import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock


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


def _production_ready_semantic_manifest() -> dict:
    manifest = _semantic_manifest()
    manifest["mmfe_bundle"] = {
        "semantic_diagnostic_summary": {
            "readiness_score": 1.0,
            "validation_ready": True,
            "production_ready": True,
            "status": "production_ready",
            "check_count": 1,
            "pass_count": 1,
            "warn_count": 0,
            "fail_count": 0,
        },
        "semantic_diagnostic_top_gaps": [],
        "semantic_diagnostic_recommendations_zh": [],
    }
    return manifest


class TestPlanSemanticProductPublishTool(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_preflight_mmfe_lakehouse_infrastructure_blocks_local_production(self):
        from data_agent.toolsets.fusion_tools import preflight_mmfe_lakehouse_infrastructure

        result = json.loads(
            self._run(
                preflight_mmfe_lakehouse_infrastructure(
                    environment="production",
                    env_json=json.dumps(
                        {
                            "AWS_ENDPOINT_URL": "http://minio:9000",
                            "AWS_ACCESS_KEY_ID": "minio_admin",
                            "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
                            "AWS_S3_BUCKET": "gis-agent-uploads",
                            "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                        }
                    ),
                )
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["summary"]["valid"])
        self.assertEqual(result["summary"]["environment"], "production")
        self.assertGreaterEqual(result["summary"]["critical_fail_count"], 2)
        self.assertTrue(any("production_endpoint" in error for error in result["errors"]))
        self.assertTrue(any("production_credentials" in error for error in result["errors"]))
        self.assertEqual(result["preflight"]["schema"], "mmfe.infrastructure_preflight.v1")
        self.assertEqual(
            result["preflight"]["sanitized_config"]["object_store"]["secret_access_key"],
            "lo***et",
        )

    def test_preflight_mmfe_lakehouse_infrastructure_allows_local_validation(self):
        from data_agent.toolsets.fusion_tools import preflight_mmfe_lakehouse_infrastructure

        result = json.loads(
            self._run(
                preflight_mmfe_lakehouse_infrastructure(
                    environment="validation",
                    env_json=json.dumps(
                        {
                            "AWS_ENDPOINT_URL": "http://minio:9000",
                            "AWS_ACCESS_KEY_ID": "minio_admin",
                            "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
                            "AWS_S3_BUCKET": "gis-agent-uploads",
                            "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                        }
                    ),
                )
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(result["summary"]["environment"], "validation")
        self.assertEqual(result["summary"]["fail_count"], 0)
        self.assertTrue(any("development_endpoint" in warning for warning in result["warnings"]))

    def test_preflight_mmfe_lakehouse_infrastructure_reports_config_drift(self):
        from data_agent.fusion.lakehouse_config import build_lakehouse_publish_defaults
        from data_agent.toolsets.fusion_tools import preflight_mmfe_lakehouse_infrastructure

        config = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
            }
        )
        config["iceberg"]["warehouse_uri"] = "s3://other-gis-lakehouse/warehouse"
        config["sedona_spark_conf"]["spark.hadoop.fs.s3a.endpoint"] = "https://s3.us-west-2.amazonaws.com"

        result = json.loads(
            self._run(
                preflight_mmfe_lakehouse_infrastructure(
                    environment="production",
                    config_json=json.dumps(config),
                )
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["summary"]["valid"])
        self.assertTrue(any("lakehouse_bucket_consistency" in error for error in result["errors"]))
        self.assertTrue(any("spark_endpoint_consistency" in error for error in result["errors"]))

    def test_preflight_mmfe_lakehouse_infrastructure_rejects_invalid_json(self):
        from data_agent.toolsets.fusion_tools import preflight_mmfe_lakehouse_infrastructure

        result = json.loads(
            self._run(preflight_mmfe_lakehouse_infrastructure(config_json="{not-json"))
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("invalid config_json", result["message"])

    def test_plan_semantic_product_publish_builds_valid_dry_run_from_json(self):
        from data_agent.toolsets.fusion_tools import plan_semantic_product_publish

        result_text = self._run(
            plan_semantic_product_publish(
                manifest_json=json.dumps(_production_ready_semantic_manifest()),
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
                use_lakehouse_env_defaults="false",
            )
        )

        result = json.loads(result_text)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["plan"]["valid"])
        self.assertTrue(result["summary"]["production_gate_valid"])
        self.assertTrue(result["summary"]["infrastructure_preflight_valid"])
        self.assertTrue(result["summary"]["production_ready"])
        self.assertEqual(result["summary"]["target_count"], 3)
        self.assertEqual(result["summary"]["valid_step_count"], 5)
        self.assertEqual(result["summary"]["invalid_step_count"], 0)
        self.assertEqual(result["plan"]["targets"], ["iceberg", "stac", "lancedb"])
        self.assertEqual(
            [step["target"] for step in result["plan"]["steps"]],
            ["production_gate", "infrastructure_preflight", "iceberg", "stac", "lancedb"],
        )
        self.assertEqual(result["plan"]["steps"][3]["depends_on"], ["iceberg"])
        self.assertEqual(result["plan"]["steps"][4]["depends_on"], ["iceberg"])
        self.assertEqual(result["plan"]["steps"][0]["schema"], "mmfe.production_publish_gate.v1")
        self.assertEqual(result["plan"]["steps"][1]["schema"], "mmfe.infrastructure_preflight.v1")
        self.assertEqual(result["plan"]["steps"][2]["schema"], "mmfe.iceberg_publish.v1")
        self.assertEqual(result["plan"]["steps"][3]["schema"], "mmfe.stac_publish.v1")
        self.assertEqual(result["plan"]["steps"][4]["schema"], "mmfe.semantic_vector_publish.v1")
        self.assertEqual(
            result["plan"]["steps"][2]["spec"]["table_identifier"],
            "prod.gis.fusion.semantic_products",
        )
        self.assertEqual(result["plan"]["steps"][4]["spec"]["target"], "lancedb")
        self.assertTrue(result["plan"]["steps"][4]["execution"]["embedder_configured"])

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
                    publish_environment="validation",
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

    def test_plan_semantic_product_publish_can_use_lakehouse_env_defaults(self):
        from data_agent.toolsets.fusion_tools import plan_semantic_product_publish

        env = {
            "AWS_ENDPOINT_URL": "http://minio:9000",
            "AWS_ACCESS_KEY_ID": "minio_admin",
            "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
            "AWS_S3_BUCKET": "gis-agent-uploads",
            "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
            "MMFE_ICEBERG_CATALOG": "local",
            "MMFE_ICEBERG_NAMESPACE": "gis.fusion",
            "MMFE_ICEBERG_TABLE": "semantic_products",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result_text = self._run(
                plan_semantic_product_publish(
                    manifest_json=json.dumps(_production_ready_semantic_manifest()),
                    targets="iceberg,stac,pgvector",
                    vector_target="pgvector",
                    iceberg_publisher_configured="true",
                    stac_publisher_configured="true",
                    vector_publisher_configured="true",
                    embedder_configured="true",
                    use_lakehouse_env_defaults="true",
                    publish_environment="validation",
                )
            )

        result = json.loads(result_text)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["plan"]["valid"])
        self.assertTrue(result["summary"]["infrastructure_preflight_valid"])
        self.assertEqual(result["plan"]["steps"][2]["spec"]["catalog"], "local")
        self.assertEqual(result["plan"]["steps"][2]["spec"]["namespace"], "gis.fusion")
        self.assertEqual(result["plan"]["steps"][2]["spec"]["table"], "semantic_products")
        self.assertEqual(
            result["plan"]["steps"][2]["spec"]["warehouse_uri"],
            "s3://gis-agent-lakehouse/warehouse",
        )
        self.assertEqual(
            result["plan"]["steps"][3]["spec"]["catalog_uri"],
            "s3://gis-agent-lakehouse/catalog/stac",
        )
        self.assertEqual(result["plan"]["steps"][4]["spec"]["target"], "pgvector")

    def test_plan_semantic_product_publish_blocks_non_production_ready_twm_product(self):
        from data_agent.toolsets.fusion_tools import plan_semantic_product_publish

        manifest_path = "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json"
        result = json.loads(
            self._run(
                plan_semantic_product_publish(
                    manifest_path=manifest_path,
                    targets="iceberg,stac,pgvector",
                    iceberg_catalog="prod",
                    iceberg_namespace="gis.fusion",
                    iceberg_table="semantic_products",
                    iceberg_warehouse_uri="s3://geo-lake/warehouse",
                    stac_collection="mmfe-products",
                    vector_target="pgvector",
                    iceberg_publisher_configured="true",
                    stac_publisher_configured="true",
                    vector_publisher_configured="true",
                    embedder_configured="true",
                    publish_environment="production",
                )
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["plan"]["valid"])
        self.assertFalse(result["summary"]["production_gate_valid"])
        self.assertTrue(result["summary"]["validation_ready"])
        self.assertFalse(result["summary"]["production_ready"])
        gate = result["plan"]["production_gate"]
        self.assertEqual(gate["publish_environment"], "production")
        self.assertFalse(gate["valid"])
        self.assertIn("semantic product is not production_ready", gate["errors"])
        self.assertTrue(
            any(error["target"] == "production_gate" for error in result["plan"]["errors"])
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
        self.assertIn("preflight_mmfe_lakehouse_infrastructure", func_names)
        self.assertIn("plan_semantic_product_publish", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("preflight_mmfe_lakehouse_infrastructure", {tool.name for tool in tools})
        self.assertIn("plan_semantic_product_publish", {tool.name for tool in tools})

    def test_export_semantic_product_okf_builds_sidecar_from_json(self):
        from data_agent.toolsets.fusion_tools import export_semantic_product_okf

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "okf")
            result = json.loads(
                self._run(
                    export_semantic_product_okf(
                        manifest_json=json.dumps(_semantic_manifest()),
                        out_dir=out_dir,
                    )
                )
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["schema"], "mmfe.okf_export.v1")
            self.assertTrue(result["valid"], result["errors"])
            self.assertTrue(os.path.exists(result["index_path"]))
            self.assertTrue(os.path.exists(result["dataset_doc"]))

    def test_export_semantic_product_okf_loads_twm_sidecars_from_manifest_path(self):
        from data_agent.toolsets.fusion_tools import export_semantic_product_okf

        manifest_path = "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json"
        with tempfile.TemporaryDirectory() as tmp:
            result = json.loads(
                self._run(
                    export_semantic_product_okf(
                        manifest_path=manifest_path,
                        out_dir=os.path.join(tmp, "okf"),
                    )
                )
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["valid"], result["errors"])
            self.assertGreater(result["concept_count"], 100)
            self.assertTrue(os.path.exists(os.path.join(result["out_dir"], "twm", "state_input_contract.md")))
            self.assertTrue(os.path.exists(os.path.join(result["out_dir"], "graphs", "semantic_graph.md")))

    def test_export_semantic_product_okf_is_registered_in_fusion_toolset(self):
        from data_agent.toolsets.fusion_tools import FusionToolset, _ALL_FUNCS

        func_names = [func.__name__ for func in _ALL_FUNCS]
        self.assertIn("export_semantic_product_okf", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("export_semantic_product_okf", {tool.name for tool in tools})

    def test_build_twm_state_input_loads_twm_sidecars_from_manifest_path(self):
        from data_agent.toolsets.fusion_tools import build_twm_state_input

        manifest_path = "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json"
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "twm_state_input.json")
            result = json.loads(
                self._run(
                    build_twm_state_input(
                        manifest_path=manifest_path,
                        out_path=out_path,
                    )
                )
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["schema"], "mmfe.twm_state_input.v1")
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["relation_count"], 728)
            self.assertEqual(result["hard_constraint_relation_count"], 67)
            self.assertEqual(result["objective_binding_count"], 13)
            self.assertTrue(os.path.exists(out_path))

    def test_build_twm_state_input_is_registered_in_fusion_toolset(self):
        from data_agent.toolsets.fusion_tools import FusionToolset, _ALL_FUNCS

        func_names = [func.__name__ for func in _ALL_FUNCS]
        self.assertIn("build_twm_state_input", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("build_twm_state_input", {tool.name for tool in tools})

    def test_build_mmfe_semantic_ontology_loads_twm_sidecars_from_manifest_path(self):
        from data_agent.toolsets.fusion_tools import build_mmfe_semantic_ontology

        manifest_path = "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json"
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "mmfe_semantic_ontology.json")
            result = json.loads(
                self._run(
                    build_mmfe_semantic_ontology(
                        manifest_path=manifest_path,
                        out_path=out_path,
                    )
                )
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["schema"], "mmfe.semantic_ontology.v1")
            self.assertTrue(result["valid"], result["errors"])
            self.assertGreater(result["summary"]["field_count"], 100)
            self.assertEqual(result["summary"]["relation_type_count"], 7)
            self.assertEqual(result["summary"]["rule_count"], 7)
            self.assertEqual(result["summary"]["optimization_objective_count"], 13)
            self.assertTrue(os.path.exists(out_path))

    def test_build_mmfe_semantic_ontology_is_registered_in_fusion_toolset(self):
        from data_agent.toolsets.fusion_tools import FusionToolset, _ALL_FUNCS

        func_names = [func.__name__ for func in _ALL_FUNCS]
        self.assertIn("build_mmfe_semantic_ontology", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("build_mmfe_semantic_ontology", {tool.name for tool in tools})

    def test_trace_mmfe_semantics_loads_twm_graph_from_manifest_path(self):
        from data_agent.toolsets.fusion_tools import trace_mmfe_semantics

        manifest_path = "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json"
        result = json.loads(
            self._run(
                trace_mmfe_semantics(
                    manifest_path=manifest_path,
                    layer_role="parcel_current",
                    field_name="DLBM",
                    max_depth="4",
                    max_paths="20",
                )
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["schema"], "mmfe.semantic_trace_tool.v1")
        self.assertEqual(result["node_id"], "field:parcel_current.DLBM")
        self.assertEqual(result["source_mode"], "computed_from_semantic_graph")
        self.assertTrue(result["precomputed_trace_card_found"])
        self.assertGreaterEqual(result["value_domain_path_count"], 1)
        self.assertGreaterEqual(result["standard_source_path_count"], 1)
        self.assertTrue(
            any(
                "value_domain:gb_t_21010_2017_land_use_code"
                in [node["id"] for node in path["nodes"]]
                for path in result["trace"]["value_domain_paths"]
            )
        )
        self.assertTrue(
            any(
                "standard_source:gb-t-21010-2017"
                in [node["id"] for node in path["nodes"]]
                for path in result["trace"]["standard_source_paths"]
            )
        )

    def test_trace_mmfe_semantics_is_registered_in_fusion_toolset(self):
        from data_agent.toolsets.fusion_tools import FusionToolset, _ALL_FUNCS

        func_names = [func.__name__ for func in _ALL_FUNCS]
        self.assertIn("trace_mmfe_semantics", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("trace_mmfe_semantics", {tool.name for tool in tools})

    def test_diagnose_mmfe_semantic_product_loads_twm_sidecars_from_manifest_path(self):
        from data_agent.toolsets.fusion_tools import diagnose_mmfe_semantic_product

        manifest_path = "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json"
        result = json.loads(
            self._run(
                diagnose_mmfe_semantic_product(
                    manifest_path=manifest_path,
                )
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["schema"], "mmfe.semantic_product_diagnostic.v1")
        self.assertTrue(result["summary"]["validation_ready"])
        self.assertFalse(result["summary"]["production_ready"])
        self.assertEqual(result["summary"]["status"], "validation_ready_with_production_gaps")
        self.assertEqual(result["capabilities"]["semantic_relation_count"], 728)
        self.assertEqual(result["capabilities"]["objective_count"], 13)
        self.assertEqual(result["capabilities"]["trace_card_count"], 14)
        self.assertIn("state_input", result["sidecar_sources"])
        self.assertIn("semantic_graph", result["sidecar_sources"])
        self.assertTrue(
            any(gap["check_id"] == "production_authority" for gap in result["top_gaps"])
        )

    def test_diagnose_mmfe_semantic_product_is_registered_in_fusion_toolset(self):
        from data_agent.toolsets.fusion_tools import FusionToolset, _ALL_FUNCS

        func_names = [func.__name__ for func in _ALL_FUNCS]
        self.assertIn("diagnose_mmfe_semantic_product", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("diagnose_mmfe_semantic_product", {tool.name for tool in tools})

    def test_query_semantic_vectors_builds_query_plan_without_embedding(self):
        from data_agent.toolsets.fusion_tools import query_semantic_vectors

        result = json.loads(
            self._run(
                query_semantic_vectors(
                    query_text="永久基本农田占用",
                    target="lancedb",
                    collection="mmfe_products",
                    top_k="3",
                )
            )
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "plan")
        self.assertTrue(result["requires_query_embedding"])
        self.assertEqual(result["spec"]["schema"], "mmfe.semantic_vector_query.v1")
        self.assertEqual(result["spec"]["target"], "lancedb")
        self.assertEqual(result["spec"]["top_k"], 3)

    def test_query_semantic_vectors_rejects_execute_without_embedding(self):
        from data_agent.toolsets.fusion_tools import query_semantic_vectors

        result = json.loads(
            self._run(
                query_semantic_vectors(
                    query_text="永久基本农田占用",
                    target="lancedb",
                    collection="mmfe_products",
                    execute_query="true",
                    lancedb_dataset_uri="/tmp/mmfe-vectors",
                )
            )
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("query_embedding_json is required", result["message"])

    def test_query_semantic_vectors_is_registered_in_fusion_toolset(self):
        from data_agent.toolsets.fusion_tools import FusionToolset, _ALL_FUNCS

        func_names = [func.__name__ for func in _ALL_FUNCS]
        self.assertIn("query_semantic_vectors", func_names)

        tools = self._run(FusionToolset().get_tools())
        self.assertIn("query_semantic_vectors", {tool.name for tool in tools})


if __name__ == "__main__":
    unittest.main()
