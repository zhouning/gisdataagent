from __future__ import annotations

from typer.testing import CliRunner

from data_agent.capability_client import CapabilityInvocationResult
from data_agent.cli import app

runner = CliRunner()


class _FakeCapabilityClient:
    def __init__(self) -> None:
        self.list_calls = []
        self.detail_calls = []
        self.invoke_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def list_capabilities(self, **kwargs):
        self.list_calls.append(kwargs)
        return {
            "schema": "gda.capability-registry.v1",
            "fingerprint": "a" * 64,
            "count": 0,
            "capabilities": [],
        }

    def get_capability(self, capability_id, **kwargs):
        self.detail_calls.append((capability_id, kwargs))
        return {
            "spec": {"capability_id": capability_id, "version": "1.0.0"},
            "fingerprint": "b" * 64,
            "projections": {},
        }

    def invoke(self, capability_id, payload, **kwargs):
        self.invoke_calls.append((capability_id, payload, kwargs))
        return CapabilityInvocationResult(
            capability_id=capability_id,
            version=kwargs.get("version") or "1.0.0",
            fingerprint="c" * 64,
            status_code=200,
            data={
                "status": "success",
                "message": "Found 0 assets",
                "count": 0,
                "assets": [],
            },
            request_id="cli-request-1",
        )


def test_capability_list_uses_runtime_surface_filters(monkeypatch) -> None:
    client = _FakeCapabilityClient()
    monkeypatch.setattr(
        "data_agent.cli._new_capability_client",
        lambda base_url, token_file: client,
    )

    result = runner.invoke(
        app,
        ["capability", "list", "--surface", "cli", "--llm-mode", "disabled"],
    )

    assert result.exit_code == 0
    assert "gda.capability-registry.v1" in result.output
    assert client.list_calls == [{"surface": "cli", "llm_mode": "disabled"}]


def test_capability_show_forwards_explicit_version(monkeypatch) -> None:
    client = _FakeCapabilityClient()
    monkeypatch.setattr(
        "data_agent.cli._new_capability_client",
        lambda base_url, token_file: client,
    )

    result = runner.invoke(
        app,
        [
            "capability",
            "show",
            "dataops.run.cancel",
            "--version",
            "1.0.0",
        ],
    )

    assert result.exit_code == 0
    assert "dataops.run.cancel" in result.output
    assert client.detail_calls == [
        ("dataops.run.cancel", {"version": "1.0.0"})
    ]


def test_capability_invoke_emits_structured_receipt(monkeypatch) -> None:
    client = _FakeCapabilityClient()
    monkeypatch.setattr(
        "data_agent.cli._new_capability_client",
        lambda base_url, token_file: client,
    )

    result = runner.invoke(
        app,
        [
            "capability",
            "invoke",
            "catalog.asset.search",
            "--input-json",
            '{"query":"roads"}',
        ],
    )

    assert result.exit_code == 0
    assert "cli-request-1" in result.output
    assert "catalog.asset.search" in result.output
    assert client.invoke_calls == [
        ("catalog.asset.search", {"query": "roads"}, {"version": None})
    ]


def test_capability_invoke_rejects_non_object_input_before_network(
    monkeypatch,
) -> None:
    client = _FakeCapabilityClient()
    monkeypatch.setattr(
        "data_agent.cli._new_capability_client",
        lambda base_url, token_file: client,
    )

    result = runner.invoke(
        app,
        [
            "capability",
            "invoke",
            "catalog.asset.search",
            "--input-json",
            '["roads"]',
        ],
    )

    assert result.exit_code == 1
    assert "one JSON object" in result.output
    assert client.invoke_calls == []
