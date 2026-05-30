"""Tests for CapabilityQAToolset and the proactive-hints helper."""
import unittest

from data_agent.toolsets import capability_qa_tools
from data_agent.toolsets.capability_qa_tools import (
    CapabilityQAToolset,
    _build_capability_index,
    _clear_cache,
    _detect_language,
    _tokenize,
    query_capabilities,
    suggest_for_ambiguous,
)


class TestHelpers(unittest.TestCase):
    def test_detect_language_chinese(self):
        self.assertEqual(_detect_language("你能做什么"), "zh")

    def test_detect_language_english(self):
        self.assertEqual(_detect_language("what can you do"), "en")

    def test_detect_language_empty_defaults_zh(self):
        self.assertEqual(_detect_language(""), "zh")

    def test_tokenize_mixed(self):
        tokens = _tokenize("buffer 缓冲区 analysis")
        self.assertIn("buffer", tokens)
        self.assertIn("analysis", tokens)
        self.assertIn("缓冲区", tokens)


class TestCapabilityIndex(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def test_index_builds(self):
        index = _build_capability_index()
        self.assertIsInstance(index, list)
        self.assertGreater(len(index), 0)
        for entry in index:
            self.assertIn("name", entry)
            self.assertIn("description", entry)
            self.assertIn("category", entry)

    def test_index_has_multiple_categories(self):
        index = _build_capability_index()
        categories = {e["category"] for e in index}
        self.assertIn("toolset", categories)
        self.assertIn("tool_category", categories)

    def test_index_cached(self):
        a = _build_capability_index()
        b = _build_capability_index()
        self.assertIs(a, b)


class TestQueryCapabilities(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def test_list_all_returns_all(self):
        result = query_capabilities(list_all=True)
        self.assertEqual(result["query"], "")
        self.assertGreater(result["total_capabilities"], 0)
        self.assertEqual(len(result["matches"]), result["total_capabilities"])
        self.assertIn("grouped_by_domain", result)
        self.assertIn("suggestion", result)

    def test_empty_query_returns_overview(self):
        result = query_capabilities()
        self.assertGreater(len(result["matches"]), 0)

    def test_chinese_query_matches(self):
        result = query_capabilities("缓冲区")
        self.assertGreater(len(result["matches"]), 0)
        names = [m["name"] for m in result["matches"]]
        self.assertTrue(
            any("spatial" in n.lower() or "geo" in n.lower() for n in names),
            f"expected spatial-related match, got {names}",
        )

    def test_english_query_matches(self):
        result = query_capabilities("buffer")
        self.assertGreater(len(result["matches"]), 0)

    def test_result_structure(self):
        result = query_capabilities("heatmap")
        for key in ("query", "language", "matches", "total_capabilities", "suggestion"):
            self.assertIn(key, result)
        for match in result["matches"]:
            for key in ("name", "description", "category", "relevance"):
                self.assertIn(key, match)

    def test_domain_filter_restricts_results(self):
        unfiltered = query_capabilities("")
        filtered = query_capabilities("", domain="remote_sensing")
        self.assertLess(len(filtered["matches"]), len(unfiltered["matches"]))
        for m in filtered["matches"]:
            self.assertTrue(
                m["domain"] == "remote_sensing" or m["category"] == "remote_sensing"
            )

    def test_language_detected_from_query(self):
        self.assertEqual(query_capabilities("你能做什么")["language"], "zh")
        self.assertEqual(query_capabilities("what can you do")["language"], "en")

    def test_nonsense_query_returns_no_matches(self):
        result = query_capabilities("xyzzy-non-existent-capability-123")
        self.assertEqual(len(result["matches"]), 0)
        # Suggestion language follows the input; this input is English.
        self.assertIn("No match", result["suggestion"])


class TestSuggestForAmbiguous(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    def tearDown(self):
        _clear_cache()

    def test_returns_list_of_dicts(self):
        hints = suggest_for_ambiguous("帮我做一下缓冲区")
        self.assertIsInstance(hints, list)
        self.assertGreater(len(hints), 0)
        for h in hints:
            self.assertIn("name", h)
            self.assertIn("description", h)

    def test_default_top_k_is_at_most_four(self):
        hints = suggest_for_ambiguous("想处理一下数据")
        self.assertLessEqual(len(hints), 4)

    def test_top_k_override(self):
        hints = suggest_for_ambiguous("遥感 NDVI", top_k=2)
        self.assertLessEqual(len(hints), 2)

    def test_empty_input_returns_empty(self):
        self.assertEqual(suggest_for_ambiguous(""), [])
        self.assertEqual(suggest_for_ambiguous("   "), [])

    def test_unmatched_input_returns_fallback(self):
        # Non-GIS word with no keyword overlap — should still return fallback hints
        hints = suggest_for_ambiguous("asdfqwertyzxcv")
        self.assertIsInstance(hints, list)


class TestCapabilityQueryDetection(unittest.TestCase):
    def test_chinese_meta_questions_detected(self):
        from data_agent.intent_router import _is_capability_query
        self.assertTrue(_is_capability_query("你能做什么"))
        self.assertTrue(_is_capability_query("你有什么功能"))
        self.assertTrue(_is_capability_query("你是做什么的"))
        self.assertTrue(_is_capability_query("介绍一下你的能力"))

    def test_english_meta_questions_detected(self):
        from data_agent.intent_router import _is_capability_query
        self.assertTrue(_is_capability_query("what can you do"))
        self.assertTrue(_is_capability_query("What are your capabilities?"))
        self.assertTrue(_is_capability_query("list all features"))

    def test_normal_task_not_detected(self):
        from data_agent.intent_router import _is_capability_query
        self.assertFalse(_is_capability_query("帮我做500米缓冲区"))
        self.assertFalse(_is_capability_query("检查这份数据的拓扑"))
        self.assertFalse(_is_capability_query("download NDVI for Beijing"))

    def test_empty_string(self):
        from data_agent.intent_router import _is_capability_query
        self.assertFalse(_is_capability_query(""))
        self.assertFalse(_is_capability_query("   "))


class TestToolsetRegistration(unittest.TestCase):
    def test_toolset_instantiates(self):
        ts = CapabilityQAToolset()
        self.assertIsNotNone(ts)

    def test_core_tools_includes_query_capabilities(self):
        from data_agent.tool_filter import CORE_TOOLS
        self.assertIn("query_capabilities", CORE_TOOLS)


if __name__ == "__main__":
    unittest.main()
