from __future__ import annotations

import hashlib
import json
from copy import deepcopy


CHANNELS = (
    "project_scope",
    "bill_of_quantities",
    "capital_cost",
    "operating_cost",
    "revenue",
    "other_benefits",
    "implementation_schedule",
    "discount_rate",
    "financing_terms",
    "taxes",
    "subsidies",
    "residual_value",
    "uwm_scenario_handoff",
)

OUTPUTS = ("annual_cash_flow", "net_present_value", "internal_rate_of_return", "payback_period", "return_on_investment", "affordability", "bankability", "investment_recommendation")


def build_financial_readiness_product(*, evidence_assets, source_artifacts):
    assets = deepcopy(evidence_assets)
    for asset in assets:
        if not asset.get("source_path"):
            raise ValueError("financial_source_path_required")
        if asset.get("asset_class") == "financial_data_standard" and asset.get("execution_status") == "observed_customer_financial_data":
            raise ValueError("standard_cannot_be_financial_observation")
    channels = {name: {"status": "unavailable", "value": None, "unit": None, "evidence_reference": None, "production_blockers": ["authoritative_customer_financial_data_missing"]} for name in CHANNELS}
    outputs = {name: None for name in OUTPUTS}
    contracts = {
        "deterministic_financial_input": {
            "required_fields": ["project_id", "scenario_id", "line_item_id", "quantity", "quantity_unit", "unit_price", "currency", "price_base_date", "time_period", "evidence_reference"],
        },
        "uwm_scenario_handoff": {
            "required_fields": ["bundle_id", "scenario_id", "baseline_definition", "intervention_definition", "quantity", "quantity_unit", "time_axis", "spatial_scope", "uncertainty", "provenance"],
        },
    }
    gate = {"status": "closed", "mechanisms": {name: "closed" for name in ("quantity_price_multiplication", "capex_aggregation", "opex_aggregation", "revenue_aggregation", "annual_cash_flow_construction", "discounted_cash_flow", "npv", "irr", "payback_period", "sensitivity_analysis", "scenario_comparison")}}
    uwm_gate = {"status": "closed", "reason": "customer_approved_financial_scenario_handoff_missing", "uwm_may_supply": ["verified_intervention_quantity", "implementation_timing", "asset_transition", "uncertainty_envelope"], "uwm_must_not_supply": ["unit_price", "capital_cost", "operating_cost", "revenue", "discount_rate", "financing_terms", "financial_return"]}
    digest = {"assets": assets, "channels": channels}
    bundle_id = "financial-readiness-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {
        "schema": "uwm.financial_investment_readiness.v1",
        "bundle_id": bundle_id,
        "summary": {"evidence_asset_count": len(assets), "financial_channel_count": len(channels), "available_financial_channel_count": 0, "computed_financial_output_count": 0, "open_calculation_mechanism_count": 0},
        "evidence_assets": assets,
        "financial_channels": channels,
        "financial_outputs": outputs,
        "data_contracts": contracts,
        "calculation_gate": gate,
        "uwm_handoff_gate": uwm_gate,
        "source_artifacts": sorted(map(str, source_artifacts)),
        "claim_boundary": {"max_claim_level": "financial_data_contract_and_deterministic_calculation_readiness", "field_definition_not_financial_observation": True, "poi_count_not_revenue": True, "project_area_not_boq": True, "uwm_intervention_not_cost_or_benefit": True, "missing_cost_not_zero_cost": True, "missing_revenue_not_zero_revenue": True},
        "fabricated_value_count": 0,
    }
