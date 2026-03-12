"""Multi-pipeline agent evaluation runner.

Evaluates all 4 pipelines independently using ADK AgentEvaluator.
Each pipeline has its own eval set (.test.json) and metric config
(test_config.json) under data_agent/evals/<pipeline>/.

The umbrella ``eval_agent.py`` module exposes all pipelines as
sub_agents of a single root_agent so AgentEvaluator can target
any pipeline via the ``agent_name`` parameter.

Usage::

    python data_agent/run_evaluation.py                 # all pipelines
    python data_agent/run_evaluation.py optimization    # single pipeline
    python data_agent/run_evaluation.py --num-runs 3    # increase sample size
"""

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding for emoji / CJK characters in eval output.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import seaborn as sns
from dotenv import load_dotenv

# Add project root so ``data_agent`` package is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.evaluation.agent_evaluator import AgentEvaluator  # noqa: E402

# Load environment variables (.env supplies GOOGLE_API_KEY, DB creds, etc.)
load_dotenv("data_agent/.env")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EVAL_AGENT_MODULE = "data_agent.evals.agent"
EVALS_DIR = Path("data_agent/evals")
RESULTS_DIR = Path("data_agent/eval_results")

# Maps pipeline name -> agent_name used by ``root_agent.find_agent()``.
PIPELINE_CONFIG = {
    "optimization": {"agent_name": "DataPipeline",         "eval_dir": EVALS_DIR / "optimization"},
    "governance":   {"agent_name": "GovernancePipeline",    "eval_dir": EVALS_DIR / "governance"},
    "general":      {"agent_name": "GeneralPipeline",       "eval_dir": EVALS_DIR / "general"},
    "planner":      {"agent_name": "Planner",               "eval_dir": EVALS_DIR / "planner"},
}

# Per-pipeline pass rate thresholds (0.0 – 1.0).
# A pipeline passes if its pass_rate >= threshold.
PIPELINE_THRESHOLDS = {
    "optimization": 0.6,
    "governance": 0.6,
    "general": 0.7,
    "planner": 0.5,
}

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> tuple[list[str] | None, int]:
    """Parse CLI arguments for pipeline selection and options.

    Returns (pipeline_names, num_runs).
    """
    pipelines = []
    num_runs = 1

    i = 0
    while i < len(argv):
        if argv[i] == "--num-runs" and i + 1 < len(argv):
            num_runs = int(argv[i + 1])
            i += 2
        elif argv[i].startswith("--"):
            i += 1  # skip unknown flags
        else:
            pipelines.append(argv[i])
            i += 1

    return pipelines or None, num_runs

# ---------------------------------------------------------------------------
# Font configuration (Chinese support)
# ---------------------------------------------------------------------------

def configure_plotting_font():
    """Configure Chinese fonts for Matplotlib on Windows / Linux."""
    font_candidates = ["Microsoft YaHei", "SimHei", "SimSun", "Malgun Gothic",
                        "Noto Sans CJK SC", "WenQuanYi Micro Hei"]
    system_fonts = {f.name for f in fm.fontManager.ttflist}
    selected = next((f for f in font_candidates if f in system_fonts), None)
    if selected:
        plt.rcParams["font.sans-serif"] = [selected] + plt.rcParams["font.sans-serif"]
        plt.rcParams["axes.unicode_minus"] = False

# ---------------------------------------------------------------------------
# Per-pipeline evaluation
# ---------------------------------------------------------------------------

async def evaluate_pipeline(name: str, config: dict, num_runs: int = 1) -> dict:
    """Run ADK evaluation for a single pipeline.

    Returns a result dict with status, scores, timing, and failure details.
    Continue-on-failure: individual test file errors do not abort the pipeline.
    """
    eval_dir: Path = config["eval_dir"]
    agent_name: str = config["agent_name"]

    test_files = sorted(eval_dir.glob("*.test.json"))
    if not test_files:
        print(f"  [skip] No .test.json files in {eval_dir}")
        return {"pipeline": name, "status": "skipped", "reason": "no test files"}

    pipeline_start = time.time()
    results = []

    for test_file in test_files:
        print(f"  Evaluating {test_file.name} (agent_name={agent_name}, num_runs={num_runs}) ...")
        file_start = time.time()
        try:
            eval_result = await AgentEvaluator.evaluate(
                agent_module=EVAL_AGENT_MODULE,
                eval_dataset_file_path_or_dir=str(test_file),
                num_runs=num_runs,
                agent_name=agent_name,
                print_detailed_results=True,
            )
            file_duration = round(time.time() - file_start, 2)

            # Extract per-metric scores if available
            metric_scores = _extract_metric_scores(eval_result)

            results.append({
                "file": test_file.name,
                "status": "passed",
                "duration_s": file_duration,
                "metrics": metric_scores,
            })
            print(f"    -> PASSED ({file_duration}s)")
            if metric_scores:
                for metric_name, score in metric_scores.items():
                    print(f"       {metric_name}: {score}")

        except AssertionError as e:
            file_duration = round(time.time() - file_start, 2)
            error_details = str(e)[:500]

            # Try to extract metric scores from assertion message
            metric_scores = _parse_assertion_metrics(error_details)

            results.append({
                "file": test_file.name,
                "status": "failed",
                "duration_s": file_duration,
                "details": error_details,
                "metrics": metric_scores,
                "suggestion": _suggest_fix(error_details),
            })
            print(f"    -> FAILED ({file_duration}s): {str(e)[:200]}")
            if metric_scores:
                for metric_name, score in metric_scores.items():
                    print(f"       {metric_name}: {score}")

        except Exception as e:
            file_duration = round(time.time() - file_start, 2)
            results.append({
                "file": test_file.name,
                "status": "error",
                "duration_s": file_duration,
                "error": str(e)[:500],
                "traceback": traceback.format_exc()[-500:],
                "suggestion": _suggest_fix(str(e)),
            })
            print(f"    -> ERROR ({file_duration}s): {str(e)[:200]}")

    pipeline_duration = round(time.time() - pipeline_start, 2)
    passed = sum(1 for r in results if r["status"] == "passed")
    total = len(results)

    return {
        "pipeline": name,
        "agent_name": agent_name,
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 4) if total else 0,
        "duration_s": pipeline_duration,
        "results": results,
    }


def _extract_metric_scores(eval_result) -> dict:
    """Extract per-metric scores from AgentEvaluator result object."""
    scores = {}
    if eval_result is None:
        return scores
    # ADK AgentEvaluator returns different types depending on version.
    # Try common attribute patterns.
    if isinstance(eval_result, dict):
        for key, value in eval_result.items():
            if isinstance(value, (int, float)):
                scores[key] = value
    elif hasattr(eval_result, "__dict__"):
        for key, value in eval_result.__dict__.items():
            if isinstance(value, (int, float)) and not key.startswith("_"):
                scores[key] = value
    return scores


def _parse_assertion_metrics(error_text: str) -> dict:
    """Try to extract metric scores from ADK assertion error messages.

    ADK assertion errors often contain patterns like:
    'tool_trajectory_avg_score: 0.0 < 0.8'
    """
    import re
    scores = {}
    # Pattern: metric_name: actual_value < threshold
    for match in re.finditer(r"(\w+(?:_\w+)+):\s*([\d.]+)\s*[<>]=?\s*([\d.]+)", error_text):
        metric_name = match.group(1)
        actual = float(match.group(2))
        scores[metric_name] = actual
    # Pattern: metric_name = actual_value
    for match in re.finditer(r"(\w+(?:_\w+)+)\s*=\s*([\d.]+)", error_text):
        metric_name = match.group(1)
        if metric_name not in scores:
            scores[metric_name] = float(match.group(2))
    return scores


def _suggest_fix(error_text: str) -> str:
    """Generate an actionable fix suggestion based on error patterns."""
    text = error_text.lower()
    if "tool_trajectory" in text:
        return (
            "Tool trajectory mismatch. Check that tool names in .test.json "
            "match actual function names in toolsets/. Run: "
            "python -m pytest data_agent/test_evaluation.py::TestToolNameConsistency -v"
        )
    if "timeout" in text or "deadline" in text:
        return "Evaluation timed out. Consider simplifying the test prompt or increasing timeout."
    if "connection" in text or "api" in text:
        return "API connection error. Check GOOGLE_API_KEY and network connectivity."
    if "import" in text:
        return "Import error. Check that all agent modules are importable."
    if "hallucination" in text:
        return "Hallucination detected. Review the test case's expected response for accuracy."
    return ""

# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def generate_charts(pipeline_results: dict):
    """Generate per-pipeline pass-rate bar chart with timing annotations."""
    configure_plotting_font()
    sns.set_theme(style="whitegrid")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    names = []
    rates = []
    durations = []
    for name, result in pipeline_results.items():
        if result.get("status") == "skipped":
            continue
        names.append(name)
        rates.append(result.get("pass_rate", 0))
        durations.append(result.get("duration_s", 0))

    if not names:
        return

    colors = []
    for r in rates:
        if r >= 0.8:
            colors.append("#4CAF50")   # green
        elif r >= 0.5:
            colors.append("#FFC107")   # amber
        else:
            colors.append("#F44336")   # red

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(names, rates, color=colors, width=0.5, edgecolor="black", alpha=0.9)
    ax.set_ylim(0, 1.25)
    ax.set_title("Data Agent 智能体评估结果 (Per-Pipeline)", fontsize=16, pad=20, fontweight="bold")
    ax.set_ylabel("通过率 (0.0 - 1.0)", fontsize=12)
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    for bar, duration in zip(bars, durations):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2.0, h + 0.02,
                f"{h:.2f}", ha="center", va="bottom", fontsize=13, fontweight="bold")
        # Show timing below the bar label
        ax.text(bar.get_x() + bar.get_width() / 2.0, -0.06,
                f"{duration:.0f}s", ha="center", va="top", fontsize=9, color="gray")

    ax.axhline(y=0.8, color="gray", linestyle="--", alpha=0.5)
    ax.text(len(names) - 0.5, 0.81, "优秀基准线 (0.8)", color="gray", fontsize=10)

    total_time = sum(durations)
    ax.text(0.02, 0.97, f"总耗时: {total_time:.0f}s",
            transform=ax.transAxes, fontsize=10, color="gray", va="top")

    output_path = RESULTS_DIR / f"eval_chart_{timestamp}.png"
    fig.savefig(str(output_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"\nChart saved to: {output_path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all_evaluations(pipelines: list[str] | None = None,
                              num_runs: int = 1):
    """Evaluate selected (or all) pipelines and write results.

    Continue-on-failure: errors in one pipeline do not abort others.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    total_start = time.time()

    targets = pipelines or list(PIPELINE_CONFIG.keys())
    all_results: dict[str, dict] = {}

    for name in targets:
        config = PIPELINE_CONFIG.get(name)
        if not config:
            print(f"Unknown pipeline: {name}")
            continue
        print(f"\n{'=' * 60}")
        print(f"Pipeline: {name} ({config['agent_name']})")
        print(f"{'=' * 60}")
        try:
            result = await evaluate_pipeline(name, config, num_runs=num_runs)
        except Exception as e:
            # Continue-on-failure: catch any unexpected error at pipeline level
            print(f"  [FATAL] Pipeline {name} crashed: {e}")
            result = {
                "pipeline": name,
                "status": "crashed",
                "error": str(e)[:500],
                "passed": 0,
                "total": 0,
                "pass_rate": 0,
            }
        all_results[name] = result

    total_duration = round(time.time() - total_start, 2)

    # Aggregate
    total_passed = sum(r.get("passed", 0) for r in all_results.values())
    total_tests = sum(r.get("total", 0) for r in all_results.values())

    # Per-pipeline verdict (threshold-based)
    pipeline_verdicts = {}
    for name, r in all_results.items():
        if r.get("status") in ("skipped", "crashed"):
            pipeline_verdicts[name] = r.get("status") == "skipped"
            continue
        threshold = PIPELINE_THRESHOLDS.get(name, 0.6)
        pipeline_verdicts[name] = r.get("pass_rate", 0) >= threshold

    overall_pass = all(pipeline_verdicts.values()) and total_tests > 0

    summary = {
        "timestamp": timestamp,
        "overall_pass": overall_pass,
        "total_passed": total_passed,
        "total_tests": total_tests,
        "total_duration_s": total_duration,
        "num_runs": num_runs,
        "pipelines": all_results,
        "pipeline_verdicts": pipeline_verdicts,
        "thresholds": PIPELINE_THRESHOLDS,
    }

    # Write summary
    summary_path = RESULTS_DIR / "eval_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Write per-pipeline detailed results
    for name, result in all_results.items():
        detail_path = RESULTS_DIR / f"eval_{name}_detail.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Summary: {total_passed}/{total_tests} passed  |  "
          f"Overall: {'PASS' if overall_pass else 'FAIL'}  |  "
          f"Duration: {total_duration}s")
    for name, r in all_results.items():
        if r.get("status") in ("skipped", "crashed"):
            status = r["status"].upper()
        else:
            rate = r.get("pass_rate", 0)
            threshold = PIPELINE_THRESHOLDS.get(name, 0.6)
            verdict = "PASS" if pipeline_verdicts.get(name, False) else "FAIL"
            status = f"{r.get('passed', 0)}/{r.get('total', 0)} ({rate:.0%} >= {threshold:.0%} → {verdict})"
        duration = f" ({r.get('duration_s', 0)}s)" if r.get("duration_s") else ""
        print(f"  {name:15s} {status}{duration}")

        # Show actionable suggestions for failures
        for file_result in r.get("results", []):
            if file_result.get("suggestion"):
                print(f"    Suggestion: {file_result['suggestion']}")

    print(f"Results: {summary_path}")

    # Chart
    generate_charts(all_results)

    if not overall_pass:
        sys.exit(1)


if __name__ == "__main__":
    # Optional: pass pipeline names and flags as CLI args, e.g.:
    #   python run_evaluation.py optimization governance
    #   python run_evaluation.py --num-runs 3
    selected, num_runs = parse_args(sys.argv[1:])
    asyncio.run(run_all_evaluations(selected, num_runs=num_runs))
