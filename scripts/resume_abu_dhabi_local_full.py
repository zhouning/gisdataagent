#!/usr/bin/env python3
"""Resume an interrupted Abu Dhabi local full benchmark without rerunning it.

The original full-run manifest is the source of truth.  This command only
reuses passed checkpoint cases through the existing benchmark runner; failed
cases are retried by that runner and all selected cases remain in the final
denominator.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_abu_dhabi_local_full import (  # noqa: E402
    configure,
    model_identity,
    selected_profiles,
    selected_sources,
    sha256,
    validate_population,
    write_json,
)


def _frozen_selection(manifest: dict) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Resolve the exact source/profile scope recorded by the original run."""

    selection = manifest.get("selection") or {}
    source_names = selection.get("sources")
    if source_names is None:
        # v1 reports from before explicit selection covered every descriptor.
        source_names = list((manifest.get("sources") or {}).keys())
    sources = selected_sources(source_names)
    profiles = selected_profiles(selection.get("profiles"))
    if set(name for name, _ in sources) != set((manifest.get("sources") or {}).keys()):
        raise ValueError("manifest source selection does not match source descriptors")
    for name, role in sources:
        if manifest["sources"][name].get("benchmark_role") not in {None, role}:
            raise ValueError(f"{name} manifest benchmark role differs from frozen selection")
    return sources, profiles


def _assert_frozen_inputs(
    manifest: dict, *, output: Path, evaluator, registry
) -> list[tuple]:
    """Resolve current artifacts and prove they still match the run manifest."""

    for relative, digest in manifest["code_sha256"].items():
        if sha256(ROOT / relative) != digest:
            raise ValueError(f"evaluation/runtime code changed: {relative}")

    sources, _profiles = _frozen_selection(manifest)
    frozen = []
    for key, role in sources:
        descriptor = manifest["sources"].get(key)
        if not descriptor:
            raise ValueError(f"manifest is missing source descriptor: {key}")
        source = registry.current_artifact_manifest(key)["source"]
        semantic = registry.current_artifact_path(key, "semantic")
        benchmark = registry.current_artifact_path(key, role)
        if sha256(semantic) != descriptor["semantic_sha256"]:
            raise ValueError(f"{key} semantic artifact changed")
        if sha256(benchmark) != descriptor["benchmark_sha256"]:
            raise ValueError(f"{key} benchmark artifact changed")
        if source != descriptor["source"]:
            raise ValueError(f"{key} source registration changed")
        cases = evaluator._validate_benchmark(
            json.loads(benchmark.read_text()),
            json.loads(semantic.read_text()),
            source_id=source["source_id"],
            benchmark_path=benchmark,
        )
        case_ids = [case["case_id"] for case in cases]
        if case_ids != descriptor["case_ids"]:
            raise ValueError(f"{key} frozen case population changed")
        gold = descriptor.get("gold_audit")
        if not gold:
            raise ValueError(f"{key} independent Gold audit is missing")
        gold_path = output / gold["path"]
        if sha256(gold_path) != gold["sha256"]:
            raise ValueError(f"{key} independent Gold audit changed")
        frozen.append((key, source, semantic, benchmark, descriptor))
    return frozen


def _validated_completed_run_ids(manifest: dict, *, output: Path) -> set[str]:
    """Verify reports already registered in the manifest before skipping them."""

    sources, profiles = _frozen_selection(manifest)
    allowed = {
        f"{source}_{profile}" for source, _ in sources for profile in profiles
    }
    unexpected = set(manifest["runs"]) - allowed
    if unexpected:
        raise ValueError(f"manifest contains unexpected runs: {sorted(unexpected)}")
    completed: set[str] = set()
    for source, _ in sources:
        descriptor = manifest["sources"][source]
        for profile in profiles:
            run_id = f"{source}_{profile}"
            run = manifest["runs"].get(run_id)
            if run is None:
                continue
            report_path = output / run["report_path"]
            if not report_path.is_file() or sha256(report_path) != run["sha256"]:
                raise ValueError(f"registered report changed or is missing: {run_id}")
            report = json.loads(report_path.read_text())
            if report["benchmark"]["execution_profile"] != profile:
                raise ValueError(f"registered report profile mismatch: {run_id}")
            if report["model"]["requested"] != manifest["model"]["name"]:
                raise ValueError(f"registered report model mismatch: {run_id}")
            population = validate_population(report, descriptor["case_ids"])
            if population != run["population"]:
                raise ValueError(f"registered report population mismatch: {run_id}")
            if population["all_cases_attempted"] and not population["infrastructure_failures"]:
                completed.add(run_id)
    return completed


async def resume(args: argparse.Namespace) -> dict:
    configure(args)
    from data_agent import free_form_nl2sql_benchmark as evaluator
    from data_agent.abu_dhabi_artifact_registry import (
        current_artifact_manifest,
        current_artifact_path,
    )
    from data_agent.model_gateway import create_model

    output = args.output.resolve()
    manifest_path = output / "manifest.json"
    if not output.is_dir() or not manifest_path.is_file():
        raise ValueError(f"existing full-run output directory is required: {output}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "gda.abu-dhabi-local-full.v1":
        raise ValueError("unsupported full-run manifest schema")
    if manifest.get("status") == "completed":
        raise ValueError("full benchmark is already complete")
    manifest.pop("output_directory", None)

    route = str(create_model(args.model).model)
    if route != f"ollama_chat/{args.model}":
        raise ValueError("effective route differs from the requested Ollama model")
    identity = model_identity(args)
    frozen_model = manifest["model"]
    if identity != {
        key: frozen_model[key] for key in ("name", "digest", "details")
    }:
        raise ValueError("local model identity differs from the frozen run")
    if frozen_model["effective_route"] != route:
        raise ValueError("effective model route differs from the frozen run")
    if manifest["runtime"] != {
        "timeout_seconds": args.timeout,
        "max_concurrency": args.concurrency,
    }:
        raise ValueError("runtime settings differ from the frozen run")

    registry = type(
        "Registry",
        (),
        {
            "current_artifact_manifest": staticmethod(current_artifact_manifest),
            "current_artifact_path": staticmethod(current_artifact_path),
        },
    )
    frozen = _assert_frozen_inputs(
        manifest, output=output, evaluator=evaluator, registry=registry
    )
    _sources, profiles = _frozen_selection(manifest)
    completed_runs = _validated_completed_run_ids(manifest, output=output)
    started_at = datetime.now(UTC).isoformat()
    manifest.setdefault("resume_history", []).append(
        {
            "started_at": started_at,
            "model": identity,
            "base_url": args.base_url,
        }
    )
    write_json(manifest_path, manifest)

    try:
        for key, source, semantic, benchmark, descriptor in frozen:
            gold_path = output / descriptor["gold_audit"]["path"]
            for profile in profiles:
                run_id = f"{key}_{profile}"
                if run_id in completed_runs:
                    continue
                checkpoint = output / f"{run_id}.checkpoint.json"
                resume_checkpoint = checkpoint.is_file()
                report = await evaluator.run_free_form_benchmark(
                    benchmark_path=benchmark,
                    semantic_layer_path=semantic,
                    source_id=source["source_id"],
                    owner=args.owner,
                    model_name=args.model,
                    reasoning_effort="medium",
                    timeout_seconds=args.timeout,
                    max_concurrency=args.concurrency,
                    execution_profile=profile,
                    request_interval_seconds=0,
                    checkpoint_path=checkpoint,
                    gold_source_cohort_path=gold_path,
                    resume=resume_checkpoint,
                    progress_interval_seconds=30,
                )
                report_path = output / f"{run_id}.json"
                write_json(report_path, report)
                population = validate_population(report, descriptor["case_ids"])
                manifest["runs"][run_id] = {
                    "report_path": report_path.name,
                    "sha256": sha256(report_path),
                    "population": population,
                    "metrics": report["metrics"],
                }
                write_json(manifest_path, manifest)

        manifest["status"] = (
            "completed"
            if set(manifest["runs"]) == {
                f"{source}_{profile}" for source, _ in _sources for profile in profiles
            }
            and all(
                run["population"]["all_cases_attempted"]
                and not run["population"]["infrastructure_failures"]
                for run in manifest["runs"].values()
            )
            else "incomplete_infrastructure"
        )
        manifest["completed_at"] = datetime.now(UTC).isoformat()
        manifest.pop("error", None)
    except BaseException as exc:
        manifest["status"] = "aborted"
        manifest["error"] = evaluator._redact_error(exc)
        raise
    finally:
        write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://10.255.254.81:11434")
    parser.add_argument("--model", default="qwen3.8:latest")
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    result = asyncio.run(resume(parser.parse_args()))
    print(json.dumps({"status": result["status"], "runs": result["runs"]}, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
