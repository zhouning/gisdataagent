import json

import pytest

from data_agent.test_uwm_livability_s2_scenario import _product_dir
from data_agent.uwm.livability_s2.scenario_service import (
    S2RunInvalid,
    S2RunNotFound,
    S2ScenarioService,
)


def _durable_run(tmp_path, monkeypatch):
    product_dir = _product_dir(tmp_path, monkeypatch)
    store_dir = tmp_path / "run-store"
    service = S2ScenarioService(product_dir, store_dir)
    parcel = service.list_parcels()["features"][0]
    current = parcel["properties"]["current_land_use_class"]
    target = next(value for value in service.catalog()["land_use_classes"] if value != current)
    run = service.rollout(
        parcel_id=str(parcel["id"]),
        from_land_use_class=current,
        to_land_use_class=target,
        snapshot_digest=service.catalog()["snapshot_digest"],
        rationale="持久审计测试",
        requested_at="2026-07-14T01:00:00Z",
        actor_id="planner-1",
        alternative_land_use_class=None,
    )
    return product_dir, store_dir, run


def test_run_survives_service_restart_with_digest_verified_store(tmp_path, monkeypatch):
    product_dir, store_dir, run = _durable_run(tmp_path, monkeypatch)

    restarted = S2ScenarioService(product_dir, store_dir)
    restored = restarted.get_run(run["run_id"], actor_id="planner-1")

    assert restored == run
    assert restored["persistence_boundary"] == "durable_digest_verified_file_store"
    with pytest.raises(S2RunNotFound, match="run_not_found"):
        restarted.get_run(run["run_id"], actor_id="other-planner")


def test_tampered_durable_run_fails_integrity_check(tmp_path, monkeypatch):
    product_dir, store_dir, run = _durable_run(tmp_path, monkeypatch)
    path = store_dir / f"{run['run_id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["payload"]["parcel_id"] = "tampered"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(S2RunInvalid, match="run_record_digest_mismatch"):
        S2ScenarioService(product_dir, store_dir).get_run(
            run["run_id"], actor_id="planner-1"
        )
