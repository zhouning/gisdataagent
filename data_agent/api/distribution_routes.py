"""Data Distribution REST routes — requests, reviews, packaging, access stats (v15.0)."""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context, _require_admin

logger = logging.getLogger("data_agent.api.distribution_routes")


async def dreq_create(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from ..data_distribution import create_data_request
    result = create_data_request(body.get("asset_id", 0), username, body.get("reason", ""))
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result, status_code=201)


async def dreq_list(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    from ..data_distribution import list_data_requests
    requests_list = list_data_requests(username, role)
    return JSONResponse({"requests": requests_list})


async def dreq_approve(request: Request):
    user, username, role, err = _require_admin(request)
    if err:
        return err
    req_id = int(request.path_params.get("id", 0))
    from ..data_distribution import approve_request
    result = approve_request(req_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result)


async def dreq_reject(request: Request):
    user, username, role, err = _require_admin(request)
    if err:
        return err
    req_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        body = {}
    from ..data_distribution import reject_request
    result = reject_request(req_id, username, body.get("reason", ""))
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result)


async def assets_package(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    asset_ids = body.get("asset_ids", [])
    if not asset_ids:
        return JSONResponse({"error": "asset_ids required"}, status_code=400)
    from ..data_distribution import package_assets
    result = package_assets(asset_ids, username=username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result)


async def catalog_review_add(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    asset_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from ..data_distribution import add_review
    result = add_review(asset_id, username, body.get("rating", 0), body.get("comment", ""))
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result)


async def catalog_reviews_list(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    asset_id = int(request.path_params.get("id", 0))
    from ..data_distribution import get_reviews, get_asset_rating
    reviews = get_reviews(asset_id)
    rating = get_asset_rating(asset_id)
    return JSONResponse({"reviews": reviews, **rating})


async def assets_hot(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    limit = int(request.query_params.get("limit", "10"))
    from ..data_distribution import get_hot_assets
    return JSONResponse({"hot_assets": get_hot_assets(limit)})


async def assets_access_stats(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    asset_id = request.query_params.get("asset_id")
    days = int(request.query_params.get("days", "30"))
    from ..data_distribution import get_access_stats
    result = get_access_stats(int(asset_id) if asset_id else None, days)
    return JSONResponse(result)


def get_distribution_routes() -> list:
    return [
        Route("/api/data-requests", dreq_create, methods=["POST"]),
        Route("/api/data-requests", dreq_list, methods=["GET"]),
        Route("/api/data-requests/{id:int}/approve", dreq_approve, methods=["POST"]),
        Route("/api/data-requests/{id:int}/reject", dreq_reject, methods=["POST"]),
        Route("/api/assets/package", assets_package, methods=["POST"]),
        Route("/api/catalog/{id:int}/review", catalog_review_add, methods=["POST"]),
        Route("/api/catalog/{id:int}/reviews", catalog_reviews_list, methods=["GET"]),
        Route("/api/assets/hot", assets_hot, methods=["GET"]),
        Route("/api/assets/access-stats", assets_access_stats, methods=["GET"]),
    ]
