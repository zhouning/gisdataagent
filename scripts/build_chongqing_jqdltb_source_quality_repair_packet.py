#!/usr/bin/env python3
"""Build a read-only, business-facing repair-candidate packet for AR-0 JQDLTB.

The packet is an evidence-backed hand-off, not an approval artifact.  It makes
the remaining choices explicit, shows the aggregate impact of each permitted
option, and records exactly which blocker can be revisited after a decision.
No strategy, ApprovalCase, correction artifact, layer output, or
``DataProductVersion`` is created by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from data_agent.platform_contracts import canonical_json_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "config/freezes/ar0-first-vertical-slice-2026-08-22.json"
DEFAULT_BASELINE = (
    REPO_ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
)
DEFAULT_DIAGNOSTIC = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
DEFAULT_SEMANTIC_AUDIT = (
    REPO_ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
)
DEFAULT_IMPACT_PREVIEW = (
    REPO_ROOT / "docs/reports/jqdltb_transformation_impact_preview_2026-08-26.json"
)
DEFAULT_READINESS = (
    REPO_ROOT / "docs/reports/jqdltb_decision_packet_readiness_2026-08-26.json"
)
DEFAULT_DECISION_PACKET = (
    REPO_ROOT / "docs/reports/jqdltb_business_decision_packet_2026-08-26.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs/reports/jqdltb_source_quality_repair_candidate_packet_2026-08-30.json"
)
SCHEMA = "gda.jqdltb_source_quality_repair_candidate_packet.v1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _repo_ref(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(REPO_ROOT):
        raise ValueError(f"evidence path escapes repository: {path}")
    return f"file:{resolved.relative_to(REPO_ROOT)}"


def _content_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(path: Path, fingerprint_field: str) -> str:
    payload = _read_json(path)
    observed = payload.pop(fingerprint_field, None)
    if not isinstance(observed, str):
        raise ValueError(f"{path} has no {fingerprint_field}")
    calculated = canonical_json_fingerprint(payload)
    if observed != calculated:
        raise ValueError(f"{path} has an invalid {fingerprint_field}")
    return calculated


def _evidence(
    path: Path,
    *,
    fingerprint_field: str | None,
    role: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    canonical = (
        _canonical_sha256(path, fingerprint_field) if fingerprint_field else None
    )
    return {
        "role": role,
        "evidence_ref": _repo_ref(path),
        "content_sha256": _content_sha256(path),
        "canonical_sha256": canonical,
        "digest_kind": (
            "content_and_canonical_json_sha256"
            if canonical
            else "content_sha256"
        ),
        "extraction_method": (
            "SHA-256 exact bytes plus "
            f"canonical_json_fingerprint(report without {fingerprint_field})"
            if canonical
            else "SHA-256 of the exact evidence bytes"
        ),
        "identity": identity,
    }


def _scenario(preview: dict[str, Any], nonpositive: str, deviation: str) -> dict[str, Any]:
    for item in preview.get("matrix") or []:
        policy = item.get("policy") or {}
        if (
            policy.get("nonpositive_area_policy") == nonpositive
            and policy.get("area_deviation_policy") == deviation
        ):
            return item
    raise ValueError(f"impact preview scenario is missing: {nonpositive}/{deviation}")


def _option(
    *,
    value: str,
    label: str,
    effect: dict[str, Any],
    required_evidence: list[str],
    closes: list[str],
    remains: list[str],
) -> dict[str, Any]:
    return {
        "value": value,
        "label": label,
        "effect": effect,
        "required_evidence": required_evidence,
        "closes_blockers_when_accepted": closes,
        "blockers_remaining_after_acceptance": remains,
    }


def _decision(
    *,
    target: str,
    category: str,
    owner_ref: str,
    current_state: str,
    evidence_roles: list[str],
    options: list[dict[str, Any]],
    blocker: str,
) -> dict[str, Any]:
    return {
        "target": target,
        "category": category,
        "status": "pending_business_evidence",
        "owner_ref": owner_ref,
        "current_state": current_state,
        "evidence_roles": evidence_roles,
        "options": options,
        "selected_value": None,
        "selected_evidence": None,
        "fail_closed_if_missing": True,
        "gating_blocker": blocker,
    }


def _validate_inputs(
    *,
    manifest: dict[str, Any],
    baseline: dict[str, Any],
    diagnostic: dict[str, Any],
    semantic_audit: dict[str, Any],
    impact_preview: dict[str, Any],
    readiness: dict[str, Any],
    decision_packet: dict[str, Any],
    diagnostic_sha256: str,
    semantic_sha256: str,
    impact_sha256: str,
    readiness_sha256: str,
    packet_sha256: str,
) -> dict[str, Any]:
    manifest_identity = manifest.get("identities") or {}
    baseline_identity = {
        "source_resource_version_id": baseline.get("source_resource_version_id"),
        "archive_sha256": baseline.get("archive_sha256"),
        "bundle_sha256": baseline.get("bundle_sha256"),
        "standard_version_ref": baseline.get("standard_version_ref"),
        "standard_fingerprint": baseline.get("standard_fingerprint"),
        "diagnostic_sha256": baseline.get("diagnostic_sha256"),
        "semantic_candidate_audit_sha256": manifest.get("evidence", {}).get(
            "semantic_candidate_audit_sha256"
        ),
    }
    if baseline_identity["archive_sha256"] != manifest_identity.get("archive_sha256"):
        raise ValueError("baseline and manifest archive identity differ")
    if baseline_identity["bundle_sha256"] != manifest_identity.get("bundle_sha256"):
        raise ValueError("baseline and manifest bundle identity differ")
    if baseline_identity["diagnostic_sha256"] != diagnostic_sha256:
        raise ValueError("baseline and diagnostic identity differ")
    if baseline_identity["semantic_candidate_audit_sha256"] != semantic_sha256:
        raise ValueError("manifest and semantic audit identity differ")
    source = diagnostic.get("source") or {}
    if source.get("archive_sha256") != baseline_identity["archive_sha256"]:
        raise ValueError("diagnostic archive identity differs")
    if source.get("bundle_sha256") != baseline_identity["bundle_sha256"]:
        raise ValueError("diagnostic bundle identity differs")
    if impact_preview.get("schema") != "gda.jqdltb_transformation_impact_preview.v1":
        raise ValueError("unsupported impact preview schema")
    impact_identity = impact_preview.get("identities") or {}
    if impact_identity.get("diagnostic_sha256") != diagnostic_sha256:
        raise ValueError("impact preview diagnostic identity differs")
    if impact_identity.get("source_resource_version_id") != baseline_identity[
        "source_resource_version_id"
    ]:
        raise ValueError("impact preview source identity differs")
    if impact_preview.get("source_bytes_modified") is not False:
        raise ValueError("impact preview is not read-only")
    if impact_preview.get("authority_state_created") is not False:
        raise ValueError("impact preview created authority state")
    if impact_preview.get("layer_artifacts_written") is not False:
        raise ValueError("impact preview wrote layer artifacts")
    if len(impact_preview.get("matrix") or []) != 6:
        raise ValueError("impact preview must contain all six policy scenarios")
    if readiness.get("schema") != "gda.jqdltb_transformation_approval_readiness.v1":
        raise ValueError("unsupported readiness schema")
    if readiness.get("identities", {}).get("diagnostic_sha256") != diagnostic_sha256:
        raise ValueError("readiness diagnostic identity differs")
    if decision_packet.get("packet_sha256") != packet_sha256:
        raise ValueError("decision packet fingerprint differs")
    if decision_packet.get("status") != "draft":
        raise ValueError("repair candidate packet expects the current draft decision packet")
    return {
        "source_resource_version_id": baseline_identity["source_resource_version_id"],
        "archive_sha256": baseline_identity["archive_sha256"],
        "bundle_sha256": baseline_identity["bundle_sha256"],
        "standard_version_ref": baseline_identity["standard_version_ref"],
        "standard_fingerprint": baseline_identity["standard_fingerprint"],
        "diagnostic_sha256": diagnostic_sha256,
        "semantic_candidate_audit_sha256": semantic_sha256,
        "impact_preview_sha256": impact_sha256,
        "readiness_sha256": readiness_sha256,
        "decision_packet_sha256": packet_sha256,
        "manifest_id": manifest.get("manifest_id"),
        "baseline_contract_sha256": baseline.get("contract_sha256"),
    }


def build_packet(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    baseline_path: Path = DEFAULT_BASELINE,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
    semantic_audit_path: Path = DEFAULT_SEMANTIC_AUDIT,
    impact_preview_path: Path = DEFAULT_IMPACT_PREVIEW,
    readiness_path: Path = DEFAULT_READINESS,
    decision_packet_path: Path = DEFAULT_DECISION_PACKET,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    baseline = _read_json(baseline_path)
    diagnostic = _read_json(diagnostic_path)
    semantic_audit = _read_json(semantic_audit_path)
    impact_preview = _read_json(impact_preview_path)
    readiness = _read_json(readiness_path)
    decision_packet = _read_json(decision_packet_path)
    diagnostic_sha256 = _canonical_sha256(diagnostic_path, "diagnostic_sha256")
    semantic_sha256 = _canonical_sha256(semantic_audit_path, "report_sha256")
    impact_sha256 = _canonical_sha256(impact_preview_path, "preview_sha256")
    readiness_sha256 = _canonical_sha256(readiness_path, "readiness_sha256")
    packet_sha256 = _canonical_sha256(decision_packet_path, "packet_sha256")
    identity = _validate_inputs(
        manifest=manifest,
        baseline=baseline,
        diagnostic=diagnostic,
        semantic_audit=semantic_audit,
        impact_preview=impact_preview,
        readiness=readiness,
        decision_packet=decision_packet,
        diagnostic_sha256=diagnostic_sha256,
        semantic_sha256=semantic_sha256,
        impact_sha256=impact_sha256,
        readiness_sha256=readiness_sha256,
        packet_sha256=packet_sha256,
    )
    evidence = [
        _evidence(
            diagnostic_path,
            fingerprint_field="diagnostic_sha256",
            role="aggregate_source_quality_diagnostic",
            identity=identity,
        ),
        _evidence(
            semantic_audit_path,
            fingerprint_field="report_sha256",
            role="semantic_candidate_audit",
            identity=identity,
        ),
        _evidence(
            impact_preview_path,
            fingerprint_field="preview_sha256",
            role="transformation_impact_preview",
            identity=identity,
        ),
        _evidence(
            readiness_path,
            fingerprint_field="readiness_sha256",
            role="approval_readiness_preflight",
            identity=identity,
        ),
        _evidence(
            decision_packet_path,
            fingerprint_field="packet_sha256",
            role="draft_business_decision_packet",
            identity=identity,
        ),
    ]
    diagnostic_area = diagnostic.get("area_consistency") or {}
    numeric = {
        str(item.get("field")): int(item.get("nonpositive_count") or 0)
        for item in diagnostic.get("numeric_constraints") or []
    }
    semantic_candidates = (
        (semantic_audit.get("source_evidence") or {}).get("candidate_field_profiles")
        or {}
    )
    quarantine_preserve = _scenario(impact_preview, "quarantine", "preserve_source")
    quarantine_quarantine = _scenario(impact_preview, "quarantine", "quarantine")
    decisions = [
        _decision(
            target="canonical_key",
            category="transformation",
            owner_ref="unassigned:chongqing-jqdltb-business",
            current_state=(
                f"BSM is not unique; TBBH is complete and unique across "
                f"{int((diagnostic.get('source') or {}).get('feature_count') or 0):,} records"
            ),
            evidence_roles=["aggregate_source_quality_diagnostic"],
            options=[
                _option(
                    value="TBBH",
                    label="接受 TBBH 作为业务主键",
                    effect={
                        "candidate_records": int(
                            (diagnostic.get("source") or {}).get("feature_count") or 0
                        ),
                        "technical_candidate": "complete_unique",
                    },
                    required_evidence=["business owner sign-off bound to diagnostic identity"],
                    closes=["decision_packet.canonical_key.pending_business_evidence"],
                    remains=[
                        "nonpositive_area_policy",
                        "area_deviation_policy",
                        "SJNF",
                        "MSSM",
                        "source_quality_not_passed",
                    ],
                ),
                _option(
                    value="reject_and_rediagnose",
                    label="拒绝并提供新的权威键诊断",
                    effect={"candidate_records": None, "technical_candidate": "not_admitted"},
                    required_evidence=["new source-quality diagnostic and business key rationale"],
                    closes=[],
                    remains=["source_primary_key_not_unique", "all downstream gates"],
                ),
            ],
            blocker="decision_packet.canonical_key.pending_business_evidence",
        ),
        _decision(
            target="nonpositive_area_policy",
            category="transformation",
            owner_ref="unassigned:chongqing-jqdltb-business",
            current_state=(
                f"TBMJ has {numeric.get('TBMJ', 0)} non-positive records; "
                f"TBDLMJ has {numeric.get('TBDLMJ', 0)}; union is "
                f"{quarantine_preserve['observations']['nonpositive_area_union']}"
            ),
            evidence_roles=["aggregate_source_quality_diagnostic", "transformation_impact_preview"],
            options=[
                _option(
                    value="quarantine",
                    label="隔离非正面积记录",
                    effect={
                        "records_quarantined": quarantine_preserve["projection"][
                            "records_quarantined"
                        ],
                        "records_after_area_policy": quarantine_preserve["projection"][
                            "records_after_area_policy"
                        ],
                    },
                    required_evidence=["quarantine disposition and reason-code contract"],
                    closes=["decision_packet.nonpositive_area_policy.pending_business_evidence"],
                    remains=["source_numeric_constraints_failed_on_full_source", "SJNF", "MSSM"],
                ),
                _option(
                    value="business_correction",
                    label="提供业务更正值后再运行",
                    effect={"records_quarantined": None, "projection_exact": False},
                    required_evidence=[
                        "correction ResourceVersion id",
                        "correction content SHA-256",
                        "row-level TBBH plus TBMJ and TBDLMJ values",
                    ],
                    closes=["decision_packet.nonpositive_area_policy.pending_business_evidence"],
                    remains=["correction_artifact_missing_until_supplied", "SJNF", "MSSM"],
                ),
            ],
            blocker="decision_packet.nonpositive_area_policy.pending_business_evidence",
        ),
        _decision(
            target="area_deviation_policy",
            category="transformation",
            owner_ref="unassigned:chongqing-jqdltb-business",
            current_state=(
                f"{int(diagnostic_area.get('outside_tolerance_count') or 0)} records exceed the "
                "frozen area tolerance; "
                f"{int(diagnostic_area.get('over_10_percent_count') or 0)} exceed 10%"
            ),
            evidence_roles=["aggregate_source_quality_diagnostic", "transformation_impact_preview"],
            options=[
                _option(
                    value="preserve_source",
                    label="保留申报面积并记录偏差",
                    effect={
                        "records_with_area_policy": quarantine_preserve["projection"][
                            "records_after_area_policy"
                        ],
                        "records_quarantined": quarantine_preserve["projection"][
                            "records_quarantined"
                        ],
                        "deviation_records_retained": int(
                            diagnostic_area.get("outside_tolerance_count") or 0
                        ),
                    },
                    required_evidence=[
                        "business acceptance of declared-area authority and audit rule"
                    ],
                    closes=["decision_packet.area_deviation_policy.pending_business_evidence"],
                    remains=["area_deviation_quality_observation", "SJNF", "MSSM"],
                ),
                _option(
                    value="use_geometry",
                    label="使用版本化几何面积规则",
                    effect={
                        "records_with_area_policy": quarantine_preserve["projection"][
                            "records_after_area_policy"
                        ],
                        "records_quarantined": quarantine_preserve["projection"][
                            "records_quarantined"
                        ],
                        "geometry_is_canonical_without_rule": False,
                    },
                    required_evidence=[
                        "geometry area rule ref and SHA-256",
                        "CRS and deterministic method",
                    ],
                    closes=["decision_packet.area_deviation_policy.pending_business_evidence"],
                    remains=["geometry_area_rule_missing_until_supplied", "SJNF", "MSSM"],
                ),
                _option(
                    value="quarantine",
                    label="隔离面积偏差记录",
                    effect={
                        "records_quarantined": quarantine_quarantine["projection"][
                            "records_quarantined"
                        ],
                        "records_after_area_policy": quarantine_quarantine["projection"][
                            "records_after_area_policy"
                        ],
                    },
                    required_evidence=["quarantine disposition and reason-code contract"],
                    closes=["decision_packet.area_deviation_policy.pending_business_evidence"],
                    remains=["SJNF", "MSSM"],
                ),
            ],
            blocker="decision_packet.area_deviation_policy.pending_business_evidence",
        ),
        _decision(
            target="SJNF",
            category="semantic",
            owner_ref="unassigned:chongqing-jqdltb-business",
            current_state="标准定义为数据生产年份；当前源和元数据没有可采纳的权威来源",
            evidence_roles=["semantic_candidate_audit"],
            options=[
                _option(
                    value="provide_authoritative_production_year",
                    label="提供版本化生产年份来源并按规则推导",
                    effect={
                        "current_candidate_non_blank_counts": {
                            field: int(
                                (semantic_candidates.get(field) or {}).get(
                                    "non_blank_count"
                                )
                                or 0
                            )
                            for field in ("PZWH", "SM", "JQDLMC")
                        },
                        "currently_admitted_authoritative_sources": 0,
                    },
                    required_evidence=[
                        "source field or business artifact",
                        "artifact SHA-256",
                        "deterministic extraction method",
                    ],
                    closes=["decision_packet.SJNF.pending_business_evidence"],
                    remains=["MSSM", "source_quality_not_passed_until_rerun"],
                ),
                _option(
                    value="quarantine_until_authority_exists",
                    label="无权威来源则继续隔离 SJNF",
                    effect={"canonical_value_written": False},
                    required_evidence=["business confirmation of quarantine policy"],
                    closes=[],
                    remains=[
                        "decision_packet.SJNF.pending_business_evidence",
                        "standardization_derived_fields_missing.SJNF",
                        "promotion_not_permitted",
                    ],
                ),
            ],
            blocker="decision_packet.SJNF.pending_business_evidence",
        ),
        _decision(
            target="MSSM",
            category="semantic",
            owner_ref="unassigned:chongqing-jqdltb-business",
            current_state="标准要求 Char(2)；当前没有 DLTB 正式值域/逐行填写规则，SM/DLBZ 均为空",
            evidence_roles=["semantic_candidate_audit"],
            options=[
                _option(
                    value="provide_authoritative_value_domain",
                    label="提供正式 Char(2) 值域和逐行映射规则",
                    effect={"canonical_value_written": True, "default_value_allowed": False},
                    required_evidence=[
                        "versioned standard/code-list artifact",
                        "artifact SHA-256",
                        "deterministic mapping or explicit row quarantine rule",
                    ],
                    closes=["decision_packet.MSSM.pending_business_evidence"],
                    remains=["SJNF", "source_quality_not_passed_until_rerun"],
                ),
                _option(
                    value="quarantine_until_authority_exists",
                    label="无值域则继续隔离 MSSM",
                    effect={"canonical_value_written": False},
                    required_evidence=["business confirmation of quarantine policy"],
                    closes=[],
                    remains=[
                        "decision_packet.MSSM.pending_business_evidence",
                        "standardization_derived_fields_missing.MSSM",
                        "promotion_not_permitted",
                    ],
                ),
            ],
            blocker="decision_packet.MSSM.pending_business_evidence",
        ),
        _decision(
            target="business_steward",
            category="promotion",
            owner_ref="unassigned:chongqing-jqdltb-business",
            current_state="AR-0 Manifest 尚未登记业务 steward",
            evidence_roles=["draft_business_decision_packet"],
            options=[
                _option(
                    value="assign_human_or_team",
                    label="登记可追责的人或团队",
                    effect={"release_gate": "eligible_for_recheck"},
                    required_evidence=["typed human/team identity and approval record"],
                    closes=["decision_packet.business_steward.pending_business_evidence"],
                    remains=[
                        "license_status",
                        "slo_on_call",
                        "environment_owner.*",
                        "source_quality_not_passed",
                    ],
                )
            ],
            blocker="decision_packet.business_steward.pending_business_evidence",
        ),
        _decision(
            target="license_status",
            category="promotion",
            owner_ref="unassigned:data-governance",
            current_state="许可状态仍是内部评估中，未允许产品发布或外部分发",
            evidence_roles=["draft_business_decision_packet"],
            options=[
                _option(
                    value="approve_scoped_use",
                    label="提交有范围的许可批准",
                    effect={"distribution_scope": "explicitly_scoped"},
                    required_evidence=["legal/data-governance record with scope and expiry"],
                    closes=["decision_packet.license_status.pending_business_evidence"],
                    remains=["business_steward", "slo_on_call", "environment_owner.*"],
                )
            ],
            blocker="decision_packet.license_status.pending_business_evidence",
        ),
        _decision(
            target="slo_on_call",
            category="promotion",
            owner_ref="unassigned:platform-operations",
            current_state="SLO 与 on-call 责任尚未批准",
            evidence_roles=["draft_business_decision_packet"],
            options=[
                _option(
                    value="approve_slo_and_on_call",
                    label="批准 Data/Service SLO 与 on-call 绑定",
                    effect={"operational_gate": "eligible_for_recheck"},
                    required_evidence=["versioned SLO, alert route, escalation and owner record"],
                    closes=["decision_packet.slo_on_call.pending_business_evidence"],
                    remains=["business_steward", "license_status", "environment_owner.*"],
                )
            ],
            blocker="decision_packet.slo_on_call.pending_business_evidence",
        ),
        _decision(
            target="environment_owner.staging",
            category="promotion",
            owner_ref="unassigned:environment-operations",
            current_state="staging owner 和环境 attestation 尚未登记",
            evidence_roles=["draft_business_decision_packet"],
            options=[
                _option(
                    value="assign_and_attest",
                    label="登记 owner 并提交 staging attestation",
                    effect={"environment_gate": "eligible_for_recheck"},
                    required_evidence=[
                        "typed owner, environment fingerprint and deployment attestation"
                    ],
                    closes=["decision_packet.environment_owner.staging.pending_business_evidence"],
                    remains=["environment_owner.production", "source_quality_not_passed"],
                )
            ],
            blocker="decision_packet.environment_owner.staging.pending_business_evidence",
        ),
        _decision(
            target="environment_owner.production",
            category="promotion",
            owner_ref="unassigned:environment-operations",
            current_state="production owner 和 production attestation 尚未登记",
            evidence_roles=["draft_business_decision_packet"],
            options=[
                _option(
                    value="assign_and_attest",
                    label="登记 owner 并提交 production attestation",
                    effect={"environment_gate": "eligible_for_recheck"},
                    required_evidence=[
                        "typed owner, production fingerprint, HA/RPO/RTO and deployment attestation"
                    ],
                    closes=["decision_packet.environment_owner.production.pending_business_evidence"],
                    remains=[
                        "source_quality_not_passed",
                        "same_product_version_raw_to_ads_evidence",
                    ],
                )
            ],
            blocker="decision_packet.environment_owner.production.pending_business_evidence",
        ),
    ]
    report = {
        "schema": SCHEMA,
        "packet_id": "jqdltb-ar0-source-quality-repair-candidates-v1",
        "status": "awaiting_business_decision",
        "scope": "ar0_first_jqdltb_vertical_slice",
        "purpose": "将只读诊断和策略影响整理成可签署的业务输入，不自动选择策略",
        "privacy": {
            "source_values_included": False,
            "feature_ids_included": False,
            "only_aggregate_evidence": True,
        },
        "side_effects": {
            "source_bytes_modified": False,
            "source_values_persisted": False,
            "authority_state_created": False,
            "strategy_created": False,
            "approval_case_created": False,
            "correction_artifact_created": False,
            "layer_artifacts_written": False,
            "data_product_version_created": False,
        },
        "identities": identity,
        "evidence": evidence,
        "decisions": decisions,
        "next_action": {
            "owner": "business/data stewards",
            "required": [
                "填写 10 项决定并附版本化证据",
                "提交为 draft decision packet 的 signed/submitted 版本",
                "由平台重新运行 readiness，再生成 dry_run proposal",
            ],
            "platform_after_submission": [
                "re-read all evidence identities",
                "compile strategy in memory",
                "create independent ApprovalCase only after admission",
                "rerun source-quality before any Raw-to-ADS materialization",
            ],
        },
        "conclusion": {
            "all_decisions_pending": True,
            "promotion_ready": False,
            "source_quality_verdict": "failed",
            "ar0_status_unchanged": "awaiting_business_approval",
            "not_a_substitute_for": [
                "business approval",
                "approved transformation contract",
                "source-quality rerun",
                "same ProductVersion Raw-to-ADS evidence",
            ],
        },
    }
    report["packet_sha256"] = canonical_json_fingerprint(report)
    return report


def _verify_packet_evidence(packet: dict[str, Any]) -> None:
    fingerprint_fields = {
        "aggregate_source_quality_diagnostic": "diagnostic_sha256",
        "semantic_candidate_audit": "report_sha256",
        "transformation_impact_preview": "preview_sha256",
        "approval_readiness_preflight": "readiness_sha256",
        "draft_business_decision_packet": "packet_sha256",
    }
    identities = packet.get("identities") or {}
    evidence = packet.get("evidence") or []
    roles = {item.get("role") for item in evidence}
    if roles != set(fingerprint_fields):
        raise ValueError("repair-candidate packet evidence roles are incomplete")
    for item in evidence:
        role = item["role"]
        evidence_ref = item.get("evidence_ref")
        if not isinstance(evidence_ref, str) or not evidence_ref.startswith("file:"):
            raise ValueError(f"repair-candidate evidence ref is invalid: {role}")
        path = (REPO_ROOT / evidence_ref.removeprefix("file:")).resolve(strict=True)
        if not path.is_relative_to(REPO_ROOT):
            raise ValueError(f"repair-candidate evidence path escapes repository: {role}")
        if _content_sha256(path) != item.get("content_sha256"):
            raise ValueError(f"repair-candidate evidence bytes drifted: {role}")
        canonical = _canonical_sha256(path, fingerprint_fields[role])
        if canonical != item.get("canonical_sha256"):
            raise ValueError(f"repair-candidate evidence fingerprint drifted: {role}")
        if item.get("identity") != identities:
            raise ValueError(f"repair-candidate evidence identity drifted: {role}")
    for decision in packet.get("decisions") or []:
        decision_roles = set(decision.get("evidence_roles") or [])
        if not decision_roles or not decision_roles.issubset(roles):
            raise ValueError(
                f"repair-candidate decision evidence is incomplete: {decision.get('target')}"
            )


def validate_packet(
    packet: dict[str, Any], *, verify_evidence_files: bool = True
) -> dict[str, Any]:
    if packet.get("schema") != SCHEMA:
        raise ValueError("unsupported repair-candidate packet schema")
    observed = packet.get("packet_sha256")
    if not isinstance(observed, str):
        raise ValueError("repair-candidate packet fingerprint is missing")
    payload = dict(packet)
    payload.pop("packet_sha256", None)
    calculated = canonical_json_fingerprint(payload)
    if observed != calculated:
        raise ValueError("repair-candidate packet fingerprint is invalid")
    decisions = packet.get("decisions") or []
    if len(decisions) != 10 or {item.get("target") for item in decisions} != {
        "canonical_key",
        "nonpositive_area_policy",
        "area_deviation_policy",
        "SJNF",
        "MSSM",
        "business_steward",
        "license_status",
        "slo_on_call",
        "environment_owner.staging",
        "environment_owner.production",
    }:
        raise ValueError("repair-candidate packet must contain exactly ten decisions")
    if any(item.get("status") != "pending_business_evidence" for item in decisions):
        raise ValueError("repair-candidate packet must remain pending until signed")
    if any(item.get("selected_value") is not None for item in decisions):
        raise ValueError("repair-candidate packet must not choose a business value")
    if packet.get("side_effects", {}).get("authority_state_created") is not False:
        raise ValueError("repair-candidate packet must not create authority state")
    if verify_evidence_files:
        _verify_packet_evidence(packet)
    return {
        "schema": SCHEMA,
        "packet_id": packet.get("packet_id"),
        "packet_sha256": observed,
        "decision_count": len(decisions),
        "all_decisions_pending": True,
        "promotion_ready": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--validate",
        type=Path,
        help="validate an existing packet and all referenced evidence without writing",
    )
    args = parser.parse_args(argv)
    if args.validate is not None:
        path = args.validate if args.validate.is_absolute() else REPO_ROOT / args.validate
        result = validate_packet(_read_json(path))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    report = build_packet()
    validate_packet(report)
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "output": str(output),
                "packet_sha256": report["packet_sha256"],
                "decision_count": len(report["decisions"]),
                "promotion_ready": report["conclusion"]["promotion_ready"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
