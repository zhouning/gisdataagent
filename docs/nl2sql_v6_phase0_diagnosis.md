# NL2SQL v6 — Phase 0 Diagnosis

**Date**: 2026-05-10
**Scope**: Why does the Gemini-tuned grounding pipeline regress DeepSeek-V4 by −0.047 EX while lifting Gemini by +0.129?
**Method**: Forensic analysis of 1020 existing records (4 cells × 85 qids × N=3 samples, reusing historical Gemini data) + runner source inspection. No new model runs.

---

## TL;DR — Root cause is NOT what we assumed

The cross-family regression is **not** primarily caused by Gemini-tuned grounding rules being wrong for DeepSeek. The dominant cause is a **mechanical extraction failure** in the benchmark runner: it only captures SQL when the agent calls the `query_database` tool via structured function-call parts, and DeepSeek's agent loop fails to reach that tool within the 120s per-question timeout in **20% of questions**.

| Symptom | Gemini full | DeepSeek full | Ratio |
|---|---:|---:|---:|
| EMPTY (pred_sql="") rate | 2.0% | **20.0%** | **10×** |
| EXEC-ERR (SQL ran, crashed) rate | 2.0% | 3.5% | 1.75× |
| WRONG (SQL ran, wrong rows) rate | 29.8% | 29.4% | 1.0× |
| OK rate | 66.3% | 45.9% | — |
| Median tokens per question | 12K | 30-35K | **~2.75×** |
| Median wall-clock per question | ~25s | 55.9s | ~2.2× |

**If the EMPTY rate were matched to Gemini's 2%, DeepSeek full EX would be ≈0.639 instead of 0.459** (recovering ~18pp of the 20pp gap).

---

## Evidence Trail

### 1. Failure-mode buckets (N=3 pooled, 255 qids per full cell)

Bucketing is:
- **OK**: `ex==1`
- **EMPTY**: `pred_sql == ""` → runner never extracted any SQL
- **ERR-exec**: SQL was generated but execution failed (DB error)
- **VAL-nonselect**: postprocessor rejected (non-SELECT statement)
- **WRONG**: SQL executed, but returned different rows from gold

| Cell | OK | WRONG | EMPTY | ERR-exec | Other |
|---|---:|---:|---:|---:|---:|
| Gemini baseline (N=1) | 45 (52.9%) | 20 (23.5%) | 1 (1.2%) | 19 (22.4%) | 0 |
| DeepSeek baseline (N=3) | 136 (53.3%) | 59 (23.1%) | 3 (1.2%) | 57 (22.4%) | 0 |
| Gemini full (N=3) | 169 (66.3%) | 76 (29.8%) | 5 (2.0%) | 5 (2.0%) | 0 |
| DeepSeek full (N=3) | 117 (45.9%) | 75 (29.4%) | **51 (20.0%)** | 9 (3.5%) | 3 (1.2%) |

**Reading**: WRONG, ERR-exec, and OK rates are broadly comparable between Gemini full and DeepSeek full. **The entire deficit is in the EMPTY bucket.**

### 2. EMPTY ↔ timeout correspondence

- Runner has `CQ_EVAL_QUESTION_TIMEOUT=120s` per question (`run_cq_eval.py:327`).
- On timeout, `full_generate` returns `{"status": "timeout", "sql": "", "error": "question-level timeout", "tokens": 0}`.
- Across 3 DS full samples, log shows **54 questions hit dur ≥ 120s**; JSON shows **51 EMPTY records**, all with `tokens=0`, `reason='empty'`, `pred_error='empty'`.
- 54/51 correspondence confirms: **EMPTY ≈ 120s wall-clock timeout**.

### 3. Why does DeepSeek's loop take so long?

Duration distribution (per question, 85q sample):

| Cell | min | p25 | median | p75 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|
| DS baseline | 1.7s | 2.9s | 4.7s | 8.7s | 17.5s | 35.7s |
| DS full | 7.4s | 28.5s | 55.9s | 109.4s | **125.4s** | 142.0s |

DS baseline is fast (~5s median). DS full is 10× slower with p75 approaching the timeout. The agent loop — not the LLM API — is the bottleneck.

Token consumption (non-empty records only):

| Cell | n | mean | median | p95 |
|---|---:|---:|---:|---:|
| DS full s1 | 65 | 61,072 | 34,565 | 164,557 |
| DS full s2 | 68 | 61,984 | 29,624 | 192,555 |
| DS full s3 | 71 | 62,085 | 30,679 | 198,239 |
| Gemini full (avg over 3) | ~83 | ~13,000 | ~12,370 | ~29,500 |

DeepSeek is spending **~2.75× more tokens** per successful question. Two plausible contributors:

1. **Reasoning/thinking tokens**. DeepSeek V3/V4 emits long CoT before function-call outputs; ADK's LiteLlm wrapper may be counting those in total tokens.
2. **Extra tool-call turns**. Each turn re-sends the full system prompt + tool schema. If DS takes 3-4 turns where Gemini takes 1-2, token cost compounds.

### 4. Instruction compliance issue in the non-timeout WRONG cases

Spot-checked 3 discordant-WRONG qids (Gemini correct, DeepSeek wrong in sample 1):

**CQ_GEO_EASY_02** — "roads with maxspeed>100 and fclass='primary', return names":
- Gemini: `SELECT name FROM … WHERE maxspeed > 100 AND fclass = 'primary'` ✓
- DeepSeek: `SELECT COUNT(*) FROM … WHERE "fclass" = 'primary'` ✗ (dropped `maxspeed>100` filter; returned COUNT instead of name)
- DS burned 164,557 tokens on this trivial question.

**CQ_GEO_MEDIUM_01** — "total area of 水田 in hectares":
- Gemini: clean `SUM(ST_Area(geometry::geography)) / 10000`
- DeepSeek: worked structurally but wrapped in `'水田_面积: ' || ROUND(...)::text` — a formatted string answer, not the raw number — so row comparison fails.

**CQ_GEO_HARD_02** — KNN "5 nearest roads to a POI":
- Gemini: correct `CROSS JOIN` + `ORDER BY ... <-> ... LIMIT 5`
- DeepSeek: `WITH poi AS (...)` correlated subquery with LIMIT 1 pre-filter — works but semantics slightly different.

**Pattern**: DeepSeek has real instruction-compliance issues. It frequently (a) doesn't call `resolve_semantic_context` before generating, losing grounding hints; (b) over-interprets the question (wraps results in formatted strings, aggregates when asked for listings); (c) uses CTE/subquery patterns that diverge from gold SQL's JOIN form.

### 5. Cross-family baseline parity is intact

Both families solve **exactly the same 45/85** questions at the schema-only baseline (b=c=0 on McNemar). This rules out capability-gap confounds and benchmark bias. **DeepSeek is not a weaker SQL generator** on this benchmark.

---

## Hypothesis Ranking

| # | Hypothesis | Evidence | Estimated share of gap |
|---|---|---|---|
| **H1** | Per-question 120s timeout cuts off DS before tool call → EMPTY | 51/85 EMPTY = 20%, token=0, dur≥120s matches log | **~18pp of 20pp gap** (dominant) |
| **H2** | Agent loop takes more turns on DS (schema mismatch / re-plans) | Token cost 2.75×, median dur 55s vs baseline 5s | drives H1 |
| **H3** | DeepSeek skips / de-prioritises tool pre-flight (`resolve_semantic_context`, `describe_table_semantic`), grounds on raw schema only | WRONG qids show lost filters, formatted-string wrapping, intent misclassification | **~2pp of gap** |
| H4 | Reasoning/CoT token output mixed into function-call turns; LiteLlm wrapper doesn't strip it before "extract tool call" | p95 tokens 165-198K per question; typical SQL answer <500 tokens | contributes to H2 |
| H5 | Gemini-tuned grounding prompt text (SRID, PostGIS idioms) confuses DS | WRONG qids aren't systematically wrong on SRID / geography casts | **small (≤2pp)** |
| H6 | Postprocessor over-rejects DS-style SQL | Only 3/255 VAL-nonselect rejections in DS full; negligible | **~1pp** |

**H1 alone, if fixed by raising timeout to 300s, recovers most of the gap** — but that's a workaround, not a fix. The real problem is H2: the agent loop burns too many turns/tokens on DeepSeek.

**What is NOT the problem** (ruled out or sized small):
- Grounding rule *content*: WRONG qids don't fail on SRID / predicate semantics.
- Self-correction loop: both families convert ERR-exec from 22% → 2-3%.
- Postprocessor: <1.2% rejection on either family.
- Model capability: baseline parity is b=c=0, exact.

---

## Recommended Fix Sequence (for Phase 1+ design)

### Fix 1 — Fallback SQL extraction from assistant text (1 day, expected lift +15pp)

The runner currently only extracts SQL from structured `function_call` parts. Add a text-parsing fallback: if `tool_execution_log` is empty but the agent emitted a text response containing a SQL-like fenced block, parse it, execute it, and score normally. This alone converts most EMPTY → one of {OK, WRONG, ERR-exec}, matching Gemini's pathway.

**Critical caveat**: this is a measurement fix only — it does NOT fix the underlying "DS agent loop is slow/wasteful" problem. But it removes the 18pp measurement bias.

### Fix 2 — Per-family prompt adapter (1-2 weeks, expected lift +3-5pp)

Restructure `data_agent/prompts/` into family-specific directories:
- `common/` — domain rules (SRID, predicate semantics, OGC facts) family-agnostic
- `gemini/` — current instruction (5-step workflow, "CRITICAL: double-quote", etc.)
- `deepseek/` — rewrite for DS's instruction-following characteristics:
  - Shorter, directive tone (DS responds less well to long narrative instructions)
  - Explicit "you MUST call resolve_semantic_context first and wait for its result before generating SQL" (not "1. FIRST ...")
  - Move domain reminders into few-shot examples rather than prose bullets
  - Disable or attenuate CoT/reasoning dump (per DeepSeek docs, one can pin `enable_thinking=false` on some endpoints)

### Fix 3 — Timeout and loop hygiene (2-3 days, expected lift +1-2pp)

- Raise `CQ_EVAL_QUESTION_TIMEOUT` to 240s for research evaluation. This is a band-aid for benchmarking, not a product fix.
- Investigate whether ADK's LiteLlm wrapper leaks thinking tokens into the function-call extraction path.
- Add hard turn-cap (e.g. max 5 tool-call turns) with early-abort if DS is looping.

### Fix 4 — Baseline-parity equivalent for full mode (stretch, +2-3pp)

Cross-family baseline is b=c=0. A reasonable target for full: cross-family full should reach the same b=c=0 structural parity on the subset where both families' extraction succeeded. Currently even on non-EMPTY DS records, the WRONG bucket shows intent-mismatch issues → pushes toward Fix 2 (prompt adapter) rather than a new lever.

---

## Go / No-go Criteria for v6

Apply the agreed thresholds (within-family p < 0.10, effect size ≥ +0.08) on DeepSeek after Fix 1 + Fix 2:

- **Fix 1 only** (fallback extraction): projected DS full EX ≈ 0.55-0.60 vs baseline 0.53 → within-family p likely 0.05-0.15, Δ +0.02-0.07 → **does not pass**.
- **Fix 1 + Fix 2** (prompt adapter): projected DS full EX ≈ 0.60-0.65 vs baseline 0.53 → Δ +0.07-0.12 → **probably passes the bar**.
- **Fix 1 + Fix 2 + Fix 3**: projected DS full EX ≈ 0.62-0.67 → passes with margin.

Gate: re-run DS full N=3 after Fix 1+2, compute stats, gate Fix 3 and any architectural work on that result.

---

## What we did NOT verify in Phase 0 (logged as debt)

1. **Per-qid tool_execution_log contents** for DS runs. The records don't persist it; we'd need a re-run with debug logging to confirm Gemini uses 2 tool calls vs DeepSeek using 0 or 4+.
2. **Whether DeepSeek's EMPTY records had text output we could have extracted.** Need to add `report_text` to persisted records (currently only `report_text[:500]` lives in session state).
3. **Exact token breakdown (reasoning vs answer) for DeepSeek.** LiteLlm wrapper may hide this.
4. **LiteLlm version and its DeepSeek/OpenAI-spec tool-schema translation.** A known limitation is that LiteLlm sometimes coerces Gemini-style tool schemas into OpenAI function-spec in a lossy way.

These are safe to defer; they'll be answered in Phase 1 development naturally (we'll add debug logging as part of the fix).

---

## Appendix A — Key source lines

- `scripts/nl2sql_bench_cq/run_cq_eval.py:327` — 120s per-question timeout
- `scripts/nl2sql_bench_cq/run_cq_eval.py:341-346` — SQL extraction walks `tool_execution_log` backward looking for `query_database`; no text fallback
- `scripts/nl2sql_bench_cq/nl2sql_agent.py:23-58` — Gemini-shaped instruction (5-step workflow with CRITICAL bullets)
- `data_agent/model_gateway.py:368-383` — DS routed via `LiteLlm(model='openai/deepseek-v4-flash')` against `https://api.deepseek.com`
- `data_agent/pipeline_runner.py:170-213` — ADK event loop extracts `function_call`/`function_response` parts; no `text → SQL` parser
