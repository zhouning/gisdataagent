import inspect
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
import yaml

from data_agent import metadata_fabric_durable_active_metadata_promotion as durable
from data_agent import metadata_fabric_gravitino_jdbc_restart as jdbc_restart
from data_agent.platform_contracts import canonical_json_fingerprint

AT = datetime(2026, 7, 30, 14, 0, tzinfo=UTC)
EXPECTED_EVIDENCE_SHA256 = (
    "53773e9417668e03ad3ab2b5c3cdbd627fb3bc397d63c5860755ec5318eebe8b"
)


def _profile():
    return durable.load_profile()


def _source():
    profile = _profile()
    return durable._load_json_object(
        durable._resolve_repo_path(profile.dependencies.m319_evidence_path)
    )


def _openmetadata():
    source = _source()
    observed = source["first_readback"]["openmetadata"]
    ref = durable.bridge.OpenMetadataTableRef(
        entity_id=observed["entity_id"],
        fully_qualified_name=observed["fully_qualified_name"],
        entity_version=observed["entity_version"],
        server_version="1.13.1",
    )
    return durable.bridge.OpenMetadataObservation(
        ref=ref,
        resource_urn=observed["resource_urn"],
        resource_version_id=observed["resource_version_id"],
        content_sha256=observed["content_sha256"],
        owner_refs=observed["owner_refs"],
        domain_refs=observed["domain_refs"],
        tag_refs=observed["tag_refs"],
        snapshot_sha256=observed["snapshot_sha256"],
        observed_at=AT,
    )


def _runtime_snapshot():
    return {
        "context": "docker-desktop",
        "namespace": {
            "name": "gda-metadata-catalog-persistence",
            "uid": "11111111-1111-4111-8111-111111111111",
        },
        "service": {
            "name": "gravitino-persistence",
            "uid": "22222222-2222-4222-8222-222222222222",
            "type": "ClusterIP",
        },
        "postgresql": {
            "statefulset_uid": "33333333-3333-4333-8333-333333333333",
            "pod_uid": "44444444-4444-4444-8444-444444444444",
            "pod_name": "gravitino-persistence-postgresql-0",
            "node_name": "desktop-worker",
            "ready_replicas": 1,
            "service_account": "gravitino-persistence-postgresql",
            "service_account_automount_disabled": True,
            "image": "docker.io/library/postgres:16.10-bookworm",
            "image_id": f"docker-pullable://postgres@{jdbc_restart.POSTGRESQL_IMAGE_DIGEST}",
            "pvc": {
                "name": "data-gravitino-persistence-postgresql-0",
                "uid": "55555555-5555-4555-8555-555555555555",
                "storage_class": "standard",
                "volume_name": "pvc-postgresql",
                "phase": "Bound",
            },
        },
        "gravitino": {
            "statefulset_uid": "66666666-6666-4666-8666-666666666666",
            "pod_uid": "77777777-7777-4777-8777-777777777777",
            "pod_name": "gravitino-persistence-0",
            "node_name": "desktop-worker",
            "ready_replicas": 1,
            "service_account": "gravitino-persistence",
            "service_account_automount_disabled": True,
            "image": "docker.io/gda/gravitino:1.3.0-local-arm64",
            "image_id": f"docker-pullable://gda/gravitino@{jdbc_restart.GRAVITINO_KUBERNETES_IMAGE_ID}",
            "pvc": {
                "name": "warehouse-gravitino-persistence-0",
                "uid": "88888888-8888-4888-8888-888888888888",
                "storage_class": "standard",
                "volume_name": "pvc-warehouse",
                "phase": "Bound",
            },
        },
        "gravitino_host_image_id": jdbc_restart.GRAVITINO_HOST_IMAGE_ID,
        "jdbc_driver_mounted": True,
        "source_schema_sha256": jdbc_restart.GRAVITINO_SCHEMA_SHA256,
    }


def _runtime_binding(snapshot=None):
    return durable._provider_runtime_binding(
        snapshot or _runtime_snapshot(),
        cluster_uid="99999999-9999-4999-8999-999999999999",
        target=_profile().target,
    )


def _plan(runtime_binding=None):
    return durable.build_projection_plan(
        _profile(),
        _source(),
        _openmetadata(),
        runtime_binding or _runtime_binding(),
    )


def test_profile_binds_checked_m319_and_jdbc_restart_dependencies():
    profile = _profile()
    source, runtime_profile = durable._load_dependencies(profile)

    assert source["evidence_sha256"] == durable.M319_EVIDENCE_SHA256
    assert source["dataset_bundle"]["content_sha256"] == (
        "fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007"
    )
    assert runtime_profile.catalog.backend == "jdbc"
    assert runtime_profile.catalog.warehouse == "file:///var/lib/gravitino/warehouse"
    assert profile.target.identity == (
        "gda_chongqing_m3_20/lakehouse/cultural_heritage/cultural_districts"
    )


def test_dependencies_use_full_jdbc_restart_validator(monkeypatch):
    profile = _profile()
    monkeypatch.setattr(
        jdbc_restart,
        "build_validation_report",
        lambda **_kwargs: {"errors": ["stale runtime contract"]},
    )

    with pytest.raises(
        durable.DurableActiveMetadataPromotionError,
        match="M3-8 JDBC restart evidence does not match",
    ):
        durable._load_dependencies(profile)


def test_runtime_bound_plan_is_distinct_from_m319_memory_binding():
    plan = _plan()
    source_binding = _source()["binding_sha256"]

    assert plan.resource_version_id == durable.RESOURCE_VERSION_ID
    assert plan.content_sha256 == _source()["dataset_bundle"]["content_sha256"]
    assert plan.source_binding_sha256 == source_binding
    assert plan.logical_binding_sha256 != source_binding
    assert plan.gravitino_ref.identity == _profile().target.identity
    assert plan.runtime_binding_sha256 == canonical_json_fingerprint(
        plan.runtime_binding
    )
    assert plan.writes_to_gda_control is False
    assert plan.writes_to_legacy is False


def test_provider_runtime_change_changes_only_runtime_bound_candidate():
    first = _plan()
    changed = deepcopy(first.runtime_binding)
    changed["service"]["uid"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    second = _plan(changed)

    assert second.logical_binding_sha256 == first.logical_binding_sha256
    assert second.runtime_binding_sha256 != first.runtime_binding_sha256
    assert (
        second.promotion_candidate_sha256 != first.promotion_candidate_sha256
    )


def test_apply_authorization_binds_exact_runtime_plan():
    plan = _plan()
    authorization = durable.build_apply_authorization(
        plan, _profile(), authorized_at=AT
    )

    durable.validate_apply_authorization(plan, authorization, at=AT)
    assert authorization[-1]

    changed = deepcopy(plan.runtime_binding)
    changed["namespace"]["uid"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    drifted = _plan(changed)
    with pytest.raises(
        durable.DurableActiveMetadataPromotionError,
        match="does not contain the exact durable plan",
    ):
        durable.validate_apply_authorization(drifted, authorization, at=AT)


def test_first_apply_is_explicit_create_and_replay_is_read_only():
    signature = inspect.signature(durable.DurableProjectionRehearsal.apply_once)

    assert signature.parameters["create"].default is False


def test_runtime_binding_excludes_pod_identity_but_restart_requires_rotation():
    before = _runtime_snapshot()
    after = deepcopy(before)
    after["postgresql"]["pod_uid"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    after["gravitino"]["pod_uid"] = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    binding = _runtime_binding(before)

    assert durable._runtime_continuity_errors(
        {"before": before, "after": after},
        binding,
        cluster_uid="99999999-9999-4999-8999-999999999999",
        target=_profile().target,
    ) == []

    after["gravitino"]["pvc"]["uid"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    errors = durable._runtime_continuity_errors(
        {"before": before, "after": after},
        binding,
        cluster_uid="99999999-9999-4999-8999-999999999999",
        target=_profile().target,
    )
    assert "gravitino PVC identity changed" in errors
    assert "durable provider runtime identity changed across restart" in errors


def test_profile_rejects_memory_catalog_and_sensitive_fields(tmp_path):
    profile = json.loads(json.dumps(yaml_safe_load(durable.DEFAULT_PROFILE_PATH)))
    profile["target"]["catalog_backend"] = "memory"
    profile["identity"]["user_password"] = "must-not-enter-profile"
    path = tmp_path / "profile.yaml"
    path.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(
        durable.DurableActiveMetadataPromotionError,
        match="profile is invalid",
    ):
        durable.load_profile(path)


def yaml_safe_load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_contract_is_valid_and_wrapper_is_fail_closed():
    contract = durable.build_contract_report()
    wrapper = durable.DEFAULT_WRAPPER_PATH.read_text(encoding="utf-8")

    assert contract["status"] == "valid"
    assert contract["source_m319_evidence_sha256"] == durable.M319_EVIDENCE_SHA256
    assert contract["binding_ledger_mode"] == (
        "promotion_candidate_only_no_ledger_write"
    )
    assert "set -euo pipefail" in wrapper
    assert "metadata_fabric_durable_active_metadata_promotion" in wrapper


def test_checked_evidence_is_runtime_bound_and_fail_closed():
    if not durable.DEFAULT_EVIDENCE_PATH.is_file():
        pytest.skip("checked M3-20 evidence is generated by the live rehearsal")
    evidence = durable._load_json_object(durable.DEFAULT_EVIDENCE_PATH)

    assert durable.verify_evidence_integrity(evidence) == []
    assert evidence["evidence_sha256"] == EXPECTED_EVIDENCE_SHA256
    assert evidence["local_durable_active_metadata_promotion_verified"] is True
    assert evidence["post_restart_first_replay_no_op_verified"] is True
    assert evidence["durable_candidate_persisted_to_gda_control"] is False
    assert evidence["durable_catalog_verified"] is False
    assert evidence["production_ready"] is False


def test_evidence_integrity_rejects_runtime_tampering_and_overclaim():
    if not durable.DEFAULT_EVIDENCE_PATH.is_file():
        pytest.skip("checked M3-20 evidence is generated by the live rehearsal")
    evidence = durable._load_json_object(durable.DEFAULT_EVIDENCE_PATH)
    evidence["observation"]["runtime_binding"]["service"]["uid"] = (
        "ffffffff-ffff-4fff-8fff-ffffffffffff"
    )

    assert "durable promotion evidence SHA-256 does not match" in (
        durable.verify_evidence_integrity(evidence)
    )

    forged = durable._load_json_object(durable.DEFAULT_EVIDENCE_PATH)
    forged["durable_catalog_verified"] = True
    stable = {key: value for key, value in forged.items() if key != "evidence_sha256"}
    forged["evidence_sha256"] = canonical_json_fingerprint(stable)
    assert "durable promotion evidence may not claim durable_catalog_verified" in (
        durable.verify_evidence_integrity(forged)
    )
