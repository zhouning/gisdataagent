import json
from pathlib import Path

import pytest

from data_agent.test_build_uwm_livability_s2_fulu import MODULE as BUILD_MODULE
from data_agent.test_traditional_livability_s6_fulu_adapter import (
    _facility_product,
    _planning_fixture_root,
    _specs,
)
from data_agent.uwm import traditional_livability_s6_fulu_adapter as s6_adapter
from data_agent.uwm.livability_s2.scenario_service import (
    S2ProductInvalid,
    S2RunNotFound,
    S2ScenarioService,
)


def _product_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(s6_adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(BUILD_MODULE.s6_adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path / "sources")
    output = tmp_path / "product"
    result = BUILD_MODULE.build_s2_fulu(
        source_root=source_root,
        facility_product=_facility_product(),
        output_dir=output,
        kernel_version="0.1.0",
    )
    assert result["ready"] is True
    return output


def _first_parcel(service: S2ScenarioService) -> dict:
    return service.list_parcels()["features"][0]


def test_scenario_service_catalog_and_parcel_detail_are_snapshot_backed(tmp_path, monkeypatch):
    service = S2ScenarioService(_product_dir(tmp_path, monkeypatch))

    catalog = service.catalog()
    parcels = service.list_parcels()
    first = parcels["features"][0]
    detail = service.parcel_detail(str(first["id"]))

    assert catalog["ready"] is True
    assert catalog["parcel_count"] == 4
    assert catalog["kernel_version"] == "0.1.0"
    assert catalog["snapshot_digest"]
    assert catalog["facility_inventory_complete"] is False
    assert catalog["online_raw_vector_access"] is False
    assert detail["parcel"]["id"] == first["id"]
    assert detail["graph_context"]["direct_edge_count"] > 0
    assert detail["claim_boundary"]["max_claim_level"] == "bounded_action_conditioned_spatial_scenario"


def test_validate_action_binds_server_actor_and_preserves_review_boundary(tmp_path, monkeypatch):
    service = S2ScenarioService(_product_dir(tmp_path, monkeypatch))
    parcel = _first_parcel(service)
    current = parcel["properties"]["current_land_use_class"]
    target = next(
        value
        for value in service.catalog()["land_use_classes"]
        if value != current and value != "unresolved"
    )

    result = service.validate_action(
        parcel_id=str(parcel["id"]),
        from_land_use_class=current,
        to_land_use_class=target,
        snapshot_digest=service.catalog()["snapshot_digest"],
        rationale="服务端验证",
        requested_at="2026-07-11T08:00:00Z",
        actor_id="authenticated-user",
    )

    assert result["action"]["actor_id"] == "authenticated-user"
    assert result["action"]["actor_binding"] == "server_authenticated_identity"
    assert result["validation"]["valid"] is True
    assert result["validation"]["transition"]["status"] == "unresolved"
    assert result["validation"]["review_required"] is True
    assert result["approval_claim"] is False


def test_rollout_returns_auditable_run_and_never_enables_unsupported_heads(tmp_path, monkeypatch):
    service = S2ScenarioService(_product_dir(tmp_path, monkeypatch))
    parcel = _first_parcel(service)
    current = parcel["properties"]["current_land_use_class"]
    target = next(value for value in service.catalog()["land_use_classes"] if value != current)

    run = service.rollout(
        parcel_id=str(parcel["id"]),
        from_land_use_class=current,
        to_land_use_class=target,
        snapshot_digest=service.catalog()["snapshot_digest"],
        rationale="反事实推演",
        requested_at="2026-07-11T08:00:00Z",
        actor_id="authenticated-user",
        alternative_land_use_class=None,
    )
    loaded = service.get_run(run["run_id"], actor_id="authenticated-user")

    assert run == loaded
    assert run["run_id"].startswith("s2_run_")
    assert run["actor_id"] == "authenticated-user"
    assert run["snapshot_digest"] == service.catalog()["snapshot_digest"]
    assert run["execution_scope"]["source_snapshot_digest"] == run["snapshot_digest"]
    assert run["rollout"]["intervention"]["action"]["source_snapshot_digest"] == run["snapshot_digest"]
    assert run["rollout"]["intervention"]["action"]["snapshot_digest"] == run["execution_scope"]["rollout_snapshot_digest"]
    assert run["rollout"]["baseline"]["t0_snapshot_digest"] == run["execution_scope"]["rollout_snapshot_digest"]
    assert run["rollout"]["intervention"]["t0_snapshot_digest"] == run["execution_scope"]["rollout_snapshot_digest"]
    assert run["rollout"]["unsupported_prediction_heads_ready"] is False
    assert "approval_probability" in run["rollout"]["unavailable_effects"]
    assert run["persistence_boundary"] == "process_memory_only"
    assert run["map_evidence"]["target_parcel"]["features"]
    assert run["map_evidence"]["affected_parcels"]["type"] == "FeatureCollection"
    assert run["map_evidence"]["planning_resources"]["type"] == "FeatureCollection"
    assert run["map_evidence"]["facilities"]["type"] == "FeatureCollection"
    assert run["map_evidence"]["proxy_distance_bands_m"] == [50, 150, 300]
    with pytest.raises(S2RunNotFound, match="run_not_found"):
        service.get_run(run["run_id"], actor_id="other-user")


def test_service_rejects_stale_requests_and_missing_runs(tmp_path, monkeypatch):
    service = S2ScenarioService(_product_dir(tmp_path, monkeypatch))
    parcel = _first_parcel(service)

    with pytest.raises(ValueError, match="action_invalid:snapshot_digest_mismatch"):
        service.rollout(
            parcel_id=str(parcel["id"]),
            from_land_use_class=parcel["properties"]["current_land_use_class"],
            to_land_use_class="village_public_service_land",
            snapshot_digest="stale",
            rationale="过期请求",
            requested_at="2026-07-11T08:00:00Z",
            actor_id="authenticated-user",
            alternative_land_use_class=None,
        )
    with pytest.raises(S2RunNotFound, match="run_not_found"):
        service.get_run("s2_run_missing", actor_id="authenticated-user")


def test_service_fails_closed_when_any_product_digest_is_tampered(tmp_path, monkeypatch):
    product_dir = _product_dir(tmp_path, monkeypatch)
    path = product_dir / "uwm_livability_s2_graph_edges.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["edges"][0]["relation_type"] = "tampered"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    service = S2ScenarioService(product_dir)
    with pytest.raises(S2ProductInvalid, match="content_digest_mismatch"):
        service.catalog()


def test_service_rejects_cross_bundle_or_schema_mixed_products(tmp_path, monkeypatch):
    product_dir = _product_dir(tmp_path, monkeypatch)
    path = product_dir / "uwm_livability_s2_transition_matrix.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["bundle_id"] = "bundle-from-other-build"
    payload["content_digest"] = _scenario_digest(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(S2ProductInvalid, match="bundle_id_mismatch"):
        S2ScenarioService(product_dir).catalog()


def _scenario_digest(payload: dict) -> str:
    import hashlib

    content = {key: value for key, value in payload.items() if key != "content_digest"}
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_rollout_uses_bounded_local_subgraph_not_full_snapshot(tmp_path, monkeypatch):
    service = S2ScenarioService(_product_dir(tmp_path, monkeypatch))
    parcel = _first_parcel(service)
    current = parcel["properties"]["current_land_use_class"]
    target = next(value for value in service.catalog()["land_use_classes"] if value != current)

    run = service.rollout(
        parcel_id=str(parcel["id"]),
        from_land_use_class=current,
        to_land_use_class=target,
        snapshot_digest=service.catalog()["snapshot_digest"],
        rationale="局部子图推演",
        requested_at="2026-07-11T08:00:00Z",
        actor_id="authenticated-user",
        alternative_land_use_class=None,
    )

    execution = run["execution_scope"]
    assert execution["source_snapshot_node_count"] > execution["rollout_node_count"]
    assert execution["source_snapshot_edge_count"] > execution["rollout_edge_count"]
    assert execution["rollout_edge_count"] == execution["direct_edge_count"] + execution["cross_scale_edge_count"]
    assert execution["scope"] == "target_parcel_bounded_local_subgraph"
