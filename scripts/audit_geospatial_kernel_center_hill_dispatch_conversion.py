#!/usr/bin/env python3
"""Audit whether Center Hill generator counts can become a flow boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from statistics import median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = Path(__file__).resolve()
SCHEMA = "gwm.geospatial_kernel.center_hill_dispatch_conversion_audit.v1"
DATA_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_center_hill_dispatch_conversion_20260801"
)
DEFAULT_POOL = DATA_ROOT / "raw/cwms_pool_elevation_2021_2025.json"
DEFAULT_POOL_HEADERS = DATA_ROOT / "raw/cwms_pool_elevation_headers.txt"
DEFAULT_TAIL = DATA_ROOT / "raw/cwms_tail_elevation_2021_2025.json"
DEFAULT_TAIL_HEADERS = DATA_ROOT / "raw/cwms_tail_elevation_headers.txt"
DEFAULT_STAGE39_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage39_center_hill_component_discharge_value_protocol/"
    "value_acquisition_manifest.json"
)
EXPECTED_BEGIN = "2021-01-01T00:00:00Z"
EXPECTED_END = "2026-01-01T00:00:00Z"
EXPECTED_GRID_COUNT = 43_825
POOL_SERIES = "CEHT1-CENTER_HILL.Elev-Pool.Inst.1Hour.0.man-rev"
TAIL_SERIES = "CETT1-CENTER_HILL.Elev-Tail.Inst.1Hour.0.man-rev"
COMPONENT_SERIES = {
    "orifice": "CETT1-CENTER_HILL.Flow-Orifice.Ave.1Hour.1Hour.man-rev",
    "sluice": "CETT1-CENTER_HILL.Flow-Sluice.Ave.1Hour.1Hour.man-rev",
    "spillway": "CETT1-CENTER_HILL.Flow-Spillway.Ave.1Hour.1Hour.man-rev",
    "turbine": "CETT1-CENTER_HILL.Flow-Turbine.Ave.1Hour.1Hour.man-rev",
}
FIXED_IP = "3.30.180.152"
CWMS_HOST = "cwms-data.usace.army.mil"
MINIMUM_STABLE_TURBINE_FLOW_M3S = 80.0
LATENT_COUNT_THRESHOLDS_M3S = (165.0, 275.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument(
        "--pool-headers",
        type=Path,
        default=DEFAULT_POOL_HEADERS,
    )
    parser.add_argument("--tail", type=Path, default=DEFAULT_TAIL)
    parser.add_argument(
        "--tail-headers",
        type=Path,
        default=DEFAULT_TAIL_HEADERS,
    )
    parser.add_argument(
        "--stage39-manifest",
        type=Path,
        default=DEFAULT_STAGE39_MANIFEST,
    )
    parser.add_argument("--audited-at", required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def audit_dispatch_conversion(
    *,
    pool_path: Path = DEFAULT_POOL,
    pool_headers_path: Path = DEFAULT_POOL_HEADERS,
    tail_path: Path = DEFAULT_TAIL,
    tail_headers_path: Path = DEFAULT_TAIL_HEADERS,
    stage39_manifest_path: Path = DEFAULT_STAGE39_MANIFEST,
    audited_at: datetime,
) -> dict[str, Any]:
    """Compile a fail-closed generator-count conversion decision."""

    if not _aware(audited_at):
        raise ValueError("dispatch_conversion_audited_at_invalid")
    audited_at = audited_at.astimezone(UTC)
    pool_body, pool_payload = _load_json(pool_path)
    tail_body, tail_payload = _load_json(tail_path)
    pool_headers_body = pool_headers_path.read_bytes()
    tail_headers_body = tail_headers_path.read_bytes()
    manifest_body, manifest = _load_json(stage39_manifest_path)
    if not isinstance(pool_payload, Mapping) or not isinstance(
        tail_payload,
        Mapping,
    ):
        raise ValueError("dispatch_conversion_elevation_payload_invalid")
    pool = _cwms_series(
        pool_payload,
        expected_name=POOL_SERIES,
        expected_unit="m",
    )
    tail = _cwms_series(
        tail_payload,
        expected_name=TAIL_SERIES,
        expected_unit="m",
    )
    pool_acquisition = _headers_status(
        pool_headers_body,
        audited_at=audited_at,
    )
    tail_acquisition = _headers_status(
        tail_headers_body,
        audited_at=audited_at,
    )
    components, component_artifacts = _component_series_from_manifest(manifest)
    aligned = _aligned_support(pool, tail, components)
    diagnostics = _latent_conversion_diagnostics(aligned)
    non_turbine = _non_turbine_diagnostics(aligned)

    gates = {
        "historical_hourly_pool_tail_and_components_aligned": (
            aligned["aligned_hour_count"] == EXPECTED_GRID_COUNT
        ),
        "independent_generator_count_labels_paired_with_flow": False,
        "generator_loading_or_megawatt_dispatch_available": False,
        "prospective_pool_and_tailwater_boundary_available": False,
        "prospective_non_turbine_release_components_available": False,
        "historical_quality_codes_scientifically_approved": False,
        "head_dependent_generator_to_turbine_flow_mapping_frozen": False,
        "generator_count_to_total_release_m3s_mapping_frozen": False,
    }
    conversion_ready = all(gates.values())
    return {
        "schema": SCHEMA,
        "status": (
            "dispatch_conversion_ready"
            if conversion_ready
            else "blocked_independent_labels_and_prospective_boundary_missing"
        ),
        "audited_at_utc": _iso(audited_at),
        "scope": {
            "system_id": "center_hill",
            "native_dispatch_unit": "generator_count",
            "required_physical_boundary_unit": "m3/s",
            "historical_support_begin_utc": EXPECTED_BEGIN,
            "historical_support_end_utc": EXPECTED_END,
            "future_outcome_or_skill_values_loaded": False,
            "network_requests_performed_by_auditor": False,
        },
        "source_artifacts": {
            "pool_elevation": _artifact(pool_path, pool_body),
            "pool_elevation_response_headers": _artifact(
                pool_headers_path,
                pool_headers_body,
            ),
            "tail_elevation": _artifact(tail_path, tail_body),
            "tail_elevation_response_headers": _artifact(
                tail_headers_path,
                tail_headers_body,
            ),
            "stage39_component_acquisition_manifest": _artifact(
                stage39_manifest_path,
                manifest_body,
            ),
            "component_series": component_artifacts,
        },
        "implementation_artifacts": {
            "conversion_auditor": _artifact(
                AUDITOR_PATH,
                AUDITOR_PATH.read_bytes(),
            ),
        },
        "elevation_acquisition": {
            "pool": {
                **pool_acquisition,
                "series_id": POOL_SERIES,
                "row_count": len(pool),
            },
            "tail": {
                **tail_acquisition,
                "series_id": TAIL_SERIES,
                "row_count": len(tail),
            },
            "transport": "curl_fixed_ipv4_fallback_with_tls_hostname_verification",
            "fixed_ip": FIXED_IP,
            "tls_hostname": CWMS_HOST,
        },
        "aligned_historical_support": aligned["summary"],
        "latent_generator_band_diagnostic": diagnostics,
        "non_turbine_release_diagnostic": non_turbine,
        "identifiability": {
            "flow_bands_are_independent_generator_labels": False,
            "flow_band_role": "posthoc_latent_diagnostic_only",
            "tailwater_is_contemporaneously_affected_by_release": True,
            "head_regression_is_forward_causal_boundary": False,
            "constant_flow_per_generator_supported": False,
            "generator_count_alone_identifies_total_release": False,
            "rejection_reasons": [
                "no_independently_observed_hourly_generator_count_labels",
                "no_generator_loading_or_megawatt_schedule",
                "contemporaneous_tailwater_is_not_a_preissue_exogenous_input",
                "no_prospective_non_turbine_release_schedule",
                "historical_man_rev_values_are_not_operational_vintages",
            ],
        },
        "readiness_gates": gates,
        "physical_release_boundary_ready": conversion_ready,
        "claim_boundary": {
            "historical_head_and_component_diagnostic_completed": True,
            "native_generator_count_labels_observed": False,
            "conversion_calibrated": False,
            "conversion_frozen": False,
            "runtime_operator_admitted": False,
            "prospective_wwm_issue_compiled": False,
            "future_outcome_loaded": False,
            "geospatial_kernel_validated": False,
        },
    }


def _cwms_series(
    payload: Mapping[str, Any],
    *,
    expected_name: str,
    expected_unit: str,
) -> dict[int, tuple[float | None, int]]:
    rows = payload.get("values")
    if (
        payload.get("name") != expected_name
        or payload.get("office-id") != "LRN"
        or payload.get("units") != expected_unit
        or payload.get("interval") != "PT1H"
        or payload.get("interval-offset") != 0
        or payload.get("begin") != EXPECTED_BEGIN
        or payload.get("end") != EXPECTED_END
        or payload.get("next-page") not in (None, "")
        or payload.get("total") != EXPECTED_GRID_COUNT
        or not isinstance(rows, list)
        or len(rows) != EXPECTED_GRID_COUNT
    ):
        raise ValueError("dispatch_conversion_cwms_series_invalid")
    result: dict[int, tuple[float | None, int]] = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[0], int)
            or isinstance(row[2], bool)
            or not isinstance(row[2], int)
            or (
                row[1] is not None
                and (
                    isinstance(row[1], bool)
                    or not isinstance(row[1], (int, float))
                    or not math.isfinite(float(row[1]))
                )
            )
        ):
            raise ValueError("dispatch_conversion_cwms_row_invalid")
        value = float(row[1]) if row[1] is not None else None
        if row[0] in result:
            raise ValueError("dispatch_conversion_cwms_time_duplicate")
        result[row[0]] = (value, row[2])
    if list(result) != sorted(result):
        raise ValueError("dispatch_conversion_cwms_time_axis_invalid")
    return result


def _component_series_from_manifest(
    manifest: object,
) -> tuple[
    dict[str, dict[int, tuple[float | None, int]]],
    dict[str, list[dict[str, object]]],
]:
    if not isinstance(manifest, Mapping):
        raise ValueError("dispatch_conversion_stage39_manifest_invalid")
    artifacts = manifest.get("artifacts")
    if (
        manifest.get("schema")
        != "gwm.geotransport.stage39_component_discharge_value_manifest.v1"
        or manifest.get("artifact_count") != 20
        or not isinstance(artifacts, list)
        or len(artifacts) != 20
    ):
        raise ValueError("dispatch_conversion_stage39_manifest_invalid")
    merged = {component: {} for component in COMPONENT_SERIES}
    verified: dict[str, list[dict[str, object]]] = {
        component: [] for component in COMPONENT_SERIES
    }
    for descriptor in artifacts:
        if not isinstance(descriptor, Mapping):
            raise ValueError("dispatch_conversion_stage39_artifact_invalid")
        component = descriptor.get("component")
        if component not in COMPONENT_SERIES:
            raise ValueError("dispatch_conversion_stage39_artifact_invalid")
        raw_path = descriptor.get("path")
        if not isinstance(raw_path, str):
            raise ValueError("dispatch_conversion_stage39_artifact_invalid")
        path = REPO_ROOT / raw_path
        body = path.read_bytes()
        if (
            descriptor.get("series_id") != COMPONENT_SERIES[component]
            or descriptor.get("http_status") != 200
            or descriptor.get("tls_hostname_verification_retained") is not True
            or descriptor.get("sha256") != hashlib.sha256(body).hexdigest()
            or descriptor.get("size_bytes") != len(body)
        ):
            raise ValueError("dispatch_conversion_stage39_artifact_invalid")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("dispatch_conversion_stage39_artifact_invalid") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("dispatch_conversion_stage39_artifact_invalid")
        yearly = _component_year(payload, expected_name=COMPONENT_SERIES[component])
        for timestamp, value in yearly.items():
            previous = merged[component].get(timestamp)
            if previous is not None and previous != value:
                raise ValueError("dispatch_conversion_component_overlap_conflict")
            merged[component][timestamp] = value
        verified[component].append(
            {
                "path": raw_path,
                "sha256": descriptor.get("sha256"),
                "size_bytes": descriptor.get("size_bytes"),
            }
        )
    if any(len(values) != EXPECTED_GRID_COUNT for values in merged.values()):
        raise ValueError("dispatch_conversion_component_axis_incomplete")
    return merged, verified


def _component_year(
    payload: Mapping[str, Any],
    *,
    expected_name: str,
) -> dict[int, tuple[float | None, int]]:
    rows = payload.get("values")
    if (
        payload.get("name") != expected_name
        or payload.get("office-id") != "LRN"
        or payload.get("units") != "cms"
        or payload.get("interval") != "PT1H"
        or payload.get("interval-offset") != 0
        or not isinstance(rows, list)
        or payload.get("total") != len(rows)
    ):
        raise ValueError("dispatch_conversion_component_payload_invalid")
    result = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[0], int)
            or not isinstance(row[2], int)
            or isinstance(row[2], bool)
            or (
                row[1] is not None
                and (
                    isinstance(row[1], bool)
                    or not isinstance(row[1], (int, float))
                    or not math.isfinite(float(row[1]))
                )
            )
        ):
            raise ValueError("dispatch_conversion_component_row_invalid")
        result[row[0]] = (
            float(row[1]) if row[1] is not None else None,
            row[2],
        )
    return result


def _aligned_support(
    pool: Mapping[int, tuple[float | None, int]],
    tail: Mapping[int, tuple[float | None, int]],
    components: Mapping[str, Mapping[int, tuple[float | None, int]]],
) -> dict[str, Any]:
    axes = [set(pool), set(tail), *(set(values) for values in components.values())]
    if any(axis != axes[0] for axis in axes[1:]):
        raise ValueError("dispatch_conversion_aligned_axis_invalid")
    rows = []
    missing_counts: Counter[str] = Counter()
    quality_codes: dict[str, Counter[int]] = {
        "pool": Counter(),
        "tail": Counter(),
        **{component: Counter() for component in COMPONENT_SERIES},
    }
    for timestamp in sorted(pool):
        raw_values = {
            "pool": pool[timestamp][0],
            "tail": tail[timestamp][0],
            **{
                component: components[component][timestamp][0]
                for component in COMPONENT_SERIES
            },
        }
        quality_codes["pool"][pool[timestamp][1]] += 1
        quality_codes["tail"][tail[timestamp][1]] += 1
        for component in COMPONENT_SERIES:
            quality_codes[component][components[component][timestamp][1]] += 1
        for name, value in raw_values.items():
            if value is None:
                missing_counts[name] += 1
        if any(value is None for value in raw_values.values()):
            continue
        values = {name: float(value) for name, value in raw_values.items()}
        head = values["pool"] - values["tail"]
        if not math.isfinite(head) or head <= 0.0:
            raise ValueError("dispatch_conversion_hydraulic_head_invalid")
        rows.append({"timestamp_ms": timestamp, "head_m": head, **values})
    return {
        "aligned_hour_count": len(pool),
        "rows": rows,
        "summary": {
            "aligned_hour_count": len(pool),
            "complete_six_series_hour_count": len(rows),
            "missing_value_counts": dict(sorted(missing_counts.items())),
            "hydraulic_head_m": _summary([row["head_m"] for row in rows]),
            "quality_code_counts": {
                name: {str(key): count for key, count in sorted(counter.items())}
                for name, counter in quality_codes.items()
            },
            "quality_codes_interpreted_as_scientific_approval": False,
            "all_series_are_posthoc_man_rev": True,
        },
    }


def _latent_conversion_diagnostics(aligned: Mapping[str, Any]) -> dict[str, Any]:
    rows = aligned["rows"]
    stable = []
    zero_count = 0
    partial_count = 0
    negative_count = 0
    for row in rows:
        flow = row["turbine"]
        if flow < 0.0:
            negative_count += 1
        if flow == 0.0:
            zero_count += 1
        elif flow < MINIMUM_STABLE_TURBINE_FLOW_M3S:
            partial_count += 1
        else:
            latent_count = (
                1
                if flow < LATENT_COUNT_THRESHOLDS_M3S[0]
                else 2
                if flow < LATENT_COUNT_THRESHOLDS_M3S[1]
                else 3
            )
            stable.append(
                {
                    "flow_m3s": flow,
                    "head_m": row["head_m"],
                    "latent_count": latent_count,
                    "per_latent_unit_flow_m3s": flow / latent_count,
                }
            )
    if not stable:
        raise ValueError("dispatch_conversion_no_stable_turbine_values")
    base = median(row["per_latent_unit_flow_m3s"] for row in stable)
    constant_errors = [
        row["flow_m3s"] - row["latent_count"] * base for row in stable
    ]
    x_values = [row["head_m"] for row in stable]
    y_values = [row["per_latent_unit_flow_m3s"] for row in stable]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    slope = (
        sum(
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in zip(x_values, y_values, strict=True)
        )
        / denominator
    )
    intercept = y_mean - slope * x_mean
    head_errors = [
        row["flow_m3s"]
        - row["latent_count"] * (intercept + slope * row["head_m"])
        for row in stable
    ]
    constant_rmse = _rmse(constant_errors)
    head_rmse = _rmse(head_errors)
    bands = {}
    for count in (1, 2, 3):
        subset = [row for row in stable if row["latent_count"] == count]
        bands[str(count)] = {
            "sample_count": len(subset),
            "turbine_flow_m3s": _summary(
                [row["flow_m3s"] for row in subset]
            ),
            "hydraulic_head_m": _summary([row["head_m"] for row in subset]),
            "per_latent_unit_flow_m3s": _summary(
                [row["per_latent_unit_flow_m3s"] for row in subset]
            ),
        }
    return {
        "role": "posthoc_latent_flow_band_diagnostic_not_generator_labels",
        "band_definition_m3s": {
            "partial_or_unclassified": [0.0, MINIMUM_STABLE_TURBINE_FLOW_M3S],
            "latent_1": [MINIMUM_STABLE_TURBINE_FLOW_M3S, 165.0],
            "latent_2": [165.0, 275.0],
            "latent_3": [275.0, None],
        },
        "zero_turbine_hour_count": zero_count,
        "negative_turbine_hour_count": negative_count,
        "partial_or_unclassified_positive_hour_count": partial_count,
        "stable_latent_band_hour_count": len(stable),
        "bands": bands,
        "constant_per_latent_unit_diagnostic": {
            "median_m3s": base,
            "flow_rmse_m3s": constant_rmse,
        },
        "contemporaneous_head_regression_diagnostic": {
            "intercept_m3s_per_latent_unit": intercept,
            "slope_m3s_per_latent_unit_per_head_m": slope,
            "flow_rmse_m3s": head_rmse,
            "rmse_change_vs_constant_percent": (
                (head_rmse / constant_rmse - 1.0) * 100.0
                if constant_rmse > 0.0
                else None
            ),
            "forward_causal_use_admitted": False,
        },
    }


def _non_turbine_diagnostics(aligned: Mapping[str, Any]) -> dict[str, Any]:
    rows = aligned["rows"]
    nonzero = 0
    negative = 0
    positive_totals = []
    for row in rows:
        values = [row[name] for name in ("orifice", "sluice", "spillway")]
        if any(abs(value) > 1e-12 for value in values):
            nonzero += 1
        if any(value < 0.0 for value in values):
            negative += 1
        positive_totals.append(sum(max(value, 0.0) for value in values))
    return {
        "component_names": ["orifice", "sluice", "spillway"],
        "nonzero_component_hour_count": nonzero,
        "nonzero_component_hour_fraction": nonzero / len(rows),
        "negative_revision_component_hour_count": negative,
        "positive_non_turbine_total_m3s": _summary(positive_totals),
        "represented_by_native_generator_count_schedule": False,
    }


def _headers_status(body: bytes, *, audited_at: datetime) -> dict[str, object]:
    try:
        text = body.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise ValueError("dispatch_conversion_headers_invalid") from exc
    lines = [line.strip() for line in text.splitlines()]
    status_lines = [line for line in lines if line.startswith("HTTP/")]
    if not status_lines:
        raise ValueError("dispatch_conversion_headers_invalid")
    match = re.match(r"^HTTP/\S+\s+(\d{3})(?:\s|$)", status_lines[-1])
    headers = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.lower()] = value.strip()
    try:
        response_date = parsedate_to_datetime(headers["date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("dispatch_conversion_headers_invalid") from exc
    if (
        match is None
        or int(match.group(1)) != 200
        or not headers.get("content-type", "").startswith("application/json")
        or not _aware(response_date)
        or response_date.astimezone(UTC) > audited_at
    ):
        raise ValueError("dispatch_conversion_headers_invalid")
    return {
        "http_status": 200,
        "content_type": headers.get("content-type"),
        "response_date_utc": _iso(response_date),
        "server": headers.get("server"),
        "tls_hostname_verification_retained": True,
    }


def _summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("dispatch_conversion_summary_empty")
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "p05": _quantile(ordered, 0.05),
        "median": _quantile(ordered, 0.5),
        "p95": _quantile(ordered, 0.95),
        "maximum": ordered[-1],
    }


def _quantile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _rmse(errors: list[float]) -> float:
    return math.sqrt(sum(value * value for value in errors) / len(errors))


def _load_json(path: Path) -> tuple[bytes, Any]:
    body = path.read_bytes()
    try:
        return body, json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dispatch_conversion_json_invalid") from exc


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
        raise ValueError("dispatch_conversion_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("dispatch_conversion_time_invalid") from exc
    if not _aware(parsed):
        raise ValueError("dispatch_conversion_time_invalid")
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
        raise ValueError("dispatch_conversion_report_overwrite_forbidden")
    report = audit_dispatch_conversion(
        pool_path=args.pool,
        pool_headers_path=args.pool_headers,
        tail_path=args.tail,
        tail_headers_path=args.tail_headers,
        stage39_manifest_path=args.stage39_manifest,
        audited_at=_parse_time(args.audited_at),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(
        "aligned_hour_count="
        f"{report['aligned_historical_support']['aligned_hour_count']}"
    )
    print(
        "physical_release_boundary_ready="
        f"{report['physical_release_boundary_ready']}"
    )


if __name__ == "__main__":
    main()
