#!/usr/bin/env python3
"""Execute the approved bounded Stage 42 component-event target plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import (  # noqa: E402
    freeze_geotransport_stage42_component_event_target_protocol as freeze,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage42_component_event_targets as planner,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE42_ROOT
PLAN_PATH = DEFAULT_OUTPUT / "target_acquisition_plan.json"
STATE_NAME = "target_acquisition_state.json"
MANIFEST_NAME = "target_acquisition_manifest.json"
FROZEN_PLAN_SHA256 = "28519b1c7834527da9b9b8c2bf30e15f15b293e040b264f60cdbf8df88449ef0"
SCHEMA = "gwm.geotransport.stage42_component_event_target_manifest.v1"
STATE_SCHEMA = "gwm.geotransport.stage42_component_event_target_state.v1"
USER_AGENT = "gisdataagent-stage42-component-event-targets/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0:
        raise ValueError("stage42_positive_timeout_required")
    output = _validate_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    plan = _load_frozen_plan()
    state_path = output / STATE_NAME
    state = _load_state(state_path, plan["sources"])
    opener = _opener(args.proxy)
    artifacts = []
    for source in plan["sources"]:
        artifact = _acquire_source(
            source=source,
            output=output,
            state=state,
            state_path=state_path,
            opener=opener,
            timeout_seconds=args.timeout_seconds,
        )
        artifacts.append(artifact)
        print(
            f"completed={len(artifacts)}/{len(plan['sources'])} "
            f"source_id={source['source_id']} bytes={artifact['size_bytes']}"
        )
    manifest = _compile_manifest(plan, state, artifacts, state_path)
    path = output / MANIFEST_NAME
    _write_json(path, manifest)
    print(path)
    print(f"requests={manifest['actual_request_count']}")
    print(f"attempts={manifest['actual_attempt_count']}")
    print(f"downloaded_bytes={manifest['actual_download_bytes']}")
    print(f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
    return 0


def _acquire_source(
    *,
    source: dict[str, Any],
    output: Path,
    state: dict[str, Any],
    state_path: Path,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
) -> dict[str, Any]:
    source_id = str(source["source_id"])
    record = state["sources"][source_id]
    raw_path = output / str(source["output_name"])
    if raw_path.is_file():
        if record.get("success") is not True:
            raise ValueError("stage42_raw_artifact_without_success_provenance")
        body = raw_path.read_bytes()
        _validate_payload(_json_object(body), source)
        if (
            hashlib.sha256(body).hexdigest() != record.get("sha256")
            or len(body) != record.get("size_bytes")
        ):
            raise ValueError("stage42_resumed_raw_artifact_drift")
        return _artifact_record(raw_path, source, record)

    maximum_attempts = planner.MAXIMUM_ATTEMPTS_PER_REQUEST
    while int(record["attempt_count"]) < maximum_attempts:
        attempt = int(record["attempt_count"]) + 1
        record["attempt_count"] = attempt
        try:
            body, retrieval = _fetch_once(
                str(source["url"]),
                opener=opener,
                timeout_seconds=timeout_seconds,
                maximum_bytes=int(source["maximum_bytes_per_attempt"]),
            )
            _validate_payload(_json_object(body), source)
        except (
            ValueError,
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
        ) as exc:
            record["failed_attempts"].append(
                {
                    "attempt": attempt,
                    "failed_at": datetime.now(UTC).isoformat(),
                    "error": str(exc),
                }
            )
            _write_json(state_path, state)
            if attempt >= maximum_attempts:
                raise RuntimeError(
                    f"stage42_request_attempts_exhausted:{source_id}"
                ) from exc
            time.sleep(float(attempt))
            continue
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
        record.update(
            {
                "success": True,
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
                "retrieval": retrieval,
            }
        )
        _write_json(state_path, state)
        return _artifact_record(raw_path, source, record)
    raise RuntimeError(f"stage42_request_attempts_exhausted:{source_id}")


def _fetch_once(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    _validate_url(url)
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with opener.open(request, timeout=timeout_seconds) as response:
        _validate_url(response.geturl())
        body = response.read(maximum_bytes + 1)
        if len(body) > maximum_bytes:
            raise ValueError("stage42_response_size_limit_exceeded")
        return body, {
            "url": url,
            "transport": "configured_proxy_or_direct_urllib",
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "tls_hostname_verification_retained": True,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }


def _validate_payload(payload: dict[str, Any], source: dict[str, Any]) -> None:
    features = payload.get("features")
    links = payload.get("links")
    begin = _parse_time(str(source["begin_utc"]))
    end = _parse_time(str(source["end_utc"]))
    if (
        payload.get("type") != "FeatureCollection"
        or not isinstance(features, list)
        or not features
        or payload.get("numberReturned") != len(features)
        or len(features)
        > int(source["expected_maximum_inclusive_grid_positions"])
        or not isinstance(links, list)
        or any(link.get("rel") == "next" for link in links)
    ):
        raise ValueError("stage42_target_payload_invalid")
    times = []
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("stage42_target_feature_invalid")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("stage42_target_feature_invalid")
        raw_value = properties.get("value")
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("stage42_target_feature_invalid") from exc
        timestamp = _parse_time(str(properties.get("time")))
        if (
            properties.get("monitoring_location_id") != source["site_id"]
            or properties.get("parameter_code") != source["parameter_code"]
            or properties.get("statistic_id") != "00011"
            or properties.get("unit_of_measure") != "ft^3/s"
            or not isinstance(properties.get("approval_status"), str)
            or not math.isfinite(numeric)
            or not begin <= timestamp <= end
            or int((timestamp - begin).total_seconds()) % 1800 != 0
        ):
            raise ValueError("stage42_target_feature_invalid")
        times.append(timestamp)
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError("stage42_target_time_axis_invalid")


def _compile_manifest(
    plan: dict[str, Any],
    state: dict[str, Any],
    artifacts: list[dict[str, Any]],
    state_path: Path,
) -> dict[str, Any]:
    attempts = sum(
        int(value["attempt_count"]) for value in state["sources"].values()
    )
    total_bytes = sum(int(value["size_bytes"]) for value in artifacts)
    if (
        len(artifacts) != planner.MAXIMUM_LOGICAL_REQUEST_COUNT
        or attempts
        > planner.MAXIMUM_LOGICAL_REQUEST_COUNT
        * planner.MAXIMUM_ATTEMPTS_PER_REQUEST
        or total_bytes > planner.MAXIMUM_PERSISTED_DOWNLOAD_BYTES
    ):
        raise ValueError("stage42_acquisition_manifest_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "status": "stage42_component_event_target_values_acquired",
        "frozen_target_acquisition_plan": _artifact(PLAN_PATH),
        "acquisition_state_artifact": _artifact(state_path),
        "actual_request_count": len(artifacts),
        "actual_attempt_count": attempts,
        "actual_download_bytes": total_bytes,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "request_boundary": plan["request_boundary"],
        "claim_boundary": {
            "stage41_events_and_target_operator_frozen_before_values": True,
            "downstream_target_values_acquired": True,
            "observed_graph_state_values_acquired": True,
            "target_coverage_compiled": False,
            "empirical_lag_support_sets_compiled": False,
            "common_empirical_lag_support_admitted": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_intervention_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _load_frozen_plan() -> dict[str, Any]:
    body = PLAN_PATH.read_bytes()
    if hashlib.sha256(body).hexdigest() != FROZEN_PLAN_SHA256:
        raise ValueError("stage42_frozen_plan_hash_invalid")
    value = _json_object(body)
    if value != planner.compile_plan():
        raise ValueError("stage42_frozen_plan_not_reproducible")
    return value


def _load_state(path: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = [str(value["source_id"]) for value in sources]
    if path.is_file():
        value = _json_object(path.read_bytes())
        if (
            value.get("schema") != STATE_SCHEMA
            or value.get("frozen_plan_sha256") != FROZEN_PLAN_SHA256
            or list(value.get("sources", {})) != expected_ids
        ):
            raise ValueError("stage42_acquisition_state_invalid")
        return value
    value = {
        "schema": STATE_SCHEMA,
        "frozen_plan_sha256": FROZEN_PLAN_SHA256,
        "sources": {
            source_id: {
                "attempt_count": 0,
                "failed_attempts": [],
                "success": False,
            }
            for source_id in expected_ids
        },
    }
    _write_json(path, value)
    return value


def _artifact_record(
    path: Path,
    source: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    retrieval = record.get("retrieval")
    if not isinstance(retrieval, dict):
        raise ValueError("stage42_success_retrieval_provenance_required")
    return {
        "source_id": source["source_id"],
        "source": source["source"],
        "event_id": source["event_id"],
        "site_id": source["site_id"],
        "site_role": source["site_role"],
        "begin_utc": source["begin_utc"],
        "end_utc": source["end_utc"],
        "role": source["role"],
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
        "hash_verified": True,
        "attempt_count": record["attempt_count"],
        "failed_attempts": record["failed_attempts"],
        "license": source["license"],
        "license_url": source["license_url"],
        **retrieval,
    }


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != planner.USGS_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        != "/ogcapi/v0/collections/continuous/items"
    ):
        raise ValueError("stage42_url_outside_allowlist")


def _validate_output(path: Path) -> Path:
    output = path.resolve()
    if output != DEFAULT_OUTPUT.resolve():
        raise ValueError("stage42_output_must_match_frozen_root")
    return output


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(*handlers)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage42_timezone_required")
    return parsed.astimezone(UTC)


def _artifact(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_object(body: bytes) -> dict[str, Any]:
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("stage42_json_object_required")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
