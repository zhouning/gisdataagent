"""Tests for annotation WebSocket broadcast (v23.0)."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from data_agent.annotation_ws import (
    broadcast_annotation_event, get_connected_count,
    _clients, _lock,
)


class TestAnnotationWsBroadcast(unittest.TestCase):
    def test_broadcast_no_clients(self):
        _clients.clear()
        count = asyncio.get_event_loop().run_until_complete(
            broadcast_annotation_event({"action": "create"})
        )
        assert count == 0

    def test_get_connected_count_empty(self):
        _clients.clear()
        assert get_connected_count() == 0

    def test_broadcast_with_mock_client(self):
        _clients.clear()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()
        _clients.add(mock_ws)
        try:
            count = asyncio.get_event_loop().run_until_complete(
                broadcast_annotation_event({"action": "create", "annotation": {"id": 1}})
            )
            assert count == 1
            mock_ws.send_text.assert_called_once()
            payload = mock_ws.send_text.call_args[0][0]
            assert '"create"' in payload
        finally:
            _clients.clear()

    def test_broadcast_removes_dead_clients(self):
        _clients.clear()
        dead_ws = AsyncMock()
        dead_ws.send_text = AsyncMock(side_effect=Exception("closed"))
        _clients.add(dead_ws)
        try:
            count = asyncio.get_event_loop().run_until_complete(
                broadcast_annotation_event({"action": "delete"})
            )
            assert count == 0
            assert dead_ws not in _clients
        finally:
            _clients.clear()


class TestAnnotationWsRoutes(unittest.TestCase):
    def test_routes_defined(self):
        from data_agent.annotation_ws import annotation_ws_routes
        assert len(annotation_ws_routes) == 1
        assert annotation_ws_routes[0].path == "/ws/annotations"


if __name__ == "__main__":
    unittest.main()
