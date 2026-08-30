import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.data_architecture_ledger import (
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ResourceVersionArchitectureBinding,
    SchemaVersion,
    architecture_binding_fingerprint,
    data_contract_version_fingerprint,
    physical_location_fingerprint,
    schema_version_fingerprint,
)
from data_agent.platform_contracts import Resource, ResourceVersion
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "113_data_architecture_version_authority.sql",
    )
)


def _architecture(
    tenant_id: str,
    resource_version_id,
    *,
    now: datetime,
) -> DataArchitectureRegistration:
    schema_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "schema_format": "iceberg",
        "authority_system": "gravitino",
        "authority_namespace": "metalake/catalog",
        "authority_object_id": f"geo.resource_{resource_version_id.hex[:8]}",
        "authority_version_ref": "schema-id:7",
    }
    schema = SchemaVersion(
        schema_version_id=uuid4(),
        schema_sha256=schema_version_fingerprint(**schema_values),
        created_by="workload:metadata-harvester",
        created_at=now,
        **schema_values,
    )
    contract_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "contract_kind": "data_product_input",
        "enforcement_mode": "required",
        "authority_system": "openmetadata",
        "authority_namespace": "table",
        "authority_object_id": str(uuid4()),
        "authority_version_ref": "version:11",
    }
    contract = DataContractVersion(
        data_contract_version_id=uuid4(),
        contract_sha256=data_contract_version_fingerprint(**contract_values),
        created_by="workload:governance-harvester",
        created_at=now,
        **contract_values,
    )
    location_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "location_kind": "iceberg_table",
        "provider_system": "iceberg_rest",
        "provider_namespace": "geo",
        "provider_locator": f"iceberg://metalake/catalog/geo/{resource_version_id}",
        "snapshot_ref": "918273645",
        "revision_ref": "metadata.json:7",
        "checksum_algorithm": "sha256",
        "content_checksum": resource_version_id.hex * 2,
    }
    location = PhysicalLocation(
        physical_location_id=uuid4(),
        location_sha256=physical_location_fingerprint(**location_values),
        created_by="workload:provider-harvester",
        created_at=now,
        **location_values,
    )
    binding_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "schema_version_id": schema.schema_version_id,
        "data_contract_version_id": contract.data_contract_version_id,
        "physical_location_id": location.physical_location_id,
    }
    binding = ResourceVersionArchitectureBinding(
        binding_sha256=architecture_binding_fingerprint(**binding_values),
        bound_by="workload:architecture-controller",
        bound_at=now,
        **binding_values,
    )
    return DataArchitectureRegistration(
        schema_version=schema,
        data_contract_version=contract,
        physical_location=location,
        binding=binding,
    )


def _register_resource_version(
    gateway: PlatformGateway,
    tenant_id: str,
    resource_version_id,
    *,
    now: datetime,
) -> None:
    resource_urn = f"gda://{tenant_id}/dataset/resource-{resource_version_id.hex[:8]}"
    gateway.register_resource(
        Resource(
            tenant_id=tenant_id,
            resource_urn=resource_urn,
            resource_kind="dataset",
            authority_system="iceberg",
            authority_locator=f"geo.resource_{resource_version_id.hex[:8]}",
            owner_ref="team:data-platform",
        )
    )
    gateway.register_resource_version(
        ResourceVersion(
            tenant_id=tenant_id,
            resource_urn=resource_urn,
            resource_version_id=resource_version_id,
            version_key="snapshot-1",
            content_sha256=resource_version_id.hex * 2,
            authority_version_ref={"snapshot": "918273645"},
            created_by="workload:source-sync",
            created_at=now,
        )
    )


def _assert_db_rejected(connection, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.exec_driver_sql(statement)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_architecture_authority_is_tenant_scoped_immutable_and_complete(
    isolated_postgres_url: str,
):
    engine = create_engine(isolated_postgres_url)
    tenant_a = f"arch-a-{uuid4().hex[:8]}"
    tenant_b = f"arch-b-{uuid4().hex[:8]}"
    now = datetime.now(UTC).replace(microsecond=0)
    version_a = uuid4()
    version_b = uuid4()
    try:
        with engine.begin() as connection:
            if not connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one():
                pytest.skip("architecture migration test requires a PostgreSQL superuser")
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))

        gateway = PlatformGateway(engine)
        _register_resource_version(gateway, tenant_a, version_a, now=now)
        _register_resource_version(gateway, tenant_b, version_b, now=now)
        architecture_a = _architecture(tenant_a, version_a, now=now)
        architecture_b = _architecture(tenant_b, version_b, now=now)

        empty = gateway.get_resource_version_architecture(tenant_a, version_a)
        assert empty.architecture_ready is False
        assert empty.missing_components == (
            "schema_version",
            "data_contract_version",
            "physical_location",
            "architecture_binding",
        )

        assert gateway.register_schema_version(architecture_a.schema_version).created
        assert not gateway.register_schema_version(architecture_a.schema_version).created
        partial = gateway.get_resource_version_architecture(tenant_a, version_a)
        assert partial.architecture_ready is False
        assert partial.missing_components == (
            "data_contract_version",
            "physical_location",
            "architecture_binding",
        )
        with pytest.raises(GatewayConflictError, match="different immutable binding"):
            gateway.register_schema_version(
                architecture_a.schema_version.model_copy(
                    update={"created_by": "workload:different-harvester"}
                )
            )

        assert gateway.register_data_contract_version(
            architecture_a.data_contract_version
        ).created
        assert gateway.register_physical_location(
            architecture_a.physical_location
        ).created
        unbound = gateway.get_resource_version_architecture(tenant_a, version_a)
        assert unbound.architecture_ready is False
        assert unbound.missing_components == ("architecture_binding",)
        assert gateway.bind_resource_version_architecture(
            architecture_a.binding
        ).created
        assert not gateway.bind_resource_version_architecture(
            architecture_a.binding
        ).created
        ready = gateway.get_resource_version_architecture(tenant_a, version_a)
        assert ready.architecture_ready is True
        assert ready.missing_components == ()
        assert ready.physical_location.provider_system == "iceberg_rest"
        assert ready.physical_location.snapshot_ref == "918273645"

        assert gateway.register_schema_version(architecture_b.schema_version).created
        assert gateway.register_data_contract_version(
            architecture_b.data_contract_version
        ).created
        assert gateway.register_physical_location(
            architecture_b.physical_location
        ).created
        cross_values = architecture_b.binding.model_dump(
            exclude={"binding_sha256", "data_contract_version_id"}
        )
        cross_values["data_contract_version_id"] = (
            architecture_a.data_contract_version.data_contract_version_id
        )
        cross_values["binding_sha256"] = architecture_binding_fingerprint(
            tenant_id=tenant_b,
            resource_version_id=version_b,
            schema_version_id=architecture_b.schema_version.schema_version_id,
            data_contract_version_id=(
                architecture_a.data_contract_version.data_contract_version_id
            ),
            physical_location_id=architecture_b.physical_location.physical_location_id,
        )
        with pytest.raises(GatewayValidationError):
            gateway.bind_resource_version_architecture(
                ResourceVersionArchitectureBinding(**cross_values)
            )
        assert gateway.bind_resource_version_architecture(architecture_b.binding).created
        assert not gateway.register_resource_version_architecture(architecture_b).created

        with pytest.raises(GatewayNotFoundError):
            gateway.get_resource_version_architecture(tenant_a, version_b)

        with engine.connect() as connection:
            with connection.begin():
                _assert_db_rejected(
                    connection,
                    "UPDATE gda_control.schema_version SET created_by = 'tampered' "
                    "WHERE schema_version_id = "
                    f"'{architecture_a.schema_version.schema_version_id}'",
                )
                _assert_db_rejected(
                    connection,
                    "DELETE FROM gda_control.physical_location "
                    "WHERE physical_location_id = "
                    f"'{architecture_a.physical_location.physical_location_id}'",
                )
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                _assert_db_rejected(
                    connection,
                    "INSERT INTO gda_control.schema_version ("
                    "tenant_id, schema_version_id, resource_version_id, "
                    "schema_format, authority_system, authority_namespace, "
                    "authority_object_id, authority_version_ref, schema_sha256, "
                    "created_by, created_at) VALUES ("
                    f"'{tenant_b}', '{uuid4()}', '{version_b}', 'iceberg', "
                    "'gravitino', 'metalake/catalog', 'geo.cross_tenant', "
                    "'schema-id:9', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'attacker', now())",
                )

        with engine.begin() as connection:
            flags = connection.execute(
                text(
                    "SELECT bool_and(relrowsecurity AND relforcerowsecurity) "
                    "FROM pg_class WHERE oid IN ("
                    "'gda_control.schema_version'::regclass, "
                    "'gda_control.data_contract_version'::regclass, "
                    "'gda_control.physical_location'::regclass, "
                    "'gda_control.resource_version_architecture_binding'::regclass)"
                )
            ).scalar_one()
            assert flags is True
            assert connection.exec_driver_sql(
                "SELECT has_table_privilege('gda_control_gateway', "
                "'gda_control.schema_version', 'SELECT,INSERT')"
            ).scalar_one()
            assert not connection.exec_driver_sql(
                "SELECT has_table_privilege('gda_control_gateway', "
                "'gda_control.schema_version', 'UPDATE,DELETE')"
            ).scalar_one()
    finally:
        engine.dispose()
