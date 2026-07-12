# 重庆文化遗产与场所语境证据产品验证报告（需求16）

- 验证日期：2026-07-12
- 产品路线：传统GIS证据分层，不启用未校准UWM Kernel
- Schema：`traditional_livability.cultural_heritage_place_evidence.v1`
- Bundle：`traditional-cultural-heritage-8de63c2759baba60b586`
- Digest：`sha256:9a6f79cbb1807a3c5be2bc0e6d75ff9d2f5f7339cb78585cacf6936598d31e36`

## 真实数据结果

- 输入设施POI：76,292。
- 文化相关证据记录：1,741。
- 明确文化场所证据：242。
- 遗产候选线索：59。
- 关键词歧义排除：1,440。
- 非文化相关记录：74,551。
- 行政单元：39；源行政信息未映射记录：410。

明确文化场所分类：文物古迹72、展览/美术场所27、纪念馆4、博物馆28、宗教场所111。

## 核心边界

明确文化场所仅表示源分类支持文化场所类别，不表示法定文化遗产。名称关键词只生成核查线索；村名、银行、停车场、酒店、商店和普通地址即使名称含“寺、庙、古”等字样也不会提升为明确文化场所。

所有记录的法定遗产状态保持 `null`。产品不输出文化价值、真实性、完整性、保护质量、游客吸引力、社区认同、活化潜力、投资优先级或政策效果评分。

## 验证结果

- 聚焦后端测试：14 passed。
- 独立五文件校验：通过。
- 前端TypeScript/Vite生产构建：通过。
- 伪造值：0。
- 最大声明能力：`cultural_place_inventory_candidate_leads_and_heritage_evidence_readiness`。
