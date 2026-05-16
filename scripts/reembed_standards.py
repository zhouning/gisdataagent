"""One-shot re-embed of std_clause / std_data_element / std_term across ALL
versions, using the active EMBEDDING_MODEL (currently nomic-embed-text via
ollama). Run after switching embedding model in .env so stored vectors
match the new query distribution.

Usage:
  .venv/Scripts/python.exe -m scripts.reembed_standards
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "data_agent", ".env"), override=True)

from sqlalchemy import text  # noqa: E402

from data_agent.db_engine import get_engine  # noqa: E402
from data_agent.embedding_gateway import (  # noqa: E402
    EmbeddingRegistry, get_active_dimension,
)
from data_agent.standards_platform.analysis.embedder import _embed_table  # noqa: E402


def _null_all_embeddings():
    """Force re-embed by NULLing existing vectors."""
    eng = get_engine()
    counts = {}
    with eng.begin() as conn:
        for table in ("std_clause", "std_data_element", "std_term"):
            r = conn.execute(text(
                f"UPDATE {table} SET embedding = NULL "
                f"WHERE embedding IS NOT NULL"
            ))
            counts[table] = r.rowcount
    return counts


def _list_versions() -> list[str]:
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id::text FROM std_document_version ORDER BY created_at"
        )).fetchall()
    return [r[0] for r in rows]


def main():
    model = EmbeddingRegistry.get_active_model()
    dim = get_active_dimension()
    print(f"Active embedding model: {model} (dim={dim})")
    skip_null = "--skip-null" in sys.argv
    if skip_null:
        print("Skipping NULL step (--skip-null); will only embed IS NULL rows.")
    else:
        print(f"Will NULL existing embeddings then re-embed.")
    print()

    if not skip_null:
        print("Step 1: NULLing existing embeddings...")
        nulled = _null_all_embeddings()
        print(f"  Nulled: {nulled}")

    print("Step 2: Embedding IS-NULL rows by version...")
    versions = _list_versions()
    print(f"  Found {len(versions)} versions")
    totals = {"clauses_embedded": 0, "terms_embedded": 0,
              "data_elements_embedded": 0}
    t_start = time.time()
    for i, ver_id in enumerate(versions, 1):
        t0 = time.time()
        clauses = _embed_table(version_id=ver_id, table="std_clause",
            id_col="id",
            text_expr="COALESCE(heading,'') || ' ' || COALESCE(body_md,'')")
        terms = _embed_table(version_id=ver_id, table="std_term",
            id_col="id",
            text_expr="COALESCE(name_zh,'') || ' ' || COALESCE(definition,'')")
        elements = _embed_table(version_id=ver_id, table="std_data_element",
            id_col="id",
            text_expr="COALESCE(name_zh,'') || ' ' || COALESCE(definition,'')")
        dt = time.time() - t0
        totals["clauses_embedded"] += clauses
        totals["terms_embedded"] += terms
        totals["data_elements_embedded"] += elements
        print(f"  [{i}/{len(versions)}] ver {ver_id[:8]}... "
              f"clauses={clauses} terms={terms} elements={elements} "
              f"({dt:.1f}s)")
    total_dt = time.time() - t_start
    print()
    print(f"Done in {total_dt:.1f}s. Totals: {totals}")


if __name__ == "__main__":
    main()
