#!/usr/bin/env python3
"""Shared label-safe Runtime-R2 helpers for V3 prediction adapters."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
SUBMISSION_CONTRACT_PATH = DRAFT_ROOT / "submission_contract.json"
BUNDLE_ROOT = DRAFT_ROOT / "phase_a_bundle"
BUNDLE_MANIFEST_PATH = BUNDLE_ROOT / "bundle_manifest.json"
KEY_COLUMNS = ["region_id", "node_id", "target_year"]
PROBABILITY_COLUMNS = [f"probability_{index}" for index in range(9)]
SUBMISSION_COLUMNS = KEY_COLUMNS + PROBABILITY_COLUMNS


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(payload: Any) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relative_path(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT))


def artifact(path: Path, *, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative_path(path),
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def runtime_environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for package in ("numpy", "pandas", "pyarrow", "rasterio", "torch"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = "not-installed"
    return {
        "schema": "gwm_bench.runtime_r2_environment.v1",
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_name": Path(sys.executable).name,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": packages,
        "thread_environment": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
    }


def peak_memory_bytes() -> int:
    maximum_resident_set = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(maximum_resident_set)
    return int(maximum_resident_set * 1024)


def target_files(protocol: dict[str, Any]) -> list[Path]:
    target_root = REPO_ROOT / protocol["dataset"]["phase_c_target_root"]
    if not target_root.exists():
        return []
    return sorted(path for path in target_root.rglob("*") if path.is_file())


def enforce_label_firewall(protocol: dict[str, Any]) -> dict[str, Any]:
    files = target_files(protocol)
    if files:
        raise RuntimeError(
            "v3_label_firewall_violation_target_files_exist_before_commitment"
        )
    target_root = REPO_ROOT / protocol["dataset"]["phase_c_target_root"]
    return {
        "target_root": str(target_root.relative_to(REPO_ROOT)),
        "target_root_exists": target_root.exists(),
        "target_file_count": 0,
        "target_pixels_read": False,
        "target_labels_visible_to_adapter": False,
        "passed": True,
    }


def load_prediction_contract() -> tuple[dict[str, Any], pd.DataFrame]:
    contract = load_json(SUBMISSION_CONTRACT_PATH)
    keys = pd.read_parquet(BUNDLE_ROOT / "submission_keys.parquet")
    keys = keys.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    return contract, keys


def validate_submission(
    frame: pd.DataFrame,
    *,
    contract: dict[str, Any],
    expected_keys: pd.DataFrame,
) -> pd.DataFrame:
    if list(frame.columns) != contract["columns"]:
        raise ValueError("prediction_columns_do_not_match_submission_contract")
    frame = frame.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    if len(frame) != int(contract["expected_row_count"]):
        raise ValueError("prediction_row_count_mismatch")
    if frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("prediction_contains_duplicate_keys")
    if not frame[KEY_COLUMNS].equals(expected_keys[KEY_COLUMNS]):
        raise ValueError("prediction_keys_do_not_match_frozen_submission_keys")
    probability = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(probability).all():
        raise ValueError("prediction_contains_non_finite_probability")
    lower, upper = contract["probability_range"]
    if np.any((probability < lower) | (probability > upper)):
        raise ValueError("prediction_probability_out_of_range")
    if not np.allclose(
        probability.sum(axis=1),
        float(contract["probability_row_sum"]),
        atol=float(contract["absolute_tolerance"]),
        rtol=0.0,
    ):
        raise ValueError("prediction_probability_rows_do_not_sum_to_one")
    return frame


def prediction_summary(
    frame: pd.DataFrame, origin: pd.DataFrame
) -> dict[str, Any]:
    origin_class = origin.set_index(["region_id", "node_id"])["land_class_2022"]
    predicted = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64).argmax(axis=1)
    keyed = frame[KEY_COLUMNS].copy()
    keyed["predicted_class"] = predicted
    keyed["origin_class"] = [
        int(origin_class.loc[(row.region_id, row.node_id)])
        for row in keyed.itertuples(index=False)
    ]
    prior = keyed.sort_values(KEY_COLUMNS, kind="mergesort").copy()
    prior["previous_class"] = prior.groupby(
        ["region_id", "node_id"], sort=False
    )["predicted_class"].shift(1)
    prior.loc[prior["target_year"] == 2023, "previous_class"] = prior.loc[
        prior["target_year"] == 2023, "origin_class"
    ]
    return {
        "row_count": len(frame),
        "region_count": int(frame["region_id"].nunique()),
        "node_count": int(
            frame[["region_id", "node_id"]].drop_duplicates().shape[0]
        ),
        "target_years": sorted(frame["target_year"].unique().tolist()),
        "argmax_class_counts": {
            str(index): int((predicted == index).sum()) for index in range(9)
        },
        "argmax_change_from_2022_by_year": {
            str(int(year)): int(
                (group["predicted_class"] != group["origin_class"]).sum()
            )
            for year, group in keyed.groupby("target_year", sort=True)
        },
        "argmax_step_change_by_year": {
            str(int(year)): int(
                (group["predicted_class"] != group["previous_class"]).sum()
            )
            for year, group in prior.groupby("target_year", sort=True)
        },
    }
