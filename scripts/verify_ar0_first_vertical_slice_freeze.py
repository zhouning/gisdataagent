#!/usr/bin/env python3
"""Verify the bounded AR-0 first vertical slice freeze manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "config/freezes/ar0-first-vertical-slice-2026-08-22.json"

EXPECTED_BLOCKERS = {
    "source_quality_not_passed",
    "source_primary_key_not_unique",
    "source_numeric_constraints_failed",
    "source_area_consistency_failed",
    "standardization_derived_fields_missing",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _diagnostic_fingerprint_matches(report: Mapping[str, Any], expected: str) -> bool:
    from data_agent.platform_contracts import canonical_json_fingerprint

    payload = dict(report)
    observed = payload.pop("diagnostic_sha256", None)
    return observed == expected == canonical_json_fingerprint(payload)


def verify_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if manifest.get("schema") != "gis-data-agent.ar0-freeze-manifest.v1":
        raise ValueError("unsupported AR-0 freeze manifest schema")
    if manifest.get("status") not in {
        "draft",
        "technical_frozen",
        "awaiting_business_approval",
        "promotable",
    }:
        raise ValueError("invalid AR-0 freeze status")

    evidence = manifest.get("evidence")
    identities = manifest.get("identities")
    scope = manifest.get("scope")
    approvals = manifest.get("approvals")
    if not all(isinstance(value, dict) for value in (evidence, identities, scope, approvals)):
        raise ValueError("manifest is missing an object section")

    mapping_protocol = _read_json(REPO_ROOT / evidence["mapping_protocol"])
    mapping_report = _read_json(REPO_ROOT / evidence["mapping_report"])
    source_report = _read_json(REPO_ROOT / evidence["source_report"])
    dolphinscheduler_runtime = _read_json(
        REPO_ROOT / evidence["dolphinscheduler_runtime_certification"]
    )
    repair_diagnostic = _read_json(REPO_ROOT / evidence["quality_repair_diagnostic"])
    semantic_candidate_audit = _read_json(
        REPO_ROOT / evidence["semantic_candidate_audit"]
    )
    transformation_contract = _read_json(
        REPO_ROOT / evidence["transformation_contract"]
    )
    impact_preview = _read_json(REPO_ROOT / evidence["transformation_impact_preview"])
    from data_agent.platform_contracts import (
        JqdltbTransformationContract,
        canonical_json_fingerprint,
    )

    parsed_transformation_contract = JqdltbTransformationContract.model_validate(
        transformation_contract
    )
    preview_payload = dict(impact_preview)
    preview_sha256 = preview_payload.pop("preview_sha256", None)
    preview_path = REPO_ROOT / evidence["transformation_impact_preview"]
    preview_content_sha256 = hashlib.sha256(preview_path.read_bytes()).hexdigest()
    preview_matrix = impact_preview.get("matrix") or []

    def preview_scenario(nonpositive: str, deviation: str) -> Mapping[str, Any]:
        matches = [
            item
            for item in preview_matrix
            if item.get("policy", {}).get("nonpositive_area_policy") == nonpositive
            and item.get("policy", {}).get("area_deviation_policy") == deviation
        ]
        return matches[0] if len(matches) == 1 else {}

    expected_impact = evidence.get("expected_transformation_impact") or {}
    quarantine_preserve = preview_scenario("quarantine", "preserve_source")
    quarantine_quarantine = preview_scenario("quarantine", "quarantine")
    business_correction_scenarios = [
        item
        for item in preview_matrix
        if item.get("policy", {}).get("nonpositive_area_policy") == "business_correction"
    ]
    standard = mapping_protocol.get("standard") or {}
    golden_cases = [
        case
        for case in mapping_protocol.get("cases") or []
        if case.get("case_id") == "bizhu-jqdltb-parcel-current-golden"
    ]
    if len(golden_cases) != 1:
        raise ValueError("mapping protocol must contain exactly one JQDLTB golden case")
    golden_case = golden_cases[0]
    mapping_governance = mapping_report.get("governance") or {}
    source = source_report.get("source") or {}
    source_profile = source.get("profile") or {}
    source_quality = source_report.get("quality") or {}
    promotion = source_report.get("promotion") or {}
    runtime = source_report.get("runtime") or {}
    diagnostic_source = repair_diagnostic.get("source") or {}
    diagnostic_policy = repair_diagnostic.get("diagnostic_policy") or {}
    diagnostic_primary_key = repair_diagnostic.get("primary_key") or {}
    diagnostic_numeric = repair_diagnostic.get("numeric_constraints") or []
    diagnostic_area = repair_diagnostic.get("area_consistency") or {}
    diagnostic_derivations = repair_diagnostic.get("standard_derivations") or []
    semantic_identities = semantic_candidate_audit.get("identities") or {}
    semantic_standard = semantic_candidate_audit.get("standard_evidence") or {}
    semantic_standard_definition = semantic_standard.get("definition") or {}
    semantic_source = semantic_candidate_audit.get("source_evidence") or {}
    semantic_profiles = semantic_source.get("candidate_field_profiles") or {}
    expected_semantic = evidence.get("expected_semantic_candidate_findings") or {}

    declared_blockers = set(evidence.get("required_source_blockers") or [])
    observed_blockers = set(promotion.get("blockers") or [])
    evaluation_policy = source_report.get("evaluation_policy") or {}
    expected_repair = evidence.get("expected_quality_repair_findings") or {}
    candidate_key_fields = [
        item.get("field") for item in diagnostic_primary_key.get("candidate_fields") or []
    ]
    observed_nonpositive = {
        str(item.get("field")): item.get("nonpositive_count") for item in diagnostic_numeric
    }
    pending_derivation_targets = [
        item.get("target_field")
        for item in diagnostic_derivations
        if item.get("status") == "pending_approval" and item.get("auto_derivation") is False
    ]
    checks: dict[str, bool] = {
        "mapping_technical_pass": mapping_report.get("technical_pass")
        is evidence.get("mapping_technical_pass"),
        "standard_code": standard.get("doc_code") == identities["standard_doc_code"],
        "standard_version": standard.get("version_label")
        == identities["standard_version_label"],
        "standard_identity": standard.get("elements_sha256")
        == identities["standard_elements_sha256"],
        "target_domain": golden_case.get("target_table") == scope.get("target_domain"),
        "archive_identity": source.get("archive_sha256") == identities["archive_sha256"],
        "bundle_identity": (source.get("bundle") or {}).get("bundle_sha256")
        == identities["bundle_sha256"]
        == golden_case.get("bundle_sha256"),
        "feature_count": source_profile.get("feature_count") == identities["feature_count"],
        "crs": source_profile.get("crs") == identities["crs"],
        "source_quality_matches": source_quality.get("source_quality_verdict")
        == evidence.get("source_quality_verdict"),
        "source_promotion_matches": promotion.get("ready")
        is evidence.get("promotion_ready"),
        "dolphinscheduler_runtime_binding": (
            runtime.get("dolphinscheduler_configured") is True
            and runtime.get("dolphinscheduler_runtime_certification")
            == evidence.get("dolphinscheduler_runtime_certification")
            and runtime.get("dolphinscheduler_server_version") == "3.4.2"
        ),
        "dolphinscheduler_runtime_certification": (
            dolphinscheduler_runtime.get("schema")
            == "gda.jqdltb_dolphinscheduler_runtime_certification.v1"
            and dolphinscheduler_runtime.get("status") == "passed"
            and dolphinscheduler_runtime.get("promotion_ready") is False
            and dolphinscheduler_runtime.get("quality_result_is_authoritative") is True
            and dolphinscheduler_runtime.get("quality_verdict") == "failed"
            and dolphinscheduler_runtime.get("data_product_version_created") is False
            and all(
                bool(value)
                for key, value in (dolphinscheduler_runtime.get("checks") or {}).items()
                if key != "quality_failed_explicit"
            )
            and dolphinscheduler_runtime.get("checks", {}).get(
                "quality_failed_explicit"
            )
            is True
        ),
        "dolphinscheduler_runtime_fingerprint": (
            dolphinscheduler_runtime.get("report_sha256")
            == canonical_json_fingerprint(
                {
                    key: value
                    for key, value in dolphinscheduler_runtime.items()
                    if key != "report_sha256"
                }
            )
        ),
        "source_blocker_contract": declared_blockers == EXPECTED_BLOCKERS
        and declared_blockers.issubset(observed_blockers),
        "business_steward_matches": (
            approvals.get("business_steward") is None
            and mapping_governance.get("business_steward") == "pending_assignment"
        )
        or approvals.get("business_steward")
        == mapping_governance.get("business_steward"),
        "license_matches": (
            approvals.get("license_status") is None
            and mapping_governance.get("license_status")
            == "pending_internal_evaluation_only"
        )
        or approvals.get("license_status") == mapping_governance.get("license_status"),
        "llm_disabled": scope.get("llm_mode") == "disabled",
        "product_version_matches": evidence.get("data_product_version_created")
        is evaluation_policy.get("data_product_version_created"),
        "repair_diagnostic_fingerprint": _diagnostic_fingerprint_matches(
            repair_diagnostic,
            str(evidence["quality_repair_diagnostic_sha256"]),
        ),
        "repair_diagnostic_identity": diagnostic_source.get("archive_sha256")
        == identities["archive_sha256"]
        and diagnostic_source.get("bundle_sha256") == identities["bundle_sha256"]
        and diagnostic_source.get("feature_count") == identities["feature_count"],
        "repair_diagnostic_read_only": diagnostic_policy == {
            "mode": "aggregate_only_read_only",
            "source_values_persisted": False,
            "source_bytes_modified": False,
            "auto_repair": False,
            "promotion_ready": False,
        },
        "repair_diagnostic_findings": candidate_key_fields
        == expected_repair.get("candidate_key_fields")
        and observed_nonpositive == expected_repair.get("nonpositive_area_counts")
        and diagnostic_area.get("outside_tolerance_count")
        == expected_repair.get("outside_area_tolerance_count")
        and pending_derivation_targets
        == expected_repair.get("pending_derivation_targets"),
        "semantic_candidate_audit_fingerprint": (
            semantic_candidate_audit.get("report_sha256")
            == evidence.get("semantic_candidate_audit_sha256")
            == canonical_json_fingerprint(
                {
                    key: value
                    for key, value in semantic_candidate_audit.items()
                    if key != "report_sha256"
                }
            )
            and hashlib.sha256(
                (REPO_ROOT / evidence["semantic_candidate_audit"]).read_bytes()
            ).hexdigest()
            == evidence.get("semantic_candidate_audit_content_sha256")
        ),
        "semantic_candidate_audit_identity": (
            semantic_identities.get("archive_sha256") == identities["archive_sha256"]
            and semantic_identities.get("bundle_sha256") == identities["bundle_sha256"]
            and semantic_identities.get("feature_count") == identities["feature_count"]
            and semantic_identities.get("source_crs") == identities["crs"]
        ),
        "semantic_candidate_audit_findings": (
            semantic_standard.get("document_sha256")
            == expected_semantic.get("standard_document_sha256")
            and semantic_source.get("metadata_xml", {}).get("sha256")
            == expected_semantic.get("metadata_xml_sha256")
            and semantic_standard_definition.get("fields", {})
            .get("SJNF", {})
            .get("definition")
            == expected_semantic.get("sjnf_definition")
            and semantic_standard_definition.get("notes", {}).get(
                "mssm_value_domain_present"
            )
            is expected_semantic.get("mssm_value_domain_present")
            and {
                field: (semantic_profiles.get(field) or {}).get("non_blank_count")
                for field in expected_semantic.get("candidate_non_blank_counts", {})
            }
            == expected_semantic.get("candidate_non_blank_counts")
            and semantic_candidate_audit.get("decisions")
            == expected_semantic.get("decisions")
        ),
        "semantic_candidate_audit_read_only": (
            semantic_candidate_audit.get("audit_mode")
            == "read_only_provenance_backed_candidate_audit"
            and semantic_source.get("target_values_written") is False
            and semantic_candidate_audit.get("governance")
            == {
                "derivation_rule_created": False,
                "strategy_created": False,
                "approval_case_created": False,
                "data_product_version_created": False,
            }
        ),
        "transformation_contract_fingerprint": transformation_contract.get(
            "contract_sha256"
        )
        == evidence.get("transformation_contract_sha256"),
        "transformation_contract_approval_gate": (
            parsed_transformation_contract.mode.value == "approval_required"
            and parsed_transformation_contract.approval_case is None
            and parsed_transformation_contract.nonpositive_area_policy is None
            and parsed_transformation_contract.area_deviation_policy is None
        ),
        "transformation_contract_identity": (
            parsed_transformation_contract.archive_sha256
            == identities["archive_sha256"]
            and parsed_transformation_contract.bundle_sha256
            == identities["bundle_sha256"]
            and parsed_transformation_contract.diagnostic_sha256
            == evidence["quality_repair_diagnostic_sha256"]
            and parsed_transformation_contract.source_resource_version_id
            == UUID(str(source_report["control_plane"]["resource_version_id"]))
        ),
        "transformation_impact_preview_fingerprint": (
            preview_sha256 == evidence.get("transformation_impact_preview_sha256")
            and preview_sha256 == canonical_json_fingerprint(preview_payload)
            and preview_content_sha256
            == evidence.get("transformation_impact_preview_content_sha256")
        ),
        "transformation_impact_preview_read_only": (
            impact_preview.get("schema") == "gda.jqdltb_transformation_impact_preview.v1"
            and impact_preview.get("mode") == "aggregate_only_read_only"
            and impact_preview.get("authority_state_created") is False
            and impact_preview.get("layer_artifacts_written") is False
            and impact_preview.get("source_bytes_modified") is False
            and impact_preview.get("source_values_persisted") is False
        ),
        "transformation_impact_preview_identity": (
            impact_preview.get("identities", {}).get("archive_sha256")
            == identities["archive_sha256"]
            and impact_preview.get("identities", {}).get("bundle_sha256_before")
            == identities["bundle_sha256"]
            and impact_preview.get("identities", {}).get("bundle_sha256_after")
            == identities["bundle_sha256"]
            and impact_preview.get("identities", {}).get("diagnostic_sha256")
            == evidence["quality_repair_diagnostic_sha256"]
            and impact_preview.get("identities", {}).get("feature_count")
            == identities["feature_count"]
        ),
        "transformation_impact_preview_matrix": (
            len(preview_matrix) == expected_impact.get("policy_count")
            and impact_preview.get("conclusion", {}).get("any_policy_promotable") is False
            and impact_preview.get("identities", {}).get("selected_strategy_sha256")
            is expected_impact.get("selected_strategy_sha256")
            and quarantine_preserve.get("projection", {}).get("exact") is True
            and quarantine_preserve.get("projection", {}).get("records_quarantined")
            == expected_impact.get("quarantine_preserve_source", {}).get(
                "records_quarantined"
            )
            and quarantine_preserve.get("projection", {}).get("records_after_area_policy")
            == expected_impact.get("quarantine_preserve_source", {}).get(
                "records_after_area_policy"
            )
            and quarantine_quarantine.get("projection", {}).get("exact") is True
            and quarantine_quarantine.get("projection", {}).get("records_quarantined")
            == expected_impact.get("quarantine_quarantine", {}).get("records_quarantined")
            and quarantine_quarantine.get("projection", {}).get("records_after_area_policy")
            == expected_impact.get("quarantine_quarantine", {}).get(
                "records_after_area_policy"
            )
            and len(business_correction_scenarios) == 3
            and all(
                item.get("projection", {}).get("exact")
                is expected_impact.get("business_correction_projection_exact")
                and item.get("projection", {}).get("records_after_area_policy") is None
                for item in business_correction_scenarios
            )
        ),
    }
    valid = all(checks.values())
    environment_owner = approvals.get("environment_owner") or {}
    promotion_ready = (
        valid
        and mapping_report.get("promotion_ready") is True
        and source_quality.get("source_quality_verdict") == "passed"
        and promotion.get("ready") is True
        and evidence.get("promotion_ready") is True
        and evidence.get("data_product_version_created") is True
        and all(
            approvals.get(key) is not None
            for key in ("business_steward", "license_status", "slo_on_call")
        )
        and all(environment_owner.get(key) is not None for key in ("staging", "production"))
    )
    if manifest.get("status") == "awaiting_business_approval" and not any(
        approvals.get(key) is None
        for key in ("business_steward", "license_status", "slo_on_call")
    ):
        raise ValueError("awaiting_business_approval manifest has no unresolved approval")
    if manifest.get("status") == "promotable" and not promotion_ready:
        raise ValueError("promotable AR-0 manifest has unresolved evidence or approval blockers")
    return {
        "schema": "gis-data-agent.ar0-freeze-verification.v1",
        "manifest_id": manifest.get("manifest_id"),
        "status": manifest.get("status"),
        "valid": valid,
        "promotion_ready": promotion_ready,
        "checks": checks,
        "unresolved_approvals": [
            key for key in ("business_steward", "license_status", "slo_on_call")
            if approvals.get(key) is None
        ],
        "source_quality_verdict": source_quality.get("source_quality_verdict"),
        "quality_repair_diagnostic_sha256": repair_diagnostic.get("diagnostic_sha256"),
        "source_promotion_blockers": promotion.get("blockers") or [],
        "mapping_governance_blockers": mapping_governance.get("promotion_blockers") or [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    try:
        report = verify_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=True, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
