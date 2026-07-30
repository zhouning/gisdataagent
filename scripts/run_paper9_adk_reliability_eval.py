#!/usr/bin/env python3
"""Measure Gemma 4 + ADK Paper9 orchestration with deterministic tool doubles."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from data_agent.model_gateway import create_model
from data_agent.paper9_agent_evaluation import (
    evaluate_paper9_tool_trajectory,
    summarize_repeated_agent_runs,
)
from data_agent.paper9_agent_prompt import PAPER9_AGENT_INSTRUCTION

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "data_agent"
    / "demo_evidence"
    / "paper9"
    / "finals_20260730"
    / "adk_reliability_report.json"
)


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    version_compatible: bool
    planning_ready: bool
    audit_outcomes: tuple[bool, ...]
    expected_terminal: str


SCENARIOS = (
    Scenario(
        name="verified_first_pass",
        prompt="使用 bishan 数据集运行一次快速县域 MPC 规划，并按约束审计后处理结果。",
        version_compatible=True,
        planning_ready=True,
        audit_outcomes=(True,),
        expected_terminal="verified_commit",
    ),
    Scenario(
        name="version_mismatch_stops",
        prompt="使用 bishan 数据集运行一次快速县域 MPC 规划。",
        version_compatible=False,
        planning_ready=False,
        audit_outcomes=(),
        expected_terminal="preflight_stop",
    ),
    Scenario(
        name="single_replan_then_verified",
        prompt="使用 bishan 数据集完成县域 MPC 规划；若硬约束失败，按允许范围恢复。",
        version_compatible=True,
        planning_ready=True,
        audit_outcomes=(False, True),
        expected_terminal="verified_commit",
    ),
)


class ToolDoubleState:
    def __init__(self, scenario: Scenario, run_id: str):
        self.scenario = scenario
        self.run_id = run_id
        self.audit_calls = 0

    def audit(self, attempt: int) -> dict[str, Any]:
        index = min(self.audit_calls, max(0, len(self.scenario.audit_outcomes) - 1))
        passed = bool(self.scenario.audit_outcomes[index])
        self.audit_calls += 1
        retryable = not passed and attempt == 0 and len(self.scenario.audit_outcomes) > 1
        return {
            "attempt": attempt,
            "hard_constraint_passed": passed,
            "retryable": retryable,
            "next_action": (
                "commit_verified_episode"
                if passed
                else "replan_once"
                if retryable
                else "stop_and_request_human_review"
            ),
            "out_dir": f"/evidence/{self.run_id}",
            "all_expected_outputs_exist": True,
        }


def _named_tool(function, name: str, description: str) -> FunctionTool:
    function.__name__ = name
    function.__qualname__ = name
    function.__doc__ = description
    return FunctionTool(function)


def build_tool_doubles(scenario: Scenario, run_id: str) -> list[FunctionTool]:
    """Expose the production tool names while keeping algorithm output deterministic."""

    state = ToolDoubleState(scenario, run_id)

    def status() -> dict[str, Any]:
        return {
            "status": "ready" if scenario.version_compatible else "unavailable",
            "version": "2.1.0",
            "paper9": {
                "package_version": "0.3.3" if scenario.version_compatible else "0.2.1",
                "algorithm_version": "2.2.3" if scenario.version_compatible else "2.1.0",
            },
            "finals": {"version_compatible": scenario.version_compatible},
        }

    def inspect(
        dataset: str = "bishan",
        prepared_dir: str = "",
        ensemble_dir: str = "",
    ) -> dict[str, Any]:
        return {
            "dataset": dataset,
            "planning_ready": scenario.planning_ready,
            "reusable_stages": ["prepare", "sample", "train"]
            if scenario.planning_ready
            else [],
            "required_stages": [] if scenario.planning_ready else ["repair_version"],
            "prepared_dir": prepared_dir or "/app/bishan-runs/prepared",
            "ensemble_dir": ensemble_dir or "/app/bishan-runs/prepared/ensemble_seed0",
        }

    def recall(dataset: str = "bishan", limit: int = 3) -> dict[str, Any]:
        return {"status": "ok", "dataset": dataset, "limit": limit, "count": 0, "episodes": []}

    def prepare(
        dltb_path: str = "",
        dem_path: str = "",
        prepared_dir: str = "",
    ) -> dict[str, Any]:
        return {"status": "ok", "mode": "tool1_prepare", "prepared_dir": prepared_dir}

    def sample(prepared_dir: str = "") -> dict[str, Any]:
        return {"status": "ok", "mode": "tool2_sample", "prepared_dir": prepared_dir}

    def train(prepared_dir: str = "") -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "tool3_train",
            "ensemble_dir": f"{prepared_dir}/ensemble_seed0",
        }

    def plan(
        dataset: str = "bishan",
        prepared_dir: str = "",
        ensemble_dir: str = "",
        horizon: int = 1,
        top_k: int = 1,
        n_episodes: int = 1,
        cultivated_area_floor_delta_ha: float = 0.0,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "tool4_plan",
            "dataset": dataset,
            "out_dir": f"/evidence/{run_id}",
            "summary": {"horizon": horizon, "top_k": top_k, "n_episodes": n_episodes},
            "cultivated_area_floor_delta_ha": cultivated_area_floor_delta_ha,
            "prepared_dir": prepared_dir,
            "ensemble_dir": ensemble_dir,
        }

    def pipeline(
        dataset: str = "bishan",
        prepared_dir: str = "",
        ensemble_dir: str = "",
        reuse_existing: bool = True,
        horizon: int = 1,
        top_k: int = 1,
        n_episodes: int = 1,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "pipeline_a_to_d",
            "dataset": dataset,
            "out_dir": f"/evidence/{run_id}",
            "steps": [
                {"step": "prepare", "status": "skipped_reused"},
                {"step": "sample", "status": "skipped_reused"},
                {"step": "train", "status": "skipped_reused"},
                {"step": "plan", "status": "ok"},
            ],
            "reuse_existing": reuse_existing,
            "summary": {"horizon": horizon, "top_k": top_k, "n_episodes": n_episodes},
            "prepared_dir": prepared_dir,
            "ensemble_dir": ensemble_dir,
        }

    def audit(
        out_dir: str,
        attempt: int = 0,
        cultivated_area_floor_delta_ha: float = 0.0,
    ) -> dict[str, Any]:
        result = state.audit(int(attempt))
        result["cultivated_area_floor_delta_ha"] = cultivated_area_floor_delta_ha
        result["out_dir"] = out_dir
        return result

    def commit(
        out_dir: str,
        dataset: str = "bishan",
        goal: str = "",
        plan_args: str = "{}",
    ) -> dict[str, Any]:
        return {
            "status": "committed",
            "out_dir": out_dir,
            "dataset": dataset,
            "goal": goal,
            "plan_args": plan_args,
            "episode": {"episode_id": f"eval-{run_id}"},
        }

    return [
        _named_tool(status, "world_model_v21_status", "Check Paper9 versions before any work."),
        _named_tool(inspect, "paper9_inspect_resources", "Inspect reusable planning resources."),
        _named_tool(recall, "paper9_recall_verified_episodes", "Recall verified prior episodes."),
        _named_tool(prepare, "world_model_v21_prepare", "Run Paper9 Tool 1 preparation."),
        _named_tool(sample, "world_model_v21_sample", "Run Paper9 Tool 2 sampling."),
        _named_tool(train, "world_model_v21_train", "Run Paper9 Tool 3 training."),
        _named_tool(plan, "world_model_v21_plan", "Run only Paper9 Tool 4 planning."),
        _named_tool(pipeline, "world_model_v21_pipeline", "Run or reuse Paper9 A/B/C/D stages."),
        _named_tool(audit, "paper9_audit_run", "Audit a planning output against hard gates."),
        _named_tool(
            commit,
            "paper9_commit_verified_episode",
            "Commit an audited successful run to verified episodic memory.",
        ),
    ]


def _normalize_response(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if set(value) == {"result"} and isinstance(value["result"], dict):
            return value["result"]
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"result": value}
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    return {"result": value}


async def run_once(model: Any, scenario: Scenario, run_number: int, timeout: int) -> dict[str, Any]:
    run_id = f"{scenario.name}-{run_number}-{uuid.uuid4().hex[:8]}"
    agent = LlmAgent(
        name="Paper9FinalsReliabilityAgent",
        model=model,
        instruction=PAPER9_AGENT_INSTRUCTION,
        tools=build_tool_doubles(scenario, run_id),
    )
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="paper9_finals_reliability",
        session_service=session_service,
        auto_create_session=True,
    )
    message = types.Content(role="user", parts=[types.Part(text=scenario.prompt)])
    events: list[dict[str, Any]] = []
    final_text: list[str] = []
    input_tokens = 0
    output_tokens = 0
    started = time.perf_counter()
    error = None
    try:
        async with asyncio.timeout(timeout):
            stream = runner.run_async(
                user_id="finals-evaluator",
                session_id=run_id,
                new_message=message,
            )
            async for event in stream:
                usage = getattr(event, "usage_metadata", None)
                if usage:
                    input_tokens += getattr(usage, "prompt_token_count", 0) or 0
                    output_tokens += getattr(usage, "candidates_token_count", 0) or 0
                content = getattr(event, "content", None)
                for part in getattr(content, "parts", None) or []:
                    if part.function_response:
                        events.append(
                            {
                                "tool": part.function_response.name,
                                "response": _normalize_response(
                                    part.function_response.response
                                ),
                            }
                        )
                    if part.text:
                        final_text.append(part.text)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    latency_ms = (time.perf_counter() - started) * 1000
    contract = evaluate_paper9_tool_trajectory(events)
    passed = bool(
        not error
        and contract["passed"]
        and contract["terminal"] == scenario.expected_terminal
    )
    return {
        "scenario": scenario.name,
        "run_number": run_number,
        "run_id": run_id,
        "passed": passed,
        "expected_terminal": scenario.expected_terminal,
        "terminal": contract["terminal"],
        "tool_count": contract["tool_count"],
        "tool_trace": contract["tool_trace"],
        "violations": contract["violations"],
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "error": error,
        "final_response": "".join(final_text)[-2000:],
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    os.environ.setdefault("MODEL_CONFIG_FORCE_ENV", "true")
    os.environ.setdefault("OLLAMA_API_BASE", args.ollama_api_base)
    model = create_model(args.model)
    rows = []
    selected_scenarios = [
        scenario
        for scenario in SCENARIOS
        if not args.scenario or scenario.name in args.scenario
    ]
    for scenario in selected_scenarios:
        for run_number in range(1, args.runs_per_scenario + 1):
            result = await run_once(model, scenario, run_number, args.timeout)
            rows.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"{scenario.name} run={run_number} {status} "
                f"terminal={result['terminal']} tools={result['tool_count']} "
                f"latency_ms={result['latency_ms']:.0f}",
                flush=True,
            )

    statistical = summarize_repeated_agent_runs(
        rows, pass_rate_threshold=args.pass_rate_threshold
    )
    return {
        "schema_version": "paper9.adk_reliability_report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "live_gemma4_adk_orchestration_with_deterministic_tool_doubles",
        "model": args.model,
        "ollama_api_base": args.ollama_api_base,
        "runs_per_scenario": args.runs_per_scenario,
        "scenarios": [scenario.name for scenario in selected_scenarios],
        "prompt_sha256": hashlib.sha256(
            PAPER9_AGENT_INSTRUCTION.encode("utf-8")
        ).hexdigest(),
        "limitations": [
            "This report measures live Gemma 4 and Google ADK tool orchestration.",
            "Tool responses are deterministic doubles; this report does not rerun "
            "Paper9 computation.",
            "Real Paper9 algorithm and artifact evidence is maintained as a separate "
            "evidence class.",
        ],
        "statistics": statistical,
        "runs": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma4-26b-ollama")
    parser.add_argument("--ollama-api-base", default="http://localhost:11434")
    parser.add_argument("--runs-per-scenario", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--pass-rate-threshold", type=float, default=0.8)
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scenario.name for scenario in SCENARIOS],
        help="Run only the named scenario; repeat the flag to select more than one.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.runs_per_scenario < 1:
        parser.error("--runs-per-scenario must be at least 1")
    if not 0 <= args.pass_rate_threshold <= 1:
        parser.error("--pass-rate-threshold must be between 0 and 1")

    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["statistics"], ensure_ascii=False, indent=2))
    return 0 if report["statistics"]["release_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
