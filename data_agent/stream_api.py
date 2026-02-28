"""
HTTP REST + WebSocket endpoints for real-time data streams.

REST:
  POST /api/streams           — create stream
  GET  /api/streams           — list active streams
  DELETE /api/streams/{id}    — stop stream
  POST /api/streams/{id}/ingest — HTTP webhook ingest

WebSocket:
  WS /ws/streams/{id}        — live GeoJSON updates

Routes are mounted before the Chainlit catch-all.
"""
import asyncio
import json
import time
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .stream_engine import (
    StreamConfig, LocationEvent,
    get_stream_engine,
)


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------

async def create_stream(request: Request) -> JSONResponse:
    """POST /api/streams — create a new stream."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    name = body.get("name", "Unnamed Stream")
    geofence_wkt = body.get("geofence_wkt", "")
    window_seconds = int(body.get("window_seconds", 60))
    owner = body.get("owner", "anonymous")

    engine = get_stream_engine()
    config = engine.create_stream(StreamConfig(
        id="",
        name=name,
        geofence_wkt=geofence_wkt,
        window_seconds=max(5, min(window_seconds, 3600)),
        owner_username=owner,
    ))

    await engine.start_stream(config.id)

    return JSONResponse({
        "status": "created",
        "stream": {
            "id": config.id,
            "name": config.name,
            "window_seconds": config.window_seconds,
            "has_geofence": bool(config.geofence_wkt),
            "ws_url": f"/ws/streams/{config.id}",
            "ingest_url": f"/api/streams/{config.id}/ingest",
        },
    }, status_code=201)


async def list_streams(request: Request) -> JSONResponse:
    """GET /api/streams — list all registered streams."""
    engine = get_stream_engine()
    streams = engine.get_active_streams()
    return JSONResponse({"streams": streams, "count": len(streams)})


async def delete_stream(request: Request) -> JSONResponse:
    """DELETE /api/streams/{id} — stop and remove a stream."""
    stream_id = request.path_params.get("id", "")
    if not stream_id:
        return JSONResponse({"error": "stream_id required"}, status_code=400)

    engine = get_stream_engine()
    stopped = await engine.stop_stream(stream_id)
    if stopped:
        return JSONResponse({"status": "stopped", "id": stream_id})
    return JSONResponse({"error": "stream not found"}, status_code=404)


async def ingest_location(request: Request) -> JSONResponse:
    """POST /api/streams/{id}/ingest — HTTP webhook ingest."""
    stream_id = request.path_params.get("id", "")
    if not stream_id:
        return JSONResponse({"error": "stream_id required"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    # Support single event or batch
    events_data = body if isinstance(body, list) else [body]
    ingested = 0

    engine = get_stream_engine()
    for item in events_data:
        try:
            event = LocationEvent(
                device_id=str(item.get("device_id", "unknown")),
                stream_id=stream_id,
                lat=float(item.get("lat", 0)),
                lng=float(item.get("lng", 0)),
                timestamp=float(item.get("timestamp", time.time())),
                speed=float(item.get("speed", 0)),
                heading=float(item.get("heading", 0)),
                payload=item.get("payload", {}),
                owner_username=item.get("owner", ""),
            )
            await engine.ingest(event)
            ingested += 1
        except (ValueError, TypeError, KeyError):
            continue

    return JSONResponse({
        "status": "ok",
        "ingested": ingested,
        "stream_id": stream_id,
    })


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------

async def stream_websocket(websocket: WebSocket) -> None:
    """WS /ws/streams/{id} — live GeoJSON FeatureCollection updates."""
    stream_id = websocket.path_params.get("id", "")
    if not stream_id:
        await websocket.close(code=4000, reason="stream_id required")
        return

    await websocket.accept()

    engine = get_stream_engine()
    queue = engine.subscribe(stream_id)

    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=30)
                await websocket.send_text(message)
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_text(json.dumps({
                    "type": "heartbeat",
                    "stream_id": stream_id,
                    "timestamp": time.time(),
                }))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[Stream WS] Error for {stream_id}: {e}")
    finally:
        engine.unsubscribe(stream_id, queue)


# ---------------------------------------------------------------------------
# Route Mounting
# ---------------------------------------------------------------------------

def get_stream_routes():
    """Return list of Starlette routes for stream API."""
    return [
        Route("/api/streams", endpoint=create_stream, methods=["POST"]),
        Route("/api/streams", endpoint=list_streams, methods=["GET"]),
        Route("/api/streams/{id}", endpoint=delete_stream, methods=["DELETE"]),
        Route("/api/streams/{id}/ingest", endpoint=ingest_location, methods=["POST"]),
        WebSocketRoute("/ws/streams/{id}", endpoint=stream_websocket),
    ]


def mount_stream_routes(app) -> bool:
    """Insert stream routes before Chainlit catch-all."""
    routes = get_stream_routes()
    inserted = False

    for route in routes:
        for i, r in enumerate(app.router.routes):
            if hasattr(r, "path") and r.path == "/{full_path:path}":
                app.router.routes.insert(i, route)
                inserted = True
                break
        else:
            app.router.routes.append(route)
            inserted = True

    if inserted:
        print("[Stream] API routes mounted: /api/streams, /ws/streams/{id}")

    return inserted
