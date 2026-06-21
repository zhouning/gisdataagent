#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.territory_world_model import TerritoryWorldModelService, TwmRepository, jsonable, now_utc_iso
from data_agent.territory_world_model.utils import read_json


DEFAULT_BUNDLE_DIR = REPO_ROOT / "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion"
DEFAULT_OPTIMIZATION_DIR = REPO_ROOT / "data_agent/test_data/twm_bishan_demo/optimization"
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_validation_bundle.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs/reports/twm_validation_bundle.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an offline/inner-network TWM validation bundle from local MMFE and optimization artifacts."
    )
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR), help="MMFE semantic bundle directory for TWM state build.")
    parser.add_argument("--optimization-dir", default=str(DEFAULT_OPTIMIZATION_DIR), help="Optional optimization bundle directory.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON validation bundle output path.")
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT), help="Markdown summary output path.")
    parser.add_argument("--project-name", default="TWM Offline Validation Bundle", help="Project name for this validation run.")
    parser.add_argument("--region-code", default="500227", help="Region/admin code for the validation project.")
    parser.add_argument("--scenario", default="offline_validation_bundle", help="Scenario label for planning and validation.")
    parser.add_argument("--horizon", type=int, default=3, help="Counterfactual rollout horizon.")
    parser.add_argument("--scca-output-dir", default="", help="Optional SCCA output directory or manifest path.")
    parser.add_argument("--scca-result-json", default="", help="Optional SCCA result JSON payload path.")
    parser.add_argument("--require-scca-pass", action="store_true", help="Require passing SCCA evidence before spatial causal claim promotion.")
    parser.add_argument("--include-auxiliary-tables", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-write-markdown", action="store_true", help="Skip Markdown output.")
    args = parser.parse_args()

    report = run_validation_bundle(
        bundle_dir=Path(args.bundle_dir).expanduser(),
        optimization_dir=Path(args.optimization_dir).expanduser() if args.optimization_dir else None,
        project_name=args.project_name,
        region_code=args.region_code,
        scenario=args.scenario,
        horizon=max(1, int(args.horizon or 1)),
        scca_output_dir=Path(args.scca_output_dir).expanduser() if args.scca_output_dir else None,
        scca_result_json=Path(args.scca_result_json).expanduser() if args.scca_result_json else None,
        require_scca_pass=bool(args.require_scca_pass),
        include_auxiliary_tables=bool(args.include_auxiliary_tables),
    )

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if not args.no_write_markdown:
        markdown_output = Path(args.markdown_output).expanduser()
        write_validation_bundle_markdown(markdown_output, report)
    print(f"wrote {output}")
    if not args.no_write_markdown:
        print(f"wrote {Path(args.markdown_output).expanduser()}")


def run_validation_bundle(
    *,
    bundle_dir: Path | str = DEFAULT_BUNDLE_DIR,
    optimization_dir: Path | str | None = DEFAULT_OPTIMIZATION_DIR,
    project_name: str = "TWM Offline Validation Bundle",
    region_code: str = "500227",
    scenario: str = "offline_validation_bundle",
    horizon: int = 3,
    scca_output_dir: Path | str | None = None,
    scca_result_json: Path | str | None = None,
    require_scca_pass: bool = False,
    include_auxiliary_tables: bool = True,
    service: TerritoryWorldModelService | None = None,
) -> dict[str, Any]:
    bundle_path = Path(bundle_dir).expanduser()
    optimization_path = Path(optimization_dir).expanduser() if optimization_dir else None
    scca_output_path = Path(scca_output_dir).expanduser() if scca_output_dir else None
    scca_json_path = Path(scca_result_json).expanduser() if scca_result_json else None

    svc = service or build_offline_validation_service()
    project = svc.create_project(
        {
            "name": project_name,
            "region_code": region_code,
            "business_scenario": "planning_supervision",
            "metadata": {
                "validation_runner": "scripts/run_twm_validation_bundle.py",
                "offline_inner_network_ready": True,
            },
        },
        username="twm-offline-validation",
    )
    state_result = svc.build_state(
        project["id"],
        {
            "bundle_dir": str(bundle_path),
            "label": f"{scenario}: state build",
            "include_auxiliary_tables": include_auxiliary_tables,
        },
    )
    state = state_result["state_version"]
    state_id = state["id"]
    default_rules = svc.ensure_default_rules()
    rule_evaluation = svc.evaluate_rules(state_id, {"include_default_rules": True})
    audit = svc.generate_audit_report(state_id)

    evidence_coverage = (state.get("quality_summary") or {}).get("evidence_coverage")
    if evidence_coverage is None:
        evidence_coverage = 0.85
    selected_plan_payload: dict[str, Any] = {
        "scenario": scenario,
        "horizon": max(1, int(horizon or 1)),
        "evidence_coverage": evidence_coverage,
        "require_scca_pass": bool(require_scca_pass),
    }
    if optimization_path is not None:
        selected_plan_payload["optimization_dir"] = str(optimization_path)

    scca_report = build_scca_report_if_requested(
        svc,
        state_id,
        scca_output_dir=scca_output_path,
        scca_result_json=scca_json_path,
    )
    if scca_report:
        selected_plan_payload["scca_causal_evidence_report"] = scca_report

    selected_bundle = svc.selected_plan_evaluation_bundle(state_id, selected_plan_payload)
    validation_report = selected_bundle.get("validation_report") or {}
    claim_ladder = ((validation_report.get("summary") or {}).get("claim_ladder") or {})

    report = {
        "schema": "territory_world_model.validation_bundle.v1",
        "created_at": now_utc_iso(),
        "status": validation_bundle_status(selected_bundle, validation_report),
        "inputs": {
            "bundle_dir": str(bundle_path),
            "optimization_dir": str(optimization_path) if optimization_path else None,
            "scca_output_dir": str(scca_output_path) if scca_output_path else None,
            "scca_result_json": str(scca_json_path) if scca_json_path else None,
            "require_scca_pass": bool(require_scca_pass),
            "include_auxiliary_tables": bool(include_auxiliary_tables),
            "scenario": scenario,
            "horizon": max(1, int(horizon or 1)),
            "evidence_coverage": evidence_coverage,
        },
        "project": sanitize_project(project),
        "state_summary": summarize_state_result(state_result),
        "rule_summary": summarize_rule_evaluation(rule_evaluation, default_rules),
        "audit_summary": summarize_audit(audit),
        "selected_plan_evaluation_bundle": sanitize_selected_plan_bundle(selected_bundle),
        "validation_summary": summarize_validation_report(validation_report),
        "claim_ladder": summarize_claim_ladder(claim_ladder),
        "scca_summary": summarize_scca_report(scca_report, require_scca_pass=require_scca_pass),
        "sanitized_export_policy": sanitized_export_policy(),
        "claim_boundary": {
            "production_accuracy_claim": "not_supported_until_real_authoritative_observed_history_holdout_validation_passes",
            "offline_validation_claim": "supports inner-network repeatable smoke/regression validation of the current TWM pipeline",
            "raw_data_policy": "raw objects, geometries and row-level attributes are not exported by this report",
        },
        "recommendations": validation_bundle_recommendations(selected_bundle, validation_report, scca_report, require_scca_pass),
    }
    return jsonable(report)


def build_offline_validation_service() -> TerritoryWorldModelService:
    return TerritoryWorldModelService(repository=TwmRepository(engine=None, persist_to_db=False))


def build_scca_report_if_requested(
    svc: TerritoryWorldModelService,
    state_id: str,
    *,
    scca_output_dir: Path | None = None,
    scca_result_json: Path | None = None,
) -> dict[str, Any]:
    if scca_output_dir is None and scca_result_json is None:
        return {}
    payload: dict[str, Any] = {"thresholds": {"min_row_count": 80}}
    if scca_output_dir is not None:
        payload["scca_output_dir"] = str(scca_output_dir)
    if scca_result_json is not None:
        payload["scca_result"] = read_json(scca_result_json)
    return svc.scca_causal_evidence_report(state_id, payload)


def validation_bundle_status(selected_bundle: dict[str, Any], validation_report: dict[str, Any]) -> str:
    if selected_bundle.get("status") == "blocked" or validation_report.get("overall_status") == "blocked":
        return "blocked"
    if selected_bundle.get("status") == "pass" and validation_report.get("overall_status") == "pass":
        return "pass"
    return "review"


def sanitize_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "region_code": project.get("region_code"),
        "business_scenario": project.get("business_scenario"),
        "status": project.get("status"),
    }


def summarize_state_result(state_result: dict[str, Any]) -> dict[str, Any]:
    state = state_result.get("state_version") or {}
    summary = state.get("summary") or {}
    quality = state.get("quality_summary") or {}
    source_manifest = state.get("source_manifest") or {}
    semantic_product = source_manifest.get("semantic_product") or {}
    state_input = source_manifest.get("state_input") or {}
    production_policy = state_input.get("production_policy") or {}
    return {
        "state_version_id": state.get("id"),
        "project_id": state.get("project_id"),
        "label": state.get("label"),
        "build_status": state.get("build_status"),
        "object_count": state.get("object_count", 0),
        "relation_count": state.get("relation_count", 0),
        "object_counts_by_role": summary.get("object_counts_by_role") or {},
        "relation_counts_by_type": summary.get("relation_counts_by_type") or {},
        "metric_crs": summary.get("metric_crs"),
        "quality_summary": {
            "evidence_coverage": quality.get("evidence_coverage"),
            "manifest_quality_score": quality.get("manifest_quality_score"),
            "synthetic_object_count": quality.get("synthetic_object_count"),
            "not_for_production_object_count": quality.get("not_for_production_object_count"),
            "qa_disabled_object_count": quality.get("qa_disabled_object_count"),
        },
        "semantic_product": {
            "product_id": semantic_product.get("product_id"),
            "product_type": semantic_product.get("product_type"),
            "version": semantic_product.get("version"),
        },
        "production_policy": {
            "contains_synthetic_sources": production_policy.get("contains_synthetic_sources"),
            "not_for_production": production_policy.get("not_for_production"),
            "authoritative_data_required_for_production": production_policy.get("authoritative_data_required_for_production"),
        },
        "warnings": list(state_result.get("warnings") or []),
    }


def summarize_rule_evaluation(rule_evaluation: dict[str, Any], default_rules: dict[str, Any]) -> dict[str, Any]:
    summary = rule_evaluation.get("summary") or {}
    return {
        "rule_set_id": (default_rules.get("rule_set") or {}).get("id"),
        "default_rule_count": len(default_rules.get("rules") or []),
        "evaluated_rule_count": summary.get("rule_count", 0),
        "hit_count": summary.get("hit_count", 0),
        "review_task_count": summary.get("review_task_count", 0),
        "evidence_item_count": summary.get("evidence_item_count", 0),
        "severity_distribution": summary.get("severity_distribution") or {},
        "warnings": list(summary.get("warnings") or []),
    }


def summarize_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_hit_count": audit.get("rule_hit_count", 0),
        "confirmed_count": audit.get("confirmed_count", 0),
        "dismissed_count": audit.get("dismissed_count", 0),
        "mitigation_count": audit.get("mitigation_count", 0),
        "evidence_gate_passed": audit.get("evidence_gate_passed"),
        "evidence_gate_summary": audit.get("evidence_gate_summary") or {},
        "rule_summary": audit.get("rule_summary") or {},
    }


def sanitize_selected_plan_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    selected = bundle.get("selected") or {}
    planning = bundle.get("planning") or {}
    beam_plan = planning.get("beam_plan") or {}
    rollout = bundle.get("counterfactual_rollout") or {}
    final_delta = (rollout.get("deltas") or {}).get("final") or {}
    return {
        "schema": bundle.get("schema"),
        "status": bundle.get("status"),
        "source": bundle.get("source") or {},
        "selected": {
            "candidate_id": selected.get("candidate_id"),
            "rank": selected.get("rank"),
            "rank_score": selected.get("rank_score"),
            "utility": selected.get("utility"),
            "risk": selected.get("risk"),
            "confidence": selected.get("confidence"),
            "claim_status": selected.get("claim_status"),
            "selection_status": selected.get("selection_status"),
            "evidence_gate_status": (selected.get("evidence_gate") or {}).get("status"),
            "action": sanitize_action(selected.get("action") or {}),
        },
        "planning_summary": {
            "schema": planning.get("schema"),
            "status": planning.get("status"),
            "scenario": planning.get("scenario"),
            "candidate_count": len((beam_plan.get("candidates") or [])),
            "ranking_count": len((beam_plan.get("ranking") or [])),
            "eligible_candidate_count": (planning.get("selection_audit") or {}).get("eligible_candidate_count"),
            "selected_from_legal_feasible_space": (planning.get("selection_audit") or {}).get("selected_from_legal_feasible_space"),
            "optimization_bundle": summarize_optimization_bundle(planning.get("optimization_bundle") or {}),
        },
        "rollout_summary": {
            "status": rollout.get("status"),
            "horizon": rollout.get("horizon"),
            "step_count": len(rollout.get("steps") or []),
            "final_delta": final_delta,
            "evidence_gate": rollout.get("evidence_gate") or {},
        },
        "evidence_gate": bundle.get("evidence_gate") or {},
        "claim_boundary": bundle.get("claim_boundary") or {},
        "recommendations": list(bundle.get("recommendations") or []),
        "created_at": bundle.get("created_at"),
    }


def sanitize_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_type": action.get("action_type"),
        "target_role": action.get("target_role"),
        "magnitude": action.get("magnitude"),
        "scenario": action.get("scenario"),
        "description": action.get("description"),
        "legal_intent": action.get("legal_intent"),
        "execution_mask": action.get("execution_mask") or {},
    }


def summarize_optimization_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": bundle.get("schema"),
        "status": bundle.get("status"),
        "optimization_dir": bundle.get("optimization_dir"),
        "summary": bundle.get("summary") or {},
        "optimizer_evidence": {
            "algorithm_family": (bundle.get("optimizer_evidence") or {}).get("algorithm_family"),
            "validation": (bundle.get("optimizer_evidence") or {}).get("validation") or {},
            "pareto_summary": (bundle.get("optimizer_evidence") or {}).get("pareto_summary") or {},
        },
    }


def summarize_validation_report(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") or {}
    return {
        "overall_status": report.get("overall_status"),
        "stage_count": summary.get("stage_count", 0),
        "passed_stage_count": summary.get("passed_stage_count", 0),
        "review_stage_count": summary.get("review_stage_count", 0),
        "blocked_stage_count": summary.get("blocked_stage_count", 0),
        "validation_ladder": list(summary.get("validation_ladder") or []),
        "blocking_gaps": list(summary.get("blocking_gaps") or []),
        "stages": [
            {
                "stage_code": stage.get("stage_code"),
                "title": stage.get("title"),
                "status": stage.get("status"),
                "metrics": stage.get("metrics") or {},
                "gaps": list(stage.get("gaps") or []),
                "evidence_summary": summarize_stage_evidence(stage.get("evidence") or {}),
            }
            for stage in report.get("stages") or []
        ],
    }


def summarize_stage_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "required",
        "provided",
        "evidence_item_count",
        "review_task_count",
        "rule_hit_count",
        "required_review_count",
        "allowed",
        "status",
    ]
    summary = {key: evidence.get(key) for key in keys if key in evidence}
    if "evidence_gate" in evidence and isinstance(evidence["evidence_gate"], dict):
        summary["evidence_gate_status"] = evidence["evidence_gate"].get("status")
        summary["evidence_gate_missing"] = list(evidence["evidence_gate"].get("missing") or [])
    if "calibration_hint" in evidence and isinstance(evidence["calibration_hint"], dict):
        summary["can_support_twm_causal_calibration"] = evidence["calibration_hint"].get("can_support_twm_causal_calibration")
    if "scca_missing" in evidence:
        summary["scca_missing"] = list(evidence.get("scca_missing") or [])
    return summary


def summarize_claim_ladder(claim_ladder: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": claim_ladder.get("schema"),
        "current_level": claim_ladder.get("current_level"),
        "current_claim": claim_ladder.get("current_claim"),
        "level_status": {
            item.get("level"): item.get("status")
            for item in claim_ladder.get("levels") or []
            if isinstance(item, dict) and item.get("level")
        },
        "next_level": claim_ladder.get("next_level"),
        "blocking_requirements": list(claim_ladder.get("blocking_requirements") or []),
    }


def summarize_scca_report(report: dict[str, Any], *, require_scca_pass: bool) -> dict[str, Any]:
    if not report:
        return {
            "required": bool(require_scca_pass),
            "provided": False,
            "status": "missing_required" if require_scca_pass else "not_provided",
            "evidence_gate_status": "missing_required" if require_scca_pass else "not_provided",
        }
    return {
        "required": bool(require_scca_pass),
        "provided": True,
        "schema": report.get("schema"),
        "status": report.get("status"),
        "evidence_gate_status": (report.get("evidence_gate") or {}).get("status"),
        "missing": list((report.get("evidence_gate") or {}).get("missing") or []),
        "effect": report.get("effect") or {},
        "balance": report.get("balance") or {},
        "spatial_diagnostics": report.get("spatial_diagnostics") or {},
        "calibration_hint": report.get("calibration_hint") or {},
    }


def sanitized_export_policy() -> dict[str, Any]:
    return {
        "schema": "territory_world_model.sanitized_export_policy.v1",
        "exports_raw_geometries": False,
        "exports_raw_state_objects": False,
        "exports_raw_row_attributes": False,
        "exports_source_file_contents": False,
        "allowed_content": [
            "counts",
            "stage statuses",
            "evidence gate summaries",
            "selected candidate summary",
            "claim ladder state",
            "recommendations",
        ],
        "intended_use": "air-gapped validation feedback and non-sensitive progress reporting",
    }


def validation_bundle_recommendations(
    selected_bundle: dict[str, Any],
    validation_report: dict[str, Any],
    scca_report: dict[str, Any],
    require_scca_pass: bool,
) -> list[str]:
    recommendations: list[str] = []
    recommendations.extend(str(item) for item in selected_bundle.get("recommendations") or [])
    blocking_gaps = (validation_report.get("summary") or {}).get("blocking_gaps") or []
    if blocking_gaps:
        recommendations.append("resolve validation blocking/review gaps before promoting the selected plan claim")
    if require_scca_pass and not scca_report:
        recommendations.append("provide SCCA causal evidence output or disable require_scca_pass for non-causal offline smoke validation")
    if scca_report and (scca_report.get("evidence_gate") or {}).get("status") != "pass":
        recommendations.append("keep spatial causal claims in review until the SCCA evidence gate passes")
    recommendations.append("replace demo/not-for-production data with authoritative observed history before claiming production accuracy")
    return sorted(dict.fromkeys(recommendations))


def write_validation_bundle_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_validation_bundle_markdown(report), encoding="utf-8")


def render_validation_bundle_markdown(report: dict[str, Any]) -> str:
    inputs = report.get("inputs") or {}
    state = report.get("state_summary") or {}
    rules = report.get("rule_summary") or {}
    audit = report.get("audit_summary") or {}
    selected = report.get("selected_plan_evaluation_bundle") or {}
    validation = report.get("validation_summary") or {}
    claim = report.get("claim_ladder") or {}
    scca = report.get("scca_summary") or {}
    lines = [
        "# TWM Offline Validation Bundle",
        "",
        "Generated by `scripts/run_twm_validation_bundle.py`.",
        "",
        "## Scope",
        "",
        "- Purpose: run the current TWM renderer, simulator, planner, evidence gate and validation ladder from local or inner-network artifacts.",
        "- Boundary: this is a repeatable validation bundle, not a production accuracy certificate.",
        "- Export policy: raw geometries, state objects and row-level attributes are intentionally excluded.",
        "",
        "## Inputs",
        "",
        f"- MMFE bundle: `{inputs.get('bundle_dir')}`",
        f"- Optimization bundle: `{inputs.get('optimization_dir')}`",
        f"- Scenario: `{inputs.get('scenario')}`",
        f"- Require SCCA pass: `{inputs.get('require_scca_pass')}`",
        f"- SCCA output: `{inputs.get('scca_output_dir') or inputs.get('scca_result_json')}`",
        "",
        "## State Build",
        "",
        f"- Status: `{state.get('build_status')}`",
        f"- Objects: `{state.get('object_count', 0)}`",
        f"- Relations: `{state.get('relation_count', 0)}`",
        f"- Metric CRS: `{state.get('metric_crs')}`",
        f"- Evidence coverage used by validation: `{inputs.get('evidence_coverage')}`",
        f"- Manifest quality score: `{(state.get('quality_summary') or {}).get('manifest_quality_score')}`",
        f"- Not-for-production objects: `{(state.get('quality_summary') or {}).get('not_for_production_object_count')}`",
        "",
        "## Rules And Audit",
        "",
        f"- Evaluated rules: `{rules.get('evaluated_rule_count', 0)}`",
        f"- Rule hits: `{rules.get('hit_count', 0)}`",
        f"- Review tasks: `{rules.get('review_task_count', 0)}`",
        f"- Evidence items: `{rules.get('evidence_item_count', 0)}`",
        f"- Severity distribution: `{rules.get('severity_distribution', {})}`",
        f"- Audit evidence gate passed: `{audit.get('evidence_gate_passed')}`",
        "",
        "## Selected Plan",
        "",
        f"- Bundle status: `{selected.get('status')}`",
        f"- Selected candidate: `{((selected.get('selected') or {}).get('candidate_id'))}`",
        f"- Rank score: `{((selected.get('selected') or {}).get('rank_score'))}`",
        f"- Evidence gate: `{(selected.get('evidence_gate') or {}).get('status')}`",
        f"- Selected from legal feasible space: `{((selected.get('planning_summary') or {}).get('selected_from_legal_feasible_space'))}`",
        f"- Candidate count: `{((selected.get('planning_summary') or {}).get('candidate_count'))}`",
        "",
        "## Validation Ladder",
        "",
        f"- Overall status: `{validation.get('overall_status')}`",
        f"- Stages: `{validation.get('passed_stage_count', 0)}` pass / `{validation.get('review_stage_count', 0)}` review / `{validation.get('blocked_stage_count', 0)}` blocked",
        f"- Claim level: `{claim.get('current_level')}` (`{claim.get('current_claim')}`)",
        f"- SCCA: required=`{scca.get('required')}`, provided=`{scca.get('provided')}`, status=`{scca.get('status')}`",
        "",
        "| Stage | Status | Key Gaps |",
        "|---|---|---|",
    ]
    for stage in validation.get("stages") or []:
        gaps = ", ".join(str(item) for item in stage.get("gaps") or []) or "none"
        lines.append(f"| `{stage.get('stage_code')}` | `{stage.get('status')}` | {gaps} |")
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            f"- Production accuracy claim: `{(report.get('claim_boundary') or {}).get('production_accuracy_claim')}`",
            f"- Offline validation claim: `{(report.get('claim_boundary') or {}).get('offline_validation_claim')}`",
            "",
            "## Recommendations",
            "",
        ]
    )
    for item in report.get("recommendations") or []:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
