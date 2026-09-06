"""Product entry point for free-form Liveability NL2Semantic2SQL."""

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

SOURCE_ID = 12
SOURCE_OWNER = "abu-dhabi-site-operator"
# Keep the historical constant for compatibility with callers that display the
# source artifact name; execution resolves the checksum-verified current path
# from the bundle on every request.
SEMANTIC_LAYER_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_data_20260730_semantic_layer_v4_full_coverage.json"
)
_PREFIX_RE = re.compile(
    r"^\s*@(?:LiveabilityNL2SQL|Liveability|abu-dhabi-liveability|宜居问数|宜居演示)"
    r"(?:\s+|$)(.*)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class LiveabilityNL2SQLRequest:
    question: str
    language: str
    explicit_source_selection: bool
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return bool(self.question) and self.error is None


def resolve_liveability_nl2sql_request(
    value: str,
    *,
    continue_selected_source: bool = False,
) -> LiveabilityNL2SQLRequest | None:
    """Resolve a source selection or follow-up without matching fixed questions."""

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
        return LiveabilityNL2SQLRequest(
            question="",
            language=language,
            explicit_source_selection=explicit,
            error="empty_question",
        )
    return LiveabilityNL2SQLRequest(
        question=question,
        language=language,
        explicit_source_selection=explicit,
    )


async def run_liveability_nl2sql_request(
    request: LiveabilityNL2SQLRequest,
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
        else os.environ.get("GDA_ABU_DHABI_LIVEABILITY_SOURCE_ID", SOURCE_ID)
    )
    resolved_owner = owner or os.environ.get("GDA_ABU_DHABI_SOURCE_OWNER", SOURCE_OWNER)
    platform_schema_options = {} if verify_platform_schema else {"verify_platform_schema": False}
    return await run_governed_virtual_nl2sql(
        question=request.question,
        semantic_layer_path=current_artifact_path("liveability", "semantic"),
        source_id=resolved_source_id,
        owner=resolved_owner,
        model_name=resolve_nl2sql_model_name(scope="liveability"),
        reasoning_effort=os.environ.get("GDA_LIVEABILITY_NL2SQL_REASONING_EFFORT", "medium"),
        timeout_seconds=timeout_seconds,
        execution_profile=execution_profile,
        **platform_schema_options,
    )


def _escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    if len(text) > 180:
        return text[:177] + "..."
    return text


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


_CAVEATS = {
    "population_reference_date_unconfirmed": {
        "zh": "人口字段按源数据原值查询，正式人口基准日尚待客户确认。",
        "en": (
            "Population fields use source values as-is; the formal reference date "
            "is pending customer confirmation."
        ),
        "ar": (
            "تُستخدم قيم حقول السكان كما هي في المصدر؛ ولا يزال التاريخ المرجعي "
            "الرسمي بانتظار تأكيد العميل."
        ),
    },
    "calculation_run_provenance_unavailable": {
        "zh": "得分表没有可绑定的计算批次，系统未擅自添加“最新批次”过滤。",
        "en": (
            "The score table has no bindable calculation run; no implicit "
            "latest-run filter was added."
        ),
        "ar": "لا يتوفر تشغيل حساب قابل للربط بجدول الدرجات؛ ولم تتم إضافة مرشح ضمني لأحدث تشغيل.",
    },
    "source_value_domain_used_as_is": {
        "zh": "分类值按源数据原值展示，未擅自翻译或改写。",
        "en": (
            "Categorical values are shown exactly as stored, without implicit "
            "translation or rewriting."
        ),
        "ar": "تُعرض القيم التصنيفية كما هي مخزنة في المصدر دون ترجمة أو إعادة صياغة ضمنية.",
    },
}


def _localized_error(language: str) -> str:
    return {
        "zh": "本次自由问数未通过语义或执行校验，系统没有返回未经治理的数据结果。",
        "en": (
            "This free-form query did not pass semantic or execution validation; "
            "no ungoverned data result was returned."
        ),
        "ar": (
            "لم يجتز هذا الاستعلام الحر التحقق الدلالي أو التنفيذي، ولم تُعرض "
            "أي نتيجة بيانات غير محكومة."
        ),
    }[language]


def _localized_empty(language: str) -> str:
    return {
        "zh": "请输入要查询的 Liveability 数据问题。",
        "en": "Enter a question about the Liveability data.",
        "ar": "أدخل سؤالاً حول بيانات جودة الحياة.",
    }[language]


def format_liveability_nl2sql_response(
    request: LiveabilityNL2SQLRequest,
    report: dict[str, Any],
) -> str:
    language = request.language
    if not request.accepted:
        return _localized_empty(language)
    status = report.get("status")
    if status == "rejected":
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
    if status != "ok":
        return _localized_error(language)

    result = report.get("result") or {}
    row_count = int(result.get("row_count") or 0)
    shown = int(result.get("displayed_row_count") or 0)
    if language == "zh":
        intro = f"查询完成，共返回 `{row_count}` 行。"
        if result.get("truncated_for_display"):
            intro += f" 当前展示前 `{shown}` 行。"
        sql_label = "执行 SQL"
        source_line = "来源：已登记虚拟来源 `liveability_data_20260730/public`，只读执行。"
        caveat_label = "语义说明"
        fingerprint_label = "结果等价指纹"
    elif language == "en":
        intro = f"Query completed with `{row_count}` rows."
        if result.get("truncated_for_display"):
            intro += f" The first `{shown}` rows are shown."
        sql_label = "Executed SQL"
        source_line = (
            "Source: registered virtual source `liveability_data_20260730/public`, "
            "read-only execution."
        )
        caveat_label = "Semantic notes"
        fingerprint_label = "Result equivalence fingerprint"
    else:
        intro = f"اكتمل الاستعلام وأعاد `{row_count}` صفاً."
        if result.get("truncated_for_display"):
            intro += f" يتم عرض أول `{shown}` صفاً."
        sql_label = "تعليمة SQL المنفذة"
        source_line = (
            "المصدر: المصدر الافتراضي المسجل `liveability_data_20260730/public`، تنفيذ للقراءة فقط."
        )
        caveat_label = "ملاحظات دلالية"
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
    parts.append(source_line)
    caveats = [
        _CAVEATS[code][language]
        for code in report.get("semantic_caveats") or []
        if code in _CAVEATS
    ]
    if caveats:
        parts.append(caveat_label + ":\n" + "\n".join(f"- {item}" for item in caveats))
    return "\n\n".join(parts)


def describe_liveability_nl2sql_request(
    request: LiveabilityNL2SQLRequest,
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
    "LiveabilityNL2SQLRequest",
    "SEMANTIC_LAYER_PATH",
    "SOURCE_ID",
    "SOURCE_OWNER",
    "describe_liveability_nl2sql_request",
    "format_liveability_nl2sql_response",
    "resolve_liveability_nl2sql_request",
    "run_liveability_nl2sql_request",
]
