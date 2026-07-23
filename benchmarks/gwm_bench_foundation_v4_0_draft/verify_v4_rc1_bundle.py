#!/usr/bin/env python3
"""Verify hashes, counts, split isolation and action contracts in V4 rc1."""

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
BUNDLE_ROOT = DRAFT_ROOT / "rc1_bundle"
MANIFEST_PATH = BUNDLE_ROOT / "bundle_manifest.json"
OUTPUT_PATH = BUNDLE_ROOT / "bundle_verification.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
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


def _path(artifact: dict[str, Any]) -> Path:
    return (REPO_ROOT / artifact["path"]).resolve()


def main() -> int:
    protocol = _load_json(PROTOCOL_PATH)
    manifest = _load_json(MANIFEST_PATH)
    artifacts = manifest["artifacts"]
    artifact_hash_checks = {
        name: _path(artifact).is_file()
        and _path(artifact).stat().st_size == artifact["bytes"]
        and _sha256(_path(artifact)) == artifact["sha256"]
        for name, artifact in artifacts.items()
    }

    development = pd.read_parquet(_path(artifacts["development"]))
    test_history = pd.read_parquet(_path(artifacts["test_history"]))
    test_action = pd.read_parquet(_path(artifacts["test_action"]))
    submission_keys = pd.read_parquet(_path(artifacts["submission_keys"]))
    test_targets = pd.read_parquet(_path(artifacts["test_targets"]))
    zone_metadata = pd.read_parquet(_path(artifacts["zone_metadata"]))
    spatial_edges = pd.read_parquet(_path(artifacts["spatial_edges"]))
    training_manifest = _load_json(_path(artifacts["training_row_manifest"]))

    action_columns = protocol["action_contract"]["numeric_features"]
    component_columns = action_columns[:10]
    submission_contract = protocol["submission_contract"]
    key_columns = submission_contract["key_columns"]
    expected_keys = submission_contract["expected_key_count"]
    development_pre = development["relative_week"].lt(0)
    development_post = development["relative_week"].gt(0)
    component_sum = test_action[component_columns].sum(axis=1).to_numpy(dtype=float)
    expected_total = test_action["expected_total_delta_usd"].to_numpy(dtype=float)

    checks = {
        "manifest_status_is_rc1_materialized": manifest["status"]
        == "V4_RC1_DATA_MATERIALIZED",
        "manifest_protocol_hash_matches": manifest["protocol_sha256"]
        == _sha256(PROTOCOL_PATH),
        "all_artifact_hashes_and_sizes_match": all(artifact_hash_checks.values()),
        "development_row_count_is_33664": len(development) == 33664,
        "development_has_two_events": sorted(
            development["event_id_audit_only"].unique().tolist()
        )
        == [
            "train_2019_nys_congestion_surcharge",
            "train_2022_tlc_taximeter_adjustment",
        ],
        "development_has_exact_52_pre_and_12_post_weeks": development.groupby(
            "event_id_audit_only", observed=True
        )["relative_week"].apply(
            lambda values: sorted(values.unique().tolist())
            == list(range(-52, 0)) + list(range(1, 13))
        ).all(),
        "development_contains_no_2025_post_action_rows": pd.to_datetime(
            development["week_end"]
        ).max()
        < pd.Timestamp("2025-01-05")
        and training_manifest["post_2025_action_rows"] == 0,
        "development_pre_actions_are_zero": np.allclose(
            development.loc[development_pre, action_columns].to_numpy(dtype=float),
            0.0,
            atol=1e-12,
            rtol=0.0,
        ),
        "development_post_actions_are_present": (
            development.loc[development_post, action_columns]
            .abs()
            .sum(axis=1)
            .gt(0)
            .all()
        ),
        "test_history_is_52_pre_action_weeks": len(test_history) == 13676
        and sorted(test_history["relative_week"].unique().tolist()) == list(range(-52, 0))
        and pd.to_datetime(test_history["week_end"]).max() == pd.Timestamp("2025-01-04"),
        "test_history_actions_are_zero": np.allclose(
            test_history[action_columns].to_numpy(dtype=float),
            0.0,
            atol=1e-12,
            rtol=0.0,
        ),
        "test_action_has_3156_keys_and_all_horizons": len(test_action) == expected_keys
        and sorted(test_action["horizon_week"].unique().tolist()) == list(range(1, 13)),
        "test_action_component_sum_contract_holds": np.allclose(
            component_sum,
            expected_total,
            atol=1e-6,
            rtol=0.0,
        ),
        "test_action_has_frozen_spatial_variation": test_action.groupby(
            "zone_id", observed=True
        )["spatial_applicability_share"].nunique().max()
        == 1
        and test_action["spatial_applicability_share"].nunique() > 1,
        "test_targets_have_3156_keys_and_four_targets": len(test_targets) == expected_keys
        and all(column in test_targets.columns for column in protocol["dataset"]["state_targets"]),
        "submission_keys_are_exact_and_unique": len(submission_keys) == expected_keys
        and not submission_keys.duplicated(key_columns).any()
        and submission_keys.sort_values(key_columns).reset_index(drop=True).equals(
            test_targets[key_columns].sort_values(key_columns).reset_index(drop=True)
        ),
        "zone_metadata_has_263_unique_zones": len(zone_metadata) == 263
        and zone_metadata["zone_id"].nunique() == 263
        and zone_metadata["zone_id"].min() == 1
        and zone_metadata["zone_id"].max() == 263,
        "cbd_exposure_has_38_zones": int(zone_metadata["cbd_exposure"].sum()) == 38,
        "spatial_graph_has_expected_relation_counts": spatial_edges.groupby(
            "relation", observed=True
        ).size().to_dict()
        == {
            "action_exposure": 263,
            "geographic_adjacency": 692,
            "origin_destination_flow": 2054,
        },
        "spatial_graph_node_ids_are_valid": spatial_edges[
            ["source_zone", "target_zone"]
        ].to_numpy().min()
        >= 1
        and spatial_edges[["source_zone", "target_zone"]].to_numpy().max() <= 263,
        "runtime_cannot_read_test_target_path": training_manifest[
            "test_target_path_permitted_for_model_runtime"
        ]
        is False
        and manifest["firewall"]["test_target_path_permitted_for_model_runtime"] is False,
        "claim_boundary_is_nonblind_and_noncausal": manifest["firewall"][
            "analyst_blindness_claimed"
        ]
        is False
        and "causal effect of congestion pricing"
        in protocol["claim_boundary"]["does_not_support"],
    }
    checks = {name: bool(value) for name, value in checks.items()}
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v4_rc1_bundle_verification.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_V4_RC1_DATA_VERIFIED" if passed else "FAIL",
        "manifest_sha256": _sha256(MANIFEST_PATH),
        "protocol_sha256": _sha256(PROTOCOL_PATH),
        "check_count": len(checks),
        "checks": checks,
        "artifact_hash_checks": artifact_hash_checks,
        "counts": manifest["counts"],
        "firewall": manifest["firewall"],
        "next_permitted_action": (
            "Freeze Runtime-R3, submission and evaluator contracts before running candidate models."
            if passed
            else "Fix rc1 bundle or firewall failures before freezing runtime contracts."
        ),
    }
    _write_json(OUTPUT_PATH, report)
    print(f"GWM-Bench Foundation V4.0 rc1: {report['status']}")
    print(f"Verification report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
