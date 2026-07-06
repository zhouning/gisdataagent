# UWM 上海市权威数据模板说明

本目录中的模板用于配合 `UWM上海市权威数据需求说明书.docx` 提交和沟通。模板不是上海市法定业务表单，也不替代政务数据共享目录或数据安全审批流程，而是当前 UWM 生产接入、校验和模型验证所需的数据结构建议。

## 核心必填模板

- `urban_spatial_unit_inventory_template.csv`
  - 上海 UWM 的空间单元底座。
  - 可描述行政区、街镇、居村、网格、街区、建筑、服务点等空间单元。
  - 原始几何建议留在上海内网；跨环境只提交脱敏 ID、层级、面积、时相和内网引用。

- `urban_state_observed_history_template.csv`
  - 真实城市状态观察历史。
  - 用于 renderer / scene state / simulator 的状态验证。
  - 必须显式 `synthetic=false`、`not_for_production=false` 才能作为生产候选。

- `urban_intervention_policy_history_template.csv`
  - 真实城市治理干预、动作可行性和政策约束历史。
  - 用于 action mask 验证和 planner 可行性约束。

- `urban_outcome_validation_history_template.csv`
  - 干预前后真实 outcome 或验证指标。
  - 用于 historical replay、observed policy outcome、negative control 和因果证据门控。

- `production_scale_profile_template.json`
  - 脱敏生产规模画像。
  - 不应包含原始几何、逐行属性、敏感对象 ID 或真实内网路径。

## 空间、服务、环境和交通模板

- `authoritative_layer_inventory_template.csv`
  - 建筑、道路、绿地、公共服务、环境、人口、交通、规划约束等权威图层清单。

- `planning_constraint_catalog_template.csv`
  - 规划约束、城市更新单元、历史风貌保护、生态空间、公共空间和项目边界目录。

- `public_service_facility_template.csv`
  - 医疗、教育、养老、托育、文体、商业、公园、社区服务、公交和轨交站点目录。

- `environment_observation_template.csv`
  - 气象、热环境、空气质量、遥感反演和传感器观测。

- `population_vulnerability_template.csv`
  - 人口总量、日间人口、老年/儿童等脆弱性统计，建议只交付聚合结果。

- `transport_accessibility_template.csv`
  - 道路、公交、轨交、慢行、OD 或聚合活动联系。

## 管理与辅助模板

- `validation_split_template.csv`
  - 训练/留出验证划分，建议按时间、空间、政策版本或项目批次留出。

- `field_mapping_template.csv`
  - 上海原始字段到 UWM 模板字段的映射关系。

- `lineage_metadata_template.csv`
  - 源系统、源版本、抽取时间、安全等级、授权范围、脱敏方法和责任部门。

- `evidence_item_catalog_template.csv`
  - 影像、街景、照片、传感器观测、文书、现场核查、人工复核等证据索引。

- `field_dictionary.csv`
  - 汇总字段字典，说明字段类型、必需性、用途和 UWM 使用场景。

## 交付建议

1. 原始几何、个人轨迹、人口明细、健康明细、通信明细、影像原件和业务附件优先保留在上海市授权内网环境中。
2. 跨环境提交时，优先提交脱敏模板、字段映射、规模画像、统计摘要和校验报告。
3. 若字段名与模板不同，先填写 `field_mapping_template.csv`，再做规范化。
4. 第一轮接入建议至少提供 `urban_spatial_unit_inventory_template.csv`、`urban_state_observed_history_template.csv`、`urban_intervention_policy_history_template.csv`、`urban_outcome_validation_history_template.csv` 和 `production_scale_profile_template.json`。
