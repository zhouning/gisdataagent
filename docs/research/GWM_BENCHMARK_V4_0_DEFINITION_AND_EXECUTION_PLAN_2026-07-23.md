# GWM Benchmark V4.0定义与执行方案

日期：2026-07-23

当前状态：BENCHMARK_COMPLETED / ACTION_TRANSFER_NOT_SUPPORTED。

定义、元数据预检、rc1周尺度bundle、Runtime-R3、提交合同和ACTION-A4评分器已经完成并封存。
冻结的suite_protocol.json保留预测前状态；当前执行状态以runtime_r3_evaluator_seal.json为准。

## 1. 一句话定义

GWM Benchmark V4.0是一场真实行动迁移考试：模型只用2019和2022两次纽约出租车政策变化学习
“状态在行动下如何变化”，然后在不使用任何2025行动后结果进行训练、调参、归一化或构图的前提下，
预测2025拥堵收费开始后263个Taxi Zone连续12周的出租车需求和CBD流动。

V4相对V3只补一个证据缺口：

> V3证明模型可以在新地区做土地状态递推；V4检查模型遇到一种训练时没有出现过的真实行动时，
> 是否真的会使用行动参数和空间作用范围，而不是只重复历史趋势。

## 2. 最终场景选择

V4主场景固定为纽约市出租车与2025 MTA Congestion Relief Zone收费。

| 候选 | 优点 | 硬伤 | 决定 |
| --- | --- | --- | --- |
| 继续做水库调度 | 行动含义直观 | 调度、入流、拓扑和许可链很难闭环 | 不作为V4核心 |
| 2015 improvement surcharge | 有严格的先封存后取数记录 | 行动不在训练联合支持内，且一次性测试已经失败 | 保留为反证材料 |
| 2025 NYC CRZ | 数据、边界、政策和历史行动齐全，可立即执行 | 结果曾被研究人员看过，不是分析者盲测 | 选为V4核心 |

这个选择的重点不是让结果更容易好看，而是让问题准确、数据充分、失败可以解释、流程能够完成。

## 3. 底层逻辑与理论依据

### 3.1 状态—行动—转移

世界模型的基本对象不是一张静态地图，而是：

    当前状态 S_t
      + 外部行动 A_t
      + 空间关系图 G_t
      -> 转移函数 F
      -> 下一状态 S_(t+1)

形式上：

    S_(t+1) = F(S_t, A_t, G_t, C_t) + error

其中C_t是允许使用的日历或上下文。V4不要求把政策效果解释成因果效应，只要求检验：当A_t换成一种
模型训练时没有见过的新数值组合和空间范围时，F是否仍能提高预测。

### 3.2 分布外行动迁移

普通时间预测可以靠季节性和惯性取得不错结果，但它不能证明模型理解了行动。V4故意让训练和测试的
行动不同：

- 2019是具有空间范围的固定附加费；
- 2022是城市范围内多项计价组件同时调整；
- 2025是新的CBD空间收费和0.75美元出租车单次费用。

因此测试问题是action out-of-distribution transfer，而不是简单的同分布插值。

### 3.3 空间关系归纳偏置

出租车需求不是263条互不相关的时间序列。一个区域的变化会沿相邻区域和OD流传播。DAM-GK通过
三类关系表达这个结构：

1. 地理相邻关系；
2. 起终点流动关系；
3. 行动暴露关系。

这属于关系归纳偏置：模型被要求用真实空间结构组织信息，而不是让一个黑箱从区编号中猜关系。

### 3.4 对照与证伪

如果模型真的使用行动，删除或破坏行动信息后应该变差。V4因此不只比较一个总误差，还执行行动删除、
日期错位、行动分量打乱、CBD范围重连和空间暴露打乱。正确模型没有按预期优于这些对照时，结论必须是
行动迁移不成立。

### 3.5 评测程序与声明边界

2025答案已在先前研究中被查看，所以V4不能声称分析者盲测。V4采用较窄但真实的声明：

- 2025行动后数据不得进入模型拟合、早停、选择、归一化、阈值或构图；
- 每个模型提交训练行清单、模型和预测哈希；
- 正式评分器冻结后统一评分；
- 不论输赢发布全部结果。

这叫模型未见的回顾性行动测试，不叫未来盲测，也不叫因果识别。

## 4. 数据详细信息

### 4.1 空间与目标

| 项目 | 固定定义 |
| --- | --- |
| 城市 | New York City |
| 空间单元 | 263个NYC TLC Taxi Zone |
| CBD作用区 | MTA官方CBD Taxi Zone polygon，共38条记录 |
| 时间粒度 | 从政策生效日开始对齐的7天块 |
| 目标1 | 每区每周pickup_count |
| 目标2 | 每区每周dropoff_count |
| 目标3 | 每区每周cbd_inflow |
| 目标4 | 每区每周cbd_outflow |

### 4.2 三次行动

| 事件 | 生效日 | 角色 | 数值与范围 |
| --- | --- | --- | --- |
| NYS congestion surcharge | 2019-02-02 | 训练 | 适用曼哈顿行程的2.50美元黄牌出租车附加费 |
| TLC taximeter adjustment | 2022-12-19 | 训练 | 起步价、计价单位和多项附加费调整 |
| MTA CRZ tolling | 2025-01-05 | 测试 | CBD适用黄牌出租车每次0.75美元 |

模型不能把事件名称、年份或event ID作为输入，只能读取15维数值行动向量和263维冻结空间暴露向量。

15个行动字段包括固定空间附加费、起步价、improvement surcharge、计价单位、早晚高峰、机场费、
期望总金额变化、相对票价变化、空间适用比例、时间适用比例和实施比例。

### 4.3 固定时间窗口

每次行动严格使用52个完整行动前周和12个完整行动后周：

| 事件 | 行动前52周 | 行动后12周 |
| --- | --- | --- |
| 2019 | 2018-02-03至2019-02-01 | 2019-02-02至2019-04-26 |
| 2022 | 2021-12-20至2022-12-18 | 2022-12-19至2023-03-12 |
| 2025 | 2024-01-07至2025-01-04 | 2025-01-05至2025-03-29 |

行动对齐周而不是自然周可以避免政策在一周中间生效造成标签混合。

### 4.4 数量与本机占用

| 层级 | 数量 |
| --- | ---: |
| TLC月文件 | 72 |
| 原始TLC记录 | 349,782,159 |
| 原始TLC本机字节 | 5,407,738,525 |
| 日尺度zone state行 | 615,946 |
| 日尺度OD行 | 21,334,750 |
| 每事件zone-week行 | 16,832 |
| 两个训练事件zone-week行 | 33,664 |
| 2025测试输入zone-week行 | 13,676 |
| 2025测试目标zone-week行 | 3,156 |
| 全部周尺度bundle行 | 50,496 |
| 需要预测的标量 | 12,624 |

72个月文件由两部分构成：2018-02至2019-12和2021-12至2023-12共48个历史文件，2024-01至
2025-12共24个当前文件。原始文件已经全部在本机，V4 draft不需要新增下载。

### 4.5 官方来源和用途

| 数据 | 发布者 | 用途 |
| --- | --- | --- |
| Yellow Taxi月度Parquet | NYC TLC | 状态、OD和费用字段 |
| taxi_zones.zip | NYC TLC | 区域边界和相邻关系 |
| taxi_zone_lookup.csv | NYC TLC | zone ID、borough和名称 |
| CBD Taxi Zone polygons | MTA / NY State Open Data | 2025空间暴露范围 |
| 2019政策页、memo、court notice | NY State Taxation and Finance | 2.50美元和空间范围 |
| 2022 adopted rule | NYC TLC / City Record | 生效日和计价组件变化 |
| 2025 CRZ toll schedule | MTA | 生效日、0.75美元和适用规则 |
| CRZ entries、CBD VMT | MTA / NY State Open Data | 独立系统级合理性检查，不进模型训练 |

## 5. 切分和防泄漏规则

训练与选择只使用2019和2022事件。超参数采用两折leave-one-intervention-out：一次用2019训练、
2022验证，另一次反向；规则选定后再用两个事件重训。

2025行动后的任何目标行禁止用于：

- 模型拟合和早停；
- 超参数和阈值选择；
- 特征归一化；
- 空间图构造；
- 行动编码选择；
- 失败后的人工修补。

每个提交必须带训练行清单及哈希。清单中出现2025-01-05及以后的记录即判为协议违规。

## 6. 技术架构

### 6.1 总体流程

    官方数据与政策证据
      -> 日尺度263区状态与OD面板
      -> 行动对齐周尺度bundle
      -> StateSnapshot + ActionSpec + SpatialGraph
      -> GWM Runtime-R3
           -> UWM / DAM-GK action-conditioned model
           -> matched no-action model
           -> three simple baselines
           -> six negative controls
      -> 12步开环rollout
      -> 统一PredictionBundle
      -> 冻结评分器
      -> 结果、哈希、失败和声明边界

### 6.2 GWM Runtime Kernel：Runtime-R3

Runtime-R3不负责决定模型好坏，它保证所有模型在同一考试条件下运行：

- ZoneWeekStateSnapshot：263区的版本化周状态；
- NumericActionSpec：15维行动向量、正式生效日和263维暴露；
- MultiRelationSpatialGraph：地理邻接、OD和行动暴露关系；
- OpenLoopRolloutRequest：从2025-01-04状态出发递推12周；
- MultiTargetPredictionBundle：相同的3,156个zone-week键和4个预测目标；
- RuntimeAuditReceipt：数据、代码、模型、环境、随机种子、资源和失败哈希。

Runtime-R3禁止在递推中把真实2025中间状态写回。随机模型固定31、47和73三个种子并提交完整集成。

### 6.3 Geospatial Kernel：DAM-GK

V4核心模型是action-modulated multi-relation Graph-GRU：

1. 对地理邻接、OD和行动暴露分别做关系消息传递；
2. 将15维数值行动向量编码成行动表示；
3. 用每个zone的空间暴露调制行动门；
4. 把空间消息和行动门送入Graph-GRU状态转移；
5. 同时输出pickup、dropoff、CBD inflow和CBD outflow；
6. 预测结果作为下一周状态继续开环递推。

这里的关键不是Graph-GRU这个名字，而是模型必须显式回答三个问题：哪里受影响、行动是什么、影响如何沿
空间关系传播。

### 6.4 图结构

| 关系 | 边数 | 含义 |
| --- | ---: | --- |
| Geographic adjacency | 692 | TLC区边界相邻 |
| OD flow | 2,054 | 每区训练安全期top-8流向 |
| Action exposure self relation | 263 | 本区的行动暴露与数值语义 |

测试行动后的OD不得用于更新图。

## 7. 模型和负对照

### 7.1 正式模型组

| 模型 | 作用 |
| --- | --- |
| UWM / DAM-GK action-conditioned | 检查完整行动空间模型 |
| matched DAM-GK no-action | 只删除行动输入，隔离行动增量价值 |
| fixed-adjacency spatial AR | 简单空间历史基线 |
| nonspatial historical AR | 不使用空间结构的历史基线 |
| 52-week seasonal persistence | 直接复制去年同周状态 |

### 7.2 六项机制检查

| 检查 | 破坏内容 | 正确模型应有表现 |
| --- | --- | --- |
| action deletion | 删除行动向量 | 误差上升 |
| date -4 weeks | 行动提前4周 | 误差上升 |
| date +4 weeks | 行动推迟4周 | 误差上升 |
| component permutation | 打乱15维行动含义 | 误差上升 |
| CBD scope rewire | 38个CBD区重连到38个非CBD区 | 误差上升 |
| exposure shuffle | 固定种子打乱263区暴露 | 误差上升 |

这些检查不能证明政策因果，但能发现模型是否根本没有使用正确行动语义。

## 8. 评分规则

### 8.1 主指标

主指标为macro pre-event normalized MAE，越低越好。

对zone z、目标 k、报告周 h：

    normalized_error(z,k,h)
      = abs(prediction - observation)
        / max(mean(target over the 52 pre-event weeks), 1)

然后对263个zone、4个目标和第1、2、4、8、12周等权平均。

这样既保留真实数量误差，又避免高流量曼哈顿区压倒其他区域。12周都必须预测，但主报告时点固定为
1、2、4、8和12周，不能看完结果后挑最好的一周。

### 8.2 辅助指标

- 按目标和周分解的归一化MAE；
- 按borough和CBD暴露分组结果；
- 全系统总量绝对百分比误差；
- 预测变化量与真实变化量比；
- 若提交区间，报告80%区间覆盖率；
- 行动模型与各基线的配对差值。

### 8.3 统计比较

以263个Taxi Zone作为成对重采样单位，固定种子20260723进行20,000次bootstrap，报告行动模型减
无行动模型的95%百分位区间。该区间用于预测比较，不解释成政策因果置信区间。

### 8.4 行动迁移成立门

必须全部满足：

1. 行动模型主指标低于同结构无行动模型；
2. 配对差值95%区间完全小于0；
3. 至少3/4目标方向一致；
4. 至少4/5报告周方向一致；
5. 正确行动语义优于行动分量打乱和CBD范围重连。

benchmark完成不要求行动模型通过这个门。门失败时，最终状态应是benchmark完成、行动迁移主张不成立。

## 9. 分阶段执行

| 阶段 | 交付物 | 退出条件 |
| --- | --- | --- |
| V4.0-draft1 | 协议、中文定义、元数据预检 | 数据、问题和声明边界通过 |
| V4.0-rc1-data | 周尺度bundle、图、行动向量、训练行清单 | 50,496行及全部哈希通过 |
| V4.0-rc2-predictions | 五模型、六控制、Runtime-R3重放、预测承诺 | 3,156键完全一致 |
| V4.0-final | 冻结评分、对照结果、失败与声明 | 九项completion gate全部核对 |

## 10. 最终执行状态

V4已经没有未完成卡点。五个模型、六个控制、31/47/73三个随机种子均已运行；35项预测重放的最大
绝对差为0.0；全部预测、模型、环境、sidecar和代码已承诺；正式评分已经生成。

最终主指标为：行动DAM-GK 0.495998，匹配无行动DAM-GK 0.501090，固定邻接空间AR 0.463994，
非空间历史AR 0.462225，52周季节基线0.571648。

行动模型比匹配无行动模型好约1.02%，但没有超过两个简单AR基线，并且CBD范围重连对照得分
0.494034，略优于正确行动。因此正式状态为benchmark完成、行动迁移主张不成立。

完整结果、图表和勘误审计见
`docs/research/GWM_BENCHMARK_V4_0_FINAL_REPORT_2026-07-23.md`。

## 11. V4能证明和不能证明什么

V4 final可以支持：

- 在纽约Taxi Zone场景下的模型未见行动迁移证据；
- UWM连续12周开环预测证据；
- 行动语义和空间暴露是否增加预测价值的匹配对照证据；
- Runtime-R3的可重放和审计证据。

V4不能支持：

- 拥堵收费的因果效果；
- 分析者从未见过答案的盲测；
- 业务级实时交通预测；
- 对其他城市、交通方式或政策的普遍有效性；
- 通用GWM Runtime产品已经完成；
- 一般意义上的UWM、DAM-GK或GWM有效性。

## 12. 文件与执行入口

机器协议：

    benchmarks/gwm_bench_foundation_v4_0_draft/suite_protocol.json

元数据预检：

    .venv/bin/python benchmarks/gwm_bench_foundation_v4_0_draft/preflight_v4_draft.py

预检报告：

    benchmarks/gwm_bench_foundation_v4_0_draft/preflight_report.json

预检只读JSON、文件元数据和Parquet footer，不扫描2025行动后目标行。通过后才进入rc1-data。

## 13. 当前封存凭证

元数据预检27项全部通过，rc1 bundle验证22项全部通过，评分器构造答案15项全部通过。

| 对象 | 状态或SHA256 |
| --- | --- |
| 协议 | 54152f65433440fb28fb8d9aeb605685b7e81bbade11bed229ce50dd7abb9950 |
| rc1 bundle manifest | dfe3fd7ae490ac2b8a2522ba77df4a111017302eabd579544b1a3300f1020acd |
| rc1 verification | cb48b7d532aa778b233997e7ff73bdba3837494296adc8f88bcf9c1da089a049 |
| evaluator conformance | a20b2990477197c2b7799b99cab5dbc2b55a496a93da4498cf52c5739803e8d6 |
| Runtime-R3/evaluator seal | 93c8a7f3335bf9c4e7338c6490f951119bc6542e5f6a87fb2656aa901674528c |
| 预测承诺 | 3c39a405b74d84ba026767c7d50c6ddd28b5e21736166e7c60b743f87660a2b3 |
| 当前机器状态 | BENCHMARK_COMPLETED / ACTION_TRANSFER_NOT_SUPPORTED |

V4保持冻结。任何使用2025答案继续调参的工作必须进入新版本，并使用新的模型未见行动进行正式测试。
