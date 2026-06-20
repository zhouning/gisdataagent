# TWM 论文谱系、贡献关系与完整架构说明

本文档面向 GIS Data Agent 中 Territory World Model, TWM 的后续设计、开发与验证。它不是对某一篇论文的摘要，而是把用户提供的 12 篇论文/项目材料放在同一条技术演进线上，说明它们之间的相互关系、各自对 TWM 的贡献，以及据此形成的完整 TWM 架构。

## 0. 输入材料与证据边界

### 0.1 论文与项目材料

| 用户编号 | 材料路径 | 在 TWM 设计中的主要证据类型 |
|---|---|---|
| 1 | `/Users/zhouning/farmland-drl-optimization/manuscript/manuscript.tex` | 早期耕地布局 DRL、规划单元评分、硬约束与迁移验证 |
| 2 | `/Users/zhouning/cadastral-drl-synthetic/submission/eswa_anonymous/01_main_manuscript_anonymous/manuscript_eswa_anonymous.tex` | 不规则地籍图斑合成基准、稀疏奖励下算法选择边界 |
| 3 | `/Users/zhouning/paper3-block-level-farmland-drl/submission/lup_anonymous/01_main_document_anonymous/manuscript_lup_anonymous.tex` | 街区/区块级抽象、宏观规划与微观执行分离 |
| 4 | `/Users/zhouning/paper4-county-marl-farmland-consolidation/submission_ems_paper4/manuscript/ems_manuscript.tex` | 县域尺度、多乡镇/多智能体分解、集中式与共享策略比较 |
| 58 | `/Users/zhouning/paper58-geofm-world-model-rl/paper/rse_submission_paper58/manuscript/rse_geofm_world_model_rl.tex` | GeoFM embedding 与轻量 latent dynamics 的边界，GeoFM 不应默认成为主角 |
| 6 | `/Users/zhouning/paper6-spatial-causal-inference/paper/ijgis_submission_20260605/01_manuscript/01_manuscript_ijgis.tex` | 空间因果推断、观测校准、反事实与世界模型仿真之间的关系 |
| 7 | `/Users/zhouning/paper7-causal-mbrl-farmland-consolidation/submission/ceus/01_main_document_anonymous/manuscript.tex` | 因果校准的 model-based RL，action-conditioned transition 与 reward calibration |
| 9 | `/Users/zhouning/arcgis-farmland-mpc/paper/submission_scirep_corrected/05_source_editable/manuscript_scirep.tex` | ArcGIS 可部署 MPC、GIS 审计、硬约束执行与 reproducible planning |
| 10 | `/Users/zhouning/paper10-geojepa-mpc-farmland-layout/paper10_geojepa_mpc/experiments/results/e0_paper10_project_proposal_opening_report_2026-06-18.md` | GeoJEPA-MPC、monitor-gated value labels、claim-evidence gate |
| 11 | `/Users/zhouning/paper11-geofm-farmland-suitability-rl/paper/proposal/01_project_initiation_proposal.md` | GeoFM suitability RL、B0/B1 消融、one-step fit 不等于 planning lift |
| 12 | `/Users/zhouning/alphaearth-training-system/submission/paper12_isprs_jprs_20260606/02_latex_source/main_isprs_jprs.tex` | GeoFM/Prithvi 架构感知适配、域偏移、地理切分、生产验证边界 |
| 13 | `/Users/zhouning/paper13-future-aware-farmland-planning/paper/paper13_opening_report_zh.md` | future-aware planning、未来状态预测、非循环验证标签与证据门控 |

### 0.2 原始需求来源

TWM 的原始需求来源是 `/Users/zhouning/Downloads/地理空间世界模型核心技术路线说明.docx` 及其同目录 HTML 转换稿。该材料提出了以下需求方向：多源自然资源数据统一入模、对象-关系-规则状态、规则优先的约束推演、风险/方案/影响评估、可追溯 GIS 证据链。

但该 Word 材料中的技术路线仍然偏概念层：它列举了空间知识图谱、GNN、元胞自动机、系统动力学、时空预测、约束 RL、多目标优化等可选技术，却没有严格定义状态、动作、动力学、输出头、训练目标、因果校准、GeoFM 门控和验证阶梯。因此本文把它作为需求来源，而不是直接作为最终 TWM 架构。

### 0.3 当前工程证据

当前 GIS Data Agent 中已经有 TWM 工程骨架：

| 模块 | 当前路径 | 当前作用 |
|---|---|---|
| 状态、场景、规则、预测数据结构 | `data_agent/territory_world_model/models.py` | 定义 TWM project/state/object/relation/rule/evidence/forecast/rollout 等结构 |
| MMFE 语义包入模 | `data_agent/territory_world_model/state_builder.py` | 将语义融合包转为对象、关系、层级 token 与质量摘要 |
| 规则与证据链 | `data_agent/territory_world_model/rule_evaluator.py`, `data_agent/territory_world_model/evidence.py` | 规则命中、证据项、复核任务、审计材料 |
| 单步预测与规划消费 | `data_agent/territory_world_model/planner.py` | action-conditioned 多头 forecast、beam search、counterfactual rollout |
| 服务与 API | `data_agent/territory_world_model/service.py`, `data_agent/api/territory_world_model_routes.py` | 项目、状态构建、规则评估、审计、forecast、rollout |
| Agent 工具 | `data_agent/toolsets/territory_world_model_tools.py` | `twm_*` 工具，供 ADK Agent 调用 |
| 测试 | `data_agent/test_territory_world_model.py` | 覆盖 MMFE 入模、规则、forecast、rollout、route 与 toolset |

当前实现仍是工程化 TWM scaffold：它已经具备状态、规则、证据、多头预测、反事实 rollout，以及首个本地 trainable neural candidate 接口，但正式的图/Transformer 层级动力主干、完整训练循环、ranking loss 优化、uncertainty calibration 和大规模跨区验证仍未完成。

## 1. 12 篇材料之间的总体关系

这 12 篇材料不是平行关系，而是从“耕地布局优化”逐步走向“可预测、可反事实、可规划、可自证边界的地理空间世界模型”的连续演进。

### 1.1 第一条主线：从图斑/网格优化到层级空间状态

论文 1 提供了最早的耕地布局 DRL 基线：将规划单元作为模型操作对象，通过评分策略、成对推理和硬约束保持数量/面积守恒。这一阶段已经有“规划单元 token”和“约束掩码”的雏形，但状态仍偏扁平，世界模型概念尚未形成。

论文 2 把问题推进到不规则地籍图斑和合成基准，暴露了稀疏奖励、图斑尺度变化、透明诊断和算法选择边界。它的重要结论不是“更复杂的 RL 一定更好”，而是：当简单透明诊断已经能解释或解决问题时，不应把 DRL 或 world model 当成默认方案。

论文 3 引入 block-level 抽象，形成“宏观规划、微观执行”的结构：上层在 block/township 等政策相关尺度上规划，下层通过确定性微观执行引擎落到地块/图斑。这直接支持 TWM 的层次 token 设计：parcel/block/township/county 不应被压成一个 flat vector。

论文 4 将尺度扩大到县域，并比较 centralized DRL 与 shared-policy MARL。它说明县域问题不能只靠一个巨大的全县 MLP 解决，必须用乡镇/片区分解动作空间和状态空间，同时保留县域总目标与跨区耦合。

这条主线给 TWM 的结论是：状态层必须是分层对象-关系状态，而不是 flat vector；动作层必须支持跨尺度目标，不能把县域规划硬塞进单一低维向量。

### 1.2 第二条主线：从 model-free RL 到 model-based planning 与 GIS 可部署性

论文 1-4 主要建立了 DRL/MARL 在耕地优化中的问题域、尺度和约束基础，但仍以策略学习为主。

论文 7 进入因果校准的 model-based RL：模型不只是输出动作，而是学习 action-conditioned transition，并用观测 treatment effect 修正 reward 或 utility。这是 TWM 从“预测器”进入“世界模型”的关键一步：模型必须回答给定状态、动作、情景后，下一状态、约束状态和效用状态会如何变化。

论文 9 是这条线的工程落地点。它把 model-based planning/MPC 接入 ArcGIS 工具链，强调 reproducible planning、硬约束、no-net-loss、独立 GIS audit 和可复核输出。论文 9 的意义非常关键：它证明 planner/MPC 应该是世界模型的 consumer，而不是世界模型本身；世界模型负责可校准的状态转移与风险/效用预测，ArcGIS/MPC 负责在合法动作空间内搜索、执行和审计。

这条主线给 TWM 的结论是：动力层必须 action-conditioned；planner 层可以使用 latent MPC、beam search、constrained rollout，但它只是消费 TWM 输出，不能把一个启发式搜索器重命名为世界模型。

### 1.3 第三条主线：GeoFM 是增强信号，不是默认主角

论文 58 直接检验 GeoFM embedding + lightweight latent dynamics 的能力边界。它说明冻结 AlphaEarth/GeoFM embedding 对世界模型有价值，但不足以单独支撑可靠规划。GeoFM 提供的是表示增强和先验，不是天然的 world dynamics。

论文 11 进一步要求 B0/B1 式消融：只有当 GeoFM embedding 在 downstream planning 上超过显式 GIS 特征基线时，才应保留。否则应 gate 掉，而不是因为“GeoFM 看起来先进”就默认作为主干。

论文 12 从 GeoFM/Prithvi 适配角度给出更强边界：架构感知很重要，LoRA 在 fused-QKV 结构上会有静默失败风险；域偏移、地理切分、标签质量和 adapter capacity 会显著影响结果。它对 TWM 的提醒是：任何 GeoFM 组件都必须在真实地理切分、生产式标签和下游规划指标上验证，不能只看 embedding reconstruction 或 one-step semantic score。

论文 10 的 GeoJEPA-MPC 则把 GeoFM 与 MPC 连接起来，但重点不是“模型更大”，而是 monitor-gated value labels 和 claim-evidence map。也就是说，GeoFM/JEPA 只能在证据通过 gate 后升级为 planning claim。

这条主线给 TWM 的结论是：GeoFM 进入状态层时必须可控、可消融、可门控。TWM 的主干是层级地理状态与 action-conditioned dynamics，GeoFM 只是 state encoder 的可选增强通道。

### 1.4 第四条主线：从相关性预测到因果校准与反事实边界

论文 6 从三种角度组织空间因果推断：统计估计、LLM 因果推理和 world-model simulation。其关键贡献是把“空间混杂、处理效应、反事实解释、观测校准”放到同一框架中，提醒 TWM 不能只学习相关性。

论文 7 将这一点落到 model-based RL 中：用 treatment-effect / observational calibration 修正 reward 或 scenario scale，使 model-based planning 不至于把历史相关性误当作干预效果。

论文 13 将 future-aware planning 引入耕地规划：模型既要看当前状态，也要预测未来状态和未来风险，并且验证标签不能循环依赖模型自身输出。它和论文 10 一样强调 evidence gate：证据不过关，claim 不能升级。

这条主线给 TWM 的结论是：TWM 的预测必须能支持 counterfactual rollout，但反事实结论只能在 causal calibration 和 evidence gate 通过后被使用。没有 treatment-effect 支撑的“干预收益”只能标记为 review_required。

### 1.5 第五条主线：从科研原型到可审计 GIS 基础能力

Word 技术路线说明提出了面向自然资源治理的总体定位：规则优先、模型辅助、人工复核、全程留痕、数据不出域。

论文 9 证明这种定位必须落在 GIS 工具链和审计链上。

论文 10 和 13 进一步要求 claim-evidence gate。

GIS Data Agent 当前 TWM 工程把这些要求初步落实为：MMFE 语义包入模、对象-关系-规则状态、规则命中、证据项 checksum、复核任务、audit report、forecast、counterfactual rollout 和 Agent/API tool。

这条主线给 TWM 的结论是：TWM 不应成为另一个黑箱模型服务，而应成为 GIS 中的“状态-推演-约束-证据”基础能力。

## 2. 每篇材料对 TWM 的贡献或关联

### 2.1 论文 1：从规划单元评分到 TWM action mask

论文 1 的贡献在于把耕地布局问题转成可学习的规划单元选择问题，并通过硬约束保持面积/数量等规划条件。它对 TWM 的直接贡献包括：

- 规划单元可以视为早期 parcel/block token。
- policy/action 需要被约束掩码限制，不能在非法动作空间中优化。
- 迁移验证说明状态表达必须对区域尺度和单元数量有一定不变性。
- 它仍主要是 model-free planning，不足以成为 TWM 的动力学层。

对 TWM 的架构要求：保留 action mask、硬约束和规划单元抽象，但不能停留在“策略直接选地块”的模式。

### 2.2 论文 2：合成地籍基准与 algorithm gate

论文 2 的贡献在于建立不规则地籍图斑上的合成基准和透明诊断，说明 Maskable PPO 等 DRL 方法在稀疏、不规则场景下并不总是优于简单可解释方法。

对 TWM 的贡献包括：

- 需要先判断问题是否真的需要 world model。
- 需要 algorithm-selection gate：如果透明规则/启发式已经足够，TWM 不应过度建模。
- 合成数据可用于 TWM 的最小单元测试和压力测试，但不能替代真实 GIS 证据。

对 TWM 的架构要求：TWM 应包含 evidence/diagnostic gate，防止把复杂模型当作默认答案。

### 2.3 论文 3：block-level 抽象与宏观-微观分离

论文 3 的贡献是把规划从图斑级单步选择提升到 block-level 结构，使策略在政策相关尺度上规划，再通过微观执行引擎落地。

对 TWM 的贡献包括：

- parcel/block/township 层次 token 的直接来源。
- 宏观 planning state 与微观 execution state 应分离。
- TWM 输出不应只是图斑变化，还应包含 block-level 连片度、百亩方等规划指标。

对 TWM 的架构要求：状态 encoder 必须显式建模层级关系，动力学预测也应按层级输出。

### 2.4 论文 4：县域 MARL 与 township decomposition

论文 4 的贡献在于把问题推到县域尺度，并用多乡镇/多智能体结构处理动作空间爆炸和跨区目标耦合。

对 TWM 的贡献包括：

- county/township 层级是必要结构，不是可选标签。
- 单一 centralized policy 的平均表现、方差和可解释性都需要与 MARL 分解比较。
- TWM 需要处理县域总目标与乡镇局部动作之间的关系。

对 TWM 的架构要求：动力学层应支持多主体/多区域 action conditioning，并在 county-level 汇总约束与效用。

### 2.5 论文 58：GeoFM world-model RL 的边界

论文 58 的贡献是直接探索 GeoFM embedding 与 world-model RL 的结合，并给出边界：冻结 GeoFM embedding 可作为 latent state 的增强，但轻量 latent dynamics 不能自动保证 planning 有效。

对 TWM 的贡献包括：

- future latent state head 的来源之一。
- GeoFM embedding 应与显式 GIS 特征并列输入，而不是替代 GIS 状态。
- multi-step prediction 需要和 planning outcome 绑定验证。
- 不确定性和 evidence boundary 必须显式输出。

对 TWM 的架构要求：GeoFM 只作为 gated enhancement；没有 downstream planning lift 就不能成为默认主干。

### 2.6 论文 6：空间因果推断与 causal calibration

论文 6 的贡献是把空间统计因果估计、LLM 因果推理和 world-model simulation 组织为互补路径，强调空间混杂、邻近溢出、处理效应和反事实校准。

对 TWM 的贡献包括：

- causal calibration layer 的理论来源。
- scenario scale 和 reward/utility 不能只由相关性模型给出。
- 反事实 rollout 必须说明 treatment、control、confounder 与观测支持。

对 TWM 的架构要求：TWM 的 utility/reward head 需要可被 treatment-effect 或 observational calibration 修正。

### 2.7 论文 7：causal MBRL 与 action-conditioned transition

论文 7 的贡献是把因果校准落到 model-based RL：学习环境转移模型，并用观测 treatment effect 校准 reward 或规划收益。

对 TWM 的贡献包括：

- 动力层必须预测 `p(next_state, constraint_state, utility_state | current_state, action, scenario)`。
- 训练与评估不能只看 one-step next-state fit，还要看 rollout 和 planning lift。
- final real-env evaluation 或 GIS audit 是必要闭环。

对 TWM 的架构要求：TWM 需要 action-conditioned dynamics、多头输出、counterfactual rollout 和 causal calibration。

### 2.8 论文 9：ArcGIS Farmland MPC 与可部署 GIS consumer

论文 9 是 TWM 架构中不可替代的一环。它把 MPC/规划搜索从论文实验带到 ArcGIS 工具链，强调可复现规划、硬约束、独立 GIS 审计和 no-net-loss 等执行约束。

对 TWM 的贡献包括：

- Planner/MPC 是 world model 的 consumer，而不是 world model 本身。
- 规划输出必须能还原为 GIS 图层、指标表和审计报告。
- 硬约束和独立 GIS audit 是部署边界，不是论文附属项。
- 排序/选择候选方案的 training signal 可以来自 MPC candidate ranking。

对 TWM 的架构要求：TWM 必须输出 planner 可消费的 latent state、constraint probability、utility delta 和 uncertainty；ArcGIS/GIS Data Agent 负责方案搜索、图层化、审计和人工复核。

### 2.9 论文 10：GeoJEPA-MPC 与 evidence-gated claim

论文 10 的贡献不是简单引入更大的 JEPA/GeoFM，而是提出 monitor-gated value labels、candidate regret、overlap、one-step regret 和 claim-evidence map。

对 TWM 的贡献包括：

- evidence gate 应成为 TWM 的一级输出，不是事后说明。
- claim 只能在通过 monitor/evidence gate 后升级。
- failure rows 必须被保留，用于定义模型能力边界。

对 TWM 的架构要求：TWM 的每个 forecast/rollout/planning lift 都要携带 evidence gate；不过 gate 的输出只能是“支持/需复核/拒绝升级”，不能伪装成模型预测。

### 2.10 论文 11：GeoFM suitability RL 与 B0/B1 消融

论文 11 的贡献是明确指出 GeoFM 的加入必须通过 B0/B1、D2/D3/D4 等控制实验验证，且 one-step fit 好不代表 planning 好。

对 TWM 的贡献包括：

- GeoFM embedding 需要可开关、可消融、可 gate。
- suitability proxy 只能作为辅助信号，不能直接替代规划收益。
- downstream planning lift 是保留 GeoFM 的关键证据。

对 TWM 的架构要求：state encoder 中必须存在 `geofm_gate`，训练与验证必须比较 explicit GIS-only baseline 与 GeoFM-enhanced variant。

### 2.11 论文 12：AlphaEarth/Prithvi 适配与架构感知 GeoFM

论文 12 的贡献在于系统评估 Prithvi-100M 的 PEFT 适配，证明 GeoFM 适配方法受 backbone 架构、fused-QKV、输入模态、地理切分、标签质量和域偏移影响很大。

对 TWM 的贡献包括：

- GeoFM 组件必须做 architecture-aware inspection，不能盲目套用 LoRA 或 adapter。
- 真实 GIS 场景需要 geographic split，patch random split 会高估泛化。
- 生产式标签质量会决定 adapter 是否真正带来语义增益。
- 域偏移下 adapter capacity 可能成为瓶颈。

对 TWM 的架构要求：TWM 的 GeoFM 接入不仅要有 B0/B1 消融，还要有地理切分、域偏移压力测试、标签质量记录和 adapter 训练参数可审计记录。

### 2.12 论文 13：future-aware planning 与非循环验证

论文 13 的贡献在于把规划目标从当前最优扩展到未来状态与未来风险，强调当前状态、未来状态和非循环验证标签之间的关系。

对 TWM 的贡献包括：

- TWM 必须预测 future latent state，而不只是当前 suitability。
- 未来风险、未来约束状态和未来效用应进入输出头。
- 验证标签不能由模型自身循环生成。
- evidence gate 决定 claim 是否能升级。

对 TWM 的架构要求：TWM 的 validation ladder 必须先验证 future-state prediction，再验证 counterfactual rollout，再验证 planning lift，最后才谈 GIS 部署。

## 3. 跨论文综合结论

### 3.1 TWM 的定义

TWM 应定义为：

> 面向国土空间治理和耕地规划的层级地理空间世界模型。它以 parcel/block/township/county 层级对象-关系状态为输入，在规则、证据、情景和因果校准约束下，预测动作条件下的未来潜在状态、约束违背概率、规划效用变化与不确定性，并将结果交给 MPC/beam search/约束 rollout 等 planner 消费，最终形成可审计 GIS 证据链。

### 3.2 TWM 不是什么

TWM 不是：

- 不是把县域 GIS 特征拼成 flat vector 后喂给 MLP 的预测器。
- 不是把 CA、系统动力学、GNN 或传统时空预测器换名叫世界模型。
- 不是 GeoFM embedding 的包装器。
- 不是 MPC/beam search 本身。
- 不是自动行政决策系统。

### 3.3 核心架构原则

1. 状态层必须是层级 token，而不是 flat vector。
2. 动力层必须 action-conditioned，而不是只预测下一帧 embedding。
3. 输出层必须多头，至少包括 future latent state、constraint violation probability、planning utility delta、uncertainty。
4. 训练目标必须服务 planning，而不是只服务 reconstruction。
5. GeoFM 只能作为 gated enhancement，不是默认主干。
6. reward/utility 必须允许 causal calibration。
7. evidence gate 决定 claim 是否升级。
8. planner 是 consumer，不是 world model。
9. 验证必须分层推进。

## 4. TWM 完整架构说明

本节是本文档最重要的架构落地部分，也是 GIS Data Agent 后续 TWM 开发的准则。

### 4.1 总体分层

TWM 由 10 层组成：

1. 数据与证据底座层。
2. 层级状态表征层。
3. 状态编码与 GeoFM gate 层。
4. 动作与情景层。
5. Action-conditioned dynamics 层。
6. 多头输出层。
7. 因果校准层。
8. Evidence gate 与 claim boundary 层。
9. Planner consumer 层。
10. GIS 部署、审计与验证层。

### 4.2 数据与证据底座层

输入数据不再被视为单纯 GIS 图层，而被组织为可计算状态的证据来源：

- 图斑/地块：parcel、cadastral parcel、planning unit。
- 区块/街区：block、baimu-fang、consolidation unit。
- 行政与治理尺度：township、county、district。
- 管制对象：永久基本农田、生态红线、城镇开发边界、用途管制分区、规划区。
- 项目与审批：建设项目、审批记录、规划许可、整改记录。
- 历史版本：年度变更调查、遥感监测、多期状态差分。
- GeoFM/遥感语义：AlphaEarth/Prithvi/GeoJEPA embedding、LULC、变化检测、质量标记。
- 证据链：空间叠置证据、规则条款、源数据引用、checksum、人工复核记录。

当前工程已通过 MMFE semantic fusion bundle 将部分数据入模，形成 state objects、relations、quality summary、hierarchy tokens 和 evidence items。

### 4.3 层级状态表征层

TWM 状态不能写成一个普通向量。推荐形式为：

```text
S_t = {
  V_parcel_t,
  V_block_t,
  V_township_t,
  V_county_t,
  E_spatial_t,
  R_policy_t,
  M_constraint_t,
  H_history_t,
  G_geofm_t,
  Q_evidence_t
}
```

其中：

- `V_parcel_t`：图斑/地块 token，包含 geometry metadata、显式 GIS 特征、用途、面积、质量、邻接关系、历史差分。
- `V_block_t`：区块 token，聚合 parcel 的连片度、形态、质量、政策目标与微观执行状态。
- `V_township_t`：乡镇 token，聚合 block 的指标、约束余量、治理目标和跨区关系。
- `V_county_t`：县域 token，表达总量约束、全局规划目标、跨乡镇耦合。
- `E_spatial_t`：对象之间的关系边，包括 contains、intersects、adjacent、distance、overlap、accessibility、upstream/downstream 等。
- `R_policy_t`：规则版本、法定管控、用途准入、保护目标。
- `M_constraint_t`：动作掩码和约束掩码。
- `H_history_t`：历史差分与时间版本链。
- `G_geofm_t`：可选 GeoFM embedding。
- `Q_evidence_t`：证据覆盖、数据质量、checksum、复核状态。

工程映射：

- `TwmStateObject` 表达对象 token。
- `TwmStateRelation` 表达关系边。
- `TwmStateVersion.summary` 和 `StateBuildResult.hierarchy_tokens` 表达层级摘要。
- `TwmEvidenceItem` 和 `TwmReviewTask` 表达证据与人工复核。

### 4.4 状态编码与 GeoFM gate 层

State encoder 应由三类输入共同组成：

1. 显式 GIS 特征：面积、地类、坡度、形状、邻接、叠置、距离、审批属性、规则命中等。
2. 层级关系特征：parcel-block-township-county 的聚合与下钻关系。
3. GeoFM embedding：仅作为可选增强。

GeoFM gate 的原则：

- `B0`: explicit GIS-only baseline。
- `B1`: GIS + frozen GeoFM embedding。
- `D2/D3/D4`: 不同数据切分、任务、域偏移和标签质量控制。
- 只有当 GeoFM 在 downstream planning lift、counterfactual rollout 或 constraint prediction 上有显著增益时才启用。
- 如果 GeoFM 只提升 one-step reconstruction，但不提升 planning，应默认关闭或降权。

### 4.5 动作与情景层

动作不是普通标签，而是对空间状态的干预：

```text
A_t = {
  action_type,
  target_objects,
  target_role,
  spatial_scope,
  magnitude,
  treatment,
  parameters,
  legal_intent,
  execution_mask
}
```

情景不是自然语言备注，而是动力学条件：

```text
Z_t = {
  policy_version,
  planning_scenario,
  future_assumption,
  market_or_population_context,
  climate_or_ecological_context,
  calibration_context
}
```

当前工程中的 `TerritoryWorldModelAction` 已包含 `action_type`、`target_role`、`magnitude`、`scenario`、`parameters` 和 `treatment`。后续需要把 `target_objects`、`spatial_scope`、`legal_intent` 和 `execution_mask` 显式化。

### 4.6 Action-conditioned dynamics 层

TWM 的核心不是预测下一帧遥感图像，而是预测动作条件下的状态演化：

```text
p_theta(
  S^latent_{t+1},
  C_{t+1},
  U_{t+1},
  Omega_{t+1}
  | S_t, A_t, Z_t, Q_t
)
```

其中：

- `S^latent_{t+1}`：未来潜在空间状态。
- `C_{t+1}`：未来约束状态，包括规则违背概率、约束余量、硬约束触碰风险。
- `U_{t+1}`：未来规划效用状态，包括耕地连片度、质量、生态冲突、建设压力、治理收益等。
- `Omega_{t+1}`：不确定性、校准缺口和证据支持度。

推荐模型结构：

- 层级 graph/transformer encoder：处理 parcel/block/township/county token。
- action cross-attention：让动作作用于目标对象和相关关系边。
- scenario conditioner：将政策版本、未来假设和外部情景作为条件。
- rule-aware mask：把不可行动作和硬约束编码到 dynamics 或 planner。
- latent transition module：输出未来 latent state。
- 多头 decoder：分别输出约束、效用、不确定性和 evidence status。

当前工程中的 `TerritoryWorldModelPlanner.forecast()` 已提供确定性 action-conditioned forecast scaffold。后续应以 trainable dynamics 替换其中启发式风险/效用函数，但保留同样的输入输出契约。

### 4.7 多头输出层

TWM 至少输出以下头：

| 输出头 | 作用 | 典型验证 |
|---|---|---|
| `future_latent_state` | 未来层级状态摘要和 latent representation | future-state prediction、时序 holdout |
| `constraint_violation_probability` | 未来规则违背和约束触碰概率 | rule hit prediction、calibration/ECE |
| `planning_utility_delta` | 动作相对 baseline 的规划效用变化 | candidate ranking、MPC regret、planning lift |
| `uncertainty` | aleatoric、epistemic、calibration gap、confidence | uncertainty calibration、coverage-risk curve |
| `calibration` | treatment effect、scenario bias、risk pressure | causal calibration audit |
| `evidence_gate` | 证据是否足以升级 claim | claim-evidence map、manual review |

注意：`evidence_gate` 不是模型预测头，而是 claim boundary 控制器。它决定某个 forecast/rollout 是否可被写入报告，或只能进入人工复核。

### 4.8 训练目标

TWM 训练不能只看 reconstruction loss。推荐目标为：

```text
L =
  lambda_transition * L_transition
  + lambda_constraint * L_constraint
  + lambda_ranking * L_planning_ranking
  + lambda_causal * L_causal_calibration
  + lambda_uncertainty * L_uncertainty_calibration
  + lambda_evidence * L_evidence_consistency
  + lambda_gate * L_geofm_gate
```

各项含义：

- `L_transition`：未来状态/latent transition 的预测误差。
- `L_constraint`：规则违背、硬约束触碰、审批冲突等的分类/概率损失。
- `L_planning_ranking`：候选方案排序损失，服务 MPC/beam search 的下游选择。
- `L_causal_calibration`：使 utility/reward 与 treatment-effect 估计一致。
- `L_uncertainty_calibration`：NLL、ECE、Brier、conformal coverage 等。
- `L_evidence_consistency`：模型 claim 与证据覆盖、数据质量、复核结果一致。
- `L_geofm_gate`：防止 GeoFM embedding 在无 downstream lift 时被过度依赖。

### 4.9 因果校准层

因果校准层的任务不是替代统计因果推断，而是把 treatment-effect 证据接入 TWM 的 utility/reward。

推荐接口：

```text
calibrated_utility =
  model_utility_delta
  + f(estimated_treatment_effect, spatial_confounder_control, scenario_scale)
```

必须记录：

- treatment 定义。
- control 或 comparison baseline。
- 空间混杂控制方式。
- 观测支持度。
- 校准缺口。
- 是否存在外推。

当前工程中 `forecast.calibration` 已输出 `scenario_bias`、`treatment_effect`、`risk_pressure` 和 `calibrated_utility_delta`。后续需要接入 paper 6/7 中更正式的 treatment-effect estimator 或外部 causal inference tool。

### 4.10 Evidence gate 与 claim boundary

TWM 的 claim 升级规则建议如下：

| 等级 | claim 状态 | 最低证据要求 |
|---|---|---|
| L0 | unsupported | 只有模型输出，无足够数据、规则或校准证据 |
| L1 | state_prediction_supported | 未来状态预测在 holdout 上通过 |
| L2 | counterfactual_supported | 反事实 rollout 通过校准和证据 gate |
| L3 | planning_lift_supported | MPC/beam candidate ranking 或 planning lift 通过 |
| L4 | deployable_gis_supported | GIS 图层、规则、审计、人工复核闭环通过 |

任何未通过 gate 的输出都应标记为 `review_required`，不能写成确定性规划结论。

当前工程中：

- 单步 forecast 输出 `evidence_gate`。
- 反事实 rollout 聚合每一步的 gate，并输出整体 `evidence_gate.status`。
- audit report 检查 evidence item checksum。

### 4.11 Planner consumer 层

Planner 层负责消费 TWM，不定义 TWM。

可用 planner 包括：

- latent MPC。
- beam search。
- constrained rollout。
- action mask search。
- multi-objective candidate ranking。

Planner 输入：

- 当前层级状态 `S_t`。
- 可行动作集合 `A_t`。
- scenario `Z_t`。
- TWM 多头 forecast。
- 规则与硬约束。

Planner 输出：

- 候选方案集合。
- 每个候选方案的 forecast/rollout。
- 约束违背概率。
- 规划效用变化。
- 不确定性。
- evidence gate。
- GIS 图层/指标/审计报告。

论文 9 对这一层最重要：ArcGIS/MPC 的价值在于把世界模型输出转成可执行、可复核、可审计 GIS 工作流。

### 4.12 GIS 部署、审计与人机协同层

TWM 在 GIS Data Agent 中应以以下形式落地：

- API：项目、数据绑定、状态构建、规则评估、forecast、counterfactual rollout、audit report。
- Agent 工具：`twm_*` 工具供自然语言任务调用。
- GIS 输出：风险图层、规则命中清单、方案指标表、证据链报告。
- 人工复核：模型输出与法定规则/专家判断冲突时自动生成 review task。
- 可追溯：每个结论保留源数据、规则版本、模型版本、动作、情景、证据 checksum。

当前工程已经提供：

- `/api/twm/states/{id}/forecast`
- `/api/twm/states/{id}/counterfactual-rollout`
- `/api/twm/states/{id}/validation-report`
- `/api/twm/states/{id}/world-model-profile`
- `/api/twm/states/{id}/dynamics-training-examples`
- `/api/twm/states/{id}/audit-report`
- `twm_forecast`
- `twm_counterfactual_rollout`
- `twm_validation_report`
- `twm_world_model_profile`
- `twm_dynamics_training_examples`
- `twm_generate_audit_report`

### 4.13 验证阶梯

TWM 验证必须按以下顺序推进：

1. 状态构建验证：对象、关系、层级 token、质量摘要、证据链是否正确。
2. 未来状态预测验证：future latent state 和显式 GIS 指标是否能在时序 holdout 上预测。
3. 约束预测验证：规则违背概率是否校准。
4. 反事实 rollout 验证：干预与 baseline 的差异是否有 treatment/evidence 支撑。
5. 规划排序验证：candidate ranking 是否优于 baseline，是否降低 regret。
6. planning lift 验证：真实或高可信模拟环境中是否提升规划目标。
7. GIS 可部署性验证：图层、指标、审计、人工复核、版本追踪是否完整。
8. 跨区域/跨域验证：地理切分、域偏移、标签质量和 GeoFM gate 是否稳健。

### 4.14 当前实现与目标架构的对应关系

| 目标架构能力 | 当前状态 | 说明 |
|---|---|---|
| 层级对象-关系状态 | 已初步完成 | MMFE 语义包可构建 parcel/project/planning zone/evidence/review 等对象与关系 |
| 显式规则与证据链 | 已初步完成 | 默认规则、规则命中、checksum evidence、review task 和 audit report |
| action-conditioned forecast | 已初步完成 | `TerritoryWorldModelAction` 与多头 forecast 已存在 |
| 多头输出 | 已初步完成 | future latent state、constraint probability、utility delta、uncertainty、calibration、evidence gate |
| counterfactual rollout | 已补充 scaffold | baseline/intervention 多步 rollout 与 delta 输出已接入 service/API/toolset |
| validation ladder report | 已补充 scaffold | state build、future prediction、constraint prediction、counterfactual、planning lift、GIS deployability 分级证据报告 |
| functional world-model profile | 已补充 scaffold | 按 rendering、simulation、planning、closed loop、evidence/provenance 输出 TWM 能力画像 |
| dynamics training examples | 已补充 scaffold | 将 state/action/forecast/rule/evidence 组织成 future dynamics、constraint、ranking、calibration、uncertainty 训练样本契约 |
| action mask / execution gate | 已补充 scaffold | 从 target object、规则命中、review task、evidence checksum 自动生成 execution mask；高风险动作的 high/critical/blocking 命中可阻断 forecast claim |
| dynamics readiness report | 已补充 scaffold | 对训练样本量、usable 样本、observed temporal support、holdout、scaffold 依赖、review pressure、multi-head target 和 loss contract 做训练准入评估 |
| dynamics candidate evaluation | 已补充 scaffold | 对候选 dynamics 的 future latent、constraint、utility ranking、uncertainty、action mask 输出做 holdout 评估；缺真实 ground truth 时不升级 claim |
| dynamics candidate fit | 已补充 scaffold | 在 readiness gate 通过后拟合透明 hierarchical baseline dynamics，产出 candidate manifest、learned parameters、predictions，并自动进入 evaluation gate |
| dynamics forecast backend adapter | 已补充 scaffold | forecast、counterfactual rollout 和 validation consumer 可消费通过 gate 的 dynamics candidate report 并覆盖多头输出；review/blocked candidate 只进入 evidence gate，不升级预测 claim |
| constrained beam planning consumer | 已补充 scaffold | 多候选 action 逐个经过 forecast/dynamics/action-mask/evidence gate，按 utility-risk-confidence 排序，并输出可审计 ranking 与 selected candidate |
| hierarchical state contract report | 已补充 scaffold | 新增 `state_contract_report`，把 parcel/block/township/county token、explicit GIS feature、constraint channel、history delta、GeoFM gate 和 claim boundary 固化为统一输入契约；当前 township 仍可能停留在 review-level proxy |
| dynamics backend contract/adapter report | 已补充 scaffold | 新增 `dynamics_backend_report`，检查 backend 是否 action-conditioned、多头输出、证据门通过且可被 forecast/rollout/beam 消费；通过后包装为 candidate report，未通过时保持 review/blocked claim |
| training objective / multi-head loss report | 已补充 scaffold | 新增 `training_objective_report`，对 transition、constraint、ranking、calibration、uncertainty、action-mask、evidence-consistency 各损失项做覆盖度与 scaffold 数值审计，为后续 trainable dynamics trainer 提供统一 loss contract |
| trainable dynamics trainer scaffold | 已补充 scaffold | 新增 `train_dynamics_candidate`，消费 readiness、training objective 和 dataset，输出 trainable candidate report、backend report 与 objective report；当前仍是透明统计 trainer scaffold，不是最终神经世界模型 |
| trainable neural dynamics | 已补充三级候选后端 scaffold | 已接入本地 `torch_multi_head_mlp`、`torch_hierarchical_graph` 与 `torch_spatiotemporal_transformer` 三条 action-conditioned 多头 trainable candidate；graph 后端按 parcel/block/township/county token 分组编码并显式消费 history_delta/temporal transition 特征，进行轻量 relation + temporal message mixing；transformer 后端把 parcel/block/township/county、relation、temporal、action、scenario、context 编成固定语义 token 序列并做 self-attention 融合；三者均可通过 `train_dynamics_candidate` 输出 candidate/backend/objective 合同；但这些仍是小型候选实现，不是最终大规模 production graph/transformer 层级时空 dynamics 主干 |
| planning ranking loss | 部分完成 | 已有 training objective scaffold 与 ranking diagnostics；真正的训练优化和 learned ranking 仍未实现 |
| causal calibration backend | 已补充本地 estimator scaffold | 已新增本地 observational causal calibration backend，输出 stratified ATT、IPW、augmented IPW、overlap diagnostics、covariate balance diagnostics，以及空间邻域暴露/空间簇处理集中度/残差空间自相关等 spatial interference diagnostics，并由 evidence gate 控制是否可进入 forecast/planning 的 utility/scenario scale；当前仍是观测校准 scaffold，不是随机试验级因果识别，也尚未接 paper 6/7 的外部空间因果 estimator 服务 |
| GeoFM gate | 已补充 scaffold | 已有 B0/B1 downstream planning lift gate；仍需要扩展到 D2/D3/D4 和真实跨区实验管线 |
| GIS 部署闭环 | 部分完成 | API/toolset/audit 已有，ArcGIS/前端深度集成需继续 |

### 4.15 下一阶段实现优先级

1. 增强 training dataset builder：从更多历史状态、方案、规则命中、审批/复核和遥感变化生成可训练样本。
2. 将当前 `torch_hierarchical_graph` 与 `torch_spatiotemporal_transformer` 的轻量 token/message mixing 继续升级为真正的大规模图/Transformer 层级时空 dynamics optimizer，并保留现有 backend/objective/evidence gate 合同。
3. 扩展 GeoFM gate：显式 GIS-only baseline 已有 scaffold，后续补 D2/D3/D4 与真实 downstream 实验。
4. 升级 causal estimator：当前已有本地 augmented-IPW/stratified observational calibration backend 和 spatial interference diagnostics；下一步把 paper 6/7 的空间 treatment-effect estimator 接成可调用服务，并把地理邻近、空间干扰和跨区稳健性诊断从规则型 scaffold 升级为真实估计与显著性分析。
5. 扩展 planning consumer：多候选 beam scaffold 已有，后续补 latent MPC、空间 action mask 搜索与硬约束中止。
6. 做分层验证报告：future prediction、counterfactual、planning lift、GIS deployability 分开输出。
8. 用真实权威行政分级数据补足 township/block token，替换当前 review-level proxy。

## 5. 最终结论

这 12 篇材料共同指向的 TWM，不是一个重命名的传统预测器，也不是 GeoFM embedding、MPC 或 GNN 的简单包装。它应是一个以层级地理状态为核心、以 action-conditioned dynamics 为主干、以多头输出为接口、以因果校准和 evidence gate 控制 claim 边界、以 planner/GIS 工具链消费结果的地理空间世界模型。

用一句话概括：

> TWM 应该是一个能预测、能反事实、能规划、还能自证边界的地理空间世界模型；它的目标不是替代 GIS，而是把传统 GIS 从“图层管理与空间分析工具”推进为“状态推演、规划模拟、约束审计和证据闭环”的基础软件能力。
