#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.territory_world_model import TerritoryWorldModelService, TwmRepository, TwmStateVersion
from data_agent.territory_world_model.utils import read_csv, safe_float, truthy


DEFAULT_TWM_DATASET = REPO_ROOT / "data_agent/test_data/twm_bishan_multi_admin_eval"
DEFAULT_PAPER7_CAUSAL_DATASET = Path("/Users/zhouning/paper7-causal-mbrl-farmland-consolidation/paper7/results/causal_dataset.csv")
DEFAULT_PAPER7_CALIBRATION = Path("/Users/zhouning/paper7-causal-mbrl-farmland-consolidation/paper7/results/causal_calibration.json")
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_data_foundation_validation.json"
DEFAULT_STRUCTURAL_OBSERVED_HISTORY_OUTPUT = REPO_ROOT / "docs/reports/twm_structural_validation_observed_history.csv"
DEFAULT_SYNTHETIC_EXPERIMENT_OUTPUT = REPO_ROOT / "docs/reports/twm_synthetic_experiment_foundation.csv"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs/reports/twm_data_foundation_health.md"

OBSERVED_HISTORY_FIELD_GROUPS: list[dict[str, Any]] = [
    {
        "group": "causal_unit_identity",
        "required": True,
        "aliases": ["unit_id", "causal_unit_id", "sample_id", "project_id", "XMDM", "xmdm", "project_code", "approval_id", "AJBH"],
    },
    {
        "group": "treatment_assignment",
        "required": True,
        "aliases": ["treatment", "treated", "intervention", "approval_status", "decision_result", "DKZT", "status", "task_status", "review_result", "approved_area_m2", "ZDZMJ"],
    },
    {
        "group": "observed_outcome",
        "required": True,
        "aliases": [
            "outcome",
            "planning_utility_delta",
            "utility_delta",
            "ranking_score",
            "observed_utility_delta",
            "reviewed_planning_utility_delta",
            "area_m2",
            "planned_area_m2",
            "DKMJ",
            "ZYZMJ",
            "approved_area_m2",
            "ZDZMJ",
        ],
    },
    {
        "group": "production_flags",
        "required": True,
        "aliases": ["synthetic", "not_for_production", "not_for_prod"],
    },
    {
        "group": "spatial_support",
        "required": True,
        "aliases": [
            "cluster",
            "spatial_cluster",
            "block_id",
            "township_id",
            "region_code",
            "county_code",
            "DKXZQDM",
            "XZQDM",
            "neighbors",
            "neighbor_unit_ids",
            "x",
            "y",
            "lon",
            "lat",
            "longitude",
            "latitude",
        ],
    },
    {
        "group": "adjustment_covariates",
        "required": True,
        "aliases": [
            "covariates",
            "area_m2",
            "planned_area_m2",
            "DKMJ",
            "quality_score",
            "baseline_outcome",
            "baseline_risk_score",
            "risk_score",
            "evidence_coverage",
            "rule_hit_count",
            "review_task_count",
        ],
    },
]

PRODUCTION_OBSERVED_HISTORY_MINIMUM_COLUMNS = [
    "unit_id or project_id",
    "approval_status or treatment",
    "outcome or approved_area_m2/DKMJ proxy fields",
    "synthetic",
    "not_for_production",
    "cluster/DKXZQDM/XZQDM or neighbors or x+y coordinates",
    "at least one numeric covariate such as area_m2, DKMJ, quality_score, risk_score",
]

PRODUCTION_POLICY_HISTORY_MINIMUM_COLUMNS = [
    "action_type",
    "action_mask_policy or policy_code",
    "action_mask_allowed or feasibility_label",
    "region_code/DKXZQDM/XZQDM or cluster",
    "period/time_index or approval_date",
]

TWM_EVIDENCE_MATCHING_COVARIATES = [
    "DKMJ",
    "area_m2",
    "planned_area_m2",
    "quality_score",
    "risk_score",
    "review_penalty",
    "rule_eval_count",
    "rule_hit_count",
    "critical_rule_hit_count",
    "high_rule_hit_count",
    "review_task_count",
    "open_review_count",
    "completed_review_count",
    "supplement_required_review_count",
    "confirmed_violation_count",
]

STRUCTURAL_VALIDATION_OBSERVED_HISTORY_FIELDS = [
    "unit_id",
    "approval_id",
    "project_id",
    "approval_status",
    "outcome",
    "approved_area_m2",
    "area_m2",
    "DKMJ",
    "stratum",
    "cluster",
    "spatial_cluster",
    "neighbors",
    "neighbor_unit_ids",
    "x",
    "y",
    "quality_score",
    "baseline_risk_score",
    "risk_score",
    "review_penalty",
    "rule_eval_count",
    "rule_hit_count",
    "critical_rule_hit_count",
    "high_rule_hit_count",
    "review_task_count",
    "open_review_count",
    "completed_review_count",
    "supplement_required_review_count",
    "confirmed_violation_count",
    "propensity_score",
    "evidence_weight",
    "synthetic",
    "not_for_production",
    "data_role",
    "source_path",
]

SYNTHETIC_EXPERIMENT_FOUNDATION_FIELDS = STRUCTURAL_VALIDATION_OBSERVED_HISTORY_FIELDS + [
    "region_code",
    "period",
    "time_index",
    "scenario_id",
    "split",
    "action_type",
    "counterfactual_group",
    "treatment_effect",
    "baseline_state_score",
    "next_state_score",
    "constraint_risk_delta",
    "planning_utility_delta",
    "uncertainty",
    "action_mask_allowed",
    "action_mask_required_reviews",
    "action_mask_hard_blocks",
    "action_mask_policy",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate TWM data foundation with local observed and empirical causal datasets.")
    parser.add_argument("--twm-dataset", default=str(DEFAULT_TWM_DATASET), help="TWM dataset root with tables/*.csv.")
    parser.add_argument("--paper7-causal-dataset", default=str(DEFAULT_PAPER7_CAUSAL_DATASET), help="Paper7 causal_dataset.csv path.")
    parser.add_argument("--paper7-calibration", default=str(DEFAULT_PAPER7_CALIBRATION), help="Paper7 causal_calibration.json path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON report output path.")
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT), help="Markdown health report output path.")
    parser.add_argument("--production-observed-history", default="", help="Optional non-synthetic approval/review history CSV to preflight.")
    parser.add_argument("--schema-template-output", default="", help="Optional CSV template output path for production observed histories.")
    parser.add_argument("--sample-limit", type=int, default=0, help="Optional maximum Paper7 records to read; 0 means all rows.")
    parser.add_argument("--paper7-match-caliper", type=float, default=2.0, help="Maximum standardized distance for Paper7 caliper matching.")
    parser.add_argument("--twm-evidence-match-caliper", type=float, default=0.0, help="Optional standardized-distance caliper for local TWM evidence matching; 0 disables.")
    parser.add_argument("--structural-observed-history-output", default=str(DEFAULT_STRUCTURAL_OBSERVED_HISTORY_OUTPUT), help="CSV output for a synthetic/not-for-production structural-validation observed-history fixture.")
    parser.add_argument("--structural-fixture-pairs", type=int, default=24, help="Number of treated/control pairs to generate for the structural-validation fixture.")
    parser.add_argument("--skip-structural-fixture", action="store_true", help="Skip generation and validation of the structural-validation observed-history fixture.")
    parser.add_argument("--synthetic-experiment-output", default=str(DEFAULT_SYNTHETIC_EXPERIMENT_OUTPUT), help="CSV output for the multi-region multi-period synthetic TWM experiment foundation.")
    parser.add_argument("--synthetic-experiment-regions", type=int, default=4, help="Number of synthetic regions for the experiment foundation.")
    parser.add_argument("--synthetic-experiment-periods", type=int, default=8, help="Number of temporal periods for the experiment foundation.")
    parser.add_argument("--synthetic-experiment-components", type=int, default=4, help="Number of spatial components per region and period.")
    parser.add_argument("--skip-synthetic-experiment", action="store_true", help="Skip synthetic experiment foundation generation and validation.")
    args = parser.parse_args()

    twm_dataset = Path(args.twm_dataset).expanduser()
    paper7_dataset = Path(args.paper7_causal_dataset).expanduser()
    paper7_calibration = Path(args.paper7_calibration).expanduser()
    production_observed_history = Path(args.production_observed_history).expanduser() if args.production_observed_history else None
    twm_evidence_match_caliper = max(0.0, float(args.twm_evidence_match_caliper or 0.0)) or None
    structural_observed_history = Path(args.structural_observed_history_output).expanduser() if not args.skip_structural_fixture else None
    structural_fixture_summary = (
        write_twm_structural_validation_observed_history(
            structural_observed_history,
            twm_dataset,
            pair_count=max(6, int(args.structural_fixture_pairs or 0)),
        )
        if structural_observed_history
        else {"status": "skipped", "note": "structural-validation fixture generation skipped"}
    )
    synthetic_experiment_path = Path(args.synthetic_experiment_output).expanduser() if not args.skip_synthetic_experiment else None
    synthetic_experiment_summary = (
        write_twm_synthetic_experiment_foundation(
            synthetic_experiment_path,
            twm_dataset,
            region_count=max(2, int(args.synthetic_experiment_regions or 0)),
            period_count=max(2, int(args.synthetic_experiment_periods or 0)),
            component_count=max(2, int(args.synthetic_experiment_components or 0)),
        )
        if synthetic_experiment_path
        else {"status": "skipped", "note": "synthetic experiment foundation generation skipped"}
    )

    svc = _build_validation_service()
    state_id = _create_minimal_state(svc)

    report: dict[str, Any] = {
        "schema": "territory_world_model.data_foundation_validation.v1",
        "inputs": {
            "twm_dataset": str(twm_dataset),
            "paper7_causal_dataset": str(paper7_dataset),
            "paper7_calibration": str(paper7_calibration),
            "production_observed_history": str(production_observed_history) if production_observed_history else None,
            "twm_evidence_match_caliper": twm_evidence_match_caliper,
            "structural_validation_observed_history": str(structural_observed_history) if structural_observed_history else None,
            "synthetic_experiment_foundation": str(synthetic_experiment_path) if synthetic_experiment_path else None,
        },
        "production_observed_history_contract": production_observed_history_contract(),
        "twm_dataset_audit": audit_twm_dataset(twm_dataset),
        "twm_observed_history_schema_audit": audit_observed_history_schema(twm_dataset / "tables" / "approval_records.csv"),
        "production_observed_history_schema_audit": (
            audit_observed_history_schema(production_observed_history)
            if production_observed_history
            else {
                **audit_observed_history_schema(None),
                "note": "pass --production-observed-history with a non-synthetic approval/review export to preflight production calibration data",
            }
        ),
        "twm_structural_validation_fixture": structural_fixture_summary,
        "twm_structural_validation_schema_audit": audit_observed_history_schema(structural_observed_history) if structural_observed_history else {
            "status": "skipped",
            "note": "structural-validation fixture generation skipped",
        },
        "twm_structural_validation_gate": validate_twm_structural_validation_fixture(svc, state_id, structural_observed_history),
        "twm_structural_validation_structural_check": validate_twm_structural_validation_fixture_structural_check(svc, state_id, structural_observed_history),
        "twm_synthetic_experiment_foundation": synthetic_experiment_summary,
        "twm_synthetic_experiment_schema_audit": audit_observed_history_schema(synthetic_experiment_path) if synthetic_experiment_path else {
            "status": "skipped",
            "note": "synthetic experiment foundation generation skipped",
        },
        "twm_synthetic_experiment_gate": validate_twm_synthetic_experiment_foundation(svc, state_id, synthetic_experiment_path),
        "twm_synthetic_experiment_structural_check": validate_twm_synthetic_experiment_foundation_structural_check(svc, state_id, synthetic_experiment_path),
        "twm_observed_history_gate": validate_twm_observed_history(svc, state_id, twm_dataset),
        "twm_spatial_relation_augmented_gate": validate_twm_spatial_relation_augmented_history(svc, state_id, twm_dataset),
        "twm_spatial_relation_augmented_structural_check": validate_twm_spatial_relation_augmented_structural_check(svc, state_id, twm_dataset),
        "twm_evidence_augmented_gate": validate_twm_evidence_augmented_history(svc, state_id, twm_dataset),
        "twm_evidence_augmented_structural_check": validate_twm_evidence_augmented_structural_check(svc, state_id, twm_dataset),
        "twm_evidence_augmented_matched_gate": validate_twm_evidence_augmented_matched_history(
            svc,
            state_id,
            twm_dataset,
            max_standardized_distance=twm_evidence_match_caliper,
        ),
        "twm_evidence_augmented_matched_structural_check": validate_twm_evidence_augmented_matched_structural_check(
            svc,
            state_id,
            twm_dataset,
            max_standardized_distance=twm_evidence_match_caliper,
        ),
        "paper7_causal_gate": validate_paper7_causal_dataset(
            svc,
            state_id,
            paper7_dataset,
            calibration_path=paper7_calibration,
            sample_limit=max(0, int(args.sample_limit or 0)),
        ),
        "paper7_matched_causal_gate": validate_paper7_matched_causal_dataset(
            svc,
            state_id,
            paper7_dataset,
            calibration_path=paper7_calibration,
            sample_limit=max(0, int(args.sample_limit or 0)),
        ),
        "paper7_caliper_matched_causal_gate": validate_paper7_matched_causal_dataset(
            svc,
            state_id,
            paper7_dataset,
            calibration_path=paper7_calibration,
            sample_limit=max(0, int(args.sample_limit or 0)),
            max_standardized_distance=max(0.0, float(args.paper7_match_caliper or 0.0)),
        ),
        "claim_boundary": {
            "renderer": "local TWM tables render GIS operational state as objects, relations, rules, evidence and review records",
            "simulator": "causal calibration validates action-conditioned effect scaling before upgrading simulator claims",
            "planner": "planning consumers must use reports only when evidence gates pass; review status keeps claims conservative",
            "core_innovation": "hierarchical GIS state plus action-conditioned dynamics plus evidence/causal gates, not GeoFM or planning alone",
        },
    }
    report["production_policy_history_alignment"] = production_policy_history_alignment(
        (report.get("production_observed_history_schema_audit") or {}).get("policy_history_quality") or {},
        synthetic_experiment_summary,
    )
    report["summary"] = summarize_validation(report)

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output = Path(args.markdown_output).expanduser()
    template_output = Path(args.schema_template_output).expanduser() if args.schema_template_output else output.parent / "twm_production_observed_history_template.csv"
    write_observed_history_template(template_output)
    report["outputs"] = {
        "report": str(output),
        "markdown_report": str(markdown_output),
        "production_observed_history_template": str(template_output),
        "structural_validation_observed_history": str(structural_observed_history) if structural_observed_history else None,
        "synthetic_experiment_foundation": str(synthetic_experiment_path) if synthetic_experiment_path else None,
    }
    report["summary"] = summarize_validation(report)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_data_foundation_health_markdown(markdown_output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {output}")
    print(f"wrote {markdown_output}")
    print(f"wrote {template_output}")


def audit_twm_dataset(dataset_root: Path) -> dict[str, Any]:
    tables_dir = dataset_root / "tables"
    expected = ["approval_records.csv", "review_tasks.csv", "rule_evaluation.csv", "state_snapshots.csv"]
    table_reports = {}
    for name in expected:
        path = tables_dir / name
        if not path.exists():
            table_reports[name] = {"exists": False, "row_count": 0}
            continue
        rows = read_csv(path)
        table_reports[name] = {
            "exists": True,
            "path": str(path),
            "row_count": len(rows),
            "synthetic_count": sum(1 for row in rows if truthy(row.get("synthetic"))),
            "not_for_production_count": sum(1 for row in rows if truthy(row.get("not_for_production"))),
            "field_count": len(rows[0]) if rows else 0,
            "fields": list(rows[0].keys())[:24] if rows else [],
        }
    approval_rows = read_csv(tables_dir / "approval_records.csv") if (tables_dir / "approval_records.csv").exists() else []
    relation_audit = audit_project_spatial_relations(dataset_root)
    review_context = build_project_review_context(dataset_root)
    return {
        "dataset_root": str(dataset_root),
        "tables": table_reports,
        "approval_status_counts": _counts(row.get("approval_status") or row.get("decision_result") for row in approval_rows),
        "production_ready_observed_history_rows": sum(
            1 for row in approval_rows if not truthy(row.get("synthetic")) and not truthy(row.get("not_for_production"))
        ),
        "project_spatial_relations": relation_audit,
        "project_review_context": audit_project_review_context(review_context),
    }


def production_observed_history_contract() -> dict[str, Any]:
    return {
        "schema": "territory_world_model.production_observed_history_contract.v1",
        "purpose": "preflight non-synthetic approval/review histories before TWM causal calibration",
        "minimum_columns": PRODUCTION_OBSERVED_HISTORY_MINIMUM_COLUMNS,
        "field_groups": OBSERVED_HISTORY_FIELD_GROUPS,
        "production_gate": {
            "synthetic": "must be present and false for production claim validation rows",
            "not_for_production": "must be present and false for production claim validation rows",
            "treated_control": "must include both approved/treated and not-approved/control rows",
            "spatial_support": "must include cluster ids, neighbor ids, or complete x/y coordinates",
            "covariates": "must include at least one numeric adjustment covariate; stronger validation needs several pre-treatment covariates",
        },
        "policy_history_gate": {
            "purpose": "preflight real approval/review histories for TWM action-mask and unseen region/action-policy feasibility validation",
            "minimum_columns": PRODUCTION_POLICY_HISTORY_MINIMUM_COLUMNS,
            "required_coverage": [
                "both allowed and blocked feasibility labels",
                "mixed-risk allowed policies such as allowed_with_conditions/protect_allowed/restore_allowed when available",
                "multiple region-policy and region-action-policy combinations",
            ],
            "claim_boundary": "policy-history coverage only prepares real-data feasibility validation; it does not prove simulator accuracy by itself",
        },
        "claim_boundary": "schema conformance only prepares data for evidence gates; it does not upgrade TWM claims without causal_calibration_report pass",
    }


def audit_observed_history_schema(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not_provided",
            "expected_minimum_columns": PRODUCTION_OBSERVED_HISTORY_MINIMUM_COLUMNS,
            "expected_policy_history_columns": PRODUCTION_POLICY_HISTORY_MINIMUM_COLUMNS,
            "policy_history_quality": _empty_observed_policy_history_quality("not_provided"),
        }
    if not path.exists():
        return {
            "status": "missing",
            "path": str(path),
            "expected_minimum_columns": PRODUCTION_OBSERVED_HISTORY_MINIMUM_COLUMNS,
            "expected_policy_history_columns": PRODUCTION_POLICY_HISTORY_MINIMUM_COLUMNS,
            "policy_history_quality": _empty_observed_policy_history_quality("missing"),
        }

    rows = read_csv(path)
    fields = list(rows[0].keys()) if rows else []
    field_lookup = {str(field).lower(): str(field) for field in fields}
    group_reports = []
    missing_groups = []
    for group in OBSERVED_HISTORY_FIELD_GROUPS:
        aliases = list(group["aliases"])
        matched = [field_lookup[alias.lower()] for alias in aliases if alias.lower() in field_lookup]
        item = {
            "group": group["group"],
            "required": bool(group.get("required")),
            "status": "pass" if matched else "missing",
            "matched_fields": sorted(set(matched)),
            "accepted_aliases": aliases,
        }
        group_reports.append(item)
        if group.get("required") and not matched:
            missing_groups.append(group["group"])

    row_quality = _observed_history_row_quality(rows)
    policy_history_quality = _observed_policy_history_quality(rows)
    missing_data_gates = []
    if row_quality["production_candidate_row_count"] <= 0:
        missing_data_gates.append("production_usable_rows")
    if row_quality["production_treated_count"] <= 0:
        missing_data_gates.append("production_treated_rows")
    if row_quality["production_control_count"] <= 0:
        missing_data_gates.append("production_control_rows")
    if row_quality["rows_with_outcome"] <= 0:
        missing_data_gates.append("observed_outcome")
    if row_quality["rows_with_spatial_support"] <= 0:
        missing_data_gates.append("spatial_support")
    if row_quality["rows_with_covariates"] <= 0:
        missing_data_gates.append("adjustment_covariates")
    if row_quality["explicit_production_flag_row_count"] < row_quality["row_count"]:
        missing_data_gates.append("explicit_production_flags")

    status = "pass" if not missing_groups and not missing_data_gates else "review"
    return {
        "schema": "territory_world_model.observed_history_schema_audit.v1",
        "status": status,
        "path": str(path),
        "row_count": len(rows),
        "field_count": len(fields),
        "fields": fields,
        "field_groups": group_reports,
        "missing_required_groups": missing_groups,
        "row_quality": row_quality,
        "policy_history_quality": policy_history_quality,
        "missing_data_gates": missing_data_gates,
        "expected_minimum_columns": PRODUCTION_OBSERVED_HISTORY_MINIMUM_COLUMNS,
        "expected_policy_history_columns": PRODUCTION_POLICY_HISTORY_MINIMUM_COLUMNS,
        "recommendations": _observed_history_schema_recommendations(missing_groups, missing_data_gates),
    }


def write_observed_history_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "unit_id",
        "approval_id",
        "project_id",
        "approval_status",
        "outcome",
        "approved_area_m2",
        "area_m2",
        "stratum",
        "cluster",
        "neighbors",
        "x",
        "y",
        "quality_score",
        "baseline_risk_score",
        "risk_score",
        "rule_hit_count",
        "review_task_count",
        "action_type",
        "action_mask_policy",
        "action_mask_allowed",
        "action_mask_required_reviews",
        "action_mask_hard_blocks",
        "region_code",
        "period",
        "time_index",
        "propensity_score",
        "evidence_weight",
        "synthetic",
        "not_for_production",
        "source_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()


def write_twm_structural_validation_observed_history(path: Path, dataset_root: Path, *, pair_count: int = 24) -> dict[str, Any]:
    """Write a synthetic/not-for-production fixture for TWM structural validation.

    The fixture is intentionally not production evidence. It provides balanced
    treated/control pairs, spatial neighbor links and review/rule covariates so
    simulator calibration plumbing can be exercised after the real local dataset
    exposes balance and spatial-support bottlenecks.
    """

    source_rows = observed_history_rows_with_project_evidence(dataset_root)
    if not source_rows:
        source_rows = []
    area_values = [
        safe_float(_row_attr(row, "area_m2", "planned_area_m2", "DKMJ", "ZYZMJ"), None)
        for row in source_rows
    ]
    area_values = [float(value) for value in area_values if value is not None and float(value) > 0]
    if not area_values:
        area_values = [10000.0, 16000.0, 24000.0, 36000.0, 52000.0, 76000.0]
    risk_values = [safe_float(row.get("risk_score"), None) for row in source_rows]
    risk_values = [float(value) for value in risk_values if value is not None]
    if not risk_values:
        risk_values = [0.08, 0.18, 0.28, 0.38]

    pair_count = max(6, int(pair_count or 0))
    rows: list[dict[str, Any]] = []
    for idx in range(pair_count):
        area = round(area_values[idx % len(area_values)], 3)
        risk = round(max(0.02, min(0.45, risk_values[idx % len(risk_values)] * 0.35 + 0.02 * (idx % 3))), 6)
        review_penalty = round(0.05 + 0.02 * (idx % 4), 6)
        rule_eval_count = 4
        rule_hit_count = 1 if idx % 3 == 0 else 0
        high_rule_hit_count = 1 if idx % 6 == 0 else 0
        quality_score = round(0.72 + 0.01 * (idx % 5), 6)
        cluster = f"structural_component_{idx:03d}"
        stratum = f"structural_admin_{idx % 4}"
        base_x = 106.2 + (idx % 6) * 0.012
        base_y = 29.58 + (idx // 6) * 0.012
        control_id = f"TWM-SV-C-{idx:03d}"
        treated_id = f"TWM-SV-T-{idx:03d}"
        pair_outcome_base = 0.18 + 0.01 * (idx % 4)
        control_outcome = round(pair_outcome_base - 0.03 * risk, 6)
        treated_outcome = round(control_outcome + 0.05, 6)
        shared = {
            "area_m2": area,
            "DKMJ": area,
            "stratum": stratum,
            "cluster": cluster,
            "spatial_cluster": cluster,
            "quality_score": quality_score,
            "baseline_risk_score": risk,
            "risk_score": risk,
            "review_penalty": review_penalty,
            "rule_eval_count": rule_eval_count,
            "rule_hit_count": rule_hit_count,
            "critical_rule_hit_count": 0,
            "high_rule_hit_count": high_rule_hit_count,
            "review_task_count": 1,
            "open_review_count": 0,
            "completed_review_count": 1,
            "supplement_required_review_count": 0,
            "confirmed_violation_count": 0,
            "propensity_score": 0.5,
            "evidence_weight": 0.95,
            "synthetic": True,
            "not_for_production": True,
            "data_role": "synthetic_structural_validation",
            "source_path": str(dataset_root),
        }
        rows.append(
            {
                **shared,
                "unit_id": control_id,
                "approval_id": f"APR-{control_id}",
                "project_id": f"PRJ-{control_id}",
                "approval_status": "in_review",
                "outcome": control_outcome,
                "approved_area_m2": 0.0,
                "neighbors": treated_id,
                "neighbor_unit_ids": treated_id,
                "x": round(base_x, 6),
                "y": round(base_y, 6),
            }
        )
        rows.append(
            {
                **shared,
                "unit_id": treated_id,
                "approval_id": f"APR-{treated_id}",
                "project_id": f"PRJ-{treated_id}",
                "approval_status": "approved",
                "outcome": treated_outcome,
                "approved_area_m2": area,
                "neighbors": control_id,
                "neighbor_unit_ids": control_id,
                "x": round(base_x + 0.001, 6),
                "y": round(base_y + 0.001, 6),
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=STRUCTURAL_VALIDATION_OBSERVED_HISTORY_FIELDS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return structural_validation_fixture_summary(path, rows, source_rows)


def structural_validation_fixture_summary(path: Path, rows: list[dict[str, Any]], source_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    quality = _observed_history_row_quality(rows)
    clusters = sorted({str(row.get("cluster") or "") for row in rows if row.get("cluster")})
    return {
        "schema": "territory_world_model.structural_validation_fixture.v1",
        "status": "generated",
        "path": str(path),
        "row_count": len(rows),
        "pair_count": len(rows) // 2,
        "source_context_row_count": len(source_rows or []),
        "treated_count": quality["treated_count"],
        "control_count": quality["control_count"],
        "rows_with_neighbors": quality["rows_with_neighbors"],
        "rows_with_covariates": quality["rows_with_covariates"],
        "spatial_cluster_count": len(clusters),
        "synthetic_count": quality["synthetic_count"],
        "not_for_production_count": quality["not_for_production_count"],
        "data_role": "synthetic_structural_validation",
        "claim_boundary": "generated from local TWM context for simulator structural validation only; not production ground truth",
    }


def write_twm_synthetic_experiment_foundation(
    path: Path,
    dataset_root: Path,
    *,
    region_count: int = 4,
    period_count: int = 6,
    component_count: int = 4,
) -> dict[str, Any]:
    """Write a richer synthetic foundation for TWM simulator experiments.

    Unlike the small structural fixture, this dataset contains regions, periods,
    scenarios, splits and action/effect labels so downstream simulator training,
    holdout and planner-consumer experiments have stable local data.
    """

    source_rows = observed_history_rows_with_project_evidence(dataset_root)
    area_values = [
        safe_float(_row_attr(row, "area_m2", "planned_area_m2", "DKMJ", "ZYZMJ"), None)
        for row in source_rows
    ]
    area_values = [float(value) for value in area_values if value is not None and float(value) > 0]
    if not area_values:
        area_values = [12000.0, 18000.0, 26000.0, 42000.0, 68000.0]

    rows: list[dict[str, Any]] = []
    for region_idx in range(region_count):
        region_code = f"SYN-R{region_idx:02d}"
        for period_idx in range(period_count):
            period = f"2026Q{(period_idx % 4) + 1}+{period_idx // 4}"
            split = synthetic_experiment_split_for_period(period_idx, period_count)
            for component_idx in range(component_count):
                pair_index = len(rows) // 2
                cluster = f"syn_component_r{region_idx:02d}_t{period_idx:02d}_c{component_idx:02d}"
                stratum = f"{region_code}:township_{component_idx % 3}"
                action_types = ["protect", "restore", "approve_with_conditions", "defer_review"]
                oracle_action_cycle = ["protect", "restore", "approve_with_conditions"]
                preferred_action = oracle_action_cycle[(region_idx + period_idx) % len(oracle_action_cycle)]
                scenario_id = f"scenario_{preferred_action}_{period_idx % 3}"
                base_area = area_values[(region_idx * period_count * component_count + period_idx * component_count + component_idx) % len(area_values)]
                area = round(base_area * (0.85 + 0.04 * region_idx + 0.02 * component_idx), 3)
                baseline_risk = round(min(0.72, 0.16 + 0.032 * region_idx + 0.014 * period_idx + 0.006 * ((component_idx + region_idx) % 2)), 6)
                review_penalty = round(0.04 + 0.02 * ((component_idx + period_idx) % 4), 6)
                quality_score = round(max(0.35, 0.82 - 0.025 * region_idx - 0.015 * component_idx + 0.005 * period_idx), 6)
                rule_hit_count = 1 if baseline_risk >= 0.22 else 0
                high_rule_hit_count = 1 if baseline_risk >= 0.34 else 0
                confirmed_violation_count = 1 if baseline_risk >= 0.6 and component_idx % 2 == 0 else 0
                action_type = action_types[component_idx % len(action_types)]
                action_profile = synthetic_experiment_action_profile(
                    action_type=action_type,
                    preferred_action=preferred_action,
                    baseline_risk=baseline_risk,
                    review_penalty=review_penalty,
                    region_idx=region_idx,
                    period_idx=period_idx,
                )
                candidate_coverage_floor = synthetic_experiment_candidate_coverage_constraint_floor(
                    action_type=action_type,
                    split=split,
                    region_idx=region_idx,
                    period_idx=period_idx,
                    period_count=period_count,
                    component_idx=component_idx,
                )
                if candidate_coverage_floor is not None:
                    constraint_probability = baseline_risk + action_profile["constraint_risk_delta"]
                    if constraint_probability < candidate_coverage_floor:
                        baseline_risk = round(min(0.46, baseline_risk + candidate_coverage_floor - constraint_probability), 6)
                        rule_hit_count = 1 if baseline_risk >= 0.22 else 0
                        high_rule_hit_count = 1 if baseline_risk >= 0.34 else 0
                        confirmed_violation_count = 1 if baseline_risk >= 0.6 and component_idx % 2 == 0 else 0
                        action_profile = synthetic_experiment_action_profile(
                            action_type=action_type,
                            preferred_action=preferred_action,
                            baseline_risk=baseline_risk,
                            review_penalty=review_penalty,
                            region_idx=region_idx,
                            period_idx=period_idx,
                        )
                treatment_effect = action_profile["treatment_effect"]
                baseline_state_score = round(0.45 + 0.08 * quality_score - 0.22 * baseline_risk, 6)
                control_next_state = round(baseline_state_score - 0.012 * baseline_risk + 0.004 * (period_idx % 3), 6)
                treated_next_state = round(control_next_state + treatment_effect, 6)
                constraint_risk_delta = action_profile["constraint_risk_delta"]
                planning_utility_delta = action_profile["planning_utility_delta"]
                uncertainty = action_profile["uncertainty"]
                action_mask = synthetic_experiment_action_mask_label(
                    action_type=action_type,
                    constraint_probability=baseline_risk + constraint_risk_delta,
                    region_idx=region_idx,
                    period_idx=period_idx,
                    component_idx=component_idx,
                )
                base_x = 106.0 + region_idx * 0.18 + component_idx * 0.012
                base_y = 29.3 + period_idx * 0.018 + component_idx * 0.004
                control_id = f"TWM-SYN-C-{pair_index:04d}"
                treated_id = f"TWM-SYN-T-{pair_index:04d}"
                shared = {
                    "area_m2": area,
                    "DKMJ": area,
                    "stratum": stratum,
                    "cluster": cluster,
                    "spatial_cluster": cluster,
                    "quality_score": quality_score,
                    "baseline_risk_score": baseline_risk,
                    "risk_score": baseline_risk,
                    "review_penalty": review_penalty,
                    "rule_eval_count": 4,
                    "rule_hit_count": rule_hit_count,
                    "critical_rule_hit_count": confirmed_violation_count,
                    "high_rule_hit_count": high_rule_hit_count,
                    "review_task_count": 1 + rule_hit_count,
                    "open_review_count": 0 if split != "test" else rule_hit_count,
                    "completed_review_count": 1,
                    "supplement_required_review_count": 1 if review_penalty >= 0.08 else 0,
                    "confirmed_violation_count": confirmed_violation_count,
                    "propensity_score": 0.5,
                    "evidence_weight": round(0.9 - min(0.15, uncertainty), 6),
                    "synthetic": True,
                    "not_for_production": True,
                    "data_role": "synthetic_experiment_foundation",
                    "source_path": str(dataset_root),
                    "region_code": region_code,
                    "period": period,
                    "time_index": period_idx,
                    "scenario_id": scenario_id,
                    "split": split,
                    "action_type": action_type,
                    "counterfactual_group": f"pair_{pair_index:04d}",
                    "treatment_effect": treatment_effect,
                    "baseline_state_score": baseline_state_score,
                    "constraint_risk_delta": constraint_risk_delta,
                    "planning_utility_delta": planning_utility_delta,
                    "uncertainty": uncertainty,
                    "action_mask_allowed": action_mask["allowed"],
                    "action_mask_required_reviews": "|".join(action_mask["required_reviews"]),
                    "action_mask_hard_blocks": "|".join(action_mask["hard_blocks"]),
                    "action_mask_policy": action_mask["policy"],
                }
                rows.append(
                    {
                        **shared,
                        "unit_id": control_id,
                        "approval_id": f"APR-{control_id}",
                        "project_id": f"PRJ-{control_id}",
                        "approval_status": "in_review",
                        "outcome": control_next_state,
                        "approved_area_m2": 0.0,
                        "neighbors": treated_id,
                        "neighbor_unit_ids": treated_id,
                        "x": round(base_x, 6),
                        "y": round(base_y, 6),
                        "next_state_score": control_next_state,
                    }
                )
                rows.append(
                    {
                        **shared,
                        "unit_id": treated_id,
                        "approval_id": f"APR-{treated_id}",
                        "project_id": f"PRJ-{treated_id}",
                        "approval_status": "approved",
                        "outcome": treated_next_state,
                        "approved_area_m2": area,
                        "neighbors": control_id,
                        "neighbor_unit_ids": control_id,
                        "x": round(base_x + 0.001, 6),
                        "y": round(base_y + 0.001, 6),
                        "next_state_score": treated_next_state,
                    }
                )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=SYNTHETIC_EXPERIMENT_FOUNDATION_FIELDS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return synthetic_experiment_foundation_summary(path, rows, source_rows)


def synthetic_experiment_holdout_period_count(period_count: int) -> int:
    if period_count <= 1:
        return 0
    if period_count <= 3:
        return 1
    return max(2, min(4, period_count // 2 if period_count >= 6 else 2))


def synthetic_experiment_split_for_period(period_idx: int, period_count: int) -> str:
    holdout_period_count = synthetic_experiment_holdout_period_count(period_count)
    holdout_start = max(1, period_count - holdout_period_count)
    if period_idx < holdout_start:
        return "train"
    holdout_offset = period_idx - holdout_start
    validation_cutoff = max(1, holdout_period_count // 2)
    return "validation" if holdout_offset < validation_cutoff else "test"


def synthetic_experiment_foundation_summary(path: Path, rows: list[dict[str, Any]], source_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    quality = _observed_history_row_quality(rows)
    splits = _counts(row.get("split") for row in rows)
    regions = sorted({str(row.get("region_code") or "") for row in rows if row.get("region_code")})
    periods = sorted({str(row.get("period") or "") for row in rows if row.get("period")})
    holdout_periods = sorted({str(row.get("period") or "") for row in rows if row.get("period") and str(row.get("split") or "") != "train"})
    scenarios = sorted({str(row.get("scenario_id") or "") for row in rows if row.get("scenario_id")})
    oracle = synthetic_experiment_oracle_summary(rows)
    action_mask = synthetic_experiment_action_mask_summary(rows)
    policy_coverage = synthetic_experiment_policy_coverage_benchmark(rows)
    return {
        "schema": "territory_world_model.synthetic_experiment_foundation.v1",
        "status": "generated",
        "path": str(path),
        "row_count": len(rows),
        "pair_count": len(rows) // 2,
        "source_context_row_count": len(source_rows or []),
        "treated_count": quality["treated_count"],
        "control_count": quality["control_count"],
        "region_count": len(regions),
        "period_count": len(periods),
        "holdout_period_count": len(holdout_periods),
        "scenario_count": len(scenarios),
        "split_counts": splits,
        "oracle_action_counts": oracle["oracle_action_counts"],
        "holdout_oracle_action_counts": oracle["holdout_oracle_action_counts"],
        "holdout_oracle_group_count": oracle["holdout_oracle_group_count"],
        "holdout_oracle_action_type_count": oracle["holdout_oracle_action_type_count"],
        "action_mask_allowed_count": action_mask["allowed_count"],
        "action_mask_blocked_count": action_mask["blocked_count"],
        "mixed_action_mask_action_types": action_mask["mixed_action_types"],
        "action_mask_counts_by_action_type": action_mask["by_action_type"],
        "action_mask_policy_counts_by_split": action_mask["policy_counts_by_split"],
        "candidate_action_mask_policy_counts": action_mask["candidate_policy_counts"],
        "holdout_action_mask_policy_counts": action_mask["holdout_policy_counts"],
        "candidate_mixed_allowed_policy_counts": action_mask["candidate_mixed_allowed_policy_counts"],
        "holdout_mixed_allowed_policy_counts": action_mask["holdout_mixed_allowed_policy_counts"],
        "policy_coverage_benchmark": policy_coverage,
        "rows_with_neighbors": quality["rows_with_neighbors"],
        "rows_with_covariates": quality["rows_with_covariates"],
        "synthetic_count": quality["synthetic_count"],
        "not_for_production_count": quality["not_for_production_count"],
        "data_role": "synthetic_experiment_foundation",
        "claim_boundary": "synthetic multi-region, multi-period experiment data for TWM development; not production ground truth",
    }


def synthetic_experiment_candidate_coverage_constraint_floor(
    *,
    action_type: str,
    split: str,
    region_idx: int,
    period_idx: int,
    period_count: int,
    component_idx: int,
) -> float | None:
    """Seed train split with mixed-risk allowed policy contexts.

    The synthetic foundation is a structural regression fixture. The candidate
    split must include mitigated-but-allowed policy contexts so learned
    feasibility heads are not forced to extrapolate every allowed mixed-risk
    decision from holdout-only labels.
    """

    if split != "train" or action_type not in {"approve_with_conditions", "protect", "restore"}:
        return None
    if synthetic_experiment_holdout_unseen_allowed_region_policy_candidate_gap(
        action_type=action_type,
        region_idx=region_idx,
        period_idx=period_idx,
        period_count=period_count,
    ):
        return None
    holdout_period_count = synthetic_experiment_holdout_period_count(period_count)
    holdout_start = max(1, period_count - holdout_period_count)
    candidate_tail_start = max(0, holdout_start - 2)
    if period_idx < candidate_tail_start:
        return None
    if synthetic_experiment_action_mask_phase_requires_review(
        action_type=action_type,
        region_idx=region_idx,
        period_idx=period_idx,
        component_idx=component_idx,
    ):
        return None
    return 0.31


def synthetic_experiment_holdout_unseen_allowed_region_policy_candidate_gap(
    *,
    action_type: str,
    region_idx: int,
    period_idx: int,
    period_count: int,
) -> bool:
    """Reserve allowed region/policy combinations for holdout-only stress.

    The candidate split still contains every mixed-risk allowed policy family in
    other regions. These gaps create explicit unseen allowed region-policy
    diagnostics across multiple action families without feeding target-derived
    labels to the simulator.
    """

    if action_type not in {"approve_with_conditions", "protect", "restore"}:
        return False
    holdout_period_count = synthetic_experiment_holdout_period_count(period_count)
    holdout_start = max(1, period_count - holdout_period_count)
    if region_idx < 3 or period_idx >= holdout_start:
        return False
    return True


def synthetic_experiment_action_mask_label(
    *,
    action_type: str,
    constraint_probability: float,
    region_idx: int,
    period_idx: int,
    component_idx: int,
) -> dict[str, Any]:
    risk = float(constraint_probability)
    required_reviews: list[str] = []
    hard_blocks: list[str] = []
    allowed = risk < 0.5 and action_type != "defer_review"
    policy = "constraint_threshold"
    if action_type == "defer_review":
        allowed = False
        required_reviews.append("synthetic_defer_review")
        policy = "defer_review_always_review"
    elif action_type == "approve_with_conditions":
        if risk >= 0.18 and synthetic_experiment_action_mask_phase_requires_review(
            action_type=action_type,
            region_idx=region_idx,
            period_idx=period_idx,
            component_idx=component_idx,
        ):
            allowed = False
            required_reviews.append("mixed_risk_condition_review")
            policy = "mixed_risk_blocked_condition_review"
        else:
            required_reviews.append("conditional_approval_monitoring") if risk >= 0.28 else None
            policy = "mixed_risk_allowed_with_conditions" if risk >= 0.28 else "low_risk_allowed"
    elif action_type == "restore":
        if risk >= 0.18 and synthetic_experiment_action_mask_phase_requires_review(
            action_type=action_type,
            region_idx=region_idx,
            period_idx=period_idx,
            component_idx=component_idx,
        ):
            allowed = False
            required_reviews.append("restoration_high_risk_phasing_review")
            policy = "mixed_risk_restore_blocked"
        else:
            policy = "mixed_risk_restore_allowed" if risk >= 0.28 else "low_risk_allowed"
    elif action_type == "protect":
        if risk >= 0.18 and synthetic_experiment_action_mask_phase_requires_review(
            action_type=action_type,
            region_idx=region_idx,
            period_idx=period_idx,
            component_idx=component_idx,
        ):
            allowed = False
            required_reviews.append("protection_boundary_conflict_review")
            policy = "mixed_risk_protect_blocked"
        else:
            policy = "mixed_risk_protect_allowed" if risk >= 0.28 else "low_risk_allowed"
    if risk >= 0.38 and not allowed:
        hard_blocks.append("mixed_high_constraint_risk")
    return {
        "allowed": allowed,
        "required_reviews": required_reviews,
        "hard_blocks": hard_blocks,
        "policy": policy,
    }


def synthetic_experiment_action_mask_phase_requires_review(
    *,
    action_type: str,
    region_idx: int,
    period_idx: int,
    component_idx: int,
) -> bool:
    if action_type == "defer_review":
        return True
    if action_type == "approve_with_conditions":
        return (region_idx + period_idx) % 2 == 0
    if action_type == "restore":
        return (period_idx + region_idx) % 3 == 0
    if action_type == "protect":
        return (region_idx + period_idx + component_idx) % 3 == 1
    return False


def synthetic_experiment_action_mask_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_action: dict[str, dict[str, int]] = {}
    policy_counts_by_split: dict[str, Counter] = {}
    candidate_policy_counts: Counter = Counter()
    holdout_policy_counts: Counter = Counter()
    allowed_count = 0
    blocked_count = 0
    for row in rows:
        if str(row.get("approval_status") or "").lower() != "approved":
            continue
        action_type = str(row.get("action_type") or "")
        split = str(row.get("split") or "unknown")
        policy = str(row.get("action_mask_policy") or "unspecified")
        allowed = truthy(row.get("action_mask_allowed"))
        bucket = by_action.setdefault(action_type, {"allowed": 0, "blocked": 0, "total": 0})
        bucket["total"] += 1
        policy_counts_by_split.setdefault(split, Counter())[policy] += 1
        if split == "train":
            candidate_policy_counts[policy] += 1
        else:
            holdout_policy_counts[policy] += 1
        if allowed:
            bucket["allowed"] += 1
            allowed_count += 1
        else:
            bucket["blocked"] += 1
            blocked_count += 1
    mixed = sorted(action for action, counts in by_action.items() if counts["allowed"] and counts["blocked"])
    return {
        "allowed_count": allowed_count,
        "blocked_count": blocked_count,
        "mixed_action_types": mixed,
        "by_action_type": dict(sorted(by_action.items())),
        "policy_counts_by_split": {
            split: dict(sorted(counts.items()))
            for split, counts in sorted(policy_counts_by_split.items())
        },
        "candidate_policy_counts": dict(sorted(candidate_policy_counts.items())),
        "holdout_policy_counts": dict(sorted(holdout_policy_counts.items())),
        "candidate_mixed_allowed_policy_counts": {
            policy: count
            for policy, count in sorted(candidate_policy_counts.items())
            if "mixed_risk" in policy and "allowed" in policy
        },
        "holdout_mixed_allowed_policy_counts": {
            policy: count
            for policy, count in sorted(holdout_policy_counts.items())
            if "mixed_risk" in policy and "allowed" in policy
        },
    }


def synthetic_experiment_policy_coverage_benchmark(rows: list[dict[str, Any]]) -> dict[str, Any]:
    modes = {
        mode: synthetic_experiment_unseen_policy_mode_summary(rows, mode)
        for mode in ("region_policy", "region_action_policy")
    }
    required_mixed_allowed_policies = sorted(
        {
            policy
            for summary in modes.values()
            for policy in (summary.get("allowed_policy_counts") or {})
            if _observed_policy_is_mixed_allowed(str(policy))
        }
    )
    return {
        "schema": "territory_world_model.synthetic_policy_coverage_benchmark.v1",
        "status": "generated" if any((item.get("example_count") or 0) > 0 for item in modes.values()) else "review",
        "source": "synthetic_experiment_unseen_mixed_risk_policy_fixture",
        "modes": modes,
        "required_allowed_count": max((int(item.get("allowed_count") or 0) for item in modes.values()), default=0),
        "required_blocked_count": max((int(item.get("blocked_count") or 0) for item in modes.values()), default=0),
        "required_region_policy_key_count": int((modes.get("region_policy") or {}).get("unseen_key_count") or 0),
        "required_region_action_policy_key_count": int((modes.get("region_action_policy") or {}).get("unseen_key_count") or 0),
        "required_mixed_allowed_policies": required_mixed_allowed_policies,
        "claim_boundary": "synthetic coverage benchmark only defines real-data feasibility coverage targets; it is not production accuracy evidence",
    }


def synthetic_experiment_unseen_policy_mode_summary(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    approved_rows = [
        row
        for row in rows
        if str(row.get("approval_status") or "").strip().lower() == "approved"
        and _synthetic_experiment_mixed_risk_non_defer_row(row)
    ]
    candidate_keys = {
        _synthetic_experiment_policy_key(row, mode)
        for row in approved_rows
        if _synthetic_experiment_policy_split(row) == "candidate"
    }
    selected = [
        row
        for row in approved_rows
        if _synthetic_experiment_policy_split(row) == "holdout"
        and _synthetic_experiment_policy_key(row, mode) not in candidate_keys
    ]
    action_counts: Counter = Counter()
    policy_counts: Counter = Counter()
    allowed_policy_counts: Counter = Counter()
    blocked_policy_counts: Counter = Counter()
    key_counts: Counter = Counter()
    allowed_count = 0
    blocked_count = 0
    for row in selected:
        action_type = str(row.get("action_type") or "unknown_action")
        policy = str(row.get("action_mask_policy") or "unspecified")
        allowed = truthy(row.get("action_mask_allowed"))
        action_counts[action_type] += 1
        policy_counts[policy] += 1
        key_counts[_synthetic_experiment_policy_key(row, mode)] += 1
        if allowed:
            allowed_count += 1
            allowed_policy_counts[policy] += 1
        else:
            blocked_count += 1
            blocked_policy_counts[policy] += 1
    return {
        "schema": "territory_world_model.synthetic_unseen_policy_mode_benchmark.v1",
        "mode": mode,
        "example_count": len(selected),
        "allowed_count": allowed_count,
        "blocked_count": blocked_count,
        "action_counts": dict(sorted(action_counts.items())),
        "policy_counts": dict(sorted(policy_counts.items())),
        "allowed_policy_counts": dict(sorted(allowed_policy_counts.items())),
        "blocked_policy_counts": dict(sorted(blocked_policy_counts.items())),
        "unseen_key_count": len(key_counts),
        "unseen_key_counts": {"|".join(key): count for key, count in sorted(key_counts.items())},
        "subset_rule": f"holdout mixed-risk approved rows with unseen candidate-split {mode} key",
    }


def _synthetic_experiment_policy_split(row: dict[str, Any]) -> str:
    return "candidate" if str(row.get("split") or "").strip().lower() == "train" else "holdout"


def _synthetic_experiment_mixed_risk_non_defer_row(row: dict[str, Any]) -> bool:
    action_type = str(row.get("action_type") or "").strip()
    if action_type not in {"approve_with_conditions", "protect", "restore"}:
        return False
    return "mixed_risk" in str(row.get("action_mask_policy") or "")


def _synthetic_experiment_policy_key(row: dict[str, Any], mode: str) -> tuple[str, ...]:
    region = str(row.get("region_code") or "unknown_region")
    action_type = str(row.get("action_type") or "unknown_action")
    policy = str(row.get("action_mask_policy") or "unspecified")
    if mode == "region_policy":
        return (region, policy)
    if mode == "region_action_policy":
        return (region, action_type, policy)
    return (mode, region, action_type, policy)


def synthetic_experiment_action_profile(
    *,
    action_type: str,
    preferred_action: str,
    baseline_risk: float,
    review_penalty: float,
    region_idx: int,
    period_idx: int,
) -> dict[str, float]:
    base_profiles = {
        "protect": {
            "treatment_effect": 0.034,
            "constraint_risk_delta": -0.032,
            "planning_utility_delta": 0.032,
            "uncertainty": 0.085,
        },
        "restore": {
            "treatment_effect": 0.042,
            "constraint_risk_delta": -0.026,
            "planning_utility_delta": 0.038,
            "uncertainty": 0.09,
        },
        "approve_with_conditions": {
            "treatment_effect": 0.039,
            "constraint_risk_delta": -0.018,
            "planning_utility_delta": 0.042,
            "uncertainty": 0.095,
        },
        "defer_review": {
            "treatment_effect": 0.012,
            "constraint_risk_delta": 0.018,
            "planning_utility_delta": -0.012,
            "uncertainty": 0.15,
        },
    }
    profile = dict(base_profiles.get(action_type, base_profiles["protect"]))
    region_penalty = 0.003 * min(3, region_idx)
    period_bonus = 0.002 * (period_idx % 2)
    if action_type == preferred_action:
        profile["treatment_effect"] += 0.024
        profile["constraint_risk_delta"] -= 0.03
        profile["planning_utility_delta"] += 0.058
        profile["uncertainty"] -= 0.015
    elif action_type != "defer_review":
        profile["constraint_risk_delta"] += 0.006
        profile["planning_utility_delta"] -= 0.008
        profile["uncertainty"] += 0.006
    profile["treatment_effect"] = round(max(0.001, profile["treatment_effect"] - region_penalty + period_bonus), 6)
    profile["constraint_risk_delta"] = round(profile["constraint_risk_delta"] + 0.002 * region_idx, 6)
    profile["planning_utility_delta"] = round(
        profile["planning_utility_delta"] - 0.012 * baseline_risk - 0.006 * review_penalty - region_penalty + period_bonus,
        6,
    )
    profile["uncertainty"] = round(min(0.35, max(0.04, profile["uncertainty"] + 0.004 * region_idx + 0.003 * (period_idx % 3))), 6)
    return profile


def synthetic_experiment_oracle_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    approved_rows = [row for row in rows if str(row.get("approval_status") or "").lower() == "approved"]
    all_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    holdout_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in approved_rows:
        key = (str(row.get("region_code") or ""), str(row.get("period") or ""))
        all_groups.setdefault(key, []).append(row)
        if str(row.get("split") or "") != "train":
            holdout_groups.setdefault(key, []).append(row)
    all_counts = Counter(synthetic_experiment_oracle_row(group).get("action_type") for group in all_groups.values() if group)
    holdout_counts = Counter(synthetic_experiment_oracle_row(group).get("action_type") for group in holdout_groups.values() if group)
    return {
        "oracle_action_counts": dict(sorted(all_counts.items())),
        "holdout_oracle_action_counts": dict(sorted(holdout_counts.items())),
        "holdout_oracle_group_count": len(holdout_groups),
        "holdout_oracle_action_type_count": len([key for key, value in holdout_counts.items() if value]),
    }


def synthetic_experiment_oracle_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=synthetic_experiment_oracle_score)


def synthetic_experiment_oracle_score(row: dict[str, Any]) -> float:
    risk = float(safe_float(row.get("baseline_risk_score"), 0.0) or 0.0) + float(safe_float(row.get("constraint_risk_delta"), 0.0) or 0.0)
    utility = float(safe_float(row.get("planning_utility_delta"), 0.0) or 0.0)
    confidence = 1.0 - float(safe_float(row.get("uncertainty"), 1.0) or 1.0)
    score = utility - risk + 0.1 * confidence
    if str(row.get("action_type") or "") == "defer_review" or risk >= 0.5:
        score -= 1.0
    return round(score, 6)


def _observed_history_row_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_count = len(rows)
    explicit_flag_rows = 0
    production_candidates = 0
    treated_count = 0
    control_count = 0
    production_treated_count = 0
    production_control_count = 0
    rows_with_outcome = 0
    rows_with_spatial = 0
    rows_with_covariates = 0
    rows_with_neighbors = 0
    rows_with_coordinates = 0
    rows_with_cluster = 0
    synthetic_count = 0
    nfp_count = 0
    for row in rows:
        synthetic_present = _row_has_any(row, "synthetic")
        nfp_present = _row_has_any(row, "not_for_production", "not_for_prod")
        if synthetic_present and nfp_present:
            explicit_flag_rows += 1
        is_synthetic = truthy(_row_attr(row, "synthetic"))
        is_nfp = truthy(_row_attr(row, "not_for_production", "not_for_prod"))
        if is_synthetic:
            synthetic_count += 1
        if is_nfp:
            nfp_count += 1
        treatment = _observed_history_treatment(row)
        has_outcome = _observed_history_has_outcome(row)
        has_covariates = _observed_history_has_covariates(row)
        spatial_support = _observed_history_spatial_support(row)
        if treatment == 1:
            treated_count += 1
        if treatment == 0:
            control_count += 1
        if has_outcome:
            rows_with_outcome += 1
        if has_covariates:
            rows_with_covariates += 1
        if spatial_support["has_any"]:
            rows_with_spatial += 1
        if spatial_support["has_cluster"]:
            rows_with_cluster += 1
        if spatial_support["has_neighbors"]:
            rows_with_neighbors += 1
        if spatial_support["has_coordinates"]:
            rows_with_coordinates += 1
        production_ready = bool(
            synthetic_present
            and nfp_present
            and not is_synthetic
            and not is_nfp
            and treatment is not None
            and has_outcome
            and has_covariates
            and spatial_support["has_any"]
        )
        if production_ready:
            production_candidates += 1
            if treatment == 1:
                production_treated_count += 1
            if treatment == 0:
                production_control_count += 1
    return {
        "row_count": row_count,
        "treated_count": treated_count,
        "control_count": control_count,
        "rows_with_outcome": rows_with_outcome,
        "rows_with_covariates": rows_with_covariates,
        "rows_with_spatial_support": rows_with_spatial,
        "rows_with_cluster": rows_with_cluster,
        "rows_with_neighbors": rows_with_neighbors,
        "rows_with_complete_coordinates": rows_with_coordinates,
        "synthetic_count": synthetic_count,
        "not_for_production_count": nfp_count,
        "explicit_production_flag_row_count": explicit_flag_rows,
        "production_candidate_row_count": production_candidates,
        "production_treated_count": production_treated_count,
        "production_control_count": production_control_count,
    }


def _observed_policy_history_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    production_rows = [
        row
        for row in rows
        if _observed_policy_history_production_ready(row)
    ]
    action_counts: Counter = Counter()
    policy_counts: Counter = Counter()
    allowed_policy_counts: Counter = Counter()
    blocked_policy_counts: Counter = Counter()
    region_counts: Counter = Counter()
    region_policy_counts: Counter = Counter()
    region_action_policy_counts: Counter = Counter()
    time_policy_counts: Counter = Counter()
    allowed_count = 0
    blocked_count = 0
    rows_with_policy = 0
    rows_with_action_type = 0
    rows_with_region = 0
    rows_with_time = 0
    for row in production_rows:
        action_type = _observed_policy_action_type(row)
        policy = _observed_policy_label(row)
        allowed = _observed_policy_allowed(row)
        region = _observed_policy_region(row)
        time_key = _observed_policy_time_key(row)
        if action_type:
            rows_with_action_type += 1
            action_counts[action_type] += 1
        if policy:
            rows_with_policy += 1
            policy_counts[policy] += 1
        if region:
            rows_with_region += 1
            region_counts[region] += 1
        if time_key:
            rows_with_time += 1
        if allowed is True:
            allowed_count += 1
            if policy:
                allowed_policy_counts[policy] += 1
        elif allowed is False:
            blocked_count += 1
            if policy:
                blocked_policy_counts[policy] += 1
        if region and policy:
            region_policy_counts[f"{region}|{policy}"] += 1
        if region and action_type and policy:
            region_action_policy_counts[f"{region}|{action_type}|{policy}"] += 1
        if time_key and policy:
            time_policy_counts[f"{time_key}|{policy}"] += 1

    mixed_allowed_policy_counts = {
        policy: count
        for policy, count in sorted(allowed_policy_counts.items())
        if _observed_policy_is_mixed_allowed(policy)
    }
    missing = []
    if not production_rows:
        missing.append("production_policy_rows")
    if allowed_count <= 0:
        missing.append("allowed_policy_labels")
    if blocked_count <= 0:
        missing.append("blocked_policy_labels")
    if rows_with_policy <= 0:
        missing.append("action_mask_policy")
    if rows_with_action_type <= 0:
        missing.append("action_type")
    if rows_with_region <= 0:
        missing.append("region_context")
    if rows_with_time <= 0:
        missing.append("temporal_context")
    if len(region_policy_counts) <= 0:
        missing.append("region_policy_coverage")
    if len(region_action_policy_counts) <= 0:
        missing.append("region_action_policy_coverage")
    if not mixed_allowed_policy_counts:
        missing.append("mixed_risk_allowed_policy_coverage")
    return {
        "schema": "territory_world_model.production_policy_history_quality.v1",
        "status": "pass" if not missing else "review",
        "row_count": len(rows),
        "production_policy_row_count": len(production_rows),
        "allowed_count": allowed_count,
        "blocked_count": blocked_count,
        "rows_with_policy": rows_with_policy,
        "rows_with_action_type": rows_with_action_type,
        "rows_with_region": rows_with_region,
        "rows_with_time": rows_with_time,
        "action_counts": dict(sorted(action_counts.items())),
        "policy_counts": dict(sorted(policy_counts.items())),
        "allowed_policy_counts": dict(sorted(allowed_policy_counts.items())),
        "blocked_policy_counts": dict(sorted(blocked_policy_counts.items())),
        "mixed_allowed_policy_counts": mixed_allowed_policy_counts,
        "region_count": len(region_counts),
        "region_policy_key_count": len(region_policy_counts),
        "region_action_policy_key_count": len(region_action_policy_counts),
        "time_policy_key_count": len(time_policy_counts),
        "region_counts": dict(sorted(region_counts.items())),
        "sample_region_policy_keys": dict(sorted(region_policy_counts.items())[:12]),
        "sample_region_action_policy_keys": dict(sorted(region_action_policy_counts.items())[:12]),
        "sample_time_policy_keys": dict(sorted(time_policy_counts.items())[:12]),
        "missing_policy_gates": missing,
        "claim_boundary": "preflight for production-observed action-mask feasibility validation only; not a production accuracy claim",
    }


def _empty_observed_policy_history_quality(status: str) -> dict[str, Any]:
    return {
        "schema": "territory_world_model.production_policy_history_quality.v1",
        "status": status,
        "row_count": 0,
        "production_policy_row_count": 0,
        "allowed_count": 0,
        "blocked_count": 0,
        "rows_with_policy": 0,
        "rows_with_action_type": 0,
        "rows_with_region": 0,
        "rows_with_time": 0,
        "action_counts": {},
        "policy_counts": {},
        "allowed_policy_counts": {},
        "blocked_policy_counts": {},
        "mixed_allowed_policy_counts": {},
        "region_count": 0,
        "region_policy_key_count": 0,
        "region_action_policy_key_count": 0,
        "time_policy_key_count": 0,
        "region_counts": {},
        "sample_region_policy_keys": {},
        "sample_region_action_policy_keys": {},
        "sample_time_policy_keys": {},
        "missing_policy_gates": ["production_policy_history_not_provided" if status == "not_provided" else "production_policy_history_missing"],
        "claim_boundary": "preflight for production-observed action-mask feasibility validation only; not a production accuracy claim",
    }


def production_policy_history_alignment(production_quality: dict[str, Any], synthetic_summary: dict[str, Any]) -> dict[str, Any]:
    benchmark = synthetic_summary.get("policy_coverage_benchmark") or {}
    production_status = str(production_quality.get("status") or "not_provided")
    observed = {
        "production_policy_row_count": int(production_quality.get("production_policy_row_count") or 0),
        "allowed_count": int(production_quality.get("allowed_count") or 0),
        "blocked_count": int(production_quality.get("blocked_count") or 0),
        "region_policy_key_count": int(production_quality.get("region_policy_key_count") or 0),
        "region_action_policy_key_count": int(production_quality.get("region_action_policy_key_count") or 0),
        "mixed_allowed_policy_counts": dict(production_quality.get("mixed_allowed_policy_counts") or {}),
    }
    required = {
        "allowed_count": int(benchmark.get("required_allowed_count") or 0),
        "blocked_count": int(benchmark.get("required_blocked_count") or 0),
        "region_policy_key_count": int(benchmark.get("required_region_policy_key_count") or 0),
        "region_action_policy_key_count": int(benchmark.get("required_region_action_policy_key_count") or 0),
        "mixed_allowed_policies": list(benchmark.get("required_mixed_allowed_policies") or []),
    }
    missing: list[str] = []
    if production_status == "not_provided":
        missing.append("production_policy_history_not_provided")
    elif production_status != "pass":
        missing.append("production_policy_history_quality")
    if not benchmark or benchmark.get("status") == "skipped":
        missing.append("synthetic_policy_coverage_benchmark")
    if benchmark:
        if observed["allowed_count"] < required["allowed_count"]:
            missing.append("allowed_policy_count_below_synthetic_unseen_benchmark")
        if observed["blocked_count"] < required["blocked_count"]:
            missing.append("blocked_policy_count_below_synthetic_unseen_benchmark")
        if observed["region_policy_key_count"] < required["region_policy_key_count"]:
            missing.append("region_policy_key_count_below_synthetic_unseen_benchmark")
        if observed["region_action_policy_key_count"] < required["region_action_policy_key_count"]:
            missing.append("region_action_policy_key_count_below_synthetic_unseen_benchmark")
        missing_mixed_policies = [
            policy
            for policy in required["mixed_allowed_policies"]
            if int((observed["mixed_allowed_policy_counts"] or {}).get(policy) or 0) <= 0
        ]
        if missing_mixed_policies:
            missing.append("mixed_allowed_policy_coverage_below_synthetic_unseen_benchmark")
    else:
        missing_mixed_policies = []

    if production_status == "not_provided":
        status = "not_provided"
    else:
        status = "pass" if not missing else "review"
    return {
        "schema": "territory_world_model.production_policy_history_alignment.v1",
        "status": status,
        "production_policy_history_status": production_status,
        "synthetic_benchmark_status": benchmark.get("status"),
        "observed": observed,
        "required": required,
        "mixed_allowed_policy_coverage": {
            "required": required["mixed_allowed_policies"],
            "observed_counts": observed["mixed_allowed_policy_counts"],
            "missing": missing_mixed_policies,
        },
        "missing": missing,
        "claim_boundary": "coverage alignment prepares real action-mask feasibility validation only; it does not prove simulator accuracy or planner optimality",
    }


def _observed_policy_history_production_ready(row: dict[str, Any]) -> bool:
    synthetic_present = _row_has_any(row, "synthetic")
    nfp_present = _row_has_any(row, "not_for_production", "not_for_prod")
    if not synthetic_present or not nfp_present:
        return False
    if truthy(_row_attr(row, "synthetic")) or truthy(_row_attr(row, "not_for_production", "not_for_prod")):
        return False
    return bool(_observed_policy_action_type(row) or _observed_policy_label(row) or _observed_policy_allowed(row) is not None)


def _observed_policy_action_type(row: dict[str, Any]) -> str:
    return str(_row_attr(row, "action_type", "action", "decision_action", "planning_action") or "").strip()


def _observed_policy_label(row: dict[str, Any]) -> str:
    return str(_row_attr(row, "action_mask_policy", "policy_code", "policy_label", "feasibility_policy") or "").strip()


def _observed_policy_allowed(row: dict[str, Any]) -> bool | None:
    raw = _row_attr(row, "action_mask_allowed", "feasibility_allowed", "allowed", "is_allowed")
    if raw not in (None, ""):
        if isinstance(raw, bool):
            return raw
        normalized = str(raw).strip().lower()
        if normalized in {"1", "true", "yes", "y", "allowed", "allow", "pass", "approved"}:
            return True
        if normalized in {"0", "false", "no", "n", "blocked", "block", "review", "requires_review", "rejected", "denied"}:
            return False
    label = str(_row_attr(row, "feasibility_label", "action_mask_label", "mask_label") or "").strip().lower()
    if label:
        if "allow" in label or label in {"pass", "approved"}:
            return True
        if any(item in label for item in ("block", "review", "reject", "deny")):
            return False
    policy = _observed_policy_label(row).lower()
    if policy:
        if "allow" in policy and not any(item in policy for item in ("block", "blocked", "review")):
            return True
        if any(item in policy for item in ("block", "blocked", "review")):
            return False
    return None


def _observed_policy_region(row: dict[str, Any]) -> str:
    return str(_row_attr(row, "region_code", "cluster", "spatial_cluster", "block_id", "township_id", "county_code", "DKXZQDM", "XZQDM") or "").strip()


def _observed_policy_time_key(row: dict[str, Any]) -> str:
    return str(_row_attr(row, "period", "time_index", "approval_date", "decision_date", "year", "quarter") or "").strip()


def _observed_policy_is_mixed_allowed(policy: str) -> bool:
    normalized = policy.strip().lower()
    return bool(
        normalized
        and "allow" in normalized
        and not any(item in normalized for item in ("block", "blocked", "review"))
        and any(item in normalized for item in ("mixed", "condition", "protect", "restore"))
    )


def _observed_history_schema_recommendations(missing_groups: list[str], missing_data_gates: list[str]) -> list[str]:
    recommendations = []
    if missing_groups:
        recommendations.append(f"add fields for required groups: {', '.join(missing_groups)}")
    if "production_usable_rows" in missing_data_gates:
        recommendations.append("provide rows with synthetic=false and not_for_production=false plus parseable treatment, outcome, spatial support and covariates")
    if "production_treated_rows" in missing_data_gates or "production_control_rows" in missing_data_gates:
        recommendations.append("include both approved/treated and review/rejected/control approval outcomes")
    if "spatial_support" in missing_data_gates:
        recommendations.append("add real spatial unit ids, neighbor project ids, or complete x/y coordinates")
    if "adjustment_covariates" in missing_data_gates:
        recommendations.append("add numeric pre-treatment covariates such as area, quality, risk, rule-hit and evidence-coverage measures")
    if "explicit_production_flags" in missing_data_gates:
        recommendations.append("include explicit synthetic and not_for_production columns so review gates can block demo rows")
    return recommendations


def _observed_history_treatment(row: dict[str, Any]) -> int | None:
    explicit = _binary_treatment(_row_attr(row, "treatment", "treated", "intervention"))
    if explicit is not None:
        return explicit
    status = str(_row_attr(row, "approval_status", "decision_result", "DKZT", "status", "task_status", "review_result") or "").strip().lower()
    if status in {"approved", "approved_with_conditions", "conditional_approval", "conditional", "granted", "pass", "passed"}:
        return 1
    if status in {"proposed", "in_review", "pending", "open", "returned", "rejected", "denied", "supplement_required", "requires_supplementary_evidence", "hit_requires_review"}:
        return 0
    approved_area = safe_float(_row_attr(row, "approved_area_m2", "ZDZMJ"), None)
    if approved_area is not None:
        return 1 if float(approved_area) > 0 else 0
    return None


def _observed_history_has_outcome(row: dict[str, Any]) -> bool:
    for key in ("outcome", "planning_utility_delta", "utility_delta", "ranking_score", "observed_utility_delta", "reviewed_planning_utility_delta"):
        if safe_float(_row_attr(row, key), None) is not None:
            return True
    return safe_float(_row_attr(row, "area_m2", "planned_area_m2", "DKMJ", "ZYZMJ", "approved_area_m2", "ZDZMJ"), None) is not None


def _observed_history_has_covariates(row: dict[str, Any]) -> bool:
    raw = row.get("covariates")
    if isinstance(raw, dict) and any(safe_float(value, None) is not None for value in raw.values()):
        return True
    return any(
        safe_float(_row_attr(row, key), None) is not None
        for key in ("area_m2", "planned_area_m2", "DKMJ", "quality_score", "baseline_outcome", "baseline_risk_score", "risk_score", "evidence_coverage", "rule_hit_count", "review_task_count")
    )


def _observed_history_spatial_support(row: dict[str, Any]) -> dict[str, bool]:
    cluster = _row_attr(row, "cluster", "spatial_cluster", "block_id", "township_id", "region_code", "county_code", "DKXZQDM", "XZQDM")
    neighbors = _neighbor_ids(_row_attr(row, "neighbors", "neighbor_unit_ids") or [])
    x = safe_float(_row_attr(row, "x", "lon", "longitude"), None)
    y = safe_float(_row_attr(row, "y", "lat", "latitude"), None)
    has_cluster = cluster not in (None, "")
    has_neighbors = bool(neighbors)
    has_coordinates = x is not None and y is not None
    return {
        "has_any": has_cluster or has_neighbors or has_coordinates,
        "has_cluster": has_cluster,
        "has_neighbors": has_neighbors,
        "has_coordinates": has_coordinates,
    }


def _row_has_any(row: dict[str, Any], *names: str) -> bool:
    wanted = {name.lower() for name in names}
    return any(str(key).lower() in wanted for key in row)


def _row_attr(row: dict[str, Any], *names: str) -> Any:
    wanted = {name.lower() for name in names}
    for name in names:
        if name in row:
            return row.get(name)
    for key, value in row.items():
        if str(key).lower() in wanted:
            return value
    return None


def _binary_treatment(value: Any) -> int | None:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if float(value) >= 0.5 else 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "treated", "treatment", "yes", "protect", "intervention", "causal_calibrated"}:
            return 1
        if normalized in {"0", "false", "control", "untreated", "no", "baseline"}:
            return 0
    return None


def _neighbor_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return []


def audit_project_spatial_relations(dataset_root: Path) -> dict[str, Any]:
    relation_path = dataset_root / "relations" / "project_parcel_rel.csv"
    if not relation_path.exists():
        return {"exists": False, "path": str(relation_path)}
    rows = read_csv(relation_path)
    neighbor_map = build_project_neighbor_map(dataset_root)
    edge_count = sum(len(values) for values in neighbor_map.values()) // 2
    return {
        "exists": True,
        "path": str(relation_path),
        "row_count": len(rows),
        "synthetic_count": sum(1 for row in rows if truthy(row.get("synthetic"))),
        "not_for_production_count": sum(1 for row in rows if truthy(row.get("not_for_production"))),
        "project_count": len({str(row.get("project_id") or "") for row in rows if row.get("project_id")}),
        "parcel_count": len({str(row.get("bsm_norm") or "") for row in rows if row.get("bsm_norm")}),
        "project_neighbor_edge_count": edge_count,
        "project_with_neighbor_count": sum(1 for values in neighbor_map.values() if values),
        "neighbor_method": "shared_project_parcel_overlap",
    }


def audit_project_review_context(context: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not context:
        return {
            "schema": "territory_world_model.project_review_context_audit.v1",
            "status": "missing",
            "project_count": 0,
            "projects_with_rule_context": 0,
            "projects_with_review_context": 0,
        }
    return {
        "schema": "territory_world_model.project_review_context_audit.v1",
        "status": "present",
        "project_count": len(context),
        "projects_with_rule_context": sum(1 for item in context.values() if item.get("rule_eval_count")),
        "projects_with_review_context": sum(1 for item in context.values() if item.get("review_task_count")),
        "total_rule_eval_count": sum(int(item.get("rule_eval_count") or 0) for item in context.values()),
        "total_rule_hit_count": sum(int(item.get("rule_hit_count") or 0) for item in context.values()),
        "total_review_task_count": sum(int(item.get("review_task_count") or 0) for item in context.values()),
        "projects_with_completed_reviews": sum(1 for item in context.values() if item.get("completed_review_count")),
        "projects_with_open_reviews": sum(1 for item in context.values() if item.get("open_review_count")),
        "projects_with_confirmed_violations": sum(1 for item in context.values() if item.get("confirmed_violation_count")),
        "max_risk_score": round(max(float(item.get("risk_score") or 0.0) for item in context.values()), 6),
        "max_review_penalty": round(max(float(item.get("review_penalty") or 0.0) for item in context.values()), 6),
        "claim_boundary": "project review context enriches observed-history covariates; it does not override synthetic/not_for_production gates",
    }


def validate_twm_observed_history(svc: TerritoryWorldModelService, state_id: str, dataset_root: Path) -> dict[str, Any]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return {"status": "missing", "path": str(approval_path)}
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history_path": str(approval_path),
            "thresholds": {
                "min_records": 20,
                "min_treated": 5,
                "min_control": 5,
            },
        },
    )
    return _causal_report_summary(report)


def validate_twm_structural_validation_fixture(
    svc: TerritoryWorldModelService,
    state_id: str,
    fixture_path: Path | None,
) -> dict[str, Any]:
    if fixture_path is None:
        return {"status": "skipped", "note": "structural-validation fixture generation skipped"}
    if not fixture_path.exists():
        return {"status": "missing", "path": str(fixture_path)}
    rows = read_csv(fixture_path)
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history_path": str(fixture_path),
            "thresholds": {
                "min_records": 20,
                "min_treated": 10,
                "min_control": 10,
                "max_standard_error": 0.25,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["fixture"] = structural_validation_fixture_summary(fixture_path, rows)
    summary["claim_boundary"] = "default gate must remain review because the structural fixture is synthetic and not_for_production"
    return summary


def validate_twm_structural_validation_fixture_structural_check(
    svc: TerritoryWorldModelService,
    state_id: str,
    fixture_path: Path | None,
) -> dict[str, Any]:
    if fixture_path is None:
        return {"status": "skipped", "note": "structural-validation fixture generation skipped"}
    if not fixture_path.exists():
        return {"status": "missing", "path": str(fixture_path)}
    rows = read_csv(fixture_path)
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history_path": str(fixture_path),
            "thresholds": {
                "min_records": 20,
                "min_treated": 10,
                "min_control": 10,
                "allow_synthetic": True,
                "allow_not_for_production": True,
                "max_standard_error": 0.25,
                "max_abs_standardized_mean_difference": 0.35,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_cluster_treatment_gap": 0.45,
                "max_spatial_residual_moran": 1.0,
                "max_spatial_estimator_standard_error": 0.25,
                "max_spatial_effect_gap": 0.25,
                "max_spatial_bootstrap_interval_width": 0.35,
                "max_spatial_holdout_delta": 0.2,
                "min_spatial_units": 3,
                "min_spatial_unit_pairs": 3,
                "min_cross_treatment_edges": 3,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["fixture"] = structural_validation_fixture_summary(fixture_path, rows)
    summary["claim_boundary"] = (
        "diagnostic only: synthetic/not_for_production rows are allowed here to verify simulator causal/spatial plumbing; "
        "this pass does not upgrade production claims"
    )
    return summary


def validate_twm_synthetic_experiment_foundation(
    svc: TerritoryWorldModelService,
    state_id: str,
    experiment_path: Path | None,
) -> dict[str, Any]:
    if experiment_path is None:
        return {"status": "skipped", "note": "synthetic experiment foundation generation skipped"}
    if not experiment_path.exists():
        return {"status": "missing", "path": str(experiment_path)}
    rows = read_csv(experiment_path)
    quality = _observed_history_row_quality(rows)
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": _mean_numeric_field(rows, "treatment_effect", default=0.05),
            "observed_history_path": str(experiment_path),
            "thresholds": {
                "min_records": min(40, max(12, len(rows) // 4)),
                "min_treated": min(20, max(6, int(quality.get("treated_count") or 0) // 4)),
                "min_control": min(20, max(6, int(quality.get("control_count") or 0) // 4)),
                "max_standard_error": 0.25,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["foundation"] = synthetic_experiment_foundation_summary(experiment_path, rows)
    summary["claim_boundary"] = "default gate remains review because this experiment foundation is synthetic and not_for_production"
    return summary


def validate_twm_synthetic_experiment_foundation_structural_check(
    svc: TerritoryWorldModelService,
    state_id: str,
    experiment_path: Path | None,
) -> dict[str, Any]:
    if experiment_path is None:
        return {"status": "skipped", "note": "synthetic experiment foundation generation skipped"}
    if not experiment_path.exists():
        return {"status": "missing", "path": str(experiment_path)}
    rows = read_csv(experiment_path)
    quality = _observed_history_row_quality(rows)
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": _mean_numeric_field(rows, "treatment_effect", default=0.05),
            "observed_history_path": str(experiment_path),
            "thresholds": {
                "min_records": min(40, max(12, len(rows) // 4)),
                "min_treated": min(20, max(6, int(quality.get("treated_count") or 0) // 4)),
                "min_control": min(20, max(6, int(quality.get("control_count") or 0) // 4)),
                "allow_synthetic": True,
                "allow_not_for_production": True,
                "max_standard_error": 0.25,
                "max_abs_standardized_mean_difference": 0.35,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_cluster_treatment_gap": 0.45,
                "max_spatial_residual_moran": 1.0,
                "max_spatial_estimator_standard_error": 0.25,
                "max_spatial_effect_gap": 0.25,
                "max_spatial_bootstrap_interval_width": 0.35,
                "max_spatial_holdout_delta": 0.2,
                "min_spatial_units": 3,
                "min_spatial_unit_pairs": 3,
                "min_cross_treatment_edges": 3,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["foundation"] = synthetic_experiment_foundation_summary(experiment_path, rows)
    summary["claim_boundary"] = (
        "diagnostic only: synthetic/not_for_production rows are allowed here to validate multi-region, "
        "multi-period simulator/planner experiment plumbing"
    )
    return summary


def validate_twm_evidence_augmented_history(svc: TerritoryWorldModelService, state_id: str, dataset_root: Path) -> dict[str, Any]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return {"status": "missing", "path": str(approval_path)}
    rows = observed_history_rows_with_project_evidence(dataset_root)
    if not rows:
        return {"status": "missing", "path": str(approval_path), "note": "no approval rows could be evidence-augmented"}
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history": rows,
            "thresholds": {
                "min_records": 20,
                "min_treated": 5,
                "min_control": 5,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["evidence_augmentation"] = evidence_augmentation_summary(dataset_root, rows)
    return summary


def validate_twm_evidence_augmented_structural_check(svc: TerritoryWorldModelService, state_id: str, dataset_root: Path) -> dict[str, Any]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return {"status": "missing", "path": str(approval_path)}
    rows = observed_history_rows_with_project_evidence(dataset_root)
    if not rows:
        return {"status": "missing", "path": str(approval_path), "note": "no approval rows could be evidence-augmented"}
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history": rows,
            "thresholds": {
                "min_records": 20,
                "min_treated": 5,
                "min_control": 5,
                "allow_synthetic": True,
                "allow_not_for_production": True,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
                "max_spatial_estimator_standard_error": 1.0,
                "max_spatial_effect_gap": 1.0,
                "max_spatial_bootstrap_interval_width": 1.0,
                "max_spatial_holdout_delta": 1.0,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["evidence_augmentation"] = evidence_augmentation_summary(dataset_root, rows)
    summary["claim_boundary"] = (
        "diagnostic only: synthetic/not_for_production rows are temporarily allowed to verify joined rule/review/spatial context; "
        "production claims must use the default evidence gate"
    )
    return summary


def validate_twm_evidence_augmented_matched_history(
    svc: TerritoryWorldModelService,
    state_id: str,
    dataset_root: Path,
    *,
    max_standardized_distance: float | None = None,
) -> dict[str, Any]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return {"status": "missing", "path": str(approval_path)}
    rows = observed_history_rows_with_project_evidence(dataset_root)
    matched_rows, matching_report = match_twm_evidence_augmented_records(rows, max_standardized_distance=max_standardized_distance)
    if not matched_rows:
        return {
            "status": "review",
            "path": str(approval_path),
            "matching": matching_report,
            "note": "no treated/control pairs could be built from evidence-augmented TWM rows",
        }
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history": matched_rows,
            "thresholds": {
                "min_records": min(20, max(8, len(matched_rows))),
                "min_treated": min(5, max(3, sum(1 for row in matched_rows if _observed_history_treatment(row) == 1))),
                "min_control": min(5, max(3, sum(1 for row in matched_rows if _observed_history_treatment(row) == 0))),
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["matching"] = matching_report
    summary["evidence_augmentation"] = evidence_augmentation_summary(dataset_root, matched_rows)
    summary["claim_boundary"] = "matched local TWM rows improve structural diagnostics but production gates still require non-synthetic observed history"
    return summary


def validate_twm_evidence_augmented_matched_structural_check(
    svc: TerritoryWorldModelService,
    state_id: str,
    dataset_root: Path,
    *,
    max_standardized_distance: float | None = None,
) -> dict[str, Any]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return {"status": "missing", "path": str(approval_path)}
    rows = observed_history_rows_with_project_evidence(dataset_root)
    matched_rows, matching_report = match_twm_evidence_augmented_records(rows, max_standardized_distance=max_standardized_distance)
    if not matched_rows:
        return {
            "status": "review",
            "path": str(approval_path),
            "matching": matching_report,
            "note": "no treated/control pairs could be built from evidence-augmented TWM rows",
        }
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history": matched_rows,
            "thresholds": {
                "min_records": min(20, max(8, len(matched_rows))),
                "min_treated": min(5, max(3, sum(1 for row in matched_rows if _observed_history_treatment(row) == 1))),
                "min_control": min(5, max(3, sum(1 for row in matched_rows if _observed_history_treatment(row) == 0))),
                "allow_synthetic": True,
                "allow_not_for_production": True,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
                "max_spatial_estimator_standard_error": 1.0,
                "max_spatial_effect_gap": 1.0,
                "max_spatial_bootstrap_interval_width": 1.0,
                "max_spatial_holdout_delta": 1.0,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["matching"] = matching_report
    summary["evidence_augmentation"] = evidence_augmentation_summary(dataset_root, matched_rows)
    summary["claim_boundary"] = (
        "diagnostic only: matching and temporary synthetic/not_for_production allowance test balance/spatial plumbing; "
        "production claims must use default gates on real observed records"
    )
    return summary


def validate_twm_spatial_relation_augmented_history(svc: TerritoryWorldModelService, state_id: str, dataset_root: Path) -> dict[str, Any]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return {"status": "missing", "path": str(approval_path)}
    rows = observed_history_rows_with_project_neighbors(dataset_root)
    if not rows:
        return {"status": "missing", "path": str(approval_path), "note": "no approval rows could be augmented"}
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history": rows,
            "thresholds": {
                "min_records": 20,
                "min_treated": 5,
                "min_control": 5,
            },
        },
    )
    summary = _causal_report_summary(report)
    neighbor_map = build_project_neighbor_map(dataset_root)
    summary["relation_augmentation"] = {
        "method": "shared_project_parcel_overlap",
        "neighbor_project_count": sum(1 for values in neighbor_map.values() if values),
        "neighbor_edge_count": sum(len(values) for values in neighbor_map.values()) // 2,
        "augmented_row_count": len(rows),
        "rows_with_neighbors": sum(1 for row in rows if row.get("neighbors")),
        "claim_boundary": "relation-derived neighbors improve diagnostics but do not override synthetic/not_for_production gates",
    }
    return summary


def validate_twm_spatial_relation_augmented_structural_check(svc: TerritoryWorldModelService, state_id: str, dataset_root: Path) -> dict[str, Any]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return {"status": "missing", "path": str(approval_path)}
    rows = observed_history_rows_with_project_neighbors(dataset_root)
    if not rows:
        return {"status": "missing", "path": str(approval_path), "note": "no approval rows could be augmented"}
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history": rows,
            "thresholds": {
                "min_records": 20,
                "min_treated": 5,
                "min_control": 5,
                "allow_synthetic": True,
                "allow_not_for_production": True,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
                "max_spatial_estimator_standard_error": 1.0,
                "max_spatial_effect_gap": 1.0,
                "max_spatial_bootstrap_interval_width": 1.0,
                "max_spatial_holdout_delta": 1.0,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["claim_boundary"] = (
        "diagnostic only: synthetic/not_for_production rows are temporarily allowed to test spatial-link plumbing; "
        "production claims must use the default evidence gate"
    )
    return summary


def validate_paper7_causal_dataset(
    svc: TerritoryWorldModelService,
    state_id: str,
    dataset_path: Path,
    *,
    calibration_path: Path,
    sample_limit: int = 0,
) -> dict[str, Any]:
    if not dataset_path.exists():
        return {"status": "missing", "path": str(dataset_path)}
    records = paper7_rows_to_causal_records(dataset_path, sample_limit=sample_limit)
    calibration = _read_json_if_exists(calibration_path)
    model_effect = safe_float(calibration.get("predicted_att"), None) if calibration else None
    if model_effect is None:
        model_effect = 0.2646815104037523
    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "paper7_policy_intervention",
            "outcome": "paper7_observed_reward_delta",
            "model_effect": model_effect,
            "records": records,
            "thresholds": {
                "min_records": min(1000, max(8, len(records) // 4)),
                "min_treated": min(1000, max(3, sum(1 for row in records if row["treatment"] == 1) // 4)),
                "min_control": min(1000, max(3, sum(1 for row in records if row["treatment"] == 0) // 4)),
                "max_standard_error": 0.25,
                "enable_spatial_estimator": True,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["external_reference"] = {
        key: calibration.get(key)
        for key in ("empirical_att", "empirical_se", "predicted_att", "calibration_factor", "n_high_sampled", "n_low_sampled")
        if calibration and key in calibration
    }
    return summary


def validate_paper7_matched_causal_dataset(
    svc: TerritoryWorldModelService,
    state_id: str,
    dataset_path: Path,
    *,
    calibration_path: Path,
    sample_limit: int = 0,
    max_standardized_distance: float | None = None,
) -> dict[str, Any]:
    if not dataset_path.exists():
        return {"status": "missing", "path": str(dataset_path)}
    records = paper7_rows_to_causal_records(dataset_path, sample_limit=sample_limit)
    matched_records, matching_report = match_paper7_records(records, max_standardized_distance=max_standardized_distance)
    calibration = _read_json_if_exists(calibration_path)
    model_effect = safe_float(calibration.get("predicted_att"), None) if calibration else None
    if model_effect is None:
        model_effect = 0.2646815104037523
    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "paper7_policy_intervention_matched",
            "outcome": "paper7_observed_reward_delta",
            "model_effect": model_effect,
            "records": matched_records,
            "thresholds": {
                "min_records": min(1000, max(8, len(matched_records) // 4)),
                "min_treated": min(500, max(3, sum(1 for row in matched_records if row["treatment"] == 1) // 4)),
                "min_control": min(500, max(3, sum(1 for row in matched_records if row["treatment"] == 0) // 4)),
                "max_standard_error": 0.25,
                "enable_spatial_estimator": True,
            },
        },
    )
    summary = _causal_report_summary(report)
    summary["matching"] = matching_report
    summary["external_reference"] = {
        key: calibration.get(key)
        for key in ("empirical_att", "empirical_se", "predicted_att", "calibration_factor", "n_high_sampled", "n_low_sampled")
        if calibration and key in calibration
    }
    return summary


def paper7_rows_to_causal_records(dataset_path: Path, *, sample_limit: int = 0) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with dataset_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            if sample_limit and idx >= sample_limit:
                break
            treatment = safe_float(row.get("treatment"), None)
            outcome = safe_float(row.get("outcome"), None)
            if treatment is None or outcome is None:
                continue
            step = safe_float(row.get("step_frac"), 0.0) or 0.0
            budget = safe_float(row.get("budget_remaining"), 0.0) or 0.0
            covariates = {
                key: float(value)
                for key, value in row.items()
                if key not in {"treatment", "outcome"} and safe_float(value, None) is not None
            }
            records.append(
                {
                    "unit_id": f"paper7:{idx}",
                    "treatment": 1 if float(treatment) >= 0.5 else 0,
                    "outcome": float(outcome),
                    "stratum": f"step_decile_{min(9, max(0, int(float(step) * 10)))}",
                    "cluster": f"budget_decile_{min(9, max(0, int((1.0 - float(budget)) * 10)))}",
                    "covariates": covariates,
                    "evidence_weight": 1.0,
                    "synthetic": False,
                    "not_for_production": False,
                    "source": "paper7_causal_mbrl_dataset",
                    "source_path": str(dataset_path),
                }
            )
    return records


def match_paper7_records(
    records: list[dict[str, Any]],
    *,
    max_standardized_distance: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Greedy one-to-one control-to-treated matching on standardized covariates.

    This improves data quality for validation without relaxing any TWM causal
    gate. The method is deterministic and reports distances so the match remains
    auditable rather than a hidden claim upgrade.
    """

    covariate_keys = [
        "budget_remaining",
        "global_slope",
        "global_cont",
        "step_frac",
        "slope_improvement",
        "block_farm_slope",
        "block_forest_slope",
        "block_slope_gap",
        "block_swap_potential",
        "block_invested",
    ]
    usable = [
        row
        for row in records
        if row.get("treatment") in {0, 1}
        and isinstance(row.get("covariates"), dict)
        and all(safe_float(row["covariates"].get(key), None) is not None for key in covariate_keys)
    ]
    if not usable:
        return [], {"method": "greedy_standardized_nearest_neighbor", "status": "not_applicable", "pair_count": 0}

    moments: dict[str, tuple[float, float]] = {}
    for key in covariate_keys:
        values = [float(row["covariates"][key]) for row in usable]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
        moments[key] = (mean, math.sqrt(variance) or 1.0)

    def vector(row: dict[str, Any]) -> tuple[float, ...]:
        return tuple((float(row["covariates"][key]) - moments[key][0]) / moments[key][1] for key in covariate_keys)

    def distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))

    treated = [(idx, row, vector(row)) for idx, row in enumerate(usable) if row["treatment"] == 1]
    control = [(idx, row, vector(row)) for idx, row in enumerate(usable) if row["treatment"] == 0]
    buckets: dict[tuple[str, str], list[tuple[int, dict[str, Any], tuple[float, ...]]]] = {}
    for item in treated:
        _idx, row, _vec = item
        buckets.setdefault((str(row.get("stratum") or ""), str(row.get("cluster") or "")), []).append(item)

    used_treated: set[int] = set()
    matched: list[dict[str, Any]] = []
    distances: list[float] = []
    for _control_idx, control_row, control_vec in control:
        candidates = list(buckets.get((str(control_row.get("stratum") or ""), str(control_row.get("cluster") or "")), []))
        if not candidates:
            candidates = [
                item
                for (stratum, _cluster), items in buckets.items()
                if stratum == str(control_row.get("stratum") or "")
                for item in items
            ]
        if not candidates:
            candidates = treated

        best: tuple[int, dict[str, Any], tuple[float, ...]] | None = None
        best_distance: float | None = None
        for item in candidates:
            treated_idx, _treated_row, treated_vec = item
            if treated_idx in used_treated:
                continue
            item_distance = distance(control_vec, treated_vec)
            if best_distance is None or item_distance < best_distance:
                best = item
                best_distance = item_distance
        if best is None:
            continue
        if max_standardized_distance is not None and float(best_distance or 0.0) > float(max_standardized_distance):
            continue
        used_treated.add(best[0])
        matched.append({**control_row, "match_group": f"paper7_match:{len(distances)}", "matching_method": "greedy_standardized_nearest_neighbor"})
        matched.append({**best[1], "match_group": f"paper7_match:{len(distances)}", "matching_method": "greedy_standardized_nearest_neighbor"})
        distances.append(float(best_distance or 0.0))

    distances_sorted = sorted(distances)
    return matched, {
        "method": "greedy_standardized_nearest_neighbor",
        "status": "pass" if matched else "not_applicable",
        "source_record_count": len(records),
        "usable_record_count": len(usable),
        "treated_source_count": len(treated),
        "control_source_count": len(control),
        "pair_count": len(distances),
        "matched_record_count": len(matched),
        "covariates": covariate_keys,
        "mean_standardized_distance": round(sum(distances) / len(distances), 6) if distances else None,
        "p95_standardized_distance": round(distances_sorted[int(0.95 * (len(distances_sorted) - 1))], 6) if distances_sorted else None,
        "max_standardized_distance": round(distances_sorted[-1], 6) if distances_sorted else None,
        "caliper_max_standardized_distance": round(float(max_standardized_distance), 6) if max_standardized_distance is not None else None,
        "claim_boundary": "matching improves validation input quality but does not relax TWM evidence gates",
    }


def match_twm_evidence_augmented_records(
    rows: list[dict[str, Any]],
    *,
    max_standardized_distance: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministically match local TWM treated/control rows on evidence covariates.

    The matcher prefers treated/control pairs inside the same shared-parcel
    component, then falls back to the same stratum before global nearest-neighbor
    matching. It is a data-quality diagnostic, not a claim upgrade.
    """

    usable = []
    for index, row in enumerate(rows):
        treatment = _observed_history_treatment(row)
        if treatment not in {0, 1}:
            continue
        covariates = _twm_evidence_matching_covariates(row)
        if not covariates:
            continue
        usable.append(
            {
                "index": index,
                "row": row,
                "treatment": treatment,
                "covariates": covariates,
                "cluster": str(row.get("cluster") or row.get("spatial_cluster") or ""),
                "stratum": str(_row_attr(row, "stratum", "region_code", "county_code", "DKXZQDM", "XZQDM") or ""),
            }
        )
    if not usable:
        return [], {"method": "twm_evidence_greedy_standardized_nearest_neighbor", "status": "not_applicable", "pair_count": 0}

    covariate_keys = [
        key
        for key in TWM_EVIDENCE_MATCHING_COVARIATES
        if sum(1 for item in usable if key in item["covariates"]) >= 2
    ]
    covariate_keys = [
        key
        for key in covariate_keys
        if any(item["treatment"] == 1 and key in item["covariates"] for item in usable)
        and any(item["treatment"] == 0 and key in item["covariates"] for item in usable)
    ]
    if not covariate_keys:
        return [], {
            "method": "twm_evidence_greedy_standardized_nearest_neighbor",
            "status": "not_applicable",
            "source_record_count": len(rows),
            "usable_record_count": len(usable),
            "pair_count": 0,
            "note": "no numeric evidence covariates are shared by treated and control rows",
        }

    moments: dict[str, tuple[float, float]] = {}
    for key in covariate_keys:
        values = [float(item["covariates"][key]) for item in usable if key in item["covariates"]]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
        moments[key] = (mean, math.sqrt(variance) or 1.0)

    def vector(item: dict[str, Any]) -> tuple[float, ...]:
        values = []
        for key in covariate_keys:
            mean, std = moments[key]
            raw = item["covariates"].get(key, mean)
            values.append((float(raw) - mean) / std)
        return tuple(values)

    def distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))

    enriched = [(item["index"], item["row"], item["treatment"], item["cluster"], item["stratum"], vector(item)) for item in usable]
    treated = [item for item in enriched if item[2] == 1]
    control = [item for item in enriched if item[2] == 0]
    treated_by_cluster: dict[str, list[tuple[int, dict[str, Any], int, str, str, tuple[float, ...]]]] = {}
    treated_by_stratum: dict[str, list[tuple[int, dict[str, Any], int, str, str, tuple[float, ...]]]] = {}
    for item in treated:
        treated_by_cluster.setdefault(item[3], []).append(item)
        treated_by_stratum.setdefault(item[4], []).append(item)

    used_treated: set[int] = set()
    matched: list[dict[str, Any]] = []
    distances: list[float] = []
    same_cluster_pairs = 0
    same_stratum_pairs = 0
    fallback_pairs = 0
    control_order = sorted(
        control,
        key=lambda item: (
            0 if item[3] and treated_by_cluster.get(item[3]) else 1,
            0 if item[4] and treated_by_stratum.get(item[4]) else 1,
            item[4],
            item[3],
            item[0],
        ),
    )
    for _control_index, control_row, _control_treatment, control_cluster, control_stratum, control_vec in control_order:
        candidate_groups = [
            ("same_component_cluster", treated_by_cluster.get(control_cluster, []) if control_cluster else []),
            ("same_stratum", treated_by_stratum.get(control_stratum, []) if control_stratum else []),
            ("global", treated),
        ]
        best = None
        best_distance = None
        best_scope = "global"
        for scope, candidates in candidate_groups:
            scoped_best = None
            scoped_distance = None
            for item in candidates:
                treated_index, _treated_row, _treated_treatment, _treated_cluster, _treated_stratum, treated_vec = item
                if treated_index in used_treated:
                    continue
                item_distance = distance(control_vec, treated_vec)
                if scoped_distance is None or item_distance < scoped_distance:
                    scoped_best = item
                    scoped_distance = item_distance
            if scoped_best is not None:
                best = scoped_best
                best_distance = scoped_distance
                best_scope = scope
                break
        if best is None:
            continue
        if max_standardized_distance is not None and float(best_distance or 0.0) > float(max_standardized_distance):
            continue
        match_group = f"twm_evidence_match:{len(distances)}"
        used_treated.add(best[0])
        if best_scope == "same_component_cluster":
            same_cluster_pairs += 1
        elif best_scope == "same_stratum":
            same_stratum_pairs += 1
        else:
            fallback_pairs += 1
        matched.append(
            {
                **control_row,
                "match_group": match_group,
                "matching_method": "twm_evidence_greedy_standardized_nearest_neighbor",
                "matching_scope": best_scope,
                "matching_standardized_distance": round(float(best_distance or 0.0), 6),
            }
        )
        matched.append(
            {
                **best[1],
                "match_group": match_group,
                "matching_method": "twm_evidence_greedy_standardized_nearest_neighbor",
                "matching_scope": best_scope,
                "matching_standardized_distance": round(float(best_distance or 0.0), 6),
            }
        )
        distances.append(float(best_distance or 0.0))

    distances_sorted = sorted(distances)
    return matched, {
        "method": "twm_evidence_greedy_standardized_nearest_neighbor",
        "status": "pass" if matched else "not_applicable",
        "source_record_count": len(rows),
        "usable_record_count": len(usable),
        "treated_source_count": len(treated),
        "control_source_count": len(control),
        "pair_count": len(distances),
        "matched_record_count": len(matched),
        "same_component_cluster_pair_count": same_cluster_pairs,
        "same_stratum_pair_count": same_stratum_pairs,
        "global_fallback_pair_count": fallback_pairs,
        "covariates": covariate_keys,
        "mean_standardized_distance": round(sum(distances) / len(distances), 6) if distances else None,
        "p95_standardized_distance": round(distances_sorted[int(0.95 * (len(distances_sorted) - 1))], 6) if distances_sorted else None,
        "max_standardized_distance": round(distances_sorted[-1], 6) if distances_sorted else None,
        "caliper_max_standardized_distance": round(float(max_standardized_distance), 6) if max_standardized_distance is not None else None,
        "claim_boundary": "local TWM matching diagnoses balance/spatial support; it does not relax synthetic or not_for_production gates",
    }


def _twm_evidence_matching_covariates(row: dict[str, Any]) -> dict[str, float]:
    covariates: dict[str, float] = {}
    raw = row.get("covariates")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in TWM_EVIDENCE_MATCHING_COVARIATES:
                numeric = safe_float(value, None)
                if numeric is not None:
                    covariates[str(key)] = float(numeric)
    for key in TWM_EVIDENCE_MATCHING_COVARIATES:
        numeric = safe_float(_row_attr(row, key), None)
        if numeric is not None:
            covariates[key] = float(numeric)
    return covariates


def observed_history_rows_with_project_neighbors(dataset_root: Path) -> list[dict[str, Any]]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return []
    neighbor_map = build_project_neighbor_map(dataset_root)
    rows: list[dict[str, Any]] = []
    for row in read_csv(approval_path):
        item = dict(row)
        project_id = str(item.get("project_id") or "")
        neighbors = sorted(neighbor_map.get(project_id, set()))
        if neighbors:
            item["unit_id"] = project_id
            item["neighbors"] = ";".join(neighbors)
            item["neighbor_unit_ids"] = item["neighbors"]
        rows.append(item)
    return rows


def observed_history_rows_with_project_evidence(dataset_root: Path) -> list[dict[str, Any]]:
    approval_path = dataset_root / "tables" / "approval_records.csv"
    if not approval_path.exists():
        return []
    neighbor_map = build_project_neighbor_map(dataset_root)
    component_map = build_project_component_cluster_map(dataset_root)
    review_context = build_project_review_context(dataset_root)
    rows: list[dict[str, Any]] = []
    for row in read_csv(approval_path):
        item = dict(row)
        project_id = str(item.get("project_id") or "").strip()
        item.setdefault("unit_id", project_id or str(item.get("approval_id") or ""))
        neighbors = sorted(neighbor_map.get(project_id, set()))
        if neighbors:
            item["neighbors"] = ";".join(neighbors)
            item["neighbor_unit_ids"] = item["neighbors"]
        if project_id in component_map:
            item["cluster"] = component_map[project_id]
            item["spatial_cluster"] = component_map[project_id]
        context = review_context.get(project_id) or {}
        if context:
            for key, value in context.items():
                item[key] = value
        rows.append(item)
    return rows


def evidence_augmentation_summary(dataset_root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    review_context = build_project_review_context(dataset_root)
    component_map = build_project_component_cluster_map(dataset_root)
    clusters: dict[str, dict[str, int]] = {}
    for row in rows:
        cluster = str(row.get("cluster") or "")
        if not cluster:
            continue
        treatment = _observed_history_treatment(row)
        bucket = clusters.setdefault(cluster, {"record_count": 0, "treated_count": 0, "control_count": 0})
        bucket["record_count"] += 1
        if treatment == 1:
            bucket["treated_count"] += 1
        if treatment == 0:
            bucket["control_count"] += 1
    mixed_clusters = {
        key: value
        for key, value in clusters.items()
        if value["treated_count"] > 0 and value["control_count"] > 0
    }
    return {
        "schema": "territory_world_model.evidence_augmented_history.v1",
        "row_count": len(rows),
        "rows_with_neighbors": sum(1 for row in rows if row.get("neighbors")),
        "rows_with_review_context": sum(1 for row in rows if safe_float(row.get("rule_eval_count"), None) is not None),
        "rows_with_spatial_component": sum(1 for row in rows if row.get("cluster") in set(component_map.values())),
        "project_review_context": audit_project_review_context(review_context),
        "component_cluster_count": len(set(component_map.values())),
        "mixed_component_cluster_count": len(mixed_clusters),
        "sample_mixed_component_clusters": [
            {"cluster": key, **value}
            for key, value in sorted(mixed_clusters.items())[:10]
        ],
        "claim_boundary": "joined rule/review/spatial context enriches structural validation but remains gated by source labels",
    }


def build_project_review_context(dataset_root: Path) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}

    def bucket(project_id: str) -> dict[str, Any]:
        return context.setdefault(
            project_id,
            {
                "rule_eval_count": 0,
                "rule_hit_count": 0,
                "critical_rule_hit_count": 0,
                "high_rule_hit_count": 0,
                "review_task_count": 0,
                "open_review_count": 0,
                "completed_review_count": 0,
                "supplement_required_review_count": 0,
                "confirmed_violation_count": 0,
                "risk_score": 0.0,
                "review_penalty": 0.0,
            },
        )

    rule_path = dataset_root / "tables" / "rule_evaluation.csv"
    if rule_path.exists():
        for row in read_csv(rule_path):
            project_id = str(row.get("project_id") or "").strip()
            if not project_id:
                continue
            item = bucket(project_id)
            item["rule_eval_count"] += 1
            risk = _rule_eval_risk_score(row)
            item["risk_score"] = max(float(item["risk_score"]), risk)
            finding = str(row.get("finding_status") or "").strip().lower()
            severity = str(row.get("severity") or "").strip().lower()
            if finding not in {"pass", "passed", "no_hit", "clear"}:
                item["rule_hit_count"] += 1
                if severity == "critical":
                    item["critical_rule_hit_count"] += 1
                if severity == "high":
                    item["high_rule_hit_count"] += 1

    review_path = dataset_root / "tables" / "review_tasks.csv"
    if review_path.exists():
        for row in read_csv(review_path):
            project_id = str(row.get("project_id") or "").strip()
            if not project_id:
                continue
            item = bucket(project_id)
            item["review_task_count"] += 1
            status = str(row.get("task_status") or "").strip().lower()
            result = str(row.get("review_result") or "").strip().lower()
            if status in {"open", "pending", "in_review"}:
                item["open_review_count"] += 1
            if status in {"completed", "closed", "resolved"}:
                item["completed_review_count"] += 1
            if result in {"requires_supplementary_evidence", "needs_supplement", "supplement_required"}:
                item["supplement_required_review_count"] += 1
            if result in {"suspected_violation_confirmed", "violation_confirmed", "confirmed"}:
                item["confirmed_violation_count"] += 1
            item["review_penalty"] = max(float(item["review_penalty"]), _review_task_penalty(row))

    for item in context.values():
        for key, value in list(item.items()):
            if isinstance(value, float):
                item[key] = round(value, 6)
    return context


def build_project_component_cluster_map(dataset_root: Path) -> dict[str, str]:
    neighbor_map = build_project_neighbor_map(dataset_root)
    project_ids: set[str] = set(neighbor_map)
    for neighbors in neighbor_map.values():
        project_ids.update(neighbors)
    component_by_project: dict[str, str] = {}
    seen: set[str] = set()
    component_index = 0
    for project_id in sorted(project_ids):
        if project_id in seen:
            continue
        stack = [project_id]
        component: list[str] = []
        seen.add(project_id)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(neighbor_map.get(current, set())):
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        if len(component) <= 1:
            continue
        cluster_id = f"shared_parcel_component_{component_index:03d}"
        component_index += 1
        for project in component:
            component_by_project[project] = cluster_id
    return component_by_project


def _rule_eval_risk_score(row: dict[str, Any]) -> float:
    severity = str(row.get("severity") or "").strip().lower()
    severity_weight = {
        "critical": 0.95,
        "blocking": 0.95,
        "high": 0.78,
        "medium": 0.48,
        "low": 0.22,
        "info": 0.08,
    }.get(severity, 0.25)
    finding = str(row.get("finding_status") or "").strip().lower()
    if finding in {"pass", "passed", "no_hit", "clear"}:
        return min(0.12, severity_weight)
    metric = safe_float(row.get("metric_value"), None)
    metric_boost = 0.0
    if metric is not None and float(metric) > 0:
        metric_boost = 0.05
    return round(max(0.25, min(1.0, severity_weight + metric_boost)), 6)


def _review_task_penalty(row: dict[str, Any]) -> float:
    status = str(row.get("task_status") or "").strip().lower()
    result = str(row.get("review_result") or "").strip().lower()
    if result in {"suspected_violation_confirmed", "violation_confirmed", "confirmed"}:
        return 1.0
    if result in {"requires_supplementary_evidence", "needs_supplement", "supplement_required"}:
        return 0.65
    if status in {"open", "pending", "in_review"} or result == "pending":
        return 0.45
    if status in {"completed", "closed", "resolved"}:
        return 0.15
    return 0.0


def build_project_neighbor_map(dataset_root: Path) -> dict[str, set[str]]:
    relation_path = dataset_root / "relations" / "project_parcel_rel.csv"
    if not relation_path.exists():
        return {}
    parcel_to_projects: dict[str, set[str]] = {}
    for row in read_csv(relation_path):
        project_id = str(row.get("project_id") or "").strip()
        parcel_id = str(row.get("bsm_norm") or row.get("parcel_id") or "").strip()
        if not project_id or not parcel_id:
            continue
        parcel_to_projects.setdefault(parcel_id, set()).add(project_id)

    neighbors: dict[str, set[str]] = {}
    for projects in parcel_to_projects.values():
        if len(projects) < 2:
            continue
        for project_id in projects:
            peers = projects - {project_id}
            if peers:
                neighbors.setdefault(project_id, set()).update(peers)
    return neighbors


def summarize_validation(report: dict[str, Any]) -> dict[str, Any]:
    twm_gate = report.get("twm_observed_history_gate") or {}
    structural_fixture = report.get("twm_structural_validation_fixture") or {}
    structural_schema = report.get("twm_structural_validation_schema_audit") or {}
    structural_fixture_gate = report.get("twm_structural_validation_gate") or {}
    structural_fixture_check = report.get("twm_structural_validation_structural_check") or {}
    synthetic_experiment = report.get("twm_synthetic_experiment_foundation") or {}
    synthetic_experiment_schema = report.get("twm_synthetic_experiment_schema_audit") or {}
    synthetic_experiment_gate = report.get("twm_synthetic_experiment_gate") or {}
    synthetic_experiment_check = report.get("twm_synthetic_experiment_structural_check") or {}
    spatial_gate = report.get("twm_spatial_relation_augmented_gate") or {}
    relation_structural_gate = report.get("twm_spatial_relation_augmented_structural_check") or {}
    evidence_gate = report.get("twm_evidence_augmented_gate") or {}
    evidence_structural_gate = report.get("twm_evidence_augmented_structural_check") or {}
    evidence_matched_gate = report.get("twm_evidence_augmented_matched_gate") or {}
    evidence_matched_structural_gate = report.get("twm_evidence_augmented_matched_structural_check") or {}
    paper7_gate = report.get("paper7_causal_gate") or {}
    paper7_matched_gate = report.get("paper7_matched_causal_gate") or {}
    paper7_caliper_matched_gate = report.get("paper7_caliper_matched_causal_gate") or {}
    data_audit = report.get("twm_dataset_audit") or {}
    schema_audit = report.get("twm_observed_history_schema_audit") or {}
    production_schema_audit = report.get("production_observed_history_schema_audit") or {}
    production_policy_quality = production_schema_audit.get("policy_history_quality") or {}
    production_policy_alignment = report.get("production_policy_history_alignment") or {}
    relation_aug = spatial_gate.get("relation_augmentation") or {}
    return {
        "status": "review",
        "twm_dataset_rows": {
            key: value.get("row_count")
            for key, value in ((data_audit.get("tables") or {}).items())
        },
        "twm_production_ready_observed_history_rows": data_audit.get("production_ready_observed_history_rows", 0),
        "twm_observed_history_schema_status": schema_audit.get("status"),
        "twm_observed_history_schema_missing_data_gates": schema_audit.get("missing_data_gates", []),
        "twm_observed_history_schema_production_candidate_rows": (schema_audit.get("row_quality") or {}).get("production_candidate_row_count", 0),
        "production_observed_history_schema_status": production_schema_audit.get("status"),
        "production_observed_history_schema_missing_data_gates": production_schema_audit.get("missing_data_gates", []),
        "production_observed_history_schema_production_candidate_rows": (production_schema_audit.get("row_quality") or {}).get("production_candidate_row_count", 0),
        "production_policy_history_status": production_policy_quality.get("status"),
        "production_policy_history_missing": production_policy_quality.get("missing_policy_gates", []),
        "production_policy_history_row_count": production_policy_quality.get("production_policy_row_count", 0),
        "production_policy_history_allowed_count": production_policy_quality.get("allowed_count", 0),
        "production_policy_history_blocked_count": production_policy_quality.get("blocked_count", 0),
        "production_policy_history_region_policy_key_count": production_policy_quality.get("region_policy_key_count", 0),
        "production_policy_history_region_action_policy_key_count": production_policy_quality.get("region_action_policy_key_count", 0),
        "production_policy_history_mixed_allowed_policy_counts": production_policy_quality.get("mixed_allowed_policy_counts", {}),
        "production_policy_alignment_status": production_policy_alignment.get("status"),
        "production_policy_alignment_missing": production_policy_alignment.get("missing", []),
        "production_policy_alignment_required": production_policy_alignment.get("required", {}),
        "production_policy_alignment_observed": production_policy_alignment.get("observed", {}),
        "production_policy_alignment_mixed_allowed_missing": (
            (production_policy_alignment.get("mixed_allowed_policy_coverage") or {}).get("missing", [])
        ),
        "twm_structural_fixture_status": structural_fixture.get("status"),
        "twm_structural_fixture_row_count": structural_fixture.get("row_count", 0),
        "twm_structural_fixture_pair_count": structural_fixture.get("pair_count", 0),
        "twm_structural_fixture_schema_status": structural_schema.get("status"),
        "twm_structural_fixture_default_status": structural_fixture_gate.get("status"),
        "twm_structural_fixture_default_missing": structural_fixture_gate.get("evidence_gate", {}).get("missing", []),
        "twm_structural_fixture_structural_status": structural_fixture_check.get("status"),
        "twm_structural_fixture_structural_missing": structural_fixture_check.get("evidence_gate", {}).get("missing", []),
        "twm_structural_fixture_structural_neighbor_edge_count": (structural_fixture_check.get("estimate") or {}).get("spatial", {}).get("neighbor_edge_count", 0),
        "twm_structural_fixture_structural_spatial_estimator_status": (structural_fixture_check.get("estimate") or {}).get("spatial_estimator", {}).get("status"),
        "twm_structural_fixture_structural_balance_max_smd": (
            (structural_fixture_check.get("estimate") or {}).get("balance") or {}
        ).get("max_abs_standardized_mean_difference"),
        "twm_synthetic_experiment_status": synthetic_experiment.get("status"),
        "twm_synthetic_experiment_row_count": synthetic_experiment.get("row_count", 0),
        "twm_synthetic_experiment_pair_count": synthetic_experiment.get("pair_count", 0),
        "twm_synthetic_experiment_region_count": synthetic_experiment.get("region_count", 0),
        "twm_synthetic_experiment_period_count": synthetic_experiment.get("period_count", 0),
        "twm_synthetic_experiment_holdout_period_count": synthetic_experiment.get("holdout_period_count", 0),
        "twm_synthetic_experiment_scenario_count": synthetic_experiment.get("scenario_count", 0),
        "twm_synthetic_experiment_split_counts": synthetic_experiment.get("split_counts", {}),
        "twm_synthetic_experiment_holdout_oracle_action_counts": synthetic_experiment.get("holdout_oracle_action_counts", {}),
        "twm_synthetic_experiment_holdout_oracle_group_count": synthetic_experiment.get("holdout_oracle_group_count", 0),
        "twm_synthetic_experiment_holdout_oracle_action_type_count": synthetic_experiment.get("holdout_oracle_action_type_count", 0),
        "twm_synthetic_experiment_action_mask_allowed_count": synthetic_experiment.get("action_mask_allowed_count", 0),
        "twm_synthetic_experiment_action_mask_blocked_count": synthetic_experiment.get("action_mask_blocked_count", 0),
        "twm_synthetic_experiment_mixed_action_mask_action_types": synthetic_experiment.get("mixed_action_mask_action_types", []),
        "twm_synthetic_experiment_action_mask_counts_by_action_type": synthetic_experiment.get("action_mask_counts_by_action_type", {}),
        "twm_synthetic_experiment_schema_status": synthetic_experiment_schema.get("status"),
        "twm_synthetic_experiment_default_status": synthetic_experiment_gate.get("status"),
        "twm_synthetic_experiment_default_missing": synthetic_experiment_gate.get("evidence_gate", {}).get("missing", []),
        "twm_synthetic_experiment_structural_status": synthetic_experiment_check.get("status"),
        "twm_synthetic_experiment_structural_missing": synthetic_experiment_check.get("evidence_gate", {}).get("missing", []),
        "twm_synthetic_experiment_structural_neighbor_edge_count": (synthetic_experiment_check.get("estimate") or {}).get("spatial", {}).get("neighbor_edge_count", 0),
        "twm_synthetic_experiment_structural_spatial_estimator_status": (synthetic_experiment_check.get("estimate") or {}).get("spatial_estimator", {}).get("status"),
        "twm_synthetic_experiment_structural_balance_max_smd": (
            (synthetic_experiment_check.get("estimate") or {}).get("balance") or {}
        ).get("max_abs_standardized_mean_difference"),
        "twm_observed_history_status": twm_gate.get("status"),
        "twm_observed_history_missing": twm_gate.get("evidence_gate", {}).get("missing", []),
        "twm_relation_augmented_status": spatial_gate.get("status"),
        "twm_relation_augmented_missing": spatial_gate.get("evidence_gate", {}).get("missing", []),
        "twm_relation_neighbor_edge_count": relation_aug.get("neighbor_edge_count", 0),
        "twm_relation_rows_with_neighbors": relation_aug.get("rows_with_neighbors", 0),
        "twm_relation_structural_status": relation_structural_gate.get("status"),
        "twm_relation_structural_neighbor_edge_count": (relation_structural_gate.get("estimate") or {}).get("spatial", {}).get("neighbor_edge_count", 0),
        "twm_relation_structural_spatial_estimator_status": (relation_structural_gate.get("estimate") or {}).get("spatial_estimator", {}).get("status"),
        "twm_project_review_context_project_count": ((data_audit.get("project_review_context") or {}).get("project_count", 0)),
        "twm_project_review_context_rule_eval_count": ((data_audit.get("project_review_context") or {}).get("total_rule_eval_count", 0)),
        "twm_project_review_context_review_task_count": ((data_audit.get("project_review_context") or {}).get("total_review_task_count", 0)),
        "twm_evidence_augmented_status": evidence_gate.get("status"),
        "twm_evidence_augmented_missing": evidence_gate.get("evidence_gate", {}).get("missing", []),
        "twm_evidence_augmented_rows_with_review_context": ((evidence_gate.get("evidence_augmentation") or {}).get("rows_with_review_context", 0)),
        "twm_evidence_structural_status": evidence_structural_gate.get("status"),
        "twm_evidence_structural_neighbor_edge_count": (evidence_structural_gate.get("estimate") or {}).get("spatial", {}).get("neighbor_edge_count", 0),
        "twm_evidence_structural_mixed_component_clusters": ((evidence_structural_gate.get("evidence_augmentation") or {}).get("mixed_component_cluster_count", 0)),
        "twm_evidence_structural_spatial_estimator_status": (evidence_structural_gate.get("estimate") or {}).get("spatial_estimator", {}).get("status"),
        "twm_evidence_matched_status": evidence_matched_gate.get("status"),
        "twm_evidence_matched_missing": evidence_matched_gate.get("evidence_gate", {}).get("missing", []),
        "twm_evidence_matched_pair_count": (evidence_matched_gate.get("matching") or {}).get("pair_count", 0),
        "twm_evidence_matched_same_component_pair_count": (evidence_matched_gate.get("matching") or {}).get("same_component_cluster_pair_count", 0),
        "twm_evidence_matched_mean_distance": (evidence_matched_gate.get("matching") or {}).get("mean_standardized_distance"),
        "twm_evidence_matched_structural_status": evidence_matched_structural_gate.get("status"),
        "twm_evidence_matched_structural_missing": evidence_matched_structural_gate.get("evidence_gate", {}).get("missing", []),
        "twm_evidence_matched_structural_neighbor_edge_count": (evidence_matched_structural_gate.get("estimate") or {}).get("spatial", {}).get("neighbor_edge_count", 0),
        "twm_evidence_matched_structural_spatial_estimator_status": (evidence_matched_structural_gate.get("estimate") or {}).get("spatial_estimator", {}).get("status"),
        "twm_evidence_matched_structural_balance_max_smd": (
            (evidence_matched_structural_gate.get("estimate") or {}).get("balance") or {}
        ).get("max_abs_standardized_mean_difference"),
        "paper7_status": paper7_gate.get("status"),
        "paper7_missing": paper7_gate.get("evidence_gate", {}).get("missing", []),
        "paper7_observed_effect": (paper7_gate.get("calibration") or {}).get("observed_effect"),
        "paper7_calibration_factor": (paper7_gate.get("calibration") or {}).get("calibration_factor"),
        "paper7_matched_status": paper7_matched_gate.get("status"),
        "paper7_matched_missing": paper7_matched_gate.get("evidence_gate", {}).get("missing", []),
        "paper7_matched_pair_count": (paper7_matched_gate.get("matching") or {}).get("pair_count", 0),
        "paper7_matched_observed_effect": (paper7_matched_gate.get("calibration") or {}).get("observed_effect"),
        "paper7_matched_calibration_factor": (paper7_matched_gate.get("calibration") or {}).get("calibration_factor"),
        "paper7_caliper_matched_status": paper7_caliper_matched_gate.get("status"),
        "paper7_caliper_matched_missing": paper7_caliper_matched_gate.get("evidence_gate", {}).get("missing", []),
        "paper7_caliper_matched_pair_count": (paper7_caliper_matched_gate.get("matching") or {}).get("pair_count", 0),
        "paper7_caliper_matched_caliper": (paper7_caliper_matched_gate.get("matching") or {}).get("caliper_max_standardized_distance"),
        "paper7_caliper_matched_observed_effect": (paper7_caliper_matched_gate.get("calibration") or {}).get("observed_effect"),
        "paper7_caliper_matched_calibration_factor": (paper7_caliper_matched_gate.get("calibration") or {}).get("calibration_factor"),
        "next_data_work": [
            "broaden unseen allowed region/action-policy stress from synthetic mixed-risk fixtures to production-observed policy histories once production labels are available",
            "keep raw learned feasibility-head diagnostics separate from post-hoc context action-mask calibration and transparent-baseline wins",
            "continue replacing post-hoc transformer affine risk calibration with learned risk-head calibration under candidate and holdout MAE gates",
            "improve graph and transformer simulator candidates on planner-consumer rollout regret after adding action-mask context feature channels",
            "use structural-validation fixture only for simulator plumbing regression, not deployment claims",
            "use evidence-augmented matching diagnostics to synthesize harder control records and mixed spatial units",
            "keep default evidence gates conservative while synthetic structural checks drive development progress",
        ],
    }


def write_data_foundation_health_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_data_foundation_health_markdown(report), encoding="utf-8")


def render_data_foundation_health_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    inputs = report.get("inputs") or {}
    outputs = report.get("outputs") or {}
    lines = [
        "# TWM Data Foundation Health",
        "",
        "Generated by `scripts/validate_twm_data_foundation.py`.",
        "",
        "## Scope",
        "",
        "- Renderer data: local TWM tables and relations render GIS operational state.",
        "- Simulator data: observed-history rows, matched rows, structural fixture, synthetic experiment foundation and Paper7 records validate causal/spatial calibration plumbing.",
        "- Planner data: downstream consumers must use these reports as evidence gates; `review` means claims cannot be upgraded.",
        "",
        "## Inputs",
        "",
        f"- TWM dataset: `{inputs.get('twm_dataset')}`",
        f"- Paper7 causal dataset: `{inputs.get('paper7_causal_dataset')}`",
        f"- Production observed history: `{inputs.get('production_observed_history')}`",
        f"- Structural validation observed history: `{inputs.get('structural_validation_observed_history')}`",
        f"- Synthetic experiment foundation: `{inputs.get('synthetic_experiment_foundation')}`",
        "",
        "## Current Assets",
        "",
        "| Asset | Count / Status | Notes |",
        "|---|---:|---|",
    ]
    for name, count in (summary.get("twm_dataset_rows") or {}).items():
        lines.append(f"| `{name}` | {count} | local TWM fixture table |")
    production_policy_alignment_required = summary.get("production_policy_alignment_required") or {}
    lines.extend(
        [
            f"| production-ready observed rows | {summary.get('twm_production_ready_observed_history_rows', 0)} | must be non-synthetic and production-usable |",
            f"| production policy-history rows | {summary.get('production_policy_history_row_count', 0)} | non-synthetic rows with action/policy feasibility fields |",
            f"| production policy allowed/blocked rows | {summary.get('production_policy_history_allowed_count', 0)} / {summary.get('production_policy_history_blocked_count', 0)} | action-mask feasibility labels for real policy validation |",
            f"| production region-policy keys | {summary.get('production_policy_history_region_policy_key_count', 0)} | real region + policy combinations for unseen-policy checks |",
            f"| production region-action-policy keys | {summary.get('production_policy_history_region_action_policy_key_count', 0)} | real region + action + policy combinations |",
            f"| production policy alignment requirement | {production_policy_alignment_required.get('region_policy_key_count', 0)} / {production_policy_alignment_required.get('region_action_policy_key_count', 0)} | synthetic unseen region-policy / region-action-policy key baseline |",
            f"| structural validation fixture rows | {summary.get('twm_structural_fixture_row_count', 0)} | synthetic/not-for-production simulator regression fixture |",
            f"| structural validation fixture pairs | {summary.get('twm_structural_fixture_pair_count', 0)} | balanced treated/control pairs |",
            f"| synthetic experiment rows | {summary.get('twm_synthetic_experiment_row_count', 0)} | multi-region multi-period simulator/planner experiment foundation |",
            f"| synthetic experiment pairs | {summary.get('twm_synthetic_experiment_pair_count', 0)} | counterfactual treated/control pairs |",
            f"| synthetic experiment regions | {summary.get('twm_synthetic_experiment_region_count', 0)} | region-coded holdout support |",
            f"| synthetic experiment periods | {summary.get('twm_synthetic_experiment_period_count', 0)} | temporal train/validation/test support |",
            f"| synthetic holdout periods | {summary.get('twm_synthetic_experiment_holdout_period_count', 0)} | rollout trajectory step coverage per region |",
            f"| synthetic holdout oracle action types | {summary.get('twm_synthetic_experiment_holdout_oracle_action_type_count', 0)} | planner-consumer action diversity check |",
            f"| synthetic action-mask allowed rows | {summary.get('twm_synthetic_experiment_action_mask_allowed_count', 0)} | action feasibility positives for simulator safety head |",
            f"| synthetic action-mask blocked rows | {summary.get('twm_synthetic_experiment_action_mask_blocked_count', 0)} | blocked/review labels for simulator safety head |",
            f"| synthetic mixed action-mask types | {len(summary.get('twm_synthetic_experiment_mixed_action_mask_action_types') or [])} | action types with both allowed and blocked examples |",
            f"| evidence-augmented matched pairs | {summary.get('twm_evidence_matched_pair_count', 0)} | local demo matching diagnostic |",
            f"| Paper7 caliper-matched pairs | {summary.get('paper7_caliper_matched_pair_count', 0)} | external empirical validation branch |",
            "",
            "## Gate Summary",
            "",
            "| Gate | Status | Missing / Key Evidence |",
            "|---|---|---|",
            _markdown_gate_row("Local observed history", summary.get("twm_observed_history_status"), summary.get("twm_observed_history_missing")),
            _markdown_gate_row("Production policy history", summary.get("production_policy_history_status"), summary.get("production_policy_history_missing")),
            _markdown_gate_row("Production policy alignment", summary.get("production_policy_alignment_status"), summary.get("production_policy_alignment_missing")),
            _markdown_gate_row("Structural fixture default", summary.get("twm_structural_fixture_default_status"), summary.get("twm_structural_fixture_default_missing")),
            _markdown_gate_row("Structural fixture structural check", summary.get("twm_structural_fixture_structural_status"), summary.get("twm_structural_fixture_structural_missing")),
            _markdown_gate_row("Synthetic experiment default", summary.get("twm_synthetic_experiment_default_status"), summary.get("twm_synthetic_experiment_default_missing")),
            _markdown_gate_row("Synthetic experiment structural check", summary.get("twm_synthetic_experiment_structural_status"), summary.get("twm_synthetic_experiment_structural_missing")),
            _markdown_gate_row("Relation augmented structural check", summary.get("twm_relation_structural_status"), [f"neighbor_edges={summary.get('twm_relation_structural_neighbor_edge_count', 0)}", f"spatial_estimator={summary.get('twm_relation_structural_spatial_estimator_status')}"]),
            _markdown_gate_row("Evidence matched structural check", summary.get("twm_evidence_matched_structural_status"), summary.get("twm_evidence_matched_structural_missing")),
            _markdown_gate_row("Paper7 caliper matched", summary.get("paper7_caliper_matched_status"), summary.get("paper7_caliper_matched_missing")),
            "",
            "## Structural Fixture",
            "",
            f"- Path: `{outputs.get('structural_validation_observed_history')}`",
            f"- Default gate: `{summary.get('twm_structural_fixture_default_status')}`.",
            f"- Structural check: `{summary.get('twm_structural_fixture_structural_status')}`.",
            f"- Structural neighbor edges: `{summary.get('twm_structural_fixture_structural_neighbor_edge_count', 0)}`.",
            f"- Structural spatial estimator: `{summary.get('twm_structural_fixture_structural_spatial_estimator_status')}`.",
            f"- Structural max covariate SMD: `{summary.get('twm_structural_fixture_structural_balance_max_smd')}`.",
            "",
            "This fixture is intentionally `synthetic=True` and `not_for_production=True`. It is only for simulator plumbing regression.",
            "",
            "## Synthetic Experiment Foundation",
            "",
            f"- Path: `{outputs.get('synthetic_experiment_foundation')}`",
            f"- Default gate: `{summary.get('twm_synthetic_experiment_default_status')}`.",
            f"- Structural check: `{summary.get('twm_synthetic_experiment_structural_status')}`.",
            f"- Structural neighbor edges: `{summary.get('twm_synthetic_experiment_structural_neighbor_edge_count', 0)}`.",
            f"- Structural spatial estimator: `{summary.get('twm_synthetic_experiment_structural_spatial_estimator_status')}`.",
            f"- Structural max covariate SMD: `{summary.get('twm_synthetic_experiment_structural_balance_max_smd')}`.",
            f"- Split counts: `{summary.get('twm_synthetic_experiment_split_counts', {})}`.",
            f"- Holdout oracle action counts: `{summary.get('twm_synthetic_experiment_holdout_oracle_action_counts', {})}`.",
            f"- Holdout oracle groups: `{summary.get('twm_synthetic_experiment_holdout_oracle_group_count', 0)}`.",
            f"- Action-mask allowed/blocked rows: `{summary.get('twm_synthetic_experiment_action_mask_allowed_count', 0)}` / `{summary.get('twm_synthetic_experiment_action_mask_blocked_count', 0)}`.",
            f"- Mixed action-mask action types: `{summary.get('twm_synthetic_experiment_mixed_action_mask_action_types', [])}`.",
            f"- Action-mask counts by action type: `{summary.get('twm_synthetic_experiment_action_mask_counts_by_action_type', {})}`.",
            "",
            "This foundation is designed for TWM development experiments: simulator training, holdout validation, planner-consumer rollouts and action-mask safety generalization checks.",
            "",
            "## Claim Boundary",
            "",
            "- Synthetic rows can drive development, regression and ablation experiments.",
            "- Default evidence gates remain conservative, so deployment-level claim promotion still requires an explicit gate pass.",
            "- Structural checks are used to verify renderer/simulator/planner plumbing and causal/spatial diagnostics.",
            "- Production policy-history checks only validate that real action-mask labels exist for feasibility testing; they do not prove simulator accuracy by themselves.",
            "- Production policy alignment compares real policy-history coverage with the synthetic unseen-policy fixture; it is a data-readiness gate, not a model-accuracy gate.",
            "",
            "## Next Data Work",
            "",
        ]
    )
    for item in summary.get("next_data_work") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- JSON report: `{outputs.get('report')}`",
            f"- Markdown report: `{outputs.get('markdown_report')}`",
            f"- Production observed-history template: `{outputs.get('production_observed_history_template')}`",
            f"- Structural validation observed history: `{outputs.get('structural_validation_observed_history')}`",
            f"- Synthetic experiment foundation: `{outputs.get('synthetic_experiment_foundation')}`",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown_gate_row(label: str, status: Any, missing: Any) -> str:
    if isinstance(missing, list):
        detail = ", ".join(str(item) for item in missing) if missing else "none"
    elif missing in (None, ""):
        detail = "none"
    else:
        detail = str(missing)
    return f"| {label} | `{status}` | {detail} |"


def _causal_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    estimate = report.get("estimate") or {}
    spatial_estimator = estimate.get("spatial_estimator") or {}
    inventory = (report.get("provenance") or {}).get("record_inventory") or {}
    return {
        "schema": report.get("schema"),
        "status": report.get("status"),
        "record_source": (report.get("provenance") or {}).get("record_source"),
        "record_inventory": inventory,
        "estimate": {
            "att": estimate.get("att"),
            "standard_error": estimate.get("standard_error"),
            "treated_count": estimate.get("treated_count"),
            "control_count": estimate.get("control_count"),
            "usable_record_count": estimate.get("usable_record_count"),
            "raw_record_count": estimate.get("raw_record_count"),
            "estimator": estimate.get("estimator"),
            "overlap": estimate.get("overlap"),
            "balance": {
                "status": (estimate.get("balance") or {}).get("status"),
                "covariate_count": (estimate.get("balance") or {}).get("covariate_count"),
                "max_abs_standardized_mean_difference": (estimate.get("balance") or {}).get("max_abs_standardized_mean_difference"),
            },
            "spatial": estimate.get("spatial"),
            "spatial_estimator": {
                "status": spatial_estimator.get("status"),
                "effect": spatial_estimator.get("effect"),
                "standard_error": spatial_estimator.get("standard_error"),
                "support": spatial_estimator.get("support"),
                "review_reasons": spatial_estimator.get("review_reasons"),
                "uncertainty": spatial_estimator.get("uncertainty"),
            },
        },
        "calibration": report.get("calibration"),
        "evidence_gate": report.get("evidence_gate"),
        "recommendations": report.get("recommendations"),
    }


def _build_validation_service() -> TerritoryWorldModelService:
    return TerritoryWorldModelService(repository=TwmRepository(engine=None, persist_to_db=False))


def _create_minimal_state(svc: TerritoryWorldModelService) -> str:
    project = svc.create_project(
        {
            "name": "TWM Data Foundation Validation",
            "region_code": "500227",
            "business_scenario": "planning_supervision",
        },
        username="data-validation",
    )
    state = TwmStateVersion(
        project_id=project["id"],
        label="minimal causal validation state",
        object_count=0,
        relation_count=0,
        quality_summary={"evidence_coverage": 1.0},
        build_status="ready",
        summary={"object_counts_by_role": {}, "relation_counts_by_type": {}},
    )
    svc.repository.save_state_version(state)
    return state.id


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _mean_numeric_field(rows: list[dict[str, Any]], field: str, *, default: float) -> float:
    values = [safe_float(row.get(field), None) for row in rows]
    numeric = [float(value) for value in values if value is not None]
    return sum(numeric) / len(numeric) if numeric else float(default)


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    main()
