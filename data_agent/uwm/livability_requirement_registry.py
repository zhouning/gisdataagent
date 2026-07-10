"""Canonical ownership registry for LIV scenarios and customer AI demands."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA = "uwm.customer_ai_requirement_registry.v2"

SOURCE_DOCUMENTS = [
    "/Users/zhouning/Downloads/宜居性专项分析.docx",
    "/Users/zhouning/Downloads/客户侧25个AI应用需求的回复.docx",
]

PRIMARY_ROUTES = {
    "traditional_livability",
    "uwm_livability",
    "planning_land",
    "infrastructure_assets",
    "population_demand",
    "economy_investment",
    "impact_implementation",
}

LIVABILITY_SCENARIO_PRIMARY_ROUTES = {
    "S1": "traditional_livability",
    "S2": "uwm_livability",
    "S4": "traditional_livability",
    "S6": "traditional_livability",
    "S7": "traditional_livability",
}

CUSTOMER_DEMAND_PRIMARY_ROUTES = {
    "1": "planning_land",
    "2": "planning_land",
    "3": "planning_land",
    "4": "infrastructure_assets",
    "5": "infrastructure_assets",
    "6": "population_demand",
    "7": "uwm_livability",
    "8": "traditional_livability",
    "9": "traditional_livability",
    "10": "traditional_livability",
    "11": "uwm_livability",
    "12": "traditional_livability",
    "13": "traditional_livability",
    "14": "traditional_livability",
    "15": "traditional_livability",
    "16": "traditional_livability",
    "17": "infrastructure_assets",
    "18": "infrastructure_assets",
    "19": "uwm_livability",
    "20": "economy_investment",
    "21": "traditional_livability",
    "22": "planning_land",
    "23": "economy_investment",
    "24": "impact_implementation",
    "25": "impact_implementation",
}

_REQUIRED_ROW_FIELDS = (
    "title",
    "primary_route",
    "required_method",
    "implementation_level",
    "data_support",
    "route_availability",
    "implemented_outputs",
    "production_blockers",
)

_SCENARIO_DEFINITIONS = {
    "S1": ("区级设施评估", "facility_inventory_service_area_gap_analysis"),
    "S2": ("用地或设施变更", "action_conditioned_counterfactual_transition"),
    "S4": ("项目宜居性评估", "project_demand_alignment_and_conflict_analysis"),
    "S6": ("超范围设施评估", "semantic_facility_mapping_and_spatial_conflict"),
    "S7": ("设施选址", "gis_location_allocation"),
}

_DEMAND_DEFINITIONS = {
    "1": ("区域与片区识别", "spatial_query_and_classification"),
    "2": ("总体规划", "planning_document_and_version_analysis"),
    "3": ("用地与地块状态", "parcel_overlay_and_status_analysis"),
    "4": ("基础设施与市政管网", "network_inventory_and_capacity_analysis"),
    "5": ("资产", "asset_inventory_and_condition_analysis"),
    "6": ("人口与人口结构", "population_spatial_statistics"),
    "7": ("宜居性与社区需求", "action_conditioned_state_forecast_and_planning"),
    "8": ("出行、步行性与可达性", "network_accessibility_analysis"),
    "9": ("公共空间与场所营造", "public_space_accessibility_and_opportunity_analysis"),
    "10": ("安全、治安与舒适", "spatial_safety_and_comfort_diagnostics"),
    "11": ("环境质量与气候舒适", "hybrid_environmental_transition_model"),
    "12": ("社会基础设施与社区设施", "facility_capacity_and_service_area_analysis"),
    "13": ("住房与社区构成", "housing_population_supply_demand_analysis"),
    "14": ("经济活力与日常便利", "activity_mix_and_convenience_analysis"),
    "15": ("社区之声与舆情", "traceable_geospatial_text_analysis"),
    "16": ("文化、标识与片区特色", "heritage_and_place_character_analysis"),
    "17": ("数字化与智慧片区就绪度", "digital_infrastructure_readiness_analysis"),
    "18": ("运维与服务质量", "operations_sla_and_service_quality_analysis"),
    "19": ("韧性与面向未来就绪度", "stress_propagation_recovery_and_robust_planning"),
    "20": ("DED执照与经济活动", "authoritative_licence_and_activity_analysis"),
    "21": ("政府机构与公共服务", "public_service_coverage_analysis"),
    "22": ("设计参数与开发要求", "rule_based_development_control_analysis"),
    "23": ("财务与投资分析", "deterministic_financial_model"),
    "24": ("影响评估与优先级排序", "cross_domain_evidence_orchestration"),
    "25": ("建议与实施路线图", "dependency_aware_implementation_planning"),
}


def _route_availability(route: str) -> str:
    if route in {"traditional_livability", "uwm_livability"}:
        return "existing"
    return "planned"


def _row(
    requirement_id: str,
    title: str,
    primary_route: str,
    required_method: str,
    *,
    implementation_level: str = "registered",
    data_support: str = "requires_data_audit",
    implemented_outputs: list[str] | None = None,
    production_blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "title": title,
        "primary_route": primary_route,
        "required_method": required_method,
        "implementation_level": implementation_level,
        "data_support": data_support,
        "route_availability": _route_availability(primary_route),
        "implemented_outputs": list(implemented_outputs or []),
        "production_blockers": list(production_blockers or []),
    }


def _scenario_rows() -> list[dict[str, Any]]:
    rows = []
    for scenario_id, route in LIVABILITY_SCENARIO_PRIMARY_ROUTES.items():
        title, required_method = _SCENARIO_DEFINITIONS[scenario_id]
        rows.append(_row(scenario_id, title, route, required_method))
    return rows


def _demand_rows() -> list[dict[str, Any]]:
    rows = []
    for demand_id, route in CUSTOMER_DEMAND_PRIMARY_ROUTES.items():
        title, required_method = _DEMAND_DEFINITIONS[demand_id]
        if demand_id == "23":
            rows.append(
                _row(
                    demand_id,
                    title,
                    route,
                    required_method,
                    implementation_level="data_contract_required",
                    data_support="requires_customer_data",
                    production_blockers=[
                        "boq",
                        "capital_cost",
                        "operating_cost",
                        "revenue",
                        "cash_flow",
                    ],
                )
            )
        else:
            rows.append(_row(demand_id, title, route, required_method))
    return rows


def build_livability_requirement_registry() -> dict[str, Any]:
    """Build a fresh registry payload with one primary route per requirement."""

    return {
        "schema": UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA,
        "source_documents": list(SOURCE_DOCUMENTS),
        "primary_routes": sorted(PRIMARY_ROUTES),
        "livability_scenarios": _scenario_rows(),
        "customer_ai_demands": _demand_rows(),
        "claim_boundary": {
            "registration_is_not_implementation": True,
            "observed_policy_outcome_superiority_claim": False,
        },
    }


def requirement_coverage_for_route(
    registry: dict[str, Any], route: str
) -> dict[str, Any]:
    """Return the non-overlapping scenario and demand view owned by ``route``."""

    if route not in PRIMARY_ROUTES:
        raise ValueError(f"unknown primary route: {route}")
    return {
        "schema": registry.get("schema"),
        "primary_route": route,
        "livability_scenarios": deepcopy(
            [
                row
                for row in registry.get("livability_scenarios", [])
                if row.get("primary_route") == route
            ]
        ),
        "customer_ai_demands": deepcopy(
            [
                row
                for row in registry.get("customer_ai_demands", [])
                if row.get("primary_route") == route
            ]
        ),
        "claim_boundary": deepcopy(registry.get("claim_boundary", {})),
    }


def validate_livability_requirement_registry(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate IDs, ownership and row contracts for the canonical registry."""

    errors: list[str] = []
    if payload.get("schema") != UWM_LIVABILITY_REQUIREMENT_REGISTRY_SCHEMA:
        errors.append("invalid schema")
    if payload.get("source_documents") != SOURCE_DOCUMENTS:
        errors.append("source_documents must exactly match canonical source documents")
    if payload.get("primary_routes") != sorted(PRIMARY_ROUTES):
        errors.append("primary_routes must exactly match canonical primary routes")

    claim_boundary = payload.get("claim_boundary")
    if not isinstance(claim_boundary, dict):
        errors.append("claim_boundary must be an object")
        claim_boundary = {}
    if claim_boundary.get("registration_is_not_implementation") is not True:
        errors.append("claim_boundary.registration_is_not_implementation must be true")
    if claim_boundary.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append(
            "claim_boundary.observed_policy_outcome_superiority_claim must be false"
        )

    scenarios = payload.get("livability_scenarios")
    demands = payload.get("customer_ai_demands")
    if not isinstance(scenarios, list):
        errors.append("livability_scenarios must be a list")
        scenarios = []
    if not isinstance(demands, list):
        errors.append("customer_ai_demands must be a list")
        demands = []

    _validate_rows(
        scenarios,
        expected_ids=set(LIVABILITY_SCENARIO_PRIMARY_ROUTES),
        expected_routes=LIVABILITY_SCENARIO_PRIMARY_ROUTES,
        canonical_rows={row["id"]: row for row in _scenario_rows()},
        label="scenario",
        errors=errors,
    )
    _validate_rows(
        demands,
        expected_ids={str(index) for index in range(1, 26)},
        expected_routes=CUSTOMER_DEMAND_PRIMARY_ROUTES,
        canonical_rows={row["id"]: row for row in _demand_rows()},
        label="demand",
        errors=errors,
    )
    return {"valid": not errors, "errors": errors}


def _validate_rows(
    rows: list[Any],
    *,
    expected_ids: set[str],
    expected_routes: dict[str, str],
    canonical_rows: dict[str, dict[str, Any]],
    label: str,
    errors: list[str],
) -> None:
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if set(ids) != expected_ids or len(ids) != len(expected_ids):
        errors.append(f"{label} IDs must exactly match {sorted(expected_ids)}")
    if len(ids) != len(set(ids)):
        errors.append(f"duplicate {label} IDs")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{label} row {index} must be an object")
            continue
        requirement_id = row.get("id")
        for field in _REQUIRED_ROW_FIELDS:
            if field not in row:
                errors.append(f"{label} {requirement_id} missing required field: {field}")

        route = row.get("primary_route")
        if route not in PRIMARY_ROUTES:
            errors.append(f"{label} {requirement_id} has invalid primary_route")
        elif expected_routes.get(requirement_id) != route:
            errors.append(f"{label} {requirement_id} has non-canonical primary_route")
        expected_availability = _route_availability(route) if route in PRIMARY_ROUTES else None
        if row.get("route_availability") not in {"existing", "planned"}:
            errors.append(f"{label} {requirement_id} has invalid route_availability")
        elif row.get("route_availability") != expected_availability:
            errors.append(f"{label} {requirement_id} has inconsistent route_availability")
        if not isinstance(row.get("implemented_outputs"), list):
            errors.append(f"{label} {requirement_id} implemented_outputs must be a list")
        if not isinstance(row.get("production_blockers"), list):
            errors.append(f"{label} {requirement_id} production_blockers must be a list")

        canonical_row = canonical_rows.get(requirement_id)
        if canonical_row is None:
            continue
        for field in _REQUIRED_ROW_FIELDS:
            if field in row and row[field] != canonical_row[field]:
                errors.append(
                    f"{label} {requirement_id} {field} does not match canonical definition"
                )
