"""Tests for Agent Messaging + Self-Improvement (v11.0.5, Design Patterns Ch17+Ch20)."""
import unittest
from unittest.mock import patch, MagicMock


class TestAgentMessage(unittest.TestCase):
    def test_creation(self):
        from data_agent.agent_messaging import AgentMessage
        msg = AgentMessage(from_agent="planner", to_agent="analyzer", payload={"task": "analyze"})
        self.assertEqual(msg.from_agent, "planner")
        self.assertEqual(msg.message_type, "notification")

    def test_to_dict(self):
        from data_agent.agent_messaging import AgentMessage
        msg = AgentMessage(from_agent="a", to_agent="b")
        d = msg.to_dict()
        self.assertIn("message_id", d)
        self.assertIn("timestamp", d)


class TestAgentMessageBus(unittest.TestCase):
    def setUp(self):
        from data_agent.agent_messaging import reset_message_bus
        reset_message_bus()

    def tearDown(self):
        from data_agent.agent_messaging import reset_message_bus
        reset_message_bus()

    def test_subscribe_and_publish(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        received = []
        bus.subscribe("analyzer", lambda msg: received.append(msg))
        bus.publish(AgentMessage(from_agent="planner", to_agent="analyzer", payload={"x": 1}))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].payload["x"], 1)

    def test_no_delivery_to_wrong_agent(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        received = []
        bus.subscribe("analyzer", lambda msg: received.append(msg))
        bus.publish(AgentMessage(from_agent="planner", to_agent="visualizer"))
        self.assertEqual(len(received), 0)

    def test_broadcast(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        received_a, received_b = [], []
        bus.subscribe("a", lambda msg: received_a.append(msg))
        bus.subscribe("b", lambda msg: received_b.append(msg))
        bus.publish(AgentMessage(from_agent="sender", to_agent="*"))
        self.assertEqual(len(received_a), 1)
        self.assertEqual(len(received_b), 1)

    def test_broadcast_excludes_sender(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        received = []
        bus.subscribe("sender", lambda msg: received.append(msg))
        bus.publish(AgentMessage(from_agent="sender", to_agent="*"))
        self.assertEqual(len(received), 0)

    def test_message_log(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        bus.publish(AgentMessage(from_agent="a", to_agent="b"))
        bus.publish(AgentMessage(from_agent="b", to_agent="a"))
        log = bus.get_message_log()
        self.assertEqual(len(log), 2)

    def test_message_log_filtered(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        bus.publish(AgentMessage(from_agent="a", to_agent="b"))
        bus.publish(AgentMessage(from_agent="c", to_agent="d"))
        log = bus.get_message_log(agent_name="a")
        self.assertEqual(len(log), 1)

    def test_unsubscribe(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        received = []
        bus.subscribe("agent", lambda msg: received.append(msg))
        bus.unsubscribe("agent")
        bus.publish(AgentMessage(from_agent="x", to_agent="agent"))
        self.assertEqual(len(received), 0)

    def test_clear(self):
        from data_agent.agent_messaging import get_message_bus, AgentMessage
        bus = get_message_bus()
        bus.subscribe("a", lambda msg: None)
        bus.publish(AgentMessage(from_agent="a", to_agent="b"))
        bus.clear()
        self.assertEqual(len(bus.get_message_log()), 0)


class TestSelfImprovementConstants(unittest.TestCase):
    def test_table_names(self):
        from data_agent.self_improvement import T_PROMPT_OUTCOMES, T_TOOL_PREFERENCES
        self.assertEqual(T_PROMPT_OUTCOMES, "agent_prompt_outcomes")
        self.assertEqual(T_TOOL_PREFERENCES, "agent_tool_preferences")


class TestPromptOutcomes(unittest.TestCase):
    @patch("data_agent.self_improvement.get_engine", return_value=None)
    def test_record_no_engine(self, _):
        from data_agent.self_improvement import record_outcome
        record_outcome("general", "test prompt", True)  # should not raise

    @patch("data_agent.self_improvement.get_engine", return_value=None)
    def test_get_rates_no_engine(self, _):
        from data_agent.self_improvement import get_pipeline_success_rates
        self.assertEqual(get_pipeline_success_rates(), {})

    def test_hash_prompt(self):
        from data_agent.self_improvement import _hash_prompt
        h = _hash_prompt("test prompt")
        self.assertEqual(len(h), 16)
        # Same input = same hash
        self.assertEqual(h, _hash_prompt("test prompt"))
        # Different input = different hash
        self.assertNotEqual(h, _hash_prompt("other prompt"))


class TestToolPreferences(unittest.TestCase):
    @patch("data_agent.self_improvement.get_engine", return_value=None)
    def test_record_no_engine(self, _):
        from data_agent.self_improvement import record_tool_usage
        record_tool_usage("buffer", True)  # should not raise

    @patch("data_agent.self_improvement.get_engine", return_value=None)
    def test_get_prefs_no_engine(self, _):
        from data_agent.self_improvement import get_tool_preferences
        self.assertEqual(get_tool_preferences(), [])

    def test_generate_hints_empty(self):
        from data_agent.self_improvement import generate_tool_hints
        with patch("data_agent.self_improvement.get_tool_preferences", return_value=[]):
            hints = generate_tool_hints()
            self.assertEqual(hints, "")

    def test_generate_hints_with_data(self):
        from data_agent.self_improvement import generate_tool_hints
        prefs = [
            {"tool_name": "buffer", "data_type": "Polygon", "crs": "",
             "success_rate": 0.95, "avg_duration": 1.2, "sample_count": 50},
        ]
        with patch("data_agent.self_improvement.get_tool_preferences", return_value=prefs):
            hints = generate_tool_hints()
            self.assertIn("buffer", hints)
            self.assertIn("推荐工具", hints)


if __name__ == "__main__":
    unittest.main()
