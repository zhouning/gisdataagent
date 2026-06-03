# Standards Platform Wave 6-eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic offline quality evaluator for Standards Platform derivation outputs.

**Architecture:** The first slice is a pure-Python evaluation package under `data_agent/standards_platform/evaluation`. It validates gold/predicted item sets, scores exact canonical identities, and renders Markdown reports without touching production derivation strategies.

**Tech Stack:** Python dataclasses, stdlib JSON, pytest, existing `data_agent/standards_platform/tests` layout.

**Implementation Status:** Complete first slice as of 2026-06-03; focused Wave 6-eval tests pass and `pytest data_agent/standards_platform/ -q` reports 326 passed, 1 skipped.

---

## File Structure

- Create `data_agent/standards_platform/evaluation/__init__.py`: public exports for the evaluation package.
- Create `data_agent/standards_platform/evaluation/schema.py`: dataclasses, validation, canonical identity generation, JSON loading.
- Create `data_agent/standards_platform/evaluation/extractor.py`: DB reader that converts active derived links into eval items.
- Create `data_agent/standards_platform/evaluation/scorer.py`: precision / recall / F1 scoring and threshold checks.
- Create `data_agent/standards_platform/evaluation/report.py`: Markdown report rendering.
- Create `data_agent/standards_platform/evaluation/cli.py`: offline report command.
- Create `data_agent/standards_platform/tests/test_evaluation_schema.py`: schema and validation tests.
- Create `data_agent/standards_platform/tests/test_evaluation_extractor.py`: DB extraction tests.
- Create `data_agent/standards_platform/tests/test_evaluation_scorer.py`: scoring and threshold tests.
- Create `data_agent/standards_platform/tests/test_evaluation_report.py`: Markdown report tests.
- Create `data_agent/standards_platform/tests/test_evaluation_cli.py`: CLI orchestration tests.

## Task 1: Evaluation Schema

**Files:**
- Create: `data_agent/standards_platform/evaluation/__init__.py`
- Create: `data_agent/standards_platform/evaluation/schema.py`
- Test: `data_agent/standards_platform/tests/test_evaluation_schema.py`

- [x] **Step 1: Write failing tests**

```python
from data_agent.standards_platform.evaluation.schema import (
    DerivationEvalItem,
    DerivationEvalSet,
)


def test_item_identity_includes_canonical_match():
    a = DerivationEvalItem(
        strategy="to_value_semantics",
        source_key="data_element:cq_dltb.dlbm",
        target_kind="semantic_hint",
        target_key="cq_dltb.dlbm:value_enum",
        match={"values": ["0101", "0102"], "hint_kind": "value_enum"},
    )
    b = DerivationEvalItem(
        strategy="to_value_semantics",
        source_key="data_element:cq_dltb.dlbm",
        target_kind="semantic_hint",
        target_key="cq_dltb.dlbm:value_enum",
        match={"hint_kind": "value_enum", "values": ["0101", "0102"]},
    )
    assert a.identity == b.identity


def test_eval_set_rejects_duplicate_identity():
    item = {
        "strategy": "to_semantic_hint",
        "source_key": "data_element:cq_dltb.dlbm",
        "target_kind": "semantic_hint",
        "target_key": "cq_dltb.dlbm:other",
    }
    try:
        DerivationEvalSet.from_mapping({"items": [item, item]})
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate identity was accepted")
```

- [x] **Step 2: Run tests to verify failure**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_schema.py -q`

Expected: import failure because `data_agent.standards_platform.evaluation` does not exist.

- [x] **Step 3: Implement schema**

Create dataclasses with strict required-field validation and duplicate detection.

- [x] **Step 4: Verify tests pass**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_schema.py -q`

Expected: all tests pass.

## Task 2: Scorer

**Files:**
- Create: `data_agent/standards_platform/evaluation/scorer.py`
- Test: `data_agent/standards_platform/tests/test_evaluation_scorer.py`

- [x] **Step 1: Write failing tests**

```python
from data_agent.standards_platform.evaluation.schema import DerivationEvalSet
from data_agent.standards_platform.evaluation.scorer import score_eval_sets


def test_scores_overall_and_by_strategy():
    gold = DerivationEvalSet.from_mapping({"items": [
        {"strategy": "to_semantic_hint", "source_key": "a", "target_kind": "semantic_hint", "target_key": "a"},
        {"strategy": "to_qc_rule", "source_key": "b", "target_kind": "qc_rule", "target_key": "b"},
    ]})
    pred = DerivationEvalSet.from_mapping({"items": [
        {"strategy": "to_semantic_hint", "source_key": "a", "target_kind": "semantic_hint", "target_key": "a"},
        {"strategy": "to_qc_rule", "source_key": "c", "target_kind": "qc_rule", "target_key": "c"},
    ]})
    report = score_eval_sets(gold, pred, min_precision=0.85, min_recall=0.75)
    assert report.overall.true_positive == 1
    assert report.overall.false_positive == 1
    assert report.overall.false_negative == 1
    assert report.by_strategy["to_semantic_hint"].precision == 1.0
    assert report.by_strategy["to_qc_rule"].recall == 0.0
    assert report.passed is False
```

- [x] **Step 2: Run tests to verify failure**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_scorer.py -q`

Expected: import failure because `scorer.py` does not exist.

- [x] **Step 3: Implement scorer**

Compute set intersections by item identity, aggregate per strategy, calculate precision / recall / F1, and store false positives / false negatives.

- [x] **Step 4: Verify tests pass**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_scorer.py -q`

Expected: all tests pass.

## Task 3: Prediction Extractor

**Files:**
- Create: `data_agent/standards_platform/evaluation/extractor.py`
- Test: `data_agent/standards_platform/tests/test_evaluation_extractor.py`

- [x] **Step 1: Write failing tests**

```python
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.semantic_hint import SemanticHintStrategy
from data_agent.standards_platform.evaluation.extractor import extract_prediction_set


def test_extracts_active_semantic_hint_prediction(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (gen_random_uuid(), :v, 'E1', '地类编码', 'string', 'mandatory', 'cq_dltb', 'dlbm')"
        ), {"v": ver_id})
    SemanticHintStrategy().run(version_id=ver_id, by_user="admin")
    predictions = extract_prediction_set(engine, version_id=ver_id)
    assert any(i.strategy == "to_semantic_hint" and i.target_key == "cq_dltb.dlbm:other" for i in predictions.items)
```

- [x] **Step 2: Run test to verify failure**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_extractor.py -q`

Expected: import failure because `extractor.py` does not exist.

- [x] **Step 3: Implement extractor**

Read active `std_derived_link` rows for one version and convert supported target tables to `DerivationEvalItem`.

- [x] **Step 4: Verify tests pass**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_extractor.py -q`

Expected: all tests pass.

## Task 4: Markdown Report

**Files:**
- Create: `data_agent/standards_platform/evaluation/report.py`
- Test: `data_agent/standards_platform/tests/test_evaluation_report.py`

- [x] **Step 1: Write failing tests**

```python
from data_agent.standards_platform.evaluation.schema import DerivationEvalSet
from data_agent.standards_platform.evaluation.scorer import score_eval_sets
from data_agent.standards_platform.evaluation.report import render_markdown


def test_render_markdown_includes_thresholds_and_strategy_table():
    gold = DerivationEvalSet.from_mapping({"dataset_id": "gold-v1", "items": [
        {"strategy": "to_semantic_hint", "source_key": "a", "target_kind": "semantic_hint", "target_key": "a"},
    ]})
    report = score_eval_sets(gold, gold, min_precision=0.85, min_recall=0.75)
    md = render_markdown(report)
    assert "gold-v1" in md
    assert "PASS" in md
    assert "to_semantic_hint" in md
    assert "0.85" in md
    assert "0.75" in md
```

- [x] **Step 2: Run tests to verify failure**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_report.py -q`

Expected: import failure because `report.py` does not exist.

- [x] **Step 3: Implement report rendering**

Render a compact Markdown summary with thresholds, overall metrics, per-strategy metrics, and limited false positive / false negative identities.

- [x] **Step 4: Verify tests pass**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_report.py -q`

Expected: all tests pass.

## Task 5: Offline CLI

**Files:**
- Create: `data_agent/standards_platform/evaluation/cli.py`
- Modify: `data_agent/standards_platform/evaluation/report.py`
- Test: `data_agent/standards_platform/tests/test_evaluation_cli.py`

- [x] **Step 1: Write failing tests**

```python
def test_run_evaluation_writes_json_and_markdown(tmp_path, monkeypatch):
    gold = tmp_path / "gold.json"
    gold.write_text('{"dataset_id":"gold-v1","items":[]}', encoding="utf-8")
    code = run_evaluation(
        engine=object(),
        version_id="v1",
        gold_path=gold,
        json_report_path=tmp_path / "report.json",
        markdown_report_path=tmp_path / "report.md",
    )
    assert code == 0
    assert "PASS" in (tmp_path / "report.md").read_text(encoding="utf-8")
```

- [x] **Step 2: Run test to verify failure**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_cli.py -q`

Expected: import failure because `cli.py` does not exist.

- [x] **Step 3: Implement CLI**

Load the gold JSON file, extract live predictions, score, write JSON and Markdown reports, and return `0` for pass or `1` for threshold failure.

- [x] **Step 4: Verify tests pass**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_cli.py -q`

Expected: all tests pass.

## Task 6: Focused Regression

**Files:**
- Test-only verification.

- [x] **Step 1: Run focused evaluation tests**

Run: `python -m pytest data_agent/standards_platform/tests/test_evaluation_schema.py data_agent/standards_platform/tests/test_evaluation_extractor.py data_agent/standards_platform/tests/test_evaluation_scorer.py data_agent/standards_platform/tests/test_evaluation_report.py data_agent/standards_platform/tests/test_evaluation_cli.py -q`

Expected: all tests pass.

- [x] **Step 2: Run adjacent standards platform tests**

Run: `python -m pytest data_agent/standards_platform/tests/test_derivation_runner.py data_agent/standards_platform/tests/test_data_model_strategy.py -q`

Expected: all tests pass or unrelated DB availability skips.
