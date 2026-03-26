"""Tests for agent message bus persistence."""
import unittest
from unittest.mock import patch, MagicMock
from data_agent.agent_messaging import AgentMessage


def _make_bus():
    """Create a fresh AgentMessageBus (import inside patch context)."""
    from data_agent.agent_messaging import AgentMessageBus
    return AgentMessageBus()


class TestMessageBusPersistence(unittest.TestCase):
    """Test delivery tracking methods."""

    def setUp(self):
        self.bus = _make_bus()

    @patch("data_agent.db_engine.get_engine")
    def test_mark_delivered(self, mock_engine):
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        self.bus.mark_delivered("msg-123")
        mock_conn.execute.assert_called_once()

    @patch("data_agent.db_engine.get_engine")
    def test_get_undelivered(self, mock_engine):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        result = self.bus.get_undelivered("agent-a")
        self.assertEqual(result, [])

    @patch("data_agent.db_engine.get_engine")
    def test_replay_undelivered(self, mock_engine):
        mock_conn = MagicMock()
        # First call: get_undelivered query
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(message_id="m1", from_agent="a", to_agent="b",
                     message_type="notification", payload="{}", correlation_id="", created_at="2026-01-01")
        ]
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        # Subscribe a handler
        handler = MagicMock()
        self.bus.subscribe("b", handler)
        replayed = self.bus.replay_undelivered("b")
        self.assertEqual(replayed, 1)
        handler.assert_called_once()

    def test_publish_local(self):
        handler = MagicMock()
        self.bus.subscribe("agent-x", handler)
        self.bus.publish(AgentMessage(from_agent="sender", to_agent="agent-x",
                                      message_type="test", payload={"data": 1}))
        handler.assert_called_once()

    @patch("data_agent.db_engine.get_engine")
    def test_cleanup_old_messages(self, mock_engine):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.rowcount = 5
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        count = self.bus.cleanup_old_messages(days=7)
        self.assertEqual(count, 5)

    @patch("data_agent.db_engine.get_engine")
    def test_persist_tracks_delivered_true(self, mock_engine):
        """When a subscriber exists, _persist_message should set delivered=True."""
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        self.bus._persist = True
        handler = MagicMock()
        self.bus.subscribe("target", handler)
        self.bus.publish(AgentMessage(from_agent="src", to_agent="target"))
        # Check the INSERT was called with delivered=True
        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        self.assertTrue(params["delivered"])

    @patch("data_agent.db_engine.get_engine")
    def test_persist_tracks_delivered_false(self, mock_engine):
        """When no subscriber exists, _persist_message should set delivered=False."""
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        self.bus._persist = True
        self.bus.publish(AgentMessage(from_agent="src", to_agent="nobody"))
        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        self.assertFalse(params["delivered"])

    def test_get_undelivered_no_engine(self):
        """get_undelivered returns [] when no DB engine available."""
        result = self.bus.get_undelivered("agent-a")
        self.assertEqual(result, [])

    def test_cleanup_no_engine(self):
        """cleanup_old_messages returns 0 when no DB engine available."""
        count = self.bus.cleanup_old_messages(days=7)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
