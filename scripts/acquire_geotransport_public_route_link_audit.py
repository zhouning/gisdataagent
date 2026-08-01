#!/usr/bin/env python3
"""Acquire bounded official Route_Link schema and regional parameter fixtures."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

import h5py
import numpy as np
from scipy.io import netcdf_file


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data/geotransport_v0_1/route_link_public_audit"
SCHEMA = "gwm.geotransport.public_route_link_audit.v1"
USER_AGENT = "gisdataagent-public-route-link-audit/0.1"
ALLOWED_HOST = "raw.githubusercontent.com"
WRF_HYDRO_COMMIT = "4510c28c9afc72b42062158125a56b6d9dc6c057"
T_ROUTE_COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"
MAXIMUM_OBJECT_COUNT = 5
MAXIMUM_TOTAL_BYTES = 1_600_000
MUSKINGUM_CUNGE_FIELDS = (
    "link",
    "to",
    "Length",
    "BtmWdth",
    "TopWdth",
    "TopWdthCC",
    "ChSlp",
    "So",
    "n",
    "nCC",
)
OPTIONAL_MUSKINGUM_FIELDS = ("MusK", "MusX")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(
    *, travel_report_path: Path = DEFAULT_TRAVEL_REPORT, values_mode: bool = False
) -> dict[str, Any]:
    travel_body = travel_report_path.read_bytes()
    travel = json.loads(travel_body)
    if travel.get("schema") != "gwm.geotransport.center_hill_travel_time_prior.v1":
        raise ValueError("route_link_audit_travel_report_invalid")
    feature_ids = [
        int(value) for value in travel["linear_referenced_path"]["feature_ids"]
    ]
    requests = [
        _request(
            source_id="wrf_hydro_route_link_cdl",
            repository="NCAR/wrf_hydro_nwm_public",
            commit=WRF_HYDRO_COMMIT,
            repository_path=(
                "tests/config_file_meta/croton_NY/nwm_ana/NWM/DOMAIN/Route_Link.cdl"
            ),
            output_name="wrf_hydro_route_link.cdl",
            maximum_bytes=20_000,
            role="authoritative_parameter_schema",
        ),
        _request(
            source_id="wrf_hydro_license",
            repository="NCAR/wrf_hydro_nwm_public",
            commit=WRF_HYDRO_COMMIT,
            repository_path="LICENSE.txt",
            output_name="wrf_hydro_LICENSE.txt",
            maximum_bytes=10_000,
            role="license",
        ),
        _request(
            source_id="t_route_hurricane_laura_nwm_v2_1",
            repository="NOAA-OWP/t-route",
            commit=T_ROUTE_COMMIT,
            repository_path="test/HurricaneLaura/domain/RouteLink_NWMv2.1.nc",
            output_name="RouteLink_HurricaneLaura_NWMv2.1.nc",
            maximum_bytes=50_000,
            role="regional_nwm_v2_1_parameter_fixture",
        ),
        _request(
            source_id="t_route_lower_colorado",
            repository="NOAA-OWP/t-route",
            commit=T_ROUTE_COMMIT,
            repository_path="test/LowerColorado_TX/domain/RouteLink.nc",
            output_name="RouteLink_LowerColorado_TX.nc",
            maximum_bytes=1_300_000,
            role="regional_operational_test_parameter_fixture",
        ),
        _request(
            source_id="t_route_license",
            repository="NOAA-OWP/t-route",
            commit=T_ROUTE_COMMIT,
            repository_path="LICENSE",
            output_name="t-route_LICENSE",
            maximum_bytes=20_000,
            role="license",
        ),
    ]
    if (
        len(requests) != MAXIMUM_OBJECT_COUNT
        or sum(int(item["maximum_bytes"]) for item in requests)
        > MAXIMUM_TOTAL_BYTES
    ):
        raise ValueError("route_link_audit_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "determine whether public official reach parameters can support a "
            "non-fabricated Kernel v2 operator"
        ),
        "center_hill_travel_report": _artifact(travel_report_path, travel_body),
        "center_hill_feature_ids": feature_ids,
        "center_hill_active_feature_ids": feature_ids[1:],
        "request_boundary": {
            "maximum_object_count": MAXIMUM_OBJECT_COUNT,
            "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
            "planned_maximum_bytes": sum(
                int(item["maximum_bytes"]) for item in requests
            ),
            "allowed_host": ALLOWED_HOST,
        },
        "requests": requests,
        "required_parameter_contract": {
            "muskingum_cunge_fields": list(MUSKINGUM_CUNGE_FIELDS),
            "optional_precomputed_muskingum_fields": list(
                OPTIONAL_MUSKINGUM_FIELDS
            ),
            "no_default_parameter_substitution": True,
        },
        "claim_boundary": {
            "request_plan_only": not values_mode,
            "public_route_link_objects_acquired": values_mode,
            "center_hill_parameter_coverage_verified": False,
            "center_hill_muskingum_cunge_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("route_link_audit_positive_request_limits_required")
    manifest = compile_plan(
        travel_report_path=args.travel_report, values_mode=not args.plan_only
    )
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plan_only:
        output = args.output / "acquisition_plan.json"
        _write_json(output, manifest)
        print(output)
        return 0

    opener = _opener(args.proxy)
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    raw_root = args.output / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    for request in manifest["requests"]:
        body, retrieval = _fetch(
            str(request["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(request["maximum_bytes"]),
        )
        total_bytes += len(body)
        if total_bytes > MAXIMUM_TOTAL_BYTES:
            raise ValueError("route_link_audit_total_download_boundary_exceeded")
        path = raw_root / str(request["output_name"])
        path.write_bytes(body)
        artifacts.append(
            {
                **request,
                **retrieval,
                **_artifact(path, body),
            }
        )

    center_hill_ids = set(int(value) for value in manifest["center_hill_feature_ids"])
    center_hill_active_ids = set(
        int(value) for value in manifest["center_hill_active_feature_ids"]
    )
    netcdf_audits = []
    for artifact in artifacts:
        if not str(artifact["path"]).endswith(".nc"):
            continue
        netcdf_audits.append(
            _audit_route_link(
                REPO_ROOT / str(artifact["path"]),
                source_id=str(artifact["source_id"]),
                center_hill_ids=center_hill_ids,
                center_hill_active_ids=center_hill_active_ids,
            )
        )

    complete_center_hill_sources = [
        item
        for item in netcdf_audits
        if item["all_required_muskingum_cunge_fields_present"]
        and item["center_hill_active_feature_coverage_count"]
        == len(center_hill_active_ids)
    ]
    manifest["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    manifest["artifacts"] = artifacts
    manifest["artifact_count"] = len(artifacts)
    manifest["total_downloaded_bytes"] = total_bytes
    manifest["netcdf_audits"] = netcdf_audits
    manifest["adjudication"] = {
        "official_field_contract_acquired": True,
        "regional_real_parameter_fixtures_acquired": len(netcdf_audits) == 2,
        "center_hill_complete_parameter_source_count": len(
            complete_center_hill_sources
        ),
        "center_hill_route_link_parameters_available": bool(
            complete_center_hill_sources
        ),
        "regional_fixture_parameters_may_be_transferred_to_center_hill": False,
        "reason": (
            "regional official fixtures establish schema and executable parameter "
            "ranges, but their feature axes do not supply Center Hill reach parameters"
            if not complete_center_hill_sources
            else "at least one source covers every active Center Hill reach"
        ),
        "next_operator_decision": (
            "block Center Hill Muskingum-Cunge execution until a version-matched "
            "Route_Link or independently authoritative per-reach parameters are acquired"
            if not complete_center_hill_sources
            else "permit invariant-gated Center Hill Muskingum-Cunge development"
        ),
    }
    manifest["claim_boundary"].update(
        {
            "center_hill_parameter_coverage_verified": True,
            "center_hill_muskingum_cunge_admitted": bool(
                complete_center_hill_sources
            ),
        }
    )
    output = args.output / "acquisition_manifest.json"
    _write_json(output, manifest)
    print(output)
    return 0


def _request(
    *,
    source_id: str,
    repository: str,
    commit: str,
    repository_path: str,
    output_name: str,
    maximum_bytes: int,
    role: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "repository": repository,
        "commit": commit,
        "repository_path": repository_path,
        "url": f"https://raw.githubusercontent.com/{repository}/{commit}/{repository_path}",
        "output_name": output_name,
        "maximum_bytes": maximum_bytes,
        "role": role,
    }


def _audit_route_link(
    path: Path,
    *,
    source_id: str,
    center_hill_ids: set[int],
    center_hill_active_ids: set[int],
) -> dict[str, Any]:
    variables, container_format = _read_netcdf_variables(path)
    present = sorted(variables)
    missing = [name for name in MUSKINGUM_CUNGE_FIELDS if name not in variables]
    optional_present = [
        name for name in OPTIONAL_MUSKINGUM_FIELDS if name in variables
    ]
    if "link" not in variables:
        raise ValueError("route_link_audit_link_axis_missing")
    links = np.asarray(variables["link"], dtype=np.int64).reshape(-1)
    unique_links = set(int(value) for value in links)
    summaries = {
        name: _numeric_summary(variables[name])
        for name in MUSKINGUM_CUNGE_FIELDS + OPTIONAL_MUSKINGUM_FIELDS
        if name in variables
    }
    overlap = sorted(unique_links & center_hill_ids)
    active_overlap = sorted(unique_links & center_hill_active_ids)
    return {
        "source_id": source_id,
        "artifact": _artifact(path, path.read_bytes()),
        "container_format": container_format,
        "feature_count": int(links.size),
        "unique_feature_count": len(unique_links),
        "variable_names": present,
        "required_muskingum_cunge_fields_missing": missing,
        "all_required_muskingum_cunge_fields_present": not missing,
        "optional_precomputed_muskingum_fields_present": optional_present,
        "center_hill_feature_overlap": overlap,
        "center_hill_feature_coverage_count": len(overlap),
        "center_hill_active_feature_overlap": active_overlap,
        "center_hill_active_feature_coverage_count": len(active_overlap),
        "parameter_summaries": summaries,
        "admitted_as_center_hill_parameters": (
            not missing and len(active_overlap) == len(center_hill_active_ids)
        ),
        "admitted_as_public_invariant_fixture": not missing,
    }


def _read_netcdf_variables(path: Path) -> tuple[dict[str, np.ndarray], str]:
    if h5py.is_hdf5(path):
        with h5py.File(path, "r") as dataset:
            variables = {
                str(name): np.asarray(value[...])
                for name, value in dataset.items()
                if isinstance(value, h5py.Dataset)
            }
        return variables, "netcdf4_hdf5"
    with netcdf_file(path, "r", mmap=False) as dataset:
        variables = {
            str(name): np.asarray(value[:]).copy()
            for name, value in dataset.variables.items()
        }
    return variables, "netcdf3"


def _numeric_summary(values: np.ndarray) -> dict[str, Any]:
    flat = values.reshape(-1)
    if flat.dtype.kind not in "biuf":
        return {"dtype": str(flat.dtype), "value_count": int(flat.size)}
    numeric = flat.astype(float)
    finite = np.isfinite(numeric)
    finite_values = numeric[finite]
    return {
        "dtype": str(flat.dtype),
        "value_count": int(flat.size),
        "finite_value_count": int(finite.sum()),
        "minimum": float(finite_values.min()) if finite_values.size else None,
        "maximum": float(finite_values.max()) if finite_values.size else None,
        "zero_count": int((finite_values == 0.0).sum()),
        "negative_count": int((finite_values < 0.0).sum()),
    }


def _opener(proxy: str | None) -> urllib.request.OpenerDirector:
    if not proxy:
        return urllib.request.build_opener()
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
) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError("route_link_audit_source_host_not_allowed")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > maximum_bytes:
                    raise ValueError("route_link_audit_declared_size_exceeded")
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("route_link_audit_stream_size_exceeded")
                return body, {
                    "source_url": url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "http_status": int(response.status),
                    "content_type": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "attempt_count": attempt,
                }
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"route_link_audit_request_failed:{url}:{error}")


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
