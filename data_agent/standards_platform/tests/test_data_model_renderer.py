"""Pure-function tests for data_model_renderer — no DB.

Each test hands the renderer dicts shaped like the strategy will populate
them, and asserts against return values.
"""
from __future__ import annotations

import re

import pytest

from data_agent.standards_platform.derivation.data_model_renderer import (
    DEFAULT_CODE_LENGTH,
    DEFAULT_GEOMETRY_SRID,
    build_model,
    render_cdm,
    render_ddl,
    render_ldm,
    render_pdm,
)


def _el(*, code, repr_class="text", obligation="optional",
        bound_table="cq_dltb", bound_column="dlbm",
        name_zh="测试列", name_en=None, datatype=None, unit=None,
        value_domain_id=None, term_id=None, definition=None) -> dict:
    return {
        "id": f"el-{code}",
        "code": code,
        "name_zh": name_zh,
        "name_en": name_en,
        "definition": definition,
        "representation_class": repr_class,
        "datatype": datatype,
        "unit": unit,
        "value_domain_id": value_domain_id,
        "obligation": obligation,
        "bound_table": bound_table,
        "bound_column": bound_column,
        "term_id": term_id,
    }


# ---------------------------------------------------------------- build_model


def test_build_model_groups_by_table():
    elements = [
        _el(code="A", bound_table="t1", bound_column="c1"),
        _el(code="B", bound_table="t1", bound_column="c2"),
        _el(code="C", bound_table="t2", bound_column="c1"),
    ]
    m = build_model(elements=elements, value_domains={})
    tables = [e["physical_table"] for e in m["entities"]]
    assert tables == ["t1", "t2"]  # sorted
    assert len(m["entities"][0]["attributes"]) == 2


def test_build_model_skips_unbound_with_warning():
    m = build_model(elements=[
        _el(code="A", bound_table=None, bound_column=None),
        _el(code="B", bound_table="t1", bound_column="c1"),
    ], value_domains={})
    assert len(m["entities"]) == 1
    assert any("skipped" in w for w in m["warnings"])


def test_build_model_dedups_columns_with_warning():
    m = build_model(elements=[
        _el(code="A", bound_table="t1", bound_column="c1"),
        _el(code="B", bound_table="t1", bound_column="c1"),  # dup
    ], value_domains={})
    attrs = m["entities"][0]["attributes"]
    assert len(attrs) == 1
    assert any("multiple data_element definitions" in w
               for w in m["warnings"])


def test_build_model_uses_term_for_entity_name():
    m = build_model(
        elements=[_el(code="A", bound_table="cq_dltb", bound_column="c",
                      term_id="T1")],
        value_domains={},
        terms={"T1": {"name_zh": "土地利用图斑", "name_en": "land_parcel"}},
    )
    assert m["entities"][0]["name_zh"] == "土地利用图斑"
    assert m["entities"][0]["name_en"] == "land_parcel"


def test_build_model_falls_back_to_humanised_table_name():
    m = build_model(
        elements=[_el(code="A", bound_table="land_use_dltb",
                      bound_column="c")],
        value_domains={},
    )
    assert m["entities"][0]["name_zh"] == "Land Use Dltb"


# ---------------------------------------------------------------- physical types


def test_pdm_code_with_enumeration_check():
    items = [{"value": "01", "label_zh": "水田", "ordinal": 0},
             {"value": "02", "label_zh": "旱地", "ordinal": 1}]
    m = build_model(
        elements=[_el(code="DLBM", repr_class="code",
                      bound_column="DLBM",
                      value_domain_id="d1")],
        value_domains={"d1": {"kind": "enumeration", "code": "DLBM_ENUM",
                              "name": "地类编码", "items": items}},
    )
    a = m["entities"][0]["attributes"][0]
    assert a["physical_type"] == f"VARCHAR({DEFAULT_CODE_LENGTH})"
    assert any('"DLBM" IN (\'01\', \'02\')' in c for c in a["constraints"])


def test_pdm_pattern_emits_regex_check():
    items = [{"value": "^[A-Z][0-9]{4}$", "ordinal": 0}]
    m = build_model(
        elements=[_el(code="C", repr_class="code", bound_column="bsm",
                      value_domain_id="d1")],
        value_domains={"d1": {"kind": "pattern", "code": "BSM_REGEX",
                              "name": "标识码", "items": items}},
    )
    a = m["entities"][0]["attributes"][0]
    assert any('~' in c and '[A-Z]' in c for c in a["constraints"])


def test_pdm_range_with_min_max_emits_between_check():
    items = [{"value": "0", "label_zh": "min", "ordinal": 0},
             {"value": "100", "label_zh": "max", "ordinal": 1}]
    m = build_model(
        elements=[_el(code="C", repr_class="integer", bound_column="floor",
                      value_domain_id="d1")],
        value_domains={"d1": {"kind": "range", "code": "FLOOR_RANGE",
                              "name": "层数", "items": items}},
    )
    a = m["entities"][0]["attributes"][0]
    assert a["physical_type"] == "BIGINT"
    assert any("BETWEEN 0 AND 100" in c for c in a["constraints"])


def test_pdm_geometry_with_unit_srid_override():
    m = build_model(
        elements=[_el(code="GEOM", repr_class="geometry",
                      bound_column="geometry", unit="POLYGON@4490")],
        value_domains={},
    )
    a = m["entities"][0]["attributes"][0]
    assert a["physical_type"] == "GEOMETRY(POLYGON, 4490)"
    assert a["is_geometry"] is True


def test_pdm_geometry_default_srid_when_no_unit():
    m = build_model(
        elements=[_el(code="GEOM", repr_class="geometry",
                      bound_column="geometry")],
        value_domains={},
    )
    a = m["entities"][0]["attributes"][0]
    assert f", {DEFAULT_GEOMETRY_SRID}" in a["physical_type"]


def test_pdm_mandatory_marks_not_nullable():
    m = build_model(
        elements=[_el(code="A", obligation="mandatory", bound_column="c1"),
                  _el(code="B", obligation="optional", bound_column="c2"),
                  _el(code="C", obligation="conditional", bound_column="c3")],
        value_domains={},
    )
    attrs = {a["physical_column"]: a
             for a in m["entities"][0]["attributes"]}
    assert attrs["c1"]["nullable"] is False
    assert attrs["c2"]["nullable"] is True
    assert attrs["c3"]["nullable"] is True


# ---------------------------------------------------------------- DDL


def test_render_ddl_includes_create_table_quotes_and_constraints():
    items = [{"value": "01", "label_zh": "水田", "ordinal": 0}]
    m = build_model(
        elements=[
            _el(code="DLBM", repr_class="code", obligation="mandatory",
                bound_table="cq_dltb", bound_column="DLBM",
                name_zh="地类编码", value_domain_id="d1"),
            _el(code="GEOM", repr_class="geometry",
                bound_table="cq_dltb", bound_column="geometry",
                name_zh="几何图形"),
        ],
        value_domains={"d1": {"kind": "enumeration", "code": "DLBM_ENUM",
                              "name": "地类编码", "items": items}},
    )
    ddl = render_ddl(m)

    # Both columns rendered.
    assert 'CREATE TABLE IF NOT EXISTS "cq_dltb"' in ddl
    assert '"DLBM" VARCHAR(64) NOT NULL CHECK' in ddl
    assert "GEOMETRY(" in ddl
    # COMMENT ON
    assert "COMMENT ON COLUMN \"cq_dltb\".\"DLBM\" IS '地类编码';" in ddl
    assert "COMMENT ON TABLE \"cq_dltb\" IS '" in ddl
    # GIST index for geometry column
    assert "USING GIST (\"geometry\")" in ddl


def test_render_ddl_dialect_validation():
    m = build_model(
        elements=[_el(code="A", bound_column="c1")],
        value_domains={},
    )
    with pytest.raises(ValueError):
        render_ddl(m, dialect="oracle")


def test_render_layers_have_distinct_shapes():
    m = build_model(
        elements=[_el(code="A", repr_class="text", bound_column="c1",
                      obligation="mandatory")],
        value_domains={},
    )
    cdm = render_cdm(m)
    ldm = render_ldm(m)
    pdm = render_pdm(m)

    assert cdm["layer"] == "CDM"
    assert ldm["layer"] == "LDM"
    assert pdm["layer"] == "PDM"

    # CDM hides logical_type
    assert "logical_type" not in cdm["entities"][0]["attributes"][0]
    # LDM shows logical_type but no physical_type
    ldm_attr = ldm["entities"][0]["attributes"][0]
    assert "logical_type" in ldm_attr
    assert "physical_type" not in ldm_attr
    # PDM has physical_type
    assert "physical_type" in pdm["entities"][0]["attributes"][0]


def test_stats_count_constraints():
    items = [{"value": "01", "ordinal": 0}]
    m = build_model(
        elements=[
            _el(code="A", repr_class="code", obligation="mandatory",
                bound_column="c1", value_domain_id="d1"),
        ],
        value_domains={"d1": {"kind": "enumeration", "items": items}},
    )
    # Constraints: NOT NULL + CHECK = 2
    assert m["stats"]["constraint_count"] == 2
    assert m["stats"]["entity_count"] == 1
    assert m["stats"]["attribute_count"] == 1


def test_render_ddl_skips_empty_entity_block():
    """Defensive: no attributes → no CREATE TABLE for that entity."""
    m = {"entities": [{"physical_table": "empty", "name_zh": "空",
                       "name_en": "empty", "attributes": []}],
         "warnings": [], "stats": {"entity_count": 1, "attribute_count": 0,
                                   "constraint_count": 0}}
    ddl = render_ddl(m)
    assert "CREATE TABLE" not in ddl
