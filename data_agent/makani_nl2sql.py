"""Product entry point for governed Makani NL2Semantic2SQL."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .governed_virtual_nl2sql import (
    detect_question_language,
    run_governed_virtual_nl2sql,
)
from .abu_dhabi_artifact_registry import current_artifact_path
from .model_gateway import resolve_nl2sql_model_name

SOURCE_ID = 13
SOURCE_OWNER = "abu-dhabi-site-operator"
# Keep the historical constant for callers that display an artifact name.
# Execution resolves the checksum-verified deployment artifact on every
# request so a public source checkout does not require customer data at import
# time.
SEMANTIC_LAYER_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "makani_sync_full_semantic_layer_v4_full_coverage.json"
)
_PREFIX_RE = re.compile(
    r"^\s*@(?:MakaniNL2SQL|Makani|abu-dhabi-makani|设施资产问数|公用设施问数)"
    r"(?:\s+|$)(.*)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class MakaniNL2SQLRequest:
    question: str
    language: str
    explicit_source_selection: bool
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return bool(self.question) and self.error is None


def resolve_makani_nl2sql_request(
    value: str,
    *,
    continue_selected_source: bool = False,
) -> MakaniNL2SQLRequest | None:
    text = str(value or "")
    match = _PREFIX_RE.match(text)
    explicit = match is not None
    if explicit:
        question = match.group(1).strip().lstrip(":：").strip()
    elif continue_selected_source and not text.lstrip().startswith("@"):
        question = text.strip()
    else:
        return None
    language = detect_question_language(question or text)
    if not question:
        return MakaniNL2SQLRequest(
            question="",
            language=language,
            explicit_source_selection=explicit,
            error="empty_question",
        )
    return MakaniNL2SQLRequest(
        question=question,
        language=language,
        explicit_source_selection=explicit,
    )


async def run_makani_nl2sql_request(
    request: MakaniNL2SQLRequest,
    *,
    source_id: int | None = None,
    owner: str | None = None,
    timeout_seconds: int = 180,
    verify_platform_schema: bool = True,
    execution_profile: Literal["baseline_sql", "semantic_ir_experimental"] = "baseline_sql",
) -> dict[str, Any]:
    if not request.accepted:
        raise ValueError(request.error or "invalid_question")
    resolved_source_id = int(
        source_id
        if source_id is not None
        else os.environ.get("GDA_ABU_DHABI_MAKANI_SOURCE_ID", SOURCE_ID)
    )
    resolved_owner = owner or os.environ.get("GDA_ABU_DHABI_SOURCE_OWNER", SOURCE_OWNER)
    platform_schema_options = {} if verify_platform_schema else {"verify_platform_schema": False}
    return await run_governed_virtual_nl2sql(
        question=request.question,
        semantic_layer_path=current_artifact_path("makani", "semantic"),
        source_id=resolved_source_id,
        owner=resolved_owner,
        model_name=resolve_nl2sql_model_name(scope="makani"),
        reasoning_effort=os.environ.get("GDA_MAKANI_NL2SQL_REASONING_EFFORT", "medium"),
        timeout_seconds=timeout_seconds,
        execution_profile=execution_profile,
        **platform_schema_options,
    )


def _escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    return text[:177] + "..." if len(text) > 180 else text


def _markdown_table(result: dict[str, Any]) -> str:
    columns = [str(value) for value in result.get("columns") or []]
    rows = list(result.get("data") or [])
    if not columns:
        return ""
    header = "| " + " | ".join(_escape_cell(value) for value in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_escape_cell(row.get(column)) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def format_makani_nl2sql_response(
    request: MakaniNL2SQLRequest,
    report: dict[str, Any],
) -> str:
    language = request.language
    if not request.accepted:
        return {
            "zh": "请输入要查询的 Makani 公用设施数据问题。",
            "en": "Enter a question about the Makani utility data.",
            "ar": "أدخل سؤالاً حول بيانات مرافق مكاني.",
        }[language]
    if report.get("status") == "rejected":
        reason = str(report.get("reason") or "")[:240].replace("`", "'")
        outcome = str(report.get("outcome") or "clarify")
        messages = {
            "clarify": {
                "zh": "需要澄清，未执行 SQL。请补充业务对象、指标以及时间或空间口径后重试。",
                "en": (
                    "Clarification is required; no SQL was executed. Specify the "
                    "business object, metric, and time or spatial scope."
                ),
                "ar": (
                    "يلزم التوضيح؛ لم يتم تنفيذ SQL. حدّد كائن الأعمال والمؤشر "
                    "والنطاق الزمني أو المكاني."
                ),
            },
            "refuse": {
                "zh": "已拒绝执行，未执行 SQL。该请求超出当前只读、安全或经审核语义边界。",
                "en": (
                    "Execution was refused; no SQL was executed. The request exceeds "
                    "the current read-only, safety, or reviewed semantic boundary."
                ),
                "ar": (
                    "تم رفض التنفيذ؛ لم يتم تنفيذ SQL. يتجاوز الطلب حدود القراءة فقط "
                    "أو السلامة أو الدلالات المعتمدة."
                ),
            },
        }
        prefix = messages.get(outcome, messages["clarify"])[language]
        clarification = report.get("clarification") or {}
        options = clarification.get("options") or []
        if clarification.get("required") and options:
            option_label = {"zh": "可选数据表", "en": "Available tables", "ar": "الجداول المتاحة"}[language]
            option_lines = []
            for option in options:
                table = str(option.get("physical_table") or "").strip()
                asset_id = str(option.get("semantic_asset_id") or "").strip()
                if table:
                    option_lines.append(f"- `{table}`" + (f"（{asset_id}）" if language == "zh" and asset_id else f" ({asset_id})" if asset_id else ""))
            if option_lines:
                prefix += f"\n\n{option_label}:\n" + "\n".join(option_lines)
        reason_label = {"zh": "治理原因", "en": "Governance reason", "ar": "سبب الحوكمة"}[language]
        return prefix + (f"\n\n{reason_label}: `{reason}`" if reason else "")
    if report.get("status") != "ok":
        return {
            "zh": "本次 Makani 问数未通过语义或执行校验，未返回未经治理的数据结果。",
            "en": "The Makani query did not pass semantic or execution validation.",
            "ar": "لم يجتز استعلام مكاني التحقق الدلالي أو التنفيذي.",
        }[language]

    result = report.get("result") or {}
    row_count = int(result.get("row_count") or 0)
    shown = int(result.get("displayed_row_count") or 0)
    if language == "zh":
        intro = f"查询完成，共返回 `{row_count}` 行。"
        if result.get("truncated_for_display"):
            intro += f" 当前展示前 `{shown}` 行。"
        sql_label = "执行 SQL"
        source_line = "来源：已登记虚拟来源 `makani_sync_full/public`，只读执行。"
        caveat = "分类和值域按源数据原值展示；跨表关系尚未声明。"
        fingerprint_label = "结果等价指纹"
    elif language == "en":
        intro = f"Query completed with `{row_count}` rows."
        if result.get("truncated_for_display"):
            intro += f" The first `{shown}` rows are shown."
        sql_label = "Executed SQL"
        source_line = (
            "Source: registered virtual source `makani_sync_full/public`, read-only execution."
        )
        caveat = "Categories use source values as-is; no cross-table relationships are declared."
        fingerprint_label = "Result equivalence fingerprint"
    else:
        intro = f"اكتمل الاستعلام وأعاد `{row_count}` صفاً."
        if result.get("truncated_for_display"):
            intro += f" يتم عرض أول `{shown}` صفاً."
        sql_label = "تعليمة SQL المنفذة"
        source_line = (
            "المصدر: المصدر الافتراضي المسجل `makani_sync_full/public`، تنفيذ للقراءة فقط."
        )
        caveat = "تُستخدم قيم المصدر كما هي؛ ولا توجد علاقات معلنة بين الجداول."
        fingerprint_label = "بصمة تكافؤ النتيجة"

    parts = [intro]
    timing = report.get("timing") or {}
    if timing.get("total_ms") is not None or timing.get("database_ms") is not None:
        if language == "zh":
            parts.append(f"耗时：总计 `{timing.get('total_ms', '-')} ms`，数据库 `{timing.get('database_ms', '-')} ms`。")
        elif language == "en":
            parts.append(f"Timing: total `{timing.get('total_ms', '-')} ms`; database `{timing.get('database_ms', '-')} ms`.")
        else:
            parts.append(f"الزمن: الإجمالي `{timing.get('total_ms', '-')} ms`؛ قاعدة البيانات `{timing.get('database_ms', '-')} ms`.")
    table = _markdown_table(result)
    if table:
        parts.append(table)
    fingerprint = str(
        (result.get("equivalence_fingerprints") or {}).get(
            "unordered_position_numeric6_fingerprint"
        )
        or ""
    )
    if fingerprint:
        parts.append(f"{fingerprint_label}: `{fingerprint}`")
    sql = str((report.get("query") or {}).get("sql") or "")
    if sql:
        parts.append(f"{sql_label}:\n```sql\n{sql}\n```")
    parts.extend([source_line, caveat])
    return "\n\n".join(parts)


def describe_makani_nl2sql_request(
    request: MakaniNL2SQLRequest,
    report: dict[str, Any] | None = None,
    *,
    source_id: int | None = None,
) -> dict[str, Any]:
    report = report or {}
    query = report.get("query") or {}
    result = report.get("result") or {}
    prompt = report.get("prompt") or {}
    metric_contract = query.get("semantic_metric_contract") or {}
    return {
        "language": request.language,
        "accepted": request.accepted,
        "error": request.error,
        "explicit_source_selection": request.explicit_source_selection,
        "source_id": source_id if source_id is not None else SOURCE_ID,
        "execution_mode": "registered_governed_virtual_read_only",
        "semantic_version": report.get("semantic_version"),
        "prompt_version": prompt.get("version"),
        "metric_contract_version": (
            report.get("metric_contract_version") or metric_contract.get("metric_contract_version")
        ),
        "applied_metric_contract_id": metric_contract.get("contract_id"),
        "metric_contract_application_type": metric_contract.get("application"),
        "status": report.get("status"),
        "question": request.question,
        "clarification": report.get("clarification"),
        "sql_sha256": query.get("sql_sha256"),
        "row_count": result.get("row_count"),
    }


__all__ = [
    "MakaniNL2SQLRequest",
    "SEMANTIC_LAYER_PATH",
    "SOURCE_ID",
    "SOURCE_OWNER",
    "describe_makani_nl2sql_request",
    "format_makani_nl2sql_response",
    "resolve_makani_nl2sql_request",
    "run_makani_nl2sql_request",
]
