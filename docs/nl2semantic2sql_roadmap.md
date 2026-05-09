# NL2Semantic2SQL 产品路线图（精简版）

**最后更新**：2026-05-09
**关联文档**：`docs/roadmap.md`（整体路线图）、`submission/nl2semantic2sql_v5/`（论文最新快照）
**前版本**：`docs/nl2semantic2sql_roadmap_v1_verbose.md.bak`（详细 v25-v27 分解，已归档）

---

## v5 投稿包已就绪（2026-05-09 完成）

IJGIS 主修订，响应两份 2026-05-08 评审报告：

- Manuscript 23 pages / 6988 words; 参考文献 570 words (total 7558, ≤7800 IJGIS 限); Abstract 181 words
- Supplement 6 pages (5 sections: BIRD details / cross-lingual per-question / **cross-model-family (S3 new)** / **DIN-SQL paired (S4 new)** / 完整复现清单)
- Cover letter 2 pages (Robustness primary / Spatial marginal / BIRD secondary / cross-lingual null / cross-family / DIN-SQL closure 六条 highlights)
- Response letter 5 pages (Part A 回应 Report 1 §2.1-§4, Part B 回应 Report 2 + priority checklist 10 项)

**最终 headline 数字**：
- Robustness 40q (primary): Full 0.975 vs baseline 0.450, paired p<10⁻⁴
- Spatial 85q majority-vote 0.659, paired p=0.052 (marginal)
- BIRD held-out 150q: +0.033 (directional, n.s.)
- Cross-lingual 50q re-audit: p=1.00 (translation artefact ruled out)
- **NEW Cross-family ablation**: Gemini 30q 0.600→0.800 p=0.0312; DeepSeek baseline parity p=1.00
- **NEW DIN-SQL paired**: BIRD 150q p=0.0755 marginal; Robustness 40q **p=7.45×10⁻⁹**

**主要技术交付**：
- `thebibliography` → natbib + abbrvnat author-date (per IJGIS Overleaf 模板)
- 22 v5 commits = 11 CODE + 11 PAPER (paper 不 push)
- 脚手架新增：30q stratified subset builder / cross-family ablation runner / BIRD DIN-SQL fast runner / CQ DIN-SQL fast runner / cross-lingual supplement LaTeX renderer
- Overfull hbox 48→2, mojibake 清零, 双盲 audit 全过

详细：见 `memory/nl2sql_v5_session_end_20260509.md`。

---

## 定位判断（决定本文档的所有内容）

经过一轮对齐讨论，NL2Semantic2SQL 当前的核心结论是：

1. **语义层 + harness engineering 的 ROI 已进入平坦区**。single-pass ablation 显示所有组件拿掉都在 ±1.6% 以内，继续加 grounding 规则只能抠出 0.5–1% 的碎片增量
2. **下一档准确率提升不在同一条路上**，只能靠底层 LLM 能力：换更强模型、用 reasoning/thinking mode、multi-sample + voting、或等下一代模型
3. **这不是产品 bug，是 LLM 应用工程的天花板**。你的角色从"算法工程师"切到"LLM 应用工程师"——工作内容变为选型、对冲、成本优化、可观测，而不是无限卷 accuracy

由此，本 roadmap 去掉"不断加规则"的工作项，只保留**三件有时间盒的事 + 一个长期习惯**。

---

## 现状快照

| 维度 | 数字 | 备注 |
|---|---|---|
| GIS Spatial 85q EX | 0.682 | Gemini 2.5 Flash，paired McNemar vs baseline *p*=0.0072 |
| Robustness 40q safe-refusal | 1.000 | 永不执行破坏性或无界查询 |
| Robustness 40q bounded-answer | 0.825 | OOM Prevention 只拿 1/8，是明确的 engineering gap |
| BIRD design 108q EX | 0.593 | *p*=0.0213（in-sample tuning） |
| BIRD held-out 150q EX | 0.507 | *p*=0.3833，不显著 |
| Production LLM | Gemini 2.5 Flash | DeepSeek V4 仅作 429 fallback，未系统评测 |
| Token cost | GIS 13.6× / BIRD 7.9× baseline | Hybrid pipeline 有望压到 ~5× |

---

## 三件事

### 事项 1：LLM 横评基础设施（Week 1，~5 天）

**目标**：把 `run_cq_eval.py` 改造成 `--model` 参数化，1 小时能跑完一组 125q + 108q 横评；4 个候选 LLM 跑出初始对比表。

**为什么做**：当前 production 用 Gemini 2.5 Flash，但其他 LLM（Gemini 2.5 Pro / DeepSeek V4-Flash / DeepSeek V4-Pro）都没有系统数字。你的 gateway 已经把它们注册好了，只差一次实际横评。

**具体工作**：

1. `run_cq_eval.py` + `run_pg_eval.py` 加 `--model <id>` 参数，贯穿到 `_lazy_init_full()` 和 baseline/DIN-SQL 的模型传参
2. 跑 4 组实验：`gemini-2.5-flash`（对齐论文基线）/ `gemini-2.5-pro` / `deepseek-v4-flash` / `deepseek-v4-pro`
3. 每组跑 GIS 125q + BIRD 108q，产出一张表
4. 把结果表归档到 `docs/llm_benchmark_2026Q2.md`（每季度更新一份）

**Definition of Done**：
- 4 个 LLM 的完整 EX 数字（Spatial / Robust-bounded / BIRD)
- 一条 production default 决策（如果 V4-Flash 能打平 Flash 价格砍 90% 就切）
- 横评表可以直接引入论文 revision 回应"单 LLM 家族"评审指控

**预估 API 成本**：1000 次 Gemini + 500 次 DeepSeek，视 quota 可能需要 2-3 天跑完。

---

### 事项 2：EXPLAIN-based OOM pre-check（✓ 已于 v4 完成 2026-05-08）

**状态**：已完成并发表于 `submission/nl2semantic2sql_v4/`。

**实际结果**：
- Robustness OOM Prevention bounded-answer：1/8 → 7/8（超过 DoD 的 6/8 目标）
- 40q Robustness full: 0.975 vs baseline 0.450，paired p<1e-4
- 125q 整体 EX 回归 < 2%（safe-refusal 仍 1.000）

**产品沉淀**：
- `data_agent/sql_postprocessor.py::explain_row_estimate()` — EXPLAIN 驱动的行数估计
- Agent prompt 新增 bounded-output 策略：对 SELECT 大表 注入 LIMIT 而非拒答
- 6 个 NL2SQL_DISABLE_* env flag 支持细粒度 ablation 和回归测试

---

### 事项 3：Hybrid pipeline + tier-based harness 配置（Week 4–6，~10 天）

**目标**：把 GIS token cost 从 13.6× 降到 ~5×，支持按 LLM tier 动态选择 harness 强度。

**为什么做**：

- Token cost 是产品规模化的硬约束（客户跑 1000 次 query 就几十美元）
- 不同 LLM 该配不同 harness：Flash 需要全套；V4-Pro 可能只需半套；未来 Gemini 3.0 Thinking 可能基本不需要
- 这是从"算法工程师"切到"LLM 应用工程师"的具体体现

**具体工作**：

1. 引入 `pipeline_runner.py` 的 `mode="hybrid"`：grounding 走 single-pass（省 tokens）、execution + self-correction 走 agent-loop（精准）
2. 在 `model_gateway.py` 的 model 注册表加 `recommended_harness` 字段：
   ```python
   "gemini-2.5-flash": {"recommended_harness": "full"},
   "gemini-2.5-pro":   {"recommended_harness": "hybrid"},
   "deepseek-v4-pro":  {"recommended_harness": "hybrid"},
   "future-reasoning": {"recommended_harness": "light"},  # 预留
   ```
3. 三档 harness 配置：`full` / `hybrid` / `light`，对应不同的 intent 标签数、self-correction T 值、few-shot K 值
4. 跑 125q × 3 harness × 2 模型 = 6 组对比，形成 cost-accuracy Pareto 曲线

**Definition of Done**：
- Hybrid 模式在 GIS 125q 上 EX ≥ 0.65 且 token cost ≤ 6×
- `model_gateway.py` 的 model 注册表里每个 LLM 都挂了推荐 harness
- Production 能一键切换 harness 模式

---

## 一个长期习惯

### 每季度 LLM 横评

**做什么**：每季度（3/6/9/12 月）重新跑事项 1 的横评，加入新发布的 LLM，更新 production default。

**为什么做**：

- 大模型每 3-6 个月出一代（Gemini 2.5 → 3.0、DeepSeek V4 → V5、Claude Sonnet → Opus 新版）
- 你的 125q benchmark 就是持续体检工具，跑一遍成本不高
- 避免"用 1 年前的 LLM 默认值"浪费用户体验

**归档格式**：每季度一个 `docs/llm_benchmark_YYYYQN.md`，固定 5 列：

```
| Model | GIS Spatial 85q EX | Robust bounded 40q | BIRD held-out 150q | Mean tokens/q | 生效日期 |
```

连续 4 个季度的数据就能画出"LLM 能力 vs 时间"的趋势线，这是比任何论文都有产品价值的数据。

---

## 有意识地不做的事情

**明确排除这些方向**，避免时间浪费：

| 方向 | 为什么不做 |
|---|---|
| 继续手动加 grounding 规则 | ROI 在平坦区，单规则只能抠出 0.5-1%，不值得 |
| 微调本地 SFT/LoRA 模型 | 数据量不足（400 对远未到 5000+），V4-Pro 已经做到这个水平，微调 7B 很难打赢 |
| 追 Spider 2.0 / BEAVER 榜单 | 这些 benchmark 不测 PostGIS，对 GIS 产品价值低 |
| ~~Agent-loop-native ablation~~ | ✓ v4 已交付（§4.6 Table 4, 6-config, agent-loop-native）|
| ~~40q Robustness 配对 baseline / DIN-SQL 重跑~~ | ✓ v4 baseline 部分已交付（full 0.975 vs baseline 0.450, p<1e-4）；DIN-SQL paired 留 first-revision |
| ~~Schema-only + self-correction 中间 baseline~~ | ✓ v4 已交付（§4.5, schema-only+pp+retry 0.565）|
| ~~EXPLAIN-based OOM pre-check~~ | ✓ v4 已交付（OOM 1/8 → 7/8, `data_agent/sql_postprocessor.py::explain_row_estimate`）|
| ~~G=(V,E) 语义层形式化~~ | ✓ v4 已交付（§3.1 Algorithm 1 + `data_agent/semantic_graph.py`）|

---

## 论文与产品的反哺关系

IJGIS revision 窗口是 2–6 个月。在这个窗口里，三件事做完会有以下 paper 层面的顺带收益：

| 事项 | 对论文 revision 的顺带价值 |
|---|---|
| 事项 1（LLM 横评） | 直接回应评审"单 LLM 家族"问题，Limitations 可以换成"已在 4 个 LLM 上验证" |
| 事项 2（EXPLAIN fix） | Discussion §5.1 的 "bounded-answer 1/8 是 engineering gap" 可以替换为"我们实现了 EXPLAIN pre-check，结果 X/8"，把 null 变 positive |
| 事项 3（Hybrid + tier） | Discussion 可以加 "domain-selective grounding in production"段，cost-benefit 讨论落到实处 |

**但不要为了论文做产品**。优先级永远是产品，论文是顺手。

---

## 论文的真正护城河（写作时强化）

如果一年后 Gemini 3.0 baseline 直接做到 0.75，v3 论文的 0.682 vs 0.529 就过时了。但以下三样不会过时：

1. **125q Chongqing PostGIS benchmark + 公开 gold SQL** — 数据集本身有引用价值
2. **Robustness 双指标（safe-refusal vs bounded-answer）框架** — 方法论贡献
3. **bilingual intent-conditioned grounding + tier-based harness 架构** — 工程模式

下次论文修订或新 paper 写作时，有意识往这三点聚焦，不要只盯住 EX 数字。

---

## 节奏建议：冻结期

三件事做完后（约 3 周），给自己一个**2 个月冻结期**：

- 不再改 grounding rules
- 不跑新评测实验
- 只做两件事：（i）观察线上表现 / 收集 feedback；（ii）等新 LLM 发布触发下一季度横评

这个节奏对小团队产品是**可持续且健康**的。"一直在路上"的焦虑来自没有终点感，而有明确冻结期就是给自己设一个终点——做到 DoD 就停手。

---

*本 roadmap 的核心判断是：NL2SQL 已经是 maintained 状态，不是 under construction 状态。维护工作是日常的，不是未完成的焦虑。*
