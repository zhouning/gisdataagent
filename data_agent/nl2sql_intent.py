# data_agent/nl2sql_intent.py
"""Intent classification for NL2SQL grounding routing (Phase A)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum


class IntentLabel(str, Enum):
    ATTRIBUTE_FILTER = "attribute_filter"
    CATEGORY_FILTER = "category_filter"
    SPATIAL_MEASUREMENT = "spatial_measurement"
    SPATIAL_JOIN = "spatial_join"
    KNN = "knn"
    AGGREGATION = "aggregation"
    PREVIEW_LISTING = "preview_listing"
    REFUSAL_INTENT = "refusal_intent"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    primary: IntentLabel
    secondary: list[IntentLabel] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "rule"  # "rule" | "llm" | "fallback"


# ---------------------------------------------------------------------------
# Rule-stage classifier
# ---------------------------------------------------------------------------
# Priority order (first match wins):
#   refusal > knn > spatial_join > aggregation > category_filter
#   > attribute_filter > spatial_measurement > preview_listing > unknown
#
# Key design decisions:
#   - AGGREGATION only fires on explicit grouping keywords (分组/group by/每.*平均
#     /sum(/count(/avg()), NOT on bare "统计" — so "统计耕地的总面积" falls through
#     to CATEGORY_FILTER.
#   - CATEGORY_FILTER covers land-use macro-categories (耕地/林地/草地/建设用地/
#     湿地/水域/城镇/乡村) but NOT sub-categories like 水田/旱地/有林地, so
#     "计算所有水田的真实空间面积" falls through to SPATIAL_MEASUREMENT.
#   - ATTRIBUTE_FILTER (= 'value') is placed before SPATIAL_MEASUREMENT so that
#     "找出 DLMC = '水田' 的图斑面积" returns ATTRIBUTE_FILTER, not SPATIAL_MEASUREMENT.
#   - PREVIEW_LISTING pattern excludes strings containing "=" so that
#     "列出所有 fclass = 'primary' 的道路名称" returns ATTRIBUTE_FILTER.
# ---------------------------------------------------------------------------

_RULES: list[tuple[IntentLabel, list[re.Pattern]]] = [
    (IntentLabel.REFUSAL_INTENT, [
        re.compile(
            r"(删除|清空|truncate|drop|delete|update|改成|修改为|新增|insert)",
            re.IGNORECASE,
        ),
    ]),
    (IntentLabel.KNN, [
        re.compile(
            r"最近的\s*\d+|nearest\s+\d+|top[- ]?k|前\s*\d+\s*(条|个)?\s*(?:近|临近|相邻)",
            re.IGNORECASE,
        ),
    ]),
    (IntentLabel.SPATIAL_JOIN, [
        re.compile(
            r"(相交|重叠|与.{0,20}相邻|落在.{0,20}之内|包含|与.{0,20}交集|intersect)",
            re.IGNORECASE,
        ),
    ]),
    # AGGREGATION: explicit grouping/aggregate functions only — bare "统计" is excluded
    # so "统计耕地的总面积" falls through to CATEGORY_FILTER.
    (IntentLabel.AGGREGATION, [
        re.compile(
            r"(分组|按.{0,20}统计|group\s+by|每.{0,10}平均|总和|总数|占比|比例"
            r"|sum\s*\(|count\s*\(|avg\s*\()",
            re.IGNORECASE,
        ),
    ]),
    # CATEGORY_FILTER: macro land-use categories only (NOT sub-categories like 水田)
    (IntentLabel.CATEGORY_FILTER, [
        re.compile(
            r"(耕地|林地|草地|建设用地|湿地|水域|城镇|乡村)",
        ),
    ]),
    # ATTRIBUTE_FILTER: equality / comparison operators — placed before SPATIAL_MEASUREMENT
    # so "找出 DLMC = '水田' 的图斑面积" → ATTRIBUTE_FILTER, not SPATIAL_MEASUREMENT.
    (IntentLabel.ATTRIBUTE_FILTER, [
        re.compile(
            r"=\s*['\"]?[A-Za-z0-9一-鿿]+|>\s*-?\d+|<\s*-?\d+|like\s+['\"]",
            re.IGNORECASE,
        ),
    ]),
    (IntentLabel.SPATIAL_MEASUREMENT, [
        re.compile(
            r"(面积|长度|周长|area\s*\(|st_length|st_area|平方米|公顷|千米)",
            re.IGNORECASE,
        ),
    ]),
    # PREVIEW_LISTING: listing/display keywords. When "=" is also present,
    # ATTRIBUTE_FILTER (higher priority) fires first and becomes primary.
    (IntentLabel.PREVIEW_LISTING, [
        re.compile(
            r"(列出所有|展示所有|显示全部|显示所有|预览|sample|preview)",
            re.IGNORECASE,
        ),
    ]),
]


def classify_rule(question: str) -> IntentResult:
    """Stage-1 keyword/pattern matching. Returns UNKNOWN if no rule fires."""
    text = question.strip()
    matches: list[tuple[IntentLabel, int]] = []
    for label, patterns in _RULES:
        for p in patterns:
            if p.search(text):
                matches.append((label, len(p.pattern)))
                break  # only one match per label needed
    if not matches:
        return IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="rule")
    primary = matches[0][0]
    secondary = [lbl for lbl, _ in matches[1:3] if lbl != primary]
    confidence = 0.95 if len(matches) == 1 else 0.85
    return IntentResult(primary=primary, secondary=secondary, confidence=confidence, source="rule")


# ---------------------------------------------------------------------------
# Stage-2 LLM judge
# ---------------------------------------------------------------------------

_JUDGE_MODEL = os.environ.get("MODEL_ROUTER", "gemini-2.0-flash")

_JUDGE_PROMPT = (
    "Classify the following database question into ONE of these intents and "
    "return strict JSON {{\"intent\": <label>, \"confidence\": <0..1>}}. "
    "Labels: attribute_filter, category_filter, spatial_measurement, "
    "spatial_join, knn, aggregation, preview_listing, refusal_intent, unknown.\n\n"
    "Question: {question}\nJSON:"
)


def _llm_judge(question: str) -> IntentResult:
    """Stage-2 LLM judge. May raise on transport / parse error."""
    from google import genai
    client = genai.Client()
    resp = client.models.generate_content(
        model=_JUDGE_MODEL,
        contents=_JUDGE_PROMPT.format(question=question),
    )
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    payload = json.loads(text)
    label = IntentLabel(payload["intent"])
    return IntentResult(primary=label, confidence=float(payload.get("confidence", 0.7)), source="llm")


def classify_intent(question: str) -> IntentResult:
    """Public entrypoint: rule stage, then LLM judge if rule is uncertain."""
    rule = classify_rule(question)
    if rule.primary is not IntentLabel.UNKNOWN and rule.confidence >= 0.7:
        return rule
    try:
        return _llm_judge(question)
    except Exception:
        return IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="fallback")
