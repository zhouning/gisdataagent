# Cognitive Runtime Design Document Audit

## 1. Audit Scope

本次不是对既有 Cognitive Runtime DOCX 的修订，而是依据已确认 Markdown 架构规格和当前代码生成首版正式详细设计文档。`semantic_fusion_engine_technical_spec.docx` 仅用于观察中文标题、表格和段落风格，不继承其业务内容。

## 2. Current Implementation Versus Target Design

| Area | Current Evidence | Target State | Status |
|---|---|---|---|
| Agent roles | 已有多个专用 Agent 和 Workflow | capability-driven specialists | partially-aligned |
| Runtime policy | UI 可组装安全插件，headless 可传空插件 | mandatory RunnerFactory | gap |
| Shared workspace | 主要依赖 session state、output_key 和 prompt context | typed RunWorkspace + events | gap |
| Quality loop | generator→checker 顺序执行 | routed revise/replan loop | conflict |
| Knowledge | KB、语义层、标准向量检索、图谱均存在 | EvidenceBundle + authority/validity/ACL | partially-aligned |
| Standards | 条款、数据元、术语、值域、引用和派生存在 | StandardKnowledgePack compiler | partially-aligned |
| Ontology | GIS YAML Reasoner、MMFE ontology package、Standards 关系资产分别存在 | governed Authority Store + OntologyPackage + Resolver | partially-aligned but fragmented |
| Heavy ontology platform | 未发现专用 RDF/SHACL、Policy、Kafka/Redpanda Ontology Platform | 条件目标：Model Registry + semantic/operational serving + CI/CD + HA/DR | not-started; entry-gated |
| Operational ontology | Capability、Toolset、Skill、Operator、MCP 和 REST 分别描述行为 | Object/Property/Link/Action/Function/Interface + unified binding | gap |
| Dynamic security | 多入口、ContextVar、插件和部分 ACL 基础 | object/property/link/action/result/context policy | gap |
| Typed consumption | REST、Python、TypeScript、MCP/A2A schema 分散 | OSDK-like generated/validated contracts | gap |
| Memory | memory service 和多种记忆模块存在 | proactive retrieval + write gate | partially-aligned |
| Planning | Planner、task decomposition、workflow engine 存在 | typed TaskFrame/TaskGraph | partially-aligned |
| Tool control | Toolset、Skill、Operator、MCP、ArcPy 存在 | capability registry + small manifest | gap |
| Evaluation | evaluator registry、eval history、failure-to-eval 存在 | independent layered evaluator and promotion gates | partially-aligned |
| Evolution | 多个 evolution 模块存在 | unified candidate/governor/promotion plane | gap |
| Observability | OTel 和 metrics helper 存在 | event-backed cognitive replay | partially-aligned |

## 3. Evidence Conflicts

1. 现有命名将三个质量流程称为 loop，但代码没有条件回跳；正式文档按“当前顺序质量门、目标真实循环”分别表述。
2. 部分历史文档将 memory service 描述为 ADK 自动检索；当前主链证据不足以证明主动检索和完成后写回，正式文档标记为目标能力。
3. ContextEngine 文档描述 embedding boost，但当前实现保持 provider 原分数；正式文档不将其表述为已实现 rerank。
4. Prompt、Tool 和 Self-Evolution 模块存在，但没有统一 candidate-evaluation-promotion 运行语义；正式文档将统一 Evolution Plane 标记为目标设计。
5. 当前 `OntologyReasoner` 将所有 ontology 匹配固定为 0.85，并通过 `pd.eval` 执行 YAML 派生公式；正式设计将其作为原型证据，不将其描述为已满足生产安全和置信度校准。
6. `mmfe.semantic_ontology.v1` 已形成有效 JSON 契约，但当前作用域集中于 MMFE/TWM；正式设计将其作为统一 OntologyPackage 的输入原型，而不是宣称全项目已具有统一本体服务。
7. Palantir 是已长期生产验证的平台，而 GIS Data Agent 的 Operational Ontology 和统一 Runtime 是目标设计；V1.3 明确分开“架构可比性”和“当前产品成熟度”。
8. 当前 Toolset、Skill、Operator、MCP 和 API 不能自动视为统一 Action model；只有完成 ActionType↔Capability↔Tool/Evaluator 版本绑定和集成测试后才能升级该主张。
9. 重型本体架构由 owner 明确要求形成目标设计，但仓库没有对应平台实现；V1.3 将其标记为带 H0 准入门的条件路线，不表述为当前能力或必经阶段。

## 4. Unsupported or Owner-Dependent Items

以下内容保持 `needs-owner-input`，不在正式文档中给出虚假承诺：

- 正式生产并发和吞吐目标；
- p95/p99 绝对延迟 SLO；
- RPO、RTO 和异地容灾要求；
- 记忆、trace、标准快照和产物保留期限；
- HITL 审批时限和组织责任人；
- Cognitive Runtime 物理表最终字段、分区和索引；
- 是否引入 OPA、OpenSearch、专用向量库或图数据库的规模阈值；
- 领域 embedding/reranker 训练数据和模型选择；
- 本体概念映射 precision/recall、未知拒绝率和代表性查询延迟；
- 本体领域 owner、审定委员会、namespace/稳定 URI 和变更 SLA；
- Stage 3 是否引入 Fuseki/TDB2、Neo4j/AGE 或其他专用图服务的基准阈值；
- Operational ObjectType/ActionType 的首批对象、状态机和事务边界；
- 动态策略引擎采用现有代码、OPA 或 Cedar；
- Python/TypeScript/OpenAPI/MCP/A2A SDK 兼容性和废弃政策。
- Heavy H0 competency questions、业务 sponsor、三年 TCO 和组织准入门；
- 重型 RDF/语义平台、Kafka/Redpanda、Schema Registry、HA/DR 拓扑和供应商选择；
- 重型平台团队编制、预算、值班和外部支持。

## 5. Diagram Audit

现有目标规格只有 Mermaid 总体图，缺少正式 Word 所需的动态图和部署/数据视图。本次重新生成以下可编辑图：

1. Cognitive Runtime 总体组件架构；
2. 认知闭环状态图；
3. 多源知识与 EvidenceBundle 架构；
4. 数据标准驱动治理时序图；
5. 受控自我进化流水线；
6. 分阶段部署拓扑；
7. 核心逻辑数据关系图。
8. 领域本体生产架构与分阶段读投影。
9. Operational Ontology、动态安全、Action、Capability、ChangeSet、Evaluator 和写回闭环。
10. 重型本体生产平台的治理、注册、形式语义、运营对象、查询、安全、事件、投影、执行和运维架构。

所有图均保留 Mermaid 源和 PNG 渲染件，并在正式文档中标注“当前/目标”性质。

## 6. Document Structure Decision

正式 DOCX 采用以下结构：范围与依据、现状评估、总体架构、运行控制、知识与标准、本体生产架构与选型、规划执行、评价恢复、记忆、自我进化、数据设计、接口和部署、试点流程、实施路线、验收指标、风险、追踪矩阵和待确认事项。
