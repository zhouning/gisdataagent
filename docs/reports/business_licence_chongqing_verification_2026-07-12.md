# 重庆企业执照与经济活动证据验证报告（需求20）

- 日期：2026-07-12
- Schema：`uwm.business_licence_activity_readiness.v1`
- Bundle：`business-licence-98b6b77530c924e1173d`
- 来源需求14 Bundle：`traditional-daily-convenience-f60dac40e168c758ea18`
- Digest：`sha256:c10817568814e41f897c24495c8c1308d6c894d51d88f5e051b631ecc4d07ced`

## 真实结果

- 企业与商业活动POI：3,749。
- 区县：39。
- 可用权威执照通道：0。
- 开放企业生命周期UWM机制：0。
- 伪造值：0。

POI记录仅保留地点ID、名称、类别、坐标、行政代码和源记录血缘。需求14中的就业、收入、交易等空字段也未被继承到需求20产品，避免将其误解为经济分析字段。

## 边界

企业POI不等于法定企业登记，不等于有效执照，不等于实际营业。企业名称不构成权威实体匹配，工业企业POI不表示实际生产，企业数量不表示就业或经济产出。缺失执照数据不表示无证经营。

产品不输出有效执照企业数、无证经营数、开业退出率、存活率、就业、营业额、税收、经济贡献、企业健康度、招商潜力、投资优先级或政策效果。

## 验证

- 聚焦后端测试：16 passed。
- POI字段白名单、空值执照通道和关闭生命周期机制独立校验：通过。
- 前端TypeScript/Vite生产构建：通过。
- 最大声明：`business_poi_spatial_evidence_and_authoritative_licence_lifecycle_readiness`。
