"""
Tests for Cross-Session Conversation Memory (v9.0.3).

Tests PostgresMemoryService, tokenizer, content hash, factory,
and integration with pipeline_runner.
"""

import hashlib
import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class TestTokenizer(unittest.TestCase):
    """Test Chinese-aware n-gram tokenizer."""

    def test_english_tokens(self):
        from data_agent.conversation_memory import _tokenize_query
        tokens = _tokenize_query("land use analysis")
        self.assertIn("land", tokens)
        self.assertIn("use", tokens)
        self.assertIn("analysis", tokens)

    def test_chinese_ngrams(self):
        from data_agent.conversation_memory import _tokenize_query
        tokens = _tokenize_query("土地利用分析")
        # Should have 2-char and 3-char n-grams
        self.assertIn("土地", tokens)
        self.assertIn("地利", tokens)
        self.assertIn("利用", tokens)
        self.assertIn("用分", tokens)
        self.assertIn("分析", tokens)
        self.assertIn("土地利", tokens)
        # Full token
        self.assertIn("土地利用分析", tokens)

    def test_mixed_text(self):
        from data_agent.conversation_memory import _tokenize_query
        tokens = _tokenize_query("DEM数据分析")
        self.assertIn("dem", tokens)  # lowercased
        self.assertIn("数据", tokens)

    def test_short_chinese(self):
        """Short Chinese (<=2 chars) should not be n-grammed."""
        from data_agent.conversation_memory import _tokenize_query
        tokens = _tokenize_query("土地")
        self.assertEqual(tokens, ["土地"])

    def test_dedup(self):
        from data_agent.conversation_memory import _tokenize_query
        tokens = _tokenize_query("test test test")
        self.assertEqual(tokens.count("test"), 1)


# ---------------------------------------------------------------------------
# Content Hash
# ---------------------------------------------------------------------------

class TestContentHash(unittest.TestCase):

    def test_hash_deterministic(self):
        from data_agent.conversation_memory import _content_hash
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        self.assertEqual(h1, h2)

    def test_hash_length(self):
        from data_agent.conversation_memory import _content_hash
        h = _content_hash("test content")
        self.assertEqual(len(h), 32)

    def test_different_content_different_hash(self):
        from data_agent.conversation_memory import _content_hash
        h1 = _content_hash("content A")
        h2 = _content_hash("content B")
        self.assertNotEqual(h1, h2)


# ---------------------------------------------------------------------------
# PostgresMemoryService
# ---------------------------------------------------------------------------

class TestPostgresMemoryService(unittest.IsolatedAsyncioTestCase):
    """Test PostgresMemoryService methods."""

    def _make_service(self):
        from data_agent.conversation_memory import PostgresMemoryService
        svc = PostgresMemoryService()
        svc._table_ensured = True  # Skip DB table creation
        return svc

    def _make_session(self, events=None, user_id="user1", app_name="test_app"):
        session = MagicMock()
        session.app_name = app_name
        session.user_id = user_id
        session.id = "session_001"
        session.events = events or []
        return session

    def _make_event(self, text, author="agent"):
        event = MagicMock()
        event.author = author
        part = MagicMock()
        part.text = text
        event.content = MagicMock()
        event.content.parts = [part]
        return event

    async def test_add_session_empty(self):
        svc = self._make_service()
        session = self._make_session(events=[])
        # Should not raise
        await svc.add_session_to_memory(session)

    async def test_add_session_skips_user_events(self):
        svc = self._make_service()
        user_event = self._make_event("user question", author="user")
        session = self._make_session(events=[user_event])
        with patch.object(svc, "_store_memory", new_callable=AsyncMock) as mock_store:
            await svc.add_session_to_memory(session)
            mock_store.assert_not_called()

    async def test_add_session_stores_agent_text(self):
        svc = self._make_service()
        agent_event = self._make_event("This is a detailed analysis of the land use data showing significant patterns.")
        session = self._make_session(events=[agent_event])
        with patch.object(svc, "_store_memory", new_callable=AsyncMock) as mock_store:
            await svc.add_session_to_memory(session)
            mock_store.assert_called_once()
            call_kwargs = mock_store.call_args
            self.assertIn("detailed analysis", call_kwargs.kwargs.get("content", call_kwargs[1].get("content", "")))

    async def test_add_session_skips_short_text(self):
        svc = self._make_service()
        short_event = self._make_event("OK")  # < MIN_TEXT_LENGTH
        session = self._make_session(events=[short_event])
        with patch.object(svc, "_store_memory", new_callable=AsyncMock) as mock_store:
            await svc.add_session_to_memory(session)
            mock_store.assert_not_called()

    async def test_add_session_truncates_long_content(self):
        svc = self._make_service()
        long_text = "A" * 3000
        agent_event = self._make_event(long_text)
        session = self._make_session(events=[agent_event])
        with patch.object(svc, "_store_memory", new_callable=AsyncMock) as mock_store:
            await svc.add_session_to_memory(session)
            content = mock_store.call_args.kwargs.get("content", mock_store.call_args[1].get("content", ""))
            self.assertLessEqual(len(content), 2000)

    @patch("data_agent.db_engine.get_engine", return_value=None)
    async def test_search_memory_no_db(self, mock_engine):
        svc = self._make_service()
        svc._table_ensured = False  # Force _ensure_table to run
        result = await svc.search_memory(app_name="test", user_id="u1", query="test")
        self.assertEqual(result.memories, [])

    @patch("data_agent.db_engine.get_engine")
    async def test_search_memory_with_results(self, mock_get_engine):
        svc = self._make_service()
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "Detailed analysis of land use patterns in the region", "2024-01-01", "s1"),
            (2, "Statistical summary of spatial features and correlations", "2024-01-02", "s2"),
        ]

        result = await svc.search_memory(app_name="test", user_id="u1", query="land use analysis")
        self.assertGreater(len(result.memories), 0)

    @patch("data_agent.db_engine.get_engine")
    async def test_store_memory_dedup(self, mock_get_engine):
        """_store_memory should use ON CONFLICT DO NOTHING for dedup."""
        svc = self._make_service()
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        await svc._store_memory(
            app_name="test", user_id="u1",
            content="Test memory content for dedup",
        )
        # Should have been called (INSERT + DELETE for quota)
        self.assertEqual(mock_conn.execute.call_count, 2)
        mock_conn.commit.assert_called_once()

    async def test_add_events_to_memory(self):
        svc = self._make_service()
        event = self._make_event("This is a substantial finding about spatial data patterns.")
        with patch.object(svc, "_store_memory", new_callable=AsyncMock) as mock_store:
            await svc.add_events_to_memory(
                app_name="test", user_id="u1", events=[event],
            )
            mock_store.assert_called_once()

    async def test_add_memory_entries(self):
        from data_agent.conversation_memory import MemoryEntry
        from google.genai import types
        svc = self._make_service()
        content = types.Content(
            role="model",
            parts=[types.Part(text="This is a significant memory entry for testing purposes")],
        )
        mem = MemoryEntry(content=content)
        with patch.object(svc, "_store_memory", new_callable=AsyncMock) as mock_store:
            await svc.add_memory(
                app_name="test", user_id="u1", memories=[mem],
            )
            mock_store.assert_called_once()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestGetMemoryService(unittest.TestCase):
    """Test get_memory_service factory."""

    @patch("data_agent.db_engine.get_engine", return_value=None)
    def test_fallback_to_inmemory(self, mock_engine):
        from data_agent.conversation_memory import get_memory_service
        svc = get_memory_service()
        self.assertIsInstance(svc, InMemoryMemoryService)

    @patch("data_agent.db_engine.get_engine")
    def test_postgres_when_db_available(self, mock_get_engine):
        from data_agent.conversation_memory import PostgresMemoryService, get_memory_service
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        svc = get_memory_service()
        self.assertIsInstance(svc, PostgresMemoryService)


# Import at module level after class definitions
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService


# ---------------------------------------------------------------------------
# BaseMemoryService compliance
# ---------------------------------------------------------------------------

class TestBaseMemoryServiceCompliance(unittest.TestCase):
    """Verify PostgresMemoryService is a proper BaseMemoryService subclass."""

    def test_is_subclass(self):
        from data_agent.conversation_memory import PostgresMemoryService
        from google.adk.memory.base_memory_service import BaseMemoryService
        self.assertTrue(issubclass(PostgresMemoryService, BaseMemoryService))

    def test_has_required_methods(self):
        from data_agent.conversation_memory import PostgresMemoryService
        svc = PostgresMemoryService()
        self.assertTrue(hasattr(svc, "add_session_to_memory"))
        self.assertTrue(hasattr(svc, "search_memory"))
        self.assertTrue(hasattr(svc, "add_events_to_memory"))
        self.assertTrue(hasattr(svc, "add_memory"))


# ---------------------------------------------------------------------------
# PipelineResult + memory_service param
# ---------------------------------------------------------------------------

class TestPipelineRunnerMemoryParam(unittest.TestCase):
    """Verify pipeline_runner accepts memory_service parameter."""

    def test_run_pipeline_headless_signature(self):
        import inspect
        from data_agent.pipeline_runner import run_pipeline_headless
        sig = inspect.signature(run_pipeline_headless)
        self.assertIn("memory_service", sig.parameters)


if __name__ == "__main__":
    unittest.main()
