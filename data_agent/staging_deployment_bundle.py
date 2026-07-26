"""Materialize a fail-closed, release-bound staging Kubernetes bundle.

This is a pre-deployment boundary, not deployment evidence. It binds a
validated candidate, expected live platform snapshot, and immutable registry
image into a Secret-free manifest. Registry provenance and live cluster state
must still be verified by protected authorities.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from .staging_candidate_evidence import CANDIDATE_SCHEMA

BUNDLE_SCHEMA = "gda.staging_deployment_bundle.v1"
PLATFORM_TRUTH_SCHEMA = "gda.platform_truth.v1"
SOURCE_REVISION_ANNOTATION = "org.opencontainers.image.revision"
CANDIDATE_FINGERPRINT_ANNOTATION = (
    "gisdataagent.io/candidate-evidence-fingerprint"
)
ENVIRONMENT_ANNOTATION = "gisdataagent.io/environment"
PLATFORM_FINGERPRINT_ANNOTATION = "gisdataagent.io/platform-fingerprint"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMMUTABLE_IMAGE_PATTERN = re.compile(
    r"^(?:[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/)?"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"@sha256:[0-9a-f]{64}$"
)
SENSITIVE_CONFIG_PATTERN = re.compile(
    r"(?:PASSWORD|SECRET|TOKEN|API_KEY|CREDENTIAL|DATABASE_URL)"
)
CANDIDATE_STABLE_FIELDS = (
    "schema",
    "source_revision",
    "image_id",
    "schema_fingerprint",
    "config_fingerprint",
    "runtime_fingerprint",
    "tests",
    "candidate_validated",
    "errors",
)
RELEASE_WORKLOADS = (
    ("Deployment", "gis-agent-app"),
    ("Deployment", "gis-agent-outbox-worker"),
    ("Deployment", "gis-agent-dolphinscheduler-command-worker"),
    ("Job", "gis-agent-migrate"),
)
IMAGE_CONSUMERS = (
    ("Deployment", "gis-agent-app", "containers", "app"),
    (
        "Deployment",
        "gis-agent-app",
        "initContainers",
        "wait-for-migrate",
    ),
    ("Deployment", "gis-agent-outbox-worker", "containers", "worker"),
    (
        "Deployment",
        "gis-agent-outbox-worker",
        "initContainers",
        "wait-for-migrate",
    ),
    (
        "Deployment",
        "gis-agent-dolphinscheduler-command-worker",
        "containers",
        "worker",
    ),
    (
        "Deployment",
        "gis-agent-dolphinscheduler-command-worker",
        "initContainers",
        "prepare-provider-token",
    ),
    ("Job", "gis-agent-migrate", "containers", "migrate"),
)
REQUIRED_LIVE_EVIDENCE = (
    "registry provenance attestation for the declared image digest",
    "protected staging cluster and namespace identity",
    "live schema/config/runtime and rollout observation",
    "live golden-slice evidence",
)


class StagingDeploymentBundleError(RuntimeError):
    """A staging bundle input could not be parsed safely."""


def _canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingDeploymentBundleError("JSON input must be an object")
    return value


def _load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    values = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    documents = [value for value in values if isinstance(value, dict)]
    if not documents:
        raise StagingDeploymentBundleError("template manifest has no resources")
    return documents


def _resource(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    return next(
        (
            document
            for document in documents
            if document.get("kind") == kind
            and ((document.get("metadata") or {}).get("name")) == name
        ),
        None,
    )


def _named(items: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("name") == name
        ),
        None,
    )


def _pod_template(resource: Mapping[str, Any]) -> dict[str, Any]:
    spec = resource.get("spec")
    if not isinstance(spec, dict):
        return {}
    template = spec.get("template")
    return template if isinstance(template, dict) else {}


def _pod_spec(resource: Mapping[str, Any]) -> dict[str, Any]:
    template = _pod_template(resource)
    pod = template.get("spec")
    return pod if isinstance(pod, dict) else {}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def _candidate_errors(candidate: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        errors.append("candidate schema is unsupported")
    source_revision = candidate.get("source_revision")
    if not isinstance(source_revision, str) or not SOURCE_REVISION_PATTERN.fullmatch(
        source_revision
    ):
        errors.append("candidate source revision must be a full lowercase Git SHA-1")
    image_id = candidate.get("image_id")
    if not isinstance(image_id, str) or not IMAGE_ID_PATTERN.fullmatch(image_id):
        errors.append("candidate local image ID must be sha256")
    for field in (
        "schema_fingerprint",
        "config_fingerprint",
        "runtime_fingerprint",
    ):
        if not _is_sha256(candidate.get(field)):
            errors.append(f"candidate {field} must be sha256")
    if candidate.get("candidate_validated") is not True:
        errors.append("candidate must be validated")
    if candidate.get("status") != "candidate_validated":
        errors.append("candidate status must be candidate_validated")
    if candidate.get("errors") != []:
        errors.append("candidate must not contain validation errors")
    tests = candidate.get("tests")
    if (
        not isinstance(tests, Mapping)
        or not isinstance(tests.get("tests"), int)
        or isinstance(tests.get("tests"), bool)
        or tests.get("tests", 0) <= 0
        or tests.get("failures") != 0
        or tests.get("errors") != 0
    ):
        errors.append("candidate tests must have zero failures and errors")
    stable = {field: candidate.get(field) for field in CANDIDATE_STABLE_FIELDS}
    if candidate.get("evidence_fingerprint") != _canonical_sha256(stable):
        errors.append("candidate evidence fingerprint does not match its content")
    return errors


def _platform_errors(
    platform: Mapping[str, Any], candidate: Mapping[str, Any]
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    if platform.get("schema") != PLATFORM_TRUTH_SCHEMA:
        errors.append("expected platform snapshot schema is unsupported")
    config = platform.get("config")
    runtime = platform.get("runtime")
    if not isinstance(config, Mapping):
        config = {}
        errors.append("expected platform config snapshot is missing")
    if not isinstance(runtime, Mapping):
        runtime = {}
        errors.append("expected platform runtime snapshot is missing")
    if config.get("profile") != "staging" or config.get("strict") is not True:
        errors.append("expected platform config must be strict staging")
    if config.get("valid") is not True or config.get("startup_allowed") is not True:
        errors.append("expected platform config must be valid and startable")
    config_fingerprint = config.get("config_fingerprint")
    runtime_fingerprint = runtime.get("inventory_fingerprint")
    if not _is_sha256(config_fingerprint):
        errors.append("expected config fingerprint must be sha256")
    if runtime.get("status") != "valid" or runtime.get("errors"):
        errors.append("expected runtime inventory must be valid")
    if runtime.get("matches_primitive_baseline") is not True:
        errors.append("expected runtime primitives must match the reviewed baseline")
    if runtime_fingerprint != candidate.get("runtime_fingerprint"):
        errors.append("expected runtime fingerprint must match the candidate")
    if not _is_sha256(runtime_fingerprint):
        errors.append("expected runtime fingerprint must be sha256")
    fingerprint = (
        _canonical_sha256(
            {"config": config_fingerprint, "runtime": runtime_fingerprint}
        )
        if _is_sha256(config_fingerprint) and _is_sha256(runtime_fingerprint)
        else None
    )
    if platform.get("platform_fingerprint") != fingerprint:
        errors.append("expected platform fingerprint does not match config/runtime")
    return errors, fingerprint


def _set_release_annotations(
    resource: dict[str, Any], annotations: Mapping[str, str]
) -> None:
    template = _pod_template(resource)
    metadata = template.setdefault("metadata", {})
    current = metadata.setdefault("annotations", {})
    current.update(annotations)


def _replace_release_images(
    documents: list[dict[str, Any]], image: str, errors: list[str]
) -> None:
    for kind, resource_name, section, container_name in IMAGE_CONSUMERS:
        resource = _resource(documents, kind, resource_name)
        if resource is None:
            errors.append(f"template is missing {kind}/{resource_name}")
            continue
        container = _named(_pod_spec(resource).get(section), container_name)
        if container is None:
            errors.append(
                f"template is missing {kind}/{resource_name} {container_name}"
            )
            continue
        container["image"] = image


def _validate_materialized_bundle(
    documents: list[dict[str, Any]],
    *,
    annotations: Mapping[str, str],
    image: str,
    errors: list[str],
) -> None:
    if any(document.get("kind") == "Secret" for document in documents):
        errors.append("staging bundle must not contain Secret resources")
    config = _resource(documents, "ConfigMap", "gis-agent-config")
    config_data = (config or {}).get("data")
    if not isinstance(config_data, Mapping):
        errors.append("staging ConfigMap is missing")
    else:
        if config_data.get("GDA_DEPLOYMENT_PROFILE") != "staging":
            errors.append("staging ConfigMap profile must be staging")
        if str(config_data.get("GDA_CONFIG_STRICT")).lower() != "true":
            errors.append("staging ConfigMap strict mode must be true")
        sensitive_keys = sorted(
            str(key)
            for key in config_data
            if SENSITIVE_CONFIG_PATTERN.search(str(key))
        )
        if sensitive_keys:
            errors.append(
                "staging ConfigMap must not contain sensitive keys: "
                + ", ".join(sensitive_keys)
            )
        model_endpoint = config_data.get("OLLAMA_API_BASE")
        try:
            endpoint_parts = (
                urlsplit(model_endpoint)
                if isinstance(model_endpoint, str)
                else None
            )
        except ValueError:
            endpoint_parts = None
        endpoint_host = (endpoint_parts.hostname or "") if endpoint_parts else ""
        if (
            endpoint_parts is None
            or endpoint_parts.scheme != "https"
            or not endpoint_host
            or endpoint_host in {"localhost", "ollama"}
            or endpoint_host.endswith((".local", ".invalid"))
        ):
            errors.append(
                "staging ConfigMap must use a non-local HTTPS model endpoint"
            )

    for kind, name in RELEASE_WORKLOADS:
        resource = _resource(documents, kind, name)
        if resource is None:
            continue
        if (resource.get("metadata") or {}).get("namespace") != "gis-agent":
            errors.append(f"{kind}/{name} must be in the gis-agent namespace")
        template_annotations = (
            (_pod_template(resource).get("metadata") or {}).get("annotations")
            or {}
        )
        for key, expected in annotations.items():
            if template_annotations.get(key) != expected:
                errors.append(f"{kind}/{name} release annotation {key} drifted")
        if _pod_spec(resource).get("automountServiceAccountToken") is not False:
            errors.append(f"{kind}/{name} must disable service account token mounting")

    for kind, resource_name, section, container_name in IMAGE_CONSUMERS:
        resource = _resource(documents, kind, resource_name)
        if resource is None:
            continue
        container = _named(_pod_spec(resource).get(section), container_name)
        if container is not None and container.get("image") != image:
            errors.append(
                f"{kind}/{resource_name} {container_name} image is not release-bound"
            )

    app = _resource(documents, "Deployment", "gis-agent-app")
    if app is not None and (app.get("spec") or {}).get("replicas") != 1:
        errors.append("staging app Deployment must have exactly one replica")
    hpa = _resource(documents, "HorizontalPodAutoscaler", "gis-agent-app-hpa")
    hpa_spec = (hpa or {}).get("spec") or {}
    if hpa is not None and (
        hpa_spec.get("minReplicas") != 1 or hpa_spec.get("maxReplicas") != 1
    ):
        errors.append("staging app HPA must remain fixed at one replica")

    expected_wait_command = [
        "python",
        "-m",
        "data_agent.migration_runner",
        "status",
    ]
    for deployment_name in ("gis-agent-app", "gis-agent-outbox-worker"):
        deployment = _resource(documents, "Deployment", deployment_name)
        waiter = (
            _named(_pod_spec(deployment).get("initContainers"), "wait-for-migrate")
            if deployment is not None
            else None
        )
        if waiter is not None and waiter.get("command") != expected_wait_command:
            errors.append(
                f"Deployment/{deployment_name} must read schema readiness from the ledger"
            )

    for document in documents:
        pod = _pod_spec(document)
        volumes = pod.get("volumes") if isinstance(pod, Mapping) else None
        if isinstance(volumes, list) and any(
            isinstance(volume, Mapping) and "hostPath" in volume
            for volume in volumes
        ):
            metadata = document.get("metadata") or {}
            errors.append(
                f"{document.get('kind')}/{metadata.get('name')} must not use hostPath"
            )
        for section in ("initContainers", "containers"):
            containers = pod.get(section) if isinstance(pod, Mapping) else None
            if not isinstance(containers, list):
                continue
            for container in containers:
                if not isinstance(container, Mapping):
                    continue
                container_image = container.get("image")
                if not isinstance(
                    container_image, str
                ) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(container_image):
                    errors.append(
                        f"{document.get('kind')}/{(document.get('metadata') or {}).get('name')} "
                        f"container {container.get('name')} must use an immutable image digest"
                    )
                for variable in container.get("env") or []:
                    if not isinstance(variable, Mapping):
                        continue
                    key = str(variable.get("name") or "")
                    value = variable.get("value")
                    if (
                        value is not None
                        and value != ""
                        and SENSITIVE_CONFIG_PATTERN.search(key)
                        and not key.endswith("_FILE")
                    ):
                        errors.append(
                            f"{document.get('kind')}/{(document.get('metadata') or {}).get('name')} "
                            f"must not inline sensitive environment variable {key}"
                        )


def build_staging_bundle(
    template_documents: list[dict[str, Any]],
    candidate: Mapping[str, Any],
    platform_snapshot: Mapping[str, Any],
    *,
    image: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return a Secret-free release manifest and non-deployment preflight report."""
    documents = [
        copy.deepcopy(document)
        for document in template_documents
        if document.get("kind") != "Secret"
    ]
    removed_secret_names = sorted(
        str((document.get("metadata") or {}).get("name") or "<unnamed>")
        for document in template_documents
        if document.get("kind") == "Secret"
    )
    errors = _candidate_errors(candidate)
    platform_validation_errors, platform_fingerprint = _platform_errors(
        platform_snapshot, candidate
    )
    errors.extend(platform_validation_errors)
    if not IMMUTABLE_IMAGE_PATTERN.fullmatch(image):
        errors.append("release image must use an immutable registry digest")

    annotations = {
        SOURCE_REVISION_ANNOTATION: str(candidate.get("source_revision") or ""),
        CANDIDATE_FINGERPRINT_ANNOTATION: str(
            candidate.get("evidence_fingerprint") or ""
        ),
        ENVIRONMENT_ANNOTATION: "staging",
        PLATFORM_FINGERPRINT_ANNOTATION: str(platform_fingerprint or ""),
    }
    for kind, name in RELEASE_WORKLOADS:
        resource = _resource(documents, kind, name)
        if resource is None:
            errors.append(f"template is missing {kind}/{name}")
            continue
        _set_release_annotations(resource, annotations)
        _pod_spec(resource)["automountServiceAccountToken"] = False
    _replace_release_images(documents, image, errors)
    _validate_materialized_bundle(
        documents,
        annotations=annotations,
        image=image,
        errors=errors,
    )

    ready = not errors
    stable = {
        "schema": BUNDLE_SCHEMA,
        "source_revision": candidate.get("source_revision"),
        "candidate_evidence_fingerprint": candidate.get("evidence_fingerprint"),
        "platform_fingerprint": platform_fingerprint,
        "image": image,
        "manifest_fingerprint": _canonical_sha256(documents) if ready else None,
        "removed_secret_names": removed_secret_names,
        "errors": errors,
        "bundle_ready": ready,
    }
    report = {
        **stable,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "ready_for_staging_apply" if ready else "blocked",
        "registry_digest_declared": bool(
            IMMUTABLE_IMAGE_PATTERN.fullmatch(image)
        ),
        "registry_digest_verified": False,
        "staging_deployed": False,
        "live_cluster_verified": False,
        "production_promotion_allowed": False,
        "required_live_evidence": list(REQUIRED_LIVE_EVIDENCE),
        "evidence_fingerprint": _canonical_sha256(stable),
    }
    return documents, report


def _write_report(report: Mapping[str, Any], path: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _write_manifest(documents: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump_all(documents, explicit_start=True, sort_keys=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--template-manifest", type=Path, required=True)
    build.add_argument("--candidate-evidence", type=Path, required=True)
    build.add_argument("--platform-snapshot", type=Path, required=True)
    build.add_argument("--image", required=True)
    build.add_argument("--manifest-output", type=Path, required=True)
    build.add_argument("--report-output", type=Path)
    args = parser.parse_args(argv)

    try:
        documents, report = build_staging_bundle(
            _load_yaml_documents(args.template_manifest),
            _load_json_object(args.candidate_evidence),
            _load_json_object(args.platform_snapshot),
            image=args.image,
        )
    except (OSError, json.JSONDecodeError, yaml.YAMLError, StagingDeploymentBundleError) as exc:
        report = {
            "schema": BUNDLE_SCHEMA,
            "status": "error",
            "bundle_ready": False,
            "staging_deployed": False,
            "live_cluster_verified": False,
            "production_promotion_allowed": False,
            "error": f"staging bundle input is invalid: {type(exc).__name__}",
        }
        _write_report(report, args.report_output)
        return 2

    if report["bundle_ready"]:
        _write_manifest(documents, args.manifest_output)
    _write_report(report, args.report_output)
    return 0 if report["bundle_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
