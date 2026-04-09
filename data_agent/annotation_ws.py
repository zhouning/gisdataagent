"""
Annotation WebSocket — real-time broadcast of annotation changes (v23.0).

Single-instance in-memory hub. When an annotation is created, updated, or
deleted via REST, the change is broadcast to all connected WebSocket clients
so their map views update instantly.

Usage:
    # Mount in frontend_api.py
    from data_agent.annotation_ws import annotation_ws_routes
    routes += annotation_ws_routes

    # Broadcast from REST handlers
    from data_agent.annotation_ws import broadcast_annotation_event
    await broadcast_annotation_event({"action": "create", "annotation": {...}})
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger("data_agent.annotation_ws")

# In-memory connection set (single-instance)
_clients: Set[WebSocket] = set()
_lock = asyncio.Lock()


async def _ws_handler(websocket: WebSocket) -> None:
    """WebSocket endpoint for annotation real-time updates."""
    await websocket.accept()
    async with _lock:
        _clients.add(websocket)
    logger.info("Annotation WS client connected (%d total)", len(_clients))
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        async with _lock:
            _clients.discard(websocket)
        logger.info("Annotation WS client disconnected (%d remaining)", len(_clients))


async def broadcast_annotation_event(event: dict) -> int:
    """Broadcast an annotation event to all connected clients.

    Args:
        event: {"action": "create"|"update"|"delete"|"resolve", "annotation": {...}}

    Returns:
        Number of clients notified.
    """
    if not _clients:
        return 0
    payload = json.dumps(event, ensure_ascii=False, default=str)
    dead: list[WebSocket] = []
    count = 0
    async with _lock:
        for ws in _clients:
            try:
                await ws.send_text(payload)
                count += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)
    return count


def get_connected_count() -> int:
    """Return number of currently connected WebSocket clients."""
    return len(_clients)


annotation_ws_routes = [
    WebSocketRoute("/ws/annotations", _ws_handler),
]
