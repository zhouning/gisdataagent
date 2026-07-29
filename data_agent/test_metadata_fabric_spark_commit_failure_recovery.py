import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import SecretStr

from data_agent import metadata_fabric_spark_commit_failure_recovery as recovery


def _checked_evidence() -> dict:
    return json.loads(recovery.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _observation() -> dict:
    return deepcopy(_checked_evidence()["observation"])


def _write_profile(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_checked_contract_and_evidence_verify_commit_failure_recovery():
    contract = recovery.build_contract_report()
    validation = recovery.build_validation_report()
    evidence = _checked_evidence()

    assert contract["local_static_contract_verified"] is True
    assert contract["contract_fingerprint"] == (
        "6d8944ab80246dc65891aa81118cb8b73f7ecad699be9a2af5e62d8260c41002"
    )
    assert recovery.verify_evidence_integrity(evidence) == []
    assert evidence["evidence_fingerprint"] == (
        "39571cdac1e4043bcfc2d03a73b2b12ff925210daf8ae36bc640b8cb14d89401"
    )
    assert validation["errors"] == []
    assert validation["local_spark_commit_failure_recovery_verified"] is True
    assert validation["local_failed_commit_atomicity_verified"] is True
    assert validation["local_retry_recovery_verified"] is True
    assert validation["local_exactly_once_visible_effect_verified"] is True
    assert validation["gravitino_api_metadata_readback_verified"] is True
    assert validation["local_cross_node_object_store_verified"] is True
    assert validation["object_store_metadata_verified"] is True
    for claim in recovery.PRODUCTION_FALSE_CLAIMS:
        assert validation[claim] is False


def test_checked_evidence_contains_atomic_snapshot_row_and_object_proof():
    observation = _observation()
    result = observation["spark"]["result"]
    baseline = result["baseline"]
    failed = result["failed_attempt"]
    retried = result["retry"]
    store = observation["object_store"]

    assert failed["snapshots"] == baseline["snapshots"]
    assert failed["rows"] == baseline["rows"]
    assert failed["data_file_paths"] == baseline["data_file_paths"]
    assert len(retried["snapshots"]) == 2
    assert retried["snapshots"][1]["parent_id"] == retried["snapshots"][0][
        "snapshot_id"
    ]
    assert retried["rows"] == [
        "spark-baseline-a",
        "spark-baseline-b",
        "spark-recovery",
    ]
    assert result["proxy"]["failed_commit_requests"] == 2
    assert result["proxy"]["forwarded_commit_requests"] == 2
    assert store["object_count"] == 9
    assert len(store["data_keys"]) == 2
    assert len(store["metadata_keys"]) == 3
    assert len(store["manifest_keys"]) == 4
    assert store["data_keys"] == sorted(
        path.removeprefix("s3://gda-metadata-warehouse/")
        for path in retried["data_file_paths"]
    )


def test_profile_rejects_privilege_expansion_and_sensitive_fields(tmp_path):
    profile = yaml.safe_load(recovery.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["scope"]["role_securable_objects"][1]["privileges"].append(
        {"name": "MODIFY_TABLE", "condition": "ALLOW"}
    )
    profile["catalog"]["secret_access_key"] = "must-not-enter-profile"

    with pytest.raises(
        recovery.MetadataFabricSparkCommitFailureRecoveryError,
        match="profile is invalid",
    ):
        recovery.load_profile(_write_profile(tmp_path, profile))


def test_profile_rejects_tampered_object_store_dependency(tmp_path, monkeypatch):
    profile = yaml.safe_load(recovery.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    dependency = json.loads(
        (
            recovery.REPO_ROOT
            / "docs/evidence/metadata-fabric-spark-object-store-interoperability-2026-07-29.json"
        ).read_text(encoding="utf-8")
    )
    dependency["production_ready"] = True
    dependency_path = (
        tmp_path
        / "docs/evidence/metadata-fabric-spark-object-store-interoperability-2026-07-29.json"
    )
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_text(json.dumps(dependency), encoding="utf-8")
    monkeypatch.setattr(recovery, "REPO_ROOT", tmp_path)

    with pytest.raises(
        recovery.MetadataFabricSparkCommitFailureRecoveryError,
        match="dependency does not match",
    ):
        recovery.load_profile(_write_profile(tmp_path, profile))


def test_manifest_rejects_committed_secret_and_incomplete_runtime(
    tmp_path, monkeypatch
):
    (tmp_path / "runtime.yaml").write_text(
        """
apiVersion: v1
kind: Namespace
metadata:
  name: gda-metadata-spark-commit-failure
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
    monkeypatch.setattr(recovery, "MANIFEST_DIR", tmp_path)

    errors = recovery._validate_manifest()

    assert "Spark commit-failure manifest may not commit Secret values" in errors
    assert "Spark commit-failure manifest is incomplete" in errors


def test_manifest_requires_suspended_tokenless_pvcless_job(monkeypatch):
    documents = recovery._manifest_documents()
    job = next(document for document in documents if document.get("kind") == "Job")
    job["spec"]["suspend"] = False
    job["spec"]["backoffLimit"] = 1
    pod_spec = job["spec"]["template"]["spec"]
    pod_spec["automountServiceAccountToken"] = True
    pod_spec["volumes"].append(
        {
            "name": "warehouse",
            "persistentVolumeClaim": {"claimName": "forbidden-warehouse"},
        }
    )
    pod_spec["containers"][0].pop("resources")
    monkeypatch.setattr(recovery, "_manifest_documents", lambda: documents)

    errors = recovery._validate_manifest()

    assert "Spark commit-failure Job retry boundary does not match" in errors
    assert "Spark commit-failure Job must disable token automount" in errors
    assert "Spark commit-failure Job may not mount a warehouse PVC" in errors
    assert "Spark commit-failure Job resources are incomplete" in errors


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["spark"]["result"]["failed_attempt"]["rows"].append(
                "spark-recovery"
            ),
            "Spark failed commit changed visible state",
        ),
        (
            lambda value: value["spark"]["result"]["failed_attempt"][
                "snapshots"
            ].append({"snapshot_id": 3, "parent_id": 2, "operation": "append"}),
            "Spark failed commit changed visible state",
        ),
        (
            lambda value: value["spark"]["result"]["failed_attempt"][
                "data_file_paths"
            ].append("s3://gda-metadata-warehouse/forged.parquet"),
            "Spark failed commit changed visible state",
        ),
        (
            lambda value: value["spark"]["result"]["baseline"].update(
                {"data_file_paths": 1}
            ),
            "Spark commit-failure baseline does not match",
        ),
        (
            lambda value: value["spark"]["result"]["retry"]["rows"].append(
                "spark-recovery"
            ),
            "Spark commit retry visible state does not match",
        ),
        (
            lambda value: value["spark"]["result"]["retry"]["snapshots"][
                1
            ].update({"parent_id": 99}),
            "Spark commit retry visible state does not match",
        ),
        (
            lambda value: value["spark"]["result"]["proxy"].update(
                {"failed_commit_requests": 1}
            ),
            "Spark commit-failure proxy observation does not match",
        ),
    ],
)
def test_evidence_rejects_atomicity_retry_or_proxy_drift(mutate, expected):
    observation = _observation()
    mutate(observation)

    evidence = recovery.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["local_spark_commit_failure_recovery_verified"] is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["object_store"]["data_keys"].append(
                "warehouse/published/gda_spark_commit_failure_probe/data/orphan.parquet"
            ),
            "Commit-failure object-store inventory does not match",
        ),
        (
            lambda value: value["object_store"]["metadata_keys"].pop(),
            "Commit-failure object-store inventory does not match",
        ),
        (
            lambda value: value["object_store"].update({"manifest_keys": 1}),
            "Commit-failure object-store inventory does not match",
        ),
        (
            lambda value: value["object_store"]["objects"][0].update({"size": 0}),
            "Commit-failure object-store inventory does not match",
        ),
        (
            lambda value: value["object_store"]["latest_metadata"].update(
                {"current_snapshot_id": 1}
            ),
            "Commit-failure Iceberg metadata projection does not match",
        ),
    ],
)
def test_evidence_rejects_direct_object_store_or_metadata_drift(mutate, expected):
    observation = _observation()
    mutate(observation)

    evidence = recovery.build_evidence(observation)

    assert expected in evidence["errors"]
    assert evidence["object_store_metadata_verified"] is False


def test_evidence_rejects_incomplete_cleanup_and_sensitive_material():
    observation = _observation()
    observation["runtime_checks"]["persistent_volumes_absent"] = False
    observation["object_store_secret_access_key"] = "must-not-enter-evidence"

    evidence = recovery.build_evidence(observation)

    assert "Spark commit-failure observation contains sensitive material" in evidence[
        "errors"
    ]
    assert "Spark commit-failure rehearsal cleanup is incomplete" in evidence["errors"]
    assert evidence["local_spark_commit_failure_recovery_verified"] is False


def test_evidence_integrity_rejects_tampering_and_production_overclaim():
    evidence = _checked_evidence()
    evidence["observation"]["spark"]["result"]["retry"]["rows"].append(
        "spark-recovery"
    )

    errors = recovery.verify_evidence_integrity(evidence)

    assert "Spark commit-failure evidence fingerprint does not match" in errors

    forged = _checked_evidence()
    forged["production_object_store_verified"] = True
    forged["spark_conformance_verified"] = True
    forged["production_ready"] = True
    stable = {
        key: value for key, value in forged.items() if key != "evidence_fingerprint"
    }
    forged["evidence_fingerprint"] = recovery.recovery._canonical_sha256(stable)
    errors = recovery.verify_evidence_integrity(forged)
    assert (
        "Spark commit-failure evidence may not claim production_object_store_verified"
        in errors
    )
    assert "Spark commit-failure evidence may not claim spark_conformance_verified" in errors
    assert "Spark commit-failure evidence may not claim production_ready" in errors


def test_runtime_start_uses_commit_failure_manifest(monkeypatch):
    profile = recovery.load_profile()
    runtime = recovery.IsolatedSparkCommitFailureRuntime(profile)
    calls = []

    class FakeKubectl:
        def get_json(self, *_args, **_kwargs):
            return None

        def run(self, args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(stdout="")

    runtime.kubectl = FakeKubectl()
    monkeypatch.setattr(runtime, "_inspect_host_image", lambda *_args: "verified")
    monkeypatch.setattr(runtime, "_runtime_inputs", lambda **_kwargs: "{}")
    monkeypatch.setattr(runtime, "observe_runtime", lambda: {"verified": True})

    observed = runtime.start(
        admin_material=SecretStr("admin"),
        database_material=SecretStr("database"),
        object_store_user=SecretStr("object-user"),
        object_store_material=SecretStr("object-material"),
    )

    assert observed == {"verified": True}
    assert ["apply", "-f", str(recovery.MANIFEST_DIR / "namespace.yaml")] in [
        call[0] for call in calls
    ]
    assert ["apply", "-k", str(recovery.MANIFEST_DIR)] in [
        call[0] for call in calls
    ]


def test_runtime_probe_uses_dynamic_job_selector_and_result_marker():
    profile = recovery.load_profile()
    runtime = recovery.IsolatedSparkCommitFailureRuntime(profile)
    calls = []
    job = {
        "metadata": {"name": "spark-commit-failure-probe", "uid": "job-uid"},
        "status": {
            "succeeded": 1,
            "conditions": [{"status": "True", "type": "Complete"}],
        },
    }
    pod = {
        "metadata": {"name": "probe-pod", "uid": "pod-uid"},
        "spec": {
            "nodeName": "desktop-worker",
            "serviceAccountName": "spark-commit-failure-probe",
            "automountServiceAccountToken": False,
            "volumes": [],
        },
        "status": {
            "phase": "Succeeded",
            "containerStatuses": [
                {
                    "name": "spark",
                    "image": "spark:local",
                    "imageID": recovery.SPARK_KUBERNETES_IMAGE_ID,
                }
            ],
        },
    }

    class FakeKubectl:
        def get_json(self, args, **_kwargs):
            calls.append(args)
            if "pods" in args:
                return {"items": [pod]}
            return job

        def run(self, args, **_kwargs):
            calls.append(args)
            if "logs" in args:
                return SimpleNamespace(
                    stdout='GDA_SPARK_COMMIT_FAILURE_RESULT={"verified": true}\n'
                )
            return SimpleNamespace(stdout="")

    runtime.kubectl = FakeKubectl()

    observed = runtime.run_spark_probe()

    assert observed["terminal_condition"] == "Complete"
    assert observed["result"] == {"verified": True}
    assert any(
        f"job-name={profile.runtime.spark_job}" in call for call in calls
    )


def test_wrapper_is_fail_closed():
    wrapper = recovery.DEFAULT_WRAPPER_PATH.read_text(encoding="utf-8")

    assert "set -euo pipefail" in wrapper
    assert "metadata_fabric_spark_commit_failure_recovery" in wrapper
