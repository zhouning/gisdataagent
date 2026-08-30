from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from data_agent.gis_mvt_http_purge_provider import (
    HTTP_MVT_CACHE_PURGE_SCHEMA,
    HTTPGISMVTCachePurgeProvider,
    HTTPGISMVTCachePurgeProviderConfigurationError,
    HTTPGISMVTCachePurgeProviderError,
)

GENERATION = "a" * 64


def _receipt(**overrides):
    payload = {
        "schema": HTTP_MVT_CACHE_PURGE_SCHEMA,
        "status": "succeeded",
        "generation_token": GENERATION,
        "matched_keys": 4,
        "deleted_keys": 4,
        "remaining_keys": 0,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_http_provider_posts_bounded_request_and_validates_receipt():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_receipt())

    provider = HTTPGISMVTCachePurgeProvider(
        "http://127.0.0.1:8080/purge",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await provider.purge_generation(GENERATION, max_keys=10, scan_count=2)
    finally:
        await provider.aclose()

    assert result.matched_keys == 4
    assert requests[0].url.path == "/purge"
    assert json.loads(requests[0].content) == {
        "generation_token": GENERATION,
        "max_keys": 10,
        "scan_count": 2,
        "schema": HTTP_MVT_CACHE_PURGE_SCHEMA,
    }


@pytest.mark.asyncio
async def test_http_provider_reads_bearer_token_file(tmp_path: Path):
    token_file = tmp_path / "purge-token"
    token_file.write_text("secret-token\n", encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(200, json=_receipt())

    provider = HTTPGISMVTCachePurgeProvider(
        "https://cache.example.test/invalidate",
        bearer_token_file=token_file,
        transport=httpx.MockTransport(handler),
    )
    try:
        await provider.purge_generation(GENERATION, max_keys=1, scan_count=1)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": "unavailable"}),
        httpx.Response(200, json=_receipt(generation_token="b" * 64)),
        httpx.Response(200, json=_receipt(remaining_keys=1)),
        httpx.Response(200, content=b"not-json"),
    ],
)
async def test_http_provider_rejects_transport_or_protocol_failures(response):
    provider = HTTPGISMVTCachePurgeProvider(
        "http://127.0.0.1:8080/purge",
        transport=httpx.MockTransport(lambda _request: response),
    )
    try:
        with pytest.raises(HTTPGISMVTCachePurgeProviderError):
            await provider.purge_generation(GENERATION, max_keys=10, scan_count=1)
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "endpoint",
    [
        "redis://127.0.0.1:6379/purge",
        "https://user:pass@example.test/purge",
        "https://example.test/purge?token=secret",
        "https://example.test/purge#fragment",
    ],
)
def test_http_provider_rejects_unsafe_endpoint(endpoint):
    with pytest.raises(HTTPGISMVTCachePurgeProviderConfigurationError):
        HTTPGISMVTCachePurgeProvider(endpoint)


def test_http_provider_rejects_invalid_timeout():
    with pytest.raises(HTTPGISMVTCachePurgeProviderConfigurationError, match="timeout"):
        HTTPGISMVTCachePurgeProvider("https://example.test/purge", timeout_seconds=61)
