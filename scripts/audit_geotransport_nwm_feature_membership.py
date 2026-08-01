#!/usr/bin/env python3
"""Verify NLDI path COMIDs against the NWM v3 feature_id coordinate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
import urllib.error
import urllib.request

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.public_data import (
    DEFAULT_REGISTRY_PATH,
    load_public_data_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH_REPORT = REPO_ROOT / "benchmarks/geotransport_v0_1/nldi_path_crosswalk_report.json"
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_RAW_CHUNK = REPO_ROOT / "data/geotransport_v0_1/nwm/feature_id/0.zst"
DEFAULT_OUTPUT = REPO_ROOT / "benchmarks/geotransport_v0_1/nwm_feature_membership_report.json"
FEATURE_CHUNK_URL = (
    "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
    "CONUS/zarr/chrtout.zarr/feature_id/0"
)
SCHEMA = "gwm.geotransport.nwm_feature_membership.v1"
USER_AGENT = "gisdataagent-geotransport-nwm-membership/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--path-report", type=Path, default=DEFAULT_PATH_REPORT)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--raw-chunk", type=Path, default=DEFAULT_RAW_CHUNK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--reuse-raw", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_public_data_registry(args.registry)
    path_report = _load_json(args.path_report)
    if path_report.get("registry_sha256") != registry.sha256:
        raise ValueError("path_report_registry_hash_mismatch")
    if path_report.get("topology_gate_status") != "pass":
        raise ValueError("admitted_nldi_path_report_required")
    feature_meta_path = args.metadata_root / "nwm-feature-id-zarray.json"
    q_lateral_meta_path = args.metadata_root / "nwm-q-lateral-zarray.json"
    feature_meta = _load_json(feature_meta_path)
    q_lateral_meta = _load_json(q_lateral_meta_path)
    if feature_meta.get("shape") != [2776734] or feature_meta.get("dtype") != "<i8":
        raise ValueError("nwm_feature_coordinate_schema_mismatch")
    if q_lateral_meta.get("shape") != [385704, 2776734]:
        raise ValueError("nwm_q_lateral_shape_mismatch")
    if feature_meta.get("chunks") != [2776734]:
        raise ValueError("nwm_feature_coordinate_chunking_mismatch")
    if args.reuse_raw:
        if not args.raw_chunk.is_file():
            raise FileNotFoundError(args.raw_chunk)
        retrieval = {
            "url": FEATURE_CHUNK_URL,
            "path": _display(args.raw_chunk),
            "sha256": _sha256_file(args.raw_chunk),
            "size_bytes": args.raw_chunk.stat().st_size,
            "reused": True,
        }
    else:
        retrieval = fetch_chunk(
            output=args.raw_chunk,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
    feature_ids = decode_zstd_numpy(
        args.raw_chunk,
        dtype=np.dtype(feature_meta["dtype"]),
        shape=tuple(feature_meta["shape"]),
    )
    if np.unique(feature_ids).size != feature_ids.size:
        raise ValueError("nwm_feature_ids_must_be_unique")
    index_by_id = {int(feature_id): index for index, feature_id in enumerate(feature_ids)}
    feature_chunk_width = int(q_lateral_meta["chunks"][1])
    rows: list[dict[str, Any]] = []
    for path_row in path_report["systems"]:
        path_ids = [int(value) for value in path_row["path"]["feature_ids"]]
        missing = [feature_id for feature_id in path_ids if feature_id not in index_by_id]
        indices = [index_by_id[feature_id] for feature_id in path_ids if feature_id in index_by_id]
        rows.append(
            {
                "system_id": path_row["system_id"],
                "feature_ids": path_ids,
                "feature_indices": indices,
                "missing_feature_ids": missing,
                "q_lateral_feature_chunk_indices": sorted(
                    {index // feature_chunk_width for index in indices}
                ),
                "membership_gate_status": "pass" if not missing else "fail",
            }
        )
    all_pass = all(row["membership_gate_status"] == "pass" for row in rows)
    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry_path": _display(args.registry),
        "registry_sha256": registry.sha256,
        "path_report_path": _display(args.path_report),
        "path_report_sha256": _sha256_file(args.path_report),
        "feature_coordinate_metadata": {
            "path": _display(feature_meta_path),
            "sha256": _sha256_file(feature_meta_path),
            "shape": feature_meta["shape"],
            "dtype": feature_meta["dtype"],
            "chunks": feature_meta["chunks"],
        },
        "q_lateral_metadata": {
            "path": _display(q_lateral_meta_path),
            "sha256": _sha256_file(q_lateral_meta_path),
            "shape": q_lateral_meta["shape"],
            "dtype": q_lateral_meta["dtype"],
            "chunks": q_lateral_meta["chunks"],
        },
        "feature_coordinate_chunk": retrieval,
        "nwm_feature_count": int(feature_ids.size),
        "nwm_feature_ids_unique": True,
        "systems": rows,
        "membership_gate_status": "pass" if all_pass else "fail",
        "claim_boundary": {
            "nldi_path_comids_present_in_nwm_v3": all_pass,
            "q_lateral_values_acquired": False,
            "forcing_feature_ids_written_to_registry": False,
            "benchmark_validated": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0 if all_pass else 2


def fetch_chunk(
    *,
    output: Path,
    proxy: str,
    timeout_seconds: float,
    retries: int,
) -> dict[str, object]:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            FEATURE_CHUNK_URL,
            headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(10_000_001)
                if len(body) > 10_000_000:
                    raise ValueError("nwm_feature_chunk_size_limit_exceeded")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(body)
                return {
                    "url": FEATURE_CHUNK_URL,
                    "http_status": response.status,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "path": _display(output),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "size_bytes": len(body),
                    "attempt_count": attempt,
                    "reused": False,
                }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"nwm_feature_chunk_request_failed:{error}")


def decode_zstd_numpy(
    path: Path,
    *,
    dtype: np.dtype[Any],
    shape: tuple[int, ...],
) -> np.ndarray:
    executable = shutil.which("zstd")
    if executable is None:
        raise RuntimeError("zstd_executable_required")
    result = subprocess.run(
        [executable, "--decompress", "--stdout", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    expected_bytes = int(np.prod(shape)) * dtype.itemsize
    if len(result.stdout) != expected_bytes:
        raise ValueError("decoded_nwm_feature_chunk_size_mismatch")
    return np.frombuffer(result.stdout, dtype=dtype).reshape(shape)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
