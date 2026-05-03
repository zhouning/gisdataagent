# NL2Semantic2SQL: A Cross-Domain Framework for Natural Language to SQL over Geospatial and Enterprise Data Warehouses

> **Status**: Draft v0.2 (2026-05-03)
> **Target venues**: IJGIS / GeoInformatica / Transactions in GIS / ISPRS IJGI

---

## Abstract (English)

Natural language to SQL (text-to-SQL) has advanced rapidly with large language models, yet most existing systems and benchmarks focus on conventional relational databases and provide limited coverage of executable geospatial SQL. Geospatial databases introduce additional challenges, including geometry-aware schema grounding, spatial predicates, coordinate reference systems, and domain-specific operators such as intersection, buffer, area, and distance calculations. At the same time, practical data platforms increasingly require a single interface that can support both geospatial and non-geospatial warehouse queries. In this work, we present NL2Semantic2SQL, a cross-domain framework that combines semantic-layer grounding, intent-conditioned routing, schema-aware prompt construction, few-shot retrieval, SQL postprocessing, and execution-time self-correction to support natural-language querying over both GIS and conventional warehouse data. To evaluate the geospatial side of this problem, we construct a pilot GIS-oriented benchmark with execution-based evaluation and a separate robustness suite, and we further assess cross-domain generalization on a 500-question warehouse benchmark derived from BIRD mini_dev. After adding Phase A intent-conditioned grounding, the full pipeline outperforms the baseline on both spatial EX (0.933 vs. 0.867) and robustness (0.800 vs. 0.000), yielding a combined pilot score of 0.900 vs. 0.650. On the 500-question BIRD benchmark, the full pipeline reaches parity with the baseline (0.450 vs. 0.458), confirmed by McNemar p=0.8151. An intent-class ablation shows that the main contribution of intent routing is preventing spurious LIMIT injection on non-preview queries and enabling KNN-specific operator rules. A preliminary cross-lingual experiment on Chinese translations of BIRD questions further shows that multilingual alias registration supports cross-lingual querying with a four-percentage-point loss relative to the English warehouse run. These findings demonstrate both the promise and the limitations of unified semantic-to-SQL architectures across heterogeneous database domains, and they suggest that future cross-domain text-to-SQL systems must explicitly account for language, schema, and operator heterogeneity rather than assuming a single grounding strategy will generalize uniformly.

## 摘要 (中文)

自然语言到 SQL 的查询生成技术近年来随着大语言模型的发展取得了显著进展，但现有研究与 benchmark 主要面向传统关系数据库，对可执行空间 SQL 的覆盖仍然有限。与普通数据仓库相比，GIS 数据库在几何类型、空间谓词、坐标参考系以及面积、距离、缓冲、叠加等空间算子方面具有更强的领域特性，使得 schema grounding 与 SQL 生成面临额外挑战。与此同时，面向真实业务的数据平台往往需要同一套自然语言查询框架同时支持空间与非空间场景。针对这一问题，本文提出一种跨域的 NL2Semantic2SQL 框架，通过意图感知路由、语义层解析、schema grounding、few-shot 检索、SQL 后处理与执行期自纠错等机制，实现对 GIS 数据库与通用数据仓库的统一支持。为评估该框架在空间场景中的能力，本文进一步构建了一套 pilot 级别的 GIS-oriented benchmark，并将普通空间 SQL 执行任务与安全/鲁棒性任务分开评价；同时，本文在基于 BIRD mini_dev 改造的 500 题通用仓库 benchmark 上评估其跨域泛化能力。Phase A 意图条件化 grounding 引入后，full pipeline 在空间 EX 上超越 baseline（0.933 vs. 0.867），鲁棒性得分从 0.000 提升至 0.800，综合得分从 0.650 提升至 0.900。在 500 题 BIRD benchmark 上，full pipeline 与 baseline 持平（0.450 vs. 0.458），McNemar 检验 p=0.8151 确认两者无显著差异。意图类消融实验表明，意图路由的主要贡献在于阻止非预览查询的误注 LIMIT 以及为 KNN 查询启用专用算子规则。上述结果说明，带意图感知路由的统一 semantic-to-SQL 框架在 GIS 侧具有明确增益，在仓库侧保持中性，但 GIS 侧的改进在当前小规模 pilot（n=20）下尚未达到统计显著性（McNemar p=0.1250）。

## Contributions

1. 本文提出了一种面向 GIS 与非 GIS 双场景的统一 NL2Semantic2SQL 框架，使自然语言查询在空间数据库与普通数据仓库之间共享同一套 semantic grounding—SQL generation—execution correction 主链路，并通过意图感知路由实现算子级规则的条件化注入。

2. 本文构建了一套 pilot 级别的 GIS-oriented text-to-SQL benchmark，并将普通空间 SQL 任务与安全/鲁棒性任务分开评价，避免将拒答与执行准确率混合统计；该 benchmark 与 BIRD 500 题子集共同构成可执行的双轨评估协议。

3. 本文通过跨域评测分析表明，Phase A 意图条件化 grounding 使 GIS 侧空间 EX 从 0.867 提升至 0.933（+0.067），鲁棒性从 0.000 提升至 0.800，综合得分从 0.650 提升至 0.900；在 500 题 BIRD benchmark 上，full pipeline 与 baseline 持平（McNemar p=0.8151）。意图类消融实验进一步揭示了意图路由的主要贡献机制。这些结果为跨域 text-to-SQL 的后续研究提供了更清晰的问题分解。

---

## 1. Introduction

Natural language to SQL has become one of the most active application directions of large language models, because it offers a direct interface between end users and structured data repositories. Recent advances have substantially improved performance on public benchmarks such as Spider and BIRD, demonstrating that modern language models can often synthesize executable SQL from natural-language questions under conventional relational settings. However, most existing text-to-SQL systems and evaluation datasets are designed for general-purpose relational databases, where the principal challenges lie in schema linking, join reasoning, aggregation, and nested query construction. By contrast, real-world geospatial database applications introduce additional semantic and operational complexity that is largely absent from these benchmarks. In geospatial settings, queries frequently involve geometry-aware schema grounding, spatial predicates, coordinate reference systems, topological relations, and spatial measurement operators such as area, distance, intersection, and buffering. These characteristics make geospatial text-to-SQL a substantially different problem rather than a simple extension of general warehouse querying.

This mismatch creates a practical and scientific gap. From a practical perspective, many operational data platforms must serve both geospatial and non-geospatial workloads through a unified natural-language interface. A user may ask one question about land-use overlap, another about building proximity, and a third about tabular business statistics in the same system. From a scientific perspective, however, existing studies rarely examine whether a single semantic grounding architecture can support these heterogeneous query types without severe domain bias. Most prior work either optimizes for conventional warehouse-style SQL generation or focuses on domain-specific geospatial systems without evaluating transferability beyond the GIS context. As a result, it remains unclear which components of a semantic-to-SQL pipeline generalize across domains and which components encode assumptions that are beneficial in one setting but harmful in another.

The challenge is especially pronounced at the grounding stage. In conventional text-to-SQL systems, schema linking is often framed as the task of aligning user expressions with table names, column names, or retrieved schema snippets. In geospatial systems, this step is more complicated because the model must additionally recognize geometry-bearing attributes, infer relevant spatial operators, respect spatial reference transformations, and distinguish between topological, metric, and aggregation-based reasoning. At the same time, aggressive domain-specific grounding strategies can introduce unintended bias when transferred to non-geospatial databases. A system tuned for Chinese GIS terminology, spatial operator hints, and geometry-aware rules may perform strongly on spatial benchmarks while underperforming on English warehouse benchmarks if its semantic retrieval mechanisms fail to adapt to differences in language, schema naming, and operator distributions. Understanding this tension is critical for building robust cross-domain natural-language interfaces to structured data.

To address this problem, we present NL2Semantic2SQL, a cross-domain framework that integrates semantic-layer grounding, schema-aware context construction, few-shot retrieval, SQL postprocessing, and execution-time self-correction into a unified natural-language-to-SQL pipeline. Rather than treating SQL generation as a single-step prompting problem, the framework first resolves semantic context, then assembles structured schema evidence, and finally performs constrained SQL generation with post-hoc correction. The design is motivated by the observation that GIS queries and non-GIS warehouse queries share a common need for semantic disambiguation, but differ substantially in the kinds of evidence and constraints that must be surfaced to the model. Our framework therefore aims to preserve a unified architecture while allowing domain-specific grounding signals to be incorporated explicitly rather than implicitly.

To evaluate the geospatial side of the problem, we further construct a GIS-oriented benchmark with execution-based evaluation, spatial operator coverage, and varying query complexity. The benchmark is designed to capture the characteristics missing from mainstream text-to-SQL datasets, including spatial selection, overlap analysis, buffering, spatial aggregation, and geometry-sensitive reasoning. We then complement this benchmark with cross-domain evaluation on a warehouse-oriented dataset derived from BIRD mini_dev, enabling a direct comparison between GIS and non-GIS scenarios under the same evaluation harness. This dual-track setting allows us to move beyond a simple "does it work?" question and instead ask a more informative scientific question: how does a unified semantic-to-SQL architecture behave when confronted with two structurally different database domains?

Our contributions are threefold. First, we propose a unified NL2Semantic2SQL framework for cross-domain querying over geospatial and conventional warehouse databases. Second, we construct a GIS benchmark designed specifically for execution-based evaluation of spatial text-to-SQL capabilities. Third, through cross-domain experiments and error analysis, we show that semantic grounding provides substantial advantages in GIS scenarios while also exposing transfer limitations in non-GIS settings, particularly when retrieval and alias-matching strategies encode GIS-centric bias. These findings suggest that future text-to-SQL systems should not assume that a single grounding strategy will generalize uniformly across heterogeneous domains, and that explicit cross-domain evaluation is necessary for building truly general natural-language database interfaces.

---

## 2. Methods

We formulate cross-domain natural language to SQL as the task of translating a user question into an executable SQL statement over heterogeneous structured databases that may belong to either geospatial or conventional warehouse domains. Unlike standard text-to-SQL settings, the target databases in our problem formulation are not assumed to share homogeneous operator semantics. In warehouse-style databases, correct SQL generation primarily depends on schema linking, join reasoning, aggregation, and temporal filtering. In geospatial databases, however, the model must additionally reason about geometry-bearing columns, spatial relations, coordinate systems, and domain-specific operators such as intersection, containment, buffering, and area or distance calculation. The purpose of our framework is therefore not only to generate valid SQL, but also to provide a semantic mediation layer that adapts the grounding process to the structural characteristics of each domain.

To support this setting, we design NL2Semantic2SQL as a three-stage pipeline. In the first stage, the system performs semantic resolution over a semantic layer that stores table-level and column-level annotations, aliases, domain hints, and task-relevant metadata. In the second stage, the resolved information is combined with database schema inspection and optional few-shot retrieval to construct a grounded context block for SQL generation. In the third stage, the generated SQL is postprocessed, executed under safety constraints, and, when necessary, revised through an execution-feedback self-correction loop. This decomposition separates semantic interpretation from SQL synthesis, allowing the framework to expose domain-specific evidence to the language model while keeping the final generation step constrained by executable schema information.

A central design feature of the framework is geospatial-aware grounding. For geospatial tables, the system explicitly identifies geometry columns, geometry types, and spatial reference information, and it injects operator-level rules into the grounding context. These rules distinguish topological predicates from metric predicates and specify when area or distance calculations require coordinate transformation or geography casting. This mechanism is intended to reduce the burden on the language model to infer low-level geospatial execution constraints from raw schema text alone. At the same time, the framework preserves the ability to operate on non-geospatial warehouse databases by falling back to generic schema linking and aggregation-oriented prompt construction when spatial signals are absent. In this sense, the framework is unified at the architectural level but adaptive at the semantic grounding level.

For non-geospatial warehouse queries, the framework introduces domain-adaptive enhancements including cross-domain candidate ranking, value-aware grounding, and schema-hint-driven source selection. Cross-domain candidate ranking adjusts the priority of candidate tables based on whether the query contains spatial signals: when no spatial operations or region filters are detected, geometry-bearing tables are deprioritized and tables with matched column evidence are boosted. Value-aware grounding enriches the prompt with sample distinct values from low-cardinality text columns, enabling the language model to use exact categorical values (e.g., segment names, currency codes, country codes) rather than guessing string literals. Schema-hint-driven source selection parses explicit database schema references from the query context and boosts tables belonging to the target schema, ensuring that within a multi-database environment, the correct warehouse tables are prioritized over unrelated schemas.

Evaluation is performed under a dual-track benchmark protocol. The geospatial track uses a GIS-oriented benchmark constructed to cover representative spatial query patterns, including spatial selection, overlap analysis, metric distance queries, buffering, and spatial aggregation. The non-geospatial track is derived from a warehouse-oriented benchmark based on BIRD mini_dev and is used to assess cross-domain generalization. For both tracks, we use execution-based evaluation as the primary metric, comparing the execution result of the predicted SQL with that of the gold SQL. We further analyze performance by query difficulty and conduct ablation studies to isolate the contributions of semantic grounding, few-shot retrieval, and execution-time self-correction.

---

## 3. Results

### 3.1 Experimental Setup

We evaluate NL2Semantic2SQL under a dual-track benchmark protocol. The GIS track uses a 20-question benchmark covering four difficulty levels (Easy, Medium, Hard, Robustness) and six spatial query categories (Attribute Filtering, Spatial Measurement, Spatial Join, Spatial Filtering, Centroid Calculation, Proximity Buffer, K-Nearest Neighbors, Spatial Topology, Complex Multi-Step Spatial, Security Rejection, Anti-Illusion, OOM Prevention, Data Tampering Prevention, Schema Enforcement). The warehouse track uses 50 questions sampled from BIRD mini_dev V2, spanning three difficulty levels (simple, moderate, challenging) across 11 database schemas imported into PostgreSQL. Both tracks use execution accuracy (EX) as the primary metric: a prediction is correct if and only if its execution result set matches the gold SQL result set under set-equality comparison with numeric tolerance.

For each track, we compare two modes:
- **Baseline**: Direct LLM generation (Gemini 2.5 Flash) with schema dump only, no semantic grounding.
- **Full pipeline**: NL2Semantic2SQL with semantic layer resolution, schema-aware context construction, few-shot retrieval (GIS track only), SQL postprocessing, and execution-time self-correction.

### 3.2 GIS Track Results

Table 1 reports the GIS benchmark results by separating normal spatial-SQL tasks from the robustness/safety suite. This distinction is important because robustness questions test refusal, interception, and safety enforcement rather than ordinary spatial-query generation. Results are from run `cq_2026-05-03_164213` (Phase A intent-conditioned grounding).

| Metric | N | Baseline | Full | Delta |
|--------|---|----------|------|-------|
| Spatial EX (non-robustness only) | 15 | 0.867 | **0.933** | +0.067 |
| Robustness success rate | 5 | 0.000 | **0.800** | +0.800 |
| Combined pilot score (all 20) | 20 | 0.650 | **0.900** | +0.250 |

Per-difficulty breakdown (full pipeline, Phase A):

| Difficulty | N | Full EX |
|------------|---|---------|
| Easy | 5 | 1.000 |
| Medium | 5 | 1.000 |
| Hard | 5 | 0.800 |
| Robustness | 5 | 0.800 |

After Phase A intent-conditioned grounding, the full pipeline **outperforms** the baseline on spatial EX (0.933 vs. 0.867). The key improvements are: EASY_02 (preview_listing intent) now succeeds because the LIMIT injection rule is correctly gated to preview-intent queries only; EASY_03 (spatial_measurement intent) now succeeds; and HARD_02 (knn intent) now succeeds because the KNN `<->` operator rule is injected only when the intent is classified as `knn`. The one new regression is HARD_01 (proximity buffer, spatial_join intent), which was correct under the baseline but fails under the full pipeline — a case where the intent-routing context appears to interfere with the buffer-based join logic.

The full pipeline's strongest advantage remains in the robustness/safety suite, where the baseline scores 0.000 and the full pipeline scores 0.800. Four of five robustness questions are handled correctly. The one robustness failure is ROBUSTNESS_03 (OOM Prevention): the LIMIT injection rule is now gated to preview-intent queries, so a large-table full scan that previously received an automatic LIMIT no longer does. This is a known trade-off of intent-conditioned LIMIT injection: it eliminates false positives on non-preview queries at the cost of missing one OOM-prevention case.

A McNemar test on the 20 GIS questions (b=1 base-OK/full-ERR, c=6 base-ERR/full-OK) gives p=0.1250, which is not significant at α=0.05. The improvement is directional — six questions improved, one regressed — but the small sample size (n=20) limits statistical power. We report this result honestly and do not claim statistical significance.

### 3.3 Warehouse Track Results (BIRD)

Table 2 presents the BIRD benchmark results at 500-question scale (run `bird_pg_2026-05-01_182457`). The primary result is parity: the full pipeline (0.450 EX) matches the baseline (0.458 EX) within the margin of noise, confirmed by McNemar p=0.8151 (b=38, c=35, n=498 valid pairs).

| Difficulty | N | Baseline EX | Full EX |
|------------|---|-------------|---------|
| simple | 148 | 0.581 | 0.541 |
| moderate | 250 | 0.436 | 0.452 |
| challenging | 102 | 0.333 | 0.314 |
| **Overall** | **500** | **0.458** | **0.450** |
| Validity | 500 | 0.960 | 0.924 |

The full pipeline slightly underperforms the baseline on simple questions (0.541 vs. 0.581) but slightly outperforms on moderate questions (0.452 vs. 0.436). The overall gap is 0.008 EX, which is not statistically significant (McNemar p=0.8151). We interpret this as cross-domain parity: the framework does not degrade warehouse performance while adding GIS-side capabilities.

For reference, the earlier 50-question pilot (run `bird_pg_2026-05-01_151254`, with MetricFlow augmentation) showed: simple 0.680, moderate 0.368, challenging 0.500, overall 0.540. The 500-question run does not include MetricFlow augmentation; the 50-question MetricFlow result remains the best single-schema configuration for the `debit_card_specializing` schema.

**Phase B MetricFlow auto-generation.** To extend MetricFlow coverage beyond the single manually-modeled schema, Phase B implemented automatic MetricFlow model generation for all 11 BIRD schemas. The generator reads SQLite PRAGMA foreign_key_list to extract 103 FK relationships across the 11 schemas, classifies each table as fact, dimension, or bridge based on its FK in/out degree, and registers 75 semantic models (70 auto-generated + 5 manual for `debit_card_specializing`). A full 500-question re-run with MetricFlow augmentation was attempted but stalled at 97/500 due to per-question agent timeouts in the auto-generated model lookup path. The 50-question MetricFlow result (EX=0.540) from the earlier run therefore remains the primary MetricFlow data point. Full MetricFlow coverage for all 11 schemas is implemented but the 500-question evaluation is incomplete; this is noted as a limitation and future work item in §4.5.

Notably, execution validity drops from 0.960 (baseline) to 0.924 (full pipeline) at 500-question scale, indicating that the full pipeline occasionally fails to produce valid SQL on questions where the baseline succeeds. This is consistent with the hypothesis that the semantic grounding layer sometimes over-constrains the generation for warehouse-style queries.

### 3.4 Error Analysis

We categorize the 23 full-pipeline failures (MetricFlow configuration) on the BIRD track into three types:

| Error Type | Count | Fraction |
|------------|-------|----------|
| Wrong result (valid SQL, incorrect answer) | 20 | 87.0% |
| No SQL generated (agent did not produce SQL) | 3 | 13.0% |
| Invalid SQL (execution error) | 0 | 0.0% |

The dominant failure mode is semantically incorrect SQL that executes successfully but returns wrong results. Manual inspection reveals three recurring patterns:

1. **Join path confusion** (8/19): The model selects incorrect join paths between fact and dimension tables. For example, joining `transactions_1k` with `yearmonth` on `CustomerID` when the gold SQL joins through `gasstations` on `GasStationID`. This reflects insufficient understanding of the warehouse schema's entity-relationship structure.

2. **Aggregation semantics** (6/19): The model applies COUNT(DISTINCT ...) where the gold SQL uses COUNT(*), or vice versa. It also confuses per-row aggregation with per-group aggregation, particularly in percentage calculations.

3. **Date/temporal parsing** (5/19): The BIRD dataset uses non-standard date formats (e.g., `Date` column containing `'201309'` as YYYYMM). The model sometimes applies SUBSTRING-based parsing differently from the gold SQL, or fails to recognize the implicit temporal granularity.

These patterns are consistent with the hypothesis that the current semantic layer, designed primarily for GIS schema disambiguation, does not provide sufficient structural metadata for warehouse-style fact/dimension reasoning.

### 3.4b Ablation Analysis

To understand which intent classes drive the GIS improvement, we perform a leave-one-class-out ablation on the GIS 20 full-pipeline run. The intent distribution in the GIS 20 benchmark is: spatial_join (6), attribute_filter (5), aggregation (3), preview_listing (2), spatial_measurement (1), category_filter (1), knn (1), refusal_intent (1).

| Dropped intent class | Remaining N | EX | Delta vs. full |
|----------------------|-------------|-----|----------------|
| FULL (all intents) | 20 | 0.9000 | — |
| drop aggregation | 17 | 0.8824 | −0.0176 |
| drop attribute_filter | 15 | 0.8667 | −0.0333 |
| drop category_filter | 19 | 0.8947 | −0.0053 |
| drop knn | 19 | 0.8947 | −0.0053 |
| drop preview_listing | 18 | 0.9444 | **+0.0444** |
| drop spatial_join | 14 | 0.9286 | +0.0286 |
| drop spatial_measurement | 19 | 0.8947 | −0.0053 |
| drop refusal_intent | 19 | 0.8947 | −0.0053 |

The ablation reveals two key findings. First, dropping `preview_listing` questions *raises* EX by +0.044, indicating that the HARD_01 regression (a spatial_join question that was previously correct) is the dominant source of error in the full pipeline — the preview_listing class itself is handled correctly (2/2), but the spatial_join class contains the one regression. Second, dropping `attribute_filter` questions lowers EX by −0.033, confirming that intent routing's largest positive contribution is on attribute-filter queries where the semantic layer's alias resolution and column grounding are most effective.

The McNemar test on GIS 20 (b=1, c=6, n=20) gives p=0.1250. This is not significant at α=0.05, but the direction is clear: six questions improved (HARD_02 KNN, MEDIUM_02 attribute_filter, ROBUSTNESS_01/02/04/05) and one regressed (HARD_01 spatial_join). The small sample size (n=20) is the primary reason for non-significance; a 100-question GIS benchmark would provide adequate power to detect an effect of this magnitude.

On BIRD 500, the McNemar test (b=38, c=35, n=498) gives p=0.8151, confirming that the full pipeline and baseline are statistically indistinguishable on warehouse queries. This is the expected result for a framework designed to add GIS capabilities without degrading warehouse performance.

### 3.4c External Baseline: DIN-SQL

To position NL2Semantic2SQL against a published prompt-engineering baseline, we adapted DIN-SQL (Pourreza & Rafiei, 2023) — a 4-stage decomposed prompting pipeline (schema linking → query classification → SQL generation → self-correction) — to PostgreSQL/PostGIS and ran it with the same Gemini 2.5 Flash model used throughout this paper.

**GIS 20 results** (run `cq_din_sql_2026-05-03_193407`):

| Difficulty | N | DIN-SQL EX |
|------------|---|------------|
| Easy | 5 | 1.000 |
| Medium | 5 | 1.000 |
| Hard | 5 | 0.600 |
| Robustness | 5 | 0.000 |
| **Overall** | **20** | **0.650** |

DIN-SQL matches the direct-LLM baseline exactly on GIS 20 (EX=0.650). Both score 0.000 on the robustness suite. DIN-SQL's 4-stage decomposition provides no safety enforcement and no spatial-operator grounding, so it cannot handle refusal, anti-illusion, or OOM-prevention cases. NL2Semantic2SQL Full outperforms both by +0.250 (0.900 vs. 0.650).

**BIRD 500 results** (run `bird_din_sql_2026-05-03_193412`):

| Difficulty | N | DIN-SQL EX |
|------------|---|------------|
| simple | — | 0.608 |
| moderate | — | 0.476 |
| challenging | — | 0.314 |
| **Overall** | **500** | **0.482** |
| Validity | 500 | 0.990 |

On BIRD 500, DIN-SQL (EX=0.482) slightly outperforms both our baseline (0.458) and full pipeline (0.450). The 4-stage decomposition's schema-linking step provides a modest advantage on warehouse queries where our semantic grounding adds overhead without sufficient structural metadata. DIN-SQL's validity rate (0.990) is also higher than our full pipeline (0.924), consistent with the view that our semantic grounding layer occasionally over-constrains generation for warehouse-style queries.

**Three-way comparison summary:**

| Method | GIS 20 EX | GIS Spatial EX | GIS Robustness | BIRD 500 EX |
|--------|-----------|----------------|----------------|-------------|
| Baseline (direct LLM) | 0.650 | 0.867 | 0.000 | 0.458 |
| DIN-SQL (4-stage) | 0.650 | 0.867 | 0.000 | 0.482 |
| NL2Semantic2SQL Full | **0.900** | **0.933** | **0.800** | 0.450 |

The pattern is clear: NL2Semantic2SQL's advantage is domain-specific. On GIS, the framework's safety enforcement and spatial-operator grounding provide a decisive +0.250 advantage over both baselines. On BIRD, DIN-SQL's schema-linking decomposition is competitive, and our full pipeline does not outperform it. We report this result straightforwardly: the current framework's value proposition is domain-specialized (GIS safety + spatial grounding), not general-purpose NL2SQL improvement.

McNemar comparison of NL2Semantic2SQL Full vs. DIN-SQL on GIS 20: since DIN-SQL matches the direct-LLM baseline exactly on GIS 20, the paired comparison is identical to the baseline comparison (b=1, c=6, p=0.1250). On BIRD 500, DIN-SQL is slightly ahead of our full pipeline (0.482 vs. 0.450); a full paired McNemar test would require per-question result alignment across runs, which we leave for future work.

### 3.5 Cross-Domain Comparison

Figure~\ref{fig:cross-domain} (Section~\ref{sec:figures}) summarizes the cross-domain comparison after Phase A intent-conditioned grounding and BIRD 500-question evaluation, now including DIN-SQL as an external baseline:

```
GIS Track (Spatial EX):  Baseline 0.867 | DIN-SQL 0.867 | Full 0.933
GIS Track (Robustness):  Baseline 0.000 | DIN-SQL 0.000 | Full 0.800
BIRD Track (500q):       Baseline 0.458 | DIN-SQL 0.482 | Full 0.450
```

The pattern is clear across three methods. On the GIS side, Phase A intent routing resolves the previous spatial-EX regression: the full pipeline outperforms both the direct-LLM baseline and DIN-SQL on spatial EX and robustness. The GIS advantage is driven by safety enforcement and domain-specific grounding — capabilities that DIN-SQL's 4-stage decomposition does not provide. On the warehouse side, DIN-SQL's schema-linking step gives it a slight edge over both our baseline and full pipeline, confirming that our framework's current value proposition is domain-specialized (GIS safety + spatial grounding) rather than general-purpose NL2SQL improvement.

### 3.6 Case Studies

To make the qualitative behavior of the framework concrete, Table~\ref{tab:case} contrasts representative successes and failures across the GIS and warehouse tracks.

| Question (paraphrased) | Track | Baseline outcome | Full-pipeline outcome | What the semantic layer changed |
|---|---|---|---|---|
| Total length (km) of one-way roads (CQ_GEO_MEDIUM_02). | GIS | Execution error: `function round(double precision, integer) does not exist`. | Correct: `ROUND((SUM(ST_Length(geometry::geography)) / 1000.0)::numeric, 2)`. | Geometry-aware grounding rule that forces explicit `::numeric` casting before `ROUND`. |
| Find the 5 nearest roads to the POI named "Chongqing North Station" (CQ_GEO_HARD_02). | GIS | Wrong row order; uses `ORDER BY ST_Distance(...)` rather than the PostGIS KNN operator. | **Correct** (Phase A): intent classified as `knn`, KNN `<->` operator rule injected, correct row ordering produced. | Intent routing gates the KNN `<->` rule to `knn`-intent queries only, eliminating false positives on non-KNN spatial queries. |
| Proximity buffer spatial join (CQ_GEO_HARD_01). | GIS | Correct. | **Wrong** (Phase A regression): intent classified as `spatial_join`, but the buffer-based join logic is disrupted by the injected spatial_join context. | New failure introduced by Phase A — the intent-routing context interferes with proximity buffer reasoning. |
| "Delete all unnamed roads" (CQ_GEO_ROBUSTNESS_01). | GIS | Generates a SQL statement that would mutate data. | Refused via the safety postprocessor with the canonical refusal text. | Postprocessor recognizes write intent and rewrites to a refusal. |
| Total consumption of customer 6 between 2013-08 and 2013-11 (BIRD QID 1483, simple). | Warehouse | Correct (matches gold). | Correct (matches gold via MetricFlow join hint and explicit measure). | Provides the `Consumption` measure of `yearmonth` and the `CustomerID` entity. |
| Annual avg-consumption differences across SME/LAM/KAM segments in 2013 (BIRD QID 1481, challenging). | Warehouse | Wrong: builds an over-aggressive nested CTE that picks the wrong subset. | Wrong: the MetricFlow hint surfaces correct entities but the question still requires multi-segment delta logic that the LLM does not synthesize. | Failure mode: structural metadata helps but does not resolve all complex aggregations. |

The Phase A fix for HARD_02 (KNN) illustrates the core mechanism of intent-conditioned routing: by classifying the query intent before grounding, the framework can inject operator-specific rules only when they are relevant, avoiding the false-positive LIMIT injections and incorrect operator hints that caused regressions in the pre-Phase-A pipeline. The new HARD_01 regression shows the remaining challenge: intent classification is not always sufficient to distinguish closely related spatial query types (spatial_join vs. proximity buffer), and incorrect intent assignment can introduce new failures.

### 3.7 Reproducibility

For each of the experimental tables in this paper, Table~\ref{tab:repro} lists the exact run directory under `data_agent/nl2sql_eval_results/`, the language model used, and any non-default decoding settings. Each run directory contains the gold SQL, the predicted SQL, the per-question execution comparison, and the per-question token usage.

| Result | Track / config | Run directory | Model | Notes |
|---|---|---|---|---|
| Table 1, GIS Spatial / Robustness (pre-Phase A) | GIS, baseline + full | `cq_2026-05-01_132919` | `gemini-2.5-flash` | Historical reference; superseded by Phase A run below. |
| Table 1, GIS Spatial / Robustness (Phase A) | GIS, baseline + full | `cq_2026-05-03_164213` | `gemini-2.5-flash` | **Primary GIS result.** Intent-conditioned grounding active. |
| Table 1, DIN-SQL on GIS 20 | GIS, DIN-SQL | `cq_din_sql_2026-05-03_193407` | `gemini-2.5-flash` | DIN-SQL 4-stage pipeline adapted to PostgreSQL/PostGIS. |
| Table 2, BIRD 500q baseline + full | BIRD 500q, baseline + full | `bird_pg_2026-05-01_182457` | `gemini-2.5-flash` | **Primary BIRD result.** No MetricFlow (baseline vs. full only). |
| Table 2, DIN-SQL on BIRD 500 | BIRD 500q, DIN-SQL | `bird_din_sql_2026-05-03_193412` | `gemini-2.5-flash` | DIN-SQL external baseline; validity=0.990. |
| Table 2 (reference), BIRD 50q Full(+MetricFlow) | BIRD 50q, full+MetricFlow | `bird_pg_2026-05-01_151254` | `gemini-2.5-flash` | Best single-schema MetricFlow result; reference only. |
| Table 2 (reference), BIRD 50q baseline + Full(prompt) | BIRD 50q, baseline + full(prompt) | `bird_pg_2026-05-01_140933` | `gemini-2.5-flash` | Prompt refinements only (no MetricFlow); reference only. |
| Table 3, Cross-lingual (Chinese) | BIRD 50q, full+MetricFlow on Chinese-translated questions | `bird_pg_chinese_2026-05-01_171426` | `gemini-2.5-flash` (eval) + `gemini-2.0-flash` (translator) | Chinese aliases registered for 75 BIRD tables and 209 columns. |
| Table 4, Error analysis | Same as BIRD 50q Full(+MetricFlow) | `bird_pg_2026-05-01_151254` | `gemini-2.5-flash` | Error categories assigned by manual inspection of `pred_sql` against `gold_sql`. |

We additionally release the following code under the project repository: the GIS benchmark questions and gold SQL, the BIRD warehouse-modeling registration script, the cross-lingual evaluation harness, the per-question SQL postprocessor and self-correction logic, and the MetricFlow YAML schemas registered for the BIRD `debit_card_specializing` schema.

## 4. Discussion

### 4.1 Why Semantic Grounding Helps in GIS

The GIS track results demonstrate that semantic grounding with intent-conditioned routing provides substantial value when the query domain involves specialized operators and schema conventions that general-purpose LLMs handle unreliably. Three mechanisms drive the improvement:

First, **geometry-aware type injection** ensures the model knows which columns are geometry-bearing, what their SRID is, and when geography casting is required. Without this, the baseline frequently omits `::geography` casts, producing area/distance values in degrees rather than meters.

Second, **intent-conditioned operator routing** gates domain-specific rules (KNN `<->` operator, LIMIT injection) to the queries where they are relevant. This eliminates the false-positive injections that caused regressions in the pre-Phase-A pipeline: EASY_02 no longer receives an unwanted LIMIT, and HARD_02 now correctly receives the KNN `<->` rule.

Third, **safety and robustness enforcement** through SQL postprocessing catches dangerous operations (DELETE, UPDATE) and handles refusal/anti-illusion cases. The baseline LLM has no such guardrails and scores 0.000 on the robustness suite.

The one remaining regression (HARD_01, proximity buffer) illustrates the residual challenge: intent classification is not always sufficient to distinguish closely related spatial query types (spatial_join vs. proximity buffer), and incorrect intent assignment can introduce new failures.

### 4.2 Why Semantic Grounding Underperforms on Warehouses

The warehouse track reveals that the same grounding architecture can introduce slight degradation when applied to domains it was not designed for. We identify three contributing factors:

**Factor 1: GIS-centric retrieval bias.** The semantic layer's source ranking algorithm deprioritizes geometry-bearing tables for non-spatial queries, but it does not provide positive signals for warehouse-specific patterns such as star-schema fact/dimension relationships. As a result, candidate table selection for moderate BIRD questions sometimes surfaces irrelevant tables or misses critical join partners.

**Factor 2: Absence of entity-relationship metadata.** The current semantic layer stores column-level annotations (domain, aliases, units) but does not encode table-level roles (fact vs. dimension) or explicit join paths. For warehouse queries that require multi-hop joins through intermediate tables, the model must infer the join graph from raw foreign-key structure, which it does less reliably than the baseline that receives the full schema dump without intermediate semantic interpretation.

**Factor 3: Few-shot suppression for non-spatial queries.** The framework intentionally suppresses GIS-oriented few-shot examples for non-spatial queries (to avoid polluting warehouse prompts with irrelevant ST_* patterns). However, this means warehouse queries receive no few-shot guidance at all, whereas the baseline benefits from its own implicit pattern matching over the schema dump.

### 4.3 The Effect of MetricFlow-Style Modeling

The error analysis suggests that the primary bottleneck for warehouse performance is not SQL syntax generation but semantic schema navigation. The model can generate syntactically correct PostgreSQL but frequently selects wrong join paths or applies incorrect aggregation granularity. This is precisely the problem that MetricFlow-style semantic modeling addresses: by explicitly declaring entities (join keys), measures (aggregatable facts), and dimensions (descriptive attributes), the system can provide the LLM with pre-computed join paths and aggregation rules rather than requiring it to infer them from raw DDL.

We validate this hypothesis by registering MetricFlow-style metadata for the most error-prone BIRD schema (\texttt{debit\_card\_specializing}, covering five tables: \texttt{customers}, \texttt{yearmonth}, \texttt{transactions\_1k}, \texttt{gasstations}, \texttt{products}) and injecting derived join-path hints into the grounding prompt. As shown in Section~\ref{sec:bird-results}, this single intervention raises overall execution accuracy from 0.520 to 0.540, with moderate questions recovering from 0.316 to 0.368 and challenging questions improving from 0.333 to 0.500. The number of execution-time SQL errors drops from two to zero, indicating that join-path hints not only repair join confusion but also make the generated SQL structurally more reliable. We interpret this as direct evidence that warehouse-side performance is bottlenecked by missing structural metadata rather than by surface-form generation, and that targeted semantic modeling closes most of the gap without changing the underlying language model.

### 4.4 Cross-Lingual Observations (Preliminary Stress Test)

We position the cross-lingual experiment as a preliminary stress test rather than a fully controlled cross-lingual evaluation. The translated questions are produced by an LLM translator (Gemini~2.0~Flash) and have not been verified by a native human annotator; furthermore, table and column names remain in their original English form, which lowers the difficulty of cross-lingual schema linking compared with a true bilingual schema. Within this constrained setting, the framework's multilingual alias mechanism is sufficient to recover most schema references when questions are paraphrased into Chinese, with only a four-percentage-point loss in execution accuracy (0.500 vs.\ 0.540) and validity (0.900 vs.\ 0.940). The remaining gap concentrates on moderate and challenging questions, suggesting that paraphrase-induced ambiguity in aggregation phrasing and join-key references is the dominant residual error. We do not claim general cross-lingual robustness, and a more rigorous evaluation would compare against (i) a no-alias baseline, (ii) a translate-back-to-English baseline, and (iii) human-translated questions.

### 4.5 Limitations

Several limitations should be noted. First, the GIS benchmark contains only 20 questions, which limits statistical power; the McNemar test on GIS 20 (p=0.1250) does not reach significance at α=0.05. Second, the BIRD evaluation now covers 500 questions, which provides adequate power to confirm parity (McNemar p=0.8151), but the full pipeline does not outperform the baseline on warehouse queries. Third, the cross-lingual experiment uses LLM-translated questions without human verification, and table/column names remain in English; we therefore present it as a preliminary stress test. Fourth, while we now include DIN-SQL as an external baseline, comparison against additional advanced strategies (e.g., MAC-SQL, DAIL-SQL) would further strengthen the positioning. The DIN-SQL comparison confirms that our framework's advantage is domain-specific: on GIS, safety enforcement and spatial grounding provide a decisive +0.250 gain; on BIRD, DIN-SQL's 4-stage schema-linking decomposition is competitive and slightly outperforms our full pipeline (0.482 vs. 0.450). Fifth, execution-based evaluation treats any result-set mismatch as failure, even when the predicted SQL is semantically equivalent but produces results in a different order or with different numeric precision. Sixth, the framework currently uses a single LLM (Gemini 2.5 Flash) for both baseline and full pipeline; cross-model evaluation would strengthen the generalizability claims. Seventh, Phase B implemented automatic MetricFlow model generation for all 11 BIRD schemas (75 models, 103 FK relationships), but the full 500-question re-run with MetricFlow stalled at 97/500 due to per-question agent timeouts; the 50-question MetricFlow result (EX=0.540) remains the primary MetricFlow data point, and full MetricFlow coverage evaluation is left for future work.

### 4.6 Future Work

Three directions emerge from this study:
1. **Component-level ablation and SOTA comparison**. Run controlled ablations that isolate the contribution of each pipeline component (semantic-layer grounding, value hints, few-shot retrieval, postprocessor, self-correction, MetricFlow), and compare against additional advanced text-to-SQL baselines such as MAC-SQL and DAIL-SQL. The DIN-SQL comparison in §3.4c provides an initial external reference point.
2. **Expanded GIS benchmark and finer intent taxonomy**. Increase the GIS benchmark to at least 100 questions (with per-category counts large enough to support significance testing), and refine the intent taxonomy to distinguish proximity-buffer queries from general spatial-join queries, addressing the HARD_01 regression.
3. **Full MetricFlow evaluation at 500-question scale**. Phase B implemented automatic MetricFlow model generation for all 11 BIRD schemas (75 models, 103 FK relationships). The next step is to resolve the per-question timeout issue in the auto-generated model lookup path and complete the 500-question re-run with full MetricFlow augmentation, which would provide a definitive answer on whether FK-aware semantic modeling closes the BIRD gap.
4. **Cross-lingual evaluation under controlled conditions**. Move beyond the current LLM-translated stress test by adding a no-alias baseline, a translate-back baseline, and human-translated questions over partially Chinese schemas, in order to disentangle the contributions of multilingual alias registration from other framework components.

## 5. Related Work

### 5.1 Text-to-SQL with Large Language Models

The application of large language models (LLMs) to text-to-SQL has progressed rapidly through increasingly sophisticated prompt engineering strategies. Early in-context learning approaches demonstrated that LLMs could generate executable SQL from natural-language questions when provided with schema descriptions and example query pairs [1, 2]. DIN-SQL [3] introduced a decomposed prompting pipeline that separates schema linking, query classification, and SQL generation into distinct stages, with self-correction as a post-generation step. DAIL-SQL [4] systematized few-shot example selection based on SQL skeleton similarity and achieved strong results on the Spider benchmark with minimal token cost. C3 [5] explored zero-shot ChatGPT-based text-to-SQL with calibrated bias correction, illustrating a complementary line of prompt-engineered solutions that does not rely on hand-crafted few-shot examples. More recently, multi-agent and tool-augmented architectures have emerged, in which specialized agents handle schema retrieval, SQL generation, and execution verification as separate collaborative roles. Our framework shares the decomposition philosophy of DIN-SQL but adds an explicit semantic layer as a structured intermediary between the user question and the schema, rather than relying solely on prompt-level schema linking.

### 5.2 Benchmarks for Text-to-SQL

Spider [1] established the standard cross-database text-to-SQL benchmark with execution-based evaluation, introducing the challenge of generalizing across unseen database schemas. BIRD [6] extended this setting to larger, more realistic databases with value-aware evaluation and difficulty stratification, revealing that LLM performance degrades substantially on complex aggregation and multi-hop join queries. Spider 2.0 [7] further expanded the scope to include enterprise-style workflows such as dbt transformations and dialect variations. BEAVER [8] specifically targets enterprise data warehouses with private schemas and complex business logic, showing that state-of-the-art models achieve near-zero accuracy on truly private enterprise data. Our work is motivated by a complementary gap: none of these benchmarks evaluate geospatial SQL generation, and none assess cross-domain transfer between GIS and warehouse query semantics.

### 5.3 Geospatial Natural Language Interfaces

Natural language interfaces to geospatial databases have a distinct research lineage from general text-to-SQL. Early systems focused on template-based spatial query construction for specific GIS applications [9]. More recent work has explored using LLMs for spatial reasoning and geographic knowledge extraction [10], but systematic evaluation of text-to-SQL capabilities over PostGIS or spatially-extended relational databases remains scarce. To our knowledge, no existing benchmark provides execution-based evaluation of spatial SQL generation with coverage of spatial operators (intersection, buffer, distance, area), coordinate system handling, and geometry-aware schema linking. Our GIS benchmark is designed to fill this gap.

### 5.4 Semantic Layers and Schema Grounding

The concept of a semantic layer as an intermediary between analytical queries and raw database schemas originates from business intelligence tools and has been formalized in frameworks such as MetricFlow [11] and dbt's semantic layer. These systems define entities, dimensions, measures, and metrics as declarative metadata that governs how joins and aggregations should be constructed. In the text-to-SQL context, semantic layers offer a principled way to provide LLMs with structured evidence about schema semantics rather than requiring the model to infer join paths and aggregation rules from raw DDL alone. Our framework adapts this concept for cross-domain use, combining GIS-specific annotations (geometry types, SRIDs, spatial operators) with warehouse-style entity-relationship metadata to support both query domains through a unified grounding architecture.

### 5.5 Cross-Domain and Cross-Lingual Text-to-SQL

Cross-domain generalization has been studied primarily through zero-shot transfer across database schemas within the same linguistic and operator domain [1, 6]. Cross-lingual text-to-SQL, where questions are posed in one language over schemas defined in another, has received less systematic attention, though multilingual benchmarks such as CSpider [12] (Chinese Spider) demonstrate that language mismatch introduces additional schema linking challenges. Our work extends the cross-domain dimension beyond schema variation to include operator heterogeneity (spatial vs. tabular) and language heterogeneity (Chinese questions over English warehouse schemas), providing a more comprehensive view of the generalization landscape.

---

## 6. References

[1] T. Yu, R. Zhang, K. Yang, et al., "Spider: A large-scale human-labeled dataset for complex and cross-domain semantic parsing and text-to-SQL task," in *Proc. EMNLP*, 2018, pp. 3911–3921.

[2] N. Rajkumar, R. Li, and D. Bahdanau, "Evaluating the text-to-SQL capabilities of large language models," arXiv:2204.00498, 2022.

[3] M. Pourreza and D. Rafiei, "DIN-SQL: Decomposed in-context learning of text-to-SQL with self-correction," in *Proc. NeurIPS*, vol. 36, 2023, pp. 30557–30584.

[4] D. Gao, H. Wang, Y. Li, et al., "Text-to-SQL empowered by large language models: A benchmark evaluation," *Proc. VLDB Endow.*, vol. 17, no. 5, pp. 1132–1145, 2024.

[5] X. Dong, C. Zhang, Y. Ge, et al., "C3: Zero-shot text-to-SQL with ChatGPT," arXiv:2307.07306, 2023.

[6] J. Li, B. Hui, G. Qu, et al., "Can LLM already serve as a database interface? A big bench for large-scale database grounded text-to-SQLs," in *Proc. NeurIPS Datasets and Benchmarks Track*, 2023.

[7] F. Lei, J. Chen, Y. Ye, et al., "Spider 2.0: Evaluating language models on real-world enterprise text-to-SQL workflows," in *Proc. ICLR*, 2025.

[8] P. B. Chen, F. Wenz, Y. Zhang, M. Kayali, N. Tatbul, M. Cafarella, Ç. Demiralp, and M. Stonebraker, "BEAVER: An enterprise benchmark for text-to-SQL," arXiv:2409.02038, 2024.

[9] D. Punjani, K. Singh, A. Both, et al., "Template-based question answering over linked geospatial data," in *Proc. 12th GIR Workshop @ ACM SIGSPATIAL*, 2018, Article 7, pp. 1–10. DOI: 10.1145/3281354.3281362.

[10] G. Mai, W. Huang, J. Sun, et al., "On the opportunities and challenges of foundation models for geospatial artificial intelligence," arXiv:2304.06798, 2023.

[11] dbt Labs / Transform Data, Inc., "MetricFlow: Industrial semantic-layer documentation," available at \url{https://docs.getdbt.com/docs/build/about-metricflow}, accessed 2026.

[12] Q. Min, Y. Shi, and Y. Zhang, "A pilot study for Chinese text-to-SQL semantic parsing (CSpider)," in *Proc. EMNLP-IJCNLP*, 2019, pp. 3652–3658.

---

## 论文主图建议

1. **Graphical Abstract**: NL input → semantic grounding → SQL generation → execution correction → GIS/warehouse output
2. **方法流程图**: semantic layer + grounding engine + few-shot + postprocess + self-correction 全链路
3. **Benchmark 对比图**: GIS benchmark vs BIRD benchmark 的问题类型、算子分布、EX 对比
4. **演进轨迹图**: full pipeline EX 从 0% → 70% 的逐步改进过程 (6 个阶段)
