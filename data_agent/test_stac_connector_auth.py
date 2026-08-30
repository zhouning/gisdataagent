"""Authentication contract tests for the STAC connector."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_agent.connectors.stac import StacConnector


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_bearer_auth_is_applied_to_every_stac_operation(mock_client_cls) -> None:
    response = MagicMock()
    response.json.return_value = {
        "id": "authenticated-stac",
        "stac_version": "1.0.0",
        "conformsTo": [],
        "collections": [],
        "features": [],
    }
    response.raise_for_status = MagicMock()
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = client

    connector = StacConnector()
    auth = {"type": "bearer", "token": "runtime-only-token"}
    await connector.health_check("https://example.com/v1", auth)
    await connector.get_capabilities("https://example.com/v1", auth)
    await connector.query("https://example.com/v1", auth, {})

    assert all(
        call.kwargs["headers"]["Authorization"] == "Bearer runtime-only-token"
        for call in client.get.await_args_list
    )
    assert client.post.await_args.kwargs["headers"]["Authorization"] == (
        "Bearer runtime-only-token"
    )
