# Intent-Conditioned Grounding for NL2Semantic2SQL (Phase A)

> Date: 2026-05-01
> Branch: feat/v12-extensible-platform
> Triggered by: GIS Spatial EX regression (0.867 → 0.733) and reviewer comments asking for component-level ablations.
> Phase: A of A→B→C. B = automated MetricFlow coverage for all BIRD schemas; C = ablation, McNemar, and DIN-SQL comparison for the paper.

---

## 1. Problem statement

The current `nl2sql_grounding.build_nl2sql_context` injects every grounding rule (LIMIT enforcement, hierarchy expansion, geometry casting, KNN guidance, value hints, safety postprocessor, MetricFlow hints) for every question. This caused the GIS Spatial-EX regression observed in the May 1 run (`cq_2026-05-01_132919`):

- `CQ_GEO_EASY_02` truncated by an over-eager LIMIT.
- `CQ_GEO_EASY_03` rewrote `"DLMC" = '水田'` into `"DLBM" LIKE '0103%'` because hierarchy expansion fired on an exact-attribute query.
- `CQ_GEO_HARD_02` used `ORDER BY ST_Distance(...)` instead of the PostGIS KNN operator, despite the prompt rule, because the rule was diluted by competing rules.

Two reviewer reports independently flag (a) the regression, (b) the lack of component-level ablations, and (c) a Robustness/Spatial-EX accounting issue (already fixed in the manuscript). This spec proposes a single methodological change that addresses all three concerns at the source.

## 2. Solution: Intent-Conditioned Grounding

We introduce an explicit **intent classification stage** between the user question and the grounding-prompt assembler. Each intent activates a *subset* of the grounding rules instead of the full set. The rule set is unchanged; only the routing changes.

### 2.1 Intent ontology (9 classes)

| Intent | Activates | Suppresses |
|---|---|---|
| `attribute_filter` | value hints, exact-string match | hierarchy expansion, KNN, LIMIT |
| `category_filter` | hierarchy expansion, value hints | exact-string match |
| `spatial_measurement` | geometry casting, `ROUND(::numeric,N)`, SRID rules | KNN, LIMIT |
| `spatial_join` | geometry casting, `ST_Intersects` preference | KNN |
| `knn` | `<->` rule, ST_Distance only in SELECT | LIMIT injection |
| `aggregation` | MetricFlow join hints, aggregation-granularity rule | hierarchy expansion |
| `preview_listing` | LIMIT injection (large-table cap) | all other rules |
| `refusal_intent` | safety guardrail, canonical refusal | all other rules |
| `unknown` | Conservative full set (current behavior) | none |

**Key invariant.** `preview_listing` is the **only** intent that triggers LIMIT injection. This single change repairs the EASY_02 regression at the source.

### 2.2 Two-stage classifier

- **Stage 1 — rule-based (≤ 5 ms).** Keyword triggers (e.g. `最近的 N 个` → `knn`; `列出` / `显示` / `所有` → `preview_listing`; `修改` / `删除` → `refusal_intent`) plus pattern matches (literal `=` and column-named values → `attribute_filter`; category words such as `耕地`/`林地` → `category_filter`).
- **Stage 2 — LLM judge (≤ 1 token call).** When stage-1 confidence < 0.7, call `gemini-2.0-flash` with the 9-class definition and the question only. Schema is not included; the call is short and cheap.
- **Fallback.** Both stages fail / inconsistent → `unknown` → existing full-pipeline path.

### 2.3 Architecture

```
NL question
    │
    ▼
IntentClassifier      → {primary, secondary[], confidence}
    │
    ▼
GroundingRouter       → selects which rules to inject
    │
    ▼
PromptAssembler       → grounded prompt (rule subset, not full set)
    │
    ▼
LLM → SQL → SafetyPostprocessor → execute → result
                                       │
                                       └── self-correction loop (unchanged)
```

`SafetyPostprocessor` keeps its AST-level write-block check unconditionally. Only the *style* rules (LIMIT, identifier hints, KNN reminder) are gated on intent.

## 3. Worked example: EASY_02

Question: `列出所有限速 > 100 且 fclass = 'primary' 的道路名称`.

```
IntentClassifier  → primary=attribute_filter, conf=0.92 (rule)
Router            → enable: value hints (fclass)
                    disable: LIMIT, hierarchy expansion, KNN
PromptAssembler   → schema + value hint (`fclass ∈ {primary, secondary, ...}`)
LLM               → SELECT name FROM cq_osm_roads_2021
                    WHERE maxspeed > 100 AND fclass = 'primary'
SafetyPostproc    → no LIMIT injection (intent ≠ preview_listing)
Execute           → ✓ matches gold
```

The same routing fixes EASY_03 (intent = `attribute_filter` → no hierarchy expansion → `"DLMC"='水田'` is preserved) and tightens the KNN rule for HARD_02 (intent = `knn` → `<->` is the *only* ranking guidance the model receives).

## 4. Implementation plan (file-level)

| File | Type | Change |
|---|---|---|
| `data_agent/nl2sql_intent.py` | new | `IntentLabel` enum, `IntentResult` dataclass, `IntentClassifier` with `classify_rule()` and `classify_llm()`, deterministic fallback logic. |
| `data_agent/nl2sql_grounding.py` | edit | Refactor `build_nl2sql_context` so that the rule-injection block consults a `GroundingRouter` keyed on `IntentLabel`. Keep the current behavior under the `unknown` branch as a fallback. |
| `data_agent/sql_postprocessor.py` | edit | Surface `inject_limit` as a function of intent rather than a global flag; move the LIMIT-on-large-table heuristic inside the `preview_listing` branch. |
| `data_agent/test_nl2sql_intent.py` | new | ≥ 5 cases per intent (including 2 ambiguous cases per pair) plus a fallback test that asserts `unknown` keeps current behavior. |
| `data_agent/test_nl2sql_grounding.py` | edit | Add snapshot tests: for each intent, assert which rule strings appear / do not appear in the assembled prompt. |
| `scripts/nl2sql_bench_cq/run_cq_eval.py` | edit | Record `intent` and active routes in each per-question record so that ablation tables can be derived from the run logs without re-running. |
| `scripts/nl2sql_bench_bird/run_pg_eval.py` | edit | Same instrumentation as above. |
| `data_agent/agent.py` | edit | Update the production NL2SQL agent prompt so that it consumes the routed grounding output rather than the static prompt. |

## 5. Error handling

- IntentClassifier timeout (> 2 s) → degrade to `unknown` + full-rule injection.
- Multiple high-confidence intents → keep top-1 as `primary`, top-2 as secondary, OR them when constructing the active-rule set, but enforce mutually-exclusive rules (e.g. `attribute_filter` always wins over `category_filter` if both fire) using a deterministic priority table.
- LLM judge returns malformed JSON → trust the rule-stage label if any, else `unknown`.
- Postprocessor / executor errors → unchanged self-correction loop.

## 6. Ablation matrix (auto-produced from logs)

| Config | What is disabled |
|---|---|
| Full | nothing |
| – LIMIT routing | `preview_listing` falls back to full rule set |
| – KNN routing | `knn` falls back to full rule set |
| – hierarchy routing | `category_filter` is treated as `attribute_filter` |
| – value-hint routing | `attribute_filter` runs without value hints |
| – safety routing | `refusal_intent` falls back to full rule set |
| Baseline | direct LLM + schema dump |

Because the active routes are recorded per question, all ablation rows can be derived from a single Full run plus the Baseline run, without re-executing the full pipeline 6 times.

## 7. Validation

- **Unit.** ≥ 5 cases per intent. Snapshot tests on the assembled prompt.
- **Regression.** Re-run GIS 20 + BIRD 50 with timeout 180 s; expect EASY_02 / EASY_03 / HARD_02 to flip from ERR to OK and no other questions to regress.
- **Scale.** Re-run BIRD 500 (resume cache) and the in-progress 100-question GIS extension. Both happen in Phase B/C.
- **Statistical.** Add McNemar test (paired) and a paired bootstrap CI for Spatial-EX and BIRD-EX, both in the post-processing of the existing run logs.

## 8. Hand-off to Phase B and Phase C

- **Phase B — automated MetricFlow coverage.** The `aggregation` branch of the GroundingRouter calls into MetricFlow. Phase B fills MetricFlow models automatically (FK + sample-stat heuristics) for the remaining 10 BIRD schemas. The router does not need to change.
- **Phase C — paper-level补强.** The ablation matrix in §6 gives the exact rows the reviewers asked for; Phase C adds a DIN-SQL or MAC-SQL external baseline and a confidence-interval column to each table.

## 9. Out of scope

- Schema-linking neural models. We rely on the existing semantic layer.
- Fine-tuning the LLM. The judge prompt is zero-shot.
- New benchmark questions. Question construction is Phase B/C work.

## 10. Acceptance criteria

1. EASY_02, EASY_03, HARD_02 each move from ERR to OK on `cq_2026-05-01_132919` regression run.
2. GIS 20 Spatial EX no longer regresses below baseline (target ≥ 0.867).
3. BIRD 50 Full(+MetricFlow) overall EX ≥ 0.540 (no regression vs. current parity).
4. The full pipeline run produces a per-question intent log that lets §6's ablation matrix be computed offline.
5. All new modules ship with tests; existing tests remain green.
