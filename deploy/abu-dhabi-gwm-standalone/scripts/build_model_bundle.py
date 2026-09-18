#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


EVENT_ID = "noaa-isd-ae-202404151200-0327"
MODEL_RELEASE_ID = "GWM-R1-20260914"
BUNDLE_SCHEMA = "gwm.abu_dhabi_flood.inference_bundle.v1"
EXPECTED_MODEL_SCHEMA = "gwm.abu_dhabi_flood.five_year_event_emulator.v1"
EXPECTED_MODEL_NAME = "cellwise_ridge_rainfall_conditioned_dynamics"
GRID_CRS = "EPSG:32640"
GRID_CELL_SIZE_M = 250.0


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the compact Abu Dhabi GWM inference bundle.")
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--label-root", type=Path, required=True)
    parser.add_argument("--observation-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def event_duration_hours(event: dict[str, Any]) -> int:
    start = datetime.fromisoformat(str(event["start_utc"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(event["end_utc"]).replace("Z", "+00:00"))
    duration = (end - start).total_seconds() / 3600.0
    if duration <= 0.0 or not duration.is_integer():
        raise ValueError("Default event duration must be a positive whole number of hours")
    return int(duration)


def main() -> None:
    args = parse_args()
    model_root = args.model_root.expanduser().resolve()
    label_root = args.label_root.expanduser().resolve()
    observation_root = args.observation_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Output directory must be absent or empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    model_receipt_path = model_root / "run_receipt.json"
    model_card_path = model_root / "gwm_model_card.json"
    split_path = model_root / "split_manifest.json"
    coefficient_path = model_root / "five_year_full_train_cellwise_ridge_coefficients.npz"
    batch_path = label_root / "batch_manifest.json"
    event_root = label_root / "events" / EVENT_ID
    event_receipt_path = event_root / "run_receipt.json"
    observation_receipt_path = observation_root / "run_receipt.json"

    model_receipt = read_json(model_receipt_path)
    model_card = read_json(model_card_path)
    split = read_json(split_path)
    batch = read_json(batch_path)
    event_receipt = read_json(event_receipt_path)
    observation_receipt = read_json(observation_receipt_path)

    external_events = (model_receipt.get("events") or {}).get("external_test_2024_april")
    if (
        model_receipt.get("status") != "completed"
        or (model_receipt.get("conclusion") or {}).get("external_test_is_reported_only") is not True
        or external_events != [EVENT_ID]
        or EVENT_ID in set((model_receipt.get("events") or {}).get("train", []))
        or model_card.get("schema") != EXPECTED_MODEL_SCHEMA
        or model_card.get("model_name") != EXPECTED_MODEL_NAME
        or split.get("event_disjoint") is not True
        or split.get("external_holdout_excluded_from_training") is not True
    ):
        raise SystemExit("Frozen model contract validation failed")

    selection = (batch.get("selection") or {}).get("events") or []
    selected_event = next(
        (item for item in selection if isinstance(item, dict) and item.get("event_id") == EVENT_ID),
        None,
    )
    if (
        not isinstance(selected_event, dict)
        or selected_event.get("external_holdout") is not True
        or selected_event.get("split") != "external_test_2024_april"
        or event_receipt.get("status") != "completed"
        or event_receipt.get("quality_passed") is not True
    ):
        raise SystemExit("Default event contract validation failed")
    base_duration = event_duration_hours(selected_event)
    depth_name = (event_receipt.get("outputs") or {}).get("depth_labels")
    if not isinstance(depth_name, str) or Path(depth_name).name != depth_name:
        raise SystemExit("Event depth-label asset is invalid")
    depth_path = event_root / depth_name

    observation_event = observation_receipt.get("event") or {}
    evaluation = observation_receipt.get("external_evaluation") or {}
    forcing_name = evaluation.get("forcing_with_zero_rain_tail")
    if (
        observation_receipt.get("status") != "completed"
        or observation_receipt.get("quality_passed") is not True
        or observation_event.get("event_id") != EVENT_ID
        or observation_event.get("external_holdout") is not True
        or observation_event.get("training_forbidden") is not True
        or not isinstance(forcing_name, str)
        or Path(forcing_name).name != forcing_name
    ):
        raise SystemExit("External forcing contract validation failed")
    forcing_path = observation_root / forcing_name
    forcing = read_json(forcing_path)
    hourly_raw = forcing.get("hourly_precipitation_mm")
    if not isinstance(hourly_raw, list) or len(hourly_raw) < base_duration:
        raise SystemExit("Default forcing is invalid")
    hourly = [float(value) for value in hourly_raw]
    tail_hours = len(hourly) - base_duration
    base_total = float(sum(hourly[:base_duration]))
    if (
        forcing.get("event_id") != EVENT_ID
        or tail_hours < 0
        or any(not math.isfinite(value) or value < 0.0 for value in hourly)
        or any(value > 1e-12 for value in hourly[base_duration:])
        or base_total <= 0.0
    ):
        raise SystemExit("Default forcing rainfall contract validation failed")

    try:
        with np.load(coefficient_path, allow_pickle=False) as archive:
            coefficients = np.asarray(archive["coefficients"], dtype=np.float64)
            coefficient_land = np.asarray(archive["land_mask"], dtype=bool)
        with np.load(depth_path, allow_pickle=False) as archive:
            x = np.asarray(archive["x"], dtype=np.float64)
            y = np.asarray(archive["y"], dtype=np.float64)
            land = np.asarray(archive["land_mask"], dtype=bool)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit("Model or grid NPZ validation failed") from error
    if (
        land.shape != (len(y) - 1, len(x) - 1)
        or coefficients.shape != (land.size, 4)
        or not np.array_equal(coefficient_land.reshape(-1), land.reshape(-1))
        or not np.allclose(np.diff(x), GRID_CELL_SIZE_M)
        or not np.allclose(np.diff(y), -GRID_CELL_SIZE_M)
    ):
        raise SystemExit("Model coefficient and grid contract mismatch")

    output_coefficients = output_dir / "coefficients.npz"
    output_grid = output_dir / "grid_250m.npz"
    output_forcing = output_dir / "default_forcing.json"
    output_card = output_dir / "model_card.json"
    output_provenance = output_dir / "provenance.json"
    shutil.copyfile(coefficient_path, output_coefficients)
    np.savez_compressed(output_grid, x=x, y=y, land_mask=land)
    write_json(
        output_forcing,
        {
            "schema": "gwm.abu_dhabi_flood.default_forcing.v1",
            "profile_id": EVENT_ID,
            "hourly_precipitation_mm": hourly,
            "base_rainfall_duration_hours": base_duration,
            "post_rainfall_tail_hours": tail_hours,
        },
    )
    write_json(output_card, model_card)
    write_json(
        output_provenance,
        {
            "schema": "gwm.abu_dhabi_flood.inference_provenance.v1",
            "source_artifacts": {
                "model_run_receipt.json": sha256(model_receipt_path),
                "gwm_model_card.json": sha256(model_card_path),
                "split_manifest.json": sha256(split_path),
                "coefficients.npz": sha256(coefficient_path),
                "batch_manifest.json": sha256(batch_path),
                "default_event_run_receipt.json": sha256(event_receipt_path),
                "default_event_depth_labels.npz": sha256(depth_path),
                "external_observation_run_receipt.json": sha256(observation_receipt_path),
                "external_evaluation_forcing.json": sha256(forcing_path),
            },
            "external_holdout_excluded_from_training": True,
            "default_profile_is_training_forbidden": True,
        },
    )
    files = {
        path.name: sha256(path)
        for path in [output_coefficients, output_grid, output_forcing, output_card, output_provenance]
    }
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "status": "ready",
        "model": {
            "release_id": MODEL_RELEASE_ID,
            "schema": EXPECTED_MODEL_SCHEMA,
            "name": EXPECTED_MODEL_NAME,
            "coefficients_file": output_coefficients.name,
            "training_event_count": len((model_receipt.get("events") or {}).get("train", [])),
            "validation_event_count": len((model_receipt.get("events") or {}).get("validation", [])),
            "blind_test_event_count": len((model_receipt.get("events") or {}).get("test", [])),
            "external_holdout_event_count": len(external_events),
            "target": model_card.get("target"),
            "terrain": model_card.get("terrain"),
        },
        "grid": {
            "grid_file": output_grid.name,
            "crs": GRID_CRS,
            "cell_size_m": GRID_CELL_SIZE_M,
            "rows": int(land.shape[0]),
            "columns": int(land.shape[1]),
            "land_cell_count": int(land.sum()),
        },
        "default_profile": {
            "profile_id": EVENT_ID,
            "forcing_file": output_forcing.name,
            "external_holdout": True,
            "training_forbidden": True,
            "start_utc": selected_event["start_utc"],
            "end_utc": selected_event["end_utc"],
            "base_total_precipitation_mm": base_total,
            "maximum_total_precipitation_mm": base_total * 3.0,
            "base_rainfall_duration_hours": base_duration,
            "post_rainfall_tail_hours": tail_hours,
            "minimum_rainfall_duration_hours": 1,
            "maximum_rainfall_duration_hours": 72,
        },
        "files": files,
        "claim_boundary": (
            "Frozen five-year research GWM rainfall amount-and-duration sensitivity inference. "
            "It emulates 250 m physical-model labels and is not an engineering replacement for the physical solver, "
            "a calibrated arbitrary design hyetograph, historical replay, or external validation result."
        ),
    }
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps({"output_dir": str(output_dir), "files": files, "manifest": manifest}, indent=2))


if __name__ == "__main__":
    main()
