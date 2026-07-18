# GIS Data Agent 主线 Roadmap 接续 Checkpoint

**日期**：2026-07-18

**分支**：`feat/v12-extensible-platform`

**主文档**：`docs/roadmap.md`

**状态**：Roadmap 战略与本体智能主线刷新完成；主线代码开发主动暂停，等待 ArcPy MCP 与 GWM 并行开发稳定。

## 1. 已冻结的最高层产品章程

1. GIS Data Agent 首先是一个优先面向自然资源和城市场景、同时支持空间与非空间多类型数据的 **Geospatial-Native、Agentic-Native、Ontology-Grounded Data Platform**。
2. 即使不部署 GWM，平台也必须凭借严格数据治理、轻量生产本体、数据工程、MMFE、可信数据产品和 Human/Agent/AI 一致消费而独立成立。
3. **GWM 是 GIS Data Agent 的特有空间世界认知内核和核心差异化能力**，但不成为标准、模型、质量、安全、MMFE、发布和消费的基础依赖。
4. 带 GWM 的产品由 LLM 与 GWM 双智能引擎支撑：LLM 负责语义、知识、意图、解释与治理编排；GWM 负责多尺度空间世界状态、地理过程、行动条件推演、不确定性和证据边界。
5. `LLM + GWM + Agentic Data Platform` 的原创性必须通过先行技术检索与传统/规则、LLM-only、GWM-only、LLM+GWM 四路同题消融验证。

## 2. Roadmap 当前主线

| 阶段 | 当前定位 |
|---|---|
| NDP-0 | Product/Ontology Charter、严格治理三维模型、数据类型矩阵、四契约族、PlatformCore/OntologyCore/GeoCore/Domain Pack/GWM 边界、Ontology Meta-model、Competency Questions 与资产映射 |
| NDP-1A | Cognitive Runtime/Security Consistency first slice：RuntimeIdentity、RunnerFactory、Workspace、Policy、真实质量回跳、恢复和隔离 |
| NDP-1B | Ontology Knowledge Brain、PostgreSQL Authority、OntologyPackage/Compiler/Resolver、Object/Action 契约、Trusted Data Product 与 Human/Agent/AI 消费闭环 |
| NDP-2 | MMFE Semantic Fusion 产品化、空间/非空间多类型数据、Data for AI Factory、Dataset/Model/DataDemand 谱系 |
| NDP-3 | 共享 GWM Runtime Kernel、TWM/UWM adapters、EvidenceClaimLedger 与 LLM+GWM 双引擎验证 |
| NDP-4 | Prospective Action/Outcome、现实学习、Heavy Ontology H0-H7、联邦、互操作、隐私与生态条件路线 |

真实 Action-Outcome 是 GWM 强因果和决策优势的能力升级门，不是 Core Data Platform、状态模型或条件模拟的启动门。

## 3. 数据治理与 MMFE 的冻结口径

```text
Data Governance = Governance Domain × Data Lifecycle Stage × Control Contract
```

- Governance Domain 至少包括标准、模型、元数据/目录、主数据/参考数据、语义/本体、质量、安全/隐私、血缘、生命周期、数据资产/产品、合规/审计和使用反馈。
- Agentic-native 治理必须有 typed Governed Object、Authority、Owner、Trigger、Agent Action、Capability、Policy、Evaluator、HITL、ChangeSet、Version、Evidence 和 KPI。
- MMFE 是数据产品生产主线中的多模态智能语义融合引擎，不是旁路 ETL，也不只服务 TWM/UWM。
- MMFE 输出目标为版本化 `SemanticFusionProductVersion`，并以语义映射、实体解析、时空对齐、冲突/置信度、人工修正、吞吐/成本和下游增益验收。

## 4. 本体路线的当前归属

Roadmap 已显式包含：

- Governance Domain 中的语义/本体；
- `GeoCore`、NaturalResource/Urban Domain Pack；
- `SemanticPackVersion` 与 Authority Resolver；
- Cognitive Runtime 下的 Standards Knowledge Brain；
- Domain/Operational Ontology Store/Compiler/Package/Resolver；
- Operational Object/Action Model；
- Heavy Ontology H0-H7 条件路线。

轻量本体路线已经上提到 NDP 主表：

```text
NDP-0  Ontology Charter / Meta-model / GeoCore / Domain / Operational / GWM ontology boundary / Competency Questions
NDP-1A Cognitive Runtime identity / policy / workspace / evaluation / isolation
NDP-1B PostgreSQL authority + versioned OntologyPackage + Compiler/Resolver + Object/Action contracts + Trusted Data Product
NDP-2  MMFE ontology-guided semantic alignment and benchmark
NDP-3  GWM consumes ontology projections for TWM/UWM state/action semantics
NDP-4  online RDF/SHACL/GeoSPARQL/federation only when Heavy Ontology entry gates pass
```

构建时 SKOS/SHACL/PROV-O/必要 GeoSPARQL/OWL-Time 验证可在轻量 Stage 2 进入 NDP-1B/NDP-2；专用 RDF/SPARQL 在线服务仍保持 H0/H3 条件触发。

## 5. 暂停主线代码开发的原因

### ArcPy MCP

- 独立 worktree：`.worktrees/arcpy-mcp-integration`
- 分支：`feat/arcpy-mcp-integration`
- 当前 worktree 干净。
- 主要所有权：`data_agent/app.py`、`api/mcp_routes.py`、`arcpy_mcp_client.py`、`mcp_hub.py`、`mcp_runtime.py`、`mcp_transport.py`、`health.py` 及对应测试。

### GWM/TWM/UWM

- 当前根工作树存在大量未提交的 GWM/UWM/API/frontend/benchmark 改动，应视为 GWM 集成现场。
- 独立 TWM worktree：`.worktrees/twm-future-latent-state-v2`，分支 `feat/twm-future-latent-state-v2`。
- TWM 分支与主分支在 `territory_world_model/neural_dynamics.py`、`service.py`、测试和 handoff 上均有同名改动，合并风险高。

## 6. 恢复主线的强制条件

1. ArcPy MCP 与 GWM/TWM/UWM 窗口分别提交完整工作并形成 handoff。
2. 选定统一集成基线，解决 `app.py`、TWM/UWM 共享实现和 API/frontend 装配冲突。
3. 目标 commit 的核心后端测试、前端构建和契约检查恢复稳定。
4. 工作树中的未提交文件完成归属确认，不混入主线提交。
5. 从稳定 commit 创建独立 worktree（建议 `.worktrees/ndp-platform-core`）继续 NDP。

## 7. 新窗口建议执行顺序

1. 运行 `git status -sb`、`git worktree list --porcelain` 和 `git log -5 --oneline --decorate`，核对并行开发是否已经合并。
2. 阅读本 checkpoint 和 `docs/roadmap.md` 顶层 Strategic Program。
3. 创建 NDP-0 正式规格：治理能力矩阵、Ontology Meta-model、30-50 个 Competency Questions、资产/表/API/schema/本体映射、四契约族和双试点验收集。
4. 第一份代码计划只覆盖 NDP-1A Cognitive Runtime/Security Consistency first slice，不同时混入 Ontology/DataProduct、MMFE 和 GWM Kernel 大改。
5. NDP-1A 退出门通过后，再为 NDP-1B Ontology Knowledge Brain/Trusted Data Product 创建独立规格、实施计划和回滚方案。

## 8. 本次提交边界

本 checkpoint 与 `docs/roadmap.md` 是本次主线保存范围。当前工作树中其它 ArcPy、GWM、UWM、Paper58、前端、脚本、报告及测试改动均属于其它窗口或既有工作，不在本次修改范围内。

文档验证已完成：Markdown 围栏配对、相对链接存在、`git diff --check` 通过；本轮未修改运行代码，因此未运行代码测试。
