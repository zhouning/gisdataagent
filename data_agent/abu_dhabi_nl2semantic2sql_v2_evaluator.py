"""Private-Gold evaluator for the public Abu Dhabi NL2Semantic2SQL v2 set.

The public benchmark intentionally declares business-language behaviour only.
This evaluator adds evaluation-only result contracts and expected dispositions
at run time.  Neither private Gold SQL nor benchmark cases are available to
the product request path, semantic-layer retrieval, or model prompt builder.
"""

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
from typing import Any, Literal

from .abu_dhabi_federated_nl2sql import (
    FEDERATED_SEMANTIC_PATH,
    AbuDhabiFederatedRequest,
    run_abu_dhabi_federated_request,
)
from .abu_dhabi_artifact_registry import current_artifact_path
from .api.abu_dhabi_nl2sql_product_routes import _execution_admission, _run_scope
from .governed_virtual_nl2sql import detect_question_language

PUBLIC_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-benchmark.v2"
PRIVATE_GOLD_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-private-gold.v1"
REPORT_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-report.v1"
EXECUTION_PROFILES = frozenset({"baseline_sql", "semantic_ir_experimental"})

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_MODULES = (
    _ROOT / "data_agent/governed_virtual_nl2sql.py",
    _ROOT / "data_agent/liveability_nl2sql.py",
    _ROOT / "data_agent/makani_nl2sql.py",
    _ROOT / "data_agent/abu_dhabi_federated_nl2sql.py",
    _ROOT / "data_agent/api/abu_dhabi_nl2sql_product_routes.py",
)
_DISALLOWED_RUNTIME_MARKERS = (
    "abu_dhabi_nl2semantic2sql_v2_private_gold",
    "L2_L01",
    "L2_M01",
    "L2_F01",
)


class V2EvaluationConfigurationError(ValueError):
    """The public benchmark, private Gold, or evaluation isolation is invalid."""


def _load(path: Path, expected_schema: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V2EvaluationConfigurationError(f"artifact_unreadable:{path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != expected_schema:
        raise V2EvaluationConfigurationError(f"artifact_schema_invalid:{path}")
    return payload


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_stems() -> dict[str, str]:
    return {
        "liveability": "liveability_data_20260730",
        "makani": "makani_sync_full",
    }


def _semantic_configuration() -> dict[str, dict[str, Any]]:
    configuration: dict[str, dict[str, Any]] = {}
    # Resolve the same checksum-verified current bundle aliases used by the
    # product request path.  The evaluator must never silently fall back to a
    # historical v3 layer after a source discovery drift, otherwise a paired
    # result can be marked wrong solely because the evaluator and runtime read
    # different semantic configurations.
    for source in ("liveability", "makani"):
        path = current_artifact_path(source, "semantic")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise V2EvaluationConfigurationError(f"semantic_layer_unreadable:{source}") from exc
        if not isinstance(payload, dict):
            raise V2EvaluationConfigurationError(f"semantic_layer_invalid:{source}")
        configuration[source] = {
            "path": str(path.relative_to(_ROOT)),
            "sha256": _sha256_bytes(path),
            "semantic_version": payload.get("semantic_version"),
            "metric_contract_version": payload.get("metric_contract_version"),
        }
    return configuration


def _validate_runtime_isolation(public: dict[str, Any], public_path: Path) -> None:
    # The customer console is deliberately allowed to read the *public*
    # benchmark for transparent UI evidence. What must never cross into a
    # request path is private Gold, case identifiers, or full question text.
    # Therefore the public artifact path is not itself a leakage marker.
    public_text = public_path.read_text(encoding="utf-8")
    questions = [str(case.get("question") or "") for case in public.get("cases") or []]
    for path in _RUNTIME_MODULES:
        text = path.read_text(encoding="utf-8")
        lowered = text.casefold()
        for marker in _DISALLOWED_RUNTIME_MARKERS:
            if marker.casefold() in lowered:
                raise V2EvaluationConfigurationError(f"runtime_benchmark_leak:{path.name}:{marker}")
        for question in questions:
            if len(question) >= 20 and question.casefold() in lowered:
                raise V2EvaluationConfigurationError(f"runtime_question_leak:{path.name}")
    if re.search(r'"canonical_sql_template"\s*:', public_text) or re.search(
        r'"gold_result"\s*:', public_text, flags=re.IGNORECASE
    ):
        raise V2EvaluationConfigurationError("public_benchmark_contains_private_gold")


def _validate_private_gold(
    public: dict[str, Any],
    gold: dict[str, Any],
    *,
    public_path: Path,
    gold_path: Path,
) -> dict[str, dict[str, Any]]:
    binding = gold.get("public_benchmark") or {}
    if binding.get("path") != str(public_path.relative_to(_ROOT)):
        raise V2EvaluationConfigurationError("private_gold_public_path_mismatch")
    if binding.get("sha256") != _sha256_bytes(public_path):
        raise V2EvaluationConfigurationError("private_gold_public_checksum_mismatch")
    if gold.get("runtime_access") != {
        "available_to_product_runtime": False,
        "available_to_prompt_or_retrieval": False,
        "contains_source_rows": False,
    }:
        raise V2EvaluationConfigurationError("private_gold_runtime_isolation_invalid")
    cases = {str(case.get("case_id") or ""): case for case in public.get("cases") or []}
    if not cases or "" in cases:
        raise V2EvaluationConfigurationError("public_case_ids_invalid")
    items = gold.get("cases") or []
    private = {str(item.get("case_id") or ""): item for item in items if isinstance(item, dict)}
    if set(private) != set(cases) or "" in private or len(private) != len(items):
        raise V2EvaluationConfigurationError("private_gold_case_set_mismatch")
    for case_id, case in cases.items():
        item = private[case_id]
        if item.get("outcome") != (case.get("expected") or {}).get("outcome"):
            raise V2EvaluationConfigurationError(f"private_gold_outcome_mismatch:{case_id}")
        if item.get("outcome") == "execute":
            scope = str(case.get("source_scope") or "")
            if scope not in {"liveability", "makani", "federated"}:
                raise V2EvaluationConfigurationError(f"private_gold_scope_invalid:{case_id}")
            if scope == "federated":
                expected = item.get("expected_bundle") or {}
                if len(str(expected.get("bundle_fingerprint") or "")) != 64:
                    raise V2EvaluationConfigurationError(f"private_gold_bundle_missing:{case_id}")
            else:
                expected = item.get("expected_result") or {}
                if not isinstance(expected.get("row_count"), int):
                    raise V2EvaluationConfigurationError(
                        f"private_gold_row_count_missing:{case_id}"
                    )
                fingerprints = expected.get("equivalence_fingerprints") or {}
                if (
                    len(str(fingerprints.get("unordered_position_numeric6_fingerprint") or ""))
                    != 64
                ):
                    raise V2EvaluationConfigurationError(
                        f"private_gold_fingerprint_missing:{case_id}"
                    )
    if gold_path.is_relative_to(_ROOT / "benchmarks"):
        raise V2EvaluationConfigurationError(
            "private_gold_must_not_be_stored_under_public_benchmarks"
        )
    return private


def _source_for_scope(scope: str, public: dict[str, Any]) -> dict[str, Any]:
    source = (public.get("source_scopes") or {}).get(scope) or {}
    if scope not in {"liveability", "makani"}:
        raise V2EvaluationConfigurationError(f"single_source_scope_required:{scope}")
    if int(source.get("source_id") or 0) <= 0:
        raise V2EvaluationConfigurationError(f"source_id_missing:{scope}")
    return source


def _single_source_result_equivalent(observed: dict[str, Any], gold: dict[str, Any]) -> bool:
    result = observed.get("result") or {}
    expected = gold.get("expected_result") or {}
    return int(result.get("row_count") or -1) == int(expected.get("row_count") or -2) and (
        result.get("equivalence_fingerprints") or {}
    ).get("unordered_position_numeric6_fingerprint") == (
        expected.get("equivalence_fingerprints") or {}
    ).get("unordered_position_numeric6_fingerprint")


def _federated_result_equivalent(observed: dict[str, Any], gold: dict[str, Any]) -> bool:
    result = observed.get("result") or {}
    expected = gold.get("expected_bundle") or {}
    return result.get("bundle_fingerprint") == expected.get("bundle_fingerprint")


def _all_validation_checks_pass(plan: dict[str, Any]) -> bool:
    validation = plan.get("validation") or {}
    checks = list(validation.get("checks") or [])
    return (
        validation.get("valid") is True
        and bool(checks)
        and all(check.get("passed") is True for check in checks)
    )


def _route_evidence_valid(
    observed: dict[str, Any],
    *,
    scope: str,
    expected_outcome: str,
    execution_profile: Literal["baseline_sql", "semantic_ir_experimental"],
) -> bool:
    planner = observed.get("planner") or {}
    if expected_outcome != "execute":
        return (
            observed.get("status") == "rejected"
            and planner.get("llm_invoked") is False
            and not (observed.get("query") or {}).get("sql")
            and not (observed.get("result") or {}).get("data")
        )

    plan = (
        observed.get("semantic_plan")
        if scope == "federated"
        else (observed.get("query") or {}).get("semantic_plan")
    ) or {}
    physical = plan.get("physical_plan") or {}
    fingerprints = plan.get("fingerprints") or {}
    common_plan_evidence = (
        observed.get("status") == "ok"
        and plan.get("status") == "planned"
        and _all_validation_checks_pass(plan)
        and bool(plan.get("logical_plan"))
        and physical.get("read_only") is True
        and len(str(fingerprints.get("semantic_ir_sha256") or "")) == 64
        and len(str(fingerprints.get("logical_plan_sha256") or "")) == 64
        and len(str(fingerprints.get("physical_plan_sha256") or "")) == 64
    )
    if not common_plan_evidence:
        return False

    route = str(planner.get("route") or "")
    if scope == "federated":
        semantic_ir = plan.get("semantic_ir") or {}
        return (
            route == "reviewed_federated_metric_contract"
            and semantic_ir.get("cross_database_sql") is False
            and semantic_ir.get("cross_source_join") is False
            and physical.get("cross_database_sql") is False
            and physical.get("cross_source_join") is False
        )

    query = observed.get("query") or {}
    static = observed.get("static_validation") or {}
    sql_evidence = (
        bool(query.get("sql"))
        and len(str(query.get("sql_sha256") or "")) == 64
        and static.get("single_read_statement") is True
        and static.get("schema_whitelist") is True
        and static.get("semantic_table_and_field_whitelist") is True
        and static.get("declared_relationships_only") is True
        and static.get("raw_geometry_projection_blocked") is True
        and int(static.get("bounded_max_rows") or 0) > 0
    )
    if not sql_evidence:
        return False

    compilation_mode = str(physical.get("compilation_mode") or "")
    if route == "deterministic_reviewed_metric_contract":
        return (
            plan.get("execution_authority") is True
            and compilation_mode == "reviewed_contract_compiler"
        )
    if execution_profile == "baseline_sql":
        # The baseline remains the production route.  It may either retain
        # the model's validated SQL AST shadow compilation or apply a
        # matching reviewed metric contract as a normalization step.  The
        # latter is still observational for baseline (execution authority is
        # false); rejecting it would misclassify a valid, governed result as
        # a route error.
        baseline_compilation_modes = {
            "validated_sql_ast_shadow",
            "reviewed_contract_shadow",
        }
        return (
            route == "governed_free_form_llm"
            and plan.get("execution_authority") is False
            and compilation_mode in baseline_compilation_modes
        )
    return (
        route == "semantic_ir_experimental_llm"
        and plan.get("execution_authority") is True
        and compilation_mode == "compiled_semantic_ir_experimental"
    )


def _semantic_spec_match(case: dict[str, Any], observed: dict[str, Any]) -> bool:
    """Compare free-form plan semantics to the public business oracle."""
    route = str((observed.get("planner") or {}).get("route") or "")
    if route not in {"governed_free_form_llm", "semantic_ir_experimental_llm"}:
        # Reviewed metric contracts and federation are shared controls whose
        # independently governed contracts are validated by route evidence.
        return True
    expected = case.get("expected") or {}
    plan = (observed.get("query") or {}).get("semantic_plan") or {}
    semantic_ir = plan.get("semantic_ir") or {}
    projections = list(semantic_ir.get("projections") or [])

    actual_dimensions: set[str] = set()
    actual_measures: list[tuple[str, str | None]] = []
    for projection in projections:
        field_ref = projection.get("field_ref") or {}
        fields = [str(field_ref.get("semantic_field") or "")]
        fields.extend(
            str(item.get("field") or "")
            for item in projection.get("source_fields") or []
            if isinstance(item, dict)
        )
        fields = [field.casefold() for field in fields if field]
        if projection.get("role") == "dimension":
            actual_dimensions.update(fields)
        if projection.get("role") == "metric":
            operation = str(projection.get("aggregate") or "").casefold()
            actual_measures.append((operation, fields[0] if fields else None))

    expected_dimensions = {str(value).casefold() for value in expected.get("dimensions") or []}
    if not expected_dimensions.issubset(actual_dimensions):
        return False

    operation_aliases = {"average": "avg"}
    for measure in expected.get("measures") or []:
        operation = operation_aliases.get(
            str(measure.get("operation") or "").casefold(),
            str(measure.get("operation") or "").casefold(),
        )
        field = str(measure.get("semantic_field") or "").casefold()
        matched = any(
            actual_operation == operation
            and (actual_field == field or (operation == "count" and actual_field is None))
            for actual_operation, actual_field in actual_measures
        )
        if not matched:
            return False

    expected_relationships = list(expected.get("relationships") or [])
    actual_joins = list(semantic_ir.get("joins") or [])
    return len(actual_joins) >= len(expected_relationships)


def _observation_evidence(report: dict[str, Any]) -> dict[str, Any]:
    query = report.get("query") or {}
    result = report.get("result") or {}
    generation = report.get("generation") or {}
    return {
        "status": report.get("status"),
        "outcome": report.get("outcome"),
        "reason": report.get("reason"),
        "planner_route": (report.get("planner") or {}).get("route"),
        "llm_invoked": (report.get("planner") or {}).get("llm_invoked"),
        "semantic_plan": query.get("semantic_plan") or report.get("semantic_plan"),
        "semantic_metric_contract": query.get("semantic_metric_contract"),
        "query_evidence": {
            "sql_sha256": query.get("sql_sha256"),
            "tables": list(query.get("tables") or []),
            "columns": list(query.get("columns") or []),
        },
        "static_validation": report.get("static_validation") or {},
        "result": {
            "row_count": result.get("row_count"),
            "result_fingerprint": result.get("result_fingerprint"),
            "equivalence_fingerprints": result.get("equivalence_fingerprints") or {},
            "bundle_fingerprint": result.get("bundle_fingerprint"),
        },
        "generation": {
            "latency_ms": generation.get("latency_ms"),
            "usage": generation.get("usage") or {},
            "observed_model_versions": list(generation.get("observed_model_versions") or []),
        },
        "source_rows_persisted": report.get("source_rows_persisted") is True,
        "error": report.get("error"),
    }


async def _run_case(
    case: dict[str, Any],
    gold: dict[str, Any],
    public: dict[str, Any],
    *,
    owner: str,
    execution_profile: Literal["baseline_sql", "semantic_ir_experimental"],
    timeout_seconds: int,
) -> dict[str, Any]:
    scope = str(case.get("source_scope") or "")
    expected_outcome = str((case.get("expected") or {}).get("outcome") or "")
    question = str(case.get("question") or "")
    language = str(case.get("language") or "")
    if detect_question_language(question) != language:
        raise V2EvaluationConfigurationError(f"language_drift:{case.get('case_id')}")

    try:
        admission = _execution_admission(scope, question)
        if not admission.get("runtime_admitted"):
            observed = {
                "status": "rejected",
                "outcome": admission.get("disposition", "clarify"),
                "reason": admission.get("decision"),
                "planner": {"route": "semantic_candidate_admission", "llm_invoked": False},
                "source_rows_persisted": False,
            }
        elif scope == "federated":
            # Federation is deterministic reviewed-contract control rather
            # than a second SQL compiler. It is included as shared policy
            # evidence and excluded by the pairwise comparator from route deltas.
            observed = await run_abu_dhabi_federated_request(
                AbuDhabiFederatedRequest(question, language, True),
                semantic_layer_path=FEDERATED_SEMANTIC_PATH,
                owner=owner,
                timeout_seconds=timeout_seconds,
                verify_platform_schema=False,
            )
        else:
            observed = await _run_scope(
                scope,
                question,
                execution_profile=execution_profile,
                verify_platform_schema=False,
            )
    except Exception as exc:
        # A suite must yield diagnosable evidence for every case. Do not emit
        # exception text here: connector errors may contain endpoint details,
        # while the type is enough to classify a product/runtime failure.
        observed = {
            "status": "error",
            "outcome": "error",
            "reason": "evaluation_runtime_exception",
            "planner": {"route": "evaluation_runtime_exception", "llm_invoked": False},
            "source_rows_persisted": False,
            "error": type(exc).__name__,
        }

    observed_outcome = (
        "execute" if observed.get("status") == "ok" else str(observed.get("outcome") or "clarify")
    )
    checks = {
        "outcome_match": observed_outcome == expected_outcome,
        "source_rows_not_persisted": observed.get("source_rows_persisted") is False,
        "route_evidence_valid": _route_evidence_valid(
            observed,
            scope=scope,
            expected_outcome=expected_outcome,
            execution_profile=execution_profile,
        ),
    }
    if expected_outcome == "execute":
        checks["result_equivalent"] = (
            _federated_result_equivalent(observed, gold)
            if scope == "federated"
            else _single_source_result_equivalent(observed, gold)
        )
        checks["semantic_spec_match"] = _semantic_spec_match(case, observed)
    passed = all(checks.values())
    return {
        "case_id": case.get("case_id"),
        "scope": scope,
        "language": language,
        "split": case.get("split"),
        "family": case.get("family"),
        "expected_outcome": expected_outcome,
        "status": "passed" if passed else "failed",
        "checks": checks,
        "observed": _observation_evidence(observed),
        "failure_reasons": sorted(name for name, value in checks.items() if not value),
    }


def _metric(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(case_reports)
    passed = sum(item["status"] == "passed" for item in case_reports)
    execute = [item for item in case_reports if item["expected_outcome"] == "execute"]
    clarify = [item for item in case_reports if item["expected_outcome"] == "clarify"]
    refuse = [item for item in case_reports if item["expected_outcome"] == "refuse"]
    generation = [item["observed"]["generation"] for item in case_reports]
    latencies = [
        float(item["latency_ms"])
        for item in generation
        if isinstance(item.get("latency_ms"), (int, float))
    ]
    return {
        "case_count": total,
        "passed_case_count": passed,
        "case_pass_rate": passed / total if total else None,
        "execute_case_count": len(execute),
        "execute_passed_case_count": sum(item["status"] == "passed" for item in execute),
        "execute_pass_rate": sum(item["status"] == "passed" for item in execute) / len(execute)
        if execute
        else None,
        "clarify_case_count": len(clarify),
        "clarify_passed_case_count": sum(item["status"] == "passed" for item in clarify),
        "refuse_case_count": len(refuse),
        "refuse_passed_case_count": sum(item["status"] == "passed" for item in refuse),
        "result_contract_case_count": len(execute),
        "result_contract_passed_case_count": sum(
            item["checks"].get("result_equivalent") is True for item in execute
        ),
        "route_evidence_passed_case_count": sum(
            item["checks"].get("route_evidence_valid") is True for item in case_reports
        ),
        "semantic_spec_case_count": len(execute),
        "semantic_spec_passed_case_count": sum(
            item["checks"].get("semantic_spec_match") is True for item in execute
        ),
        "mean_generation_latency_ms": round(sum(latencies) / len(latencies), 3)
        if latencies
        else None,
        "planner_route_counts": dict(
            sorted(
                Counter(
                    str(item["observed"].get("planner_route") or "unknown") for item in case_reports
                ).items()
            )
        ),
        "failure_class_counts": dict(
            sorted(
                Counter(
                    reason for item in case_reports for reason in item.get("failure_reasons") or []
                ).items()
            )
        ),
    }


async def run_v2_evaluation(
    *,
    public_benchmark_path: Path,
    private_gold_path: Path,
    owner: str,
    execution_profile: Literal["baseline_sql", "semantic_ir_experimental"] = "baseline_sql",
    timeout_seconds: int = 180,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    if execution_profile not in EXECUTION_PROFILES:
        raise V2EvaluationConfigurationError("execution_profile_invalid")
    public = _load(public_benchmark_path, PUBLIC_SCHEMA)
    private_gold = _load(private_gold_path, PRIVATE_GOLD_SCHEMA)
    _validate_runtime_isolation(public, public_benchmark_path)
    gold_by_case = _validate_private_gold(
        public,
        private_gold,
        public_path=public_benchmark_path,
        gold_path=private_gold_path,
    )
    cases = list(public.get("cases") or [])
    if case_ids is not None:
        unknown = case_ids - {str(case.get("case_id") or "") for case in cases}
        if unknown:
            raise V2EvaluationConfigurationError("unknown_case_ids:" + ",".join(sorted(unknown)))
        cases = [case for case in cases if str(case.get("case_id") or "") in case_ids]
    if not cases:
        raise V2EvaluationConfigurationError("no_cases_selected")

    reports = []
    for case in cases:
        reports.append(
            await _run_case(
                case,
                gold_by_case[str(case["case_id"])],
                public,
                owner=owner,
                execution_profile=execution_profile,
                timeout_seconds=timeout_seconds,
            )
        )
    return {
        "schema": REPORT_SCHEMA,
        "status": "passed" if all(item["status"] == "passed" for item in reports) else "failed",
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluation_scope": "private_gold_governed_product_evaluation",
        "execution_profile": execution_profile,
        "public_benchmark": {
            "path": str(public_benchmark_path.relative_to(_ROOT)),
            "sha256": _sha256_bytes(public_benchmark_path),
            "benchmark_id": public.get("benchmark_id"),
            "version": public.get("version"),
            "selected_case_ids": [str(case["case_id"]) for case in cases],
        },
        "private_gold": {
            "contract_id": private_gold.get("contract_id"),
            "sha256": _sha256_bytes(private_gold_path),
            "runtime_accessible": False,
        },
        "semantic_configuration": _semantic_configuration(),
        "runtime_isolation": {
            "runtime_module_scan_passed": True,
            "questions_loaded_only_by_evaluator": True,
            "gold_loaded_only_by_evaluator": True,
            "source_rows_persisted": False,
            "platform_schema_gate": "isolated_evaluator_bypass",
            "product_runtime_platform_schema_gate_unchanged": True,
        },
        "metrics": _metric(reports),
        "cases": reports,
        "limitations": [
            (
                "A report is valid only for the selected frozen public benchmark "
                "and matching private Gold checksum."
            ),
            (
                "Federated cases test independent source aggregates and "
                "application-level presentation; they do not authorize "
                "cross-database SQL or joins."
            ),
            (
                "The SemanticQueryIR profile is an isolated candidate route and "
                "cannot become production solely from this report."
            ),
        ],
    }


def _load_environment() -> None:
    from dotenv import load_dotenv

    default_env_path = _ROOT / "data_agent/.env"
    operator_env_path = Path(os.environ.get("GDA_OPERATOR_ENV_FILE", default_env_path))
    for env_path in dict.fromkeys((default_env_path, operator_env_path)):
        if env_path.exists():
            load_dotenv(env_path, override=False)
    secret_path = _ROOT / "data_agent/.vsource-secret.env"
    if secret_path.exists():
        load_dotenv(secret_path, override=False)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(name, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--private-gold", type=Path, required=True)
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    parser.add_argument(
        "--execution-profile", choices=sorted(EXECUTION_PROFILES), default="baseline_sql"
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    _load_environment()
    report = asyncio.run(
        run_v2_evaluation(
            public_benchmark_path=args.benchmark.resolve(),
            private_gold_path=args.private_gold.resolve(),
            owner=args.owner,
            execution_profile=args.execution_profile,
            timeout_seconds=args.timeout_seconds,
            case_ids=set(args.case_id) or None,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"status": report["status"], "metrics": report["metrics"]}, ensure_ascii=False)
    )
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
