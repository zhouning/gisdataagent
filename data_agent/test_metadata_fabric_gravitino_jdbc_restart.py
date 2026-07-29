import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from data_agent import metadata_fabric_gravitino_jdbc_restart as restart


def _checked_evidence() -> dict:
    return json.loads(restart.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _observation() -> dict:
    return deepcopy(_checked_evidence()["observation"])


def _write_profile(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_checked_in_contract_and_evidence_verify_the_local_boundary():
    contract = restart.build_contract_report()
    validation = restart.build_validation_report()
    evidence = _checked_evidence()

    assert contract["contract_fingerprint"] == (
        "f622d8a61bae49171bc76a16bfe64280c616c028bddf88479f1ad04acb1dadf0"
    )
    assert contract["local_static_contract_verified"] is True
    assert contract["runtime_image_identity"] == {
        "gravitino_host_image_id": restart.GRAVITINO_HOST_IMAGE_ID,
        "gravitino_kubernetes_image_id": restart.GRAVITINO_KUBERNETES_IMAGE_ID,
        "postgresql_image_digest": restart.POSTGRESQL_IMAGE_DIGEST,
    }
    assert restart.verify_evidence_integrity(evidence) == []
    assert validation["errors"] == []
    assert validation["local_gravitino_jdbc_catalog_restart_verified"] is True
    assert validation["local_authenticated_catalog_persistence_verified"] is True
    assert validation["persistent_catalog_identity_binding_verified"] is False
    assert validation["protected_workload_identity_verified"] is False
    assert validation["oidc_verified"] is False
    assert validation["tls_verified"] is False
    assert validation["production_ingestion_verified"] is False
    assert validation["production_ready"] is False


def test_profile_rejects_privilege_expansion_and_sensitive_fields(tmp_path):
    profile = yaml.safe_load(restart.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["scope"]["role_securable_objects"][1]["privileges"].append(
        {"name": "MODIFY_TABLE", "condition": "ALLOW"}
    )
    profile["catalog"]["jdbc_password"] = "must-not-enter-profile"

    with pytest.raises(
        restart.MetadataFabricGravitinoJdbcRestartError,
        match="profile is invalid",
    ):
        restart.load_profile(_write_profile(tmp_path, profile))


def test_profile_rejects_tampered_identity_dependency(tmp_path, monkeypatch):
    profile = yaml.safe_load(restart.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    dependency = json.loads(
        (
            restart.REPO_ROOT
            / "docs/evidence/metadata-fabric-gravitino-identity-2026-07-28.json"
        ).read_text(encoding="utf-8")
    )
    dependency["production_identity_verified"] = True
    dependency_path = (
        tmp_path
        / "docs/evidence/metadata-fabric-gravitino-identity-2026-07-28.json"
    )
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_text(json.dumps(dependency), encoding="utf-8")
    monkeypatch.setattr(restart, "REPO_ROOT", tmp_path)

    with pytest.raises(
        restart.MetadataFabricGravitinoJdbcRestartError,
        match="identity dependency does not match",
    ):
        restart.load_profile(_write_profile(tmp_path, profile))


def test_manifest_rejects_committed_secret_and_incomplete_runtime(
    tmp_path, monkeypatch
):
    (tmp_path / "runtime.yaml").write_text(
        """
apiVersion: v1
kind: Namespace
metadata:
  name: gda-metadata-catalog-persistence
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
    monkeypatch.setattr(restart, "MANIFEST_DIR", tmp_path)

    errors = restart._validate_manifest()

    assert "Gravitino JDBC restart manifest may not commit Secret values" in errors
    assert "Gravitino JDBC restart manifest is incomplete" in errors


def test_manifest_requires_driver_init_container_resources(monkeypatch):
    documents = restart._manifest_documents()
    workload = next(
        document
        for document in documents
        if document.get("kind") == "StatefulSet"
        and document["metadata"]["name"] == "gravitino-persistence"
    )
    driver_init = next(
        item
        for item in workload["spec"]["template"]["spec"]["initContainers"]
        if item["name"] == "stage-postgresql-jdbc-driver"
    )
    driver_init.pop("resources")
    monkeypatch.setattr(restart, "_manifest_documents", lambda: documents)

    assert "Gravitino JDBC driver initContainer resources are incomplete" in (
        restart._validate_manifest()
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["restart"]["after"]["gravitino"].update(
                {"pod_uid": value["restart"]["before"]["gravitino"]["pod_uid"]}
            ),
            "gravitino pod did not restart",
        ),
        (
            lambda value: value["restart"]["after"]["postgresql"]["pvc"].update(
                {"uid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
            ),
            "postgresql PVC identity changed",
        ),
        (
            lambda value: value["restart"]["after"]["gravitino"].update(
                {"image_id": "sha256:" + "0" * 64}
            ),
            "gravitino runtime image ID does not match",
        ),
        (
            lambda value: value["restart"]["after"]["postgresql"].update(
                {"ready_replicas": 0}
            ),
            "postgresql was not ready around restart",
        ),
        (
            lambda value: value["restart"]["before"]["gravitino"].update(
                {"image_id": "sha256:" + "0" * 64}
            ),
            "gravitino runtime image ID does not match",
        ),
        (
            lambda value: value["restart"]["before"]["postgresql"].update(
                {"service_account": "default"}
            ),
            "postgresql service account token isolation failed",
        ),
        (
            lambda value: value["restart"]["before"].update(
                {"gravitino_host_image_id": "sha256:" + "0" * 64}
            ),
            "before runtime boundary does not match",
        ),
    ],
)
def test_evidence_rejects_restart_or_pvc_identity_drift(mutate, expected):
    observation = _observation()
    mutate(observation)

    evidence = restart.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["local_gravitino_jdbc_catalog_restart_verified"] is False
    assert evidence["local_postgresql_pvc_restart_verified"] is False
    assert evidence["local_warehouse_pvc_restart_verified"] is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["post_restart"]["table"].update(
                {"fingerprint": "0" * 64}
            ),
            "JDBC-backed table did not survive restart",
        ),
        (
            lambda value: value["post_restart"]["role"]["securable_objects"][1][
                "privileges"
            ].append({"name": "MODIFY_TABLE", "condition": "ALLOW"}),
            "minimum-privilege role did not survive restart",
        ),
        (
            lambda value: value["post_restart"].update(
                {"denied_catalog_create_status": 200}
            ),
            "administrative catalog mutation was not denied",
        ),
        (
            lambda value: value["post_restart"]["authentication"].update(
                {"bounded_status": 401}
            ),
            "authenticated principals did not survive restart",
        ),
    ],
)
def test_evidence_rejects_table_role_denial_or_authentication_drift(
    mutate, expected
):
    observation = _observation()
    mutate(observation)

    evidence = restart.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["local_authenticated_catalog_persistence_verified"] is False


def test_evidence_recomputes_table_fingerprint_instead_of_trusting_continuity():
    observation = _observation()
    forged_projection = deepcopy(
        observation["pre_restart"]["table"]["projection"]
    )
    forged_projection["columns"][0]["nullable"] = True
    forged_fingerprint = restart.recovery._canonical_sha256(forged_projection)
    for phase in ("pre_restart", "post_restart"):
        observation[phase]["table"]["projection"] = deepcopy(forged_projection)
        observation[phase]["table"]["fingerprint"] = forged_fingerprint

    evidence = restart.build_evidence(observation)

    assert "JDBC-backed table did not survive restart" in evidence["errors"]


def test_evidence_rejects_incomplete_cleanup_and_sensitive_material():
    observation = _observation()
    observation["runtime_checks"]["namespace_absent"] = False
    observation["database_password"] = "must-not-enter-evidence"

    evidence = restart.build_evidence(observation)

    assert "Gravitino JDBC restart observation contains sensitive material" in evidence[
        "errors"
    ]
    assert "Gravitino JDBC restart cleanup is incomplete" in evidence["errors"]
    assert evidence["local_gravitino_jdbc_catalog_restart_verified"] is False


def test_evidence_integrity_rejects_tampering_and_production_overclaim():
    evidence = _checked_evidence()
    evidence["observation"]["post_restart"]["table"]["name"] = "tampered"

    errors = restart.verify_evidence_integrity(evidence)

    assert "Gravitino JDBC restart evidence fingerprint does not match" in errors

    forged = _checked_evidence()
    forged["persistent_catalog_identity_binding_verified"] = True
    forged["production_ready"] = True
    stable = {
        key: value for key, value in forged.items() if key != "evidence_fingerprint"
    }
    forged["evidence_fingerprint"] = restart.recovery._canonical_sha256(stable)
    errors = restart.verify_evidence_integrity(forged)
    assert (
        "Gravitino JDBC restart evidence may not claim "
        "persistent_catalog_identity_binding_verified"
    ) in errors
    assert "Gravitino JDBC restart evidence may not claim production_ready" in errors


def test_wrapper_is_fail_closed():
    wrapper = restart.DEFAULT_WRAPPER_PATH.read_text(encoding="utf-8")

    assert "set -euo pipefail" in wrapper
    assert "metadata_fabric_gravitino_jdbc_restart" in wrapper
