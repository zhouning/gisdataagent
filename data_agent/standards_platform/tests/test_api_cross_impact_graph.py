"""API tests for the version-level cross-standard impact graph."""
from __future__ import annotations

import types
import uuid

from data_agent.standards_platform.tests.test_api_standards import (
    _auth_user, _client,
)


def test_version_impact_graph_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )

    r = _client().get(f"/api/std/impact/versions/{uuid.uuid4()}")

    assert r.status_code == 401


def test_version_impact_graph_missing_version_404(monkeypatch, engine):
    _auth_user(monkeypatch, role="viewer")

    r = _client().get(f"/api/std/impact/versions/{uuid.uuid4()}")

    assert r.status_code == 404
    assert r.json() == {"error": "version not found"}


def test_version_impact_graph_rejects_invalid_query_params(
    monkeypatch, fresh_clause
):
    _, _, ver_id = fresh_clause
    _auth_user(monkeypatch, role="viewer")

    bad_top_k = _client().get(
        f"/api/std/impact/versions/{ver_id}?top_k=not-an-int"
    )
    bad_min_similarity = _client().get(
        f"/api/std/impact/versions/{ver_id}?min_similarity=bad"
    )
    bad_bool = _client().get(
        f"/api/std/impact/versions/{ver_id}?include_similar=flase"
    )

    assert bad_top_k.status_code == 400
    assert bad_min_similarity.status_code == 400
    assert bad_bool.status_code == 400


def test_version_impact_graph_rejects_query_param_bounds(
    monkeypatch, fresh_clause
):
    _, _, ver_id = fresh_clause
    _auth_user(monkeypatch, role="viewer")

    too_low_similarity = _client().get(
        f"/api/std/impact/versions/{ver_id}?min_similarity=-0.1"
    )
    too_high_similarity = _client().get(
        f"/api/std/impact/versions/{ver_id}?min_similarity=1.1"
    )
    zero_top_k = _client().get(
        f"/api/std/impact/versions/{ver_id}?top_k=0"
    )

    assert too_low_similarity.status_code == 400
    assert too_high_similarity.status_code == 400
    assert zero_top_k.status_code == 400


def test_version_impact_graph_delegates_to_repository(
    monkeypatch, fresh_clause
):
    _, _, ver_id = fresh_clause
    _auth_user(monkeypatch, role="viewer")
    calls = []

    def fake_version_impact_graph(
        version_id, *, include_similar=True, min_similarity=0.8, top_k=20
    ):
        calls.append({
            "version_id": version_id,
            "include_similar": include_similar,
            "min_similarity": min_similarity,
            "top_k": top_k,
        })
        return {
            "version_id": version_id,
            "nodes": [{"id": f"version:{version_id}", "kind": "version"}],
            "edges": [],
            "summary": {
                "node_count": 1,
                "edge_count": 0,
                "by_edge_type": {},
                "cross_version_edge_count": 0,
            },
        }

    from data_agent.api import standards_routes

    monkeypatch.setattr(
        standards_routes,
        "_impact_graph",
        types.SimpleNamespace(version_impact_graph=fake_version_impact_graph),
        raising=False,
    )

    r = _client().get(
        f"/api/std/impact/versions/{ver_id}"
        "?include_similar=FALSE&min_similarity=0.72&top_k=120"
    )

    assert r.status_code == 200
    assert r.json()["version_id"] == ver_id
    assert calls == [{
        "version_id": ver_id,
        "include_similar": False,
        "min_similarity": 0.72,
        "top_k": 100,
    }]


def test_version_impact_graph_static_route_is_not_shadowed(
    monkeypatch, fresh_clause
):
    _, _, ver_id = fresh_clause
    _auth_user(monkeypatch, role="viewer")

    def fake_version_impact_graph(
        version_id, *, include_similar=True, min_similarity=0.8, top_k=20
    ):
        return {
            "version_id": version_id,
            "nodes": [],
            "edges": [],
            "summary": {
                "node_count": 0,
                "edge_count": 0,
                "by_edge_type": {},
                "cross_version_edge_count": 0,
            },
        }

    from data_agent.api import standards_routes

    monkeypatch.setattr(
        standards_routes,
        "_impact_graph",
        types.SimpleNamespace(version_impact_graph=fake_version_impact_graph),
        raising=False,
    )

    r = _client().get(f"/api/std/impact/versions/{ver_id}")

    assert r.status_code == 200
    assert r.json()["version_id"] == ver_id
