import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from data_agent import metadata_fabric_active_metadata_binding_reconciliation as binding
from data_agent import metadata_fabric_active_metadata_projection_execution as execution
from data_agent import metadata_fabric_ingestion_replay as replay
from data_agent.dolphinscheduler_adapter import DolphinSchedulerDefinitionBinding
from data_agent.metadata_fabric_binding_contract import (
    ACTIVE_METADATA_PROJECTION_EVIDENCE_SCHEMA,
    build_metadata_fabric_provider_evidence,
    build_metadata_fabric_provider_evidence_artifact,
    parse_metadata_fabric_provider_evidence_artifact,
)

AT = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
EXPECTED_EVIDENCE_SHA256 = (
    "e6d0e3ac4e052029dad0c18d0804626a8af61554a54081c37d8cc9a80c55cd33"
)


def _source():
    return json.loads(binding.DEFAULT_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _profile():
    return execution.build_projection_profile(AT)


def _scheduler_binding(definition):
    return DolphinSchedulerDefinitionBinding(
        tenant_id=binding.TENANT,
        definition_version_id=binding.DEFINITION_ID,
        project_code=190000000000101,
        workflow_definition_code=190000000000102,
        workflow_definition_version=1,
        compiled_sha256=definition.workflow.compiled_sha256,
    )


class FakeOpenMetadata:
    def __init__(self, table=None):
        self.table = deepcopy(table)
        self.mutations = []

    def get_table(self, _fqn):
        return deepcopy(self.table)


class FakeGravitino:
    def __init__(self, table=None):
        self.table = deepcopy(table)
        self.mutations = []
        self.apply_count = 0
        self.compensated = False

    def get_table(self, _target):
        return deepcopy(self.table)

    def _request(
        self,
        _method,
        _path,
        *,
        json_body=None,
        params=None,
        allow_not_found=False,
    ):
        del json_body, params, allow_not_found
        return None

    def apply(self, plan, target):
        self.apply_count += 1
        projection = next(
            item for item in plan.projections if item.provider == "gravitino"
        )
        self.table = {
            "code": 0,
            "table": {
                "name": target.table,
                "properties": {
                    "gda.resource_urn": plan.resource_urn,
                    "gda.resource_version_id": str(plan.resource_version_id),
                    "gda.content_sha256": plan.content_sha256,
                    "gda.provider_revision": projection.desired_state[
                        "provider_revision"
                    ],
                },
            },
        }
        self.mutations.append("gravitino.table.create")
        return deepcopy(self.table)

    def compensate(self):
        self.table = None
        self.compensated = True
        return True


class FakeStaleMemoryCatalogGravitino(FakeGravitino):
    def __init__(self, target, *, identifiers):
        super().__init__()
        self.target = target
        self.identifiers = identifiers
        self.requests = []

    def _request(
        self,
        method,
        path,
        *,
        json_body=None,
        params=None,
        allow_not_found=False,
    ):
        del json_body, allow_not_found
        self.requests.append((method, path, params))
        catalog_path = (
            f"metalakes/{self.target.metalake}/catalogs/{self.target.catalog}"
        )
        if method == "GET" and path == catalog_path:
            return {
                "code": 0,
                "catalog": {
                    "name": self.target.catalog,
                    "type": self.target.catalog_type.lower(),
                    "provider": self.target.catalog_provider,
                    "properties": {
                        "catalog-backend": self.target.catalog_backend,
                        "uri": self.target.uri,
                        "warehouse": self.target.warehouse,
                        "in-use": "true",
                    },
                },
            }
        if method == "GET" and path == f"{catalog_path}/schemas":
            return {"code": 0, "identifiers": self.identifiers}
        if method == "GET":
            return None
        return {"code": 0}


def _retained_openmetadata_payload(source):
    observed = source["first_apply"]["openmetadata"]
    return {
        "id": observed["entity_id"],
        "name": "cultural_districts",
        "fullyQualifiedName": observed["fully_qualified_name"],
        "version": observed["entity_version"],
        "deleted": False,
        "owners": [
            {
                "type": "team",
                "fullyQualifiedName": "data-platform",
            }
        ],
        "domains": [
            {
                "type": "domain",
                "fullyQualifiedName": "natural-resources",
            }
        ],
        "tags": [
            {"tagFQN": "CulturalHeritage.CulturalDistrict"},
            {"tagFQN": "Sensitivity.Internal"},
        ],
        "extension": {
            "gdaResourceUrn": observed["resource_urn"],
            "gdaResourceVersionId": observed["resource_version_id"],
            "gdaContentSha256": observed["content_sha256"],
        },
    }


def _repair_inputs():
    source = _source()
    profile = _profile()
    payload = _retained_openmetadata_payload(source)
    source["first_apply"]["openmetadata"]["snapshot_sha256"] = (
        binding.canonical_json_fingerprint(payload)
    )
    bound = binding.build_bound_source(_source(), profile)
    plan = binding.build_projection_plan(bound.version.content_sha256, profile)
    request = execution.build_execution_request(plan)
    definition = binding.build_scheduler_definition(
        "http://host.docker.internal:43123/v1/execute-projection",
        request,
        created_at=AT,
    )
    dispatch = binding.build_dispatch_bundle(
        bound.version.content_sha256,
        bound,
        definition,
        _scheduler_binding(definition),
        authorized_at=AT,
    )
    apply_authorization = execution.build_provider_apply_authorization(
        plan,
        dispatch.run,
        profile,
    )
    return source, profile, plan, dispatch.run, apply_authorization, payload


def test_m3_18_provider_refs_build_exact_real_data_binding():
    source = _source()
    bound = binding.build_bound_source(source, _profile())

    assert bound.version.resource_version_id == binding.SOURCE_ID
    assert bound.version.content_sha256 == source["dataset_bundle"]["content_sha256"]
    assert str(bound.binding.openmetadata.entity_id) == (
        source["first_apply"]["openmetadata"]["entity_id"]
    )
    assert bound.binding.openmetadata.fully_qualified_name == (
        "gda_chongqing_m3_18.cultural_heritage.published.cultural_districts"
    )
    assert bound.binding.gravitino[0].identity == (
        "gda_chongqing_m3_18/iceberg/cultural_heritage/cultural_districts"
    )
    assert bound.binding.binding_sha256 == (
        source["first_apply"]["binding_candidate_sha256"]
    )
    assert bound.resource.governance_ref == (
        bound.binding.openmetadata.model_dump(mode="json")
    )
    assert bound.resource.technical_refs == (
        bound.binding.gravitino[0].model_dump(mode="json"),
    )


def test_binding_reconciliation_uses_distinct_dispatch_and_apply_authorization():
    source = _source()
    profile = _profile()
    bound = binding.build_bound_source(source, profile)
    plan = binding.build_projection_plan(bound.version.content_sha256, profile)
    request = execution.build_execution_request(plan)
    definition = binding.build_scheduler_definition(
        "http://host.docker.internal:43123/v1/execute-projection",
        request,
        created_at=AT,
    )
    dispatch = binding.build_dispatch_bundle(
        bound.version.content_sha256,
        bound,
        definition,
        _scheduler_binding(definition),
        authorized_at=AT,
    )
    apply_authorization = execution.build_provider_apply_authorization(
        plan,
        dispatch.run,
        profile,
    )
    apply_decision = replay.parse_policy_decision_artifact(
        apply_authorization.policy_decision_artifact
    )

    assert plan.definition_version_id == binding.DEFINITION_ID
    assert plan.run_id == binding.RUN_ID
    assert definition.definition.capability_id == "metadata_fabric.projection_plan"
    assert dispatch.source_resource == bound.resource
    assert dispatch.run.status.value == "accepted"
    assert dispatch.activation_authorization.provider_mutations_executed is False
    assert apply_decision.action == replay.ACTION
    assert apply_decision.execution_plan_artifact_id != (
        dispatch.dispatch_plan.artifact_id
    )


def test_provider_evidence_accepts_active_metadata_execution_source():
    source = _source()
    bound = binding.build_bound_source(source, _profile())
    first = source["first_apply"]
    provider_evidence = build_metadata_fabric_provider_evidence(
        binding=bound.binding,
        source_evidence_schema=ACTIVE_METADATA_PROJECTION_EVIDENCE_SCHEMA,
        source_evidence_sha256=source["evidence_sha256"],
        openmetadata_snapshot_sha256=first["openmetadata"]["snapshot_sha256"],
        gravitino_snapshot_sha256=first["gravitino"]["snapshot_sha256"],
        first_apply_status="no_op",
        first_apply_mutation_count=0,
        observed_at=AT,
    )
    artifact = build_metadata_fabric_provider_evidence_artifact(
        provider_evidence,
        created_by=binding.RUNNER,
    )

    assert parse_metadata_fabric_provider_evidence_artifact(artifact) == (
        provider_evidence
    )
    assert provider_evidence.source_evidence_schema == (
        ACTIVE_METADATA_PROJECTION_EVIDENCE_SCHEMA
    )


def test_source_evidence_tampering_is_rejected_before_binding_construction():
    tampered = deepcopy(_source())
    tampered["first_apply"]["openmetadata"]["entity_id"] = (
        "00000000-0000-4000-8000-000000000001"
    )

    with pytest.raises(
        binding.ActiveMetadataBindingReconciliationError,
        match="M3-18 projection execution evidence is invalid",
    ):
        binding.build_bound_source(tampered, _profile())


def test_static_contract_is_source_bound_and_fail_closed():
    report = binding.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["source_execution_evidence_sha256"] == (
        _source()["evidence_sha256"]
    )
    assert report["expected_binding_sha256"] == (
        _source()["first_apply"]["binding_candidate_sha256"]
    )
    assert report["binding_persisted_to_gda_control"] is False
    assert report["provider_mutations_executed"] is False
    assert report["production_ready"] is False


def test_exact_openmetadata_and_missing_gravitino_repairs_then_replays_no_op():
    source, profile, plan, run, apply_authorization, payload = _repair_inputs()
    openmetadata = FakeOpenMetadata(payload)
    gravitino = FakeGravitino()

    repaired = binding.apply_or_repair_once(
        plan,
        profile,
        apply_authorization,
        run,
        source,
        openmetadata=openmetadata,
        gravitino=gravitino,
        at=AT,
    )
    replayed = replay.apply_once(
        plan,
        profile,
        apply_authorization,
        run,
        openmetadata=openmetadata,
        gravitino=gravitino,
        at=AT,
    )

    assert repaired.status == replay.ApplyStatus.CREATED
    assert repaired.mutations == ("gravitino.table.create",)
    assert replayed.status == replay.ApplyStatus.NO_OP
    assert replayed.mutations == ()
    assert repaired.binding_candidate_sha256 == replayed.binding_candidate_sha256
    assert openmetadata.mutations == []
    assert gravitino.apply_count == 1


def test_openmetadata_snapshot_drift_blocks_before_gravitino_repair():
    source, profile, plan, run, apply_authorization, payload = _repair_inputs()
    payload["name"] = "drifted_name"
    openmetadata = FakeOpenMetadata(payload)
    gravitino = FakeGravitino()
    gravitino.apply(plan, profile.targets.gravitino)
    gravitino.mutations.clear()
    gravitino.apply_count = 0

    with pytest.raises(
        binding.ActiveMetadataBindingReconciliationError,
        match="OpenMetadata projection drifted",
    ):
        binding.apply_or_repair_once(
            plan,
            profile,
            apply_authorization,
            run,
            source,
            openmetadata=openmetadata,
            gravitino=gravitino,
            at=AT,
        )

    assert openmetadata.mutations == []
    assert gravitino.mutations == []
    assert gravitino.apply_count == 0


def test_missing_openmetadata_and_retained_gravitino_blocks_before_mutation():
    source, profile, plan, run, apply_authorization, _payload = _repair_inputs()
    gravitino = FakeGravitino(table={"code": 0, "table": {}})

    with pytest.raises(
        replay.MetadataFabricPartialProjectionError,
        match="requires the exact retained M3-18 OpenMetadata projection",
    ):
        binding.apply_or_repair_once(
            plan,
            profile,
            apply_authorization,
            run,
            source,
            openmetadata=FakeOpenMetadata(),
            gravitino=gravitino,
            at=AT,
        )

    assert gravitino.mutations == []
    assert gravitino.apply_count == 0


def test_exact_empty_stale_memory_catalog_is_reset_before_recreation():
    target = _profile().targets.gravitino
    gravitino = FakeStaleMemoryCatalogGravitino(target, identifiers=[])

    assert binding._reset_stale_empty_gravitino_memory_catalog(
        gravitino,
        target,
    )

    assert gravitino.mutations == ["gravitino.catalog.reset_stale_empty_memory"]
    assert gravitino.requests[-1][0] == "DELETE"
    assert gravitino.requests[-1][2] == {"force": "true"}


def test_nonempty_stale_memory_catalog_blocks_before_reset():
    target = _profile().targets.gravitino
    gravitino = FakeStaleMemoryCatalogGravitino(
        target,
        identifiers=[{"namespace": [target.catalog], "name": "retained"}],
    )

    with pytest.raises(
        replay.MetadataFabricPartialProjectionError,
        match="not visibly empty",
    ):
        binding._reset_stale_empty_gravitino_memory_catalog(gravitino, target)

    assert gravitino.mutations == []
    assert all(method != "DELETE" for method, _path, _params in gravitino.requests)


def test_checked_reconciliation_evidence_is_current_and_fail_closed():
    evidence = json.loads(binding.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert binding.validate_rehearsal_evidence(evidence) == []
    assert evidence["evidence_sha256"] == EXPECTED_EVIDENCE_SHA256
    assert evidence["binding_persisted_to_gda_control"] is True
    assert evidence["first_readback"]["mutations"] == [
        "gravitino.catalog.reset_stale_empty_memory",
        "gravitino.catalog.create",
        "gravitino.schema.create",
        "gravitino.table.create",
    ]
    assert evidence["replay_readback"]["mutation_count"] == 0
    assert evidence["platform_run_status"] == "reconciling"
    assert evidence["durable_catalog_verified"] is False
    assert evidence["production_ready"] is False

    tampered = deepcopy(evidence)
    tampered["binding_persisted_to_gda_control"] = False
    stable = {key: value for key, value in tampered.items() if key != "evidence_sha256"}
    tampered["evidence_sha256"] = binding.canonical_json_fingerprint(stable)
    assert "binding reconciliation did not verify binding_persisted_to_gda_control" in (
        binding.validate_rehearsal_evidence(tampered)
    )
