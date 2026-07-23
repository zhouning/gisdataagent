#!/usr/bin/env python3
"""Materialize four action-aligned events and four V5 outer-fold firewalls."""

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
PREFLIGHT_PATH = DRAFT_ROOT / "preflight_report.json"
OUTPUT_ROOT = DRAFT_ROOT / "rc1_bundle"
V4_ZONE_PATH = REPO_ROOT / "benchmarks/gwm_bench_foundation_v4_0_draft/rc1_bundle/graph/zone_metadata.parquet"
V4_EDGE_PATH = REPO_ROOT / "benchmarks/gwm_bench_foundation_v4_0_draft/rc1_bundle/graph/spatial_edges.parquet"
STATE_COLUMNS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
METADATA_COLUMNS = ["Borough", "Zone", "service_zone", "cbd_exposure"]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, row_count: int | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if row_count is not None:
        row["row_count"] = int(row_count)
    return row


def resolve_source(protocol: dict[str, Any], basename: str) -> Path:
    for group in ("event_panels", "od_panels"):
        for row in protocol["source_assets"][group]:
            path = REPO_ROOT / row["path"]
            if path.name == basename:
                return path
    raise KeyError(basename)


def relative_week(dates: pd.Series, effective: pd.Timestamp) -> pd.Series:
    delta = (dates - effective).dt.days.to_numpy(dtype=np.int64)
    values = np.where(delta < 0, np.floor_divide(delta, 7), np.floor_divide(delta, 7) + 1)
    return pd.Series(values.astype(np.int16), index=dates.index)


def week_start(relative: int, effective: pd.Timestamp) -> pd.Timestamp:
    offset = relative * 7 if relative < 0 else (relative - 1) * 7
    return effective + pd.Timedelta(days=offset)


def aggregate_event(
    frame: pd.DataFrame,
    event: dict[str, Any],
    action_columns: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    effective = pd.Timestamp(event["effective_date"])
    start = pd.Timestamp(event["pre_window"][0])
    end = pd.Timestamp(event["post_window"][1])
    selected = frame.loc[
        frame["event_audit_only"].eq(event["source_event"])
        & frame["date"].between(start, end)
    ].copy()
    expected_days = 64 * 7
    if len(selected) != 263 * expected_days or selected["date"].nunique() != expected_days:
        raise ValueError(f"{event['event_id']}: incomplete 64-week daily grid")
    if selected.duplicated(["date", "zone_id"]).any():
        raise ValueError(f"{event['event_id']}: duplicate daily zone key")
    selected["relative_week"] = relative_week(selected["date"], effective)
    expected_weeks = list(range(-52, 0)) + list(range(1, 13))
    if sorted(selected["relative_week"].unique().tolist()) != expected_weeks:
        raise ValueError(f"{event['event_id']}: relative-week mismatch")
    if not selected.groupby("relative_week", observed=True).size().eq(263 * 7).all():
        raise ValueError(f"{event['event_id']}: incomplete weekly cell")

    aggregation: dict[str, str] = {column: "sum" for column in STATE_COLUMNS}
    aggregation.update({column: "first" for column in METADATA_COLUMNS})
    aggregation.update({column: "mean" for column in action_columns})
    weekly = (
        selected.groupby(["relative_week", "zone_id"], observed=True, as_index=False)
        .agg(aggregation)
        .sort_values(["relative_week", "zone_id"])
        .reset_index(drop=True)
    )
    weekly["event_id_audit_only"] = event["event_id"]
    weekly["source_event_audit_only"] = event["source_event"]
    weekly["effective_date_audit_only"] = effective
    weekly["week_start"] = weekly["relative_week"].map(
        lambda value: week_start(int(value), effective)
    )
    weekly["week_end"] = weekly["week_start"] + pd.Timedelta(days=6)
    weekly["is_post_action_audit_only"] = weekly["relative_week"].gt(0)
    weekly = weekly[
        [
            "event_id_audit_only",
            "source_event_audit_only",
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
    ]
    audit = {
        "event_id": event["event_id"],
        "source_event": event["source_event"],
        "effective_date": event["effective_date"],
        "source_date_min": selected["date"].min().strftime("%Y-%m-%d"),
        "source_date_max": selected["date"].max().strftime("%Y-%m-%d"),
        "source_zone_day_rows": len(selected),
        "weekly_rows": len(weekly),
        "pre_week_count": int(weekly.loc[weekly["relative_week"].lt(0), "relative_week"].nunique()),
        "post_week_count": int(weekly.loc[weekly["relative_week"].gt(0), "relative_week"].nunique()),
        "zone_count": int(weekly["zone_id"].nunique()),
    }
    return weekly, audit


def build_event_graph(
    event: dict[str, Any],
    weekly: pd.DataFrame,
    protocol: dict[str, Any],
    adjacency: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    od_path = resolve_source(protocol, event["od_panel"])
    pre_start = pd.Timestamp(event["pre_window"][0])
    pre_end = pd.Timestamp(event["pre_window"][1])
    od = pd.read_parquet(
        od_path,
        columns=["date", "origin_zone", "destination_zone", "trip_count"],
        filters=[("date", ">=", pre_start), ("date", "<=", pre_end)],
    )
    od = od.loc[
        od["origin_zone"].between(1, 263)
        & od["destination_zone"].between(1, 263)
        & od["origin_zone"].ne(od["destination_zone"])
        & od["trip_count"].gt(0)
    ]
    totals = (
        od.groupby(["origin_zone", "destination_zone"], observed=True, as_index=False)[
            "trip_count"
        ]
        .sum()
        .sort_values(
            ["origin_zone", "trip_count", "destination_zone"],
            ascending=[True, False, True],
        )
    )
    top = totals.groupby("origin_zone", observed=True, as_index=False).head(8).copy()
    denominators = top.groupby("origin_zone", observed=True)["trip_count"].transform("sum")
    top["weight"] = top["trip_count"] / denominators
    od_edges = top.rename(
        columns={"origin_zone": "source_zone", "destination_zone": "target_zone"}
    )[["source_zone", "target_zone", "weight"]]
    od_edges["relation"] = "origin_destination_flow"

    post_first = weekly.loc[weekly["relative_week"].eq(1)].sort_values("zone_id")
    exposure = post_first[
        ["zone_id", "spatial_applicability_share"]
    ].rename(
        columns={
            "zone_id": "source_zone",
            "spatial_applicability_share": "weight",
        }
    )
    exposure["target_zone"] = exposure["source_zone"]
    exposure["relation"] = "action_exposure"
    exposure = exposure[["source_zone", "target_zone", "relation", "weight"]]

    graph = pd.concat(
        [
            adjacency[["source_zone", "target_zone", "relation", "weight"]],
            od_edges[["source_zone", "target_zone", "relation", "weight"]],
            exposure,
        ],
        ignore_index=True,
    ).sort_values(["relation", "source_zone", "target_zone"]).reset_index(drop=True)
    audit = {
        "event_id": event["event_id"],
        "od_source_path": str(od_path.relative_to(REPO_ROOT)),
        "od_source_pre_rows": len(od),
        "relation_counts": {
            key: int(value)
            for key, value in graph.groupby("relation", observed=True).size().items()
        },
        "od_origin_count": int(od_edges["source_zone"].nunique()),
        "od_edge_count": len(od_edges),
        "action_exposure_nonzero_zones": int(exposure["weight"].gt(0).sum()),
    }
    return graph, audit


def main() -> int:
    protocol = load_json(PROTOCOL_PATH)
    preflight = load_json(PREFLIGHT_PATH)
    if preflight["status"] != "PASS_V5_DRAFT_READY_FOR_RC1":
        raise ValueError("V5 preflight has not passed")
    if preflight["protocol_sha256"] != sha256_file(PROTOCOL_PATH):
        raise ValueError("V5 protocol changed after preflight")

    action_columns = protocol["scene"]["action_columns"]
    source_columns = [
        "date",
        "zone_id",
        "event_audit_only",
        *METADATA_COLUMNS,
        *STATE_COLUMNS,
        *action_columns,
    ]
    event_source_paths = {
        resolve_source(protocol, event["source_panel"]) for event in protocol["events"]
    }
    source_frames = [pd.read_parquet(path, columns=source_columns) for path in event_source_paths]
    source = pd.concat(source_frames, ignore_index=True)
    source["date"] = pd.to_datetime(source["date"])

    zone_metadata = pd.read_parquet(V4_ZONE_PATH).sort_values("zone_id").reset_index(drop=True)
    v4_edges = pd.read_parquet(V4_EDGE_PATH)
    adjacency = v4_edges.loc[v4_edges["relation"].eq("geographic_adjacency")].copy()
    if len(zone_metadata) != 263 or len(adjacency) != 692:
        raise ValueError("frozen V4 zone metadata or adjacency is invalid")

    weekly_by_event: dict[str, pd.DataFrame] = {}
    graph_by_event: dict[str, pd.DataFrame] = {}
    event_audits: list[dict[str, Any]] = []
    event_artifacts: dict[str, Any] = {}
    for event in protocol["events"]:
        event_id = event["event_id"]
        weekly, weekly_audit = aggregate_event(source, event, action_columns)
        graph, graph_audit = build_event_graph(event, weekly, protocol, adjacency)
        weekly_by_event[event_id] = weekly
        graph_by_event[event_id] = graph
        event_root = OUTPUT_ROOT / "events" / event_id
        weekly_path = event_root / "weekly_state_action.parquet"
        graph_path = event_root / "spatial_edges.parquet"
        weekly_path.parent.mkdir(parents=True, exist_ok=True)
        weekly.to_parquet(weekly_path, index=False)
        graph.to_parquet(graph_path, index=False)
        event_audits.append({**weekly_audit, "graph": graph_audit})
        event_artifacts[event_id] = {
            "weekly_state_action": artifact(weekly_path, len(weekly)),
            "spatial_edges": artifact(graph_path, len(graph)),
        }

    zone_path = OUTPUT_ROOT / "graph" / "zone_metadata.parquet"
    zone_path.parent.mkdir(parents=True, exist_ok=True)
    zone_metadata.to_parquet(zone_path, index=False)

    fold_artifacts: dict[str, Any] = {}
    fold_audits: list[dict[str, Any]] = []
    for fold in protocol["outer_folds"]:
        fold_id = fold["fold_id"]
        test_event = fold["test_event"]
        train_events = fold["training_events"]
        fold_root = OUTPUT_ROOT / "folds" / fold_id
        development = pd.concat(
            [weekly_by_event[event_id] for event_id in train_events],
            ignore_index=True,
        )
        test_all = weekly_by_event[test_event]
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
        test_graph = graph_by_event[test_event]

        paths = {
            "development": fold_root / "development/weekly_state_action.parquet",
            "training_manifest": fold_root / "development/training_row_manifest.json",
            "test_history": fold_root / "test_input/weekly_state_history.parquet",
            "test_action": fold_root / "test_input/future_action_spec.parquet",
            "submission_keys": fold_root / "test_input/submission_keys.parquet",
            "test_targets": fold_root / "test_targets/weekly_targets.parquet",
            "zone_metadata": fold_root / "graph/zone_metadata.parquet",
            "test_spatial_edges": fold_root / "graph/test_spatial_edges.parquet",
            "training_graph_index": fold_root / "graph/training_graph_index.json",
        }
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        development.to_parquet(paths["development"], index=False)
        test_history.to_parquet(paths["test_history"], index=False)
        test_action.to_parquet(paths["test_action"], index=False)
        submission_keys.to_parquet(paths["submission_keys"], index=False)
        test_targets.to_parquet(paths["test_targets"], index=False)
        zone_metadata.to_parquet(paths["zone_metadata"], index=False)
        test_graph.to_parquet(paths["test_spatial_edges"], index=False)

        graph_index = {
            "schema": "gwm_bench.foundation_v5_training_graph_index.v1",
            "fold_id": fold_id,
            "test_event": test_event,
            "training_event_graphs": {
                event_id: event_artifacts[event_id]["spatial_edges"]
                for event_id in train_events
            },
            "test_event_graph_permitted_for_model_runtime": True,
            "test_event_graph_uses_post_action_od": False,
        }
        write_json(paths["training_graph_index"], graph_index)
        training_manifest = {
            "schema": "gwm_bench.foundation_v5_fold_training_manifest.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fold_id": fold_id,
            "test_event": test_event,
            "permitted_training_events": train_events,
            "weekly_rows": len(development),
            "heldout_event_rows": int(
                development["event_id_audit_only"].eq(test_event).sum()
            ),
            "heldout_post_action_target_rows_loaded": 0,
            "chronologically_later_training_events_permitted": True,
            "analyst_blindness_claimed": False,
            "test_target_path_permitted_for_model_runtime": False,
            "normalization_may_read_current_fold_targets": False,
            "selection_may_read_current_fold_targets": False,
            "graph_may_read_current_fold_post_action_rows": False,
            "artifact": artifact(paths["development"], len(development)),
        }
        write_json(paths["training_manifest"], training_manifest)

        fold_artifacts[fold_id] = {
            "development": artifact(paths["development"], len(development)),
            "training_manifest": artifact(paths["training_manifest"]),
            "test_history": artifact(paths["test_history"], len(test_history)),
            "test_action": artifact(paths["test_action"], len(test_action)),
            "submission_keys": artifact(paths["submission_keys"], len(submission_keys)),
            "test_targets": artifact(paths["test_targets"], len(test_targets)),
            "zone_metadata": artifact(paths["zone_metadata"], len(zone_metadata)),
            "test_spatial_edges": artifact(paths["test_spatial_edges"], len(test_graph)),
            "training_graph_index": artifact(paths["training_graph_index"]),
        }
        fold_audits.append(
            {
                "fold_id": fold_id,
                "test_event": test_event,
                "training_events": train_events,
                "development_rows": len(development),
                "test_history_rows": len(test_history),
                "test_action_rows": len(test_action),
                "test_target_rows": len(test_targets),
                "test_graph_relation_counts": {
                    key: int(value)
                    for key, value in test_graph.groupby("relation", observed=True).size().items()
                },
            }
        )

    total_event_rows = sum(len(frame) for frame in weekly_by_event.values())
    if total_event_rows != protocol["split_contract"]["expected_total_event_week_rows"]:
        raise ValueError("V5 total event-week row count mismatch")
    manifest = {
        "schema": "gwm_bench.foundation_v5_rc1_bundle.v1",
        "suite_id": protocol["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "V5_RC1_DATA_MATERIALIZED",
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "preflight_sha256": sha256_file(PREFLIGHT_PATH),
        "source_assets": protocol["source_assets"],
        "counts": {
            "event_count": len(weekly_by_event),
            "outer_fold_count": len(fold_artifacts),
            "total_event_week_rows": total_event_rows,
            "total_outer_test_keys": sum(
                row["test_target_rows"] for row in fold_audits
            ),
            "zone_metadata_rows": len(zone_metadata),
        },
        "event_audits": event_audits,
        "fold_audits": fold_audits,
        "artifacts": {
            "zone_metadata": artifact(zone_path, len(zone_metadata)),
            "events": event_artifacts,
            "folds": fold_artifacts,
        },
        "firewall": {
            "fold_targets_written_to_separate_directories": True,
            "current_fold_target_path_permitted_for_model_runtime": False,
            "heldout_event_pre_action_graph_permitted": True,
            "heldout_event_post_action_graph_update_permitted": False,
            "analyst_blindness_claimed": False,
        },
    }
    manifest_path = OUTPUT_ROOT / "bundle_manifest.json"
    write_json(manifest_path, manifest)
    print("GWM-Bench Foundation V5.0 rc1: V5_RC1_DATA_MATERIALIZED")
    print(f"Bundle manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
