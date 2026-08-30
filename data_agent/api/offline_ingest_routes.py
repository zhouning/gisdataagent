"""HTTP surface for resumable offline geospatial ingest.

The routes stream request bodies directly to disk and delegate all state to
``OfflineIngestStore``.  A Windows collector can use the same store without
HTTP, which is important for physically isolated deployments.
"""

from __future__ import annotations

import asyncio
import json
import os
import zipfile

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from ..openai_compatible_llm import LLMServiceError
from .helpers import _get_user_from_request, _set_user_context


def _store():
    from ..offline_ingest import OfflineIngestStore

    return OfflineIngestStore()


def _auth(request: Request):
    # Standalone collector installations may run without Chainlit cookies. The
    # integrated GIS Data Agent keeps auth enabled by default.
    required = os.environ.get("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    user = _get_user_from_request(request)
    if required and not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    if user:
        _set_user_context(user)
        return (user.identifier if hasattr(user, "identifier") else str(user)), None
    return "collector", None


async def create_session(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
        result = _store().create_session(
            body.get("filename", "asset"),
            int(body.get("size", -1)),
            chunk_size=int(body.get("chunk_size", 128 * 1024 * 1024)),
            expected_sha256=body.get("sha256"),
            asset_kind=body.get("asset_kind"),
            source_system=body.get("source_system"),
        )
        result["actor"] = actor
        return JSONResponse(result, status_code=201)
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def session_status(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        return JSONResponse(_store().session_status(request.path_params["session_id"]))
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


async def upload_chunk(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        result = await _store().write_chunk(
            request.path_params["session_id"],
            int(request.path_params["index"]),
            request.stream(),
            supplied_sha256=request.headers.get("x-chunk-sha256"),
        )
        return JSONResponse({"status": "accepted", **result})
    except FileNotFoundError:
        return JSONResponse({"error": "upload session not found"}, status_code=404)
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def finalize_session(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        return JSONResponse(
            _store().finalize_session(request.path_params["session_id"], actor=actor)
        )
    except FileNotFoundError:
        return JSONResponse({"error": "upload session not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def ingest_session(request: Request):
    """Continue a finalized browser upload through expansion, profiling and quality."""
    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        result = _store().ingest_uploaded_session(
            request.path_params["session_id"],
            actor=actor,
            run_quality=bool(body.get("run_quality", True)),
        )
        return JSONResponse(result, status_code=200 if result.get("resumed") else 202)
    except FileNotFoundError:
        return JSONResponse({"error": "upload session or Raw asset not found"}, status_code=404)
    except (ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def local_scan(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
        path = body.get("path")
        if not path:
            return JSONResponse({"error": "path is required"}, status_code=400)
        return JSONResponse(_store().scan_local_path(path, actor=actor), status_code=202)
    except FileNotFoundError:
        return JSONResponse({"error": "path not found"}, status_code=404)
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def run_detail(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        return JSONResponse(_store().get_run(request.path_params["run_id"]))
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


async def run_list(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        raw_limit = request.query_params.get("limit", "50")
        return JSONResponse({"runs": _store().list_runs(limit=int(raw_limit))})
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def overview(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        raw_limit = request.query_params.get("limit", "50")
        return JSONResponse(_store().overview(limit=int(raw_limit)))
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def deep_quality(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        result = _store().run_deep_quality(request.path_params["run_id"], actor=actor)
        return JSONResponse(result, status_code=202)
    except FileNotFoundError:
        return JSONResponse({"error": "run not found"}, status_code=404)
    except (TypeError, ValueError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def standardize_run(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        result = _store().create_standardization_plan(
            request.path_params["run_id"],
            actor=actor,
            allow_review=bool(body.get("allow_review", False)),
        )
        return JSONResponse(result, status_code=202)
    except FileNotFoundError:
        return JSONResponse({"error": "run not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def diagnostics(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        archive = _store().export_diagnostics(request.path_params["run_id"])
        return FileResponse(archive, filename=archive.name, media_type="application/zip")
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


async def contract_catalog(request: Request):
    """Expose the active contract evidence for the offline admin panel."""
    _, error = _auth(request)
    if error:
        return error
    # Prefer the versioned Ningxia baseline; a supplied workbook is also a
    # valid runtime baseline and is checked per dataset at ingest time.
    configured = os.environ.get("GDA_STANDARD_CONTRACTS", "").strip()
    if not configured:
        configured = os.environ.get("GDA_STANDARD_CONTRACT_XLSX", "").strip()
    if not configured:
        return JSONResponse(
            {
                "status": "not_configured",
                "authority": "default_alias",
                "contracts": {},
            }
        )
    try:
        from ..standard_contracts import load_contract_catalog

        catalog = load_contract_catalog(configured)
        return JSONResponse(catalog)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": str(exc), "source": configured}, status_code=422)


async def execute_standardization(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        result = _store().execute_standardization_plan(
            request.path_params["plan_id"],
            actor=actor,
            vector_format=body.get("vector_format"),
        )
        return JSONResponse(result, status_code=200 if result.get("status") == "succeeded" else 409)
    except FileNotFoundError:
        return JSONResponse({"error": "standardization plan not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def ontology_bind(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        result = _store().create_ontology_binding(
            request.path_params["plan_id"],
            actor=actor,
            ontology_version=body.get("ontology_version"),
            binding_mode=str(body.get("binding_mode") or "production"),
        )
        return JSONResponse(result, status_code=200)
    except FileNotFoundError:
        return JSONResponse(
            {"error": "standardization materialization not found"}, status_code=404
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def semantic_project(request: Request):
    """Build the file-backed DLTB semantic projection after materialization."""

    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        from ..dltb_vertical_demo import DLTBVerticalDemo

        store = _store()
        result = DLTBVerticalDemo(store).build_projection(
            request.path_params["plan_id"],
            actor=actor,
            mode=str(body.get("mode") or "rehearsal"),
            preview_limit=int(body.get("preview_limit") or 500),
            publish_postgis=bool(body.get("publish_postgis", True)),
            postgis_table_name=str(
                body.get("postgis_table_name") or "land_parcel_current"
            ),
        )
        return JSONResponse(result, status_code=200)
    except FileNotFoundError:
        return JSONResponse({"error": "DLTB materialization not found"}, status_code=404)
    except (TypeError, ValueError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


def _projection_path(store, projection_id: str):
    import re

    if not re.fullmatch(r"[a-f0-9-]{16,64}", projection_id):
        raise ValueError("invalid projection id")
    path = store.root / "semantic_products" / projection_id / "semantic_projection.json"
    if not path.exists():
        raise FileNotFoundError(projection_id)
    return path


async def semantic_projection_detail(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        from ..dltb_vertical_demo import DLTBVerticalDemo

        projection = DLTBVerticalDemo.load_projection(
            _projection_path(_store(), request.path_params["projection_id"])
        )
        return JSONResponse({"status": "succeeded", "projection": projection})
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


async def semantic_catalog(request: Request):
    _, error = _auth(request)
    if error:
        return error
    store = _store()
    path = store.root / "semantic_products" / "catalog.json"
    if not path.exists():
        return JSONResponse({"schema": "gda.offline-semantic-catalog.v1", "sources": []})
    try:
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def semantic_query(request: Request):
    actor, error = _auth(request)
    if error:
        return error
    try:
        body = await request.json()
        projection_id = str(body.get("projection_id") or "")
        question = str(body.get("question") or "").strip()
        if not question:
            return JSONResponse({"error": "question is required"}, status_code=400)
        execution_engine = str(body.get("execution_engine") or "postgis")
        from ..dltb_multi_engine_query import query_dltb

        result = await asyncio.to_thread(
            query_dltb,
            _projection_path(_store(), projection_id),
            question,
            execution_engine=execution_engine,
            limit=int(body.get("limit") or 100),
        )
        result["actor"] = actor
        return JSONResponse(result)
    except FileNotFoundError:
        return JSONResponse({"error": "semantic projection not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except LLMServiceError as exc:
        return JSONResponse(
            {
                "error": str(exc),
                "code": "local_llm_unavailable",
                "fallback_used": False,
            },
            status_code=503,
        )
    except (TypeError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


def get_offline_ingest_routes() -> list[Route]:
    return [
        Route("/api/offline-ingest/sessions", endpoint=create_session, methods=["POST"]),
        Route(
            "/api/offline-ingest/sessions/{session_id}", endpoint=session_status, methods=["GET"]
        ),
        Route(
            "/api/offline-ingest/sessions/{session_id}/chunks/{index:int}",
            endpoint=upload_chunk,
            methods=["PUT"],
        ),
        Route(
            "/api/offline-ingest/sessions/{session_id}/finalize",
            endpoint=finalize_session,
            methods=["POST"],
        ),
        Route(
            "/api/offline-ingest/sessions/{session_id}/ingest",
            endpoint=ingest_session,
            methods=["POST"],
        ),
        Route("/api/offline-ingest/local-scan", endpoint=local_scan, methods=["POST"]),
        Route("/api/offline-ingest/overview", endpoint=overview, methods=["GET"]),
        Route("/api/offline-ingest/runs", endpoint=run_list, methods=["GET"]),
        Route("/api/offline-ingest/runs/{run_id}", endpoint=run_detail, methods=["GET"]),
        Route(
            "/api/offline-ingest/runs/{run_id}/quality",
            endpoint=deep_quality,
            methods=["POST"],
        ),
        Route(
            "/api/offline-ingest/runs/{run_id}/standardize",
            endpoint=standardize_run,
            methods=["POST"],
        ),
        Route(
            "/api/offline-ingest/runs/{run_id}/diagnostics",
            endpoint=diagnostics,
            methods=["GET"],
        ),
        Route("/api/offline-ingest/contracts", endpoint=contract_catalog, methods=["GET"]),
        Route(
            "/api/offline-ingest/standardization/{plan_id}/execute",
            endpoint=execute_standardization,
            methods=["POST"],
        ),
        Route(
            "/api/offline-ingest/standardization/{plan_id}/ontology-bind",
            endpoint=ontology_bind,
            methods=["POST"],
        ),
        Route(
            "/api/offline-ingest/standardization/{plan_id}/semantic-project",
            endpoint=semantic_project,
            methods=["POST"],
        ),
        Route(
            "/api/offline-ingest/semantic/{projection_id}",
            endpoint=semantic_projection_detail,
            methods=["GET"],
        ),
        Route(
            "/api/offline-ingest/semantic-catalog",
            endpoint=semantic_catalog,
            methods=["GET"],
        ),
        Route(
            "/api/offline-ingest/semantic-query",
            endpoint=semantic_query,
            methods=["POST"],
        ),
    ]
