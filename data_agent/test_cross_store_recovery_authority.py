from __future__ import annotations

import os
from dataclasses import replace

import pytest
from sqlalchemy import create_engine

from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.platform_runtime.cross_store_recovery import (
    CrossStoreRecoveryContractError,
    build_cross_store_recovery_binding,
)
from data_agent.platform_runtime.cross_store_recovery_authority import (
    CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION,
    CrossStoreRecoveryAuthorityConfigurationError,
    CrossStoreRecoveryAuthorityForbiddenError,
    CrossStoreRecoveryAuthorityValidationError,
    PostgresCrossStoreRecoveryBindingAuthority,
)
from data_agent.platform_runtime.object_recovery import (
    TenantObjectDigest,
    build_object_recovery_manifest,
    sha256_bytes,
)
from data_agent.platform_runtime.tenant_recovery import (
    build_recovery_manifest,
    fingerprint_tenant_rows,
)

TENANTS = {"tenant-a": "tenants/tenant-a/", "tenant-b": "tenants/tenant-b/"}


def _binding(
    source_ref: str = "gda://tenant-a/data_product/source/v1",
    source_content_sha256: str = "a" * 64,
):
    control = build_recovery_manifest(
        tuple(TENANTS),
        tuple(
            fingerprint_tenant_rows(tenant, "resource", [{"source": tenant}])
            for tenant in TENANTS
        ),
    )
    objects = build_object_recovery_manifest(
        TENANTS,
        tuple(
            TenantObjectDigest(
                tenant_id=tenant,
                prefix=prefix,
                key=f"{prefix}roads.json",
                size_bytes=1,
                etag=f"etag-{tenant}",
                version_id=f"version-{tenant}",
                sha256=sha256_bytes(b"x"),
            )
            for tenant, prefix in TENANTS.items()
        ),
    )
    return build_cross_store_recovery_binding(
        control,
        objects,
        source_resource_version_ref=source_ref,
        source_content_sha256=source_content_sha256,
    )


def test_migration_exposes_only_controlled_append_path() -> None:
    migration = CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION.read_text(
        encoding="utf-8"
    )
    assert "cross_store_recovery_binding_history" in migration
    assert "cross_store_recovery_binding_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "GRANT INSERT" not in migration
    assert "source already has a different binding" in migration


def test_repository_requires_postgresql() -> None:
    authority = PostgresCrossStoreRecoveryBindingAuthority(
        "tenant-a", create_engine("sqlite://")
    )
    with pytest.raises(
        CrossStoreRecoveryAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        authority.current("a" * 64)


def test_repository_rejects_binding_outside_tenant_before_database_access() -> None:
    authority = PostgresCrossStoreRecoveryBindingAuthority("tenant-c")
    with pytest.raises(
        CrossStoreRecoveryAuthorityForbiddenError,
        match="does not cover",
    ):
        authority.append(_binding())


def test_stored_binding_parser_rejects_tampered_document() -> None:
    binding = _binding()
    tampered = replace(binding, binding_sha256="b" * 64)
    with pytest.raises(CrossStoreRecoveryContractError):
        tampered.validate()


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_binding_is_idempotent_restart_isolated_and_drift_closed() -> None:
    binding = _binding()
    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            for migration in (
                "092_platform_control_ledger.sql",
                "094_platform_control_gateway.sql",
            ):
                connection.exec_driver_sql(
                    (
                        CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION.parent
                        / migration
                    ).read_text(encoding="utf-8").replace("%", "%%")
                )
            connection.exec_driver_sql(
                CROSS_STORE_RECOVERY_BINDING_AUTHORITY_MIGRATION.read_text(
                    encoding="utf-8"
                ).replace("%", "%%")
            )

        authority_a = PostgresCrossStoreRecoveryBindingAuthority(
            "tenant-a", sandbox.runtime_engine
        )
        authority_b = PostgresCrossStoreRecoveryBindingAuthority(
            "tenant-b", sandbox.runtime_engine
        )
        assert authority_a.append(binding) == binding
        assert authority_a.append(binding) == binding
        assert authority_b.append(binding) == binding

        # A new repository instance represents a process restart; it must read
        # the same durable identity instead of relying on in-memory state.
        restarted_a = PostgresCrossStoreRecoveryBindingAuthority(
            "tenant-a", sandbox.runtime_engine
        )
        assert restarted_a.current(binding.binding_sha256) == binding
        assert restarted_a.history(binding.source_resource_version_ref) == (binding,)
        assert (
            PostgresCrossStoreRecoveryBindingAuthority(
                "tenant-c", sandbox.runtime_engine
            ).current(binding.binding_sha256)
            is None
        )

        drifted = _binding(source_content_sha256="b" * 64)
        with pytest.raises(
            CrossStoreRecoveryAuthorityValidationError,
            match="different binding|evidence|conflict",
        ):
            authority_a.append(drifted)
