import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from data_agent import metadata_fabric_spark_iceberg_rest_interoperability as interop


def _checked_evidence() -> dict:
    return json.loads(interop.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _observation() -> dict:
    return deepcopy(_checked_evidence()["observation"])


def _write_profile(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_checked_in_contract_and_evidence_verify_the_local_boundary():
    contract = interop.build_contract_report()
    validation = interop.build_validation_report()
    evidence = _checked_evidence()

    assert contract["contract_fingerprint"] == (
        "a78b95d36a6a5d5f4b5e303be21263d00fdd7102c3a70ce282ba69f2d8cdcd2e"
    )
    assert contract["local_static_contract_verified"] is True
    assert contract["runtime_image_identity"] == {
        "gravitino_host_image_id": interop.GRAVITINO_HOST_IMAGE_ID,
        "gravitino_kubernetes_image_id": interop.GRAVITINO_KUBERNETES_IMAGE_ID,
        "postgresql_image_digest": interop.POSTGRESQL_IMAGE_DIGEST,
        "spark_host_image_id": interop.SPARK_HOST_IMAGE_ID,
        "spark_kubernetes_image_id": interop.SPARK_KUBERNETES_IMAGE_ID,
    }
    assert interop.verify_evidence_integrity(evidence) == []
    assert evidence["evidence_fingerprint"] == (
        "50f9d0021db11e22364697d1ad8928ee068d28dc8046556bbca1a4e1c819f8e0"
    )
    assert validation["errors"] == []
    assert validation["local_spark_iceberg_rest_interoperability_verified"] is True
    assert validation["local_spark_create_read_write_verified"] is True
    assert validation["local_spark_schema_evolution_verified"] is True
    assert validation["local_spark_snapshot_time_travel_verified"] is True
    assert validation["gravitino_api_metadata_readback_verified"] is True
    assert validation["local_same_node_shared_pvc_verified"] is True
    assert validation["spark_conformance_verified"] is False
    assert validation["flink_conformance_verified"] is False
    assert validation["persistent_catalog_identity_binding_verified"] is False
    assert validation["protected_workload_identity_verified"] is False
    assert validation["oidc_verified"] is False
    assert validation["tls_verified"] is False
    assert validation["production_ingestion_verified"] is False
    assert validation["production_ready"] is False


def test_profile_rejects_privilege_expansion_and_sensitive_fields(tmp_path):
    profile = yaml.safe_load(interop.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["scope"]["role_securable_objects"][1]["privileges"].append(
        {"name": "MODIFY_TABLE", "condition": "ALLOW"}
    )
    profile["catalog"]["jdbc_password"] = "must-not-enter-profile"

    with pytest.raises(
        interop.MetadataFabricSparkIcebergRestInteroperabilityError,
        match="profile is invalid",
    ):
        interop.load_profile(_write_profile(tmp_path, profile))


def test_profile_rejects_tampered_jdbc_restart_dependency(tmp_path, monkeypatch):
    profile = yaml.safe_load(interop.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    dependency = json.loads(
        (
            interop.REPO_ROOT
            / "docs/evidence/metadata-fabric-gravitino-jdbc-restart-2026-07-29.json"
        ).read_text(encoding="utf-8")
    )
    dependency["production_ready"] = True
    dependency_path = (
        tmp_path
        / "docs/evidence/metadata-fabric-gravitino-jdbc-restart-2026-07-29.json"
    )
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_text(json.dumps(dependency), encoding="utf-8")
    monkeypatch.setattr(interop, "REPO_ROOT", tmp_path)

    with pytest.raises(
        interop.MetadataFabricSparkIcebergRestInteroperabilityError,
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
  name: gda-metadata-spark-interop
---
apiVersion: v1
kind: Secret
metadata:
  name: forbidden
stringData:
  password: forbidden
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(interop, "MANIFEST_DIR", tmp_path)

    errors = interop._validate_manifest()

    assert "Spark interoperability manifest may not commit Secret values" in errors
    assert "Spark interoperability manifest is incomplete" in errors


def test_manifest_requires_suspended_tokenless_job_with_resources(monkeypatch):
    documents = interop._manifest_documents()
    job = next(document for document in documents if document.get("kind") == "Job")
    job["spec"]["suspend"] = False
    pod_spec = job["spec"]["template"]["spec"]
    pod_spec["automountServiceAccountToken"] = True
    pod_spec["containers"][0].pop("resources")
    monkeypatch.setattr(interop, "_manifest_documents", lambda: documents)

    errors = interop._validate_manifest()

    assert "Spark interoperability Job must start suspended" in errors
    assert "Spark interoperability Job must disable token automount" in errors
    assert "Spark interoperability Job resources are incomplete" in errors


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["spark"]["job"].update(
                {"succeeded": 0, "failed": 1}
            ),
            "Spark interoperability Job did not complete exactly once",
        ),
        (
            lambda value: value["spark"]["pod"].update(
                {"image_id": "sha256:" + "0" * 64}
            ),
            "Spark interoperability runtime boundary does not match",
        ),
        (
            lambda value: value["spark"]["pod"].update(
                {"warehouse_pvc": "unrelated-pvc"}
            ),
            "Spark interoperability runtime boundary does not match",
        ),
        (
            lambda value: value["runtime"]["iceberg_rest"].update(
                {"ready": False}
            ),
            "Iceberg REST sidecar boundary does not match",
        ),
    ],
)
def test_evidence_rejects_job_image_pvc_or_rest_runtime_drift(mutate, expected):
    observation = _observation()
    mutate(observation)

    evidence = interop.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["local_spark_iceberg_rest_interoperability_verified"] is False
    if expected.startswith("Spark interoperability"):
        assert evidence["local_spark_create_read_write_verified"] is False
        assert evidence["local_spark_schema_evolution_verified"] is False
        assert evidence["local_spark_snapshot_time_travel_verified"] is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["spark"]["result"].update(
                {"current_rows": [["forged", None]]}
            ),
            "Spark create/read/write result does not match",
        ),
        (
            lambda value: value["spark"]["result"].update(
                {"snapshot_operations": ["append", "overwrite"]}
            ),
            "Spark snapshot/time-travel result does not match",
        ),
        (
            lambda value: value["post_spark"]["table"]["projection"][
                "columns"
            ].pop(),
            "Gravitino API did not read back Spark schema evolution",
        ),
        (
            lambda value: value["post_spark"].update(
                {"denied_catalog_create_status": 200}
            ),
            "Post-Spark administrative catalog mutation was not denied",
        ),
    ],
)
def test_evidence_rejects_data_snapshot_schema_or_denial_drift(mutate, expected):
    observation = _observation()
    mutate(observation)

    evidence = interop.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["local_spark_iceberg_rest_interoperability_verified"] is False


def test_evidence_recomputes_api_fingerprint_instead_of_trusting_it():
    observation = _observation()
    projection = observation["post_spark"]["table"]["projection"]
    projection["columns"][1]["nullable"] = False
    observation["post_spark"]["table"]["fingerprint"] = (
        interop.recovery._canonical_sha256(projection)
    )

    evidence = interop.build_evidence(observation)

    assert "Gravitino API did not read back Spark schema evolution" in evidence["errors"]
    assert evidence["gravitino_api_metadata_readback_verified"] is False


def test_evidence_rejects_incomplete_cleanup_and_sensitive_material():
    observation = _observation()
    observation["runtime_checks"]["namespace_absent"] = False
    observation["database_password"] = "must-not-enter-evidence"

    evidence = interop.build_evidence(observation)

    assert "Spark interoperability observation contains sensitive material" in evidence[
        "errors"
    ]
    assert "Spark interoperability cleanup is incomplete" in evidence["errors"]
    assert evidence["local_spark_iceberg_rest_interoperability_verified"] is False


def test_evidence_integrity_rejects_tampering_and_production_overclaim():
    evidence = _checked_evidence()
    evidence["observation"]["spark"]["result"]["current_rows"][0][0] = "tampered"

    errors = interop.verify_evidence_integrity(evidence)

    assert "Spark interoperability evidence fingerprint does not match" in errors

    forged = _checked_evidence()
    forged["spark_conformance_verified"] = True
    forged["production_ready"] = True
    stable = {
        key: value for key, value in forged.items() if key != "evidence_fingerprint"
    }
    forged["evidence_fingerprint"] = interop.recovery._canonical_sha256(stable)
    errors = interop.verify_evidence_integrity(forged)
    assert (
        "Spark interoperability evidence may not claim spark_conformance_verified"
        in errors
    )
    assert "Spark interoperability evidence may not claim production_ready" in errors


def test_wrapper_is_fail_closed():
    wrapper = interop.DEFAULT_WRAPPER_PATH.read_text(encoding="utf-8")

    assert "set -euo pipefail" in wrapper
    assert "metadata_fabric_spark_iceberg_rest_interoperability" in wrapper
