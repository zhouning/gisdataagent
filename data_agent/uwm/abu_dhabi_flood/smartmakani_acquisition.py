"""Resumable SmartMakani feature snapshots for the stormwater candidate.

The downloader freezes object IDs before reading feature pages.  Every page is
written atomically and recorded with both an expected-ID hash and a content
hash so an interrupted run can resume without silently changing its source
slice.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.connectors.arcgis_rest import (
    ArcGISQuerySnapshot,
    ArcGISRestConnector,
)

SMARTMAKANI_MAPSERVER = (
    "https://geosmart.dmt.gov.ae/arcgis/rest/services/"
    "Survey/Rain_Incidents/MapServer"
)
TARGET_BBOX_WGS84 = (54.2971553, 24.2810331, 54.7659108, 24.601854)
TARGET_CRS = "EPSG:32640"
SNAPSHOT_SCHEMA = "gwm.abu_dhabi_flood.smartmakani_snapshot.v1"
DOWNLOAD_MANIFEST_SCHEMA = "gwm.abu_dhabi_flood.smartmakani_download.v1"
_DATASET_KEY = re.compile(r"[a-z0-9][a-z0-9_]{0,63}")


@dataclass(frozen=True)
class SmartMakaniLayerSpec:
    layer_id: int
    role: str
    out_fields: tuple[str, ...]
    bbox_wgs84: tuple[float, float, float, float] | None
    contains_personal_fields: bool = False
    calibration_admission: str = "not_admitted_for_calibration"
    service_url: str = SMARTMAKANI_MAPSERVER
    dataset_key: str | None = None
    object_id_field: str = "OBJECTID"
    snapshot_bbox_grid: tuple[int, int] | None = None
    snapshot_concurrency: int = 1
    snapshot_request_timeout_seconds: float = 30.0
    page_query_strategy: str = "auto"
    page_concurrency: int = 1
    request_batch_size: int | None = None
    page_request_timeout_seconds: float = 30.0
    nullable_out_fields: tuple[str, ...] = ()
    required_non_null_fields: tuple[str, ...] = ()

    @property
    def endpoint_url(self) -> str:
        return f"{self.service_url.rstrip('/')}/{self.layer_id}"

    @property
    def storage_key(self) -> str:
        key = self.dataset_key or f"layer_{self.layer_id}"
        if not _DATASET_KEY.fullmatch(key):
            raise ValueError(f"invalid_smartmakani_dataset_key:{key}")
        return key


PIPELINE_FIELDS = (
    "OBJECTID",
    "ENABLED",
    "UNIQUE_ID",
    "SOURCE",
    "HANDOVER",
    "CONSTRUCTION_DATE",
    "PIPE_TYPE",
    "PIPE_MATERIAL",
    "INVERT_LEVEL_UP",
    "INVERT_LEVEL_DOWN",
    "SUBTYPE",
    "ASSET_DIAMETER",
    "HYDROID",
    "OUTFALL_NAME",
    "Asset_ID",
    "Sector",
    "O_ID",
    "Start_X",
    "Start_Y",
    "End_X",
    "End_Y",
)

MIMS_MODEL_FIELDS = (
    "OBJECTID",
    "CASE_CATEGORY",
    "CASE_CLOSURE_DATE",
    "CASE_CREATION_DATE",
    "CASE_STATUS",
    "CASE_TYPE_HIERARCHY_ARA",
    "CASE_TYPE_HIERARCHY_ENG",
    "CASE_TYPE_HIERARCHY_SUB_ARA",
    "CASE_TYPE_HIERARCHY_SUB_ENG",
    "AGENCY_NAME_ARABIC",
    "AGENCY_NAME_ENGLISH",
    "ISSUE_STATUS_ARABIC",
    "ISSUE_STATUS_ENGLISH",
    "ROAD_NAME_A",
    "ROAD_NAME_E",
    "SECTOR_NAME_A",
    "SECTOR_NAME_E",
    "ZONE_NAME_A",
    "ZONE_NAME_E",
    "SERVICE_SECTOR_ARABIC",
    "SERVICE_SECTOR_ENGLISH",
    "PLOT_LANDUSE_MAIN",
    "PLOT_LANDUSE_SUB",
    "INSP_RESULT_TYPE_NAME_A",
    "INSP_RESULT_TYPE_NAME_E",
    "INSPECTION_TYPE_NAME_A",
    "INSPECTION_TYPE_NAME_E",
    "PARENT_INSPECTION_TYPE_NAME_A",
    "PARENT_INSPECTION_TYPE_NAME_E",
)

SENSITIVE_MIMS_FIELDS = frozenset(
    {
        "ATTACHMENT_URL",
        "CASE_ID",
        "ONLINE_NUMBER",
        "PAYMENT_RECEIVED_DATE",
        "PAYMENT_STATUS",
        "PLOT_NUMBER",
        "RAISED_BY",
        "RAISED_BY_ARABIC",
        "RAISED_BY_ENGLISH",
        "RECEIVED_AMOUNT",
        "VEHICLE_PLATE_NUMBER",
        "VIOLATOR_NAME_A",
        "VIOLATOR_NAME_E",
        "VIOLATOR_NATIONAL_NUMBER",
        "VIOLATOR_PHONE_NUMBER",
        "VIOLATOR_PHONE_NUMBER_2",
        "VIOLATOR_TRADE_LICENSE_NUMBER",
        "WORKFLOW_INSTANCE_ID",
    }
)

LAYER_SPECS = {
    2: SmartMakaniLayerSpec(
        layer_id=2,
        role="static_rain_incident_points_mainland",
        out_fields=("OBJECTID", "Northing", "Easting", "M", "Site", "Region", "Remark"),
        bbox_wgs84=None,
    ),
    3: SmartMakaniLayerSpec(
        layer_id=3,
        role="static_rain_incident_points_island",
        out_fields=(
            "OBJECTID",
            "REMARKS",
            "POINT_X",
            "POINT_Y",
            "Name",
            "OUTFALL_NA",
            "SL_NO",
        ),
        bbox_wgs84=None,
    ),
    30: SmartMakaniLayerSpec(
        layer_id=30,
        role="historical_mims_incident_view_privacy_minimized",
        out_fields=MIMS_MODEL_FIELDS,
        bbox_wgs84=TARGET_BBOX_WGS84,
    ),
    32: SmartMakaniLayerSpec(
        layer_id=32,
        role="historical_mims_renderer_equivalent_privacy_minimized",
        out_fields=MIMS_MODEL_FIELDS,
        bbox_wgs84=TARGET_BBOX_WGS84,
    ),
    37: SmartMakaniLayerSpec(
        layer_id=37,
        role="stormwater_pipeline_hydraulic_candidate",
        out_fields=PIPELINE_FIELDS,
        bbox_wgs84=TARGET_BBOX_WGS84,
    ),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_bytes(path, canonical_json_bytes(payload))


def _request_contract(spec: SmartMakaniLayerSpec) -> dict[str, Any]:
    contract = {
        "endpoint_url": spec.endpoint_url,
        "layer_id": spec.layer_id,
        "where": "1=1",
        "bbox_wgs84": list(spec.bbox_wgs84) if spec.bbox_wgs84 else None,
        "out_fields": list(spec.out_fields),
        "return_geometry": True,
        "target_crs": TARGET_CRS,
        "contains_personal_fields": spec.contains_personal_fields,
        "calibration_admission": spec.calibration_admission,
    }
    # Preserve the on-disk contract of the already frozen Rain_Incidents layers.
    if spec.dataset_key is not None:
        contract.update(
            {
                "dataset_key": spec.storage_key,
                "object_id_field": spec.object_id_field,
                "access_mode": "query_only",
                "snapshot_bbox_grid": (
                    list(spec.snapshot_bbox_grid)
                    if spec.snapshot_bbox_grid is not None
                    else None
                ),
                "snapshot_concurrency": spec.snapshot_concurrency,
                "snapshot_request_timeout_seconds": (
                    spec.snapshot_request_timeout_seconds
                ),
                "page_query_strategy": spec.page_query_strategy,
                "page_concurrency": spec.page_concurrency,
                "page_request_timeout_seconds": spec.page_request_timeout_seconds,
                "nullable_out_fields": list(spec.nullable_out_fields),
                "required_non_null_fields": list(spec.required_non_null_fields),
            }
        )
    return contract


def _snapshot_from_files(
    layer_root: Path,
    spec: SmartMakaniLayerSpec,
) -> tuple[ArcGISQuerySnapshot, dict[str, Any]] | None:
    descriptor_path = layer_root / "snapshot.json"
    ids_path = layer_root / "object_ids.json"
    if not descriptor_path.exists() and not ids_path.exists():
        return None
    if not descriptor_path.exists() or not ids_path.exists():
        raise ValueError(f"incomplete_local_snapshot_contract:layer_{spec.layer_id}")

    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    object_ids = json.loads(ids_path.read_text(encoding="utf-8"))
    if descriptor.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"unsupported_snapshot_schema:layer_{spec.layer_id}")
    frozen_contract = dict(descriptor.get("request_contract") or {})
    active_contract = _request_contract(spec)
    for transport_key in (
        "snapshot_concurrency",
        "snapshot_request_timeout_seconds",
        "page_query_strategy",
        "page_concurrency",
        "page_request_timeout_seconds",
        "nullable_out_fields",
        "required_non_null_fields",
    ):
        frozen_contract.pop(transport_key, None)
        active_contract.pop(transport_key, None)
    if frozen_contract != active_contract:
        raise ValueError(f"snapshot_request_contract_changed:layer_{spec.layer_id}")
    if not isinstance(object_ids, list):
        raise ValueError(f"invalid_snapshot_object_ids:layer_{spec.layer_id}")
    if sha256_file(ids_path) != descriptor.get("object_ids_sha256"):
        raise ValueError(f"snapshot_object_ids_checksum_mismatch:layer_{spec.layer_id}")
    if len(object_ids) != descriptor.get("record_count"):
        raise ValueError(f"snapshot_object_ids_count_mismatch:layer_{spec.layer_id}")

    snapshot = ArcGISQuerySnapshot(
        query_url=descriptor["query_url"],
        service_url=descriptor["service_url"],
        layer_id=spec.layer_id,
        object_id_field=descriptor["object_id_field"],
        object_ids=tuple(object_ids),
        matched_record_count=descriptor["matched_record_count"],
        where="1=1",
        out_fields=",".join(spec.out_fields),
        return_geometry=True,
        snapshot_strategy=descriptor["snapshot_strategy"],
        page_query_strategy=spec.page_query_strategy,
        page_concurrency=spec.page_concurrency,
        nullable_out_fields=tuple(
            dict.fromkeys((*spec.nullable_out_fields, *spec.required_non_null_fields))
        ),
        request_timeout_seconds=spec.page_request_timeout_seconds,
    )
    return snapshot, descriptor


async def freeze_layer_snapshot(
    layer_root: Path,
    spec: SmartMakaniLayerSpec,
    *,
    connector: ArcGISRestConnector,
) -> tuple[ArcGISQuerySnapshot, dict[str, Any]]:
    """Create or load the immutable ID set for one layer."""

    local = _snapshot_from_files(layer_root, spec)
    if local is not None:
        return local

    query_config = {
        "out_fields": ",".join(spec.out_fields),
        "object_id_field": spec.object_id_field,
        "return_geometry": True,
        "snapshot_strategy": "auto",
        "snapshot_id_page_size": 1000,
        "snapshot_page_query_strategy": "auto",
        "snapshot_page_concurrency": spec.page_concurrency,
        "snapshot_nullable_out_fields": list(
            dict.fromkeys((*spec.nullable_out_fields, *spec.required_non_null_fields))
        ),
    }
    query_config["snapshot_page_query_strategy"] = spec.page_query_strategy
    if spec.snapshot_bbox_grid is not None:
        snapshot = await _create_tiled_query_snapshot(
            spec,
            connector=connector,
            query_config=query_config,
        )
    else:
        snapshot = await connector.create_query_snapshot(
            spec.endpoint_url,
            {},
            query_config,
            bbox=list(spec.bbox_wgs84) if spec.bbox_wgs84 else None,
            max_records=1_000_000,
        )
    if snapshot.truncated:
        raise RuntimeError(
            f"source_snapshot_truncated:layer_{spec.layer_id}:"
            f"{snapshot.record_count}/{snapshot.matched_record_count}"
        )

    ids_path = layer_root / "object_ids.json"
    _atomic_write_json(ids_path, list(snapshot.object_ids))
    descriptor: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "created_at": utc_now(),
        "request_contract": _request_contract(spec),
        "query_url": snapshot.query_url,
        "service_url": snapshot.service_url,
        "object_id_field": snapshot.object_id_field,
        "record_count": snapshot.record_count,
        "matched_record_count": snapshot.matched_record_count,
        "truncated": snapshot.truncated,
        "snapshot_strategy": snapshot.snapshot_strategy,
        "page_query_strategy": snapshot.page_query_strategy,
        "page_concurrency": snapshot.page_concurrency,
        "object_ids_path": "object_ids.json",
        "object_ids_sha256": sha256_file(ids_path),
    }
    fingerprint_payload = {
        key: value
        for key, value in descriptor.items()
        if key not in {"created_at", "snapshot_fingerprint"}
    }
    descriptor["snapshot_fingerprint"] = sha256_bytes(
        canonical_json_bytes(fingerprint_payload)
    )
    _atomic_write_json(layer_root / "snapshot.json", descriptor)
    return snapshot, descriptor


def _bbox_tiles(
    bbox: tuple[float, float, float, float],
    grid: tuple[int, int],
) -> list[list[float]]:
    columns, rows = grid
    if not 1 <= columns <= 64 or not 1 <= rows <= 64:
        raise ValueError("snapshot_bbox_grid_dimensions_must_be_between_1_and_64")
    xmin, ymin, xmax, ymax = bbox
    if not xmin < xmax or not ymin < ymax:
        raise ValueError("snapshot_bbox_grid_requires_valid_bbox")
    width = (xmax - xmin) / columns
    height = (ymax - ymin) / rows
    return [
        [
            xmin + column * width,
            ymin + row * height,
            xmax if column == columns - 1 else xmin + (column + 1) * width,
            ymax if row == rows - 1 else ymin + (row + 1) * height,
        ]
        for row in range(rows)
        for column in range(columns)
    ]


async def _create_tiled_query_snapshot(
    spec: SmartMakaniLayerSpec,
    *,
    connector: ArcGISRestConnector,
    query_config: dict[str, Any],
) -> ArcGISQuerySnapshot:
    import httpx

    if spec.bbox_wgs84 is None or spec.snapshot_bbox_grid is None:
        raise ValueError("tiled_snapshot_requires_bbox_and_grid")
    tiles = _bbox_tiles(spec.bbox_wgs84, spec.snapshot_bbox_grid)
    concurrency = max(1, min(int(spec.snapshot_concurrency), 8))
    semaphore = asyncio.Semaphore(concurrency)
    query_url = f"{spec.endpoint_url}/query"

    async def freeze_tile(
        client: httpx.AsyncClient,
        tile: list[float],
        *,
        depth: int = 0,
    ) -> tuple[str, list[Any]]:
        last_error: Exception | None = None
        attempts = 2 if depth < 2 else 3
        for attempt in range(attempts):
            try:
                async with semaphore:
                    response = await client.get(
                        query_url,
                        params={
                            "where": "1=1",
                            "geometry": ",".join(str(value) for value in tile),
                            "geometryType": "esriGeometryEnvelope",
                            "inSR": "4326",
                            "spatialRel": "esriSpatialRelIntersects",
                            "returnIdsOnly": "true",
                            "returnGeometry": "false",
                            "f": "json",
                        },
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("tiled_snapshot_response_must_be_object")
                if error := payload.get("error"):
                    raise RuntimeError(
                        "tiled_snapshot_query_failed:"
                        f"{error.get('code')}:{error.get('message')}"
                    )
                object_ids = payload.get("objectIds")
                if object_ids is None and payload.get("objectIdFieldName"):
                    object_ids = []
                if not isinstance(object_ids, list):
                    raise ValueError("tiled_snapshot_missing_object_ids")
                object_id_field = str(
                    payload.get("objectIdFieldName") or spec.object_id_field
                )
                return object_id_field, object_ids
            except Exception as exc:
                last_error = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
        if depth < 2:
            subtiles = _bbox_tiles(tuple(tile), (2, 2))
            results = await asyncio.gather(
                *(freeze_tile(client, item, depth=depth + 1) for item in subtiles)
            )
            fields = {field for field, _ in results}
            if len(fields) != 1:
                raise ValueError(
                    f"tiled_snapshot_object_id_field_changed:{spec.storage_key}"
                )
            return next(iter(fields)), list(
                {object_id for _, ids in results for object_id in ids}
            )
        assert last_error is not None
        raise last_error

    _ = connector
    request_timeout = float(spec.snapshot_request_timeout_seconds)
    if not 1.0 <= request_timeout <= 600.0:
        raise ValueError("snapshot_request_timeout_seconds_must_be_between_1_and_600")
    timeout = httpx.Timeout(request_timeout, connect=min(30.0, request_timeout))
    async with httpx.AsyncClient(timeout=timeout) as client:
        tile_results = await asyncio.gather(
            *(freeze_tile(client, tile) for tile in tiles)
        )
    object_id_fields = {item[0] for item in tile_results}
    if len(object_id_fields) != 1:
        raise ValueError(f"tiled_snapshot_object_id_field_changed:{spec.storage_key}")
    object_ids = tuple(
        sorted(
            {object_id for _, ids in tile_results for object_id in ids},
            key=lambda value: (str(type(value)), value),
        )
    )
    return ArcGISQuerySnapshot(
        query_url=query_url,
        service_url=spec.service_url,
        layer_id=spec.layer_id,
        object_id_field=next(iter(object_id_fields)),
        object_ids=object_ids,
        matched_record_count=len(object_ids),
        where="1=1",
        out_fields=str(query_config["out_fields"]),
        return_geometry=bool(query_config["return_geometry"]),
        snapshot_strategy=(
            "tiled_return_ids_only_"
            f"{spec.snapshot_bbox_grid[0]}x{spec.snapshot_bbox_grid[1]}"
        ),
        page_query_strategy=spec.page_query_strategy,
        page_concurrency=spec.page_concurrency,
        request_timeout_seconds=spec.page_request_timeout_seconds,
    )


def _page_contract(object_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(object_ids)
    return {
        "record_count": len(values),
        "first_object_id": values[0] if values else None,
        "last_object_id": values[-1] if values else None,
        "object_ids_sha256": sha256_bytes(canonical_json_bytes(values)),
    }


def _valid_existing_page(
    layer_root: Path,
    entry: dict[str, Any] | None,
    expected_ids: tuple[Any, ...],
    required_fields: tuple[str, ...] = (),
    required_non_null_fields: tuple[str, ...] = (),
) -> bool:
    if not entry:
        return False
    expected = _page_contract(expected_ids)
    if any(entry.get(key) != value for key, value in expected.items()):
        return False
    relative_path = entry.get("path")
    if not isinstance(relative_path, str):
        return False
    path = layer_root / relative_path
    valid_file = (
        path.is_file()
        and path.stat().st_size == entry.get("size_bytes")
        and sha256_file(path) == entry.get("sha256")
    )
    if not valid_file or not (required_fields or required_non_null_fields):
        return valid_file
    payload = json.loads(path.read_text(encoding="utf-8"))
    observed_fields = {
        key
        for feature in payload.get("features", [])
        for key in (feature.get("properties") or {})
    }
    if not set(required_fields).issubset(observed_fields):
        return False
    return all(
        any(
            (feature.get("properties") or {}).get(field) is not None
            for feature in payload.get("features", [])
        )
        for field in required_non_null_fields
    )


def _frame_object_ids(frame: Any, field: str) -> list[Any]:
    matching = next(
        (column for column in frame.columns if str(column).casefold() == field.casefold()),
        None,
    )
    if matching is None:
        raise ValueError(f"downloaded_page_missing_object_id_field:{field}")
    return list(frame[matching])


def _geojson_bytes(frame: Any) -> bytes:
    # GeoPandas includes an explicit CRS member for projected GeoJSON output.
    return (
        frame.to_json(
            drop_id=True,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            to_wgs84=False,
        )
        + "\n"
    ).encode("utf-8")


def _consecutive_runs(indices: list[int]) -> list[tuple[int, int]]:
    if not indices:
        return []
    runs: list[tuple[int, int]] = []
    start = previous = indices[0]
    for index in indices[1:]:
        if index != previous + 1:
            runs.append((start, previous + 1))
            start = index
        previous = index
    runs.append((start, previous + 1))
    return runs


async def _download_layer_unchecked(
    dataset_root: Path,
    spec: SmartMakaniLayerSpec,
    *,
    connector: ArcGISRestConnector | None = None,
    page_size: int = 1000,
) -> dict[str, Any]:
    """Download one layer with immutable IDs, checksums and resume support."""

    if not 1 <= page_size <= 1000:
        raise ValueError("page_size_must_be_between_1_and_1000")
    if spec.contains_personal_fields:
        raise ValueError(f"personal_fields_not_allowed:layer_{spec.layer_id}")
    if SENSITIVE_MIMS_FIELDS.intersection(spec.out_fields):
        raise ValueError(f"sensitive_field_in_download_contract:layer_{spec.layer_id}")

    active_connector = connector or ArcGISRestConnector()
    layer_root = (
        dataset_root.resolve()
        / "online"
        / "smartmakani"
        / "features"
        / spec.storage_key
    )
    pages_root = layer_root / "pages"
    pages_root.mkdir(parents=True, exist_ok=True)
    snapshot, descriptor = await freeze_layer_snapshot(
        layer_root,
        spec,
        connector=active_connector,
    )
    manifest_path = layer_root / "snapshot_manifest.json"
    existing_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )
    if existing_manifest and existing_manifest.get("snapshot_fingerprint") != descriptor[
        "snapshot_fingerprint"
    ]:
        raise ValueError(f"download_manifest_snapshot_changed:layer_{spec.layer_id}")
    existing_pages = {
        int(item["page_index"]): item
        for item in existing_manifest.get("pages", [])
        if isinstance(item, dict) and "page_index" in item
    }

    page_count = (snapshot.record_count + page_size - 1) // page_size
    expected_by_page = {
        index: snapshot.object_ids[index * page_size : (index + 1) * page_size]
        for index in range(page_count)
    }
    complete_pages = {
        index: entry
        for index, expected_ids in expected_by_page.items()
        if _valid_existing_page(
            layer_root,
            existing_pages.get(index),
            expected_ids,
            spec.nullable_out_fields,
            spec.required_non_null_fields,
        )
        for entry in (existing_pages[index],)
    }
    missing_indices = sorted(set(expected_by_page) - set(complete_pages))
    started_at = existing_manifest.get("started_at") or utc_now()
    request_batch_size = min(page_size, spec.request_batch_size or page_size)
    if request_batch_size < 1:
        raise ValueError("request_batch_size_must_be_positive")

    def current_manifest(status: str, error: str | None = None) -> dict[str, Any]:
        pages = [complete_pages[index] for index in sorted(complete_pages)]
        payload: dict[str, Any] = {
            "schema": DOWNLOAD_MANIFEST_SCHEMA,
            "layer_id": spec.layer_id,
            "role": spec.role,
            "source_url": spec.endpoint_url,
            "dataset_key": spec.storage_key,
            "access_mode": "query_only",
            "started_at": started_at,
            "updated_at": utc_now(),
            "status": status,
            "snapshot_fingerprint": descriptor["snapshot_fingerprint"],
            "snapshot_path": "snapshot.json",
            "page_size": page_size,
            "request_batch_size": request_batch_size,
            "expected_page_count": page_count,
            "completed_page_count": len(pages),
            "expected_record_count": snapshot.record_count,
            "completed_record_count": sum(item["record_count"] for item in pages),
            "target_crs": TARGET_CRS,
            "out_fields": list(spec.out_fields),
            "public_feature_rows": True,
            "contains_personal_fields": False,
            "calibration_admission": spec.calibration_admission,
            "pages": pages,
        }
        if error:
            payload["last_error"] = error
        if status == "complete":
            payload["completed_at"] = utc_now()
            payload["content_fingerprint"] = sha256_bytes(
                canonical_json_bytes(
                    {
                        "snapshot_fingerprint": descriptor["snapshot_fingerprint"],
                        "page_sha256": [item["sha256"] for item in pages],
                    }
                )
            )
        return payload

    _atomic_write_json(
        manifest_path,
        current_manifest("complete" if not missing_indices else "in_progress"),
    )

    def persist_page(page_index: int, frame: Any) -> None:
        expected_ids = expected_by_page[page_index]
        actual_ids = _frame_object_ids(frame, snapshot.object_id_field)
        if actual_ids != list(expected_ids):
            raise ValueError(
                f"downloaded_page_object_ids_mismatch:"
                f"layer_{spec.layer_id}:page_{page_index}"
            )
        payload = _geojson_bytes(frame)
        relative_path = f"pages/page_{page_index:06d}.geojson"
        output_path = layer_root / relative_path
        _atomic_write_bytes(output_path, payload)
        complete_pages[page_index] = {
            "page_index": page_index,
            "path": relative_path,
            **_page_contract(expected_ids),
            "size_bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
        _atomic_write_json(manifest_path, current_manifest("in_progress"))

    try:
        if request_batch_size < page_size:
            import geopandas as gpd
            import pandas as pd

            for page_index in missing_indices:
                expected_ids = expected_by_page[page_index]
                page_snapshot = replace(
                    snapshot,
                    object_ids=expected_ids,
                    matched_record_count=len(expected_ids),
                )
                frames = []
                async for subpage in active_connector.iter_snapshot_pages(
                    page_snapshot,
                    {},
                    page_size=request_batch_size,
                    target_crs=TARGET_CRS,
                ):
                    frames.append(subpage["frame"])
                frame = gpd.GeoDataFrame(
                    pd.concat(frames, ignore_index=True),
                    geometry="geometry",
                    crs=TARGET_CRS,
                )
                persist_page(page_index, frame)
        else:
            for run_start, run_end in _consecutive_runs(missing_indices):
                first_id_index = run_start * page_size
                last_id_index = min(run_end * page_size, snapshot.record_count)
                run_snapshot = replace(
                    snapshot,
                    object_ids=snapshot.object_ids[first_id_index:last_id_index],
                    matched_record_count=last_id_index - first_id_index,
                )
                async for page in active_connector.iter_snapshot_pages(
                    run_snapshot,
                    {},
                    page_size=page_size,
                    target_crs=TARGET_CRS,
                ):
                    persist_page(
                        run_start + int(page["batch_index"]),
                        page["frame"],
                    )
    except Exception as exc:
        _atomic_write_json(manifest_path, current_manifest("incomplete", str(exc)))
        raise

    manifest = current_manifest("complete")
    if manifest["completed_record_count"] != snapshot.record_count:
        raise RuntimeError(f"download_record_count_incomplete:layer_{spec.layer_id}")
    _atomic_write_json(manifest_path, manifest)
    return manifest


async def download_layer(
    dataset_root: Path,
    spec: SmartMakaniLayerSpec,
    *,
    connector: ArcGISRestConnector | None = None,
    page_size: int = 1000,
) -> dict[str, Any]:
    """Acquire one allowlisted layer behind live SPR and immutable audit."""

    # Unit tests inject a non-ArcGIS connector so the download/compiler logic
    # can be exercised without the deployment-only governance services. The
    # production ArcGIS path remains fail-closed when those services are not
    # installed in the host application.
    if connector is not None and not isinstance(connector, ArcGISRestConnector):
        return await _download_layer_unchecked(
            dataset_root,
            spec,
            connector=connector,
            page_size=page_size,
        )

    try:
        from data_agent.governed_external_access import GovernedExternalAccessService
        from data_agent.governed_query_security import resolve_governed_query_security_ports
        from data_agent.user_context import current_tenant_id, current_user_role
    except ImportError as exc:
        raise RuntimeError(
            "governed_external_access_dependencies_required_for_arcgis_acquisition"
        ) from exc

    tenant_id = current_tenant_id.get().strip()
    role = current_user_role.get().strip() or "dataops"
    security_ports = resolve_governed_query_security_ports(tenant_id)
    request_payload = {
        "layer_id": spec.layer_id,
        "dataset_key": spec.storage_key,
        "role": spec.role,
        "out_fields": list(spec.out_fields),
        "bbox_wgs84": list(spec.bbox_wgs84) if spec.bbox_wgs84 else None,
        "page_size": page_size,
        "snapshot_bbox_grid": (
            list(spec.snapshot_bbox_grid) if spec.snapshot_bbox_grid else None
        ),
        "snapshot_concurrency": spec.snapshot_concurrency,
        "page_query_strategy": spec.page_query_strategy,
        "page_concurrency": spec.page_concurrency,
    }
    return await GovernedExternalAccessService().execute_async(
        tenant_id=tenant_id,
        actor_subject="workload:smartmakani-acquisition",
        roles=(role,),
        channel="observation_provider",
        adapter_id="gda.smartmakani.arcgis.v1",
        access_mode="acquire",
        resource_refs=(
            f"provider:smartmakani/layers/{spec.storage_key}",
        ),
        request_payload=request_payload,
        action="observation.provider.acquire",
        operation=lambda: _download_layer_unchecked(
            dataset_root,
            spec,
            connector=connector,
            page_size=page_size,
        ),
        security_reader=security_ports[0] if security_ports else None,
    )


async def download_layers(
    dataset_root: Path,
    *,
    layer_ids: Iterable[int] = (2, 3, 30, 32, 37),
    page_size: int = 1000,
    connector: ArcGISRestConnector | None = None,
) -> list[dict[str, Any]]:
    active_connector = connector or ArcGISRestConnector()
    manifests = []
    for layer_id in layer_ids:
        try:
            spec = LAYER_SPECS[int(layer_id)]
        except KeyError as exc:
            raise ValueError(f"unsupported_smartmakani_layer:{layer_id}") from exc
        manifests.append(
            await download_layer(
                dataset_root,
                spec,
                connector=active_connector,
                page_size=page_size,
            )
        )
    return manifests


def layer_specs_as_dicts() -> list[dict[str, Any]]:
    return [asdict(LAYER_SPECS[layer_id]) for layer_id in sorted(LAYER_SPECS)]
