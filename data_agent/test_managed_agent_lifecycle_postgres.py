"""PostgreSQL rehearsal for the managed Agent lifecycle API and runtime."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent import managed_agents
from data_agent.api import managed_agents_routes
from data_agent.db_engine import get_engine


class _RollbackOnlyEngine:
    """Route-compatible connection wrapper which rolls back the whole rehearsal."""

    def __init__(self, engine):
        self._connection = engine.connect()
        self._transaction = self._connection.begin()

    @contextmanager
    def begin(self):
        yield self._connection

    @contextmanager
    def connect(self):
        yield self._connection

    def close(self):
        if self._transaction.is_active:
            self._transaction.rollback()
        self._connection.close()


@pytest.fixture
def lifecycle_engine():
    engine = get_engine()
    if engine is None:
        pytest.skip("Database engine is not configured")
    facade = _RollbackOnlyEngine(engine)
    try:
        yield facade
    finally:
        facade.close()


def test_managed_agent_lifecycle_publishes_runtime_and_rolls_back(
    monkeypatch, lifecycle_engine,
):
    """Exercise create, test, approve, publish, disable, rollback, and archive."""
    tenant_id = f"lifecycle-test-{uuid4().hex}"
    owner = "managed-agent-lifecycle-test"

    def current_user(request):
        role = request.headers.get("x-test-role", "analyst")
        return SimpleNamespace(
            identifier=owner,
            metadata={"role": role, "tenant_id": tenant_id},
        )

    class _FakeLlmAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(managed_agents_routes, "_get_user_from_request", current_user)
    monkeypatch.setattr(managed_agents_routes, "get_engine", lambda: lifecycle_engine)
    monkeypatch.setattr(managed_agents, "get_engine", lambda: lifecycle_engine)
    monkeypatch.setattr("data_agent.agent.get_model_for_tier", lambda tier: f"test-{tier}")
    monkeypatch.setattr("google.adk.agents.llm_agent.LlmAgent", _FakeLlmAgent)

    app = Starlette(routes=managed_agents_routes.get_managed_agent_routes())
    agent_name = f"Lifecycle agent {uuid4().hex[:12]}"
    first_spec = {
        "name": agent_name,
        "description": "Lifecycle integration rehearsal",
        "instruction": "Inspect approved GIS data and return a concise answer.",
        "model_tier": "fast",
        "allowed_toolsets": [],
        "skill_refs": [],
        "data_policy": {"mode": "read_only"},
    }

    with TestClient(app) as client:
        created = client.post("/api/managed-agents", json=first_spec)
        assert created.status_code == 201, created.text
        agent_id = created.json()["agent"]["id"]

        assert client.post(f"/api/managed-agents/{agent_id}/test").status_code == 200
        assert client.post(f"/api/managed-agents/{agent_id}/submit").status_code == 200
        approved = client.post(
            f"/api/managed-agents/{agent_id}/approve",
            headers={"x-test-role": "admin"},
            json={"approve": True, "note": "approved by lifecycle rehearsal"},
        )
        assert approved.status_code == 200, approved.text
        published_v1 = client.post(f"/api/managed-agents/{agent_id}/publish")
        assert published_v1.status_code == 200, published_v1.text
        assert published_v1.json()["revision"] == 1

        runtime_v1, release_v1 = managed_agents.build_managed_agent(
            int(agent_id), user_id=owner, tenant_id=tenant_id,
        )
        assert release_v1["version"] == 1
        assert release_v1["revision"] == 1
        assert runtime_v1.kwargs["tools"] == []

        updated = client.put(
            f"/api/managed-agents/{agent_id}",
            json={"instruction": "Return a version-two lifecycle result."},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["agent"]["current_version"] == 2
        assert client.post(f"/api/managed-agents/{agent_id}/test").status_code == 200
        assert client.post(f"/api/managed-agents/{agent_id}/submit").status_code == 200
        assert client.post(
            f"/api/managed-agents/{agent_id}/approve",
            headers={"x-test-role": "admin"}, json={"approve": True},
        ).status_code == 200
        published_v2 = client.post(f"/api/managed-agents/{agent_id}/publish")
        assert published_v2.status_code == 200, published_v2.text
        assert published_v2.json()["revision"] == 2

        runtime_v2, release_v2 = managed_agents.build_managed_agent(
            int(agent_id), user_id=owner, tenant_id=tenant_id,
        )
        assert release_v2["version"] == 2
        assert release_v2["revision"] == 2
        assert "version-two" in runtime_v2.kwargs["instruction"]

        disabled = client.post(f"/api/managed-agents/{agent_id}/disable")
        assert disabled.status_code == 200, disabled.text
        with pytest.raises(managed_agents.ManagedAgentUnavailable):
            managed_agents.build_managed_agent(int(agent_id), user_id=owner, tenant_id=tenant_id)

        rolled_back = client.post(f"/api/managed-agents/{agent_id}/rollback", json={"version": 1})
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["revision"] == 3
        _, rollback_release = managed_agents.build_managed_agent(
            int(agent_id), user_id=owner, tenant_id=tenant_id,
        )
        assert rollback_release["version"] == 1
        assert rollback_release["revision"] == 3

        archived = client.post(f"/api/managed-agents/{agent_id}/archive")
        assert archived.status_code == 200, archived.text
        events = client.get(f"/api/managed-agents/{agent_id}/events")
        assert events.status_code == 200, events.text
        assert {
            "created", "tested", "submitted", "approved", "published", "disabled",
            "rolled_back", "archived",
        }.issubset({event["event_type"] for event in events.json()["events"]})
