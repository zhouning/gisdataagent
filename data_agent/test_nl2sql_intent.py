# data_agent/test_nl2sql_intent.py
from data_agent.nl2sql_intent import IntentLabel, IntentResult


def test_intent_label_has_all_nine_classes():
    expected = {
        "ATTRIBUTE_FILTER", "CATEGORY_FILTER", "SPATIAL_MEASUREMENT",
        "SPATIAL_JOIN", "KNN", "AGGREGATION",
        "PREVIEW_LISTING", "REFUSAL_INTENT", "UNKNOWN",
    }
    actual = {label.name for label in IntentLabel}
    assert actual == expected


def test_intent_result_dataclass_carries_primary_secondary_confidence():
    r = IntentResult(
        primary=IntentLabel.ATTRIBUTE_FILTER,
        secondary=[IntentLabel.PREVIEW_LISTING],
        confidence=0.91,
        source="rule",
    )
    assert r.primary is IntentLabel.ATTRIBUTE_FILTER
    assert r.secondary == [IntentLabel.PREVIEW_LISTING]
    assert r.confidence == 0.91
    assert r.source == "rule"


import pytest
from data_agent.nl2sql_intent import classify_rule, IntentLabel


@pytest.mark.parametrize("question, expected", [
    ("列出所有 fclass = 'primary' 的道路名称", IntentLabel.ATTRIBUTE_FILTER),
    ("找出 DLMC = '水田' 的图斑面积", IntentLabel.ATTRIBUTE_FILTER),
    ("统计耕地的总面积", IntentLabel.CATEGORY_FILTER),
    ("分析林地分布", IntentLabel.CATEGORY_FILTER),
    ("计算所有水田的真实空间面积", IntentLabel.SPATIAL_MEASUREMENT),
    ("名称包含 '建设路' 的道路与水田的重叠总长度", IntentLabel.SPATIAL_JOIN),
    ("找出离 POI '重庆北站' 最近的 5 条道路", IntentLabel.KNN),
    ("按 fclass 分组统计道路总数", IntentLabel.AGGREGATION),
    ("显示所有 POI 的位置", IntentLabel.PREVIEW_LISTING),
    ("把 DLMC 等于 '其他林地' 的统一改成 '林地'", IntentLabel.REFUSAL_INTENT),
])
def test_classify_rule_returns_expected_intent(question, expected):
    result = classify_rule(question)
    assert result.primary is expected
    assert result.source == "rule"


from unittest.mock import patch
from data_agent.nl2sql_intent import classify_intent


def test_classify_intent_uses_rule_when_confident():
    result = classify_intent("找出离 POI '重庆北站' 最近的 5 条道路")
    assert result.primary is IntentLabel.KNN
    assert result.source == "rule"


def test_classify_intent_falls_back_to_llm_when_rule_uncertain():
    fake = IntentResult(primary=IntentLabel.AGGREGATION, confidence=0.78, source="llm")
    with patch("data_agent.nl2sql_intent._llm_judge", return_value=fake) as m:
        result = classify_intent("帮我看看大家都在干什么")
        assert m.called
        assert result.primary is IntentLabel.AGGREGATION
        assert result.source == "llm"


def test_classify_intent_returns_unknown_on_llm_failure():
    with patch("data_agent.nl2sql_intent._llm_judge", side_effect=RuntimeError("boom")):
        result = classify_intent("干啥")
        assert result.primary is IntentLabel.UNKNOWN
        assert result.source == "fallback"


def test_user_context_exposes_current_nl2sql_intent():
    from data_agent.user_context import current_nl2sql_intent
    from data_agent.nl2sql_intent import IntentLabel
    assert current_nl2sql_intent.get() == IntentLabel.UNKNOWN
    token = current_nl2sql_intent.set(IntentLabel.KNN)
    try:
        assert current_nl2sql_intent.get() is IntentLabel.KNN
    finally:
        current_nl2sql_intent.reset(token)
