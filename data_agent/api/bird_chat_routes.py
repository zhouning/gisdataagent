"""List only registered sources visible to the authenticated chat user."""
import asyncio
import logging

from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..bird_chat import visible_chat_sources


async def list_bird_chat_sources(request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse({"sources": await asyncio.to_thread(visible_chat_sources)})
    except Exception:
        logging.getLogger(__name__).exception("BIRD source catalog unavailable")
        return JSONResponse({"error": "Source catalog unavailable"}, status_code=503)


def get_bird_chat_routes():
    return [Route("/api/nl2sql/bird-sources", list_bird_chat_sources, methods=["GET"])]
