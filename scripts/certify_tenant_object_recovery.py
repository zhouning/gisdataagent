#!/usr/bin/env python3
"""Certify tenant-scoped object recovery against disposable MinIO."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.platform_runtime.object_recovery import (
    TenantObjectDigest,
    TenantObjectScope,
    build_object_recovery_manifest,
    compare_object_recovery_manifests,
    sha256_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/tenant-object-recovery/acceptance-report.json"
DEFAULT_MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"
DEFAULT_MC_IMAGE = "minio/mc:RELEASE.2025-04-16T18-13-26Z"


def _auth(access_key: str, secret_key: str) -> dict[str, str]:
    return {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "region_name": "us-east-1",
    }


def _client(endpoint: str, access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        config=BotoConfig(s3={"addressing_style": "path"}),
        **_auth(access_key, secret_key),
    )


class _TemporaryMinio:
    def __init__(self, minio_image: str, mc_image: str) -> None:
        suffix = secrets.token_hex(6)
        self.minio_image = minio_image
        self.mc_image = mc_image
        self.network = f"gda-object-recovery-{suffix}"
        self.volume = f"gda-object-recovery-{suffix}"
        self.container = f"gda-object-recovery-minio-{suffix}"
        self.source_bucket = f"gda-object-source-{suffix}"
        self.restored_bucket = f"gda-object-restored-{suffix}"
        self.root_user = f"gda-root-{suffix}"
        # Keep credentials free of a leading dash: mc treats an unescaped
        # secret beginning with '-' as a global option.
        self.root_secret = f"gda-root-secret-{secrets.token_urlsafe(18)}"
        self.endpoint: str | None = None
        self.admin: Any | None = None
        self.users: dict[str, tuple[str, str]] = {}
        self.policies: dict[str, str] = {}
        self._started = False

    @staticmethod
    def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("docker", *args),
            check=check,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def start(self) -> None:
        self._docker("image", "inspect", self.minio_image)
        self._docker("image", "inspect", self.mc_image)
        self._docker("network", "create", self.network)
        self._docker("volume", "create", self.volume)
        self._docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            self.container,
            "--network",
            self.network,
            "--network-alias",
            "minio",
            "--publish",
            "127.0.0.1::9000",
            "--mount",
            f"type=volume,source={self.volume},target=/data",
            "--env",
            f"MINIO_ROOT_USER={self.root_user}",
            "--env",
            f"MINIO_ROOT_PASSWORD={self.root_secret}",
            self.minio_image,
            "server",
            "/data",
            "--address",
            ":9000",
        )
        self._started = True
        port = self._docker("port", self.container, "9000/tcp").stdout.strip()
        if not port:
            raise RuntimeError("MinIO API port was not published")
        self.endpoint = f"http://127.0.0.1:{port.rsplit(':', 1)[-1]}"
        self.admin = _client(self.endpoint, self.root_user, self.root_secret)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                self.admin.create_bucket(Bucket=self.source_bucket)
                self.admin.create_bucket(Bucket=self.restored_bucket)
                for bucket in (self.source_bucket, self.restored_bucket):
                    self.admin.put_bucket_versioning(
                        Bucket=bucket,
                        VersioningConfiguration={"Status": "Enabled"},
                    )
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("disposable MinIO did not become ready")

    def _run_mc(self, command: str, *, policy_path: Path | None = None) -> None:
        if not self._started:
            raise RuntimeError("MinIO is not running")
        args = [
            "run",
            "--rm",
            "--network",
            self.network,
            "--entrypoint",
            "/bin/sh",
        ]
        if policy_path is not None:
            args.extend(["-v", f"{policy_path}:/gda-policy.json:ro"])
        args.extend(
            [
                self.mc_image,
                "-c",
                "set -eu; mc alias set local http://minio:9000 "
                f"'{self.root_user}' '{self.root_secret}'; {command}",
            ]
        )
        result = self._docker(*args, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout).replace(self.root_secret, "[REDACTED]")
            raise RuntimeError(f"MinIO admin command failed: {message[:800]}")

    def add_user(self, tenant_id: str, prefix: str) -> TenantObjectScope:
        suffix = secrets.token_hex(4)
        user = f"gda-obj-{tenant_id[-1]}-{suffix}"
        secret = f"gda-object-secret-{secrets.token_urlsafe(24)}"
        policy = f"gda-obj-policy-{tenant_id[-1]}-{suffix}"
        bucket_arns = [
            f"arn:aws:s3:::{self.source_bucket}",
            f"arn:aws:s3:::{self.restored_bucket}",
        ]
        object_arns = [f"{bucket_arn}/{prefix}*" for bucket_arn in bucket_arns]
        policy_payload = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetBucketLocation"],
                    "Resource": bucket_arns,
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": bucket_arns,
                    "Condition": {"StringLike": {"s3:prefix": [prefix, f"{prefix}*"]}},
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:GetObjectVersion",
                        "s3:PutObject",
                        "s3:DeleteObject",
                        "s3:DeleteObjectVersion",
                    ],
                    "Resource": object_arns,
                },
            ],
        }
        policy_file = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        policy_path = Path(policy_file.name)
        try:
            json.dump(policy_payload, policy_file, sort_keys=True)
            policy_file.close()
            self._run_mc(
                f"mc admin user add local '{user}' '{secret}'; "
                f"mc admin policy create local '{policy}' /gda-policy.json; "
                f"mc admin policy attach local '{policy}' --user '{user}'",
                policy_path=policy_path,
            )
        finally:
            policy_path.unlink(missing_ok=True)
        self.users[tenant_id] = (user, secret)
        self.policies[tenant_id] = policy
        return TenantObjectScope(tenant_id, prefix)

    def _delete_bucket(self, bucket: str) -> bool:
        if self.admin is None:
            return False
        versions = self.admin.list_object_versions(Bucket=bucket)
        objects = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for item in (*versions.get("Versions", []), *versions.get("DeleteMarkers", []))
        ]
        if objects:
            self.admin.delete_objects(
                Bucket=bucket, Delete={"Objects": objects, "Quiet": True}
            )
        self.admin.delete_bucket(Bucket=bucket)
        try:
            self.admin.head_bucket(Bucket=bucket)
        except ClientError as exc:
            return str(exc.response.get("Error", {}).get("Code") or "") in {
                "404",
                "NoSuchBucket",
            }
        return False

    def cleanup(self) -> dict[str, bool]:
        cleanup = {
            "source_bucket_absent": self._delete_bucket(self.source_bucket),
            "restored_bucket_absent": self._delete_bucket(self.restored_bucket),
        }
        for tenant_id, (user, _) in self.users.items():
            policy = self.policies.get(tenant_id)
            if policy:
                self._run_mc(
                    f"mc admin policy detach local '{policy}' --user '{user}' || true; "
                    f"mc admin policy remove local '{policy}' || true; "
                    f"mc admin user remove local '{user}' || true",
                )
        if self._started:
            self._docker("rm", "--force", self.container, check=False)
        cleanup["container_absent"] = (
            self._docker("container", "inspect", self.container, check=False).returncode != 0
        )
        self._docker("volume", "rm", self.volume, check=False)
        cleanup["volume_absent"] = (
            self._docker("volume", "inspect", self.volume, check=False).returncode != 0
        )
        self._docker("network", "rm", self.network, check=False)
        cleanup["network_absent"] = (
            self._docker("network", "inspect", self.network, check=False).returncode != 0
        )
        return cleanup


def _read_body(response: dict[str, Any]) -> bytes:
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise RuntimeError("S3 response has no readable body")
    try:
        return body.read()
    finally:
        body.close()


def _put_and_digest(
    client: Any,
    scope: TenantObjectScope,
    bucket: str,
    key: str,
    payload: bytes,
) -> TenantObjectDigest:
    scope.put_object(client, bucket=bucket, key=key, Body=payload)
    head = scope.head_object(client, bucket=bucket, key=key)
    readback = _read_body(scope.get_object(client, bucket=bucket, key=key))
    if readback != payload:
        raise RuntimeError(f"source readback changed for {key}")
    version_id = str(head.get("VersionId") or "").strip()
    etag = str(head.get("ETag") or "").strip('"')
    return TenantObjectDigest(
        tenant_id=scope.tenant_id,
        prefix=scope.prefix,
        key=key,
        size_bytes=int(head.get("ContentLength") or 0),
        etag=etag,
        version_id=version_id,
        sha256=sha256_bytes(payload),
    )


def _denied(call) -> dict[str, Any]:
    try:
        call()
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        return {"denied": code in {"AccessDenied", "AllAccessDisabled"}, "code": code}
    return {"denied": False, "code": None}


def _run(sandbox: _TemporaryMinio) -> dict[str, Any]:
    if sandbox.endpoint is None or sandbox.admin is None:
        raise RuntimeError("MinIO is not ready")
    prefixes = {"tenant-a": "tenants/tenant-a/", "tenant-b": "tenants/tenant-b/"}
    scopes = {
        tenant: sandbox.add_user(tenant, prefix)
        for tenant, prefix in prefixes.items()
    }
    clients = {
        tenant: _client(sandbox.endpoint, *sandbox.users[tenant]) for tenant in prefixes
    }
    payloads = {
        "tenant-a": {
            "tenants/tenant-a/roads.json": b'{"type":"FeatureCollection","features":[]}'
            + b"\n",
            "tenants/tenant-a/tiles/0.bin": b"tenant-a-binary\x00\x01",
        },
        "tenant-b": {
            "tenants/tenant-b/roads.json": b'{"type":"FeatureCollection","features":[1]}'
            + b"\n",
            "tenants/tenant-b/tiles/0.bin": b"tenant-b-binary\x02\x03",
        },
    }
    source_objects = tuple(
        _put_and_digest(
            clients[tenant],
            scopes[tenant],
            sandbox.source_bucket,
            key,
            payload,
        )
        for tenant, tenant_payloads in payloads.items()
        for key, payload in tenant_payloads.items()
    )
    source_manifest = build_object_recovery_manifest(prefixes, source_objects)

    restored_objects = tuple(
        _put_and_digest(
            clients[tenant],
            scopes[tenant],
            sandbox.restored_bucket,
            key,
            payload,
        )
        for tenant, tenant_payloads in payloads.items()
        for key, payload in tenant_payloads.items()
    )
    restored_manifest = build_object_recovery_manifest(prefixes, restored_objects)
    compare_object_recovery_manifests(
        source_manifest, restored_manifest, allow_version_id_remap=True
    )

    cross_checks: dict[str, Any] = {}
    for tenant in prefixes:
        other = "tenant-b" if tenant == "tenant-a" else "tenant-a"
        other_key = next(iter(payloads[other]))
        client = clients[tenant]
        forbidden_key = other_key.replace("roads.json", "forbidden.json")
        cross_checks[f"{tenant}_cross_read"] = _denied(
            lambda client=client, key=other_key: client.get_object(
                Bucket=sandbox.restored_bucket, Key=key
            )
        )
        cross_checks[f"{tenant}_cross_write"] = _denied(
            lambda client=client, key=forbidden_key: client.put_object(
                Bucket=sandbox.restored_bucket,
                Key=key,
                Body=b"must-not-write",
            )
        )
        cross_checks[f"{tenant}_cross_delete"] = _denied(
            lambda client=client, key=other_key: client.delete_object(
                Bucket=sandbox.restored_bucket, Key=key
            )
        )

    source_bucket_versioning = sandbox.admin.get_bucket_versioning(Bucket=sandbox.source_bucket)
    restored_bucket_versioning = sandbox.admin.get_bucket_versioning(Bucket=sandbox.restored_bucket)
    checks = {
        "source_versioning_enabled": source_bucket_versioning.get("Status") == "Enabled",
        "restored_versioning_enabled": restored_bucket_versioning.get("Status") == "Enabled",
        "source_inventory_has_two_tenants": {
            item.tenant_id for item in source_objects
        }
        == set(prefixes),
        "source_and_restored_object_count_match": len(source_objects) == len(restored_objects) == 4,
        "restored_manifest_admitted_with_explicit_version_remap": True,
        "source_and_restored_etags_match": [item.etag for item in source_objects]
        == [item.etag for item in restored_objects],
        "source_and_restored_bytes_match": [item.sha256 for item in source_objects]
        == [item.sha256 for item in restored_objects],
        "all_cross_tenant_operations_denied": all(
            item["denied"] for item in cross_checks.values()
        ),
        "forbidden_cross_tenant_objects_absent": all(
            not any(
                row.get("Key") == key
                for row in sandbox.admin.list_objects_v2(
                    Bucket=sandbox.restored_bucket, Prefix=prefix
                ).get("Contents", [])
            )
            for key, prefix in (
                ("tenants/tenant-a/forbidden.json", prefixes["tenant-a"]),
                ("tenants/tenant-b/forbidden.json", prefixes["tenant-b"]),
            )
        ),
    }
    return {
        "schema": "gda.tenant_object_recovery.acceptance.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "provider": {
            "name": "minio",
            "image": sandbox.minio_image,
            "endpoint": sandbox.endpoint,
            "source_bucket": sandbox.source_bucket,
            "restored_bucket": sandbox.restored_bucket,
            "persistent": False,
        },
        "tenant_prefixes": prefixes,
        "source_manifest": source_manifest.as_dict(),
        "restored_manifest": restored_manifest.as_dict(),
        "cross_tenant_operations": cross_checks,
        "checks": checks,
        "not_claimed": [
            "production object-store replication, Object Lock, HA, PITR, RPO or RTO",
            "multipart ETag equivalence or provider-independent VersionId preservation",
            "control-ledger and object-store atomic cross-store commit",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minio-image", default=DEFAULT_MINIO_IMAGE)
    parser.add_argument("--mc-image", default=DEFAULT_MC_IMAGE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)

    sandbox = _TemporaryMinio(args.minio_image, args.mc_image)
    report: dict[str, Any]
    try:
        sandbox.start()
        report = _run(sandbox)
    except Exception as exc:
        message = str(exc).replace(sandbox.root_secret, "[REDACTED]")
        report = {
            "schema": "gda.tenant_object_recovery.acceptance.v1",
            "status": "failed",
            "error": message[:1000],
        }
    finally:
        cleanup = sandbox.cleanup()
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
        report["status"] = "failed"
    report["report_sha256"] = canonical_json_fingerprint(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "report_sha256": report["report_sha256"],
                "checks": report.get("checks", {}),
                "cleanup": cleanup,
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
