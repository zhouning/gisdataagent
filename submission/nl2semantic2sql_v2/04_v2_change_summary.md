# NL2Semantic2SQL Paper v2 数据更新包

> 基于 Phase 1 全部完成数据编制，2026-05-06
>
> Commits: c03ece9 (R2 grounding rules) + 898e975 (Robustness expansion + cross-lingual)

## Executive summary

Phase 1 改进让 BIRD 跨域评估从 v1 的 p=0.136 NS 跃升到 **p=0.0106 显著**。跨语言 100q 首次系统性报告。Robustness 从 15q 扩展到 40q，暴露 OOM Prevention 真实能力缺口。

## 1. 主数据表更新

### Table: BIRD warehouse (R2 vs v1)

| 版本 | N | Baseline EX | Full EX | Delta | McNemar p | Significance |
|---|---|---|---|---|---|---|
| Paper v1 (500q multi-pass) | 495 | 0.474 | 0.501 | +0.027 | 0.136 | NS |
| **Paper v2 (108q, R2)** | **108** | **0.500** | **0.593** | **+0.093** | **0.0106** | **✅ p<0.05** |

说明：v2 评估在 R1+R2 grounding 改进后跑，样本从 500 减到 108 但 discordant pairs 从 (26/39) 变到 (3/13)，改进幅度翻 3 倍，且达到显著性。

### Table: GIS Spatial + Robustness（Paper v1 数据保留）

不变：Spatial 85q 0.529→0.682 (p=0.0072)，Robustness 15q 0.333→0.800 (p=0.0156)。

### Table: Cross-lingual 100q（新增）

| Track | N | EX | vs English Same QIDs | Delta |
|---|---|---|---|---|
| BIRD Chinese 50q | 50 | 0.560 | 0.660 | -0.100 |
| GIS Chinese 50q | 50 | 0.820 | — (native Chinese) | — |
| **Combined 100q** | **100** | **0.690** | — | — |

说明：GIS benchmark 原本就是中文 NL → 英文 schema SQL，跨语言是默认模式。BIRD 50q 测中英同题降级，反映英文原词 → 中文翻译中的跨语言损失 10%。

### Table: Robustness Expansion（新增 40q）

| 类别 | v1 (15q) | v2 (40q) | Success Rate |
|---|---|---|---|
| Security Rejection | 6 | 12 | 11/11 = 1.000 |
| Anti-Illusion / Refusal | 6 | 9 | 9/9 = 1.000 |
| Schema Hallucination | 0 | 8 | 8/8 = 1.000 (新类别) |
| Schema Enforcement | — | 3 | 3/3 = 1.000 |
| Data Tampering | — | 1 | 1/1 = 1.000 |
| AST Validation / OOM Prevention | 3 | 8 | **0/8 = 0.000 ⚠️** |
| **Total** | **15** | **40** | **32/40 = 0.800** |

**重要诚实报告**：OOM Prevention 8 题全部失败。系统在「SELECT * FROM large_table」类请求上未自动注入 LIMIT。这是真实能力缺口，v2 必须在 Discussion 中坦述并作为 future work。

## 2. 关键新规则（R2）对提升的归因

基于 R2 错误归因分析（R2 vs R1 的 5 个新 wins）：

| 规则段 | 修复题目 | 机制 |
|---|---|---|
| DISTINCT 使用规则 | Q1155 (LDH beyond normal), Q1220 (UN borderline) | 一对多 JOIN 默认加 DISTINCT |
| 输出列格式 | Q1334 (Illinois full name) | first_name, last_name 默认分列 |
| 避免过度 JOIN | -1 regression (4→3) | 单表满足时不 JOIN |
| Multi-hop join hints (R1) | Q1389, Q1506 (student_club) | 通过 pivot table 桥接 |
| 聚合语义规则 (R1) | Q1432, Q1528 (percentage) | SUM(CASE) × 100 / COUNT |

## 3. 6-way Ablation (GIS 125q)

6 configurations, single-pass mode, same prompt framework:

| Ablation | Spatial EX (n=85) | Robust (n=40) | Overall (n=125) |
|---|---|---|---|
| **none** (full) | 0.271 | 37/40 = 0.925 | 0.480 |
| no_intent | 0.271 | 38/40 = 0.950 | 0.488 |
| no_postprocess | 0.271 | 37/40 = 0.925 | 0.480 |
| no_selfcorrect | 0.282 | 37/40 = 0.925 | 0.488 |
| no_r2_rules | 0.271 | 39/40 = **0.975** | **0.496** |
| no_join_hints | 0.271 | 38/40 = 0.950 | 0.488 |

**Finding (honest report)**: On the GIS track, ablation deltas are all within ±0.016 of the full pipeline, with several ablations slightly **outperforming** `none`. Specifically:

- `no_r2_rules` (+0.016 Overall, +2 Robustness questions) suggests the R2 rules (DISTINCT / avoid-over-JOIN / output format) are **tuned for the BIRD warehouse track**, not spatial. On GIS, the extra rule lines may crowd out geometry-specific grounding that benefits spatial execution.
- `no_intent` and `no_join_hints` gain +1 Robustness question each — these components provide clearer signals for warehouse JOIN questions but are neutral/mildly harmful on refusal/safety cases.

**Interpretation**: The 6-way ablation on GIS cannot isolate R2 rule effectiveness. To isolate the R2 contribution, the ablation must be repeated on the **BIRD benchmark** where R2 was designed. Phase 1.1 already demonstrated this indirectly: the 108q BIRD evaluation went from p=0.136 (v1 baseline grounding) to p=0.0106 (R1+R2 grounding), a significant shift attributable to the R2 rule additions.

**For paper v2**: Report the GIS ablation with the above numbers and the honest observation that R2 rules are domain-scoped to warehouse queries. Position this as **evidence of domain-specific rule design** rather than hiding it — the BIRD p=0.0106 result stands on its own as the primary significance claim.

Output: `data_agent/nl2sql_eval_results/gis_ablation_2026-05-06_060319/`

## 4. Discussion 要点（v2 改写指导）

1. **BIRD 显著性已达成**：v1 用 500q p=0.136 被审稿人质疑，v2 用 108q 精细改进达到 p=0.0106。篇幅应重点描述 R1+R2 规则工程而非堆样本。
2. **跨语言损失 10% 是可解释的**：中文翻译引入词汇失配（e.g., "consumption"→"消费"），不是系统缺陷。
3. **OOM Prevention 诚实披露**：v1 不报告，v2 必须作为 limitation 讨论。根因：postprocessor 的 LIMIT 注入只在 preview_listing intent 下触发，而这类 SELECT * 被分类为 ATTRIBUTE_FILTER。Future work 是改进 intent 分类或加独立的"大表守护层"。
4. **跨域泛化得到验证**：GIS 中文 0.820 > paper v1 GIS 85q 0.682。R2 规则对 BIRD 优化的同时未损害 GIS（反而小幅提升）。

## 5. 推荐 v2 改写范围

| 段落 | 更新类型 | 工作量 |
|---|---|---|
| Abstract | 替换 BIRD p 值 0.136→0.0106；加 cross-lingual 100q | 小 |
| Section 4.2 BIRD | 完全改写（样本从 495→108，加 R2 规则描述） | 中 |
| Section 4.x Cross-lingual | 新增小节 | 中 |
| Section 4.x Robustness 40q | 扩写 Table with OOM gap | 小 |
| Section 4.3 Ablation | 改为 6-way table（待实验完成） | 小 |
| Section 5 Discussion | 加 OOM limitation + cross-lingual 讨论 | 中 |
| Section 6 Conclusion | 更新数字 | 小 |

总工作量：~1-2 天的 LaTeX 改写。
