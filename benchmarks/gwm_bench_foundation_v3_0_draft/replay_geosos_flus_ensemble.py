#!/usr/bin/env python3
"""Replay all GeoSOS FLUS seed members and the V3 ensemble."""

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
from run_geosos_flus_ensemble import SEEDS, run


PREDICTION_ROOT = DRAFT_ROOT / "predictions/geosos_flus_three_seed_ensemble"
DEFAULT_OUTPUT = PREDICTION_ROOT / "replay_report.json"


def _compare(path: Path, replay_path: Path, *, name: str) -> dict[str, Any]:
    committed = pd.read_parquet(path)
    replayed = pd.read_parquet(replay_path)
    checks = {
        "prediction_file_sha256_equal": sha256_file(path)
        == sha256_file(replay_path),
        "columns_equal": list(committed.columns) == list(replayed.columns),
        "keys_and_order_equal": committed.iloc[:, :3].equals(
            replayed.iloc[:, :3]
        ),
        "probability_values_bitwise_equal": np.array_equal(
            committed[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64),
            replayed[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64),
        ),
    }
    return {
        "member": name,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "committed_prediction_sha256": sha256_file(path),
        "replayed_prediction_sha256": sha256_file(replay_path),
        "row_count": len(committed),
    }


def replay(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    started = time.perf_counter()
    protocol = load_json(PROTOCOL_PATH)
    firewall_before = enforce_label_firewall(protocol)
    required = [PREDICTION_ROOT / "prediction.parquet"] + [
        PREDICTION_ROOT / "members" / f"seed_{seed}" / "prediction.parquet"
        for seed in SEEDS
    ]
    if any(not path.is_file() for path in required):
        raise FileNotFoundError("flus_committed_prediction_or_seed_member_missing")
    with tempfile.TemporaryDirectory(
        prefix=".gwm-v3-flus-replay-", dir=DRAFT_ROOT
    ) as name:
        replay_root = Path(name) / "geosos_flus_three_seed_ensemble"
        run(output_root=replay_root)
        members = [
            _compare(
                PREDICTION_ROOT
                / "members"
                / f"seed_{seed}"
                / "prediction.parquet",
                replay_root
                / "members"
                / f"seed_{seed}"
                / "prediction.parquet",
                name=f"seed_{seed}",
            )
            for seed in SEEDS
        ]
        ensemble = _compare(
            PREDICTION_ROOT / "prediction.parquet",
            replay_root / "prediction.parquet",
            name="three_seed_ensemble",
        )
        model_spec_equal = sha256_file(PREDICTION_ROOT / "model_spec.json") == (
            sha256_file(replay_root / "model_spec.json")
        )
        source_manifest_equal = sha256_file(
            PREDICTION_ROOT / "source_manifest.json"
        ) == sha256_file(replay_root / "source_manifest.json")
    firewall_after = enforce_label_firewall(protocol)
    all_results = [*members, ensemble]
    passed = (
        all(row["status"] == "PASS" for row in all_results)
        and model_spec_equal
        and source_manifest_equal
    )
    report = {
        "schema": "gwm_bench.runtime_r2_replay.v1",
        "suite_id": protocol["suite_id"],
        "scope": "geosos_flus_all_seed_members",
        "status": (
            "PASS_SEED_COMPLETE_REPLAY_LABEL_FIREWALL_INTACT"
            if passed
            else "FAIL_FLUS_REPLAY"
        ),
        "created_at": utc_now(),
        "members": members,
        "ensemble": ensemble,
        "model_spec_sha256_equal": model_spec_equal,
        "source_manifest_sha256_equal": source_manifest_equal,
        "label_firewall": {
            "before": firewall_before,
            "after": firewall_after,
            "target_pixels_read": False,
        },
        "wall_time_seconds": time.perf_counter() - started,
    }
    write_json_atomic(report, output_path)
    if not passed:
        raise RuntimeError(report["status"])
    print(report["status"])
    for row in all_results:
        print(f"{row['member']}: {row['committed_prediction_sha256']}")
    print(f"report: {output_path}")
    return report


if __name__ == "__main__":
    replay()
