"""Tests for the optional real pgvector MMFE publisher adapter."""

import importlib.util
import json
import os
import unittest
from unittest import mock
from pathlib import Path


def _deterministic_embedder(texts, **kwargs):
    vectors = []
    for text in texts:
        length = float(len(text))
        checksum = float(sum(ord(ch) for ch in text) % 997)
        vectors.append([length, checksum, 1.0])
    return vectors


class TestPgvectorAdapter(unittest.TestCase):
    def test_pgvector_executor_is_exported_without_opening_database(self):
        from data_agent.fusion import build_pgvector_executor, build_pgvector_query_executor
        from data_agent.fusion_engine import (
            build_pgvector_executor as proxy,
            build_pgvector_query_executor as proxy_query,
        )

        self.assertTrue(callable(build_pgvector_executor))
        self.assertTrue(callable(proxy))
        self.assertTrue(callable(build_pgvector_query_executor))
        self.assertTrue(callable(proxy_query))

    def test_publish_payload_requires_connection_configuration(self):
        from data_agent.fusion.pgvector_adapter import publish_payload_to_pgvector

        payload = {
            "table": "agent_mmfe_semantic_vectors",
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

        cleared = {
            "MMFE_PGVECTOR_DSN": "",
            "DATABASE_URL": "",
            "POSTGRES_USER": "",
            "POSTGRES_PASSWORD": "",
            "POSTGRES_DATABASE": "",
            "POSTGRES_DB": "",
        }
        with mock.patch.dict(os.environ, cleared, clear=False):
            for key in cleared:
                os.environ.pop(key, None)
            with self.assertRaisesRegex(ValueError, "connection_url"):
                publish_payload_to_pgvector(payload)

    def test_publish_payload_rejects_unsafe_table_name(self):
        from data_agent.fusion.pgvector_adapter import publish_payload_to_pgvector

        with self.assertRaisesRegex(ValueError, "unsafe PostgreSQL identifier|table must"):
            publish_payload_to_pgvector(
                {
                    "table": "agent_mmfe_semantic_vectors;drop",
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
                },
                engine=object(),
            )

    def test_query_payload_rejects_unsafe_table_name(self):
        from data_agent.fusion.pgvector_adapter import query_pgvector_semantic_vectors

        with self.assertRaisesRegex(ValueError, "unsafe PostgreSQL identifier|table must"):
            query_pgvector_semantic_vectors(
                {
                    "table": "agent_mmfe_semantic_vectors;drop",
                    "collection": "test",
                    "query_embedding": [1.0, 2.0, 3.0],
                },
                engine=object(),
            )

    def test_vector_dimension_from_format_type(self):
        from data_agent.fusion.pgvector_adapter import _vector_dimension_from_format_type

        self.assertEqual(_vector_dimension_from_format_type("vector(768)"), 768)
        self.assertEqual(_vector_dimension_from_format_type("vector(16)"), 16)
        self.assertIsNone(_vector_dimension_from_format_type("text"))
        self.assertIsNone(_vector_dimension_from_format_type(None))

    @unittest.skipIf(
        not os.environ.get("MMFE_PGVECTOR_TEST_DSN"),
        "MMFE_PGVECTOR_TEST_DSN is not configured",
    )
    @unittest.skipIf(
        importlib.util.find_spec("sqlalchemy") is None,
        "optional dependency sqlalchemy is not installed",
    )
    def test_publish_twm_semantic_wrapper_to_pgvector_and_query_back(self):
        from sqlalchemy import create_engine, text

        from data_agent.fusion import (
            build_pgvector_executor,
            build_pgvector_query_executor,
            build_pgvector_querier,
            build_pgvector_publisher,
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
            target="pgvector",
            collection="twm_validation_scaffold",
            embedding_model="deterministic-test-3d",
        )
        embedded = embed_semantic_vector_records(spec, embedder=_deterministic_embedder)
        self.assertTrue(embedded["valid"], embedded["errors"])

        table = "agent_mmfe_semantic_vectors_test"
        dsn = os.environ["MMFE_PGVECTOR_TEST_DSN"]
        engine = create_engine(dsn, pool_pre_ping=True)
        try:
            with engine.begin() as conn:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
            executor = build_pgvector_executor(
                engine=engine,
                table=table,
                mode="overwrite",
                create_extension=True,
            )
            publisher = build_pgvector_publisher(table=table, executor=executor)
            result = run_semantic_vector_publish(embedded["spec"], publisher=publisher)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["published_count"], 1)

            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        f'SELECT collection, content_text, metadata '
                        f'FROM "{table}" WHERE record_id = :record_id'
                    ),
                    {"record_id": embedded["spec"]["records"][0]["record_id"]},
                ).mappings().one()
            self.assertEqual(row["collection"], "twm_validation_scaffold")
            self.assertIn("TWM role parcel_current", row["content_text"])
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            self.assertTrue(metadata["fallback_chunk"])
            self.assertEqual(metadata["business_output_path"], manifest["business_output"]["path"])

            query_spec = build_semantic_vector_query_spec(
                "TWM role parcel_current",
                target="pgvector",
                collection="twm_validation_scaffold",
                top_k=1,
            )
            query_spec["query_embedding"] = embedded["spec"]["records"][0]["embedding"]
            query_spec["embedding_required"] = False
            query_spec["embedding_dimension"] = len(query_spec["query_embedding"])
            query_executor = build_pgvector_query_executor(engine=engine, table=table)
            querier = build_pgvector_querier(table=table, executor=query_executor)
            query_result = run_semantic_vector_query(query_spec, querier=querier)
            self.assertTrue(query_result["valid"], query_result["errors"])
            self.assertEqual(query_result["match_count"], 1)
            self.assertIn("TWM role parcel_current", query_result["matches"][0]["text"])
            self.assertTrue(query_result["matches"][0]["metadata"]["fallback_chunk"])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
