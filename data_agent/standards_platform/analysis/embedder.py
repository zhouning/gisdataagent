"""Batch-compute embeddings via embedding_gateway; write to vector columns.
Dimension must match get_active_dimension() (default 768). Empty on failure."""
from __future__ import annotations

from sqlalchemy import text

from ...db_engine import get_engine
from ...embedding_gateway import get_embeddings, get_active_dimension
from ...observability import get_logger

logger = get_logger("standards_platform.analysis.embedder")


def _format_vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def _embed_table(*, version_id: str, table: str, id_col: str,
                 text_expr: str) -> int:
    eng = get_engine()
    if eng is None:
        return 0
    with eng.connect() as conn:
        rows = conn.execute(text(
            f"SELECT {id_col} AS id, {text_expr} AS body FROM {table} "
            f"WHERE document_version_id = :v AND embedding IS NULL"
        ), {"v": version_id}).mappings().all()
    if not rows:
        return 0
    texts = [r["body"] or "" for r in rows]
    vecs = get_embeddings(texts)
    if len(vecs) < len(texts):
        logger.warning("embedding count mismatch (%d vs %d) — skipping %s",
                       len(vecs), len(texts), table)
        return 0
    vecs = vecs[:len(texts)]
    dim = get_active_dimension()
    ok = 0
    with eng.begin() as conn:
        for r, v in zip(rows, vecs):
            if len(v) != dim:
                continue
            conn.execute(text(
                f"UPDATE {table} SET embedding = CAST(:e AS vector) WHERE {id_col} = :i"
            ), {"e": _format_vec(v), "i": r["id"]})
            ok += 1
    return ok


def embed_version(*, version_id: str) -> dict[str, int]:
    return {
        "clauses_embedded": _embed_table(version_id=version_id,
            table="std_clause", id_col="id",
            text_expr="COALESCE(heading,'') || ' ' || COALESCE(body_md,'')"),
        "terms_embedded": _embed_table(version_id=version_id,
            table="std_term", id_col="id",
            text_expr="COALESCE(name_zh,'') || ' ' || COALESCE(definition,'')"),
        "data_elements_embedded": _embed_table(version_id=version_id,
            table="std_data_element", id_col="id",
            text_expr="COALESCE(name_zh,'') || ' ' || COALESCE(definition,'')"),
    }
