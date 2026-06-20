# TWM 与李飞飞《A Functional Taxonomy of World Models》的对应关系

本文档说明 GIS Data Agent 中 Territory World Model, TWM 与李飞飞文章《A Functional Taxonomy of World Models》的对应关系。

来源说明：

- 文章：Fei-Fei Li, “A Functional Taxonomy of World Models”
- 链接：`https://drfeifei.substack.com/p/a-functional-taxonomy-of-world-models`
- 发布时间：2026-06-03
- 性质：Substack 文章，不是 peer-reviewed paper
- 核心副标题：Renderers, Simulators, Planners, and the Loop That Connects Them

## 1. 文章的核心框架

这篇文章的价值不在于提出某个具体模型结构，而在于给出一个功能性分类。它把 world model 放在 agent loop 中理解：智能体基于观察和目标选择动作，动作改变世界状态，世界状态再生成新的观察。

在这个 loop 中，文章区分了三类功能：

1. Renderer：从世界状态/动作生成 observation，典型形式是视觉、视频、3D 或感知输出。
2. Simulator：在状态和动作之间推演世界如何变化，是连接 renderer 和 planner 的骨干。
3. Planner：从当前观察、目标和模型推演中选择动作。

文章最重要的提醒是：把世界模型只理解成“视频生成器”太窄；真正的 world model 应该放在“渲染-模拟-规划”的闭环里理解。

## 2. TWM 与三类功能的对应

| 李飞飞文章中的功能 | 通用含义 | TWM 中的对应 | 当前工程状态 |
|---|---|---|---|
| Renderer | 将世界状态转为 observation | GIS-operational rendering：对象、关系、规则叠置、风险图层、指标表、审计报告 | 已有对象-关系状态、规则命中、审计报告；不是 photorealistic renderer |
| Simulator | 根据状态和动作推演未来状态 | action-conditioned territorial rollout：预测 future latent state、constraint state、utility state、uncertainty | 已有确定性 scaffold，trainable dynamics 未完成 |
| Planner | 基于模型推演选择动作 | latent MPC、beam search、constrained rollout 等 planner consumer | 已有 planner facade、forecast、counterfactual rollout；ranking loss 未完成 |
| Loop | observation-action-state 的闭环 | GIS evidence-gated review loop：规则、证据、人工复核、审计再反馈 | 已有 evidence item、checksum、review task、validation report |

## 3. 为什么 TWM 不是视觉世界模型

李飞飞文章中的 renderer 很容易让人想到视频生成、3D 生成或 photorealistic world generation。但 TWM 的领域是国土空间治理，不应该把核心目标误转成视觉渲染。

TWM 的 renderer 是 GIS-operational renderer：

- 把 state objects 渲染成 GIS 图层和对象清单。
- 把 state relations 渲染成叠置、邻接、包含、距离、冲突关系。
- 把 rule hits 渲染成风险清单和可审计证据链。
- 把 forecast/rollout 渲染成方案指标、风险变化和人工复核任务。

因此 TWM 与视觉世界模型的对应不是“生成视频”，而是“把可计算地理状态还原成 GIS 业务可观察、可复核、可审计的 observation”。

## 4. TWM 的核心应落在 Simulator

从这篇文章的分类看，TWM 的核心创新应落在 simulator，而不是 renderer 或 planner。

TWM simulator 应预测：

```text
p(
  future_latent_state,
  constraint_state,
  utility_state,
  uncertainty
  | current_hierarchical_state, action, scenario, evidence
)
```

这与用户此前提出的要求一致：

- 状态层不是 flat vector，而是 parcel/block/township/county 层级 token。
- 动力层必须 action-conditioned。
- 输出层必须多头。
- 训练目标必须服务 planning ranking、constraint calibration 和 uncertainty calibration。
- GeoFM 只能 gated enhancement。
- 反事实必须经过 causal calibration。
- claim 必须经过 evidence gate。

## 5. Planner 不是 TWM 本体

李飞飞文章把 planner 单独列为一类功能，这对 TWM 很关键。

TWM 不应把 MPC、beam search 或 constrained rollout 直接说成世界模型。更准确的边界是：

- TWM simulator 产生未来状态、约束风险、效用变化和不确定性。
- Planner 消费这些输出，在动作空间内搜索方案。
- GIS 审计层把方案、证据和人工复核闭环化。

这也解释了为什么论文 9 在 TWM 体系里非常重要：ArcGIS/MPC 是 deployable planner consumer，不是 TWM 的全部。

## 6. TWM 对文章框架的 GIS 扩展

李飞飞文章是通用 AI/空间智能视角。TWM 面向自然资源治理，需要额外增加一条 GIS governance axis：

```text
Renderer -> Simulator -> Planner -> Evidence/Review Loop
```

也就是说，TWM 的闭环不能停在“planner 选择动作”。在行政和规划场景中，还必须回答：

- 这个结论来自哪些源数据？
- 命中了哪些规则？
- 证据是否有 checksum？
- 是否存在未完成的人工复核？
- claim 是否有资格从 review_required 升级为 supported？

因此 TWM 的完整功能分类应写成：

1. GIS renderer：状态可观察化。
2. Territorial simulator：动作条件推演。
3. Planning consumer：约束规划与方案搜索。
4. Evidence-gated loop：证据、复核、审计、部署边界。

## 7. 当前工程实现映射

当前 GIS Data Agent 已新增 `world_model_profile` 能力：

- API：`POST /api/twm/states/{id}/world-model-profile`
- Tool：`twm_world_model_profile`
- Async Tool：`twm_world_model_profile_async`

该 profile 输出五个轴：

1. `rendering`
2. `simulation`
3. `planning`
4. `closed_loop`
5. `evidence_provenance`

其中前四个对应李飞飞文章的 renderer/simulator/planner/loop，第五个是 TWM 面向 GIS 治理新增的证据溯源轴。

## 8. 对 TWM 论文写作的启示

如果后续写 TWM 论文，可以这样使用这篇文章：

- 在引言或 discussion 中引用它作为“world model 不应窄化为视频生成器”的概念来源。
- 用它解释 TWM 的功能边界：GIS renderer、territorial simulator、planner consumer、evidence loop。
- 明确说明它不是 peer-reviewed technical foundation，因此不能替代 Dyna、World Models、PlaNet、Dreamer、MuZero、PETS/MBPO、MPC、causal inference、uncertainty calibration 等正式学术文献。
- 把它作为“概念框架”，把正式论文作为“技术依据”。

推荐表述：

> Following Li's functional taxonomy of world models as renderers, simulators and planners connected through an agent loop, we position TWM not as a photorealistic renderer, but as a GIS-operational world model whose core simulator predicts action-conditioned territorial state, constraint risk, planning utility and uncertainty, while planner modules consume these forecasts and an evidence-gated GIS audit loop bounds deployable claims.

## 9. 最重要的结论

TWM 与李飞飞文章的对应关系可以压缩为一句话：

> TWM 不是视觉世界模型意义上的 renderer；TWM 的核心是 simulator，planner 是 consumer，GIS evidence/provenance 是自然资源治理场景对 world-model loop 的必要扩展。

