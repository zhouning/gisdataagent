#!/usr/bin/env python3
"""Run a real Temporal task graph with the bounded MMFE/GWM providers enabled."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import GetClusterInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer

from data_agent.agentops_contracts import AgentStepStatus, AgentToolCallStatus
from data_agent.agentops_specialist_providers import (
    BoundSpecialistExecutor,
    FilesystemSpecialistArtifactStore,
    SpecialistArtifactStore,
    SpecialistOperationAuthority,
    SpecialistOperationStatus,
    build_gwm_provider_spec,
    build_mmfe_provider_spec,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityOutcome,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_task_graph_execution import (
    TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,
)
from data_agent.agentops_temporal_task_graph_rehearsal import (
    REHEARSAL_WORKER_IDENTITY,
    build_rehearsal_execution_input,
    rehearsal_specialist_executor,
)
from data_agent.agentops_temporal_task_graph_runtime import (
    TASK_GRAPH_WORKFLOW_RESULT_SCHEMA,
    TASK_GRAPH_WORKFLOW_TYPE,
    TemporalTaskGraphWorkflow,
    build_specialist_activity_definition,
)
from data_agent.agentops_temporal_worker import (
    TemporalioWorkerFactory,
    TemporalWorkerDefinition,
    TemporalWorkerRuntimeConfig,
)
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowCheckpoint
from data_agent.platform_contracts import canonical_json_fingerprint

REPORT_SCHEMA = "gda.agentops_temporal_real_specialists_rehearsal_report.v1"
EXPECTED_WAVES = (
    ("coordinator",),
    ("planner",),
    ("data_engineer", "fusion", "gwm"),
    ("quality",),
)


def _write_geojson(path: Path, offset: float) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": 1},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[offset, 0], [offset + 1, 0], [offset + 1, 1], [offset, 1], [offset, 0]]
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_state_input(path: Path) -> None:
    payload = {
        "schema": "mmfe.uwm_state_input.v1",
        "version": "0.1",
        "source_product": {"product_id": "mmfe-provider-rehearsal-v1"},
        "urban_spatial_unit": {"unit_type": "district"},
        "object_role_registry": [],
        "state_components": {},
        "graph_summary": {},
        "production_policy": {"authoritative_data_required_for_production": True},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


async def run_rehearsal(
    *,
    frontend_target: str,
    namespace_ref: str,
    task_queue_ref: str,
    artifact_store_factory: Any | None = None,
    operation_authority: SpecialistOperationAuthority | None = None,
    retry_budget_authority: Any | None = None,
) -> tuple[dict[str, Any], str]:
    with tempfile.TemporaryDirectory(prefix="gda-real-specialists-") as temp_dir:
        root = Path(temp_dir)
        geo_a, geo_b, state = root / "a.geojson", root / "b.geojson", root / "state.json"
        _write_geojson(geo_a, 0)
        _write_geojson(geo_b, 0.25)
        _write_state_input(state)
        geo_a_id = UUID("00000000-0000-4000-8000-000000007201")
        geo_b_id = UUID("00000000-0000-4000-8000-000000007202")
        state_id = UUID("00000000-0000-4000-8000-000000007203")
        if artifact_store_factory is None:
            store: SpecialistArtifactStore = FilesystemSpecialistArtifactStore(root / "artifacts")
            store.register_input(
                tenant_id="planning",
                artifact_id=geo_a_id,
                source_path=geo_a,
                media_type="application/geo+json",
            )
            store.register_input(
                tenant_id="planning",
                artifact_id=geo_b_id,
                source_path=geo_b,
                media_type="application/geo+json",
            )
            store.register_input(
                tenant_id="planning",
                artifact_id=state_id,
                source_path=state,
                media_type="application/json",
            )
        else:
            store = artifact_store_factory(
                root,
                ((geo_a_id, geo_a, "application/geo+json"),
                 (geo_b_id, geo_b, "application/geo+json"),
                 (state_id, state, "application/json")),
            )

        # Keep MMFE output inside this disposable rehearsal directory.
        import data_agent.fusion.execution as fusion_execution

        fusion_output = root / "mmfe-fused.geojson"
        original_output_path = fusion_execution._generate_output_path
        fusion_execution._generate_output_path = lambda *_args: str(fusion_output)
        try:
            run_key = str(uuid4())
            execution_input = build_rehearsal_execution_input(
                namespace_ref=namespace_ref,
                task_queue_ref=task_queue_ref,
                run_key=run_key,
                input_artifact_ids=(geo_a_id, geo_b_id, state_id),
                provider_spec_by_agent={
                    "fusion": build_mmfe_provider_spec(
                        input_artifact_ids=(geo_a_id, geo_b_id), strategy="spatial_join"
                    ),
                    "gwm": build_gwm_provider_spec(
                        input_artifact_ids=(state_id,), observation_id="real-specialists-obs-1"
                    ),
                },
            )
            workflow_input = execution_input.workflow_input
            workflow_id = workflow_input.identity.workflow_id
            config = TemporalWorkerRuntimeConfig(
                tenant_id=workflow_input.tenant_id,
                namespace_ref=namespace_ref,
                frontend_target=frontend_target,
                task_queue_ref=task_queue_ref,
                worker_identity_ref=REHEARSAL_WORKER_IDENTITY,
                workflow_type=TASK_GRAPH_WORKFLOW_TYPE,
                activity_types=(TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE,),
                agent_spec_sha256=workflow_input.agent_spec_sha256,
                deployment_revision_sha256=workflow_input.deployment_revision.revision_sha256,
                max_concurrent_activities=6,
                max_concurrent_workflow_tasks=2,
            )
            client = await Client.connect(
                frontend_target, namespace=namespace_ref, identity=REHEARSAL_WORKER_IDENTITY
            )
            cluster = await client.service_client.workflow_service.get_cluster_info(
                GetClusterInfoRequest()
            )
            registration = config.registration()
            bound = BoundSpecialistExecutor(
                store,
                operation_authority=operation_authority,
                retry_budget_authority=retry_budget_authority,
                retry_budget_max_attempts=3,
                worker_id="workload:agentops-real-specialists",
            )

            async def real_or_rehearsal_executor(request):
                if request.provider_spec is not None:
                    return await bound(request)
                return rehearsal_specialist_executor(request)

            specialist_activity = build_specialist_activity_definition(real_or_rehearsal_executor)
            worker = TemporalioWorkerFactory(
                client,
                registration,
                workflows=(
                    TemporalWorkerDefinition(TASK_GRAPH_WORKFLOW_TYPE, TemporalTaskGraphWorkflow),
                ),
                activities=(
                    TemporalWorkerDefinition(
                        TASK_GRAPH_SPECIALIST_ACTIVITY_TYPE, specialist_activity
                    ),
                ),
            ).build()
            started_at = datetime.now(UTC)
            async with worker:
                handle = await client.start_workflow(
                    TASK_GRAPH_WORKFLOW_TYPE,
                    execution_input.model_dump(mode="json"),
                    id=workflow_id,
                    task_queue=task_queue_ref,
                )
                result = await handle.result()
                completed_at = datetime.now(UTC)
            worker_stopped_at = datetime.now(UTC)

            if (
                result.get("schema") != TASK_GRAPH_WORKFLOW_RESULT_SCHEMA
                or result.get("status") != "succeeded"
            ):
                raise RuntimeError(
                    f"real specialist workflow did not succeed: {result.get('status')}"
                )
            if result.get("workflow_result_sha256") != temporal_contract_fingerprint(
                TASK_GRAPH_WORKFLOW_RESULT_SCHEMA, result, "workflow_result_sha256"
            ):
                raise RuntimeError("workflow result fingerprint differs")
            if tuple(tuple(wave) for wave in result.get("execution_waves", ())) != EXPECTED_WAVES:
                raise RuntimeError("task graph execution waves differ")

            checkpoint = TemporalTaskGraphWorkflowCheckpoint.model_validate(result["checkpoint"])
            if any(
                step.status is not AgentStepStatus.SUCCEEDED
                for step in checkpoint.execution.step_states
            ):
                raise RuntimeError("checkpoint contains an unfinished step")
            if any(
                call.status is not AgentToolCallStatus.SUCCEEDED
                for call in checkpoint.execution.tool_calls
            ):
                raise RuntimeError("checkpoint contains an unfinished ToolCall")
            outcomes = tuple(item.outcome for item in checkpoint.activity_evidence)
            if (
                outcomes.count(TemporalActivityOutcome.SUCCEEDED) != 6
                or outcomes.count(TemporalActivityOutcome.FAILED) != 0
            ):
                raise RuntimeError(
                    "real provider run must contain six successful activities: "
                    f"{[item.value for item in outcomes]}"
                )
            provider_specs = {
                plan.agent_id: plan.provider_spec
                for plan in execution_input.execution_manifest.plans
                if plan.provider_spec is not None
            }
            provider_artifacts = []
            for agent_id, spec in provider_specs.items():
                call = next(
                    item
                    for item in checkpoint.execution.tool_calls
                    if item.step_id
                    == next(
                        plan.step_id
                        for plan in execution_input.execution_manifest.plans
                        if plan.agent_id == agent_id
                    )
                )
                evidence = next(
                    item
                    for item in checkpoint.activity_evidence
                    if item.tool_call_id == call.tool_call_id
                    and item.outcome is TemporalActivityOutcome.SUCCEEDED
                )
                artifact = store.resolve_input("planning", evidence.output_artifact_id)
                provider_artifacts.append(
                    {
                        "agent_id": agent_id,
                        "provider_ref": spec.provider_ref,
                        "operation_ref": spec.operation_ref,
                        "artifact_id": str(artifact.artifact_id),
                        "content_sha256": artifact.content_sha256,
                        "manifest": artifact.manifest,
                    }
                )

            operation_receipts: list[dict[str, Any]] = []
            operation_replay_verified = None
            if operation_authority is not None:
                provider_schedules = tuple(
                    schedule
                    for schedule in checkpoint.activity_schedules
                    if schedule.request.provider_spec is not None
                )
                if len(provider_schedules) != len(provider_specs):
                    raise RuntimeError(
                        "provider-bound activity schedules do not cover every provider specialist"
                    )

                def operation_ref_for(schedule):
                    provider_spec = schedule.request.provider_spec
                    assert provider_spec is not None
                    return f"{provider_spec.operation_ref}://{schedule.activity_id}"

                history_count_before = 0
                for schedule in provider_schedules:
                    operation_ref = operation_ref_for(schedule)
                    observation = operation_authority.observe(operation_ref)
                    if observation is None:
                        raise RuntimeError(
                            f"provider operation receipt is missing: {operation_ref}"
                        )
                    if observation.status is not SpecialistOperationStatus.SUCCEEDED:
                        raise RuntimeError(
                            f"provider operation receipt is not terminal success: {operation_ref}"
                        )
                    matching_evidence = next(
                        evidence
                        for evidence in checkpoint.activity_evidence
                        if evidence.activity_id == schedule.activity_id
                    )
                    if (
                        observation.output_artifact_id != matching_evidence.output_artifact_id
                        or observation.request_sha256 != schedule.request_sha256
                    ):
                        raise RuntimeError(
                            "provider receipt does not bind Temporal activity evidence: "
                            f"{operation_ref}"
                        )
                    history = getattr(operation_authority, "history", None)
                    history_count = (
                        len(history(operation_ref)) if callable(history) else None
                    )
                    if history_count is not None:
                        history_count_before += history_count
                    operation_receipts.append(
                        {
                            "activity_id": str(schedule.activity_id),
                            "run_id": str(schedule.run_id),
                            "tool_call_id": str(schedule.tool_call_id),
                            "operation_ref": operation_ref,
                            "provider_ref": observation.provider_ref,
                            "provider_receipt_ref": observation.provider_receipt_ref,
                            "status": observation.status.value,
                            "output_artifact_id": str(observation.output_artifact_id),
                            "receipt_sha256": observation.receipt_sha256,
                            "history_count": history_count,
                        }
                    )

                # A worker restart/replay must observe the durable terminal receipt and
                # return the same Artifact without submitting or executing the provider again.
                replay_executor = BoundSpecialistExecutor(
                    store,
                    operation_authority=operation_authority,
                    retry_budget_authority=retry_budget_authority,
                    retry_budget_max_attempts=3,
                    worker_id="workload:agentops-replay-worker",
                )
                replay_results = tuple(
                    [await replay_executor(schedule.request) for schedule in provider_schedules]
                )
                if any(
                    result.outcome is not TemporalActivityOutcome.SUCCEEDED
                    for result in replay_results
                ):
                    raise RuntimeError("provider receipt replay did not return success")
                if any(
                    result.output_artifact_id
                    != next(
                        evidence.output_artifact_id
                        for evidence in checkpoint.activity_evidence
                        if evidence.activity_id == schedule.activity_id
                    )
                    for schedule, result in zip(provider_schedules, replay_results, strict=True)
                ):
                    raise RuntimeError("provider receipt replay returned a different Artifact")
                history_count_after = 0
                history_available = True
                for schedule in provider_schedules:
                    history = getattr(operation_authority, "history", None)
                    if not callable(history):
                        history_available = False
                        break
                    history_count_after += len(history(operation_ref_for(schedule)))
                operation_replay_verified = (
                    history_count_after == history_count_before
                    if history_available
                    else True
                )
                if not operation_replay_verified:
                    raise RuntimeError(
                        "provider receipt replay appended a duplicate operation transition"
                    )

            history = await handle.fetch_history()
            history_json = history.to_json()
            replay = await Replayer(workflows=[TemporalTaskGraphWorkflow]).replay_workflow(
                WorkflowHistory.from_json(workflow_id, history_json)
            )
            if replay.replay_failure is not None:
                raise replay.replay_failure
            event_types = tuple(EventType.Name(event.event_type) for event in history.events)
            report: dict[str, Any] = {
                "schema": REPORT_SCHEMA,
                "generated_at": worker_stopped_at.isoformat(),
                "status": "passed",
                "scope": "docker_desktop_temporal_sandbox_bounded_real_mmfe_gwm",
                "production_readiness_claimed": False,
                "temporal_server_version": cluster.server_version,
                "temporal_sdk_version": version("temporalio"),
                "workflow_id": workflow_id,
                "provider_run_id": handle.first_execution_run_id,
                "graph_sha256": workflow_input.task_graph.graph_sha256,
                "execution_input_sha256": execution_input.execution_input_sha256,
                "provider_agents": tuple(sorted(provider_specs)),
                "provider_artifacts": provider_artifacts,
                **(
                    {
                        "operation_authority": {
                            "backend": operation_authority.__class__.__name__,
                            "provider_operation_receipts": operation_receipts,
                            "replay_same_artifacts": operation_replay_verified,
                            "history_replay_duplicate_submission": False,
                        }
                    }
                    if operation_authority is not None
                    else {}
                ),
                "activity_evidence_count": len(checkpoint.activity_evidence),
                "history_event_count": len(history.events),
                "history_activity_scheduled_count": event_types.count(
                    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
                ),
                "history_activity_completed_count": event_types.count(
                    "EVENT_TYPE_ACTIVITY_TASK_COMPLETED"
                ),
                "history_sha256": hashlib.sha256(history_json.encode("utf-8")).hexdigest(),
                "history_replay_status": "passed",
                "started_at": started_at.isoformat(),
                "workflow_completed_at": completed_at.isoformat(),
            }
            report["report_sha256"] = canonical_json_fingerprint(report)
            return report, history_json
        finally:
            fusion_execution._generate_output_path = original_output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default="agentops-real-specialists-rehearsal")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report, history_json = asyncio.run(
        run_rehearsal(
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.history.write_text(history_json + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
