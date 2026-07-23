# GWM-Bench Foundation V4.0

## 当前状态

BENCHMARK_COMPLETED / ACTION_TRANSFER_NOT_SUPPORTED

V4.0已经完成问题定义、rc1周尺度数据包、Runtime-R3、五个模型、六项负对照、35项预测重放、
预测承诺和正式评分。行动模型优于同结构无行动模型，但未超过简单AR基线，并被CBD范围重连负对照
反超，因此benchmark完成而行动迁移主张不成立。

冻结的suite_protocol.json保留预测前状态，不应为了显示进度而事后改写。当前执行状态以
runtime_r3_evaluator_seal.json为准。

V4只新增一个问题：模型从2019和2022两次真实政策变化中学习后，能不能在完全不使用
2025行动后结果进行训练、调参或归一化的条件下，预测纽约拥堵收费开始后的12周出租车空间运行状态。

这是一场“模型未见行动迁移考试”。它不是政策因果评估，也不声称2025答案从未被研究人员看过。

## 为什么选这个场景

- 72个月度TLC文件、349,782,159条原始记录已经在本机；
- 263个Taxi Zone边界、CBD暴露范围、2019/2022/2025政策日期和数值都有官方来源；
- 不需要继续等下载，也不需要水库调度记录；
- 2019和2022用于训练，2025是模型未见的新空间行动；
- 可以直接检验“行动参数和空间暴露是否真的给预测带来价值”。

2015封存测试没有被删除，但不作为V4主场景。原因是它虽然盲性更强，却落在训练行动的联合支持
之外，而且一次性测试已经失败。它适合作为公开的反证材料，不适合继续充当新版本的主考试。

## 固定数据

| 项目 | V4定义 |
| --- | --- |
| 场景 | 纽约黄牌出租车在真实价格与拥堵收费变化下的空间运行 |
| 空间单元 | 263个NYC TLC Taxi Zone |
| 时间单元 | 从政策生效日对齐的7天块 |
| 训练行动 | 2019纽约州拥堵附加费、2022计价器费率调整 |
| 测试行动 | 2025-01-05 MTA Congestion Relief Zone收费 |
| 每次行动输入 | 52周行动前状态 |
| 每次行动输出 | 12周行动后状态 |
| 预测目标 | pickup、dropoff、CBD inflow、CBD outflow |
| 训练区周行 | 33,664 |
| 测试输入区周行 | 13,676 |
| 测试目标区周行 | 3,156 |
| 全部区周行 | 50,496 |

三个窗口固定为：

| 事件 | 行动前52周 | 行动后12周 |
| --- | --- | --- |
| 2019 | 2018-02-03至2019-02-01 | 2019-02-02至2019-04-26 |
| 2022 | 2021-12-20至2022-12-18 | 2022-12-19至2023-03-12 |
| 2025 | 2024-01-07至2025-01-04 | 2025-01-05至2025-03-29 |

## 技术架构

V4把V3的Runtime-R2扩展为Runtime-R3：

    官方TLC与MTA数据
      -> ZoneWeekStateSnapshot
      -> NumericActionSpec
      -> MultiRelationSpatialGraph
      -> GWM Runtime-R3
           -> UWM / DAM-GK action-conditioned adapter
           -> no-action DAM-GK adapter
           -> simple baseline adapters
      -> 12步开环预测
      -> 统一评分与审计凭证

Runtime-R3负责状态、行动、空间图、递推、哈希、重放和失败记录。DAM-GK负责模型内部的空间动力学：
地理邻接、OD流、行动暴露三类关系先分别传递信息，再由数值行动参数调制Graph-GRU状态转移。

模型不能读取政策名称或事件ID，只能读取数值行动含义和冻结的空间暴露范围。

## 固定模型与对照

正式比较包含：

1. UWM / DAM-GK行动条件模型；
2. 同结构但删除行动输入的DAM-GK；
3. 固定邻接空间自回归；
4. 非空间历史自回归；
5. 52周季节不变基线。

行动机制必须额外经受六项检查：行动删除、日期前移4周、日期后移4周、行动分量打乱、CBD边界
重连、空间暴露打乱。

## 评分

主指标是宏平均行动前归一化MAE，越低越好：每个区、每个目标先用该区行动前52周均值做尺度，
然后对263个区、4个目标以及第1、2、4、8、12周等权平均。这样不会让曼哈顿高流量区完全支配结果。

“行动迁移成立”必须同时满足：

- 行动条件模型优于同结构无行动模型；
- 两者差值的263区配对bootstrap 95%区间完全低于0；
- 至少3/4目标和4/5报告时点方向一致；
- 正确行动语义优于行动分量打乱和CBD边界重连。

benchmark是否完成不取决于TWM获胜。失败结果必须完整发布。

## 预检

运行：

    .venv/bin/python benchmarks/gwm_bench_foundation_v4_0_draft/preflight_v4_draft.py

预检只读取JSON清单、文件元数据和Parquet footer，不扫描2025行动后目标行。当前预检27项全过，
数据下载、定义和硬盘检查均无阻塞。

## rc1与封存结果

| 项目 | 正式状态 |
| --- | --- |
| rc1 bundle | PASS_V4_RC1_DATA_VERIFIED，22项全过 |
| 训练周行 | 33,664 |
| 测试历史输入周行 | 13,676 |
| 测试行动行 | 3,156 |
| 测试目标行 | 3,156，独立目录隔离 |
| 图边 | 3,009 |
| 评分器构造答案 | PASS_ACTION_A4_EVALUATOR_CONFORMANCE，15项全过 |
| Runtime与评分器 | BENCHMARK_COMPLETED / ACTION_TRANSFER_NOT_SUPPORTED |

正式结果：`final_results/action_a4_results.json`。

完整中文报告：`docs/research/GWM_BENCHMARK_V4_0_FINAL_REPORT_2026-07-23.md`。

关键指纹：

| 对象 | SHA256 |
| --- | --- |
| 协议 | 54152f65433440fb28fb8d9aeb605685b7e81bbade11bed229ce50dd7abb9950 |
| rc1 manifest | dfe3fd7ae490ac2b8a2522ba77df4a111017302eabd579544b1a3300f1020acd |
| rc1 verification | cb48b7d532aa778b233997e7ff73bdba3837494296adc8f88bcf9c1da089a049 |
| evaluator conformance | a20b2990477197c2b7799b99cab5dbc2b55a496a93da4498cf52c5739803e8d6 |
| Runtime-R3/evaluator seal | 93c8a7f3335bf9c4e7338c6490f951119bc6542e5f6a87fb2656aa901674528c |

机器规则见 suite_protocol.json，完整中文定义见
docs/research/GWM_BENCHMARK_V4_0_DEFINITION_AND_EXECUTION_PLAN_2026-07-23.md。
