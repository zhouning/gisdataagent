"""Tests for Agent Decision Tracer (v15.0)."""
import unittest


class TestDecisionEvent(unittest.TestCase):
    def test_create_event(self):
        from data_agent.agent_decision_tracer import DecisionEvent
        import time
        e = DecisionEvent(
            timestamp=time.time(),
            agent_name="explorer",
            event_type="tool_selection",
            decision="选择工具 describe_geodataframe",
            reasoning="数据画像是分析的第一步",
            alternatives=["check_topology"],
        )
        self.assertEqual(e.event_type, "tool_selection")
        self.assertEqual(e.agent_name, "explorer")


class TestDecisionTrace(unittest.TestCase):
    def setUp(self):
        from data_agent.agent_decision_tracer import DecisionTrace
        self.trace = DecisionTrace(pipeline_type="optimization", trace_id="abc123")

    def test_add_tool_selection(self):
        self.trace.add_tool_selection("explorer", "describe_geodataframe",
                                      reasoning="需要数据画像", args={"file_path": "test.shp"})
        self.assertEqual(len(self.trace.events), 1)
        self.assertEqual(self.trace.events[0].event_type, "tool_selection")

    def test_add_agent_transfer(self):
        self.trace.add_agent_transfer("explorer", "processor", reason="探查完成转处理")
        self.assertEqual(len(self.trace.events), 1)
        self.assertEqual(self.trace.events[0].event_type, "transfer")

    def test_add_quality_gate(self):
        self.trace.add_quality_gate("quality_checker", "retry", feedback="FFI 未达标")
        self.assertEqual(self.trace.events[0].context["verdict"], "retry")

    def test_to_dict(self):
        self.trace.add_tool_selection("a", "t1")
        self.trace.add_agent_transfer("a", "b")
        d = self.trace.to_dict()
        self.assertEqual(d["pipeline_type"], "optimization")
        self.assertEqual(d["trace_id"], "abc123")
        self.assertEqual(d["event_count"], 2)
        self.assertIsInstance(d["events"], list)

    def test_to_mermaid(self):
        self.trace.add_agent_transfer("User", "explorer", "开始探查")
        self.trace.add_tool_selection("explorer", "describe_geodataframe", "画像")
        self.trace.add_quality_gate("checker", "pass")
        mermaid = self.trace.to_mermaid_sequence()
        self.assertIn("sequenceDiagram", mermaid)
        self.assertIn("explorer", mermaid)

    def test_empty_trace(self):
        d = self.trace.to_dict()
        self.assertEqual(d["event_count"], 0)
        mermaid = self.trace.to_mermaid_sequence()
        self.assertIn("sequenceDiagram", mermaid)


if __name__ == "__main__":
    unittest.main()
