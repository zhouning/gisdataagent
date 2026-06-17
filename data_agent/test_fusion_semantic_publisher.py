"""Tests for MMFE semantic vector publisher contracts."""

import json
import unittest
from pathlib import Path


def _semantic_manifest() -> dict:
    return {
        "product_type": "semantic_fusion_product",
        "version": "1.1",
        "product_id": "sfp-test",
        "business_output": {
            "path": "outputs/fused.geojson",
            "format": "GeoJSON",
            "row_count": 2,
            "column_count": 4,
            "crs": "EPSG:4326",
        },
        "ai_metadata": {
            "embedding_ready": True,
            "recommended_vector_targets": ["pgvector", "lancedb"],
            "chunks": [
                {
                    "chunk_id": "fusion:product",
                    "text": "Semantic fusion product generated with spatial_join.",
                    "metadata": {"strategy": "spatial_join", "row_count": 2},
                },
                {
                    "chunk_id": "fusion:feature:0",
                    "text": "Feature 0: parcel_id=P1; area=1000.0",
                    "metadata": {"quality": "high"},
                },
            ],
        },
    }


def _semantic_manifest_with_lakehouse() -> dict:
    manifest = _semantic_manifest()
    manifest["business_output"] = {
        "path": "s3://geo-lake/curated/fusion/run-001/fused.parquet",
        "format": "GeoParquet",
        "row_count": 2,
        "column_count": 4,
        "crs": "EPSG:4326",
    }
    manifest["lakehouse"] = {
        "iceberg": {
            "storage_layer": "analytical_lakehouse",
            "object_store": "s3",
            "catalog": "prod",
            "namespace": "gis.fusion",
            "table": "semantic_products",
            "table_identifier": "prod.gis.fusion.semantic_products",
            "warehouse_uri": "s3://geo-lake/warehouse",
            "snapshot_id": "snap-001",
            "partition": {"product_id": "sfp-test"},
            "spatial_engine": "sedona",
        }
    }
    return manifest


class TestSemanticVectorPublisher(unittest.TestCase):
    def test_build_semantic_vector_publish_spec_from_manifest_chunks(self):
        from data_agent.fusion.semantic_publisher import (
            SEMANTIC_VECTOR_PUBLISH_SCHEMA,
            build_semantic_vector_publish_spec,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest(),
            target="pgvector",
            collection="mmfe_semantic_products",
            embedding_model="text-embedding-004",
            metadata={"run_id": "publish-test"},
        )

        self.assertEqual(spec["schema"], SEMANTIC_VECTOR_PUBLISH_SCHEMA)
        self.assertEqual(spec["target"], "pgvector")
        self.assertEqual(spec["collection"], "mmfe_semantic_products")
        self.assertEqual(spec["embedding_model"], "text-embedding-004")
        self.assertEqual(spec["product_id"], "sfp-test")
        self.assertEqual(spec["source_manifest"]["business_output_path"], "outputs/fused.geojson")
        self.assertEqual(len(spec["records"]), 2)
        self.assertEqual(spec["records"][0]["record_id"], "sfp-test:fusion:product")
        self.assertEqual(spec["records"][0]["text"], "Semantic fusion product generated with spatial_join.")
        self.assertEqual(spec["records"][0]["metadata"]["chunk_id"], "fusion:product")
        self.assertEqual(spec["records"][0]["metadata"]["product_id"], "sfp-test")
        self.assertTrue(spec["embedding_required"])
        self.assertEqual(spec["metadata"]["run_id"], "publish-test")

    def test_build_semantic_vector_publish_spec_falls_back_to_retrieval_text(self):
        from data_agent.fusion.semantic_publisher import build_semantic_vector_publish_spec

        manifest = {
            "product_type": "semantic_fusion_product",
            "version": "1.0-demo-wrapper",
            "business_output": {
                "path": "data_agent/test_data/twm_bishan_demo/parcel_current.geojson",
                "format": "GeoJSON",
                "row_count": 4900,
                "column_count": 46,
                "crs": "EPSG:4326",
            },
            "ai_metadata": {
                "retrieval_text": "Demo semantic wrapper for TWM role parcel_current.",
                "chunks": [],
                "embedding_ready": False,
            },
            "lineage": {"strategy": "demo_wrapper"},
        }

        spec = build_semantic_vector_publish_spec(
            manifest,
            target="lancedb",
            collection="twm_validation_scaffold",
        )

        self.assertTrue(spec["product_id"].startswith("sfp-"))
        self.assertEqual(len(spec["records"]), 1)
        self.assertEqual(spec["records"][0]["text"], "Demo semantic wrapper for TWM role parcel_current.")
        self.assertEqual(spec["records"][0]["metadata"]["fallback_chunk"], True)
        self.assertEqual(spec["records"][0]["metadata"]["strategy"], "demo_wrapper")
        self.assertEqual(
            spec["records"][0]["metadata"]["business_output_path"],
            "data_agent/test_data/twm_bishan_demo/parcel_current.geojson",
        )

    def test_twm_semantic_wrappers_are_publishable_validation_fixtures(self):
        from data_agent.fusion.semantic_publisher import (
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
            validate_semantic_vector_publish_spec,
        )

        manifest_paths = sorted(Path("data_agent/test_data").glob("twm_*/*.semantic.json"))
        self.assertEqual(len(manifest_paths), 4)

        product_ids = set()
        for manifest_path in manifest_paths:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            spec = build_semantic_vector_publish_spec(
                manifest,
                target="pgvector",
                collection="twm_validation_scaffold",
                embedding_model="deterministic-test-3d",
                metadata={
                    "fixture_package": manifest_path.parent.name,
                    "fixture_manifest": manifest_path.name,
                    "usage": "mmfe_regression_validation",
                },
            )

            self.assertEqual(validate_semantic_vector_publish_spec(spec), [])
            self.assertEqual(spec["target"], "pgvector")
            self.assertEqual(spec["collection"], "twm_validation_scaffold")
            self.assertTrue(spec["product_id"].startswith("sfp-"))
            self.assertNotIn(spec["product_id"], product_ids)
            product_ids.add(spec["product_id"])
            self.assertEqual(len(spec["records"]), 1)
            self.assertEqual(spec["records"][0]["metadata"]["fallback_chunk"], True)
            self.assertEqual(
                spec["records"][0]["metadata"]["business_output_path"],
                manifest["business_output"]["path"],
            )
            self.assertIn("TWM role", spec["records"][0]["text"])

            embedded = embed_semantic_vector_records(
                spec,
                embedder=lambda texts, **kwargs: [
                    [float(len(text)), float(sum(ord(ch) for ch in text) % 997), 1.0]
                    for text in texts
                ],
            )
            self.assertTrue(embedded["valid"], embedded["errors"])
            self.assertEqual(embedded["embedded_count"], 1)
            self.assertEqual(embedded["embedding_dimension"], 3)
            self.assertFalse(embedded["spec"]["embedding_required"])

    def test_build_semantic_vector_publish_spec_carries_authoritative_lakehouse_lineage(self):
        from data_agent.fusion.semantic_publisher import build_semantic_vector_publish_spec

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest_with_lakehouse(),
            target="lancedb",
            collection="mmfe_products",
        )

        authoritative = spec["source_manifest"]["authoritative_lakehouse"]
        self.assertEqual(authoritative["target"], "iceberg")
        self.assertEqual(authoritative["storage_layer"], "analytical_lakehouse")
        self.assertEqual(authoritative["object_store"], "s3")
        self.assertEqual(authoritative["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(authoritative["snapshot_id"], "snap-001")
        self.assertEqual(authoritative["business_output_path"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")
        self.assertEqual(authoritative["spatial_engine"], "sedona")
        self.assertEqual(spec["records"][0]["metadata"]["authoritative_lakehouse"], authoritative)

    def test_validate_semantic_vector_publish_spec_reports_errors(self):
        from data_agent.fusion.semantic_publisher import validate_semantic_vector_publish_spec

        errors = validate_semantic_vector_publish_spec(
            {
                "schema": "mmfe.semantic_vector_publish.v1",
                "target": "unsupported-store",
                "collection": "",
                "records": [{"record_id": "", "text": "", "metadata": "bad"}],
            }
        )

        self.assertTrue(any("target" in error for error in errors))
        self.assertTrue(any("collection" in error for error in errors))
        self.assertTrue(any("records[0].record_id" in error for error in errors))
        self.assertTrue(any("records[0].text" in error for error in errors))
        self.assertTrue(any("records[0].metadata" in error for error in errors))

    def test_run_semantic_vector_publish_uses_injected_publisher(self):
        from data_agent.fusion.semantic_publisher import (
            build_semantic_vector_publish_spec,
            run_semantic_vector_publish,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest(),
            target="lancedb",
            collection="mmfe_products",
        )

        def publisher(records, **kwargs):
            return {
                "published_count": len(records),
                "target": kwargs["target"],
                "collection": kwargs["collection"],
                "record_ids": [record["record_id"] for record in records],
            }

        result = run_semantic_vector_publish(spec, publisher=publisher)

        self.assertTrue(result["valid"])
        self.assertEqual(result["published_count"], 2)
        self.assertEqual(result["target"], "lancedb")
        self.assertEqual(result["collection"], "mmfe_products")
        self.assertEqual(result["backend_result"]["record_ids"][0], "sfp-test:fusion:product")

    def test_build_pgvector_publisher_upserts_embedded_records(self):
        from data_agent.fusion.semantic_publisher import (
            build_pgvector_publisher,
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
            run_semantic_vector_publish,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest(),
            target="pgvector",
            collection="mmfe_semantic_products",
            embedding_model="mock-embedder",
        )
        embedded = embed_semantic_vector_records(
            spec,
            embedder=lambda texts, **kwargs: [[1.0, 0.0], [0.0, 1.0]],
        )["spec"]
        calls = []

        def executor(payload):
            calls.append(payload)
            return {"upserted": len(payload["rows"]), "table": payload["table"]}

        publisher = build_pgvector_publisher(
            table="agent_mmfe_semantic_vectors",
            executor=executor,
        )

        result = run_semantic_vector_publish(embedded, publisher=publisher)

        self.assertTrue(result["valid"])
        self.assertEqual(result["published_count"], 2)
        self.assertEqual(calls[0]["table"], "agent_mmfe_semantic_vectors")
        self.assertEqual(calls[0]["collection"], "mmfe_semantic_products")
        self.assertEqual(calls[0]["rows"][0]["record_id"], "sfp-test:fusion:product")
        self.assertEqual(calls[0]["rows"][0]["embedding"], [1.0, 0.0])
        self.assertEqual(calls[0]["rows"][0]["metadata"]["chunk_id"], "fusion:product")
        self.assertEqual(result["backend_result"]["upserted"], 2)

    def test_pgvector_publisher_requires_executor_and_embeddings(self):
        from data_agent.fusion.semantic_publisher import (
            build_pgvector_publisher,
            build_semantic_vector_publish_spec,
            run_semantic_vector_publish,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest(),
            target="pgvector",
            collection="mmfe_semantic_products",
        )
        publisher = build_pgvector_publisher(table="agent_mmfe_semantic_vectors")

        result = run_semantic_vector_publish(spec, publisher=publisher)

        self.assertFalse(result["valid"])
        self.assertTrue(any("executor is required" in error for error in result["errors"]))

        publisher_with_executor = build_pgvector_publisher(
            table="agent_mmfe_semantic_vectors",
            executor=lambda payload: {"upserted": len(payload["rows"])},
        )
        missing_embedding = run_semantic_vector_publish(
            spec,
            publisher=publisher_with_executor,
        )

        self.assertFalse(missing_embedding["valid"])
        self.assertTrue(any("embedding" in error for error in missing_embedding["errors"]))

    def test_build_lancedb_publisher_writes_embedded_records(self):
        from data_agent.fusion.semantic_publisher import (
            build_lancedb_publisher,
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
            run_semantic_vector_publish,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest(),
            target="lancedb",
            collection="mmfe_products",
            embedding_model="mock-embedder",
        )
        embedded = embed_semantic_vector_records(
            spec,
            embedder=lambda texts, **kwargs: [[1.0, 0.0], [0.0, 1.0]],
        )["spec"]
        calls = []

        def executor(payload):
            calls.append(payload)
            return {"inserted": len(payload["rows"]), "dataset_uri": payload["dataset_uri"]}

        publisher = build_lancedb_publisher(
            dataset_uri="file:///tmp/mmfe_vectors.lance",
            table="semantic_products",
            executor=executor,
        )

        result = run_semantic_vector_publish(embedded, publisher=publisher)

        self.assertTrue(result["valid"])
        self.assertEqual(result["published_count"], 2)
        self.assertEqual(calls[0]["target"], "lancedb")
        self.assertEqual(calls[0]["dataset_uri"], "file:///tmp/mmfe_vectors.lance")
        self.assertEqual(calls[0]["table"], "semantic_products")
        self.assertEqual(calls[0]["collection"], "mmfe_products")
        self.assertEqual(calls[0]["rows"][0]["record_id"], "sfp-test:fusion:product")
        self.assertEqual(calls[0]["rows"][0]["text"], "Semantic fusion product generated with spatial_join.")
        self.assertEqual(calls[0]["rows"][0]["embedding"], [1.0, 0.0])
        self.assertEqual(calls[0]["rows"][0]["metadata"]["chunk_id"], "fusion:product")
        self.assertEqual(result["backend_result"]["inserted"], 2)

    def test_lancedb_publisher_payload_preserves_authoritative_lakehouse_lineage(self):
        from data_agent.fusion.semantic_publisher import (
            build_lancedb_publisher,
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
            run_semantic_vector_publish,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest_with_lakehouse(),
            target="lancedb",
            collection="mmfe_products",
            embedding_model="mock-embedder",
        )
        embedded = embed_semantic_vector_records(
            spec,
            embedder=lambda texts, **kwargs: [[1.0, 0.0], [0.0, 1.0]],
        )["spec"]
        calls = []

        publisher = build_lancedb_publisher(
            dataset_uri="file:///tmp/mmfe_vectors.lance",
            table="semantic_products",
            executor=lambda payload: calls.append(payload) or {"inserted": len(payload["rows"])},
        )

        result = run_semantic_vector_publish(embedded, publisher=publisher)

        self.assertTrue(result["valid"])
        authoritative = calls[0]["rows"][0]["metadata"]["authoritative_lakehouse"]
        self.assertEqual(authoritative["target"], "iceberg")
        self.assertEqual(authoritative["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(authoritative["snapshot_id"], "snap-001")
        self.assertEqual(authoritative["business_output_path"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")

    def test_lancedb_publisher_requires_executor_and_embeddings(self):
        from data_agent.fusion.semantic_publisher import (
            build_lancedb_publisher,
            build_semantic_vector_publish_spec,
            run_semantic_vector_publish,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest(),
            target="lancedb",
            collection="mmfe_semantic_products",
        )
        publisher = build_lancedb_publisher(dataset_uri="file:///tmp/mmfe_vectors.lance")

        result = run_semantic_vector_publish(spec, publisher=publisher)

        self.assertFalse(result["valid"])
        self.assertTrue(any("executor is required" in error for error in result["errors"]))

        publisher_with_executor = build_lancedb_publisher(
            dataset_uri="file:///tmp/mmfe_vectors.lance",
            executor=lambda payload: {"inserted": len(payload["rows"])},
        )
        missing_embedding = run_semantic_vector_publish(
            spec,
            publisher=publisher_with_executor,
        )

        self.assertFalse(missing_embedding["valid"])
        self.assertTrue(any("embedding" in error for error in missing_embedding["errors"]))

    def test_embed_semantic_vector_records_uses_injected_embedder(self):
        from data_agent.fusion.semantic_publisher import (
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
        )

        spec = build_semantic_vector_publish_spec(
            _semantic_manifest(),
            target="pgvector",
            embedding_model="mock-embedder",
        )

        def embedder(texts, **kwargs):
            return [[float(index), float(len(text))] for index, text in enumerate(texts)]

        result = embed_semantic_vector_records(spec, embedder=embedder)

        self.assertTrue(result["valid"])
        self.assertEqual(result["embedded_count"], 2)
        self.assertEqual(result["embedding_model"], "mock-embedder")
        self.assertEqual(result["spec"]["records"][0]["embedding"], [0.0, 52.0])
        self.assertEqual(result["spec"]["records"][1]["embedding"], [1.0, 36.0])
        self.assertFalse(result["spec"]["embedding_required"])
        self.assertEqual(result["spec"]["embedding_dimension"], 2)
        self.assertEqual(result["spec"]["records"][0]["metadata"]["embedding_model"], "mock-embedder")

    def test_embed_semantic_vector_records_requires_embedder(self):
        from data_agent.fusion.semantic_publisher import (
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
        )

        spec = build_semantic_vector_publish_spec(_semantic_manifest(), target="pgvector")

        result = embed_semantic_vector_records(spec)

        self.assertFalse(result["valid"])
        self.assertEqual(result["embedded_count"], 0)
        self.assertTrue(any("embedder is required" in error for error in result["errors"]))

    def test_run_semantic_vector_publish_requires_publisher(self):
        from data_agent.fusion.semantic_publisher import (
            build_semantic_vector_publish_spec,
            run_semantic_vector_publish,
        )

        spec = build_semantic_vector_publish_spec(_semantic_manifest(), target="pgvector")

        result = run_semantic_vector_publish(spec)

        self.assertFalse(result["valid"])
        self.assertEqual(result["published_count"], 0)
        self.assertTrue(any("publisher is required" in error for error in result["errors"]))

    def test_semantic_vector_query_contract_embeds_and_runs_with_injected_querier(self):
        from data_agent.fusion.semantic_publisher import (
            SEMANTIC_VECTOR_QUERY_SCHEMA,
            build_lancedb_querier,
            build_semantic_vector_query_spec,
            embed_semantic_vector_query,
            run_semantic_vector_query,
            validate_semantic_vector_query_spec,
        )

        spec = build_semantic_vector_query_spec(
            "永久基本农田占用",
            target="lancedb",
            collection="mmfe_products",
            top_k=3,
            product_id="sfp-test",
        )

        self.assertEqual(spec["schema"], SEMANTIC_VECTOR_QUERY_SCHEMA)
        self.assertEqual(validate_semantic_vector_query_spec(spec), [])

        embedded = embed_semantic_vector_query(
            spec,
            embedder=lambda texts, **kwargs: [[float(len(texts[0])), 1.0, 0.0]],
        )
        self.assertTrue(embedded["valid"], embedded["errors"])
        self.assertEqual(embedded["embedded_count"], 1)
        self.assertFalse(embedded["spec"]["embedding_required"])

        def executor(payload):
            self.assertEqual(payload["target"], "lancedb")
            self.assertEqual(payload["collection"], "mmfe_products")
            self.assertEqual(payload["product_id"], "sfp-test")
            self.assertEqual(payload["top_k"], 3)
            return {
                "matches": [
                    {
                        "record_id": "sfp-test:fusion:rules",
                        "text": "永久基本农田占用审查",
                        "score": 0.91,
                        "metadata": {"rule_id": "TWM-FARM-001"},
                    }
                ]
            }

        result = run_semantic_vector_query(
            embedded["spec"],
            querier=build_lancedb_querier(dataset_uri="/tmp/mmfe_vectors", executor=executor),
        )

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["matches"][0]["metadata"]["rule_id"], "TWM-FARM-001")

    def test_run_semantic_vector_query_requires_embedding_and_querier(self):
        from data_agent.fusion.semantic_publisher import (
            build_semantic_vector_query_spec,
            run_semantic_vector_query,
        )

        spec = build_semantic_vector_query_spec("test", target="pgvector")
        result = run_semantic_vector_query(spec, querier=lambda payload: {"matches": []})
        self.assertFalse(result["valid"])
        self.assertTrue(any("query embedding is required" in error for error in result["errors"]))

        spec["query_embedding"] = [1.0, 0.0]
        spec["embedding_required"] = False
        result = run_semantic_vector_query(spec)
        self.assertFalse(result["valid"])
        self.assertTrue(any("querier is required" in error for error in result["errors"]))

    def test_semantic_vector_publisher_helpers_are_reexported(self):
        from data_agent.fusion import (
            build_lancedb_querier,
            build_lancedb_publisher,
            build_pgvector_executor,
            build_pgvector_querier,
            build_pgvector_publisher,
            build_semantic_vector_query_spec,
            build_semantic_vector_publish_spec,
            embed_semantic_vector_query,
            embed_semantic_vector_records,
            publish_payload_to_pgvector,
            run_semantic_vector_query,
        )
        from data_agent.fusion_engine import (
            build_lancedb_querier as proxy_build_lancedb_querier,
            build_lancedb_publisher as proxy_build_lancedb_publisher,
            build_pgvector_executor as proxy_build_pgvector_executor,
            build_pgvector_querier as proxy_build_pgvector_querier,
            build_pgvector_publisher as proxy_build_pgvector_publisher,
            embed_semantic_vector_query as proxy_embed_semantic_vector_query,
            embed_semantic_vector_records as proxy_embed_semantic_vector_records,
            publish_payload_to_pgvector as proxy_publish_payload_to_pgvector,
            run_semantic_vector_query as proxy_run_semantic_vector_query,
            run_semantic_vector_publish,
        )

        self.assertTrue(callable(build_lancedb_querier))
        self.assertTrue(callable(proxy_build_lancedb_querier))
        self.assertTrue(callable(build_lancedb_publisher))
        self.assertTrue(callable(proxy_build_lancedb_publisher))
        self.assertTrue(callable(build_pgvector_querier))
        self.assertTrue(callable(proxy_build_pgvector_querier))
        self.assertTrue(callable(build_pgvector_publisher))
        self.assertTrue(callable(proxy_build_pgvector_publisher))
        self.assertTrue(callable(build_pgvector_executor))
        self.assertTrue(callable(proxy_build_pgvector_executor))
        self.assertTrue(callable(publish_payload_to_pgvector))
        self.assertTrue(callable(proxy_publish_payload_to_pgvector))
        self.assertTrue(callable(build_semantic_vector_query_spec))
        self.assertTrue(callable(build_semantic_vector_publish_spec))
        self.assertTrue(callable(embed_semantic_vector_query))
        self.assertTrue(callable(proxy_embed_semantic_vector_query))
        self.assertTrue(callable(embed_semantic_vector_records))
        self.assertTrue(callable(proxy_embed_semantic_vector_records))
        self.assertTrue(callable(run_semantic_vector_query))
        self.assertTrue(callable(proxy_run_semantic_vector_query))
        self.assertTrue(callable(run_semantic_vector_publish))


if __name__ == "__main__":
    unittest.main()
