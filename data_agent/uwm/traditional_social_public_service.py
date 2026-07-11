from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

SCHEMA = "traditional_livability.social_public_service.v1"

DEMAND12_CHANNELS = {
    "facility_inventory": "implemented",
    "semantic_classification": "implemented",
    "administrative_distribution": "implemented",
    "category_diversity": "implemented",
    "nearest_service_accessibility": "proxy_only",
    "relative_evidence_gap": "proxy_only",
    "authoritative_capacity": "unavailable",
    "population_capacity_match": "unavailable",
    "overload_determination": "unavailable",
    "lifecycle_status": "unavailable",
    "active_inactive_composition": "unavailable",
    "meps_bdms_verification": "unavailable",
    "authoritative_service_area": "unavailable",
    "future_demand": "unavailable",
}

DEMAND21_CHANNELS = {
    "public_service_inventory": "implemented",
    "semantic_classification": "implemented",
    "administrative_distribution": "implemented",
    "service_type_diversity": "implemented",
    "nearest_service_accessibility": "proxy_only",
    "relative_evidence_gap": "proxy_only",
    "observed_service_availability": "unavailable",
    "authoritative_service_area": "unavailable",
    "population_service_match": "unavailable",
    "authoritative_service_deficit": "unavailable",
    "policy_effect": "unavailable",
}

SOCIAL_CATEGORIES = {
    "education", "childcare", "healthcare", "religious", "community_service",
    "sports", "park_recreation", "library", "youth_service", "elderly_service",
    "culture", "family_service",
}
PUBLIC_SERVICE_CATEGORIES = {
    "government_service", "public_service", "government_institution",
    "community_governance", "administrative_service",
}


def build_social_public_service_product(
    *,
    facilities: Sequence[Mapping[str, Any]],
    admin_units: Sequence[Mapping[str, Any]],
    source_artifacts: Sequence[str],
) -> dict[str, Any]:
    canonical_facilities = _canonical_facilities(facilities)
    canonical_admins = _canonical_admins(admin_units)
    admin_rows = _build_admin_rows(canonical_admins, canonical_facilities)
    readiness = {
        "social_infrastructure": _readiness(DEMAND12_CHANNELS),
        "government_public_service": _readiness(DEMAND21_CHANNELS),
    }
    digest_input = {
        "schema": SCHEMA,
        "facilities": canonical_facilities,
        "admin_units": admin_rows,
        "source_artifacts": sorted(str(path) for path in source_artifacts),
    }
    bundle_id = "traditional-social-public-service-" + sha256(
        json.dumps(digest_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "schema": SCHEMA,
        "bundle_id": bundle_id,
        "views": {
            "social_infrastructure": {"demand_id": "12", "title": "社会基础设施与社区设施"},
            "government_public_service": {"demand_id": "21", "title": "政府机构与公共服务"},
        },
        "summary": {
            "facility_count": len(canonical_facilities),
            "admin_unit_count": len(admin_rows),
            "social_infrastructure_facility_count": sum("social_infrastructure" in row["view_membership"] for row in canonical_facilities),
            "government_public_service_facility_count": sum("government_public_service" in row["view_membership"] for row in canonical_facilities),
        },
        "facilities": canonical_facilities,
        "admin_units": admin_rows,
        "channel_readiness": readiness,
        "source_artifacts": sorted(str(path) for path in source_artifacts),
        "claim_boundary": {
            "max_claim_level": "observed_inventory_and_relative_proxy",
            "authoritative_service_deficit_claim": False,
            "authoritative_capacity_claim": False,
            "future_demand_claim": False,
            "causal_policy_effect_claim": False,
        },
        "production_blockers": [
            "authoritative_capacity_missing",
            "authoritative_lifecycle_and_activity_status_missing",
            "population_capacity_match_missing",
            "authoritative_service_area_standard_missing",
            "future_demand_evidence_missing",
        ],
    }


def _canonical_facilities(facilities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for source in facilities:
        facility_id = str(source.get("facility_id") or "").strip()
        if not facility_id:
            raise ValueError("facility_id_missing")
        if facility_id in seen:
            raise ValueError("duplicate_facility_id")
        seen.add(facility_id)
        source_dataset = str(source.get("source_dataset") or "").strip()
        source_record_id = str(source.get("source_record_id") or "").strip()
        if not source_dataset or not source_record_id:
            raise ValueError("facility_source_trace_missing")
        category = str(source.get("canonical_category") or "").strip()
        membership = []
        if category in SOCIAL_CATEGORIES:
            membership.append("social_infrastructure")
        if category in PUBLIC_SERVICE_CATEGORIES:
            membership.append("government_public_service")
        result.append({
            "facility_id": facility_id,
            "name": source.get("name"),
            "raw_category": source.get("raw_category"),
            "canonical_category": category or None,
            "view_membership": membership,
            "longitude": source.get("longitude"),
            "latitude": source.get("latitude"),
            "admin_unit_id": source.get("admin_unit_id"),
            "source_dataset": source_dataset,
            "source_record_id": source_record_id,
            "classification_method": source.get("classification_method"),
            "classification_confidence": source.get("classification_confidence"),
            "lifecycle_status": None,
            "active_status": None,
            "capacity": None,
            "service_radius_m": None,
            "source_trace": {"source_dataset": source_dataset, "source_record_id": source_record_id},
            "limitations": ["capacity_lifecycle_activity_and_service_radius_not_observed"],
        })
    return sorted(result, key=lambda row: row["facility_id"])


def _canonical_admins(admin_units: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for source in admin_units:
        admin_id = str(source.get("admin_unit_id") or "").strip()
        if not admin_id:
            raise ValueError("admin_unit_id_missing")
        if admin_id in seen:
            raise ValueError("duplicate_admin_unit_id")
        seen.add(admin_id)
        result.append({
            "admin_unit_id": admin_id,
            "county": source.get("county"),
            "township": source.get("township"),
            "longitude": source.get("longitude"),
            "latitude": source.get("latitude"),
            "service_accessibility_score": source.get("service_accessibility_score"),
        })
    return sorted(result, key=lambda row: row["admin_unit_id"])


def _build_admin_rows(admins: list[dict[str, Any]], facilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for admin in admins:
        member_facilities = [row for row in facilities if row.get("admin_unit_id") == admin["admin_unit_id"]]
        social = _view_metrics(member_facilities, "social_infrastructure", admin.get("service_accessibility_score"))
        public = _view_metrics(member_facilities, "government_public_service", admin.get("service_accessibility_score"))
        rows.append({**deepcopy(admin), "social_infrastructure": social, "government_public_service": public})
    _assign_ranks(rows, "social_infrastructure")
    _assign_ranks(rows, "government_public_service")
    return rows


def _view_metrics(facilities: list[dict[str, Any]], view: str, accessibility: Any) -> dict[str, Any]:
    selected = [row for row in facilities if view in row["view_membership"]]
    categories = sorted({row["canonical_category"] for row in selected if row.get("canonical_category")})
    reasons = []
    if not selected:
        reasons.append("zero_supported_facilities")
    if accessibility is None:
        reasons.append("accessibility_evidence_missing")
    return {
        "facility_count": len(selected),
        "category_count": len(categories),
        "categories": categories,
        "relative_gap_rank": None,
        "relative_gap_reasons": reasons,
        "relative_proxy_not_authoritative_standard": True,
        "observed_capacity_match": False,
        "policy_outcome_claim": False,
        "authoritative_service_deficit": None,
    }


def _assign_ranks(rows: list[dict[str, Any]], view: str) -> None:
    ordered = sorted(
        rows,
        key=lambda row: (
            0 if row[view]["facility_count"] == 0 else 1,
            row[view]["category_count"],
            row[view]["facility_count"],
            row["service_accessibility_score"] if row["service_accessibility_score"] is not None else -1.0,
            row["admin_unit_id"],
        ),
    )
    for rank, row in enumerate(ordered, 1):
        row[view]["relative_gap_rank"] = rank
        if row[view]["category_count"] <= 1:
            row[view]["relative_gap_reasons"].append("low_supported_category_diversity")


def _readiness(channels: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    result = {}
    for channel, status in channels.items():
        result[channel] = {
            "status": status,
            "value": None,
            "relative_proxy_not_authoritative_standard": status == "proxy_only",
        }
    return result
