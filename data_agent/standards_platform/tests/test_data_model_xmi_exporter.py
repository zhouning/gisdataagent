"""Pure-function tests for EA-compatible XMI export from PDM snapshots."""
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from data_agent.standards.xmi_parser import parse_xmi_file
from data_agent.standards_platform.derivation.data_model_xmi_exporter import (
    export_pdm_to_ea_xmi,
)


def _pdm() -> dict:
    return {
        "layer": "PDM",
        "dialect": "postgresql",
        "entities": [
            {
                "physical_table": "cq_dltb",
                "name_zh": "土地利用图斑",
                "name_en": "land_parcel",
                "attributes": [
                    {
                        "physical_column": "DLBM",
                        "name_zh": "地类编码",
                        "physical_type": "VARCHAR(64)",
                        "nullable": False,
                        "is_geometry": False,
                        "constraints": ['CHECK ("DLBM" IN (\'01\'))'],
                    },
                    {
                        "physical_column": "MJ",
                        "name_zh": "面积",
                        "physical_type": "NUMERIC(18,4)",
                        "nullable": True,
                        "is_geometry": False,
                        "constraints": [],
                    },
                    {
                        "physical_column": "geometry",
                        "name_zh": "几何图形",
                        "physical_type": "GEOMETRY(POLYGON, 4490)",
                        "nullable": False,
                        "is_geometry": True,
                        "constraints": [],
                    },
                ],
            },
            {
                "physical_table": "std_region",
                "name_zh": "行政区",
                "name_en": "region",
                "attributes": [
                    {
                        "physical_column": "enabled",
                        "name_zh": "是否启用",
                        "physical_type": "BOOLEAN",
                        "nullable": True,
                        "is_geometry": False,
                        "constraints": [],
                    }
                ],
            },
        ],
    }


def test_export_pdm_to_ea_xmi_emits_minimal_uml_document():
    xml = export_pdm_to_ea_xmi(
        _pdm(),
        model_name="Standards Platform Data Model",
        package_name="自然资源数据模型",
    )

    root = ET.fromstring(xml)
    assert root.tag.endswith("XMI")
    assert "uml:Model" in xml
    assert "自然资源数据模型" in xml
    assert "土地利用图斑" in xml
    assert "地类编码" in xml

    class_count = xml.count('xmi:type="uml:Class"')
    attr_count = xml.count('xmi:type="uml:Property"')
    assert class_count == 2
    assert attr_count == 4


def test_export_pdm_to_ea_xmi_is_deterministic():
    first = export_pdm_to_ea_xmi(_pdm(), package_name="自然资源数据模型")
    second = export_pdm_to_ea_xmi(_pdm(), package_name="自然资源数据模型")

    assert first == second
    assert "CLASS_" in first
    assert "ATTR_" in first


def test_export_pdm_to_ea_xmi_emits_stable_multiplicity_ids_and_types():
    xml = export_pdm_to_ea_xmi(_pdm(), package_name="鑷劧璧勬簮鏁版嵁妯″瀷")
    root = ET.fromstring(xml)
    xmi_id = "{http://www.omg.org/spec/XMI/20131001}id"
    xmi_type = "{http://www.omg.org/spec/XMI/20131001}type"

    attributes = root.findall(".//ownedAttribute")

    assert attributes
    for attribute in attributes:
        lower = attribute.find("lowerValue")
        upper = attribute.find("upperValue")
        assert lower is not None
        assert upper is not None
        assert lower.attrib[xmi_type] == "uml:LiteralInteger"
        assert upper.attrib[xmi_type] == "uml:LiteralUnlimitedNatural"
        assert lower.attrib[xmi_id].startswith("LOWER_")
        assert upper.attrib[xmi_id].startswith("UPPER_")


def test_export_pdm_to_ea_xmi_round_trips_through_existing_parser(tmp_path: Path):
    xml = export_pdm_to_ea_xmi(_pdm(), package_name="自然资源数据模型")
    target = tmp_path / "exported_model.xml"
    target.write_text(xml, encoding="utf-8")

    parsed = parse_xmi_file(target)

    assert parsed.top_package_name == "自然资源数据模型"
    assert parsed.stats.total_classes == 2
    assert parsed.stats.total_attributes == 4
    class_by_name = {c.name_decoded: c for c in parsed.classes}
    assert "土地利用图斑" in class_by_name

    attrs = {a.name_decoded: a for a in class_by_name["土地利用图斑"].attributes}
    assert attrs["地类编码"].lower == "1"
    assert attrs["地类编码"].upper == "1"
    assert attrs["地类编码"].type_name == "string"
    assert attrs["面积"].lower == "0"
    assert attrs["面积"].upper == "1"
    assert attrs["面积"].type_name == "numeric"
    assert attrs["几何图形"].type_name == "string"


def test_export_pdm_to_ea_xmi_emits_xml_declaration_and_trailing_newline():
    xml = export_pdm_to_ea_xmi(_pdm(), package_name="自然资源数据模型")

    assert xml.startswith("<?xml version='1.0' encoding='utf-8'?>") or xml.startswith(
        '<?xml version="1.0" encoding="utf-8"?>'
    )
    assert xml.endswith("\n")


def test_export_pdm_to_ea_xmi_preserves_ids_for_reordered_entities_and_attributes(tmp_path: Path):
    pdm = _pdm()
    parcel_name = pdm["entities"][0]["name_zh"]
    region_name = pdm["entities"][1]["name_zh"]
    reordered = {
        **pdm,
        "entities": [
            {
                **pdm["entities"][1],
                "attributes": list(reversed(pdm["entities"][1]["attributes"])),
            },
            {
                **pdm["entities"][0],
                "attributes": list(reversed(pdm["entities"][0]["attributes"])),
            },
        ],
    }

    original = export_pdm_to_ea_xmi(pdm, package_name="自然资源数据模型")
    shuffled = export_pdm_to_ea_xmi(reordered, package_name="自然资源数据模型")

    original_path = tmp_path / "original.xml"
    shuffled_path = tmp_path / "shuffled.xml"
    original_path.write_text(original, encoding="utf-8")
    shuffled_path.write_text(shuffled, encoding="utf-8")

    original_parsed = parse_xmi_file(original_path)
    shuffled_parsed = parse_xmi_file(shuffled_path)

    original_classes = {c.name_decoded: c for c in original_parsed.classes}
    shuffled_classes = {c.name_decoded: c for c in shuffled_parsed.classes}

    assert original_classes[parcel_name].class_id == shuffled_classes[parcel_name].class_id
    assert original_classes[region_name].class_id == shuffled_classes[region_name].class_id

    original_attrs = {a.name_decoded: a.attr_id for a in original_classes[parcel_name].attributes}
    shuffled_attrs = {a.name_decoded: a.attr_id for a in shuffled_classes[parcel_name].attributes}
    assert original_attrs == shuffled_attrs


def test_export_pdm_to_ea_xmi_uses_model_name_as_package_fallback(tmp_path: Path):
    xml = export_pdm_to_ea_xmi(_pdm(), model_name="Model Fallback")
    target = tmp_path / "fallback.xml"
    target.write_text(xml, encoding="utf-8")

    parsed = parse_xmi_file(target)
    assert parsed.top_package_name == "Model Fallback"
    assert "Model Fallback" in xml


def test_export_pdm_to_ea_xmi_maps_exact_int_to_integer(tmp_path: Path):
    pdm = {
        "layer": "PDM",
        "dialect": "postgresql",
        "entities": [
            {
                "physical_table": "int_table",
                "name_zh": "整数表",
                "attributes": [
                    {
                        "physical_column": "int_col",
                        "name_zh": "整数列",
                        "physical_type": "INT",
                        "nullable": False,
                        "is_geometry": False,
                        "constraints": [],
                    }
                ],
            }
        ],
    }

    xml = export_pdm_to_ea_xmi(pdm, package_name="整数模型")
    target = tmp_path / "int_model.xml"
    target.write_text(xml, encoding="utf-8")

    parsed = parse_xmi_file(target)
    attr = parsed.classes[0].attributes[0]

    assert attr.type_name == "integer"


def test_export_pdm_to_ea_xmi_maps_geometry_type_string_to_string(tmp_path: Path):
    pdm = {
        "layer": "PDM",
        "dialect": "postgresql",
        "entities": [
            {
                "physical_table": "geom_table",
                "name_zh": "几何表",
                "attributes": [
                    {
                        "physical_column": "geom_col",
                        "name_zh": "几何列",
                        "physical_type": "GEOMETRY(POINT, 4490)",
                        "nullable": False,
                        "constraints": [],
                    }
                ],
            }
        ],
    }

    xml = export_pdm_to_ea_xmi(pdm, package_name="几何模型")
    target = tmp_path / "geometry_model.xml"
    target.write_text(xml, encoding="utf-8")

    parsed = parse_xmi_file(target)
    attr = parsed.classes[0].attributes[0]

    assert attr.type_name == "string"
