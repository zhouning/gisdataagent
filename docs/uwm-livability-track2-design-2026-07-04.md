# UWM-Livability for Urban Cup 2026 Track 2: Design Memo

日期：2026-07-04

## 1. 这份文档的目的

这份文档固化当前关于 UWM（Urban World Model）参加 Urban Cup 2026 Track 2 的设计判断，避免后续实现时退化成临时脚本、指标堆叠或前端 demo。

必须吸取 TWM 早期教训：不能先写一批看起来能跑的代码，再回头补理论、补数据边界、补验证。UWM 必须先定义清楚：

- 要解决的城市科学问题；
- 为什么它是 world model，而不是传统宜居性指数；
- 现有数据基础与缺口；
- MMFE 如何参与数据融合并在过程中被完善；
- 公开数据、受限数据、合成数据的使用边界；
- 如何持续记录材料，满足 Track 2 对研究报告、数据说明、可复现代码、AI 协作过程记录和研究日志的提交要求。

本文档是 UWM-Livability 的初始设计备忘录，不是最终实现计划。后续进入代码实现前，应再拆成正式 spec、数据契约和实施计划。

## 2. 赛道 2 约束

Urban Cup 2026 Track 2 是 Urban Science Vibe Research。它不限定固定数据集、固定问题或 leaderboard，而是评估团队是否能借助 AI 工具完成端到端城市科学研究。

该赛道的核心评价点包括：

- 研究问题的重要性与新颖性；
- 数据来源的创造性；
- 分析过程的严谨性和可复现性；
- AI 协作过程的有效记录；
- 发现对城市科学的价值。

因此，UWM 不能以“做一个城市宜居性分析工具”为目标结束，而应以：

```text
构建一个可复现、可审计、可反事实推演的 Urban World Model，
并用它研究城市宜居性、气候健康风险和空间公平。
```

作为 Track 2 的研究主线。

## 3. 业务场景定义

建议业务场景：

```text
面向气候健康与空间公平的城市宜居性世界模型：
以重庆中心城区为核心，评估规划干预对热暴露、空气污染、
服务可达性和社会公平的动态影响。
```

该场景不只回答“哪里宜居”，而要回答：

1. 当前城市中哪些区域处于低宜居性陷阱？
2. 这些低宜居性区域由哪些机制共同造成：热暴露、空气污染、建筑形态、道路活动、公共服务不足、人口脆弱性，还是多因素耦合？
3. 如果采取增绿、公共服务补点、交通减排、建筑强度控制、慢行改善等干预，未来宜居性如何变化？
4. 干预是否真正惠及脆弱人群，而不只是提高平均宜居性？
5. 模型结论哪些可以形成较强证据，哪些只能是 bounded support，哪些只能保留为探索性情景？

## 4. 为什么不是传统宜居性评价

传统宜居性评价通常是：

```text
指标选取 -> 标准化 -> 加权叠加 -> 空间分区 -> 解释
```

UWM-Livability 必须是：

```text
城市观测 O_t
-> 城市隐状态 z_t
-> 干预动作 a_t
-> 状态转移 z_t+1
-> 多目标结果 y_t+k
-> 因果证据与不确定性门控
```

形式化表达：

```text
z_t = Encoder(O_t, G)
z_t+1 = Dynamics(z_t, a_t, e_t, G)
y_t+k = Decoder(z_t+k)
V = Livability(y, equity, uncertainty, evidence)
```

其中：

- `O_t`：遥感、建筑、道路、POI、AOI、人口、通勤、气象、LST、PM2.5/NO2/O3、规划约束等观测；
- `G`：城市空间图，包括空间邻接、道路网络邻接、功能相似邻接、通勤联系；
- `z_t`：城市世界状态，不是单个指数，而是形态、环境暴露、活动强度、服务供给、脆弱性共同构成的状态表示；
- `a_t`：可解释规划干预，例如增绿、降低交通排放、公共服务补点、建筑强度调整、慢行网络优化；
- `e_t`：外生情景，例如高温日、静稳天气、人口增长、交通需求变化；
- `y_t+k`：热风险、空气污染暴露、服务可达性、空间公平和综合宜居性；
- `V`：多目标价值函数，不能只看平均分，必须包含弱势群体和低宜居区域是否改善。

UWM 版宜居性分析相对传统方法必须多出五类能力：

| 能力 | 传统宜居性评价 | UWM-Livability |
| --- | --- | --- |
| 输出 | 静态宜居性指数 | 当前状态、未来预测、干预后变化、不确定性 |
| 数据 | 指标表、POI、遥感 | 多源时空状态、行为、环境、规划约束 |
| 方法 | 加权叠加、AHP、熵权、回归 | 状态表征、动态转移、反事实模拟、因果门控 |
| 解释 | 指标贡献 | 机制链条：形态-活动-环境-健康/公平 |
| 可信度 | 敏感性分析 | SCCA、空间 bootstrap、placebo、残差 Moran、公开 benchmark |

## 5. UWM 与 GWM、TWM 的关系

UWM 和 TWM 都属于 Geospatial World Model（GWM）的子类。

- TWM 面向国土空间、自然资源、地类变化、规划约束和土地利用推演。
- UWM 面向城市形态、城市活动、环境暴露、公共服务、人口脆弱性和城市治理干预。

二者共享世界模型纪律：

```text
Trajectory Dataset
+ Renderer
+ Simulator
+ Planner
+ Benchmark
+ Causal Calibration
+ Evidence Gate
+ Failure Memory
+ Model Registry
+ Claim Boundary
```

UWM 不能只复用 TWM 的展示和报告层。它必须建立自己的城市状态、城市动作、城市轨迹和城市证据边界。

## 6. 总体技术架构

建议 UWM-Livability 分成六层。

### 6.1 Urban Data Foundation

统一管理重庆中心城区及公开 benchmark 数据。该层必须区分：

- 已有真实数据；
- 可公开获取数据；
- 受限但未来可从客户数据库获取的数据；
- 合成或半合成数据；
- 仅用于 smoke test 的占位数据。

所有数据进入 UWM 前必须有数据 manifest，至少记录：

- 数据名称；
- 来源；
- 获取日期；
- 空间范围；
- 时间范围；
- CRS/SRID；
- 许可或使用限制；
- 是否为合成数据；
- 是否允许用于生产结论；
- 质量问题；
- 下游用途。

### 6.2 Spatial Unit and Graph Layer

UWM v0 建议使用：

```text
250m/500m grid + 街区/建筑补充层
```

图结构至少包括：

- 空间邻接图；
- 道路网络邻接图；
- 功能相似图；
- 通勤或 OD 联系图；
- 环境传播邻接，例如热环境/污染扩散近邻。

### 6.3 Urban State Encoder

状态编码器把多源观测转成 `z_t`。

Paper58 / AlphaEarth 的定位：

- 可作为遥感语义状态基座；
- 可提供建设强度、地表状态、变化筛查和空间 allocation prior；
- 不能被直接描述为完整 UWM 动态模拟器；
- 不能替代城市活动、空气污染、公共服务、人口脆弱性和规划约束数据。

UWM 状态应包含：

- 地表遥感状态；
- 建筑形态状态；
- 道路与交通暴露状态；
- POI/AOI 功能状态；
- 绿地、水体和冷岛状态；
- 热环境状态；
- 空气污染暴露状态；
- 公共服务可达性状态；
- 人口与脆弱性状态；
- 规划约束状态；
- 数据质量和证据覆盖状态。

### 6.4 Scenario Dynamics Layer

这是 UWM 与普通宜居性评价的核心差异。

UWM 必须支持动作条件推演：

```text
predict_next(encoded_state, action, scenario)
rollout(initial_state, action_sequence, scenario)
score_transition(prediction, truth)
```

初始动作集合：

- 增加绿地或树冠覆盖；
- 降低道路交通强度或排放；
- 调整建筑密度/高度；
- 增设公共服务设施；
- 优化慢行或公共交通可达性；
- 极端高温或静稳天气压力测试；
- 多动作组合策略。

输出不应是一个单点预测，而应包含：

- `future_state_delta`；
- `livability_delta`；
- `heat_risk_delta`；
- `air_pollution_exposure_delta`；
- `service_accessibility_delta`；
- `equity_delta`；
- `uncertainty_interval`；
- `simulator_trace`；
- `claim_boundary`。

### 6.5 Causal Evidence Layer

UWM 不能把相关性当因果。所有干预效果都必须经过证据门控。

Paper6 / SCCA 的定位：

- 提供空间因果诊断；
- 检查平衡性、共同支撑、空间 bootstrap、placebo、残差空间自相关；
- 形成 `core_support`、`bounded_support`、`fragile` 等证据等级；
- 把可疑反事实结论降级为探索性情景。

EPA benchmark 的定位：

- Paper6 分支中的 EPA Green Book / Census county 数据已经形成过公开 policy-structure semi-synthetic benchmark；
- 当前落地版本不是完整 AQS PM2.5 观测浓度面板，而是“真实 EPA 政策地理结构 + 半合成已知效应污染结果”；
- 它适合作为 UWM-Air 的公开可复现验证场；
- 它不能替代重庆本地空气污染观测数据。

### 6.6 Livability Report and Submission Layer

输出必须服务 Track 2 提交。

UWM 不只产出地图，还要产出：

- 研究问题与假设；
- 数据说明；
- 可复现实验代码；
- AI 协作日志；
- 模型架构说明；
- 干预情景和结果图；
- 证据等级表；
- 失败案例和边界声明；
- 城市科学发现总结。

## 7. MMFE 在 UWM 中的角色

MMFE 是 UWM 数据基础的主入口，不是旁路工具。

当前 MMFE 已有五阶段生命周期：

```text
Profiling -> Assessment -> Alignment -> Execution -> Validation
```

并已支持：

- 多源数据探测；
- 兼容性评估；
- 语义字段对齐；
- 融合执行；
- 质量验证；
- 语义产品生成；
- Lakehouse / STAC / OKF / TWM 对接方向。

UWM 应复用并扩展这条路线。

### 7.1 UWM 对 MMFE 的消费契约

参照现有 `mmfe.twm_state_input.v1`，UWM 应新增类似契约：

```text
mmfe.uwm_state_input.v1
```

该契约至少包括：

- urban spatial unit registry；
- layer role bindings；
- canonical field bindings；
- temporal alignment summary；
- spatial graph relation summary；
- environmental exposure components；
- service accessibility components；
- mobility / activity components；
- population vulnerability components；
- planning constraint components；
- synthetic-source flags；
- data quality warnings；
- production policy；
- AI grounding metadata。

### 7.2 在使用 MMFE 的过程中完善 MMFE

UWM 实现不能只把 MMFE 当作黑盒。每遇到城市数据融合需求，应反哺 MMFE。

建议的 MMFE 改进项：

1. **城市 POI/AOI 语义本体**
   - 建立教育、医疗、公园、交通、商业、养老、文化等城市服务类别映射；
   - 支持高德、百度、OSM、公开统计口径之间的类别对齐。

2. **时空对齐能力**
   - 支持年、月、日、小时等不同时间粒度对齐；
   - 记录时序插值、最近邻匹配、窗口聚合的规则和误差。

3. **栅格-矢量-点-流融合**
   - LST、NDVI、AlphaEarth、空气污染栅格；
   - POI/AOI 点面；
   - 建筑面；
   - OD/通勤流；
   - 道路网络。

4. **城市图构建产物**
   - 从融合结果直接产出空间邻接、道路邻接、功能相似、通勤联系等图结构；
   - 供 UWM encoder 和 dynamics 使用。

5. **合成数据与受限数据标记**
   - 每个字段和图层必须记录 `synthetic`、`semi_synthetic`、`restricted_expected`、`public_proxy`；
   - 任何合成字段不能被误用于生产级事实声明。

6. **证据与质量 sidecar**
   - 每次融合必须产出质量评分、字段对齐置信度、CRS 风险、时间错配风险、空间覆盖缺口；
   - UWM 的 evidence gate 必须消费这些 sidecar。

7. **UWM state-input builder**
   - 类似 `build_twm_state_input_from_semantic_product`，新增 UWM 消费函数；
   - 明确 `source_of_truth_geometry_and_attributes` 与 `semantic_product_usage` 的边界。

## 8. 数据基础现状与补齐策略

### 8.1 已有或已检查的数据资产

来自规划院样例和既有工作：

- 重庆 DEM；
- CLCD 重庆土地覆盖；
- OSM roads 2021；
- 重庆中心城区建筑轮廓与楼层；
- 高层建筑样本；
- 历史街区；
- 2024 高德 POI；
- 2024 百度 AOI；
- 区县人口；
- 联通通勤 CSV，但缺少 grid geometry；
- 百度搜索指数 OD 线；
- 璧山规划数据库，包括现状/规划用地、保护控制层、项目/审查意见。

Paper6：

- 重庆 UHI：建筑高度暴露、LST 结果、土地覆盖/高程/城市上下文调整；
- CountyData：社会资本、长寿、空气污染等县级示例；
- EPA Green Book benchmark：PM2.5 非达标政策地理结构 + Census county geometry + 半合成已知效应；
- Snow / Soho SCCA 示例；
- GeoFM / AlphaEarth ablation。

Paper58：

- AlphaEarth / GeoFM 表征；
- LAS / FLUS hybrid allocation style；
- 遥感语义状态和 allocation prior。

### 8.2 UWM 缺口

当前 UWM 最大数据缺口：

- 重庆本地空气污染观测或公开代理；
- 气象扩散条件；
- 人口脆弱性；
- 公共服务设施的可靠分类与服务半径；
- 通勤 OD 的空间单元几何；
- 多年份城市状态轨迹；
- 干预动作的真实或合理情景参数；
- 可验证的时间 holdout。

### 8.3 公开数据优先策略

能从公开渠道补齐的，优先公开获取并通过 MMFE 入库。

候选公开数据方向：

- OSM / Geofabrik：道路、POI、建筑、绿地、水体；
- Sentinel-2 / Landsat / MODIS：NDVI、NDBI、LST、土地覆盖辅助；
- Google Earth Engine：遥感产品再提取；
- GHSL / WorldPop / LandScan 类人口栅格：人口分布代理；
- ERA5：温度、风、湿度、降水、边界层等气象驱动；
- CAMS / MERRA-2 / MAIAC AOD / OpenAQ：空气污染或污染代理；
- 统计年鉴和公开政府数据：区县人口、公共服务、经济社会属性；
- OpenStreetMap transit / road network：交通与可达性代理。

公开数据接入原则：

```text
先记录来源和许可证 -> 再入 MMFE profiling -> 再做 schema/CRS/time 对齐
-> 再发布 UWM state-input -> 再进入模型。
```

### 8.4 受限数据与合成数据策略

实际项目中，部分权威数据来自客户数据库，当前阶段拿不到。不能因此停止 UWM，但必须严格标记边界。

允许使用合成数据的场景：

- smoke test；
- pipeline 验证；
- UI/报告联调；
- 已知效应 causal benchmark；
- 缺失权威字段的结构占位；
- 情景压力测试。

合成数据必须满足：

- 有显式生成规则；
- 有随机种子；
- 有 manifest；
- 标记 `synthetic` 或 `semi_synthetic`；
- 不用于事实性城市结论；
- 不与真实观测混淆；
- 报告中明确说明仅用于验证流程或机制。

这条纪律必须写入 UWM 的 claim boundary。

## 9. UWM-Air 模块

UWM-Air 是 UWM-Livability 的环境暴露子模块。

### 9.1 EPA 的作用

EPA Green Book benchmark 有用，但边界明确：

- 它提供公开、可复现的空气污染政策结构；
- 它能检验 UWM-Air 是否处理空间邻接、政策暴露、溢出和证据降级；
- 它目前不是完整 AQS PM2.5 观测浓度面板；
- 它不能替代重庆本地空气污染数据。

### 9.2 重庆空气污染补齐

重庆 UWM-Air 应优先寻找：

- 国控/市控空气质量站点；
- OpenAQ 或其它公开站点记录；
- CAMS / MERRA-2 / MAIAC AOD / 遥感 PM2.5 代理；
- ERA5 气象驱动；
- 道路、POI、工业/商业活动、建筑密度、绿地水体等暴露驱动。

如果真实站点数据暂时不可得，可先构建：

```text
公开污染代理 + 合成校准层 + 证据边界
```

但必须明确它不能产生生产级污染事实结论。

## 10. UWM-Livability 初始任务

UWM v0 不做泛化万能城市大脑，只做一个可控、可复现、能提交 Track 2 的研究系统。

建议 v0 范围：

- 主区域：重庆中心城区；
- 辅助区域：璧山作为 urban-rural fringe / planning bridge，不作为主战场；
- 主问题：热暴露 + 空气污染 + 服务可达性 + 空间公平；
- 主动作：增绿、交通减排、服务补点、建筑强度调整、慢行改善；
- 主验证：传统宜居性指数 baseline、Paper6 SCCA、Paper58/AlphaEarth 表征、EPA UWM-Air benchmark；
- 主产物：研究报告、数据说明、可复现实验代码、AI 协作日志、情景地图、证据等级表。

## 11. 传统 baseline 必须保留

为了证明 UWM 方法有必要，必须先构建传统 baseline：

```text
传统宜居性指数 = 指标标准化 + 权重叠加 + 空间分区
```

候选指标：

- 热环境；
- 空气污染；
- 绿地可达性；
- 公共服务可达性；
- 交通可达性；
- 建筑密度；
- 人口密度；
- 脆弱性。

然后 UWM 必须超越它：

- 能预测干预后变化；
- 能解释机制链条；
- 能输出不确定性；
- 能区分证据等级；
- 能识别平均改善背后的公平性损失；
- 能在公开 benchmark 上复现。

没有 baseline，就无法证明 UWM 不是换名的指标体系。

## 12. 赛道 2 提交材料记录制度

从第一天起，UWM 工作必须自动或半自动保留以下材料。

### 12.1 研究日志

建议路径：

```text
docs/reports/uwm_track2_research_log.md
```

记录：

- 每次研究问题变化；
- 数据发现过程；
- AI 协作过程；
- 失败尝试；
- 数据缺口；
- 模型边界调整；
- 重要实验结论。

### 12.2 数据清单

建议路径：

```text
docs/reports/uwm_data_foundation_manifest.csv
docs/reports/uwm_data_foundation_manifest.md
```

字段至少包括：

- dataset_id；
- dataset_name；
- source_type；
- source_url_or_local_path；
- public/restricted/synthetic；
- spatial_extent；
- temporal_extent；
- geometry_type；
- crs；
- license；
- lineage；
- quality_score；
- used_by；
- claim_boundary。

### 12.3 AI 协作记录

必须保留：

- 对话摘要；
- 设计决策；
- 代码变更记录；
- 数据获取记录；
- 自动生成内容与人工判断的边界；
- 被拒绝或降级的模型声明。

### 12.4 可复现实验记录

每个实验必须输出：

- config；
- input manifest；
- command；
- code commit；
- environment；
- random seed；
- output path；
- metrics；
- evidence grade；
- failure notes。

## 13. UWM claim boundary

UWM 输出必须区分四类声明：

1. **Factual observation**
   - 来自真实数据和可追溯来源；
   - 可用于描述当前状态。

2. **Model prediction**
   - 来自 world model rollout；
   - 必须附带不确定性和验证结果。

3. **Causal / counterfactual claim**
   - 需要 SCCA 或其它因果证据门控；
   - 未通过门控只能降级。

4. **Synthetic / exploratory scenario**
   - 用于机制演示、压力测试、流程验证；
   - 不能作为真实城市结论。

推荐证据等级：

```text
core_support
bounded_support
fragile
exploratory_only
not_for_claim
```

## 14. 初始实施路线

### Phase 0: Design Gate

- 固化 UWM 理论定义；
- 固化业务场景；
- 固化数据 manifest schema；
- 固化 MMFE -> UWM state-input 契约；
- 固化 Track 2 材料记录制度。

### Phase 1: Data Foundation

- 盘点已有重庆中心城区数据；
- 把规划院样例、Paper6、Paper58、公开数据候选纳入统一 manifest；
- 使用 MMFE 做 profiling、alignment、fusion validation；
- 产出第一版 `mmfe.uwm_state_input.v1`。

### Phase 2: Traditional Baseline

- 构建传统宜居性指数；
- 作为 UWM 必须超越的 baseline；
- 输出 baseline 地图和敏感性分析。

### Phase 3: UWM State and Scenario Runtime

- 构建城市状态 `z_t`；
- 接入 AlphaEarth / GeoFM 表征；
- 定义规划动作；
- 实现初始 rollout；
- 每次 rollout 输出 simulator trace。

### Phase 4: Evidence Gate

- 接入 Paper6 SCCA；
- 对热环境、空气污染、服务可达性等模块做因果/空间诊断；
- 接入 EPA UWM-Air benchmark；
- 输出证据等级。

### Phase 5: Track 2 Submission Package

- 研究报告；
- 数据说明；
- 可复现代码；
- AI 协作记录；
- 研究日志；
- 图表与可视化；
- 结果边界声明。

## 15. 当前不可偷懒的硬约束

1. 不能只做静态宜居性指数。
2. 不能用几个脚本和地图冒充 UWM。
3. 不能把 AlphaEarth 说成完整城市世界模型。
4. 不能把 Paper6 EPA benchmark 说成重庆空气污染数据。
5. 不能混淆真实、公开代理、受限预期、合成数据。
6. 不能让 planner 绕过 simulator trace。
7. 不能让反事实结论绕过 evidence gate。
8. 不能忽略传统 baseline。
9. 不能等到最后才整理 Track 2 提交材料。
10. 不能在没有数据 manifest 和 claim boundary 的情况下做强结论。

## 16. 下一步建议

下一步不应直接写 UWM 算法代码，而应先完成三件事：

1. 写正式 `UWM-Livability Track 2 Design Spec`。
2. 定义 `mmfe.uwm_state_input.v1` 数据契约。
3. 建立 `uwm_data_foundation_manifest` 和 `uwm_track2_research_log` 初始文件。

完成这三件事后，再进入实现计划和代码开发。
