# -*- coding: utf-8 -*-
"""Tests for should_decompose() in intent_router.py."""
import pytest
from data_agent.intent_router import should_decompose


class TestShouldDecompose:
    """Test multi-step query detection heuristic."""

    def test_short_text_returns_false(self):
        assert not should_decompose("分析数据")

    def test_single_step_returns_false(self):
        assert not should_decompose("请帮我分析一下这个区域的土地利用情况，生成一张地图")

    def test_single_marker_returns_false(self):
        assert not should_decompose("首先分析一下这个数据集的质量问题和分布情况")

    def test_chinese_multi_step_markers(self):
        text = "首先加载上海市行政区划数据，然后计算各区的耕地面积，最后生成统计图表"
        assert should_decompose(text)

    def test_english_multi_step_markers(self):
        text = "First load the shapefile, then run buffer analysis, and finally generate a heatmap"
        assert should_decompose(text)

    def test_numbered_list_dot(self):
        text = "1. 加载上海市数据 2. 分析土地利用 3. 生成报告"
        assert should_decompose(text)

    def test_numbered_list_chinese_comma(self):
        text = "1、加载上海市数据 2、分析土地利用 3、生成报告"
        assert should_decompose(text)

    def test_multiline_numbered_list(self):
        text = """请按以下步骤执行：
1. 加载上海市数据
2. 分析土地利用变化
3. 生成可视化报告"""
        assert should_decompose(text)

    def test_english_numbered_list(self):
        text = "1. Load the data 2. Run spatial join 3. Generate heatmap"
        assert should_decompose(text)

    def test_empty_string(self):
        assert not should_decompose("")

    def test_mixed_markers(self):
        text = "首先加载数据, then 分析一下, finally 出图"
        assert should_decompose(text)

    def test_two_chinese_markers(self):
        text = "先进行缓冲区分析，然后做一个热力图，接着统计面积"
        assert should_decompose(text)
