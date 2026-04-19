"""Tests for XmiDomainStandardProvider and StandardRegistry.list_xmi_modules."""
import os
import tempfile

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_INDEX = {
    "modules": [
        {
            "module_id": "mod_001",
            "module_name": "LandParcel",
            "class_count": 3,
            "source_file": "land.xmi",
        },
        {
            "module_id": "mod_002",
            "module_name": "WaterBody",
            "class_count": 2,
            "source_file": "water.xmi",
        },
    ],
    "class_index": {
        "Parcel": {"class_name": "Parcel", "module_name": "LandParcel", "module_id": "mod_001"},
        "WaterPolygon": {"class_name": "WaterPolygon", "module_name": "WaterBody", "module_id": "mod_002"},
    },
}


def _write_index(base_dir: str, data: dict) -> None:
    indexes_dir = os.path.join(base_dir, "indexes")
    os.makedirs(indexes_dir, exist_ok=True)
    with open(os.path.join(indexes_dir, "xmi_global_index.yaml"), "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)


# ---------------------------------------------------------------------------
# XmiDomainStandardProvider tests
# ---------------------------------------------------------------------------

class TestXmiDomainStandardProvider:
    def _make_provider(self, compiled_dir: str):
        from data_agent.context_engine import XmiDomainStandardProvider
        return XmiDomainStandardProvider(compiled_dir=compiled_dir)

    def test_returns_empty_when_compiled_dir_missing(self, tmp_path):
        provider = self._make_provider(str(tmp_path / "nonexistent"))
        result = provider.get_context("Parcel land", "governance", {})
        assert result == []

    def test_returns_context_block_on_match(self, tmp_path):
        _write_index(str(tmp_path), _MINIMAL_INDEX)
        provider = self._make_provider(str(tmp_path))
        result = provider.get_context("Parcel land", "governance", {})
        assert len(result) == 1
        block = result[0]
        assert block.provider == "xmi_domain_standard"
        assert block.source == "xmi_global_index"
        assert "Parcel" in block.content or "LandParcel" in block.content
        assert 0.0 < block.relevance_score <= 1.0
        assert block.token_count > 0

    def test_returns_empty_when_no_match(self, tmp_path):
        _write_index(str(tmp_path), _MINIMAL_INDEX)
        provider = self._make_provider(str(tmp_path))
        result = provider.get_context("zzznomatch", "general", {})
        assert result == []

    def test_supports_task_types(self):
        from data_agent.context_engine import XmiDomainStandardProvider
        p = XmiDomainStandardProvider()
        assert "governance" in p.supports_task_types
        assert "general" in p.supports_task_types
        assert "optimization" in p.supports_task_types

    def test_graceful_on_corrupt_index(self, tmp_path):
        indexes_dir = os.path.join(str(tmp_path), "indexes")
        os.makedirs(indexes_dir, exist_ok=True)
        with open(os.path.join(indexes_dir, "xmi_global_index.yaml"), "w") as f:
            f.write(": invalid: yaml: [[[")
        provider = self._make_provider(str(tmp_path))
        result = provider.get_context("Parcel", "governance", {})
        assert result == []

    def test_module_name_match(self, tmp_path):
        _write_index(str(tmp_path), _MINIMAL_INDEX)
        provider = self._make_provider(str(tmp_path))
        # "Water" should match module_name "WaterBody"
        result = provider.get_context("Water analysis", "general", {})
        assert len(result) == 1
        assert "Water" in result[0].content


# ---------------------------------------------------------------------------
# StandardRegistry.list_xmi_modules tests
# ---------------------------------------------------------------------------

class TestStandardRegistryListXmiModules:
    def test_returns_module_list(self, tmp_path):
        _write_index(str(tmp_path), _MINIMAL_INDEX)
        from data_agent.standard_registry import StandardRegistry
        modules = StandardRegistry.list_xmi_modules(compiled_dir=str(tmp_path))
        assert len(modules) == 2
        names = {m["module_name"] for m in modules}
        assert "LandParcel" in names
        assert "WaterBody" in names
        for m in modules:
            assert "module_id" in m
            assert "class_count" in m
            assert "source_file" in m

    def test_returns_empty_when_dir_missing(self, tmp_path):
        from data_agent.standard_registry import StandardRegistry
        modules = StandardRegistry.list_xmi_modules(compiled_dir=str(tmp_path / "nonexistent"))
        assert modules == []

    def test_returns_empty_on_empty_index(self, tmp_path):
        _write_index(str(tmp_path), {})
        from data_agent.standard_registry import StandardRegistry
        modules = StandardRegistry.list_xmi_modules(compiled_dir=str(tmp_path))
        assert modules == []

    def test_class_count_preserved(self, tmp_path):
        _write_index(str(tmp_path), _MINIMAL_INDEX)
        from data_agent.standard_registry import StandardRegistry
        modules = StandardRegistry.list_xmi_modules(compiled_dir=str(tmp_path))
        land = next(m for m in modules if m["module_name"] == "LandParcel")
        assert land["class_count"] == 3
        assert land["source_file"] == "land.xmi"
