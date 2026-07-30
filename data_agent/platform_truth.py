"""AR-0 configuration and runtime truth contracts.

This module deliberately uses only the Python standard library so it can run
before application frameworks, database drivers, and model SDKs are imported.
It does not replace subsystem configuration yet.  It establishes one typed,
redacted inventory and a source-code gate that prevents new unregistered
configuration or background runtime surfaces from appearing silently.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit


REPORT_SCHEMA = "gda.platform_truth.v1"
SOURCE_ROOT = Path(__file__).resolve().parent
VALID_PROFILES = frozenset({"development", "test", "staging", "production"})
PROFILE_ALIASES = {
    "dev": "development",
    "ci": "test",
    "stage": "staging",
    "prod": "production",
}
SECRET_PLACEHOLDER_TOKENS = (
    "change_me",
    "your_",
    "replace_with",
    "placeholder",
    "generate_a_",
    "default-secret",
    "local_dev_",
)


class PlatformTruthError(RuntimeError):
    """A strict platform truth contract was not satisfied."""


@dataclass(frozen=True)
class ConfigSpec:
    key: str
    value_type: str = "str"
    default: Any = None
    secret: bool = False
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    required_profiles: tuple[str, ...] = ()
    owner: str = "platform"
    description: str = ""


@dataclass(frozen=True)
class RuntimeSpec:
    runtime_id: str
    kind: str
    status: str
    durability: str
    state_authority: str
    owner: str
    production_role: str
    code_paths: tuple[str, ...]
    evidence: tuple[tuple[str, str], ...]
    target: str
    replacement_required: bool = False


def _config(
    key: str,
    value_type: str = "str",
    default: Any = None,
    *,
    secret: bool = False,
    choices: tuple[str, ...] = (),
    minimum: float | None = None,
    maximum: float | None = None,
    required_profiles: tuple[str, ...] = (),
    owner: str = "platform",
    description: str = "",
) -> ConfigSpec:
    return ConfigSpec(
        key=key,
        value_type=value_type,
        default=default,
        secret=secret,
        choices=choices,
        minimum=minimum,
        maximum=maximum,
        required_profiles=required_profiles,
        owner=owner,
        description=description,
    )


CONFIG_SPECS = (
    _config(
        "GDA_DEPLOYMENT_PROFILE",
        "enum",
        "development",
        choices=tuple(sorted(VALID_PROFILES)),
        description="Deployment policy profile.",
    ),
    _config(
        "GDA_CONFIG_STRICT",
        "bool",
        None,
        description="Enable strict validation; staging and production are always strict.",
    ),
    _config("DB_BACKEND", "enum", "postgres", choices=("postgres", "duckdb"), owner="data-platform"),
    _config("DATABASE_URL", "url", None, secret=True, owner="data-platform"),
    _config("POSTGRES_HOST", "str", "localhost", owner="data-platform"),
    _config("POSTGRES_PORT", "int", 5432, minimum=1, maximum=65535, owner="data-platform"),
    _config("POSTGRES_DATABASE", "str", None, owner="data-platform"),
    _config("POSTGRES_USER", "str", None, owner="data-platform"),
    _config("POSTGRES_PASSWORD", "str", None, secret=True, owner="data-platform"),
    _config("DATABASE_READ_URL", "url", None, secret=True, owner="data-platform"),
    _config("DB_POOL_SIZE", "int", 20, minimum=1, maximum=500, owner="data-platform"),
    _config("DB_MAX_OVERFLOW", "int", 30, minimum=0, maximum=1000, owner="data-platform"),
    _config("ASYNC_POOL_MIN", "int", 5, minimum=0, maximum=500, owner="data-platform"),
    _config("ASYNC_POOL_MAX", "int", 20, minimum=1, maximum=1000, owner="data-platform"),
    _config("CHAINLIT_AUTH_SECRET", "str", None, secret=True, owner="security"),
    _config("REDIS_URL", "url", None, secret=True, owner="runtime"),
    _config(
        "CLOUD_STORAGE_PROVIDER",
        "enum",
        None,
        choices=("aws", "gcs", "huawei"),
        owner="data-platform",
    ),
    _config("AWS_ENDPOINT_URL", "url", None, owner="data-platform"),
    _config("AWS_ACCESS_KEY_ID", "str", None, secret=True, owner="data-platform"),
    _config("AWS_SECRET_ACCESS_KEY", "str", None, secret=True, owner="data-platform"),
    _config("AWS_S3_BUCKET", "str", None, owner="data-platform"),
    _config("AWS_REGION", "str", "us-east-1", owner="data-platform"),
    _config("HUAWEI_OBS_AK", "str", None, secret=True, owner="data-platform"),
    _config("HUAWEI_OBS_SK", "str", None, secret=True, owner="data-platform"),
    _config("HUAWEI_OBS_SERVER", "url", None, owner="data-platform"),
    _config("HUAWEI_OBS_BUCKET", "str", None, owner="data-platform"),
    _config("GCS_BUCKET", "str", None, owner="data-platform"),
    _config("MMFE_LAKEHOUSE_BUCKET", "str", None, owner="lakehouse"),
    _config("MMFE_LAKEHOUSE_WAREHOUSE_URI", "uri", None, owner="lakehouse"),
    _config("MMFE_STAC_CATALOG_URI", "uri", None, owner="lakehouse"),
    _config("MMFE_ICEBERG_CATALOG", "str", "local", owner="lakehouse"),
    _config("MMFE_ICEBERG_NAMESPACE", "str", "gis.fusion", owner="lakehouse"),
    _config("ROUTER_MODEL", "str", "gemini-2.0-flash", owner="ai-platform"),
    _config("MODEL_FAST", "str", "gemini-2.0-flash", owner="ai-platform"),
    _config("MODEL_STANDARD", "str", "gemini-2.5-flash", owner="ai-platform"),
    _config("MODEL_PREMIUM", "str", "gemini-2.5-pro", owner="ai-platform"),
    _config("EMBEDDING_MODEL", "str", "text-embedding-004", owner="ai-platform"),
    _config("MODEL_CONFIG_FORCE_ENV", "bool", False, owner="ai-platform"),
    _config("GOOGLE_GENAI_USE_VERTEXAI", "bool", False, owner="ai-platform"),
    _config("GOOGLE_CLOUD_PROJECT", "str", None, owner="ai-platform"),
    _config("GOOGLE_CLOUD_LOCATION", "str", "global", owner="ai-platform"),
    _config("GOOGLE_API_KEY", "str", None, secret=True, owner="ai-platform"),
    _config("OLLAMA_API_BASE", "url", None, owner="ai-platform"),
    _config("DYNAMIC_PLANNER", "bool", True, owner="agent-platform"),
    _config("TASK_QUEUE_CONCURRENCY", "int", 3, minimum=1, maximum=100, owner="runtime"),
    _config("TASK_QUEUE_MAX_PER_USER", "int", 10, minimum=1, maximum=1000, owner="runtime"),
    _config("SPARK_L1_MAX_MB", "int", 100, minimum=1, owner="runtime"),
    _config("SPARK_L2_MAX_MB", "int", 1024, minimum=1, owner="runtime"),
    _config(
        "SPARK_BACKEND",
        "enum",
        "local",
        choices=("local", "livy", "dataproc", "emr"),
        owner="runtime",
    ),
    _config("SPARK_LIVY_URL", "url", None, owner="runtime"),
    _config("SELF_EVOLUTION_SCHEDULER_ENABLED", "bool", False, owner="agentops"),
    _config(
        "SELF_EVOLUTION_SCHEDULER_INTERVAL_SECONDS",
        "int",
        86400,
        minimum=300,
        maximum=2592000,
        owner="agentops",
    ),
    _config("STANDARDS_OUTBOX_WORKER_INTERVAL_SEC", "int", 5, minimum=1, maximum=3600, owner="data-platform"),
    _config("STANDARDS_OUTBOX_MAX_ATTEMPTS", "int", 5, minimum=1, maximum=100, owner="data-platform"),
    _config(
        "DOLPHINSCHEDULER_COMMAND_WORKER_ENABLED",
        "bool",
        False,
        owner="dataops",
        description="Enable the managed DolphinScheduler command worker process.",
    ),
    _config("DOLPHINSCHEDULER_BASE_URL", "url", None, owner="dataops"),
    _config(
        "DOLPHINSCHEDULER_TOKEN_FILE",
        "str",
        None,
        secret=True,
        owner="security",
    ),
    _config(
        "DOLPHINSCHEDULER_PROJECT_CODE",
        "int",
        None,
        minimum=1,
        owner="dataops",
    ),
    _config("DOLPHINSCHEDULER_WORKLOAD_SUBJECT", "str", None, owner="security"),
    _config(
        "DOLPHINSCHEDULER_POLICY_EVALUATOR_SUBJECT",
        "str",
        None,
        owner="security",
    ),
    _config("DOLPHINSCHEDULER_TENANT_CODE", "str", "default", owner="dataops"),
    _config("DOLPHINSCHEDULER_WORKER_GROUP", "str", "default", owner="dataops"),
    _config(
        "DOLPHINSCHEDULER_REQUEST_TIMEOUT_SECONDS",
        "float",
        15,
        minimum=1,
        maximum=300,
        owner="dataops",
    ),
    _config(
        "DOLPHINSCHEDULER_RECONCILIATION_PAGE_LIMIT",
        "int",
        5,
        minimum=1,
        maximum=100,
        owner="dataops",
    ),
    _config(
        "DOLPHINSCHEDULER_COMMAND_TENANT_ID",
        "str",
        None,
        owner="data-platform",
    ),
    _config(
        "DOLPHINSCHEDULER_COMMAND_WORKER_ID",
        "str",
        None,
        owner="sre",
    ),
    _config(
        "DOLPHINSCHEDULER_COMMAND_BATCH_SIZE",
        "int",
        10,
        minimum=1,
        maximum=100,
        owner="dataops",
    ),
    _config(
        "DOLPHINSCHEDULER_COMMAND_LEASE_SECONDS",
        "int",
        60,
        minimum=5,
        maximum=3600,
        owner="dataops",
    ),
    _config(
        "DOLPHINSCHEDULER_COMMAND_POLL_INTERVAL_SECONDS",
        "float",
        5,
        minimum=0.1,
        maximum=3600,
        owner="dataops",
    ),
    _config(
        "DOLPHINSCHEDULER_COMMAND_STATUS_FILE",
        "str",
        "/tmp/gda-dolphinscheduler-command-worker.json",
        owner="sre",
    ),
    _config(
        "DOLPHINSCHEDULER_COMMAND_HEALTH_MAX_AGE_SECONDS",
        "float",
        30,
        minimum=1,
        maximum=7200,
        owner="sre",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_ENABLED",
        "bool",
        False,
        owner="metadata-platform",
        description="Enable the managed Active Metadata request staging worker.",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_TENANT_ID",
        "str",
        None,
        owner="metadata-platform",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_WORKER_ID",
        "str",
        None,
        owner="sre",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_SUBJECT",
        "str",
        None,
        owner="security",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_BATCH_SIZE",
        "int",
        10,
        minimum=1,
        maximum=100,
        owner="metadata-platform",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_LEASE_SECONDS",
        "int",
        60,
        minimum=5,
        maximum=3600,
        owner="metadata-platform",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_POLL_INTERVAL_SECONDS",
        "float",
        5,
        minimum=0.1,
        maximum=3600,
        owner="metadata-platform",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_STATUS_FILE",
        "str",
        "/tmp/gda-active-metadata-consumer.json",
        owner="sre",
    ),
    _config(
        "ACTIVE_METADATA_CONSUMER_HEALTH_MAX_AGE_SECONDS",
        "float",
        30,
        minimum=1,
        maximum=7200,
        owner="sre",
    ),
    _config("ARCPY_MCP_ENABLED", "bool", False, owner="gis-runtime"),
    _config("ARCPY_MCP_URL", "url", None, owner="gis-runtime"),
    _config("ARCPY_MCP_TOKEN", "str", None, secret=True, owner="gis-runtime"),
    _config("ARCPY_MCP_TOKEN_FILE", "str", None, secret=True, owner="gis-runtime"),
    _config("ARCPY_MCP_CA_BUNDLE", "str", None, owner="gis-runtime"),
    _config("ARCPY_MCP_CONNECT_TIMEOUT", "int", 10, minimum=1, maximum=300, owner="gis-runtime"),
    _config("LOG_LEVEL", "enum", "INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), owner="sre"),
    _config("LOG_FORMAT", "enum", "text", choices=("text", "json"), owner="sre"),
)


RUNTIME_INVENTORY = (
    RuntimeSpec(
        "workflow_scheduler",
        "cron_scheduler",
        "legacy",
        "process_local",
        "agent_workflows + APScheduler memory",
        "data-platform",
        "compatibility_only",
        ("data_agent/workflow_engine.py",),
        (("data_agent/workflow_engine.py", "AsyncIOScheduler"),),
        "DolphinScheduler DataOps adapter",
        True,
    ),
    RuntimeSpec(
        "task_queue",
        "async_queue",
        "legacy",
        "partial",
        "Redis/in-memory queue + agent_task_queue projection",
        "agent-platform",
        "compatibility_only",
        ("data_agent/task_queue.py",),
        (("data_agent/task_queue.py", "asyncio.ensure_future"),),
        "PlatformRun + selected orchestrator",
        True,
    ),
    RuntimeSpec(
        "spark_gateway",
        "compute_gateway",
        "legacy",
        "process_local",
        "SparkGateway._jobs memory",
        "data-platform",
        "compatibility_only",
        ("data_agent/spark_gateway.py",),
        (("data_agent/spark_gateway.py", "class SparkGateway"),),
        "Execution adapter with external run reconciliation",
        True,
    ),
    RuntimeSpec(
        "stream_processor",
        "stream_loop",
        "legacy",
        "process_local",
        "Redis stream + in-process task map",
        "data-platform",
        "compatibility_only",
        ("data_agent/stream_engine.py",),
        (("data_agent/stream_engine.py", "asyncio.create_task"),),
        "Flink/stream runtime adapter",
        True,
    ),
    RuntimeSpec(
        "self_evolution_scheduler",
        "interval_scheduler",
        "conditional",
        "process_local",
        "in-process task + persisted cycle result",
        "agentops",
        "disabled_by_default",
        ("data_agent/self_evolution_scheduler.py",),
        (("data_agent/self_evolution_scheduler.py", "self-evolution-scheduler"),),
        "Temporal AgentOps workflow when production-gated",
        True,
    ),
    RuntimeSpec(
        "standards_outbox_worker",
        "outbox_worker",
        "governed",
        "database_durable",
        "std_outbox",
        "data-platform",
        "authoritative_event_delivery",
        ("data_agent/standards_platform/outbox_worker.py",),
        (("data_agent/standards_platform/outbox_worker.py", "outbox.claim_batch"),),
        "Retain as reliable command/event delivery",
    ),
    RuntimeSpec(
        "dolphinscheduler_command_worker",
        "outbox_worker",
        "governed",
        "database_durable",
        "gda_control.platform_command_outbox",
        "dataops",
        "provider_command_delivery",
        (
            "data_agent/dolphinscheduler_command_worker.py",
            "data_agent/dolphinscheduler_command_consumer.py",
        ),
        (
            (
                "data_agent/dolphinscheduler_command_worker.py",
                "class DolphinSchedulerCommandWorker",
            ),
            (
                "data_agent/dolphinscheduler_command_consumer.py",
                "self.gateway.claim_commands(",
            ),
        ),
        "Retain as tenant-scoped managed provider command delivery",
    ),
    RuntimeSpec(
        "active_metadata_consumer_worker",
        "outbox_worker",
        "governed",
        "database_durable",
        (
            "gda_control.metadata_change_outbox + "
            "gda_control.metadata_activation_request"
        ),
        "metadata-platform",
        "activation_request_staging_only",
        (
            "data_agent/active_metadata_consumer_worker.py",
            "data_agent/active_metadata_consumer.py",
        ),
        (
            (
                "data_agent/active_metadata_consumer_worker.py",
                "class ActiveMetadataConsumerWorker",
            ),
            (
                "data_agent/active_metadata_consumer.py",
                "self.gateway.stage_metadata_activation_request(",
            ),
        ),
        "Retain as tenant-scoped inert activation request staging",
    ),
    RuntimeSpec(
        "api_workflow_background",
        "api_background_task",
        "legacy",
        "process_local",
        "agent_workflow_runs + in-process task",
        "agent-platform",
        "not_authoritative",
        ("data_agent/api/workflow_routes.py",),
        (("data_agent/api/workflow_routes.py", "asyncio.create_task"),),
        "Orchestration gateway submission",
        True,
    ),
    RuntimeSpec(
        "app_ephemeral_tasks",
        "ui_background_task",
        "legacy",
        "process_local",
        "request/session memory",
        "agent-platform",
        "not_authoritative",
        ("data_agent/app.py",),
        (("data_agent/app.py", "asyncio.create_task"),),
        "Typed command submission or request-scoped await",
        True,
    ),
    RuntimeSpec(
        "feedback_background",
        "api_background_task",
        "legacy",
        "process_local",
        "agent_feedback projection",
        "agentops",
        "not_authoritative",
        ("data_agent/api/feedback_routes.py",),
        (("data_agent/api/feedback_routes.py", "asyncio.create_task"),),
        "Outbox command with idempotent consumer",
        True,
    ),
    RuntimeSpec(
        "bot_delivery_tasks",
        "integration_background_task",
        "legacy",
        "process_local",
        "provider callback + process task",
        "integrations",
        "not_authoritative",
        (
            "data_agent/bot_base.py",
            "data_agent/wecom_bot.py",
            "data_agent/dingtalk_bot.py",
            "data_agent/feishu_bot.py",
        ),
        (("data_agent/bot_base.py", "asyncio.create_task"),),
        "Durable inbound command/outbound delivery adapter",
        True,
    ),
    RuntimeSpec(
        "mcp_lifecycle_tasks",
        "transport_lifecycle",
        "ephemeral",
        "request_scoped",
        "MCP session state",
        "agent-platform",
        "request_scoped_only",
        ("data_agent/mcp_runtime.py",),
        (("data_agent/mcp_runtime.py", "asyncio.create_task"),),
        "Retain with bounded cancellation and no business run authority",
    ),
    RuntimeSpec(
        "arcpy_remote_runtime",
        "remote_tool_runtime",
        "governed",
        "remote_job_durable",
        "ArcPy MCP remote job + local transport tasks",
        "gis-runtime",
        "execution_provider",
        ("data_agent/arcpy_mcp_client.py", "data_agent/arcpy_tools.py"),
        (("data_agent/arcpy_mcp_client.py", "class ArcPyMcpClient"),),
        "PlatformRun-correlated execution provider",
    ),
    RuntimeSpec(
        "metadata_backup_repository_rehearsal",
        "recovery_rehearsal",
        "governed",
        "evidence_durable",
        "versioned S3 observation + committed recovery evidence",
        "sre",
        "local_verification_only",
        ("data_agent/metadata_fabric_backup_repository.py",),
        (
            (
                "data_agent/metadata_fabric_backup_repository.py",
                "class _RepositoryRoundTrip",
            ),
        ),
        "Production backup controller and independent recovery reader",
    ),
    RuntimeSpec(
        "metadata_cross_cluster_recovery_rehearsal",
        "recovery_rehearsal",
        "governed",
        "evidence_durable",
        "host-external versioned S3 observation + committed cross-cluster evidence",
        "sre",
        "local_verification_only",
        ("data_agent/metadata_fabric_cross_cluster_recovery.py",),
        (
            (
                "data_agent/metadata_fabric_cross_cluster_recovery.py",
                "class _ExternalRepositoryRuntime",
            ),
        ),
        "Production backup controller and failure-domain-isolated recovery reader",
    ),
    RuntimeSpec(
        "metadata_provider_metrics_collector",
        "metrics_probe",
        "governed",
        "evidence_durable",
        "committed provider metrics evidence",
        "sre",
        "local_verification_only",
        ("data_agent/metadata_fabric_provider_metrics.py",),
        (
            (
                "data_agent/metadata_fabric_provider_metrics.py",
                "class _PortForward",
            ),
        ),
        "Production metrics pipeline with TLS, alert delivery, and SLO ownership",
    ),
    RuntimeSpec(
        "metadata_otel_metrics_pipeline",
        "metrics_pipeline",
        "governed",
        "evidence_durable",
        "committed local OTel metrics pipeline evidence",
        "sre",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_otel_metrics.py",
            "scripts/metadata-fabric-otel-metrics.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_otel_metrics.py",
                "class _OtelPortForward",
            ),
        ),
        "Durable production metrics backend with TLS, alerting, and SLO ownership",
    ),
    RuntimeSpec(
        "metadata_otel_failure_rehearsal",
        "metrics_failure_rehearsal",
        "governed",
        "evidence_durable",
        "committed local OTel scrape failure/recovery evidence",
        "sre",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_otel_failure_rehearsal.py",
            "scripts/metadata-fabric-otel-failure-rehearsal.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_otel_failure_rehearsal.py",
                "def collect_live_otel_failure_rehearsal",
            ),
        ),
        "Protected-environment failure injection tied to alert and SLO runbooks",
    ),
    RuntimeSpec(
        "metadata_network_policy_enforcement_rehearsal",
        "network_policy_enforcement_rehearsal",
        "governed",
        "evidence_durable",
        "committed local cross-node NetworkPolicy enforcement evidence",
        "sre",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_network_policy_enforcement.py",
            "scripts/metadata-fabric-network-policy-enforcement.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_network_policy_enforcement.py",
                "def collect_live_network_policy_enforcement",
            ),
        ),
        "Protected-environment NetworkPolicy enforcement and tenant isolation gate",
    ),
    RuntimeSpec(
        "metadata_openlineage_delivery_rehearsal",
        "lineage_delivery_rehearsal",
        "governed",
        "evidence_durable",
        "temporary PostgreSQL outbox + committed local wire evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_lineage_delivery.py",
            "scripts/metadata-fabric-openlineage-delivery.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_lineage_delivery.py",
                "threading.Thread",
            ),
        ),
        "Managed outbox worker and protected authenticated OpenLineage receiver",
    ),
    RuntimeSpec(
        "metadata_provider_identity_rehearsal",
        "provider_identity_rehearsal",
        "governed",
        "evidence_durable",
        "committed local OpenMetadata bounded identity evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_provider_identity.py",
            "scripts/metadata-fabric-provider-identity.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_provider_identity.py",
                "subprocess.run",
            ),
        ),
        "Protected OIDC workload identity and authenticated Gravitino access control",
    ),
    RuntimeSpec(
        "metadata_gravitino_identity_rehearsal",
        "gravitino_identity_rehearsal",
        "governed",
        "evidence_durable",
        "committed local Gravitino Basic bounded identity evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_gravitino_identity.py",
            "scripts/metadata-fabric-gravitino-identity.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_gravitino_identity.py",
                "subprocess.run",
            ),
        ),
        "Protected OIDC workload identity, TLS and production Gravitino catalog",
    ),
    RuntimeSpec(
        "metadata_gravitino_jdbc_restart_rehearsal",
        "gravitino_catalog_restart_rehearsal",
        "governed",
        "evidence_durable",
        "committed local authenticated JDBC catalog restart evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_gravitino_jdbc_restart.py",
            "scripts/metadata-fabric-gravitino-jdbc-restart.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_gravitino_jdbc_restart.py",
                "subprocess.run",
            ),
        ),
        "Protected identity and production catalog durability/conformance gate",
    ),
    RuntimeSpec(
        "metadata_spark_iceberg_rest_interoperability_rehearsal",
        "spark_iceberg_rest_interoperability_rehearsal",
        "governed",
        "evidence_durable",
        "committed local Spark/Iceberg REST interoperability evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_spark_iceberg_rest_interoperability.py",
            "scripts/metadata-fabric-spark-iceberg-rest-interoperability.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_spark_iceberg_rest_interoperability.py",
                "subprocess.run",
            ),
        ),
        "Protected Spark/Flink conformance and production object-store catalog gate",
    ),
    RuntimeSpec(
        "metadata_spark_object_store_interoperability_rehearsal",
        "spark_object_store_interoperability_rehearsal",
        "governed",
        "evidence_durable",
        "committed local cross-node Spark/S3 object-store interoperability evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_spark_object_store_interoperability.py",
            "scripts/metadata-fabric-spark-object-store-interoperability.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_spark_object_store_interoperability.py",
                "subprocess.run",
            ),
        ),
        "Protected identity/TLS, production object storage and full Spark/Flink conformance",
    ),
    RuntimeSpec(
        "metadata_spark_commit_failure_recovery_rehearsal",
        "spark_commit_failure_recovery_rehearsal",
        "governed",
        "evidence_durable",
        "committed local Spark/Iceberg commit-failure recovery evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_spark_commit_failure_recovery.py",
            "scripts/metadata-fabric-spark-commit-failure-recovery.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_spark_commit_failure_recovery.py",
                "class IsolatedSparkCommitFailureRuntime",
            ),
        ),
        "Protected identity/TLS, production object storage and full Spark/Flink conformance",
    ),
    RuntimeSpec(
        "metadata_spark_uncertain_commit_reconciliation_rehearsal",
        "spark_uncertain_commit_reconciliation_rehearsal",
        "governed",
        "evidence_durable",
        "committed local Spark/Iceberg uncertain-commit reconciliation evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_spark_uncertain_commit_reconciliation.py",
            "scripts/metadata-fabric-spark-uncertain-commit-reconciliation.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_spark_uncertain_commit_reconciliation.py",
                "class IsolatedSparkUncertainCommitRuntime",
            ),
        ),
        "Protected identity/TLS, production object storage and full Spark/Flink conformance",
    ),
    RuntimeSpec(
        "metadata_active_metadata_outbox_rehearsal",
        "active_metadata_outbox_rehearsal",
        "governed",
        "evidence_durable",
        "committed local PostgreSQL Active Metadata outbox evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_active_metadata_outbox.py",
            "scripts/metadata-fabric-active-metadata-outbox.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_active_metadata_outbox.py",
                "def run_local_rehearsal",
            ),
        ),
        "Durable inert activation request staging before authorization",
    ),
    RuntimeSpec(
        "metadata_active_metadata_consumer_rehearsal",
        "active_metadata_consumer_rehearsal",
        "governed",
        "evidence_durable",
        "temporary PostgreSQL activation requests + committed local evidence",
        "metadata-platform",
        "local_verification_only",
        (
            "data_agent/metadata_fabric_active_metadata_consumer.py",
            "scripts/metadata-fabric-active-metadata-consumer.sh",
        ),
        (
            (
                "data_agent/metadata_fabric_active_metadata_consumer.py",
                "def run_local_rehearsal",
            ),
        ),
        "Protected authorization and scheduler promotion of durable requests",
    ),
    RuntimeSpec(
        "datalake_monitor",
        "monitor_loop",
        "legacy",
        "process_local",
        "agent_monitor_discoveries + in-process task",
        "data-platform",
        "compatibility_only",
        ("data_agent/datalake_monitor.py",),
        (("data_agent/datalake_monitor.py", "class DataLakeMonitor"),),
        "DataOps observability run with durable checkpoints",
        True,
    ),
    RuntimeSpec(
        "annotation_broadcast_tasks",
        "api_background_task",
        "legacy",
        "process_local",
        "annotation table + best-effort WebSocket event",
        "integrations",
        "not_authoritative",
        ("data_agent/frontend_api.py",),
        (("data_agent/frontend_api.py", "broadcast_annotation_event"),),
        "Outbox-backed annotation event delivery",
        True,
    ),
    RuntimeSpec(
        "stream_control_tasks",
        "api_background_task",
        "legacy",
        "process_local",
        "stream engine state + untracked stop task",
        "data-platform",
        "not_authoritative",
        ("data_agent/stream_tools.py",),
        (("data_agent/stream_tools.py", "engine.stop_stream"),),
        "Typed stream control command with a durable RunRef",
        True,
    ),
    RuntimeSpec(
        "bounded_thread_offload",
        "request_thread_pool",
        "ephemeral",
        "request_scoped",
        "request result",
        "platform",
        "request_scoped_only",
        (
            "data_agent/toolsets/remote_sensing_tools.py",
            "data_agent/toolsets/evolution_tools.py",
            "data_agent/standards_platform/drafting/citation_assistant.py",
        ),
        (("data_agent/toolsets/remote_sensing_tools.py", "ThreadPoolExecutor"),),
        "Retain only for bounded request-scoped blocking calls",
    ),
)


# Fingerprint of literal environment reads in production Python modules.  It is
# intentionally updated only with an explicit config-contract review.
ENV_ACCESS_BASELINE_FINGERPRINT = (
    "5ee717911c109b480328a050893296e37591bfca748e3ed1743b7e3def3d9048"
)
RUNTIME_PRIMITIVE_BASELINE_FINGERPRINT = (
    "d6402d91e40ddb61591a7d258925d79e5eee964c3a9c0ace7de34acd10facbfd"
)

_IGNORED_SOURCE_PARTS = frozenset(
    {"tests", "benchmarks", "experiments", "test_data", "__pycache__"}
)


def _normalize_profile(value: str | None) -> str:
    normalized = str(value or "development").strip().lower()
    return PROFILE_ALIASES.get(normalized, normalized)


def _parse_value(spec: ConfigSpec, raw: Any) -> tuple[Any, str | None]:
    value = spec.default if raw is None or str(raw).strip() == "" else raw
    if value is None:
        return None, None
    try:
        if spec.value_type in {"str", "uri"}:
            parsed: Any = str(value).strip()
        elif spec.value_type == "int":
            parsed = int(value)
        elif spec.value_type == "float":
            parsed = float(value)
        elif spec.value_type == "bool":
            lowered = str(value).strip().lower()
            if lowered not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
                raise ValueError("expected boolean")
            parsed = lowered in {"1", "true", "yes", "on"}
        elif spec.value_type == "enum":
            parsed = str(value).strip()
            if parsed not in spec.choices:
                raise ValueError(f"expected one of {', '.join(spec.choices)}")
        elif spec.value_type == "url":
            parsed = str(value).strip()
            parts = urlsplit(_normalize_postgres_scheme(parsed))
            if not parts.scheme or not parts.netloc:
                raise ValueError("expected absolute URL")
        else:
            raise ValueError(f"unsupported type {spec.value_type}")
        if spec.minimum is not None and parsed < spec.minimum:
            raise ValueError(f"must be >= {spec.minimum:g}")
        if spec.maximum is not None and parsed > spec.maximum:
            raise ValueError(f"must be <= {spec.maximum:g}")
        return parsed, None
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def _issue(key: str, code: str, message: str) -> dict[str, str]:
    return {"key": key, "code": code, "message": message}


def _is_placeholder_secret(value: str) -> bool:
    lowered = value.strip().lower()
    return any(token in lowered for token in SECRET_PLACEHOLDER_TOKENS)


def _normalize_postgres_scheme(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+") and "://" in url:
        return "postgresql://" + url.split("://", 1)[1]
    return url


def resolve_database_url(values: Mapping[str, str] | None = None) -> str | None:
    """Resolve the authoritative database URL with DATABASE_URL precedence."""
    env = values if values is not None else os.environ
    direct = str(env.get("DATABASE_URL") or "").strip()
    if direct:
        return _normalize_postgres_scheme(direct)
    user = str(env.get("POSTGRES_USER") or "").strip()
    password = str(env.get("POSTGRES_PASSWORD") or "")
    database = str(env.get("POSTGRES_DATABASE") or "").strip()
    if not user or not password or not database:
        return None
    host = str(env.get("POSTGRES_HOST") or "localhost").strip()
    port = str(env.get("POSTGRES_PORT") or "5432").strip()
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@"
        f"{host}:{port}/{quote(database, safe='')}"
    )


def _database_identity(url: str) -> tuple[str | None, int | None, str, str | None]:
    parts = urlsplit(_normalize_postgres_scheme(url))
    return (
        parts.hostname,
        parts.port or 5432,
        parts.path.lstrip("/"),
        parts.username,
    )


def build_config_report(
    values: Mapping[str, str] | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    """Build a typed, redacted configuration report and startup verdict."""
    env = values if values is not None else os.environ
    requested_profile = profile or env.get("GDA_DEPLOYMENT_PROFILE")
    effective_profile = _normalize_profile(requested_profile)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if effective_profile not in VALID_PROFILES:
        errors.append(
            _issue(
                "GDA_DEPLOYMENT_PROFILE",
                "invalid_profile",
                f"unsupported deployment profile {effective_profile!r}",
            )
        )

    strict_raw = env.get("GDA_CONFIG_STRICT")
    profile_requires_strict = effective_profile not in {"development", "test"}
    if strict_raw is None or str(strict_raw).strip() == "":
        strict = profile_requires_strict
    else:
        strict_value, strict_error = _parse_value(
            _config("GDA_CONFIG_STRICT", "bool"), strict_raw
        )
        strict = profile_requires_strict if strict_error else (
            bool(strict_value) or profile_requires_strict
        )
        if not strict_error and profile_requires_strict and not strict_value:
            warnings.append(
                _issue(
                    "GDA_CONFIG_STRICT",
                    "strict_disable_ignored",
                    f"strict validation cannot be disabled in {effective_profile}",
                )
            )

    entries: dict[str, dict[str, Any]] = {}
    parsed_values: dict[str, Any] = {}
    for spec in CONFIG_SPECS:
        raw = env.get(spec.key)
        value_to_parse = (
            effective_profile
            if spec.key == "GDA_DEPLOYMENT_PROFILE"
            else raw
        )
        parsed, parse_error = _parse_value(spec, value_to_parse)
        if spec.key == "GDA_DEPLOYMENT_PROFILE" and profile is not None:
            source = "argument"
        else:
            source = "environment" if raw is not None and str(raw).strip() else (
                "default" if spec.default is not None else "unset"
            )
        configured = parsed is not None
        entry = {
            "type": spec.value_type,
            "owner": spec.owner,
            "source": source,
            "configured": configured,
            "secret": spec.secret,
        }
        if spec.secret:
            entry["value"] = "<redacted>" if configured else None
        else:
            entry["value"] = parsed
        entries[spec.key] = entry
        parsed_values[spec.key] = parsed
        if parse_error:
            errors.append(_issue(spec.key, "invalid_value", parse_error))
        if effective_profile in spec.required_profiles and not configured:
            errors.append(
                _issue(spec.key, "required", f"required in {effective_profile}")
            )
        if spec.secret and raw and _is_placeholder_secret(str(raw)):
            target = (
                errors
                if effective_profile in {"staging", "production"}
                else warnings
            )
            target.append(
                _issue(spec.key, "placeholder_secret", "placeholder secret is configured")
            )

    _validate_database_config(env, effective_profile, parsed_values, errors, warnings)
    _validate_auth_config(env, effective_profile, errors, warnings)
    _validate_storage_config(env, effective_profile, parsed_values, errors, warnings)
    _validate_model_config(env, effective_profile, parsed_values, errors, warnings)
    _validate_runtime_config(effective_profile, parsed_values, errors, warnings)

    safe_snapshot = {
        key: {
            "source": entry["source"],
            "configured": entry["configured"],
            "value": entry["value"],
        }
        for key, entry in sorted(entries.items())
    }
    fingerprint = _json_fingerprint(
        {"profile": effective_profile, "config": safe_snapshot}
    )
    valid = not errors
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": effective_profile,
        "strict": strict,
        "valid": valid,
        "startup_allowed": valid or not strict,
        "config_fingerprint": fingerprint,
        "entries": entries,
        "errors": errors,
        "warnings": warnings,
    }


def _validate_database_config(
    env: Mapping[str, str],
    profile: str,
    parsed: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    backend = parsed.get("DB_BACKEND") or "postgres"
    if profile == "production" and backend != "postgres":
        errors.append(
            _issue("DB_BACKEND", "production_backend", "production requires postgres")
        )
    if backend != "postgres":
        return
    resolved = resolve_database_url(env)
    if not resolved:
        target = errors if profile in {"staging", "production"} else warnings
        target.append(
            _issue(
                "DATABASE_URL",
                "database_unconfigured",
                "set DATABASE_URL or POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DATABASE",
            )
        )
        return
    direct = str(env.get("DATABASE_URL") or "").strip()
    component_complete = all(
        str(env.get(key) or "").strip()
        for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DATABASE")
    )
    if direct and component_complete:
        component_values = dict(env)
        component_values.pop("DATABASE_URL", None)
        component_url = resolve_database_url(component_values)
        if component_url and _database_identity(direct) != _database_identity(component_url):
            errors.append(
                _issue(
                    "DATABASE_URL",
                    "database_source_conflict",
                    "DATABASE_URL and POSTGRES_* identify different databases",
                )
            )
    if parsed.get("ASYNC_POOL_MIN") is not None and parsed.get("ASYNC_POOL_MAX") is not None:
        if parsed["ASYNC_POOL_MIN"] > parsed["ASYNC_POOL_MAX"]:
            errors.append(
                _issue(
                    "ASYNC_POOL_MIN",
                    "pool_range",
                    "ASYNC_POOL_MIN must be <= ASYNC_POOL_MAX",
                )
            )


def _validate_auth_config(
    env: Mapping[str, str],
    profile: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    secret = str(env.get("CHAINLIT_AUTH_SECRET") or "")
    if not secret:
        target = errors if profile in {"staging", "production"} else warnings
        target.append(
            _issue("CHAINLIT_AUTH_SECRET", "auth_secret_missing", "authentication secret is not configured")
        )
    elif profile in {"staging", "production"} and len(secret) < 32:
        errors.append(
            _issue(
                "CHAINLIT_AUTH_SECRET",
                "auth_secret_short",
                f"{profile} secret must be at least 32 characters",
            )
        )


def _validate_storage_config(
    env: Mapping[str, str],
    profile: str,
    parsed: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    provider = parsed.get("CLOUD_STORAGE_PROVIDER")
    if not provider:
        target = errors if profile == "production" else warnings
        target.append(
            _issue("CLOUD_STORAGE_PROVIDER", "storage_unconfigured", "no object storage provider is configured")
        )
        return
    requirements = {
        "aws": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_S3_BUCKET"),
        "huawei": ("HUAWEI_OBS_AK", "HUAWEI_OBS_SK", "HUAWEI_OBS_SERVER", "HUAWEI_OBS_BUCKET"),
        "gcs": ("GCS_BUCKET",),
    }
    missing = [key for key in requirements[provider] if not str(env.get(key) or "").strip()]
    if missing:
        target = errors if profile in {"staging", "production"} else warnings
        target.append(
            _issue(
                "CLOUD_STORAGE_PROVIDER",
                "storage_incomplete",
                f"{provider} configuration is missing: {', '.join(missing)}",
            )
        )
def _validate_model_config(
    env: Mapping[str, str],
    profile: str,
    parsed: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    vertex_ready = bool(parsed.get("GOOGLE_GENAI_USE_VERTEXAI") and env.get("GOOGLE_CLOUD_PROJECT"))
    model_ready = bool(env.get("GOOGLE_API_KEY") or env.get("OLLAMA_API_BASE") or vertex_ready)
    if not model_ready:
        target = errors if profile in {"staging", "production"} else warnings
        target.append(
            _issue(
                "ROUTER_MODEL",
                "model_provider_unconfigured",
                "configure Ollama, Google API key, or Vertex AI project",
            )
        )


def _validate_runtime_config(
    profile: str,
    parsed: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    l1 = parsed.get("SPARK_L1_MAX_MB")
    l2 = parsed.get("SPARK_L2_MAX_MB")
    if l1 is not None and l2 is not None and l1 >= l2:
        errors.append(
            _issue("SPARK_L1_MAX_MB", "spark_tier_range", "SPARK_L1_MAX_MB must be less than SPARK_L2_MAX_MB")
        )
    if parsed.get("SPARK_BACKEND") == "livy" and not parsed.get("SPARK_LIVY_URL"):
        errors.append(
            _issue("SPARK_LIVY_URL", "livy_url_missing", "SPARK_LIVY_URL is required for the livy backend")
        )
    if profile == "production" and parsed.get("SELF_EVOLUTION_SCHEDULER_ENABLED"):
        warnings.append(
            _issue(
                "SELF_EVOLUTION_SCHEDULER_ENABLED",
                "legacy_scheduler_enabled",
                "self-evolution still uses a process-local scheduler",
            )
        )
    if parsed.get("DOLPHINSCHEDULER_COMMAND_WORKER_ENABLED"):
        required = (
            "DOLPHINSCHEDULER_BASE_URL",
            "DOLPHINSCHEDULER_TOKEN_FILE",
            "DOLPHINSCHEDULER_PROJECT_CODE",
            "DOLPHINSCHEDULER_WORKLOAD_SUBJECT",
            "DOLPHINSCHEDULER_POLICY_EVALUATOR_SUBJECT",
            "DOLPHINSCHEDULER_COMMAND_TENANT_ID",
            "DOLPHINSCHEDULER_COMMAND_WORKER_ID",
        )
        for key in required:
            if not parsed.get(key):
                errors.append(
                    _issue(
                        key,
                        "dolphinscheduler_worker_required",
                        f"{key} is required when the command worker is enabled",
                    )
                )
    provider_timeout = parsed.get("DOLPHINSCHEDULER_REQUEST_TIMEOUT_SECONDS")
    command_lease = parsed.get("DOLPHINSCHEDULER_COMMAND_LEASE_SECONDS")
    if (
        provider_timeout is not None
        and command_lease is not None
        and command_lease <= provider_timeout
    ):
        errors.append(
            _issue(
                "DOLPHINSCHEDULER_COMMAND_LEASE_SECONDS",
                "dolphinscheduler_lease_timeout",
                "command lease must exceed provider request timeout",
            )
        )
    poll_interval = parsed.get(
        "DOLPHINSCHEDULER_COMMAND_POLL_INTERVAL_SECONDS"
    )
    health_max_age = parsed.get(
        "DOLPHINSCHEDULER_COMMAND_HEALTH_MAX_AGE_SECONDS"
    )
    if (
        poll_interval is not None
        and health_max_age is not None
        and health_max_age < poll_interval * 2
    ):
        errors.append(
            _issue(
                "DOLPHINSCHEDULER_COMMAND_HEALTH_MAX_AGE_SECONDS",
                "dolphinscheduler_health_window",
                "health max age must cover at least two polling intervals",
            )
        )


def assert_startup_config(
    values: Mapping[str, str] | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    """Return the config report or raise when strict startup is not allowed."""
    report = build_config_report(values, profile=profile)
    if not report["startup_allowed"]:
        summary = "; ".join(
            f"{issue['key']}:{issue['code']}" for issue in report["errors"]
        )
        raise PlatformTruthError(f"strict configuration validation failed: {summary}")
    return report


def _is_production_source(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if path.name.startswith(("test_", "integration_test_")) or path.name.endswith(
        "_test.py"
    ):
        return False
    return not any(part in _IGNORED_SOURCE_PARTS for part in relative.parts)


class _EnvironmentAccessVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.keys: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in {"os.environ.get", "os.getenv", "environ.get", "getenv"} and node.args:
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                self.keys.add(node.args[0].value)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _call_name(node.value) in {"os.environ", "environ"}:
            key_node = node.slice
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                self.keys.add(key_node.value)
        self.generic_visit(node)


class _RuntimePrimitiveVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.primitives: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in {"asyncio.create_task", "asyncio.ensure_future", "ensure_future"}:
            self.primitives.add("async_task")
        elif name.endswith(".create_task"):
            self.primitives.add("loop_task")
        elif name in {"threading.Thread", "Thread"}:
            self.primitives.add("thread")
        elif name.endswith("ThreadPoolExecutor"):
            self.primitives.add("thread_pool")
        elif name.endswith("ProcessPoolExecutor"):
            self.primitives.add("process_pool")
        elif name.endswith("AsyncIOScheduler"):
            self.primitives.add("scheduler")
        elif name in {"subprocess.Popen", "asyncio.create_subprocess_exec"}:
            self.primitives.add("subprocess")
        self.generic_visit(node)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _scan_python_sources(
    source_root: Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]], list[str]]:
    env_accesses: dict[str, set[str]] = {}
    runtime_primitives: dict[str, set[str]] = {}
    parse_errors: list[str] = []
    display_root = source_root.parent
    for path in sorted(source_root.rglob("*.py")):
        if not _is_production_source(path, source_root):
            continue
        relative = path.relative_to(display_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            parse_errors.append(f"{relative}: {exc}")
            continue
        env_visitor = _EnvironmentAccessVisitor()
        env_visitor.visit(tree)
        for key in env_visitor.keys:
            env_accesses.setdefault(key, set()).add(relative)
        runtime_visitor = _RuntimePrimitiveVisitor()
        runtime_visitor.visit(tree)
        if runtime_visitor.primitives:
            runtime_primitives[relative] = runtime_visitor.primitives
    return env_accesses, runtime_primitives, parse_errors


def environment_access_report(source_root: Path | None = None) -> dict[str, Any]:
    root = (source_root or SOURCE_ROOT).resolve()
    accesses, _, parse_errors = _scan_python_sources(root)
    normalized = {key: sorted(paths) for key, paths in sorted(accesses.items())}
    fingerprint = _json_fingerprint(normalized)
    return {
        "fingerprint": fingerprint,
        "baseline_fingerprint": ENV_ACCESS_BASELINE_FINGERPRINT,
        "matches_baseline": fingerprint == ENV_ACCESS_BASELINE_FINGERPRINT,
        "key_count": len(normalized),
        "accesses": normalized,
        "parse_errors": parse_errors,
    }


def build_runtime_report(source_root: Path | None = None) -> dict[str, Any]:
    root = (source_root or SOURCE_ROOT).resolve()
    project_root = root.parent
    errors: list[str] = []
    runtime_ids = [spec.runtime_id for spec in RUNTIME_INVENTORY]
    if len(runtime_ids) != len(set(runtime_ids)):
        errors.append("runtime IDs must be unique")
    registered_paths = {
        path for spec in RUNTIME_INVENTORY for path in spec.code_paths
    }
    for spec in RUNTIME_INVENTORY:
        for relative, marker in spec.evidence:
            path = project_root / relative
            if not path.exists():
                errors.append(f"{spec.runtime_id}: missing evidence file {relative}")
                continue
            if marker not in path.read_text(encoding="utf-8"):
                errors.append(
                    f"{spec.runtime_id}: missing evidence marker {marker!r} in {relative}"
                )

    _, primitives, parse_errors = _scan_python_sources(root)
    errors.extend(parse_errors)
    detected_primitives = {
        path: sorted(kinds) for path, kinds in sorted(primitives.items())
    }
    detected_fingerprint = _json_fingerprint(detected_primitives)
    if detected_fingerprint != RUNTIME_PRIMITIVE_BASELINE_FINGERPRINT:
        errors.append(
            "runtime primitive fingerprint changed; review the runtime inventory"
        )
    unregistered = {
        path: sorted(kinds)
        for path, kinds in sorted(primitives.items())
        if path not in registered_paths
    }
    for path, kinds in unregistered.items():
        errors.append(
            f"unregistered runtime primitives in {path}: {', '.join(kinds)}"
        )
    inventory = [asdict(spec) for spec in RUNTIME_INVENTORY]
    blockers = [
        spec.runtime_id for spec in RUNTIME_INVENTORY if spec.replacement_required
    ]
    return {
        "status": "valid" if not errors else "invalid",
        "inventory_fingerprint": _json_fingerprint(inventory),
        "detected_primitives_fingerprint": detected_fingerprint,
        "baseline_primitives_fingerprint": RUNTIME_PRIMITIVE_BASELINE_FINGERPRINT,
        "matches_primitive_baseline": (
            detected_fingerprint == RUNTIME_PRIMITIVE_BASELINE_FINGERPRINT
        ),
        "runtime_count": len(inventory),
        "inventory": inventory,
        "detected_primitives": detected_primitives,
        "unregistered_primitives": unregistered,
        "production_ready": not blockers and not errors,
        "production_blockers": blockers,
        "errors": errors,
    }


def validate_static_contract(source_root: Path | None = None) -> dict[str, Any]:
    env_report = environment_access_report(source_root)
    runtime_report = build_runtime_report(source_root)
    config_keys = [spec.key for spec in CONFIG_SPECS]
    errors: list[str] = []
    if len(config_keys) != len(set(config_keys)):
        errors.append("config keys must be unique")
    if not env_report["matches_baseline"]:
        errors.append(
            "environment access fingerprint changed; register/review config access"
        )
    errors.extend(runtime_report["errors"])
    return {
        "schema": REPORT_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "config_spec_count": len(CONFIG_SPECS),
        "config_registry_fingerprint": _json_fingerprint(
            [asdict(spec) for spec in CONFIG_SPECS]
        ),
        "environment_access": env_report,
        "runtime": runtime_report,
        "errors": errors,
    }


def build_platform_snapshot(
    values: Mapping[str, str] | None = None,
    *,
    profile: str | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    config = build_config_report(values, profile=profile)
    runtime = build_runtime_report(source_root)
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "runtime": runtime,
        "platform_fingerprint": _json_fingerprint(
            {
                "config": config["config_fingerprint"],
                "runtime": runtime["inventory_fingerprint"],
            }
        ),
    }


def compare_platform_snapshots(
    left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    fields = {
        "platform_fingerprint": (
            left.get("platform_fingerprint"),
            right.get("platform_fingerprint"),
        ),
        "config_fingerprint": (
            (left.get("config") or {}).get("config_fingerprint"),
            (right.get("config") or {}).get("config_fingerprint"),
        ),
        "runtime_fingerprint": (
            (left.get("runtime") or {}).get("inventory_fingerprint"),
            (right.get("runtime") or {}).get("inventory_fingerprint"),
        ),
    }
    differences = {
        field: {"left": values[0], "right": values[1]}
        for field, values in fields.items()
        if values[0] != values[1]
    }
    return {"match": not differences, "differences": differences}


def _json_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _print_report(report: dict[str, Any], output: str | None = None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--source-root", default=str(SOURCE_ROOT))
    validate_parser.add_argument("--output")
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--profile")
    snapshot_parser.add_argument("--source-root", default=str(SOURCE_ROOT))
    snapshot_parser.add_argument("--output")
    runtime_parser = subparsers.add_parser("runtime")
    runtime_parser.add_argument("--source-root", default=str(SOURCE_ROOT))
    runtime_parser.add_argument("--output")
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("left")
    compare_parser.add_argument("right")

    args = parser.parse_args(argv)
    if args.command == "validate":
        report = validate_static_contract(Path(args.source_root))
        _print_report(report, args.output)
        return 0 if report["status"] == "valid" else 1
    if args.command == "runtime":
        report = build_runtime_report(Path(args.source_root))
        _print_report(report, args.output)
        return 0 if report["status"] == "valid" else 1
    if args.command == "snapshot":
        report = build_platform_snapshot(
            profile=args.profile,
            source_root=Path(args.source_root),
        )
        _print_report(report, args.output)
        return 0 if report["config"]["startup_allowed"] else 1

    left = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right = json.loads(Path(args.right).read_text(encoding="utf-8"))
    report = compare_platform_snapshots(left, right)
    _print_report(report)
    return 0 if report["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
