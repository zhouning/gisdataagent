from datetime import UTC, datetime

import pytest

from data_agent.platform_runtime.tenant_recovery import (
    TenantRecoveryContractError,
    build_recovery_manifest,
    compare_recovery_manifests,
    fingerprint_tenant_rows,
    validate_tenant_visibility,
)

TABLES = ("resource", "platform_run")


def _manifest(rows_by_tenant: dict[str, dict[str, list[dict]]]):
    digests = [
        fingerprint_tenant_rows(tenant, table, rows)
        for tenant, tables in rows_by_tenant.items()
        for table, rows in tables.items()
    ]
    return build_recovery_manifest(tuple(rows_by_tenant), digests)


def test_manifest_is_stable_across_sql_order_and_datetime_types():
    source = _manifest(
        {
            "tenant-a": {
                "resource": [
                    {"id": 2, "at": datetime(2026, 8, 25, tzinfo=UTC)},
                    {"id": 1, "at": datetime(2026, 8, 25, tzinfo=UTC)},
                ],
                "platform_run": [{"id": "run-a"}],
            },
            "tenant-b": {"resource": [{"id": 3}], "platform_run": [{"id": "run-b"}]},
        }
    )
    restored = _manifest(
        {
            "tenant-b": {"platform_run": [{"id": "run-b"}], "resource": [{"id": 3}]},
            "tenant-a": {
                "platform_run": [{"id": "run-a"}],
                "resource": [
                    {"id": 1, "at": "2026-08-25T00:00:00+00:00"},
                    {"id": 2, "at": "2026-08-25T00:00:00+00:00"},
                ],
            },
        }
    )
    compare_recovery_manifests(source, restored)
    assert source.manifest_sha256 == restored.manifest_sha256


def test_manifest_rejects_missing_tenant_table_digest():
    resource = fingerprint_tenant_rows("tenant-a", "resource", [{"id": 1}])
    with pytest.raises(TenantRecoveryContractError, match="every tenant"):
        build_recovery_manifest(("tenant-a", "tenant-b"), (resource,))


def test_visibility_requires_exact_post_restore_tenant_rows():
    manifest = _manifest(
        {
            "tenant-a": {"resource": [{"id": 1}], "platform_run": [{"id": "a"}]},
            "tenant-b": {"resource": [{"id": 2}], "platform_run": [{"id": "b"}]},
        }
    )
    validate_tenant_visibility(
        manifest,
        {
            "tenant-a": {"resource": 1, "platform_run": 1},
            "tenant-b": {"resource": 1, "platform_run": 1},
        },
    )
    with pytest.raises(TenantRecoveryContractError, match="visibility mismatch"):
        validate_tenant_visibility(
            manifest,
            {
                "tenant-a": {"resource": 2, "platform_run": 1},
                "tenant-b": {"resource": 1, "platform_run": 1},
            },
        )


def test_manifest_difference_fails_closed():
    source = _manifest({"tenant-a": {"resource": [{"id": 1}], "platform_run": []}})
    restored = _manifest({"tenant-a": {"resource": [{"id": 2}], "platform_run": []}})
    with pytest.raises(TenantRecoveryContractError, match="differs"):
        compare_recovery_manifests(source, restored)
