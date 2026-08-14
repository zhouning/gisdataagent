"""Authenticated, budgeted Ontology Semantic Query Gateway routes."""

from __future__ import annotations

import logging
import mimetypes

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from ..ontology import get_ontology_service
from ..ontology.okf_bundle import resolve_okf_resource, validate_ontology_okf_bundle
from ..ontology.query_contracts import OntologyQueryPlan
from ..ontology.registry import list_ontology_profiles
from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.ontology_routes")


def _authenticate(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return user, None


def _int_param(request: Request, name: str, default: int) -> int:
    value = request.query_params.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _service(request: Request):
    """Resolve the requested ontology, keeping the legacy path on NR."""
    ontology_key = request.path_params.get("ontology_key")
    return get_ontology_service(ontology_key) if ontology_key else get_ontology_service()


async def ontologies_list(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    return JSONResponse({"items": [profile.public_dict() for profile in list_ontology_profiles()]})


async def ontology_status(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        return JSONResponse(_service(request).status())
    except Exception as exc:
        logger.exception("ontology status failed")
        return JSONResponse({"available": False, "error": str(exc)}, status_code=503)


async def ontology_versions(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        return JSONResponse({"items": _service(request).versions()})
    except Exception as exc:
        logger.exception("ontology versions failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_domains(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        return JSONResponse({"items": _service(request).domains()})
    except Exception as exc:
        logger.exception("ontology domains failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_concepts(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        kinds = {
            value.strip()
            for value in request.query_params.get("kinds", "").split(",")
            if value.strip()
        }
        payload = _service(request).search_concepts(
            query=request.query_params.get("q", "").strip(),
            domain_id=request.query_params.get("domain_id") or None,
            kinds=kinds or None,
            source_system=request.query_params.get("source_system") or None,
            offset=_int_param(request, "offset", 0),
            limit=_int_param(request, "limit", 50),
        )
        return JSONResponse(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("ontology concept search failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_concept(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    concept_id = request.query_params.get("concept_id", "").strip()
    if not concept_id:
        return JSONResponse({"error": "concept_id is required"}, status_code=400)
    try:
        payload = _service(request).get_concept(concept_id)
        if payload is None:
            return JSONResponse({"error": "ontology concept not found"}, status_code=404)
        return JSONResponse(payload)
    except Exception as exc:
        logger.exception("ontology concept detail failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_properties(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    concept_id = request.query_params.get("concept_id", "").strip()
    if not concept_id:
        return JSONResponse({"error": "concept_id is required"}, status_code=400)
    try:
        return JSONResponse(_service(request).get_properties(
            concept_id,
            offset=_int_param(request, "offset", 0),
            limit=_int_param(request, "limit", 100),
            include_effective=request.query_params.get("include_effective", "false").lower()
            in {"1", "true", "yes"},
        ))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("ontology properties failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_relations(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    concept_id = request.query_params.get("concept_id", "").strip()
    if not concept_id:
        return JSONResponse({"error": "concept_id is required"}, status_code=400)
    try:
        return JSONResponse(_service(request).get_relations(
            concept_id,
            direction=request.query_params.get("direction", "both"),
            limit=_int_param(request, "limit", 200),
        ))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("ontology relations failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_graph(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        return JSONResponse(_service(request).get_graph(
            root_id=request.query_params.get("root_id") or None,
            domain_id=request.query_params.get("domain_id") or None,
            depth=_int_param(request, "depth", 1),
            limit=_int_param(request, "limit", 250),
            include_mappings=request.query_params.get("include_mappings", "true").lower()
            in {"1", "true", "yes"},
        ))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("ontology graph failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_mappings(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        return JSONResponse(_service(request).get_mappings(
            status=request.query_params.get("status") or None,
            domain_id=request.query_params.get("domain_id") or None,
            offset=_int_param(request, "offset", 0),
            limit=_int_param(request, "limit", 100),
        ))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("ontology mappings failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_validation(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        return JSONResponse(_service(request).validation())
    except Exception as exc:
        logger.exception("ontology validation failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_align(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    try:
        body = await request.json()
        fields = body.get("fields")
        if not isinstance(fields, list) or not all(isinstance(field, dict) for field in fields):
            raise ValueError("fields must be an array of objects")
        return JSONResponse(_service(request).align_fields(
            fields,
            domain_id=str(body.get("domain_id") or "").strip() or None,
        ))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("ontology alignment failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_query(request: Request):
    """Execute a closed ontology query plan; arbitrary SQL/SPARQL is rejected."""
    _, error = _authenticate(request)
    if error:
        return error
    try:
        body = await request.json()
        plan = OntologyQueryPlan.model_validate(body)
        return JSONResponse(_service(request).execute_query(plan))
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("ontology typed query failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_okf(request: Request):
    """Serve one authenticated resource from the official OKF v0.2 bundle."""
    _, error = _authenticate(request)
    if error:
        return error
    if request.query_params.get("validate") in {"1", "true", "yes"}:
        return JSONResponse(validate_ontology_okf_bundle())
    try:
        path = resolve_okf_resource(request.query_params.get("path", "index.md"))
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".md":
            media_type = "text/markdown; charset=utf-8"
        return FileResponse(path, media_type=media_type)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except KeyError:
        return JSONResponse({"error": "OKF bundle resource not found"}, status_code=404)
    except Exception as exc:
        logger.exception("ontology OKF resource failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


async def ontology_export(request: Request):
    _, error = _authenticate(request)
    if error:
        return error
    export_format = request.path_params.get("export_format", "")
    try:
        path, media_type, filename = _service(request).export_path(export_format)
        return FileResponse(path, media_type=media_type, filename=filename)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except KeyError:
        return JSONResponse({"error": "ontology export is unavailable"}, status_code=404)
    except Exception as exc:
        logger.exception("ontology export failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


def get_ontology_routes() -> list[Route]:
    legacy = [
        Route("/api/ontology/status", ontology_status, methods=["GET"]),
        Route("/api/ontology/versions", ontology_versions, methods=["GET"]),
        Route("/api/ontology/domains", ontology_domains, methods=["GET"]),
        Route("/api/ontology/concepts", ontology_concepts, methods=["GET"]),
        Route("/api/ontology/concept", ontology_concept, methods=["GET"]),
        Route("/api/ontology/properties", ontology_properties, methods=["GET"]),
        Route("/api/ontology/relations", ontology_relations, methods=["GET"]),
        Route("/api/ontology/graph", ontology_graph, methods=["GET"]),
        Route("/api/ontology/mappings", ontology_mappings, methods=["GET"]),
        Route("/api/ontology/validation", ontology_validation, methods=["GET"]),
        Route("/api/ontology/align", ontology_align, methods=["POST"]),
        Route("/api/ontology/query", ontology_query, methods=["POST"]),
        Route("/api/ontology/okf", ontology_okf, methods=["GET"]),
        Route("/api/ontology/export/{export_format}", ontology_export, methods=["GET"]),
    ]
    scoped_prefix = "/api/ontologies/{ontology_key}"
    scoped = [
        Route(f"{scoped_prefix}/status", ontology_status, methods=["GET"]),
        Route(f"{scoped_prefix}/versions", ontology_versions, methods=["GET"]),
        Route(f"{scoped_prefix}/domains", ontology_domains, methods=["GET"]),
        Route(f"{scoped_prefix}/concepts", ontology_concepts, methods=["GET"]),
        Route(f"{scoped_prefix}/concept", ontology_concept, methods=["GET"]),
        Route(f"{scoped_prefix}/properties", ontology_properties, methods=["GET"]),
        Route(f"{scoped_prefix}/relations", ontology_relations, methods=["GET"]),
        Route(f"{scoped_prefix}/graph", ontology_graph, methods=["GET"]),
        Route(f"{scoped_prefix}/mappings", ontology_mappings, methods=["GET"]),
        Route(f"{scoped_prefix}/validation", ontology_validation, methods=["GET"]),
        Route(f"{scoped_prefix}/align", ontology_align, methods=["POST"]),
        Route(f"{scoped_prefix}/query", ontology_query, methods=["POST"]),
        Route(f"{scoped_prefix}/export/{{export_format}}", ontology_export, methods=["GET"]),
    ]
    return [Route("/api/ontologies", ontologies_list, methods=["GET"]), *legacy, *scoped]
