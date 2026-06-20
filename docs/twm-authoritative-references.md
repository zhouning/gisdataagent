# TWM 论文写作可引用的权威理论与技术依据

本文档补充 `docs/twm-lineage-and-architecture.md`：前者来自用户提供的 12 篇论文/项目材料，本文列出 12 篇之外可支撑 Territory World Model, TWM 论文写作的权威文献来源。

核心判断：TWM 不能只引用传统 GIS/土地利用模拟文献，否则会被审稿人理解为“旧模型换名”。TWM 的参考文献结构应以世界模型、model-based RL、MPC/规划、因果推断、图/层级关系表征、GeoFM/遥感 foundation model、不确定性校准、证据门控和 GIS provenance 为主；传统土地利用模拟只能作为 baseline 和历史背景。

边界说明：本文档是“选题和引用骨架”，不是最终 BibTeX 文件。正式投稿前需要逐条核验作者、题名、年份、venue、DOI/arXiv ID，并按目标期刊格式导出参考文献。

## 1. 世界模型与 model-based RL 主线

这些文献支撑 TWM 的根本定义：模型学习环境状态转移，并服务于规划、反事实 rollout 和决策，而不是只做静态预测。

| 推荐引用 | 支撑 TWM 的内容 | TWM 中的对应设计 |
|---|---|---|
| Sutton, R. S. 1991. Dyna, an integrated architecture for learning, planning, and reacting. | 学习模型、规划和行动的统一框架。 | TWM 不是 planner 本身，而是为 planner 提供可推演模型。 |
| Ha, D. and Schmidhuber, J. 2018. World Models. | 用压缩 latent representation 和 learned dynamics 支持智能体行为。 | future latent state head、latent rollout。 |
| Hafner, D. et al. 2019. Learning Latent Dynamics for Planning from Pixels, PlaNet. | 从观测学习 latent dynamics 并用于 planning。 | 层级地理状态编码后的 latent dynamics。 |
| Hafner, D. et al. 2020. Dream to Control: Learning Behaviors by Latent Imagination, Dreamer. | 在 latent imagination 中学习行为。 | 多步 rollout、规划前模拟。 |
| Schrittwieser, J. et al. 2020. Mastering Atari, Go, Chess and Shogi by Planning with a Learned Model, MuZero. | 不显式还原环境规则，也可学习用于规划的模型。 | TWM 应优化 planning-relevant outputs，而不是只追求 reconstruction。 |
| Chua, K. et al. 2018. Deep Reinforcement Learning in a Handful of Trials using Probabilistic Dynamics Models, PETS. | 概率动力学 ensemble 与 trajectory sampling。 | uncertainty head、probabilistic rollout。 |
| Janner, M. et al. 2019. When to Trust Your Model: Model-Based Policy Optimization. | 模型误差边界决定 rollout 使用范围。 | evidence gate、rollout horizon gate。 |
| Hansen, N. et al. 2022/2024. TD-MPC / TD-MPC2. | learned latent dynamics + MPC 的现代连续控制路线。 | latent MPC/beam search 是 TWM consumer。 |

写作建议：这些文献应放在 TWM 引言和方法背景中，强调 TWM 与普通预测模型的区别是 action-conditioned dynamics + planning-oriented evaluation。

## 2. MPC、规划和 constrained decision making

这些文献支撑 TWM 的 planner consumer 层。TWM 论文里必须说明 MPC/beam/constrained rollout 是 consumer，不是世界模型本身。

| 推荐引用 | 支撑内容 | TWM 对应设计 |
|---|---|---|
| Camacho, E. F. and Bordons, C. Model Predictive Control. | MPC 的经典控制理论基础。 | receding horizon planning、约束下滚动优化。 |
| Rawlings, J. B. et al. Model Predictive Control: Theory, Computation, and Design. | MPC 的理论、计算和约束处理。 | constrained rollout、hard constraints。 |
| Williams, G. et al. 2017. Information Theoretic MPC / Model Predictive Path Integral Control. | sampling-based MPC。 | 多候选 rollout 与 soft utility ranking。 |
| Amos, B. and Kolter, J. Z. 2017. OptNet. | 可微优化层。 | 未来可把约束优化接入 trainable pipeline。 |

写作建议：MPC 文献不应单独支撑“TWM 是世界模型”，它支撑的是“如何消费 TWM 预测输出完成规划”。

## 3. 因果推断、反事实和 treatment-effect 校准

这些文献支撑 TWM 不能只学相关性，必须有 causal calibration。

| 推荐引用 | 支撑内容 | TWM 对应设计 |
|---|---|---|
| Rubin, D. B. 1974. Estimating causal effects of treatments in randomized and nonrandomized studies. | potential outcomes 框架。 | baseline/intervention counterfactual rollout。 |
| Rosenbaum, P. R. and Rubin, D. B. 1983. The central role of the propensity score. | 观测数据处理效应校准。 | observational calibration、scenario scale 修正。 |
| Pearl, J. 2009. Causality. | 结构因果模型、do-calculus、反事实。 | intervention 与 observation 的边界。 |
| Imbens, G. W. and Rubin, D. B. 2015. Causal Inference for Statistics, Social, and Biomedical Sciences. | 现代因果推断教材级依据。 | treatment/control/evidence 记录。 |
| Athey, S. and Imbens, G. 2016. Recursive partitioning for heterogeneous causal effects. | 异质处理效应。 | 不同地块/乡镇的 treatment effect 不应一刀切。 |
| Wager, S. and Athey, S. 2018. Estimation and inference of heterogeneous treatment effects using random forests. | causal forest。 | utility/reward calibration backend 候选。 |
| Chernozhukov, V. et al. 2018. Double/debiased machine learning. | 高维观测数据下因果参数估计。 | 遥感/GIS 高维协变量下的 treatment-effect 校准。 |

写作建议：TWM 的“反事实”不能只引用世界模型文献，还必须引用因果推断文献来定义 intervention 的证据边界。

## 4. 图网络、关系归纳偏置与层级状态

这些文献支撑 parcel/block/township/county 层级 token 和对象-关系状态。

| 推荐引用 | 支撑内容 | TWM 对应设计 |
|---|---|---|
| Battaglia, P. W. et al. 2018. Relational inductive biases, deep learning, and graph networks. | 对象-关系图是可学习系统建模的通用归纳偏置。 | `TwmStateObject` + `TwmStateRelation`。 |
| Kipf, T. N. and Welling, M. 2017. Semi-supervised classification with graph convolutional networks. | GCN 基础。 | 空间对象关系图上的信息传播。 |
| Velickovic, P. et al. 2018. Graph Attention Networks. | 注意力式图关系建模。 | action cross-attention 到目标对象与邻接对象。 |
| Bronstein, M. M. et al. 2017/2021. Geometric deep learning. | 非欧几里得结构上的深度学习。 | GIS 拓扑/邻接/包含关系建模。 |
| Sutton, R. S., Precup, D. and Singh, S. 1999. Between MDPs and semi-MDPs: options. | 时间抽象和层级动作。 | block/township 层级 action。 |
| Dietterich, T. G. 2000. MAXQ hierarchical reinforcement learning. | 层级任务分解。 | 县域目标与乡镇动作分解。 |
| Bacon, P. L. et al. 2017. The option-critic architecture. | 可学习 options。 | TWM 后续可学习区域级 macro-action。 |

写作建议：层级状态要引用 graph networks 和 hierarchical RL，而不是只说“GIS 图层很多，所以分层”。

## 5. 多智能体与县域/乡镇分解

这些文献支撑县域尺度下 township decomposition 和多主体动作空间。

| 推荐引用 | 支撑内容 | TWM 对应设计 |
|---|---|---|
| Lowe, R. et al. 2017. Multi-Agent Actor-Critic for Mixed Cooperative-Competitive Environments. | 多智能体 actor-critic。 | 多乡镇 agent 或区域 action。 |
| Rashid, T. et al. 2018. QMIX: Monotonic value function factorisation. | cooperative MARL 的 value decomposition。 | 县域总目标与乡镇局部目标汇总。 |
| Yu, C. et al. 2022. The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games, MAPPO. | cooperative MARL strong baseline。 | 与 shared-policy/MARL baseline 对照。 |
| Zhang, K. et al. 2021. Multi-Agent Reinforcement Learning: A Selective Overview. | MARL 综述。 | 引言背景和方法定位。 |

写作建议：如果 TWM 论文主打县域/乡镇层级，MARL 文献可作为动作空间分解的理论支撑，但 TWM 本身仍应以 world-model dynamics 为核心。

## 6. GeoFM、遥感 foundation model 与自监督表征

这些文献支撑 GeoFM embedding 的可控增强，而不是默认主干。

| 推荐引用 | 支撑内容 | TWM 对应设计 |
|---|---|---|
| He, K. et al. 2022. Masked Autoencoders Are Scalable Vision Learners. | MAE 自监督视觉表征基础。 | Prithvi/SatMAE 等 GeoFM 的方法根源。 |
| Cong, Y. et al. 2022. SatMAE: Pre-training Transformers for Temporal and Multi-Spectral Satellite Imagery. | 多时相多光谱遥感 MAE。 | GeoFM embedding 候选来源。 |
| Jakubik, J. et al. 2023/2024. Prithvi-100M / Foundation Models for Generalist Geospatial AI. | 遥感 foundation model。 | GeoFM state enhancement。 |
| Reed, C. J. et al. 2023. Scale-MAE. | 多尺度地理表征学习。 | parcel/block/township 跨尺度表征。 |
| Hong, D. et al. 2024. SpectralGPT. | 光谱遥感 foundation model。 | 多光谱/高光谱增强。 |
| Assran, M. et al. 2023. I-JEPA. | joint-embedding predictive architecture。 | GeoJEPA/TWM 的表示预测背景。 |
| Bardes, A. et al. 2024. V-JEPA. | 视频/时序 JEPA。 | future latent prediction 与非重构式预测。 |

写作建议：GeoFM 文献应用来说明“为什么可提供 state prior”，同时必须引用消融和 downstream planning 验证，避免把 GeoFM 写成自动有效。

## 7. 不确定性校准、选择性预测与 evidence gate

这些文献支撑 TWM 的 uncertainty head 和 evidence gate。

| 推荐引用 | 支撑内容 | TWM 对应设计 |
|---|---|---|
| Guo, C. et al. 2017. On Calibration of Modern Neural Networks. | 概率校准基础。 | constraint violation probability calibration。 |
| Lakshminarayanan, B. et al. 2017. Simple and Scalable Predictive Uncertainty Estimation using Deep Ensembles. | ensemble uncertainty。 | epistemic uncertainty。 |
| Ovadia, Y. et al. 2019. Can You Trust Your Model's Uncertainty Under Dataset Shift? | 域偏移下不确定性评估。 | geographic split、domain shift gate。 |
| Angelopoulos, A. N. and Bates, S. 2021. A Gentle Introduction to Conformal Prediction. | distribution-free uncertainty。 | coverage-risk 和 deployability gate。 |
| Geifman, Y. and El-Yaniv, R. 2017. Selective Classification for Deep Neural Networks. | 模型拒答/选择性预测。 | claim 不通过 gate 时进入 review_required。 |
| Geifman, Y. and El-Yaniv, R. 2019. SelectiveNet. | 集成 reject option 的神经网络。 | evidence gate 的理论类比。 |
| Mitchell, M. et al. 2019. Model Cards for Model Reporting. | 模型能力边界报告。 | TWM validation report。 |
| Gebru, T. et al. 2021. Datasheets for Datasets. | 数据集证据与边界。 | TWM source manifest、quality summary。 |

写作建议：evidence gate 不要只写成工程规则，应与 selective prediction、model cards、dataset datasheets 和 uncertainty calibration 关联。

## 8. Provenance、FAIR 与 GIS 可审计证据链

这些文献支撑 TWM 的 GIS audit、checksum evidence 和可追溯输出。

| 推荐引用 | 支撑内容 | TWM 对应设计 |
|---|---|---|
| Wilkinson, M. D. et al. 2016. The FAIR Guiding Principles for scientific data management and stewardship. | FAIR 数据原则。 | 数据来源、版本、可复用性。 |
| W3C PROV-DM, 2013. PROV Data Model. | provenance 标准。 | source -> rule -> model -> review 的证据链。 |
| Moreau, L. et al. 2011. The Open Provenance Model core specification. | provenance 建模基础。 | 审计图和证据链设计。 |
| ISO 19115 Geographic information metadata. | 地理信息元数据。 | GIS 数据资产 metadata。 |
| ISO 19157 Geographic information data quality. | 地理数据质量。 | quality summary、qa gate。 |

写作建议：如果 TWM 论文投遥感/GIS 期刊，provenance 和 ISO 质量标准会比纯 AI 文献更能支撑“可部署 GIS”的可信性。

## 9. 传统土地利用变化与空间模拟：作为 baseline，不作为 TWM 主干

这些文献应被引用为历史背景和实验 baseline，不能作为 TWM 创新的核心依据。

| 推荐引用 | 支撑内容 | TWM 中的定位 |
|---|---|---|
| Clarke, K. C., Hoppen, S. and Gaydos, L. 1997. SLEUTH urban growth model. | CA 城市增长模拟。 | 传统空间模拟 baseline。 |
| Verburg, P. H. et al. 2002. CLUE-S land-use change model. | 土地利用变化模型。 | 传统土地系统 baseline。 |
| Liu, X. et al. 2017. FLUS model. | future land use simulation。 | 用于对比单纯土地利用模拟。 |
| Liang, X. et al. 2021. PLUS patch-generating land use simulation. | patch-level land-use simulation。 | 与 TWM action-conditioned planning 区分。 |

写作建议：这些文献要明确说“它们擅长土地利用格局模拟，但通常不提供 action-conditioned causal calibration、多头 planning utility、evidence gate 和 GIS 审计闭环”。

## 10. 建议的论文参考文献结构

如果后续写 TWM 论文，建议参考文献按下面结构组织：

1. 第一段：GIS/自然资源治理需要从静态图层分析走向状态推演与规划模拟，引用传统土地利用模拟和 GIS provenance。
2. 第二段：AI 世界模型和 model-based RL 提供 action-conditioned dynamics 与 planning-oriented evaluation，引用 Dyna、World Models、PlaNet、Dreamer、MuZero、PETS/MBPO/TD-MPC。
3. 第三段：地理空间状态具有对象-关系-层级结构，引用 graph networks、GNN、hierarchical RL、MARL。
4. 第四段：遥感 GeoFM 提供 state prior，但必须 architecture-aware 和 downstream-gated，引用 MAE、SatMAE、Prithvi、Scale-MAE、SpectralGPT、I-JEPA/V-JEPA。
5. 第五段：规划收益不能只学相关性，必须引用 Rubin/Pearl/Rosenbaum-Rubin、causal forest、double ML 支撑 causal calibration。
6. 第六段：TWM 的可信落地依赖 uncertainty calibration、selective prediction、model cards/datasheets、FAIR/PROV/ISO metadata。

## 11. 最小核心引用包

如果篇幅有限，TWM 论文至少应引用：

- Sutton 1991 Dyna。
- Ha and Schmidhuber 2018 World Models。
- Hafner et al. 2019 PlaNet。
- Hafner et al. 2020 Dreamer。
- Schrittwieser et al. 2020 MuZero。
- Chua et al. 2018 PETS 或 Janner et al. 2019 MBPO。
- Rubin 1974 或 Pearl 2009。
- Rosenbaum and Rubin 1983。
- Battaglia et al. 2018 Graph Networks。
- He et al. 2022 MAE。
- Cong et al. 2022 SatMAE 或 Jakubik et al. Prithvi。
- Guo et al. 2017 calibration。
- Angelopoulos and Bates 2021 conformal prediction。
- Mitchell et al. 2019 Model Cards。
- Wilkinson et al. 2016 FAIR。
- W3C PROV-DM 2013。
- Verburg et al. 2002 CLUE-S 或 Liu et al. 2017 FLUS 作为传统 baseline。

## 12. 对 TWM 创新表述的约束

写论文时应避免以下表述：

- “首次将世界模型用于 GIS”这类过大声明，除非做系统综述确认。
- “GeoFM 直接提供地理世界模型”这类未经消融支持的声明。
- “MPC 就是 TWM”这类概念混淆。
- “预测准确即规划有效”这类被 model-based RL 文献反复否定的假设。

更稳妥的创新表述：

> We propose a geospatial world-model architecture that represents territorial planning states as hierarchical object-relation tokens, learns or approximates action-conditioned dynamics with multi-head outputs for future latent state, constraint risk, planning utility and uncertainty, and gates counterfactual/planning claims through causal calibration and GIS evidence provenance.
