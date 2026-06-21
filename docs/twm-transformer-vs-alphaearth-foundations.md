# TWM Transformer 与 AlphaEarth Foundations Transformer 对比

生成日期：2026-06-21

对比对象：

- TWM：`GIS Data Agent` 项目中的 `torch_spatiotemporal_transformer` 候选模拟器。
- 论文：`/Users/zhouning/Downloads/2507.22291v2.pdf`，标题为 *AlphaEarth Foundations: An embedding field model for accurate and efficient global mapping from sparse label data*。

## 一句话结论

两者都使用了 Transformer/self-attention 思路处理时空上下文，但不是同一层级、同一用途的模型。

TWM 里的 transformer 是一个面向国土空间规划推演的轻量世界模型候选后端，用来预测状态变化、约束风险、规划效用和行动可行性。AlphaEarth Foundations 里的 transformer/STP 架构是遥感基础表征模型的一部分，用来从海量多源遥感视频生成全球 10m 级 embedding field，服务 sparse-label mapping。

因此，二者的共同点主要在“时空 token 表征 + attention 融合”；本质差异在“任务目标、输入数据、训练规模、输出语义和生产定位”。

## 对照表

| 维度 | TWM transformer | AlphaEarth Foundations transformer/STP |
|---|---|---|
| 核心任务 | 作为 TWM 规划模拟器候选模型，服务自然资源/国土空间行动评估 | 作为遥感基础表征模型，生成全球 embedding field |
| 下游用途 | 约束风险预测、效用预测、行动可行性判断、planner 消费 | 低样本制图、分类、回归、变化检测 |
| 输入 | TWM 语义 token：parcel、block、township、county、relations、temporal、action、scenario、context | 多源遥感视频序列：Sentinel-2、Sentinel-1、Landsat 等，带 acquisition timestamp 和传感器元数据 |
| 时空处理 | 固定数量语义 token，经轻量 TransformerEncoder 融合 | STP encoder：space/time/precision 多路径，含 ViT-like spatial self-attention、time-axial self-attention 和 convolution |
| 时间条件 | `time_index`、period、temporal token、scenario context | support period、valid period、sinusoidal timecode，可做 temporal summary、插值和外推 |
| 输出 | 6 个规划模拟头：future area/state、constraint probability、utility delta、confidence、calibrated utility、action mask allowed | 64 维/64 层 embedding field，约束在球面 `S63`，再用于 sparse-label mapping |
| 训练目标 | 多头监督损失：transition、constraint、utility、confidence、calibration、action feasibility、ranking/temporal consistency | reconstruction、batch uniformity、teacher-student consistency、text contrastive |
| 训练规模 | 当前为本地 synthetic foundation 严格验证：128 treated examples、60 epochs | 8,412,511 video sequences，约 3.0B frames，512 TPU v4，100k steps |
| 当前定位 | TWM 开发验证中的轻量候选模型，不作生产就绪声明 | 论文定位为全球基础 embedding 模型/数据产品 |

## TWM 侧实现要点

当前 TWM transformer 实现在：

- `data_agent/territory_world_model/neural_dynamics.py`
- `scripts/run_twm_synthetic_experiment.py`

关键结构：

1. 使用固定语义 token 组织输入，包括 `parcel`、`block`、`township`、`county`、`relations`、`temporal`、`action`、`scenario`、`context`。
2. 每个 token 先经过线性编码、LayerNorm 和 ReLU。
3. token 序列进入 2 层 `TransformerEncoder`。
4. 输出经过 pooling 后进入 6 个预测头。
5. 风险头和 action-mask 可行性头支持 `context_residual` 模式，从 `action/context/temporal` token 读取额外上下文。
6. 当前 strict synthetic profile 使用 `hidden_dim=32`，transformer 训练 epoch floor 为 `60`。

最新严格验证结果记录在 `docs/twm-current-handoff.md`：

- raw transformer action mask：`false_allow=0`，`false_block=0`
- conditional high-risk subset：`false_allow=0`，`false_block=0`
- input leakage audit：`pass`，forbidden hits `0`
- planner holdout exact-match：`0.8125`
- planner mean regret：`0.007593`

这些结果仍属于 synthetic experiment，不应解读为生产部署能力证明。

## AlphaEarth Foundations 侧要点

论文中的 AlphaEarth Foundations 不是规划模拟器，而是遥感 embedding field 模型。

关键设计：

1. 输入是多源、多时间的地球观测数据，主要包括 Sentinel-2、Sentinel-1、Landsat 8/9 等。
2. 模型将观测的 timestamp 转为 sinusoidal timecode。
3. 通过 support period 和 valid period 分离“输入观测窗口”和“需要总结的时间窗口”。
4. STP encoder 同时维护：
   - space path：ViT-like spatial self-attention
   - time path：time-axial self-attention
   - precision path：3x3 convolution
5. embedding 被约束为 `S63` 上的方向向量。
6. teacher/student 共享参数，通过随机丢源、丢时间步、前后半段缺失等扰动训练缺测鲁棒性。
7. 训练目标包括多源重建、batch uniformity、teacher-student consistency 和 text contrastive。

论文规模远大于 TWM 当前模型：8,412,511 个 video sequences、3,047,520,515 个 frames、512 TPU v4、100k steps。

## 本质区别

### 1. 一个是基础表征模型，一个是规划世界模型候选

AlphaEarth Foundations 解决的是“如何从海量遥感观测中学习通用地球表征”。它输出 embedding field，下游再用 kNN、linear layer 等方法做 mapping。

TWM transformer 解决的是“给定某个规划行动和上下文，未来状态、约束风险、效用和行动可行性如何变化”。它直接输出 planner 可消费的模拟结果。

### 2. AlphaEarth 学的是遥感观测空间，TWM 学的是规划行动空间

AlphaEarth 的输入是传感器观测、时间戳和测量元数据。

TWM 的输入是规划对象、行政层级、行动类型、政策语义、风险上下文和时间索引。它关心的不是“这个像元长什么样”，而是“采取这个规划动作后，约束和效用如何变化”。

### 3. AlphaEarth 是预训练 embedding，TWM 是 action-conditioned simulator

AlphaEarth 的核心产物是可迁移 embedding。它本身不直接回答某个规划动作是否允许、是否后悔、是否触发审查。

TWM transformer 的输出里直接包含 `constraint_violation_probability`、`planning_utility_delta` 和 `action_mask.allowed`，这是规划模拟器的任务语义。

### 4. AlphaEarth 的时空建模更底层、更重；TWM 更业务语义、更轻

AlphaEarth 直接处理遥感视频和空间像素结构，架构和训练规模都更重。

TWM 当前处理的是已经结构化后的 GIS/TWM 语义摘要 token，模型轻量，便于在 agent 工作流中快速训练、验证和审计。

## TWM 可以借鉴 AlphaEarth 的地方

1. **引入遥感 foundation embedding 作为外部观测特征**  
   AlphaEarth/Google Satellite Embedding 这类 embedding 可以作为 TWM 的 GeoFM 特征输入，补充当前 GIS 语义 token。

2. **借鉴 support period / valid period 设计**  
   TWM 的规划模拟也可以明确区分“证据观测窗口”和“规划评估窗口”，尤其适用于年度变化、季节性耕地利用和工程建设时序。

3. **借鉴 teacher-student 缺测鲁棒训练**  
   自然资源数据常有缺失、云遮挡、时相不齐、审批记录不完整。TWM 后续可加入“完整证据 vs 缺证据”的一致性训练，而不是只依赖完整样本。

4. **借鉴 embedding uniformity / representation health 诊断**  
   TWM 当前有 leakage audit 和 action-mask diagnostics，未来可以增加 embedding collapse、token separability、跨区域泛化等表征健康检查。

5. **借鉴多源重建思想，但不能照搬目标函数**  
   AlphaEarth 重建遥感源；TWM 更应重建/预测规划状态、审查结果、约束命中和政策可行性。目标函数应围绕规划语义重写。

## 不应直接照搬的地方

1. 不应把 AlphaEarth 的 embedding field 模型直接叫作 TWM simulator。它没有 action-conditioned planning head。
2. 不应把 AlphaEarth 的低样本 mapping 表现等同于 TWM 的规划优化能力。
3. 不应把遥感重建 loss 直接替代 TWM 的 constraint/action-mask/planner regret 评估。
4. 不应在没有生产观测历史、审查记录和真实 holdout 的情况下，用 synthetic TWM 指标声称生产可用。

## 结论

TWM transformer 与 AlphaEarth Foundations transformer 在技术族谱上都属于 Transformer/self-attention 时空建模，但它们位于不同层级：

- AlphaEarth 是“遥感世界的基础表征层”。
- TWM transformer 是“规划决策世界模型的模拟层”。

更合理的集成路线不是替换，而是分层耦合：

1. 用 AlphaEarth/GeoFM embedding 增强 TWM 的观测表征。
2. 由 TWM transformer 学习 action-conditioned transition、constraint、utility 和 feasibility。
3. 用 TWM 的 leakage audit、conditional high-risk diagnostics、planner regret 和真实 holdout 验证规划可用性。

这样，AlphaEarth 提供“看懂地表”的能力，TWM 提供“评估规划行动后果”的能力。

