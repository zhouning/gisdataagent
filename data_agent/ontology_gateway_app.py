"""Read-only ASGI gateway for ontology runtime and customer demo APIs."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from .api.ontology_demo_routes import get_ontology_demo_routes
from .api.ontology_routes import get_ontology_routes


async def health(_request):
    return JSONResponse({"status": "ok", "service": "ontology-gateway"})


app = Starlette(
    routes=[
        Route("/healthz", health, methods=["GET"]),
        *get_ontology_routes(),
        *get_ontology_demo_routes(),
    ]
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
