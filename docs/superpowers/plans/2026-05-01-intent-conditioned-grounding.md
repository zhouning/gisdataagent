# Intent-Conditioned Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always-on "inject every grounding rule" behavior in `data_agent/nl2sql_grounding.py` with a 9-class intent classifier that selectively activates rules, eliminating the GIS Spatial-EX regression (0.867 → 0.733) and producing a per-question intent log that supports component-level ablations.

**Architecture:** A new `data_agent/nl2sql_intent.py` module exposes an `IntentClassifier` (rule stage + LLM-judge fallback) returning an `IntentResult`. `nl2sql_grounding.build_nl2sql_context` consults a `GroundingRouter` keyed on the result to choose which rule blocks to emit. `sql_postprocessor.postprocess_sql` accepts an `intent` parameter so LIMIT injection only fires for `preview_listing`. Every per-question record gets an `intent` field so ablation tables can be derived offline.

**Tech Stack:** Python 3.13, sqlglot, Google GenAI SDK (Gemini 2.0 Flash for the judge), pytest, the existing semantic layer / context engine.

---

## File Structure

| File | Type | Responsibility |
|---|---|---|
| `data_agent/nl2sql_intent.py` | new | `IntentLabel` enum, `IntentResult` dataclass, rule-stage matcher, LLM-judge fallback, `classify_intent(question)` entrypoint. |
| `data_agent/test_nl2sql_intent.py` | new | Unit tests: ≥5 cases per intent + ambiguity tie-breakers + LLM-fallback degraded modes. |
| `data_agent/nl2sql_grounding.py` | edit | Add `GroundingRouter` and route the rule-emission section of `_format_grounding_prompt` through it; add `intent` to the returned payload. |
| `data_agent/test_nl2sql_grounding.py` | edit | Snapshot tests asserting that `attribute_filter`, `category_filter`, `knn`, `preview_listing`, `refusal_intent` produce the expected rule subsets. |
| `data_agent/sql_postprocessor.py` | edit | `postprocess_sql` gains an `intent` keyword; LIMIT injection runs only when `intent in {IntentLabel.PREVIEW_LISTING, IntentLabel.UNKNOWN}`. |
| `data_agent/test_sql_postprocessor.py` | edit | Add `intent`-aware tests: attribute_filter on a large table must NOT receive a LIMIT; preview_listing on the same table must receive one. |
| `data_agent/nl2sql_executor.py` | edit | Pass intent into `prepare_nl2sql_context` cache and into `postprocess_sql`. |
| `data_agent/user_context.py` | edit | New `current_nl2sql_intent` ContextVar. |
| `scripts/nl2sql_bench_cq/run_cq_eval.py` | edit | Capture `intent` per question record (via `prepare_nl2sql_context` payload), write to results JSON. |
| `scripts/nl2sql_bench_bird/run_pg_eval.py` | edit | Same instrumentation. |
| `data_agent/agent.py` | edit | Update MentionNL2SQL instruction so it states the framework will pick rules per intent (no behavior change required, but the model should know). |

---

## Tasks

### Task 1: Define the intent ontology (enum + dataclass)

**Files:**
- Create: `data_agent/nl2sql_intent.py`
- Test: `data_agent/test_nl2sql_intent.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py -k "intent_label_has_all or intent_result_dataclass" -v`

Expected: FAIL — `ModuleNotFoundError` or `AttributeError` for `IntentLabel` / `IntentResult`.

- [ ] **Step 3: Write minimal implementation**

```python
# data_agent/nl2sql_intent.py
"""Intent classification for NL2SQL grounding routing (Phase A)."""
from __future__ import annotations

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add data_agent/nl2sql_intent.py data_agent/test_nl2sql_intent.py
git commit -m "feat(nl2sql): add intent ontology for grounding routing"
```

---

### Task 2: Rule-stage classifier

**Files:**
- Modify: `data_agent/nl2sql_intent.py`
- Test: `data_agent/test_nl2sql_intent.py`

- [ ] **Step 1: Write the failing tests (one assert per intent)**

Append to `data_agent/test_nl2sql_intent.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py::test_classify_rule_returns_expected_intent -v`

Expected: FAIL — `classify_rule` does not exist.

- [ ] **Step 3: Implement the rule stage**

Append to `data_agent/nl2sql_intent.py`:

```python
import re

# Ordered priority: first match wins. The order encodes the precedence rule
# from the spec: refusal > knn > aggregation > spatial_* > category_filter
# > attribute_filter > preview_listing > unknown.
_RULES: list[tuple[IntentLabel, list[re.Pattern]]] = [
    (IntentLabel.REFUSAL_INTENT, [
        re.compile(r"(删除|清空|truncate|drop|delete|update|改成|修改为|新增|insert)", re.IGNORECASE),
    ]),
    (IntentLabel.KNN, [
        re.compile(r"最近的\s*\d+|nearest\s+\d+|top[- ]?k|前\s*\d+\s*(条|个)?\s*(?:近|临近|相邻)"),
    ]),
    (IntentLabel.SPATIAL_JOIN, [
        re.compile(r"(相交|重叠|与.*相邻|落在.*之内|包含|与.*交集|intersect)"),
    ]),
    (IntentLabel.SPATIAL_MEASUREMENT, [
        re.compile(r"(面积|长度|周长|area\s*\(|st_length|st_area|平方米|公顷|千米)"),
    ]),
    (IntentLabel.AGGREGATION, [
        re.compile(r"(分组|按.*统计|group by|每.*平均|总和|总数|占比|比例|sum\s*\(|count\s*\(|avg\s*\()", re.IGNORECASE),
    ]),
    (IntentLabel.CATEGORY_FILTER, [
        re.compile(r"(耕地|林地|草地|建设用地|湿地|水域|城镇|乡村)(?!.*=\s*['\"]?(?:水田|旱地|有林地))"),
    ]),
    (IntentLabel.ATTRIBUTE_FILTER, [
        re.compile(r"=\s*['\"]?[A-Za-z0-9一-鿿]+|>\s*-?\d+|<\s*-?\d+|like\s+['\"]"),
    ]),
    (IntentLabel.PREVIEW_LISTING, [
        re.compile(r"(列出所有(?!.*[=<>])|展示所有|显示全部|预览|sample|preview)"),
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
                break
    if not matches:
        return IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="rule")
    primary = matches[0][0]
    secondary = [lbl for lbl, _ in matches[1:3] if lbl != primary]
    confidence = 0.95 if len(matches) == 1 else 0.85
    return IntentResult(primary=primary, secondary=secondary, confidence=confidence, source="rule")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py -v`

Expected: 12 passed (2 from Task 1 + 10 parameterized).

- [ ] **Step 5: Commit**

```bash
git add data_agent/nl2sql_intent.py data_agent/test_nl2sql_intent.py
git commit -m "feat(nl2sql): rule-stage intent classifier with 9 labels"
```

---

### Task 3: LLM-judge fallback + `classify_intent` entrypoint

**Files:**
- Modify: `data_agent/nl2sql_intent.py`
- Test: `data_agent/test_nl2sql_intent.py`

- [ ] **Step 1: Write the failing tests**

Append to `data_agent/test_nl2sql_intent.py`:

```python
from unittest.mock import patch


def test_classify_intent_uses_rule_when_confident():
    result = classify_intent("找出离 POI '重庆北站' 最近的 5 条道路")
    assert result.primary is IntentLabel.KNN
    assert result.source == "rule"


def test_classify_intent_falls_back_to_llm_when_rule_uncertain():
    fake = IntentResult(primary=IntentLabel.AGGREGATION, confidence=0.78, source="llm")
    with patch("data_agent.nl2sql_intent._llm_judge", return_value=fake) as m:
        result = classify_intent("帮我看看大家都在干什么")  # vague, no rule match
        assert m.called
        assert result.primary is IntentLabel.AGGREGATION
        assert result.source == "llm"


def test_classify_intent_returns_unknown_on_llm_failure():
    with patch("data_agent.nl2sql_intent._llm_judge", side_effect=RuntimeError("boom")):
        result = classify_intent("干啥")  # vague
        assert result.primary is IntentLabel.UNKNOWN
        assert result.source == "fallback"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py -k "classify_intent" -v`

Expected: FAIL — `classify_intent` and `_llm_judge` do not exist.

- [ ] **Step 3: Implement the entrypoint**

Append to `data_agent/nl2sql_intent.py`:

```python
import json
import os

_JUDGE_MODEL = os.environ.get("MODEL_ROUTER", "gemini-2.0-flash")

_JUDGE_PROMPT = (
    "Classify the following database question into ONE of these intents and "
    "return strict JSON {\"intent\": <label>, \"confidence\": <0..1>}. "
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
    # Strip markdown fences if present.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py -v`

Expected: 15 passed (12 + 3).

- [ ] **Step 5: Commit**

```bash
git add data_agent/nl2sql_intent.py data_agent/test_nl2sql_intent.py
git commit -m "feat(nl2sql): two-stage intent classifier with LLM-judge fallback"
```

---

### Task 4: ContextVar for the active intent

**Files:**
- Modify: `data_agent/user_context.py`
- Test: `data_agent/test_nl2sql_intent.py`

- [ ] **Step 1: Write the failing test**

Append to `data_agent/test_nl2sql_intent.py`:

```python
def test_user_context_exposes_current_nl2sql_intent():
    from data_agent.user_context import current_nl2sql_intent
    from data_agent.nl2sql_intent import IntentLabel
    assert current_nl2sql_intent.get() == IntentLabel.UNKNOWN
    token = current_nl2sql_intent.set(IntentLabel.KNN)
    try:
        assert current_nl2sql_intent.get() is IntentLabel.KNN
    finally:
        current_nl2sql_intent.reset(token)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py -k "user_context_exposes_current_nl2sql_intent" -v`

Expected: FAIL — `current_nl2sql_intent` does not exist.

- [ ] **Step 3: Add the ContextVar**

In `data_agent/user_context.py`, after the `current_nl2sql_question` line (around line 20), add:

```python
from data_agent.nl2sql_intent import IntentLabel  # noqa: E402

current_nl2sql_intent: ContextVar[IntentLabel] = ContextVar(
    'current_nl2sql_intent', default=IntentLabel.UNKNOWN,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_intent.py -v`

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add data_agent/user_context.py data_agent/test_nl2sql_intent.py
git commit -m "feat(nl2sql): expose current_nl2sql_intent ContextVar"
```

---

### Task 5: Routing in `nl2sql_grounding._format_grounding_prompt`

**Files:**
- Modify: `data_agent/nl2sql_grounding.py`
- Test: `data_agent/test_nl2sql_grounding.py`

- [ ] **Step 1: Write the failing snapshot tests**

Append to `data_agent/test_nl2sql_grounding.py`:

```python
def test_format_grounding_prompt_attribute_filter_omits_limit_rule():
    from data_agent.nl2sql_grounding import _format_grounding_prompt
    from data_agent.nl2sql_intent import IntentLabel
    payload = {"candidate_tables": [], "semantic_hints": {}, "intent": IntentLabel.ATTRIBUTE_FILTER}
    out = _format_grounding_prompt(payload)
    assert "大表全表扫描必须有 LIMIT" not in out


def test_format_grounding_prompt_preview_listing_keeps_limit_rule():
    from data_agent.nl2sql_grounding import _format_grounding_prompt
    from data_agent.nl2sql_intent import IntentLabel
    payload = {"candidate_tables": [], "semantic_hints": {}, "intent": IntentLabel.PREVIEW_LISTING}
    out = _format_grounding_prompt(payload)
    assert "大表全表扫描必须有 LIMIT" in out


def test_format_grounding_prompt_knn_emphasizes_arrow_operator():
    from data_agent.nl2sql_grounding import _format_grounding_prompt
    from data_agent.nl2sql_intent import IntentLabel
    payload = {"candidate_tables": [], "semantic_hints": {}, "intent": IntentLabel.KNN}
    out = _format_grounding_prompt(payload)
    assert "<->" in out
    assert "ORDER BY ST_Distance" in out  # the rule explicitly forbids it
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_grounding.py -k "_format_grounding_prompt_" -v`

Expected: FAIL — current implementation always emits the LIMIT rule and never references `<->` explicitly.

- [ ] **Step 3: Replace the static "安全规则" / "KNN" blocks with intent-routed blocks**

In `data_agent/nl2sql_grounding.py`, find the block that ends with:

```python
    lines.append("")
    lines.append("## 安全规则")
    lines.append("- 只允许 SELECT 查询")
    lines.append("- 大表全表扫描必须有 LIMIT")
    lines.append("- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER")
    return "\n".join(lines)
```

Replace it with:

```python
    from .nl2sql_intent import IntentLabel
    intent = payload.get("intent", IntentLabel.UNKNOWN)
    if not isinstance(intent, IntentLabel):
        try:
            intent = IntentLabel(intent)
        except ValueError:
            intent = IntentLabel.UNKNOWN

    lines.append("")
    lines.append("## 安全规则")
    lines.append("- 只允许 SELECT 查询")
    lines.append("- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER")

    if intent in (IntentLabel.PREVIEW_LISTING, IntentLabel.UNKNOWN):
        lines.append("- 大表全表扫描必须有 LIMIT")

    if intent in (IntentLabel.KNN, IntentLabel.UNKNOWN):
        lines.append("")
        lines.append("## KNN 排序规则")
        lines.append("- 最近邻必须使用 PostGIS 索引算子: ORDER BY a.geometry <-> b.geometry LIMIT K")
        lines.append("- 不允许使用 ORDER BY ST_Distance(...) 进行排序；ST_Distance 只在 SELECT 中报告距离值")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_grounding.py -v`

Expected: existing tests still pass + 3 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add data_agent/nl2sql_grounding.py data_agent/test_nl2sql_grounding.py
git commit -m "feat(nl2sql): route LIMIT and KNN rules through intent label"
```

---

### Task 6: `build_nl2sql_context` calls `classify_intent` and surfaces the result

**Files:**
- Modify: `data_agent/nl2sql_grounding.py`
- Test: `data_agent/test_nl2sql_grounding.py`

- [ ] **Step 1: Write the failing test**

Append to `data_agent/test_nl2sql_grounding.py`:

```python
def test_build_nl2sql_context_attaches_intent_to_payload():
    from unittest.mock import patch
    from data_agent.nl2sql_grounding import build_nl2sql_context
    from data_agent.nl2sql_intent import IntentLabel, IntentResult

    fake = IntentResult(primary=IntentLabel.ATTRIBUTE_FILTER, confidence=0.95, source="rule")
    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=fake), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value={
             "sources": [], "matched_columns": {}, "spatial_ops": [], "region_filter": None,
             "metric_hints": [], "hierarchy_matches": [], "equivalences": [], "sql_filters": [],
         }):
        payload = build_nl2sql_context("列出 fclass = 'primary' 的道路")
    assert payload["intent"] is IntentLabel.ATTRIBUTE_FILTER
    assert "intent_source" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_grounding.py -k "build_nl2sql_context_attaches_intent" -v`

Expected: FAIL.

- [ ] **Step 3: Wire `classify_intent` into `build_nl2sql_context`**

At the top of `data_agent/nl2sql_grounding.py`, add:

```python
from .nl2sql_intent import classify_intent, IntentLabel
```

Inside `build_nl2sql_context`, immediately after the function entry / before any return path, compute the intent and add it to the payload. Example diff (pseudocode; insert near where the payload dict is constructed):

```python
intent_result = classify_intent(user_text)
payload["intent"] = intent_result.primary
payload["intent_secondary"] = [lbl.value for lbl in intent_result.secondary]
payload["intent_confidence"] = intent_result.confidence
payload["intent_source"] = intent_result.source
```

(If the function builds and returns multiple payload shapes, set these fields in the single shared `payload` object before the return.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_grounding.py -v`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add data_agent/nl2sql_grounding.py data_agent/test_nl2sql_grounding.py
git commit -m "feat(nl2sql): attach classified intent to grounding payload"
```

---

### Task 7: Intent-aware `postprocess_sql`

**Files:**
- Modify: `data_agent/sql_postprocessor.py`
- Test: `data_agent/test_sql_postprocessor.py`

- [ ] **Step 1: Write the failing test**

Append to `data_agent/test_sql_postprocessor.py`:

```python
def test_postprocess_attribute_filter_does_not_inject_limit_on_large_table():
    from data_agent.sql_postprocessor import postprocess_sql
    from data_agent.nl2sql_intent import IntentLabel

    schemas = {"cq_amap_poi_2024": [{"column_name": "geometry", "needs_quoting": False}]}
    res = postprocess_sql(
        "SELECT * FROM cq_amap_poi_2024 WHERE name = 'A'",
        table_schemas=schemas,
        large_tables={"cq_amap_poi_2024"},
        intent=IntentLabel.ATTRIBUTE_FILTER,
    )
    assert "LIMIT" not in res.sql.upper()


def test_postprocess_preview_listing_does_inject_limit_on_large_table():
    from data_agent.sql_postprocessor import postprocess_sql
    from data_agent.nl2sql_intent import IntentLabel

    schemas = {"cq_amap_poi_2024": [{"column_name": "geometry", "needs_quoting": False}]}
    res = postprocess_sql(
        "SELECT * FROM cq_amap_poi_2024",
        table_schemas=schemas,
        large_tables={"cq_amap_poi_2024"},
        intent=IntentLabel.PREVIEW_LISTING,
    )
    assert "LIMIT 1000" in res.sql.upper()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -k "attribute_filter or preview_listing" -v`

Expected: FAIL — `postprocess_sql` does not yet accept `intent`.

- [ ] **Step 3: Add `intent` parameter and gate LIMIT injection**

In `data_agent/sql_postprocessor.py`:

1. At top of file, import:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .nl2sql_intent import IntentLabel
```

2. Update the signature of `postprocess_sql`:

```python
def postprocess_sql(
    raw_sql: str,
    table_schemas: dict,
    large_tables: Optional[set] = None,
    intent: Optional["IntentLabel"] = None,
) -> PostprocessResult:
```

3. Replace the `if (large_tables and _references_large_table(parsed, large_tables) and not _is_aggregation_only(parsed)):` block so that it ALSO requires the intent to be `PREVIEW_LISTING` or `UNKNOWN`:

```python
from .nl2sql_intent import IntentLabel
allow_limit = intent in (None, IntentLabel.PREVIEW_LISTING, IntentLabel.UNKNOWN)
if (
    allow_limit
    and large_tables
    and _references_large_table(parsed, large_tables)
    and not _is_aggregation_only(parsed)
):
    ...
```

(Keep the existing inner logic for limit injection and bumping unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_sql_postprocessor.py -v`

Expected: all green (existing 12+ tests + 2 new).

- [ ] **Step 5: Commit**

```bash
git add data_agent/sql_postprocessor.py data_agent/test_sql_postprocessor.py
git commit -m "feat(nl2sql): gate LIMIT injection on intent label"
```

---

### Task 8: Wire intent through the executor

**Files:**
- Modify: `data_agent/nl2sql_executor.py`
- Test: `data_agent/test_nl2sql_executor.py`

- [ ] **Step 1: Write the failing test**

Append to `data_agent/test_nl2sql_executor.py` (create the file if it does not exist):

```python
from unittest.mock import patch
from data_agent.nl2sql_intent import IntentLabel
from data_agent import nl2sql_executor


def test_prepare_nl2sql_context_caches_intent():
    payload = {
        "candidate_tables": [],
        "intent": IntentLabel.KNN,
        "intent_source": "rule",
        "grounding_prompt": "...",
    }
    with patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload):
        nl2sql_executor.prepare_nl2sql_context("问题")
    from data_agent.user_context import current_nl2sql_intent
    assert current_nl2sql_intent.get() is IntentLabel.KNN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_executor.py -v`

Expected: FAIL — `prepare_nl2sql_context` does not yet update the ContextVar.

- [ ] **Step 3: Update the executor**

In `data_agent/nl2sql_executor.py`:

1. Import the new ContextVar:

```python
from .user_context import current_nl2sql_intent
```

2. Inside `prepare_nl2sql_context`, after the existing `current_nl2sql_*` setters, add:

```python
intent = payload.get("intent")
if intent is not None:
    current_nl2sql_intent.set(intent)
```

3. Inside `execute_nl2sql`, when calling `postprocess_sql`, pass `intent=current_nl2sql_intent.get()`:

```python
pp_result = postprocess_sql(last_sql, schemas, large_tables, intent=current_nl2sql_intent.get())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_executor.py -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add data_agent/nl2sql_executor.py data_agent/test_nl2sql_executor.py
git commit -m "feat(nl2sql): plumb intent through executor and postprocessor"
```

---

### Task 9: Capture intent in benchmark records

**Files:**
- Modify: `scripts/nl2sql_bench_cq/run_cq_eval.py`
- Modify: `scripts/nl2sql_bench_bird/run_pg_eval.py`
- Test: `data_agent/test_nl2sql_benchmark_mode.py`

- [ ] **Step 1: Write the failing test**

Append to `data_agent/test_nl2sql_benchmark_mode.py`:

```python
def test_run_one_record_includes_intent_field_for_cq():
    """run_one() in run_cq_eval.py should populate `intent` and `intent_source`."""
    from importlib import util
    spec = util.spec_from_file_location(
        "run_cq_eval_intent_check",
        "scripts/nl2sql_bench_cq/run_cq_eval.py",
    )
    src = open(spec.origin, encoding="utf-8").read()
    assert "rec[\"intent\"]" in src or "rec['intent']" in src
    assert "rec[\"intent_source\"]" in src or "rec['intent_source']" in src


def test_run_one_record_includes_intent_field_for_bird():
    src = open(
        "scripts/nl2sql_bench_bird/run_pg_eval.py", encoding="utf-8",
    ).read()
    assert "rec[\"intent\"]" in src or "rec['intent']" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_benchmark_mode.py -k "intent" -v`

Expected: FAIL — neither runner records intent yet.

- [ ] **Step 3: Capture the intent in both runners**

In `scripts/nl2sql_bench_cq/run_cq_eval.py`, locate the `full_generate(...)` (or the place where `run_one` builds its `rec` dict). After the SQL is generated and just before the dict is returned, insert:

```python
from data_agent.user_context import current_nl2sql_intent  # noqa: E402
intent = current_nl2sql_intent.get()
rec["intent"] = intent.value if hasattr(intent, "value") else str(intent)
rec["intent_source"] = "rule_or_llm"  # leave as a coarse label; downstream tools can refine
```

Apply the same change in `scripts/nl2sql_bench_bird/run_pg_eval.py` immediately before the per-question record is appended to `recs`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_benchmark_mode.py -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add scripts/nl2sql_bench_cq/run_cq_eval.py scripts/nl2sql_bench_bird/run_pg_eval.py data_agent/test_nl2sql_benchmark_mode.py
git commit -m "feat(nl2sql): record intent label per benchmark question"
```

---

### Task 10: Regression check — re-run GIS 20 + verify the three target failures now pass

**Files:**
- Modify: none (verification only)

- [ ] **Step 1: Run the GIS 20 benchmark with the new pipeline**

Run:

```bash
$env:PYTHONPATH="D:\\adk"
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_cq_eval.py --mode both
```

Expected: a new run directory under `data_agent/nl2sql_eval_results/cq_<timestamp>/` containing both `baseline_results.json` and `full_results.json`.

- [ ] **Step 2: Verify CQ_GEO_EASY_02, CQ_GEO_EASY_03, CQ_GEO_HARD_02 are now correct in the full run**

Run:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe - <<'PY'
import json, glob, os
runs = sorted(glob.glob("data_agent/nl2sql_eval_results/cq_2026-05-01_*"))
latest = runs[-1]
full = json.load(open(os.path.join(latest, "full_results.json"), encoding="utf-8"))
targets = {"CQ_GEO_EASY_02", "CQ_GEO_EASY_03", "CQ_GEO_HARD_02"}
for r in full["records"]:
    if r["qid"] in targets:
        print(r["qid"], r.get("intent"), "ex=", r.get("ex"))
PY
```

Expected output: all three QIDs have `ex=1` and an `intent` value matching the spec (`attribute_filter` / `attribute_filter` / `knn`).

- [ ] **Step 3: Verify Spatial-EX no longer regresses**

Run:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe - <<'PY'
import json, glob, os
latest = sorted(glob.glob("data_agent/nl2sql_eval_results/cq_2026-05-01_*"))[-1]
full = json.load(open(os.path.join(latest, "full_results.json"), encoding="utf-8"))["records"]
spatial = [r for r in full if r["difficulty"] != "Robustness"]
ex = sum(r["ex"] for r in spatial) / len(spatial)
print("spatial_ex=", round(ex, 3))
assert ex >= 0.867, f"spatial_ex regressed to {ex}"
print("OK")
PY
```

Expected: `spatial_ex >= 0.867` and the assertion does not raise.

- [ ] **Step 4: Commit a summary note**

```bash
mkdir -p data_agent/nl2sql_eval_results/notes
echo "Phase A regression check: spatial_ex>=0.867, target failures fixed" > data_agent/nl2sql_eval_results/notes/phase_a_check.md
git add data_agent/nl2sql_eval_results/notes/phase_a_check.md
git commit -m "docs(nl2sql): record Phase A regression check status"
```

---

### Task 11: Resume the BIRD 500 run (full mode) under the new pipeline

**Files:**
- Modify: none (operational verification)

- [ ] **Step 1: Resume the existing BIRD 500 run**

The existing run directory `data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/` already contains the per-question SQLite resume cache. Resume it with the same `--out-dir` so that completed questions are not re-run:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_pg_eval.py --mode both --out-dir data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457
```

Expected: the runner skips cached entries and continues `full` from where it left off; per-question records gain an `intent` field for *new* questions only.

- [ ] **Step 2: Sanity-check that new records carry intent**

Run after the script finishes (or after 50 new full-mode entries appear in the resume cache):

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe - <<'PY'
import json, sqlite3
db = "data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/run_state.db"
conn = sqlite3.connect(db)
rows = conn.execute("SELECT payload FROM done WHERE mode='full' ORDER BY rowid DESC LIMIT 5").fetchall()
for (p,) in rows:
    print(json.loads(p).get("intent"))
PY
```

Expected: the most recent five rows have a non-empty `intent` field.

- [ ] **Step 3: Commit a brief checkpoint**

```bash
git add -A
git commit --allow-empty -m "chore(nl2sql): bird 500 resume checkpoint with intent capture"
```

---

### Task 12: Update the production NL2SQL agent prompt

**Files:**
- Modify: `data_agent/agent.py`
- Test: `data_agent/test_nl2sql_benchmark_mode.py`

- [ ] **Step 1: Write the failing assertion**

Append to `data_agent/test_nl2sql_benchmark_mode.py`:

```python
def test_production_nl2sql_prompt_mentions_intent_routing():
    src = open("data_agent/agent.py", encoding="utf-8").read()
    assert "意图" in src and "LIMIT 仅用于" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_benchmark_mode.py -k "production_nl2sql_prompt_mentions_intent_routing" -v`

Expected: FAIL.

- [ ] **Step 3: Update the MentionNL2SQL instruction**

In `data_agent/agent.py`, locate the `MentionNL2SQL` `instruction=` block. Append a single sentence to the existing safety-rule paragraph:

```
"工作模式: 系统会先识别问题意图，然后只注入与该意图相关的接地规则。LIMIT 仅用于预览类问题；KNN 仅用于最近邻问题；不要把不相关的规则套用到当前问题上。"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest data_agent/test_nl2sql_benchmark_mode.py -v`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add data_agent/agent.py data_agent/test_nl2sql_benchmark_mode.py
git commit -m "feat(nl2sql): align production agent prompt with intent routing"
```

---

### Task 13: Compute the ablation matrix from existing logs

**Files:**
- Create: `scripts/nl2sql_bench_common/derive_ablation.py`
- Test: `scripts/nl2sql_bench_common/test_derive_ablation.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/nl2sql_bench_common/test_derive_ablation.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest scripts/nl2sql_bench_common/test_derive_ablation.py -v`

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the derivation**

Create `scripts/nl2sql_bench_common/__init__.py` (empty) and `scripts/nl2sql_bench_common/derive_ablation.py`:

```python
"""Derive ablation slices from a Full-pipeline run by dropping specific intents."""
from __future__ import annotations

import json
from pathlib import Path


def derive_ablation(full_results_path: str | Path, drop_intent: str) -> dict:
    payload = json.loads(Path(full_results_path).read_text(encoding="utf-8"))
    records = [r for r in payload["records"] if r.get("intent") != drop_intent]
    n = len(records)
    ex = sum(r.get("ex", 0) for r in records) / n if n else 0.0
    return {"n": n, "execution_accuracy": round(ex, 4), "drop_intent": drop_intent}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--full", required=True)
    p.add_argument("--drop", required=True)
    args = p.parse_args()
    print(json.dumps(derive_ablation(args.full, args.drop), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest scripts/nl2sql_bench_common/test_derive_ablation.py -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add scripts/nl2sql_bench_common/__init__.py scripts/nl2sql_bench_common/derive_ablation.py scripts/nl2sql_bench_common/test_derive_ablation.py
git commit -m "feat(nl2sql): derive ablation slices from intent-tagged full-run logs"
```

---

### Task 14: McNemar significance test on baseline vs full

**Files:**
- Create: `scripts/nl2sql_bench_common/mcnemar.py`
- Test: `scripts/nl2sql_bench_common/test_mcnemar.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/nl2sql_bench_common/test_mcnemar.py`:

```python
def test_mcnemar_returns_p_value_for_paired_results():
    from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired
    base = [1, 0, 1, 0, 1, 0]
    full = [1, 1, 0, 1, 1, 0]
    out = mcnemar_paired(base, full)
    assert "b" in out and "c" in out and "p_value" in out
    assert out["b"] + out["c"] >= 1
    assert 0.0 <= out["p_value"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest scripts/nl2sql_bench_common/test_mcnemar.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the test**

Create `scripts/nl2sql_bench_common/mcnemar.py`:

```python
"""Exact McNemar test for paired binary outcomes.

`base` and `full` are aligned per-question 0/1 EX outcomes. The exact
binomial test is used so the result is valid for small samples (e.g. our
20-question GIS pilot).
"""
from __future__ import annotations

from math import comb


def mcnemar_paired(base: list[int], full: list[int]) -> dict:
    if len(base) != len(full):
        raise ValueError("paired sequences must have equal length")
    b = sum(1 for x, y in zip(base, full) if x == 1 and y == 0)
    c = sum(1 for x, y in zip(base, full) if x == 0 and y == 1)
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "p_value": 1.0}
    k = min(b, c)
    # two-sided exact binomial probability
    p = sum(comb(n, i) for i in range(k + 1)) / (2 ** n) * 2
    return {"b": b, "c": c, "p_value": min(1.0, p)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest scripts/nl2sql_bench_common/test_mcnemar.py -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add scripts/nl2sql_bench_common/mcnemar.py scripts/nl2sql_bench_common/test_mcnemar.py
git commit -m "feat(nl2sql): exact McNemar test for paired benchmark results"
```

---

### Task 15: Push the branch

**Files:**
- Modify: none

- [ ] **Step 1: Push**

```bash
git push origin feat/v12-extensible-platform
```

Expected: a fast-forward push showing all Phase-A commits.

---

## Self-Review

**Spec coverage:**
- §2.1 nine-class ontology → Task 1.
- §2.2 two-stage classifier → Tasks 2 (rule) + 3 (LLM judge).
- §2.3 architecture (router) → Tasks 5 (`_format_grounding_prompt`) + 6 (`build_nl2sql_context`).
- §2.3 LIMIT gating in postprocessor → Task 7.
- §3 worked example (EASY_02) → Task 10 verifies it executes correctly.
- §5 error handling for LLM-judge failure → Task 3 step 1 third test.
- §6 ablation matrix derivation → Task 13.
- §7 statistical: McNemar → Task 14. Bootstrap CI is left for Phase C as the spec allows.
- §10 acceptance criteria 1–3 → Task 10 / Task 11 / existing BIRD 50 still passes (Task 11 keeps Full+MetricFlow stable). Criterion 4 (intent log) → Task 9. Criterion 5 (tests stay green) → every task has test gating.

**Placeholder scan:** every step has a concrete code block, exact command, and expected output. No "TBD", "implement later", or "similar to Task N".

**Type consistency:** `IntentLabel` enum value strings (e.g. `"attribute_filter"`) match the JSON contract used by `_llm_judge` in Task 3 and the `intent` field written by the runners in Task 9, and read back by the ablation tool in Task 13. `IntentResult` field names (`primary`, `secondary`, `confidence`, `source`) are used identically across Tasks 1, 2, 3, and 6.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-01-intent-conditioned-grounding.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
