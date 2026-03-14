"""Tests for GraphRAG (v10.0.5).

Covers entity extraction, deduplication, graph construction,
graph-augmented retrieval, and REST endpoints.
"""
import asyncio
import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class TestEntityExtraction(unittest.TestCase):
    def test_regex_extraction_crs(self):
        from data_agent.graph_rag import extract_entities_from_text
        entities = extract_entities_from_text("数据使用 EPSG:4326 坐标系统")
        names = [e["name"] for e in entities]
        self.assertIn("EPSG:4326", names)

    def test_regex_extraction_location(self):
        from data_agent.graph_rag import extract_entities_from_text
        entities = extract_entities_from_text("北京市海淀区的数据分析")
        types = [e["type"] for e in entities]
        self.assertIn("location", types)

    def test_regex_extraction_standard(self):
        from data_agent.graph_rag import extract_entities_from_text
        entities = extract_entities_from_text("符合 GB/T 21010 标准")
        names = [e["name"] for e in entities]
        self.assertIn("GB/T 21010", names)

    def test_regex_extraction_metric(self):
        from data_agent.graph_rag import extract_entities_from_text
        entities = extract_entities_from_text("计算 NDVI 和 DEM 数据")
        names = [e["name"] for e in entities]
        self.assertIn("NDVI", names)
        self.assertIn("DEM", names)

    def test_empty_text(self):
        from data_agent.graph_rag import extract_entities_from_text
        self.assertEqual(extract_entities_from_text(""), [])
        self.assertEqual(extract_entities_from_text(None), [])

    def test_extract_combined_no_llm(self):
        from data_agent.graph_rag import extract_entities
        entities = extract_entities("EPSG:4326 北京市的数据", use_llm=False)
        self.assertGreater(len(entities), 0)


class TestEntityDeduplication(unittest.TestCase):
    def test_exact_duplicate(self):
        from data_agent.graph_rag import deduplicate_entities
        entities = [
            {"name": "北京市", "type": "location", "confidence": 0.9},
            {"name": "北京市", "type": "location", "confidence": 0.8},
        ]
        result = deduplicate_entities(entities)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["confidence"], 0.9)  # keeps higher

    def test_different_types_not_dedup(self):
        from data_agent.graph_rag import deduplicate_entities
        entities = [
            {"name": "DEM", "type": "metric", "confidence": 0.9},
            {"name": "DEM", "type": "dataset", "confidence": 0.8},
        ]
        result = deduplicate_entities(entities)
        self.assertEqual(len(result), 2)

    def test_fuzzy_match(self):
        from data_agent.graph_rag import _is_duplicate
        self.assertTrue(_is_duplicate("北京市海淀区", "北京市海淀区", "location", "location"))
        self.assertFalse(_is_duplicate("北京", "上海", "location", "location"))

    def test_empty_list(self):
        from data_agent.graph_rag import deduplicate_entities
        self.assertEqual(deduplicate_entities([]), [])


class TestGraphConstruction(unittest.TestCase):
    @patch("data_agent.graph_rag.get_engine", return_value=None)
    def test_build_no_engine(self, _):
        from data_agent.graph_rag import build_kb_graph
        result = build_kb_graph(1)
        self.assertEqual(result["status"], "error")

    @patch("data_agent.graph_rag.get_engine")
    def test_build_empty_kb(self, mock_eng):
        from data_agent.graph_rag import build_kb_graph
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        # DELETE calls return nothing, then SELECT returns empty
        mock_conn.execute.side_effect = [
            MagicMock(),  # DELETE relations
            MagicMock(),  # DELETE entities
            MagicMock(fetchall=MagicMock(return_value=[])),  # SELECT chunks
        ]
        result = build_kb_graph(1, use_llm=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["entities"], 0)

    @patch("data_agent.graph_rag.get_engine")
    def test_build_with_chunks(self, mock_eng):
        from data_agent.graph_rag import build_kb_graph
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        entity_id_counter = [0]
        def mock_execute(sql_text, params=None):
            result = MagicMock()
            sql_str = str(sql_text) if hasattr(sql_text, 'text') else str(sql_text)
            if "DELETE" in sql_str:
                return result
            if "SELECT" in sql_str and "agent_kb_chunks" in sql_str:
                result.fetchall = MagicMock(return_value=[
                    (1, "EPSG:4326 北京市的数据 NDVI分析"),
                    (2, "上海市 DEM 数据处理"),
                ])
                return result
            if "INSERT" in sql_str and "RETURNING" in sql_str:
                entity_id_counter[0] += 1
                result.scalar = MagicMock(return_value=entity_id_counter[0])
                return result
            return result

        mock_conn.execute = mock_execute
        result = build_kb_graph(1, use_llm=False)
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["entities"], 0)

    @patch("data_agent.graph_rag.get_engine", return_value=None)
    def test_incremental_no_engine(self, _):
        from data_agent.graph_rag import incremental_graph_update
        result = incremental_graph_update(1, 1)
        self.assertEqual(result["status"], "error")


class TestGraphAugmentedRetrieval(unittest.TestCase):
    @patch("data_agent.knowledge_base.search_kb", return_value=[])
    def test_empty_vector_results(self, _):
        from data_agent.graph_rag import graph_rag_search
        results = graph_rag_search("test query", kb_id=1)
        self.assertEqual(results, [])

    @patch("data_agent.graph_rag.get_engine", return_value=None)
    @patch("data_agent.knowledge_base.search_kb")
    def test_vector_only_no_db(self, mock_search, _):
        from data_agent.graph_rag import graph_rag_search
        mock_search.return_value = [
            {"chunk_id": 1, "content": "test", "score": 0.9},
        ]
        results = graph_rag_search("test", kb_id=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "vector")


class TestEntityGraph(unittest.TestCase):
    @patch("data_agent.graph_rag.get_engine", return_value=None)
    def test_get_graph_no_engine(self, _):
        from data_agent.graph_rag import get_entity_graph
        result = get_entity_graph(1)
        self.assertEqual(result["nodes"], [])

    @patch("data_agent.graph_rag.get_engine")
    def test_get_graph_with_data(self, mock_eng):
        from data_agent.graph_rag import get_entity_graph
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[
                (1, "北京市", "location", 0.9),
                (2, "NDVI", "metric", 0.85),
            ])),
            MagicMock(fetchall=MagicMock(return_value=[
                (1, 2, "co_occurs_with", 0.8),
            ])),
        ]
        result = get_entity_graph(1)
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual(len(result["links"]), 1)
        self.assertEqual(result["stats"]["node_count"], 2)


class TestGraphRAGRoutes(unittest.TestCase):
    def test_routes_registered(self):
        from data_agent.frontend_api import get_frontend_api_routes
        routes = get_frontend_api_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/kb/{id:int}/build-graph", paths)
        self.assertIn("/api/kb/{id:int}/graph", paths)
        self.assertIn("/api/kb/{id:int}/graph-search", paths)
        self.assertIn("/api/kb/{id:int}/entities", paths)

    @patch("data_agent.frontend_api._get_user_from_request", return_value=None)
    def test_build_graph_unauthorized(self, _):
        from data_agent.frontend_api import _api_kb_build_graph
        req = MagicMock()
        req.path_params = {"id": "1"}
        resp = _run_async(_api_kb_build_graph(req))
        self.assertEqual(resp.status_code, 401)


class TestGraphRAGToolset(unittest.TestCase):
    def test_kb_toolset_has_9_tools(self):
        from data_agent.toolsets.knowledge_base_tools import _ALL_FUNCS
        self.assertEqual(len(_ALL_FUNCS), 9)  # 6 original + 3 GraphRAG


class TestConstants(unittest.TestCase):
    def test_table_names(self):
        from data_agent.graph_rag import T_KB_ENTITIES, T_KB_RELATIONS
        self.assertEqual(T_KB_ENTITIES, "agent_kb_entities")
        self.assertEqual(T_KB_RELATIONS, "agent_kb_relations")

    def test_entity_types(self):
        from data_agent.graph_rag import ENTITY_TYPES
        self.assertIn("location", ENTITY_TYPES)
        self.assertIn("metric", ENTITY_TYPES)
        self.assertIn("dataset", ENTITY_TYPES)


if __name__ == "__main__":
    unittest.main()
