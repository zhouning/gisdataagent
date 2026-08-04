"""Download a small OpenAQ v3 station observation proxy snapshot for UWM.

The OpenAQ API key must be supplied at runtime via OPENAQ_API_KEY or stdin.
The key is used only in the request header and is never persisted.
"""

from __future__ import annotations

import argparse
import copy
import getpass
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from data_agent.uwm.openaq_station_observations import (
    build_mmfe_state_input_from_openaq_station_proxy,
    build_openaq_locations_url,
    build_openaq_sensor_measurements_url,
    write_openaq_station_snapshot,
)

PM25_PARAMETERS = {"pm25", "pm2_5"}
OPENAQ_PAGINATED_RESULTS_SCHEMA = "uwm.openaq_paginated_results.v1"
OPENAQ_ACQUISITION_AUDIT_SCHEMA = "uwm.openaq_multi_station_acquisition_audit.v1"
OPENAQ_ACQUISITION_PLAN_SCHEMA = "uwm.openaq_multi_station_acquisition_plan.v1"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCATIONS_INPUT = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_station_observations"
    / "openaq_locations_raw.json"
)
DEFAULT_PLAN_OUTPUT = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central"
    / "openaq_multi_station_acquisition_plan_2026_08_04.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latitude", type=float, default=29.563)
    parser.add_argument("--longitude", type=float, default=106.551)
    parser.add_argument("--label", default="Chongqing central")
    parser.add_argument("--radius-m", type=int, default=25000)
    parser.add_argument("--location-limit", type=int, default=20)
    parser.add_argument(
        "--station-limit", "--sensor-limit", dest="station_limit", type=int, default=6
    )
    parser.add_argument("--measurement-limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--station-id", action="append", type=int, default=[])
    parser.add_argument("--sensor-id", action="append", type=int, default=[])
    parser.add_argument("--scene-start-date", default="2024-07-01")
    parser.add_argument("--scene-end-date", default="2024-07-07")
    parser.add_argument("--proxy")
    parser.add_argument("--api-key-stdin", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--locations-input", type=Path, default=DEFAULT_LOCATIONS_INPUT)
    parser.add_argument("--plan-output", type=Path, default=DEFAULT_PLAN_OUTPUT)
    parser.add_argument("--created-at")
    parser.add_argument(
        "--output-dir",
        default="data/uwm_public_proxy/chongqing_central/openaq_station_observations",
    )
    args = parser.parse_args()

    date_from, date_to = scene_measurement_datetime_bounds(
        args.scene_start_date, args.scene_end_date
    )
    created_at = args.created_at or datetime.now(UTC).isoformat()
    if args.plan_only:
        locations_payload = json.loads(args.locations_input.read_text(encoding="utf-8"))
        bindings = choose_pm25_sensor_bindings(
            locations_payload,
            limit=args.station_limit,
            station_allowlist=args.station_id,
            sensor_allowlist=args.sensor_id,
        )
        plan = build_acquisition_plan(
            created_at=created_at,
            bindings=bindings,
            date_from=date_from,
            date_to=date_to,
            measurement_page_limit=args.measurement_limit,
            max_pages=args.max_pages,
            locations_payload=locations_payload,
            locations_source_ref=_relative_or_absolute(args.locations_input),
        )
        _atomic_write_json(args.plan_output, plan)
        print(
            json.dumps(
                {
                    "plan_output": str(args.plan_output),
                    "planned_station_count": len(bindings),
                    "measurement_downloaded": False,
                    "plan_sha256": plan["plan_sha256"],
                },
                ensure_ascii=False,
            )
        )
        return

    api_key = _api_key(args.api_key_stdin)
    headers = {"X-API-Key": api_key}
    client_kwargs: dict[str, Any] = {"timeout": 60.0}
    if args.proxy:
        client_kwargs["proxy"] = args.proxy

    with httpx.Client(**client_kwargs) as client:
        result = acquire_openaq_snapshot(
            client=client,
            headers=headers,
            output_dir=Path(args.output_dir),
            requested_location={
                "latitude": args.latitude,
                "longitude": args.longitude,
                "label": args.label,
            },
            radius_m=args.radius_m,
            location_page_limit=args.location_limit,
            station_limit=args.station_limit,
            station_allowlist=args.station_id,
            sensor_allowlist=args.sensor_id,
            date_from=date_from,
            date_to=date_to,
            measurement_page_limit=args.measurement_limit,
            max_pages=args.max_pages,
            scene_time_range={
                "start_date": args.scene_start_date,
                "end_date": args.scene_end_date,
            },
            fetched_at=created_at,
            api_key=api_key,
            replace_existing=args.replace_existing,
        )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "manifest": "snapshot_manifest.json",
                "record_counts": result["manifest"]["record_counts"],
                "observed_time_range": result["manifest"]["observed_time_range"],
                "scene_holdout_ready": result["manifest"]["scene_holdout_ready"],
                "station_ids": [row["station_id"] for row in result["bindings"]],
                "sensor_ids": [row["sensor_id"] for row in result["bindings"]],
                "acquisition_complete": True,
            },
            ensure_ascii=False,
        )
    )


def _api_key(read_stdin: bool) -> str:
    if read_stdin:
        key = (
            getpass.getpass("OpenAQ API key: ").strip()
            if sys.stdin.isatty()
            else sys.stdin.readline().strip()
        )
    else:
        key = os.environ.get("OPENAQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("OpenAQ API key is required via OPENAQ_API_KEY or --api-key-stdin")
    return key


def scene_measurement_datetime_bounds(
    scene_start_date: str, scene_end_date: str
) -> tuple[str, str]:
    """Convert inclusive scene dates to OpenAQ UTC measurement datetime bounds."""

    start = datetime.fromisoformat(scene_start_date).date()
    end_exclusive = datetime.fromisoformat(scene_end_date).date() + timedelta(days=1)
    return f"{start.isoformat()}T00:00:00Z", f"{end_exclusive.isoformat()}T00:00:00Z"


def _get_json(client: httpx.Client, url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def choose_pm25_sensor_bindings(
    locations_payload: Mapping[str, Any],
    *,
    limit: int,
    station_allowlist: Sequence[int | str] = (),
    sensor_allowlist: Sequence[int | str] = (),
) -> list[dict[str, Any]]:
    """Choose at most one PM2.5 sensor per station, nearest station first."""

    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("station_limit_must_be_positive")
    requested_stations = {str(value) for value in station_allowlist}
    requested_sensors = {str(value) for value in sensor_allowlist}
    locations = locations_payload.get("results") or []
    if not isinstance(locations, list) or not all(isinstance(row, Mapping) for row in locations):
        raise ValueError("openaq_locations_results_invalid")
    ordered_locations = sorted(
        locations,
        key=lambda row: (
            _float(row.get("distance")) is None,
            _float(row.get("distance")) or 0.0,
            str(row.get("id") or ""),
        ),
    )
    bindings = []
    for location in ordered_locations:
        station_id = str(location.get("id") or "").strip()
        if not station_id or (requested_stations and station_id not in requested_stations):
            continue
        candidates = []
        for sensor in location.get("sensors") or []:
            if not isinstance(sensor, Mapping):
                continue
            parameter = sensor.get("parameter") or {}
            name = str(parameter.get("name") or "").lower().replace(".", "")
            sensor_id = str(sensor.get("id") or "").strip()
            if (
                name in PM25_PARAMETERS
                and sensor_id
                and (not requested_sensors or sensor_id in requested_sensors)
            ):
                candidates.append(sensor)
        candidates.sort(key=lambda sensor: int(sensor["id"]))
        if requested_sensors and len(candidates) > 1:
            raise ValueError(f"multiple_allowed_pm25_sensors_for_station:{station_id}")
        if candidates:
            selected = candidates[0]
            coordinates = location.get("coordinates") or {}
            bindings.append(
                {
                    "station_id": int(station_id),
                    "station_name": str(location.get("name") or "") or None,
                    "sensor_id": int(selected["id"]),
                    "parameter": "pm25",
                    "distance_m": _float(location.get("distance")),
                    "latitude": _float(coordinates.get("latitude")),
                    "longitude": _float(coordinates.get("longitude")),
                }
            )
    selected_stations = {str(row["station_id"]) for row in bindings}
    selected_sensors = {str(row["sensor_id"]) for row in bindings}
    missing_stations = sorted(requested_stations - selected_stations)
    missing_sensors = sorted(requested_sensors - selected_sensors)
    if missing_stations:
        raise ValueError("requested_stations_missing_pm25_sensor:" + ",".join(missing_stations))
    if missing_sensors:
        raise ValueError("requested_pm25_sensors_missing:" + ",".join(missing_sensors))
    if len(bindings) > limit:
        if requested_stations or requested_sensors:
            raise ValueError("requested_sensor_bindings_exceed_station_limit")
        bindings = bindings[:limit]
    return bindings


def _choose_sensor_ids(locations_payload: dict[str, Any], limit: int) -> list[int]:
    """Backward-compatible sensor ID view of the station-balanced selector."""

    return [row["sensor_id"] for row in choose_pm25_sensor_bindings(locations_payload, limit=limit)]


def fetch_paginated_results(
    *,
    client: httpx.Client,
    url_for_page: Callable[[int], str],
    headers: dict[str, str],
    max_pages: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch all OpenAQ pages and fail if found/fetched completeness is uncertain."""

    if max_pages <= 0:
        raise ValueError("max_pages_must_be_positive")
    first_payload: dict[str, Any] | None = None
    all_results: list[dict[str, Any]] = []
    expected_found: int | str | None = None
    found_relation: str | None = None
    found_boundary: int | None = None
    parsed_found_values: list[tuple[str, int]] = []
    page_audit = []
    completion_signal: str | None = None
    for page in range(1, max_pages + 1):
        payload = _get_json(client, url_for_page(page), headers)
        meta = payload.get("meta")
        results = payload.get("results")
        if (
            not isinstance(meta, Mapping)
            or not isinstance(results, list)
            or not all(isinstance(row, dict) for row in results)
        ):
            raise ValueError(f"openaq_page_payload_invalid:{page}")
        found = meta.get("found")
        reported_page = meta.get("page")
        parsed_found = _parse_reported_found(found)
        page_limit = meta.get("limit")
        if parsed_found is None:
            raise ValueError(f"openaq_page_found_invalid:{page}")
        if not isinstance(page_limit, int) or isinstance(page_limit, bool) or page_limit <= 0:
            raise ValueError(f"openaq_page_limit_invalid:{page}")
        if reported_page is not None and reported_page != page:
            raise ValueError(f"openaq_page_number_mismatch:{page}")
        if expected_found is None:
            expected_found = found
            found_relation, found_boundary = parsed_found
            first_payload = copy.deepcopy(payload)
        parsed_found_values.append(parsed_found)
        all_results.extend(copy.deepcopy(results))
        page_audit.append({"page": page, "result_count": len(results), "reported_found": found})
        found_is_stable = all(value == parsed_found_values[0] for value in parsed_found_values)
        if found_relation == "exact" and found_is_stable and len(all_results) >= found_boundary:
            completion_signal = "reported_found_reached"
            break
        if len(results) < page_limit:
            page_relation, page_boundary = parsed_found
            page_count_self_consistent = page_relation == "exact" and page_boundary in {
                len(results),
                len(all_results),
            }
            lower_bound_exceeded = (
                found_relation == "lower_bound" and len(all_results) > found_boundary
            )
            if page_count_self_consistent or lower_bound_exceeded:
                completion_signal = "terminal_short_page"
                break
        if not results:
            raise ValueError(f"openaq_pagination_stalled:{page}")
    if (
        first_payload is None
        or expected_found is None
        or found_relation is None
        or found_boundary is None
    ):
        raise ValueError("openaq_pagination_no_response")
    reported_found_consistent = all(
        value == parsed_found_values[0] for value in parsed_found_values
    )
    if completion_signal is None:
        raise ValueError(
            f"openaq_pagination_incomplete_without_terminal_page:fetched={len(all_results)}"
        )
    if (
        found_relation == "exact"
        and completion_signal == "reported_found_reached"
        and len(all_results) != found_boundary
    ):
        raise ValueError(
            f"openaq_pagination_incomplete:found={found_boundary}:fetched={len(all_results)}"
        )
    if found_relation == "lower_bound" and (
        len(all_results) <= found_boundary or completion_signal != "terminal_short_page"
    ):
        raise ValueError(
            f"openaq_pagination_incomplete:found=>{found_boundary}:fetched={len(all_results)}"
        )
    aggregate = first_payload
    aggregate["schema"] = OPENAQ_PAGINATED_RESULTS_SCHEMA
    aggregate["results"] = all_results
    aggregate["meta"] = {
        **dict(first_payload["meta"]),
        "found": expected_found,
        "found_relation": found_relation,
        "found_lower_bound_exclusive": (
            found_boundary if found_relation == "lower_bound" else None
        ),
        "fetched": len(all_results),
        "reported_found_consistent": reported_found_consistent,
        "pages_fetched": len(page_audit),
        "acquisition_complete": True,
    }
    audit = {
        "found": expected_found,
        "found_relation": found_relation,
        "found_lower_bound_exclusive": (
            found_boundary if found_relation == "lower_bound" else None
        ),
        "fetched": len(all_results),
        "reported_found_consistent": reported_found_consistent,
        "pages_fetched": len(page_audit),
        "page_audit": page_audit,
        "completion_signal": completion_signal,
        "complete": True,
    }
    return aggregate, audit


def _parse_reported_found(value: Any) -> tuple[str, int] | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return "exact", value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            return "exact", int(normalized)
        if normalized.startswith(">") and normalized[1:].strip().isdigit():
            return "lower_bound", int(normalized[1:].strip())
    return None


def acquire_openaq_snapshot(
    *,
    client: httpx.Client,
    headers: dict[str, str],
    output_dir: Path,
    requested_location: dict[str, Any],
    radius_m: int,
    location_page_limit: int,
    station_limit: int,
    station_allowlist: Sequence[int | str],
    sensor_allowlist: Sequence[int | str],
    date_from: str,
    date_to: str,
    measurement_page_limit: int,
    max_pages: int,
    scene_time_range: dict[str, str],
    fetched_at: str,
    api_key: str,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Acquire, validate, and publish a complete multi-station snapshot."""

    if output_dir.exists() and not replace_existing:
        raise FileExistsError(f"output directory already exists: {output_dir}")
    locations_payload, locations_audit = fetch_paginated_results(
        client=client,
        url_for_page=lambda page: build_openaq_locations_url(
            latitude=float(requested_location["latitude"]),
            longitude=float(requested_location["longitude"]),
            radius_m=radius_m,
            limit=location_page_limit,
            page=page,
        ),
        headers=headers,
        max_pages=max_pages,
    )
    bindings = choose_pm25_sensor_bindings(
        locations_payload,
        limit=station_limit,
        station_allowlist=station_allowlist,
        sensor_allowlist=sensor_allowlist,
    )
    if not bindings:
        raise ValueError("no_pm25_station_sensor_bindings_selected")
    measurement_payloads = {}
    sensor_audits = {}
    for binding in bindings:
        sensor_id = binding["sensor_id"]
        payload, audit = fetch_paginated_results(
            client=client,
            url_for_page=lambda page, sensor_id=sensor_id: build_openaq_sensor_measurements_url(
                sensor_id=sensor_id,
                date_from=date_from,
                date_to=date_to,
                limit=measurement_page_limit,
                page=page,
            ),
            headers=headers,
            max_pages=max_pages,
        )
        measurement_payloads[str(sensor_id)] = payload
        sensor_audits[str(sensor_id)] = audit

    acquisition_audit = {
        "schema": OPENAQ_ACQUISITION_AUDIT_SCHEMA,
        "version": "0.1",
        "fetched_at": fetched_at,
        "selection_strategy": "nearest_station_one_pm25_sensor_per_location",
        "selected_bindings": bindings,
        "location_pagination": locations_audit,
        "sensor_measurement_pagination": sensor_audits,
        "all_pages_complete": locations_audit["complete"]
        and all(audit["complete"] for audit in sensor_audits.values()),
        "api_key_persisted": False,
        "claim_boundary": {
            "max_claim_level": "acquisition_audit_only",
            "scientific_result_claim": False,
        },
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    try:
        manifest = write_openaq_station_snapshot(
            output_dir=staging,
            locations_payload=locations_payload,
            sensor_measurement_payloads=measurement_payloads,
            requested_location=requested_location,
            scene_time_range=scene_time_range,
            fetched_at=fetched_at,
        )
        proxy = json.loads(
            (staging / "openaq_station_observation_proxy.json").read_text(encoding="utf-8")
        )
        state_input = build_mmfe_state_input_from_openaq_station_proxy(proxy, timestamp=fetched_at)
        _write_json(staging / "mmfe_uwm_state_input_openaq_station.json", state_input)
        _write_json(staging / "openaq_acquisition_audit.json", acquisition_audit)
        manifest["files"]["acquisition_audit"] = "openaq_acquisition_audit.json"
        manifest["acquisition_audit"] = {
            "selected_station_count": len(bindings),
            "selected_sensor_count": len(bindings),
            "all_pages_complete": acquisition_audit["all_pages_complete"],
            "api_key_persisted": False,
        }
        _write_json(staging / "snapshot_manifest.json", manifest)
        _validate_staged_snapshot(
            staging=staging,
            bindings=bindings,
            manifest=manifest,
            acquisition_audit=acquisition_audit,
            api_key=api_key,
        )
        _publish_staged_snapshot(
            staging=staging,
            output_dir=output_dir,
            replace_existing=replace_existing,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"manifest": manifest, "bindings": bindings, "acquisition_audit": acquisition_audit}


def build_acquisition_plan(
    *,
    created_at: str,
    bindings: Sequence[Mapping[str, Any]],
    date_from: str,
    date_to: str,
    measurement_page_limit: int,
    max_pages: int,
    locations_payload: Mapping[str, Any],
    locations_source_ref: str,
) -> dict[str, Any]:
    plan = {
        "schema": OPENAQ_ACQUISITION_PLAN_SCHEMA,
        "version": "0.1",
        "created_at": created_at,
        "target_parameter": "pm25",
        "selection_strategy": "one_pm25_sensor_per_location",
        "measurement_time_range": {"datetime_from": date_from, "datetime_to": date_to},
        "measurement_page_limit": measurement_page_limit,
        "max_pages": max_pages,
        "locations_source_ref": locations_source_ref,
        "locations_payload_sha256": _canonical_sha256(locations_payload),
        "planned_bindings": [dict(binding) for binding in bindings],
        "planned_station_count": len(bindings),
        "measurement_downloaded": False,
        "api_key_persisted": False,
        "claim_boundary": {
            "max_claim_level": "acquisition_plan_only",
            "observed_measurement_claim": False,
            "scientific_result_claim": False,
        },
    }
    plan["plan_sha256"] = _canonical_sha256(plan)
    return plan


def _validate_staged_snapshot(
    *,
    staging: Path,
    bindings: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    acquisition_audit: Mapping[str, Any],
    api_key: str,
) -> None:
    required_files = {
        "openaq_locations_raw.json",
        "openaq_sensor_measurements_raw.json",
        "openaq_station_observation_proxy.json",
        "mmfe_uwm_state_input_openaq_station.json",
        "openaq_acquisition_audit.json",
        "snapshot_manifest.json",
    }
    if not all((staging / name).is_file() for name in required_files):
        raise ValueError("openaq_staged_snapshot_files_incomplete")
    expected_sensors = {str(row["sensor_id"]) for row in bindings}
    measurement_payloads = json.loads(
        (staging / "openaq_sensor_measurements_raw.json").read_text(encoding="utf-8")
    )
    if set(measurement_payloads) != expected_sensors:
        raise ValueError("openaq_staged_snapshot_sensor_set_mismatch")
    fetched = sum(len(payload.get("results") or []) for payload in measurement_payloads.values())
    if fetched != (manifest.get("record_counts") or {}).get("measurements"):
        raise ValueError("openaq_staged_snapshot_measurement_count_mismatch")
    if acquisition_audit.get("all_pages_complete") is not True:
        raise ValueError("openaq_staged_snapshot_pagination_incomplete")
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in staging.iterdir() if path.is_file()
    )
    if api_key and api_key in serialized:
        raise ValueError("openaq_api_key_persisted_in_snapshot")


def _publish_staged_snapshot(*, staging: Path, output_dir: Path, replace_existing: bool) -> None:
    if output_dir.exists() and not replace_existing:
        raise FileExistsError(f"output directory already exists: {output_dir}")
    if not output_dir.exists():
        os.replace(staging, output_dir)
        return
    backup = output_dir.parent / f".{output_dir.name}.backup-{uuid.uuid4().hex}"
    os.replace(output_dir, backup)
    try:
        os.replace(staging, output_dir)
    except BaseException:
        os.replace(backup, output_dir)
        raise
    shutil.rmtree(backup)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        _write_json(temporary, payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relative_or_absolute(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    main()
