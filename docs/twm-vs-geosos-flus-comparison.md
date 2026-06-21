# TWM 与 GeoSOS/FLUS 的比较分析

更新日期：2026-06-20

本文比较 GIS Data Agent 项目中的 Territory World Model, TWM 与 GeoSOS/FLUS 传统土地利用模拟与优化路线。这里的“以前的算法”特指 GeoSOS 官网所述 Geographical Simulation and Optimization System 及其 FLUS, Future Land Use Simulation 模型，主要参考：

- `http://www.geosimulation.cn/index.html`
- `http://www.geosimulation.cn/FLUS.html`
- `http://www.geosimulation.cn/Publications.html`
- `/Users/zhouning/Downloads/2017LUP-FLUS.pdf`
- `/Users/zhouning/Downloads/A Geographical Simulation and Optimization System Based on Coupling Strategies.pdf`
- GIS Data Agent 本地 TWM 文档与代码。

## 1. 核心结论

GeoSOS/FLUS 是土地利用变化模拟与空间优化的经典路线，核心是 CA/MAS/SI、ANN 适宜性、土地类型竞争与自适应惯性机制。它擅长回答：

> 在给定驱动因子、土地需求、邻域规则和情景约束下，未来土地利用格局会如何演化或分配？

GIS Data Agent 的 TWM 不是单纯替代 FLUS 的土地利用模拟器，而是面向自然资源和国土空间治理的：

```text
state -> action-conditioned simulation -> evidence-gated planning
```

世界模型框架。它擅长回答：

> 某个规划、审批、保护或建设行动，在规则、证据、因果校准和审计边界下会带来什么后果，以及这个结论能否升级为可用 claim？

一句话概括：

> FLUS/GeoSOS 强在“土地类型如何竞争和扩张”；TWM 强在“行动是否合规、影响是否可信、方案是否可审计”。

## 2. GeoSOS/FLUS 的方法定位

GeoSOS 是由李晓教授团队提出和开发的地理模拟与优化系统。官网说明其集成 cellular automata, CA、agent-based models, ABMs，以及 swarm intelligence models, SIMs，用于地理过程模拟和复杂空间优化问题，包括土地利用变化、城市增长、自然保护区分区和设施选址。

GeoSOS 软件体系包含独立 GeoSOS 软件和 ArcGIS 插件版本。其底层思路是 bottom-up 地理模拟，包含 CA、MAS 和 SI 三类主要组件，并提供 MCE-CA、logistic-CA、PCA-CA、ANN-CA、Decision-tree-CA 等 CA 算法，以及设施选址、路径搜索、面积优化等空间优化能力。

FLUS 是 GeoSOS 系列中与土地利用变化模拟最相关的模型。根据 FLUS 页面和 2017 年 Landscape and Urban Planning 论文，FLUS 的主要特征包括：

- 基于 Cellular Automata 的多类型土地利用分配模型。
- 使用 ANN 学习土地利用格局与自然、人类驱动因子之间的复杂关系。
- 通过自适应惯性和竞争机制处理不同土地利用类型之间的竞争与相互作用。
- 通过随机机制反映 LUCC 动态的不确定性。
- GeoSOS-FLUS 是对原 GeoSOS 软件的扩展，用于多土地利用变化模拟和情景分析。
- 未来土地需求通常需要由外部模型提供，例如 System Dynamics 或 Markov chain。

因此，GeoSOS/FLUS 的本质是：

> 以土地利用类型为中心的 CA 仿真与空间分配模型，并可与 MAS/SI/优化算法耦合。

## 3. TWM 的方法定位

GIS Data Agent 中的 TWM 是面向国土空间治理的 geospatial world model。它不是把 GIS 图层简单输入一个预测器，而是将国土空间状态组织为对象、关系、规则、证据和复核任务组成的可计算状态。

当前工程证据包括：

- `data_agent/territory_world_model/models.py`：定义 project、state、object、relation、rule、evidence、forecast、rollout 等结构。
- `data_agent/territory_world_model/state_builder.py`：将 MMFE 语义融合包转为对象、关系、层级 token 与质量摘要。
- `data_agent/territory_world_model/rule_evaluator.py` 和 `evidence.py`：处理规则命中、证据项、复核任务和审计材料。
- `data_agent/territory_world_model/planner.py`：提供 action-conditioned 多头 forecast、beam planning 和 counterfactual rollout。
- `data_agent/territory_world_model/spatial_causal_estimator.py`：提供空间固定效应与 treated/control neighbor matching 的因果校准适配器。
- `data_agent/toolsets/territory_world_model_tools.py`：提供 ADK Agent 可调用的 `twm_*` 工具。

TWM simulator 的核心目标不是预测单一下一帧影像或土地适宜性分数，而是预测：

```text
p(
  future_state,
  constraint_risk,
  planning_utility_delta,
  uncertainty
  | current_hierarchical_gis_state, action, scenario, evidence
)
```

这意味着 TWM 的核心变量不是“某个元胞变成哪种土地类型”，而是：

- 当前层级 GIS 状态是什么。
- 执行了什么规划、审批、保护或建设行动。
- 行动是否被规则允许。
- 证据是否足够支撑模型结论。
- 未来状态、约束风险、规划效用和不确定性如何变化。
- 结果能否通过 causal/evidence gate 升级为规划 claim。

## 4. 逐项对比

| 维度 | GeoSOS/FLUS | GIS Data Agent TWM |
|---|---|---|
| 主要目标 | 多类型土地利用变化模拟、城市增长、情景分析、空间优化 | 国土空间治理中的行动推演、风险评估、方案排序、证据审计 |
| 核心问题 | 土地利用格局未来如何变化 | 某个行动在规则和证据约束下会造成什么后果 |
| 基本单元 | 栅格/元胞、土地利用类型、驱动因子、邻域 | `parcel / block / township / county / project / rule / evidence / review_task` |
| 状态表达 | 土地利用类型图、驱动因子栅格、邻域状态 | 层级 GIS 对象-关系-规则-证据状态 |
| 动力学机制 | CA 转换规则、ANN 适宜性、自适应惯性、土地类型竞争 | action-conditioned dynamics，多头输出 future state、constraint risk、utility delta、uncertainty |
| 人类/自然因素 | 通过驱动因子、土地需求、场景、规划政策进入模型 | 通过 action、scenario、审批/审查历史、规则、证据和因果校准进入模型 |
| 优化机制 | GeoSOS 强在 CA 与 MAS/SI/蚁群等优化耦合；FLUS 强在土地利用分配 | planner 是 simulator 的 consumer，可使用 beam search、MPC、constrained rollout，但不能绕过 evidence gate |
| 约束处理 | 可表达规划边界、土地需求、转换限制、适宜性 | 规则命中、硬约束、action mask、人工复核和审计链是一等公民 |
| 因果能力 | 主要是校准后的情景模拟，不直接识别干预因果效应 | 内置 spatial fixed effects、treated/control neighbor matching；证据不足则返回 `review` |
| 不确定性 | 通过随机机制反映 LUCC 动态不确定性 | 输出 epistemic、aleatoric、calibration gap、confidence，并与 evidence gate 绑定 |
| 输出结果 | 未来土地利用图、情景模拟结果、空间分配结果 | 未来状态、约束违背概率、效用变化、不确定性、证据 gate、审计报告、复核任务 |
| 工程形态 | 桌面软件、ArcGIS 插件、C++/Qt/GDAL 等 | GIS Data Agent 服务/API/ADK toolset，嵌入自然资源治理智能体流程 |
| 成熟度 | 成熟经典算法和软件体系 | 已形成原型闭环，但生产级 claim 仍需真实审批审查历史和跨区域验证 |

## 5. 相同点

TWM 与 GeoSOS/FLUS 并非完全无关。两者共享以下问题背景：

- 都面向地理空间过程变化。
- 都关注土地利用、规划约束和空间决策。
- 都需要多源 GIS/遥感/社会经济数据。
- 都可服务规划、环境管理、保护区划定、城市增长或自然资源治理。
- 都需要处理空间异质性、邻域关系和未来情景。

因此，FLUS 可被视为 TWM 在土地利用模拟方向的重要前序基线之一。TWM 不能声称“第一次做土地利用模拟”，因为 GeoSOS/FLUS、CLUE/CLUE-S、CA-Markov、SLEUTH、PLUS、UrbanSim 等已有大量成熟工作。

## 6. 关键差异

### 6.1 从土地类型演化到行动条件推演

FLUS 的核心是土地利用类型在空间上的竞争、转换和分配。它关心的是在给定需求和驱动因子下，哪些栅格会转为某种土地利用类型。

TWM 的核心是 action-conditioned dynamics。它关心的是在当前国土空间状态下，如果执行某项规划、审批、保护、建设或审查行动，未来状态、约束风险和规划效用如何变化。

因此，TWM 的动作不是附属输入，而是世界模型推演的条件变量。

### 6.2 从栅格 CA 到层级对象-关系状态

FLUS 主要基于栅格元胞和土地利用类型，虽然可结合多种驱动因子和规划约束，但基本空间计算单元仍偏 raster/CA。

TWM 的状态是层级 GIS object-relation-rule-evidence state，包括 parcel、block、township、county、project、rule、evidence、review_task 等对象，以及重叠、邻接、包含、项目-地块、规则命中、证据支撑等关系。

这使 TWM 更适合自然资源一张图、用途管制、审批审查、项目监管和可追溯审计。

### 6.3 从情景模拟到证据门控 claim

FLUS 输出情景下的土地利用模拟结果。结果可信度主要依赖模型校准、历史验证、Kappa/Figure of Merit 等空间模拟评价指标。

TWM 的输出不仅包含预测结果，还包含 evidence gate。若存在 synthetic/not-for-production 数据、证据覆盖不足、action mask 阻断、空间因果支持不足、covariate balance 或 spatial interference 问题，系统只能返回 `review`，不能将模型输出升级为生产 claim。

也就是说，TWM 的核心不是“预测一个结果”，而是判断“这个结果是否有资格被使用”。

### 6.4 从相关性模拟到空间因果校准

FLUS 通过 ANN 和 CA 机制学习土地利用格局与驱动因子之间的关系，并通过竞争机制和随机机制模拟变化过程。

TWM 在此基础上进一步引入 causal calibration：使用观测审批/审查历史、treated/control、空间邻接、空间固定效应、邻近匹配和不确定性诊断校准行动效应。若空间支持不足，TWM 的空间因果适配器会返回 `review`，而不是强行给出可用结论。

这一区别对规划决策很关键：土地利用变化的相关性预测不等于规划行动的干预收益。

### 6.5 从优化器本体到 planner consumer

GeoSOS 的一个重要特点是将 simulation 与 optimization 耦合，例如 CA 与 MAS/SI、蚁群算法等空间优化策略结合。

TWM 中 planner 不定义世界模型本体。planner 是 simulator 的 consumer，消费 future state、constraint risk、utility delta、uncertainty 等输出，再做 beam search、MPC-style candidate search 或 constrained rollout。planner 的方案收益必须受 simulator、causal calibration 和 evidence gate 共同限定。

这避免了把一个启发式搜索器或 MPC 过程直接包装成世界模型。

## 7. 创新边界判断

不建议使用以下表述：

> TWM 是世界上第一个地理空间模拟模型。

这个说法不稳，因为土地利用模拟、城市仿真、空间优化、数字孪生和遥感预测已有大量已有工作。

也不建议说：

> TWM 比 FLUS 更先进，所以可以替代 FLUS。

这也不准确。FLUS 在土地利用 CA 模拟、情景分配和软件成熟度上仍然是强基线。TWM 与 FLUS 的关系更适合表述为范式升级和任务扩展，而不是简单替代。

更稳妥的创新表述是：

> TWM 提出一种面向国土空间治理的 geospatial world model，把层级 GIS 对象-关系-规则-证据状态、行动条件动力学、空间因果校准、证据门控和规划消费闭环统一到同一个可审计框架中。相较于传统土地利用模拟、遥感预测、城市数字孪生和 GIS 优化工具，TWM 的核心突破是让规划 claim 必须经过 action-conditioned simulator 与 causal/evidence gate 才能升级。

英文论文式表述可以写成：

> We introduce a governance-oriented geospatial world model for territorial planning. TWM represents land systems as hierarchical GIS object-relation-rule-evidence states, learns action-conditioned multi-head dynamics for future state, constraint risk, planning utility and uncertainty, and upgrades planning claims only through spatial causal calibration and evidence-gated validation.

## 8. 与 FLUS 的关系建议

在论文、汇报或答辩中，建议按以下关系描述：

1. GeoSOS/FLUS 是 TWM 的重要传统基线之一。
2. TWM 不否定 FLUS，而是把土地利用模拟从“类型格局演化”扩展到“治理行动后果推演”。
3. FLUS 的 CA/ANN/竞争机制可作为 TWM simulator 的一类 domain baseline 或候选 transition backend。
4. TWM 的差异化能力在规则、证据、因果、审计和 planner consumer 闭环。
5. 对土地利用格局预测任务，应与 FLUS/PLUS/CA-Markov 等进行基线对比；对审批审查、行动干预、可审计规划 claim 任务，应突出 TWM 的治理型世界模型定位。

## 9. 可直接引用的简短结论

短版：

> FLUS/GeoSOS 是经典的土地利用 CA 仿真与优化系统；TWM 是面向国土空间治理的 evidence-gated geospatial world model。前者强在土地类型如何竞争和扩张，后者强在行动是否合规、影响是否可信、方案是否可审计。

中版：

> GeoSOS/FLUS 以 CA、ANN、自适应惯性和土地类型竞争机制模拟多类型土地利用变化，并可与 MAS/SI 等优化算法耦合。TWM 的目标不是重复构造一个土地利用模拟器，而是把层级 GIS 对象-关系-规则-证据状态、行动条件动力学、空间因果校准、证据门控和规划消费闭环组织成可审计的国土空间治理世界模型。

强调创新边界版：

> TWM 不能声称首次实现地理空间模拟，但可以主张首次系统地把 action-conditioned territorial dynamics、规则/证据状态、空间因果校准和 evidence-gated planner consumer 结合到自然资源治理场景中。其核心创新不是“预测土地如何变化”，而是“预测必须被行动、规则、因果和证据边界共同约束”。

## 10. 当前工程状态与风险

当前 GIS Data Agent 中的 TWM 已经具备 renderer-simulator-planner 原型闭环：

- renderer 层：对象、关系、规则、证据、复核、审计状态已形成结构化状态。
- simulator 层：action-conditioned forecast、counterfactual rollout、causal calibration、spatial estimator、evidence gate 已形成验证链路。
- planner 层：beam planning、counterfactual rollout、ArcGIS/MPC consumer 方向已明确。

但当前仍不能升级为生产级 world-model claim，主要原因是：

- 本地验证数据仍含 synthetic 或 not-for-production 标记。
- 真实 treated/control 审批审查历史不足。
- 真实空间邻接、跨区验证和空间干扰诊断仍需补强。
- 图/Transformer 层级动力主干、完整训练循环、ranking loss 优化和 uncertainty calibration 仍需进一步实现。

因此，当前最准确的状态是：

> TWM 已经从概念进入可运行原型和数据验证阶段；其 simulator 路线已经成型，但生产级创新主张还需要非合成审批审查历史、真实空间邻接、跨区域验证和更强的 causal/evidence gate 通过结果支撑。

