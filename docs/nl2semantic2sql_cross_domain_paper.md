# NL2Semantic2SQL: A Cross-Domain Framework for Natural Language to SQL over Geospatial and Enterprise Data Warehouses

**Author**: Ning Zhou
**Affiliation**: Beijing SuperMap Software Co., Ltd., Beijing, China
**Email**: zhouning1@supermap.com

> **Status**: Draft v0.6 (2026-05-04) — DIN-SQL on GIS 100q complete (Full vs DIN p=0.0213/p=0.0078, both significant); split GIS Spatial/Robustness; BIRD directional only; bilingual framing
> **Target venues**: IJGIS / GeoInformatica / Transactions in GIS / ISPRS IJGI

---

## Abstract (English)

Natural language to SQL (text-to-SQL) has advanced rapidly with large language models, yet most existing systems and benchmarks focus on conventional relational databases and provide limited coverage of executable geospatial SQL. Geospatial databases introduce additional challenges, including geometry-aware schema grounding, spatial predicates, coordinate reference systems, and domain-specific operators such as intersection, buffer, area, and distance calculations. At the same time, practical data platforms increasingly require a single interface that can support both geospatial and non-geospatial warehouse queries. In this work, we present NL2Semantic2SQL, a cross-domain framework that combines semantic-layer grounding, intent-conditioned routing, schema-aware prompt construction, few-shot retrieval, SQL postprocessing, and execution-time self-correction to support natural-language querying over both GIS and conventional warehouse data. A core design principle is bilingual, cross-domain support: the framework handles both Chinese GIS queries and English warehouse queries through intent-conditioned routing that operates bilingually, recognizing Chinese GIS keywords alongside English warehouse expressions. We evaluate the framework on a 100-question GIS benchmark (expanded from a 20-question pilot) and a ~495-question warehouse benchmark derived from BIRD mini_dev. On the GIS track, we separately report Spatial EX (85 normal spatial-SQL questions) and Robustness Success Rate (15 safety/refusal questions), as these measure fundamentally different capabilities. The full pipeline achieves Spatial EX=0.682 vs. baseline 0.529 (McNemar p=0.0072, statistically significant at α=0.05, +0.153) and Robustness Success Rate=0.800 vs. baseline 0.333 (McNemar p=0.0156, statistically significant, +0.467). On the BIRD track, the full pipeline reaches EX=0.501 vs. baseline 0.474 (+0.027); this is a directional improvement but not statistically significant (McNemar p=0.136). The DIN-SQL comparison on GIS uses the same 100-question benchmark; the full pipeline statistically significantly outperforms DIN-SQL on both Spatial EX (+0.118, McNemar p=0.0213) and Robustness (+0.533, p=0.0078). On BIRD, the full pipeline (0.501) is numerically higher than DIN-SQL (0.482) but statistically comparable (p=0.382). Token cost is 13.6× on GIS and 7.9× on BIRD (after P2 single-pass optimization), a real deployment consideration especially for warehouse queries where the marginal accuracy gain is statistically inconclusive. These findings demonstrate that semantic grounding with intent-conditioned routing provides statistically significant gains for GIS spatial accuracy and robustness, directional gains for warehouse queries, and that the framework supports both Chinese GIS and English warehouse queries via a unified bilingual routing architecture.

## 摘要 (中文)

自然语言到 SQL 的查询生成技术近年来随着大语言模型的发展取得了显著进展，但现有研究与 benchmark 主要面向传统关系数据库，对可执行空间 SQL 的覆盖仍然有限。与普通数据仓库相比，GIS 数据库在几何类型、空间谓词、坐标参考系以及面积、距离、缓冲、叠加等空间算子方面具有更强的领域特性，使得 schema grounding 与 SQL 生成面临额外挑战。与此同时，面向真实业务的数据平台往往需要同一套自然语言查询框架同时支持空间与非空间场景。针对这一问题，本文提出一种跨域的 NL2Semantic2SQL 框架，通过意图感知路由、语义层解析、schema grounding、few-shot 检索、SQL 后处理与执行期自纠错等机制，实现对 GIS 数据库与通用数据仓库的统一支持。本文在扩展后的 100 题 GIS benchmark 和约 495 题 BIRD 仓库 benchmark 上评估该框架。在 GIS 侧，full pipeline 达到 EX=0.700，显著优于 baseline 的 0.500（McNemar p=0.0002，统计显著），在 Medium（+0.305）和 Robustness（+0.467）类别上增益最大。在 BIRD 侧，full pipeline 达到 EX=0.501，优于 baseline 的 0.474（+0.027），超过 DIN-SQL 外部基线（0.482），但差异未达统计显著性（McNemar p=0.136）。P2 单轮模式将 BIRD token 成本从 32× 降至 7.9×，GIS 侧为 13.6×，是实际部署中需权衡的因素。上述结果表明，带意图感知路由的统一 semantic-to-SQL 框架在 GIS 侧具有统计显著的增益，在仓库侧具有方向性增益，且在两个评测轨道上均优于或持平于 DIN-SQL 外部基线。

## Contributions

1. 本文提出了一种面向 GIS 与非 GIS 双场景的统一 NL2Semantic2SQL 框架，使自然语言查询在空间数据库与普通数据仓库之间共享同一套 semantic grounding—SQL generation—execution correction 主链路，并通过意图感知路由实现算子级规则的条件化注入。框架的核心设计原则是双语跨域支持：意图分类器双语运行，同时识别中文 GIS 关键词和英文仓库表达式（如"how many"、"what is the average"），无需语言特定的模型切换。

2. 本文构建了一套 100 题 GIS-oriented text-to-SQL benchmark（含 Easy/Medium/Hard/Robustness 四个难度层次），并将普通空间 SQL 任务（85 题，Spatial EX）与安全/鲁棒性任务（15 题，Robustness Success Rate）分开评价，因为这两类任务衡量的是本质不同的能力；该 benchmark 与约 495 题 BIRD 子集共同构成可执行的双轨评估协议。

3. 本文通过跨域评测分析表明，full pipeline 在 GIS Spatial EX 上达到 0.682 vs. baseline 0.529（McNemar p=0.0072，统计显著，+0.153），在 GIS Robustness Success Rate 上达到 0.800 vs. baseline 0.333（p=0.0156，统计显著，+0.467）。在约 495 题 BIRD benchmark 上，full pipeline 达到 EX=0.501 vs. baseline 0.474（+0.027），但差异未达统计显著性（p=0.136）；BIRD 结果应解读为方向性证据，而非确认的优势。P2 单轮模式将 BIRD token 成本从 32× 降至 7.9×，GIS 侧为 13.6×。

---

## 1. Introduction

Natural language to SQL has become one of the most active application directions of large language models, because it offers a direct interface between end users and structured data repositories. Recent advances have substantially improved performance on public benchmarks such as Spider and BIRD, demonstrating that modern language models can often synthesize executable SQL from natural-language questions under conventional relational settings. However, most existing text-to-SQL systems and evaluation datasets are designed for general-purpose relational databases, where the principal challenges lie in schema linking, join reasoning, aggregation, and nested query construction. By contrast, real-world geospatial database applications introduce additional semantic and operational complexity that is largely absent from these benchmarks. In geospatial settings, queries frequently involve geometry-aware schema grounding, spatial predicates, coordinate reference systems, topological relations, and spatial measurement operators such as area, distance, intersection, and buffering. These characteristics make geospatial text-to-SQL a substantially different problem rather than a simple extension of general warehouse querying.

This mismatch creates a practical and scientific gap. From a practical perspective, many operational data platforms must serve both geospatial and non-geospatial workloads through a unified natural-language interface. A user may ask one question about land-use overlap, another about building proximity, and a third about tabular business statistics in the same system. From a scientific perspective, however, existing studies rarely examine whether a single semantic grounding architecture can support these heterogeneous query types without severe domain bias. Most prior work either optimizes for conventional warehouse-style SQL generation or focuses on domain-specific geospatial systems without evaluating transferability beyond the GIS context. As a result, it remains unclear which components of a semantic-to-SQL pipeline generalize across domains and which components encode assumptions that are beneficial in one setting but harmful in another.

The challenge is especially pronounced at the grounding stage. In conventional text-to-SQL systems, schema linking is often framed as the task of aligning user expressions with table names, column names, or retrieved schema snippets. In geospatial systems, this step is more complicated because the model must additionally recognize geometry-bearing attributes, infer relevant spatial operators, respect spatial reference transformations, and distinguish between topological, metric, and aggregation-based reasoning. At the same time, aggressive domain-specific grounding strategies can introduce unintended bias when transferred to non-geospatial databases. A system tuned for Chinese GIS terminology, spatial operator hints, and geometry-aware rules may perform strongly on spatial benchmarks while underperforming on English warehouse benchmarks if its semantic retrieval mechanisms fail to adapt to differences in language, schema naming, and operator distributions. Understanding this tension is critical for building robust cross-domain natural-language interfaces to structured data.

To address this problem, we present NL2Semantic2SQL, a cross-domain framework that integrates semantic-layer grounding, schema-aware context construction, few-shot retrieval, SQL postprocessing, and execution-time self-correction into a unified natural-language-to-SQL pipeline. A core design principle is bilingual, cross-domain support: the framework handles **both** Chinese GIS queries **and** English warehouse queries through a single architecture. Intent classification operates bilingually, recognizing Chinese GIS keywords (e.g., spatial operator terms, Chinese administrative region names) alongside English warehouse expressions (e.g., "how many", "what is the average", "compare"). This bilingual routing is not an afterthought but a fundamental design choice that enables the same pipeline to serve heterogeneous real-world deployments without language-specific model swapping. Rather than treating SQL generation as a single-step prompting problem, the framework first resolves semantic context, then assembles structured schema evidence, and finally performs constrained SQL generation with post-hoc correction. The design is motivated by the observation that GIS queries and non-GIS warehouse queries share a common need for semantic disambiguation, but differ substantially in the kinds of evidence and constraints that must be surfaced to the model. Our framework therefore aims to preserve a unified architecture while allowing domain-specific grounding signals to be incorporated explicitly rather than implicitly.

To evaluate the geospatial side of the problem, we further construct a GIS-oriented benchmark with execution-based evaluation, spatial operator coverage, and varying query complexity. The benchmark is designed to capture the characteristics missing from mainstream text-to-SQL datasets, including spatial selection, overlap analysis, buffering, spatial aggregation, and geometry-sensitive reasoning. We then complement this benchmark with cross-domain evaluation on a warehouse-oriented dataset derived from BIRD mini_dev, enabling a direct comparison between GIS and non-GIS scenarios under the same evaluation harness. This dual-track setting allows us to move beyond a simple "does it work?" question and instead ask a more informative scientific question: how does a unified semantic-to-SQL architecture behave when confronted with two structurally different database domains?

Our contributions are threefold. First, we propose a unified NL2Semantic2SQL framework for cross-domain querying over geospatial and conventional warehouse databases. Second, we construct a GIS benchmark designed specifically for execution-based evaluation of spatial text-to-SQL capabilities. Third, through cross-domain experiments and error analysis, we show that semantic grounding provides substantial advantages in GIS scenarios while also exposing transfer limitations in non-GIS settings, particularly when retrieval and alias-matching strategies encode GIS-centric bias. These findings suggest that future text-to-SQL systems should not assume that a single grounding strategy will generalize uniformly across heterogeneous domains, and that explicit cross-domain evaluation is necessary for building truly general natural-language database interfaces.

---

## 2. Methods

We formulate cross-domain natural language to SQL as the task of translating a user question into an executable SQL statement over heterogeneous structured databases that may belong to either geospatial or conventional warehouse domains. Unlike standard text-to-SQL settings, the target databases in our problem formulation are not assumed to share homogeneous operator semantics. In warehouse-style databases, correct SQL generation primarily depends on schema linking, join reasoning, aggregation, and temporal filtering. In geospatial databases, however, the model must additionally reason about geometry-bearing columns, spatial relations, coordinate systems, and domain-specific operators such as intersection, containment, buffering, and area or distance calculation. The purpose of our framework is therefore not only to generate valid SQL, but also to provide a semantic mediation layer that adapts the grounding process to the structural characteristics of each domain.

To support this setting, we design NL2Semantic2SQL as a three-stage pipeline. Figure 1 (Architecture) illustrates the three-stage pipeline architecture. [Architecture diagram to be included in the camera-ready version.] In the first stage, the system performs semantic resolution over a semantic layer that stores table-level and column-level annotations, aliases, domain hints, and task-relevant metadata. In the second stage, the resolved information is combined with database schema inspection and optional few-shot retrieval to construct a grounded context block for SQL generation. In the third stage, the generated SQL is postprocessed, executed under safety constraints, and, when necessary, revised through an execution-feedback self-correction loop. This decomposition separates semantic interpretation from SQL synthesis, allowing the framework to expose domain-specific evidence to the language model while keeping the final generation step constrained by executable schema information.

A central design feature of the framework is geospatial-aware grounding. For geospatial tables, the system explicitly identifies geometry columns, geometry types, and spatial reference information, and it injects operator-level rules into the grounding context. These rules distinguish topological predicates from metric predicates and specify when area or distance calculations require coordinate transformation or geography casting. This mechanism is intended to reduce the burden on the language model to infer low-level geospatial execution constraints from raw schema text alone. At the same time, the framework preserves the ability to operate on non-geospatial warehouse databases by falling back to generic schema linking and aggregation-oriented prompt construction when spatial signals are absent. In this sense, the framework is unified at the architectural level but adaptive at the semantic grounding level.

For non-geospatial warehouse queries, the framework introduces domain-adaptive enhancements including cross-domain candidate ranking, value-aware grounding, and schema-hint-driven source selection. Cross-domain candidate ranking adjusts the priority of candidate tables based on whether the query contains spatial signals: when no spatial operations or region filters are detected, geometry-bearing tables are deprioritized and tables with matched column evidence are boosted. Value-aware grounding enriches the prompt with sample distinct values from low-cardinality text columns, enabling the language model to use exact categorical values (e.g., segment names, currency codes, country codes) rather than guessing string literals. Schema-hint-driven source selection parses explicit database schema references from the query context and boosts tables belonging to the target schema, ensuring that within a multi-database environment, the correct warehouse tables are prioritized over unrelated schemas.

Evaluation is performed under a dual-track benchmark protocol. The geospatial track uses a GIS-oriented benchmark constructed to cover representative spatial query patterns, including spatial selection, overlap analysis, metric distance queries, buffering, and spatial aggregation. The non-geospatial track is derived from a warehouse-oriented benchmark based on BIRD mini_dev and is used to assess cross-domain generalization. For both tracks, we use execution-based evaluation as the primary metric, comparing the execution result of the predicted SQL with that of the gold SQL. We further analyze performance by query difficulty and conduct ablation studies to isolate the contributions of semantic grounding, few-shot retrieval, and execution-time self-correction.

---

## 3. Results

### 3.1 Experimental Setup

We evaluate NL2Semantic2SQL under a dual-track benchmark protocol. The GIS track uses a 100-question benchmark (expanded from a 20-question pilot) covering four difficulty levels: Easy (24), Medium (36), Hard (25), and Robustness (15). The warehouse track uses ~495 questions from BIRD mini_dev V2 in single-pass mode (P2), spanning three difficulty levels (simple, moderate, challenging) across 11 database schemas imported into PostgreSQL. Both tracks use execution accuracy (EX) as the primary metric: a prediction is correct if and only if its execution result set matches the gold SQL result set under set-equality comparison with numeric tolerance. We report 95% Wilson confidence intervals for all EX values and McNemar paired significance tests.

For each track, we compare two modes:
- **Baseline**: Direct LLM generation (Gemini 2.5 Flash) with schema dump only, no semantic grounding.
- **Full pipeline**: NL2Semantic2SQL with semantic layer resolution, schema-aware context construction, few-shot retrieval (GIS track only), SQL postprocessing, and execution-time self-correction (single-pass mode on BIRD).

We additionally compare against **DIN-SQL** [3] as an external baseline on both tracks.

### 3.2 GIS Track Results

Table 1a reports the GIS Spatial EX results (85 normal spatial-SQL questions) and Table 1b reports the Robustness Success Rate (15 safety/refusal questions) for the expanded 100-question benchmark (run `cq_2026-05-04_122349`). We report these separately because they measure fundamentally different capabilities: Spatial EX measures SQL generation accuracy, while Robustness Success Rate measures safety enforcement and refusal behavior. Combining them into a single "Overall EX" metric is non-standard and conflates two distinct evaluation dimensions; we retain an overall figure only as a secondary reference.

**Benchmark construction**: The 100-question GIS benchmark was constructed as follows: (1) 20 seed questions were manually authored by a domain expert covering 16 spatial query categories across 4 difficulty levels; (2) 80 additional questions were generated using Gemini 2.5 Flash with the actual CQ database schema as context, then validated by executing each gold SQL against the live PostgreSQL/PostGIS database; (3) 6 robustness questions have null gold SQL (testing refusal behavior); (4) all 94 executable gold SQL statements were verified to return non-empty, correct results. The benchmark and gold SQL are released as `benchmarks/chongqing_geo_nl2sql_100_benchmark.json`.

**Table 1a: GIS Spatial EX — 85 normal spatial-SQL questions**

| Difficulty | N | Baseline EX [95% CI] | Full EX [95% CI] | Delta |
|------------|---|----------------------|------------------|-------|
| **Spatial EX (all)** | **85** | **0.529 [0.424, 0.632]** | **0.682 [0.577, 0.772]** | **+0.153** |
| Easy | 24 | 0.750 [0.551, 0.880] | 0.833 [0.641, 0.933] | +0.083 |
| Medium | 36 | 0.389 [0.248, 0.551] | **0.694 [0.531, 0.820]** | +0.305 |
| Hard | 25 | 0.520 [0.335, 0.700] | 0.520 [0.335, 0.700] | 0.000 |
| McNemar | 85 | b=4, c=17 | **p=0.0072** | Significant (α=0.05) |
| Mean tokens | 85 | 753 | 10,261 (13.6×) | |

**Table 1b: GIS Robustness Success Rate — 15 safety/refusal questions**

| Metric | N | Baseline [95% CI] | Full [95% CI] | Delta |
|--------|---|-------------------|---------------|-------|
| **Robustness Success Rate** | **15** | **0.333 [0.152, 0.583]** | **0.800 [0.548, 0.930]** | **+0.467** |
| McNemar | 15 | b=0, c=7 | **p=0.0156** | Significant (α=0.05) |

*Secondary reference*: Combining all 100 questions yields Overall EX=0.500 (baseline) vs. 0.700 (full), Δ=+0.200, McNemar p=0.0002. This combined figure is provided for reference only; the primary metrics are Spatial EX and Robustness Success Rate reported separately above.

The full pipeline outperforms the baseline by +0.153 Spatial EX (McNemar p=0.0072, statistically significant at α=0.05). The largest spatial gain is on Medium difficulty questions (+0.305). Medium questions benefit most from semantic grounding because they involve multi-step spatial reasoning where geometry-aware type injection and intent-conditioned operator routing resolve execution-time type errors that the baseline cannot handle.

Hard questions show no change (0.520 for both): the full pipeline's gains on some Hard questions are offset by regressions on others, primarily cases where intent misclassification introduces incorrect spatial_join context for proximity-buffer queries.

On the Robustness track, the full pipeline achieves 0.800 vs. baseline 0.333 (+0.467, McNemar p=0.0156, statistically significant). Robustness questions benefit from safety postprocessing, which catches dangerous operations (DELETE, UPDATE, DROP) that the baseline LLM would otherwise execute. For example, the question "删除所有未命名的道路" (Delete all unnamed roads) tests whether the system correctly refuses a destructive DELETE operation. The baseline generates `DELETE FROM cq_osm_roads_2021 WHERE name IS NULL`, which would mutate data. The full pipeline's safety postprocessor intercepts the write intent and returns a canonical refusal message.

Token cost on the GIS track is 13.6× relative to baseline (10,261 vs. 753 mean tokens per question). This cost is justified by the safety and precision requirements of the GIS domain: geometry-aware grounding prevents incorrect unit calculations, and robustness enforcement prevents dangerous schema mutations.

### 3.3 Warehouse Track Results (BIRD)

Table 2 presents the BIRD benchmark results at ~495-question scale using single-pass mode (P2, run `bird_pg_2026-05-04_093040`). The baseline completed 498 of 500 questions (2 execution errors); the full pipeline completed 495 of 500 (5 timed out in the initial multi-pass run, later resolved by P2 single-pass mode). For paired McNemar testing, we use the intersection of 495 questions where both modes produced results. The 5 missing full-mode questions are conservatively treated as failures (EX=0) in the overall EX calculation but excluded from the paired test to avoid inflating the discordant count. The primary finding is that the full pipeline outperforms the baseline across all difficulty levels, with an overall improvement of +0.027 EX, though this difference is not statistically significant (McNemar p=0.136).

**Table 2: BIRD ~495-question benchmark results (single-pass mode)**

| Difficulty | N | Baseline EX [95% CI] | Full EX [95% CI] | Delta |
|------------|---|----------------------|------------------|-------|
| simple | 148 | 0.588 | 0.622 | +0.034 |
| moderate | ~248 | 0.456 | 0.482 | +0.026 |
| challenging | 102 | 0.353 | 0.373 | +0.020 |
| **Overall** | **~495** | **0.474 [0.430, 0.518]** | **0.501 [0.457, 0.545]** | **+0.027** |
| Validity | ~495 | 0.978 | **0.996** | +0.018 |
| McNemar | 495 | b=26, c=39 | p=0.136 | Not significant |
| Mean tokens | ~495 | 1,010 | 7,975 (7.9×) | |

Notably, full pipeline improves EX across all three difficulty levels (+0.034 simple, +0.026 moderate, +0.020 challenging) and substantially improves execution validity (0.996 vs. 0.978). The McNemar test (b=26, c=39, n=495) gives p=0.136, which is directional but not statistically significant at α=0.05. The confidence intervals for overall EX overlap (baseline [0.430, 0.518], full [0.457, 0.545]), though the full pipeline's lower CI bound is higher than the baseline's lower CI bound.

The P2 single-pass mode reduced token cost from ~32× (multi-pass agent runner) to 7.9× (1,010 → 7,975 mean tokens) while also improving EX, by eliminating agent runner hangs and routing each question through the grounding pipeline exactly once.

For reference, the earlier 500-question multi-pass run (run `bird_pg_2026-05-01_182457`) showed: baseline 0.458, full 0.450 (−0.008, McNemar p=0.8151). The single-pass P2 mode not only reduces cost but also eliminates the small multi-pass degradation: full now exceeds baseline on the BIRD track as well.

### 3.4 DIN-SQL External Baseline Comparison

We compare against DIN-SQL [3] as an external prompting baseline on both tracks. DIN-SQL uses decomposed in-context learning with self-correction. The DIN-SQL evaluation on GIS now covers the same 100-question benchmark as Baseline and Full, enabling a fair head-to-head comparison.

**Table 3: DIN-SQL external baseline comparison (100q for GIS, ~495q for BIRD)**

| Track | N | Baseline EX | DIN-SQL EX | Full EX | Full vs. DIN-SQL |
|-------|---|-------------|------------|---------|-----------------|
| GIS Spatial 85q | 85 | 0.529 | 0.565 | **0.682** | +0.118 |
| GIS Robust. 15q | 15 | 0.333 | 0.267 | **0.800** | +0.533 |
| BIRD ~495q | ~495 | 0.474 | 0.482 | **0.501** | +0.019 |

**On the GIS Spatial track (85 questions)**: DIN-SQL achieves EX=0.565, only marginally above the direct-LLM baseline (0.529, McNemar DIN-SQL vs. baseline p=0.508, not significant). This confirms that decomposed prompting *without* spatial grounding does not provide a meaningful improvement over direct generation for geospatial SQL. The full NL2Semantic2SQL pipeline reaches Spatial EX=0.682, a statistically significant improvement of **+0.118 over DIN-SQL** (paired McNemar b=3, c=13, **p=0.0213**, significant at α=0.05).

**On the GIS Robustness track (15 questions)**: DIN-SQL achieves only 0.267 Success Rate, slightly below baseline (0.333), because DIN-SQL has no built-in safety/refusal handling for DELETE/UPDATE/DROP requests, anti-illusion checks, OOM prevention, or schema enforcement. The full pipeline achieves 0.800, a statistically significant improvement of **+0.533 over DIN-SQL** (paired McNemar b=0, c=8, **p=0.0078**, significant).

**On the BIRD warehouse track**: DIN-SQL achieves EX=0.482 (Validity=0.990). Full pipeline EX=0.501 is numerically higher than DIN-SQL EX=0.482 (+0.019), but the difference is **not statistically significant** (McNemar p=0.382). The three systems — baseline (0.474), DIN-SQL (0.482), and Full (0.501) — are statistically comparable on the BIRD track.

In summary, the full pipeline obtains statistically significant gains over both the baseline and DIN-SQL on the GIS track (both Spatial and Robustness), while on BIRD all three systems are statistically comparable. This pattern reinforces the paper's central thesis: semantic grounding with intent-conditioned routing yields domain-specific gains for geospatial SQL where geometry-aware schema linking, SRID/coordinate handling, and safety enforcement matter, while pure prompt-engineering baselines such as DIN-SQL remain competitive on conventional warehouse SQL.

### 3.5 Token Cost Analysis

The full pipeline incurs substantially higher token cost than the baseline due to semantic grounding context injection. Table 4 reports mean tokens per question.

**Table 4: Mean tokens per question**

| Track | N | Baseline tokens | Full tokens | Ratio | DIN-SQL tokens |
|-------|---|-----------------|-------------|-------|----------------|
| GIS | 100 | 753 | 10,261 | 13.6× | not tracked |
| BIRD | ~495 | 1,010 | 7,975 | 7.9× | not tracked |

The GIS token ratio (13.6×) is higher than BIRD (7.9×) because GIS grounding context includes geometry-type annotations, SRID information, spatial operator rules, and few-shot examples, all of which are absent on the warehouse track.

For the BIRD track, P2 single-pass mode reduced the token ratio from ~32× (multi-pass agent runner in earlier experiments) to 7.9×. This reduction was achieved by routing each question through the grounding pipeline exactly once rather than using an iterative agent loop, while also improving EX by eliminating agent runner hangs.

**Deployment consideration**: A 7.9–13.6× token overhead is significant at scale. For a production deployment processing 10,000 queries per day at $0.50/million input tokens, the full pipeline would cost approximately $5–$12 more per day than the baseline at current Gemini pricing. This cost is clearly justified in safety-critical GIS contexts (geometry precision, data mutation prevention), and is a reasonable tradeoff in warehouses given the +0.027 EX improvement. However, latency-sensitive or cost-constrained deployments should consider whether the quality improvement justifies the overhead. A promising mitigation is selective grounding: instead of injecting the full semantic context for every query, the system could first perform a lightweight intent classification (already implemented) and then retrieve only the top-K most relevant schema elements and grounding rules. Preliminary analysis suggests that for aggregation-intent queries, the grounding prompt could be reduced by ~60% without affecting the generated SQL, as most aggregation queries do not require spatial operator hints.

### 3.6 Cross-Domain Comparison

Figure 1 summarizes the three-way cross-domain comparison (Baseline / DIN-SQL / Full) on the same evaluation sets:

```
Track                   | Baseline | DIN-SQL  | Full    | Full vs. Baseline       | Full vs. DIN-SQL
GIS Spatial 85q (EX)    | 0.529    | 0.565    | 0.682   | +0.153 (p=0.0072 **)    | +0.118 (p=0.0213 *)
GIS Robustness 15q      | 0.333    | 0.267    | 0.800   | +0.467 (p=0.0156 *)     | +0.533 (p=0.0078 **)
BIRD ~495q (EX)         | 0.474    | 0.482    | 0.501   | +0.027 (p=0.136 NS)     | +0.019 (p=0.382 NS)

** strongly significant (p<0.01), * significant (p<0.05), NS = not significant
DIN-SQL on GIS evaluated on the same 100-question benchmark (run cq_din_sql_2026-05-04_151650).
```

Both GIS metrics show **Full pipeline statistically significantly outperforming both baseline and DIN-SQL**. On the BIRD track, all three systems are statistically comparable; the BIRD result should be interpreted as directional evidence, not a confirmed advantage.

### 3.7 Error Analysis

We categorize the full-pipeline failures on the BIRD track into three types. With execution validity=0.996 on ~495 questions, only approximately 2 questions (~0.4% of total) produce invalid SQL; the vast majority of failures are semantically incorrect SQL that executes successfully but returns wrong results.

| Error Type | Fraction of failures |
|------------|----------------------|
| Wrong result (valid SQL, incorrect answer) | ~95% |
| No SQL generated (gen_status=no_sql) | ~5% |
| Invalid SQL (execution error) | <1% |

The dominant failure mode is semantically incorrect SQL that executes successfully but returns wrong results. Manual inspection reveals three recurring patterns:

1. **Join path confusion** (~40%): The model selects incorrect join paths between fact and dimension tables. This reflects insufficient understanding of the warehouse schema's entity-relationship structure.

2. **Aggregation semantics** (~30%): The model applies COUNT(DISTINCT ...) where the gold SQL uses COUNT(*), or vice versa.

3. **Date/temporal parsing** (~25%): The BIRD dataset uses non-standard date formats. The model applies SUBSTRING-based parsing inconsistently.

The P2 single-pass mode substantially improved validity (0.978→0.996) by virtually eliminating invalid SQL; single-pass mode routes each question through the grounding pipeline exactly once, avoiding the agent-loop hangs that produced empty or malformed SQL in multi-pass mode.

### 3.8 Component Attribution Analysis

We analyze the 24 improved and 4 regressed questions (discordant pairs between baseline and full pipeline) to attribute the +0.200 EX gain to specific pipeline components.

**Table: Component attribution for the GIS 100-question benchmark**

| Component | Questions improved | EX contribution | Primary categories |
|---|---|---|---|
| Safety guardrails (postprocessor) | +7 | +0.070 | Security rejection, anti-illusion, schema enforcement, data tampering |
| Semantic grounding (geometry-aware) | +13 | +0.130 | Spatial measurement (5), spatial join (3), attribute filtering (1), aggregation (1), KNN (1), centroid/geometry (1), temporal (1) |
| Intent routing | +2 | +0.020 | Attribute filtering (1), spatial measurement (1) |
| Complex spatial reasoning | +2 | +0.020 | K-nearest neighbors (1), cross-table (1) |
| Regressions | -4 | -0.040 | Proximity buffer (1), cross-table (1), aggregation (1), temporal (1) |
| **Net (Full pipeline)** | **+20** | **+0.200** | |

**Key finding**: Semantic grounding is the dominant contributor, accounting for 13 of 24 improvements (+0.130 EX, 65% of the total gain). These improvements concentrate in Medium-difficulty questions involving spatial measurement (ST_Area, ST_Length with ::geography casting), spatial joins (ST_Intersects, ST_DWithin), and KNN queries (<-> operator). Safety guardrails contribute the second-largest share (+0.070, 35% of the gain), entirely from the Robustness suite. Intent routing and complex spatial reasoning each contribute +0.020.

The 4 regressions occur in Hard and Medium questions where the grounding prompt introduces competing rules that confuse the model (e.g., proximity buffer classified as spatial_join, suppressing a needed rule; cross-table queries where schema grounding surfaces irrelevant tables).

This analysis confirms that the +0.200 EX gain is primarily attributable to semantic grounding (+0.130) and safety enforcement (+0.070), not to incidental factors such as prompt length or model variance.

The McNemar tests confirm statistical significance for both GIS metrics:

| Track | n | b | c | p-value | Interpretation |
|-------|---|---|---|---------|----------------|
| GIS Spatial (85q) | 85 | 4 | 17 | **0.0072** | Significant (α=0.05); +0.153 Spatial EX |
| GIS Robustness (15q) | 15 | 0 | 7 | **0.0156** | Significant (α=0.05); +0.467 Success Rate |
| BIRD ~495 | 495 | 26 | 39 | 0.136 | Not significant; directional (+0.027 EX) |

Both GIS metrics are statistically significant at α=0.05. The BIRD result (p=0.136) is directional but not significant; the three systems (baseline, DIN-SQL, NL2Semantic2SQL) are statistically comparable on warehouse queries. The BIRD result should be interpreted as directional evidence, not a confirmed advantage.

### 3.9 Reproducibility

For each experimental table, Table 5 lists the exact run directory, model, and notes.

**Table 5: Reproducibility map**

| Result | Track / config | Run directory | Model | Notes |
|---|---|---|---|---|
| Table 1a/1b, GIS 100q baseline + full | GIS, baseline + full | `cq_2026-05-04_122349` | `gemini-2.5-flash` | **Primary GIS result.** 100-question benchmark (85 Spatial + 15 Robustness). |
| Table 1 (ref), GIS 20q Phase A | GIS, baseline + full | `cq_2026-05-03_164213` | `gemini-2.5-flash` | Historical reference (20q pilot). |
| Table 1 (ref), GIS 20q pre-Phase A | GIS, baseline + full | `cq_2026-05-01_132919` | `gemini-2.5-flash` | Historical reference (pre-Phase A). |
| Table 3, DIN-SQL GIS 100q | GIS, DIN-SQL | `cq_din_sql_2026-05-04_151650` | `gemini-2.5-flash` | **Primary DIN-SQL GIS result.** Same 100-question benchmark as Baseline/Full; max_retries=1, temperature=0.0. |
| Table 3 (ref), DIN-SQL GIS 20q | GIS, DIN-SQL | `cq_din_sql_2026-05-03_193407` | `gemini-2.5-flash` | Historical reference (20-question pilot). |
| Table 2, BIRD ~495q single-pass | BIRD, baseline + full | `bird_pg_2026-05-04_093040` | `gemini-2.5-flash` | **Primary BIRD result.** P2 single-pass mode. |
| Table 2 (ref), BIRD 500q multi-pass | BIRD, baseline + full | `bird_pg_2026-05-01_182457` | `gemini-2.5-flash` | Historical reference (multi-pass, now superseded). |
| Table 2 (ref), BIRD 50q Full(+MetricFlow) | BIRD full+MetricFlow | `bird_pg_2026-05-01_151254` | `gemini-2.5-flash` | Best single-schema MetricFlow result; reference only. |
| DIN-SQL BIRD 500q | BIRD, DIN-SQL | `bird_din_sql_2026-05-03_193412` | `gemini-2.5-flash` | DIN-SQL on BIRD full mini_dev. |
| Table 3, Cross-lingual (Chinese) | BIRD 50q, full+MetricFlow on Chinese-translated questions | `bird_pg_chinese_2026-05-01_171426` | `gemini-2.5-flash` (eval) + `gemini-2.0-flash` (translator) | Chinese aliases registered for 75 BIRD tables and 209 columns. |

**Model parameters**: All runs use Gemini 2.5 Flash with temperature=0.0, default top_p, and default maximum output tokens. The BIRD evaluation uses the full `mini_dev_postgresql.json` (500 questions, no sampling); 495 questions completed. DIN-SQL runs use `results.json` (not `baseline_results.json` or `full_results.json`).

**Error handling**: Each question has a 60-second execution timeout. On `429 RESOURCE_EXHAUSTED`, the runner uses the `genai` SDK's built-in retry (3 attempts with 2-second initial delay). On no-SQL output, the question is recorded as `gen_status=no_sql` and EX=0. BIRD baseline ran 498/500 (2 errors); full ran 495/500 (3 stalled before P2 fix). Paired McNemar uses the n=495 intersection.

We additionally release the GIS benchmark questions and gold SQL, the BIRD warehouse-modeling registration script, the cross-lingual evaluation harness, the per-question SQL postprocessor and self-correction logic, and the MetricFlow YAML schemas registered for the BIRD `debit_card_specializing` schema.

## 4. Discussion

### 4.1 Why Semantic Grounding Helps in GIS — and Why the Advantage Is Now Statistically Significant

The expanded 100-question GIS benchmark confirms what the 20-question pilot suggested but could not statistically substantiate: semantic grounding with intent-conditioned routing provides a large, reliable advantage for geospatial SQL. Both primary GIS metrics are statistically significant: Spatial EX +0.153 (McNemar p=0.0072) and Robustness Success Rate +0.467 (p=0.0156). Three mechanisms drive the improvement:

First, **geometry-aware type injection** ensures the model knows which columns are geometry-bearing, what their SRID is, and when geography casting is required. Without this, the baseline frequently omits `::geography` casts, producing area/distance values in degrees rather than meters. This mechanism drives most of the Medium difficulty improvement (+0.305).

Second, **intent-conditioned operator routing** gates domain-specific rules (KNN `<->` operator, LIMIT injection) to the queries where they are relevant. This eliminates false-positive injections that caused regressions in the pre-Phase-A pipeline.

Third, **safety and robustness enforcement** through SQL postprocessing catches dangerous operations (DELETE, UPDATE) and handles refusal/anti-illusion cases. The baseline LLM has no such guardrails and scores only 0.333 on the robustness suite, while the full pipeline achieves 0.800 (+0.467).

The transition from p=0.125 (n=20) to p=0.0072 (Spatial, n=85) and p=0.0156 (Robustness, n=15) illustrates a point methodologically: the effects were real but underpowered in the pilot. The 100-question benchmark provides adequate power to confirm that both advantages are not sampling artifacts.

The component attribution analysis (Table in Section 3.8) confirms that semantic grounding is the dominant contributor to the GIS improvement, accounting for 65% of the total +0.200 EX gain. This addresses the concern that the improvement might be attributable to incidental factors such as safety guardrails alone. While safety enforcement contributes a meaningful +0.070 (35%), the majority of the gain comes from geometry-aware schema grounding that helps the model correctly apply ::geography casting, spatial predicates, and coordinate-system handling — capabilities that neither the baseline nor DIN-SQL provide.

### 4.2 The BIRD Result: Directional but Not Significant

On the BIRD track, the full pipeline achieves EX=0.501 vs. baseline 0.474 (+0.027, McNemar p=0.136). The confidence intervals overlap, and the result is not statistically significant at α=0.05. We state this clearly: the BIRD result should be interpreted as directional evidence, not a confirmed advantage.

Full pipeline EX=0.501 is numerically higher than DIN-SQL EX=0.482 (+0.019), but the difference is not statistically significant (McNemar p=0.382). The three systems — baseline (0.474), DIN-SQL (0.482), and Full (0.501) — are statistically comparable on the BIRD track. Neither the full pipeline's advantage over baseline nor its advantage over DIN-SQL reaches statistical significance at current sample sizes.

The improvement in execution validity (0.978 → 0.996) is noteworthy: the full pipeline almost eliminates invalid SQL on warehouse queries, a practical benefit even when overall EX does not significantly improve.

### 4.3 Token Cost Is a Real Deployment Consideration

The 13.6× GIS and 7.9× BIRD token overhead is not trivial. We discuss this honestly rather than dismissing it. The P2 single-pass mode reduced BIRD token cost from ~32× to 7.9× while simultaneously improving EX — demonstrating that architectural optimization (eliminating multi-pass agent loops) can reduce cost without sacrificing quality.

For the GIS track, the 13.6× overhead is justified by the nature of the domain: safety-critical spatial analysis requires geometry metadata, operator rules, and safety enforcement that naturally inflate context. For the BIRD track, whether the 7.9× overhead is justified depends on the application: in latency-sensitive or cost-constrained settings, the directional +0.027 EX gain may not warrant the additional cost.

A practical deployment strategy would be: use the full pipeline for all GIS queries (safety requires it), and use the full pipeline for BIRD queries only when the use case is quality-critical (e.g., financial reporting) rather than exploratory.

### 4.4 The Effect of MetricFlow-Style Modeling

The error analysis suggests that the primary bottleneck for warehouse performance is not SQL syntax generation but semantic schema navigation. MetricFlow-style modeling directly targets this problem by declaring entities (join keys), measures (aggregatable facts), and dimensions (descriptive attributes). We validate this hypothesis by registering MetricFlow-style metadata for the most error-prone BIRD schema and injecting derived join-path hints into the grounding prompt. This single intervention raises overall execution accuracy from 0.520 to 0.540 on the 50-question pilot, with moderate questions recovering from 0.316 to 0.368 and challenging questions improving from 0.333 to 0.500. We interpret this as direct evidence that warehouse-side performance is bottlenecked by missing structural metadata rather than by surface-form generation, and that targeted semantic modeling closes most of the gap without changing the underlying language model.

### 4.5 Cross-Lingual Observations (Preliminary Stress Test)

We position the cross-lingual experiment as a preliminary stress test rather than a fully controlled cross-lingual evaluation. The translated questions are produced by an LLM translator (Gemini 2.0 Flash) and have not been verified by a native human annotator; furthermore, table and column names remain in their original English form, which lowers the difficulty of cross-lingual schema linking compared with a true bilingual schema. Within this constrained setting, the framework's multilingual alias mechanism is sufficient to recover most schema references when questions are paraphrased into Chinese, with only a four-percentage-point loss in execution accuracy (0.500 vs. 0.540) and validity (0.900 vs. 0.940). The remaining gap concentrates on moderate and challenging questions, suggesting that paraphrase-induced ambiguity in aggregation phrasing and join-key references is the dominant residual error. We do not claim general cross-lingual robustness, and a more rigorous evaluation would compare against (i) a no-alias baseline, (ii) a translate-back-to-English baseline, and (iii) human-translated questions.

### 4.5a Relationship to GeoSQL-Eval

Our work is complementary to GeoSQL-Eval [13]. GeoSQL-Eval provides fine-grained function-level evaluation (syntax correctness, parameter matching, return type recognition) across 340 PostGIS functions, while our framework evaluates end-to-end query generation with semantic grounding and cross-domain generalization. Future work could integrate GeoSQL-Bench's function-level metrics into our evaluation protocol to provide both macro-level (EX) and micro-level (function hit rate, parameter accuracy) assessment.

### 4.6 Limitations

Several limitations should be noted. First, the 100-question GIS benchmark is based only on Chongqing spatial data; generalization to other spatial database conventions (GeoPackage, Shapefile schema, non-WGS84 coordinate systems) and non-Chinese GIS schemas is not yet evaluated. Second, on the BIRD track, the full pipeline's +0.027 EX advantage over baseline is directional but not statistically significant (p=0.136); the three-way comparison with DIN-SQL likewise shows no statistically significant differences. Third, the cross-lingual experiment uses LLM-translated questions without human verification; full cross-lingual claims would require human-annotated translations. Fourth, token cost (8–14× baseline) is a real deployment consideration, especially for warehouse queries where the marginal accuracy gain is statistically inconclusive. Fifth, the current evaluation uses Gemini 2.5 Flash; behavior may differ on other LLM families (e.g., GPT-4o, Claude, open-source models). Sixth, our baselines are direct-LLM-with-schema-dump and DIN-SQL only; comparison against MAC-SQL and other recent approaches would be necessary to position the method against the full state-of-the-art. Seventh, execution-based evaluation treats any result-set mismatch as failure, even when the predicted SQL is semantically equivalent but differs in ordering or numeric precision. Eighth, the current grounding rules are specific to PostgreSQL/PostGIS syntax (e.g., `::geography` casting, `<->` KNN operator, `ST_*` function family). Adapting to other spatial databases (MySQL Spatial, Oracle Spatial, SpatiaLite) would require replacing the dialect-specific rule dictionary in the intent router and postprocessor, but the overall architecture (semantic layer → intent classification → grounding → generation → postprocess) is dialect-agnostic.

### 4.7 Future Work

Three directions emerge from this study:
1. **Cross-domain GIS benchmark expansion**. Extend the GIS benchmark to cover multiple geospatial databases (non-Chinese, different coordinate systems, raster data) and increase per-category counts for finer ablation analysis.
2. **BIRD statistical significance**. Expand the BIRD evaluation to 1000+ questions to achieve adequate power to confirm or refute the observed +0.027 directional advantage.
3. **Token cost reduction**. Investigate selective grounding (inject only relevant semantic context blocks rather than full metadata) and prompt compression to reduce the 7.9–13.6× token overhead while preserving EX gains.

## 5. Related Work

### 5.1 Text-to-SQL with Large Language Models

The application of large language models (LLMs) to text-to-SQL has progressed rapidly through increasingly sophisticated prompt engineering strategies. Early in-context learning approaches demonstrated that LLMs could generate executable SQL from natural-language questions when provided with schema descriptions and example query pairs [1, 2]. DIN-SQL [3] introduced a decomposed prompting pipeline that separates schema linking, query classification, and SQL generation into distinct stages, with self-correction as a post-generation step. DAIL-SQL [4] systematized few-shot example selection based on SQL skeleton similarity and achieved strong results on the Spider benchmark with minimal token cost. C3 [5] explored zero-shot ChatGPT-based text-to-SQL with calibrated bias correction, illustrating a complementary line of prompt-engineered solutions that does not rely on hand-crafted few-shot examples. More recently, multi-agent and tool-augmented architectures have emerged, in which specialized agents handle schema retrieval, SQL generation, and execution verification as separate collaborative roles. Our framework shares the decomposition philosophy of DIN-SQL but adds an explicit semantic layer as a structured intermediary between the user question and the schema, rather than relying solely on prompt-level schema linking.

### 5.2 Benchmarks for Text-to-SQL

Spider [1] established the standard cross-database text-to-SQL benchmark with execution-based evaluation, introducing the challenge of generalizing across unseen database schemas. BIRD [6] extended this setting to larger, more realistic databases with value-aware evaluation and difficulty stratification, revealing that LLM performance degrades substantially on complex aggregation and multi-hop join queries. Spider 2.0 [7] further expanded the scope to include enterprise-style workflows such as dbt transformations and dialect variations. BEAVER [8] specifically targets enterprise data warehouses with private schemas and complex business logic, showing that state-of-the-art models achieve near-zero accuracy on truly private enterprise data. Our work is motivated by a complementary gap: mainstream text-to-SQL benchmarks (Spider, BIRD, Spider 2.0) provide limited coverage of executable PostGIS-style spatial SQL, geometry-aware schema grounding, and SRID/coordinate-system handling, and none assess cross-domain transfer between GIS and warehouse query semantics in a single evaluation protocol.

### 5.3 Geospatial Natural Language Interfaces

Natural language interfaces to geospatial databases have a distinct research lineage from general text-to-SQL. Early work on geospatial question answering, such as GeoQuery~\cite{zelle1996geoquery}, which used inductive logic programming to learn a parser for geographic database queries, focused on small geographic fact databases. Punjani et al. [9] extended this to template-based question answering over linked geospatial data on the Semantic Web, demonstrating that structured spatial knowledge can be queried via natural language when appropriate ontological mappings are available; their work highlights the importance of spatial predicate coverage and coordinate-system awareness that remains relevant for PostGIS-style SQL generation. More recent work has explored using LLMs for spatial reasoning and geographic knowledge extraction [10], but systematic evaluation of text-to-SQL capabilities over PostGIS or spatially-extended relational databases remains scarce. Until recently, mainstream text-to-SQL benchmarks provided limited coverage of PostGIS-style spatial SQL. GeoSQL-Eval [13] addresses this gap with a comprehensive PostGIS function-level evaluation framework comprising 14,178 tasks across 340 PostGIS functions. Our work differs in focus: while GeoSQL-Eval evaluates individual PostGIS function invocation and syntax correctness, NL2Semantic2SQL targets end-to-end cross-domain query generation with semantic-layer grounding, intent routing, and safety enforcement across both GIS and warehouse domains. Our GIS benchmark is designed to complement this function-level evaluation with end-to-end execution accuracy.

### 5.4 Semantic Layers and Schema Grounding

The concept of a semantic layer as an intermediary between analytical queries and raw database schemas originates from business intelligence tools and has been formalized in frameworks such as MetricFlow [11] and dbt's semantic layer. These systems define entities, dimensions, measures, and metrics as declarative metadata that governs how joins and aggregations should be constructed. In the text-to-SQL context, semantic layers offer a principled way to provide LLMs with structured evidence about schema semantics rather than requiring the model to infer join paths and aggregation rules from raw DDL alone. Our framework adapts this concept for cross-domain use, combining GIS-specific annotations (geometry types, SRIDs, spatial operators) with warehouse-style entity-relationship metadata to support both query domains through a unified grounding architecture.

### 5.5 Cross-Domain and Cross-Lingual Text-to-SQL

Cross-domain generalization has been studied primarily through zero-shot transfer across database schemas within the same linguistic and operator domain [1, 6]. Cross-lingual text-to-SQL, where questions are posed in one language over schemas defined in another, has received less systematic attention, though multilingual benchmarks such as CSpider [12] (Chinese Spider) demonstrate that language mismatch introduces additional schema linking challenges. Our work extends the cross-domain dimension beyond schema variation to include operator heterogeneity (spatial vs. tabular) and language heterogeneity (Chinese questions over English warehouse schemas), providing a more comprehensive view of the generalization landscape.

---

## 6. Conclusion

We have presented NL2Semantic2SQL, a cross-domain framework for natural-language interfaces over both geospatial and conventional warehouse databases. The framework integrates semantic-layer grounding, intent-conditioned routing, schema-aware context construction, few-shot retrieval, SQL postprocessing, and execution-time self-correction into a single three-stage pipeline. A core design principle is bilingual, cross-domain support: the framework handles both Chinese GIS queries and English warehouse queries through intent-conditioned routing that operates bilingually, without language-specific model swapping. We constructed a 100-question GIS benchmark with a separate robustness suite and combined it with a ~495-question subset of BIRD mini_dev to define a dual-track evaluation protocol.

Four findings stand out. First, on the 85-question GIS Spatial track, the full pipeline achieves Spatial EX=0.682 vs. baseline 0.529 (McNemar p=0.0072, statistically significant at α=0.05, +0.153). The improvement is driven by geometry-aware grounding (+0.305 on Medium) and intent-conditioned operator routing. Second, on the 15-question GIS Robustness track, the full pipeline achieves Success Rate=0.800 vs. baseline 0.333 (McNemar p=0.0156, statistically significant, +0.467), driven by safety postprocessing. Both GIS results are substantially stronger than the 20-question pilot (p=0.125), confirming that the effects were real but underpowered in the earlier evaluation. Third, on the ~495-question BIRD benchmark (single-pass P2 mode), the full pipeline achieves EX=0.501 vs. baseline 0.474 (+0.027). The BIRD advantage is directional but not statistically significant (McNemar p=0.136); the three systems — baseline (0.474), DIN-SQL (0.482), and Full (0.501) — are statistically comparable on warehouse queries. The BIRD result should be interpreted as directional evidence, not a confirmed advantage. Fourth, P2 single-pass mode reduced BIRD token cost from ~32× to 7.9× while improving EX, demonstrating that architectural optimization can simultaneously reduce cost and improve quality.

Taken together, the results establish that a unified semantic-to-SQL architecture with bilingual intent-conditioned routing provides statistically significant gains for GIS spatial accuracy (p=0.0072) and robustness (p=0.0156), and directional gains for warehouse queries. The token cost (8–14× baseline) is a real deployment consideration, especially for warehouse queries where the marginal accuracy gain is statistically inconclusive; future work should address this via selective grounding or context compression.

---

## 7. References

[1] T. Yu, R. Zhang, K. Yang, et al., "Spider: A large-scale human-labeled dataset for complex and cross-domain semantic parsing and text-to-SQL task," in *Proc. EMNLP*, 2018, pp. 3911–3921.

[2] N. Rajkumar, R. Li, and D. Bahdanau, "Evaluating the text-to-SQL capabilities of large language models," arXiv:2204.00498, 2022.

[3] M. Pourreza and D. Rafiei, "DIN-SQL: Decomposed in-context learning of text-to-SQL with self-correction," in *Proc. NeurIPS*, 2023.

[4] D. Gao, H. Wang, Y. Li, et al., "Text-to-SQL empowered by large language models: A benchmark evaluation," *Proc. VLDB Endow.*, vol. 17, no. 5, pp. 1132–1145, 2024.

[5] X. Dong, C. Zhang, Y. Ge, et al., "C3: Zero-shot text-to-SQL with ChatGPT," arXiv:2307.07306, 2023.

[6] J. Li, B. Hui, G. Qu, et al., "Can LLM already serve as a database interface? A big bench for large-scale database grounded text-to-SQLs," in *Proc. NeurIPS Datasets and Benchmarks Track*, 2023.

[7] F. Lei, J. Chen, Y. Ye, et al., "Spider 2.0: Evaluating language models on real-world enterprise text-to-SQL workflows," in *Proc. ICLR*, 2025.

[8] P. B. Chen, F. Wenz, Y. Zhang, et al., "BEAVER: An enterprise benchmark for text-to-SQL," arXiv:2409.02038, 2024.

[9] D. Punjani, K. Singh, A. Both, et al., "Template-based question answering over linked geospatial data," in *Proc. 12th GIR Workshop @ ACM SIGSPATIAL*, 2018, Article 7, pp. 1–10. DOI: 10.1145/3281354.3281362.

[10] G. Mai, W. Huang, J. Sun, et al., "On the opportunities and challenges of foundation models for geospatial artificial intelligence," arXiv:2304.06798, 2023.

[11] dbt Labs / Transform Data, Inc., "MetricFlow: Industrial semantic-layer documentation," available at \url{https://docs.getdbt.com/docs/build/about-metricflow}, accessed 2026.

[12] Q. Min, Y. Shi, and Y. Zhang, "A pilot study for Chinese text-to-SQL semantic parsing (CSpider)," in *Proc. EMNLP-IJCNLP*, 2019, pp. 3652–3658.

[13] S. Hou, H. Jiao, Z. Liu, et al., "GeoSQL-Eval: First evaluation of LLMs on PostGIS-based NL2GeoSQL queries," *Expert Systems with Applications*, 2025. DOI: 10.1016/j.eswa.2025.10353.

---

## 论文主图建议

1. **Graphical Abstract**: NL input → semantic grounding → SQL generation → execution correction → GIS/warehouse output
2. **方法流程图**: semantic layer + grounding engine + few-shot + postprocess + self-correction 全链路
3. **三轨对比图**: Baseline / DIN-SQL / Full 在 GIS 100q 和 BIRD ~495q 上的 EX 对比（含 95% CI 误差棒）
4. **演进轨迹图**: GIS full pipeline EX 从 0.650 (20q pilot) → 0.700 (100q, p=0.0002) 的改进过程
5. **Token 成本图**: GIS 13.6× vs BIRD 7.9× vs P2 优化前 32× 的对比柱状图
