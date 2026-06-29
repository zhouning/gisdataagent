# Territory World Model（TWM）自然资源权威数据需求说明书

- 拟提交对象：自然资源部相关数据主管、业务主管和信息化支撑单位
- 项目：GIS Data Agent / Territory World Model（TWM）
- 版本：v1.0
- 日期：2026-06-29
- 编制依据：当前 GIS Data Agent 仓库中的 TWM 数据契约、validation bundle、production onboarding、production scale profile 模板和数据基础评估结果

## 1. 文件目的

本文用于说明 TWM 从工程验证阶段进入真实自然资源业务验证阶段所需的权威数据。文档重点回答四个问题：需要哪些数据，为什么需要，数据在 TWM 中如何使用，以及数据应按什么结构交付。

本文不是自然资源部法定归档清单，也不替代任何正式业务标准。本文只描述当前 TWM 生产接入、校验和模型验证所需的最小数据条件。原始权威数据可以保留在内网权威环境中；跨环境材料应优先采用脱敏模板、字段映射、规模画像和校验报告。

## 2. 核心结论

- 当前 TWM 已经具备状态构建、规则/证据/复核、action-conditioned forecast、future latent state、action mask、counterfactual rollout、validation ladder 和生产 readiness gate。
- 当前主要短板不是算法接口缺失，而是真实、权威、非合成、可追溯的自然资源业务数据尚未接入。
- 若要让 TWM 从 `review` 进入有意义的生产验证，必须优先提供三类 P0 数据：真实 observed history、真实 policy/action feasibility history、生产 scale profile。
- 现有 TxPoint10M 大数据实验已证明 MinIO/Iceberg/Sedona 可支撑 1000 万行时空分析路径，但该数据集不是自然资源 TWM 业务数据，只能作为 lakehouse 能力证据。

## 3. 最小交付包

| 交付物 | 优先级 | 作用 | 推荐格式 |
| --- | --- | --- | --- |
| production_observed_history.csv | P0 | 提供真实 treated/control、outcome、空间支撑、协变量和 train/holdout，支撑生产 observed-history preflight 和因果/预测校准。 | CSV |
| production_policy_history.csv | P0 | 提供真实动作、政策、allowed/blocked、区域、时期和政策版本，支撑 action mask 可行性验证。 | CSV，可与 observed_history 合表 |
| production_scale_profile.json | P0 | 提供脱敏规模画像，判断生产图层是否满足湖仓、分区、空间索引和分布式计算门槛。 | JSON |
| spatial layer inventory | P0/P1 | 列出现状图斑、控制线、行政区、年度变更、证据图层等权威空间数据。 | CSV + 内网图层引用 |
| field_mapping.csv | P1 | 说明原始字段如何映射到 TWM 模板字段。 | CSV |
| lineage_metadata.csv | P1 | 说明源系统、版本、抽取时间、安全等级和脱敏方式。 | CSV |

## 4. 数据使用场景

| 场景 | 使用说明 | 需要的数据对象 |
| --- | --- | --- |
| S1 状态构建 | 使用现状地块、行政区、控制线、项目范围和空间关系构建 TWM 层级状态。 | D01,D02,D03,D08,D10 |
| S2 规则/证据/复核 | 将法定控制线和规则命中转化为 hard block、required review、evidence item 和 audit trail。 | D02,D03,D07,D08,D10 |
| S3 action mask 可行性 | 判断 protect、restore、approve_with_conditions 等动作在区域、时期、政策版本下是否允许。 | D04,D05,D02,D10 |
| S4 future_latent_state 训练与验证 | 从多期状态和 observed_history 中学习 future latent、decoded_state 和 transition_delta。 | D01,D04,D06,D08,D09 |
| S5 因果/准实验校准 | 用真实 treated/control、空间支撑和协变量评估审批/处置结果，而不是依赖演示数据。 | D04,D05,D08,D10 |
| S6 planner/方案比选 | 用规则、证据、风险、效用和可行性标签过滤并排序候选方案。 | D01,D02,D03,D04,D05,D07 |
| S7 生产规模验证 | 用规模画像判断是否满足湖仓、分区、空间索引、分布式计算、抽样/切片门槛。 | D09 |
| S8 审计和提交复核 | 为自然资源业务人员提供可回溯的数据来源、版本、证据链和人工复核入口。 | D07,D10 |

## 5. 数据对象详细要求

### D01 现状地块/图斑与地类空间底座

- 优先级：P0-核心必需
- 为什么需要：TWM 的状态构建、规则叠加、约束评估和后续规划动作都需要一个可追溯的空间单元底座。
- TWM 使用场景：构建 parcel/block/township/county 层级状态；计算面积、邻接、控制线冲突、规划适宜性；为 future_latent_state 和规划方案提供空间承载单元。
- 交付建议：可在内网以 Shapefile/GeoPackage/GeoParquet/PostGIS/Iceberg 表交付；跨环境仅提供脱敏字段字典和规模画像。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| parcel_id | string | 必需 | 稳定空间单元 ID，可映射至图斑编号/地块编号。 |
| geometry | geometry | 内网必需 | 面几何；对外材料不导出原始几何。 |
| area_m2 | number | 必需 | 权威面积或可复算面积。 |
| land_use_code | string | 必需 | 现状地类/用途编码。 |
| admin_code | string | 必需 | 行政区代码。 |
| snapshot_date | date | 必需 | 数据时相。 |
| source_version | string | 必需 | 源数据版本或批次。 |
| crs | string | 必需 | 坐标参考系统。 |

### D02 法定控制线/规划管控图层

- 优先级：P0-核心必需
- 为什么需要：TWM 的 action mask、硬约束、规则命中、审批可行性判断必须依赖权威管控边界，而不是合成替身。
- TWM 使用场景：判断永久基本农田、生态保护红线、城镇开发边界、用途管制分区等冲突；生成 rule_evaluation、hard_blocks 和 required_reviews。
- 交付建议：内网空间图层加版本信息；对外提供 layer alias、规则类别、版本和规模画像。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| control_id | string | 必需 | 控制线/管控单元 ID。 |
| control_type | enum | 必需 | pbf/ecological_redline/urban_boundary/planning_zone/use_control 等。 |
| geometry | geometry | 内网必需 | 控制线或管控区几何。 |
| severity | enum | 必需 | hard_block/requires_review/info。 |
| rule_code | string | 必需 | 适用规则代码。 |
| effective_date | date | 必需 | 生效日期。 |
| version | string | 必需 | 管控边界版本。 |

### D03 项目/审批/审查/复核业务对象

- 优先级：P0-核心必需
- 为什么需要：没有真实业务对象，TWM 只能做图层叠加和工程演示，无法校准审批/复核结果。
- TWM 使用场景：构建 project、approval、review_task 对象；连接空间单元、审批状态、审查任务、规则命中和证据项。
- 交付建议：CSV/数据库视图均可；需提供稳定 ID 和与空间单元的关联关系。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| project_id | string | 推荐 | 项目/事项编号；没有项目概念时可为空。 |
| approval_id | string | 必需 | 审批件/案卷/事项编号。 |
| unit_id | string | 必需 | 可观测样本 ID，可映射到项目、审批件、地块或图斑。 |
| approval_status | enum | 必需 | approved/in_review/rejected/returned/approved_with_conditions 等。 |
| decision_date | date | 必需 | 审批或处置时间。 |
| approved_area_m2 | number | 推荐 | 批准面积。 |
| review_task_id | string | 推荐 | 复核/补正任务编号。 |
| review_result | string | 推荐 | 复核结论。 |

### D04 生产观察历史 observed_history

- 优先级：P0-核心必需
- 为什么需要：这是 TWM 从离线演示进入生产验证的核心数据。它提供 treated/control、outcome、空间支撑和协变量。
- TWM 使用场景：生产 observed-history preflight、因果校准、holdout 验证、action-conditioned dynamics 训练/评估、claim ladder 升级。
- 交付建议：优先按 production_observed_history_template.csv 提供；必须显式 synthetic=false、not_for_production=false。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| unit_id | string | 必需 | 样本 ID。 |
| approval_id | string | 推荐 | 审批件 ID。 |
| approval_status | enum | 必需 | 处理/决策状态。 |
| outcome | number | 必需 | 业务结果或效用代理。 |
| area_m2 | number | 必需 | 面积协变量。 |
| cluster | string | 推荐 | 空间簇/行政区/分组。 |
| neighbors | string | 推荐 | 邻接样本 ID，分号分隔。 |
| x | number | 条件必需 | 代表点经度或投影 X。 |
| y | number | 条件必需 | 代表点纬度或投影 Y。 |
| quality_score | number | 推荐 | 质量/适宜性协变量。 |
| baseline_risk_score | number | 推荐 | 决策前风险。 |
| risk_score | number | 推荐 | 审查时风险。 |
| split | enum | 必需 | train/holdout。 |
| period | string | 必需 | 时期。 |
| synthetic | boolean | 必需 | 生产数据必须 false。 |
| not_for_production | boolean | 必需 | 生产数据必须 false。 |

### D05 政策/动作可行性历史 policy_history

- 优先级：P0-核心必需
- 为什么需要：TWM 的 action mask 不是只判断动作类型，而要知道在特定区域、时期、政策版本下动作是否允许。
- TWM 使用场景：校验 allowed/blocked 标签、region_policy、region_action_policy、mixed-risk allowed policy 覆盖，避免模型把高风险动作一律误判为禁止。
- 交付建议：可与 observed_history 合表，也可单独交付 production_policy_history.csv。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| unit_id | string | 必需 | 关联 observed_history 的样本 ID。 |
| action_type | enum | 必需 | protect/restore/approve_with_conditions/defer_review/reject 等。 |
| action_mask_policy | string | 必需 | 政策/规则/动作掩码标签。 |
| action_mask_allowed | boolean | 必需 | 该动作在当时政策下是否允许。 |
| action_mask_required_reviews | string | 推荐 | 需要的复核事项。 |
| action_mask_hard_blocks | string | 推荐 | 硬阻断原因。 |
| region_code | string | 必需 | 区域代码。 |
| period | string | 必需 | 时期。 |
| policy_effective_date | date | 必需 | 政策生效日期。 |
| policy_version | string | 必需 | 政策版本。 |
| split | enum | 必需 | train/holdout。 |

### D06 年度变更/时序快照

- 优先级：P0-核心必需
- 为什么需要：TWM 是世界模型，需要学习状态如何随时间变化；单期现状图层不足以验证 future state。
- TWM 使用场景：构建 current/observed_next latent，训练 transition_delta，做 temporal holdout 和多期回放。
- 交付建议：年度变更表、状态快照表或按时期分区的空间图层。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| unit_id | string | 必需 | 空间单元或样本 ID。 |
| from_period | string | 必需 | 起始时期。 |
| to_period | string | 必需 | 目标时期。 |
| from_land_use_code | string | 必需 | 变化前地类。 |
| to_land_use_code | string | 必需 | 变化后地类。 |
| change_area_m2 | number | 必需 | 变化面积。 |
| change_reason | string | 推荐 | 变化原因或确认依据。 |
| source_version | string | 必需 | 数据版本。 |

### D07 证据项目录 evidence_item

- 优先级：P1-强烈建议
- 为什么需要：TWM 的结论需要证据链支撑，否则只能给出模型输出，不能支持审查复核。
- TWM 使用场景：连接影像、照片、现场核查、文书附件、规则命中依据和人工复核结论。
- 交付建议：只需交付证据索引和元数据；原文件可留在内网文档/影像系统。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| evidence_id | string | 必需 | 证据项 ID。 |
| unit_id | string | 必需 | 关联样本/项目/地块。 |
| evidence_type | enum | 必需 | satellite_image/photo/document/field_check/rule_hit。 |
| capture_time | datetime | 推荐 | 采集时间。 |
| source_system | string | 必需 | 来源系统。 |
| quality_score | number | 推荐 | 质量评分。 |
| uri_or_reference | string | 内网必需 | 内网引用路径或档案号；跨环境需脱敏。 |

### D08 空间关系与拓扑关系

- 优先级：P1-强烈建议
- 为什么需要：空间邻接、包含、交叠和缓冲关系决定空间干扰、规则命中和图结构动态。
- TWM 使用场景：支撑 relation-aware graph dynamics、spatial causal diagnostics、邻接暴露、控制线重叠和项目-地块关联。
- 交付建议：关系表或可由空间库在内网计算。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| relation_id | string | 必需 | 关系 ID。 |
| source_id | string | 必需 | 源对象。 |
| target_id | string | 必需 | 目标对象。 |
| relation_type | enum | 必需 | adjacent/contains/intersects/overlaps/buffered_by。 |
| overlap_area_m2 | number | 条件必需 | 相交/重叠面积。 |
| distance_m | number | 条件必需 | 距离。 |
| source_version | string | 推荐 | 计算批次或版本。 |

### D09 生产规模画像 scale_profile

- 优先级：P0-核心必需
- 为什么需要：生产环境是否可承载百万/千万/亿级图层，取决于存储格式、分区、空间索引和分布式计算能力。
- TWM 使用场景：production_scale_readiness gate；判断是否需要 MinIO/Iceberg/Sedona/GeoParquet/Trino 等 lakehouse 路径和抽样/切片策略。
- 交付建议：production_scale_profile.json，必须是脱敏元数据，不含原始几何和逐行属性。

| 字段 | 类型 | 必需性 | 说明 |
| --- | --- | --- | --- |
| schema | string | 必需 | territory_world_model.production_scale_profile.v1。 |
| example_only | boolean | 必需 | 真实画像必须 false。 |
| not_for_production | boolean | 必需 | 真实画像必须 false。 |
| layers[].name | string | 必需 | 脱敏图层别名。 |
| layers[].row_count | integer | 必需 | 行数/对象数。 |
| layers[].storage_format | string | 必需 | parquet/geoparquet/iceberg/delta/hudi/orc 等。 |
| layers[].partition_columns | array | 必需 | 分区字段。 |
| layers[].spatial_index | string | 必需 | s2/h3/hilbert/quadkey/grid 等。 |
| compute.distributed | boolean | 千万级必需 | 是否分布式计算。 |

### D10 数据血缘、版本和脱敏说明

- 优先级：P1-强烈建议
- 为什么需要：TWM 的审计、复核和生产结论必须能追溯到源系统、版本、抽取时间和脱敏边界。
- TWM 使用场景：支撑 audit report、human review、模型版本和数据版本对应关系。
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
| owner_department | string | 推荐 | 责任部门或角色。 |

## 6. 生产 observed_history 的通过门槛

一条记录要进入生产候选样本，至少要满足：有稳定样本 ID；有处理/决策状态；有 outcome 或业务结果代理；有空间支撑；有至少一个数值协变量；`synthetic=false`；`not_for_production=false`。整个文件必须同时包含 treated 和 control 样本，并包含 train 和 holdout。

推荐 treated 状态包括 `approved`、`approved_with_conditions`、`conditional_approval`、`granted`、`pass`。推荐 control/review 状态包括 `in_review`、`pending`、`returned`、`rejected`、`denied`、`supplement_required`、`requires_review`。

## 7. 政策/动作可行性的通过门槛

TWM 需要的不只是“过没过”，还需要知道特定动作在特定区域、时期和政策版本下是否允许。必须覆盖 allowed 和 blocked 两类样本，并覆盖区域-政策、区域-动作-政策组合。尤其需要真实的混合风险允许样本，例如高风险但在附条件、修复或保护政策下仍可允许的案例。

## 8. 时间留出与生产验证要求

生产验证必须提供 train/holdout。推荐按时间留出、区域留出或二者结合。没有 holdout 的数据只能做预检或回放，不能支撑 TWM 生产准确性声明。每条样本应带 `period`、`split`、`policy_effective_date` 或 `policy_version`。

## 9. 规模画像与大数据要求

百万级图层需要列式/湖仓存储、分区和空间索引；千万级图层还需要分布式计算；亿级图层还需要抽样、切片、分块或金字塔策略。规模画像只提交脱敏元数据，不提交原始几何和逐行属性。

## 10. 不应跨环境提交的数据

- 原始几何和逐行完整业务属性。
- 涉密对象编号、人员信息、单位敏感信息和审批正文全文。
- 暴露内网结构的真实路径、密钥、账号、服务地址。
- 未脱敏的影像、照片、附件原件。可提交证据索引、档案号或内网引用。

## 11. 质量验收口径

初次接入建议以 TWM 脚本输出为准。目标状态为：`production_observed_history_preflight.status=pass`、`production_scale_readiness.status=pass`、`production_readiness_gate.status=pass`。若输出为 `review`，表示可读但覆盖不足；若为 `blocked`，表示路径、结构或关键证据缺失。

## 12. 随文模板清单

| 模板文件 | 用途 |
| --- | --- |
| annual_change_history_template.csv | 年度变更/时序快照模板。 |
| control_layer_catalog_template.csv | 法定控制线和规划管控图层目录模板。 |
| evidence_item_catalog_template.csv | 影像、照片、文书、现场核查等证据索引模板。 |
| field_mapping_template.csv | 原始字段到 TWM 模板字段的映射表。 |
| lineage_metadata_template.csv | 数据血缘、版本、抽取时间、安全等级和脱敏说明。 |
| production_observed_history_template.csv | 核心生产观察历史模板。 |
| production_policy_history_template.csv | 动作/政策可行性历史模板。 |
| project_approval_review_template.csv | 项目、审批、审查、复核业务对象模板。 |
| spatial_layer_inventory_template.csv | 权威空间图层清单和规模元数据模板。 |
| spatial_relation_template.csv | 空间邻接、包含、相交、重叠等关系模板。 |
| validation_split_template.csv | train/holdout 留出划分模板。 |
| field_dictionary.csv | 字段字典，汇总所有数据对象字段、必需性、说明和 TWM 使用场景。 |
| production_scale_profile_template.json | 脱敏生产规模画像 JSON 模板。 |

## 13. 证据来源

- `docs/twm-production-input-data-requirements.md`：既有 TWM 生产输入数据要求。
- `docs/reports/twm_validation_bundle.md` 和 `.json`：当前 validation bundle、生产 preflight、scale readiness、deployment punch list。
- `docs/reports/twm_production_scale_profile_template.json`：生产规模画像契约。
- `scripts/run_twm_validation_bundle.py`、`scripts/run_twm_production_onboarding.py`、`scripts/validate_twm_data_foundation.py`：生产接入和校验脚本。
- `docs/twm-current-handoff.md`：当前 TWM roadmap、claim boundary、future_latent_state v2 和 TxPoint10M lakehouse scale evidence。

## 14. 需要数据主管确认的问题

1. 哪些业务系统可提供审批/审查/复核/处置历史，字段和时间跨度如何。
2. 哪些政策/规则版本可以追溯到具体审批或复核记录。
3. 真实 train/holdout 应按时间、区域还是政策版本划分。
4. 原始几何和证据原件保留在哪个内网环境，TWM 以何种权限访问。
5. 哪些字段需要脱敏、替换 ID 或只提供统计画像。
6. 生产规模是否达到千万/亿级，是否已有 MinIO/Iceberg/Sedona/GeoParquet/Trino/Spark 等湖仓能力。

## 15. 附：推荐校验命令

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/run_twm_production_onboarding.py \
  --production-observed-history <production_observed_history.csv> \
  --production-scale-profile <production_scale_profile.json> \
  --output-dir <output_dir> \
  --require-production-readiness
```

如果只有原始导出表，应先提供字段映射并输出规范化 observed_history，再运行上述命令。
