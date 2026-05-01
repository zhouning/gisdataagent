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
