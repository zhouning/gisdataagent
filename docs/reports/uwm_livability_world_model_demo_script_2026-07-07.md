# 城市宜居性分析（UWM）演示脚本说明

版本日期：2026-07-07  
演示入口：`http://localhost:8000`  
演示页面：`工作台 -> 智能分析 -> 城市宜居性分析（UWM）`  
适用场景：在 GIS Data Agent 中演示 UWM 世界模型方法基于同一套城市宜居性数据，如何输出传统静态方法无法直接得到的反事实决策包。

## 1. 文档目的

本文档用于现场演示和内部复核，说明当前已经实现的“城市宜居性分析（UWM）”功能：

1. 城市宜居性分析的业务理论依据是什么；
2. UWM 相比传统方法的技术机制差异是什么；
3. UWM 读取了哪些真实本地准备数据和公开代理数据；
4. 数据经过了哪些处理，如何进入 renderer、simulator 和 planner；
5. 当前 UWM 最终输出什么结果；
6. 如何解释这些结果，可解释性和证据边界在哪里；
7. 当前结果表达方式是否适合客户演示，以及还可以如何增强。

本文档只描述 UWM 世界模型方法。传统方法的对应演示说明见：

```text
docs/reports/uwm_traditional_livability_demo_script_2026-07-07.md
```

## 2. 演示核心口径

当前 UWM 回答的问题不是：

```text
当前哪些地方分数最低？
```

而是：

```text
在同一套重庆中心城区城市宜居性数据基础上，
如果采取某个行动序列，
未来宜居性、空气污染暴露、服务可达性、公平性和邻近单元会如何变化，
并且这个行动序列为什么比传统静态优先级策略更好？
```

因此，UWM 的最终输出不是单纯的宜居性排名图，而是：

```text
城市宜居性反事实决策包
```

现场讲解时必须明确：当前 UWM 可以支持 `bounded_support` 级别的离线反事实规划结论，即在同一数据、同一场景、同一传统静态基线下，UWM 输出的行动序列在端点对齐、风险校正、空间外溢和单动作回放分布上优于传统静态策略。当前不能声称已经在真实政策实施后的 observed policy outcome 上证明优于传统治理方法。

## 3. 城市宜居性业务理论基础

UWM 城市宜居性分析延续此前理论文档中的业务基础：

```text
docs/reports/uwm_livability_theory_sources_and_standards_2026-07-05.md
docs/reports/uwm_livability_business_theory_2026-07-05.md
```

城市宜居性不是一个单一指标，也不是单一国家标准能够完整定义的对象。它是城市复杂巨系统中环境、服务、人口、空间公平、交通活动和规划可实施性共同作用的结果。

当前 UWM 采用的业务理论可以概括为：

```text
城市宜居性
= 环境健康风险
+ 公共服务可达性
+ 15 分钟生活圈/日常活动便利性
+ 绿地与开放空间
+ 人口暴露公平性
+ 城市形态和开发强度约束
```

其理论和标准支撑包括：

| 理论/标准来源 | 对 UWM 的支撑 |
| --- | --- |
| 健康城市与健康社会决定因素 | 城市空间条件会影响居民健康、服务机会、活动机会和社会参与 |
| 城市环境质量与人类福祉 | 宜居性应同时看物理环境、居民福利、社会差异和空间分布 |
| 城市规划与人口健康 | 土地利用、交通、密度、公共空间、空气污染和步行环境共同影响健康 |
| 15 分钟城市/15 分钟生活圈 | 居民应在合理时间、距离和成本内获得基本生活服务 |
| 空间公平与环境正义 | 不能只优化全市平均值，还要看高暴露、低服务、脆弱区域是否受益 |
| `GB 3095-2026 环境空气质量标准` | 支撑 PM2.5 等空气污染暴露评价口径 |
| `GB 50180-2018 城市居住区规划设计标准` | 支撑居住区服务设施、生活圈和公共服务配套评价 |
| `GB/T 51346-2019 城市绿地规划标准` | 支撑绿地、开放空间和生态环境改善类动作 |
| `GB/T 51255-2017 绿色生态城区评价标准` | 支撑绿色生态城区、人居环境和可持续评价 |

传统方法也可以使用这些理论来构建静态指标体系，但它只能回答“当前哪里差”。UWM 进一步把这些理论变成可模拟、可规划、可验证的状态转移问题。

## 4. 为什么传统方法不够

传统城市信息化模式通常是指标大屏或驾驶舱增强版。它可以做：

```text
多源指标汇总
静态综合评分
行政单元排名
风险/短板识别
TOP N 治理优先区
静态规则建议
```

这类方法的最终输出是：

```text
当前哪里差、差在哪些维度、哪些地方优先关注。
```

它不直接输出：

```text
采取某个行动后未来状态如何变化；
多个行动按什么顺序执行更好；
行动是否影响相邻单元；
在不确定性下是否仍然值得做；
端点权重变化后结论是否稳健；
行动序列是否胜过单动作或静态启发式基线。
```

UWM 的实质性进步不是“图表更多”，而是把城市宜居性从静态评价推进到世界模型决策：

```text
Renderer:  D -> s_t
Simulator: (s_t, a_t) -> s_{t+1}, r, uncertainty
Planner:   search over a_{1:H}
```

这意味着 UWM 不是把传统方法包装得更好看，而是在同一数据基础上输出传统方法无法直接获得的反事实决策结果。

## 5. UWM 技术实现机制

### 5.1 Renderer：把多源城市数据渲染为世界状态

这里的 renderer 不是前端可视化，而是状态构造器。它将多源 GIS、环境、服务、人口、道路、建筑形态和邻接关系数据统一到 36 个重庆中心城区行政单元上，形成可被 simulator 和 planner 使用的城市状态 `s_t`。

当前 renderer 对应的核心场景产物为：

```text
data/uwm_public_proxy/chongqing_central/multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json
```

关键状态字段包括：

```text
livability_need_score
exposure_priority_score
service_gap_norm
essential_service_gap_norm
tap_scene_pm25_mean_ugm3
chap_pm25_ugm3
gee_cams_pm25_ugm3
ghsl_population_proxy_sum
ghsl_built_surface_proxy_sum
admin_graph_degree
osm_road_segment_count
osm_road_length_degrees_proxy
osm_bbox_area_degrees2
```

同时，UWM 端点验证还投影了 2.5D 建筑楼层形态：

```text
data/uwm_public_proxy/chongqing_central/building_floor_morphology_2026_07_07/uwm_building_floor_morphology.json
```

注意：当前是 2D/2.5D 城市状态，不是完整 3D mesh、BIM 或 point-cloud 城市模型，不能把它夸大为完整三维城市世界。

### 5.2 Simulator：模拟行动条件下的状态变化

simulator 是 UWM 区别于传统方法的核心。传统方法只能看当前指标，simulator 必须回答：

```text
如果采取行动 a_t，未来状态 s_{t+1} 会怎样变化？
```

当前 simulator 使用 data-calibrated mechanism table 替代纯手写硬编码系数。对应产物为：

```text
data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json
```

其机制系数由以下真实准备数据和公开代理证据缩放校准：

| 证据来源 | 用途 |
| --- | --- |
| OpenAQ 空气质量观测代理 | 校准空气污染动态状态证据 |
| TAP PM2.5 2018-2024 网格数据 | 校准 PM2.5 时间转移证据 |
| station-aligned air quality holdout | 约束空气质量 holdout 误差 |
| NOAA ISD 重庆气象观测 | 校准热环境尺度 |
| admin livability target panel | 校准服务缺口、公平性和宜居性需求尺度 |

当前模拟器可处理的动作类型包括：

```text
increase_green_infrastructure
cool_roofs
traffic_emission_control
add_community_service
```

当前最优行动序列选择了 `increase_green_infrastructure`，原因是目标单元满足：

```text
mask_reason = heat_risk_above_threshold
```

simulator 输出的不只是一个分数，而是每个行动导致的未来状态变化：

```text
heat_risk_delta
air_pollution_exposure_delta
service_accessibility_delta
equity_delta
livability_delta
uncertainty_interval
neighbor_spillover
```

### 5.3 Planner：搜索行动序列而不是做静态排序

planner 使用模拟器生成的 rollout，在行动空间中搜索多步行动序列。当前对应产物为：

```text
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json
```

planner 的目标不是简单挑当前分数最低的行政单元，而是寻找：

```text
在热风险、污染暴露、服务可达性、公平性和不确定性约束下，
整体未来收益更高、外溢更好、风险校正后仍然更优的行动组合。
```

当前 planner 的搜索结果再经过以下评估产物进入最终决策包：

```text
data/uwm_public_proxy/chongqing_central/livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json
data/uwm_public_proxy/chongqing_central/endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json
data/uwm_public_proxy/chongqing_central/spatial_spillover_planner_evaluator_2026_07_07/uwm_spatial_spillover_planner_evaluator.json
data/uwm_public_proxy/chongqing_central/livability_decision_package_2026_07_07/uwm_livability_decision_package.json
```

最终由 API 暴露给前端：

```text
GET /api/uwm/livability-decision
```

对应后端和前端实现位置：

```text
data_agent/api/uwm_livability_decision_routes.py
frontend/src/components/datapanel/LivabilityWorldModelTab.tsx
```

## 6. 数据流说明

### 6.1 原始/准备数据

当前 UWM 使用的主场景数据为：

```text
data/uwm_public_proxy/chongqing_central/multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json
```

该场景登记的数据源包括：

| 数据源 | 当前 UWM 中的作用 |
| --- | --- |
| `admin_livability_target_complete_bbox` | 提供宜居性目标和需求状态，是传统和 UWM 共同的数据基础 |
| `admin_exposure_equity` | 提供人口暴露和公平性状态 |
| `admin_service_accessibility_complete_bbox` | 提供公共服务可达性和基本服务缺口 |
| `ghsl_admin_alignment` | 提供人口和建成面代理状态 |
| `gee_admin_environment` | 提供 GEE/CAMS 环境代理状态 |
| `scene_aligned_gridded_air_quality_holdout` | 提供 TAP/CHAP PM2.5 场景对齐空气质量数据和 holdout 端点 |
| `admin_spatial_adjacency_graph` | 提供行政单元邻接图，用于空间外溢评估 |
| `unicom_latent_mobility_graph` | 已纳入数据基础记录；因缺少网格到行政单元稳定 crosswalk，当前不直接投影进决策包计分 |
| `osm_mobility_network_proxy` | 提供道路网络代理状态 |
| `osm_admin_mobility_crosswalk` | 将 OSM 道路段投影到行政单元状态向量 |

覆盖复核口径：

| 项目 | 当前值 |
| --- | --- |
| 行政单元数量 | 36 |
| 暴露公平性匹配 | 36/36 |
| 服务可达性匹配 | 36/36 |
| GHSL 匹配 | 36/36 |
| GEE 环境匹配 | 36/36 |
| PM2.5 场景对齐匹配 | 36/36 |
| 行政邻接图源节点/边 | 1,017 / 2,847 |
| OSM 道路网络节点/边 | 42,058 / 45,468 |
| OSM 已分配道路段 | 45,449 |
| OSM 未分配道路段 | 19 |
| 联通潜在流动图节点/边 | 756 / 1,067 |

### 6.2 处理链路

当前 UWM 数据流可以按以下链路理解：

```text
多源原始/准备数据
-> 行政单元空间对齐与 state_vector 构造
-> multisource_livability_scene
-> building_floor_25d_morphology 投影
-> livability_endpoint_suite
-> data_calibrated_mechanism_table
-> data_calibrated_model_based_graph_search
-> endpoint_aligned_planner_evaluator
-> spatial_spillover_planner_evaluator
-> livability_decision_package
-> traditional_vs_world_model_demo
-> /api/uwm/livability-decision
-> 城市宜居性分析（UWM）前端页面
```

这条链路体现了 UWM 和传统方法的根本差异：

| 阶段 | 传统方法 | UWM |
| --- | --- | --- |
| 数据输入 | 同一多源场景 | 同一多源场景 |
| 状态表达 | 当前指标和综合排序 | renderer 构造可模拟状态 `s_t` |
| 行动建模 | 静态规则建议 | simulator 建模 `(s_t, a_t) -> s_{t+1}` |
| 决策方式 | 当前短板排序 | planner 搜索行动序列 |
| 输出结果 | 静态问题清单 | 反事实决策包 |
| 证据边界 | 当前状态解释 | 离线回放、端点验证、风险校正、空间外溢，非真实政策 outcome |

## 7. 当前 UWM 的最终结果

当前 API schema 为：

```text
uwm.livability_decision_api.v1
```

同数据契约为：

| 项目 | 值 |
| --- | --- |
| `scene_id` | `uwm-multisource-livability-scene-2026-07-06` |
| `admin_unit_count` | 36 |
| `same_data_basis` | `true` |
| `same_livability_scenario` | `true` |
| 使用的世界模型组件 | `renderer`, `simulator`, `planner` |

当前 UWM 推荐的行动序列为：

| 步骤 | 动作 | 目标行政单元 | 强度 | 动作掩码原因 |
| --- | --- | --- | --- | --- |
| 1 | 增加绿色基础设施 | `江北区|观音桥街道|653` | 1.0 | `heat_risk_above_threshold` |
| 2 | 增加绿色基础设施 | `九龙坡区|九龙镇|77` | 1.0 | `heat_risk_above_threshold` |

当前优先解释的受益单元包括：

| 行政单元 | 宜居性变化 | 公平性变化 | 污染暴露变化 | 服务变化 |
| --- | ---: | ---: | ---: | ---: |
| `九龙坡区|九龙镇|77` | 0.129847655 | 0.050222700 | -0.077625000 | 0.024560000 |
| `江北区|观音桥街道|653` | 0.129847655 | 0.050222700 | -0.077625000 | 0.024560000 |
| `九龙坡区|杨家坪街道|781` | 0.045446679 | 0.017577945 | -0.027168750 | 0.008596000 |
| `九龙坡区|石坪桥街道|782` | 0.045446679 | 0.017577945 | -0.027168750 | 0.008596000 |
| `九龙坡区|谢家湾街道|785` | 0.045446679 | 0.017577945 | -0.027168750 | 0.008596000 |
| `江北区|五里店街道|603` | 0.045446679 | 0.017577945 | -0.027168750 | 0.008596000 |

结果解读：

```text
livability_delta > 0       表示模拟后综合宜居性改善；
equity_delta > 0            表示公平性改善；
air_pollution_exposure_delta < 0 表示污染暴露下降；
service_accessibility_delta > 0  表示服务可达性改善。
```

## 8. 与传统方法的同数据对照结果

传统方法输出：

```text
final_output_type = static_problem_ranking
top_priority_units = 九龙坡区|九龙镇|77, 南岸区|南坪镇|299
counterfactual_output_available = false
simulator_used = false
planner_used = false
```

UWM 输出：

```text
final_output_type = counterfactual_decision_package
target_units = 江北区|观音桥街道|653, 九龙坡区|九龙镇|77
counterfactual_output_available = true
```

UWM 当前相对传统静态启发式的证据为：

| 指标 | 值 | 解释 |
| --- | ---: | --- |
| `endpoint_aligned_advantage_over_static` | 0.000745700 | 在验证端点加权口径上，planner 序列优于传统静态策略 |
| `endpoint_aligned_advantage_ratio` | 2.127273 | planner 端点对齐分数约为传统静态策略的 2.127 倍 |
| `risk_adjusted_advantage_over_static` | 0.012777213 | 扣除不确定性惩罚后仍优于传统静态策略 |
| `neighbor_livability_delta_advantage` | 0.272680076 | 一阶邻近单元宜居性外溢收益优于传统策略 |
| `planner_benefited_unit_count` | 13 | planner 序列使 13 个行政单元宜居性改善 |
| `static_benefited_unit_count` | 6 | 传统静态单步策略使 6 个行政单元宜居性改善 |
| `single_action_transition_count` | 355 | 与 355 个 single-action replay baseline 对照 |
| `best_sequence_percentile_vs_single_actions` | 1.0 | 当前最优序列位于单动作基线分布顶部 |
| `empirical_one_sided_p_value` | 0.002809 | 相对单动作回放分布的一侧经验 p 值 |

这说明当前 UWM 的优势主要体现在最终结果能力上：传统方法输出“问题排名”，UWM 输出“经过模拟器和规划器验证的行动序列、未来变化、外溢和风险校正证据”。

## 9. 端点验证与稳健性

当前 UWM 最终端点 suite 为：

```text
uwm.livability_endpoint_suite.v1
```

端点验证结果：

| 项目 | 值 |
| --- | --- |
| endpoint 数量 | 3 |
| ready endpoint 数量 | 3 |
| 2.5D 建筑楼层形态是否投影 | `true` |
| 平均相对 MAE 降低 | 0.115337 |
| 最小相对 MAE 降低 | 0.003047 |

端点包括：

```text
air_quality_pm25
service_point_accessibility
essential_service_accessibility
```

端点权重敏感性结果显示 5 种 profile 下 UWM 都优于静态策略：

| profile | planner score | static score | advantage |
| --- | ---: | ---: | ---: |
| `validation_weighted` | 0.001407208 | 0.000661508 | 0.000745700 |
| `equal_weights` | 0.020596063 | 0.009681910 | 0.010914153 |
| `air_only` | 0.012614063 | 0.005929687 | 0.006684375 |
| `service_point_only` | 0.003991000 | 0.001876111 | 0.002114889 |
| `essential_service_only` | 0.003991000 | 0.001876111 | 0.002114889 |

这部分是演示时解释“不是换个权重就消失”的关键证据。但它仍然是离线端点和回放证据，不是政策实施后的真实因果效果。

## 10. 可解释性

当前 UWM 的可解释性来自五层。

### 10.1 数据来源可解释

每个状态变量都能追溯到多源场景数据或后续证据产物。例如：

```text
PM2.5 来自 TAP/CHAP/GEE/CAMS 场景对齐数据；
服务可达性来自 service accessibility 和 OSM 投影；
人口和建成面来自 GHSL；
空间外溢来自行政邻接图；
2.5D 城市形态来自建筑楼层形态投影；
动作机制来自 data_calibrated_mechanism_table。
```

### 10.2 动作选择可解释

当前两个推荐动作都不是任意选择，而是满足：

```text
action_type = increase_green_infrastructure
mask_reason = heat_risk_above_threshold
```

这意味着 planner 选择的是在热风险阈值约束下具有较好未来收益的增绿动作序列。

### 10.3 状态变化可解释

每个目标单元和受益单元都输出：

```text
heat_risk_delta
air_pollution_exposure_delta
service_accessibility_delta
equity_delta
livability_delta
```

因此，客户不仅能看到“推荐做什么”，还能看到“为什么这会改善宜居性”。

### 10.4 空间外溢可解释

UWM 使用行政单元邻接图评估一阶邻近单元收益。当前 planner 的邻近受益单元数为 11，传统静态策略为 5，邻近宜居性变化优势为 0.272680076。

这部分是传统方法很难自然输出的结果，因为传统静态排序通常不会模拟一个行动对周边单元的影响。

### 10.5 证据边界可解释

当前最终决策包明确写入：

```text
max_claim_level = bounded_support
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

现场必须这样解释：

> 当前 UWM 已经能在真实准备数据和公开代理数据基础上输出反事实决策包，并在离线 replay、端点对齐、风险校正、空间外溢和单动作基线分布上支持其优于传统静态策略；但还没有真实政策实施后的 outcome 数据，因此不能说已经完成真实政策效果证明。

## 11. 结果表达方式评价

当前前端页面已经具备客户演示所需的核心表达结构：

| 页面模块 | 表达内容 | 演示价值 |
| --- | --- | --- |
| KPI 区 | 推荐动作、目标单元、风险校正收益、p-value | 快速说明 UWM 输出的是决策包而非排名 |
| 世界模型链路 | renderer / simulator / planner 是否使用 | 明确技术架构没有退化成指标大屏 |
| 同一数据对照 | 传统最终输出 vs UWM 最终输出 | 证明比较是同数据同场景 |
| 强于传统方法的证据 | endpoint、risk、spillover、p-value | 展示 UWM 为什么强于静态策略 |
| 推荐行动序列 | 多步 action sequence | 展示 planner 能力 |
| 反事实状态变化与空间外溢 | 行政单元级 delta 表 | 展示未来影响和可解释性 |
| UWM-only 输出 | multi-step、counterfactual、spillover 等 | 明确传统方法无法直接输出的能力 |
| 证据边界 | bounded_support 和 observed policy claim | 防止越界宣传 |

当前表达方式适合做第一版客户演示，因为它能直观看到传统方法和 UWM 的最终输出差异。但如果要做更强的产品级演示，还建议增强：

1. 地图化展示 `livability_delta`、`air_pollution_exposure_delta` 和外溢受益单元；
2. 传统方法与 UWM 的左右并排对照页；
3. 行动序列时间轴；
4. 不确定性区间可视化；
5. 一键导出“城市宜居性反事实决策报告”；
6. 点击行政单元查看数据来源、动作机制、邻接外溢和证据边界。

## 12. 演示操作脚本

### 12.1 进入页面

操作：

```text
打开 http://localhost:8000
进入 工作台 -> 智能分析 -> 城市宜居性分析（UWM）
```

预期看到：

```text
城市宜居性分析（UWM）
同一数据基础上的 renderer / simulator / planner 反事实决策包
```

讲解要点：

```text
这不是传统指标大屏，而是 UWM 的最终反事实决策输出页面。
```

### 12.2 讲解世界模型链路

操作：

```text
查看“世界模型链路”模块。
```

预期看到：

```text
renderer 已使用
simulator 已使用
planner 已使用
```

讲解要点：

```text
renderer 把多源城市数据构造成状态；
simulator 模拟行动后的未来变化；
planner 搜索多步行动序列；
所以 UWM 输出的是行动方案和未来影响，不是静态排名。
```

### 12.3 讲解同一数据对照

操作：

```text
查看“同一数据对照”模块。
```

预期看到：

```text
scene_id = uwm-multisource-livability-scene-2026-07-06
行政单元 = 36
传统最终输出 = static_problem_ranking
UWM 最终输出 = counterfactual_decision_package
```

讲解要点：

```text
这里不是让 UWM 多用数据、传统方法少用数据；
两者基于同一个城市、同一批行政单元、同一宜居性场景；
差异来自方法能力，而不是数据不公平。
```

### 12.4 讲解推荐行动序列

操作：

```text
查看“推荐行动序列”模块。
```

预期看到：

```text
1. 增加绿色基础设施：江北区 · 观音桥街道 · 653
2. 增加绿色基础设施：九龙坡区 · 九龙镇 · 77
```

讲解要点：

```text
传统方法会告诉我们九龙镇、南坪镇等当前短板明显；
UWM 进一步通过模拟和规划给出行动序列；
当前序列针对热风险超过阈值的单元选择增绿动作。
```

### 12.5 讲解反事实状态变化

操作：

```text
查看“反事实状态变化与空间外溢”表。
```

预期看到：

```text
九龙坡区|九龙镇|77: livability_delta = 0.129847655
江北区|观音桥街道|653: livability_delta = 0.129847655
多个相邻单元也出现正向 livability_delta
```

讲解要点：

```text
UWM 的结果不是只说“这个地方差”，而是说“做了这些动作后，每个单元预计怎么变”；
污染暴露变化为负代表风险下降；
服务和公平性变化为正代表改善。
```

### 12.6 讲解强于传统方法的证据

操作：

```text
查看“强于传统方法的证据”模块。
```

预期看到：

```text
endpoint_aligned_advantage_over_static = 0.000745700
risk_adjusted_advantage_over_static = 0.012777213
neighbor_livability_delta_advantage = 0.272680076
empirical_one_sided_p_value = 0.002809
```

讲解要点：

```text
UWM 不是只多给了一个建议；
它在验证端点、风险校正、空间外溢和单动作 baseline 分布上都给出了比较证据；
这就是 UWM 在最终输出结果上超越传统方法的地方。
```

### 12.7 讲解证据边界

操作：

```text
查看“证据边界”模块。
```

预期看到：

```text
claim level = bounded_support
observed_policy_outcome_superiority_claim = false
```

讲解要点：

```text
当前结论是离线反事实规划和真实准备数据支撑的 bounded support；
不能说已经完成真实政策实施效果验证；
后续如果接入真实干预前后数据或准实验评估，才能升级 claim level。
```

## 13. 异常处理和访问说明

如果直接访问 API：

```text
GET http://localhost:8000/api/uwm/livability-decision
```

未登录时返回 401 是预期行为，因为 API 需要 GIS Data Agent 登录态。客户演示应从应用页面进入。

如果页面无法访问，先检查 Docker 应用：

```text
docker-compose ps
```

当前已验证应用访问路径为：

```text
http://localhost:8000
```

## 14. 当前验证证据

当前 UWM 页面和 API 对应实现已经通过以下本地验证：

```text
uv run pytest data_agent/test_uwm_livability_decision_routes.py \
  data_agent/test_uwm_livability_world_model_frontend_contract.py \
  data_agent/test_uwm_livability_decision_package.py \
  data_agent/test_uwm_traditional_vs_world_model_demo.py \
  data_agent/test_uwm_traditional_livability_analysis.py \
  data_agent/test_uwm_traditional_livability_routes.py \
  data_agent/test_uwm_traditional_livability_frontend_contract.py -q

结果：13 passed
```

前端构建已验证：

```text
npm --prefix frontend run build

结果：构建成功；存在 Vite chunk size warning，不影响当前页面加载。
```

Docker 应用已验证：

```text
docker-compose build app
docker-compose up -d app
curl -I http://localhost:8000/

结果：http://localhost:8000/ 返回 HTTP 200
```

UWM 决策包加载复核结果：

```text
schema = uwm.livability_decision_api.v1
components = renderer, simulator, planner
target_units = 江北区|观音桥街道|653, 九龙坡区|九龙镇|77
single_action_transition_count = 355
empirical_one_sided_p_value = 0.002809
claim level = bounded_support
observed_policy_outcome_superiority_claim = false
```

## 15. 结论

基于当前实现，UWM 城市宜居性分析的最终成果是：

```text
同一数据、同一城市宜居性场景下的城市宜居性反事实决策包。
```

它相比传统方法的关键进步是：

1. 传统方法输出静态问题排名，UWM 输出多步行动序列；
2. 传统方法解释当前状态，UWM 模拟行动后的未来状态变化；
3. 传统方法难以自然表达空间外溢，UWM 显式输出邻近单元受益；
4. 传统方法依赖人工经验选择治理动作，UWM 通过 planner 搜索行动组合；
5. 传统方法缺少风险校正和端点稳健性，UWM 输出风险调整收益和端点权重敏感性；
6. UWM 保留 claim boundary，避免把离线 replay 夸大为真实政策 outcome。

因此，当前 UWM 已经具备客户可演示的核心差异：不是更复杂的指标大屏，而是面向城市复杂巨系统管理的反事实模拟和规划决策能力。
