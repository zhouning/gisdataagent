#!/usr/bin/env python3
"""Independently replay V3 internal baselines and compare sealed bytes."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from prediction_runtime import (
    DRAFT_ROOT,
    PROBABILITY_COLUMNS,
    PROTOCOL_PATH,
    enforce_label_firewall,
    load_json,
    sha256_file,
    utc_now,
    write_json_atomic,
)
from run_internal_baselines import run


PREDICTION_ROOT = DRAFT_ROOT / "predictions"
MODEL_IDS = (
    "state_persistence",
    "nonspatial_history_only",
    "fixed_adjacency_spatial",
)
DEFAULT_OUTPUT = PREDICTION_ROOT / "internal_baseline_replay_report.json"


def _compare_model(model_id: str, replay_root: Path) -> dict[str, Any]:
    committed_path = PREDICTION_ROOT / model_id / "prediction.parquet"
    replay_path = replay_root / model_id / "prediction.parquet"
    committed = pd.read_parquet(committed_path)
    replayed = pd.read_parquet(replay_path)
    committed_values = committed[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    replayed_values = replayed[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    checks = {
        "prediction_file_sha256_equal": sha256_file(committed_path)
        == sha256_file(replay_path),
        "columns_equal": list(committed.columns) == list(replayed.columns),
        "keys_and_order_equal": committed.iloc[:, :3].equals(
            replayed.iloc[:, :3]
        ),
        "probability_values_bitwise_equal": np.array_equal(
            committed_values, replayed_values
        ),
        "model_spec_sha256_equal": sha256_file(
            PREDICTION_ROOT / model_id / "model_spec.json"
        )
        == sha256_file(replay_root / model_id / "model_spec.json"),
    }
    return {
        "model_id": model_id,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "committed_prediction_sha256": sha256_file(committed_path),
        "replayed_prediction_sha256": sha256_file(replay_path),
        "row_count": len(committed),
    }


def replay(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    started = time.perf_counter()
    protocol = load_json(PROTOCOL_PATH)
    firewall_before = enforce_label_firewall(protocol)
    for model_id in MODEL_IDS:
        if not (PREDICTION_ROOT / model_id / "prediction.parquet").is_file():
            raise FileNotFoundError(f"missing_committed_prediction:{model_id}")
    with tempfile.TemporaryDirectory(
        prefix=".gwm-v3-baseline-replay-", dir=DRAFT_ROOT
    ) as name:
        replay_root = Path(name) / "predictions"
        run(replay_root)
        models = [_compare_model(model_id, replay_root) for model_id in MODEL_IDS]
    firewall_after = enforce_label_firewall(protocol)
    report = {
        "schema": "gwm_bench.runtime_r2_replay.v1",
        "suite_id": protocol["suite_id"],
        "scope": "three_internal_baselines",
        "status": (
            "PASS_DETERMINISTIC_REPLAY_LABEL_FIREWALL_INTACT"
            if all(model["status"] == "PASS" for model in models)
            else "FAIL_DETERMINISTIC_REPLAY"
        ),
        "created_at": utc_now(),
        "models": models,
        "label_firewall": {
            "before": firewall_before,
            "after": firewall_after,
            "target_pixels_read": False,
        },
        "wall_time_seconds": time.perf_counter() - started,
    }
    write_json_atomic(report, output_path)
    if not report["status"].startswith("PASS"):
        raise RuntimeError(report["status"])
    print(report["status"])
    for model in models:
        print(
            f"{model['model_id']}: {model['committed_prediction_sha256']}",
            flush=True,
        )
    print(f"report: {output_path}")
    return report


if __name__ == "__main__":
    replay()
