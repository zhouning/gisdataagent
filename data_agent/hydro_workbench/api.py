"""HTTP handlers shared by the existing GIS Data Agent and the dev app."""

from __future__ import annotations

import os
import json
import re
import importlib.util
from urllib.parse import quote_plus, urlparse
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


def _swmm_out_parser() -> Any:
    """Load the native SWMM OUT parser without optional UWM dependencies."""

    try:
        from ..uwm.abu_dhabi_flood import swmm_out_parser

        return swmm_out_parser
    except ModuleNotFoundError:
        parser_path = Path(__file__).resolve().parents[1] / "uwm" / "abu_dhabi_flood" / "swmm_out_parser.py"
        spec = importlib.util.spec_from_file_location("hydro_swmm_out_parser", parser_path)
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _optional_int_environment(name: str) -> int | None:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _regional_pilot_catalog() -> dict[str, dict[str, Any]]:
    """Read deployment-registered, region-scoped model-ready assets.

    The catalog is intentionally supplied by the deployment rather than
    inferred from a browser path.  This keeps the UI credential-free while
    allowing a selected Catchment to switch from city defaults to a bounded
    regional pilot package.
    """

    raw = str(os.environ.get("HYDRO_REGIONAL_PILOTS_JSON") or "").strip()
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        str(region): value
        for region, value in decoded.items()
        if isinstance(region, str) and isinstance(value, dict)
    }


def hydro_source_defaults_payload(region: str | None = None) -> dict[str, Any]:
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
            "format": str(
                os.environ.get("HYDRO_DEFAULT_RAINFALL_FORMAT")
                or "April 2024 reconstructed hourly hyetograph JSON"
            ),
            "version": str(
                os.environ.get("HYDRO_DEFAULT_RAINFALL_VERSION")
                or "uae-april-2024-reconstruction-v1"
            ),
            "provided_by_customer": False,
            "etl_required": False,
            "registered": bool(rainfall_uri),
            "source_uri": str(os.environ.get("HYDRO_RAINFALL_SOURCE_URI") or "").strip(),
            "source_format": str(
                os.environ.get("HYDRO_RAINFALL_SOURCE_FORMAT")
                or "GWM April 2024 public-evidence reconstruction"
            ),
            "source_name": str(
                os.environ.get("HYDRO_RAINFALL_SOURCE_NAME")
                or "uae_april_2024_reconstructed_hyetograph.json"
            ),
            "size_bytes": _optional_int_environment("HYDRO_DEFAULT_RAINFALL_SIZE_BYTES"),
            "sha256": str(os.environ.get("HYDRO_DEFAULT_RAINFALL_SHA256") or "").strip(),
            "event_id": str(os.environ.get("HYDRO_RAINFALL_EVENT_ID") or "uae-april-2024-extreme-rainfall"),
            "time_standard": str(os.environ.get("HYDRO_RAINFALL_TIME_STANDARD") or "GST (UTC+04:00)"),
            "start_time": str(os.environ.get("HYDRO_RAINFALL_START_TIME") or "2024-04-15T20:00:00+04:00"),
            "end_time": str(os.environ.get("HYDRO_RAINFALL_END_TIME") or "2024-04-17T12:00:00+04:00"),
            "total_mm": float(os.environ.get("HYDRO_RAINFALL_TOTAL_MM") or "254.78"),
            "duration_minutes": _optional_int_environment("HYDRO_RAINFALL_DURATION_MINUTES") or 2_400,
            "peak_interval_mm": float(os.environ.get("HYDRO_RAINFALL_PEAK_INTERVAL_MM") or "30.32"),
            "interval_count": _optional_int_environment("HYDRO_RAINFALL_INTERVAL_COUNT") or 40,
            "interval_minutes": _optional_int_environment("HYDRO_RAINFALL_INTERVAL_MINUTES") or 60,
            "evidence_class": str(os.environ.get("HYDRO_RAINFALL_EVIDENCE_CLASS") or "public_reconstruction"),
            "admission": str(os.environ.get("HYDRO_RAINFALL_ADMISSION") or "prototype_sensitivity_only"),
            "calibration_admitted": False,
            "diagnostic_forcing_admitted": True,
        },
        "tide": {
            "uri": "",
            "format": "CSV/JSON time series",
            "version": "not-provided",
            "provided_by_customer": False,
            "etl_required": True,
            "registered": False,
        },
        "outfalls": {
            "uri": "",
            "format": "GeoPackage/GeoJSON",
            "version": "not-provided",
            "provided_by_customer": False,
            "etl_required": True,
            "registered": False,
        },
        "pumps": {
            "uri": "",
            "format": "CSV/GeoPackage",
            "version": "not-provided",
            "provided_by_customer": False,
            "etl_required": True,
            "registered": False,
        },
    }
    regional_pilots = _regional_pilot_catalog()
    selected_region = str(region or "").strip() or None
    regional_pilot = regional_pilots.get(selected_region or "") if selected_region else None
    if regional_pilot:
        for key in ("network", "terrain", "tide", "outfalls", "pumps"):
            override = regional_pilot.get(key)
            if isinstance(override, dict):
                sources[key] = {**sources.get(key, {}), **override, "registered": bool(override.get("uri"))}
        # Region packages do not replace the rainfall proxy unless explicitly
        # registered; retaining the event forcing makes the pilot reproducible.
        if isinstance(regional_pilot.get("rainfall"), dict):
            sources["rainfall"] = {**sources["rainfall"], **regional_pilot["rainfall"]}
    return {
        "schema": "gwm.abu_dhabi_flood.hydro_source_defaults.v1",
        "dataset_version": "customer-data-v1",
        "storage_scope": "deployment_object_store",
        "sources": sources,
        "region": selected_region,
        "regional_pilot": regional_pilot,
        "regional_pilots": {
            name: {
                "status": value.get("status", "registered"),
                "engineering_admission": value.get("engineering_admission", "diagnostic_only"),
                "catchment_count": value.get("catchment_count"),
                "dynamic_tide_available": bool(value.get("dynamic_tide_available", False)),
                "scada_available": bool(value.get("scada_available", False)),
            }
            for name, value in regional_pilots.items()
        },
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


_AREA_OBJECT_CACHE: dict[str, tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]] = {}


def _area_options_from_catalog_payload(
    decoded: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a model-ready catchment FeatureCollection and expose its QA metadata."""

    if not isinstance(decoded, dict) or decoded.get("type") != "FeatureCollection":
        return [], {"status": "invalid", "count": 0, "format": "GeoJSON"}

    options = _area_options_from_feature_collection(decoded)
    catalog_metadata = decoded.get("metadata")
    if not isinstance(catalog_metadata, dict):
        catalog_metadata = {}
    region_metadata = catalog_metadata.get("regions")
    if not isinstance(region_metadata, list):
        region_metadata = []
    attribute_statuses = {
        str(item.get("region")): str(item.get("attributes"))
        for item in region_metadata
        if isinstance(item, dict) and item.get("region") and item.get("attributes")
    }
    if attribute_statuses:
        attribute_status = "; ".join(
            f"{region} {status}" for region, status in attribute_statuses.items()
        )
    else:
        attribute_status = "not_declared"
    return options, {
        "status": "ready" if options else "empty",
        "count": len(options),
        "format": "GeoJSON",
        "attribute_status": attribute_status,
        "source_crs": str(catalog_metadata.get("source_crs") or ""),
        "source_crs_status": str(catalog_metadata.get("source_crs_status") or ""),
        "output_crs": str(catalog_metadata.get("output_crs") or "EPSG:4326"),
        "regions": region_metadata,
    }


def _area_options_from_feature_collection(decoded: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract selectable polygon options from a GeoJSON FeatureCollection."""

    options: list[dict[str, Any]] = []
    for feature in decoded.get("features") or []:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        option_id = properties.get("id") or properties.get("code") or properties.get("ID")
        name_value = properties.get("name") or properties.get("NAME") or option_id
        geometry = feature.get("geometry")
        if option_id and name_value and isinstance(geometry, dict) and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            options.append({
                "id": str(option_id),
                "name": str(name_value),
                "geometry": geometry,
                "properties": properties,
            })
    return options


def _read_json_from_object_uri(uri: str) -> dict[str, Any] | None:
    """Read a registered GeoJSON object without exposing storage credentials."""

    cached = _AREA_OBJECT_CACHE.get(uri)
    if cached is not None:
        return cached[0]
    parsed = urlparse(uri)
    try:
        if parsed.scheme == "file":
            with Path(parsed.path).open("r", encoding="utf-8") as stream:
                decoded = json.load(stream)
        elif parsed.scheme in {"s3", "minio"}:
            import boto3
            from botocore.config import Config as BotoConfig

            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
            if not bucket or not key:
                raise ValueError("object URI must include bucket and key")
            client_kwargs: dict[str, Any] = {
                "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
                "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
                "region_name": os.environ.get("AWS_REGION", "us-east-1"),
            }
            endpoint_url = str(os.environ.get("AWS_ENDPOINT_URL") or "").strip()
            if endpoint_url:
                client_kwargs["endpoint_url"] = endpoint_url
                client_kwargs["config"] = BotoConfig(s3={"addressing_style": "path"})
            response = boto3.client("s3", **client_kwargs).get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()
            decoded = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
        else:
            raise ValueError("unsupported object URI scheme")
    except Exception as error:
        print(f"[hydro-area] catchment object unavailable: {type(error).__name__}: {error}")
        return None
    if not isinstance(decoded, dict):
        return None
    options, metadata = _area_options_from_catalog_payload(decoded)
    _AREA_OBJECT_CACHE[uri] = (decoded, options, metadata)
    return decoded


def _area_options_from_object_uri(uri: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load a catchment catalog from a registered MinIO/S3/NAS URI."""

    decoded = _read_json_from_object_uri(uri)
    if decoded is None:
        return [], {
            "status": "unavailable",
            "uri": uri,
            "count": 0,
            "format": "GeoJSON",
            "error_code": "object_read_failed",
        }
    options, metadata = _area_options_from_catalog_payload(decoded)
    return options, {**metadata, "uri": uri}


def _model_region_geometry(catchments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Dissolve subcatchments into one honest model-region boundary.

    Shapely is present in the hydrodynamics runtime and produces a compact
    union.  The dependency-free fallback preserves the exact component
    polygons as a MultiPolygon instead of replacing them with a misleading
    bounding box.
    """

    geometries = [
        item.get("geometry")
        for item in catchments
        if isinstance(item.get("geometry"), dict)
        and item["geometry"].get("type") in {"Polygon", "MultiPolygon"}
    ]
    if not geometries:
        return None
    try:
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union

        dissolved = mapping(unary_union([shape(geometry) for geometry in geometries]))
        if dissolved.get("type") in {"Polygon", "MultiPolygon"}:
            return dissolved
    except Exception:
        pass
    polygons: list[Any] = []
    for geometry in geometries:
        if geometry["type"] == "Polygon":
            polygons.append(geometry.get("coordinates") or [])
        else:
            polygons.extend(geometry.get("coordinates") or [])
    return {"type": "MultiPolygon", "coordinates": polygons} if polygons else None


def _model_region_options(
    catchments: list[dict[str, Any]], regional_pilots: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expose complete solver packages, not individual runoff units, as AOIs."""

    by_region: dict[str, list[dict[str, Any]]] = {}
    for option in catchments:
        properties = option.get("properties") if isinstance(option.get("properties"), dict) else {}
        region = str(properties.get("region") or "").strip()
        if region:
            by_region.setdefault(region, []).append(option)
    options: list[dict[str, Any]] = []
    for region, package in sorted(regional_pilots.items()):
        members = by_region.get(region, [])
        geometry = _model_region_geometry(members)
        if geometry is None:
            configured = package.get("geometry")
            geometry = configured if isinstance(configured, dict) else None
        if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        options.append(
            {
                "id": region,
                "name": str(package.get("name") or region),
                "geometry": geometry,
                "properties": {
                    "region": region,
                    "selection_role": "complete_model_region",
                    "subcatchment_count": len(members)
                    or int(package.get("catchment_count") or 0),
                    "engineering_admission": package.get("engineering_admission", "diagnostic_only"),
                    "status": package.get("status", "registered"),
                },
            }
        )
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
    """Return administrative areas, model regions and subcatchment filters."""

    administrative = _area_options_from_environment("HYDRO_ADMINISTRATIVE_OPTIONS_JSON")
    catchments = _area_options_from_environment("HYDRO_CATCHMENT_OPTIONS_JSON")
    administrative_source = {"status": "ready" if administrative else "not_registered", "uri": str(os.environ.get("HYDRO_ADMINISTRATIVE_BOUNDARY_URI") or "").strip(), "count": len(administrative)}
    catchment_uri = str(os.environ.get("HYDRO_CATCHMENT_BOUNDARY_URI") or "").strip()
    catchment_source = {"status": "ready" if catchments else "not_registered", "uri": catchment_uri, "count": len(catchments)}
    if not administrative:
        administrative, administrative_source = _area_options_from_database("administrative_units")
    if not catchments and catchment_uri:
        # The model-ready object-store catalog is the authoritative local
        # development source. Do not silently replace a failed read with an
        # empty database fallback: that would make the UI look valid while
        # hiding the real storage problem.
        catchments, catchment_source = _area_options_from_object_uri(catchment_uri)
    elif not catchments:
        catchments, catchment_source = _area_options_from_database("catchments")
    model_regions = _model_region_options(catchments, _regional_pilot_catalog())
    model_region_source = {
        "status": "ready" if model_regions else "not_registered",
        "uri": catchment_source.get("uri", ""),
        "count": len(model_regions),
        "derived_from": "registered_subcatchment_catalog_and_regional_model_packages",
    }
    return {
        "schema": "gwm.abu_dhabi_flood.hydro_area_options.v1",
        "crs": "EPSG:4326",
        "administrative_units": administrative,
        "model_regions": model_regions,
        "subcatchments": catchments,
        # Compatibility alias for older clients and retained run manifests.
        "catchments": catchments,
        "sources": {
            "administrative_units": administrative_source,
            "model_regions": model_region_source,
            "subcatchments": catchment_source,
            "catchments": catchment_source,
        },
        "freehand": {"status": "ready"},
    }


async def get_hydro_source_defaults(request: Request) -> JSONResponse:
    return JSONResponse(hydro_source_defaults_payload(request.query_params.get("region")))


async def list_hydro_runs(request: Request) -> JSONResponse:
    """Return the durable run history visible to the current principal."""

    raw_limit = request.query_params.get("limit", "50")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 50
    try:
        records = _coordinator().list_runs(limit=limit)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_history_failed", "detail": str(error)[:500]}, status_code=503
        )
    return JSONResponse(
        {
            "schema": "gwm.abu_dhabi_flood.hydro_run_history.v1",
            "runs": records,
            "count": len(records),
        }
    )


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
        "two_d_maximum": directory / "two_d" / "maximum_depth_points.geojson",
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


def _hydro_timeline_payload(directory: Path, layer: str | None = None) -> dict[str, Any]:
    """Expose the solver-native time axes used by the shared map player."""

    result_path = directory / "result.json"
    result = read_json(result_path) if result_path.exists() else {}
    branches: dict[str, dict[str, Any]] = {}
    for key, result_key, directory_name in (
        ("one_d", "one_d", "one_d"),
        ("two_d", "two_d", "two_d"),
    ):
        branch = result.get(result_key)
        if not isinstance(branch, dict) and isinstance(result.get("coupled"), dict):
            branch = result["coupled"].get(result_key)
        if not isinstance(branch, dict):
            branch = {}
        timeline_file = str(branch.get("timeline") or "")
        path = Path(timeline_file) if timeline_file else directory / directory_name / "timeline.json"
        if not path.is_absolute():
            path = directory / path
        if path.exists():
            timeline = read_json(path)
        elif key == "one_d":
            # Backfill the timeline for runs created before the workbench
            # started recording timeline.json. The native OUT is retained and
            # is sufficient to reconstruct the report clock without rerunning.
            binary = directory / directory_name / "model.out"
            if not binary.exists() and (directory / "coupled" / directory_name / "model.out").exists():
                binary = directory / "coupled" / directory_name / "model.out"
            if not binary.exists():
                continue
            try:
                parser = _swmm_out_parser()
                header = parser.read_swmm_out_header(binary)
                timeline = parser.timeline_from_header(header)
                timeline.update({
                    "kind": "swmm-node",
                    "total_node_count": int(header.get("n_nodes", 0)),
                    "report_step_minutes": float(header.get("report_step_seconds", 0)) / 60.0,
                })
            except (OSError, ValueError):
                continue
        else:
            continue
        if not isinstance(timeline, dict) or not timeline.get("available"):
            continue
        timeline = {**timeline}
        timeline["endpoint"] = f"/api/abu-dhabi/flood/hydro-runs/__RUN_ID__/timeseries?layer={key}"
        timeline["maximum_map"] = branch.get("maximum_map")
        timeline["final_map"] = branch.get("map")
        branches[key] = timeline
    return {"schema": "gwm.abu_dhabi_flood.hydro_timeline.v1", "available": bool(branches), "layers": branches}


async def get_hydro_timeline(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        coordinator = _coordinator()
        coordinator.assert_access(run_id)
        coordinator.assert_integrity(run_id)
        directory = run_dir(run_id, coordinator.root) / "results"
        payload = _hydro_timeline_payload(directory)
        encoded = json.dumps(payload, ensure_ascii=False)
        payload = json.loads(encoded.replace("__RUN_ID__", run_id))
        return JSONResponse(payload)
    except (FileNotFoundError, ValueError, OSError, HydroRunAccessError, HydroRunStateError):
        return JSONResponse({"error": "hydro_timeline_not_ready"}, status_code=404)


async def get_hydro_timeseries(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    layer = str(request.query_params.get("layer") or "")
    try:
        time_index = int(request.query_params.get("time_index", "0"))
    except ValueError:
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    try:
        coordinator = _coordinator()
        coordinator.assert_access(run_id)
        coordinator.assert_integrity(run_id)
        directory = run_dir(run_id, coordinator.root) / "results"
        timeline = _hydro_timeline_payload(directory).get("layers", {}).get(layer)
        if not isinstance(timeline, dict):
            return JSONResponse({"error": "hydro_timeline_layer_not_ready"}, status_code=404)
        if time_index < 0 or time_index >= int(timeline.get("period_count", 0)):
            return JSONResponse({"error": "time_index_out_of_range"}, status_code=400)
        if layer == "two_d":
            item = (timeline.get("snapshots") or [])[time_index]
            path = Path(str(item.get("path") or ""))
            if not path.is_absolute():
                path = directory / path
            payload = read_json(path)
            payload["metadata"] = {**payload.get("metadata", {}), "timeline": timeline, "time_index": time_index, "elapsed_minutes": timeline.get("elapsed_minutes", [])[time_index]}
            return JSONResponse(payload)
        # SWMM OUT is read natively one reporting period at a time.
        parser = _swmm_out_parser()
        binary = directory / "one_d" / "model.out"
        if not binary.exists() and (directory / "coupled" / "one_d" / "model.out").exists():
            binary = directory / "coupled" / "one_d" / "model.out"
        network_path = directory / "one_d" / "network.geojson"
        if not network_path.exists():
            network_path = directory / "coupled" / "one_d" / "network.geojson"
        header = parser.read_swmm_out_header(binary)
        period = parser.read_node_period(binary, header, time_index)
        network = read_json(network_path)
        geometries = {
            str(feature.get("properties", {}).get("id")): feature.get("geometry")
            for feature in network.get("features", [])
            if feature.get("geometry") and feature.get("geometry", {}).get("type") == "Point"
        }
        features = []
        for position, values in enumerate(period.get("nodes", [])):
            if position >= len(header.get("node_names", [])) or len(values) < 6:
                continue
            node_id = str(header["node_names"][position])
            geometry = geometries.get(node_id)
            if not geometry:
                continue
            features.append({"type": "Feature", "geometry": geometry, "properties": {
                "id": node_id, "kind": "junction", "time_index": time_index,
                "timestamp": period.get("timestamp"), "elapsed_minutes": period.get("elapsed_minutes"),
                "water_depth_m": max(0.0, float(values[0])),
                "hydraulic_head_m": float(values[1]), "stored_volume_m3": max(0.0, float(values[2])),
                "total_inflow_m3s": float(values[4]), "overflow_or_flooding_m3s": max(0.0, float(values[5])),
            }})
        return JSONResponse({"type": "FeatureCollection", "name": f"{run_id}_one_d_time_{time_index:04d}", "features": features, "metadata": {"timeline": timeline, "time_index": time_index, "timestamp": period.get("timestamp"), "elapsed_minutes": period.get("elapsed_minutes"), "node_feature_count": len(features)}})
    except (FileNotFoundError, ValueError, OSError, HydroRunAccessError, HydroRunStateError):
        return JSONResponse({"error": "hydro_timeseries_not_ready"}, status_code=404)


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
                "/api/abu-dhabi/flood/hydro-runs/history",
                list_hydro_runs,
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
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}/timeline", get_hydro_timeline, methods=["GET"]),
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}/timeseries", get_hydro_timeseries, methods=["GET"]),
        ]
    return []


WORKBENCH_HTML = Path(__file__).with_name("workbench.html").read_text(encoding="utf-8")


async def workbench_page(request: Request) -> HTMLResponse:
    return HTMLResponse(WORKBENCH_HTML)
