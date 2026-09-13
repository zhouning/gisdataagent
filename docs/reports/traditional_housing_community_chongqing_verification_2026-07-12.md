# 重庆住房与社区构成证据产品验证报告（需求13）

- 验证日期：2026-07-12
- 产品模式：城市宜居性分析（传统方法）
- Schema：`traditional_livability.housing_community_evidence.v1`
- Bundle：`traditional-housing-community-bdc129bdab6a460d7731`
- Digest：`sha256:3ba0fa0b90b8167e912ffdf2fdf44d494cd9da04610cf5da00419951c66f2c45`

## 真实数据结果

- 建筑源记录：107,452；解析几何：107,452；已分配：44,887；未分配：62,565。
- 建筑形态行政单元：36；楼层数代理合计：322,665；最大楼层：66。
- 下推人口代理行政单元：852；区县人口统计：39。
- 产品行政单元：852；建筑形态精确 `admin_unit_id` 匹配：36；人口代理精确匹配：852；显式 `admin_code` 区县统计连接：852。
- 伪造值：0。

## 技术边界

产品只支持 `building_morphology_context`、`population_context` 和 `housing_evidence_readiness`。建筑数不等于住房套数，楼层数不等于住宅面积，下推人口不是人口普查微观数据，人口密度不等于住房拥挤，相对证据缺口不等于权威住房短缺。

住房类型、套数、住宅面积、空置、价格租金、可负担性、产权/租赁、家庭规模与构成、工人住宿、家庭适宜性、拥挤、职住观测邻近、混合使用、住房需求/短缺、开发建议和政策因果效果均保持 `unavailable` 且值为 `null`。

## 验证结果

- 聚焦 Python 测试：3 passed。
- 独立五文件校验：通过。
- 前端 TypeScript/Vite 生产构建：通过。
- 最大可声明能力：`building_morphology_population_context_and_housing_evidence_readiness`。
