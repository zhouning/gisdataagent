#!/usr/bin/env python3
"""Metadata-only preflight for GWM Benchmark V4.0 draft.

The preflight reads JSON manifests, file metadata and Parquet footers. It does
not scan any 2025 post-action target row and does not materialize the weekly
benchmark bundle.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
DEFAULT_OUTPUT = DRAFT_ROOT / "preflight_report.json"
DATA_ROOT = REPO_ROOT / "data" / "uwm_regimeworld_nyc"
MINIMUM_FREE_BYTES = 2 * 1024**3


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_path(value: str) -> Path:
    return (REPO_ROOT / value).resolve()


def _month_range(start: str, end: str) -> list[str]:
    start_year, start_month = (int(value) for value in start.split("-"))
    end_year, end_month = (int(value) for value in end.split("-"))
    current = date(start_year, start_month, 1)
    final = date(end_year, end_month, 1)
    values: list[str] = []
    while current <= final:
        values.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return values


def _parquet_footer(path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "row_count": parquet.metadata.num_rows,
        "row_group_count": parquet.metadata.num_row_groups,
        "columns": parquet.schema_arrow.names,
    }


def preflight(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    artifacts = protocol["dataset"]["source_artifacts"]
    current_manifest_path = _repo_path(artifacts["current_acquisition_manifest"])
    historical_manifest_path = _repo_path(artifacts["historical_tlc_manifest"])
    policy_manifest_path = _repo_path(artifacts["policy_manifest"])
    daily_zone_path = _repo_path(artifacts["daily_zone_state"])
    daily_od_path = _repo_path(artifacts["daily_od_state"])
    event_panel_path = _repo_path(artifacts["compositional_event_panel"])
    action_ontology_path = _repo_path(artifacts["compositional_action_ontology"])
    build_report_path = _repo_path(artifacts["daily_state_build_report"])
    action_ledger_path = _repo_path(artifacts["action_ledger"])
    graph_ledger_path = _repo_path(artifacts["graph_ledger"])

    required_paths = {
        key: _repo_path(value)
        for key, value in artifacts.items()
    }
    all_required_paths_exist = all(path.is_file() for path in required_paths.values())

    current_manifest = _load_json(current_manifest_path)
    historical_manifest = _load_json(historical_manifest_path)
    policy_manifest = _load_json(policy_manifest_path)
    build_report = _load_json(build_report_path)
    action_ledger = _load_json(action_ledger_path)
    graph_ledger = _load_json(graph_ledger_path)
    action_ontology = _load_json(action_ontology_path)

    expected_historical_months = (
        _month_range("2018-02", "2019-12")
        + _month_range("2021-12", "2023-12")
    )
    expected_current_months = _month_range("2024-01", "2025-12")
    historical_resources = historical_manifest["resources"]
    historical_months = [resource["month"] for resource in historical_resources]
    historical_paths = [_repo_path(resource["path"]) for resource in historical_resources]
    historical_files_present = all(path.is_file() for path in historical_paths)
    historical_bytes = sum(path.stat().st_size for path in historical_paths if path.is_file())
    historical_rows = sum(
        int(resource["validation"]["row_count"])
        for resource in historical_resources
    )

    current_resources = [
        resource
        for resource in current_manifest["resources"]
        if resource["resource_id"].startswith("tlc_yellow_2024-")
        or resource["resource_id"].startswith("tlc_yellow_2025-")
    ]
    current_months = [resource["resource_id"].removeprefix("tlc_yellow_") for resource in current_resources]
    current_paths = [DATA_ROOT / resource["path"] for resource in current_resources]
    current_files_present = all(path.is_file() for path in current_paths)
    current_declared_sizes_match = all(
        path.is_file() and path.stat().st_size == int(resource["size_bytes"])
        for path, resource in zip(current_paths, current_resources, strict=True)
    )
    current_bytes = sum(int(resource["size_bytes"]) for resource in current_resources)
    current_rows = sum(
        int(resource["validation"]["row_count"])
        for resource in current_resources
    )

    zone_footer = _parquet_footer(daily_zone_path)
    od_footer = _parquet_footer(daily_od_path)
    event_footer = _parquet_footer(event_panel_path)
    required_zone_columns = {
        "date",
        "zone_id",
        "pickup_count",
        "dropoff_count",
        "cbd_inflow",
        "cbd_outflow",
        "cbd_exposure",
        "action_nys_congestion_surcharge_usd",
        "action_meter_initial_charge_usd",
        "action_meter_additional_unit_usd",
        "action_crz_trip_charge_usd",
        "action_crz_zone_exposure",
        "split",
    }
    required_od_columns = {
        "date",
        "origin_zone",
        "destination_zone",
        "trip_count",
        "split",
    }
    required_event_columns = {
        "date",
        "zone_id",
        "event_audit_only",
        "pickup_count",
        "dropoff_count",
        "cbd_inflow",
        "cbd_outflow",
        *protocol["action_contract"]["numeric_features"],
    }

    verified_policy_resources = policy_manifest["resources"]
    current_policy = current_manifest["policy"]
    official_2025_sources = current_policy["official_sources"]
    cbd_resource = next(
        resource
        for resource in current_manifest["resources"]
        if resource["resource_id"] == "mta_cbd_taxi_zones"
    )
    action_dates = {
        intervention["date"]
        for intervention in action_ledger["interventions"]
    }
    event_windows = protocol["dataset"]["events"]
    event_week_contract_exact = all(
        event["pre_week_count"] == 52
        and event["post_week_count"] == 12
        for event in event_windows
    )

    free_bytes = shutil.disk_usage(REPO_ROOT).free
    checks = {
        "protocol_schema_is_v4_draft": protocol["schema"]
        == "gwm_bench.foundation_v4_draft_protocol.v1",
        "protocol_definition_is_complete": protocol["current_state"]["definition_complete"]
        and protocol["current_state"]["candidate_selected"],
        "required_source_artifacts_exist": all_required_paths_exist,
        "historical_manifest_has_exact_48_months": historical_months
        == expected_historical_months
        and len(historical_resources) == 48,
        "historical_files_are_local_and_admitted": historical_files_present
        and all(resource["status"] == "admitted" for resource in historical_resources),
        "current_manifest_has_exact_24_months": current_months
        == expected_current_months
        and len(current_resources) == 24,
        "current_files_are_local_admitted_and_size_matched": current_files_present
        and current_declared_sizes_match
        and all(resource["status"] == "admitted" for resource in current_resources),
        "raw_inventory_matches_protocol": len(historical_resources) + len(current_resources)
        == protocol["dataset"]["raw_source_inventory"]["tlc_monthly_file_count"]
        and historical_rows + current_rows
        == protocol["dataset"]["raw_source_inventory"]["tlc_raw_row_count"]
        and historical_bytes + current_bytes
        == protocol["dataset"]["raw_source_inventory"]["tlc_local_bytes"],
        "daily_zone_footer_matches_report": zone_footer["row_count"]
        == build_report["panel_rows"]
        == protocol["dataset"]["raw_source_inventory"]["daily_zone_panel_rows"],
        "daily_od_footer_matches_protocol": od_footer["row_count"]
        == protocol["dataset"]["raw_source_inventory"]["daily_od_panel_rows"],
        "daily_zone_schema_supports_v4": required_zone_columns.issubset(zone_footer["columns"]),
        "daily_od_schema_supports_v4": required_od_columns.issubset(od_footer["columns"]),
        "compositional_event_panel_supports_v4": event_footer["row_count"] == 576233
        and required_event_columns.issubset(event_footer["columns"]),
        "daily_panel_has_263_zones_and_expected_dates": build_report["panel_zones"] == 263
        and build_report["panel_dates"] == 2342
        and build_report["date_min"] == "2018-02-01"
        and build_report["date_max"] == "2026-05-31",
        "2025_targets_were_not_used_by_source_builder": build_report[
            "unseen_2025_labels_used_for_training"
        ]
        is False,
        "action_ledger_has_all_three_boundaries": action_dates
        == {"2019-02-02", "2022-12-19", "2025-01-05"},
        "action_ontology_matches_protocol": action_ontology["features"]
        == protocol["action_contract"]["numeric_features"]
        and action_ontology["event_id_model_input_permitted"] is False
        and action_ontology["opaque_policy_embedding_permitted"] is False,
        "action_ledger_prohibits_event_id_input": "event_id_audit_only is prohibited"
        in action_ledger["model_input_rule"],
        "2019_and_2022_policy_documents_are_verified": len(verified_policy_resources) >= 5
        and all(resource["verified"] for resource in verified_policy_resources),
        "2025_policy_terms_and_official_sources_are_declared": current_policy[
            "implementation_date"
        ]
        == "2025-01-05"
        and current_policy["yellow_taxi_per_trip_charge_usd"] == 0.75
        and len(official_2025_sources) >= 3,
        "official_cbd_exposure_is_admitted": cbd_resource["status"] == "admitted"
        and cbd_resource["validation"]["row_count"] == 38,
        "graph_ledger_matches_v4_contract": graph_ledger["node_count"] == 263
        and graph_ledger["adjacency_edge_count"] == 692
        and graph_ledger["od_edge_count"] == 2054
        and graph_ledger["top_k_od"] == 8,
        "event_week_contract_is_exact": event_week_contract_exact
        and protocol["dataset"]["derived_row_counts"]["total_zone_week_rows"] == 50496
        and protocol["submission_contract"]["expected_key_count"] == 3156,
        "claim_boundary_rejects_causal_and_blind_claims": "causal effect of congestion pricing"
        in protocol["claim_boundary"]["does_not_support"]
        and "analyst-unseen or externally hidden-label evaluation"
        in protocol["claim_boundary"]["does_not_support"],
        "benchmark_completion_does_not_require_model_win": protocol["evaluation"][
            "benchmark_completion_requires_model_win"
        ]
        is False
        and protocol["evaluation"]["negative_result_publishable"] is True,
        "no_new_raw_download_is_required": protocol["resource_policy"][
            "new_raw_download_required"
        ]
        is False
        and historical_files_present
        and current_files_present,
        "workspace_has_at_least_2_gib_free": free_bytes >= MINIMUM_FREE_BYTES,
    }
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v4_draft_preflight.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_READY_TO_MATERIALIZE_WEEKLY_BUNDLE" if passed else "FAIL",
        "protocol_sha256": _sha256(PROTOCOL_PATH),
        "check_count": len(checks),
        "checks": checks,
        "summary": {
            "selected_scene": protocol["dataset"]["scene"],
            "zone_count": 263,
            "training_events": 2,
            "test_events": 1,
            "raw_tlc_files": len(historical_resources) + len(current_resources),
            "raw_tlc_rows": historical_rows + current_rows,
            "raw_tlc_bytes": historical_bytes + current_bytes,
            "daily_zone_rows": zone_footer["row_count"],
            "daily_od_rows": od_footer["row_count"],
            "expected_weekly_rows": 50496,
            "expected_prediction_keys": 3156,
            "free_bytes": free_bytes,
        },
        "metadata_only_guarantee": {
            "parquet_row_groups_scanned": 0,
            "post_action_2025_target_rows_read": 0,
            "parquet_footers_read": [zone_footer, od_footer, event_footer],
            "raw_file_hash_reverification_deferred_to_rc1": True,
        },
        "readiness": {
            "data_download_blocker": False,
            "disk_space_blocker": free_bytes < MINIMUM_FREE_BYTES,
            "definition_blocker": False,
            "remaining_work": [
                "materialize and hash the 50,496-row action-aligned weekly bundle",
                "freeze Runtime-R3 and evaluator contracts",
                "run five models plus six negative controls",
                "publish the frozen score and action-transfer claim decision",
            ],
        },
        "next_permitted_action": (
            "Materialize the weekly development/test bundle without using 2025 post-action rows for fitting, selection, normalization or graph construction."
            if passed
            else "Fix failed metadata or protocol checks before materializing any V4 bundle."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V4.0-draft1: {report['status']}")
    print(f"Preflight report: {output_path}")
    return report


if __name__ == "__main__":
    result = preflight()
    raise SystemExit(0 if result["status"].startswith("PASS_") else 1)
