from copy import deepcopy

import yaml

from data_agent import active_metadata_consumer_deployment as deployment


def _documents():
    return list(
        yaml.safe_load_all(
            deployment.DEFAULT_MANIFEST.read_text(encoding="utf-8")
        )
    )


def _write_documents(path, documents):
    path.write_text(
        yaml.safe_dump_all(documents, sort_keys=False),
        encoding="utf-8",
    )


def test_inert_consumer_deployment_is_database_only_and_fail_closed():
    report = deployment.build_deployment_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["expected_replicas"] == 0
    assert report["provider_credentials_present"] is False
    assert report["scheduler_credentials_present"] is False
    assert report["deployment_applied"] is False
    assert report["production_scheduler_submission_verified"] is False
    assert report["production_ready"] is False


def test_validator_rejects_enabled_base_and_scheduler_secret(tmp_path):
    documents = deepcopy(_documents())
    workload = documents[0]
    workload["spec"]["replicas"] = 1
    container = workload["spec"]["template"]["spec"]["containers"][0]
    container["env"].append(
        {"name": "DOLPHINSCHEDULER_TOKEN", "value": "must-not-be-here"}
    )
    unsafe = tmp_path / "unsafe-consumer.yaml"
    _write_documents(unsafe, documents)

    report = deployment.build_deployment_report(unsafe)

    assert report["status"] == "invalid"
    assert "consumer replicas do not match the inert deployment gate" in report[
        "errors"
    ]
    assert "consumer must not receive provider or scheduler secrets" in report[
        "errors"
    ]


def test_validator_rejects_kubernetes_token_and_missing_network_access(tmp_path):
    documents = deepcopy(_documents())
    documents[0]["spec"]["template"]["spec"][
        "automountServiceAccountToken"
    ] = True
    unsafe = tmp_path / "token-enabled.yaml"
    _write_documents(unsafe, documents)

    policies = list(
        yaml.safe_load_all(
            deployment.DEFAULT_NETWORK_POLICY.read_text(encoding="utf-8")
        )
    )
    postgres = next(
        item
        for item in policies
        if item["kind"] == "NetworkPolicy"
        and item["metadata"]["name"] == "postgres-access"
    )
    sources = postgres["spec"]["ingress"][0]["from"]
    postgres["spec"]["ingress"][0]["from"] = [
        source
        for source in sources
        if source.get("podSelector", {}).get("matchLabels", {}).get(
            "app.kubernetes.io/name"
        )
        != deployment.DEPLOYMENT_NAME
    ]
    unsafe_network = tmp_path / "networkpolicy.yaml"
    _write_documents(unsafe_network, policies)

    report = deployment.build_deployment_report(
        unsafe,
        network_policy_path=unsafe_network,
    )

    assert report["status"] == "invalid"
    assert "consumer must disable Kubernetes API token mounting" in report["errors"]
    assert "PostgreSQL NetworkPolicy must admit the consumer selector" in report[
        "errors"
    ]
