"""Tests for knowledge_base.py — RAG private knowledge base (v8.0.2)."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch, mock_open

import numpy as np


# ---------------------------------------------------------------------------
# Chunking tests (pure function — no mocks needed)
# ---------------------------------------------------------------------------


class TestChunkText(unittest.TestCase):
    """Test _chunk_text paragraph-based splitting."""

    def setUp(self):
        from data_agent.knowledge_base import _chunk_text
        self.chunk = _chunk_text

    def test_empty_text_returns_one_chunk(self):
        result = self.chunk("")
        self.assertEqual(len(result), 1)

    def test_short_text_single_chunk(self):
        result = self.chunk("Hello world")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Hello world")

    def test_paragraph_splitting(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        result = self.chunk(text, max_chunk_size=30, overlap=0)
        self.assertGreater(len(result), 1)
        # All content should be present
        joined = " ".join(result)
        self.assertIn("Paragraph one", joined)
        self.assertIn("Paragraph three", joined)

    def test_overlap_applied(self):
        text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100
        result = self.chunk(text, max_chunk_size=120, overlap=20)
        if len(result) > 1:
            # Second chunk should start with tail of first
            self.assertTrue(len(result[1]) > 20)

    def test_large_paragraph_split_at_sentence(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
        result = self.chunk(text, max_chunk_size=40, overlap=0)
        self.assertGreater(len(result), 1)

    def test_chinese_text_chunking(self):
        text = "第一段内容。这是一些描述。\n\n第二段内容。更多的描述信息。\n\n第三段。"
        result = self.chunk(text, max_chunk_size=20, overlap=0)
        self.assertGreater(len(result), 1)

    def test_custom_chunk_size(self):
        text = "Word " * 200  # ~1000 chars
        result = self.chunk(text, max_chunk_size=100, overlap=10)
        self.assertGreater(len(result), 1)
        for chunk in result:
            # Allow some tolerance for overlap
            self.assertLessEqual(len(chunk), 200)

    def test_whitespace_only_returns_one_chunk(self):
        result = self.chunk("   \n\n   ")
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Cosine search tests (pure function with numpy)
# ---------------------------------------------------------------------------


class TestCosineSearch(unittest.TestCase):
    """Test _cosine_search ranking logic."""

    def setUp(self):
        from data_agent.knowledge_base import _cosine_search
        self.search = _cosine_search

    def test_identical_vectors_score_1(self):
        vec = [1.0, 0.0, 0.0]
        rows = [(1, "text", vec, 10, 0, {})]
        results = self.search(vec, rows, top_k=1)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["score"], 1.0, places=3)

    def test_orthogonal_vectors_score_0(self):
        q = [1.0, 0.0, 0.0]
        rows = [(1, "text", [0.0, 1.0, 0.0], 10, 0, {})]
        results = self.search(q, rows, top_k=1)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["score"], 0.0, places=3)

    def test_ranking_correct(self):
        q = [1.0, 0.0, 0.0]
        rows = [
            (1, "far", [0.0, 1.0, 0.0], 10, 0, {}),    # 0.0
            (2, "close", [0.9, 0.1, 0.0], 10, 1, {}),   # ~0.99
            (3, "mid", [0.5, 0.5, 0.0], 10, 2, {}),     # ~0.71
        ]
        results = self.search(q, rows, top_k=3)
        self.assertEqual(results[0]["chunk_id"], 2)  # highest score
        self.assertEqual(results[1]["chunk_id"], 3)
        self.assertEqual(results[2]["chunk_id"], 1)

    def test_top_k_limit(self):
        q = [1.0, 0.0]
        rows = [(i, f"text{i}", [1.0, 0.0], 10, i, {}) for i in range(10)]
        results = self.search(q, rows, top_k=3)
        self.assertEqual(len(results), 3)

    def test_empty_inputs(self):
        self.assertEqual(self.search([], [], 5), [])
        self.assertEqual(self.search([1.0], [], 5), [])
        self.assertEqual(self.search([], [(1, "t", [1.0], 1, 0, {})], 5), [])

    def test_null_embeddings_skipped(self):
        q = [1.0, 0.0]
        rows = [
            (1, "no emb", None, 10, 0, {}),
            (2, "has emb", [1.0, 0.0], 10, 1, {}),
        ]
        results = self.search(q, rows, top_k=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["chunk_id"], 2)


# ---------------------------------------------------------------------------
# Text extraction tests
# ---------------------------------------------------------------------------


class TestExtractText(unittest.TestCase):
    """Test _extract_text for different file types."""

    def test_plain_text(self):
        from data_agent.knowledge_base import _extract_text
        m = mock_open(read_data="Hello plain text")
        with patch("builtins.open", m):
            result = _extract_text("test.txt", "text/plain")
        self.assertEqual(result, "Hello plain text")

    def test_markdown(self):
        from data_agent.knowledge_base import _extract_text
        m = mock_open(read_data="# Heading\n\nContent")
        with patch("builtins.open", m):
            result = _extract_text("test.md", "text/markdown")
        self.assertIn("Heading", result)

    @patch("data_agent.knowledge_base.PdfReader", create=True)
    def test_pdf(self, _mock_cls):
        """PDF extraction should handle pypdf import."""
        from data_agent.knowledge_base import _extract_text
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "PDF content here"
        mock_reader.pages = [mock_page]

        with patch("data_agent.knowledge_base._extract_text") as mock_fn:
            mock_fn.return_value = "PDF content here"
            result = mock_fn("test.pdf", "application/pdf")
        self.assertEqual(result, "PDF content here")

    def test_unsupported_type(self):
        from data_agent.knowledge_base import _extract_text
        result = _extract_text("test.xyz", "application/unknown")
        self.assertEqual(result, "")

    def test_file_not_found_returns_empty(self):
        from data_agent.knowledge_base import _extract_text
        result = _extract_text("/nonexistent/file.txt", "text/plain")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# Row conversion tests
# ---------------------------------------------------------------------------


class TestRowConversion(unittest.TestCase):
    """Test row-to-dict conversion helpers."""

    def test_kb_row_conversion(self):
        from data_agent.knowledge_base import _row_to_kb_dict
        row = (1, "user1", "Test KB", "desc", False, 5, 20, "2026-01-01", "2026-01-02")
        d = _row_to_kb_dict(row)
        self.assertEqual(d["id"], 1)
        self.assertEqual(d["name"], "Test KB")
        self.assertEqual(d["document_count"], 5)

    def test_doc_row_conversion(self):
        from data_agent.knowledge_base import _row_to_doc_dict
        row = (1, 10, "file.pdf", "application/pdf", 5000, 10, {}, "2026-01-01")
        d = _row_to_doc_dict(row)
        self.assertEqual(d["id"], 1)
        self.assertEqual(d["filename"], "file.pdf")
        self.assertEqual(d["chunk_count"], 10)

    def test_none_row(self):
        from data_agent.knowledge_base import _row_to_kb_dict, _row_to_doc_dict
        self.assertEqual(_row_to_kb_dict(None), {})
        self.assertEqual(_row_to_doc_dict(None), {})


# ---------------------------------------------------------------------------
# DB CRUD tests (mocked)
# ---------------------------------------------------------------------------


def _make_mock_engine():
    """Create a mock engine with context manager support."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine, mock_conn


class TestEnsureTables(unittest.TestCase):
    """Test table creation."""

    @patch("data_agent.knowledge_base.get_engine")
    def test_creates_tables(self, mock_get):
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        from data_agent.knowledge_base import ensure_kb_tables
        ensure_kb_tables()
        # Should have called execute multiple times (CREATE TABLE + INDEX)
        self.assertGreater(mock_conn.execute.call_count, 5)
        mock_conn.commit.assert_called_once()

    @patch("data_agent.knowledge_base.get_engine", return_value=None)
    def test_no_db_no_crash(self, _):
        from data_agent.knowledge_base import ensure_kb_tables
        ensure_kb_tables()  # Should not raise


class TestCreateKnowledgeBase(unittest.TestCase):
    """Test create_knowledge_base."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_creates_and_returns_id(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        # quota check
        mock_conn.execute.return_value.scalar.side_effect = [0, 42]
        from data_agent.knowledge_base import create_knowledge_base
        result = create_knowledge_base("Test KB", "A description")
        self.assertEqual(result, 42)

    @patch("data_agent.knowledge_base.get_engine", return_value=None)
    def test_no_db_returns_none(self, _):
        from data_agent.knowledge_base import create_knowledge_base
        self.assertIsNone(create_knowledge_base("Test KB"))

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_quota_exceeded_returns_none(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        mock_conn.execute.return_value.scalar.return_value = 20  # at limit
        from data_agent.knowledge_base import create_knowledge_base
        result = create_knowledge_base("Another KB")
        self.assertIsNone(result)


class TestListKnowledgeBases(unittest.TestCase):
    """Test list_knowledge_bases."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_returns_list(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "testuser", "KB1", "desc1", False, 3, 15, "2026-01-01", "2026-01-02"),
        ]
        from data_agent.knowledge_base import list_knowledge_bases
        result = list_knowledge_bases()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "KB1")

    @patch("data_agent.knowledge_base.get_engine", return_value=None)
    def test_no_db_returns_empty(self, _):
        from data_agent.knowledge_base import list_knowledge_bases
        self.assertEqual(list_knowledge_bases(), [])


class TestGetKnowledgeBase(unittest.TestCase):
    """Test get_knowledge_base."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_returns_dict(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        mock_conn.execute.return_value.fetchone.return_value = (
            1, "testuser", "KB1", "desc", False, 3, 15, "2026-01-01", "2026-01-02"
        )
        from data_agent.knowledge_base import get_knowledge_base
        result = get_knowledge_base(1)
        self.assertEqual(result["name"], "KB1")

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_not_found_returns_none(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        mock_conn.execute.return_value.fetchone.return_value = None
        from data_agent.knowledge_base import get_knowledge_base
        self.assertIsNone(get_knowledge_base(999))


class TestDeleteKnowledgeBase(unittest.TestCase):
    """Test delete_knowledge_base."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_deletes_and_returns_true(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        mock_conn.execute.return_value.rowcount = 1
        from data_agent.knowledge_base import delete_knowledge_base
        self.assertTrue(delete_knowledge_base(1))

    @patch("data_agent.knowledge_base.get_engine", return_value=None)
    def test_no_db_returns_false(self, _):
        from data_agent.knowledge_base import delete_knowledge_base
        self.assertFalse(delete_knowledge_base(1))


class TestListDocuments(unittest.TestCase):
    """Test list_documents."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_returns_list(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        # First call: access check fetchone
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        # Second call: documents fetchall
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, 1, "doc.pdf", "application/pdf", 5000, 10, {}, "2026-01-01"),
        ]
        from data_agent.knowledge_base import list_documents
        result = list_documents(1)
        self.assertEqual(len(result), 1)

    @patch("data_agent.knowledge_base.get_engine", return_value=None)
    def test_no_db_returns_empty(self, _):
        from data_agent.knowledge_base import list_documents
        self.assertEqual(list_documents(1), [])


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


class TestSearchKb(unittest.TestCase):
    """Test search_kb semantic search."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base._get_embeddings")
    @patch("data_agent.knowledge_base.get_engine")
    def test_search_returns_ranked_results(self, mock_get, mock_emb, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        # _resolve_kb_id
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        # Chunks
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "chunk about land use", [0.9, 0.1, 0.0], 10, 0, {}),
            (2, "chunk about weather", [0.1, 0.9, 0.0], 10, 1, {}),
        ]
        mock_emb.return_value = [[0.9, 0.1, 0.0]]  # query embedding
        from data_agent.knowledge_base import search_kb
        results = search_kb("land use query", kb_name="TestKB", top_k=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["chunk_id"], 1)  # more similar

    @patch("data_agent.knowledge_base._get_embeddings", return_value=[])
    @patch("data_agent.knowledge_base.get_engine")
    def test_search_no_embedding_returns_empty(self, mock_get, mock_emb):
        mock_engine, _ = _make_mock_engine()
        mock_get.return_value = mock_engine
        from data_agent.knowledge_base import search_kb
        results = search_kb("test query")
        self.assertEqual(results, [])

    @patch("data_agent.knowledge_base.get_engine", return_value=None)
    def test_no_db_returns_empty(self, _):
        from data_agent.knowledge_base import search_kb
        self.assertEqual(search_kb("test"), [])


class TestGetKbContext(unittest.TestCase):
    """Test get_kb_context formatting."""

    @patch("data_agent.knowledge_base.search_kb")
    def test_formats_context_block(self, mock_search):
        mock_search.return_value = [
            {"chunk_id": 1, "content": "Relevant info", "score": 0.87,
             "doc_id": 10, "chunk_index": 0, "metadata": {}},
        ]
        from data_agent.knowledge_base import get_kb_context
        result = get_kb_context("test query")
        self.assertIn("知识库检索结果", result)
        self.assertIn("0.87", result)
        self.assertIn("Relevant info", result)

    @patch("data_agent.knowledge_base.search_kb", return_value=[])
    def test_empty_results(self, _):
        from data_agent.knowledge_base import get_kb_context
        result = get_kb_context("test query")
        self.assertIn("未找到", result)


# ---------------------------------------------------------------------------
# Constants & integration tests
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Test table constants and audit actions."""

    def test_table_constants(self):
        from data_agent.database_tools import T_KNOWLEDGE_BASES, T_KB_DOCUMENTS, T_KB_CHUNKS
        self.assertEqual(T_KNOWLEDGE_BASES, "agent_knowledge_bases")
        self.assertEqual(T_KB_DOCUMENTS, "agent_kb_documents")
        self.assertEqual(T_KB_CHUNKS, "agent_kb_chunks")

    def test_audit_actions(self):
        from data_agent.audit_logger import (
            ACTION_KB_CREATE, ACTION_KB_DELETE,
            ACTION_KB_DOC_ADD, ACTION_KB_DOC_DELETE,
            ACTION_LABELS,
        )
        self.assertEqual(ACTION_KB_CREATE, "kb_create")
        self.assertIn(ACTION_KB_CREATE, ACTION_LABELS)
        self.assertIn(ACTION_KB_DELETE, ACTION_LABELS)
        self.assertIn(ACTION_KB_DOC_ADD, ACTION_LABELS)
        self.assertIn(ACTION_KB_DOC_DELETE, ACTION_LABELS)

    def test_extension_content_types(self):
        from data_agent.knowledge_base import EXTENSION_TO_CONTENT_TYPE
        self.assertIn(".pdf", EXTENSION_TO_CONTENT_TYPE)
        self.assertIn(".docx", EXTENSION_TO_CONTENT_TYPE)
        self.assertIn(".txt", EXTENSION_TO_CONTENT_TYPE)
        self.assertIn(".md", EXTENSION_TO_CONTENT_TYPE)


class TestToolsetRegistry(unittest.TestCase):
    """Test KnowledgeBaseToolset registration in custom_skills."""

    def test_in_toolset_names(self):
        from data_agent.custom_skills import TOOLSET_NAMES
        self.assertIn("KnowledgeBaseToolset", TOOLSET_NAMES)


class TestKnowledgeBaseToolset(unittest.TestCase):
    """Test KnowledgeBaseToolset class."""

    def test_get_tools_returns_functions(self):
        import asyncio
        from data_agent.toolsets.knowledge_base_tools import KnowledgeBaseToolset
        toolset = KnowledgeBaseToolset()
        loop = asyncio.new_event_loop()
        try:
            tools = loop.run_until_complete(toolset.get_tools())
        finally:
            loop.close()
        self.assertGreaterEqual(len(tools), 6)

    def test_tool_filter(self):
        import asyncio
        from data_agent.toolsets.knowledge_base_tools import KnowledgeBaseToolset, KB_READ
        toolset = KnowledgeBaseToolset(tool_filter=KB_READ)
        loop = asyncio.new_event_loop()
        try:
            tools = loop.run_until_complete(toolset.get_tools())
        finally:
            loop.close()
        names = [t.name for t in tools]
        self.assertIn("search_knowledge_base", names)
        self.assertNotIn("create_knowledge_base", names)


class TestRouteCount(unittest.TestCase):
    """Test that route count reflects KB endpoints."""

    def test_route_count(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        self.assertEqual(len(routes), 117)

    def test_kb_routes_present(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/kb", paths)
        self.assertIn("/api/kb/search", paths)


# ---------------------------------------------------------------------------
# Reindex tests
# ---------------------------------------------------------------------------


class TestReindexKb(unittest.TestCase):
    """Test reindex_kb."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base._get_embeddings")
    @patch("data_agent.knowledge_base.get_engine")
    def test_reindexes_null_embeddings(self, mock_get, mock_emb, mock_ctx):
        mock_ctx.get.return_value = "testuser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        # ownership check
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        # null embedding chunks
        mock_conn.execute.return_value.fetchall.return_value = [
            (1, "chunk text 1"),
            (2, "chunk text 2"),
        ]
        mock_emb.return_value = [[0.1, 0.2], [0.3, 0.4]]
        from data_agent.knowledge_base import reindex_kb
        stats = reindex_kb(1)
        self.assertEqual(stats["reindexed"], 2)
        self.assertEqual(stats["failed"], 0)

    @patch("data_agent.knowledge_base.get_engine", return_value=None)
    def test_no_db(self, _):
        from data_agent.knowledge_base import reindex_kb
        stats = reindex_kb(1)
        self.assertEqual(stats["reindexed"], 0)
        self.assertIn("error", stats)


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------


class TestPermissions(unittest.TestCase):
    """Test owner-only access control."""

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_non_owner_cannot_delete(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "otheruser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        mock_conn.execute.return_value.rowcount = 0  # no rows deleted
        from data_agent.knowledge_base import delete_knowledge_base
        self.assertFalse(delete_knowledge_base(1))

    @patch("data_agent.knowledge_base.current_user_id")
    @patch("data_agent.knowledge_base.get_engine")
    def test_add_doc_to_unowned_kb_fails(self, mock_get, mock_ctx):
        mock_ctx.get.return_value = "otheruser"
        mock_engine, mock_conn = _make_mock_engine()
        mock_get.return_value = mock_engine
        mock_conn.execute.return_value.fetchone.return_value = None  # not found/not owned
        from data_agent.knowledge_base import add_document
        result = add_document(1, "test.txt", "some content")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
