#!/usr/bin/env python3
"""Prepare frozen zero-rain-tail forcings for supplementary physics replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from scripts.extract_abu_dhabi_gwm_confirmatory_sentinel2_batch import build_forcing
except ModuleNotFoundError:
    from extract_abu_dhabi_gwm_confirmatory_sentinel2_batch import build_forcing


WORKSPACE = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821"
)
DEFAULT_ROOT = WORKSPACE / "customer_gwm_supplementary_external_validation_20260917_v1"
DEFAULT_COHORT = DEFAULT_ROOT / "frozen_supplementary_final_cohort_v1.json"
DEFAULT_ERA5 = Path(
    "/Users/zhouning/Downloads/阿布扎比/公开降雨逐时格点_ERA5_1983_2025/"
    "era5_hourly_event_grid.parquet"
)
DEFAULT_OUTPUT = DEFAULT_ROOT / "observations_final_v1"
COHORT_SCHEMA = "gwm.abu_dhabi_flood.supplementary_final_cohort.v1"
SCHEMA = "gwm.abu_dhabi_flood.supplementary_physics_inputs.v1"


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
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _parse(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("supplementary_physics_datetime_timezone_missing")
    return result.astimezone(UTC)


def run(args: argparse.Namespace) -> dict[str, Any]:
    cohort_path = args.cohort.expanduser().resolve()
    era5_path = args.era5.expanduser().resolve()
    output = args.output.expanduser().resolve()
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    if cohort.get("schema") != COHORT_SCHEMA or cohort.get("status") != (
        "frozen_before_supplementary_model_outputs"
    ):
        raise ValueError("supplementary_physics_cohort_invalid")
    hourly = pd.read_parquet(era5_path)
    era5_sha256 = _sha256(era5_path)
    events: list[dict[str, Any]] = []
    for event in cohort["events"]:
        event_id = str(event["event_id"])
        forcing = build_forcing(
            hourly,
            event,
            source_path=era5_path,
            source_sha256=era5_sha256,
        )
        start = _parse(str(forcing["start_utc"]))
        observation = _parse(str(event["observation_datetime_utc"]))
        offset_seconds = (observation - start).total_seconds()
        if offset_seconds <= 0:
            raise ValueError(f"supplementary_physics_observation_precedes_event:{event_id}")
        base_hourly = [float(value) for value in forcing["hourly_precipitation_mm"]]
        target_hours = max(len(base_hourly), math.ceil(offset_seconds / 3600.0))
        extended = {
            **forcing,
            "hourly_precipitation_mm": base_hourly
            + [0.0] * (target_hours - len(base_hourly)),
            "purpose": (
                "frozen supplementary external evaluation only; forbidden from GWM training"
            ),
            "observation_source": event["observation_source"],
            "satellite_observation_utc": observation.isoformat().replace("+00:00", "Z"),
            "satellite_observation_time_seconds_from_event_start": offset_seconds,
            "nearest_300_second_model_frame_seconds": round(offset_seconds / 300.0) * 300,
            "zero_rainfall_tail_hours": target_hours - len(base_hourly),
            "supplementary_cohort_freeze_sha256": cohort["freeze_sha256"],
        }
        event_root = output / event_id
        forcing_path = event_root / "satellite_overpass_external_evaluation_forcing.json"
        _write(forcing_path, extended)
        compatibility_receipt = {
            "schema": "gwm.abu_dhabi_flood.supplementary_observation_compatibility.v1",
            "status": "completed",
            "event_id": event_id,
            "pixel_qc_passed": True,
            "observation_source": event["observation_source"],
            "observation_receipt": event["observation_receipt"],
            "observation_250m": event["observation_250m"],
            "forcing": {"path": str(forcing_path), "sha256": _sha256(forcing_path)},
            "model_outputs_accessed": False,
        }
        compatibility_receipt["receipt_sha256"] = _canonical_sha256(
            compatibility_receipt
        )
        _write(event_root / "run_receipt.json", compatibility_receipt)
        events.append(
            {
                "event_id": event_id,
                "status": "completed",
                "pixel_qc_passed": True,
                "observation_source": event["observation_source"],
                "observation_datetime_utc": event["observation_datetime_utc"],
                "forcing_path": str(forcing_path),
                "forcing_sha256": _sha256(forcing_path),
                "simulation_duration_hours": offset_seconds / 3600.0,
                "zero_rainfall_tail_hours": target_hours - len(base_hourly),
            }
        )
    batch: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "completed",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "cohort": {
            "path": str(cohort_path),
            "sha256": _sha256(cohort_path),
            "freeze_sha256": cohort["freeze_sha256"],
        },
        "events": events,
        "counts": {"selected": len(events), "pixel_qc_passed": len(events)},
        "claim_boundary": cohort["claim_boundary"],
        "model_outputs_accessed": False,
    }
    batch["receipt_sha256"] = _canonical_sha256(batch)
    _write(output / "batch_receipt.json", batch)
    return batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--era5", type=Path, default=DEFAULT_ERA5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args)
    print(
        json.dumps(
            {
                "status": result["status"],
                "counts": result["counts"],
                "events": result["events"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
