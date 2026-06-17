"""Tests for the optional real LanceDB MMFE publisher adapter."""

import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path


def _deterministic_embedder(texts, **kwargs):
    vectors = []
    for text in texts:
        length = float(len(text))
        checksum = float(sum(ord(ch) for ch in text) % 997)
        vectors.append([length, checksum, 1.0])
    return vectors


class TestLanceDBAdapter(unittest.TestCase):
    def test_local_lancedb_executor_is_exported_without_importing_lancedb(self):
        from data_agent.fusion import build_local_lancedb_executor, build_local_lancedb_query_executor
        from data_agent.fusion_engine import (
            build_local_lancedb_executor as proxy,
            build_local_lancedb_query_executor as proxy_query,
        )

        self.assertTrue(callable(build_local_lancedb_executor))
        self.assertTrue(callable(proxy))
        self.assertTrue(callable(build_local_lancedb_query_executor))
        self.assertTrue(callable(proxy_query))

    def test_list_lancedb_tables_accepts_new_response_shape(self):
        from data_agent.fusion.lancedb_adapter import _list_lancedb_tables

        db = types.SimpleNamespace(list_tables=lambda: types.SimpleNamespace(tables=["semantic_products"]))

        self.assertEqual(_list_lancedb_tables(db), ["semantic_products"])

    @unittest.skipIf(
        importlib.util.find_spec("lancedb") is not None,
        "LanceDB installed; missing-dependency path is not applicable",
    )
    def test_publish_payload_reports_missing_optional_dependency(self):
        from data_agent.fusion.lancedb_adapter import publish_payload_to_lancedb

        payload = {
            "dataset_uri": "/tmp/mmfe-lancedb-missing-dep",
            "table": "semantic_products",
            "collection": "test",
            "product_id": "p1",
            "rows": [
                {
                    "record_id": "p1:c1",
                    "text": "hello",
                    "embedding": [1.0, 2.0, 3.0],
                    "metadata": {},
                }
            ],
        }

        with self.assertRaisesRegex(RuntimeError, "optional dependencies"):
            publish_payload_to_lancedb(payload)

    @unittest.skipIf(
        importlib.util.find_spec("lancedb") is not None,
        "LanceDB installed; missing-dependency path is not applicable",
    )
    def test_query_reports_missing_optional_dependency(self):
        from data_agent.fusion.lancedb_adapter import query_lancedb_semantic_vectors

        with self.assertRaisesRegex(RuntimeError, "optional dependency"):
            query_lancedb_semantic_vectors(
                {
                    "dataset_uri": "/tmp/mmfe-lancedb-missing-dep",
                    "table": "semantic_products",
                    "collection": "test",
                    "query_embedding": [1.0, 2.0, 3.0],
                    "top_k": 1,
                }
            )

    @unittest.skipIf(
        importlib.util.find_spec("lancedb") is None,
        "optional dependency lancedb is not installed",
    )
    def test_publish_twm_semantic_wrapper_to_local_lancedb_and_query_back(self):
        import lancedb

        from data_agent.fusion import (
            build_lancedb_querier,
            build_lancedb_publisher,
            build_local_lancedb_executor,
            build_local_lancedb_query_executor,
            build_semantic_vector_query_spec,
            build_semantic_vector_publish_spec,
            embed_semantic_vector_records,
            run_semantic_vector_query,
            run_semantic_vector_publish,
        )

        manifest_path = Path("data_agent/test_data/twm_bishan_demo/parcel_current.semantic.json")
        self.assertTrue(manifest_path.exists(), f"missing fixture: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        spec = build_semantic_vector_publish_spec(
            manifest,
            target="lancedb",
            collection="twm_validation_scaffold",
            embedding_model="deterministic-test-3d",
        )
        embedded = embed_semantic_vector_records(spec, embedder=_deterministic_embedder)
        self.assertTrue(embedded["valid"], embedded["errors"])

        with tempfile.TemporaryDirectory() as tmp:
            executor = build_local_lancedb_executor(tmp)
            publisher = build_lancedb_publisher(
                dataset_uri=tmp,
                table="semantic_products",
                executor=executor,
            )
            result = run_semantic_vector_publish(embedded["spec"], publisher=publisher)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["published_count"], 1)

            table = lancedb.connect(tmp).open_table("semantic_products")
            rows = table.to_arrow().to_pylist()
            self.assertEqual(len(rows), 1)
            self.assertIn("TWM role parcel_current", rows[0]["text"])
            self.assertEqual(rows[0]["collection"], "twm_validation_scaffold")
            metadata = json.loads(rows[0]["metadata_json"])
            self.assertTrue(metadata["fallback_chunk"])
            self.assertEqual(metadata["business_output_path"], manifest["business_output"]["path"])

            query_spec = build_semantic_vector_query_spec(
                "TWM role parcel_current",
                target="lancedb",
                collection="twm_validation_scaffold",
                top_k=1,
            )
            query_spec["query_embedding"] = embedded["spec"]["records"][0]["embedding"]
            query_spec["embedding_required"] = False
            query_spec["embedding_dimension"] = len(query_spec["query_embedding"])
            query_executor = build_local_lancedb_query_executor(tmp)
            querier = build_lancedb_querier(
                dataset_uri=tmp,
                table="semantic_products",
                executor=query_executor,
            )
            query_result = run_semantic_vector_query(query_spec, querier=querier)
            self.assertTrue(query_result["valid"], query_result["errors"])
            self.assertEqual(query_result["match_count"], 1)
            self.assertIn("TWM role parcel_current", query_result["matches"][0]["text"])
            self.assertTrue(query_result["matches"][0]["metadata"]["fallback_chunk"])


if __name__ == "__main__":
    unittest.main()
