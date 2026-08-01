#!/usr/bin/env python3
"""Audit TVA Lake Info as a native Center Hill dispatch source."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = Path(__file__).resolve()
SCHEMA = "gwm.geospatial_kernel.tva_native_dispatch_candidate.v1"
DEFAULT_CONVERSION_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_center_hill_dispatch_conversion_audit_20260801.json"
)
EXPECTED_PACKAGE = "com.tva.lakeinfo"
EXPECTED_VERSION = "5.2.0"
EXPECTED_XAPK_SHA256 = (
    "2c5daf63a17a980929d74ec3823fd0266701b6ad0e4f00d1fb793154d9000581"
)
EXPECTED_SOURCE_MAP_SHA256 = (
    "bb2cbcc824e892a3ef34817131578ff15e1a8c5f7859d54a5660dbfff6ac0948"
)
EXPECTED_LAKE_ID = "CEHT1"
EXPECTED_LAKE_NAME = "Center Hill"
EXPECTED_BASE_URL = "https://apigw-public.tva.gov/river"
EXPECTED_ENDPOINT = f"{EXPECTED_BASE_URL}/generation-releases/{EXPECTED_LAKE_ID}"
LOCAL_TIME_ZONE = ZoneInfo("America/Chicago")
REQUIRED_LOOKBACK_HOURS = 7
REQUIRED_FORECAST_HOURS = 12
SOURCE_EXPECTATIONS = {
    "./src/app/app-config.ts": (
        "public static readonly environmentName: string = 'prd';",
        (
            "public static readonly baseUrl: string = "
            "'https://apigw-public.tva.gov/river';"
        ),
    ),
    "./src/app/providers/generation-release.service.ts": (
        (
            "const url = AppConfig.baseUrl + '/generation-releases' + "
            "'/' + lakeId;"
        ),
        "record.date = fews[i].Day;",
        "record.timePeriod = fews[i].Time;",
        "record.generators = fews[i].Generators;",
    ),
    "./src/app/models/generation-release.ts": (
        "date: string;",
        "timePeriod: string;",
        "generators: string;",
    ),
}
TIME_PERIOD_PATTERN = re.compile(
    r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AP]M)\s*-\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*([AP]M)"
    r"(?:\s+(?:CT|CST|CDT))?\s*$",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-contract-evidence", type=Path, required=True)
    parser.add_argument("--lake-config", type=Path, required=True)
    parser.add_argument("--response-headers", type=Path, required=True)
    parser.add_argument("--response-body", type=Path, required=True)
    parser.add_argument(
        "--conversion-report",
        type=Path,
        default=DEFAULT_CONVERSION_REPORT,
    )
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--issue-time", required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def audit_native_dispatch_candidate(
    *,
    app_contract_evidence_path: Path,
    lake_config_path: Path,
    response_headers_path: Path,
    response_body_path: Path,
    conversion_report_path: Path = DEFAULT_CONVERSION_REPORT,
    observed_at: datetime,
    issue_time: datetime,
) -> dict[str, Any]:
    """Compile an outcome-free, fail-closed dispatch-source decision."""

    if not _aware(observed_at) or not _aware(issue_time):
        raise ValueError("tva_native_dispatch_time_invalid")
    observed_at = observed_at.astimezone(UTC)
    issue_time = issue_time.astimezone(UTC)
    if (
        issue_time < observed_at
        or issue_time.minute != 0
        or issue_time.second != 0
        or issue_time.microsecond != 0
    ):
        raise ValueError("tva_native_dispatch_issue_time_invalid")

    contract_body, contract_evidence = _load_json(app_contract_evidence_path)
    lake_config_body, lake_config = _load_json(lake_config_path)
    headers_body = response_headers_path.read_bytes()
    response_body = response_body_path.read_bytes()
    conversion_body, conversion = _load_json(conversion_report_path)

    mobile_contract = _mobile_contract_status(contract_evidence, lake_config)
    acquisition = _response_status(
        headers_body,
        response_body,
        observed_at=observed_at,
    )
    schedule = _schedule_status(
        response_body,
        http_status=acquisition["http_status"],
        issue_time=issue_time,
    )
    physical_boundary = _conversion_boundary_status(
        conversion,
        issue_time=issue_time,
    )
    readiness = {
        "official_app_contract_verified": mobile_contract["contract_verified"],
        "center_hill_identity_verified": mobile_contract[
            "center_hill_identity_verified"
        ],
        "api_response_200": acquisition["http_status"] == 200,
        "native_dispatch_payload_verified": schedule["payload_verified"],
        "native_dispatch_required_axis_ready": schedule[
            "required_axis_explicitly_covered"
        ],
        "native_dispatch_externally_timestamped": False,
        "generator_count_to_release_m3s_mapping_frozen": False,
    }
    readiness["native_dispatch_action_ready"] = all(
        readiness[key]
        for key in (
            "official_app_contract_verified",
            "center_hill_identity_verified",
            "api_response_200",
            "native_dispatch_payload_verified",
            "native_dispatch_required_axis_ready",
            "native_dispatch_externally_timestamped",
        )
    )
    readiness["generator_count_to_release_m3s_mapping_frozen"] = (
        physical_boundary["generator_count_to_release_m3s_mapping_frozen"]
    )
    readiness["physical_release_boundary_ready"] = physical_boundary[
        "conversion_ready"
    ]
    if acquisition["http_status"] != 200:
        status = "blocked_native_dispatch_api_access"
    elif not schedule["payload_verified"]:
        status = "blocked_native_dispatch_payload_invalid"
    elif not schedule["required_axis_explicitly_covered"]:
        status = "blocked_native_dispatch_axis_incomplete"
    else:
        status = "native_dispatch_candidate_verified_conversion_unresolved"

    return {
        "schema": SCHEMA,
        "status": status,
        "observed_at_utc": _iso(observed_at),
        "intended_issue_time_utc": _iso(issue_time),
        "scope": {
            "system_id": "center_hill",
            "lake_id": EXPECTED_LAKE_ID,
            "endpoint": EXPECTED_ENDPOINT,
            "required_support": {
                "lookback_hours": REQUIRED_LOOKBACK_HOURS,
                "forecast_hours": REQUIRED_FORECAST_HOURS,
                "hour_count": REQUIRED_LOOKBACK_HOURS
                + REQUIRED_FORECAST_HOURS,
            },
            "network_requests_performed_by_auditor": False,
        },
        "source_artifacts": {
            "official_app_contract_evidence": _artifact(
                app_contract_evidence_path,
                contract_body,
            ),
            "official_app_lake_configuration": _artifact(
                lake_config_path,
                lake_config_body,
            ),
            "api_response_headers": _artifact(
                response_headers_path,
                headers_body,
            ),
            "api_response_body": _artifact(
                response_body_path,
                response_body,
            ),
            "dispatch_conversion_audit": _artifact(
                conversion_report_path,
                conversion_body,
            ),
        },
        "implementation_artifacts": {
            "candidate_auditor": _artifact(
                AUDITOR_PATH,
                AUDITOR_PATH.read_bytes(),
            ),
        },
        "official_mobile_app_contract": mobile_contract,
        "api_acquisition": acquisition,
        "native_dispatch_action": schedule,
        "physical_release_boundary": physical_boundary,
        "readiness_gates": readiness,
        "claim_boundary": {
            "official_app_endpoint_contract_verified": True,
            "live_native_dispatch_payload_verified": schedule[
                "payload_verified"
            ],
            "native_dispatch_action_admitted": readiness[
                "native_dispatch_action_ready"
            ],
            "physical_release_boundary_admitted": False,
            "wwm_issue_compiled": False,
            "future_outcome_loaded": False,
            "geospatial_kernel_validated": False,
        },
    }


def _mobile_contract_status(
    contract_evidence: object,
    lake_config: object,
) -> dict[str, object]:
    if not isinstance(contract_evidence, Mapping):
        raise ValueError("tva_native_dispatch_contract_evidence_invalid")
    application = contract_evidence.get("application")
    source_map = contract_evidence.get("source_map")
    excerpts = contract_evidence.get("sanitized_source_excerpts")
    sanitization = contract_evidence.get("sanitization")
    if (
        contract_evidence.get("schema")
        != "gwm.geospatial_kernel.tva_lake_info_contract_evidence.v1"
        or not isinstance(application, Mapping)
        or application.get("package") != EXPECTED_PACKAGE
        or application.get("version") != EXPECTED_VERSION
        or application.get("xapk_sha256") != EXPECTED_XAPK_SHA256
        or not isinstance(source_map, Mapping)
        or source_map.get("asset_path") != "assets/public/main.js.map"
        or source_map.get("sha256") != EXPECTED_SOURCE_MAP_SHA256
        or source_map.get("full_artifact_committed") is not False
        or not isinstance(excerpts, Mapping)
        or not isinstance(sanitization, Mapping)
        or sanitization.get(
            "only_required_endpoint_and_field_mapping_excerpts_retained"
        )
        is not True
        or sanitization.get("embedded_credentials_retained") is not False
        or sanitization.get("parent_source_map_hash_retained") is not True
    ):
        raise ValueError("tva_native_dispatch_contract_evidence_invalid")
    verified_sources: dict[str, dict[str, object]] = {}
    for name, snippets in SOURCE_EXPECTATIONS.items():
        retained = excerpts.get(name)
        if not isinstance(retained, list) or retained != list(snippets):
            raise ValueError("tva_native_dispatch_source_contract_invalid")
        content = "\n".join(retained)
        verified_sources[name] = {
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "required_snippet_count": len(snippets),
            "all_required_snippets_verified": True,
        }
    if not isinstance(lake_config, list):
        raise ValueError("tva_native_dispatch_lake_config_invalid")
    matches = [
        item
        for item in lake_config
        if isinstance(item, Mapping) and item.get("lakeId") == EXPECTED_LAKE_ID
    ]
    if len(matches) != 1:
        raise ValueError("tva_native_dispatch_center_hill_identity_invalid")
    center_hill = matches[0]
    identity_verified = (
        center_hill.get("name") == EXPECTED_LAKE_NAME
        and center_hill.get("infoImage") == "USACE"
        and center_hill.get("gpData") is True
    )
    if not identity_verified:
        raise ValueError("tva_native_dispatch_center_hill_identity_invalid")
    return {
        "package": EXPECTED_PACKAGE,
        "version": EXPECTED_VERSION,
        "environment": "prd",
        "base_url": EXPECTED_BASE_URL,
        "generation_release_endpoint": EXPECTED_ENDPOINT,
        "xapk_sha256": EXPECTED_XAPK_SHA256,
        "source_map_sha256": EXPECTED_SOURCE_MAP_SHA256,
        "full_source_map_excluded_for_credential_safety": True,
        "response_field_mapping": {
            "Day": "date",
            "Time": "time_period",
            "Generators": "generator_count",
        },
        "verified_source_files": verified_sources,
        "center_hill_identity": {
            "lake_id": EXPECTED_LAKE_ID,
            "name": EXPECTED_LAKE_NAME,
            "source_organization_marker": "USACE",
            "generation_and_release_data_enabled": True,
        },
        "center_hill_identity_verified": True,
        "contract_verified": True,
    }


def _conversion_boundary_status(
    payload: object,
    *,
    issue_time: datetime,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("tva_native_dispatch_conversion_report_invalid")
    scope = payload.get("scope")
    gates = payload.get("readiness_gates")
    identifiability = payload.get("identifiability")
    claims = payload.get("claim_boundary")
    if (
        payload.get("schema")
        != "gwm.geospatial_kernel.center_hill_dispatch_conversion_audit.v1"
        or _parse_time(payload.get("audited_at_utc")) != issue_time
        or not isinstance(scope, Mapping)
        or scope.get("system_id") != "center_hill"
        or scope.get("native_dispatch_unit") != "generator_count"
        or scope.get("required_physical_boundary_unit") != "m3/s"
        or not isinstance(gates, Mapping)
        or not isinstance(identifiability, Mapping)
        or not isinstance(claims, Mapping)
        or claims.get("historical_head_and_component_diagnostic_completed")
        is not True
        or claims.get("future_outcome_loaded") is not False
        or claims.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("tva_native_dispatch_conversion_report_invalid")
    conversion_ready = payload.get("physical_release_boundary_ready") is True
    mapping_frozen = (
        gates.get("generator_count_to_total_release_m3s_mapping_frozen") is True
    )
    if conversion_ready != mapping_frozen:
        raise ValueError("tva_native_dispatch_conversion_report_invalid")
    return {
        "required_output_unit": "m3/s",
        "native_action_unit": "generator_count",
        "historical_head_and_component_diagnostic_completed": True,
        "independent_generator_count_labels_available": gates.get(
            "independent_generator_count_labels_paired_with_flow"
        ),
        "generator_loading_or_megawatt_dispatch_available": gates.get(
            "generator_loading_or_megawatt_dispatch_available"
        ),
        "prospective_pool_and_tailwater_boundary_available": gates.get(
            "prospective_pool_and_tailwater_boundary_available"
        ),
        "non_turbine_release_components_available_prospectively": gates.get(
            "prospective_non_turbine_release_components_available"
        ),
        "generator_count_to_release_m3s_mapping_frozen": mapping_frozen,
        "conversion_ready": conversion_ready,
        "blockers": identifiability.get("rejection_reasons"),
    }


def _response_status(
    headers_body: bytes,
    response_body: bytes,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    try:
        text = headers_body.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise ValueError("tva_native_dispatch_headers_invalid") from exc
    lines = [line.strip() for line in text.splitlines()]
    status_indices = [
        index for index, line in enumerate(lines) if line.startswith("HTTP/")
    ]
    if not status_indices:
        raise ValueError("tva_native_dispatch_headers_invalid")
    first = status_indices[-1]
    status_match = re.match(r"^HTTP/\S+\s+(\d{3})(?:\s|$)", lines[first])
    if status_match is None:
        raise ValueError("tva_native_dispatch_headers_invalid")
    headers: dict[str, str] = {}
    for line in lines[first + 1 :]:
        if line.startswith("HTTP/"):
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.lower()] = value.strip()
    try:
        response_date = parsedate_to_datetime(headers["date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("tva_native_dispatch_headers_invalid") from exc
    if not _aware(response_date) or response_date.astimezone(UTC) > observed_at:
        raise ValueError("tva_native_dispatch_response_time_invalid")
    status = int(status_match.group(1))
    body_text = response_body.decode("utf-8", errors="replace").strip()
    cloudflare_match = re.fullmatch(r"error code:\s*(\d+)", body_text)
    return {
        "method": "GET",
        "url": EXPECTED_ENDPOINT,
        "http_status": status,
        "content_type": headers.get("content-type"),
        "server": headers.get("server"),
        "response_date_utc": _iso(response_date),
        "response_precedes_intended_issue": True,
        "response_size_bytes": len(response_body),
        "access_succeeded": status == 200,
        "cloudflare_error_code": (
            cloudflare_match.group(1) if cloudflare_match else None
        ),
        "geographic_access_policy_denial_observed": bool(
            status == 403
            and cloudflare_match
            and cloudflare_match.group(1) == "1009"
        ),
        "tls_hostname_verification_retained": True,
    }


def _schedule_status(
    body: bytes,
    *,
    http_status: object,
    issue_time: datetime,
) -> dict[str, object]:
    empty = {
        "lake_id": EXPECTED_LAKE_ID,
        "native_unit": "generator_count",
        "time_zone": "America/Chicago",
        "payload_verified": False,
        "row_count": 0,
        "interval_count": 0,
        "earliest_interval_start_utc": None,
        "latest_interval_end_utc": None,
        "explicit_zero_generator_interval_count": 0,
        "required_axis_hour_count": REQUIRED_LOOKBACK_HOURS
        + REQUIRED_FORECAST_HOURS,
        "explicitly_covered_required_hour_count": 0,
        "missing_required_hour_starts_utc": [],
        "overlapping_required_hour_starts_utc": [],
        "required_axis_explicitly_covered": False,
        "omitted_periods_may_be_treated_as_zero": False,
        "server_schedule_publication_time_available": False,
    }
    if http_status != 200:
        return empty
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("tva_native_dispatch_payload_invalid") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("tva_native_dispatch_payload_invalid")

    intervals = []
    for row in payload:
        if not isinstance(row, Mapping):
            raise ValueError("tva_native_dispatch_payload_invalid")
        day = _parse_local_day(row.get("Day"))
        start_local, end_local = _parse_local_interval(day, row.get("Time"))
        generators = _parse_generator_count(row.get("Generators"))
        intervals.append((start_local.astimezone(UTC), end_local.astimezone(UTC), generators))
    intervals.sort(key=lambda value: (value[0], value[1], value[2]))
    required_start = issue_time - timedelta(hours=REQUIRED_LOOKBACK_HOURS)
    required_end = issue_time + timedelta(hours=REQUIRED_FORECAST_HOURS)
    missing = []
    overlapping = []
    covered = 0
    cursor = required_start
    while cursor < required_end:
        bucket_end = cursor + timedelta(hours=1)
        matches = [
            interval
            for interval in intervals
            if interval[0] <= cursor and interval[1] >= bucket_end
        ]
        if len(matches) == 1:
            covered += 1
        elif not matches:
            missing.append(_iso(cursor))
        else:
            overlapping.append(_iso(cursor))
        cursor = bucket_end
    return {
        **empty,
        "payload_verified": True,
        "row_count": len(payload),
        "interval_count": len(intervals),
        "earliest_interval_start_utc": _iso(intervals[0][0]),
        "latest_interval_end_utc": _iso(max(row[1] for row in intervals)),
        "explicit_zero_generator_interval_count": sum(
            row[2] == 0 for row in intervals
        ),
        "explicitly_covered_required_hour_count": covered,
        "missing_required_hour_starts_utc": missing,
        "overlapping_required_hour_starts_utc": overlapping,
        "required_axis_explicitly_covered": bool(
            covered == REQUIRED_LOOKBACK_HOURS + REQUIRED_FORECAST_HOURS
            and not missing
            and not overlapping
        ),
    }


def _parse_local_day(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("tva_native_dispatch_day_invalid")
    for date_format in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value.strip(), date_format)
            return parsed.replace(tzinfo=LOCAL_TIME_ZONE)
        except ValueError:
            continue
    raise ValueError("tva_native_dispatch_day_invalid")


def _parse_local_interval(
    day: datetime,
    value: object,
) -> tuple[datetime, datetime]:
    if not isinstance(value, str):
        raise ValueError("tva_native_dispatch_time_period_invalid")
    match = TIME_PERIOD_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("tva_native_dispatch_time_period_invalid")
    start_hour = _clock_hour(int(match.group(1)), match.group(3))
    end_hour = _clock_hour(int(match.group(4)), match.group(6))
    start_minute = int(match.group(2) or "0")
    end_minute = int(match.group(5) or "0")
    if start_minute >= 60 or end_minute >= 60:
        raise ValueError("tva_native_dispatch_time_period_invalid")
    start = day.replace(hour=start_hour, minute=start_minute)
    end = day.replace(hour=end_hour, minute=end_minute)
    if end <= start:
        end += timedelta(days=1)
    if end - start > timedelta(days=1):
        raise ValueError("tva_native_dispatch_time_period_invalid")
    return start, end


def _clock_hour(hour: int, meridiem: str) -> int:
    if not 1 <= hour <= 12:
        raise ValueError("tva_native_dispatch_time_period_invalid")
    return hour % 12 + (12 if meridiem.upper() == "PM" else 0)


def _parse_generator_count(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("tva_native_dispatch_generator_count_invalid")
    if isinstance(value, int):
        count = value
    elif isinstance(value, str):
        match = re.fullmatch(
            r"\s*(\d+)\s*(?:generators?)?\s*",
            value,
            re.IGNORECASE,
        )
        if match is None:
            raise ValueError("tva_native_dispatch_generator_count_invalid")
        count = int(match.group(1))
    else:
        raise ValueError("tva_native_dispatch_generator_count_invalid")
    if count < 0:
        raise ValueError("tva_native_dispatch_generator_count_invalid")
    return count


def _load_json(path: Path) -> tuple[bytes, Any]:
    body = path.read_bytes()
    try:
        return body, json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("tva_native_dispatch_json_invalid") from exc


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    return {
        "path": _display_path(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("tva_native_dispatch_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("tva_native_dispatch_time_invalid") from exc
    if not _aware(parsed):
        raise ValueError("tva_native_dispatch_time_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> None:
    args = parse_args()
    if args.report.exists():
        raise ValueError("tva_native_dispatch_report_overwrite_forbidden")
    report = audit_native_dispatch_candidate(
        app_contract_evidence_path=args.app_contract_evidence,
        lake_config_path=args.lake_config,
        response_headers_path=args.response_headers,
        response_body_path=args.response_body,
        conversion_report_path=args.conversion_report,
        observed_at=_parse_time(args.observed_at),
        issue_time=_parse_time(args.issue_time),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(
        "native_dispatch_action_ready="
        f"{report['readiness_gates']['native_dispatch_action_ready']}"
    )
    print(
        "physical_release_boundary_ready="
        f"{report['readiness_gates']['physical_release_boundary_ready']}"
    )


if __name__ == "__main__":
    main()
