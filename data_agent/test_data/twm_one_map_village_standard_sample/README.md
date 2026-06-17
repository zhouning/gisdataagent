# 自然资源一张图村规划标准结构样例包

该数据包用于验证自然资源一张图村规划样例能否按 TWM 角色契约接入。

- `source_sample=true`: 来自压缩包中的村规划汇交样例，保留源字段并补齐 TWM 必需字段。
- `synthetic=true`: 当前真实权威数据缺失时的契约测试替身，例如永久基本农田、项目、审批和执法记录。
- `not_for_production=true`: 所有数据均禁止作为生产级自然资源治理结论使用。

建议先查看：

- `preview/index.html`
- `data_quality_report.md`
- `dataset_manifest.json`
- `standards/one_map_role_contracts.zh.json`
