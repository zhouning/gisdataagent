"""Regression tests for ADK Workflow compatibility boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from google.adk.evaluation.agent_evaluator import AgentEvaluator
from google.adk.workflow import Workflow

from data_agent.adk_compat import find_adk_node, set_workflow_compat_attrs


def _workflow(name: str, children: list[Workflow] | None = None) -> Workflow:
    children = children or []
    edges = [("START", *children)] if children else []
    return set_workflow_compat_attrs(
        Workflow(name=name, edges=edges),
        sub_agents=children,
    )


def test_find_adk_node_walks_nested_workflow_graphs():
    target = _workflow("Target")
    nested = _workflow("Nested", [target])
    root = _workflow("Root", [nested])

    assert find_adk_node(root, "Root") is root
    assert root.find_agent("Target") is target
    assert root.find_agent("Missing") is None


def test_agent_evaluator_can_select_a_workflow_node():
    target = _workflow("GeneralPipeline")
    root = _workflow("EvalUmbrella", [target])
    module = SimpleNamespace(root_agent=root)

    with patch(
        "google.adk.evaluation.agent_evaluator.importlib.import_module",
        return_value=module,
    ):
        selected = asyncio.run(
            AgentEvaluator._get_agent_for_eval(
                "tests.workflow_fixture.agent",
                agent_name="GeneralPipeline",
            )
        )

    assert selected is target
