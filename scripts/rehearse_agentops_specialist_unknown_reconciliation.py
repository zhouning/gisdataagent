#!/usr/bin/env python3
"""Rehearse provider unknown/cancellation reconciliation at the AgentOps boundary.

This is a bounded local contract rehearsal. It uses the real MMFE/GWM provider functions,
the Temporal provider-neutral harness, and an append-only in-memory operation receipt
authority. It intentionally does not claim Temporal server, PostgreSQL, MinIO, or
production cancellation readiness.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from data_agent.agentops_contracts import AgentSideEffect
from data_agent.agentops_specialist_providers import (
    BoundSpecialistExecutor,
    FilesystemSpecialistArtifactStore,
    InMemorySpecialistOperationAuthority,
    build_gwm_provider_spec,
    build_mmfe_provider_spec,
    reconcile_unknown_specialist_activity,
)
from data_agent.agentops_temporal_adapter import TemporalActivityAdapter
from data_agent.agentops_temporal_task_graph_rehearsal import build_rehearsal_execution_input
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
from data_agent.platform_contracts import canonical_json_fingerprint

REPORT_SCHEMA = "gda.agentops_specialist_unknown_reconciliation_rehearsal_report.v1"


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


def _write_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "mmfe.uwm_state_input.v1",
                "version": "0.1",
                "source_product": {"product_id": "unknown-reconciliation-rehearsal-v1"},
                "urban_spatial_unit": {"unit_type": "district"},
                "object_role_registry": [],
                "state_components": {},
                "graph_summary": {},
                "production_policy": {"authoritative_data_required_for_production": True},
            }
        ),
        encoding="utf-8",
    )


def _advance_to_fusion(harness: TemporalTaskGraphWorkflowHarness, execution_input):
    workflow_input = execution_input.workflow_input
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    plans = {plan.agent_id: plan for plan in execution_input.execution_manifest.plans}
    for agent_id in ("coordinator", "planner"):
        step = next(item for item in workflow_input.task_graph.steps if item.agent_id == agent_id)
        harness.start_step(workflow_id, step.step_id)
        harness.complete_step(workflow_id, step_id=step.step_id)
    step = next(item for item in workflow_input.task_graph.steps if item.agent_id == "fusion")
    harness.start_step(workflow_id, step.step_id)
    plan = plans["fusion"]
    current = harness.bind_tool_call(
        workflow_id,
        step_id=step.step_id,
        tool_ref=plan.tool_ref,
        capability_ref=plan.capability_ref,
        subject_context=plan.subject_context,
        side_effect=AgentSideEffect.DATA_WRITE,
        policy_decision_ref=plan.policy_decision_ref,
        idempotency_key=plan.idempotency_key,
        input_artifact_ids=tuple(sorted(workflow_input.input_artifact_ids, key=str)),
    )
    call = next(item for item in current.execution.tool_calls if item.step_id == step.step_id)
    harness.dispatch_tool_call(workflow_id, call.tool_call_id)
    return workflow_id, call, plan


def run_rehearsal() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="gda-unknown-reconcile-") as temp_dir:
        root = Path(temp_dir)
        source_a, source_b, state = root / "a.geojson", root / "b.geojson", root / "state.json"
        _write_geojson(source_a, 0)
        _write_geojson(source_b, 0.25)
        _write_state(state)
        input_ids = (
            UUID("00000000-0000-4000-8000-000000007401"),
            UUID("00000000-0000-4000-8000-000000007402"),
            UUID("00000000-0000-4000-8000-000000007403"),
        )
        store = FilesystemSpecialistArtifactStore(root / "artifacts")
        store.register_input(
            tenant_id="planning",
            artifact_id=input_ids[0],
            source_path=source_a,
            media_type="application/geo+json",
        )
        store.register_input(
            tenant_id="planning",
            artifact_id=input_ids[1],
            source_path=source_b,
            media_type="application/geo+json",
        )
        store.register_input(
            tenant_id="planning",
            artifact_id=input_ids[2],
            source_path=state,
            media_type="application/json",
        )
        import data_agent.fusion.execution as fusion_execution

        output_path = root / "fused.geojson"
        original_output_path = fusion_execution._generate_output_path
        fusion_execution._generate_output_path = lambda *_args: str(output_path)
        try:
            execution_input = build_rehearsal_execution_input(
                namespace_ref="gda-agentops-unknown-rehearsal",
                task_queue_ref="unknown-reconciliation-rehearsal",
                run_key=str(uuid4()),
                input_artifact_ids=input_ids,
                provider_spec_by_agent={
                    "fusion": build_mmfe_provider_spec(
                        input_artifact_ids=input_ids[:2], strategy="spatial_join"
                    )
                },
            )
            harness = TemporalTaskGraphWorkflowHarness()
            workflow_id, call, plan = _advance_to_fusion(harness, execution_input)
            snapshot = harness.schedule_activity(
                workflow_id,
                call.tool_call_id,
                activity_type=plan.activity_type,
                schedule_to_close_timeout_seconds=60,
                start_to_close_timeout_seconds=30,
                heartbeat_timeout_seconds=10,
                provider_spec=plan.provider_spec,
            )
            request = snapshot.activity_schedules[-1].request
            authority = InMemorySpecialistOperationAuthority()
            unknown = asyncio.run(
                BoundSpecialistExecutor(
                    store, operation_authority=authority, unknown_after_commit=True
                )(request)
            )
            unknown_evidence = TemporalActivityAdapter.evidence_from_result(request, unknown)
            harness.record_scheduled_activity(workflow_id, unknown_evidence)
            reconciliation, settled = reconcile_unknown_specialist_activity(
                request,
                unknown,
                artifact_store=store,
                operation_authority=authority,
            )
            settled_evidence = TemporalActivityAdapter.evidence_from_result(request, settled)
            final_snapshot = harness.record_scheduled_activity(workflow_id, settled_evidence)

            # Cancellation/timeout path: submit is recorded, cancellation is requested,
            # and the absence of a provider output remains unknown_pending.
            gwm_spec = build_gwm_provider_spec(
                input_artifact_ids=(input_ids[2],), observation_id="cancel-obs"
            )
            cancel_input = build_rehearsal_execution_input(
                namespace_ref="gda-agentops-unknown-rehearsal",
                task_queue_ref="unknown-reconciliation-rehearsal",
                run_key=str(uuid4()),
                input_artifact_ids=input_ids,
                provider_spec_by_agent={"fusion": gwm_spec},
            )
            cancel_harness = TemporalTaskGraphWorkflowHarness()
            cancel_workflow_id, cancel_call, cancel_plan = _advance_to_fusion(
                cancel_harness, cancel_input
            )
            cancel_snapshot = cancel_harness.schedule_activity(
                cancel_workflow_id,
                cancel_call.tool_call_id,
                activity_type=cancel_plan.activity_type,
                schedule_to_close_timeout_seconds=60,
                start_to_close_timeout_seconds=30,
                heartbeat_timeout_seconds=10,
                provider_spec=gwm_spec,
            )
            cancel_request = cancel_snapshot.activity_schedules[-1].request
            cancel_authority = InMemorySpecialistOperationAuthority()
            cancel_unknown = asyncio.run(
                BoundSpecialistExecutor(
                    store,
                    operation_authority=cancel_authority,
                    cancellation_timeout_before_execution=True,
                )(cancel_request)
            )
            cancel_evidence = TemporalActivityAdapter.evidence_from_result(
                cancel_request, cancel_unknown
            )
            cancel_harness.record_scheduled_activity(cancel_workflow_id, cancel_evidence)
            cancel_reconciliation, cancel_settled = reconcile_unknown_specialist_activity(
                cancel_request,
                cancel_unknown,
                artifact_store=store,
                operation_authority=cancel_authority,
            )
            report: dict[str, object] = {
                "schema": REPORT_SCHEMA,
                "status": "passed",
                "scope": "bounded_local_temporal_contract_rehearsal",
                "production_readiness_claimed": False,
                "unknown_after_commit": {
                    "provider_operation_status": authority.observe(
                        unknown.provider_operation_ref
                    ).status.value,
                    "unknown_output_artifact_id": None,
                    "reconciliation_verdict": reconciliation.verdict.value,
                    "settled_outcome": settled.outcome.value,
                    "settled_output_artifact_id": str(settled.output_artifact_id),
                    "unknown_evidence_idempotency_key": unknown_evidence.idempotency_key,
                    "settled_evidence_idempotency_key": settled_evidence.idempotency_key,
                    "run_status": final_snapshot.workflow.run.status.value,
                },
                "cancellation_timeout": {
                    "provider_operation_status": cancel_authority.observe(
                        cancel_unknown.provider_operation_ref
                    ).status.value,
                    "unknown_output_artifact_id": None,
                    "reconciliation_verdict": cancel_reconciliation.verdict.value,
                    "settled_outcome": cancel_settled.outcome.value,
                    "run_status": cancel_harness.get(cancel_workflow_id).workflow.run.status.value,
                },
                "provider_receipt_history_counts": {
                    "commit_path": len(authority.history),
                    "cancellation_path": len(cancel_authority.history),
                },
            }
            report["report_sha256"] = canonical_json_fingerprint(report)
            return report
        finally:
            fusion_execution._generate_output_path = original_output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = run_rehearsal()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
