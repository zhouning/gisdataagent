"""HTTP handlers shared by the existing GIS Data Agent and the dev app."""

from __future__ import annotations

import os
import json
import re
from urllib.parse import quote_plus
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from .contracts import ManifestValidationError, build_preflight
from .coordinator import HydroRunAccessError, HydroRunCoordinator, HydroRunStateError
from .storage import read_json, run_dir


def _coordinator() -> HydroRunCoordinator:
    return HydroRunCoordinator()


def _optional_int_environment(name: str) -> int | None:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def hydro_source_defaults_payload() -> dict[str, Any]:
    """Return deployment-registered, credential-free customer source URIs.

    The browser never receives host filesystem paths or object-store
    credentials. Deployments register stable object URIs through environment
    configuration, so the same UI works with MinIO, S3 or NAS-backed assets.
    """

    network_uri = str(os.environ.get("HYDRO_DEFAULT_NETWORK_URI") or "").strip()
    terrain_uri = str(os.environ.get("HYDRO_DEFAULT_TERRAIN_URI") or "").strip()
    rainfall_uri = str(os.environ.get("HYDRO_DEFAULT_RAINFALL_URI") or "").strip()
    sources = {
        "network": {
            "uri": network_uri,
            "format": str(os.environ.get("HYDRO_DEFAULT_NETWORK_FORMAT") or "SWMM_INP"),
            "version": str(
                os.environ.get("HYDRO_DEFAULT_NETWORK_VERSION") or "customer-data-v1"
            ),
            "provided_by_customer": True,
            "etl_required": False,
            "registered": bool(network_uri),
            "source_uri": str(os.environ.get("HYDRO_NETWORK_SOURCE_URI") or "").strip(),
            "source_format": str(
                os.environ.get("HYDRO_NETWORK_SOURCE_FORMAT") or "FILE_GDB_ZIP"
            ),
            "source_name": str(
                os.environ.get("HYDRO_NETWORK_SOURCE_NAME")
                or "DMT_StormWater_AbuDhabi_Processed.gdb.zip"
            ),
            "size_bytes": _optional_int_environment("HYDRO_DEFAULT_NETWORK_SIZE_BYTES"),
            "sha256": str(os.environ.get("HYDRO_DEFAULT_NETWORK_SHA256") or "").strip(),
        },
        "terrain": {
            "uri": terrain_uri,
            "format": str(os.environ.get("HYDRO_DEFAULT_TERRAIN_FORMAT") or "GeoTIFF"),
            "version": str(
                os.environ.get("HYDRO_DEFAULT_TERRAIN_VERSION") or "customer-data-v1"
            ),
            "provided_by_customer": True,
            "etl_required": False,
            "registered": bool(terrain_uri),
            "source_uri": str(os.environ.get("HYDRO_TERRAIN_SOURCE_URI") or "").strip(),
            "source_format": str(os.environ.get("HYDRO_TERRAIN_SOURCE_FORMAT") or "GeoTIFF"),
            "source_name": str(
                os.environ.get("HYDRO_TERRAIN_SOURCE_NAME") or "AUH_DTM_5m_Z40.TIF"
            ),
            "size_bytes": _optional_int_environment("HYDRO_DEFAULT_TERRAIN_SIZE_BYTES"),
            "sha256": str(os.environ.get("HYDRO_DEFAULT_TERRAIN_SHA256") or "").strip(),
            "crs": str(os.environ.get("HYDRO_DEFAULT_TERRAIN_CRS") or "EPSG:32640"),
            "resolution_m": _optional_int_environment("HYDRO_DEFAULT_TERRAIN_RESOLUTION_M"),
        },
        "rainfall": {
            "uri": rainfall_uri,
            "format": str(os.environ.get("HYDRO_DEFAULT_RAINFALL_FORMAT") or "Open-Meteo JSON hourly time series"),
            "version": str(os.environ.get("HYDRO_DEFAULT_RAINFALL_VERSION") or "uae-april-2024-event-v1"),
            "provided_by_customer": False,
            "etl_required": False,
            "registered": bool(rainfall_uri),
            "source_uri": str(os.environ.get("HYDRO_RAINFALL_SOURCE_URI") or "").strip(),
            "source_format": str(os.environ.get("HYDRO_RAINFALL_SOURCE_FORMAT") or "Open-Meteo Historical API archive point product"),
            "source_name": str(os.environ.get("HYDRO_RAINFALL_SOURCE_NAME") or "openmeteo_archive_abu_dhabi_20240415_20240417.json"),
            "size_bytes": _optional_int_environment("HYDRO_DEFAULT_RAINFALL_SIZE_BYTES"),
            "sha256": str(os.environ.get("HYDRO_DEFAULT_RAINFALL_SHA256") or "").strip(),
            "event_id": str(os.environ.get("HYDRO_RAINFALL_EVENT_ID") or "uae-april-2024-extreme-rainfall"),
            "time_standard": str(os.environ.get("HYDRO_RAINFALL_TIME_STANDARD") or "GMT"),
            "start_time": str(os.environ.get("HYDRO_RAINFALL_START_TIME") or "2024-04-15T00:00:00Z"),
            "end_time": str(os.environ.get("HYDRO_RAINFALL_END_TIME") or "2024-04-17T23:00:00Z"),
            "total_mm": float(os.environ.get("HYDRO_RAINFALL_TOTAL_MM") or "67.8"),
            "duration_minutes": _optional_int_environment("HYDRO_RAINFALL_DURATION_MINUTES") or 4_320,
            "peak_interval_mm": float(os.environ.get("HYDRO_RAINFALL_PEAK_INTERVAL_MM") or "25.9"),
            "evidence_class": str(os.environ.get("HYDRO_RAINFALL_EVIDENCE_CLASS") or "public_proxy"),
            "calibration_admitted": False,
            "diagnostic_forcing_admitted": True,
        },
    }
    return {
        "schema": "gwm.abu_dhabi_flood.hydro_source_defaults.v1",
        "dataset_version": "customer-data-v1",
        "storage_scope": "deployment_object_store",
        "sources": sources,
    }


def _area_options_from_environment(name: str) -> list[dict[str, Any]]:
    """Read deployment-provided area options without inventing geometries.

    Boundary products are deliberately injected by the deployment.  The
    local development overlay does not register synthetic administrative or
    catchment polygons, so an empty list is the truthful response until the
    customer publishes those assets.
    """

    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(decoded, dict) and decoded.get("type") == "FeatureCollection":
        options: list[dict[str, Any]] = []
        for feature in decoded.get("features") or []:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            option_id = properties.get("id") or properties.get("code") or properties.get("ID")
            name_value = properties.get("name") or properties.get("NAME") or option_id
            if option_id and name_value and isinstance(feature.get("geometry"), dict) and feature["geometry"].get("type") in {"Polygon", "MultiPolygon"}:
                options.append({
                    "id": str(option_id),
                    "name": str(name_value),
                    "geometry": feature["geometry"],
                    "properties": properties,
                })
        return options
    if isinstance(decoded, list):
        options = []
        for item in decoded:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            geometry = item.get("geometry")
            if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                continue
            options.append({
                **item,
                "id": str(item["id"]),
                "name": str(item.get("name") or item["id"]),
            })
    return options


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _qualified_identifier(value: str, default_schema: str = "public") -> sql.Composed:
    """Build a safe schema-qualified identifier from deployment configuration."""

    parts = str(value or "").strip().split(".")
    if len(parts) == 1:
        parts.insert(0, default_schema)
    if len(parts) != 2 or not all(_SAFE_IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError("invalid configured area table")
    return sql.SQL(".").join(sql.Identifier(part) for part in parts)


def _area_database_url() -> str:
    # A separate connection is intentional: the customer source database is
    # not the GIS Data Agent control database and must never be inferred from
    # DATABASE_URL.  The URL is injected by the deployment/secret manager.
    configured_url = str(
        os.environ.get("HYDRO_AREA_DATABASE_URL")
        or os.environ.get("HYDRO_ADMINISTRATIVE_DATABASE_URL")
        or ""
    ).strip()
    if configured_url:
        return configured_url
    host = str(os.environ.get("HYDRO_AREA_DATABASE_HOST") or "").strip()
    user = str(os.environ.get("HYDRO_AREA_DATABASE_USER") or "").strip()
    password = str(os.environ.get("HYDRO_AREA_DATABASE_PASSWORD") or "")
    database = str(os.environ.get("HYDRO_AREA_DATABASE_NAME") or "liveability_data_20260730").strip()
    port = str(os.environ.get("HYDRO_AREA_DATABASE_PORT") or "5443").strip()
    if not host or not user or not password or not database:
        return ""
    return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"


def _area_options_from_database(kind: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read real boundary features from the customer PostGIS source.

    This path is deliberately opt-in and fail-closed.  If the customer
    database is not configured or reachable, no synthetic options are
    returned; the response tells the UI that the source is unavailable.
    """

    database_url = _area_database_url()
    if not database_url:
        host = str(os.environ.get("HYDRO_AREA_DATABASE_HOST") or "").strip()
        if host:
            port = str(os.environ.get("HYDRO_AREA_DATABASE_PORT") or "5443").strip()
            database = str(os.environ.get("HYDRO_AREA_DATABASE_NAME") or "liveability_data_20260730").strip()
            return [], {"status": "credentials_not_registered", "uri": f"postgresql://{host}:{port}/{database}", "count": 0}
        return [], {"status": "not_registered", "uri": "", "count": 0}

    prefix = "HYDRO_ADMINISTRATIVE" if kind == "administrative_units" else "HYDRO_CATCHMENT"
    table = os.environ.get(f"{prefix}_TABLE") or (
        "public.udm_district" if kind == "administrative_units" else ""
    )
    if not table:
        return [], {"status": "not_registered", "uri": "", "count": 0}
    id_column = os.environ.get(f"{prefix}_ID_COLUMN") or (
        "objectid" if kind == "administrative_units" else "catchment_id"
    )
    name_column = os.environ.get(f"{prefix}_NAME_COLUMN") or (
        "nameenglish" if kind == "administrative_units" else "name"
    )
    geometry_column = os.environ.get(f"{prefix}_GEOMETRY_COLUMN") or "shape"
    limit_raw = os.environ.get(f"{prefix}_LIMIT") or "5000"
    try:
        limit = max(1, min(int(limit_raw), 20000))
    except ValueError:
        limit = 5000
    if not _SAFE_IDENTIFIER.fullmatch(str(geometry_column)):
        return [], {"status": "configuration_error", "uri": "", "count": 0}
    try:
        query = sql.SQL(
            "SELECT to_jsonb(area_row), "
            "ST_AsGeoJSON(ST_Transform(area_row.{geom_col}, 4326)) "
            "FROM {table} AS area_row WHERE area_row.{geom_col} IS NOT NULL "
            "AND GeometryType(area_row.{geom_col}) IN ('POLYGON', 'MULTIPOLYGON') "
            "LIMIT %s"
        ).format(
            geom_col=sql.Identifier(geometry_column),
            table=_qualified_identifier(table),
        )
        with psycopg2.connect(database_url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()
        options = []
        for attributes, geometry_json in rows:
            if not isinstance(attributes, dict) or not geometry_json:
                continue
            try:
                geometry = json.loads(geometry_json) if isinstance(geometry_json, str) else geometry_json
            except (TypeError, json.JSONDecodeError):
                continue
            if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                continue
            option_id = attributes.get(id_column) or attributes.get("id") or attributes.get("objectid") or attributes.get("gid")
            option_name = attributes.get(name_column) or attributes.get("name") or attributes.get("nameenglish") or option_id
            if not option_id:
                continue
            options.append({"id": str(option_id), "name": str(option_name or option_id), "geometry": geometry})
        return options, {
            "status": "ready" if options else "empty",
            "uri": f"postgresql://customer-source/{table}",
            "count": len(options),
            "table": table,
        }
    except Exception as error:
        # Do not put DSNs, usernames or driver diagnostics in a browser
        # response.  The pod log contains the detailed exception.
        print(f"[hydro-area] {kind} source unavailable: {type(error).__name__}: {error}")
        return [], {
            "status": "unavailable",
            "uri": f"postgresql://customer-source/{table}",
            "count": 0,
            "error_code": type(error).__name__,
            "table": table,
        }
def hydro_area_options_payload() -> dict[str, Any]:
    """Return real administrative/catchment choices registered by a deployment."""

    administrative = _area_options_from_environment("HYDRO_ADMINISTRATIVE_OPTIONS_JSON")
    catchments = _area_options_from_environment("HYDRO_CATCHMENT_OPTIONS_JSON")
    administrative_source = {"status": "ready" if administrative else "not_registered", "uri": str(os.environ.get("HYDRO_ADMINISTRATIVE_BOUNDARY_URI") or "").strip(), "count": len(administrative)}
    catchment_source = {"status": "ready" if catchments else "not_registered", "uri": str(os.environ.get("HYDRO_CATCHMENT_BOUNDARY_URI") or "").strip(), "count": len(catchments)}
    if not administrative:
        administrative, administrative_source = _area_options_from_database("administrative_units")
    if not catchments:
        catchments, catchment_source = _area_options_from_database("catchments")
    return {
        "schema": "gwm.abu_dhabi_flood.hydro_area_options.v1",
        "crs": "EPSG:4326",
        "administrative_units": administrative,
        "catchments": catchments,
        "sources": {
            "administrative_units": administrative_source,
            "catchments": catchment_source,
        },
        "freehand": {"status": "ready"},
    }


async def get_hydro_source_defaults(request: Request) -> JSONResponse:
    del request
    return JSONResponse(hydro_source_defaults_payload())


async def get_hydro_area_options(request: Request) -> JSONResponse:
    del request
    return JSONResponse(hydro_area_options_payload())


async def create_hydro_run(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        response = _coordinator().submit(payload)
        return JSONResponse(response, status_code=202)
    except ManifestValidationError as error:
        return JSONResponse({"error": "manifest_invalid", "issues": error.issues}, status_code=422)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_submit_failed", "detail": str(error)[:500]}, status_code=503
        )


async def preflight_hydro_run(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        return JSONResponse(build_preflight(payload))
    except ManifestValidationError as error:
        return JSONResponse({"error": "manifest_invalid", "issues": error.issues}, status_code=422)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_preflight_failed", "detail": str(error)[:500]}, status_code=503
        )


async def get_hydro_run(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        return JSONResponse(_coordinator().status(run_id))
    except (FileNotFoundError, ValueError):
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except HydroRunAccessError:
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except HydroRunStateError:
        return JSONResponse({"error": "hydro_run_state_invalid"}, status_code=409)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_status_failed", "detail": str(error)[:500]}, status_code=503
        )


async def cancel_hydro_run(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        return JSONResponse(_coordinator().cancel(run_id), status_code=202)
    except (FileNotFoundError, ValueError):
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except HydroRunAccessError:
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except HydroRunStateError as error:
        return JSONResponse({"error": "hydro_run_state_invalid", "detail": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_cancel_failed", "detail": str(error)[:500]}, status_code=503
        )


async def get_hydro_result(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        coordinator = _coordinator()
        coordinator.assert_access(run_id)
        coordinator.assert_integrity(run_id)
        result = read_json(run_dir(run_id, coordinator.root) / "results" / "result.json")
    except (FileNotFoundError, ValueError, OSError):
        return JSONResponse({"error": "hydro_result_not_ready"}, status_code=404)
    except HydroRunAccessError:
        return JSONResponse({"error": "hydro_result_not_ready"}, status_code=404)
    except HydroRunStateError:
        return JSONResponse({"error": "hydro_result_not_ready"}, status_code=404)
    return JSONResponse(result)


async def get_hydro_logs(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        return JSONResponse(_coordinator().logs(run_id))
    except (FileNotFoundError, ValueError):
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except HydroRunAccessError:
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_logs_failed", "detail": str(error)[:500]}, status_code=503
        )


async def get_hydro_map(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    requested = str(request.query_params.get("layer") or "")
    try:
        coordinator = _coordinator()
        coordinator.assert_access(run_id)
        coordinator.assert_integrity(run_id)
    except (FileNotFoundError, ValueError):
        return JSONResponse({"error": "hydro_map_not_ready"}, status_code=404)
    except HydroRunAccessError:
        return JSONResponse({"error": "hydro_map_not_ready"}, status_code=404)
    except HydroRunStateError:
        return JSONResponse({"error": "hydro_map_not_ready"}, status_code=404)
    directory = run_dir(run_id, coordinator.root) / "results"
    candidates = {
        "one_d": directory / "one_d" / "network.geojson",
        "two_d": directory / "two_d" / "depth_points.geojson",
        "coupled": directory / "coupled" / "maximum_depth_wgs84.geojson",
    }
    path = (
        candidates.get(requested)
        if requested
        else next((candidate for candidate in candidates.values() if candidate.exists()), None)
    )
    if path is None or not path.exists():
        return JSONResponse({"error": "hydro_map_not_ready"}, status_code=404)
    try:
        return JSONResponse(read_json(path))
    except (OSError, ValueError, TypeError):
        return JSONResponse({"error": "hydro_map_not_ready"}, status_code=404)


def hydro_routes(*, authenticated: bool = False) -> list[Any]:
    from starlette.routing import Route

    if not authenticated:
        return [
            Route(
                "/api/abu-dhabi/flood/hydro-runs/source-defaults",
                get_hydro_source_defaults,
                methods=["GET"],
            ),
            Route(
                "/api/abu-dhabi/flood/hydro-runs/area-options",
                get_hydro_area_options,
                methods=["GET"],
            ),
            Route(
                "/api/abu-dhabi/flood/hydro-runs/preflight",
                preflight_hydro_run,
                methods=["POST"],
            ),
            Route("/api/abu-dhabi/flood/hydro-runs", create_hydro_run, methods=["POST"]),
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}", get_hydro_run, methods=["GET"]),
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}", cancel_hydro_run, methods=["DELETE"]),
            Route(
                "/api/abu-dhabi/flood/hydro-runs/{run_id}/result", get_hydro_result, methods=["GET"]
            ),
            Route(
                "/api/abu-dhabi/flood/hydro-runs/{run_id}/logs",
                get_hydro_logs,
                methods=["GET"],
            ),
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}/map", get_hydro_map, methods=["GET"]),
        ]
    return []


WORKBENCH_HTML = Path(__file__).with_name("workbench.html").read_text(encoding="utf-8")


async def workbench_page(request: Request) -> HTMLResponse:
    return HTMLResponse(WORKBENCH_HTML)
