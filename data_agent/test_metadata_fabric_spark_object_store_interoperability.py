import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from data_agent import metadata_fabric_spark_object_store_interoperability as interop


def _checked_evidence() -> dict:
    return json.loads(interop.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _observation() -> dict:
    return deepcopy(_checked_evidence()["observation"])


def _write_profile(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_checked_contract_and_evidence_verify_cross_node_object_store_boundary():
    contract = interop.build_contract_report()
    validation = interop.build_validation_report()
    evidence = _checked_evidence()

    assert contract["local_static_contract_verified"] is True
    assert contract["contract_fingerprint"] == (
        "9713cdb3040e1b6532489f329aef7ed7b5266e0757551252f537cb83476b4bee"
    )
    assert contract["runtime_image_identity"] == {
        "gravitino_host_image_id": interop.GRAVITINO_HOST_IMAGE_ID,
        "gravitino_kubernetes_image_id": interop.GRAVITINO_KUBERNETES_IMAGE_ID,
        "postgresql_image_digest": interop.POSTGRESQL_IMAGE_DIGEST,
        "spark_host_image_id": interop.SPARK_HOST_IMAGE_ID,
        "spark_kubernetes_image_id": interop.SPARK_KUBERNETES_IMAGE_ID,
        "minio_host_image_id": interop.MINIO_HOST_IMAGE_ID,
        "minio_kubernetes_image_id": interop.MINIO_KUBERNETES_IMAGE_ID,
    }
    assert interop.verify_evidence_integrity(evidence) == []
    assert evidence["evidence_fingerprint"] == (
        "05844457efb378581fb7fc2e7ed3c706819b2d8fa5a52b2f82577051d38c2cd1"
    )
    assert validation["errors"] == []
    assert validation["local_spark_object_store_interoperability_verified"] is True
    assert validation["local_spark_create_read_write_verified"] is True
    assert validation["local_spark_schema_evolution_verified"] is True
    assert validation["local_spark_snapshot_time_travel_verified"] is True
    assert validation["gravitino_api_metadata_readback_verified"] is True
    assert validation["local_cross_node_object_store_verified"] is True
    assert validation["object_store_metadata_verified"] is True
    assert validation["production_object_store_verified"] is False
    assert validation["spark_conformance_verified"] is False
    assert validation["flink_conformance_verified"] is False
    assert validation["persistent_catalog_identity_binding_verified"] is False
    assert validation["protected_workload_identity_verified"] is False
    assert validation["oidc_verified"] is False
    assert validation["tls_verified"] is False
    assert validation["production_ingestion_verified"] is False
    assert validation["production_ready"] is False


def test_checked_evidence_contains_direct_object_store_and_node_proof():
    observation = _observation()
    runtime = observation["runtime"]
    store = observation["object_store"]

    assert runtime["object_store"]["node_name"] == "desktop-control-plane"
    assert runtime["gravitino"]["node_name"] == "desktop-worker"
    assert observation["spark"]["pod"]["node_name"] == "desktop-worker"
    assert runtime["gravitino"]["persistent_volume_claims"] == []
    assert observation["spark"]["pod"]["persistent_volume_claims"] == []
    assert store["object_count"] == 10
    assert len(store["data_keys"]) == 2
    assert len(store["metadata_keys"]) == 4
    assert len(store["manifest_keys"]) == 4
    assert store["latest_metadata"]["fields"] == [
        {"name": "probe_id", "required": True, "type": "string"},
        {"name": "quality", "required": False, "type": "string"},
    ]


def test_profile_rejects_privilege_expansion_and_sensitive_fields(tmp_path):
    profile = yaml.safe_load(interop.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["scope"]["role_securable_objects"][1]["privileges"].append(
        {"name": "MODIFY_TABLE", "condition": "ALLOW"}
    )
    profile["catalog"]["object_store_access_key"] = "must-not-enter-profile"

    with pytest.raises(
        interop.MetadataFabricSparkObjectStoreInteroperabilityError,
        match="profile is invalid",
    ):
        interop.load_profile(_write_profile(tmp_path, profile))


def test_profile_rejects_tampered_spark_dependency(tmp_path, monkeypatch):
    profile = yaml.safe_load(interop.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    dependency = json.loads(
        (
            interop.REPO_ROOT
            / "docs/evidence/metadata-fabric-spark-iceberg-rest-interoperability-2026-07-29.json"
        ).read_text(encoding="utf-8")
    )
    dependency["production_ready"] = True
    dependency_path = (
        tmp_path
        / "docs/evidence/metadata-fabric-spark-iceberg-rest-interoperability-2026-07-29.json"
    )
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_text(json.dumps(dependency), encoding="utf-8")
    monkeypatch.setattr(interop, "REPO_ROOT", tmp_path)

    with pytest.raises(
        interop.MetadataFabricSparkObjectStoreInteroperabilityError,
        match="dependency does not match",
    ):
        interop.load_profile(_write_profile(tmp_path, profile))


def test_manifest_rejects_committed_secret_and_incomplete_runtime(
    tmp_path, monkeypatch
):
    (tmp_path / "runtime.yaml").write_text(
        """
apiVersion: v1
kind: Namespace
metadata:
  name: gda-metadata-spark-object-store
---
apiVersion: v1
kind: Secret
metadata:
  name: forbidden
stringData:
  material: forbidden
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(interop, "MANIFEST_DIR", tmp_path)

    errors = interop._validate_manifest()

    assert "Spark object-store manifest may not commit Secret values" in errors
    assert "Spark object-store manifest is incomplete" in errors


def test_manifest_requires_suspended_tokenless_pvcless_job(monkeypatch):
    documents = interop._manifest_documents()
    job = next(document for document in documents if document.get("kind") == "Job")
    job["spec"]["suspend"] = False
    pod_spec = job["spec"]["template"]["spec"]
    pod_spec["automountServiceAccountToken"] = True
    pod_spec["volumes"].append(
        {
            "name": "warehouse",
            "persistentVolumeClaim": {"claimName": "forbidden-warehouse"},
        }
    )
    pod_spec["containers"][0].pop("resources")
    monkeypatch.setattr(interop, "_manifest_documents", lambda: documents)

    errors = interop._validate_manifest()

    assert "Spark object-store Job must start suspended" in errors
    assert "Spark object-store Job must disable token automount" in errors
    assert "Spark object-store Job may not mount a warehouse PVC" in errors
    assert "Spark object-store Job resources are incomplete" in errors


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["spark"]["pod"].update(
                {"persistent_volume_claims": ["forged-warehouse"]}
            ),
            "Spark object-store runtime boundary does not match",
        ),
        (
            lambda value: value["runtime"]["object_store"].update(
                {"node_name": "desktop-worker"}
            ),
            "object_store runtime observation does not match",
        ),
        (
            lambda value: value["spark"].update(
                {"failure_diagnostic": ["forged failure"]}
            ),
            "Spark object-store result envelope does not match",
        ),
        (
            lambda value: value["spark"]["result"].update(
                {"current_rows": [["forged", None]]}
            ),
            "Spark object-store create/read/write result does not match",
        ),
    ],
)
def test_evidence_rejects_spark_runtime_node_or_data_drift(mutate, expected):
    observation = _observation()
    mutate(observation)

    evidence = interop.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["local_spark_object_store_interoperability_verified"] is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["object_store"]["data_keys"].pop(),
            "Object-store Iceberg object inventory does not match",
        ),
        (
            lambda value: value["object_store"]["latest_metadata"].update(
                {"current_snapshot_id": 1}
            ),
            "Object-store Iceberg metadata projection does not match",
        ),
        (
            lambda value: value["post_spark"]["table"]["projection"][
                "columns"
            ].pop(),
            "Gravitino API did not read back object-store schema evolution",
        ),
        (
            lambda value: value["post_spark"].update(
                {"denied_catalog_create_status": 200}
            ),
            "Post-Spark object-store catalog mutation was not denied",
        ),
    ],
)
def test_evidence_rejects_object_metadata_schema_or_denial_drift(mutate, expected):
    observation = _observation()
    mutate(observation)

    evidence = interop.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["local_spark_object_store_interoperability_verified"] is False


def test_evidence_rejects_incomplete_cleanup_and_sensitive_material():
    observation = _observation()
    observation["runtime_checks"]["persistent_volumes_absent"] = False
    observation["object_store_secret_access_key"] = "must-not-enter-evidence"

    evidence = interop.build_evidence(observation)

    assert "Spark object-store observation contains sensitive material" in evidence[
        "errors"
    ]
    assert "Spark object-store interoperability cleanup is incomplete" in evidence[
        "errors"
    ]
    assert evidence["local_spark_object_store_interoperability_verified"] is False


def test_evidence_integrity_rejects_tampering_and_production_overclaim():
    evidence = _checked_evidence()
    evidence["observation"]["object_store"]["objects"][0]["size"] = 0

    errors = interop.verify_evidence_integrity(evidence)

    assert "Spark object-store evidence fingerprint does not match" in errors

    forged = _checked_evidence()
    forged["production_object_store_verified"] = True
    forged["spark_conformance_verified"] = True
    forged["production_ready"] = True
    stable = {
        key: value for key, value in forged.items() if key != "evidence_fingerprint"
    }
    forged["evidence_fingerprint"] = interop.recovery._canonical_sha256(stable)
    errors = interop.verify_evidence_integrity(forged)
    assert (
        "Spark object-store evidence may not claim production_object_store_verified"
        in errors
    )
    assert "Spark object-store evidence may not claim spark_conformance_verified" in errors
    assert "Spark object-store evidence may not claim production_ready" in errors


def test_wrapper_is_fail_closed():
    wrapper = interop.DEFAULT_WRAPPER_PATH.read_text(encoding="utf-8")

    assert "set -euo pipefail" in wrapper
    assert "metadata_fabric_spark_object_store_interoperability" in wrapper
