# ADR-153: 对话式本体查询、语义网关与 OKF 0.2 知识包

**Status**: Accepted, amended for official OKF v0.2 conformance

**Date**: 2026-08-05

**Related**: ADR-139, ADR-140

## Context

左侧对话窗口需要回答自然资源概念、层级、关系路径、状态转换、字段映射和本体应用场景，
并驱动右侧本体视图、演示场景和地图。回答必须绑定已发布本体版本和来源，不能让大模型自由生成
SQL/SPARQL，也不能把功能、页面或数据库表误当成领域类。

系统同时需要明确 Google ADK、OKF、RDF 存储和业务数据库的职责。OKF 是 Agent 与人员共同
读取、交换和维护的 Markdown/YAML 知识包；`Attested Computation` 只是其中一种可选概念类型，
不是所有查询结果的通用包装。OKF 不是本体数据库、查询引擎、Agent 运行时或权威发布库。

## Options Considered

| 方案 | 优点 | 风险 | 结论 |
|---|---|---|---|
| 大模型直接生成 SPARQL | 灵活、开发量低 | 注入、越权、无预算、语义幻觉 | 不选 |
| 仅做向量检索/RAG | 易接入对话 | 不能可靠表达类层级、关系方向和转换约束 | 不选 |
| 专用 Agent + 类型化查询计划 + 语义网关 | 可治理、可解释、可联动 | 需要维护查询合同和模板 | 选择 |

## Decision

### 1. 对话运行时

Google ADK 中设置独立 `OntologyAnalysisAgent`。确定性意图路由先识别本体问题，Agent 只能调用
`query_ontology` 和 `run_ontology_application_scenario` 两个高层工具。工具接收封闭的
`OntologyQueryPlan`，支持概念解释、层级、关系路径、转换规则、字段映射和已注册场景；合同明确
禁止额外 SQL/SPARQL 字段。

转换问题既允许以过程类为主语（如“建设占用允许哪些源状态和目标状态”），也允许使用业务人员
更自然的实体类或状态类问法（如“农用地可以怎样转换”）。对于实体类，语义网关按受治理的稳定
代码约定确定性映射到相应土地利用状态类，并仅在有界的上下位状态范围内反查转换过程；RDF 侧由
`state_transition_processes` 白名单模板复核。映射方法、命中的状态范围和过程规则都进入查询结果，
不存在对应状态类时明确返回“尚未注册”，不让大模型猜测过程。

当问题同时给出目标概念（如“农用地如何转为建设用地”），网关分别解析源、目标利用状态，仅保留
源端命中 `allowedSource` 且目标端命中 `allowedTarget` 的过程。随后使用 `transition_rules` 白名单
模板逐一复核命中过程的完整源/目标规则，避免把“与源概念相关”误答为“能够到达指定目标”。

### 2. 查询与存储边界

- Apache Jena Fuseki 5.5.0/TDB2 保存并查询 OWL/RDF 读投影，SPARQL 仅使用服务端白名单模板。
- PostgreSQL `gda_ontology` 保存发布版本、映射、来源、校验、审计和活动版本指针。
- 不可变 `2.0.1` 包是 hash 校验的发布、恢复和 Protege 导出单元。
- PostGIS/MMFE 执行对象级空间计算和语义融合，不把批量 geometry 放入 RDF。

RDF 投影不可用时，查询网关可回退到权威 PostgreSQL/不可变包，并必须在回答证据中显式报告
回退。任意 SPARQL、无界遍历和本体写操作均不暴露给浏览器或 Agent。

### 3. OKF 0.2 知识包的位置

系统发布真实的 `natural-resource-ontology-knowledge-v2` OKF bundle。根 `index.md` 精确声明
`okf_version: "0.2"`，概念文档使用 Markdown 和 YAML frontmatter，包含本体资产、转换模型、
映射目录、来源和已批准计算。知识包可由 Agent、人员、搜索索引或知识界面渐进读取。

普通概念、层级、关系和映射查询返回：

- `okf_reference`：指向 bundle 中已有的知识概念，不把 JSON 响应伪装成 OKF bundle；
- `query_provenance`：记录本次查询参数、执行 Agent、生成时间和本体包摘要；
- 不返回 attestation，因为普通只读查询不是官方定义的 `Attested Computation`。

和平村、斑竹村等注册分析场景引用独立的 `Attested Computation` 概念。概念必须声明类型化
`parameters`、固定 `computation`、`executor.resource`、receipt 字段和无 LLM 的
`attester.resource`。Agent 只能绑定已声明参数，运行时依次执行：

1. 校验活动本体、计算资源和版本锁定输入；
2. 执行批准的确定性计算并生成 receipt；
3. attester 独立重读输入、计算摘要并核对展示结果；
4. 通过时返回 `display`，失败时返回 `refuse_display`，且不发送地图图层。

receipt 与 verdict 是每次运行产生的运行时产物，不写入静态 bundle。`verified` 确认知识定义
仍符合发布规则，attestation 确认某一次运行确实绑定并执行了批准计算，两者不能混用。

MMFE 语义产品可另外导出 `mmfe.okf_export.v2` sidecar，供其他 Agent、评审人员和跨系统交换
字段语义、关系、规则和来源。OKF 不自动晋升候选映射，不替代 OWL/SHACL 校验，也不承担在线
SPARQL 查询。

平台消费兼容基线为 OKF `0.2+`。bundle 仍写入精确规范版本 `0.2`；`compatibility` 只出现在
平台引用合同中，不写入 bundle 根 `index.md`。

### 4. 工作区联动

工具结果同时返回受限 `workspace_update`：概念查询聚焦“本体模型”页的稳定概念 ID；场景查询
打开“本体应用”页、运行已注册场景，并发送 `map_update`。前端只接受白名单字段，通过
`gda-workspace-update` 事件切换视图，不能执行工具结果中的任意脚本或查询。

## Consequences

### Positive

- 对话回答、右侧模型、场景地图和 OKF 知识来源使用同一 `2.0.1` package hash。
- 客户演示场景只有在 receipt 通过确定性 attester 后才展示结论和地图。
- 专业 RDF 查询能力与既有事务治理并存，不形成两个可写权威源。
- 客户能够看到“概念关系如何参与判断”，而不只是一个聊天答案或静态知识图谱。

### Negative

- 新增 Fuseki/TDB2 运维、投影验收和固定查询模板维护成本。
- 新问题类型需要先扩展查询合同和测试，不能依赖大模型即时拼接 SPARQL。

### Mitigation

- 镜像绑定 Jena `5.5.0` 与本体 `2.0.1`，校验 Apache SHA-512 和 Turtle SHA-256。
- RDF 服务仅开放 query/read-only Graph Store，Compose/Kubernetes 在应用启动前验证 528,252
  条三元组，运行时状态再做受限 COUNT 探测。
- 查询结果始终返回版本、hash、后端、回退告警、来源和真实 OKF bundle 概念引用。
- CI 校验 bundle 结构、计算合同字段、资源可达性，并以篡改 receipt 测试验证展示门禁。
