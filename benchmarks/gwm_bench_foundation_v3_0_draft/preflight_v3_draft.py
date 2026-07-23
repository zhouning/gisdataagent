#!/usr/bin/env python3
"""Validate the V3 draft without acquiring or reading lockbox targets."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
REGION_PATH = DRAFT_ROOT / "lockbox_regions.json"
DEFAULT_OUTPUT = DRAFT_ROOT / "preflight_report.json"
DOWNLOADER_PATH = REPO_ROOT / "scripts/download_twm_gee_dynamic_world_benchmark.py"
MINIMUM_FREE_BYTES = 20 * 1024**3


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


def _bbox_intersects(left: list[float], right: list[float]) -> bool:
    return max(left[0], right[0]) < min(left[2], right[2]) and max(
        left[1], right[1]
    ) < min(left[3], right[3])


def _pairwise_overlap_ids(regions: list[dict[str, Any]]) -> list[list[str]]:
    overlaps: list[list[str]] = []
    for index, left in enumerate(regions):
        for right in regions[index + 1 :]:
            if _bbox_intersects(left["bbox"], right["bbox"]):
                overlaps.append([left["region_id"], right["region_id"]])
    return overlaps


def _cross_overlap_ids(
    lockbox_regions: list[dict[str, Any]],
    development_regions: list[dict[str, Any]],
) -> list[list[str]]:
    overlaps: list[list[str]] = []
    for lockbox in lockbox_regions:
        for development in development_regions:
            if _bbox_intersects(lockbox["bbox"], development["bbox"]):
                overlaps.append(
                    [lockbox["region_id"], development["region_id"]]
                )
    return overlaps


def _target_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for path in root.rglob("*")
        if path.is_file()
    )


def preflight(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    lockbox = _load_json(REGION_PATH)
    development_manifest_path = _repo_path(
        protocol["dataset"]["development_region_manifest"]
    )
    development = _load_json(development_manifest_path)

    lockbox_regions = lockbox["regions"]
    development_regions = development["regions"]
    lockbox_ids = [row["region_id"] for row in lockbox_regions]
    city_names = [row["city"] for row in lockbox_regions]
    strata = lockbox["strata"]
    stratum_ids = {row["stratum_id"] for row in strata}
    stratum_member_ids = [
        region_id for row in strata for region_id in row["region_ids"]
    ]

    input_years = protocol["dataset"]["allowed_input_years"]
    target_years = protocol["dataset"]["lockbox_target_years"]
    target_root = _repo_path(protocol["dataset"]["phase_c_target_root"])
    input_root = _repo_path(protocol["dataset"]["phase_a_input_root"])
    commitment_root = _repo_path(
        protocol["dataset"]["phase_b_commitment_root"]
    )
    target_files = _target_files(target_root)

    new_overlaps = _pairwise_overlap_ids(lockbox_regions)
    development_overlaps = _cross_overlap_ids(
        lockbox_regions, development_regions
    )
    expected_width, expected_height = lockbox["bbox_size_degrees"]
    boxes_valid = all(
        len(row["bbox"]) == 4
        and -180.0 <= row["bbox"][0] < row["bbox"][2] <= 180.0
        and -90.0 <= row["bbox"][1] < row["bbox"][3] <= 90.0
        and abs((row["bbox"][2] - row["bbox"][0]) - expected_width)
        <= 1e-9
        and abs((row["bbox"][3] - row["bbox"][1]) - expected_height)
        <= 1e-9
        for row in lockbox_regions
    )
    strata_valid = (
        len(strata) == 5
        and all(len(row["region_ids"]) == 4 for row in strata)
        and sorted(stratum_member_ids) == sorted(lockbox_ids)
        and all(row["stratum_id"] in stratum_ids for row in lockbox_regions)
        and all(
            row["region_id"]
            in next(
                item["region_ids"]
                for item in strata
                if item["stratum_id"] == row["stratum_id"]
            )
            for row in lockbox_regions
        )
    )

    downloader_text = (
        DOWNLOADER_PATH.read_text(encoding="utf-8")
        if DOWNLOADER_PATH.is_file()
        else ""
    )
    downloader_capabilities = all(
        token in downloader_text
        for token in (
            "--regions-json",
            "--years",
            "--project",
            "--output-dir",
            "--manifest-output",
            'ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")',
        )
    )
    free_bytes = shutil.disk_usage(REPO_ROOT).free
    current_state = protocol["current_state"]
    phase_a_validated = bool(
        current_state.get("phase_a_inputs_acquired")
        and current_state.get("phase_a_inputs_validated")
    )
    phase_a_bundle_verified = bool(
        phase_a_validated
        and current_state.get("phase_a_bundle_materialized")
        and current_state.get("phase_a_bundle_verified")
    )
    runtime_and_evaluator_sealed = bool(
        phase_a_bundle_verified
        and current_state.get("protocol_frozen")
        and current_state.get("runtime_r2_contract_frozen")
        and current_state.get("submission_contract_frozen")
        and current_state.get("evaluator_conformance_passed")
        and current_state.get("evaluator_sealed")
    )
    checks = {
        "protocol_schema_and_status_valid": protocol["schema"]
        == "gwm_bench.foundation_v3_draft_protocol.v1"
        and protocol["status"]
        in {
            "draft_ready_for_label_safe_phase_a",
            "draft_phase_a_inputs_validated",
            "draft_phase_a_bundle_verified",
            "draft_runtime_r2_evaluator_sealed_predictions_pending",
        },
        "development_manifest_exists": development_manifest_path.is_file(),
        "development_region_count_is_20": len(development_regions)
        == protocol["dataset"]["development_region_count"]
        == 20,
        "lockbox_region_count_is_20": len(lockbox_regions)
        == protocol["dataset"]["lockbox_region_count"]
        == 20,
        "lockbox_ids_and_cities_are_unique": len(set(lockbox_ids))
        == len(lockbox_ids)
        and len(set(city_names)) == len(city_names),
        "lockbox_boxes_are_fixed_and_valid": boxes_valid,
        "five_geographic_strata_have_four_regions_each": strata_valid,
        "lockbox_regions_do_not_overlap_each_other": not new_overlaps,
        "lockbox_regions_do_not_overlap_development_regions": not development_overlaps,
        "region_selection_declares_no_target_label_use": not lockbox[
            "target_labels_inspected_for_selection"
        ],
        "input_and_target_years_are_disjoint": not set(input_years)
        & set(target_years),
        "forecast_year_partition_is_exact": input_years
        == list(range(2017, 2023))
        and target_years == list(range(2023, 2026))
        and protocol["dataset"]["forecast_origin_year"] == 2022,
        "downloader_supports_separate_phase_a_acquisition": downloader_capabilities,
        "target_directory_contains_no_files": not target_files,
        "protocol_records_no_target_pixel_access": not protocol[
            "label_firewall"
        ]["target_pixels_accessed_by_v3_pipeline"],
        "no_prediction_or_score_state_is_claimed": not current_state[
            "predictions_committed"
        ]
        and not current_state["target_labels_acquired"]
        and not current_state["scores_available"],
        "phase_a_state_matches_protocol_status": (
            protocol["status"]
            == "draft_runtime_r2_evaluator_sealed_predictions_pending"
            and runtime_and_evaluator_sealed
        )
        or (
            protocol["status"] == "draft_phase_a_bundle_verified"
            and phase_a_bundle_verified
            and not runtime_and_evaluator_sealed
        )
        or (
            protocol["status"] == "draft_phase_a_inputs_validated"
            and phase_a_validated
            and not phase_a_bundle_verified
        )
        or (
            protocol["status"] == "draft_ready_for_label_safe_phase_a"
            and not phase_a_validated
        ),
        "benchmark_completion_does_not_require_twm_win": not protocol[
            "benchmark_completion_rule"
        ]["model_win_required"]
        and protocol["benchmark_completion_rule"]["negative_result_publishable"],
        "hydro_and_intervention_extensions_are_non_blocking": not protocol[
            "extension_policy"
        ]["extension_failure_blocks_v3_core"],
        "claim_boundary_rejects_causal_and_general_gwm_claims": (
            "identified real-world policy or action effects"
            in protocol["claim_boundary"]["does_not_support"]
            and "general TWM, DAM-GK or GWM validity"
            in protocol["claim_boundary"]["does_not_support"]
        ),
        "temporary_workspace_has_at_least_20_gib_free": free_bytes
        >= MINIMUM_FREE_BYTES,
    }
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v3_draft_preflight.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "PASS_RUNTIME_R2_EVALUATOR_SEALED_LABEL_FIREWALL_INTACT"
            if passed and runtime_and_evaluator_sealed
            else "PASS_PHASE_A_BUNDLE_LABEL_FIREWALL_INTACT"
            if passed and phase_a_bundle_verified
            else "PASS_PHASE_A_LABEL_FIREWALL_INTACT"
            if passed and phase_a_validated
            else "PASS_READY_FOR_PHASE_A"
            if passed
            else "FAIL"
        ),
        "protocol_sha256": _sha256(PROTOCOL_PATH),
        "lockbox_region_manifest_sha256": _sha256(REGION_PATH),
        "development_manifest_sha256": _sha256(development_manifest_path),
        "check_count": len(checks),
        "checks": checks,
        "summary": {
            "development_region_count": len(development_regions),
            "lockbox_region_count": len(lockbox_regions),
            "geographic_stratum_count": len(strata),
            "input_years": input_years,
            "target_years": target_years,
            "expected_phase_a_annual_label_raster_count": len(lockbox_regions)
            * len(input_years),
            "input_root_exists": input_root.exists(),
            "prediction_commitment_root_exists": commitment_root.exists(),
            "target_root_exists": target_root.exists(),
            "target_file_count": len(target_files),
            "free_bytes": free_bytes,
        },
        "label_firewall": {
            "target_pixels_read_by_preflight": False,
            "target_file_names_seen": target_files,
            "target_acquisition_permitted_now": False,
        },
        "next_permitted_action": (
            "Run and commit all five model predictions; do not acquire targets."
            if passed and runtime_and_evaluator_sealed
            else "Freeze Runtime-R2 submission and evaluator contracts; do not acquire targets."
            if passed and phase_a_bundle_verified
            else "Materialize fixed nodes and graphs; do not acquire targets."
            if passed and phase_a_validated
            else "Acquire only 2017-2022 Phase A inputs for the 20 lockbox regions."
            if passed
            else "Fix failed preflight checks without acquiring target labels."
        ),
        "phase_a_command": [
            ".venv/bin/python",
            "scripts/download_twm_gee_dynamic_world_benchmark.py",
            "--project",
            protocol["dataset"]["source"]["earth_engine_project"],
            "--regions-json",
            str(REGION_PATH.relative_to(REPO_ROOT)),
            "--years",
            ",".join(str(year) for year in input_years),
            "--driver-years",
            ",".join(str(year) for year in input_years),
            "--include-drivers",
            "--output-dir",
            str(input_root.relative_to(REPO_ROOT)),
            "--manifest-output",
            str((input_root / "manifest.json").relative_to(REPO_ROOT)),
            "--status-output",
            str((input_root / "download_status.json").relative_to(REPO_ROOT)),
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V3.0-draft1: {report['status']}")
    print(f"Preflight report: {output_path}")
    return report


if __name__ == "__main__":
    result = preflight()
    raise SystemExit(0 if result["status"].startswith("PASS_") else 1)
