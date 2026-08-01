#!/usr/bin/env python3
"""Execute the approved bounded Stage 39 component-discharge value plan."""

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
    freeze_geotransport_stage39_component_discharge_value_protocol as freeze,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage39_component_discharge_values as planner,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE39_ROOT
PLAN_PATH = DEFAULT_OUTPUT / "value_acquisition_plan.json"
STATE_NAME = "value_acquisition_state.json"
MANIFEST_NAME = "value_acquisition_manifest.json"
FROZEN_PLAN_SHA256 = "0870a5c636d59b8074efaab199b881e4a384b58d19fd7410ca12e00a329e4f26"
SCHEMA = "gwm.geotransport.stage39_component_discharge_value_manifest.v1"
STATE_SCHEMA = "gwm.geotransport.stage39_component_discharge_acquisition_state.v1"
USER_AGENT = "gisdataagent-stage39-component-discharge-values/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0:
        raise ValueError("stage39_positive_timeout_required")
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
            raise ValueError("stage39_raw_artifact_without_success_provenance")
        body = raw_path.read_bytes()
        payload = _json_object(body)
        _validate_payload(payload, source)
        if hashlib.sha256(body).hexdigest() != record.get("sha256") or len(body) != record.get(
            "size_bytes"
        ):
            raise ValueError("stage39_resumed_raw_artifact_drift")
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
            payload = _json_object(body)
            _validate_payload(payload, source)
        except (ValueError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            record["failed_attempts"].append(
                {
                    "attempt": attempt,
                    "failed_at": datetime.now(UTC).isoformat(),
                    "error": str(exc),
                }
            )
            _write_json(state_path, state)
            if attempt >= maximum_attempts:
                raise RuntimeError(f"stage39_request_attempts_exhausted:{source_id}") from exc
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
    raise RuntimeError(f"stage39_request_attempts_exhausted:{source_id}")


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
        headers={
            "Accept": "application/json;version=2",
            "User-Agent": USER_AGENT,
        },
    )
    with opener.open(request, timeout=timeout_seconds) as response:
        _validate_url(response.geturl())
        body = response.read(maximum_bytes + 1)
        if len(body) > maximum_bytes:
            raise ValueError("stage39_response_size_limit_exceeded")
        return body, {
            "url": url,
            "transport": "configured_proxy_or_direct_urllib",
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "tls_hostname_verification_retained": True,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }


def _validate_payload(payload: dict[str, Any], source: dict[str, Any]) -> None:
    rows = payload.get("values")
    begin = _parse_time(str(source["begin_utc"]))
    end = _parse_time(str(source["end_utc"]))
    if (
        payload.get("name") != source["series_id"]
        or payload.get("office-id") != "LRN"
        or payload.get("units") != "cms"
        or payload.get("interval") != "PT1H"
        or payload.get("interval-offset") != 0
        or payload.get("page-size") != planner.CWMS_PAGE_SIZE
        or payload.get("next-page") not in (None, "")
        or not isinstance(rows, list)
        or payload.get("total") != len(rows)
        or len(rows) > int(source["expected_maximum_inclusive_grid_positions"])
    ):
        raise ValueError("stage39_component_discharge_payload_invalid")
    if "begin" in payload and _parse_time(str(payload["begin"])) != begin:
        raise ValueError("stage39_component_discharge_payload_begin_invalid")
    if "end" in payload and _parse_time(str(payload["end"])) != end:
        raise ValueError("stage39_component_discharge_payload_end_invalid")
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
                    or isinstance(row[1], bool)
                    or not math.isfinite(float(row[1]))
                )
            )
            or not isinstance(row[2], int)
            or isinstance(row[2], bool)
        ):
            raise ValueError("stage39_component_discharge_row_invalid")
        timestamp = datetime.fromtimestamp(row[0] / 1000.0, tz=UTC)
        if not begin <= timestamp <= end:
            raise ValueError("stage39_component_discharge_time_outside_window")
        times.append(timestamp)
    if (
        times != sorted(times)
        or len(times) != len(set(times))
        or any(
            (right - left).total_seconds() % 3600 != 0
            for left, right in zip(times, times[1:], strict=False)
        )
    ):
        raise ValueError("stage39_component_discharge_time_axis_invalid")


def _compile_manifest(
    plan: dict[str, Any],
    state: dict[str, Any],
    artifacts: list[dict[str, Any]],
    state_path: Path,
) -> dict[str, Any]:
    attempts = sum(int(value["attempt_count"]) for value in state["sources"].values())
    total_bytes = sum(int(value["size_bytes"]) for value in artifacts)
    if (
        len(artifacts) != planner.MAXIMUM_REQUEST_COUNT
        or attempts > planner.MAXIMUM_REQUEST_COUNT * planner.MAXIMUM_ATTEMPTS_PER_REQUEST
        or total_bytes > planner.MAXIMUM_PERSISTED_DOWNLOAD_BYTES
    ):
        raise ValueError("stage39_acquisition_manifest_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "frozen_value_acquisition_plan": _artifact(PLAN_PATH),
        "acquisition_state_artifact": _artifact(state_path),
        "actual_request_count": len(artifacts),
        "actual_attempt_count": attempts,
        "actual_download_bytes": total_bytes,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "request_boundary": plan["request_boundary"],
        "claim_boundary": {
            "component_values_acquired": True,
            "coverage_or_quality_support_compiled": False,
            "synchronized_total_discharge_compiled": False,
            "component_discharge_event_selected": False,
            "downstream_outcome_values_acquired": False,
            "gate_command_admitted": False,
            "human_action_admitted": False,
            "causal_intervention_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _load_frozen_plan() -> dict[str, Any]:
    body = PLAN_PATH.read_bytes()
    if hashlib.sha256(body).hexdigest() != FROZEN_PLAN_SHA256:
        raise ValueError("stage39_frozen_plan_hash_invalid")
    value = _json_object(body)
    if value != planner.compile_plan():
        raise ValueError("stage39_frozen_plan_not_reproducible")
    return value


def _load_state(path: Path, sources: list[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = [str(value["source_id"]) for value in sources]
    if path.is_file():
        value = _json_object(path.read_bytes())
        if value.get("schema") != STATE_SCHEMA or list(value.get("sources", {})) != expected_ids:
            raise ValueError("stage39_acquisition_state_invalid")
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


def _artifact_record(path: Path, source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    retrieval = record.get("retrieval")
    if not isinstance(retrieval, dict):
        raise ValueError("stage39_success_retrieval_provenance_required")
    return {
        "source_id": source["source_id"],
        "source": source["source"],
        "component": source["component"],
        "series_id": source["series_id"],
        "begin_utc": source["begin_utc"],
        "end_utc": source["end_utc"],
        "role": source["role"],
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
        "hash_verified": True,
        "attempt_count": record["attempt_count"],
        "failed_attempts": record["failed_attempts"],
        "source_terms": source["source_terms"],
        "source_terms_url": source["source_terms_url"],
        **retrieval,
    }


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != planner.CWMS_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/cwms-data/timeseries"
    ):
        raise ValueError("stage39_url_outside_allowlist")


def _validate_output(path: Path) -> Path:
    output = path.resolve()
    expected = DEFAULT_OUTPUT.resolve()
    if output != expected:
        raise ValueError("stage39_output_must_match_frozen_root")
    return output


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage39_timezone_required")
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
        raise ValueError("stage39_json_object_required")
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
