#!/usr/bin/env python3
"""Audit whether current public inputs can form one sealed WWM v2 issue."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = Path(__file__).resolve()
SCHEMA = "gwm.geospatial_kernel.prospective_wwm_live_preflight.v3"
EXPECTED_CWMS_SERIES = (
    "CETT1-CENTER_HILL.Flow.Ave.~1Day.1Day.celrn-cwms-forecast"
)
EXPECTED_USGS_SITE = "03424730"
EXPECTED_USGS_PARAMETER = "00060"
EXPECTED_CENTER_HILL_NETWORK = (
    "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"
)
DEFAULT_ACTION_FREEZE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_action_innovation_candidate_freeze.json"
)
DEFAULT_CROSS_SYSTEM_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_action_innovation_cross_system_posthoc_report.json"
)
DEFAULT_TIMESTAMP_REGISTRY = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_timestamp_authority_registry.json"
)
DEFAULT_TVA_NATIVE_DISPATCH_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_tva_native_dispatch_candidate_20260801.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwms-action-response", type=Path, required=True)
    parser.add_argument("--usgs-observation-response", type=Path, required=True)
    parser.add_argument("--nwm-response-headers", type=Path, required=True)
    parser.add_argument("--nwm-url", required=True)
    parser.add_argument("--action-freeze", type=Path, default=DEFAULT_ACTION_FREEZE)
    parser.add_argument(
        "--cross-system-report",
        type=Path,
        default=DEFAULT_CROSS_SYSTEM_REPORT,
    )
    parser.add_argument(
        "--timestamp-registry",
        type=Path,
        default=DEFAULT_TIMESTAMP_REGISTRY,
    )
    parser.add_argument(
        "--tva-native-dispatch-report",
        type=Path,
        default=DEFAULT_TVA_NATIVE_DISPATCH_REPORT,
    )
    parser.add_argument("--audited-at", required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def compile_live_preflight(
    *,
    cwms_action_response_path: Path,
    usgs_observation_response_path: Path,
    nwm_response_headers_path: Path,
    nwm_url: str,
    action_freeze_path: Path = DEFAULT_ACTION_FREEZE,
    cross_system_report_path: Path = DEFAULT_CROSS_SYSTEM_REPORT,
    timestamp_registry_path: Path = DEFAULT_TIMESTAMP_REGISTRY,
    tva_native_dispatch_report_path: Path = DEFAULT_TVA_NATIVE_DISPATCH_REPORT,
    audited_at: datetime,
) -> dict[str, Any]:
    """Compile a fail-closed readiness decision without producing forecasts."""

    if not _aware(audited_at):
        raise ValueError("prospective_wwm_live_preflight_audited_at_invalid")
    audited_at = audited_at.astimezone(UTC)
    cwms_body, cwms = _load_json(cwms_action_response_path)
    usgs_body, usgs = _load_json(usgs_observation_response_path)
    nwm_headers = nwm_response_headers_path.read_bytes()
    freeze_body, freeze = _load_json(action_freeze_path)
    cross_body, cross = _load_json(cross_system_report_path)
    registry_body, registry = _load_json(timestamp_registry_path)
    tva_body, tva = _load_json(tva_native_dispatch_report_path)

    action = _cwms_action_status(cwms)
    observation = _usgs_observation_status(usgs, audited_at=audited_at)
    forcing = _nwm_status(nwm_headers, nwm_url=nwm_url, audited_at=audited_at)
    frozen_support = _frozen_support_status(freeze)
    cross_system = _cross_system_status(cross)
    timestamping = _timestamp_status(registry)
    native_dispatch = _tva_native_dispatch_status(tva, audited_at=audited_at)
    gates = {
        "center_hill_action_candidate_identity_verified": frozen_support[
            "center_hill_network_identity_verified"
        ],
        "current_observation_is_authoritative_unimputed_and_preissue": observation[
            "accepted_by_wwm_v3_issue_contract"
        ],
        "native_dispatch_action_covers_issue_minus_7h_through_plus_12h": (
            native_dispatch["native_dispatch_action_ready"]
        ),
        "generator_dispatch_to_physical_release_boundary_frozen": (
            native_dispatch["physical_release_boundary_ready"]
        ),
        "nwm_exact_forcing_transform_and_12h_axis_verified": forcing[
            "exact_forcing_contract_ready"
        ],
        "sealed_physical_forecast_receipt_available": False,
        "j_percy_priest_action_candidate_transfer_supported": cross_system[
            "zero_refit_transfer_supported"
        ],
        "trusted_external_timestamp_authority_ready": timestamping[
            "trusted_external_timestamp_verification_ready"
        ],
    }
    center_hill_gate_names = (
        "center_hill_action_candidate_identity_verified",
        "current_observation_is_authoritative_unimputed_and_preissue",
        "native_dispatch_action_covers_issue_minus_7h_through_plus_12h",
        "generator_dispatch_to_physical_release_boundary_frozen",
        "nwm_exact_forcing_transform_and_12h_axis_verified",
        "sealed_physical_forecast_receipt_available",
    )
    center_hill_ready = all(gates[key] for key in center_hill_gate_names)
    campaign_ready = all(gates.values())
    campaign_blocking_reasons = [
        key for key, passed in gates.items() if passed is not True
    ]
    center_hill_blocking_reasons = [
        key for key in center_hill_gate_names if gates[key] is not True
    ]
    return {
        "schema": SCHEMA,
        "status": (
            "ready_to_compile_live_wwm_v3_issue"
            if center_hill_ready
            else "blocked_live_wwm_v3_issue_inputs_not_ready"
        ),
        "audited_at_utc": _iso(audited_at),
        "scope": {
            "candidate_issue_schema": (
                "gwm.geospatial_kernel.prospective_wwm_candidate_issue.v3"
            ),
            "systems_required_for_promotion": [
                "center_hill",
                "j_percy_priest",
            ],
            "forecast_horizons_hours": [1, 3, 6, 12],
            "network_requests_performed_by_compiler": False,
            "action_contract_layers": [
                "native_dispatch_action_generator_count",
                "physical_release_boundary_m3s",
            ],
        },
        "source_artifacts": {
            "cwms_action_response": _artifact(
                cwms_action_response_path,
                cwms_body,
            ),
            "usgs_observation_response": _artifact(
                usgs_observation_response_path,
                usgs_body,
            ),
            "nwm_response_headers": _artifact(
                nwm_response_headers_path,
                nwm_headers,
            ),
            "action_candidate_freeze": _artifact(
                action_freeze_path,
                freeze_body,
            ),
            "cross_system_action_report": _artifact(
                cross_system_report_path,
                cross_body,
            ),
            "timestamp_authority_registry": _artifact(
                timestamp_registry_path,
                registry_body,
            ),
            "tva_native_dispatch_candidate_report": _artifact(
                tva_native_dispatch_report_path,
                tva_body,
            ),
        },
        "implementation_artifacts": {
            "live_preflight_auditor": _artifact(
                AUDITOR_PATH,
                AUDITOR_PATH.read_bytes(),
            ),
        },
        "live_inputs": {
            "center_hill_archival_release_source": action,
            "center_hill_native_dispatch_candidate": native_dispatch,
            "center_hill_outlet_observation": observation,
            "nwm_short_range_candidate": forcing,
        },
        "model_support": {
            "frozen_action_candidate": frozen_support,
            "cross_system_action_transfer": cross_system,
            "external_timestamping": timestamping,
        },
        "readiness_gates": gates,
        "center_hill_blocking_reasons": center_hill_blocking_reasons,
        "campaign_blocking_reasons": campaign_blocking_reasons,
        "center_hill_live_wwm_v3_issue_ready": center_hill_ready,
        "trusted_dual_system_campaign_ready": campaign_ready,
        "claim_boundary": {
            "live_public_input_readiness_audited": True,
            "wwm_v3_issue_compiled": False,
            "physical_prediction_executed": False,
            "future_outcome_loaded": False,
            "candidate_promoted": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _cwms_action_status(payload: Mapping[str, Any]) -> dict[str, object]:
    values = payload.get("values")
    if (
        payload.get("name") != EXPECTED_CWMS_SERIES
        or payload.get("office-id") != "LRN"
        or payload.get("units") != "cms"
        or not isinstance(values, list)
        or not isinstance(payload.get("total"), int)
        or payload["total"] != len(values)
    ):
        raise ValueError("prospective_wwm_live_preflight_cwms_response_invalid")
    return {
        "series_id": EXPECTED_CWMS_SERIES,
        "requested_begin_utc": payload.get("begin"),
        "requested_end_utc": payload.get("end"),
        "catalog_interval_semantics": "approximately_1_day",
        "returned_value_count": len(values),
        "hourly_resolution_available": False,
        "required_hourly_axis_available": False,
        "operational_action_vintage_verified": False,
    }


def _usgs_observation_status(
    payload: Mapping[str, Any],
    *,
    audited_at: datetime,
) -> dict[str, object]:
    value = payload.get("value")
    if not isinstance(value, Mapping):
        raise ValueError("prospective_wwm_live_preflight_usgs_response_invalid")
    series = value.get("timeSeries")
    if not isinstance(series, list) or len(series) != 1:
        raise ValueError("prospective_wwm_live_preflight_usgs_response_invalid")
    item = series[0]
    if not isinstance(item, Mapping):
        raise ValueError("prospective_wwm_live_preflight_usgs_response_invalid")
    source = item.get("sourceInfo")
    variable = item.get("variable")
    batches = item.get("values")
    if (
        not isinstance(source, Mapping)
        or not isinstance(variable, Mapping)
        or not isinstance(batches, list)
        or len(batches) != 1
    ):
        raise ValueError("prospective_wwm_live_preflight_usgs_response_invalid")
    site_codes = source.get("siteCode")
    variable_codes = variable.get("variableCode")
    rows = batches[0].get("value") if isinstance(batches[0], Mapping) else None
    if (
        not isinstance(site_codes, list)
        or not any(
            isinstance(code, Mapping)
            and code.get("value") == EXPECTED_USGS_SITE
            for code in site_codes
        )
        or not isinstance(variable_codes, list)
        or not any(
            isinstance(code, Mapping)
            and code.get("value") == EXPECTED_USGS_PARAMETER
            for code in variable_codes
        )
        or not isinstance(rows, list)
        or not rows
    ):
        raise ValueError("prospective_wwm_live_preflight_usgs_response_invalid")
    parsed_rows: list[tuple[datetime, float, tuple[str, ...]]] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("qualifiers"), list):
            raise ValueError("prospective_wwm_live_preflight_usgs_response_invalid")
        valid_at = _parse_time(row.get("dateTime"))
        try:
            discharge_cfs = float(row.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "prospective_wwm_live_preflight_usgs_response_invalid"
            ) from exc
        qualifiers = tuple(row["qualifiers"])
        if (
            not math.isfinite(discharge_cfs)
            or discharge_cfs < 0.0
            or any(not isinstance(code, str) for code in qualifiers)
        ):
            raise ValueError("prospective_wwm_live_preflight_usgs_response_invalid")
        parsed_rows.append((valid_at, discharge_cfs, qualifiers))
    latest_at, latest_cfs, qualifiers = max(parsed_rows, key=lambda row: row[0])
    approved = "A" in qualifiers
    operational_quality = approved or "P" in qualifiers
    preissue = latest_at <= audited_at
    return {
        "site_id": EXPECTED_USGS_SITE,
        "parameter_code": EXPECTED_USGS_PARAMETER,
        "source_authoritative": True,
        "latest_valid_at_utc": _iso(latest_at),
        "latest_discharge_cfs": latest_cfs,
        "latest_discharge_m3s": latest_cfs * 0.028316846592,
        "latest_qualifiers": list(qualifiers),
        "latest_value_is_approved": approved,
        "latest_value_is_provisional": "P" in qualifiers,
        "latest_value_not_after_audit": preissue,
        "accepted_by_wwm_v3_issue_contract": bool(
            operational_quality and preissue
        ),
    }


def _nwm_status(
    body: bytes,
    *,
    nwm_url: str,
    audited_at: datetime,
) -> dict[str, object]:
    parsed_url = urlparse(nwm_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "nomads.ncep.noaa.gov"
        or "short_range.channel_rt" not in parsed_url.path
        or not parsed_url.path.endswith(".conus.nc")
    ):
        raise ValueError("prospective_wwm_live_preflight_nwm_url_invalid")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("prospective_wwm_live_preflight_nwm_headers_invalid") from exc
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    status_ok = any(
        line.startswith("HTTP/")
        and len(line.split()) >= 2
        and line.split()[1] == "200"
        for line in lines
    )
    headers: dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers.setdefault(key.lower(), value.strip())
    try:
        content_length = int(headers["content-length"])
        last_modified = parsedate_to_datetime(headers["last-modified"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("prospective_wwm_live_preflight_nwm_headers_invalid") from exc
    if not _aware(last_modified) or last_modified > audited_at:
        raise ValueError("prospective_wwm_live_preflight_nwm_headers_invalid")
    return {
        "source_url": nwm_url,
        "http_200": status_ok,
        "content_length_bytes": content_length,
        "last_modified_utc": _iso(last_modified),
        "one_short_range_channel_file_available": bool(
            status_ok and content_length > 0
        ),
        "full_1h_3h_6h_12h_axis_acquired": False,
        "historical_q_lateral_to_operational_channel_transform_frozen": False,
        "exact_forcing_contract_ready": False,
    }


def _frozen_support_status(payload: Mapping[str, Any]) -> dict[str, object]:
    artifacts = payload.get("candidate_artifacts")
    if (
        payload.get("status") != "frozen_bounded_candidate_not_admitted"
        or not isinstance(artifacts, Mapping)
        or not isinstance(artifacts.get("parameters"), Mapping)
    ):
        raise ValueError("prospective_wwm_live_preflight_action_freeze_invalid")
    parameter_path, parameter_body = _read_verified(artifacts["parameters"])
    try:
        parameters = json.loads(parameter_body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "prospective_wwm_live_preflight_action_parameters_invalid"
        ) from exc
    support = parameters.get("support") if isinstance(parameters, Mapping) else None
    if not isinstance(support, Mapping):
        raise ValueError("prospective_wwm_live_preflight_action_parameters_invalid")
    network_id = support.get("network_id")
    return {
        "parameter_path": _display_path(parameter_path),
        "network_id": network_id,
        "lag_hours": support.get("lag_hours"),
        "center_hill_network_identity_verified": (
            network_id == EXPECTED_CENTER_HILL_NETWORK
        ),
        "multi_system_support_frozen": False,
        "candidate_admitted": False,
    }


def _cross_system_status(payload: Mapping[str, Any]) -> dict[str, object]:
    gate = payload.get("diagnostic_gate")
    claims = payload.get("claim_boundary")
    if (
        payload.get("status")
        != "zero_refit_cross_system_posthoc_failure_replicated"
        or not isinstance(gate, Mapping)
        or not isinstance(claims, Mapping)
        or claims.get("cross_system_failure_replicated") is not True
    ):
        raise ValueError("prospective_wwm_live_preflight_cross_report_invalid")
    supported = gate.get("cross_system_diagnostic_gate_passed") is True
    return {
        "target_system": "j_percy_priest",
        "zero_refit_transfer_supported": supported,
        "historical_failure_replicated": True,
    }


def _tva_native_dispatch_status(
    payload: Mapping[str, Any],
    *,
    audited_at: datetime,
) -> dict[str, object]:
    scope = payload.get("scope")
    mobile = payload.get("official_mobile_app_contract")
    acquisition = payload.get("api_acquisition")
    dispatch = payload.get("native_dispatch_action")
    boundary = payload.get("physical_release_boundary")
    gates = payload.get("readiness_gates")
    claims = payload.get("claim_boundary")
    if (
        payload.get("schema")
        != "gwm.geospatial_kernel.tva_native_dispatch_candidate.v1"
        or not isinstance(scope, Mapping)
        or scope.get("system_id") != "center_hill"
        or scope.get("lake_id") != "CEHT1"
        or scope.get("endpoint")
        != (
            "https://apigw-public.tva.gov/river/"
            "generation-releases/CEHT1"
        )
        or _parse_time(payload.get("intended_issue_time_utc")) != audited_at
        or _parse_time(payload.get("observed_at_utc")) > audited_at
        or not isinstance(mobile, Mapping)
        or mobile.get("contract_verified") is not True
        or mobile.get("center_hill_identity_verified") is not True
        or not isinstance(acquisition, Mapping)
        or not isinstance(dispatch, Mapping)
        or not isinstance(boundary, Mapping)
        or not isinstance(gates, Mapping)
        or not isinstance(claims, Mapping)
        or claims.get("official_app_endpoint_contract_verified") is not True
        or claims.get("future_outcome_loaded") is not False
        or claims.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError(
            "prospective_wwm_live_preflight_tva_dispatch_report_invalid"
        )
    action_ready = gates.get("native_dispatch_action_ready") is True
    boundary_ready = gates.get("physical_release_boundary_ready") is True
    if (
        action_ready
        != bool(
            acquisition.get("http_status") == 200
            and dispatch.get("payload_verified") is True
            and dispatch.get("required_axis_explicitly_covered") is True
            and gates.get("native_dispatch_externally_timestamped") is True
        )
        or boundary_ready
        != bool(
            action_ready
            and boundary.get("generator_count_to_release_m3s_mapping_frozen")
            is True
        )
    ):
        raise ValueError(
            "prospective_wwm_live_preflight_tva_dispatch_report_invalid"
        )
    return {
        "candidate_status": payload.get("status"),
        "official_app_package": mobile.get("package"),
        "official_app_version": mobile.get("version"),
        "endpoint": scope.get("endpoint"),
        "api_http_status": acquisition.get("http_status"),
        "geographic_access_policy_denial_observed": acquisition.get(
            "geographic_access_policy_denial_observed"
        ),
        "native_action_unit": dispatch.get("native_unit"),
        "native_dispatch_payload_verified": dispatch.get("payload_verified"),
        "required_axis_explicitly_covered": dispatch.get(
            "required_axis_explicitly_covered"
        ),
        "server_schedule_publication_time_available": dispatch.get(
            "server_schedule_publication_time_available"
        ),
        "native_dispatch_externally_timestamped": gates.get(
            "native_dispatch_externally_timestamped"
        ),
        "native_dispatch_action_ready": action_ready,
        "physical_release_output_unit": boundary.get("required_output_unit"),
        "generator_count_to_release_m3s_mapping_frozen": boundary.get(
            "generator_count_to_release_m3s_mapping_frozen"
        ),
        "physical_release_boundary_ready": boundary_ready,
        "physical_release_boundary_blockers": boundary.get("blockers"),
    }


def _timestamp_status(payload: Mapping[str, Any]) -> dict[str, object]:
    registered = payload.get("registered_authorities")
    readiness = payload.get("readiness")
    if not isinstance(registered, Mapping) or not isinstance(readiness, Mapping):
        raise ValueError("prospective_wwm_live_preflight_timestamp_registry_invalid")
    ready = readiness.get("trusted_external_timestamp_verification_ready") is True
    return {
        "registered_authority_count": len(registered),
        "trusted_external_timestamp_verification_ready": ready,
        "blocker": readiness.get("blocker"),
    }


def _read_verified(descriptor: object) -> tuple[Path, bytes]:
    if not isinstance(descriptor, Mapping) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise ValueError("prospective_wwm_live_preflight_artifact_invalid")
    raw_path = descriptor["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("prospective_wwm_live_preflight_artifact_invalid")
    path = Path(raw_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("prospective_wwm_live_preflight_artifact_invalid")
    return path, body


def _load_json(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body = path.read_bytes()
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("prospective_wwm_live_preflight_json_invalid") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("prospective_wwm_live_preflight_json_invalid")
    return body, payload


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


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("prospective_wwm_live_preflight_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("prospective_wwm_live_preflight_time_invalid") from exc
    if not _aware(parsed):
        raise ValueError("prospective_wwm_live_preflight_time_invalid")
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> None:
    args = parse_args()
    if args.report.exists():
        raise ValueError("prospective_wwm_live_preflight_overwrite_forbidden")
    report = compile_live_preflight(
        cwms_action_response_path=args.cwms_action_response,
        usgs_observation_response_path=args.usgs_observation_response,
        nwm_response_headers_path=args.nwm_response_headers,
        nwm_url=args.nwm_url,
        action_freeze_path=args.action_freeze,
        cross_system_report_path=args.cross_system_report,
        timestamp_registry_path=args.timestamp_registry,
        tva_native_dispatch_report_path=args.tva_native_dispatch_report,
        audited_at=_parse_time(args.audited_at),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(
        "center_hill_live_wwm_v3_issue_ready="
        f"{report['center_hill_live_wwm_v3_issue_ready']}"
    )
    print(
        "trusted_dual_system_campaign_ready="
        f"{report['trusted_dual_system_campaign_ready']}"
    )
    print(
        "center_hill_blocking_reason_count="
        f"{len(report['center_hill_blocking_reasons'])}"
    )


if __name__ == "__main__":
    main()
