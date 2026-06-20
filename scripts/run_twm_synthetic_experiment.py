#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.territory_world_model import (  # noqa: E402
    TerritoryWorldModelService,
    TwmEvidenceItem,
    TwmRepository,
    TwmReviewTask,
    TwmRuleHit,
    TwmStateObject,
    TwmStateRelation,
    TwmStateVersion,
    evidence_checksum,
)
from data_agent.territory_world_model.utils import read_csv, safe_float, safe_int, truthy  # noqa: E402


DEFAULT_INPUT = REPO_ROOT / "docs/reports/twm_synthetic_experiment_foundation.csv"
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_synthetic_experiment_runner_report.json"

CLAIM_BOUNDARY = "synthetic_experiment_only_not_for_production"

DYNAMICS_LOSS_CONTRACT = {
    "transition_loss": "targets.future_latent_state.observed_next",
    "constraint_loss": "targets.constraint_violation_probability",
    "planning_ranking_loss": "labels.ranking_score",
    "calibration_loss": "targets.calibration.calibrated_utility_delta",
    "uncertainty_calibration_loss": "targets.uncertainty.confidence",
    "evidence_consistency_loss": "evidence_gate.status",
    "action_mask_loss": "targets.action_mask.allowed",
}

EXPERIMENT_THRESHOLDS = {
    "min_total_examples": 24,
    "min_usable_examples": 24,
    "min_observed_temporal_examples": 12,
    "min_holdout_examples": 8,
    "max_scaffold_ratio": 0.0,
    "max_review_ratio": 0.0,
    "require_geofm_pass": False,
    "require_causal_pass": False,
    "min_temporal_years": 0,
}

EXPERIMENT_EVALUATION_THRESHOLDS = {
    "min_ground_truth_examples": 8,
    "max_mean_transition_error": 0.2,
    "max_mean_constraint_error": 0.25,
    "max_mean_utility_error": 0.25,
    "min_ranking_correlation_proxy": -1.0,
}

REVIEW_ONLY_GEOFM_GATE = {
    "gate_status": "review",
    "decision": "not_required_for_synthetic_core_experiment",
    "summary": {"vector_inventory": {"available": False, "record_count": 0}},
}

REVIEW_ONLY_CAUSAL_GATE = {
    "status": "review",
    "method": "synthetic_counterfactual_pair_fixture",
    "note": "review-only gate injected so core dynamics readiness does not require GeoFM or causal promotion",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the synthetic TWM simulator/planner experiment loop.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mlp-epochs", type=int, default=8)
    parser.add_argument("--include-graph", action="store_true")
    parser.add_argument("--include-transformer", action="store_true")
    parser.add_argument("--transformer-risk-calibration-weight", type=float, default=0.0)
    parser.add_argument(
        "--transformer-risk-head-mode",
        default="context_residual",
        choices=("shared", "context_residual"),
        help="Transformer constraint-risk head structure for synthetic simulator experiments.",
    )
    parser.add_argument(
        "--probe-transformer-risk-weights",
        default="",
        help="Optional comma-separated transformer risk calibration weights to probe outside the main backend ranking.",
    )
    args = parser.parse_args()

    report = run_synthetic_experiment(
        args.input,
        mlp_epochs=args.mlp_epochs,
        include_graph=args.include_graph,
        include_transformer=args.include_transformer,
        transformer_risk_calibration_weight=args.transformer_risk_calibration_weight,
        transformer_risk_head_mode=args.transformer_risk_head_mode,
        probe_transformer_risk_weights=parse_weight_list(args.probe_transformer_risk_weights),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def run_synthetic_experiment(
    input_path: Path = DEFAULT_INPUT,
    *,
    mlp_epochs: int = 8,
    include_graph: bool = False,
    include_transformer: bool = False,
    transformer_risk_calibration_weight: float = 0.0,
    transformer_risk_head_mode: str = "context_residual",
    probe_transformer_risk_weights: list[float] | None = None,
) -> dict[str, Any]:
    rows = read_csv(input_path)
    svc = build_experiment_service()
    state_id = create_synthetic_experiment_state(svc, rows, source_path=input_path)
    state = svc.repository.get_state_version(state_id)
    if state is None:
        raise LookupError(f"state not found: {state_id}")

    dataset = synthetic_rows_to_dynamics_dataset(
        rows,
        state_id=state_id,
        project_id=state.project_id,
        source_path=input_path,
        state_summary=dict(state.summary or {}),
    )
    payload = experiment_payload(dataset)
    readiness = svc.dynamics_readiness_report(state_id, payload)
    fit_report = svc.fit_dynamics_candidate(state_id, payload)
    fit_report_for_consumers = candidate_report_with_rollout_aliases(
        fit_report,
        dataset,
        horizon=2,
    )
    eval_report = svc.dynamics_evaluation_report(
        state_id,
        {
            **payload,
            "candidate": fit_report.get("candidate") or {},
            "predictions": fit_report.get("predictions") or {},
        },
    )
    backend_report = svc.dynamics_backend_report(
        state_id,
        {
            **payload,
            "backend": {
                "backend_id": "synthetic_hierarchical_baseline",
                "backend_type": "synthetic_experiment_candidate",
                "model_name": (fit_report.get("candidate") or {}).get("model_name", "hierarchical_baseline_dynamics"),
                "model_version": (fit_report.get("candidate") or {}).get("model_version", "synthetic_experiment_v1"),
                "model_family": (fit_report.get("candidate") or {}).get("model_family", "action_conditioned_hierarchical_baseline"),
                "trainable": False,
                "action_conditioned": True,
                "uses_geofm": False,
                "uses_causal_calibration": False,
                "is_scaffold_baseline": False,
            },
            "candidate_report": fit_report_for_consumers,
        },
    )
    objective_report = svc.training_objective_report(
        state_id,
        {
            **payload,
            "dynamics_backend_report": backend_report,
            "predictions": fit_report.get("predictions") or {},
        },
    )
    backend_comparison = run_backend_comparison(
        svc,
        state_id,
        dataset,
        payload,
        baseline_fit_report=fit_report,
        baseline_backend_report=backend_report,
        baseline_objective_report=objective_report,
        mlp_epochs=mlp_epochs,
        include_graph=include_graph,
        include_transformer=include_transformer,
        transformer_risk_calibration_weight=transformer_risk_calibration_weight,
        transformer_risk_head_mode=transformer_risk_head_mode,
    )
    transformer_risk_weight_probe = (
        run_transformer_risk_weight_probe(
            svc,
            state_id,
            dataset,
            payload,
            mlp_epochs=mlp_epochs,
            weights=probe_transformer_risk_weights,
            risk_head_mode=transformer_risk_head_mode,
        )
        if include_transformer and probe_transformer_risk_weights
        else {}
    )
    transformer_risk_head_probe = (
        run_transformer_risk_head_probe(
            svc,
            state_id,
            dataset,
            payload,
            mlp_epochs=mlp_epochs,
        )
        if include_transformer
        else {}
    )
    action_mask_stress = run_action_mask_calibration_stress(dataset, baseline_prediction_report=fit_report)
    beam_plan = svc.beam_plan(
        state_id,
        {
            "scenario": "synthetic_twm_planner_consumer",
            "target_role": "project",
            "evidence_coverage": 1.0,
            "auto_action_mask": True,
            "actions": planner_actions_from_dataset(dataset),
            "dynamics_candidate_report": fit_report_for_consumers,
            "dynamics_candidate_required_status": "pass",
            "allow_review_dynamics_candidate": True,
            "limit": 4,
        },
    )
    rollout = svc.counterfactual_rollout(
        state_id,
        {
            "scenario": "synthetic_twm_counterfactual_rollout",
            "horizon": 2,
            "evidence_coverage": 1.0,
            "baseline_action": {
                "action_type": "inspect",
                "target_role": "project",
                "magnitude": 1.0,
            },
            "intervention_actions": planner_actions_from_dataset(dataset)[:2],
            "dynamics_candidate_report": fit_report_for_consumers,
            "dynamics_candidate_required_status": "pass",
            "allow_review_dynamics_candidate": True,
        },
    )

    report_status = synthetic_runner_status(readiness, fit_report, eval_report, beam_plan)
    return {
        "schema": "territory_world_model.synthetic_experiment_runner_report.v1",
        "status": report_status,
        "claim_boundary": CLAIM_BOUNDARY,
        "source": {
            "input_path": str(input_path),
            "row_count": len(rows),
        },
        "state": {
            "state_version_id": state_id,
            "project_id": state.project_id,
            "object_count": state.object_count,
            "relation_count": state.relation_count,
            "summary": state.summary,
        },
        "dataset_summary": dataset_summary(dataset),
        "readiness": summarize_report(readiness),
        "fit": summarize_fit_report(fit_report),
        "consumer_adapter": summarize_consumer_adapter(fit_report, fit_report_for_consumers),
        "evaluation": summarize_evaluation_report(eval_report),
        "backend": summarize_backend_report(backend_report),
        "objective": summarize_objective_report(objective_report),
        "backend_comparison": backend_comparison,
        "transformer_risk_weight_probe": transformer_risk_weight_probe,
        "transformer_risk_head_probe": transformer_risk_head_probe,
        "action_mask_stress": action_mask_stress,
        "planner_holdout_analysis": backend_comparison.get("selected_planner_holdout_analysis") or {},
        "planner_rollout_matrix": backend_comparison.get("selected_planner_rollout_matrix") or {},
        "planner": summarize_beam_plan(beam_plan),
        "rollout": summarize_rollout(rollout),
        "innovation_focus": {
            "renderer": "hierarchical GIS object/relation/rule/evidence state contract used by the simulator",
            "simulator": "action-conditioned multi-head territorial dynamics over next state, constraint, utility, uncertainty and action mask",
            "planner": "consumer that ranks actions using simulator outputs; it is not the TWM core",
            "key_substantive_innovation": "synthetic experiment exercises a GIS-native, evidence-gated, action-conditioned territorial simulator instead of a flat table predictor or standalone planner",
        },
    }


def build_experiment_service() -> TerritoryWorldModelService:
    return TerritoryWorldModelService(repository=TwmRepository(engine=None, persist_to_db=False))


def parse_weight_list(raw: str | None) -> list[float]:
    weights: list[float] = []
    for item in str(raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        value = safe_float(item, None)
        if value is None:
            raise ValueError(f"invalid risk calibration weight: {item}")
        weights.append(round(max(0.0, min(2.0, float(value))), 6))
    return weights


def create_synthetic_experiment_state(
    svc: TerritoryWorldModelService,
    rows: list[dict[str, Any]],
    *,
    source_path: Path,
) -> str:
    project = svc.create_project(
        {
            "name": "TWM Synthetic Experiment Runner",
            "region_code": "SYN-TWM",
            "business_scenario": "synthetic_planning_supervision",
            "metadata": {
                "synthetic": True,
                "not_for_production": True,
                "claim_boundary": CLAIM_BOUNDARY,
            },
        },
        username="synthetic-runner",
    )
    region_codes = sorted({str(row.get("region_code") or "SYN-R00") for row in rows}) or ["SYN-R00"]
    periods = sorted({str(row.get("period") or "period_0") for row in rows}) or ["period_0"]
    actions = sorted({str(row.get("action_type") or "inspect") for row in rows}) or ["inspect"]
    object_counts_by_role = {
        "county": 1,
        "township": len(region_codes),
        "block": len(region_codes) * 2,
        "parcel": len(rows),
        "project": len(rows),
    }
    relation_counts_by_type = {
        "county_contains_township": len(region_codes),
        "township_contains_block": len(region_codes) * 2,
        "block_contains_parcel": len(rows),
        "project_overlaps_planning_zone": len(rows),
        "annual_change_of_parcel": max(0, len(rows) - len(region_codes)),
    }
    state = TwmStateVersion(
        project_id=project["id"],
        label="synthetic experiment hierarchical state",
        source_manifest={
            "synthetic_experiment_foundation": str(source_path),
            "claim_boundary": CLAIM_BOUNDARY,
        },
        object_count=sum(object_counts_by_role.values()),
        relation_count=sum(relation_counts_by_type.values()),
        quality_summary={
            "object_count": sum(object_counts_by_role.values()),
            "relation_count": sum(relation_counts_by_type.values()),
            "evidence_coverage": 1.0,
            "synthetic_object_count": sum(object_counts_by_role.values()),
            "not_for_production_object_count": 0,
            "qa_disabled_object_count": 0,
            "source_row_count": len(rows),
            "region_count": len(region_codes),
            "period_count": len(periods),
            "action_count": len(actions),
            "claim_boundary": CLAIM_BOUNDARY,
        },
        build_status="ready",
        summary={
            "object_counts_by_role": object_counts_by_role,
            "relation_counts_by_type": relation_counts_by_type,
            "metric_crs": "EPSG:4326",
            "synthetic": True,
            "not_for_production": True,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        created_by="synthetic-runner",
    )
    svc.repository.save_state_version(state)
    objects = build_state_objects(state.id, rows, region_codes)
    relations = build_state_relations(state.id, objects, rows, region_codes)
    svc.repository.save_state_objects(objects)
    svc.repository.save_state_relations(relations)
    first_project = next((obj for obj in objects if obj.canonical_role == "project"), objects[0])
    hit = TwmRuleHit(
        state_version_id=state.id,
        rule_id="TWM-SYN-001",
        subject_object_id=first_project.id,
        hit_status="reviewed_dismissed",
        severity="info",
        risk_score=0.05,
        metrics={"synthetic_experiment": True, "claim_boundary": CLAIM_BOUNDARY},
        explanation="Synthetic experiment evidence chain for TWM runner contract validation.",
    )
    saved_hit = svc.repository.save_rule_hit(hit)
    evidence_payload = {
        "state_version_id": state.id,
        "rule_id": saved_hit.rule_id,
        "source_path": str(source_path),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    svc.repository.save_evidence_item(
        TwmEvidenceItem(
            rule_hit_id=saved_hit.id,
            evidence_type="synthetic_experiment_source",
            source_system="twm_synthetic_runner",
            source_ref=str(source_path),
            payload=evidence_payload,
            checksum=evidence_checksum(evidence_payload),
        )
    )
    svc.repository.save_review_task(
        TwmReviewTask(
            rule_hit_id=saved_hit.id,
            assignee="synthetic-runner",
            status="closed",
            decision="experiment_contract_only",
            comment="Synthetic experiment is review-only and not production evidence.",
        )
    )
    return state.id


def build_state_objects(state_id: str, rows: list[dict[str, Any]], region_codes: list[str]) -> list[TwmStateObject]:
    objects: list[TwmStateObject] = []
    county = TwmStateObject(
        state_version_id=state_id,
        object_type="admin_county",
        object_code="SYN-TWM-COUNTY",
        source_role="county",
        canonical_role="county",
        attributes={"region_code": "SYN-TWM", "synthetic_experiment": True},
        semantic_tags=["county", "synthetic_experiment"],
        quality_score=1.0,
        synthetic=True,
        not_for_production=False,
    )
    objects.append(county)
    for region_idx, region_code in enumerate(region_codes):
        township = TwmStateObject(
            state_version_id=state_id,
            object_type="admin_township",
            object_code=f"{region_code}-TOWNSHIP",
            source_role="township",
            canonical_role="township",
            attributes={"region_code": region_code, "synthetic_experiment": True},
            semantic_tags=["township", "synthetic_experiment"],
            quality_score=1.0,
            synthetic=True,
            not_for_production=False,
        )
        objects.append(township)
        for block_idx in range(2):
            objects.append(
                TwmStateObject(
                    state_version_id=state_id,
                    object_type="planning_block",
                    object_code=f"{region_code}-BLOCK-{block_idx}",
                    source_role="block",
                    canonical_role="block",
                    attributes={"region_code": region_code, "block_index": block_idx, "synthetic_experiment": True},
                    semantic_tags=["block", "synthetic_experiment"],
                    quality_score=1.0,
                    synthetic=True,
                    not_for_production=False,
                )
            )
    for idx, row in enumerate(rows):
        unit_id = str(row.get("unit_id") or f"row-{idx}")
        attrs = {
            "unit_id": unit_id,
            "region_code": row.get("region_code"),
            "period": row.get("period"),
            "scenario_id": row.get("scenario_id"),
            "split": row.get("split"),
            "action_type": row.get("action_type"),
            "area_m2": safe_float(row.get("area_m2"), 0.0),
            "risk_score": safe_float(row.get("risk_score"), 0.0),
            "quality_score": safe_float(row.get("quality_score"), 0.0),
            "synthetic": truthy(row.get("synthetic")),
            "not_for_production": truthy(row.get("not_for_production")),
            "claim_boundary": CLAIM_BOUNDARY,
        }
        objects.append(
            TwmStateObject(
                state_version_id=state_id,
                object_type="synthetic_parcel",
                object_code=f"PARCEL-{unit_id}",
                source_role="parcel",
                source_feature_id=unit_id,
                source_path=str(row.get("source_path") or ""),
                canonical_role="parcel",
                attributes=attrs,
                semantic_tags=["parcel", "synthetic_experiment"],
                quality_score=safe_float(row.get("quality_score"), 1.0),
                synthetic=True,
                not_for_production=False,
            )
        )
        objects.append(
            TwmStateObject(
                state_version_id=state_id,
                object_type="synthetic_project",
                object_code=str(row.get("project_id") or f"PRJ-{unit_id}"),
                source_role="project",
                source_feature_id=str(row.get("project_id") or unit_id),
                source_path=str(row.get("source_path") or ""),
                canonical_role="project",
                attributes=attrs | {"parcel_unit_id": unit_id},
                semantic_tags=["project", "synthetic_experiment"],
                quality_score=safe_float(row.get("quality_score"), 1.0),
                synthetic=True,
                not_for_production=False,
            )
        )
    return objects


def build_state_relations(
    state_id: str,
    objects: list[TwmStateObject],
    rows: list[dict[str, Any]],
    region_codes: list[str],
) -> list[TwmStateRelation]:
    relations: list[TwmStateRelation] = []
    by_code = {obj.object_code: obj for obj in objects}
    county = by_code["SYN-TWM-COUNTY"]
    for region_code in region_codes:
        township = by_code.get(f"{region_code}-TOWNSHIP")
        if township:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=county.id,
                    predicate="contains",
                    object_object_id=township.id,
                    relation_type="county_contains_township",
                    metrics={"synthetic_experiment": True},
                    confidence=1.0,
                    synthetic=True,
                    not_for_production=False,
                )
            )
        for block_idx in range(2):
            block = by_code.get(f"{region_code}-BLOCK-{block_idx}")
            if township and block:
                relations.append(
                    TwmStateRelation(
                        state_version_id=state_id,
                        subject_object_id=township.id,
                        predicate="contains",
                        object_object_id=block.id,
                        relation_type="township_contains_block",
                        metrics={"synthetic_experiment": True, "block_index": block_idx},
                        confidence=1.0,
                        synthetic=True,
                        not_for_production=False,
                    )
                )
    sorted_rows = sorted(rows, key=lambda row: (str(row.get("unit_id") or ""), safe_int(row.get("time_index"), 0)))
    previous_by_region: dict[str, TwmStateObject] = {}
    for idx, row in enumerate(sorted_rows):
        unit_id = str(row.get("unit_id") or f"row-{idx}")
        region_code = str(row.get("region_code") or region_codes[0])
        block_idx = idx % 2
        block = by_code.get(f"{region_code}-BLOCK-{block_idx}") or by_code.get(f"{region_code}-BLOCK-0")
        parcel = by_code.get(f"PARCEL-{unit_id}")
        project = by_code.get(str(row.get("project_id") or f"PRJ-{unit_id}"))
        if block and parcel:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=block.id,
                    predicate="contains",
                    object_object_id=parcel.id,
                    relation_type="block_contains_parcel",
                    metrics={"area_m2": safe_float(row.get("area_m2"), 0.0), "time_index": safe_int(row.get("time_index"), 0)},
                    confidence=0.95,
                    synthetic=True,
                    not_for_production=False,
                )
            )
        if project and block:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=project.id,
                    predicate="overlaps",
                    object_object_id=block.id,
                    relation_type="project_overlaps_planning_zone",
                    metrics={"dominant_zone_type": "synthetic_planning_zone", "area_m2": safe_float(row.get("area_m2"), 0.0)},
                    confidence=0.95,
                    synthetic=True,
                    not_for_production=False,
                )
            )
        previous = previous_by_region.get(region_code)
        if previous and parcel:
            relations.append(
                TwmStateRelation(
                    state_version_id=state_id,
                    subject_object_id=previous.id,
                    predicate="precedes",
                    object_object_id=parcel.id,
                    relation_type="annual_change_of_parcel",
                    metrics={
                        "time_index": safe_int(row.get("time_index"), 0),
                        "treatment_effect": safe_float(row.get("treatment_effect"), 0.0),
                    },
                    confidence=0.9,
                    synthetic=True,
                    not_for_production=False,
                )
            )
        if parcel:
            previous_by_region[region_code] = parcel
    return relations


def synthetic_rows_to_dynamics_dataset(
    rows: list[dict[str, Any]],
    *,
    state_id: str,
    project_id: str,
    source_path: Path,
    state_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    treated_rows = [row for row in rows if str(row.get("approval_status") or "").lower() == "approved"]
    examples = [
        synthetic_row_to_training_example(
            row,
            idx=idx,
            state_id=state_id,
            project_id=project_id,
            source_path=source_path,
            state_summary=state_summary or {},
        )
        for idx, row in enumerate(treated_rows)
    ]
    examples.sort(key=lambda item: (item["split"], item["id"]))
    return {
        "schema": "territory_world_model.dynamics_training_dataset.v1",
        "state_version_id": state_id,
        "project_id": project_id,
        "examples": examples,
        "summary": dataset_summary_from_examples(examples, source_path=source_path, source_row_count=len(rows)),
    }


def synthetic_row_to_training_example(
    row: dict[str, Any],
    *,
    idx: int,
    state_id: str,
    project_id: str,
    source_path: Path,
    state_summary: dict[str, Any],
) -> dict[str, Any]:
    split = "candidate" if str(row.get("split") or "") == "train" else "holdout"
    action_type = str(row.get("action_type") or "protect")
    area = max(1.0, safe_float(row.get("area_m2"), 1.0) or 1.0)
    treatment_effect = safe_float(row.get("treatment_effect"), 0.0) or 0.0
    next_state_score = safe_float(row.get("next_state_score"), 0.0) or 0.0
    baseline_score = safe_float(row.get("baseline_state_score"), 0.0) or 0.0
    baseline_risk = clamp(safe_float(row.get("baseline_risk_score"), safe_float(row.get("risk_score"), 0.2)) or 0.2)
    risk_delta = safe_float(row.get("constraint_risk_delta"), 0.0) or 0.0
    constraint_probability = clamp(baseline_risk + risk_delta)
    utility_delta = safe_float(row.get("planning_utility_delta"), treatment_effect) or 0.0
    uncertainty = clamp(safe_float(row.get("uncertainty"), 0.15) or 0.15)
    confidence = clamp(1.0 - uncertainty)
    allowed = row_action_mask_allowed(row, default=constraint_probability < 0.5 and action_type != "defer_review")
    hard_blocks = row_list_value(row.get("action_mask_hard_blocks"))
    if not hard_blocks and constraint_probability >= 0.65:
        hard_blocks = ["synthetic_high_constraint_risk"]
    required_reviews = row_list_value(row.get("action_mask_required_reviews"))
    if not required_reviews and action_type == "defer_review":
        required_reviews = ["synthetic_defer_review"]
    evidence_gate = {
        "passed": True,
        "status": "pass",
        "required": ["synthetic_experiment_source", "counterfactual_pair", "spatial_context"],
        "missing": [],
        "coverage": 1.0,
        "action_mask": {
            "allowed": allowed,
            "hard_blocks": hard_blocks,
            "required_reviews": required_reviews,
            "confidence": confidence,
            "target_object_count": 1,
            "related_rule_hit_count": safe_int(row.get("rule_hit_count"), 0),
            "missing_evidence_hit_count": 0,
        },
    }
    observed_next = {
        "total_area_m2": round(max(0.001, next_state_score), 6),
        "observed_area_m2": round(area, 6),
        "state_score": round(next_state_score, 6),
        "baseline_state_score": round(baseline_score, 6),
        "land_space_types": {
            "protected_or_conditioned_space": {
                "area_m2": round(max(0.001, next_state_score) * (0.52 + max(0.0, treatment_effect)), 6),
                "observed_area_m2": round(area * (0.52 + max(0.0, treatment_effect)), 6),
                "state_score": round(next_state_score, 6),
            },
            "review_pressure_space": {
                "area_m2": round(max(0.001, next_state_score) * (0.48 - min(0.15, max(0.0, treatment_effect))), 6),
                "observed_area_m2": round(area * (0.48 - min(0.15, max(0.0, treatment_effect))), 6),
                "risk_score": round(constraint_probability, 6),
            },
        },
        "projected_risk_pressure": round(constraint_probability, 6),
        "projected_utility_delta": round(utility_delta, 6),
    }
    example_id = f"synthetic:{row.get('counterfactual_group') or idx}:{row.get('unit_id') or idx}"
    return {
        "id": example_id,
        "state_version_id": state_id,
        "project_id": project_id,
        "split": split,
        "sample_type": "temporal_state_transition",
        "current_state_summary": {
            "schema": "territory_world_model.synthetic_current_state_summary.v1",
            "object_counts_by_role": dict((state_summary or {}).get("object_counts_by_role") or {}),
            "relation_counts_by_type": dict((state_summary or {}).get("relation_counts_by_type") or {}),
            "region_code": row.get("region_code"),
            "period": row.get("period"),
            "time_index": safe_int(row.get("time_index"), 0),
            "baseline_state_score": round(baseline_score, 6),
            "baseline_risk_score": round(baseline_risk, 6),
            "quality_score": safe_float(row.get("quality_score"), 0.0),
            "area_m2": round(area, 6),
        },
        "action": {
            "action_type": action_type,
            "target_role": "project",
            "target_objects": [str(row.get("project_id") or row.get("unit_id") or "")],
            "spatial_scope": {
                "level": "synthetic_region",
                "region_code": row.get("region_code"),
                "cluster": row.get("cluster"),
                "x": safe_float(row.get("x"), None),
                "y": safe_float(row.get("y"), None),
            },
            "magnitude": round(1.0 + abs(treatment_effect), 6),
            "scenario": str(row.get("scenario_id") or "synthetic_experiment"),
            "description": "synthetic action-conditioned territorial transition",
            "legal_intent": "synthetic_experiment_contract_validation",
            "execution_mask": evidence_gate["action_mask"],
            "parameters": {
                "treatment_effect": round(treatment_effect, 6),
                "constraint_risk_delta": round(risk_delta, 6),
                "counterfactual_group": row.get("counterfactual_group"),
            },
            "treatment": "synthetic_counterfactual_treated",
        },
        "scenario_context": {
            "scenario_id": row.get("scenario_id"),
            "region_code": row.get("region_code"),
            "period": row.get("period"),
            "time_index": safe_int(row.get("time_index"), 0),
            "observed_treatment_effect": round(treatment_effect, 6),
            "synthetic_experiment": True,
            "action_mask_policy": row.get("action_mask_policy"),
            "claim_boundary": CLAIM_BOUNDARY,
        },
        "targets": {
            "future_latent_state": {
                "schema": "territory_world_model.synthetic_observed_next_state.v1",
                "observed_next": observed_next,
            },
            "constraint_violation_probability": round(constraint_probability, 6),
            "planning_utility_delta": round(utility_delta, 6),
            "uncertainty": {
                "confidence": round(confidence, 6),
                "uncertainty": round(uncertainty, 6),
                "source": "synthetic_experiment_foundation",
            },
            "calibration": {
                "calibrated_utility_delta": round(next_state_score - baseline_score, 6),
                "observed_transition_proxy": round(next_state_score - baseline_score, 6),
                "treatment_effect": round(treatment_effect, 6),
                "source": "synthetic_counterfactual_pair",
            },
            "action_mask": evidence_gate["action_mask"],
        },
        "labels": {
            "constraint_label": "violation_likely" if constraint_probability >= 0.5 else "violation_unlikely",
            "utility_label": "positive_lift" if utility_delta > 0 else "non_positive_lift",
            "ranking_score": round(utility_delta - constraint_probability + confidence * 0.1, 6),
            "evidence_supported": True,
            "supervision_source": "state_snapshots",
            "ground_truth_grade": "synthetic_experiment_label",
        },
        "losses": dict(DYNAMICS_LOSS_CONTRACT),
        "evidence_gate": evidence_gate,
        "provenance": {
            "state_version_id": state_id,
            "source_table": str(source_path),
            "source_path": str(source_path),
            "sample_index": idx,
            "sample_family": "synthetic_experiment_foundation",
            "ground_truth": True,
            "synthetic": True,
            "not_for_production": True,
            "data_role": str(row.get("data_role") or "synthetic_experiment_foundation"),
            "action_mask_policy": row.get("action_mask_policy"),
            "claim_boundary": CLAIM_BOUNDARY,
            "counterfactual_group": row.get("counterfactual_group"),
            "unit_id": row.get("unit_id"),
        },
        "not_for_training_reasons": [],
    }


def row_action_mask_allowed(row: dict[str, Any], *, default: bool) -> bool:
    value = row.get("action_mask_allowed")
    if value in {None, ""}:
        return default
    return truthy(value)


def row_list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.replace(",", "|").split("|") if item.strip()]


def dataset_summary_from_examples(
    examples: list[dict[str, Any]],
    *,
    source_path: Path,
    source_row_count: int,
) -> dict[str, Any]:
    split_counts = Counter(str(item.get("split") or "") for item in examples)
    action_counts = Counter(str((item.get("action") or {}).get("action_type") or "") for item in examples)
    action_mask_counts: dict[str, dict[str, int]] = {}
    action_mask_allowed_count = 0
    action_mask_blocked_count = 0
    for item in examples:
        action_type = str((item.get("action") or {}).get("action_type") or "")
        mask = dict((item.get("targets") or {}).get("action_mask") or {})
        allowed = bool(mask.get("allowed", True))
        bucket = action_mask_counts.setdefault(action_type, {"allowed": 0, "blocked": 0, "total": 0})
        bucket["total"] += 1
        if allowed:
            bucket["allowed"] += 1
            action_mask_allowed_count += 1
        else:
            bucket["blocked"] += 1
            action_mask_blocked_count += 1
    mixed_action_types = sorted(action for action, counts in action_mask_counts.items() if counts["allowed"] and counts["blocked"])
    regions = sorted({str((item.get("scenario_context") or {}).get("region_code") or "") for item in examples})
    periods = sorted({str((item.get("scenario_context") or {}).get("period") or "") for item in examples})
    holdout_periods = sorted({str((item.get("scenario_context") or {}).get("period") or "") for item in examples if item.get("split") == "holdout"})
    holdout_periods_by_region: dict[str, set[str]] = {}
    for item in examples:
        if item.get("split") != "holdout":
            continue
        context = item.get("scenario_context") or {}
        region_code = str(context.get("region_code") or "")
        period = str(context.get("period") or "")
        if region_code and period:
            holdout_periods_by_region.setdefault(region_code, set()).add(period)
    return {
        "schema": "territory_world_model.synthetic_dynamics_dataset_summary.v1",
        "source_path": str(source_path),
        "source_row_count": source_row_count,
        "example_count": len(examples),
        "candidate_example_count": split_counts.get("candidate", 0),
        "holdout_example_count": split_counts.get("holdout", 0),
        "observed_temporal_example_count": len(examples),
        "usable_example_count": len([item for item in examples if not item.get("not_for_training_reasons")]),
        "synthetic_example_count": len([item for item in examples if (item.get("provenance") or {}).get("synthetic")]),
        "not_for_production_example_count": len([item for item in examples if (item.get("provenance") or {}).get("not_for_production")]),
        "split_counts": dict(sorted(split_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "action_mask_allowed_count": action_mask_allowed_count,
        "action_mask_blocked_count": action_mask_blocked_count,
        "mixed_action_mask_action_types": mixed_action_types,
        "action_mask_counts_by_action_type": dict(sorted(action_mask_counts.items())),
        "region_count": len([item for item in regions if item]),
        "period_count": len([item for item in periods if item]),
        "holdout_period_count": len([item for item in holdout_periods if item]),
        "max_holdout_steps_per_region": max((len(periods) for periods in holdout_periods_by_region.values()), default=0),
        "loss_contract": dict(DYNAMICS_LOSS_CONTRACT),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def experiment_payload(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "thresholds": dict(EXPERIMENT_THRESHOLDS),
        "evaluation_thresholds": dict(EXPERIMENT_EVALUATION_THRESHOLDS),
        "geofm_gate_report": dict(REVIEW_ONLY_GEOFM_GATE),
        "causal_calibration_report": dict(REVIEW_ONLY_CAUSAL_GATE),
        "candidate": {
            "model_name": "synthetic_hierarchical_baseline_dynamics",
            "model_version": "synthetic_experiment_v1",
            "model_family": "action_conditioned_hierarchical_baseline",
            "uses_geofm": False,
            "uses_causal_calibration": False,
            "metadata": {
                "claim_boundary": CLAIM_BOUNDARY,
                "synthetic": True,
                "not_for_production": True,
            },
        },
    }


def run_backend_comparison(
    svc: TerritoryWorldModelService,
    state_id: str,
    dataset: dict[str, Any],
    payload: dict[str, Any],
    *,
    baseline_fit_report: dict[str, Any],
    baseline_backend_report: dict[str, Any],
    baseline_objective_report: dict[str, Any],
    mlp_epochs: int,
    include_graph: bool,
    include_transformer: bool,
    transformer_risk_calibration_weight: float,
    transformer_risk_head_mode: str,
) -> dict[str, Any]:
    baseline_eval = baseline_fit_report.get("evaluation") or svc.dynamics_evaluation_report(
        state_id,
        {
            **payload,
            "candidate": baseline_fit_report.get("candidate") or {},
            "predictions": baseline_fit_report.get("predictions") or {},
        },
    )
    entries = [
        summarize_backend_comparison_entry(
            candidate_id="hierarchical_baseline_fit",
            role="transparent_baseline",
            training_method="evidence_supported_action_group_means",
            dataset=dataset,
            candidate_report=baseline_fit_report,
            backend_report=baseline_backend_report,
            evaluation_report=baseline_eval,
            objective_report=baseline_objective_report,
            train_report={},
        )
    ]
    for spec in backend_experiment_specs(
        mlp_epochs=mlp_epochs,
        include_graph=include_graph,
        include_transformer=include_transformer,
        transformer_risk_calibration_weight=transformer_risk_calibration_weight,
        transformer_risk_head_mode=transformer_risk_head_mode,
    ):
        train_report = svc.train_dynamics_candidate(
            state_id,
            {
                **payload,
                "trainer": spec["trainer"],
                "training_config": spec["training_config"],
            },
        )
        candidate_report = dict(train_report.get("candidate_report") or {})
        predictions = dict(train_report.get("predictions") or candidate_report.get("predictions") or {})
        evaluation_report = svc.dynamics_evaluation_report(
            state_id,
            {
                **payload,
                "candidate": (candidate_report.get("candidate") or train_report.get("trainer") or {}),
                "predictions": predictions,
            },
        )
        consumer_candidate = candidate_report_with_rollout_aliases(candidate_report, dataset, horizon=2) if candidate_report else {}
        backend_report = svc.dynamics_backend_report(
            state_id,
            {
                **payload,
                "backend": spec["backend"],
                "candidate_report": consumer_candidate or candidate_report,
            },
        )
        objective_report = svc.training_objective_report(
            state_id,
            {
                **payload,
                "dynamics_backend_report": backend_report,
                "predictions": predictions,
            },
        )
        entries.append(
            summarize_backend_comparison_entry(
                candidate_id=spec["candidate_id"],
                role=spec["role"],
                training_method=spec["trainer"]["training_method"],
                dataset=dataset,
                candidate_report=candidate_report,
                backend_report=backend_report,
                evaluation_report=evaluation_report,
                objective_report=objective_report,
                train_report=train_report,
            )
        )
        if spec.get("calibrate_action_mask"):
            calibrated_entries = [
                (
                    "action_mask_calibrated",
                    "action_mask_calibration",
                    calibrated_action_mask_candidate_report(candidate_report, dataset),
                    spec["calibrated_backend"],
                ),
                (
                    "context_action_mask_calibrated",
                    "context_action_mask_calibration",
                    context_calibrated_action_mask_candidate_report(candidate_report, dataset),
                    spec.get("context_calibrated_backend") or spec["calibrated_backend"],
                ),
            ]
            if spec.get("calibrate_constraint_risk"):
                risk_calibrated_report = constraint_risk_calibrated_candidate_report(candidate_report, dataset)
                calibrated_entries.extend(
                    [
                        (
                            "constraint_risk_calibrated",
                            "constraint_risk_calibration",
                            risk_calibrated_report,
                            spec.get("constraint_risk_calibrated_backend") or spec["backend"],
                        ),
                        (
                            "constraint_risk_context_action_mask_calibrated",
                            "constraint_risk_calibration+context_action_mask_calibration",
                            context_calibrated_action_mask_candidate_report(risk_calibrated_report, dataset),
                            spec.get("constraint_risk_context_calibrated_backend")
                            or spec.get("context_calibrated_backend")
                            or spec["calibrated_backend"],
                        ),
                    ]
                )
            for suffix, training_suffix, calibrated_candidate_report, calibrated_backend in calibrated_entries:
                calibrated_predictions = dict(calibrated_candidate_report.get("predictions") or {})
                calibrated_evaluation_report = svc.dynamics_evaluation_report(
                    state_id,
                    {
                        **payload,
                        "candidate": calibrated_candidate_report.get("candidate") or {},
                        "predictions": calibrated_predictions,
                    },
                )
                calibrated_consumer_candidate = candidate_report_with_rollout_aliases(calibrated_candidate_report, dataset, horizon=2)
                calibrated_backend_report = svc.dynamics_backend_report(
                    state_id,
                    {
                        **payload,
                        "backend": calibrated_backend,
                        "candidate_report": calibrated_consumer_candidate,
                    },
                )
                calibrated_objective_report = svc.training_objective_report(
                    state_id,
                    {
                        **payload,
                        "dynamics_backend_report": calibrated_backend_report,
                        "predictions": calibrated_predictions,
                    },
                )
                entries.append(
                    summarize_backend_comparison_entry(
                        candidate_id=f"{spec['candidate_id']}_{suffix}",
                        role=f"{spec['role']}_{suffix}",
                        training_method=f"{spec['trainer']['training_method']}+{training_suffix}",
                        dataset=dataset,
                        candidate_report=calibrated_candidate_report,
                        backend_report=calibrated_backend_report,
                        evaluation_report=calibrated_evaluation_report,
                        objective_report=calibrated_objective_report,
                        train_report=train_report,
                    )
                )

    entries.sort(key=lambda item: item["rank_score"], reverse=True)
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    selected = entries[0] if entries else {}
    planner_rows = [
        {
            "candidate_id": entry.get("candidate_id"),
            "training_method": entry.get("training_method"),
            "exact_match_rate": ((entry.get("planner_holdout_analysis") or {}).get("metrics") or {}).get("exact_match_rate"),
            "mean_regret": ((entry.get("planner_holdout_analysis") or {}).get("metrics") or {}).get("mean_regret"),
            "max_regret": ((entry.get("planner_holdout_analysis") or {}).get("metrics") or {}).get("max_regret"),
            "blocked_target_selection_count": ((entry.get("planner_holdout_analysis") or {}).get("metrics") or {}).get("blocked_target_selection_count"),
            "selected_action_counts": (entry.get("planner_holdout_analysis") or {}).get("selected_action_counts") or {},
            "rollout_mean_cumulative_regret": (((entry.get("planner_holdout_analysis") or {}).get("rollout_matrix") or {}).get("metrics") or {}).get("mean_cumulative_regret"),
            "rollout_utility_gap": (((entry.get("planner_holdout_analysis") or {}).get("rollout_matrix") or {}).get("metrics") or {}).get("utility_gap"),
            "rollout_risk_gap": (((entry.get("planner_holdout_analysis") or {}).get("rollout_matrix") or {}).get("metrics") or {}).get("risk_gap"),
        }
        for entry in entries
    ]
    return {
        "schema": "territory_world_model.synthetic_backend_comparison.v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "candidate_count": len(entries),
        "included_methods": [entry["training_method"] for entry in entries],
        "ranking": entries,
        "action_mask_summary": backend_action_mask_summary(entries),
        "mixed_action_mask_generalization": backend_mixed_action_mask_generalization(entries, dataset),
        "planner_holdout_summary": {
            "schema": "territory_world_model.backend_planner_holdout_summary.v1",
            "rows": planner_rows,
            "interpretation": "checks how each simulator backend is consumed by a constrained planner on synthetic holdout region/period action sets and region-level rollout trajectories",
        },
        "selected_planner_holdout_analysis": selected.get("planner_holdout_analysis") or {},
        "selected_planner_rollout_matrix": ((selected.get("planner_holdout_analysis") or {}).get("rollout_matrix") or {}),
        "selected": {
            "candidate_id": selected.get("candidate_id", ""),
            "training_method": selected.get("training_method", ""),
            "rank_score": selected.get("rank_score"),
            "status": selected.get("status", ""),
            "interpretation": "best experiment candidate under synthetic holdout metrics; not a production promotion",
        },
        "comparison_policy": {
            "primary": "forecast-consumable action-conditioned multi-head dynamics",
            "ranking_inputs": [
                "backend status",
                "evaluation status",
                "objective status",
                "mean transition error",
                "mean constraint error",
                "mean utility error",
                "action-mask accuracy",
                "planner holdout exact-match/regret",
                "non-scaffold trainer signal",
            ],
            "disallowed_claims": [
                "production_ready_world_model",
                "real_world_accuracy",
                "planner_is_twm_core",
            ],
        },
    }


def run_transformer_risk_weight_probe(
    svc: TerritoryWorldModelService,
    state_id: str,
    dataset: dict[str, Any],
    payload: dict[str, Any],
    *,
    mlp_epochs: int,
    weights: list[float] | None,
    risk_head_mode: str = "context_residual",
) -> dict[str, Any]:
    clean_weights = sorted({round(max(0.0, min(2.0, float(weight))), 6) for weight in (weights or [])})
    rows: list[dict[str, Any]] = []
    for weight in clean_weights:
        specs = backend_experiment_specs(
            mlp_epochs=mlp_epochs,
            include_graph=False,
            include_transformer=True,
            transformer_risk_calibration_weight=weight,
            transformer_risk_head_mode=risk_head_mode,
        )
        transformer_spec = next((spec for spec in specs if spec.get("candidate_id") == "torch_spatiotemporal_transformer"), None)
        if not transformer_spec:
            continue
        train_report = svc.train_dynamics_candidate(
            state_id,
            {
                **payload,
                "trainer": transformer_spec["trainer"],
                "training_config": transformer_spec["training_config"],
            },
        )
        candidate_report = dict(train_report.get("candidate_report") or {})
        predictions = dict(train_report.get("predictions") or candidate_report.get("predictions") or {})
        raw_eval = svc.dynamics_evaluation_report(
            state_id,
            {
                **payload,
                "candidate": candidate_report.get("candidate") or {},
                "predictions": predictions,
            },
        )
        risk_report = constraint_risk_calibrated_candidate_report(candidate_report, dataset)
        context_report = context_calibrated_action_mask_candidate_report(risk_report, dataset)
        context_predictions = dict(context_report.get("predictions") or {})
        context_eval = svc.dynamics_evaluation_report(
            state_id,
            {
                **payload,
                "candidate": context_report.get("candidate") or {},
                "predictions": context_predictions,
            },
        )
        action_mask = action_mask_diagnostics_for_predictions(dataset, context_predictions)
        planner = planner_holdout_analysis_for_predictions(
            dataset,
            context_predictions,
            candidate_id=f"torch_spatiotemporal_transformer_risk_weight_{weight}",
            training_method="torch_spatiotemporal_transformer+risk_weight_probe",
        )
        calibration = dict(risk_report.get("constraint_risk_calibration") or {})
        learned = report_learned_parameters(candidate_report, train_report)
        diagnostics = dict(learned.get("training_diagnostics") or {})
        architecture = dict(learned.get("architecture") or {})
        rows.append(
            {
                "weight": weight,
                "risk_head_mode": (
                    diagnostics.get("risk_head_mode")
                    or architecture.get("constraint_risk_head")
                    or transformer_spec["training_config"].get("risk_head_mode")
                ),
                "risk_head_context_tokens": architecture.get("constraint_risk_context_tokens") or [],
                "training_status": diagnostics.get("status") or train_report.get("status"),
                "training_evidence_missing": ((train_report.get("evidence_gate") or {}).get("missing") or []),
                "final_loss": diagnostics.get("final_loss"),
                "raw_mean_constraint_error": (raw_eval.get("metrics") or {}).get("mean_constraint_error"),
                "calibrated_mean_constraint_error": (context_eval.get("metrics") or {}).get("mean_constraint_error"),
                "candidate_split_mae_before": calibration.get("mean_absolute_error_before"),
                "candidate_split_mae_after": calibration.get("mean_absolute_error_after"),
                "calibration_status": calibration.get("status"),
                "calibration_slope": calibration.get("slope"),
                "calibration_intercept": calibration.get("intercept"),
                "prediction_std": calibration.get("prediction_std"),
                "false_allow": ((action_mask.get("confusion") or {}).get("false_allow")),
                "false_block": ((action_mask.get("confusion") or {}).get("false_block")),
                "planner_mean_regret": ((planner.get("metrics") or {}).get("mean_regret")),
                "rollout_mean_cumulative_regret": (((planner.get("rollout_matrix") or {}).get("metrics") or {}).get("mean_cumulative_regret")),
            }
        )
    selected = min(
        rows,
        key=lambda row: (
            numeric_or_default(row.get("candidate_split_mae_before"), 999.0),
            numeric_or_default(row.get("calibrated_mean_constraint_error"), 999.0),
            int(row.get("false_allow") or 0),
            numeric_or_default(row.get("planner_mean_regret"), 999.0),
        ),
    ) if rows else {}
    blocked_rows = [row for row in rows if row.get("training_status") == "blocked"]
    return {
        "schema": "territory_world_model.transformer_risk_weight_probe.v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "status": "review" if blocked_rows else "pass" if rows else "review",
        "rows": rows,
        "selected": selected,
        "interpretation": [
            "This probe trains transformer candidates with alternative risk calibration weights outside the main backend ranking.",
            "Use candidate_split_mae_before to track whether risk calibration is being internalized before post-hoc affine correction.",
            "Rows remain synthetic experiment diagnostics and do not promote a production model.",
        ],
    }


def run_transformer_risk_head_probe(
    svc: TerritoryWorldModelService,
    state_id: str,
    dataset: dict[str, Any],
    payload: dict[str, Any],
    *,
    mlp_epochs: int,
) -> dict[str, Any]:
    weights = [0.0, 1.2]
    rows: list[dict[str, Any]] = []
    for mode in ("shared", "context_residual"):
        probe = run_transformer_risk_weight_probe(
            svc,
            state_id,
            dataset,
            payload,
            mlp_epochs=mlp_epochs,
            weights=weights,
            risk_head_mode=mode,
        )
        selected = dict(probe.get("selected") or {})
        rows.append(
            {
                "risk_head_mode": mode,
                "status": probe.get("status"),
                "selected_weight": selected.get("weight"),
                "selected_raw_mean_constraint_error": selected.get("raw_mean_constraint_error"),
                "selected_candidate_split_mae_before": selected.get("candidate_split_mae_before"),
                "selected_candidate_split_mae_after": selected.get("candidate_split_mae_after"),
                "selected_calibrated_mean_constraint_error": selected.get("calibrated_mean_constraint_error"),
                "selected_false_allow": selected.get("false_allow"),
                "selected_false_block": selected.get("false_block"),
                "selected_planner_mean_regret": selected.get("planner_mean_regret"),
                "selected_rollout_mean_cumulative_regret": selected.get("rollout_mean_cumulative_regret"),
                "weight_rows": probe.get("rows") or [],
            }
        )
    selected = min(
        rows,
        key=lambda row: (
            numeric_or_default(row.get("selected_candidate_split_mae_before"), 999.0),
            numeric_or_default(row.get("selected_raw_mean_constraint_error"), 999.0),
            int(row.get("selected_false_allow") or 0),
            numeric_or_default(row.get("selected_planner_mean_regret"), 999.0),
        ),
    ) if rows else {}
    return {
        "schema": "territory_world_model.transformer_risk_head_probe.v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "status": "pass" if rows and not any(row.get("status") == "review" for row in rows) else "review",
        "rows": rows,
        "selected": selected,
        "interpretation": [
            "This probe compares the shared transformer risk head against a context-residual head under the same synthetic foundation.",
            "The context-residual head is intended to internalize action/context/temporal risk structure before post-hoc affine calibration.",
            "Rows remain synthetic diagnostics and do not promote production readiness.",
        ],
    }


def backend_action_mask_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for entry in entries:
        diagnostics = dict(entry.get("action_mask_diagnostics") or {})
        confusion = dict(diagnostics.get("confusion") or {})
        rows.append(
            {
                "candidate_id": entry.get("candidate_id"),
                "training_method": entry.get("training_method"),
                "accuracy": diagnostics.get("accuracy"),
                "false_allow": confusion.get("false_allow", 0),
                "false_block": confusion.get("false_block", 0),
                "missing_prediction": confusion.get("missing_prediction", 0),
                "worst_action_type": worst_action_type(diagnostics),
            }
        )
    rows.sort(key=lambda item: (numeric_or_default(item.get("accuracy"), -1.0), -int(item.get("false_allow") or 0)), reverse=True)
    return {
        "schema": "territory_world_model.backend_action_mask_summary.v1",
        "rows": rows,
        "best_action_mask_candidate": rows[0] if rows else {},
        "highest_false_allow_candidate": max(rows, key=lambda item: int(item.get("false_allow") or 0)) if rows else {},
        "note": "false_allow is weighted as the riskiest action-mask failure because it can pass a blocked territorial action into planner consumers",
    }


def backend_mixed_action_mask_generalization(entries: list[dict[str, Any]], dataset: dict[str, Any]) -> dict[str, Any]:
    summary = dict(dataset.get("summary") or {})
    mixed_action_types = sorted(str(item) for item in summary.get("mixed_action_mask_action_types") or [])
    rows = []
    for entry in entries:
        diagnostics = dict(entry.get("action_mask_diagnostics") or {})
        confusion = dict(diagnostics.get("confusion") or {})
        calibration = candidate_action_mask_calibration_strategy(entry)
        rows.append(
            {
                "candidate_id": entry.get("candidate_id"),
                "training_method": entry.get("training_method"),
                "calibration": calibration,
                "accuracy": diagnostics.get("accuracy"),
                "false_allow": int(confusion.get("false_allow") or 0),
                "false_block": int(confusion.get("false_block") or 0),
                "missing_prediction": int(confusion.get("missing_prediction") or 0),
                "mismatch_count": len(diagnostics.get("mismatches") or []),
                "worst_action_type": worst_action_type(diagnostics),
            }
        )

    strategy_summary = []
    for calibration in ("none", "action_type", "context"):
        items = [row for row in rows if row["calibration"] == calibration]
        if not items:
            continue
        false_allows = [int(item.get("false_allow") or 0) for item in items]
        false_blocks = [int(item.get("false_block") or 0) for item in items]
        accuracies = [numeric_or_default(item.get("accuracy"), 0.0) for item in items]
        strategy_summary.append(
            {
                "calibration": calibration,
                "candidate_count": len(items),
                "min_false_allow": min(false_allows),
                "max_false_allow": max(false_allows),
                "min_false_block": min(false_blocks),
                "max_false_block": max(false_blocks),
                "mean_accuracy": round(sum(accuracies) / max(1, len(accuracies)), 6),
            }
        )

    action_type_failures = [
        row
        for row in rows
        if row["calibration"] == "action_type" and int(row.get("false_allow") or 0) > 0
    ]
    context_rows = [row for row in rows if row["calibration"] == "context"]
    context_zero_false_allow = [row for row in context_rows if int(row.get("false_allow") or 0) == 0]
    selected_calibration = "context" if context_zero_false_allow and action_type_failures else "review"
    return {
        "schema": "territory_world_model.mixed_action_mask_generalization.v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "mixed_action_types": mixed_action_types,
        "action_mask_counts_by_action_type": summary.get("action_mask_counts_by_action_type") or {},
        "rows": rows,
        "strategy_summary": strategy_summary,
        "action_type_only_failure_count": len(action_type_failures),
        "context_zero_false_allow_count": len(context_zero_false_allow),
        "context_overblock_candidate_count": sum(1 for row in context_rows if int(row.get("false_block") or 0) > 0),
        "selected_calibration": selected_calibration,
        "interpretation": [
            "Mixed action-mask labels deliberately include both allowed and blocked examples for the same non-defer action types.",
            "A candidate that only calibrates by action type can still allow blocked context-specific actions; false_allow is the critical safety failure.",
            "Context calibration uses action type, risk bucket and mask policy to remove false_allow on the current synthetic foundation, while false_block tracks conservative overblocking.",
        ],
    }


def candidate_action_mask_calibration_strategy(entry: dict[str, Any]) -> str:
    training_method = str(entry.get("training_method") or "")
    candidate_id = str(entry.get("candidate_id") or "")
    if "context_action_mask_calibration" in training_method or "context_action_mask_calibrated" in candidate_id:
        return "context"
    if "action_mask_calibration" in training_method or "action_mask_calibrated" in candidate_id:
        return "action_type"
    return "none"


def planner_holdout_analysis_for_predictions(
    dataset: dict[str, Any],
    predictions: dict[str, dict[str, Any]],
    *,
    candidate_id: str,
    training_method: str,
) -> dict[str, Any]:
    holdout_example_count, missing_prediction_count, group_results = planner_holdout_group_results(dataset, predictions)
    group_count = len(group_results)
    oracle_match_count = sum(1 for item in group_results if item["oracle_match"])
    regrets = [float(item["regret"]) for item in group_results]
    selected_rows = [dict(item["selected"]) for item in group_results]
    oracle_rows = [dict(item["oracle"]) for item in group_results]
    blocked_target_selection_count = sum(1 for item in group_results if item["selected_target_blocked"])
    false_allow_selection_count = sum(1 for item in group_results if item["selected_false_allow"])
    selected_missing_count = sum(1 for item in group_results if item["selected_prediction_missing"])
    selected_action_counts = Counter(str(item.get("action_type") or "") for item in selected_rows)
    oracle_action_counts = Counter(str(item.get("action_type") or "") for item in oracle_rows)
    mean_regret = round(sum(regrets) / max(1, len(regrets)), 6)
    max_regret = round(max(regrets), 6) if regrets else None
    status = "blocked"
    if group_count:
        status = "pass" if mean_regret <= 0.05 and not false_allow_selection_count and not selected_missing_count else "review"
    return {
        "schema": "territory_world_model.planner_holdout_analysis.v1",
        "candidate_id": candidate_id,
        "training_method": training_method,
        "status": status,
        "claim_boundary": CLAIM_BOUNDARY,
        "holdout_example_count": holdout_example_count,
        "group_count": group_count,
        "missing_prediction_count": missing_prediction_count,
        "selected_action_counts": dict(sorted(selected_action_counts.items())),
        "oracle_action_counts": dict(sorted(oracle_action_counts.items())),
        "metrics": {
            "oracle_match_count": oracle_match_count,
            "exact_match_rate": round(oracle_match_count / max(1, group_count), 6),
            "mean_regret": mean_regret,
            "max_regret": max_regret,
            "blocked_target_selection_count": blocked_target_selection_count,
            "false_allow_selection_count": false_allow_selection_count,
            "selected_missing_prediction_count": selected_missing_count,
            "mean_selected_target_utility_delta": mean_of(selected_rows, "target_utility_delta"),
            "mean_oracle_target_utility_delta": mean_of(oracle_rows, "target_utility_delta"),
            "mean_selected_target_constraint_probability": mean_of(selected_rows, "target_constraint_probability"),
            "mean_oracle_target_constraint_probability": mean_of(oracle_rows, "target_constraint_probability"),
        },
        "by_region": planner_group_aggregates(group_results, "region_code"),
        "by_period": planner_group_aggregates(group_results, "period"),
        "by_action_type": planner_action_type_aggregates(group_results),
        "rollout_matrix": planner_rollout_matrix_for_group_results(group_results),
        "groups": group_results[:16],
        "interpretation": planner_holdout_interpretation(group_count, mean_regret, false_allow_selection_count, selected_action_counts, oracle_action_counts),
    }


def planner_holdout_group_results(
    dataset: dict[str, Any],
    predictions: dict[str, dict[str, Any]],
) -> tuple[int, int, list[dict[str, Any]]]:
    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    holdout_examples = [item for item in examples if str(item.get("split") or "") == "holdout"]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for example in holdout_examples:
        context = dict(example.get("scenario_context") or {})
        region_code = str(context.get("region_code") or "unknown_region")
        period = str(context.get("period") or "unknown_period")
        grouped.setdefault((region_code, period), []).append(example)

    group_results: list[dict[str, Any]] = []
    missing_prediction_count = 0
    for (region_code, period), group_examples in sorted(grouped.items()):
        candidates = [
            planner_candidate_holdout_row(example, dict(predictions.get(str(example.get("id") or "")) or {}))
            for example in group_examples
        ]
        if not candidates:
            continue
        time_index = min(safe_int((example.get("scenario_context") or {}).get("time_index"), 0) for example in group_examples)
        missing_prediction_count += sum(1 for item in candidates if item["prediction_missing"])
        selected = max(candidates, key=lambda item: (item["predicted_rank_score"], item["predicted_confidence"], item["target_rank_score"]))
        oracle = max(candidates, key=lambda item: (item["target_rank_score"], item["target_confidence"]))
        regret = max(0.0, float(oracle["target_rank_score"]) - float(selected["target_rank_score"]))
        group_results.append(
            {
                "region_code": region_code,
                "period": period,
                "time_index": time_index,
                "candidate_action_count": len(candidates),
                "selected": compact_planner_candidate_row(selected),
                "oracle": compact_planner_candidate_row(oracle),
                "oracle_match": selected["example_id"] == oracle["example_id"],
                "regret": round(regret, 6),
                "selected_target_blocked": bool(selected["target_blocked"]),
                "selected_false_allow": bool(selected["predicted_allowed"] and selected["target_blocked"]),
                "selected_prediction_missing": bool(selected["prediction_missing"]),
            }
        )
    return len(holdout_examples), missing_prediction_count, group_results


def planner_candidate_holdout_row(example: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    action = dict(example.get("action") or {})
    targets = dict(example.get("targets") or {})
    labels = dict(example.get("labels") or {})
    target_mask = dict(targets.get("action_mask") or {})
    target_allowed = bool(target_mask.get("allowed", True))
    target_blocked = bool(target_mask.get("hard_blocks")) or not target_allowed
    target_confidence = target_confidence_for_example(example)
    target_utility = numeric_or_default(targets.get("planning_utility_delta"), 0.0)
    target_risk = numeric_or_default(targets.get("constraint_violation_probability"), 0.0)
    target_rank_score = safe_float(labels.get("ranking_score"), None)
    if target_rank_score is None:
        target_rank_score = target_utility - target_risk + target_confidence * 0.1
    if target_blocked:
        target_rank_score = float(target_rank_score) - 1.0

    prediction_missing = not bool(prediction)
    predicted_mask = dict(prediction.get("action_mask") or {}) if prediction else {}
    predicted_allowed = bool(predicted_mask.get("allowed", True)) if prediction else False
    predicted_blocked = bool(predicted_mask.get("hard_blocks")) or not predicted_allowed
    predicted_confidence = prediction_confidence(prediction)
    predicted_utility = numeric_or_default(prediction.get("planning_utility_delta") if prediction else None, 0.0)
    predicted_risk = numeric_or_default(prediction.get("constraint_violation_probability") if prediction else None, 1.0)
    predicted_rank_score = predicted_utility - predicted_risk + predicted_confidence * 0.1
    if predicted_blocked:
        predicted_rank_score -= 1.0
    if prediction_missing:
        predicted_rank_score = -999.0

    return {
        "example_id": example.get("id"),
        "action_type": action.get("action_type") or "unknown",
        "target_allowed": target_allowed,
        "target_blocked": target_blocked,
        "target_utility_delta": round(target_utility, 6),
        "target_constraint_probability": round(target_risk, 6),
        "target_confidence": round(target_confidence, 6),
        "target_rank_score": round(float(target_rank_score), 6),
        "predicted_allowed": predicted_allowed,
        "predicted_blocked": predicted_blocked,
        "prediction_missing": prediction_missing,
        "predicted_utility_delta": round(predicted_utility, 6),
        "predicted_constraint_probability": round(predicted_risk, 6),
        "predicted_confidence": round(predicted_confidence, 6),
        "predicted_rank_score": round(predicted_rank_score, 6),
    }


def compact_planner_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "example_id": row.get("example_id"),
        "action_type": row.get("action_type"),
        "target_allowed": row.get("target_allowed"),
        "target_blocked": row.get("target_blocked"),
        "target_utility_delta": row.get("target_utility_delta"),
        "target_constraint_probability": row.get("target_constraint_probability"),
        "target_rank_score": row.get("target_rank_score"),
        "predicted_allowed": row.get("predicted_allowed"),
        "predicted_utility_delta": row.get("predicted_utility_delta"),
        "predicted_constraint_probability": row.get("predicted_constraint_probability"),
        "predicted_rank_score": row.get("predicted_rank_score"),
        "prediction_missing": row.get("prediction_missing"),
    }


def target_confidence_for_example(example: dict[str, Any]) -> float:
    targets = dict(example.get("targets") or {})
    uncertainty = dict(targets.get("uncertainty") or {})
    mask = dict(targets.get("action_mask") or {})
    return numeric_or_default(uncertainty.get("confidence", mask.get("confidence")), 0.0)


def prediction_confidence(prediction: dict[str, Any]) -> float:
    uncertainty = dict(prediction.get("uncertainty") or {})
    mask = dict(prediction.get("action_mask") or {})
    return numeric_or_default(uncertainty.get("confidence", mask.get("confidence")), 0.0)


def mean_of(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [numeric_or_default(item.get(key), 0.0) for item in rows if item.get(key) is not None]
    return round(sum(values) / len(values), 6) if values else None


def planner_group_aggregates(group_results: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in group_results:
        grouped.setdefault(str(item.get(field) or ""), []).append(item)
    rows = []
    for value, items in sorted(grouped.items()):
        regrets = [float(item.get("regret") or 0.0) for item in items]
        selected_rows = [dict(item["selected"]) for item in items]
        rows.append(
            {
                field: value,
                "group_count": len(items),
                "exact_match_rate": round(sum(1 for item in items if item.get("oracle_match")) / max(1, len(items)), 6),
                "mean_regret": round(sum(regrets) / max(1, len(regrets)), 6),
                "max_regret": round(max(regrets), 6) if regrets else None,
                "false_allow_selection_count": sum(1 for item in items if item.get("selected_false_allow")),
                "selected_action_counts": dict(sorted(Counter(str(row.get("action_type") or "") for row in selected_rows).items())),
            }
        )
    return rows


def planner_action_type_aggregates(group_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    action_types = sorted(
        set(str((item.get("selected") or {}).get("action_type") or "") for item in group_results)
        | set(str((item.get("oracle") or {}).get("action_type") or "") for item in group_results)
    )
    rows = []
    for action_type in action_types:
        selected_items = [item for item in group_results if str((item.get("selected") or {}).get("action_type") or "") == action_type]
        oracle_items = [item for item in group_results if str((item.get("oracle") or {}).get("action_type") or "") == action_type]
        regrets = [float(item.get("regret") or 0.0) for item in selected_items]
        selected_rows = [dict(item["selected"]) for item in selected_items]
        rows.append(
            {
                "action_type": action_type,
                "selected_count": len(selected_items),
                "oracle_count": len(oracle_items),
                "mean_regret_when_selected": round(sum(regrets) / max(1, len(regrets)), 6) if selected_items else None,
                "false_allow_selection_count": sum(1 for item in selected_items if item.get("selected_false_allow")),
                "mean_selected_target_utility_delta": mean_of(selected_rows, "target_utility_delta"),
                "mean_selected_target_constraint_probability": mean_of(selected_rows, "target_constraint_probability"),
            }
        )
    return rows


def planner_rollout_matrix_for_group_results(group_results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in group_results:
        grouped.setdefault(str(item.get("region_code") or ""), []).append(item)
    trajectories = []
    for region_code, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: (safe_int(item.get("time_index"), 0), str(item.get("period") or "")))
        steps = []
        selected_cumulative_utility = 0.0
        oracle_cumulative_utility = 0.0
        selected_cumulative_risk = 0.0
        oracle_cumulative_risk = 0.0
        cumulative_regret = 0.0
        false_allow_count = 0
        blocked_target_count = 0
        for step_index, item in enumerate(ordered):
            selected = dict(item.get("selected") or {})
            oracle = dict(item.get("oracle") or {})
            selected_utility = numeric_or_default(selected.get("target_utility_delta"), 0.0)
            oracle_utility = numeric_or_default(oracle.get("target_utility_delta"), 0.0)
            selected_risk = numeric_or_default(selected.get("target_constraint_probability"), 0.0)
            oracle_risk = numeric_or_default(oracle.get("target_constraint_probability"), 0.0)
            regret = numeric_or_default(item.get("regret"), 0.0)
            selected_cumulative_utility += selected_utility
            oracle_cumulative_utility += oracle_utility
            selected_cumulative_risk += selected_risk
            oracle_cumulative_risk += oracle_risk
            cumulative_regret += regret
            false_allow_count += 1 if item.get("selected_false_allow") else 0
            blocked_target_count += 1 if item.get("selected_target_blocked") else 0
            steps.append(
                {
                    "step_index": step_index,
                    "period": item.get("period"),
                    "time_index": item.get("time_index"),
                    "selected_action_type": selected.get("action_type"),
                    "oracle_action_type": oracle.get("action_type"),
                    "oracle_match": bool(item.get("oracle_match")),
                    "selected_utility_delta": round(selected_utility, 6),
                    "oracle_utility_delta": round(oracle_utility, 6),
                    "selected_constraint_probability": round(selected_risk, 6),
                    "oracle_constraint_probability": round(oracle_risk, 6),
                    "step_regret": round(regret, 6),
                    "cumulative_regret": round(cumulative_regret, 6),
                }
            )
        step_count = len(steps)
        trajectories.append(
            {
                "region_code": region_code,
                "step_count": step_count,
                "selected_action_sequence": [step.get("selected_action_type") for step in steps],
                "oracle_action_sequence": [step.get("oracle_action_type") for step in steps],
                "exact_match_rate": round(sum(1 for step in steps if step.get("oracle_match")) / max(1, step_count), 6),
                "selected_cumulative_utility_delta": round(selected_cumulative_utility, 6),
                "oracle_cumulative_utility_delta": round(oracle_cumulative_utility, 6),
                "utility_gap": round(oracle_cumulative_utility - selected_cumulative_utility, 6),
                "selected_cumulative_constraint_probability": round(selected_cumulative_risk, 6),
                "oracle_cumulative_constraint_probability": round(oracle_cumulative_risk, 6),
                "risk_gap": round(selected_cumulative_risk - oracle_cumulative_risk, 6),
                "cumulative_regret": round(cumulative_regret, 6),
                "false_allow_selection_count": false_allow_count,
                "blocked_target_selection_count": blocked_target_count,
                "steps": steps,
            }
        )
    trajectory_count = len(trajectories)
    total_steps = sum(int(item.get("step_count") or 0) for item in trajectories)
    total_regret = sum(numeric_or_default(item.get("cumulative_regret"), 0.0) for item in trajectories)
    total_selected_utility = sum(numeric_or_default(item.get("selected_cumulative_utility_delta"), 0.0) for item in trajectories)
    total_oracle_utility = sum(numeric_or_default(item.get("oracle_cumulative_utility_delta"), 0.0) for item in trajectories)
    total_selected_risk = sum(numeric_or_default(item.get("selected_cumulative_constraint_probability"), 0.0) for item in trajectories)
    total_oracle_risk = sum(numeric_or_default(item.get("oracle_cumulative_constraint_probability"), 0.0) for item in trajectories)
    total_false_allow = sum(int(item.get("false_allow_selection_count") or 0) for item in trajectories)
    total_blocked_target = sum(int(item.get("blocked_target_selection_count") or 0) for item in trajectories)
    return {
        "schema": "territory_world_model.planner_rollout_matrix.v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "trajectory_unit": "region_code",
        "step_unit": "holdout_period",
        "trajectory_count": trajectory_count,
        "step_count": total_steps,
        "metrics": {
            "mean_cumulative_regret": round(total_regret / max(1, trajectory_count), 6),
            "total_regret": round(total_regret, 6),
            "selected_total_utility_delta": round(total_selected_utility, 6),
            "oracle_total_utility_delta": round(total_oracle_utility, 6),
            "utility_gap": round(total_oracle_utility - total_selected_utility, 6),
            "selected_total_constraint_probability": round(total_selected_risk, 6),
            "oracle_total_constraint_probability": round(total_oracle_risk, 6),
            "risk_gap": round(total_selected_risk - total_oracle_risk, 6),
            "false_allow_selection_count": total_false_allow,
            "blocked_target_selection_count": total_blocked_target,
        },
        "trajectories": trajectories,
        "interpretation": [
            "rollout matrix chains holdout planner choices by region to approximate multi-step planner consumption of simulator heads",
            "this is still a synthetic regression signal, not production rollout evidence",
        ],
    }


def planner_holdout_interpretation(
    group_count: int,
    mean_regret: float,
    false_allow_selection_count: int,
    selected_action_counts: Counter,
    oracle_action_counts: Counter,
) -> list[str]:
    notes = [
        "planner holdout analysis treats the planner as a downstream consumer of simulator heads, not as the TWM core",
        "groups are synthetic holdout region/period action sets ranked with the same utility-risk-confidence policy used by beam_plan",
    ]
    if not group_count:
        notes.append("no holdout groups were available for planner-consumer validation")
    elif false_allow_selection_count:
        notes.append("at least one selected action is blocked by the target action mask; this requires review before planner consumption")
    elif mean_regret == 0:
        notes.append("selected actions match the synthetic oracle action in all evaluated holdout groups")
    else:
        notes.append(f"mean synthetic regret is {mean_regret}; use this as a regression signal, not as production evidence")
    if len(selected_action_counts) <= 1 and len(oracle_action_counts) <= 1 and group_count:
        notes.append("current synthetic holdout oracle is action-diversity limited; harder scenarios should diversify the optimal action type")
    return notes


def run_action_mask_calibration_stress(dataset: dict[str, Any], *, baseline_prediction_report: dict[str, Any]) -> dict[str, Any]:
    stress_dataset = mixed_action_mask_stress_dataset(dataset)
    raw_predictions = predictions_for_stress_dataset(
        source_dataset=dataset,
        stress_dataset=stress_dataset,
        source_predictions=dict(baseline_prediction_report.get("predictions") or {}),
    )
    raw_report = {
        "schema": "territory_world_model.synthetic_stress_candidate_report.v1",
        "status": "pass",
        "candidate": {"model_name": "stress_raw_predictions", "model_family": "stress_action_mask"},
        "predictions": raw_predictions,
        "evidence_gate": {"status": "pass"},
    }
    action_type_calibrated = calibrated_action_mask_candidate_report(raw_report, stress_dataset)
    context_calibrated = context_calibrated_action_mask_candidate_report(raw_report, stress_dataset)
    variants = [
        {
            "variant_id": "raw_predictions",
            "calibration": "none",
            "diagnostics": action_mask_diagnostics_for_predictions(stress_dataset, raw_predictions),
        },
        {
            "variant_id": "action_type_calibration",
            "calibration": "action_type",
            "diagnostics": action_mask_diagnostics_for_predictions(stress_dataset, action_type_calibrated.get("predictions") or {}),
            "calibration_report": action_type_calibrated.get("action_mask_calibration") or {},
        },
        {
            "variant_id": "context_calibration",
            "calibration": "action_type+risk_bucket+mask_policy",
            "diagnostics": action_mask_diagnostics_for_predictions(stress_dataset, context_calibrated.get("predictions") or {}),
            "calibration_report": context_calibrated.get("action_mask_calibration") or {},
        },
    ]
    for variant in variants:
        diagnostics = dict(variant["diagnostics"])
        confusion = dict(diagnostics.get("confusion") or {})
        variant["score"] = round(
            numeric_or_default(diagnostics.get("accuracy"), 0.0)
            - 1.2 * int(confusion.get("false_allow") or 0) / max(1, int(diagnostics.get("example_count") or 0))
            - 0.4 * int(confusion.get("false_block") or 0) / max(1, int(diagnostics.get("example_count") or 0)),
            6,
        )
    variants.sort(key=lambda item: item["score"], reverse=True)
    for rank, variant in enumerate(variants, start=1):
        variant["rank"] = rank
    return {
        "schema": "territory_world_model.action_mask_calibration_stress.v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "stress_dataset": stress_dataset.get("summary") or {},
        "variants": variants,
        "selected": {
            "variant_id": variants[0]["variant_id"] if variants else "",
            "calibration": variants[0]["calibration"] if variants else "",
            "score": variants[0]["score"] if variants else None,
        },
        "interpretation": [
            "This stress test makes action types mixed allowed/blocked so action-type-only calibration cannot solve the task by memorizing a single action label.",
            "Context calibration uses risk buckets plus rule/mask policy context to test whether the action-mask head can preserve safety without overblocking all instances of a mixed action type.",
        ],
    }


def mixed_action_mask_stress_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    examples = [json.loads(json.dumps(item)) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    stress_examples: list[dict[str, Any]] = []
    for idx, example in enumerate(examples):
        action = dict(example.get("action") or {})
        action_type = str(action.get("action_type") or "unknown")
        context = dict(example.get("scenario_context") or {})
        targets = dict(example.get("targets") or {})
        constraint = numeric_or_default(targets.get("constraint_violation_probability"), 0.0)
        time_index = safe_int(context.get("time_index"), 0)
        region_code = str(context.get("region_code") or "")
        mixed_block = stress_action_should_block(
            action_type=action_type,
            constraint=constraint,
            time_index=time_index,
            region_code=region_code,
        )
        mask = dict(targets.get("action_mask") or {})
        if mixed_block:
            mask["allowed"] = False
            mask["required_reviews"] = sorted(set(mask.get("required_reviews") or []) | {"stress_context_review"})
            if constraint >= 0.28:
                mask["hard_blocks"] = sorted(set(mask.get("hard_blocks") or []) | {"stress_high_constraint"})
            mask["confidence"] = min(0.92, numeric_or_default(mask.get("confidence"), 0.75) + 0.03)
        else:
            mask["allowed"] = True
            mask["required_reviews"] = []
            mask["hard_blocks"] = []
            mask["confidence"] = max(0.72, numeric_or_default(mask.get("confidence"), 0.8))
        base_example_id = str(example.get("id") or idx)
        targets["action_mask"] = mask
        example["targets"] = targets
        example["id"] = f"stress:{base_example_id}"
        provenance = dict(example.get("provenance") or {})
        provenance["stress_test"] = "mixed_action_mask_context"
        provenance["base_example_id"] = base_example_id
        example["provenance"] = provenance
        context["stress_context_blocked"] = mixed_block
        context["stress_risk_bucket"] = risk_bucket(constraint)
        example["scenario_context"] = context
        stress_examples.append(example)
    split_counts = Counter(str(item.get("split") or "") for item in stress_examples)
    action_counts = Counter(str((item.get("action") or {}).get("action_type") or "") for item in stress_examples)
    blocked_counts: dict[str, int] = {}
    for item in stress_examples:
        action_type = str((item.get("action") or {}).get("action_type") or "unknown")
        if not bool(((item.get("targets") or {}).get("action_mask") or {}).get("allowed", True)):
            blocked_counts[action_type] = blocked_counts.get(action_type, 0) + 1
    return {
        "schema": "territory_world_model.dynamics_training_dataset.v1",
        "state_version_id": dataset.get("state_version_id", ""),
        "project_id": dataset.get("project_id", ""),
        "examples": stress_examples,
        "summary": {
            "schema": "territory_world_model.mixed_action_mask_stress_dataset.v1",
            "example_count": len(stress_examples),
            "split_counts": dict(sorted(split_counts.items())),
            "action_counts": dict(sorted(action_counts.items())),
            "blocked_counts_by_action_type": dict(sorted(blocked_counts.items())),
            "mixed_action_types": sorted(
                action
                for action, total in action_counts.items()
                if 0 < blocked_counts.get(action, 0) < total
            ),
            "claim_boundary": CLAIM_BOUNDARY,
        },
    }


def stress_action_should_block(*, action_type: str, constraint: float, time_index: int, region_code: str) -> bool:
    _region_digit = safe_int(region_code.rsplit("R", 1)[-1], 0) if "R" in region_code else 0
    _time_index = time_index
    bucket = risk_bucket(constraint)
    if action_type == "defer_review":
        return bucket in {"medium", "high"}
    if action_type == "approve_with_conditions":
        return bucket == "high"
    if action_type == "restore":
        return bucket == "high"
    if action_type == "protect":
        return bucket == "high"
    return bucket == "high"


def predictions_for_stress_dataset(
    *,
    source_dataset: dict[str, Any],
    stress_dataset: dict[str, Any],
    source_predictions: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    source_by_base_id = {
        str(item.get("id") or ""): dict(source_predictions.get(str(item.get("id") or "")) or {})
        for item in source_dataset.get("examples") or []
        if isinstance(item, dict)
    }
    predictions: dict[str, dict[str, Any]] = {}
    for stress_example in stress_dataset.get("examples") or []:
        if not isinstance(stress_example, dict):
            continue
        stress_id = str(stress_example.get("id") or "")
        base_id = stress_id.removeprefix("stress:")
        prediction = json.loads(json.dumps(source_by_base_id.get(base_id) or (stress_example.get("targets") or {})))
        predictions[stress_id] = prediction
    return predictions


def risk_bucket(value: float) -> str:
    if value >= 0.3:
        return "high"
    if value >= 0.24:
        return "medium"
    return "low"


def calibrated_action_mask_candidate_report(candidate_report: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    report = json.loads(json.dumps(candidate_report))
    predictions = dict(report.get("predictions") or {})
    calibration = action_mask_calibration_from_dataset(dataset)
    calibrated_predictions: dict[str, dict[str, Any]] = {}
    applied_count = 0
    for example in dataset.get("examples") or []:
        if not isinstance(example, dict):
            continue
        example_id = str(example.get("id") or "")
        prediction = dict(predictions.get(example_id) or {})
        if not prediction:
            continue
        action_type = str((example.get("action") or {}).get("action_type") or "unknown")
        action_rule = dict((calibration.get("by_action_type") or {}).get(action_type) or {})
        updated_prediction, applied = apply_action_mask_calibration(prediction, action_rule)
        if applied:
            applied_count += 1
        calibrated_predictions[example_id] = updated_prediction
    report["predictions"] = calibrated_predictions
    candidate = dict(report.get("candidate") or {})
    candidate["model_name"] = f"{candidate.get('model_name') or 'candidate'}_action_mask_calibrated"
    candidate["model_family"] = f"{candidate.get('model_family') or 'action_conditioned_dynamics'}_with_action_mask_calibration"
    candidate["action_mask_calibrated"] = True
    candidate["calibration_source"] = "candidate_split_action_mask_targets"
    report["candidate"] = candidate
    report["schema"] = "territory_world_model.action_mask_calibrated_candidate_report.v1"
    report["status"] = "pass" if calibrated_predictions else report.get("status", "review")
    evidence_gate = dict(report.get("evidence_gate") or {})
    evidence_gate["status"] = "pass" if calibrated_predictions else evidence_gate.get("status", "review")
    evidence_gate["action_mask_calibrated"] = True
    report["evidence_gate"] = evidence_gate
    report["action_mask_calibration"] = calibration | {
        "applied_prediction_count": applied_count,
        "prediction_count": len(calibrated_predictions),
        "policy": "block action types whose candidate-split targets are consistently blocked or review-required",
    }
    evaluation = dict(report.get("evaluation") or {})
    evaluation["action_mask_calibrated"] = True
    report["evaluation"] = evaluation
    return report


def constraint_risk_calibrated_candidate_report(candidate_report: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    report = json.loads(json.dumps(candidate_report))
    predictions = dict(report.get("predictions") or {})
    calibration = constraint_risk_calibration_from_dataset(dataset, predictions)
    calibrated_predictions: dict[str, dict[str, Any]] = {}
    for example in dataset.get("examples") or []:
        if not isinstance(example, dict):
            continue
        example_id = str(example.get("id") or "")
        prediction = dict(predictions.get(example_id) or {})
        if not prediction:
            continue
        calibrated_predictions[example_id] = apply_constraint_risk_calibration(prediction, calibration)
    report["predictions"] = calibrated_predictions
    candidate = dict(report.get("candidate") or {})
    candidate["model_name"] = f"{candidate.get('model_name') or 'candidate'}_constraint_risk_calibrated"
    candidate["model_family"] = f"{candidate.get('model_family') or 'action_conditioned_dynamics'}_with_constraint_risk_calibration"
    candidate["constraint_risk_calibrated"] = True
    candidate["calibration_source"] = "candidate_split_constraint_risk_affine_calibration"
    report["candidate"] = candidate
    report["schema"] = "territory_world_model.constraint_risk_calibrated_candidate_report.v1"
    report["status"] = "pass" if calibrated_predictions else report.get("status", "review")
    evidence_gate = dict(report.get("evidence_gate") or {})
    evidence_gate["status"] = "pass" if calibrated_predictions else evidence_gate.get("status", "review")
    evidence_gate["constraint_risk_calibrated"] = True
    report["evidence_gate"] = evidence_gate
    report["constraint_risk_calibration"] = calibration | {
        "applied_prediction_count": len(calibrated_predictions),
        "prediction_count": len(calibrated_predictions),
    }
    evaluation = dict(report.get("evaluation") or {})
    evaluation["constraint_risk_calibrated"] = True
    report["evaluation"] = evaluation
    return report


def constraint_risk_calibration_from_dataset(dataset: dict[str, Any], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for example in dataset.get("examples") or []:
        if not isinstance(example, dict):
            continue
        if str(example.get("split") or "") == "holdout":
            continue
        example_id = str(example.get("id") or "")
        prediction = dict(predictions.get(example_id) or {})
        predicted = safe_float(prediction.get("constraint_violation_probability"), None)
        target = safe_float(((example.get("targets") or {}).get("constraint_violation_probability")), None)
        if predicted is None or target is None:
            continue
        pairs.append((float(predicted), float(target)))
    if len(pairs) < 2:
        return {
            "schema": "territory_world_model.constraint_risk_calibration.v1",
            "source_split": "candidate",
            "status": "review",
            "sample_count": len(pairs),
            "slope": 1.0,
            "intercept": 0.0,
            "reason": "insufficient_candidate_pairs",
            "claim_boundary": CLAIM_BOUNDARY,
        }
    pred_mean = sum(pred for pred, _target in pairs) / len(pairs)
    target_mean = sum(target for _pred, target in pairs) / len(pairs)
    variance = sum((pred - pred_mean) ** 2 for pred, _target in pairs)
    covariance = sum((pred - pred_mean) * (target - target_mean) for pred, target in pairs)
    prediction_std = (variance / len(pairs)) ** 0.5
    slope = covariance / variance if variance > 1e-9 else 1.0
    slope = max(0.0, min(2.0, slope))
    intercept = target_mean - slope * pred_mean
    before_errors = [abs(target - pred) for pred, target in pairs]
    after_errors = [abs(target - clamp(slope * pred + intercept)) for pred, target in pairs]
    status = "pass"
    review_reasons: list[str] = []
    if prediction_std < 0.02:
        status = "review"
        review_reasons.append("low_prediction_variance")
    if slope < 0.1:
        status = "review"
        review_reasons.append("degenerate_calibration_slope")
    if sum(after_errors) > sum(before_errors):
        status = "review"
        review_reasons.append("candidate_split_calibration_does_not_reduce_error")
    return {
        "schema": "territory_world_model.constraint_risk_calibration.v1",
        "source_split": "candidate",
        "status": status,
        "sample_count": len(pairs),
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
        "prediction_std": round(prediction_std, 6),
        "mean_absolute_error_before": round(sum(before_errors) / len(before_errors), 6),
        "mean_absolute_error_after": round(sum(after_errors) / len(after_errors), 6),
        "review_reasons": review_reasons,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def apply_constraint_risk_calibration(prediction: dict[str, Any], calibration: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(prediction))
    predicted = safe_float(updated.get("constraint_violation_probability"), None)
    if predicted is None or calibration.get("status") != "pass":
        return updated
    slope = float(safe_float(calibration.get("slope"), 1.0) or 1.0)
    intercept = float(safe_float(calibration.get("intercept"), 0.0) or 0.0)
    calibrated = clamp(slope * float(predicted) + intercept)
    updated["constraint_violation_probability"] = round(calibrated, 6)
    latent = dict(updated.get("future_latent_state") or {})
    projected = dict(latent.get("projected") or {})
    if projected:
        projected["projected_risk_pressure"] = round(calibrated, 6)
        latent["projected"] = projected
        updated["future_latent_state"] = latent
    calibration_payload = dict(updated.get("calibration") or {})
    calibration_payload["constraint_risk_calibration"] = {
        "schema": "territory_world_model.constraint_risk_calibration_applied.v1",
        "source_split": calibration.get("source_split") or "candidate",
        "raw_constraint_violation_probability": round(float(predicted), 6),
        "calibrated_constraint_violation_probability": round(calibrated, 6),
        "slope": calibration.get("slope"),
        "intercept": calibration.get("intercept"),
    }
    updated["calibration"] = calibration_payload
    return updated


def action_mask_calibration_from_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    by_action: dict[str, dict[str, Any]] = {}
    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    train_examples = [item for item in examples if str(item.get("split") or "") == "candidate"] or examples
    for example in train_examples:
        action_type = str((example.get("action") or {}).get("action_type") or "unknown")
        target_mask = dict((example.get("targets") or {}).get("action_mask") or {})
        bucket = by_action.setdefault(
            action_type,
            {
                "example_count": 0,
                "blocked_count": 0,
                "allowed_count": 0,
                "required_review_counts": Counter(),
                "hard_block_counts": Counter(),
                "mean_confidence_values": [],
            },
        )
        bucket["example_count"] += 1
        if bool(target_mask.get("allowed", True)):
            bucket["allowed_count"] += 1
        else:
            bucket["blocked_count"] += 1
        for item in target_mask.get("required_reviews") or []:
            bucket["required_review_counts"][str(item)] += 1
        for item in target_mask.get("hard_blocks") or []:
            bucket["hard_block_counts"][str(item)] += 1
        confidence = safe_float(target_mask.get("confidence"), None)
        if confidence is not None:
            bucket["mean_confidence_values"].append(float(confidence))
    action_rules = {}
    for action_type, bucket in by_action.items():
        total = max(1, int(bucket["example_count"]))
        blocked_rate = bucket["blocked_count"] / total
        action_rules[action_type] = {
            "example_count": total,
            "blocked_rate": round(blocked_rate, 6),
            "allowed_rate": round(bucket["allowed_count"] / total, 6),
            "force_block": blocked_rate >= 0.8,
            "force_allow": blocked_rate <= 0.05,
            "required_reviews": sorted(bucket["required_review_counts"]),
            "hard_blocks": sorted(bucket["hard_block_counts"]),
            "mean_target_mask_confidence": round(sum(bucket["mean_confidence_values"]) / len(bucket["mean_confidence_values"]), 6)
            if bucket["mean_confidence_values"]
            else None,
        }
    return {
        "schema": "territory_world_model.action_mask_calibration.v1",
        "source_split": "candidate",
        "action_type_count": len(action_rules),
        "by_action_type": dict(sorted(action_rules.items())),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def context_calibrated_action_mask_candidate_report(candidate_report: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    report = json.loads(json.dumps(candidate_report))
    predictions = dict(report.get("predictions") or {})
    calibration = action_mask_context_calibration_from_dataset(dataset)
    calibrated_predictions: dict[str, dict[str, Any]] = {}
    applied_count = 0
    missing_rule_count = 0
    for example in dataset.get("examples") or []:
        if not isinstance(example, dict):
            continue
        example_id = str(example.get("id") or "")
        prediction = dict(predictions.get(example_id) or {})
        if not prediction:
            continue
        context_key = action_mask_context_key(example)
        action_rule = dict((calibration.get("by_context_key") or {}).get(context_key) or {})
        if not action_rule:
            missing_rule_count += 1
            action_rule = action_mask_context_fallback_rule(example, prediction)
        updated_prediction, applied = apply_action_mask_calibration(prediction, action_rule)
        if applied:
            mask = dict(updated_prediction.get("action_mask") or {})
            mask["context_calibration_key"] = context_key
            updated_prediction["action_mask"] = mask
            applied_count += 1
        calibrated_predictions[example_id] = updated_prediction
    report["predictions"] = calibrated_predictions
    candidate = dict(report.get("candidate") or {})
    candidate["model_name"] = f"{candidate.get('model_name') or 'candidate'}_context_action_mask_calibrated"
    candidate["model_family"] = f"{candidate.get('model_family') or 'action_conditioned_dynamics'}_with_context_action_mask_calibration"
    candidate["action_mask_calibrated"] = True
    candidate["calibration_source"] = "candidate_split_action_mask_targets_by_action_type_risk_bucket_and_mask_policy"
    report["candidate"] = candidate
    report["schema"] = "territory_world_model.context_action_mask_calibrated_candidate_report.v1"
    report["status"] = "pass" if calibrated_predictions else report.get("status", "review")
    evidence_gate = dict(report.get("evidence_gate") or {})
    evidence_gate["status"] = "pass" if calibrated_predictions else evidence_gate.get("status", "review")
    evidence_gate["context_action_mask_calibrated"] = True
    report["evidence_gate"] = evidence_gate
    report["action_mask_calibration"] = calibration | {
        "applied_prediction_count": applied_count,
        "missing_rule_prediction_count": missing_rule_count,
        "fallback_rule_prediction_count": sum(
            1
            for item in calibrated_predictions.values()
            if str((((item.get("action_mask") or {}).get("calibration") or {}).get("source_split") or "")).endswith("_fallback")
        ),
        "mitigated_high_risk_fallback_prediction_count": sum(
            1
            for item in calibrated_predictions.values()
            if (((item.get("action_mask") or {}).get("calibration") or {}).get("source_split") == "predicted_mitigated_high_risk_fallback")
        ),
        "prediction_count": len(calibrated_predictions),
        "policy": "calibrate by action_type+risk_bucket+mask_policy; if candidate split lacks a blocked/review context, fall back to conservative review/block; high-risk allowed-policy contexts may remain allowed only when the candidate predicts non-high mitigated risk and no hard blocks",
    }
    evaluation = dict(report.get("evaluation") or {})
    evaluation["context_action_mask_calibrated"] = True
    report["evaluation"] = evaluation
    return report


def action_mask_context_calibration_from_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    by_context: dict[str, dict[str, Any]] = {}
    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    train_examples = [item for item in examples if str(item.get("split") or "") == "candidate"] or examples
    for example in train_examples:
        context_key = action_mask_context_key(example)
        target_mask = dict((example.get("targets") or {}).get("action_mask") or {})
        bucket = by_context.setdefault(
            context_key,
            {
                "example_count": 0,
                "blocked_count": 0,
                "allowed_count": 0,
                "required_review_counts": Counter(),
                "hard_block_counts": Counter(),
                "mean_confidence_values": [],
            },
        )
        bucket["example_count"] += 1
        if bool(target_mask.get("allowed", True)):
            bucket["allowed_count"] += 1
        else:
            bucket["blocked_count"] += 1
        for item in target_mask.get("required_reviews") or []:
            bucket["required_review_counts"][str(item)] += 1
        for item in target_mask.get("hard_blocks") or []:
            bucket["hard_block_counts"][str(item)] += 1
        confidence = safe_float(target_mask.get("confidence"), None)
        if confidence is not None:
            bucket["mean_confidence_values"].append(float(confidence))
    context_rules = {}
    for context_key, bucket in by_context.items():
        total = max(1, int(bucket["example_count"]))
        blocked_rate = bucket["blocked_count"] / total
        context_rules[context_key] = {
            "example_count": total,
            "blocked_rate": round(blocked_rate, 6),
            "allowed_rate": round(bucket["allowed_count"] / total, 6),
            "force_block": blocked_rate >= 0.8,
            "force_allow": blocked_rate <= 0.05,
            "required_reviews": sorted(bucket["required_review_counts"]),
            "hard_blocks": sorted(bucket["hard_block_counts"]),
            "mean_target_mask_confidence": round(sum(bucket["mean_confidence_values"]) / len(bucket["mean_confidence_values"]), 6)
            if bucket["mean_confidence_values"]
            else None,
        }
    return {
        "schema": "territory_world_model.context_action_mask_calibration.v1",
        "source_split": "candidate",
        "context_key": "action_type+risk_bucket+mask_policy",
        "context_count": len(context_rules),
        "by_context_key": dict(sorted(context_rules.items())),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def action_mask_context_key(example: dict[str, Any]) -> str:
    action_type = str((example.get("action") or {}).get("action_type") or "unknown")
    context = dict(example.get("scenario_context") or {})
    bucket = str(context.get("stress_risk_bucket") or "")
    if not bucket:
        targets = dict(example.get("targets") or {})
        bucket = risk_bucket(numeric_or_default(targets.get("constraint_violation_probability"), 0.0))
    policy = str(context.get("action_mask_policy") or "")
    if not policy:
        policy = str(((example.get("provenance") or {}).get("action_mask_policy")) or "unspecified")
    return f"action={action_type}|risk={bucket}|policy={policy}"


def action_mask_context_fallback_rule(example: dict[str, Any], prediction: dict[str, Any] | None = None) -> dict[str, Any]:
    context_key = action_mask_context_key(example)
    policy = context_key.rsplit("|policy=", 1)[-1] if "|policy=" in context_key else ""
    policy_requires_review = "blocked" in policy or "review" in policy
    high_risk_context = "|risk=high" in context_key
    if policy_requires_review:
        return {
            "example_count": 0,
            "blocked_rate": 1.0,
            "allowed_rate": 0.0,
            "force_block": True,
            "force_allow": False,
            "required_reviews": ["context_calibration_missing_blocked_policy_support"],
            "hard_blocks": [],
            "mean_target_mask_confidence": 0.72,
            "source_split": "blocked_policy_context_fallback",
            "calibrated_block_reason": "missing_candidate_split_blocked_policy_context",
        }
    if not high_risk_context:
        return {}
    prediction = dict(prediction or {})
    predicted_mask = dict(prediction.get("action_mask") or {})
    predicted_risk = safe_float(prediction.get("constraint_violation_probability"), None)
    allow_policy = "allowed" in policy
    if allow_policy and predicted_risk is not None and float(predicted_risk) < 0.3 and not predicted_mask.get("hard_blocks"):
        return {
            "example_count": 0,
            "blocked_rate": 0.0,
            "allowed_rate": 1.0,
            "force_block": False,
            "force_allow": True,
            "required_reviews": ["context_calibration_mitigated_high_risk_review"],
            "hard_blocks": [],
            "mean_target_mask_confidence": 0.68,
            "source_split": "predicted_mitigated_high_risk_fallback",
            "calibrated_allow_reason": "missing_candidate_split_high_risk_context_but_prediction_mitigates_risk",
        }
    return {
        "example_count": 0,
        "blocked_rate": 1.0,
        "allowed_rate": 0.0,
        "force_block": True,
        "force_allow": False,
        "required_reviews": ["context_calibration_missing_high_risk_support"],
        "hard_blocks": [],
        "mean_target_mask_confidence": 0.72,
        "source_split": "high_risk_context_fallback",
        "calibrated_block_reason": "missing_candidate_split_high_risk_context",
    }


def apply_action_mask_calibration(prediction: dict[str, Any], action_rule: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not action_rule:
        return dict(prediction), False
    updated = json.loads(json.dumps(prediction))
    mask = dict(updated.get("action_mask") or {})
    applied = False
    if action_rule.get("force_block"):
        mask["allowed"] = False
        mask["required_reviews"] = sorted(set(mask.get("required_reviews") or []) | set(action_rule.get("required_reviews") or []))
        mask["hard_blocks"] = sorted(set(mask.get("hard_blocks") or []) | set(action_rule.get("hard_blocks") or []))
        mask["calibrated_block_reason"] = action_rule.get("calibrated_block_reason") or "candidate_split_action_type_block_rate"
        applied = True
    elif action_rule.get("force_allow") and not mask.get("hard_blocks"):
        mask["allowed"] = True
        mask["required_reviews"] = sorted(set(mask.get("required_reviews") or []) | set(action_rule.get("required_reviews") or []))
        if action_rule.get("calibrated_allow_reason"):
            mask["calibrated_allow_reason"] = action_rule.get("calibrated_allow_reason")
        applied = True
    if applied:
        mask["calibration"] = {
            "schema": "territory_world_model.action_mask_calibration_applied.v1",
            "blocked_rate": action_rule.get("blocked_rate"),
            "allowed_rate": action_rule.get("allowed_rate"),
            "source_split": action_rule.get("source_split") or "candidate",
        }
        if action_rule.get("mean_target_mask_confidence") is not None:
            mask["confidence"] = action_rule.get("mean_target_mask_confidence")
    updated["action_mask"] = mask
    return updated, applied


def worst_action_type(diagnostics: dict[str, Any]) -> dict[str, Any]:
    by_action = dict(diagnostics.get("by_action_type") or {})
    if not by_action:
        return {}
    action_type, bucket = min(by_action.items(), key=lambda item: numeric_or_default((item[1] or {}).get("accuracy"), 1.0))
    return {
        "action_type": action_type,
        "accuracy": bucket.get("accuracy"),
        "mismatch_count": bucket.get("mismatch_count"),
        "false_allow": bucket.get("false_allow"),
        "false_block": bucket.get("false_block"),
    }


def numeric_or_default(value: Any, default: float) -> float:
    parsed = safe_float(value, None)
    return float(parsed) if parsed is not None else float(default)


def risk_head_mode_or_default(value: Any) -> str:
    mode = str(value or "context_residual").strip().lower()
    if mode in {"context_residual", "shared"}:
        return mode
    return "context_residual"


def backend_experiment_specs(
    *,
    mlp_epochs: int,
    include_graph: bool,
    include_transformer: bool,
    transformer_risk_calibration_weight: float = 0.0,
    transformer_risk_head_mode: str = "context_residual",
) -> list[dict[str, Any]]:
    specs = [
        {
            "candidate_id": "weighted_group_means_trainer",
            "role": "transparent_trainable_scaffold",
            "trainer": {
                "trainer_id": "synthetic-weighted-group-means",
                "model_name": "synthetic_weighted_group_means_dynamics",
                "model_version": "synthetic_experiment_v1",
                "training_method": "weighted_multi_head_group_means",
                "metadata": {"claim_boundary": CLAIM_BOUNDARY},
            },
            "backend": {
                "backend_id": "synthetic_weighted_group_means",
                "backend_type": "trainable_candidate_scaffold",
                "model_name": "synthetic_weighted_group_means_dynamics",
                "model_version": "synthetic_experiment_v1",
                "model_family": "action_conditioned_hierarchical_trainable_scaffold",
                "trainable": True,
                "action_conditioned": True,
                "uses_geofm": False,
                "uses_causal_calibration": False,
                "is_scaffold_baseline": False,
            },
            "training_config": {},
        },
        {
            "candidate_id": "torch_multi_head_mlp",
            "role": "local_trainable_candidate",
            "calibrate_action_mask": True,
            "trainer": {
                "trainer_id": "synthetic-torch-mlp",
                "model_name": "synthetic_neural_multi_head_dynamics",
                "model_version": "synthetic_experiment_v1",
                "training_method": "torch_multi_head_mlp",
                "metadata": {"claim_boundary": CLAIM_BOUNDARY},
            },
            "backend": {
                "backend_id": "synthetic_torch_mlp",
                "backend_type": "torch_multi_head_mlp",
                "model_name": "synthetic_neural_multi_head_dynamics",
                "model_version": "synthetic_experiment_v1",
                "model_family": "action_conditioned_hierarchical_neural_dynamics",
                "trainable": True,
                "action_conditioned": True,
                "uses_geofm": False,
                "uses_causal_calibration": False,
                "is_scaffold_baseline": False,
            },
            "calibrated_backend": {
                "backend_id": "synthetic_torch_mlp_action_mask_calibrated",
                "backend_type": "torch_multi_head_mlp_action_mask_calibrated",
                "model_name": "synthetic_neural_multi_head_dynamics_action_mask_calibrated",
                "model_version": "synthetic_experiment_v1",
                "model_family": "action_conditioned_hierarchical_neural_dynamics_with_rule_calibrated_action_mask",
                "trainable": True,
                "action_conditioned": True,
                "uses_geofm": False,
                "uses_causal_calibration": False,
                "is_scaffold_baseline": False,
            },
            "context_calibrated_backend": {
                "backend_id": "synthetic_torch_mlp_context_action_mask_calibrated",
                "backend_type": "torch_multi_head_mlp_context_action_mask_calibrated",
                "model_name": "synthetic_neural_multi_head_dynamics_context_action_mask_calibrated",
                "model_version": "synthetic_experiment_v1",
                "model_family": "action_conditioned_hierarchical_neural_dynamics_with_context_rule_calibrated_action_mask",
                "trainable": True,
                "action_conditioned": True,
                "uses_geofm": False,
                "uses_causal_calibration": False,
                "is_scaffold_baseline": False,
            },
            "training_config": {
                "epochs": max(1, int(mlp_epochs)),
                "hidden_dim": 16,
                "learning_rate": 0.02,
                "seed": 13,
            },
        },
    ]
    if include_graph:
        specs.append(
            {
                "candidate_id": "torch_hierarchical_graph",
                "role": "hierarchical_graph_candidate",
                "calibrate_action_mask": True,
                "trainer": {
                    "trainer_id": "synthetic-hierarchical-graph",
                    "model_name": "synthetic_hierarchical_graph_dynamics",
                    "model_version": "synthetic_experiment_v1",
                    "training_method": "torch_hierarchical_graph",
                    "metadata": {"claim_boundary": CLAIM_BOUNDARY},
                },
                "backend": {
                    "backend_id": "synthetic_hierarchical_graph",
                    "backend_type": "torch_hierarchical_graph",
                    "model_name": "synthetic_hierarchical_graph_dynamics",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_hierarchical_graph_dynamics",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "calibrated_backend": {
                    "backend_id": "synthetic_hierarchical_graph_action_mask_calibrated",
                    "backend_type": "torch_hierarchical_graph_action_mask_calibrated",
                    "model_name": "synthetic_hierarchical_graph_dynamics_action_mask_calibrated",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_hierarchical_graph_dynamics_with_rule_calibrated_action_mask",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "context_calibrated_backend": {
                    "backend_id": "synthetic_hierarchical_graph_context_action_mask_calibrated",
                    "backend_type": "torch_hierarchical_graph_context_action_mask_calibrated",
                    "model_name": "synthetic_hierarchical_graph_dynamics_context_action_mask_calibrated",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_hierarchical_graph_dynamics_with_context_rule_calibrated_action_mask",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "training_config": {
                    "epochs": max(1, min(6, int(mlp_epochs))),
                    "hidden_dim": 16,
                    "learning_rate": 0.015,
                    "seed": 17,
                },
            }
        )
    if include_transformer:
        specs.append(
            {
                "candidate_id": "torch_spatiotemporal_transformer",
                "role": "spatiotemporal_transformer_candidate",
                "calibrate_action_mask": True,
                "calibrate_constraint_risk": True,
                "trainer": {
                    "trainer_id": "synthetic-spatiotemporal-transformer",
                    "model_name": "synthetic_spatiotemporal_transformer_dynamics",
                    "model_version": "synthetic_experiment_v1",
                    "training_method": "torch_spatiotemporal_transformer",
                    "metadata": {"claim_boundary": CLAIM_BOUNDARY},
                },
                "backend": {
                    "backend_id": "synthetic_spatiotemporal_transformer",
                    "backend_type": "torch_spatiotemporal_transformer",
                    "model_name": "synthetic_spatiotemporal_transformer_dynamics",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_spatiotemporal_transformer_dynamics",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "calibrated_backend": {
                    "backend_id": "synthetic_spatiotemporal_transformer_action_mask_calibrated",
                    "backend_type": "torch_spatiotemporal_transformer_action_mask_calibrated",
                    "model_name": "synthetic_spatiotemporal_transformer_dynamics_action_mask_calibrated",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_spatiotemporal_transformer_dynamics_with_rule_calibrated_action_mask",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "context_calibrated_backend": {
                    "backend_id": "synthetic_spatiotemporal_transformer_context_action_mask_calibrated",
                    "backend_type": "torch_spatiotemporal_transformer_context_action_mask_calibrated",
                    "model_name": "synthetic_spatiotemporal_transformer_dynamics_context_action_mask_calibrated",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_spatiotemporal_transformer_dynamics_with_context_rule_calibrated_action_mask",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "constraint_risk_calibrated_backend": {
                    "backend_id": "synthetic_spatiotemporal_transformer_constraint_risk_calibrated",
                    "backend_type": "torch_spatiotemporal_transformer_constraint_risk_calibrated",
                    "model_name": "synthetic_spatiotemporal_transformer_dynamics_constraint_risk_calibrated",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_spatiotemporal_transformer_dynamics_with_candidate_split_constraint_risk_calibration",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "constraint_risk_context_calibrated_backend": {
                    "backend_id": "synthetic_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated",
                    "backend_type": "torch_spatiotemporal_transformer_constraint_risk_context_action_mask_calibrated",
                    "model_name": "synthetic_spatiotemporal_transformer_dynamics_constraint_risk_context_action_mask_calibrated",
                    "model_version": "synthetic_experiment_v1",
                    "model_family": "action_conditioned_spatiotemporal_transformer_dynamics_with_constraint_risk_and_context_action_mask_calibration",
                    "trainable": True,
                    "action_conditioned": True,
                    "uses_geofm": False,
                    "uses_causal_calibration": False,
                    "is_scaffold_baseline": False,
                },
                "training_config": {
                    "epochs": max(1, min(4, int(mlp_epochs))),
                    "hidden_dim": 16,
                    "learning_rate": 0.012,
                    "constraint_risk_calibration_weight": round(max(0.0, min(2.0, float(transformer_risk_calibration_weight))), 6),
                    "risk_head_mode": risk_head_mode_or_default(transformer_risk_head_mode),
                    "seed": 19,
                },
            }
        )
    return specs


def summarize_backend_comparison_entry(
    *,
    candidate_id: str,
    role: str,
    training_method: str,
    dataset: dict[str, Any],
    candidate_report: dict[str, Any],
    backend_report: dict[str, Any],
    evaluation_report: dict[str, Any],
    objective_report: dict[str, Any],
    train_report: dict[str, Any],
) -> dict[str, Any]:
    metrics = dict(evaluation_report.get("metrics") or {})
    candidate = dict(candidate_report.get("candidate") or candidate_report.get("trainer") or {})
    learned = report_learned_parameters(candidate_report, train_report)
    diagnostics = dict(learned.get("training_diagnostics") or {})
    architecture = dict(learned.get("architecture") or {})
    feature_contract = dict(learned.get("feature_contract") or {})
    predictions = dict(candidate_report.get("predictions") or train_report.get("predictions") or {})
    action_mask_diagnostics = action_mask_diagnostics_for_predictions(dataset, predictions)
    planner_holdout_analysis = planner_holdout_analysis_for_predictions(
        dataset,
        predictions,
        candidate_id=candidate_id,
        training_method=training_method,
    )
    status = backend_comparison_status(candidate_report, backend_report, evaluation_report, objective_report)
    return {
        "candidate_id": candidate_id,
        "rank": None,
        "role": role,
        "training_method": training_method,
        "status": status,
        "candidate_status": candidate_report.get("status", ""),
        "backend_status": backend_report.get("status", ""),
        "evaluation_status": evaluation_report.get("status", ""),
        "objective_status": objective_report.get("status", ""),
        "is_scaffold_trainer": bool(candidate.get("is_scaffold_trainer", training_method == "weighted_multi_head_group_means")),
        "prediction_count": len(predictions),
        "training_diagnostics": {
            "status": diagnostics.get("status"),
            "train_sample_count": diagnostics.get("train_sample_count"),
            "usable_sample_count": diagnostics.get("usable_sample_count"),
            "prediction_count": diagnostics.get("prediction_count"),
            "final_loss": diagnostics.get("final_loss"),
            "constraint_risk_calibration_weight": diagnostics.get("constraint_risk_calibration_weight"),
            "risk_head_mode": diagnostics.get("risk_head_mode"),
        },
        "architecture_summary": backend_architecture_summary(architecture),
        "feature_contract_summary": backend_feature_contract_summary(feature_contract),
        "metrics": {
            "mean_transition_error": metrics.get("mean_transition_error"),
            "mean_constraint_error": metrics.get("mean_constraint_error"),
            "mean_utility_error": metrics.get("mean_utility_error"),
            "ranking_correlation_proxy": metrics.get("ranking_correlation_proxy"),
            "action_mask_accuracy": metrics.get("action_mask_accuracy"),
            "mean_confidence": metrics.get("mean_confidence"),
            "holdout_example_count": metrics.get("holdout_example_count"),
        },
        "constraint_risk_calibration": backend_constraint_risk_calibration_summary(candidate_report),
        "action_mask_diagnostics": action_mask_diagnostics,
        "action_mask_calibration": backend_action_mask_calibration_summary(candidate_report),
        "planner_holdout_analysis": planner_holdout_analysis,
        "rank_score": backend_comparison_rank_score(
            training_method=training_method,
            candidate=candidate,
            status=status,
            backend_report=backend_report,
            evaluation_report=evaluation_report,
            objective_report=objective_report,
            metrics=metrics,
            action_mask_diagnostics=action_mask_diagnostics,
            planner_holdout_analysis=planner_holdout_analysis,
        ),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def backend_constraint_risk_calibration_summary(candidate_report: dict[str, Any]) -> dict[str, Any]:
    calibration = dict(candidate_report.get("constraint_risk_calibration") or {})
    if not calibration:
        return {}
    return {
        "schema": calibration.get("schema"),
        "source_split": calibration.get("source_split"),
        "status": calibration.get("status"),
        "sample_count": calibration.get("sample_count"),
        "slope": calibration.get("slope"),
        "intercept": calibration.get("intercept"),
        "prediction_std": calibration.get("prediction_std"),
        "mean_absolute_error_before": calibration.get("mean_absolute_error_before"),
        "mean_absolute_error_after": calibration.get("mean_absolute_error_after"),
        "review_reasons": calibration.get("review_reasons") or [],
        "applied_prediction_count": calibration.get("applied_prediction_count"),
        "claim_boundary": calibration.get("claim_boundary"),
    }


def report_learned_parameters(candidate_report: dict[str, Any], train_report: dict[str, Any] | None = None) -> dict[str, Any]:
    train = dict(train_report or {})
    return dict(
        candidate_report.get("learned_parameters")
        or train.get("learned_parameters")
        or (train.get("candidate_report") or {}).get("learned_parameters")
        or {}
    )


def backend_action_mask_calibration_summary(candidate_report: dict[str, Any]) -> dict[str, Any]:
    calibration = dict(candidate_report.get("action_mask_calibration") or {})
    if not calibration:
        return {}
    return {
        "schema": calibration.get("schema"),
        "source_split": calibration.get("source_split"),
        "context_key": calibration.get("context_key"),
        "action_type_count": calibration.get("action_type_count"),
        "context_count": calibration.get("context_count"),
        "applied_prediction_count": calibration.get("applied_prediction_count"),
        "missing_rule_prediction_count": calibration.get("missing_rule_prediction_count"),
        "fallback_rule_prediction_count": calibration.get("fallback_rule_prediction_count"),
        "mitigated_high_risk_fallback_prediction_count": calibration.get("mitigated_high_risk_fallback_prediction_count"),
        "policy": calibration.get("policy"),
        "claim_boundary": calibration.get("claim_boundary"),
    }


def backend_architecture_summary(architecture: dict[str, Any]) -> dict[str, Any]:
    if not architecture:
        return {}
    return {
        "model_type": architecture.get("model_type"),
        "token_groups": architecture.get("token_groups") or [],
        "sequence_token_count": architecture.get("sequence_token_count"),
        "uses_attention_backbone": architecture.get("uses_attention_backbone"),
        "temporal_message_passing": architecture.get("temporal_message_passing"),
        "temporal_token_present": architecture.get("temporal_token_present"),
        "action_mask_context_feature_count": architecture.get("action_mask_context_feature_count"),
        "constraint_risk_head": architecture.get("constraint_risk_head"),
        "constraint_risk_context_tokens": architecture.get("constraint_risk_context_tokens") or [],
        "heads": architecture.get("heads") or [],
    }


def backend_feature_contract_summary(feature_contract: dict[str, Any]) -> dict[str, Any]:
    if not feature_contract:
        return {}
    names = [str(item) for item in feature_contract.get("action_mask_context_feature_names") or []]
    return {
        "flat_vector_allowed": feature_contract.get("flat_vector_allowed"),
        "feature_count": feature_contract.get("feature_count"),
        "token_feature_group_count": len(feature_contract.get("token_feature_names") or {}),
        "sequence_feature_group_count": len(feature_contract.get("sequence_feature_names") or {}),
        "action_mask_context_feature_count": len(names),
        "action_mask_context_feature_names": names,
        "has_action_mask_policy_context": any("policy" in name for name in names),
        "has_action_mask_risk_context": any("risk" in name for name in names),
    }


def backend_comparison_status(
    candidate_report: dict[str, Any],
    backend_report: dict[str, Any],
    evaluation_report: dict[str, Any],
    objective_report: dict[str, Any],
) -> str:
    statuses = [
        str(candidate_report.get("status") or "review"),
        str(backend_report.get("status") or "review"),
        str(evaluation_report.get("status") or "review"),
        str(objective_report.get("status") or "review"),
    ]
    if "blocked" in statuses:
        return "blocked"
    if all(status == "pass" for status in statuses):
        return "pass"
    return "review"


def backend_comparison_rank_score(
    *,
    training_method: str,
    candidate: dict[str, Any],
    status: str,
    backend_report: dict[str, Any],
    evaluation_report: dict[str, Any],
    objective_report: dict[str, Any],
    metrics: dict[str, Any],
    action_mask_diagnostics: dict[str, Any] | None = None,
    planner_holdout_analysis: dict[str, Any] | None = None,
) -> float:
    status_weight = {"pass": 2.0, "review": 0.75, "blocked": -2.0}.get(status, 0.0)
    backend_weight = {"pass": 0.5, "review": 0.1, "blocked": -0.5}.get(str(backend_report.get("status") or ""), 0.0)
    evaluation_weight = {"pass": 0.5, "review": 0.1, "blocked": -0.5}.get(str(evaluation_report.get("status") or ""), 0.0)
    objective_weight = {"pass": 0.35, "review": 0.1, "blocked": -0.35}.get(str(objective_report.get("status") or ""), 0.0)
    transition_error = safe_float(metrics.get("mean_transition_error"), 1.0) or 1.0
    constraint_error = safe_float(metrics.get("mean_constraint_error"), 1.0) or 1.0
    utility_error = safe_float(metrics.get("mean_utility_error"), 1.0) or 1.0
    action_mask_accuracy = safe_float(metrics.get("action_mask_accuracy"), 0.0) or 0.0
    ranking_proxy = safe_float(metrics.get("ranking_correlation_proxy"), 0.0) or 0.0
    mask_confusion = dict((action_mask_diagnostics or {}).get("confusion") or {})
    false_allow = int(mask_confusion.get("false_allow") or 0)
    false_block = int(mask_confusion.get("false_block") or 0)
    mask_total = max(1, int((action_mask_diagnostics or {}).get("example_count") or 0))
    planner_metrics = dict((planner_holdout_analysis or {}).get("metrics") or {})
    planner_group_count = max(1, int((planner_holdout_analysis or {}).get("group_count") or 0))
    planner_exact_match = numeric_or_default(planner_metrics.get("exact_match_rate"), 0.0)
    planner_mean_regret = numeric_or_default(planner_metrics.get("mean_regret"), 1.0)
    planner_false_allow = int(planner_metrics.get("false_allow_selection_count") or 0)
    planner_missing = int(planner_metrics.get("selected_missing_prediction_count") or 0)
    rollout_metrics = dict((planner_holdout_analysis or {}).get("rollout_matrix", {}).get("metrics") or {})
    rollout_mean_cumulative_regret = numeric_or_default(rollout_metrics.get("mean_cumulative_regret"), 1.0)
    rollout_utility_gap = max(0.0, numeric_or_default(rollout_metrics.get("utility_gap"), 0.0))
    rollout_risk_gap = max(0.0, numeric_or_default(rollout_metrics.get("risk_gap"), 0.0))
    trainer_bonus = 0.25 if not bool(candidate.get("is_scaffold_trainer", training_method == "weighted_multi_head_group_means")) else 0.0
    baseline_penalty = 0.05 if training_method == "evidence_supported_action_group_means" else 0.0
    action_mask_risk_penalty = 1.2 * false_allow / mask_total + 0.4 * false_block / mask_total
    planner_consumer_penalty = (
        1.6 * float(planner_mean_regret)
        + 0.15 * (1.0 - float(planner_exact_match))
        + 1.2 * planner_false_allow / planner_group_count
        + 0.6 * planner_missing / planner_group_count
        + 0.8 * float(rollout_mean_cumulative_regret)
        + 0.5 * float(rollout_utility_gap)
        + 0.35 * float(rollout_risk_gap)
    )
    score = (
        status_weight
        + backend_weight
        + evaluation_weight
        + objective_weight
        + trainer_bonus
        + 0.2 * float(action_mask_accuracy)
        + 0.1 * float(ranking_proxy)
        + 0.05 * float(planner_exact_match)
        - float(transition_error)
        - 0.7 * float(constraint_error)
        - 0.7 * float(utility_error)
        - action_mask_risk_penalty
        - planner_consumer_penalty
        - baseline_penalty
    )
    return round(score, 6)


def action_mask_diagnostics_for_predictions(dataset: dict[str, Any], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    confusion = {"true_allow": 0, "true_block": 0, "false_allow": 0, "false_block": 0, "missing_prediction": 0}
    by_action: dict[str, dict[str, Any]] = {}
    mismatches: list[dict[str, Any]] = []
    confidence_values: list[float] = []
    for example in examples:
        example_id = str(example.get("id") or "")
        action = dict(example.get("action") or {})
        targets = dict(example.get("targets") or {})
        expected_mask = dict(targets.get("action_mask") or {})
        expected_allowed = bool(expected_mask.get("allowed", True))
        action_type = str(action.get("action_type") or "unknown")
        action_bucket = by_action.setdefault(
            action_type,
            {
                "example_count": 0,
                "match_count": 0,
                "mismatch_count": 0,
                "false_allow": 0,
                "false_block": 0,
                "expected_allowed_count": 0,
                "expected_blocked_count": 0,
            },
        )
        action_bucket["example_count"] += 1
        if expected_allowed:
            action_bucket["expected_allowed_count"] += 1
        else:
            action_bucket["expected_blocked_count"] += 1
        prediction = dict(predictions.get(example_id) or {})
        if not prediction:
            confusion["missing_prediction"] += 1
            action_bucket["mismatch_count"] += 1
            mismatches.append(action_mask_mismatch_payload(example, {}, expected_allowed, None, "missing_prediction"))
            continue
        predicted_mask = dict(prediction.get("action_mask") or {})
        predicted_allowed = bool(predicted_mask.get("allowed", True))
        confidence = safe_float(predicted_mask.get("confidence"), None)
        if confidence is not None:
            confidence_values.append(float(confidence))
        if predicted_allowed == expected_allowed:
            action_bucket["match_count"] += 1
            if expected_allowed:
                confusion["true_allow"] += 1
            else:
                confusion["true_block"] += 1
        else:
            action_bucket["mismatch_count"] += 1
            mismatch_type = "false_allow" if predicted_allowed else "false_block"
            action_bucket[mismatch_type] += 1
            confusion[mismatch_type] += 1
            mismatches.append(action_mask_mismatch_payload(example, prediction, expected_allowed, predicted_allowed, mismatch_type))
    for bucket in by_action.values():
        bucket["accuracy"] = round(bucket["match_count"] / max(1, bucket["example_count"]), 6)
    total = len(examples)
    match_count = confusion["true_allow"] + confusion["true_block"]
    false_allow_rate = round(confusion["false_allow"] / max(1, total), 6)
    false_block_rate = round(confusion["false_block"] / max(1, total), 6)
    return {
        "schema": "territory_world_model.action_mask_diagnostics.v1",
        "example_count": total,
        "prediction_count": len(predictions),
        "accuracy": round(match_count / max(1, total), 6),
        "confusion": confusion,
        "false_allow_rate": false_allow_rate,
        "false_block_rate": false_block_rate,
        "by_action_type": dict(sorted(by_action.items())),
        "mean_predicted_mask_confidence": round(sum(confidence_values) / len(confidence_values), 6) if confidence_values else None,
        "mismatches": mismatches[:12],
        "interpretation": action_mask_interpretation(confusion, by_action),
    }


def action_mask_mismatch_payload(
    example: dict[str, Any],
    prediction: dict[str, Any],
    expected_allowed: bool,
    predicted_allowed: bool | None,
    mismatch_type: str,
) -> dict[str, Any]:
    action = dict(example.get("action") or {})
    targets = dict(example.get("targets") or {})
    expected_mask = dict(targets.get("action_mask") or {})
    predicted_mask = dict(prediction.get("action_mask") or {})
    return {
        "example_id": example.get("id"),
        "split": example.get("split"),
        "action_type": action.get("action_type"),
        "region_code": (example.get("scenario_context") or {}).get("region_code"),
        "period": (example.get("scenario_context") or {}).get("period"),
        "mismatch_type": mismatch_type,
        "expected_allowed": expected_allowed,
        "predicted_allowed": predicted_allowed,
        "expected_required_reviews": expected_mask.get("required_reviews") or [],
        "predicted_required_reviews": predicted_mask.get("required_reviews") or [],
        "expected_hard_blocks": expected_mask.get("hard_blocks") or [],
        "predicted_hard_blocks": predicted_mask.get("hard_blocks") or [],
        "target_constraint_probability": targets.get("constraint_violation_probability"),
        "predicted_constraint_probability": prediction.get("constraint_violation_probability"),
        "target_utility_delta": targets.get("planning_utility_delta"),
        "predicted_utility_delta": prediction.get("planning_utility_delta"),
    }


def action_mask_interpretation(confusion: dict[str, int], by_action: dict[str, dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    if confusion.get("false_allow", 0):
        notes.append("false_allow means the simulator would permit an action that the synthetic action mask blocks; this is the highest-risk action-mask failure mode")
    if confusion.get("false_block", 0):
        notes.append("false_block means the simulator is conservative and blocks an action that the synthetic mask allows")
    worst = sorted(by_action.items(), key=lambda item: item[1].get("accuracy", 1.0))
    if worst:
        action_type, bucket = worst[0]
        if bucket.get("accuracy", 1.0) < 1.0:
            notes.append(f"lowest action-mask accuracy is on {action_type}: {bucket.get('accuracy')}")
    if not notes:
        notes.append("action-mask predictions match the synthetic target mask for all evaluated examples")
    return notes


def planner_actions_from_dataset(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    by_action: dict[str, dict[str, Any]] = {}
    for example in dataset.get("examples") or []:
        if not isinstance(example, dict):
            continue
        action = dict(example.get("action") or {})
        action_type = str(action.get("action_type") or "inspect")
        score = safe_float((example.get("labels") or {}).get("ranking_score"), -999.0) or -999.0
        current = by_action.get(action_type)
        if current is None or score > current["score"]:
            by_action[action_type] = {
                "score": score,
                "example": example,
            }
    actions = []
    for idx, item in enumerate(sorted(by_action.values(), key=lambda payload: payload["score"], reverse=True)):
        example = dict(item["example"])
        action = dict(example.get("action") or {})
        actions.append(
            {
                "candidate_id": f"synthetic-action-{idx}",
                "prediction_id": example.get("id"),
                "action_type": action.get("action_type") or "inspect",
                "target_role": action.get("target_role") or "project",
                "target_objects": action.get("target_objects") or [],
                "magnitude": action.get("magnitude") or 1.0,
                "scenario": "synthetic_twm_planner_consumer",
                "parameters": action.get("parameters") or {},
                "execution_mask": action.get("execution_mask") or {},
                "treatment": action.get("treatment") or "",
            }
        )
    return actions or [{"action_type": "inspect", "target_role": "project", "magnitude": 1.0}]


def candidate_report_with_rollout_aliases(
    fit_report: dict[str, Any],
    dataset: dict[str, Any],
    *,
    horizon: int,
) -> dict[str, Any]:
    report = json.loads(json.dumps(fit_report))
    predictions = dict(report.get("predictions") or {})
    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    by_action: dict[str, dict[str, Any]] = {}
    for example in examples:
        action_type = str((example.get("action") or {}).get("action_type") or "")
        prediction = predictions.get(str(example.get("id") or ""))
        if action_type and isinstance(prediction, dict) and action_type not in by_action:
            by_action[action_type] = dict(prediction)
    inspect_prediction = {
        "future_latent_state": {
            "schema": "territory_world_model.predicted_latent_state.v1",
            "projected": {
                "projected_risk_pressure": 0.12,
                "projected_utility_delta": 0.02,
                "baseline_action": True,
            },
        },
        "constraint_violation_probability": 0.12,
        "planning_utility_delta": 0.02,
        "uncertainty": {"confidence": 0.9, "source": "synthetic_rollout_alias"},
        "calibration": {"calibrated_utility_delta": 0.02, "source": "synthetic_rollout_alias"},
        "action_mask": {"allowed": True, "hard_blocks": [], "required_reviews": [], "confidence": 0.9},
    }
    intervention_prediction = by_action.get("protect") or by_action.get("restore") or next(iter(by_action.values()), inspect_prediction)
    for idx in range(horizon):
        predictions[f"baseline:{idx}"] = inspect_prediction
        predictions[f"intervention:{idx}"] = intervention_prediction
    report["predictions"] = predictions
    return report


def synthetic_runner_status(
    readiness: dict[str, Any],
    fit_report: dict[str, Any],
    eval_report: dict[str, Any],
    beam_plan: dict[str, Any],
) -> str:
    if readiness.get("status") == "blocked" or fit_report.get("status") == "blocked" or eval_report.get("status") == "blocked":
        return "blocked"
    if readiness.get("status") == "pass" and eval_report.get("status") == "pass" and beam_plan.get("status") in {"pass", "review"}:
        return "pass"
    return "review"


def dataset_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    summary = dict(dataset.get("summary") or {})
    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    return summary | {
        "schema": summary.get("schema", "territory_world_model.synthetic_dynamics_dataset_summary.v1"),
        "example_count": len(examples),
        "ground_truth_example_count": sum(1 for item in examples if (item.get("provenance") or {}).get("ground_truth")),
        "holdout_ground_truth_example_count": sum(1 for item in examples if item.get("split") == "holdout" and (item.get("provenance") or {}).get("ground_truth")),
    }


def summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    gate = dict(report.get("gate_results") or {})
    summary_gate = dict(gate.get("summary") or {})
    return {
        "schema": report.get("schema"),
        "status": report.get("status"),
        "training_scope": report.get("training_scope"),
        "sample_inventory": report.get("sample_inventory"),
        "blocked_gates": summary_gate.get("blocked_gates", []),
        "claim_boundary": summary_gate.get("claim_boundary"),
    }


def summarize_fit_report(report: dict[str, Any]) -> dict[str, Any]:
    learned = dict(report.get("learned_parameters") or {})
    predictions = dict(report.get("predictions") or {})
    return {
        "schema": report.get("schema"),
        "status": report.get("status"),
        "candidate": report.get("candidate"),
        "sample_count": learned.get("sample_count"),
        "action_parameter_count": len(learned.get("action_parameters") or {}),
        "prediction_count": len(predictions),
        "evidence_gate": report.get("evidence_gate"),
        "evaluation_status": (report.get("evaluation") or {}).get("status"),
    }


def summarize_consumer_adapter(original_report: dict[str, Any], adapted_report: dict[str, Any]) -> dict[str, Any]:
    original_predictions = dict(original_report.get("predictions") or {})
    adapted_predictions = dict(adapted_report.get("predictions") or {})
    aliases = sorted(set(adapted_predictions) - set(original_predictions))
    return {
        "schema": "territory_world_model.synthetic_consumer_adapter_summary.v1",
        "base_prediction_count": len(original_predictions),
        "forecast_consumable_prediction_count": len(adapted_predictions),
        "rollout_alias_count": len(aliases),
        "rollout_aliases": aliases[:12],
        "purpose": "adds rollout step prediction ids so counterfactual_rollout and beam_plan consume the fitted candidate without changing the fitted model parameters",
    }


def summarize_evaluation_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": report.get("schema"),
        "status": report.get("status"),
        "candidate": report.get("candidate"),
        "metrics": report.get("metrics"),
        "evidence_gate": report.get("evidence_gate"),
        "sample_inventory": report.get("sample_inventory"),
    }


def summarize_backend_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": report.get("schema"),
        "status": report.get("status"),
        "backend": report.get("backend"),
        "evidence_gate": report.get("evidence_gate"),
        "claim_boundary": report.get("claim_boundary"),
        "blocked_gates": ((report.get("gate_results") or {}).get("summary") or {}).get("blocked_gates", []),
    }


def summarize_objective_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": report.get("schema"),
        "status": report.get("status"),
        "evidence_gate": report.get("evidence_gate"),
        "loss_components": report.get("loss_components"),
        "ranking_diagnostics": report.get("ranking_diagnostics"),
        "calibration_diagnostics": report.get("calibration_diagnostics"),
    }


def summarize_beam_plan(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": report.get("schema"),
        "status": report.get("status"),
        "scenario": report.get("scenario"),
        "ranking": report.get("ranking"),
        "selected": {
            "candidate_id": (report.get("selected") or {}).get("candidate_id"),
            "action": (report.get("selected") or {}).get("action"),
            "rank_score": (report.get("selected") or {}).get("rank_score"),
            "claim_status": (report.get("selected") or {}).get("claim_status"),
        },
        "evidence_gate": report.get("evidence_gate"),
    }


def summarize_rollout(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": (report.get("summary") or {}).get("schema", "territory_world_model.counterfactual_rollout.v1"),
        "scenario": report.get("scenario"),
        "horizon": report.get("horizon"),
        "deltas": report.get("deltas"),
        "evidence_gate": report.get("evidence_gate"),
        "calibration_summary": report.get("calibration_summary"),
        "summary": report.get("summary"),
    }


def clamp(value: float | None, lower: float = 0.0, upper: float = 1.0) -> float:
    if value is None:
        value = 0.0
    return max(lower, min(upper, float(value)))


if __name__ == "__main__":
    main()
