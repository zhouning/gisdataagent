#!/usr/bin/env python3
"""Commit a label-blind, full-grid FLUS forecast through calendar 2026."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1 import (  # noqa: E402
    run_flus_full_grid_observed_baseline as full_grid_runner,
)
from benchmarks.gwm_bench_foundation_v0_1 import (  # noqa: E402
    run_flus_observed_baseline as flus_runner,
)
from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (  # noqa: E402
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
)


RELEASE_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = RELEASE_ROOT / "flus_2026_precommit"
DEFAULT_FLUS_ROOT = Path("/Users/zhouning/FLUS_console_crossplatform")
DEFAULT_SOURCE_ROOT = REPO_ROOT / "data/twm_public_landcover/gee_dynamic_world"
DEFAULT_BUNDLE_ROOT = (
    REPO_ROOT / "benchmarks/gwm_bench_foundation_v0_1/development"
)
HIDDEN_LABEL_MANIFEST = (
    DEFAULT_SOURCE_ROOT / "twm_v2_2026_hidden_label_registration.json"
)
FORECAST_YEARS = tuple(range(2021, 2027))
DEFAULT_SEEDS = (31, 47, 73)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _artifact(path: Path, *, role: str) -> dict[str, Any]:
    path = path.resolve()
    try:
        stored_path = str(path.relative_to(REPO_ROOT))
        path_scope = "repository_relative"
    except ValueError:
        stored_path = str(path)
        path_scope = "external_absolute"
    return {
        "path": stored_path,
        "path_scope": path_scope,
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _prediction_artifact(
    path: Path, *, role: str, row_count: int
) -> dict[str, Any]:
    return {**_artifact(path, role=role), "row_count": row_count}


def _validate_prediction(frame: pd.DataFrame, *, expected_rows: int) -> None:
    if list(frame.columns) != KEY_COLUMNS + PROBABILITY_COLUMNS:
        raise ValueError("flus_2026_prediction_columns_mismatch")
    if len(frame) != expected_rows or frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("flus_2026_prediction_keys_invalid")
    if set(frame["target_year"].astype(int)) != set(FORECAST_YEARS):
        raise ValueError("flus_2026_prediction_years_mismatch")
    probabilities = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(probabilities).all():
        raise ValueError("flus_2026_prediction_has_nonfinite_probability")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise ValueError("flus_2026_prediction_probability_out_of_range")
    if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0.0):
        raise ValueError("flus_2026_prediction_probabilities_do_not_sum_to_one")


def _predicted_2026_changes(frame: pd.DataFrame) -> int:
    bridge = frame[frame["target_year"].isin((2025, 2026))].copy()
    bridge["predicted_class"] = np.argmax(
        bridge[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64), axis=1
    )
    wide = bridge.pivot(
        index=["fold_index", "region_id", "node_id"],
        columns="target_year",
        values="predicted_class",
    )
    if list(wide.columns) != [2025, 2026]:
        raise ValueError("flus_2026_bridge_years_incomplete")
    return int((wide[2026] != wide[2025]).sum())


def _scrub_ephemeral_paths(value: Any, temporary_root: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _scrub_ephemeral_paths(item, temporary_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_ephemeral_paths(item, temporary_root) for item in value]
    if isinstance(value, str) and str(temporary_root) in value:
        return value.replace(str(temporary_root), "<ephemeral_work_root>")
    return value


def _run_member(
    *,
    seed: int,
    output_root: Path,
    bundle_root: Path,
    source_root: Path,
    flus_root: Path,
    sample_per_mille: float,
    max_iterations: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    member_root = output_root / f"seed_{seed}"
    member_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"gwm-flus-2026-{seed}-") as raw_temp:
        temporary_root = Path(raw_temp)
        temporary_output = temporary_root / "run"
        report = full_grid_runner.run_flus_full_grid_observed_baseline(
            bundle_root=bundle_root,
            source_root=source_root,
            output_root=temporary_output,
            flus_root=flus_root,
            seed=seed,
            sample_per_mille=sample_per_mille,
            max_iterations=max_iterations,
            evaluate=False,
        )
        if report["evaluation"] is not None:
            raise ValueError("flus_2026_member_opened_labels")
        source_prediction = (
            temporary_output / "flus_full_grid_observed_submission.parquet"
        )
        destination_prediction = member_root / "prediction_2021_2026.parquet"
        shutil.copy2(source_prediction, destination_prediction)
        frame = pd.read_parquet(destination_prediction)
        expected_rows = 1055 * len(FORECAST_YEARS)
        _validate_prediction(frame, expected_rows=expected_rows)
        audit = _scrub_ephemeral_paths(report, temporary_root)
        audit["schema"] = "gwm_bench.flus_2026_member_precommit.v1"
        audit["status"] = "flus_2026_member_committed_without_labels"
        audit["forecast_years"] = list(FORECAST_YEARS)
        audit["work_artifacts_retained"] = False
        audit["artifacts"] = {
            "prediction": _prediction_artifact(
                destination_prediction,
                role=f"flus_seed_{seed}_prediction_2021_2026",
                row_count=len(frame),
            )
        }
        audit["integrity"] = {
            "evaluation_disabled": True,
            "hidden_label_manifest_present": HIDDEN_LABEL_MANIFEST.is_file(),
            "hidden_label_manifest_accessed": False,
            "hidden_label_pixels_accessed": False,
            "maximum_observed_input_year": 2020,
        }
        audit_path = member_root / "run_report.json"
        _write_json(audit, audit_path)
    return frame, {
        "seed": seed,
        "predicted_2026_change_count": _predicted_2026_changes(frame),
        "prediction": _prediction_artifact(
            destination_prediction,
            role=f"flus_seed_{seed}_prediction_2021_2026",
            row_count=len(frame),
        ),
        "run_report": _artifact(
            audit_path, role=f"flus_seed_{seed}_label_blind_run_report"
        ),
    }


def _load_completed_member(
    *, seed: int, output_root: Path
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    member_root = output_root / f"seed_{seed}"
    prediction_path = member_root / "prediction_2021_2026.parquet"
    report_path = member_root / "run_report.json"
    if not prediction_path.is_file() and not report_path.is_file():
        return None
    if not prediction_path.is_file() or not report_path.is_file():
        raise ValueError(f"incomplete_existing_flus_2026_member:{seed}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "flus_2026_member_committed_without_labels":
        raise ValueError(f"invalid_existing_flus_2026_member_report:{seed}")
    if int(report["method"]["seed"]) != seed:
        raise ValueError(f"existing_flus_2026_member_seed_mismatch:{seed}")
    if report["integrity"] != {
        "evaluation_disabled": True,
        "hidden_label_manifest_present": False,
        "hidden_label_manifest_accessed": False,
        "hidden_label_pixels_accessed": False,
        "maximum_observed_input_year": 2020,
    }:
        raise ValueError(f"existing_flus_2026_member_integrity_mismatch:{seed}")
    expected_artifact = report["artifacts"]["prediction"]
    if (
        prediction_path.stat().st_size != int(expected_artifact["size_bytes"])
        or _sha256(prediction_path) != expected_artifact["sha256"]
    ):
        raise ValueError(f"existing_flus_2026_member_hash_mismatch:{seed}")
    frame = pd.read_parquet(prediction_path)
    _validate_prediction(frame, expected_rows=1055 * len(FORECAST_YEARS))
    return frame, {
        "seed": seed,
        "predicted_2026_change_count": _predicted_2026_changes(frame),
        "prediction": _prediction_artifact(
            prediction_path,
            role=f"flus_seed_{seed}_prediction_2021_2026",
            row_count=len(frame),
        ),
        "run_report": _artifact(
            report_path, role=f"flus_seed_{seed}_label_blind_run_report"
        ),
    }


def _ensemble(frames: list[pd.DataFrame]) -> pd.DataFrame:
    ordered = [
        frame.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        for frame in frames
    ]
    expected_keys = ordered[0][KEY_COLUMNS]
    for frame in ordered[1:]:
        if not frame[KEY_COLUMNS].equals(expected_keys):
            raise ValueError("flus_2026_member_keys_mismatch")
    probabilities = np.mean(
        [frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64) for frame in ordered],
        axis=0,
    )
    result = expected_keys.copy()
    result[PROBABILITY_COLUMNS] = probabilities
    _validate_prediction(result, expected_rows=1055 * len(FORECAST_YEARS))
    return result


def commit_flus_2026_forecast(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    flus_root: Path = DEFAULT_FLUS_ROOT,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    sample_per_mille: float = 10.0,
    max_iterations: int = 500,
) -> dict[str, Any]:
    if HIDDEN_LABEL_MANIFEST.is_file():
        raise RuntimeError("refusing_flus_precommit_after_hidden_label_registration")
    if len(seeds) < 2 or len(set(seeds)) != len(seeds):
        raise ValueError("flus_2026_requires_multiple_unique_seeds")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    # The existing full-grid runner is reused unchanged; only its rollout horizon
    # is extended before any function reads data or invokes the FLUS binary.
    full_grid_runner.TARGET_YEARS = FORECAST_YEARS
    flus_runner.TARGET_YEARS = FORECAST_YEARS

    frames = []
    members = []
    for seed in seeds:
        completed = _load_completed_member(seed=seed, output_root=output_root)
        if completed is None:
            frame, member = _run_member(
                seed=seed,
                output_root=output_root,
                bundle_root=bundle_root.resolve(),
                source_root=source_root.resolve(),
                flus_root=flus_root.resolve(),
                sample_per_mille=sample_per_mille,
                max_iterations=max_iterations,
            )
            completion = "completed"
        else:
            frame, member = completed
            completion = "reused"
        frames.append(frame)
        members.append(member)
        print(
            f"{completion} FLUS 2026 precommit seed={seed} "
            f"changes={member['predicted_2026_change_count']}",
            flush=True,
        )

    ensemble = _ensemble(frames)
    prediction_path = output_root / "flus_prediction_2021_2026.parquet"
    temporary = prediction_path.with_suffix(".parquet.tmp")
    ensemble.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(prediction_path)

    binary = flus_root.resolve() / "build/cmake-release/flus_console"
    source_paths = [
        Path(__file__),
        Path(full_grid_runner.__file__),
        Path(flus_runner.__file__),
        REPO_ROOT / "benchmarks/gwm_bench_foundation_v0_1/observed_evaluator.py",
    ]
    input_paths = [
        REPO_ROOT / "benchmarks/gwm_bench_foundation_v0_1/benchmark_contract.json",
        bundle_root.resolve() / "bundle_manifest.json",
        bundle_root.resolve() / "region_folds.json",
        bundle_root.resolve() / "observed_train.parquet",
        bundle_root.resolve() / "observed_inputs.parquet",
    ]
    protocol = {
        "schema": "gwm_bench.flus_2026_candidate_precommit.v1",
        "protocol_id": "FLUS-FULL-GRID-TEMPORAL-2026-PRECOMMIT-v1",
        "status": "flus_candidate_and_predictions_sealed_before_2026_labels",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "forecast_origin_year": 2020,
        "forecast_years": list(FORECAST_YEARS),
        "scored_year": 2026,
        "scored_region_count": 20,
        "scored_node_count": 1055,
        "candidate": {
            "name": "GeoSOS FLUS full-grid three-seed ensemble",
            "seeds": list(seeds),
            "sample_per_mille": sample_per_mille,
            "max_iterations_per_region_year": max_iterations,
            "allocation_grid": "complete aligned 100 m source raster",
            "evaluation_grid": "frozen 1,055 OBSERVED-O1 nodes",
            "land_demand": (
                "fold-training 2017-2020 transition matrix recursively applied "
                "from each test region's 2020 full-grid class counts"
            ),
        },
        "artifacts": {
            "prediction": _prediction_artifact(
                prediction_path,
                role="precommitted_flus_prediction_2021_2026",
                row_count=len(ensemble),
            ),
            "members": members,
            "binary": _artifact(binary, role="flus_console_binary"),
            "source": [
                _artifact(path, role=f"source_{index}")
                for index, path in enumerate(source_paths)
            ],
            "inputs": [
                _artifact(path, role=f"input_{index}")
                for index, path in enumerate(input_paths)
            ],
        },
        "prediction_summary": {
            "row_count": len(ensemble),
            "predicted_2026_change_count": _predicted_2026_changes(ensemble),
            "member_predicted_2026_change_counts": {
                str(row["seed"]): row["predicted_2026_change_count"]
                for row in members
            },
        },
        "integrity": {
            "maximum_observed_input_year": 2020,
            "evaluation_disabled_for_all_members": True,
            "hidden_label_manifest_present": False,
            "hidden_label_manifest_accessed": False,
            "hidden_label_pixels_accessed": False,
            "prediction_hash_committed_before_labels": True,
            "post_commit_model_or_parameter_changes_allowed": False,
        },
        "claim_boundary": {
            "prospective_2026_flus_baseline_committed": True,
            "prospective_2026_flus_score_available": False,
            "published_flus_best_score_reproduced": False,
            "general_twm_supported": False,
            "general_gwm_supported": False,
        },
    }
    fingerprint_material = json.dumps(
        {
            "candidate": protocol["candidate"],
            "prediction": protocol["artifacts"]["prediction"],
            "members": protocol["artifacts"]["members"],
            "binary": protocol["artifacts"]["binary"],
            "source": protocol["artifacts"]["source"],
            "inputs": protocol["artifacts"]["inputs"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    protocol["candidate_fingerprint"] = hashlib.sha256(
        fingerprint_material
    ).hexdigest()
    protocol_path = output_root / "precommit_protocol.json"
    _write_json(protocol, protocol_path)
    print(
        json.dumps(
            {
                "status": protocol["status"],
                "prediction_sha256": protocol["artifacts"]["prediction"]["sha256"],
                "prediction_rows": len(ensemble),
                "predicted_2026_change_count": protocol["prediction_summary"][
                    "predicted_2026_change_count"
                ],
                "protocol": str(protocol_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return protocol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--flus-root", type=Path, default=DEFAULT_FLUS_ROOT)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--sample-per-mille", type=float, default=10.0)
    parser.add_argument("--max-iterations", type=int, default=500)
    args = parser.parse_args()
    commit_flus_2026_forecast(
        output_root=args.output_root,
        bundle_root=args.bundle_root,
        source_root=args.source_root,
        flus_root=args.flus_root,
        seeds=tuple(args.seeds),
        sample_per_mille=args.sample_per_mille,
        max_iterations=args.max_iterations,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
