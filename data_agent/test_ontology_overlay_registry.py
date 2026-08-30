from data_agent.ontology.overlay_registry import (
    list_overlay_descriptors,
    overlay_concept,
    overlay_concepts,
    overlay_summary,
)
from data_agent.api.ontology_routes import get_ontology_routes


def test_dmt_overlay_registry_discovers_current_source_overlays_without_ui_constants():
    descriptors = list_overlay_descriptors("abu-dhabi-dmt-gis")

    assert {item.source_key for item in descriptors} == {
        "liveability_data_20260730",
        "makani_sync_full",
    }
    assert all(item.overlay_id for item in descriptors)
    assert all(item.semantic_path and item.semantic_path.is_file() for item in descriptors)


def test_overlay_summary_exposes_governance_bindings_and_coverage():
    items = overlay_summary("abu-dhabi-dmt-gis")

    assert len(items) == 2
    liveability = next(item for item in items if item["source"]["database_name"] == "liveability_data_20260730")
    assert liveability["source"]["ingestion_mode"] == "virtual_source"
    assert liveability["source"]["source_rows_persisted"] is False
    assert liveability["binding"]["metadata_fingerprint"]
    assert liveability["binding"]["semantic_version"]
    assert liveability["coverage"]["resource_count"] == 159
    assert liveability["claim_boundary"]["unreviewed_assets_executable"] is False


def test_overlay_concepts_are_paged_and_detail_returns_fields():
    overlay_id = overlay_summary("abu-dhabi-dmt-gis")[0]["overlay_id"]
    page = overlay_concepts(
        "abu-dhabi-dmt-gis",
        overlay_id,
        query="facility",
        limit=3,
    )

    assert page["total"] > 0
    assert len(page["items"]) <= 3
    concept_id = page["items"][0]["concept_id"]
    detail = overlay_concept("abu-dhabi-dmt-gis", overlay_id, concept_id)
    assert detail is not None
    assert detail["concept"]["concept_id"] == concept_id
    assert detail["concept"]["field_count"] == len(detail["concept"]["fields"])
    assert all("physical_field" in field for field in detail["concept"]["fields"])


def test_scoped_ontology_routes_expose_overlay_read_model():
    paths = {route.path for route in get_ontology_routes()}
    assert "/api/ontologies/{ontology_key}/overlays" in paths
    assert "/api/ontologies/{ontology_key}/overlays/{overlay_id}/concepts" in paths
    assert "/api/ontologies/{ontology_key}/overlays/{overlay_id}/concept" in paths
