# TWM 自然资源权威数据模板说明

本目录中的模板用于配合 `TWM自然资源部数据需求说明书.docx` 提交和沟通。模板不是法定业务表单，而是当前 TWM 生产接入、校验和模型验证所需的数据结构建议。

## 核心必填模板

- `production_observed_history_template.csv`
  - 真实审批/复核/处置观察历史。
  - 必须包含真实生产标记：`synthetic=false`、`not_for_production=false`。
  - 用于生产观察历史预检、因果/准实验校准、holdout 验证和 claim ladder 升级。

- `production_policy_history_template.csv`
  - 真实政策/动作可行性历史。
  - 重点字段是 `action_type`、`action_mask_policy`、`action_mask_allowed`、`region_code`、`period`、`policy_version`。
  - 用于 action mask 可行性验证和区域-政策覆盖检查。

- `production_scale_profile_template.json`
  - 脱敏生产规模画像。
  - 不应包含原始几何、逐行属性、敏感对象 ID 或真实内网路径。
  - 用于校验湖仓、分区、空间索引、分布式计算、抽样/切片能力。

## 空间与业务对象模板

- `spatial_layer_inventory_template.csv`
  - 现状地块、行政区、控制线、年度变更、证据图层等空间图层清单。

- `control_layer_catalog_template.csv`
  - 永久基本农田、生态保护红线、城镇开发边界、用途管制分区等法定控制线目录。

- `project_approval_review_template.csv`
  - 项目、审批件、审查任务、复核结论等业务对象目录。

- `annual_change_history_template.csv`
  - 年度变更或多期状态快照。

- `spatial_relation_template.csv`
  - 邻接、包含、相交、重叠、项目-地块关联等空间关系。

- `evidence_item_catalog_template.csv`
  - 影像、照片、文书、现场核查、规则命中等证据索引。

## 管理与辅助模板

- `validation_split_template.csv`
  - 训练/留出验证划分，建议按时间、区域或政策版本留出。

- `field_mapping_template.csv`
  - 原始字段到 TWM 模板字段的映射关系。

- `lineage_metadata_template.csv`
  - 源系统、源版本、抽取时间、安全等级、脱敏方法和责任部门。

- `field_dictionary.csv`
  - 汇总字段字典，说明每个字段的类型、必需性、用途和 TWM 使用场景。

## 交付建议

1. 原始几何、影像、附件和逐行敏感属性优先保留在自然资源内网权威环境中。
2. 跨环境提交时，优先提交脱敏模板、字段映射、规模画像和校验报告。
3. 若字段名与模板不同，先填写 `field_mapping_template.csv`，再做规范化。
4. 第一轮接入建议至少提供 `production_observed_history_template.csv`、`production_policy_history_template.csv` 和 `production_scale_profile_template.json`。
