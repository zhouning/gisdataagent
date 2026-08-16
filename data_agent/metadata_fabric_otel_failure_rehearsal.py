"""Rehearse bounded OTel scrape failure detection and recovery.

The command temporarily deploys the existing local Metadata Fabric metrics
pipeline, breaks only the Gravitino scrape endpoint in the Collector
ConfigMap, proves the isolated failure, restores the checked-in configuration,
and removes every temporary resource. It does not modify either metadata
provider or claim production monitoring, alerting, storage, TLS, or SLOs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import metadata_fabric_otel_metrics as pipeline
from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery


CONTRACT_SCHEMA = "gda.metadata_fabric_otel_failure_rehearsal_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_otel_failure_rehearsal_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_otel_failure_rehearsal_evidence.v1"
PROFILE_SCHEMA = "gda.metadata_fabric_otel_failure_rehearsal_profile.v1"
CONTEXT = pipeline.CONTEXT
NAMESPACE = pipeline.NAMESPACE

FAULT_JOB = "gravitino"
ORIGINAL_ENDPOINT = "metadata-json-exporter:7979"
FAULT_ENDPOINT = "metadata-json-exporter:1"
COLLECTOR_CONFIGMAP = "metadata-otel-collector-config"
COLLECTOR_DEPLOYMENT = pipeline.OTEL_DEPLOYMENT
STAGES = ("baseline", "fault", "recovery")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-otel-failure-rehearsal.local.yaml"
)
DEFAULT_WRAPPER = REPO_ROOT / "scripts/metadata-fabric-otel-failure-rehearsal.sh"
DEFAULT_CONFIGMAPS_PATH = pipeline.DEFAULT_MANIFEST_DIR / "configmaps.yaml"


class MetadataFabricOtelFailureRehearsalError(RuntimeError):
    """The local OTel scrape failure/recovery contract failed closed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    return pipeline._valid_sha256(value)


def _profile_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if (
        profile.get("schema") != PROFILE_SCHEMA
        or profile.get("environment") != "local_docker_desktop"
    ):
        errors.append("OTel failure rehearsal profile schema or environment does not match")
    if _mapping(profile.get("cluster")) != {
        "context": CONTEXT,
        "namespace": NAMESPACE,
    }:
        errors.append("OTel failure rehearsal cluster boundary does not match")
    if _mapping(profile.get("pipeline")) != {
        "base_contract": pipeline.CONTRACT_SCHEMA,
        "collector_deployment": COLLECTOR_DEPLOYMENT,
        "collector_configmap": COLLECTOR_CONFIGMAP,
        "scrape_job": FAULT_JOB,
    }:
        errors.append("OTel failure rehearsal pipeline profile does not match")
    if _mapping(profile.get("fault")) != {
        "type": "collector_scrape_endpoint_replacement",
        "original_endpoint": ORIGINAL_ENDPOINT,
        "replacement_endpoint": FAULT_ENDPOINT,
        "expected_openmetadata_up": 1,
        "expected_gravitino_up": 0,
    }:
        errors.append("OTel failure injection profile does not match")
    if _mapping(profile.get("recovery")) != {
        "source": "k8s/metadata-fabric-otel-metrics",
        "expected_openmetadata_up": 1,
        "expected_gravitino_up": 1,
    }:
        errors.append("OTel failure recovery profile does not match")

    expected_claims = {
        "local_otel_scrape_failure_recovery_verified",
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
    claims = _mapping(profile.get("claims"))
    if set(claims) != expected_claims:
        errors.append("OTel failure rehearsal claim inventory does not match")
    for claim in sorted(expected_claims):
        if claims.get(claim) is not False:
            errors.append(
                f"unverified OTel failure rehearsal claim must remain false: {claim}"
            )
    return errors


def _collector_configmap(path: Path) -> dict[str, Any]:
    documents = pipeline._load_yaml_documents(path)
    matches = [
        document
        for document in documents
        if document.get("kind") == "ConfigMap"
        and _mapping(document.get("metadata")).get("name") == COLLECTOR_CONFIGMAP
    ]
    if len(matches) != 1:
        raise MetadataFabricOtelFailureRehearsalError(
            "OTel Collector ConfigMap inventory does not match"
        )
    return matches[0]


def _embedded_collector_config(configmap: Mapping[str, Any]) -> dict[str, Any]:
    text = _mapping(configmap.get("data")).get("config.yaml")
    try:
        config = yaml.safe_load(str(text))
    except yaml.YAMLError as exc:
        raise MetadataFabricOtelFailureRehearsalError(
            "OTel Collector embedded configuration is invalid"
        ) from exc
    if not isinstance(config, dict):
        raise MetadataFabricOtelFailureRehearsalError(
            "OTel Collector embedded configuration is not an object"
        )
    return config


def _gravitino_address_relabel(config: Mapping[str, Any]) -> dict[str, Any]:
    receiver = _mapping(
        _mapping(config.get("receivers")).get("prometheus/provider_metrics")
    )
    scrape_configs = _mapping(receiver.get("config")).get("scrape_configs")
    jobs = [
        item
        for item in (scrape_configs if isinstance(scrape_configs, list) else [])
        if _mapping(item).get("job_name") == FAULT_JOB
    ]
    if len(jobs) != 1:
        raise MetadataFabricOtelFailureRehearsalError(
            "Gravitino scrape job inventory does not match"
        )
    relabel_configs = _mapping(jobs[0]).get("relabel_configs")
    addresses = [
        item
        for item in (relabel_configs if isinstance(relabel_configs, list) else [])
        if _mapping(item).get("target_label") == "__address__"
    ]
    if len(addresses) != 1 or not isinstance(addresses[0], dict):
        raise MetadataFabricOtelFailureRehearsalError(
            "Gravitino address relabel inventory does not match"
        )
    return addresses[0]


def build_faulted_collector_configmap(
    configmaps_path: Path | None = None,
) -> dict[str, Any]:
    """Return a structured ConfigMap with only the Gravitino endpoint faulted."""
    source = _collector_configmap((configmaps_path or DEFAULT_CONFIGMAPS_PATH).resolve())
    faulted = deepcopy(source)
    embedded = _embedded_collector_config(faulted)
    address = _gravitino_address_relabel(embedded)
    if address.get("replacement") != ORIGINAL_ENDPOINT:
        raise MetadataFabricOtelFailureRehearsalError(
            "Gravitino original scrape endpoint does not match"
        )
    address["replacement"] = FAULT_ENDPOINT
    faulted["data"]["config.yaml"] = yaml.safe_dump(embedded, sort_keys=False)
    metadata = faulted.setdefault("metadata", {})
    metadata["namespace"] = NAMESPACE
    metadata["labels"] = {
        "app.kubernetes.io/part-of": pipeline.PART_OF_LABEL,
        "gda.openai.com/environment": "local-observability-evidence",
    }
    return faulted


def _fault_config_errors(
    base: Mapping[str, Any], faulted: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if faulted.get("apiVersion") != "v1" or faulted.get("kind") != "ConfigMap":
        errors.append("faulted OTel resource is not a v1 ConfigMap")
    metadata = _mapping(faulted.get("metadata"))
    if (
        metadata.get("name") != COLLECTOR_CONFIGMAP
        or metadata.get("namespace") != NAMESPACE
        or _mapping(metadata.get("labels"))
        != {
            "app.kubernetes.io/part-of": pipeline.PART_OF_LABEL,
            "gda.openai.com/environment": "local-observability-evidence",
        }
    ):
        errors.append("faulted OTel ConfigMap metadata boundary does not match")
    try:
        base_config = _embedded_collector_config(base)
        fault_config = _embedded_collector_config(faulted)
        base_address = _gravitino_address_relabel(base_config)
        fault_address = _gravitino_address_relabel(fault_config)
        if base_address.get("replacement") != ORIGINAL_ENDPOINT:
            errors.append("base Gravitino scrape endpoint does not match")
        if fault_address.get("replacement") != FAULT_ENDPOINT:
            errors.append("faulted Gravitino scrape endpoint does not match")
        expected = deepcopy(base_config)
        _gravitino_address_relabel(expected)["replacement"] = FAULT_ENDPOINT
        if fault_config != expected:
            errors.append("fault injection changed more than the Gravitino endpoint")
    except MetadataFabricOtelFailureRehearsalError as exc:
        errors.append(str(exc))
    return errors


def _config_sha256(configmap: Mapping[str, Any]) -> str:
    text = _mapping(configmap.get("data")).get("config.yaml")
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def build_otel_failure_contract_report(
    profile_path: Path | None = None,
    wrapper_path: Path | None = None,
    configmaps_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the bounded failure injection and recovery contract."""
    profile_file = (profile_path or DEFAULT_PROFILE_PATH).resolve()
    wrapper = (wrapper_path or DEFAULT_WRAPPER).resolve()
    configmaps = (configmaps_path or DEFAULT_CONFIGMAPS_PATH).resolve()
    errors: list[str] = []
    try:
        profile = provider_metrics.repository._load_yaml_object(profile_file)
        errors.extend(_profile_errors(profile))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"OTel failure rehearsal profile is invalid: {type(exc).__name__}")

    base_contract = pipeline.build_otel_metrics_contract_report()
    if base_contract.get("local_static_contract_verified") is not True:
        errors.append("base OTel metrics contract is invalid")

    base_config_sha256: str | None = None
    fault_config_sha256: str | None = None
    try:
        base = _collector_configmap(configmaps)
        faulted = build_faulted_collector_configmap(configmaps)
        errors.extend(_fault_config_errors(base, faulted))
        base_config_sha256 = _config_sha256(base)
        fault_config_sha256 = _config_sha256(faulted)
        if base_config_sha256 == fault_config_sha256:
            errors.append("faulted OTel Collector configuration did not change")
    except (OSError, TypeError, yaml.YAMLError, MetadataFabricOtelFailureRehearsalError) as exc:
        errors.append(f"OTel failure injection contract is invalid: {type(exc).__name__}")

    try:
        wrapper_text = wrapper.read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_otel_failure_rehearsal"):
            if marker not in wrapper_text:
                errors.append(f"OTel failure rehearsal wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"OTel failure rehearsal wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in (Path(__file__).resolve(), profile_file, wrapper):
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
        "base_contract_schema": pipeline.CONTRACT_SCHEMA,
        "base_contract_fingerprint": base_contract.get("contract_fingerprint"),
        "collector_configmap": COLLECTOR_CONFIGMAP,
        "collector_deployment": COLLECTOR_DEPLOYMENT,
        "fault_job": FAULT_JOB,
        "original_endpoint": ORIGINAL_ENDPOINT,
        "fault_endpoint": FAULT_ENDPOINT,
        "base_config_sha256": base_config_sha256,
        "fault_config_sha256": fault_config_sha256,
        "runtime_resource_inventory": pipeline.EXPECTED_RUNTIME_RESOURCES,
        "local_static_contract_verified": not errors,
        "local_otel_scrape_failure_recovery_verified": False,
        "otel_pipeline_verified": False,
        "production_metrics_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


def _stage_summary_errors(summary: Mapping[str, Any], stage: str) -> list[str]:
    errors: list[str] = []
    if stage not in STAGES:
        return ["OTel failure rehearsal stage does not match"]
    if summary.get("stage") != stage or summary.get("sequence") != STAGES.index(stage) + 1:
        errors.append(f"OTel {stage} stage identity does not match")
    if stage in {"baseline", "recovery"}:
        errors.extend(pipeline._pipeline_summary_errors(summary))
        return errors

    if summary.get("format") != "prometheus_text_0.0.4":
        errors.append("OTel fault Prometheus format does not match")
    for key in ("metric_family_count", "sample_count"):
        if not isinstance(summary.get(key), int) or summary.get(key, 0) <= 0:
            errors.append(f"OTel fault {key} is empty")
    for key in (
        "metric_family_name_fingerprint",
        "metric_family_type_fingerprint",
        "label_name_fingerprint",
    ):
        if not _valid_sha256(summary.get(key)):
            errors.append(f"OTel fault {key} is invalid")
    if _mapping(summary.get("required_families")) != {
        "openmetadata": list(pipeline.OPENMETADATA_REQUIRED_FAMILIES),
        "gravitino": list(pipeline.GRAVITINO_REQUIRED_FAMILIES),
    }:
        errors.append("OTel fault required family inventory does not match")
    if _mapping(summary.get("missing_required_families")) != {
        "openmetadata": [],
        "gravitino": list(pipeline.GRAVITINO_REQUIRED_FAMILIES),
    }:
        errors.append("OTel fault metric isolation does not match")
    jobs = _mapping(summary.get("jobs"))
    openmetadata = _mapping(jobs.get("openmetadata"))
    gravitino = _mapping(jobs.get("gravitino"))
    if set(jobs) != {"openmetadata", "gravitino"}:
        errors.append("OTel fault scrape job inventory does not match")
    if openmetadata.get("up") != 1.0:
        errors.append("OTel fault stage disrupted OpenMetadata")
    openmetadata_samples = openmetadata.get("scrape_samples_scraped")
    if not isinstance(openmetadata_samples, (int, float)) or openmetadata_samples <= 0:
        errors.append("OTel fault OpenMetadata scrape has no samples")
    if gravitino.get("up") != 0.0:
        errors.append("OTel Gravitino fault was not detected")
    if gravitino.get("scrape_samples_scraped") != 0.0:
        errors.append("OTel fault Gravitino scrape unexpectedly returned samples")
    gravitino_values = _mapping(summary.get("gravitino_values"))
    if set(gravitino_values) != set(pipeline.GRAVITINO_REQUIRED_FAMILIES) or any(
        value is not None for value in gravitino_values.values()
    ):
        errors.append("OTel fault retained Gravitino allowlisted values")
    if summary.get("constant_labels_verified") is not True:
        errors.append("OTel fault constant/provider labels were not verified")
    if summary.get("raw_metrics_retained") is not False:
        errors.append("OTel fault evidence may not retain raw metrics")
    return errors


def _wait_for_stage_summary(
    local_port: int, *, stage: str, timeout_seconds: float = 90
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            summary = pipeline._pipeline_summary(
                pipeline._fetch_metrics(local_port),
                sequence=STAGES.index(stage) + 1,
                observed_at=datetime.now(UTC),
            )
            summary["stage"] = stage
            if not _stage_summary_errors(summary, stage):
                return summary
        except pipeline.MetadataFabricOtelMetricsError as exc:
            last_error = exc
        time.sleep(1)
    raise MetadataFabricOtelFailureRehearsalError(
        f"OTel {stage} stage did not reach the required state"
    ) from last_error


def _observe_stage(
    *,
    kubectl: str,
    context: str,
    stage: str,
    forwards_stopped: dict[str, bool],
) -> dict[str, Any]:
    forward = pipeline._OtelPortForward(kubectl=kubectl, context=context)
    try:
        forward.start()
        return _wait_for_stage_summary(forward.local_port, stage=stage)
    finally:
        forwards_stopped[stage] = forward.stop()


def _rollout_collector(
    runner: recovery._CommandRunner, *, label: str
) -> None:
    runner.kubectl_run(
        ["-n", NAMESPACE, "rollout", "restart", f"deployment/{COLLECTOR_DEPLOYMENT}"],
        timeout=60,
        label=f"restart OTel Collector for {label}",
    )
    runner.kubectl_run(
        [
            "-n",
            NAMESPACE,
            "rollout",
            "status",
            f"deployment/{COLLECTOR_DEPLOYMENT}",
            "--timeout=180s",
        ],
        timeout=210,
        label=f"wait for OTel Collector {label} rollout",
    )


def _collector_config_identity(runner: recovery._CommandRunner) -> dict[str, Any]:
    payload = runner.kubectl_json(
        ["-n", NAMESPACE, "get", "configmap", COLLECTOR_CONFIGMAP, "-o", "json"],
        label="read OTel Collector ConfigMap identity",
    )
    text = _mapping(payload.get("data")).get("config.yaml")
    return {
        "uid": _mapping(payload.get("metadata")).get("uid"),
        "config_sha256": hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
    }


def _apply_fault_config(
    runner: recovery._CommandRunner, faulted: Mapping[str, Any]
) -> None:
    with tempfile.TemporaryDirectory(prefix="gda-otel-fault-") as directory:
        path = Path(directory) / "collector-configmap.yaml"
        path.write_text(yaml.safe_dump(dict(faulted), sort_keys=False), encoding="utf-8")
        runner.kubectl_run(
            ["apply", "-f", str(path)],
            timeout=60,
            label="apply Gravitino OTel scrape fault",
        )


def collect_live_otel_failure_rehearsal(
    *, kubectl: str = "kubectl", context: str = CONTEXT
) -> dict[str, Any]:
    """Inject, detect, recover, and clean up one local OTel scrape failure."""
    if context != CONTEXT:
        raise MetadataFabricOtelFailureRehearsalError(
            "OTel failure rehearsal requires docker-desktop"
        )
    started = datetime.now(UTC)
    contract = build_otel_failure_contract_report()
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricOtelFailureRehearsalError(
            "OTel failure rehearsal static contract is invalid"
        )

    runner = recovery._CommandRunner(kubectl, context)
    cluster_uid, namespace, resources_before, providers_before = pipeline._preflight_snapshot(
        runner
    )
    if not cluster_uid or not namespace.get("uid"):
        raise MetadataFabricOtelFailureRehearsalError(
            "OTel failure rehearsal cluster identity is unavailable"
        )
    if resources_before:
        raise MetadataFabricOtelFailureRehearsalError(
            "pre-existing local OTel metrics resources must be removed first"
        )

    faulted = build_faulted_collector_configmap()
    apply_attempted = False
    apply_completed = False
    initial_rollouts = {name: False for name in pipeline.EXPECTED_DEPLOYMENTS}
    fault_config_applied = False
    fault_rollout_completed = False
    recovery_config_applied = False
    recovery_rollout_completed = False
    fallback_restore_completed = False
    forwards_stopped = {stage: False for stage in STAGES}
    cleanup_command_completed = False
    remaining_resources: list[str] = []
    providers_preserved = False
    runtime_inventory: list[str] = []
    components: dict[str, Any] = {}
    stages: dict[str, Any] = {}
    config_identities: dict[str, Any] = {}
    failure: Exception | None = None
    try:
        apply_attempted = True
        runner.kubectl_run(
            ["apply", "-k", str(pipeline.DEFAULT_MANIFEST_DIR)],
            timeout=180,
            label="apply local OTel metrics pipeline",
        )
        apply_completed = True
        for name in pipeline.EXPECTED_DEPLOYMENTS:
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
            initial_rollouts[name] = True
        runtime_inventory = pipeline._list_ephemeral_resources(runner)
        # The base helper validates both ConfigMaps against the M2c-2 contract.
        components["baseline"] = pipeline._component_identities(
            runner,
            _mapping(pipeline.build_otel_metrics_contract_report().get("config_hashes")),
        )
        config_identities["baseline"] = _collector_config_identity(runner)
        stages["baseline"] = _observe_stage(
            kubectl=kubectl,
            context=context,
            stage="baseline",
            forwards_stopped=forwards_stopped,
        )

        _apply_fault_config(runner, faulted)
        fault_config_applied = True
        config_identities["fault"] = _collector_config_identity(runner)
        _rollout_collector(runner, label="fault")
        fault_rollout_completed = True
        stages["fault"] = _observe_stage(
            kubectl=kubectl,
            context=context,
            stage="fault",
            forwards_stopped=forwards_stopped,
        )

        runner.kubectl_run(
            ["apply", "-k", str(pipeline.DEFAULT_MANIFEST_DIR)],
            timeout=180,
            label="restore local OTel metrics pipeline configuration",
        )
        recovery_config_applied = True
        _rollout_collector(runner, label="recovery")
        recovery_rollout_completed = True
        config_identities["recovery"] = _collector_config_identity(runner)
        components["recovery"] = pipeline._component_identities(
            runner,
            _mapping(pipeline.build_otel_metrics_contract_report().get("config_hashes")),
        )
        stages["recovery"] = _observe_stage(
            kubectl=kubectl,
            context=context,
            stage="recovery",
            forwards_stopped=forwards_stopped,
        )
    except Exception as exc:
        failure = exc
    finally:
        if fault_config_applied and not recovery_config_applied:
            try:
                runner.kubectl_run(
                    ["apply", "-k", str(pipeline.DEFAULT_MANIFEST_DIR)],
                    timeout=180,
                    label="restore OTel configuration after rehearsal failure",
                )
                fallback_restore_completed = True
            except Exception as exc:
                failure = failure or exc
        if apply_attempted:
            try:
                runner.kubectl_run(
                    [
                        "delete",
                        "--ignore-not-found=true",
                        "-k",
                        str(pipeline.DEFAULT_MANIFEST_DIR),
                    ],
                    timeout=180,
                    label="remove local OTel failure rehearsal pipeline",
                )
                cleanup_command_completed = True
                remaining_resources = pipeline._wait_for_ephemeral_cleanup(runner)
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
        if isinstance(failure, MetadataFabricOtelFailureRehearsalError):
            raise failure
        raise MetadataFabricOtelFailureRehearsalError(
            f"live OTel failure rehearsal failed: {failure}"
        ) from failure

    completed = datetime.now(UTC)
    baseline_config = _mapping(config_identities.get("baseline"))
    fault_config = _mapping(config_identities.get("fault"))
    recovery_config = _mapping(config_identities.get("recovery"))
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
        "stages": stages,
        "fault_injection": {
            "job": FAULT_JOB,
            "type": "collector_scrape_endpoint_replacement",
            "original_endpoint": ORIGINAL_ENDPOINT,
            "fault_endpoint": FAULT_ENDPOINT,
            "baseline_config_sha256": baseline_config.get("config_sha256"),
            "fault_config_sha256": fault_config.get("config_sha256"),
            "recovery_config_sha256": recovery_config.get("config_sha256"),
            "expected_fault_config_sha256": contract.get("fault_config_sha256"),
            "configmap_uid_preserved": bool(baseline_config.get("uid"))
            and baseline_config.get("uid") == fault_config.get("uid")
            and fault_config.get("uid") == recovery_config.get("uid"),
        },
        "runtime_checks": {
            "resources_absent_before_apply": resources_before == [],
            "apply_completed": apply_completed,
            "initial_rollouts_completed": initial_rollouts,
            "fault_config_applied": fault_config_applied,
            "fault_rollout_completed": fault_rollout_completed,
            "recovery_config_applied": recovery_config_applied,
            "recovery_rollout_completed": recovery_rollout_completed,
            "fallback_restore_completed": fallback_restore_completed,
            "port_forwards_stopped": forwards_stopped,
            "runtime_resource_inventory": runtime_inventory,
            "runtime_resource_inventory_matches": (
                runtime_inventory == pipeline.EXPECTED_RUNTIME_RESOURCES
            ),
            "cleanup_command_completed": cleanup_command_completed,
            "ephemeral_resources_removed": remaining_resources == [],
            "remaining_resources": remaining_resources,
            "provider_identities_preserved": providers_preserved,
            "kubernetes_credential_resources_requested": False,
            "persistent_volume_resources_requested": False,
            "rbac_resources_requested": False,
        },
    }


def _component_pair_errors(components: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(components) != {"baseline", "recovery"}:
        errors.append("OTel failure rehearsal component stage inventory does not match")
        return errors
    errors.extend(pipeline._component_errors(_mapping(components.get("baseline"))))
    errors.extend(pipeline._component_errors(_mapping(components.get("recovery"))))
    baseline = _mapping(components.get("baseline"))
    recovered = _mapping(components.get("recovery"))
    for kind in ("deployments", "services", "configmaps"):
        before = _mapping(baseline.get(kind))
        after = _mapping(recovered.get(kind))
        if set(before) != set(after) or any(
            _mapping(before.get(name)).get("uid")
            != _mapping(after.get(name)).get("uid")
            for name in before
        ):
            errors.append(f"OTel {kind} identities changed during failure rehearsal")
    return errors


def _observation_errors(
    observation: Mapping[str, Any], *, now: datetime, max_age_seconds: float
) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(observation):
        errors.append("OTel failure rehearsal observation contains credential-bearing fields")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("OTel failure rehearsal observation schema does not match")
    try:
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
        if age < -30 or age > max_age_seconds:
            errors.append("OTel failure rehearsal observation is outside the freshness window")
    except ValueError:
        errors.append("OTel failure rehearsal observation timestamp is invalid")

    contract = _mapping(observation.get("contract"))
    if contract.get("local_static_contract_verified") is not True:
        errors.append("OTel failure rehearsal static contract was not verified")
    if not _valid_sha256(contract.get("contract_fingerprint")):
        errors.append("OTel failure rehearsal contract fingerprint is invalid")
    cluster = _mapping(observation.get("cluster"))
    namespace = _mapping(cluster.get("namespace"))
    if cluster.get("context") != CONTEXT or not cluster.get("uid"):
        errors.append("OTel failure rehearsal cluster identity does not match")
    if namespace.get("name") != NAMESPACE or not namespace.get("uid"):
        errors.append("OTel failure rehearsal Namespace identity does not match")
    errors.extend(_component_pair_errors(_mapping(observation.get("components"))))

    stages = _mapping(observation.get("stages"))
    if set(stages) != set(STAGES):
        errors.append("OTel failure rehearsal stage inventory does not match")
    for stage in STAGES:
        errors.extend(_stage_summary_errors(_mapping(stages.get(stage)), stage))

    current_contract = build_otel_failure_contract_report()
    if current_contract.get("local_static_contract_verified") is not True:
        errors.append("current OTel failure rehearsal contract is invalid")
    if contract.get("contract_fingerprint") != current_contract.get(
        "contract_fingerprint"
    ):
        errors.append("OTel failure rehearsal contract fingerprint is stale")
    injection = _mapping(observation.get("fault_injection"))
    if (
        injection.get("job") != FAULT_JOB
        or injection.get("type") != "collector_scrape_endpoint_replacement"
        or injection.get("original_endpoint") != ORIGINAL_ENDPOINT
        or injection.get("fault_endpoint") != FAULT_ENDPOINT
        or injection.get("baseline_config_sha256")
        != current_contract.get("base_config_sha256")
        or injection.get("fault_config_sha256")
        != current_contract.get("fault_config_sha256")
        or injection.get("recovery_config_sha256")
        != current_contract.get("base_config_sha256")
        or injection.get("expected_fault_config_sha256")
        != current_contract.get("fault_config_sha256")
        or injection.get("configmap_uid_preserved") is not True
    ):
        errors.append("OTel failure injection and recovery configuration does not match")

    runtime = _mapping(observation.get("runtime_checks"))
    for key in (
        "resources_absent_before_apply",
        "apply_completed",
        "fault_config_applied",
        "fault_rollout_completed",
        "recovery_config_applied",
        "recovery_rollout_completed",
        "runtime_resource_inventory_matches",
        "cleanup_command_completed",
        "ephemeral_resources_removed",
        "provider_identities_preserved",
    ):
        if runtime.get(key) is not True:
            errors.append(f"OTel failure rehearsal runtime check did not pass: {key}")
    if _mapping(runtime.get("initial_rollouts_completed")) != {
        name: True for name in pipeline.EXPECTED_DEPLOYMENTS
    }:
        errors.append("OTel failure rehearsal initial rollout inventory does not match")
    if _mapping(runtime.get("port_forwards_stopped")) != {
        stage: True for stage in STAGES
    }:
        errors.append("OTel failure rehearsal port-forward cleanup did not pass")
    if runtime.get("runtime_resource_inventory") != pipeline.EXPECTED_RUNTIME_RESOURCES:
        errors.append("OTel failure rehearsal live resource inventory does not match")
    if runtime.get("remaining_resources") != []:
        errors.append("OTel failure rehearsal ephemeral resources remain")
    for key in (
        "kubernetes_credential_resources_requested",
        "persistent_volume_resources_requested",
        "rbac_resources_requested",
    ):
        if runtime.get(key) is not False:
            errors.append(
                f"OTel failure rehearsal may not request restricted resources: {key}"
            )
    return errors


def build_otel_failure_evidence(
    observation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = 3600,
) -> dict[str, Any]:
    """Build fail-closed evidence for local scrape failure and recovery."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise MetadataFabricOtelFailureRehearsalError(
            "verification time must be timezone-aware"
        )
    errors = _observation_errors(
        observation, now=current, max_age_seconds=max_age_seconds
    )
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop_ephemeral_otel_failure_rehearsal",
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "observation_fingerprint": recovery._canonical_sha256(observation),
        "checks": {
            "static_contract": "passed" if verified else "blocked",
            "baseline_scrape": "passed" if verified else "blocked",
            "isolated_fault_detection": "passed" if verified else "blocked",
            "configuration_recovery": "passed" if verified else "blocked",
            "recovered_scrape": "passed" if verified else "blocked",
            "ephemeral_cleanup": "passed" if verified else "blocked",
            "provider_identity_preservation": "passed" if verified else "blocked",
            "production_boundaries": "passed",
        },
        "errors": errors,
        "metrics_scope": "local_ephemeral_otel_scrape_failure_recovery",
        "local_otel_scrape_failure_recovery_verified": verified,
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
        "status": (
            "local_otel_scrape_failure_recovery_verified" if verified else "blocked"
        ),
        "evidence_fingerprint": recovery._canonical_sha256(stable),
    }


def verify_evidence_integrity(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if recovery._sensitive_paths(report):
        errors.append("OTel failure rehearsal evidence contains credential-bearing fields")
    if report.get("schema") != EVIDENCE_SCHEMA:
        errors.append("OTel failure rehearsal evidence schema does not match")
    stable = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "status", "evidence_fingerprint"}
    }
    if report.get("evidence_fingerprint") != recovery._canonical_sha256(stable):
        errors.append("OTel failure rehearsal evidence fingerprint does not match")
    verified = report.get("local_otel_scrape_failure_recovery_verified") is True
    expected_status = (
        "local_otel_scrape_failure_recovery_verified" if verified else "blocked"
    )
    if report.get("status") != expected_status:
        errors.append("OTel failure rehearsal local claim status does not match")
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
            errors.append(f"OTel failure rehearsal evidence may not claim {claim}")
    return errors


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricOtelFailureRehearsalError("JSON input must be an object")
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
            report = build_otel_failure_contract_report()
            _write_report(report, None)
            return 0 if report["local_static_contract_verified"] else 1
        if args.command == "run":
            observation = collect_live_otel_failure_rehearsal(
                kubectl=args.kubectl, context=args.context
            )
            report = build_otel_failure_evidence(observation)
            _write_report(report, args.output)
            return 0 if report["local_otel_scrape_failure_recovery_verified"] else 1
        report = _load_json_object(args.input)
        errors = verify_evidence_integrity(report)
        _write_report({"verified": not errors, "errors": errors}, None)
        return 0 if not errors else 1
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
        MetadataFabricOtelFailureRehearsalError,
        pipeline.MetadataFabricOtelMetricsError,
        recovery.MetadataFabricRecoveryError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata OTel failure rehearsal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
