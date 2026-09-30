"""Authenticated, local-snapshot-only pond screening endpoints."""
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


async def pond_catalog(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..uwm.abu_dhabi_flood.pond_planning import catalog
    try:
        return JSONResponse(await run_in_threadpool(catalog), headers={"Cache-Control": "private, no-store"})
    except FileNotFoundError:
        return JSONResponse({"error": "pond_snapshot_not_provisioned"}, status_code=503)
    except (ValueError, KeyError):
        return JSONResponse({"error": "pond_snapshot_integrity_failed"}, status_code=409)


async def pond_screening(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "pond_json_required"}, status_code=400)
    from ..uwm.abu_dhabi_flood.pond_planning import screen, screening_csv
    try:
        result = await run_in_threadpool(screen, payload)
        if request.url.path.endswith("export.csv"):
            return Response("\ufeff" + screening_csv(result), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="pond-screening-{result["screening_id"]}.csv"', "Cache-Control": "private, no-store"})
        return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
    except FileNotFoundError:
        return JSONResponse({"error": "pond_snapshot_not_provisioned"}, status_code=503)
    except ValueError as error:
        code = str(error)
        return JSONResponse({"error": code if code.startswith("pond_") else "pond_screening_invalid"}, status_code=400)
    except (KeyError, TypeError):
        return JSONResponse({"error": "pond_snapshot_integrity_failed"}, status_code=409)


def get_abu_dhabi_pond_routes():
    prefix = "/api/abu-dhabi/flood/pond-planning"
    return [Route(prefix + "/catalog", pond_catalog, methods=["GET"]),
            Route(prefix + "/screen", pond_screening, methods=["POST"]),
            Route(prefix + "/export.csv", pond_screening, methods=["POST"])]
