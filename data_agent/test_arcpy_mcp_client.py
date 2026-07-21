"""Tests for the private ArcPy MCP client."""

import asyncio
import gc
import hashlib
import logging
import os
import stat
import threading
import zipfile
from dataclasses import asdict, fields
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


def test_upload_dataclasses_keep_their_public_field_contracts():
    assert [field.name for field in fields(PreparedLocalUpload)] == [
        "upload_path",
        "source_path",
        "logical_name",
        "media_type",
        "size",
        "sha256",
        "delete_after_upload",
    ]
    assert [field.name for field in fields(UploadedArtifact)] == [
        "artifact_id",
        "artifact_path",
        "source_path",
        "local_package_path",
        "delete_local_package",
    ]


def _client() -> ArcPyMcpClient:
    return ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )


def _cleanup_prepared(prepared: PreparedLocalUpload) -> None:
    prepared._cleanup_local_package()
    prepared._close_lease()


def _fail_first_private_cleanup(
    monkeypatch, client_module, cleanup_operation
):
    original_cleanup_operation = getattr(
        client_module.os, cleanup_operation
    )
    state = {"failed": False}

    def fail_first_cleanup(path, *args, **kwargs):
        targets_entry = (
            cleanup_operation in {"stat", "unlink"}
            and path == "entry.zip"
            and kwargs.get("dir_fd") is not None
        )
        targets_directory = (
            cleanup_operation == "rmdir"
            and isinstance(path, str)
            and path.startswith(".arcpy-package-")
            and kwargs.get("dir_fd") is not None
        )
        if not state["failed"] and (targets_entry or targets_directory):
            state["failed"] = True
            raise OSError(f"forced cleanup {cleanup_operation} failure")
        return original_cleanup_operation(path, *args, **kwargs)

    monkeypatch.setattr(
        client_module.os, cleanup_operation, fail_first_cleanup
    )
    return state


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


@pytest.fixture
def symlinked_user_upload_root(tmp_path, monkeypatch):
    base = tmp_path / "uploads"
    victim_upload_dir = base / "victim"
    victim_upload_dir.mkdir(parents=True)
    attacker_upload_dir = base / "attacker"
    attacker_upload_dir.symlink_to(victim_upload_dir, target_is_directory=True)
    monkeypatch.setattr("data_agent.user_context._BASE_UPLOAD_DIR", str(base))
    monkeypatch.setattr("data_agent.gis_processors._BASE_UPLOAD_DIR", str(base))
    token = current_user_id.set("attacker")
    try:
        yield attacker_upload_dir, victim_upload_dir
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
    assert "_lease" not in repr(prepared)
    assert "_lease_init" not in repr(prepared)
    assert "_lease" not in asdict(prepared)
    assert "_lease_init" not in asdict(prepared)


def test_package_shapefile_includes_required_and_optional_sidecars(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        (user_upload_dir / f"roads{suffix}").write_bytes(suffix.encode())
    (user_upload_dir / "roads.shp.xml").write_bytes(b"metadata")
    (user_upload_dir / "other.dbf").write_bytes(b"ignore")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")

    assert prepared.upload_path.parent.parent == user_upload_dir
    assert prepared.upload_path.parent.name.startswith(".arcpy-package-")
    assert prepared.upload_path.name == "entry.zip"
    assert prepared.logical_name == "roads.zip"
    assert prepared.media_type == "application/zip"
    assert prepared.delete_after_upload is True
    with zipfile.ZipFile(prepared.upload_path) as archive:
        assert archive.namelist() == [
            "roads.cpg",
            "roads.dbf",
            "roads.prj",
            "roads.shp",
            "roads.shp.xml",
            "roads.shx",
        ]
    _cleanup_prepared(prepared)


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
    for suffix in (
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".atx",
        ".qix",
        ".xml",
    ):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"sidecar")
    (user_upload_dir / "roads.shp.xml").write_bytes(b"metadata")
    (user_upload_dir / "roads.secret").write_bytes(b"private")
    (user_upload_dir / "roads.backup.prj").write_bytes(b"backup")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")

    with zipfile.ZipFile(prepared.upload_path) as archive:
        assert archive.namelist() == [
            "roads.dbf",
            "roads.prj",
            "roads.shp",
            "roads.shp.xml",
            "roads.shx",
            "roads.xml",
        ]
    _cleanup_prepared(prepared)


def test_package_shapefile_includes_compound_field_atx_sidecars(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"core")
    (user_upload_dir / "roads.PARCEL_ID.atx").write_bytes(b"field-index")
    (user_upload_dir / "roads.backup.atx").write_bytes(b"backup-field-index")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")

    with zipfile.ZipFile(prepared.upload_path) as archive:
        assert archive.namelist() == [
            "roads.backup.atx",
            "roads.dbf",
            "roads.PARCEL_ID.atx",
            "roads.shp",
            "roads.shx",
        ]
    _cleanup_prepared(prepared)


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
    _cleanup_prepared(prepared)


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


def test_package_rejects_other_users_files_via_shared_upload_root(
    user_upload_dir,
):
    victim_upload_dir = user_upload_dir.parent / "victim"
    victim_upload_dir.mkdir()
    victim_file = victim_upload_dir / "secret.tif"
    victim_file.write_bytes(b"victim-private-data")

    for provided in (victim_file, Path("victim") / "secret.tif"):
        with pytest.raises(ArcPyMcpError) as exc_info:
            package_local_dataset(provided)

        assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


def test_package_rejects_regular_file_through_symlinked_user_upload_root(
    symlinked_user_upload_root,
):
    _, victim_upload_dir = symlinked_user_upload_root
    (victim_upload_dir / "secret.tif").write_bytes(b"victim-private-data")

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset("secret.tif")

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"


def test_package_does_not_create_archive_through_symlinked_user_upload_root(
    symlinked_user_upload_root,
):
    _, victim_upload_dir = symlinked_user_upload_root
    for suffix in (".shp", ".shx", ".dbf"):
        (victim_upload_dir / f"roads{suffix}").write_bytes(b"victim-data")

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset("roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_OUTSIDE_SANDBOX"
    assert list(victim_upload_dir.glob("arcpy-input-*.zip")) == []


def test_package_rejects_file_swapped_to_cross_user_symlink_before_hash(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    source = user_upload_dir / "source.tif"
    source.write_bytes(b"attacker-data")
    victim_upload_dir = user_upload_dir.parent / "victim"
    victim_upload_dir.mkdir()
    victim_file = victim_upload_dir / "secret.tif"
    victim_file.write_bytes(b"victim-private-data")
    original_pin_file = client_module._pin_current_user_file

    def swap_then_pin(path, tenant_fd, user_upload_dir):
        source.unlink()
        source.symlink_to(victim_file)
        return original_pin_file(path, tenant_fd, user_upload_dir)

    monkeypatch.setattr(
        client_module, "_pin_current_user_file", swap_then_pin
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(source)

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
    assert list(user_upload_dir.glob(".arcpy-package-*")) == []


@pytest.mark.parametrize("failure_stage", ["fdopen", "zip"])
@pytest.mark.parametrize("cleanup_operation", ["stat", "unlink", "rmdir"])
def test_packaging_error_retries_transient_private_cleanup_failure(
    user_upload_dir, monkeypatch, failure_stage, cleanup_operation
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    if failure_stage == "fdopen":
        original_fdopen = client_module.os.fdopen

        def fail_package_fdopen(descriptor, mode, *args, **kwargs):
            if mode == "w+b":
                raise OSError("forced package fdopen failure")
            return original_fdopen(descriptor, mode, *args, **kwargs)

        monkeypatch.setattr(client_module.os, "fdopen", fail_package_fdopen)
    else:

        class FailingZipFile:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                raise OSError("forced ZIP failure")

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(client_module.zipfile, "ZipFile", FailingZipFile)

    cleanup_state = _fail_first_private_cleanup(
        monkeypatch, client_module, cleanup_operation
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_PACKAGE_FAILED"
    assert cleanup_state["failed"] is True
    assert list(user_upload_dir.glob(".arcpy-package-*")) == []


@pytest.mark.parametrize(
    ("metadata_error", "expected_code"),
    [
        (
            ArcPyMcpError("ARCPY_INPUT_INVALID", "forced metadata failure"),
            "ARCPY_INPUT_INVALID",
        ),
        (OSError("forced metadata failure"), "ARCPY_INPUT_PACKAGE_FAILED"),
    ],
    ids=["arcpy-error", "os-error"],
)
@pytest.mark.parametrize("cleanup_operation", ["stat", "unlink", "rmdir"])
def test_metadata_error_retries_transient_private_cleanup_failure(
    user_upload_dir,
    monkeypatch,
    metadata_error,
    expected_code,
    cleanup_operation,
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    def fail_metadata(lease):
        raise metadata_error

    monkeypatch.setattr(
        client_module._PreparedUploadLease, "metadata", fail_metadata
    )
    cleanup_state = _fail_first_private_cleanup(
        monkeypatch, client_module, cleanup_operation
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == expected_code
    assert cleanup_state["failed"] is True
    assert list(user_upload_dir.glob(".arcpy-package-*")) == []


@pytest.mark.parametrize("cleanup_operation", ["unlink", "rmdir"])
def test_package_dup_error_retries_transient_prelease_cleanup_failure(
    user_upload_dir, monkeypatch, cleanup_operation
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    dup_failed = False

    def fail_package_dup(descriptor):
        nonlocal dup_failed
        dup_failed = True
        raise OSError("forced package dup failure")

    monkeypatch.setattr(client_module.os, "dup", fail_package_dup)
    cleanup_state = _fail_first_private_cleanup(
        monkeypatch, client_module, cleanup_operation
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_PACKAGE_FAILED"
    assert dup_failed is True
    assert cleanup_state["failed"] is True
    assert list(user_upload_dir.glob(".arcpy-package-*")) == []


def test_private_directory_open_error_retries_transient_rmdir_failure(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    original_open = client_module.os.open
    private_open_failed = False

    def fail_private_directory_open(path, flags, *args, **kwargs):
        nonlocal private_open_failed
        if isinstance(path, str) and path.startswith(".arcpy-package-"):
            private_open_failed = True
            raise OSError("forced private directory open failure")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(client_module.os, "open", fail_private_directory_open)
    cleanup_state = _fail_first_private_cleanup(
        monkeypatch, client_module, "rmdir"
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_PACKAGE_FAILED"
    assert private_open_failed is True
    assert cleanup_state["failed"] is True
    assert list(user_upload_dir.glob(".arcpy-package-*")) == []


def test_package_cleanup_uses_pinned_tenant_after_directory_replacement(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")
    original_new_package_file = client_module._new_package_file
    created_relative_paths = []
    original_dir = user_upload_dir.parent / "original-user-dir"

    def capture_new_package_file(expected_tenant_identity=None):
        result = original_new_package_file(expected_tenant_identity)
        package_path = result[0]
        created_relative_paths.append(
            package_path.relative_to(user_upload_dir)
        )
        return result

    class ReplacingZipFile:
        def __init__(self, package_stream, *args, **kwargs):
            package_stream.write(b"partial")
            user_upload_dir.rename(original_dir)
            user_upload_dir.mkdir()
            replacement_path = user_upload_dir / created_relative_paths[0]
            replacement_path.parent.mkdir(parents=True, mode=0o700)
            replacement_path.write_bytes(b"unrelated")

        def __enter__(self):
            raise OSError("zip failed")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        client_module, "_new_package_file", capture_new_package_file
    )
    monkeypatch.setattr(client_module.zipfile, "ZipFile", ReplacingZipFile)

    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_PACKAGE_FAILED"
    assert not (original_dir / created_relative_paths[0]).exists()
    assert not (original_dir / created_relative_paths[0]).parent.exists()
    assert (
        user_upload_dir / created_relative_paths[0]
    ).read_bytes() == b"unrelated"


def test_prepared_package_uses_exclusive_pinned_private_directory(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")
    private_dir = prepared.upload_path.parent
    private_stat = os.stat(private_dir, follow_symlinks=False)

    assert private_dir.parent == user_upload_dir
    assert private_dir.name.startswith(".arcpy-package-")
    assert prepared.upload_path.name == "entry.zip"
    assert stat.S_ISDIR(private_stat.st_mode)
    assert stat.S_IMODE(private_stat.st_mode) == 0o700
    assert private_stat.st_uid == os.geteuid()
    assert os.path.samestat(
        private_stat, os.fstat(prepared._lease._private_dir_fd)
    )
    assert prepared.upload_path.read_bytes().startswith(b"PK")

    _cleanup_prepared(prepared)
    assert not private_dir.exists()


def test_prepared_package_cleanup_removes_same_inode_metadata_change(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")
    prepared.upload_path.write_bytes(b"damaged-package")

    prepared._cleanup_local_package()
    prepared._close_lease()

    assert not prepared.upload_path.exists()


@pytest.mark.parametrize("failing_operation", ["stat", "unlink", "rmdir"])
def test_prepared_package_cleanup_retries_without_private_directory_orphan(
    user_upload_dir, monkeypatch, failing_operation
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")
    private_dir = prepared.upload_path.parent
    lease = prepared._lease
    original_operation = getattr(client_module.os, failing_operation)
    failed = False

    def fail_once(path, *args, **kwargs):
        nonlocal failed
        targets_entry = (
            failing_operation in {"stat", "unlink"}
            and path == prepared.upload_path.name
            and kwargs.get("dir_fd") == lease._private_dir_fd
        )
        targets_directory = (
            failing_operation == "rmdir"
            and path == private_dir.name
            and kwargs.get("dir_fd") == lease._tenant_fd
        )
        if not failed and (targets_entry or targets_directory):
            failed = True
            raise OSError(f"forced cleanup {failing_operation} failure")
        return original_operation(path, *args, **kwargs)

    monkeypatch.setattr(client_module.os, failing_operation, fail_once)

    prepared._cleanup_local_package()
    assert failed is True
    assert not private_dir.exists()

    prepared._cleanup_local_package()
    prepared._close_lease()
    assert not private_dir.exists()
    assert list(user_upload_dir.glob(".arcpy-package-*")) == []


def test_prepared_package_cleanup_uses_pinned_original_tenant(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")
    private_relative_path = prepared.upload_path.parent.relative_to(
        user_upload_dir
    )
    original_user_dir = user_upload_dir.parent / "original-user-dir"
    user_upload_dir.rename(original_user_dir)
    user_upload_dir.mkdir()
    replacement_private_dir = user_upload_dir / private_relative_path
    replacement_private_dir.mkdir(mode=0o700)
    replacement_path = replacement_private_dir / prepared.upload_path.name
    replacement_path.write_bytes(b"replacement-must-survive")

    prepared._cleanup_local_package()
    prepared._close_lease()

    assert not (original_user_dir / private_relative_path).exists()
    assert replacement_path.read_bytes() == b"replacement-must-survive"


def test_prepared_package_cleanup_and_close_are_idempotent_without_fd_leaks(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    prepared = package_local_dataset(user_upload_dir / "roads.shp")
    private_dir = prepared.upload_path.parent
    lease_fds = (
        prepared._lease._tenant_fd,
        prepared._lease._private_dir_fd,
        prepared._lease._file_fd,
    )

    prepared._cleanup_local_package()
    prepared._cleanup_local_package()
    prepared._close_lease()
    prepared._close_lease()

    assert not private_dir.exists()
    for descriptor in lease_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_package_lease_rejects_renamed_original_before_upload(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")
    original_write_package = client_module._write_package
    renamed_path = user_upload_dir / "renamed-original.zip"

    def write_then_replace(entries, expected_tenant_identity=None):
        result = original_write_package(entries, expected_tenant_identity)
        package_path = result[0] if isinstance(result, tuple) else result
        package_path.rename(renamed_path)
        package_path.write_bytes(b"not-a-zip")
        return result

    monkeypatch.setattr(client_module, "_write_package", write_then_replace)
    with pytest.raises(ArcPyMcpError) as exc_info:
        package_local_dataset(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_INPUT_INVALID"
    assert renamed_path.exists()
    replacement_paths = list(
        user_upload_dir.glob(".arcpy-package-*/entry.zip")
    )
    assert len(replacement_paths) == 1
    assert replacement_paths[0].read_bytes() == b"not-a-zip"


@pytest.mark.asyncio
async def test_upload_rejects_hardlink_tamper_with_restored_mtime(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir, payload=b"original-data")
    hardlink = user_upload_dir / "hardlink.gpkg"
    os.link(prepared.upload_path, hardlink)
    original_stat = os.stat(hardlink)
    prepared.upload_path.unlink()
    hardlink.write_bytes(b"tampered-data")
    os.utime(
        hardlink,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    http_calls = []
    client = _upload_client([FakeUploadResponse()], [], http_calls)

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
    try:
        with pytest.raises(ArcPyMcpError) as exc_info:
            await client._upload_prepared(prepared)
        assert exc_info.value.code == "ARCPY_INPUT_INVALID"
        assert http_calls == []
    finally:
        hardlink.unlink()


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
        body = b"".join([chunk async for chunk in content])
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
        "https://bad host/upload",
        "https://./upload",
        "https://256.256.256.256/upload",
    ],
)
def test_signed_upload_url_requires_https_host_without_userinfo(signed_url):
    with pytest.raises(ArcPyMcpError) as exc_info:
        ArcPyMcpClient._signed_url({"upload_url": signed_url})

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"
    assert signed_url not in str(exc_info.value)
    assert signed_url not in repr(exc_info.value.details)


@pytest.mark.parametrize(
    "signed_url",
    [
        "https://signed.example/upload",
        "https://127.0.0.1/upload",
        "https://[2001:db8::1]/upload",
    ],
)
def test_signed_upload_url_accepts_valid_dns_and_ip_hosts(signed_url):
    assert ArcPyMcpClient._signed_url({"upload_url": signed_url}) == signed_url


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
    assert factory_calls == [{"follow_redirects": False}]
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
async def test_upload_real_httpx_async_stream_resumes_without_mcp_authorization(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    requests = []

    async def handler(request):
        body = await request.aread()
        upload_offset = request.headers.get("Upload-Offset")
        authorization = request.headers.get("Authorization")
        assert authorization is None
        assert all(
            not value.casefold().startswith("bearer ")
            for value in request.headers.values()
        )
        requests.append((upload_offset, body))
        if len(requests) == 1:
            assert upload_offset == "0"
            assert body == b"0123456789"
            raise httpx.ReadError("interrupted", request=request)
        assert upload_offset == "4"
        assert body == b"456789"
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(handler)

    def signed_http_client_factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            headers={"Authorization": "Bearer fixture-mcp-credential"},
        ),
        signed_http_client_factory=signed_http_client_factory,
    )
    tool_calls = []

    async def call_tool(name, arguments):
        tool_calls.append((name, arguments))
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "get_upload_status":
            return {"artifact_id": "artifact-1", "committed_size": 4}
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
    assert requests == [("0", b"0123456789"), ("4", b"456789")]
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
        ("get_upload_status", {"artifact_id": "artifact-1"}),
        ("complete_upload", {"artifact_id": "artifact-1"}),
    ]


@pytest.mark.asyncio
async def test_upload_replays_async_stream_across_temporary_redirect(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    requests = []

    class RedirectTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            body = b"".join([chunk async for chunk in request.stream])
            requests.append((str(request.url), body))
            if len(requests) == 1:
                return httpx.Response(
                    307,
                    headers={"Location": "https://storage.example/upload"},
                    request=request,
                )
            return httpx.Response(200, request=request)

    transport = RedirectTransport()

    def signed_http_client_factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=signed_http_client_factory,
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

    assert requests == [
        ("https://signed.example/upload", b"0123456789"),
        ("https://storage.example/upload", b"0123456789"),
    ]


@pytest.mark.asyncio
async def test_upload_rejects_https_redirect_to_http_without_sending_body(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    downgrade_bodies = []

    class DowngradeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            body = b"".join([chunk async for chunk in request.stream])
            if request.url.scheme == "http":
                downgrade_bodies.append(body)
                return httpx.Response(200, request=request)
            return httpx.Response(
                307,
                headers={"Location": "http://storage.example/upload"},
                request=request,
            )

    def signed_http_client_factory(**kwargs):
        return httpx.AsyncClient(transport=DowngradeTransport(), **kwargs)

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=signed_http_client_factory,
    )
    deleted = []

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "delete_artifact":
            deleted.append(arguments)
            return {}
        if name == "complete_upload":
            return {
                "state": "ready",
                "artifact_id": "artifact-1",
                "verified_sha256": prepared.sha256,
                "size": prepared.size,
            }
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"
    assert downgrade_bodies == []
    assert deleted == [{"artifact_id": "artifact-1"}]


@pytest.mark.asyncio
async def test_redirect_location_is_redacted_before_target_registration(
    user_upload_dir, caplog
):
    from data_agent.mcp_transport import current_runtime_secrets

    prepared = _prepared_regular(user_upload_dir)
    redirect_target = (
        "https://storage.example/opaque-redirect-path-fixture"
        "?custom=opaque-redirect-query-fixture"
    )
    caplog.set_level(logging.INFO)
    httpx_handler = logging.StreamHandler()
    logging.getLogger("httpx").addHandler(httpx_handler)

    class LoggingRedirectTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            body = b"".join([chunk async for chunk in request.stream])
            assert body == b"0123456789"
            if request.url.host == "signed.example":
                logging.getLogger().info(
                    "root redirect Location %s", redirect_target
                )
                logging.getLogger("httpx.fixture").info(
                    "httpx redirect Location %s", redirect_target
                )
                return httpx.Response(
                    307,
                    headers={"Location": redirect_target},
                    request=request,
                )
            return httpx.Response(200, request=request)

    def signed_http_client_factory(**kwargs):
        return httpx.AsyncClient(
            transport=LoggingRedirectTransport(), **kwargs
        )

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=signed_http_client_factory,
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
    try:
        await client._upload_prepared(prepared)
    finally:
        logging.getLogger("httpx").removeHandler(httpx_handler)

    logs = caplog.text
    assert redirect_target not in logs
    assert "opaque-redirect-path-fixture" not in logs
    assert "opaque-redirect-query-fixture" not in logs
    assert redirect_target not in current_runtime_secrets()


@pytest.mark.asyncio
async def test_relative_redirect_location_is_redacted_from_root_and_httpx_logs(
    user_upload_dir, caplog
):
    prepared = _prepared_regular(user_upload_dir)
    redirect_target = (
        "/opaque-relative-path-fixture?custom=opaque-relative-query-fixture"
    )
    caplog.set_level(logging.INFO)
    httpx_handler = logging.StreamHandler()
    logging.getLogger("httpx").addHandler(httpx_handler)

    class LoggingRelativeRedirectTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            body = b"".join([chunk async for chunk in request.stream])
            assert body == b"0123456789"
            if request.url.path == "/upload":
                logging.getLogger().info(f"root relative Location {redirect_target}")
                logging.getLogger("httpx.fixture").info(
                    f"httpx relative Location {redirect_target}"
                )
                return httpx.Response(
                    307,
                    headers={"Location": redirect_target},
                    request=request,
                )
            return httpx.Response(200, request=request)

    def signed_http_client_factory(**kwargs):
        return httpx.AsyncClient(
            transport=LoggingRelativeRedirectTransport(), **kwargs
        )

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=signed_http_client_factory,
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
    try:
        await client._upload_prepared(prepared)
    finally:
        logging.getLogger("httpx").removeHandler(httpx_handler)

    logs = caplog.text
    assert redirect_target not in logs
    assert "opaque-relative-path-fixture" not in logs
    assert "opaque-relative-query-fixture" not in logs


@pytest.mark.asyncio
async def test_upload_uses_pinned_file_after_tenant_directory_replacement(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir, payload=b"original-data")
    original_user_dir = user_upload_dir.parent / "original-user-dir"
    user_upload_dir.rename(original_user_dir)
    user_upload_dir.mkdir()
    (user_upload_dir / prepared.upload_path.name).write_bytes(
        b"replacement-data"
    )
    http_calls = []
    client = _upload_client([FakeUploadResponse()], [], http_calls)

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

    assert http_calls[0]["body"] == b"original-data"


@pytest.mark.asyncio
async def test_upload_rejects_path_replacement_after_preparation(user_upload_dir):
    prepared = _prepared_regular(user_upload_dir, payload=b"original-data")
    prepared.upload_path.unlink()
    prepared.upload_path.write_bytes(b"replacement-data")
    http_calls = []
    client = _upload_client([FakeUploadResponse()], [], http_calls)
    deleted = []

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "delete_artifact":
            deleted.append(arguments)
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._upload_prepared(prepared)

    assert exc_info.value.code == "ARCPY_INPUT_INVALID"
    assert http_calls == []
    assert deleted == [{"artifact_id": "artifact-1"}]


@pytest.mark.asyncio
async def test_upload_rejects_in_place_mutation_during_stream(user_upload_dir):
    payload = b"a" * (1024 * 1024 + 32)
    prepared = _prepared_regular(user_upload_dir, payload=payload)
    deleted = []

    class MutatingSignedUploadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def put(self, url, *, headers, content, timeout):
            iterator = content.__aiter__()
            await anext(iterator)
            prepared.upload_path.write_bytes(b"z" * len(payload))
            async for _ in iterator:
                pass
            return FakeUploadResponse()

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=lambda **kwargs: MutatingSignedUploadClient(),
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
        if name == "delete_artifact":
            deleted.append(arguments)
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError):
        await client._upload_prepared(prepared)

    assert deleted == [{"artifact_id": "artifact-1"}]


@pytest.mark.asyncio
async def test_upload_cancellation_closes_stream_and_cleans_artifact(
    user_upload_dir,
):
    prepared = _prepared_regular(user_upload_dir)
    lease = prepared._lease
    upload_started = asyncio.Event()
    hold_upload = asyncio.Event()

    class BlockingSignedUploadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def put(self, url, *, headers, content, timeout):
            async for _ in content:
                prepared.upload_path.write_bytes(b"x" * prepared.size)
                upload_started.set()
                await hold_upload.wait()
            return FakeUploadResponse()

    def signed_http_client_factory(**kwargs):
        return BlockingSignedUploadClient()

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=signed_http_client_factory,
    )
    deleted = []

    async def call_tool(name, arguments):
        if name == "create_upload":
            return {
                "artifact_id": "artifact-1",
                "upload_url": "https://signed.example/upload",
            }
        if name == "delete_artifact":
            deleted.append(arguments)
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool
    upload_task = asyncio.create_task(client._upload_prepared(prepared))
    await upload_started.wait()

    upload_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await upload_task

    assert lease._closed is True
    assert deleted == [{"artifact_id": "artifact-1"}]


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
@pytest.mark.parametrize(
    ("signed_url", "opaque_path", "opaque_query"),
    [
        (
            "https://signed.example/opaque-path-fixture-secret"
            "?custom=opaque-query-fixture-secret",
            "opaque-path-fixture-secret",
            "opaque-query-fixture-secret",
        ),
        (
            "https://SIGNED.Example/needs space/normalized-path-fixture-secret"
            "?custom=needs space normalized-query-fixture-secret",
            "normalized-path-fixture-secret",
            "normalized-query-fixture-secret",
        ),
    ],
)
async def test_signed_upload_url_is_redacted_from_root_and_httpx_logs(
    user_upload_dir, caplog, signed_url, opaque_path, opaque_query
):
    from data_agent.mcp_transport import current_runtime_secrets

    prepared = _prepared_regular(user_upload_dir)
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
            body = b"".join([chunk async for chunk in content])
            return await self.client.put(
                url,
                headers=headers,
                content=body,
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
        {"follow_redirects": False, "verify": str(ca_bundle)}
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
async def test_inspect_terminal_log_cancellation_preserves_cancelled_error():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
    )
    log_started = asyncio.Event()

    async def call_tool(name, arguments):
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "get_job":
            return {"status": "failed"}
        if name == "get_job_log":
            log_started.set()
            await asyncio.Event().wait()
        raise AssertionError(name)

    client.call_tool = call_tool
    inspection_task = asyncio.create_task(
        client._inspect_uploaded_artifact("artifact-1")
    )
    await log_started.wait()

    inspection_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await inspection_task


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

    cancelled = []

    async def call_tool(name, arguments):
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "get_job":
            return {"status": "running"}
        if name == "cancel_job":
            cancelled.append(arguments)
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_JOB_TIMED_OUT"
    assert cancelled == [{"job_id": "job-1"}]
    assert sleep.delays == [2, 5, 2, 4.0]


@pytest.mark.asyncio
async def test_inspect_timeout_cancels_nonterminal_job_once():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
        inspection_timeout=1.0,
    )
    cancelled = []
    jobs = iter([{"status": "cancelled"}])

    async def call_tool(name, arguments):
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "get_job":
            return next(jobs)
        if name == "cancel_job":
            cancelled.append(arguments)
            return {}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_JOB_TIMED_OUT"
    assert cancelled == [{"job_id": "job-1"}]
    assert sleep.delays == [2]


@pytest.mark.asyncio
async def test_inspect_drain_rejects_cancelled_status_for_other_job():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
        inspection_timeout=6.0,
    )
    jobs = iter(
        [
            {"job_id": "job-1", "status": "running"},
            {"job_id": "job-other", "status": "cancelled"},
            {"job_id": "job-1", "status": "cancelled"},
        ]
    )
    calls = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "cancel_job":
            return {}
        if name == "get_job":
            return next(jobs)
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._inspect_uploaded_artifact("artifact-1")

    assert exc_info.value.code == "ARCPY_JOB_TIMED_OUT"
    assert [name for name, _ in calls].count("cancel_job") == 1
    assert [name for name, _ in calls].count("get_job") == 3


@pytest.mark.asyncio
async def test_inspect_caller_cancellation_cancels_nonterminal_job_once():
    sleep_started = asyncio.Event()
    hold_sleep = asyncio.Event()
    client = _client()
    cancelled = []

    sleep_calls = []

    async def blocking_sleep(delay):
        sleep_calls.append(delay)
        sleep_started.set()
        if len(sleep_calls) == 1:
            await hold_sleep.wait()

    async def call_tool(name, arguments):
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "get_job":
            return {"status": "cancelled"}
        if name == "cancel_job":
            cancelled.append(arguments)
            return {}
        raise AssertionError(name)

    client._sleep = blocking_sleep
    client.call_tool = call_tool
    inspection_task = asyncio.create_task(
        client._inspect_uploaded_artifact("artifact-1")
    )
    await sleep_started.wait()

    inspection_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await inspection_task

    assert cancelled == [{"job_id": "job-1"}]
    assert sleep_calls == [2]


@pytest.mark.asyncio
async def test_inspect_initial_rpc_cancellation_cancels_returned_job_once():
    client = _client()
    inspect_started = asyncio.Event()
    release_inspect = asyncio.Event()
    inspect_finished = asyncio.Event()
    drain_finished = asyncio.Event()
    cancelled = []
    drained = []

    async def call_tool(name, arguments):
        if name == "inspect_dataset":
            inspect_started.set()
            await release_inspect.wait()
            inspect_finished.set()
            return {"job_id": "job-1"}
        if name == "cancel_job":
            cancelled.append(arguments)
            return {}
        if name == "get_job":
            drained.append(arguments)
            drain_finished.set()
            return {"job_id": "job-1", "status": "cancelled"}
        raise AssertionError(name)

    client.call_tool = call_tool
    inspection_task = asyncio.create_task(
        client._inspect_uploaded_artifact("artifact-1")
    )
    await inspect_started.wait()

    inspection_task.cancel()
    release_inspect.set()

    with pytest.raises(asyncio.CancelledError):
        await inspection_task

    assert inspect_finished.is_set()
    assert drain_finished.is_set()
    assert cancelled == [{"job_id": "job-1"}]
    assert drained == [{"job_id": "job-1"}]


@pytest.mark.asyncio
async def test_inspect_cancellation_uses_one_full_inspection_deadline():
    clock = FakeClock()
    sleep = AdvancingSleep(clock)
    client = ArcPyMcpClient(
        McpServerConfig(
            name="arcpy",
            url="https://service.example/mcp",
            timeout=1.0,
        ),
        clock=clock,
        sleep=sleep,
        inspection_timeout=10.0,
    )
    inspect_started = asyncio.Event()
    release_inspect = asyncio.Event()
    cleanup_started = asyncio.Event()
    calls = []
    original_cleanup_deadline = client._inspection_cleanup_deadline

    def inspection_cleanup_deadline():
        deadline = original_cleanup_deadline()
        cleanup_started.set()
        return deadline

    async def call_tool(name, arguments):
        calls.append((name, arguments, clock()))
        if name == "inspect_dataset":
            inspect_started.set()
            await release_inspect.wait()
            return {"job_id": "job-1"}
        if name == "cancel_job":
            return {}
        if name == "get_job":
            return {"job_id": "job-1", "status": "running"}
        raise AssertionError(name)

    client.call_tool = call_tool
    client._inspection_cleanup_deadline = inspection_cleanup_deadline
    inspection_task = asyncio.create_task(
        client._inspect_uploaded_artifact("artifact-1")
    )
    await inspect_started.wait()

    inspection_task.cancel()
    await cleanup_started.wait()
    clock.advance(4.0)
    release_inspect.set()

    with pytest.raises(asyncio.CancelledError):
        await inspection_task

    assert [name for name, _, _ in calls].count("cancel_job") == 1
    assert [name for name, _, _ in calls].count("get_job") == 2
    assert sleep.delays == [2, 4.0]


@pytest.mark.asyncio
async def test_inspect_initial_rpc_cancellation_consumes_hung_call():
    config = McpServerConfig(
        name="arcpy", url="https://service.example/mcp", timeout=0.01
    )
    client = ArcPyMcpClient(config, inspection_timeout=0.01)
    inspect_started = asyncio.Event()
    inspect_finished = asyncio.Event()

    async def call_tool(name, arguments):
        if name != "inspect_dataset":
            raise AssertionError(name)
        inspect_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            inspect_finished.set()

    client.call_tool = call_tool
    inspection_task = asyncio.create_task(
        client._inspect_uploaded_artifact("artifact-1")
    )
    await inspect_started.wait()

    inspection_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(inspection_task, timeout=0.2)
    assert inspect_finished.is_set()


@pytest.mark.asyncio
async def test_inspect_initial_rpc_cleanup_hard_bounds_cancel_suppression():
    config = McpServerConfig(
        name="arcpy", url="https://service.example/mcp", timeout=1.0
    )
    client = ArcPyMcpClient(config, inspection_timeout=0.01)
    inspect_started = asyncio.Event()
    cancellation_swallowed = asyncio.Event()
    release_inspect = asyncio.Event()
    inspect_finished = asyncio.Event()

    async def call_tool(name, arguments):
        if name != "inspect_dataset":
            raise AssertionError(name)
        inspect_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_swallowed.set()
            await release_inspect.wait()
            return None
        finally:
            inspect_finished.set()

    client.call_tool = call_tool
    inspection_task = asyncio.create_task(
        client._inspect_uploaded_artifact("artifact-1")
    )
    await inspect_started.wait()
    inspection_task.cancel()

    completed_in_budget = False
    try:
        await asyncio.wait_for(asyncio.shield(inspection_task), timeout=0.05)
    except asyncio.CancelledError:
        completed_in_budget = True
    except asyncio.TimeoutError:
        pass
    finally:
        release_inspect.set()
        if not inspection_task.done():
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(inspection_task, timeout=0.2)
        await asyncio.wait_for(inspect_finished.wait(), timeout=0.2)

    assert completed_in_budget is True
    assert cancellation_swallowed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("hung_rpc", ["cancel_job", "get_job"])
async def test_inspect_drain_bounds_hung_rpc(hung_rpc):
    config = McpServerConfig(
        name="arcpy", url="https://service.example/mcp", timeout=0.01
    )
    client = ArcPyMcpClient(
        config,
        inspection_timeout=0.01,
    )
    started = asyncio.Event()

    async def call_tool(name, arguments):
        if name == hung_rpc:
            started.set()
            await asyncio.Event().wait()
        if name == "cancel_job":
            return {}
        if name == "get_job":
            return {"job_id": "job-1", "status": "running"}
        raise AssertionError(name)

    client.call_tool = call_tool
    await asyncio.wait_for(
        client._cancel_and_drain_inspection_job("job-1"), timeout=0.2
    )
    assert started.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("hung_rpc", ["cancel_job", "get_job"])
async def test_inspect_drain_hard_bounds_rpc_cancel_suppression(hung_rpc):
    config = McpServerConfig(
        name="arcpy", url="https://service.example/mcp", timeout=1.0
    )
    client = ArcPyMcpClient(config, inspection_timeout=0.01)
    cancellation_swallowed = asyncio.Event()
    release_rpc = asyncio.Event()
    rpc_finished = asyncio.Event()

    async def call_tool(name, arguments):
        if name == hung_rpc:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_swallowed.set()
                await release_rpc.wait()
                if name == "get_job":
                    return {"job_id": "job-1", "status": "cancelled"}
                return {}
            finally:
                rpc_finished.set()
        if name == "cancel_job":
            return {}
        if name == "get_job":
            return {"job_id": "job-1", "status": "running"}
        raise AssertionError(name)

    client.call_tool = call_tool
    cleanup_task = asyncio.create_task(
        client._cancel_and_drain_inspection_job("job-1")
    )
    completed_in_budget = False
    try:
        await asyncio.wait_for(asyncio.shield(cleanup_task), timeout=0.05)
        completed_in_budget = True
    except asyncio.TimeoutError:
        pass
    finally:
        release_rpc.set()
        await asyncio.wait_for(cleanup_task, timeout=0.2)
        await asyncio.wait_for(rpc_finished.wait(), timeout=0.2)

    assert completed_in_budget is True
    assert cancellation_swallowed.is_set()


@pytest.mark.asyncio
async def test_inspect_second_cancellation_interrupts_drain():
    client = _client()
    polling_started = asyncio.Event()
    drain_started = asyncio.Event()
    cancelled = []
    sleep_calls = 0
    get_job_calls = 0

    async def blocking_sleep(delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            polling_started.set()
            await asyncio.Event().wait()

    async def call_tool(name, arguments):
        nonlocal get_job_calls
        if name == "inspect_dataset":
            return {"job_id": "job-1"}
        if name == "cancel_job":
            cancelled.append(arguments)
            return {}
        if name == "get_job":
            get_job_calls += 1
            if get_job_calls > 1:
                return {"job_id": "job-1", "status": "cancelled"}
            drain_started.set()
            await asyncio.Event().wait()
        raise AssertionError(name)

    client._sleep = blocking_sleep
    client.call_tool = call_tool
    inspection_task = asyncio.create_task(
        client._inspect_uploaded_artifact("artifact-1")
    )
    await polling_started.wait()

    inspection_task.cancel()
    await drain_started.wait()
    inspection_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(inspection_task, timeout=0.2)

    assert cancelled == [{"job_id": "job-1"}]
    assert get_job_calls == 1


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


@pytest.mark.parametrize(
    "artifact_path",
    [
        "folder/file:stream",
        "folder/trailing.",
        "folder/trailing ",
        "folder/CON",
        "folder/con.txt",
        "PRN/data.shp",
        "folder/AUX.json",
        "folder/NUL.tif",
        "folder/COM1.bin",
        "folder/com9.extra",
        "folder/COM\u00b9.bin",
        "folder/com\u00b2.extra",
        "folder/Com\u00b3",
        "folder/LPT1",
        "folder/lpt9.txt",
        "folder/LPT\u00b9",
        "folder/lpt\u00b2.txt",
        "folder/Lpt\u00b3",
        "folder/CONIN$",
        "folder/conin$.txt",
        "folder/CONOUT$",
        "folder/conout$.json",
        "folder/control\x01name.shp",
        "folder/nul\x00name.shp",
    ],
)
def test_artifact_relative_path_rejects_windows_unsafe_components(
    artifact_path,
):
    job = {
        "artifact_id": "artifact-1",
        "result": {"artifact_path": artifact_path},
    }

    with pytest.raises(ArcPyMcpError) as exc_info:
        ArcPyMcpClient._artifact_relative_path(job, "artifact-1")

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"


@pytest.mark.parametrize(
    "artifact_path",
    [
        "folder/conduit.shp",
        "folder/auxiliary.json",
        "folder/com10.bin",
        "folder/lpt10.txt",
        "normal.name/roads.shp",
    ],
)
def test_artifact_relative_path_accepts_windows_safe_components(artifact_path):
    job = {
        "artifact_id": "artifact-1",
        "result": {"artifact_path": artifact_path},
    }

    assert (
        ArcPyMcpClient._artifact_relative_path(job, "artifact-1")
        == artifact_path
    )


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
async def test_prepare_input_cancellation_cleans_completed_background_package(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"sidecar")
    original_write_package = client_module._write_package
    package_paths = []
    package_ready = threading.Event()
    release_package = threading.Event()
    package_finished = threading.Event()

    def blocking_write_package(entries, expected_tenant_identity=None):
        package_result = original_write_package(
            entries, expected_tenant_identity
        )
        package_path = (
            package_result[0]
            if isinstance(package_result, tuple)
            else package_result
        )
        package_paths.append(package_path)
        package_ready.set()
        release_package.wait(timeout=5)
        package_finished.set()
        return package_result

    monkeypatch.setattr(
        client_module, "_write_package", blocking_write_package
    )
    client = _client()
    client._upload_prepared = AsyncMock()
    prepare_task = asyncio.create_task(
        client.prepare_input(user_upload_dir / "roads.shp")
    )
    await asyncio.to_thread(package_ready.wait, 5)

    prepare_task.cancel()
    release_package.set()
    with pytest.raises(asyncio.CancelledError):
        await prepare_task
    await asyncio.to_thread(package_finished.wait, 5)

    assert package_paths and not package_paths[0].exists()
    client._upload_prepared.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_input_repeated_cancellation_drains_background_package(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"sidecar")
    original_write_package = client_module._write_package
    package_paths = []
    lease_fds = []
    package_ready = threading.Event()
    release_package = threading.Event()
    package_finished = threading.Event()

    def blocking_write_package(entries, expected_tenant_identity=None):
        package_path, lease = original_write_package(
            entries, expected_tenant_identity
        )
        package_paths.append(package_path)
        lease_fds.extend(
            (lease._tenant_fd, lease._private_dir_fd, lease._file_fd)
        )
        package_ready.set()
        release_package.wait(timeout=5)
        package_finished.set()
        return package_path, lease

    monkeypatch.setattr(
        client_module, "_write_package", blocking_write_package
    )
    client = _client()
    client._upload_prepared = AsyncMock()
    prepare_task = asyncio.create_task(
        client.prepare_input(user_upload_dir / "roads.shp")
    )
    assert await asyncio.to_thread(package_ready.wait, 5)

    prepare_task.cancel("first cancellation")
    await asyncio.sleep(0)
    assert not prepare_task.done()
    prepare_task.cancel("second cancellation")
    release_package.set()

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await prepare_task
    assert exc_info.value.args == ("first cancellation",)
    assert await asyncio.to_thread(package_finished.wait, 5)
    gc.collect()

    assert package_paths and not package_paths[0].parent.exists()
    for descriptor in lease_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    client._upload_prepared.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_input_cancellation_wins_over_background_package_error(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"sidecar")
    original_new_package_file = client_module._new_package_file
    package_paths = []
    lease_fds = []
    package_started = threading.Event()
    release_package = threading.Event()

    def capture_new_package_file(expected_tenant_identity=None):
        package_path, package_stream, lease = original_new_package_file(
            expected_tenant_identity
        )
        package_paths.append(package_path)
        lease_fds.extend(
            (lease._tenant_fd, lease._private_dir_fd, lease._file_fd)
        )
        return package_path, package_stream, lease

    class BlockingFailingZipFile:
        def __init__(self, *args, **kwargs):
            package_started.set()
            release_package.wait(timeout=5)

        def __enter__(self):
            raise OSError("forced package failure")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        client_module, "_new_package_file", capture_new_package_file
    )
    monkeypatch.setattr(
        client_module.zipfile, "ZipFile", BlockingFailingZipFile
    )
    client = _client()
    client._upload_prepared = AsyncMock()
    prepare_task = asyncio.create_task(
        client.prepare_input(user_upload_dir / "roads.shp")
    )
    assert await asyncio.to_thread(package_started.wait, 5)

    prepare_task.cancel("first cancellation")
    await asyncio.sleep(0)
    prepare_task.cancel("second cancellation")
    release_package.set()

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await prepare_task
    assert exc_info.value.args == ("first cancellation",)

    assert package_paths and not package_paths[0].parent.exists()
    for descriptor in lease_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    client._upload_prepared.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_input_repeated_cancellation_drains_local_cleanup(
    user_upload_dir, monkeypatch
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"sidecar")
    original_cleanup = PreparedLocalUpload._cleanup_local_package
    package_paths = []
    lease_fds = []
    cleanup_saw_open_fds = []
    upload_started = asyncio.Event()
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()
    cleanup_finished = threading.Event()

    def blocking_cleanup(prepared):
        cleanup_started.set()
        release_cleanup.wait(timeout=5)
        try:
            original_cleanup(prepared)
            cleanup_saw_open_fds.append(
                all(
                    os.fstat(descriptor) is not None
                    for descriptor in lease_fds
                )
            )
        except OSError:
            cleanup_saw_open_fds.append(False)
        finally:
            cleanup_finished.set()

    monkeypatch.setattr(
        PreparedLocalUpload, "_cleanup_local_package", blocking_cleanup
    )
    client = _client()

    async def blocking_upload(prepared, **kwargs):
        package_paths.append(prepared.upload_path)
        lease_fds.extend(
            (
                prepared._lease._tenant_fd,
                prepared._lease._private_dir_fd,
                prepared._lease._file_fd,
            )
        )
        upload_started.set()
        await asyncio.Future()

    client._upload_prepared = blocking_upload
    prepare_task = asyncio.create_task(
        client.prepare_input(user_upload_dir / "roads.shp")
    )
    await upload_started.wait()

    prepare_task.cancel("first cancellation")
    assert await asyncio.to_thread(cleanup_started.wait, 5)
    prepare_task.cancel("second cancellation")
    release_cleanup.set()

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await prepare_task
    assert exc_info.value.args == ("first cancellation",)
    assert await asyncio.to_thread(cleanup_finished.wait, 5)

    assert cleanup_saw_open_fds == [True]
    assert package_paths and not package_paths[0].parent.exists()
    for descriptor in lease_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.asyncio
async def test_prepare_input_returns_uploaded_artifact_in_required_order(
    user_upload_dir,
):
    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(suffix.encode())
    source = (user_upload_dir / "roads.shp").resolve()
    events = []
    client = _client()

    async def upload(prepared, **kwargs):
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
    assert uploaded.local_package_path.parent.parent == user_upload_dir
    assert uploaded.local_package_path.parent.name.startswith(
        ".arcpy-package-"
    )
    assert uploaded.local_package_path.name == "entry.zip"
    assert uploaded.local_package_path.exists()
    package_dir = uploaded.local_package_path.parent
    uploaded._cleanup_local_package()
    uploaded._close_lease()
    assert not package_dir.exists()


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

    async def upload(prepared, **kwargs):
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

    async def upload(prepared, **kwargs):
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

    async def fail_upload(prepared, **kwargs):
        package_paths.append(prepared.upload_path)
        raise ArcPyMcpError("ARCPY_UPLOAD_FAILED", "private URL")

    client._upload_prepared = fail_upload

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.prepare_input(user_upload_dir / "roads.shp")

    assert exc_info.value.code == "ARCPY_UPLOAD_FAILED"
    assert package_paths and not package_paths[0].exists()


@pytest.mark.parametrize(
    ("failure_stage", "cleanup_operation"),
    [
        ("upload", "stat"),
        ("inspection", "unlink"),
        ("cancellation", "rmdir"),
    ],
)
@pytest.mark.asyncio
async def test_prepare_input_retries_transient_private_cleanup_failure(
    user_upload_dir, monkeypatch, failure_stage, cleanup_operation
):
    import data_agent.arcpy_mcp_client as client_module

    for suffix in (".shp", ".shx", ".dbf"):
        (user_upload_dir / f"roads{suffix}").write_bytes(b"x")

    client = _client()
    expected_error = None
    if failure_stage == "upload":
        expected_error = ArcPyMcpError(
            "ARCPY_UPLOAD_FAILED", "forced upload failure"
        )
        client._upload_prepared = AsyncMock(side_effect=expected_error)
    elif failure_stage == "inspection":
        expected_error = ArcPyMcpError(
            "ARCPY_INSPECTION_FAILED", "forced inspection failure"
        )
        client._upload_prepared = AsyncMock(return_value="artifact-1")
        client._inspect_uploaded_artifact = AsyncMock(
            side_effect=expected_error
        )
        client._best_effort_delete_artifact = AsyncMock()
    else:
        client._upload_prepared = AsyncMock(
            side_effect=asyncio.CancelledError()
        )

    cleanup_state = _fail_first_private_cleanup(
        monkeypatch, client_module, cleanup_operation
    )

    if failure_stage == "cancellation":
        with pytest.raises(asyncio.CancelledError):
            await client.prepare_input(user_upload_dir / "roads.shp")
    else:
        with pytest.raises(ArcPyMcpError) as exc_info:
            await client.prepare_input(user_upload_dir / "roads.shp")
        assert exc_info.value is expected_error

    assert cleanup_state["failed"] is True
    assert list(user_upload_dir.glob(".arcpy-package-*")) == []


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


class FakeSignedDownloadResponse:
    def __init__(self, body: bytes, status_code: int = 200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = dict(headers or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_raw(self):
        yield self._body


class FakeSignedDownloadClient:
    def __init__(self, response, calls):
        self._response = response
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, *, headers, timeout):
        self._calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return self._response


@pytest.mark.asyncio
async def test_poll_wait_for_job_uses_required_delays_and_waits_for_succeeded():
    clock = FakeClock()
    delays = []
    statuses = iter(("queued", "running", "pending", "succeeded"))

    async def sleep(delay):
        delays.append(delay)
        clock.advance(delay)

    async def call_tool(name, arguments):
        assert name == "get_job"
        assert arguments == {"job_id": "job-1"}
        return {"id": "job-1", "status": next(statuses), "result": {}}

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        clock=clock,
        sleep=sleep,
    )
    client.call_tool = call_tool

    job = await client.wait_for_job("job-1", timeout=60)

    assert job["status"] == "succeeded"
    assert delays == [2, 5, 10, 20]


@pytest.mark.asyncio
async def test_job_log_is_fetched_for_terminal_failure():
    calls = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "get_job":
            return {
                "id": "job-1",
                "status": "failed",
                "error_code": "ARCPY_EXECUTION_FAILED",
            }
        if name == "get_job_log":
            return {
                "result": [
                    {"level": "error", "message": "ERROR 000229: bad input"}
                ]
            }
        raise AssertionError(name)

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        sleep=AsyncMock(),
    )
    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.wait_for_job("job-1", timeout=60)

    assert exc_info.value.code == "ARCPY_JOB_FAILED"
    assert exc_info.value.details == {
        "status": "failed",
        "arcpy_messages": ["ERROR 000229: bad input"],
    }
    assert calls == [
        ("get_job", {"job_id": "job-1"}),
        ("get_job_log", {"job_id": "job-1"}),
    ]


@pytest.mark.asyncio
async def test_cancel_job_calls_remote_once_and_drains_to_terminal():
    calls = []
    statuses = iter(("running", "cancelled"))

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "cancel_job":
            return {"id": "job-1", "status": "cancelling"}
        if name == "get_job":
            return {"id": "job-1", "status": next(statuses)}
        if name == "get_job_log":
            return {"result": []}
        raise AssertionError(name)

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        sleep=AsyncMock(),
    )
    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.cancel_job("job-1")

    assert exc_info.value.code == "ARCPY_JOB_CANCELLED"
    assert [name for name, _ in calls].count("cancel_job") == 1
    assert [name for name, _ in calls].count("get_job") == 2


def _download_client(response, factory_calls, http_calls):
    def factory(**factory_kwargs):
        factory_calls.append(factory_kwargs)
        return FakeSignedDownloadClient(response, http_calls)

    return ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=factory,
    )


@pytest.mark.asyncio
async def test_download_checksum_mismatch_deletes_partial_file(user_upload_dir):
    body = b"corrupt-result"
    factory_calls = []
    http_calls = []
    client = _download_client(
        FakeSignedDownloadResponse(body), factory_calls, http_calls
    )
    client.health_check = AsyncMock(
        return_value={
            "worker": {
                "product": "ArcInfo",
                "install": {"Version": "3.7.1"},
            }
        }
    )

    async def call_tool(name, arguments):
        assert name == "create_download"
        assert arguments == {"artifact_id": "output-1"}
        return {
            "artifact_id": "output-1",
            "download_url": "https://signed.example/result",
            "logical_name": "result.geojson",
            "actual_sha256": hashlib.sha256(b"expected").hexdigest(),
            "actual_size": len(body),
        }

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.download_job_results(
            "buffer_features",
            {
                "status": "succeeded",
                "result": {"output_artifact_ids": ["output-1"]},
            },
            [str(user_upload_dir / "source.geojson")],
        )

    assert exc_info.value.code == "ARCPY_DOWNLOAD_CHECKSUM_MISMATCH"
    assert list(user_upload_dir.rglob("*.part")) == []
    assert list(user_upload_dir.rglob("result*.geojson")) == []
    assert factory_calls == [{"follow_redirects": False}]
    assert http_calls[0]["headers"] == {"Accept-Encoding": "identity"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry_name",
    [
        "../escape.shp",
        "/absolute.shp",
        "C:/drive.shp",
        "..\\escape.shp",
    ],
)
async def test_download_rejects_unsafe_zip_entries(
    user_upload_dir, tmp_path, entry_name
):
    archive = tmp_path / "result.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(entry_name, b"shape")
    body = archive.read_bytes()
    client = _download_client(
        FakeSignedDownloadResponse(body), [], []
    )
    client.health_check = AsyncMock(
        return_value={
            "worker": {
                "product": "ArcInfo",
                "install": {"Version": "3.7.1"},
            }
        }
    )

    async def call_tool(name, arguments):
        assert name == "create_download"
        return {
            "artifact_id": "output-zip",
            "download_url": "https://signed.example/result",
            "logical_name": "result.zip",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.download_job_results(
            "buffer_features",
            {
                "status": "succeeded",
                "result": {"output_artifact_ids": ["output-zip"]},
            },
            [str(user_upload_dir / "source.shp")],
        )

    assert exc_info.value.code == "ARCPY_UNSAFE_ARCHIVE"
    assert not (user_upload_dir.parent / "escape.shp").exists()


class InterruptingDownloadResponse(FakeSignedDownloadResponse):
    async def aiter_raw(self):
        yield self._body
        raise httpx.ReadError("interrupted")


class SequencedSignedDownloadClient:
    def __init__(self, responses, calls):
        self._responses = iter(responses)
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, *, headers, timeout):
        self._calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return next(self._responses)


@pytest.mark.asyncio
async def test_download_resumes_with_range_and_registers_verified_output(
    user_upload_dir, monkeypatch
):
    import data_agent.data_catalog as data_catalog

    body = b'foo {"type":"FeatureCollection","features":[]} bar'
    first, second = body[:7], body[7:]
    http_calls = []
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return SequencedSignedDownloadClient(
            [
                InterruptingDownloadResponse(first),
                FakeSignedDownloadResponse(
                    second,
                    status_code=206,
                    headers={
                        "Content-Range": f"bytes 7-{len(body) - 1}/{len(body)}"
                    },
                ),
            ],
            http_calls,
        )

    registrations = []
    monkeypatch.setattr(
        data_catalog,
        "register_tool_output",
        lambda *args, **kwargs: registrations.append((args, kwargs)),
    )
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=factory,
    )
    client.health_check = AsyncMock(
        return_value={
            "worker": {
                "product": "ArcInfo",
                "install": {"Version": "3.7.1"},
            }
        }
    )
    calls = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "create_download":
            return {
                "artifact_id": "output-1",
                "download_url": "https://signed.example/result",
                "logical_name": "result.bin",
                "actual_sha256": hashlib.sha256(body).hexdigest(),
                "actual_size": len(body),
            }
        if name == "delete_artifact":
            return {"artifact_id": "output-1", "state": "deleted"}
        raise AssertionError(name)

    client.call_tool = call_tool

    result = await client.download_job_results(
        "buffer_features",
        {
            "status": "succeeded",
            "request": {"distance": "10 Meters"},
            "result": {"output_artifact_ids": ["output-1"]},
        },
        [str(user_upload_dir / "source.geojson")],
        _tool_params={"distance": "10 Meters"},
    )

    output = Path(result["local_outputs"][0])
    assert output.read_bytes() == body
    assert list(user_upload_dir.rglob("*.part")) == []
    assert factory_calls == [{"follow_redirects": False}]
    assert http_calls[0]["headers"] == {"Accept-Encoding": "identity"}
    assert http_calls[1]["headers"] == {
        "Accept-Encoding": "identity",
        "Range": "bytes=7-",
    }
    assert all("Authorization" not in call["headers"] for call in http_calls)
    assert [name for name, _ in calls] == [
        "create_download",
        "create_download",
        "delete_artifact",
    ]
    assert registrations[0][0][0] == str(output)


@pytest.mark.asyncio
async def test_download_never_starts_for_non_succeeded_job():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    client.health_check = AsyncMock(return_value={"worker": {}})
    client.call_tool = AsyncMock()

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.download_job_results(
            "buffer_features",
            {"status": "running", "result": {"output_artifact_ids": []}},
            [],
        )

    assert exc_info.value.code == "ARCPY_RESPONSE_INVALID"
    client.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_dedicated_binds_inputs_waits_downloads_and_cleans_up():
    events = []
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        job_timeout=321,
    )
    client.health_check = AsyncMock(
        side_effect=lambda: events.append("health")
        or {"worker": {"product": "ArcInfo", "install": {"Version": "3.7"}}}
    )

    async def prepare(path):
        events.append(("prepare", path))
        prefix = Path(path).stem
        return UploadedArtifact(
            artifact_id=f"artifact-{prefix}",
            artifact_path=f"{prefix}.geojson",
            source_path=Path(path),
            local_package_path=Path(path),
            delete_local_package=False,
        )

    async def call_tool(name, arguments):
        events.append((name, arguments))
        if name == "clip_features":
            return {"job_id": "job-1"}
        if name == "delete_artifact":
            return {"state": "deleted"}
        raise AssertionError(name)

    client.prepare_input = prepare
    client.call_tool = call_tool
    client.wait_for_job = AsyncMock(
        side_effect=lambda job_id, timeout: events.append(
            ("wait", job_id, timeout)
        )
        or {"id": job_id, "status": "succeeded", "result": {"output_artifact_ids": []}}
    )
    client.download_job_results = AsyncMock(
        side_effect=lambda operation, job, paths, **kwargs: events.append(
            ("download", operation, paths)
        )
        or {"status": "success", "operation": operation}
    )

    result = await client.run_dedicated(
        "clip_features",
        {"input": "/uploads/roads.geojson", "clip": "/uploads/aoi.geojson"},
        {"output_name": "clipped.zip"},
    )

    assert result["status"] == "success"
    assert result["operation"] == "clip_features"
    assert result["arcgis_product"] == "ArcInfo"
    assert events[0] == "health"
    assert (
        "clip_features",
        {
            "output_name": "clipped.zip",
            "input_artifact_id": "artifact-roads",
            "input_path": "roads.geojson",
            "clip_artifact_id": "artifact-aoi",
            "clip_path": "aoi.geojson",
        },
    ) in events
    assert ("wait", "job-1", 321.0) in events
    assert [event for event in events if event[0] == "delete_artifact"] == [
        ("delete_artifact", {"artifact_id": "artifact-roads"}),
        ("delete_artifact", {"artifact_id": "artifact-aoi"}),
    ]


@pytest.mark.asyncio
async def test_run_catalog_tool_requires_exact_schema_validated_match():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    client.health_check = AsyncMock(return_value={"worker": {}})
    events = []

    async def call_tool(name, arguments):
        events.append((name, arguments))
        if name == "search_tools":
            return {"result": [{"tool_id": "vector.erase"}]}
        if name == "describe_tool":
            return {
                "tool_id": "vector.erase",
                "input_schema": {
                    "type": "object",
                    "properties": {"output_name": {"type": "string"}},
                    "required": ["output_name"],
                    "additionalProperties": False,
                },
            }
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.run_catalog_tool(
            "vector.erase",
            "vector",
            {},
            {"output_name": 42},
        )

    assert exc_info.value.code == "ARCPY_TOOL_NOT_ALLOWED"
    assert [name for name, _ in events] == ["search_tools", "describe_tool"]


def test_select_exact_catalog_tool_rejects_fuzzy_and_duplicate_matches():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )

    with pytest.raises(ArcPyMcpError) as fuzzy:
        client._select_exact_tool_id(
            {"result": [{"tool_id": "vector.buffer"}]}, "buffer"
        )
    with pytest.raises(ArcPyMcpError) as duplicate:
        client._select_exact_tool_id(
            {
                "result": [
                    {"tool_id": "vector.buffer"},
                    {"tool_id": "vector.buffer"},
                ]
            },
            "vector.buffer",
        )

    assert fuzzy.value.code == "ARCPY_TOOL_NOT_ALLOWED"
    assert duplicate.value.code == "ARCPY_TOOL_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_cancelled_wait_requests_cancel_once_and_drains_terminal_state():
    sleep_started = asyncio.Event()
    sleeps = []
    calls = []
    statuses = iter(("running", "cancelled"))

    async def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 1:
            sleep_started.set()
            await asyncio.Future()

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "cancel_job":
            return {"id": "job-1", "status": "cancelling"}
        if name == "get_job":
            return {"id": "job-1", "status": next(statuses)}
        if name == "get_job_log":
            return {"result": []}
        raise AssertionError(name)

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        sleep=sleep,
    )
    client.call_tool = call_tool
    wait_task = asyncio.create_task(client.wait_for_job("job-1", 60))
    await sleep_started.wait()

    wait_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await wait_task

    assert [name for name, _ in calls].count("cancel_job") == 1
    assert [name for name, _ in calls].count("get_job") == 2


@pytest.mark.asyncio
async def test_download_rejects_zip_symlink(user_upload_dir, tmp_path):
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        entry = zipfile.ZipInfo("link.shp")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(entry, "../escape.shp")
    body = archive.read_bytes()
    client = _download_client(FakeSignedDownloadResponse(body), [], [])
    client.health_check = AsyncMock(return_value={"worker": {}})

    async def call_tool(name, arguments):
        if name == "create_download":
            return {
                "artifact_id": "output-zip",
                "download_url": "https://signed.example/result",
                "logical_name": "result.zip",
                "actual_sha256": hashlib.sha256(body).hexdigest(),
                "actual_size": len(body),
            }
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.download_job_results(
            "buffer_features",
            {
                "status": "succeeded",
                "result": {"output_artifact_ids": ["output-zip"]},
            },
            [],
        )

    assert exc_info.value.code == "ARCPY_UNSAFE_ARCHIVE"


@pytest.mark.asyncio
async def test_verified_geojson_is_registered_and_returns_map_metadata(
    user_upload_dir, monkeypatch
):
    import data_agent.artifact_handler as artifact_handler
    import data_agent.data_catalog as data_catalog
    import geopandas as gpd

    output = user_upload_dir / "result.geojson"
    output.write_text(
        '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
    )
    registrations = []
    monkeypatch.setattr(
        data_catalog,
        "register_tool_output",
        lambda *args, **kwargs: registrations.append((args, kwargs)),
    )
    monkeypatch.setattr(
        artifact_handler,
        "build_map_update_from_geojson",
        lambda path: {"layers": [{"path": path}]},
    )
    monkeypatch.setattr(
        gpd,
        "read_file",
        lambda path: SimpleNamespace(empty=False),
    )
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    client.health_check = AsyncMock(
        return_value={
            "worker": {
                "product": "ArcInfo",
                "install": {"Version": "3.7.1"},
            }
        }
    )
    client._download_artifact = AsyncMock(return_value=[output])
    client._run_remote_cleanup = AsyncMock()

    result = await client.download_job_results(
        "buffer_features",
        {
            "status": "succeeded",
            "request": {"distance": "10 Meters"},
            "result": {
                "output_artifact_ids": ["output-1"],
                "dataset_summary": {"count": 4},
            },
        },
        ["source.geojson"],
        _tool_params={"distance": "10 Meters"},
    )

    assert result["local_outputs"] == [str(output)]
    assert result["map_update"] == {"layers": [{"path": str(output)}]}
    assert result["dataset_summary"] == {"count": 4}
    assert result["arcgis_product"] == "ArcInfo"
    assert result["arcgis_version"] == "3.7.1"
    assert registrations == [
        (
            (str(output), "buffer_features", {"distance": "10 Meters"}),
            {"source_paths": ["source.geojson"]},
        )
    ]


@pytest.mark.asyncio
async def test_run_deep_learning_checks_image_analyst_and_marks_operation():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    client.health_check = AsyncMock(return_value={"worker": {}})
    client.get_capabilities = AsyncMock(return_value={"worker": {}})
    client._execute_operation = AsyncMock(return_value={"status": "success"})

    result = await client.run_deep_learning(
        "detect_objects",
        {"input": "image.tif"},
        "model.dlpk",
        {"output_name": "detections.zip"},
    )

    assert result == {"status": "success"}
    client.get_capabilities.assert_awaited_once_with(
        required_extension="ImageAnalyst"
    )
    client._execute_operation.assert_awaited_once_with(
        remote_tool="detect_objects",
        local_inputs={"input": "image.tif", "model": "model.dlpk"},
        parameters={"output_name": "detections.zip"},
        deep_learning=True,
    )


@pytest.mark.asyncio
async def test_deep_learning_operation_waits_with_dl_job_timeout():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        job_timeout=12,
        dl_job_timeout=345,
    )
    client.health_check = AsyncMock(return_value={"worker": {}})
    uploaded = UploadedArtifact(
        artifact_id="image-1",
        artifact_path="image.tif",
        source_path=Path("image.tif"),
        local_package_path=Path("image.tif"),
        delete_local_package=False,
    )
    client.prepare_input = AsyncMock(return_value=uploaded)

    async def call_tool(name, arguments):
        if name == "detect_objects":
            return {"job_id": "job-1"}
        if name == "delete_artifact":
            return {"state": "deleted"}
        raise AssertionError(name)

    client.call_tool = call_tool
    client.wait_for_job = AsyncMock(
        return_value={
            "id": "job-1",
            "status": "succeeded",
            "result": {"output_artifact_ids": []},
        }
    )
    client.download_job_results = AsyncMock(
        return_value={"status": "success"}
    )

    await client._execute_operation(
        "detect_objects",
        {"input": "image.tif"},
        {"output_name": "detections.zip"},
        deep_learning=True,
    )

    client.wait_for_job.assert_awaited_once_with("job-1", 345.0)


@pytest.mark.asyncio
async def test_catalog_tool_submits_validated_exact_tool_and_cleans_input():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    client.health_check = AsyncMock(
        return_value={
            "worker": {
                "product": "ArcInfo",
                "install": {"Version": "3.7.1"},
            }
        }
    )
    uploaded = UploadedArtifact(
        artifact_id="input-1",
        artifact_path="roads.geojson",
        source_path=Path("roads.geojson"),
        local_package_path=Path("roads.geojson"),
        delete_local_package=False,
    )
    client.prepare_input = AsyncMock(return_value=uploaded)
    events = []

    async def call_tool(name, arguments):
        events.append((name, arguments))
        if name == "search_tools":
            return {"result": [{"tool_id": "vector.erase"}]}
        if name == "describe_tool":
            return {
                "tool_id": "vector.erase",
                "input_schema": {
                    "type": "object",
                    "properties": {"output_name": {"type": "string"}},
                    "required": ["output_name"],
                    "additionalProperties": False,
                },
            }
        if name == "submit_job":
            return {"job_id": "job-1"}
        if name == "delete_artifact":
            return {"state": "deleted"}
        raise AssertionError(name)

    client.call_tool = call_tool
    client.wait_for_job = AsyncMock(
        return_value={
            "id": "job-1",
            "status": "succeeded",
            "result": {"output_artifact_ids": []},
        }
    )
    client.download_job_results = AsyncMock(
        return_value={"status": "success", "operation": "vector.erase"}
    )

    result = await client.run_catalog_tool(
        "vector.erase",
        "vector",
        {"input": "roads.geojson"},
        {"output_name": "erased.zip"},
    )

    assert result["status"] == "success"
    assert (
        "submit_job",
        {
            "tool_id": "vector.erase",
            "parameters": {
                "output_name": "erased.zip",
                "input_artifact_id": "input-1",
                "input_path": "roads.geojson",
            },
        },
    ) in events
    assert events[-1] == (
        "delete_artifact",
        {"artifact_id": "input-1"},
    )


def test_catalog_tool_selection_forbids_training_even_if_server_returns_it():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        client._select_exact_tool_id(
            {"result": [{"tool_id": "dl.TrainDeepLearningModel"}]},
            "dl.TrainDeepLearningModel",
        )

    assert exc_info.value.code == "ARCPY_TOOL_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_run_multi_input_cleans_prepared_remote_on_later_prepare_failure():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    client.health_check = AsyncMock(return_value={"worker": {}})
    uploaded = UploadedArtifact(
        artifact_id="input-1",
        artifact_path="first.geojson",
        source_path=Path("first.geojson"),
        local_package_path=Path("first.geojson"),
        delete_local_package=False,
    )
    client.prepare_input = AsyncMock(
        side_effect=[uploaded, ArcPyMcpError("ARCPY_INPUT_INVALID", "bad")]
    )
    client.call_tool = AsyncMock(return_value={"state": "deleted"})

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client.run_multi_input(
            "intersect_features",
            ["first.geojson", "second.geojson"],
            {"output_name": "intersection.zip"},
        )

    assert exc_info.value.code == "ARCPY_INPUT_INVALID"
    client.call_tool.assert_awaited_once_with(
        "delete_artifact", {"artifact_id": "input-1"}
    )


@pytest.mark.asyncio
async def test_submit_wait_download_does_not_delete_parameter_artifact_ids():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    calls = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "intersect_features":
            raise ArcPyMcpError("ARCPY_JOB_FAILED", "failed")
        if name == "delete_artifact":
            return {"state": "deleted"}
        raise AssertionError(name)

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError):
        await client._submit_wait_download(
            "intersect_features",
            {
                "inputs": [
                    {"artifact_id": "owned-input", "path": "roads.shp"}
                ],
                "reference_artifact_id": "not-owned",
            },
            ["roads.shp"],
        )

    deleted = [
        arguments["artifact_id"]
        for name, arguments in calls
        if name == "delete_artifact"
    ]
    assert deleted == ["owned-input"]


@pytest.mark.asyncio
async def test_wait_for_job_bounds_hung_get_job_rpc():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        sleep=AsyncMock(),
    )

    async def call_tool(name, arguments):
        assert name == "get_job"
        await asyncio.Future()

    client.call_tool = call_tool

    with pytest.raises(ArcPyMcpError) as exc_info:
        await asyncio.wait_for(
            client.wait_for_job("job-1", timeout=0.02), timeout=0.5
        )

    assert exc_info.value.code == "ARCPY_JOB_TIMED_OUT"


@pytest.mark.asyncio
async def test_cancelled_wait_bounds_hung_cancel_rpc_and_calls_once():
    sleep_started = asyncio.Event()
    cancel_calls = 0

    async def sleep(delay):
        sleep_started.set()
        await asyncio.Future()

    async def call_tool(name, arguments):
        nonlocal cancel_calls
        if name == "cancel_job":
            cancel_calls += 1
            await asyncio.Future()
        raise AssertionError(name)

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        sleep=sleep,
        job_timeout=0.02,
    )
    client.call_tool = call_tool
    task = asyncio.create_task(client.wait_for_job("job-1", timeout=60))
    await sleep_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.5)

    assert cancel_calls == 1


@pytest.mark.parametrize(
    "tool_id",
    [
        "dl.detect_objects",
        "dl.classify_pixels",
        "dl.classify_objects",
        "dl.detect_change",
    ],
)
def test_catalog_tool_selection_forbids_deep_learning_bypass(tool_id):
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        client._select_exact_tool_id(
            {"result": [{"tool_id": tool_id}]}, tool_id
        )

    assert exc_info.value.code == "ARCPY_TOOL_NOT_ALLOWED"


def test_select_exact_catalog_tool_falls_back_to_tools_when_result_empty():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )

    assert (
        client._select_exact_tool_id(
            {
                "result": [],
                "tools": [{"tool_id": "vector.erase"}],
            },
            "vector.erase",
        )
        == "vector.erase"
    )


@pytest.mark.asyncio
async def test_download_retries_expired_signed_url(user_upload_dir):
    body = b"verified-result"
    http_calls = []

    def factory(**kwargs):
        return SequencedSignedDownloadClient(
            [
                FakeSignedDownloadResponse(b"", status_code=403),
                FakeSignedDownloadResponse(body),
            ],
            http_calls,
        )

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=factory,
    )
    create_calls = 0

    async def call_tool(name, arguments):
        nonlocal create_calls
        assert name == "create_download"
        create_calls += 1
        return {
            "artifact_id": "output-1",
            "download_url": f"https://signed.example/result-{create_calls}",
            "logical_name": "result.bin",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }

    client.call_tool = call_tool

    outputs = await client._download_artifact("output-1")

    assert outputs[0].read_bytes() == body
    assert create_calls == 2
    assert all("Authorization" not in call["headers"] for call in http_calls)


@pytest.mark.asyncio
async def test_download_rejects_mismatched_content_range(user_upload_dir):
    body = b"abcdef"
    http_calls = []

    def factory(**kwargs):
        return SequencedSignedDownloadClient(
            [
                InterruptingDownloadResponse(body[:3]),
                FakeSignedDownloadResponse(
                    body[3:],
                    status_code=206,
                    headers={"Content-Range": "bytes 0-2/6"},
                ),
            ],
            http_calls,
        )

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=factory,
    )
    client.call_tool = AsyncMock(
        return_value={
            "artifact_id": "output-1",
            "download_url": "https://signed.example/result",
            "logical_name": "result.bin",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._download_artifact("output-1")

    assert exc_info.value.code == "ARCPY_DOWNLOAD_FAILED"
    assert list(user_upload_dir.glob(".arcpy-result-*")) == []


@pytest.mark.asyncio
async def test_download_accepts_416_when_partial_is_already_complete(
    user_upload_dir,
):
    body = b"complete-before-disconnect"

    def factory(**kwargs):
        return SequencedSignedDownloadClient(
            [
                InterruptingDownloadResponse(body),
                FakeSignedDownloadResponse(
                    b"",
                    status_code=416,
                    headers={"Content-Range": f"bytes */{len(body)}"},
                ),
            ],
            [],
        )

    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        signed_http_client_factory=factory,
    )
    client.call_tool = AsyncMock(
        return_value={
            "artifact_id": "output-1",
            "download_url": "https://signed.example/result",
            "logical_name": "result.bin",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }
    )

    outputs = await client._download_artifact("output-1")

    assert outputs[0].read_bytes() == body


@pytest.mark.asyncio
async def test_download_rejects_part_name_swap_after_hash(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    body = b"verified"
    original_rename = client_module.os.rename

    def swap_then_rename(src, dst, *, src_dir_fd, dst_dir_fd):
        os.unlink(src, dir_fd=src_dir_fd)
        descriptor = os.open(
            src,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=src_dir_fd,
        )
        with os.fdopen(descriptor, "wb") as replacement:
            replacement.write(b"attacker")
        return original_rename(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(client_module.os, "rename", swap_then_rename)
    client = _download_client(FakeSignedDownloadResponse(body), [], [])
    client.call_tool = AsyncMock(
        return_value={
            "artifact_id": "output-1",
            "download_url": "https://signed.example/result",
            "logical_name": "result.bin",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._download_artifact("output-1")

    assert exc_info.value.code == "ARCPY_DOWNLOAD_FAILED"
    assert list(user_upload_dir.glob(".arcpy-result-*")) == []


@pytest.mark.asyncio
async def test_download_rejects_workspace_directory_swap_before_return(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    body = b"verified"
    moved_paths = []
    original_validate = client_module._DownloadWorkspace.validate_path

    def swap_then_validate(workspace):
        moved = workspace.path.with_name(f"{workspace.path.name}-moved")
        workspace.path.rename(moved)
        workspace.path.mkdir(mode=0o700)
        moved_paths.append(moved)
        return original_validate(workspace)

    monkeypatch.setattr(
        client_module._DownloadWorkspace,
        "validate_path",
        swap_then_validate,
    )
    client = _download_client(FakeSignedDownloadResponse(body), [], [])
    client.call_tool = AsyncMock(
        return_value={
            "artifact_id": "output-1",
            "download_url": "https://signed.example/result",
            "logical_name": "result.bin",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._download_artifact("output-1")

    assert exc_info.value.code == "ARCPY_DOWNLOAD_FAILED"
    assert moved_paths
    assert list(moved_paths[0].iterdir()) == []
    assert list(user_upload_dir.rglob("result.bin")) == []


@pytest.mark.asyncio
async def test_cancelled_zip_extraction_drains_thread_before_cleanup(
    user_upload_dir, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    body = b"verified-zip-placeholder"
    extraction_started = threading.Event()
    release_extraction = threading.Event()

    def blocking_extract(archive_stream, workspace):
        extraction_started.set()
        release_extraction.wait(2)
        late_output = workspace.path / "late.shp"
        late_output.write_bytes(b"late")
        return [late_output]

    monkeypatch.setattr(
        client_module, "_extract_verified_zip", blocking_extract
    )
    client = _download_client(FakeSignedDownloadResponse(body), [], [])
    client.call_tool = AsyncMock(
        return_value={
            "artifact_id": "output-1",
            "download_url": "https://signed.example/result",
            "logical_name": "result.zip",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }
    )
    task = asyncio.create_task(client._download_artifact("output-1"))
    await asyncio.to_thread(extraction_started.wait)
    timer = threading.Timer(0.02, release_extraction.set)
    timer.start()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    timer.join()
    assert list(user_upload_dir.glob(".arcpy-result-*")) == []


@pytest.mark.asyncio
async def test_zip_extraction_enforces_uncompressed_size_limit(
    user_upload_dir, tmp_path, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    archive = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("roads.shp", b"1234")
    body = archive.read_bytes()
    monkeypatch.setattr(
        client_module, "_MAX_ARCHIVE_UNCOMPRESSED_BYTES", 3
    )
    client = _download_client(FakeSignedDownloadResponse(body), [], [])
    client.call_tool = AsyncMock(
        return_value={
            "artifact_id": "output-1",
            "download_url": "https://signed.example/result",
            "logical_name": "result.zip",
            "actual_sha256": hashlib.sha256(body).hexdigest(),
            "actual_size": len(body),
        }
    )

    with pytest.raises(ArcPyMcpError) as exc_info:
        await client._download_artifact("output-1")

    assert exc_info.value.code == "ARCPY_UNSAFE_ARCHIVE"
    assert list(user_upload_dir.glob(".arcpy-result-*")) == []


def test_extracted_dataset_paths_keep_non_sidecar_same_stem():
    import data_agent.arcpy_mcp_client as client_module

    root = Path("/tmp/result")
    paths = [
        root / "roads.shp",
        root / "roads.dbf",
        root / "roads.shx",
        root / "roads.tif",
        root / "roads.geojson",
    ]

    outputs = client_module._extracted_dataset_paths(paths)

    assert root / "roads.shp" in outputs
    assert root / "roads.tif" in outputs
    assert root / "roads.geojson" in outputs
    assert root / "roads.dbf" not in outputs
    assert root / "roads.shx" not in outputs


def test_unique_map_geojson_never_overwrites_existing_output(
    tmp_path, monkeypatch
):
    import data_agent.arcpy_mcp_client as client_module

    source = tmp_path / "roads.shp"
    collision = tmp_path / "roads-map-collision.geojson"
    collision.write_bytes(b"verified-existing")
    tokens = iter(("temporary", "collision", "unique"))
    monkeypatch.setattr(
        client_module.secrets, "token_hex", lambda size: next(tokens)
    )

    class Frame:
        def to_file(self, path, driver):
            assert driver == "GeoJSON"
            Path(path).write_bytes(b"generated")

    output = client_module._write_unique_geojson(Frame(), source)

    assert collision.read_bytes() == b"verified-existing"
    assert output.name == "roads-map-unique.geojson"
    assert output.read_bytes() == b"generated"


def test_result_metadata_is_fail_closed_for_untrusted_job_fields():
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    job = {
        "result": {
            "output_artifact_ids": ["output-1"],
            "signed_url": "https://signed.example/result?sig=secret",
            "dataset_summary": {
                "count": 3,
                "name": "roads",
                "server_path": "C:\\private\\roads.shp",
                "callback": "https://signed.example/result?sig=secret",
            },
        }
    }

    assert client._dataset_summary(job) == {"count": 3, "name": "roads"}
    assert client._registration_parameters(
        {
            "distance": "10 Meters",
            "input_path": "/private/roads.shp",
            "input_artifact_id": "input-1",
            "callback": "https://signed.example/result?sig=secret",
        }
    ) == {"distance": "10 Meters", "callback": "[REDACTED]"}


@pytest.mark.asyncio
async def test_verified_output_is_deleted_remotely_when_registration_fails(
    user_upload_dir,
):
    output = user_upload_dir / "result.bin"
    output.write_bytes(b"verified")
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp")
    )
    client.health_check = AsyncMock(return_value={"worker": {}})
    client._download_artifact = AsyncMock(return_value=[output])
    client._register_and_map_outputs = AsyncMock(
        side_effect=RuntimeError("registration failed")
    )
    client._run_remote_cleanup = AsyncMock()

    with pytest.raises(RuntimeError, match="registration failed"):
        await client.download_job_results(
            "buffer_features",
            {
                "status": "succeeded",
                "result": {"output_artifact_ids": ["output-1"]},
            },
            [],
        )

    client._run_remote_cleanup.assert_awaited_once_with(["output-1"])


@pytest.mark.asyncio
async def test_cancellation_during_output_delete_is_not_swallowed(
    user_upload_dir,
):
    output = user_upload_dir / "result.bin"
    output.write_bytes(b"verified")
    delete_started = asyncio.Event()
    release_delete = asyncio.Event()
    delete_calls = 0
    client = ArcPyMcpClient(
        McpServerConfig(name="arcpy", url="https://service.example/mcp"),
        inspection_timeout=1,
    )
    client.health_check = AsyncMock(return_value={"worker": {}})
    client._download_artifact = AsyncMock(return_value=[output])
    client._register_and_map_outputs = AsyncMock(
        return_value=([str(output)], None)
    )

    async def call_tool(name, arguments):
        nonlocal delete_calls
        assert name == "delete_artifact"
        delete_calls += 1
        delete_started.set()
        await release_delete.wait()
        return {"state": "deleted"}

    client.call_tool = call_tool
    task = asyncio.create_task(
        client.download_job_results(
            "buffer_features",
            {
                "status": "succeeded",
                "result": {"output_artifact_ids": ["output-1"]},
            },
            [],
        )
    )
    await delete_started.wait()
    task.cancel()
    release_delete.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    assert delete_calls == 1


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
