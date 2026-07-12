import pytest

from data_agent.uwm.financial_readiness import build_financial_readiness_product


def test_financial_product_is_fail_closed_without_customer_financial_data():
    product = build_financial_readiness_product(
        evidence_assets=[{
            "asset_id": "financial-field-standard",
            "asset_class": "financial_data_standard",
            "source_path": "standard.yaml",
            "execution_status": "contract_only",
        }],
        source_artifacts=["standard.yaml"],
    )

    assert product["schema"] == "uwm.financial_investment_readiness.v1"
    assert all(channel["status"] == "unavailable" and channel["value"] is None for channel in product["financial_channels"].values())
    assert all(value is None for value in product["financial_outputs"].values())
    assert all(value == "closed" for value in product["calculation_gate"]["mechanisms"].values())
    assert product["uwm_handoff_gate"]["status"] == "closed"
    assert product["claim_boundary"]["uwm_intervention_not_cost_or_benefit"] is True
    assert product["fabricated_value_count"] == 0


def test_financial_standard_cannot_be_customer_observation():
    with pytest.raises(ValueError, match="standard_cannot_be_financial_observation"):
        build_financial_readiness_product(
            evidence_assets=[{
                "asset_id": "bad",
                "asset_class": "financial_data_standard",
                "source_path": "standard.yaml",
                "execution_status": "observed_customer_financial_data",
            }],
            source_artifacts=["standard.yaml"],
        )
