"""Tests for D-5: AI-assisted Skill creation."""
import json
import pytest
from unittest.mock import patch, MagicMock

from data_agent.skill_generator import (
    generate_skill_config,
    _recommend_toolsets,
    _detect_category,
    _detect_model_tier,
    _generate_skill_name,
    _generate_trigger_keywords,
    _generate_instruction,
)


# ---------------------------------------------------------------------------
# Toolset recommendation
# ---------------------------------------------------------------------------

class TestRecommendToolsets:
    def test_vegetation_analysis(self):
        recs = _recommend_toolsets("分析农田植被覆盖变化")
        names = {r["name"] for r in recs}
        assert "RemoteSensingToolset" in names

    def test_spatial_processing(self):
        recs = _recommend_toolsets("缓冲区分析和空间叠加")
        names = {r["name"] for r in recs}
        assert "GeoProcessingToolset" in names

    def test_visualization(self):
        recs = _recommend_toolsets("生成热力图可视化")
        names = {r["name"] for r in recs}
        assert "VisualizationToolset" in names

    def test_database(self):
        recs = _recommend_toolsets("导入数据到 PostGIS 数据库")
        names = {r["name"] for r in recs}
        assert "DatabaseToolset" in names

    def test_always_includes_exploration(self):
        recs = _recommend_toolsets("some unrelated task")
        names = {r["name"] for r in recs}
        assert "ExplorationToolset" in names

    def test_max_6_toolsets(self):
        recs = _recommend_toolsets("遥感 空间 数据库 可视化 统计 融合 因果 预测")
        assert len(recs) <= 6

    def test_reasons_included(self):
        recs = _recommend_toolsets("遥感影像处理")
        for r in recs:
            assert "reasons" in r
            assert isinstance(r["reasons"], list)


# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

class TestDetectCategory:
    def test_spatial_analysis(self):
        assert _detect_category("空间缓冲区分析") == "spatial_analysis"

    def test_remote_sensing(self):
        assert _detect_category("遥感影像 NDVI 计算") == "remote_sensing"

    def test_data_management(self):
        assert _detect_category("数据清洗和质检") == "data_management"

    def test_advanced_analysis(self):
        assert _detect_category("因果推断分析") == "advanced_analysis"

    def test_visualization(self):
        assert _detect_category("地图可视化") == "visualization"

    def test_default_other(self):
        assert _detect_category("completely unrelated xyz") == "other"


# ---------------------------------------------------------------------------
# Model tier detection
# ---------------------------------------------------------------------------

class TestDetectModelTier:
    def test_premium_complex(self):
        assert _detect_model_tier("复杂的多步推理和规划") == "premium"

    def test_premium_causal(self):
        assert _detect_model_tier("因果推断分析") == "premium"

    def test_fast_simple(self):
        assert _detect_model_tier("简单查询列出数据") == "fast"

    def test_standard_default(self):
        assert _detect_model_tier("常规空间分析") == "standard"


# ---------------------------------------------------------------------------
# Skill name generation
# ---------------------------------------------------------------------------

class TestGenerateSkillName:
    def test_english_keywords(self):
        name = _generate_skill_name("vegetation monitoring analysis")
        assert "vegetation" in name
        assert "_" in name

    def test_chinese_mapping(self):
        name = _generate_skill_name("植被监测分析")
        assert "vegetation" in name or "monitor" in name or "analyze" in name

    def test_fallback(self):
        name = _generate_skill_name("xyz")
        assert name == "custom_skill"

    def test_snake_case(self):
        name = _generate_skill_name("Urban Heat Island Analysis")
        assert name.islower()
        assert "_" in name


# ---------------------------------------------------------------------------
# Trigger keywords generation
# ---------------------------------------------------------------------------

class TestGenerateTriggerKeywords:
    def test_extracts_chinese_terms(self):
        kw = _generate_trigger_keywords("城市热岛效应分析", "urban_heat_island")
        assert any(len(k) >= 2 and '\u4e00' <= k[0] <= '\u9fff' for k in kw)

    def test_includes_skill_name_parts(self):
        kw = _generate_trigger_keywords("test description", "urban_heat")
        assert "urban" in kw or "heat" in kw

    def test_max_6_keywords(self):
        kw = _generate_trigger_keywords("植被 监测 分析 评估 预测 优化 统计", "veg_monitor")
        assert len(kw) <= 6

    def test_deduplicates(self):
        kw = _generate_trigger_keywords("分析分析分析", "analyze")
        assert kw.count("分析") <= 1


# ---------------------------------------------------------------------------
# Instruction generation
# ---------------------------------------------------------------------------

class TestGenerateInstruction:
    def test_includes_description(self):
        inst = _generate_instruction("植被监测", ["RemoteSensingToolset"], "remote_sensing")
        assert "植被监测" in inst

    def test_includes_toolsets(self):
        inst = _generate_instruction("test", ["RemoteSensingToolset", "VisualizationToolset"], "other")
        assert "RemoteSensingToolset" in inst
        assert "VisualizationToolset" in inst

    def test_structured_format(self):
        inst = _generate_instruction("test", ["ExplorationToolset"], "other")
        assert "核心职责" in inst
        assert "工作流程" in inst
        assert "输出格式" in inst
        assert "注意事项" in inst


# ---------------------------------------------------------------------------
# Full config generation
# ---------------------------------------------------------------------------

class TestGenerateSkillConfig:
    def test_short_description_error(self):
        result = generate_skill_config("abc")
        assert result["status"] == "error"

    def test_vegetation_analysis_full(self):
        result = generate_skill_config("分析农田植被覆盖变化，使用遥感影像计算 NDVI")
        assert result["status"] == "success"
        config = result["config"]
        assert "skill_name" in config
        assert "RemoteSensingToolset" in config["toolset_names"]
        assert config["category"] == "remote_sensing"
        assert len(config["trigger_keywords"]) > 0

    def test_urban_heat_island(self):
        result = generate_skill_config("城市热岛效应分析，融合遥感地表温度与气象站点数据")
        assert result["status"] == "success"
        config = result["config"]
        assert "RemoteSensingToolset" in config["toolset_names"]
        assert "FusionToolset" in config["toolset_names"]

    def test_spatial_buffer(self):
        result = generate_skill_config("创建缓冲区并进行空间叠加分析")
        assert result["status"] == "success"
        config = result["config"]
        assert "GeoProcessingToolset" in config["toolset_names"]
        assert config["category"] == "spatial_analysis"

    def test_quality_check(self):
        result = generate_skill_config("数据质检和清洗")
        assert result["status"] == "success"
        config = result["config"]
        toolsets = set(config["toolset_names"])
        assert "GovernanceToolset" in toolsets or "DataCleaningToolset" in toolsets

    def test_returns_preview(self):
        result = generate_skill_config("test analysis task")
        assert "preview" in result
        assert "skill_name" in result["preview"]
        assert "model_tier" in result["preview"]

    def test_returns_toolset_recommendations(self):
        result = generate_skill_config("remote sensing analysis")
        assert "toolset_recommendations" in result
        assert len(result["toolset_recommendations"]) > 0
        for rec in result["toolset_recommendations"]:
            assert "name" in rec
            assert "reasons" in rec

    def test_model_tier_premium_for_complex(self):
        result = generate_skill_config("复杂的多步推理和因果分析")
        assert result["config"]["model_tier"] == "premium"

    def test_model_tier_fast_for_simple(self):
        result = generate_skill_config("简单查询数据")
        assert result["config"]["model_tier"] == "fast"


# ---------------------------------------------------------------------------
# API endpoint (mocked)
# ---------------------------------------------------------------------------

class TestSkillsGenerateEndpoint:
    def test_endpoint_requires_auth(self):
        """Test that endpoint requires authentication."""
        from data_agent.api.skills_routes import skills_generate
        from starlette.requests import Request
        import asyncio

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"",
            "path": "/api/skills/generate",
        }
        request = Request(scope)
        response = asyncio.get_event_loop().run_until_complete(skills_generate(request))
        assert response.status_code == 401

    def test_endpoint_requires_description(self):
        """Test that endpoint requires description field."""
        from data_agent.api.skills_routes import skills_generate
        from starlette.requests import Request
        import asyncio

        mock_user = MagicMock()
        mock_user.identifier = "test_user"
        mock_user.metadata = {"role": "analyst"}

        with patch("data_agent.api.skills_routes._get_user_from_request", return_value=mock_user):
            with patch("data_agent.api.skills_routes._set_user_context", return_value=("test_user", "analyst")):
                scope = {
                    "type": "http",
                    "method": "POST",
                    "headers": [],
                    "query_string": b"",
                    "path": "/api/skills/generate",
                }
                request = Request(scope)
                request._body = b'{}'
                response = asyncio.get_event_loop().run_until_complete(skills_generate(request))
                assert response.status_code == 400


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestSkillCreatorSkill:
    def test_skill_file_exists(self):
        import os
        skill_path = "data_agent/skills/skill-creator/SKILL.md"
        assert os.path.exists(skill_path)

    def test_skill_has_frontmatter(self):
        with open("data_agent/skills/skill-creator/SKILL.md", encoding="utf-8") as f:
            content = f.read()
        assert "---" in content
        assert "name: skill-creator" in content
        assert "trigger_keywords" in content
