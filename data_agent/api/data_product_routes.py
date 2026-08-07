"""Public discovery and governed operations for published data products."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from ..data_product_registry import (
    DataProductConflictError,
    DataProductNotFoundError,
    DataProductPromotionImpactError,
    DataProductRegistry,
    DataProductRegistryError,
)
from ..db_engine import get_engine
from ..platform_gateway import PlatformGateway
from .platform_gateway_routes import GatewayPrincipal, _principal

PUBLIC_TENANT = os.environ.get("GDA_PUBLIC_DATA_PRODUCT_TENANT", "local-dev")
STORAGE_ROOT = Path(
    os.environ.get(
        "GDA_DATA_PRODUCT_STORAGE_ROOT",
        "/app/data_agent/uploads/data_products",
    )
)
PAGE_PATH = Path(__file__).resolve().parents[1] / "data_products/product_page.html"
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


def _registry() -> DataProductRegistry:
    return DataProductRegistry()


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"data": None, "error": {"code": code, "message": message}},
        status_code=status_code,
    )


def _success(data: Any, **extra: Any) -> JSONResponse:
    return JSONResponse({"data": data, "error": None, **extra})


async def list_data_products(request: Request) -> JSONResponse:
    try:
        items = await asyncio.to_thread(
            _registry().list_products, PUBLIC_TENANT, public_only=True
        )
        return _success(items, total=len(items))
    except DataProductRegistryError:
        return _error(503, "data_product_registry_unavailable", "Catalog is unavailable")


async def get_data_product(request: Request) -> JSONResponse:
    try:
        product = await asyncio.to_thread(
            _registry().get_product,
            PUBLIC_TENANT,
            request.path_params["product_slug"],
        )
        if product["governance_ref"].get("visibility") != "public":
            return _error(404, "data_product_not_found", "Data product was not found")
        product["links"] = _product_links(product["product_slug"])
        return _success(product)
    except DataProductNotFoundError:
        return _error(404, "data_product_not_found", "Data product was not found")
    except DataProductRegistryError:
        return _error(503, "data_product_registry_unavailable", "Catalog is unavailable")


async def get_data_product_version(request: Request) -> JSONResponse:
    try:
        version = await asyncio.to_thread(
            _registry().get_version,
            PUBLIC_TENANT,
            request.path_params["product_slug"],
            request.path_params["version_key"],
        )
        return _success(version)
    except DataProductNotFoundError:
        return _error(404, "data_product_version_not_found", "Version was not found")
    except DataProductRegistryError:
        return _error(503, "data_product_registry_unavailable", "Catalog is unavailable")


async def get_data_product_lineage(request: Request) -> JSONResponse:
    try:
        lineage = await asyncio.to_thread(
            _registry().lineage,
            PUBLIC_TENANT,
            request.path_params["product_slug"],
        )
        return _success(lineage)
    except DataProductNotFoundError:
        return _error(404, "data_product_not_found", "Data product was not found")
    except DataProductRegistryError:
        return _error(503, "data_product_registry_unavailable", "Lineage is unavailable")


async def get_data_product_stac(request: Request) -> JSONResponse:
    try:
        version = await asyncio.to_thread(
            _registry().get_version,
            PUBLIC_TENANT,
            request.path_params["product_slug"],
        )
        distribution = _stac_distribution(version["distribution_manifest"])
        artifact = await asyncio.to_thread(
            PlatformGateway().get_artifact,
            PUBLIC_TENANT,
            UUID(distribution["artifact_id"]),
        )
        item = await asyncio.to_thread(_read_s3_json_artifact, artifact)
        return JSONResponse(item, media_type="application/geo+json")
    except DataProductNotFoundError:
        return _error(404, "data_product_not_found", "Data product was not found")
    except Exception:
        return _error(503, "data_product_stac_unavailable", "STAC item is unavailable")


async def get_data_product_features(request: Request) -> JSONResponse:
    try:
        limit = _bounded_int(request.query_params.get("limit"), 5000, 1, 20000)
        simplify = _bounded_float(request.query_params.get("simplify"), 0.002, 0.0, 0.1)
        bbox = _bbox(request.query_params.get("bbox"))
        version = await asyncio.to_thread(
            _registry().get_version,
            PUBLIC_TENANT,
            request.path_params["product_slug"],
        )
        projection = _postgis_projection(version["distribution_manifest"])
        feature_collection = await asyncio.to_thread(
            _read_features,
            projection,
            limit=limit,
            simplify=simplify,
            bbox=bbox,
        )
        feature_collection["data_product_version"] = version["version_key"]
        feature_collection["is_current"] = version["is_current"]
        return JSONResponse(feature_collection)
    except ValueError as exc:
        return _error(400, "invalid_query", str(exc))
    except DataProductNotFoundError:
        return _error(404, "data_product_not_found", "Data product was not found")
    except (DataProductRegistryError, RuntimeError):
        return _error(503, "data_product_projection_unavailable", "Map data is unavailable")


async def download_data_product(request: Request):
    try:
        version = await asyncio.to_thread(
            _registry().get_version,
            PUBLIC_TENANT,
            request.path_params["product_slug"],
        )
        distribution = _file_distribution(version["distribution_manifest"])
        artifact = await asyncio.to_thread(
            PlatformGateway().get_artifact,
            PUBLIC_TENANT,
            UUID(distribution["artifact_id"]),
        )
        _validate_distribution_artifact(distribution, artifact)
        parts = urlsplit(artifact.storage_uri)
        filename = f"{request.path_params['product_slug']}-{version['version_key']}.geojson"
        if parts.scheme == "s3":
            payload = await asyncio.to_thread(
                _read_s3_binary_artifact,
                artifact,
            )
            return Response(
                payload,
                media_type=artifact.media_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        if parts.scheme != "file":
            raise RuntimeError("product artifact is not downloadable")
        path = Path(parts.path).resolve(strict=True)
        root = STORAGE_ROOT.resolve(strict=True)
        if not path.is_relative_to(root):
            raise RuntimeError("product artifact is outside the storage root")
        return FileResponse(
            path,
            media_type=artifact.media_type,
            filename=filename,
        )
    except DataProductNotFoundError:
        return _error(404, "data_product_not_found", "Data product was not found")
    except Exception:
        return _error(503, "data_product_download_unavailable", "Download is unavailable")


async def rollback_data_product(request: Request) -> JSONResponse:
    principal = _principal(request)
    if not isinstance(principal, GatewayPrincipal):
        return principal
    try:
        body = await request.json()
        target = str(body.get("target_version") or "").strip()
        reason = str(body.get("reason") or "").strip()
        idempotency_key = str(body.get("idempotency_key") or "").strip()
        result = await asyncio.to_thread(
            _registry().rollback,
            principal.tenant_id,
            request.path_params["product_slug"],
            target,
            actor_subject=principal.actor_ref,
            reason=reason,
            idempotency_key=idempotency_key,
        )
        return _success(result)
    except (ValueError, json.JSONDecodeError) as exc:
        return _error(400, "invalid_rollback", str(exc))
    except DataProductNotFoundError:
        return _error(404, "data_product_version_not_found", "Rollback target was not found")
    except DataProductConflictError as exc:
        return _error(409, "data_product_version_conflict", str(exc))
    except DataProductRegistryError:
        return _error(503, "data_product_registry_unavailable", "Rollback is unavailable")


async def preview_data_product_promotion_impact(request: Request) -> JSONResponse:
    principal = _principal(request)
    if not isinstance(principal, GatewayPrincipal):
        return principal
    target = str(request.query_params.get("target_version") or "").strip()
    if not target:
        return _error(400, "invalid_promotion", "target_version is required")
    try:
        result = await asyncio.to_thread(
            _registry().preview_promotion_impact,
            principal.tenant_id,
            request.path_params["product_slug"],
            target,
        )
        return _success(result)
    except DataProductNotFoundError:
        return _error(
            404,
            "data_product_version_not_found",
            "Promotion target was not found",
        )
    except DataProductConflictError as exc:
        return _error(409, "data_product_version_conflict", str(exc))
    except DataProductRegistryError:
        return _error(
            503,
            "data_product_registry_unavailable",
            "Promotion impact is unavailable",
        )


async def promote_data_product(request: Request) -> JSONResponse:
    principal = _principal(request)
    if not isinstance(principal, GatewayPrincipal):
        return principal
    try:
        body = await request.json()
        target = str(body.get("target_version") or "").strip()
        reason = str(body.get("reason") or "").strip()
        idempotency_key = str(body.get("idempotency_key") or "").strip()
        impact_acknowledgement = str(
            body.get("impact_acknowledgement") or ""
        ).strip()
        result = await asyncio.to_thread(
            _registry().promote,
            principal.tenant_id,
            request.path_params["product_slug"],
            target,
            actor_subject=principal.actor_ref,
            reason=reason,
            idempotency_key=idempotency_key,
            impact_acknowledgement=impact_acknowledgement,
        )
        return _success(result)
    except (ValueError, json.JSONDecodeError) as exc:
        return _error(400, "invalid_promotion", str(exc))
    except DataProductNotFoundError:
        return _error(404, "data_product_version_not_found", "Promotion target was not found")
    except DataProductPromotionImpactError as exc:
        return JSONResponse(
            {
                "data": exc.impact,
                "error": {
                    "code": "promotion_impact_acknowledgement_required",
                    "message": str(exc),
                },
            },
            status_code=409,
        )
    except DataProductConflictError as exc:
        return _error(409, "data_product_version_conflict", str(exc))
    except DataProductRegistryError:
        return _error(503, "data_product_registry_unavailable", "Promotion is unavailable")


async def data_product_page(request: Request) -> HTMLResponse:
    slug = request.path_params["product_slug"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,127}", slug):
        return HTMLResponse("Not found", status_code=404)
    html = PAGE_PATH.read_text(encoding="utf-8").replace("__PRODUCT_SLUG__", slug)
    return HTMLResponse(html)


def _product_links(slug: str) -> dict[str, str]:
    base = f"/api/data-products/{slug}"
    return {
        "self": base,
        "map": f"/data-products/{slug}",
        "features": f"{base}/features",
        "download": f"{base}/download",
        "lineage": f"{base}/lineage",
        "stac": f"{base}/stac",
    }


def _postgis_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    for item in manifest.get("formats", []):
        if item.get("kind") == "PostGIS":
            schema = str(item.get("schema") or "")
            table = str(item.get("table") or "")
            if not _IDENTIFIER_RE.fullmatch(schema) or not _IDENTIFIER_RE.fullmatch(table):
                raise RuntimeError("invalid PostGIS projection identifier")
            return item
    raise RuntimeError("PostGIS projection is not published")


def _file_distribution(manifest: dict[str, Any]) -> dict[str, Any]:
    for item in manifest.get("formats", []):
        if item.get("kind") == "S3GeoJSON" and item.get("artifact_id"):
            return item
    for item in manifest.get("formats", []):
        if item.get("kind") == "GeoJSON" and item.get("artifact_id"):
            return item
    raise RuntimeError("GeoJSON distribution is not published")


def _stac_distribution(manifest: dict[str, Any]) -> dict[str, Any]:
    for item in manifest.get("formats", []):
        if item.get("kind") == "STAC" and item.get("artifact_id"):
            return item
    raise RuntimeError("STAC distribution is not published")


def _read_s3_json_artifact(artifact) -> dict[str, Any]:
    payload = _read_s3_binary_artifact(artifact)
    value = json.loads(payload)
    if not isinstance(value, dict) or value.get("type") != "Feature":
        raise RuntimeError("STAC artifact is invalid")
    return value


def _validate_distribution_artifact(distribution: dict[str, Any], artifact) -> None:
    distribution_sha256 = str(distribution.get("content_sha256") or "")
    if distribution_sha256 and distribution_sha256 != artifact.content_sha256:
        raise RuntimeError("distribution and artifact checksums disagree")
    distribution_size = distribution.get("size_bytes")
    if distribution_size is not None and int(distribution_size) != artifact.size_bytes:
        raise RuntimeError("distribution and artifact sizes disagree")


def _read_s3_binary_artifact(artifact) -> bytes:
    parts = urlsplit(artifact.storage_uri)
    if parts.scheme != "s3" or not parts.netloc or not parts.path.lstrip("/"):
        raise RuntimeError("artifact is not stored in S3")
    response = _s3_client().get_object(
        Bucket=parts.netloc,
        Key=parts.path.lstrip("/"),
    )
    content_length = int(response.get("ContentLength", -1))
    if content_length != artifact.size_bytes:
        raise RuntimeError("S3 artifact size mismatch")
    metadata_sha256 = str((response.get("Metadata") or {}).get("sha256") or "")
    if metadata_sha256 != artifact.content_sha256:
        raise RuntimeError("S3 artifact metadata checksum mismatch")
    body = response["Body"]
    try:
        payload = body.read()
    finally:
        close = getattr(body, "close", None)
        if close is not None:
            close()
    if len(payload) != artifact.size_bytes:
        raise RuntimeError("S3 artifact payload size mismatch")
    if hashlib.sha256(payload).hexdigest() != artifact.content_sha256:
        raise RuntimeError("S3 artifact checksum mismatch")
    return payload


def _s3_client():
    import boto3
    from botocore.config import Config as BotoConfig

    endpoint = os.environ.get("AWS_ENDPOINT_URL") or None
    kwargs: dict[str, Any] = {
        "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "region_name": os.environ.get("AWS_REGION", "us-east-1"),
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})
    return boto3.client("s3", **kwargs)


def _read_features(
    projection: dict[str, Any],
    *,
    limit: int,
    simplify: float,
    bbox: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL is unavailable")
    schema = projection["schema"]
    table = projection["table"]
    relation = f'"{schema}"."{table}"'
    geometry = "geometry" if simplify == 0 else "ST_SimplifyPreserveTopology(geometry, :simplify)"
    where = ""
    params: dict[str, Any] = {"limit": limit, "simplify": simplify}
    if bbox is not None:
        where = "WHERE geometry && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)"
        params.update(dict(zip(("xmin", "ymin", "xmax", "ymax"), bbox, strict=True)))
    with engine.connect() as connection:
        total = connection.execute(
            text(f"SELECT count(*) FROM {relation} {where}"), params
        ).scalar_one()
        rows = connection.execute(
            text(
                f"""
                SELECT road_id,
                       to_jsonb(source_row) - 'geometry' AS properties,
                       ST_AsGeoJSON({geometry})::jsonb AS geometry
                  FROM {relation} AS source_row
                  {where}
                 ORDER BY road_id
                 LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": row["road_id"],
                "properties": row["properties"],
                "geometry": row["geometry"],
            }
            for row in rows
        ],
        "numberMatched": int(total),
        "numberReturned": len(rows),
        "limit": limit,
        "simplify": simplify,
    }


def _bounded_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError("limit must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"limit must be between {minimum} and {maximum}")
    return value


def _bounded_float(raw: str | None, default: float, minimum: float, maximum: float) -> float:
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError("simplify must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"simplify must be between {minimum} and {maximum}")
    return value


def _bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    try:
        values = tuple(float(value) for value in raw.split(","))
    except ValueError as exc:
        raise ValueError("bbox must contain four comma-separated numbers") from exc
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("bbox must be xmin,ymin,xmax,ymax")
    return values


def get_data_product_routes() -> list[Route]:
    return [
        Route("/api/data-products", list_data_products, methods=["GET"]),
        Route("/api/data-products/{product_slug}", get_data_product, methods=["GET"]),
        Route(
            "/api/data-products/{product_slug}/versions/{version_key}",
            get_data_product_version,
            methods=["GET"],
        ),
        Route(
            "/api/data-products/{product_slug}/features",
            get_data_product_features,
            methods=["GET"],
        ),
        Route(
            "/api/data-products/{product_slug}/download",
            download_data_product,
            methods=["GET"],
        ),
        Route(
            "/api/data-products/{product_slug}/lineage",
            get_data_product_lineage,
            methods=["GET"],
        ),
        Route(
            "/api/data-products/{product_slug}/stac",
            get_data_product_stac,
            methods=["GET"],
        ),
        Route(
            "/api/data-products/{product_slug}/rollback",
            rollback_data_product,
            methods=["POST"],
        ),
        Route(
            "/api/data-products/{product_slug}/promote",
            promote_data_product,
            methods=["POST"],
        ),
        Route(
            "/api/data-products/{product_slug}/promotion-impact",
            preview_data_product_promotion_impact,
            methods=["GET"],
        ),
        Route("/data-products/{product_slug}", data_product_page, methods=["GET"]),
    ]
