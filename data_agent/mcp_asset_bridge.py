"""Governed catalog-asset workflows for ArcPy MCP and DTS MCP.

The language model sees two bounded functions at the bottom of this module.
This service owns the unsafe-to-delegate parts of the protocol: materialising
catalog assets, packaging sidecars, signed transfers, polling, checksum
verification, object-store ingestion, asset registration, and lineage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from .db_engine import get_engine
from .i18n import t
from .observability import get_logger
from .user_context import current_user_id, current_user_role

logger = get_logger("mcp_asset_bridge")

_TERMINAL = {"succeeded", "failed", "timed_out", "cancelled", "interrupted"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MANAGED_SERVERS = {"arcpy-mcp", "dts-mcp"}
_SHAPEFILE_REQUIRED = (".shp", ".shx", ".dbf", ".prj")
_PRIVATE_RESULT_KEYS = {
    "artifact_id",
    "artifactid",
    "download_url",
    "downloadurl",
    "id",
    "job_id",
    "jobid",
    "result_artifact_id",
    "resultartifactid",
    "signed_url",
    "signedurl",
    "upload_url",
    "uploadurl",
    "url",
}
ProgressFn = Callable[[dict[str, Any]], Awaitable[None] | None]


class McpAssetBridgeError(RuntimeError):
    """A user-safe, stable error from the governed bridge."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.user_message = message


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(value: str, fallback: str = "asset") -> str:
    value = Path(str(value or "")).name
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return value[:160] or fallback


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _json(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _sanitize_for_storage(value: Any) -> Any:
    """Remove transport-only identifiers and secrets from durable evidence."""
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in _PRIVATE_RESULT_KEYS:
                continue
            if any(secret in normalized for secret in ("token", "authorization", "secret")):
                continue
            result[key] = _sanitize_for_storage(child)
        return result
    if isinstance(value, list):
        return [_sanitize_for_storage(child) for child in value]
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered.startswith(("http://", "https://", "bearer ")):
            return "[redacted]"
        if re.match(r"^(?:[a-z]:[\\/]|\\\\)", value, flags=re.IGNORECASE):
            return "[redacted]"
    return value


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first(value: Any, keys: tuple[str, ...]) -> Any:
    for item in _walk(value):
        for key in keys:
            if key in item and item[key] not in (None, ""):
                return item[key]
    return None


def _artifact_id(value: Any) -> str:
    result = _first(value, ("artifact_id", "artifactId", "id"))
    if isinstance(result, str) and result:
        return result
    raise McpAssetBridgeError("MCP_ARTIFACT_MISSING", t("mcp_bridge.artifact_missing"))


def _job_id(value: Any) -> str:
    # ArcPy dedicated tools return the queued job record with its identifier
    # in the top-level ``id`` field; catalog/submit responses use job_id.
    result = _first(value, ("job_id", "jobId", "id"))
    if isinstance(result, str) and result:
        return result
    raise McpAssetBridgeError("MCP_JOB_MISSING", t("mcp_bridge.job_missing"))


def _job_status(value: Any) -> str:
    status = _first(value, ("status", "state"))
    return str(status or "unknown").lower()


def _asset_row(asset_id: int) -> dict[str, Any]:
    engine = get_engine()
    if not engine:
        raise McpAssetBridgeError("CATALOG_UNAVAILABLE", t("mcp_bridge.catalog_unavailable"))
    username = current_user_id.get() or "anonymous"
    role = current_user_role.get() or "anonymous"
    try:
        with engine.connect() as conn:
            from .database_tools import _inject_user_context
            _inject_user_context(conn)
            row = conn.execute(
                text(
                    """
                    SELECT id, asset_name, display_name, owner_username, is_shared,
                           technical_metadata, business_metadata,
                           operational_metadata, lineage_metadata
                    FROM agent_data_assets WHERE id = :id
                    """
                ),
                {"id": int(asset_id)},
            ).mappings().first()
    except Exception as exc:
        logger.warning("Catalog asset lookup failed: %s", exc)
        raise McpAssetBridgeError(
            "CATALOG_UNAVAILABLE",
            t("mcp_bridge.catalog_read_failed"),
        ) from exc
    if not row:
        raise McpAssetBridgeError(
            "ASSET_NOT_FOUND",
            t("mcp_bridge.asset_not_found", asset_id=asset_id),
        )
    if role != "admin" and row["owner_username"] != username and not row["is_shared"]:
        raise McpAssetBridgeError("ASSET_FORBIDDEN", t("mcp_bridge.asset_forbidden"))
    result = dict(row)
    for key in (
        "technical_metadata",
        "business_metadata",
        "operational_metadata",
        "lineage_metadata",
    ):
        result[key] = _json(result.get(key)) or {}
    return result


def _storage(asset: dict[str, Any]) -> dict[str, Any]:
    technical = asset.get("technical_metadata") or {}
    return technical.get("storage") or {}


def _format(asset: dict[str, Any]) -> str:
    storage = _storage(asset)
    value = storage.get("format") or Path(asset.get("asset_name", "")).suffix.lstrip(".")
    return str(value).lower()


def _postgis_dsn(table: str) -> tuple[str, dict[str, str]]:
    if not _SAFE_TABLE.fullmatch(table):
        raise McpAssetBridgeError("INVALID_TABLE", t("mcp_bridge.invalid_table"))
    engine = get_engine()
    if not engine:
        raise McpAssetBridgeError("CATALOG_UNAVAILABLE", t("mcp_bridge.catalog_unavailable"))
    url = engine.url
    env = {}
    password = url.password or os.environ.get("POSTGRES_PASSWORD", "")
    if password:
        env["PGPASSWORD"] = password
    dsn = " ".join(
        part for part in (
            f"host={url.host or '127.0.0.1'}",
            f"port={url.port or 5432}",
            f"dbname={url.database or 'gis_agent'}",
            f"user={url.username or 'postgres'}",
        ) if part
    )
    return f"PG:{dsn}", env


def _copy_or_export_asset(
    asset: dict[str, Any],
    destination: Path,
    *,
    preferred_name: str = "input",
    target_epsg: int | None = None,
    feature_limit: int = 0,
    output_format: str = "GPKG",
) -> Path:
    """Materialise a catalog asset into a controlled temporary directory."""
    destination.mkdir(parents=True, exist_ok=True)
    storage = _storage(asset)
    source_path = storage.get("path") or storage.get("local_path")
    table = storage.get("postgis_table")
    if table:
        dsn, env = _postgis_dsn(str(table))
        if output_format.upper() == "ESRI SHAPEFILE":
            target = destination / _safe_name(preferred_name, "input")
            target.mkdir(exist_ok=True)
            command = [
                "ogr2ogr",
                "-overwrite",
                "-f",
                "ESRI Shapefile",
                str(target),
                dsn,
            ]
            layer_name = _safe_name(preferred_name, "input")
        else:
            target = destination / f"{_safe_name(preferred_name)}.gpkg"
            command = ["ogr2ogr", "-overwrite", "-f", "GPKG", str(target), dsn]
            layer_name = "input"
        sql = f'SELECT * FROM "{table}"'
        if feature_limit:
            sql += f" LIMIT {int(feature_limit)}"
        command.extend(["-sql", sql, "-nln", layer_name])
        if target_epsg:
            command.extend(["-t_srs", f"EPSG:{int(target_epsg)}"])
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("MCP_MATERIALIZE_TIMEOUT", "900")),
                env={**os.environ, **env},
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.warning("PostGIS materialization failed: %s", exc)
            raise McpAssetBridgeError(
                "MATERIALIZE_FAILED",
                t("mcp_bridge.materialize_postgis_failed"),
            ) from exc
        if output_format.upper() == "ESRI SHAPEFILE":
            shp = target / f"{layer_name}.shp"
            if not shp.exists():
                raise McpAssetBridgeError(
                    "MATERIALIZE_FAILED",
                    t("mcp_bridge.materialize_shapefile_missing"),
                )
            return shp
        return target

    if source_path and os.path.isfile(source_path):
        source = Path(source_path).resolve()
        if output_format.upper() == "ESRI SHAPEFILE":
            if source.suffix.lower() == ".zip":
                return shutil.copy2(source, destination / _safe_name(source.name))
            output_dir = destination / _safe_name(preferred_name, "input")
            output_dir.mkdir(exist_ok=True)
            target = output_dir / f"{_safe_name(preferred_name, 'input')}.shp"
            if source.suffix.lower() == ".shp":
                for sidecar in source.parent.glob(f"{source.stem}.*"):
                    shutil.copy2(sidecar, output_dir / f"{target.stem}{sidecar.suffix.lower()}")
                return target
            command = [
                "ogr2ogr",
                "-overwrite",
                "-f",
                "ESRI Shapefile",
                str(output_dir),
                str(source),
                "-nln",
                target.stem,
            ]
            if target_epsg:
                command.extend(["-t_srs", f"EPSG:{int(target_epsg)}"])
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=int(os.environ.get("MCP_MATERIALIZE_TIMEOUT", "900")),
                )
            except (
                OSError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as exc:
                raise McpAssetBridgeError(
                    "MATERIALIZE_FAILED",
                    t("mcp_bridge.materialize_vector_failed"),
                ) from exc
            return target
        name = _safe_name(preferred_name or source.name, source.name)
        if not Path(name).suffix and source.suffix:
            name += source.suffix.lower()
        target = destination / name
        if source.suffix.lower() == ".shp":
            for sidecar in source.parent.glob(f"{source.stem}.*"):
                shutil.copy2(
                    sidecar,
                    destination / f"{target.stem}{sidecar.suffix.lower()}",
                )
            return target
        if source.suffix.lower() == ".zip":
            return shutil.copy2(source, target)
        return shutil.copy2(source, target)

    uri = (
        storage.get("lakehouse_uri")
        or storage.get("uri")
        or storage.get("cloud_uri")
    )
    if isinstance(uri, str) and uri.startswith("s3://"):
        return _download_s3_asset(uri, destination, preferred_name)
    raise McpAssetBridgeError(
        "MATERIALIZE_UNSUPPORTED",
        t("mcp_bridge.materialize_location_missing"),
    )


def _s3_client():
    try:
        import boto3
        return boto3.client(
            "s3",
            endpoint_url=(
                os.environ.get("AWS_ENDPOINT_URL")
                or os.environ.get("S3_ENDPOINT_URL")
            ),
            aws_access_key_id=(
                os.environ.get("AWS_ACCESS_KEY_ID")
                or os.environ.get("MINIO_ROOT_USER")
            ),
            aws_secret_access_key=(
                os.environ.get("AWS_SECRET_ACCESS_KEY")
                or os.environ.get("MINIO_ROOT_PASSWORD")
            ),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    except Exception as exc:
        raise McpAssetBridgeError(
            "OBJECT_STORE_UNAVAILABLE",
            t("mcp_bridge.object_store_unavailable"),
        ) from exc


def _parse_s3(uri: str) -> tuple[str, str]:
    match = re.fullmatch(r"s3://([^/]+)/(.+)", uri)
    if not match:
        raise McpAssetBridgeError("INVALID_STORAGE_URI", t("mcp_bridge.invalid_storage_uri"))
    return match.group(1), match.group(2)


def _download_s3_asset(uri: str, destination: Path, preferred_name: str) -> Path:
    bucket, key = _parse_s3(uri)
    client = _s3_client()
    name = _safe_name(preferred_name or Path(key).name, Path(key).name)
    if not Path(name).suffix and Path(key).suffix:
        name += Path(key).suffix.lower()
    target = destination / name
    try:
        client.download_file(bucket, key, str(target))
    except Exception as exc:
        raise McpAssetBridgeError(
            "MATERIALIZE_FAILED",
            t("mcp_bridge.materialize_object_store_failed"),
        ) from exc
    return target


def _zip_inputs(files: list[tuple[Path, str]], target: Path) -> Path:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, relative in files:
            relative = relative.replace("\\", "/")
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise McpAssetBridgeError(
                    "INVALID_PACKAGE",
                    t("mcp_bridge.invalid_package_path"),
                )
            archive.write(path, relative)
    return target


def _validate_zip(path: Path, required: tuple[str, ...] = ()) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            for name in names:
                p = Path(name.replace("\\", "/"))
                if p.is_absolute() or ".." in p.parts:
                    raise McpAssetBridgeError(
                        "INVALID_PACKAGE",
                        t("mcp_bridge.zip_path_traversal"),
                    )
                mode = archive.getinfo(name).external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise McpAssetBridgeError(
                        "INVALID_PACKAGE",
                        t("mcp_bridge.zip_symlink"),
                    )
            lower = {Path(name).name.lower() for name in names}
            missing = [item for item in required if item.lower() not in lower]
            if missing:
                raise McpAssetBridgeError(
                    "INVALID_RESULT",
                    t("mcp_bridge.result_missing_members", members=", ".join(missing)),
                )
            return names
    except zipfile.BadZipFile as exc:
        raise McpAssetBridgeError(
            "INVALID_RESULT",
            t("mcp_bridge.invalid_result_zip"),
        ) from exc


def _safe_extract_zip(path: Path, destination: Path) -> list[Path]:
    """Extract a validated ZIP without following links or escaping the target."""
    _validate_zip(path)
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    extracted = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            relative = Path(info.filename.replace("\\", "/"))
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                raise McpAssetBridgeError(
                    "INVALID_PACKAGE",
                    t("mcp_bridge.zip_path_traversal"),
                )
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    return extracted


def _prepare_road_shapefile(
    source: Path,
    workdir: Path,
    target_epsg: int | None,
) -> tuple[Path, Any, tuple[float, float, float, float]]:
    """Normalize a vector source to a complete projected ``roads.*`` set."""
    if source.suffix.lower() == ".zip":
        extracted = _safe_extract_zip(source, workdir / "road-archive")
        candidates = sorted(path for path in extracted if path.suffix.lower() == ".shp")
        if not candidates:
            raise McpAssetBridgeError(
                "DTS_ROAD_SHP_MISSING",
                t("mcp_bridge.road_shapefile_missing"),
            )
        source = candidates[0]

    normalized_dir = workdir / "road-normalized"
    normalized_dir.mkdir(exist_ok=True)
    normalized = normalized_dir / "roads.shp"
    if source.suffix.lower() != ".shp" or target_epsg:
        command = [
            "ogr2ogr",
            "-overwrite",
            "-f",
            "ESRI Shapefile",
            str(normalized_dir),
            str(source),
            "-nln",
            "roads",
        ]
        if target_epsg:
            epsg = int(target_epsg)
            if not 1 <= epsg <= 999999:
                raise McpAssetBridgeError("INVALID_EPSG", t("mcp_bridge.invalid_epsg"))
            command.extend(["-t_srs", f"EPSG:{epsg}"])
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("MCP_MATERIALIZE_TIMEOUT", "900")),
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise McpAssetBridgeError(
                "DTS_ROAD_INVALID",
                t("mcp_bridge.road_convert_failed"),
            ) from exc
    else:
        for sidecar in source.parent.glob(f"{source.stem}.*"):
            shutil.copy2(
                sidecar,
                normalized_dir / f"roads{sidecar.suffix.lower()}",
            )

    missing = [
        f"roads{suffix}"
        for suffix in _SHAPEFILE_REQUIRED
        if not (normalized_dir / f"roads{suffix}").is_file()
    ]
    if missing:
        raise McpAssetBridgeError(
            "DTS_ROAD_SIDECAR_MISSING",
            t("mcp_bridge.road_sidecars_missing", members=", ".join(missing)),
        )

    try:
        import fiona
        from pyproj import CRS

        with fiona.open(normalized) as collection:
            road_crs = CRS.from_user_input(collection.crs_wkt or collection.crs)
            bounds = tuple(float(value) for value in collection.bounds)
            geometry = str(collection.schema.get("geometry") or "")
        if not road_crs.is_projected:
            raise McpAssetBridgeError(
                "DTS_PROJECTED_CRS_REQUIRED",
                t("mcp_bridge.projected_crs_required"),
            )
        if "LineString" not in geometry:
            raise McpAssetBridgeError(
                "DTS_ROAD_GEOMETRY_REQUIRED",
                t("mcp_bridge.road_geometry_required"),
            )
    except McpAssetBridgeError:
        raise
    except Exception as exc:
        raise McpAssetBridgeError(
            "DTS_ROAD_INVALID",
            t("mcp_bridge.road_validation_failed"),
        ) from exc
    return normalized, road_crs, bounds


def _validate_dts_raster_alignment(
    road_crs: Any,
    road_bounds: tuple[float, float, float, float],
    dom_path: Path,
    dem_path: Path | None,
) -> dict[str, Any]:
    """Require DOM/DEM to share the projected road CRS and spatial coverage."""
    try:
        import rasterio
        from pyproj import CRS

        checked = {}
        for label, path in (("DOM", dom_path), ("DEM", dem_path)):
            if path is None:
                continue
            with rasterio.open(path) as dataset:
                if dataset.crs is None:
                    raise McpAssetBridgeError(
                        "DTS_RASTER_CRS_MISSING",
                        t("mcp_bridge.raster_crs_missing", label=label),
                    )
                raster_crs = CRS.from_user_input(dataset.crs)
                bounds = tuple(float(value) for value in dataset.bounds)
            if raster_crs != road_crs:
                raise McpAssetBridgeError(
                    "DTS_CRS_MISMATCH",
                    t("mcp_bridge.crs_mismatch", label=label),
                )
            overlaps = not (
                road_bounds[2] <= bounds[0]
                or road_bounds[0] >= bounds[2]
                or road_bounds[3] <= bounds[1]
                or road_bounds[1] >= bounds[3]
            )
            if not overlaps:
                raise McpAssetBridgeError(
                    "DTS_EXTENT_MISMATCH",
                    t("mcp_bridge.extent_mismatch", label=label),
                )
            checked[label.lower()] = {
                "crs": raster_crs.to_string(),
                "bounds": list(bounds),
            }
        return checked
    except McpAssetBridgeError:
        raise
    except Exception as exc:
        raise McpAssetBridgeError(
            "DTS_RASTER_INVALID",
            t("mcp_bridge.raster_validation_failed"),
        ) from exc


def _signed_put(url: str, path: Path, ca_cert: str, offset_header: str) -> None:
    import httpx

    try:
        with httpx.Client(
            verify=ca_cert or True,
            timeout=None,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            with path.open("rb") as handle:
                response = client.put(url, headers={offset_header: "0"}, content=handle)
            response.raise_for_status()
    except Exception as exc:
        raise McpAssetBridgeError("UPLOAD_FAILED", t("mcp_bridge.upload_failed")) from exc


def _signed_download(url: str, path: Path, ca_cert: str) -> None:
    import httpx

    try:
        with httpx.Client(
            verify=ca_cert or True,
            timeout=None,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with path.open("wb") as handle:
                    for block in response.iter_bytes(1024 * 1024):
                        handle.write(block)
    except Exception as exc:
        raise McpAssetBridgeError("DOWNLOAD_FAILED", t("mcp_bridge.download_failed")) from exc


async def _call(server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    from .mcp_hub import get_mcp_hub

    try:
        return await get_mcp_hub().call_tool(server, tool, args)
    except McpAssetBridgeError:
        raise
    except Exception as exc:
        raise McpAssetBridgeError(
            "MCP_CALL_FAILED",
            t("mcp_bridge.call_failed", tool=tool),
        ) from exc


async def _poll(server: str, job_id: str, *, timeout: int = 1800,
                progress: ProgressFn | None = None) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    delays = [2, 5, 10]
    index = 0
    while True:
        job_tool = "get_job" if server == "arcpy-mcp" else "dts_get_job"
        result = await _call(server, job_tool, {"job_id": job_id})
        status = _job_status(result)
        if progress:
            update = {"stage": "job", "status": status}
            maybe = progress(update)
            if asyncio.iscoroutine(maybe):
                await maybe
        if status in _TERMINAL:
            if status != "succeeded":
                detail = {}
                if server == "arcpy-mcp":
                    try:
                        detail = await _call(
                            server, "get_job_log", {"job_id": job_id}
                        )
                    except Exception:
                        detail = {}
                code = _first(detail, ("error_code", "errorCode"))
                suffix = f" ({code})" if code else ""
                raise McpAssetBridgeError(
                    "MCP_JOB_FAILED",
                    t("mcp_bridge.job_failed", status=status, suffix=suffix),
                )
            return result
        if asyncio.get_running_loop().time() - started > timeout:
            raise McpAssetBridgeError("MCP_JOB_TIMEOUT", t("mcp_bridge.job_timeout"))
        delay = delays[index] if index < len(delays) else 20
        index += 1
        await asyncio.sleep(delay)


def _ca_cert(server: str) -> str:
    env_name = "ARCPY_MCP_CA_CERT" if server == "arcpy-mcp" else "DTS_MCP_CA_CERT"
    configured = os.environ.get(env_name, "")
    if configured:
        return configured
    if server == "arcpy-mcp":
        return (
            "/Users/zhouning/codex-arcpy-mcp-plugin/plugins/arcpy-mcp/"
            "assets/arcpy-mcp-ca.crt"
        )
    return (
        "/Users/zhouning/codex-dts-mcp-plugin/plugins/dts-mcp/"
        "assets/dts-mcp-ca.crt"
    )


async def _upload(server: str, path: Path, logical_name: str) -> tuple[str, dict[str, Any]]:
    size, digest = _sha256(path)
    tool = "create_upload" if server == "arcpy-mcp" else "dts_create_upload"
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".zip":
        media_type = "application/zip"
    payload = await _call(
        server,
        tool,
        {
            "logical_name": logical_name,
            "expected_size": size,
            "expected_sha256": digest,
            "media_type": media_type,
        },
    )
    artifact_id = _artifact_id(payload)
    url = _first(payload, ("upload_url", "uploadUrl", "url"))
    if not isinstance(url, str) or not url.startswith("https://"):
        raise McpAssetBridgeError("UPLOAD_URL_MISSING", t("mcp_bridge.upload_url_missing"))
    offset_header = "Upload-Offset" if server == "arcpy-mcp" else "X-Upload-Offset"
    await asyncio.to_thread(
        _signed_put,
        url,
        path,
        _ca_cert(server),
        offset_header,
    )
    complete_tool = (
        "complete_upload" if server == "arcpy-mcp" else "dts_complete_upload"
    )
    complete = await _call(server, complete_tool, {"artifact_id": artifact_id})
    actual = _first(complete, ("actual_sha256", "actualSha256"))
    state = str(_first(complete, ("state", "status")) or "").lower()
    if not actual or str(actual).lower() != digest:
        raise McpAssetBridgeError(
            "UPLOAD_HASH_MISMATCH",
            t("mcp_bridge.upload_hash_mismatch"),
        )
    if state != "ready":
        raise McpAssetBridgeError("UPLOAD_NOT_READY", t("mcp_bridge.upload_not_ready"))
    return artifact_id, {"size": size, "sha256": digest}


async def _download_result(
    server: str,
    reference_id: str,
    workdir: Path,
    *,
    preferred_name: str = "",
) -> tuple[Path, dict[str, Any]]:
    args = {"artifact_id": reference_id} if server == "arcpy-mcp" else {"job_id": reference_id}
    tool = "create_download" if server == "arcpy-mcp" else "dts_download_output"
    payload = await _call(server, tool, args)
    url = _first(payload, ("download_url", "downloadUrl", "url"))
    if not isinstance(url, str) or not url.startswith("https://"):
        raise McpAssetBridgeError(
            "DOWNLOAD_URL_MISSING",
            t("mcp_bridge.download_url_missing"),
        )
    expected = _first(payload, ("actual_sha256", "actualSha256", "sha256"))
    suggested = _first(payload, ("logical_name", "filename", "file_name", "name"))
    if isinstance(suggested, str) and _SAFE_ID.fullmatch(Path(suggested).name):
        result_name = Path(suggested).name
    elif preferred_name:
        result_name = _safe_name(preferred_name, "mcp-result")
    else:
        result_name = "mcp-result.zip" if server == "dts-mcp" else "mcp-result.bin"
    target = workdir / result_name
    await asyncio.to_thread(_signed_download, url, target, _ca_cert(server))
    size, digest = _sha256(target)
    if not expected or str(expected).lower() != digest:
        raise McpAssetBridgeError(
            "RESULT_HASH_MISMATCH",
            t("mcp_bridge.result_hash_mismatch"),
        )
    return target, {"size": size, "sha256": digest}


def _result_artifact_id(job: dict[str, Any], input_artifact: str) -> str:
    candidates = []
    for item in _walk(job):
        for key in (
            "result_artifact_id",
            "resultArtifactId",
            "output_artifact_id",
            "outputArtifactId",
        ):
            value = item.get(key)
            if isinstance(value, str):
                candidates.append(value)
        for key in (
            "result_artifacts",
            "resultArtifacts",
            "result_artifact_ids",
            "resultArtifactIds",
            "output_artifact_ids",
            "outputArtifactIds",
            "artifacts",
            "outputs",
        ):
            value = item.get(key)
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str):
                        candidates.append(entry)
                    elif isinstance(entry, dict):
                        value_id = (
                            entry.get("artifact_id")
                            or entry.get("artifactId")
                            or entry.get("id")
                        )
                        if isinstance(value_id, str):
                            candidates.append(value_id)
    for value in candidates:
        if value != input_artifact:
            return value
    raise McpAssetBridgeError(
        "RESULT_ARTIFACT_MISSING",
        t("mcp_bridge.result_artifact_missing"),
    )


def _run_receipt(
    run_id: uuid.UUID,
    *,
    status: str | None = None,
    stages: list | None = None,
    input_sha: str | None = None,
    output_sha: str | None = None,
    output_asset_id: int | None = None,
    error: McpAssetBridgeError | None = None,
) -> None:
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            values = {
                "run": str(run_id),
                "status": status,
                "stages": json.dumps(_sanitize_for_storage(stages or [])),
                "input_sha": input_sha,
                "output_sha": output_sha,
                "output_asset": output_asset_id,
                "error_code": error.code if error else None,
                "error_message": error.user_message if error else None,
            }
            conn.execute(
                text(
                    """
                    UPDATE agent_mcp_asset_runs SET
                        status = COALESCE(:status, status),
                        stages = CAST(:stages AS jsonb),
                        input_sha256 = COALESCE(:input_sha, input_sha256),
                        output_sha256 = COALESCE(:output_sha, output_sha256),
                        output_asset_id = COALESCE(:output_asset, output_asset_id),
                        error_code = :error_code,
                        error_message = :error_message,
                        started_at = COALESCE(started_at, NOW()),
                        completed_at = CASE
                            WHEN :status IN (
                                'succeeded', 'failed', 'timed_out',
                                'cancelled', 'interrupted'
                            ) THEN NOW()
                            ELSE completed_at
                        END
                    WHERE run_id = :run
                    """
                ),
                values,
            )
            conn.commit()
    except Exception as exc:
        logger.debug("MCP run receipt update skipped: %s", exc)


def _register_output(
    *,
    run_id: uuid.UUID,
    server: str,
    operation: str,
    source_assets: list[int],
    output_path: Path,
    output_sha: str,
    owner: str,
    metadata: dict[str, Any],
) -> int:
    engine = get_engine()
    if not engine:
        raise McpAssetBridgeError(
            "CATALOG_UNAVAILABLE",
            t("mcp_bridge.catalog_register_unavailable"),
        )
    prefix = os.environ.get(
        "MCP_ASSET_OUTPUT_PREFIX",
        "s3://gis-agent-lakehouse/derived/mcp",
    )
    if not prefix.startswith("s3://"):
        raise McpAssetBridgeError(
            "OBJECT_STORE_UNAVAILABLE",
            t("mcp_bridge.result_prefix_invalid"),
        )
    bucket, key_prefix = _parse_s3(prefix.rstrip("/"))
    owner_key = _safe_name(owner, "user")
    key = f"{key_prefix}/{owner_key}/{run_id}/{_safe_name(output_path.name)}"
    client = _s3_client()
    try:
        client.upload_file(str(output_path), bucket, key)
    except Exception as exc:
        raise McpAssetBridgeError(
            "RESULT_PERSIST_FAILED",
            t("mcp_bridge.result_persist_failed"),
        ) from exc
    uri = f"s3://{bucket}/{key}"
    size = output_path.stat().st_size
    technical = {
        "storage": {
            "backend": "s3",
            "uri": uri,
            "cloud_key": key,
            "bucket": bucket,
            "size_bytes": size,
            "format": output_path.suffix.lstrip(".").lower(),
            "sha256": output_sha,
        },
        "checksums": {"sha256": output_sha},
        "mcp": {
            "server": server,
            "operation": operation,
            "verified": True,
            "evidence": _sanitize_for_storage(metadata),
        },
    }
    business = {
        "semantic": {
            "description": t(
                "mcp_bridge.catalog_result_description",
                server=server,
                run_id=run_id,
            ),
            "keywords": ["mcp", server, operation],
        },
        "classification": {
            "category": (
                "vector"
                if output_path.suffix.lower() in {".gpkg", ".shp"}
                else "other"
            )
        },
    }
    operational = {
        "creation": {
            "tool": server,
            "operation": operation,
            "run_id": str(run_id),
            "completed_at": _now(),
        },
        "version": {"version": 1, "is_latest": True},
    }
    lineage = {
        "upstream": {"asset_ids": [{"id": item} for item in source_assets]},
        "transformation": {
            "server": server,
            "operation": operation,
            "run_id": str(run_id),
        },
    }
    try:
        with engine.connect() as conn:
            from .database_tools import _inject_user_context

            _inject_user_context(conn)
            row = conn.execute(
                text(
                    """
                    INSERT INTO agent_data_assets
                        (asset_name, display_name, owner_username, is_shared,
                         technical_metadata, business_metadata, operational_metadata,
                         lineage_metadata)
                    VALUES (:name, :name, :owner, false, CAST(:technical AS jsonb),
                            CAST(:business AS jsonb), CAST(:operational AS jsonb),
                            CAST(:lineage AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "name": f"{server}-{operation}-{run_id}{output_path.suffix}",
                    "owner": owner,
                    "technical": json.dumps(technical),
                    "business": json.dumps(business),
                    "operational": json.dumps(operational),
                    "lineage": json.dumps(lineage),
                },
            ).scalar_one()
            lineage_metadata = json.dumps(
                {"operation": operation, "verified_sha256": output_sha}
            )
            for source_id in source_assets:
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_asset_lineage
                            (source_asset_id, target_asset_id, relationship, tool_name,
                             pipeline_run_id, metadata, created_by)
                        VALUES (:source, :target, 'derives_from', :tool, :run,
                                CAST(:metadata AS jsonb), :owner)
                        """
                    ),
                    {
                        "source": source_id,
                        "target": row,
                        "tool": server,
                        "run": str(run_id),
                        "metadata": lineage_metadata,
                        "owner": owner,
                    },
                )
            conn.execute(
                text(
                    """
                    INSERT INTO agent_asset_versions
                        (asset_id, version, snapshot_path, file_size_bytes,
                         feature_count, change_summary, created_by)
                    VALUES (:asset, 1, :path, :size, :features, :summary, :owner)
                    """
                ),
                {
                    "asset": row,
                    "path": uri,
                    "size": size,
                    "features": int(metadata.get("feature_count") or 0),
                    "summary": f"{server} MCP {operation}",
                    "owner": owner,
                },
            )
            conn.commit()
    except Exception as exc:
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            logger.warning("Could not remove orphaned MCP result object")
        raise McpAssetBridgeError(
            "RESULT_REGISTER_FAILED",
            t("mcp_bridge.result_register_failed"),
        ) from exc
    return int(row)


async def _run_arcpy(
    asset_id: int,
    operation: str,
    parameters: dict[str, Any],
    run_id: uuid.UUID,
    owner: str,
    progress: ProgressFn | None,
) -> dict[str, Any]:
    asset = _asset_row(asset_id)
    allowed = {
        "inspect_dataset",
        "project_features",
        "repair_geometry",
        "check_geometry",
        "buffer_features",
    }
    if operation not in allowed:
        raise McpAssetBridgeError("INVALID_OPERATION", t("mcp_bridge.invalid_operation"))
    health = await _call("arcpy-mcp", "health_check", {})
    if str(health.get("status", "")).lower() != "healthy":
        raise McpAssetBridgeError("ARCPY_UNHEALTHY", t("mcp_bridge.arcpy_unhealthy"))
    await _call("arcpy-mcp", "get_capabilities", {})
    with tempfile.TemporaryDirectory(prefix="gda-arcpy-") as temp:
        workdir = Path(temp)
        feature_limit = int(parameters.get("feature_limit") or 0)
        if feature_limit < 0 or feature_limit > 1_000_000:
            raise McpAssetBridgeError(
                "INVALID_FEATURE_LIMIT",
                t("mcp_bridge.feature_limit_invalid"),
            )
        source = _copy_or_export_asset(
            asset,
            workdir,
            preferred_name="input",
            feature_limit=feature_limit,
            # ArcPy Pro's worker is reliable with a complete shapefile
            # package; PostGIS vector exports as GeoPackage can fail with
            # the opaque ERROR 999999 during Describe/Project.
            output_format=(
                "ESRI SHAPEFILE"
                if _storage(asset).get("postgis_table")
                else "GPKG"
            ),
        )
        package = source
        input_path = source.name
        if source.suffix.lower() == ".shp":
            sidecars = sorted(source.parent.glob(f"{source.stem}.*"))
            missing = [
                f"{source.stem}{suffix}"
                for suffix in _SHAPEFILE_REQUIRED
                if not (source.parent / f"{source.stem}{suffix}").is_file()
            ]
            if missing:
                raise McpAssetBridgeError(
                    "SHAPEFILE_SIDECAR_MISSING",
                    t(
                        "mcp_bridge.shapefile_sidecars_missing",
                        members=", ".join(missing),
                    ),
                )
            package = _zip_inputs(
                [(path, path.name) for path in sidecars],
                workdir / "input.zip",
            )
            input_path = source.name
        elif source.suffix.lower() == ".zip":
            members = _validate_zip(source)
            shp = next((name for name in members if name.lower().endswith(".shp")), "")
            input_path = Path(shp).as_posix() if shp else source.name
        elif source.suffix.lower() not in {".gpkg", ".tif", ".tiff", ".img"}:
            package = _zip_inputs([(source, source.name)], workdir / "input.zip")
        artifact_id, input_meta = await _upload("arcpy-mcp", package, package.name)
        if progress:
            value = progress(
                {
                    "stage": "upload",
                    "status": "succeeded",
                    "sha256": input_meta["sha256"],
                }
            )
            if asyncio.iscoroutine(value):
                await value
        inspect_job = _job_id(
            await _call(
                "arcpy-mcp",
                "inspect_dataset",
                {
                    "input_artifact_id": artifact_id,
                    "input_path": input_path,
                },
            )
        )
        inspection = await _poll("arcpy-mcp", inspect_job, progress=progress)
        if operation == "inspect_dataset":
            report = workdir / "inspection.json"
            safe_inspection = _sanitize_for_storage(inspection)
            report.write_text(
                json.dumps(safe_inspection, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_path = report
            output_meta = {
                "sha256": _sha256(report)[1],
                "size": report.stat().st_size,
            }
        else:
            requested_name = parameters.get("output_name") or (
                f"{asset.get('asset_name', 'asset')}-{operation}.gpkg"
            )
            output_name = _safe_name(str(requested_name))
            if input_path.lower().endswith(".shp"):
                expected_suffix = ".dbf" if operation == "check_geometry" else ".shp"
                if Path(output_name).suffix.lower() != expected_suffix:
                    output_name = f"{Path(output_name).stem}{expected_suffix}"
            if operation == "project_features":
                args = {
                    "input_artifact_id": artifact_id,
                    "input_path": input_path,
                    "output_spatial_reference": parameters.get(
                        "output_spatial_reference",
                        32640,
                    ),
                    "output_name": output_name,
                }
                tool = "project_features"
            elif operation == "repair_geometry":
                args = {
                    "input_artifact_id": artifact_id,
                    "input_path": input_path,
                    "output_name": output_name,
                    "delete_null": str(
                        parameters.get("delete_null", "DELETE_NULL")
                    ),
                }
                tool = "repair_geometry"
            elif operation == "check_geometry":
                args = {
                    "input_artifact_id": artifact_id,
                    "input_path": input_path,
                    "output_name": output_name,
                }
                tool = "check_geometry"
            else:
                args = {
                    "input_artifact_id": artifact_id,
                    "input_path": input_path,
                    "output_name": output_name,
                    "distance": str(parameters.get("distance", "10 Meters")),
                }
                tool = "buffer_features"
            job = _job_id(await _call("arcpy-mcp", tool, args))
            finished = await _poll("arcpy-mcp", job, progress=progress)
            result_artifact = _result_artifact_id(finished, artifact_id)
            output_path, output_meta = await _download_result(
                "arcpy-mcp",
                result_artifact,
                workdir,
                preferred_name=output_name,
            )
        output_asset = _register_output(
            run_id=run_id,
            server="arcpy-mcp",
            operation=operation,
            source_assets=[asset_id],
            output_path=output_path,
            output_sha=output_meta["sha256"],
            owner=owner,
            metadata=(
                _sanitize_for_storage(inspection)
                if operation == "inspect_dataset"
                else {}
            ),
        )
        return {
            "run_id": str(run_id),
            "status": "succeeded",
            "server": "arcpy-mcp",
            "operation": operation,
            "source_asset_id": asset_id,
            "output_asset_id": output_asset,
            "input": {
                "size_bytes": input_meta["size"],
                "sha256": input_meta["sha256"],
            },
            "output": {
                "size_bytes": output_meta["size"],
                "sha256": output_meta["sha256"],
            },
        }


async def _run_dts(
    source_asset_id: int,
    dom_asset_id: int,
    dem_asset_id: int | None,
    parameters: dict[str, Any],
    run_id: uuid.UUID,
    owner: str,
    progress: ProgressFn | None,
) -> dict[str, Any]:
    roads = _asset_row(source_asset_id)
    dom = _asset_row(dom_asset_id)
    dem = _asset_row(dem_asset_id) if dem_asset_id else None
    ping = await _call("dts-mcp", "dts_ping", {})
    if not ping.get("ok"):
        raise McpAssetBridgeError("DTS_UNHEALTHY", t("mcp_bridge.dts_unhealthy"))
    pipelines = await _call("dts-mcp", "dts_list_pipelines", {})
    road = next(
        (
            item
            for item in pipelines.get("pipelines", [])
            if item.get("name") == "road"
        ),
        None,
    )
    if not road or not road.get("verified"):
        raise McpAssetBridgeError(
            "DTS_PIPELINE_UNVERIFIED",
            t("mcp_bridge.dts_pipeline_unverified"),
        )
    with tempfile.TemporaryDirectory(prefix="gda-dts-") as temp:
        workdir = Path(temp)
        road_source = _copy_or_export_asset(
            roads,
            workdir,
            preferred_name="roads",
            output_format="ESRI SHAPEFILE",
        )
        road_source, road_crs, road_bounds = _prepare_road_shapefile(
            road_source,
            workdir,
            parameters.get("target_epsg"),
        )
        dom_source = _copy_or_export_asset(dom, workdir, preferred_name="dom.tif")
        dem_source = None
        if dem:
            dem_source = _copy_or_export_asset(
                dem,
                workdir,
                preferred_name="dem.tif",
            )
        alignment = _validate_dts_raster_alignment(
            road_crs,
            road_bounds,
            dom_source,
            dem_source,
        )
        files: list[tuple[Path, str]] = []
        road_dir = road_source.parent
        for member in sorted(road_dir.glob("roads.*")):
            files.append((member, member.name))
        files.append((dom_source, "dom.tif"))
        if dem_source:
            files.append((dem_source, "dem.tif"))
        package = _zip_inputs(files, workdir / "dts-road-input.zip")
        artifact_id, input_meta = await _upload("dts-mcp", package, package.name)
        flags = {
            "roadShp": {"artifact": artifact_id, "path": "roads.shp"},
            "domPath": {"artifact": artifact_id, "path": "dom.tif"},
            "roadRGB": str(parameters.get("roadRGB", "255,0,0")),
        }
        if dem_source:
            flags["demPath"] = {"artifact": artifact_id, "path": "dem.tif"}
        timeout = int(parameters.get("timeout", 1800))
        response = await _call(
            "dts-mcp",
            "dts_publish",
            {
                "pipeline": "road",
                "strict": True,
                "timeout": timeout,
                "flags": flags,
            },
        )
        job = _job_id(response)
        await _poll("dts-mcp", job, timeout=timeout, progress=progress)
        output_path, output_meta = await _download_result(
            "dts-mcp",
            job,
            workdir,
            preferred_name="dts-road-result.zip",
        )
        output_members = _validate_zip(output_path, ("DataInfor.txt",))
        if not any(name.lower().endswith(".3dt") for name in output_members):
            raise McpAssetBridgeError(
                "INVALID_RESULT",
                t("mcp_bridge.dts_result_3dt_missing"),
            )
        source_assets = [
            value
            for value in (source_asset_id, dom_asset_id, dem_asset_id)
            if value
        ]
        output_asset = _register_output(
            run_id=run_id,
            server="dts-mcp",
            operation="road",
            source_assets=source_assets,
            output_path=output_path,
            output_sha=output_meta["sha256"],
            owner=owner,
            metadata={"alignment": alignment},
        )
        return {
            "run_id": str(run_id),
            "status": "succeeded",
            "server": "dts-mcp",
            "operation": "road",
            "source_asset_ids": source_assets,
            "output_asset_id": output_asset,
            "input": {
                "size_bytes": input_meta["size"],
                "sha256": input_meta["sha256"],
            },
            "output": {
                "size_bytes": output_meta["size"],
                "sha256": output_meta["sha256"],
                "required_members": [".3dt", "DataInfor.txt"],
            },
        }


async def run_mcp_asset_workflow(
    asset_id: int,
    mcp_server: str,
    operation: str = "project_features",
    dom_asset_id: int | None = None,
    dem_asset_id: int | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a governed MCP workflow on a catalog asset and register its result.

    Use this single tool from chat.  ``asset_id`` is the catalog source asset;
    for DTS ``operation`` must be ``road`` and ``dom_asset_id`` is required.
    ArcPy operations are ``inspect_dataset``, ``project_features``,
    ``repair_geometry``, ``check_geometry``, and ``buffer_features``.
    """
    if mcp_server not in _MANAGED_SERVERS:
        return {
            "status": "error",
            "code": "SERVER_NOT_MANAGED",
            "message": t("mcp_bridge.managed_only"),
        }
    owner = current_user_id.get() or "anonymous"
    run_id = uuid.uuid4()
    params = parameters or {}
    source_ids = [int(asset_id)]
    if dom_asset_id:
        source_ids.append(int(dom_asset_id))
    if dem_asset_id:
        source_ids.append(int(dem_asset_id))
    stages: list[dict[str, Any]] = []

    def record_progress(update: dict[str, Any]) -> None:
        stage = _sanitize_for_storage(update)
        stage["at"] = _now()
        stages.append(stage)
        _run_receipt(run_id, status="running", stages=stages)

    engine = get_engine()
    if engine:
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_mcp_asset_runs
                            (run_id, requested_by, server_name, operation,
                             status, source_asset_ids)
                        VALUES (:run, :owner, :server, :operation,
                                'running', CAST(:sources AS jsonb))
                        """
                    ),
                    {
                        "run": str(run_id),
                        "owner": owner,
                        "server": mcp_server,
                        "operation": operation,
                        "sources": json.dumps(source_ids),
                    },
                )
                conn.commit()
        except Exception:
            logger.debug("MCP run receipt table unavailable")
    try:
        if mcp_server == "arcpy-mcp":
            result = await _run_arcpy(
                int(asset_id),
                operation,
                params,
                run_id,
                owner,
                record_progress,
            )
        else:
            if operation != "road" or not dom_asset_id:
                raise McpAssetBridgeError(
                    "DTS_INPUT_REQUIRED",
                    t("mcp_bridge.dts_inputs_required"),
                )
            result = await _run_dts(
                int(asset_id),
                int(dom_asset_id),
                int(dem_asset_id) if dem_asset_id else None,
                params,
                run_id,
                owner,
                record_progress,
            )
        stages.append({"stage": "catalog", "status": "succeeded", "at": _now()})
        _run_receipt(
            run_id,
            status="succeeded",
            stages=stages,
            input_sha=result.get("input", {}).get("sha256"),
            output_sha=result.get("output", {}).get("sha256"),
            output_asset_id=result.get("output_asset_id"),
        )
        return result
    except McpAssetBridgeError as exc:
        stages.append(
            {
                "stage": "workflow",
                "status": "failed",
                "code": exc.code,
                "at": _now(),
            }
        )
        _run_receipt(run_id, status="failed", stages=stages, error=exc)
        return {
            "status": "error",
            "run_id": str(run_id),
            "code": exc.code,
            "message": exc.user_message,
        }
    except Exception as exc:
        safe = McpAssetBridgeError(
            "MCP_WORKFLOW_FAILED",
            t("mcp_bridge.workflow_failed"),
        )
        logger.exception("MCP asset workflow failed: %s", exc)
        stages.append(
            {
                "stage": "workflow",
                "status": "failed",
                "code": safe.code,
                "at": _now(),
            }
        )
        _run_receipt(run_id, status="failed", stages=stages, error=safe)
        return {
            "status": "error",
            "run_id": str(run_id),
            "code": safe.code,
            "message": safe.user_message,
        }


def describe_mcp_asset_workflow(asset_id: int, mcp_server: str) -> dict:
    """Return compatibility facts without uploading or changing state."""
    if mcp_server not in _MANAGED_SERVERS:
        return {
            "status": "error",
            "code": "SERVER_NOT_MANAGED",
            "message": t("mcp_bridge.unknown_server"),
        }
    asset = _asset_row(int(asset_id))
    storage = _storage(asset)
    fmt = _format(asset)
    if mcp_server == "arcpy-mcp":
        return {
            "status": "ready",
            "server": mcp_server,
            "asset_id": asset_id,
            "operations": [
                "inspect_dataset",
                "project_features",
                "repair_geometry",
                "check_geometry",
                "buffer_features",
            ],
            "format": fmt,
            "crs": (asset.get("technical_metadata") or {})
            .get("spatial", {})
            .get("crs"),
            "materialization": (
                "postgis"
                if storage.get("postgis_table")
                else "object_store_or_local"
            ),
        }
    return {
        "status": "needs_supporting_assets",
        "server": mcp_server,
        "asset_id": asset_id,
        "pipeline": "road",
        "required": [
            t("mcp_bridge.required_projected_road"),
            t("mcp_bridge.required_dom"),
        ],
        "optional": [t("mcp_bridge.optional_dem")],
        "reason": t("mcp_bridge.dts_reason"),
    }


def build_mcp_asset_toolset():
    from google.adk.tools.base_toolset import BaseToolset
    from google.adk.tools.function_tool import FunctionTool

    class _McpAssetToolset(BaseToolset):
        async def get_tools(self, readonly_context=None):
            return [FunctionTool(describe_mcp_asset_workflow), FunctionTool(run_mcp_asset_workflow)]

        async def close(self):
            return None

    return _McpAssetToolset()
