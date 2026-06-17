"""Smoke test MMFE semantic vector publish -> query retrieval.

This script is intentionally executable outside the ADK tool layer. It validates
the hard integration path: semantic product chunks are embedded, published to a
vector backend, and retrieved with a query embedding produced by the same
embedding adapter.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.fusion import (  # noqa: E402
    build_lancedb_publisher,
    build_lancedb_querier,
    build_local_lancedb_executor,
    build_local_lancedb_query_executor,
    build_pgvector_executor,
    build_pgvector_publisher,
    build_pgvector_querier,
    build_pgvector_query_executor,
    build_semantic_vector_publish_spec,
    build_semantic_vector_query_spec,
    embed_semantic_vector_query,
    embed_semantic_vector_records,
    run_semantic_vector_publish,
    run_semantic_vector_query,
)


DEFAULT_MANIFEST = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--target", choices=["pgvector", "lancedb"], default="pgvector")
    parser.add_argument("--collection", default="twm_mmfe_smoke")
    parser.add_argument("--query", default="永久基本农田占用审查")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--embedding-backend", choices=["gateway", "deterministic"], default="gateway")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--pgvector-dsn", default="")
    parser.add_argument("--pgvector-table", default="agent_mmfe_semantic_vectors_smoke")
    parser.add_argument("--lancedb-uri", default=".tmp/mmfe-lancedb-smoke")
    parser.add_argument("--lancedb-table", default="semantic_products")
    parser.add_argument("--expect-text", default="")
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace, *, publisher=None, querier=None) -> dict[str, Any]:
    """Run publish -> query retrieval smoke, with injectable backends for tests."""
    manifest = _read_manifest(args.manifest)
    embedder = _build_embedder(args.embedding_backend)
    embedding_model = args.embedding_model or _active_embedding_model(args.embedding_backend)

    publish_spec = build_semantic_vector_publish_spec(
        manifest,
        target=args.target,
        collection=args.collection,
        embedding_model=embedding_model,
        metadata={"smoke": "mmfe_semantic_vector_retrieval"},
    )
    embedded_publish = embed_semantic_vector_records(publish_spec, embedder=embedder)
    if not embedded_publish.get("valid"):
        _exit_error("embedding publish records failed", embedded_publish)

    publisher = publisher or _build_publisher(args)
    publish_result = run_semantic_vector_publish(embedded_publish["spec"], publisher=publisher)
    if not publish_result.get("valid"):
        _exit_error("semantic vector publish failed", publish_result)

    query_spec = build_semantic_vector_query_spec(
        query_text=args.query,
        target=args.target,
        collection=args.collection,
        embedding_model=embedding_model,
        top_k=args.top_k,
        product_id=embedded_publish["spec"].get("product_id"),
        metadata={"smoke": "mmfe_semantic_vector_retrieval"},
    )
    embedded_query = embed_semantic_vector_query(query_spec, embedder=embedder)
    if not embedded_query.get("valid"):
        _exit_error("embedding query failed", embedded_query)

    querier = querier or _build_querier(args)
    query_result = run_semantic_vector_query(embedded_query["spec"], querier=querier)
    if not query_result.get("valid"):
        _exit_error("semantic vector query failed", query_result)

    matches = query_result.get("matches") or []
    expected_ok = _expectation_ok(matches, args.expect_text)
    if args.expect_text and not expected_ok:
        _exit_error(
            "semantic vector query did not return expected text",
            {"expect_text": args.expect_text, "matches": matches},
        )

    return {
        "status": "ok",
        "target": args.target,
        "manifest": str(args.manifest),
        "product_id": embedded_publish["spec"].get("product_id"),
        "collection": args.collection,
        "embedding_backend": args.embedding_backend,
        "embedding_model": embedding_model,
        "embedding_dimension": embedded_publish.get("embedding_dimension"),
        "published_count": publish_result.get("published_count"),
        "query": args.query,
        "match_count": query_result.get("match_count"),
        "expectation_ok": expected_ok,
        "matches": _summarize_matches(matches),
        "publish_backend": publish_result.get("backend_result"),
    }


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_embedder(kind: str):
    if kind == "deterministic":
        return _deterministic_embedder

    def gateway_embedder(texts: list[str], **kwargs) -> list[list[float]]:
        from data_agent.embedding_gateway import get_embeddings

        vectors = get_embeddings(texts, model_name=kwargs.get("embedding_model"))
        if len(vectors) != len(texts):
            raise RuntimeError(
                "embedding_gateway returned no usable vectors; configure GOOGLE_API_KEY, "
                "Vertex credentials, EMBEDDING_MODEL, or use --embedding-backend deterministic"
            )
        return vectors

    return gateway_embedder


def _active_embedding_model(kind: str) -> str:
    if kind == "deterministic":
        return "deterministic-smoke-16d"
    try:
        from data_agent.embedding_gateway import EmbeddingRegistry

        return EmbeddingRegistry.get_active_model()
    except Exception:
        return "embedding_gateway"


def _deterministic_embedder(texts: list[str], **kwargs) -> list[list[float]]:
    return [_deterministic_embedding(text) for text in texts]


def _deterministic_embedding(text: str, dimension: int = 16) -> list[float]:
    # Small hashing embedder for offline smoke tests. It is not a semantic model.
    values = [0.0 for _ in range(dimension)]
    for index, char in enumerate(text):
        bucket = index % dimension
        values[bucket] += (ord(char) % 997) / 997.0
    norm = sum(value * value for value in values) ** 0.5 or 1.0
    return [value / norm for value in values]


def _build_publisher(args):
    if args.target == "pgvector":
        dsn = args.pgvector_dsn or os.environ.get("MMFE_PGVECTOR_TEST_DSN") or os.environ.get("DATABASE_URL") or ""
        if not dsn:
            raise SystemExit("pgvector target requires --pgvector-dsn, MMFE_PGVECTOR_TEST_DSN, or DATABASE_URL")
        executor = build_pgvector_executor(
            connection_url=dsn,
            table=args.pgvector_table,
            mode="overwrite",
            create_extension=True,
        )
        return build_pgvector_publisher(table=args.pgvector_table, executor=executor)

    executor = build_local_lancedb_executor(args.lancedb_uri, mode="overwrite")
    return build_lancedb_publisher(
        dataset_uri=args.lancedb_uri,
        table=args.lancedb_table,
        executor=executor,
    )


def _build_querier(args):
    if args.target == "pgvector":
        dsn = args.pgvector_dsn or os.environ.get("MMFE_PGVECTOR_TEST_DSN") or os.environ.get("DATABASE_URL") or ""
        if not dsn:
            raise SystemExit("pgvector target requires --pgvector-dsn, MMFE_PGVECTOR_TEST_DSN, or DATABASE_URL")
        executor = build_pgvector_query_executor(connection_url=dsn, table=args.pgvector_table)
        return build_pgvector_querier(table=args.pgvector_table, executor=executor)

    executor = build_local_lancedb_query_executor(args.lancedb_uri)
    return build_lancedb_querier(
        dataset_uri=args.lancedb_uri,
        table=args.lancedb_table,
        executor=executor,
    )


def _expectation_ok(matches: list[dict[str, Any]], expected: str) -> bool:
    if not expected:
        return True
    needle = expected.lower()
    for match in matches:
        if needle in str(match.get("text") or "").lower():
            return True
        metadata_text = json.dumps(match.get("metadata") or {}, ensure_ascii=False).lower()
        if needle in metadata_text:
            return True
    return False


def _summarize_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for match in matches:
        text = str(match.get("text") or "")
        summary.append(
            {
                "record_id": match.get("record_id"),
                "score": match.get("score"),
                "distance": match.get("distance"),
                "text_preview": text[:240],
                "metadata": match.get("metadata"),
            }
        )
    return summary


def _exit_error(message: str, payload: dict) -> None:
    print(
        json.dumps(
            {"status": "error", "message": message, "details": payload},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
