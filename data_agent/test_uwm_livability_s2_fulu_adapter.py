from pathlib import Path

from data_agent.test_traditional_livability_s6_fulu_adapter import (
    _facility_product,
    _planning_fixture_root,
    _specs,
)
from data_agent.uwm import traditional_livability_s6_fulu_adapter as s6_adapter
from data_agent.uwm.livability_s2.fulu_adapter import build_fulu_s2_inputs
from data_agent.uwm.livability_s2.state_builder import build_fulu_s2_state_graph


def _build(tmp_path: Path, monkeypatch, *, reverse_rows: bool = False) -> dict:
    monkeypatch.setattr(s6_adapter, "ASSET_SPECS", _specs())
    return build_fulu_s2_inputs(
        source_root=_planning_fixture_root(tmp_path, reverse_rows=reverse_rows),
        facility_product=_facility_product(),
    )


def test_fulu_s2_adapter_uses_current_parcels_and_overlays_planned_land_use(
    tmp_path, monkeypatch
):
    payload = _build(tmp_path, monkeypatch)

    assert payload["schema"] == "uwm.livability_s2.fulu_inputs.v1"
    assert payload["ready"] is True
    assert {row["planning_area_id"] for row in payload["parcels"]} == {
        "fulu_heping",
        "fulu_banzhu",
    }
    assert len(payload["parcels"]) == 4
    residential = [
        row for row in payload["parcels"] if row["current_land_use_class"] == "village_residential_land"
    ]
    assert len(residential) == 2
    assert all(row["source_layer"] == "JQDLTB" for row in payload["parcels"])
    assert all(row["source_land_use_code"] for row in payload["parcels"])
    assert all(row["current_resource_id"] for row in payload["parcels"])
    assert all(row["parcel_id"].startswith("parcel_") for row in payload["parcels"])
    assert any(
        row["planned_land_use_class"] == "village_public_service_land"
        and row["planned_overlap_count"] >= 1
        for row in residential
    )
    assert all("planned_overlap_evidence" in row for row in payload["parcels"])


def test_fulu_s2_adapter_preserves_s6_resource_ids_unmapped_objects_and_facilities(
    tmp_path, monkeypatch
):
    payload = _build(tmp_path, monkeypatch)
    s6_payload = s6_adapter.build_fulu_s6_resources(
        source_root=tmp_path, facility_product=_facility_product()
    )

    assert {row["resource_id"] for row in payload["planning_resources"]} == {
        row["resource_id"] for row in s6_payload["planning_resources"]
    }
    assert any(
        row["resource_domain"] == "unresolved" for row in payload["planning_resources"]
    )
    assert payload["current_facilities"] == s6_payload["current_facilities"]
    assert payload["facility_inventory"]["complete_inventory"] is False


def test_fulu_s2_adapter_is_stable_when_source_rows_are_reordered(tmp_path, monkeypatch):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = _build(first_root, monkeypatch, reverse_rows=False)
    second = _build(second_root, monkeypatch, reverse_rows=True)

    assert [row["parcel_id"] for row in first["parcels"]] == [
        row["parcel_id"] for row in second["parcels"]
    ]
    assert first["content_digest"] == second["content_digest"]


def test_fulu_s2_state_builder_creates_cross_scale_graph_with_traceable_edges(
    tmp_path, monkeypatch
):
    inputs = _build(tmp_path, monkeypatch)

    graph_product = build_fulu_s2_state_graph(inputs, kernel_version="0.1.0")

    assert graph_product["ready"] is True
    graph = graph_product["state_graph"]
    node_types = {node["node_type"] for node in graph["nodes"]}
    relation_types = {edge["relation_type"] for edge in graph["edges"]}
    assert {"parcel", "planning_resource", "facility", "village_context", "admin_context"} <= node_types
    assert "parcel_contains_resource" in relation_types
    assert "parcel_within_village" in relation_types
    assert "village_within_admin" in relation_types
    assert all(edge["evidence_refs"] for edge in graph["edges"])
    assert graph_product["build_report"]["parcel_count"] == len(inputs["parcels"])


def test_fulu_s2_adapter_returns_blockers_instead_of_synthetic_parcels(tmp_path, monkeypatch):
    monkeypatch.setattr(s6_adapter, "ASSET_SPECS", _specs())

    payload = build_fulu_s2_inputs(
        source_root=tmp_path / "missing",
        facility_product=_facility_product(),
    )

    assert payload["ready"] is False
    assert payload["parcels"] == []
    assert payload["blockers"]
    assert payload["synthetic_parcels_created"] is False
