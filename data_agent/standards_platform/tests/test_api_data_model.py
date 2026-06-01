"""API tests for /api/std/data-model/* endpoints (Wave 8)."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.data_model import (
    DataModelStrategy,
)
from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def _seed_one_element(engine, ver_id):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, representation_class, datatype, obligation, "
            "bound_table, bound_column) "
            "VALUES (:i, :v, 'E', '名', 'text', 'string', 'mandatory', "
            " 'cq_dltb', 'col')"
        ), {"i": eid, "v": ver_id})
    return eid


def _cleanup(engine, doc_id):
    """fresh_clause's teardown does the heavy lifting via FK cascade,
    but we cleanup non-cascading rows here for safety."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


# ---------------------------------------------------------------- auth


def test_data_model_get_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )
    r = _client().get(f"/api/std/data-model/{uuid.uuid4()}")
    assert r.status_code == 401


def test_data_model_ddl_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )
    r = _client().get(f"/api/std/data-model/{uuid.uuid4()}/ddl")
    assert r.status_code == 401


# ---------------------------------------------------------------- not found


def test_data_model_get_unknown_version_404(monkeypatch, engine):
    _auth_user(monkeypatch, role="admin")
    r = _client().get(f"/api/std/data-model/{uuid.uuid4()}")
    assert r.status_code == 404


def test_data_model_get_no_active_snapshot_404(monkeypatch, fresh_clause):
    """Version exists but no snapshot has been generated."""
    _, doc_id, ver_id = fresh_clause
    _auth_user(monkeypatch, role="admin")
    r = _client().get(f"/api/std/data-model/{ver_id}")
    assert r.status_code == 404
    assert "no active data-model snapshot" in r.json()["error"]


# ---------------------------------------------------------------- happy path


def test_data_model_get_returns_full_payload(monkeypatch, engine,
                                              fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_one_element(engine, ver_id)
    DataModelStrategy().run(version_id=ver_id, by_user="admin")
    _auth_user(monkeypatch, role="admin")
    try:
        r = _client().get(f"/api/std/data-model/{ver_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["version_id"] == ver_id
        assert body["stats"]["entity_count"] == 1
        assert body["stats"]["attribute_count"] == 1
        assert body["cdm"]["layer"] == "CDM"
        assert body["pdm"]["layer"] == "PDM"
        assert "CREATE TABLE" in body["ddl_postgresql"]
        assert "NOT NULL" in body["ddl_postgresql"]
    finally:
        pass  # fresh_clause teardown cleans up


def test_data_model_get_with_layer_param(monkeypatch, engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_one_element(engine, ver_id)
    DataModelStrategy().run(version_id=ver_id)
    _auth_user(monkeypatch, role="admin")

    for layer in ("cdm", "ldm", "pdm", "ddl"):
        r = _client().get(f"/api/std/data-model/{ver_id}?layer={layer}")
        assert r.status_code == 200, f"{layer}: {r.text}"
        assert r.json()["layer"] == layer.upper()


def test_data_model_get_invalid_layer_400(monkeypatch, engine, fresh_clause):
    _, _, ver_id = fresh_clause
    _seed_one_element(engine, ver_id)
    DataModelStrategy().run(version_id=ver_id)
    _auth_user(monkeypatch, role="admin")
    r = _client().get(f"/api/std/data-model/{ver_id}?layer=bogus")
    assert r.status_code == 400


def test_data_model_ddl_returns_text(monkeypatch, engine, fresh_clause):
    _, _, ver_id = fresh_clause
    _seed_one_element(engine, ver_id)
    DataModelStrategy().run(version_id=ver_id)
    _auth_user(monkeypatch, role="admin")
    r = _client().get(f"/api/std/data-model/{ver_id}/ddl")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    assert "Content-Disposition" in {k.title() for k in r.headers.keys()} \
           or "content-disposition" in r.headers
    assert "CREATE TABLE" in r.text


def test_data_model_snapshots_lists_history(monkeypatch, engine, fresh_clause):
    _, _, ver_id = fresh_clause
    _seed_one_element(engine, ver_id)
    DataModelStrategy().run(version_id=ver_id)
    DataModelStrategy().run(version_id=ver_id)  # re-derive
    _auth_user(monkeypatch, role="admin")

    r = _client().get(f"/api/std/data-model/{ver_id}/snapshots")
    assert r.status_code == 200
    snaps = r.json()["snapshots"]
    assert len(snaps) == 2
    statuses = [s["derived_status"] for s in snaps]
    # Newest first → first row is active, second is stale.
    assert statuses == ["active", "stale"]


def test_data_model_snapshots_unknown_version_404(monkeypatch, engine):
    _auth_user(monkeypatch, role="admin")
    r = _client().get(f"/api/std/data-model/{uuid.uuid4()}/snapshots")
    assert r.status_code == 404


def test_data_model_get_viewer_role_allowed(monkeypatch, engine, fresh_clause):
    """Read endpoints don't require admin — analyst/viewer can pull."""
    _, _, ver_id = fresh_clause
    _seed_one_element(engine, ver_id)
    DataModelStrategy().run(version_id=ver_id)
    _auth_user(monkeypatch, role="viewer")
    r = _client().get(f"/api/std/data-model/{ver_id}")
    assert r.status_code == 200
