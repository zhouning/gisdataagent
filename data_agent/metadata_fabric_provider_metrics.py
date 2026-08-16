"""Verify bounded provider-native metrics for the local Metadata Fabric.

The collector reads OpenMetadata Dropwizard/Prometheus metrics and Gravitino
Dropwizard JSON through short-lived loopback port-forwards. It records only
allowlisted health values plus metric-name/type/label-key fingerprints. It does
not claim an OTel pipeline, alert delivery, SLOs, TLS, or production monitoring.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from prometheus_client.parser import text_string_to_metric_families

from . import metadata_fabric_backup_repository as repository
from . import metadata_fabric_recovery_rehearsal as recovery
from . import metadata_fabric_sandbox as sandbox


CONTRACT_SCHEMA = "gda.metadata_fabric_provider_metrics_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_provider_metrics_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_provider_metrics_evidence.v1"
PROFILE_SCHEMA = "gda.metadata_fabric_provider_metrics_profile.v1"
CONTEXT = "docker-desktop"
NAMESPACE = sandbox.NAMESPACE
DROPWIZARD_VERSION = "4.0.0"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-provider-metrics.local.yaml"
DEFAULT_WRAPPER = REPO_ROOT / "scripts/metadata-fabric-provider-metrics.sh"
OPENMETADATA_VALUES = (
    REPO_ROOT / "helm/metadata-fabric-sandbox/openmetadata-values.yaml"
)
GRAVITINO_MANIFEST = REPO_ROOT / "k8s/metadata-fabric-sandbox/gravitino.yaml"

OPENMETADATA_REQUIRED_GAUGES = (
    "database.pool.MaxConnections",
    "database.pool.TotalConnections",
    "health.aggregate.healthy",
    "health.aggregate.unhealthy",
)
OPENMETADATA_REQUIRED_PROMETHEUS = (
    "auth_attempts",
    "db_connections",
    "http_server_requests_sec_seconds",
    "jvm_memory_used_bytes",
)
GRAVITINO_REQUIRED_GAUGES = (
    "gravitino-relational-store.datasource.active-connections",
    "gravitino-relational-store.datasource.max-connections",
    "gravitino-server.http-server.total-thread.num",
    "jvm.heap.max",
    "jvm.heap.used",
)
PROVIDERS = {
    "openmetadata": {
        "version": sandbox.OPENMETADATA_VERSION,
        "workload": "deployment/openmetadata",
        "service": "openmetadata",
        "port": 8586,
        "container": "openmetadata",
        "image": (
            f"docker.getcollate.io/openmetadata/server:{sandbox.OPENMETADATA_VERSION}"
        ),
    },
    "gravitino": {
        "version": sandbox.GRAVITINO_VERSION,
        "workload": "statefulset/metadata-gravitino",
        "service": "metadata-gravitino",
        "port": 8090,
        "container": "gravitino",
        "image": f"gda/gravitino:{sandbox.GRAVITINO_VERSION}-local-arm64",
    },
}


class MetadataFabricProviderMetricsError(RuntimeError):
    """The provider metrics contract or live collection failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    cluster = _mapping(profile.get("cluster"))
    providers = _mapping(profile.get("providers"))
    claims = _mapping(profile.get("claims"))
    if (
        profile.get("schema") != PROFILE_SCHEMA
        or profile.get("environment") != "local_docker_desktop"
    ):
        errors.append("provider metrics profile schema or environment does not match")
    if cluster.get("context") != CONTEXT or cluster.get("namespace") != NAMESPACE:
        errors.append("provider metrics cluster boundary does not match")

    openmetadata = _mapping(providers.get("openmetadata"))
    om_endpoints = _mapping(openmetadata.get("endpoints"))
    if (
        openmetadata.get("version") != sandbox.OPENMETADATA_VERSION
        or openmetadata.get("workload") != "deployment/openmetadata"
        or openmetadata.get("service") != "openmetadata"
        or openmetadata.get("admin_port") != 8586
        or om_endpoints != {"dropwizard": "/metrics", "prometheus": "/prometheus"}
    ):
        errors.append("OpenMetadata metrics profile does not match")

    gravitino = _mapping(providers.get("gravitino"))
    grav_endpoints = _mapping(gravitino.get("endpoints"))
    if (
        gravitino.get("version") != sandbox.GRAVITINO_VERSION
        or gravitino.get("workload") != "statefulset/metadata-gravitino"
        or gravitino.get("service") != "metadata-gravitino"
        or gravitino.get("metrics_port") != 8090
        or grav_endpoints != {"dropwizard": "/metrics"}
    ):
        errors.append("Gravitino metrics profile does not match")

    for claim in (
        "local_provider_metrics_verified",
        "production_metrics_verified",
        "otel_pipeline_verified",
        "alert_delivery_verified",
        "slo_verified",
        "metrics_tls_verified",
        "oidc_verified",
        "network_policy_enforcement_verified",
        "upgrade_verified",
        "writes_to_gda_enabled",
        "production_ready",
    ):
        if claims.get(claim) is not False:
            errors.append(
                f"unverified metrics profile claim must remain false: {claim}"
            )
    return errors


def build_provider_metrics_contract_report(
    profile_path: Path | None = None,
    wrapper_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the local provider metrics profile and claim boundary."""
    profile_file = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    wrapper = (wrapper_path or DEFAULT_WRAPPER).resolve()
    errors: list[str] = []
    try:
        profile = repository._load_yaml_object(profile_file)
        errors.extend(_profile_errors(profile))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"provider metrics profile is invalid: {type(exc).__name__}")

    sandbox_contract = sandbox.build_sandbox_report()
    if sandbox_contract.get("static_contract_verified") is not True:
        errors.append("metadata fabric sandbox contract is invalid")
    try:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_provider_metrics"):
            if marker not in wrapper_text:
                errors.append(f"provider metrics wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"provider metrics wrapper is invalid: {type(exc).__name__}")

    for path, markers in (
        (OPENMETADATA_VALUES, ("adminPort: 8586",)),
        (
            GRAVITINO_MANIFEST,
            (
                "gravitino.server.webserver.httpPort = 8090",
                "port: 8090",
            ),
        ),
    ):
        try:
            text = path.read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    errors.append(
                        f"metrics source is missing marker {marker}: {path.name}"
                    )
        except OSError as exc:
            errors.append(f"metrics source is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in (
        Path(__file__).resolve(),
        Path(sandbox.__file__).resolve(),
        profile_file,
        wrapper,
        OPENMETADATA_VALUES,
        GRAVITINO_MANIFEST,
    ):
        if path.is_file():
            try:
                relative = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                relative = path.name
            files[relative] = {"path": relative, "sha256": recovery._file_sha256(path)}

    stable = {
        "schema": CONTRACT_SCHEMA,
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "providers": PROVIDERS,
        "openmetadata_required_gauges": OPENMETADATA_REQUIRED_GAUGES,
        "openmetadata_required_prometheus": OPENMETADATA_REQUIRED_PROMETHEUS,
        "gravitino_required_gauges": GRAVITINO_REQUIRED_GAUGES,
        "local_static_contract_verified": not errors,
        "local_provider_metrics_verified": False,
        "production_metrics_verified": False,
        "otel_pipeline_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


def _dropwizard_summary(
    payload: Mapping[str, Any], required_gauges: tuple[str, ...]
) -> dict[str, Any]:
    sections = ("gauges", "counters", "histograms", "meters", "timers")
    inventories: dict[str, list[str]] = {}
    for section in sections:
        values = _mapping(payload.get(section))
        inventories[section] = sorted(str(name) for name in values)
    gauges = _mapping(payload.get("gauges"))
    required_values = {
        name: _mapping(gauges.get(name)).get("value") for name in required_gauges
    }
    return {
        "format": "dropwizard_json",
        "version": payload.get("version"),
        "section_counts": {key: len(value) for key, value in inventories.items()},
        "metric_name_fingerprint": recovery._canonical_sha256(inventories),
        "required_metric_names": list(required_gauges),
        "missing_required_metrics": [
            name for name, value in required_values.items() if value is None
        ],
        "required_gauge_values": required_values,
    }


def _prometheus_summary(payload: str) -> dict[str, Any]:
    families = list(text_string_to_metric_families(payload))
    family_names = sorted(family.name for family in families)
    family_types = sorted((family.name, family.type) for family in families)
    label_names: set[str] = set()
    sample_count = 0
    for family in families:
        for sample in family.samples:
            sample_count += 1
            label_names.update(str(name) for name in sample.labels)
    missing = [
        name for name in OPENMETADATA_REQUIRED_PROMETHEUS if name not in family_names
    ]
    return {
        "format": "prometheus_text_0.0.4",
        "metric_family_count": len(families),
        "sample_count": sample_count,
        "metric_family_name_fingerprint": recovery._canonical_sha256(family_names),
        "metric_family_type_fingerprint": recovery._canonical_sha256(family_types),
        "metric_type_counts": dict(
            sorted(Counter(family.type for family in families).items())
        ),
        "label_name_fingerprint": recovery._canonical_sha256(sorted(label_names)),
        "label_name_count": len(label_names),
        "required_metric_names": list(OPENMETADATA_REQUIRED_PROMETHEUS),
        "missing_required_metrics": missing,
    }


class _PortForward:
    def __init__(
        self,
        *,
        kubectl: str,
        context: str,
        namespace: str,
        service: str,
        target_port: int,
    ) -> None:
        self.kubectl = kubectl
        self.context = context
        self.namespace = namespace
        self.service = service
        self.target_port = target_port
        self.local_port = repository._free_local_port()
        self.process: subprocess.Popen[bytes] | None = None

    def command(self) -> list[str]:
        return [
            self.kubectl,
            "--context",
            self.context,
            "-n",
            self.namespace,
            "port-forward",
            f"service/{self.service}",
            f"{self.local_port}:{self.target_port}",
            "--address=127.0.0.1",
        ]

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(
                self.command(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise MetadataFabricProviderMetricsError(
                f"{self.service} metrics port-forward was unavailable"
            ) from exc
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise MetadataFabricProviderMetricsError(
                    f"{self.service} metrics port-forward stopped before readiness"
                )
            try:
                with socket.create_connection(
                    ("127.0.0.1", self.local_port), timeout=1
                ):
                    return
            except OSError:
                time.sleep(0.25)
        self.stop()
        raise MetadataFabricProviderMetricsError(
            f"{self.service} metrics port-forward did not become ready"
        )

    def stop(self) -> bool:
        if self.process is None:
            return True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        return self.process.poll() is not None


def _fetch(local_port: int, path: str, *, label: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{local_port}{path}",
        headers={"Accept": "application/json, text/plain"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            content_type = response.headers.get_content_type()
    except (OSError, urllib.error.URLError) as exc:
        raise MetadataFabricProviderMetricsError(f"{label} request failed") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise MetadataFabricProviderMetricsError(f"{label} response is too large")
    return body, content_type


def _json_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataFabricProviderMetricsError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise MetadataFabricProviderMetricsError(f"{label} is not an object")
    return value


def _provider_identity(
    runner: recovery._CommandRunner, name: str, spec: Mapping[str, Any]
) -> dict[str, Any]:
    service = runner.kubectl_json(
        ["-n", NAMESPACE, "get", "service", str(spec["service"]), "-o", "json"],
        label=f"read {name} metrics Service",
    )
    workload_kind, workload_name = str(spec["workload"]).split("/", 1)
    workload = runner.kubectl_json(
        ["-n", NAMESPACE, "get", workload_kind, workload_name, "-o", "json"],
        label=f"read {name} metrics workload",
    )
    service_meta = _mapping(service.get("metadata"))
    service_spec = _mapping(service.get("spec"))
    workload_meta = _mapping(workload.get("metadata"))
    workload_spec = _mapping(workload.get("spec"))
    template = _mapping(workload_spec.get("template"))
    pod_spec = _mapping(template.get("spec"))
    containers = (
        pod_spec.get("containers")
        if isinstance(pod_spec.get("containers"), list)
        else []
    )
    container = next(
        (
            _mapping(item)
            for item in containers
            if _mapping(item).get("name") == spec["container"]
        ),
        {},
    )
    ports = (
        service_spec.get("ports")
        if isinstance(service_spec.get("ports"), list)
        else []
    )
    return {
        "service": {
            "name": service_meta.get("name"),
            "uid": service_meta.get("uid"),
            "type": service_spec.get("type"),
            "ports": sorted(
                int(_mapping(item).get("port"))
                for item in ports
                if isinstance(_mapping(item).get("port"), int)
            ),
        },
        "workload": {
            "kind": workload.get("kind"),
            "name": workload_meta.get("name"),
            "uid": workload_meta.get("uid"),
            "image": container.get("image"),
            "ready_replicas": _mapping(workload.get("status")).get("readyReplicas", 0),
        },
    }


def collect_live_provider_metrics(
    *, kubectl: str = "kubectl", context: str = CONTEXT
) -> dict[str, Any]:
    """Collect allowlisted metric summaries from both local providers."""
    if context != CONTEXT:
        raise MetadataFabricProviderMetricsError(
            "provider metrics collection requires docker-desktop"
        )
    started = datetime.now(UTC)
    contract = build_provider_metrics_contract_report()
    if contract["local_static_contract_verified"] is not True:
        raise MetadataFabricProviderMetricsError("provider metrics contract is invalid")
    runner = recovery._CommandRunner(kubectl, context)
    cluster_uid = recovery._cluster_uid(runner)
    namespace = recovery._namespace_identity(runner, NAMESPACE)
    if not cluster_uid or not namespace.get("uid"):
        raise MetadataFabricProviderMetricsError(
            "provider metrics cluster identity is unavailable"
        )

    provider_observations: dict[str, Any] = {}
    stopped: dict[str, bool] = {}
    for name, spec in PROVIDERS.items():
        forward = _PortForward(
            kubectl=kubectl,
            context=context,
            namespace=NAMESPACE,
            service=str(spec["service"]),
            target_port=int(spec["port"]),
        )
        failure: Exception | None = None
        observation: dict[str, Any] = {}
        try:
            identity = _provider_identity(runner, name, spec)
            forward.start()
            dropwizard_body, dropwizard_type = _fetch(
                forward.local_port, "/metrics", label=f"{name} Dropwizard metrics"
            )
            required = (
                OPENMETADATA_REQUIRED_GAUGES
                if name == "openmetadata"
                else GRAVITINO_REQUIRED_GAUGES
            )
            observation = {
                "identity": identity,
                "transport": {
                    "scheme": "http",
                    "service_port": spec["port"],
                    "dropwizard_path": "/metrics",
                    "dropwizard_content_type": dropwizard_type,
                },
                "dropwizard": _dropwizard_summary(
                    _json_object(dropwizard_body, f"{name} Dropwizard metrics"),
                    required,
                ),
            }
            if name == "openmetadata":
                prometheus_body, prometheus_type = _fetch(
                    forward.local_port,
                    "/prometheus",
                    label="OpenMetadata Prometheus metrics",
                )
                try:
                    prometheus_text = prometheus_body.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise MetadataFabricProviderMetricsError(
                        "OpenMetadata Prometheus metrics are not UTF-8"
                    ) from exc
                observation["transport"]["prometheus_path"] = "/prometheus"
                observation["transport"]["prometheus_content_type"] = prometheus_type
                observation["prometheus"] = _prometheus_summary(prometheus_text)
        except Exception as exc:
            failure = exc
        finally:
            try:
                stopped[name] = forward.stop()
            except Exception as exc:
                failure = failure or exc
                stopped[name] = False
        if failure is not None:
            if isinstance(failure, MetadataFabricProviderMetricsError):
                raise failure
            raise MetadataFabricProviderMetricsError(
                f"{name} metrics collection failed"
            ) from failure
        provider_observations[name] = observation

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
        "cluster": {
            "context": context,
            "uid": cluster_uid,
            "namespace": namespace,
        },
        "providers": provider_observations,
        "runtime_checks": {
            "all_port_forwards_stopped": all(stopped.values()),
            "port_forwards": stopped,
            "provider_resources_mutated": False,
            "kubernetes_credential_resources_requested": False,
        },
    }


def _dropwizard_errors(
    name: str,
    summary: Mapping[str, Any],
    required: tuple[str, ...],
) -> list[str]:
    errors: list[str] = []
    counts = _mapping(summary.get("section_counts"))
    if (
        summary.get("format") != "dropwizard_json"
        or summary.get("version") != DROPWIZARD_VERSION
    ):
        errors.append(f"{name} Dropwizard format or version does not match")
    if set(counts) != {"gauges", "counters", "histograms", "meters", "timers"}:
        errors.append(f"{name} Dropwizard section inventory does not match")
    if not isinstance(counts.get("gauges"), int) or counts.get("gauges", 0) <= 0:
        errors.append(f"{name} Dropwizard gauge inventory is empty")
    if not _valid_sha256(summary.get("metric_name_fingerprint")):
        errors.append(f"{name} Dropwizard metric fingerprint is invalid")
    if summary.get("required_metric_names") != list(required):
        errors.append(f"{name} required metric inventory does not match")
    if summary.get("missing_required_metrics") != []:
        errors.append(f"{name} required metrics are missing")
    values = _mapping(summary.get("required_gauge_values"))
    if set(values) != set(required) or any(
        not isinstance(value, (int, float)) for value in values.values()
    ):
        errors.append(f"{name} required gauge values are invalid")
    return errors


def _prometheus_errors(summary: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if summary.get("format") != "prometheus_text_0.0.4":
        errors.append("OpenMetadata Prometheus format does not match")
    for key in ("metric_family_count", "sample_count"):
        if not isinstance(summary.get(key), int) or summary.get(key, 0) <= 0:
            errors.append(f"OpenMetadata Prometheus {key} is empty")
    for key in (
        "metric_family_name_fingerprint",
        "metric_family_type_fingerprint",
        "label_name_fingerprint",
    ):
        if not _valid_sha256(summary.get(key)):
            errors.append(f"OpenMetadata Prometheus {key} is invalid")
    if summary.get("required_metric_names") != list(OPENMETADATA_REQUIRED_PROMETHEUS):
        errors.append("OpenMetadata Prometheus required inventory does not match")
    if summary.get("missing_required_metrics") != []:
        errors.append("OpenMetadata Prometheus required metrics are missing")
    return errors


def _observation_errors(
    observation: Mapping[str, Any], *, now: datetime, max_age_seconds: float
) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(observation):
        errors.append("provider metrics observation contains credential-bearing fields")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("provider metrics observation schema does not match")
    try:
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
        if age < -30 or age > max_age_seconds:
            errors.append(
                "provider metrics observation is outside the freshness window"
            )
    except ValueError:
        errors.append("provider metrics observation timestamp is invalid")
    contract = _mapping(observation.get("contract"))
    if contract.get("local_static_contract_verified") is not True:
        errors.append("provider metrics static contract was not verified")
    if not _valid_sha256(contract.get("contract_fingerprint")):
        errors.append("provider metrics contract fingerprint is invalid")
    cluster = _mapping(observation.get("cluster"))
    namespace = _mapping(cluster.get("namespace"))
    if cluster.get("context") != CONTEXT or not cluster.get("uid"):
        errors.append("provider metrics cluster identity does not match")
    if namespace.get("name") != NAMESPACE or not namespace.get("uid"):
        errors.append("provider metrics Namespace identity does not match")

    providers = _mapping(observation.get("providers"))
    if set(providers) != set(PROVIDERS):
        errors.append("provider metrics inventory does not match")
    for name, spec in PROVIDERS.items():
        provider = _mapping(providers.get(name))
        identity = _mapping(provider.get("identity"))
        service = _mapping(identity.get("service"))
        workload = _mapping(identity.get("workload"))
        transport = _mapping(provider.get("transport"))
        expected_kind, expected_name = str(spec["workload"]).split("/", 1)
        expected_kind = "Deployment" if expected_kind == "deployment" else "StatefulSet"
        if (
            service.get("name") != spec["service"]
            or not service.get("uid")
            or service.get("type") != "ClusterIP"
            or spec["port"] not in (service.get("ports") or [])
        ):
            errors.append(f"{name} metrics Service identity does not match")
        if (
            workload.get("kind") != expected_kind
            or workload.get("name") != expected_name
            or not workload.get("uid")
            or workload.get("image") != spec["image"]
            or workload.get("ready_replicas") != 1
        ):
            errors.append(f"{name} metrics workload identity does not match")
        if (
            transport.get("scheme") != "http"
            or transport.get("service_port") != spec["port"]
            or transport.get("dropwizard_path") != "/metrics"
            or transport.get("dropwizard_content_type") != "application/json"
        ):
            errors.append(f"{name} metrics transport does not match")
        required = (
            OPENMETADATA_REQUIRED_GAUGES
            if name == "openmetadata"
            else GRAVITINO_REQUIRED_GAUGES
        )
        errors.extend(
            _dropwizard_errors(
                name, _mapping(provider.get("dropwizard")), required
            )
        )
        if name == "openmetadata":
            if (
                transport.get("prometheus_path") != "/prometheus"
                or transport.get("prometheus_content_type") != "text/plain"
            ):
                errors.append("OpenMetadata Prometheus transport does not match")
            errors.extend(_prometheus_errors(_mapping(provider.get("prometheus"))))

    om_values = _mapping(
        _mapping(_mapping(providers.get("openmetadata")).get("dropwizard")).get(
            "required_gauge_values"
        )
    )
    if (
        om_values.get("health.aggregate.healthy") != 1
        or om_values.get("health.aggregate.unhealthy") != 0
        or not isinstance(om_values.get("database.pool.MaxConnections"), (int, float))
        or om_values.get("database.pool.MaxConnections", 0) <= 0
        or om_values.get("database.pool.TotalConnections", 0)
        > om_values.get("database.pool.MaxConnections", 0)
    ):
        errors.append("OpenMetadata health/database metrics are not healthy")
    grav_values = _mapping(
        _mapping(_mapping(providers.get("gravitino")).get("dropwizard")).get(
            "required_gauge_values"
        )
    )
    if (
        grav_values.get("gravitino-relational-store.datasource.max-connections", 0)
        <= 0
        or grav_values.get("gravitino-server.http-server.total-thread.num", 0) <= 0
        or grav_values.get("jvm.heap.max", 0) <= 0
        or grav_values.get("jvm.heap.used", -1) < 0
        or grav_values.get("jvm.heap.used", 0) > grav_values.get("jvm.heap.max", 0)
    ):
        errors.append("Gravitino datasource/JVM metrics are not healthy")

    runtime = _mapping(observation.get("runtime_checks"))
    if runtime.get("all_port_forwards_stopped") is not True:
        errors.append("provider metrics port-forwards were not stopped")
    if _mapping(runtime.get("port_forwards")) != {
        "openmetadata": True,
        "gravitino": True,
    }:
        errors.append("provider metrics port-forward cleanup inventory does not match")
    if runtime.get("provider_resources_mutated") is not False:
        errors.append("provider metrics collection may not mutate provider resources")
    if runtime.get("kubernetes_credential_resources_requested") is not False:
        errors.append("provider metrics collection may not request Kubernetes Secrets")
    return errors


def build_provider_metrics_evidence(
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build fail-closed evidence for local provider-native metrics."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricProviderMetricsError(
            "verification time must be timezone-aware"
        )
    errors = _observation_errors(
        observation, now=current, max_age_seconds=max_age_seconds
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop_provider_native_metrics",
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "observation_fingerprint": recovery._canonical_sha256(observation),
        "checks": {
            "static_contract": "passed" if verified else "blocked",
            "provider_identity": "passed" if verified else "blocked",
            "openmetadata_dropwizard": "passed" if verified else "blocked",
            "openmetadata_prometheus": "passed" if verified else "blocked",
            "gravitino_dropwizard": "passed" if verified else "blocked",
            "credential_free_projection": "passed" if verified else "blocked",
            "ephemeral_cleanup": "passed" if verified else "blocked",
            "production_boundaries": "passed",
        },
        "errors": errors,
        "metrics_scope": "local_provider_native_endpoints_via_loopback_port_forward",
        "local_provider_metrics_verified": verified,
        "production_metrics_verified": False,
        "otel_pipeline_verified": False,
        "alert_delivery_verified": False,
        "slo_verified": False,
        "metrics_tls_verified": False,
        "oidc_verified": False,
        "network_policy_enforcement_verified": False,
        "upgrade_verified": False,
        "writes_to_gda_enabled": False,
        "production_ready": False,
        "observation": observation,
    }
    return {
        **stable,
        "generated_at": current.isoformat(),
        "status": "local_provider_metrics_verified" if verified else "blocked",
        "evidence_fingerprint": recovery._canonical_sha256(stable),
    }


def verify_evidence_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("provider metrics evidence contains credential-bearing fields")
    if report.get("schema") != EVIDENCE_SCHEMA:
        errors.append("provider metrics evidence schema does not match")
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "status", "evidence_fingerprint"}
    }
    if report.get("evidence_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("provider metrics evidence fingerprint does not match")
    for claim in (
        "production_metrics_verified",
        "otel_pipeline_verified",
        "alert_delivery_verified",
        "slo_verified",
        "metrics_tls_verified",
        "oidc_verified",
        "network_policy_enforcement_verified",
        "upgrade_verified",
        "writes_to_gda_enabled",
        "production_ready",
    ):
        if report.get(claim) is not False:
            errors.append(f"provider metrics evidence may not claim {claim}")
    return errors


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricProviderMetricsError("JSON input must be an object")
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
            report = build_provider_metrics_contract_report()
            _write_report(report, None)
            return 0 if report["local_static_contract_verified"] else 1
        if args.command == "run":
            observation = collect_live_provider_metrics(
                kubectl=args.kubectl, context=args.context
            )
            report = build_provider_metrics_evidence(observation)
            _write_report(report, args.output)
            return 0 if report["local_provider_metrics_verified"] else 1
        report = _load_json_object(args.input)
        errors = verify_evidence_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        MetadataFabricProviderMetricsError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata provider metrics: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
