import inspect
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError

from data_agent import metadata_fabric_durable_active_metadata_promotion as durable
from data_agent import metadata_fabric_object_store_active_metadata_promotion as object_promotion
from data_agent import metadata_fabric_spark_object_store_interoperability as m310
from data_agent.platform_contracts import canonical_json_fingerprint

AT = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
EXPECTED_EVIDENCE_SHA256 = "d73754c53cf16d888aa345baa5d079cc7fd98d8b84db747f52188c1a69bf1628"


def _profile():
    return object_promotion.load_profile()


def _source():
    profile = _profile()
    return object_promotion._load_json_object(
        object_promotion._resolve_repo_path(profile.dependencies.m320_evidence_path)
    )


def _openmetadata():
    expected = _source()["observation"]["openmetadata"]
    ref = object_promotion.bridge.OpenMetadataTableRef(
        entity_id=expected["entity_id"],
        fully_qualified_name=expected["fully_qualified_name"],
        entity_version=expected["entity_version"],
        server_version="1.13.1",
    )
    return object_promotion.bridge.OpenMetadataObservation(
        ref=ref,
        resource_urn=expected["resource_urn"],
        resource_version_id=expected["resource_version_id"],
        content_sha256=expected["content_sha256"],
        owner_refs=expected["owner_refs"],
        domain_refs=expected["domain_refs"],
        tag_refs=expected["tag_refs"],
        snapshot_sha256=expected["snapshot_sha256"],
        observed_at=AT,
    )


def _workload(uid: str, pod_uid: str, *, node: str, pvc=None):
    return {
        "statefulset_uid": uid,
        "pod_uid": pod_uid,
        "pod_name": "pod-0",
        "node_name": node,
        "ready_replicas": 1,
        "service_account": "bounded",
        "service_account_automount_disabled": True,
        "image": "example/image:pinned",
        "image_id": f"sha256:{uid.replace('-', '')[:32].ljust(64, '0')}",
        "persistent_volume_claims": [pvc["name"]] if pvc else [],
        "pvc": pvc,
    }


def _runtime_snapshot():
    postgresql_pvc = {
        "name": "data-gravitino-persistence-postgresql-0",
        "uid": "55555555-5555-4555-8555-555555555555",
        "storage_class": "standard",
        "volume_name": "pvc-postgresql",
        "phase": "Bound",
    }
    object_store_pvc = {
        "name": "data-metadata-object-store-0",
        "uid": "88888888-8888-4888-8888-888888888888",
        "storage_class": "standard",
        "volume_name": "pvc-object-store",
        "phase": "Bound",
    }
    return {
        "context": "docker-desktop",
        "namespace": {
            "name": "gda-metadata-spark-object-store",
            "uid": "11111111-1111-4111-8111-111111111111",
        },
        "service": {
            "name": "gravitino-persistence",
            "uid": "22222222-2222-4222-8222-222222222222",
            "type": "ClusterIP",
        },
        "object_store_service": {
            "name": "metadata-object-store",
            "uid": "33333333-3333-4333-8333-333333333333",
            "type": "ClusterIP",
        },
        "postgresql": _workload(
            "44444444-4444-4444-8444-444444444444",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            node="desktop-worker",
            pvc=postgresql_pvc,
        ),
        "gravitino": _workload(
            "66666666-6666-4666-8666-666666666666",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            node="desktop-worker",
        ),
        "object_store": _workload(
            "77777777-7777-4777-8777-777777777777",
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            node="desktop-control-plane",
            pvc=object_store_pvc,
        ),
    }


def _runtime_binding(snapshot=None):
    return object_promotion._provider_runtime_binding(
        snapshot or _runtime_snapshot(),
        cluster_uid="99999999-9999-4999-8999-999999999999",
        target=_profile().target,
    )


def _plan(runtime_binding=None):
    return object_promotion.build_projection_plan(
        _profile(),
        _source(),
        _openmetadata(),
        runtime_binding or _runtime_binding(),
    )


def test_profile_binds_checked_m320_and_m310_dependencies():
    profile = _profile()
    source, runtime_profile = object_promotion._load_dependencies(profile)

    assert source["evidence_sha256"] == object_promotion.M320_EVIDENCE_SHA256
    assert source["dataset_bundle"]["content_sha256"] == (
        "fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007"
    )
    assert runtime_profile.catalog.backend == "jdbc"
    assert runtime_profile.catalog.warehouse == "s3://gda-metadata-warehouse/warehouse"
    assert profile.target.identity == (
        "gda_chongqing_m3_21/lakehouse/cultural_heritage/cultural_districts"
    )
    assert profile.claims.production_object_store_verified is False


def test_dependencies_use_full_predecessor_validators(monkeypatch):
    profile = _profile()
    durable_called = False
    object_store_called = False
    durable_validator = durable.build_validation_report
    object_store_validator = m310.build_validation_report

    def checked_durable(**kwargs):
        nonlocal durable_called
        durable_called = True
        return durable_validator(**kwargs)

    def checked_object_store(**kwargs):
        nonlocal object_store_called
        object_store_called = True
        return object_store_validator(**kwargs)

    monkeypatch.setattr(durable, "build_validation_report", checked_durable)
    monkeypatch.setattr(m310, "build_validation_report", checked_object_store)

    object_promotion._load_dependencies(profile)

    assert durable_called is True
    assert object_store_called is True


def test_runtime_binding_binds_s3_identity_but_excludes_rotating_pods():
    snapshot = _runtime_snapshot()
    binding = _runtime_binding(snapshot)
    changed_pods = deepcopy(snapshot)
    changed_pods["postgresql"]["pod_uid"] = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    changed_pods["gravitino"]["pod_uid"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

    assert _runtime_binding(changed_pods) == binding
    assert "pod_uid" not in json.dumps(binding, sort_keys=True)
    assert binding["catalog"] == {
        "backend": "jdbc",
        "uri": "jdbc:postgresql://gravitino-persistence-postgresql:5432/iceberg",
        "warehouse": "s3://gda-metadata-warehouse/warehouse",
        "io_impl": "org.apache.iceberg.aws.s3.S3FileIO",
        "s3_endpoint": "http://metadata-object-store:9000",
        "s3_region": "us-east-1",
        "s3_path_style_access": True,
        "bucket": "gda-metadata-warehouse",
    }
    assert binding["storage"]["gravitino_persistent_volume_claims"] == []

    changed_storage = deepcopy(snapshot)
    changed_storage["object_store"]["pvc"]["uid"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    assert _runtime_binding(changed_storage) != binding


def test_runtime_binding_rejects_shared_pvc_or_same_node():
    shared_pvc = _runtime_snapshot()
    shared_pvc["gravitino"]["pvc"] = deepcopy(shared_pvc["object_store"]["pvc"])
    shared_pvc["gravitino"]["persistent_volume_claims"] = ["data-metadata-object-store-0"]
    with pytest.raises(object_promotion.ObjectStoreActiveMetadataPromotionError):
        _runtime_binding(shared_pvc)

    same_node = _runtime_snapshot()
    same_node["object_store"]["node_name"] = "desktop-worker"
    with pytest.raises(object_promotion.ObjectStoreActiveMetadataPromotionError):
        _runtime_binding(same_node)


def test_plan_has_independent_predecessor_and_candidate_fingerprints():
    plan = _plan()

    assert plan.predecessor_promotion_candidate_sha256 == _source()["promotion_candidate_sha256"]
    assert plan.promotion_candidate_sha256 != (plan.predecessor_promotion_candidate_sha256)
    assert plan.runtime_binding_sha256 == canonical_json_fingerprint(plan.runtime_binding)
    assert plan.target.table_location == (
        "s3://gda-metadata-warehouse/warehouse/cultural_heritage/cultural_districts"
    )

    tampered = plan.model_dump(mode="json", by_alias=True)
    tampered["runtime_binding"]["catalog"]["bucket"] = "wrong-bucket"
    with pytest.raises(ValidationError):
        object_promotion.ObjectStoreProjectionPlan.model_validate(tampered)


def test_authorization_binds_exact_object_store_plan():
    plan = _plan()
    authorization = object_promotion.build_apply_authorization(plan, _profile(), authorized_at=AT)

    object_promotion.validate_apply_authorization(plan, authorization, at=AT)
    changed = list(authorization)
    changed[-1] = "0" * 64
    with pytest.raises(object_promotion.ObjectStoreActiveMetadataPromotionError):
        object_promotion.validate_apply_authorization(plan, tuple(changed), at=AT)


def test_bootstrap_source_configures_s3_without_recording_material():
    source = inspect.getsource(object_promotion.ObjectStoreProjectionRehearsal.bootstrap)

    for marker in (
        '"io-impl": profile.target.io_impl',
        '"s3-access-key-id": object_store_user.get_secret_value()',
        '"s3-secret-access-key": object_store_material.get_secret_value()',
        '"s3-endpoint": profile.target.s3_endpoint',
        '"material_recorded": False',
    ):
        assert marker in source


def test_restart_orders_postgresql_before_gravitino():
    source = inspect.getsource(object_promotion.restart_provider_runtime)
    assert source.index("statefulset/gravitino-persistence-postgresql") < source.index(
        '"statefulset/gravitino-persistence",'
    )


class _Body:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload


class _S3Client:
    def __init__(self, metadata):
        self.metadata = json.dumps(metadata).encode()
        self.closed = False

    def list_objects_v2(self, **request):
        assert request == {
            "Bucket": "gda-metadata-warehouse",
            "Prefix": "warehouse/cultural_heritage/cultural_districts/",
        }
        return {
            "IsTruncated": False,
            "Contents": [
                {
                    "Key": (
                        "warehouse/cultural_heritage/cultural_districts/"
                        "metadata/00000-test.metadata.json"
                    ),
                    "Size": len(self.metadata),
                    "ETag": '"etag"',
                }
            ],
        }

    def get_object(self, **request):
        assert request["Bucket"] == "gda-metadata-warehouse"
        return {"Body": _Body(self.metadata)}

    def close(self):
        self.closed = True


class _Runtime:
    def __init__(self, client):
        self.client = client

    def _s3_client(self, **kwargs):
        assert kwargs["endpoint_url"] == "http://127.0.0.1:9000"
        return self.client


def test_direct_s3_observation_requires_exact_empty_table_metadata():
    metadata = {
        "location": ("s3://gda-metadata-warehouse/warehouse/cultural_heritage/cultural_districts"),
        "current-schema-id": 0,
        "current-snapshot-id": -1,
        "schemas": [
            {
                "schema-id": 0,
                "fields": [
                    {"name": "BSM", "required": True, "type": "string"},
                    {"name": "geometry", "required": True, "type": "binary"},
                ],
            }
        ],
    }
    client = _S3Client(metadata)

    observed = object_promotion.observe_table_object_store(
        _Runtime(client),
        _profile(),
        endpoint_url="http://127.0.0.1:9000",
        object_store_user=SecretStr("user"),
        object_store_material=SecretStr("material"),
    )

    assert observed["object_count"] == 1
    assert observed["data_keys"] == []
    assert observed["manifest_keys"] == []
    assert observed["source_feature_rows_present"] is False
    assert client.closed is True


def test_direct_s3_observation_rejects_wrong_location():
    metadata = {
        "location": "s3://wrong/table",
        "current-schema-id": 0,
        "schemas": [
            {
                "schema-id": 0,
                "fields": [
                    {"name": "BSM", "required": True, "type": "string"},
                    {"name": "geometry", "required": True, "type": "binary"},
                ],
            }
        ],
    }
    with pytest.raises(object_promotion.ObjectStoreActiveMetadataPromotionError):
        object_promotion.observe_table_object_store(
            _Runtime(_S3Client(metadata)),
            _profile(),
            endpoint_url="http://127.0.0.1:9000",
            object_store_user=SecretStr("user"),
            object_store_material=SecretStr("material"),
        )


def test_contract_is_valid_and_fail_closed_for_production():
    report = object_promotion.build_contract_report()

    assert report["status"] == "valid"
    assert report["source_m320_evidence_sha256"] == (object_promotion.M320_EVIDENCE_SHA256)
    assert report["m310_evidence_fingerprint"] == (object_promotion.M310_EVIDENCE_FINGERPRINT)
    assert report["production_object_store_verified"] is False
    assert report["production_ready"] is False


def test_evidence_integrity_rejects_sensitive_material_and_overclaim():
    evidence = {
        "schema": object_promotion.EVIDENCE_SCHEMA,
        "errors": [],
        "production_object_store_verified": True,
        "local_object_store_active_metadata_promotion_verified": True,
        "credential": "must-not-appear",
    }
    stable = dict(evidence)
    evidence["evidence_sha256"] = canonical_json_fingerprint(stable)

    errors = object_promotion.verify_evidence_integrity(evidence)

    assert "object-store promotion evidence contains sensitive material" in errors
    assert any("production_object_store_verified" in error for error in errors)


def test_checked_evidence_is_valid_and_content_bound():
    evidence = object_promotion._load_json_object(object_promotion.DEFAULT_EVIDENCE_PATH)
    report = object_promotion.build_validation_report()

    assert evidence["evidence_sha256"] == EXPECTED_EVIDENCE_SHA256
    assert evidence["promotion_candidate_sha256"] == (
        "63812c311b3f239bc6a944748c4ff384250eb9c9ed9009d3384fc699f1d3eaa9"
    )
    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["direct_object_store_metadata_verified"] is True

    tampered = deepcopy(evidence)
    tampered["observation"]["object_store_after_restart"]["objects"][0]["etag"] = "tampered"
    stable = {key: value for key, value in tampered.items() if key != "evidence_sha256"}
    tampered["evidence_sha256"] = canonical_json_fingerprint(stable)
    rebuilt = object_promotion.build_evidence(tampered["observation"], profile=_profile())
    assert "direct S3 Iceberg metadata did not survive provider restart" in rebuilt["errors"]
