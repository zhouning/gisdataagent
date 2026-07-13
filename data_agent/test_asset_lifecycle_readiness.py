import pytest

from data_agent.uwm.asset_lifecycle_readiness import build_asset_lifecycle_readiness_product


def test_asset_product_keeps_record_counts_separate_and_lifecycle_closed():
    product = build_asset_lifecycle_readiness_product(source_products=[{"product_id": "buildings", "source_path": "overview.json", "bundle_id": "b1", "record_count": 10, "record_semantics": "building_footprints"}], source_artifacts=["overview.json"])
    assert product["schema"] == "uwm.asset_lifecycle_readiness.v1"
    assert product["summary"]["unique_asset_count"] is None
    assert all(channel["status"] == "unavailable" and channel["value"] is None for channel in product["lifecycle_channels"].values())
    assert all(value == "closed" for value in product["lifecycle_gate"]["mechanisms"].values())
    assert product["claim_boundary"]["source_record_count_not_unique_asset_count"] is True
    assert product["fabricated_value_count"] == 0


def test_source_product_cannot_claim_authoritative_assets_without_identity():
    with pytest.raises(ValueError, match="authoritative_asset_claim_requires_identity_evidence"):
        build_asset_lifecycle_readiness_product(source_products=[{"product_id": "bad", "source_path": "x", "bundle_id": "b", "asset_status": "authoritative_assets", "identity_evidence": None}], source_artifacts=["x"])
