"""Finalize one retained real-feature staging Run from complete evidence.

M3-24 keeps the M3-22/M3-23 history immutable. It rebuilds the same bounded
real-feature execution in a retained local staging runtime, persists complete
DolphinScheduler dispatch authorization, requires a fresh material readback,
replaces the executor-created quality candidate with evidence created by the
independent evaluator, and then uses the existing output promoter and database
success finalizer.

Retained local staging is deliberately not production. Protected workload
identity, production storage, TLS/OIDC, durable catalog operations and tenant
attestation remain separate readiness gates.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid5

import pyarrow.parquet as pq
import shapely
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import create_engine, text

from . import metadata_fabric_active_metadata_scheduler_delivery as delivery
from . import metadata_fabric_object_store_active_metadata_promotion as m321
from . import metadata_fabric_real_feature_ingestion as m322
from . import metadata_fabric_real_feature_ledger_promotion as m323
from . import metadata_fabric_spark_object_store_interoperability as m310
from .dolphinscheduler_adapter import (
    DOLPHINSCHEDULER_API_PROFILE,
    DOLPHINSCHEDULER_SERVER_VERSION,
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerDefinitionBinding,
    DolphinSchedulerProfile,
    DolphinSchedulerWorkflowSpec,
    build_dolphinscheduler_binding_artifact,
    compile_dolphinscheduler_workflow,
)
from .platform_authorization import (
    build_approval_artifact,
    build_policy_decision_artifact,
    validate_run_authorization_evidence,
)
from .platform_contracts import (
    ApprovalRecord,
    Artifact,
    FrameworkAttemptObservation,
    PlatformDefinitionVersion,
    PlatformRun,
    PolicyDecision,
    QualityResult,
    ResourceVersion,
    RunPolicyReferences,
    RunStatus,
    RunSuccessEvidence,
    SubjectContext,
    canonical_json_bytes,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from .platform_gateway import (
    DefinitionRegistration,
    GatewayWriteResult,
    PlatformGateway,
)

CONTRACT_SCHEMA = "gda.retained_real_feature_terminal_success_contract.v1"
RETENTION_SCHEMA = "gda.retained_real_feature_material_observation.v1"
REQUEST_SCHEMA = "gda.retained_real_feature_execution_request.v1"
EVIDENCE_SCHEMA = "gda.retained_real_feature_terminal_success_evidence.v1"
VALIDATION_SCHEMA = "gda.retained_real_feature_terminal_success_validation.v1"
SOURCE_INGESTION_EVIDENCE_SHA256 = m323.SOURCE_EVIDENCE_SHA256
SOURCE_PROMOTION_EVIDENCE_SHA256 = (
    "f6efea5000791dec1716a8354a8e39a8425b083ca4d409f4bcb61f0e7e03580d"
)
TENANT = m322.TENANT
RUN_ID = m322.RUN_ID
DEFINITION_VERSION_ID = m322.DEFINITION_VERSION_ID
SOURCE_RESOURCE_VERSION_ID = m322.SOURCE_RESOURCE_VERSION_ID
OUTPUT_RESOURCE_VERSION_ID = m322.OUTPUT_RESOURCE_VERSION_ID
RUNNER = m322.WORKLOAD
QUALITY_EVALUATOR = m322.QUALITY_EVALUATOR
POLICY_EVALUATOR = "workload:real-feature-terminal-policy-evaluator"
APPROVER = "human:metadata-platform-owner"
TASK_CODE = 900000000000000024
CALLBACK_PATH = "/m3-24/execute"
CONTROL_POSTGRES_IMAGE = "postgres:16.10-bookworm"
CONTROL_POSTGRES_IMAGE_ID = (
    "sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74"
)
RETENTION_DAYS = 7
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_EVIDENCE_PATH = m322.DEFAULT_EVIDENCE_PATH
DEFAULT_PROMOTION_EVIDENCE_PATH = m323.DEFAULT_EVIDENCE_PATH
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-retained-real-feature-terminal-success-2026-07-31.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-retained-real-feature-terminal-success.sh"
)
MIGRATIONS = m323.MIGRATIONS
FALSE_CLAIMS = (
    "source_dataset_committed",
    "source_absolute_path_committed",
    "source_feature_payload_committed",
    "protected_workload_identity_verified",
    "durable_catalog_verified",
    "production_object_store_verified",
    "production_scheduler_verified",
    "production_ingestion_verified",
    "production_tenant_attestation_verified",
    "oidc_verified",
    "tls_verified",
    "production_ready",
)


class RetainedTerminalSuccessError(RuntimeError):
    """The retained real-feature terminal-success gate failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetainedExecutionRequest(_FrozenModel):
    request_schema: Literal[REQUEST_SCHEMA] = Field(default=REQUEST_SCHEMA, alias="schema")
    tenant_id: Literal[TENANT]
    run_id: UUID
    definition_version_id: UUID
    source_resource_version_id: UUID
    output_resource_version_id: UUID
    output_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingestion_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retention_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-z0-9-]+$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _valid_fingerprint(self) -> RetainedExecutionRequest:
        if (
            self.run_id != RUN_ID
            or self.definition_version_id != DEFINITION_VERSION_ID
            or self.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID
            or self.output_resource_version_id != OUTPUT_RESOURCE_VERSION_ID
        ):
            raise ValueError("retained execution request identity does not match")
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", by_alias=True, exclude={"request_sha256"})
        )
        if self.request_sha256 != expected:
            raise ValueError("retained execution request fingerprint does not match")
        return self


class RetainedMaterialObservation(_FrozenModel):
    observation_schema: Literal[RETENTION_SCHEMA] = Field(
        default=RETENTION_SCHEMA, alias="schema"
    )
    tenant_id: Literal[TENANT]
    run_id: UUID
    output_resource_version_id: UUID
    output_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storage_uri: str
    retention_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-z0-9-]+$")
    owner: Literal["team:metadata-platform"]
    namespace: str = Field(min_length=1, max_length=253)
    namespace_uid: str = Field(min_length=8, max_length=128)
    control_database_ref: str = Field(min_length=1, max_length=255)
    object_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: int
    feature_count: Literal[20]
    data_file_count: Literal[1]
    data_size_bytes: int = Field(gt=0)
    readable: Literal[True]
    source_payload_retained: Literal[False]
    materialized_at: datetime
    observed_at: datetime
    expires_at: datetime
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _consistent_retention(self) -> RetainedMaterialObservation:
        if (
            self.run_id != RUN_ID
            or self.output_resource_version_id != OUTPUT_RESOURCE_VERSION_ID
        ):
            raise ValueError("retained material observation identity does not match")
        parts = urlsplit(self.storage_uri)
        if parts.scheme != "s3" or not parts.netloc or parts.query or parts.fragment:
            raise ValueError("retained material must use a stable S3 URI")
        if not self.materialized_at < self.observed_at < self.expires_at:
            raise ValueError("retained material timestamps are not ordered")
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", by_alias=True, exclude={"observation_sha256"})
        )
        if self.observation_sha256 != expected:
            raise ValueError("retained material observation fingerprint does not match")
        return self


@dataclass(frozen=True)
class TerminalDefinitionBundle:
    registration: DefinitionRegistration
    definition: PlatformDefinitionVersion
    workflow: DolphinSchedulerWorkflowSpec


@dataclass(frozen=True)
class TerminalAuthorizationBundle:
    source_resource: Any
    source_version: ResourceVersion
    definition_registration: DefinitionRegistration
    output_resource: Any
    execution_plan: Artifact
    policy_decision: Artifact
    approval: Artifact
    run: PlatformRun


def _run_command(args: list[str], *, timeout: float = 180) -> str:
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RetainedTerminalSuccessError(
            f"local runtime command failed: {Path(args[0]).name}"
        )
    return completed.stdout.strip()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


class RetainedControlPostgres:
    """Own one labeled local PostgreSQL container and its retained volume."""

    def __init__(
        self,
        retention_id: str,
        *,
        expires_at: datetime,
        password: SecretStr,
    ) -> None:
        suffix = retention_id.removeprefix("m3-24-")[:24]
        self.retention_id = retention_id
        self.expires_at = expires_at
        self.password = password
        self.container_name = f"gda-m3-24-control-{suffix}"
        self.volume_name = f"gda-m3-24-control-{suffix}"
        self.host_port = _free_loopback_port()
        self.database_url = (
            "postgresql://postgres:"
            f"{password.get_secret_value()}@127.0.0.1:{self.host_port}/postgres"
        )
        self.created = False

    @property
    def database_ref(self) -> str:
        return f"docker:{self.container_name}/postgres"

    def start(self) -> dict[str, Any]:
        image_id = _run_command(
            ["docker", "image", "inspect", CONTROL_POSTGRES_IMAGE, "--format", "{{.Id}}"]
        )
        if image_id != CONTROL_POSTGRES_IMAGE_ID:
            raise RetainedTerminalSuccessError(
                "retained control PostgreSQL image identity drifted"
            )
        expiry = self.expires_at.isoformat().replace("+00:00", "Z")
        labels = [
            "--label",
            f"gda.retention-id={self.retention_id}",
            "--label",
            "gda.owner=team:metadata-platform",
            "--label",
            f"gda.expires-at={expiry}",
        ]
        _run_command(
            [
                "docker",
                "volume",
                "create",
                *labels,
                self.volume_name,
            ]
        )
        try:
            _run_command(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    self.container_name,
                    *labels,
                    "--publish",
                    f"127.0.0.1:{self.host_port}:5432",
                    "--mount",
                    f"source={self.volume_name},target=/var/lib/postgresql/data",
                    "--env",
                    f"POSTGRES_PASSWORD={self.password.get_secret_value()}",
                    CONTROL_POSTGRES_IMAGE,
                ]
            )
            self.created = True
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                engine = create_engine(self.database_url)
                try:
                    with engine.connect() as connection:
                        connection.execute(text("SELECT 1")).scalar_one()
                    break
                except Exception:
                    time.sleep(1)
                finally:
                    engine.dispose()
            else:
                raise RetainedTerminalSuccessError(
                    "retained control PostgreSQL did not become ready"
                )
            return self.observe()
        except BaseException:
            self.cleanup()
            raise

    def observe(self) -> dict[str, Any]:
        state = json.loads(
            _run_command(
                [
                    "docker",
                    "container",
                    "inspect",
                    self.container_name,
                    "--format",
                    "{{json .State}}",
                ]
            )
        )
        volume = json.loads(
            _run_command(
                [
                    "docker",
                    "volume",
                    "inspect",
                    self.volume_name,
                    "--format",
                    "{{json .}}",
                ]
            )
        )
        labels = volume.get("Labels") if isinstance(volume, dict) else None
        return {
            "database_ref": self.database_ref,
            "container_name": self.container_name,
            "volume_name": self.volume_name,
            "host_port": self.host_port,
            "container_running": state.get("Running") is True,
            "container_status": state.get("Status"),
            "volume_retained": isinstance(volume, dict),
            "retention_id": (labels or {}).get("gda.retention-id"),
            "owner": (labels or {}).get("gda.owner"),
            "expires_at": (labels or {}).get("gda.expires-at"),
            "credential_recorded": False,
        }

    def cleanup(self) -> None:
        if self.created:
            subprocess.run(
                ["docker", "rm", "--force", self.container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.created = False
        subprocess.run(
            ["docker", "volume", "rm", self.volume_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )


def _authorization_fingerprint(bundle: TerminalAuthorizationBundle) -> str:
    return canonical_json_fingerprint(
        {
            "run": bundle.run.model_dump(mode="json"),
            "execution_plan": bundle.execution_plan.model_dump(mode="json"),
            "policy_decision": bundle.policy_decision.model_dump(mode="json"),
            "approval": bundle.approval.model_dump(mode="json"),
        }
    )


class RetainedRealFeatureExecutor:
    """Perform the one provider mutation invoked by DolphinScheduler."""

    def __init__(
        self,
        request: RetainedExecutionRequest,
        profile: m322.RealFeatureIngestionProfile,
        plan: m322.RealFeatureIngestionPlan,
        source: Mapping[str, Any],
        runtime: m310.IsolatedSparkObjectStoreRuntime,
        rehearsal: m321.ObjectStoreProjectionRehearsal,
        *,
        endpoint_url: str,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
        authorization_sha256: str,
    ) -> None:
        self.request = request
        self.profile = profile
        self.plan = plan
        self.source = source
        self.runtime = runtime
        self.rehearsal = rehearsal
        self.endpoint_url = endpoint_url
        self.object_store_user = object_store_user
        self.object_store_material = object_store_material
        self.authorization_sha256 = authorization_sha256
        self.request_count = 0
        self.table_create: dict[str, Any] | None = None
        self.spark: dict[str, Any] | None = None
        self.store: dict[str, Any] | None = None
        self.output_contracts: dict[str, Any] | None = None
        self.materialized_at: datetime | None = None
        self.source_input_removed = False
        self.error_type: str | None = None
        self.error_stage: str | None = None
        self.stage = "waiting_for_request"

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.request_count += 1
        try:
            observed = RetainedExecutionRequest.model_validate(payload)
            if observed != self.request or self.request_count != 1:
                raise RetainedTerminalSuccessError(
                    "retained executor accepts exactly one compiled request"
                )
            self.stage = "creating_target_table"
            self.table_create = m322.create_target_table(
                self.rehearsal, self.profile, self.plan
            )
            input_payload = {
                **_mapping(self.source.get("payload")),
                "plan_sha256": self.plan.ingestion_plan_sha256,
                "authorization_sha256": self.authorization_sha256,
            }
            try:
                self.stage = "running_spark_ingestion"
                self.spark = m322._run_spark_ingestion(
                    self.runtime, input_payload=input_payload
                )
                self.stage = "observing_object_store"
                self.store = m322.observe_ingested_table(
                    self.runtime,
                    self.profile,
                    endpoint_url=self.endpoint_url,
                    object_store_user=self.object_store_user,
                    object_store_material=self.object_store_material,
                )
            finally:
                self.runtime.kubectl.run(
                    [
                        "-n",
                        self.runtime.profile.cluster.rehearsal_namespace,
                        "delete",
                        "configmap",
                        "real-feature-ingestion-input",
                        "--ignore-not-found=true",
                        "--wait=true",
                    ],
                    label="retained real feature source input cleanup",
                )
                self.source_input_removed = (
                    self.runtime.kubectl.get_json(
                        [
                            "-n",
                            self.runtime.profile.cluster.rehearsal_namespace,
                            "get",
                            "configmap",
                            "real-feature-ingestion-input",
                        ],
                        allow_not_found=True,
                        label="retained source input absence verification",
                    )
                    is None
                )
            assert self.spark is not None and self.store is not None
            self.stage = "validating_provider_readback"
            errors = m322._spark_errors(
                self.spark,
                self.plan,
                {"projection": _mapping(self.source.get("projection"))},
                expected_authorization_sha256=self.authorization_sha256,
            )
            errors.extend(m322._object_store_errors(self.store, self.spark, self.profile))
            if errors or not self.source_input_removed:
                raise RetainedTerminalSuccessError(
                    "scheduler-triggered retained ingestion readback failed"
                )
            self.materialized_at = datetime.now(UTC)
            self.stage = "building_output_contracts"
            self.output_contracts = m322.build_output_contracts(
                self.plan,
                self.spark,
                self.store,
                created_at=self.materialized_at,
            )
            self.stage = "completed"
            return {
                "schema": "gda.retained_real_feature_execution_response.v1",
                "status": "materialized_and_replayed",
                "request_sha256": self.request.request_sha256,
                "output_content_sha256": self.plan.output_content_sha256,
                "source_payload_retained": False,
            }
        except Exception as exc:
            self.error_type = type(exc).__name__
            self.error_stage = self.stage
            raise


class RetainedExecutionServer:
    def __init__(self) -> None:
        self.executor: RetainedRealFeatureExecutor | None = None
        self.started = False
        self.cleanup_verified = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != CALLBACK_PATH:
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 32768 or owner.executor is None:
                        raise ValueError("retained execution request is unavailable")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("retained execution request must be an object")
                    response = owner.executor.execute(payload)
                except Exception:
                    self.send_error(500)
                    return
                body = json.dumps(
                    response,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self._server = HTTPServer(("0.0.0.0", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="gda-m3-24-retained-real-feature-executor",
            daemon=True,
        )

    @property
    def callback_url(self) -> str:
        return f"http://host.docker.internal:{self._server.server_port}{CALLBACK_PATH}"

    def start(self) -> None:
        if self.executor is None:
            raise RetainedTerminalSuccessError(
                "retained execution server requires an executor"
            )
        self._thread.start()
        self.started = True

    def stop(self) -> bool:
        if self.started:
            self._server.shutdown()
            self._thread.join(timeout=30)
        self._server.server_close()
        self.cleanup_verified = not self._thread.is_alive()
        return self.cleanup_verified


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RetainedTerminalSuccessError(f"{path.name} must contain an object")
    return value


def _file_record(path: Path) -> dict[str, str | None]:
    relative = path.resolve().relative_to(REPO_ROOT).as_posix()
    return {
        "path": relative,
        "sha256": (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        ),
    }


def _mark_namespace_retained(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    *,
    retention_id: str,
    expires_at: datetime,
) -> dict[str, Any]:
    namespace = runtime.profile.cluster.rehearsal_namespace
    expiry = expires_at.isoformat().replace("+00:00", "Z")
    runtime.kubectl.run(
        [
            "label",
            "namespace",
            namespace,
            f"gda.gisdataagent.io/retention-id={retention_id}",
            "gda.gisdataagent.io/owner=metadata-platform",
            "--overwrite",
        ],
        label="retained namespace ownership labels",
    )
    runtime.kubectl.run(
        [
            "annotate",
            "namespace",
            namespace,
            f"gda.gisdataagent.io/expires-at={expiry}",
            "gda.gisdataagent.io/cleanup-command="
            "metadata-fabric-retained-real-feature-terminal-success cleanup",
            "--overwrite",
        ],
        label="retained namespace lifecycle annotations",
    )
    observed = runtime.kubectl.get_json(
        ["get", "namespace", namespace], label="retained namespace readback"
    )
    assert observed is not None
    metadata = _mapping(observed.get("metadata"))
    labels = _mapping(metadata.get("labels"))
    annotations = _mapping(metadata.get("annotations"))
    result = {
        "name": metadata.get("name"),
        "uid": metadata.get("uid"),
        "retention_id": labels.get("gda.gisdataagent.io/retention-id"),
        "owner": labels.get("gda.gisdataagent.io/owner"),
        "expires_at": annotations.get("gda.gisdataagent.io/expires-at"),
        "cleanup_command_recorded": bool(
            annotations.get("gda.gisdataagent.io/cleanup-command")
        ),
    }
    if result != {
        "name": namespace,
        "uid": metadata.get("uid"),
        "retention_id": retention_id,
        "owner": "metadata-platform",
        "expires_at": expiry,
        "cleanup_command_recorded": True,
    }:
        raise RetainedTerminalSuccessError(
            "retained namespace lifecycle readback drifted"
        )
    return result


def independently_evaluate_retained_parquet(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    profile: m322.RealFeatureIngestionProfile,
    plan: m322.RealFeatureIngestionPlan,
    source: Mapping[str, Any],
    store: Mapping[str, Any],
    *,
    endpoint_url: str,
    object_store_user: SecretStr,
    object_store_material: SecretStr,
) -> dict[str, Any]:
    data_keys = list(store.get("data_keys") or [])
    if len(data_keys) != 1:
        raise RetainedTerminalSuccessError(
            "independent evaluator requires exactly one Parquet data file"
        )
    client = runtime._s3_client(
        endpoint_url=endpoint_url,
        object_store_user=object_store_user,
        object_store_material=object_store_material,
    )
    try:
        response = client.get_object(Bucket=profile.target.bucket, Key=data_keys[0])
        body = response["Body"].read()
    finally:
        client.close()
    table = pq.read_table(io.BytesIO(body))
    expected_columns = list(m322.SPARK_COLUMNS)
    if table.column_names != expected_columns or table.num_rows != plan.expected_feature_count:
        raise RetainedTerminalSuccessError(
            "independent Parquet schema or feature count drifted"
        )
    columns = table.to_pydict()
    row_hashes: list[str] = []
    valid_count = 0
    non_empty_count = 0
    positive_area_count = 0
    bbox_match_count = 0
    geometry_z_count = 0
    for index in range(table.num_rows):
        geometry_bytes = bytes(columns["geometry"][index])
        geometry = shapely.from_wkb(geometry_bytes)
        valid_count += int(bool(shapely.is_valid(geometry)))
        non_empty_count += int(not bool(shapely.is_empty(geometry)))
        positive_area_count += int(float(shapely.area(geometry)) > 0)
        geometry_z_count += int(bool(shapely.has_z(geometry)))
        min_x, min_y, max_x, max_y = shapely.bounds(geometry)
        expected_bounds = (
            float(columns["min_x"][index]),
            float(columns["min_y"][index]),
            float(columns["max_x"][index]),
            float(columns["max_y"][index]),
        )
        bbox_match_count += int(
            all(
                abs(float(actual) - expected) <= 1e-12
                for actual, expected in zip(
                    (min_x, min_y, max_x, max_y), expected_bounds, strict=True
                )
            )
        )
        stable = {
            "BSM": str(columns["BSM"][index]),
            "geometry_wkb_hex": geometry_bytes.hex(),
            "srid": int(columns["srid"][index]),
            "min_x": expected_bounds[0],
            "min_y": expected_bounds[1],
            "max_x": expected_bounds[2],
            "max_y": expected_bounds[3],
        }
        row_hash = canonical_json_fingerprint(stable)
        if row_hash != str(columns["row_sha256"][index]):
            raise RetainedTerminalSuccessError(
                "independent Parquet row fingerprint drifted"
            )
        row_hashes.append(row_hash)
    projection = _mapping(source.get("projection"))
    expected_hashes = sorted(str(value) for value in projection.get("row_sha256") or [])
    metrics = {
        "feature_count": table.num_rows,
        "unique_bsm_count": len(set(str(value) for value in columns["BSM"])),
        "valid_geometry_count": valid_count,
        "non_empty_geometry_count": non_empty_count,
        "geometry_z_count": geometry_z_count,
        "srid_match_count": sum(int(value) == 4490 for value in columns["srid"]),
        "positive_area_count": positive_area_count,
        "bbox_match_count": bbox_match_count,
        "row_fingerprint_match_count": sum(
            left == right
            for left, right in zip(sorted(row_hashes), expected_hashes, strict=True)
        ),
    }
    if any(value != plan.expected_feature_count for value in metrics.values()):
        raise RetainedTerminalSuccessError(
            "independent retained Parquet quality gate failed"
        )
    return {
        "metrics": metrics,
        "data_key_sha256": hashlib.sha256(data_keys[0].encode()).hexdigest(),
        "data_body_sha256": hashlib.sha256(body).hexdigest(),
        "data_size_bytes": len(body),
        "row_set_sha256": plan.row_set_sha256,
        "feature_payload_recorded": False,
        "identifier_values_recorded": False,
        "geometry_values_recorded": False,
    }


def build_execution_request(
    plan: m322.RealFeatureIngestionPlan, *, retention_id: str
) -> RetainedExecutionRequest:
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_VERSION_ID,
        "source_resource_version_id": SOURCE_RESOURCE_VERSION_ID,
        "output_resource_version_id": OUTPUT_RESOURCE_VERSION_ID,
        "output_content_sha256": plan.output_content_sha256,
        "ingestion_plan_sha256": plan.ingestion_plan_sha256,
        "retention_id": retention_id,
    }
    stable = {
        "schema": REQUEST_SCHEMA,
        **{
            key: str(value) if isinstance(value, UUID) else value
            for key, value in values.items()
        },
    }
    return RetainedExecutionRequest(
        **values,
        request_sha256=canonical_json_fingerprint(stable),
    )


def _workflow_document(
    callback_url: str, request: RetainedExecutionRequest
) -> dict[str, Any]:
    request_json = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    quoted_request = request_json.replace("'", "'\"'\"'")
    quoted_url = callback_url.replace("'", "'\"'\"'")
    raw_script = (
        "curl --fail --silent --show-error --max-time 1200 "
        "--request POST --header 'Content-Type: application/json' "
        f"--data-binary '{quoted_request}' '{quoted_url}'"
    )
    task = {
        "code": TASK_CODE,
        "name": "ingest_retained_real_feature_slice",
        "version": 1,
        "description": "Ingest one authorized real feature slice into retained staging",
        "delayTime": 0,
        "taskType": "SHELL",
        "taskParams": {
            "localParams": [],
            "rawScript": raw_script,
            "resourceList": [],
            "dependence": {},
            "conditionResult": {"successNode": [], "failedNode": []},
            "waitStartTimeout": {},
        },
        "flag": "YES",
        "taskPriority": "MEDIUM",
        "workerGroup": "default",
        "environmentCode": -1,
        "failRetryTimes": 0,
        "failRetryInterval": 1,
        "timeoutFlag": "OPEN",
        "timeoutNotifyStrategy": "WARN",
        "timeout": 1260,
    }
    return {
        "dolphinscheduler": {
            "name": "gda_retained_real_feature_terminal_success_v1",
            "description": "Authorized retained real-feature staging ingestion",
            "task_definitions": [task],
            "task_relations": [
                {
                    "name": "",
                    "preTaskCode": 0,
                    "preTaskVersion": 0,
                    "postTaskCode": TASK_CODE,
                    "postTaskVersion": 1,
                    "conditionType": "NONE",
                    "conditionParams": {},
                }
            ],
            "locations": [{"taskCode": TASK_CODE, "x": 160, "y": 100}],
            "global_params": [],
            "timeout_seconds": 1320,
            "execution_type": "PARALLEL",
        }
    }


def build_terminal_definition(
    callback_url: str,
    request: RetainedExecutionRequest,
    *,
    created_at: datetime,
) -> TerminalDefinitionBundle:
    definition_urn = f"gda://{TENANT}/definition/real-feature-ingestion"
    document = _workflow_document(callback_url, request)
    input_contract = {
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "semantic_type": "gis.cultural_districts",
        "execution_request_sha256": request.request_sha256,
    }
    output_contract = {
        "output_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
        "retained_staging_material": True,
        "independent_quality_evidence": True,
        "source_to_output_lineage": True,
        "platform_run_terminal_success": True,
    }
    definition_sha = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id=m322.ACTION,
        portability_class="provider_native",
        definition_document=document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    resource = m323.Resource(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_kind="definition",
        authority_system="gda",
        authority_locator="definition/real-feature-ingestion",
        owner_ref="team:metadata-platform",
    )
    version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=definition_urn,
        resource_version_id=DEFINITION_VERSION_ID,
        version_key="dolphinscheduler-3.4.2-retained-real-feature-v1",
        content_sha256=definition_sha,
        authority_version_ref={
            "api_profile": DOLPHINSCHEDULER_API_PROFILE,
            "server_version": DOLPHINSCHEDULER_SERVER_VERSION,
            "execution_request_sha256": request.request_sha256,
        },
        created_by="workload:metadata-definition-registrar",
        created_at=created_at,
    )
    definition = PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=definition_urn,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        capability_id=m322.ACTION,
        portability_class="provider_native",
        definition_document=document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=definition_sha,
    )
    registration = DefinitionRegistration(
        resource=resource,
        resource_version=version,
        definition=definition,
    )
    return TerminalDefinitionBundle(
        registration=registration,
        definition=definition,
        workflow=compile_dolphinscheduler_workflow(definition),
    )


def build_terminal_authorization(
    source: Mapping[str, Any],
    definition_bundle: TerminalDefinitionBundle,
    binding: DolphinSchedulerDefinitionBinding,
    *,
    authorized_at: datetime,
) -> TerminalAuthorizationBundle:
    base_promotion = m323.build_promotion(source)
    prerequisites = m323.build_prerequisites(source, base_promotion)
    if (
        binding.definition_version_id != DEFINITION_VERSION_ID
        or binding.compiled_sha256 != definition_bundle.workflow.compiled_sha256
    ):
        raise RetainedTerminalSuccessError(
            "DolphinScheduler binding does not match the terminal definition"
        )
    execution_plan = build_dolphinscheduler_binding_artifact(
        binding,
        created_by=RUNNER,
        created_at=authorized_at - timedelta(seconds=3),
    )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id=RUNNER.removeprefix("workload:"),
        subject_type="workload",
        roles=("spatial_ingestion_executor",),
        purpose="ingest and terminalize one retained real feature staging slice",
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_VERSION_ID,
        resource_version_ids=(DEFINITION_VERSION_ID, SOURCE_RESOURCE_VERSION_ID),
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref="policy://gda/metadata-fabric/retained-real-feature/v1",
        evaluator_subject=POLICY_EVALUATOR,
        requires_approval=True,
        decided_at=authorized_at - timedelta(seconds=3),
        expires_at=authorized_at + timedelta(days=30),
    )
    policy = build_policy_decision_artifact(decision)
    approval = build_approval_artifact(
        ApprovalRecord(
            tenant_id=TENANT,
            run_id=RUN_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            policy_decision_artifact_id=policy.artifact_id,
            policy_decision_sha256=policy.content_sha256,
            verdict="approved",
            approver_subject=APPROVER,
            reason="Approve one bounded retained local staging ingestion.",
            decided_at=authorized_at - timedelta(seconds=2),
            expires_at=authorized_at + timedelta(days=7),
        )
    )
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            {
                "binding_name": "source_dataset",
                "resource_version_id": SOURCE_RESOURCE_VERSION_ID,
                "semantic_type": "gis.cultural_districts",
            },
        ),
        idempotency_key=(
            "retained-real-feature-ingestion:"
            f"{base_promotion.output_resource_version.content_sha256}"
        ),
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy.artifact_id,
            approval_artifact_id=approval.artifact_id,
        ),
        config_fingerprint=definition_bundle.definition.definition_sha256,
        submitted_at=authorized_at - timedelta(seconds=1),
    )
    validate_run_authorization_evidence(
        run,
        policy,
        approval,
        execution_plan,
        at=authorized_at,
        expected_action="dolphinscheduler.dispatch",
    )
    return TerminalAuthorizationBundle(
        source_resource=prerequisites.source_resource,
        source_version=prerequisites.source_version,
        definition_registration=definition_bundle.registration,
        output_resource=prerequisites.output_resource,
        execution_plan=execution_plan,
        policy_decision=policy,
        approval=approval,
        run=run,
    )


def build_retained_material_observation(**values: Any) -> RetainedMaterialObservation:
    stable = {
        "schema": RETENTION_SCHEMA,
        **{
            key: value.isoformat().replace("+00:00", "Z")
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
            for key, value in values.items()
        },
    }
    return RetainedMaterialObservation(
        **values,
        observation_sha256=canonical_json_fingerprint(stable),
    )


def build_terminal_promotion(
    source: Mapping[str, Any],
    retention: RetainedMaterialObservation,
) -> m323.RunOutputLedgerPromotion:
    base = m323.build_promotion(source)
    if (
        retention.output_content_sha256
        != base.output_resource_version.content_sha256
        or retention.storage_uri != base.output_artifact.storage_uri
        or retention.row_set_sha256 != base.output_artifact.manifest.get("row_set_sha256")
        or retention.feature_count != base.output_artifact.manifest.get("feature_count")
    ):
        raise RetainedTerminalSuccessError(
            "retained material does not bind the checked real-feature output"
        )
    output_version = base.output_resource_version.model_copy(
        update={
            "authority_version_ref": {
                **base.output_resource_version.authority_version_ref,
                "snapshot_id": retention.snapshot_id,
                "retention_id": retention.retention_id,
                "namespace_uid": retention.namespace_uid,
                "object_inventory_sha256": retention.object_inventory_sha256,
                "retention_expires_at": retention.expires_at.isoformat(),
            },
            "created_at": retention.materialized_at,
        }
    )
    output_artifact = base.output_artifact.model_copy(
        update={
            "manifest": {
                **base.output_artifact.manifest,
                "snapshot_id": retention.snapshot_id,
                "data_file_count": retention.data_file_count,
                "retention_id": retention.retention_id,
                "retention_observation_sha256": retention.observation_sha256,
                "retention_expires_at": retention.expires_at.isoformat(),
            },
            "size_bytes": retention.data_size_bytes,
            "created_at": retention.materialized_at,
        }
    )
    metrics = {
        **base.quality_result.metrics,
        "independent_material_readback": True,
        "retained_feature_count": retention.feature_count,
        "retained_data_file_count": retention.data_file_count,
        "retained_row_set_sha256": retention.row_set_sha256,
    }
    quality_manifest = {
        "schema": RETENTION_SCHEMA,
        "rule_version_ref": "quality://gda/spatial/retained-real-feature/v1",
        "metrics": metrics,
        "retention_observation": retention.model_dump(mode="json", by_alias=True),
    }
    quality_artifact_id = uuid5(
        RUN_ID, f"retained-quality-evidence:{retention.observation_sha256}"
    )
    quality_artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=quality_artifact_id,
        artifact_key=f"retained-real-feature-quality:{quality_artifact_id}",
        artifact_role="evidence",
        storage_uri=(
            f"postgresql://gda-control/quality-evidence/{TENANT}/{quality_artifact_id}"
        ),
        media_type="application/vnd.gda.retained-real-feature-quality+json",
        content_sha256=canonical_json_fingerprint(quality_manifest),
        size_bytes=len(canonical_json_bytes(quality_manifest)),
        run_id=RUN_ID,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        manifest=quality_manifest,
        created_by=QUALITY_EVALUATOR,
        created_at=retention.observed_at,
    )
    quality_sha = quality_result_fingerprint(
        tenant_id=TENANT,
        run_id=RUN_ID,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        rule_version_ref="quality://gda/spatial/retained-real-feature/v1",
        verdict="passed",
        metrics=metrics,
        evidence_artifact_id=quality_artifact_id,
        evaluated_by=QUALITY_EVALUATOR,
        evaluated_at=retention.observed_at,
    )
    quality = QualityResult(
        tenant_id=TENANT,
        quality_result_id=uuid5(RUN_ID, f"retained-quality:{quality_sha}"),
        run_id=RUN_ID,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        rule_version_ref="quality://gda/spatial/retained-real-feature/v1",
        verdict="passed",
        metrics=metrics,
        evidence_artifact_id=quality_artifact_id,
        result_sha256=quality_sha,
        evaluated_by=QUALITY_EVALUATOR,
        evaluated_at=retention.observed_at,
    )
    lineage_facets = {
        **base.lineage_event.facets,
        "retention_id": retention.retention_id,
        "retention_observation_sha256": retention.observation_sha256,
    }
    output_artifact = output_artifact.model_copy(
        update={"manifest": {**output_artifact.manifest, **lineage_facets}}
    )
    lineage_values = {
        "event_type": base.lineage_event.event_type.value,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "target_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
        "run_id": str(RUN_ID),
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "artifact_id": str(output_artifact.artifact_id),
        "producer": RUNNER,
        "facets": lineage_facets,
        "occurred_at": retention.materialized_at.isoformat().replace("+00:00", "Z"),
    }
    lineage_sha = canonical_json_fingerprint(lineage_values)
    lineage = base.lineage_event.model_copy(
        update={
            "lineage_event_id": uuid5(RUN_ID, f"retained-lineage:{lineage_sha}"),
            "event_sha256": lineage_sha,
            "facets": lineage_facets,
            "occurred_at": retention.materialized_at,
        }
    )
    return m323.RunOutputLedgerPromotion(
        authority_resource=base.authority_resource,
        output_resource_version=output_version,
        output_artifact=output_artifact,
        quality_evidence_artifact=quality_artifact,
        quality_result=quality,
        lineage_event=lineage,
    )


def register_terminal_authorization(
    gateway: PlatformGateway, bundle: TerminalAuthorizationBundle
) -> None:
    gateway.register_resource(bundle.source_resource)
    gateway.register_resource_version(bundle.source_version)
    gateway.register_definition(bundle.definition_registration)
    gateway.register_resource(bundle.output_resource)
    for artifact in (
        bundle.execution_plan,
        bundle.policy_decision,
        bundle.approval,
    ):
        gateway.record_artifact(artifact)
    gateway.submit_run(bundle.run)


def build_success_evidence(
    promotion: m323.RunOutputLedgerPromotion,
    observation: FrameworkAttemptObservation,
) -> RunSuccessEvidence:
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "attempt_observation_id": observation.observation_id,
        "output_artifact_id": promotion.output_artifact.artifact_id,
        "quality_result_id": promotion.quality_result.quality_result_id,
        "lineage_event_id": promotion.lineage_event.lineage_event_id,
    }
    return RunSuccessEvidence(
        **values,
        evidence_sha256=run_success_evidence_fingerprint(**values),
    )


class RetainedTerminalSuccessCoordinator:
    """Gate promotion/finalization on a fresh, independently verified readback."""

    def __init__(
        self,
        gateway: PlatformGateway,
        *,
        material_probe: Callable[[RetainedMaterialObservation], bool],
    ) -> None:
        self.gateway = gateway
        self.material_probe = material_probe
        self.promoter = m323.RunOutputLedgerPromoter(gateway)

    def _verify_terminal_replay(
        self, promotion: m323.RunOutputLedgerPromotion
    ) -> GatewayWriteResult:
        with self.gateway._transaction(TENANT) as connection:
            stored = m323.RunOutputLedgerPromotion(
                authority_resource=self.gateway._load_resource(
                    connection,
                    TENANT,
                    promotion.authority_resource.resource_urn,
                ),
                output_resource_version=self.gateway._load_resource_version(
                    connection,
                    TENANT,
                    promotion.output_resource_version.resource_version_id,
                ),
                output_artifact=self.gateway._load_artifact(
                    connection,
                    TENANT,
                    promotion.output_artifact.artifact_id,
                ),
                quality_evidence_artifact=self.gateway._load_artifact(
                    connection,
                    TENANT,
                    promotion.quality_evidence_artifact.artifact_id,
                ),
                quality_result=self.gateway._load_quality_result(
                    connection,
                    TENANT,
                    promotion.quality_result.quality_result_id,
                ),
                lineage_event=self.gateway._load_lineage(
                    connection,
                    TENANT,
                    promotion.lineage_event.lineage_event_id,
                ),
            )
        if stored != promotion:
            raise RetainedTerminalSuccessError(
                "terminal replay facts differ from the successful verdict"
            )
        return GatewayWriteResult(stored, False)

    def finalize(
        self,
        promotion: m323.RunOutputLedgerPromotion,
        retention: RetainedMaterialObservation,
        observation: FrameworkAttemptObservation,
        *,
        reason: str = "retained staging output passed terminal evidence gate",
    ) -> tuple[GatewayWriteResult, PlatformRun]:
        if (
            observation.tenant_id != TENANT
            or observation.run_id != RUN_ID
            or observation.framework_kind.value != "dolphinscheduler"
            or observation.observed_state.lower() != "success"
            or observation.evidence.get("provider_state") != "SUCCESS"
            or observation.evidence.get("api_profile")
            != DOLPHINSCHEDULER_API_PROFILE
            or observation.evidence.get("server_version")
            != DOLPHINSCHEDULER_SERVER_VERSION
            or observation.observation_sha256
            != canonical_json_fingerprint(observation.evidence)
        ):
            raise RetainedTerminalSuccessError(
                "terminal finalization requires a DolphinScheduler success observation"
            )
        if (
            promotion.quality_evidence_artifact.created_by != QUALITY_EVALUATOR
            or promotion.quality_result.evaluated_by != QUALITY_EVALUATOR
            or promotion.quality_result.evidence_artifact_id
            != promotion.quality_evidence_artifact.artifact_id
            or promotion.quality_evidence_artifact.manifest.get(
                "retention_observation"
            )
            != retention.model_dump(mode="json", by_alias=True)
        ):
            raise RetainedTerminalSuccessError(
                "quality evidence was not created by the independent evaluator"
            )
        if not self.material_probe(retention):
            raise RetainedTerminalSuccessError(
                "retained staging material is absent, expired, or unreadable"
            )
        run = self.gateway.get_run(TENANT, RUN_ID)
        if run.status == RunStatus.SUCCEEDED:
            promoted = self._verify_terminal_replay(promotion)
        elif run.status in {RunStatus.RUNNING, RunStatus.RECONCILING}:
            promoted = self.promoter.promote(promotion)
        else:
            raise RetainedTerminalSuccessError(
                "terminal finalization requires a running or reconciling Run"
            )
        succeeded = self.gateway.finalize_run_success(
            build_success_evidence(promotion, observation),
            expected_state_version=run.state_version,
            actor_subject=RUNNER,
            reason=reason,
        )
        return promoted, succeeded


def _live_material_probe(
    retention: RetainedMaterialObservation,
    *,
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    profile: m322.RealFeatureIngestionProfile,
    control: RetainedControlPostgres,
    endpoint_url: str,
    object_store_user: SecretStr,
    object_store_material: SecretStr,
) -> bool:
    if datetime.now(UTC) >= retention.expires_at:
        return False
    namespace = runtime.kubectl.get_json(
        ["get", "namespace", retention.namespace],
        allow_not_found=True,
        label="terminal retained namespace probe",
    )
    if namespace is None:
        return False
    metadata = _mapping(namespace.get("metadata"))
    labels = _mapping(metadata.get("labels"))
    annotations = _mapping(metadata.get("annotations"))
    if (
        metadata.get("uid") != retention.namespace_uid
        or labels.get("gda.gisdataagent.io/retention-id") != retention.retention_id
        or labels.get("gda.gisdataagent.io/owner") != "metadata-platform"
        or annotations.get("gda.gisdataagent.io/expires-at")
        != retention.expires_at.isoformat().replace("+00:00", "Z")
    ):
        return False
    source_input = runtime.kubectl.get_json(
        [
            "-n",
            retention.namespace,
            "get",
            "configmap",
            "real-feature-ingestion-input",
        ],
        allow_not_found=True,
        label="terminal retained source input probe",
    )
    if source_input is not None:
        return False
    control_state = control.observe()
    if (
        control_state.get("database_ref") != retention.control_database_ref
        or control_state.get("container_running") is not True
        or control_state.get("volume_retained") is not True
        or control_state.get("retention_id") != retention.retention_id
    ):
        return False
    store = m322.observe_ingested_table(
        runtime,
        profile,
        endpoint_url=endpoint_url,
        object_store_user=object_store_user,
        object_store_material=object_store_material,
    )
    latest = _mapping(store.get("latest_metadata"))
    return (
        store.get("object_inventory_sha256") == retention.object_inventory_sha256
        and latest.get("body_sha256") == retention.metadata_body_sha256
        and latest.get("current_snapshot_id") == retention.snapshot_id
        and len(store.get("data_keys") or []) == retention.data_file_count
    )


def _ledger_counts(engine: Any) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM gda_control.artifact
                   WHERE tenant_id = :tenant_id) AS artifacts,
                  (SELECT count(*) FROM gda_control.artifact
                   WHERE tenant_id = :tenant_id
                     AND artifact_role = 'execution_plan') AS execution_plans,
                  (SELECT count(*) FROM gda_control.artifact
                   WHERE tenant_id = :tenant_id
                     AND media_type = 'application/vnd.gda.policy-decision+json')
                    AS policy_decisions,
                  (SELECT count(*) FROM gda_control.artifact
                   WHERE tenant_id = :tenant_id
                     AND media_type = 'application/vnd.gda.approval+json') AS approvals,
                  (SELECT count(*) FROM gda_control.artifact
                   WHERE tenant_id = :tenant_id
                     AND run_id = :run_id
                     AND created_by = :quality_evaluator) AS evaluator_evidence,
                  (SELECT count(*) FROM gda_control.framework_attempt_observation
                   WHERE tenant_id = :tenant_id AND run_id = :run_id) AS attempts,
                  (SELECT count(*) FROM gda_control.quality_result
                   WHERE tenant_id = :tenant_id AND run_id = :run_id) AS quality_results,
                  (SELECT count(*) FROM gda_control.lineage_event
                   WHERE tenant_id = :tenant_id AND run_id = :run_id) AS lineage_events,
                  (SELECT count(*) FROM gda_control.platform_run_event
                   WHERE tenant_id = :tenant_id AND run_id = :run_id) AS run_events
                """
            ),
            {
                "tenant_id": TENANT,
                "run_id": RUN_ID,
                "quality_evaluator": QUALITY_EVALUATOR,
            },
        ).mappings().one()
    return {key: int(value) for key, value in row.items()}


def run_live_rehearsal(
    *,
    profile_path: Path,
    shapefile_path: Path,
    ogrinfo_path: Path,
    proj_data_path: Path | None,
    scheduler_admin_password: SecretStr,
    scheduler_readiness_timeout_seconds: float = 240,
    terminal_timeout_seconds: float = 1500,
) -> dict[str, Any]:
    contract = build_contract_report()
    if contract.get("status") != "valid":
        raise RetainedTerminalSuccessError("M3-24 static contract is invalid")
    profile = m322.load_profile(profile_path)
    predecessor, runtime_profile = m322._load_dependencies(profile)
    source = m322.build_source_input(
        profile,
        predecessor,
        shapefile_path=shapefile_path,
        ogrinfo_path=ogrinfo_path,
        proj_data_path=proj_data_path,
    )
    checked_source = _load_json_object(DEFAULT_SOURCE_EVIDENCE_PATH)
    if (
        source.get("inventory") != checked_source.get("dataset_bundle")
        or source.get("projection") != checked_source.get("source_projection")
    ):
        raise RetainedTerminalSuccessError(
            "live source does not match the checked M3-22 dataset projection"
        )

    retention_id = f"m3-24-{secrets.token_hex(8)}"
    started_at = datetime.now(UTC)
    expires_at = started_at + timedelta(days=RETENTION_DAYS)
    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    object_store_user = SecretStr("gda" + secrets.token_hex(8))
    object_store_material = SecretStr(secrets.token_urlsafe(32))
    control_password = SecretStr(secrets.token_urlsafe(32))
    runtime = m310.IsolatedSparkObjectStoreRuntime(runtime_profile)
    control = RetainedControlPostgres(
        retention_id,
        expires_at=expires_at,
        password=control_password,
    )
    server = RetainedExecutionServer()
    object_forward: Any = None
    gravitino_forward: Any = None
    rehearsal: m321.ObjectStoreProjectionRehearsal | None = None
    engine: Any = None
    client: DolphinSchedulerClient | None = None
    retained = False
    object_forward_stopped = False
    gravitino_forward_stopped = False
    namespace_retention: dict[str, Any] | None = None
    control_state: dict[str, Any] | None = None
    scheduler: delivery.EphemeralDolphinScheduler | None = None
    try:
        initial_runtime = runtime.start(
            admin_material=admin_material,
            database_material=database_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        namespace_retention = _mark_namespace_retained(
            runtime,
            retention_id=retention_id,
            expires_at=expires_at,
        )
        cluster = runtime.kubectl.get_json(
            ["get", "namespace", "kube-system"],
            label="retained real feature cluster identity",
        )
        assert cluster is not None
        cluster_uid = str(_mapping(_mapping(cluster).get("metadata")).get("uid"))
        runtime_binding = m321._provider_runtime_binding(
            initial_runtime,
            cluster_uid=cluster_uid,
            target=profile.target,
        )
        plan = m322.build_ingestion_plan(
            profile, predecessor, source, runtime_binding
        )
        request = build_execution_request(plan, retention_id=retention_id)
        definition_bundle = build_terminal_definition(
            server.callback_url,
            request,
            created_at=datetime.now(UTC),
        )

        object_forward = m321.provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.object_store_service,
            target_port=runtime_profile.runtime.object_store_service_port,
        )
        object_forward.start()
        endpoint_url = f"http://127.0.0.1:{object_forward.local_port}"
        object_store_prepared = runtime.prepare_object_store(
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        gravitino_forward = m321.provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.service,
            target_port=runtime_profile.runtime.gravitino_service_port,
        )
        gravitino_forward.start()
        rehearsal = m321.ObjectStoreProjectionRehearsal(
            base_url=f"http://127.0.0.1:{gravitino_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        bootstrap = rehearsal.bootstrap(
            profile,
            database_material=database_material,
            user_material=user_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )

        control_state = control.start()
        engine = create_engine(control.database_url)
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        scheduler = delivery.EphemeralDolphinScheduler(
            scheduler_admin_password,
            readiness_timeout=scheduler_readiness_timeout_seconds,
        )
        with scheduler:
            project_code, access_token = scheduler.provision_project()
            scheduler_profile = DolphinSchedulerProfile(
                base_url=scheduler.base_url,
                access_token=access_token,
                project_code=project_code,
                workload_subject=RUNNER,
                policy_evaluator_subject=POLICY_EVALUATOR,
                tenant_code="default",
                worker_group="default",
                timezone_name="UTC",
                request_timeout_seconds=300,
                reconciliation_page_limit=5,
            )
            client = DolphinSchedulerClient(scheduler_profile)
            binding = client.create_workflow(definition_bundle.workflow)
            authorized_at = datetime.now(UTC)
            authorization = build_terminal_authorization(
                checked_source,
                definition_bundle,
                binding,
                authorized_at=authorized_at,
            )
            authorization_sha = _authorization_fingerprint(authorization)
            register_terminal_authorization(gateway, authorization)
            server.executor = RetainedRealFeatureExecutor(
                request,
                profile,
                plan,
                source,
                runtime,
                rehearsal,
                endpoint_url=endpoint_url,
                object_store_user=object_store_user,
                object_store_material=object_store_material,
                authorization_sha256=authorization_sha,
            )
            server.start()
            adapter = DolphinSchedulerAdapter(
                scheduler_profile,
                gateway=gateway,
                client=client,
                clock=lambda: authorized_at,
            )
            dispatched = adapter.dispatch(
                TENANT,
                RUN_ID,
                binding,
                actor_subject=RUNNER,
                attempt_no=1,
            )
            terminal_instance = delivery._wait_for_terminal_instance(
                client,
                dispatched.workflow_instance_id,
                binding.workflow_definition_code,
                timeout_seconds=terminal_timeout_seconds,
            )
            reconciled = adapter.reconcile(
                TENANT,
                RUN_ID,
                binding,
                actor_subject=RUNNER,
                attempt_no=1,
            )
            if (
                terminal_instance.state.upper() != "SUCCESS"
                or reconciled.provider_state != "SUCCESS"
                or reconciled.run.status != RunStatus.RECONCILING
            ):
                executor_diagnostic = server.executor
                raise RetainedTerminalSuccessError(
                    "DolphinScheduler did not produce a reconcilable success: "
                    + json.dumps(
                        {
                            "terminal_state": terminal_instance.state.upper(),
                            "reconciled_state": reconciled.provider_state,
                            "run_status": reconciled.run.status.value,
                            "callback_count": (
                                executor_diagnostic.request_count
                                if executor_diagnostic is not None
                                else 0
                            ),
                            "executor_stage": (
                                executor_diagnostic.error_stage
                                if executor_diagnostic is not None
                                else None
                            ),
                            "executor_error_type": (
                                executor_diagnostic.error_type
                                if executor_diagnostic is not None
                                else None
                            ),
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                )
        server_stopped = server.stop()
        if client is not None:
            client.close()
            client = None
        executor = server.executor
        if (
            executor is None
            or executor.error_type is not None
            or executor.request_count != 1
            or executor.store is None
            or executor.output_contracts is None
            or executor.materialized_at is None
            or not executor.source_input_removed
        ):
            raise RetainedTerminalSuccessError(
                "retained real feature executor outcome is incomplete"
            )
        independent = independently_evaluate_retained_parquet(
            runtime,
            profile,
            plan,
            source,
            executor.store,
            endpoint_url=endpoint_url,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        latest = _mapping(executor.store.get("latest_metadata"))
        data_objects = [
            item
            for item in executor.store.get("objects") or []
            if str(_mapping(item).get("key") or "").endswith(".parquet")
        ]
        retention = build_retained_material_observation(
            tenant_id=TENANT,
            run_id=RUN_ID,
            output_resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
            output_content_sha256=plan.output_content_sha256,
            storage_uri=profile.target.table_location,
            retention_id=retention_id,
            owner="team:metadata-platform",
            namespace=str(namespace_retention["name"]),
            namespace_uid=str(namespace_retention["uid"]),
            control_database_ref=control.database_ref,
            object_inventory_sha256=str(
                executor.store.get("object_inventory_sha256")
            ),
            metadata_body_sha256=str(latest.get("body_sha256")),
            row_set_sha256=plan.row_set_sha256,
            snapshot_id=int(latest["current_snapshot_id"]),
            feature_count=20,
            data_file_count=len(data_objects),
            data_size_bytes=int(independent["data_size_bytes"]),
            readable=True,
            source_payload_retained=False,
            materialized_at=executor.materialized_at,
            observed_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        promotion = build_terminal_promotion(checked_source, retention)
        def live_probe(observed: RetainedMaterialObservation) -> bool:
            return _live_material_probe(
                observed,
                runtime=runtime,
                profile=profile,
                control=control,
                endpoint_url=endpoint_url,
                object_store_user=object_store_user,
                object_store_material=object_store_material,
            )
        coordinator = RetainedTerminalSuccessCoordinator(
            gateway, material_probe=live_probe
        )
        first_promotion, succeeded = coordinator.finalize(
            promotion, retention, reconciled.observation
        )
        replay_promotion, replayed = coordinator.finalize(
            promotion, retention, reconciled.observation
        )
        counts = _ledger_counts(engine)
        control_state = control.observe()
        verified = (
            first_promotion.created
            and not replay_promotion.created
            and succeeded == replayed
            and succeeded.status == RunStatus.SUCCEEDED
            and succeeded.state_version == 3
            and counts
            == {
                "artifacts": 5,
                "execution_plans": 1,
                "policy_decisions": 1,
                "approvals": 1,
                "evaluator_evidence": 1,
                "attempts": 2,
                "quality_results": 1,
                "lineage_events": 1,
                "run_events": 4,
            }
            and control_state.get("container_running") is True
            and control_state.get("volume_retained") is True
            and scheduler.cleanup_verified
            and server_stopped
            and live_probe(retention)
        )
        stable = {
            "schema": EVIDENCE_SCHEMA,
            "status": (
                "local_retained_real_feature_terminal_success_verified"
                if verified
                else "blocked"
            ),
            "contract_sha256": contract["contract_sha256"],
            "source_ingestion_evidence_sha256": SOURCE_INGESTION_EVIDENCE_SHA256,
            "source_promotion_evidence_sha256": SOURCE_PROMOTION_EVIDENCE_SHA256,
            "retention_id": retention_id,
            "tenant_id": TENANT,
            "run_id": str(RUN_ID),
            "definition_version_id": str(DEFINITION_VERSION_ID),
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "output_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
            "output_content_sha256": plan.output_content_sha256,
            "dataset_bundle": source["inventory"],
            "source_projection": source["projection"],
            "execution_request_sha256": request.request_sha256,
            "definition_sha256": definition_bundle.definition.definition_sha256,
            "compiled_workflow_sha256": definition_bundle.workflow.compiled_sha256,
            "authorization": {
                "execution_plan_artifact_id": str(authorization.execution_plan.artifact_id),
                "policy_decision_artifact_id": str(authorization.policy_decision.artifact_id),
                "approval_artifact_id": str(authorization.approval.artifact_id),
                "authorization_sha256": authorization_sha,
                "payload_recorded": False,
            },
            "provider_observation": {
                "observation_id": str(reconciled.observation.observation_id),
                "observation_sha256": reconciled.observation.observation_sha256,
                "external_namespace": reconciled.observation.external_namespace,
                "external_run_id": reconciled.observation.external_run_id,
                "observed_state": reconciled.observation.observed_state,
                "provider_state": reconciled.provider_state,
            },
            "retention_observation": retention.model_dump(mode="json", by_alias=True),
            "retention_observation_sha256": retention.observation_sha256,
            "namespace_retention": namespace_retention,
            "control_database": control_state,
            "initial_runtime": initial_runtime,
            "object_store_prepared": object_store_prepared,
            "bootstrap": bootstrap,
            "independent_quality": independent,
            "quality_evidence_artifact_id": str(
                promotion.quality_evidence_artifact.artifact_id
            ),
            "quality_result_id": str(promotion.quality_result.quality_result_id),
            "lineage_event_id": str(promotion.lineage_event.lineage_event_id),
            "output_artifact_id": str(promotion.output_artifact.artifact_id),
            "ledger_counts": counts,
            "platform_run_status": succeeded.status.value,
            "platform_run_state_version": succeeded.state_version,
            "scheduler_container_cleanup_verified": scheduler.cleanup_verified,
            "execution_callback_cleanup_verified": server_stopped,
            "runtime_port_forwards_stopped": False,
            "retained_staging_material_verified": verified,
            "retained_control_database_verified": verified,
            "complete_authorization_artifacts_persisted": verified,
            "dolphinscheduler_success_observed": verified,
            "independent_quality_evidence_persisted": verified,
            "atomic_output_promotion_verified": verified,
            "platform_run_succeeded": verified,
            "exact_terminal_replay_verified": verified,
            "source_payload_removed_from_runtime": verified,
            "writes_to_legacy": False,
            **{claim: False for claim in FALSE_CLAIMS},
            "errors": [] if verified else ["M3-24 live rehearsal did not verify"],
        }
        if not verified:
            raise RetainedTerminalSuccessError(
                "M3-24 live retained rehearsal did not verify"
            )
        retained = True
        evidence = {
            **stable,
            "evidence_sha256": canonical_json_fingerprint(stable),
        }
    finally:
        if client is not None:
            client.close()
        if rehearsal is not None:
            rehearsal.close()
        if gravitino_forward is not None:
            gravitino_forward_stopped = gravitino_forward.stop()
        if object_forward is not None:
            object_forward_stopped = object_forward.stop()
        if server.started and not server.cleanup_verified:
            server.stop()
        if engine is not None:
            engine.dispose()
        if not retained:
            runtime.cleanup()
            control.cleanup()
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    stable["runtime_port_forwards_stopped"] = (
        object_forward_stopped and gravitino_forward_stopped
    )
    if not stable["runtime_port_forwards_stopped"]:
        raise RetainedTerminalSuccessError("M3-24 runtime port-forward cleanup failed")
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def _apply_migrations(engine: Any) -> None:
    m323._apply_migrations(engine)


def build_contract_report() -> dict[str, Any]:
    errors: list[str] = []
    files = {
        "terminal_success": _file_record(Path(__file__).resolve()),
        "source_ingestion": _file_record(Path(m322.__file__).resolve()),
        "source_promotion": _file_record(Path(m323.__file__).resolve()),
        "wrapper": _file_record(DEFAULT_WRAPPER_PATH),
    }
    try:
        source = _load_json_object(DEFAULT_SOURCE_EVIDENCE_PATH)
        m323.validate_source_evidence(source)
        promotion_evidence = _load_json_object(DEFAULT_PROMOTION_EVIDENCE_PATH)
        if m323.validate_rehearsal_evidence(promotion_evidence):
            errors.append("M3-23 promotion evidence is invalid")
        if promotion_evidence.get("evidence_sha256") != SOURCE_PROMOTION_EVIDENCE_SHA256:
            errors.append("M3-23 promotion evidence fingerprint drifted")
    except (OSError, ValueError, RetainedTerminalSuccessError):
        errors.append("M3-22/M3-23 predecessor evidence is unavailable")
    if files["wrapper"]["sha256"] is None:
        errors.append("M3-24 wrapper is unavailable")
    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_ingestion_evidence_sha256": SOURCE_INGESTION_EVIDENCE_SHA256,
        "source_promotion_evidence_sha256": SOURCE_PROMOTION_EVIDENCE_SHA256,
        "files": files,
        "requires_retained_material_readback": True,
        "requires_complete_authorization_artifacts": True,
        "requires_dolphinscheduler_success_observation": True,
        "requires_independent_quality_evidence_creator": True,
        "uses_existing_atomic_promoter": True,
        "uses_existing_success_finalizer": True,
        "retained_staging_is_production": False,
        "writes_to_legacy": False,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        **{claim: False for claim in FALSE_CLAIMS},
    }


def validate_evidence(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("M3-24 evidence schema does not match")
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-24 evidence fingerprint does not match")
    contract = build_contract_report()
    if evidence.get("contract_sha256") != contract.get("contract_sha256"):
        errors.append("M3-24 contract binding is stale")
    for claim in (
        "retained_staging_material_verified",
        "retained_control_database_verified",
        "complete_authorization_artifacts_persisted",
        "dolphinscheduler_success_observed",
        "independent_quality_evidence_persisted",
        "atomic_output_promotion_verified",
        "platform_run_succeeded",
        "exact_terminal_replay_verified",
        "source_payload_removed_from_runtime",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"M3-24 evidence claim is false: {claim}")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"M3-24 evidence may not claim {claim}")
    try:
        retention = RetainedMaterialObservation.model_validate(
            evidence.get("retention_observation")
        )
        if retention.observation_sha256 != evidence.get(
            "retention_observation_sha256"
        ):
            errors.append("M3-24 retention observation binding drifted")
    except ValueError:
        errors.append("M3-24 retention observation is invalid")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        "/Users/",
        "/home/",
        "Downloads/",
        ".tmp/",
        "geometry_wkb_hex",
        '"rows"',
        '"password"',
        '"secret"',
        '"token"',
        '"access_key"',
        '"access-key"',
    ):
        if forbidden in serialized:
            errors.append("M3-24 evidence contains source or secret material")
            break
    return errors


def build_validation_report(
    *, evidence_path: Path = DEFAULT_EVIDENCE_PATH
) -> dict[str, Any]:
    contract = build_contract_report()
    errors = list(contract["errors"])
    evidence: dict[str, Any] | None = None
    try:
        evidence = _load_json_object(evidence_path)
        errors.extend(validate_evidence(evidence))
    except (OSError, ValueError, RetainedTerminalSuccessError):
        errors.append("M3-24 checked evidence is unavailable")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": contract["contract_sha256"],
        "evidence_sha256": evidence.get("evidence_sha256") if evidence else None,
        "errors": errors,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def cleanup_retained_rehearsal(
    evidence_path: Path, *, retention_id: str
) -> dict[str, Any]:
    evidence = _load_json_object(evidence_path)
    if validate_evidence(evidence):
        raise RetainedTerminalSuccessError(
            "cleanup requires intact checked M3-24 evidence"
        )
    if evidence.get("retention_id") != retention_id:
        raise RetainedTerminalSuccessError(
            "cleanup retention ID does not match checked evidence"
        )
    retention = RetainedMaterialObservation.model_validate(
        evidence.get("retention_observation")
    )
    control = _mapping(evidence.get("control_database"))
    namespace_json = _run_command(
        ["kubectl", "get", "namespace", retention.namespace, "-o", "json"]
    )
    namespace = json.loads(namespace_json)
    metadata = _mapping(namespace.get("metadata"))
    labels = _mapping(metadata.get("labels"))
    if (
        metadata.get("uid") != retention.namespace_uid
        or labels.get("gda.gisdataagent.io/retention-id") != retention_id
    ):
        raise RetainedTerminalSuccessError(
            "cleanup namespace ownership does not match checked evidence"
        )
    container_name = str(control.get("container_name") or "")
    volume_name = str(control.get("volume_name") or "")
    if not container_name.startswith("gda-m3-24-control-") or not volume_name.startswith(
        "gda-m3-24-control-"
    ):
        raise RetainedTerminalSuccessError(
            "cleanup control database identity is not bounded"
        )
    container_retention = _run_command(
        [
            "docker",
            "container",
            "inspect",
            container_name,
            "--format",
            "{{index .Config.Labels \"gda.retention-id\"}}",
        ]
    )
    volume_retention = _run_command(
        [
            "docker",
            "volume",
            "inspect",
            volume_name,
            "--format",
            "{{index .Labels \"gda.retention-id\"}}",
        ]
    )
    if container_retention != retention_id or volume_retention != retention_id:
        raise RetainedTerminalSuccessError(
            "cleanup control database ownership does not match checked evidence"
        )
    _run_command(
        [
            "kubectl",
            "delete",
            "namespace",
            retention.namespace,
            "--wait=true",
            "--timeout=5m",
        ],
        timeout=330,
    )
    _run_command(["docker", "rm", "--force", container_name])
    _run_command(["docker", "volume", "rm", volume_name])
    return {
        "status": "cleaned",
        "retention_id": retention_id,
        "namespace_removed": True,
        "control_database_removed": True,
        "recoverable": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("contract")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    live = subparsers.add_parser("live-rehearsal")
    live.add_argument("--profile", type=Path, default=m322.DEFAULT_PROFILE_PATH)
    live.add_argument("--shapefile", type=Path, required=True)
    live.add_argument("--ogrinfo", type=Path, required=True)
    live.add_argument("--proj-data", type=Path)
    live.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE_PATH)
    live.add_argument(
        "--scheduler-admin-password-env",
        default="GDA_M324_DOLPHINSCHEDULER_ADMIN_PASSWORD",
    )
    live.add_argument("--scheduler-readiness-timeout", type=float, default=240)
    live.add_argument("--terminal-timeout", type=float, default=1500)
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    cleanup.add_argument("--retention-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "contract":
        report = build_contract_report()
    elif args.command == "validate":
        report = build_validation_report(evidence_path=args.evidence)
    elif args.command == "live-rehearsal":
        report = run_live_rehearsal(
            profile_path=args.profile,
            shapefile_path=args.shapefile,
            ogrinfo_path=args.ogrinfo,
            proj_data_path=args.proj_data,
            scheduler_admin_password=delivery._read_admin_password(
                args.scheduler_admin_password_env
            ),
            scheduler_readiness_timeout_seconds=args.scheduler_readiness_timeout,
            terminal_timeout_seconds=args.terminal_timeout,
        )
        errors = validate_evidence(report)
        if errors:
            raise RetainedTerminalSuccessError(
                "M3-24 live evidence failed self-validation: " + "; ".join(errors)
            )
        _write_json(args.output, report)
    else:
        report = cleanup_retained_rehearsal(
            args.evidence, retention_id=args.retention_id
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {
        "valid",
        "local_retained_real_feature_terminal_success_verified",
        "cleaned",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
