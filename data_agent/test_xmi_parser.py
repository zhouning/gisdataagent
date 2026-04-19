"""Tests for Enterprise Architect XMI parser."""

import unittest
from pathlib import Path

from data_agent.standards.xmi_parser import (
    decode_html_entities,
    is_unknown_eajava_primitive,
    normalize_primitive_type,
    parse_xmi_file,
)


FIXTURE_FILE = Path(__file__).with_name("test_data") / "xmi_parser_minimal_fixture.xml"
XMI_FILE = Path("D:/adk/数据标准/自然资源全域数据模型/01统一地理底图.xml")


class TestXMIParserFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = parse_xmi_file(FIXTURE_FILE)

    def test_fixture_module_and_package(self):
        self.assertEqual(self.result.module_name, "xmi_parser_minimal_fixture")
        self.assertEqual(self.result.top_package_name, "Fixture模块")
        self.assertEqual(self.result.source_file, str(FIXTURE_FILE))

    def test_fixture_parses_model_level_class(self):
        class_by_name = {c.name_decoded: c for c in self.result.classes}
        self.assertIn("ModelLevelEntity", class_by_name)
        self.assertEqual(class_by_name["ModelLevelEntity"].package_path, [])

    def test_fixture_generalization(self):
        class_name_by_id = {c.class_id: c.name_decoded for c in self.result.classes}
        generalization = next((g for g in self.result.generalizations if g.generalization_id == "GEN_1"), None)
        self.assertIsNotNone(generalization)
        self.assertEqual(class_name_by_id.get(generalization.source_class_id), "Child类")
        self.assertEqual(generalization.target_class_name, "Base类")

    def test_fixture_type_ref_direct_attribute_form(self):
        class_c = next((c for c in self.result.classes if c.name_decoded == "AttrTypeDirect"), None)
        self.assertIsNotNone(class_c)
        attr = next((a for a in class_c.attributes if a.attr_id == "ATTR_C1"), None)
        self.assertIsNotNone(attr)
        self.assertEqual(attr.type_ref, "CLASS_A")
        self.assertEqual(attr.type_name, "Base类")

    def test_fixture_member_end_attribute_form(self):
        target_assoc = next((a for a in self.result.associations if a.association_id == "ASSOC_2"), None)
        self.assertIsNotNone(target_assoc)
        self.assertEqual(len(target_assoc.ends), 2)

        end_by_id = {end.end_id: end for end in target_assoc.ends}
        self.assertEqual(set(end_by_id), {"ASSOC2_END_A", "ASSOC2_END_C"})
        self.assertEqual(end_by_id["ASSOC2_END_A"].type_ref, "CLASS_A")
        self.assertEqual(end_by_id["ASSOC2_END_A"].type_name, "Base类")
        self.assertEqual(end_by_id["ASSOC2_END_C"].type_ref, "CLASS_C")
        self.assertEqual(end_by_id["ASSOC2_END_C"].type_name, "AttrTypeDirect")

        unresolved_contexts = {(item["context"], item["owner_id"]) for item in self.result.unresolved_refs}
        self.assertNotIn(("association_incomplete", "ASSOC_2"), unresolved_contexts)

    def test_fixture_association_end_not_in_attributes(self):
        child_class = next((c for c in self.result.classes if c.name_decoded == "Child类"), None)
        self.assertIsNotNone(child_class)
        attr_ids = {attr.attr_id for attr in child_class.attributes}
        self.assertNotIn("ASSOC_END_CLASS_B", attr_ids)

    def test_fixture_unknown_eajava_primitive_records_unresolved(self):
        model_class = next((c for c in self.result.classes if c.name_decoded == "ModelLevelEntity"), None)
        self.assertIsNotNone(model_class)
        attr = next((a for a in model_class.attributes if a.attr_id == "MODEL_ATTR_1"), None)
        self.assertIsNotNone(attr)
        self.assertEqual(attr.type_ref, "EAJava_uuid")
        self.assertTrue(is_unknown_eajava_primitive(attr.type_ref, attr.type_name))

        unresolved_contexts = {(item["context"], item["ref_id"], item["owner_id"]) for item in self.result.unresolved_refs}
        self.assertIn(("unknown_primitive_type", "EAJava_uuid", "MODEL_LEVEL_CLASS"), unresolved_contexts)

    def test_primitive_type_helpers(self):
        self.assertEqual(normalize_primitive_type("EAJava_double"), "numeric")
        self.assertEqual(normalize_primitive_type("EAJava_String"), "string")
        self.assertEqual(normalize_primitive_type("EAJava_boolean"), "boolean")
        self.assertEqual(normalize_primitive_type("EAJava_long"), "integer")
        self.assertTrue(is_unknown_eajava_primitive("EAJava_uuid"))
        self.assertFalse(is_unknown_eajava_primitive("EAJava_int"))

    def test_chinese_entity_decoded(self):
        class_names = {c.name_decoded for c in self.result.classes}
        self.assertIn("Base类", class_names)
        self.assertIn("Child类", class_names)
        self.assertEqual(decode_html_entities("Fixture&#27169;&#22359;"), "Fixture模块")


class TestXMIParserIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not XMI_FILE.exists():
            raise unittest.SkipTest(f"XMI sample file not found: {XMI_FILE}")
        cls.result = parse_xmi_file(XMI_FILE)

    def test_module_inference_not_use_ea_model(self):
        self.assertNotEqual(self.result.module_name, "EA_Model")
        self.assertEqual(self.result.module_name, "01统一地理底图")
        self.assertEqual(self.result.top_package_name, "01统一地理底图")
        self.assertEqual(self.result.source_file, str(XMI_FILE))

    def test_parse_classes(self):
        self.assertGreater(len(self.result.classes), 20)
        self.assertGreater(self.result.stats.total_classes, 20)

    def test_real_generalization_resolves_class_name(self):
        generalization = next(
            (g for g in self.result.generalizations if g.source_class_id and g.target_class_id and g.target_class_name),
            None,
        )
        self.assertIsNotNone(generalization)

        class_name_by_id = {c.class_id: c.name_decoded for c in self.result.classes}
        source_name = class_name_by_id.get(generalization.source_class_id)
        self.assertIn("三维模型", {source_name, generalization.target_class_name})

    def test_real_association_has_precise_known_structure(self):
        target_assoc = next(
            (
                assoc for assoc in self.result.associations
                if assoc.association_id == "EAID_B659F71D_552E_46cc_8E1A_ADF9E7F89E8B"
            ),
            None,
        )
        self.assertIsNotNone(target_assoc)
        self.assertEqual(len(target_assoc.ends), 2)

        end_by_id = {end.end_id: end for end in target_assoc.ends}
        self.assertEqual(
            set(end_by_id),
            {
                "EAID_dst59F71D_552E_46cc_8E1A_ADF9E7F89E8B",
                "EAID_src59F71D_552E_46cc_8E1A_ADF9E7F89E8B",
            },
        )

        self.assertEqual(end_by_id["EAID_dst59F71D_552E_46cc_8E1A_ADF9E7F89E8B"].type_name, "地图")
        self.assertEqual(end_by_id["EAID_dst59F71D_552E_46cc_8E1A_ADF9E7F89E8B"].owner_class_name, "地理场景")
        self.assertEqual(end_by_id["EAID_src59F71D_552E_46cc_8E1A_ADF9E7F89E8B"].type_name, "地理场景")
        self.assertIsNone(end_by_id["EAID_src59F71D_552E_46cc_8E1A_ADF9E7F89E8B"].owner_class_name)

    def test_association_end_not_mixed_into_class_attributes(self):
        target_class = next((c for c in self.result.classes if c.name_decoded == "地理场景"), None)
        self.assertIsNotNone(target_class)

        attr_ids = {attr.attr_id for attr in target_class.attributes}
        attr_names = {attr.name_decoded for attr in target_class.attributes}
        self.assertNotIn("EAID_dst59F71D_552E_46cc_8E1A_ADF9E7F89E8B", attr_ids)
        self.assertNotIn("", attr_names)

        target_assoc = next(
            (
                assoc for assoc in self.result.associations
                if assoc.association_id == "EAID_B659F71D_552E_46cc_8E1A_ADF9E7F89E8B"
            ),
            None,
        )
        self.assertIsNotNone(target_assoc)
        end_ids = {end.end_id for end in target_assoc.ends}
        self.assertIn("EAID_dst59F71D_552E_46cc_8E1A_ADF9E7F89E8B", end_ids)

    def test_primitive_type_normalization(self):
        target_class = next((c for c in self.result.classes if c.name_decoded == "基础地理实体"), None)
        self.assertIsNotNone(target_class)

        attr = next((a for a in target_class.attributes if a.name_decoded == "产生时间"), None)
        self.assertIsNotNone(attr)
        self.assertEqual(attr.type_ref, "EAJava_int")
        self.assertEqual(attr.type_name, "integer")


if __name__ == "__main__":
    unittest.main()
