from pathlib import Path

import pytest

from data_agent.metadata_fabric import MetadataFabricSystem
from data_agent.metadata_provider_read import MetadataProviderReadService
from data_agent.metadata_provider_search import MetadataProviderSearchService
from data_agent.openmetadata_lineage_worker import (
    OpenMetadataLineageWorkerConfig,
)
from data_agent.openmetadata_master_data_worker import (
    OpenMetadataMasterDataWorkerConfig,
)
from data_agent.provider_credentials import (
    ProviderCredentialConfigurationError,
    resolve_bearer_token_file,
)


def _resolve(
    values: dict[str, str],
    *,
    cwd: Path | None = None,
    required: bool = False,
) -> Path | None:
    return resolve_bearer_token_file(
        file_env_name="GDA_OPENMETADATA_BEARER_TOKEN_FILE",
        source_env_name="GDA_OPENMETADATA_BEARER_TOKEN_SOURCE",
        error_factory=ProviderCredentialConfigurationError,
        environ=values,
        cwd=cwd,
        required=required,
    )


def test_source_only_accepts_relative_path_from_process_cwd(tmp_path: Path) -> None:
    token = tmp_path / "secrets" / "openmetadata_token"
    token.parent.mkdir()
    token.write_text("provider-token\n", encoding="utf-8")

    assert _resolve(
        {"GDA_OPENMETADATA_BEARER_TOKEN_SOURCE": "secrets/openmetadata_token"},
        cwd=tmp_path,
    ) == token


def test_file_only_requires_absolute_existing_regular_file(tmp_path: Path) -> None:
    token = tmp_path / "openmetadata_token"
    token.write_text("provider-token", encoding="utf-8")

    assert _resolve({"GDA_OPENMETADATA_BEARER_TOKEN_FILE": str(token)}) == token
    with pytest.raises(ProviderCredentialConfigurationError, match="absolute path"):
        _resolve({"GDA_OPENMETADATA_BEARER_TOKEN_FILE": "relative-token"})


def test_both_sources_must_resolve_to_the_same_file(tmp_path: Path) -> None:
    token = tmp_path / "openmetadata_token"
    token.write_text("provider-token", encoding="utf-8")

    assert _resolve(
        {
            "GDA_OPENMETADATA_BEARER_TOKEN_FILE": str(token),
            "GDA_OPENMETADATA_BEARER_TOKEN_SOURCE": "openmetadata_token",
        },
        cwd=tmp_path,
    ) == token

    other = tmp_path / "other_token"
    other.write_text("other-token", encoding="utf-8")
    with pytest.raises(ProviderCredentialConfigurationError, match="same file"):
        _resolve(
            {
                "GDA_OPENMETADATA_BEARER_TOKEN_FILE": str(token),
                "GDA_OPENMETADATA_BEARER_TOKEN_SOURCE": str(other),
            },
            cwd=tmp_path,
        )


def test_missing_required_source_fails_closed() -> None:
    with pytest.raises(ProviderCredentialConfigurationError, match="required"):
        _resolve({}, required=True)


def test_missing_or_non_file_source_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ProviderCredentialConfigurationError, match="does not exist"):
        _resolve(
            {"GDA_OPENMETADATA_BEARER_TOKEN_SOURCE": "missing-token"},
            cwd=tmp_path,
        )
    directory = tmp_path / "token-directory"
    directory.mkdir()
    with pytest.raises(ProviderCredentialConfigurationError, match="regular file"):
        _resolve(
            {"GDA_OPENMETADATA_BEARER_TOKEN_SOURCE": str(directory)},
            cwd=tmp_path,
        )


def test_openmetadata_worker_configs_use_source_only(monkeypatch, tmp_path: Path) -> None:
    token = tmp_path / "openmetadata_token"
    token.write_text("provider-token", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GDA_METADATA_FABRIC_TENANT_ID", "tenant-a")
    monkeypatch.setenv("GDA_OPENMETADATA_URL", "https://metadata.internal")
    monkeypatch.delenv("GDA_OPENMETADATA_BEARER_TOKEN_FILE", raising=False)
    monkeypatch.setenv("GDA_OPENMETADATA_BEARER_TOKEN_SOURCE", "openmetadata_token")

    assert OpenMetadataLineageWorkerConfig.from_env().bearer_token_file == token
    assert OpenMetadataMasterDataWorkerConfig.from_env().bearer_token_file == token


def test_provider_bridges_use_source_only(monkeypatch, tmp_path: Path) -> None:
    token = tmp_path / "openmetadata_token"
    token.write_text("provider-token", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GDA_OPENMETADATA_URL", "https://metadata.internal")
    monkeypatch.delenv("GDA_OPENMETADATA_BEARER_TOKEN_FILE", raising=False)
    monkeypatch.setenv("GDA_OPENMETADATA_BEARER_TOKEN_SOURCE", "openmetadata_token")

    with MetadataProviderReadService.from_env() as read_service:
        read_client = read_service._clients[MetadataFabricSystem.OPENMETADATA]
        assert read_client._bearer_token_file == token
    with MetadataProviderSearchService.from_env() as search_service:
        assert search_service._openmetadata._bearer_token_file == token
