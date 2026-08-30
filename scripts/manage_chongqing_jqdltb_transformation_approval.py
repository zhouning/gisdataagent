#!/usr/bin/env python3
"""Prepare and compile the approval-gated JQDLTB transformation.

`submit-decision-packet` applies an explicit human decision file to a frozen
draft without creating authority state. `prepare` then creates a complete
non-executable proposal and a pending ApprovalCase. The existing approval
authority persists and decides that case. `compile` accepts the approved case
returned by that authority and emits an executable contract. This command
never transforms or writes dataset records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from data_agent.platform_contracts import (
    ApprovalCase,
    JqdltbDecision,
    JqdltbDecisionEvidence,
    JqdltbDecisionIdentity,
    JqdltbDecisionPacket,
    JqdltbDecisionPacketStatus,
    JqdltbDecisionStatus,
    JqdltbTransformationContract,
    JqdltbTransformationMode,
    JqdltbTransformationStrategy,
    build_jqdltb_decision_packet,
    build_jqdltb_transformation_approval_case,
    build_jqdltb_transformation_contract,
    canonical_json_fingerprint,
    compile_jqdltb_executable_contract,
)

try:
    from scripts.verify_ar0_first_vertical_slice_freeze import verify_manifest
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from verify_ar0_first_vertical_slice_freeze import verify_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = (
    REPO_ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
)
DEFAULT_MANIFEST = (
    REPO_ROOT / "config/freezes/ar0-first-vertical-slice-2026-08-22.json"
)
DEFAULT_DIAGNOSTIC = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
DEFAULT_SEMANTIC_AUDIT = (
    REPO_ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
)
TRANSFORMATION_DECISION_TARGETS = (
    "canonical_key",
    "nonpositive_area_policy",
    "area_deviation_policy",
    "SJNF",
    "MSSM",
)
PROMOTION_DECISION_TARGETS = (
    "business_steward",
    "license_status",
    "slo_on_call",
    "environment_owner.staging",
    "environment_owner.production",
)
DECISION_PATCH_FIELDS = frozenset(
    {
        "owner_ref",
        "selected_value",
        "selected_resource_version_id",
        "selected_artifact_sha256",
        "selected_rule_ref",
        "selected_rule_sha256",
        "source_fields",
        "semantic_contract_ref",
        "semantic_contract_sha256",
        "method",
    }
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _diagnostic_sha256(diagnostic: dict[str, Any]) -> str:
    payload = dict(diagnostic)
    observed = payload.pop("diagnostic_sha256", None)
    calculated = canonical_json_fingerprint(payload)
    if observed != calculated:
        raise ValueError("JQDLTB diagnostic fingerprint is invalid")
    return calculated


def _semantic_audit_sha256(audit: dict[str, Any]) -> str:
    observed = audit.get("report_sha256")
    payload = {key: value for key, value in audit.items() if key != "report_sha256"}
    calculated = canonical_json_fingerprint(payload)
    if observed != calculated:
        raise ValueError("JQDLTB semantic candidate audit fingerprint is invalid")
    return calculated


def _decision_requirements(diagnostic: dict[str, Any]) -> dict[str, Any]:
    key = diagnostic.get("primary_key") or {}
    area = diagnostic.get("area_consistency") or {}
    numeric = diagnostic.get("numeric_constraints") or []
    derivations = diagnostic.get("standard_derivations") or []
    return {
        "canonical_key": {
            "required": True,
            "allowed": ["TBBH"],
            "observed_candidates": [
                {
                    "field": item.get("field"),
                    "unique_complete": item.get("unique_complete"),
                    "distinct_non_null": item.get("distinct_non_null"),
                }
                for item in key.get("candidate_fields") or []
            ],
        },
        "nonpositive_area_policy": {
            "required": True,
            "allowed": ["quarantine", "business_correction"],
            "observed_counts": {
                str(item.get("field")): int(item.get("nonpositive_count") or 0)
                for item in numeric
            },
            "business_correction_requires": [
                "business_correction_resource_version_id",
                "business_correction_sha256",
            ],
        },
        "area_deviation_policy": {
            "required": True,
            "allowed": ["preserve_source", "use_geometry", "quarantine"],
            "outside_tolerance_count": area.get("outside_tolerance_count"),
            "over_10_percent_count": area.get("over_10_percent_count"),
            "use_geometry_requires": [
                "geometry_area_rule_ref",
                "geometry_area_rule_sha256",
            ],
        },
        "derivation_contracts": [
            {
                "target_field": item.get("target_field"),
                "required": True,
                "observed_candidate_source_fields": sorted(
                    str(candidate.get("field"))
                    for candidate in item.get("candidates") or []
                    if candidate.get("field")
                ),
                "requires": [
                    "source_fields",
                    "semantic_contract_ref",
                    "semantic_contract_sha256",
                    "method",
                ],
            }
            for item in derivations
        ],
    }


def _semantic_candidate_requirements(
    semantic_audit: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return explicit semantic status for every proposed source field.

    A field is usable only after the audit records ``accepted`` or ``approved``.
    Presence in the source or a diagnostic candidate list is not an approval.
    """

    accepted_statuses = {"accepted", "approved"}
    accepted_decisions = {"accepted_candidate_available", "accepted", "approved"}
    result: dict[str, dict[str, Any]] = {}
    for target, candidates in (semantic_audit.get("candidates") or {}).items():
        statuses: dict[str, str] = {}
        for candidate in candidates or []:
            field = candidate.get("field")
            status = candidate.get("status")
            if field and status:
                statuses[str(field)] = str(status)
        decision = (semantic_audit.get("decisions") or {}).get(target)
        permitted = (
            sorted(field for field, status in statuses.items() if status in accepted_statuses)
            if decision in accepted_decisions
            else []
        )
        result[str(target)] = {
            "field_statuses": statuses,
            "decision": decision,
            "permitted_source_fields": permitted,
            "rejected_source_fields": sorted(
                field for field, status in statuses.items() if status == "rejected"
            ),
            "pending_source_fields": sorted(
                field
                for field, status in statuses.items()
                if status == "pending_business_evidence"
            ),
        }
    return result


def _validate_semantic_audit_binding(
    *,
    baseline: JqdltbTransformationContract,
    semantic_audit: dict[str, Any],
    expected_sha256: str | None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    audit_sha256 = _semantic_audit_sha256(semantic_audit)
    if audit_sha256 != expected_sha256:
        raise ValueError("semantic candidate audit is not bound to the freeze manifest")
    identities = semantic_audit.get("identities") or {}
    if (
        identities.get("archive_sha256") != baseline.archive_sha256
        or identities.get("bundle_sha256") != baseline.bundle_sha256
        or (
            f"{identities.get('standard_doc_code')}:"
            f"{identities.get('standard_version_label')}"
        )
        != baseline.standard_version_ref
    ):
        raise ValueError("semantic candidate audit and baseline identities differ")
    return audit_sha256, _semantic_candidate_requirements(semantic_audit)


def _validate_baseline_manifest_binding(
    *,
    manifest: dict[str, Any],
    baseline: JqdltbTransformationContract,
) -> None:
    """Ensure the caller supplied the exact baseline named by the Manifest."""

    contract_ref = (manifest.get("evidence") or {}).get("transformation_contract")
    if not isinstance(contract_ref, str) or not contract_ref:
        raise ValueError("freeze manifest transformation contract reference is missing")
    expected = JqdltbTransformationContract.model_validate(
        _read_json(REPO_ROOT / contract_ref)
    )
    if baseline.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError("baseline does not match the transformation contract bound by the freeze")


def _validate_strategy_source_admission(
    *,
    strategy: JqdltbTransformationStrategy,
    diagnostic: dict[str, Any],
    semantic_candidates: dict[str, dict[str, Any]],
) -> None:
    decisions = _decision_requirements(diagnostic)
    observed_sources = {
        item["target_field"]: set(item["observed_candidate_source_fields"])
        for item in decisions["derivation_contracts"]
    }
    available_sources = {
        target: set(item["permitted_source_fields"])
        for target, item in semantic_candidates.items()
    }
    for derivation in strategy.derivation_contracts:
        unobserved = set(derivation.source_fields) - observed_sources.get(
            derivation.target_field, set()
        )
        if unobserved:
            raise ValueError(
                f"{derivation.target_field} derivation uses unobserved source fields: "
                + ", ".join(sorted(unobserved))
            )
        unapproved = set(derivation.source_fields) - available_sources.get(
            derivation.target_field, set()
        )
        if unapproved:
            statuses = semantic_candidates.get(derivation.target_field, {}).get(
                "field_statuses", {}
            )
            rejected = sorted(
                field for field in unapproved if statuses.get(field) == "rejected"
            )
            pending = sorted(
                field
                for field in unapproved
                if statuses.get(field) == "pending_business_evidence"
            )
            reason = "semantically unapproved source fields"
            if rejected:
                reason = "semantically rejected source fields"
            elif pending:
                reason = "source fields pending semantic business evidence"
            raise ValueError(
                f"{derivation.target_field} derivation uses {reason}: "
                + ", ".join(sorted(unapproved))
            )


def build_readiness_report(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    semantic_audit_path: Path = DEFAULT_SEMANTIC_AUDIT,
    strategy: JqdltbTransformationStrategy | None = None,
    decision_packet: JqdltbDecisionPacket | None = None,
) -> dict[str, Any]:
    """Check frozen evidence and an optional strategy without creating authority state."""

    if strategy is not None and decision_packet is not None:
        raise ValueError("readiness accepts either strategy or decision packet, not both")
    freeze = verify_manifest(manifest_path)
    manifest = _read_json(manifest_path)
    baseline = JqdltbTransformationContract.model_validate(_read_json(baseline_path))
    _validate_baseline_manifest_binding(manifest=manifest, baseline=baseline)
    diagnostic = _read_json(diagnostic_path)
    semantic_audit = _read_json(semantic_audit_path)
    diagnostic_sha256 = _diagnostic_sha256(diagnostic)
    semantic_audit_sha256 = _semantic_audit_sha256(semantic_audit)
    if baseline.mode is not JqdltbTransformationMode.APPROVAL_REQUIRED:
        raise ValueError("readiness requires the unresolved approval-gated baseline")
    if baseline.diagnostic_sha256 != diagnostic_sha256:
        raise ValueError("baseline and diagnostic identities differ")
    expected_semantic_audit_sha256 = (manifest.get("evidence") or {}).get(
        "semantic_candidate_audit_sha256"
    )
    semantic_audit_sha256, semantic_candidates = _validate_semantic_audit_binding(
        baseline=baseline,
        semantic_audit=semantic_audit,
        expected_sha256=expected_semantic_audit_sha256,
    )
    packet_validation = None
    packet_transformation_blockers: list[str] = []
    packet_promotion_blockers: list[str] = []
    if decision_packet is not None:
        packet_validation = validate_decision_packet(
            decision_packet,
            manifest_path=manifest_path,
            baseline_path=baseline_path,
            diagnostic_path=diagnostic_path,
            semantic_audit_path=semantic_audit_path,
        )
        packet_transformation_blockers = [
            f"decision_packet.{target}.{status}"
            for target, status in packet_validation["transformation_blockers"].items()
        ]
        packet_promotion_blockers = [
            f"decision_packet.{target}.{status}"
            for target, status in packet_validation["promotion_blockers"].items()
        ]
        if decision_packet.status is not JqdltbDecisionPacketStatus.SUBMITTED:
            packet_transformation_blockers.append("decision_packet.status.draft")
            packet_promotion_blockers.append("decision_packet.status.draft")
        if packet_validation["strategy_ready"]:
            strategy = decision_packet.to_strategy()

    decisions = _decision_requirements(diagnostic)
    semantic_definition = (
        semantic_audit.get("standard_evidence", {}).get("definition", {})
    )
    semantic_profiles = semantic_audit.get("source_evidence", {}).get(
        "candidate_field_profiles", {}
    )
    decisions["semantic_evidence"] = {
        "audit_sha256": semantic_audit_sha256,
        "targets": semantic_audit.get("decisions", {}),
        "sjnf_definition": semantic_definition.get("fields", {})
        .get("SJNF", {})
        .get("definition"),
        "mssm_type": semantic_definition.get("fields", {})
        .get("MSSM", {})
        .get("type"),
        "mssm_length": semantic_definition.get("fields", {})
        .get("MSSM", {})
        .get("length"),
        "mssm_value_domain_present": semantic_definition.get("notes", {}).get(
            "mssm_value_domain_present"
        ),
        "candidate_non_blank_counts": {
            field: (semantic_profiles.get(field) or {}).get("non_blank_count")
            for field in ("PZWH", "SM", "DLBZ", "JQDLMC")
        },
        "candidate_statuses": semantic_candidates,
        "next_business_inputs": semantic_audit.get("business_input_minimum", []),
    }
    proposal_preview = None
    strategy_sha256 = None
    transformation_blockers: list[str] = []
    semantic_blockers = [
        f"semantic_derivation_evidence_missing.{target}"
        for target in ("SJNF", "MSSM")
        if not semantic_candidates.get(target, {}).get("permitted_source_fields")
    ]
    if not freeze["valid"]:
        transformation_blockers.append("freeze_manifest_invalid")
    transformation_blockers.extend(semantic_blockers)
    if strategy is None:
        transformation_blockers.extend(
            packet_transformation_blockers
            if decision_packet is not None
            else ["transformation_strategy_missing"]
        )
    else:
        _validate_strategy_source_admission(
            strategy=strategy,
            diagnostic=diagnostic,
            semantic_candidates=semantic_candidates,
        )
        strategy_sha256 = canonical_json_fingerprint(strategy.model_dump(mode="json"))
        proposal = build_jqdltb_transformation_contract(
            tenant_id=baseline.tenant_id,
            mode=JqdltbTransformationMode.DRY_RUN,
            source_resource_version_id=baseline.source_resource_version_id,
            source_resource_urn=baseline.source_resource_urn,
            archive_sha256=baseline.archive_sha256,
            bundle_sha256=baseline.bundle_sha256,
            standard_version_ref=baseline.standard_version_ref,
            standard_fingerprint=baseline.standard_fingerprint,
            diagnostic_sha256=baseline.diagnostic_sha256,
            semantic_candidate_audit_sha256=semantic_audit_sha256,
            canonical_key=strategy.canonical_key,
            nonpositive_area_policy=strategy.nonpositive_area_policy,
            business_correction_resource_version_id=(
                strategy.business_correction_resource_version_id
            ),
            business_correction_sha256=strategy.business_correction_sha256,
            area_deviation_policy=strategy.area_deviation_policy,
            geometry_area_rule_ref=strategy.geometry_area_rule_ref,
            geometry_area_rule_sha256=strategy.geometry_area_rule_sha256,
            derivation_contracts=strategy.derivation_contracts,
            created_by="workload:ar0-readiness",
            created_at=baseline.created_at,
        )
        proposal_preview = {
            "plan_sha256": proposal.plan_sha256,
            "approval_context": proposal.approval_context(),
        }

    approvals = manifest.get("approvals") or {}
    environment_owner = approvals.get("environment_owner") or {}
    promotion_blockers = list(freeze["unresolved_approvals"])
    promotion_blockers.extend(semantic_blockers)
    promotion_blockers.extend(
        f"environment_owner.{environment}_missing"
        for environment in ("staging", "production")
        if environment_owner.get(environment) is None
    )
    if freeze["source_quality_verdict"] != "passed":
        promotion_blockers.append("source_quality_not_passed")
    if not (manifest.get("evidence") or {}).get("data_product_version_created"):
        promotion_blockers.append("data_product_version_not_created")
    if strategy is None:
        promotion_blockers.extend(
            packet_transformation_blockers + packet_promotion_blockers
            if decision_packet is not None
            else ["transformation_strategy_missing"]
        )
    else:
        promotion_blockers.extend(packet_promotion_blockers)
        promotion_blockers.append("transformation_approval_missing")
    promotion_blockers = list(dict.fromkeys(promotion_blockers))

    identities = {
        "source_resource_version_id": str(baseline.source_resource_version_id),
        "archive_sha256": baseline.archive_sha256,
        "bundle_sha256": baseline.bundle_sha256,
        "standard_version_ref": baseline.standard_version_ref,
        "standard_fingerprint": baseline.standard_fingerprint,
        "diagnostic_sha256": diagnostic_sha256,
        "semantic_candidate_audit_sha256": semantic_audit_sha256,
        "strategy_sha256": strategy_sha256,
    }
    if decision_packet is not None:
        identities["decision_packet_sha256"] = decision_packet.packet_sha256

    report = {
        "schema": "gda.jqdltb_transformation_approval_readiness.v1",
        "scope": "read_only_preflight",
        "authority_state_created": False,
        "source_bytes_modified": False,
        "freeze": {
            "manifest_id": freeze["manifest_id"],
            "status": freeze["status"],
            "valid": freeze["valid"],
            "promotion_ready": freeze["promotion_ready"],
        },
        "identities": identities,
        "decision_requirements": decisions,
        "transformation_proposal": {
            "ready": not transformation_blockers,
            "blockers": transformation_blockers,
            "preview": proposal_preview,
            "next_action": (
                (
                    "run prepare with this exact decision packet"
                    if decision_packet is not None
                    else "run prepare with this exact strategy"
                )
                if not transformation_blockers
                else (
                    "submit the five transformation decisions in the decision packet"
                    if decision_packet is not None
                    else "provide a complete business-selected strategy"
                )
            ),
        },
        "product_promotion": {
            "ready": False,
            "blockers": promotion_blockers,
        },
    }
    if decision_packet is not None and packet_validation is not None:
        report["decision_packet"] = {
            "packet_id": decision_packet.packet_id,
            "status": decision_packet.status.value,
            "packet_sha256": decision_packet.packet_sha256,
            "validation_sha256": packet_validation["validation_sha256"],
            "identity_bound": packet_validation["identity_bound"],
            "strategy_ready": packet_validation["strategy_ready"],
            "transformation_blockers": packet_validation["transformation_blockers"],
            "promotion_blockers": packet_validation["promotion_blockers"],
        }
    return report | {"readiness_sha256": canonical_json_fingerprint(report)}


def _packet_identity(
    baseline: JqdltbTransformationContract,
    semantic_audit: dict[str, Any],
) -> JqdltbDecisionIdentity:
    return JqdltbDecisionIdentity(
        source_resource_version_id=baseline.source_resource_version_id,
        archive_sha256=baseline.archive_sha256,
        bundle_sha256=baseline.bundle_sha256,
        standard_version_ref=baseline.standard_version_ref,
        standard_fingerprint=baseline.standard_fingerprint,
        diagnostic_sha256=baseline.diagnostic_sha256,
        semantic_candidate_audit_sha256=_semantic_audit_sha256(semantic_audit),
    )


def _packet_evidence(
    *,
    ref: str,
    sha256: str,
    digest_kind: str,
    extraction_method: str,
    identity: JqdltbDecisionIdentity,
) -> JqdltbDecisionEvidence:
    return JqdltbDecisionEvidence(
        evidence_ref=ref,
        evidence_sha256=sha256,
        digest_kind=digest_kind,
        extraction_method=extraction_method,
        identity=identity,
    )


def build_decision_packet(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    semantic_audit_path: Path = DEFAULT_SEMANTIC_AUDIT,
    packet_id: str = "jqdltb-ar0-business-decisions-v1",
    created_by: str = "workload:ar0-decision-intake",
    created_at: datetime | None = None,
) -> JqdltbDecisionPacket:
    """Create a draft packet from the currently frozen, read-only evidence."""

    manifest_path = _absolute(manifest_path)
    baseline_path = _absolute(baseline_path)
    diagnostic_path = _absolute(diagnostic_path)
    semantic_audit_path = _absolute(semantic_audit_path)
    manifest = _read_json(manifest_path)
    baseline = JqdltbTransformationContract.model_validate(_read_json(baseline_path))
    _validate_baseline_manifest_binding(manifest=manifest, baseline=baseline)
    diagnostic = _read_json(diagnostic_path)
    semantic_audit = _read_json(semantic_audit_path)
    diagnostic_sha256 = _diagnostic_sha256(diagnostic)
    if diagnostic_sha256 != baseline.diagnostic_sha256:
        raise ValueError("baseline and diagnostic identities differ")
    audit_sha256, _ = _validate_semantic_audit_binding(
        baseline=baseline,
        semantic_audit=semantic_audit,
        expected_sha256=(manifest.get("evidence") or {}).get(
            "semantic_candidate_audit_sha256"
        ),
    )
    identity = _packet_identity(baseline, semantic_audit)
    diagnostic_ref = str(diagnostic_path.relative_to(REPO_ROOT))
    semantic_ref = str(semantic_audit_path.relative_to(REPO_ROOT))
    manifest_ref = str(manifest_path.relative_to(REPO_ROOT))
    diagnostic_evidence = _packet_evidence(
        ref=f"file:{diagnostic_ref}",
        sha256=diagnostic_sha256,
        digest_kind="canonical_json_sha256",
        extraction_method="canonical_json_fingerprint(report without diagnostic_sha256)",
        identity=identity,
    )
    semantic_evidence = _packet_evidence(
        ref=f"file:{semantic_ref}",
        sha256=audit_sha256,
        digest_kind="canonical_json_sha256",
        extraction_method="canonical_json_fingerprint(report without report_sha256)",
        identity=identity,
    )
    manifest_evidence = _packet_evidence(
        ref=f"file:{manifest_ref}",
        sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        digest_kind="content_sha256",
        extraction_method="SHA-256 of the exact evidence bytes",
        identity=identity,
    )
    approvals = manifest.get("approvals") or {}
    environment_owner = approvals.get("environment_owner") or {}
    rows = {
        "canonical_key": (
            "TBBH is complete and unique in the frozen diagnostic",
            "unassigned:chongqing-jqdltb-business",
            diagnostic_evidence,
        ),
        "nonpositive_area_policy": (
            "TBMJ/TBDLMJ each contain 6 non-positive records",
            "unassigned:chongqing-jqdltb-business",
            diagnostic_evidence,
        ),
        "area_deviation_policy": (
            "7 records exceed the area tolerance; 2 exceed 10%",
            "unassigned:chongqing-jqdltb-business",
            diagnostic_evidence,
        ),
        "SJNF": (
            "no authoritative production-year source is admitted",
            "unassigned:chongqing-jqdltb-business",
            semantic_evidence,
        ),
        "MSSM": (
            "no DLTB MSSM Char(2) value domain or row rule is available",
            "unassigned:chongqing-jqdltb-business",
            semantic_evidence,
        ),
        "business_steward": (
            str(approvals.get("business_steward") or "pending_assignment"),
            "unassigned:chongqing-jqdltb-business",
            manifest_evidence,
        ),
        "license_status": (
            str(approvals.get("license_status") or "pending_internal_evaluation_only"),
            "unassigned:data-governance",
            manifest_evidence,
        ),
        "slo_on_call": (
            str(approvals.get("slo_on_call") or "pending_approval"),
            "unassigned:platform-operations",
            manifest_evidence,
        ),
        "environment_owner.staging": (
            str(environment_owner.get("staging") or "pending_assignment"),
            "unassigned:environment-operations",
            manifest_evidence,
        ),
        "environment_owner.production": (
            str(environment_owner.get("production") or "pending_assignment"),
            "unassigned:environment-operations",
            manifest_evidence,
        ),
    }
    decisions = tuple(
        JqdltbDecision(
            target=target,
            status=JqdltbDecisionStatus.PENDING_BUSINESS_EVIDENCE,
            current_state=current_state,
            owner_ref=owner_ref,
            evidence=evidence,
        )
        for target, (current_state, owner_ref, evidence) in rows.items()
    )
    return build_jqdltb_decision_packet(
        packet_id=packet_id,
        identity=identity,
        decisions=decisions,
        created_by=created_by,
        created_at=created_at or datetime.now().astimezone(),
    )


def validate_decision_packet(
    packet: JqdltbDecisionPacket,
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    semantic_audit_path: Path = DEFAULT_SEMANTIC_AUDIT,
) -> dict[str, Any]:
    """Validate packet identity and, when submitted, compile its strategy in memory."""

    manifest = _read_json(_absolute(manifest_path))
    baseline = JqdltbTransformationContract.model_validate(
        _read_json(_absolute(baseline_path))
    )
    _validate_baseline_manifest_binding(manifest=manifest, baseline=baseline)
    diagnostic = _read_json(_absolute(diagnostic_path))
    semantic_audit = _read_json(_absolute(semantic_audit_path))
    diagnostic_sha256 = _diagnostic_sha256(diagnostic)
    audit_sha256, semantic_candidates = _validate_semantic_audit_binding(
        baseline=baseline,
        semantic_audit=semantic_audit,
        expected_sha256=(manifest.get("evidence") or {}).get(
            "semantic_candidate_audit_sha256"
        ),
    )
    expected_identity = _packet_identity(baseline, semantic_audit)
    if packet.identity != expected_identity:
        raise ValueError(
            "JQDLTB decision packet identity does not match the frozen baseline"
        )
    if (
        diagnostic_sha256 != baseline.diagnostic_sha256
        or audit_sha256 != packet.identity.semantic_candidate_audit_sha256
    ):
        raise ValueError("JQDLTB decision packet evidence identity drifted")
    for decision in packet.decisions:
        evidence = decision.evidence
        if evidence is None or not evidence.evidence_ref.startswith("file:"):
            raise ValueError(f"JQDLTB decision evidence ref is not a local file: {decision.target}")
        evidence_path = REPO_ROOT / evidence.evidence_ref.removeprefix("file:")
        if not evidence_path.is_file() or not evidence_path.resolve().is_relative_to(REPO_ROOT):
            raise ValueError(f"JQDLTB decision evidence file is unavailable: {decision.target}")
        if evidence.digest_kind == "content_sha256":
            actual_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        else:
            evidence_payload = _read_json(evidence_path)
            digest_field = (
                "diagnostic_sha256"
                if "diagnostic_sha256" in evidence_payload
                else "report_sha256"
                if "report_sha256" in evidence_payload
                else None
            )
            if digest_field is None:
                raise ValueError(
                    f"JQDLTB canonical evidence has no fingerprint field: {decision.target}"
                )
            observed = evidence_payload.pop(digest_field)
            actual_sha256 = canonical_json_fingerprint(evidence_payload)
            if observed != actual_sha256:
                raise ValueError(
                    f"JQDLTB canonical evidence fingerprint is invalid: {decision.target}"
                )
        if actual_sha256 != evidence.evidence_sha256:
            raise ValueError(f"JQDLTB decision evidence SHA-256 drifted: {decision.target}")
    blocker_statuses = {
        item.target: item.status.value
        for item in packet.decisions
        if item.status
        not in {
            JqdltbDecisionStatus.ACCEPTED,
            JqdltbDecisionStatus.SUBMITTED,
        }
    }
    result: dict[str, Any] = {
        "schema": "gda.jqdltb_decision_packet_validation.v1",
        "packet_id": packet.packet_id,
        "packet_sha256": packet.packet_sha256,
        "status": packet.status.value,
        "identity_bound": True,
        "strategy_ready": False,
        "blockers": list(blocker_statuses),
        "transformation_blockers": {
            target: blocker_statuses[target]
            for target in TRANSFORMATION_DECISION_TARGETS
            if target in blocker_statuses
        },
        "promotion_blockers": {
            target: blocker_statuses[target]
            for target in PROMOTION_DECISION_TARGETS
            if target in blocker_statuses
        },
    }
    if packet.status is JqdltbDecisionPacketStatus.SUBMITTED:
        if not result["transformation_blockers"]:
            strategy = packet.to_strategy()
            _validate_strategy_source_admission(
                strategy=strategy,
                diagnostic=diagnostic,
                semantic_candidates=semantic_candidates,
            )
            result["strategy_ready"] = True
            result["strategy_sha256"] = canonical_json_fingerprint(
                strategy.model_dump(mode="json")
            )
    return result | {"validation_sha256": canonical_json_fingerprint(result)}


def submit_decision_packet(
    *,
    draft_path: Path,
    decisions_path: Path,
    submitted_by: str,
    submitted_at: datetime,
    manifest_path: Path = DEFAULT_MANIFEST,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    semantic_audit_path: Path = DEFAULT_SEMANTIC_AUDIT,
) -> JqdltbDecisionPacket:
    """Apply an explicit human decision file to a frozen draft packet.

    The decision file only patches decision values and their owner/binding
    fields.  Frozen evidence and packet identity are copied from the draft;
    unknown targets or fields fail before an output packet is written.
    """

    draft = JqdltbDecisionPacket.model_validate(_read_json(_absolute(draft_path)))
    if draft.status is not JqdltbDecisionPacketStatus.DRAFT:
        raise ValueError("only a draft JQDLTB decision packet can be submitted")
    validate_decision_packet(
        draft,
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        diagnostic_path=diagnostic_path,
        semantic_audit_path=semantic_audit_path,
    )
    patches = _read_decision_patches(decisions_path)
    submitted_decisions = _apply_decision_patches(draft, patches)

    packet = build_jqdltb_decision_packet(
        packet_id=draft.packet_id,
        identity=draft.identity,
        decisions=tuple(submitted_decisions),
        created_by=draft.created_by,
        created_at=draft.created_at,
        status=JqdltbDecisionPacketStatus.SUBMITTED,
        submitted_by=submitted_by,
        submitted_at=submitted_at,
    )
    validate_decision_packet(
        packet,
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        diagnostic_path=diagnostic_path,
        semantic_audit_path=semantic_audit_path,
    )
    return packet


def _read_decision_patches(decisions_path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json(_absolute(decisions_path))
    if set(payload) != {"decisions"}:
        raise ValueError("decision submission file must contain only a decisions object")
    patches = payload.get("decisions")
    if not isinstance(patches, dict) or not patches:
        raise ValueError("decision submission file must contain at least one decision")
    if not all(
        isinstance(target, str) and isinstance(patch, dict)
        for target, patch in patches.items()
    ):
        raise ValueError("decision submission targets and patches must be objects")
    return patches


def _apply_decision_patches(
    base: JqdltbDecisionPacket,
    patches: dict[str, dict[str, Any]],
    *,
    reject_existing_submitted: bool = False,
) -> list[JqdltbDecision]:
    required_targets = {item.target for item in base.decisions}
    unknown_targets = set(patches) - required_targets
    if unknown_targets:
        raise ValueError(
            "decision submission contains unknown targets: "
            + ", ".join(sorted(str(target) for target in unknown_targets))
        )

    submitted_decisions: list[JqdltbDecision] = []
    for pending in base.decisions:
        patch = patches.get(pending.target)
        if patch is None:
            submitted_decisions.append(pending)
            continue
        if reject_existing_submitted and pending.status in {
            JqdltbDecisionStatus.SUBMITTED,
            JqdltbDecisionStatus.ACCEPTED,
        }:
            raise ValueError(
                f"incremental decision update cannot overwrite submitted target: {pending.target}"
            )
        unknown_fields = set(patch) - DECISION_PATCH_FIELDS
        if unknown_fields:
            raise ValueError(
                f"decision patch contains unsupported fields for {pending.target}: "
                + ", ".join(sorted(str(field) for field in unknown_fields))
            )
        if "selected_value" not in patch:
            raise ValueError(
                f"submitted decision requires selected_value: {pending.target}"
            )
        if "owner_ref" not in patch:
            raise ValueError(f"submitted decision requires owner_ref: {pending.target}")
        decision_payload = pending.model_dump(mode="json")
        decision_payload.update(patch)
        semantic_deferred = (
            pending.target in {"SJNF", "MSSM"}
            and patch.get("selected_value") == "quarantine_until_authority_exists"
        )
        correction_deferred = (
            pending.target == "nonpositive_area_policy"
            and patch.get("selected_value") == "business_correction"
            and not patch.get("selected_resource_version_id")
            and not patch.get("selected_artifact_sha256")
        )
        decision_payload["status"] = (
            JqdltbDecisionStatus.DEFERRED.value
            if semantic_deferred or correction_deferred
            else JqdltbDecisionStatus.SUBMITTED.value
        )
        submitted_decisions.append(JqdltbDecision.model_validate(decision_payload))
    return submitted_decisions


def update_submitted_decision_packet(
    *,
    base_path: Path,
    decisions_path: Path,
    submitted_by: str,
    submitted_at: datetime,
    manifest_path: Path = DEFAULT_MANIFEST,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    semantic_audit_path: Path = DEFAULT_SEMANTIC_AUDIT,
) -> JqdltbDecisionPacket:
    """Add decisions to a previously submitted packet without losing prior choices."""

    base = JqdltbDecisionPacket.model_validate(_read_json(_absolute(base_path)))
    if base.status is not JqdltbDecisionPacketStatus.SUBMITTED:
        raise ValueError("incremental decision update requires a submitted packet")
    if base.submitted_at is not None and submitted_at <= base.submitted_at:
        raise ValueError("incremental decision update requires a later submission time")
    validate_decision_packet(
        base,
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        diagnostic_path=diagnostic_path,
        semantic_audit_path=semantic_audit_path,
    )
    patches = _read_decision_patches(decisions_path)
    decisions = _apply_decision_patches(
        base,
        patches,
        reject_existing_submitted=True,
    )

    packet = build_jqdltb_decision_packet(
        packet_id=base.packet_id,
        identity=base.identity,
        decisions=tuple(decisions),
        created_by=base.created_by,
        created_at=base.created_at,
        status=JqdltbDecisionPacketStatus.SUBMITTED,
        submitted_by=submitted_by,
        submitted_at=submitted_at,
    )
    validate_decision_packet(
        packet,
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        diagnostic_path=diagnostic_path,
        semantic_audit_path=semantic_audit_path,
    )
    return packet


def _build_approval(
    *,
    baseline: JqdltbTransformationContract,
    strategy: JqdltbTransformationStrategy,
    case_id: str,
    requester_subject: str,
    request_reason: str,
    created_by: str,
    proposed_at: datetime,
    requested_at: datetime,
    expires_at: datetime,
    semantic_candidate_audit_sha256: str | None = None,
) -> tuple[JqdltbTransformationContract, ApprovalCase]:
    """Build proposal and pending case after admission has already been checked.

    This is intentionally private.  Production callers must use
    :func:`prepare_approval`, which binds the strategy to the frozen semantic
    audit before creating any approval artifact.
    """

    if baseline.mode is not JqdltbTransformationMode.APPROVAL_REQUIRED:
        raise ValueError("JQDLTB approval preparation requires the unresolved baseline")
    proposal = build_jqdltb_transformation_contract(
        tenant_id=baseline.tenant_id,
        mode=JqdltbTransformationMode.DRY_RUN,
        source_resource_version_id=baseline.source_resource_version_id,
        source_resource_urn=baseline.source_resource_urn,
        archive_sha256=baseline.archive_sha256,
        bundle_sha256=baseline.bundle_sha256,
        standard_version_ref=baseline.standard_version_ref,
        standard_fingerprint=baseline.standard_fingerprint,
        diagnostic_sha256=baseline.diagnostic_sha256,
        semantic_candidate_audit_sha256=semantic_candidate_audit_sha256,
        canonical_key=strategy.canonical_key,
        nonpositive_area_policy=strategy.nonpositive_area_policy,
        business_correction_resource_version_id=(
            strategy.business_correction_resource_version_id
        ),
        business_correction_sha256=strategy.business_correction_sha256,
        area_deviation_policy=strategy.area_deviation_policy,
        geometry_area_rule_ref=strategy.geometry_area_rule_ref,
        geometry_area_rule_sha256=strategy.geometry_area_rule_sha256,
        derivation_contracts=strategy.derivation_contracts,
        created_by=created_by,
        created_at=proposed_at,
    )
    approval_case = build_jqdltb_transformation_approval_case(
        proposal,
        case_id=case_id,
        requester_subject=requester_subject,
        request_reason=request_reason,
        requested_at=requested_at,
        expires_at=expires_at,
    )
    return proposal, approval_case


def prepare_approval(
    *,
    baseline: JqdltbTransformationContract,
    strategy: JqdltbTransformationStrategy,
    case_id: str,
    requester_subject: str,
    request_reason: str,
    created_by: str,
    proposed_at: datetime,
    requested_at: datetime,
    expires_at: datetime,
    manifest_path: Path = DEFAULT_MANIFEST,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    semantic_audit_path: Path = DEFAULT_SEMANTIC_AUDIT,
) -> tuple[JqdltbTransformationContract, ApprovalCase]:
    """Create approval artifacts only after frozen semantic admission.

    The evidence is reloaded here rather than accepted from readiness output,
    so a caller cannot turn a stale or hand-built candidate map into an
    ApprovalCase.  The resulting proposal remains bound to the same source,
    standard and diagnostic identities as the unresolved baseline.
    """

    manifest_path = _absolute(manifest_path)
    freeze = verify_manifest(manifest_path)
    if not freeze["valid"]:
        raise ValueError("JQDLTB approval preparation requires a valid freeze manifest")
    manifest = _read_json(manifest_path)
    _validate_baseline_manifest_binding(manifest=manifest, baseline=baseline)
    diagnostic = _read_json(_absolute(diagnostic_path))
    semantic_audit = _read_json(_absolute(semantic_audit_path))
    diagnostic_sha256 = _diagnostic_sha256(diagnostic)
    if baseline.diagnostic_sha256 != diagnostic_sha256:
        raise ValueError("baseline and diagnostic identities differ")
    audit_sha256, semantic_candidates = _validate_semantic_audit_binding(
        baseline=baseline,
        semantic_audit=semantic_audit,
        expected_sha256=(manifest.get("evidence") or {}).get(
            "semantic_candidate_audit_sha256"
        ),
    )
    _validate_strategy_source_admission(
        strategy=strategy,
        diagnostic=diagnostic,
        semantic_candidates=semantic_candidates,
    )
    return _build_approval(
        baseline=baseline,
        strategy=strategy,
        case_id=case_id,
        requester_subject=requester_subject,
        request_reason=request_reason,
        created_by=created_by,
        proposed_at=proposed_at,
        requested_at=requested_at,
        expires_at=expires_at,
        semantic_candidate_audit_sha256=audit_sha256,
    )


def compile_approved(
    *,
    proposal: JqdltbTransformationContract,
    approval_case: ApprovalCase,
    created_by: str,
    compiled_at: datetime,
) -> JqdltbTransformationContract:
    return compile_jqdltb_executable_contract(
        proposal,
        approval_case=approval_case,
        created_by=created_by,
        created_at=compiled_at,
    )


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _add_prepare_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("prepare")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument(
        "--semantic-audit", type=Path, default=DEFAULT_SEMANTIC_AUDIT
    )
    strategy_inputs = parser.add_mutually_exclusive_group(required=True)
    strategy_inputs.add_argument("--strategy", type=Path)
    strategy_inputs.add_argument(
        "--decision-packet",
        type=Path,
        help="submitted JQDLTB decision packet; validated and converted to Strategy",
    )
    parser.add_argument("--proposal-output", type=Path, required=True)
    parser.add_argument("--approval-output", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--requester-subject", required=True)
    parser.add_argument("--request-reason", required=True)
    parser.add_argument("--created-by", default="workload:ar0-contract-builder")
    parser.add_argument("--proposed-at", required=True, type=_datetime)
    parser.add_argument("--requested-at", required=True, type=_datetime)
    parser.add_argument("--expires-at", required=True, type=_datetime)


def _add_compile_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("compile")
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--approval-case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-by", default="workload:ar0-contract-compiler")
    parser.add_argument("--compiled-at", required=True, type=_datetime)


def _add_readiness_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("readiness")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument(
        "--semantic-audit", type=Path, default=DEFAULT_SEMANTIC_AUDIT
    )
    strategy_inputs = parser.add_mutually_exclusive_group()
    strategy_inputs.add_argument("--strategy", type=Path)
    strategy_inputs.add_argument(
        "--decision-packet",
        type=Path,
        help="JQDLTB decision packet validated against frozen evidence",
    )
    parser.add_argument("--output", type=Path)


def _add_decision_packet_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "decision-packet",
        help="emit a draft business decision packet from frozen evidence",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--semantic-audit", type=Path, default=DEFAULT_SEMANTIC_AUDIT)
    parser.add_argument("--packet-id", default="jqdltb-ar0-business-decisions-v1")
    parser.add_argument("--created-by", default="workload:ar0-decision-intake")
    parser.add_argument("--created-at", type=_datetime)
    parser.add_argument("--output", type=Path, required=True)


def _add_validate_packet_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "validate-decision-packet",
        help="validate a packet against the frozen baseline and evidence",
    )
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--semantic-audit", type=Path, default=DEFAULT_SEMANTIC_AUDIT)
    parser.add_argument("--output", type=Path)


def _add_submit_packet_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "submit-decision-packet",
        help="apply explicit human decisions to a frozen draft packet",
    )
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument(
        "--decisions",
        type=Path,
        required=True,
        help="JSON object with a decisions map; omitted targets remain pending",
    )
    parser.add_argument("--submitted-by", required=True)
    parser.add_argument("--submitted-at", required=True, type=_datetime)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--semantic-audit", type=Path, default=DEFAULT_SEMANTIC_AUDIT)
    parser.add_argument("--output", type=Path, required=True)


def _add_update_submitted_packet_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "update-submitted-decision-packet",
        help="add explicit human decisions to a previously submitted packet",
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument(
        "--decisions",
        type=Path,
        required=True,
        help="JSON object with new decisions; already submitted targets cannot be overwritten",
    )
    parser.add_argument("--submitted-by", required=True)
    parser.add_argument("--submitted-at", required=True, type=_datetime)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--semantic-audit", type=Path, default=DEFAULT_SEMANTIC_AUDIT)
    parser.add_argument("--output", type=Path, required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_prepare_parser(subparsers)
    _add_compile_parser(subparsers)
    _add_readiness_parser(subparsers)
    _add_decision_packet_parser(subparsers)
    _add_validate_packet_parser(subparsers)
    _add_submit_packet_parser(subparsers)
    _add_update_submitted_packet_parser(subparsers)
    subparsers.add_parser("schema")
    subparsers.add_parser("decision-schema")
    args = parser.parse_args(argv)

    if args.command == "schema":
        print(
            json.dumps(
                JqdltbTransformationStrategy.model_json_schema(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "decision-schema":
        print(
            json.dumps(
                JqdltbDecisionPacket.model_json_schema(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "readiness":
        strategy_path = _absolute(args.strategy) if args.strategy else None
        decision_packet_path = (
            _absolute(args.decision_packet) if args.decision_packet else None
        )
        result = build_readiness_report(
            manifest_path=_absolute(args.manifest),
            baseline_path=_absolute(args.baseline),
            diagnostic_path=_absolute(args.diagnostic),
            semantic_audit_path=_absolute(args.semantic_audit),
            strategy=(
                JqdltbTransformationStrategy.model_validate(_read_json(strategy_path))
                if strategy_path is not None
                else None
            ),
            decision_packet=(
                JqdltbDecisionPacket.model_validate(
                    _read_json(decision_packet_path)
                )
                if decision_packet_path is not None
                else None
            ),
        )
        if args.output is not None:
            output = _absolute(args.output)
            inputs = {
                _absolute(args.manifest).resolve(),
                _absolute(args.baseline).resolve(),
                _absolute(args.diagnostic).resolve(),
                _absolute(args.semantic_audit).resolve(),
            }
            if strategy_path is not None:
                inputs.add(strategy_path.resolve())
            if decision_packet_path is not None:
                inputs.add(decision_packet_path.resolve())
            if output.resolve() in inputs:
                raise ValueError("readiness output must not overwrite an input")
            _write_json(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "decision-packet":
        output = _absolute(args.output)
        packet = build_decision_packet(
            manifest_path=args.manifest,
            baseline_path=args.baseline,
            diagnostic_path=args.diagnostic,
            semantic_audit_path=args.semantic_audit,
            packet_id=args.packet_id,
            created_by=args.created_by,
            created_at=args.created_at,
        )
        _write_json(output, packet.model_dump(mode="json"))
        result = {
            "status": packet.status.value,
            "packet_id": packet.packet_id,
            "packet_sha256": packet.packet_sha256,
            "output": str(output),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "validate-decision-packet":
        packet = JqdltbDecisionPacket.model_validate(
            _read_json(_absolute(args.packet))
        )
        result = validate_decision_packet(
            packet,
            manifest_path=args.manifest,
            baseline_path=args.baseline,
            diagnostic_path=args.diagnostic,
            semantic_audit_path=args.semantic_audit,
        )
        if args.output is not None:
            _write_json(_absolute(args.output), result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "submit-decision-packet":
        draft_path = _absolute(args.draft)
        decisions_path = _absolute(args.decisions)
        output = _absolute(args.output)
        if output.resolve() in {draft_path.resolve(), decisions_path.resolve()}:
            raise ValueError("submitted packet output must not overwrite an input")
        packet = submit_decision_packet(
            draft_path=draft_path,
            decisions_path=decisions_path,
            submitted_by=args.submitted_by,
            submitted_at=args.submitted_at,
            manifest_path=_absolute(args.manifest),
            baseline_path=_absolute(args.baseline),
            diagnostic_path=_absolute(args.diagnostic),
            semantic_audit_path=_absolute(args.semantic_audit),
        )
        validation = validate_decision_packet(
            packet,
            manifest_path=_absolute(args.manifest),
            baseline_path=_absolute(args.baseline),
            diagnostic_path=_absolute(args.diagnostic),
            semantic_audit_path=_absolute(args.semantic_audit),
        )
        _write_json(output, packet.model_dump(mode="json"))
        result = {
            "status": packet.status.value,
            "packet_id": packet.packet_id,
            "packet_sha256": packet.packet_sha256,
            "strategy_ready": validation["strategy_ready"],
            "output": str(output),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "update-submitted-decision-packet":
        base_path = _absolute(args.base)
        decisions_path = _absolute(args.decisions)
        output = _absolute(args.output)
        if output.resolve() in {base_path.resolve(), decisions_path.resolve()}:
            raise ValueError("updated packet output must not overwrite an input")
        packet = update_submitted_decision_packet(
            base_path=base_path,
            decisions_path=decisions_path,
            submitted_by=args.submitted_by,
            submitted_at=args.submitted_at,
            manifest_path=_absolute(args.manifest),
            baseline_path=_absolute(args.baseline),
            diagnostic_path=_absolute(args.diagnostic),
            semantic_audit_path=_absolute(args.semantic_audit),
        )
        validation = validate_decision_packet(
            packet,
            manifest_path=_absolute(args.manifest),
            baseline_path=_absolute(args.baseline),
            diagnostic_path=_absolute(args.diagnostic),
            semantic_audit_path=_absolute(args.semantic_audit),
        )
        _write_json(output, packet.model_dump(mode="json"))
        result = {
            "status": packet.status.value,
            "packet_id": packet.packet_id,
            "packet_sha256": packet.packet_sha256,
            "strategy_ready": validation["strategy_ready"],
            "output": str(output),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "prepare":
        baseline_path = _absolute(args.baseline)
        manifest_path = _absolute(args.manifest)
        diagnostic_path = _absolute(args.diagnostic)
        semantic_audit_path = _absolute(args.semantic_audit)
        strategy_path = _absolute(args.strategy) if args.strategy else None
        decision_packet_path = (
            _absolute(args.decision_packet) if args.decision_packet else None
        )
        proposal_output = _absolute(args.proposal_output)
        approval_output = _absolute(args.approval_output)
        input_paths = {
            baseline_path.resolve(),
            manifest_path.resolve(),
            diagnostic_path.resolve(),
            semantic_audit_path.resolve(),
        }
        input_paths.update(
            path.resolve()
            for path in (strategy_path, decision_packet_path)
            if path is not None
        )
        output_paths = {proposal_output.resolve(), approval_output.resolve()}
        if len(output_paths) != 2 or input_paths & output_paths:
            raise ValueError(
                "proposal and ApprovalCase outputs must be distinct from all inputs"
            )
        baseline = JqdltbTransformationContract.model_validate(
            _read_json(baseline_path)
        )
        if strategy_path is not None:
            strategy = JqdltbTransformationStrategy.model_validate(
                _read_json(strategy_path)
            )
        else:
            decision_packet = JqdltbDecisionPacket.model_validate(
                _read_json(decision_packet_path)
            )
            validate_decision_packet(
                decision_packet,
                manifest_path=manifest_path,
                baseline_path=baseline_path,
                diagnostic_path=diagnostic_path,
                semantic_audit_path=semantic_audit_path,
            )
            strategy = decision_packet.to_strategy()
        proposal, approval_case = prepare_approval(
            baseline=baseline,
            strategy=strategy,
            case_id=args.case_id,
            requester_subject=args.requester_subject,
            request_reason=args.request_reason,
            created_by=args.created_by,
            proposed_at=args.proposed_at,
            requested_at=args.requested_at,
            expires_at=args.expires_at,
            manifest_path=manifest_path,
            diagnostic_path=diagnostic_path,
            semantic_audit_path=semantic_audit_path,
        )
        _write_json(proposal_output, proposal.model_dump(mode="json"))
        _write_json(approval_output, approval_case.model_dump(mode="json"))
        result = {
            "status": "awaiting_approval",
            "plan_sha256": proposal.plan_sha256,
            "proposal": str(proposal_output),
            "approval_case": str(approval_output),
        }
    else:
        proposal_path = _absolute(args.proposal)
        approval_path = _absolute(args.approval_case)
        output = _absolute(args.output)
        if output.resolve() in {proposal_path.resolve(), approval_path.resolve()}:
            raise ValueError("executable output must not overwrite approval inputs")
        contract = compile_approved(
            proposal=JqdltbTransformationContract.model_validate(
                _read_json(proposal_path)
            ),
            approval_case=ApprovalCase.model_validate(
                _read_json(approval_path)
            ),
            created_by=args.created_by,
            compiled_at=args.compiled_at,
        )
        _write_json(output, contract.model_dump(mode="json"))
        result = {
            "status": "executable",
            "plan_sha256": contract.plan_sha256,
            "contract_sha256": contract.contract_sha256,
            "output": str(output),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
