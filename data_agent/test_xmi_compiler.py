"""Tests for XMI corpus compiler."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from data_agent.standards.xmi_compiler import compile_xmi_corpus


FIXTURE_FILE = Path(__file__).with_name("test_data") / "xmi_parser_minimal_fixture.xml"


class TestXmiCompilerIntegration(unittest.TestCase):
    def test_compile_fixture_with_real_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "src"
            output_dir = Path(tmp) / "out"
            source_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURE_FILE, source_dir / FIXTURE_FILE.name)

            result = compile_xmi_corpus(source_dir, output_dir)

            self.assertEqual(result["file_count"], 1)
            self.assertEqual(result["module_count"], 1)
            self.assertEqual(result["class_count"], 4)
            self.assertEqual(result["association_count"], 2)

            normalized_files = list((output_dir / "xmi_normalized").glob("xmi_parser_minimal_fixture__*.json"))
            self.assertEqual(len(normalized_files), 1)
            normalized_file = normalized_files[0]
            global_index_file = output_dir / "indexes" / "xmi_global_index.yaml"
            aliases_file = output_dir / "indexes" / "module_aliases.yaml"
            nodes_file = output_dir / "kg" / "domain_model_nodes.json"
            edges_file = output_dir / "kg" / "domain_model_edges.json"

            self.assertTrue(normalized_file.exists())
            self.assertTrue(global_index_file.exists())
            self.assertTrue(aliases_file.exists())
            self.assertTrue(nodes_file.exists())
            self.assertTrue(edges_file.exists())

            normalized = json.loads(normalized_file.read_text(encoding="utf-8"))
            self.assertEqual(normalized["module_name"], "xmi_parser_minimal_fixture")
            self.assertEqual(normalized["module_id_raw"], "xmi_parser_minimal_fixture")
            self.assertTrue(normalized["module_id"].startswith("xmi_parser_minimal_fixture__"))
            self.assertEqual(normalized["top_package_name"], "Fixture模块")
            self.assertEqual(normalized["class_count"], 4)
            self.assertEqual(normalized["association_count"], 2)
            self.assertEqual(normalized["generalization_count"], 1)
            self.assertGreaterEqual(normalized["unresolved_ref_count"], 1)

            module_id = normalized["module_id"]
            class_by_id = {item["class_id"]: item for item in normalized["classes"]}
            class_a_id = f"{module_id}::class::CLASS_A"
            class_b_id = f"{module_id}::class::CLASS_B"
            class_c_id = f"{module_id}::class::CLASS_C"
            self.assertIn(class_a_id, class_by_id)
            self.assertIn(class_b_id, class_by_id)
            self.assertEqual(class_by_id[class_a_id]["class_id_raw"], "CLASS_A")
            self.assertEqual(class_by_id[class_a_id]["class_name"], "Base类")
            self.assertEqual(class_by_id[class_a_id]["package_path"], ["Fixture模块"])
            self.assertEqual(class_by_id[class_b_id]["class_name"], "Child类")
            self.assertEqual(class_by_id[class_b_id]["super_class_id"], class_a_id)
            self.assertEqual(class_by_id[class_b_id]["super_class_id_raw"], "CLASS_A")
            self.assertEqual(class_by_id[class_b_id]["super_class_ids"], [class_a_id])
            self.assertEqual(class_by_id[class_c_id]["attributes"][0]["attribute_name"], "parentRef")
            self.assertEqual(class_by_id[class_c_id]["attributes"][0]["attribute_type"], "Base类")
            self.assertEqual(class_by_id[class_c_id]["attributes"][0]["type_global_ref"], class_a_id)

            assoc_by_id = {item["association_id"]: item for item in normalized["associations"]}
            self.assertIn("ASSOC_1", assoc_by_id)
            self.assertIn("ASSOC_2", assoc_by_id)
            self.assertEqual(len(assoc_by_id["ASSOC_1"]["ends"]), 1)
            self.assertEqual(len(assoc_by_id["ASSOC_2"]["ends"]), 2)
            self.assertEqual(assoc_by_id["ASSOC_2"]["association_name"], "connectsTo")
            self.assertEqual(assoc_by_id["ASSOC_2"]["ends"][0]["type_ref"], "CLASS_A")
            self.assertEqual(assoc_by_id["ASSOC_2"]["ends"][0]["type_name"], "Base类")
            self.assertEqual(assoc_by_id["ASSOC_2"]["ends"][1]["type_ref"], "CLASS_C")
            self.assertEqual(assoc_by_id["ASSOC_2"]["ends"][1]["type_name"], "AttrTypeDirect")

            self.assertEqual(len(normalized["generalizations"]), 1)
            self.assertEqual(normalized["generalizations"][0]["source_class_id"], class_b_id)
            self.assertEqual(normalized["generalizations"][0]["source_class_id_raw"], "CLASS_B")
            self.assertEqual(normalized["generalizations"][0]["target_class_id"], class_a_id)
            self.assertEqual(normalized["generalizations"][0]["target_class_id_raw"], "CLASS_A")
            self.assertEqual(normalized["generalizations"][0]["target_class_name"], "Base类")

            global_index = yaml.safe_load(global_index_file.read_text(encoding="utf-8"))
            self.assertIn("generated_at", global_index)
            self.assertEqual(global_index["module_count"], 1)
            self.assertEqual(global_index["class_count"], 4)
            self.assertEqual(global_index["association_count"], 2)
            self.assertGreaterEqual(global_index["unresolved_ref_count"], 1)
            self.assertTrue(any(item["source_file"] == normalized["source_file"] for item in global_index["unresolved_refs"]))
            self.assertEqual(global_index["modules"][0]["module_id_raw"], "xmi_parser_minimal_fixture")
            self.assertIn(class_a_id, global_index["class_index"])
            self.assertEqual(global_index["class_index"][class_a_id]["class_id_raw"], "CLASS_A")
            self.assertEqual(global_index["class_index"][class_a_id]["class_name"], "Base类")
            self.assertEqual(global_index["class_index"][class_a_id]["package_path"], ["Fixture模块"])
            self.assertEqual(global_index["class_index"][class_a_id]["module_id_raw"], "xmi_parser_minimal_fixture")

            aliases = yaml.safe_load(aliases_file.read_text(encoding="utf-8"))
            all_pairs = {(x["left"], x["right"]) for x in aliases.get("mappings", [])}
            candidate_pairs = {(x["left"], x["right"]) for x in aliases.get("candidate_mappings", [])}
            self.assertIn(("统一规划", "统一空间规划"), all_pairs)
            self.assertIn(("执法督察", "督察执法"), all_pairs)
            self.assertIn(("开发利用", "统一资源利用"), all_pairs)
            self.assertIn(("底线安全", "统一灾害防治"), candidate_pairs)

            nodes = json.loads(nodes_file.read_text(encoding="utf-8"))
            edges = json.loads(edges_file.read_text(encoding="utf-8"))
            node_types = {n["type"] for n in nodes}
            edge_types = {e["type"] for e in edges}
            self.assertTrue({"module", "class", "attribute"}.issubset(node_types))
            self.assertTrue({"belongs_to_module", "has_attribute", "inherits_from", "associates_with"}.issubset(edge_types))

            module_node = next((n for n in nodes if n["type"] == "module" and n["id"] == module_id), None)
            self.assertIsNotNone(module_node)
            self.assertEqual(module_node["id_raw"], "xmi_parser_minimal_fixture")
            self.assertGreaterEqual(module_node["unresolved_ref_count"], 1)

            unresolved_edges = [e for e in edges if e["type"] == "has_unresolved_ref"]
            self.assertTrue(any(e["source"] == module_id for e in unresolved_edges))

            assoc_edge = next((e for e in edges if e["type"] == "associates_with" and e.get("association_id") == "ASSOC_2"), None)
            self.assertIsNotNone(assoc_edge)
            self.assertEqual(assoc_edge["source"], class_a_id)
            self.assertEqual(assoc_edge["target"], class_c_id)
            self.assertEqual(assoc_edge["source_class_id_raw"], "CLASS_A")
            self.assertEqual(assoc_edge["target_class_id_raw"], "CLASS_C")
            self.assertEqual(assoc_edge["association_name"], "connectsTo")

            inherit_edge = next((e for e in edges if e["type"] == "inherits_from" and e.get("generalization_id") == "GEN_1"), None)
            self.assertIsNotNone(inherit_edge)
            self.assertEqual(inherit_edge["source"], class_b_id)
            self.assertEqual(inherit_edge["target"], class_a_id)
            self.assertEqual(inherit_edge["source_class_id_raw"], "CLASS_B")
            self.assertEqual(inherit_edge["target_class_id_raw"], "CLASS_A")


class TestXmiCompilerPatchedDataclassCompatibility(unittest.TestCase):
    def _mock_parse_dataclass_like(self, _path: str):
        class FakeResult:
            def to_dict(self):
                return {
                    "module_id": "module-a",
                    "module_name": "统一空间规划",
                    "source_file": "module_a.xml",
                    "top_package_name": "planning.pkg",
                    "classes": [
                        {
                            "class_id": "cls-land",
                            "name": "LandParcel",
                            "name_decoded": "LandParcel",
                            "package_path": ["planning", "land"],
                            "attributes": [
                                {
                                    "attr_id": "attr-id",
                                    "name": "id",
                                    "name_decoded": "id",
                                    "type_ref": "EAJava_String",
                                    "type_name": "string",
                                }
                            ],
                            "generalizations": [],
                            "source": "module_a.xml",
                        },
                        {
                            "class_id": "cls-zoning",
                            "name": "ZoningUnit",
                            "name_decoded": "ZoningUnit",
                            "package_path": ["planning", "zone"],
                            "attributes": [],
                            "generalizations": [
                                {
                                    "generalization_id": "gen-1",
                                    "source_class_id": "cls-zoning",
                                    "target_class_id": "cls-land",
                                    "target_class_name": "LandParcel",
                                }
                            ],
                            "source": "module_a.xml",
                        },
                    ],
                    "associations": [
                        {
                            "association_id": "assoc-1",
                            "name": "landToZone",
                            "name_decoded": "landToZone",
                            "ends": [
                                {
                                    "end_id": "end-1",
                                    "type_ref": "cls-land",
                                    "type_name": "LandParcel",
                                },
                                {
                                    "end_id": "end-2",
                                    "type_ref": "cls-zoning",
                                    "type_name": "ZoningUnit",
                                },
                            ],
                            "source": "module_a.xml",
                        }
                    ],
                    "generalizations": [
                        {
                            "generalization_id": "gen-1",
                            "source_class_id": "cls-zoning",
                            "target_class_id": "cls-land",
                            "target_class_name": "LandParcel",
                        }
                    ],
                    "stats": {
                        "total_classes": 2,
                        "total_associations": 1,
                        "total_generalizations": 1,
                    },
                    "unresolved_refs": [],
                }

        return FakeResult()

    def test_compile_accepts_to_dict_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "src"
            output_dir = Path(tmp) / "out"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "module_a.xml").write_text("<xmi/>", encoding="utf-8")

            with patch(
                "data_agent.standards.xmi_compiler._parse_xmi_file",
                side_effect=self._mock_parse_dataclass_like,
            ):
                result = compile_xmi_corpus(source_dir, output_dir)

            self.assertEqual(result["file_count"], 1)
            self.assertEqual(result["class_count"], 2)
            self.assertEqual(result["association_count"], 1)

            normalized_files = list((output_dir / "xmi_normalized").glob("module_a__*.json"))
            self.assertEqual(len(normalized_files), 1)
            normalized = json.loads(normalized_files[0].read_text(encoding="utf-8"))
            module_id = normalized["module_id"]
            self.assertEqual(normalized["module_id_raw"], "module-a")
            self.assertTrue(module_id.startswith("module-a__"))
            self.assertEqual(normalized["classes"][0]["package_path"], ["planning", "land"])
            self.assertEqual(normalized["classes"][0]["class_id"], f"{module_id}::class::cls-land")
            self.assertEqual(normalized["classes"][0]["class_id_raw"], "cls-land")
            self.assertEqual(normalized["classes"][1]["super_class_id"], f"{module_id}::class::cls-land")
            self.assertEqual(normalized["classes"][1]["super_class_id_raw"], "cls-land")
            self.assertEqual(normalized["associations"][0]["ends"][0]["type_ref"], "cls-land")
            self.assertEqual(normalized["associations"][0]["ends"][0]["type_global_ref"], f"{module_id}::class::cls-land")


class TestXmiCompilerCorpusIdConflicts(unittest.TestCase):
    def _mock_parse_conflicting_ids(self, path: str):
        stem = Path(path).stem
        if stem == "module_one":
            return {
                "module_id": "module-shared",
                "module_name": "模块一",
                "source_file": path,
                "top_package_name": "pkg.one",
                "classes": [
                    {
                        "class_id": "CLASS_DUP",
                        "name": "Alpha",
                        "name_decoded": "Alpha",
                        "package_path": ["pkg", "one"],
                        "attributes": [
                            {
                                "attr_id": "ATTR_DUP",
                                "name": "name",
                                "name_decoded": "name",
                                "type_ref": "EAJava_String",
                                "type_name": "string",
                            }
                        ],
                        "generalizations": [],
                        "source": path,
                    },
                    {
                        "class_id": "BASE_DUP",
                        "name": "BaseOne",
                        "name_decoded": "BaseOne",
                        "package_path": ["pkg", "one"],
                        "attributes": [],
                        "generalizations": [],
                        "source": path,
                    },
                ],
                "associations": [
                    {
                        "association_id": "ASSOC_ONE",
                        "name": "assocOne",
                        "name_decoded": "assocOne",
                        "ends": [
                            {"end_id": "END1", "type_ref": "CLASS_DUP", "type_name": "Alpha"},
                            {"end_id": "END2", "type_ref": "BASE_DUP", "type_name": "BaseOne"},
                        ],
                        "source": path,
                    }
                ],
                "generalizations": [
                    {
                        "generalization_id": "GEN_ONE",
                        "source_class_id": "CLASS_DUP",
                        "target_class_id": "BASE_DUP",
                        "target_class_name": "BaseOne",
                    }
                ],
                "stats": {},
                "unresolved_refs": [],
            }

        return {
            "module_id": "module-shared",
            "module_name": "模块二",
            "source_file": path,
            "top_package_name": "pkg.two",
            "classes": [
                {
                    "class_id": "CLASS_DUP",
                    "name": "Beta",
                    "name_decoded": "Beta",
                    "package_path": ["pkg", "two"],
                    "attributes": [
                        {
                            "attr_id": "ATTR_DUP",
                            "name": "name",
                            "name_decoded": "name",
                            "type_ref": "EAJava_String",
                            "type_name": "string",
                        }
                    ],
                    "generalizations": [],
                    "source": path,
                },
                {
                    "class_id": "BASE_DUP",
                    "name": "BaseTwo",
                    "name_decoded": "BaseTwo",
                    "package_path": ["pkg", "two"],
                    "attributes": [],
                    "generalizations": [],
                    "source": path,
                },
            ],
            "associations": [
                {
                    "association_id": "ASSOC_TWO",
                    "name": "assocTwo",
                    "name_decoded": "assocTwo",
                    "ends": [
                        {"end_id": "END3", "type_ref": "CLASS_DUP", "type_name": "Beta"},
                        {"end_id": "END4", "type_ref": "BASE_DUP", "type_name": "BaseTwo"},
                    ],
                    "source": path,
                }
            ],
            "generalizations": [
                {
                    "generalization_id": "GEN_TWO",
                    "source_class_id": "CLASS_DUP",
                    "target_class_id": "BASE_DUP",
                    "target_class_name": "BaseTwo",
                }
            ],
            "stats": {},
            "unresolved_refs": [],
        }

    def test_multi_file_duplicate_raw_ids_do_not_collapse(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "src"
            output_dir = Path(tmp) / "out"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "module_one.xml").write_text("<xmi/>", encoding="utf-8")
            (source_dir / "module_two.xml").write_text("<xmi/>", encoding="utf-8")

            with patch(
                "data_agent.standards.xmi_compiler._parse_xmi_file",
                side_effect=self._mock_parse_conflicting_ids,
            ):
                result = compile_xmi_corpus(source_dir, output_dir)

            self.assertEqual(result["file_count"], 2)
            self.assertEqual(result["class_count"], 4)
            self.assertEqual(result["association_count"], 2)

            doc_one_file = next(iter((output_dir / "xmi_normalized").glob("module_one__*.json")))
            doc_two_file = next(iter((output_dir / "xmi_normalized").glob("module_two__*.json")))
            doc_one = json.loads(doc_one_file.read_text(encoding="utf-8"))
            doc_two = json.loads(doc_two_file.read_text(encoding="utf-8"))

            self.assertEqual(doc_one["module_id_raw"], "module-shared")
            self.assertEqual(doc_two["module_id_raw"], "module-shared")
            self.assertNotEqual(doc_one["module_id"], doc_two["module_id"])

            class_one_id = f"{doc_one['module_id']}::class::CLASS_DUP"
            class_two_id = f"{doc_two['module_id']}::class::CLASS_DUP"
            base_one_id = f"{doc_one['module_id']}::class::BASE_DUP"
            base_two_id = f"{doc_two['module_id']}::class::BASE_DUP"

            global_index = yaml.safe_load((output_dir / "indexes" / "xmi_global_index.yaml").read_text(encoding="utf-8"))
            self.assertIn(class_one_id, global_index["class_index"])
            self.assertIn(class_two_id, global_index["class_index"])
            self.assertNotEqual(class_one_id, class_two_id)
            self.assertEqual(global_index["class_index"][class_one_id]["class_id_raw"], "CLASS_DUP")
            self.assertEqual(global_index["class_index"][class_two_id]["class_id_raw"], "CLASS_DUP")
            self.assertEqual(global_index["class_index"][class_one_id]["module_id_raw"], "module-shared")
            self.assertEqual(global_index["class_index"][class_two_id]["module_id_raw"], "module-shared")
            self.assertEqual(global_index["class_index"][class_one_id]["class_name"], "Alpha")
            self.assertEqual(global_index["class_index"][class_two_id]["class_name"], "Beta")

            nodes = json.loads((output_dir / "kg" / "domain_model_nodes.json").read_text(encoding="utf-8"))
            edges = json.loads((output_dir / "kg" / "domain_model_edges.json").read_text(encoding="utf-8"))

            class_nodes = {node["id"]: node for node in nodes if node["type"] == "class"}
            self.assertIn(class_one_id, class_nodes)
            self.assertIn(class_two_id, class_nodes)
            self.assertEqual(class_nodes[class_one_id]["id_raw"], "CLASS_DUP")
            self.assertEqual(class_nodes[class_two_id]["id_raw"], "CLASS_DUP")

            module_nodes = {node["id"]: node for node in nodes if node["type"] == "module"}
            self.assertIn(doc_one["module_id"], module_nodes)
            self.assertIn(doc_two["module_id"], module_nodes)
            self.assertEqual(module_nodes[doc_one["module_id"]]["id_raw"], "module-shared")
            self.assertEqual(module_nodes[doc_two["module_id"]]["id_raw"], "module-shared")

            attr_nodes = {node["id"]: node for node in nodes if node["type"] == "attribute"}
            self.assertIn(f"{class_one_id}::attr::ATTR_DUP", attr_nodes)
            self.assertIn(f"{class_two_id}::attr::ATTR_DUP", attr_nodes)

            inherit_edges = [e for e in edges if e["type"] == "inherits_from"]
            self.assertTrue(any(e["source"] == class_one_id and e["target"] == base_one_id for e in inherit_edges))
            self.assertTrue(any(e["source"] == class_two_id and e["target"] == base_two_id for e in inherit_edges))

            assoc_edges = [e for e in edges if e["type"] == "associates_with"]
            self.assertTrue(any(e["source"] == class_one_id and e["target"] == base_one_id for e in assoc_edges))
            self.assertTrue(any(e["source"] == class_two_id and e["target"] == base_two_id for e in assoc_edges))


class TestXmiCompilerFallbackIdUniqueness(unittest.TestCase):
    def _mock_parse_same_name_without_ids(self, path: str):
        return {
            "module_id": "module-fallback",
            "module_name": "同名回退模块",
            "source_file": path,
            "top_package_name": "pkg.fallback",
            "classes": [
                {
                    "name": "DuplicateName",
                    "name_decoded": "DuplicateName",
                    "package_path": ["pkg", "fallback"],
                    "attributes": [
                        {
                            "name": "dup_attr",
                            "name_decoded": "dup_attr",
                            "type_ref": "EAJava_String",
                            "type_name": "string",
                        },
                        {
                            "name": "dup_attr",
                            "name_decoded": "dup_attr",
                            "type_ref": "EAJava_String",
                            "type_name": "string",
                        },
                    ],
                    "generalizations": [],
                    "source": path,
                },
                {
                    "name": "DuplicateName",
                    "name_decoded": "DuplicateName",
                    "package_path": ["pkg", "fallback"],
                    "attributes": [],
                    "generalizations": [],
                    "source": path,
                },
            ],
            "associations": [],
            "generalizations": [],
            "stats": {},
            "unresolved_refs": [],
        }

    def test_fallback_raw_ids_are_unique_within_same_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "src"
            output_dir = Path(tmp) / "out"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "same_name.xml").write_text("<xmi/>", encoding="utf-8")

            with patch(
                "data_agent.standards.xmi_compiler._parse_xmi_file",
                side_effect=self._mock_parse_same_name_without_ids,
            ):
                result = compile_xmi_corpus(source_dir, output_dir)

            self.assertEqual(result["file_count"], 1)
            self.assertEqual(result["class_count"], 2)
            self.assertEqual(result["association_count"], 0)

            normalized_files = list((output_dir / "xmi_normalized").glob("same_name__*.json"))
            self.assertEqual(len(normalized_files), 1)
            normalized = json.loads(normalized_files[0].read_text(encoding="utf-8"))

            classes = normalized["classes"]
            self.assertEqual(len(classes), 2)
            self.assertNotEqual(classes[0]["class_id_raw"], classes[1]["class_id_raw"])
            self.assertNotEqual(classes[0]["class_id"], classes[1]["class_id"])
            self.assertTrue(classes[0]["class_id_raw"].endswith("::0"))
            self.assertTrue(classes[1]["class_id_raw"].endswith("::1"))

            attrs = classes[0]["attributes"]
            self.assertEqual(len(attrs), 2)
            self.assertNotEqual(attrs[0]["attribute_id_raw"], attrs[1]["attribute_id_raw"])
            self.assertNotEqual(attrs[0]["attribute_id"], attrs[1]["attribute_id"])
            self.assertTrue(attrs[0]["attribute_id_raw"].endswith("::0"))
            self.assertTrue(attrs[1]["attribute_id_raw"].endswith("::1"))

            global_index = yaml.safe_load((output_dir / "indexes" / "xmi_global_index.yaml").read_text(encoding="utf-8"))
            self.assertEqual(len(global_index["class_index"]), 2)

            nodes = json.loads((output_dir / "kg" / "domain_model_nodes.json").read_text(encoding="utf-8"))
            class_nodes = [node for node in nodes if node["type"] == "class"]
            attr_nodes = [node for node in nodes if node["type"] == "attribute"]
            self.assertEqual(len(class_nodes), 2)
            self.assertEqual(len(attr_nodes), 2)
            self.assertEqual(len({node["id"] for node in class_nodes}), 2)
            self.assertEqual(len({node["id"] for node in attr_nodes}), 2)


    def test_association_and_generalization_fallback_ids_are_unique(self):
        def mock_parse(path: str):
            return {
                "module_id": "module-rel-fallback",
                "module_name": "RelFallback",
                "source_file": path,
                "top_package_name": "pkg.rel",
                "classes": [
                    {
                        "class_id": "CLS_A",
                        "name": "A",
                        "name_decoded": "A",
                        "package_path": ["pkg", "rel"],
                        "attributes": [],
                        "generalizations": [],
                        "source": path,
                    },
                    {
                        "class_id": "CLS_B",
                        "name": "B",
                        "name_decoded": "B",
                        "package_path": ["pkg", "rel"],
                        "attributes": [],
                        "generalizations": [],
                        "source": path,
                    },
                ],
                "associations": [
                    {
                        "name": "relates",
                        "name_decoded": "relates",
                        "ends": [
                            {"end_id": "END_1", "type_ref": "CLS_A", "type_name": "A"},
                            {"end_id": "END_2", "type_ref": "CLS_B", "type_name": "B"},
                        ],
                        "source": path,
                    },
                    {
                        "name": "relates",
                        "name_decoded": "relates",
                        "ends": [
                            {"end_id": "END_3", "type_ref": "CLS_A", "type_name": "A"},
                            {"end_id": "END_4", "type_ref": "CLS_B", "type_name": "B"},
                        ],
                        "source": path,
                    },
                ],
                "generalizations": [
                    {
                        "source_class_id": "CLS_B",
                        "target_class_id": "CLS_A",
                        "target_class_name": "A",
                    },
                    {
                        "source_class_id": "CLS_B",
                        "target_class_id": "CLS_A",
                        "target_class_name": "A",
                    },
                ],
                "stats": {},
                "unresolved_refs": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "src"
            output_dir = Path(tmp) / "out"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "fallback_rel.xml").write_text("<xmi/>", encoding="utf-8")

            with patch("data_agent.standards.xmi_compiler._parse_xmi_file", side_effect=mock_parse):
                compile_xmi_corpus(source_dir, output_dir)

            normalized_file = next(iter((output_dir / "xmi_normalized").glob("fallback_rel__*.json")))
            normalized = json.loads(normalized_file.read_text(encoding="utf-8"))

            assoc_ids = [item["association_id"] for item in normalized["associations"]]
            self.assertEqual(len(assoc_ids), 2)
            self.assertEqual(len(set(assoc_ids)), 2)
            self.assertTrue(assoc_ids[0].endswith("::0"))
            self.assertTrue(assoc_ids[1].endswith("::1"))

            gen_ids = [item["generalization_id"] for item in normalized["generalizations"]]
            self.assertEqual(len(gen_ids), 2)
            self.assertEqual(len(set(gen_ids)), 2)
            self.assertTrue(gen_ids[0].endswith("::0"))
            self.assertTrue(gen_ids[1].endswith("::1"))

            edges = json.loads((output_dir / "kg" / "domain_model_edges.json").read_text(encoding="utf-8"))
            inherit_gen_ids = [e["generalization_id"] for e in edges if e["type"] == "inherits_from"]
            self.assertEqual(set(inherit_gen_ids), set(gen_ids))

    def test_duplicate_basenames_do_not_overwrite_normalized_outputs(self):
        def mock_parse(path: str):
            source = Path(path).as_posix()
            return {
                "module_id": f"module::{source}",
                "module_name": Path(path).parent.name,
                "source_file": source,
                "top_package_name": Path(path).parent.name,
                "classes": [],
                "associations": [],
                "generalizations": [],
                "stats": {},
                "unresolved_refs": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "src"
            output_dir = Path(tmp) / "out"
            (source_dir / "dir1").mkdir(parents=True, exist_ok=True)
            (source_dir / "dir2").mkdir(parents=True, exist_ok=True)
            (source_dir / "dir1" / "shared.xml").write_text("<xmi/>", encoding="utf-8")
            (source_dir / "dir2" / "shared.xml").write_text("<xmi/>", encoding="utf-8")

            with patch("data_agent.standards.xmi_compiler._parse_xmi_file", side_effect=mock_parse):
                result = compile_xmi_corpus(source_dir, output_dir, source_glob="**/*.xml")

            self.assertEqual(result["file_count"], 2)
            self.assertEqual(result["module_count"], 2)

            normalized_files = sorted((output_dir / "xmi_normalized").glob("shared__*.json"))
            self.assertEqual(len(normalized_files), 2)
            self.assertNotEqual(normalized_files[0].name, normalized_files[1].name)

            docs = [json.loads(path.read_text(encoding="utf-8")) for path in normalized_files]
            source_files = {doc["source_file"] for doc in docs}
            self.assertEqual(source_files, {"dir1/shared.xml", "dir2/shared.xml"})
            self.assertTrue(all(not Path(src).is_absolute() for src in source_files))

            global_index = yaml.safe_load((output_dir / "indexes" / "xmi_global_index.yaml").read_text(encoding="utf-8"))
            index_sources = {module["source_file"] for module in global_index["modules"]}
            self.assertEqual(index_sources, {"dir1/shared.xml", "dir2/shared.xml"})

            nodes = json.loads((output_dir / "kg" / "domain_model_nodes.json").read_text(encoding="utf-8"))
            module_sources = {node["source_file"] for node in nodes if node["type"] == "module"}
            self.assertEqual(module_sources, {"dir1/shared.xml", "dir2/shared.xml"})

    def test_missing_parser_source_file_falls_back_to_relative_path(self):
        def mock_parse(_path: str):
            return {
                "module_id": "module-no-source",
                "module_name": "NoSource",
                "top_package_name": "pkg.nosource",
                "classes": [],
                "associations": [],
                "generalizations": [],
                "stats": {},
                "unresolved_refs": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "src"
            output_dir = Path(tmp) / "out"
            (source_dir / "nested").mkdir(parents=True, exist_ok=True)
            (source_dir / "nested" / "nosource.xml").write_text("<xmi/>", encoding="utf-8")

            with patch("data_agent.standards.xmi_compiler._parse_xmi_file", side_effect=mock_parse):
                compile_xmi_corpus(source_dir, output_dir, source_glob="**/*.xml")

            normalized_file = next(iter((output_dir / "xmi_normalized").glob("nosource__*.json")))
            normalized = json.loads(normalized_file.read_text(encoding="utf-8"))
            self.assertEqual(normalized["source_file"], "nested/nosource.xml")

            global_index = yaml.safe_load((output_dir / "indexes" / "xmi_global_index.yaml").read_text(encoding="utf-8"))
            self.assertEqual(global_index["modules"][0]["source_file"], "nested/nosource.xml")
