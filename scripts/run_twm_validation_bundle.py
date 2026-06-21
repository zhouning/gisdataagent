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
from data_agent.territory_world_model.utils import read_csv, read_json
from scripts.validate_twm_data_foundation import (
    audit_observed_history_schema,
    production_policy_history_alignment,
    synthetic_experiment_foundation_summary,
)


DEFAULT_BUNDLE_DIR = REPO_ROOT / "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion"
DEFAULT_OPTIMIZATION_DIR = REPO_ROOT / "data_agent/test_data/twm_bishan_demo/optimization"
DEFAULT_SYNTHETIC_EXPERIMENT_FOUNDATION = REPO_ROOT / "docs/reports/twm_synthetic_experiment_foundation.csv"
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_validation_bundle.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs/reports/twm_validation_bundle.md"
DEFAULT_SCALE_PROFILE_TEMPLATE = REPO_ROOT / "docs/reports/twm_production_scale_profile_template.json"


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
    parser.add_argument("--production-observed-history", default="", help="Optional real non-synthetic observed approval/review history CSV.")
    parser.add_argument("--synthetic-experiment-foundation", default=str(DEFAULT_SYNTHETIC_EXPERIMENT_FOUNDATION), help="Synthetic experiment CSV used only as a policy-coverage benchmark.")
    parser.add_argument("--production-scale-profile", default="", help="Optional JSON profile describing real layer/table scale and distributed lakehouse readiness.")
    parser.add_argument("--scale-profile-template-output", default=str(DEFAULT_SCALE_PROFILE_TEMPLATE), help="JSON template output path for sanitized production scale profiles.")
    parser.add_argument("--require-production-readiness", action="store_true", help="Promote missing production evidence from review-only diagnostics to a blocked readiness gate.")
    parser.add_argument("--fail-on-blocked", action="store_true", help="Exit non-zero after writing outputs when the validation bundle status is blocked.")
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
        production_observed_history=Path(args.production_observed_history).expanduser() if args.production_observed_history else None,
        synthetic_experiment_foundation=Path(args.synthetic_experiment_foundation).expanduser() if args.synthetic_experiment_foundation else None,
        production_scale_profile=Path(args.production_scale_profile).expanduser() if args.production_scale_profile else None,
        require_production_readiness=bool(args.require_production_readiness),
        include_auxiliary_tables=bool(args.include_auxiliary_tables),
    )

    scale_template_output = Path(args.scale_profile_template_output).expanduser() if args.scale_profile_template_output else None
    if scale_template_output is not None:
        write_production_scale_profile_template(scale_template_output)
        report["outputs"] = {
            **(report.get("outputs") or {}),
            "production_scale_profile_template": str(scale_template_output),
        }

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if not args.no_write_markdown:
        markdown_output = Path(args.markdown_output).expanduser()
        write_validation_bundle_markdown(markdown_output, report)
    print(f"wrote {output}")
    if not args.no_write_markdown:
        print(f"wrote {Path(args.markdown_output).expanduser()}")
    exit_code = validation_bundle_exit_code(
        report,
        fail_on_blocked=bool(args.fail_on_blocked or args.require_production_readiness),
    )
    if exit_code:
        raise SystemExit(exit_code)


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
    production_observed_history: Path | str | None = None,
    synthetic_experiment_foundation: Path | str | None = DEFAULT_SYNTHETIC_EXPERIMENT_FOUNDATION,
    production_scale_profile: Path | str | None = None,
    require_production_readiness: bool = False,
    include_auxiliary_tables: bool = True,
    service: TerritoryWorldModelService | None = None,
) -> dict[str, Any]:
    bundle_path = Path(bundle_dir).expanduser()
    optimization_path = Path(optimization_dir).expanduser() if optimization_dir else None
    scca_output_path = Path(scca_output_dir).expanduser() if scca_output_dir else None
    scca_json_path = Path(scca_result_json).expanduser() if scca_result_json else None
    production_history_path = Path(production_observed_history).expanduser() if production_observed_history else None
    synthetic_foundation_path = Path(synthetic_experiment_foundation).expanduser() if synthetic_experiment_foundation else None
    scale_profile_path = Path(production_scale_profile).expanduser() if production_scale_profile else None

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
    state_summary = summarize_state_result(state_result)

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
    production_preflight = build_production_observed_history_preflight(
        production_observed_history=production_history_path,
        synthetic_experiment_foundation=synthetic_foundation_path,
    )
    scale_readiness = build_production_scale_readiness(
        production_scale_profile=scale_profile_path,
        state_summary=state_summary,
    )
    readiness_gate = build_production_readiness_gate(
        selected_bundle=selected_bundle,
        validation_report=validation_report,
        claim_ladder=claim_ladder,
        production_preflight=production_preflight,
        production_scale_readiness=scale_readiness,
        scca_report=scca_report,
        require_scca_pass=require_scca_pass,
        require_production_readiness=require_production_readiness,
    )

    report = {
        "schema": "territory_world_model.validation_bundle.v1",
        "created_at": now_utc_iso(),
        "status": validation_bundle_status(selected_bundle, validation_report, production_preflight, readiness_gate),
        "inputs": {
            "bundle_dir": str(bundle_path),
            "optimization_dir": str(optimization_path) if optimization_path else None,
            "scca_output_dir": str(scca_output_path) if scca_output_path else None,
            "scca_result_json": str(scca_json_path) if scca_json_path else None,
            "production_observed_history": str(production_history_path) if production_history_path else None,
            "synthetic_experiment_foundation": str(synthetic_foundation_path) if synthetic_foundation_path else None,
            "production_scale_profile": str(scale_profile_path) if scale_profile_path else None,
            "require_scca_pass": bool(require_scca_pass),
            "require_production_readiness": bool(require_production_readiness),
            "include_auxiliary_tables": bool(include_auxiliary_tables),
            "scenario": scenario,
            "horizon": max(1, int(horizon or 1)),
            "evidence_coverage": evidence_coverage,
        },
        "project": sanitize_project(project),
        "state_summary": state_summary,
        "rule_summary": summarize_rule_evaluation(rule_evaluation, default_rules),
        "audit_summary": summarize_audit(audit),
        "selected_plan_evaluation_bundle": sanitize_selected_plan_bundle(selected_bundle),
        "validation_summary": summarize_validation_report(validation_report),
        "claim_ladder": summarize_claim_ladder(claim_ladder),
        "scca_summary": summarize_scca_report(scca_report, require_scca_pass=require_scca_pass),
        "production_observed_history_preflight": production_preflight,
        "production_scale_profile_contract": production_scale_profile_contract(),
        "production_scale_readiness": scale_readiness,
        "production_readiness_gate": readiness_gate,
        "sanitized_export_policy": sanitized_export_policy(),
        "claim_boundary": {
            "production_accuracy_claim": "not_supported_until_real_authoritative_observed_history_holdout_validation_passes",
            "offline_validation_claim": "supports inner-network repeatable smoke/regression validation of the current TWM pipeline",
            "raw_data_policy": "raw objects, geometries and row-level attributes are not exported by this report",
        },
        "recommendations": validation_bundle_recommendations(
            selected_bundle,
            validation_report,
            scca_report,
            require_scca_pass,
            production_preflight,
            scale_readiness,
            readiness_gate,
        ),
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


def validation_bundle_status(
    selected_bundle: dict[str, Any],
    validation_report: dict[str, Any],
    production_preflight: dict[str, Any] | None = None,
    production_readiness_gate: dict[str, Any] | None = None,
) -> str:
    if selected_bundle.get("status") == "blocked" or validation_report.get("overall_status") == "blocked":
        return "blocked"
    readiness_status = str((production_readiness_gate or {}).get("status") or "not_required")
    if readiness_status == "blocked":
        return "blocked"
    if readiness_status == "review":
        return "review"
    production_status = str((production_preflight or {}).get("status") or "not_provided")
    if production_status == "blocked":
        return "blocked"
    if production_status == "review":
        return "review"
    if selected_bundle.get("status") == "pass" and validation_report.get("overall_status") == "pass":
        return "pass"
    return "review"


def validation_bundle_exit_code(report: dict[str, Any], *, fail_on_blocked: bool = False) -> int:
    if fail_on_blocked and report.get("status") == "blocked":
        return 2
    return 0


def build_production_observed_history_preflight(
    *,
    production_observed_history: Path | str | None = None,
    synthetic_experiment_foundation: Path | str | None = DEFAULT_SYNTHETIC_EXPERIMENT_FOUNDATION,
) -> dict[str, Any]:
    production_path = Path(production_observed_history).expanduser() if production_observed_history else None
    synthetic_path = Path(synthetic_experiment_foundation).expanduser() if synthetic_experiment_foundation else None
    schema_audit = audit_observed_history_schema(production_path)
    policy_quality = schema_audit.get("policy_history_quality") or {}
    benchmark = load_synthetic_policy_coverage_benchmark(synthetic_path)
    alignment = production_policy_history_alignment(policy_quality, benchmark)

    if production_path is not None and schema_audit.get("status") == "missing":
        status = "blocked"
    elif production_path is None:
        status = "not_provided"
    elif schema_audit.get("status") == "pass" and alignment.get("status") == "pass":
        status = "pass"
    else:
        status = "review"

    return {
        "schema": "territory_world_model.production_observed_history_preflight.v1",
        "status": status,
        "production_observed_history": str(production_path) if production_path else None,
        "synthetic_experiment_foundation": str(synthetic_path) if synthetic_path else None,
        "schema_audit": summarize_observed_history_schema_audit(schema_audit),
        "policy_history_quality": summarize_policy_history_quality(policy_quality),
        "policy_history_alignment": alignment,
        "synthetic_policy_coverage_benchmark": summarize_synthetic_policy_benchmark(benchmark),
        "claim_boundary": "data-readiness preflight only; observed-history coverage does not by itself prove TWM production accuracy",
    }


def load_synthetic_policy_coverage_benchmark(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "schema": "territory_world_model.synthetic_experiment_foundation.v1",
            "status": "not_provided",
            "policy_coverage_benchmark": {"status": "not_provided"},
        }
    if not path.exists():
        return {
            "schema": "territory_world_model.synthetic_experiment_foundation.v1",
            "status": "missing",
            "path": str(path),
            "policy_coverage_benchmark": {"status": "missing"},
        }
    rows = read_csv(path)
    return synthetic_experiment_foundation_summary(path, rows)


def summarize_observed_history_schema_audit(audit: dict[str, Any]) -> dict[str, Any]:
    row_quality = audit.get("row_quality") or {}
    return {
        "schema": audit.get("schema", "territory_world_model.observed_history_schema_audit.v1"),
        "status": audit.get("status"),
        "path": audit.get("path"),
        "row_count": audit.get("row_count", 0),
        "field_count": audit.get("field_count", 0),
        "missing_required_groups": list(audit.get("missing_required_groups") or []),
        "missing_data_gates": list(audit.get("missing_data_gates") or []),
        "row_quality": {
            "production_candidate_row_count": row_quality.get("production_candidate_row_count", 0),
            "production_treated_count": row_quality.get("production_treated_count", 0),
            "production_control_count": row_quality.get("production_control_count", 0),
            "rows_with_outcome": row_quality.get("rows_with_outcome", 0),
            "rows_with_spatial_support": row_quality.get("rows_with_spatial_support", 0),
            "rows_with_covariates": row_quality.get("rows_with_covariates", 0),
            "synthetic_count": row_quality.get("synthetic_count", 0),
            "not_for_production_count": row_quality.get("not_for_production_count", 0),
        },
        "expected_minimum_columns": list(audit.get("expected_minimum_columns") or []),
        "expected_policy_history_columns": list(audit.get("expected_policy_history_columns") or []),
    }


def summarize_policy_history_quality(quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": quality.get("schema", "territory_world_model.production_policy_history_quality.v1"),
        "status": quality.get("status"),
        "production_policy_row_count": quality.get("production_policy_row_count", 0),
        "allowed_count": quality.get("allowed_count", 0),
        "blocked_count": quality.get("blocked_count", 0),
        "rows_with_policy": quality.get("rows_with_policy", 0),
        "rows_with_action_type": quality.get("rows_with_action_type", 0),
        "rows_with_region": quality.get("rows_with_region", 0),
        "rows_with_time": quality.get("rows_with_time", 0),
        "region_count": quality.get("region_count", 0),
        "region_policy_key_count": quality.get("region_policy_key_count", 0),
        "region_action_policy_key_count": quality.get("region_action_policy_key_count", 0),
        "time_policy_key_count": quality.get("time_policy_key_count", 0),
        "mixed_allowed_policy_counts": dict(quality.get("mixed_allowed_policy_counts") or {}),
        "missing_policy_gates": list(quality.get("missing_policy_gates") or []),
        "claim_boundary": quality.get("claim_boundary"),
    }


def summarize_synthetic_policy_benchmark(summary: dict[str, Any]) -> dict[str, Any]:
    benchmark = summary.get("policy_coverage_benchmark") or {}
    return {
        "schema": benchmark.get("schema", "territory_world_model.synthetic_policy_coverage_benchmark.v1"),
        "status": benchmark.get("status") or summary.get("status"),
        "source": benchmark.get("source"),
        "required_allowed_count": benchmark.get("required_allowed_count", 0),
        "required_blocked_count": benchmark.get("required_blocked_count", 0),
        "required_region_policy_key_count": benchmark.get("required_region_policy_key_count", 0),
        "required_region_action_policy_key_count": benchmark.get("required_region_action_policy_key_count", 0),
        "required_mixed_allowed_policies": list(benchmark.get("required_mixed_allowed_policies") or []),
        "claim_boundary": benchmark.get("claim_boundary"),
    }


def build_production_readiness_gate(
    *,
    selected_bundle: dict[str, Any],
    validation_report: dict[str, Any],
    claim_ladder: dict[str, Any],
    production_preflight: dict[str, Any],
    production_scale_readiness: dict[str, Any] | None = None,
    scca_report: dict[str, Any],
    require_scca_pass: bool,
    require_production_readiness: bool,
) -> dict[str, Any]:
    checks = [
        readiness_check(
            "selected_plan_bundle_pass",
            selected_bundle.get("status") == "pass",
            selected_bundle.get("status"),
            "selected-plan evaluation bundle must pass",
        ),
        readiness_check(
            "validation_report_pass",
            validation_report.get("overall_status") == "pass",
            validation_report.get("overall_status"),
            "validation ladder must pass",
        ),
        readiness_check(
            "claim_ladder_deployable",
            claim_ladder.get("current_level") == "L4",
            claim_ladder.get("current_level"),
            "claim ladder must reach L4 deployable GIS support",
        ),
        readiness_check(
            "production_observed_history_preflight_pass",
            production_preflight.get("status") == "pass",
            production_preflight.get("status"),
            "real observed-history schema and policy-history alignment must pass",
        ),
        readiness_check(
            "production_scale_readiness_pass",
            (production_scale_readiness or {}).get("status") == "pass",
            (production_scale_readiness or {}).get("status", "not_provided"),
            "production scale profile must pass lakehouse, partitioning, spatial-index and distributed-compute readiness gates",
        ),
        readiness_check(
            "human_review_and_audit_pass",
            selected_plan_human_review_ready(selected_bundle, validation_report),
            {
                "selected_plan_status": selected_bundle.get("status"),
                "validation_status": validation_report.get("overall_status"),
                "review_stage": validation_stage_status(validation_report, "gis_deployability"),
            },
            "human review, audit and GIS deployability gates must pass",
        ),
    ]
    if require_scca_pass:
        checks.append(
            readiness_check(
                "scca_causal_evidence_pass",
                bool(scca_report) and (scca_report.get("evidence_gate") or {}).get("status") == "pass",
                (scca_report.get("evidence_gate") or {}).get("status") if scca_report else "missing",
                "SCCA spatial causal evidence must pass when required",
            )
        )

    failed = [check for check in checks if check["status"] != "pass"]
    if not require_production_readiness:
        status = "pass" if not failed else "review"
    else:
        status = "pass" if not failed else "blocked"
    return {
        "schema": "territory_world_model.production_readiness_gate.v1",
        "required": bool(require_production_readiness),
        "status": status,
        "checks": checks,
        "missing": [check["gate"] for check in failed],
        "claim_boundary": "production readiness requires passing real observed history, validation, claim ladder and human review gates; this gate is stricter than offline smoke validation",
    }


def build_production_scale_readiness(
    *,
    production_scale_profile: Path | str | None = None,
    state_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_path = Path(production_scale_profile).expanduser() if production_scale_profile else None
    if profile_path is None:
        local_max = max(
            int((state_summary or {}).get("object_count") or 0),
            int((state_summary or {}).get("relation_count") or 0),
        )
        return {
            "schema": "territory_world_model.production_scale_readiness.v1",
            "status": "not_provided",
            "profile_path": None,
            "scale_tier": classify_scale_tier(local_max),
            "observed": {
                "max_layer_row_count": 0,
                "total_row_count": 0,
                "layer_count": 0,
                "local_state_object_count": int((state_summary or {}).get("object_count") or 0),
                "local_state_relation_count": int((state_summary or {}).get("relation_count") or 0),
            },
            "checks": [
                readiness_check(
                    "production_scale_profile_provided",
                    False,
                    "not_provided",
                    "provide a sanitized production-scale profile before claiming national or million-scale readiness",
                )
            ],
            "missing": ["production_scale_profile_provided"],
            "claim_boundary": "local/demo state size does not prove readiness for million- or hundred-million-scale production layers",
        }
    if not profile_path.exists():
        return {
            "schema": "territory_world_model.production_scale_readiness.v1",
            "status": "blocked",
            "profile_path": str(profile_path),
            "scale_tier": "unknown",
            "observed": {"max_layer_row_count": 0, "total_row_count": 0, "layer_count": 0},
            "checks": [
                readiness_check(
                    "production_scale_profile_readable",
                    False,
                    "missing",
                    "production scale profile path must exist",
                )
            ],
            "missing": ["production_scale_profile_readable"],
            "claim_boundary": "scale readiness cannot be evaluated when the supplied profile is missing",
        }

    profile = read_json(profile_path)
    layers = production_scale_layers(profile)
    max_rows = max((layer["row_count"] for layer in layers), default=0)
    total_rows = sum(layer["row_count"] for layer in layers)
    scale_tier = classify_scale_tier(max_rows)
    needs_lakehouse = max_rows >= 1_000_000
    needs_distributed = max_rows >= 10_000_000
    needs_national_controls = max_rows >= 100_000_000
    checks = [
        readiness_check(
            "production_scale_profile_readable",
            True,
            str(profile_path),
            "production scale profile path must exist",
        ),
        readiness_check(
            "production_scale_profile_not_example",
            not production_scale_profile_is_example(profile),
            {
                "example_only": profile.get("example_only"),
                "not_for_production": profile.get("not_for_production"),
            },
            "profile must be filled from sanitized real production metadata, not the example template",
        ),
        readiness_check(
            "production_layer_inventory",
            bool(layers),
            len(layers),
            "profile must include at least one production layer or table with row counts",
        ),
        readiness_check(
            "lakehouse_storage",
            (not needs_lakehouse) or profile_has_lakehouse_storage(profile, layers),
            production_scale_storage_observed(profile, layers),
            "million-scale layers require columnar lakehouse storage such as GeoParquet, Iceberg, Delta or Hudi",
        ),
        readiness_check(
            "partition_strategy",
            (not needs_lakehouse) or profile_has_partitioning(profile, layers),
            production_scale_partition_observed(profile, layers),
            "million-scale layers require explicit administrative, temporal or spatial partitioning",
        ),
        readiness_check(
            "spatial_index_strategy",
            (not needs_lakehouse) or profile_has_spatial_index(profile, layers),
            production_scale_spatial_index_observed(profile, layers),
            "million-scale spatial layers require spatial index, grid, tile or Hilbert/S2/H3/quadkey strategy",
        ),
        readiness_check(
            "distributed_compute",
            (not needs_distributed) or profile_has_distributed_compute(profile),
            production_scale_compute_observed(profile),
            "ten-million-scale and larger layers require distributed compute such as Spark/Sedona, Flink, Dask, Ray or distributed SQL",
        ),
        readiness_check(
            "national_scale_sampling_or_tiling",
            (not needs_national_controls) or profile_has_sampling_or_tiling(profile, layers),
            production_scale_sampling_observed(profile, layers),
            "hundred-million-scale layers require tiling, sampling, chunking or pyramid strategy for validation and serving",
        ),
    ]
    failed = [check for check in checks if check["status"] != "pass"]
    status = "pass" if not failed else "review"
    return {
        "schema": "territory_world_model.production_scale_readiness.v1",
        "status": status,
        "profile_path": str(profile_path),
        "scale_tier": scale_tier,
        "observed": {
            "max_layer_row_count": max_rows,
            "total_row_count": total_rows,
            "layer_count": len(layers),
            "requires_lakehouse_storage": needs_lakehouse,
            "requires_distributed_compute": needs_distributed,
            "requires_national_scale_controls": needs_national_controls,
        },
        "checks": checks,
        "missing": [check["gate"] for check in failed],
        "claim_boundary": "scale readiness checks architecture evidence only; they do not prove model accuracy, rule correctness or planning optimality",
    }


def production_scale_layers(profile: dict[str, Any]) -> list[dict[str, Any]]:
    raw_layers: list[Any] = []
    for key in ("layers", "tables", "vector_layers", "feature_layers"):
        value = profile.get(key)
        if isinstance(value, list):
            raw_layers.extend(value)
    layers: list[dict[str, Any]] = []
    for item in raw_layers:
        if not isinstance(item, dict):
            continue
        row_count = first_int(item, "row_count", "feature_count", "record_count", "object_count", "count")
        layers.append(
            {
                "name": str(item.get("name") or item.get("table") or item.get("layer") or "unnamed"),
                "row_count": max(0, row_count),
                "storage_format": str(item.get("storage_format") or item.get("format") or item.get("file_format") or ""),
                "lakehouse_table": truthy_value(item.get("lakehouse_table") or item.get("managed_table")),
                "partition_columns": list_value(item.get("partition_columns") or item.get("partitions") or item.get("partitioning")),
                "spatial_index": str(item.get("spatial_index") or item.get("index") or item.get("grid") or ""),
                "tiling": str(item.get("tiling") or item.get("tile_scheme") or item.get("pyramid") or ""),
                "sampling_strategy": str(item.get("sampling_strategy") or item.get("chunking") or ""),
            }
        )
    return layers


def production_scale_profile_is_example(profile: dict[str, Any]) -> bool:
    return truthy_value(profile.get("example_only")) or truthy_value(profile.get("not_for_production"))


def production_scale_profile_contract() -> dict[str, Any]:
    return {
        "schema": "territory_world_model.production_scale_profile_contract.v1",
        "purpose": "sanitized metadata contract for checking whether TWM validation can be rehearsed against million- or national-scale layers",
        "sensitive_data_policy": {
            "do_not_include": [
                "raw geometries",
                "row-level attributes",
                "object ids that are sensitive",
                "file paths that reveal classified network structure",
                "business secrets or approval content",
            ],
            "allowed": [
                "row counts",
                "layer/table names or sanitized aliases",
                "storage format",
                "partition columns",
                "spatial index or tile strategy",
                "distributed compute engine family",
                "sampling/chunking/tiling strategy",
            ],
        },
        "minimum_fields": {
            "layers": [
                "name",
                "row_count",
                "storage_format",
                "partition_columns",
                "spatial_index",
                "tiling or sampling_strategy for hundred-million-scale layers",
            ],
            "compute": ["engine or spatial_engine", "distributed"],
            "validation": ["sampling_strategy or chunking for national-scale validation"],
        },
        "scale_rules": {
            "million_scale": "requires lakehouse/columnar storage, partitioning and spatial indexing",
            "ten_million_scale": "requires million-scale gates plus distributed compute",
            "hundred_million_scale": "requires ten-million-scale gates plus sampling/tiling/chunking/pyramid strategy",
        },
        "claim_boundary": "this contract checks platform and data-layout readiness only; it does not prove TWM accuracy, simulator quality or planner optimality",
    }


def production_scale_profile_template() -> dict[str, Any]:
    return {
        "schema": "territory_world_model.production_scale_profile.v1",
        "example_only": True,
        "not_for_production": True,
        "profile_id": "replace_with_inner_network_profile_id",
        "created_by": "replace_with_role_or_team",
        "created_at": "YYYY-MM-DD",
        "scope": {
            "region_scope": "national_or_province_or_city",
            "business_scope": "natural_resource_planning_or_land_use_control",
            "sensitivity": "sanitized_metadata_only",
        },
        "layers": [
            {
                "name": "sanitized_layer_alias",
                "row_count": 120000000,
                "storage_format": "geoparquet",
                "lakehouse_table": True,
                "partition_columns": ["province_code", "year"],
                "spatial_index": "s2_or_h3_or_hilbert_or_quadkey",
                "tiling": "quadkey_or_vector_tile_pyramid",
                "sampling_strategy": "stratified_spatial_temporal_holdout",
                "notes": "replace values with sanitized production metadata; do not include raw geometries or row-level attributes",
            }
        ],
        "storage": {
            "table_format": "iceberg_or_delta_or_hudi_or_geoparquet",
            "object_store": "minio_or_hdfs_or_secure_object_store",
            "partition_columns": ["province_code", "year"],
            "spatial_index": "s2_or_h3_or_hilbert_or_quadkey",
        },
        "compute": {
            "engine": "spark",
            "spatial_engine": "sedona",
            "sql_engine": "trino_or_spark_sql",
            "distributed": True,
            "worker_count": "replace_with_sanitized_capacity_bucket",
        },
        "validation": {
            "sampling_strategy": "stratified_spatial_temporal_holdout",
            "chunking": "administrative_partition_plus_spatial_tile",
            "holdout_policy": "province_time_or_tile_based_holdout",
        },
        "serving": {
            "tiling": "vector_tile_pyramid",
            "tile_cache": "configured",
        },
        "claim_boundary": "template only; set example_only=false and not_for_production=false only after replacing every example value with sanitized real production metadata",
    }


def write_production_scale_profile_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(production_scale_profile_template(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_int(mapping: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key not in mapping:
            continue
        try:
            return int(float(str(mapping.get(key)).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return 0


def list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def truthy_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "pass", "passed"}


def classify_scale_tier(max_rows: int) -> str:
    if max_rows >= 100_000_000:
        return "hundred_million_scale"
    if max_rows >= 10_000_000:
        return "ten_million_scale"
    if max_rows >= 1_000_000:
        return "million_scale"
    if max_rows > 0:
        return "local_or_county_scale"
    return "not_profiled"


def profile_has_lakehouse_storage(profile: dict[str, Any], layers: list[dict[str, Any]]) -> bool:
    formats = production_scale_storage_observed(profile, layers)
    accepted = {"parquet", "geoparquet", "iceberg", "delta", "deltalake", "hudi", "orc"}
    return any(item in accepted for item in formats)


def production_scale_storage_observed(profile: dict[str, Any], layers: list[dict[str, Any]]) -> list[str]:
    observed: set[str] = set()
    storage = profile.get("storage") if isinstance(profile.get("storage"), dict) else {}
    for key in ("format", "table_format", "lakehouse", "catalog", "object_store"):
        value = str((storage or {}).get(key) or "").strip().lower()
        if value:
            observed.add(value)
    for layer in layers:
        value = str(layer.get("storage_format") or "").strip().lower()
        if value:
            observed.add(value)
        if layer.get("lakehouse_table"):
            observed.add("lakehouse_table")
    return sorted(observed)


def profile_has_partitioning(profile: dict[str, Any], layers: list[dict[str, Any]]) -> bool:
    return bool(production_scale_partition_observed(profile, layers))


def production_scale_partition_observed(profile: dict[str, Any], layers: list[dict[str, Any]]) -> list[str]:
    observed: set[str] = set()
    storage = profile.get("storage") if isinstance(profile.get("storage"), dict) else {}
    for item in list_value((storage or {}).get("partition_columns") or (storage or {}).get("partitioning")):
        observed.add(item)
    for layer in layers:
        for item in layer.get("partition_columns") or []:
            observed.add(str(item))
    return sorted(observed)


def profile_has_spatial_index(profile: dict[str, Any], layers: list[dict[str, Any]]) -> bool:
    return bool(production_scale_spatial_index_observed(profile, layers))


def production_scale_spatial_index_observed(profile: dict[str, Any], layers: list[dict[str, Any]]) -> list[str]:
    observed: set[str] = set()
    storage = profile.get("storage") if isinstance(profile.get("storage"), dict) else {}
    for key in ("spatial_index", "grid", "tile_index"):
        value = str((storage or {}).get(key) or "").strip().lower()
        if value:
            observed.add(value)
    for layer in layers:
        value = str(layer.get("spatial_index") or "").strip().lower()
        if value:
            observed.add(value)
    return sorted(observed)


def profile_has_distributed_compute(profile: dict[str, Any]) -> bool:
    observed = production_scale_compute_observed(profile)
    accepted = {"spark", "sedona", "flink", "dask", "ray", "trino", "presto", "distributed_sql", "distributed-sql"}
    return any(item in accepted for item in observed)


def production_scale_compute_observed(profile: dict[str, Any]) -> list[str]:
    observed: set[str] = set()
    compute = profile.get("compute") if isinstance(profile.get("compute"), dict) else {}
    for key in ("engine", "spatial_engine", "sql_engine", "scheduler"):
        value = str((compute or {}).get(key) or "").strip().lower()
        if value:
            observed.add(value)
    if truthy_value((compute or {}).get("distributed")):
        observed.add("distributed")
    return sorted(observed)


def profile_has_sampling_or_tiling(profile: dict[str, Any], layers: list[dict[str, Any]]) -> bool:
    return bool(production_scale_sampling_observed(profile, layers))


def production_scale_sampling_observed(profile: dict[str, Any], layers: list[dict[str, Any]]) -> list[str]:
    observed: set[str] = set()
    validation = profile.get("validation") if isinstance(profile.get("validation"), dict) else {}
    serving = profile.get("serving") if isinstance(profile.get("serving"), dict) else {}
    for key in ("sampling_strategy", "chunking", "tiling", "tile_cache", "pyramid"):
        for source in (validation or {}, serving or {}):
            value = str(source.get(key) or "").strip().lower()
            if value and value not in {"false", "0", "none"}:
                observed.add(value)
    for layer in layers:
        for key in ("tiling", "sampling_strategy"):
            value = str(layer.get(key) or "").strip().lower()
            if value:
                observed.add(value)
    return sorted(observed)


def readiness_check(gate: str, passed: bool, observed: Any, requirement: str) -> dict[str, Any]:
    return {
        "gate": gate,
        "status": "pass" if passed else "review",
        "observed": observed,
        "requirement": requirement,
    }


def validation_stage_status(validation_report: dict[str, Any], stage_code: str) -> str:
    for stage in validation_report.get("stages") or []:
        if stage.get("stage_code") == stage_code:
            return str(stage.get("status") or "")
    return "missing"


def selected_plan_human_review_ready(selected_bundle: dict[str, Any], validation_report: dict[str, Any]) -> bool:
    gate = selected_bundle.get("evidence_gate") or {}
    claim_boundary = selected_bundle.get("claim_boundary") or {}
    return (
        selected_bundle.get("status") == "pass"
        and gate.get("status") == "pass"
        and validation_stage_status(validation_report, "gis_deployability") == "pass"
        and claim_boundary.get("validation_overall_status") == "pass"
    )


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
            "production observed-history readiness counts",
            "production policy-history coverage diagnostics",
            "production scale readiness diagnostics",
            "production readiness gate summary",
            "recommendations",
        ],
        "intended_use": "air-gapped validation feedback and non-sensitive progress reporting",
    }


def validation_bundle_recommendations(
    selected_bundle: dict[str, Any],
    validation_report: dict[str, Any],
    scca_report: dict[str, Any],
    require_scca_pass: bool,
    production_preflight: dict[str, Any] | None = None,
    production_scale_readiness: dict[str, Any] | None = None,
    production_readiness_gate: dict[str, Any] | None = None,
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
    production_status = str((production_preflight or {}).get("status") or "not_provided")
    if production_status == "not_provided":
        recommendations.append("provide real non-synthetic observed history to move beyond offline smoke validation")
    elif production_status == "blocked":
        recommendations.append("fix the production observed-history path before running production readiness gates")
    elif production_status == "review":
        recommendations.append("complete production observed-history schema, policy-history and synthetic-benchmark alignment gates")
    scale_status = str((production_scale_readiness or {}).get("status") or "not_provided")
    scale_tier = str((production_scale_readiness or {}).get("scale_tier") or "not_profiled")
    if scale_status == "not_provided":
        recommendations.append("provide a sanitized production scale profile before claiming readiness for million- or national-scale layers")
    elif scale_status == "blocked":
        recommendations.append("fix the production scale profile path before running production readiness gates")
    elif scale_status == "review":
        recommendations.append(f"complete lakehouse, partitioning, spatial-index and distributed-compute readiness gates for {scale_tier}")
    readiness_status = str((production_readiness_gate or {}).get("status") or "not_required")
    if readiness_status == "blocked":
        recommendations.append("production readiness is blocked; use the production_readiness_gate missing list as the deployment punch list")
    elif readiness_status == "review":
        recommendations.append("production readiness is not yet satisfied; keep this bundle as an offline validation artifact")
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
    production = report.get("production_observed_history_preflight") or {}
    scale = report.get("production_scale_readiness") or {}
    readiness = report.get("production_readiness_gate") or {}
    production_schema = production.get("schema_audit") or {}
    production_policy = production.get("policy_history_quality") or {}
    production_alignment = production.get("policy_history_alignment") or {}
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
        f"- Production observed history: `{inputs.get('production_observed_history')}`",
        f"- Synthetic policy benchmark: `{inputs.get('synthetic_experiment_foundation')}`",
        f"- Production scale profile: `{inputs.get('production_scale_profile')}`",
        f"- Require production readiness: `{inputs.get('require_production_readiness')}`",
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
        "## Production Observed-History Preflight",
        "",
        f"- Preflight status: `{production.get('status')}`",
        f"- Schema status: `{production_schema.get('status')}`",
        f"- Production-ready rows: `{(production_schema.get('row_quality') or {}).get('production_candidate_row_count', 0)}`",
        f"- Policy-history status: `{production_policy.get('status')}`",
        f"- Policy allowed/blocked rows: `{production_policy.get('allowed_count', 0)}` / `{production_policy.get('blocked_count', 0)}`",
        f"- Region-policy keys: `{production_policy.get('region_policy_key_count', 0)}`",
        f"- Region-action-policy keys: `{production_policy.get('region_action_policy_key_count', 0)}`",
        f"- Alignment status: `{production_alignment.get('status')}`",
        f"- Alignment missing: `{production_alignment.get('missing', [])}`",
        "",
        "## Production Scale Readiness",
        "",
        f"- Scale status: `{scale.get('status')}`",
        f"- Scale tier: `{scale.get('scale_tier')}`",
        f"- Max layer rows: `{(scale.get('observed') or {}).get('max_layer_row_count', 0)}`",
        f"- Total rows: `{(scale.get('observed') or {}).get('total_row_count', 0)}`",
        f"- Layer count: `{(scale.get('observed') or {}).get('layer_count', 0)}`",
        f"- Missing gates: `{scale.get('missing', [])}`",
        "",
        "## Production Readiness Gate",
        "",
        f"- Required: `{readiness.get('required')}`",
        f"- Status: `{readiness.get('status')}`",
        f"- Missing gates: `{readiness.get('missing', [])}`",
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
