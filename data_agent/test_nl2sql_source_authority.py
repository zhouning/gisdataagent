from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.nl2sql_source_authority import (
    NL2SQLSourceAdmissionError,
    NL2SQLSourceAuthority,
    NL2SQLSourceBinding,
)
from data_agent.platform_contracts import ResourceVersion, SubjectContext, SubjectType


TENANT = "nl2sql-governance"
VERSION_ID = UUID("00000000-0000-4000-8000-000000000601")
NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


def _version(*, immutable: bool = True) -> ResourceVersion:
    return ResourceVersion(
        tenant_id=TENANT,
        resource_urn=f"gda://{TENANT}/dataset/land-parcels",
        resource_version_id=VERSION_ID,
        version_key="sha256-aaaaaaaaaaaa",
        content_sha256="a" * 64,
        authority_version_ref={
            "postgis_table": "land_parcels_snapshot",
            "source_mode": "immutable_snapshot" if immutable else "mutable_view",
        },
        created_by="workload:ingestion-provider",
        created_at=NOW,
    )


def _subject() -> SubjectContext:
    return SubjectContext(
        tenant_id=TENANT,
        subject_id="operator-a",
        subject_type=SubjectType.HUMAN,
        roles=("platform_operator",),
        purpose="activate governed NL2SQL source binding",
    )


def test_binding_is_deterministic_and_binds_resource_version_evidence() -> None:
    first = NL2SQLSourceBinding.create(
        tenant_id=TENANT,
        semantic_source_name="land_parcels_snapshot",
        execution_engine="postgis",
        physical_locator="land_parcels_snapshot",
        source_mode="immutable_snapshot",
        resource_version=_version(),
    )
    replay = NL2SQLSourceBinding.create(
        tenant_id=TENANT,
        semantic_source_name="land_parcels_snapshot",
        execution_engine="postgis",
        physical_locator="land_parcels_snapshot",
        source_mode="immutable_snapshot",
        resource_version=_version(),
    )

    assert replay == first
    assert first.registered_by == "workload:ingestion-provider"
    assert first.registered_at == NOW

    payload = first.model_dump(mode="json", by_alias=True)
    payload["physical_locator"] = "other_table"
    with pytest.raises(ValidationError, match="fingerprint"):
        NL2SQLSourceBinding.model_validate(payload)


def test_activation_cannot_upgrade_mutable_resource_evidence_to_snapshot() -> None:
    version = _version(immutable=False)
    binding = NL2SQLSourceBinding.create(
        tenant_id=TENANT,
        semantic_source_name="land_parcels_snapshot",
        execution_engine="postgis",
        physical_locator="land_parcels_snapshot",
        source_mode="immutable_snapshot",
        resource_version=version,
    )

    class FakeGateway:
        def get_resource_version(self, tenant_id, resource_version_id):
            assert tenant_id == TENANT
            assert resource_version_id == VERSION_ID
            return version

    authority = NL2SQLSourceAuthority(gateway=FakeGateway())
    with pytest.raises(NL2SQLSourceAdmissionError, match="does not attest"):
        authority.activate(binding, _subject())


def test_activation_requires_authoritative_physical_locator() -> None:
    version = _version()
    binding = NL2SQLSourceBinding.create(
        tenant_id=TENANT,
        semantic_source_name="other_table",
        execution_engine="postgis",
        physical_locator="other_table",
        source_mode="immutable_snapshot",
        resource_version=version,
    )

    class FakeGateway:
        def get_resource_version(self, tenant_id, resource_version_id):
            return version

    authority = NL2SQLSourceAuthority(gateway=FakeGateway())
    with pytest.raises(NL2SQLSourceAdmissionError, match="physical locator"):
        authority.activate(binding, _subject())


def test_migration_declares_tenant_rls_and_gateway_recorder() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).parent
        / "migrations"
        / "157_nl2sql_source_binding_authority.sql"
    ).read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "app.current_tenant" in sql
    assert "activate_nl2sql_source_binding" in sql
    assert "gda_control_gateway" in sql
