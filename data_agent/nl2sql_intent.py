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
            r"(删除|清空|truncate|drop\s+(table|database)|\bdelete\s+from\b|\bupdate\s+\w+\s+set\b|改成|修改为|新增|\binsert\s+into\b)",
            re.IGNORECASE,
        ),
    ]),
    (IntentLabel.KNN, [
        re.compile(
            r"最近的\s*\d+|nearest\s+\d+|top[- ]?k|前\s*\d+\s*(条|个)?\s*(?:近|临近|相邻)"
            r"|\b(?:closest|most\s+similar)\s+\d*",
            re.IGNORECASE,
        ),
    ]),
    (IntentLabel.SPATIAL_JOIN, [
        re.compile(
            r"(相交|重叠|与.{0,20}相邻|落在.{0,20}之内|包含|与.{0,20}交集"
            r"|\bintersect\b|\bcontains\b|\bwithin\s+(?:the\s+)?(?:boundary|polygon|region)\b)",
            re.IGNORECASE,
        ),
    ]),
    # AGGREGATION: explicit aggregation keywords. English keywords are placed FIRST
    # so questions like "What is the average X" or "How many Y" get AGGREGATION
    # rather than falling through to ATTRIBUTE_FILTER on incidental "= 'value'" tokens.
    # Bare Chinese "统计" is excluded so "统计耕地的总面积" falls through to CATEGORY_FILTER.
    (IntentLabel.AGGREGATION, [
        re.compile(
            # English aggregation lexicon — covers "what is/was the X" + "how many/much"
            # + "calculate/compute" + per/by/group + sum/count/avg/max/min functions.
            r"\b(?:how\s+many|how\s+much"
            r"|what\s+(?:is|was|are|were)\s+the\s+(?:ratio|percentage|percent|fraction|number|count|total|sum|average|mean|highest|lowest|maximum|minimum|biggest|smallest|most|least|peak|difference|disparity|amount|deviation)"
            r"|what\s+(?:is|was|are|were)\s+the\s+(?:total|average|highest|lowest|biggest|smallest|maximum|minimum)\s+(?:cost|price|amount|number|count|sum|spent|earned|paid|received)"
            r"|the\s+(?:most|least|highest|lowest|biggest|smallest|maximum|minimum|peak|top|bottom)\s+\w+"
            r"|(?:per|for\s+each|by)\s+(?:year|month|day|week|customer|category|country|segment|group|type|kind)"
            r"|group\s+by|order\s+by\s+count|distinct\s+count"
            r"|sum\s*\(|count\s*\(|avg\s*\(|max\s*\(|min\s*\("
            r"|\bhow\s+many\s+(?:more|fewer|less)\b|\b(?:percentage|percent|fraction|ratio|deviation)\s+(?:of|in)\b"
            r"|\bwhich\s+(?:year|month|day|country|customer|product|category|department|segment)\s+(?:had|has|recorded|saw|received|spent|earned)\b"
            r"|\bfind\s+the\s+(?:most|least|highest|lowest|biggest|smallest|top|bottom|number|count|total|average)\b"
            r"|\b(?:calculate|compute)\s+the\b|\bcalculate\s+the\s+(?:total|average|amount|number|count|difference|sum|deviation)\b"
            r"|\bare\s+there\s+more\b|\bdeviation\s+in\s+percentage\b)"
            # Chinese
            r"|分组|按.{0,20}统计|每.{0,10}平均|总和|总数|占比|比例",
            re.IGNORECASE,
        ),
    ]),
    # CATEGORY_FILTER: macro land-use categories only (NOT sub-categories like 水田)
    (IntentLabel.CATEGORY_FILTER, [
        re.compile(
            r"(耕地|林地|草地|建设用地|湿地|水域|城镇|乡村)",
        ),
    ]),
    # ATTRIBUTE_FILTER: equality / comparison operators OR specific-entity lookup
    # phrasings ("State the X of Y", "Tell the phone of Z"). Placed before
    # SPATIAL_MEASUREMENT and PREVIEW_LISTING so a question that names a value
    # ("the customer who paid 548.4") classifies as ATTRIBUTE_FILTER.
    (IntentLabel.ATTRIBUTE_FILTER, [
        re.compile(
            r"=\s*['\"]?[A-Za-z0-9一-鿿]+|>\s*-?\d+|<\s*-?\d+|like\s+['\"]"
            # English specific-entity lookup phrasings — directive verb + "the" + noun
            r"|\b(?:state|tell|mention|indicate|identify|give|write)\s+(?:me\s+|us\s+)?(?:the|out\s+the|whether)\b"
            # "What is X's Y" / "What's X's Y" — possessive lookup (allow multi-word names)
            r"|\bwhat(?:'s|\s+is|\s+was|\s+are|\s+were)\s+(?:[A-Z][a-z]+\s+)*[A-Z][a-z]+'s\s+\w+"
            # "What is the X" + identity-like predicate
            r"|\bwhat\s+(?:is|was|are|were)\s+(?:the|\w+'s)\s+\w+\s+(?:major|name|phone|address|date|status|category|type|kind|currency|department|nationality|segment)\b"
            # "Was/Did/Is/Are the X" — boolean entity lookup
            r"|\b(?:was|did|does|do|is|are)\s+the\s+\w+\b"
            # "For the/each/all X who" — entity-filter clause
            r"|\bfor\s+(?:the|each|all)\s+(?:customer|patient|person|product|member|student|employee)\s+who\b"
            # "Which X has/had/is/was" — single-entity selector
            r"|\bwhich\s+(?:student|patient|customer|member|employee|product|item|department|club|disease|symptom|currency|country)\s+(?:has|had|is|was|did|received|spent|paid|attended|managed|recorded)\b",
            re.IGNORECASE,
        ),
    ]),
    (IntentLabel.SPATIAL_MEASUREMENT, [
        re.compile(
            r"(面积|长度|周长|area\s*\(|st_length|st_area|平方米|公顷|千米)",
            re.IGNORECASE,
        ),
    ]),
    # PREVIEW_LISTING: listing/display keywords. Placed AFTER ATTRIBUTE_FILTER so
    # "Please list X where Y = Z" or "List X and the date Y paid" classifies as
    # ATTRIBUTE_FILTER. Bare "List the X" with multi-row intent classifies here.
    (IntentLabel.PREVIEW_LISTING, [
        re.compile(
            # Chinese
            r"列出所有|展示所有|显示全部|显示所有|预览|sample|preview"
            # English bare/explicit listing
            r"|\bplease\s+(?:list|show|display|give\s+(?:me|us))\b"
            r"|\b(?:list|display|enumerate|show)\s+(?:all|the)\s+(?:names?|ids?|values?|records?|products?|customers?|patients?|members?|students?|events?|items?|details?)\b"
            r"|\bshow\s+(?:all|the)\s+\w+\s+(?:where|that|with|having)\b"
            r"|\blist\s+all\s+\w+\b|\blist\s+out\s+the\b"
            r"|\bwhat\s+are\s+the\s+(?:names?|ids?|values?|titles?|descriptions?|categories?|symptoms?|diseases?)\s+of\b",
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


def classify_intent(question: str, family: str | None = None) -> IntentResult:
    """Public entrypoint: rule stage, then LLM judge if rule is uncertain.

    Per-family override (v6 Phase 1):
      - family="deepseek"  → rule stage ONLY (skip LLM judge). Evidence: on the
        17 grounding-reversal qids (see docs/nl2sql_v6_phase1_error_attribution.md),
        the LLM judge consistently misclassified aggregation questions as
        attribute_filter or preview_listing, which then misled the DS prompt's
        grounding block. DS's own system_instruction.md R2 handles
        aggregation/listing distinction directly from question surface form.
      - family="qwen" (planned) → same bypass as deepseek for now; revisit
        after Phase 3 Qwen attribution pass.
      - other families → rule + LLM judge (legacy behaviour).
    """
    if os.environ.get("NL2SQL_DISABLE_INTENT") == "1":
        return IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="disabled")
    rule = classify_rule(question)
    # Families that benefit from rule-only classification skip the LLM judge.
    if family in ("deepseek", "qwen"):
        return rule
    if rule.primary is not IntentLabel.UNKNOWN and rule.confidence >= 0.7:
        return rule
    try:
        return _llm_judge(question)
    except Exception:
        return IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="fallback")
