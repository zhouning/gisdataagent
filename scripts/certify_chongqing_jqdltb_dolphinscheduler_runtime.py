#!/usr/bin/env python3
"""Certify the real DolphinScheduler runtime evidence for the JQDLTB audit.

This is an evidence compiler, not a product-promotion command.  It checks the
local 3.4.2 provider health and the already persisted deployment, dispatch and
finalization receipts for the frozen JQDLTB source.  A failed quality result is
an expected and explicit outcome of this certification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from data_agent.platform_contracts import Artifact, ArtifactRole, canonical_json_fingerprint
from data_agent.platform_gateway import PlatformGateway, PlatformGatewayError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = REPO_ROOT / ".tmp/dolphinscheduler-sandbox/profile.json"
DEFAULT_RUNTIME_DIR = REPO_ROOT / ".tmp/dolphinscheduler-sandbox"
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs/reports/jqdltb_dolphinscheduler_runtime_2026-08-26.json"
)
SOURCE_RESOURCE_VERSION_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
DEFINITION_VERSION_ID = UUID("b1c933bd-8968-559f-b2b1-228fe5dc6f24")
RUNTIME_EVIDENCE_CREATED_AT = datetime(2026, 8, 26, tzinfo=UTC)
SCHEMA = "gda.jqdltb_dolphinscheduler_runtime_certification.v1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _health(profile: dict[str, Any]) -> dict[str, Any]:
    url = str(profile["base_url"]).rstrip("/") + "/actuator/health"
    request = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + Path(profile["token_file"]).read_text().strip()},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {
                "url": url,
                "http_status": int(response.status),
                "status": payload.get("status"),
                "reachable": response.status == 200,
            }
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        # The managed execution sandbox may deny host-loopback networking even
        # while the Compose container is healthy.  Docker's health observation
        # is an equivalent local signal and is recorded as such in the report.
        try:
            names = subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "label=com.docker.compose.service=dolphinscheduler",
                    "--format",
                    "{{.Names}}",
                ],
                text=True,
                timeout=5,
            ).splitlines()
            if names:
                status = subprocess.check_output(
                    [
                        "docker",
                        "inspect",
                        "-f",
                        "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
                        names[0],
                    ],
                    text=True,
                    timeout=5,
                ).strip()
                return {
                    "url": url,
                    "reachable": status == "healthy",
                    "status": "UP" if status == "healthy" else status.upper(),
                    "observation_source": "docker_health",
                    "container": names[0],
                    "http_probe_error": str(exc),
                }
        except (OSError, subprocess.SubprocessError) as docker_exc:
            return {
                "url": url,
                "reachable": False,
                "error": str(exc),
                "docker_health_error": str(docker_exc),
            }
        return {"url": url, "reachable": False, "error": str(exc)}


def certify(
    *,
    profile_path: Path,
    runtime_dir: Path,
    output: Path,
    record_artifact: bool = False,
) -> dict[str, Any]:
    profile = _read_json(profile_path)
    deployment_path = runtime_dir / "jqdltb-deployment-report.json"
    submission_path = runtime_dir / "jqdltb-run-submission-report.json"
    finalization_path = runtime_dir / "jqdltb-finalization-report.json"
    required = (deployment_path, submission_path, finalization_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError("missing JQDLTB runtime receipts: " + ", ".join(missing))

    deployment = _read_json(deployment_path)
    submission = _read_json(submission_path)
    finalization = _read_json(finalization_path)
    checks = {
        "profile_schema": profile.get("schema") == "gda.dolphinscheduler_sandbox_profile.v1",
        "provider_version": profile.get("server_version") == "3.4.2",
        "deployment_ready": deployment.get("status") == "ready",
        "deployment_definition": deployment.get("definition_version_id")
        == str(DEFINITION_VERSION_ID),
        "deployment_source": deployment.get("source_resource_version_id")
        == str(SOURCE_RESOURCE_VERSION_ID),
        "workflow_created": deployment.get("workflow_created") is True,
        "submission_accepted": submission.get("status") == "accepted",
        "submission_definition": submission.get("definition_version_id")
        == str(DEFINITION_VERSION_ID),
        "submission_source": submission.get("source_resource_version_id")
        == str(SOURCE_RESOURCE_VERSION_ID),
        "provider_success": finalization.get("provider_state") == "SUCCESS",
        "quality_failed_explicit": finalization.get("quality_verdict") == "failed",
        "run_failed_closed": finalization.get("platform_run_status") == "failed",
        "no_product_created": finalization.get("data_product_version_created") is False,
    }
    health = _health(profile)
    checks["provider_health"] = health.get("reachable") is True and health.get("status") == "UP"
    receipts = {
        "profile": {
            "path": str(profile_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(profile_path),
            "server_version": profile.get("server_version"),
            "api_profile": profile.get("api_profile"),
            "project_code": profile.get("project_code"),
        },
        "deployment": {
            "path": str(deployment_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(deployment_path),
            "workflow_definition_code": deployment.get("workflow_definition_code"),
        },
        "submission": {
            "path": str(submission_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(submission_path),
            "run_id": submission.get("run_id"),
        },
        "finalization": {
            "path": str(finalization_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(finalization_path),
            "run_id": finalization.get("run_id"),
            "quality_result_id": finalization.get("quality_result_id"),
        },
    }
    identity = {
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "run_id": submission.get("run_id"),
        "quality_result_id": finalization.get("quality_result_id"),
    }
    checks["run_identity_continuity"] = (
        finalization.get("run_id") == submission.get("run_id")
        and finalization.get("quality_result_id") is not None
    )
    report = {
        "schema": SCHEMA,
        "status": "passed" if all(checks.values()) else "failed",
        "certification_mode": "real_local_dolphinscheduler_receipts",
        "promotion_ready": False,
        "quality_result_is_authoritative": True,
        "quality_verdict": finalization.get("quality_verdict"),
        "data_product_version_created": False,
        "artifact_recorded": False,
        "artifact_id": None,
        "health": health,
        "identity": identity,
        "checks": checks,
        "receipts": receipts,
        "limitations": [
            "local_single_node_sandbox_only",
            "does_not_approve_business_or_license_decisions",
            "failed_quality_must_remain_failed_closed",
            "does_not_prove_staging_or_production_ha_rpo_rto",
        ],
        "certified_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    if record_artifact:
        run_id = UUID(str(submission["run_id"]))
        artifact_id = uuid5(
            NAMESPACE_URL,
            f"gda://local-dev/artifact/{run_id}/dolphinscheduler-runtime-attestation-v2",
        )
        artifact = Artifact(
            tenant_id="local-dev",
            artifact_id=artifact_id,
            artifact_key=f"jqdltb-dolphinscheduler-runtime-v2-{run_id.hex[:16]}",
            artifact_role=ArtifactRole.EVIDENCE,
            storage_uri=finalization_path.as_uri(),
            media_type="application/json",
            content_sha256=_sha256(finalization_path),
            size_bytes=finalization_path.stat().st_size,
            run_id=run_id,
            resource_version_id=SOURCE_RESOURCE_VERSION_ID,
            manifest={
                "schema": SCHEMA,
                "provider": "dolphinscheduler",
                "server_version": profile.get("server_version"),
                "provider_state": finalization.get("provider_state"),
                "quality_verdict": finalization.get("quality_verdict"),
                "promotion_ready": False,
            },
            created_by="workload:ar0-runtime-certifier",
            created_at=RUNTIME_EVIDENCE_CREATED_AT,
        )
        try:
            artifact_result = PlatformGateway().record_artifact(artifact)
        except PlatformGatewayError as exc:
            report["artifact_record_error"] = str(exc)
            report["status"] = "failed"
        else:
            report["artifact_recorded"] = True
            report["artifact_id"] = str(artifact.artifact_id)
            report["artifact_created"] = artifact_result.created
            report["artifact_content_sha256"] = artifact.content_sha256
    report["report_sha256"] = canonical_json_fingerprint(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--record-artifact",
        action="store_true",
        help="record an idempotent evidence Artifact in the GDA control ledger",
    )
    args = parser.parse_args()
    report = certify(
        profile_path=args.profile.resolve(),
        runtime_dir=args.runtime_dir.resolve(),
        output=args.output.resolve(),
        record_artifact=args.record_artifact,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
