# TWM 渲染器、模拟器、规划器的技术核心与创新边界

更新日期：2026-06-20

本文档整理 Territory World Model, TWM 在李飞飞 world model 功能分类中
renderer、simulator、planner 三类能力的技术实现核心，以及当前可以较稳妥主张
的创新突破边界。

需要严格区分的是：不能把“渲染器、模拟器、规划器”三个单点都说成世界首创。
GIS 渲染、土地利用模拟、城市数字孪生、MPC/规划优化都已经有大量已有工作。
TWM 真正有机会构成“之前没人系统做过”的突破，是把三者组织成一个面向国土
空间治理的 evidence-gated geospatial world model，尤其是 simulator 这一层。

## 1. Renderer：GIS-operational renderer

### 技术实现核心

TWM 的 renderer 不是照片级渲染器，也不是生成影像或 3D 场景。它的核心是把
国土空间世界状态渲染成 GIS 治理可观察、可复核、可审计的业务 observation。

核心能力包括：

- 把国土空间世界状态表示成结构化对象：
  `parcel / block / township / county / project / rule / evidence / review_task`
- 把对象关系表示成 GIS relation graph：
  重叠、邻接、包含、项目-地块关系、规则命中关系、审查任务关系。
- 把规则、证据、审计状态渲染成可观察业务状态：
  风险清单、规则命中、证据链、人工复核状态、审计报告。
- 把世界状态转换为 simulator 和 planner 可消费的结构化 observation。

### 创新判断

单独看，GIS 图层渲染、知识图谱、规则引擎、审计报告都不是世界首创。

TWM renderer 的新意在于：renderer 不再只是前端展示层，而是 world model loop
里的 observation generator，把对象、关系、规则、证据、复核状态统一成后续
simulator/planner 可消费的世界状态。

较稳妥的创新表述是：

> TWM 提出面向国土空间治理的对象-关系-规则-证据状态渲染器，使 GIS 业务状态
> 成为 world-model loop 中可计算、可追溯、可审计的 observation。

但 renderer 不是 TWM 最强的“世界首创”点。

## 2. Simulator：TWM 的核心

### 技术实现核心

TWM simulator 是 TWM 的核心。它要预测的不是单纯下一帧影像或单一适宜性分数，
而是行动和情景条件下的国土空间状态变化：

```text
p(
  future_state,
  constraint_risk,
  planning_utility_delta,
  uncertainty
  | current_hierarchical_gis_state, action, scenario, evidence
)
```

具体技术核心包括：

- 层级 GIS state encoder：
  parcel/block/township/county 多尺度 token，不把县域状态压成 flat vector。
- action-conditioned dynamics：
  给定规划行动、审批行动、保护行动、建设行动后，预测未来状态变化。
- multi-head output：
  未来状态、约束违背概率、效用变化、不确定性、校准因子。
- causal calibration：
  用观测审批/审查历史、treated/control、空间邻接、covariate balance 校准行动效应。
- spatial causal estimator：
  混合空间单元 fixed effect、treated/control neighbor matching、空间干扰诊断。
- evidence gate：
  synthetic/not-for-production、covariate balance、spatial interference、
  spatial estimator 等不过关时，结论只能是 `review`，不能升级为生产 claim。

### 创新判断

土地利用模拟已经有很多传统模型，例如 CLUE/CLUE-S、CA-Markov、SLEUTH、FLUS、
PLUS 等；城市仿真、UrbanSim、城市数字孪生和遥感 world model 也都有相邻工作。
因此 TWM 不能声称“第一次做地理空间模拟”。

TWM 可以较强地主张的是：

> 第一次把层级 GIS 对象-关系-规则-证据状态、action-conditioned territorial
> dynamics、多头规划输出、空间因果校准、证据门控、planner 消费闭环整合成
> 国土空间治理 world model。

三层能力中，simulator 是最接近“实质性突破”的部分。

一句话概括：

> TWM 的核心创新不是会预测，而是预测必须被 action、规则、空间因果、证据 gate
> 共同约束。

## 3. Planner：planner consumer

### 技术实现核心

TWM planner 不定义 TWM 本体，而是消费 simulator 输出。它的技术核心是把
simulator 给出的未来状态、约束风险、效用变化和不确定性，用于规划方案搜索、
排序和审计。

核心能力包括：

- beam search / constrained rollout / MPC-style candidate search。
- 输入 simulator 输出：
  future state、constraint risk、utility delta、uncertainty。
- 在合法动作空间中搜索方案：
  不能违反耕地保护、生态红线、开发边界、审批规则等硬约束。
- 输出候选方案、排序、风险解释、审计材料和复核任务。
- planner 不能绕过 simulator/evidence gate，方案收益必须来自经过校准的世界模型输出。

### 创新判断

MPC、beam search、约束优化、多目标规划都不是世界首创。

TWM planner 的新意在于：

- planner 是 evidence-gated GIS planning consumer；
- planner 的方案收益不能只靠优化分数，而必须由 simulator、causal calibration
  和 evidence gate 共同限定；
- planner 输出不仅是最优方案，还包括风险、证据、复核和审计状态。

较稳妥的创新表述是：

> TWM 将规划器定义为 evidence-gated consumer，使国土空间方案搜索受行动条件
> 模拟器、因果校准和 GIS 证据边界共同约束。

但 planner 本身不是 TWM 最强创新点。

## 4. 创新强弱排序

当前最稳妥的创新强弱排序如下：

1. 最强：Simulator  
   层级 GIS 状态 + action-conditioned dynamics + spatial causal calibration +
   evidence gate。

2. 中等：Renderer  
   把 GIS 业务状态变成 world-model observation，而不是普通图层展示。

3. 较弱但必要：Planner  
   planner 作为 evidence-gated consumer，而不是把 MPC/beam search 包装成世界模型。

## 5. 不建议使用的表述

不建议说：

> TWM 是世界上第一个地理空间模拟模型。

这个说法不稳，因为土地利用模拟、城市仿真、空间规划优化、数字孪生和遥感预测
都有大量已有工作。

也不建议说：

> TWM 的 planner 是世界模型本体。

planner 是 TWM simulator 的 consumer，不是 TWM 的核心定义。

也不建议说：

> GeoFM 是 TWM 的核心突破。

GeoFM 只能是 gated enhancement。没有 downstream planning lift 和证据 gate，
GeoFM 不应成为默认主干。

## 6. 推荐的创新表述

较稳妥、也更有技术含量的表述是：

> TWM 提出一种面向国土空间治理的 geospatial world model，把层级 GIS
> 对象-关系-规则-证据状态、行动条件动力学、空间因果校准、证据门控和规划
> 消费闭环统一到同一个可审计框架中。相较于传统土地利用模拟、遥感预测、
> 城市数字孪生和 GIS 优化工具，TWM 的核心突破是让规划 claim 必须经过
> action-conditioned simulator 与 causal/evidence gate 才能升级。

英文论文式表述可以写成：

> We introduce a governance-oriented geospatial world model for territorial
> planning. TWM represents land systems as hierarchical GIS object-relation-rule-
> evidence states, learns action-conditioned multi-head dynamics for future state,
> constraint risk, planning utility and uncertainty, and upgrades planning claims
> only through spatial causal calibration and evidence-gated validation.

## 7. 当前工程含义

按当前工程进度，TWM 已经具备 renderer-simulator-planner 原型闭环：

- renderer 层：对象、关系、规则、证据、复核、审计状态已经形成结构化状态。
- simulator 层：action-conditioned forecast、counterfactual rollout、causal calibration、
  spatial estimator、evidence gate 已经形成验证链路。
- planner 层：beam planning、counterfactual rollout、ArcGIS/MPC consumer 方向已经明确。

但当前仍不能升级为生产级 world-model claim，原因是本地验证数据仍然是
`synthetic=True` 和 `not_for_production=True`，且 evidence-augmented matching 后
仍存在 covariate balance、spatial interference 和 spatial estimator 缺口。

因此，当前最准确的状态是：

> TWM 已经从概念进入可运行的原型和数据验证阶段；其核心 simulator 路线已经成型，
> 但生产级创新主张还需要非合成 treated/control 审批审查历史、真实空间邻接、
> 跨区域验证和更强的 causal/evidence gate 通过结果来支撑。
