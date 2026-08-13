"""Render a read-only staging platform preflight Job.

The Job uses the attested release image and environment-provided ConfigMap and
Secret to emit a redacted platform snapshot. It has no Kubernetes API token and
does not run migrations or application code.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .staging_live_evidence import (
    CANDIDATE_FINGERPRINT_ANNOTATION,
    ENVIRONMENT_ACCESS_FINGERPRINT_ANNOTATION,
    ENVIRONMENT_ANNOTATION,
    RELEASE_FINGERPRINT_ANNOTATION,
    RUNTIME_FINGERPRINT_ANNOTATION,
    SCHEMA_FINGERPRINT_ANNOTATION,
    SOURCE_REVISION_ANNOTATION,
)
from .staging_workload_manifest import (
    DEFAULT_NAMESPACE,
    DEVELOPMENT_NAMESPACE,
    DNS_LABEL_PATTERN,
    IMMUTABLE_IMAGE_PATTERN,
    SOURCE_REVISION_PATTERN,
    StagingWorkloadManifestError,
    staging_release_input_errors,
)

PREFLIGHT_SCHEMA = "gda.staging_platform_preflight.v1"
OBSERVATION_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,19}[a-z0-9])?$")


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StagingWorkloadManifestError("JSON evidence must be an object")
    return value


def _security_context() -> dict[str, Any]:
    return {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "runAsNonRoot": True,
    }


def build_staging_platform_preflight(
    candidate: Mapping[str, Any],
    registry: Mapping[str, Any],
    provenance: Mapping[str, Any],
    release: Mapping[str, Any],
    *,
    source_repository: str,
    source_revision: str,
    verifier_revision: str,
    observation_id: str,
    namespace: str = DEFAULT_NAMESPACE,
    config_map_name: str = "gis-agent-staging-config",
    secret_name: str = "gis-agent-staging-secret",
    image_pull_secret_name: str = "gis-agent-staging-registry",
) -> dict[str, Any]:
    """Build a deterministic, read-only platform snapshot Job."""
    errors = staging_release_input_errors(
        candidate,
        registry,
        provenance,
        release,
        source_repository=source_repository,
        source_revision=source_revision,
        verifier_revision=verifier_revision,
    )
    for label, value in (
        ("namespace", namespace),
        ("ConfigMap", config_map_name),
        ("Secret", secret_name),
        ("image pull Secret", image_pull_secret_name),
    ):
        if not DNS_LABEL_PATTERN.fullmatch(value):
            errors.append(f"{label} name is invalid")
    if namespace == DEVELOPMENT_NAMESPACE:
        errors.append("protected staging cannot target the development namespace")
    if not OBSERVATION_ID_PATTERN.fullmatch(observation_id):
        errors.append("observation ID is invalid")
    image = release.get("image")
    if not isinstance(image, str) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(image):
        errors.append("release image must be an immutable GHCR digest")
    if release.get("source_revision") != source_revision or not (
        isinstance(source_revision, str)
        and SOURCE_REVISION_PATTERN.fullmatch(source_revision)
    ):
        errors.append("source revision is invalid or does not match the release")
    if errors:
        raise StagingWorkloadManifestError("; ".join(errors))

    release_fingerprint = str(release["evidence_fingerprint"])
    name = (
        f"gis-agent-platform-{source_revision[:8]}-"
        f"{release_fingerprint[:8]}-{observation_id}"
    )
    if not DNS_LABEL_PATTERN.fullmatch(name):
        raise StagingWorkloadManifestError("preflight Job name is invalid")
    labels = {
        "app.kubernetes.io/name": "gis-agent-platform-preflight",
        "app.kubernetes.io/part-of": "gis-data-agent",
        "app.kubernetes.io/component": "preflight",
        "app.kubernetes.io/managed-by": "gda-staging-release",
        "gisdataagent.io/source-revision": source_revision,
    }
    annotations = {
        SOURCE_REVISION_ANNOTATION: source_revision,
        CANDIDATE_FINGERPRINT_ANNOTATION: str(
            release["candidate_evidence_fingerprint"]
        ),
        RELEASE_FINGERPRINT_ANNOTATION: release_fingerprint,
        ENVIRONMENT_ANNOTATION: "staging",
        SCHEMA_FINGERPRINT_ANNOTATION: str(release["schema_fingerprint"]),
        ENVIRONMENT_ACCESS_FINGERPRINT_ANNOTATION: str(
            release["environment_access_fingerprint"]
        ),
        RUNTIME_FINGERPRINT_ANNOTATION: str(release["runtime_fingerprint"]),
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "activeDeadlineSeconds": 300,
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "metadata": {"labels": labels, "annotations": annotations},
                "spec": {
                    "automountServiceAccountToken": False,
                    "imagePullSecrets": [{"name": image_pull_secret_name}],
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "platform-snapshot",
                            "image": image,
                            "imagePullPolicy": "Always",
                            "envFrom": [
                                {"configMapRef": {"name": config_map_name}},
                                {"secretRef": {"name": secret_name}},
                            ],
                            "env": [
                                {
                                    "name": "GDA_DEPLOYMENT_PROFILE",
                                    "value": "staging",
                                },
                                {"name": "POSTGRES_ADMIN_USER", "value": ""},
                                {
                                    "name": "POSTGRES_ADMIN_PASSWORD",
                                    "value": "",
                                },
                            ],
                            "command": ["/app/.venv/bin/python"],
                            "args": [
                                "-m",
                                "data_agent.staging_platform_snapshot",
                                "--profile",
                                "staging",
                            ],
                            "securityContext": _security_context(),
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "256Mi"},
                                "limits": {"cpu": "1", "memory": "1Gi"},
                            },
                        }
                    ],
                },
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-evidence", type=Path, required=True)
    parser.add_argument("--registry-evidence", type=Path, required=True)
    parser.add_argument("--provenance-evidence", type=Path, required=True)
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--verifier-revision", required=True)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--config-map-name", default="gis-agent-staging-config")
    parser.add_argument("--secret-name", default="gis-agent-staging-secret")
    parser.add_argument(
        "--image-pull-secret-name",
        default="gis-agent-staging-registry",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document = build_staging_platform_preflight(
            _load_json_object(args.candidate_evidence),
            _load_json_object(args.registry_evidence),
            _load_json_object(args.provenance_evidence),
            _load_json_object(args.release_evidence),
            source_repository=args.source_repository,
            source_revision=args.source_revision,
            verifier_revision=args.verifier_revision,
            observation_id=args.observation_id,
            namespace=args.namespace,
            config_map_name=args.config_map_name,
            secret_name=args.secret_name,
            image_pull_secret_name=args.image_pull_secret_name,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            yaml.safe_dump(document, explicit_start=True, sort_keys=False),
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, StagingWorkloadManifestError) as exc:
        print(
            json.dumps(
                {
                    "schema": PREFLIGHT_SCHEMA,
                    "status": "blocked",
                    "preflight_rendered": False,
                    "production_promotion_allowed": False,
                    "error": f"staging preflight blocked: {type(exc).__name__}",
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "schema": PREFLIGHT_SCHEMA,
                "status": "rendered",
                "preflight_rendered": True,
                "job_name": document["metadata"]["name"],
                "output": str(args.output),
                "production_promotion_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
