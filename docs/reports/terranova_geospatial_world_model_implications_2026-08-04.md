# TerraNova 对 GIS Data Agent Geospatial World Model 的启发

日期：2026-08-04
论文：Carlos Rodriguez-Pardo, Massimo Tavoni, *TerraNova: A Foundation Model for the Anthropocene*
论文版本：arXiv:2607.29527v1，2026-07-31
本地论文：`/Users/zhouning/Downloads/2607.29527v1.pdf`

## 0. 核心结论

TerraNova 对 GIS Data Agent 最重要的启发，不是把当前 Geospatial Kernel 扩大成一个覆盖整个地球、社会和治理过程的统一模型，而是为现有 action-conditioned geospatial dynamics 增加一个独立的：

> **跨几何、跨变量、带不确定性的 Geospatial Foundation State Prior。**

TerraNova 主要学习：

```text
(task, location/country, time)
-> variable predictive distribution
```

GIS Data Agent 的 Geospatial Kernel 真正需要学习：

```text
(state, action, forcing, topology)
-> next-state distribution
```

因此，TerraNova 类模型适合作为世界状态重建、缺测补全、新变量适配和跨几何信息融合的上游表示层，不适合替代现有的行动条件状态转移、物理传播、因果校准、递归写回和规划评测。

## 1. TerraNova 解决了什么问题

TerraNova 将物理地球与人类社会的联合建模重新表述为一个多几何表示学习问题：

- 环境、气候和生态变量通常是连续栅格场；
- 经济、治理、人口和社会变量通常记录在行政区边界内；
- 将栅格聚合到行政区会丢失区内差异；
- 将行政统计栅格化会制造不存在的空间精度。

TerraNova 没有预先把两类数据转换成同一种几何，而是在原生几何中训练：

- 512 个 0.25 度 gridded Earth-system fields；
- 512 个 country-level indicators；
- location、country、time 和 task 专用编码器；
- cross-modal transformer 形成共享时空状态；
- hypernetwork 为每次查询生成 task-conditioned decoder；
- Normal-Inverse-Gamma head 输出预测分布；
- country-location contrastive alignment 连接行政区和境内坐标；
- external geospatial alignment 引入 SatCLIP、GeoCLIP 和 Copernicus 等视觉地理语义。

它取得的主要能力包括：

- 从少量空间观测重建稠密场；
- 通过少量标签适配未见变量；
- 在国家和坐标之间执行 cross-geometry retrieval；
- 将部分国家级变量的空间先验下推到栅格；
- 对每次查询输出经过校准的预测区间。

## 2. 与 GIS Data Agent GWM 的根本区别

| 维度 | TerraNova | GIS Data Agent Geospatial Kernel |
|---|---|---|
| 核心问题 | 多变量、多几何观测的共享表示 | 有界空间环境中的行动条件状态转移 |
| 主要输入 | task、coordinate/country、time | state、action、forcing、topology、context |
| 主要输出 | 某变量在某时空位置的预测分布 | 下一状态、状态增量、关系变化和不确定性 |
| 时间机制 | 时间编码、插值和潜空间 transport | 多步递归演化、状态写回和时滞传播 |
| 行动 | 不建模 | 必须显式进入转移模型 |
| 空间关系 | 坐标与国家边界的软对齐 | 邻接、上下游、包含、网络和动态拓扑 |
| 因果能力 | 明确不支持 | 仅在额外识别、负对照和证据门通过后形成有界主张 |
| 最适合的系统角色 | observation/state prior | domain transition model/runtime kernel |

两者的正确关系不是替代，而是组合：

```text
TerraNova-like representation
-> 提供初始状态先验、背景上下文和缺测补全
-> Geospatial Kernel 消费该状态
-> 在 action、forcing 和 topology 条件下推演下一状态
```

## 3. 对现有架构的五项直接启发

### 3.1 原生几何应成为一等数据合同

当前 `UwmCanonicalObservation.v1` 已经区分：

- `spatial_units`；
- `object_layers`；
- `raster_features`；
- `graph_edges`；
- `temporal_index`；
- `provenance` 和 `claim_boundary`。

但 renderer 当前主要保留对象类型、角色和数据集 ID，尚未完整表达每个变量实际的 measurement support。建议为每个观测变量增加：

```text
geometry_type:
  point | raster | polygon | network | volume

spatial_support:
  sensor_footprint | grid_cell | parcel | admin_unit | reach | catchment

resolution:
  spatial_resolution + temporal_resolution

aggregation_semantics:
  count | mean | total | density | rate | category | stock | flow

observation_semantics:
  observed | interpolated | downscaled | simulated | proxy

calibration_and_evidence:
  uncertainty + provenance + valid_time + claim_ceiling
```

这样可以避免在进入模型前丢失行政区、栅格、宗地、传感器和网络观测之间的语义差异。

### 3.2 在 dynamics 之前增加 Foundation State Prior

推荐的目标架构为：

```text
Raster / Admin / Parcel / Sensor / Network observations
                         |
                         v
       Geometry-specific encoders and soft alignment
                         |
                         v
         Geospatial Foundation State Prior Z_t
                         |
                current observation assimilation
                         |
                         v
             task-bounded world state S_t
                         |
       +-----------------+------------------+
       |                 |                  |
     action A_t       forcing C_t       topology G_t
       |                 |                  |
       +-----------------+------------------+
                         |
                         v
          Domain-specific Geospatial Kernel
                         |
                         v
                 P(S_t+1), G_t+1
                         |
                         v
       conformal calibration + Evidence Gate
                         |
                         v
                  rollout / planner
```

`Z_t` 只能作为状态先验或 context，不能自动升级为真实观测。其推断值必须携带 `observed_vs_inferred`、空间支撑、预测区间和 evidence grade。

### 3.3 用于小样本状态重建，而不是替代动作动力学

TerraNova 在稀疏测量条件下表现出较强的空间先验：在每 4,096 个栅格单元仅保留一个观测的设置中，其平均 held-out `R2` 约为 0.74，最佳传统插值约为 0.56。

这一能力可以对应 GIS Data Agent 当前的真实缺口：

- UWM：从稀疏监测站重建热环境、污染、人口暴露和公共服务场；
- TWM：联合行政统计、遥感场、宗地对象和规划单元形成较完整的初始状态；
- WWM：提供气候、地形、土地覆盖和人类活动背景上下文。

但它不能补齐：

- 精确时间戳的控制动作；
- 动作后的独立 outcome；
- 小时级河道初始状态；
- 真实未来 forcing；
- 河网守恒和水动力边界；
- 行动响应的可识别性。

因此，应用优先级应为：

```text
UWM > TWM >> WWM
```

其中 WWM 的 0.25 度年度背景变量与小时级水库和河道路由之间存在明显的尺度不匹配。

### 3.4 采用软对齐，不采用强制数值一致

TerraNova 的补充实验显示：

- country-location contrastive alignment 能显著建立跨几何检索能力；
- 移除该对齐后，coordinate-to-country retrieval 降到随机水平；
- national-to-gridded downscaling 同时退化到平坦国家均值基线；
- 但强制国家预测等于境内坐标预测均值的 consistency loss 会降低重建性能。

这对 GIS Data Agent 的含义是：

- 行政区、宗地、栅格、设施和网络节点可以在潜空间建立语义邻接；
- 不同 measurement support 上的数值不能被强制视为相等；
- 对齐权重应由任务语义决定，例如人口、面积、土地类型、汇水贡献或可达性；
- 下推结果必须标记为 inferred spatial prior，不能伪装成细粒度观测。

外部 teacher 也必须携带 support boundary。TerraNova 的 EO teachers 只在陆地提供监督，其收益在海洋目标上基本消失，说明 teacher 的覆盖边界会直接限制蒸馏收益。

### 3.5 将预测不确定性与 Evidence Gate 合并

TerraNova 的 evidential head 并非即插即用：

- 原始 unseen-task intervals 系统性过宽；
- 论文使用每任务 split-conformal multiplier 恢复目标覆盖率；
- aleatoric 和 epistemic 分量不能仅凭边际似然完全分别识别；
- 作者只把两者作为诊断 proxy，而不是分别校准后的真实分解。

GIS Data Agent 应将以下信息合并为 claim ceiling：

```text
model uncertainty
+ conformal calibration status
+ spatial support coverage
+ temporal extrapolation distance
+ teacher/model applicability
+ evidence grade
= allowed claim level
```

每个 uncertainty artifact 至少应保存：

- calibration set 和 holdout set 定义；
- 空间、时间或系统级切分方式；
- confidence level；
- empirical coverage；
- CRPS 或 interval score；
- calibration sample count；
- applicable geometry、region 和 horizon；
- uncalibrated 与 calibrated interval；
- evidence reference 和 claim boundary。

## 4. 论文结果中最需要谨慎解释的部分

### 4.1 领先来自适配器，不是通用 frozen embedding

MiSS-adapted TerraNova 在静态环境目标上达到约 0.88 mean held-out `R2`，最强对比模型约为 0.77。但对 frozen embedding 做线性 probe 时，TerraNova 在九种方法中只排第七。

因此，不能把一个 TerraNova-like embedding 直接拼接到现有 node features 后就期待 Kernel 明显改善。真正需要验证的是：

- task-conditioned adapter；
- context-conditioned decoder；
- state assimilation；
- 与 domain transition model 的联合或分阶段训练。

### 4.2 时间编码不等于动力学

TerraNova 在未见 national indicators 上能执行 temporal interpolation 和短期 nowcasting，但：

- 未来预测超过约两年后开始落后于简单趋势外推；
- 六年未来 anomaly correlation 约为 0.49；
- 模型没有 action 或 forcing 条件；
- 作者明确承认 time-as-input 限制了 conditioned dynamics。

其 temporal transport 的 semigroup consistency 可以作为潜空间正则化启发，但不能直接视为真实世界状态转移。

### 4.3 Downscaling 是能力演示，不是可信数据产品

论文在四个 biosphere targets 上报告约 0.51 至 0.66 的 seed-mean within-country correlation，但明确将其称为 representation capability，而不是 validated product。

特别需要禁止：

- 将国家治理变量直接下推为街区级治理事实；
- 将行政统计下推结果作为政策效果；
- 将潜空间相关性解释为空间因果机制；
- 在没有真实细粒度 holdout 时发布 inferred map。

### 4.4 训练和验证仍有边界

- Production training 约使用单张 H100 327 GPU-hours、34 billion samples；
- 模型约 366M parameters；
- 主训练的 gridded validation 主要留出时间包络内部的年份，而不是未来外推；
- 最终 alignment knockout 每个配置只有一个训练 seed；
- land/ocean support placebo 只有两个 ocean targets；
- 代码和权重截至 2026-08-04 仍标注为 upon acceptance。

因此，近期更现实的路线是验证方法思想，而不是完整复刻 TerraNova。

## 5. 对三个领域实例的价值判断

### 5.1 UWM：价值最高

UWM 同时存在：

- 遥感和环境栅格；
- 街道、社区和行政区统计；
- 建筑、设施和宗地对象；
- 道路、服务和空间溢出图；
- 稀疏监测站和不同时间覆盖。

TerraNova 式多几何表示最适合解决 UWM 的 state reconstruction 和 sparse observation 问题。推荐优先选择空气质量、热风险或公共服务场作为第一个验证任务，避免一开始触及政策因果。

### 5.2 TWM：价值中高

TWM 可以使用该思想连接：

- 土地利用栅格；
- 宗地和规划对象；
- 乡镇、区县和城市统计；
- AlphaEarth 或其他 EO embeddings；
- 规划约束和保护边界。

最合理的角色是改善初始状态、区域上下文和新变量适配，然后继续由 TWM/FLUS/Geospatial Kernel 处理 action-conditioned allocation 和状态写回。

### 5.3 WWM：直接价值较低

WWM 的关键问题是小时级动作、forcing、河网拓扑、初始状态、守恒和 prospective issue/outcome。TerraNova 的年度 0.25 度场与 country geometry 不能解决这些核心边界。

可借鉴的只有：

- 多源背景状态编码；
- 新流域的小样本 context adapter；
- uncertainty-aware prior；
- teacher support 和 extrapolation evidence。

不能因此重新开启已经 no-go 的 Center Hill action-conditioned WWM 主线。

## 6. 建议的最小验证实验

### 6.1 研究问题

> 在一个真实城市中，保留栅格、行政区和图对象的原生几何并进行软对齐，是否能在严格空间和时间留出下，提高稀疏状态重建、新变量适配和不确定性校准？

这个问题只验证 foundation state representation，不验证政策效果或完整世界模型。

### 6.2 数据几何

选择一个已有真实数据和 evidence artifacts 的城市，建立三个输入 route：

```text
Raster route:
  PM2.5 / temperature / NDVI / built-up / night light

Administrative route:
  population / housing / service supply / demographic indicators

Graph-object route:
  road nodes / facilities / blocks / adjacency / accessibility
```

### 6.3 模型对照

至少比较：

1. no alignment；
2. EO/AlphaEarth alignment only；
3. admin-raster alignment only；
4. EO + admin-raster dual alignment；
5. hard aggregation/consistency baseline；
6. classical interpolation and spatial statistical baselines。

### 6.4 严格切分

- contiguous spatial-block holdout；
- future temporal-block holdout；
- whole-admin-unit group holdout；
- sparse label budgets；
- teacher off-support placebo；
- 至少三个训练 seed；
- 所有切分和适配预算预先冻结。

### 6.5 指标

- held-out `R2`、RMSE、MAE；
- anomaly correlation；
- cross-geometry retrieval；
- within-admin spatial correlation；
- CRPS、interval score 和 coverage；
- calibration error；
- label efficiency；
- trainable parameter count 和 fit time。

### 6.6 成功门槛

该实验只能支持以下主张：

```text
multi-geometry representation improves bounded state reconstruction
and uncertainty-aware adaptation under strict holdout
```

不能支持：

```text
policy causal effect
action-conditioned dynamics
general geospatial world model validation
autonomous planning superiority
```

通过 representation gate 后，才把 `Z_t` 接入现有 Kernel 的 `node_context` 或 `region_context`，并继续执行 action deletion、action shuffle、topology rewiring、forcing ablation 和多步 rollout 评测。

## 7. 建议的实施优先级

### P0：先改观测合同，不训练大模型

- 为 observation schema 增加 native geometry 和 spatial support 元数据；
- 明确 observed、interpolated、downscaled、simulated 和 proxy；
- 将 uncertainty calibration 和 teacher applicability 接入 claim boundary；
- 保持对现有 `uwm.canonical_observation.v1` 的兼容或设计 v2 migration。

#### P0 实施状态（2026-08-04）

P0 已按兼容扩展方式落地，当前没有创建 `v2`：

- `uwm.native_geometry_support.v1` 已加入 UWM 合同层；
- `geometry_type`、`spatial_support`、`temporal_support`、`aggregation_semantics`、
  `observation_semantics`、`uncertainty` 和 `calibration` 可沿 MMFE state input 进入
  canonical observation；
- 旧 `v1` role 不声明这些字段时仍然有效，但会在完整性摘要中标记为 legacy/incomplete；
- role 一旦声明 native geometry 元数据，就必须提供合法的 geometry、spatial support 和
  observation semantics；
- downscaled、interpolated 和 simulated 值必须携带 uncertainty 与 calibration status；
- 未校准的 inferred values 会把 renderer 的 `max_claim_level` 降到
  `exploratory_only`，并且不会被声明为真实观测；
- GEE environmental proxy、GHSL admin alignment 和 OpenAQ station observation 三条真实
  producer 路径已补齐相应元数据。

验证结果：6 个合同、renderer 和 producer 测试模块共 `29 passed`；7 个 simulator、
model-based RL、baseline、planner benchmark 和 evaluation 消费端兼容测试模块共
`26 passed`。因此这次修改目前支持的是“可审计的原生几何观测合同”，不代表 P1 的
multi-geometry state prior 已经训练或通过 holdout benchmark。

### P1：完成一个三几何 state-prior benchmark

- 单城市；
- 单一状态重建问题；
- 严格 holdout；
- 经典插值、空间统计和 frozen embedding baselines；
- 只验证状态层，不混入 planner。

#### P1 实施状态（2026-08-04）

P1-A benchmark harness 已落地：

- 输入合同要求 raster、admin 和 graph-object 三条原生 geometry route；
- query context 单独保留 coordinate 和 ordered time，不计作第四条观测几何；
- 实现 contiguous spatial-block、whole-admin-group 和 future-temporal 三种互斥的
  train/calibration/holdout；
- 基线包括 train mean、spatial IDW、hard admin mean、raster-only ridge 和
  raster-admin fusion；
- 候选为不强制跨 support 数值相等的 standardized linear fusion ridge；
- 增加 shuffled-admin、shuffled-graph 负对照，以及 split-conformal coverage 和
  interval score；
- baseline 和负对照优势必须达到预声明的最小相对改进，当前默认门槛为 `1%`；
- 只有 `observed_holdout`、evidence refs、三种 holdout 优势、负对照和 calibration
  同时通过时，才能形成 bounded state-reconstruction claim。

P1-B 已接入仓库内冻结的重庆 public-proxy artifacts：

- 36 个 CHAP/TAP 行政代表点；
- 7 天 TAP gridded PM2.5，共 252 条 target rows；
- 36 个 admin livability rows；
- 从 1,017 节点行政邻接图中完整匹配相同的 36 个 graph nodes；
- 三条 route 的 `county + township` join 完整，无静默丢行。

这次真实 proxy 运行没有通过 advantage gate：

| 方法 | 三种 holdout mean MAE |
|---|---:|
| hard admin mean | 3.3742 |
| spatial IDW | 3.4458 |
| raster-only ridge | 4.0274 |
| raster-admin fusion | 4.0454 |
| multi-geometry fusion | 4.1334 |

multi-geometry 候选没有击败必需基线；它相对 shuffled controls 的微小差异也没有同时
达到 `1%` 预声明门槛。其 split-conformal 总 coverage 为 `0.6567`，低于 `0.85`
门槛；尤其 future-temporal coverage 为 `0.0`。此外 TAP/CHAP 是 public gridded
products，不是独立 station-observed holdout。

P1-C 又接入了同场景期、但不读取 TAP target values 的 Open-Meteo dynamic context：

- daily temperature、precipitation 和 maximum wind；
- hourly humidity 的 daily mean；
- 独立 Open-Meteo air-quality proxy 的 hourly PM2.5 daily mean；
- 所有 primary ridge variants 共享相同 context，并增加 no-dynamic-context 消融；
- schema 强制 `uses_target_values = false`，同一日期广播到空间样本的值必须一致。

动态 context 没有改善结果，反而使 multi-geometry mean MAE 从 `4.1334` 上升到
`6.2763`，future-temporal MAE 从 `6.2828` 上升到 `15.3357`。总 coverage 从
`0.6567` 降到 `0.6343`，future-temporal coverage 仍为 `0.0`。`1e-6` 至 `100`
的固定 ridge sensitivity 也没有消除 future failure，因此不应通过 holdout 调参选择一个
事后有利参数。

新增的动态 context 数据充分性审计同样不通过：future split 只有 5 个独立训练日期，却有
5 个动态变量，比例为 `1:1`；预声明最低要求为每个动态变量 3 个训练日期，即至少 15 个
训练日期。本机冻结的 TAP 数据只有 2018-10 和 2024-07 两个 7 天窗口；即使忽略六年
regime gap 强行合并，总计也只有 14 个日期，严格切分后约 10 个训练日期，仍不满足门槛。
因此不应把两个窗口拼接成伪连续序列。当前共有六项 remaining gates：

```text
candidate_beats_required_baselines_on_every_split
geometry_shuffle_negative_controls_passed
dynamic_context_ablation_gate_passed
dynamic_context_sample_support_gate_passed
split_conformal_coverage_passed
observed_holdout_evidence_present
```

当前输出正确保持：

```text
supported_claim = multi_geometry_benchmark_execution_only
max_claim_level = exploratory_only
geospatial_state_prior_benchmark_ready = false
```

这个 no-go 只说明当前短时间窗、public proxy features 和线性 fusion 不足以支持 P1
优势主张。下一步需要扩展到至少 15 个训练日期，并使用独立 station 或其他 observed
holdout；不能通过调松 coverage、删除传统基线或事后筛选 context variables 来“通过”门禁。

### P2：将通过门禁的 state prior 接入领域 Kernel

- 作为 `node_context`、`region_context` 或 state initializer；
- 不替换 action、forcing 和 topology；
- 对比是否改善未见区域和小样本 transition skill；
- 验证 representation gain 是否传递到真实 action-conditioned holdout。

#### P2 准入基础设施状态（2026-08-04）

P2-A 已新增 fail-closed state-prior admission contract，但尚未把任何 prior 接入通用
runtime：

- `uwm.geospatial_state_prior.context_artifact.v1` 约束 prior 的 provenance、三条 geometry
  route coverage、evidence refs、split-conformal calibration、uncertainty 和 target-leakage
  audit，并要求 context artifact SHA-256；
- `uwm.geospatial_kernel.state_prior_admission.v1` 重新校验 benchmark contract、固定的八项
  readiness gates、`observed_holdout`、`bounded_support`、geometry coverage、calibration link
  和 claim boundary；
- 只有全部 gate 同时通过时才生成 `uwm.geospatial_kernel.state_prior_context.v1`，并只启用
  `learned_calibrated` support；
- context envelope 只允许用于 `node_context`、`region_context` 和 `state_initializer`，明确
  禁止替代 action model、forcing、topology、policy effect 和 action-conditioned dynamics；
- 任一 gate 失败时，输出 `status = rejected`、空 `enabled_support_levels` 和
  `context_envelope = null`，因此领域 adapter 无法误消费未通过门禁的 prior；
- admission validator 固定禁止 policy causal effect、action-conditioned dynamics、general
  GWM validation 和 empirical policy-effect claim escalation。

当前重庆 public-proxy benchmark 被明确拒绝：其 `benchmark_ready`、
`observed_holdout_evidence`、完整 readiness、`bounded_support` 和 calibrated coverage gate
均不通过。因此 P2 当前状态是“准入安全边界可执行”，不是“重庆 state prior 已可用于
Kernel”。合格 observed-holdout deterministic fixture 可以准入，用于证明正向合同路径；它不构成
真实研究结果。

P2-B 已新增 DAM-GK 的受控 `node_context` 绑定：

- `gwm.geospatial_kernel.dam_gk_state_prior_context_binding.v1` 只接受内部一致且状态为
  `admitted` 的 P2-A envelope；
- 调用方必须提交与 envelope 一致的 context artifact SHA-256、冻结的 node order、feature
  order 和有限浮点 tensor；feature 重名、漏节点、换序、NaN、dtype/device 不一致均 fail
  closed；
- prior channels 只追加在已有 `node_context` 尾部；如果 batch 使用
  `node_context_by_step`，只把同一个 origin-state prior 静态复制到各 rollout step，不将其
  解释为未来观测；
- adapter 同时返回扩维后的 `DAMGKConfig` 和 binding receipt；receipt 分别绑定 admission、
  source context artifact 与实际进入 batch 的 tensor SHA-256；
- 绑定过程验证 node state、action、已有 context/forcing channels、edge index、edge
  features、relation types、teacher state 和 region context 均保持不变；
- `zero` 与 deterministic `shuffle_nodes` controls 只作用于新增 prior channels，为 paired
  holdout 的 representation deletion/shuffle ablation 提供可执行输入。

P2-B 当前仍只由 observed-ready deterministic fixture 验证，没有真实 prior 被接入，也没有
形成 transition-skill improvement claim。`region_context` 和 `state_initializer` 仍保持
未绑定状态；先从最窄的 `node_context` 路径验证可以减少状态覆盖和区域条件语义混淆。

P2-C 已新增 paired strict-holdout evaluator：

- `gwm.geospatial_kernel.state_prior_transition_evaluation.v1` 固定
  `unseen_region`、`low_sample_region` 和 `future_action_conditioned` 三类 holdout；
- 必须同时提交 full prior、zero prior、shuffled prior 和 traditional baseline 四组逐样本成对
  预测；三组 prior 变体必须共享 model parameters 和 P2-B 的 fixed-kernel-input digest；
- 每个 prediction artifact 都绑定相同的 paired-input SHA-256，并分别绑定自己的 predictions
  SHA-256 与 context-values SHA-256，baseline 明确禁止携带 state-prior context；
- action、forcing、topology、observed target、node 和 split identity 在 paired-input digest 中
  冻结；缺失证据、非有限值、哈希不匹配或 control 改动其他输入会直接拒绝评测；
- readiness 要求 observed holdout、三类 split 的最低样本量、零 train/holdout sample
  overlap、unseen-region 零 region overlap、low-sample region 的预声明训练样本上限、future
  ordering、至少两个 future action，以及 full prior 在每个 split 上同时击败 traditional、
  zero 和 shuffled comparator；
- full prior 的 interval coverage 必须在每个 split 达到 admission confidence 减 tolerance 的
  预声明阈值；skill 或 coverage gate 失败会生成合法 `not_for_claim` 结果，而不是格式错误；
- 即使全部通过，也只支持“state-prior context 在固定 action/forcing/topology 的 paired strict
  holdout 上改善 transition prediction skill”，不支持 policy causality、general dynamics、
  general GWM validation 或 autonomous planning superiority。

P2-C 当前同样只由 deterministic observed-ready fixture 验证 evaluator 的正负合同路径。没有
真实 observed prior、真实 action-conditioned predictions 或新的 empirical result；当前重庆
public-proxy 仍只能得到 `exploratory_only` execution claim。

P2-D1 已新增冻结预注册协议：

- `gwm.geospatial_kernel.state_prior_transition_protocol.v1` 在 transition holdout 开放前冻结
  protocol ID、创建/冻结时间和最早开放时间，并要求实际访问时间不早于预声明边界、评测时间
  不早于实际访问时间；冻结晚于开放边界的协议直接拒绝；
- 协议绑定 P2-A admission SHA-256、state-prior ID、context artifact SHA-256、P2-B fixed
  Kernel-input SHA-256，以及 full、zero、shuffle 三组实际 context tensor SHA-256；
- 三类 split、四种 method、主指标 `MAE`、每 split 最低样本量、最小相对改善、confidence、
  coverage tolerance 和 minimum coverage threshold 均进入 canonical `protocol_sha256`；
- `zero` 和 deterministic `shuffle_nodes` 的操作定义与 seed、candidate/control 共享 model
  SHA-256、traditional baseline model SHA-256 均被冻结；prediction artifacts 必须逐一携带
  同一个 protocol SHA-256，且 model/context hashes 必须与协议及 binding 一致；
- unseen-region 零 region overlap、low-sample region 的预声明训练样本上限、future ordering
  和 action-outcome pair overlap 规则均在协议中冻结，evaluator 不再接受运行时 loose threshold
  参数，也不能由 leakage audit 自行放宽 low-sample 上限；
- 协议 validator 会重算 canonical SHA-256；阈值、模型哈希或绑定元数据被改动后旧 digest 立即
  失效。即使攻击者重算 digest，协议仍禁止提升到 policy causality、general dynamics、general
  GWM validation 或 autonomous planning superiority；
- 预注册协议只定义“满足全部 gate 时最多允许提出什么结论”，本身不产生 transition-skill
  证据。当前正向路径仍只由 deterministic fixture 验证，不是新的 empirical result。

P2-D1b 进一步补上 external registration 与 holdout opening receipt：

- `gwm.geospatial_kernel.state_prior_transition_protocol_registration.v1` 要求协议冻结后、
  holdout 开放边界前，在 write-once artifact store、experiment registry 或 signed timestamp
  service 中登记 protocol；收据绑定 registry URI、registry record SHA-256、registrar、登记时间
  和外部 evidence ref，并生成 canonical registration-receipt SHA-256；
- `gwm.geospatial_kernel.state_prior_transition_holdout_opening.v1` 将首次 label access 绑定到已经
  验证的 registration receipt、具体 holdout dataset ID、manifest SHA-256、access-log URI/SHA-256
  和 accessor；开放早于登记或早于预声明边界均 fail closed；
- full、zero、shuffle、traditional 四组 prediction artifacts 现在必须同时携带 protocol、
  registration receipt、holdout opening receipt 和 holdout manifest 四层 digest；artifact 创建时间
  必须位于 holdout 开放后且不晚于 evaluation，任一链路错配直接拒绝；
- registration/opening receipt 自身不允许提出 scientific result、transition gain、policy causality
  或 general GWM claim；即使修改 claim 后重算 receipt digest，validator 仍会拒绝；
- 当前实现负责验证外部登记和访问日志的合同与哈希链，不负责替代真实 write-once registry 或
  第三方时间戳服务。本轮只用 deterministic fixture 覆盖接口，没有生成真实外部登记证据。

P2-D1c 已新增 single-use execution guard：

- `gwm.geospatial_kernel.state_prior_transition_single_use_reservation.v1` 在正式 evaluator 启动前
  使用 `O_EXCL` 原子预占权限为 `0600` 的 receipt 文件，并执行 flush/fsync；同一路径已经存在
  时直接拒绝，不覆盖历史收据；
- reservation 绑定 protocol、registration、opening、holdout manifest、四组 prediction artifact
  bundle 与实际 evaluator 文件 SHA-256，并把这些身份合成为 `single_use_key_sha256`，供部署侧
  中心化 write-once store 执行跨路径唯一性约束；
- 成功评测生成 `single_use_finalization.v1`，绑定完整 evaluation SHA-256、readiness 和受限
  supported claim；评测抛出异常则生成 `failed` receipt，只记录稳定 failure code，不保留可重跑
  权限；
- `completed`、`failed` 和意外中断后遗留的 `reserved` 都默认阻塞自动重试。finalize 在文件锁内
  重新读取并比对原 reservation，文件被篡改或已经消费会直接拒绝；
- 成功路径返回 `single_use_execution.v1`，把 evaluation 和 final receipt 再绑定为 execution
  bundle SHA-256。single-use receipt 本身不独立提出 scientific result 或因果/GWM claim；
- 本地 `O_EXCL` 无法阻止有文件删除权限的操作者删除 receipt 或换一个未受管目录重跑。生产环境
  必须由受保护的中心 registry 对 `single_use_key_sha256` 建唯一索引并保留失败/中断记录。本轮
  仍只用 deterministic fixture 验证 guard，不是正式实证执行。

P2-D1d 已新增中央 single-use registry 的单节点参考实现：

- `gwm.geospatial_kernel.state_prior_transition_single_use_registry_record.v1` 使用 SQLite
  `single_use_key_sha256` 主键和 `BEGIN IMMEDIATE` 事务，把同一冻结评测在不同本地 receipt
  路径上的预占合并为一个唯一 attempt；连接启用 foreign keys，数据库启用 WAL，写入使用
  `synchronous = FULL`，每个操作使用独立连接；
- attempts 和 events 表只允许追加，触发器拒绝 update/delete；事件序列固定为一次
  `reserved`，随后至多一次 `completed` 或 `failed`，没有 delete、reset 或 retry API；
- 正式执行顺序固定为本地 `O_EXCL` 预占、中央 registry 预占、evaluator、本地终结、中央终结。
  中央预占冲突会保留本地 `reserved` receipt；中央终结失败时，本地 completed/failed receipt 和
  中央 reserved key 都继续阻止重跑；
- registry record 保存完整 reservation/finalization receipt、按序事件和 canonical SHA-256；成功
  execution bundle 进一步绑定该 registry record。validator 会同时检查 receipt digest、事件顺序、
  key、状态、不可重跑标志和 claim boundary，篡改后即使重算 registry-record digest 仍会拒绝；
- 并发 fixture 验证同一 key 的两个 writer 恰好一个成功；跨路径重复、失败后重试、重复终结、
  update/delete、事件篡改和 claim escalation 均 fail closed；
- 该 SQLite backend 只是单节点参考 registry：它依赖本机文件保护和本机时钟，不提供跨节点共识、
  第三方可信时间戳、外部 WORM 保留或抵抗数据库管理员删除/替换数据库的能力。正式评测仍必须迁移
  到受保护的生产 registry 或 signed timestamp/WORM service；本轮 deterministic fixture 不是外部
  登记证据，也不是实证结果。

P2-D2a 已新增 observed state-prior candidate readiness 审计：

- 修正 OpenAQ `observed_time_range` 语义：覆盖范围现在只由实际 measurement 的 `datetime` 或
  `period.datetimeFrom/datetimeTo` 形成，不再用站点 `datetimeFirst/datetimeLast` 生命周期冒充观测
  覆盖；零 measurement snapshot 现在必须得到 `null/null`，不能因为站点曾运行而通过时间 gate；
- 已从本地 raw payload 无网络重建 OpenAQ 历史和 2024 scene-attempt 派生物。历史 600 条多污染物
  measurement 的真实范围为 `2018-10-17T11:00:00Z` 至 `2018-10-23T23:00:00Z`；2024 attempt
  仍为 0 条 measurement、`null/null`，`scene_holdout_ready = false`；
- `uwm.geospatial_kernel.state_prior_observed_candidate_readiness.v1` 将 raw observation、sensor-location
  解析、station-admin crosswalk、三几何 dataset、时间重叠、target leakage、normalized proxy 一致性
  和输入 artifact SHA-256 固定为 15 项 gate；该证书最多允许进入 P1 benchmark input，永远不能直接
  生成 P2 admission 或 scientific/transition/policy/GWM claim；
- 当前重庆本地证据有 100 条 PM2.5 measurement 和 7 个观测日，但实际只覆盖 1 个 sensor、1 个
  station 和 1 个 spatial band；2018-10 observed target 与 2024-07 三几何 dataset 没有时间重叠；
- 当前 canonical readiness artifact 位于
  `data/uwm_public_proxy/chongqing_central/geospatial_state_prior_observed_readiness_2026_08_04/`
  ，digest 为 `746d9d3298735f536da353bb822a07295e102c9ae8ac79023886253a006dfaeb`；结果严格保持
  `p1_benchmark_input_ready = false`、`p2_admission_permitted = false` 和 `max_claim_level = not_for_claim`；
- 已完成 P2-D2b 的 station-admin 空间归属：
  `uwm.geospatial_kernel.station_admin_crosswalk.v1` 绑定 locations/admin GeoJSON 输入 SHA-256，使用
  point-covered-by-polygon 关系审计 unmatched、ambiguous、无效坐标与无效几何；边界多重命中不会被
  任意分配。当前 15 个 catalog station 全部唯一匹配到 1017 个本地乡镇面之一，crosswalk digest 为
  `9371eaf4bf9bd3beaa951d1ea7979827933d0a7d4bd91fd4b5a1e8f0934eb119`；行政标识仍明确是本地
  省/区县/乡镇名称组合，不宣称官方行政代码或历史边界对齐；
- OpenAQ acquisition 已改为每个 location 最多选择 1 个 PM2.5 sensor，支持 station/sensor allowlist、
  精确计数分页或 `found = ">N"` 下界加 terminal-short-page 完整性审计、临时目录检查与显式替换下的
  事务式目录交换；默认拒绝覆盖已有 snapshot，任一分页或单站请求失败都不会发布部分快照，API key
  只进入请求 header；
- 无 API key 阶段生成的 15 站 acquisition plan digest 为
  `981877648a34f28f5ca6f02b3f56538e5248d6585b7267655a379eb90bd50f52`，并明确
  `measurement_downloaded = false`、`max_claim_level = acquisition_plan_only`，不把计划冒充实测；
- 获得 API key 后已执行 live acquisition，key 未写入 URL、日志或 artifact。新 snapshot 包含 15 个
  station/sensor binding 和 1314 条真实 PM2.5 measurement，其中 13 个站有值、两个 2019 年启用的站
  在 2018 窗口严格保持 0；观测范围为 `2018-10-17T11:00:00Z` 至
  `2018-10-24T00:00:00Z`，所有 sensor page audit 均为 complete；
- live locations 对应 crosswalk 重新绑定输入 hash，15 个站仍为 15 matched、0 unmatched、0 ambiguous，
  digest 为 `497398c5eb6b5a0b63a542ee15e073a186fd3dcac9d88e8ad119a0e506d8c9e9`。

P2-D2c 已形成同期 observed-station P1 candidate 并执行默认协议：

- 新 dataset 使用 OpenAQ 日均 PM2.5 作为 observed point target；raster route 只使用前一日 TAP PM2.5
  和站点到 TAP grid 的距离，admin route 使用行政面面积/周长，graph route 使用行政邻接 degree；没有
  使用当日或未来 target value。因 `t-1` 约束，首日 13 个样本被审计性丢弃，最终形成 13 个站、13 个
  admin group、6 个时间组和 78 个样本；TAP 可能吸收相关监测源，因此仍禁止独立来源主张；
- 同期 readiness 的 15 项 gate 全部通过，digest 为
  `caf22df264b97abb4f52966cc0f0bd70dc6a2b959bb4d0b37bd8c2ad960d7e4e`，只支持
  `p1_benchmark_input_ready = true`；按合同 `p2_admission_permitted` 仍固定为 false；
- P1 使用未调参默认协议运行后明确失败：multi-geometry candidate 总体 MAE 为 `5.433187454`，弱于
  raster-only baseline 的 `4.471114337`；candidate 在 future-temporal split 略优于 raster-only
  （`3.052842672` vs `3.115228448`），但在 spatial-block 和 whole-admin 上明显更差；
- `candidate_beats_required_baselines_on_every_split`、`geometry_shuffle_negative_controls_passed` 和
  `split_conformal_coverage_passed` 三项 gate 未通过；整体 conformal coverage 为 `0.837837838`，低于
  `0.85` 门槛，spatial-block coverage 仅 `0.666666667`；结果固定为
  `geospatial_state_prior_benchmark_ready = false`、`max_claim_level = not_for_claim` 和
  `no_multi_geometry_state_reconstruction_claim_supported`，不得接入 P2 或事后调参升级结论。

P2-D2d 已把上述 no-go 转成 fail-closed 失败诊断，并内部冻结下一轮 P1 设计：

- 新增 `uwm.geospatial_kernel.state_prior_p1_failure_diagnostic.v1`，绑定原 dataset/benchmark 的
  canonical SHA-256，逐 route 输出整体和 train/calibration/holdout centered rank、feature variance、
  描述性 feature-target correlation、相对 train 的 standardized mean shift、candidate-minus-baseline/
  negative-control MAE delta 和 conformal coverage deficit。correlation 明确不能作为 feature evidence；
- 诊断进一步定位到空间泛化退化：structured admin route 相对 shuffled-admin control 在
  spatial-block 和 whole-admin 的 MAE 分别差 `1.961694377` 和 `0.364453889`；polygon area 在
  spatial-block holdout 相对 train 漂移 `1.149135027` 个标准差；whole-admin calibration/holdout 的
  `admin_adjacency_degree` 都退化为零方差。graph route 相对 raster+admin 在三个 split 均有小幅改善，
  且优于 shuffled-graph control，但单一 degree 特征不足以抵消 admin route 的外推损失；
- 覆盖率失败不是均匀发生：spatial-block deficit 为 `0.183333333`，whole-admin 为
  `0.016666667`，future-temporal 为 `0`。这些都是已经打开的 2018 holdout 上的事后描述，不能用于
  回改同一 holdout 的 feature、threshold 或 readiness；诊断 artifact digest 为
  `1aede01d5ab421d629aa9e43af7b7614046ce446ed37395fd839cfae504d933a`，固定
  `p1_benchmark_ready = false`、`p2_admission_permitted = false` 和 `max_claim_level = not_for_claim`；
- 下一轮内部 freeze 把 2018-10-18 至 2018-10-23 固定为 opened development-only window，把尚未由
  protocol builder 获取 target 的 2024-07-02 至 2024-07-07 固定为 final evaluation window；本地已有的
  2024 acquisition attempt 只有 15 个 location、90 个 sensor 和 0 条 measurement，未暴露 target value，
  但已作为 evidence/limitation 明确登记。候选、四个
  baseline、两个 geometry shuffle control、seed `37`、`1%` 最小改善和 `0.85` coverage threshold
  均保持不变。feature source allowlist 只允许 OpenAQ target、`t-1` TAP raster、当前 admin geometry
  和 adjacency graph，禁止未声明特征及 target-derived/same-day proxy；
- 该 freeze digest 为 `ee52b37d10bda4b7f64fea960254312806bcefaea8ef9220630226001df37488`，只是
  internal protocol，不是可信外部预注册。external registration、holdout access log、source hash、
  minimum support、admin boundary vintage、license/lineage 和新 readiness 七项 activation gate 初始
  全为 false，因此 `p1_execution_permitted = false`、`p2_admission_permitted = false`。2024 窗口是历史
  数据的 fresh target acquisition，不得表述为实时 prospective forecast。

P2-D2e 已完成 2024 final window 的真实 predictor-side preflight，不再以新增模型代码代替数据检查：

- 使用旧 2024 locations catalog 重建一站一个 PM2.5 sensor 的 15 站 acquisition plan，时间边界严格为
  `[2024-07-02T00:00:00Z, 2024-07-08T00:00:00Z)`；15 个 station/sensor pair 与已经完成分页审计的
  2018 live acquisition 完全一致。plan digest 为
  `2a11ca59e1fd8be61ab7d5c58cc7e22cc4f8bc93f4c2b9a9c0ace0a920a8e19d`，仍固定
  `measurement_downloaded = false` 和 `max_claim_level = acquisition_plan_only`；
- 旧 2024 attempt 的 location catalog 有 90 个 sensor，但 measurement payload 只保留 20 个 sensor query，
  且全部 `found = 0`；它不符合当前 15 站 acquisition 审计合同，也没有暴露 target value。新 plan 没有
  复用旧的零结果作为观测证据；
- 基于同一 2024 locations 重算 station-admin crosswalk，仍为 15 matched、0 unmatched、0 ambiguous、
  0 invalid coordinates，digest 为
  `cdc648f49c822a21a0e370121fbbbcd53e5400b015d932b3c76a7b39b42b7954`；15 站对应 13 个 admin group；
- TAP 本地包包含 day-of-year 183 至 189、每天 6 个 tile，共 42 个 raster zip 和 6 个 coordinate zip。
  final target 需要的 `t-1` 区间是 2024-07-01 至 2024-07-06；15 站的 required/available lag support 为
  `90/90`，missing 为 0，实际使用 tile 075/096，最大 grid distance 为 `0.005131276644265911` 度；
- admin provenance 继续 fail-closed：GeoJSON manifest 只能追溯到本地
  `/Users/zhouning/Downloads/shp/xiangzhen.shp`；Esri XML 记录的创建和字段处理日期是 `20210622`，没有
  external source URL 或 license document，并明确含有开县/梁平县等历史名称。因此空间匹配可复算，
  但 2024 official boundary vintage 和 source license 两项仍不能通过；
- machine-readable predictor preflight digest 为
  `65c47235e37278494adf9a7909f6dd1b2b610d9de41e6b39dd11143308e23dc7`，结果为
  `pre_acquisition_predictor_inputs_ready = true`。这只表示 plan/crosswalk/admin/graph/TAP predictor 链完整；
  target measurements、admin vintage、admin license 和 external registration 四项仍是 blocker，所以
  `p1_execution_permitted = false`、`p2_admission_permitted = false`。preflight 不回写或篡改 frozen protocol。

P2-D2f 已把不可关闭的 admin provenance blocker 固化为 fail-closed protocol closure，避免先获取 2024
target 再发现内部冻结协议不能合法执行：

- closure 绑定原 protocol digest
  `ee52b37d10bda4b7f64fea960254312806bcefaea8ef9220630226001df37488`，不修改原协议；原 allowlist
  指定的 `chongqing_township_admin_units_local_snapshot` 仍只有本地 shapefile lineage，boundary vintage、
  source URL 和 license 均不可验证，因此该协议 digest 被标记为 `closed_fail_closed`，不可原地重新激活；
- 已有 Geofabrik probe 只能证明 `chongqing-260717.osm.pbf` 在 2026-07-17 可访问。这个时间晚于
  2024-07-02 final window 的 predictor cutoff，而且 probe 没有行政边界 extract、geometry digest、几何
  有效性结果、官方边界身份或随证据绑定的 license 文档；它既不在关闭的 source allowlist 中，也不是
  2024 administrative snapshot，所以 `eligible_as_frozen_protocol_repair = false`；
- closure builder 只读取 protocol、predictor preflight、acquisition plan、旧零测量 attempt manifest 和既有
  Geofabrik metadata probe。plan 仍为 `measurement_downloaded = false`，旧 attempt 仍为 0 measurements、
  null observed range，builder 明确不读取 target values，因此只能在 `available_local_evidence_only` 范围内
  声明 `target_unconsumed_under_available_evidence = true`；这不是对仓库外访问行为的独立证明；
- closure digest 为
  `5850f62eb483944bb7cf56b8190c27de1de4d6df3f1ea118c0e18c5e223576eb`，固定
  `protocol_reactivation_permitted = false`、`target_acquisition_permitted = false`、
  `p1_execution_permitted = false` 和 `p2_admission_permitted = false`。继续实验必须在 target 获取前建立新的
  protocol digest，并先取得外部登记回执；新的行政区源还必须具备不晚于 predictor cutoff 的 snapshot
  日期、source/license/content hash、提取后 geometry hash、CRS/coverage/topology 校验，并从同一 snapshot
  重建 station crosswalk 和 admin graph。当前 2026 Geofabrik probe 不能满足这组 v2 re-entry gates。

验证结果：原生观测合同、P1 benchmark/重庆 no-go、P2-A/P2-B/P2-C/P2-D1/P2-D1b/P2-D1c/
P2-D1d/P2-D2a/P2-D2b/P2-D2c/P2-D2d/P2-D2e/P2-D2f、DAM-GK 兼容路径和相关 geospatial/OpenAQ 回归
合计 `183 passed`；P2-D2f protocol closure 定向测试为 `4 passed`，覆盖确定性重建、重算 digest 后禁止
协议自解封和 acquisition plan 已含 target 时拒绝关闭；P2-D2e predictor preflight 定向测试为 `3 passed`；其中
P2-D2d 诊断/内部 freeze 的定向测试为 `9 passed`，覆盖重算 digest 后的 claim/
admission 升级、threshold 放宽、协议自激活、窗口重叠和 target leakage；
station-admin crosswalk 和 OpenAQ acquisition 新增 fixture 已覆盖唯一/歧义/未匹配分配、重算 digest
后的 gate escalation、多站选择、分页完整性、部分失败、禁止覆盖和密钥不落盘。新增和修改文件通过
Ruff，且没有修改通用 `geospatial_kernel/runtime.py` 合同。旧 internal freeze 已因 admin provenance
不可修复而关闭，不能再通过补 gate 后获取 2024 target。下一步是先寻找或构建满足 v2 re-entry requirements
的日期固定行政区 snapshot，并在 target 获取前冻结及外部登记一个新协议；之后才能重建
crosswalk/readiness 并只执行一次新冻结 P1。2018 诊断可用于提出下一版研究假设，但不能改写旧协议的
source allowlist。只有新的 P1/P2-A 真正通过，才能把 protocol 与真实 holdout
manifest 登记到受保护的生产 write-once registry，并以唯一 key 执行一次四组 prediction paired
evaluation。在此之前不接 `region_context`、state initializer 或 planner。

### P3：再考虑 foundation-scale pretraining

只有在 P1 和 P2 都显示稳定增量后，才评估：

- 扩展到更多城市和领域；
- polygon、network 和 parcel 专用编码器；
- task-conditioned hypernetwork；
- multi-domain pretraining；
- 大规模 compute 投入。

## 8. 最终判断

TerraNova 补上的是 GIS Data Agent 当前较弱的一层：

> **如何从异构、异尺度和异几何观测中形成可迁移、可补全且带不确定性的世界状态。**

它没有补上当前 GWM 真正困难的一层：

> **行动如何通过真实空间关系和外部 forcing 导致未来状态变化。**

因此，最佳路线是形成清晰的两层架构：

```text
Geospatial Foundation State Model
负责 observation、representation、completion、adaptation

Action-Conditioned Geospatial Dynamics Kernel
负责 transition、constraint、writeback、rollout、planning evidence
```

这种分层既能吸收 TerraNova 的表示学习优势，又不会破坏 GIS Data Agent 已经建立的有界任务世界、行动条件动力学、真实强基线、因果边界和 Evidence Gate 研究纪律。

## 9. 项目内相关依据

- `docs/reports/bounded_world_definition_and_geospatial_kernel_correction_2026-08-01.md`
- `docs/research/GWM_RESEARCH_PRINCIPLES.md`
- `docs/reports/gwm_geospatial_kernel_closure_decision_2026-08-01.md`
- `docs/reports/world_models_geospatial_dimension_and_kernel_paper_potential_2026-08-01.md`
- `docs/reports/gwm_substantive_progress_retrospective_2026-08-01.md`
- `docs/uwm-renderer-simulator-planner-theory-2026-07-04.md`
- `data_agent/uwm/contracts.py`
- `data_agent/uwm/renderer.py`
- `data_agent/uwm/dam_geospatial_kernel/contracts.py`
- `data_agent/uwm/geospatial_kernel/contracts.py`

## 10. 论文证据来源

- Rodriguez-Pardo, C., and Tavoni, M. (2026). *TerraNova: A Foundation Model for the Anthropocene*. arXiv:2607.29527v1.
- TerraNova Supplementary Information: full methodological specification, ablation programme, extended results and computational cost.
- TerraNova project page: `https://carlosrodriguezpardo.es/projects/TerraNova/`。
