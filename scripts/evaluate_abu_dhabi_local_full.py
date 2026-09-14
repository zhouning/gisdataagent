#!/usr/bin/env python3
"""Run both current customer benchmarks in full with an explicit local profile.

Gold audits and scoring stay in the existing evaluation modules. The runtime
receives only each natural-language question and its published semantic layer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROFILES = ("baseline_sql", "semantic_ir_experimental")
SOURCE_ROLES = {
    "liveability": "benchmark",
    "makani": "customer_v4_benchmark",
}


def selected_sources(values: list[str] | None) -> tuple[tuple[str, str], ...]:
    """Resolve an explicit product-source scope without changing the default full run."""

    names = tuple(values or SOURCE_ROLES)
    if len(set(names)) != len(names):
        raise ValueError("source selection must not contain duplicates")
    invalid = sorted(set(names) - set(SOURCE_ROLES))
    if invalid:
        raise ValueError("unknown source selection: " + ", ".join(invalid))
    return tuple((name, SOURCE_ROLES[name]) for name in names)


def selected_profiles(values: list[str] | None) -> tuple[str, ...]:
    """Resolve an explicit execution-profile scope without changing the default."""

    profiles = tuple(values or PROFILES)
    if len(set(profiles)) != len(profiles):
        raise ValueError("profile selection must not contain duplicates")
    invalid = sorted(set(profiles) - set(PROFILES))
    if invalid:
        raise ValueError("unknown profile selection: " + ", ".join(invalid))
    return profiles


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def frozen_cohort_sha256(sources: dict[str, dict]) -> str:
    """Fingerprint the exact benchmark/semantic population before execution.

    Repeated-run promotion is meaningful only if every run used the same
    source case ids and published semantic version.  The digest deliberately
    excludes timestamps, Gold-audit outputs, and model results.
    """

    population = {
        source: {
            "benchmark_sha256": descriptor["benchmark_sha256"],
            "semantic_sha256": descriptor["semantic_sha256"],
            "case_ids": descriptor["case_ids"],
        }
        for source, descriptor in sorted(sources.items())
    }
    rendered = json.dumps(population, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def emit(stage: str, **values: object) -> None:
    print(json.dumps({"at": datetime.now(UTC).isoformat(), "stage": stage, **values}), flush=True)


def configure(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv

    for path in (
        Path(os.environ.get("GDA_OPERATOR_ENV_FILE", ROOT / "data_agent/.env")),
        ROOT / "data_agent/.vsource-secret.env",
        ROOT / "data_agent/.abu-dhabi-vsource-secret.env",
    ):
        load_dotenv(path, override=False)
    base = args.base_url.rstrip("/").removesuffix("/v1")
    args.base_url = base
    os.environ.update(
        {
            "GDA_LLM_PROVIDER": "ollama",
            "GDA_LLM_MODEL": args.model,
            "GDA_LLM_BASE_URL": base + "/v1",
            "GDA_LLM_API_KEY": "ollama",
            "OLLAMA_API_BASE": base,
            "GDA_LLM_TIMEOUT_SECONDS": str(args.timeout),
            "GDA_LLM_ENABLE_THINKING": "false",
        }
    )
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)


def model_identity(args: argparse.Namespace) -> dict:
    with urlopen(args.base_url + "/api/tags", timeout=20) as response:
        tags = json.load(response)
    matches = [item for item in tags["models"] if item["name"] == args.model]
    if len(matches) != 1:
        raise ValueError("requested local model tag is not uniquely available")
    return {key: matches[0][key] for key in ("name", "digest", "details")}


def validate_population(report: dict, case_ids: list[str]) -> dict:
    actual = [row["case_id"] for row in report["cases"]]
    if Counter(actual) != Counter(case_ids) or len(set(actual)) != len(actual):
        raise ValueError("full benchmark population mismatch")
    skipped = sum(
        "benchmark_infrastructure_circuit_open" in row.get("failure_reasons", [])
        for row in report["cases"]
    )
    return {
        "expected": len(case_ids),
        "recorded": len(actual),
        "unique": len(set(actual)),
        "infrastructure_not_attempted": skipped,
        "infrastructure_failures": report["metrics"]["infrastructure_failure_case_count"],
        "all_cases_attempted": skipped == 0,
    }


async def evaluate(args: argparse.Namespace) -> dict:
    configure(args)
    # Import after profile configuration: the model registry reads environment
    # at import time. Do not call the CLI loader, which selects operator Gemini.
    from data_agent import free_form_nl2sql_benchmark as evaluator
    from data_agent.abu_dhabi_artifact_registry import (
        current_artifact_manifest,
        current_artifact_path,
    )
    from data_agent.model_gateway import create_model
    from data_agent.nl2sql_model_profile import resolve_nl2sql_model_profile
    from data_agent.nl2sql_gold_source_cohort import audit_gold_source_cohort

    args.output.mkdir(parents=True, exist_ok=False)
    route = str(create_model(args.model).model)
    if route != f"ollama_chat/{args.model}":
        raise ValueError("effective route differs from the requested Ollama model")
    identity = model_identity(args)
    model_profile = resolve_nl2sql_model_profile(route, provider="ollama")
    sources = selected_sources(args.source)
    profiles = selected_profiles(args.profile)
    manifest = {
        "schema": "gda.abu-dhabi-local-full.v1",
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "model": {
            **identity,
            "effective_route": route,
            "base_url": args.base_url,
            "thinking": False,
            "request_timeout_seconds": args.timeout,
            "generation_budget_seconds": args.timeout,
            "temperature": None,
            "temperature_source": "provider_default_not_overridden_by_query_runtime",
            "compatibility_profile": {
                **model_profile.to_dict(),
                "fingerprint": model_profile.fingerprint,
            },
        },
        "runtime": {"timeout_seconds": args.timeout, "max_concurrency": args.concurrency},
        "selection": {
            "sources": [key for key, _ in sources],
            "case_ids": None,
            "splits": None,
            "profiles": list(profiles),
        },
        "claim_boundary": {
            "scope": "all_cases_in_both_current_customer_benchmarks",
            "older_makani_2328_inventory_benchmark_included": False,
            "source_rows_persisted": False,
            "retrieval": "published_semantics_lexical",
            "vector_retrieval_evaluated": False,
            "browser_verified": False,
            "single_run_not_release_stability_evidence": True,
        },
        "code_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                Path(__file__).resolve(),
                ROOT / "data_agent/free_form_nl2sql_benchmark.py",
                ROOT / "data_agent/nl2sql_gold_source_cohort.py",
                ROOT / "data_agent/governed_virtual_nl2sql.py",
                ROOT / "data_agent/semantic_query_ir.py",
                ROOT / "data_agent/model_gateway.py",
                ROOT / "data_agent/abu_dhabi_nl2sql_presentation.py",
                ROOT / "data_agent/abu_dhabi_nl2sql_map_presentation.py",
                ROOT / "data_agent/nl2sql_model_profile.py",
            )
        },
        "sources": {},
        "runs": {},
    }
    frozen = []
    for key, role in sources:
        source = current_artifact_manifest(key)["source"]
        semantic = current_artifact_path(key, "semantic")
        benchmark = current_artifact_path(key, role)
        layer = json.loads(semantic.read_text())
        definition = json.loads(benchmark.read_text())
        cases = evaluator._validate_benchmark(
            definition,
            layer,
            source_id=source["source_id"],
            benchmark_path=benchmark,
        )
        descriptor = {
            "source": source,
            "benchmark_role": role,
            "benchmark_id": definition.get("benchmark_id"),
            "benchmark_path": str(benchmark.relative_to(ROOT)),
            "benchmark_sha256": sha256(benchmark),
            "semantic_path": str(semantic.relative_to(ROOT)),
            "semantic_sha256": sha256(semantic),
            "semantic_version": layer["semantic_version"],
            "case_count": len(cases),
            "case_ids": [case["case_id"] for case in cases],
            "languages": dict(Counter(case["language"] for case in cases)),
        }
        manifest["sources"][key] = descriptor
        frozen.append((key, source, semantic, benchmark, descriptor))
    manifest["cohort_sha256"] = frozen_cohort_sha256(manifest["sources"])
    manifest["expected_executions"] = sum(item[4]["case_count"] for item in frozen) * len(profiles)
    write_json(args.output / "manifest.json", manifest)
    emit("full_run_frozen", executions=manifest["expected_executions"], model=identity)

    def assert_frozen() -> None:
        for _, _, semantic, benchmark, descriptor in frozen:
            if (
                sha256(semantic) != descriptor["semantic_sha256"]
                or sha256(benchmark) != descriptor["benchmark_sha256"]
            ):
                raise ValueError("frozen benchmark or semantic layer changed")
        for relative, digest in manifest["code_sha256"].items():
            if sha256(ROOT / relative) != digest:
                raise ValueError(f"evaluation/runtime code changed: {relative}")
        if model_identity(args) != identity:
            raise ValueError("local model identity changed")

    try:
        for key, source, semantic, benchmark, descriptor in frozen:
            emit("gold_audit_started", source=key)
            audit = await audit_gold_source_cohort(
                benchmark_path=benchmark,
                semantic_layer_path=semantic,
                source_id=source["source_id"],
                owner=args.owner,
            )
            gold_path = args.output / f"{key}_gold.json"
            write_json(gold_path, audit)
            descriptor["gold_audit"] = {
                "path": gold_path.name,
                "sha256": sha256(gold_path),
                "status": audit["status"],
                "metrics": audit["metrics"],
            }
            write_json(args.output / "manifest.json", manifest)
            emit(
                "gold_audit_completed", source=key, status=audit["status"], metrics=audit["metrics"]
            )
            if audit["status"] != "complete":
                raise ValueError(f"independent Gold audit incomplete: {key}")

        for key, source, semantic, benchmark, descriptor in frozen:
            for profile in profiles:
                assert_frozen()
                run_id = f"{key}_{profile}"
                emit("benchmark_started", run=run_id, cases=descriptor["case_count"])
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
                    checkpoint_path=args.output / f"{run_id}.checkpoint.json",
                    gold_source_cohort_path=args.output / f"{key}_gold.json",
                    progress_interval_seconds=30,
                )
                report_path = args.output / f"{run_id}.json"
                write_json(report_path, report)
                population = validate_population(report, descriptor["case_ids"])
                manifest["runs"][run_id] = {
                    "report_path": report_path.name,
                    "sha256": sha256(report_path),
                    "population": population,
                    "metrics": report["metrics"],
                }
                write_json(args.output / "manifest.json", manifest)
                emit(
                    "benchmark_completed",
                    run=run_id,
                    population=population,
                    passed=report["metrics"]["passed_case_count"],
                )
        assert_frozen()
        manifest["status"] = (
            "completed"
            if all(
                run["population"]["all_cases_attempted"]
                and not run["population"]["infrastructure_failures"]
                for run in manifest["runs"].values()
            )
            else "incomplete_infrastructure"
        )
        manifest["completed_at"] = datetime.now(UTC).isoformat()
    except BaseException as exc:
        manifest["status"] = (
            "interrupted"
            if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
            else "aborted"
        )
        manifest["error"] = evaluator._redact_error(exc)
        raise
    finally:
        write_json(args.output / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://10.255.254.81:11434")
    parser.add_argument("--model", default="qwen3.8:latest")
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--source",
        action="append",
        choices=tuple(SOURCE_ROLES),
        help="Evaluate only this governed source; repeat to select multiple sources.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=PROFILES,
        help="Evaluate only this execution profile; repeat to select multiple profiles.",
    )
    parser.add_argument("--output", type=Path, required=True)
    result = asyncio.run(evaluate(parser.parse_args()))
    emit("full_run_finished", status=result["status"])
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
