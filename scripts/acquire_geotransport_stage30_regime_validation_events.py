"""Acquire release-stratified blind events for the Stage 30 lag-rule test.

The four phases deliberately keep downstream and tributary values unavailable
until the release-only event manifest and observation plan are hash frozen.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any, Iterable
import urllib.parse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import acquire_geotransport_stage29_blind_transfer_events as stage29


DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage30_center_hill_regime_validation_events"
)
SELECTION_SCHEMA = "gwm.geotransport.stage30_regime_event_selection.v1"
OBSERVATION_SCHEMA = "gwm.geotransport.stage30_observation_acquisition.v1"
CWMS_SERIES_ID = stage29.CWMS_SERIES_ID
CWMS_OFFICE = stage29.CWMS_OFFICE
CWMS_BEGIN = stage29.CWMS_BEGIN
CWMS_END = stage29.CWMS_END
CWMS_PAGE_SIZE = stage29.CWMS_PAGE_SIZE
DOWNSTREAM_SITE_ID = stage29.DOWNSTREAM_SITE_ID
TRIBUTARY_SITE_ID = stage29.TRIBUTARY_SITE_ID
PARAMETER_CODE = stage29.PARAMETER_CODE
LAG_CANDIDATES_HOURS = tuple(range(13))
EVENT_BEFORE_STEP_HOURS = 24
EVENT_AFTER_STEP_HOURS = 48
EVENT_DURATION_HOURS = 72
OBSERVATION_EXTENSION_HOURS = 12
MINIMUM_STEP_M3S = 50.0
LARGE_STEP_M3S = 150.0
MINIMUM_WINDOW_RANGE_M3S = 100.0
ANTECEDENT_HOURS = 24
HIGH_FLOW_THRESHOLD_M3S = 200.0
HIGH_FLOW_LAG_HOURS = 5
LOW_FLOW_LAG_HOURS = 6
MINIMUM_EVENT_SEPARATION_DAYS = 180
EXCLUSION_RADIUS_DAYS = 90
EXCLUDED_EVENT_TIMES = (
    "2022-12-23T19:00:00Z",
    "2025-09-10T14:00:00Z",
    "2025-03-03T16:00:00Z",
)
STAGE28_DEVELOPMENT_START = "2024-05-15T00:00:00Z"
STAGE28_DEVELOPMENT_END = "2024-05-18T00:00:00Z"
STRATUM_ORDER = (
    "high_increase",
    "high_decrease",
    "low_increase",
    "low_decrease",
)
MAXIMUM_SELECTION_REQUEST_COUNT = 1
MAXIMUM_OBSERVATION_REQUEST_COUNT = 8
MAXIMUM_SELECTION_DOWNLOAD_BYTES = 5_000_000
MAXIMUM_OBSERVATION_DOWNLOAD_BYTES = 16_000_000
USGS_LICENSE = stage29.USGS_LICENSE
USGS_LICENSE_URL = stage29.USGS_LICENSE_URL


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
    return {
        "schema": SELECTION_SCHEMA,
        "mode": "release_values" if values_mode else "selection_plan",
        "purpose": (
            "select four release-stratified blind validation events without "
            "loading Stonewall or Smith Fork event observations"
        ),
        "development_evidence": {
            "source_stage": 29,
            "event_antecedent_24_hour_means_m3s": [
                308.57103705083335,
                56.81303321416664,
                131.37129029041665,
            ],
            "event_best_lags_hours": [5, 6, 6],
            "derivation_uses_stage30_outcomes": False,
        },
        "frozen_regime_lag_rule": {
            "antecedent_support_hours": ANTECEDENT_HOURS,
            "antecedent_window": "24_real_hours_strictly_before_step",
            "high_flow_threshold_m3s": HIGH_FLOW_THRESHOLD_M3S,
            "high_flow_predicted_lag_hours": HIGH_FLOW_LAG_HOURS,
            "low_flow_predicted_lag_hours": LOW_FLOW_LAG_HOURS,
            "release_direction_used_for_stratification_only": True,
            "step_magnitude_used_for_stratification_only": True,
            "outcome_values_used": False,
        },
        "release_candidate_pool": {
            "series_id": CWMS_SERIES_ID,
            "office": CWMS_OFFICE,
            "begin": CWMS_BEGIN,
            "end": CWMS_END,
            "unit": "cms",
            "expected_inclusive_hour_count": 43_825,
        },
        "predeclared_event_selection": {
            "event_count": 4,
            "required_strata_in_selection_order": list(STRATUM_ORDER),
            "antecedent_flow_classes": {
                "high": "mean_greater_than_or_equal_to_200_m3s",
                "low": "mean_less_than_200_m3s",
            },
            "release_direction_classes": ["increase", "decrease"],
            "step_magnitude_classes": {
                "large": "absolute_step_greater_than_or_equal_to_150_m3s",
                "moderate": "absolute_step_50_to_less_than_150_m3s",
            },
            "window_hours_before_step": EVENT_BEFORE_STEP_HOURS,
            "window_hours_after_step": EVENT_AFTER_STEP_HOURS,
            "minimum_absolute_one_hour_step_m3s": MINIMUM_STEP_M3S,
            "minimum_window_range_m3s": MINIMUM_WINDOW_RANGE_M3S,
            "minimum_event_separation_days": MINIMUM_EVENT_SEPARATION_DAYS,
            "stage28_and_stage29_exclusion_radius_days": (
                EXCLUSION_RADIUS_DAYS
            ),
            "stage29_excluded_step_times_utc": list(EXCLUDED_EVENT_TIMES),
            "ranking_within_stratum": (
                "descending_absolute_step_then_descending_window_range_"
                "then_ascending_step_time"
            ),
            "selection_data": "cwms_release_values_only",
            "selected_role": "blind_regime_validation",
        },
        "predeclared_transfer_test": {
            "lag_candidates_hours": list(LAG_CANDIDATES_HOURS),
            "observation_extension_hours": OBSERVATION_EXTENSION_HOURS,
            "per_event_rule_support_threshold": {
                "best_lag_distance_from_predicted_hours": 1,
                "predicted_lag_minimum_pearson_r": 0.8,
                "best_minus_predicted_maximum_pearson_r": 0.05,
                "minimum_pair_count": 60,
            },
            "rule_admission_requirement": (
                "all_four_strata_support_frozen_predicted_lag"
            ),
            "retuning_after_observation_values": False,
        },
        "request_boundary": {
            "allowed_hosts": [stage29.CWMS_HOST],
            "maximum_request_count": MAXIMUM_SELECTION_REQUEST_COUNT,
            "maximum_total_download_bytes": (
                MAXIMUM_SELECTION_DOWNLOAD_BYTES
            ),
            "workspace_or_private_data_sent": False,
            "downstream_or_tributary_observation_values_requested": False,
            "cwms_fixed_ip_fallback_retains_tls_hostname_verification": True,
        },
        "sources": sources,
        "claim_boundary": {
            "events_selected": False,
            "downstream_values_acquired": False,
            "tributary_values_acquired": False,
            "regime_conditioned_lag_admitted": False,
            "physical_travel_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _selection_sources() -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
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
            "url": f"{stage29.CWMS_ROOT}/timeseries?{query}",
            "output_name": "raw/cwms_release_candidate_pool.json",
            "maximum_bytes": MAXIMUM_SELECTION_DOWNLOAD_BYTES,
            "role": "release_only_regime_validation_candidate_pool",
            "source_terms": stage29.CWMS_SOURCE_TERMS,
            "source_terms_url": stage29.CWMS_SOURCE_URL,
        }
    ]


def compile_observation_plan(
    selection_manifest_path: Path | None = None,
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
        raise ValueError("stage30_observation_request_boundary_exceeded")
    return {
        "schema": OBSERVATION_SCHEMA,
        "mode": "observation_plan",
        "purpose": (
            "acquire Stonewall outcomes and Smith Fork graph states only "
            "after release-stratified events are hash frozen"
        ),
        "frozen_event_selection_manifest": stage29._artifact(path),
        "selected_events": selection["selected_events"],
        "frozen_regime_lag_rule": compile_selection_plan()[
            "frozen_regime_lag_rule"
        ],
        "predeclared_transfer_test": compile_selection_plan()[
            "predeclared_transfer_test"
        ],
        "request_boundary": {
            "allowed_hosts": ["api.waterdata.usgs.gov"],
            "maximum_request_count": MAXIMUM_OBSERVATION_REQUEST_COUNT,
            "maximum_total_download_bytes": (
                MAXIMUM_OBSERVATION_DOWNLOAD_BYTES
            ),
            "workspace_or_private_data_sent": False,
            "event_selection_may_be_recomputed_from_observations": False,
            "regime_rule_may_be_retuned_from_observations": False,
        },
        "sources": sources,
        "claim_boundary": {
            "events_hash_frozen_before_observation_values": True,
            "downstream_values_acquired": False,
            "tributary_values_acquired": False,
            "regime_conditioned_lag_admitted": False,
            "physical_travel_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _observation_sources(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event["event_id"])
        start = stage29._parse_time(str(event["start_utc"]))
        end = stage29._parse_time(str(event["end_utc"])) + timedelta(
            hours=OBSERVATION_EXTENSION_HOURS
        )
        for site_id, site_role in (
            (DOWNSTREAM_SITE_ID, "downstream_outcome"),
            (TRIBUTARY_SITE_ID, "observed_graph_state"),
        ):
            query = urllib.parse.urlencode(
                {
                    "f": "json",
                    "limit": 10000,
                    "monitoring_location_id": site_id,
                    "parameter_code": PARAMETER_CODE,
                    "datetime": f"{stage29._iso(start)}/{stage29._iso(end)}",
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
                    "output_name": f"raw/usgs_{short_id}_{event_id}.json",
                    "maximum_bytes": 2_000_000,
                    "role": f"blind_regime_validation_{site_role}_values",
                    "license": USGS_LICENSE,
                    "license_url": USGS_LICENSE_URL,
                }
            )
    return sources


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage30_positive_request_limits_required")
    output = stage29._validate_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.phase == "selection-plan":
        path = output / "selection_plan.json"
        stage29._write_json(path, compile_selection_plan())
    elif args.phase == "release":
        path = _acquire_release_selection(args, output)
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


def _acquire_release_selection(
    args: argparse.Namespace, output: Path
) -> Path:
    frozen_path = output / "selection_plan.json"
    frozen_plan = _load_exact_plan(frozen_path, compile_selection_plan())
    values_plan = compile_selection_plan(values_mode=True)
    source = values_plan["sources"][0]
    body, retrieval = stage29._fetch(
        str(source["url"]),
        opener=stage29._opener(args.proxy),
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        maximum_bytes=int(source["maximum_bytes"]),
    )
    payload = stage29._json_object(body)
    stage29._validate_cwms_pool(payload)
    raw_path = output / str(source["output_name"])
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(body)
    artifact = stage29._artifact_record(
        raw_path, source=source, retrieval=retrieval
    )
    candidates, selected = _select_events(payload)
    candidate_path = output / "release_event_candidate_ledger.json"
    stage29._write_json(
        candidate_path,
        {
            "schema": "gwm.geotransport.stage30_release_candidates.v1",
            "selection_protocol": values_plan["predeclared_event_selection"],
            "eligible_candidate_count": len(candidates),
            "eligible_candidates": candidates,
            "selected_events": selected,
            "downstream_or_tributary_values_loaded": False,
        },
    )
    manifest = {
        **values_plan,
        "status": "regime_events_frozen_before_observations",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "frozen_selection_plan": stage29._artifact(frozen_path),
        "frozen_selection_plan_content": frozen_plan,
        "release_event_candidate_ledger": stage29._artifact(candidate_path),
        "eligible_candidate_count": len(candidates),
        "selected_events": selected,
        "selected_event_count": len(selected),
        "artifacts": [artifact],
        "artifact_count": 1,
        "actual_request_count": 1,
        "total_downloaded_bytes": len(body),
        "claim_boundary_after_release_selection": {
            "events_selected_from_release_only": True,
            "events_hash_frozen": True,
            "downstream_values_acquired": False,
            "tributary_values_acquired": False,
            "regime_rule_scored": False,
            "regime_conditioned_lag_admitted": False,
            "runtime_operator_admitted": False,
        },
    }
    path = output / "event_selection_manifest.json"
    stage29._write_json(path, manifest)
    print(f"eligible_candidates={len(candidates)}")
    print(f"selected_events={len(selected)}")
    return path


def _acquire_observations(
    args: argparse.Namespace, output: Path
) -> Path:
    selection_path = output / "event_selection_manifest.json"
    frozen_path = output / "observation_plan.json"
    expected_plan = compile_observation_plan(selection_path)
    frozen_plan = _load_exact_plan(frozen_path, expected_plan)
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    opener = stage29._opener(args.proxy)
    for source in frozen_plan["sources"]:
        body, retrieval = stage29._fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        payload = stage29._json_object(body)
        stage29._validate_observation_values(payload, source)
        total_bytes = stage29._checked_total(
            total_bytes,
            len(body),
            maximum=MAXIMUM_OBSERVATION_DOWNLOAD_BYTES,
        )
        raw_path = output / str(source["output_name"])
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
        artifacts.append(
            stage29._artifact_record(
                raw_path, source=source, retrieval=retrieval
            )
        )
    manifest = {
        **frozen_plan,
        "mode": "observation_values",
        "status": "regime_validation_observations_acquired",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "frozen_observation_plan": stage29._artifact(frozen_path),
        "frozen_observation_plan_content": frozen_plan,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "actual_request_count": len(artifacts),
        "total_downloaded_bytes": total_bytes,
        "claim_boundary_after_observations": {
            "events_hash_frozen_before_observation_values": True,
            "regime_rule_frozen_before_observation_values": True,
            "downstream_values_acquired": True,
            "tributary_values_acquired": True,
            "regime_rule_scored": False,
            "regime_conditioned_lag_admitted": False,
            "runtime_operator_admitted": False,
        },
    }
    path = output / "observation_acquisition_manifest.json"
    stage29._write_json(path, manifest)
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
    excluded_intervals = [
        (
            stage29._parse_time(value) - timedelta(days=EXCLUSION_RADIUS_DAYS),
            stage29._parse_time(value) + timedelta(days=EXCLUSION_RADIUS_DAYS),
        )
        for value in EXCLUDED_EVENT_TIMES
    ]
    excluded_intervals.append(
        (
            stage29._parse_time(STAGE28_DEVELOPMENT_START)
            - timedelta(days=EXCLUSION_RADIUS_DAYS),
            stage29._parse_time(STAGE28_DEVELOPMENT_END)
            + timedelta(days=EXCLUSION_RADIUS_DAYS),
        )
    )
    candidates: list[dict[str, Any]] = []
    for index in range(EVENT_BEFORE_STEP_HOURS, len(series) - EVENT_AFTER_STEP_HOURS):
        step_time, current, _ = series[index]
        signed_step = current - series[index - 1][1]
        absolute_step = abs(signed_step)
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
        if window_range < MINIMUM_WINDOW_RANGE_M3S or any(
            start <= step_time <= end for start, end in excluded_intervals
        ):
            continue
        antecedent = tuple(
            value[1] for value in series[index - ANTECEDENT_HOURS : index]
        )
        antecedent_mean = sum(antecedent) / len(antecedent)
        flow_class = (
            "high" if antecedent_mean >= HIGH_FLOW_THRESHOLD_M3S else "low"
        )
        direction = "increase" if signed_step > 0.0 else "decrease"
        magnitude = "large" if absolute_step >= LARGE_STEP_M3S else "moderate"
        candidates.append(
            {
                "step_time_utc": stage29._iso(step_time),
                "signed_step_m3s": signed_step,
                "absolute_step_m3s": absolute_step,
                "step_magnitude_class": magnitude,
                "release_direction": direction,
                "antecedent_support_hours": ANTECEDENT_HOURS,
                "antecedent_release_mean_m3s": antecedent_mean,
                "antecedent_flow_class": flow_class,
                "selection_stratum": f"{flow_class}_{direction}",
                "predicted_lag_hours": (
                    HIGH_FLOW_LAG_HOURS
                    if flow_class == "high"
                    else LOW_FLOW_LAG_HOURS
                ),
                "window_range_m3s": window_range,
                "start_utc": stage29._iso(window[0][0]),
                "end_utc": stage29._iso(window[-1][0]),
                "inclusive_release_value_count": len(window),
                "quality_codes": sorted({value[2] for value in window}),
            }
        )
    candidates.sort(
        key=lambda value: (
            STRATUM_ORDER.index(str(value["selection_stratum"])),
            -float(value["absolute_step_m3s"]),
            -float(value["window_range_m3s"]),
            str(value["step_time_utc"]),
        )
    )
    selected: list[dict[str, Any]] = []
    separation = timedelta(days=MINIMUM_EVENT_SEPARATION_DAYS)
    for stratum in STRATUM_ORDER:
        selected_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate["selection_stratum"] == stratum
                and all(
                    abs(
                        stage29._parse_time(str(candidate["step_time_utc"]))
                        - stage29._parse_time(str(value["step_time_utc"]))
                    )
                    >= separation
                    for value in selected
                )
            ),
            None,
        )
        if selected_candidate is None:
            raise ValueError(f"stage30_stratum_unavailable:{stratum}")
        step_time = stage29._parse_time(
            str(selected_candidate["step_time_utc"])
        )
        selected.append(
            {
                **selected_candidate,
                "event_id": f"release_step_{step_time:%Y%m%dT%H%MZ}",
                "role": "blind_regime_validation",
                "selection_rank": len(selected) + 1,
                "selected_without_observation_values": True,
                "rule_frozen_without_observation_values": True,
            }
        )
    return candidates, selected


def _validate_selection_manifest_shape(value: dict[str, Any]) -> None:
    events = value.get("selected_events") or []
    after = value.get("claim_boundary_after_release_selection") or {}
    if (
        value.get("schema") != SELECTION_SCHEMA
        or value.get("status") != "regime_events_frozen_before_observations"
        or value.get("selected_event_count") != 4
        or [event.get("selection_stratum") for event in events]
        != list(STRATUM_ORDER)
        or any(
            event.get("role") != "blind_regime_validation"
            or event.get("selected_without_observation_values") is not True
            or event.get("rule_frozen_without_observation_values") is not True
            for event in events
        )
        or after.get("events_selected_from_release_only") is not True
        or after.get("events_hash_frozen") is not True
        or after.get("downstream_values_acquired") is not False
        or after.get("tributary_values_acquired") is not False
    ):
        raise ValueError("stage30_event_selection_manifest_invalid")


def _load_exact_plan(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("stage30_plan_must_be_frozen_before_values")
    value = stage29._read_json(path)
    if value != expected:
        raise ValueError("stage30_frozen_plan_mismatch")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
