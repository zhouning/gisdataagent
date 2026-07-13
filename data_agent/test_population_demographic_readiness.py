import pytest

from data_agent.uwm.population_demographic_readiness import build_population_demographic_readiness_product


def test_population_product_keeps_demographics_and_forecast_closed():
    product = build_population_demographic_readiness_product(
        evidence_products=[{"product_id": "ghsl", "source_path": "overview.json", "bundle_id": "b1", "evidence_role": "population_spatial_proxy", "observation_year": 2020}],
        source_artifacts=["overview.json"],
    )
    assert product["schema"] == "uwm.population_demographic_readiness.v1"
    assert product["summary"]["authoritative_current_population"] is None
    assert product["summary"]["forecast_population"] is None
    assert all(channel["status"] == "unavailable" and channel["value"] is None for channel in product["demographic_channels"].values())
    assert all(value == "closed" for value in product["population_gate"]["mechanisms"].values())
    assert product["claim_boundary"]["population_proxy_not_authoritative_population"] is True
    assert product["fabricated_value_count"] == 0


def test_proxy_cannot_claim_authoritative_population():
    with pytest.raises(ValueError, match="proxy_cannot_be_authoritative_population"):
        build_population_demographic_readiness_product(
            evidence_products=[{"product_id": "bad", "source_path": "x", "evidence_role": "population_spatial_proxy", "population_status": "authoritative_current"}],
            source_artifacts=["x"],
        )
