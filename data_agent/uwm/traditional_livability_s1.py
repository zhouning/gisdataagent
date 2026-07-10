from __future__ import annotations

from collections import Counter
from typing import Any


SCHEMA = "uwm.traditional_livability.s1_assessment.v1"
STANDARD_FIELDS = {"canonical_class", "metric", "threshold", "unit", "authority", "effective_date", "evidence_level"}


def build_s1_facility_assessment(
    *,
    assessment_id: str,
    created_at: str,
    facility_product: dict[str, Any],
    standards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    populations = _population_index(facility_product.get("population_units") or [])
    accepted, rejected = _validated_standards(standards or [])
    standard_index = {(row["canonical_class"], row["metric"]): row for row in accepted}
    matched_counts: Counter[tuple[str, str]] = Counter()
    unmatched = []
    facilities = facility_product.get("facilities") or []
    for facility in facilities:
        admin_code = str(facility.get("admin_code") or "")
        canonical_class = str(facility.get("canonical_class") or "unmapped")
        if admin_code not in populations:
            unmatched.append(_facility_reference(facility))
            continue
        matched_counts[(admin_code, canonical_class)] += 1

    metrics = []
    for (admin_code, canonical_class), facility_count in sorted(matched_counts.items()):
        population = populations[admin_code]
        rate = round(facility_count / population["population"] * 10000, 6)
        standard = standard_index.get((canonical_class, "facilities_per_10000_residents"))
        gap = round(rate - float(standard["threshold"]), 6) if standard else None
        metrics.append(
            {
                "admin_code": admin_code,
                "admin_name": population.get("admin_name"),
                "population": population["population"],
                "population_basis": population.get("population_basis"),
                "canonical_class": canonical_class,
                "facility_count": facility_count,
                "facilities_per_10000_residents": rate,
                "compliance_status": _compliance(gap),
                "gap_to_standard": gap,
                "standard": dict(standard) if standard else None,
                "capacity_assessment_available": False,
            }
        )
    blockers = list(
        dict.fromkeys(
            [
                *(facility_product.get("production_blockers") or []),
                *(
                    []
                    if accepted
                    else ["authoritative_fp_fpp_thresholds_missing"]
                ),
                "facility_capacity_missing",
            ]
        )
    )
    return {
        "schema": SCHEMA,
        "assessment_id": assessment_id,
        "created_at": created_at,
        "facility_product_id": facility_product.get("product_id"),
        "method": "deterministic_current_state_facility_supply_assessment",
        "summary": {
            "population_unit_count": len(populations),
            "facility_count": len(facilities),
            "matched_facility_count": sum(matched_counts.values()),
            "unmatched_facility_count": len(unmatched),
            "mapped_facility_count": sum(row.get("mapping_status") == "mapped_internal_taxonomy" for row in facilities),
            "unmapped_facility_count": sum(row.get("mapping_status") == "unmapped" for row in facilities),
            "authoritative_standard_count": len(accepted),
        },
        "supply_metrics": metrics,
        "unmatched_facilities": unmatched,
        "accepted_standards": accepted,
        "rejected_standards": rejected,
        "production_blockers": blockers,
        "claim_boundary": {
            "future_impact_assessed": False,
            "network_service_area_assessed": False,
            "compliance_requires_authoritative_standard": True,
            "capacity_compliance_assessed": False,
        },
    }


def _population_index(rows):
    index = {}
    for row in rows:
        code = str(row.get("admin_code") or "")
        population = int(row.get("population") or 0)
        if not code:
            raise ValueError("population_admin_code_required")
        if population <= 0:
            raise ValueError(f"population_must_be_positive:{code}")
        if code in index:
            raise ValueError(f"duplicate_population_admin_code:{code}")
        index[code] = {**row, "population": population}
    return index


def _validated_standards(rows):
    accepted, rejected = [], []
    for row in rows:
        missing = sorted(field for field in STANDARD_FIELDS if row.get(field) in (None, ""))
        if missing or row.get("evidence_level") != "authoritative" or row.get("metric") != "facilities_per_10000_residents":
            rejected.append({"standard": dict(row), "reason": "invalid_or_non_authoritative_standard", "missing_fields": missing})
            continue
        accepted.append(dict(row))
    return accepted, rejected


def _compliance(gap):
    if gap is None:
        return "not_assessed"
    return "meets_standard" if gap >= 0 else "below_standard"


def _facility_reference(row):
    return {key: row.get(key) for key in ("source_dataset_id", "source_record_id", "name", "admin_code", "canonical_class", "mapping_status")}
