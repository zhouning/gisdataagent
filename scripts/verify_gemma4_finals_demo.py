#!/usr/bin/env python3
"""Verify the exact Gemma 4 finals demo prompts against the running system."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.adk.agents.run_config import RunConfig  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from data_agent.agent import _make_agent_by_name  # noqa: E402
from data_agent.nl2sql_executor import run_nl2semantic2sql  # noqa: E402
from data_agent.toolsets.nl2sql_tools import execute_safe_sql  # noqa: E402
from data_agent.toolsets.world_model_v21_tools import (  # noqa: E402
    paper9_inspect_resources,
    world_model_v21_status,
)

NL2SQL_UI_PROMPT = "@NL2SQL 统计距离道路网络中最长桥梁100米范围内的高德POI数量。"
NL2SQL_QUESTION = NL2SQL_UI_PROMPT.split(" ", 1)[1]
PAPER9_UI_PROMPT = (
    "@WorldModelV21 请使用 bishan 数据集运行一次快速县域 MPC 规划，"
    "完成硬约束审计，并仅在通过后保存已验证经验。"
)
PAPER9_QUESTION = PAPER9_UI_PROMPT.split(" ", 1)[1]

REFERENCE_SQL = """
WITH longest_bridge AS (
  SELECT geometry
  FROM cq_osm_roads_2021
  WHERE bridge = 'T'
  ORDER BY ST_Length(geometry::geography) DESC
  LIMIT 1
)
SELECT COUNT(DISTINCT p."ID") AS poi_count
FROM cq_amap_poi_2024 AS p
CROSS JOIN longest_bridge AS lb
WHERE ST_DWithin(p.geometry::geography, lb.geometry::geography, 100)
""".strip()

EXPECTED_PAPER9_TRACE = [
    "world_model_v21_status",
    "paper9_inspect_resources",
    "paper9_recall_verified_episodes",
    "world_model_v21_pipeline",
    "paper9_audit_run",
    "paper9_commit_verified_episode",
]


def _decode(value: Any) -> Any:
    current = value
    for _ in range(3):
        if isinstance(current, str):
            try:
                current = json.loads(current)
            except json.JSONDecodeError:
                return current
            continue
        if isinstance(current, dict) and set(current) == {"result"}:
            current = current["result"]
            continue
        break
    return current


def _single_value(execution: dict[str, Any]) -> Any:
    data = execution.get("data") or []
    if len(data) != 1 or not isinstance(data[0], dict) or len(data[0]) != 1:
        return None
    return next(iter(data[0].values()))


def _validate_nl2sql_payload(payload: dict[str, Any]) -> dict[str, Any]:
    execution = payload.get("execution") or {}
    sql = str(payload.get("sql") or "")
    value = _single_value(execution)
    checks = {
        "status_ok": payload.get("status") == "ok",
        "single_result_is_35": value == 35,
        "uses_st_dwithin": "ST_DWITHIN" in sql.upper(),
        "uses_geography": "GEOGRAPHY" in sql.upper(),
        "uses_100_meters": "100" in sql,
        "uses_expected_tables": all(
            table in sql for table in ("cq_osm_roads_2021", "cq_amap_poi_2024")
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "status": payload.get("status"),
        "error": payload.get("error"),
        "value": value,
        "sql": sql,
        "corrections": payload.get("corrections") or [],
    }


def run_nl2sql_checks(repeats: int) -> dict[str, Any]:
    reference_payload = _decode(execute_safe_sql(REFERENCE_SQL))
    reference_value = _single_value(reference_payload)
    runs: list[dict[str, Any]] = []
    for run_number in range(1, repeats + 1):
        started = time.perf_counter()
        payload = _decode(run_nl2semantic2sql(NL2SQL_QUESTION))
        result = _validate_nl2sql_payload(payload if isinstance(payload, dict) else {})
        result["run"] = run_number
        result["latency_s"] = round(time.perf_counter() - started, 3)
        runs.append(result)
    return {
        "ui_prompt": NL2SQL_UI_PROMPT,
        "reference_sql": REFERENCE_SQL,
        "reference_value": reference_value,
        "reference_passed": reference_value == 35,
        "repeats": repeats,
        "runs": runs,
        "passed": reference_value == 35 and all(run["passed"] for run in runs),
    }


def _paper9_data_checks(
    pipeline: dict[str, Any],
    audit: dict[str, Any],
    commit: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, Any]]:
    plan = pipeline.get("plan_result") or pipeline
    committed_episode = commit.get("episode") or {}
    final_out_dir = (
        committed_episode.get("out_dir")
        or audit.get("out_dir")
        or plan.get("out_dir")
    )
    summary: dict[str, Any] = {}
    summary_error = None
    if final_out_dir:
        summary_path = Path(str(final_out_dir)) / "mpc_summary.json"
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary = loaded
            else:
                summary_error = "mpc_summary.json is not a JSON object"
        except (OSError, json.JSONDecodeError) as exc:
            summary_error = f"{type(exc).__name__}: {exc}"
    result_rows = summary.get("results") or []
    result = result_rows[0] if result_rows else {}
    shape = summary.get("shapefile_output") or {}
    audit_artifacts = audit.get("artifacts") or {}
    optimized_artifact = audit_artifacts.get("optimized_spatial_result") or {}
    checks = {
        "pipeline_ok": pipeline.get("status") == "ok",
        "tool4_plan_ok": plan.get("status") == "ok",
        "final_summary_loaded": summary_error is None and bool(result_rows),
        "hard_gate_passed": audit.get("hard_constraint_passed") is True,
        "all_outputs_exist": audit.get("all_expected_outputs_exist") is True,
        "verified_memory_committed": commit.get("status") == "committed",
        "cultivated_area_not_reduced": float(
            result.get("cultivated_area_change_ha", -1)
        )
        >= 0,
        "slope_reduced": float(result.get("slope_change_pct", 1)) < 0,
        "contiguity_improved": float(result.get("cont_change", 0)) > 0,
        "optimized_spatial_artifact": optimized_artifact.get("exists") is True,
    }
    metrics = {
        "out_dir": final_out_dir,
        "summary_error": summary_error,
        "steps_run": result.get("steps_run"),
        "swaps_completed": result.get("swaps_completed"),
        "cultivated_area_change_ha": result.get("cultivated_area_change_ha"),
        "slope_change_pct": result.get("slope_change_pct"),
        "cont_change": result.get("cont_change"),
        "baimu_area_change_ha": result.get("baimu_area_change_ha"),
        "n_input": shape.get("n_input"),
        "n_in_env": shape.get("n_in_env"),
        "n_farm_to_forest": shape.get("n_farm_to_forest"),
        "n_forest_to_farm": shape.get("n_forest_to_farm"),
        "land_use_code_scheme": shape.get("land_use_code_scheme"),
        "episode_id": (commit.get("episode") or {}).get("episode_id"),
    }
    return checks, metrics


async def run_live_paper9(timeout_s: int) -> dict[str, Any]:
    agent = _make_agent_by_name("WorldModelV21")
    if agent is None:
        return {"passed": False, "error": "WorldModelV21 agent is not registered"}
    session_id = f"finals-demo-{uuid.uuid4().hex[:10]}"
    runner = Runner(
        agent=agent,
        app_name="gemma4_finals_demo_verification",
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )
    message = types.Content(role="user", parts=[types.Part(text=PAPER9_QUESTION)])
    trace: list[str] = []
    responses: dict[str, dict[str, Any]] = {}
    final_text: list[str] = []
    started = time.perf_counter()
    error = None
    try:
        async with asyncio.timeout(timeout_s):
            events = runner.run_async(
                user_id="finals-demo-verifier",
                session_id=session_id,
                new_message=message,
                run_config=RunConfig(max_llm_calls=12),
            )
            async for event in events:
                content = getattr(event, "content", None)
                for part in getattr(content, "parts", None) or []:
                    if part.function_response:
                        name = part.function_response.name
                        trace.append(name)
                        decoded = _decode(part.function_response.response)
                        responses[name] = decoded if isinstance(decoded, dict) else {
                            "result": decoded
                        }
                    if part.text:
                        final_text.append(part.text)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    pipeline = responses.get("world_model_v21_pipeline") or {}
    audit = responses.get("paper9_audit_run") or {}
    commit = responses.get("paper9_commit_verified_episode") or {}
    checks, metrics = _paper9_data_checks(pipeline, audit, commit)
    checks["exact_six_tool_trace"] = trace == EXPECTED_PAPER9_TRACE
    return {
        "ui_prompt": PAPER9_UI_PROMPT,
        "session_id": session_id,
        "latency_s": round(time.perf_counter() - started, 3),
        "trace": trace,
        "expected_trace": EXPECTED_PAPER9_TRACE,
        "checks": checks,
        "metrics": metrics,
        "error": error,
        "final_text": "".join(final_text)[-4000:],
        "passed": error is None and all(checks.values()),
    }


def run_paper9_preflight() -> dict[str, Any]:
    status = _decode(world_model_v21_status())
    inspect = _decode(paper9_inspect_resources(dataset="bishan"))
    checks = {
        "status_ready": status.get("status") == "ready",
        "package_0_3_3": (status.get("paper9") or {}).get("package_version") == "0.3.3",
        "algorithm_2_2_3": (status.get("paper9") or {}).get("algorithm_version") == "2.2.3",
        "version_compatible": (status.get("finals") or {}).get("version_compatible") is True,
        "planning_ready": inspect.get("planning_ready") is True,
        "three_onnx_members": (
            ((inspect.get("stages") or {}).get("train") or {}).get("onnx_member_count")
            == 3
        ),
    }
    return {
        "checks": checks,
        "status": status,
        "inspect": inspect,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nl2sql-repeats", type=int, default=3)
    parser.add_argument("--skip-nl2sql", action="store_true")
    parser.add_argument("--skip-paper9-live", action="store_true")
    parser.add_argument("--paper9-timeout", type=int, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.nl2sql_repeats < 1:
        parser.error("--nl2sql-repeats must be at least 1")

    preflight = run_paper9_preflight()
    nl2sql = None if args.skip_nl2sql else run_nl2sql_checks(args.nl2sql_repeats)
    paper9 = (
        None
        if args.skip_paper9_live
        else asyncio.run(run_live_paper9(args.paper9_timeout))
    )
    sections = [preflight, nl2sql, paper9]
    passed = all(section is None or section.get("passed") for section in sections)
    report = {
        "schema_version": "gemma4.finals_demo_verification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "exact_production_prompts_against_running_data_and_tools",
        "passed": passed,
        "paper9_preflight": preflight,
        "nl2sql": nl2sql,
        "paper9_live_agent": paper9,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
