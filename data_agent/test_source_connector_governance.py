"""Tests for governed source definitions and connector certification."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_agent.connectors import BaseConnector
from data_agent.connectors import database as database_connector_module
from data_agent.connectors.database import (
    _connection_url,
    _governed_read_query,
    _read_only_sql,
    _runtime_query_request,
)
from data_agent.source_connector_governance import (
    CapabilityOperation,
    CapabilityStatus,
    CertificationStatus,
    CredentialAuthType,
    CredentialReference,
    DiscoveredResource,
    DiscoverySnapshot,
    MappingCredentialResolver,
    ProfileField,
    SourceConnectorKind,
    SourceDefinition,
    certify_source_connector,
    detect_schema_drift,
)


class _FakeConnector(BaseConnector):
    SOURCE_TYPE = "database"

    def __init__(self, *, fail_health: bool = False, secret: str = "") -> None:
        self.fail_health = fail_health
        self.secret = secret

    async def health_check(self, endpoint_url: str, auth_config: dict) -> dict:
        if self.fail_health:
            return {
                "health": "error",
                "message": f"connection rejected password={self.secret}",
            }
        return {"health": "healthy", "message": "OK"}

    async def get_capabilities(self, endpoint_url: str, auth_config: dict) -> dict:
        return {}

    async def discover(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict | None = None,
    ) -> dict:
        return {
            "provider": "PostgreSQL",
            "provider_version": "16.14",
            "layers": [
                {
                    "name": "public.demo",
                    "type": "table",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "nullable": False},
                        {"name": "name", "type": "TEXT", "nullable": True},
                    ],
                }
            ],
        }

    async def query(self, *args, **kwargs):
        return [{"id": 1, "name": "Chongqing"}]


def _credential(version: int = 1) -> CredentialReference:
    return CredentialReference(
        credential_id="credential:local-postgres",
        version=version,
        auth_type=CredentialAuthType.BASIC,
        provider="local-secret-store",
    )


def _definition(credential: CredentialReference | None = None) -> SourceDefinition:
    return SourceDefinition(
        source_id="local-postgis-control-ledger",
        version="1.0.0",
        source_kind=SourceConnectorKind.DATABASE,
        endpoint_url="postgresql://127.0.0.1:5433/gis_agent",
        owner_ref="team:data-platform",
        credential_reference=credential or _credential(),
        connector_version="1.0.0",
        query_config={"table": "public.agent_resource"},
    )


def test_source_definition_is_frozen_and_rejects_embedded_credentials() -> None:
    definition = _definition()
    assert len(definition.fingerprint) == 64
    with pytest.raises(ValidationError, match="frozen"):
        definition.endpoint_url = "postgresql://other/db"  # type: ignore[misc]
    document = definition.model_dump(mode="json")
    document["endpoint_url"] = "postgresql://user:secret@localhost/db"
    with pytest.raises(ValidationError, match="must not embed credentials"):
        SourceDefinition.model_validate(document)
    document = definition.model_dump(mode="json")
    document["query_config"]["password"] = "hidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceDefinition.model_validate(document)
    with pytest.raises(ValidationError, match="frozen"):
        definition.query_config.table = "public.other"  # type: ignore[union-attr,misc]


def test_source_definition_rejects_wrong_typed_query_config() -> None:
    document = _definition().model_dump(mode="json")
    document["source_kind"] = "stac"
    document["endpoint_url"] = "https://stac.example.test"
    with pytest.raises(ValidationError, match="incompatible query_config"):
        SourceDefinition.model_validate(document)


def test_database_runtime_credentials_and_read_only_sql_are_fail_closed() -> None:
    connection_url = _connection_url(
        "postgresql://localhost:5432/gis_agent",
        {
            "type": "basic",
            "username": "reader@example.test",
            "password": "p@ss:/word",
        },
    )
    assert "reader%40example.test" in connection_url
    assert "p%40ss%3A%2Fword" in connection_url
    assert _read_only_sql("SELECT 1") == "SELECT 1"
    with pytest.raises(ValueError, match="read-only SELECT"):
        _read_only_sql("DELETE FROM public.demo")
    with pytest.raises(ValueError, match="one read-only"):
        _read_only_sql("SELECT 1; DELETE FROM public.demo")
    bounded = _governed_read_query(
        "SELECT id FROM makani.addresses",
        ("makani",),
        100,
    )
    assert bounded.endswith("LIMIT 100")
    with pytest.raises(ValueError, match="unauthorized schema"):
        _governed_read_query(
            "SELECT id FROM public.addresses",
            ("makani",),
            100,
        )
    with pytest.raises(ValueError, match="schema-qualify"):
        _governed_read_query("SELECT id FROM addresses", ("makani",), 100)
    with pytest.raises(ValueError, match="blocked read-side-effect"):
        _governed_read_query("SELECT pg_sleep(1) FROM makani.addresses", ("makani",), 100)


def test_database_per_request_sql_cannot_override_governance_policy() -> None:
    sql, table, geom_column = _runtime_query_request(
        {
            "allowed_schemas": ["layer"],
            "statement_timeout_ms": 15000,
            "max_rows": 1000,
        },
        {
            "sql": "SELECT status, COUNT(*) FROM layer.st_pipeline GROUP BY status",
            "geom_column": "geom",
            "allowed_schemas": ["public"],
            "max_rows": 999999,
        },
    )

    assert sql.startswith("SELECT status")
    assert table == ""
    assert geom_column == "geom"


def test_database_level_source_requires_metadata_only_schema_scope() -> None:
    definition = SourceDefinition(
        source_id="abu-dhabi-liveability",
        version="1.0.0",
        source_kind=SourceConnectorKind.DATABASE,
        endpoint_url="postgresql://192.0.2.10:5444/liveability_data",
        owner_ref="team:data-platform",
        credential_reference=_credential(),
        connector_version="1.0.0",
        query_config={
            "allowed_schemas": ["makani"],
            "discovery_mode": "metadata_only",
        },
    )
    assert definition.query_config.allowed_schemas == ("makani",)
    with pytest.raises(ValidationError, match="requires table or allowed_schemas"):
        SourceDefinition.model_validate(
            {
                **definition.model_dump(mode="json"),
                "query_config": {"discovery_mode": "metadata_only"},
            }
        )


@pytest.mark.asyncio
async def test_database_governed_discovery_is_scoped_to_definition_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_capabilities(
        endpoint_url: str,
        auth_config: dict,
        *,
        target_table: str | None = None,
        allowed_schemas: tuple[str, ...] = (),
        discovery_limit: int = 5000,
        statement_timeout_ms: int = 15_000,
        lock_timeout_ms: int = 2_000,
    ) -> dict:
        calls.append(
            (
                endpoint_url,
                auth_config,
                target_table,
                allowed_schemas,
                discovery_limit,
                statement_timeout_ms,
                lock_timeout_ms,
            )
        )
        return {"layers": [{"name": target_table}], "truncated": False}

    monkeypatch.setattr(
        database_connector_module,
        "_database_capabilities",
        fake_capabilities,
    )
    connector = database_connector_module.DatabaseConnector()
    result = await connector.discover(
        "postgresql://localhost/gis_agent",
        {"type": "none"},
        {"table": "governed.source_table"},
    )
    assert result["layers"] == [{"name": "governed.source_table"}]
    assert calls == [
        (
            "postgresql://localhost/gis_agent",
            {"type": "none"},
            "governed.source_table",
            (),
            5000,
            15_000,
            2_000,
        )
    ]


@pytest.mark.asyncio
async def test_metadata_only_database_certification_never_queries_source_rows() -> None:
    class MetadataOnlyConnector(_FakeConnector):
        async def discover(self, *args, **kwargs):
            return {
                "provider": "PostgreSQL",
                "provider_version": "16.14; PostGIS 3.5",
                "layers": [
                    {
                        "name": "makani.addresses",
                        "type": "table",
                        "columns": [
                            {"name": "id", "type": "BIGINT", "nullable": False},
                            {
                                "name": "geom",
                                "type": "geometry(POINT,EPSG:4326)",
                                "nullable": True,
                            },
                        ],
                        "primary_key": ["id"],
                        "estimated_record_count": 42,
                    }
                ],
            }

        async def query(self, *args, **kwargs):
            raise AssertionError("metadata-only certification must not query rows")

    definition = SourceDefinition(
        source_id="abu-dhabi-liveability",
        version="1.0.0",
        source_kind=SourceConnectorKind.DATABASE,
        endpoint_url="postgresql://192.0.2.10:5444/liveability_data",
        owner_ref="team:data-platform",
        credential_reference=_credential(),
        connector_version="1.0.0",
        query_config={
            "allowed_schemas": ["makani"],
            "discovery_mode": "metadata_only",
        },
    )
    resolver = MappingCredentialResolver(
        {("credential:local-postgres", 1): {"type": "basic", "username": "u", "password": "p"}}
    )
    report = await certify_source_connector(
        definition,
        resolver,
        connector=MetadataOnlyConnector(),
    )
    assert report.status is CertificationStatus.PASSED
    assert report.profile and report.profile.metadata_only
    assert report.profile.resource_count == 1
    assert "no source rows sampled" in report.capabilities[2].message


@pytest.mark.asyncio
async def test_certification_records_all_verified_operations_and_is_idempotent() -> None:
    definition = _definition()
    resolver = MappingCredentialResolver(
        {("credential:local-postgres", 1): {"type": "basic", "username": "u", "password": "p"}}
    )
    at = datetime(2026, 8, 1, tzinfo=UTC)
    first = await certify_source_connector(
        definition,
        resolver,
        connector=_FakeConnector(),
        certified_at=at,
    )
    second = await certify_source_connector(
        definition,
        resolver,
        connector=_FakeConnector(),
        certified_at=at,
    )
    assert first.status is CertificationStatus.PASSED
    assert [capability.operation for capability in first.capabilities] == list(CapabilityOperation)
    assert all(capability.status is CapabilityStatus.PASSED for capability in first.capabilities)
    assert first.discovery and first.profile
    assert first.discovery.fingerprint == second.discovery.fingerprint
    assert first.profile.fingerprint == second.profile.fingerprint
    assert first.fingerprint == second.fingerprint


@pytest.mark.asyncio
async def test_failed_credentials_are_redacted_and_fail_closed() -> None:
    secret = "must-never-appear"
    definition = _definition()
    resolver = MappingCredentialResolver(
        {("credential:local-postgres", 1): {"type": "basic", "username": "u", "password": secret}}
    )
    report = await certify_source_connector(
        definition,
        resolver,
        connector=_FakeConnector(fail_health=True, secret=secret),
    )
    payload = report.model_dump_json()
    assert report.status is CertificationStatus.FAILED
    assert report.capabilities[0].status is CapabilityStatus.FAILED
    assert all(
        capability.status is CapabilityStatus.NOT_EVALUATED
        for capability in report.capabilities[1:]
    )
    assert secret not in payload
    assert "[REDACTED]" in payload


@pytest.mark.asyncio
async def test_missing_credential_reference_fails_without_resolver_details() -> None:
    report = await certify_source_connector(
        _definition(),
        MappingCredentialResolver({}),
        connector=_FakeConnector(),
    )
    assert report.status is CertificationStatus.FAILED
    payload = report.model_dump_json()
    assert "credential reference could not be resolved" in payload
    assert "KeyError" not in payload


def test_credential_rotation_changes_only_the_reference_identity() -> None:
    first = _definition(_credential(1))
    second = _definition(_credential(2))
    assert first.credential_reference.fingerprint != second.credential_reference.fingerprint
    assert first.fingerprint != second.fingerprint
    assert "password" not in first.model_dump_json()


def test_schema_drift_detects_breaking_and_additive_changes() -> None:
    old = DiscoverySnapshot(
        provider="PostgreSQL",
        provider_version="16.14",
        resources=(
            DiscoveredResource(
                name="public.demo",
                resource_type="table",
                fields=(
                    ProfileField(name="id", data_type="INTEGER", nullable=False),
                    ProfileField(name="name", data_type="TEXT", nullable=True),
                ),
            ),
        ),
    )
    additive = old.model_copy(
        update={
            "resources": (
                old.resources[0].model_copy(
                    update={
                        "fields": old.resources[0].fields
                        + (ProfileField(name="district", data_type="TEXT", nullable=True),)
                    }
                ),
            )
        }
    )
    additive_event = detect_schema_drift("source-a", old, additive)
    assert additive_event and not additive_event.breaking
    assert additive_event.changed_resources == ("public.demo",)
    assert [change.change_kind for change in additive_event.field_changes] == ["added"]
    assert additive_event.field_changes[0].field_name == "district"

    breaking = old.model_copy(
        update={
            "resources": (
                old.resources[0].model_copy(update={"fields": old.resources[0].fields[:1]}),
            )
        }
    )
    breaking_event = detect_schema_drift("source-a", old, breaking)
    assert breaking_event and breaking_event.breaking
    assert [change.change_kind for change in breaking_event.field_changes] == ["removed"]
    assert len(breaking_event.event_id) == 64


def test_same_schema_with_changed_object_identity_is_not_schema_drift() -> None:
    previous = DiscoverySnapshot(
        provider="MinIO",
        provider_version="S3-compatible",
        resources=(
            DiscoveredResource(
                name="catalog/item.json",
                resource_type="object",
                provider_version_token="etag-a",
            ),
        ),
    )
    current = previous.model_copy(
        update={
            "resources": (
                previous.resources[0].model_copy(update={"provider_version_token": "etag-b"}),
            )
        }
    )
    assert detect_schema_drift("source-a", previous, current) is None
