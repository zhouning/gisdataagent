"""
Failure to Eval — automatically convert production failures into evaluation test cases.

Implements the "Evolve" loop from Google's AgentOps whitepaper:
Production failure → New test case → Evaluation dataset → CI/CD → Deployed fix

Usage:
    from data_agent.failure_to_eval import convert_failure_to_testcase
    testcase = convert_failure_to_testcase(failure_record)
"""
import json
import os
from datetime import datetime
from typing import Optional

from .observability import get_logger

logger = get_logger("failure_to_eval")

_EVALS_DIR = os.path.join(os.path.dirname(__file__), "evals")


def get_recent_failures(limit: int = 20) -> list[dict]:
    """Get recent tool failures from the failure learning table.

    Returns list of failure records suitable for conversion to test cases.
    """
    try:
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return []
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, tool_name, error_message, tool_args, created_at
                FROM agent_tool_failures
                ORDER BY created_at DESC
                LIMIT :lim
            """), {"lim": limit}).fetchall()
            return [{
                "id": r[0], "tool_name": r[1], "error": r[2],
                "args": r[3], "time": r[4].isoformat() if r[4] else None,
            } for r in rows]
    except Exception:
        return []


def convert_failure_to_testcase(
    user_query: str,
    expected_tool: str = "",
    failure_description: str = "",
    pipeline: str = "general",
) -> dict:
    """Convert a production failure into an evaluation test case.

    Args:
        user_query: The user query that caused the failure.
        expected_tool: The tool that should have been called.
        failure_description: Description of what went wrong.
        pipeline: Which pipeline eval suite to add to.

    Returns:
        The generated test case dict.
    """
    testcase = {
        "query": user_query,
        "expected_tool_use": [expected_tool] if expected_tool else [],
        "expected_intermediate_agent_actions": [],
        "reference": f"Auto-generated from production failure: {failure_description}",
        "source": "production_failure",
        "created_at": datetime.now().isoformat(),
    }
    return testcase


def append_to_eval_dataset(
    testcase: dict,
    pipeline: str = "general",
) -> str:
    """Append a test case to the evaluation dataset for a pipeline.

    Args:
        testcase: Test case dict from convert_failure_to_testcase.
        pipeline: Pipeline name (general, optimization, governance, planner).

    Returns:
        Path to the updated test file, or error message.
    """
    eval_dir = os.path.join(_EVALS_DIR, pipeline)
    if not os.path.isdir(eval_dir):
        return f"Eval directory not found: {eval_dir}"

    test_file = os.path.join(eval_dir, f"{pipeline}.test.json")
    if not os.path.isfile(test_file):
        return f"Test file not found: {test_file}"

    try:
        with open(test_file, "r", encoding="utf-8") as f:
            existing = json.load(f)

        if not isinstance(existing, list):
            existing = [existing]

        existing.append(testcase)

        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        logger.info("Added test case to %s (%d total)", test_file, len(existing))
        return test_file
    except Exception as e:
        return f"Failed to append test case: {e}"


def failure_to_eval_pipeline(
    user_query: str,
    expected_tool: str = "",
    failure_description: str = "",
    pipeline: str = "general",
) -> dict:
    """End-to-end: convert failure to test case and append to eval dataset.

    Returns:
        {"status": "success"|"error", "testcase": dict, "file": str}
    """
    testcase = convert_failure_to_testcase(
        user_query, expected_tool, failure_description, pipeline,
    )
    result = append_to_eval_dataset(testcase, pipeline)

    if result.endswith(".json"):
        return {"status": "success", "testcase": testcase, "file": result}
    return {"status": "error", "message": result, "testcase": testcase}
