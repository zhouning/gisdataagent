"""Controlled Chainlit entry point for the Abu Dhabi Liveability pilot.

This module deliberately resolves only the three frozen Gold Contract
questions. It is not a general natural-language-to-SQL router.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_LANGUAGES = ("zh", "en", "ar")
SOURCE_ID = 12
SOURCE_OWNER = "abu-dhabi-site-operator"
SEMANTIC_LAYER_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/customer/abu_dhabi_liveability_site_validation"
    / "liveability_semantic_layer_candidate_v0.json"
)
CONTRACT_DIR = SEMANTIC_LAYER_PATH.parent / "gold_candidates"
CONTRACT_PATHS = {
    "LIVEABILITY_FACILITY_COUNT_BY_TYPE_STAGE_V0": (
        CONTRACT_DIR / "LIVEABILITY_FACILITY_COUNT_BY_TYPE_STAGE_V0.json"
    ),
    "LIVEABILITY_DISTRICT_SCORE_SUMMARY_BY_STAGE_V0": (
        CONTRACT_DIR / "LIVEABILITY_DISTRICT_SCORE_SUMMARY_BY_STAGE_V0.json"
    ),
    "LIVEABILITY_ISOCHRONE_COUNT_BY_TYPE_STAGE_MODE_V0": (
        CONTRACT_DIR / "LIVEABILITY_ISOCHRONE_COUNT_BY_TYPE_STAGE_MODE_V0.json"
    ),
}
_PREFIX_RE = re.compile(
    r"^\s*@(?:Liveability|LiveabilityDemo|abu-dhabi-liveability|宜居演示)\b\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class LiveabilityDemoRequest:
    """A resolved fixed-contract request or a controlled-entry error."""

    question: str
    language: str
    contract_id: str | None
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return self.contract_id is not None and self.error is None


def _normalize_question(value: str) -> str:
    """Normalize punctuation/spacing without translating source terminology."""
    return "".join(char.casefold() for char in value if char.isalnum())


def _detect_language(value: str) -> str:
    if _ARABIC_RE.search(value):
        return "ar"
    if _CJK_RE.search(value):
        return "zh"
    return "en"


def _load_contract_questions() -> list[tuple[str, dict[str, str]]]:
    contracts: list[tuple[str, dict[str, str]]] = []
    for contract_id, path in CONTRACT_PATHS.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        questions = payload.get("questions") or {}
        contracts.append(
            (
                contract_id,
                {
                    language: str(questions[language])
                    for language in SUPPORTED_LANGUAGES
                    if questions.get(language)
                },
            )
        )
    return contracts


def resolve_liveability_demo_request(value: str) -> LiveabilityDemoRequest | None:
    """Resolve an explicit ``@Liveability`` request to one frozen contract.

    ``None`` means the message is unrelated to this controlled entry point.
    A prefixed but unsupported question returns a request with ``error`` so
    the caller can fail closed and explain the bounded scope.
    """

    match = _PREFIX_RE.match(value or "")
    if not match:
        return None
    question = match.group(1).strip()
    language = _detect_language(question)
    normalized = _normalize_question(question)
    if not normalized:
        return LiveabilityDemoRequest(
            question=question,
            language=language,
            contract_id=None,
            error="empty_question",
        )
    for contract_id, questions in _load_contract_questions():
        expected = questions.get(language)
        if expected and _normalize_question(expected) == normalized:
            return LiveabilityDemoRequest(
                question=question,
                language=language,
                contract_id=contract_id,
            )
    return LiveabilityDemoRequest(
        question=question,
        language=language,
        contract_id=None,
        error="question_not_in_frozen_contracts",
    )


def _localized_scope(language: str) -> str:
    return {
        "zh": "受控 Liveability 演示：来源 liveability_data/public，虚拟只读查询。",
        "en": (
            "Controlled Liveability demo: governed virtual read-only query on "
            "liveability_data/public."
        ),
        "ar": "عرض جودة الحياة المقيّد: استعلام افتراضي للقراءة فقط من liveability_data/public.",
    }[language]


def _localized_not_available(language: str) -> str:
    return {
        "zh": (
            "当前受控入口只接受三个已冻结的 Liveability Gold Contract 问题；"
            "未生成自由 SQL。请使用人工验证文档中的原问题。"
        ),
        "en": (
            "This controlled entry accepts only the three frozen Liveability Gold Contract "
            "questions; no free-form SQL was generated. Use a question from the manual script."
        ),
        "ar": (
            "تقبل هذه الواجهة المقيّدة أسئلة عقود Gold الثلاثة المجمّدة فقط؛ "
            "لم يتم إنشاء SQL حر. استخدم سؤالاً من دليل التحقق اليدوي."
        ),
    }[language]


def _localized_failure(language: str) -> str:
    return {
        "zh": "本次受控问数未通过契约校验，系统没有生成可采信的数据答案。",
        "en": (
            "The controlled query did not pass the contract checks; no trusted data "
            "answer was produced."
        ),
        "ar": "لم يجتز الاستعلام المقيّد فحوص العقد، لذلك لم يتم إصدار إجابة بيانات موثوقة.",
    }[language]


def _format_success(language: str, report: dict[str, Any], run: dict[str, Any]) -> str:
    execution = run.get("execution") or {}
    contract_id = str((report.get("contract") or {}).get("contract_id") or "")
    model = report.get("model") or {}
    versions = ", ".join(run.get("observed_model_versions") or []) or "unknown"
    fingerprint = str(execution.get("result_fingerprint") or "")
    row_count = execution.get("row_count")
    answer = str(run.get("same_language_answer") or "")
    if language == "zh":
        evidence = (
            f"\n\n契约：`{contract_id}`\n"
            f"结果分组数：`{row_count}`\n"
            f"结果指纹：`{fingerprint}`\n"
            f"模型：`{model.get('adk_route', 'gpt-5.1')}`（{versions}）\n"
            f"{_localized_scope(language)}"
        )
    elif language == "en":
        evidence = (
            f"\n\nContract: `{contract_id}`\n"
            f"Result groups: `{row_count}`\n"
            f"Result fingerprint: `{fingerprint}`\n"
            f"Model: `{model.get('adk_route', 'gpt-5.1')}` ({versions})\n"
            f"{_localized_scope(language)}"
        )
    else:
        evidence = (
            f"\n\nالعقد: `{contract_id}`\n"
            f"عدد مجموعات النتائج: `{row_count}`\n"
            f"بصمة النتيجة: `{fingerprint}`\n"
            f"النموذج: `{model.get('adk_route', 'gpt-5.1')}` ({versions})\n"
            f"{_localized_scope(language)}"
        )
    return answer + evidence


def _format_failure(language: str, report: dict[str, Any], run: dict[str, Any] | None) -> str:
    contract_id = str((report.get("contract") or {}).get("contract_id") or "unknown")
    error = str((run or {}).get("error") or "contract_validation_failed")
    # The pilot redacts secrets. Keep the UI error bounded and do not expose SQL.
    error = error[:240]
    if language == "zh":
        return f"{_localized_failure(language)}\n契约：`{contract_id}`\n诊断：`{error}`"
    if language == "en":
        return f"{_localized_failure(language)}\nContract: `{contract_id}`\nDiagnostic: `{error}`"
    return f"{_localized_failure(language)}\nالعقد: `{contract_id}`\nالتشخيص: `{error}`"


async def run_liveability_demo_request(
    request: LiveabilityDemoRequest,
    *,
    source_id: int | None = None,
    owner: str | None = None,
    timeout_seconds: int = 180,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run one resolved question through the frozen pilot contract."""

    if not request.accepted:
        raise ValueError(request.error or "question_not_in_frozen_contracts")
    from .multilingual_nl2sql_pilot import run_multilingual_pilot

    resolved_source_id = int(
        source_id
        if source_id is not None
        else os.environ.get("GDA_ABU_DHABI_LIVEABILITY_SOURCE_ID", SOURCE_ID)
    )
    resolved_owner = owner or os.environ.get("GDA_ABU_DHABI_SOURCE_OWNER", SOURCE_OWNER)
    report = await run_multilingual_pilot(
        contract_path=CONTRACT_PATHS[request.contract_id],
        semantic_layer_path=SEMANTIC_LAYER_PATH,
        source_id=resolved_source_id,
        owner=resolved_owner,
        model_name="gpt-5.1",
        reasoning_effort=os.environ.get("GDA_LIVEABILITY_DEMO_REASONING_EFFORT", "medium"),
        timeout_seconds=timeout_seconds,
        languages=(request.language,),
    )
    run = next(
        (
            candidate
            for candidate in report.get("runs") or []
            if candidate.get("language") == request.language
        ),
        None,
    )
    return report, run


def format_liveability_demo_response(
    request: LiveabilityDemoRequest,
    report: dict[str, Any],
    run: dict[str, Any] | None,
) -> str:
    """Render only contracted aggregate evidence and same-language text."""

    if not request.accepted:
        return _localized_not_available(request.language)
    if report.get("status") == "passed" and run and run.get("status") == "passed":
        return _format_success(request.language, report, run)
    return _format_failure(request.language, report, run)


def format_liveability_demo_error(request: LiveabilityDemoRequest) -> str:
    """Render a generic same-language runtime failure without exposing secrets."""

    if request.language == "zh":
        return "受控 Liveability 演示暂时不可用；系统未生成可采信的数据答案。"
    if request.language == "en":
        return (
            "The controlled Liveability demo is temporarily unavailable; no trusted "
            "data answer was produced."
        )
    return "عرض جودة الحياة المقيّد غير متاح مؤقتاً؛ لم يتم إصدار إجابة بيانات موثوقة."


def describe_liveability_demo_request(
    request: LiveabilityDemoRequest,
    *,
    source_id: int | None = None,
) -> dict[str, Any]:
    """Return secret-free routing metadata suitable for Chainlit audit fields."""

    return {
        "contract_id": request.contract_id,
        "language": request.language,
        "accepted": request.accepted,
        "error": request.error,
        "source_id": source_id if source_id is not None else SOURCE_ID,
        "execution_mode": "registered_governed_virtual_read_only",
    }
