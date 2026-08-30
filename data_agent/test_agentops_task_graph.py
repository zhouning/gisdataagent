from __future__ import annotations

from uuid import UUID

import pytest

from data_agent.agentops_contracts import (
    AGENT_TASK_STEP_SCHEMA,
    AgentRun,
    AgentRunStatus,
    agent_contract_fingerprint,
    agent_run_fingerprint,
)
from data_agent.agentops_task_graph import AgentTaskGraph, compile_agent_task_graph
from data_agent.test_agentops_contracts import _deployment, _evaluation, _run, _spec


def _fixtures() -> tuple:
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    return spec, deployment, _run(deployment)


def test_compiler_emits_deterministic_multimodal_and_gwm_specialist_graph() -> None:
    spec, deployment, run = _fixtures()

    graph = compile_agent_task_graph(spec, deployment, run)
    by_agent = {step.agent_id: step for step in graph.steps}

    assert isinstance(graph, AgentTaskGraph)
    assert [step.agent_id for step in graph.steps] == [
        "coordinator",
        "planner",
        "data_engineer",
        "fusion",
        "gwm",
        "quality",
    ]
    assert by_agent["fusion"].role.value == "multimodal_fusion"
    assert by_agent["gwm"].role.value == "gwm_specialist"
    assert {
        dependency
        for dependency in by_agent["quality"].depends_on_step_ids
    } == {
        by_agent["data_engineer"].step_id,
        by_agent["fusion"].step_id,
        by_agent["gwm"].step_id,
    }
    assert all(step.status.value == "pending" for step in graph.steps)


def test_compiler_reuses_step_ids_and_graph_fingerprint_across_replay() -> None:
    spec, deployment, run = _fixtures()

    first = compile_agent_task_graph(spec, deployment, run)
    second = compile_agent_task_graph(spec, deployment, run)

    assert first == second
    assert first.graph_sha256 == second.graph_sha256
    assert tuple(step.step_id for step in first.steps) == tuple(
        step.step_id for step in second.steps
    )


def test_compiler_rejects_progressed_or_child_run() -> None:
    spec, deployment, accepted = _fixtures()
    progressed_values = accepted.model_dump(mode="json")
    progressed_values["status"] = AgentRunStatus.RUNNING.value
    progressed_values["state_version"] = 1
    progressed_values["run_sha256"] = agent_run_fingerprint(progressed_values)
    progressed = AgentRun(**progressed_values)
    with pytest.raises(ValueError, match="accepted or planning"):
        compile_agent_task_graph(spec, deployment, progressed)

    child_values = accepted.model_dump(mode="json")
    child_values["run_id"] = str(UUID("00000000-0000-4000-8000-000000000902"))
    child_values["parent_run_id"] = str(accepted.run_id)
    child_values["root_run_id"] = str(accepted.run_id)
    child_values["run_sha256"] = agent_run_fingerprint(child_values)
    child = AgentRun(**child_values)
    with pytest.raises(ValueError, match="root AgentRun"):
        compile_agent_task_graph(spec, deployment, child)


def test_graph_contract_rejects_tampered_dependency_or_hash() -> None:
    spec, deployment, run = _fixtures()
    graph = compile_agent_task_graph(spec, deployment, run)
    values = graph.model_dump(mode="json")
    values["graph_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="graph_sha256"):
        AgentTaskGraph(**values)


def test_graph_contract_rejects_runtime_step_projection() -> None:
    spec, deployment, run = _fixtures()
    graph = compile_agent_task_graph(spec, deployment, run)
    values = graph.model_dump(mode="json")
    step = dict(values["steps"][0])
    step["status"] = "running"
    step["step_sha256"] = agent_contract_fingerprint(
        AGENT_TASK_STEP_SCHEMA, step, "step_sha256"
    )
    values["steps"][0] = step
    values["graph_sha256"] = agent_contract_fingerprint(
        "gda.agent_task_graph.v1", values, "graph_sha256"
    )
    with pytest.raises(ValueError, match="pending plan projections"):
        AgentTaskGraph(**values)
