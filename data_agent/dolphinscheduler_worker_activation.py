"""Validate redacted evidence before activating the managed worker in staging."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from .dolphinscheduler_worker_deployment import (
    CONFIG_NAME,
    DEPLOYMENT_NAME,
    REQUIRED_CONFIG_ENV,
    SECRET_NAME,
    build_deployment_report,
)

ACTIVATION_SCHEMA = "gda.dolphinscheduler_worker_activation.v1"
SECRET_ATTESTATION_SCHEMA = (
    "gda.dolphinscheduler_worker_secret_attestation.v1"
)
NAMESPACE = "gis-agent"
REQUIRED_CONFIG_KEYS = tuple(REQUIRED_CONFIG_ENV.values())
REQUIRED_SECRET_KEYS = ("access-token", "database-url")
ATTESTATION_FIELDS = {
    "schema",
    "environment",
    "namespace",
    "secret_name",
    "keys",
    "resource_uid",
    "resource_version",
    "observed_at",
}
IMMUTABLE_IMAGE_PATTERN = re.compile(
    r"^(?:[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/)?"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"@sha256:[0-9a-f]{64}$"
)
RESOURCE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
RESOURCE_UID_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
)
SUBJECT_PATTERN = re.compile(r"^workload:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$")
TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PLACEHOLDER_VALUES = {"changeme", "placeholder", "replace-me", "todo"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    documents = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    return [document for document in documents if isinstance(document, dict)]


def _resource(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any] | None:
    for document in documents:
        if document.get("kind") != kind:
            continue
        if ((document.get("metadata") or {}).get("name")) == name:
            return document
    return None


def _named(items: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON document must be an object")
    return payload


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp


def _validate_image_contract(
    deployment: dict[str, Any] | None,
    errors: list[str],
) -> str | None:
    if deployment is None:
        return None
    pod = (((deployment.get("spec") or {}).get("template") or {}).get("spec") or {})
    worker = _named(pod.get("containers"), "worker")
    token_init = _named(pod.get("initContainers"), "prepare-provider-token")
    worker_image = (worker or {}).get("image")
    init_image = (token_init or {}).get("image")
    for container_name, image in (
        ("worker", worker_image),
        ("prepare-provider-token", init_image),
    ):
        if not isinstance(image, str) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(image):
            errors.append(
                f"{container_name} image must use an immutable sha256 digest"
            )
    if worker_image != init_image:
        errors.append("worker and token init containers must use the same image digest")
    if isinstance(worker_image, str) and IMMUTABLE_IMAGE_PATTERN.fullmatch(worker_image):
        return worker_image
    return None


def _validate_config_map(
    config_map: dict[str, Any] | None,
    errors: list[str],
) -> tuple[str | None, str | None, str | None]:
    if config_map is None:
        errors.append("staging ConfigMap snapshot is missing")
        return None, None, None
    if config_map.get("apiVersion") != "v1":
        errors.append("staging ConfigMap snapshot must use apiVersion v1")
    metadata = config_map.get("metadata") or {}
    if metadata.get("namespace") != NAMESPACE:
        errors.append(f"staging ConfigMap must belong to namespace {NAMESPACE}")
    resource_uid = metadata.get("uid")
    if not isinstance(resource_uid, str) or not RESOURCE_UID_PATTERN.fullmatch(
        resource_uid
    ):
        errors.append("staging ConfigMap uid is invalid")
        resource_uid = None
    resource_version = metadata.get("resourceVersion")
    if not isinstance(resource_version, str) or not RESOURCE_VERSION_PATTERN.fullmatch(
        resource_version
    ):
        errors.append("staging ConfigMap resourceVersion is invalid")
        resource_version = None
    data = config_map.get("data")
    if not isinstance(data, dict):
        errors.append("staging ConfigMap data must be an object")
        return resource_uid, resource_version, None
    values: dict[str, str] = {}
    for key in REQUIRED_CONFIG_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"staging ConfigMap must define non-empty {key}")
            continue
        if value != value.strip() or value.casefold() in PLACEHOLDER_VALUES:
            errors.append(f"staging ConfigMap contains invalid value for {key}")
            continue
        values[key] = value

    base_url = values.get("base-url")
    if base_url:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.hostname.casefold() in {"0.0.0.0", "::1", "localhost"}
            or parsed.hostname.startswith("127.")
        ):
            errors.append(
                "staging DolphinScheduler base-url must be credential-free HTTPS"
            )

    project_code = values.get("project-code")
    if project_code:
        try:
            valid_project_code = int(project_code) > 0
        except ValueError:
            valid_project_code = False
        if not valid_project_code:
            errors.append("staging DolphinScheduler project-code must be positive")

    workload = values.get("workload-subject")
    evaluator = values.get("policy-evaluator-subject")
    for key, subject in (
        ("workload-subject", workload),
        ("policy-evaluator-subject", evaluator),
    ):
        if subject and not SUBJECT_PATTERN.fullmatch(subject):
            errors.append(f"staging ConfigMap {key} must be a workload subject")
    if workload and evaluator and workload == evaluator:
        errors.append("worker and policy evaluator subjects must be distinct")

    command_tenant = values.get("command-tenant-id")
    if command_tenant and not TENANT_PATTERN.fullmatch(command_tenant):
        errors.append("staging ConfigMap command-tenant-id is invalid")

    if len(values) != len(REQUIRED_CONFIG_KEYS):
        return resource_uid, resource_version, None
    fingerprint = _canonical_sha256(
        {key: values[key] for key in REQUIRED_CONFIG_KEYS}
    )
    return resource_uid, resource_version, fingerprint


def _validate_secret_attestation(
    attestation: dict[str, Any],
    *,
    environment: str,
    max_age_seconds: float,
    now: datetime,
    errors: list[str],
) -> tuple[str | None, str | None, str | None]:
    fields = set(attestation)
    if fields != ATTESTATION_FIELDS:
        errors.append(
            "secret attestation fields must be exact and must not contain secret values"
        )
    if attestation.get("schema") != SECRET_ATTESTATION_SCHEMA:
        errors.append("secret attestation schema is unsupported")
    if attestation.get("environment") != environment:
        errors.append("secret attestation environment does not match activation")
    if attestation.get("namespace") != NAMESPACE:
        errors.append(f"secret attestation namespace must be {NAMESPACE}")
    if attestation.get("secret_name") != SECRET_NAME:
        errors.append("secret attestation must reference the dedicated worker Secret")
    keys = attestation.get("keys")
    if keys != list(REQUIRED_SECRET_KEYS):
        errors.append("secret attestation must list only the required canonical keys")
    resource_uid = attestation.get("resource_uid")
    if not isinstance(resource_uid, str) or not RESOURCE_UID_PATTERN.fullmatch(
        resource_uid
    ):
        errors.append("secret attestation resource_uid is invalid")
        resource_uid = None
    resource_version = attestation.get("resource_version")
    if not isinstance(resource_version, str) or not RESOURCE_VERSION_PATTERN.fullmatch(
        resource_version
    ):
        errors.append("secret attestation resource_version is invalid")
        resource_version = None
    observed_at = _parse_timestamp(attestation.get("observed_at"))
    if observed_at is None:
        errors.append("secret attestation observed_at must be timezone-aware")
    else:
        age_seconds = (now - observed_at).total_seconds()
        if age_seconds < -300:
            errors.append("secret attestation observed_at is in the future")
        elif age_seconds > max_age_seconds:
            errors.append("secret attestation is stale")
    fingerprint = _canonical_sha256(attestation) if fields == ATTESTATION_FIELDS else None
    return resource_uid, resource_version, fingerprint


def build_activation_report(
    manifest_path: Path,
    config_map_path: Path,
    secret_attestation_path: Path,
    *,
    environment: str,
    max_attestation_age_seconds: float = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate staging inputs without claiming the Deployment is live."""
    manifest = manifest_path.resolve()
    config_snapshot = config_map_path.resolve()
    secret_attestation = secret_attestation_path.resolve()
    current = now or datetime.now(UTC)
    errors: list[str] = []

    if environment != "staging":
        errors.append("activation contract v1 only permits the staging environment")
    time_window_valid = not (
        current.tzinfo is None
        or current.utcoffset() is None
        or not math.isfinite(max_attestation_age_seconds)
        or max_attestation_age_seconds <= 0
    )
    if not time_window_valid:
        errors.append("activation time window is invalid")

    deployment_report = build_deployment_report(
        manifest,
        network_policy_path=manifest,
        expected_replicas=1,
    )
    errors.extend(deployment_report["errors"])

    documents: list[dict[str, Any]] = []
    config_documents: list[dict[str, Any]] = []
    attestation: dict[str, Any] = {}
    try:
        documents = _load_yaml_documents(manifest)
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"activation manifest is unavailable or invalid: {type(exc).__name__}")
    try:
        config_documents = _load_yaml_documents(config_snapshot)
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"ConfigMap snapshot is unavailable or invalid: {type(exc).__name__}")
    try:
        attestation = _load_json_object(secret_attestation)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"secret attestation is unavailable or invalid: {type(exc).__name__}")

    deployment = _resource(documents, "Deployment", DEPLOYMENT_NAME)
    if _resource(documents, "Secret", SECRET_NAME) is not None:
        errors.append("activation manifest must not embed the dedicated worker Secret")
    image_digest = _validate_image_contract(deployment, errors)
    config_uid, config_version, config_fingerprint = _validate_config_map(
        _resource(config_documents, "ConfigMap", CONFIG_NAME),
        errors,
    )

    secret_uid: str | None = None
    resource_version: str | None = None
    attestation_fingerprint: str | None = None
    if attestation and time_window_valid:
        (
            secret_uid,
            resource_version,
            attestation_fingerprint,
        ) = _validate_secret_attestation(
            attestation,
            environment=environment,
            max_age_seconds=max_attestation_age_seconds,
            now=current,
            errors=errors,
        )

    files: dict[str, dict[str, str]] = {}
    for name, path in (
        ("manifest", manifest),
        ("config_map", config_snapshot),
        ("secret_attestation", secret_attestation),
    ):
        if path.is_file():
            files[name] = {"path": path.as_posix(), "sha256": _sha256(path)}

    requested_replicas = (
        ((deployment or {}).get("spec") or {}).get("replicas")
    )
    ready = not errors
    return {
        "schema": ACTIVATION_SCHEMA,
        "status": "ready_for_activation" if ready else "blocked",
        "activation_ready": ready,
        "deployed": False,
        "live_cluster_verified": False,
        "environment": environment,
        "deployment_name": DEPLOYMENT_NAME,
        "requested_replicas": requested_replicas,
        "image_digest": image_digest,
        "config_resource_uid": config_uid,
        "config_resource_version": config_version,
        "config_fingerprint": config_fingerprint,
        "config_keys": list(REQUIRED_CONFIG_KEYS),
        "secret_keys": list(REQUIRED_SECRET_KEYS),
        "secret_resource_uid": secret_uid,
        "secret_resource_version": resource_version,
        "secret_attestation_fingerprint": attestation_fingerprint,
        "files": files,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config-map", type=Path, required=True)
    parser.add_argument("--secret-attestation", type=Path, required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--max-attestation-age-seconds", type=float, default=900)
    args = parser.parse_args(argv)
    report = build_activation_report(
        args.manifest,
        args.config_map,
        args.secret_attestation,
        environment=args.environment,
        max_attestation_age_seconds=args.max_attestation_age_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["activation_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
