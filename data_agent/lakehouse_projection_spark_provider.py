"""Docker Spark/Iceberg provider adapter for lakehouse projection repair."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .lakehouse_projection_executor import (
    LakehouseProjectionConfigurationError,
    LakehouseProjectionExecutionError,
    LakehouseProjectionTarget,
    LakehouseSnapshotEvidence,
)


class DockerSparkIcebergProjectionProvider:
    """Invoke the fixed Spark worker in a pinned deployment-side runtime."""

    def __init__(
        self,
        *,
        repository_root: Path,
        image: str,
        docker_network: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: str | None = None,
        java_home: str = "/usr/lib/jvm/java-17-openjdk-arm64",
        timeout_seconds: float = 600,
    ) -> None:
        root = repository_root.resolve()
        if not root.is_dir():
            raise LakehouseProjectionConfigurationError(
                "lakehouse Spark repository root is unavailable"
            )
        if not image.strip() or not docker_network.strip():
            raise LakehouseProjectionConfigurationError(
                "lakehouse Spark image and Docker network are required"
            )
        if not access_key_id or not secret_access_key:
            raise LakehouseProjectionConfigurationError(
                "lakehouse object-store credentials are required"
            )
        if not java_home.startswith("/usr/lib/jvm/"):
            raise LakehouseProjectionConfigurationError(
                "lakehouse Spark JAVA_HOME must be an absolute JVM path"
            )
        if timeout_seconds <= 0 or timeout_seconds > 3600:
            raise LakehouseProjectionConfigurationError(
                "lakehouse Spark timeout must be between 0 and 3600 seconds"
            )
        self.repository_root = root
        self.image = image.strip()
        self.docker_network = docker_network.strip()
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.session_token = session_token
        self.java_home = java_home
        self.timeout_seconds = timeout_seconds

    def _run(
        self,
        action: str,
        target: LakehouseProjectionTarget,
        *,
        records: tuple[dict[str, Any], ...] = (),
        plan_sha256: str | None = None,
        idempotency_key: str | None = None,
        receipt_sha256: str | None = None,
    ) -> LakehouseSnapshotEvidence:
        payload = {
            "action": action,
            "target": {
                "catalog": target.catalog,
                "namespace": target.namespace,
                "table": target.table,
                "warehouse_uri": target.warehouse_uri,
                "endpoint_url": target.endpoint_url,
                "region_name": target.region_name,
                "artifact_sha256": target.artifact_sha256,
                "tenant_id": target.tenant_id,
                "projection_id": target.projection_id,
                "target_ref": target.target_ref,
                "expected_table_content_sha256": target.expected_table_content_sha256,
                "expected_row_count": target.expected_row_count,
            },
            "records": list(records),
            "plan_sha256": plan_sha256,
            "idempotency_key": idempotency_key,
            "receipt_sha256": receipt_sha256,
        }
        environment = os.environ.copy()
        environment["AWS_ACCESS_KEY_ID"] = self.access_key_id
        environment["AWS_SECRET_ACCESS_KEY"] = self.secret_access_key
        environment["AWS_REGION"] = target.region_name
        environment["JAVA_HOME"] = self.java_home
        if self.session_token:
            environment["AWS_SESSION_TOKEN"] = self.session_token
        with tempfile.TemporaryDirectory(prefix="gda-lakehouse-projection-") as raw_directory:
            directory = Path(raw_directory)
            input_path = directory / "request.json"
            output_path = directory / "result.json"
            input_path.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            command = [
                "docker",
                "run",
                "--rm",
                "--network",
                self.docker_network,
                "--env",
                "AWS_ACCESS_KEY_ID",
                "--env",
                "AWS_SECRET_ACCESS_KEY",
                "--env",
                "AWS_REGION",
                "--env",
                "JAVA_HOME",
            ]
            if self.session_token:
                command.extend(("--env", "AWS_SESSION_TOKEN"))
            command.extend(
                (
                    "--mount",
                    f"type=bind,source={self.repository_root},target=/workspace,readonly",
                    "--mount",
                    f"type=bind,source={directory},target=/gda-run",
                    "--workdir",
                    "/workspace",
                    self.image,
                    "python",
                    "-m",
                    "data_agent.lakehouse_projection_spark_worker",
                    "--request",
                    "/gda-run/request.json",
                    "--result",
                    "/gda-run/result.json",
                )
            )
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.repository_root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise LakehouseProjectionExecutionError(
                    "Spark Iceberg provider process could not run"
                ) from exc
            if completed.returncode != 0:
                details = (completed.stderr or completed.stdout)[-4000:]
                raise LakehouseProjectionExecutionError(f"Spark Iceberg provider failed: {details}")
            try:
                result = json.loads(output_path.read_text(encoding="utf-8"))
                return LakehouseSnapshotEvidence.model_validate(result)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LakehouseProjectionExecutionError(
                    "Spark Iceberg provider returned invalid evidence"
                ) from exc

    def observe(self, target: LakehouseProjectionTarget) -> LakehouseSnapshotEvidence:
        return self._run("observe", target)

    def replace(
        self,
        target: LakehouseProjectionTarget,
        records: tuple[dict[str, Any], ...],
        *,
        plan_sha256: str,
        idempotency_key: str,
        receipt_sha256: str | None = None,
    ) -> LakehouseSnapshotEvidence:
        return self._run(
            "rebuild",
            target,
            records=records,
            plan_sha256=plan_sha256,
            idempotency_key=idempotency_key,
            receipt_sha256=receipt_sha256,
        )

    def drop(
        self,
        target: LakehouseProjectionTarget,
        *,
        plan_sha256: str,
        idempotency_key: str,
        receipt_sha256: str | None = None,
    ) -> LakehouseSnapshotEvidence:
        return self._run(
            "delete",
            target,
            plan_sha256=plan_sha256,
            idempotency_key=idempotency_key,
            receipt_sha256=receipt_sha256,
        )


__all__ = ["DockerSparkIcebergProjectionProvider"]
