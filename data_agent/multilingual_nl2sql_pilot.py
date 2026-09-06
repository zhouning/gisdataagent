"""Contract-driven multilingual NL2SQL pilot for governed virtual sources."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

PILOT_SCHEMA = "gda.multilingual-nl2sql-pilot-report.v1"
PROMPT_VERSION = "abu-dhabi-contract-nl2sql-v2"
SUPPORTED_LANGUAGES = ("zh", "en", "ar")


class SemanticPlanProposal(BaseModel):
    """Semantic plan fields required before SQL is eligible for execution."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["aggregate"]
    entity: str = Field(min_length=1)
    physical_binding: str = Field(min_length=3)
    dimensions: list[str] = Field(min_length=1)
    metrics: list[str] = Field(min_length=1)
    network_type_constant: str | None = Field(default=None, min_length=1)


class NL2SQLProposal(BaseModel):
    """Structured output contract returned by the ADK model."""

    model_config = ConfigDict(extra="forbid")

    language: Literal["zh", "en", "ar"]
    semantic_plan: SemanticPlanProposal
    sql: str = Field(min_length=20)

    @field_validator("sql")
    @classmethod
    def _strip_sql(cls, value: str) -> str:
        return value.strip()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load JSON contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON contract must be an object: {path}")
    return value


def _resolve_contract_path(path_value: str, contract_path: Path) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    repository_candidate = Path(__file__).resolve().parents[1] / candidate
    if repository_candidate.exists():
        return repository_candidate
    return contract_path.parent / candidate


def _validate_bundle(
    contract: dict[str, Any],
    semantic_layer: dict[str, Any],
    *,
    contract_path: Path,
    source_id: int,
) -> dict[str, Any]:
    if contract.get("schema") != "gda.nl2sql-gold-result-contract.v1":
        raise ValueError("Unsupported Gold result contract schema")
    if semantic_layer.get("schema") != "gda.multilingual-virtual-semantic-layer.v1":
        raise ValueError("Unsupported multilingual semantic layer schema")

    contract_id = str(contract.get("contract_id") or "")
    source_contract = contract.get("source_contract") or {}
    source_binding = semantic_layer.get("source_binding") or {}
    if int(source_contract.get("source_id") or -1) != source_id:
        raise ValueError("Gold contract source_id does not match the requested source")
    if int(source_binding.get("source_id") or -1) != source_id:
        raise ValueError("Semantic layer source_id does not match the requested source")
    if source_contract.get("discovery_fingerprint") != source_binding.get("discovery_fingerprint"):
        raise ValueError("Gold contract and semantic layer discovery fingerprints differ")
    if source_contract.get("semantic_version") != semantic_layer.get("semantic_version"):
        raise ValueError("Gold contract and semantic layer versions differ")

    activation_gate = semantic_layer.get("activation_gate") or {}
    if activation_gate.get("active_for_free_form_nl2sql") is not False:
        raise ValueError("Pilot requires free-form NL2SQL to remain disabled")
    if contract_id not in (activation_gate.get("allowed_contract_ids") or []):
        raise ValueError("Gold contract is not allowed by the semantic activation gate")

    query_contract = contract.get("query") or {}
    gold_path_value = str(query_contract.get("path") or "")
    if not gold_path_value:
        raise ValueError("Gold contract does not identify its SQL artifact")
    gold_sql_path = _resolve_contract_path(gold_path_value, contract_path)
    try:
        gold_sql_bytes = gold_sql_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read Gold SQL artifact: {exc}") from exc
    if _sha256_bytes(gold_sql_bytes) != query_contract.get("sha256"):
        raise ValueError("Gold SQL checksum does not match the frozen contract")
    if query_contract.get("read_only") is not True:
        raise ValueError("Gold contract is not marked read-only")
    if query_contract.get("schema_qualified") is not True:
        raise ValueError("Gold contract is not marked schema-qualified")

    questions = contract.get("questions") or {}
    missing_languages = [lang for lang in SUPPORTED_LANGUAGES if not questions.get(lang)]
    if missing_languages:
        raise ValueError(
            "Gold contract is missing question languages: " + ", ".join(missing_languages)
        )

    expected_result = contract.get("expected_result") or {}
    expected_columns = expected_result.get("columns") or []
    if not expected_columns or not all(isinstance(value, str) for value in expected_columns):
        raise ValueError("Gold contract must declare ordered expected result columns")

    generation_rules = query_contract.get("generation_rules") or []
    if generation_rules and not all(
        isinstance(value, str) and value.strip() for value in generation_rules
    ):
        raise ValueError("Gold SQL generation rules must be non-empty strings")

    answer_contract = contract.get("answer_contract")
    if answer_contract is not None:
        if not isinstance(answer_contract, dict):
            raise ValueError("Gold answer contract must be an object")
        templates = answer_contract.get("templates") or {}
        missing_templates = [lang for lang in SUPPORTED_LANGUAGES if not templates.get(lang)]
        if missing_templates:
            raise ValueError(
                "Gold answer contract is missing templates: " + ", ".join(missing_templates)
            )
        metric_names: set[str] = set()
        for metric in answer_contract.get("summary_metrics") or []:
            if not isinstance(metric, dict):
                raise ValueError("Gold answer summary metrics must be objects")
            name = str(metric.get("name") or "")
            column = str(metric.get("column") or "")
            aggregation = str(metric.get("aggregation") or "")
            if not name or not column:
                raise ValueError("Gold answer summary metrics require name and column")
            if name in metric_names:
                raise ValueError(f"Duplicate Gold answer summary metric: {name}")
            if column not in expected_columns:
                raise ValueError(
                    f"Gold answer summary column is absent from expected result: {column}"
                )
            if aggregation not in {"sum", "min", "max", "mean", "first", "count"}:
                raise ValueError(f"Unsupported Gold answer summary aggregation: {aggregation}")
            metric_names.add(name)

    semantic_plan = contract.get("semantic_plan") or {}
    physical_binding = str(semantic_plan.get("physical_binding") or "")
    table_binding = next(
        (
            item
            for item in semantic_layer.get("table_bindings") or []
            if item.get("physical_table") == physical_binding
        ),
        None,
    )
    if not table_binding:
        raise ValueError("Gold physical binding is absent from the semantic layer")
    return {
        "contract_id": contract_id,
        "source_contract": source_contract,
        "source_binding": source_binding,
        "semantic_plan": semantic_plan,
        "table_binding": table_binding,
        "questions": questions,
        "query_contract": query_contract,
        "expected_result": expected_result,
        "answer_contract": answer_contract,
    }


def _validate_registered_source(
    source: dict[str, Any],
    discovery: dict[str, Any],
    bundle: dict[str, Any],
) -> None:
    if source.get("source_type") != "database" or not source.get("enabled"):
        raise ValueError("Registered database source is unavailable or disabled")
    if discovery.get("discovery_status") != "succeeded":
        raise ValueError("Registered source discovery has not succeeded")
    expected_fingerprint = bundle["source_contract"]["discovery_fingerprint"]
    if discovery.get("discovery_fingerprint") != expected_fingerprint:
        raise ValueError("Registered source discovery fingerprint has drifted")

    snapshot = discovery.get("discovery_snapshot") or {}
    expected_database = bundle["source_contract"].get("database_name")
    if snapshot.get("database_name") != expected_database:
        raise ValueError("Registered source database does not match the Gold contract")
    expected_schemas = [bundle["source_contract"].get("authorized_schema")]
    actual_schemas = list((source.get("query_config") or {}).get("allowed_schemas") or [])
    if actual_schemas != expected_schemas:
        raise ValueError("Registered source schema whitelist does not match the Gold contract")
    if list(snapshot.get("authorized_schemas") or []) != expected_schemas:
        raise ValueError("Discovery snapshot schema scope does not match the Gold contract")


def _build_instruction(bundle: dict[str, Any]) -> str:
    semantic_plan = bundle["semantic_plan"]
    table_binding = bundle["table_binding"]
    field_bindings = {
        item["semantic_field"]: item["physical_field"]
        for item in table_binding.get("fields") or []
        if item.get("semantic_field") and item.get("physical_field")
    }
    planning_contract = {
        "intent": semantic_plan.get("intent"),
        "entity": semantic_plan.get("entity"),
        "physical_binding": semantic_plan.get("physical_binding"),
        "dimensions": semantic_plan.get("dimensions"),
        "metrics": semantic_plan.get("metrics"),
        "network_type_constant": semantic_plan.get("network_type_constant"),
        "physical_fields": field_bindings,
        "output_columns": bundle["expected_result"]["columns"],
    }
    contract_json = json.dumps(
        planning_contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    generation_rules = list(bundle["query_contract"].get("generation_rules") or [])
    if not generation_rules:
        generation_rules = [
            "Reference only layer.st_pipeline and schema-qualify it.",
            "Return columns in this order: network_type, segment_material, "
            "segment_status, segment_count, missing_diameter_count.",
            "network_type is the literal stormwater.",
            "Group by pipe_material and status after trimming whitespace. Represent "
            "NULL or blank values as __MISSING__; do not normalize, translate, or "
            "merge other source values.",
            "segment_count counts source records in each group.",
            "missing_diameter_count counts only records where pipe_diameter IS NULL.",
            "Sort by segment_count descending, then segment_material and segment_status ascending.",
        ]
    rendered_rules = "\n".join(f"- {rule}" for rule in generation_rules)
    return f"""You are the governed GIS Data Agent NL2SQL planner.

This is a contract-bound pilot, not free-form NL2SQL. Return only the structured output
required by the response schema. Detect whether the question is Chinese, English, or
Arabic and set language to zh, en, or ar. Copy the semantic plan exactly from the
contract below and generate one PostgreSQL SELECT statement implementing it.

<planning_contract>{contract_json}</planning_contract>

SQL requirements:
{rendered_rules}
- Do not use joins, SELECT *, comments, multiple statements, locking, DDL, DML,
  system catalogs, or unqualified physical tables.
- Verify the semantic plan and SQL against every requirement before returning.
"""


def _strip_json_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


async def _generate_proposal(
    model: Any,
    *,
    instruction: str,
    question: str,
    language: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = LlmAgent(
        name="AbuDhabiContractNL2SQL",
        model=model,
        instruction=instruction,
        output_schema=NL2SQLProposal,
        mode="chat",
    )
    run_id = f"contract-{language}-{uuid.uuid4().hex}"
    runner = Runner(
        agent=agent,
        app_name="abu_dhabi_multilingual_nl2sql_pilot",
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )
    message = types.Content(role="user", parts=[types.Part(text=question)])
    text_candidates: list[str] = []
    model_versions: set[str] = set()
    usage = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    started = time.perf_counter()
    async with asyncio.timeout(timeout_seconds):
        async for event in runner.run_async(
            user_id="abu-dhabi-site-pilot",
            session_id=run_id,
            new_message=message,
        ):
            event_usage = getattr(event, "usage_metadata", None)
            if event_usage:
                usage["input_tokens"] += int(getattr(event_usage, "prompt_token_count", 0) or 0)
                usage["output_tokens"] += int(
                    getattr(event_usage, "candidates_token_count", 0) or 0
                )
                usage["reasoning_tokens"] += int(
                    getattr(event_usage, "thoughts_token_count", 0) or 0
                )
            version = getattr(event, "model_version", None)
            if version:
                model_versions.add(str(version))
            content = getattr(event, "content", None)
            for part in getattr(content, "parts", None) or []:
                if part.text:
                    text_candidates.append(part.text)

    proposal = None
    for candidate in reversed(text_candidates):
        try:
            proposal = NL2SQLProposal.model_validate_json(_strip_json_fence(candidate))
            break
        except ValueError:
            continue
    if proposal is None:
        raise ValueError("ADK model did not return the required structured proposal")
    return {
        "proposal": proposal,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "usage": usage,
        "model_versions": sorted(model_versions),
    }


def _proposal_violations(
    proposal: NL2SQLProposal,
    *,
    language: str,
    expected_plan: dict[str, Any],
) -> list[str]:
    violations = []
    if proposal.language != language:
        violations.append("response_language_mismatch")
    actual_plan = proposal.semantic_plan.model_dump()
    for field in SemanticPlanProposal.model_fields:
        if actual_plan.get(field) != expected_plan.get(field):
            violations.append(f"semantic_plan_mismatch:{field}")
    return violations


def _validate_sql_binding(sql: str, bundle: dict[str, Any]) -> None:
    from sqlglot import exp, parse_one

    expression = parse_one(sql.rstrip(";").strip(), read="postgres")
    cte_names = {
        str(cte.alias_or_name).casefold()
        for cte in expression.find_all(exp.CTE)
        if cte.alias_or_name
    }
    physical_tables = {
        f"{table.db}.{table.name}"
        for table in expression.find_all(exp.Table)
        if str(table.name or "").casefold() not in cte_names
    }
    expected_table = str(bundle["semantic_plan"]["physical_binding"])
    if physical_tables != {expected_table}:
        raise ValueError("Generated SQL does not use exactly the contracted physical table")
    for select in expression.find_all(exp.Select):
        if any(
            isinstance(projection, exp.Star)
            or (isinstance(projection, exp.Column) and projection.is_star)
            for projection in select.expressions
        ):
            raise ValueError("Generated SQL must not project wildcard columns")

    allowed_columns = {
        item["physical_field"]
        for item in bundle["table_binding"].get("fields") or []
        if item.get("physical_field")
    }
    allowed_columns.update(bundle["expected_result"].get("columns") or [])
    referenced_columns = {str(column.name) for column in expression.find_all(exp.Column)}
    unexpected_columns = sorted(referenced_columns - allowed_columns)
    if unexpected_columns:
        raise ValueError(
            "Generated SQL references fields outside the semantic binding: "
            + ", ".join(unexpected_columns)
        )


def _legacy_answer_contract() -> dict[str, Any]:
    return {
        "summary_metrics": [
            {
                "name": "segment_count",
                "column": "segment_count",
                "aggregation": "sum",
            },
            {
                "name": "missing_diameter_count",
                "column": "missing_diameter_count",
                "aggregation": "sum",
            },
        ],
        "templates": {
            "zh": (
                "查询成功：按管材和状态得到 {row_count} 个分组，共计 {segment_count} "
                "条雨水管线线段，其中 {missing_diameter_count} 条记录缺少管径。"
                "结果与冻结 Gold 契约一致。"
            ),
            "en": (
                "Query completed: {row_count} pipe-material/status groups contain "
                "{segment_count} stormwater segments, and {missing_diameter_count} "
                "records have no pipe diameter. The result matches the frozen Gold "
                "contract."
            ),
            "ar": (
                "اكتمل الاستعلام: تضم {row_count} مجموعة حسب مادة الأنبوب والحالة ما "
                "مجموعه {segment_count} مقطعاً لشبكة تصريف مياه الأمطار، وتفتقد "
                "{missing_diameter_count} سجلات إلى قطر الأنبوب. تتطابق النتيجة مع "
                "عقد Gold المجمّد."
            ),
        },
    }


def _aggregate_summary(result: Any, answer_contract: dict[str, Any]) -> dict[str, Any]:
    metrics = list(answer_contract.get("summary_metrics") or [])
    required = {str(metric["column"]) for metric in metrics}
    columns = {str(value) for value in result.columns}
    if not required.issubset(columns):
        raise ValueError("Query result lacks contracted aggregate columns")
    summary: dict[str, Any] = {}
    for metric in metrics:
        name = str(metric["name"])
        column = str(metric["column"])
        aggregation = str(metric["aggregation"])
        series = result[column]
        if aggregation == "sum":
            value = series.sum()
        elif aggregation == "min":
            value = series.min()
        elif aggregation == "max":
            value = series.max()
        elif aggregation == "mean":
            value = series.mean()
        elif aggregation == "first":
            value = None if series.empty else series.iloc[0]
        else:
            value = series.count()
        if hasattr(value, "item"):
            value = value.item()
        summary[name] = value
    return summary


def _same_language_answer(
    language: str,
    *,
    passed: bool,
    row_count: int | None = None,
    summary: dict[str, Any] | None = None,
    answer_contract: dict[str, Any] | None = None,
) -> str:
    if not passed:
        return {
            "zh": "本次问数未通过冻结契约校验，未形成可采信的数据答案。",
            "en": (
                "This query did not pass the frozen contract checks, so no trusted "
                "data answer was produced."
            ),
            "ar": "لم يجتز هذا الاستعلام فحوص العقد المجمّد، لذلك لم يتم إصدار إجابة بيانات موثوقة.",
        }[language]
    assert row_count is not None and summary is not None
    resolved_contract = answer_contract or _legacy_answer_contract()
    values = {"row_count": row_count, **summary}
    try:
        return str(resolved_contract["templates"][language]).format(**values)
    except KeyError as exc:
        raise ValueError(f"Gold answer template references an unknown value: {exc}") from exc


def _redact_error(value: Any) -> str:
    message = str(value)
    for name in (
        "OPENAI_API_KEY",
        "GDA_LLM_API_KEY",
        "GDA_VSOURCE_PASSWORD",
        "CHAINLIT_AUTH_SECRET",
        "GDA_CONTROL_PLANE_ENCRYPTION_SECRET",
    ):
        secret = os.environ.get(name, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", message)
    return message[:500]


@contextmanager
def _reasoning_effort(value: str):
    name = "GDA_OPENAI_REASONING_EFFORT"
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


async def run_multilingual_pilot(
    *,
    contract_path: Path,
    semantic_layer_path: Path,
    source_id: int,
    owner: str,
    model_name: str = "gpt-5.1",
    reasoning_effort: str = "medium",
    timeout_seconds: int = 180,
    languages: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run one frozen contract through ADK.

    The CLI keeps the default three-language run. The Chainlit controlled
    Liveability entry point may request one language so a human question does
    not silently trigger two unrelated model calls.
    """
    requested_languages = SUPPORTED_LANGUAGES if languages is None else tuple(languages)
    invalid_languages = [
        language for language in requested_languages if language not in SUPPORTED_LANGUAGES
    ]
    if invalid_languages:
        raise ValueError("Unsupported pilot language(s): " + ", ".join(invalid_languages))
    if not requested_languages:
        raise ValueError("At least one pilot language is required")

    from .migration_runner import verify_schema_state
    from .model_gateway import create_model
    from .virtual_sources import (
        get_virtual_source,
        get_virtual_source_discovery,
        query_virtual_source,
    )

    verify_schema_state()
    contract = _load_json(contract_path)
    semantic_layer = _load_json(semantic_layer_path)
    bundle = _validate_bundle(
        contract,
        semantic_layer,
        contract_path=contract_path,
        source_id=source_id,
    )
    discovery = get_virtual_source_discovery(source_id, owner)
    source = get_virtual_source(source_id, owner)
    if discovery is None or source is None:
        raise ValueError("Registered source or discovery evidence is not visible to this owner")
    _validate_registered_source(source, discovery, bundle)

    instruction = _build_instruction(bundle)
    with _reasoning_effort(reasoning_effort):
        model = create_model(model_name)
    model_route = str(getattr(model, "model", model_name))
    query_limit = int(bundle["query_contract"].get("bounded_limit") or 1000)
    expected_result = bundle["expected_result"]
    answer_contract = bundle["answer_contract"] or _legacy_answer_contract()
    runs = []

    for language in requested_languages:
        question = str(bundle["questions"][language])
        run: dict[str, Any] = {
            "language": language,
            "question": question,
            "status": "failed",
            "same_language_answer": _same_language_answer(language, passed=False),
            "source_rows_persisted": False,
        }
        try:
            generation = await _generate_proposal(
                model,
                instruction=instruction,
                question=question,
                language=language,
                timeout_seconds=timeout_seconds,
            )
            proposal = generation["proposal"]
            plan = proposal.semantic_plan.model_dump()
            violations = _proposal_violations(
                proposal,
                language=language,
                expected_plan=bundle["semantic_plan"],
            )
            run.update(
                {
                    "latency_ms": generation["latency_ms"],
                    "usage": generation["usage"],
                    "observed_model_versions": generation["model_versions"],
                    "proposal": {
                        "language": proposal.language,
                        "semantic_plan": plan,
                        "semantic_plan_fingerprint": _sha256_json(plan),
                        "sql": proposal.sql,
                        "sql_sha256": _sha256_bytes(proposal.sql.encode("utf-8")),
                    },
                    "semantic_contract_violations": violations,
                }
            )
            if violations:
                runs.append(run)
                continue

            from .connectors.database import validate_database_read_query

            _validate_sql_binding(proposal.sql, bundle)
            validate_database_read_query(
                proposal.sql,
                source.get("query_config") or {},
                limit=query_limit,
            )
            run["static_validation"] = {
                "passed": True,
                "schema_whitelist_enforced": True,
                "single_read_statement_enforced": True,
                "semantic_table_binding_enforced": True,
                "bounded_limit": query_limit,
            }
            result = await query_virtual_source(
                source,
                limit=query_limit,
                extra_params={"sql": proposal.sql, "geom_column": ""},
                register_result=False,
            )
            if isinstance(result, dict):
                raise RuntimeError(result.get("message", "Governed database query failed"))

            from .query_result_contract import tabular_result_contract

            evidence = tabular_result_contract(result)
            aggregate_summary = _aggregate_summary(result, answer_contract)
            columns_match = evidence["columns"] == expected_result.get("columns")
            row_count_match = evidence["row_count"] == expected_result.get("row_count")
            fingerprint_match = evidence["result_fingerprint"] == expected_result.get(
                "ordered_result_fingerprint"
            )
            passed = bool(columns_match and row_count_match and fingerprint_match)
            run.update(
                {
                    "status": "passed" if passed else "failed",
                    "execution": {
                        **evidence,
                        "aggregate_summary": aggregate_summary,
                        "columns_match": columns_match,
                        "row_count_match": row_count_match,
                        "gold_result_fingerprint_match": fingerprint_match,
                    },
                    "same_language_answer": _same_language_answer(
                        language,
                        passed=passed,
                        row_count=evidence["row_count"],
                        summary=aggregate_summary,
                        answer_contract=answer_contract,
                    ),
                }
            )
        except Exception as exc:
            run["error"] = _redact_error(exc)
        runs.append(run)

    passed_runs = [run for run in runs if run["status"] == "passed"]
    plan_fingerprints = {
        run.get("proposal", {}).get("semantic_plan_fingerprint") for run in passed_runs
    }
    result_fingerprints = {
        run.get("execution", {}).get("result_fingerprint") for run in passed_runs
    }
    multilingual_consistency = bool(
        len(passed_runs) == len(requested_languages)
        and len(plan_fingerprints) == 1
        and len(result_fingerprints) == 1
    )
    return {
        "schema": PILOT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if multilingual_consistency else "failed",
        "scope": "single_frozen_contract_pipeline_validation_only",
        "requested_languages": list(requested_languages),
        "benchmark_accuracy_claim": False,
        "model": {
            "requested": model_name,
            "adk_route": model_route,
            "reasoning_effort": reasoning_effort,
            "official_model_reference": "https://developers.openai.com/api/docs/models/gpt-5.1",
        },
        "prompt": {
            "version": PROMPT_VERSION,
            "sha256": _sha256_bytes(instruction.encode("utf-8")),
        },
        "contract": {
            "contract_id": bundle["contract_id"],
            "contract_status": contract.get("status"),
            "semantic_version": semantic_layer.get("semantic_version"),
            "ontology_overlay_id": bundle["source_contract"].get("ontology_overlay_id"),
            "arabic_question_status": contract.get("arabic_question_status"),
        },
        "source": {
            "source_id": source_id,
            "source_name": source.get("source_name"),
            "database_name": (discovery.get("discovery_snapshot") or {}).get("database_name"),
            "authorized_schemas": list(
                (source.get("query_config") or {}).get("allowed_schemas") or []
            ),
            "discovery_fingerprint": discovery.get("discovery_fingerprint"),
            "execution_mode": "registered_governed_virtual_read_only",
        },
        "metrics": {
            "language_run_count": len(runs),
            "passed_language_count": len(passed_runs),
            "contract_result_match_rate": len(passed_runs) / len(runs),
            "multilingual_consistency_passed": multilingual_consistency,
        },
        "limitations": [
            "This is one frozen contract repeated in three languages, not a benchmark "
            "accuracy result.",
            "Arabic terminology remains provisional pending customer confirmation.",
            "Free-form NL2SQL remains disabled.",
            "No source rows are persisted in this report.",
        ],
        "runs": runs,
    }


def _load_environment() -> None:
    configured = os.environ.get("GDA_OPERATOR_ENV_FILE")
    env_path = Path(configured) if configured else Path(__file__).with_name(".env")
    if env_path.exists():
        load_dotenv(env_path, override=False)
    secret_path = Path(__file__).with_name(".vsource-secret.env")
    if secret_path.exists():
        load_dotenv(secret_path, override=False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gda-nl2sql-pilot",
        description="Run a frozen multilingual NL2SQL contract through ADK and a virtual source.",
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--semantic-layer", type=Path, required=True)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--model", default="gpt-5.1")
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_environment()
    args = _parser().parse_args(argv)
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be positive")
    try:
        report = asyncio.run(
            run_multilingual_pilot(
                contract_path=args.contract,
                semantic_layer_path=args.semantic_layer,
                source_id=args.source_id,
                owner=args.owner,
                model_name=args.model,
                reasoning_effort=args.reasoning_effort,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except Exception as exc:
        report = {
            "schema": PILOT_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "error",
            "stage": "pilot_preflight",
            "message": _redact_error(exc),
        }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        console_payload = {
            "status": report.get("status"),
            "output": str(args.output),
            "metrics": report.get("metrics"),
            "message": report.get("message"),
        }
    else:
        console_payload = report
    print(json.dumps(console_payload, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
