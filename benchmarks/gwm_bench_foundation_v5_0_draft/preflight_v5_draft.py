#!/usr/bin/env python3
"""Validate that the frozen V5 definition is locally feasible before rc1 build."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
OUTPUT_PATH = DRAFT_ROOT / "preflight_report.json"
TARGETS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
AUDIT_COLUMNS = [
    "date",
    "zone_id",
    "event_audit_only",
    "policy_date_audit_only",
    "is_post_policy_audit_only",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source(protocol: dict[str, Any], basename: str) -> Path:
    for group in ("event_panels", "od_panels"):
        for row in protocol["source_assets"][group]:
            path = REPO_ROOT / row["path"]
            if path.name == basename:
                return path
    raise KeyError(basename)


def main() -> int:
    protocol = load_json(PROTOCOL_PATH)
    checks: dict[str, bool] = {}
    checks["protocol_schema"] = protocol["schema"] == "gwm_bench.foundation_v5_suite_protocol.v1"
    checks["protocol_frozen_before_bundle"] = (
        protocol["status"] == "defined_before_v5_bundle_or_model_execution"
    )
    checks["four_events_defined"] = len(protocol["events"]) == 4
    checks["four_outer_folds_defined"] = len(protocol["outer_folds"]) == 4
    checks["new_download_not_required"] = protocol["source_assets"]["new_download_required"] is False
    checks["claim_rejects_analyst_blindness"] = any(
        "analyst-unseen" in value for value in protocol["claim_boundary"]["does_not_support"]
    )
    checks["completion_does_not_require_model_win"] = (
        protocol["completion_definition"]["model_win_required"] is False
    )

    source_audits: list[dict[str, Any]] = []
    for group in ("event_panels", "od_panels"):
        for row in protocol["source_assets"][group]:
            path = REPO_ROOT / row["path"]
            exists = path.is_file()
            checks[f"source_exists::{path.name}"] = exists
            checks[f"source_size::{path.name}"] = exists and path.stat().st_size == row["bytes"]
            checks[f"source_hash::{path.name}"] = exists and sha256_file(path) == row["sha256"]
            if exists:
                source_audits.append(
                    {
                        "path": row["path"],
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )

    v4_path = REPO_ROOT / protocol["v4_evidence_boundary"]["v4_result_path"]
    v4 = load_json(v4_path)
    checks["v4_result_hash_bound"] = (
        sha256_file(v4_path) == protocol["v4_evidence_boundary"]["v4_result_sha256"]
    )
    checks["v4_action_transfer_not_supported"] = v4["status"] == "ACTION_TRANSFER_NOT_SUPPORTED"
    checks["v4_best_baseline_confirmed"] = (
        min(
            (metrics["primary_macro_pre_event_normalized_mae"], model_id)
            for model_id, metrics in v4["metrics"].items()
            if model_id
            in {
                "fixed_adjacency_spatial_ar",
                "nonspatial_historical_ar",
                "seasonal_persistence_52w",
            }
        )[1]
        == "nonspatial_historical_ar"
    )
    checks["v4_scope_failure_confirmed"] = (
        v4["action_transfer_gate"]["conditions"]["correct_action_beats_cbd_scope_rewire"]
        is False
    )

    event_audits: list[dict[str, Any]] = []
    expected_source_rows = 263 * 64 * 7
    for event in protocol["events"]:
        panel_path = resolve_source(protocol, event["source_panel"])
        columns = [*AUDIT_COLUMNS, *TARGETS, *protocol["scene"]["action_columns"]]
        frame = pd.read_parquet(
            panel_path,
            columns=columns,
            filters=[("event_audit_only", "==", event["source_event"])],
        )
        frame["date"] = pd.to_datetime(frame["date"])
        pre_start = pd.Timestamp(event["pre_window"][0])
        pre_end = pd.Timestamp(event["pre_window"][1])
        post_start = pd.Timestamp(event["post_window"][0])
        post_end = pd.Timestamp(event["post_window"][1])
        window = frame.loc[frame["date"].between(pre_start, post_end)].copy()
        pre = window.loc[window["date"].between(pre_start, pre_end)]
        post = window.loc[window["date"].between(post_start, post_end)]
        prefix = event["event_id"]
        checks[f"{prefix}::policy_date"] = (
            pd.Timestamp(frame["policy_date_audit_only"].iloc[0])
            == pd.Timestamp(event["effective_date"])
        )
        checks[f"{prefix}::window_is_contiguous"] = pre_end + pd.Timedelta(days=1) == post_start
        checks[f"{prefix}::52_pre_weeks"] = pre["date"].nunique() == 364
        checks[f"{prefix}::12_post_weeks"] = post["date"].nunique() == 84
        checks[f"{prefix}::263_zones"] = window["zone_id"].nunique() == 263
        checks[f"{prefix}::complete_window_rows"] = len(window) == expected_source_rows
        checks[f"{prefix}::no_duplicate_date_zone"] = not window.duplicated(["date", "zone_id"]).any()
        checks[f"{prefix}::complete_daily_zone_grid"] = bool(
            window.groupby("date", observed=True)["zone_id"].nunique().eq(263).all()
        )
        target_values = window[TARGETS].to_numpy(dtype=np.float64)
        action_values = window[protocol["scene"]["action_columns"]].to_numpy(dtype=np.float64)
        checks[f"{prefix}::finite_nonnegative_targets"] = bool(
            np.isfinite(target_values).all() and (target_values >= 0).all()
        )
        checks[f"{prefix}::finite_actions"] = bool(np.isfinite(action_values).all())
        checks[f"{prefix}::post_action_nonzero"] = bool(
            post["expected_total_delta_usd"].to_numpy(dtype=float).max() > 0
        )

        od_path = resolve_source(protocol, event["od_panel"])
        dataset = ds.dataset(od_path, format="parquet")
        expression = (ds.field("date") >= pre_start.to_datetime64()) & (
            ds.field("date") <= pre_end.to_datetime64()
        )
        od_pre_rows = int(dataset.count_rows(filter=expression))
        checks[f"{prefix}::pre_action_od_available"] = od_pre_rows > 0
        event_audits.append(
            {
                "event_id": event["event_id"],
                "source_event": event["source_event"],
                "effective_date": event["effective_date"],
                "window_rows": len(window),
                "pre_days": pre["date"].nunique(),
                "post_days": post["date"].nunique(),
                "zones": window["zone_id"].nunique(),
                "pre_action_od_rows": od_pre_rows,
                "post_expected_total_delta_range": [
                    float(post["expected_total_delta_usd"].min()),
                    float(post["expected_total_delta_usd"].max()),
                ],
            }
        )

    fold_test_events = [fold["test_event"] for fold in protocol["outer_folds"]]
    event_ids = [event["event_id"] for event in protocol["events"]]
    checks["each_event_held_out_exactly_once"] = sorted(fold_test_events) == sorted(event_ids)
    checks["three_training_events_per_fold"] = all(
        len(fold["training_events"]) == 3
        and fold["test_event"] not in fold["training_events"]
        and set(fold["training_events"]) == set(event_ids) - {fold["test_event"]}
        for fold in protocol["outer_folds"]
    )
    checks["frozen_expected_total_week_rows"] = (
        protocol["split_contract"]["expected_total_event_week_rows"] == 67328
    )
    checks["frozen_expected_outer_test_keys"] = (
        protocol["split_contract"]["expected_total_outer_test_keys"] == 12624
    )
    free_bytes = shutil.disk_usage(REPO_ROOT).free
    checks["disk_has_one_gib_free"] = free_bytes >= 1024**3

    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v5_preflight.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_V5_DRAFT_READY_FOR_RC1" if passed else "FAIL",
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "check_count": len(checks),
        "checks": checks,
        "source_audits": source_audits,
        "event_audits": event_audits,
        "disk_free_bytes": free_bytes,
        "new_download_required": False,
        "next_permitted_action": (
            "Materialize four event-week bundles and four outer-fold firewalls."
            if passed
            else "Resolve failed preflight checks before any V5 model execution."
        ),
    }
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V5.0 preflight: {report['status']}")
    print(f"Preflight report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
