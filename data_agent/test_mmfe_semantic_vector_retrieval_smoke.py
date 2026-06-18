"""Tests for the MMFE semantic vector retrieval smoke script."""

import argparse
import json
import sys
import types
import unittest
from pathlib import Path

from scripts.smoke_mmfe_semantic_vector_retrieval import run_smoke


class TestMMFESemanticVectorRetrievalSmoke(unittest.TestCase):
    def test_run_smoke_publishes_and_queries_twm_semantic_product_with_injected_backends(self):
        manifest = Path(
            "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/"
            "twm_mmfe_semantic_product.json"
        )
        self.assertTrue(manifest.exists(), f"missing fixture: {manifest}")
        expected_count = _manifest_chunk_count(manifest)

        published_records = []

        def publisher(records, **kwargs):
            published_records.extend(records)
            return {
                "target": kwargs["target"],
                "collection": kwargs["collection"],
                "published_count": len(records),
            }

        def querier(spec):
            self.assertEqual(spec["target"], "pgvector")
            self.assertEqual(spec["collection"], "twm_mmfe_smoke")
            self.assertFalse(spec["embedding_required"])
            self.assertEqual(spec["embedding_dimension"], 16)
            match = next(record for record in published_records if "永久基本农田" in record["text"])
            return {
                "target": "pgvector",
                "matches": [
                    {
                        "record_id": match["record_id"],
                        "product_id": spec["product_id"],
                        "collection": spec["collection"],
                        "text": match["text"],
                        "metadata": match["metadata"],
                        "score": 1.0,
                    }
                ],
            }

        args = argparse.Namespace(
            manifest=manifest,
            target="pgvector",
            collection="twm_mmfe_smoke",
            query="永久基本农田占用审查",
            top_k=3,
            embedding_backend="deterministic",
            embedding_model="",
            pgvector_dsn="",
            pgvector_table="agent_mmfe_semantic_vectors_smoke",
            lancedb_uri=".tmp/mmfe-lancedb-smoke",
            lancedb_table="semantic_products",
            expect_text="永久基本农田",
        )

        summary = run_smoke(args, publisher=publisher, querier=querier)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["target"], "pgvector")
        self.assertEqual(summary["published_count"], expected_count)
        self.assertEqual(summary["match_count"], 1)
        self.assertEqual(summary["embedding_backend"], "deterministic")
        self.assertEqual(summary["embedding_dimension"], 16)
        self.assertTrue(summary["expectation_ok"])
        self.assertEqual(len(published_records), expected_count)
        self.assertTrue(any("永久基本农田" in record["text"] for record in published_records))

    def test_run_smoke_gateway_backend_passes_explicit_embedding_model(self):
        manifest = Path(
            "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/"
            "twm_mmfe_semantic_product.json"
        )
        seen_models = []
        published_records = []

        fake_gateway = types.ModuleType("data_agent.embedding_gateway")

        def get_embeddings(texts, model_name=None):
            seen_models.append(model_name)
            return [[1.0, 0.0, 0.0] for _ in texts]

        fake_gateway.get_embeddings = get_embeddings

        def publisher(records, **kwargs):
            published_records.extend(records)
            return {"published_count": len(records)}

        def querier(spec):
            return {
                "matches": [
                    {
                        "record_id": published_records[0]["record_id"],
                        "product_id": spec["product_id"],
                        "collection": spec["collection"],
                        "text": published_records[0]["text"],
                        "metadata": published_records[0]["metadata"],
                    }
                ]
            }

        args = argparse.Namespace(
            manifest=manifest,
            target="lancedb",
            collection="twm_mmfe_smoke",
            query="融合产品",
            top_k=1,
            embedding_backend="gateway",
            embedding_model="unit-test-embedder",
            pgvector_dsn="",
            pgvector_table="agent_mmfe_semantic_vectors_smoke",
            lancedb_uri=".tmp/mmfe-lancedb-smoke",
            lancedb_table="semantic_products",
            expect_text="",
        )

        original = sys.modules.get("data_agent.embedding_gateway")
        sys.modules["data_agent.embedding_gateway"] = fake_gateway
        try:
            summary = run_smoke(args, publisher=publisher, querier=querier)
        finally:
            if original is None:
                sys.modules.pop("data_agent.embedding_gateway", None)
            else:
                sys.modules["data_agent.embedding_gateway"] = original

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["embedding_model"], "unit-test-embedder")
        self.assertEqual(seen_models, ["unit-test-embedder", "unit-test-embedder"])


def _manifest_chunk_count(path: Path) -> int:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return len((manifest.get("ai_metadata") or {}).get("chunks") or [])


if __name__ == "__main__":
    unittest.main()
