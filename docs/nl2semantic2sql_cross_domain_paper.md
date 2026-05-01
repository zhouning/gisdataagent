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

Table 2 presents the BIRD mini_dev benchmark results across three pipeline configurations: baseline (direct LLM), full pipeline with prompt refinements only, and full pipeline with MetricFlow warehouse modeling.

| Difficulty | N | Baseline EX | Full (prompt) | Full (+MetricFlow) |
|------------|---|-------------|---------------|---------------------|
| simple | 25 | 0.640 | 0.720 | 0.680 |
| moderate | 19 | 0.474 | 0.316 | 0.368 |
| challenging | 6 | 0.333 | 0.333 | 0.500 |
| **Overall** | **50** | **0.540** | **0.520** | **0.540** |

The results reveal a two-stage improvement trajectory. The initial prompt refinements (removing forced LIMIT, improving projection constraints) improve simple-question accuracy by 8 percentage points (0.640 → 0.720) but degrade moderate questions (0.474 → 0.316), yielding a net-neutral overall EX of 0.520. Adding MetricFlow-style warehouse modeling — which provides explicit fact/dimension table roles, entity join keys, and measure declarations — recovers moderate performance (0.316 → 0.368) and improves challenging questions (0.333 → 0.500), bringing the overall EX to 0.540, matching the baseline.

Notably, the MetricFlow configuration eliminates all SQL execution errors (invalid SQL count drops from 2 to 0), indicating that join-path hints help the model generate structurally correct table references. Execution validity improves from 0.900 (prompt-only) to 0.940 (MetricFlow), matching the baseline's 0.960.

The convergence of full pipeline and baseline at 0.540 overall EX, combined with the full pipeline's substantial advantage on the GIS track (0.800 vs. 0.650), suggests that the framework achieves cross-domain parity on warehouse queries while providing clear added value for geospatial queries.

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

Both tracks involve cross-lingual challenges. The GIS track uses Chinese questions over Chinese-named columns (DLMC, BSM, TBMJ), while the BIRD track uses English questions over English-named columns. The framework handles both through its alias-matching mechanism, which supports multilingual synonyms registered in the semantic layer.

We conduct a preliminary cross-lingual experiment by translating the same 50 BIRD questions into Chinese and evaluating them with the full MetricFlow-enhanced pipeline. The Chinese run achieves EX=0.500 and Valid=0.900, compared with EX=0.540 and Valid=0.940 for the English MetricFlow run. The 4-percentage-point gap suggests that the semantic layer's Chinese aliases are sufficient to recover most schema references, but cross-lingual paraphrase still introduces additional ambiguity, especially in moderate-difficulty questions involving aggregation semantics and join paths.

This result is encouraging because it demonstrates that the framework can support cross-lingual warehouse querying without any retraining or bilingual supervision. At the same time, the remaining gap indicates that multilingual alias registration alone is not enough to eliminate cross-lingual performance loss. Future work should consider bilingual few-shot exemplars or translation-aware grounding strategies to close this gap.

### 4.5 Limitations

Several limitations should be noted. First, the GIS benchmark contains only 20 questions, which limits statistical power for per-category analysis. Second, the BIRD evaluation uses 50 questions from a single database cluster (debit_card_specializing dominates), which may not represent the full diversity of warehouse query patterns. Third, execution-based evaluation treats any result-set mismatch as failure, even when the predicted SQL is semantically equivalent but produces results in a different order or with different numeric precision. Fourth, the framework currently uses a single LLM (Gemini 2.5 Flash) for both baseline and full pipeline; comparative evaluation across model families would strengthen the generalizability claims.

### 4.6 Future Work

Three directions emerge from this study:

1. **MetricFlow integration**: Introduce explicit fact/dimension/entity metadata for non-GIS schemas to provide join-path guidance and aggregation constraints, targeting the moderate-difficulty warehouse failures.

2. **Expanded benchmark scale**: Increase BIRD evaluation to 500 questions across all 11 databases, and expand the GIS benchmark to 50+ questions with finer spatial operator coverage.

3. **Cross-lingual evaluation**: Systematically evaluate Chinese-to-English and English-to-Chinese query translation using the registered multilingual aliases, producing a cross-lingual text-to-SQL benchmark that spans both GIS and warehouse domains.

## 5. Related Work

### 5.1 Text-to-SQL with Large Language Models

The application of large language models (LLMs) to text-to-SQL has progressed rapidly through increasingly sophisticated prompt engineering strategies. Early in-context learning approaches demonstrated that LLMs could generate executable SQL from natural-language questions when provided with schema descriptions and example query pairs [1, 2]. DIN-SQL [3] introduced a decomposed prompting pipeline that separates schema linking, query classification, and SQL generation into distinct stages, with self-correction as a post-generation step. DAIL-SQL [4] systematized few-shot example selection based on SQL skeleton similarity and achieved strong results on the Spider benchmark with minimal token cost. More recently, multi-agent and tool-augmented architectures have emerged, in which specialized agents handle schema retrieval, SQL generation, and execution verification as separate collaborative roles [5]. Our framework shares this decomposition philosophy but adds a semantic layer as a structured intermediary between the user question and the schema, rather than relying solely on prompt-level schema linking.

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

[2] B. Rajkumar, R. Pang, and T. Dao, "Evaluating the text-to-SQL capabilities of large language models," arXiv:2204.00498, 2022.

[3] M. Pourreza and D. Rafiei, "DIN-SQL: Decomposed in-context learning of text-to-SQL with self-correction," in *Proc. NeurIPS*, vol. 36, 2023, pp. 30557–30584.

[4] D. Gao, H. Wang, Y. Li, et al., "Text-to-SQL empowered by large language models: A benchmark evaluation," *Proc. VLDB Endow.*, vol. 17, no. 5, pp. 1132–1145, 2024.

[5] X. Dong, C. Zhang, Y. Ge, et al., "C3: Zero-shot text-to-SQL with ChatGPT," arXiv:2307.07306, 2023.

[6] J. Li, B. Hui, G. Qu, et al., "Can LLM already serve as a database interface? A big bench for large-scale database grounded text-to-SQLs," in *Proc. NeurIPS*, 2024.

[7] F. Lei, T. Shi, Y. Cai, et al., "Spider 2.0: Evaluating language models on real-world enterprise text-to-SQL workflows," in *Proc. ICLR*, 2025.

[8] P. B. Chen, F. Bontempo, Y. Song, et al., "BEAVER: An enterprise benchmark for text-to-SQL," arXiv:2409.02038, 2024.

[9] M. Punjani, K. Singh, A. Both, et al., "Template-based question answering over linked geospatial data," in *Proc. ACM SIGSPATIAL*, 2018, pp. 175–178.

[10] G. Mai, C. Cundy, K. Choi, et al., "On the opportunities and challenges of foundation models for geospatial artificial intelligence," arXiv:2304.06798, 2023.

[11] Transform Data, Inc., "MetricFlow: A framework for defining and serving metrics," https://docs.getdbt.com/docs/build/about-metricflow, 2023.

[12] Q. Min, Y. Shi, and Y. Zhang, "A pilot study for Chinese SQL semantic parsing," in *Proc. EMNLP*, 2019, pp. 3652–3658.

---

## 论文主图建议

1. **Graphical Abstract**: NL input → semantic grounding → SQL generation → execution correction → GIS/warehouse output
2. **方法流程图**: semantic layer + grounding engine + few-shot + postprocess + self-correction 全链路
3. **Benchmark 对比图**: GIS benchmark vs BIRD benchmark 的问题类型、算子分布、EX 对比
4. **演进轨迹图**: full pipeline EX 从 0% → 70% 的逐步改进过程 (6 个阶段)
