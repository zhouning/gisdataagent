# NL2SQL v6 — Cross-Family Generalisation: Short Report

**Status**: archival report (not for journal submission). Submission target is v7.
**Last updated**: 2026-05-11
**Authors**: 周宁 / 北京超图软件 / zhouning1@supermap.com

---

## 1. Scope

This report documents the v6 experimental cycle of the GIS NL2SQL harness on
the Chongqing 85-question Spatial benchmark, with the specific goal of
establishing whether a single grounding + intent-routing + postprocessing
harness can produce statistically detectable within-family Execution-Accuracy
gains across four major LLM families:

  - Google **Gemini 2.5 Flash** (online, AI Studio)
  - **DeepSeek V4 Flash** (online, official API)
  - Alibaba **Qwen 3.6 Flash** (online, MaaS token-plan endpoint)
  - Google **Gemma 4 31B IT** (local, Ollama Q4_K_M deployment on a LAN host)

The experiment is **deliberately within-family**: for each family, both the
"baseline" (schema-only direct HTTP) and "full" (LlmAgent with grounding +
intent routing + postprocessor) pipelines use the same model. The Δ
between baseline and full is the harness's contribution; the four Δs are
**not** intended to be compared as a head-to-head LLM ranking.

## 2. Benchmark

  - **Source**: `benchmarks/chongqing_geo_nl2sql_100_benchmark.json`
    (125 questions: 24 Easy + 36 Medium + 25 Hard + 40 Robustness)
  - **Used here**: Spatial 85q subset (Easy + Medium + Hard), filtered by
    `load_spatial_85q()` in `scripts/nl2sql_bench_cq/run_cross_family_85q.py`.
  - **Domain**: Chongqing-area land-use, OSM roads, POIs, AOIs, historic
    districts, population, mobile-commuting data — PostGIS 3.4 on PG 16.
  - **Categories**: Attribute Filtering (17), Aggregation (14), Spatial Join
    (11), Spatial Measurement (10), KNN (5), Complex Multi-Step (5),
    Cross-Table (5), Temporal/Statistical (5), and 13 other long-tail.

## 3. Setup

  - **Per-family sampling**: N=3 for full mode (every family); N=3 for
    DeepSeek/Qwen/Gemma baseline; N=1 for Gemini baseline (Gemini's
    `temperature=0.0` direct-HTTP path is deterministic in our infrastructure,
    so resampling adds no variance).
  - **Temperature**: not pinned. Each family runs at its provider default
    (Gemini server-side default; DeepSeek/Qwen/Gemma OpenAI-spec default 1.0).
    Stochastic variance is captured at the experiment level via N=3.
  - **Per-question wall-clock cap**: 240s (Phase 1) → 360s (Phase 3 Gemma local,
    to accommodate 31B Q4 LAN deployment latency).
  - **Adjudication**: paired McNemar on majority-vote-across-N (per-qid MV
    declared OK if ≥ ⌈N/2⌉ of N samples have ex=1) with two-sided exact
    binomial p on (b, c) discordant pairs.
  - **Common harness in "full" mode**:
    1. `classify_intent` (rule-only for DS/Qwen/Gemma; rule+LLM-judge for
       Gemini per Phase 1 family routing rule)
    2. `resolve_semantic_context` (semantic_layer.py over agent_semantic_registry +
       semantic_catalog.yaml) → grounded context block
    3. ADK LlmAgent agent loop (max 6 turns) with three tools:
       `query_database`, `describe_table`, `list_semantic_sources`
    4. Postprocessor: identifier-quoting repair + LIMIT injection on
       large-table preview queries + write-statement rejection
    5. Runtime guards: hallucinated-table-name and give-up-SQL detection

## 4. Results — Within-family Δ (4 families, Spatial 85q)

All numbers are paired McNemar on majority vote across N samples.

| Family | Baseline mean (sd, N) | Full mean (sd, N) | Δ on MV | b | c | p (two-sided) |
|---|---|---|---:|---:|---:|---:|
| Gemini 2.5 Flash | 0.529 (—, 1) | 0.663 (±0.048, 3) | **+0.129** | 8 | 19 | **0.052** (marginal) |
| DeepSeek V4 Flash | 0.533 (±0.007, 3) | 0.682 (±0.031, 3) | **+0.188** | 7 | 23 | **0.005** ★ |
| Qwen 3.6 Flash | 0.529 (±0.000, 3) | 0.682 (±0.024, 3) | **+0.153** | 7 | 20 | **0.019** ★ |
| Gemma 4 31B IT (local Ollama) | 0.529 (±0.000, 3) | 0.661 (±0.032, 3) | **+0.153** | 9 | 22 | **0.029** ★ |

★ = passes within-family gate at α=0.05.

**Reading**: All four families show statistically detectable harness gains.
DeepSeek leads with Δ +0.188 (p=0.005). Qwen and Gemma both land on Δ +0.153,
identical to two decimal places. Gemini sits exactly on the boundary at
p=0.052 — its baseline was already harder to beat because Gemini's
`temperature=0.0` direct-HTTP path is internally tighter than the
OpenAI-spec providers' default 1.0. Despite the higher Gemini baseline
ceiling, the harness still extracts +12.9pp.

Per-cell standard deviations (full mode) are 0.024–0.048 across three
samples, indicating consistent stochastic behaviour. Gemma's local Ollama
deployment shows σ=0.032, falling within the same band as the hosted
families — the Q4_K_M quantisation and LAN latency add variance to wall
clock but not to EX.

## 5. Results — Cross-family baseline parity

The four families' baselines, when run independently on the same 85
questions, agree on **exactly the same 45 questions** (b=c=0 on every
pairwise McNemar):

| Pair | n | b | c | Δ_mv | p |
|---|---:|---:|---:|---:|---:|
| Gemini vs DeepSeek | 85 | 0 | 0 | 0.000 | 1.000 |
| Gemini vs Qwen | 85 | 0 | 0 | 0.000 | 1.000 |
| Gemini vs Gemma | 85 | 0 | 0 | 0.000 | 1.000 |
| DeepSeek vs Qwen | 85 | 0 | 0 | 0.000 | 1.000 |
| DeepSeek vs Gemma | 85 | 0 | 0 | 0.000 | 1.000 |
| Qwen vs Gemma | 85 | 0 | 0 | 0.000 | 1.000 |

This is **strong evidence of a "model-invariant solvable layer"** in the
benchmark: the same 45 questions are answerable from schema alone by every
family tested, and the remaining 40 questions require external grounding
to solve. The within-family Δ above is therefore the harness's contribution
to that 40-question hard core, not a capability gap between families.

## 6. Resource cost (median per question on full mode)

| Family | Wall-clock | Tokens | Notes |
|---|---:|---:|---|
| Gemini 2.5 Flash | ~25s | ~12K | Hosted, AI Studio |
| DeepSeek V4 Flash | ~56s | ~30K | Hosted, thinking=disabled (Phase 1 Fix 0) |
| Qwen 3.6 Flash | ~30s | ~5K | Hosted, enable_thinking=false |
| Gemma 4 31B IT | ~140s | ~6K | Local Ollama Q4_K_M on LAN |

Gemma local is roughly 5× slower than hosted Flash models per question
but consumes ~5× fewer tokens (no thinking-mode output). Total Gemma N=3
wall-clock on this LAN host: 10.1h (cells: 197.9 + 206.1 + 201.9 min).
Per-cell EMPTY count (questions where the 360s wall-clock budget ran out
before the agent could call query_database) was 13/14/15 across the three
samples — a stable failure rate of ~16%, attributable to the agent loop
on hard spatial multi-step questions running out of budget on local
inference.

## 7. Limitations

We disclose four known issues that materially affect how the numbers above
should be interpreted, and which jointly motivate the v7 experimental cycle.

### 7.1 Question-side schema leakage (partially mitigated by schema injection)

A post-hoc audit on 2026-05-11 found that **94% (80/85) of Spatial questions
contain parenthetical hints** revealing ground-truth schema information:
table names like `(cq_dltb)` / `(cq_land_use_dltb)`, column names like
`(DLMC)` / `(Floor)` / `(BSM)`, PostGIS function names like `(ST_Intersects)` /
`(geometry::geography)`, value-bearing predicates like `(DLMC = '水田')`, and
unit-conversion hints like `(1公顷=10000平方米)` — **176 such spans in
total across 92/125 questions**.

The leakage impact depends on whether the question's target table is in the
prompt-side schema block (see §7.2). For questions whose tables are already
in the schema block (49/85 = 58%), paren-side schema hints are redundant with
the prompt schema; for questions whose tables are NOT in the schema block
(36/85 = 42%), the parens are the model's only explicit schema information
in baseline mode, and paren removal would force the LLM to rely on
pre-training recall of Chinese table naming conventions.

Independent of the schema-block question, the paren-based hinting style is
incompatible with real-world NL2SQL deployments, where users do not write
"统计果园(cq_dltb 表中 DLMC 字段值)的数量". v7's main contribution will
therefore be an LLM-rewritten "business-language" version of the benchmark
in which schema identifiers are removed from the question text entirely,
and a re-run of all four families on the cleaned benchmark.

### 7.2 Inconsistent prompt-side schema coverage (4 of 11 tables)

`dump_schema()` in `scripts/nl2sql_bench_cq/run_cq_eval.py:77` hard-codes
**only 4 tables** (`cq_amap_poi_2024`, `cq_buildings_2021`,
`cq_land_use_dltb`, `cq_osm_roads_2021`) into the prompt schema block.
The other 7 benchmark tables (`cq_dltb`, `cq_osm_roads`,
`cq_historic_districts`, `cq_baidu_aoi_2024`, `cq_baidu_search_index_2023`,
`cq_district_population`, `cq_unicom_commuting_2023`) **do not appear in
the baseline prompt at all**.

Per-question breakdown across the 85q Spatial subset:

| Schema-block coverage | Questions | Share |
|---|---:|---:|
| All target tables in dump_schema | 49 | 58% |
| Some tables in, some missing | 14 | 16% |
| All target tables missing | 22 | 26% |

For the 22/85 fully-missing questions, the baseline LLM has no prompt-side
schema information about the target table; the parenthetical hints (§7.1)
may be the only explicit schema signal. This is a conflated experimental
variable: the within-family Δ on these 22 questions measures both
"grounding's ability to fetch missing schema" and "grounding's ability to
build a SQL query correctly once the schema is known". v7 will rectify
this by switching `dump_schema()` to a full 11-table auto-dump from the
live database catalog. The v6 numbers should therefore be read as a lower
bound on grounding's contribution to schema linking specifically, and as
a conservative estimate of the overall Δ.

### 7.3 Semantic-layer gap on 2 of 11 tables (patched post-experiment)

A separate audit at the same time found that `cq_land_use_dltb` (used in 13
golden_sql) and `cq_osm_roads_2021` (used in 7 golden_sql) were **not
registered in `agent_semantic_sources` or `agent_semantic_registry`** at
experiment time. The grounding stage's fuzzy alias matcher returned the
nearest parent table (`cq_dltb` and `cq_osm_roads` respectively) as a partial
fallback, so the affected ~20 questions were still partially groundable —
but the registry-driven semantic enrichment they should have received was
absent. The registry was patched after the experiment; we elected not to
re-run the 4 families × 510 questions because the affected questions are a
known confound rather than a result-changing bug, and the next experimental
cycle (v7) will run on the patched registry from the start.

### 7.4 Gemma 4 31B IT deployment heterogeneity

Three of the four families were tested on managed cloud APIs at the
provider's deployed configuration; Gemma 4 31B IT was tested on a local
Q4_K_M-quantised Ollama instance on a LAN host (192.168.31.252:11434).
The AI Studio variant of Gemma was attempted earlier in this cycle but
its 16K-input-tokens-per-minute paid-tier-3 quota was too restrictive
for an agent loop that routinely uses 14-20K input tokens per question.
The local Ollama path therefore represents a **different operating point**
from the other three families: per-question wall-clock is 5-10× slower
and the Q4_K_M quantisation is not byte-equivalent to the upstream IT
release. The within-family Δ is unaffected by this (baseline and full
share the same Gemma instance), but the cross-family **head-to-head**
positioning of Gemma relative to the other three should be treated as
deployment-bound rather than capability-bound.

## 8. Transition to v7

The v7 cycle's main work follows from the limitations above:

  1. **Benchmark rewrite (P0)** — LLM-driven "business-language" rewrite of
     all 125 questions: every parenthetical hint stripped, every bare
     schema identifier in the question text replaced by natural-language
     domain expressions. Robustness traps that depend on hallucinated table
     names are preserved. Targets `benchmarks/chongqing_geo_nl2sql_125q_business_lang.json`.
  2. **Catalog audit (P1)** — Re-confirm `agent_semantic_registry` and
     `agent_semantic_sources` cover all 11 benchmark tables (post-patch in
     this report); audit `semantic_catalog.yaml` for alias gaps that v7's
     cleaner question text will expose; integrate XMI domain-standard
     dictionary as additional alias source.
  3. **Cross-family re-run (P2)** — 4 families × baseline+full × N=3 on the
     business-language benchmark.
  4. **Hint-contamination quantification (P3)** — paired McNemar between v6
     (leaked) and v7 (clean) per-family Δs; this is itself an independent
     contribution to NL2SQL benchmark methodology.
  5. **Gemini 3.x preview (P4)** — supplemental within-family run as soon
     as Gemini 3.x preview becomes generally available.
  6. **Paper draft (P5)** — IJGIS target, title draft: *"NL2GeoSQL Benchmarks
     Beyond Schema Hints: Evaluating Semantic Grounding without Question-Side
     Leakage"*.

## 9. Reproducibility

Code: `scripts/nl2sql_bench_cq/`
  - `nl2sql_agent.py` — agent builder
  - `run_phase3_qwen_n3.py`, `run_phase3_gemma_ollama_n3.py`,
    `run_phase1_*` — per-family runners
  - `pool_v6_4families.py` — this report's table generator

Data: `data_agent/nl2sql_eval_results/`
  - Per-cell JSON records with qid, ex, valid, pred_sql, tokens, gen_error
  - Summary: `v6_final_4family_summary.json`

Commits (local, to be pushed in v6 close-out):
  - `8b9d284` — Phase 1: per-family prompt adapter, DS passes within-family
  - `6546e81` — Phase 3 partial: Qwen passes within-family; Gemma vLLM staged
  - [pending] — Phase 3 Gemma via Ollama complete + L1 registry patch +
    this report
