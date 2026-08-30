from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "238_ogc_api_features_endpoint_contract.sql"
)


def test_ogc_api_features_endpoint_contract_migration_is_release_layer_bound():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "validate_ogc_api_features_endpoint_contract" in sql
    assert "gda.ogc_api_features_endpoint.v1" in sql
    assert "collection_id" in sql
    assert "service_release_binding" in sql
    assert "layer_definition_version" in sql
    assert "BEFORE INSERT ON gda_control.endpoint_revision" in sql
    assert "BEFORE INSERT ON gda_control.gis_service_endpoint_activation_event" in sql
    assert "USING ERRCODE = '23514'" in sql
