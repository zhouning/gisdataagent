from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent import migration_runner
from data_agent import platform_contracts as contracts

TENANT = "tenant-a"
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000010")
RUN_ID = UUID("00000000-0000-4000-8000-000000000020")
SOURCE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000030")
TARGET_VERSION_ID = UUID("00000000-0000-4000-8000-000000000040")
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
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


def test_resource_contract_binds_tenant_kind_and_authority():
    resource = contracts.Resource(
        tenant_id=TENANT,
        resource_urn=contracts.build_resource_urn(TENANT, "dataset", "parcels"),
        resource_kind="dataset",
        authority_system="iceberg",
        authority_locator="geo.parcels",
        owner_ref="team:data-platform",
    )

    assert resource.resource_kind == "dataset"
    with pytest.raises(ValidationError, match="tenant must match"):
        contracts.Resource(
            **{
                **resource.model_dump(),
                "tenant_id": "tenant-b",
            }
        )
    with pytest.raises(ValidationError, match="kind must match"):
        contracts.Resource(
            **{
                **resource.model_dump(),
                "resource_kind": "model",
            }
        )


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


def test_policy_decision_canonicalizes_exact_resource_scope():
    decision = contracts.PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=_run().subject_context,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_ID,
        resource_version_ids=(SOURCE_VERSION_ID, DEFINITION_ID),
        execution_plan_artifact_id=TARGET_VERSION_ID,
        effect="allow",
        policy_version_ref="gda://tenant-a/policy/dataops-dispatch:v1",
        evaluator_subject="workload:policy-evaluator",
        obligations=("retain_evidence", "emit_audit"),
        decided_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert decision.resource_version_ids == (DEFINITION_ID, SOURCE_VERSION_ID)
    assert decision.obligations == ("emit_audit", "retain_evidence")
    with pytest.raises(ValidationError, match="include the definition"):
        contracts.PolicyDecision(
            **{
                **decision.model_dump(),
                "resource_version_ids": (SOURCE_VERSION_ID,),
            }
        )
    with pytest.raises(ValidationError, match="workload identity"):
        contracts.PolicyDecision(
            **{
                **decision.model_dump(),
                "evaluator_subject": "human:operator",
            }
        )


def test_approval_requires_human_identity_and_bounded_expiry():
    approval = contracts.ApprovalRecord(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        policy_decision_artifact_id=TARGET_VERSION_ID,
        policy_decision_sha256=SHA_A,
        verdict="approved",
        approver_subject="human:dataops-approver",
        reason="approved controlled publication",
        decided_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert approval.verdict.value == "approved"
    with pytest.raises(ValidationError, match="human identity"):
        contracts.ApprovalRecord(
            **{
                **approval.model_dump(),
                "approver_subject": "workload:dataops-adapter",
            }
        )


def test_platform_command_requires_consistent_claim_and_completion_state():
    command = contracts.PlatformCommand(
        tenant_id=TENANT,
        command_id=TARGET_VERSION_ID,
        run_id=RUN_ID,
        command_type="dolphinscheduler.dispatch",
        execution_plan_artifact_id=DEFINITION_ID,
        dedupe_key="dispatch:run-1",
        actor_subject="workload:dataops-adapter",
        available_at=NOW,
        created_at=NOW,
    )

    assert command.status.value == "pending"
    with pytest.raises(ValidationError, match="requires an active claim"):
        contracts.PlatformCommand(
            **{
                **command.model_dump(),
                "status": "in_flight",
            }
        )
    with pytest.raises(ValidationError, match="cannot reference"):
        contracts.PlatformCommand(
            **{
                **command.model_dump(),
                "trigger_observation_id": SOURCE_VERSION_ID,
            }
        )


def test_quality_result_and_success_evidence_are_content_bound():
    evidence_artifact_id = UUID("00000000-0000-4000-8000-000000000080")
    quality_result_id = UUID("00000000-0000-4000-8000-000000000090")
    metrics = {"feature_count": 3, "geometry_errors": 0}
    quality_sha256 = contracts.quality_result_fingerprint(
        tenant_id=TENANT,
        run_id=RUN_ID,
        resource_version_id=TARGET_VERSION_ID,
        rule_version_ref="gda://tenant-a/quality-rule/dltb-v1",
        verdict="passed",
        metrics=metrics,
        evidence_artifact_id=evidence_artifact_id,
        evaluated_by="workload:quality-evaluator",
        evaluated_at=NOW,
    )
    quality = contracts.QualityResult(
        tenant_id=TENANT,
        quality_result_id=quality_result_id,
        run_id=RUN_ID,
        resource_version_id=TARGET_VERSION_ID,
        rule_version_ref="gda://tenant-a/quality-rule/dltb-v1",
        verdict="passed",
        metrics=metrics,
        evidence_artifact_id=evidence_artifact_id,
        result_sha256=quality_sha256,
        evaluated_by="workload:quality-evaluator",
        evaluated_at=NOW,
    )
    success_sha256 = contracts.run_success_evidence_fingerprint(
        tenant_id=TENANT,
        run_id=RUN_ID,
        attempt_observation_id=SOURCE_VERSION_ID,
        output_artifact_id=TARGET_VERSION_ID,
        quality_result_id=quality_result_id,
        lineage_event_id=DEFINITION_ID,
    )
    success = contracts.RunSuccessEvidence(
        tenant_id=TENANT,
        run_id=RUN_ID,
        attempt_observation_id=SOURCE_VERSION_ID,
        output_artifact_id=TARGET_VERSION_ID,
        quality_result_id=quality_result_id,
        lineage_event_id=DEFINITION_ID,
        evidence_sha256=success_sha256,
    )

    assert quality.verdict == contracts.QualityVerdict.PASSED
    assert success.evidence_sha256 == success_sha256
    with pytest.raises(ValidationError, match="result_sha256"):
        contracts.QualityResult(
            **{**quality.model_dump(), "metrics": {"feature_count": 2}}
        )
    with pytest.raises(ValidationError, match="workload identity"):
        contracts.QualityResult(
            **{
                **quality.model_dump(),
                "evaluated_by": "human:quality-evaluator",
            }
        )


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


def test_data_incident_is_content_bound_and_has_one_way_remediation():
    incident_id = UUID("00000000-0000-4000-8000-000000000055")
    observation_id = UUID("00000000-0000-4000-8000-000000000056")
    details = {"provider_state": "FAILURE", "workflow_instance_id": 7}
    fingerprint = contracts.data_incident_fingerprint(
        tenant_id=TENANT,
        run_id=RUN_ID,
        dedupe_key=f"cancel-terminal:{observation_id}",
        incident_type="provider_cancel_terminal_mismatch",
        severity="high",
        summary="provider cancellation did not converge",
        trigger_observation_id=observation_id,
        details=details,
        detected_by="workload:dataops-adapter",
        opened_at=NOW,
    )
    incident = contracts.DataIncident(
        tenant_id=TENANT,
        incident_id=incident_id,
        run_id=RUN_ID,
        dedupe_key=f"cancel-terminal:{observation_id}",
        incident_type="provider_cancel_terminal_mismatch",
        severity="high",
        summary="provider cancellation did not converge",
        trigger_observation_id=observation_id,
        details=details,
        incident_sha256=fingerprint,
        detected_by="workload:dataops-adapter",
        opened_at=NOW,
        updated_at=NOW,
    )

    assert incident.status == contracts.IncidentStatus.OPEN
    contracts.validate_incident_transition("open", "acknowledged")
    contracts.validate_incident_transition("acknowledged", "resolved")
    with pytest.raises(contracts.PlatformContractError):
        contracts.validate_incident_transition("resolved", "open")
    with pytest.raises(ValidationError, match="incident_sha256"):
        contracts.DataIncident(
            **{**incident.model_dump(), "details": {"provider_state": "STOP"}}
        )
    with pytest.raises(ValidationError, match="workload identity"):
        contracts.DataIncident(
            **{**incident.model_dump(), "detected_by": "human:operator"}
        )

    resource_values = {
        "tenant_id": TENANT,
        "incident_id": UUID("00000000-0000-4000-8000-000000000057"),
        "run_id": None,
        "subject_resource_urn": f"gda://{TENANT}/service/approval-notification",
        "dedupe_key": "slo-burn:episode-1",
        "incident_type": "slo_error_budget_burn",
        "severity": "critical",
        "summary": "SLO error budget is burning",
        "trigger_observation_id": None,
        "details": {"slo_version_ref": "slo-v1"},
        "detected_by": "workload:slo-alert-ingestor",
        "opened_at": NOW,
        "updated_at": NOW,
    }
    resource_values["incident_sha256"] = contracts.data_incident_fingerprint(
        **{
            key: resource_values[key]
            for key in (
                "tenant_id",
                "run_id",
                "subject_resource_urn",
                "dedupe_key",
                "incident_type",
                "severity",
                "summary",
                "trigger_observation_id",
                "details",
                "detected_by",
                "opened_at",
            )
        }
    )
    resource_incident = contracts.DataIncident(**resource_values)
    assert resource_incident.run_id is None
    with pytest.raises(ValidationError, match="exactly one"):
        contracts.DataIncident(**{**resource_values, "run_id": RUN_ID})
    with pytest.raises(ValidationError, match="exactly one"):
        contracts.DataIncident(
            **{**resource_values, "subject_resource_urn": None}
        )


def test_incident_notification_binds_immutable_event_and_delivery_lease():
    incident_id = UUID("00000000-0000-4000-8000-000000000055")
    event_id = UUID("00000000-0000-4000-8000-000000000057")
    notification_id = UUID("00000000-0000-4000-8000-000000000058")
    details = {"provider_state": "FAILURE"}
    incident = contracts.DataIncident(
        tenant_id=TENANT,
        incident_id=incident_id,
        run_id=RUN_ID,
        dedupe_key="cancel-terminal:observation-1",
        incident_type="provider_cancel_terminal_mismatch",
        severity="high",
        summary="provider cancellation did not converge",
        details=details,
        incident_sha256=contracts.data_incident_fingerprint(
            tenant_id=TENANT,
            run_id=RUN_ID,
            dedupe_key="cancel-terminal:observation-1",
            incident_type="provider_cancel_terminal_mismatch",
            severity="high",
            summary="provider cancellation did not converge",
            trigger_observation_id=None,
            details=details,
            detected_by="workload:dataops-adapter",
            opened_at=NOW,
        ),
        detected_by="workload:dataops-adapter",
        opened_at=NOW,
        updated_at=NOW,
    )
    event = contracts.DataIncidentEvent(
        tenant_id=TENANT,
        event_id=event_id,
        incident_id=incident_id,
        sequence_no=0,
        to_status="open",
        actor_subject="workload:dataops-adapter",
        reason="incident detected",
        details=details,
        occurred_at=NOW,
    )
    notification = contracts.IncidentNotification(
        tenant_id=TENANT,
        notification_id=notification_id,
        incident_id=incident_id,
        incident_event_id=event_id,
        incident_sequence_no=0,
        channel="alertmanager",
        destination_ref="alertmanager:default",
        available_at=NOW,
        created_at=NOW,
    )

    envelope = contracts.IncidentNotificationEnvelope(
        notification=notification,
        incident=incident,
        event=event,
    )
    assert envelope.event.to_status == contracts.IncidentStatus.OPEN
    with pytest.raises(ValidationError, match="destination"):
        contracts.IncidentNotification(
            **{**notification.model_dump(), "destination_ref": "pagerduty:default"}
        )
    with pytest.raises(ValidationError, match="active claim"):
        contracts.IncidentNotification(
            **{**notification.model_dump(), "status": "in_flight"}
        )
    with pytest.raises(ValidationError, match="sequence"):
        contracts.IncidentNotificationEnvelope(
            notification=notification.model_copy(update={"incident_sequence_no": 1}),
            incident=incident,
            event=event,
        )

    done_values = {
        **notification.model_dump(),
            "status": "done",
            "completed_at": NOW,
            "provider_receipt": {
                "schema": "gda.alertmanager_provider_receipt.v1",
                "provider": "alertmanager",
                "accepted": True,
                "http_status": 202,
                "destination_ref": "alertmanager:default",
                "accepted_at": "2026-08-01T12:00:00Z",
            },
            "receipt_sha256": "a" * 64,
            "terminal_worker_id": "worker:test",
    }
    done = contracts.IncidentNotification(**done_values)
    assert done.status is contracts.IncidentNotificationStatus.DONE
    with pytest.raises(ValidationError, match="receipt schema"):
        contracts.IncidentNotification(
            **{**done_values, "provider_receipt": {"schema": "unknown"}}
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
        if Path(item["filename"]).stem == "092_platform_control_ledger"
    )

    assert report["status"] == "valid"
    assert report["contract_count"] == 38
    assert Path(migration["path"]).resolve() == contracts.CONTROL_LEDGER_MIGRATION.resolve()
    assert len(report["migration"]["sha256"]) == 64
    migration_stems = {Path(item["filename"]).stem for item in migrations}
    assert "123_resource_bound_data_incident" in migration_stems
    assert "129_platform_run_event_delivery_outbox" in migration_stems
    assert "198_blueprint_provider_retry_command" in migration_stems
    assert "199_blueprint_duckdb_provider_success" in migration_stems
    assert "200_blueprint_duckdb_execute_command" in migration_stems
    assert "201_blueprint_duckdb_object_storage_evidence" in migration_stems
    assert "202_blueprint_duckdb_spatial_receipt_evidence" in migration_stems


def test_blueprint_provider_retry_extends_only_the_shared_command_vocabulary():
    migration = (
        Path(__file__).resolve().parent
        / "migrations"
        / "198_blueprint_provider_retry_command.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    assert "ALTER TABLE gda_control.platform_command_outbox" in sql
    assert "'blueprint_provider.retry'" in sql
    assert "CREATE TABLE" not in sql
    assert "CREATE TYPE" not in sql


def test_blueprint_duckdb_provider_extends_the_existing_success_authority():
    migration = (
        Path(__file__).resolve().parent
        / "migrations"
        / "199_blueprint_duckdb_provider_success.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION gda_control.finalize_blueprint_test_run_success" in sql
    assert "gda.data_product_blueprint_duckdb_provider_receipt.v1" in sql
    assert "execution_plan_artifact_id" in sql
    assert "output_content_sha256" in sql
    assert "independent passed Blueprint test QualityResult" in sql
    assert "gda_control.apply_platform_run_transition" in sql
    assert "CREATE TABLE" not in sql


def test_blueprint_duckdb_worker_extends_only_the_shared_command_vocabulary():
    migration = (
        Path(__file__).resolve().parent
        / "migrations"
        / "200_blueprint_duckdb_execute_command.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    assert "ALTER TABLE gda_control.platform_command_outbox" in sql
    assert "'blueprint_provider.execute'" in sql
    assert "'blueprint_provider.retry'" in sql
    assert "CREATE TABLE" not in sql
    assert "CREATE TYPE" not in sql


def test_blueprint_duckdb_s3_success_requires_exact_object_version_evidence():
    migration = (
        Path(__file__).resolve().parent
        / "migrations"
        / "201_blueprint_duckdb_object_storage_evidence.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    assert "gda.s3_object_version.v1" in sql
    assert "version_id" in sql
    assert "etag" in sql
    assert "output_storage_evidence" in sql
    assert "VALIDATE CONSTRAINT" in sql
    assert "CREATE TABLE" not in sql
    assert "CREATE OR REPLACE FUNCTION" not in sql


def test_blueprint_duckdb_spatial_success_requires_extension_and_geoparquet_evidence():
    migration = (
        Path(__file__).resolve().parent
        / "migrations"
        / "202_blueprint_duckdb_spatial_receipt_evidence.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    assert "gda.duckdb_spatial_extension.v1" in sql
    assert "gda.geoparquet_spatial_output.v1" in sql
    assert "autoinstall_enabled" in sql
    assert "enforce_blueprint_duckdb_spatial_success" in sql
    assert "platform_run_event" in sql
    assert "CREATE TABLE" not in sql


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
