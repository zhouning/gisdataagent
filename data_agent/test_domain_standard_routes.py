"""Tests for domain_standard_routes.py — handler functions tested directly."""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(query_params=None, path_params=None, body=None, cookies=None):
    req = MagicMock()
    req.query_params = query_params or {}
    req.path_params = path_params or {}
    req.cookies = cookies or {"access_token": "tok"}
    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(return_value={})
    return req


def _mock_user():
    user = MagicMock()
    user.identifier = "testuser"
    user.metadata = {"role": "analyst"}
    return user


def _write_index(indexes_dir: str, index_data: dict):
    os.makedirs(indexes_dir, exist_ok=True)
    with open(os.path.join(indexes_dir, "xmi_global_index.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(index_data, f, allow_unicode=True)


def _write_normalized(normalized_dir: str, doc: dict):
    os.makedirs(normalized_dir, exist_ok=True)
    fname = doc["module_id"].replace("::", "_").replace("/", "_") + ".json"
    with open(os.path.join(normalized_dir, fname), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def _write_kg(kg_dir: str, nodes: list, edges: list):
    os.makedirs(kg_dir, exist_ok=True)
    with open(os.path.join(kg_dir, "domain_model_nodes.json"), "w", encoding="utf-8") as f:
        json.dump(nodes, f)
    with open(os.path.join(kg_dir, "domain_model_edges.json"), "w", encoding="utf-8") as f:
        json.dump(edges, f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MODULE_ID = "mod_abc__deadbeef"
SAMPLE_CLASS_ID = f"{SAMPLE_MODULE_ID}::class::cls1"

SAMPLE_INDEX = {
    "generated_at": "2026-01-01T00:00:00+00:00",
    "source_root": "/tmp/xmi_src",
    "module_count": 1,
    "class_count": 2,
    "association_count": 1,
    "unresolved_ref_count": 0,
    "unresolved_refs": [],
    "modules": [
        {
            "module_id": SAMPLE_MODULE_ID,
            "module_id_raw": "mod_abc",
            "module_name": "TestModule",
            "source_file": "test.xml",
            "top_package_name": "TestPkg",
            "class_count": 2,
            "association_count": 1,
            "unresolved_ref_count": 0,
        }
    ],
    "class_index": {
        SAMPLE_CLASS_ID: {
            "class_id_raw": "cls1",
            "module_id": SAMPLE_MODULE_ID,
            "module_id_raw": "mod_abc",
            "module_name": "TestModule",
            "class_name": "ClassA",
            "package_path": ["TestPkg"],
            "source_file": "test.xml",
        }
    },
}

SAMPLE_NORMALIZED_DOC = {
    "module_id": SAMPLE_MODULE_ID,
    "module_id_raw": "mod_abc",
    "module_name": "TestModule",
    "source_file": "test.xml",
    "top_package_name": "TestPkg",
    "class_count": 1,
    "association_count": 1,
    "unresolved_ref_count": 0,
    "unresolved_refs": [],
    "classes": [
        {
            "class_id": SAMPLE_CLASS_ID,
            "class_id_raw": "cls1",
            "class_name": "ClassA",
            "class_raw_name": "ClassA",
            "package_path": ["TestPkg"],
            "source": "test.xml",
            "attributes": [
                {
                    "attribute_id": f"{SAMPLE_CLASS_ID}::attr::attr1",
                    "attribute_id_raw": "attr1",
                    "attribute_name": "name",
                    "attribute_type": "String",
                }
            ],
            "generalizations": [],
            "super_class_id": None,
            "super_class_id_raw": None,
        }
    ],
    "associations": [
        {
            "association_id": "assoc1",
            "association_name": "rel",
            "ends": [
                {"type_global_ref": SAMPLE_CLASS_ID, "type_ref": "cls1"},
                {"type_global_ref": "other_class", "type_ref": "cls2"},
            ],
        }
    ],
    "generalizations": [],
}

SAMPLE_KG_NODES = [
    {"id": SAMPLE_MODULE_ID, "type": "module", "name": "TestModule"},
    {"id": SAMPLE_CLASS_ID, "type": "class", "name": "ClassA", "module_id": SAMPLE_MODULE_ID},
]

SAMPLE_KG_EDGES = [
    {"source": SAMPLE_CLASS_ID, "target": SAMPLE_MODULE_ID, "type": "belongs_to_module"},
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestXmiStatus(unittest.IsolatedAsyncioTestCase):

    async def test_returns_compiled_false_when_no_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._INDEX_PATH",
                       os.path.join(tmpdir, "indexes", "xmi_global_index.yaml")), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_status
                req = _make_request()
                resp = await xmi_status(req)
                data = json.loads(resp.body)
                self.assertFalse(data["compiled"])

    async def test_returns_stats_when_index_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexes_dir = os.path.join(tmpdir, "indexes")
            _write_index(indexes_dir, SAMPLE_INDEX)
            idx_path = os.path.join(indexes_dir, "xmi_global_index.yaml")
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._INDEX_PATH", idx_path), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_status
                req = _make_request()
                resp = await xmi_status(req)
                data = json.loads(resp.body)
                self.assertTrue(data["compiled"])
                self.assertEqual(data["module_count"], 1)
                self.assertEqual(data["class_count"], 2)
                self.assertEqual(data["association_count"], 1)


class TestXmiModules(unittest.IsolatedAsyncioTestCase):

    async def test_returns_module_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexes_dir = os.path.join(tmpdir, "indexes")
            _write_index(indexes_dir, SAMPLE_INDEX)
            idx_path = os.path.join(indexes_dir, "xmi_global_index.yaml")
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._INDEX_PATH", idx_path), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_modules
                req = _make_request()
                resp = await xmi_modules(req)
                data = json.loads(resp.body)
                self.assertIn("modules", data)
                self.assertEqual(len(data["modules"]), 1)
                self.assertEqual(data["modules"][0]["module_id"], SAMPLE_MODULE_ID)

    async def test_returns_404_when_not_compiled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._INDEX_PATH",
                       os.path.join(tmpdir, "indexes", "xmi_global_index.yaml")), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_modules
                req = _make_request()
                resp = await xmi_modules(req)
                self.assertEqual(resp.status_code, 404)


class TestXmiClasses(unittest.IsolatedAsyncioTestCase):

    async def test_returns_class_list_for_valid_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            normalized_dir = os.path.join(tmpdir, "xmi_normalized")
            _write_normalized(normalized_dir, SAMPLE_NORMALIZED_DOC)
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_classes
                req = _make_request(query_params={"module_id": SAMPLE_MODULE_ID})
                resp = await xmi_classes(req)
                data = json.loads(resp.body)
                self.assertEqual(data["module_id"], SAMPLE_MODULE_ID)
                self.assertEqual(len(data["classes"]), 1)
                self.assertEqual(data["classes"][0]["class_name"], "ClassA")
                self.assertEqual(data["classes"][0]["attribute_count"], 1)

    async def test_returns_400_without_module_id(self):
        with patch("data_agent.api.domain_standard_routes._get_user_from_request",
                   return_value=_mock_user()):
            from data_agent.api.domain_standard_routes import xmi_classes
            req = _make_request(query_params={})
            resp = await xmi_classes(req)
            self.assertEqual(resp.status_code, 400)


class TestXmiClassDetail(unittest.IsolatedAsyncioTestCase):

    async def test_returns_class_with_attributes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexes_dir = os.path.join(tmpdir, "indexes")
            _write_index(indexes_dir, SAMPLE_INDEX)
            idx_path = os.path.join(indexes_dir, "xmi_global_index.yaml")
            normalized_dir = os.path.join(tmpdir, "xmi_normalized")
            _write_normalized(normalized_dir, SAMPLE_NORMALIZED_DOC)
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._INDEX_PATH", idx_path), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_class_detail
                req = _make_request(path_params={"class_id": SAMPLE_CLASS_ID})
                resp = await xmi_class_detail(req)
                data = json.loads(resp.body)
                self.assertEqual(data["class_id"], SAMPLE_CLASS_ID)
                self.assertEqual(data["class_name"], "ClassA")
                self.assertEqual(len(data["attributes"]), 1)
                self.assertIn("referencing_associations", data)

    async def test_returns_404_for_unknown_class(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexes_dir = os.path.join(tmpdir, "indexes")
            _write_index(indexes_dir, SAMPLE_INDEX)
            idx_path = os.path.join(indexes_dir, "xmi_global_index.yaml")
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._INDEX_PATH", idx_path), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_class_detail
                req = _make_request(path_params={"class_id": "nonexistent::class"})
                resp = await xmi_class_detail(req)
                self.assertEqual(resp.status_code, 404)


class TestXmiGraph(unittest.IsolatedAsyncioTestCase):

    async def test_returns_reactflow_nodes_and_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kg_dir = os.path.join(tmpdir, "kg")
            _write_kg(kg_dir, SAMPLE_KG_NODES, SAMPLE_KG_EDGES)
            with patch("data_agent.api.domain_standard_routes.COMPILED_DIR", tmpdir), \
                 patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()):
                from data_agent.api.domain_standard_routes import xmi_graph
                req = _make_request(query_params={"module_id": SAMPLE_MODULE_ID})
                resp = await xmi_graph(req)
                data = json.loads(resp.body)
                self.assertIn("nodes", data)
                self.assertIn("edges", data)
                # Module node + 1 class node
                self.assertEqual(len(data["nodes"]), 2)
                types = {n["type"] for n in data["nodes"]}
                self.assertIn("umlModule", types)
                self.assertIn("umlClass", types)

    async def test_returns_400_without_module_id(self):
        with patch("data_agent.api.domain_standard_routes._get_user_from_request",
                   return_value=_mock_user()):
            from data_agent.api.domain_standard_routes import xmi_graph
            req = _make_request(query_params={})
            resp = await xmi_graph(req)
            self.assertEqual(resp.status_code, 400)


class TestXmiCompile(unittest.IsolatedAsyncioTestCase):

    async def test_calls_compile_xmi_corpus(self):
        with tempfile.TemporaryDirectory() as src_dir:
            with patch("data_agent.api.domain_standard_routes._get_user_from_request",
                       return_value=_mock_user()), \
                 patch("data_agent.api.domain_standard_routes.COMPILED_DIR", "/tmp/compiled"), \
                 patch("data_agent.standards.xmi_compiler.compile_xmi_corpus",
                       return_value={"file_count": 0, "module_count": 0}) as mock_compile:
                from data_agent.api.domain_standard_routes import xmi_compile
                req = _make_request(body={"source_dir": src_dir})
                resp = await xmi_compile(req)
                data = json.loads(resp.body)
                self.assertIn("file_count", data)
                mock_compile.assert_called_once()

    async def test_returns_400_for_missing_source_dir(self):
        with patch("data_agent.api.domain_standard_routes._get_user_from_request",
                   return_value=_mock_user()):
            from data_agent.api.domain_standard_routes import xmi_compile
            req = _make_request(body={})
            resp = await xmi_compile(req)
            self.assertEqual(resp.status_code, 400)

    async def test_returns_400_for_nonexistent_source_dir(self):
        with patch("data_agent.api.domain_standard_routes._get_user_from_request",
                   return_value=_mock_user()):
            from data_agent.api.domain_standard_routes import xmi_compile
            req = _make_request(body={"source_dir": "/nonexistent/path/xyz"})
            resp = await xmi_compile(req)
            self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
