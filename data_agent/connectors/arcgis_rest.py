"""Read-only ArcGIS REST FeatureServer / MapServer connector.

The connector supports service-directory discovery and deterministic feature
queries. Feature reads prefer an object-ID snapshot so a changing upstream
service cannot silently duplicate or skip records between offset pages.
"""

import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from . import HTTP_TIMEOUT, BaseConnector, ConnectorRegistry, build_auth_headers

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RECORDS = 5000
_ABSOLUTE_MAX_RECORDS = 1_000_000
_DEFAULT_PAGE_SIZE = 2000
_MAX_PAGE_SIZE = 5000
_MAX_RETRIES = 5
_DEFAULT_SNAPSHOT_ID_PAGE_SIZE = 4000
_MAX_SNAPSHOT_RANGE_CONCURRENCY = 16
_SNAPSHOT_STRATEGIES = frozenset({
    "auto",
    "return_ids_only",
    "ordered_id_paging",
    "object_id_range_paging",
})
_MAX_DISCOVERY_FOLDERS = 50
_MAX_DISCOVERY_SERVICES = 100
_DISCOVERY_CONCURRENCY = 8
_OBJECT_ID_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SERVICE_TARGET = re.compile(
    r"/(?P<service_type>FeatureServer|MapServer)(?:/(?P<layer_id>\d+))?/?$",
    re.IGNORECASE,
)


class _ArcGISResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArcGISQuerySnapshot:
    """Immutable feature identity set used by one ingestion run."""

    query_url: str
    service_url: str
    layer_id: int
    object_id_field: str
    object_ids: tuple[Any, ...]
    matched_record_count: int
    where: str
    out_fields: str
    return_geometry: bool
    snapshot_strategy: str
    page_query_strategy: str = "auto"
    page_concurrency: int = 1
    nullable_out_fields: tuple[str, ...] = ()
    default_null_out_fields: tuple[str, ...] = ()
    request_timeout_seconds: float = HTTP_TIMEOUT

    @property
    def record_count(self) -> int:
        return len(self.object_ids)

    @property
    def truncated(self) -> bool:
        return self.record_count < self.matched_record_count


def _clean_url(url: str) -> str:
    parts = urlsplit(str(url).strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _service_target(url: str) -> tuple[str, int | None] | None:
    """Return a normalized service root and optional layer ID."""
    cleaned = _clean_url(url)
    parts = urlsplit(cleaned)
    match = _SERVICE_TARGET.search(parts.path)
    if not match:
        return None
    service_path = parts.path[: match.start()] + f"/{match.group('service_type')}"
    service_url = urlunsplit((parts.scheme, parts.netloc, service_path, "", ""))
    layer_id = match.group("layer_id")
    return service_url, int(layer_id) if layer_id is not None else None


def _services_root(url: str) -> str:
    """Return the ArcGIS ``.../rest/services`` root for a directory URL."""
    cleaned = _clean_url(url)
    parts = urlsplit(cleaned)
    marker = "/rest/services"
    marker_index = parts.path.lower().find(marker)
    if marker_index < 0:
        return cleaned
    root_path = parts.path[: marker_index + len(marker)]
    return urlunsplit((parts.scheme, parts.netloc, root_path, "", ""))


def _positive_int(value: Any, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _object_id_sort_key(value: Any) -> tuple[int, int, str]:
    raw = str(value)
    if re.fullmatch(r"-?\d+", raw):
        return 0, int(raw), ""
    return 1, 0, raw


def _error_result(data: dict) -> dict | None:
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    return {
        "status": "error",
        "code": error.get("code"),
        "message": error.get("message", str(error)),
    }


def _sanitize_geojson_geometry(geometry: Any) -> dict | None:
    """Keep a feature row when ArcGIS emits a malformed/null geometry."""
    if not isinstance(geometry, dict):
        return None

    def valid_coordinates(value: Any) -> bool:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return math.isfinite(float(value))
        if isinstance(value, (list, tuple)):
            return bool(value) and all(valid_coordinates(item) for item in value)
        return False

    if geometry.get("type") == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, list) or not geometries:
            return None
        if any(_sanitize_geojson_geometry(item) is None for item in geometries):
            return None
    elif not valid_coordinates(geometry.get("coordinates")):
        return None
    try:
        from shapely.geometry import shape

        shape(geometry)
    except (AttributeError, TypeError, ValueError):
        return None
    return geometry


async def _get_json(
    client,
    url: str,
    *,
    params: dict,
    headers: dict,
    max_attempts: int = _MAX_RETRIES,
    method: str = "GET",
) -> dict:
    """Request JSON with bounded retries for transient transport/server failures."""
    import httpx

    attempts = max(1, int(max_attempts))
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            if method == "POST":
                response = await client.post(url, data=params, headers=headers)
            else:
                response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("ArcGIS REST response must be a JSON object")
            error = data.get("error")
            error_code = error.get("code") if isinstance(error, dict) else None
            if error_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                await asyncio.sleep(0.25 * (2**attempt))
                continue
            return data
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status is None or status == 429 or status >= 500
            if not retryable or attempt == attempts - 1:
                raise
            await asyncio.sleep(0.25 * (2**attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("ArcGIS REST request failed")


class ArcGISRestConnector(BaseConnector):
    SOURCE_TYPE = "arcgis_rest"

    async def create_query_snapshot(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: list[float] | None = None,
        filter_expr: str | None = None,
        max_records: int | None = None,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> ArcGISQuerySnapshot:
        """Freeze ordered feature IDs before a multi-page ingestion.

        ArcGIS offset pagination can duplicate or skip rows while a service is
        changing. A returnIdsOnly snapshot gives the ingestion run a stable,
        replayable source slice and a deterministic progress denominator.
        """
        import httpx

        target = _service_target(endpoint_url)
        if target is None:
            raise ValueError(
                "ArcGIS ingestion requires a FeatureServer or MapServer service URL"
            )
        service_url, endpoint_layer_id = target
        layer_id = endpoint_layer_id
        if layer_id is None:
            layer_id = int(query_config.get("layer_id", 0))

        where = str(filter_expr or query_config.get("where", "1=1"))
        out_fields = str(query_config.get("out_fields", "*"))
        raw_nullable_out_fields = query_config.get(
            "snapshot_nullable_out_fields", (),
        )
        if isinstance(raw_nullable_out_fields, str):
            raw_nullable_out_fields = raw_nullable_out_fields.split(",")
        if not isinstance(raw_nullable_out_fields, (list, tuple)):
            raise ValueError("snapshot_nullable_out_fields must be a list")
        nullable_out_fields = tuple(
            str(field).strip()
            for field in raw_nullable_out_fields
            if str(field).strip()
        )
        if any(not _OBJECT_ID_FIELD.fullmatch(field) for field in nullable_out_fields):
            raise ValueError(
                "snapshot_nullable_out_fields must contain simple field names"
            )
        raw_default_null_out_fields = query_config.get(
            "snapshot_default_null_out_fields", (),
        )
        if isinstance(raw_default_null_out_fields, str):
            raw_default_null_out_fields = raw_default_null_out_fields.split(",")
        if not isinstance(raw_default_null_out_fields, (list, tuple)):
            raise ValueError("snapshot_default_null_out_fields must be a list")
        default_null_out_fields = tuple(
            str(field).strip()
            for field in raw_default_null_out_fields
            if str(field).strip()
        )
        if any(
            not _OBJECT_ID_FIELD.fullmatch(field)
            for field in default_null_out_fields
        ):
            raise ValueError(
                "snapshot_default_null_out_fields must contain simple field names"
            )
        return_geometry = bool(query_config.get("return_geometry", True))
        query_url = f"{service_url}/{layer_id}/query"
        filter_params = self._filter_params(where, bbox)
        headers = build_auth_headers(auth_config)
        object_id_field = str(query_config.get("object_id_field", "OBJECTID"))
        snapshot_strategy = str(
            query_config.get("snapshot_strategy", "auto")
        ).strip().lower()
        if snapshot_strategy not in _SNAPSHOT_STRATEGIES:
            raise ValueError(
                "snapshot_strategy must be auto, return_ids_only, "
                "ordered_id_paging, or object_id_range_paging"
            )
        if not _OBJECT_ID_FIELD.fullmatch(object_id_field):
            raise ValueError("object_id_field must be a simple ArcGIS field name")

        data: dict[str, Any] = {}
        raw_ids: list[Any] | None = None
        matched_record_count: int | None = None
        strategy_used = "return_ids_only"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            if snapshot_strategy not in {"ordered_id_paging", "object_id_range_paging"}:
                try:
                    data = await _get_json(
                        client,
                        query_url,
                        params={
                            **filter_params,
                            "returnIdsOnly": "true",
                            "returnGeometry": "false",
                            "f": "json",
                        },
                        headers=headers,
                        # A deterministic ordered-page fallback exists, so a single
                        # slow all-ID request must not stall a durable worker lease.
                        max_attempts=1,
                    )
                    if error := _error_result(data):
                        raise _ArcGISResponseError(error["message"])
                    candidate_ids = data.get("objectIds")
                    if not isinstance(candidate_ids, list):
                        raise _ArcGISResponseError(
                            "ArcGIS layer did not return an objectIds array"
                        )
                    raw_ids = candidate_ids
                    object_id_field = str(
                        data.get("objectIdFieldName") or object_id_field
                    )
                    if not _OBJECT_ID_FIELD.fullmatch(object_id_field):
                        raise _ArcGISResponseError(
                            "ArcGIS returned an invalid object ID field name"
                        )
                    matched_record_count = len(raw_ids)
                    if progress_callback is not None:
                        await progress_callback()
                except Exception as exc:
                    if snapshot_strategy == "return_ids_only":
                        raise
                    logger.warning(
                        "ArcGIS returnIdsOnly snapshot failed for %s; "
                        "falling back to ordered ID pagination: %s",
                        query_url,
                        exc,
                    )

            if raw_ids is None and snapshot_strategy == "object_id_range_paging":
                dense_range_value = query_config.get(
                    "snapshot_id_dense_range_size"
                )
                raw_ids, matched_record_count = await self._ranged_object_id_snapshot(
                    client,
                    query_url,
                    headers,
                    filter_params,
                    object_id_field=object_id_field,
                    max_records=max_records,
                    page_size=_positive_int(
                        query_config.get("snapshot_id_page_size"),
                        _DEFAULT_SNAPSHOT_ID_PAGE_SIZE,
                        _MAX_PAGE_SIZE,
                    ),
                    range_size=_positive_int(
                        query_config.get("snapshot_id_range_size"),
                        50_000,
                        10_000_000,
                    ),
                    dense_range_size=(
                        _positive_int(dense_range_value, 250, _MAX_PAGE_SIZE)
                        if dense_range_value is not None
                        else None
                    ),
                    range_concurrency=_positive_int(
                        query_config.get("snapshot_id_range_concurrency"),
                        1,
                        _MAX_SNAPSHOT_RANGE_CONCURRENCY,
                    ),
                    contiguous_range_stats=bool(
                        query_config.get("snapshot_id_contiguous_range_stats", False)
                    ),
                    progress_callback=progress_callback,
                )
                strategy_used = "object_id_range_paging"
            elif raw_ids is None:
                raw_ids, matched_record_count = await self._paged_object_id_snapshot(
                    client,
                    query_url,
                    headers,
                    filter_params,
                    object_id_field=object_id_field,
                    max_records=max_records,
                    page_size=_positive_int(
                        query_config.get("snapshot_id_page_size"),
                        _DEFAULT_SNAPSHOT_ID_PAGE_SIZE,
                        _MAX_PAGE_SIZE,
                    ),
                    progress_callback=progress_callback,
                )
                strategy_used = "ordered_id_paging"

        object_ids = sorted(
            dict.fromkeys(raw_ids),
            key=_object_id_sort_key,
        )
        matched_record_count = (
            len(object_ids)
            if matched_record_count is None
            else matched_record_count
        )
        if max_records is not None:
            bounded_max = max(0, min(int(max_records), _ABSOLUTE_MAX_RECORDS))
            object_ids = object_ids[:bounded_max]
        return ArcGISQuerySnapshot(
            query_url=query_url,
            service_url=service_url,
            layer_id=layer_id,
            object_id_field=object_id_field,
            object_ids=tuple(object_ids),
            matched_record_count=matched_record_count,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            snapshot_strategy=strategy_used,
            page_query_strategy=str(
                query_config.get("snapshot_page_query_strategy", "auto")
            ).strip().lower(),
            page_concurrency=_positive_int(
                query_config.get("snapshot_page_concurrency"),
                1,
                _MAX_SNAPSHOT_RANGE_CONCURRENCY,
            ),
            nullable_out_fields=nullable_out_fields,
            default_null_out_fields=default_null_out_fields,
        )

    async def _ranged_object_id_snapshot(
        self,
        client,
        query_url: str,
        headers: dict,
        filter_params: dict[str, str],
        *,
        object_id_field: str,
        max_records: int | None,
        page_size: int,
        range_size: int,
        dense_range_size: int | None,
        range_concurrency: int,
        contiguous_range_stats: bool,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[list[Any], int]:
        """Enumerate OIDs in bounded value ranges for slow high-offset services."""
        statistics_data = await _get_json(
            client,
            query_url,
            params={
                **filter_params,
                "outStatistics": (
                    '[{"statisticType":"min","onStatisticField":"'
                    f'{object_id_field}","outStatisticFieldName":"min_oid"}},'
                    '{"statisticType":"max","onStatisticField":"'
                    f'{object_id_field}","outStatisticFieldName":"max_oid"}},'
                    '{"statisticType":"count","onStatisticField":"'
                    f'{object_id_field}","outStatisticFieldName":"record_count"}}]'
                ),
                "returnGeometry": "false",
                "f": "json",
            },
            headers=headers,
        )
        if error := _error_result(statistics_data):
            raise _ArcGISResponseError(error["message"])
        attributes = statistics_data["features"][0]["attributes"]
        minimum = int(attributes["min_oid"])
        maximum = int(attributes["max_oid"])
        matched_record_count = int(attributes["record_count"])
        if progress_callback is not None:
            await progress_callback()

        record_limit = matched_record_count
        if max_records is not None:
            record_limit = min(record_limit, max(0, int(max_records)))
        object_ids: list[Any] = []
        base_where = str(filter_params.get("where", "1=1")).strip()
        serialized_progress = progress_callback
        if progress_callback is not None and range_concurrency > 1:
            progress_lock = asyncio.Lock()

            async def serialized_progress() -> None:
                async with progress_lock:
                    await progress_callback()

        range_bounds = [
            (lower, min(maximum, lower + range_size - 1))
            for lower in range(minimum, maximum + 1, range_size)
        ]
        nested_range_concurrency = (
            1 if range_concurrency > 1 and len(range_bounds) > 1
            else range_concurrency
        )

        async def query_range(bounds: tuple[int, int]) -> list[Any]:
            lower, upper = bounds
            return await self._query_object_id_range(
                client,
                query_url,
                headers,
                filter_params,
                object_id_field=object_id_field,
                base_where=base_where,
                lower=lower,
                upper=upper,
                page_size=page_size,
                dense_range_size=dense_range_size,
                range_concurrency=nested_range_concurrency,
                contiguous_range_stats=contiguous_range_stats,
                progress_callback=serialized_progress,
            )

        if range_concurrency == 1 or len(range_bounds) <= 1:
            range_results = [
                await query_range(bounds) for bounds in range_bounds
            ]
        else:
            semaphore = asyncio.Semaphore(range_concurrency)

            async def bounded_query(bounds: tuple[int, int]) -> list[Any]:
                async with semaphore:
                    return await query_range(bounds)

            range_results = await asyncio.gather(*(
                bounded_query(bounds) for bounds in range_bounds
            ))

        for range_ids in range_results:
            object_ids.extend(range_ids)
            if len(object_ids) >= record_limit:
                break

        unique_ids = sorted(
            dict.fromkeys(object_ids),
            key=_object_id_sort_key,
        )
        return unique_ids[:record_limit], matched_record_count

    async def _query_object_id_range(
        self,
        client,
        query_url: str,
        headers: dict,
        filter_params: dict[str, str],
        *,
        object_id_field: str,
        base_where: str,
        lower: int,
        upper: int,
        page_size: int,
        dense_range_size: int | None,
        range_concurrency: int = 1,
        contiguous_range_stats: bool = False,
        transport_retries_remaining: int = 2,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> list[Any]:
        """Read one OID range, recursively splitting hot ranges on failure."""
        range_where = (
            f"{object_id_field} BETWEEN {lower} AND {upper}"
            if base_where.replace(" ", "") == "1=1"
            else (
                f"({base_where}) AND "
                f"{object_id_field} BETWEEN {lower} AND {upper}"
            )
        )
        if (
            contiguous_range_stats
            and dense_range_size is not None
            and upper - lower + 1 > dense_range_size
        ):
            contiguous_ids = await self._verified_contiguous_range_ids(
                client,
                query_url,
                headers,
                filter_params,
                object_id_field=object_id_field,
                range_where=range_where,
                lower=lower,
                upper=upper,
                progress_callback=progress_callback,
            )
            if contiguous_ids is not None:
                logger.info(
                    "ArcGIS OID range %d-%d verified as contiguous; "
                    "materializing %d IDs from authoritative statistics",
                    lower,
                    upper,
                    len(contiguous_ids),
                )
                return contiguous_ids
        try:
            range_ids: list[Any] = []
            offset = 0
            while True:
                page_data = await _get_json(
                    client,
                    query_url,
                    params={
                        **filter_params,
                        "where": range_where,
                        "outFields": object_id_field,
                        "returnGeometry": "false",
                        "orderByFields": f"{object_id_field} ASC",
                        "resultOffset": str(offset),
                        "resultRecordCount": str(page_size),
                        "f": "json",
                    },
                    headers=headers,
                    max_attempts=1,
                )
                if error := _error_result(page_data):
                    raise _ArcGISResponseError(error["message"])
                features = page_data.get("features")
                if not isinstance(features, list):
                    raise _ArcGISResponseError(
                        "ArcGIS ranged ID page did not contain a features array"
                    )
                for feature in features:
                    feature_attributes = (
                        feature.get("attributes") if isinstance(feature, dict) else None
                    )
                    if isinstance(feature_attributes, dict):
                        value = feature_attributes.get(object_id_field)
                        if value is not None:
                            range_ids.append(value)
                if progress_callback is not None:
                    await progress_callback()
                if not features:
                    break
                offset += len(features)
                if len(features) < page_size and not page_data.get("exceededTransferLimit"):
                    break
            return range_ids
        except Exception as exc:
            if lower >= upper:
                raise
            import httpx

            span = upper - lower + 1
            if (
                contiguous_range_stats
                and dense_range_size is not None
                and span > dense_range_size
            ):
                contiguous_ids = await self._verified_contiguous_range_ids(
                    client,
                    query_url,
                    headers,
                    filter_params,
                    object_id_field=object_id_field,
                    range_where=range_where,
                    lower=lower,
                    upper=upper,
                    progress_callback=progress_callback,
                )
                if contiguous_ids is not None:
                    logger.info(
                        "ArcGIS OID range %d-%d verified as contiguous; "
                        "materializing %d IDs from authoritative statistics",
                        lower,
                        upper,
                        len(contiguous_ids),
                    )
                    return contiguous_ids
            if (
                isinstance(exc, httpx.TransportError)
                and transport_retries_remaining > 0
                and (
                    dense_range_size is None
                    or span > dense_range_size
                )
            ):
                logger.warning(
                    "ArcGIS OID range %d-%d transport failed for %s; "
                    "retrying the same range before partitioning: %s",
                    lower,
                    upper,
                    query_url,
                    exc,
                )
                return await self._query_object_id_range(
                    client,
                    query_url,
                    headers,
                    filter_params,
                    object_id_field=object_id_field,
                    base_where=base_where,
                    lower=lower,
                    upper=upper,
                    page_size=page_size,
                    dense_range_size=dense_range_size,
                    range_concurrency=range_concurrency,
                    contiguous_range_stats=contiguous_range_stats,
                    transport_retries_remaining=(
                        transport_retries_remaining - 1
                    ),
                    progress_callback=progress_callback,
                )
            if dense_range_size is not None and span > dense_range_size:
                logger.warning(
                    "ArcGIS OID range %d-%d failed for %s; "
                    "partitioning directly into ranges of at most %d: %s",
                    lower,
                    upper,
                    query_url,
                    dense_range_size,
                    exc,
                )
                chunks = [
                    (chunk_lower, min(
                        upper, chunk_lower + dense_range_size - 1
                    ))
                    for chunk_lower in range(lower, upper + 1, dense_range_size)
                ]

                async def query_chunk(bounds: tuple[int, int]) -> list[Any]:
                    chunk_lower, chunk_upper = bounds
                    return await self._query_object_id_range(
                        client,
                        query_url,
                        headers,
                        filter_params,
                        object_id_field=object_id_field,
                        base_where=base_where,
                        lower=chunk_lower,
                        upper=chunk_upper,
                        page_size=page_size,
                        dense_range_size=dense_range_size,
                        range_concurrency=range_concurrency,
                        contiguous_range_stats=contiguous_range_stats,
                        transport_retries_remaining=2,
                        progress_callback=progress_callback,
                    )

                if range_concurrency == 1:
                    chunk_results = [
                        await query_chunk(bounds) for bounds in chunks
                    ]
                else:
                    semaphore = asyncio.Semaphore(range_concurrency)

                    async def bounded_query(
                        bounds: tuple[int, int],
                    ) -> list[Any]:
                        async with semaphore:
                            return await query_chunk(bounds)

                    chunk_results = await asyncio.gather(*(
                        bounded_query(bounds) for bounds in chunks
                    ))
                return [
                    object_id
                    for chunk_ids in chunk_results
                    for object_id in chunk_ids
                ]
            midpoint = lower + (upper - lower) // 2
            logger.warning(
                "ArcGIS OID range %d-%d failed for %s; splitting at %d: %s",
                lower,
                upper,
                query_url,
                midpoint,
                exc,
            )
            left = await self._query_object_id_range(
                client,
                query_url,
                headers,
                filter_params,
                object_id_field=object_id_field,
                base_where=base_where,
                lower=lower,
                upper=midpoint,
                page_size=page_size,
                dense_range_size=dense_range_size,
                range_concurrency=range_concurrency,
                contiguous_range_stats=contiguous_range_stats,
                transport_retries_remaining=2,
                progress_callback=progress_callback,
            )
            right = await self._query_object_id_range(
                client,
                query_url,
                headers,
                filter_params,
                object_id_field=object_id_field,
                base_where=base_where,
                lower=midpoint + 1,
                upper=upper,
                page_size=page_size,
                dense_range_size=dense_range_size,
                range_concurrency=range_concurrency,
                contiguous_range_stats=contiguous_range_stats,
                transport_retries_remaining=2,
                progress_callback=progress_callback,
            )
            return [*left, *right]

    async def _verified_contiguous_range_ids(
        self,
        client,
        query_url: str,
        headers: dict,
        filter_params: dict[str, str],
        *,
        object_id_field: str,
        range_where: str,
        lower: int,
        upper: int,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> list[int] | None:
        """Prove a filtered OID range is gapless using authoritative statistics."""
        try:
            data = await _get_json(
                client,
                query_url,
                params={
                    **filter_params,
                    "where": range_where,
                    "outStatistics": (
                        '[{"statisticType":"min","onStatisticField":"'
                        f'{object_id_field}","outStatisticFieldName":"min_oid"}},'
                        '{"statisticType":"max","onStatisticField":"'
                        f'{object_id_field}","outStatisticFieldName":"max_oid"}},'
                        '{"statisticType":"count","onStatisticField":"'
                        f'{object_id_field}","outStatisticFieldName":"record_count"}}]'
                    ),
                    "returnGeometry": "false",
                    "f": "json",
                },
                headers=headers,
                max_attempts=3,
            )
            if _error_result(data):
                return None
            features = data.get("features")
            if not isinstance(features, list) or not features:
                return None
            attributes = features[0].get("attributes", {})
            count = int(attributes.get("record_count", -1))
            if count == 0:
                verified_ids: list[int] | None = []
            else:
                minimum = int(attributes["min_oid"])
                maximum = int(attributes["max_oid"])
                if (
                    minimum < lower
                    or maximum > upper
                    or count != maximum - minimum + 1
                ):
                    verified_ids = None
                else:
                    verified_ids = list(range(minimum, maximum + 1))
        except Exception as exc:
            logger.warning(
                "ArcGIS contiguous-range statistics failed for %d-%d at %s; "
                "falling back to bounded range queries: %s",
                lower,
                upper,
                query_url,
                exc,
            )
            return None
        if progress_callback is not None:
            await progress_callback()
        return verified_ids

    async def _paged_object_id_snapshot(
        self,
        client,
        query_url: str,
        headers: dict,
        filter_params: dict[str, str],
        *,
        object_id_field: str,
        max_records: int | None,
        page_size: int,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[list[Any], int]:
        """Enumerate ordered IDs when a service cannot return one large ID array."""
        matched_record_count: int | None = None
        try:
            count_data = await _get_json(
                client,
                query_url,
                params={
                    **filter_params,
                    "returnCountOnly": "true",
                    "returnGeometry": "false",
                    "f": "json",
                },
                headers=headers,
            )
            if error := _error_result(count_data):
                raise _ArcGISResponseError(error["message"])
            matched_record_count = int(count_data["count"])
        except Exception as exc:
            logger.warning(
                "ArcGIS count query failed during ordered ID snapshot for %s: %s",
                query_url,
                exc,
            )
            try:
                statistics_data = await _get_json(
                    client,
                    query_url,
                    params={
                        **filter_params,
                        "outStatistics": (
                            '[{"statisticType":"count","onStatisticField":"'
                            f'{object_id_field}","outStatisticFieldName":"record_count"}}]'
                        ),
                        "returnGeometry": "false",
                        "f": "json",
                    },
                    headers=headers,
                )
                if error := _error_result(statistics_data):
                    raise _ArcGISResponseError(error["message"])
                matched_record_count = int(
                    statistics_data["features"][0]["attributes"]["record_count"]
                )
            except Exception as statistics_exc:
                logger.warning(
                    "ArcGIS statistics count fallback failed for %s: %s",
                    query_url,
                    statistics_exc,
                )
        if progress_callback is not None:
            await progress_callback()

        record_limit = _ABSOLUTE_MAX_RECORDS
        if max_records is not None:
            record_limit = max(0, min(int(max_records), _ABSOLUTE_MAX_RECORDS))
        if record_limit == 0:
            return [], matched_record_count or 0

        capture_limit = (
            min(record_limit, matched_record_count)
            if matched_record_count is not None
            else record_limit
        )
        if matched_record_count is None and record_limit < _ABSOLUTE_MAX_RECORDS:
            capture_limit += 1

        object_ids: list[Any] = []
        offset = 0
        while len(object_ids) < capture_limit:
            requested = min(page_size, capture_limit - len(object_ids))
            page_data = await _get_json(
                client,
                query_url,
                params={
                    **filter_params,
                    "outFields": object_id_field,
                    "returnGeometry": "false",
                    "orderByFields": f"{object_id_field} ASC",
                    "resultOffset": str(offset),
                    "resultRecordCount": str(requested),
                    "f": "json",
                },
                headers=headers,
            )
            if error := _error_result(page_data):
                raise _ArcGISResponseError(error["message"])
            features = page_data.get("features")
            if not isinstance(features, list):
                raise _ArcGISResponseError(
                    "ArcGIS ordered ID page did not contain a features array"
                )
            if not features:
                break

            for feature in features:
                attributes = feature.get("attributes") if isinstance(feature, dict) else None
                if not isinstance(attributes, dict):
                    continue
                object_id = attributes.get(object_id_field)
                if object_id is None:
                    object_id = next(
                        (
                            value
                            for key, value in attributes.items()
                            if str(key).casefold() == object_id_field.casefold()
                        ),
                        None,
                    )
                if object_id is not None:
                    object_ids.append(object_id)

            offset += len(features)
            if progress_callback is not None:
                await progress_callback()
            if len(features) < requested and not page_data.get("exceededTransferLimit"):
                break

        unique_ids = sorted(
            dict.fromkeys(object_ids),
            key=_object_id_sort_key,
        )
        observed_count = len(unique_ids)
        return (
            unique_ids[:record_limit],
            matched_record_count if matched_record_count is not None else observed_count,
        )

    async def iter_snapshot_pages(
        self,
        snapshot: ArcGISQuerySnapshot,
        auth_config: dict,
        *,
        page_size: int = _DEFAULT_PAGE_SIZE,
        target_crs: str | None = "EPSG:4326",
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ):
        """Yield bounded GeoDataFrame pages for a frozen query snapshot."""
        import geopandas as gpd
        import httpx

        bounded_page_size = _positive_int(
            page_size, _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE,
        )
        headers = build_auth_headers(auth_config)
        use_where_clause = False
        page_query_strategy = getattr(snapshot, "page_query_strategy", "auto")
        if page_query_strategy not in {"auto", "where", "object_ids"}:
            raise ValueError(
                "snapshot page query strategy must be auto, where, or object_ids"
            )
        page_concurrency = (
            max(1, int(getattr(snapshot, "page_concurrency", 1)))
            if page_query_strategy in {"where", "object_ids"}
            else 1
        )
        progress = progress_callback
        if progress_callback is not None and page_concurrency > 1:
            progress_lock = asyncio.Lock()

            async def progress() -> None:
                async with progress_lock:
                    await progress_callback()

        request_timeout = float(
            getattr(snapshot, "request_timeout_seconds", HTTP_TIMEOUT)
        )
        if not 1.0 <= request_timeout <= 600.0:
            raise ValueError(
                "snapshot request timeout seconds must be between 1 and 600"
            )
        async with httpx.AsyncClient(timeout=request_timeout) as client:
            async def fetch_page(start: int) -> tuple[int, tuple[Any, ...], dict]:
                nonlocal use_where_clause
                object_ids = snapshot.object_ids[start : start + bounded_page_size]
                common_params = {
                    "outFields": snapshot.out_fields,
                    "returnGeometry": str(snapshot.return_geometry).lower(),
                    "outSR": "4326",
                    "f": "geojson",
                }
                if page_query_strategy == "object_ids":
                    data = await self._query_snapshot_page_by_object_ids(
                        client,
                        snapshot,
                        headers,
                        object_ids,
                        common_params,
                        progress_callback=progress,
                    )
                elif page_query_strategy == "where" or use_where_clause:
                    data = await self._query_snapshot_page_by_where(
                        client, snapshot, headers, object_ids, common_params,
                        progress_callback=progress,
                    )
                else:
                    try:
                        data = await _get_json(
                            client,
                            snapshot.query_url,
                            params={
                                "objectIds": ",".join(str(value) for value in object_ids),
                                **common_params,
                            },
                            headers=headers,
                            method="POST",
                        )
                        if error := _error_result(data):
                            raise _ArcGISResponseError(error["message"])
                        self._validate_snapshot_page(
                            data, snapshot.object_id_field, object_ids,
                        )
                    except Exception as exc:
                        logger.warning(
                            "ArcGIS objectIds feature query failed for %s; "
                            "using an exact object-ID WHERE clause for this run: %s",
                            snapshot.query_url,
                            exc,
                        )
                        data = await self._query_snapshot_page_by_where(
                            client, snapshot, headers, object_ids, common_params,
                            progress_callback=progress,
                        )
                        use_where_clause = True
                if snapshot.nullable_out_fields:
                    await self._merge_nullable_snapshot_fields(
                        client,
                        snapshot,
                        headers,
                        object_ids,
                        data,
                        progress_callback=progress,
                    )
                if snapshot.default_null_out_fields:
                    self._add_default_null_snapshot_fields(
                        data, snapshot.default_null_out_fields,
                    )
                return start, object_ids, data

            starts = iter(range(0, snapshot.record_count, bounded_page_size))
            pending: list[asyncio.Task] = []

            def schedule_next() -> bool:
                try:
                    start = next(starts)
                except StopIteration:
                    return False
                pending.append(asyncio.create_task(fetch_page(start)))
                return True

            for _ in range(page_concurrency):
                if not schedule_next():
                    break
            try:
                while pending:
                    start, object_ids, data = await pending.pop(0)
                    schedule_next()
                    features = data.get("features", [])
                    normalized_features = [
                        {
                            **feature,
                            "geometry": _sanitize_geojson_geometry(
                                feature.get("geometry")
                            ),
                        }
                        for feature in features
                    ]
                    frame = gpd.GeoDataFrame.from_features(
                        normalized_features, crs="EPSG:4326",
                    )
                    if target_crs and frame.crs and str(frame.crs) != target_crs:
                        frame = frame.to_crs(target_crs)
                    yield {
                        "batch_index": start // bounded_page_size,
                        "object_ids": object_ids,
                        "frame": frame,
                        "records_read": len(frame),
                        "records_total": snapshot.record_count,
                    }
            finally:
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

    async def _query_snapshot_page_by_object_ids(
        self,
        client,
        snapshot: ArcGISQuerySnapshot,
        headers: dict,
        object_ids: tuple[Any, ...],
        common_params: dict[str, str],
        *,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> dict:
        """Query exact IDs and split large responses without a WHERE fallback."""

        try:
            data = await _get_json(
                client,
                snapshot.query_url,
                params={
                    "objectIds": ",".join(str(value) for value in object_ids),
                    **common_params,
                },
                headers=headers,
                method="POST",
                max_attempts=1,
            )
            if error := _error_result(data):
                raise _ArcGISResponseError(error["message"])
            self._validate_snapshot_page(
                data,
                snapshot.object_id_field,
                object_ids,
            )
        except Exception as exc:
            if len(object_ids) <= 1:
                raise
            middle = len(object_ids) // 2
            logger.warning(
                "ArcGIS objectIds page of %d IDs failed for %s; splitting the batch: %s",
                len(object_ids),
                snapshot.query_url,
                exc,
            )
            left = await self._query_snapshot_page_by_object_ids(
                client,
                snapshot,
                headers,
                object_ids[:middle],
                common_params,
                progress_callback=progress_callback,
            )
            right = await self._query_snapshot_page_by_object_ids(
                client,
                snapshot,
                headers,
                object_ids[middle:],
                common_params,
                progress_callback=progress_callback,
            )
            left_features = left.get("features", [])
            right_features = right.get("features", [])
            if not isinstance(left_features, list) or not isinstance(
                right_features, list
            ):
                raise _ArcGISResponseError(
                    "ArcGIS split objectIds response did not contain feature arrays"
                ) from exc
            return {
                "type": "FeatureCollection",
                "features": [*left_features, *right_features],
            }
        if progress_callback is not None:
            await progress_callback()
        return data

    async def _query_snapshot_page_by_where(
        self,
        client,
        snapshot: ArcGISQuerySnapshot,
        headers: dict,
        object_ids: tuple[Any, ...],
        common_params: dict[str, str],
        *,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> dict:
        exact_where = self._exact_object_id_where(
            snapshot.object_id_field, object_ids,
        )
        try:
            data = await _get_json(
                client,
                snapshot.query_url,
                params={
                    "where": exact_where,
                    **common_params,
                },
                headers=headers,
                method="POST",
            )
            if error := _error_result(data):
                raise _ArcGISResponseError(error["message"])
            self._validate_snapshot_page(
                data, snapshot.object_id_field, object_ids,
            )
        except Exception as exc:
            if len(object_ids) <= 1:
                raise
            middle = len(object_ids) // 2
            logger.warning(
                "ArcGIS exact WHERE page of %d IDs failed for %s; "
                "splitting the batch: %s",
                len(object_ids),
                snapshot.query_url,
                exc,
            )
            left = await self._query_snapshot_page_by_where(
                client,
                snapshot,
                headers,
                object_ids[:middle],
                common_params,
                progress_callback=progress_callback,
            )
            right = await self._query_snapshot_page_by_where(
                client,
                snapshot,
                headers,
                object_ids[middle:],
                common_params,
                progress_callback=progress_callback,
            )
            left_features = left.get("features", [])
            right_features = right.get("features", [])
            if not isinstance(left_features, list) or not isinstance(right_features, list):
                raise _ArcGISResponseError(
                    "ArcGIS split WHERE response did not contain feature arrays"
                ) from exc
            return {
                "type": "FeatureCollection",
                "features": [*left_features, *right_features],
            }
        if progress_callback is not None:
            await progress_callback()
        return data

    async def _merge_nullable_snapshot_fields(
        self,
        client,
        snapshot: ArcGISQuerySnapshot,
        headers: dict,
        object_ids: tuple[Any, ...],
        primary_data: dict,
        *,
        progress_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Left-join fields whose ArcGIS projection suppresses null rows."""
        data = await _get_json(
            client,
            snapshot.query_url,
            params={
                "where": self._exact_object_id_where(
                    snapshot.object_id_field, object_ids,
                ),
                "outFields": ",".join((
                    snapshot.object_id_field,
                    *snapshot.nullable_out_fields,
                )),
                "returnGeometry": "false",
                "f": "json",
            },
            headers=headers,
            method="POST",
        )
        if error := _error_result(data):
            raise _ArcGISResponseError(error["message"])
        supplemental_features = data.get("features")
        if not isinstance(supplemental_features, list):
            raise _ArcGISResponseError(
                "ArcGIS nullable-field response did not contain a features array"
            )

        requested_ids = {str(value) for value in object_ids}
        supplemental_by_id: dict[str, dict] = {}
        for feature in supplemental_features:
            attributes = (
                feature.get("attributes") if isinstance(feature, dict) else None
            )
            if not isinstance(attributes, dict):
                raise _ArcGISResponseError(
                    "ArcGIS nullable-field feature did not contain attributes"
                )
            object_id = self._property_value(
                attributes, snapshot.object_id_field,
            )
            if object_id is None or str(object_id) not in requested_ids:
                raise _ArcGISResponseError(
                    "ArcGIS nullable-field response returned an unexpected object ID"
                )
            if str(object_id) in supplemental_by_id:
                raise _ArcGISResponseError(
                    "ArcGIS nullable-field response returned a duplicate object ID"
                )
            supplemental_by_id[str(object_id)] = attributes

        primary_features = primary_data.get("features")
        if not isinstance(primary_features, list):
            raise _ArcGISResponseError(
                "ArcGIS primary response did not contain a features array"
            )
        for feature in primary_features:
            properties = feature["properties"]
            object_id = self._property_value(
                properties, snapshot.object_id_field,
            )
            supplemental = supplemental_by_id.get(str(object_id), {})
            for field in snapshot.nullable_out_fields:
                properties[field] = self._property_value(supplemental, field)
        if progress_callback is not None:
            await progress_callback()

    @staticmethod
    def _add_default_null_snapshot_fields(
        data: dict,
        fields: tuple[str, ...],
    ) -> None:
        features = data.get("features")
        if not isinstance(features, list):
            raise _ArcGISResponseError(
                "ArcGIS response did not contain a features array"
            )
        for feature in features:
            properties = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(properties, dict):
                raise _ArcGISResponseError(
                    "ArcGIS feature did not contain properties"
                )
            for field in fields:
                properties.setdefault(field, None)

    @staticmethod
    def _exact_object_id_where(
        object_id_field: str,
        object_ids: tuple[Any, ...],
    ) -> str:
        values = []
        integer_values = []
        for value in object_ids:
            raw = str(value)
            if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
                values.append(raw)
            else:
                values.append("'" + raw.replace("'", "''") + "'")
            if re.fullmatch(r"-?\d+", raw):
                integer_values.append(int(raw))
        contiguous_integers = (
            len(integer_values) == len(object_ids)
            and all(
                value == integer_values[0] + index
                for index, value in enumerate(integer_values)
            )
        )
        if contiguous_integers:
            return (
                f"{object_id_field} BETWEEN "
                f"{integer_values[0]} AND {integer_values[-1]}"
            )
        return f"{object_id_field} IN ({','.join(values)})"

    @staticmethod
    def _property_value(properties: dict, field: str) -> Any:
        value = properties.get(field)
        if value is not None:
            return value
        field_key = field.casefold()
        return next(
            (
                candidate
                for key, candidate in properties.items()
                if str(key).casefold() == field_key
            ),
            None,
        )

    @staticmethod
    def _validate_snapshot_page(
        data: dict,
        object_id_field: str,
        requested_object_ids: tuple[Any, ...],
    ) -> None:
        """Reject successful ArcGIS responses that silently omit snapshot rows."""
        features = data.get("features")
        if not isinstance(features, list):
            raise _ArcGISResponseError(
                "ArcGIS snapshot page did not contain a features array"
            )
        returned_ids = []
        for feature in features:
            properties = (
                feature.get("properties") if isinstance(feature, dict) else None
            )
            if not isinstance(properties, dict):
                raise _ArcGISResponseError(
                    "ArcGIS GeoJSON feature did not contain properties"
                )
            object_id = ArcGISRestConnector._property_value(
                properties, object_id_field,
            )
            if object_id is None:
                raise _ArcGISResponseError(
                    f"ArcGIS GeoJSON feature omitted {object_id_field}"
                )
            returned_ids.append(str(object_id))

        expected_ids = {str(value) for value in requested_object_ids}
        observed_ids = set(returned_ids)
        if (
            len(returned_ids) != len(requested_object_ids)
            or observed_ids != expected_ids
        ):
            missing = sorted(expected_ids - observed_ids)[:5]
            unexpected = sorted(observed_ids - expected_ids)[:5]
            raise _ArcGISResponseError(
                "ArcGIS snapshot page was incomplete: "
                f"requested={len(requested_object_ids)}, "
                f"returned={len(returned_ids)}, missing={missing}, "
                f"unexpected={unexpected}"
            )

    @staticmethod
    def _filter_params(
        where: str,
        bbox: list[float] | None,
    ) -> dict[str, str]:
        params: dict[str, str] = {"where": where}
        if bbox:
            if len(bbox) != 4:
                raise ValueError("bbox must contain four coordinates")
            params.update({
                "geometry": ",".join(str(value) for value in bbox),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            })
        return params

    async def query(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        *,
        bbox: list[float] | None = None,
        filter_expr: str | None = None,
        limit: int = 1000,
        extra_params: dict | None = None,
        target_crs: str | None = None,
    ):
        import geopandas as gpd
        import httpx

        target = _service_target(endpoint_url)
        if target is None:
            return {
                "status": "error",
                "message": (
                    "ArcGIS queries require a FeatureServer or MapServer service URL; "
                    "use discovery first when starting from a services directory"
                ),
            }
        service_url, endpoint_layer_id = target
        layer_id = endpoint_layer_id
        if layer_id is None:
            layer_id = int(query_config.get("layer_id", 0))

        requested_limit = max(0, int(limit))
        if requested_limit == 0:
            return gpd.GeoDataFrame()
        configured_cap = _positive_int(
            query_config.get("max_records"),
            _DEFAULT_MAX_RECORDS,
            _ABSOLUTE_MAX_RECORDS,
        )
        max_records = min(requested_limit, configured_cap)
        page_size = min(
            _positive_int(
                query_config.get("page_size"), _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE,
            ),
            max_records,
        )

        where = filter_expr or query_config.get("where", "1=1")
        out_fields = query_config.get("out_fields", "*")
        return_geometry = bool(query_config.get("return_geometry", True))
        object_id_field = str(query_config.get("object_id_field", "OBJECTID"))
        query_url = f"{service_url}/{layer_id}/query"
        headers = build_auth_headers(auth_config)

        try:
            filter_params = self._filter_params(str(where), bbox)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            raw_ids = None
            id_data: dict = {}
            snapshot_paging = bool(query_config.get("snapshot_paging", True))
            if snapshot_paging and max_records > page_size:
                id_params = {
                    **filter_params,
                    "returnIdsOnly": "true",
                    "returnGeometry": "false",
                    "f": "json",
                }
                id_data = await _get_json(
                    client, query_url, params=id_params, headers=headers,
                )
                if error := _error_result(id_data):
                    return error
                raw_ids = id_data.get("objectIds")
            if isinstance(raw_ids, list):
                object_id_field = str(
                    id_data.get("objectIdFieldName") or object_id_field
                )
                object_ids = sorted(
                    dict.fromkeys(raw_ids),
                    key=_object_id_sort_key,
                )[:max_records]
                if not object_ids:
                    return gpd.GeoDataFrame()
                try:
                    all_features = await self._query_object_id_pages(
                        client,
                        query_url,
                        headers,
                        object_ids,
                        page_size=page_size,
                        out_fields=out_fields,
                        return_geometry=return_geometry,
                    )
                except _ArcGISResponseError as exc:
                    return {"status": "error", "message": str(exc)}
            else:
                try:
                    all_features = await self._query_offset_pages(
                        client,
                        query_url,
                        headers,
                        filter_params,
                        page_size=page_size,
                        max_records=max_records,
                        out_fields=out_fields,
                        return_geometry=return_geometry,
                        object_id_field=object_id_field,
                    )
                except _ArcGISResponseError as exc:
                    return {"status": "error", "message": str(exc)}

        all_features = all_features[:max_records]
        if not all_features:
            return gpd.GeoDataFrame()

        gdf = gpd.GeoDataFrame.from_features(all_features, crs="EPSG:4326")
        if target_crs and gdf.crs and str(gdf.crs) != target_crs:
            gdf = gdf.to_crs(target_crs)
        return gdf

    async def _query_object_id_pages(
        self,
        client,
        query_url: str,
        headers: dict,
        object_ids: list,
        *,
        page_size: int,
        out_fields: str,
        return_geometry: bool,
    ) -> list:
        features: list = []
        for start in range(0, len(object_ids), page_size):
            batch = object_ids[start : start + page_size]
            data = await _get_json(
                client,
                query_url,
                params={
                    "objectIds": ",".join(str(value) for value in batch),
                    "outFields": out_fields,
                    "returnGeometry": str(return_geometry).lower(),
                    "outSR": "4326",
                    "f": "geojson",
                },
                headers=headers,
                method="POST",
            )
            if error := _error_result(data):
                raise _ArcGISResponseError(error["message"])
            features.extend(data.get("features", []))
        return features

    async def _query_offset_pages(
        self,
        client,
        query_url: str,
        headers: dict,
        filter_params: dict,
        *,
        page_size: int,
        max_records: int,
        out_fields: str,
        return_geometry: bool,
        object_id_field: str,
    ) -> list:
        features: list = []
        offset = 0
        while len(features) < max_records:
            requested = min(page_size, max_records - len(features))
            data = await _get_json(
                client,
                query_url,
                params={
                    **filter_params,
                    "outFields": out_fields,
                    "returnGeometry": str(return_geometry).lower(),
                    "outSR": "4326",
                    "orderByFields": f"{object_id_field} ASC",
                    "resultOffset": str(offset),
                    "resultRecordCount": str(requested),
                    "f": "geojson",
                },
                headers=headers,
            )
            if error := _error_result(data):
                raise _ArcGISResponseError(error["message"])
            page = data.get("features", [])
            features.extend(page)
            if len(page) < requested:
                break
            offset += len(page)
        return features

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        import httpx

        headers = build_auth_headers(auth_config)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                data = await _get_json(
                    client, _clean_url(endpoint_url), params={"f": "json"}, headers=headers,
                )
            if error := _error_result(data):
                return {"health": "error", "message": error["message"]}
            return {"health": "healthy", "message": "OK"}
        except httpx.TimeoutException:
            return {"health": "timeout", "message": "Connection timed out"}
        except Exception as exc:
            return {"health": "error", "message": str(exc)[:200]}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        """Discover queryable leaf layers from a service or services directory."""
        import httpx

        endpoint = _clean_url(endpoint_url)
        headers = build_auth_headers(auth_config)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            target = _service_target(endpoint)
            if target is not None:
                service_url, _ = target
                data = await _get_json(
                    client, service_url, params={"f": "json"}, headers=headers,
                )
                if error := _error_result(data):
                    return error
                layers = self._leaf_layers(
                    data.get("layers", []), service_url=service_url,
                )
                return {
                    "layers": layers,
                    "service": "ArcGIS REST",
                    "description": data.get("serviceDescription", ""),
                }
            return await self._discover_directory(client, endpoint, headers)

    async def _discover_directory(self, client, endpoint: str, headers: dict) -> dict:
        root_data = await _get_json(
            client, endpoint, params={"f": "json"}, headers=headers,
        )
        if error := _error_result(root_data):
            return error

        service_root = _services_root(endpoint)
        folders = [
            str(folder) for folder in root_data.get("folders", [])
        ][:_MAX_DISCOVERY_FOLDERS]
        warnings: list[str] = []

        async def fetch_folder(folder: str) -> dict:
            folder_url = f"{service_root}/{quote(folder, safe='/')}"
            try:
                return await _get_json(
                    client, folder_url, params={"f": "json"}, headers=headers,
                )
            except Exception as exc:
                warnings.append(f"{folder}: {str(exc)[:120]}")
                return {"services": []}

        folder_catalogs = await asyncio.gather(
            *(fetch_folder(folder) for folder in folders)
        )
        service_specs = list(root_data.get("services", []))
        for catalog in folder_catalogs:
            service_specs.extend(catalog.get("services", []))

        services: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for spec in service_specs:
            name = str(spec.get("name", "")).strip("/")
            service_type = str(spec.get("type", ""))
            key = (name, service_type)
            if (
                not name
                or service_type not in {"FeatureServer", "MapServer"}
                or key in seen
            ):
                continue
            seen.add(key)
            services.append({"name": name, "type": service_type})
            if len(services) >= _MAX_DISCOVERY_SERVICES:
                break

        semaphore = asyncio.Semaphore(_DISCOVERY_CONCURRENCY)

        async def fetch_service(spec: dict) -> list[dict]:
            name = spec["name"]
            service_type = spec["type"]
            service_url = (
                f"{service_root}/{quote(name, safe='/')}/{service_type}"
            )
            try:
                async with semaphore:
                    data = await _get_json(
                        client, service_url, params={"f": "json"}, headers=headers,
                    )
                if error := _error_result(data):
                    warnings.append(f"{name}: {error['message'][:120]}")
                    return []
                return self._leaf_layers(
                    data.get("layers", []),
                    service_url=service_url,
                    service_name=name,
                    service_type=service_type,
                )
            except Exception as exc:
                warnings.append(f"{name}: {str(exc)[:120]}")
                return []

        discovered = await asyncio.gather(
            *(fetch_service(spec) for spec in services)
        )
        layers = [layer for service_layers in discovered for layer in service_layers]
        return {
            "layers": layers,
            "folders": folders,
            "services": services,
            "service": "ArcGIS REST directory",
            "partial": bool(warnings),
            "warnings": warnings,
        }

    @staticmethod
    def _leaf_layers(
        layers: list,
        *,
        service_url: str,
        service_name: str = "",
        service_type: str = "",
    ) -> list[dict]:
        result: list[dict] = []
        for layer in layers:
            geometry_type = layer.get("geometryType", "")
            if not geometry_type or layer.get("subLayerIds"):
                continue
            result.append({
                "id": layer.get("id"),
                "name": layer.get("name", ""),
                "geometryType": geometry_type,
                "endpoint_url": service_url,
                "service_name": service_name,
                "service_type": service_type,
                "maxRecordCount": layer.get("maxRecordCount"),
            })
        return result


ConnectorRegistry.register(ArcGISRestConnector())
