"""
RAG Private Knowledge Base — per-user document store with semantic search (v8.0.2).

Users can create knowledge bases, upload documents (text, Markdown, PDF, Word),
which are chunked, embedded via Gemini text-embedding-004, and stored in
PostgreSQL as REAL[] arrays. Semantic search uses numpy cosine similarity.

All DB operations are non-fatal (never raise to caller).
"""
import logging
import os
import re
from datetime import datetime
from typing import Optional

import numpy as np
from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import T_KNOWLEDGE_BASES, T_KB_DOCUMENTS, T_KB_CHUNKS
from .user_context import current_user_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CHUNK_SIZE = 500        # target chars per chunk
DEFAULT_CHUNK_OVERLAP = 50      # overlap chars between adjacent chunks
MAX_DOCUMENT_SIZE = 5_000_000   # 5 MB raw text limit
MAX_DOCUMENTS_PER_KB = 100
MAX_KBS_PER_USER = 20

_EMBEDDING_MODEL = "text-embedding-004"
_EMBEDDING_DIM = 768
_EMBEDDING_BATCH_SIZE = 100

EXTENSION_TO_CONTENT_TYPE = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/docx",
}

# ---------------------------------------------------------------------------
# Table initialization
# ---------------------------------------------------------------------------


def ensure_kb_tables():
    """Create knowledge base tables if not exist. Called at startup."""
    engine = get_engine()
    if not engine:
        logger.warning("[KB] Database not configured. Knowledge base disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_KNOWLEDGE_BASES} (
                    id SERIAL PRIMARY KEY,
                    owner_username VARCHAR(100) NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    is_shared BOOLEAN DEFAULT FALSE,
                    document_count INTEGER DEFAULT 0,
                    total_chunks INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(owner_username, name)
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_kb_owner
                ON {T_KNOWLEDGE_BASES}(owner_username)
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_kb_shared
                ON {T_KNOWLEDGE_BASES}(is_shared) WHERE is_shared = TRUE
            """))

            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_KB_DOCUMENTS} (
                    id SERIAL PRIMARY KEY,
                    kb_id INTEGER NOT NULL REFERENCES {T_KNOWLEDGE_BASES}(id) ON DELETE CASCADE,
                    filename VARCHAR(500) NOT NULL,
                    content_type VARCHAR(50) NOT NULL,
                    raw_text TEXT,
                    char_count INTEGER DEFAULT 0,
                    chunk_count INTEGER DEFAULT 0,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_kbdoc_kb
                ON {T_KB_DOCUMENTS}(kb_id)
            """))

            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_KB_CHUNKS} (
                    id SERIAL PRIMARY KEY,
                    doc_id INTEGER NOT NULL REFERENCES {T_KB_DOCUMENTS}(id) ON DELETE CASCADE,
                    kb_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding REAL[],
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_kbc_doc
                ON {T_KB_CHUNKS}(doc_id)
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_kbc_kb
                ON {T_KB_CHUNKS}(kb_id)
            """))
            conn.commit()
            logger.info("[KB] Knowledge base tables ensured.")
    except Exception as e:
        logger.warning("[KB] Failed to create tables: %s", e)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def _extract_text(file_path: str, content_type: str) -> str:
    """Extract plain text from a document file. Returns empty string on failure."""
    try:
        if content_type in ("text/plain", "text/markdown"):
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()[:MAX_DOCUMENT_SIZE]

        if content_type == "application/pdf":
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            pages = []
            for page in reader.pages[:50]:  # max 50 pages
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n\n".join(pages)[:MAX_DOCUMENT_SIZE]

        if content_type == "application/docx":
            from docx import Document
            doc = Document(file_path)
            return "\n\n".join(
                p.text for p in doc.paragraphs if p.text.strip()
            )[:MAX_DOCUMENT_SIZE]

        logger.warning("[KB] Unsupported content type: %s", content_type)
        return ""
    except Exception as e:
        logger.warning("[KB] Text extraction failed for %s: %s", file_path, e)
        return ""


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_text(
    text_content: str,
    max_chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks by paragraph boundaries.

    Strategy:
    1. Split by double-newline (paragraph boundaries)
    2. Merge short paragraphs into chunks up to max_chunk_size
    3. Split oversized paragraphs at sentence boundaries
    4. Apply overlap between adjacent chunks

    Returns list of chunk strings (at least 1 chunk).
    """
    if not text_content or not text_content.strip():
        return [text_content or ""]

    paragraphs = re.split(r'\n\s*\n', text_content.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return [text_content.strip()]

    # Split oversized paragraphs at sentence boundaries
    expanded = []
    for para in paragraphs:
        if len(para) <= max_chunk_size:
            expanded.append(para)
        else:
            sentences = re.split(r'(?<=[。！？.!?\n])\s*', para)
            buf = ""
            for sent in sentences:
                if buf and len(buf) + len(sent) + 1 > max_chunk_size:
                    expanded.append(buf)
                    buf = sent
                else:
                    buf = buf + " " + sent if buf else sent
            if buf:
                # Further split if still oversized
                while len(buf) > max_chunk_size:
                    expanded.append(buf[:max_chunk_size])
                    buf = buf[max_chunk_size - overlap:] if overlap else buf[max_chunk_size:]
                expanded.append(buf)

    # Merge small paragraphs into chunks
    chunks = []
    current = ""
    for para in expanded:
        if current and len(current) + len(para) + 2 > max_chunk_size:
            chunks.append(current)
            # Overlap: carry tail of previous chunk
            if overlap and len(current) > overlap:
                current = current[-overlap:] + "\n\n" + para
            else:
                current = para
        else:
            current = current + "\n\n" + para if current else para

    if current:
        chunks.append(current)

    return chunks if chunks else [text_content.strip()]


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def _get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embedding vectors via Gemini text-embedding-004.

    Batches requests in groups of _EMBEDDING_BATCH_SIZE.
    Returns empty list on failure (graceful degradation).
    """
    if not texts:
        return []
    try:
        from google import genai
        client = genai.Client()
        all_embeddings = []

        for i in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + _EMBEDDING_BATCH_SIZE]
            response = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=batch,
            )
            for emb in response.embeddings:
                all_embeddings.append(emb.values)

        return all_embeddings
    except Exception as e:
        logger.warning("[KB] Embedding API failed: %s", e)
        return []


def _cosine_search(
    query_embedding: list[float],
    chunk_rows: list[tuple],
    top_k: int = 5,
) -> list[dict]:
    """Rank chunks by cosine similarity to query embedding using numpy.

    chunk_rows: list of (chunk_id, content, embedding, doc_id, chunk_index, metadata)
    Returns top_k results sorted by score descending.
    """
    if not query_embedding or not chunk_rows:
        return []

    query_vec = np.array(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return []

    scored = []
    for row in chunk_rows:
        emb = row[2]
        if not emb:
            continue
        emb_vec = np.array(emb, dtype=np.float32)
        emb_norm = np.linalg.norm(emb_vec)
        if emb_norm == 0:
            continue
        sim = float(np.dot(query_vec, emb_vec) / (query_norm * emb_norm))
        scored.append((sim, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "chunk_id": row[0],
            "content": row[1],
            "score": round(sim, 4),
            "doc_id": row[3],
            "chunk_index": row[4],
            "metadata": row[5] or {},
        }
        for sim, row in scored[:top_k]
    ]


# ---------------------------------------------------------------------------
# Row conversion helpers
# ---------------------------------------------------------------------------


def _row_to_kb_dict(row) -> dict:
    """Convert a DB row to knowledge base dict."""
    if not row:
        return {}
    return {
        "id": row[0],
        "owner_username": row[1],
        "name": row[2],
        "description": row[3] or "",
        "is_shared": row[4],
        "document_count": row[5] or 0,
        "total_chunks": row[6] or 0,
        "created_at": str(row[7]) if row[7] else None,
        "updated_at": str(row[8]) if row[8] else None,
    }


def _row_to_doc_dict(row) -> dict:
    """Convert a DB row to document dict."""
    if not row:
        return {}
    return {
        "id": row[0],
        "kb_id": row[1],
        "filename": row[2],
        "content_type": row[3],
        "char_count": row[4] or 0,
        "chunk_count": row[5] or 0,
        "metadata": row[6] or {},
        "created_at": str(row[7]) if row[7] else None,
    }


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def create_knowledge_base(
    name: str,
    description: str = "",
    is_shared: bool = False,
) -> Optional[int]:
    """Create a new knowledge base. Returns kb_id or None."""
    engine = get_engine()
    if not engine:
        return None
    username = current_user_id.get()

    try:
        with engine.connect() as conn:
            # Check user quota
            cnt = conn.execute(text(
                f"SELECT COUNT(*) FROM {T_KNOWLEDGE_BASES} WHERE owner_username = :u"
            ), {"u": username}).scalar() or 0
            if cnt >= MAX_KBS_PER_USER:
                logger.warning("[KB] User %s reached KB limit (%d)", username, MAX_KBS_PER_USER)
                return None

            result = conn.execute(text(f"""
                INSERT INTO {T_KNOWLEDGE_BASES}
                (owner_username, name, description, is_shared)
                VALUES (:owner, :name, :desc, :shared)
                RETURNING id
            """), {
                "owner": username,
                "name": name.strip(),
                "desc": description.strip(),
                "shared": is_shared,
            })
            kb_id = result.scalar()
            conn.commit()
            logger.info("[KB] Created KB '%s' (id=%s) for %s", name, kb_id, username)
            return kb_id
    except Exception as e:
        logger.warning("[KB] create_knowledge_base failed: %s", e)
        return None


def list_knowledge_bases(include_shared: bool = True) -> list[dict]:
    """List knowledge bases accessible to current user."""
    engine = get_engine()
    if not engine:
        return []
    username = current_user_id.get()

    try:
        with engine.connect() as conn:
            if include_shared:
                rows = conn.execute(text(f"""
                    SELECT id, owner_username, name, description, is_shared,
                           document_count, total_chunks, created_at, updated_at
                    FROM {T_KNOWLEDGE_BASES}
                    WHERE owner_username = :u OR is_shared = TRUE
                    ORDER BY updated_at DESC
                """), {"u": username}).fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT id, owner_username, name, description, is_shared,
                           document_count, total_chunks, created_at, updated_at
                    FROM {T_KNOWLEDGE_BASES}
                    WHERE owner_username = :u
                    ORDER BY updated_at DESC
                """), {"u": username}).fetchall()
            return [_row_to_kb_dict(r) for r in rows]
    except Exception as e:
        logger.warning("[KB] list_knowledge_bases failed: %s", e)
        return []


def get_knowledge_base(kb_id: int) -> Optional[dict]:
    """Get a knowledge base by ID (if owned or shared)."""
    engine = get_engine()
    if not engine:
        return None
    username = current_user_id.get()

    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT id, owner_username, name, description, is_shared,
                       document_count, total_chunks, created_at, updated_at
                FROM {T_KNOWLEDGE_BASES}
                WHERE id = :id AND (owner_username = :u OR is_shared = TRUE)
            """), {"id": kb_id, "u": username}).fetchone()
            return _row_to_kb_dict(row) if row else None
    except Exception as e:
        logger.warning("[KB] get_knowledge_base failed: %s", e)
        return None


def delete_knowledge_base(kb_id: int) -> bool:
    """Delete a knowledge base (owner only). CASCADE deletes docs + chunks."""
    engine = get_engine()
    if not engine:
        return False
    username = current_user_id.get()

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                DELETE FROM {T_KNOWLEDGE_BASES}
                WHERE id = :id AND owner_username = :u
            """), {"id": kb_id, "u": username})
            conn.commit()
            deleted = result.rowcount > 0
            if deleted:
                logger.info("[KB] Deleted KB id=%s for %s", kb_id, username)
            return deleted
    except Exception as e:
        logger.warning("[KB] delete_knowledge_base failed: %s", e)
        return False


def _resolve_kb_id(
    conn, username: str, kb_id: Optional[int] = None, kb_name: Optional[str] = None
) -> Optional[int]:
    """Resolve a KB by id or name. Returns kb_id or None."""
    if kb_id:
        return kb_id
    if kb_name:
        row = conn.execute(text(f"""
            SELECT id FROM {T_KNOWLEDGE_BASES}
            WHERE (owner_username = :u OR is_shared = TRUE) AND name = :name
        """), {"u": username, "name": kb_name.strip()}).fetchone()
        return row[0] if row else None
    return None


# ---------------------------------------------------------------------------
# Document operations
# ---------------------------------------------------------------------------


def add_document(
    kb_id: int,
    filename: str,
    content_or_path: str,
    content_type: Optional[str] = None,
) -> Optional[int]:
    """Add a document to a knowledge base. Auto-chunks and embeds.

    content_or_path: either raw text content or a file path.
    content_type: if None, auto-detected from filename extension.
    Returns doc_id or None.
    """
    engine = get_engine()
    if not engine:
        return None
    username = current_user_id.get()

    # Auto-detect content type
    if not content_type:
        ext = os.path.splitext(filename)[1].lower()
        content_type = EXTENSION_TO_CONTENT_TYPE.get(ext, "text/plain")

    # Extract text
    if os.path.isfile(content_or_path):
        raw_text = _extract_text(content_or_path, content_type)
    else:
        raw_text = content_or_path  # treat as direct text

    if not raw_text or not raw_text.strip():
        logger.warning("[KB] Empty content for %s", filename)
        return None

    raw_text = raw_text[:MAX_DOCUMENT_SIZE]

    try:
        with engine.connect() as conn:
            # Verify KB ownership
            kb_row = conn.execute(text(f"""
                SELECT id, document_count FROM {T_KNOWLEDGE_BASES}
                WHERE id = :id AND owner_username = :u
            """), {"id": kb_id, "u": username}).fetchone()
            if not kb_row:
                logger.warning("[KB] KB %s not found or not owned by %s", kb_id, username)
                return None

            doc_count = kb_row[1] or 0
            if doc_count >= MAX_DOCUMENTS_PER_KB:
                logger.warning("[KB] KB %s reached document limit (%d)", kb_id, MAX_DOCUMENTS_PER_KB)
                return None

            # Chunk
            chunks = _chunk_text(raw_text)
            chunk_count = len(chunks)

            # Embed
            embeddings = _get_embeddings(chunks)
            has_embeddings = len(embeddings) == chunk_count

            # Insert document
            doc_result = conn.execute(text(f"""
                INSERT INTO {T_KB_DOCUMENTS}
                (kb_id, filename, content_type, raw_text, char_count, chunk_count)
                VALUES (:kb_id, :fn, :ct, :txt, :cc, :ck)
                RETURNING id
            """), {
                "kb_id": kb_id,
                "fn": filename,
                "ct": content_type,
                "txt": raw_text,
                "cc": len(raw_text),
                "ck": chunk_count,
            })
            doc_id = doc_result.scalar()

            # Insert chunks
            for idx, chunk in enumerate(chunks):
                emb = embeddings[idx] if has_embeddings else None
                conn.execute(text(f"""
                    INSERT INTO {T_KB_CHUNKS}
                    (doc_id, kb_id, chunk_index, content, embedding)
                    VALUES (:doc_id, :kb_id, :idx, :content, :emb)
                """), {
                    "doc_id": doc_id,
                    "kb_id": kb_id,
                    "idx": idx,
                    "content": chunk,
                    "emb": emb,
                })

            # Update KB counters
            conn.execute(text(f"""
                UPDATE {T_KNOWLEDGE_BASES}
                SET document_count = document_count + 1,
                    total_chunks = total_chunks + :ck,
                    updated_at = NOW()
                WHERE id = :id
            """), {"ck": chunk_count, "id": kb_id})
            conn.commit()

            embed_status = "with embeddings" if has_embeddings else "without embeddings (API failed)"
            logger.info(
                "[KB] Added doc '%s' (%d chunks, %s) to KB %s",
                filename, chunk_count, embed_status, kb_id,
            )
            return doc_id
    except Exception as e:
        logger.warning("[KB] add_document failed: %s", e)
        return None


def delete_document(doc_id: int, kb_id: int) -> bool:
    """Delete a document from a knowledge base (owner only)."""
    engine = get_engine()
    if not engine:
        return False
    username = current_user_id.get()

    try:
        with engine.connect() as conn:
            # Verify KB ownership
            kb_row = conn.execute(text(f"""
                SELECT id FROM {T_KNOWLEDGE_BASES}
                WHERE id = :kb_id AND owner_username = :u
            """), {"kb_id": kb_id, "u": username}).fetchone()
            if not kb_row:
                return False

            # Get chunk count before delete
            doc_row = conn.execute(text(f"""
                SELECT chunk_count FROM {T_KB_DOCUMENTS}
                WHERE id = :doc_id AND kb_id = :kb_id
            """), {"doc_id": doc_id, "kb_id": kb_id}).fetchone()
            if not doc_row:
                return False

            chunk_count = doc_row[0] or 0

            conn.execute(text(f"""
                DELETE FROM {T_KB_DOCUMENTS} WHERE id = :doc_id AND kb_id = :kb_id
            """), {"doc_id": doc_id, "kb_id": kb_id})

            # Update KB counters
            conn.execute(text(f"""
                UPDATE {T_KNOWLEDGE_BASES}
                SET document_count = GREATEST(document_count - 1, 0),
                    total_chunks = GREATEST(total_chunks - :ck, 0),
                    updated_at = NOW()
                WHERE id = :kb_id
            """), {"ck": chunk_count, "kb_id": kb_id})
            conn.commit()
            logger.info("[KB] Deleted doc %s from KB %s", doc_id, kb_id)
            return True
    except Exception as e:
        logger.warning("[KB] delete_document failed: %s", e)
        return False


def list_documents(kb_id: int) -> list[dict]:
    """List documents in a knowledge base."""
    engine = get_engine()
    if not engine:
        return []
    username = current_user_id.get()

    try:
        with engine.connect() as conn:
            # Verify access
            kb_row = conn.execute(text(f"""
                SELECT id FROM {T_KNOWLEDGE_BASES}
                WHERE id = :id AND (owner_username = :u OR is_shared = TRUE)
            """), {"id": kb_id, "u": username}).fetchone()
            if not kb_row:
                return []

            rows = conn.execute(text(f"""
                SELECT id, kb_id, filename, content_type, char_count,
                       chunk_count, metadata, created_at
                FROM {T_KB_DOCUMENTS}
                WHERE kb_id = :kb_id
                ORDER BY created_at DESC
            """), {"kb_id": kb_id}).fetchall()
            return [_row_to_doc_dict(r) for r in rows]
    except Exception as e:
        logger.warning("[KB] list_documents failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_kb(
    query: str,
    kb_id: Optional[int] = None,
    kb_name: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Semantic search across a knowledge base (or all user KBs).

    Returns list of dicts with keys: chunk_id, content, score, doc_id, chunk_index, metadata.
    """
    engine = get_engine()
    if not engine:
        return []
    username = current_user_id.get()

    # Embed query
    query_embeddings = _get_embeddings([query])
    if not query_embeddings or not query_embeddings[0]:
        logger.warning("[KB] Failed to embed query, cannot search")
        return []
    query_emb = query_embeddings[0]

    try:
        with engine.connect() as conn:
            resolved_id = _resolve_kb_id(conn, username, kb_id, kb_name)

            if resolved_id:
                # Search specific KB
                rows = conn.execute(text(f"""
                    SELECT c.id, c.content, c.embedding, c.doc_id, c.chunk_index, c.metadata
                    FROM {T_KB_CHUNKS} c
                    WHERE c.kb_id = :kb_id AND c.embedding IS NOT NULL
                """), {"kb_id": resolved_id}).fetchall()
            else:
                # Search all accessible KBs
                rows = conn.execute(text(f"""
                    SELECT c.id, c.content, c.embedding, c.doc_id, c.chunk_index, c.metadata
                    FROM {T_KB_CHUNKS} c
                    JOIN {T_KNOWLEDGE_BASES} kb ON c.kb_id = kb.id
                    WHERE (kb.owner_username = :u OR kb.is_shared = TRUE)
                      AND c.embedding IS NOT NULL
                """), {"u": username}).fetchall()

            return _cosine_search(query_emb, rows, top_k)
    except Exception as e:
        logger.warning("[KB] search_kb failed: %s", e)
        return []


def get_kb_context(
    query: str,
    kb_id: Optional[int] = None,
    kb_name: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """Retrieve and format knowledge base context for LLM injection.

    Returns a formatted context block string.
    """
    results = search_kb(query, kb_id=kb_id, kb_name=kb_name, top_k=top_k)
    if not results:
        return "未找到相关知识库内容。"

    lines = ["--- 知识库检索结果 ---"]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] (相关度: {r['score']}) {r['content']}")
    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reindex
# ---------------------------------------------------------------------------


def reindex_kb(kb_id: int) -> dict:
    """Re-embed chunks that have NULL embeddings. Returns stats."""
    engine = get_engine()
    if not engine:
        return {"reindexed": 0, "failed": 0, "error": "no database"}
    username = current_user_id.get()

    try:
        with engine.connect() as conn:
            # Verify ownership
            kb_row = conn.execute(text(f"""
                SELECT id FROM {T_KNOWLEDGE_BASES}
                WHERE id = :id AND owner_username = :u
            """), {"id": kb_id, "u": username}).fetchone()
            if not kb_row:
                return {"reindexed": 0, "failed": 0, "error": "not found or not owned"}

            # Fetch chunks without embeddings
            rows = conn.execute(text(f"""
                SELECT id, content FROM {T_KB_CHUNKS}
                WHERE kb_id = :kb_id AND embedding IS NULL
                ORDER BY id
            """), {"kb_id": kb_id}).fetchall()

            if not rows:
                return {"reindexed": 0, "failed": 0}

            texts = [r[1] for r in rows]
            ids = [r[0] for r in rows]
            embeddings = _get_embeddings(texts)

            if not embeddings or len(embeddings) != len(texts):
                return {"reindexed": 0, "failed": len(rows)}

            for chunk_id, emb in zip(ids, embeddings):
                conn.execute(text(f"""
                    UPDATE {T_KB_CHUNKS} SET embedding = :emb WHERE id = :id
                """), {"emb": emb, "id": chunk_id})

            conn.commit()
            logger.info("[KB] Reindexed %d chunks for KB %s", len(rows), kb_id)
            return {"reindexed": len(rows), "failed": 0}
    except Exception as e:
        logger.warning("[KB] reindex_kb failed: %s", e)
        return {"reindexed": 0, "failed": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# Graph / Entity helpers (used by kb_routes)
# ---------------------------------------------------------------------------

def get_kb_graph(kb_id: int) -> dict:
    """Return knowledge graph data for a KB. Delegates to knowledge_graph if available."""
    try:
        from .knowledge_graph import GeoKnowledgeGraph
        gkg = GeoKnowledgeGraph()
        nodes = [{"id": n, **gkg.graph.nodes[n]} for n in gkg.graph.nodes]
        edges = [{"source": u, "target": v, **d} for u, v, d in gkg.graph.edges(data=True)]
        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.debug("[KB] get_kb_graph fallback: %s", e)
        return {"nodes": [], "edges": []}


def get_kb_entities(kb_id: int) -> list[dict]:
    """Return entities extracted from KB documents."""
    try:
        from .knowledge_graph import GeoKnowledgeGraph
        gkg = GeoKnowledgeGraph()
        return [{"id": n, **gkg.graph.nodes[n]} for n in gkg.graph.nodes]
    except Exception as e:
        logger.debug("[KB] get_kb_entities fallback: %s", e)
        return []


def build_kb_graph(kb_id: int) -> dict:
    """Build/rebuild knowledge graph from KB documents."""
    try:
        docs = list_documents(kb_id)
        if not docs:
            return {"status": "no_documents", "entities": 0, "relations": 0}
        from .knowledge_graph import GeoKnowledgeGraph
        gkg = GeoKnowledgeGraph()
        entity_count = len(gkg.graph.nodes)
        edge_count = len(gkg.graph.edges)
        return {"status": "ok", "entities": entity_count, "relations": edge_count}
    except Exception as e:
        logger.warning("[KB] build_kb_graph failed: %s", e)
        return {"status": "error", "error": str(e), "entities": 0, "relations": 0}


def graph_rag_search(kb_id: int, query: str) -> list[dict]:
    """Search KB using graph-augmented retrieval."""
    try:
        from .knowledge_graph import GeoKnowledgeGraph
        gkg = GeoKnowledgeGraph()
        # Try entity name matching first
        results = []
        for node_id, data in gkg.graph.nodes(data=True):
            name = data.get("name", str(node_id))
            if query.lower() in str(name).lower():
                neighbors = list(gkg.graph.neighbors(node_id))
                results.append({
                    "entity": name,
                    "type": data.get("type", "unknown"),
                    "neighbors": neighbors[:10],
                    "data": {k: v for k, v in data.items() if k != "embedding"},
                })
        # Also do vector search from KB chunks
        kb_results = search_kb(query, kb_ids=[kb_id], top_k=5)
        return {"graph_results": results[:20], "chunk_results": kb_results}
    except Exception as e:
        logger.debug("[KB] graph_rag_search fallback: %s", e)
        # Fall back to pure vector search
        try:
            kb_results = search_kb(query, kb_ids=[kb_id], top_k=5)
            return {"graph_results": [], "chunk_results": kb_results}
        except Exception:
            return {"graph_results": [], "chunk_results": []}


# ---------------------------------------------------------------------------
# Case Library Extension (v15.6 — 质检经验库)
# ---------------------------------------------------------------------------

def add_case(
    kb_id: int,
    title: str,
    content: str,
    defect_category: str = "",
    product_type: str = "",
    resolution: str = "",
    tags: list[str] = None,
) -> Optional[int]:
    """Add a QC case (experience record) to a knowledge base.

    Cases are documents with additional metadata for structured retrieval.
    Returns doc_id or None.
    """
    # First add as a regular document
    case_text = f"# {title}\n\n{content}"
    if resolution:
        case_text += f"\n\n## 处理方案\n{resolution}"

    doc_id = add_document(kb_id, f"case_{title[:30]}.md", case_text, "text/markdown")
    if not doc_id:
        return None

    # Update case-specific fields
    engine = get_engine()
    if not engine:
        return doc_id
    try:
        import json as _json
        with engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {T_KB_DOCUMENTS}
                SET doc_type = 'case',
                    defect_category = :dc,
                    product_type = :pt,
                    resolution = :res,
                    tags = :tags::jsonb
                WHERE id = :id
            """), {
                "id": doc_id,
                "dc": defect_category or None,
                "pt": product_type or None,
                "res": resolution or None,
                "tags": _json.dumps(tags or []),
            })
            conn.commit()
    except Exception as e:
        logger.warning("[KB] Failed to update case metadata for doc %d: %s", doc_id, e)

    return doc_id


def search_cases(
    query: str = "",
    kb_id: int = None,
    defect_category: str = "",
    product_type: str = "",
    top_k: int = 10,
) -> list[dict]:
    """Search cases by defect category, product type, and/or semantic query.

    Returns list of case dicts with metadata.
    """
    engine = get_engine()
    if not engine:
        return []

    try:
        conditions = [f"d.doc_type = 'case'"]
        params: dict = {"lim": top_k}

        if kb_id:
            conditions.append("d.kb_id = :kb_id")
            params["kb_id"] = kb_id
        if defect_category:
            conditions.append("d.defect_category = :dc")
            params["dc"] = defect_category
        if product_type:
            conditions.append("d.product_type = :pt")
            params["pt"] = product_type

        where = " AND ".join(conditions)

        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT d.id, d.kb_id, d.filename, d.defect_category,
                       d.product_type, d.resolution, d.tags,
                       d.raw_text, d.created_at
                FROM {T_KB_DOCUMENTS} d
                WHERE {where}
                ORDER BY d.created_at DESC
                LIMIT :lim
            """), params).mappings().all()

            results = []
            for r in rows:
                results.append({
                    "doc_id": r["id"],
                    "kb_id": r["kb_id"],
                    "filename": r["filename"],
                    "defect_category": r["defect_category"],
                    "product_type": r["product_type"],
                    "resolution": r["resolution"],
                    "tags": r["tags"] if r["tags"] else [],
                    "preview": (r["raw_text"] or "")[:200],
                    "created_at": str(r["created_at"]),
                })

        # If query provided, also do semantic search and merge
        if query and kb_id:
            semantic = search_kb(query, kb_ids=[kb_id], top_k=top_k)
            # Merge: add semantic results not already in structured results
            existing_ids = {r["doc_id"] for r in results}
            for sr in semantic:
                if sr.get("doc_id") not in existing_ids:
                    results.append(sr)

        return results[:top_k]
    except Exception as e:
        logger.warning("[KB] search_cases failed: %s", e)
        return []


def list_cases(kb_id: int = None) -> list[dict]:
    """List all cases, optionally filtered by KB."""
    return search_cases(kb_id=kb_id, top_k=100)
