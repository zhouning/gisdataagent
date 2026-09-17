#!/usr/bin/env python3
"""Extract Sentinel-2 observations for the frozen confirmatory GWM cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path(
    "/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/"
    "customer_gwm_confirmatory_external_validation_20260916_v1"
)
DEFAULT_PROTOCOL = DEFAULT_ROOT / "frozen_event_protocol.json"
DEFAULT_PAIRS = DEFAULT_ROOT / "sentinel2_frozen_pairs.csv"
DEFAULT_SCENE_RECEIPT = DEFAULT_ROOT / "sentinel2_scene_audit_receipt.json"
DEFAULT_ERA5 = Path(
    "/Users/zhouning/Downloads/阿布扎比/公开降雨逐时格点_ERA5_1983_2025/"
    "era5_hourly_event_grid.parquet"
)
DEFAULT_EXTRACTOR = REPOSITORY_ROOT / "scripts/extract_abu_dhabi_sentinel2_observed_flood.py"
SCHEMA = "gwm.abu_dhabi_flood.confirmatory_sentinel2_batch.v1"


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
        raise ValueError(f"confirmatory_sentinel2_json_invalid:{path}")
    return value


def select_optical_cohort(
    events: list[dict[str, Any]],
    pairs: pd.DataFrame,
    target_count: int,
) -> list[dict[str, Any]]:
    pair_by_id = {
        str(row.event_id): row for row in pairs.sort_values("cohort_order").itertuples(index=False)
    }
    selected: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: int(item["cohort_order"])):
        pair = pair_by_id.get(str(event["event_id"]))
        if pair is None or not bool(pair.sentinel2_pair_admitted):
            continue
        selected.append(
            {
                **event,
                "selected_before_date": str(pair.selected_before_date),
                "selected_after_date": str(pair.selected_after_date),
                "selected_before_datetime_utc": str(pair.selected_before_datetime_utc),
                "selected_after_datetime_utc": str(pair.selected_after_datetime_utc),
            }
        )
        if len(selected) == target_count:
            break
    if len(selected) != target_count:
        raise ValueError("confirmatory_sentinel2_optical_cohort_insufficient")
    return selected


def build_forcing(
    hourly: pd.DataFrame,
    event: dict[str, Any],
    *,
    source_path: Path,
    source_sha256: str,
) -> dict[str, Any]:
    event_id = str(event["event_id"])
    start = pd.Timestamp(event["start_utc"])
    end = pd.Timestamp(event["end_utc"])
    expected = pd.date_range(start, end, freq="1h", inclusive="left")
    subset = hourly[
        hourly["event_id"].astype(str).eq(event_id)
        & hourly["inside_noaa_event_window"].astype(bool)
    ].copy()
    subset["timestamp"] = pd.to_datetime(subset["timestamp_utc"], utc=True, errors="raise")
    values = (
        subset.groupby("timestamp", sort=True)["precipitation_mm"]
        .mean()
        .reindex(expected, fill_value=0.0)
    )
    if subset.empty or not values.index.equals(expected):
        raise ValueError(f"confirmatory_sentinel2_forcing_invalid:{event_id}")
    return {
        "event_id": event_id,
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "hourly_precipitation_mm": [float(max(value, 0.0)) for value in values],
        "source": "ECMWF ERA5 hourly event grid",
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "support_point_count": int(subset["point_id"].nunique()),
        "aggregation": "mean of nine spatial support points",
        "purpose": "confirmatory external evaluation only; forbidden from GWM training",
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _run_one(
    event: dict[str, Any],
    *,
    extractor: Path,
    python_executable: Path,
    output_root: Path,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    event_id = str(event["event_id"])
    event_root = output_root / event_id
    command = [
        str(python_executable),
        str(extractor),
        "--event-forcing",
        str(event_root / "forcing.json"),
        "--output",
        str(event_root),
        "--before-date",
        str(event["selected_before_date"]),
        "--after-date",
        str(event["selected_after_date"]),
        "--water-threshold",
        str(thresholds["sentinel2_water_threshold"]),
        "--change-threshold",
        str(thresholds["sentinel2_mndwi_change_threshold"]),
        "--minimum-valid-fraction",
        str(thresholds["minimum_250m_paired_valid_fraction"]),
        "--minimum-observed-fraction",
        str(thresholds["minimum_250m_observed_water_fraction"]),
    ]
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    receipt_path = event_root / "run_receipt.json"
    if process.returncode != 0 or not receipt_path.is_file():
        return {
            "event_id": event_id,
            "status": "failed",
            "returncode": int(process.returncode),
            "stdout": process.stdout[-4000:],
            "stderr": process.stderr[-4000:],
        }
    receipt = _read_json(receipt_path)
    observation_path = event_root / str(receipt["outputs"]["observed_flood_250m"])
    with np.load(observation_path) as archive:
        total_cells = int(np.asarray(archive["valid_fraction"]).size)
    valid_cells = int(receipt["outputs"]["valid_250m_cell_count"])
    valid_fraction = valid_cells / total_cells
    pixel_qc_passed = bool(
        receipt.get("quality_passed") is True
        and valid_fraction >= float(thresholds["minimum_evaluable_250m_cell_fraction"])
    )
    return {
        "event_id": event_id,
        "status": "completed",
        "pixel_qc_passed": pixel_qc_passed,
        "valid_250m_cell_count": valid_cells,
        "total_250m_cell_count": total_cells,
        "evaluable_250m_cell_fraction": valid_fraction,
        "observed_new_surface_water_area_m2": receipt["outputs"][
            "observed_new_surface_water_area_m2"
        ],
        "observed_flood_250m_cell_count": receipt["outputs"]["observed_flood_250m_cell_count"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha256(receipt_path),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol_path = args.protocol.expanduser().resolve()
    pairs_path = args.pairs.expanduser().resolve()
    scene_receipt_path = args.scene_receipt.expanduser().resolve()
    era5_path = args.era5.expanduser().resolve()
    extractor = args.extractor.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    python_executable = Path(args.python_executable).expanduser().absolute()
    protocol = _read_json(protocol_path)
    scene_receipt = _read_json(scene_receipt_path)
    if scene_receipt.get("protocol", {}).get("freeze_sha256") != protocol.get("freeze_sha256"):
        raise ValueError("confirmatory_sentinel2_scene_receipt_protocol_mismatch")
    pairs = pd.read_csv(pairs_path)
    target_count = int(protocol["selection"]["primary_event_count"])
    cohort = select_optical_cohort(protocol["events"], pairs, target_count)
    thresholds = {
        **protocol["frozen_satellite_evaluation"],
        "minimum_evaluable_250m_cell_fraction": args.minimum_evaluable_cell_fraction,
    }
    cohort_freeze: dict[str, Any] = {
        "schema": "gwm.abu_dhabi_flood.confirmatory_optical_cohort.v1",
        "status": "frozen_before_pixel_access",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "parent_freeze_sha256": protocol["freeze_sha256"],
        "selection": "admitted primary events followed by admitted backups in frozen order",
        "events": cohort,
        "pixel_quality_thresholds": thresholds,
        "inputs": {
            "protocol_sha256": _sha256(protocol_path),
            "pairs_sha256": _sha256(pairs_path),
            "scene_receipt_sha256": _sha256(scene_receipt_path),
            "era5_sha256": _sha256(era5_path),
            "extractor_sha256": _sha256(extractor),
        },
        "model_outputs_accessed": False,
    }
    cohort_freeze["freeze_sha256"] = _canonical_sha256(cohort_freeze)
    output_root.mkdir(parents=True, exist_ok=True)
    freeze_path = output_root / "frozen_optical_cohort.json"
    if freeze_path.exists():
        existing = _read_json(freeze_path)
        if existing.get("freeze_sha256") != cohort_freeze["freeze_sha256"]:
            raise ValueError("confirmatory_sentinel2_optical_cohort_already_differs")
    else:
        _write_json(freeze_path, cohort_freeze)
    hourly = pd.read_parquet(era5_path)
    era5_sha256 = _sha256(era5_path)
    for event in cohort:
        event_root = output_root / str(event["event_id"])
        forcing = build_forcing(
            hourly,
            event,
            source_path=era5_path,
            source_sha256=era5_sha256,
        )
        _write_json(event_root / "forcing.json", forcing)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                _run_one,
                event,
                extractor=extractor,
                python_executable=python_executable,
                output_root=output_root,
                thresholds=thresholds,
            ): event["event_id"]
            for event in cohort
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result['event_id']}: {result['status']}", flush=True)
    order = {str(event["event_id"]): index for index, event in enumerate(cohort)}
    results.sort(key=lambda item: order[item["event_id"]])
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": (
            "completed"
            if all(result["status"] == "completed" for result in results)
            else "completed_with_failures"
        ),
        "cohort_freeze": {
            "path": str(freeze_path),
            "sha256": _sha256(freeze_path),
            "freeze_sha256": cohort_freeze["freeze_sha256"],
        },
        "execution": {"max_workers": args.max_workers, "model_outputs_accessed": False},
        "events": results,
        "counts": {
            "target_events": len(cohort),
            "completed": sum(result["status"] == "completed" for result in results),
            "pixel_qc_passed": sum(result.get("pixel_qc_passed") is True for result in results),
        },
    }
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    _write_json(output_root / "batch_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--scene-receipt", type=Path, default=DEFAULT_SCENE_RECEIPT)
    parser.add_argument("--era5", type=Path, default=DEFAULT_ERA5)
    parser.add_argument("--extractor", type=Path, default=DEFAULT_EXTRACTOR)
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "observations")
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--minimum-evaluable-cell-fraction", type=float, default=0.70)
    parser.add_argument("--max-workers", type=int, default=2)
    args = parser.parse_args()
    if not 0.0 < args.minimum_evaluable_cell_fraction <= 1.0 or args.max_workers <= 0:
        raise ValueError("confirmatory_sentinel2_batch_arguments_invalid")
    result = run(args)
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
