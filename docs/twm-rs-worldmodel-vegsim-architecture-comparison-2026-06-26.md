# TWM 与 RS-WorldModel、VegSim 及既有 12 篇论文的核心架构对比

日期：2026-06-26

## 0. 范围与证据边界

本文分析两篇新增论文：

1. `/Users/zhouning/Downloads/2603.14941v1.pdf`
   - 题名：RS-WorldModel: a Unified Model for Remote Sensing Understanding and Future Sense Forecasting
   - arXiv：2603.14941v1
   - 核心任务：遥感时空变化问答（ST-CQA）与文本引导未来场景生成（TFSF）
2. `/Users/zhouning/Downloads/2606.21961v1.pdf`
   - 题名：VegSim: A Geospatial World Model for Scenario-Conditioned Vegetation Simulation
   - arXiv：2606.21961v1
   - 核心任务：在可控未来气象 forcing 下做 NDVI 植被情景模拟

本文对照的 TWM 资料主要包括：

- `docs/twm-lineage-and-architecture.md`
- `docs/twm-current-handoff.md`
- `docs/twm-technical-review-2026-06-25.md`
- `docs/superpowers/specs/2026-06-15-territorial-world-model-design.md`
- `data_agent/territory_world_model/models.py`
- `data_agent/territory_world_model/planner.py`
- `data_agent/territory_world_model/neural_dynamics.py`
- `data_agent/territory_world_model/claim_ladder.py`

“之前 12 篇论文”的口径采用 `docs/twm-lineage-and-architecture.md` 中的谱系表：论文 1、2、3、4、58、6、7、9、10、11、12、13。严格说该表有 12 个材料条目，但编号中包含 `58` 和 `13`，不是自然连续的 1-12。

## 1. 一句话结论

RS-WorldModel 是遥感 VLM/生成式统一模型，强在多模态理解与未来影像生成；VegSim 是更接近 world model 原义的“状态 + 外部 forcing + latent rollout + 不确定性”的轻量动力学模型；TWM 则是治理型地理空间 world model，核心不在生成影像或单变量 NDVI，而在层级 GIS 对象-关系-规则-证据状态、治理动作条件推演、多头风险/效用/不确定性输出、因果校准、planner consumer 和 claim-evidence gate。

因此：

- RS-WorldModel 可以为 TWM 提供遥感元数据 token 化、遥感理解-预测联合训练、verifiable reward 的启发，但不能替代 TWM 的对象化治理状态和证据门控。
- VegSim 对 TWM 更有直接架构价值，尤其是可控外部 forcing、显式 latent rollout、quantile uncertainty、observed-forcing validation before perturbed-forcing simulation、以及“条件模拟不是因果估计”的边界表述。
- TWM 目前在治理闭环和证据边界上比两篇新论文更强，但在真实训练数据规模、连续时序动力学、概率不确定性和完整 latent state head 上仍弱于论文式模型。

## 2. 术语表

| 术语 | 本文采用的含义 |
|---|---|
| TWM | Territory World Model，面向国土空间治理的层级地理空间世界模型 |
| RS-WorldModel | 面向遥感理解与未来影像生成的统一 VLM/生成式模型 |
| VegSim | 面向植被 NDVI 情景模拟的 geospatial world model |
| ST-CQA | Spatiotemporal Change Question-Answering，遥感时空变化问答 |
| TFSF | Text-Guided Future Scene Forecasting，文本引导未来遥感场景生成 |
| forcing | 外部驱动序列；VegSim 中主要是未来气象变量，TWM 中可扩展为政策、市场、人口、气候、工程扰动等情景条件 |
| action | TWM 中的治理干预动作，如选址、整治、保护、审批、规划调整；不是 VegSim 的气象 forcing，也不是 RS-WorldModel 的文本 prompt |
| evidence gate | TWM 的证据门控，决定模型输出能否升级为 claim |

## 3. 两篇新增论文的核心架构

### 3.1 RS-WorldModel

RS-WorldModel 的核心架构可以概括为：

```text
fMoW 多时相遥感图像 + 地理/成像元数据
        ↓
RSWBench-1.1M 自动标注与 refinement
        ↓
MoVQGAN 图像离散视觉 token
        ↓
Qwen3-VL-2B-Instruct autoregressive mixed-token model
        ↓
Stage 1: Geo-Aware Generative Pre-training
Stage 2: Synergistic Instruction Tuning
Stage 3: Verifiable Reinforcement Optimization
        ↓
文本答案（ST-CQA）或未来影像 token（TFSF）
```

关键设计点：

- 把 ST-CQA 和 TFSF 统一为 instruction-conditioned sequence generation，即 `p(y | prompt, image, metadata)`。
- 用 MoVQGAN 把 256×256 遥感图像转为离散视觉 token，文本 token 与视觉 token 共用自回归 next-token objective。
- 地理坐标、GSD、时间戳、太阳角、off-nadir、云量等元数据被序列化为专用 token。
- 训练分三阶段：
  - GAGP：只用当前图像与目标元数据预测目标图像 token，学习 geo-aware generation prior。
  - SIT：把变化问答与未来生成混合做 instruction tuning。
  - VRO：用 GRPO 做 verifiable reinforcement optimization，TFSF 奖励来自图文一致性与参考图像一致性，ST-CQA 奖励来自 LLM-as-a-judge。
- 输出是自然语言变化解释或生成式未来遥感影像，不是 GIS 对象状态、规则命中、约束风险或规划效用。

它的“world model”更接近“遥感视觉语言生成器内化了地理/成像变化先验”，而不是显式状态转移模型。它没有显式的 action space、constraint head、planner consumer、GIS audit、human review gate。

### 3.2 VegSim

VegSim 的核心架构可以概括为：

```text
Sentinel-2 B04/B8A -> NDVI 稀疏历史序列
每日气象变量 + 工程化累计气象特征
经纬度 + Köppen-Geiger 气候区
        ↓
History Transformer encoder + learned-query pooling -> 初始 latent state z0
Future forcing Transformer encoder + lead-time embedding -> future tokens
Spatial encoder -> static spatial context
        ↓
GRU latent dynamics:
zk = GRUCell(MLPin([future_token_k, spatial_context, lead_time_k]), z(k-1))
        ↓
shared MLP decoder
        ↓
NDVI quantiles: 0.1 / 0.5 / 0.9
```

关键设计点：

- 输入历史是稀疏、非均匀的 clear-sky NDVI 序列；未来 forcing 是每日气象协变量。
- 状态是单个 minicube 的 latent vegetation state，不是图斑/规则/项目的治理状态。
- 未来气象 forcing 是可替换的 controllable input；推理时改变 forcing 即可做 scenario-conditioned simulation。
- 训练目标是 temporally weighted pinball loss，加 quantile non-crossing penalty。
- 输出是 NDVI 分位数，天然带概率不确定性。
- 验证逻辑很严谨：因为扰动情景没有 ground truth，所以先用 observed future forcing 验证模型能否复现真实轨迹，再把同一动力学用于 perturbed forcing。
- 作者明确说 scenario rollout 是 conditional simulation under distributional shift，不是 weather variables 的 causal effect estimate。

VegSim 比 RS-WorldModel 更接近 TWM 的动力学范式，因为它显式分离了历史状态、外部条件、latent rollout 和不确定性输出。但它的对象粒度、任务目标和治理约束都比 TWM 窄。

## 4. TWM 当前核心架构

根据当前文档和代码，TWM 的目标架构是：

```text
权威/公开/脱敏 GIS 数据 + MMFE semantic bundle + 规则/证据/历史版本
        ↓
层级 GIS 状态：
parcel / block / township / county
object + relation + rule + evidence + history + quality
        ↓
state encoder + optional GeoFM gate
        ↓
治理 action + scenario
        ↓
action-conditioned multi-head dynamics
        ↓
future state / constraint risk / utility delta / uncertainty / calibration / action mask / evidence gate
        ↓
MPC / beam / constrained rollout planner consumer
        ↓
GIS 图层、规则命中、方案指标、审计报告、人工复核
```

当前工程已经实现或具备 scaffold 的能力：

- `TwmStateObject`、`TwmStateRelation`、`TwmPolicyRule`、`TwmRuleHit`、`TwmEvidenceItem`、`TwmReviewTask` 等对象-关系-规则-证据契约。
- `TerritoryWorldModelAction` 中已有 action type、target role、target objects、spatial scope、magnitude、scenario、legal intent、execution mask、treatment。
- `TerritoryWorldModelForecast` 中已有 future latent state、constraint violation probability、planning utility delta、uncertainty、calibration、evidence gate。
- `TerritoryWorldModelPlanner` 明确是 consumer，不是 world model 本体。
- `claim_ladder.py` 定义 L0-L4 claim upgrade：state prediction、counterfactual、planning lift、deployable GIS，每一级都有 gate。
- 神经候选 backend 包括 MLP、hierarchical graph、spatiotemporal transformer，但当前仍是 candidate/scaffold。

需要严肃保留的边界：

- 当前 `future_latent_state` 在神经训练目标中仍主要是 compact area-level proxy，不是完整 parcel geometry/state latent。
- 当前因果校准主要是 observational calibration，不等于干预性因果识别。
- 当前真实生产审批/复核/政策动作可行性数据仍缺失，不能升级 production-ready 或 blanket superiority claim。

## 5. 与既有 12 篇论文谱系的关系

| 材料 | 核心架构贡献 | 与两篇新论文的关系 | 对 TWM 的含义 |
|---|---|---|---|
| 论文 1：耕地布局 DRL | 规划单元、硬约束、action mask、迁移验证 | 比 RS/VegSim 更接近治理动作，但缺 world dynamics | TWM 保留 action mask，不停留在 model-free policy |
| 论文 2：地籍合成基准 | 不规则图斑、稀疏奖励、algorithm gate | 两篇新论文都没有 algorithm-selection gate | TWM 应防止“凡事 world model 化” |
| 论文 3：block-level DRL | 宏观规划与微观执行分离 | VegSim/RS 都没有 parcel-block 层级治理状态 | TWM 的层级 token 来源之一 |
| 论文 4：县域 MARL | township decomposition、多智能体/多区域动作 | VegSim 是单 minicube latent，RS 是图像样本级 | TWM 需要县域-乡镇跨尺度耦合 |
| 论文 58：GeoFM world-model RL | GeoFM embedding + lightweight dynamics 的边界 | RS-WorldModel 更像大 VLM/GeoFM 主体，VegSim 不依赖 GeoFM | TWM 应保持 GeoFM gate，而非默认主干 |
| 论文 6：空间因果推断 | confounder、treatment effect、反事实边界 | VegSim 明确“不做因果估计”，RS 基本无因果层 | TWM 的反事实 claim 必须受 causal/evidence gate 限制 |
| 论文 7：causal MBRL | action-conditioned transition + reward calibration | VegSim 有 forcing-conditioned rollout，但不是治理 action | TWM 的核心动力学合同主要来自这里 |
| 论文 9：ArcGIS MPC | planner consumer、GIS audit、硬约束执行 | 两篇新论文都没有 GIS 审计部署层 | TWM 不能把 planner 或生成器等同于 world model |
| 论文 10：GeoJEPA-MPC | monitor-gated value labels、claim-evidence map | RS 的 VRO 可借鉴“可验证奖励”，但不是证据门控 | TWM 的 claim gate 应保留一等公民地位 |
| 论文 11：GeoFM suitability RL | B0/B1 消融、one-step fit 不等于 planning lift | RS 的大模型指标不能直接代表 planning lift | GeoFM/VLM 只能在下游规划证据通过后启用 |
| 论文 12：AlphaEarth/Prithvi 适配 | 架构感知 PEFT、地理切分、域偏移 | RS 用 Qwen3-VL，VegSim 用小模型；二者都强调 split/generalization | TWM 接入 foundation model 要做架构审计和地理 holdout |
| 论文 13：future-aware planning | future state、非循环验证标签、evidence gate | VegSim 的 future rollout 可启发 TWM；RS 的 future image 不等于 planning future | TWM 验证必须先 future-state，再 counterfactual，再 planning lift |

总体看，12 篇旧论文给 TWM 提供的是治理规划、动作、约束、因果、审计、GeoFM gate、planner consumer 的谱系；两篇新论文主要补充遥感世界模型和生态/气象情景模拟的技术参照。

## 6. 四类架构同轴对比

| 维度 | RS-WorldModel | VegSim | TWM | 既有 12 篇谱系 |
|---|---|---|---|---|
| 状态单位 | 遥感图像 token + 元数据 token | minicube NDVI latent state | parcel/block/township/county 对象-关系-规则-证据状态 | 从 parcel 到 block/township/county 逐步升级 |
| 空间结构 | 隐式在视觉 token 与元数据中 | 经纬度 harmonic + 气候区 embedding | 显式 geometry、relation、行政层级、规则覆盖 | 图斑、区块、县域、多乡镇 |
| 时间结构 | pre/post 或当前/目标时相 | 稀疏历史 NDVI + dense future forcing | 状态版本、历史差分、年度变化、rollout horizon | future-aware planning 与时序 holdout |
| 条件输入 | prompt、图像、目标元数据、文本 instruction | 未来气象 forcing、lead time、空间上下文 | 治理 action、scenario、rule version、evidence quality、calibration context | action mask、MPC action、treatment/context |
| 动力学 | 自回归 mixed-token generation | GRU latent rollout under forcing | action-conditioned multi-head dynamics | causal MBRL、world-model RL、MPC |
| 输出 | 文本解释或未来遥感影像 | NDVI quantiles | future state、constraint risk、utility delta、uncertainty、calibration、evidence gate | 规划效用、约束、ranking、审计 |
| 不确定性 | 主要靠评估指标和 VRO，不是显式概率 head | 0.1/0.5/0.9 quantile，CRPS/pinball | 已有 uncertainty 字段，但概率校准仍需加强 | uncertainty/calibration 是后期谱系要求 |
| 因果边界 | 基本不处理因果 | 明确不是 causal estimate | 观测因果校准 + evidence gate，仍需真实 treatment support | 论文 6/7 是核心来源 |
| 证据审计 | 数据构造和 judge prompt 可追溯，但无 GIS audit | 有 observed-forcing validation 与误差诊断，无审计链 | evidence item、checksum、review task、claim ladder | 论文 9/10/13 支撑 |
| planner | 无 | 无，只做 scenario simulation | planner 是 consumer：MPC/beam/constrained rollout | 论文 9 明确 planner 边界 |
| 适合吸收的点 | 元数据 token、联合理解-预测、可验证奖励 | forcing 分离、quantile head、扰动协议、非因果标注 | 保持治理闭环 | 作为 TWM 的本体谱系 |

## 7. 关键相同点

1. 三者都承认地理空间任务不能只看像素或属性，必须引入位置、时间、观测条件或上下文。
2. 三者都面向“未来”：RS-WorldModel 生成未来遥感影像，VegSim rollout 未来 NDVI，TWM 推演治理动作后的未来状态/风险/效用。
3. 三者都不是单纯静态分类器：RS 是自回归生成，VegSim 是 latent recurrent rollout，TWM 是 action-conditioned rollout/planning consumer。
4. VegSim 与 TWM 都强调 scenario/conditioned rollout 的边界。VegSim 明确“不等于因果效应”，TWM 用 causal/evidence gate 限制反事实 claim。
5. RS-WorldModel、VegSim 和 TWM 都需要地理切分/时序 holdout 证明泛化，而不能只看随机样本分割。

## 8. 关键差异

### 8.1 RS-WorldModel 与 TWM 的差异

RS-WorldModel 的 action 本质是 prompt/instruction，不是治理动作。它能生成“指定目标时间和成像条件下的遥感图像”，但不能回答“某个建设项目选址是否触碰永久基本农田、若采取整治动作未来规则风险和规划效用如何变化、证据能否升级为审计 claim”。

RS-WorldModel 的输出是 token 级语言/影像，TWM 的输出是 GIS 可消费的 forecast、rule hit、risk layer、scenario metric、review task 和 audit report。

因此 RS-WorldModel 适合作为 TWM 的遥感感知/生成候选组件，不适合作为 TWM 本体。

### 8.2 VegSim 与 TWM 的差异

VegSim 的核心强项是把 future weather 作为 controllable forcing，并用同一个 trained dynamics 做 observed forecasting 与 perturbed simulation。这非常接近 TWM 应有的 scenario layer。

但 VegSim 不是治理模型：

- 没有图斑、项目、审批、红线、用途管制、规划分区等对象。
- 没有 rule DSL、hard constraint、action feasibility、human review。
- 没有 utility delta、planning ranking 或 planner consumer。
- 没有 claim ladder 或 GIS audit。

所以 VegSim 是 TWM 的“环境/生态过程后端”范式参考，而不是完整 TWM。

### 8.3 两篇新论文与 12 篇旧论文的差异

两篇新论文来自遥感/生态时序建模主线，强调感知、生成、外部自然 forcing 和泛化评估；12 篇旧论文来自耕地/国土规划优化主线，强调动作、约束、因果、MPC、审计、GeoFM gate 和生产验证边界。

TWM 的本体仍应以 12 篇旧论文谱系为主，两篇新论文作为补强：

- RS-WorldModel 补强遥感理解与未来影像生成。
- VegSim 补强外部 forcing、概率 rollout 和场景扰动协议。

## 9. 建议吸收进 TWM 的设计

### 9.1 从 RS-WorldModel 吸收

1. **地理与成像元数据 token 化**
   - 可用于 TWM 的遥感证据通道：时间戳、太阳角、云量、off-nadir、GSD 等不应只放在 metadata 里，应进入可计算状态或 evidence item。
2. **理解与预测联合训练**
   - TWM 可把 rule explanation、change caption、future-state prediction、risk explanation 做多任务训练，但输出仍要受 evidence gate 约束。
3. **verifiable reward 思路**
   - 可借鉴 VRO，但 TWM 的 judge 不应替代法定规则或人工复核。它只能用于训练解释质量、元数据一致性和报告可读性。
4. **自动标注 + refinement pipeline**
   - 可用于生成遥感变化解释训练集，但所有自动标注必须带 provenance 和 low-confidence 标记，不能充当权威审批标签。

### 9.2 从 VegSim 吸收

1. **把 scenario forcing 明确建模为一等输入**
   - TWM 当前 scenario 仍偏元数据，应扩展为结构化 forcing：政策版本、人口/市场、气候/生态、建设压力、遥感观测条件、治理资源约束。
2. **observed-forcing validation before perturbed-forcing simulation**
   - TWM 做政策/气候/市场扰动前，必须先证明在 observed history 上能预测真实状态变化。
3. **概率输出与 quantile head**
   - TWM 目前有 uncertainty 字段，但可以增加 quantile/conformal coverage，让风险和效用不只是点估计。
4. **lead-time embedding 与不规则时间间隔**
   - 自然资源状态版本不一定等距，TWM 应显式建模 `delta_t`，而不是默认年度等间隔。
5. **场景扰动协议**
   - VegSim 对 additive/multiplicative perturbation、时间窗口、物理单位归一化的处理可迁移到 TWM 的 policy/climate/market scenario perturbation。
6. **非因果声明模板**
   - TWM 所有未通过因果 gate 的 rollout 应显式标注为 conditional simulation，不得写成 causal effect。

## 10. 不应吸收或需要警惕的点

1. 不应把 RS-WorldModel 式“生成未来图像”直接包装成 TWM 的治理预测。图像 plausibility 不等于规划合法性、审批可行性或治理收益。
2. 不应让 LLM-as-a-judge 升级为 TWM 证据 gate。LLM judge 可以辅助训练和解释评分，但不能替代规则条款、源数据、空间计算和人工复核。
3. 不应把 VegSim 的气象 forcing 等同于 TWM action。forcing 是外部条件，action 是治理干预，两者在 TWM 中都需要，但语义不同。
4. 不应用两篇新论文的 benchmark 指标为 TWM 背书。它们证明的是各自任务上的能力，不证明 TWM 在国土治理中的 planning lift。
5. 不应因为 RS-WorldModel 使用 1.1M 样本就低估 TWM 的结构化治理价值；但也不能忽视 TWM 当前真实生产训练数据不足的问题。

## 11. 对 TWM roadmap 的具体影响

建议把两篇新论文吸收到 TWM roadmap 的方式如下：

| 优先级 | 建议事项 | 来源 | 目标 |
|---|---|---|---|
| P0 | 在 TWM scenario schema 中区分 `action` 与 `forcing` | VegSim + 论文 7 | 避免治理干预与外部情景混淆 |
| P0 | 所有 counterfactual/perturbed rollout 默认输出 `identification_strength` | VegSim + 论文 6/7 | 明确 conditional simulation vs causal estimate |
| P1 | 增加 observed-history validation gate：先验证 observed forcing，再允许 perturbation claim | VegSim | 降低情景模拟 overclaim |
| P1 | 增加 quantile/conformal uncertainty 输出 | VegSim | 让 risk/utility 具备概率覆盖语义 |
| P1 | 把遥感观测元数据纳入 evidence/state contract | RS-WorldModel | 提升遥感变化解释可信度 |
| P2 | 建设遥感变化理解/预测辅助数据集，但标记自动标注来源 | RS-WorldModel | 支撑 TWM 的遥感 evidence enrichment |
| P2 | 用 verifiable reward 训练解释文本，而不是训练审批结论 | RS-WorldModel | 提升报告质量但不越权 |
| P2 | 将生态/植被/气候模块做成 TWM dynamics backend 插件 | VegSim | 支持生态红线、耕地质量、植被风险类情景 |

## 12. 最终判断

这两篇新论文不会改变 TWM 的主路线。TWM 仍应定位为 governance-oriented geospatial world model，而不是 remote sensing generation model 或 vegetation forecasting model。

但它们会强化 TWM 的两个薄弱点：

1. RS-WorldModel 提醒 TWM：遥感观测条件、元数据、变化解释和未来影像生成可以成为强大的 evidence enrichment 通道。
2. VegSim 提醒 TWM：真正像 world model 的情景模拟必须显式分离历史状态、未来 forcing、latent rollout、概率不确定性和因果边界。

更准确的吸收策略是：

> TWM 的主体继续沿 12 篇旧论文形成的 action-conditioned governance world model 路线推进；RS-WorldModel 作为遥感理解/生成组件候选，VegSim 作为环境 forcing 与概率 rollout 后端范式候选。两者都进入 TWM 的模块库和验证路线，但都不替代 TWM 的对象-关系-规则-证据状态、planner consumer、claim ladder 与 GIS audit。
