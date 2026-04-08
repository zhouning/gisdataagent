"""Feedback Loop REST API routes (v19.0)."""
from __future__ import annotations

import asyncio
import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _require_admin


async def _api_feedback_submit(request: Request):
    """POST /api/feedback — submit thumbs up/down on an agent response."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    vote = body.get("vote")
    if vote not in (1, -1):
        return JSONResponse({"error": "vote must be 1 or -1"}, status_code=400)
    query_text = body.get("query_text", "")
    if not query_text:
        return JSONResponse({"error": "query_text required"}, status_code=400)

    from ..feedback import FeedbackStore, FeedbackProcessor

    store = FeedbackStore()
    fb_id = store.record(
        username=user.get("username", ""),
        query_text=query_text,
        vote=vote,
        session_id=body.get("session_id"),
        message_id=body.get("message_id"),
        pipeline_type=body.get("pipeline_type"),
        response_text=body.get("response_text"),
        issue_description=body.get("issue_description"),
        issue_tags=body.get("issue_tags"),
        context_snapshot=body.get("context_snapshot"),
    )
    if fb_id is None:
        return JSONResponse({"error": "failed to save"}, status_code=500)

    # Auto-process upvotes in background
    if vote == 1:
        processor = FeedbackProcessor()
        asyncio.create_task(processor.process_upvote(fb_id))

    return JSONResponse({"id": fb_id, "status": "recorded"})


async def _api_feedback_stats(request: Request):
    """GET /api/feedback/stats?days=30 — feedback statistics."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    days = int(request.query_params.get("days", "30"))

    from ..feedback import FeedbackStore

    stats = FeedbackStore().get_stats(days=days)
    return JSONResponse(stats)


async def _api_feedback_list(request: Request):
    """GET /api/feedback/list?vote=-1&resolved=false&limit=50."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    vote = request.query_params.get("vote")
    resolved = request.query_params.get("resolved")
    limit = int(request.query_params.get("limit", "50"))

    vote_int = int(vote) if vote is not None else None
    resolved_bool = resolved.lower() == "true" if resolved is not None else None

    from ..feedback import FeedbackStore

    items = FeedbackStore().list_recent(vote=vote_int, resolved=resolved_bool, limit=limit)
    return JSONResponse(items)


async def _api_feedback_ingest(request: Request):
    """POST /api/feedback/{id}/ingest — manually trigger upvote ingestion (admin)."""
    admin_check = _require_admin(request)
    if admin_check:
        return admin_check
    fb_id = int(request.path_params["id"])

    from ..feedback import FeedbackProcessor

    processor = FeedbackProcessor()
    result = await processor.process_upvote(fb_id)
    return JSONResponse(result)


async def _api_feedback_process_downvotes(request: Request):
    """POST /api/feedback/process-downvotes — batch process downvotes (admin)."""
    admin_check = _require_admin(request)
    if admin_check:
        return admin_check

    from ..feedback import FeedbackProcessor

    processor = FeedbackProcessor()
    result = await processor.process_downvote_batch()
    return JSONResponse(result)


def get_feedback_routes() -> list[Route]:
    return [
        Route("/api/feedback", endpoint=_api_feedback_submit, methods=["POST"]),
        Route("/api/feedback/stats", endpoint=_api_feedback_stats, methods=["GET"]),
        Route("/api/feedback/list", endpoint=_api_feedback_list, methods=["GET"]),
        Route("/api/feedback/{id:int}/ingest", endpoint=_api_feedback_ingest, methods=["POST"]),
        Route("/api/feedback/process-downvotes", endpoint=_api_feedback_process_downvotes, methods=["POST"]),
    ]
