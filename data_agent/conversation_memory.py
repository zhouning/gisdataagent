"""
Cross-Session Conversation Memory (v9.0.3).

PostgreSQL-backed implementation of ADK ``BaseMemoryService`` that persists
key findings across sessions.  Falls back to ``InMemoryMemoryService`` when
the database is unavailable.

Usage::

    from data_agent.conversation_memory import get_memory_service
    memory_service = get_memory_service()   # PostgreSQL or in-memory fallback
    runner = Runner(..., memory_service=memory_service)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from difflib import SequenceMatcher
from typing import Sequence, Mapping

from google.adk.memory.base_memory_service import BaseMemoryService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.sessions import Session
from google.adk.events import Event
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types

logger = logging.getLogger("data_agent.conversation_memory")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

T_MEMORIES = "agent_conversation_memories"
MAX_MEMORIES_PER_USER = 500
MIN_TEXT_LENGTH = 20  # Skip trivially short content

# ADK memory search response type
from google.adk.memory.base_memory_service import SearchMemoryResponse


# ---------------------------------------------------------------------------
# Chinese n-gram tokenizer (shared with data_catalog)
# ---------------------------------------------------------------------------

def _tokenize_query(text: str) -> list[str]:
    """Extract tokens from text with Chinese n-gram support."""
    lower = text.lower()
    raw_tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', lower)
    tokens = []
    for tok in raw_tokens:
        if re.match(r'^[\u4e00-\u9fff]+$', tok) and len(tok) > 2:
            for n in (2, 3):
                for i in range(len(tok) - n + 1):
                    tokens.append(tok[i:i + n])
            tokens.append(tok)
        else:
            tokens.append(tok)
    # Deduplicate preserving order
    seen = set()
    unique = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _content_hash(text: str) -> str:
    """SHA-256 hash of text for dedup."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# PostgreSQL Memory Service
# ---------------------------------------------------------------------------

class PostgresMemoryService(BaseMemoryService):
    """Persistent memory service backed by PostgreSQL.

    Stores conversation key-findings per (app_name, user_id) with
    content-hash deduplication and per-user quota enforcement.
    """

    def __init__(self):
        self._table_ensured = False

    def _ensure_table(self):
        """Create the memories table if it doesn't exist."""
        if self._table_ensured:
            return
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not configured")
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_MEMORIES} (
                    id SERIAL PRIMARY KEY,
                    app_name VARCHAR(200) NOT NULL DEFAULT 'data_agent',
                    user_id VARCHAR(200) NOT NULL,
                    session_id VARCHAR(200) DEFAULT '',
                    content_text TEXT NOT NULL,
                    content_hash VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    metadata JSONB DEFAULT '{{}}'::jsonb
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{T_MEMORIES}_user
                ON {T_MEMORIES} (app_name, user_id)
            """))
            conn.execute(text(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{T_MEMORIES}_hash
                ON {T_MEMORIES} (app_name, user_id, content_hash)
            """))
            conn.commit()
        self._table_ensured = True

    # -----------------------------------------------------------------------
    # BaseMemoryService interface
    # -----------------------------------------------------------------------

    async def add_session_to_memory(self, session: Session) -> None:
        """Extract key findings from a completed session and persist them."""
        if not session or not session.events:
            return
        # Collect text from non-user events (agent output)
        texts = []
        for event in session.events:
            if getattr(event, "author", None) == "user":
                continue
            if not (event.content and event.content.parts):
                continue
            for part in event.content.parts:
                if part.text and len(part.text) >= MIN_TEXT_LENGTH:
                    texts.append(part.text)
        if not texts:
            return

        # Combine into a single memory entry (truncate to 2000 chars)
        combined = "\n---\n".join(texts)[:2000]
        await self._store_memory(
            app_name=session.app_name,
            user_id=session.user_id,
            content=combined,
            session_id=session.id,
        )

    async def add_events_to_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        events: Sequence[Event],
        session_id: str | None = None,
        custom_metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Store a set of events as memory entries."""
        texts = []
        for event in events:
            if not (event.content and event.content.parts):
                continue
            for part in event.content.parts:
                if part.text and len(part.text) >= MIN_TEXT_LENGTH:
                    texts.append(part.text)
        if not texts:
            return
        combined = "\n---\n".join(texts)[:2000]
        metadata = dict(custom_metadata) if custom_metadata else {}
        await self._store_memory(
            app_name=app_name,
            user_id=user_id,
            content=combined,
            session_id=session_id or "",
            metadata=metadata,
        )

    async def add_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        memories: Sequence[MemoryEntry],
        custom_metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Store explicit MemoryEntry objects."""
        for mem in memories:
            # Extract text from Content object
            text_parts = []
            if mem.content and mem.content.parts:
                for part in mem.content.parts:
                    if hasattr(part, "text") and part.text:
                        text_parts.append(part.text)
            content = "\n".join(text_parts)
            if len(content) < MIN_TEXT_LENGTH:
                continue
            metadata = dict(custom_metadata) if custom_metadata else {}
            await self._store_memory(
                app_name=app_name,
                user_id=user_id,
                content=content[:2000],
                metadata=metadata,
            )

    async def search_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        query: str,
    ) -> SearchMemoryResponse:
        """Search stored memories using Chinese-aware n-gram matching."""
        try:
            self._ensure_table()
        except Exception:
            return SearchMemoryResponse(memories=[])

        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return SearchMemoryResponse(memories=[])

        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f"""
                        SELECT id, content_text, created_at, session_id
                        FROM {T_MEMORIES}
                        WHERE app_name = :app AND user_id = :uid
                        ORDER BY created_at DESC
                        LIMIT 200
                    """),
                    {"app": app_name, "uid": user_id},
                ).fetchall()
        except Exception as e:
            logger.warning("Memory search DB error: %s", e)
            return SearchMemoryResponse(memories=[])

        if not rows:
            return SearchMemoryResponse(memories=[])

        # Score and rank
        query_tokens = _tokenize_query(query)
        query_lower = query.lower()
        scored = []
        for row in rows:
            content = (row[1] or "").lower()
            # Direct substring
            if query_lower in content:
                score = 0.9
            elif query_tokens:
                hits = sum(1 for t in query_tokens if t in content)
                token_score = hits / len(query_tokens) * 0.85
                fuzzy = SequenceMatcher(None, query_lower, content[:200]).ratio()
                score = max(token_score, fuzzy)
            else:
                score = 0.0
            if score >= 0.2:
                scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:10]

        # Build MemoryEntry list
        results = []
        for score, row in top:
            content = types.Content(
                role="model",
                parts=[types.Part(text=row[1])],
            )
            entry = MemoryEntry(content=content)
            results.append(entry)

        return SearchMemoryResponse(memories=results)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _store_memory(
        self,
        app_name: str,
        user_id: str,
        content: str,
        session_id: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Insert a memory entry with dedup and quota enforcement."""
        try:
            self._ensure_table()
        except Exception as e:
            logger.warning("Cannot store memory: %s", e)
            return

        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return

        ch = _content_hash(content)

        try:
            with engine.connect() as conn:
                # Upsert — skip if content_hash already exists
                conn.execute(
                    text(f"""
                        INSERT INTO {T_MEMORIES}
                            (app_name, user_id, session_id, content_text, content_hash, metadata)
                        VALUES (:app, :uid, :sid, :content, :hash, :meta)
                        ON CONFLICT (app_name, user_id, content_hash) DO NOTHING
                    """),
                    {
                        "app": app_name,
                        "uid": user_id,
                        "sid": session_id,
                        "content": content,
                        "hash": ch,
                        "meta": json.dumps(metadata or {}),
                    },
                )
                # Enforce per-user quota — delete oldest beyond MAX
                conn.execute(
                    text(f"""
                        DELETE FROM {T_MEMORIES}
                        WHERE id IN (
                            SELECT id FROM {T_MEMORIES}
                            WHERE app_name = :app AND user_id = :uid
                            ORDER BY created_at DESC
                            OFFSET :max_count
                        )
                    """),
                    {"app": app_name, "uid": user_id, "max_count": MAX_MEMORIES_PER_USER},
                )
                conn.commit()
        except Exception as e:
            logger.warning("Memory store error: %s", e)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_memory_service() -> BaseMemoryService:
    """Return PostgresMemoryService if DB is available, else InMemory fallback."""
    try:
        from .db_engine import get_engine
        engine = get_engine()
        if engine:
            svc = PostgresMemoryService()
            svc._ensure_table()
            logger.info("Using PostgresMemoryService for conversation memory")
            return svc
    except Exception as e:
        logger.warning("PostgresMemoryService unavailable (%s), falling back to InMemory", e)

    return InMemoryMemoryService()
