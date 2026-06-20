"""Evaluation-only agent module.

Provides a synthetic umbrella ``root_agent`` that lists all four production
pipelines for offline structure checks.

Production code (``app.py``) continues to use the individual pipeline agents
directly via semantic routing — this module is never imported at runtime.

This file MUST be named ``agent.py`` inside the ``evals`` package so that
ADK's ``_get_agent_for_eval()`` resolves it correctly when called with
``agent_module="data_agent.evals"``.

Usage::

    await AgentEvaluator.evaluate(
        agent_module="data_agent.evals",
        eval_dataset_file_path_or_dir="data_agent/evals/optimization",
        agent_name="DataPipeline",
    )
"""

from google.adk.workflow import JoinNode, Workflow

from data_agent.agent import (
    data_pipeline,
    governance_pipeline,
    general_pipeline,
    planner_agent,
)
from data_agent.adk_compat import set_workflow_compat_attrs

_join = JoinNode(name="EvalUmbrellaJoin")

root_agent = Workflow(
    name="EvalUmbrella",
    description="Evaluation umbrella for structure checks.",
    edges=[
        ("START", (data_pipeline, governance_pipeline, general_pipeline, planner_agent)),
        ((data_pipeline, governance_pipeline, general_pipeline, planner_agent), _join),
    ],
)
set_workflow_compat_attrs(
    root_agent,
    sub_agents=[
        data_pipeline,
        governance_pipeline,
        general_pipeline,
        planner_agent,
    ],
)
