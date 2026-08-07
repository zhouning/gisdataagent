"""Data Distribution REST routes — requests, reviews, packaging, access stats (v15.0)."""

import logging

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _require_admin, _set_user_context

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
    try:
        asset_id = int(body.get("asset_id", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "资产编号无效"}, status_code=400)
    from ..data_distribution import create_data_request
    result = create_data_request(
        asset_id,
        username,
        body.get("reason", ""),
        body.get("duration_days", 30),
        body.get("package_quota", 5),
    )
    if result.get("status") == "error":
        status_code = 404 if result.get("error_code") == "asset_not_found" else 400
        return JSONResponse({"error": result["message"]}, status_code=status_code)
    return JSONResponse(result, status_code=201 if result.get("created", True) else 200)


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
    result = approve_request(req_id, username, current_tenant_id.get())
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result)


async def dreq_revoke(request: Request):
    _user, username, _role, err = _require_admin(request)
    if err:
        return err
    req_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        body = {}
    from ..data_distribution import revoke_request

    result = revoke_request(req_id, username, body.get("reason", ""))
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
        status_code = {
            "access_denied": 403,
            "asset_not_found": 404,
            "quota_exhausted": 409,
        }.get(result.get("error_code"), 400)
        return JSONResponse(
            {
                "error": result["message"],
                "error_code": result.get("error_code"),
            },
            status_code=status_code,
        )
    return JSONResponse(result)


async def distribution_package_download(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from ..data_distribution import get_distribution_package

    result = get_distribution_package(request.path_params.get("package_id", ""), username)
    if result.get("status") == "error":
        status_code = 404 if result.get("error_code") == "package_not_found" else 503
        return JSONResponse({"error": result["message"]}, status_code=status_code)
    return FileResponse(
        result["file_path"],
        media_type="application/zip",
        filename=result["zip_name"],
    )


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
    from ..data_distribution import get_asset_rating, get_reviews
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
        Route("/api/data-requests/{id:int}/revoke", dreq_revoke, methods=["POST"]),
        Route("/api/assets/package", assets_package, methods=["POST"]),
        Route(
            "/api/distribution-packages/{package_id:str}/download",
            distribution_package_download,
            methods=["GET"],
        ),
        Route("/api/catalog/{id:int}/review", catalog_review_add, methods=["POST"]),
        Route("/api/catalog/{id:int}/reviews", catalog_reviews_list, methods=["GET"]),
        Route("/api/assets/hot", assets_hot, methods=["GET"]),
        Route("/api/assets/access-stats", assets_access_stats, methods=["GET"]),
    ]
