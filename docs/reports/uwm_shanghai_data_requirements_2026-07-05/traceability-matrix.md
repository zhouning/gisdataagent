# UWM 上海市权威数据需求追踪矩阵

| 文档章节 | 数据/证据来源 | 追踪说明 |
|---|---|---|
| 文件目的 | `uwm-urban-livability-strategic-technical-proposal.md` 第 1、8、9、11 节 | UWM 需要真实权威数据进入城市治理业务验证，且必须保持辅助研判和证据门控定位 |
| 核心结论 | `uwm_data_foundation_summary_2026-07-05.md` 第 1、2、6、7 节 | 当前 UWM 已有工程链条和状态预测证据，但缺真实政策 outcome 和上海权威数据 |
| 最小交付包 | `uwm-renderer-simulator-planner-theory-2026-07-04.md` 第 2-5 节、`uwm_data_foundation_summary_2026-07-05.md` 第 5 节 | renderer/simulator/planner 分别需要 canonical observation、rollout trace、plan package 和证据门控 |
| D01-D04 城市底座与服务设施 | `uwm_livability_business_theory_2026-07-05.md` 第 2-6 节 | 城市宜居性需要环境健康、公共服务可达性、空间公平、城市形态和实施约束 |
| D05 环境观测 | `uwm_data_foundation_summary_2026-07-05.md` OpenAQ temporal benchmark、air_pollution_exposure blocker | 当前真实状态预测证据来自 OpenAQ，但上海场景仍需本地权威观测和校准 |
| D06 人口脆弱性 | `uwm_data_foundation_summary_2026-07-05.md` population_vulnerability 缺口 | 公平评估需要权威人口和脆弱性汇总，不应依赖 GHSL/WorldPop 代理替代 |
| D07 交通可达与活动联系 | `uwm_data_foundation_summary_2026-07-05.md` mobility_graph / mobility_activity 缺口 | 当前 OSM highway / latent mobility 不能替代上海真实 travel-time、OD 或交通流 |
| D08-D10 干预与 outcome | `uwm_model_based_rl_inspiration_implementation_2026-07-05.md` 第 5、6 节 | 当前 planner 优势是 known-effect replay，不是 observed intervention outcome；真实 outcome 是 claim 升级前提 |
| D11 规模画像 | TWM data requirements 的 production scale profile 思路和 UWM 大城市数据规模要求 | 上海超大城市数据需要 lakehouse、分区、空间索引、分布式计算和抽样/切片策略 |
| D12-D13 血缘与证据 | `uwm-renderer-simulator-planner-theory-2026-07-04.md` provenance/evidence theory、`uwm-urban-livability-strategic-technical-proposal.md` 第 9 节 | UWM 必须记录来源、版本、脱敏、证据和人工复核，避免模型输出无审计依据 |
| 不跨环境提交数据 | `uwm-urban-livability-strategic-technical-proposal.md` 第 8.4、9 节 | UWM 优先本地/内网/政务云运行，敏感数据不出域，输出需 claim boundary 检查 |
