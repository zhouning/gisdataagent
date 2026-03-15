"""Tests for Advanced Reasoning (v11.0.2).

Covers reasoning extraction, confidence scoring, trace serialization.
"""
import unittest
from unittest.mock import patch, MagicMock


class TestReasoningConstants(unittest.TestCase):
    def test_state_key(self):
        from data_agent.reasoning import STATE_KEY
        self.assertEqual(STATE_KEY, "__reasoning_trace__")

    def test_cot_prefix(self):
        from data_agent.reasoning import COT_PREFIX
        self.assertIn("<reasoning>", COT_PREFIX)


class TestReasoningExtraction(unittest.TestCase):
    def test_extract_single_block(self):
        from data_agent.reasoning import extract_reasoning_blocks
        text = "Hello <reasoning>I think we should buffer</reasoning> World"
        blocks, cleaned = extract_reasoning_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertIn("buffer", blocks[0])
        self.assertNotIn("<reasoning>", cleaned)
        self.assertIn("Hello", cleaned)
        self.assertIn("World", cleaned)

    def test_extract_multiple_blocks(self):
        from data_agent.reasoning import extract_reasoning_blocks
        text = "<reasoning>Step 1</reasoning> middle <reasoning>Step 2</reasoning> end"
        blocks, cleaned = extract_reasoning_blocks(text)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0], "Step 1")
        self.assertEqual(blocks[1], "Step 2")

    def test_extract_no_blocks(self):
        from data_agent.reasoning import extract_reasoning_blocks
        blocks, cleaned = extract_reasoning_blocks("no reasoning here")
        self.assertEqual(blocks, [])
        self.assertEqual(cleaned, "no reasoning here")

    def test_extract_empty(self):
        from data_agent.reasoning import extract_reasoning_blocks
        blocks, cleaned = extract_reasoning_blocks("")
        self.assertEqual(blocks, [])
        self.assertEqual(cleaned, "")

    def test_extract_multiline_block(self):
        from data_agent.reasoning import extract_reasoning_blocks
        text = "<reasoning>\n观察到数据有EPSG:4326\n选择使用buffer分析\n</reasoning>"
        blocks, _ = extract_reasoning_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertIn("EPSG:4326", blocks[0])


class TestReasoningSteps(unittest.TestCase):
    def test_build_steps(self):
        from data_agent.reasoning import build_reasoning_steps
        blocks = ["观察到数据量为5000行\n选择DBSCAN聚类"]
        steps = build_reasoning_steps(blocks)
        self.assertEqual(len(steps), 1)
        self.assertIn("5000", steps[0].thought)

    def test_step_to_dict(self):
        from data_agent.reasoning import ReasoningStep
        step = ReasoningStep(thought="think", action="do", observation="see")
        d = step.to_dict()
        self.assertEqual(d["thought"], "think")
        self.assertIn("timestamp", d)


class TestReasoningTrace(unittest.TestCase):
    def test_empty_trace(self):
        from data_agent.reasoning import ReasoningTrace
        trace = ReasoningTrace()
        d = trace.to_dict()
        self.assertEqual(d["step_count"], 0)
        self.assertIsNone(d["confidence"])

    def test_from_session_state_empty(self):
        from data_agent.reasoning import ReasoningTrace
        trace = ReasoningTrace.from_session_state({})
        self.assertEqual(len(trace.steps), 0)

    def test_from_session_state_with_data(self):
        from data_agent.reasoning import ReasoningTrace, STATE_KEY
        state = {
            STATE_KEY: [
                {"thought": "step 1", "action": "analyze", "observation": "found pattern"},
                "raw reasoning block",
            ]
        }
        trace = ReasoningTrace.from_session_state(state)
        self.assertEqual(len(trace.steps), 2)
        self.assertEqual(trace.steps[0].thought, "step 1")
        self.assertEqual(trace.steps[1].thought, "raw reasoning block")


class TestConfidenceScore(unittest.TestCase):
    def test_to_dict(self):
        from data_agent.reasoning import ConfidenceScore
        score = ConfidenceScore(overall=0.85, data_quality=0.9,
                                method_appropriateness=0.8,
                                result_completeness=0.75,
                                explanation="Good analysis")
        d = score.to_dict()
        self.assertEqual(d["overall"], 0.85)
        self.assertEqual(d["explanation"], "Good analysis")

    def test_heuristic_with_error(self):
        from data_agent.reasoning import heuristic_confidence
        score = heuristic_confidence("", [], error="pipeline crashed")
        self.assertLess(score.overall, 0.2)

    def test_heuristic_long_report(self):
        from data_agent.reasoning import heuristic_confidence
        score = heuristic_confidence("x" * 3000, [{"name": "tool1"}, {"name": "tool2"}])
        self.assertGreater(score.overall, 0.6)

    def test_heuristic_with_tool_errors(self):
        from data_agent.reasoning import heuristic_confidence
        tool_log = [{"name": "t1", "status": "error"}, {"name": "t2", "status": "ok"}]
        score = heuristic_confidence("some report", tool_log)
        self.assertLess(score.overall, 0.8)

    def test_score_confidence_heuristic_fallback(self):
        from data_agent.reasoning import score_confidence
        score = score_confidence("analysis report text", use_llm=False)
        self.assertIsNotNone(score)
        self.assertGreater(score.overall, 0)


class TestReasoningEnabled(unittest.TestCase):
    def test_default_enabled(self):
        from data_agent.reasoning import REASONING_ENABLED
        # Should be true by default (unless env var overrides)
        self.assertIsInstance(REASONING_ENABLED, bool)


if __name__ == "__main__":
    unittest.main()
