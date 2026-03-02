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
"""

import asyncio
import json
import os
import sys
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

# Maps pipeline name → agent_name used by ``root_agent.find_agent()``.
PIPELINE_CONFIG = {
    "optimization": {"agent_name": "DataPipeline",         "eval_dir": EVALS_DIR / "optimization"},
    "governance":   {"agent_name": "GovernancePipeline",    "eval_dir": EVALS_DIR / "governance"},
    "general":      {"agent_name": "GeneralPipeline",       "eval_dir": EVALS_DIR / "general"},
    "planner":      {"agent_name": "Planner",               "eval_dir": EVALS_DIR / "planner"},
}

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

async def evaluate_pipeline(name: str, config: dict) -> dict:
    """Run ADK evaluation for a single pipeline.

    Returns a result dict with status, scores, and failure details.
    """
    eval_dir: Path = config["eval_dir"]
    agent_name: str = config["agent_name"]

    test_files = sorted(eval_dir.glob("*.test.json"))
    if not test_files:
        print(f"  [skip] No .test.json files in {eval_dir}")
        return {"pipeline": name, "status": "skipped", "reason": "no test files"}

    results = []
    for test_file in test_files:
        print(f"  Evaluating {test_file.name} (agent_name={agent_name}) ...")
        try:
            await AgentEvaluator.evaluate(
                agent_module=EVAL_AGENT_MODULE,
                eval_dataset_file_path_or_dir=str(test_file),
                num_runs=1,
                agent_name=agent_name,
                print_detailed_results=True,
            )
            results.append({"file": test_file.name, "status": "passed"})
            print(f"    -> PASSED")
        except AssertionError as e:
            results.append({"file": test_file.name, "status": "failed", "details": str(e)[:500]})
            print(f"    -> FAILED: {str(e)[:200]}")
        except Exception as e:
            results.append({"file": test_file.name, "status": "error", "error": str(e)[:500]})
            print(f"    -> ERROR: {str(e)[:200]}")

    passed = sum(1 for r in results if r["status"] == "passed")
    total = len(results)

    return {
        "pipeline": name,
        "agent_name": agent_name,
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 4) if total else 0,
        "results": results,
    }

# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def generate_charts(pipeline_results: dict):
    """Generate per-pipeline pass-rate bar chart."""
    configure_plotting_font()
    sns.set_theme(style="whitegrid")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    names = []
    rates = []
    for name, result in pipeline_results.items():
        if result.get("status") == "skipped":
            continue
        names.append(name)
        rates.append(result.get("pass_rate", 0))

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
    ax.set_ylim(0, 1.15)
    ax.set_title("Data Agent 智能体评估结果 (Per-Pipeline)", fontsize=16, pad=20, fontweight="bold")
    ax.set_ylabel("通过率 (0.0 - 1.0)", fontsize=12)
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    for bar in bars:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2.0, h + 0.02,
                f"{h:.2f}", ha="center", va="bottom", fontsize=13, fontweight="bold")

    ax.axhline(y=0.8, color="gray", linestyle="--", alpha=0.5)
    ax.text(len(names) - 0.5, 0.81, "优秀基准线 (0.8)", color="gray", fontsize=10)

    output_path = RESULTS_DIR / f"eval_chart_{timestamp}.png"
    fig.savefig(str(output_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"\nChart saved to: {output_path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all_evaluations(pipelines: list[str] | None = None):
    """Evaluate selected (or all) pipelines and write results."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()

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
        result = await evaluate_pipeline(name, config)
        all_results[name] = result

    # Aggregate
    total_passed = sum(r.get("passed", 0) for r in all_results.values())
    total_tests = sum(r.get("total", 0) for r in all_results.values())
    overall_pass = total_passed == total_tests and total_tests > 0

    summary = {
        "timestamp": timestamp,
        "overall_pass": overall_pass,
        "total_passed": total_passed,
        "total_tests": total_tests,
        "pipelines": all_results,
    }

    summary_path = RESULTS_DIR / "eval_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Summary: {total_passed}/{total_tests} passed  |  Overall: {'PASS' if overall_pass else 'FAIL'}")
    for name, r in all_results.items():
        status = "SKIP" if r.get("status") == "skipped" else f"{r.get('passed', 0)}/{r.get('total', 0)}"
        print(f"  {name:15s} {status}")
    print(f"Results: {summary_path}")

    # Chart
    generate_charts(all_results)

    if not overall_pass:
        sys.exit(1)


if __name__ == "__main__":
    # Optional: pass pipeline names as CLI args, e.g.:
    #   python run_evaluation.py optimization governance
    selected = sys.argv[1:] or None
    asyncio.run(run_all_evaluations(selected))
