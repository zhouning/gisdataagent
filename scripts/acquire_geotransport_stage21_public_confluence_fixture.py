#!/usr/bin/env python3
"""Acquire the bounded public inputs for the Stage 21 confluence fixture."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/stage21_center_hill_public_confluence"
)
SCHEMA = "gwm.geotransport.stage21_public_confluence_acquisition.v1"
USER_AGENT = "gisdataagent-stage21-public-confluence/0.1"
MAXIMUM_TOTAL_DOWNLOAD_BYTES = 1_000_000
SITE_ID = "03424860"
TARGET_FEATURE_IDS = (18421705, 18421707, 18421703)
JUNCTION_COORDINATE = (-85.909170702, 36.178724498)
PATCH_BBOX_WGS84 = (
    -85.9099638,
    36.1779240,
    -85.9082903,
    36.1793977,
)
CDL_BBOX_EPSG5070 = (897627.5, 1506403.7, 897759.2, 1506511.3)

NLDI_URL = (
    "https://api.water.usgs.gov/nldi/linked-data/nwissite/"
    "USGS-03424860/navigation/UT/flowlines?distance=2.0"
)
NWIS_SITE_URL = (
    "https://waterservices.usgs.gov/nwis/site/?"
    "format=rdb&sites=03424860&siteOutput=expanded"
)
THREE_DEP_SERVICE_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/"
    "3DEPElevation/ImageServer?f=pjson"
)
THREE_DEP_EXPORT_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/"
    "3DEPElevation/ImageServer/exportImage?"
    + urllib.parse.urlencode(
        {
            "bbox": ",".join(str(value) for value in PATCH_BBOX_WGS84),
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": "64,64",
            "format": "tiff",
            "pixelType": "F32",
            "f": "image",
        }
    )
)
CDL_REQUEST_URL = (
    "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile?"
    + urllib.parse.urlencode(
        {
            "year": "2024",
            "bbox": ",".join(str(value) for value in CDL_BBOX_EPSG5070),
        }
    )
)

REQUESTS = (
    {
        "source_id": "usgs_nldi_flowlines_2km",
        "url": NLDI_URL,
        "output_name": "raw/nldi_upstream_flowlines_2km.json",
        "maximum_bytes": 150_000,
        "role": "public_flowline_topology_and_centerline_direction",
        "license": "USGS public-domain data",
        "license_url": (
            "https://www.usgs.gov/information-policies-and-instructions/"
            "copyrights-and-credits"
        ),
    },
    {
        "source_id": "usgs_nwis_site_03424860",
        "url": NWIS_SITE_URL,
        "output_name": "raw/nwis_site_03424860.rdb",
        "maximum_bytes": 80_000,
        "role": "public_gauge_identity_location_and_observable_role",
        "license": "USGS public-domain data",
        "license_url": (
            "https://www.usgs.gov/information-policies-and-instructions/"
            "copyrights-and-credits"
        ),
    },
    {
        "source_id": "usgs_3dep_service_metadata",
        "url": THREE_DEP_SERVICE_URL,
        "output_name": "raw/three_dep_service.json",
        "maximum_bytes": 150_000,
        "role": "public_terrain_source_identity_and_vintage_snapshot",
        "license": "USGS public-domain data",
        "license_url": "https://www.usgs.gov/3d-elevation-program/about-3dep-products-services",
    },
    {
        "source_id": "usgs_3dep_patch_elevation",
        "url": THREE_DEP_EXPORT_URL,
        "output_name": "raw/three_dep_elevation_64x64.tif",
        "maximum_bytes": 500_000,
        "role": "public_bare_earth_terrain_context_not_bathymetry",
        "license": "USGS public-domain data",
        "license_url": "https://www.usgs.gov/3d-elevation-program/about-3dep-products-services",
    },
    {
        "source_id": "usda_cdl_2024_clip_request",
        "url": CDL_REQUEST_URL,
        "output_name": "raw/cdl_2024_clip_request.xml",
        "maximum_bytes": 20_000,
        "role": "public_land_cover_clip_request",
        "license": "USDA NASS public data",
        "license_url": "https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php",
    },
)

REUSED_GAUGE_OBSERVATION = {
    "path": (
        "data/geotransport_v0_1/raw/"
        "center_hill-usgs-iv-20220101T000000Z-20220102T000000Z.json"
    ),
    "size_bytes": 6774,
    "sha256": (
        "84ebb336edf45d22cfa33cbc8d97011f39f0685d7d3e9db527535230f69e3bbc"
    ),
    "source_url": (
        "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=03424860"
        "&parameterCd=00060&startDT=2021-12-31T23%3A00%3A00Z"
        "&endDT=2022-01-02T01%3A00%3A00Z&siteStatus=all"
    ),
    "role": "downstream_scalar_discharge_observation_only",
}

ALLOWED_HOSTS = frozenset(
    {
        "api.water.usgs.gov",
        "elevation.nationalmap.gov",
        "nassgeodata.gmu.edu",
        "waterservices.usgs.gov",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--gdal-translate", type=Path)
    parser.add_argument("--gdal-warp", type=Path)
    parser.add_argument("--proj-data", type=Path)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    planned = sum(int(value["maximum_bytes"]) for value in REQUESTS) + 100_000
    if planned > MAXIMUM_TOTAL_DOWNLOAD_BYTES:
        raise ValueError("stage21_public_confluence_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "compile one reproducible real confluence spatial fixture from "
            "public hydrography, terrain, land-cover, and gauge evidence"
        ),
        "target": {
            "site_id": SITE_ID,
            "junction_coordinate_wgs84": list(JUNCTION_COORDINATE),
            "target_feature_ids": list(TARGET_FEATURE_IDS),
            "patch_bbox_wgs84": list(PATCH_BBOX_WGS84),
            "land_cover_bbox_epsg5070": list(CDL_BBOX_EPSG5070),
        },
        "request_boundary": {
            "allowed_hosts": sorted(ALLOWED_HOSTS),
            "planned_request_count": len(REQUESTS) + 1,
            "maximum_total_download_bytes": MAXIMUM_TOTAL_DOWNLOAD_BYTES,
            "planned_maximum_bytes": planned,
            "nldi_navigation_distance_km": 2.0,
            "terrain_export_shape": [64, 64],
            "workspace_or_private_data_sent": False,
        },
        "requests": [dict(value) for value in REQUESTS],
        "reused_public_observation": dict(REUSED_GAUGE_OBSERVATION),
        "claim_boundary": {
            "source_values_acquired": values_mode,
            "terrain_is_channel_bathymetry": False,
            "land_cover_prior_is_calibrated_roughness": False,
            "gauge_discharge_is_two_dimensional_momentum": False,
            "public_vector_momentum_validation_completed": False,
            "operator_admitted": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage21_public_confluence_request_limits_invalid")
    output = args.output.resolve()
    data_root = (REPO_ROOT / "data/geotransport_v0_1").resolve()
    if output != data_root and data_root not in output.parents:
        raise ValueError("stage21_public_confluence_output_outside_data_root")
    output.mkdir(parents=True, exist_ok=True)
    plan = compile_plan(values_mode=not args.plan_only)
    if args.plan_only:
        path = output / "acquisition_plan.json"
        _write_json(path, plan)
        print(path)
        return 0

    translate = _find_gdal_tool("gdal_translate", args.gdal_translate)
    warp = _find_gdal_tool("gdalwarp", args.gdal_warp)
    proj_data = _find_proj_data(args.proj_data)
    opener = _opener(args.proxy)
    artifacts: list[dict[str, Any]] = []
    bodies: dict[str, bytes] = {}
    total_bytes = 0
    for source in REQUESTS:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        _validate_source_body(str(source["source_id"]), body)
        total_bytes += len(body)
        _validate_total(total_bytes)
        destination = output / str(source["output_name"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        bodies[str(source["source_id"])] = body
        artifacts.append(
            _artifact_record(destination, source=source, retrieval=retrieval)
        )

    cdl_url = _parse_cdl_return_url(
        bodies["usda_cdl_2024_clip_request"]
    )
    cdl_body, cdl_retrieval = _fetch(
        cdl_url,
        opener=opener,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        maximum_bytes=100_000,
    )
    _validate_tiff(cdl_body)
    total_bytes += len(cdl_body)
    _validate_total(total_bytes)
    cdl_source = {
        "source_id": "usda_cdl_2024_clip",
        "url": cdl_url,
        "output_name": "raw/cdl_2024_clip.tif",
        "maximum_bytes": 100_000,
        "role": "public_land_cover_classification_for_roughness_prior",
        "license": "USDA NASS public data",
        "license_url": (
            "https://www.nass.usda.gov/Research_and_Science/"
            "Cropland/SARS1a.php"
        ),
    }
    cdl_path = output / str(cdl_source["output_name"])
    cdl_path.write_bytes(cdl_body)
    artifacts.append(
        _artifact_record(
            cdl_path, source=cdl_source, retrieval=cdl_retrieval
        )
    )

    terrain_path = output / "raw/three_dep_elevation_64x64.tif"
    derived = _derive_raster_samples(
        output,
        terrain_path=terrain_path,
        cdl_path=cdl_path,
        translate=translate,
        warp=warp,
        proj_data=proj_data,
    )
    reused = _verify_reused_gauge_observation()
    manifest = {
        **plan,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "total_downloaded_bytes": total_bytes,
        "derived_artifacts": derived,
        "reused_public_observation": reused,
        "toolchain": {
            "gdal_translate": _tool_identity(translate),
            "gdalwarp": _tool_identity(warp),
            "proj_data": str(proj_data),
        },
    }
    path = output / "acquisition_manifest.json"
    _write_json(path, manifest)
    print(path)
    print(f"downloaded_bytes={total_bytes}")
    print(f"artifacts={len(artifacts)}")
    return 0


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("stage21_public_confluence_proxy_url_invalid")
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )


def _fetch(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, object]]:
    _validate_url(url)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                _validate_url(response.geturl())
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError(
                        "stage21_public_confluence_object_boundary_exceeded"
                    )
                return body, {
                    "http_status": int(response.status),
                    "content_type": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "final_url": response.geturl(),
                    "attempt_count": attempt,
                }
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError("stage21_public_confluence_download_failed") from last_error


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("stage21_public_confluence_url_outside_allowlist")


def _validate_source_body(source_id: str, body: bytes) -> None:
    if source_id == "usgs_nldi_flowlines_2km":
        value = json.loads(body)
        feature_ids = {
            int(feature["properties"]["nhdplus_comid"])
            for feature in value.get("features", [])
        }
        valid = set(TARGET_FEATURE_IDS).issubset(feature_ids)
    elif source_id == "usgs_nwis_site_03424860":
        valid = b"USGS\t03424860\t" in body
    elif source_id == "usgs_3dep_service_metadata":
        value = json.loads(body)
        valid = value.get("name") == "3DEPElevation"
    elif source_id == "usgs_3dep_patch_elevation":
        valid = _is_tiff(body)
    elif source_id == "usda_cdl_2024_clip_request":
        valid = b"GetCDLFileResponse" in body and b"returnURL" in body
    else:
        valid = False
    if not valid:
        raise ValueError("stage21_public_confluence_source_identity_invalid")


def _parse_cdl_return_url(body: bytes) -> str:
    root = ET.fromstring(body)
    element = next(
        (value for value in root.iter() if value.tag.endswith("returnURL")),
        None,
    )
    if element is None or not element.text:
        raise ValueError("stage21_public_confluence_cdl_return_url_missing")
    url = element.text.strip()
    _validate_url(url)
    return url


def _is_tiff(body: bytes) -> bool:
    return body.startswith(b"II*\x00") or body.startswith(b"MM\x00*")


def _validate_tiff(body: bytes) -> None:
    if not _is_tiff(body):
        raise ValueError("stage21_public_confluence_tiff_invalid")


def _find_gdal_tool(name: str, supplied: Path | None) -> Path:
    candidates = [
        supplied,
        Path(value) if (value := shutil.which(name)) else None,
        Path(f"/Applications/QGIS-final-4_0_2.app/Contents/MacOS/{name}"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise ValueError(f"stage21_public_confluence_{name}_missing")


def _find_proj_data(supplied: Path | None) -> Path:
    candidates = [
        supplied,
        Path(
            "/Applications/QGIS-final-4_0_2.app/Contents/"
            "Resources/qgis/proj"
        ),
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "proj.db").is_file():
            return candidate.resolve()
    raise ValueError("stage21_public_confluence_proj_data_missing")


def _derive_raster_samples(
    output: Path,
    *,
    terrain_path: Path,
    cdl_path: Path,
    translate: Path,
    warp: Path,
    proj_data: Path,
) -> list[dict[str, object]]:
    derived_root = output / "derived"
    derived_root.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PROJ_DATA"] = str(proj_data)
    with tempfile.TemporaryDirectory(prefix="gwm-stage21-") as temporary:
        temporary_root = Path(temporary)
        terrain_xyz = temporary_root / "terrain.xyz"
        _run(
            [str(translate), "-of", "XYZ", str(terrain_path), str(terrain_xyz)],
            environment,
        )
        terrain_samples = _read_xyz(terrain_xyz, integer_values=False)
        if len(terrain_samples) < 100:
            raise ValueError("stage21_public_confluence_terrain_samples_sparse")
        terrain_value = {
            "schema": "gwm.geotransport.public_terrain_samples.v1",
            "source_crs": "EPSG:4326",
            "coordinate_order": "longitude_latitude",
            "vertical_quantity": "3DEP_bare_earth_elevation_m",
            "bathymetry": False,
            "sample_count": len(terrain_samples),
            "samples": [
                {"longitude": x, "latitude": y, "elevation_m": value}
                for x, y, value in terrain_samples
            ],
        }
        terrain_output = derived_root / "three_dep_elevation_samples.json"
        _write_json(terrain_output, terrain_value)

        cdl_wgs84 = temporary_root / "cdl_wgs84.tif"
        _run(
            [
                str(warp),
                "-overwrite",
                "-t_srs",
                "EPSG:4326",
                "-r",
                "near",
                "-dstnodata",
                "0",
                str(cdl_path),
                str(cdl_wgs84),
            ],
            environment,
        )
        cdl_xyz = temporary_root / "cdl.xyz"
        _run(
            [str(translate), "-of", "XYZ", str(cdl_wgs84), str(cdl_xyz)],
            environment,
        )
        cdl_samples = _read_xyz(cdl_xyz, integer_values=True)
        if not cdl_samples or not any(value > 0 for _, _, value in cdl_samples):
            raise ValueError("stage21_public_confluence_land_cover_empty")
        cdl_value = {
            "schema": "gwm.geotransport.public_land_cover_samples.v1",
            "source_crs": "EPSG:4326",
            "coordinate_order": "longitude_latitude",
            "classification": "USDA_NASS_CDL_2024",
            "native_pixel_size_m": 30.0,
            "resampling": "nearest_neighbor_to_EPSG4326",
            "sample_count": len(cdl_samples),
            "samples": [
                {"longitude": x, "latitude": y, "class_code": int(value)}
                for x, y, value in cdl_samples
            ],
        }
        cdl_output = derived_root / "cdl_2024_samples.json"
        _write_json(cdl_output, cdl_value)

    return [
        _derived_record(terrain_output, terrain_path),
        _derived_record(cdl_output, cdl_path),
    ]


def _read_xyz(
    path: Path, *, integer_values: bool
) -> list[tuple[float, float, float | int]]:
    samples: list[tuple[float, float, float | int]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 3:
            raise ValueError("stage21_public_confluence_xyz_row_invalid")
        x, y, value = (float(part) for part in parts)
        if not all(math.isfinite(item) for item in (x, y, value)):
            continue
        samples.append((x, y, int(round(value)) if integer_values else value))
    return samples


def _run(command: list[str], environment: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "stage21_public_confluence_gdal_failed: "
            + completed.stderr.strip()
        )


def _artifact_record(
    path: Path,
    *,
    source: dict[str, Any],
    retrieval: dict[str, object],
) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        **source,
        **retrieval,
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _derived_record(path: Path, source_path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "source_path": source_path.relative_to(REPO_ROOT).as_posix(),
        "method": "GDAL_nearest_or_native_XYZ_extraction",
    }


def _verify_reused_gauge_observation() -> dict[str, object]:
    value = dict(REUSED_GAUGE_OBSERVATION)
    path = REPO_ROOT / str(value["path"])
    body = path.read_bytes()
    actual_hash = hashlib.sha256(body).hexdigest()
    identity_matches = (
        len(body) == int(value["size_bytes"])
        and actual_hash == value["sha256"]
    )
    if not identity_matches:
        raise ValueError("stage21_public_confluence_gauge_identity_mismatch")
    value.update(
        {
            "actual_size_bytes": len(body),
            "actual_sha256": actual_hash,
            "identity_matches": True,
            "workspace_data_uploaded": False,
        }
    )
    return value


def _tool_identity(path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [str(path), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "path": str(path),
        "version": (completed.stdout or completed.stderr).strip(),
    }


def _validate_total(total_bytes: int) -> None:
    if total_bytes > MAXIMUM_TOTAL_DOWNLOAD_BYTES:
        raise ValueError(
            "stage21_public_confluence_total_download_boundary_exceeded"
        )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
