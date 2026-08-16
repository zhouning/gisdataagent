import json
from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent import metadata_fabric_ingestion as ingestion
from data_agent import platform_contracts as contracts

EXPECTED_PLAN_SHA256 = "a5c8ef636c03a38d0c6edaacff7d1edeba9c4b8a7f1491c493e9308257c5a94d"
EXPECTED_OPENLINEAGE_SHA256 = "4929e51c4126e09415a9fc1578c9401077c5d7c374294e70deeebd29c8216dd2"
EXPECTED_REPLAY_SHA256 = "c33857b2ae75f1106ed7d59e8e53296a3f76f4b90ef386238159b328d47c57ca"


def _inputs():
    values = ingestion._load_contract_inputs(
        ingestion.DEFAULT_PLATFORM_FIXTURE,
        ingestion.DEFAULT_METADATA_FIXTURE,
    )
    return {
        "platform_payload": values[0],
        "metadata_payload": values[1],
        "metadata_resource": values[2],
        "target": values[3],
        "binding": values[4],
        "definition": values[5],
        "run": values[6],
        "source": values[7],
        "artifact": values[8],
        "quality": values[9],
        "lineage": values[10],
        "success": values[11],
        "openmetadata": values[12],
        "gravitino": values[13],
    }


def _plan(values=None):
    source = values or _inputs()
    return ingestion.build_ingestion_plan(
        **{
            key: source[key]
            for key in (
                "metadata_resource",
                "target",
                "binding",
                "definition",
                "run",
                "source",
                "artifact",
                "quality",
                "lineage",
                "success",
                "openmetadata",
                "gravitino",
            )
        }
    )


def _replay(plan, values=None):
    source = values or _inputs()
    return ingestion.evaluate_replay(
        plan,
        resource=source["metadata_resource"],
        version=source["target"],
        binding=source["binding"],
        openmetadata=source["openmetadata"],
        gravitino=source["gravitino"],
    )


def _quality(values, **changes):
    quality = values["quality"]
    payload = quality.model_dump(mode="python")
    payload.update(changes)
    payload["result_sha256"] = contracts.quality_result_fingerprint(
        tenant_id=payload["tenant_id"],
        run_id=payload["run_id"],
        resource_version_id=payload["resource_version_id"],
        rule_version_ref=payload["rule_version_ref"],
        verdict=payload["verdict"],
        metrics=payload["metrics"],
        evidence_artifact_id=payload["evidence_artifact_id"],
        evaluated_by=payload["evaluated_by"],
        evaluated_at=payload["evaluated_at"],
    )
    return contracts.QualityResult.model_validate(payload)


def test_checked_in_ingestion_contract_is_verified_without_enabling_writes():
    report = ingestion.build_ingestion_contract_report()

    assert report == {
        "schema": ingestion.REPORT_SCHEMA,
        "m3_1_contract_verified": True,
        "terminal_evidence_bound": True,
        "deterministic_replay_verified": True,
        "openlineage_candidate_contract_verified": True,
        "projection_count": 2,
        "plan_sha256": EXPECTED_PLAN_SHA256,
        "openlineage_event_sha256": EXPECTED_OPENLINEAGE_SHA256,
        "replay_sha256": EXPECTED_REPLAY_SHA256,
        "replay_status": "no_op",
        "provider_apply_authorized": False,
        "provider_mutations_executed": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
        "live_provider_ingestion_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }


def test_plan_binds_terminal_evidence_projection_ownership_and_openlineage():
    plan = _plan()

    assert plan.plan_sha256 == EXPECTED_PLAN_SHA256
    assert plan.resource_version_id == UUID("00000000-0000-4000-8000-000000000040")
    assert [item.provider for item in plan.projections] == [
        "openmetadata",
        "gravitino",
    ]
    assert plan.projections[0].authority_fields == (ingestion.OPENMETADATA_AUTHORITY_FIELDS)
    assert plan.projections[1].authority_fields == (ingestion.GRAVITINO_AUTHORITY_FIELDS)
    event = plan.openlineage_event
    assert event.schema_url == ingestion.OPENLINEAGE_SCHEMA_URL
    assert event.event_type == "COMPLETE"
    assert event.run.run_id == plan.run_id
    assert event.job.name == "land_use.publish"
    assert str(plan.source_resource_version_id) in event.inputs[0].name
    assert str(plan.resource_version_id) in event.outputs[0].name
    assert plan.provider_apply_authorized is False
    assert plan.writes_to_gda_control is False
    assert plan.writes_to_legacy is False


def test_repeated_build_and_matching_replay_are_deterministic_no_ops():
    values = _inputs()
    first = _plan(values)
    second = _plan(values)
    replay = _replay(first, values)
    reordered = dict(values)
    reordered["openmetadata"] = values["openmetadata"].model_copy(
        update={"tag_refs": tuple(reversed(values["openmetadata"].tag_refs))}
    )
    reordered_plan = _plan(reordered)

    assert first == second
    assert first == reordered_plan
    assert first.idempotency_key == second.idempotency_key
    assert replay.status == ingestion.ReplayStatus.NO_OP
    assert replay.blockers == ()
    assert replay.replay_sha256 == EXPECTED_REPLAY_SHA256
    assert replay.provider_mutations_executed is False


def test_output_artifact_must_bind_target_content_and_run():
    values = _inputs()
    artifact = values["artifact"].model_copy(update={"content_sha256": "a" * 64})
    values["artifact"] = artifact

    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="output artifact does not bind",
    ):
        _plan(values)


def test_quality_must_pass_and_bind_target():
    values = _inputs()
    values["quality"] = _quality(values, verdict="failed")

    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="passed QualityResult",
    ):
        _plan(values)


def test_quality_evaluator_must_be_independent_from_output_producer():
    values = _inputs()
    values["quality"] = _quality(
        values,
        evaluated_by=values["artifact"].created_by,
    )

    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="quality evaluator is not independent",
    ):
        _plan(values)


def test_lineage_must_bind_immutable_run_input_and_target():
    values = _inputs()
    values["lineage"] = values["lineage"].model_copy(
        update={"source_resource_version_id": UUID(int=123)}
    )

    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="lineage event does not bind",
    ):
        _plan(values)

    values = _inputs()
    values["lineage"] = values["lineage"].model_copy(
        update={"facets": {"fixture_only": True, "tampered": True}}
    )
    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="LineageEvent content hash",
    ):
        _plan(values)


def test_success_evidence_must_bind_artifact_quality_and_lineage():
    values = _inputs()
    success = values["success"]
    changed_artifact = UUID(int=456)
    values["success"] = contracts.RunSuccessEvidence(
        tenant_id=success.tenant_id,
        run_id=success.run_id,
        attempt_observation_id=success.attempt_observation_id,
        output_artifact_id=changed_artifact,
        quality_result_id=success.quality_result_id,
        lineage_event_id=success.lineage_event_id,
        evidence_sha256=contracts.run_success_evidence_fingerprint(
            tenant_id=success.tenant_id,
            run_id=success.run_id,
            attempt_observation_id=success.attempt_observation_id,
            output_artifact_id=changed_artifact,
            quality_result_id=success.quality_result_id,
            lineage_event_id=success.lineage_event_id,
        ),
    )

    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="RunSuccessEvidence does not bind",
    ):
        _plan(values)


def test_target_resource_version_must_match_metadata_binding():
    values = _inputs()
    values["target"] = values["target"].model_copy(update={"content_sha256": "c" * 64})

    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="target ResourceVersion does not match",
    ):
        _plan(values)


def test_projection_rejects_secret_extra_and_wrong_authority_fields():
    projection = _plan().projections[0]
    for changes, error in (
        (
            {
                "desired_state": {
                    **projection.desired_state,
                    "client_secret": "forbidden",
                }
            },
            "secret-bearing",
        ),
        (
            {"authority_fields": ("resource_version",)},
            "authority fields",
        ),
    ):
        payload = projection.model_dump(mode="python")
        payload.update(changes)
        with pytest.raises(ValidationError, match=error):
            ingestion.ProviderProjection.model_validate(payload)


def test_projection_rejects_hash_and_idempotency_tampering():
    projection = _plan().projections[0]
    for field in ("desired_state_sha256", "idempotency_key"):
        payload = projection.model_dump(mode="python")
        payload[field] = "f" * 64
        with pytest.raises(ValidationError, match=field):
            ingestion.ProviderProjection.model_validate(payload)


def test_plan_rejects_duplicate_targets_hash_tampering_and_write_claims():
    plan = _plan()
    cases = (
        {"projections": (plan.projections[0], plan.projections[0])},
        {"plan_sha256": "f" * 64},
        {"provider_apply_authorized": True},
        {"writes_to_gda_control": True},
    )
    for changes in cases:
        payload = plan.model_dump(mode="python", by_alias=True)
        payload.update(changes)
        with pytest.raises(ValidationError):
            ingestion.MetadataFabricIngestionPlan.model_validate(payload)

    changed_state = {
        **plan.projections[0].desired_state,
        "resource_version_id": str(UUID(int=789)),
    }
    changed_projection = ingestion._projection(
        provider="openmetadata",
        target_identity=plan.projections[0].target_identity,
        desired_state=changed_state,
    )
    payload = plan.model_dump(mode="python", by_alias=True)
    payload["projections"] = (changed_projection, *plan.projections[1:])
    with pytest.raises(ValidationError, match="projection GDA identity"):
        ingestion.MetadataFabricIngestionPlan.model_validate(payload)


def test_openlineage_rejects_naive_time_and_duplicate_datasets():
    event = _plan().openlineage_event
    payload = event.model_dump(mode="python", by_alias=True)
    payload["eventTime"] = event.event_time.replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone"):
        ingestion.OpenLineageRunEvent.model_validate(payload)

    payload = event.model_dump(mode="python", by_alias=True)
    payload["inputs"] = [event.inputs[0], event.inputs[0]]
    with pytest.raises(ValidationError, match="unique"):
        ingestion.OpenLineageRunEvent.model_validate(payload)


@pytest.mark.parametrize("field", ["owner_refs", "domain_refs", "tag_refs"])
def test_openmetadata_projection_drift_blocks_replay(field):
    values = _inputs()
    plan = _plan(values)
    values["openmetadata"] = values["openmetadata"].model_copy(update={field: ("changed:value",)})

    replay = _replay(plan, values)

    assert replay.status == ingestion.ReplayStatus.BLOCKED
    assert replay.provider_apply_authorized is False
    assert any("projection_state_drift:openmetadata" in item for item in replay.blockers)


def test_gravitino_revision_and_target_inventory_drift_block_replay():
    values = _inputs()
    plan = _plan(values)
    observation = values["gravitino"][0].model_copy(
        update={"provider_revision": "iceberg-snapshot-changed"}
    )
    values["gravitino"] = (observation,)

    replay = _replay(plan, values)

    assert replay.status == ingestion.ReplayStatus.BLOCKED
    assert any("gravitino_provider_revision_drift" in item for item in replay.blockers)

    values = _inputs()
    values["gravitino"] = ()
    replay = _replay(plan, values)
    assert "projection_target_inventory_drift" in replay.blockers


def test_changed_expected_fingerprint_fails_closed(tmp_path):
    expected = json.loads(ingestion.DEFAULT_EXPECTED_FIXTURE.read_text(encoding="utf-8"))
    expected["plan_sha256"] = "0" * 64
    target = tmp_path / "expected.json"
    target.write_text(json.dumps(expected), encoding="utf-8")

    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="golden fingerprint drift",
    ):
        ingestion.build_ingestion_contract_report(expected_path=target)


def test_changed_platform_or_metadata_fixture_fails_before_plan(tmp_path):
    platform = deepcopy(_inputs()["platform_payload"])
    platform["contracts"]["artifact"]["content_sha256"] = "0" * 64
    platform_path = tmp_path / "platform.json"
    platform_path.write_text(json.dumps(platform), encoding="utf-8")
    with pytest.raises(
        ingestion.MetadataFabricIngestionError,
        match="platform golden fixture is invalid",
    ):
        ingestion.build_ingestion_contract_report(platform_path=platform_path)

    metadata = deepcopy(_inputs()["metadata_payload"])
    metadata["openmetadata_response"]["client_secret"] = "forbidden"
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(
        ingestion.bridge.MetadataFabricProtocolError,
        match="secret-bearing",
    ):
        ingestion.build_ingestion_contract_report(metadata_path=metadata_path)


def test_cli_validate_prints_the_fail_closed_report(capsys):
    assert ingestion.main(["validate"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["m3_1_contract_verified"] is True
    assert report["provider_apply_authorized"] is False
    assert report["production_ready"] is False
