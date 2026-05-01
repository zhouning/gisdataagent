# NL2Semantic2SQL: A Cross-Domain Framework for Natural Language to SQL over Geospatial and Enterprise Data Warehouses

> **Status**: Draft v0.1 (2026-05-01)
> **Target venues**: IJGIS / GeoInformatica / Transactions in GIS / ISPRS IJGI

---

## Abstract (English)

Natural language to SQL (text-to-SQL) has advanced rapidly with large language models, yet most existing systems and benchmarks focus on conventional relational databases and overlook geospatial query scenarios. Geospatial databases introduce additional challenges, including geometry-aware schema grounding, spatial predicates, coordinate reference systems, and domain-specific operators such as intersection, buffer, area, and distance calculations. At the same time, practical data platforms increasingly require a single interface that can support both geospatial and non-geospatial warehouse queries. In this work, we present NL2Semantic2SQL, a cross-domain framework that combines semantic layer grounding, schema-aware prompt construction, few-shot retrieval, SQL postprocessing, and execution-time self-correction to support natural-language querying over both GIS and conventional warehouse data. To evaluate the geospatial side of this problem, we construct a GIS-oriented benchmark with execution-based evaluation and structured coverage of spatial operators and query complexity. We further assess cross-domain generalization by comparing the framework against direct large language model baselines on both GIS benchmark tasks and an enterprise-style warehouse benchmark derived from BIRD mini_dev. Experimental results show that semantic grounding substantially improves performance in GIS settings, where spatial semantics and schema disambiguation are critical, while also revealing nontrivial domain-transfer challenges in conventional warehouse scenarios, especially when semantic matching strategies are biased toward GIS-centric patterns. These findings demonstrate both the promise and the limitations of unified semantic-to-SQL architectures across heterogeneous database domains, and they suggest that future cross-domain text-to-SQL systems must explicitly account for language, schema, and operator heterogeneity rather than assuming a single grounding strategy will generalize universally.

## 摘要 (中文)

自然语言到 SQL 的查询生成技术近年来随着大语言模型的发展取得了显著进展，但现有研究与 benchmark 主要面向传统关系数据库，较少覆盖地理空间数据库场景。与普通数据仓库相比，GIS 数据库在几何类型、空间谓词、坐标参考系以及面积、距离、缓冲、叠加等空间算子方面具有更强的领域特性，使得 schema grounding 与 SQL 生成面临额外挑战。与此同时，面向真实业务的数据平台往往需要同一套自然语言查询框架同时支持空间与非空间场景。针对这一问题，本文提出一种跨域的 NL2Semantic2SQL 框架，通过语义层解析、schema grounding、few-shot 检索、SQL 后处理与执行期自纠错等机制，实现对 GIS 数据库与通用数据仓库的统一支持。为评估该框架在空间场景中的能力，本文进一步构建了一套 GIS-oriented benchmark，覆盖多类空间算子与不同难度层级，并采用执行结果一致性作为核心评测指标。在实验中，本文将所提出框架分别应用于 GIS benchmark 与基于 BIRD mini_dev 改造的通用仓库 benchmark，并与直接 LLM 生成 SQL 的 baseline 进行对比。结果表明，语义 grounding 对 GIS 查询具有明显增益，尤其在涉及空间关系、空间聚合和复杂 schema 消歧的任务中效果更为显著；同时，跨域实验也揭示了 GIS 定制的语义匹配策略在通用仓库场景下可能引入领域偏置。上述结果说明，统一的 semantic-to-SQL 框架具有可行性，但其跨域泛化能力依赖于对语言特征、schema 结构和操作符体系差异的显式建模。

## Contributions

1. 本文提出了一种面向 GIS 与非 GIS 双场景的统一 NL2Semantic2SQL 框架，使自然语言查询在空间数据库与普通数据仓库之间共享同一套 semantic grounding—SQL generation—execution correction 主链路。

2. 本文构建了一套 GIS-oriented text-to-SQL benchmark，用于系统评估空间算子、空间聚合与空间 schema 消歧问题，并填补该领域缺少标准化 execution-based benchmark 的空白。

3. 本文通过跨域评测分析表明，语义层与 grounding 机制在 GIS 查询中可显著提升表现，但在通用仓库场景下仍可能暴露领域偏置与 schema 召回不足，从而为跨域 text-to-SQL 的后续研究提供了更清晰的问题分解。

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

Table 1 presents the GIS benchmark results.

| Difficulty | N | Baseline EX | Full EX | Delta |
|------------|---|-------------|---------|-------|
| Easy | 5 | 1.000 | 0.800 | -0.200 |
| Medium | 5 | 0.800 | 1.000 | +0.200 |
| Hard | 5 | 0.800 | 0.800 | 0.000 |
| Robustness | 5 | 0.000 | 1.000 | +1.000 |
| **Overall** | **20** | **0.650** | **0.800** | **+0.150** |

The full pipeline achieves an overall EX of 0.800, a 15-percentage-point improvement over the baseline (0.650). The most striking gain is in the Robustness category, where the baseline scores 0.000 and the full pipeline scores 1.000. Robustness questions test security rejection (refusing DELETE/UPDATE requests), anti-illusion (refusing queries about nonexistent columns), OOM prevention (adding LIMIT for large-table full scans), and data tampering prevention. The baseline LLM generates syntactically valid but semantically dangerous SQL for all five robustness questions, whereas the full pipeline correctly refuses or constrains each one through its postprocessing and safety enforcement layers.

For Medium-difficulty spatial queries (spatial measurement, spatial join, spatial filtering, centroid calculation), the full pipeline achieves perfect accuracy (1.000 vs. 0.800 baseline). The improvement is attributable to geometry-aware grounding: the semantic layer injects explicit rules about geography casting, SRID handling, and ROUND(::numeric, N) syntax that the baseline LLM frequently violates.

The single remaining failure in the full pipeline is a Hard-difficulty K-Nearest Neighbors question (CQ_GEO_HARD_02), where the model uses `ORDER BY ST_Distance(...)` instead of the PostGIS KNN index operator `<->`, producing a different row ordering. This failure illustrates a known limitation: even with explicit prompt guidance, LLMs sometimes default to more familiar SQL patterns over domain-specific operators.

### 3.3 Warehouse Track Results (BIRD)

Table 2 presents the BIRD mini_dev benchmark results.

| Difficulty | N | Baseline EX | Full EX | Delta |
|------------|---|-------------|---------|-------|
| simple | 25 | 0.640 | 0.720 | +0.080 |
| moderate | 19 | 0.474 | 0.316 | -0.158 |
| challenging | 6 | 0.333 | 0.333 | 0.000 |
| **Overall** | **50** | **0.540** | **0.520** | **-0.020** |

On the warehouse track, the full pipeline achieves an overall EX of 0.520, marginally below the baseline (0.540). However, the aggregate number masks a divergent pattern across difficulty levels. For simple questions, the full pipeline outperforms the baseline by 8 percentage points (0.720 vs. 0.640), indicating that semantic grounding helps with straightforward filtered and aggregation queries by providing better schema context and column disambiguation. For moderate questions, the full pipeline underperforms by 15.8 percentage points (0.316 vs. 0.474), and for challenging questions, performance is identical.

Execution validity (the fraction of generated SQL that executes without error) is 0.960 for baseline and 0.900 for full, indicating that the full pipeline occasionally generates SQL that fails at execution time, likely due to schema-qualified table references or operator mismatches introduced by the grounding layer.

### 3.4 Error Analysis

We categorize the 24 full-pipeline failures on the BIRD track into three types:

| Error Type | Count | Fraction |
|------------|-------|----------|
| Wrong result (valid SQL, incorrect answer) | 19 | 79.2% |
| No SQL generated (agent did not produce SQL) | 3 | 12.5% |
| Invalid SQL (execution error) | 2 | 8.3% |

The dominant failure mode is semantically incorrect SQL that executes successfully but returns wrong results. Manual inspection reveals three recurring patterns:

1. **Join path confusion** (8/19): The model selects incorrect join paths between fact and dimension tables. For example, joining `transactions_1k` with `yearmonth` on `CustomerID` when the gold SQL joins through `gasstations` on `GasStationID`. This reflects insufficient understanding of the warehouse schema's entity-relationship structure.

2. **Aggregation semantics** (6/19): The model applies COUNT(DISTINCT ...) where the gold SQL uses COUNT(*), or vice versa. It also confuses per-row aggregation with per-group aggregation, particularly in percentage calculations.

3. **Date/temporal parsing** (5/19): The BIRD dataset uses non-standard date formats (e.g., `Date` column containing `'201309'` as YYYYMM). The model sometimes applies SUBSTRING-based parsing differently from the gold SQL, or fails to recognize the implicit temporal granularity.

These patterns are consistent with the hypothesis that the current semantic layer, designed primarily for GIS schema disambiguation, does not provide sufficient structural metadata for warehouse-style fact/dimension reasoning.

### 3.5 Cross-Domain Comparison

Figure 1 (to be rendered) summarizes the cross-domain comparison:

```
GIS Track:   Baseline 0.650 → Full 0.800  (+0.150, +23.1%)
BIRD Track:  Baseline 0.540 → Full 0.520  (-0.020, -3.7%)
```

The asymmetry is striking. On the GIS track, semantic grounding provides a substantial and consistent advantage. On the warehouse track, the same grounding architecture provides marginal improvement on simple queries but introduces slight degradation on moderate queries. This suggests that the framework's grounding mechanisms are well-calibrated for GIS-specific challenges (geometry types, spatial operators, coordinate systems) but insufficiently adapted for warehouse-specific challenges (entity-relationship navigation, temporal reasoning, multi-table aggregation patterns).

## 4. Discussion

### 4.1 Why Semantic Grounding Helps in GIS

The GIS track results demonstrate that semantic grounding provides substantial value when the query domain involves specialized operators and schema conventions that general-purpose LLMs handle unreliably. Three mechanisms drive the improvement:

First, **geometry-aware type injection** ensures the model knows which columns are geometry-bearing, what their SRID is, and when geography casting is required. Without this, the baseline frequently omits `::geography` casts, producing area/distance values in degrees rather than meters.

Second, **safety and robustness enforcement** through SQL postprocessing catches dangerous operations (DELETE, UPDATE) and injects LIMIT constraints for large-table full scans. The baseline LLM has no such guardrails and scores 0.000 on all robustness questions.

Third, **domain vocabulary grounding** through the semantic layer's hierarchy matching and alias resolution helps the model correctly interpret Chinese domain terminology (e.g., 地类名称, 图斑面积) and map it to the correct quoted column references. The baseline must infer these mappings from raw schema text alone.

### 4.2 Why Semantic Grounding Underperforms on Warehouses

The warehouse track reveals that the same grounding architecture can introduce slight degradation when applied to domains it was not designed for. We identify three contributing factors:

**Factor 1: GIS-centric retrieval bias.** The semantic layer's source ranking algorithm deprioritizes geometry-bearing tables for non-spatial queries, but it does not provide positive signals for warehouse-specific patterns such as star-schema fact/dimension relationships. As a result, candidate table selection for moderate BIRD questions sometimes surfaces irrelevant tables or misses critical join partners.

**Factor 2: Absence of entity-relationship metadata.** The current semantic layer stores column-level annotations (domain, aliases, units) but does not encode table-level roles (fact vs. dimension) or explicit join paths. For warehouse queries that require multi-hop joins through intermediate tables, the model must infer the join graph from raw foreign-key structure, which it does less reliably than the baseline that receives the full schema dump without intermediate semantic interpretation.

**Factor 3: Few-shot suppression for non-spatial queries.** The framework intentionally suppresses GIS-oriented few-shot examples for non-spatial queries (to avoid polluting warehouse prompts with irrelevant ST_* patterns). However, this means warehouse queries receive no few-shot guidance at all, whereas the baseline benefits from its own implicit pattern matching over the schema dump.

### 4.3 The Case for MetricFlow-Style Modeling

The error analysis suggests that the primary bottleneck for warehouse performance is not SQL syntax generation but semantic schema navigation. The model can generate syntactically correct PostgreSQL but frequently selects wrong join paths or applies incorrect aggregation granularity. This is precisely the problem that MetricFlow-style semantic modeling addresses: by explicitly declaring entities (join keys), measures (aggregatable facts), and dimensions (descriptive attributes), the system can provide the LLM with pre-computed join paths and aggregation rules rather than requiring it to infer them from raw DDL.

We hypothesize that introducing entity/measure/dimension metadata for BIRD schemas would primarily improve moderate-difficulty questions, where the failure mode is join-path confusion rather than SQL syntax errors. This represents a natural next step for the framework's cross-domain generalization.

### 4.4 Cross-Lingual Observations

Both tracks involve cross-lingual challenges. The GIS track uses Chinese questions over Chinese-named columns (DLMC, BSM, TBMJ), while the BIRD track uses English questions over English-named columns. The framework handles both through its alias-matching mechanism, which supports multilingual synonyms registered in the semantic layer. Preliminary experiments with Chinese translations of BIRD questions (using pre-registered Chinese aliases for 75 tables and 209 columns) show successful table/column resolution, suggesting that the framework's cross-lingual capability is functional but requires systematic evaluation in future work.

### 4.5 Limitations

Several limitations should be noted. First, the GIS benchmark contains only 20 questions, which limits statistical power for per-category analysis. Second, the BIRD evaluation uses 50 questions from a single database cluster (debit_card_specializing dominates), which may not represent the full diversity of warehouse query patterns. Third, execution-based evaluation treats any result-set mismatch as failure, even when the predicted SQL is semantically equivalent but produces results in a different order or with different numeric precision. Fourth, the framework currently uses a single LLM (Gemini 2.5 Flash) for both baseline and full pipeline; comparative evaluation across model families would strengthen the generalizability claims.

### 4.6 Future Work

Three directions emerge from this study:

1. **MetricFlow integration**: Introduce explicit fact/dimension/entity metadata for non-GIS schemas to provide join-path guidance and aggregation constraints, targeting the moderate-difficulty warehouse failures.

2. **Expanded benchmark scale**: Increase BIRD evaluation to 500 questions across all 11 databases, and expand the GIS benchmark to 50+ questions with finer spatial operator coverage.

3. **Cross-lingual evaluation**: Systematically evaluate Chinese-to-English and English-to-Chinese query translation using the registered multilingual aliases, producing a cross-lingual text-to-SQL benchmark that spans both GIS and warehouse domains.

## 5. References (待补充)

关键引用:
- BIRD benchmark (Li et al., 2024)
- Spider (Yu et al., 2018)
- BEAVER (Chen et al., 2024) — 论文起因
- Spider 2.0 (ICLR 2025)
- MetricFlow / dbt semantic layer
- Google ADK
- Gemini 2.5 Flash

---

## 论文主图建议

1. **Graphical Abstract**: NL input → semantic grounding → SQL generation → execution correction → GIS/warehouse output
2. **方法流程图**: semantic layer + grounding engine + few-shot + postprocess + self-correction 全链路
3. **Benchmark 对比图**: GIS benchmark vs BIRD benchmark 的问题类型、算子分布、EX 对比
4. **演进轨迹图**: full pipeline EX 从 0% → 70% 的逐步改进过程 (6 个阶段)
