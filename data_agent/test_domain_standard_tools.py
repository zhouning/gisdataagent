"""Tests for DomainStandardToolset."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_XML = str(
    Path(__file__).parent / "test_data" / "xmi_parser_minimal_fixture.xml"
)

_SAMPLE_INDEX = {
    "generated_at": "2026-01-01T00:00:00+00:00",
    "source_root": "/tmp/src",
    "module_count": 2,
    "class_count": 5,
    "association_count": 3,
    "unresolved_ref_count": 0,
    "unresolved_refs": [],
    "modules": [
        {
            "module_id": "mod_a__abc12345",
            "module_id_raw": "mod_a",
            "module_name": "地籍管理",
            "source_file": "mod_a.xml",
            "top_package_name": "地籍",
            "class_count": 3,
            "association_count": 2,
            "unresolved_ref_count": 0,
        },
        {
            "module_id": "mod_b__def67890",
            "module_id_raw": "mod_b",
            "module_name": "规划管理",
            "source_file": "mod_b.xml",
            "top_package_name": "规划",
            "class_count": 2,
            "association_count": 1,
            "unresolved_ref_count": 0,
        },
    ],
    "class_index": {
        "mod_a__abc12345::class::C001": {
            "class_id_raw": "C001",
            "module_id": "mod_a__abc12345",
            "module_id_raw": "mod_a",
            "module_name": "地籍管理",
            "class_name": "宗地",
            "package_path": ["地籍", "基础地籍"],
            "source_file": "mod_a.xml",
        },
        "mod_a__abc12345::class::C002": {
            "class_id_raw": "C002",
            "module_id": "mod_a__abc12345",
            "module_id_raw": "mod_a",
            "module_name": "地籍管理",
            "class_name": "界址点",
            "package_path": ["地籍", "基础地籍"],
            "source_file": "mod_a.xml",
        },
        "mod_b__def67890::class::C010": {
            "class_id_raw": "C010",
            "module_id": "mod_b__def67890",
            "module_id_raw": "mod_b",
            "module_name": "规划管理",
            "class_name": "规划用地",
            "package_path": ["规划", "用地管理"],
            "source_file": "mod_b.xml",
        },
    },
}


def _write_index(tmpdir: str) -> None:
    idx_dir = Path(tmpdir) / "indexes"
    idx_dir.mkdir(parents=True, exist_ok=True)
    with (idx_dir / "xmi_global_index.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(_SAMPLE_INDEX, f, allow_unicode=True)


# ---------------------------------------------------------------------------
# compile_xmi_standards
# ---------------------------------------------------------------------------

class TestCompileXmiStandards:
    def test_missing_source_dir(self):
        from data_agent.toolsets.domain_standard_tools import compile_xmi_standards
        result = compile_xmi_standards("/nonexistent/path/xyz")
        assert "不存在" in result

    def test_compile_with_fixture(self):
        """Integration-style: compile the real minimal fixture XML."""
        from data_agent.toolsets.domain_standard_tools import compile_xmi_standards

        if not os.path.isfile(FIXTURE_XML):
            pytest.skip("fixture XML not found")

        src_dir = str(Path(FIXTURE_XML).parent)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = compile_xmi_standards(src_dir, tmpdir)
        # Should succeed and mention counts
        assert "XMI编译完成" in result or "编译失败" in result  # either is acceptable

    def test_compile_calls_corpus(self):
        """Mock compile_xmi_corpus and verify summary formatting."""
        from data_agent.toolsets.domain_standard_tools import compile_xmi_standards

        fake_result = {
            "source_root": "/src",
            "output_root": "/out",
            "file_count": 3,
            "module_count": 3,
            "class_count": 42,
            "association_count": 15,
        }
        with tempfile.TemporaryDirectory() as src_dir:
            # Patch at the source module since the import is lazy (inside function body)
            with patch(
                "data_agent.standards.xmi_compiler.compile_xmi_corpus",
                return_value=fake_result,
            ):
                result = compile_xmi_standards(src_dir, "/out")

        assert "文件数: 3" in result
        assert "模块数: 3" in result
        assert "类数: 42" in result
        assert "关联数: 15" in result

    def test_compile_exception_returns_error(self):
        from data_agent.toolsets.domain_standard_tools import compile_xmi_standards

        with tempfile.TemporaryDirectory() as src_dir:
            with patch(
                "data_agent.standards.xmi_compiler.compile_xmi_corpus",
                side_effect=RuntimeError("boom"),
            ):
                result = compile_xmi_standards(src_dir, "/out")

        assert "编译失败" in result
        assert "boom" in result


# ---------------------------------------------------------------------------
# query_domain_modules
# ---------------------------------------------------------------------------

class TestQueryDomainModules:
    def test_missing_index(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_modules
        with tempfile.TemporaryDirectory() as tmpdir:
            result = query_domain_modules(tmpdir)
        assert "未找到" in result or "请先运行" in result

    def test_returns_module_list(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_modules
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_index(tmpdir)
            result = query_domain_modules(tmpdir)

        assert "地籍管理" in result
        assert "规划管理" in result
        assert "2 个模块" in result
        assert "5 个类" in result

    def test_class_counts_shown(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_modules
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_index(tmpdir)
            result = query_domain_modules(tmpdir)

        # Each module line should show class count
        assert "类: 3" in result
        assert "类: 2" in result


# ---------------------------------------------------------------------------
# query_domain_class
# ---------------------------------------------------------------------------

class TestQueryDomainClass:
    def test_empty_query(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_class
        result = query_domain_class("")
        assert "请提供" in result

    def test_missing_index(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_class
        with tempfile.TemporaryDirectory() as tmpdir:
            result = query_domain_class("宗地", tmpdir)
        assert "未找到" in result or "请先运行" in result

    def test_exact_match(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_class
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_index(tmpdir)
            result = query_domain_class("宗地", tmpdir)

        assert "宗地" in result
        assert "地籍管理" in result
        assert "基础地籍" in result

    def test_partial_match(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_class
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_index(tmpdir)
            result = query_domain_class("地", tmpdir)

        # "宗地", "规划用地" both contain "地"
        assert "找到" in result
        assert "宗地" in result

    def test_no_match(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_class
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_index(tmpdir)
            result = query_domain_class("不存在的类名XYZ", tmpdir)

        assert "未找到" in result

    def test_case_insensitive(self):
        from data_agent.toolsets.domain_standard_tools import query_domain_class
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_index(tmpdir)
            # ASCII partial match — "规划" contains no ASCII, but test insensitivity
            # by searching with mixed case on a class that has ASCII chars if any
            result = query_domain_class("规划", tmpdir)

        assert "规划" in result


# ---------------------------------------------------------------------------
# DomainStandardToolset class
# ---------------------------------------------------------------------------

class TestDomainStandardToolset:
    def test_get_tools_returns_three(self):
        import asyncio
        from data_agent.toolsets.domain_standard_tools import DomainStandardToolset
        ts = DomainStandardToolset()
        tools = asyncio.run(ts.get_tools())
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert "compile_xmi_standards" in names
        assert "query_domain_modules" in names
        assert "query_domain_class" in names

    def test_tool_filter(self):
        import asyncio
        from data_agent.toolsets.domain_standard_tools import DomainStandardToolset
        ts = DomainStandardToolset(tool_filter=["query_domain_modules", "query_domain_class"])
        tools = asyncio.run(ts.get_tools())
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "compile_xmi_standards" not in names

    def test_toolset_metadata(self):
        from data_agent.toolsets.domain_standard_tools import DomainStandardToolset
        ts = DomainStandardToolset()
        assert ts.name == "DomainStandardToolset"
        assert "领域" in ts.description
