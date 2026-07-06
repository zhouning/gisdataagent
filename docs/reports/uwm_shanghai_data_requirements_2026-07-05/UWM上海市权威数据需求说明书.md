# Urban World Model（UWM）上海市权威数据需求说明书

- 拟提交对象：上海市城市规划、住房城乡建设、城市更新、城市体检、生态环境、交通、公共服务、数据管理和信息化支撑相关主管单位
- 项目：GIS Data Agent / Urban World Model（UWM）
- 版本：v1.0
- 日期：2026-07-05
- 编制依据：当前 GIS Data Agent 仓库中的 UWM-Livability 设计、renderer/simulator/planner 契约、数据基础 manifest、OpenAQ temporal benchmark、Graph-MDP / model-based RL scaffold、UWM 城市宜居性战略技术说明

## 1. 文件目的

本文用于说明 UWM 从公开代理数据和工程验证阶段进入上海市真实城市治理业务验证阶段所需的权威数据。文档重点回答四个问题：需要哪些数据，为什么需要，数据在 UWM 中如何使用，以及数据应按什么结构和安全边界交付。

本文不是上海市任何部门的法定数据归档清单，也不替代正式业务标准、政务数据共享目录或数据出境/出域审批流程。本文只描述当前 UWM 面向城市宜居治理、城市体检、城市更新、环境健康风险、公共服务可达性、空间公平和干预方案推演所需的最小数据条件。

原始权威数据可以并建议保留在上海市权威内网或政务云环境中。跨环境沟通材料应优先采用脱敏模板、字段映射、规模画像、质量报告和可复核的统计摘要。涉及个人、企业、车辆、通信、健康、位置轨迹、精确住址、敏感设施和涉密空间对象的数据，默认不跨环境导出原始明细。

## 2. 核心结论

- 当前 UWM 已经具备数据基础、MMFE state input、renderer、scene state、simulator、evidence-gated planner、Graph-MDP、offline value/world-model policy、learned rollout planner 和评估门控的可运行工程骨架。
- 当前 UWM 已在 OpenAQ 600 条真实小时观测 temporal holdout 上证明 online temporal state update 显著优于传统静态 baseline suite，但这只证明状态预测层，不证明政策干预 outcome。
- 当前 UWM 的主要短板不是算法接口缺失，而是面向上海真实城市治理的权威空间单元、公共服务、人口脆弱性、交通可达、环境观测、城市更新干预和真实 outcome 数据尚未接入。
- 若要让 UWM 从 `proxy / known-effect replay` 进入有意义的上海业务验证，必须优先提供三类 P0 数据：真实城市状态底座、真实干预/治理历史、真实 observed outcome / validation holdout。
- 第一轮申请应坚持“最小化、分级、可审计、可回收”的原则：优先申请脱敏数据视图、字段映射、规模画像、统计摘要和内网运行环境；只有在必要时才申请经过审批的明细数据。

## 3. 最小交付包

| 交付物 | 优先级 | 作用 | 推荐格式 |
| --- | --- | --- | --- |
| urban_spatial_unit_inventory.csv | P0 | 提供行政区、街镇、居村、网格、街区、建筑或规则网格等 UWM 空间单元底座。 | CSV + 内网图层引用 |
| urban_state_observed_history.csv | P0 | 提供真实城市状态、环境暴露、服务可达性、人口脆弱性、train/holdout，支撑 renderer/simulator 状态验证。 | CSV/Parquet |
| urban_intervention_policy_history.csv | P0 | 提供城市更新、增绿、交通治理、公共服务补点、低碳/环保治理等真实动作和可行性历史，支撑 action mask 和 planner 验证。 | CSV/数据库视图 |
| urban_outcome_validation_history.csv | P0 | 提供干预前后可观测 outcome，用于历史回放、政策效果评估、负控和因果门控。 | CSV/Parquet |
| production_scale_profile.json | P0 | 提供脱敏规模画像，判断生产图层是否满足湖仓、分区、空间索引和分布式计算门槛。 | JSON |
| authoritative_layer_inventory.csv | P0/P1 | 列出建筑、道路、POI、公共服务、环境、人口、规划约束等权威图层。 | CSV + 内网图层引用 |
| field_mapping.csv | P1 | 说明上海原始字段如何映射到 UWM 模板字段。 | CSV |
| lineage_metadata.csv | P1 | 说明源系统、版本、抽取时间、安全等级、授权边界和脱敏方式。 | CSV |

## 4. 数据使用场景

| 场景 | 使用说明 | 需要的数据对象 |
| --- | --- | --- |
| S1 城市状态构建 | 使用上海权威空间单元、建筑、道路、公共服务、人口、环境和规划约束构建 UWM canonical observation。 | D01,D02,D03,D04,D05,D06,D07,D10 |
| S2 宜居性诊断 | 识别低宜居区域，解释热暴露、污染暴露、服务不足、交通压力、人口脆弱性和空间公平机制。 | D01,D03,D04,D05,D06,D07,D10 |
| S3 action mask 可行性 | 判断增绿、服务补点、交通减排、冷屋顶改造、慢行改善、城市更新等动作在空间、预算、规划和政策约束下是否可实施。 | D02,D08,D09,D10 |
| S4 simulator 状态转移验证 | 使用多期状态、真实观测和历史干预验证 action-conditioned rollout，不依赖合成场景。 | D05,D06,D08,D09,D10 |
| S5 planner 方案比选 | 用真实约束、真实干预历史和 observed outcome 比较 UWM planner 与传统静态启发式方案。 | D08,D09,D10 |
| S6 空间公平评估 | 判断低宜居区域、脆弱人群、高暴露人群是否真实受益，而不是只提升平均分。 | D01,D06,D07,D10 |
| S7 生产规模验证 | 用规模画像判断是否满足湖仓、分区、空间索引、分布式计算、抽样和切片门槛。 | D11 |
| S8 审计和人工复核 | 为业务人员提供可回溯的数据来源、版本、证据链、复核意见和对外表述边界。 | D12,D13 |

## 5. 数据对象详细要求

### D01 城市空间单元底座

- 优先级：P0-核心必需
- 为什么需要：UWM 的状态构建、服务可达性、环境暴露、人口脆弱性、公平性评估和干预动作都需要稳定空间单元。
- UWM 使用场景：构建 district / subdistrict / community / grid / block / building 层级状态；计算邻接、覆盖、服务半径、暴露和治理对象。
- 交付建议：原始几何优先留在上海内网；跨环境提供脱敏 ID、空间层级、统计摘要和内网引用。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| unit_id | string | 必需 | 稳定空间单元 ID，可为脱敏别名。 |
| unit_type | enum | 必需 | district/subdistrict/community/grid/block/building/site。 |
| parent_unit_id | string | 推荐 | 上级空间单元 ID。 |
| geometry | geometry | 内网必需 | 面/点/线几何；对外材料默认不导出原始几何。 |
| area_m2 | number | 必需 | 权威面积或可复算面积。 |
| admin_code | string | 必需 | 行政区划或管理单元代码，可脱敏。 |
| snapshot_date | date | 必需 | 数据时相。 |
| crs | string | 必需 | 坐标参考系统。 |
| source_version | string | 必需 | 源数据版本或批次。 |

### D02 规划约束、城市更新和建设管控图层

- 优先级：P0-核心必需
- 为什么需要：UWM planner 不能在不可实施空间单元上推荐动作。城市更新、增绿、服务补点、建筑改造和交通治理都受规划、用地、保护、管控和项目条件约束。
- UWM 使用场景：生成 action mask、hard block、required review、implementation constraint 和 feasibility score。
- 交付建议：提供规划约束目录、更新单元、保护边界、用地/建设管控、历史风貌保护、蓝绿空间、公共空间和项目边界的内网图层引用。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| constraint_id | string | 必需 | 约束或管控对象 ID。 |
| constraint_type | enum | 必需 | planning_zone/urban_renewal_unit/historic_conservation/ecological_space/road_control/public_space/project_boundary 等。 |
| geometry | geometry | 内网必需 | 约束空间几何。 |
| severity | enum | 必需 | hard_block/requires_review/soft_constraint/info。 |
| allowed_actions | string | 推荐 | 允许动作列表，分号分隔。 |
| blocked_actions | string | 推荐 | 禁止动作列表，分号分隔。 |
| effective_date | date | 必需 | 生效日期。 |
| version | string | 必需 | 约束版本。 |
| owner_department | string | 推荐 | 责任部门或角色。 |

### D03 建筑、道路、绿地水体和城市形态数据

- 优先级：P0-核心必需
- 为什么需要：城市形态影响热环境、通风、污染暴露、服务可达性和城市更新可行性。
- UWM 使用场景：构建 urban_form、heat context、walkability context、road exposure、green/blue infrastructure state。
- 交付建议：可按图层清单和内网引用交付；跨环境提供字段字典、尺度、时相和统计摘要。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| feature_id | string | 必需 | 建筑/道路/绿地/水体对象 ID，可脱敏。 |
| feature_type | enum | 必需 | building/road/green_space/water/body/public_space。 |
| geometry | geometry | 内网必需 | 对象几何。 |
| height_m | number | 条件必需 | 建筑高度或道路高架相关字段。 |
| floor_area_m2 | number | 推荐 | 建筑面积或估算建筑量。 |
| land_use_or_function | string | 推荐 | 用途或功能类别。 |
| road_class | string | 条件必需 | 道路等级。 |
| green_ratio | number | 推荐 | 绿化或植被相关指标。 |
| snapshot_date | date | 必需 | 数据时相。 |
| source_version | string | 必需 | 源数据版本。 |

### D04 公共服务设施和 POI/AOI 目录

- 优先级：P0-核心必需
- 为什么需要：UWM 需要判断服务可达性和公共服务补短板，不只是统计设施总量。
- UWM 使用场景：service_accessibility、15 分钟生活圈、公共服务补点、空间公平评估、planner action target。
- 交付建议：教育、医疗、养老、托育、文体、商业、公园、社区服务、轨道站点、公交站点等应保留类别、等级、容量或服务半径字段。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| service_id | string | 必需 | 服务设施 ID，可脱敏。 |
| service_type | enum | 必需 | education/healthcare/eldercare/childcare/culture/sports/park/commercial/community_service/transit 等。 |
| service_level | string | 推荐 | 等级、规模或服务层级。 |
| geometry | geometry | 内网必需 | 点/面几何。 |
| capacity | number | 推荐 | 床位、学位、服务能力、面积等。 |
| opening_status | enum | 推荐 | existing/planned/under_construction/closed。 |
| service_radius_m | number | 推荐 | 业务认可服务半径。 |
| source_system | string | 必需 | 来源系统。 |
| source_version | string | 必需 | 源数据版本。 |

### D05 环境、气象、热暴露和空气质量观测

- 优先级：P0-核心必需
- 为什么需要：上海 UWM 不能只依赖 Open-Meteo、CAMS、CHAP 或 OpenAQ 代理数据。真实业务验证需要上海场景一致的环境和气象观测。
- UWM 使用场景：heat_risk、air_pollution_exposure、meteorology context、state dynamics validation、scenario controls、health-risk proxy。
- 交付建议：站点观测、栅格产品、遥感反演和业务监测均可；必须记录时间粒度、站点/栅格空间支撑、质控标记。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| observation_id | string | 必需 | 观测 ID。 |
| unit_id | string | 推荐 | 关联空间单元。 |
| station_or_grid_id | string | 必需 | 站点或格网 ID。 |
| observation_type | enum | 必需 | temperature/humidity/wind/pm25/pm10/no2/o3/so2/co/lst/ndvi/heat_index 等。 |
| observed_value | number | 必需 | 观测值。 |
| unit | string | 必需 | 计量单位。 |
| observed_time | datetime | 必需 | 观测时间。 |
| quality_flag | string | 推荐 | 质控标记。 |
| source_system | string | 必需 | 来源系统。 |
| synthetic | boolean | 必需 | 真实观测必须 false。 |

### D06 人口、脆弱性和活动分布

- 优先级：P0-核心必需
- 为什么需要：宜居治理必须回答“谁受益、谁受损”。没有人口和脆弱性数据，UWM 只能评估空间，不足以评估公平。
- UWM 使用场景：population_vulnerability、exposure_equity、low-livability target、beneficiary analysis、fairness constraint。
- 交付建议：优先按统计单元或网格汇总，不申请个人明细；涉及敏感群体时只交付分级统计和脱敏指标。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| unit_id | string | 必需 | 空间单元 ID。 |
| population_total | number | 必需 | 常住或服务人口总量。 |
| population_daytime | number | 推荐 | 日间人口或活动人口。 |
| elderly_count_or_rate | number | 推荐 | 老年人口数量或比例。 |
| children_count_or_rate | number | 推荐 | 儿童人口数量或比例。 |
| vulnerable_group_index | number | 推荐 | 脆弱性综合指标。 |
| income_or_social_support_proxy | number | 条件必需 | 经批准后的脱敏社会经济代理指标。 |
| period | string | 必需 | 时期。 |
| source_version | string | 必需 | 源数据版本。 |
| privacy_aggregation_level | string | 必需 | 聚合级别，避免个人识别。 |

### D07 交通网络、可达性和活动联系

- 优先级：P0/P1-核心建议
- 为什么需要：公共服务可达性和交通暴露不能只用直线距离。UWM 需要道路、公共交通、慢行和活动联系支撑更真实的可达性。
- UWM 使用场景：mobility_graph、service_accessibility、traffic_emission_exposure、walkability、OD context、planner constraints。
- 交付建议：道路/公交/轨交网络可提供几何和拓扑；OD 或活动数据应优先聚合到网格/街镇级别，不申请个人轨迹。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| network_id | string | 必需 | 网络或边 ID。 |
| network_type | enum | 必需 | road/transit/walk/bike/od_activity。 |
| source_unit_id | string | 条件必需 | OD 或边起点。 |
| target_unit_id | string | 条件必需 | OD 或边终点。 |
| geometry | geometry | 内网必需 | 道路/线路几何。 |
| travel_time_min | number | 推荐 | 出行时间或阻抗。 |
| distance_m | number | 推荐 | 距离。 |
| flow_or_activity | number | 推荐 | 聚合流量或活动强度。 |
| period | string | 必需 | 时间窗口。 |
| privacy_aggregation_level | string | 条件必需 | OD/活动数据聚合级别。 |

### D08 城市治理干预和项目历史

- 优先级：P0-核心必需
- 为什么需要：没有真实干预历史，UWM planner 只能在 simulator replay 中比较方案，不能验证真实政策 outcome。
- UWM 使用场景：action-conditioned rollout、historical replay、policy outcome validation、planner regret、causal gate。
- 交付建议：包括城市更新、口袋公园、绿化提升、交通减排、公交优化、服务设施新增、冷屋顶或建筑节能改造、街道微更新等项目。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| intervention_id | string | 必需 | 干预或项目 ID，可脱敏。 |
| action_type | enum | 必需 | increase_green_infrastructure/traffic_emission_control/add_community_service/cool_roof/walkability_improvement/urban_renewal 等。 |
| unit_id | string | 必需 | 作用空间单元。 |
| geometry | geometry | 内网推荐 | 干预范围。 |
| start_date | date | 必需 | 开始时间。 |
| completion_date | date | 推荐 | 完成时间。 |
| implementation_status | enum | 必需 | planned/under_construction/completed/cancelled。 |
| budget_or_scale | number | 推荐 | 投资额、面积、设施数量或规模。 |
| responsible_department | string | 推荐 | 责任部门或角色。 |
| policy_version | string | 推荐 | 政策或计划版本。 |

### D09 干预可行性、约束和审批/复核记录

- 优先级：P0-核心必需
- 为什么需要：UWM 的 action mask 必须知道哪些动作在某个空间单元、某个时期、某个政策版本下允许、受限或禁止。
- UWM 使用场景：action mask validation、required review、hard block、planner feasibility gate。
- 交付建议：可由项目审批、计划管理、城市更新项目库、设施补点计划、交通治理计划等系统提供脱敏视图。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| feasibility_id | string | 必需 | 可行性记录 ID。 |
| unit_id | string | 必需 | 空间单元。 |
| action_type | enum | 必需 | 干预动作类型。 |
| action_allowed | boolean | 必需 | 是否允许。 |
| required_reviews | string | 推荐 | 需要复核事项。 |
| hard_blocks | string | 推荐 | 硬阻断原因。 |
| soft_constraints | string | 推荐 | 软约束。 |
| period | string | 必需 | 时期。 |
| policy_version | string | 必需 | 政策版本。 |
| source_system | string | 必需 | 来源系统。 |

### D10 真实 outcome / validation history

- 优先级：P0-核心必需
- 为什么需要：这是 UWM 从工程验证进入真实政策效果验证的关键数据。它用于验证干预前后状态变化，而不是只依赖模型推演。
- UWM 使用场景：historical replay、observed policy outcome、negative control、causal evidence gate、planner superiority claim boundary。
- 交付建议：可以按空间单元和时间窗口汇总，包含干预组/对照组、前后状态、outcome 指标和 split。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| outcome_id | string | 必需 | outcome 记录 ID。 |
| unit_id | string | 必需 | 空间单元。 |
| intervention_id | string | 推荐 | 关联干预 ID。 |
| treated | boolean | 必需 | 是否干预组。 |
| outcome_type | enum | 必需 | heat_risk/air_pollution/service_accessibility/equity/livability/complaint_rate/usage_count 等。 |
| baseline_value | number | 必需 | 干预前值。 |
| followup_value | number | 必需 | 干预后值。 |
| delta_value | number | 推荐 | 变化值。 |
| baseline_period | string | 必需 | 前期窗口。 |
| followup_period | string | 必需 | 后期窗口。 |
| split | enum | 必需 | train/holdout。 |
| synthetic | boolean | 必需 | 真实 outcome 必须 false。 |
| not_for_production | boolean | 必需 | 生产验证必须 false。 |

### D11 生产规模画像 scale_profile

- 优先级：P0-核心必需
- 为什么需要：上海城市数据可能包含百万/千万级 POI、道路、建筑、轨迹或栅格。生产环境是否可承载取决于存储格式、分区、空间索引和分布式计算能力。
- UWM 使用场景：production scale readiness gate；判断是否需要 MinIO/Iceberg/Sedona/GeoParquet/Trino 等 lakehouse 路径和抽样/切片策略。
- 交付建议：production_scale_profile.json，必须是脱敏元数据，不含原始几何和逐行敏感属性。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| schema | string | 必需 | urban_world_model.production_scale_profile.v1。 |
| example_only | boolean | 必需 | 真实画像必须 false。 |
| not_for_production | boolean | 必需 | 真实画像必须 false。 |
| layers[].name | string | 必需 | 脱敏图层别名。 |
| layers[].row_count | integer | 必需 | 行数/对象数。 |
| layers[].storage_format | string | 必需 | parquet/geoparquet/iceberg/delta/hudi/orc/postgis 等。 |
| layers[].partition_columns | array | 必需 | 分区字段。 |
| layers[].spatial_index | string | 推荐 | s2/h3/hilbert/quadkey/grid/geohash 等。 |
| compute.distributed | boolean | 千万级必需 | 是否分布式计算。 |

### D12 数据血缘、版本和脱敏说明

- 优先级：P1-强烈建议
- 为什么需要：UWM 的审计、复核和对外表述必须能追溯到源系统、版本、抽取时间、授权边界和脱敏方式。
- UWM 使用场景：audit report、human review、模型版本和数据版本对应关系、claim boundary。
- 交付建议：metadata/lineage CSV 或数据说明表。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| dataset_id | string | 必需 | 数据集 ID。 |
| source_system | string | 必需 | 源系统。 |
| source_version | string | 必需 | 源版本。 |
| extract_time | datetime | 必需 | 抽取时间。 |
| update_frequency | string | 推荐 | 刷新频率。 |
| security_level | string | 必需 | 安全/保密等级。 |
| desensitization_method | string | 必需 | 脱敏方式。 |
| authorization_scope | string | 必需 | 授权用途和边界。 |
| owner_department | string | 推荐 | 责任部门或角色。 |

### D13 证据项目录和人工复核记录

- 优先级：P1-强烈建议
- 为什么需要：UWM 输出需要证据链支撑，否则只能形成模型建议，不能支持业务复核。
- UWM 使用场景：evidence gate、review task、audit package、claim downgrade。
- 交付建议：只需交付证据索引和元数据；原文件可留在上海内网档案、图像或业务系统。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| evidence_id | string | 必需 | 证据项 ID。 |
| unit_id | string | 必需 | 关联空间单元。 |
| intervention_id | string | 推荐 | 关联干预或项目。 |
| evidence_type | enum | 必需 | satellite_image/street_view/photo/document/sensor_observation/field_check/review_record。 |
| capture_time | datetime | 推荐 | 采集时间。 |
| source_system | string | 必需 | 来源系统。 |
| quality_score | number | 推荐 | 质量评分。 |
| uri_or_reference | string | 内网必需 | 内网引用路径或档案号；跨环境需脱敏。 |
| export_policy | string | 必需 | metadata_only/inner_network_only/desensitized_export_allowed。 |

## 6. 生产 state / outcome history 的通过门槛

一条记录要进入 UWM 生产候选样本，至少要满足：

- 有稳定空间单元 ID；
- 有明确时间窗口；
- 有真实状态或 outcome 指标；
- 有空间支撑；
- 至少包含一个环境、服务、人口、交通或形态协变量；
- `synthetic=false`；
- `not_for_production=false`；
- 能区分 train / holdout；
- 对干预效果验证，必须同时包含 treated 和 control 或可构造对照的样本。

没有 holdout 的数据只能做预检或回放，不能支撑 UWM 生产准确性或政策效果声明。

## 7. 干预动作可行性的通过门槛

UWM 需要的不只是“项目做没做”，还需要知道特定动作在特定空间单元、时期和政策版本下是否允许、为什么允许、为什么受限或为什么禁止。

必须覆盖 allowed 和 blocked 两类样本，并覆盖以下动作类型中的至少一部分：

- `increase_green_infrastructure`
- `traffic_emission_control`
- `add_community_service`
- `cool_roof`
- `walkability_improvement`
- `urban_renewal`
- `public_space_improvement`
- `transit_access_improvement`

尤其需要真实的混合约束允许样本，例如热风险高但可增绿、服务缺口高但受用地约束、交通污染高但需多部门复核的案例。

## 8. 时间留出、空间留出与验证要求

生产验证建议同时采用：

- 时间留出：用较早时期训练，用较晚时期验证；
- 空间留出：用部分区、街镇、社区或网格留作 holdout；
- 政策版本留出：用不同政策或项目批次验证可迁移性；
- 负控：选择理论上不应受某动作影响的指标或区域检查模型是否误报；
- 对照组：选择未干预但相似的空间单元作为 control。

每条样本应带 `period`、`split`、`policy_version`、`baseline_period` 和 `followup_period`。

## 9. 规模画像与大数据要求

百万级城市对象需要列式/湖仓存储、分区和空间索引；千万级对象还需要分布式计算；亿级轨迹、栅格或传感器记录还需要抽样、切片、分块或金字塔策略。

规模画像只提交脱敏元数据，不提交原始几何和逐行属性。对上海市这类超大城市，建议在第一轮就提供以下图层的规模画像：

- 建筑轮廓和建筑属性；
- 道路、公交、轨交和慢行网络；
- POI/AOI 和公共服务设施；
- 网格/街区/居村/街镇空间单元；
- 环境和气象观测；
- 栅格产品；
- 城市更新、公共服务补点和交通治理项目历史；
- 聚合 OD 或活动数据。

## 10. 不应跨环境提交的数据

- 原始个人轨迹、通信明细、车牌、人脸、手机号、身份证、住址等个人敏感信息。
- 未脱敏的企业经营敏感数据、医疗健康个体数据、教育个体数据和社会救助个体数据。
- 原始几何和逐行完整业务属性，除非经过正式审批并在受控环境中使用。
- 暴露内网结构的真实路径、密钥、账号、服务地址。
- 未脱敏的影像、照片、街景、附件原件。可提交证据索引、档案号或内网引用。
- 涉密、敏感设施、重点保护对象和安全风险点的精确位置明细。

## 11. 分阶段申请建议

第一阶段：脱敏清单和规模画像。

申请数据目录、字段字典、规模画像、数据时相、空间范围、更新频率、权限边界和样例统计，不申请敏感明细。

第二阶段：内网运行验证。

在上海市授权环境中运行 UWM renderer 和基础状态构建，原始几何和敏感明细不出域。

第三阶段：历史回放和 holdout 验证。

申请干预历史、状态前后对比、对照样本和 train/holdout 划分，用于验证 simulator 和 planner。

第四阶段：业务试点闭环。

在选定区、街镇或专项主题内，接入业务复核流程，记录模型建议、人工复核、实施结果和后续监测。

## 12. 对上海市合作沟通的建议

建议将 UWM 申请定位为：

> 面向城市体检、城市更新、气候健康风险、公共服务补短板和空间公平治理的城市世界模型试点，需要在上海市授权环境中接入最小必要权威数据，用于状态诊断、干预推演、方案比选和证据审计。

不建议将申请表述为“获取全量城市数据训练 AI 大模型”。更稳妥的表述是：

- 优先内网运行；
- 优先脱敏和汇总；
- 优先最小字段；
- 优先选定试点区域和主题；
- 所有模型输出均为辅助研判，不替代业务部门决策；
- 真实政策效果声明必须经过 holdout、历史回放和因果证据门控。
