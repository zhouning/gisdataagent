"""Tests for MMFE semantic vector publisher contracts."""

import unittest


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

    def test_semantic_vector_publisher_helpers_are_reexported(self):
        from data_agent.fusion import (
            build_pgvector_publisher,
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
        )
        from data_agent.fusion_engine import (
            build_pgvector_publisher as proxy_build_pgvector_publisher,
            embed_semantic_vector_records as proxy_embed_semantic_vector_records,
            run_semantic_vector_publish,
        )

        self.assertTrue(callable(build_pgvector_publisher))
        self.assertTrue(callable(proxy_build_pgvector_publisher))
        self.assertTrue(callable(build_semantic_vector_publish_spec))
        self.assertTrue(callable(embed_semantic_vector_records))
        self.assertTrue(callable(proxy_embed_semantic_vector_records))
        self.assertTrue(callable(run_semantic_vector_publish))


if __name__ == "__main__":
    unittest.main()
