#!/usr/bin/env python3
"""Run read-only host checks required by the Gemma 4 finals demo."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.finals_preflight import (  # noqa: E402
    fetch_ollama_tags,
    inspect_finals_host,
)

DEFAULT_REPO = Path("/app/paper9-demo")
DEFAULT_BISHAN_RUNS = Path("/app/bishan-runs")


def _default_repo() -> Path:
    return Path(
        os.environ.get("PAPER9_HOST_REPO")
        or os.environ.get("PAPER9_FARMLAND_MPC_REPO")
        or DEFAULT_REPO
    )


def _default_bishan_runs() -> Path:
    host_runs = os.environ.get("PAPER9_BISHAN_RUNS_HOST")
    if host_runs:
        return Path(host_runs)
    prepared_dir = os.environ.get("PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR")
    if prepared_dir:
        prepared = Path(prepared_dir)
        return prepared.parent if prepared.name == "prepared" else prepared
    return DEFAULT_BISHAN_RUNS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--paper9-repo",
        type=Path,
        default=_default_repo(),
    )
    parser.add_argument(
        "--bishan-runs",
        type=Path,
        default=_default_bishan_runs(),
    )
    parser.add_argument(
        "--ollama-api-base",
        default=os.environ.get("OLLAMA_API_BASE", "http://localhost:11434"),
    )
    parser.add_argument("--model-tag", default="Gemma4:26b")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        tags = fetch_ollama_tags(args.ollama_api_base)
        ollama_error = None
    except Exception as exc:
        tags = []
        ollama_error = f"{type(exc).__name__}: {exc}"

    report = inspect_finals_host(
        paper9_repo=args.paper9_repo,
        bishan_runs=args.bishan_runs,
        model_tag=args.model_tag,
        ollama_tags=tags,
    )
    if ollama_error:
        report["ollama_error"] = ollama_error
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
