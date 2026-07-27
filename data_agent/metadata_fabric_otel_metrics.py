"""Verify a bounded local OTel pipeline for Metadata Fabric metrics.

The command temporarily deploys an OpenTelemetry Collector and the upstream
Prometheus JSON Exporter, observes two scrape intervals, and removes every
pipeline resource. Evidence is restricted to allowlisted health values and
metric inventory fingerprints. It does not claim durable storage, alerting,
TLS, SLOs, tenant isolation, or production monitoring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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

from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery
from . import metadata_fabric_sandbox as sandbox


CONTRACT_SCHEMA = "gda.metadata_fabric_otel_metrics_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_otel_metrics_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_otel_metrics_evidence.v1"
PROFILE_SCHEMA = "gda.metadata_fabric_otel_metrics_profile.v1"
CONTEXT = "docker-desktop"
NAMESPACE = sandbox.NAMESPACE
PART_OF_LABEL = "gda-metadata-fabric-otel-metrics"
RESOURCE_SELECTOR = f"app.kubernetes.io/part-of={PART_OF_LABEL}"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

OTEL_VERSION = "0.135.0"
OTEL_IMAGE = (
    "otel/opentelemetry-collector-contrib@"
    "sha256:330e0c7e4f4f60dc94f9657e5fb96ce9cfcf333b9aaa41a5c06b4ce4532de92d"
)
JSON_EXPORTER_VERSION = "0.7.0"
JSON_EXPORTER_IMAGE = (
    "prometheuscommunity/json-exporter@"
    "sha256:62370e6e39818966ae1ddfbb69ebf480c697a313cc05ddd76c910b9fbe6934ec"
)
SCRAPE_INTERVAL_SECONDS = 5
REPEATED_OBSERVATIONS = 2

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-otel-metrics.local.yaml"
DEFAULT_WRAPPER = REPO_ROOT / "scripts/metadata-fabric-otel-metrics.sh"
DEFAULT_MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-otel-metrics"
MANIFEST_FILES = (
    "kustomization.yaml",
    "serviceaccounts.yaml",
    "configmaps.yaml",
    "workloads.yaml",
    "networkpolicy.yaml",
)

OTEL_DEPLOYMENT = "metadata-otel-collector"
OTEL_SERVICE = "metadata-otel-collector"
JSON_EXPORTER_DEPLOYMENT = "metadata-json-exporter"
JSON_EXPORTER_SERVICE = "metadata-json-exporter"
EXPECTED_DEPLOYMENTS = {
    OTEL_DEPLOYMENT: OTEL_IMAGE,
    JSON_EXPORTER_DEPLOYMENT: JSON_EXPORTER_IMAGE,
}
EXPECTED_SERVICES = {
    OTEL_SERVICE: [8889, 13133],
    JSON_EXPORTER_SERVICE: [7979],
}
EXPECTED_CONFIGMAPS = {
    "metadata-otel-collector-config",
    "metadata-json-exporter-config",
}
EXPECTED_SERVICEACCOUNTS = {
    "metadata-otel-collector",
    "metadata-json-exporter",
}
EXPECTED_NETWORKPOLICIES = {
    "metadata-otel-collector-egress",
    "metadata-json-exporter-ingress",
    "metadata-json-exporter-egress",
}
EXPECTED_RUNTIME_RESOURCES = sorted(
    [f"Deployment/{name}" for name in EXPECTED_DEPLOYMENTS]
    + [f"Service/{name}" for name in EXPECTED_SERVICES]
    + [f"ConfigMap/{name}" for name in EXPECTED_CONFIGMAPS]
    + [f"ServiceAccount/{name}" for name in EXPECTED_SERVICEACCOUNTS]
    + [f"NetworkPolicy/{name}" for name in EXPECTED_NETWORKPOLICIES]
)

OPENMETADATA_REQUIRED_FAMILIES = (
    "auth_attempts",
    "db_connections",
    "http_server_requests_sec_seconds",
    "jvm_memory_used_bytes",
)
GRAVITINO_REQUIRED_FAMILIES = (
    "gda_gravitino_datasource_active_connections",
    "gda_gravitino_datasource_max_connections",
    "gda_gravitino_http_threads",
    "gda_gravitino_jvm_heap_used_bytes",
    "gda_gravitino_jvm_heap_max_bytes",
)
GRAVITINO_JSON_PATHS = {
    "gda_gravitino_datasource_active_connections": (
        r"{ .gauges.gravitino-relational-store\.datasource\.active-connections.value }"
    ),
    "gda_gravitino_datasource_max_connections": (
        r"{ .gauges.gravitino-relational-store\.datasource\.max-connections.value }"
    ),
    "gda_gravitino_http_threads": (
        r"{ .gauges.gravitino-server\.http-server\.total-thread\.num.value }"
    ),
    "gda_gravitino_jvm_heap_used_bytes": r"{ .gauges.jvm\.heap\.used.value }",
    "gda_gravitino_jvm_heap_max_bytes": r"{ .gauges.jvm\.heap\.max.value }",
}


class MetadataFabricOtelMetricsError(RuntimeError):
    """The local OTel metrics contract or live verification failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    documents = []
    for value in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if value is not None:
            if not isinstance(value, dict):
                raise TypeError(f"{path.name} contains a non-object document")
            documents.append(value)
    return documents


def _resource_map(documents: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    resources: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        kind = document.get("kind")
        name = _mapping(document.get("metadata")).get("name")
        if not isinstance(kind, str) or not isinstance(name, str):
            raise TypeError("Kubernetes resource kind or name is missing")
        key = (kind, name)
        if key in resources:
            raise TypeError(f"duplicate Kubernetes resource: {kind}/{name}")
        resources[key] = document
    return resources


def _contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key) in forbidden or _contains_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    cluster = _mapping(profile.get("cluster"))
    components = _mapping(profile.get("components"))
    pipeline = _mapping(profile.get("pipeline"))
    claims = _mapping(profile.get("claims"))
    if (
        profile.get("schema") != PROFILE_SCHEMA
        or profile.get("environment") != "local_docker_desktop"
    ):
        errors.append("OTel metrics profile schema or environment does not match")
    if cluster != {"context": CONTEXT, "namespace": NAMESPACE}:
        errors.append("OTel metrics cluster boundary does not match")

    otel = _mapping(components.get("otel_collector"))
    if otel != {
        "version": OTEL_VERSION,
        "image": OTEL_IMAGE,
        "workload": f"deployment/{OTEL_DEPLOYMENT}",
        "service": OTEL_SERVICE,
        "prometheus_port": 8889,
    }:
        errors.append("OTel Collector component profile does not match")
    exporter = _mapping(components.get("json_exporter"))
    if exporter != {
        "version": JSON_EXPORTER_VERSION,
        "image": JSON_EXPORTER_IMAGE,
        "workload": f"deployment/{JSON_EXPORTER_DEPLOYMENT}",
        "service": JSON_EXPORTER_SERVICE,
        "port": 7979,
    }:
        errors.append("JSON Exporter component profile does not match")
    if pipeline != {
        "scrape_interval_seconds": SCRAPE_INTERVAL_SECONDS,
        "repeated_observations": REPEATED_OBSERVATIONS,
        "openmetadata_target": "http://openmetadata:8586/prometheus",
        "gravitino_target": "http://metadata-gravitino:8090/metrics",
        "exported_endpoint": "http://metadata-otel-collector:8889/metrics",
    }:
        errors.append("OTel metrics pipeline profile does not match")

    expected_claims = {
        "local_otel_metrics_pipeline_verified",
        "local_repeated_scrape_verified",
        "otel_pipeline_verified",
        "production_metrics_verified",
        "persistent_metrics_storage_verified",
        "alert_delivery_verified",
        "slo_verified",
        "metrics_tls_verified",
        "tenant_isolation_verified",
        "oidc_verified",
        "network_policy_enforcement_verified",
        "upgrade_verified",
        "writes_to_gda_enabled",
        "production_ready",
    }
    if set(claims) != expected_claims:
        errors.append("OTel metrics claim inventory does not match")
    for claim in sorted(expected_claims):
        if claims.get(claim) is not False:
            errors.append(f"unverified OTel metrics profile claim must remain false: {claim}")
    return errors


def _manifest_errors(manifest_dir: Path) -> tuple[list[str], dict[str, str]]:
    errors: list[str] = []
    config_hashes: dict[str, str] = {}
    try:
        documents: list[dict[str, Any]] = []
        for name in MANIFEST_FILES[1:]:
            documents.extend(_load_yaml_documents(manifest_dir / name))
        resources = _resource_map(documents)
        kustomization_docs = _load_yaml_documents(manifest_dir / MANIFEST_FILES[0])
        if len(kustomization_docs) != 1:
            raise TypeError("kustomization document count does not match")
        kustomization = kustomization_docs[0]
    except (OSError, TypeError, yaml.YAMLError) as exc:
        return [f"OTel metrics manifests are invalid: {type(exc).__name__}"], {}

    expected_keys = {
        *(("Deployment", name) for name in EXPECTED_DEPLOYMENTS),
        *(("Service", name) for name in EXPECTED_SERVICES),
        *(("ConfigMap", name) for name in EXPECTED_CONFIGMAPS),
        *(("ServiceAccount", name) for name in EXPECTED_SERVICEACCOUNTS),
        *(("NetworkPolicy", name) for name in EXPECTED_NETWORKPOLICIES),
    }
    if set(resources) != expected_keys:
        errors.append("OTel metrics Kubernetes resource inventory does not match")
    if _contains_key(
        documents,
        {
            "secret",
            "secretKeyRef",
            "persistentVolumeClaim",
            "hostPath",
            "roleRef",
        },
    ):
        errors.append("OTel metrics manifests request credentials, storage, or RBAC")

    expected_resource_files = list(MANIFEST_FILES[1:])
    labels = kustomization.get("labels")
    label_pairs = {}
    if isinstance(labels, list) and labels:
        label_pairs = dict(_mapping(_mapping(labels[0]).get("pairs")))
    if (
        kustomization.get("kind") != "Kustomization"
        or kustomization.get("namespace") != NAMESPACE
        or kustomization.get("resources") != expected_resource_files
        or label_pairs.get("app.kubernetes.io/part-of") != PART_OF_LABEL
        or label_pairs.get("gda.openai.com/environment")
        != "local-observability-evidence"
    ):
        errors.append("OTel metrics kustomization boundary does not match")

    for name in EXPECTED_SERVICEACCOUNTS:
        service_account = _mapping(resources.get(("ServiceAccount", name)))
        if service_account.get("automountServiceAccountToken") is not False:
            errors.append(f"OTel metrics ServiceAccount must not mount a token: {name}")

    for name, expected_image in EXPECTED_DEPLOYMENTS.items():
        deployment = _mapping(resources.get(("Deployment", name)))
        spec = _mapping(deployment.get("spec"))
        template_spec = _mapping(_mapping(spec.get("template")).get("spec"))
        containers = template_spec.get("containers")
        container = _mapping(containers[0]) if isinstance(containers, list) and len(containers) == 1 else {}
        security = _mapping(container.get("securityContext"))
        if (
            deployment.get("apiVersion") != "apps/v1"
            or spec.get("replicas") != 1
            or spec.get("strategy") != {"type": "Recreate"}
            or template_spec.get("serviceAccountName") != name
            or template_spec.get("automountServiceAccountToken") is not False
            or container.get("image") != expected_image
            or security.get("runAsNonRoot") is not True
            or security.get("allowPrivilegeEscalation") is not False
            or security.get("readOnlyRootFilesystem") is not True
            or _mapping(security.get("capabilities")).get("drop") != ["ALL"]
        ):
            errors.append(f"OTel metrics Deployment contract does not match: {name}")
    exporter_container = _mapping(
        _mapping(_mapping(resources.get(("Deployment", JSON_EXPORTER_DEPLOYMENT))).get("spec"))
        .get("template")
    )
    exporter_pod_spec = _mapping(exporter_container.get("spec"))
    exporter_containers = exporter_pod_spec.get("containers")
    exporter_security = _mapping(
        _mapping(exporter_containers[0]).get("securityContext")
        if isinstance(exporter_containers, list) and exporter_containers
        else {}
    )
    if exporter_security.get("runAsUser") != 65534 or exporter_security.get("runAsGroup") != 65534:
        errors.append("JSON Exporter must pin the numeric nobody identity")

    for name, expected_ports in EXPECTED_SERVICES.items():
        service = _mapping(resources.get(("Service", name)))
        spec = _mapping(service.get("spec"))
        ports = spec.get("ports") if isinstance(spec.get("ports"), list) else []
        observed_ports = sorted(
            int(_mapping(port).get("port"))
            for port in ports
            if isinstance(_mapping(port).get("port"), int)
        )
        if spec.get("type") != "ClusterIP" or observed_ports != sorted(expected_ports):
            errors.append(f"OTel metrics Service contract does not match: {name}")

    try:
        json_exporter_cm = _mapping(
            resources[("ConfigMap", "metadata-json-exporter-config")]
        )
        json_exporter_text = _mapping(json_exporter_cm.get("data")).get("config.yaml")
        json_exporter_config = yaml.safe_load(str(json_exporter_text))
        metrics = _mapping(_mapping(_mapping(json_exporter_config).get("modules")).get("gravitino")).get("metrics")
        metric_items = metrics if isinstance(metrics, list) else []
        observed_paths = {
            str(_mapping(item).get("name")): _mapping(item).get("path")
            for item in metric_items
        }
        if observed_paths != GRAVITINO_JSON_PATHS:
            errors.append("JSON Exporter allowlisted metric paths do not match")
        config_hashes["metadata-json-exporter-config"] = hashlib.sha256(
            str(json_exporter_text).encode("utf-8")
        ).hexdigest()

        otel_cm = _mapping(resources[("ConfigMap", "metadata-otel-collector-config")])
        otel_text = _mapping(otel_cm.get("data")).get("config.yaml")
        otel_config = _mapping(yaml.safe_load(str(otel_text)))
        receiver = _mapping(_mapping(otel_config.get("receivers")).get("prometheus/provider_metrics"))
        prometheus_config = _mapping(receiver.get("config"))
        global_config = _mapping(prometheus_config.get("global"))
        scrape_configs = prometheus_config.get("scrape_configs")
        jobs = {
            str(_mapping(job).get("job_name")): _mapping(job)
            for job in scrape_configs
        } if isinstance(scrape_configs, list) else {}
        exporter = _mapping(_mapping(otel_config.get("exporters")).get("prometheus"))
        if (
            global_config.get("scrape_interval") != f"{SCRAPE_INTERVAL_SECONDS}s"
            or global_config.get("scrape_timeout") != "4s"
            or set(jobs) != {"openmetadata", "gravitino"}
            or _mapping(jobs.get("openmetadata")).get("metrics_path") != "/prometheus"
            or _mapping(jobs.get("gravitino")).get("metrics_path") != "/probe"
            or _mapping(_mapping(jobs.get("gravitino")).get("params")).get("module") != ["gravitino"]
            or exporter.get("endpoint") != "0.0.0.0:8889"
            or _mapping(exporter.get("const_labels"))
            != {"gda_pipeline": "metadata_fabric_local"}
        ):
            errors.append("OTel Collector scrape/export contract does not match")
        config_hashes["metadata-otel-collector-config"] = hashlib.sha256(
            str(otel_text).encode("utf-8")
        ).hexdigest()
    except (KeyError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"OTel metrics embedded configuration is invalid: {type(exc).__name__}")

    for name in EXPECTED_NETWORKPOLICIES:
        policy = _mapping(resources.get(("NetworkPolicy", name)))
        spec = _mapping(policy.get("spec"))
        if not _mapping(spec.get("podSelector")) or not spec.get("policyTypes"):
            errors.append(f"OTel metrics NetworkPolicy contract does not match: {name}")
    return errors, config_hashes


def build_otel_metrics_contract_report(
    profile_path: Path | None = None,
    wrapper_path: Path | None = None,
    manifest_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate the bounded local OTel profile and Kubernetes manifests."""
    profile_file = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    wrapper = (wrapper_path or DEFAULT_WRAPPER).resolve()
    manifests = (manifest_dir or DEFAULT_MANIFEST_DIR).resolve()
    errors: list[str] = []
    try:
        profile = provider_metrics.repository._load_yaml_object(profile_file)
        errors.extend(_profile_errors(profile))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"OTel metrics profile is invalid: {type(exc).__name__}")

    manifest_errors, config_hashes = _manifest_errors(manifests)
    errors.extend(manifest_errors)
    provider_contract = provider_metrics.build_provider_metrics_contract_report()
    if provider_contract.get("local_static_contract_verified") is not True:
        errors.append("provider-native metrics contract is invalid")
    try:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_otel_metrics"):
            if marker not in wrapper_text:
                errors.append(f"OTel metrics wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"OTel metrics wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    paths = [Path(__file__).resolve(), profile_file, wrapper]
    paths.extend(manifests / name for name in MANIFEST_FILES)
    for path in paths:
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
        "components": {
            "otel_collector": {"version": OTEL_VERSION, "image": OTEL_IMAGE},
            "json_exporter": {
                "version": JSON_EXPORTER_VERSION,
                "image": JSON_EXPORTER_IMAGE,
            },
        },
        "scrape_interval_seconds": SCRAPE_INTERVAL_SECONDS,
        "repeated_observations": REPEATED_OBSERVATIONS,
        "openmetadata_required_families": OPENMETADATA_REQUIRED_FAMILIES,
        "gravitino_required_families": GRAVITINO_REQUIRED_FAMILIES,
        "runtime_resource_inventory": EXPECTED_RUNTIME_RESOURCES,
        "config_hashes": config_hashes,
        "local_static_contract_verified": not errors,
        "local_otel_metrics_pipeline_verified": False,
        "otel_pipeline_verified": False,
        "production_metrics_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


class _OtelPortForward:
    def __init__(
        self,
        *,
        kubectl: str,
        context: str,
        namespace: str = NAMESPACE,
        local_port: int | None = None,
    ) -> None:
        self.kubectl = kubectl
        self.context = context
        self.namespace = namespace
        self.local_port = local_port or provider_metrics.repository._free_local_port()
        self.process: subprocess.Popen[bytes] | None = None

    def command(self) -> list[str]:
        return [
            self.kubectl,
            "--context",
            self.context,
            "-n",
            self.namespace,
            "port-forward",
            f"service/{OTEL_SERVICE}",
            f"{self.local_port}:8889",
            "--address=127.0.0.1",
        ]

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(
                self.command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            raise MetadataFabricOtelMetricsError(
                "OTel metrics port-forward was unavailable"
            ) from exc
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise MetadataFabricOtelMetricsError(
                    "OTel metrics port-forward stopped before readiness"
                )
            try:
                with socket.create_connection(("127.0.0.1", self.local_port), timeout=1):
                    return
            except OSError:
                time.sleep(0.25)
        self.stop()
        raise MetadataFabricOtelMetricsError(
            "OTel metrics port-forward did not become ready"
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


def _fetch_metrics(local_port: int) -> str:
    request = urllib.request.Request(
        f"http://127.0.0.1:{local_port}/metrics",
        headers={"Accept": "text/plain"},
        method="GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            content_type = response.headers.get_content_type()
    except (OSError, urllib.error.URLError) as exc:
        raise MetadataFabricOtelMetricsError("OTel metrics request failed") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise MetadataFabricOtelMetricsError("OTel metrics response is too large")
    if content_type != "text/plain":
        raise MetadataFabricOtelMetricsError("OTel metrics response is not text/plain")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MetadataFabricOtelMetricsError("OTel metrics response is not UTF-8") from exc


def _sample_value(samples: list[Any], name: str, job: str) -> float | None:
    matches = [
        sample
        for sample in samples
        if sample.name == name and sample.labels.get("job") == job
    ]
    if len(matches) != 1:
        return None
    value = float(matches[0].value)
    return value if math.isfinite(value) else None


def _pipeline_summary(payload: str, *, sequence: int, observed_at: datetime) -> dict[str, Any]:
    try:
        families = list(text_string_to_metric_families(payload))
    except (TypeError, ValueError) as exc:
        raise MetadataFabricOtelMetricsError("OTel metrics are invalid Prometheus text") from exc
    family_names = sorted(family.name for family in families)
    family_types = sorted((family.name, family.type) for family in families)
    samples = [sample for family in families for sample in family.samples]
    label_names = sorted(
        {str(label) for sample in samples for label in sample.labels}
    )
    required_families = {
        "openmetadata": list(OPENMETADATA_REQUIRED_FAMILIES),
        "gravitino": list(GRAVITINO_REQUIRED_FAMILIES),
    }
    missing = {
        provider: [name for name in names if name not in family_names]
        for provider, names in required_families.items()
    }
    required_sample_names = {
        *OPENMETADATA_REQUIRED_FAMILIES,
        *GRAVITINO_REQUIRED_FAMILIES,
        "auth_attempts_total",
        "db_connections_total",
        "up",
        "scrape_samples_scraped",
    }
    required_samples = [
        sample for sample in samples if sample.name in required_sample_names
    ]
    constant_labels_verified = bool(required_samples) and all(
        sample.labels.get("gda_pipeline") == "metadata_fabric_local"
        and sample.labels.get("gda_provider") in {"openmetadata", "gravitino"}
        for sample in required_samples
    )
    gravitino_values = {
        name: _sample_value(samples, name, "gravitino")
        for name in GRAVITINO_REQUIRED_FAMILIES
    }
    return {
        "sequence": sequence,
        "observed_at": observed_at.isoformat(),
        "format": "prometheus_text_0.0.4",
        "metric_family_count": len(families),
        "sample_count": len(samples),
        "metric_family_name_fingerprint": recovery._canonical_sha256(family_names),
        "metric_family_type_fingerprint": recovery._canonical_sha256(family_types),
        "metric_type_counts": dict(sorted(Counter(family.type for family in families).items())),
        "label_name_count": len(label_names),
        "label_name_fingerprint": recovery._canonical_sha256(label_names),
        "required_families": required_families,
        "missing_required_families": missing,
        "jobs": {
            job: {
                "up": _sample_value(samples, "up", job),
                "scrape_samples_scraped": _sample_value(
                    samples, "scrape_samples_scraped", job
                ),
            }
            for job in ("openmetadata", "gravitino")
        },
        "gravitino_values": gravitino_values,
        "constant_labels_verified": constant_labels_verified,
        "raw_metrics_retained": False,
    }


def _pipeline_summary_errors(summary: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if summary.get("format") != "prometheus_text_0.0.4":
        errors.append("OTel Prometheus format does not match")
    for key in ("metric_family_count", "sample_count"):
        if not isinstance(summary.get(key), int) or summary.get(key, 0) <= 0:
            errors.append(f"OTel {key} is empty")
    for key in (
        "metric_family_name_fingerprint",
        "metric_family_type_fingerprint",
        "label_name_fingerprint",
    ):
        if not _valid_sha256(summary.get(key)):
            errors.append(f"OTel {key} is invalid")
    if _mapping(summary.get("required_families")) != {
        "openmetadata": list(OPENMETADATA_REQUIRED_FAMILIES),
        "gravitino": list(GRAVITINO_REQUIRED_FAMILIES),
    }:
        errors.append("OTel required family inventory does not match")
    if _mapping(summary.get("missing_required_families")) != {
        "openmetadata": [],
        "gravitino": [],
    }:
        errors.append("OTel required metric families are missing")
    jobs = _mapping(summary.get("jobs"))
    if set(jobs) != {"openmetadata", "gravitino"}:
        errors.append("OTel scrape job inventory does not match")
    for job in ("openmetadata", "gravitino"):
        values = _mapping(jobs.get(job))
        if values.get("up") != 1.0:
            errors.append(f"OTel {job} scrape is not up")
        samples = values.get("scrape_samples_scraped")
        if not isinstance(samples, (int, float)) or samples <= 0:
            errors.append(f"OTel {job} scrape has no samples")
    gravitino_values = _mapping(summary.get("gravitino_values"))
    if set(gravitino_values) != set(GRAVITINO_REQUIRED_FAMILIES) or any(
        not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        for value in gravitino_values.values()
    ):
        errors.append("OTel Gravitino allowlisted values are invalid")
    if summary.get("constant_labels_verified") is not True:
        errors.append("OTel constant/provider labels were not verified")
    if summary.get("raw_metrics_retained") is not False:
        errors.append("OTel evidence may not retain raw metrics")
    return errors


def _summary_ready(summary: Mapping[str, Any]) -> bool:
    return not _pipeline_summary_errors(summary)


def _wait_for_pipeline_summary(local_port: int, *, sequence: int) -> dict[str, Any]:
    deadline = time.monotonic() + 90
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            observed_at = datetime.now(UTC)
            summary = _pipeline_summary(
                _fetch_metrics(local_port), sequence=sequence, observed_at=observed_at
            )
            if _summary_ready(summary):
                return summary
        except MetadataFabricOtelMetricsError as exc:
            last_error = exc
        time.sleep(1)
    raise MetadataFabricOtelMetricsError(
        "OTel pipeline did not expose the required metrics"
    ) from last_error


def _list_ephemeral_resources(runner: recovery._CommandRunner) -> list[str]:
    payload = runner.kubectl_json(
        [
            "-n",
            NAMESPACE,
            "get",
            "deployment,service,configmap,serviceaccount,networkpolicy",
            "-l",
            RESOURCE_SELECTOR,
            "-o",
            "json",
        ],
        label="list local OTel metrics resources",
    )
    result = []
    for item in payload.get("items") or []:
        resource = _mapping(item)
        kind = resource.get("kind")
        name = _mapping(resource.get("metadata")).get("name")
        if isinstance(kind, str) and isinstance(name, str):
            result.append(f"{kind}/{name}")
    return sorted(result)


def _wait_for_ephemeral_cleanup(runner: recovery._CommandRunner) -> list[str]:
    deadline = time.monotonic() + 90
    remaining: list[str] = []
    while time.monotonic() < deadline:
        remaining = _list_ephemeral_resources(runner)
        if not remaining:
            return []
        time.sleep(1)
    return remaining


def _component_identities(
    runner: recovery._CommandRunner,
    expected_config_hashes: Mapping[str, Any],
) -> dict[str, Any]:
    deployments: dict[str, Any] = {}
    for name in EXPECTED_DEPLOYMENTS:
        payload = runner.kubectl_json(
            ["-n", NAMESPACE, "get", "deployment", name, "-o", "json"],
            label=f"read {name} identity",
        )
        metadata = _mapping(payload.get("metadata"))
        spec = _mapping(payload.get("spec"))
        pod_spec = _mapping(_mapping(spec.get("template")).get("spec"))
        containers = pod_spec.get("containers")
        container = _mapping(containers[0]) if isinstance(containers, list) and containers else {}
        deployments[name] = {
            "uid": metadata.get("uid"),
            "image": container.get("image"),
            "ready_replicas": _mapping(payload.get("status")).get("readyReplicas", 0),
            "service_account": pod_spec.get("serviceAccountName"),
        }
    services: dict[str, Any] = {}
    for name in EXPECTED_SERVICES:
        payload = runner.kubectl_json(
            ["-n", NAMESPACE, "get", "service", name, "-o", "json"],
            label=f"read {name} Service identity",
        )
        metadata = _mapping(payload.get("metadata"))
        spec = _mapping(payload.get("spec"))
        ports = spec.get("ports") if isinstance(spec.get("ports"), list) else []
        services[name] = {
            "uid": metadata.get("uid"),
            "type": spec.get("type"),
            "ports": sorted(
                int(_mapping(port).get("port"))
                for port in ports
                if isinstance(_mapping(port).get("port"), int)
            ),
        }
    configmaps: dict[str, Any] = {}
    for name in EXPECTED_CONFIGMAPS:
        payload = runner.kubectl_json(
            ["-n", NAMESPACE, "get", "configmap", name, "-o", "json"],
            label=f"read {name} ConfigMap identity",
        )
        metadata = _mapping(payload.get("metadata"))
        config_text = _mapping(payload.get("data")).get("config.yaml")
        digest = hashlib.sha256(str(config_text).encode("utf-8")).hexdigest()
        configmaps[name] = {
            "uid": metadata.get("uid"),
            "config_sha256": digest,
            "matches_static_contract": digest == expected_config_hashes.get(name),
        }
    return {
        "deployments": deployments,
        "services": services,
        "configmaps": configmaps,
    }


def _component_errors(components: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    deployments = _mapping(components.get("deployments"))
    services = _mapping(components.get("services"))
    configmaps = _mapping(components.get("configmaps"))
    if set(deployments) != set(EXPECTED_DEPLOYMENTS):
        errors.append("OTel Deployment identity inventory does not match")
    for name, image in EXPECTED_DEPLOYMENTS.items():
        item = _mapping(deployments.get(name))
        if (
            not item.get("uid")
            or item.get("image") != image
            or item.get("ready_replicas") != 1
            or item.get("service_account") != name
        ):
            errors.append(f"OTel Deployment identity does not match: {name}")
    if set(services) != set(EXPECTED_SERVICES):
        errors.append("OTel Service identity inventory does not match")
    for name, ports in EXPECTED_SERVICES.items():
        item = _mapping(services.get(name))
        if (
            not item.get("uid")
            or item.get("type") != "ClusterIP"
            or item.get("ports") != sorted(ports)
        ):
            errors.append(f"OTel Service identity does not match: {name}")
    if set(configmaps) != EXPECTED_CONFIGMAPS:
        errors.append("OTel ConfigMap identity inventory does not match")
    for name in EXPECTED_CONFIGMAPS:
        item = _mapping(configmaps.get(name))
        if (
            not item.get("uid")
            or not _valid_sha256(item.get("config_sha256"))
            or item.get("matches_static_contract") is not True
        ):
            errors.append(f"OTel ConfigMap identity does not match: {name}")
    return errors


def _preflight_snapshot(
    runner: recovery._CommandRunner,
) -> tuple[str | None, dict[str, Any], list[str], dict[str, Any]]:
    last_error: recovery.MetadataFabricRecoveryError | None = None
    for attempt in range(3):
        try:
            cluster_uid = recovery._cluster_uid(runner)
            namespace = recovery._namespace_identity(runner, NAMESPACE)
            resources = _list_ephemeral_resources(runner)
            providers = {
                name: provider_metrics._provider_identity(runner, name, spec)
                for name, spec in provider_metrics.PROVIDERS.items()
            }
            return cluster_uid, namespace, resources, providers
        except recovery.MetadataFabricRecoveryError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise MetadataFabricOtelMetricsError(
        f"OTel metrics preflight inspection failed: {last_error}"
    ) from last_error


def collect_live_otel_metrics_pipeline(
    *, kubectl: str = "kubectl", context: str = CONTEXT
) -> dict[str, Any]:
    """Deploy, observe twice, and completely remove the local metrics pipeline."""
    if context != CONTEXT:
        raise MetadataFabricOtelMetricsError(
            "OTel metrics verification requires docker-desktop"
        )
    started = datetime.now(UTC)
    contract = build_otel_metrics_contract_report()
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricOtelMetricsError("OTel metrics static contract is invalid")
    runner = recovery._CommandRunner(kubectl, context)
    cluster_uid, namespace, resources_before, providers_before = (
        _preflight_snapshot(runner)
    )
    if not cluster_uid or not namespace.get("uid"):
        raise MetadataFabricOtelMetricsError("OTel metrics cluster identity is unavailable")
    if resources_before:
        raise MetadataFabricOtelMetricsError(
            "pre-existing local OTel metrics resources must be removed first"
        )

    apply_attempted = False
    apply_completed = False
    rollouts = {name: False for name in EXPECTED_DEPLOYMENTS}
    forward: _OtelPortForward | None = None
    port_forward_stopped = True
    cleanup_command_completed = False
    remaining_resources: list[str] = []
    providers_preserved = False
    runtime_inventory: list[str] = []
    components: dict[str, Any] = {}
    scrapes: list[dict[str, Any]] = []
    failure: Exception | None = None
    try:
        apply_attempted = True
        runner.kubectl_run(
            ["apply", "-k", str(DEFAULT_MANIFEST_DIR)],
            timeout=180,
            label="apply local OTel metrics pipeline",
        )
        apply_completed = True
        for name in EXPECTED_DEPLOYMENTS:
            runner.kubectl_run(
                [
                    "-n",
                    NAMESPACE,
                    "rollout",
                    "status",
                    f"deployment/{name}",
                    "--timeout=180s",
                ],
                timeout=210,
                label=f"wait for {name} rollout",
            )
            rollouts[name] = True
        runtime_inventory = _list_ephemeral_resources(runner)
        components = _component_identities(runner, _mapping(contract.get("config_hashes")))
        forward = _OtelPortForward(kubectl=kubectl, context=context)
        forward.start()
        scrapes.append(_wait_for_pipeline_summary(forward.local_port, sequence=1))
        time.sleep(SCRAPE_INTERVAL_SECONDS + 1)
        scrapes.append(_wait_for_pipeline_summary(forward.local_port, sequence=2))
    except Exception as exc:
        failure = exc
    finally:
        if forward is not None:
            try:
                port_forward_stopped = forward.stop()
            except Exception as exc:
                failure = failure or exc
                port_forward_stopped = False
        if apply_attempted:
            try:
                runner.kubectl_run(
                    [
                        "delete",
                        "--ignore-not-found=true",
                        "-k",
                        str(DEFAULT_MANIFEST_DIR),
                    ],
                    timeout=180,
                    label="remove local OTel metrics pipeline",
                )
                cleanup_command_completed = True
                remaining_resources = _wait_for_ephemeral_cleanup(runner)
            except Exception as exc:
                failure = failure or exc
        try:
            providers_after = {
                name: provider_metrics._provider_identity(runner, name, spec)
                for name, spec in provider_metrics.PROVIDERS.items()
            }
            providers_preserved = providers_after == providers_before
        except Exception as exc:
            failure = failure or exc

    if failure is not None:
        if isinstance(failure, MetadataFabricOtelMetricsError):
            raise failure
        raise MetadataFabricOtelMetricsError(
            f"live OTel metrics pipeline verification failed: {failure}"
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
        "cluster": {
            "context": context,
            "uid": cluster_uid,
            "namespace": namespace,
        },
        "components": components,
        "scrapes": scrapes,
        "scrape_separation_seconds": round(
            (
                datetime.fromisoformat(scrapes[1]["observed_at"])
                - datetime.fromisoformat(scrapes[0]["observed_at"])
            ).total_seconds(),
            3,
        ),
        "runtime_checks": {
            "resources_absent_before_apply": resources_before == [],
            "apply_completed": apply_completed,
            "rollouts_completed": rollouts,
            "runtime_resource_inventory": runtime_inventory,
            "runtime_resource_inventory_matches": (
                runtime_inventory == EXPECTED_RUNTIME_RESOURCES
            ),
            "port_forward_stopped": port_forward_stopped,
            "cleanup_command_completed": cleanup_command_completed,
            "ephemeral_resources_removed": remaining_resources == [],
            "remaining_resources": remaining_resources,
            "provider_identities_preserved": providers_preserved,
            "kubernetes_credential_resources_requested": False,
            "persistent_volume_resources_requested": False,
            "rbac_resources_requested": False,
        },
    }


def _observation_errors(
    observation: Mapping[str, Any], *, now: datetime, max_age_seconds: float
) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(observation):
        errors.append("OTel metrics observation contains credential-bearing fields")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("OTel metrics observation schema does not match")
    try:
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
        if age < -30 or age > max_age_seconds:
            errors.append("OTel metrics observation is outside the freshness window")
    except ValueError:
        errors.append("OTel metrics observation timestamp is invalid")
    contract = _mapping(observation.get("contract"))
    if contract.get("local_static_contract_verified") is not True:
        errors.append("OTel metrics static contract was not verified")
    if not _valid_sha256(contract.get("contract_fingerprint")):
        errors.append("OTel metrics contract fingerprint is invalid")
    cluster = _mapping(observation.get("cluster"))
    namespace = _mapping(cluster.get("namespace"))
    if cluster.get("context") != CONTEXT or not cluster.get("uid"):
        errors.append("OTel metrics cluster identity does not match")
    if namespace.get("name") != NAMESPACE or not namespace.get("uid"):
        errors.append("OTel metrics Namespace identity does not match")
    errors.extend(_component_errors(_mapping(observation.get("components"))))

    scrapes = observation.get("scrapes")
    scrape_items = scrapes if isinstance(scrapes, list) else []
    if len(scrape_items) != REPEATED_OBSERVATIONS:
        errors.append("OTel repeated scrape count does not match")
    for sequence, scrape in enumerate(scrape_items, start=1):
        item = _mapping(scrape)
        if item.get("sequence") != sequence:
            errors.append("OTel scrape sequence does not match")
        errors.extend(_pipeline_summary_errors(item))
    separation = observation.get("scrape_separation_seconds")
    if not isinstance(separation, (int, float)) or separation < SCRAPE_INTERVAL_SECONDS:
        errors.append("OTel observations did not span a complete scrape interval")

    runtime = _mapping(observation.get("runtime_checks"))
    required_true = (
        "resources_absent_before_apply",
        "apply_completed",
        "runtime_resource_inventory_matches",
        "port_forward_stopped",
        "cleanup_command_completed",
        "ephemeral_resources_removed",
        "provider_identities_preserved",
    )
    for key in required_true:
        if runtime.get(key) is not True:
            errors.append(f"OTel runtime check did not pass: {key}")
    if _mapping(runtime.get("rollouts_completed")) != {
        name: True for name in EXPECTED_DEPLOYMENTS
    }:
        errors.append("OTel rollout completion inventory does not match")
    if runtime.get("runtime_resource_inventory") != EXPECTED_RUNTIME_RESOURCES:
        errors.append("OTel live resource inventory does not match")
    if runtime.get("remaining_resources") != []:
        errors.append("OTel ephemeral resources remain after verification")
    for key in (
        "kubernetes_credential_resources_requested",
        "persistent_volume_resources_requested",
        "rbac_resources_requested",
    ):
        if runtime.get(key) is not False:
            errors.append(f"OTel runtime may not request restricted resources: {key}")
    return errors


def build_otel_metrics_evidence(
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build fail-closed evidence for the local ephemeral OTel pipeline."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricOtelMetricsError(
            "verification time must be timezone-aware"
        )
    errors = _observation_errors(
        observation, now=current, max_age_seconds=max_age_seconds
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop_ephemeral_otel_metrics",
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "observation_fingerprint": recovery._canonical_sha256(observation),
        "checks": {
            "static_contract": "passed" if verified else "blocked",
            "component_identity": "passed" if verified else "blocked",
            "openmetadata_pipeline": "passed" if verified else "blocked",
            "gravitino_translation_pipeline": "passed" if verified else "blocked",
            "repeated_scrape": "passed" if verified else "blocked",
            "allowlist_projection": "passed" if verified else "blocked",
            "ephemeral_cleanup": "passed" if verified else "blocked",
            "provider_identity_preservation": "passed" if verified else "blocked",
            "production_boundaries": "passed",
        },
        "errors": errors,
        "metrics_scope": "local_ephemeral_otel_prometheus_export",
        "local_otel_metrics_pipeline_verified": verified,
        "local_repeated_scrape_verified": verified,
        "otel_pipeline_verified": False,
        "production_metrics_verified": False,
        "persistent_metrics_storage_verified": False,
        "alert_delivery_verified": False,
        "slo_verified": False,
        "metrics_tls_verified": False,
        "tenant_isolation_verified": False,
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
        "status": "local_otel_metrics_pipeline_verified" if verified else "blocked",
        "evidence_fingerprint": recovery._canonical_sha256(stable),
    }


def verify_evidence_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("OTel metrics evidence contains credential-bearing fields")
    if report.get("schema") != EVIDENCE_SCHEMA:
        errors.append("OTel metrics evidence schema does not match")
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "status", "evidence_fingerprint"}
    }
    if report.get("evidence_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("OTel metrics evidence fingerprint does not match")
    local_verified = report.get("local_otel_metrics_pipeline_verified") is True
    repeated_verified = report.get("local_repeated_scrape_verified") is True
    expected_status = "local_otel_metrics_pipeline_verified" if local_verified else "blocked"
    if report.get("status") != expected_status or repeated_verified != local_verified:
        errors.append("OTel metrics local claim status does not match")
    for claim in (
        "otel_pipeline_verified",
        "production_metrics_verified",
        "persistent_metrics_storage_verified",
        "alert_delivery_verified",
        "slo_verified",
        "metrics_tls_verified",
        "tenant_isolation_verified",
        "oidc_verified",
        "network_policy_enforcement_verified",
        "upgrade_verified",
        "writes_to_gda_enabled",
        "production_ready",
    ):
        if report.get(claim) is not False:
            errors.append(f"OTel metrics evidence may not claim {claim}")
    return errors


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricOtelMetricsError("JSON input must be an object")
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
            report = build_otel_metrics_contract_report()
            _write_report(report, None)
            return 0 if report["local_static_contract_verified"] else 1
        if args.command == "run":
            observation = collect_live_otel_metrics_pipeline(
                kubectl=args.kubectl, context=args.context
            )
            report = build_otel_metrics_evidence(observation)
            _write_report(report, args.output)
            return 0 if report["local_otel_metrics_pipeline_verified"] else 1
        report = _load_json_object(args.input)
        errors = verify_evidence_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        MetadataFabricOtelMetricsError,
        recovery.MetadataFabricRecoveryError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata OTel metrics: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
