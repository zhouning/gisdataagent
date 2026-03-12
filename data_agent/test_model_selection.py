"""
Tests for Resource-Aware Dynamic Model Selection.

Covers: assess_complexity tiers, MODEL_TIER_MAP, get_model_for_tier,
current_model_tier ContextVar.
"""
import unittest
from unittest.mock import patch


class TestAssessComplexity(unittest.TestCase):
    def test_short_general_returns_fast(self):
        """Short general query with no files → fast."""
        from data_agent.utils import assess_complexity
        tier = assess_complexity("查询北京人口", "GENERAL", file_count=0)
        self.assertEqual(tier, "fast")

    def test_long_optimization_returns_premium(self):
        """Long optimization text → premium."""
        from data_agent.utils import assess_complexity
        long_text = "请对这三块耕地进行深度分析和用地优化" + "详细描述" * 60
        tier = assess_complexity(long_text, "OPTIMIZATION", file_count=0)
        self.assertEqual(tier, "premium")

    def test_many_files_governance_returns_premium(self):
        """Governance with many files → premium."""
        from data_agent.utils import assess_complexity
        tier = assess_complexity("审计这些数据", "GOVERNANCE", file_count=3)
        self.assertEqual(tier, "premium")

    def test_complex_keywords_returns_premium(self):
        """Complex keywords in optimization → premium."""
        from data_agent.utils import assess_complexity
        tier = assess_complexity("多源融合三个数据集", "OPTIMIZATION", file_count=0)
        self.assertEqual(tier, "premium")

    def test_medium_query_returns_standard(self):
        """Medium-length general query → standard."""
        from data_agent.utils import assess_complexity
        text = "请对上海市浦东新区的土地利用数据做缓冲区分析并生成热力图"
        tier = assess_complexity(text, "GENERAL", file_count=1)
        self.assertEqual(tier, "standard")

    def test_general_with_spatial_keyword_returns_standard(self):
        """Short general with spatial keyword → standard (not fast)."""
        from data_agent.utils import assess_complexity
        tier = assess_complexity("做缓冲区分析", "GENERAL", file_count=0)
        self.assertEqual(tier, "standard")

    def test_short_optimization_returns_standard(self):
        """Short optimization without complex keywords → standard."""
        from data_agent.utils import assess_complexity
        tier = assess_complexity("优化布局", "OPTIMIZATION", file_count=0)
        self.assertEqual(tier, "standard")


class TestModelTierMap(unittest.TestCase):
    def test_all_tiers_present(self):
        """MODEL_TIER_MAP has fast, standard, premium."""
        from data_agent.agent import MODEL_TIER_MAP
        self.assertIn("fast", MODEL_TIER_MAP)
        self.assertIn("standard", MODEL_TIER_MAP)
        self.assertIn("premium", MODEL_TIER_MAP)

    def test_tier_values(self):
        """Tier values match model constants."""
        from data_agent.agent import MODEL_TIER_MAP, MODEL_FAST, MODEL_STANDARD, MODEL_PREMIUM
        self.assertEqual(MODEL_TIER_MAP["fast"], MODEL_FAST)
        self.assertEqual(MODEL_TIER_MAP["standard"], MODEL_STANDARD)
        self.assertEqual(MODEL_TIER_MAP["premium"], MODEL_PREMIUM)


class TestGetModelForTier(unittest.TestCase):
    def test_default_returns_standard(self):
        """Default tier is 'standard'."""
        from data_agent.agent import get_model_for_tier, MODEL_STANDARD
        model = get_model_for_tier("standard")
        self.assertEqual(model, MODEL_STANDARD)

    def test_contextvar_override_to_premium(self):
        """ContextVar override to premium."""
        from data_agent.agent import get_model_for_tier, MODEL_PREMIUM
        from data_agent.user_context import current_model_tier
        token = current_model_tier.set("premium")
        try:
            model = get_model_for_tier("standard")
            self.assertEqual(model, MODEL_PREMIUM)
        finally:
            current_model_tier.reset(token)

    def test_contextvar_override_to_fast(self):
        """ContextVar set to fast."""
        from data_agent.agent import get_model_for_tier, MODEL_FAST
        from data_agent.user_context import current_model_tier
        token = current_model_tier.set("fast")
        try:
            model = get_model_for_tier("standard")
            self.assertEqual(model, MODEL_FAST)
        finally:
            current_model_tier.reset(token)


    def test_base_tier_fast_at_default_contextvar(self):
        """When ContextVar is at default, base_tier='fast' returns MODEL_FAST."""
        from data_agent.agent import get_model_for_tier, MODEL_FAST
        model = get_model_for_tier("fast")
        self.assertEqual(model, MODEL_FAST)


class TestModelTierContextVar(unittest.TestCase):
    def test_default_is_standard(self):
        """current_model_tier default is 'standard'."""
        from data_agent.user_context import current_model_tier
        self.assertEqual(current_model_tier.get(), "standard")

    def test_set_and_get(self):
        """current_model_tier can be set and read."""
        from data_agent.user_context import current_model_tier
        token = current_model_tier.set("premium")
        try:
            self.assertEqual(current_model_tier.get(), "premium")
        finally:
            current_model_tier.reset(token)


if __name__ == "__main__":
    unittest.main()
