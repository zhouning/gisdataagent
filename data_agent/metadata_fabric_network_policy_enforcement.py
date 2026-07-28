"""Verify bounded local Kubernetes NetworkPolicy enforcement.

The runner creates a restricted, short-lived namespace with one HTTP server
on the control-plane node and two clients on the worker node. It proves
baseline connectivity, ingress default-deny, selector-based ingress recovery,
egress default-deny, and DNS/target-specific egress recovery before deleting
the entire namespace. It never changes Metadata Fabric provider workloads and
does not claim that a production cluster or provider policy has been verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery


CONTRACT_SCHEMA = "gda.metadata_fabric_network_policy_enforcement_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_network_policy_enforcement_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_network_policy_enforcement_evidence.v1"
PROFILE_SCHEMA = "gda.metadata_fabric_network_policy_enforcement_profile.v1"

CONTEXT = "docker-desktop"
NAMESPACE = "gda-metadata-network-policy-rehearsal"
SERVER_VERSION = "v1.35.5"
SERVER_NODE = "desktop-control-plane"
CLIENT_NODE = "desktop-worker"
CNI_NAMESPACE = "kube-system"
CNI_DAEMONSET = "kindnet"
CNI_IMAGE = "docker.io/kindest/kindnetd:v20260528-9350166c"
PROBE_IMAGE = (
    "docker.io/library/busybox@"
    "sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662"
)
PART_OF_LABEL = "gda-metadata-network-policy-rehearsal"
PROBE_SERVICE = "probe-server"
PROBE_PORT = 8080
SUCCESS_BODY = "gda-network-policy-ok"
CLIENTS = {"allowed": "probe-allowed", "denied": "probe-denied"}
PODS = {"probe-server", *CLIENTS.values()}

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-network-policy-enforcement.local.yaml"
)
DEFAULT_MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-network-policy-enforcement"
DEFAULT_BASE_PATH = DEFAULT_MANIFEST_DIR / "base.yaml"
DEFAULT_WRAPPER = REPO_ROOT / "scripts/metadata-fabric-network-policy-enforcement.sh"

POLICY_FILES = {
    "probe-server-default-deny": "ingress-default-deny.yaml",
    "probe-server-allow-authorized": "ingress-allow-authorized.yaml",
    "probe-authorized-default-deny": "egress-default-deny.yaml",
    "probe-authorized-allow-dns-and-server": "egress-allow-authorized.yaml",
}
STAGE_CONTRACT = [
    {
        "name": "baseline",
        "policies": [],
        "expected": {"allowed": "connected", "denied": "connected"},
    },
    {
        "name": "ingress_default_deny",
        "policies": ["probe-server-default-deny"],
        "expected": {"allowed": "blocked", "denied": "blocked"},
    },
    {
        "name": "ingress_authorized",
        "policies": [
            "probe-server-default-deny",
            "probe-server-allow-authorized",
        ],
        "expected": {"allowed": "connected", "denied": "blocked"},
    },
    {
        "name": "egress_default_deny",
        "policies": [
            "probe-server-default-deny",
            "probe-server-allow-authorized",
            "probe-authorized-default-deny",
        ],
        "expected": {"allowed": "blocked", "denied": "blocked"},
    },
    {
        "name": "egress_authorized",
        "policies": list(POLICY_FILES),
        "expected": {"allowed": "connected", "denied": "blocked"},
    },
]
EXPECTED_CLAIMS = {
    "local_network_policy_enforcement_verified",
    "production_network_policy_enforcement_verified",
    "metadata_provider_network_policy_verified",
    "tenant_isolation_verified",
    "oidc_verified",
    "upgrade_verified",
    "writes_to_gda_enabled",
    "production_ready",
}
EXPECTED_RUNTIME_RESOURCES = sorted(
    [
        "Pod/probe-allowed",
        "Pod/probe-denied",
        "Pod/probe-server",
        "ResourceQuota/metadata-network-policy-rehearsal",
        "Service/probe-server",
        "ServiceAccount/probe",
        *[f"NetworkPolicy/{name}" for name in POLICY_FILES],
    ]
)
RESOURCE_LABELS = {"app.kubernetes.io/part-of": PART_OF_LABEL}
NAMESPACE_LABELS = {
    **RESOURCE_LABELS,
    "gda.openai.com/environment": "local-network-policy-evidence",
    "gda.openai.com/ephemeral-owner": "metadata-network-policy-rehearsal",
    "pod-security.kubernetes.io/audit": "restricted",
    "pod-security.kubernetes.io/audit-version": "v1.35",
    "pod-security.kubernetes.io/enforce": "restricted",
    "pod-security.kubernetes.io/enforce-version": "v1.35",
    "pod-security.kubernetes.io/warn": "restricted",
    "pod-security.kubernetes.io/warn-version": "v1.35",
}
RUNTIME_NAMESPACE_LABELS = {
    **NAMESPACE_LABELS,
    "kubernetes.io/metadata.name": NAMESPACE,
}
EXPECTED_QUOTA = {
    "pods": "3",
    "services": "1",
    "services.loadbalancers": "0",
    "services.nodeports": "0",
    "count/networkpolicies.networking.k8s.io": "4",
    "requests.cpu": "15m",
    "requests.memory": "24Mi",
    "limits.cpu": "150m",
    "limits.memory": "96Mi",
}
EXPECTED_POLICY_SPECS = {
    "probe-server-default-deny": {
        "podSelector": {"matchLabels": {"role": "server"}},
        "policyTypes": ["Ingress"],
        "ingress": [],
    },
    "probe-server-allow-authorized": {
        "podSelector": {"matchLabels": {"role": "server"}},
        "policyTypes": ["Ingress"],
        "ingress": [
            {
                "from": [
                    {"podSelector": {"matchLabels": {"access": "allowed"}}}
                ],
                "ports": [{"protocol": "TCP", "port": PROBE_PORT}],
            }
        ],
    },
    "probe-authorized-default-deny": {
        "podSelector": {"matchLabels": {"access": "allowed"}},
        "policyTypes": ["Egress"],
        "egress": [],
    },
    "probe-authorized-allow-dns-and-server": {
        "podSelector": {"matchLabels": {"access": "allowed"}},
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {
                                "kubernetes.io/metadata.name": "kube-system"
                            }
                        },
                        "podSelector": {
                            "matchLabels": {"k8s-app": "kube-dns"}
                        },
                    }
                ],
                "ports": [
                    {"protocol": "UDP", "port": 53},
                    {"protocol": "TCP", "port": 53},
                ],
            },
            {
                "to": [
                    {"podSelector": {"matchLabels": {"role": "server"}}}
                ],
                "ports": [{"protocol": "TCP", "port": PROBE_PORT}],
            },
        ],
    },
}


class MetadataFabricNetworkPolicyError(RuntimeError):
    """The local NetworkPolicy enforcement contract failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_yaml_object(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("YAML document is not an object")
    return payload


def _load_documents(path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(item, dict)
    ]


def _resource(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in documents
            if item.get("kind") == kind
            and _mapping(item.get("metadata")).get("name") == name
        ),
        None,
    )


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(profile) != {
        "schema",
        "environment",
        "cluster",
        "probe",
        "stages",
        "claims",
    }:
        errors.append("NetworkPolicy profile field inventory does not match")
    if profile.get("schema") != PROFILE_SCHEMA or profile.get(
        "environment"
    ) != "local_docker_desktop":
        errors.append("NetworkPolicy profile schema or environment does not match")
    if _mapping(profile.get("cluster")) != {
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "server_version": SERVER_VERSION,
        "nodes": {"server": SERVER_NODE, "clients": CLIENT_NODE},
        "cni": {
            "namespace": CNI_NAMESPACE,
            "daemonset": CNI_DAEMONSET,
            "image": CNI_IMAGE,
        },
    }:
        errors.append("NetworkPolicy cluster/CNI profile does not match")
    if _mapping(profile.get("probe")) != {
        "image": PROBE_IMAGE,
        "service": PROBE_SERVICE,
        "port": PROBE_PORT,
        "success_body": SUCCESS_BODY,
        "request_timeout_seconds": 2,
        "stage_timeout_seconds": 30,
    }:
        errors.append("NetworkPolicy traffic probe profile does not match")
    if profile.get("stages") != STAGE_CONTRACT:
        errors.append("NetworkPolicy stage contract does not match")
    claims = _mapping(profile.get("claims"))
    if set(claims) != EXPECTED_CLAIMS:
        errors.append("NetworkPolicy claim inventory does not match")
    for claim in sorted(EXPECTED_CLAIMS):
        if claims.get(claim) is not False:
            errors.append(f"unverified NetworkPolicy claim must remain false: {claim}")
    if recovery._sensitive_paths(profile):
        errors.append("NetworkPolicy profile contains credential-bearing fields")
    return errors


def _container_security_errors(
    container: Mapping[str, Any], *, pod_name: str
) -> list[str]:
    errors: list[str] = []
    security = _mapping(container.get("securityContext"))
    capabilities = _mapping(security.get("capabilities"))
    if (
        security.get("allowPrivilegeEscalation") is not False
        or security.get("readOnlyRootFilesystem") is not True
        or security.get("runAsNonRoot") is not True
        or security.get("runAsUser") != 65534
        or security.get("runAsGroup") != 65534
        or security.get("privileged") is True
        or _mapping(security.get("seccompProfile")) != {"type": "RuntimeDefault"}
        or capabilities.get("drop") != ["ALL"]
        or capabilities.get("add") not in (None, [])
    ):
        errors.append(f"NetworkPolicy Pod/{pod_name} security context does not match")
    if container.get("image") != PROBE_IMAGE:
        errors.append(f"NetworkPolicy Pod/{pod_name} image is not digest pinned")
    if _mapping(container.get("resources")) != {
        "requests": {"cpu": "5m", "memory": "8Mi"},
        "limits": {"cpu": "50m", "memory": "32Mi"},
    }:
        errors.append(f"NetworkPolicy Pod/{pod_name} resources are not bounded")
    return errors


def _manifest_errors(
    base_path: Path, policy_paths: Mapping[str, Path]
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    documents: list[dict[str, Any]] = []
    try:
        base_documents = _load_documents(base_path)
        documents.extend(base_documents)
    except (OSError, TypeError, yaml.YAMLError) as exc:
        return [f"NetworkPolicy base manifest is invalid: {type(exc).__name__}"], []

    expected_base = {
        ("Namespace", NAMESPACE),
        ("ResourceQuota", "metadata-network-policy-rehearsal"),
        ("ServiceAccount", "probe"),
        ("Service", PROBE_SERVICE),
        *(("Pod", name) for name in PODS),
    }
    actual_base = {
        (
            str(item.get("kind")),
            str(_mapping(item.get("metadata")).get("name")),
        )
        for item in base_documents
    }
    if actual_base != expected_base:
        errors.append("NetworkPolicy base resource inventory does not match")

    expected_api_versions = {
        "Namespace": "v1",
        "ResourceQuota": "v1",
        "ServiceAccount": "v1",
        "Service": "v1",
        "Pod": "v1",
    }
    for document in base_documents:
        kind = str(document.get("kind"))
        metadata = _mapping(document.get("metadata"))
        name = str(metadata.get("name"))
        if document.get("apiVersion") != expected_api_versions.get(kind):
            errors.append(f"NetworkPolicy {kind}/{name} API version does not match")
        if kind != "Namespace" and metadata.get("namespace") != NAMESPACE:
            errors.append(f"NetworkPolicy {kind}/{name} is outside the rehearsal namespace")
        if kind in {"ResourceQuota", "ServiceAccount", "Service"} and _mapping(
            metadata.get("labels")
        ) != RESOURCE_LABELS:
            errors.append(f"NetworkPolicy {kind}/{name} cleanup label does not match")

    namespace = _resource(base_documents, "Namespace", NAMESPACE) or {}
    if _mapping(_mapping(namespace.get("metadata")).get("labels")) != NAMESPACE_LABELS:
        errors.append("NetworkPolicy Namespace labels do not match")
    quota = _resource(
        base_documents, "ResourceQuota", "metadata-network-policy-rehearsal"
    ) or {}
    if _mapping(_mapping(quota.get("spec")).get("hard")) != EXPECTED_QUOTA:
        errors.append("NetworkPolicy ResourceQuota does not match")
    service_account = _resource(base_documents, "ServiceAccount", "probe") or {}
    if (
        service_account.get("automountServiceAccountToken") is not False
        or set(service_account) != {
            "apiVersion",
            "kind",
            "metadata",
            "automountServiceAccountToken",
        }
    ):
        errors.append("NetworkPolicy ServiceAccount must disable token mounting")

    service = _resource(base_documents, "Service", PROBE_SERVICE) or {}
    service_spec = _mapping(service.get("spec"))
    if (
        service_spec.get("type") != "ClusterIP"
        or _mapping(service_spec.get("selector")) != {"role": "server"}
        or service_spec.get("ports")
        != [
            {
                "name": "http",
                "port": PROBE_PORT,
                "targetPort": "http",
                "protocol": "TCP",
            }
        ]
    ):
        errors.append("NetworkPolicy probe Service does not match")

    for pod_name in sorted(PODS):
        pod = _resource(base_documents, "Pod", pod_name) or {}
        metadata = _mapping(pod.get("metadata"))
        spec = _mapping(pod.get("spec"))
        labels = _mapping(metadata.get("labels"))
        containers = spec.get("containers") if isinstance(spec.get("containers"), list) else []
        expected_access = "allowed" if pod_name == "probe-allowed" else "denied"
        expected_labels = {
            **RESOURCE_LABELS,
            "role": "server" if pod_name == "probe-server" else "client",
            **({} if pod_name == "probe-server" else {"access": expected_access}),
        }
        if labels != expected_labels:
            errors.append(f"NetworkPolicy Pod/{pod_name} labels do not match")
        if (
            spec.get("automountServiceAccountToken") is not False
            or spec.get("serviceAccountName") != "probe"
        ):
            errors.append(f"NetworkPolicy Pod/{pod_name} token boundary does not match")
        if any(spec.get(key) is True for key in ("hostNetwork", "hostPID", "hostIPC")):
            errors.append(f"NetworkPolicy Pod/{pod_name} may not join host namespaces")
        if len(containers) != 1:
            errors.append(f"NetworkPolicy Pod/{pod_name} container inventory does not match")
            continue
        container = _mapping(containers[0])
        errors.extend(_container_security_errors(container, pod_name=pod_name))
        forbidden_volumes = {
            "hostPath",
            "secret",
            "projected",
            "persistentVolumeClaim",
        }
        if any(
            forbidden_volumes.intersection(_mapping(volume))
            for volume in spec.get("volumes") or []
            if isinstance(volume, Mapping)
        ):
            errors.append(f"NetworkPolicy Pod/{pod_name} requests a forbidden volume")
        expected_node = SERVER_NODE if pod_name == "probe-server" else CLIENT_NODE
        if _mapping(spec.get("nodeSelector")) != {
            "kubernetes.io/hostname": expected_node
        }:
            errors.append(f"NetworkPolicy Pod/{pod_name} node placement does not match")
        if spec.get("terminationGracePeriodSeconds") != 1:
            errors.append(f"NetworkPolicy Pod/{pod_name} termination boundary does not match")
        if container.get("imagePullPolicy") != "IfNotPresent":
            errors.append(f"NetworkPolicy Pod/{pod_name} image pull policy does not match")
        if pod_name == "probe-server":
            if spec.get("tolerations") != [
                {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ]:
                errors.append("NetworkPolicy server toleration does not match")
            if (
                container.get("name") != "server"
                or container.get("command")
                != [
                    "/bin/sh",
                    "-c",
                    "printf 'gda-network-policy-ok\\n' > /www/index.html && "
                    "exec httpd -f -p 8080 -h /www",
                ]
                or container.get("ports")
                != [{"name": "http", "containerPort": PROBE_PORT, "protocol": "TCP"}]
                or _mapping(container.get("readinessProbe"))
                != {
                    "httpGet": {"path": "/", "port": "http"},
                    "initialDelaySeconds": 1,
                    "periodSeconds": 1,
                    "timeoutSeconds": 1,
                    "failureThreshold": 30,
                }
                or container.get("volumeMounts")
                != [{"name": "www", "mountPath": "/www"}]
                or spec.get("volumes")
                != [{"name": "www", "emptyDir": {"sizeLimit": "1Mi"}}]
            ):
                errors.append("NetworkPolicy server process or storage contract does not match")
        else:
            if spec.get("tolerations"):
                errors.append(f"NetworkPolicy Pod/{pod_name} may not tolerate control-plane")
            if (
                container.get("name") != "client"
                or container.get("command") != ["/bin/sh", "-c", "exec sleep 3600"]
                or container.get("ports") not in (None, [])
                or _mapping(container.get("readinessProbe"))
                != {
                    "exec": {"command": ["/bin/sh", "-c", "test -r /etc/resolv.conf"]},
                    "initialDelaySeconds": 1,
                    "periodSeconds": 1,
                    "timeoutSeconds": 1,
                    "failureThreshold": 30,
                }
                or container.get("volumeMounts") not in (None, [])
                or spec.get("volumes") not in (None, [])
            ):
                errors.append(f"NetworkPolicy Pod/{pod_name} process contract does not match")

        expected_spec_keys = {
            "automountServiceAccountToken",
            "serviceAccountName",
            "nodeSelector",
            "containers",
            "terminationGracePeriodSeconds",
            *({"tolerations", "volumes"} if pod_name == "probe-server" else set()),
        }
        if set(spec) != expected_spec_keys:
            errors.append(f"NetworkPolicy Pod/{pod_name} spec field inventory does not match")

    for name, path in policy_paths.items():
        try:
            policy_documents = _load_documents(path)
        except (OSError, TypeError, yaml.YAMLError) as exc:
            errors.append(f"NetworkPolicy/{name} manifest is invalid: {type(exc).__name__}")
            continue
        documents.extend(policy_documents)
        if len(policy_documents) != 1:
            errors.append(f"NetworkPolicy/{name} manifest inventory does not match")
            continue
        policy = policy_documents[0]
        metadata = _mapping(policy.get("metadata"))
        if (
            policy.get("apiVersion") != "networking.k8s.io/v1"
            or policy.get("kind") != "NetworkPolicy"
            or metadata.get("name") != name
            or metadata.get("namespace") != NAMESPACE
            or _mapping(metadata.get("labels")) != RESOURCE_LABELS
            or _mapping(policy.get("spec")) != EXPECTED_POLICY_SPECS[name]
        ):
            errors.append(f"NetworkPolicy/{name} contract does not match")

    if recovery._sensitive_paths(documents):
        errors.append("NetworkPolicy manifests contain credential-bearing fields")
    return errors, documents


def build_network_policy_contract_report(
    *,
    profile_path: Path | None = None,
    manifest_dir: Path | None = None,
    wrapper_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the static local enforcement contract without touching Kubernetes."""
    profile_file = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    manifests = (manifest_dir or DEFAULT_MANIFEST_DIR).resolve()
    base_path = manifests / "base.yaml"
    policy_paths = {
        name: manifests / filename for name, filename in POLICY_FILES.items()
    }
    wrapper = (wrapper_path or DEFAULT_WRAPPER).resolve()
    errors: list[str] = []
    try:
        profile = _load_yaml_object(profile_file)
        errors.extend(_profile_errors(profile))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"NetworkPolicy profile is invalid: {type(exc).__name__}")
    manifest_errors, documents = _manifest_errors(base_path, policy_paths)
    errors.extend(manifest_errors)
    try:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_network_policy_enforcement"):
            if marker not in wrapper_text:
                errors.append(f"NetworkPolicy wrapper is missing safety marker: {marker}")
    except OSError as exc:
        errors.append(f"NetworkPolicy wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in [Path(__file__).resolve(), profile_file, base_path, *policy_paths.values(), wrapper]:
        if path.is_file():
            try:
                relative = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                relative = path.name
            files[relative] = {
                "path": relative,
                "sha256": recovery._file_sha256(path),
            }
    policy_spec_fingerprints = {
        name: recovery._canonical_sha256(spec)
        for name, spec in EXPECTED_POLICY_SPECS.items()
    }
    static_inventory = sorted(
        f"{item.get('kind')}/{_mapping(item.get('metadata')).get('name')}"
        for item in documents
    )
    stable = {
        "schema": CONTRACT_SCHEMA,
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "server_version": SERVER_VERSION,
        "nodes": {"server": SERVER_NODE, "clients": CLIENT_NODE},
        "cni": {"daemonset": f"{CNI_NAMESPACE}/{CNI_DAEMONSET}", "image": CNI_IMAGE},
        "probe_image": PROBE_IMAGE,
        "stages": STAGE_CONTRACT,
        "static_resource_inventory": static_inventory,
        "runtime_resource_inventory": EXPECTED_RUNTIME_RESOURCES,
        "policy_spec_fingerprints": policy_spec_fingerprints,
        "local_static_contract_verified": not errors,
        "local_network_policy_enforcement_verified": False,
        "production_network_policy_enforcement_verified": False,
        "metadata_provider_network_policy_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


def _ready(condition_list: Any) -> bool:
    return any(
        _mapping(item).get("type") == "Ready"
        and _mapping(item).get("status") == "True"
        for item in (condition_list if isinstance(condition_list, list) else [])
    )


def _normalized_runtime_policy_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(spec)
    policy_types = normalized.get("policyTypes")
    if not isinstance(policy_types, list):
        return normalized
    for policy_type, rule_key in (("Ingress", "ingress"), ("Egress", "egress")):
        if policy_type in policy_types and rule_key not in normalized:
            normalized[rule_key] = []
    return normalized


def _cluster_snapshot(runner: recovery._CommandRunner) -> dict[str, Any]:
    version = runner.kubectl_json(["version", "-o", "json"], label="read Kubernetes version")
    nodes_payload = runner.kubectl_json(["get", "nodes", "-o", "json"], label="read nodes")
    nodes: dict[str, Any] = {}
    for item in nodes_payload.get("items") or []:
        node = _mapping(item)
        metadata = _mapping(node.get("metadata"))
        status = _mapping(node.get("status"))
        addresses = status.get("addresses") if isinstance(status.get("addresses"), list) else []
        internal_ip = next(
            (
                _mapping(address).get("address")
                for address in addresses
                if _mapping(address).get("type") == "InternalIP"
            ),
            None,
        )
        nodes[str(metadata.get("name"))] = {
            "uid": metadata.get("uid"),
            "version": _mapping(status.get("nodeInfo")).get("kubeletVersion"),
            "internal_ip": internal_ip,
            "ready": _ready(status.get("conditions")),
        }
    daemonset = runner.kubectl_json(
        ["-n", CNI_NAMESPACE, "get", "daemonset", CNI_DAEMONSET, "-o", "json"],
        label="read kindnet DaemonSet",
    )
    daemonset_metadata = _mapping(daemonset.get("metadata"))
    daemonset_spec = _mapping(daemonset.get("spec"))
    template_spec = _mapping(_mapping(daemonset_spec.get("template")).get("spec"))
    containers = (
        template_spec.get("containers")
        if isinstance(template_spec.get("containers"), list)
        else []
    )
    container = next(
        (
            _mapping(item)
            for item in containers
            if _mapping(item).get("name") == "kindnet-cni"
        ),
        {},
    )
    daemonset_status = _mapping(daemonset.get("status"))
    return {
        "uid": recovery._cluster_uid(runner),
        "server_version": _mapping(version.get("serverVersion")).get("gitVersion"),
        "nodes": nodes,
        "cni": {
            "namespace": CNI_NAMESPACE,
            "daemonset": CNI_DAEMONSET,
            "uid": daemonset_metadata.get("uid"),
            "image": container.get("image"),
            "desired": daemonset_status.get("desiredNumberScheduled"),
            "ready": daemonset_status.get("numberReady"),
            "available": daemonset_status.get("numberAvailable"),
        },
    }


def _cluster_errors(cluster: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not cluster.get("uid") or cluster.get("server_version") != SERVER_VERSION:
        errors.append("NetworkPolicy cluster identity or server version does not match")
    nodes = _mapping(cluster.get("nodes"))
    if set(nodes) != {SERVER_NODE, CLIENT_NODE}:
        errors.append("NetworkPolicy node inventory does not match")
    for name in (SERVER_NODE, CLIENT_NODE):
        node = _mapping(nodes.get(name))
        if (
            not node.get("uid")
            or node.get("version") != SERVER_VERSION
            or not node.get("internal_ip")
            or node.get("ready") is not True
        ):
            errors.append(f"NetworkPolicy node identity is not ready: {name}")
    cni = _mapping(cluster.get("cni"))
    if (
        cni.get("namespace") != CNI_NAMESPACE
        or cni.get("daemonset") != CNI_DAEMONSET
        or not cni.get("uid")
        or cni.get("image") != CNI_IMAGE
        or cni.get("desired") != 2
        or cni.get("ready") != 2
        or cni.get("available") != 2
    ):
        errors.append("NetworkPolicy kindnet identity/readiness does not match")
    return errors


def _provider_identities(runner: recovery._CommandRunner) -> dict[str, Any]:
    return {
        name: provider_metrics._provider_identity(runner, name, spec)
        for name, spec in provider_metrics.PROVIDERS.items()
    }


def _resource_identities(runner: recovery._CommandRunner) -> dict[str, Any]:
    namespace = runner.kubectl_json(
        ["get", "namespace", NAMESPACE, "-o", "json"],
        label="read NetworkPolicy rehearsal Namespace",
    )
    pods_payload = runner.kubectl_json(
        ["-n", NAMESPACE, "get", "pods", "-o", "json"],
        label="read NetworkPolicy probe Pods",
    )
    service = runner.kubectl_json(
        ["-n", NAMESPACE, "get", "service", PROBE_SERVICE, "-o", "json"],
        label="read NetworkPolicy probe Service",
    )
    policies_payload = runner.kubectl_json(
        ["-n", NAMESPACE, "get", "networkpolicies", "-o", "json"],
        label="read NetworkPolicy identities",
    )
    pods: dict[str, Any] = {}
    for item in pods_payload.get("items") or []:
        pod = _mapping(item)
        metadata = _mapping(pod.get("metadata"))
        spec = _mapping(pod.get("spec"))
        status = _mapping(pod.get("status"))
        containers = spec.get("containers") if isinstance(spec.get("containers"), list) else []
        container = _mapping(containers[0]) if containers else {}
        name = str(metadata.get("name"))
        pods[name] = {
            "uid": metadata.get("uid"),
            "node": spec.get("nodeName"),
            "ip": status.get("podIP"),
            "image": container.get("image"),
            "service_account": spec.get("serviceAccountName"),
            "labels": dict(_mapping(metadata.get("labels"))),
            "ready": _ready(status.get("conditions")),
        }
    service_metadata = _mapping(service.get("metadata"))
    service_spec = _mapping(service.get("spec"))
    policies: dict[str, Any] = {}
    for item in policies_payload.get("items") or []:
        policy = _mapping(item)
        metadata = _mapping(policy.get("metadata"))
        name = str(metadata.get("name"))
        policies[name] = {
            "uid": metadata.get("uid"),
            "spec_fingerprint": recovery._canonical_sha256(
                _normalized_runtime_policy_spec(_mapping(policy.get("spec")))
            ),
        }
    return {
        "namespace": {
            "name": _mapping(namespace.get("metadata")).get("name"),
            "uid": _mapping(namespace.get("metadata")).get("uid"),
            "labels": dict(_mapping(_mapping(namespace.get("metadata")).get("labels"))),
        },
        "pods": pods,
        "service": {
            "name": service_metadata.get("name"),
            "uid": service_metadata.get("uid"),
            "type": service_spec.get("type"),
            "cluster_ip": service_spec.get("clusterIP"),
            "ports": [
                _mapping(port).get("port")
                for port in service_spec.get("ports") or []
            ],
        },
        "policies": policies,
    }


def _runtime_resource_inventory(runner: recovery._CommandRunner) -> list[str]:
    selector = f"app.kubernetes.io/part-of={PART_OF_LABEL}"
    queries = (
        ("Pod", "pods"),
        ("Service", "services"),
        ("ServiceAccount", "serviceaccounts"),
        ("ResourceQuota", "resourcequotas"),
        ("NetworkPolicy", "networkpolicies"),
    )
    resources: list[str] = []
    for kind, resource in queries:
        payload = runner.kubectl_json(
            ["-n", NAMESPACE, "get", resource, "-l", selector, "-o", "json"],
            label=f"list labeled {resource}",
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        resources.extend(
            f"{kind}/{_mapping(_mapping(item).get('metadata')).get('name')}"
            for item in items
        )
    return sorted(resources)


def _exec_health(runner: recovery._CommandRunner, pod_name: str) -> bool:
    output = runner.kubectl_run(
        ["-n", NAMESPACE, "exec", pod_name, "--", "sh", "-c", "printf gda-exec-ok"],
        timeout=15,
        label=f"verify exec channel for {pod_name}",
    )
    return output == b"gda-exec-ok"


def _probe_client(
    runner: recovery._CommandRunner, pod_name: str, *, request_timeout: int
) -> dict[str, Any]:
    exec_healthy = _exec_health(runner, pod_name)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            runner.kubectl_args(
                [
                    "-n",
                    NAMESPACE,
                    "exec",
                    pod_name,
                    "--",
                    "timeout",
                    str(request_timeout),
                    "wget",
                    "-qO-",
                    f"http://{PROBE_SERVICE}:{PROBE_PORT}/",
                ]
            ),
            capture_output=True,
            check=False,
            timeout=request_timeout + 15,
        )
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        return_code = completed.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MetadataFabricNetworkPolicyError(
            f"traffic probe was unavailable for {pod_name}"
        ) from exc
    duration = round(time.monotonic() - started, 3)
    transport_connected = return_code == 0
    response_valid = transport_connected and stdout == SUCCESS_BODY
    return {
        "exec_channel_healthy": exec_healthy,
        "outcome": "connected" if transport_connected else "blocked",
        "response_valid": response_valid,
        "response_sha256": (
            hashlib.sha256(stdout.encode("utf-8")).hexdigest()
            if transport_connected
            else None
        ),
        "return_code": return_code,
        "duration_seconds": duration,
        "raw_response_retained": False,
    }


def _probe_matches(result: Mapping[str, Any], expected: str) -> bool:
    if result.get("exec_channel_healthy") is not True:
        return False
    if result.get("raw_response_retained") is not False:
        return False
    if expected == "connected":
        return (
            result.get("outcome") == "connected"
            and result.get("return_code") == 0
            and result.get("response_valid") is True
            and result.get("response_sha256")
            == hashlib.sha256(SUCCESS_BODY.encode("utf-8")).hexdigest()
        )
    return (
        result.get("outcome") == "blocked"
        and isinstance(result.get("return_code"), int)
        and result.get("return_code") != 0
        and result.get("response_valid") is False
        and result.get("response_sha256") is None
    )


def _all_probe_pods_ready(runner: recovery._CommandRunner) -> bool:
    payload = runner.kubectl_json(
        ["-n", NAMESPACE, "get", "pods", "-o", "json"],
        label="verify NetworkPolicy probe Pod readiness",
    )
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {
        str(_mapping(_mapping(item).get("metadata")).get("name"))
        for item in items
    } == PODS and all(
        _ready(_mapping(_mapping(item).get("status")).get("conditions"))
        for item in items
    )


def _observe_stage(
    runner: recovery._CommandRunner,
    stage: Mapping[str, Any],
    *,
    request_timeout: int = 2,
    stage_timeout: int = 30,
) -> dict[str, Any]:
    deadline = time.monotonic() + stage_timeout
    attempt = 0
    last_results: dict[str, Any] = {}
    while time.monotonic() < deadline:
        attempt += 1
        last_results = {
            client: _probe_client(
                runner,
                pod_name,
                request_timeout=request_timeout,
            )
            for client, pod_name in CLIENTS.items()
        }
        expected = _mapping(stage.get("expected"))
        if all(
            _probe_matches(_mapping(last_results.get(client)), str(expected.get(client)))
            for client in CLIENTS
        ) and _all_probe_pods_ready(runner):
            return {
                "name": stage.get("name"),
                "sequence": STAGE_CONTRACT.index(stage) + 1,
                "active_policies": list(stage.get("policies") or []),
                "attempt_count": attempt,
                "clients": last_results,
                "pods_ready_after_probe": True,
            }
        time.sleep(0.5)
    raise MetadataFabricNetworkPolicyError(
        f"NetworkPolicy stage did not reach expected traffic state: {stage.get('name')}"
    )


def collect_live_network_policy_enforcement(
    *, kubectl: str = "kubectl", context: str = CONTEXT
) -> dict[str, Any]:
    """Run the isolated cross-node NetworkPolicy enforcement rehearsal."""
    if context != CONTEXT:
        raise MetadataFabricNetworkPolicyError(
            "NetworkPolicy enforcement rehearsal requires docker-desktop"
        )
    started = datetime.now(UTC)
    contract = build_network_policy_contract_report()
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricNetworkPolicyError(
            "NetworkPolicy enforcement static contract is invalid"
        )
    runner = recovery._CommandRunner(kubectl, context)
    cluster_before = _cluster_snapshot(runner)
    cluster_preflight_errors = _cluster_errors(cluster_before)
    if cluster_preflight_errors:
        raise MetadataFabricNetworkPolicyError(cluster_preflight_errors[0])
    if runner.namespace_exists(NAMESPACE):
        raise MetadataFabricNetworkPolicyError(
            "pre-existing NetworkPolicy rehearsal namespace must be removed first"
        )
    providers_before = _provider_identities(runner)

    base_apply_attempted = False
    base_apply_completed = False
    pods_ready = False
    stage_results: list[dict[str, Any]] = []
    policy_applied = {name: False for name in POLICY_FILES}
    resources: dict[str, Any] = {}
    runtime_inventory: list[str] = []
    cleanup_completed = False
    namespace_removed = False
    providers_preserved = False
    cluster_preserved = False
    failure: Exception | None = None
    try:
        base_apply_attempted = True
        runner.kubectl_run(
            ["apply", "-f", str(DEFAULT_BASE_PATH)],
            timeout=180,
            label="apply NetworkPolicy rehearsal base",
        )
        base_apply_completed = True
        runner.kubectl_run(
            [
                "-n",
                NAMESPACE,
                "wait",
                "--for=condition=Ready",
                "pod",
                "--all",
                "--timeout=180s",
            ],
            timeout=210,
            label="wait for NetworkPolicy probe Pods",
        )
        pods_ready = True

        for stage in STAGE_CONTRACT:
            for policy_name in stage["policies"]:
                if policy_applied[policy_name]:
                    continue
                runner.kubectl_run(
                    [
                        "apply",
                        "-f",
                        str(DEFAULT_MANIFEST_DIR / POLICY_FILES[policy_name]),
                    ],
                    timeout=60,
                    label=f"apply NetworkPolicy/{policy_name}",
                )
                policy_applied[policy_name] = True
            stage_results.append(_observe_stage(runner, stage))

        resources = _resource_identities(runner)
        runtime_inventory = _runtime_resource_inventory(runner)
    except Exception as exc:
        failure = exc
    finally:
        if base_apply_attempted:
            try:
                runner.kubectl_run(
                    [
                        "delete",
                        "namespace",
                        NAMESPACE,
                        "--ignore-not-found=true",
                        "--wait=true",
                        "--timeout=120s",
                    ],
                    timeout=150,
                    label="delete NetworkPolicy rehearsal Namespace",
                )
                cleanup_completed = True
                namespace_removed = not runner.namespace_exists(NAMESPACE)
            except Exception as exc:
                failure = failure or exc
        try:
            providers_preserved = _provider_identities(runner) == providers_before
            cluster_preserved = _cluster_snapshot(runner) == cluster_before
        except Exception as exc:
            failure = failure or exc

    if failure is not None:
        if isinstance(failure, MetadataFabricNetworkPolicyError):
            raise failure
        raise MetadataFabricNetworkPolicyError(
            f"live NetworkPolicy enforcement rehearsal failed: {failure}"
        ) from failure
    completed = datetime.now(UTC)
    return {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": completed.isoformat(),
        "started_at": started.isoformat(),
        "duration_seconds": round((completed - started).total_seconds(), 3),
        "contract": {
            "local_static_contract_verified": contract[
                "local_static_contract_verified"
            ],
            "contract_fingerprint": contract["contract_fingerprint"],
        },
        "cluster": {"context": context, **cluster_before},
        "resources": resources,
        "stages": stage_results,
        "runtime_checks": {
            "namespace_absent_before_apply": True,
            "base_apply_completed": base_apply_completed,
            "probe_pods_ready": pods_ready,
            "cross_node_placement_verified": (
                _mapping(_mapping(resources.get("pods")).get("probe-server")).get(
                    "node"
                )
                == SERVER_NODE
                and all(
                    _mapping(_mapping(resources.get("pods")).get(name)).get("node")
                    == CLIENT_NODE
                    for name in CLIENTS.values()
                )
            ),
            "policies_applied": policy_applied,
            "runtime_resource_inventory": runtime_inventory,
            "runtime_resource_inventory_matches": (
                runtime_inventory == EXPECTED_RUNTIME_RESOURCES
            ),
            "cleanup_command_completed": cleanup_completed,
            "ephemeral_namespace_removed": namespace_removed,
            "remaining_resources": [],
            "provider_identities_preserved": providers_preserved,
            "cluster_and_cni_identities_preserved": cluster_preserved,
            "metadata_provider_namespaces_modified": False,
            "kubernetes_credential_resources_requested": False,
            "persistent_volume_resources_requested": False,
            "rbac_resources_requested": False,
        },
    }


def _resource_errors(resources: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    namespace = _mapping(resources.get("namespace"))
    if (
        namespace.get("name") != NAMESPACE
        or not namespace.get("uid")
        or _mapping(namespace.get("labels")) != RUNTIME_NAMESPACE_LABELS
    ):
        errors.append("NetworkPolicy runtime Namespace identity does not match")
    pods = _mapping(resources.get("pods"))
    if set(pods) != PODS:
        errors.append("NetworkPolicy runtime Pod inventory does not match")
    for name in sorted(PODS):
        pod = _mapping(pods.get(name))
        expected_node = SERVER_NODE if name == "probe-server" else CLIENT_NODE
        labels = _mapping(pod.get("labels"))
        if (
            not pod.get("uid")
            or not pod.get("ip")
            or pod.get("node") != expected_node
            or pod.get("image") != PROBE_IMAGE
            or pod.get("service_account") != "probe"
            or pod.get("ready") is not True
            or labels.get("app.kubernetes.io/part-of") != PART_OF_LABEL
        ):
            errors.append(f"NetworkPolicy runtime Pod identity does not match: {name}")
    service = _mapping(resources.get("service"))
    if (
        service.get("name") != PROBE_SERVICE
        or not service.get("uid")
        or service.get("type") != "ClusterIP"
        or not service.get("cluster_ip")
        or service.get("ports") != [PROBE_PORT]
    ):
        errors.append("NetworkPolicy runtime Service identity does not match")
    policies = _mapping(resources.get("policies"))
    if set(policies) != set(POLICY_FILES):
        errors.append("NetworkPolicy runtime policy inventory does not match")
    for name, spec in EXPECTED_POLICY_SPECS.items():
        policy = _mapping(policies.get(name))
        if (
            not policy.get("uid")
            or policy.get("spec_fingerprint")
            != recovery._canonical_sha256(spec)
        ):
            errors.append(f"NetworkPolicy runtime policy identity does not match: {name}")
    return errors


def _stage_errors(stages: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(stages, list) or len(stages) != len(STAGE_CONTRACT):
        return ["NetworkPolicy observation stage inventory does not match"]
    for sequence, (observed, expected) in enumerate(
        zip(stages, STAGE_CONTRACT, strict=True), start=1
    ):
        stage = _mapping(observed)
        if (
            stage.get("name") != expected["name"]
            or stage.get("sequence") != sequence
            or stage.get("active_policies") != expected["policies"]
            or not isinstance(stage.get("attempt_count"), int)
            or stage.get("attempt_count", 0) <= 0
            or stage.get("pods_ready_after_probe") is not True
        ):
            errors.append(f"NetworkPolicy stage identity does not match: {expected['name']}")
        clients = _mapping(stage.get("clients"))
        if set(clients) != set(CLIENTS):
            errors.append(f"NetworkPolicy client inventory does not match: {expected['name']}")
        for client, expected_outcome in expected["expected"].items():
            if not _probe_matches(_mapping(clients.get(client)), expected_outcome):
                errors.append(
                    f"NetworkPolicy traffic outcome does not match: {expected['name']}/{client}"
                )
    return errors


def _observation_errors(
    observation: Mapping[str, Any], *, now: datetime, max_age_seconds: float
) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(observation):
        errors.append("NetworkPolicy observation contains credential-bearing fields")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("NetworkPolicy observation schema does not match")
    try:
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
        if age < -30 or age > max_age_seconds:
            errors.append("NetworkPolicy observation is outside the freshness window")
    except ValueError:
        errors.append("NetworkPolicy observation timestamp is invalid")

    contract = _mapping(observation.get("contract"))
    current_contract = build_network_policy_contract_report()
    if contract.get("local_static_contract_verified") is not True:
        errors.append("NetworkPolicy static contract was not verified")
    if current_contract.get("local_static_contract_verified") is not True:
        errors.append("current NetworkPolicy static contract is invalid")
    if contract.get("contract_fingerprint") != current_contract.get(
        "contract_fingerprint"
    ):
        errors.append("NetworkPolicy contract fingerprint is stale")

    cluster = _mapping(observation.get("cluster"))
    if cluster.get("context") != CONTEXT:
        errors.append("NetworkPolicy observation context does not match")
    errors.extend(_cluster_errors(cluster))
    errors.extend(_resource_errors(_mapping(observation.get("resources"))))
    errors.extend(_stage_errors(observation.get("stages")))

    runtime = _mapping(observation.get("runtime_checks"))
    for key in (
        "namespace_absent_before_apply",
        "base_apply_completed",
        "probe_pods_ready",
        "cross_node_placement_verified",
        "runtime_resource_inventory_matches",
        "cleanup_command_completed",
        "ephemeral_namespace_removed",
        "provider_identities_preserved",
        "cluster_and_cni_identities_preserved",
    ):
        if runtime.get(key) is not True:
            errors.append(f"NetworkPolicy runtime check did not pass: {key}")
    if _mapping(runtime.get("policies_applied")) != {
        name: True for name in POLICY_FILES
    }:
        errors.append("NetworkPolicy apply inventory does not match")
    if runtime.get("runtime_resource_inventory") != EXPECTED_RUNTIME_RESOURCES:
        errors.append("NetworkPolicy runtime resource inventory does not match")
    if runtime.get("remaining_resources") != []:
        errors.append("NetworkPolicy rehearsal resources remain after cleanup")
    if runtime.get("metadata_provider_namespaces_modified") is not False:
        errors.append("NetworkPolicy rehearsal may not modify provider namespaces")
    for key in (
        "kubernetes_credential_resources_requested",
        "persistent_volume_resources_requested",
        "rbac_resources_requested",
    ):
        if runtime.get(key) is not False:
            errors.append(f"NetworkPolicy rehearsal may not request restricted resource: {key}")
    return errors


def build_network_policy_evidence(
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build fail-closed evidence for the bounded local enforcement rehearsal."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricNetworkPolicyError(
            "NetworkPolicy verification time must be timezone-aware"
        )
    errors = _observation_errors(
        observation,
        now=current,
        max_age_seconds=max_age_seconds,
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop_cross_node_network_policy_rehearsal",
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "observation_fingerprint": recovery._canonical_sha256(observation),
        "checks": {
            "static_contract": "passed" if verified else "blocked",
            "cross_node_baseline": "passed" if verified else "blocked",
            "ingress_default_deny": "passed" if verified else "blocked",
            "ingress_selector_allow": "passed" if verified else "blocked",
            "egress_default_deny": "passed" if verified else "blocked",
            "dns_and_target_egress_allow": "passed" if verified else "blocked",
            "ephemeral_cleanup": "passed" if verified else "blocked",
            "provider_identity_preservation": "passed" if verified else "blocked",
            "production_boundaries": "passed",
        },
        "errors": errors,
        "network_policy_scope": "isolated_local_cross_node_kindnet_enforcement",
        "local_network_policy_enforcement_verified": verified,
        "production_network_policy_enforcement_verified": False,
        "metadata_provider_network_policy_verified": False,
        "tenant_isolation_verified": False,
        "oidc_verified": False,
        "upgrade_verified": False,
        "writes_to_gda_enabled": False,
        "production_ready": False,
        "observation": observation,
    }
    return {
        **stable,
        "generated_at": current.isoformat(),
        "status": (
            "local_network_policy_enforcement_verified" if verified else "blocked"
        ),
        "evidence_fingerprint": recovery._canonical_sha256(stable),
    }


def verify_evidence_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("NetworkPolicy evidence contains credential-bearing fields")
    if report.get("schema") != EVIDENCE_SCHEMA:
        errors.append("NetworkPolicy evidence schema does not match")
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "status", "evidence_fingerprint"}
    }
    if report.get("evidence_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("NetworkPolicy evidence fingerprint does not match")
    verified = report.get("local_network_policy_enforcement_verified") is True
    expected_status = (
        "local_network_policy_enforcement_verified" if verified else "blocked"
    )
    if report.get("status") != expected_status:
        errors.append("NetworkPolicy local claim status does not match")
    for claim in (
        "production_network_policy_enforcement_verified",
        "metadata_provider_network_policy_verified",
        "tenant_isolation_verified",
        "oidc_verified",
        "upgrade_verified",
        "writes_to_gda_enabled",
        "production_ready",
    ):
        if report.get(claim) is not False:
            errors.append(f"NetworkPolicy evidence may not claim {claim}")
    return errors


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricNetworkPolicyError("JSON input must be an object")
    return payload


def _write_report(report: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--kubectl", default="kubectl")
    run_parser.add_argument("--context", default=CONTEXT)
    run_parser.add_argument("--output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            report = build_network_policy_contract_report()
            _write_report(report, None)
            return 0 if report["local_static_contract_verified"] else 1
        if args.command == "run":
            observation = collect_live_network_policy_enforcement(
                kubectl=args.kubectl,
                context=args.context,
            )
            report = build_network_policy_evidence(observation)
            _write_report(report, args.output)
            return 0 if report["local_network_policy_enforcement_verified"] else 1
        report = _load_json_object(args.input)
        errors = verify_evidence_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
        MetadataFabricNetworkPolicyError,
        recovery.MetadataFabricRecoveryError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata NetworkPolicy enforcement: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
