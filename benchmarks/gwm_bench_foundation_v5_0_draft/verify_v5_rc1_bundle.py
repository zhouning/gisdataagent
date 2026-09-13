#!/usr/bin/env python3
"""Independently verify the V5 RC1 event bundles and outer-fold firewalls."""

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
BUNDLE_ROOT = DRAFT_ROOT / "rc1_bundle"
MANIFEST_PATH = BUNDLE_ROOT / "bundle_manifest.json"
OUTPUT_PATH = BUNDLE_ROOT / "bundle_verification.json"
V4_ZONE_PATH = (
    REPO_ROOT
    / "benchmarks/gwm_bench_foundation_v4_0_draft/rc1_bundle/graph/zone_metadata.parquet"
)
V4_EDGE_PATH = (
    REPO_ROOT
    / "benchmarks/gwm_bench_foundation_v4_0_draft/rc1_bundle/graph/spatial_edges.parquet"
)
STATE_COLUMNS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]
KEY_COLUMNS = ["zone_id", "horizon_week"]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
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


def artifact_path(artifact: dict[str, Any]) -> Path:
    return REPO_ROOT / artifact["path"]


def artifact_ok(artifact: dict[str, Any]) -> bool:
    path = artifact_path(artifact)
    return (
        path.is_file()
        and path.stat().st_size == artifact["bytes"]
        and sha256_file(path) == artifact["sha256"]
    )


def source_artifact_ok(asset: dict[str, Any]) -> bool:
    path = REPO_ROOT / asset["path"]
    return (
        path.is_file()
        and path.stat().st_size == asset["bytes"]
        and sha256_file(path) == asset["sha256"]
    )


def add(checks: dict[str, bool], name: str, value: Any) -> None:
    checks[name] = bool(value)


def expected_week_start(relative_week: pd.Series, effective: pd.Timestamp) -> pd.Series:
    values = relative_week.to_numpy(dtype=np.int64)
    offsets = np.where(values < 0, values * 7, (values - 1) * 7)
    return pd.Series(effective + pd.to_timedelta(offsets, unit="D"), index=relative_week.index)


def sorted_equal(
    left: pd.DataFrame,
    right: pd.DataFrame,
    sort_columns: list[str],
    columns: list[str] | None = None,
) -> bool:
    if columns is not None:
        if not set(columns).issubset(left.columns) or not set(columns).issubset(right.columns):
            return False
        left = left[columns]
        right = right[columns]
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return False
    left = left.sort_values(sort_columns).reset_index(drop=True)
    right = right.sort_values(sort_columns).reset_index(drop=True)
    for column in left.columns:
        left_values = left[column]
        right_values = right[column]
        if pd.api.types.is_numeric_dtype(left_values.dtype) and pd.api.types.is_numeric_dtype(
            right_values.dtype
        ):
            if not np.allclose(
                left_values.to_numpy(dtype=float),
                right_values.to_numpy(dtype=float),
                atol=1e-12,
                rtol=1e-12,
                equal_nan=True,
            ):
                return False
        elif not left_values.equals(right_values):
            return False
    return True


def resolve_od_source(protocol: dict[str, Any], basename: str) -> Path:
    for asset in protocol["source_assets"]["od_panels"]:
        path = REPO_ROOT / asset["path"]
        if path.name == basename:
            return path
    raise KeyError(basename)


def recompute_pre_action_od_edges(
    protocol: dict[str, Any], event: dict[str, Any]
) -> pd.DataFrame:
    path = resolve_od_source(protocol, event["od_panel"])
    od = pd.read_parquet(
        path,
        columns=["date", "origin_zone", "destination_zone", "trip_count"],
        filters=[
            ("date", ">=", pd.Timestamp(event["pre_window"][0])),
            ("date", "<=", pd.Timestamp(event["pre_window"][1])),
        ],
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
    top["weight"] = top["trip_count"] / top.groupby(
        "origin_zone", observed=True
    )["trip_count"].transform("sum")
    return top.rename(
        columns={"origin_zone": "source_zone", "destination_zone": "target_zone"}
    )[["source_zone", "target_zone", "weight"]]


def main() -> int:
    protocol = load_json(PROTOCOL_PATH)
    preflight = load_json(PREFLIGHT_PATH)
    manifest = load_json(MANIFEST_PATH)
    action_columns = protocol["scene"]["action_columns"]
    component_columns = action_columns[:10]
    expected_weeks = list(range(-52, 0)) + list(range(1, 13))
    expected_zones = list(range(1, 264))
    split = protocol["split_contract"]
    events_by_id = {event["event_id"]: event for event in protocol["events"]}
    checks: dict[str, bool] = {}
    artifact_hash_checks: dict[str, bool] = {}
    source_hash_checks: dict[str, bool] = {}
    event_summaries: dict[str, Any] = {}
    fold_summaries: dict[str, Any] = {}

    add(checks, "manifest_status_is_v5_rc1_materialized", manifest["status"] == "V5_RC1_DATA_MATERIALIZED")
    add(checks, "suite_id_matches_protocol", manifest["suite_id"] == protocol["suite_id"])
    add(checks, "protocol_hash_matches_manifest", manifest["protocol_sha256"] == sha256_file(PROTOCOL_PATH))
    add(checks, "preflight_hash_matches_manifest", manifest["preflight_sha256"] == sha256_file(PREFLIGHT_PATH))
    add(checks, "preflight_status_passed", preflight["status"] == "PASS_V5_DRAFT_READY_FOR_RC1")
    add(checks, "preflight_protocol_hash_matches", preflight["protocol_sha256"] == sha256_file(PROTOCOL_PATH))
    add(checks, "protocol_requires_no_new_download", protocol["source_assets"]["new_download_required"] is False)
    add(checks, "manifest_event_count_is_four", manifest["counts"]["event_count"] == 4)
    add(checks, "manifest_outer_fold_count_is_four", manifest["counts"]["outer_fold_count"] == 4)
    add(
        checks,
        "manifest_total_event_rows_match_contract",
        manifest["counts"]["total_event_week_rows"] == split["expected_total_event_week_rows"],
    )
    add(
        checks,
        "manifest_total_test_keys_match_contract",
        manifest["counts"]["total_outer_test_keys"] == split["expected_total_outer_test_keys"],
    )

    for group in ("event_panels", "od_panels"):
        for asset in protocol["source_assets"][group]:
            key = f"{group}/{Path(asset['path']).name}"
            source_hash_checks[key] = source_artifact_ok(asset)
    add(checks, "all_frozen_source_hashes_and_sizes_match", all(source_hash_checks.values()))

    zone_artifact = manifest["artifacts"]["zone_metadata"]
    artifact_hash_checks["graph/zone_metadata"] = artifact_ok(zone_artifact)
    zone_metadata = pd.read_parquet(artifact_path(zone_artifact))
    v4_zone_metadata = pd.read_parquet(V4_ZONE_PATH)
    add(
        checks,
        "zone_metadata_has_exact_263_zone_domain",
        len(zone_metadata) == 263
        and zone_metadata["zone_id"].nunique() == 263
        and sorted(zone_metadata["zone_id"].tolist()) == expected_zones,
    )
    add(checks, "zone_metadata_has_38_cbd_zones", int(zone_metadata["cbd_exposure"].sum()) == 38)
    add(
        checks,
        "zone_metadata_is_exact_frozen_v4_copy",
        sorted_equal(zone_metadata, v4_zone_metadata, ["zone_id"]),
    )
    v4_edges = pd.read_parquet(V4_EDGE_PATH)
    v4_adjacency = v4_edges.loc[v4_edges["relation"].eq("geographic_adjacency")].copy()

    event_frames: dict[str, pd.DataFrame] = {}
    event_graphs: dict[str, pd.DataFrame] = {}
    for event_id, event in events_by_id.items():
        prefix = f"event/{event_id}"
        artifacts = manifest["artifacts"]["events"][event_id]
        for name, artifact in artifacts.items():
            artifact_hash_checks[f"events/{event_id}/{name}"] = artifact_ok(artifact)
        weekly = pd.read_parquet(artifact_path(artifacts["weekly_state_action"]))
        graph = pd.read_parquet(artifact_path(artifacts["spatial_edges"]))
        event_frames[event_id] = weekly
        event_graphs[event_id] = graph
        effective = pd.Timestamp(event["effective_date"])
        pre = weekly["relative_week"].lt(0)
        post = weekly["relative_week"].gt(0)
        expected_starts = expected_week_start(weekly["relative_week"], effective)
        key_columns = ["event_id_audit_only", "relative_week", "zone_id"]
        add(checks, f"{prefix}/row_count", len(weekly) == split["expected_event_week_rows"])
        add(checks, f"{prefix}/unique_keys", not weekly.duplicated(key_columns).any())
        add(
            checks,
            f"{prefix}/event_identity",
            weekly["event_id_audit_only"].nunique() == 1
            and weekly["event_id_audit_only"].iloc[0] == event_id
            and weekly["source_event_audit_only"].nunique() == 1
            and weekly["source_event_audit_only"].iloc[0] == event["source_event"],
        )
        add(
            checks,
            f"{prefix}/exact_week_domain",
            sorted(weekly["relative_week"].unique().tolist()) == expected_weeks
            and weekly.groupby("relative_week", observed=True).size().eq(263).all(),
        )
        add(
            checks,
            f"{prefix}/exact_zone_domain",
            sorted(weekly["zone_id"].unique().tolist()) == expected_zones
            and weekly.groupby("zone_id", observed=True).size().eq(64).all(),
        )
        add(
            checks,
            f"{prefix}/dates_align_to_action",
            pd.to_datetime(weekly["effective_date_audit_only"]).eq(effective).all()
            and pd.to_datetime(weekly["week_start"]).equals(expected_starts)
            and pd.to_datetime(weekly["week_end"]).equals(expected_starts + pd.Timedelta(days=6)),
        )
        add(
            checks,
            f"{prefix}/post_flag_matches_week_sign",
            weekly["is_post_action_audit_only"].eq(post).all(),
        )
        add(
            checks,
            f"{prefix}/states_are_finite_and_nonnegative",
            np.isfinite(weekly[STATE_COLUMNS].to_numpy(dtype=float)).all()
            and weekly[STATE_COLUMNS].ge(0).all().all(),
        )
        add(
            checks,
            f"{prefix}/actions_are_finite",
            np.isfinite(weekly[action_columns].to_numpy(dtype=float)).all(),
        )
        add(
            checks,
            f"{prefix}/pre_action_vector_is_zero",
            np.allclose(
                weekly.loc[pre, action_columns].to_numpy(dtype=float),
                0.0,
                atol=1e-12,
                rtol=0.0,
            ),
        )
        add(
            checks,
            f"{prefix}/post_component_sum_matches_total",
            np.allclose(
                weekly.loc[post, component_columns].sum(axis=1).to_numpy(dtype=float),
                weekly.loc[post, "expected_total_delta_usd"].to_numpy(dtype=float),
                atol=1e-10,
                rtol=0.0,
            ),
        )
        share_columns = [
            "spatial_applicability_share",
            "temporal_applicability_share",
            "implementation_share",
        ]
        add(
            checks,
            f"{prefix}/post_action_shares_are_probabilities",
            weekly.loc[post, share_columns].ge(0).all().all()
            and weekly.loc[post, share_columns].le(1).all().all(),
        )

        relation_counts = graph.groupby("relation", observed=True).size().to_dict()
        add(
            checks,
            f"{prefix}/graph_relation_contract",
            relation_counts.get("geographic_adjacency") == 692
            and relation_counts.get("action_exposure") == 263
            and 1 <= relation_counts.get("origin_destination_flow", 0) <= 263 * 8
            and set(relation_counts) == {
                "geographic_adjacency",
                "origin_destination_flow",
                "action_exposure",
            },
        )
        add(
            checks,
            f"{prefix}/graph_node_domain",
            graph[["source_zone", "target_zone"]].to_numpy().min() >= 1
            and graph[["source_zone", "target_zone"]].to_numpy().max() <= 263
            and np.isfinite(graph["weight"].to_numpy(dtype=float)).all(),
        )
        adjacency = graph.loc[graph["relation"].eq("geographic_adjacency")]
        add(
            checks,
            f"{prefix}/adjacency_is_exact_frozen_v4_copy",
            sorted_equal(
                adjacency,
                v4_adjacency,
                ["source_zone", "target_zone"],
                ["source_zone", "target_zone", "relation", "weight"],
            ),
        )
        od_edges = graph.loc[graph["relation"].eq("origin_destination_flow")][
            ["source_zone", "target_zone", "weight"]
        ]
        recomputed_od = recompute_pre_action_od_edges(protocol, event)
        add(
            checks,
            f"{prefix}/od_edges_exactly_recomputed_from_pre_action_only",
            sorted_equal(
                od_edges,
                recomputed_od,
                ["source_zone", "target_zone"],
            ),
        )
        add(
            checks,
            f"{prefix}/od_top8_and_normalization_contract",
            od_edges.groupby("source_zone", observed=True).size().le(8).all()
            and np.allclose(
                od_edges.groupby("source_zone", observed=True)["weight"].sum().to_numpy(),
                1.0,
                atol=1e-12,
                rtol=0.0,
            )
            and od_edges["weight"].gt(0).all(),
        )
        exposure = graph.loc[graph["relation"].eq("action_exposure")].sort_values(
            "source_zone"
        )
        expected_exposure = weekly.loc[weekly["relative_week"].eq(1)].sort_values("zone_id")
        add(
            checks,
            f"{prefix}/action_exposure_matches_frozen_action_spec",
            len(exposure) == 263
            and exposure["source_zone"].equals(exposure["target_zone"])
            and exposure["source_zone"].tolist() == expected_exposure["zone_id"].tolist()
            and np.allclose(
                exposure["weight"].to_numpy(dtype=float),
                expected_exposure["spatial_applicability_share"].to_numpy(dtype=float),
                atol=1e-12,
                rtol=0.0,
            ),
        )
        event_summaries[event_id] = {
            "weekly_rows": len(weekly),
            "pre_weeks": int(weekly.loc[pre, "relative_week"].nunique()),
            "post_weeks": int(weekly.loc[post, "relative_week"].nunique()),
            "zones": int(weekly["zone_id"].nunique()),
            "graph_relation_counts": {key: int(value) for key, value in relation_counts.items()},
        }

    for fold in protocol["outer_folds"]:
        fold_id = fold["fold_id"]
        prefix = f"fold/{fold_id}"
        test_event = fold["test_event"]
        train_events = fold["training_events"]
        artifacts = manifest["artifacts"]["folds"][fold_id]
        for name, artifact in artifacts.items():
            artifact_hash_checks[f"folds/{fold_id}/{name}"] = artifact_ok(artifact)
        development = pd.read_parquet(artifact_path(artifacts["development"]))
        history = pd.read_parquet(artifact_path(artifacts["test_history"]))
        future_action = pd.read_parquet(artifact_path(artifacts["test_action"]))
        submission_keys = pd.read_parquet(artifact_path(artifacts["submission_keys"]))
        targets = pd.read_parquet(artifact_path(artifacts["test_targets"]))
        fold_zones = pd.read_parquet(artifact_path(artifacts["zone_metadata"]))
        test_graph = pd.read_parquet(artifact_path(artifacts["test_spatial_edges"]))
        training_manifest = load_json(artifact_path(artifacts["training_manifest"]))
        graph_index = load_json(artifact_path(artifacts["training_graph_index"]))
        full_test_event = event_frames[test_event]
        expected_history = full_test_event.loc[full_test_event["relative_week"].lt(0)].copy()
        expected_post = full_test_event.loc[full_test_event["relative_week"].gt(0)].copy()
        expected_development = pd.concat(
            [event_frames[event_id] for event_id in train_events], ignore_index=True
        )
        expected_action_columns = [
            "zone_id",
            "relative_week",
            "week_start",
            "week_end",
            "cbd_exposure",
            *action_columns,
        ]
        expected_action = expected_post[expected_action_columns].rename(
            columns={"relative_week": "horizon_week"}
        )
        expected_targets = expected_post[
            ["zone_id", "relative_week", "week_start", "week_end", *STATE_COLUMNS]
        ].rename(columns={"relative_week": "horizon_week"})
        add(
            checks,
            f"{prefix}/development_row_count",
            len(development) == split["expected_training_rows_per_outer_fold"],
        )
        add(
            checks,
            f"{prefix}/development_has_exact_training_events",
            sorted(development["event_id_audit_only"].unique().tolist())
            == sorted(train_events)
            and not development["event_id_audit_only"].eq(test_event).any()
            and development.groupby("event_id_audit_only", observed=True).size().eq(
                split["expected_event_week_rows"]
            ).all(),
        )
        add(
            checks,
            f"{prefix}/development_is_exact_event_union",
            sorted_equal(
                development,
                expected_development,
                ["event_id_audit_only", "relative_week", "zone_id"],
            ),
        )
        add(
            checks,
            f"{prefix}/history_is_exact_heldout_pre_action",
            len(history) == split["expected_test_history_rows_per_outer_fold"]
            and sorted_equal(history, expected_history, ["relative_week", "zone_id"])
            and sorted(history["relative_week"].unique().tolist()) == list(range(-52, 0)),
        )
        add(
            checks,
            f"{prefix}/history_action_vector_is_zero",
            np.allclose(
                history[action_columns].to_numpy(dtype=float),
                0.0,
                atol=1e-12,
                rtol=0.0,
            ),
        )
        add(
            checks,
            f"{prefix}/future_action_is_exact_heldout_spec",
            len(future_action) == split["expected_test_action_rows_per_outer_fold"]
            and sorted_equal(future_action, expected_action, KEY_COLUMNS)
            and not set(STATE_COLUMNS).intersection(future_action.columns),
        )
        add(
            checks,
            f"{prefix}/targets_are_exact_and_action_free",
            len(targets) == split["expected_test_target_rows_per_outer_fold"]
            and sorted_equal(targets, expected_targets, KEY_COLUMNS)
            and not set(action_columns).intersection(targets.columns),
        )
        add(
            checks,
            f"{prefix}/submission_keys_are_exact_and_unique",
            len(submission_keys) == split["expected_test_target_rows_per_outer_fold"]
            and not submission_keys.duplicated(KEY_COLUMNS).any()
            and sorted_equal(submission_keys, targets[KEY_COLUMNS], KEY_COLUMNS)
            and sorted_equal(submission_keys, future_action[KEY_COLUMNS], KEY_COLUMNS),
        )
        add(
            checks,
            f"{prefix}/all_12_horizons_and_263_zones_present",
            sorted(submission_keys["horizon_week"].unique().tolist()) == list(range(1, 13))
            and sorted(submission_keys["zone_id"].unique().tolist()) == expected_zones
            and submission_keys.groupby("horizon_week", observed=True).size().eq(263).all(),
        )
        add(
            checks,
            f"{prefix}/zone_metadata_is_frozen_copy",
            sorted_equal(fold_zones, zone_metadata, ["zone_id"]),
        )
        add(
            checks,
            f"{prefix}/test_graph_is_exact_pre_action_event_graph",
            sorted_equal(
                test_graph,
                event_graphs[test_event],
                ["relation", "source_zone", "target_zone"],
            ),
        )
        add(
            checks,
            f"{prefix}/training_manifest_isolated",
            training_manifest["fold_id"] == fold_id
            and training_manifest["test_event"] == test_event
            and training_manifest["permitted_training_events"] == train_events
            and training_manifest["weekly_rows"] == split["expected_training_rows_per_outer_fold"]
            and training_manifest["heldout_event_rows"] == 0
            and training_manifest["heldout_post_action_target_rows_loaded"] == 0
            and training_manifest["test_target_path_permitted_for_model_runtime"] is False
            and training_manifest["normalization_may_read_current_fold_targets"] is False
            and training_manifest["selection_may_read_current_fold_targets"] is False
            and training_manifest["graph_may_read_current_fold_post_action_rows"] is False
            and artifact_ok(training_manifest["artifact"]),
        )
        graph_artifacts_ok = all(
            event_id in graph_index["training_event_graphs"]
            and artifact_ok(graph_index["training_event_graphs"][event_id])
            for event_id in train_events
        )
        add(
            checks,
            f"{prefix}/training_graph_index_isolated",
            graph_index["fold_id"] == fold_id
            and graph_index["test_event"] == test_event
            and sorted(graph_index["training_event_graphs"]) == sorted(train_events)
            and test_event not in graph_index["training_event_graphs"]
            and graph_index["test_event_graph_permitted_for_model_runtime"] is True
            and graph_index["test_event_graph_uses_post_action_od"] is False
            and graph_artifacts_ok,
        )
        add(
            checks,
            f"{prefix}/target_artifact_is_physically_separate",
            "test_targets" in artifact_path(artifacts["test_targets"]).parts
            and "test_input" in artifact_path(artifacts["test_history"]).parts
            and "test_input" in artifact_path(artifacts["test_action"]).parts
            and artifact_path(artifacts["test_targets"]).parent
            != artifact_path(artifacts["test_history"]).parent,
        )
        fold_summaries[fold_id] = {
            "test_event": test_event,
            "training_events": train_events,
            "development_rows": len(development),
            "history_rows": len(history),
            "future_action_rows": len(future_action),
            "target_rows": len(targets),
        }

    add(checks, "all_bundle_artifact_hashes_and_sizes_match", all(artifact_hash_checks.values()))
    add(
        checks,
        "manifest_firewall_denies_target_access",
        manifest["firewall"]["fold_targets_written_to_separate_directories"] is True
        and manifest["firewall"]["current_fold_target_path_permitted_for_model_runtime"] is False
        and manifest["firewall"]["heldout_event_pre_action_graph_permitted"] is True
        and manifest["firewall"]["heldout_event_post_action_graph_update_permitted"] is False,
    )
    add(
        checks,
        "claim_boundary_is_nonblind_and_noncausal",
        manifest["firewall"]["analyst_blindness_claimed"] is False
        and "analyst-unseen or externally hidden labels"
        in protocol["claim_boundary"]["does_not_support"]
        and "causal effects of any taxi fee or congestion-pricing policy"
        in protocol["claim_boundary"]["does_not_support"],
    )
    add(
        checks,
        "completion_does_not_require_model_win",
        protocol["completion_definition"]["model_win_required"] is False
        and protocol["action_transfer_gate"]["completion_independent_of_gate"] is True,
    )

    passed = all(checks.values())
    failed_checks = [name for name, value in checks.items() if not value]
    report = {
        "schema": "gwm_bench.foundation_v5_rc1_bundle_verification.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_V5_RC1_DATA_VERIFIED" if passed else "FAIL_V5_RC1_DATA_VERIFICATION",
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "preflight_sha256": sha256_file(PREFLIGHT_PATH),
        "check_count": len(checks),
        "passed_check_count": sum(checks.values()),
        "failed_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "checks": checks,
        "source_hash_checks": source_hash_checks,
        "artifact_hash_checks": artifact_hash_checks,
        "counts": manifest["counts"],
        "event_summaries": event_summaries,
        "fold_summaries": fold_summaries,
        "firewall": manifest["firewall"],
        "next_permitted_action": (
            "Freeze Runtime-R4, submission contracts and the evaluator before any formal model execution."
            if passed
            else "Fix the failed RC1 data or firewall checks before freezing Runtime-R4."
        ),
    }
    write_json(OUTPUT_PATH, report)
    print(f"GWM-Bench Foundation V5.0 rc1: {report['status']}")
    print(f"Checks: {report['passed_check_count']}/{report['check_count']}")
    if failed_checks:
        print("Failed checks:")
        for name in failed_checks:
            print(f"- {name}")
    print(f"Verification report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
