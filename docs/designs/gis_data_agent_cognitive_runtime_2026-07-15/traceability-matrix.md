# Cognitive Runtime Design Traceability Matrix

| Section | Main Claims | Evidence IDs | Confidence | Open Questions |
|---|---|---|---|---|
| 1 文档范围 | 目标为受监督自治、受控自我进化、本体和对象行动感知；重型平台为条件目标 | F001, F034, F036-F040 | verified design | 无 |
| 2 现状评估 | 模块丰富且已有三类本体原型，但缺少统一 Runtime、Operational Ontology 和 Action 主链 | F002-F024, F028-F033, F037-F039 | verified/inferred | 集成测试需在实施阶段补齐 |
| 3 总体架构 | 五层 Cognitive Runtime；吸收 Palantir operational ontology 但保持 GIS 垂直边界 | F001, F024, F034, F036-F038 | verified design | 无 |
| 4 运行控制 | identity、policy、budget、checkpoint | F007-F010, F024 | current+target | 物理存储待设计 |
| 5 Workspace | typed state + immutable events | F001, F021, F024 | target design | 事件保留期需 owner |
| 6 知识与证据 | 多源知识、OntologyBinding 和 EvidenceBundle | F009-F017, F028-F034 | current+target | 权威评分策略待基准测试 |
| 7 标准与本体 | Domain/Operational Ontology、动态安全、typed SDK；轻量四阶段与重型平台控制面/数据面、形式语义、多投影和准入门 | F013-F017, F028-F042 | current+target | 重型产品、SLO、TCO、组织、策略和 H3+ 门待确认 |
| 8 规划与执行 | TaskGraph + ActionType↔Capability↔Tool binding | F004-F006, F022, F024, F034, F037-F039 | current+target | capability/action inventory 待生成 |
| 9 治理试点 | 数据标准驱动治理为首条验收链 | F001, F013-F017, F031 | verified design | 真实/脱敏数据集待选定 |
| 10 评价恢复/HITL | layered evaluator + true routed loop | F003, F008, F019, F020, F024 | conflict+target | 领域阈值和审批 SLA 待 owner |
| 11 记忆 | working/episodic/procedural + write gate | F011, F012, F024 | current+target | retention 待 owner |
| 12 自我进化 | candidate→eval→shadow→canary→promotion，本体变更按风险分级 | F018-F020, F024, F034 | current+target | canary 流量比例待实施验证 |
| 13 数据设计 | run/event/evidence/memory/evolution + domain/operational ontology 逻辑模型 | F020, F025, F031, F035, F038 | target | 最终 DDL 待对应子项目设计 |
| 14 接口 | Runtime、Retriever、Ontology、Capability、ActionExecutor 和 SDK contracts | F024, F030, F034, F038-F039 | target | API/SDK 物理协议待实施 |
| 15 部署与选型 | modular monolith 为基线；重型路线条件增加 Registry、RDF/SHACL、Gateway、Policy、Event 和 Object/Action 服务 | F023, F033-F042 | current+target | 产品、策略、RPO/RTO、容量、TCO 和 H3 门待 owner |
| 16 安全/可观测/性能 | 对象/属性/关系/Action 动态安全、ChangeSet/Result、版本 trace 和重型平台恢复演练 | F008, F010, F021, F029, F034, F037-F042 | current+target | 正式 SLO、策略、HA/DR 待 owner |
| 17 实施路线 | Runtime Kernel 优先；Heavy H0-H7 是独立条件路线，H3+ 非必经 | F001, F024-F026, F034-F042 | verified design | 排期、资源和 H0 sponsor 待 owner |
| 18 验收 | runtime、retrieval、ontology、action/security/SDK 和重型平台准入/一致性/恢复门 | F024, F026, F034-F042 | target | 映射阈值和重型 SLO 需基线 |
| 19 风险 | RAG、本体、Action/tool、安全、SDK、投影、多真值和平台团队风险受控制 | F029, F033-F042 | target | 无 |
| 20 分解 | 五个顺序子项目；Heavy H0-H7 独立管理且不重写既有 GIS 能力 | F001, F034, F038-F042 | verified design | H0 是否启动待 owner |
| 21 待确认 | NFR、本体 owner、策略、Action、SDK、重型产品、事件流、TCO 和团队 | F026, F035, F038, F042 | needs-owner-input | owner 决策 |
| 22 追踪 | 证据包、审计和追踪矩阵保持可审查 | F001-F042 | verified | 无 |
| 23 结论 | 大脑是 Runtime；重型本体是条件语义/运营平台而非前置依赖 | F001, F034, F036-F042 | verified design | 无 |
