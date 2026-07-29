import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import SecretStr

from data_agent import metadata_fabric_spark_commit_failure_recovery as dependency
from data_agent import metadata_fabric_spark_uncertain_commit_reconciliation as reconcile


def _dependency_observation() -> dict:
    evidence = json.loads(dependency.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    return deepcopy(evidence["observation"])


def _synthetic_observation() -> dict:
    observation = _dependency_observation()
    observation["schema"] = reconcile.OBSERVATION_SCHEMA
    observation["contract"] = {
        "contract_fingerprint": reconcile.build_contract_report()[
            "contract_fingerprint"
        ],
        "local_static_contract_verified": True,
        "dependency_evidence_fingerprint": (
            reconcile.DEPENDENCY_EVIDENCE_FINGERPRINT
        ),
    }
    old = observation["spark"]["result"]
    final = deepcopy(old["retry"])
    final["rows"] = [
        "spark-baseline-a",
        "spark-baseline-b",
        "spark-uncertain-commit",
    ]
    observation["spark"]["result"] = {
        "schema": "gda.spark_uncertain_commit_reconciliation_probe_result.v1",
        "spark_version": old["spark_version"],
        "iceberg_runtime": old["iceberg_runtime"],
        "catalog_uri": old["catalog_uri"],
        "catalog_upstream": old["catalog_upstream"],
        "warehouse": old["warehouse"],
        "object_store_endpoint": old["object_store_endpoint"],
        "file_io": old["file_io"],
        "table": old["table"],
        "initial_columns": old["initial_columns"],
        "initial_rows": old["initial_rows"],
        "initial_snapshots": old["initial_snapshots"],
        "baseline": deepcopy(old["baseline"]),
        "uncertain_attempt": {
            "exception_observed": True,
            "exception_type": "Py4JJavaError",
            "logical_row": "spark-uncertain-commit",
        },
        "reconciliation": {
            "decision": "committed_do_not_resubmit",
            "readback_attempts": 1,
            "write_resubmitted": False,
            **final,
        },
        "proxy": {
            "forwarded_commit_requests": 2,
            "uncertain_commit_forwarded_requests": 1,
            "provider_success_responses_dropped": 1,
            "suppressed_duplicate_commit_requests": 1,
            "provider_success_status": 200,
            "total_requests": 10,
            "injection_mode": "post_forward_success_response_drop_http_504",
            "provider_commit_forwarded": True,
            "loopback_only": True,
        },
        "provider_committed_response_loss_verified": True,
        "commit_outcome_readback_verified": True,
        "duplicate_resubmission_prevented": True,
        "single_visible_commit_verified": True,
        "object_store_data_files_verified": True,
        "material_recorded": False,
    }
    return observation


def _write_profile(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_checked_contract_and_evidence_verify_uncertain_commit_reconciliation():
    contract = reconcile.build_contract_report()
    validation = reconcile.build_validation_report()
    evidence = json.loads(reconcile.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert contract["contract_fingerprint"] == (
        "7a8d75a1d6b4558b982c6c3242d8d356c5046955f8aae7a45e5c297b6f4d4132"
    )
    assert reconcile.verify_evidence_integrity(evidence) == []
    assert evidence["evidence_fingerprint"] == (
        "d6462fff78d07047311b1f715d5f2c7f08c0ce8fbdd5c8b26a3d95ddc3474786"
    )
    assert validation["errors"] == []
    assert validation["local_spark_uncertain_commit_reconciliation_verified"] is True
    assert validation["local_provider_committed_response_loss_verified"] is True
    assert validation["local_commit_outcome_readback_verified"] is True
    assert validation["local_duplicate_resubmission_prevented"] is True
    assert validation["local_single_visible_commit_verified"] is True
    for claim in reconcile.PRODUCTION_FALSE_CLAIMS:
        assert validation[claim] is False


def test_checked_evidence_contains_response_loss_readback_and_object_proof():
    evidence = json.loads(reconcile.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    observation = evidence["observation"]
    result = observation["spark"]["result"]
    baseline = result["baseline"]
    reconciled = result["reconciliation"]
    proxy = result["proxy"]
    store = observation["object_store"]

    assert proxy["uncertain_commit_forwarded_requests"] == 1
    assert proxy["provider_success_responses_dropped"] == 1
    assert proxy["suppressed_duplicate_commit_requests"] == 1
    assert proxy["provider_success_status"] == 200
    assert reconciled["decision"] == "committed_do_not_resubmit"
    assert reconciled["write_resubmitted"] is False
    assert len(reconciled["snapshots"]) == len(baseline["snapshots"]) + 1
    assert reconciled["snapshots"][1]["parent_id"] == (
        reconciled["snapshots"][0]["snapshot_id"]
    )
    assert reconciled["rows"] == [
        "spark-baseline-a",
        "spark-baseline-b",
        "spark-uncertain-commit",
    ]
    assert store["object_count"] == 9
    assert len(store["data_keys"]) == 2
    assert len(store["metadata_keys"]) == 3
    assert len(store["manifest_keys"]) == 4


def test_static_contract_binds_post_forward_reconciliation():
    contract = reconcile.build_contract_report()

    assert contract["errors"] == []
    assert contract["local_static_contract_verified"] is True
    assert contract["failure_injection"] == {
        "boundary": "iceberg_rest_table_commit_response",
        "mode": "post_forward_success_response_drop_http_504",
        "scope": "single_spark_driver_loopback_proxy",
        "provider_commit_forwarded": True,
        "provider_success_response_delivered": False,
    }
    assert contract["reconciliation"]["write_resubmissions"] == 0
    assert contract["dependency_evidence_fingerprint"] == (
        dependency.build_validation_report()["evidence_fingerprint"]
    )
    for claim in reconcile.PRODUCTION_FALSE_CLAIMS:
        assert contract[claim] is False


def test_synthetic_observation_proves_one_commit_without_resubmission():
    evidence = reconcile.build_evidence(_synthetic_observation())

    assert evidence["errors"] == []
    assert evidence["local_spark_uncertain_commit_reconciliation_verified"] is True
    assert evidence["local_provider_committed_response_loss_verified"] is True
    assert evidence["local_commit_outcome_readback_verified"] is True
    assert evidence["local_duplicate_resubmission_prevented"] is True
    assert evidence["local_single_visible_commit_verified"] is True
    for claim in reconcile.PRODUCTION_FALSE_CLAIMS:
        assert evidence[claim] is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["spark"]["result"]["reconciliation"].update(
                {"write_resubmitted": True}
            ),
            "not reconciled from readback",
        ),
        (
            lambda value: value["spark"]["result"]["reconciliation"].update(
                {"decision": "retry_write"}
            ),
            "not reconciled from readback",
        ),
        (
            lambda value: value["spark"]["result"]["reconciliation"][
                "rows"
            ].append("spark-uncertain-commit"),
            "not reconciled from readback",
        ),
        (
            lambda value: value["spark"]["result"]["reconciliation"][
                "snapshots"
            ][1].update({"parent_id": 99}),
            "not reconciled from readback",
        ),
        (
            lambda value: value["spark"]["result"]["proxy"].update(
                {"provider_success_responses_dropped": 0}
            ),
            "proxy observation does not match",
        ),
        (
            lambda value: value["spark"]["result"]["proxy"].update(
                {"provider_commit_forwarded": False}
            ),
            "proxy observation does not match",
        ),
        (
            lambda value: value["spark"]["result"].update(
                {"duplicate_resubmission_prevented": False}
            ),
            "local claims do not match",
        ),
    ],
)
def test_evidence_rejects_uncertain_outcome_or_duplicate_drift(mutate, expected):
    observation = _synthetic_observation()
    mutate(observation)

    evidence = reconcile.build_evidence(observation)

    assert any(expected in error for error in evidence["errors"])
    assert evidence["local_spark_uncertain_commit_reconciliation_verified"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["spark"]["result"]["reconciliation"].update(
            {"rows": 1}
        ),
        lambda value: value["spark"]["result"]["reconciliation"].update(
            {"snapshots": 1}
        ),
        lambda value: value["spark"]["result"]["reconciliation"].update(
            {"data_file_paths": 1}
        ),
        lambda value: value["object_store"].update({"objects": 1}),
        lambda value: value["object_store"].update({"data_keys": 1}),
        lambda value: value["object_store"].update({"metadata_keys": 1}),
        lambda value: value["object_store"].update({"manifest_keys": 1}),
    ],
)
def test_evidence_fails_closed_for_malformed_collection_fields(mutate):
    observation = _synthetic_observation()
    mutate(observation)

    evidence = reconcile.build_evidence(observation)

    assert evidence["errors"]
    assert evidence["local_spark_uncertain_commit_reconciliation_verified"] is False


def test_profile_rejects_sensitive_material_and_dependency_drift(
    tmp_path, monkeypatch
):
    profile = yaml.safe_load(reconcile.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["catalog"]["secret_access_key"] = "must-not-enter-profile"
    with pytest.raises(
        reconcile.MetadataFabricSparkUncertainCommitReconciliationError,
        match="profile is invalid",
    ):
        reconcile.load_profile(_write_profile(tmp_path, profile))

    profile = yaml.safe_load(reconcile.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    dependency_value = json.loads(
        dependency.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )
    dependency_value["production_ready"] = True
    dependency_path = (
        tmp_path
        / "docs/evidence/metadata-fabric-spark-commit-failure-recovery-2026-07-29.json"
    )
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_text(json.dumps(dependency_value), encoding="utf-8")
    monkeypatch.setattr(reconcile, "REPO_ROOT", tmp_path)
    with pytest.raises(
        reconcile.MetadataFabricSparkUncertainCommitReconciliationError,
        match="dependency does not match",
    ):
        reconcile.load_profile(_write_profile(tmp_path, profile))


def test_evidence_integrity_rejects_sensitive_or_production_claims():
    observation = _synthetic_observation()
    observation["runtime_secret"] = "must-not-enter-evidence"
    evidence = reconcile.build_evidence(observation)
    assert any("contains sensitive material" in error for error in evidence["errors"])

    checked = reconcile.build_evidence(_synthetic_observation())
    forged = deepcopy(checked)
    forged["production_ready"] = True
    assert reconcile.verify_evidence_integrity(forged)
    assert any(
        "may not claim production_ready" in error
        for error in reconcile.verify_evidence_integrity(forged)
    )


def test_runtime_replaces_suspended_probe_before_release(monkeypatch):
    profile = reconcile.load_profile()
    calls = []

    monkeypatch.setattr(
        dependency.IsolatedSparkCommitFailureRuntime,
        "start",
        lambda _self, **_kwargs: {"runtime": "observed"},
    )
    runtime = reconcile.IsolatedSparkUncertainCommitRuntime(profile)

    class FakeKubectl:
        def run(self, args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(stdout="")

    runtime.kubectl = FakeKubectl()
    observed = runtime.start(
        admin_material=SecretStr("admin"),
        database_material=SecretStr("database"),
        object_store_user=SecretStr("object-user"),
        object_store_material=SecretStr("object-material"),
    )

    assert observed == {"runtime": "observed"}
    assert len(calls) == 1
    args, _kwargs = calls[0]
    assert args[2:5] == ["patch", "configmap", profile.runtime.spark_job]
    payload = json.loads(args[args.index("-p") + 1])
    assert "committed_do_not_resubmit" in payload["data"]["probe.py"]


def test_probe_and_wrapper_are_fail_closed():
    probe = reconcile.DEFAULT_PROBE_PATH.read_text(encoding="utf-8")
    wrapper = reconcile.DEFAULT_WRAPPER_PATH.read_text(encoding="utf-8")

    assert probe.count(".writeTo(TABLE)") == 2
    assert "post_forward_success_response_drop_http_504" in probe
    assert '"write_resubmitted": False' in probe
    assert "set -euo pipefail" in wrapper
    assert "metadata_fabric_spark_uncertain_commit_reconciliation" in wrapper


def test_validation_without_checked_evidence_fails_closed(tmp_path):
    report = reconcile.build_validation_report(evidence_path=tmp_path / "missing.json")

    assert report["errors"]
    assert report["local_spark_uncertain_commit_reconciliation_verified"] is False
    assert report["spark_reconcile_verified"] is False
