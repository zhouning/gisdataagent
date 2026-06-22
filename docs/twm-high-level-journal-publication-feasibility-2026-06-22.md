# TWM 高水平期刊发表可能性评估

更新日期：2026-06-22

## 1. 总体判断

TWM 有发表高水平期刊论文的潜力，但不能按“系统工程堆栈介绍”去投高水平期刊。当前 TWM 更像一个有潜力的研究原型，距离高水平论文还差几个关键条件：

1. 真问题：必须证明目标业务场景存在未被充分解决的国土治理问题。
2. 真数据：必须使用真实或脱敏的审批、复核、变更、监管历史。
3. 强基线：必须与 manual GIS overlay、rule-only engine、土地利用模拟、优化排序等同案比较。
4. 可证伪实验：必须明确 TWM 在什么指标上优于简单方法，什么结果会推翻 TWM 的主张。

因此，TWM 不是不能投高水平期刊，而是不能靠“world model + GIS + Transformer + GeoFM + SCCA”的技术堆叠去投。它必须证明自己解决了一个真实、重要、尚未被很好解决的国土空间治理问题。

## 2. 最有希望的论文定位

最有希望的论文定位不是：

> 我们做了一个 GIS world model 平台。

而应该是：

> 面向国土空间治理的 evidence-gated geospatial world model：将对象-关系-规则-证据状态、动作条件化多头动态、空间因果校准和规划消费者闭环统一起来，用于可审计的规划审查与方案推演。

这个定位落在以下交叉方向：

1. GIScience。
2. Land-use planning。
3. Spatial decision support。
4. AI for geospatial governance。
5. Evidence-aware planning support systems。

## 3. 当前不能直接冲高水平的原因

当前最大短板不是代码量，而是证据等级。

主要问题包括：

1. 现有测试数据很多是 `synthetic` 或 `not-for-production`。
2. TWM 的真实未满足业务需求还需要通过访谈、案例和基线对比证明。
3. 动作条件化 dynamics 当前更多是 scaffold/candidate，还没有真实历史上的预测或决策提升证据。
4. 与 FLUS、PLUS、CLUE-S、rule-only GIS engine、manual overlay、optimization-only ranking 的同案对比还不够。
5. 当前很多 TWM evidence gate 返回 `blocked`，这是诚实的工程结果，但也说明目前不能主张 production-ready world model。

所以，如果现在立即写论文，比较稳妥的形态是：

> Conceptual framework + engineering prototype + synthetic/structural validation。

这种论文可以作为技术报告、workshop、arXiv-style manuscript 或中等强度期刊的基础，但要冲高水平期刊还不够。

## 4. 高水平论文需要补的关键数据

要冲高水平期刊，最关键的是拿到真实或脱敏历史数据。最低数据要求包括：

1. `state_t`：项目、地块、管控边界、规划分区、证据、规则命中。
2. `action_t`：审查、保护、调整、整治、审批、退回、补正等治理动作。
3. `state_{t+1}` 或结果：审批结果、复核结果、后续监管结果、变更结果。
4. 人工审查记录：人工判定、复核意见、补正要求、最终处置。
5. 同案 baseline 输出：人工叠加、规则引擎、土地利用模拟、优化排序等方法在同一批 case 上的结果。

没有这些数据，TWM 可以作为工程原型成立，但很难证明它解决了真实领域问题。

## 5. 必须做的基线对比

建议至少做四类同案比较：

1. TWM vs manual GIS overlay checklist。
2. TWM vs rule-only spatial compliance engine。
3. TWM vs FLUS / PLUS / CLUE-S 或类似土地利用模拟方法。
4. TWM vs optimization-only candidate ranking。

这些比较必须使用同一批项目、地块、候选方案或审查 case，不能只比较聚合指标。否则无法证明 TWM 真正优于更简单、更成熟的方法。

## 6. 推荐实验指标

不要只报 accuracy。TWM 的论文指标应该围绕国土治理业务价值设计：

1. Hard-constraint conflict recall。
2. Missed blocking conflict rate。
3. Unsupported recommendation rate。
4. Evidence link completeness。
5. Audit trail completeness。
6. Review task precision。
7. Candidate rejection reason coverage。
8. Legal-feasible top-k precision。
9. Planner regret / plan-option triage regret。
10. Uncertainty calibration。
11. Human reviewer agreement。

这些指标比单纯的预测精度更能体现 TWM 的价值，因为 TWM 的核心不是“生成更像的地图”，而是“把状态、动作、规则、证据、因果边界和规划选择放进一个可审计闭环”。

## 7. 可能形成的论文贡献点

如果补齐真实数据和实验，TWM 的贡献可以写成以下几类。

### 7.1 状态表示贡献

提出 hierarchical GIS object-relation-rule-evidence state，将 parcel、project、planning zone、control boundary、rule hit、evidence item、review task 等治理对象放入统一状态表示。

### 7.2 动作条件化动态贡献

提出 action-conditioned multi-head territorial dynamics contract：

```text
state_t + governance_action_t + scenario/evidence_context
  -> future territorial state
  -> constraint risk
  -> planning utility
  -> uncertainty
  -> action mask / evidence gate
```

### 7.3 证据门控贡献

提出 evidence-gated claim ladder，防止模型在证据不足时越权给出审批、规划或因果结论。

### 7.4 因果与规划闭环贡献

将 spatial causal calibration、policy constraints、planner consumption 和 human review 纳入统一闭环。

### 7.5 实证贡献

在真实国土审查或规划场景上证明 TWM 比 rule-only、manual overlay、land-use simulator 或 optimization-only ranking 更可审计、更少漏检或更能解释候选方案不可行原因。

## 8. 适合的投稿方向

如果补齐真实数据和实验，可以考虑以下方向：

1. GIScience / IJGIS 方向：强调 geospatial representation、spatial reasoning、GIS decision support。
2. Computers, Environment and Urban Systems：强调城市/国土空间系统建模与决策支持。
3. Environmental Modelling & Software：强调可审计建模、模拟系统、软件与方法。
4. Landscape and Urban Planning：强调规划审查、方案比选、政策约束和实际规划价值。
5. Applied Geography / Land Use Policy：强调国土治理、土地利用政策、审查决策支持。

如果只保留当前原型和合成数据，建议先做 technical report、workshop paper 或预印本，而不是直接冲高水平正刊。

## 9. 现实推进路线

建议按以下路线推进：

1. 先写一版内部 technical report 或 arXiv-style manuscript。
2. 用论文草稿反推还缺哪些真实数据、访谈证据和 baseline。
3. 获取真实或脱敏审批审查数据。
4. 做同案 baseline export validation。
5. 做 baseline comparison 和 holdout validation。
6. 明确 predictive claim 与 causal/counterfactual claim 的边界。
7. 引入人工复核结果，形成 human-in-the-loop validation。
8. 再决定投哪一类期刊。

## 10. 一句话结论

TWM 有发表高水平期刊的潜力，但前提不是继续堆更多模型组件，而是证明一个真实国土治理问题以前确实没有被很好解决，并用真实或脱敏历史数据证明 TWM 的 evidence-gated action-conditioned simulator 比更简单的 GIS 规则、人工叠加、土地利用模拟或优化方法带来可审计的实质提升。

