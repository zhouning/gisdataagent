"""Evaluation-only agent module.

Provides a synthetic umbrella ``root_agent`` that wraps all four production
pipelines so that ``AgentEvaluator.evaluate()`` can target any pipeline via
the ``agent_name`` parameter.

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

from google.adk.agents import LlmAgent

from data_agent.agent import (
    MODEL_FAST,
    data_pipeline,
    governance_pipeline,
    general_pipeline,
    planner_agent,
)

root_agent = LlmAgent(
    name="EvalUmbrella",
    model=MODEL_FAST,
    instruction=(
        "You are an evaluation dispatcher. "
        "Route the user request to the appropriate sub-pipeline."
    ),
    sub_agents=[
        data_pipeline,
        governance_pipeline,
        general_pipeline,
        planner_agent,
    ],
)
