# NL2SQL v7 — Plan: Schema-Hint-Free Benchmark + Cross-Family Re-evaluation

**Status**: planning (work starts after v6 close-out is committed and pushed).
**Target venue**: IJGIS.
**Title draft**: *NL2GeoSQL Benchmarks Beyond Schema Hints: Evaluating Semantic
Grounding without Question-Side Leakage*.
**Last updated**: 2026-05-11

---

## 1. Motivation

The v6 cycle established that a single grounding harness produces statistically
detectable within-family Execution-Accuracy gains across four LLM families on
the Chongqing 85-question Spatial benchmark (see `docs/nl2sql_v6_short_report.md`).
However, a post-hoc audit at the close of v6 found two methodological issues
that materially affect how the v6 numbers should be interpreted:

  1. **Question-side schema leakage.** 94% of Spatial questions contain
     parenthetical hints revealing ground-truth table names, column names,
     and PostGIS function names — work that semantic grounding is supposed
     to do. The v6 Δ is therefore a lower bound on grounding's true value.
  2. **Semantic-layer coverage gap.** Two of eleven benchmark tables
     (`cq_land_use_dltb`, `cq_osm_roads_2021`) were not registered in
     `agent_semantic_sources` / `agent_semantic_registry` at experiment time.
     v7 starts on a fully registered catalog.

v7 addresses both by (a) rewriting the benchmark in business-domain language
with no schema identifiers in the question text, (b) auditing and patching
the semantic catalog before any new run, and (c) re-running the 4-family
within-family Δ on the cleaned benchmark. The Δ between v6 (hinted) and v7
(clean) is itself a publishable independent contribution: it quantifies how
much LLM NL2SQL benchmark scores depend on question-side schema contamination.

## 2. Deliverables

  D1. `benchmarks/chongqing_geo_nl2sql_125q_business_lang.json` — LLM-rewritten
      business-language benchmark, manually reviewed.
  D2. `data_agent/nl2sql_eval_results/v7_final_4family_summary.json` —
      pooled 4-family within-family Δ on D1.
  D3. `data_agent/nl2sql_eval_results/v7_vs_v6_hint_contamination.json` —
      paired McNemar between v6-hinted Δ and v7-clean Δ per family.
  D4. `docs/nl2semantic2sql_v7_manuscript.{md,tex,pdf}` — IJGIS draft.
  D5. Catalog patch: full `agent_semantic_*` coverage for all 11 cq_* tables;
      XMI domain dictionary integrated as alias source.

## 3. Workstreams (P0–P5)

### P0 — Business-language benchmark (4–6h LLM + 2–3h manual review)

  - Tooling: `scripts/nl2sql_bench_cq/rewrite_business_lang.py`
  - Input per question: `golden_sql` + table/column descriptions from
    `agent_semantic_sources` / `agent_semantic_registry`.
  - Model: **Gemini 2.5 Pro** (preferred — quality > speed; long context for
    schema dictionary).
  - Output schema (per question):
    ```yaml
    id: CQ_GEO_EASY_01
    question_business: "..."         # NEW: business-language version
    question_original: "..."         # paren-stripped v7 intermediate
    question_v5: "..."               # original with hints (for diff)
    rewrite_notes: "..."             # LLM's reasoning for the rewrite
    golden_sql: "..."                # unchanged
    difficulty: ...                  # unchanged
    category: ...                    # unchanged
    target_metric: ...               # unchanged
    ```
  - Constraints on the LLM rewriter:
    * MUST NOT mention any cq_* table, any column name from gold SQL, or
      any PostGIS function name in `question_business`.
    * MUST preserve unit ("公顷"/"千米"/"度"), filter values, top-K limits.
    * MUST preserve "拒绝" intent on Robustness questions; in particular
      keep hallucinated table-name traps (cq_population_census etc.).
  - Manual review: 100% of 125 questions; reject any with semantic drift,
    re-prompt with explicit constraint reminder.

### P1 — Catalog audit and patch (2–3h)

  - Confirm 11 cq_* tables registered in `agent_semantic_sources` and
    `agent_semantic_registry` (post-v6-patch).
  - Coverage audit: for every column referenced in golden_sql, ensure at
    least one Chinese alias exists in `agent_semantic_registry.aliases`.
    Expected gaps include 联通通勤 columns ("扩样后人口"), 历史街区 columns,
    and 百度AOI 第一分类 hierarchy.
  - Add missing aliases. Estimated 30–60 missing rows.
  - **XMI integration**: load XMI compiled dictionary (11 modules / 2328
    classes / 1228 associations per current state) as a second alias
    source in `resolve_semantic_context`. This is the integration path
    decided in `xmi_semantic_layer_integration_20260511.md` (姿态 2).

### P2 — Cross-family re-run on clean benchmark (~12h wall-clock)

  - Same 4 families × baseline+full × N=3 protocol as v6.
  - Same runners with `--benchmark` pointing to D1.
  - Per-question timeout retained at 360s (cross-family fairness).
  - Gemma local: Ollama gemma4:31b @ 192.168.31.252:11434 (unchanged).
  - Output: `data_agent/nl2sql_eval_results/v7_4family_85q_<ts>/`.

### P3 — Hint-contamination quantification (1–2h analysis)

  - Reuse `pool_v6_4families.py`, parameterised on benchmark file.
  - Compute per-family v7-clean Δ + paired McNemar (b, c, p) — same metric
    as v6.
  - Compute v6-vs-v7 paired McNemar **on the harness's full-mode outputs**,
    per family, on the **same 125 qids**. This isolates the effect of
    question-text contamination from the effect of the harness itself.
  - Expected outcome: v7 baseline drops substantially (e.g. 0.53 → 0.30–0.40);
    v7 full drops less (0.66–0.68 → 0.55–0.62); the v7 Δ widens to
    +0.20–0.30. If observed, this is the v7 paper's headline finding.

### P4 — Gemini 3.x preview supplemental (when available)

  - Single within-family run on the clean benchmark when Gemini 3.x preview
    becomes accessible.
  - Reported as an appendix; not a fifth family for the main comparison.

### P5 — Paper draft (4–6 days of writing)

  - Structure:
    * Abstract: hint-contamination problem; clean-benchmark methodology;
      4-family validation; quantified contamination effect.
    * Introduction: text-to-SQL benchmarks and the hidden schema-linking
      shortcut problem.
    * Related work: BIRD, Spider 2.0, BEAVER, DIN-SQL, semantic-layer
      tools. Position the hint-contamination claim against prior critiques
      of NL2SQL benchmarks.
    * Methodology: paren-strip + business-language rewrite protocol; LLM
      rewriter prompt; manual review procedure; reproducibility checks.
    * Experiments: P2 results, per-family Δ + cross-family parity on
      clean benchmark.
    * Hint contamination measurement: P3 results, v6 vs v7 paired McNemar.
    * Discussion: implications for current published NL2SQL leaderboards;
      recommendations for future benchmark authors.
    * Limitations: 125 questions on a single domain; bilingual extension
      and BIRD extension as future work.
  - Target page count: 22–25 (IJGIS limit).

## 4. Timeline

Assumes v6 close-out (Phase 3 Gemma N=3 + L1 registry patch + commit/push +
short report) completes within 1 day after this plan is written.

| Day | Work |
|---|---|
| Day 0 | v6 close-out done. v7 plan reviewed. |
| Day 1 | P0 rewriter script + first 30 questions LLM-rewritten and reviewed. |
| Day 2 | P0 continue (remaining 95 questions), P1 catalog audit and patch in parallel. |
| Day 3 | P0 manual review complete. P2 starts (4 families × baseline+full × N=3). |
| Day 4 | P2 finishes overnight; P3 analysis. |
| Day 5–8 | P5 paper draft (Introduction, Related, Methods, Results, Discussion). |
| Day 9 | Co-author review, figures finalised, cover letter, submission to IJGIS. |
| Day 10+ | P4 Gemini 3.x supplemental (when available); reviewer responses if applicable. |

## 5. Dependencies and blockers

  - **DB availability**: PG 119.3.175.198:5432/flights_dataset must be up
    for the entire 12h P2 run. Snapshot recovery time: ~5min.
  - **Ollama host**: 192.168.31.252:11434 must remain reachable on LAN
    (Gemma path). Backup plan: Gemma 4 31B via AI Studio with retry-on-429
    runner (already implemented in `run_phase3_gemma_n3.py`, the
    pre-Ollama variant).
  - **Gemini API quota**: P0 LLM rewrite uses 2.5 Pro for 125 questions
    ≈ 500K input + 200K output tokens; well within free tier.
  - **DeepSeek API**: P2 needs ~500K tokens for 85q × N=3 full mode at
    ~30K tokens/q; within paid balance.
  - **No external review or coordination required** — solo project.

## 6. Decision log (carried from v6)

  - **2026-05-11**: Phase 3 Gemma not paused; benchmark rewrite is v7.
  - **2026-05-11**: Strict-mode strip — all parens removed including unit
    equations and business classification rules.
  - **2026-05-11**: Business-language rewrite chosen over bare-identifier
    handling, to avoid second-order leakage from Chinese table aliases.
  - **2026-05-11**: XMI integration (姿态 2) folded into P1; schema-validation
    XMI use (姿态 3) deferred to v8.
  - **2026-05-11**: BIRD multi-family extension explicitly out-of-scope per
    `nl2sql_v6_product_paper_alignment_20260510.md` user preference.

## 7. Out of scope for v7

  - BIRD multi-family extension (out per user preference; v6 product/paper
    alignment).
  - DuckDB Lite-mode backend (deferred indefinitely per
    `duckdb_litemode_deferred.md`).
  - DRL-side experiments (not in NL2SQL scope).
  - Frontend E2E verification of the new benchmark loader (also deferred
    per XMI integration memo).
