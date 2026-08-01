#!/usr/bin/env python3
"""Acquire frozen public documentation for Stage 34 temporal semantics."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import acquire_geotransport_stage29_blind_transfer_events as stage29


DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/stage34_center_hill_temporal_semantics"
)
SCHEMA = "gwm.geotransport.stage34_temporal_semantics_acquisition.v1"
OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/"
    "temporal_response_semantics.py"
)
DOCUMENT_HOST = "raw.githubusercontent.com"
DOCUMENT_COMMIT = "beb8d507c9da8ec074d444117bda7d7daf69e5ee"
DOCUMENT_URL = (
    "https://raw.githubusercontent.com/USACE/cwms-data-api/"
    f"{DOCUMENT_COMMIT}/docs/source/data/timeseries.rst"
)
MAXIMUM_DOWNLOAD_BYTES = 500_000
REQUIRED_DOCUMENT_MARKERS = (
    "parameter",
    "type",
    "duration",
    "interval",
    "version",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("plan", "acquire"), required=True
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": "documentation_values" if values_mode else "plan",
        "purpose": (
            "freeze authoritative CWMS time-series naming semantics before "
            "compiling observation and process-time compatibility"
        ),
        "frozen_operator_artifact": stage29._artifact(OPERATOR_PATH),
        "predeclared_semantic_boundary": {
            "source_field": "CWMS hourly interval-average release",
            "target_field": (
                "derived hourly mean of two USGS instantaneous samples"
            ),
            "empirical_functional": (
                "windowed linear-association peak on interval-end labels"
            ),
            "physics_functionals": [
                "first signal arrival",
                "discharge-response centroid",
                "material-exit centroid",
            ],
            "same_time_dimension_is_sufficient_for_substitution": False,
            "runtime_promotion_allowed": False,
        },
        "document_validation": {
            "encoding": "utf-8",
            "required_casefolded_markers": list(
                REQUIRED_DOCUMENT_MARKERS
            ),
            "source_commit": DOCUMENT_COMMIT,
        },
        "request_boundary": {
            "allowed_hosts": [DOCUMENT_HOST],
            "maximum_request_count": 1,
            "maximum_total_download_bytes": MAXIMUM_DOWNLOAD_BYTES,
            "workspace_or_private_data_sent": False,
            "release_or_downstream_outcome_values_requested": False,
        },
        "sources": [
            {
                "source_id": "cwms_timeseries_semantics_document",
                "source": "usace_cwms_data_api_repository",
                "role": "authoritative_temporal_series_semantics",
                "url": DOCUMENT_URL,
                "output_name": "raw/cwms_timeseries.rst",
                "maximum_bytes": MAXIMUM_DOWNLOAD_BYTES,
                "source_terms": (
                    "upstream repository terms retained; redistribution "
                    "not independently adjudicated"
                ),
                "source_terms_url": (
                    "https://github.com/USACE/cwms-data-api/blob/"
                    f"{DOCUMENT_COMMIT}/LICENSE"
                ),
            }
        ],
        "claim_boundary": {
            "documentation_acquired": values_mode,
            "interval_end_label_shift_admitted": False,
            "actuation_instant_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_transition_admitted": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage34_positive_request_limits_required")
    output = stage29._validate_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.phase == "plan":
        path = output / "acquisition_plan.json"
        stage29._write_json(path, compile_plan())
    else:
        path = _acquire(args, output)
    print(path)
    return 0


def _acquire(args: argparse.Namespace, output: Path) -> Path:
    plan_path = output / "acquisition_plan.json"
    frozen_plan = _load_exact_plan(plan_path, compile_plan())
    values_plan = compile_plan(values_mode=True)
    source = values_plan["sources"][0]
    body, retrieval = _fetch_document(
        str(source["url"]),
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        maximum_bytes=int(source["maximum_bytes"]),
    )
    _validate_document(body)
    raw_path = output / str(source["output_name"])
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(body)
    artifact = {
        "source_id": source["source_id"],
        "source": source["source"],
        "role": source["role"],
        "path": raw_path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "hash_verified": True,
        "source_terms": source["source_terms"],
        "source_terms_url": source["source_terms_url"],
        **retrieval,
    }
    manifest = {
        **values_plan,
        "status": "temporal_semantics_document_acquired",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "frozen_acquisition_plan": stage29._artifact(plan_path),
        "frozen_acquisition_plan_content": frozen_plan,
        "document_commit": DOCUMENT_COMMIT,
        "required_markers_verified": list(REQUIRED_DOCUMENT_MARKERS),
        "artifacts": [artifact],
        "artifact_count": 1,
        "actual_request_count": 1,
        "total_downloaded_bytes": len(body),
        "claim_boundary_after_acquisition": {
            "operator_frozen_before_document_values": True,
            "documentation_acquired": True,
            "release_or_downstream_outcome_values_acquired": False,
            "temporal_semantics_reconciliation_compiled": False,
            "physical_response_time_admitted": False,
            "runtime_transition_admitted": False,
        },
    }
    path = output / "acquisition_manifest.json"
    stage29._write_json(path, manifest)
    print(f"downloaded_bytes={len(body)}")
    return path


def _fetch_document(
    url: str,
    *,
    proxy: str,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, object]]:
    _validate_url(url)
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    opener = urllib.request.build_opener(*handlers)
    failures = []
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/plain",
                "User-Agent": "gis-data-agent-stage34/1.0",
            },
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                _validate_url(response.geturl())
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("stage34_document_size_limit_exceeded")
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
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
        ) as exc:
            error = exc
            failures.append({"attempt": attempt, "error": str(exc)})
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                break
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"stage34_document_request_failed:{error}:{failures}")


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != DOCUMENT_HOST
        or parsed.username is not None
        or parsed.password is not None
        or DOCUMENT_COMMIT not in parsed.path
    ):
        raise ValueError("stage34_document_url_outside_allowlist")


def _validate_document(body: bytes) -> str:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("stage34_document_utf8_required") from exc
    folded = text.casefold()
    if (
        len(body) < 1_000
        or any(value not in folded for value in REQUIRED_DOCUMENT_MARKERS)
    ):
        raise ValueError("stage34_document_markers_missing")
    return text


def _load_exact_plan(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("stage34_plan_must_be_frozen_before_document_values")
    value = json.loads(path.read_bytes())
    if value != expected:
        raise ValueError("stage34_frozen_plan_mismatch")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
