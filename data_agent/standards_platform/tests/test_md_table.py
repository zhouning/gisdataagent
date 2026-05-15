"""Unit tests for the markdown table parser."""
from __future__ import annotations

import pytest
from data_agent.standards_platform.drafting.md_table import parse_md_table


def test_parse_empty_returns_empty_list():
    assert parse_md_table("") == []
    assert parse_md_table("just some prose, no table") == []


def test_parse_basic_table():
    md = (
        "模块: water\n\n"
        "| 序号 | 字段代码 | 字段名称 | 类型 | 长度 | 值域 | 必选 | 备注 |\n"
        "|------|----------|----------|------|------|------|------|------|\n"
        "| 1 | XZQDM | 行政区代码 | char | 12 | GB/T 2260 | M | - |\n"
        "| 2 | XZQMC | 行政区名称 | varchar | 50 |  | C |  |\n"
    )
    rows = parse_md_table(md)
    assert len(rows) == 2
    assert rows[0]["code"] == "XZQDM"
    assert rows[0]["name_zh"] == "行政区代码"
    assert rows[0]["datatype"] == "char(12)"
    assert rows[0]["obligation"] == "mandatory"
    assert rows[1]["code"] == "XZQMC"
    assert rows[1]["datatype"] == "varchar(50)"
    assert rows[1]["obligation"] == "conditional"
    assert rows[1]["definition"] == ""


def test_parse_decimal_length():
    md = (
        "| 字段代码 | 字段名称 | 类型 | 长度 |\n"
        "|----------|----------|------|------|\n"
        "| AREA | 面积 | decimal | 10,2 |\n"
    )
    rows = parse_md_table(md)
    assert rows[0]["datatype"] == "decimal(10,2)"


def test_parse_missing_required_code_column_raises():
    md = (
        "| 序号 | 字段名称 |\n"
        "|------|----------|\n"
        "| 1 | foo |\n"
    )
    with pytest.raises(ValueError, match="字段代码"):
        parse_md_table(md)


def test_parse_skips_blank_code_rows():
    md = (
        "| 字段代码 | 字段名称 |\n"
        "|----------|----------|\n"
        "| FOO | name |\n"
        "|  | (blank code) |\n"
        "| BAR | other |\n"
    )
    rows = parse_md_table(md)
    codes = [r["code"] for r in rows]
    assert codes == ["FOO", "BAR"]
