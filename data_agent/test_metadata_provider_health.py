from pathlib import Path

import httpx

from data_agent.metadata_fabric import MetadataFabricSystem
from data_agent.metadata_provider_health import check_metadata_provider


def test_gravitino_health_requires_up_status_and_does_not_send_auth(monkeypatch) -> None:
    monkeypatch.setenv("GDA_GRAVITINO_URL", "http://gravitino.internal")
    monkeypatch.delenv("GDA_GRAVITINO_BEARER_TOKEN_FILE", raising=False)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "UP", "details": {"secret": "omit"}})

    result = check_metadata_provider(
        MetadataFabricSystem.GRAVITINO,
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "ok"
    assert result["endpoint"] == "/health"
    assert requests[0].url.path == "/health"
    assert requests[0].headers["accept"] == "*/*"
    assert "authorization" not in requests[0].headers
    assert "secret" not in result


def test_gravitino_health_rejects_false_health_document(monkeypatch) -> None:
    monkeypatch.setenv("GDA_GRAVITINO_URL", "http://gravitino.internal")

    result = check_metadata_provider(
        MetadataFabricSystem.GRAVITINO,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"status": "DOWN"})
        ),
    )

    assert result["status"] == "protocol_error"
    assert result["code"] == "health_status_not_up"


def test_openmetadata_health_classifies_unauthorized_without_response_body(
    monkeypatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "openmetadata-token"
    token_file.write_text("token\n", encoding="utf-8")
    monkeypatch.setenv("GDA_OPENMETADATA_URL", "https://metadata.internal")
    monkeypatch.setenv("GDA_OPENMETADATA_BEARER_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("GDA_OPENMETADATA_BEARER_TOKEN_SOURCE", raising=False)

    result = check_metadata_provider(
        MetadataFabricSystem.OPENMETADATA,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401,
                content=b"provider secret must not be returned",
                request=request,
            )
        ),
    )

    assert result["status"] == "unauthorized"
    assert result["status_code"] == 401
    assert "provider secret" not in str(result)


def test_configured_provider_transport_failure_is_retryable(monkeypatch) -> None:
    monkeypatch.setenv("GDA_GRAVITINO_URL", "http://gravitino.internal")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out")

    result = check_metadata_provider(
        MetadataFabricSystem.GRAVITINO,
        transport=httpx.MockTransport(handler),
    )

    assert result["status"] == "unavailable"
    assert result["retryable"] is True


def test_absent_provider_is_explicitly_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("GDA_GRAVITINO_URL", raising=False)
    monkeypatch.delenv("GDA_GRAVITINO_BEARER_TOKEN_FILE", raising=False)
    monkeypatch.delenv("GDA_OPENMETADATA_URL", raising=False)
    monkeypatch.delenv("GDA_OPENMETADATA_BEARER_TOKEN_FILE", raising=False)
    monkeypatch.delenv("GDA_OPENMETADATA_BEARER_TOKEN_SOURCE", raising=False)

    result = check_metadata_provider(MetadataFabricSystem.GRAVITINO)

    assert result["status"] == "unconfigured"
