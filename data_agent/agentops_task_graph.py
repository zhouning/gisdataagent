"""Deterministic compiler from an AgentOps topology to an executable task graph.

The compiler creates only typed planning evidence. It does not execute models, call tools,
or become a scheduler. Temporal (or a deterministic test harness) can consume the graph;
the AgentSpec, AgentRun, policy and DataProductVersion remain the authorities.
"""

from __future__ import annotations

from collections import defaultdict
from heapq import heappop, heappush
from typing import ClassVar
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from .agentops_contracts import (
    AGENT_TASK_STEP_SCHEMA,
    AgentDeploymentRevision,
    AgentRun,
    AgentRunStatus,
    AgentSpecVersion,
    AgentStepStatus,
    AgentTaskStep,
    agent_contract_fingerprint,
)
from .platform_contracts import FrozenContract, Sha256, TenantId

AGENT_TASK_GRAPH_SCHEMA = "gda.agent_task_graph.v1"
_TASK_ID_NAMESPACE = NAMESPACE_URL


class AgentTaskGraph(FrozenContract):
    """Immutable, provider-neutral task graph for one root AgentRun."""

    schema_id: ClassVar[str] = AGENT_TASK_GRAPH_SCHEMA
    tenant_id: TenantId
    run_id: UUID
    deployment_revision_sha256: Sha256
    agent_spec_sha256: Sha256
    coordinator_agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    steps: tuple[AgentTaskStep, ...] = Field(min_length=2)
    graph_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_graph(self) -> AgentTaskGraph:
        if any(step.tenant_id != self.tenant_id for step in self.steps):
            raise ValueError("task graph step tenant differs from graph tenant")
        if any(step.run_id != self.run_id for step in self.steps):
            raise ValueError("task graph step run differs from graph run")
        agent_ids = tuple(step.agent_id for step in self.steps)
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("task graph agent ids must be unique")
        step_ids = tuple(step.step_id for step in self.steps)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("task graph step ids must be unique")
        if self.coordinator_agent_id not in agent_ids:
            raise ValueError("task graph coordinator is not present")
        if agent_ids[0] != self.coordinator_agent_id:
            raise ValueError("task graph coordinator must be the first step")
        if tuple(step.sequence_no for step in self.steps) != tuple(range(len(self.steps))):
            raise ValueError("task graph sequence numbers must be contiguous")
        step_by_id = {step.step_id: step for step in self.steps}
        for step in self.steps:
            if (
                step.status is not AgentStepStatus.PENDING
                or step.attempt_no != 1
                or step.input_artifact_ids
                or step.output_artifact_ids
            ):
                raise ValueError(
                    "task graph steps must remain pending plan projections"
                )
            if any(dependency not in step_by_id for dependency in step.depends_on_step_ids):
                raise ValueError("task graph dependency references an unknown step")
            if any(
                step_by_id[dependency].sequence_no >= step.sequence_no
                for dependency in step.depends_on_step_ids
            ):
                raise ValueError("task graph dependencies must point to earlier steps")
        expected = agent_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "graph_sha256"
        )
        if self.graph_sha256 != expected:
            raise ValueError("graph_sha256 does not match task graph content")
        return self


def _deterministic_step_id(
    *, run_id: UUID, agent_spec_sha256: str, agent_id: str
) -> UUID:
    return uuid5(
        _TASK_ID_NAMESPACE,
        f"gda-agent-task:{run_id}:{agent_spec_sha256}:{agent_id}",
    )


def _topological_order(spec: AgentSpecVersion) -> tuple[str, ...]:
    node_ids = {node.agent_id for node in spec.topology.nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in spec.topology.edges:
        if edge.to_agent_id not in adjacency[edge.from_agent_id]:
            adjacency[edge.from_agent_id].add(edge.to_agent_id)
            indegree[edge.to_agent_id] += 1

    available: list[str] = []
    for node_id, count in indegree.items():
        if count == 0:
            heappush(available, node_id)
    ordered: list[str] = []
    while available:
        current = heappop(available)
        ordered.append(current)
        for child in sorted(adjacency[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heappush(available, child)
    if len(ordered) != len(node_ids):
        raise ValueError("agent topology cannot compile because it contains a cycle")
    return tuple(ordered)


def compile_agent_task_graph(
    spec: AgentSpecVersion,
    deployment: AgentDeploymentRevision,
    run: AgentRun,
) -> AgentTaskGraph:
    """Compile a stable specialist DAG without executing any provider side effect."""

    if spec.tenant_id != deployment.tenant_id or spec.tenant_id != run.tenant_id:
        raise ValueError("AgentSpec, deployment and run tenants must match")
    if deployment.agent_spec_sha256 != spec.spec_sha256:
        raise ValueError("deployment does not bind the supplied AgentSpec")
    if run.deployment_revision_sha256 != deployment.revision_sha256:
        raise ValueError("run does not bind the supplied deployment revision")
    if run.parent_run_id is not None or run.root_run_id != run.run_id:
        raise ValueError("task graph compiler requires a root AgentRun")
    if run.status not in {AgentRunStatus.ACCEPTED, AgentRunStatus.PLANNING}:
        raise ValueError("task graph compiler requires an accepted or planning AgentRun")

    nodes = {node.agent_id: node for node in spec.topology.nodes}
    ordered_ids = _topological_order(spec)
    step_ids = {
        agent_id: _deterministic_step_id(
            run_id=run.run_id,
            agent_spec_sha256=spec.spec_sha256,
            agent_id=agent_id,
        )
        for agent_id in ordered_ids
    }
    incoming: dict[str, set[str]] = {agent_id: set() for agent_id in ordered_ids}
    for edge in spec.topology.edges:
        incoming[edge.to_agent_id].add(edge.from_agent_id)

    steps: list[AgentTaskStep] = []
    for sequence_no, agent_id in enumerate(ordered_ids):
        values = {
            "tenant_id": run.tenant_id,
            "run_id": run.run_id,
            "step_id": step_ids[agent_id],
            "agent_id": agent_id,
            "role": nodes[agent_id].role,
            "sequence_no": sequence_no,
            "depends_on_step_ids": tuple(
                sorted((step_ids[parent] for parent in incoming[agent_id]), key=str)
            ),
            "status": AgentStepStatus.PENDING,
            "attempt_no": 1,
            "input_artifact_ids": (),
            "output_artifact_ids": (),
        }
        values["step_sha256"] = agent_contract_fingerprint(
            AGENT_TASK_STEP_SCHEMA, values, "step_sha256"
        )
        steps.append(AgentTaskStep(**values))

    graph_values = {
        "tenant_id": run.tenant_id,
        "run_id": run.run_id,
        "deployment_revision_sha256": deployment.revision_sha256,
        "agent_spec_sha256": spec.spec_sha256,
        "coordinator_agent_id": spec.topology.coordinator_agent_id,
        "steps": tuple(steps),
    }
    graph_values["graph_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_GRAPH_SCHEMA, graph_values, "graph_sha256"
    )
    return AgentTaskGraph(**graph_values)


__all__ = [
    "AGENT_TASK_GRAPH_SCHEMA",
    "AgentTaskGraph",
    "compile_agent_task_graph",
]
