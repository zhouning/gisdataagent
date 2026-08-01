#!/usr/bin/env python3
"""Plan or acquire bounded NWM q_lateral chunks for admitted transport paths."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    NWM_Q_LATERAL_EXTRACT_SCHEMA,
    build_nwm_q_lateral_plan,
    extract_nwm_q_lateral,
    load_nwm_zarr_schema,
    load_public_data_registry,
    nwm_chunk_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_OUTPUT = REPO_ROOT / "data/geotransport_v0_1/nwm_q_lateral"
ALLOWED_HOST = "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com"
USER_AGENT = "gisdataagent-geotransport-nwm-q-lateral/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--system", action="append", required=True, dest="systems")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--accept-modeled-forcing", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-hours", type=int, default=744)
    parser.add_argument("--max-q-chunks", type=int, default=32)
    parser.add_argument(
        "--reuse-raw-manifest",
        type=Path,
        help="Reuse already verified raw chunks; missing chunks fail without download.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.retries <= 0 or args.max_hours <= 0 or args.max_q_chunks <= 0:
        raise ValueError("positive_extraction_limits_required")
    registry = load_public_data_registry(args.registry)
    schema = load_nwm_zarr_schema(args.metadata_root)
    if len(args.systems) != len(set(args.systems)):
        raise ValueError("nwm_systems_must_be_unique")
    plans = tuple(
        build_nwm_q_lateral_plan(
            registry,
            schema,
            system_id=system_id,
            start=args.start,
            end=args.end,
        )
        for system_id in args.systems
    )
    if any(plan.time_count > args.max_hours for plan in plans):
        raise ValueError("nwm_extraction_max_hours_exceeded")
    time_chunk_indices = sorted(
        {index for plan in plans for index in plan.time_chunk_indices}
    )
    q_chunk_keys = sorted({key for plan in plans for key in plan.q_chunk_keys})
    if len(q_chunk_keys) > args.max_q_chunks:
        raise ValueError("nwm_extraction_max_q_chunks_exceeded")
    manifest: dict[str, Any] = {
        "schema": NWM_Q_LATERAL_EXTRACT_SCHEMA,
        "mode": "plan" if args.plan_only else "values",
        "registry_path": _display(args.registry),
        "registry_sha256": registry.sha256,
        "metadata_root": _display(args.metadata_root),
        "metadata_sha256": dict(schema.metadata_sha256),
        "start_inclusive": plans[0].start.isoformat(),
        "end_exclusive": plans[0].end.isoformat(),
        "systems": [_plan_payload(plan) for plan in plans],
        "time_chunk_urls": [nwm_chunk_url("time", str(index)) for index in time_chunk_indices],
        "q_lateral_chunk_urls": [
            nwm_chunk_url("q_lateral", f"{time_index}.{feature_index}")
            for time_index, feature_index in q_chunk_keys
        ],
        "limits": {
            "max_hours_per_system": args.max_hours,
            "max_q_chunks": args.max_q_chunks,
            "planned_q_chunk_count": len(q_chunk_keys),
        },
        "source_semantics": {
            "source": "noaa_nwm_v3_retrospective",
            "variable": "q_lateral",
            "role": "modeled_forcing",
            "modeled": True,
            "ground_truth": False,
            "streamflow_used": False,
            "units": "m3 s-1",
        },
        "claim_boundary": {
            "request_plan_only": args.plan_only,
            "modeled_forcing_values_acquired": not args.plan_only,
            "observed_forcing_acquired": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
            "raw_chunks_reused_without_download": (
                args.reuse_raw_manifest is not None and not args.plan_only
            ),
        },
    }
    if args.reuse_raw_manifest is not None:
        reuse_body = args.reuse_raw_manifest.read_bytes()
        manifest["raw_chunk_lineage"] = {
            "path": _display(args.reuse_raw_manifest),
            "sha256": hashlib.sha256(reuse_body).hexdigest(),
            "size_bytes": len(reuse_body),
        }
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plan_only:
        output = args.output / "extraction_plan.json"
        _write_json(output, manifest)
        print(output)
        return 0
    if not args.accept_modeled_forcing:
        raise ValueError("nwm_values_require_accept_modeled_forcing")

    time_bodies: dict[int, bytes] = {}
    q_bodies: dict[tuple[int, int], bytes] = {}
    artifacts: list[dict[str, Any]] = []
    if args.reuse_raw_manifest is not None:
        reused = load_reused_raw_chunks(
            args.reuse_raw_manifest,
            time_chunk_indices=tuple(time_chunk_indices),
            q_chunk_keys=tuple(q_chunk_keys),
        )
        time_bodies.update(reused[0])
        q_bodies.update(reused[1])
        artifacts.extend(reused[2])
    else:
        opener = _opener(args.proxy)
        for index in time_chunk_indices:
            url = nwm_chunk_url("time", str(index))
            body, retrieval = _fetch_chunk(
                url,
                opener=opener,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                maximum_bytes=1_000_000,
            )
            path = args.output / "raw/time" / f"{index}.zst"
            artifacts.append(_save_artifact(path, body, retrieval, variable="time"))
            time_bodies[index] = body
        for time_index, feature_index in q_chunk_keys:
            key = f"{time_index}.{feature_index}"
            url = nwm_chunk_url("q_lateral", key)
            body, retrieval = _fetch_chunk(
                url,
                opener=opener,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                maximum_bytes=100_000_000,
            )
            path = args.output / "raw/q_lateral" / f"{key}.zst"
            artifacts.append(
                _save_artifact(path, body, retrieval, variable="q_lateral")
            )
            q_bodies[(time_index, feature_index)] = body

    value_artifacts: list[dict[str, Any]] = []
    result_summaries: list[dict[str, Any]] = []
    for plan in plans:
        result = extract_nwm_q_lateral(
            plan,
            schema,
            time_chunks={index: time_bodies[index] for index in plan.time_chunk_indices},
            q_chunks={key: q_bodies[key] for key in plan.q_chunk_keys},
        )
        path = args.output / "values" / f"{plan.system_id}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["timestamp_utc", "feature_id", "q_lateral_m3s", "source_role"]
            )
            for row, timestamp in enumerate(result.timestamps):
                for column, feature_id in enumerate(result.feature_ids):
                    value = result.values_m3s[row, column]
                    writer.writerow(
                        [
                            timestamp,
                            feature_id,
                            "" if math.isnan(value) else format(value, ".10g"),
                            result.variable_role,
                        ]
                    )
        value_artifacts.append(_local_artifact(path, variable="q_lateral_values"))
        result_summaries.append(
            {
                "system_id": result.system_id,
                "time_count": len(result.timestamps),
                "feature_count": len(result.feature_ids),
                "value_count": int(result.values_m3s.size),
                "fill_value_count": result.fill_value_count,
                "output_path": _display(path),
            }
        )
    manifest["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    manifest["raw_chunk_artifacts"] = artifacts
    manifest["value_artifacts"] = value_artifacts
    manifest["results"] = result_summaries
    output = args.output / "extraction_manifest.json"
    _write_json(output, manifest)
    print(output)
    return 0


def _plan_payload(plan: Any) -> dict[str, Any]:
    return {
        "system_id": plan.system_id,
        "time_count": plan.time_count,
        "start_time_index": plan.start_time_index,
        "end_time_index": plan.end_time_index,
        "feature_ids": list(plan.feature_ids),
        "feature_indices": list(plan.feature_indices),
        "time_chunk_indices": list(plan.time_chunk_indices),
        "feature_chunk_indices": list(plan.feature_chunk_indices),
        "q_chunk_keys": [list(key) for key in plan.q_chunk_keys],
    }


def load_reused_raw_chunks(
    manifest_path: Path,
    *,
    time_chunk_indices: tuple[int, ...],
    q_chunk_keys: tuple[tuple[int, int], ...],
) -> tuple[
    dict[int, bytes],
    dict[tuple[int, int], bytes],
    list[dict[str, Any]],
]:
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest.get("schema") != NWM_Q_LATERAL_EXTRACT_SCHEMA
        or manifest.get("mode") != "values"
    ):
        raise ValueError("nwm_reuse_source_manifest_invalid")
    semantics = manifest.get("source_semantics") or {}
    if (
        semantics.get("source") != "noaa_nwm_v3_retrospective"
        or semantics.get("variable") != "q_lateral"
        or semantics.get("ground_truth") is not False
    ):
        raise ValueError("nwm_reuse_source_semantics_invalid")
    descriptors = manifest.get("raw_chunk_artifacts") or []
    by_url = {descriptor.get("url"): descriptor for descriptor in descriptors}
    expected: list[tuple[str, int | tuple[int, int], str]] = []
    expected.extend(
        ("time", index, nwm_chunk_url("time", str(index)))
        for index in time_chunk_indices
    )
    expected.extend(
        (
            "q_lateral",
            key,
            nwm_chunk_url("q_lateral", f"{key[0]}.{key[1]}"),
        )
        for key in q_chunk_keys
    )
    time_bodies: dict[int, bytes] = {}
    q_bodies: dict[tuple[int, int], bytes] = {}
    reused_artifacts: list[dict[str, Any]] = []
    for variable, key, url in expected:
        descriptor = by_url.get(url)
        if not isinstance(descriptor, dict) or descriptor.get("variable") != variable:
            raise ValueError(f"nwm_reuse_required_chunk_missing:{url}")
        path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
        try:
            path.relative_to(REPO_ROOT)
        except ValueError as exc:
            raise ValueError("nwm_reuse_chunk_outside_repository") from exc
        body = path.read_bytes()
        if (
            hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
            or len(body) != descriptor.get("size_bytes")
        ):
            raise ValueError(f"nwm_reuse_chunk_identity_mismatch:{path}")
        reused_artifacts.append({**descriptor, "reused_without_download": True})
        if variable == "time":
            time_bodies[int(key)] = body
        else:
            if not isinstance(key, tuple):
                raise RuntimeError("nwm_reuse_q_chunk_key_invalid")
            q_bodies[key] = body
    return time_bodies, q_bodies, reused_artifacts


def _fetch_chunk(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError("nwm_chunk_url_outside_official_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                    raise ValueError("nwm_chunk_redirect_outside_official_allowlist")
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("nwm_chunk_size_limit_exceeded")
                return body, {
                    "url": url,
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "attempt_count": attempt,
                }
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(f"non_retryable_nwm_http_error:{exc.code}") from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"nwm_chunk_request_failed:{error}")


def _save_artifact(
    path: Path,
    body: bytes,
    retrieval: dict[str, Any],
    *,
    variable: str,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        **retrieval,
        "variable": variable,
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _local_artifact(path: Path, *, variable: str) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "variable": variable,
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
