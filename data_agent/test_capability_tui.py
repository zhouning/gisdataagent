from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from data_agent.capability_client import CapabilityInvocationResult
from data_agent.tui import GISAgentApp, PendingCapabilityInvocation

_CANCEL_PAYLOAD = {
    "run_id": "30000000-0000-4000-8000-000000000040",
    "client_request_id": "cancel-tui-20260805-001",
    "expected_state_version": 2,
    "reason": "operator cancelled an obsolete source refresh",
}


class _FakeCapabilityClient:
    def __init__(self) -> None:
        self.invoke_calls: list[tuple[str, dict, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def invoke(self, capability_id, payload, **kwargs):
        self.invoke_calls.append((capability_id, payload, kwargs))
        return CapabilityInvocationResult(
            capability_id=capability_id,
            version=kwargs["version"],
            fingerprint="c" * 64,
            status_code=202,
            data={"accepted": True},
            request_id="tui-request-1",
            created=True,
        )


@pytest.mark.asyncio
async def test_high_risk_tui_invocation_stages_without_network() -> None:
    app = GISAgentApp(user="operator", role="platform_operator")
    started: list[PendingCapabilityInvocation] = []
    app._start_capability_invocation = started.append

    async with app.run_test():
        app._handle_command(
            "/capability invoke dataops.run.cancel "
            + json.dumps(_CANCEL_PAYLOAD)
        )

        pending = app._pending_capability
        assert pending is not None
        assert pending.payload == _CANCEL_PAYLOAD
        assert pending.confirmation_code is not None
        assert len(pending.confirmation_code) == 12
        assert started == []


@pytest.mark.asyncio
async def test_tui_confirmation_is_bound_to_the_preview() -> None:
    app = GISAgentApp(user="operator", role="platform_operator")
    started: list[PendingCapabilityInvocation] = []
    app._start_capability_invocation = started.append

    async with app.run_test():
        app._handle_command(
            "/capability invoke dataops.run.cancel "
            + json.dumps(_CANCEL_PAYLOAD)
        )
        pending = app._pending_capability
        assert pending is not None

        app._handle_command("/capability confirm WRONG-CODE")
        assert started == []
        assert app._pending_capability is pending

        app._handle_command(
            f"/capability confirm {pending.confirmation_code}"
        )
        assert started == [pending]


@pytest.mark.asyncio
async def test_expired_tui_confirmation_cannot_execute() -> None:
    app = GISAgentApp(user="operator", role="platform_operator")
    started: list[PendingCapabilityInvocation] = []
    app._start_capability_invocation = started.append

    async with app.run_test():
        app._handle_command(
            "/capability invoke dataops.run.cancel "
            + json.dumps(_CANCEL_PAYLOAD)
        )
        pending = app._pending_capability
        assert pending is not None
        app._pending_capability = replace(pending, expires_at_monotonic=0.0)

        app._handle_command(
            f"/capability confirm {pending.confirmation_code}"
        )

        assert started == []
        assert app._pending_capability is None


@pytest.mark.asyncio
async def test_tui_rejects_invalid_input_before_invocation() -> None:
    app = GISAgentApp(user="operator", role="platform_operator")
    started: list[PendingCapabilityInvocation] = []
    app._start_capability_invocation = started.append

    async with app.run_test():
        app._handle_command(
            '/capability invoke dataops.run.cancel {"run_id":"invalid"}'
        )

        assert app._pending_capability is None
        assert started == []


@pytest.mark.asyncio
async def test_read_only_tui_capability_does_not_require_confirmation() -> None:
    app = GISAgentApp(user="analyst", role="analyst")
    started: list[PendingCapabilityInvocation] = []
    app._start_capability_invocation = started.append

    async with app.run_test():
        app._handle_command(
            '/capability invoke catalog.asset.search {"query":"roads"}'
        )

        assert app._pending_capability is None
        assert len(started) == 1
        assert started[0].confirmation_code is None


def test_tui_invocation_uses_delegated_token_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "session.token"
    token_file.write_text("secret-session-token\n", encoding="utf-8")
    fake_client = _FakeCapabilityClient()
    client_args = []

    def new_client(base_url, delegated_token_file):
        client_args.append((base_url, delegated_token_file))
        return fake_client

    monkeypatch.setenv("GDA_PLATFORM_URL", "https://platform.example.test")
    monkeypatch.setenv("GDA_ACCESS_TOKEN_FILE", str(token_file))
    monkeypatch.setattr("data_agent.cli._new_capability_client", new_client)
    pending = PendingCapabilityInvocation(
        capability_id="dataops.run.cancel",
        version="1.0.0",
        fingerprint="a" * 64,
        operation="command",
        risk="high",
        side_effect="external_write",
        payload=dict(_CANCEL_PAYLOAD),
        confirmation_code="ABCDEF123456",
        expires_at_monotonic=1.0,
    )

    result = GISAgentApp()._invoke_capability_sync(pending)

    assert result.request_id == "tui-request-1"
    assert client_args == [
        ("https://platform.example.test", token_file),
    ]
    assert fake_client.invoke_calls == [
        (
            "dataops.run.cancel",
            _CANCEL_PAYLOAD,
            {"version": "1.0.0"},
        )
    ]
