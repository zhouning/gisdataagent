"""Tests for the private ArcPy MCP client."""

import asyncio
import gc
import hashlib
import logging
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anyio
import httpx
import pytest

from data_agent.arcpy_mcp_client import (
    ArcPyMcpClient,
    ArcPyMcpError,
    PreparedLocalUpload,
    UploadedArtifact,
    package_local_dataset,
)
from data_agent.mcp_hub import McpServerConfig
from data_agent.user_context import current_user_id, get_user_upload_dir


@pytest.fixture(autouse=True)
def close_constructed_clients(monkeypatch):
    clients = []
    original_init = ArcPyMcpClient.__init__

    def tracked_init(client, *args, **kwargs):
        original_init(client, *args, **kwargs)
        clients.append(client)

    monkeypatch.setattr(ArcPyMcpClient, "__init__", tracked_init)
    yield
    for client in clients:
        try:
            asyncio.run(client.close())
        except BaseException:
            pass


def test_client_api_is_importable():
    assert ArcPyMcpClient is not None
    assert ArcPyMcpError is not None


def _client() -> ArcPyMcpClient:
    return ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )


@pytest.fixture
def user_upload_dir(tmp_path, monkeypatch):
    base = tmp_path / "uploads"
    base.mkdir()
    monkeypatch.setattr("data_agent.user_context._BASE_UPLOAD_DIR", str(base))
    monkeypatch.setattr("data_agent.gis_processors._BASE_UPLOAD_DIR", str(base))
    token = current_user_id.set("arcpy-test-user")
    try:
        yield Path(get_user_upload_dir())
    finally:
        current_user_id.reset(token)


def test_package_regular_file_preserves_metadata_and_streaming_hash(
    user_upload_dir,
):
    source = user_upload_dir / "roads.geojson"
    payload = b'{"type":"FeatureCollection","features":[]}'
    source.write_bytes(payload)

    prepared = package_local_dataset(source)

    assert prepared == PreparedLocalUpload(
        upload_path=source.resolve(),
        source_path=source.resolve(),
        logical_name="roads.geojson",
        media_type="application/geo+json",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        delete_after_upload=False,
    )


def test_package_shapefile_includes_required_and_optional_sidecars(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
        (user_upload_dir / f"roads{suffix}").write_bytes(suffix.encode())
    (user_upload_dir / "roads.shp.xml").write_bytes(b"metadata")
    (user_upload_dir / "other.dbf").write_bytes(b"ignore")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")

    assert prepared.upload_path.parent == user_upload_dir
    assert prepared.logical_name == "roads.zip"
    assert prepared.media_type == "application/zip"
    assert prepared.delete_after_upload is True
    with zipfile.ZipFile(prepared.upload_path) as archive:
        assert archive.namelist() == [
            "roads.cpg",
            "roads.dbf",
            "roads.prj",
            "roads.qix",
            "roads.shp",
            "roads.shp.xml",
            "roads.shx",
        ]
    prepared.upload_path.unlink()


def test_package_shapefile_does_not_accept_nested_stem_as_required_sidecars(
    user_upload_dir,
):
    (user_upload_dir / "roads.shp").write_bytes(b"shape")
    (user_upload_dir / "roads.backup.shx").write_bytes(b"index")
    (user_upload_dir / "roads.backup.dbf").write_bytes(b"table")

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_INCOMPLETE"


def test_package_shapefile_ignores_unknown_and_nested_stem_files(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".atx", ".xml"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"sidecar")
    (user_upload_dir / "roads.shp.xml").write_bytes(b"metadata")
    (user_upload_dir / "roads.secret").write_bytes(b"private")
    (user_upload_dir / "roads.backup.prj").write_bytes(b"backup")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")

    with zipfile.ZipFile(prepared.upload_path) as archive:
        assert archive.namelist() == [
            "roads.atx",
            "roads.dbf",
            "roads.prj",
            "roads.shp",
            "roads.shp.xml",
            "roads.shx",
            "roads.xml",
        ]
    prepared.upload_path.unlink()


def test_package_shapefile_rejects_known_sidecar_symlink(
    user_upload_dir,
):
    (user_upload_dir / "roads.shp").write_bytes(b"shape")
    (user_upload_dir / "roads.dbf").write_bytes(b"table")
    target = user_upload_dir / "real.shx"
    target.write_bytes(b"index")
    (user_upload_dir / "roads.shx").symlink_to(target)

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


@pytest.mark.parametrize("missing", [".shp", ".shx", ".dbf"])
def test_package_shapefile_requires_all_core_sidecars(
    user_upload_dir, missing
):
    for suffix in (".shp", ".shx", ".dbf"):
        if suffix != missing:
            (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    expected = (
        "ARCPY_INPUT_NOT_FOUND"
        if missing == ".shp"
        else "ARCPY_INPUT_INCOMPLETE"
    )
    assert exc_info.value.code == expected


def test_package_gdb_recurses_with_dataset_root(user_upload_dir):
    source = user_upload_dir / "parcels.gdb"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "a00000001.gdbtable").write_bytes(b"table")
    (nested / "index.bin").write_bytes(b"index")

    prepared = package_local_dataset(source)

    assert prepared.logical_name == "parcels.gdb.zip"
    with zipfile.ZipFile(prepared.upload_path) as archive:
        assert archive.namelist() == [
            "parcels.gdb/a00000001.gdbtable",
            "parcels.gdb/nested/index.bin",
        ]
    prepared.upload_path.unlink()


def test_package_empty_gdb_has_stable_incomplete_error(user_upload_dir):
    source = user_upload_dir / "empty.gdb"
    source.mkdir()

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(source)

    assert exc_info.value.code == "ARCPY_INPUT_INCOMPLETE"


def test_package_rejects_gdb_internal_symlink(user_upload_dir, tmp_path):
    source = user_upload_dir / "parcels.gdb"
    source.mkdir()
    outside = tmp_path / "private.bin"
    outside.write_bytes(b"private")
    (source / "link.bin").symlink_to(outside)

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(source)

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


@pytest.mark.parametrize(
    "provided",
    ["../outside.geojson", "C:\\private\\roads.shp", "\\\\host\\share\\roads.shp"],
)
def test_package_rejects_lexical_path_bypass(user_upload_dir, provided):
    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(provided)

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


def test_package_rejects_caller_symlink_even_when_target_is_in_sandbox(
    user_upload_dir,
):
    target = user_upload_dir / "target.geojson"
    target.write_bytes(b"{}")
    link = user_upload_dir / "link.geojson"
    link.symlink_to(target)

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(link)

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


def test_package_rejects_relative_caller_symlink_in_user_sandbox(
    user_upload_dir,
):
    target = user_upload_dir / "target.geojson"
    target.write_bytes(b"{}")
    (user_upload_dir / "link.geojson").symlink_to(target)

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset("link.geojson")

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


def test_package_rejects_windows_drive_relative_path(user_upload_dir):
    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset("C:roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


def test_package_cleans_partial_temp_archive_on_zip_failure(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    class FailingZipFile:
        def __init__(self, path, *args, **kwargs):
            Path(path).write_bytes(b"partial")

        def __enter__(self):
            raise OSError("zip failed")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(client_module.zipfile, "ZipFile", FailingZipFile)

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_PACKAGE_FAILED"
    assert list(user_upload_dir.glob("*.zip")) == []


class FakeUploadResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


class FakeSignedUploadClient:
    def __init__(self, outcomes, calls):
        self._outcomes = iter(outcomes)
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def put(self, url, *, headers, content, timeout):
        body = content.read()
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.mark.parametrize(
    "signed_url",
    [
        "http://signed.example/upload",
        "https:///missing-host",
        "https://user:password@signed.example/upload",
    ],
)
def test_signed_upload_url_requires_https_host_without_userinfo(signed_url):
    with pytest.raises(ArcPyMcpError) as exc_info:
        ArcPyMcpClient._signed_url({"upload_url": signed_url})

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"
    assert signed_url not in str(exc_info.value)
    assert signed_url not in repr(exc_info.value.details)


def _prepared_regular(user_upload_dir, payload=b"0123456789"):
    source = user_upload_dir / "sample.gpkg"
    source.write_bytes(payload)
    return package_local_dataset(source)


def _upload_client(outcomes, factory_calls, http_calls, **kwargs):
    def factory(**factory_kwargs):
        factory_calls.append(factory_kwargs)
        return FakeSignedUploadClient(outcomes, http_calls)

    return ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=factory,
        upload_timeout=17.0,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_upload_uses_exact_metadata_offset_zero_and_no_authorization(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    factory_calls = []
    http_calls = []
    client = _upload_client(
        [FakeUploadResponse()], factory_calls, http_calls
    )
    tool_calls = []

    async def call_tool(name, arguments):
        tool_calls.append((name, arguments))
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload-one",
            }
        if name == "complete_upload":
            return {
                "state": "ready",
                "artifact_id": "artifact-1",
                "verified_sha256": prepared.sha256,
                "size": prepared.size,
            }
        raise AssertionError(name)

    client.call_tool = call_tool

    artifact_id = await client._upload_prepared(prepared)

    assert artifact_id == "artifact-1"
    assert tool_calls == [
        (
            "create_upload",
            {
                "logical_name": prepared.logical_name,
                "expected_size": prepared.size,
                "expected_sha256": prepared.sha256,
                "media_type": prepared.media_type,
            },
        ),
        ("complete_upload", {"artifact_id": "artifact-1"}),
    ]
    assert factory_calls == [{"follow_redirects": True}]
    assert http_calls == [
        {
            "url": "https://signed.example/upload-one",
            "headers": {"Upload-Offset": "0"},
            "body": b"0123456789",
            "timeout": 17.0,
        }
    ]
    assert "Authorization" not in repr(factory_calls + http_calls)


@pytest.mark.asyncio
async def test_upload_resumes_from_strict_server_committed_offset(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    factory_calls = []
    http_calls = []
    interrupted = httpx.ReadError(
        "interrupted",
        request=httpx.Request("PUT", "https://signed.example/upload"),
    )
    client = _upload_client(
        [interrupted, FakeUploadResponse()], factory_calls, http_calls
    )
    tool_calls = []

    async def call_tool(name, arguments):
        tool_calls.append((name, arguments))
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "signed_url": "https://signed.example/upload",
            }
        if name == "get_upload_status":
            return {"artifact_id": "artifact-1", "committed_size": 4}
        if name == "complete_upload":
            return {
                "state": "ready",
                "artifact_id": "artifact-1",
                "actual_sha256": prepared.sha256,
                "actual_size": prepared.size,
            }
        raise AssertionError(name)

    client.call_tool = call_tool

    await client._upload_prepared(prepared)

    assert [call["headers"] for call in http_calls] == [
        {"Upload-Offset": "0"},
        {"Upload-Offset": "4"},
    ]
    assert http_calls[1]["body"] == b"456789"
    assert ("get_upload_status", {"artifact_id": "artifact-1"}) in tool_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("expired_status", [401, 403])
async def test_upload_expired_url_renews_and_resumes_from_server_offset(
    user_upload_dir, expired_status
):
    prepared = _prepared_regular(user_upload_dir)
    factory_calls = []
    http_calls = []
    client = _upload_client(
        [FakeUploadResponse(expired_status), FakeUploadResponse()],
        factory_calls,
        http_calls,
    )
    names = []

    async def call_tool(name, arguments):
        names.append(name)
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/expired",
            }
        if name == "get_upload_status":
            return {"committed_size": 3}
        if name == "renew_upload":
            return {"signed_url": "https://signed.example/renewed"}
        if name == "complete_upload":
            return {
                "state": "ready",
                "artifact_id": "artifact-1",
                "verified_sha256": prepared.sha256,
                "actual_size_bytes": prepared.size,
            }
        raise AssertionError(name)

    client.call_tool = call_tool

    await client._upload_prepared(prepared)

    assert names == [
        "create_upload",
        "get_upload_status",
        "renew_upload",
        "complete_upload",
    ]
    assert http_calls[1]["url"] == "https://signed.example/renewed"
    assert http_calls[1]["headers"] == {"Upload-Offset": "3"}


@pytest.mark.asyncio
async def test_upload_rejects_renewal_for_different_artifact(user_upload_dir):
    prepared = _prepared_regular(user_upload_dir)
    factory_calls = []
    http_calls = []
    client = _upload_client(
        [FakeUploadResponse(403)], factory_calls, http_calls
    )

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/expired",
            }
        if name == "get_upload_status":
            return {"artifact_id": "artifact-1", "committed_size": 3}
        if name == "renew_upload":
            return {
                "artifact_id": "artifact-other",
                "upload_url": "https://signed.example/wrong",
            }
        if name == "delete_artifact":
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("committed_size", [-1, 11, True, "4", None])
async def test_upload_rejects_invalid_committed_offset(
    user_upload_dir, committed_size
):
    prepared = _prepared_regular(user_upload_dir)
    factory_calls = []
    http_calls = []
    interrupted = httpx.ReadError(
        "interrupted",
        request=httpx.Request("PUT", "https://signed.example/upload"),
    )
    client = _upload_client([interrupted], factory_calls, http_calls)
    deleted = []

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "get_upload_status":
            return {"committed_size": committed_size}
        if name == "delete_artifact":
            deleted.append(arguments)
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"
    assert deleted == [{"artifact_id": "artifact-1"}]


@pytest.mark.asyncio
async def test_upload_network_failures_are_bounded_and_cleanup_artifact(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    factory_calls = []
    http_calls = []
    failures = [
        httpx.ReadError(
            "interrupted",
            request=httpx.Request("PUT", "https://signed.example/upload"),
        )
        for _ in range(3)
    ]
    client = _upload_client(failures, factory_calls, http_calls)
    names = []

    async def call_tool(name, arguments):
        names.append(name)
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "get_upload_status":
            return {"committed_size": 0}
        if name == "delete_artifact":
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"
    assert len(http_calls) == 3
    assert names.count("get_upload_status") == 2
    assert names[-1] == "delete_artifact"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "completion",
    [
        {
            "state": "pending",
            "artifact_id": "artifact-1",
            "verified_sha256": "local",
            "size": 5,
        },
        {
            "state": "ready",
            "artifact_id": "other",
            "verified_sha256": "local",
            "size": 5,
        },
        {
            "state": "ready",
            "artifact_id": "artifact-1",
            "verified_sha256": "wrong",
            "size": 5,
        },
        {
            "state": "ready",
            "artifact_id": "artifact-1",
            "verified_sha256": "local",
            "size": 999,
        },
        {"state": "ready", "artifact_id": "artifact-1", "size": 5},
        {"state": "ready", "verified_sha256": "local", "size": 5},
        {
            "state": "ready",
            "artifact_id": "artifact-1",
            "verified_sha256": "local",
        },
        {
            "state": "ready",
            "artifact_id": "artifact-1",
            "verified_sha256": "local",
            "actual_sha256": "wrong",
            "size": 5,
        },
        {
            "state": "ready",
            "artifact_id": "artifact-1",
            "verified_sha256": "local",
            "size": 5,
            "actual_size": 999,
        },
    ],
)
async def test_upload_rejects_unverified_completion_and_cleans_artifact(
    user_upload_dir, completion
):
    prepared = _prepared_regular(user_upload_dir, payload=b"local")
    factory_calls = []
    http_calls = []
    client = _upload_client(
        [FakeUploadResponse()], factory_calls, http_calls
    )
    deleted = []

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "complete_upload":
            result = dict(completion)
            if result.get("verified_sha256") == "local":
                result["verified_sha256"] = prepared.sha256
            return result
        if name == "delete_artifact":
            deleted.append(arguments)
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_UPLOAD_VERIFICATION_FAILED"
    assert deleted == [{"artifact_id": "artifact-1"}]


@pytest.mark.asyncio
async def test_upload_nonexpired_http_failure_is_stable_and_sanitized(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    factory_calls = []
    http_calls = []
    signed_url = "https://signed.example/private?signature=fixture-secret"
    client = _upload_client(
        [FakeUploadResponse(500)], factory_calls, http_calls
    )

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {"artifact_id": "artifact-1", "upload_url": signed_url}
        if name == "delete_artifact":
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"
    assert signed_url not in str(exc_info.value)
    assert signed_url not in repr(exc_info.value.details)


@pytest.mark.asyncio
async def test_signed_upload_url_is_redacted_from_root_and_httpx_logs(
    user_upload_dir, caplog
):
    from data_agent.mcp_transport import current_runtime_secrets

    prepared = _prepared_regular(user_upload_dir)
    opaque_path = "opaque-path-fixture-secret"
    opaque_query = "opaque-query-fixture-secret"
    signed_url = (
        f"https://signed.example/{opaque_path}?custom={opaque_query}"
    )
    caplog.set_level(logging.INFO)
    httpx_handler = logging.StreamHandler()
    logging.getLogger("httpx").addHandler(httpx_handler)

    def handler(request):
        logging.getLogger().info("root signed request %s", request.url)
        logging.getLogger("httpx.fixture").info(
            "httpx signed request %s", request.url
        )
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    class HttpxSignedClient:
        def __init__(self, **kwargs):
            self.client = httpx.AsyncClient(transport=transport, **kwargs)

        async def __aenter__(self):
            await self.client.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

        async def put(self, url, *, headers, content, timeout):
            return await self.client.put(
                url,
                headers=headers,
                content=content.read(),
                timeout=timeout,
            )

    def factory(**kwargs):
        return HttpxSignedClient(**kwargs)

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=factory,
    )

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {"artifact_id": "artifact-1", "upload_url": signed_url}
        if name == "complete_upload":
            return {
                "state": "ready",
                "artifact_id": "artifact-1",
                "verified_sha256": prepared.sha256,
                "size": prepared.size,
            }
        raise AssertionError(name)

    client.call_tool = call_tool
    try:
        await client._upload_prepared(prepared)
    finally:
        logging.getLogger("httpx").removeHandler(httpx_handler)

    logs = caplog.text
    assert signed_url not in logs
    assert opaque_path not in logs
    assert opaque_query not in logs
    assert signed_url not in current_runtime_secrets()


@pytest.mark.asyncio
async def test_signed_upload_client_uses_only_configured_custom_ca(
    user_upload_dir, tmp_path, monkeypatch
):
    prepared = _prepared_regular(user_upload_dir)
    ca_bundle = tmp_path / "ca.pem"
    ca_bundle.write_text("fixture certificate", encoding="utf-8")
    monkeypatch.setenv("ARCPY_TEST_CA", str(ca_bundle))
    factory_calls = []
    http_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return FakeSignedUploadClient([FakeUploadResponse()], http_calls)

    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            ca_bundle_env_var="ARCPY_TEST_CA",
        ),
        signed_http_client_factory=factory,
    )

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "complete_upload":
            return {
                "state": "ready",
                "artifact_id": "artifact-1",
                "verified_sha256": prepared.sha256,
                "size": prepared.size,
            }
        raise AssertionError(name)

    client.call_tool = call_tool

    await client._upload_prepared(prepared)

    assert factory_calls == [
        {"follow_redirects": True, "verify": str(ca_bundle)}
    ]
    assert "Authorization" not in repr(factory_calls)


@pytest.mark.asyncio
async def test_upload_cleanup_failure_does_not_replace_original_error(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    client = _upload_client([FakeUploadResponse(500)], [], [])

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "delete_artifact":
            raise ArcPyMcpError(
                "ARCPY_MCP_UNREACHABLE", "private cleanup failure"
            )
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"


class AdvancingSleep:
    def __init__(self, clock):
        self.clock = clock
        self.delays = []

    async def __call__(self, delay):
        self.delays.append(delay)
        self.clock.advance(delay)


@pytest.mark.asyncio
async def test_inspect_polls_until_succeeded_and_returns_dataset_path():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
        inspection_timeout=40.0,
    )
    calls = []
    jobs = iter(
        [
            {"job_id": "job-1", "status": "queued"},
            {"job_id": "job-1", "status": "running"},
            {
                "job_id": "job-1",
                "status": "succeeded",
                "result": {
                    "dataset": {
                        "artifact_id": "artifact-1",
                        "path": "roads.shp",
                    }
                },
            },
        ]
    )

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "get_job":
            return next(jobs)
        raise AssertionError(name)

    client.call_tool = call_tool

    path = await client._inspect_uploaded_artifact("artifact-1")

    assert path == "roads.shp"
    assert calls[0] == (
        "inspect_dataset",
        {"artifact_id": "artifact-1", "path": "."},
    )
    assert sleep.delays == [2, 5, 10]


@pytest.mark.asyncio
async def test_inspect_supports_result_artifact_path_contract():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
    )
    client.call_tool = AsyncMock(
        side_effect=[
            {"job_id": "job-1"},
            {
                "status": "succeeded",
                "artifact_id": "artifact-1",
                "result": {"artifact_path": "parcels.gdb"},
            },
        ]
    )

    assert (
        await client._inspect_uploaded_artifact("artifact-1")
        == "parcels.gdb"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["failed", "timed_out", "cancelled", "interrupted"]
)
async def test_inspect_terminal_failure_reads_log_but_returns_stable_error(
    status,
):
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
    )
    private_log = "C:\\private\\worker.gdb Authorization: Bearer fixture"
    client.call_tool = AsyncMock(
        side_effect=[
            {"job_id": "job-1"},
            {"status": status},
            {"messages": [private_log]},
        ]
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_INSPECTION_FAILED"
    assert private_log not in str(exc_info.value)
    assert private_log not in repr(exc_info.value.details)
    assert client.call_tool.await_args_list[-1].args == (
        "get_job_log",
        {"job_id": "job-1"},
    )


@pytest.mark.asyncio
async def test_inspect_times_out_with_bounded_polling():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
        inspection_timeout=6.0,
    )

    async def call_tool(name, arguments):
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "get_job":
            return {"status": "running"}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_JOB_TIMED_OUT"
    assert sleep.delays == [2, 5]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "artifact_path",
    [
        "",
        ".",
        "/private/roads.shp",
        "C:\\private\\roads.shp",
        "\\\\host\\share\\roads.shp",
        "../roads.shp",
        "folder/../../roads.shp",
    ],
)
async def test_inspect_rejects_unsafe_artifact_relative_path(artifact_path):
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
    )
    client.call_tool = AsyncMock(
        side_effect=[
            {"job_id": "job-1"},
            {
                "status": "succeeded",
                "result": {
                    "dataset": {
                        "artifact_id": "artifact-1",
                        "path": artifact_path,
                    }
                },
            },
        ]
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_inspect_rejects_result_for_different_artifact():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
    )
    client.call_tool = AsyncMock(
        side_effect=[
            {"job_id": "job-1"},
            {
                "status": "succeeded",
                "result": {
                    "dataset": {
                        "artifact_id": "artifact-other",
                        "path": "roads.shp",
                    }
                },
            },
        ]
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_inspect_rejects_unbound_result_path():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
    )
    client.call_tool = AsyncMock(
        side_effect=[
            {"job_id": "job-1"},
            {
                "status": "succeeded",
                "result": {"dataset": {"path": "roads.shp"}},
            },
        ]
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_prepare_input_rejects_missing_and_outside_sandbox(
    user_upload_dir, tmp_path
):
    outside = tmp_path / "outside.geojson"
    outside.write_bytes(b"{}")
    client = _client()
    client._upload_prepared = AsyncMock()

    for provided, expected in (
        (user_upload_dir / "missing.geojson", "ARCPY_INPUT_NOT_FOUND"),
        (outside, "ARCPY_INPUT_OUTSIDE_SANDBOX"),
    ):
        with pytest.raises(ArcPyMcpError) as exc_info:
            await client.prepare_input(provided)
        assert exc_info.value.code == expected

    client._upload_prepared.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_input_returns_uploaded_artifact_in_required_order(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(suffix.encode())
    source = (user_upload_dir / "roads.shp").resolve()
    events = []
    client = _client()

    async def upload(prepared):
        events.append(("upload", prepared.logical_name))
        assert prepared.upload_path.exists()
        return "artifact-1"

    async def inspect(artifact_id):
        events.append(("inspect", artifact_id))
        return "roads.shp"

    client._upload_prepared = upload
    client._inspect_uploaded_artifact = inspect

    uploaded = await client.prepare_input(source)

    assert uploaded == UploadedArtifact(
        artifact_id="artifact-1",
        artifact_path="roads.shp",
        source_path=source,
        local_package_path=uploaded.local_package_path,
        delete_local_package=True,
    )
    assert events == [("upload", "roads.zip"), ("inspect", "artifact-1")]
    assert uploaded.local_package_path.parent == user_upload_dir
    assert uploaded.local_package_path.exists()
    uploaded.local_package_path.unlink()


@pytest.mark.asyncio
async def test_prepare_input_regular_file_is_not_marked_for_local_cleanup(
    user_upload_dir,
):
    source = user_upload_dir / "roads.tif"
    source.write_bytes(b"raster")
    client = _client()
    client._upload_prepared = AsyncMock(return_value="artifact-1")
    client._inspect_uploaded_artifact = AsyncMock(return_value="roads.tif")

    uploaded = await client.prepare_input(source)

    assert uploaded.local_package_path == source.resolve()
    assert uploaded.delete_local_package is False
    assert source.exists()


@pytest.mark.asyncio
async def test_prepare_input_inspection_failure_cleans_remote_and_temp_package(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")
    client = _client()
    package_paths = []

    async def upload(prepared):
        package_paths.append(prepared.upload_path)
        return "artifact-1"

    client._upload_prepared = upload
    client._inspect_uploaded_artifact = AsyncMock(
        side_effect=ArcPyMcpError(
            "ARCPY_INSPECTION_FAILED", "private inspection detail"
        )
    )
    client.call_tool = AsyncMock(return_value={})

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.prepare_input(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INSPECTION_FAILED"
    assert package_paths and not package_paths[0].exists()
    client.call_tool.assert_awaited_once_with(
        "delete_artifact", {"artifact_id": "artifact-1"}
    )


@pytest.mark.asyncio
async def test_prepare_input_cleanup_failure_preserves_inspection_error(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")
    client = _client()
    package_paths = []

    async def upload(prepared):
        package_paths.append(prepared.upload_path)
        return "artifact-1"

    client._upload_prepared = upload
    client._inspect_uploaded_artifact = AsyncMock(
        side_effect=ArcPyMcpError(
            "ARCPY_INSPECTION_FAILED", "private inspection failure"
        )
    )
    client.call_tool = AsyncMock(
        side_effect=ArcPyMcpError(
            "ARCPY_MCP_UNREACHABLE", "private cleanup failure"
        )
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.prepare_input(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INSPECTION_FAILED"
    assert package_paths and not package_paths[0].exists()


@pytest.mark.asyncio
async def test_prepare_input_upload_failure_cleans_temp_package(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")
    client = _client()
    package_paths = []

    async def fail_upload(prepared):
        package_paths.append(prepared.upload_path)
        raise ArcPyMcpError("ARCPY_UPLOAD_FAILED", "private URL")

    client._upload_prepared = fail_upload

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.prepare_input(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"
    assert package_paths and not package_paths[0].exists()


def _result(*, structured=None, text=None, error=False, snake_case=False):
    attributes = {"content": [] if text is None else [SimpleNamespace(text=text)]}
    if snake_case:
        attributes.update(is_error=error, structured_content=structured)
    else:
        attributes.update(isError=error, structuredContent=structured)
    return SimpleNamespace(**attributes)


def test_error_has_stable_code_dict_details_and_sanitized_repr():
    error = ArcPyMcpError(
        "ARCPY_TEST",
        "Authorization: Bearer fixture-credential",
        {
            "url": "https://download.example/item?signature=fixture-signature",
            "Authorization: Bearer fixture-key-credential": RuntimeError(
                "Authorization: Bearer fixture-value-credential"
            ),
        },
    )

    assert error.code == "ARCPY_TEST"
    assert error.details["url"] == "[REDACTED]"
    assert "fixture-credential" not in str(error)
    assert "fixture-signature" not in repr(error)
    assert "fixture-key-credential" not in repr(error.details)
    assert "fixture-value-credential" not in repr(error.details)


def test_error_redacts_runtime_secret_private_url_and_absolute_paths():
    from data_agent.mcp_transport import (
        register_runtime_secrets,
        unregister_runtime_secrets,
    )

    credential = "fixture-bare-runtime-credential"
    private_url = "https://10.1.2.3/private/service"
    unix_path = "/private/ca.pem"
    windows_path = "C:\\private\\ca.pem"
    register_runtime_secrets([credential])
    try:
        error = ArcPyMcpError(
            "ARCPY_TEST",
            f"failure {credential} {private_url} {unix_path} {windows_path}",
            {
                f"key-{credential}": private_url,
                "unix": unix_path,
                "windows": windows_path,
            },
        )
    finally:
        unregister_runtime_secrets([credential])

    public_state = f"{error!s} {error.details!r}"
    for sensitive in (
        credential,
        private_url,
        "10.1.2.3",
        unix_path,
        windows_path,
    ):
        assert sensitive not in public_state


def test_error_strictly_redacts_ipv6_unc_and_paths_with_spaces():
    ipv6 = "fd00::1234"
    unc_path = "\\\\server\\share\\private-ca.pem"
    unix_path = "/private/ca bundles/root.pem"
    windows_path = "C:\\private ca\\root.pem"
    error = ArcPyMcpError(
        "ARCPY_TEST",
        f"unsafe {ipv6} {unc_path} {unix_path} {windows_path}",
        {
            "safe-key": ipv6,
            unc_path: "unsafe-key",
            "unix": unix_path,
            "windows": windows_path,
        },
    )

    assert str(error) == "[REDACTED]"
    assert error.details["safe-key"] == "[REDACTED]"
    public_details = repr(error.details)
    for fragment in (
        "fd00",
        "server",
        "share",
        "private-ca",
        "ca bundles",
        "private ca",
        "root.pem",
    ):
        assert fragment not in public_details


@pytest.mark.parametrize(
    "sensitive",
    [
        "host=fd00::1234",
        "host=10.0.0.8:8443",
        "path=C:\\private ca\\root.pem",
        "path=C:/private ca/root.pem",
    ],
)
def test_error_redacts_embedded_location_tokens_as_whole_strings(sensitive):
    error = ArcPyMcpError(
        "ARCPY_TEST",
        sensitive,
        {sensitive: sensitive},
    )

    assert str(error) == "[REDACTED]"
    assert error.details == {"[REDACTED]": "[REDACTED]"}
    assert sensitive not in repr(error.details)


@pytest.mark.parametrize(
    "unsafe",
    [
        "worker=10.0.0.8:8443.",
        "worker=fd00::1234.",
        "endpoint=redis://internal-host:6379/0",
        "path:/private/ca.pem",
        "path:C:\\private\\ca.pem",
    ],
)
def test_unknown_error_code_fails_closed_for_message_and_details(unsafe):
    error = ArcPyMcpError("ARCPY_UNKNOWN", unsafe, {unsafe: unsafe})

    assert str(error) == "[REDACTED]"
    assert error.details == {"[REDACTED]": "[REDACTED]"}
    assert unsafe not in repr(error.details)


def test_known_error_code_ignores_caller_supplied_message():
    error = ArcPyMcpError(
        "ARCPY_MCP_UNREACHABLE",
        "caller supplied diagnostic must not be public",
    )

    assert str(error) == "ArcPy MCP service is unreachable"


def test_error_details_preserve_only_safe_identifiers_and_scalar_values():
    error = ArcPyMcpError(
        "ARCPY_JOB_FAILED",
        "ignored",
        {
            "count": 3,
            "enabled": True,
            "ratio": 1.25,
            "missing": None,
            "nested": {"attempt": 2, "diagnostic": "not public"},
        },
    )

    assert error.details == {
        "count": 3,
        "enabled": True,
        "ratio": 1.25,
        "missing": None,
        "nested": {"attempt": 2, "diagnostic": "[REDACTED]"},
    }


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected_before_connect():
    client = _client()
    client.connect = AsyncMock()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("execute_python", {})

    assert exc_info.value.code == "ARCPY_TOOL_NOT_ALLOWED"
    client.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_train_deep_learning_model_is_rejected_before_connect():
    client = _client()
    client.connect = AsyncMock()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("TrainDeepLearningModel", {})

    assert exc_info.value.code == "ARCPY_TOOL_NOT_ALLOWED"
    client.connect.assert_not_awaited()


def test_allowlist_matches_private_service_contract_exactly():
    assert ArcPyMcpClient.allowed_tools == frozenset(
        {
            "health_check",
            "get_capabilities",
            "create_upload",
            "get_upload_status",
            "renew_upload",
            "complete_upload",
            "list_artifacts",
            "delete_artifact",
            "inspect_dataset",
            "get_job",
            "list_jobs",
            "cancel_job",
            "get_job_log",
            "create_download",
            "search_tools",
            "describe_tool",
            "submit_job",
            "buffer_features",
            "clip_features",
            "clip_raster",
            "dissolve_features",
            "intersect_features",
            "spatial_join",
            "project_features",
            "project_raster",
            "check_geometry",
            "repair_geometry",
            "calculate_slope",
            "zonal_statistics",
            "export_map_layout",
            "detect_objects",
            "classify_pixels",
            "classify_objects",
            "detect_change",
        }
    )


@pytest.mark.asyncio
async def test_call_tool_returns_a_copy_of_structured_content():
    payload = {"status": "ok", "nested": {"count": 1}}
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(structured=payload))
    )

    returned = await client.call_tool("get_job", {"job_id": "job-1"})

    assert returned == payload
    assert returned is not payload


@pytest.mark.asyncio
async def test_call_tool_supports_snake_case_sdk_result_attributes():
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=_result(structured={"status": "ok"}, snake_case=True)
        )
    )

    assert await client.call_tool("get_job", {}) == {"status": "ok"}


@pytest.mark.asyncio
async def test_call_tool_parses_text_json_object_fallback():
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(text='{"status": "ok"}'))
    )

    assert await client.call_tool("get_job", {}) == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        _result(text="not json"),
        _result(text="[]"),
        _result(structured=["not", "an", "object"]),
        _result(),
    ],
)
async def test_call_tool_rejects_invalid_or_non_object_response(result):
    client = _client()
    client._session = SimpleNamespace(call_tool=AsyncMock(return_value=result))

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("get_job", {})

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"
    assert "JSONDecodeError" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_call_tool_maps_transport_failure_without_exception_chain_secrets():
    credential = "fixture-runtime-credential"
    signed_value = "fixture-signed-value"
    client = _client()
    client._resolved_token = credential
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=RuntimeError(
                "Authorization: Bearer "
                f"{credential}; https://download.example/item?signature={signed_value}"
            )
        )
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("get_capabilities", {})

    error = exc_info.value
    assert error.code == "ARCPY_MCP_UNREACHABLE"
    assert str(error) == "ArcPy MCP service is unreachable"
    assert credential not in str(error)
    assert signed_value not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.asyncio
async def test_call_tool_maps_sanitized_result_error():
    credential = "fixture-runtime-credential"
    signed_value = "fixture-signed-value"
    client = _client()
    client._resolved_token = credential
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=_result(
                error=True,
                text=(
                    "Authorization: Bearer "
                    f"{credential}; https://download.example/item?sig={signed_value}"
                ),
            )
        )
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.call_tool("submit_job", {})

    assert exc_info.value.code == "ARCPY_JOB_FAILED"
    assert str(exc_info.value) == "ArcPy MCP tool reported a failure"
    assert credential not in str(exc_info.value)
    assert signed_value not in repr(exc_info.value)


class FakeContext:
    def __init__(self, name, value, events):
        self.name = name
        self.value = value
        self.events = events
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        self.events.append(f"enter:{self.name}")
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_count += 1
        self.events.append(f"exit:{self.name}")


class TaskAffineContext(FakeContext):
    def __init__(self, name, value, events):
        super().__init__(name, value, events)
        self.enter_task = None
        self.affinity_violation = False

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return await super().__aenter__()

    async def __aexit__(self, exc_type, exc, traceback):
        if asyncio.current_task() is not self.enter_task:
            self.affinity_violation = True
            raise RuntimeError("context exited from a different task")
        await super().__aexit__(exc_type, exc, traceback)


class SensitiveFailingExitContext(TaskAffineContext):
    def __init__(self, name, value, events, message):
        super().__init__(name, value, events)
        self.message = message

    async def __aexit__(self, exc_type, exc, traceback):
        await super().__aexit__(exc_type, exc, traceback)
        raise RuntimeError(self.message)


class BlockingExitContext(TaskAffineContext):
    def __init__(self, name, value, events, exit_started, release_exit):
        super().__init__(name, value, events)
        self.exit_started = exit_started
        self.release_exit = release_exit

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_started.set()
        await asyncio.to_thread(self.release_exit.wait)
        await super().__aexit__(exc_type, exc, traceback)


class AnyioTaskGroupContext:
    def __init__(self, value, exited):
        self.value = value
        self.exited = exited
        self.task_group = None

    async def __aenter__(self):
        self.task_group = anyio.create_task_group()
        await self.task_group.__aenter__()
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        await self.task_group.__aexit__(exc_type, exc, traceback)
        self.exited.set()


class FakeSdkSession:
    def __init__(self, events, *, initialize_error=None, call_result=None):
        self.events = events
        self.initialize_error = initialize_error
        self.call_result = call_result or _result(structured={"status": "ok"})
        self.initialize_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.events.append("enter:session")
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_count += 1
        self.events.append("exit:session")

    async def initialize(self):
        self.initialize_count += 1
        self.events.append("initialize")
        if self.initialize_error:
            raise self.initialize_error

    async def call_tool(self, name, arguments):
        return self.call_result


def _install_fake_sdk(monkeypatch, sessions):
    import data_agent.arcpy_mcp_client as client_module

    events = sessions[0].events
    http_contexts = []
    transport_contexts = []

    def make_http_client(**kwargs):
        context = TaskAffineContext("http", object(), events)
        http_contexts.append(context)
        return context

    def make_transport(url, *, http_client, terminate_on_close=True):
        context = TaskAffineContext(
            "transport", ("read", "write", lambda: "session-id"), events
        )
        transport_contexts.append(context)
        return context

    http_factory = MagicMock(side_effect=make_http_client)
    transport_factory = MagicMock(side_effect=make_transport)
    session_factory = MagicMock(side_effect=sessions)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", http_factory)
    monkeypatch.setattr(client_module, "streamable_http_client", transport_factory)
    monkeypatch.setattr(client_module, "ClientSession", session_factory)
    return SimpleNamespace(
        events=events,
        http_factory=http_factory,
        http_contexts=http_contexts,
        transport_factory=transport_factory,
        transport_contexts=transport_contexts,
        session_factory=session_factory,
    )


def _install_blocking_exit_sdk(monkeypatch):
    import data_agent.arcpy_mcp_client as client_module

    events = []
    exit_started = threading.Event()
    release_exit = threading.Event()
    sessions = [FakeSdkSession(events), FakeSdkSession(events)]
    http_contexts = []
    transport_contexts = []

    def make_http_client(**kwargs):
        context = FakeContext("http", object(), events)
        http_contexts.append(context)
        return context

    def make_transport(url, *, http_client, terminate_on_close=True):
        value = ("read", "write", lambda: None)
        if not transport_contexts:
            context = BlockingExitContext(
                "transport", value, events, exit_started, release_exit
            )
        else:
            context = FakeContext("transport", value, events)
        transport_contexts.append(context)
        return context

    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        MagicMock(side_effect=make_http_client),
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(side_effect=make_transport),
    )
    monkeypatch.setattr(
        client_module,
        "ClientSession",
        MagicMock(side_effect=sessions),
    )
    return SimpleNamespace(
        events=events,
        exit_started=exit_started,
        release_exit=release_exit,
        sessions=sessions,
        http_contexts=http_contexts,
        transport_contexts=transport_contexts,
    )


async def _cancel_and_consume(task):
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


@pytest.mark.asyncio
async def test_connect_builds_one_authenticated_official_session_and_initializes(
    monkeypatch,
):
    from data_agent.mcp_transport import current_runtime_secrets

    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    sdk.events = events
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-connect-credential")
    config = McpServerConfig(
        name="arcpy",
        url="https://service.example/mcp",
        timeout=7,
        bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
    )
    client = ArcPyMcpClient(config)

    await client.connect()
    await client.connect()

    sdk.http_factory.assert_called_once_with(
        headers={"Authorization": "Bearer fixture-connect-credential"},
        timeout=7,
        follow_redirects=True,
    )
    sdk.transport_factory.assert_called_once()
    assert sdk.transport_factory.call_args.kwargs["http_client"] is not None
    assert sdk.session_factory.call_count == 1
    assert session.initialize_count == 1
    assert client._session is session
    assert current_runtime_secrets() == ("fixture-connect-credential",)

    await client.close()
    assert current_runtime_secrets() == ()


@pytest.mark.asyncio
async def test_session_contexts_exit_in_the_same_owner_task(monkeypatch):
    import data_agent.arcpy_mcp_client as client_module

    events = []
    http_context = TaskAffineContext("http", object(), events)
    transport_context = TaskAffineContext(
        "transport", ("read", "write", lambda: None), events
    )
    session = FakeSdkSession(events)
    session_context = TaskAffineContext("session", session, events)
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        MagicMock(return_value=http_context),
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(return_value=transport_context),
    )
    monkeypatch.setattr(
        client_module,
        "ClientSession",
        MagicMock(return_value=session_context),
    )
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-affinity-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    await client.connect()
    close_task = asyncio.create_task(client.close())
    await close_task

    assert http_context.affinity_violation is False
    assert transport_context.affinity_violation is False
    assert session_context.affinity_violation is False
    assert http_context.exit_count == 1
    assert transport_context.exit_count == 1
    assert session_context.exit_count == 1


@pytest.mark.asyncio
async def test_close_maps_sensitive_owner_cleanup_failure_and_remains_idempotent(
    monkeypatch,
):
    import data_agent.arcpy_mcp_client as client_module
    from data_agent.mcp_transport import current_runtime_secrets

    credential = "fixture-cleanup-runtime-credential"
    private_url = "https://10.1.2.3/private/service"
    ca_path = "/private/ca bundles/root.pem"
    events = []
    http_context = TaskAffineContext("http", object(), events)
    transport_context = SensitiveFailingExitContext(
        "transport",
        ("read", "write", lambda: None),
        events,
        f"Authorization: Bearer {credential} {private_url} {ca_path}",
    )
    session = FakeSdkSession(events)
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        MagicMock(return_value=http_context),
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(return_value=transport_context),
    )
    monkeypatch.setattr(
        client_module,
        "ClientSession",
        MagicMock(return_value=session),
    )
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", credential)
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.close()

    error = exc_info.value
    assert error.code == "ARCPY_MCP_UNREACHABLE"
    assert str(error) == "ArcPy MCP service is unreachable"
    assert credential not in repr(error)
    assert private_url not in repr(error)
    assert ca_path not in repr(error)
    assert current_runtime_secrets() == ()
    assert client._session is None
    assert client._stack is None
    await client.close()


@pytest.mark.asyncio
async def test_close_from_foreign_running_owner_loop(monkeypatch):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-running-loop-credential")
    owner_loop = asyncio.new_event_loop()
    loop_started = threading.Event()

    def run_loop():
        asyncio.set_event_loop(owner_loop)
        loop_started.set()
        owner_loop.run_forever()

    thread = threading.Thread(target=run_loop)
    thread.start()
    loop_started.wait()
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    connect_future = asyncio.run_coroutine_threadsafe(client.connect(), owner_loop)
    await asyncio.to_thread(connect_future.result, 2)
    owner = client._owner_task

    try:
        await client.close()
        assert owner.done()
        assert all(not context.affinity_violation for context in sdk.http_contexts)
        assert all(
            not context.affinity_violation for context in sdk.transport_contexts
        )
    finally:
        if not owner.done():
            cleanup = asyncio.run_coroutine_threadsafe(
                _cancel_and_consume(owner), owner_loop
            )
            await asyncio.to_thread(cleanup.result, 2)
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        await asyncio.to_thread(thread.join, 2)
        assert not thread.is_alive()
        owner_loop.close()


@pytest.mark.asyncio
async def test_close_from_foreign_stopped_owner_loop(monkeypatch):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-stopped-loop-credential")
    owner_loop = asyncio.new_event_loop()
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    setup_errors = []

    def connect_then_stop():
        asyncio.set_event_loop(owner_loop)
        try:
            owner_loop.run_until_complete(client.connect())
        except BaseException as exc:
            setup_errors.append(exc)

    setup_thread = threading.Thread(target=connect_then_stop)
    setup_thread.start()
    await asyncio.to_thread(setup_thread.join, 2)
    assert not setup_thread.is_alive()
    assert setup_errors == []
    owner = client._owner_task

    try:
        await client.close()
        assert owner.done()
        assert all(not context.affinity_violation for context in sdk.http_contexts)
        assert all(
            not context.affinity_violation for context in sdk.transport_contexts
        )
    finally:
        if not owner.done():
            await asyncio.to_thread(
                owner_loop.run_until_complete,
                _cancel_and_consume(owner),
            )
        owner_loop.close()


@pytest.mark.asyncio
async def test_close_with_closed_owner_loop_is_sanitized_and_warning_free(
    monkeypatch, caplog, recwarn
):
    from data_agent.mcp_transport import current_runtime_secrets

    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    credential = "fixture-closed-loop-credential"
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", credential)
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    setup_errors = []

    def connect_then_close_caller_loop():
        try:
            asyncio.run(client.connect())
        except BaseException as exc:
            setup_errors.append(exc)

    setup_thread = threading.Thread(target=connect_then_close_caller_loop)
    setup_thread.start()
    await asyncio.to_thread(setup_thread.join, 2)
    assert not setup_thread.is_alive()
    assert setup_errors == []

    with caplog.at_level("WARNING", logger="data_agent.arcpy_mcp_client"):
        await client.close()
    gc.collect()

    assert current_runtime_secrets() == ()
    assert client._owner_task is None
    assert client._owner_loop is None
    assert client._worker_thread is None
    assert client._worker_loop is None
    assert client._session is None
    assert client._resolved_token is None
    assert all(not context.affinity_violation for context in sdk.http_contexts)
    assert all(not context.affinity_violation for context in sdk.transport_contexts)
    assert not any("Task was destroyed" in record.message for record in caplog.records)
    assert not any("coroutine" in str(warning.message) for warning in recwarn)


@pytest.mark.asyncio
async def test_dedicated_owner_survives_caller_loop_close_until_explicit_close(
    monkeypatch, recwarn
):
    import data_agent.arcpy_mcp_client as client_module
    from data_agent.mcp_transport import current_runtime_secrets

    credential = "fixture-dedicated-anyio-credential"
    exits = [threading.Event() for _ in range(3)]
    session = FakeSdkSession([])
    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        MagicMock(return_value=AnyioTaskGroupContext(object(), exits[0])),
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(
            return_value=AnyioTaskGroupContext(
                ("read", "write", lambda: None), exits[1]
            )
        ),
    )
    monkeypatch.setattr(
        client_module,
        "ClientSession",
        MagicMock(return_value=AnyioTaskGroupContext(session, exits[2])),
    )
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", credential)
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    caller_errors = []

    def use_client_then_close_caller_loop():
        async def use_client():
            await client.connect()
            assert await client.call_tool("get_job", {}) == {"status": "ok"}

        try:
            asyncio.run(use_client())
        except BaseException as exc:
            caller_errors.append(exc)

    caller = threading.Thread(target=use_client_then_close_caller_loop)
    caller.start()
    await asyncio.to_thread(caller.join, 2)
    assert not caller.is_alive()
    assert caller_errors == []
    exited_before_explicit_close = [event.is_set() for event in exits]

    await client.close()
    gc.collect()

    assert exited_before_explicit_close == [False, False, False]
    assert [event.is_set() for event in exits] == [True, True, True]
    assert current_runtime_secrets() == ()
    assert not any("coroutine" in str(warning.message) for warning in recwarn)


@pytest.mark.asyncio
async def test_close_during_worker_loop_publication_requests_stop(monkeypatch):
    import data_agent.arcpy_mcp_client as client_module

    original_new_event_loop = client_module.asyncio.new_event_loop
    publication_started = threading.Event()
    release_publication = threading.Event()

    def delayed_new_event_loop():
        publication_started.set()
        release_publication.wait()
        return original_new_event_loop()

    monkeypatch.setattr(
        client_module.asyncio, "new_event_loop", delayed_new_event_loop
    )
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(structured={"status": "ok"}))
    )
    connect_task = asyncio.create_task(client.connect())
    await asyncio.to_thread(publication_started.wait)
    close_task = asyncio.create_task(client.close())
    await asyncio.sleep(0)
    stop_requested = getattr(client, "_worker_stop_requested", None)

    if stop_requested is None:
        startup_handshake = client._worker_started
        release_publication.set()
        assert await asyncio.to_thread(startup_handshake.wait, 2)
        if client._worker_loop is not None:
            client._request_worker_stop(client._worker_loop)
    else:
        assert await asyncio.to_thread(stop_requested.wait, 2)
        release_publication.set()

    close_error = None
    try:
        await asyncio.wait_for(close_task, timeout=2.0)
    except BaseException as exc:
        close_error = exc
    connect_result = await asyncio.gather(connect_task, return_exceptions=True)

    assert stop_requested is not None
    assert close_error is None
    assert isinstance(connect_result[0], ArcPyMcpError)
    assert connect_result[0].code == "ARCPY_MCP_UNREACHABLE"
    assert client._worker_thread is None
    assert client._worker_loop is None


@pytest.mark.asyncio
async def test_worker_thread_start_failure_is_recoverable(monkeypatch):
    original_start = threading.Thread.start
    failed = False

    def fail_arcpy_worker_once(thread):
        nonlocal failed
        if thread.name == "arcpy-mcp-worker" and not failed:
            failed = True
            raise RuntimeError("synthetic worker start failure")
        return original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_arcpy_worker_once)
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(structured={"status": "ok"}))
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.connect()
    close_error = None
    try:
        await client.close()
        await client.close()
    except BaseException as exc:
        close_error = exc
    monkeypatch.setattr(threading.Thread, "start", original_start)

    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    assert close_error is None
    assert client._worker_thread is None
    assert client._worker_loop is None
    assert client._worker_started is None

    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(structured={"status": "ok"}))
    )
    await client.connect()
    await client.close()


@pytest.mark.asyncio
async def test_health_recovers_on_new_caller_loop_after_old_loop_cancellation(
    monkeypatch,
):
    started = threading.Event()
    release = threading.Event()
    call_count = 0

    class BlockingHealthSession(FakeSdkSession):
        async def call_tool(self, name, arguments):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                started.set()
                await asyncio.to_thread(release.wait)
            return _result(structured={"status": "healthy", "worker": {}})

    sessions = [BlockingHealthSession([]), FakeSdkSession([])]
    _install_fake_sdk(monkeypatch, sessions)
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-loop-cache-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    caller_errors = []

    def cancel_health_then_close_caller_loop():
        async def cancel_health():
            tasks = [asyncio.create_task(client.health_check()) for _ in range(12)]
            await asyncio.to_thread(started.wait)
            for task in tasks:
                task.cancel()
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            asyncio.run(cancel_health())
        except BaseException as exc:
            caller_errors.append(exc)

    caller = threading.Thread(target=cancel_health_then_close_caller_loop)
    caller.start()
    await asyncio.to_thread(caller.join, 2)
    assert not caller.is_alive()
    assert caller_errors == []

    result = await asyncio.wait_for(client.health_check(), timeout=2.0)

    assert result["status"] == "healthy"
    assert 1 <= call_count <= 2
    await client.close()
    assert client._worker_thread is None
    assert client._worker_loop is None


@pytest.mark.asyncio
async def test_call_during_owner_cleanup_is_rejected_then_retry_uses_new_owner(
    monkeypatch,
):
    sdk = _install_blocking_exit_sdk(monkeypatch)
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-generation-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()
    first_owner = client._owner_task
    first_worker = client._worker_thread
    owner_done = threading.Event()
    client._worker_loop.call_soon_threadsafe(
        first_owner.add_done_callback,
        lambda task: owner_done.set(),
    )
    client._worker_loop.call_soon_threadsafe(
        client._commands.put_nowait, ("shutdown",)
    )
    await asyncio.to_thread(sdk.exit_started.wait)

    retry_during_cleanup = asyncio.create_task(client.call_tool("get_job", {}))
    with pytest.raises(ArcPyMcpError) as exc_info:
        await asyncio.wait_for(retry_during_cleanup, timeout=2.0)

    sdk.release_exit.set()
    await asyncio.to_thread(owner_done.wait)
    await asyncio.to_thread(first_worker.join)
    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    result = await client.call_tool("get_job", {})
    assert result == {"status": "ok"}
    assert client._owner_task is not first_owner
    await client.close()


@pytest.mark.asyncio
async def test_cancelled_close_waiter_recovers_after_owner_finishes(monkeypatch):
    sdk = _install_blocking_exit_sdk(monkeypatch)
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-close-caller-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()
    owner = client._owner_task
    worker = client._worker_thread
    close_task = asyncio.create_task(client.close())
    await asyncio.to_thread(sdk.exit_started.wait)
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert client._closing is True
    sdk.release_exit.set()
    await asyncio.to_thread(worker.join)

    assert client._closing is False
    assert client._owner_task is None
    await client.connect()
    await client.close()


@pytest.mark.asyncio
async def test_secret_file_precedence_and_ca_factory_are_wired(
    monkeypatch, tmp_path
):
    import data_agent.arcpy_mcp_client as client_module

    events = []
    session = FakeSdkSession(events)
    http_context = FakeContext("http", object(), events)
    client_factory = MagicMock(return_value=http_context)
    ca_factory_builder = MagicMock(return_value=client_factory)
    monkeypatch.setattr(
        client_module, "build_httpx_client_factory", ca_factory_builder
    )
    transport_context = FakeContext(
        "transport", ("read", "write", lambda: None), events
    )
    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        MagicMock(return_value=transport_context),
    )
    monkeypatch.setattr(
        client_module, "ClientSession", MagicMock(return_value=session)
    )
    token_file = tmp_path / "credential"
    token_file.write_text("fixture-file-credential\n", encoding="utf-8")
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text(
        "-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-env-credential")
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("ARCPY_CLIENT_TEST_CA", str(ca_file))
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
            bearer_token_file_env_var="ARCPY_CLIENT_TEST_TOKEN_FILE",
            ca_bundle_env_var="ARCPY_CLIENT_TEST_CA",
        )
    )

    await client.connect()

    ca_factory_builder.assert_called_once_with(str(ca_file))
    client_factory.assert_called_once_with(
        headers={"Authorization": "Bearer fixture-file-credential"},
        timeout=5.0,
    )
    assert "fixture-env-credential" not in repr(client)
    assert "fixture-file-credential" not in repr(client)
    assert str(ca_file) not in repr(client)
    await client.close()


@pytest.mark.asyncio
async def test_close_exits_all_contexts_in_reverse_order_and_is_idempotent(
    monkeypatch,
):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    sdk.events = events
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-close-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )
    await client.connect()

    await client.close()
    await client.close()

    assert session.exit_count == 1
    assert sdk.transport_contexts[0].exit_count == 1
    assert sdk.http_contexts[0].exit_count == 1
    assert events[-3:] == ["exit:session", "exit:transport", "exit:http"]
    assert client._session is None
    assert client._resolved_token is None
    assert client._stack is None


@pytest.mark.asyncio
async def test_half_connect_failure_cleans_up_and_allows_retry(monkeypatch):
    from data_agent.mcp_transport import current_runtime_secrets

    first_events = []
    second_events = []
    first_session = FakeSdkSession(
        first_events,
        initialize_error=RuntimeError(
            "Authorization: Bearer fixture-failed-connect-credential"
        ),
    )
    second_session = FakeSdkSession(second_events)
    sdk = _install_fake_sdk(monkeypatch, [first_session, second_session])
    monkeypatch.setenv(
        "ARCPY_CLIENT_TEST_TOKEN", "fixture-failed-connect-credential"
    )
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.connect()

    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    assert "fixture-failed-connect-credential" not in repr(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert first_session.exit_count == 1
    assert sdk.transport_contexts[0].exit_count == 1
    assert sdk.http_contexts[0].exit_count == 1
    assert client._session is None
    assert client._resolved_token is None
    assert client._stack is None
    assert current_runtime_secrets() == ()

    await client.connect()
    assert client._session is second_session
    assert second_session.initialize_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_cancelled_connect_caller_does_not_cancel_session_owner(monkeypatch):
    from data_agent.mcp_transport import current_runtime_secrets

    initialize_started = threading.Event()
    release_initialize = threading.Event()

    class BlockingInitializeSession(FakeSdkSession):
        async def initialize(self):
            self.initialize_count += 1
            initialize_started.set()
            await asyncio.to_thread(release_initialize.wait)

    session = BlockingInitializeSession([])
    sdk = _install_fake_sdk(monkeypatch, [session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-cancel-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    connect_task = asyncio.create_task(client.connect())
    await asyncio.to_thread(initialize_started.wait)
    connect_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect_task

    assert session.exit_count == 0
    assert sdk.transport_contexts[0].exit_count == 0
    assert sdk.http_contexts[0].exit_count == 0
    assert current_runtime_secrets() == ("fixture-cancel-credential",)

    release_initialize.set()
    await client.connect()
    assert client._session is session
    await client.close()
    assert session.exit_count == 1
    assert current_runtime_secrets() == ()


@pytest.mark.asyncio
async def test_owner_cancelled_before_start_resolves_connect_waiter():
    client = _client()
    connect_task = asyncio.create_task(client.connect())
    connect_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await connect_task

    client._session = SimpleNamespace(
        call_tool=AsyncMock(return_value=_result(structured={"status": "ok"}))
    )
    await asyncio.wait_for(client.connect(), timeout=2.0)
    assert client._owner_task is not None
    await client.close()



@pytest.mark.asyncio
async def test_concurrent_connect_creates_a_single_session(monkeypatch):
    events = []
    session = FakeSdkSession(events)
    sdk = _install_fake_sdk(monkeypatch, [session])
    monkeypatch.setenv("ARCPY_CLIENT_TEST_TOKEN", "fixture-concurrent-credential")
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    await asyncio.gather(*(client.connect() for _ in range(8)))

    assert sdk.http_factory.call_count == 1
    assert sdk.transport_factory.call_count == 1
    assert sdk.session_factory.call_count == 1
    assert session.initialize_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_missing_url_and_credentials_have_stable_configuration_errors(
    monkeypatch,
):
    monkeypatch.delenv("ARCPY_CLIENT_TEST_TOKEN", raising=False)
    no_url = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy", bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN"
        )
    )
    no_credential = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            bearer_token_env_var="ARCPY_CLIENT_TEST_TOKEN",
        )
    )

    with pytest.raises(ArcPyMcpError) as url_error:
        await no_url.connect()
    with pytest.raises(ArcPyMcpError) as credential_error:
        await no_credential.connect()

    assert url_error.value.code == "ARCPY_MCP_URL_MISSING"
    assert credential_error.value.code == "ARCPY_MCP_TOKEN_MISSING"


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.mark.asyncio
async def test_close_cancels_an_owned_call_without_deadlock():
    started = threading.Event()
    release = threading.Event()

    class BlockingSession:
        async def call_tool(self, name, arguments):
            started.set()
            while not release.is_set():
                await asyncio.sleep(0)
            return _result(structured={"status": "ok"})

    client = _client()
    client._session = BlockingSession()
    call_task = asyncio.create_task(client.call_tool("get_job", {}))
    await asyncio.to_thread(started.wait)
    close_task = asyncio.create_task(client.close())
    try:
        await asyncio.wait_for(close_task, timeout=2.0)
    except asyncio.TimeoutError:
        release.set()
        await close_task
        raise

    with pytest.raises(ArcPyMcpError) as exc_info:
        await call_task
    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    assert client._session is None


@pytest.mark.asyncio
async def test_cancelled_call_waiter_does_not_cancel_owner_or_next_call():
    first_started = threading.Event()
    release_first = threading.Event()
    first_completed = threading.Event()

    class RecordingSession:
        def __init__(self):
            self.call_tasks = []
            self.call_count = 0

        async def call_tool(self, name, arguments):
            self.call_tasks.append(asyncio.current_task())
            self.call_count += 1
            if self.call_count == 1:
                first_started.set()
                await asyncio.to_thread(release_first.wait)
                first_completed.set()
            return _result(structured={"call": self.call_count})

    session = RecordingSession()
    client = _client()
    client._session = session
    first_call = asyncio.create_task(client.call_tool("get_job", {}))
    await asyncio.to_thread(first_started.wait)
    first_call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_call

    release_first.set()
    await asyncio.to_thread(first_completed.wait)
    second = await client.call_tool("get_job", {})

    assert second == {"call": 2}
    assert session.call_tasks == [client._owner_task, client._owner_task]
    await client.close()


@pytest.mark.asyncio
async def test_cancelled_queued_call_is_not_invoked_remotely():
    first_started = threading.Event()
    release_first = threading.Event()

    class RecordingSession:
        def __init__(self):
            self.names = []

        async def call_tool(self, name, arguments):
            self.names.append(name)
            if len(self.names) == 1:
                first_started.set()
                await asyncio.to_thread(release_first.wait)
            return _result(structured={"name": name})

    session = RecordingSession()
    client = _client()
    client._session = session
    first_call = asyncio.create_task(client.call_tool("get_job", {}))
    await asyncio.to_thread(first_started.wait)
    queued_call = asyncio.create_task(client.call_tool("submit_job", {}))
    for _ in range(10):
        if client._commands.qsize() == 1:
            break
        await asyncio.sleep(0)
    assert client._commands.qsize() == 1

    queued_call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued_call
    release_first.set()
    assert await first_call == {"name": "get_job"}
    for _ in range(10):
        await asyncio.sleep(0)

    assert session.names == ["get_job"]
    await client.close()


@pytest.mark.asyncio
async def test_health_check_requires_healthy_status_and_worker_dict():
    invalid_results = [
        {"status": "degraded", "worker": {"detail": "private-host"}},
        {"status": "healthy"},
        {"status": "healthy", "worker": "not-an-object"},
    ]
    for payload in invalid_results:
        client = _client()
        client._session = SimpleNamespace(
            call_tool=AsyncMock(return_value=_result(structured=payload))
        )

        with pytest.raises(ArcPyMcpError) as exc_info:
            await client.health_check()

        assert exc_info.value.code == "ARCPY_WORKER_UNAVAILABLE"
        assert str(exc_info.value) == "ArcPy worker is unavailable"
        assert "private-host" not in repr(exc_info.value)


@pytest.mark.asyncio
async def test_health_check_caches_only_success_for_thirty_seconds():
    clock = FakeClock()
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                _result(structured={"status": "unhealthy", "worker": {}}),
                _result(
                    structured={"status": "healthy", "worker": {"mode": "cpu"}}
                ),
                _result(
                    structured={
                        "status": "healthy",
                        "worker": {"mode": "cpu", "generation": 2},
                    }
                ),
            ]
        )
    )
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
    )
    client._session = session

    with pytest.raises(ArcPyMcpError):
        await client.health_check()
    first = await client.health_check()
    first["worker"]["mode"] = "mutated"
    clock.advance(29.9)
    cached = await client.health_check()
    clock.advance(0.1)
    refreshed = await client.health_check()

    assert cached["worker"]["mode"] == "cpu"
    assert refreshed["worker"]["generation"] == 2
    assert session.call_tool.await_count == 3


@pytest.mark.asyncio
async def test_health_transport_failure_is_not_cached():
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                RuntimeError("temporary transport failure"),
                _result(
                    structured={"status": "healthy", "worker": {"mode": "cpu"}}
                ),
            ]
        )
    )
    client = _client()
    client._session = session

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.health_check()
    result = await client.health_check()

    assert exc_info.value.code == "ARCPY_MCP_UNREACHABLE"
    assert result["status"] == "healthy"
    assert session.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_health_check_cold_cache_is_single_flight():
    calls = 0

    class HealthSession:
        async def call_tool(self, name, arguments):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return _result(structured={"status": "healthy", "worker": {}})

    client = _client()
    client._session = HealthSession()

    results = await asyncio.gather(*(client.health_check() for _ in range(12)))

    assert calls == 1
    assert all(result["status"] == "healthy" for result in results)


@pytest.mark.asyncio
async def test_health_result_after_close_does_not_repopulate_cache():
    started = threading.Event()

    class BlockingHealthSession:
        async def call_tool(self, name, arguments):
            started.set()
            while True:
                await asyncio.sleep(0)

    client = _client()
    client._session = BlockingHealthSession()
    health_task = asyncio.create_task(client.health_check())
    await asyncio.to_thread(started.wait)
    await client.close()

    with pytest.raises(ArcPyMcpError):
        await health_task
    assert client._health_cache is None


@pytest.mark.asyncio
async def test_capabilities_accepts_only_available_supported_extension():
    client = _client()
    client._session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=_result(
                structured={
                    "worker": {
                        "extensions": {
                            "Spatial": "Available",
                            "ImageAnalyst": "Unavailable",
                        }
                    }
                }
            )
        )
    )

    result = await client.get_capabilities("spatial analyst")
    with pytest.raises(ArcPyMcpError) as unavailable:
        await client.get_capabilities("image_analyst")
    with pytest.raises(ArcPyMcpError) as invalid:
        await client.get_capabilities("Network")

    assert result["worker"]["extensions"]["Spatial"] == "Available"
    assert unavailable.value.code == "ARCPY_EXTENSION_UNAVAILABLE"
    assert str(unavailable.value) == "Required ArcPy extension is unavailable"
    assert invalid.value.code == "ARCPY_INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_capabilities_cache_has_independent_thirty_second_ttl():
    clock = FakeClock()
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                _result(
                    structured={
                        "worker": {"extensions": {"Spatial": "Available"}},
                        "generation": 1,
                    }
                ),
                _result(
                    structured={
                        "worker": {"extensions": {"Spatial": "Available"}},
                        "generation": 2,
                    }
                ),
            ]
        )
    )
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
    )
    client._session = session

    first = await client.get_capabilities("Spatial")
    clock.advance(29.9)
    cached = await client.get_capabilities()
    clock.advance(0.1)
    refreshed = await client.get_capabilities("Spatial")

    assert first["generation"] == cached["generation"] == 1
    assert refreshed["generation"] == 2
    assert session.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_capabilities_cold_cache_is_single_flight():
    calls = 0

    class CapabilitiesSession:
        async def call_tool(self, name, arguments):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return _result(
                structured={"worker": {"extensions": {"Spatial": "Available"}}}
            )

    client = _client()
    client._session = CapabilitiesSession()

    results = await asyncio.gather(
        *(client.get_capabilities("Spatial") for _ in range(12))
    )

    assert calls == 1
    assert all(
        result["worker"]["extensions"]["Spatial"] == "Available"
        for result in results
    )


@pytest.mark.asyncio
async def test_capability_result_after_close_does_not_repopulate_cache():
    started = threading.Event()

    class BlockingCapabilitiesSession:
        async def call_tool(self, name, arguments):
            started.set()
            while True:
                await asyncio.sleep(0)

    client = _client()
    client._session = BlockingCapabilitiesSession()
    capability_task = asyncio.create_task(client.get_capabilities())
    await asyncio.to_thread(started.wait)
    await client.close()

    with pytest.raises(ArcPyMcpError):
        await capability_task
    assert client._capabilities_cache is None


@pytest.mark.asyncio
async def test_close_clears_health_and_capability_caches():
    session = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                _result(structured={"status": "healthy", "worker": {}}),
                _result(structured={"worker": {"extensions": {}}}),
                _result(structured={"status": "healthy", "worker": {}}),
                _result(structured={"worker": {"extensions": {}}}),
            ]
        )
    )
    client = _client()
    client._session = session
    await client.health_check()
    await client.get_capabilities()

    await client.close()
    client._session = session
    await client.health_check()
    await client.get_capabilities()

    assert session.call_tool.await_count == 4
