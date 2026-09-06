"""Evaluate reviewed Liveability + Makani cross-source aggregate contracts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .abu_dhabi_federated_nl2sql import (
    FEDERATED_SEMANTIC_PATH,
    PLANNER_VERSION,
    resolve_abu_dhabi_federated_request,
    run_abu_dhabi_federated_request,
)
from .governed_virtual_nl2sql import MAX_QUESTION_LENGTH, SUPPORTED_LANGUAGES

BENCHMARK_SCHEMA = "gda.federated-free-form-nl2sql-benchmark.v1"
GOLD_SCHEMA = "gda.federated-nl2sql-gold-bundle.v1"
REPORT_SCHEMA = "gda.federated-free-form-nl2sql-benchmark-report.v1"


class FederatedBenchmarkConfigurationError(ValueError):
    """The federated benchmark definition is unsafe or inconsistent."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FederatedBenchmarkConfigurationError(
            f"Cannot load benchmark artifact: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise FederatedBenchmarkConfigurationError("Benchmark artifact must be an object")
    return payload


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_artifact_path(value: str, *, benchmark_path: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    repository_candidate = Path(__file__).resolve().parents[1] / candidate
    if repository_candidate.exists():
        return repository_candidate
    return benchmark_path.parent / candidate


def _load_gold_bundle(
    reference: dict[str, Any],
    *,
    benchmark_path: Path,
    semantic: dict[str, Any],
    expected_contract_id: str,
) -> dict[str, Any]:
    if not isinstance(reference, dict) or not reference.get("path"):
        raise FederatedBenchmarkConfigurationError("gold_bundle.path is required")
    path = _resolve_artifact_path(str(reference["path"]), benchmark_path=benchmark_path)
    payload = _load_json(path)
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    if reference.get("sha256") and reference["sha256"] != checksum:
        raise FederatedBenchmarkConfigurationError(
            f"Federated Gold bundle checksum mismatch: {path}"
        )
    if payload.get("schema") != GOLD_SCHEMA:
        raise FederatedBenchmarkConfigurationError(
            f"Unsupported federated Gold bundle: {path}"
        )
    if payload.get("federated_contract_id") != expected_contract_id:
        raise FederatedBenchmarkConfigurationError(
            f"Federated Gold contract differs from benchmark: {path}"
        )
    if payload.get("semantic_version") != semantic.get("semantic_version"):
        raise FederatedBenchmarkConfigurationError(
            f"Federated Gold semantic version drift: {path}"
        )
    policy = payload.get("execution_policy") or {}
    if policy.get("cross_database_sql") is not False:
        raise FederatedBenchmarkConfigurationError("Gold must disable cross-database SQL")
    if policy.get("cross_source_join") is not False:
        raise FederatedBenchmarkConfigurationError("Gold must disable cross-source joins")
    expected = payload.get("expected_bundle") or {}
    if expected.get("section_count") != 2:
        raise FederatedBenchmarkConfigurationError("Gold bundle must contain two sections")
    if len(str(expected.get("bundle_fingerprint") or "")) != 64:
        raise FederatedBenchmarkConfigurationError("Gold bundle fingerprint is invalid")

    semantic_sources = semantic.get("sources") or {}
    semantic_contract = next(
        (
            item
            for item in semantic.get("contracts") or []
            if str(item.get("contract_id") or "") == expected_contract_id
        ),
        None,
    )
    if semantic_contract is None:
        raise FederatedBenchmarkConfigurationError(
            "Gold references an unknown runtime contract"
        )
    runtime_contracts = {
        str(item.get("source") or ""): str(item.get("metric_contract_id") or "")
        for item in semantic_contract.get("subplans") or []
    }
    gold_sources = payload.get("sources") or []
    if [item.get("source") for item in gold_sources] != ["liveability", "makani"]:
        raise FederatedBenchmarkConfigurationError(
            "Gold source order must be liveability then makani"
        )
    for item in gold_sources:
        source = semantic_sources.get(str(item.get("source"))) or {}
        for key in (
            "source_id",
            "database_name",
            "discovery_fingerprint",
            "profile_fingerprint",
        ):
            if item.get(key) != source.get(key):
                raise FederatedBenchmarkConfigurationError(
                    f"Federated Gold source binding drift: {key}"
                )
        result = item.get("expected_result") or {}
        if item.get("runtime_metric_contract_id") != runtime_contracts.get(
            str(item.get("source") or "")
        ):
            raise FederatedBenchmarkConfigurationError(
                "Federated Gold runtime metric contract drift"
            )
        if not isinstance(result.get("row_count"), int):
            raise FederatedBenchmarkConfigurationError("Gold row_count is invalid")
        if len(str(result.get("equivalence_fingerprint") or "")) != 64:
            raise FederatedBenchmarkConfigurationError(
                "Gold source equivalence fingerprint is invalid"
            )
    return {
        "path": str(path),
        "sha256": checksum,
        "bundle_contract_id": payload.get("bundle_contract_id"),
        "federated_contract_id": payload.get("federated_contract_id"),
        "expected_bundle": expected,
        "sources": gold_sources,
    }


def _validate_benchmark(
    benchmark: dict[str, Any],
    semantic: dict[str, Any],
    *,
    benchmark_path: Path,
) -> list[dict[str, Any]]:
    if benchmark.get("schema") != BENCHMARK_SCHEMA:
        raise FederatedBenchmarkConfigurationError("Unsupported benchmark schema")
    if semantic.get("schema") != "gda.federated-virtual-semantic-layer.v1":
        raise FederatedBenchmarkConfigurationError("Unsupported semantic layer schema")
    if (semantic.get("activation_gate") or {}).get("active") is not True:
        raise FederatedBenchmarkConfigurationError("Federated semantic layer is inactive")
    if benchmark.get("semantic_version") != semantic.get("semantic_version"):
        raise FederatedBenchmarkConfigurationError("Benchmark semantic version drift")
    if semantic.get("contract_format") != "metric_contract_refs_v1":
        raise FederatedBenchmarkConfigurationError(
            "Runtime federation must use metric contract references"
        )
    if semantic.get("benchmark_artifacts_embedded") is not False:
        raise FederatedBenchmarkConfigurationError(
            "Runtime semantic layer contains benchmark artifacts"
        )
    integrity = benchmark.get("evaluation_integrity") or {}
    if integrity != {
        "runtime_semantic_contains_benchmark_questions": False,
        "runtime_semantic_contains_gold_references": False,
        "gold_loaded_only_by_benchmark_runner": True,
    }:
        raise FederatedBenchmarkConfigurationError(
            "Benchmark evaluation-integrity declaration is invalid"
        )

    expected_sources = [
        {
            "source": name,
            "source_id": source.get("source_id"),
            "database_name": source.get("database_name"),
            "authorized_schemas": source.get("authorized_schemas"),
            "discovery_fingerprint": source.get("discovery_fingerprint"),
            "profile_fingerprint": source.get("profile_fingerprint"),
        }
        for name, source in (semantic.get("sources") or {}).items()
    ]
    if benchmark.get("sources") != expected_sources:
        raise FederatedBenchmarkConfigurationError("Benchmark source bindings drifted")

    contract_ids = {
        str(contract.get("contract_id")) for contract in semantic.get("contracts") or []
    }
    cases = benchmark.get("cases") or []
    if not cases:
        raise FederatedBenchmarkConfigurationError("Benchmark must contain cases")
    seen: set[str] = set()
    normalized = []
    serialized_semantic = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    physical_or_sql = re.compile(
        r"(?:\b(?:select|from|join|where|group\s+by|order\s+by|limit|sql|schema|public)\b|st_[a-z0-9_]+)",
        re.IGNORECASE,
    )
    for case in cases:
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in seen:
            raise FederatedBenchmarkConfigurationError(
                f"Duplicate or empty case_id: {case_id}"
            )
        seen.add(case_id)
        language = str(case.get("language") or "")
        if language not in SUPPORTED_LANGUAGES:
            raise FederatedBenchmarkConfigurationError(
                f"Unsupported case language: {language}"
            )
        question = str(case.get("question") or "").strip()
        if not question or len(question) > MAX_QUESTION_LENGTH:
            raise FederatedBenchmarkConfigurationError(
                f"Case {case_id} question length is invalid"
            )
        if question.casefold() in serialized_semantic:
            raise FederatedBenchmarkConfigurationError(
                f"Case {case_id} question is embedded in runtime semantics"
            )
        if physical_or_sql.search(question):
            raise FederatedBenchmarkConfigurationError(
                f"Case {case_id} contains a physical or SQL identifier"
            )
        expected = case.get("expected") or {}
        status = str(expected.get("status") or "")
        if status not in {"ok", "rejected"}:
            raise FederatedBenchmarkConfigurationError(
                f"Case {case_id} expected.status is invalid"
            )
        contract_id = str(expected.get("contract_id") or "")
        gold = None
        if status == "ok":
            if contract_id not in contract_ids:
                raise FederatedBenchmarkConfigurationError(
                    f"Case {case_id} references an unknown contract"
                )
            gold = _load_gold_bundle(
                expected.get("gold_bundle") or {},
                benchmark_path=benchmark_path,
                semantic=semantic,
                expected_contract_id=contract_id,
            )
        elif contract_id or expected.get("gold_bundle"):
            raise FederatedBenchmarkConfigurationError(
                f"Rejected case {case_id} cannot bind a Gold bundle"
            )
        normalized.append(
            {
                **case,
                "case_id": case_id,
                "language": language,
                "question": question,
                "expected": {
                    **expected,
                    "status": status,
                    "contract_id": contract_id,
                    "gold_bundle": gold,
                },
            }
        )
    return normalized


def _subplan_evidence(report: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = []
    for section in (report.get("result") or {}).get("sections") or []:
        planner = section.get("planner") or {}
        semantic_plan = (section.get("query") or {}).get("semantic_plan") or {}
        evidence.append(
            {
                "source": section.get("source"),
                "source_id": section.get("source_id"),
                "metric_contract_id": section.get("metric_contract_id"),
                "planner_route": planner.get("route"),
                "llm_invoked": planner.get("llm_invoked"),
                "semantic_plan_status": semantic_plan.get("status"),
                "semantic_plan_sha256": (
                    semantic_plan.get("fingerprints") or {}
                ).get("semantic_ir_sha256"),
            }
        )
    return evidence


def _safe_observation(report: dict[str, Any]) -> dict[str, Any]:
    contract = report.get("contract") or {}
    result = report.get("result") or {}
    sections = result.get("sections") or []
    semantic_plan = report.get("semantic_plan") or {}
    return {
        "status": report.get("status"),
        "language": report.get("language"),
        "reason": report.get("reason"),
        "error": report.get("error"),
        "subquery_failures": list(report.get("subquery_failures") or []),
        "contract_id": contract.get("contract_id"),
        "application": contract.get("application"),
        "cross_database_sql": contract.get("cross_database_sql"),
        "cross_source_join": contract.get("cross_source_join"),
        "source_ids": [item.get("source_id") for item in report.get("sources") or []],
        "section_count": result.get("section_count"),
        "bundle_fingerprint": result.get("bundle_fingerprint"),
        "semantic_plan_status": semantic_plan.get("status"),
        "semantic_plan_valid": (semantic_plan.get("validation") or {}).get("valid"),
        "semantic_plan_sha256": (semantic_plan.get("fingerprints") or {}).get(
            "semantic_ir_sha256"
        ),
        "source_evidence": [
            {
                "source": section.get("source"),
                "source_id": section.get("source_id"),
                "row_count": (section.get("result") or {}).get("row_count"),
                "equivalence_fingerprint": (
                    (section.get("result") or {}).get("equivalence_fingerprints") or {}
                ).get("unordered_position_numeric6_fingerprint"),
                "source_rows_persisted": section.get("source_rows_persisted"),
            }
            for section in sections
        ],
        "subplans": _subplan_evidence(report),
        "source_rows_persisted": report.get("source_rows_persisted"),
    }


def _check_case(case: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected"]
    observed = _safe_observation(report)
    checks = {
        "status_match": observed["status"] == expected["status"],
        "language_match": observed["language"] == case["language"],
        "source_rows_not_persisted": observed["source_rows_persisted"] is False,
    }
    if expected["status"] == "ok":
        gold = expected["gold_bundle"]
        gold_sources = gold["sources"]
        actual_sources = observed["source_evidence"]
        checks.update(
            {
                "contract_match": observed["contract_id"]
                == expected["contract_id"],
                "application_merge_match": observed["application"]
                == "independent_sections",
                "cross_database_sql_disabled": observed["cross_database_sql"] is False,
                "cross_source_join_disabled": observed["cross_source_join"] is False,
                "source_ids_match": observed["source_ids"]
                == list(expected.get("source_ids") or []),
                "section_count_match": observed["section_count"] == 2,
                "bundle_fingerprint_match": observed["bundle_fingerprint"]
                == gold["expected_bundle"]["bundle_fingerprint"],
                "source_gold_equivalence_match": len(actual_sources) == 2
                and all(
                    actual.get("source") == expected_source.get("source")
                    and actual.get("source_id") == expected_source.get("source_id")
                    and actual.get("row_count")
                    == (expected_source.get("expected_result") or {}).get("row_count")
                    and actual.get("equivalence_fingerprint")
                    == (expected_source.get("expected_result") or {}).get(
                        "equivalence_fingerprint"
                    )
                    for actual, expected_source in zip(
                        actual_sources, gold_sources, strict=True
                    )
                ),
                "section_rows_not_persisted": all(
                    item.get("source_rows_persisted") is False
                    for item in actual_sources
                ),
                "federated_semantic_plan_validated": observed[
                    "semantic_plan_status"
                ]
                == "planned"
                and observed["semantic_plan_valid"] is True
                and len(str(observed["semantic_plan_sha256"] or "")) == 64,
                "source_semantic_plans_validated": len(observed["subplans"]) == 2
                and all(
                    item.get("semantic_plan_status") == "planned"
                    and len(str(item.get("semantic_plan_sha256") or "")) == 64
                    for item in observed["subplans"]
                ),
                "deterministic_contract_execution": len(observed["subplans"]) == 2
                and all(
                    item.get("planner_route")
                    == "deterministic_reviewed_metric_contract"
                    and item.get("llm_invoked") is False
                    for item in observed["subplans"]
                ),
            }
        )
    else:
        checks.update(
            {
                "rejection_reason_match": observed["reason"]
                == "question_not_covered_by_reviewed_cross_source_contract",
                "no_source_execution": not observed["source_ids"]
                and observed["section_count"] is None,
            }
        )
    passed = all(checks.values())
    return {
        "case_id": case["case_id"],
        "language": case["language"],
        "question": case["question"],
        "status": "passed" if passed else "failed",
        "checks": checks,
        "observed": observed,
        "gold_bundle": (
            {
                "bundle_contract_id": expected["gold_bundle"]["bundle_contract_id"],
                "path": expected["gold_bundle"]["path"],
                "sha256": expected["gold_bundle"]["sha256"],
            }
            if expected.get("gold_bundle")
            else None
        ),
        "failure_reasons": sorted(name for name, value in checks.items() if not value),
    }


def _redact_error(value: Any) -> str:
    message = str(value)
    for name in (
        "OPENAI_API_KEY",
        "GDA_LLM_API_KEY",
        "GDA_VSOURCE_PASSWORD",
        "GDA_CONTROL_PLANE_ENCRYPTION_SECRET",
    ):
        secret = os.environ.get(name, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", message)
    return message[:500]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int((percentile * len(ordered) + 99) // 100)))
    return round(ordered[rank - 1], 3)


async def run_federated_benchmark(
    *,
    benchmark_path: Path,
    semantic_layer_path: Path = FEDERATED_SEMANTIC_PATH,
    owner: str,
    model_name: str = "gpt-5.1",
    reasoning_effort: str = "medium",
    timeout_seconds: int = 180,
    case_ids: tuple[str, ...] | None = None,
    request_interval_seconds: float | None = None,
) -> dict[str, Any]:
    """Run reviewed cross-source cases through the product federation route."""

    from .migration_runner import verify_schema_state

    verify_schema_state()
    benchmark = _load_json(benchmark_path)
    semantic = _load_json(semantic_layer_path)
    cases = _validate_benchmark(
        benchmark,
        semantic,
        benchmark_path=benchmark_path,
    )
    full_case_count = len(cases)
    if case_ids:
        requested = set(case_ids)
        unknown = sorted(requested - {case["case_id"] for case in cases})
        if unknown:
            raise FederatedBenchmarkConfigurationError(
                "Unknown case_id(s): " + ", ".join(unknown)
            )
        cases = [case for case in cases if case["case_id"] in requested]
    if not cases:
        raise FederatedBenchmarkConfigurationError("Case selection produced no cases")
    if request_interval_seconds is None:
        request_interval_seconds = float(
            os.environ.get("GDA_NL2SQL_BENCH_REQUEST_INTERVAL_SECONDS", "0")
        )
    if request_interval_seconds < 0 or request_interval_seconds > 60:
        raise FederatedBenchmarkConfigurationError(
            "request_interval_seconds must be between 0 and 60"
        )

    case_reports = []
    for index, case in enumerate(cases):
        try:
            request = resolve_abu_dhabi_federated_request(
                "@AbuDhabi " + case["question"]
            )
            if request is None or not request.accepted:
                raise FederatedBenchmarkConfigurationError(
                    f"Case {case['case_id']} cannot be routed"
                )
            execution = await run_abu_dhabi_federated_request(
                request,
                semantic_layer_path=semantic_layer_path,
                owner=owner,
                model_name=model_name,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
            )
            case_reports.append(_check_case(case, execution))
        except Exception as exc:
            case_reports.append(
                {
                    "case_id": case["case_id"],
                    "language": case["language"],
                    "question": case["question"],
                    "status": "failed",
                    "checks": {},
                    "observed": {
                        "status": "error",
                        "source_rows_persisted": False,
                    },
                    "gold_bundle": None,
                    "failure_reasons": ["benchmark_execution_error"],
                    "error": _redact_error(exc),
                }
            )
        if request_interval_seconds and index + 1 < len(cases):
            await asyncio.sleep(request_interval_seconds)

    passed = [item for item in case_reports if item["status"] == "passed"]
    gold_pairs = [
        (item, case)
        for item, case in zip(case_reports, cases, strict=True)
        if case["expected"].get("gold_bundle")
    ]
    refusal_pairs = [
        (item, case)
        for item, case in zip(case_reports, cases, strict=True)
        if case["expected"]["status"] == "rejected"
    ]
    subplans = [
        subplan
        for item in case_reports
        for subplan in (item.get("observed") or {}).get("subplans") or []
    ]
    by_language = {}
    for language in SUPPORTED_LANGUAGES:
        language_items = [
            item
            for item, case in zip(case_reports, cases, strict=True)
            if case["language"] == language
        ]
        if language_items:
            language_passed = sum(
                1 for item in language_items if item["status"] == "passed"
            )
            by_language[language] = {
                "case_count": len(language_items),
                "passed_case_count": language_passed,
                "case_pass_rate": _ratio(language_passed, len(language_items)),
            }
    status_counts = Counter(
        str((item.get("observed") or {}).get("status") or "error")
        for item in case_reports
    )
    benchmark_complete = len(cases) == full_case_count
    gold_passed = sum(1 for item, _case in gold_pairs if item["status"] == "passed")
    reviewed_contract_count = int(
        (benchmark.get("coverage") or {}).get(
            "reviewed_cross_source_contract_count",
            len(semantic.get("contracts") or []),
        )
    )
    refusal_passed = sum(
        1
        for item, _case in refusal_pairs
        if (item.get("observed") or {}).get("status") == "rejected"
    )
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if len(passed) == len(case_reports) else "failed",
        "scope": "reviewed_cross_source_independent_aggregate_evaluation",
        "benchmark_accuracy_claim": bool(
            benchmark_complete and gold_pairs and gold_passed == len(gold_pairs)
        ),
        "benchmark": {
            "benchmark_id": benchmark.get("benchmark_id"),
            "version": benchmark.get("version"),
            "source_file_sha256": _sha256_json(benchmark),
            "semantic_layer_version": semantic.get("semantic_version"),
            "planner_version": PLANNER_VERSION,
            "definition_complete": (
                (benchmark.get("completeness") or {}).get("status") == "complete"
            ),
            "run_complete": benchmark_complete,
            "selected_case_ids": [case["case_id"] for case in cases],
            "coverage": benchmark.get("coverage") or {},
            "claim_boundary": benchmark.get("claim_boundary") or {},
        },
        "planner": {
            "version": PLANNER_VERSION,
            "route": "reviewed_federated_metric_contract",
            "llm_invoked": False,
            "requested_model_not_used": model_name,
            "requested_reasoning_effort_not_used": reasoning_effort,
        },
        "sources": benchmark.get("sources"),
        "execution_policy": {
            "mode": "parallel_registered_virtual_sources_application_merge",
            "cross_database_sql": False,
            "cross_source_join": False,
            "source_rows_persisted": False,
        },
        "metrics": {
            "case_count": len(case_reports),
            "passed_case_count": len(passed),
            "case_pass_rate": _ratio(len(passed), len(case_reports)),
            "status_counts": dict(sorted(status_counts.items())),
            "expected_query_case_count": len(gold_pairs),
            "query_execution_success_count": sum(
                1
                for item, _case in gold_pairs
                if (item.get("observed") or {}).get("status") == "ok"
            ),
            "gold_bundle_case_count": len(gold_pairs),
            "gold_bundle_equivalence_passed_case_count": gold_passed,
            "gold_bundle_equivalence_pass_rate": _ratio(
                gold_passed, len(gold_pairs)
            ),
            "refusal_case_count": len(refusal_pairs),
            "refusal_passed_case_count": refusal_passed,
            "refusal_recall": _ratio(refusal_passed, len(refusal_pairs)),
            "source_subquery_count": len(subplans),
            "source_semantic_plan_validated_count": sum(
                item.get("semantic_plan_status") == "planned" for item in subplans
            ),
            "llm_invocation_count": sum(
                item.get("llm_invoked") is True for item in subplans
            ),
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
            },
            "by_language": by_language,
            "infrastructure_failure_case_count": sum(
                1
                for item in case_reports
                if item.get("error")
                or (item.get("observed") or {}).get("status") == "error"
            ),
        },
        "source_rows_persisted": False,
        "limitations": [
            f"Only {reviewed_contract_count} reviewed independent aggregate "
            "contracts are evaluated.",
            "Arbitrary cross-source joins, row-level matching, and spatial linkage are rejected.",
            "Arabic labels and source categorical values remain subject to customer review.",
        ],
        "evaluation_integrity": benchmark.get("evaluation_integrity") or {},
        "cases": case_reports,
    }


def _load_environment() -> None:
    configured = os.environ.get("GDA_OPERATOR_ENV_FILE")
    env_path = Path(configured) if configured else Path(__file__).with_name(".env")
    if env_path.exists():
        load_dotenv(env_path, override=False)
    secret_path = Path(__file__).with_name(".vsource-secret.env")
    if secret_path.exists():
        load_dotenv(secret_path, override=False)
    if os.environ.get("GDA_DISABLE_LLM_PROXY", "").casefold() in {"1", "true", "yes"}:
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            os.environ.pop(name, None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gda-federated-nl2sql-eval",
        description="Evaluate reviewed Liveability + Makani cross-source contracts.",
    )
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--semantic-layer", type=Path, default=FEDERATED_SEMANTIC_PATH)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--model", default="gpt-5.1")
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--request-interval-seconds", type=float)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_environment()
    args = _parser().parse_args(argv)
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be positive")
    try:
        report = asyncio.run(
            run_federated_benchmark(
                benchmark_path=args.benchmark,
                semantic_layer_path=args.semantic_layer,
                owner=args.owner,
                model_name=args.model,
                reasoning_effort=args.reasoning_effort,
                timeout_seconds=args.timeout_seconds,
                case_ids=tuple(args.case_id),
                request_interval_seconds=args.request_interval_seconds,
            )
        )
    except Exception as exc:
        report = {
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "error",
            "stage": "benchmark_preflight",
            "message": _redact_error(exc),
        }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output = {
            "status": report.get("status"),
            "output": str(args.output),
            "metrics": report.get("metrics"),
        }
    else:
        output = report
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "passed" else 1


__all__ = [
    "BENCHMARK_SCHEMA",
    "GOLD_SCHEMA",
    "REPORT_SCHEMA",
    "FederatedBenchmarkConfigurationError",
    "run_federated_benchmark",
]


if __name__ == "__main__":
    raise SystemExit(main())
