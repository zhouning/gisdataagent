"""Authenticated read model and execution boundary for Abu Dhabi NL2Semantic2SQL.

The product console deliberately reads only source metadata, reviewed semantic
artifacts, and benchmark summaries.  Benchmark Gold SQL/result contracts are
evaluation-only and are never returned here or passed to a query runtime.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.abu_dhabi_nl2sql_product")

_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_ROOT = _ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
_FULL_SEMANTIC_READINESS_PATH = _ARTIFACT_ROOT / "abu_dhabi_full_semantic_readiness_report.json"
_BENCHMARK_ROOT = _ROOT / "benchmarks/abu_dhabi_nl2sql_product_v1"
_BENCHMARK_V2_PATH = _ROOT / (
    "benchmarks/abu_dhabi_nl2semantic2sql_v2/abu_dhabi_nl2semantic2sql_benchmark_v2.json"
)
_BENCHMARK_V2_SELECTION_REPORT_PATH = _ROOT / (
    "benchmarks/abu_dhabi_nl2semantic2sql_v2/selection_report.json"
)
_BENCHMARK_V3_PATH = _ROOT / (
    "benchmarks/abu_dhabi_nl2semantic2sql_v3/abu_dhabi_nl2semantic2sql_benchmark_v3.json"
)
_BENCHMARK_V3_SELECTION_REPORT_PATH = _ROOT / (
    "benchmarks/abu_dhabi_nl2semantic2sql_v3/selection_report.json"
)
_BENCHMARK_V2_PUBLISHED_REPORT_MANIFEST_PATH = (
    _ROOT / "benchmarks/abu_dhabi_nl2semantic2sql_v2/published_report_manifest.json"
)
_PUBLISHED_REPORT_MANIFEST_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-published-report-manifest.v1"
_EVALUATION_REPORT_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-report.v1"
_PAIRWISE_REPORT_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-pairwise.v1"
_STABILITY_REPORT_SCHEMA = "gda.abu-dhabi-nl2semantic2sql-v2-stability.v1"
_MAX_QUESTION_LENGTH = 4_000
_DISPLAY_ROW_LIMIT = 100
_SEMANTIC_CONFIG_PAGE_LIMIT = 100
_SEMANTIC_CONFIG_MAX_PAGE_LIMIT = 500
_SEMANTIC_CONFIGURATION_SECTIONS: tuple[str, ...] = (
    "summary",
    "source_binding",
    "activation_gate",
    "query_policy",
    "response_language_policy",
    "ontology_overlay",
    "technical_catalog",
    "dictionary_semantic_publication",
    "dictionary_evidence",
    "semantic_candidate_catalog",
    "relationship_candidate_catalog",
    "business_semantic_rules",
    "semantic_caveats",
    "table_bindings",
    "semantic_assets",
    "relationships",
    "metric_contracts",
    "all",
)
_QUESTION_CAPABILITY_REQUIREMENTS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "prediction",
        ("预测", "预计", "未来", "forecast", "predict", "projection"),
        (),
    ),
    (
        "consumption_measure",
        (
            "能源",
            "能耗",
            "消耗",
            "用量",
            "电量",
            "用电",
            "用水",
            "energy",
            "consumption",
            "electricity",
        ),
        ("sum",),
    ),
    (
        "network_distance",
        ("道路距离", "通勤时间", "最近", "nearest", "road distance", "commute time"),
        ("nearest", "network_distance"),
    ),
    (
        "coverage_measure",
        ("服务覆盖", "覆盖人口", "覆盖率", "service coverage", "coverage population"),
        ("coverage",),
    ),
)

_SOURCE_SPECS: tuple[dict[str, str | int], ...] = (
    {
        "key": "liveability",
        "label": "Liveability",
        "source_id": 12,
        "semantic": "liveability_data_20260730_semantic_layer_v4_full_coverage.json",
        "ontology": "liveability_data_20260730_ontology_v4_full_coverage.json",
        "catalog": "liveability_data_20260730_technical_semantic_catalog_v3.json",
        "candidates": "liveability_data_20260730_semantic_candidate_catalog_v1.json",
        "relationships": "liveability_data_20260730_relationship_candidate_catalog_v1.json",
        "benchmark": "liveability_product_benchmark_v1.json",
        "report": "gpt_5_1_liveability_product_v1_selective_direct_stability_report.json",
        "release_scorecard": "liveability_nl2sql_release_scorecard_20260825.json",
        "coverage_plan": "liveability_nl2sql_coverage_plan_20260825.json",
        "technical_candidates": "liveability_technical_nl2sql_benchmark_candidates_20260826.json",
        "dictionary_evidence": "liveability_dictionary_evidence_current_20260826.json",
    },
    {
        "key": "makani",
        "label": "Makani",
        "source_id": 13,
        "semantic": "makani_sync_full_semantic_layer_v4_full_coverage.json",
        "ontology": "makani_sync_full_ontology_v4_full_coverage.json",
        "catalog": "makani_sync_full_technical_semantic_catalog_v3.json",
        "candidates": "makani_sync_full_semantic_candidate_catalog_v1.json",
        "relationships": "makani_sync_full_relationship_candidate_catalog_v1.json",
        "benchmark": "makani_product_benchmark_v1.json",
        "report": "makani_gemini37flash_failed4_rerun_20260826.json",
        "release_scorecard": "makani_nl2sql_release_scorecard_current_20260826.json",
        "coverage_plan": "makani_nl2sql_coverage_plan_20260825.json",
        "technical_candidates": "makani_technical_nl2sql_benchmark_candidates_20260826.json",
        "dictionary_evidence": "makani_dictionary_evidence_current_20260826.json",
    },
)

_FEDERATED_SPEC = {
    "key": "federated",
    "label": "Federated",
    "semantic": "abu_dhabi_federated_semantic_layer_v5.json",
    "benchmark": "abu_dhabi_federated_free_form_benchmark_v4.json",
    "report": "federated_product_v4_contract_ir_run.json",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact_object_required:{path.name}")
    return payload


def _public_artifact_value(value: Any) -> Any:
    """Remove workstation-specific absolute paths from customer-facing evidence."""

    if isinstance(value, dict):
        return {key: _public_artifact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_artifact_value(item) for item in value]
    if not isinstance(value, str) or not value.startswith("/"):
        return value

    path = Path(value)
    try:
        return path.relative_to(_ROOT).as_posix()
    except ValueError:
        pass
    normalized = value.replace("\\", "/")
    dictionary_marker = "/数据字典/"
    if dictionary_marker in normalized:
        return "customer_dictionary/" + normalized.split(dictionary_marker, 1)[1]
    return "external_artifact/" + path.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_published_artifact(descriptor: dict[str, Any], *, expected_schema: str) -> dict[str, Any]:
    relative_path = Path(str(descriptor.get("path") or ""))
    expected_sha = str(descriptor.get("sha256") or "")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("published_evaluation_path_invalid")
    path = (_ROOT / relative_path).resolve()
    try:
        path.relative_to(_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("published_evaluation_path_outside_repository") from exc
    if len(expected_sha) != 64 or _sha256(path) != expected_sha:
        raise ValueError(f"published_evaluation_checksum_mismatch:{relative_path.name}")
    payload = _load_json(path)
    if payload.get("schema") != expected_schema:
        raise ValueError(f"published_evaluation_schema_invalid:{relative_path.name}")
    return payload


def _route_evaluation_summary(report: dict[str, Any]) -> dict[str, Any]:
    public_benchmark = report.get("public_benchmark") or {}
    semantic_configuration = report.get("semantic_configuration") or {}
    metrics = report.get("metrics") or {}
    runtime_isolation = report.get("runtime_isolation") or {}
    private_gold = report.get("private_gold") or {}
    return {
        "status": report.get("status"),
        "generated_at": report.get("generated_at"),
        "execution_profile": report.get("execution_profile"),
        "evaluation_scope": report.get("evaluation_scope"),
        "public_benchmark": {
            "benchmark_id": public_benchmark.get("benchmark_id"),
            "version": public_benchmark.get("version"),
            "sha256": public_benchmark.get("sha256"),
            "selected_case_count": len(public_benchmark.get("selected_case_ids") or []),
        },
        "semantic_configuration": {
            source: {
                "path": configuration.get("path"),
                "sha256": configuration.get("sha256"),
                "semantic_version": configuration.get("semantic_version"),
                "metric_contract_version": configuration.get("metric_contract_version"),
            }
            for source, configuration in sorted(semantic_configuration.items())
            if isinstance(configuration, dict)
        },
        "metrics": {
            key: metrics.get(key)
            for key in (
                "case_count",
                "passed_case_count",
                "case_pass_rate",
                "execute_case_count",
                "execute_passed_case_count",
                "execute_pass_rate",
                "clarify_case_count",
                "clarify_passed_case_count",
                "refuse_case_count",
                "refuse_passed_case_count",
                "result_contract_case_count",
                "result_contract_passed_case_count",
                "mean_generation_latency_ms",
                "planner_route_counts",
                "failure_class_counts",
            )
        },
        "runtime_isolation": {
            "runtime_module_scan_passed": runtime_isolation.get("runtime_module_scan_passed"),
            "questions_loaded_only_by_evaluator": runtime_isolation.get(
                "questions_loaded_only_by_evaluator"
            ),
            "gold_loaded_only_by_evaluator": runtime_isolation.get("gold_loaded_only_by_evaluator"),
            "source_rows_persisted": runtime_isolation.get("source_rows_persisted"),
            "private_gold_runtime_accessible": private_gold.get("runtime_accessible"),
        },
        "limitations": list(report.get("limitations") or []),
    }


def _pairwise_evaluation_summary(report: dict[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics") or {}
    all_cases = metrics.get("all_cases") or {}
    route_comparison = metrics.get("route_comparison") or {}
    route_case_count = int(route_comparison.get("case_count") or 0)
    all_case_count = int(all_cases.get("case_count") or 0)
    pass_rate_delta = route_comparison.get("candidate_minus_baseline_pass_rate")
    promotion = report.get("candidate_promotion_assessment") or {}
    if pass_rate_delta == 0:
        accuracy_conclusion = "tied_on_current_paired_run"
    elif isinstance(pass_rate_delta, (int, float)) and pass_rate_delta > 0:
        accuracy_conclusion = "candidate_higher_on_current_paired_run"
    else:
        accuracy_conclusion = "baseline_higher_on_current_paired_run"
    return {
        "status": report.get("status"),
        "comparison_role": report.get("comparison_role"),
        "paired_configuration_verified": report.get("paired_configuration_verified"),
        "metrics": {
            "all_cases": all_cases,
            "route_comparison": route_comparison,
            "by_category": metrics.get("by_category") or {},
        },
        "interpretation": {
            "accuracy_conclusion": accuracy_conclusion,
            "route_comparison_case_count": route_case_count,
            "shared_control_case_count": max(all_case_count - route_case_count, 0),
            "promotion_supported": promotion.get("promotion_supported") is True,
            "promotion_reason": promotion.get("reason"),
            "repeated_stability_evidence_required": True,
        },
        "limitations": list(report.get("limitations") or []),
    }


def _published_evaluation_summary(
    manifest_path: Path = _BENCHMARK_V2_PUBLISHED_REPORT_MANIFEST_PATH,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    if manifest.get("schema") != _PUBLISHED_REPORT_MANIFEST_SCHEMA:
        raise ValueError("published_evaluation_manifest_schema_invalid")
    reports = manifest.get("reports") or {}
    baseline = _load_published_artifact(
        reports.get("baseline_sql") or {}, expected_schema=_EVALUATION_REPORT_SCHEMA
    )
    candidate = _load_published_artifact(
        reports.get("semantic_ir_experimental") or {},
        expected_schema=_EVALUATION_REPORT_SCHEMA,
    )
    pairwise = _load_published_artifact(
        reports.get("pairwise") or {}, expected_schema=_PAIRWISE_REPORT_SCHEMA
    )
    stability = _load_published_artifact(
        reports.get("stability") or {}, expected_schema=_STABILITY_REPORT_SCHEMA
    )
    if baseline.get("execution_profile") != "baseline_sql":
        raise ValueError("published_baseline_profile_invalid")
    if candidate.get("execution_profile") != "semantic_ir_experimental":
        raise ValueError("published_candidate_profile_invalid")
    if not pairwise.get("paired_configuration_verified"):
        raise ValueError("published_pairwise_configuration_unverified")
    for key in (
        "public_benchmark",
        "private_gold",
        "semantic_configuration",
        "runtime_isolation",
    ):
        if baseline.get(key) != candidate.get(key):
            raise ValueError(f"published_pair_configuration_mismatch:{key}")
    public_benchmark = baseline.get("public_benchmark") or {}
    stability_benchmark = stability.get("benchmark") or {}
    if stability_benchmark.get("sha256") != public_benchmark.get("sha256"):
        raise ValueError("published_stability_benchmark_mismatch")
    semantic_configuration = baseline.get("semantic_configuration") or {}
    stability_semantic = stability.get("semantic_configuration") or {}
    if any(
        (stability_semantic.get(source) or {}).get("sha256") != (configuration or {}).get("sha256")
        for source, configuration in semantic_configuration.items()
    ):
        raise ValueError("published_stability_semantic_configuration_mismatch")
    return {
        "release_id": manifest.get("release_id"),
        "published_at": manifest.get("published_at"),
        "publication_policy": manifest.get("publication_policy") or {},
        "routes": {
            "baseline_sql": _route_evaluation_summary(baseline),
            "semantic_ir_experimental": _route_evaluation_summary(candidate),
        },
        "pairwise": _pairwise_evaluation_summary(pairwise),
        "stability": {
            "status": stability.get("status"),
            "benchmark": stability_benchmark,
            "semantic_configuration": stability_semantic,
            "configuration_audit": stability.get("configuration_audit") or {},
            "metrics": stability.get("metrics") or {},
            "runs": list(stability.get("runs") or []),
            "unstable_route_cases": list(stability.get("unstable_route_cases") or []),
            "promotion_assessment": stability.get("promotion_assessment") or {},
            "limitations": list(stability.get("limitations") or []),
        },
    }


def _load_source_artifacts(spec: dict[str, str | int]) -> dict[str, dict[str, Any]]:
    current_paths: dict[str, Path] = {}
    if spec.get("key") in {"liveability", "makani"}:
        try:
            from ..abu_dhabi_artifact_registry import current_artifact_path

            for role in (
                "semantic",
                "ontology",
                "catalog",
                "candidates",
                "relationships",
                "technical_candidates",
                "release_scorecard",
                "coverage_plan",
                "benchmark",
                "report",
                "technical_coverage",
                "business_semantic_task_queue",
                "business_benchmark_task_queue",
                "technical_freeze_state",
                "dictionary_evidence",
            ):
                registry_role = {
                    "semantic": "semantic",
                    "ontology": "ontology",
                    "catalog": "catalog",
                    "candidates": "semantic_candidates",
                    "relationships": "relationships",
                    "technical_candidates": "technical_candidates",
                    "release_scorecard": "release_scorecard",
                    "coverage_plan": "coverage_plan",
                    "benchmark": "benchmark",
                    "report": "report",
                    "technical_coverage": "technical_coverage",
                    "business_semantic_task_queue": "business_semantic_task_queue",
                    "business_benchmark_task_queue": "business_benchmark_task_queue",
                    "technical_freeze_state": "technical_freeze_state",
                    "dictionary_evidence": "dictionary_evidence",
                }[role]
                current_paths[role] = current_artifact_path(str(spec["key"]), registry_role)
        except (OSError, ValueError) as exc:
            logger.error("Current Abu Dhabi artifact bundle unavailable for %s: %s", spec.get("key"), exc)
            raise
    artifacts = {
        "semantic": _load_json(current_paths.get("semantic", _ARTIFACT_ROOT / str(spec["semantic"]))),
        "ontology": _load_json(current_paths.get("ontology", _ARTIFACT_ROOT / str(spec["ontology"]))),
        "catalog": _load_json(current_paths.get("catalog", _ARTIFACT_ROOT / str(spec["catalog"]))),
        "candidates": _load_json(current_paths.get("candidates", _ARTIFACT_ROOT / str(spec["candidates"]))),
        "relationships": _load_json(current_paths.get("relationships", _ARTIFACT_ROOT / str(spec["relationships"]))),
        "benchmark": _load_json(current_paths.get("benchmark", _BENCHMARK_ROOT / str(spec["benchmark"]))),
        "report": _load_json(current_paths.get("report", _BENCHMARK_ROOT / "reports" / str(spec["report"]))),
    }
    scorecard_path = current_paths.get("release_scorecard", _ARTIFACT_ROOT / str(spec.get("release_scorecard") or ""))
    coverage_plan_path = current_paths.get("coverage_plan", _ARTIFACT_ROOT / str(spec.get("coverage_plan") or ""))
    artifacts["scorecard"] = _load_json(scorecard_path) if scorecard_path.is_file() else {}
    artifacts["coverage_plan"] = _load_json(coverage_plan_path) if coverage_plan_path.is_file() else {}
    technical_candidates_path = current_paths.get("technical_candidates", _ARTIFACT_ROOT / str(spec.get("technical_candidates") or ""))
    artifacts["technical_candidates"] = (
        _load_json(technical_candidates_path)
        if technical_candidates_path.is_file()
        else {}
    )
    try:
        technical_coverage_path = current_paths.get("technical_coverage")
    except NameError:
        technical_coverage_path = None
    artifacts["technical_coverage"] = (
        _load_json(technical_coverage_path)
        if technical_coverage_path and technical_coverage_path.is_file()
        else {}
    )
    task_queue_path = current_paths.get("business_semantic_task_queue")
    artifacts["business_semantic_task_queue"] = (
        _load_json(task_queue_path)
        if task_queue_path and task_queue_path.is_file()
        else {}
    )
    benchmark_queue_path = current_paths.get("business_benchmark_task_queue")
    artifacts["business_benchmark_task_queue"] = (
        _load_json(benchmark_queue_path)
        if benchmark_queue_path and benchmark_queue_path.is_file()
        else {}
    )
    freeze_state_path = current_paths.get("technical_freeze_state")
    artifacts["technical_freeze_state"] = (
        _load_json(freeze_state_path)
        if freeze_state_path and freeze_state_path.is_file()
        else {}
    )
    dictionary_evidence_path = current_paths.get(
        "dictionary_evidence",
        _ARTIFACT_ROOT / str(spec.get("dictionary_evidence") or ""),
    )
    artifacts["dictionary_evidence"] = (
        _load_json(dictionary_evidence_path)
        if dictionary_evidence_path and dictionary_evidence_path.is_file()
        else {}
    )
    return artifacts


def _readiness_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Expose readiness evidence without duplicating the per-table inventory."""

    return {
        "status": report.get("status"),
        "semantic_coverage": report.get("semantic_coverage") or {},
        # Evaluation-only Gold contract counters are not part of the
        # customer-facing evidence surface.  Keep operational/readiness
        # metrics while applying the same recursive redaction policy used for
        # semantic configuration.
        "metrics": _redact_semantic_configuration(report.get("metrics") or {}),
        "relationships": report.get("relationships") or {},
        "benchmark": report.get("benchmark") or {},
        "capabilities": report.get("capabilities") or {},
        "unsupported_query_classes": list(report.get("unsupported_query_classes") or []),
        "release_gate": report.get("release_gate") or {},
        "errors": list(report.get("errors") or []),
    }


def _redact_semantic_configuration(value: Any) -> Any:
    """Return semantic configuration without evaluation or source-row payloads."""

    blocked_keys = {
        "gold",
        "gold_sql",
        "gold_result",
        "gold_result_contract",
        "source_rows",
        "source_rows_persisted",
    }
    if isinstance(value, dict):
        return {
            str(key): _redact_semantic_configuration(item)
            for key, item in value.items()
            if (
                str(key).casefold() not in blocked_keys
                and "gold_result_contract" not in str(key).casefold()
                and "gold_sql" not in str(key).casefold()
            )
        }
    if isinstance(value, list):
        return [_redact_semantic_configuration(item) for item in value]
    return _public_artifact_value(value)


def _semantic_configuration_view(
    scope: str,
    *,
    section: str = "summary",
    offset: int = 0,
    limit: int = _SEMANTIC_CONFIG_PAGE_LIMIT,
    search: str = "",
    include_candidates: bool = False,
) -> dict[str, Any]:
    """Expose the complete published semantic configuration as a paged read model.

    The existing product evidence endpoint intentionally returns summaries. This
    endpoint is an authenticated inspection surface for operators who need to
    inspect every binding, field, relationship, metric contract, and activation
    rule without granting execution authority or exposing benchmark Gold data.
    """

    if scope not in {"liveability", "makani"}:
        raise ValueError("semantic_configuration_scope_unsupported")
    if section not in _SEMANTIC_CONFIGURATION_SECTIONS:
        raise ValueError("semantic_configuration_section_unsupported")
    if offset < 0:
        raise ValueError("semantic_configuration_offset_invalid")
    if limit < 1 or limit > _SEMANTIC_CONFIG_MAX_PAGE_LIMIT:
        raise ValueError("semantic_configuration_limit_invalid")

    spec = _source_spec(scope)
    source_artifacts = _load_source_artifacts(spec)
    semantic = _redact_semantic_configuration(source_artifacts["semantic"])
    if not include_candidates:
        # Keep the default read model focused on published business
        # authority.  The complete inferred candidate inventory remains
        # available through the explicit include_candidates=true query flag,
        # which is what the product's full configuration inspector uses.
        semantic["semantic_assets"] = [
            asset
            for asset in semantic.get("semantic_assets") or []
            if str(asset.get("review_status") or "").casefold().startswith("reviewed")
        ]
    # Dictionary evidence is published as a companion artifact so that it can
    # be regenerated independently from the semantic configuration.  Include
    # it in the read model when older semantic documents do not embed it.
    dictionary_evidence = _redact_semantic_configuration(
        source_artifacts.get("dictionary_evidence") or {}
    )
    if not semantic.get("dictionary_evidence") and dictionary_evidence:
        semantic["dictionary_evidence"] = dictionary_evidence
    collection_sections = {
        name
        for name in _SEMANTIC_CONFIGURATION_SECTIONS
        if name
        not in {
            "summary",
            "source_binding",
            "activation_gate",
            "query_policy",
            "response_language_policy",
            "ontology_overlay",
            "technical_catalog",
            "dictionary_semantic_publication",
            "dictionary_evidence",
            "semantic_candidate_catalog",
            "relationship_candidate_catalog",
            "all",
        }
    }
    collection_counts = {
        name: len(semantic.get(name) or [])
        for name in sorted(collection_sections)
    }
    source_binding = semantic.get("source_binding") or {}
    source = {
        "key": spec["key"],
        "label": spec["label"],
        "source_id": source_binding.get("source_id", spec["source_id"]),
        "database_name": source_binding.get("database_name"),
        "authorized_schemas": list(source_binding.get("allowed_schemas") or []),
        "semantic_version": semantic.get("semantic_version"),
    }
    metadata = {
        "schema": semantic.get("schema"),
        "status": semantic.get("status"),
        "semantic_version": semantic.get("semantic_version"),
        "metric_contract_version": semantic.get("metric_contract_version"),
        "supersedes_for_free_form": semantic.get("supersedes_for_free_form"),
        "source_binding": semantic.get("source_binding") or {},
        "activation_gate": semantic.get("activation_gate") or {},
        "query_policy": semantic.get("query_policy") or {},
        "response_language_policy": semantic.get("response_language_policy"),
        "ontology_overlay": semantic.get("ontology_overlay"),
        "technical_catalog": semantic.get("technical_catalog"),
        "dictionary_evidence": semantic.get("dictionary_evidence") or dictionary_evidence,
        "business_semantic_rules": semantic.get("business_semantic_rules") or [],
        "semantic_caveats": semantic.get("semantic_caveats") or [],
        "collection_counts": collection_counts,
        "available_sections": list(_SEMANTIC_CONFIGURATION_SECTIONS),
    }
    response: dict[str, Any] = {
        "schema": "gda.abu-dhabi-semantic-configuration.v1",
        "scope": scope,
        "source": source,
        "section": section,
        "offset": offset,
        "limit": limit,
        "search": search,
        "collection_counts": collection_counts,
        "available_sections": list(_SEMANTIC_CONFIGURATION_SECTIONS),
        "execution_authority": False,
        "gold_artifacts_runtime_accessible": False,
        "source_rows_persisted": False,
    }
    if section == "summary":
        response.update({"total": 1, "has_more": False, "configuration": metadata})
        return response
    if section == "all":
        response.update(
            {
                "total": 1,
                "has_more": False,
                "configuration": semantic,
                "downloadable": True,
            }
        )
        return response
    if section in {
        "source_binding",
        "activation_gate",
        "query_policy",
        "response_language_policy",
        "ontology_overlay",
        "technical_catalog",
        "dictionary_semantic_publication",
        "dictionary_evidence",
        "semantic_candidate_catalog",
        "relationship_candidate_catalog",
    }:
        response.update(
            {
                "total": 1,
                "has_more": False,
                "configuration": {
                    section: (
                        semantic.get(section)
                        if section != "dictionary_evidence"
                        else semantic.get("dictionary_evidence") or dictionary_evidence
                    )
                },
            }
        )
        return response

    raw_items = list(semantic.get(section) or [])
    normalized_search = search.strip().casefold()
    if normalized_search:
        raw_items = [
            item
            for item in raw_items
            if normalized_search
            in json.dumps(item, ensure_ascii=False, sort_keys=True).casefold()
        ]
    items = raw_items[offset : offset + limit]
    response.update(
        {
            "total": len(raw_items),
            "has_more": offset + len(items) < len(raw_items),
            "items": items,
        }
    )
    return response


def _resource_status_counts(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for resource in catalog.get("resources") or []:
        status = str(resource.get("semantic_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return [{"status": status, "count": count} for status, count in sorted(counts.items())]


def _resource_inventory(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose table-level discovery evidence without exposing source rows.

    This is intentionally a compact read model.  Field definitions remain in
    the catalog artifact and are not duplicated into the product response;
    the UI can therefore inspect every discovered object while keeping the
    evidence payload bounded for the 772-resource Makani source.
    """

    inventory: list[dict[str, Any]] = []
    for resource in catalog.get("resources") or []:
        fields = list(resource.get("fields") or [])
        dictionary = resource.get("dictionary_mapping") or {}
        inventory.append(
            {
                "physical_table": resource.get("physical_table"),
                "resource_type": resource.get("resource_type"),
                "semantic_status": resource.get("semantic_status"),
                "activation_reason": resource.get("activation_reason"),
                "field_count": len(fields),
                "spatial": any(
                    "geometry" in str(field.get("data_type") or "").casefold()
                    or str(field.get("physical_field") or "").casefold()
                    in {"shape", "geom", "geometry"}
                    for field in fields
                ),
                "estimated_record_count": resource.get("estimated_record_count"),
                "primary_key_count": len(resource.get("primary_key") or []),
                "foreign_key_count": len(resource.get("foreign_keys") or []),
                "dictionary_status": dictionary.get("status"),
            }
        )
    return sorted(
        inventory,
        key=lambda item: str(item.get("physical_table") or "").casefold(),
    )


def _merge_semantic_resource_inventory(
    inventory: list[dict[str, Any]], semantic: dict[str, Any]
) -> list[dict[str, Any]]:
    """Attach execution/read-mode state to the unified metadata inventory."""

    bindings = {
        str(item.get("physical_table") or ""): item
        for item in semantic.get("table_bindings") or []
        if str(item.get("physical_table") or "")
    }
    merged = []
    for item in inventory:
        binding = bindings.get(str(item.get("physical_table") or ""), {})
        merged.append(
            {
                **item,
                "binding_status": binding.get("binding_status"),
                "semantic_coverage_status": binding.get("semantic_coverage_status"),
                "execution_eligible": binding.get("execution_eligible") is True,
                "technical_query_eligible": binding.get("technical_query_eligible") is True,
                "technical_query_policy": binding.get("technical_query_policy"),
                "field_coverage": binding.get("field_coverage") or {},
                "dictionary_evidence": _public_artifact_value(
                    binding.get("dictionary_evidence") or {}
                ),
            }
        )
    return merged


def _source_registration(username: str, source_id: int) -> dict[str, Any]:
    """Return only status fields from the platform source registry.

    Artifact evidence remains useful when a viewer has no ownership of the
    source registration, so an unavailable registry record is not treated as
    a healthy source.
    """

    try:
        from ..virtual_sources import list_virtual_sources

        records = list_virtual_sources(username, include_shared=True)
        source = next(
            (item for item in records if int(item.get("id") or -1) == source_id),
            None,
        )
        if source is None:
            return {"visible_to_current_user": False, "registration_status": "not_visible"}
        return {
            "visible_to_current_user": True,
            "registration_status": "registered",
            "enabled": bool(source.get("enabled")),
            "health_status": str(source.get("health_status") or "unknown"),
            "discovery_status": str(source.get("discovery_status") or "unknown"),
            "last_discovery_at": source.get("last_discovery_at"),
            "last_health_check": source.get("last_health_check"),
        }
    except Exception:
        logger.warning("Unable to read virtual-source status for source_id=%s", source_id)
        return {"visible_to_current_user": False, "registration_status": "unavailable"}


def _semantic_asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
    labels = asset.get("labels") or {}
    return {
        "asset_id": asset.get("asset_id"),
        "label": labels.get("zh") or labels.get("en") or asset.get("asset_id"),
        "labels": {key: value for key, value in labels.items() if key in {"zh", "en", "ar"}},
        "description": asset.get("description"),
        "review_status": asset.get("review_status"),
        "grain": asset.get("grain"),
        "roles": list(asset.get("roles") or []),
        "capabilities": list(asset.get("capabilities") or []),
        "physical_tables": list(asset.get("physical_tables") or []),
        "fields": [
            {
                "semantic_field": field.get("semantic_field"),
                "physical_field": field.get("physical_field"),
                "business_role": field.get("business_role"),
                "usage": field.get("usage"),
                "unit": field.get("unit"),
                "labels": field.get("labels") or {},
            }
            for field in asset.get("fields") or []
        ],
    }


def _metric_contract_summary(contract: dict[str, Any]) -> dict[str, Any]:
    direct = contract.get("direct_execution") or {}
    return {
        "contract_id": contract.get("contract_id"),
        "operation": contract.get("operation"),
        "tables": list(contract.get("tables") or []),
        "dimensions": [item.get("alias") for item in contract.get("dimensions") or []],
        "metrics": [item.get("alias") for item in contract.get("metrics") or []],
        "order_by": list(contract.get("order_by") or []),
        "review_status": contract.get("review_status", "technical_table_local"),
        "priority": contract.get("priority"),
        "direct_execution_enabled": direct.get("enabled") is True,
    }


def _benchmark_cases(benchmark: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the complete benchmark inventory with optional run observations.

    A report may intentionally cover only a small execution sample (for
    example, a four-question Gemini rerun).  The product inventory must still
    represent every published definition; execution fields therefore describe
    the latest observation or explicitly say ``not_run``.
    """

    observations = {
        str(item.get("case_id")): item
        for item in report.get("cases") or []
        if isinstance(item, dict) and item.get("case_id")
    }
    items = []
    for definition in benchmark.get("cases") or []:
        if not isinstance(definition, dict):
            continue
        case_id = str(definition.get("case_id") or "")
        observation = observations.get(case_id) or {}
        expected = definition.get("expected") or {}
        observed = bool(observation)
        items.append(
            {
                "case_id": case_id,
                "question": definition.get("question"),
                "language": definition.get("language"),
                "track": observation.get("track") or definition.get("track"),
                "split": observation.get("split") or definition.get("split"),
                "expected_status": expected.get("status"),
                "capabilities": list(definition.get("capabilities") or []),
                "execution_status": observation.get("status") if observed else "not_run",
                "run_count": observation.get("run_count", 0) if observed else 0,
                "passed_run_count": observation.get("passed_run_count", 0) if observed else 0,
                "pass_rate": observation.get("pass_rate") if observed else None,
                "behavior_consistency": observation.get("behavior_consistency") if observed else None,
                "planner_route_counts": observation.get("planner_route_counts") or {},
                "meets_release_threshold": (
                    observation.get("meets_case_release_threshold")
                    if observed
                    else None
                ),
            }
        )
    return items


def _benchmark_split_counts(benchmark: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in benchmark.get("cases") or []:
        split = str(case.get("split") or "unspecified")
        counts[split] = counts.get(split, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _benchmark_v2_summary(
    benchmark: dict[str, Any], selection_report: dict[str, Any] | None = None
) -> dict[str, Any]:
    cases = list(benchmark.get("cases") or [])
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        by_scope.setdefault(str(case.get("source_scope") or ""), []).append(
            {
                "case_id": case.get("case_id"),
                "question": case.get("question"),
                "language": case.get("language"),
                "split": case.get("split"),
                "family": case.get("family"),
                "expected_outcome": (case.get("expected") or {}).get("outcome"),
                "expected_assets": list((case.get("expected") or {}).get("semantic_assets") or []),
            }
        )
    return {
        "benchmark_id": benchmark.get("benchmark_id"),
        "version": benchmark.get("version"),
        "purpose": benchmark.get("purpose"),
        "evaluation_dimensions": list(benchmark.get("evaluation_dimensions") or []),
        "anti_leakage": benchmark.get("anti_leakage") or {},
        "case_count": len(cases),
        "scope_case_counts": {scope: len(items) for scope, items in sorted(by_scope.items())},
        "cases_by_scope": by_scope,
        "selection_report": {
            "scope": selection_report.get("scope"),
            "metrics": selection_report.get("metrics") or {},
            "claim_boundary": selection_report.get("claim_boundary") or {},
        }
        if selection_report
        else None,
    }


def _benchmark_v3_summary(
    benchmark: dict[str, Any], selection_report: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Expose the challenge-set contract and aggregate selection evidence."""

    cases = list(benchmark.get("cases") or [])
    scope_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    difficulty_counts: dict[str, int] = {}
    for case in cases:
        scope = str(case.get("source_scope") or "unknown")
        family = str(case.get("family") or "unknown")
        difficulty = str(case.get("difficulty") or "unknown")
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1
        difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
    return {
        "benchmark_id": benchmark.get("benchmark_id"),
        "version": benchmark.get("version"),
        "purpose": benchmark.get("purpose"),
        "case_count": len(cases),
        "scope_case_counts": dict(sorted(scope_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "evaluation_dimensions": list(benchmark.get("evaluation_dimensions") or []),
        "anti_leakage": benchmark.get("anti_leakage") or {},
        "selection_report": {
            "scope": selection_report.get("scope"),
            "metrics": selection_report.get("metrics") or {},
            "claim_boundary": selection_report.get("claim_boundary") or {},
        }
        if selection_report
        else None,
        "cases": [
            {
                "case_id": case.get("case_id"),
                "source_scope": case.get("source_scope"),
                "question": case.get("question"),
                "language": case.get("language"),
                "family": case.get("family"),
                "difficulty": case.get("difficulty"),
                "expected_outcome": (case.get("expected") or {}).get("outcome"),
            }
            for case in cases
        ],
    }


def _candidate_catalog_summary(candidate_catalog: dict[str, Any]) -> dict[str, Any]:
    """Return coverage and governance state, never the 931-candidate payload."""

    return {
        "catalog_id": candidate_catalog.get("catalog_id"),
        "coverage": candidate_catalog.get("coverage") or {},
        "runtime_role": candidate_catalog.get("runtime_role") or {},
        "claim_boundary": candidate_catalog.get("claim_boundary") or {},
    }


def _relationship_catalog_summary(relationship_catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_id": relationship_catalog.get("catalog_id"),
        "coverage": relationship_catalog.get("coverage") or {},
        "runtime_role": relationship_catalog.get("runtime_role") or {},
        "claim_boundary": relationship_catalog.get("claim_boundary") or {},
    }


def _source_evidence(spec: dict[str, str | int], username: str) -> dict[str, Any]:
    artifacts = _load_source_artifacts(spec)
    semantic = artifacts["semantic"]
    ontology = artifacts["ontology"]
    catalog = artifacts["catalog"]
    candidates = artifacts["candidates"]
    relationships = artifacts["relationships"]
    report = artifacts["report"]
    scorecard = artifacts.get("scorecard") or {}
    coverage_plan = artifacts.get("coverage_plan") or {}
    technical_candidates = artifacts.get("technical_candidates") or {}
    dictionary_evidence = artifacts.get("dictionary_evidence") or {}
    binding = semantic.get("source_binding") or {}
    coverage = ontology.get("coverage") or {}
    source_id = int(spec["source_id"])
    return {
        "key": spec["key"],
        "label": spec["label"],
        "semantic_admin_scope": spec["key"],
        "source": {
            "source_id": source_id,
            "database_name": binding.get("database_name"),
            "authorized_schemas": list(binding.get("allowed_schemas") or []),
            "execution_mode": binding.get("execution_mode"),
            "virtual_ingestion": {
                "mode": "metadata_only_virtual_source",
                "source_rows_persisted": False,
                "query_execution": "read_only_source_side_pushdown",
            },
            "discovery_fingerprint": binding.get("discovery_fingerprint"),
            "profile_fingerprint": binding.get("profile_fingerprint"),
            "registration": _source_registration(username, source_id),
        },
        "technical_catalog": {
            "status": catalog.get("status"),
            "resource_count": (catalog.get("coverage") or {}).get("resource_count"),
            "field_count": (catalog.get("coverage") or {}).get("field_count"),
            "active_semantic_resource_count": (
                (catalog.get("coverage") or {}).get("active_semantic_resource_count")
            ),
            "technical_only_or_excluded_count": (
                (catalog.get("coverage") or {}).get("technical_only_or_excluded_count")
            ),
            "status_counts": _resource_status_counts(catalog),
            "resources": _merge_semantic_resource_inventory(
                _resource_inventory(catalog), semantic
            ),
        },
        "ontology": {
            "version": ontology.get("ontology_enrichment_version"),
            "status": ontology.get("status"),
            "base_ontology": ontology.get("base_ontology"),
            "coverage": coverage,
            "runtime_role": ontology.get("runtime_role") or {},
            "prohibitions": list(ontology.get("prohibitions") or []),
            "concepts": [
                {
                    "concept_id": item.get("concept_id"),
                    "physical_binding": item.get("physical_binding"),
                    "runtime_status": item.get("runtime_status"),
                }
                for item in ontology.get("concepts") or []
            ],
            "relations": _public_artifact_value(list(ontology.get("relations") or [])),
        },
        "semantic_candidates": _candidate_catalog_summary(candidates),
        "relationship_candidates": _relationship_catalog_summary(relationships),
        "dictionary_evidence": {
            "schema": dictionary_evidence.get("schema"),
            "source_kind": dictionary_evidence.get("source_kind"),
            "compatibility": dictionary_evidence.get("compatibility") or {},
            "coverage": dictionary_evidence.get("coverage") or {},
            "claim_boundary": dictionary_evidence.get("claim_boundary") or {},
            "generated_from": _public_artifact_value(
                dictionary_evidence.get("generated_from") or {}
            ),
        },
        "semantic_layer": {
            "version": semantic.get("semantic_version"),
            "status": semantic.get("status"),
            "activation_gate": semantic.get("activation_gate") or {},
            "metric_contract_version": semantic.get("metric_contract_version"),
            "query_policy": semantic.get("query_policy") or {},
            "business_semantic_rules": list(semantic.get("business_semantic_rules") or []),
            "semantic_caveats": list(semantic.get("semantic_caveats") or []),
            "assets": [
                _semantic_asset_summary(asset) for asset in semantic.get("semantic_assets") or []
            ],
            "relationships": _public_artifact_value(
                list(semantic.get("relationships") or [])
            ),
            "metric_contracts": [
                _metric_contract_summary(contract)
                for contract in semantic.get("metric_contracts") or []
            ],
        },
        "benchmark": {
            "benchmark_id": (report.get("benchmark") or {}).get("benchmark_id"),
            "status": report.get("status"),
            "run_count": report.get("run_count"),
            "metrics": _redact_semantic_configuration(report.get("metrics") or {}),
            "release_gate": report.get("release_gate") or {},
            "split_counts": _benchmark_split_counts(artifacts["benchmark"]),
            "cases": _benchmark_cases(artifacts["benchmark"], report),
            "integrity": {
                "questions_use_business_language": True,
                "gold_artifacts_runtime_accessible": False,
                "source_rows_persisted": False,
            },
        },
        "benchmark_scorecard": {
            "status": scorecard.get("status"),
            "generated_at": scorecard.get("generated_at"),
            "benchmark": scorecard.get("benchmark") or {},
            "coverage": scorecard.get("coverage") or {},
            "quality": scorecard.get("quality") or {},
            "release_gates": scorecard.get("release_gates") or {},
            "terminology": scorecard.get("terminology") or {},
        },
        "benchmark_coverage_plan": {
            "summary": coverage_plan.get("summary") or {},
            "claim_boundary": coverage_plan.get("claim_boundary") or {},
        },
        "technical_benchmark_candidates": {
            "coverage": technical_candidates.get("coverage") or {},
            "claim_boundary": technical_candidates.get("claim_boundary") or {},
            "source": {
                "semantic_layer_sha256": (
                    (technical_candidates.get("source") or {}).get("semantic_layer_sha256")
                ),
                "discovery_fingerprint": (
                    (technical_candidates.get("source") or {}).get("discovery_fingerprint")
                ),
                "profile_fingerprint": (
                    (technical_candidates.get("source") or {}).get("profile_fingerprint")
                ),
            },
        },
        "technical_freeze_coverage": {
            "metrics": (artifacts.get("technical_coverage") or {}).get("metrics") or {},
            "operation_coverage": (artifacts.get("technical_coverage") or {}).get("operation_coverage") or {},
            "freeze_batches": (artifacts.get("technical_coverage") or {}).get("freeze_batches") or [],
            "claim_boundary": (artifacts.get("technical_coverage") or {}).get("claim_boundary") or {},
        },
        "business_semantic_review_queue": {
            "coverage": (artifacts.get("business_semantic_task_queue") or {}).get("coverage") or {},
            "claim_boundary": (artifacts.get("business_semantic_task_queue") or {}).get("claim_boundary") or {},
        },
        "business_benchmark_review_queue": {
            "coverage": (artifacts.get("business_benchmark_task_queue") or {}).get("coverage") or {},
            "claim_boundary": (artifacts.get("business_benchmark_task_queue") or {}).get("claim_boundary") or {},
        },
        "technical_freeze_resume": {
            "total_candidates": (artifacts.get("technical_freeze_state") or {}).get("total_candidates"),
            "completed_candidate_count": len((artifacts.get("technical_freeze_state") or {}).get("completed_candidate_ids") or []),
            "batch_count": len((artifacts.get("technical_freeze_state") or {}).get("batch_files") or []),
            "updated_at": (artifacts.get("technical_freeze_state") or {}).get("updated_at"),
        },
    }


def _federated_benchmark_evidence() -> dict[str, Any]:
    semantic = _load_json(_ARTIFACT_ROOT / str(_FEDERATED_SPEC["semantic"]))
    benchmark = _load_json(_ARTIFACT_ROOT / str(_FEDERATED_SPEC["benchmark"]))
    report = _load_json(_BENCHMARK_ROOT / "reports" / str(_FEDERATED_SPEC["report"]))
    definitions = {str(case.get("case_id")): case for case in benchmark.get("cases") or []}
    cases = []
    for observation in report.get("cases") or []:
        case_id = str(observation.get("case_id") or "")
        definition = definitions.get(case_id, {})
        cases.append(
            {
                "case_id": case_id,
                "question": definition.get("question"),
                "language": definition.get("language"),
                "track": definition.get("track", "federated"),
                "expected_status": (definition.get("expected") or {}).get("status"),
                "passed": observation.get("status") == "passed",
                "planner_route": (
                    (observation.get("observed") or {}).get("planner", {}).get("route")
                ),
                "typed_source_plan_validated": (
                    (observation.get("observed") or {}).get("semantic_plan", {}).get("status")
                    == "planned"
                ),
            }
        )
    return {
        "key": _FEDERATED_SPEC["key"],
        "label": _FEDERATED_SPEC["label"],
        "semantic_version": semantic.get("semantic_version"),
        "status": report.get("status"),
        "activation_gate": semantic.get("activation_gate") or {},
        "claim_boundary": (report.get("benchmark") or {}).get("claim_boundary") or {},
        "execution_policy": report.get("execution_policy") or {},
        "limitations": list(report.get("limitations") or []),
        "metrics": report.get("metrics") or {},
        "planner": report.get("planner") or {},
        "cases": cases,
        "integrity": {
            "questions_use_business_language": True,
            "gold_artifacts_runtime_accessible": False,
            "source_rows_persisted": False,
        },
    }


def build_product_evidence(username: str) -> dict[str, Any]:
    """Build a customer-facing read model from frozen, non-secret artifacts."""

    sources = [_source_evidence(spec, username) for spec in _SOURCE_SPECS]
    selection_report = (
        _load_json(_BENCHMARK_V2_SELECTION_REPORT_PATH)
        if _BENCHMARK_V2_SELECTION_REPORT_PATH.exists()
        else None
    )
    benchmark_v2 = _benchmark_v2_summary(_load_json(_BENCHMARK_V2_PATH), selection_report)
    benchmark_v3 = None
    if _BENCHMARK_V3_PATH.exists():
        benchmark_v3 = _benchmark_v3_summary(
            _load_json(_BENCHMARK_V3_PATH),
            _load_json(_BENCHMARK_V3_SELECTION_REPORT_PATH)
            if _BENCHMARK_V3_SELECTION_REPORT_PATH.exists()
            else None,
        )
    readiness = _load_json(_FULL_SEMANTIC_READINESS_PATH)
    readiness_sources = readiness.get("sources") or {}
    # The historical combined readiness report is retained as an audit
    # artifact, but it predates the current source-bound table-card
    # publication.  Overlay each source's technical/business coverage from
    # the checksum-verified current semantic artifact so the console cannot
    # report stale inventory (for example 161 instead of the current 176
    # Liveability resources).  Release gates and claim boundaries remain
    # conservative and continue to come from the audited readiness report.
    current_readiness_sources: dict[str, dict[str, Any]] = {}
    for source_spec in _SOURCE_SPECS:
        source_key = str(source_spec["key"])
        current_artifacts = _load_source_artifacts(source_spec)
        previous = readiness_sources.get(source_key) or {}
        current_semantic = current_artifacts.get("semantic") or {}
        merged = dict(previous) if isinstance(previous, dict) else {}
        current_coverage = current_semantic.get("coverage") or {}
        if current_coverage:
            # Preserve readiness-only derived counters (notably table-tier
            # and field-role summaries) while replacing inventory counters
            # with the current semantic publication.
            previous_coverage = merged.get("semantic_coverage") or {}
            merged["semantic_coverage"] = {
                **previous_coverage,
                **current_coverage,
                "table_tier_counts": previous_coverage.get("table_tier_counts")
                or current_coverage.get("table_tier_counts")
                or {},
                "field_semantics": previous_coverage.get("field_semantics")
                or current_coverage.get("field_semantics")
                or {},
            }
        current_readiness_sources[source_key] = merged
    return {
        "schema": "gda.abu-dhabi-nl2semantic2sql-product-evidence.v1",
        "product": {
            "name": "Abu Dhabi NL2Semantic2SQL",
            "runtime_mode": "governed_virtual_read_only",
            "source_rows_persisted": False,
            "benchmark_gold_runtime_accessible": False,
            "business_ontology_complete": False,
            "business_ontology_scope": "reviewed_asset_subset",
            "execution_paths": {
                "reviewed_metric_contract": {
                    "enabled": True,
                    "execution_authority": "reviewed_metric_contract_template_compiler",
                    "flow": [
                        "metric contract resolution",
                        "SemanticQueryIR",
                        "semantic validation",
                        "logical plan",
                        "certified template compiler",
                        "read-only source execution",
                    ],
                    "scope": "unique, unparameterized reviewed metric contracts",
                },
                "governed_free_form": {
                    "enabled": True,
                    "execution_authority": (
                        "governed SQL admission or validated semantic IR PostGIS compiler"
                    ),
                    "semantic_ir_mode": "executable_restricted_canary",
                    "scope": (
                        "baseline SQL admission remains default; semantic_ir_experimental "
                        "accepts only logical AdHocSemanticQueryIR and compiles it "
                        "deterministically after binding and read-only source admission"
                    ),
                },
                "semantic_candidate_selection": {
                    "enabled": True,
                    "execution_authority": "none",
                    "flow": [
                        "business-language candidate retrieval",
                        "ambiguity and approval gate",
                        "reviewed semantic runtime only",
                    ],
                    "scope": (
                        "all discovered resources are assessed; unreviewed candidates "
                        "cannot execute"
                    ),
                },
            },
        },
        "sources": sources,
        "full_semantic_readiness": {
            "schema": readiness.get("schema"),
            "scope": readiness.get("scope"),
            "claim_boundary": readiness.get("claim_boundary"),
            "global_release_gate": readiness.get("global_release_gate") or {},
            "sources": {
                key: _readiness_summary(value)
                for key, value in current_readiness_sources.items()
                if isinstance(value, dict)
            },
        },
        "benchmark_v2": benchmark_v2,
        "benchmark_v3": benchmark_v3,
        "benchmark_evaluation": _published_evaluation_summary(),
        "federated": _federated_benchmark_evidence(),
    }


def _compact_plan(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "schema": value.get("schema_id"),
        "status": value.get("status"),
        "execution_authority": value.get("execution_authority"),
        "fallback_reason": value.get("fallback_reason"),
        "fingerprints": value.get("fingerprints") or {},
        "semantic_ir": value.get("semantic_ir") or {},
        "validation": value.get("validation") or {},
        "logical_plan": value.get("logical_plan") or {},
        "physical_plan": value.get("physical_plan") or {},
    }


def _compact_query(query: dict[str, Any]) -> dict[str, Any]:
    return {
        "sql": query.get("sql"),
        "sql_sha256": query.get("sql_sha256"),
        "tables": list(query.get("tables") or []),
        "columns": list(query.get("columns") or []),
        "semantic_metric_contract": query.get("semantic_metric_contract") or {},
        "postprocessor_corrections": list(query.get("postprocessor_corrections") or []),
        "semantic_plan": _compact_plan(query.get("semantic_plan")),
    }


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    rows = list(result.get("data") or [])[:_DISPLAY_ROW_LIMIT]
    return {
        "row_count": result.get("row_count"),
        "displayed_row_count": min(len(rows), _DISPLAY_ROW_LIMIT),
        "truncated_for_console": len(result.get("data") or []) > _DISPLAY_ROW_LIMIT,
        "columns": list(result.get("columns") or []),
        "data": rows,
        "result_fingerprint": result.get("result_fingerprint"),
        "equivalence_fingerprints": result.get("equivalence_fingerprints") or {},
    }


def _compact_generation(generation: dict[str, Any]) -> dict[str, Any]:
    usage = generation.get("usage") or {}
    return {
        "latency_ms": generation.get("latency_ms"),
        "usage": {
            key: int(usage.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "reasoning_tokens")
        },
        "observed_model_versions": [
            str(value) for value in generation.get("observed_model_versions") or []
        ],
        "attempt": generation.get("attempt"),
    }


def _compact_single_source_report(scope: str, report: dict[str, Any]) -> dict[str, Any]:
    query = report.get("query") or {}
    source = report.get("source") or {}
    return {
        "schema": "gda.abu-dhabi-nl2semantic2sql-console-result.v1",
        "scope": scope,
        "status": report.get("status"),
        "reason": report.get("reason"),
        # The governed runtime writes a redacted error message. Returning it
        # here makes an execution failure diagnosable in the product console
        # without exposing prompts, credentials, or source rows.
        "error": report.get("error"),
        "semantic_version": report.get("semantic_version"),
        "metric_contract_version": report.get("metric_contract_version"),
        "answer_scope": report.get("answer_scope") or {
            "mode": "reviewed_business_semantics",
            "technical_tables": [],
            "business_semantic_authority": True,
        },
        "planner": report.get("planner") or {},
        "source": {
            "source_id": source.get("source_id"),
            "source_name": source.get("source_name"),
            "database_name": source.get("database_name"),
            "authorized_schemas": list(source.get("authorized_schemas") or []),
            "discovery_fingerprint": source.get("discovery_fingerprint"),
            "execution_mode": source.get("execution_mode"),
        },
        "source_rows_persisted": report.get("source_rows_persisted") is True,
        "generation": _compact_generation(report.get("generation") or {}),
        "timing": {
            "total_ms": (report.get("timing") or {}).get("total_ms"),
            "database_ms": (report.get("timing") or {}).get("database_ms"),
        },
        "query": _compact_query(query),
        "result": _compact_result(report.get("result") or {}),
        "static_validation": {
            str(key): value
            for key, value in (report.get("static_validation") or {}).items()
            if isinstance(value, (bool, int, float, str))
        },
        "semantic_caveats": list(report.get("semantic_caveats") or []),
    }


def _compact_federated_report(report: dict[str, Any]) -> dict[str, Any]:
    sections = []
    for section in (report.get("result") or {}).get("sections") or []:
        sections.append(
            {
                "source": section.get("source"),
                "source_id": section.get("source_id"),
                "query": _compact_query(section.get("query") or {}),
                "result": _compact_result(section.get("result") or {}),
            }
        )
    return {
        "schema": "gda.abu-dhabi-nl2semantic2sql-console-result.v1",
        "scope": "federated",
        "status": report.get("status"),
        "reason": report.get("reason"),
        "error": report.get("error"),
        "semantic_version": report.get("semantic_version"),
        "planner": report.get("planner") or {},
        "timing": {
            "total_ms": (report.get("timing") or {}).get("total_ms"),
            "database_ms": (report.get("timing") or {}).get("database_ms"),
        },
        "contract": report.get("contract") or {},
        "semantic_plan": _compact_plan(report.get("semantic_plan")),
        "source_rows_persisted": report.get("source_rows_persisted") is True,
        "result": {
            "section_count": (report.get("result") or {}).get("section_count"),
            "bundle_fingerprint": (report.get("result") or {}).get("bundle_fingerprint"),
            "sections": sections,
        },
    }


def _source_spec(scope: str) -> dict[str, str | int]:
    spec = next((item for item in _SOURCE_SPECS if item["key"] == scope), None)
    if spec is None:
        raise ValueError("scope must be liveability or makani")
    return spec


def _candidate_resolution_view(
    resolution: dict[str, Any], candidate_catalog: dict[str, Any]
) -> dict[str, Any]:
    """Redact private bindings from the business-language selection response."""

    source_assets = {
        str(asset.get("candidate_id") or ""): asset
        for asset in candidate_catalog.get("assets") or []
        if isinstance(asset, dict)
    }
    candidates: list[dict[str, Any]] = []
    for item in resolution.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        asset = source_assets.get(str(item.get("candidate_id") or ""), {})
        alignment = item.get("dictionary_alignment") or {}
        field_evidence = [
            str(field.get("dictionary_description") or "")
            for field in asset.get("fields") or []
            if isinstance(field, dict)
            and field.get("dictionary_supported") is True
            and str(field.get("dictionary_description") or "")
        ]
        candidates.append(
            {
                "candidate_id": item.get("candidate_id"),
                "business_label": item.get("business_label"),
                "business_aliases": list(item.get("business_aliases") or []),
                "business_description": item.get("business_description"),
                "asset_state": item.get("asset_state"),
                "state_reason": asset.get("state_reason"),
                "published_runtime_asset": item.get("published_runtime_asset"),
                "score": item.get("score"),
                "matched_business_terms": list(item.get("matched_business_terms") or []),
                "matched_business_objects": list(item.get("matched_business_objects") or []),
                "dictionary_evidence": {
                    "alignment_status": alignment.get("status"),
                    "matched_field_count": alignment.get("matched_field_count"),
                    "matched_field_coverage": alignment.get("matched_field_coverage"),
                    "field_description_samples": field_evidence[:8],
                },
            }
        )
    return {
        "schema": resolution.get("schema"),
        "status": resolution.get("status"),
        "decision": resolution.get("decision"),
        "question": resolution.get("question"),
        "physical_table_name_used_for_retrieval": False,
        "candidate_count_considered": resolution.get("candidate_count_considered"),
        "reviewed_asset_set_candidate_ids": list(
            resolution.get("reviewed_asset_set_candidate_ids") or []
        ),
        "candidates": candidates,
    }


def resolve_semantic_candidates(scope: str, question: str) -> dict[str, Any]:
    """Resolve business candidates without granting any SQL authority."""

    from ..abu_dhabi_semantic_candidates import rank_semantic_candidate_assets

    spec = _source_spec(scope)
    artifacts = _load_source_artifacts(spec)
    semantic = artifacts["semantic"]
    candidate_catalog = artifacts["candidates"]
    return {
        "schema": "gda.abu-dhabi-semantic-candidate-console-result.v1",
        "scope": scope,
        "source": {
            "source_id": spec["source_id"],
            "database_name": (semantic.get("source_binding") or {}).get("database_name"),
        },
        "catalog": _candidate_catalog_summary(candidate_catalog),
        "resolution": _candidate_resolution_view(
            rank_semantic_candidate_assets(question, candidate_catalog),
            candidate_catalog,
        ),
    }


def _question_capability_requirements(question: str) -> list[tuple[str, tuple[str, ...]]]:
    folded = question.casefold()
    return [
        (requirement, capabilities)
        for requirement, terms, capabilities in _QUESTION_CAPABILITY_REQUIREMENTS
        if any(term.casefold() in folded for term in terms)
    ]


def _configured_intent_capability_requirements(
    question: str,
    language: str,
    semantic: dict[str, Any],
) -> list[tuple[str, tuple[str, ...], str]]:
    """Resolve source-specific intent gates from reviewed semantic config."""

    from ..governed_virtual_nl2sql import _metric_contract_matches_question

    requirements: list[tuple[str, tuple[str, ...], str]] = []
    for rule in (semantic.get("query_policy") or {}).get("intent_capability_requirements") or []:
        if not isinstance(rule, dict) or not _metric_contract_matches_question(
            question,
            language,
            {"match": {"required_term_groups": rule.get("required_term_groups") or {}}},
        ):
            continue
        intent_id = str(rule.get("intent_id") or "").strip()
        capabilities = tuple(
            str(value) for value in rule.get("required_capabilities") or [] if str(value)
        )
        disposition = str(rule.get("disposition") or "clarify")
        if intent_id and capabilities and disposition in {"clarify", "refuse"}:
            requirements.append((intent_id, capabilities, disposition))
    return requirements


def _measure_field_matches_question(asset: dict[str, Any], question: str) -> bool:
    folded = question.casefold()
    question_words = {
        word
        for word in re.findall(r"[a-z][a-z0-9]{2,}", folded)
        if word
        not in {
            "the",
            "and",
            "all",
            "show",
            "compare",
            "average",
            "total",
            "sum",
            "count",
            "number",
            "each",
        }
    }
    for field in asset.get("fields") or []:
        if str(field.get("business_role") or "") != "measure":
            continue
        field_text = " ".join(
            [
                str(field.get("semantic_field") or ""),
                str(field.get("description") or ""),
                *[str(value) for value in (field.get("labels") or {}).values()],
            ]
        ).casefold()
        if any(
            len(term) >= 2 and term.casefold() in folded
            for term in (field.get("labels") or {}).values()
        ):
            return True
        field_words = set(re.findall(r"[a-z][a-z0-9]{2,}", field_text))
        if question_words.intersection(field_words):
            return True
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", field_text):
            if run in folded:
                return True
    return False


def _reviewed_candidate_capabilities(
    candidates: list[dict[str, Any]], semantic: dict[str, Any], question: str
) -> set[str]:
    reviewed_asset_ids = {
        str((candidate.get("published_runtime_asset") or {}).get("asset_id") or "")
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("published_runtime_asset")
    }
    capabilities: set[str] = set()
    for asset in semantic.get("semantic_assets") or []:
        if (
            not isinstance(asset, dict)
            or str(asset.get("asset_id") or "") not in reviewed_asset_ids
            or not str(asset.get("review_status") or "").casefold().startswith("reviewed")
        ):
            continue
        measure_matches = _measure_field_matches_question(asset, question)
        for capability in asset.get("capabilities") or []:
            value = str(capability)
            if value in {"sum", "average", "ranking"} and not measure_matches:
                continue
            if value:
                capabilities.add(value)
    return capabilities


def _reviewed_asset_set_is_connected(
    candidates: list[dict[str, Any]], semantic: dict[str, Any]
) -> bool:
    """Require an audited relation path for every selected business asset.

    Candidate retrieval can identify several relevant business concepts, but
    relevance does not prove they may be joined. This check derives a graph
    exclusively from reviewed semantic relationships and permits a multi-asset
    execution only when the selected assets form one connected component.
    """

    asset_ids = {
        str((candidate.get("published_runtime_asset") or {}).get("asset_id") or "")
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("published_runtime_asset")
    }
    asset_ids.discard("")
    if len(asset_ids) < 2:
        return True

    asset_by_table = {
        str(table).casefold(): str(asset.get("asset_id") or "")
        for asset in semantic.get("semantic_assets") or []
        if isinstance(asset, dict)
        for table in asset.get("physical_tables") or []
        if str(asset.get("asset_id") or "") in asset_ids
    }
    graph: dict[str, set[str]] = {asset_id: set() for asset_id in asset_ids}
    for relation in semantic.get("relationships") or []:
        if not isinstance(relation, dict) or not str(
            relation.get("review_status") or ""
        ).casefold().startswith("reviewed"):
            continue
        left = str(relation.get("left") or "")
        right = str(relation.get("right") or "")
        if "." not in left or "." not in right:
            continue
        left_table = left.rsplit(".", 1)[0].casefold()
        right_table = right.rsplit(".", 1)[0].casefold()
        left_asset = asset_by_table.get(left_table)
        right_asset = asset_by_table.get(right_table)
        if not left_asset or not right_asset or left_asset == right_asset:
            continue
        graph[left_asset].add(right_asset)
        graph[right_asset].add(left_asset)

    reachable = {next(iter(asset_ids))}
    pending = list(reachable)
    while pending:
        current = pending.pop()
        for neighbour in graph[current] - reachable:
            reachable.add(neighbour)
            pending.append(neighbour)
    return reachable == asset_ids


def _execution_admission(scope: str, question: str) -> dict[str, Any]:
    """Apply the candidate/review boundary inside the execution API.

    The UI performs candidate resolution for transparency, but it is not a
    security boundary.  This function is called immediately before any source
    runtime and returns only business-facing candidate evidence.  Physical
    bindings remain private to the semantic layer/compiler.
    """

    from ..governed_virtual_nl2sql import (
        classify_read_only_request,
        classify_sensitive_data_request,
        detect_question_language,
    )

    technical_semantic = (
        _load_source_artifacts(_source_spec(scope))["semantic"]
        if scope in {"liveability", "makani"}
        else None
    )
    policy_reason = classify_read_only_request(
        question,
        semantic_layer=technical_semantic,
    ) or classify_sensitive_data_request(question)
    if policy_reason:
        return {
            "schema": "gda.abu-dhabi-execution-admission.v1",
            "scope": scope,
            "status": "blocked",
            "decision": policy_reason,
            "disposition": "refuse",
            "runtime_admitted": False,
            "candidate_resolution": None,
        }

    # Technical metadata is a first-class, read-only query surface.  It is
    # intentionally checked before business candidate admission so a table
    # that has complete discovered fields is not made invisible merely because
    # its business definition is still awaiting review.  This branch grants
    # no joins, KPI contracts, or business-semantic authority.
    if scope in {"liveability", "makani"}:
        from ..governed_virtual_nl2sql import (
            _explicit_physical_tables,
            _technical_binding_is_queryable,
            _technical_query_binding_resolution,
        )

        assert technical_semantic is not None
        technical = _technical_query_binding_resolution(question, technical_semantic)
        if technical.get("status") == "resolved" and technical.get("technical_metadata_only"):
            return {
                "schema": "gda.abu-dhabi-execution-admission.v1",
                "scope": scope,
                "status": "technical_metadata_admitted",
                "decision": "technical_metadata_query_admitted",
                "disposition": "execute",
                "runtime_admitted": True,
                "query_mode": "technical_metadata_only",
                "business_semantic_authority": False,
                "candidate_resolution": {
                    "status": "technical_metadata_binding",
                    "table_count": len(technical.get("requested_tables") or []),
                },
            }
        explicit_tables = _explicit_physical_tables(question, technical_semantic)
        bindings = {
            str(item.get("physical_table") or ""): item
            for item in technical_semantic.get("table_bindings") or []
        }
        blocked_tables = [
            table
            for table in explicit_tables
            if table in bindings
            and bindings[table].get("execution_eligible") is not True
            and not _technical_binding_is_queryable(bindings[table])
        ]
        if blocked_tables:
            return {
                "schema": "gda.abu-dhabi-execution-admission.v1",
                "scope": scope,
                "status": "blocked",
                "decision": "explicit_table_not_queryable",
                "disposition": "clarify",
                "runtime_admitted": False,
                "candidate_resolution": {
                    "status": "blocked_table_binding",
                    "tables": blocked_tables,
                },
            }

    if scope == "federated":
        from ..abu_dhabi_federated_nl2sql import (
            FEDERATED_SEMANTIC_PATH,
            _load_federated_semantic_layer,
            classify_federated_admission,
        )

        federation = classify_federated_admission(
            question,
            detect_question_language(question),
            _load_federated_semantic_layer(FEDERATED_SEMANTIC_PATH),
        )
        if federation["disposition"] != "execute":
            return {
                "schema": "gda.abu-dhabi-execution-admission.v1",
                "scope": scope,
                "status": "blocked",
                "decision": federation["reason"],
                "disposition": federation["disposition"],
                "runtime_admitted": False,
                "candidate_resolution": None,
            }
        return {
            "schema": "gda.abu-dhabi-execution-admission.v1",
            "scope": scope,
            "status": "contract_gate",
            "decision": "federated_reviewed_contract_admitted",
            "disposition": "execute",
            "runtime_admitted": True,
            "candidate_resolution": None,
        }

    resolution_payload = resolve_semantic_candidates(scope, question)
    resolution = resolution_payload["resolution"]
    candidates = list(resolution.get("candidates") or [])
    top = candidates[0] if candidates else None
    reviewed_set_ids = {
        str(value)
        for value in resolution.get("reviewed_asset_set_candidate_ids") or []
        if str(value)
    }
    admitted_candidates = [
        item for item in candidates if str(item.get("candidate_id") or "") in reviewed_set_ids
    ] or ([top] if top else [])
    relationship_candidates = [
        item for item in candidates if str(item.get("candidate_id") or "") in reviewed_set_ids
    ] or admitted_candidates
    unreviewed_close = [
        item for item in admitted_candidates if not item.get("published_runtime_asset")
    ]
    semantic = _load_source_artifacts(_source_spec(scope))["semantic"]
    available_capabilities = _reviewed_candidate_capabilities(
        admitted_candidates, semantic, question
    )
    requirements = _question_capability_requirements(question)
    configured_requirements = _configured_intent_capability_requirements(
        question,
        detect_question_language(question),
        semantic,
    )
    all_requirements = [
        (requirement, required_capabilities, "refuse" if requirement == "prediction" else "clarify")
        for requirement, required_capabilities in requirements
    ] + configured_requirements
    unsupported_requirement = next(
        (
            (requirement, disposition)
            for requirement, required_capabilities, disposition in all_requirements
            if requirement == "prediction"
            or not set(required_capabilities).issubset(available_capabilities)
        ),
        None,
    )
    reviewed_asset_set_connected = _reviewed_asset_set_is_connected(
        relationship_candidates,
        semantic,
    )

    disposition = "clarify"
    if unsupported_requirement:
        requirement, disposition = unsupported_requirement
        decision = f"reviewed_asset_does_not_cover_{requirement}"
        status = "blocked"
    elif not candidates:
        decision = "clarify_or_submit_for_semantic_modelling"
        status = "blocked"
    elif resolution.get("status") == "underspecified_query":
        decision = str(resolution.get("decision") or "clarify_missing_metric_or_query_operation")
        status = "blocked"
    elif resolution.get("status") == "ambiguous_candidates":
        decision = str(resolution.get("decision") or "clarify_before_any_execution")
        status = "blocked"
    elif not top.get("published_runtime_asset"):
        decision = "do_not_execute_until_published"
        status = "blocked"
    elif unreviewed_close:
        decision = "clarify_reviewed_asset_vs_unreviewed_candidate"
        status = "blocked"
        disposition = "clarify"
    elif not reviewed_asset_set_connected:
        decision = "clarify_missing_reviewed_relationship"
        status = "blocked"
        disposition = "clarify"
    else:
        decision = "reviewed_candidate_set_admitted"
        status = "admitted"
        disposition = "execute"

    # Keep the candidates that actually form the reviewed execution set first
    # in the console evidence. The resolver still retains close unreviewed
    # candidates for transparency, but they must not visually look like the
    # assets that admitted execution.
    admitted_ids = {str(item.get("candidate_id") or "") for item in admitted_candidates}
    display_candidates = [
        *admitted_candidates,
        *[
            item
            for item in candidates
            if str(item.get("candidate_id") or "") not in admitted_ids
        ],
    ]

    return {
        "schema": "gda.abu-dhabi-execution-admission.v1",
        "scope": scope,
        "status": status,
        "decision": decision,
        "disposition": disposition,
        "runtime_admitted": status == "admitted",
        "required_capabilities": [
            capability
            for _requirement, required_capabilities, _disposition in all_requirements
            for capability in required_capabilities
        ],
        "reviewed_candidate_capabilities": sorted(available_capabilities),
        "candidate_resolution": {
            "status": resolution.get("status"),
            "decision": resolution.get("decision"),
            "candidate_count_considered": resolution.get("candidate_count_considered"),
            "reviewed_asset_set_candidate_ids": list(
                resolution.get("reviewed_asset_set_candidate_ids") or []
            ),
            "reviewed_asset_set_connected": reviewed_asset_set_connected,
            "candidates": [
                {
                    "business_label": item.get("business_label"),
                    "asset_state": item.get("asset_state"),
                    "published_runtime_asset": bool(item.get("published_runtime_asset")),
                    "score": item.get("score"),
                    "matched_business_terms": list(item.get("matched_business_terms") or []),
                }
                for item in display_candidates[:8]
            ],
        },
    }


def _admission_rejection(scope: str, admission: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "gda.abu-dhabi-nl2semantic2sql-console-result.v1",
        "scope": scope,
        "status": "rejected",
        "outcome": admission.get("disposition", "clarify"),
        "reason": admission.get("decision"),
        "error": None,
        "planner": {
            "route": "semantic_candidate_admission",
            "llm_invoked": False,
        },
        "source_rows_persisted": False,
        "admission": admission,
        "query": {},
        "result": {},
    }


async def _run_scope(
    scope: str,
    question: str,
    *,
    execution_profile: str = "baseline_sql",
    verify_platform_schema: bool = True,
) -> dict[str, Any]:
    """Run an admitted scope using an internal route profile.

    The public endpoint deliberately leaves this argument inaccessible and
    therefore always uses the baseline. The evaluator imports this internal
    boundary to apply the same admission checks before comparing routes.
    """

    if execution_profile not in {"baseline_sql", "semantic_ir_experimental"}:
        raise ValueError("unsupported execution profile")
    from ..governed_virtual_nl2sql import detect_question_language

    language = detect_question_language(question)
    owner = os.environ.get("GDA_ABU_DHABI_SOURCE_OWNER", "abu-dhabi-site-operator")
    started = time.perf_counter()

    def with_total_timing(report: dict[str, Any]) -> dict[str, Any]:
        timing = report.setdefault("timing", {})
        timing.setdefault("total_ms", round((time.perf_counter() - started) * 1000, 3))
        return report

    if scope == "liveability":
        from ..liveability_nl2sql import LiveabilityNL2SQLRequest, run_liveability_nl2sql_request

        report = await run_liveability_nl2sql_request(
            LiveabilityNL2SQLRequest(question, language, True),
            owner=owner,
            verify_platform_schema=verify_platform_schema,
            execution_profile=execution_profile,
        )
        return _compact_single_source_report(scope, with_total_timing(report))
    if scope == "makani":
        from ..makani_nl2sql import MakaniNL2SQLRequest, run_makani_nl2sql_request

        report = await run_makani_nl2sql_request(
            MakaniNL2SQLRequest(question, language, True),
            owner=owner,
            verify_platform_schema=verify_platform_schema,
            execution_profile=execution_profile,
        )
        return _compact_single_source_report(scope, with_total_timing(report))
    if scope == "federated":
        from ..abu_dhabi_federated_nl2sql import (
            AbuDhabiFederatedRequest,
            run_abu_dhabi_federated_request,
        )

        report = await run_abu_dhabi_federated_request(
            AbuDhabiFederatedRequest(question, language, True),
            owner=owner,
            verify_platform_schema=verify_platform_schema,
        )
        return _compact_federated_report(with_total_timing(report))
    raise ValueError("scope must be liveability, makani, or federated")


async def product_evidence(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    try:
        return JSONResponse(build_product_evidence(username))
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception("Abu Dhabi NL2Semantic2SQL product evidence is unavailable")
        return JSONResponse(
            {"error": "Product evidence artifacts are unavailable"}, status_code=503
        )


async def product_semantic_configuration(request: Request) -> JSONResponse:
    """Return a complete, paged semantic-layer inspection read model."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        scope = str(request.query_params.get("scope") or "").strip()
        section = str(request.query_params.get("section") or "summary").strip()
        search = str(request.query_params.get("search") or "").strip()
        include_candidates = str(
            request.query_params.get("include_candidates") or ""
        ).casefold() in {"1", "true", "yes"}
        try:
            offset = int(request.query_params.get("offset") or "0")
            limit = int(
                request.query_params.get("limit")
                or str(_SEMANTIC_CONFIG_PAGE_LIMIT)
            )
        except ValueError as exc:
            raise ValueError("semantic_configuration_pagination_invalid") from exc
        return JSONResponse(
            _semantic_configuration_view(
                scope,
                section=section,
                offset=offset,
                limit=limit,
                search=search,
                include_candidates=include_candidates,
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.exception("Abu Dhabi semantic configuration unavailable")
        code = (
            str(exc)
            if str(exc).startswith("semantic_configuration_")
            else "semantic_configuration_unavailable"
        )
        status_code = 400 if code != "semantic_configuration_unavailable" else 503
        return JSONResponse({"error": code}, status_code=status_code)


async def product_execute(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict) or set(body) - {"scope", "question"}:
        return JSONResponse(
            {"error": "Request must contain only scope and question"}, status_code=400
        )
    scope = str(body.get("scope") or "").strip()
    question = str(body.get("question") or "").strip()
    if scope not in {"liveability", "makani", "federated"}:
        return JSONResponse({"error": "Unsupported query scope"}, status_code=400)
    if not question or len(question) > _MAX_QUESTION_LENGTH:
        return JSONResponse(
            {"error": f"question must be 1 to {_MAX_QUESTION_LENGTH} characters"},
            status_code=400,
        )
    try:
        admission = _execution_admission(scope, question)
        if not admission.get("runtime_admitted"):
            return JSONResponse(_admission_rejection(scope, admission))
        result = await asyncio.wait_for(_run_scope(scope, question), timeout=190)
        result["admission"] = admission
        return JSONResponse(result)
    except TimeoutError:
        return JSONResponse(
            {"error": "Governed query timed out", "code": "governed_query_timeout"},
            status_code=504,
        )
    except Exception:
        logger.exception("Abu Dhabi NL2Semantic2SQL execution failed for scope=%s", scope)
        return JSONResponse(
            {"error": "Governed query could not be completed", "code": "governed_query_failed"},
            status_code=502,
        )


async def product_resolve_semantic_candidates(request: Request) -> JSONResponse:
    """Run the non-executing business-language table/asset selection stage."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict) or set(body) - {"scope", "question"}:
        return JSONResponse(
            {"error": "Request must contain only scope and question"}, status_code=400
        )
    scope = str(body.get("scope") or "").strip()
    question = str(body.get("question") or "").strip()
    if scope not in {"liveability", "makani"}:
        return JSONResponse(
            {"error": "Candidate selection currently supports one source at a time"},
            status_code=400,
        )
    if not question or len(question) > _MAX_QUESTION_LENGTH:
        return JSONResponse(
            {"error": f"question must be 1 to {_MAX_QUESTION_LENGTH} characters"},
            status_code=400,
        )
    try:
        return JSONResponse(resolve_semantic_candidates(scope, question))
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception("Abu Dhabi semantic candidate resolution failed for scope=%s", scope)
        return JSONResponse(
            {"error": "Semantic candidate evidence is unavailable"}, status_code=503
        )


def get_abu_dhabi_nl2sql_product_routes() -> list[Route]:
    return [
        Route(
            "/api/abu-dhabi/nl2semantic2sql/evidence",
            product_evidence,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/nl2semantic2sql/semantic-configuration",
            product_semantic_configuration,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/nl2semantic2sql/execute",
            product_execute,
            methods=["POST"],
        ),
        Route(
            "/api/abu-dhabi/nl2semantic2sql/semantic-candidates/resolve",
            product_resolve_semantic_candidates,
            methods=["POST"],
        ),
    ]


__all__ = [
    "build_product_evidence",
    "get_abu_dhabi_nl2sql_product_routes",
    "product_evidence",
    "product_semantic_configuration",
    "product_execute",
    "product_resolve_semantic_candidates",
    "resolve_semantic_candidates",
]
