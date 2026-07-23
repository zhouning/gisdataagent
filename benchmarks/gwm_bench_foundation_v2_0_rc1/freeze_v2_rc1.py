#!/usr/bin/env python3
"""Freeze the GWM-Bench Foundation V2.0 release-candidate protocol."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_ROOT = Path(__file__).resolve().parent
V0_ROOT = REPO_ROOT / "benchmarks/gwm_bench_foundation_v0_1"
TWM_ROOT = V0_ROOT / "development/multiregion_temporal_holdout/twm_v2_frozen_2026"
FLUS_ROOT = RELEASE_ROOT / "flus_2026_precommit"
LABEL_MANIFEST = (
    REPO_ROOT
    / "data/twm_public_landcover/gee_dynamic_world/twm_v2_2026_hidden_label_registration.json"
)
DEFAULT_OUTPUT = RELEASE_ROOT / "suite_protocol.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, *, role: str) -> dict[str, Any]:
    path = path.resolve()
    try:
        stored_path = str(path.relative_to(REPO_ROOT))
        path_scope = "repository_relative"
    except ValueError:
        stored_path = str(path)
        path_scope = "external_absolute"
    return {
        "path": stored_path,
        "path_scope": path_scope,
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def freeze_v2_rc1(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    if LABEL_MANIFEST.is_file():
        raise RuntimeError("refusing_v2_rc1_freeze_after_hidden_label_registration")

    data_validation_path = V0_ROOT / "development/data_validation_report.json"
    data_validation = _load_json(data_validation_path)
    if (
        data_validation["status"] != "data_validation_passed"
        or len(data_validation["checks"]) != 13
        or not all(data_validation["checks"].values())
    ):
        raise ValueError("v2_rc1_data_validation_not_passed")

    twm_protocol_path = TWM_ROOT / "precommit_protocol.json"
    twm_verification_path = TWM_ROOT / "precommit_verification.json"
    twm_evaluator_seal_path = TWM_ROOT / "evaluator_implementation_seal.json"
    twm_protocol = _load_json(twm_protocol_path)
    twm_verification = _load_json(twm_verification_path)
    if (
        twm_protocol["status"]
        != "candidate_and_predictions_sealed_before_2026_labels"
        or twm_protocol["integrity"]["2026_label_pixels_accessed"]
        or twm_verification["status"]
        != "2026_precommit_integrity_verified_without_labels"
        or twm_verification["2026_label_pixels_accessed"]
    ):
        raise ValueError("v2_rc1_twm_precommit_invalid")

    flus_protocol_path = FLUS_ROOT / "precommit_protocol.json"
    flus_protocol = _load_json(flus_protocol_path)
    if (
        flus_protocol["status"]
        != "flus_candidate_and_predictions_sealed_before_2026_labels"
        or flus_protocol["integrity"]["hidden_label_pixels_accessed"]
        or flus_protocol["forecast_years"] != list(range(2021, 2027))
    ):
        raise ValueError("v2_rc1_flus_precommit_invalid")

    artifacts = {
        "benchmark_contract": _artifact(
            V0_ROOT / "benchmark_contract.json", role="foundation_contract"
        ),
        "bundle_manifest": _artifact(
            V0_ROOT / "development/bundle_manifest.json",
            role="materialized_data_manifest",
        ),
        "data_validation": _artifact(
            data_validation_path, role="independent_data_validation"
        ),
        "runtime_contract": _artifact(
            REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/contracts.py",
            role="current_dam_gk_state_action_graph_contract",
        ),
        "twm_protocol": _artifact(
            twm_protocol_path, role="sealed_twm_2026_protocol"
        ),
        "twm_verification": _artifact(
            twm_verification_path, role="twm_deterministic_replay_evidence"
        ),
        "twm_evaluator_seal": _artifact(
            twm_evaluator_seal_path, role="sealed_twm_hidden_evaluator"
        ),
        "twm_prediction": _artifact(
            REPO_ROOT / twm_protocol["artifacts"]["prediction"]["path"],
            role="precommitted_twm_prediction_2021_2026",
        ),
        "persistence_prediction": _artifact(
            REPO_ROOT
            / twm_protocol["artifacts"]["baselines"]["persistence"]["path"],
            role="precommitted_persistence_prediction_2021_2026",
        ),
        "fixed_adjacency_prediction": _artifact(
            REPO_ROOT
            / twm_protocol["artifacts"]["baselines"]["fixed_adjacency"]["path"],
            role="precommitted_fixed_adjacency_prediction_2021_2026",
        ),
        "flus_protocol": _artifact(
            flus_protocol_path, role="sealed_flus_2026_protocol"
        ),
        "flus_prediction": _artifact(
            REPO_ROOT / flus_protocol["artifacts"]["prediction"]["path"],
            role="precommitted_flus_prediction_2021_2026",
        ),
        "scorer": _artifact(
            RELEASE_ROOT / "score_v2_2026_hidden.py",
            role="sealed_v2_hidden_scorer",
        ),
        "scorer_dependency": _artifact(
            V0_ROOT / "score_twm_v2_2026_hidden.py",
            role="sealed_label_registration_and_metric_dependency",
        ),
    }

    protocol = {
        "schema": "gwm_bench.foundation_v2_rc1_protocol.v1",
        "suite_id": "GWM-BENCH-FOUNDATION-V2.0-RC1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "rc1_candidates_and_evaluator_sealed_labels_pending",
        "definition": (
            "A prospective, label-blind test of reproducible GWM spatial-state "
            "rollout with public DAM-GK conformance and a common TWM-FLUS scorecard."
        ),
        "dataset": {
            "region_count": 20,
            "unique_node_count": 1055,
            "directed_edge_count": 3338,
            "forecast_origin_year": 2020,
            "forecast_years": list(range(2021, 2027)),
            "scored_year": 2026,
            "source_resolution_m": 100,
            "scored_row_count_per_model": 1055,
        },
        "tracks": {
            "RUNTIME-R1": {
                "status": "benchmark_runtime_contract_ready",
                "gates": [
                    "versioned state-action-context-graph contract",
                    "artifact and prediction hashes",
                    "deterministic TWM replay from frozen weights",
                    "label-blind model routing",
                    "auditable run and source lineage",
                ],
                "shared_cross_domain_runtime_product_claimed": False,
            },
            "CONTROLLED-C1": {
                "status": "public_conformance_ready",
                "sample_count": 128,
                "purpose": (
                    "Check DAM-GK action gates, directed relations, topology, lags, "
                    "state deltas and affected nodes against exact synthetic truth."
                ),
                "hidden_real_action_effect_claimed": False,
            },
            "OBSERVED-O2": {
                "status": "twm_flus_predictions_sealed_labels_pending",
                "models": [
                    "frozen TWM V2 three-seed ensemble",
                    "GeoSOS FLUS full-grid three-seed ensemble",
                    "persistence",
                    "fixed adjacency",
                ],
                "primary_metric": "unweighted_mean_of_20_region_2026_change_f1",
                "secondary_metrics": [
                    "overall_change_f1",
                    "changed_destination_macro_f1",
                    "overall_class_macro_f1",
                    "multiclass_brier_score",
                    "predicted_to_observed_change_ratio",
                ],
                "comparison": (
                    "paired 20-region bootstrap of TWM minus FLUS change F1; "
                    "20,000 draws with seed 20260723"
                ),
                "single_composite_score": False,
            },
        },
        "hidden_labels": {
            "status": "pending_full_calendar_2026_labels",
            "required_source": "GOOGLE/DYNAMICWORLD/V1 annual mode label",
            "required_years": [2025, 2026],
            "required_region_count": 20,
            "required_grid": "exact match to each frozen 2020 reference raster",
            "observation_window_utc": [
                "2026-01-01T00:00:00Z",
                "2027-01-01T00:00:00Z",
            ],
            "earliest_valid_export_date": "2027-01-01",
            "manifest_path": str(LABEL_MANIFEST.relative_to(REPO_ROOT)),
            "manifest_present_during_rc1_freeze": False,
            "pixels_accessed_during_rc1_freeze": False,
        },
        "artifacts": artifacts,
        "prediction_commitments": {
            "twm": {
                "sha256": artifacts["twm_prediction"]["sha256"],
                "predicted_2026_change_count": twm_verification[
                    "ensemble_predicted_2026_change_count"
                ],
            },
            "flus": {
                "sha256": artifacts["flus_prediction"]["sha256"],
                "predicted_2026_change_count": flus_protocol[
                    "prediction_summary"
                ]["predicted_2026_change_count"],
            },
        },
        "finalization_gates": [
            "all RC1 artifact hashes still match",
            "full-calendar 2025 and 2026 labels registered no earlier than 2027-01-01",
            "hidden grids and region set pass the sealed validator",
            "the sealed scorer runs once without model or threshold changes",
            "TWM, FLUS and internal-baseline results are published even if TWM loses",
        ],
        "benchmark_completion_rule": {
            "model_win_required": False,
            "negative_result_publishable": True,
            "insufficient_change_labels": "completed_but_model_result_inconclusive",
        },
        "claim_boundary": {
            "supports_on_finalization": [
                "bounded prospective 2026 temporal evaluation on 20 existing regions",
                "same-protocol TWM versus full-grid FLUS comparison",
                "public DAM-GK mechanism conformance",
                "benchmark-level runtime reproducibility and auditability",
            ],
            "does_not_support": [
                "identified real-world policy or action effects",
                "new-geography generalization",
                "operational forecasting validation",
                "shared cross-domain GWM Runtime Kernel product completion",
                "general TWM or GWM validity",
            ],
        },
    }
    fingerprint = json.dumps(
        {
            "suite_id": protocol["suite_id"],
            "dataset": protocol["dataset"],
            "tracks": protocol["tracks"],
            "hidden_labels": protocol["hidden_labels"],
            "artifacts": protocol["artifacts"],
            "finalization_gates": protocol["finalization_gates"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    protocol["suite_fingerprint"] = hashlib.sha256(fingerprint).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": protocol["status"],
                "suite_fingerprint": protocol["suite_fingerprint"],
                "protocol": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return protocol


if __name__ == "__main__":
    freeze_v2_rc1()
