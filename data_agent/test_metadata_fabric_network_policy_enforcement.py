import hashlib
import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from data_agent import metadata_fabric_network_policy_enforcement as enforcement
from data_agent import metadata_fabric_recovery_rehearsal as recovery


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _probe(outcome: str) -> dict:
    connected = outcome == "connected"
    return {
        "exec_channel_healthy": True,
        "outcome": outcome,
        "response_valid": connected,
        "response_sha256": (
            hashlib.sha256(enforcement.SUCCESS_BODY.encode("utf-8")).hexdigest()
            if connected
            else None
        ),
        "return_code": 0 if connected else 1,
        "duration_seconds": 0.01,
        "raw_response_retained": False,
    }


def _observation() -> dict:
    contract = enforcement.build_network_policy_contract_report()
    pods = {}
    for name in sorted(enforcement.PODS):
        server = name == "probe-server"
        pods[name] = {
            "uid": f"{name}-uid",
            "node": enforcement.SERVER_NODE if server else enforcement.CLIENT_NODE,
            "ip": "10.244.0.10" if server else "10.244.1.10",
            "image": enforcement.PROBE_IMAGE,
            "service_account": "probe",
            "labels": {
                **enforcement.RESOURCE_LABELS,
                "role": "server" if server else "client",
                **(
                    {}
                    if server
                    else {
                        "access": (
                            "allowed" if name == "probe-allowed" else "denied"
                        )
                    }
                ),
            },
            "ready": True,
        }
    stages = []
    for sequence, expected in enumerate(enforcement.STAGE_CONTRACT, start=1):
        stages.append(
            {
                "name": expected["name"],
                "sequence": sequence,
                "active_policies": expected["policies"],
                "attempt_count": 1,
                "clients": {
                    client: _probe(outcome)
                    for client, outcome in expected["expected"].items()
                },
                "pods_ready_after_probe": True,
            }
        )
    return {
        "schema": enforcement.OBSERVATION_SCHEMA,
        "observed_at": (NOW + timedelta(seconds=10)).isoformat(),
        "started_at": NOW.isoformat(),
        "duration_seconds": 10.0,
        "contract": {
            "local_static_contract_verified": True,
            "contract_fingerprint": contract["contract_fingerprint"],
        },
        "cluster": {
            "context": enforcement.CONTEXT,
            "uid": "cluster-uid",
            "server_version": enforcement.SERVER_VERSION,
            "nodes": {
                name: {
                    "uid": f"{name}-uid",
                    "version": enforcement.SERVER_VERSION,
                    "internal_ip": f"192.168.65.{index}",
                    "ready": True,
                }
                for index, name in enumerate(
                    (enforcement.SERVER_NODE, enforcement.CLIENT_NODE), start=3
                )
            },
            "cni": {
                "namespace": enforcement.CNI_NAMESPACE,
                "daemonset": enforcement.CNI_DAEMONSET,
                "uid": "kindnet-uid",
                "image": enforcement.CNI_IMAGE,
                "desired": 2,
                "ready": 2,
                "available": 2,
            },
        },
        "resources": {
            "namespace": {
                "name": enforcement.NAMESPACE,
                "uid": "namespace-uid",
                "labels": enforcement.RUNTIME_NAMESPACE_LABELS,
            },
            "pods": pods,
            "service": {
                "name": enforcement.PROBE_SERVICE,
                "uid": "service-uid",
                "type": "ClusterIP",
                "cluster_ip": "10.96.0.20",
                "ports": [enforcement.PROBE_PORT],
            },
            "policies": {
                name: {
                    "uid": f"{name}-uid",
                    "spec_fingerprint": recovery._canonical_sha256(spec),
                }
                for name, spec in enforcement.EXPECTED_POLICY_SPECS.items()
            },
        },
        "stages": stages,
        "runtime_checks": {
            "namespace_absent_before_apply": True,
            "base_apply_completed": True,
            "probe_pods_ready": True,
            "cross_node_placement_verified": True,
            "policies_applied": {name: True for name in enforcement.POLICY_FILES},
            "runtime_resource_inventory": enforcement.EXPECTED_RUNTIME_RESOURCES,
            "runtime_resource_inventory_matches": True,
            "cleanup_command_completed": True,
            "ephemeral_namespace_removed": True,
            "remaining_resources": [],
            "provider_identities_preserved": True,
            "cluster_and_cni_identities_preserved": True,
            "metadata_provider_namespaces_modified": False,
            "kubernetes_credential_resources_requested": False,
            "persistent_volume_resources_requested": False,
            "rbac_resources_requested": False,
        },
    }


def test_static_contract_is_bounded_and_valid():
    report = enforcement.build_network_policy_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["local_network_policy_enforcement_verified"] is False
    assert report["production_network_policy_enforcement_verified"] is False
    assert report["metadata_provider_network_policy_verified"] is False
    assert report["runtime_resource_inventory"] == enforcement.EXPECTED_RUNTIME_RESOURCES
    assert all(
        not Path(item["path"]).is_absolute() for item in report["files"].values()
    )


def test_static_contract_rejects_profile_inventory_drift_and_overclaim(tmp_path):
    profile = yaml.safe_load(enforcement.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["unexpected"] = True
    profile["claims"]["production_ready"] = True
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = enforcement.build_network_policy_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "profile field inventory" in rendered
    assert "production_ready" in rendered


def test_static_contract_rejects_manifest_process_storage_and_privilege_drift(
    tmp_path,
):
    target = tmp_path / "manifests"
    shutil.copytree(enforcement.DEFAULT_MANIFEST_DIR, target)
    base_path = target / "base.yaml"
    documents = list(yaml.safe_load_all(base_path.read_text(encoding="utf-8")))
    service = next(item for item in documents if item.get("kind") == "Service")
    service["metadata"]["labels"] = {}
    server = next(
        item
        for item in documents
        if item.get("kind") == "Pod"
        and item.get("metadata", {}).get("name") == "probe-server"
    )
    container = server["spec"]["containers"][0]
    container["command"] = ["/bin/sh", "-c", "exec sleep 3600"]
    container["securityContext"]["privileged"] = True
    container["securityContext"]["capabilities"]["add"] = ["NET_ADMIN"]
    server["spec"]["volumes"] = [{"name": "host", "hostPath": {"path": "/"}}]
    base_path.write_text(yaml.safe_dump_all(documents), encoding="utf-8")

    report = enforcement.build_network_policy_contract_report(manifest_dir=target)

    assert report["local_static_contract_verified"] is False
    rendered = "\n".join(report["errors"])
    assert "Service/probe-server cleanup label" in rendered
    assert "Pod/probe-server security context" in rendered
    assert "forbidden volume" in rendered
    assert "server process or storage contract" in rendered


def test_runtime_inventory_and_readiness_tolerate_malformed_nested_objects():
    class Runner:
        def kubectl_json(self, args, *, label):
            if args[3] == "pods":
                return {"items": [{"metadata": None, "status": None}]}
            return {"items": "not-a-list"}

    runner = Runner()

    assert enforcement._runtime_resource_inventory(runner) == ["Pod/None"]
    assert enforcement._all_probe_pods_ready(runner) is False


def test_runtime_policy_normalization_restores_api_omitted_default_deny_rules():
    ingress = deepcopy(
        enforcement.EXPECTED_POLICY_SPECS["probe-server-default-deny"]
    )
    ingress.pop("ingress")
    egress = deepcopy(
        enforcement.EXPECTED_POLICY_SPECS["probe-authorized-default-deny"]
    )
    egress.pop("egress")

    assert enforcement._normalized_runtime_policy_spec(ingress) == (
        enforcement.EXPECTED_POLICY_SPECS["probe-server-default-deny"]
    )
    assert enforcement._normalized_runtime_policy_spec(egress) == (
        enforcement.EXPECTED_POLICY_SPECS["probe-authorized-default-deny"]
    )


def test_valid_evidence_proves_exactly_five_local_enforcement_stages():
    report = enforcement.build_network_policy_evidence(
        _observation(), now=NOW + timedelta(seconds=10)
    )

    assert report["status"] == "local_network_policy_enforcement_verified"
    assert report["local_network_policy_enforcement_verified"] is True
    assert report["production_network_policy_enforcement_verified"] is False
    assert report["metadata_provider_network_policy_verified"] is False
    assert report["tenant_isolation_verified"] is False
    assert report["production_ready"] is False
    assert [stage["name"] for stage in report["observation"]["stages"]] == [
        stage["name"] for stage in enforcement.STAGE_CONTRACT
    ]
    assert enforcement.verify_evidence_integrity(report) == []


def test_evidence_blocks_stage_cni_server_and_node_drift():
    observation = _observation()
    observation["stages"][2]["clients"]["allowed"] = _probe("blocked")
    observation["cluster"]["server_version"] = "v1.36.1"
    observation["cluster"]["nodes"][enforcement.CLIENT_NODE]["ready"] = False
    observation["cluster"]["cni"]["image"] = "kindnet:unapproved"

    report = enforcement.build_network_policy_evidence(
        observation, now=NOW + timedelta(seconds=10)
    )

    assert report["status"] == "blocked"
    rendered = "\n".join(report["errors"])
    assert "cluster identity or server version" in rendered
    assert f"node identity is not ready: {enforcement.CLIENT_NODE}" in rendered
    assert "kindnet identity/readiness" in rendered
    assert "ingress_authorized/allowed" in rendered


def test_evidence_blocks_cleanup_provider_identity_and_resource_failures():
    observation = _observation()
    observation["resources"]["namespace"]["labels"] = enforcement.NAMESPACE_LABELS
    observation["runtime_checks"]["ephemeral_namespace_removed"] = False
    observation["runtime_checks"]["remaining_resources"] = ["Pod/probe-server"]
    observation["runtime_checks"]["provider_identities_preserved"] = False

    report = enforcement.build_network_policy_evidence(
        observation, now=NOW + timedelta(seconds=10)
    )

    assert report["status"] == "blocked"
    rendered = "\n".join(report["errors"])
    assert "runtime Namespace identity" in rendered
    assert "ephemeral_namespace_removed" in rendered
    assert "provider_identities_preserved" in rendered
    assert "resources remain after cleanup" in rendered


def test_evidence_blocks_stale_contract_and_sensitive_fields():
    observation = _observation()
    observation["contract"]["contract_fingerprint"] = "0" * 64
    observation["api_token"] = "must-not-be-recorded"

    report = enforcement.build_network_policy_evidence(
        observation, now=NOW + timedelta(seconds=10)
    )

    assert report["status"] == "blocked"
    rendered = "\n".join(report["errors"])
    assert "credential-bearing fields" in rendered
    assert "contract fingerprint is stale" in rendered


def test_integrity_verifier_rejects_tampering_and_production_overclaim():
    report = enforcement.build_network_policy_evidence(
        _observation(), now=NOW + timedelta(seconds=10)
    )
    tampered = deepcopy(report)
    tampered["production_ready"] = True

    errors = enforcement.verify_evidence_integrity(tampered)

    assert "NetworkPolicy evidence fingerprint does not match" in errors
    assert "NetworkPolicy evidence may not claim production_ready" in errors
    assert "api_token" not in json.dumps(report)


def test_committed_network_policy_evidence_is_integral_and_current():
    evidence_path = (
        Path(__file__).resolve().parent.parent
        / "docs/evidence/metadata-fabric-network-policy-enforcement-2026-07-28.json"
    )
    report = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert enforcement.verify_evidence_integrity(report) == []
    assert report["observation"]["contract"]["contract_fingerprint"] == (
        enforcement.build_network_policy_contract_report()["contract_fingerprint"]
    )
    assert report["local_network_policy_enforcement_verified"] is True
    assert report["production_network_policy_enforcement_verified"] is False
    assert report["metadata_provider_network_policy_verified"] is False
    assert report["production_ready"] is False
