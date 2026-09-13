"""Role-level UWM data foundation audits."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .manifest import audit_uwm_manifest


UWM_CORE_DATA_ROLES = {
    "urban_form": {
        "aliases": {"urban_form", "building", "buildings"},
        "required_for": ["renderer", "simulator", "planner"],
        "public_acquisition_action": "verify_or_mount_urban_form_public_reproducibility_substitute",
    },
    "heat_exposure": {
        "aliases": {"heat_exposure", "uwm_heat", "uhi"},
        "required_for": ["renderer", "simulator", "evaluation"],
        "public_acquisition_action": "download_or_mount_heat_exposure_public_proxy",
    },
    "air_pollution_exposure": {
        "aliases": {"air_pollution_exposure", "uwm_air", "air_quality"},
        "required_for": ["renderer", "simulator", "evaluation"],
        "public_acquisition_action": "download_or_mount_air_pollution_public_proxy",
    },
    "service_accessibility": {
        "aliases": {"service_accessibility", "poi", "aoi"},
        "required_for": ["baseline", "simulator", "planner"],
        "public_acquisition_action": "download_or_mount_service_accessibility_public_substitute",
    },
    "mobility_graph": {
        "aliases": {"mobility_graph", "mobility_activity", "graph", "roads"},
        "required_for": ["renderer", "simulator"],
        "public_acquisition_action": "verify_or_mount_mobility_graph_public_substitute",
    },
    "population_vulnerability": {
        "aliases": {"population_vulnerability", "demographic_vulnerability", "population"},
        "required_for": ["simulator", "planner", "equity_evaluation"],
        "public_acquisition_action": "download_or_mount_population_vulnerability_public_proxy",
    },
    "administrative_units": {
        "aliases": {
            "administrative_units",
            "admin_units",
            "governance_unit",
            "township",
            "xiangzhen",
        },
        "required_for": ["mmfe_alignment", "renderer", "planner", "equity_evaluation"],
        "public_acquisition_action": "verify_or_mount_administrative_boundary_public_substitute",
    },
    "spatial_adjacency_graph": {
        "aliases": {
            "spatial_adjacency_graph",
            "admin_spatial_graph",
            "admin_boundary_adjacency",
            "spatial_adjacency",
        },
        "required_for": ["simulator", "planner", "model_based_rl"],
        "public_acquisition_action": "verify_or_mount_boundary_adjacency_or_network_graph",
    },
    "meteorology": {
        "aliases": {"meteorology", "weather", "era5", "climate"},
        "required_for": ["simulator", "scenario"],
        "public_acquisition_action": "download_or_mount_meteorology_public_proxy",
    },
    "remote_sensing_state": {
        "aliases": {"remote_sensing_state", "landcover", "alphaearth", "geofm"},
        "required_for": ["renderer", "state_prior"],
        "public_acquisition_action": "download_or_mount_remote_sensing_state_public_proxy",
    },
    "causal_evidence_gate": {
        "aliases": {"evidence_gate", "scca", "causal_evidence"},
        "required_for": ["evaluation", "claim_boundary"],
        "public_acquisition_action": "mount_or_reproduce_causal_evidence_gate_benchmark",
    },
}

_CLAIM_ORDER = ["not_for_claim", "exploratory_only", "fragile", "bounded_support", "core_support"]


def audit_uwm_data_foundation_roles(
    rows: list[dict[str, Any]],
    *,
    required_roles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit data-role coverage from manifest rows."""

    required_roles = required_roles or UWM_CORE_DATA_ROLES
    role_coverage = {
        role: _coverage_for_role(role, config, rows)
        for role, config in required_roles.items()
    }
    missing_roles = [
        role
        for role, coverage in role_coverage.items()
        if coverage["coverage_level"] == "missing"
    ]
    empirical_blockers = [
        role
        for role, coverage in role_coverage.items()
        if coverage["blocks_empirical_superiority"]
    ]
    acquisition_queue = [
        required_roles[role]["public_acquisition_action"]
        for role in empirical_blockers
        if required_roles[role].get("public_acquisition_action")
    ]
    return {
        "schema": "uwm.data_foundation_role_audit.v1",
        "role_coverage": role_coverage,
        "missing_required_roles": missing_roles,
        "empirical_superiority_blockers": empirical_blockers,
        "public_acquisition_queue": acquisition_queue,
        "claim_ceiling": _claim_ceiling(role_coverage),
    }


def audit_uwm_data_foundation_manifest(path: str | Path) -> dict[str, Any]:
    """Audit manifest validity and UWM role-level coverage together."""

    manifest_audit = audit_uwm_manifest(path)
    rows = _load_rows(path) if manifest_audit.get("valid") else []
    role_audit = audit_uwm_data_foundation_roles(rows)
    return {
        "schema": "uwm.data_foundation_manifest_role_audit.v1",
        "manifest_valid": bool(manifest_audit.get("valid")),
        "manifest_errors": manifest_audit.get("errors", []),
        "manifest_row_count": manifest_audit.get("row_count", 0),
        "role_coverage": role_audit["role_coverage"],
        "missing_required_roles": role_audit["missing_required_roles"],
        "empirical_superiority_blockers": role_audit["empirical_superiority_blockers"],
        "public_acquisition_queue": role_audit["public_acquisition_queue"],
        "claim_ceiling": role_audit["claim_ceiling"],
        "manifest_audit": manifest_audit,
    }


def _coverage_for_role(
    role: str,
    config: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if _row_matches_role(row, config["aliases"])
    ]
    coverage_level = _coverage_level(matches)
    return {
        "role": role,
        "coverage_level": coverage_level,
        "dataset_ids": [str(row.get("dataset_id", "")) for row in matches],
        "required_for": config.get("required_for", []),
        "claim_ceiling": _role_claim_ceiling(matches, coverage_level),
        "blocks_empirical_superiority": _blocks_empirical_superiority(role, matches, coverage_level),
        "public_acquisition_action": config.get("public_acquisition_action"),
    }


def _row_matches_role(row: dict[str, Any], aliases: set[str]) -> bool:
    tokens = _tokens(row.get("used_by", ""))
    tokens.update(_tokens(row.get("dataset_id", "")))
    tokens.update(_tokens(row.get("dataset_name", "")))
    if tokens.intersection(aliases):
        return True
    haystack = " ".join(
        str(row.get(key, "")).lower().replace("-", "_")
        for key in ["used_by", "dataset_id", "dataset_name"]
    )
    return any(alias in haystack for alias in aliases)


def _tokens(value: Any) -> set[str]:
    normalised = str(value).lower().replace("-", "_").replace(" ", "_")
    for separator in [";", ",", "/", "|"]:
        normalised = normalised.replace(separator, " ")
    return {token.strip() for token in normalised.split() if token.strip()}


def _coverage_level(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "missing"
    if any(_is_available_real(row) for row in rows):
        return "usable_real"
    if any(_is_available_proxy(row) for row in rows):
        return "proxy_available"
    if any(_is_available_fitted_proxy(row) for row in rows):
        return "fitted_proxy_available"
    if any(_is_raw_available_proxy(row) for row in rows):
        return "raw_proxy_available"
    if any(_is_planned_proxy(row) for row in rows):
        return "planned_proxy"
    if any(str(row.get("synthetic_status")) == "semi_synthetic" for row in rows):
        return "semi_synthetic_only"
    if any(str(row.get("synthetic_status")) == "synthetic" for row in rows):
        return "synthetic_only"
    if any(str(row.get("synthetic_status")) == "smoke_only" for row in rows):
        return "smoke_only"
    return "missing"


def _is_available_real(row: dict[str, Any]) -> bool:
    return str(row.get("access_status")) == "available" and str(row.get("synthetic_status")) == "real"


def _is_available_proxy(row: dict[str, Any]) -> bool:
    return str(row.get("access_status")) == "available" and str(row.get("synthetic_status")) == "public_proxy"


def _is_available_fitted_proxy(row: dict[str, Any]) -> bool:
    return str(row.get("access_status")) == "available" and str(row.get("synthetic_status")) == "fitted_proxy"


def _is_raw_available_proxy(row: dict[str, Any]) -> bool:
    return (
        str(row.get("access_status")) == "raw_public_proxy_available"
        and str(row.get("synthetic_status")) == "public_proxy"
    )


def _is_planned_proxy(row: dict[str, Any]) -> bool:
    return str(row.get("access_status")) == "planned_public_download" and str(row.get("synthetic_status")) == "public_proxy"


def _role_claim_ceiling(rows: list[dict[str, Any]], coverage_level: str) -> str:
    if coverage_level == "missing":
        return "not_for_claim"
    if coverage_level in {"synthetic_only", "semi_synthetic_only", "smoke_only"}:
        return "exploratory_only"
    if coverage_level == "usable_real":
        supporting_rows = [row for row in rows if _is_available_real(row)]
    elif coverage_level == "proxy_available":
        supporting_rows = [row for row in rows if _is_available_proxy(row)]
    elif coverage_level == "fitted_proxy_available":
        supporting_rows = [row for row in rows if _is_available_fitted_proxy(row)]
    elif coverage_level == "raw_proxy_available":
        supporting_rows = [row for row in rows if _is_raw_available_proxy(row)]
    elif coverage_level == "planned_proxy":
        supporting_rows = [row for row in rows if _is_planned_proxy(row)]
    else:
        supporting_rows = rows
    claim_boundaries = [
        str(row.get("claim_boundary") or "not_for_claim")
        for row in supporting_rows
        if str(row.get("claim_boundary") or "not_for_claim") != "not_for_claim"
    ]
    return min(claim_boundaries, key=_claim_rank) if claim_boundaries else "not_for_claim"


def _blocks_empirical_superiority(role: str, rows: list[dict[str, Any]], coverage_level: str) -> bool:
    if coverage_level in {
        "missing",
        "fitted_proxy_available",
        "planned_proxy",
        "raw_proxy_available",
        "synthetic_only",
        "semi_synthetic_only",
        "smoke_only",
    }:
        return True
    if role in {"air_pollution_exposure", "meteorology"} and coverage_level == "proxy_available":
        return not any(_is_environmental_holdout_ready(row) for row in rows if _is_available_proxy(row))
    return False


def _is_environmental_holdout_ready(row: dict[str, Any]) -> bool:
    quality = str(row.get("quality_status") or "").lower()
    lineage = str(row.get("lineage") or "").lower()
    text = f"{quality} {lineage}"
    if any(
        exclusion in text
        for exclusion in [
            "not_policy_outcome",
            "not_policy_intervention_outcome",
            "not policy intervention outcome",
            "temporal_state_benchmark",
        ]
    ):
        return False
    return any(
        marker in text
        for marker in [
            "holdout_ready",
            "station_calibrated_holdout",
            "observed_holdout",
            "empirical_ready",
        ]
    )


def _claim_ceiling(role_coverage: dict[str, dict[str, Any]]) -> str:
    ceilings = [coverage["claim_ceiling"] for coverage in role_coverage.values()]
    if not ceilings:
        return "not_for_claim"
    return min(ceilings, key=_claim_rank)


def _claim_rank(claim: str) -> int:
    try:
        return _CLAIM_ORDER.index(claim)
    except ValueError:
        return 0


def _load_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
