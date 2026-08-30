"""Bounded, read-only ontology routes for the standalone CIM viewer."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..ontology import get_ontology_service

logger = logging.getLogger("data_agent.api.public_ontology_routes")

_PUBLIC_HEADERS = {
    "Cache-Control": "private, max-age=60",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}


def _response(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code, headers=_PUBLIC_HEADERS)


def _bounded_int(
    request: Request,
    name: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int,
) -> int:
    raw_value = request.query_params.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


async def _read_only(
    operation: str,
    loader: Callable[[], Any],
) -> JSONResponse:
    try:
        return _response(loader())
    except ValueError as exc:
        return _response({"error": str(exc)}, status_code=400)
    except KeyError:
        return _response({"error": "ontology resource not found"}, status_code=404)
    except Exception:
        logger.exception("public ontology %s failed", operation)
        return _response({"error": "ontology service unavailable"}, status_code=503)


async def public_ontology_status(request: Request) -> JSONResponse:
    def load() -> Any:
        payload = dict(get_ontology_service().status())
        # The CIM viewer needs package identity and quality metrics, not the
        # server's local filesystem layout.
        payload.pop("package_dir", None)
        return payload

    return await _read_only("status", load)


async def public_ontology_domains(request: Request) -> JSONResponse:
    return await _read_only(
        "domains",
        lambda: {"items": get_ontology_service().domains()},
    )


async def public_ontology_concepts(request: Request) -> JSONResponse:
    def load() -> Any:
        kinds = {
            value.strip()
            for value in request.query_params.get("kinds", "").split(",")
            if value.strip()
        }
        return get_ontology_service().search_concepts(
            query=request.query_params.get("q", "").strip(),
            domain_id=request.query_params.get("domain_id") or None,
            kinds=kinds or None,
            source_system=request.query_params.get("source_system") or None,
            offset=_bounded_int(request, "offset", 0, maximum=10_000),
            limit=_bounded_int(request, "limit", 50, minimum=1, maximum=100),
        )

    return await _read_only("concept search", load)


async def public_ontology_concept(request: Request) -> JSONResponse:
    concept_id = request.query_params.get("concept_id", "").strip()
    if not concept_id:
        return _response({"error": "concept_id is required"}, status_code=400)

    def load() -> Any:
        payload = get_ontology_service().get_concept(concept_id)
        if payload is None:
            raise KeyError(concept_id)
        return payload

    return await _read_only("concept detail", load)


async def public_ontology_properties(request: Request) -> JSONResponse:
    concept_id = request.query_params.get("concept_id", "").strip()
    if not concept_id:
        return _response({"error": "concept_id is required"}, status_code=400)

    return await _read_only(
        "properties",
        lambda: get_ontology_service().get_properties(
            concept_id,
            offset=_bounded_int(request, "offset", 0, maximum=10_000),
            limit=_bounded_int(request, "limit", 100, minimum=1, maximum=500),
            include_effective=request.query_params.get("include_effective", "false").lower()
            in {"1", "true", "yes"},
        ),
    )


async def public_ontology_relations(request: Request) -> JSONResponse:
    concept_id = request.query_params.get("concept_id", "").strip()
    if not concept_id:
        return _response({"error": "concept_id is required"}, status_code=400)

    return await _read_only(
        "relations",
        lambda: get_ontology_service().get_relations(
            concept_id,
            direction=request.query_params.get("direction", "both"),
            limit=_bounded_int(request, "limit", 100, minimum=1, maximum=200),
        ),
    )


async def public_ontology_graph(request: Request) -> JSONResponse:
    return await _read_only(
        "graph",
        lambda: get_ontology_service().get_graph(
            root_id=request.query_params.get("root_id") or None,
            domain_id=request.query_params.get("domain_id") or None,
            depth=_bounded_int(request, "depth", 1, minimum=1, maximum=3),
            limit=_bounded_int(request, "limit", 100, minimum=1, maximum=250),
            include_mappings=request.query_params.get("include_mappings", "true").lower()
            in {"1", "true", "yes"},
        ),
    )


async def public_ontology_mappings(request: Request) -> JSONResponse:
    return await _read_only(
        "mappings",
        lambda: get_ontology_service().get_mappings(
            status=request.query_params.get("status") or None,
            domain_id=request.query_params.get("domain_id") or None,
            offset=_bounded_int(request, "offset", 0, maximum=10_000),
            limit=_bounded_int(request, "limit", 80, minimum=1, maximum=100),
        ),
    )


async def public_ontology_validation(request: Request) -> JSONResponse:
    return await _read_only(
        "validation",
        lambda: get_ontology_service().validation(),
    )


def get_public_ontology_routes() -> list[Route]:
    """Expose only bounded GET operations required by the CIM ontology viewer."""
    prefix = "/api/public/ontology"
    return [
        Route(f"{prefix}/status", public_ontology_status, methods=["GET"]),
        Route(f"{prefix}/domains", public_ontology_domains, methods=["GET"]),
        Route(f"{prefix}/concepts", public_ontology_concepts, methods=["GET"]),
        Route(f"{prefix}/concept", public_ontology_concept, methods=["GET"]),
        Route(f"{prefix}/properties", public_ontology_properties, methods=["GET"]),
        Route(f"{prefix}/relations", public_ontology_relations, methods=["GET"]),
        Route(f"{prefix}/graph", public_ontology_graph, methods=["GET"]),
        Route(f"{prefix}/mappings", public_ontology_mappings, methods=["GET"]),
        Route(f"{prefix}/validation", public_ontology_validation, methods=["GET"]),
    ]
