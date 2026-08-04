from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from data_agent.data_architecture_ledger import (
    DATA_ARCHITECTURE_MIGRATION,
    DataArchitectureRegistration,
    DataContractVersion,
    PhysicalLocation,
    ResourceVersionArchitecture,
    ResourceVersionArchitectureBinding,
    SchemaVersion,
    architecture_binding_fingerprint,
    data_contract_version_fingerprint,
    physical_location_fingerprint,
    schema_version_fingerprint,
)


def _registration() -> DataArchitectureRegistration:
    now = datetime.now(UTC)
    tenant_id = "architecture-test"
    resource_version_id = uuid4()
    schema_values = {
        "tenant_id": tenant_id,
        "resource_version_id": resource_version_id,
        "schema_format": "iceberg",
        "authority_system": "gravitino",
        "authority_namespace": "metalake/catalog",
        "authority_object_id": "geo.parcels",
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
        "authority_object_id": "30000000-0000-4000-8000-000000000001",
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
        "provider_locator": "iceberg://metalake/catalog/geo/parcels",
        "snapshot_ref": "918273645",
        "revision_ref": "metadata.json:7",
        "checksum_algorithm": "sha256",
        "content_checksum": "a" * 64,
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


def test_typed_registration_covers_schema_contract_location_and_binding() -> None:
    registration = _registration()

    assert registration.schema_version.authority_system == "gravitino"
    assert registration.data_contract_version.authority_system == "openmetadata"
    assert registration.physical_location.snapshot_ref == "918273645"
    assert (
        registration.binding.resource_version_id
        == registration.schema_version.resource_version_id
    )


def test_contracts_reject_wrong_fingerprint_and_location_without_revision() -> None:
    registration = _registration()

    with pytest.raises(ValidationError, match="schema_sha256"):
        SchemaVersion.model_validate(
            registration.schema_version.model_dump()
            | {"schema_sha256": "0" * 64}
        )
    location = registration.physical_location.model_dump()
    location.update(snapshot_ref=None, revision_ref=None)
    with pytest.raises(ValidationError, match="snapshot_ref or revision_ref"):
        PhysicalLocation.model_validate(location)


def test_registration_rejects_component_from_another_resource_version() -> None:
    registration = _registration()
    contract = registration.data_contract_version
    other_resource_version_id = uuid4()
    contract_values = contract.model_dump(
        exclude={"contract_sha256", "resource_version_id"}
    )
    contract_values["resource_version_id"] = other_resource_version_id
    contract_values["contract_sha256"] = data_contract_version_fingerprint(
        tenant_id=contract.tenant_id,
        resource_version_id=other_resource_version_id,
        contract_kind=contract.contract_kind,
        enforcement_mode=contract.enforcement_mode,
        authority_system=contract.authority_system,
        authority_namespace=contract.authority_namespace,
        authority_object_id=contract.authority_object_id,
        authority_version_ref=contract.authority_version_ref,
    )

    with pytest.raises(ValidationError, match="one tenant ResourceVersion"):
        DataArchitectureRegistration(
            schema_version=registration.schema_version,
            data_contract_version=DataContractVersion(**contract_values),
            physical_location=registration.physical_location,
            binding=registration.binding,
        )


def test_readiness_cannot_claim_ready_without_complete_binding() -> None:
    registration = _registration()

    with pytest.raises(ValidationError, match="complete binding"):
        ResourceVersionArchitecture(
            tenant_id=registration.binding.tenant_id,
            resource_version_id=registration.binding.resource_version_id,
            architecture_ready=True,
            missing_components=(),
        )
    incomplete = ResourceVersionArchitecture(
        tenant_id=registration.binding.tenant_id,
        resource_version_id=registration.binding.resource_version_id,
        architecture_ready=False,
        missing_components=("architecture_binding",),
        schema_version_record=registration.schema_version,
        data_contract_version_record=registration.data_contract_version,
        physical_location=registration.physical_location,
    )
    assert incomplete.architecture_ready is False


def test_migration_is_rls_scoped_append_only_and_reference_only() -> None:
    sql = DATA_ARCHITECTURE_MIGRATION.read_text(encoding="utf-8")

    for table in (
        "schema_version",
        "data_contract_version",
        "physical_location",
        "resource_version_architecture_binding",
    ):
        assert f"CREATE TABLE IF NOT EXISTS gda_control.{table}" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "reject_immutable_mutation()" in sql
    assert "fk_gda_architecture_binding_schema" in sql
    assert "fk_gda_architecture_binding_contract" in sql
    assert "fk_gda_architecture_binding_location" in sql
    assert "JSONB" not in sql
