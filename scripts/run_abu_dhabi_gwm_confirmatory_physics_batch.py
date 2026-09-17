#!/usr/bin/env python3
"""Replay physics to Sentinel-2 overpasses for the confirmatory GWM cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_confirmatory_external_validation_20260916_v1"
)
DEFAULT_OBSERVATIONS = DEFAULT_ROOT / "observations"
DEFAULT_RUNNER = REPOSITORY_ROOT / "scripts/run_abu_dhabi_five_year_2d_coupled_labels.py"
DEFAULT_PYTHON = REPOSITORY_ROOT / "external_models/anuga-venv/bin/python"
DEFAULT_IMPLEMENTATION_ROOT = REPOSITORY_ROOT
SCHEMA = "gwm.abu_dhabi_flood.confirmatory_physics_batch.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"confirmatory_physics_json_invalid:{path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def select_pixel_qc_events(batch_receipt: dict[str, Any]) -> list[dict[str, Any]]:
    events = batch_receipt.get("events")
    if not isinstance(events, list):
        raise ValueError("confirmatory_physics_observation_batch_invalid")
    return [
        event
        for event in events
        if event.get("status") == "completed" and event.get("pixel_qc_passed") is True
    ]


def _completed_receipt(path: Path, event_id: str, runner_sha256: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    receipt = _read_json(path)
    if (
        receipt.get("status") == "completed"
        and receipt.get("quality_passed") is True
        and receipt.get("event", {}).get("event_id") == event_id
        and receipt.get("event", {}).get("split") == "evaluation_only"
        and receipt.get("implementation", {}).get("runner_sha256") == runner_sha256
    ):
        return receipt
    return None


def _run_one(
    event: dict[str, Any],
    *,
    observation_root: Path,
    output_root: Path,
    runner: Path,
    python_executable: Path,
    implementation_root: Path,
    runner_sha256: str,
) -> dict[str, Any]:
    event_id = str(event["event_id"])
    forcing = observation_root / event_id / "satellite_overpass_external_evaluation_forcing.json"
    observation_receipt = observation_root / event_id / "run_receipt.json"
    event_output = output_root / event_id
    receipt_path = event_output / "run_receipt.json"
    completed = _completed_receipt(receipt_path, event_id, runner_sha256)
    if completed is not None:
        return {
            "event_id": event_id,
            "status": "skipped_completed",
            "quality_passed": True,
            "elapsed_seconds": 0.0,
            "receipt_path": str(receipt_path),
            "receipt_sha256": _sha256(receipt_path),
            "depth_labels": str(event_output / completed["outputs"]["depth_labels"]),
        }
    if not forcing.is_file() or not observation_receipt.is_file():
        raise FileNotFoundError(f"confirmatory_physics_observation_assets_missing:{event_id}")
    event_output.mkdir(parents=True, exist_ok=True)
    command = [
        str(python_executable),
        str(runner),
        "--forcing",
        str(forcing),
        "--output",
        str(event_output),
        "--event-split",
        "evaluation_only",
        "--implementation-root",
        str(implementation_root),
    ]
    started = time.monotonic()
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    elapsed = round(time.monotonic() - started, 3)
    receipt = _read_json(receipt_path) if receipt_path.is_file() else {}
    if process.returncode != 0 or receipt.get("status") != "completed":
        return {
            "event_id": event_id,
            "status": "failed",
            "quality_passed": bool(receipt.get("quality_passed", False)),
            "elapsed_seconds": elapsed,
            "returncode": int(process.returncode),
            "failure_type": receipt.get("failure_type"),
            "failure_reason": receipt.get("failure_reason"),
            "stdout": process.stdout[-4000:],
            "stderr": process.stderr[-4000:],
        }
    return {
        "event_id": event_id,
        "status": "completed",
        "quality_passed": bool(receipt["quality_passed"]),
        "elapsed_seconds": elapsed,
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha256(receipt_path),
        "depth_labels": str(event_output / receipt["outputs"]["depth_labels"]),
        "maximum_depth_m": receipt["outputs"]["maximum_depth_m"],
        "inundated_area_ge_0_01m2": receipt["outputs"]["inundated_area_ge_0_01m2"],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    observation_root = args.observation_root.expanduser().resolve()
    observation_batch_path = observation_root / "batch_receipt.json"
    output_root = args.output.expanduser().resolve()
    runner = args.runner.expanduser().resolve()
    python_executable = Path(args.python_executable).expanduser().absolute()
    implementation_root = args.implementation_root.expanduser().resolve()
    observation_batch = _read_json(observation_batch_path)
    events = select_pixel_qc_events(observation_batch)
    if len(events) < args.minimum_events:
        raise ValueError("confirmatory_physics_event_count_below_minimum")
    for path in (runner, python_executable):
        if not path.is_file():
            raise FileNotFoundError(f"confirmatory_physics_runtime_missing:{path}")
    if not implementation_root.is_dir():
        raise FileNotFoundError(
            f"confirmatory_physics_implementation_root_missing:{implementation_root}"
        )
    runner_sha256 = _sha256(runner)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema": args.batch_schema,
        "status": "running",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "selection": {
            "rule": args.selection_rule,
            "event_ids": [event["event_id"] for event in events],
            "event_count": len(events),
            "confirmatory_target_event_count": args.confirmatory_target_events,
            "confirmatory_sample_size_sufficient": (
                len(events) >= args.confirmatory_target_events
            ),
        },
        "inputs": {
            "observation_batch": str(observation_batch_path),
            "observation_batch_sha256": _sha256(observation_batch_path),
            "runner": str(runner),
            "runner_sha256": runner_sha256,
            "implementation_root": str(implementation_root),
        },
        "execution": {
            "mode": "independent_event_subprocesses",
            "max_workers": args.max_workers,
            "event_split": "evaluation_only",
        },
        "events": [],
    }
    manifest_path = output_root / "batch_receipt.json"
    _write_json(manifest_path, manifest)
    results: list[dict[str, Any]] = []
    order = {str(event["event_id"]): index for index, event in enumerate(events)}
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                _run_one,
                event,
                observation_root=observation_root,
                output_root=output_root,
                runner=runner,
                python_executable=python_executable,
                implementation_root=implementation_root,
                runner_sha256=runner_sha256,
            ): str(event["event_id"])
            for event in events
        }
        for future in as_completed(futures):
            event_id = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {
                    "event_id": event_id,
                    "status": "failed",
                    "failure_type": type(error).__name__,
                    "failure_reason": str(error),
                }
            results.append(result)
            results.sort(key=lambda item: order[item["event_id"]])
            manifest["events"] = results
            _write_json(manifest_path, manifest)
            print(f"{event_id}: {result['status']}", flush=True)
    manifest["events"] = sorted(results, key=lambda item: order[item["event_id"]])
    failures = sum(result["status"] == "failed" for result in results)
    manifest["counts"] = {
        "selected": len(events),
        "completed_or_reused": len(events) - failures,
        "failed": failures,
        "quality_passed": sum(result.get("quality_passed") is True for result in results),
    }
    manifest["status"] = (
        "completed_underpowered"
        if failures == 0 and len(events) < args.confirmatory_target_events
        else "completed"
        if failures == 0
        else "completed_with_failures"
    )
    manifest["receipt_sha256"] = _canonical_sha256(manifest)
    _write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation-root", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "physics")
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--python-executable", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument(
        "--implementation-root", type=Path, default=DEFAULT_IMPLEMENTATION_ROOT
    )
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--minimum-events", type=int, default=3)
    parser.add_argument("--confirmatory-target-events", type=int, default=3)
    parser.add_argument("--batch-schema", default=SCHEMA)
    parser.add_argument(
        "--selection-rule",
        default="completed Sentinel-2 extraction with frozen pixel_qc_passed=true",
    )
    args = parser.parse_args()
    if (
        args.max_workers <= 0
        or args.minimum_events <= 0
        or args.confirmatory_target_events < args.minimum_events
    ):
        raise ValueError("confirmatory_physics_workers_invalid")
    result = run(args)
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
