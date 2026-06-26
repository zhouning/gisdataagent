# TWM 真实权威输入数据要求

- 日期：2026-06-25
- 状态：面向生产接入的数据交付要求
- 依据：当前仓库中的 TWM 校验契约、模板和生产接入脚本
- 适用对象：准备把 TWM 从本地演示/合成数据切换到真实权威自然资源数据环境的人员

## 1. 先说清楚边界

本文不试图替自然资源业务部门定义法定数据、审批制度或业务流程。这里的要求只来自当前 TWM 代码已经明确支持和校验的输入契约：

- `scripts/validate_twm_data_foundation.py`
- `scripts/run_twm_validation_bundle.py`
- `scripts/run_twm_production_onboarding.py`
- `docs/reports/twm_production_observed_history_template.csv`
- `docs/reports/twm_production_scale_profile_template.json`

因此，本文说的“必须提供”，意思是：如果要让当前 TWM 的生产接入校验通过，数据里必须有这些信息。它不等同于自然资源主管部门的法定归档清单，也不替代任何正式业务标准。

当前 TWM 剩下的关键工作不是再合成更多演示数据，而是接入真实、权威、可追溯、非合成的观察历史和生产规模画像。没有这些数据，TWM 只能证明工程链路、规则执行、状态构建、合成实验和离线验证能力，不能声称已经具备生产准确性。

## 2. 最小交付包

建议第一次生产接入至少交付两个文件：

1. `production_observed_history.csv`
   - 真实、非合成的审批/审查/复核/处置观察历史。
   - 每一行是一个可以被 TWM 当作因果校准和可行性校验样本的观测记录。
   - 必须显式标记 `synthetic=false` 和 `not_for_production=false`。

2. `production_scale_profile.json`
   - 脱敏后的生产规模画像。
   - 只描述图层/表的规模、存储、分区、索引和计算环境。
   - 不要放原始几何、逐行属性、涉密对象编号、真实内部路径或审批内容。

如果原始审批导出表字段名和 TWM 模板不同，可以先提供原始 CSV，再由脚本归一化到 TWM 模板。但归一化只做字段映射，不证明数据真实、完整或业务正确。

## 3. `production_observed_history.csv` 推荐表头

推荐直接使用当前模板表头：

```csv
unit_id,approval_id,project_id,approval_status,outcome,approved_area_m2,area_m2,stratum,cluster,neighbors,x,y,quality_score,baseline_risk_score,risk_score,rule_hit_count,review_task_count,action_type,action_mask_policy,action_mask_allowed,action_mask_required_reviews,action_mask_hard_blocks,region_code,period,split,time_index,policy_effective_date,policy_version,propensity_score,evidence_weight,synthetic,not_for_production,source_path
```

模板位置：

- `docs/reports/twm_production_observed_history_template.csv`

字段可以使用别名，脚本会识别一批常见字段名。但是为了减少歧义，生产接入建议尽量按上面的英文表头提供。

## 4. 每行数据代表什么

每一行应代表一个真实世界里已经发生过、可以追溯来源的观察样本。它可以是一个项目、一个审批事项、一个审查单元、一个地块/图斑层面的处置记录，关键是这行记录必须同时回答这些问题：

- 这个样本是谁：`unit_id`、`project_id` 或 `approval_id`。
- 它最后或当时被怎样处理：`approval_status` 或 `treatment`。
- 处理后观测到什么结果：`outcome`，或至少有面积类结果代理字段。
- 它发生在哪个空间上下文：行政区、空间簇、邻接单元或坐标。
- 当时有哪些前置特征：面积、质量、风险、规则命中、复核任务等数值协变量。
- 它是不是生产可用真实数据：`synthetic=false` 且 `not_for_production=false`。
- 当时适用什么政策/规则版本：`policy_effective_date` 或 `policy_version`。
- 它属于训练还是留出验证：`split=train` 或 `split=holdout`。

## 5. 必需字段组

当前校验脚本不是只检查某几个固定字段，而是检查字段组。每个字段组至少要命中一个可识别字段。

| 字段组 | 必需性 | 推荐字段 | 可接受别名示例 | 作用 |
|---|---:|---|---|---|
| 因果单元身份 | 必需 | `unit_id` | `causal_unit_id`, `sample_id`, `project_id`, `XMDM`, `approval_id`, `AJBH` | 标识一条可追溯的观测样本 |
| 处理/决策结果 | 必需 | `approval_status` | `treatment`, `treated`, `decision_result`, `DKZT`, `status`, `review_result`, `approved_area_m2`, `ZDZMJ` | 区分已批准/已处置和未批准/对照样本 |
| 观测结果 | 必需 | `outcome` | `planning_utility_delta`, `utility_delta`, `ranking_score`, `observed_utility_delta`, `area_m2`, `DKMJ`, `approved_area_m2`, `ZDZMJ` | 用于后续效果、效用或结果校准 |
| 生产标记 | 必需 | `synthetic`, `not_for_production` | `is_synthetic`, `not_for_prod`, `not_for_training` | 防止合成/演示数据误入生产结论 |
| 空间支撑 | 必需 | `cluster`, `region_code`, `neighbors`, `x`, `y` | `spatial_cluster`, `block_id`, `township_id`, `county_code`, `DKXZQDM`, `XZQDM`, `neighbor_unit_ids`, `lon`, `lat` | 支撑空间分组、邻接、区域外推和空间验证 |
| 调整协变量 | 必需 | `area_m2`, `quality_score`, `risk_score` | `planned_area_m2`, `DKMJ`, `baseline_risk_score`, `evidence_coverage`, `rule_hit_count`, `review_task_count` | 支撑因果/准实验校准，降低样本不可比问题 |

## 6. 生产可用行的硬门槛

一行数据要被当前脚本当作生产候选行，至少要满足：

- 有 `synthetic` 字段，并且值为 false。
- 有 `not_for_production` 字段，并且值为 false。
- 能解析出处理/决策状态。
- 有观测结果。
- 有至少一个数值型调整协变量。
- 有空间支撑信息，三选一即可：
  - 空间簇/行政区字段，如 `cluster`、`region_code`、`DKXZQDM`、`XZQDM`。
  - 邻接单元字段，如 `neighbors`、`neighbor_unit_ids`。
  - 完整坐标字段，如 `x,y` 或 `lon,lat`。

整个文件还必须同时包含处理组和对照组。也就是说，不能只给“通过审批”的记录，也不能只给“被退回/驳回/待审”的记录。当前脚本会检查生产候选行里的 `production_treated_count` 和 `production_control_count`。

## 7. 处理状态怎么填

推荐字段是 `approval_status`。当前脚本会把以下值视为处理组，也就是已批准、已通过或带条件通过：

- `approved`
- `approved_with_conditions`
- `conditional_approval`
- `conditional`
- `granted`
- `pass`
- `passed`

以下值会被视为对照组，也就是未批准、待审、退回、驳回或需补正：

- `proposed`
- `in_review`
- `pending`
- `open`
- `returned`
- `rejected`
- `denied`
- `supplement_required`
- `requires_supplementary_evidence`
- `hit_requires_review`

如果没有状态字段，但有 `approved_area_m2` 或 `ZDZMJ`，脚本会把批准面积大于 0 的行视为处理组，把批准面积为 0 的行视为对照组。生产接入不建议只依赖面积推断，最好显式给出状态。

## 8. 结果字段怎么填

优先提供业务上可解释、可审计的结果字段：

- `outcome`
- `observed_utility_delta`
- `reviewed_planning_utility_delta`
- `planning_utility_delta`
- `ranking_score`

如果当前业务没有统一效用分数，可以先使用面积类代理结果：

- `approved_area_m2`
- `area_m2`
- `DKMJ`
- `ZDZMJ`
- `ZYZMJ`

面积类字段只能作为低阶代理结果。它可以让生产预检通过，但不能单独证明 TWM 模拟器准确或规划方案最优。

## 9. 空间支撑要求

空间支撑的目标不是让 CSV 里塞完整几何，而是让 TWM 能知道样本发生在哪个空间上下文里。

推荐优先级：

1. 行政或空间分组字段：
   - `region_code`
   - `cluster`
   - `township_id`
   - `county_code`
   - `DKXZQDM`
   - `XZQDM`

2. 邻接关系字段：
   - `neighbors`
   - `neighbor_unit_ids`

3. 坐标字段：
   - `x,y`
   - `lon,lat`
   - `longitude,latitude`

如果同时能提供权威空间图层，建议另行提供空间数据包或在内网数据目录中注册。CSV 中只要保留可以关联的 ID 即可。不要在脱敏校验报告中导出原始几何。

## 10. 调整协变量要求

至少提供一个数值型协变量，建议提供多个。可用字段包括：

- `area_m2`
- `planned_area_m2`
- `DKMJ`
- `quality_score`
- `baseline_outcome`
- `baseline_risk_score`
- `risk_score`
- `evidence_coverage`
- `rule_hit_count`
- `review_task_count`

更稳妥的生产数据应尽量覆盖这些类型：

- 面积规模：用于控制项目/单元大小差异。
- 初始质量或适宜性：用于控制样本初始条件差异。
- 初始风险：用于控制高风险样本和低风险样本的可比性。
- 规则命中数量：用于反映当时约束冲突强度。
- 复核任务数量：用于反映人工审查复杂度。

这些字段应尽量是决策前或决策当时已知的特征。不要把决策之后才产生的结果变量混进协变量里，否则会污染后续因果校准。

## 11. 政策/动作可行性字段

TWM 当前不只要知道“过没过”，还要预检动作掩码和政策可行性。因此建议提供：

| 字段 | 必需性 | 说明 |
|---|---:|---|
| `action_type` | 推荐接近必需 | 该行对应的动作类型，例如保护、修复、带条件批准、延后复核等。具体枚举由真实业务数据决定，TWM 不在文档中编造。 |
| `action_mask_policy` | 推荐接近必需 | 当时触发或适用的政策/规则标签、代码或可行性策略。 |
| `action_mask_allowed` | 推荐接近必需 | 该动作在当时政策下是否允许，建议填 true/false。 |
| `action_mask_required_reviews` | 推荐 | 需要哪些复核或补正事项。 |
| `action_mask_hard_blocks` | 推荐 | 是否存在硬性阻断条件。 |
| `region_code` | 推荐接近必需 | 区域上下文，用于区域-政策覆盖检查。 |
| `period` | 推荐接近必需 | 时间上下文，用于时序验证。 |

脚本会检查：

- 是否有允许样本。
- 是否有阻断样本。
- 是否有动作类型。
- 是否有政策标签。
- 是否有区域上下文。
- 是否有时间上下文。
- 是否存在区域 + 政策组合。
- 是否存在区域 + 动作 + 政策组合。
- 是否存在混合风险下仍允许的政策样本。

`action_mask_allowed` 可接受的真值示例：

- `true`
- `1`
- `yes`
- `allowed`
- `allow`
- `pass`
- `approved`

可接受的假值示例：

- `false`
- `0`
- `no`
- `blocked`
- `block`
- `review`
- `requires_review`
- `rejected`
- `denied`

## 12. 时间切分要求

生产接入必须支持留出验证。当前脚本会检查：

- 至少有两个时间周期。
- 有 `train` 训练/校准样本。
- 有 `holdout` 留出验证样本。
- 每条生产候选行都有政策生效日期或政策版本。

推荐字段：

- `period`
- `time_index`
- `approval_date`
- `decision_date`
- `year`
- `quarter`
- `split`
- `policy_effective_date`
- `policy_version`
- `rule_version`
- `planning_version`
- `standard_version`
- `land_policy_version`

`split` 的推荐值：

- 训练/校准：`train`
- 留出验证：`holdout`

脚本也能识别部分别名：

- `training`, `candidate`, `fit`, `calibration` 会归一到 `train`。
- `test`, `validation`, `valid`, `eval`, `evaluation` 会归一到 `holdout`。

如果没有明确留出集，TWM 不能升级为真实生产准确性验证，只能做数据预检或回放式检查。

## 13. `production_scale_profile.json` 要求

这个文件不是业务数据表，而是脱敏的规模与平台画像。目的只是回答：真实生产数据规模是否需要湖仓、分区、空间索引、分布式计算、抽样和切片策略。

模板位置：

- `docs/reports/twm_production_scale_profile_template.json`

生产接入时必须把模板中的示例标记改掉：

- `example_only=false`
- `not_for_production=false`

最小结构示例：

```json
{
  "schema": "territory_world_model.production_scale_profile.v1",
  "example_only": false,
  "not_for_production": false,
  "profile_id": "sanitized_profile_id",
  "created_by": "sanitized_team_or_role",
  "created_at": "2026-06-25",
  "scope": {
    "region_scope": "province_or_city_or_national",
    "business_scope": "natural_resource_planning_or_land_use_control",
    "sensitivity": "sanitized_metadata_only"
  },
  "layers": [
    {
      "name": "sanitized_layer_alias",
      "row_count": 120000000,
      "storage_format": "geoparquet",
      "lakehouse_table": true,
      "partition_columns": ["province_code", "year"],
      "spatial_index": "s2_or_h3_or_hilbert_or_quadkey",
      "tiling": "quadkey_or_vector_tile_pyramid",
      "sampling_strategy": "stratified_spatial_temporal_holdout"
    }
  ],
  "storage": {
    "table_format": "iceberg_or_delta_or_hudi_or_geoparquet",
    "object_store": "minio_or_hdfs_or_secure_object_store",
    "partition_columns": ["province_code", "year"],
    "spatial_index": "s2_or_h3_or_hilbert_or_quadkey"
  },
  "compute": {
    "engine": "spark",
    "spatial_engine": "sedona",
    "sql_engine": "trino_or_spark_sql",
    "distributed": true,
    "worker_count": "sanitized_capacity_bucket"
  },
  "validation": {
    "sampling_strategy": "stratified_spatial_temporal_holdout",
    "chunking": "administrative_partition_plus_spatial_tile",
    "holdout_policy": "province_time_or_tile_based_holdout"
  }
}
```

规模门槛：

- 百万级图层：需要列式/湖仓存储、分区、空间索引。
- 千万级图层：在百万级要求基础上，需要分布式计算。
- 亿级图层：在千万级要求基础上，需要抽样、切片、分块或金字塔策略。

可接受的存储/计算线索包括：

- 存储格式：`parquet`, `geoparquet`, `iceberg`, `delta`, `hudi`, `orc`。
- 空间索引：`s2`, `h3`, `hilbert`, `quadkey` 等。
- 分布式计算：`spark`, `sedona`, `flink`, `dask`, `ray`, `trino`, `presto`。

## 14. 不要提供什么

生产预检阶段不要把以下内容放进要导出的报告或脱敏规模画像：

- 原始几何。
- 逐行业务属性。
- 涉密或敏感对象 ID。
- 暴露内网结构的真实文件路径。
- 业务秘密、审批正文、审查意见全文。
- 未明确脱敏的人员、单位或联系方式。

如果 TWM 部署在权威数据内网中，原始空间图层和业务表可以留在内网数据湖、数据库或文件系统内，由 TWM 在内网读取。对外或跨环境交付时，只给脱敏统计、字段映射和校验结果。

## 15. 什么情况算“可进入下一步”

第一次接入时，建议以脚本输出为准：

- `production_observed_history_preflight.status=pass`
- `production_scale_readiness.status=pass`
- `production_readiness_gate.status=pass`

如果状态是 `review`，说明文件可读，但有关键覆盖不足，例如缺少留出集、缺少阻断样本、缺少政策版本、缺少区域-政策组合或规模画像还是模板。

如果状态是 `blocked`，说明路径缺失、生产可用行不可构成校验，或在强制生产就绪模式下关键证据没有提供。

## 16. 推荐校验命令

如果已经有规范化后的观察历史 CSV：

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/run_twm_production_onboarding.py \
  --production-observed-history <production_observed_history.csv> \
  --production-scale-profile <production_scale_profile.json> \
  --output-dir <output_dir> \
  --require-production-readiness
```

如果只有原始审批/复核导出 CSV，需要先归一化：

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/run_twm_production_onboarding.py \
  --raw-production-observed-history <raw_approval_review_export.csv> \
  --normalized-production-observed-history-output <normalized_production_observed_history.csv> \
  --production-scale-profile <production_scale_profile.json> \
  --output-dir <output_dir> \
  --require-production-readiness
```

如果要单独输出模板：

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/validate_twm_data_foundation.py \
  --schema-template-output docs/reports/twm_production_observed_history_template.csv
```

## 17. “项目”在本文里具体指什么

这里的“项目”不是我额外编造的一个自然资源业务分类，也不特指某一种固定业务事项。它在当前 TWM 数据契约里只是一个可观测业务对象的 ID 字段，通常对应 `project_id`，可接受别名包括 `XMDM`、`xmdm`、`project_code` 等。

更准确地说：

- 如果真实数据中有“建设项目”“用地项目”“审批项目”“调整方案”等项目编号，那么它可以填入 `project_id`。
- 如果真实数据不是按项目组织，而是按审批件、案卷、图斑、地块或审查单元组织，也可以不用 `project_id`，改用 `approval_id` 或 `unit_id`。
- TWM 真正需要的是稳定、可追溯、能和空间单元及审批/复核结果关联的观测单元 ID。

所以，`project_id` 只是身份字段之一，不是硬性要求每行都必须叫“项目”。当前脚本的硬要求是命中“因果单元身份”字段组，也就是至少有一个能标识样本的字段，例如：

- `unit_id`
- `causal_unit_id`
- `sample_id`
- `project_id`
- `XMDM`
- `approval_id`
- `AJBH`

如果你的权威数据里没有“项目”这个概念，但有审批事项编号、案卷编号、地块编号或图斑编号，也可以接入。接入时只需要把它映射到 `unit_id`，并保留原始字段名说明。

## 18. 给数据提供方的简短说明

请优先提供一份真实、非合成、可追溯的审批/复核观察历史 CSV。每行至少要能标识一个样本、说明处理状态、给出观测结果、提供空间上下文、提供若干决策前协变量，并显式标记 `synthetic=false`、`not_for_production=false`。同时请提供脱敏规模画像 JSON，用于判断真实生产图层是否具备湖仓、分区、空间索引、分布式计算和留出验证条件。

TWM 不要求第一次就导出全部原始权威空间数据到仓库。原始空间数据可以留在内网权威环境中，TWM 只需要在部署环境中能按 ID、空间关系和字段映射访问它们。跨环境交付时请只给脱敏模板、字段映射、规模画像和校验报告。

## 19. 当前数据基础总览

当前仓库里的数据基础可以分成四类：

1. **本地 TWM fixture**
   用于 renderer / simulator / planner / evidence gate 的工程回归。
2. **合成结构化样本**
   用于模拟 treated/control、空间邻接、时间切分和 policy feasibility。
3. **公共或样例级基准数据**
   用于和外部基线、公开 FLUS 样例或公共遥感产品对比。
4. **生产输入契约与模板**
   这些是结构定义，不是生产真值。

从当前健康报告看，仓库里已经有的基础大致是：

- `approval_records.csv` 90 行，本地 fixture。
- `review_tasks.csv` 114 行，本地 fixture。
- `rule_evaluation.csv` 360 行，本地 fixture。
- `state_snapshots.csv` 10 行，本地 fixture。
- `twm_structural_validation_observed_history.csv` 48 行，合成且 `not_for_production=true`。
- `twm_synthetic_experiment_foundation.csv` 256 行，合成的多区域多时期实验底座。
- Dynamic World 20-region 公共基准，适合比较算法，不等于自然资源权威业务数据。
- GeoSOS DongGuan 80m / FLUS V2.4 样例，适合方法对比，不等于生产权威数据。
- TWM runtime 当前已经能构建出状态对象和关系对象，但其中大部分仍是 `not_for_production`。

这意味着：当前数据基础足够支撑研发、回归、方法比较和离线验证，但还不足以支撑真实生产准确性结论。

## 20. 完整数据结构总图

下面这张表把 TWM 的完整数据结构拆成“当前已有基础”和“必须用真实权威数据更新”的两列。你可以把它理解成生产接入时的对账总表。

| 层级 | 数据对象 | 当前仓库现状 | 真实权威数据是否必须补齐 | 需要补的内容 |
|---|---|---|---|---|
| A1 | `parcel_current` 现状地块/图斑 | 有 DLTB-like 图斑、公共基准和若干示例输出 | 是 | 真实权威地块几何、面积、地类、权属、编码、时相、CRS、来源版本 |
| A2 | `admin_unit` 行政区/乡镇/村 | 有公开行政界和部分派生边界 | 建议补齐 | 业务内正式管辖层级、标准代码、名称、版本、上下级关系 |
| A3 | `control_layer` 法定控制线/规划分区 | 多为合成或替身 | 是 | 永久基本农田、生态保护红线、城镇开发边界、用途管制单元、规划分区 |
| A4 | `project` 业务项目对象 | 当前只有 ID 契约，没有统一真实项目底座 | 是 | 项目编号、项目范围、项目类型、发起时间、责任单位、审批链条 |
| A5 | `approval` 审批/审查对象 | 只有模板和少量 fixture 语义 | 是 | 真实审批件、审批状态、批复面积、时间、部门、版本、附件索引 |
| A6 | `review_task` 复核/补正任务 | 有本地 fixture | 是 | 真实复核任务、任务状态、补正原因、复核结论、办理时限 |
| A7 | `rule_evaluation` 规则评估结果 | 有本地 fixture | 建议补齐 | 真实规则命中、命中原因、规则版本、规则优先级、阻断/放行原因 |
| A8 | `observed_history` 观察历史 CSV | 模板已定，真实生产数据缺失 | 是，核心必填 | 真实 treated/control、outcome、空间支撑、协变量、`synthetic=false`、`not_for_production=false` |
| A9 | `policy_history` 政策/可行性历史 | 当前缺失真实标签 | 是，核心必填 | 动作类型、可行性标签、区域-政策组合、时间上下文、政策版本、生效日期 |
| A10 | `enforcement` 执法督察/违法处置 | 当前没有真实生产底座 | 是 | 疑似违法、核查、处罚、整改、复核闭环、关联地块/项目 |
| A11 | `annual_change` 年度变更链 | 可从演示/合成数据推导 | 是 | 真实年度变化调查链、前后时相、变化编码、确认依据 |
| A12 | `evidence_item` 影像/照片/附件/文书 | 有公共遥感和样例基准 | 建议补齐 | 权威时相影像、附件索引、证据来源、采集时间、质检结果 |
| A13 | `spatial_relation` 邻接/包含/交叠关系 | 本地 runtime 有关系对象 | 建议补齐 | 真实地块邻接、包含、相交、缓冲、拓扑校验结果 |
| A14 | `model_output` TWM/FLUS/WorldModel 方案输出 | 有现成样例和实验输出 | 不必作为权威真值，但建议保留 | 方案候选、预测图、优化结果、需求量、约束说明、评价指标 |
| A15 | `validation_split` 训练/验证/留出划分 | 合成样本里已具备 | 是 | 真实 train/holdout 划分、按时间或区域留出、交叉验证策略 |
| A16 | `scale_profile` 生产规模画像 | 当前缺失真实画像 | 是，核心必填 | 图层行数、分区、存储格式、空间索引、计算引擎、抽样/切片策略 |
| A17 | `lineage_metadata` 溯源与刷新元数据 | 文档里有部分描述 | 建议补齐 | 源系统、抽取时间、责任人、刷新频率、脱敏策略、保密等级 |
| A18 | `report_artifacts` 校验/基线/对比报告 | 已有大量报告 | 不需要作为权威输入 | 这些是输出物，不是生产输入，但要保留审计链 |

一句话总结这张表：

- **必须由真实权威数据补齐的**：`observed_history`、`policy_history`、`scale_profile`、`control_layer`、`project`、`approval`、`review_task`、`enforcement`、`annual_change`、`validation_split`。
- **可以先用现有底座继续开发的**：`model_output`、`report_artifacts`、部分 `spatial_relation`、部分 `evidence_item`。
- **适合保留为合成或公共基准的**：`structural_validation_observed_history`、`synthetic_experiment_foundation`、Dynamic World benchmark、GeoSOS/FLUS 样例。

## 21. 质检差距总览

当前质检差距不在“有没有一个 CSV 文件”，而在“有没有能支撑真实生产结论的证据闭环”。

| 质检项 | 现状 | 差距 | 需要真实权威数据补的内容 |
|---|---|---|---|
| 本地观测历史门 | `review` | 缺 min_records、min_treated、min_control、overlap、standard_error、真实生产标记 | 真实 treated/control 观测历史、足够样本数、真实 outcome、真实协变量 |
| 生产政策历史门 | `not_provided` | 完全缺失 | 真实 action/policy feasibility 记录、allowed/blocked 标签、区域-政策覆盖 |
| 政策对齐门 | `not_provided` | 缺 allowed/blocked 计数、区域键、动作键、混合可行政策覆盖 | 真实政策历史和多区域多动作组合 |
| 生产时序门 | `not_provided` | 缺留出期、政策版本、生效日期 | 至少两个时期、train/holdout、政策版本追溯 |
| 生产规模门 | `not_provided` | 缺 scale profile | 脱敏后的真实图层规模、存储、分区、索引、分布式计算信息 |
| 生产就绪门 | `review` / `blocked` | 仍缺真实观测历史、政策历史、规模画像 | 把上面几类输入补齐后才能升级 |

所以，当前 TWM 的问题不是“结构不够”，而是“结构已经有了，真实权威填充值还没进来”。只要你把上面 A8、A9、A3、A4、A5、A6、A10、A11、A16 这些层补全，当前的校验链就能从 review 走向真正有意义的 production readiness 评估。
