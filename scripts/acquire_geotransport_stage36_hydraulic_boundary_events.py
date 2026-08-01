#!/usr/bin/env python3
"""Plan and acquire source-only Stage 36 hydraulic-boundary events."""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    hydraulic_boundary_perturbation as perturbation,
)
from scripts import (  # noqa: E402
    acquire_geotransport_stage29_blind_transfer_events as stage29,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage36_hydraulic_boundary_event_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE36_ROOT
SCHEMA = "gwm.geotransport.stage36_tailwater_event_selection.v1"
OBSERVATION_SCHEMA = (
    "gwm.geotransport.stage36_downstream_observation_acquisition.v1"
)
USER_AGENT = "gisdataagent-stage36-hydraulic-boundary-events/0.1"
CWMS_HOST = "cwms-data.usace.army.mil"
CWMS_ROOT = f"https://{CWMS_HOST}/cwms-data"
USGS_HOST = "api.waterdata.usgs.gov"
USGS_ROOT = (
    "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"
)
TARGET_SITE_ID = "USGS-03424860"
TARGET_PARAMETER_CODE = "00060"
CWMS_SERIES_ID = (
    "CETT1-CENTER_HILL.Elev-Tail.Inst.30Minutes.0.dcp-rev"
)
CWMS_OFFICE = "LRN"
CWMS_BEGIN = "2021-01-01T00:00:00Z"
CWMS_END = "2026-01-01T00:00:00Z"
CWMS_PAGE_SIZE = 20_000
YEAR_WINDOWS = tuple(
    (
        f"{year}-01-01T00:00:00Z",
        f"{year + 1}-01-01T00:00:00Z",
    )
    for year in range(2021, 2026)
)
PROTOCOL_PATH = REPO_ROOT / freeze.STAGE36_ROOT / "protocol.json"
FROZEN_PROTOCOL_SHA256 = (
    "b0be7dedec2b7dfd933f2c81ea16a2b6bf853a3acafa499fd9beef84f7551ff7"
)
EVENT_COUNT = 4
EVENT_BEFORE_INTERVALS = 48
EVENT_AFTER_INTERVALS = 96
MINIMUM_EVENT_SEPARATION_DAYS = 180
PRIOR_OUTCOME_EXCLUSION_DAYS = 14
DEVELOPMENT_EXCLUSION_DAYS = 90
MAXIMUM_REQUEST_COUNT = 5
MAXIMUM_BYTES_PER_REQUEST = 1_000_000
MAXIMUM_TOTAL_DOWNLOAD_BYTES = 5_000_000
MAXIMUM_OBSERVATION_REQUEST_COUNT = 4
MAXIMUM_OBSERVATION_BYTES_PER_REQUEST = 1_000_000
MAXIMUM_OBSERVATION_DOWNLOAD_BYTES = 4_000_000
EXPECTED_UNIQUE_SAMPLE_COUNT = 87_649
ATTEMPT_AUDIT_SCHEMA = (
    "gwm.geotransport.stage36_interrupted_acquisition_attempt_audit.v1"
)
ATTEMPT_AUDIT_NAME = "interrupted_acquisition_attempt_audit.json"
CWMS_SOURCE_TERMS = (
    "USACE CWMS Data API public endpoint; redistribution terms not "
    "independently adjudicated"
)
CWMS_SOURCE_URL = "https://cwms-data.usace.army.mil/cwms-data/swagger-ui.html"
USGS_LICENSE = "USGS public-domain data"
USGS_LICENSE_URL = (
    "https://www.usgs.gov/information-policies-and-instructions/"
    "copyrights-and-credits"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=(
            "selection-plan",
            "tailwater",
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
    protocol_artifact = _frozen_protocol_artifact()
    sources = _selection_sources()
    planned_bytes = sum(int(value["maximum_bytes"]) for value in sources)
    if (
        len(sources) != MAXIMUM_REQUEST_COUNT
        or planned_bytes > MAXIMUM_TOTAL_DOWNLOAD_BYTES
    ):
        raise ValueError("stage36_selection_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "tailwater_values" if values_mode else "selection_plan",
        "purpose": (
            "select blind hydraulic-boundary events from Center Hill "
            "tailwater elevation before any new downstream observation request"
        ),
        "frozen_protocol_artifact": protocol_artifact,
        "frozen_operator_artifact": freeze.artifact_record(
            freeze.OPERATOR_PATH
        ),
        "candidate_pool": {
            "series_id": CWMS_SERIES_ID,
            "office": CWMS_OFFICE,
            "unit": "m",
            "begin_utc": CWMS_BEGIN,
            "end_utc": CWMS_END,
            "interval_minutes": 30,
            "expected_unique_inclusive_sample_count": (
                EXPECTED_UNIQUE_SAMPLE_COUNT
            ),
            "annual_request_windows_share_boundary_samples": True,
            "duplicate_boundary_policy": (
                "require_identical_then_keep_one"
            ),
        },
        "frozen_source_gate": freeze.build_protocol()[
            "frozen_source_gate"
        ],
        "predeclared_event_selection": freeze.build_protocol()[
            "predeclared_event_selection"
        ],
        "predeclared_target_functional": freeze.build_protocol()[
            "predeclared_target_functional"
        ],
        "blinding_protocol": freeze.build_protocol()["blinding_protocol"],
        "request_boundary": {
            "allowed_hosts": [CWMS_HOST],
            "maximum_request_count": MAXIMUM_REQUEST_COUNT,
            "maximum_attempts_per_request": 3,
            "maximum_bytes_per_request": MAXIMUM_BYTES_PER_REQUEST,
            "maximum_total_download_bytes": MAXIMUM_TOTAL_DOWNLOAD_BYTES,
            "planned_maximum_bytes": planned_bytes,
            "workspace_or_private_data_sent": False,
            "release_values_requested": False,
            "downstream_or_tributary_observation_values_requested": False,
            "server_returned_pagination_followed": False,
        },
        "sources": sources,
        "claim_boundary": {
            "candidate_pool_values_acquired": values_mode,
            "events_selected": False,
            "downstream_values_acquired": False,
            "statistical_departures_compiled": False,
            "physical_travel_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _selection_sources() -> list[dict[str, Any]]:
    sources = []
    for index, (begin, end) in enumerate(YEAR_WINDOWS, start=1):
        query = urllib.parse.urlencode(
            {
                "name": CWMS_SERIES_ID,
                "office": CWMS_OFFICE,
                "begin": begin,
                "end": end,
                "unit": "m",
                "page-size": CWMS_PAGE_SIZE,
            }
        )
        sources.append(
            {
                "source_id": f"cwms_tailwater_stage_part_{index}",
                "source": "usace_cwms",
                "url": f"{CWMS_ROOT}/timeseries?{query}",
                "output_name": (
                    f"raw/cwms_tailwater_stage_{begin[:4]}.json"
                ),
                "begin_utc": begin,
                "end_utc": end,
                "maximum_bytes": MAXIMUM_BYTES_PER_REQUEST,
                "role": "source_only_tailwater_elevation_candidate_pool",
                "source_terms": CWMS_SOURCE_TERMS,
                "source_terms_url": CWMS_SOURCE_URL,
            }
        )
    return sources


def compile_observation_plan(
    selection_manifest_path: Path | None = None,
    *,
    values_mode: bool = False,
) -> dict[str, Any]:
    path = selection_manifest_path or (
        DEFAULT_OUTPUT / "event_selection_manifest.json"
    )
    selection = stage29._read_json(path)
    _validate_selection_manifest_shape(selection)
    sources = _observation_sources(selection["selected_events"])
    planned_bytes = sum(int(value["maximum_bytes"]) for value in sources)
    if (
        len(sources) != MAXIMUM_OBSERVATION_REQUEST_COUNT
        or planned_bytes > MAXIMUM_OBSERVATION_DOWNLOAD_BYTES
    ):
        raise ValueError("stage36_observation_request_boundary_exceeded")
    return {
        "schema": OBSERVATION_SCHEMA,
        "mode": "observation_values" if values_mode else "observation_plan",
        "purpose": (
            "acquire the four frozen downstream discharge windows only after "
            "source-only hydraulic-boundary event selection"
        ),
        "frozen_event_selection_manifest": stage29._artifact(path),
        "frozen_protocol_artifact": selection["frozen_protocol_artifact"],
        "frozen_operator_artifact": selection["frozen_operator_artifact"],
        "selected_events": selection["selected_events"],
        "predeclared_target_functional": selection[
            "predeclared_target_functional"
        ],
        "request_boundary": {
            "allowed_hosts": [USGS_HOST],
            "maximum_request_count": MAXIMUM_OBSERVATION_REQUEST_COUNT,
            "maximum_attempts_per_request": 3,
            "maximum_bytes_per_request": (
                MAXIMUM_OBSERVATION_BYTES_PER_REQUEST
            ),
            "maximum_total_download_bytes": (
                MAXIMUM_OBSERVATION_DOWNLOAD_BYTES
            ),
            "planned_maximum_bytes": planned_bytes,
            "workspace_or_private_data_sent": False,
            "release_or_tributary_values_requested": False,
            "event_selection_may_be_recomputed_from_outcomes": False,
            "source_or_target_threshold_retuning_allowed": False,
        },
        "sources": sources,
        "claim_boundary": {
            "events_operator_and_target_functional_frozen_before_outcomes": True,
            "downstream_values_acquired": values_mode,
            "statistical_departures_compiled": False,
            "causal_response_admitted": False,
            "physical_first_arrival_admitted": False,
            "physical_travel_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _observation_sources(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources = []
    for event in events:
        marker = stage29._parse_time(str(event["marker_time_utc"]))
        begin = stage29._iso(marker - timedelta(hours=24))
        end = stage29._iso(marker + timedelta(hours=24))
        query = urllib.parse.urlencode(
            {
                "f": "json",
                "limit": 10_000,
                "monitoring_location_id": TARGET_SITE_ID,
                "parameter_code": TARGET_PARAMETER_CODE,
                "datetime": f"{begin}/{end}",
            }
        )
        event_id = str(event["event_id"])
        sources.append(
            {
                "source_id": f"usgs_downstream_{event_id}",
                "source": "usgs_water_data",
                "event_id": event_id,
                "site_id": TARGET_SITE_ID,
                "site_role": "downstream_target",
                "begin_utc": begin,
                "end_utc": end,
                "url": f"{USGS_ROOT}?{query}",
                "output_name": f"raw/usgs_03424860_{event_id}.json",
                "maximum_bytes": MAXIMUM_OBSERVATION_BYTES_PER_REQUEST,
                "role": "blind_first_persistent_departure_target_values",
                "license": USGS_LICENSE,
                "license_url": USGS_LICENSE_URL,
            }
        )
    return sources


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries not in range(1, 4):
        raise ValueError("stage36_bounded_positive_request_limits_required")
    output = stage29._validate_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.phase == "selection-plan":
        path = output / "selection_plan.json"
        stage29._write_json(path, compile_selection_plan())
    elif args.phase == "tailwater":
        path = _acquire_tailwater_selection(args, output)
    elif args.phase == "observation-plan":
        path = output / "observation_plan.json"
        stage29._write_json(
            path,
            compile_observation_plan(output / "event_selection_manifest.json"),
        )
    else:
        path = _acquire_observations(args, output)
    print(path)
    return 0


def _acquire_tailwater_selection(
    args: argparse.Namespace, output: Path
) -> Path:
    plan_path = output / "selection_plan.json"
    frozen_plan = _load_exact_plan(plan_path, compile_selection_plan())
    values_plan = compile_selection_plan(values_mode=True)
    opener = stage29._opener(args.proxy)
    attempt_audit_path = output / ATTEMPT_AUDIT_NAME
    prior_attempts = _load_attempt_audit(attempt_audit_path, values_plan["sources"])
    payloads = []
    artifacts = []
    total_bytes = 0
    total_attempts = 0
    resumed_response_count = 0
    network_requests_in_resume_run = 0
    for source in values_plan["sources"]:
        source_id = str(source["source_id"])
        raw_path = output / str(source["output_name"])
        prior = prior_attempts[source_id]
        if raw_path.is_file():
            body = raw_path.read_bytes()
            actual_hash = hashlib.sha256(body).hexdigest()
            if (
                prior["attempts_before_resume"] <= 0
                or prior["persisted_response_sha256"] != actual_hash
            ):
                raise ValueError("stage36_resumed_response_audit_mismatch")
            retrieval = {
                "url": source["url"],
                "transport": "existing_approved_response_after_interruption",
                "http_status": 200,
                "content_type": "application/json",
                "attempt_count": prior["attempts_before_resume"],
                "failed_attempts": [],
                "tls_hostname_verification_retained": True,
                "retrieved_at": None,
                "reused_existing_response": True,
            }
            resumed_response_count += 1
        else:
            if prior["attempts_before_resume"] != 0:
                raise ValueError("stage36_audited_response_missing")
            body, retrieval = _fetch(
                str(source["url"]),
                opener=opener,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                maximum_bytes=int(source["maximum_bytes"]),
                allowed_host=CWMS_HOST,
                accept="application/json;version=2",
            )
            network_requests_in_resume_run += 1
        payload = stage29._json_object(body)
        _validate_tailwater_payload(payload, source)
        total_bytes = stage29._checked_total(
            total_bytes,
            len(body),
            maximum=MAXIMUM_TOTAL_DOWNLOAD_BYTES,
        )
        total_attempts += int(retrieval["attempt_count"])
        if int(retrieval["attempt_count"]) > 3:
            raise ValueError("stage36_attempt_boundary_exceeded")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
        artifacts.append(
            stage29._artifact_record(
                raw_path,
                source=source,
                retrieval=retrieval,
            )
        )
        payloads.append(payload)

    series = _combine_tailwater_payloads(payloads)
    candidates, selected = _select_events(series)
    candidate_path = output / "tailwater_event_candidate_ledger.json"
    stage29._write_json(
        candidate_path,
        {
            "schema": "gwm.geotransport.stage36_tailwater_event_candidates.v1",
            "frozen_protocol_artifact": frozen_plan[
                "frozen_protocol_artifact"
            ],
            "candidate_pool_unique_sample_count": len(series),
            "eligible_candidate_count": len(candidates),
            "eligible_candidates": candidates,
            "selected_events": selected,
            "release_values_loaded": False,
            "downstream_or_tributary_values_loaded": False,
        },
    )
    manifest = {
        **values_plan,
        "status": "hydraulic_boundary_events_frozen_before_outcomes",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "frozen_selection_plan": stage29._artifact(plan_path),
        "frozen_selection_plan_content": frozen_plan,
        "tailwater_event_candidate_ledger": stage29._artifact(candidate_path),
        "candidate_pool_unique_sample_count": len(series),
        "eligible_candidate_count": len(candidates),
        "selected_events": selected,
        "selected_event_count": len(selected),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "logical_request_count": len(artifacts),
        "network_requests_in_resume_run": network_requests_in_resume_run,
        "reused_response_count": resumed_response_count,
        "actual_attempt_count": total_attempts,
        "total_downloaded_bytes": total_bytes,
        "interrupted_attempt_audit": (
            stage29._artifact(attempt_audit_path)
            if attempt_audit_path.is_file()
            else None
        ),
        "claim_boundary_after_source_selection": {
            "operator_protocol_and_events_frozen": True,
            "events_selected_from_tailwater_elevation_only": True,
            "release_values_acquired": False,
            "downstream_values_acquired": False,
            "statistical_departures_compiled": False,
            "physical_travel_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }
    path = output / "event_selection_manifest.json"
    stage29._write_json(path, manifest)
    print(f"eligible_candidates={len(candidates)}")
    print(f"selected_events={len(selected)}")
    print(f"downloaded_bytes={total_bytes}")
    return path


def _acquire_observations(args: argparse.Namespace, output: Path) -> Path:
    selection_path = output / "event_selection_manifest.json"
    plan_path = output / "observation_plan.json"
    expected = compile_observation_plan(selection_path)
    frozen_plan = _load_exact_plan(plan_path, expected)
    values_plan = compile_observation_plan(selection_path, values_mode=True)
    opener = stage29._opener(args.proxy)
    artifacts = []
    total_bytes = 0
    total_attempts = 0
    for source in values_plan["sources"]:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
            allowed_host=USGS_HOST,
            accept="application/json",
        )
        payload = stage29._json_object(body)
        _validate_observation_payload(payload, source)
        total_bytes = stage29._checked_total(
            total_bytes,
            len(body),
            maximum=MAXIMUM_OBSERVATION_DOWNLOAD_BYTES,
        )
        total_attempts += int(retrieval["attempt_count"])
        raw_path = output / str(source["output_name"])
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
        artifacts.append(
            stage29._artifact_record(
                raw_path,
                source=source,
                retrieval=retrieval,
            )
        )
    manifest = {
        **values_plan,
        "status": "stage36_downstream_observations_acquired",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "frozen_observation_plan": stage29._artifact(plan_path),
        "frozen_observation_plan_content": frozen_plan,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "actual_request_count": len(artifacts),
        "actual_attempt_count": total_attempts,
        "total_downloaded_bytes": total_bytes,
        "claim_boundary_after_observations": {
            "events_operator_and_target_functional_frozen_before_outcomes": True,
            "downstream_values_acquired": True,
            "statistical_departures_compiled": False,
            "causal_response_admitted": False,
            "physical_first_arrival_admitted": False,
            "physical_travel_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }
    path = output / "observation_acquisition_manifest.json"
    stage29._write_json(path, manifest)
    print(f"requests={len(artifacts)}")
    print(f"downloaded_bytes={total_bytes}")
    return path


def _validate_tailwater_payload(
    payload: dict[str, Any], source: dict[str, Any]
) -> None:
    rows = payload.get("values")
    begin = stage29._parse_time(str(source["begin_utc"]))
    end = stage29._parse_time(str(source["end_utc"]))
    if (
        payload.get("name") != CWMS_SERIES_ID
        or payload.get("office-id") != CWMS_OFFICE
        or payload.get("units") != "m"
        or payload.get("interval") != "PT30M"
        or payload.get("interval-offset") != 0
        or payload.get("page-size") != CWMS_PAGE_SIZE
        or not isinstance(rows, list)
        or not rows
        or payload.get("total") != len(rows)
        or len(rows) > 17_569
    ):
        raise ValueError("stage36_tailwater_candidate_pool_part_invalid")
    times = []
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[0], int)
            or (
                row[1] is not None
                and (
                    not isinstance(row[1], (int, float))
                    or not math.isfinite(float(row[1]))
                )
            )
            or not isinstance(row[2], int)
        ):
            raise ValueError("stage36_tailwater_candidate_pool_row_invalid")
        times.append(
            datetime.fromtimestamp(row[0] / 1000.0, tz=UTC)
        )
    if (
        times[0] != begin
        or times[-1] != end
        or times != sorted(times)
        or len(times) != len(set(times))
        or any(
            (right - left).total_seconds() % 1800 != 0
            for left, right in zip(times, times[1:], strict=False)
        )
    ):
        raise ValueError("stage36_tailwater_candidate_pool_time_axis_invalid")


def _validate_observation_payload(
    payload: dict[str, Any], source: dict[str, Any]
) -> None:
    features = payload.get("features")
    begin = stage29._parse_time(str(source["begin_utc"]))
    end = stage29._parse_time(str(source["end_utc"]))
    if not isinstance(features, list) or not features:
        raise ValueError("stage36_downstream_observation_values_empty")
    times = []
    for feature in features:
        properties = feature.get("properties") or {}
        if (
            properties.get("monitoring_location_id") != TARGET_SITE_ID
            or properties.get("parameter_code") != TARGET_PARAMETER_CODE
            or properties.get("statistic_id") != "00011"
            or properties.get("unit_of_measure") != "ft^3/s"
            or not isinstance(properties.get("approval_status"), str)
        ):
            raise ValueError("stage36_downstream_observation_row_invalid")
        value = float(properties["value"])
        timestamp = stage29._parse_time(str(properties["time"]))
        if not math.isfinite(value) or not begin <= timestamp <= end:
            raise ValueError("stage36_downstream_observation_row_invalid")
        times.append(timestamp)
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError("stage36_downstream_observation_time_axis_invalid")


def _combine_tailwater_payloads(
    payloads: Iterable[dict[str, Any]],
) -> tuple[tuple[datetime, float | None, int], ...]:
    by_time: dict[datetime, tuple[float | None, int]] = {}
    for payload in payloads:
        for row in payload["values"]:
            timestamp = datetime.fromtimestamp(
                int(row[0]) / 1000.0,
                tz=UTC,
            )
            value = (
                None if row[1] is None else float(row[1]),
                int(row[2]),
            )
            if timestamp in by_time and by_time[timestamp] != value:
                raise ValueError("stage36_duplicate_boundary_sample_mismatch")
            by_time[timestamp] = value
    result = tuple(
        (timestamp, value[0], value[1])
        for timestamp, value in sorted(by_time.items())
    )
    if len(result) != EXPECTED_UNIQUE_SAMPLE_COUNT:
        raise ValueError("stage36_candidate_pool_unique_sample_count_invalid")
    return result


def _select_events(
    series: tuple[tuple[datetime, float | None, int], ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = _compile_candidates(series)
    selected: list[dict[str, Any]] = []
    separation = timedelta(days=MINIMUM_EVENT_SEPARATION_DAYS)
    for candidate in candidates:
        marker_time = stage29._parse_time(str(candidate["marker_time_utc"]))
        if any(
            abs(
                marker_time
                - stage29._parse_time(str(prior["marker_time_utc"]))
            )
            < separation
            for prior in selected
        ):
            continue
        selected.append(
            {
                **candidate,
                "event_id": (
                    f"tailwater_stage_change_{marker_time:%Y%m%dT%H%MZ}"
                ),
                "role": "blind_hydraulic_boundary_event",
                "selection_rank": len(selected) + 1,
                "selected_without_release_or_downstream_values": True,
                "source_and_target_operators_frozen_before_outcomes": True,
            }
        )
        if len(selected) == EVENT_COUNT:
            break
    if len(selected) != EVENT_COUNT:
        raise ValueError("stage36_four_hydraulic_boundary_events_unavailable")
    return candidates, selected


def _compile_candidates(
    series: tuple[tuple[datetime, float | None, int], ...],
) -> list[dict[str, Any]]:
    exclusions = _excluded_intervals()
    candidates = []
    for index in range(
        EVENT_BEFORE_INTERVALS,
        len(series) - EVENT_AFTER_INTERVALS,
    ):
        marker_time, current, _ = series[index]
        previous = series[index - 1][1]
        if current is None or previous is None:
            continue
        signed_change = current - previous
        if abs(signed_change) < perturbation.MINIMUM_ABSOLUTE_PRIMARY_CHANGE_M:
            continue
        if any(start <= marker_time <= end for start, end in exclusions):
            continue
        window = series[
            index - EVENT_BEFORE_INTERVALS :
            index + EVENT_AFTER_INTERVALS + 1
        ]
        expected_times = tuple(
            window[0][0] + timedelta(minutes=30 * offset)
            for offset in range(perturbation.INCLUSIVE_WINDOW_SAMPLE_COUNT)
        )
        if (
            len(window) != perturbation.INCLUSIVE_WINDOW_SAMPLE_COUNT
            or tuple(value[0] for value in window) != expected_times
            or any(value[1] is None for value in window)
            or {value[2] for value in window} != {0}
        ):
            continue
        report = perturbation.compile_observed_hydraulic_boundary_perturbation(
            tuple(float(value[1]) for value in window if value[1] is not None)
        )
        if not report.blind_target_test_admissible:
            continue
        candidates.append(
            {
                "marker_time_utc": stage29._iso(marker_time),
                "marker_time_support_utc": [
                    stage29._iso(series[index - 1][0]),
                    stage29._iso(marker_time),
                ],
                "start_utc": stage29._iso(window[0][0]),
                "end_utc": stage29._iso(window[-1][0]),
                "inclusive_elevation_sample_count": len(window),
                "quality_codes": [0],
                "source_only_perturbation": report.as_dict(),
            }
        )
    candidates.sort(key=_candidate_rank)
    return candidates


def _candidate_rank(value: dict[str, Any]) -> tuple[object, ...]:
    report = value["source_only_perturbation"]
    return (
        -float(report["absolute_primary_change_m"]),
        -int(report["excursion_support_intervals"]),
        -float(report["normalized_excursion_intervals"]),
        str(value["marker_time_utc"]),
    )


def _excluded_intervals() -> tuple[tuple[datetime, datetime], ...]:
    prior_radius = timedelta(days=PRIOR_OUTCOME_EXCLUSION_DAYS)
    development_radius = timedelta(days=DEVELOPMENT_EXCLUSION_DAYS)
    development_marker = stage29._parse_time("2022-12-23T19:00:00Z")
    intervals = [
        (
            stage29._parse_time(value) - prior_radius,
            stage29._parse_time(value) + prior_radius,
        )
        for value in freeze.PRIOR_OUTCOME_EVENT_TIMES_UTC
    ]
    intervals.extend(
        (
            stage29._parse_time(start) - prior_radius,
            stage29._parse_time(end) + prior_radius,
        )
        for start, end in freeze.PRIOR_OUTCOME_WINDOWS_UTC
    )
    intervals.append(
        (
            development_marker - development_radius,
            development_marker + development_radius,
        )
    )
    return tuple(intervals)


def _frozen_protocol_artifact() -> dict[str, Any]:
    artifact = stage29._artifact(PROTOCOL_PATH)
    if artifact["sha256"] != FROZEN_PROTOCOL_SHA256:
        raise ValueError("stage36_frozen_protocol_drift")
    protocol = stage29._read_json(PROTOCOL_PATH)
    if (
        protocol.get("schema") != freeze.SCHEMA
        or protocol.get("data_boundary", {}).get(
            "new_candidate_pool_values_acquired"
        )
        is not False
        or protocol.get("data_boundary", {}).get(
            "new_downstream_outcome_values_acquired"
        )
        is not False
    ):
        raise ValueError("stage36_frozen_protocol_invalid")
    return artifact


def _load_attempt_audit(
    path: Path,
    sources: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    source_ids = tuple(str(value["source_id"]) for value in sources)
    if not path.is_file():
        return {
            source_id: {
                "attempts_before_resume": 0,
                "persisted_response_sha256": None,
            }
            for source_id in source_ids
        }
    value = stage29._read_json(path)
    records = value.get("logical_requests") or []
    by_id = {str(record.get("source_id")): record for record in records}
    if (
        value.get("schema") != ATTEMPT_AUDIT_SCHEMA
        or value.get("maximum_attempts_per_logical_request") != 3
        or value.get("workspace_or_private_data_sent") is not False
        or value.get("downstream_or_release_values_requested") is not False
        or tuple(by_id) != source_ids
        or any(
            not isinstance(record.get("attempts_before_resume"), int)
            or record["attempts_before_resume"] not in range(4)
            or (
                record["attempts_before_resume"] == 0
                and record.get("persisted_response_sha256") is not None
            )
            or (
                record["attempts_before_resume"] > 0
                and (
                    not isinstance(record.get("persisted_response_sha256"), str)
                    or len(record["persisted_response_sha256"]) != 64
                )
            )
            for record in records
        )
    ):
        raise ValueError("stage36_interrupted_attempt_audit_invalid")
    return by_id


def _validate_selection_manifest_shape(value: dict[str, Any]) -> None:
    events = value.get("selected_events") or []
    after = value.get("claim_boundary_after_source_selection") or {}
    if (
        value.get("schema") != SCHEMA
        or value.get("status")
        != "hydraulic_boundary_events_frozen_before_outcomes"
        or value.get("selected_event_count") != EVENT_COUNT
        or len(events) != EVENT_COUNT
        or value.get("frozen_protocol_artifact", {}).get("sha256")
        != FROZEN_PROTOCOL_SHA256
        or any(
            event.get("role") != "blind_hydraulic_boundary_event"
            or event.get("selected_without_release_or_downstream_values")
            is not True
            or event.get("source_and_target_operators_frozen_before_outcomes")
            is not True
            or event.get("source_only_perturbation", {}).get(
                "blind_target_test_admissible"
            )
            is not True
            for event in events
        )
        or after.get("operator_protocol_and_events_frozen") is not True
        or after.get("events_selected_from_tailwater_elevation_only") is not True
        or after.get("release_values_acquired") is not False
        or after.get("downstream_values_acquired") is not False
    ):
        raise ValueError("stage36_event_selection_manifest_invalid")


def _load_exact_plan(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("stage36_plan_must_be_frozen_before_values")
    value = stage29._read_json(path)
    if value != expected:
        raise ValueError("stage36_frozen_plan_mismatch")
    return value


def _validate_url(url: str, *, allowed_host: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != allowed_host
        or allowed_host not in {CWMS_HOST, USGS_HOST}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("stage36_url_outside_allowlist")


def _fetch(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
    allowed_host: str,
    accept: str,
) -> tuple[bytes, dict[str, Any]]:
    _validate_url(url, allowed_host=allowed_host)
    failures = []
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                _validate_url(response.geturl(), allowed_host=allowed_host)
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("stage36_object_size_limit_exceeded")
                return body, {
                    "url": url,
                    "transport": "configured_proxy_or_direct_urllib",
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "failed_attempts": failures,
                    "tls_hostname_verification_retained": True,
                    "retrieved_at": datetime.now(UTC).isoformat(),
                }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            error = exc
            failures.append({"attempt": attempt, "error": str(exc)})
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                break
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"stage36_request_failed:{error}:{failures}")


if __name__ == "__main__":
    raise SystemExit(main())
