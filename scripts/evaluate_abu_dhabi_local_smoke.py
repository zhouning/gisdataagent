#!/usr/bin/env python3
"""Run a frozen local-model cohort through the ordinary governed query routes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_openai_compatible_models import normalize_base_url, request_json  # noqa: E402

INFRASTRUCTURE_FAILURES = frozenset({"model_provider_unavailable", "virtual_source_unavailable"})
ARTIFACT_OVERRIDE_SCHEMA = "gda.abu-dhabi-local-smoke-artifact-overrides.v1"
PROFILES = ("baseline_sql", "semantic_ir_experimental")


def selected_profiles(values: list[str] | None) -> tuple[str, ...]:
    """Resolve an explicit route scope while preserving the two-route default."""

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


def repository_relative_path(path: Path) -> str:
    """Return a repository-relative path, rejecting paths outside the checkout."""

    candidate = path.resolve()
    try:
        return str(candidate.relative_to(ROOT.resolve()))
    except ValueError as exc:
        raise ValueError("artifact_override_path_outside_repository") from exc


def resolve_repository_file(path: Path, *, error: str) -> Path:
    """Resolve an existing regular file constrained to this repository."""

    candidate = path.resolve()
    repository_relative_path(candidate)
    if not candidate.is_file():
        raise ValueError(error)
    return candidate


def _load_artifact_overrides(path: Path | None) -> dict:
    """Load a checksum-pinned, evaluation-only semantic override manifest.

    Production artifact registry pointers are intentionally not mutable through
    this mechanism.  A canary can replace only the semantic file used by this
    evaluator, and its digest must independently match both the override
    manifest and the frozen cohort.
    """

    if path is None:
        return {"active": False, "semantic_overrides": {}}
    manifest_path = resolve_repository_file(path, error="artifact_override_manifest_missing")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != ARTIFACT_OVERRIDE_SCHEMA:
        raise ValueError("artifact_override_schema_invalid")
    if payload.get("status") != "canary_not_activated":
        raise ValueError("artifact_override_must_be_unactivated_canary")
    raw_overrides = payload.get("semantic_overrides")
    if not isinstance(raw_overrides, dict) or not raw_overrides:
        raise ValueError("artifact_override_semantic_overrides_missing")

    semantic_overrides = {}
    for source_key, descriptor in raw_overrides.items():
        if not isinstance(source_key, str) or not source_key.strip() or not isinstance(descriptor, dict):
            raise ValueError("artifact_override_descriptor_invalid")
        raw_path = Path(str(descriptor.get("path") or ""))
        expected_sha = str(descriptor.get("sha256") or "")
        if raw_path.is_absolute() or ".." in raw_path.parts or len(expected_sha) != 64:
            raise ValueError("artifact_override_descriptor_invalid")
        semantic_path = resolve_repository_file(ROOT / raw_path, error="artifact_override_semantic_missing")
        actual_sha = sha256(semantic_path)
        if actual_sha != expected_sha:
            raise ValueError(f"artifact_override_semantic_checksum_mismatch:{source_key}")
        semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
        semantic_version = str(semantic.get("semantic_version") or "")
        if not semantic_version:
            raise ValueError(f"artifact_override_semantic_version_missing:{source_key}")
        declared_version = str(descriptor.get("semantic_version") or "")
        if declared_version and declared_version != semantic_version:
            raise ValueError(f"artifact_override_semantic_version_mismatch:{source_key}")
        semantic_overrides[source_key] = {
            "path": semantic_path,
            "sha256": actual_sha,
            "semantic_version": semantic_version,
        }
    return {
        "active": True,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256(manifest_path),
        "status": payload["status"],
        "semantic_overrides": semantic_overrides,
    }


def probe(base: str, model: str, timeout: int) -> dict:
    result = {"checked_at": datetime.now(UTC).isoformat(), "base_url": base}
    for name, endpoint, payload in (
        ("models", "/models", None),
        (
            "chat",
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "temperature": 0,
                "max_tokens": 64,
                "reasoning_effort": "none",
            },
        ),
        (
            "embedding",
            "/embeddings",
            {
                "model": os.environ.get("GDA_EMBEDDING_MODEL", "nomic-embed-text-v2-moe:latest"),
                "input": ["district facility count"],
            },
        ),
    ):
        endpoint_base = (
            normalize_base_url(os.environ.get("GDA_EMBEDDING_BASE_URL") or base)
            if name == "embedding"
            else base
        )
        try:
            response, latency = request_json(
                endpoint_base + endpoint,
                api_key=os.environ.get("GDA_EMBEDDING_API_KEY", "ollama")
                if name == "embedding"
                else "ollama",
                payload=payload,
                timeout=timeout if name == "chat" else 30,
            )
            details = {"status": "passed", "latency_ms": latency, "base_url": endpoint_base}
            if payload is not None:
                details["model"] = payload["model"]
            if name == "models":
                details["model_ids"] = [item["id"] for item in response.get("data", [])]
                if model not in details["model_ids"]:
                    raise ValueError("configured chat model is absent from models endpoint")
            elif name == "chat":
                choices = response.get("choices") or []
                if (
                    not choices
                    or str(choices[0].get("message", {}).get("content") or "").strip() != "OK"
                ):
                    raise ValueError("chat probe did not return the requested visible OK response")
                details["response_model"] = response.get("model")
            else:
                rows = response.get("data") or []
                vector = rows[0].get("embedding") if rows else None
                if not isinstance(vector, list) or not vector:
                    raise ValueError("embedding endpoint returned no vector")
                details["dimension"] = len(vector)
                expected = int(os.environ.get("GDA_EMBEDDING_DIMENSION", "768"))
                if len(vector) != expected:
                    raise ValueError(f"embedding dimension mismatch: {len(vector)} != {expected}")
            result[name] = details
        except (OSError, ValueError, KeyError) as exc:
            result[name] = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "base_url": endpoint_base,
            }
    return result


def presentation_checks(
    execution: dict, semantic: Path, language: str, expected_chart: str | None
) -> dict:
    from data_agent.abu_dhabi_nl2sql_presentation import build_nl2sql_answer_presentation

    if execution.get("status") != "ok":
        return {"status": "not_applicable", "browser_verified": False}
    presentation = build_nl2sql_answer_presentation(
        execution,
        semantic_layer_path=semantic,
        language=language,
    )
    if not presentation:
        return {"status": "failed", "reason": "missing_presentation", "browser_verified": False}
    columns = presentation["columns"]
    visualization = presentation.get("visualization") or {}
    checks = {
        "column_keys_match": [item["key"] for item in columns] == execution["result"]["columns"],
        "labels_present": all(str(item["label"]).strip() for item in columns),
        "row_count_match": presentation["row_count"] == execution["result"]["row_count"],
        "read_only_evidence": presentation["evidence"]["read_only"] is True,
    }
    if expected_chart:
        checks["requested_chart_match"] = visualization.get("kind") == expected_chart
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "visualization_type": visualization.get("kind"),
        "browser_verified": False,
    }


def summarize(cases: list[dict]) -> list[dict]:
    groups = {}
    for case in cases:
        planner = case.get("observed", {}).get("planner") or {}
        route = "llm" if planner.get("llm_invoked") else planner.get("route", "unobserved")
        groups.setdefault((case["source_key"], case["execution_profile"], route), []).append(case)
    summaries = []
    for (source, profile, route), rows in groups.items():
        evaluable = [row for row in rows if row.get("failure_class") not in INFRASTRUCTURE_FAILURES]

        def percentile(values: list[float], percentile_value: float) -> float | None:
            if not values:
                return None
            ordered = sorted(values)
            if len(ordered) == 1:
                return round(ordered[0], 3)
            rank = (len(ordered) - 1) * percentile_value / 100
            lower = int(rank)
            upper = min(lower + 1, len(ordered) - 1)
            fraction = rank - lower
            value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
            return round(value, 3)

        def count_check(name: str, checked_rows: list[dict] = evaluable) -> dict:
            values = [
                row["checks"][name]
                for row in checked_rows
                if name in row.get("checks", {})
                and not (
                    name == "gold_result_equivalence_match"
                    and row.get("gold_source_status") == "gold_stale_source_result"
                )
            ]
            return {"passed": sum(value is True for value in values), "evaluated": len(values)}

        presentations = [
            row["presentation"]
            for row in rows
            if row.get("presentation", {}).get("status") in {"passed", "failed"}
        ]
        gold_rows = [
            row
            for row in evaluable
            if row.get("gold_source_status") != "gold_stale_source_result"
            and (
                row.get("has_gold")
                or "gold_result_equivalence_match" in row.get("checks", {})
            )
        ]
        expected_refusal_rows = [
            row for row in evaluable if row.get("expected_status") == "rejected"
        ]
        refusal_tp = sum(
            (row.get("observed") or {}).get("status") == "rejected"
            for row in expected_refusal_rows
        )
        refusal_fp = sum(
            row.get("expected_status") != "rejected"
            and (row.get("observed") or {}).get("status") == "rejected"
            for row in evaluable
        )
        refusal_fn = len(expected_refusal_rows) - refusal_tp
        latency_values = [
            float(
                (
                    ((row.get("observed") or {}).get("generation") or {})
                    .get("total_latency_ms")
                )
                or (
                    ((row.get("observed") or {}).get("generation") or {})
                    .get("latency_ms")
                )
                or 0
            )
            for row in evaluable
            if (
                ((row.get("observed") or {}).get("generation") or {}).get(
                    "total_latency_ms"
                )
                is not None
                or ((row.get("observed") or {}).get("generation") or {}).get(
                    "latency_ms"
                )
                is not None
            )
        ]
        expected_query_rows = [
            row
            for row in evaluable
            if (
                row.get("expected_status") == "ok"
                or row.get("has_gold")
                or "gold_result_equivalence_match" in row.get("checks", {})
            )
        ]
        execution_success_count = sum(
            (row.get("observed") or {}).get("status") == "ok"
            for row in expected_query_rows
        )
        summaries.append(
            {
                "source": source,
                "execution_profile": profile,
                "planner_route": route,
                "case_count": len(rows),
                "passed": sum(row["status"] == "passed" for row in rows),
                "infrastructure_failed": len(rows) - len(evaluable),
                "selection": count_check("table_set_match"),
                "plan_validation": {
                    "passed": sum(
                        (
                            (row.get("observed", {}).get("semantic_plan") or {})
                            .get("validation")
                            or {}
                        ).get("valid")
                        is True
                        for row in rows
                    ),
                    "observed": sum(
                        isinstance(
                            (
                                (row.get("observed", {}).get("semantic_plan") or {})
                                .get("validation")
                                or {}
                            ).get("valid"),
                            bool,
                        )
                        for row in rows
                    ),
                },
                "executed": sum(row.get("observed", {}).get("status") == "ok" for row in rows),
                "result_equivalence": count_check("gold_result_equivalence_match"),
                "presentation": {
                    "passed": sum(row["status"] == "passed" for row in presentations),
                    "evaluated": len(presentations),
                },
                "gold_case_count": len(gold_rows),
                "gold_equivalent": sum(
                    row.get("checks", {}).get("gold_result_equivalence_match") is True
                    for row in gold_rows
                ),
                "current_gold_case_count": len(gold_rows),
                "gold_contract_passed": sum(row.get("status") == "passed" for row in gold_rows),
                "expected_query_case_count": len(expected_query_rows),
                "query_execution_success_count": execution_success_count,
                "query_execution_success_rate": (
                    execution_success_count / len(expected_query_rows)
                    if expected_query_rows
                    else None
                ),
                "expected_refusals": len(expected_refusal_rows),
                "correct_refusals": refusal_tp,
                "observed_refusals": sum(
                    (row.get("observed") or {}).get("status") == "rejected"
                    for row in evaluable
                ),
                "refusal": {
                    "true_positive_count": refusal_tp,
                    "false_positive_count": refusal_fp,
                    "false_negative_count": refusal_fn,
                    "precision": refusal_tp / (refusal_tp + refusal_fp)
                    if refusal_tp + refusal_fp
                    else None,
                    "recall": refusal_tp / (refusal_tp + refusal_fn)
                    if refusal_tp + refusal_fn
                    else None,
                },
                "mean_generation_latency_ms": (
                    round(sum(latency_values) / len(latency_values), 3)
                    if latency_values
                    else None
                ),
                "p95_generation_latency_ms": percentile(latency_values, 95),
                "generation_latency_basis": "total_including_retries",
                "failure_classes": dict(
                    Counter(row["failure_class"] for row in rows if row.get("failure_class"))
                ),
            }
        )
    return summaries


def selection_checks(case: dict, semantic: dict) -> dict:
    from data_agent.governed_virtual_nl2sql import (
        _ground_semantic_layer_for_prompt,
        resolve_direct_metric_contract,
        resolve_semantic_answerability_contract,
    )

    grounded, evidence = _ground_semantic_layer_for_prompt(case["question"], semantic)
    tables = {item["physical_table"] for item in grounded["table_bindings"]}
    expected = case["expected"]
    alternatives = expected.get("allowed_table_sets") or [expected["tables"]]
    direct = resolve_direct_metric_contract(case["question"], case["language"], semantic)
    answerability = resolve_semantic_answerability_contract(
        case["question"], case["language"], semantic
    )
    return {
        "case_id": case["case_id"],
        "expected_status": expected["status"],
        "retrieved_tables": sorted(tables),
        "strategy": evidence["strategy"],
        "expected_tables_recalled": any(set(values) <= tables for values in alternatives)
        if expected["status"] == "ok"
        else None,
        "direct_metric_status": direct["status"],
        "direct_metric_contract_id": direct.get("contract_id"),
        "answerability_status": answerability["status"],
        "llm_invoked": False,
        "source_executed": False,
    }


def assert_artifacts_unchanged(report: dict) -> None:
    for artifact in report["artifacts"].values():
        for role in ("semantic", "benchmark"):
            if sha256(ROOT / artifact[role + "_path"]) != artifact[role + "_sha256"]:
                raise ValueError(f"{role} artifact changed during evaluation")
    override = report.get("artifact_overrides") or {}
    if override.get("active") and sha256(ROOT / override["manifest_path"]) != override[
        "manifest_sha256"
    ]:
        raise ValueError("artifact_override_manifest_changed")
    root = ROOT.resolve()
    for relative, digest in (report.get("code_sha256") or {}).items():
        candidate = (ROOT / str(relative)).resolve()
        if root not in candidate.parents or sha256(candidate) != digest:
            raise ValueError("evaluation/runtime code changed")


async def evaluate(args: argparse.Namespace) -> dict:
    from dotenv import load_dotenv

    # Apply the explicit evaluation profile after loading operator credentials.
    # Import runtime modules only afterwards so model registry initialization sees it.
    for path in (
        Path(os.environ.get("GDA_OPERATOR_ENV_FILE", ROOT / "data_agent/.env")),
        ROOT / "data_agent/.vsource-secret.env",
        ROOT / "data_agent/.abu-dhabi-vsource-secret.env",
    ):
        load_dotenv(path, override=False)
    base = normalize_base_url(args.base_url)
    os.environ.update(
        {
            "GDA_LLM_PROVIDER": "ollama",
            "GDA_LLM_MODEL": args.model,
            "GDA_LLM_BASE_URL": base,
            "GDA_LLM_API_KEY": "ollama",
            "OLLAMA_API_BASE": base.removesuffix("/v1"),
            "GDA_LLM_TIMEOUT_SECONDS": str(args.timeout),
            "GDA_LLM_ENABLE_THINKING": "false",
        }
    )
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)

    from data_agent import free_form_nl2sql_benchmark as evaluator
    from data_agent.abu_dhabi_artifact_registry import (
        current_artifact_manifest,
        current_artifact_path,
    )
    from data_agent.governed_virtual_nl2sql import (
        _generation_budget_seconds,
        run_governed_virtual_nl2sql,
    )
    from data_agent.migration_runner import verify_runtime_schema_state
    from data_agent.model_gateway import create_model
    from data_agent.nl2sql_model_profile import profile_for_model

    profiles = selected_profiles(args.profile)
    args.output.mkdir(parents=True, exist_ok=False)
    cohort_path = resolve_repository_file(args.cohort, error="cohort_missing")
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    artifact_overrides = _load_artifact_overrides(args.artifact_overrides)
    report = {
        "schema": "gda.abu-dhabi-local-smoke.v1",
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "cohort_sha256": sha256(cohort_path),
        "cases": [],
        "model": {
            "provider": "ollama",
            "model": args.model,
            "base_url": base,
            "thinking": False,
            "temperature": None,
            "temperature_source": "provider_default_not_overridden_by_query_runtime",
            "probe_temperature": 0,
            "timeout_seconds": args.timeout,
            "generation_budget_seconds": _generation_budget_seconds(args.timeout),
            "compatibility_profile": profile_for_model(args.model),
        },
        "claim_boundary": {
            "full_database_accuracy": False,
            "vector_retrieval_evaluated": False,
            "source_rows_persisted": False,
            "browser_verified": False,
            "retrieval": "published_semantics_lexical",
            "gold_freshness_revalidated": False,
            "current_bundle_changed": False,
        },
        "execution_profiles": list(profiles),
    }
    report["artifact_overrides"] = {
        "active": artifact_overrides["active"],
        "status": artifact_overrides.get("status"),
        "manifest_path": (
            repository_relative_path(artifact_overrides["manifest_path"])
            if artifact_overrides["active"]
            else None
        ),
        "manifest_sha256": artifact_overrides.get("manifest_sha256"),
        "semantic_overrides": {
            source_key: {
                "path": repository_relative_path(details["path"]),
                "sha256": details["sha256"],
                "semantic_version": details["semantic_version"],
            }
            for source_key, details in artifact_overrides["semantic_overrides"].items()
        },
        "current_bundle_changed": False,
    }
    report["code_sha256"] = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in (
            Path(__file__),
            ROOT / "data_agent/governed_virtual_nl2sql.py",
            ROOT / "data_agent/semantic_query_ir.py",
            ROOT / "data_agent/model_gateway.py",
            ROOT / "data_agent/free_form_nl2sql_benchmark.py",
            ROOT / "data_agent/abu_dhabi_nl2sql_presentation.py",
            ROOT / "data_agent/abu_dhabi_nl2sql_map_presentation.py",
            ROOT / "data_agent/nl2sql_model_profile.py",
        )
    }
    report["model"]["effective_route"] = str(create_model(args.model).model)
    if report["model"]["effective_route"] != f"ollama_chat/{args.model}":
        raise ValueError("effective model route does not match explicit Ollama configuration")
    report["artifacts"] = {}
    frozen = []
    for source in cohort["sources"]:
        key = source["source_key"]
        manifest = current_artifact_manifest(key)
        override = artifact_overrides["semantic_overrides"].get(key)
        semantic = override["path"] if override else current_artifact_path(key, "semantic")
        benchmark = current_artifact_path(key, source["benchmark_role"])
        for role, path in (("semantic", semantic), ("benchmark", benchmark)):
            if sha256(path) != source[role + "_sha256"]:
                raise ValueError(f"frozen {key} {role} fingerprint changed")
        layer = json.loads(semantic.read_text())
        report["artifacts"][key] = {
            "semantic_path": str(semantic.relative_to(ROOT)),
            "semantic_version": layer["semantic_version"],
            "semantic_sha256": sha256(semantic),
            "benchmark_path": str(benchmark.relative_to(ROOT)),
            "benchmark_sha256": sha256(benchmark),
            "source": manifest["source"],
            "semantic_resolution": "canary_override" if override else "current_bundle",
            "current_bundle_semantic_path": repository_relative_path(
                current_artifact_path(key, "semantic")
            ),
            "current_bundle_semantic_sha256": sha256(current_artifact_path(key, "semantic")),
        }
        cases = evaluator._validate_benchmark(
            json.loads(benchmark.read_text()),
            layer,
            source_id=manifest["source"]["source_id"],
            benchmark_path=benchmark,
        )
        by_id = {case["case_id"]: case for case in cases}
        frozen.append(
            (
                source,
                manifest,
                semantic,
                benchmark,
                layer,
                [by_id[item["case_id"]] for item in source["cases"]],
            )
        )
    unknown_override_sources = set(artifact_overrides["semantic_overrides"]) - {
        source["source_key"] for source in cohort["sources"]
    }
    if unknown_override_sources:
        raise ValueError(
            "artifact_override_source_not_in_cohort:" + ",".join(sorted(unknown_override_sources))
        )
    report["cohort"] = cohort
    report["selection_only"] = [
        {"source_key": source["source_key"], **selection_checks(case, layer)}
        for source, manifest, semantic, benchmark, layer, cases in frozen
        for case in cases
    ]
    write_json(args.output / "report.json", report)
    if args.selection_only:
        report["status"] = "selection_only_completed"
        report["completed_at"] = datetime.now(UTC).isoformat()
        return report
    if args.gold_only:
        from data_agent.nl2sql_gold_source_cohort import audit_gold_source_cohort

        report["gold_audits"] = {}
        for source, manifest, semantic, benchmark, _layer, cases in frozen:
            contract_ids = tuple(
                sorted(
                    {
                        case["expected"]["gold_result_contract"]["contract_id"]
                        for case in cases
                        if case["expected"].get("gold_result_contract")
                    }
                )
            )
            audit = await audit_gold_source_cohort(
                benchmark_path=benchmark,
                semantic_layer_path=semantic,
                source_id=manifest["source"]["source_id"],
                owner=args.owner,
                contract_ids=contract_ids,
            )
            audit_path = args.output / f"{source['source_key']}_gold.json"
            write_json(audit_path, audit)
            report["gold_audits"][source["source_key"]] = {
                "path": str(audit_path),
                "sha256": sha256(audit_path),
                "status": audit["status"],
                "metrics": audit.get("metrics"),
            }
            write_json(args.output / "report.json", report)
        assert_artifacts_unchanged(report)
        report["status"] = "gold_audit_completed"
        report["completed_at"] = datetime.now(UTC).isoformat()
        return report
    try:
        tags, _ = request_json(base.removesuffix("/v1") + "/api/tags", api_key="", timeout=10)
        report["model"]["installed"] = next(
            item for item in tags["models"] if item["name"] == args.model
        )
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        report["status"] = "infrastructure_blocked"
        report["preflight"] = {
            "inventory": {"status": "failed", "error": evaluator._redact_error(exc)}
        }
        return report
    report["preflight"] = probe(base, args.model, args.timeout)
    write_json(args.output / "report.json", report)
    if any(report["preflight"][name]["status"] != "passed" for name in ("models", "chat")):
        report["status"] = "infrastructure_blocked"
        return report
    try:
        verify_runtime_schema_state(
            required_migrations=("012_virtual_sources", "182_governed_virtual_source_discovery")
        )
    except Exception as exc:
        report["status"] = "infrastructure_blocked"
        report["preflight"]["control_plane"] = {
            "status": "failed",
            "error": evaluator._redact_error(exc),
        }
        return report
    for profile in profiles:
        for source, manifest, semantic, _benchmark, _layer, cases in frozen:
            for case, specification in zip(cases, source["cases"], strict=True):
                assert_artifacts_unchanged(report)
                started = time.perf_counter()
                try:
                    execution = await run_governed_virtual_nl2sql(
                        question=case["question"],
                        semantic_layer_path=semantic,
                        source_id=manifest["source"]["source_id"],
                        owner=args.owner,
                        model_name=args.model,
                        reasoning_effort="none",
                        timeout_seconds=args.timeout,
                        execution_profile=profile,
                        verify_platform_schema=False,
                        reuse_runtime_metadata=True,
                    )
                    checked = evaluator._check_case(
                        case,
                        execution,
                        source_id=manifest["source"]["source_id"],
                        database_name=manifest["source"]["database_name"],
                        authorized_schemas=manifest["source"]["allowed_schemas"],
                    )
                    checked["failure_class"] = evaluator._failure_class(checked)
                    checked["presentation"] = presentation_checks(
                        execution, semantic, case["language"], specification.get("expected_chart")
                    )
                    if checked["presentation"]["status"] == "failed":
                        checked["presentation_failure_class"] = "presentation_contract_failure"
                except Exception as exc:
                    checked = {
                        "case_id": case["case_id"],
                        "status": "failed",
                        "checks": {},
                        "error": evaluator._redact_error(exc),
                    }
                    checked["failure_class"] = (
                        evaluator._failure_class(checked) or "evaluation_error"
                    )
                assert_artifacts_unchanged(report)
                checked.update(
                    source_key=source["source_key"],
                    execution_profile=profile,
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                )
                report["cases"].append(checked)
                report["summary"] = summarize(report["cases"])
                write_json(args.output / "report.json", report)
                print(
                    json.dumps(
                        {
                            key: checked.get(key)
                            for key in (
                                "source_key",
                                "execution_profile",
                                "case_id",
                                "status",
                                "failure_class",
                                "elapsed_seconds",
                            )
                        }
                    ),
                    flush=True,
                )
                if checked.get("failure_class") in INFRASTRUCTURE_FAILURES:
                    report["status"] = "infrastructure_blocked"
                    return report
    from data_agent.abu_dhabi_nl2sql_map_presentation import build_governed_nl2sql_map_update

    report["map_controls"] = []
    frozen_by_source = {
        source["source_key"]: (manifest, semantic)
        for source, manifest, semantic, _benchmark, _layer, _cases in frozen
    }
    for control in cohort.get("map_controls", []):
        assert_artifacts_unchanged(report)
        try:
            manifest, semantic = frozen_by_source[control["source_key"]]
        except KeyError as exc:
            raise ValueError("map_control_source_not_in_cohort") from exc
        source_id = manifest["source"]["source_id"]
        for profile in profiles:
            execution = await run_governed_virtual_nl2sql(
                question=control["question"],
                semantic_layer_path=semantic,
                source_id=source_id,
                owner=args.owner,
                model_name=args.model,
                reasoning_effort="none",
                timeout_seconds=args.timeout,
                execution_profile=profile,
                verify_platform_schema=False,
                reuse_runtime_metadata=True,
            )
            update, diagnostic = await build_governed_nl2sql_map_update(
                report=execution,
                question=control["question"],
                semantic_layer_path=semantic,
                source_id=source_id,
                owner=args.owner,
                language=control["language"],
            )
            report["map_controls"].append(
                {
                    "source_key": control["source_key"],
                    "question": control["question"],
                    "execution_profile": profile,
                    "planner": execution.get("planner"),
                    "query_status": execution["status"],
                    "diagnostic": diagnostic,
                    "feature_count_match": diagnostic.get("feature_count")
                    == control["expected_feature_count"],
                    "map_summary": update.get("summary") if update else None,
                    "browser_verified": False,
                    "included_in_model_accuracy": False,
                }
            )
            write_json(args.output / "report.json", report)
    assert_artifacts_unchanged(report)
    report["status"] = "completed"
    report["completed_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument(
        "--artifact-overrides",
        type=Path,
        help="Repository-contained, checksum-pinned, unactivated semantic canary manifest.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--profile",
        action="append",
        choices=PROFILES,
        help="Execution route to evaluate; repeat to select both (default: both).",
    )
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument("--gold-only", action="store_true")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    report = asyncio.run(evaluate(args))
    write_json(args.output / "report.json", report)
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))
    return (
        0
        if report["status"] in {"completed", "selection_only_completed", "gold_audit_completed"}
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
