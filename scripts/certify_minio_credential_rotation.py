#!/usr/bin/env python3
"""Certify real MinIO credential rotation with an isolated read-only source."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from dotenv import dotenv_values

from data_agent.connectors.object_storage import _s3_client
from data_agent.source_connector_governance import (
    CertificationStatus,
    CredentialAuthType,
    CredentialReference,
    MappingCredentialResolver,
    SourceConnectorKind,
    SourceDefinition,
    certify_source_connector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-connector-certification/minio-rotation-report.json"
SOURCE_BUCKET = "gis-agent-lakehouse"
SOURCE_KEY = "catalog/stac/data-products/chongqing-osm-roads/items/v1.2.0.json"


def _settings() -> dict[str, str]:
    values = {
        key: str(value)
        for key, value in dotenv_values(REPO_ROOT / ".env").items()
        if value is not None
    }
    return {**values, **os.environ}


def _auth(access_key: str, secret_key: str, region: str) -> dict[str, str]:
    return {
        "type": "aws_sigv4",
        "access_key_id": access_key,
        "secret_access_key": secret_key,
        "region_name": region,
    }


class _MinioCertificationSandbox:
    """Own random MinIO IAM and object-storage resources, then remove only those."""

    def __init__(self, endpoint_url: str, settings: dict[str, str]) -> None:
        suffix = secrets.token_hex(5)
        self.endpoint_url = endpoint_url
        self.region = settings.get("AWS_REGION", "us-east-1")
        self.bucket = f"gda-connector-cert-{suffix}"
        self.key = "input/chongqing-osm-roads-v1.2.0.json"
        self.denied_key = f"write-denied/{suffix}.json"
        self.user = f"gda-connector-reader-{suffix}"
        self.policy = f"gda-connector-read-{suffix}"
        self.secret_v1 = secrets.token_urlsafe(32)
        self.secret_v2 = secrets.token_urlsafe(32)
        self._admin = _s3_client(
            endpoint_url,
            _auth(
                settings.get("MINIO_ROOT_USER", "minio_admin"),
                settings.get("MINIO_ROOT_PASSWORD", "local_dev_minio_secret"),
                self.region,
            ),
        )
        self._created_bucket = False
        self._created_object = False
        self._created_user = False
        self._created_policy = False
        self._attached_policy = False
        self._policy_directory = tempfile.TemporaryDirectory(
            prefix="minio-policy-",
            dir=REPO_ROOT / ".tmp/source-connector-certification",
        )

    @property
    def policy_path(self) -> Path:
        return Path(self._policy_directory.name) / "policy.json"

    def setup(self) -> None:
        source = self._admin.get_object(Bucket=SOURCE_BUCKET, Key=SOURCE_KEY)
        source_payload = source["Body"].read()
        source["Body"].close()
        item = json.loads(source_payload)
        if item.get("id") != "chongqing-osm-roads-v1.2.0":
            raise RuntimeError("governed Chongqing OSM STAC item is not v1.2.0")

        self._admin.create_bucket(Bucket=self.bucket)
        self._created_bucket = True
        self._admin.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=source_payload,
            ContentType="application/geo+json",
            Metadata={"gda-certification-source": f"s3://{SOURCE_BUCKET}/{SOURCE_KEY}"},
        )
        self._created_object = True

        self.policy_path.write_text(
            json.dumps(self._read_only_policy(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._run_mc(
            'mc admin user add local "$GDA_CERT_USER" "$GDA_CERT_SECRET"',
            secret=self.secret_v1,
        )
        self._created_user = True
        self._run_mc(
            'mc admin policy create local "$GDA_CERT_POLICY" /gda-cert/policy.json',
            mount_policy=True,
        )
        self._created_policy = True
        self._run_mc('mc admin policy attach local "$GDA_CERT_POLICY" --user "$GDA_CERT_USER"')
        self._attached_policy = True

    def rotate_secret(self) -> None:
        self._run_mc(
            'mc admin user add local "$GDA_CERT_USER" "$GDA_CERT_SECRET"',
            secret=self.secret_v2,
        )

    def replace_item(self, item: dict[str, Any]) -> None:
        """Replace the isolated source object through the sandbox administrator."""

        payload = (json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        self._admin.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=payload,
            ContentType="application/geo+json",
            Metadata={"gda-certification-source": f"s3://{SOURCE_BUCKET}/{SOURCE_KEY}"},
        )

    def write_denial(self) -> dict[str, Any]:
        client = _s3_client(
            self.endpoint_url,
            _auth(self.user, self.secret_v1, self.region),
        )
        error_code: str | None = None
        try:
            client.put_object(
                Bucket=self.bucket,
                Key=self.denied_key,
                Body=b'{"must_not_write":true}\n',
                ContentType="application/json",
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code") or "")
        object_absent = not self._object_exists(self.denied_key)
        return {
            "denied": error_code in {"AccessDenied", "AllAccessDisabled"} and object_absent,
            "provider_error_code": error_code,
            "object_absent": object_absent,
            "target": f"s3://{self.bucket}/{self.denied_key}",
        }

    def cleanup(self) -> dict[str, bool]:
        if self._attached_policy:
            self._run_mc(
                'mc admin policy detach local "$GDA_CERT_POLICY" --user "$GDA_CERT_USER"',
                check=False,
            )
        if self._created_user:
            self._run_mc(
                'mc admin user remove local "$GDA_CERT_USER"',
                check=False,
            )
        if self._created_policy:
            self._run_mc(
                'mc admin policy remove local "$GDA_CERT_POLICY"',
                check=False,
            )
        if self._created_bucket:
            self._admin.delete_objects(
                Bucket=self.bucket,
                Delete={
                    "Objects": [
                        {"Key": self.key},
                        {"Key": self.denied_key},
                    ],
                    "Quiet": True,
                },
            )
            self._admin.delete_bucket(Bucket=self.bucket)

        user_removed = (
            self._run_mc(
                'mc admin user info local "$GDA_CERT_USER"',
                check=False,
            ).returncode
            != 0
        )
        policy_removed = (
            self._run_mc(
                'mc admin policy info local "$GDA_CERT_POLICY"',
                check=False,
            ).returncode
            != 0
        )
        bucket_removed = self.bucket not in {
            bucket["Name"] for bucket in self._admin.list_buckets().get("Buckets", [])
        }
        denied_object_removed = bucket_removed or not self._object_exists(self.denied_key)
        self._policy_directory.cleanup()
        return {
            "user_removed": user_removed,
            "policy_removed": policy_removed,
            "bucket_removed": bucket_removed,
            "denied_object_removed": denied_object_removed,
            "policy_file_removed": not self.policy_path.exists(),
        }

    def _object_exists(self, key: str) -> bool:
        try:
            self._admin.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code") or "")
            if code in {"404", "NoSuchBucket", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def _read_only_policy(self) -> dict[str, Any]:
        bucket_arn = f"arn:aws:s3:::{self.bucket}"
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListAllMyBuckets"],
                    "Resource": ["arn:aws:s3:::*"],
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetBucketLocation"],
                    "Resource": [bucket_arn],
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": [bucket_arn],
                    "Condition": {"StringLike": {"s3:prefix": [self.key]}},
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"{bucket_arn}/{self.key}"],
                },
            ],
        }

    def _run_mc(
        self,
        command: str,
        *,
        secret: str | None = None,
        mount_policy: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            **os.environ,
            "GDA_CERT_USER": self.user,
            "GDA_CERT_POLICY": self.policy,
        }
        forwarded = ["GDA_CERT_USER", "GDA_CERT_POLICY"]
        if secret is not None:
            environment["GDA_CERT_SECRET"] = secret
            forwarded.append("GDA_CERT_SECRET")
        args = ["docker", "compose", "run", "--rm", "--no-deps", "-T"]
        for name in forwarded:
            args.extend(["-e", name])
        if mount_policy:
            args.extend(["-v", f"{self.policy_path.parent}:/gda-cert:ro"])
        args.extend(
            [
                "--entrypoint",
                "/bin/sh",
                "minio-bucket-init",
                "-c",
                "set -eu; "
                'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" '
                '"$MINIO_ROOT_PASSWORD" >/dev/null; ' + command,
            ]
        )
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout).replace(secret or "", "[REDACTED]")
            raise RuntimeError(f"MinIO admin command failed: {message[:500]}")
        return result


def _credential(version: int) -> CredentialReference:
    return CredentialReference(
        credential_id="credential:minio-rotation-certification",
        version=version,
        auth_type=CredentialAuthType.AWS_SIGV4,
        provider="ephemeral-minio-user",
    )


def _definition(
    endpoint_url: str,
    sandbox: _MinioCertificationSandbox,
    credential: CredentialReference,
) -> SourceDefinition:
    return SourceDefinition(
        source_id="minio-rotation-certification",
        version=f"1.0.{credential.version - 1}",
        source_kind=SourceConnectorKind.OBJECT_STORAGE,
        endpoint_url=endpoint_url,
        owner_ref="team:data-platform",
        credential_reference=credential,
        connector_version="1.0.0",
        query_config={
            "bucket": sandbox.bucket,
            "key": sandbox.key,
            "format": "geojson",
            "discovery_limit": 10,
        },
    )


async def _certify(
    endpoint_url: str,
    sandbox: _MinioCertificationSandbox,
) -> dict[str, Any]:
    reference_v1 = _credential(1)
    reference_v2 = _credential(2)
    definition_v1 = _definition(endpoint_url, sandbox, reference_v1)
    definition_v2 = _definition(endpoint_url, sandbox, reference_v2)
    now = datetime.now(UTC)

    initial = await certify_source_connector(
        definition_v1,
        MappingCredentialResolver(
            {
                (reference_v1.credential_id, 1): _auth(
                    sandbox.user,
                    sandbox.secret_v1,
                    sandbox.region,
                )
            }
        ),
        certified_at=now,
    )
    write_denial = sandbox.write_denial()
    sandbox.rotate_secret()
    stale = await certify_source_connector(
        definition_v1,
        MappingCredentialResolver(
            {
                (reference_v1.credential_id, 1): _auth(
                    sandbox.user,
                    sandbox.secret_v1,
                    sandbox.region,
                )
            }
        ),
        certified_at=now,
    )
    rotated = await certify_source_connector(
        definition_v2,
        MappingCredentialResolver(
            {
                (reference_v2.credential_id, 2): _auth(
                    sandbox.user,
                    sandbox.secret_v2,
                    sandbox.region,
                )
            }
        ),
        certified_at=now,
    )

    secret_free_payload = json.dumps(
        [
            initial.model_dump(mode="json"),
            stale.model_dump(mode="json"),
            rotated.model_dump(mode="json"),
        ],
        sort_keys=True,
    )
    checks = {
        "initial_credential_passed": initial.status is CertificationStatus.PASSED,
        "provider_write_denied": write_denial["denied"],
        "stale_credential_failed_after_rotation": stale.status is CertificationStatus.FAILED,
        "rotated_credential_passed": rotated.status is CertificationStatus.PASSED,
        "credential_reference_changed": (
            reference_v1.fingerprint != reference_v2.fingerprint
            and definition_v1.fingerprint != definition_v2.fingerprint
        ),
        "rotation_preserved_object": (
            initial.discovery is not None
            and rotated.discovery is not None
            and initial.discovery.fingerprint == rotated.discovery.fingerprint
            and initial.profile is not None
            and rotated.profile is not None
            and initial.profile.fingerprint == rotated.profile.fingerprint
        ),
        "credential_secrets_redacted": (
            sandbox.secret_v1 not in secret_free_payload
            and sandbox.secret_v2 not in secret_free_payload
        ),
    }
    return {
        "schema": "gda.minio_credential_rotation.acceptance.v1",
        "generated_at": now.isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "provider": {
            "name": initial.provider,
            "version": initial.provider_version,
        },
        "sandbox": {
            "bucket": sandbox.bucket,
            "key": sandbox.key,
            "user": sandbox.user,
            "policy": sandbox.policy,
            "persistent": False,
        },
        "real_input": f"s3://{SOURCE_BUCKET}/{SOURCE_KEY}",
        "checks": checks,
        "least_privilege": write_denial,
        "credential_rotation": {
            "before_reference_fingerprint": reference_v1.fingerprint,
            "after_reference_fingerprint": reference_v2.fingerprint,
            "before_definition_fingerprint": definition_v1.fingerprint,
            "after_definition_fingerprint": definition_v2.fingerprint,
            "stale_credential_status": stale.status.value,
            "rotated_credential_status": rotated.status.value,
            "discovery_and_profile_fingerprints_stable": checks["rotation_preserved_object"],
        },
        "certifications": {
            "initial": initial.model_dump(mode="json"),
            "stale": stale.model_dump(mode="json"),
            "rotated": rotated.model_dump(mode="json"),
        },
        "not_claimed": [
            "object schema mutation or SchemaDriftEvent persistence",
            "STAC credential rotation",
            "incremental ingestion or CDC",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minio-url", default="http://127.0.0.1:9000")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)

    sandbox = _MinioCertificationSandbox(args.minio_url, _settings())
    report: dict[str, Any] | None = None
    cleanup: dict[str, bool] = {}
    try:
        sandbox.setup()
        report = asyncio.run(_certify(args.minio_url, sandbox))
    finally:
        cleanup = sandbox.cleanup()
    if report is None:
        raise RuntimeError("MinIO certification did not produce a report")
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
        report["status"] = "failed"
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": cleanup,
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
