from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent import migration_runner, platform_contracts as contracts


TENANT = "tenant-a"
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000010")
RUN_ID = UUID("00000000-0000-4000-8000-000000000020")
SOURCE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000030")
TARGET_VERSION_ID = UUID("00000000-0000-4000-8000-000000000040")
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _subject(**overrides):
    values = {
        "tenant_id": TENANT,
        "subject_id": "user-1",
        "subject_type": "human",
        "roles": ("analyst", "data_steward"),
        "purpose": "publish governed land-use data",
        "trace_id": "trace-1",
    }
    values.update(overrides)
    return contracts.SubjectContext(**values)


def _definition(**overrides):
    values = {
        "tenant_id": TENANT,
        "definition_urn": contracts.build_resource_urn(
            TENANT, "definition", "land-use-publish"
        ),
        "definition_version_id": DEFINITION_ID,
        "orchestration_class": "dataops",
        "capability_id": "land_use.publish",
        "portability_class": "portable",
        "definition_document": {"tasks": [{"id": "publish"}]},
        "input_contract": {"type": "object", "required": ["source"]},
        "output_contract": {"type": "object", "required": ["product"]},
    }
    values.update(overrides)
    values.setdefault(
        "definition_sha256",
        contracts.platform_definition_fingerprint(
            orchestration_class=values["orchestration_class"],
            capability_id=values["capability_id"],
            portability_class=values["portability_class"],
            definition_document=values["definition_document"],
            input_contract=values["input_contract"],
            output_contract=values["output_contract"],
        ),
    )
    return contracts.PlatformDefinitionVersion(**values)


def _run(**overrides):
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "orchestration_class": "dataops",
        "subject_context": _subject(),
        "input_bindings": (
            {
                "binding_name": "source",
                "resource_version_id": SOURCE_VERSION_ID,
                "semantic_type": "gis.land_use.parcel_set",
            },
        ),
        "idempotency_key": "manual:land-use-publish:2026-07-24",
        "config_fingerprint": SHA_A,
        "status": "accepted",
        "state_version": 0,
        "submitted_at": NOW,
    }
    values.update(overrides)
    return contracts.PlatformRun(**values)


def test_resource_urn_build_parse_and_canonical_rejection():
    urn = contracts.build_resource_urn(
        TENANT, "dataset", "land-use-parcels-v1"
    )

    assert urn == "gda://tenant-a/dataset/land-use-parcels-v1"
    assert contracts.parse_resource_urn(urn) == {
        "tenant_id": TENANT,
        "resource_kind": "dataset",
        "resource_id": "land-use-parcels-v1",
    }
    with pytest.raises(contracts.PlatformContractError):
        contracts.build_resource_urn("Tenant-A", "dataset", "parcels")
    with pytest.raises(contracts.PlatformContractError):
        contracts.parse_resource_urn("gda://tenant-a/dataset/../secret")


def test_resource_version_requires_tenant_and_predecessor_consistency():
    urn = contracts.build_resource_urn(TENANT, "dataset", "parcels")
    version = contracts.ResourceVersion(
        tenant_id=TENANT,
        resource_urn=urn,
        resource_version_id=SOURCE_VERSION_ID,
        version_key="snapshot-20260724",
        content_sha256=SHA_A,
        authority_version_ref={"iceberg_snapshot_id": 42},
        created_by="workload:dataops",
        created_at=NOW,
    )

    assert version.resource_urn == urn
    with pytest.raises(ValidationError, match="tenant must match"):
        contracts.ResourceVersion(
            **{
                **version.model_dump(),
                "tenant_id": "tenant-b",
            }
        )
    with pytest.raises(ValidationError, match="own predecessor"):
        contracts.ResourceVersion(
            **{
                **version.model_dump(),
                "predecessor_version_id": SOURCE_VERSION_ID,
            }
        )


def test_definition_hash_covers_document_and_contracts():
    definition = _definition()

    assert definition.definition_sha256 == contracts.platform_definition_fingerprint(
        orchestration_class=definition.orchestration_class,
        capability_id=definition.capability_id,
        portability_class=definition.portability_class,
        definition_document=definition.definition_document,
        input_contract=definition.input_contract,
        output_contract=definition.output_contract,
    )
    with pytest.raises(ValidationError, match="does not match"):
        _definition(
            definition_document={"tasks": [{"id": "changed"}]},
            definition_sha256=SHA_A,
        )


def test_contract_fingerprint_is_canonical_and_change_sensitive():
    first = _definition(
        definition_document={"b": 2, "a": {"y": 2, "x": 1}}
    )
    second = _definition(
        definition_document={"a": {"x": 1, "y": 2}, "b": 2}
    )
    changed = _definition(
        definition_document={"a": {"x": 1, "y": 3}, "b": 2}
    )

    assert first.contract_fingerprint() == second.contract_fingerprint()
    assert first.contract_fingerprint() != changed.contract_fingerprint()


def test_platform_run_freezes_tenant_bindings_and_initial_state():
    run = _run()

    assert run.subject_context.roles == ("analyst", "data_steward")
    assert run.input_bindings[0].resource_version_id == SOURCE_VERSION_ID
    with pytest.raises(ValidationError, match="tenant must match"):
        _run(subject_context=_subject(tenant_id="tenant-b"))
    with pytest.raises(ValidationError, match="binding names must be unique"):
        _run(input_bindings=(_run().input_bindings[0], _run().input_bindings[0]))
    with pytest.raises(ValidationError, match="state version zero"):
        _run(status="running", state_version=0)
    with pytest.raises(ValidationError, match="state version zero"):
        _run(status="accepted", state_version=1)


def test_run_transition_graph_rejects_terminal_and_skip_transitions():
    contracts.validate_run_transition("accepted", "dispatching")
    contracts.validate_run_transition("running", "succeeded")
    contracts.validate_run_transition("reconciling", "running")

    with pytest.raises(contracts.PlatformContractError):
        contracts.validate_run_transition("accepted", "succeeded")
    with pytest.raises(contracts.PlatformContractError):
        contracts.validate_run_transition("succeeded", "running")
    with pytest.raises(contracts.PlatformContractError):
        contracts.validate_run_transition("running", "running")


def test_run_event_sequence_zero_and_transitions_share_state_contract():
    initial = contracts.PlatformRunEvent(
        tenant_id=TENANT,
        event_id=UUID("00000000-0000-4000-8000-000000000050"),
        run_id=RUN_ID,
        sequence_no=0,
        to_status="accepted",
        actor_subject="user-1",
        reason="submitted",
        occurred_at=NOW,
    )
    assert initial.from_status is None

    with pytest.raises(ValidationError):
        contracts.PlatformRunEvent(
            **{
                **initial.model_dump(),
                "sequence_no": 1,
                "from_status": "accepted",
                "to_status": "succeeded",
            }
        )


def test_artifact_rejects_credentials_signed_urls_and_relative_files():
    base = {
        "tenant_id": TENANT,
        "artifact_id": UUID("00000000-0000-4000-8000-000000000060"),
        "artifact_key": "published-parcels",
        "artifact_role": "output",
        "storage_uri": "s3://land-use/products/parcels.parquet",
        "media_type": "application/vnd.apache.parquet",
        "content_sha256": SHA_B,
        "size_bytes": 4096,
        "run_id": RUN_ID,
        "resource_version_id": TARGET_VERSION_ID,
        "created_by": "workload:dataops",
        "created_at": NOW,
    }
    artifact = contracts.Artifact(**base)
    assert artifact.storage_uri.startswith("s3://")
    assert contracts.Artifact(
        **{**base, "storage_uri": "file:///var/lib/gda/artifact.parquet"}
    ).storage_uri.startswith("file:///")

    for unsafe_uri in (
        "s3://access:secret@bucket/key",
        "https://objects.example/key?signature=secret",
        "file://relative/path",
    ):
        with pytest.raises(ValidationError):
            contracts.Artifact(**{**base, "storage_uri": unsafe_uri})


def test_lineage_rejects_self_edges_and_naive_timestamps():
    base = {
        "tenant_id": TENANT,
        "lineage_event_id": UUID("00000000-0000-4000-8000-000000000070"),
        "event_type": "derive",
        "source_resource_version_id": SOURCE_VERSION_ID,
        "target_resource_version_id": TARGET_VERSION_ID,
        "producer": "gda-lineage-emitter",
        "event_sha256": SHA_A,
        "run_id": RUN_ID,
        "occurred_at": NOW,
    }
    assert contracts.LineageEvent(**base).event_type.value == "derive"
    with pytest.raises(ValidationError, match="must differ"):
        contracts.LineageEvent(
            **{**base, "target_resource_version_id": SOURCE_VERSION_ID}
        )
    with pytest.raises(ValidationError, match="timezone"):
        contracts.LineageEvent(
            **{**base, "occurred_at": datetime(2026, 7, 24, 12, 0)}
        )


def test_contracts_forbid_unknown_fields_and_export_stable_json_schemas():
    with pytest.raises(ValidationError, match="Extra inputs"):
        contracts.SubjectContext(
            **{
                **_subject().model_dump(),
                "admin_override": True,
            }
        )

    schemas = contracts.contract_schemas()
    assert set(schemas) == {model.schema_id for model in contracts.CONTRACT_MODELS}
    assert schemas["platform_run"]["additionalProperties"] is False


def test_control_ledger_contract_and_migration_catalog_are_valid():
    report = contracts.build_contract_report()
    migrations = migration_runner.discover_migrations()
    migration = next(
        item for item in migrations
        if item["migration_id"] == "092_platform_control_ledger"
    )

    assert report["status"] == "valid"
    assert report["contract_count"] == 9
    assert report["migration"]["sha256"] == migration["checksum"]
    assert migrations[-1]["migration_id"] == "092_platform_control_ledger"


def test_sql_contract_has_tenant_fks_rls_append_only_and_no_legacy_backfill():
    sql = Path(contracts.CONTROL_LEDGER_MIGRATION).read_text(encoding="utf-8")

    assert "FOREIGN KEY (tenant_id, resource_version_id)" in sql
    assert "platform_run_input_binding" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "transition_platform_run" in sql
    assert "SECURITY DEFINER" in sql
    assert "p_tenant_id TEXT" in sql
    assert "uq_gda_resource_version_resource_id" in sql
    assert "reject_immutable_mutation" in sql
    assert "INSERT INTO gda_control.resource" not in sql
    for legacy_table in (
        "agent_data_assets",
        "agent_asset_versions",
        "agent_workflows",
        "agent_workflow_runs",
        "agent_asset_lineage",
    ):
        assert legacy_table not in sql
