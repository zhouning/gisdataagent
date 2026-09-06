"""Governed cross-source NL2Semantic2SQL for Liveability and Makani."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .governed_virtual_nl2sql import (
    detect_question_language,
    run_governed_metric_contract,
)
from .semantic_query_ir import build_federated_semantic_plan_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
FEDERATED_V1_SEMANTIC_PATH = (
    REPO_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "abu_dhabi_federated_semantic_layer_v1.json"
)
FEDERATED_V3_SEMANTIC_PATH = (
    REPO_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "abu_dhabi_federated_semantic_layer_v3.json"
)
FEDERATED_V4_SEMANTIC_PATH = (
    REPO_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "abu_dhabi_federated_semantic_layer_v4.json"
)
FEDERATED_V5_SEMANTIC_PATH = (
    REPO_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "abu_dhabi_federated_semantic_layer_v5.json"
)
FEDERATED_SEMANTIC_PATH = FEDERATED_V5_SEMANTIC_PATH
SOURCE_OWNER = "abu-dhabi-site-operator"
PLANNER_VERSION = "abu-dhabi-federated-contract-planner-v2"
# Retained for callers of the previous public constant. The v2 route has no LLM prompt.
PROMPT_VERSION = PLANNER_VERSION
_PREFIX_RE = re.compile(
    r"^\s*@(?:AbuDhabi|DMTFederated|跨库问数|阿布扎比跨库)"
    r"(?:\s+|$)(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_DIRECT_CROSS_SOURCE_LINK_RE = re.compile(
    r"(?:\b(?:join|link|match|merge|union)\b|"
    r"(?:直接)?(?:关联|连接|匹配|合并)|"
    r"(?:ربط|وصل|مطابقة|دمج))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AbuDhabiFederatedRequest:
    question: str
    language: str
    explicit_scope_selection: bool
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return bool(self.question) and self.error is None


def resolve_abu_dhabi_federated_request(
    value: str,
    *,
    continue_selected_scope: bool = False,
) -> AbuDhabiFederatedRequest | None:
    text = str(value or "")
    match = _PREFIX_RE.match(text)
    explicit = match is not None
    if explicit:
        question = match.group(1).strip().lstrip(":：").strip()
    elif continue_selected_scope and not text.lstrip().startswith("@"):
        question = text.strip()
    else:
        return None
    language = detect_question_language(question or text)
    if not question:
        return AbuDhabiFederatedRequest(
            question="",
            language=language,
            explicit_scope_selection=explicit,
            error="empty_question",
        )
    return AbuDhabiFederatedRequest(
        question=question,
        language=language,
        explicit_scope_selection=explicit,
    )


def _load_federated_semantic_layer(path: Path = FEDERATED_SEMANTIC_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "gda.federated-virtual-semantic-layer.v1":
        raise ValueError("federated_semantic_layer_invalid")
    gate = payload.get("activation_gate") or {}
    if gate.get("active") is not True:
        raise ValueError("federated_semantic_layer_inactive")
    if gate.get("allow_cross_database_sql") is not False:
        raise ValueError("cross_database_sql_must_be_disabled")
    if gate.get("allow_cross_source_join") is not False:
        raise ValueError("cross_source_join_must_be_disabled")
    sources = payload.get("sources") or {}
    if set(sources) != {"liveability", "makani"}:
        raise ValueError("federated_source_set_invalid")
    for source in sources.values():
        path = REPO_ROOT / str(source.get("semantic_layer") or "")
        semantic = json.loads(path.read_text(encoding="utf-8"))
        binding = semantic.get("source_binding") or {}
        for key in (
            "source_id",
            "database_name",
            "discovery_fingerprint",
            "profile_fingerprint",
        ):
            if binding.get(key) != source.get(key):
                raise ValueError(f"federated_source_binding_drift:{key}")
        if list(binding.get("allowed_schemas") or []) != list(
            source.get("authorized_schemas") or []
        ):
            raise ValueError("federated_source_schema_drift")
    if payload.get("contract_format") == "metric_contract_refs_v1":
        if payload.get("benchmark_artifacts_embedded") is not False:
            raise ValueError("federated_benchmark_artifacts_must_be_external")
        for contract in payload.get("contracts") or []:
            if "questions" in contract:
                raise ValueError("federated_runtime_question_examples_forbidden")
            subplans = contract.get("subplans") or []
            if len(subplans) != 2:
                raise ValueError("federated_contract_requires_two_subplans")
            if {str(item.get("source") or "") for item in subplans} != set(sources):
                raise ValueError("federated_contract_source_scope_invalid")
            for subplan in subplans:
                if set(subplan) != {"source", "metric_contract_id"}:
                    raise ValueError("federated_subplan_must_only_reference_contract")
                if not str(subplan.get("metric_contract_id") or ""):
                    raise ValueError("federated_metric_contract_id_required")
    return payload


def _normalize_contract_text(value: str, language: str) -> str:
    text = str(value or "").casefold()
    if language != "ar":
        return text
    text = re.sub(r"[\u0640\u064b-\u065f\u0670]", "", text)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"}))
    # Restore the definite article after the common attached Arabic li- clitic:
    # للمرافق -> المرافق, وللمرافق -> والمرافق.
    return re.sub(r"(?<!\w)([وف]?)لل", r"\1ال", text)


def _match_contract(
    question: str,
    language: str,
    semantic: dict[str, Any],
) -> dict[str, Any] | None:
    normalized = _normalize_contract_text(question, language)
    matches = []
    for contract in semantic.get("contracts") or []:
        groups = ((contract.get("match") or {}).get("required_term_groups") or {}).get(
            language
        ) or []
        if groups and all(
            any(_normalize_contract_text(str(term), language) in normalized for term in group)
            for group in groups
        ):
            matches.append(contract)
    if len(matches) > 1:
        raise ValueError("ambiguous_federated_semantic_contract")
    return matches[0] if matches else None


def classify_federated_admission(
    question: str,
    language: str,
    semantic: dict[str, Any],
) -> dict[str, str | None]:
    """Classify a federated request before any source query is started.

    Approved contracts are intentionally narrow: each source may execute an
    independent aggregate, and the application can present the sections
    together. A direct entity association is refused; a request that does not
    identify an approved aggregate is a clarification, not an unsafe query.
    """

    contract = _match_contract(question, language, semantic)
    if contract is not None:
        return {
            "disposition": "execute",
            "reason": None,
            "contract_id": str(contract["contract_id"]),
        }
    if _DIRECT_CROSS_SOURCE_LINK_RE.search(question):
        return {
            "disposition": "refuse",
            "reason": "cross_source_direct_join_requested",
            "contract_id": None,
        }
    return {
        "disposition": "clarify",
        "reason": "clarify_reviewed_cross_source_aggregate_required",
        "contract_id": None,
    }


def build_federated_bundle_evidence(
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = [
        {
            "source": section["source"],
            "source_id": section["source_id"],
            "row_count": section["result"]["row_count"],
            "equivalence_fingerprint": (
                section["result"].get("equivalence_fingerprints") or {}
            ).get("unordered_position_numeric6_fingerprint"),
        }
        for section in sections
    ]
    encoded = json.dumps(
        ordered,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "section_count": len(ordered),
        "bundle_fingerprint": hashlib.sha256(encoded).hexdigest(),
        "sections": ordered,
    }


async def run_abu_dhabi_federated_request(
    request: AbuDhabiFederatedRequest,
    *,
    semantic_layer_path: Path = FEDERATED_SEMANTIC_PATH,
    owner: str = SOURCE_OWNER,
    model_name: str = "gpt-5.1",
    reasoning_effort: str = "medium",
    timeout_seconds: int = 180,
    verify_platform_schema: bool = True,
) -> dict[str, Any]:
    if not request.accepted:
        raise ValueError(request.error or "invalid_question")
    semantic = _load_federated_semantic_layer(Path(semantic_layer_path))
    admission = classify_federated_admission(
        request.question,
        request.language,
        semantic,
    )
    contract_id = admission.get("contract_id")
    contract = next(
        (
            item
            for item in semantic.get("contracts") or []
            if str(item.get("contract_id") or "") == contract_id
        ),
        None,
    )
    base = {
        "schema": "gda.federated-virtual-nl2sql-result.v1",
        "language": request.language,
        "question": request.question,
        "semantic_version": semantic["semantic_version"],
        "planner": {
            "version": PLANNER_VERSION,
            "route": "reviewed_federated_metric_contract",
            "llm_invoked": False,
        },
        "source_rows_persisted": False,
    }
    if contract is None:
        return {
            **base,
            "status": "rejected",
            "reason": admission["reason"],
            "outcome": admission["disposition"],
        }

    sources = semantic["sources"]

    from .migration_runner import verify_runtime_schema_state

    if verify_platform_schema:
        verify_runtime_schema_state(
            required_migrations=(
                "012_virtual_sources",
                "182_governed_virtual_source_discovery",
            )
        )

    async def execute(subplan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        source = sources[str(subplan["source"])]
        report = await run_governed_metric_contract(
            contract_id=str(subplan["metric_contract_id"]),
            question_context=request.question,
            language=request.language,
            semantic_layer_path=REPO_ROOT / str(source["semantic_layer"]),
            source_id=int(source["source_id"]),
            owner=owner,
            verify_platform_schema=False,
        )
        return subplan, report

    executions = await asyncio.gather(
        *(execute(subplan) for subplan in contract.get("subplans") or [])
    )
    if len(executions) != 2 or any(report.get("status") != "ok" for _, report in executions):
        failures = [
            {
                "source": str(subplan.get("source") or "unknown"),
                "status": str(report.get("status") or "error"),
                "reason": (
                    str(report.get("reason"))[:240] if report.get("reason") is not None else None
                ),
                "error": (
                    str(report.get("error"))[:240] if report.get("error") is not None else None
                ),
            }
            for subplan, report in executions
            if report.get("status") != "ok"
        ]
        return {
            **base,
            "status": "error",
            "contract": {"contract_id": contract["contract_id"]},
            "error": "federated_subquery_failed",
            "subquery_failures": failures,
        }

    sections = []
    for subplan, report in executions:
        source_name = str(subplan["source"])
        source = sources[source_name]
        sections.append(
            {
                "source": source_name,
                "source_id": source["source_id"],
                "database_name": source["database_name"],
                "semantic_version": report.get("semantic_version"),
                "metric_contract_version": report.get("metric_contract_version"),
                "metric_contract_id": subplan.get("metric_contract_id"),
                "planner": report.get("planner"),
                "query": report.get("query"),
                "result": report.get("result"),
                "semantic_caveats": report.get("semantic_caveats") or [],
                "source_rows_persisted": report.get("source_rows_persisted"),
            }
        )
    evidence = build_federated_bundle_evidence(sections)
    semantic_plan = build_federated_semantic_plan_evidence(
        question=request.question,
        language=request.language,
        semantic_version=str(semantic["semantic_version"]),
        federated_contract_id=str(contract["contract_id"]),
        subplans=[
            {
                "source": str(subplan["source"]),
                "metric_contract_id": str(subplan["metric_contract_id"]),
                "report": report,
            }
            for subplan, report in executions
        ],
    )
    return {
        **base,
        "status": "ok",
        "contract": {
            "contract_id": contract["contract_id"],
            "application": "independent_sections",
            "metric_contract_ids": [
                str(item["metric_contract_id"]) for item in contract.get("subplans") or []
            ],
            "cross_database_sql": False,
            "cross_source_join": False,
        },
        "semantic_plan": semantic_plan.model_dump(mode="json"),
        "sources": [
            {
                "source": item["source"],
                "source_id": item["source_id"],
                "database_name": item["database_name"],
            }
            for item in sections
        ],
        "result": {
            "section_count": evidence["section_count"],
            "bundle_fingerprint": evidence["bundle_fingerprint"],
            "sections": sections,
        },
    }


def _escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _section_table(result: dict[str, Any]) -> str:
    columns = [str(value) for value in result.get("columns") or []]
    if not columns:
        return ""
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in result.get("data") or []:
        lines.append("| " + " | ".join(_escape_cell(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def format_abu_dhabi_federated_response(
    request: AbuDhabiFederatedRequest,
    report: dict[str, Any],
) -> str:
    language = request.language
    if not request.accepted:
        return {
            "zh": "请输入需要同时查询 Liveability 和 Makani 的问题。",
            "en": "Enter a question that uses both Liveability and Makani.",
            "ar": "أدخل سؤالاً يستخدم بيانات جودة الحياة ومكاني معاً.",
        }[language]
    if report.get("status") == "rejected":
        reason = str(report.get("reason") or "")[:240].replace("`", "'")
        outcome = str(report.get("outcome") or "clarify")
        messages = {
            "clarify": {
                "zh": "需要澄清，未执行任何来源 SQL。请明确两个来源的业务对象、指标和比较口径。",
                "en": (
                    "Clarification is required; no source SQL was executed. Specify "
                    "the business objects, metrics, and comparison scope for both sources."
                ),
                "ar": (
                    "يلزم التوضيح؛ لم يتم تنفيذ SQL على أي مصدر. حدّد كائنات الأعمال "
                    "والمؤشرات ونطاق المقارنة للمصدرين."
                ),
            },
            "refuse": {
                "zh": "已拒绝执行，未执行任何来源 SQL。该请求超出只读或已审核的跨源语义边界。",
                "en": (
                    "Execution was refused; no source SQL was executed. The request "
                    "exceeds the read-only or reviewed cross-source semantic boundary."
                ),
                "ar": (
                    "تم رفض التنفيذ؛ لم يتم تنفيذ SQL على أي مصدر. يتجاوز الطلب حدود "
                    "القراءة فقط أو الدلالات المعتمدة عبر المصدرين."
                ),
            },
        }
        prefix = messages.get(outcome, messages["clarify"])[language]
        reason_label = {"zh": "治理原因", "en": "Governance reason", "ar": "سبب الحوكمة"}[language]
        return prefix + (f"\n\n{reason_label}: `{reason}`" if reason else "")
    if report.get("status") != "ok":
        return {
            "zh": "跨库问数的一个受治理子查询未通过，未返回部分结果。",
            "en": "A governed cross-source subquery failed; no partial result was returned.",
            "ar": "فشل استعلام فرعي محكوم؛ ولم تُعرض نتيجة جزئية.",
        }[language]

    labels = {
        "zh": {"liveability": "Liveability 结果", "makani": "Makani 结果"},
        "en": {"liveability": "Liveability result", "makani": "Makani result"},
        "ar": {"liveability": "نتيجة جودة الحياة", "makani": "نتيجة مكاني"},
    }[language]
    evidence_labels = {
        "zh": ("结果行数", "结果等价指纹", "跨源组合结果指纹"),
        "en": ("Result rows", "Result equivalence fingerprint", "Cross-source bundle fingerprint"),
        "ar": ("صفوف النتيجة", "بصمة تكافؤ النتيجة", "بصمة حزمة النتائج عبر المصادر"),
    }[language]
    parts = []
    for section in (report.get("result") or {}).get("sections") or []:
        source = str(section["source"])
        result = section.get("result") or {}
        parts.append(f"### {labels[source]}\n\n{_section_table(result)}")
        fingerprint = str(
            (result.get("equivalence_fingerprints") or {}).get(
                "unordered_position_numeric6_fingerprint"
            )
            or ""
        )
        if fingerprint:
            parts.append(
                f"{evidence_labels[0]}: `{int(result.get('row_count') or 0)}`  \n"
                f"{evidence_labels[1]}: `{fingerprint}`"
            )
        sql = str((section.get("query") or {}).get("sql") or "")
        if sql:
            parts.append(f"```sql\n{sql}\n```")
    bundle_fingerprint = str((report.get("result") or {}).get("bundle_fingerprint") or "")
    if bundle_fingerprint:
        parts.append(f"{evidence_labels[2]}: `{bundle_fingerprint}`")
    boundary = {
        "zh": "两个数据库分别只读执行，结果仅在应用层并列展示；未执行跨库 SQL 或跨库 Join。",
        "en": (
            "The databases were queried independently and merged only for "
            "presentation; no cross-database SQL or join was executed."
        ),
        "ar": (
            "نُفذ الاستعلام على كل قاعدة بصورة مستقلة، ودُمج العرض فقط؛ "
            "دون SQL أو ربط مباشر بين القاعدتين."
        ),
    }[language]
    parts.append(boundary)
    return "\n\n".join(parts)


def describe_abu_dhabi_federated_request(
    request: AbuDhabiFederatedRequest,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = report or {}
    contract = report.get("contract") or {}
    result = report.get("result") or {}
    return {
        "language": request.language,
        "accepted": request.accepted,
        "error": request.error,
        "semantic_version": report.get("semantic_version"),
        "planner_version": (report.get("planner") or {}).get("version"),
        "semantic_plan_status": (report.get("semantic_plan") or {}).get("status"),
        "status": report.get("status"),
        "applied_contract_id": contract.get("contract_id"),
        "contract_application_type": contract.get("application"),
        "source_ids": [item.get("source_id") for item in report.get("sources") or []],
        "cross_database_sql": contract.get("cross_database_sql"),
        "cross_source_join": contract.get("cross_source_join"),
        "section_count": result.get("section_count"),
        "bundle_fingerprint": result.get("bundle_fingerprint"),
    }


__all__ = [
    "AbuDhabiFederatedRequest",
    "FEDERATED_SEMANTIC_PATH",
    "FEDERATED_V1_SEMANTIC_PATH",
    "FEDERATED_V3_SEMANTIC_PATH",
    "FEDERATED_V4_SEMANTIC_PATH",
    "FEDERATED_V5_SEMANTIC_PATH",
    "PLANNER_VERSION",
    "PROMPT_VERSION",
    "build_federated_bundle_evidence",
    "classify_federated_admission",
    "describe_abu_dhabi_federated_request",
    "format_abu_dhabi_federated_response",
    "resolve_abu_dhabi_federated_request",
    "run_abu_dhabi_federated_request",
]
