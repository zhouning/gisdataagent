#!/usr/bin/env python3
"""Rehearse Kubernetes discovery-worker takeover on a real Temporal start target."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import Field, model_validator
from temporalio import workflow
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from data_agent.agentops_temporal_adapter import (
        TEMPORAL_START_RECONCILIATION_SCHEMA,
        TemporalProviderStartStatus,
        TemporalStartReconciliation,
        TemporalStartReconciliationVerdict,
        TemporalWorkflowStartRequest,
    )
    from data_agent.agentops_temporal_contracts import temporal_contract_fingerprint
    from data_agent.agentops_temporal_start_target_authority import (
        PostgresAgentOpsTemporalStartTargetAuthority,
    )
    from data_agent.agentops_temporalio_provider import TemporalioProviderClient
    from data_agent.platform_contracts import FrozenContract, canonical_json_fingerprint

NAMESPACE_REF = "gda-agentops-sandbox"
TENANT_ID = "local-dev"
WORKFLOW_TYPE = "gda.agentops.kubernetes-business-target.v1"
TASK_QUEUE = "agentops-kubernetes-business-target"
WORKER_ID = "workload:agentops-kubernetes-business-target"
DISCOVERY_DEPLOYMENT = "gis-agent-agentops-discovery"
TEMPORAL_DEPLOYMENT = "gis-agent-temporal"
DISCOVERY_NAMESPACE = "gda-agentops-sandbox"


@workflow.defn(name=WORKFLOW_TYPE)
class KubernetesBusinessTargetWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, str]:
        await workflow.sleep(90)
        return {"workflow_id": payload["identity"]["workflow_id"]}


class _SubmitThenRaiseClient:
    def __init__(self, client: Client) -> None:
        self._client = client
        self.data_converter = client.data_converter

    async def start_workflow(self, *args: Any, **kwargs: Any) -> Any:
        await self._client.start_workflow(*args, **kwargs)
        raise RuntimeError("simulated transport loss after Temporal accepted start")

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None) -> Any:
        return self._client.get_workflow_handle(workflow_id, run_id=run_id)


class BusinessTargetRehearsalReport(FrozenContract):
    schema_id: ClassVar[str] = "gda.agentops-temporal-discovery-kubernetes-business-target.v1"
    checked_at: datetime
    namespace_ref: str
    tenant_id: str
    workflow_id: str
    provider_run_id: str
    temporal_server_version: str
    temporal_sdk_version: str
    first_claimed_by: str
    takeover_claimed_by: str
    takeover_pod_name: str
    first_claimed_at: datetime
    takeover_observed_at: datetime
    lease_wait_seconds: float
    target_attempt_count: int = Field(ge=0)
    temporal_history_event_count: int = Field(ge=1)
    history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    production_readiness_claimed: bool = False
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash_matches(self) -> BusinessTargetRehearsalReport:
        values = self.model_dump(mode="json")
        supplied = values.pop("report_sha256")
        if supplied != canonical_json_fingerprint(values):
            raise ValueError("business target rehearsal report hash is invalid")
        return self


def _dockerless_kubectl(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["kubectl", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        input=input_text,
    )
    return result.stdout.strip()


def _kubectl(*args: str, input_text: str | None = None) -> str:
    return _dockerless_kubectl(*args, input_text=input_text)


def _wait_for_temporal_ready(timeout_seconds: float = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            ready = _kubectl(
                "get",
                "deployment",
                TEMPORAL_DEPLOYMENT,
                "-n",
                DISCOVERY_NAMESPACE,
                "-o",
                "jsonpath={.status.readyReplicas}",
            )
            if ready == "1":
                return
        except subprocess.SubprocessError:
            pass
        time.sleep(1)
    raise RuntimeError("Temporal deployment did not become ready")


def _scale_temporal(replicas: int) -> None:
    _kubectl(
        "scale",
        "deployment",
        TEMPORAL_DEPLOYMENT,
        "-n",
        DISCOVERY_NAMESPACE,
        f"--replicas={replicas}",
    )


def _scale_discovery(replicas: int) -> None:
    _kubectl(
        "scale",
        "deployment",
        DISCOVERY_DEPLOYMENT,
        "-n",
        DISCOVERY_NAMESPACE,
        f"--replicas={replicas}",
    )


def _deployment_replicas(deployment: str) -> int:
    value = _kubectl(
        "get",
        "deployment",
        deployment,
        "-n",
        DISCOVERY_NAMESPACE,
        "-o",
        "jsonpath={.spec.replicas}",
    )
    return int(value or "0")


def _wait_for_deployment_ready(
    deployment: str, expected_replicas: int, timeout_seconds: float = 180
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if expected_replicas == 0:
                pods = json.loads(
                    _kubectl(
                        "get",
                        "pods",
                        "-n",
                        DISCOVERY_NAMESPACE,
                        "-l",
                        "app.kubernetes.io/name=gis-agent-agentops-discovery",
                        "-o",
                        "json",
                    )
                )
                if not pods.get("items"):
                    return
            ready = int(
                _kubectl(
                    "get",
                    "deployment",
                    deployment,
                    "-n",
                    DISCOVERY_NAMESPACE,
                    "-o",
                    "jsonpath={.status.readyReplicas}",
                )
                or "0"
            )
            available = int(
                _kubectl(
                    "get",
                    "deployment",
                    deployment,
                    "-n",
                    DISCOVERY_NAMESPACE,
                    "-o",
                    "jsonpath={.status.availableReplicas}",
                )
                or "0"
            )
            if ready >= expected_replicas and available >= expected_replicas:
                return
        except (subprocess.SubprocessError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError(
        f"{deployment} did not become ready with {expected_replicas} replicas"
    )


def _delete_pod(pod_name: str, *, force: bool = False) -> None:
    args = ["delete", "pod", pod_name, "-n", DISCOVERY_NAMESPACE, "--wait=false"]
    if force:
        args.extend(["--grace-period=0", "--force"])
    _kubectl(*args)


def _wait_for_pod_phase(
    pod_name: str, expected_phase: str, timeout_seconds: float = 90
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            phase = _kubectl(
                "get",
                "pod",
                pod_name,
                "-n",
                DISCOVERY_NAMESPACE,
                "-o",
                "jsonpath={.status.phase}",
            )
            if phase == expected_phase:
                return
            if phase in {"Failed", "Unknown"}:
                logs = ""
                try:
                    logs = _kubectl(
                        "logs", pod_name, "-n", DISCOVERY_NAMESPACE, "--tail=40"
                    )
                except subprocess.SubprocessError:
                    pass
                raise RuntimeError(f"rehearsal Pod entered {phase}: {logs[-2000:]}")
        except subprocess.CalledProcessError:
            pass
        time.sleep(1)
    raise RuntimeError(f"rehearsal Pod {pod_name} did not reach {expected_phase}")


def _wait_for_pod_deleted(pod_name: str, timeout_seconds: float = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            _kubectl("get", "pod", pod_name, "-n", DISCOVERY_NAMESPACE)
        except subprocess.CalledProcessError:
            return
        time.sleep(0.5)
    raise RuntimeError(f"rehearsal Pod {pod_name} was not deleted")


def _pod_exists(pod_name: str) -> bool:
    try:
        _kubectl("get", "pod", pod_name, "-n", DISCOVERY_NAMESPACE)
    except subprocess.CalledProcessError:
        return False
    return True


def _holder_code(target_id: str) -> str:
    return "\n".join(
        [
            "import os,time",
            "from uuid import UUID",
            "from sqlalchemy import create_engine",
            "from data_agent.agentops_temporal_start_target_authority import "
            "PostgresAgentOpsTemporalStartTargetAuthority",
            f"target_id=UUID('{target_id}')",
            "tenant=os.environ['GDA_AGENTOPS_RECONCILER_TENANT_ID']",
            "namespace=os.environ['GDA_AGENTOPS_RECONCILER_NAMESPACE']",
            "worker=os.environ['GDA_AGENTOPS_RECONCILER_WORKER_ID']",
            "authority=PostgresAgentOpsTemporalStartTargetAuthority("
            "create_engine(os.environ['DATABASE_URL']))",
            "deadline=time.monotonic()+60",
            "claimed=None",
            "while time.monotonic()<deadline and claimed is None:",
            "    current=authority.get_target(tenant_id=tenant,target_id=target_id)",
            "    if current is not None and current.status=='claimed' and "
            "current.claimed_by==worker: claimed=current; break",
            "    for candidate in authority.claim_due_targets(tenant_id=tenant, "
            "namespace_ref=namespace,worker_id=worker,limit=10,lease_seconds=60):",
            "        if candidate.target_id==target_id: claimed=candidate; break",
            "        try: authority.release_target_claim(candidate,worker_id=worker, "
            "error='rehearsal target filter',retry_after_seconds=1)",
            "        except Exception: pass",
            "    if claimed is None: time.sleep(0.2)",
            "if claimed is None: raise SystemExit('target was not claimed by holder Pod')",
            "print('claimed:'+str(claimed.target_id)+':'+worker,flush=True)",
            "while True: time.sleep(300)",
        ]
    )


def _create_holder_pod(target_id: str) -> tuple[str, str]:
    deployment = json.loads(
        _kubectl(
            "get",
            "deployment",
            DISCOVERY_DEPLOYMENT,
            "-n",
            DISCOVERY_NAMESPACE,
            "-o",
            "json",
        )
    )
    pod_name = f"gda-agentops-lease-holder-{uuid4().hex[:12]}"
    template = deployment["spec"]["template"]
    pod_spec = json.loads(json.dumps(template["spec"]))
    container = next(item for item in pod_spec["containers"] if item["name"] == "discovery")
    container["command"] = [
        "python",
        "-c",
        _holder_code(target_id),
    ]
    container.pop("args", None)
    env = list(container.get("env", []))
    env.extend(
        [
            {"name": "GDA_AGENTOPS_RECONCILER_TENANT_ID", "value": TENANT_ID},
            {"name": "GDA_AGENTOPS_RECONCILER_NAMESPACE", "value": NAMESPACE_REF},
            {
                "name": "GDA_AGENTOPS_RECONCILER_WORKER_ID",
                "value": f"workload:agentops-discovery:{pod_name}",
            },
        ]
    )
    container["env"] = env
    pod_spec["restartPolicy"] = "Never"
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": DISCOVERY_NAMESPACE,
            "labels": {
                # Keep the production discovery labels so the sandbox NetworkPolicy
                # grants this temporary Pod the same PostgreSQL access as a worker.
                "app.kubernetes.io/name": "gis-agent-agentops-discovery",
                "app.kubernetes.io/component": "agentops-discovery",
            },
        },
        "spec": pod_spec,
    }
    _kubectl(
        "create",
        "-f",
        "-",
        input_text=json.dumps(pod, separators=(",", ":")),
    )
    return pod_name, f"workload:agentops-discovery:{pod_name}"


def _build_start_request(*, workflow_id: str) -> TemporalWorkflowStartRequest:
    identity = {
        "tenant_id": TENANT_ID,
        "namespace": {
            "tenant_id": TENANT_ID,
            "isolation_class": "tenant",
            "namespace_ref": NAMESPACE_REF,
            "namespace_sha256": "0" * 64,
        },
        "task_queue": {
            "tenant_id": TENANT_ID,
            "namespace_ref": NAMESPACE_REF,
            "queue_ref": TASK_QUEUE,
            "worker_identity_ref": WORKER_ID,
            "queue_sha256": "0" * 64,
        },
        "workflow_type": WORKFLOW_TYPE,
        "agent_spec_sha256": "1" * 64,
        "deployment_revision_sha256": "2" * 64,
        "idempotency_key": f"kubernetes-business-target:{uuid4()}",
        "workflow_id": workflow_id,
        "identity_sha256": "3" * 64,
    }
    payload = {
        "identity": identity,
        "policy_decision_ref": "artifact://agentops/kubernetes-business-target-policy",
        "business_target": {
            "kind": "agentops.discovery.lease_takeover",
            "source": "Temporal start target authority",
        },
    }
    values = {
        "tenant_id": TENANT_ID,
        "namespace_ref": NAMESPACE_REF,
        "workflow_id": workflow_id,
        "workflow_type": WORKFLOW_TYPE,
        "task_queue_ref": TASK_QUEUE,
        "policy_decision_ref": payload["policy_decision_ref"],
        "payload": payload,
    }
    values["payload_sha256"] = canonical_json_fingerprint(
        {"schema": "gda.temporal_start_request.v1", "data": values}
    )
    return TemporalWorkflowStartRequest(**values)


async def run_rehearsal(
    *,
    frontend_target: str,
    database_url: str,
    report_path: Path,
    history_path: Path,
) -> BusinessTargetRehearsalReport:
    workflow_id = f"gda-agentops-k8s-business-target-{uuid4().hex[:16]}"
    request = _build_start_request(workflow_id=workflow_id)
    client = await Client.connect(frontend_target, namespace=NAMESPACE_REF, identity=WORKER_ID)
    from sqlalchemy import create_engine

    engine = create_engine(database_url)
    target_authority = PostgresAgentOpsTemporalStartTargetAuthority(engine)
    original_discovery_replicas = _deployment_replicas(DISCOVERY_DEPLOYMENT)
    holder_pod = ""
    holder_worker = ""
    target = None
    workflow_started = False
    first_claimed_by = ""
    takeover_claimed_by = ""
    takeover_pod_name = ""
    first_claimed_at = datetime.now(UTC)
    takeover_observed_at = datetime.now(UTC)
    lease_wait_seconds = 0.0
    try:
        # Stop managed workers before registering the target.  A dedicated Pod with
        # the same image, Secret and worker identity claims the target and remains
        # alive until this rehearsal deletes it, removing a reconciliation race.
        _scale_discovery(0)
        _wait_for_deployment_ready(DISCOVERY_DEPLOYMENT, 0)
        async with Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[KubernetesBusinessTargetWorkflow],
        ):
            provider = TemporalioProviderClient(
                _SubmitThenRaiseClient(client), namespace_ref=NAMESPACE_REF
            )
            unknown = await provider.start_workflow(
                tenant_id=TENANT_ID,
                namespace_ref=NAMESPACE_REF,
                workflow_id=workflow_id,
                workflow_type=WORKFLOW_TYPE,
                task_queue_ref=TASK_QUEUE,
                payload=request.payload,
                retry_policy={
                    "initial_interval_seconds": 1.0,
                    "backoff_coefficient": 2.0,
                    "max_interval_seconds": 10.0,
                    "max_attempts": 1,
                    "non_retryable_error_types": [],
                },
            )
            workflow_started = True
            reconciliation_values = {
                "tenant_id": request.tenant_id,
                "namespace_ref": request.namespace_ref,
                "workflow_id": request.workflow_id,
                "provider_status": unknown.status,
                "verdict": TemporalStartReconciliationVerdict.UNKNOWN_PENDING,
                "provider_run_id": None,
                "provider_receipt_ref": unknown.provider_receipt_ref,
                "request_sha256": request.payload_sha256,
                "observed_input_sha256": None,
            }
            reconciliation_values["reconciliation_sha256"] = temporal_contract_fingerprint(
                TEMPORAL_START_RECONCILIATION_SCHEMA,
                reconciliation_values,
                "reconciliation_sha256",
            )
            reconciliation = TemporalStartReconciliation(**reconciliation_values)
            target = target_authority.register_start_target(
                request,
                unknown,
                reconciliation,
                registered_by=WORKER_ID,
                # Put this target ahead of stale rehearsal rows that may still be
                # retrying in the shared sandbox control database.
                available_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            if unknown.status is not TemporalProviderStartStatus.UNKNOWN:
                raise RuntimeError("provider did not return an unknown start receipt")

            holder_pod, holder_worker = _create_holder_pod(str(target.target_id))
            _wait_for_pod_phase(holder_pod, "Running")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                target = target_authority.get_target(
                    tenant_id=TENANT_ID, target_id=target.target_id
                ) or target
                if target.status == "claimed" and target.claimed_by == holder_worker:
                    first_claimed_by = target.claimed_by
                    first_claimed_at = datetime.now(UTC)
                    break
                await asyncio.sleep(0.2)
            if not first_claimed_by:
                logs = _kubectl("logs", holder_pod, "-n", DISCOVERY_NAMESPACE, "--tail=40")
                raise RuntimeError(
                    "Kubernetes rehearsal holder did not claim business target: "
                    + logs[-2000:]
                )

            lease_expiry = target.claimed_until
            if lease_expiry is None:
                raise RuntimeError("claimed target has no lease expiry")
            _delete_pod(holder_pod, force=True)
            _wait_for_pod_deleted(holder_pod)
            _scale_discovery(1)
            _wait_for_deployment_ready(DISCOVERY_DEPLOYMENT, 1)
            takeover_pod_name = _kubectl(
                "get",
                "pods",
                "-n",
                DISCOVERY_NAMESPACE,
                "-l",
                "app.kubernetes.io/name=gis-agent-agentops-discovery",
                "-o",
                "jsonpath={.items[0].metadata.name}",
            )
            if not takeover_pod_name:
                raise RuntimeError("no managed discovery Pod was ready for takeover")
            takeover_claimed_by = f"workload:agentops-discovery:{takeover_pod_name}"
            remaining = (lease_expiry - datetime.now(UTC)).total_seconds()
            if remaining > 0:
                await asyncio.sleep(remaining + 2)
            lease_wait_seconds = max(0.0, (datetime.now(UTC) - first_claimed_at).total_seconds())

            takeover_deadline = time.monotonic() + 90
            settled = target
            while time.monotonic() < takeover_deadline:
                settled = target_authority.get_target(
                    tenant_id=TENANT_ID, target_id=target.target_id
                ) or settled
                if (
                    settled.status in {"ready", "completed"}
                    and settled.provider_run_id
                    and settled.attempt_count >= target.attempt_count + 1
                ):
                    takeover_observed_at = datetime.now(UTC)
                    break
                await asyncio.sleep(0.25)
            if settled.provider_run_id is None:
                raise RuntimeError("business target was not reconciled after lease takeover")

            observer = TemporalioProviderClient(client, namespace_ref=NAMESPACE_REF)
            input_observation = await observer.observe_workflow_input(
                tenant_id=TENANT_ID,
                namespace_ref=NAMESPACE_REF,
                workflow_id=workflow_id,
                provider_run_id=settled.provider_run_id,
            )
            history = await client.get_workflow_handle(
                workflow_id, run_id=settled.provider_run_id
            ).fetch_history()
            history_events = list(getattr(history, "events", ()) or ())
            history_json = history.to_json()
            checks = {
                "unknown_start_registered": unknown.status is TemporalProviderStartStatus.UNKNOWN,
                "first_discovery_pod_claimed_target": first_claimed_by == holder_worker,
                "first_claimed_pod_was_terminated": not _pod_exists(holder_pod),
                "managed_discovery_pod_was_restored": bool(takeover_pod_name),
                "lease_expired_before_takeover": settled.attempt_count >= target.attempt_count + 1,
                "second_worker_reconciled_input_and_attached_provider_run": bool(
                    settled.provider_run_id
                ),
                "second_worker_identity_is_bound_to_ready_pod": takeover_claimed_by
                == f"workload:agentops-discovery:{takeover_pod_name}",
                "target_ready_after_takeover": settled.status in {"ready", "completed"},
                "second_worker_observed_temporal_input": (
                    input_observation.observed_input_sha256 == request.payload_sha256
                ),
                "temporal_history_contains_start": len(history_events) >= 1,
                "target_tenant_is_local_dev": settled.tenant_id == TENANT_ID,
            }
            cluster = await client.service_client.workflow_service.get_cluster_info(
                GetClusterInfoRequest()
            )
            payload = {
                "checked_at": datetime.now(UTC),
                "namespace_ref": NAMESPACE_REF,
                "tenant_id": TENANT_ID,
                "workflow_id": workflow_id,
                "provider_run_id": settled.provider_run_id,
                "temporal_server_version": getattr(cluster, "server_version", "unknown"),
                "temporal_sdk_version": version("temporalio"),
                "first_claimed_by": first_claimed_by,
                "takeover_claimed_by": takeover_claimed_by,
                "takeover_pod_name": takeover_pod_name,
                "first_claimed_at": first_claimed_at,
                "takeover_observed_at": takeover_observed_at,
                "lease_wait_seconds": round(lease_wait_seconds, 3),
                "target_attempt_count": settled.attempt_count,
                "temporal_history_event_count": len(history_events),
                "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
                "checks": checks,
                "passed": all(checks.values()),
                "failure_reasons": tuple(name for name, passed in checks.items() if not passed),
                "production_readiness_claimed": False,
            }
            normalized = json.loads(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    default=lambda value: value.astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                )
            )
            report = BusinessTargetRehearsalReport(
                **payload, report_sha256=canonical_json_fingerprint(normalized)
            )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(history_json + "\n", encoding="utf-8")
            return report
    finally:
        if holder_pod:
            try:
                _delete_pod(holder_pod)
            except subprocess.SubprocessError:
                pass
        try:
            _scale_discovery(original_discovery_replicas)
            _wait_for_deployment_ready(DISCOVERY_DEPLOYMENT, original_discovery_replicas)
        except (RuntimeError, subprocess.SubprocessError):
            pass
        engine.dispose()
        if workflow_started:
            try:
                await client.get_workflow_handle(workflow_id).cancel()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), required=False)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("docs/reports/agentops_temporal_discovery_kubernetes_business_target_2026-08-28.json"),
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("docs/reports/agentops_temporal_discovery_kubernetes_business_target_history_2026-08-28.json"),
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    report = asyncio.run(
        run_rehearsal(
            frontend_target=args.frontend,
            database_url=args.database_url,
            report_path=args.report,
            history_path=args.history,
        )
    )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
