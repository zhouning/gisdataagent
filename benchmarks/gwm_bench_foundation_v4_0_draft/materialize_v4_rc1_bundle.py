#!/usr/bin/env python3
"""Materialize the frozen action-aligned weekly bundle for GWM Benchmark V4."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
OUTPUT_ROOT = DRAFT_ROOT / "rc1_bundle"
EVENT_PANEL_PATH = (
    REPO_ROOT
    / "paper-output/regimeworld-nyc-v4-compositional-uwm/results/development_event_panel.parquet"
)
GRAPH_LEDGER_PATH = REPO_ROOT / "paper-output/regimeworld-nyc-v1/results/graph_ledger.json"

STATE_COLUMNS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
METADATA_COLUMNS = ["Borough", "Zone", "service_zone", "cbd_exposure"]
EVENTS = {
    "development_2019_congestion_surcharge": {
        "event_id": "train_2019_nys_congestion_surcharge",
        "role": "training_and_development",
        "effective_date": "2019-02-02",
        "start": "2018-02-03",
        "end": "2019-04-26",
    },
    "development_2022_taximeter_adjustment": {
        "event_id": "train_2022_tlc_taximeter_adjustment",
        "role": "training_and_development",
        "effective_date": "2022-12-19",
        "start": "2021-12-20",
        "end": "2023-03-12",
    },
    "development_2025_crz": {
        "event_id": "test_2025_mta_crz",
        "role": "model_unseen_test_intervention",
        "effective_date": "2025-01-05",
        "start": "2024-01-07",
        "end": "2025-03-29",
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, row_count: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if row_count is not None:
        payload["row_count"] = row_count
    return payload


def _relative_week(dates: pd.Series, effective: pd.Timestamp) -> pd.Series:
    delta = (dates - effective).dt.days.to_numpy(dtype=np.int64)
    values = np.where(delta < 0, np.floor_divide(delta, 7), np.floor_divide(delta, 7) + 1)
    return pd.Series(values.astype(np.int16), index=dates.index)


def _week_start(relative_week: int, effective: pd.Timestamp) -> pd.Timestamp:
    offset = relative_week * 7 if relative_week < 0 else (relative_week - 1) * 7
    return effective + pd.Timedelta(days=offset)


def _aggregate_event(
    source: pd.DataFrame,
    source_event: str,
    spec: dict[str, str],
    action_columns: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    effective = pd.Timestamp(spec["effective_date"])
    selected = source.loc[
        source["event_audit_only"].eq(source_event)
        & source["date"].between(spec["start"], spec["end"])
    ].copy()
    expected_days = 64 * 7
    expected_rows = 263 * expected_days
    if selected["date"].nunique() != expected_days or len(selected) != expected_rows:
        raise ValueError(
            f"{source_event}: expected {expected_days} days and {expected_rows} rows, "
            f"found {selected['date'].nunique()} days and {len(selected)} rows"
        )
    if selected["zone_id"].nunique() != 263:
        raise ValueError(f"{source_event}: expected 263 zones")
    if selected.duplicated(["date", "zone_id"]).any():
        raise ValueError(f"{source_event}: duplicate date-zone rows")

    selected["relative_week"] = _relative_week(selected["date"], effective)
    expected_relative_weeks = list(range(-52, 0)) + list(range(1, 13))
    actual_relative_weeks = sorted(selected["relative_week"].unique().tolist())
    if actual_relative_weeks != expected_relative_weeks:
        raise ValueError(f"{source_event}: relative-week coverage mismatch")
    cells_per_week = selected.groupby("relative_week", observed=True).size()
    if not (cells_per_week == 263 * 7).all():
        raise ValueError(f"{source_event}: incomplete zone-day week")

    action_cardinality = selected.groupby(
        ["relative_week", "zone_id"], observed=True
    )[action_columns].nunique(dropna=False)
    if int(action_cardinality.to_numpy().max()) != 1:
        raise ValueError(f"{source_event}: action values change within a zone-week")

    aggregation: dict[str, str] = {column: "sum" for column in STATE_COLUMNS}
    aggregation.update({column: "first" for column in METADATA_COLUMNS})
    aggregation.update({column: "first" for column in action_columns})
    weekly = (
        selected.groupby(["relative_week", "zone_id"], observed=True, as_index=False)
        .agg(aggregation)
        .sort_values(["relative_week", "zone_id"])
        .reset_index(drop=True)
    )
    weekly["event_id_audit_only"] = spec["event_id"]
    weekly["event_role_audit_only"] = spec["role"]
    weekly["effective_date_audit_only"] = effective
    weekly["week_start"] = weekly["relative_week"].map(
        lambda value: _week_start(int(value), effective)
    )
    weekly["week_end"] = weekly["week_start"] + pd.Timedelta(days=6)
    weekly["is_post_action_audit_only"] = weekly["relative_week"].gt(0)
    ordered = [
        "event_id_audit_only",
        "event_role_audit_only",
        "effective_date_audit_only",
        "relative_week",
        "week_start",
        "week_end",
        "is_post_action_audit_only",
        "zone_id",
        *METADATA_COLUMNS,
        *STATE_COLUMNS,
        *action_columns,
    ]
    weekly = weekly[ordered]
    audit = {
        "source_event": source_event,
        "event_id": spec["event_id"],
        "role": spec["role"],
        "effective_date": spec["effective_date"],
        "source_date_min": selected["date"].min().strftime("%Y-%m-%d"),
        "source_date_max": selected["date"].max().strftime("%Y-%m-%d"),
        "source_zone_day_rows": len(selected),
        "weekly_rows": len(weekly),
        "pre_week_count": int(weekly.loc[weekly["relative_week"].lt(0), "relative_week"].nunique()),
        "post_week_count": int(weekly.loc[weekly["relative_week"].gt(0), "relative_week"].nunique()),
        "zone_count": int(weekly["zone_id"].nunique()),
    }
    return weekly, audit


def _build_graph(graph_ledger: dict[str, Any], zone_metadata: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for edge in graph_ledger["adjacency_edges"]:
        rows.append(
            {
                "source_zone": int(edge["source"]),
                "target_zone": int(edge["target"]),
                "relation": "geographic_adjacency",
                "weight": float(edge["weight"]),
            }
        )
    for edge in graph_ledger["od_edges"]:
        rows.append(
            {
                "source_zone": int(edge["source"]),
                "target_zone": int(edge["target"]),
                "relation": "origin_destination_flow",
                "weight": float(edge["weight"]),
            }
        )
    for row in zone_metadata.itertuples(index=False):
        rows.append(
            {
                "source_zone": int(row.zone_id),
                "target_zone": int(row.zone_id),
                "relation": "action_exposure",
                "weight": float(row.cbd_exposure),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["relation", "source_zone", "target_zone"]
    ).reset_index(drop=True)


def main() -> int:
    protocol = _load_json(PROTOCOL_PATH)
    action_columns = protocol["action_contract"]["numeric_features"]
    source_columns = [
        "date",
        "zone_id",
        "event_audit_only",
        *METADATA_COLUMNS,
        *STATE_COLUMNS,
        *action_columns,
    ]
    source = pd.read_parquet(EVENT_PANEL_PATH, columns=source_columns)
    source["date"] = pd.to_datetime(source["date"])
    weekly_parts: dict[str, pd.DataFrame] = {}
    event_audits: list[dict[str, Any]] = []
    for source_event, spec in EVENTS.items():
        weekly, audit = _aggregate_event(source, source_event, spec, action_columns)
        weekly_parts[source_event] = weekly
        event_audits.append(audit)

    development = pd.concat(
        [
            weekly_parts["development_2019_congestion_surcharge"],
            weekly_parts["development_2022_taximeter_adjustment"],
        ],
        ignore_index=True,
    )
    test_all = weekly_parts["development_2025_crz"]
    test_history = test_all.loc[test_all["relative_week"].lt(0)].copy()
    test_post = test_all.loc[test_all["relative_week"].gt(0)].copy()
    test_action = test_post[
        [
            "zone_id",
            "relative_week",
            "week_start",
            "week_end",
            "cbd_exposure",
            *action_columns,
        ]
    ].rename(columns={"relative_week": "horizon_week"})
    test_targets = test_post[
        ["zone_id", "relative_week", "week_start", "week_end", *STATE_COLUMNS]
    ].rename(columns={"relative_week": "horizon_week"})
    submission_keys = test_targets[["zone_id", "horizon_week"]].copy()

    zone_metadata = (
        test_history[["zone_id", *METADATA_COLUMNS]]
        .drop_duplicates()
        .sort_values("zone_id")
        .reset_index(drop=True)
    )
    if len(zone_metadata) != 263:
        raise ValueError("expected 263 unique zone metadata rows")
    graph = _build_graph(_load_json(GRAPH_LEDGER_PATH), zone_metadata)

    expected_counts = protocol["dataset"]["derived_row_counts"]
    observed_counts = {
        "development_rows": len(development),
        "test_history_rows": len(test_history),
        "test_action_rows": len(test_action),
        "test_target_rows": len(test_targets),
        "submission_key_rows": len(submission_keys),
        "zone_metadata_rows": len(zone_metadata),
        "graph_edge_rows": len(graph),
    }
    expected_observed = {
        "development_rows": expected_counts["training_zone_week_rows"],
        "test_history_rows": expected_counts["test_input_zone_week_rows"],
        "test_action_rows": expected_counts["test_target_zone_week_rows"],
        "test_target_rows": expected_counts["test_target_zone_week_rows"],
        "submission_key_rows": protocol["submission_contract"]["expected_key_count"],
        "zone_metadata_rows": 263,
        "graph_edge_rows": 692 + 2054 + 263,
    }
    if observed_counts != expected_observed:
        raise ValueError(f"bundle row-count mismatch: {observed_counts} != {expected_observed}")
    if development["week_end"].max() >= pd.Timestamp("2025-01-05"):
        raise ValueError("development bundle contains a 2025 post-action row")
    if test_history["week_end"].max() != pd.Timestamp("2025-01-04"):
        raise ValueError("test history does not end immediately before the action")
    if test_targets["week_start"].min() != pd.Timestamp("2025-01-05"):
        raise ValueError("test targets do not begin on the action boundary")
    if submission_keys.duplicated().any():
        raise ValueError("duplicate submission keys")

    development_path = OUTPUT_ROOT / "development" / "weekly_state_action.parquet"
    test_history_path = OUTPUT_ROOT / "test_input" / "weekly_state_history.parquet"
    test_action_path = OUTPUT_ROOT / "test_input" / "future_action_spec.parquet"
    key_path = OUTPUT_ROOT / "test_input" / "submission_keys.parquet"
    target_path = OUTPUT_ROOT / "test_targets" / "weekly_targets.parquet"
    zone_path = OUTPUT_ROOT / "graph" / "zone_metadata.parquet"
    graph_path = OUTPUT_ROOT / "graph" / "spatial_edges.parquet"
    for path in (
        development_path,
        test_history_path,
        test_action_path,
        key_path,
        target_path,
        zone_path,
        graph_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    development.to_parquet(development_path, index=False)
    test_history.to_parquet(test_history_path, index=False)
    test_action.to_parquet(test_action_path, index=False)
    submission_keys.to_parquet(key_path, index=False)
    test_targets.to_parquet(target_path, index=False)
    zone_metadata.to_parquet(zone_path, index=False)
    graph.to_parquet(graph_path, index=False)

    training_manifest = {
        "schema": "gwm_bench.foundation_v4_training_row_manifest.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "permitted_event_ids": sorted(development["event_id_audit_only"].unique().tolist()),
        "source_date_min": development["week_start"].min().strftime("%Y-%m-%d"),
        "source_date_max": development["week_end"].max().strftime("%Y-%m-%d"),
        "weekly_rows": len(development),
        "zone_count": int(development["zone_id"].nunique()),
        "post_2025_action_rows": int(
            development["week_start"].ge(pd.Timestamp("2025-01-05")).sum()
        ),
        "normalization_may_read_test_targets": False,
        "graph_may_read_test_targets": False,
        "test_target_path_permitted_for_model_runtime": False,
        "artifact": _artifact(development_path, len(development)),
    }
    training_manifest_path = OUTPUT_ROOT / "development" / "training_row_manifest.json"
    _write_json(training_manifest_path, training_manifest)

    manifest = {
        "schema": "gwm_bench.foundation_v4_rc1_bundle.v1",
        "suite_id": protocol["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "V4_RC1_DATA_MATERIALIZED",
        "protocol_sha256": _sha256(PROTOCOL_PATH),
        "source_event_panel": _artifact(EVENT_PANEL_PATH),
        "source_graph_ledger": _artifact(GRAPH_LEDGER_PATH),
        "event_audits": event_audits,
        "counts": observed_counts,
        "artifacts": {
            "development": _artifact(development_path, len(development)),
            "training_row_manifest": _artifact(training_manifest_path),
            "test_history": _artifact(test_history_path, len(test_history)),
            "test_action": _artifact(test_action_path, len(test_action)),
            "submission_keys": _artifact(key_path, len(submission_keys)),
            "test_targets": _artifact(target_path, len(test_targets)),
            "zone_metadata": _artifact(zone_path, len(zone_metadata)),
            "spatial_edges": _artifact(graph_path, len(graph)),
        },
        "firewall": {
            "test_targets_written_to_separate_directory": True,
            "test_target_path_permitted_for_model_runtime": False,
            "development_max_date": development["week_end"].max().strftime("%Y-%m-%d"),
            "test_history_max_date": test_history["week_end"].max().strftime("%Y-%m-%d"),
            "test_target_min_date": test_targets["week_start"].min().strftime("%Y-%m-%d"),
            "analyst_blindness_claimed": False,
        },
        "model_input_prohibitions": [
            "event_id_audit_only",
            "event_role_audit_only",
            "effective_date_audit_only",
            "policy name",
            "event year",
        ],
    }
    manifest_path = OUTPUT_ROOT / "bundle_manifest.json"
    _write_json(manifest_path, manifest)
    print("GWM-Bench Foundation V4.0 rc1: V4_RC1_DATA_MATERIALIZED")
    print(f"Bundle manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
