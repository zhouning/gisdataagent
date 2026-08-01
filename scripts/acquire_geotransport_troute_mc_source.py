#!/usr/bin/env python3
"""Acquire a bounded, fixed-commit t-route Muskingum-Cunge source bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data/geotransport_v0_1/t_route_mc_source_audit"
SCHEMA = "gwm.geotransport.t_route_mc_source_audit.v1"
T_ROUTE_COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"
T_ROUTE_REPOSITORY = "NOAA-OWP/t-route"
ALLOWED_HOST = "raw.githubusercontent.com"
USER_AGENT = "gisdataagent-t-route-mc-source-audit/0.1"
MAXIMUM_OBJECT_COUNT = 8
MAXIMUM_TOTAL_BYTES = 120_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    requests = [
        _request(
            "precision_module",
            "src/kernel/muskingum/varPrecision.f90",
            "varPrecision.f90",
            2_000,
            "official_float_precision_contract",
        ),
        _request(
            "mc_single_segment_kernel",
            "src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90",
            "MCsingleSegStime_f2py_NOLOOP.f90",
            30_000,
            "official_muskingum_cunge_kernel",
        ),
        _request(
            "mc_c_binding",
            "src/kernel/muskingum/pyMCsingleSegStime_NoLoop.f90",
            "pyMCsingleSegStime_NoLoop.f90",
            5_000,
            "official_bind_c_entrypoint",
        ),
        _request(
            "mc_c_header",
            "src/troute-routing/troute/routing/fast_reach/pyMCsingleSegStime_NoLoop.h",
            "pyMCsingleSegStime_NoLoop.h",
            5_000,
            "official_c_abi_contract",
        ),
        _request(
            "mc_reach_wrapper",
            "src/troute-routing/troute/routing/fast_reach/reach.pyx",
            "reach.pyx",
            12_000,
            "official_network_state_and_order_contract",
        ),
        _request(
            "mc_reference_demo",
            "src/kernel/muskingum/mc_sseg_stime_NOLOOP_demo.py",
            "mc_sseg_stime_NOLOOP_demo.py",
            35_000,
            "official_qvd_conformance_values",
        ),
        _request(
            "mc_makefile",
            "src/kernel/muskingum/makefile",
            "makefile",
            8_000,
            "official_build_contract",
        ),
        _request(
            "t_route_license",
            "LICENSE",
            "LICENSE",
            20_000,
            "license",
        ),
    ]
    planned_bytes = sum(int(item["maximum_bytes"]) for item in requests)
    if (
        len(requests) != MAXIMUM_OBJECT_COUNT
        or planned_bytes > MAXIMUM_TOTAL_BYTES
    ):
        raise ValueError("t_route_mc_source_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "build an exact-commit professional Muskingum-Cunge baseline without "
            "vendoring or installing the full t-route application"
        ),
        "repository": T_ROUTE_REPOSITORY,
        "commit": T_ROUTE_COMMIT,
        "request_boundary": {
            "allowed_host": ALLOWED_HOST,
            "maximum_object_count": MAXIMUM_OBJECT_COUNT,
            "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
            "planned_maximum_bytes": planned_bytes,
        },
        "requests": requests,
        "runtime_contract": {
            "entrypoint": "c_muskingcungenwm",
            "precision": "Fortran default real / C float32",
            "state_order": ["discharge_m3s", "velocity_mps", "depth_m"],
            "parameter_order": [
                "dt",
                "qup",
                "quc",
                "qdp",
                "qlat",
                "dx",
                "bottom_width",
                "top_width",
                "compound_top_width",
                "manning_n",
                "compound_manning_n",
                "channel_side_slope_ChSlp",
                "bed_slope",
                "previous_velocity",
                "previous_depth",
            ],
            "channel_geometry_evidence": (
                "the official kernel computes horizontal_per_vertical z=1/ChSlp"
            ),
        },
        "claim_boundary": {
            "source_identity_fixed": True,
            "source_values_acquired": values_mode,
            "runtime_built": False,
            "official_kernel_executed": False,
            "center_hill_execution_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("t_route_mc_source_positive_request_limits_required")
    manifest = compile_plan(values_mode=not args.plan_only)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plan_only:
        path = args.output / "acquisition_plan.json"
        _write_json(path, manifest)
        print(path)
        return 0

    raw_root = args.output / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    opener = _opener(args.proxy)
    total_bytes = 0
    artifacts: list[dict[str, Any]] = []
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
            raise ValueError("t_route_mc_source_total_download_boundary_exceeded")
        path = raw_root / str(request["output_name"])
        path.write_bytes(body)
        artifacts.append({**request, **retrieval, **_artifact(path, body)})

    manifest.update(
        {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": artifacts,
            "artifact_count": len(artifacts),
            "total_downloaded_bytes": total_bytes,
        }
    )
    output = args.output / "acquisition_manifest.json"
    _write_json(output, manifest)
    print(output)
    return 0


def _request(
    source_id: str,
    repository_path: str,
    output_name: str,
    maximum_bytes: int,
    role: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "repository": T_ROUTE_REPOSITORY,
        "commit": T_ROUTE_COMMIT,
        "repository_path": repository_path,
        "url": (
            f"https://{ALLOWED_HOST}/{T_ROUTE_REPOSITORY}/"
            f"{T_ROUTE_COMMIT}/{repository_path}"
        ),
        "output_name": output_name,
        "maximum_bytes": maximum_bytes,
        "role": role,
    }


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("t_route_mc_source_proxy_url_invalid")
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
        raise ValueError("t_route_mc_source_url_outside_allowlist")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("t_route_mc_source_object_boundary_exceeded")
                return body, {
                    "http_status": int(response.status),
                    "content_type": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "attempt_count": attempt,
                }
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 4))
    raise RuntimeError("t_route_mc_source_download_failed") from last_error


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
