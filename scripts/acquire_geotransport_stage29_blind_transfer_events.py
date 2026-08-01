#!/usr/bin/env python3
"""Acquire release-selected blind transfer events and public observations."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/stage29_center_hill_blind_transfer_events"
)
SELECTION_SCHEMA = "gwm.geotransport.stage29_release_event_selection.v1"
OBSERVATION_SCHEMA = "gwm.geotransport.stage29_observation_acquisition.v1"
USER_AGENT = "gisdataagent-stage29-blind-transfer-events/0.1"
CWMS_HOST = "cwms-data.usace.army.mil"
CWMS_ROOT = f"https://{CWMS_HOST}/cwms-data"
CWMS_RESOLVED_IPS = ("3.30.180.152", "3.32.180.175")
CWMS_SERIES_ID = "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev"
CWMS_OFFICE = "LRN"
CWMS_BEGIN = "2021-01-01T00:00:00Z"
CWMS_END = "2026-01-01T00:00:00Z"
CWMS_PAGE_SIZE = 50_000
DOWNSTREAM_SITE_ID = "USGS-03424860"
TRIBUTARY_SITE_ID = "USGS-03424730"
PARAMETER_CODE = "00060"
LAG_CANDIDATES_HOURS = tuple(range(13))
STAGE28_DIAGNOSTIC_LAG_HOURS = 6
EVENT_COUNT = 3
EVENT_BEFORE_STEP_HOURS = 24
EVENT_AFTER_STEP_HOURS = 48
EVENT_DURATION_HOURS = 72
OBSERVATION_EXTENSION_HOURS = max(LAG_CANDIDATES_HOURS)
MINIMUM_STEP_M3S = 50.0
MINIMUM_WINDOW_RANGE_M3S = 100.0
MINIMUM_EVENT_SEPARATION_DAYS = 180
STAGE28_EXCLUSION_DAYS = 90
STAGE28_DEVELOPMENT_START = "2024-05-15T00:00:00Z"
STAGE28_DEVELOPMENT_END = "2024-05-18T00:00:00Z"
MAXIMUM_SELECTION_REQUEST_COUNT = 5
MAXIMUM_OBSERVATION_REQUEST_COUNT = EVENT_COUNT * 2
MAXIMUM_SELECTION_DOWNLOAD_BYTES = 10_000_000
MAXIMUM_OBSERVATION_DOWNLOAD_BYTES = 12_000_000
ALLOWED_HOSTS = frozenset(
    {CWMS_HOST, "api.waterdata.usgs.gov", "api.water.usgs.gov"}
)
USGS_LICENSE = "USGS public-domain data"
USGS_LICENSE_URL = (
    "https://www.usgs.gov/information-policies-and-instructions/"
    "copyrights-and-credits"
)
CWMS_SOURCE_TERMS = (
    "USACE CWMS Data API public endpoint; redistribution terms not "
    "independently adjudicated"
)
CWMS_SOURCE_URL = "https://cwms-data.usace.army.mil/cwms-data/swagger-ui.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=(
            "selection-plan",
            "release",
            "observation-plan",
            "observations",
        ),
        required=True,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_selection_plan(*, values_mode: bool = False) -> dict[str, Any]:
    sources = _selection_sources()
    planned_bytes = sum(int(value["maximum_bytes"]) for value in sources)
    if (
        len(sources) > MAXIMUM_SELECTION_REQUEST_COUNT
        or planned_bytes > MAXIMUM_SELECTION_DOWNLOAD_BYTES
    ):
        raise ValueError("stage29_selection_request_boundary_exceeded")
    return {
        "schema": SELECTION_SCHEMA,
        "mode": "release_values" if values_mode else "selection_plan",
        "purpose": (
            "select blind transfer events from Center Hill release values "
            "before acquiring downstream or tributary observation values"
        ),
        "release_candidate_pool": {
            "series_id": CWMS_SERIES_ID,
            "office": CWMS_OFFICE,
            "begin": CWMS_BEGIN,
            "end": CWMS_END,
            "unit": "cms",
            "expected_inclusive_hour_count": 43_825,
        },
        "predeclared_event_selection": {
            "event_count": EVENT_COUNT,
            "window_hours_before_step": EVENT_BEFORE_STEP_HOURS,
            "window_hours_after_step": EVENT_AFTER_STEP_HOURS,
            "window_duration_hours": EVENT_DURATION_HOURS,
            "minimum_absolute_one_hour_step_m3s": MINIMUM_STEP_M3S,
            "minimum_window_range_m3s": MINIMUM_WINDOW_RANGE_M3S,
            "minimum_event_separation_days": MINIMUM_EVENT_SEPARATION_DAYS,
            "stage28_development_exclusion_days": STAGE28_EXCLUSION_DAYS,
            "ranking": (
                "descending_absolute_step_then_descending_window_range_"
                "then_ascending_step_time"
            ),
            "selection_data": "cwms_release_values_only",
            "selected_role": "blind_transfer",
        },
        "predeclared_transfer_diagnostic": {
            "lag_candidates_hours": list(LAG_CANDIDATES_HOURS),
            "stage28_fixed_lag_hours": STAGE28_DIAGNOSTIC_LAG_HOURS,
            "observation_extension_hours": OBSERVATION_EXTENSION_HOURS,
            "hourly_aggregation": (
                "mean_of_two_observed_half_hour_samples_in_open_closed_hour"
            ),
            "missing_sample_policy": "drop_hour_without_filling",
            "per_event_support_threshold": {
                "best_lag_distance_from_stage28_hours": 2,
                "fixed_lag_minimum_pearson_r": 0.8,
                "best_minus_fixed_maximum_pearson_r": 0.05,
                "minimum_pair_count": 60,
            },
            "stable_transfer_requirement": "all_three_events_support_fixed_lag",
        },
        "request_boundary": {
            "allowed_hosts": sorted(ALLOWED_HOSTS),
            "maximum_request_count": MAXIMUM_SELECTION_REQUEST_COUNT,
            "maximum_total_download_bytes": (
                MAXIMUM_SELECTION_DOWNLOAD_BYTES
            ),
            "planned_maximum_bytes": planned_bytes,
            "workspace_or_private_data_sent": False,
            "downstream_or_tributary_observation_values_requested": False,
            "cwms_fixed_ip_fallback_retains_tls_hostname_verification": True,
        },
        "sources": sources,
        "claim_boundary": {
            "release_values_acquired": values_mode,
            "events_selected": False,
            "downstream_values_acquired": False,
            "tributary_values_acquired": False,
            "blind_transfer_completed": False,
            "stable_travel_time_admitted": False,
            "observed_lateral_inflow_total_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _selection_sources() -> list[dict[str, Any]]:
    cwms_query = urllib.parse.urlencode(
        {
            "name": CWMS_SERIES_ID,
            "office": CWMS_OFFICE,
            "begin": CWMS_BEGIN,
            "end": CWMS_END,
            "unit": "cms",
            "page-size": CWMS_PAGE_SIZE,
        }
    )
    return [
        {
            "source_id": "cwms_release_candidate_pool",
            "source": "usace_cwms",
            "url": f"{CWMS_ROOT}/timeseries?{cwms_query}",
            "output_name": "raw/cwms_release_candidate_pool.json",
            "maximum_bytes": 5_000_000,
            "role": "release_only_event_candidate_pool",
            "source_terms": CWMS_SOURCE_TERMS,
            "source_terms_url": CWMS_SOURCE_URL,
        },
        {
            "source_id": "usgs_smith_fork_site",
            "source": "usgs_water_data",
            "url": (
                "https://api.waterdata.usgs.gov/ogcapi/v0/collections/"
                "monitoring-locations/items/USGS-03424730?f=json"
            ),
            "output_name": "raw/usgs_smith_fork_site.json",
            "maximum_bytes": 150_000,
            "role": "observed_tributary_site_identity",
            "license": USGS_LICENSE,
            "license_url": USGS_LICENSE_URL,
        },
        {
            "source_id": "usgs_smith_fork_series_metadata",
            "source": "usgs_water_data",
            "url": (
                "https://api.waterdata.usgs.gov/ogcapi/v0/collections/"
                "time-series-metadata/items?f=json&limit=10000&"
                "monitoring_location_id=USGS-03424730"
            ),
            "output_name": "raw/usgs_smith_fork_series_metadata.json",
            "maximum_bytes": 500_000,
            "role": "observed_tributary_parameter_and_time_support",
            "license": USGS_LICENSE,
            "license_url": USGS_LICENSE_URL,
        },
        {
            "source_id": "nldi_smith_fork_site",
            "source": "usgs_nldi",
            "url": (
                "https://api.water.usgs.gov/nldi/linked-data/nwissite/"
                "USGS-03424730"
            ),
            "output_name": "raw/nldi_smith_fork_site.json",
            "maximum_bytes": 150_000,
            "role": "observed_tributary_comid_binding",
            "license": USGS_LICENSE,
            "license_url": USGS_LICENSE_URL,
        },
        {
            "source_id": "nldi_smith_fork_downstream_path",
            "source": "usgs_nldi",
            "url": (
                "https://api.water.usgs.gov/nldi/linked-data/nwissite/"
                "USGS-03424730/navigation/DM/flowlines?distance=50"
            ),
            "output_name": "raw/nldi_smith_fork_downstream_path.json",
            "maximum_bytes": 2_000_000,
            "role": "tributary_to_stonewall_downstream_topology_path",
            "license": USGS_LICENSE,
            "license_url": USGS_LICENSE_URL,
        },
    ]


def compile_observation_plan(
    selection_manifest_path: Path | None = None,
) -> dict[str, Any]:
    path = selection_manifest_path or (
        DEFAULT_OUTPUT / "event_selection_manifest.json"
    )
    selection = _read_json(path)
    _validate_selection_manifest_shape(selection)
    sources = _observation_sources(selection["selected_events"])
    planned_bytes = sum(int(value["maximum_bytes"]) for value in sources)
    if (
        len(sources) != MAXIMUM_OBSERVATION_REQUEST_COUNT
        or planned_bytes > MAXIMUM_OBSERVATION_DOWNLOAD_BYTES
    ):
        raise ValueError("stage29_observation_request_boundary_exceeded")
    return {
        "schema": OBSERVATION_SCHEMA,
        "mode": "observation_plan",
        "purpose": (
            "acquire downstream and one observed tributary series only after "
            "release-side blind transfer events are hash frozen"
        ),
        "frozen_event_selection_manifest": _artifact(path),
        "selected_events": selection["selected_events"],
        "predeclared_transfer_diagnostic": compile_selection_plan()[
            "predeclared_transfer_diagnostic"
        ],
        "request_boundary": {
            "allowed_hosts": ["api.waterdata.usgs.gov"],
            "maximum_request_count": MAXIMUM_OBSERVATION_REQUEST_COUNT,
            "maximum_total_download_bytes": (
                MAXIMUM_OBSERVATION_DOWNLOAD_BYTES
            ),
            "planned_maximum_bytes": planned_bytes,
            "workspace_or_private_data_sent": False,
            "event_selection_may_be_recomputed_from_observations": False,
        },
        "sources": sources,
        "claim_boundary": {
            "events_hash_frozen_before_observation_values": True,
            "downstream_values_acquired": False,
            "tributary_values_acquired": False,
            "travel_time_admitted": False,
            "observed_lateral_inflow_total_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _observation_sources(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event["event_id"])
        start = _parse_time(str(event["start_utc"]))
        end = _parse_time(str(event["end_utc"])) + timedelta(
            hours=OBSERVATION_EXTENSION_HOURS
        )
        for site_id, site_role in (
            (DOWNSTREAM_SITE_ID, "downstream_outcome"),
            (TRIBUTARY_SITE_ID, "observed_tributary_state"),
        ):
            query = urllib.parse.urlencode(
                {
                    "f": "json",
                    "limit": 10000,
                    "monitoring_location_id": site_id,
                    "parameter_code": PARAMETER_CODE,
                    "datetime": f"{_iso(start)}/{_iso(end)}",
                }
            )
            short_id = site_id.removeprefix("USGS-")
            sources.append(
                {
                    "source_id": f"usgs_{short_id}_{event_id}",
                    "source": "usgs_water_data",
                    "event_id": event_id,
                    "site_id": site_id,
                    "site_role": site_role,
                    "url": (
                        "https://api.waterdata.usgs.gov/ogcapi/v0/"
                        f"collections/continuous/items?{query}"
                    ),
                    "output_name": (
                        f"raw/usgs_{short_id}_{event_id}.json"
                    ),
                    "maximum_bytes": 2_000_000,
                    "role": f"blind_transfer_{site_role}_values",
                    "license": USGS_LICENSE,
                    "license_url": USGS_LICENSE_URL,
                }
            )
    return sources


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage29_positive_request_limits_required")
    output = _validate_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.phase == "selection-plan":
        path = output / "selection_plan.json"
        _write_json(path, compile_selection_plan())
        print(path)
        return 0
    if args.phase == "release":
        path = _acquire_release_selection(args, output)
        print(path)
        return 0
    if args.phase == "observation-plan":
        selection_path = output / "event_selection_manifest.json"
        path = output / "observation_plan.json"
        _write_json(path, compile_observation_plan(selection_path))
        print(path)
        return 0
    path = _acquire_observations(args, output)
    print(path)
    return 0


def _acquire_release_selection(
    args: argparse.Namespace, output: Path
) -> Path:
    frozen_path = output / "selection_plan.json"
    frozen_plan = _load_exact_plan(frozen_path, compile_selection_plan())
    values_plan = compile_selection_plan(values_mode=True)
    opener = _opener(args.proxy)
    artifacts: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for source in values_plan["sources"]:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        payload = _json_object(body)
        _validate_selection_source(str(source["source_id"]), payload)
        total_bytes = _checked_total(
            total_bytes,
            len(body),
            maximum=MAXIMUM_SELECTION_DOWNLOAD_BYTES,
        )
        raw_path = output / str(source["output_name"])
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
        artifacts.append(
            _artifact_record(raw_path, source=source, retrieval=retrieval)
        )
        payloads[str(source["source_id"])] = payload

    candidates, selected = _select_events(
        payloads["cwms_release_candidate_pool"]
    )
    candidate_path = output / "release_event_candidate_ledger.json"
    _write_json(
        candidate_path,
        {
            "schema": "gwm.geotransport.stage29_release_event_candidates.v1",
            "selection_protocol": values_plan["predeclared_event_selection"],
            "eligible_candidate_count": len(candidates),
            "eligible_candidates": candidates,
            "selected_events": selected,
            "downstream_or_tributary_values_loaded": False,
        },
    )
    manifest = {
        **values_plan,
        "status": "release_selected_events_frozen_before_observations",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "frozen_selection_plan": _artifact(frozen_path),
        "frozen_selection_plan_content": frozen_plan,
        "release_event_candidate_ledger": _artifact(candidate_path),
        "eligible_candidate_count": len(candidates),
        "selected_events": selected,
        "selected_event_count": len(selected),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "actual_request_count": len(artifacts),
        "total_downloaded_bytes": total_bytes,
        "claim_boundary_after_release_selection": {
            "events_selected_from_release_only": True,
            "events_hash_frozen": True,
            "downstream_values_acquired": False,
            "tributary_values_acquired": False,
            "blind_transfer_completed": False,
            "stable_travel_time_admitted": False,
            "observed_lateral_inflow_total_admitted": False,
            "runtime_operator_admitted": False,
        },
    }
    path = output / "event_selection_manifest.json"
    _write_json(path, manifest)
    print(f"eligible_candidates={len(candidates)}")
    print(f"selected_events={len(selected)}")
    print(f"downloaded_bytes={total_bytes}")
    return path


def _acquire_observations(
    args: argparse.Namespace, output: Path
) -> Path:
    selection_path = output / "event_selection_manifest.json"
    expected_plan = compile_observation_plan(selection_path)
    frozen_path = output / "observation_plan.json"
    frozen_plan = _load_exact_plan(frozen_path, expected_plan)
    opener = _opener(args.proxy)
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    for source in frozen_plan["sources"]:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        payload = _json_object(body)
        _validate_observation_values(payload, source)
        total_bytes = _checked_total(
            total_bytes,
            len(body),
            maximum=MAXIMUM_OBSERVATION_DOWNLOAD_BYTES,
        )
        raw_path = output / str(source["output_name"])
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
        artifacts.append(
            _artifact_record(raw_path, source=source, retrieval=retrieval)
        )
    manifest = {
        **frozen_plan,
        "mode": "observation_values",
        "status": "blind_transfer_observations_acquired",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "frozen_observation_plan": _artifact(frozen_path),
        "frozen_observation_plan_content": frozen_plan,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "actual_request_count": len(artifacts),
        "total_downloaded_bytes": total_bytes,
        "claim_boundary_after_observations": {
            "events_hash_frozen_before_observation_values": True,
            "downstream_values_acquired": True,
            "tributary_values_acquired": True,
            "blind_transfer_scored": False,
            "stable_travel_time_admitted": False,
            "observed_tributary_state_admitted": False,
            "observed_lateral_inflow_total_admitted": False,
            "runtime_operator_admitted": False,
        },
    }
    path = output / "observation_acquisition_manifest.json"
    _write_json(path, manifest)
    print(f"requests={len(artifacts)}")
    print(f"downloaded_bytes={total_bytes}")
    return path


def _select_events(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = payload["values"]
    series = tuple(
        (
            datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc),
            float(row[1]),
            int(row[2]),
        )
        for row in rows
    )
    excluded_start = _parse_time(STAGE28_DEVELOPMENT_START) - timedelta(
        days=STAGE28_EXCLUSION_DAYS
    )
    excluded_end = _parse_time(STAGE28_DEVELOPMENT_END) + timedelta(
        days=STAGE28_EXCLUSION_DAYS
    )
    candidates = []
    for index in range(EVENT_BEFORE_STEP_HOURS, len(series) - EVENT_AFTER_STEP_HOURS):
        step_time, current, _ = series[index]
        previous = series[index - 1][1]
        absolute_step = abs(current - previous)
        if absolute_step < MINIMUM_STEP_M3S:
            continue
        window = series[
            index - EVENT_BEFORE_STEP_HOURS : index + EVENT_AFTER_STEP_HOURS + 1
        ]
        expected = tuple(
            window[0][0] + timedelta(hours=offset)
            for offset in range(EVENT_DURATION_HOURS + 1)
        )
        if tuple(value[0] for value in window) != expected:
            continue
        window_range = max(value[1] for value in window) - min(
            value[1] for value in window
        )
        if window_range < MINIMUM_WINDOW_RANGE_M3S:
            continue
        if excluded_start <= step_time <= excluded_end:
            continue
        candidates.append(
            {
                "step_time_utc": _iso(step_time),
                "signed_step_m3s": current - previous,
                "absolute_step_m3s": absolute_step,
                "window_range_m3s": window_range,
                "start_utc": _iso(window[0][0]),
                "end_utc": _iso(window[-1][0]),
                "inclusive_release_value_count": len(window),
                "quality_codes": sorted({value[2] for value in window}),
            }
        )
    candidates.sort(
        key=lambda value: (
            -float(value["absolute_step_m3s"]),
            -float(value["window_range_m3s"]),
            str(value["step_time_utc"]),
        )
    )
    selected: list[dict[str, Any]] = []
    separation = timedelta(days=MINIMUM_EVENT_SEPARATION_DAYS)
    for candidate in candidates:
        step_time = _parse_time(str(candidate["step_time_utc"]))
        if any(
            abs(step_time - _parse_time(str(value["step_time_utc"])))
            < separation
            for value in selected
        ):
            continue
        selected.append(
            {
                **candidate,
                "event_id": f"release_step_{step_time:%Y%m%dT%H%MZ}",
                "role": "blind_transfer",
                "selection_rank": len(selected) + 1,
                "selected_without_observation_values": True,
            }
        )
        if len(selected) == EVENT_COUNT:
            break
    if len(selected) != EVENT_COUNT:
        raise ValueError("stage29_three_release_selected_events_unavailable")
    return candidates, selected


def _validate_selection_source(source_id: str, value: dict[str, Any]) -> None:
    if source_id == "cwms_release_candidate_pool":
        _validate_cwms_pool(value)
    elif source_id == "usgs_smith_fork_site":
        if (
            value.get("id") != TRIBUTARY_SITE_ID
            or (value.get("properties") or {}).get("site_type") != "Stream"
            or (value.get("properties") or {}).get("drainage_area") != 214.0
        ):
            raise ValueError("stage29_smith_fork_site_invalid")
    elif source_id == "usgs_smith_fork_series_metadata":
        features = value.get("features") or []
        if not any(
            feature.get("id") == "c59c7559af4f4a0ebef64eb811803ea0"
            and feature["properties"].get("monitoring_location_id")
            == TRIBUTARY_SITE_ID
            and feature["properties"].get("parameter_code") == PARAMETER_CODE
            and feature["properties"].get("statistic_id") == "00011"
            and feature["properties"].get("computation_identifier")
            == "Instantaneous"
            and feature["properties"].get("unit_of_measure") == "ft^3/s"
            for feature in features
        ):
            raise ValueError("stage29_smith_fork_series_metadata_invalid")
    elif source_id == "nldi_smith_fork_site":
        features = value.get("features") or []
        properties = features[0].get("properties") if len(features) == 1 else {}
        if (
            properties.get("identifier") != TRIBUTARY_SITE_ID
            or properties.get("comid") != 18421273
        ):
            raise ValueError("stage29_smith_fork_nldi_binding_invalid")
    elif source_id == "nldi_smith_fork_downstream_path":
        ids = {int(feature["id"]) for feature in value.get("features") or []}
        if not {18421273, 18421743, 18421703}.issubset(ids):
            raise ValueError("stage29_smith_fork_downstream_path_invalid")
    else:
        raise ValueError("stage29_selection_source_unknown")


def _validate_cwms_pool(value: dict[str, Any]) -> None:
    rows = value.get("values")
    expected_start = _parse_time(CWMS_BEGIN)
    if (
        value.get("name") != CWMS_SERIES_ID
        or value.get("office-id") != CWMS_OFFICE
        or value.get("units") != "cms"
        or value.get("interval") != "PT1H"
        or value.get("interval-offset") != 0
        or value.get("page-size") != CWMS_PAGE_SIZE
        or not isinstance(rows, list)
        or len(rows) != 43_825
        or value.get("total") != len(rows)
    ):
        raise ValueError("stage29_cwms_candidate_pool_invalid")
    for index, row in enumerate(rows):
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[0], int)
            or not isinstance(row[1], (int, float))
            or not math.isfinite(float(row[1]))
            or not isinstance(row[2], int)
            or datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc)
            != expected_start + timedelta(hours=index)
        ):
            raise ValueError("stage29_cwms_candidate_pool_row_invalid")


def _validate_observation_values(
    value: dict[str, Any], source: dict[str, Any]
) -> None:
    features = value.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("stage29_observation_values_empty")
    times = []
    for feature in features:
        properties = feature.get("properties") or {}
        if (
            properties.get("monitoring_location_id") != source["site_id"]
            or properties.get("parameter_code") != PARAMETER_CODE
            or properties.get("statistic_id") != "00011"
            or properties.get("unit_of_measure") != "ft^3/s"
            or not isinstance(properties.get("approval_status"), str)
        ):
            raise ValueError("stage29_observation_value_row_invalid")
        float(properties["value"])
        times.append(_parse_time(str(properties["time"])))
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError("stage29_observation_time_axis_invalid")


def _validate_selection_manifest_shape(value: dict[str, Any]) -> None:
    after = value.get("claim_boundary_after_release_selection") or {}
    if (
        value.get("schema") != SELECTION_SCHEMA
        or value.get("status")
        != "release_selected_events_frozen_before_observations"
        or value.get("selected_event_count") != EVENT_COUNT
        or len(value.get("selected_events") or []) != EVENT_COUNT
        or any(
            event.get("role") != "blind_transfer"
            or event.get("selected_without_observation_values") is not True
            for event in value.get("selected_events") or []
        )
        or after.get("events_selected_from_release_only") is not True
        or after.get("events_hash_frozen") is not True
        or after.get("downstream_values_acquired") is not False
        or after.get("tributary_values_acquired") is not False
    ):
        raise ValueError("stage29_event_selection_manifest_invalid")


def _load_exact_plan(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("stage29_plan_must_be_frozen_before_values")
    value = _read_json(path)
    if value != expected:
        raise ValueError("stage29_frozen_plan_mismatch")
    return value


def _fetch(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    host = _validate_url(url)
    failures: list[dict[str, Any]] = []
    error: Exception | None = None
    accept = (
        "application/json;version=2"
        if host == CWMS_HOST
        else "application/json"
    )
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url, headers={"Accept": accept, "User-Agent": USER_AGENT}
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                _validate_url(response.geturl())
                body = response.read(maximum_bytes + 1)
                _validate_size(body, maximum_bytes)
                return body, {
                    "url": url,
                    "transport": "configured_proxy_or_direct_urllib",
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "failed_attempts": failures,
                    "tls_hostname_verification_retained": True,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            error = exc
            failures.append(
                {
                    "transport": "configured_proxy_or_direct_urllib",
                    "attempt": attempt,
                    "error": str(exc),
                }
            )
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                break
            if attempt < retries:
                time.sleep(float(attempt))
    if host == CWMS_HOST:
        for resolved_ip in CWMS_RESOLVED_IPS:
            command = _cwms_curl_command(
                url,
                resolved_ip=resolved_ip,
                timeout_seconds=timeout_seconds,
            )
            result = subprocess.run(command, capture_output=True, check=False)
            if result.returncode == 0:
                _validate_size(result.stdout, maximum_bytes)
                return result.stdout, {
                    "url": url,
                    "transport": f"direct_resolve_{resolved_ip}",
                    "http_status": 200,
                    "content_type": "application/json",
                    "attempt_count": len(failures) + 1,
                    "failed_attempts": failures,
                    "tls_hostname_verification_retained": True,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
            failures.append(
                {
                    "transport": f"direct_resolve_{resolved_ip}",
                    "returncode": result.returncode,
                    "error": result.stderr.decode("utf-8", errors="replace"),
                }
            )
    raise RuntimeError(f"stage29_request_failed:{error}:{failures}")


def _cwms_curl_command(
    url: str, *, resolved_ip: str, timeout_seconds: float
) -> list[str]:
    if resolved_ip not in CWMS_RESOLVED_IPS or _validate_url(url) != CWMS_HOST:
        raise ValueError("stage29_cwms_resolved_transport_invalid")
    return [
        "curl",
        "--noproxy",
        "*",
        "--resolve",
        f"{CWMS_HOST}:443:{resolved_ip}",
        "-fsS",
        "--retry",
        "2",
        "--retry-all-errors",
        "--connect-timeout",
        "15",
        "--max-time",
        str(max(1, int(timeout_seconds))),
        "-A",
        USER_AGENT,
        "-H",
        "Accept: application/json;version=2",
        url,
    ]


def _validate_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("stage29_url_outside_allowlist")
    return str(parsed.hostname)


def _validate_output(path: Path) -> Path:
    output = path.resolve()
    data_root = (REPO_ROOT / "data/geotransport_v0_1").resolve()
    if output != data_root and data_root not in output.parents:
        raise ValueError("stage29_output_outside_data_root")
    return output


def _validate_size(body: bytes, maximum_bytes: int) -> None:
    if len(body) > maximum_bytes:
        raise ValueError("stage29_object_size_limit_exceeded")


def _checked_total(current: int, added: int, *, maximum: int) -> int:
    total = current + added
    if total > maximum:
        raise ValueError("stage29_total_size_limit_exceeded")
    return total


def _artifact_record(
    path: Path, *, source: dict[str, Any], retrieval: dict[str, Any]
) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "source": source["source"],
        "role": source["role"],
        "event_id": source.get("event_id"),
        "site_id": source.get("site_id"),
        "site_role": source.get("site_role"),
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "hash_verified": True,
        "license": source.get("license"),
        "license_url": source.get("license_url"),
        "source_terms": source.get("source_terms"),
        "source_terms_url": source.get("source_terms_url"),
        **retrieval,
    }


def _artifact(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_object(body: bytes) -> dict[str, Any]:
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("stage29_json_object_required")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return _json_object(path.read_bytes())


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage29_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(*handlers)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
