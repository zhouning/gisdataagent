import json
from pathlib import Path

import pytest


@pytest.fixture
def sample_full_run(tmp_path):
    rec = lambda qid, intent, ex: {"qid": qid, "intent": intent, "ex": ex, "valid": 1}
    payload = {
        "summary": {"mode": "full", "n": 4, "execution_accuracy": 0.5},
        "records": [
            rec(1, "preview_listing", 0),
            rec(2, "knn", 1),
            rec(3, "attribute_filter", 1),
            rec(4, "category_filter", 0),
        ],
    }
    p = tmp_path / "full_results.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_derive_ablation_drops_disabled_intent_class(sample_full_run):
    from scripts.nl2sql_bench_common.derive_ablation import derive_ablation
    res = derive_ablation(sample_full_run, drop_intent="preview_listing")
    assert res["n"] == 3
    assert res["execution_accuracy"] == pytest.approx(2 / 3)


def test_derive_ablation_all_intents_returns_full_set(sample_full_run):
    from scripts.nl2sql_bench_common.derive_ablation import derive_ablation
    res = derive_ablation(sample_full_run, drop_intent="nonexistent_intent")
    assert res["n"] == 4
    assert res["execution_accuracy"] == pytest.approx(0.5)
