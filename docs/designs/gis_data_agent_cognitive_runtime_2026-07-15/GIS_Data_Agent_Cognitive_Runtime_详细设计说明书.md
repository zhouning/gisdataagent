# GIS Data Agent Cognitive Runtime 详细设计说明书

**文档版本：** V1.3<br>
**编制日期：** 2026-07-15<br>
**设计性质：** 目标架构与分阶段实施设计<br>
**首个试点：** 数据标准驱动的空间数据治理<br>
**自主等级：** 受监督自主执行与受控自我进化<br>
**证据基线：** Git commit `1421e005b227524ce35d537688a140bd2d8d16e7`

## 修订记录

| 版本 | 日期 | 修订说明 | 状态 |
|---|---|---|---|
| V1.0 | 2026-07-15 | 基于已确认 Cognitive Runtime 规格和当前代码证据形成首版正式详细设计 | 评审版 |
| V1.1 | 2026-07-15 | 将领域本体、知识编译、本体治理及分阶段生产技术选型融合进 Cognitive Runtime | 评审版 |
| V1.2 | 2026-07-15 | 基于 Palantir AIP/Ontology 客观对比补充 Operational Ontology、对象行动闭环、动态安全和统一消费层 | 评审版 |
| V1.3 | 2026-07-15 | 增加企业级重型本体条件目标架构、控制/数据平面、形式语义平台、多投影一致性、生产拓扑、组织门和准入路线 | 评审版 |

## 1. 文档目的与范围

### 1.1 编制目的

本说明书用于定义 GIS Data Agent 面向生产级智能体的“认知大脑”设计。文档重点描述统一运行控制、认知工作区、多源知识、数据标准、领域本体、任务规划、专业工具执行、质量评价、记忆、HITL 和受控自我进化之间的职责边界与协作关系。

本设计不把大语言模型、RAG、领域本体、Planner 或单一 Agent 等同于完整大脑。完整大脑被定义为由确定性运行时包围概率模型、能够改变真实数据状态并验证结果的 Cognitive Runtime。本体是大脑的受治理领域语义骨架，负责概念、关系、约束和能力语义，不负责运行时路由、授权或工具副作用控制。

### 1.2 设计目标

系统应具备以下能力：

- 将自然语言目标转换为强类型任务契约；
- 检索具有权限、版本、地域、时间和来源信息的领域证据；
- 将数据标准编译为原文、结构化对象和可执行规则；
- 将 Standards Platform、GIS 本体原型、MMFE 语义本体和运行能力语义收束为版本化 OntologyPackage；
- 通过领域本体完成概念消歧、字段/数据元映射、关系导航、能力选择和结果约束验证；
- 生成可执行、可验证的任务图；
- 选择窄职责 Specialist 和有限工具清单；
- 调用 SQL、PostGIS、ArcPy、治理、TWM 和报告能力产生真实产物；
- 通过独立 Evaluator 控制通过、重试、检索、重规划和 HITL；
- 保存事件、checkpoint、产物、血缘和运行版本；
- 将成功和失败转化为结构化经验；
- 通过候选、评测、shadow、canary、晋级和回滚实现受控自我进化。

### 1.3 非目标

首期不包含：在线自动修改生产代码、在线模型权重更新、完全取消 HITL、将所有数据转成向量、一次性微服务化、一次性重写全部 pipeline、将完整聊天记录直接保存为长期记忆、构建覆盖所有 GIS 知识的“大而全”本体、把全部空间要素复制进 RDF/图数据库，以及在轻量 Stage 1/2 尚未证明不足前直接部署重型本体平台。

### 1.4 输入与证据

本说明书使用以下输入：

- 已确认目标规格：`docs/superpowers/specs/2026-07-15-gis-data-agent-cognitive-runtime-design.md`；
- 当前 Agent、Workflow、Runner、插件、ContextEngine、Memory、Standards Platform、Evaluation 和 Evolution 代码；
- `data_agent/fusion/ontology.py`、`data_agent/standards/gis_ontology.yaml` 和 `data_agent/fusion/semantic_ontology.py` 等现有本体原型；
- `docs/reports/gis-data-agent-brain-vs-palantir-objective-comparison-2026-07-15.md` 及其 Palantir 官方公开资料基线；
- `docs/reports/gis-data-agent-heavy-ontology-production-architecture-2026-07-15.md` 中的企业级重型本体条件目标架构；
- Docker、Docker Compose、PostGIS/pgvector 和 Kubernetes 配置；
- `evidence-pack.md`、`design-doc-audit.md` 和 `traceability-matrix.md`。

正式文档中“当前实现”和“目标设计”分别表述。未由现有证据确定的容量、SLO、RPO/RTO 和保留期统一列为 `needs-owner-input`。

## 2. 当前实现评估

### 2.1 已有基础

当前项目已经具备多 Agent 和 Workflow、语义层、数据标准平台、知识库、GraphRAG、记忆、Planner、Evaluator、Guardrail、HITL、OTel、Prompt Registry、Tool Evolution 和 Self-Evolution 等模块。[证据：F002、F004、F006、F008、F009、F011、F013-F023]

数据标准平台已经实现：

- 标准文件采集与结构化；
- 条款、术语、数据元和值域；
- 引用搜索和引用审定；
- pgvector 相似条款检索；
- 发布、版本、回滚和市场；
- SemanticHint、Synonym、QC Rule、Spatial Policy Rule 和 Data Model 等派生能力。

当前还存在三类本体实现基础：[证据：F028-F032]

- `gis_ontology.yaml` 与 `OntologyReasoner` 已支持字段等价组、字段派生和条件推断；
- MMFE 已生成 `mmfe.semantic_ontology.v1` JSON 本体包，包含概念、关系、治理契约和消费契约；
- Standards Platform 的条款、术语、数据元、值域、引用、派生链、影响图和 XMI 输出已具备构建权威本体写模型的主要素材。

这些能力目前分别服务于 Fusion、MMFE/TWM 和 Standards Platform，尚未形成统一命名空间、统一版本、统一 ACL、统一发布审定和统一运行时解析契约。

### 2.2 主要结构性缺口

| 领域 | 当前状态 | 目标状态 |
|---|---|---|
| 运行入口 | UI 和 headless 入口可采用不同插件策略 | 所有入口使用统一 RunnerFactory |
| 工作状态 | session state、output_key 和 prompt 上下文分散 | 强类型 RunWorkspace 和事件流 |
| 质量循环 | generator→checker 顺序执行 | Evaluator verdict 驱动真实回跳 |
| 工具选择 | 通用 Agent 暴露大量 Toolset | Capability Registry + 动态小工具集 |
| 知识 | 多类知识源存在但缺少统一证据契约 | EvidenceBundle 和权威优先级 |
| 本体 | YAML Reasoner、MMFE 本体包和 Standards 结构化关系并存 | 受治理 Authority Store + OntologyPackage + OntologyResolver |
| 运营对象与行动 | Capability、Tool、Workflow 和 API 分散表达动作语义 | ObjectType/ActionType/FunctionType 与 Capability、Policy、ChangeSet 统一 |
| 记忆 | service 和工具存在，主动检索/写门不足 | 显式检索、写门、纠错和保留策略 |
| 自我进化 | 多个模块并存 | Candidate Registry + Evolution Governor |
| 可观测性 | span 和指标基础存在 | 可回放的认知事件和版本追踪 |

当前 `_quality_gate_workflow` 只有 generator 到 checker 的顺序边，`max_iterations` 不构成执行回跳。[证据：F003]

## 3. 总体架构设计

![图 3-1 GIS Data Agent Cognitive Runtime 总体架构](diagrams/01_overall_architecture.png)

图 3-1 将大脑划分为五层：运行控制、认知工作区、认知模块、专业执行和学习进化。

### 3.1 Runtime Control Plane

负责身份、权限、策略、预算、版本、trace、checkpoint、幂等和取消。它是所有入口不可绕过的控制边界。

### 3.2 Cognitive Workspace

保存目标、任务契约、计划、证据、记忆命中、工具观察、产物、失败路径、评价反馈、预算和版本。各认知模块不通过自由文本互相猜测状态。

### 3.3 Cognitive Modules

包括 Perception、Retrieval、Ontology Resolution、Planning、Execution、Evaluation 和 HITL。模块由 AttentionRouter 选择，不自行建立隐式循环。

### 3.4 Execution Plane

由 StandardsGovernance、SpatialAnalysis、NL2SQL、ArcPy、TWM、Visualization 和 Report 等 Specialist 承担真实操作。

### 3.5 Learning and Evolution Plane

从生产 trace、评价和人工修订中形成 EvolutionEvent，生成候选并通过独立评测和灰度晋级。

### 3.6 Palantir 标杆边界

本设计吸收 Palantir 公开产品中 operational ontology、动态安全、对象行动闭环、typed SDK 和受治理发布的思想，但不以复制通用 Foundry 为目标。GIS Data Agent 保留自然资源数据标准、空间规则、PostGIS/ArcPy、TWM、规划推演和 EvidenceBundle 的垂直边界。[证据：F036-F038]

Palantir 是已长期生产验证的企业平台，GIS Data Agent 的 Operational Ontology、统一 Cognitive Runtime 和 Controlled Evolution 仍是目标设计；本说明书不把目标契约表述为当前已达到 Palantir 产品成熟度。

## 4. 运行控制设计

### 4.1 RuntimeIdentity

```python
class RuntimeIdentity(BaseModel):
    tenant_id: str
    user_id: str
    organization_id: str | None
    role: str
    permissions: set[str]
    data_scopes: set[str]
    knowledge_scopes: set[str]
    object_scopes: set[str]
    action_permissions: set[str]
    session_id: str | None
```

RuntimeIdentity 必须显式传入检索、记忆、缓存、Capability 和工具。不得假设线程池、异步 Worker 或远程 MCP 会自动继承用户 ContextVar。

### 4.2 RuntimePolicy

RuntimePolicy 至少包含：

- 必需插件清单；
- 模型路由策略；
- 副作用等级；
- HITL 策略；
- 迭代、token、成本、时间和工具失败预算；
- 检索次数和上下文预算；
- trace、checkpoint 和审计要求。

LLM 可以解释风险，但不能授予权限、扩大数据范围或跳过审批。

### 4.3 统一 RunnerFactory

UI、API、MCP、A2A、队列、CLI、TUI 和 Bot 都调用同一个 Runtime 入口。调用方可以追加受控扩展，但不能将必需安全插件替换为空列表。

## 5. Cognitive Workspace 与状态机

### 5.1 Workspace 核心结构

```python
class RunWorkspace(BaseModel):
    run_id: str
    identity: RuntimeIdentity
    goal: str
    task_frame: TaskFrame | None
    risk_level: str
    plan: TaskGraph | None
    target_objects: list[ObjectInstanceRef]
    planned_actions: list[PlannedAction]
    evidence_bundle: EvidenceBundle | None
    memory_hits: list[MemoryHit]
    observations: list[ToolObservation]
    change_sets: list[ChangeSet]
    action_results: list[ActionResult]
    artifacts: list[ArtifactReference]
    evaluator_feedback: list[QualityVerdict]
    budget: RunBudget
    versions: RuntimeVersions
    next_action: str | None
    termination_reason: str | None
```

### 5.2 事件溯源

系统保存不可变事件、定期 checkpoint 和当前 projection。核心事件包括 goal_perceived、evidence_retrieved、plan_created、plan_revised、tool_completed、tool_failed、quality_evaluated、hitl_resolved、memory_written 和 run_terminated。

系统保存决策摘要、证据、输入输出和版本，不要求保存模型私有 chain-of-thought。

### 5.3 认知状态图

![图 5-1 认知闭环状态机](diagrams/02_cognitive_loop_state.png)

AttentionRouter 的合法动作限定为：clarify、retrieve、plan、execute、evaluate、replan、retry_tool、request_hitl、respond、escalate 和 terminate。

终止状态包括 success、partial_success、needs_input、awaiting_hitl、unsafe_to_continue 和 failed_with_checkpoint。

## 6. 知识与证据设计

### 6.1 知识分类

| 知识类型 | 内容 | 主要机制 | 权威性 |
|---|---|---|---|
| 规范知识 | 标准、法规、政策、规范 | Hybrid Retrieval + Standards Platform | 仅当前有效发布版本 |
| 语义知识 | 术语、指标、字段、本体、血缘 | Semantic Layer + SQL + Graph | 发布结构化状态 |
| 运行事实 | 当前数据、GIS 要素、服务和模型状态 | SQL、PostGIS、ArcPy、API | 实时事实最高 |
| 程序知识 | 治理、分析、制图、恢复流程 | Workflow、Skill、Capability | 需版本和评测 |
| 经验知识 | 历史运行、失败、修订 | Episodic/Procedural Memory | 经验证后作为建议 |
| 参数知识 | 模型通用知识 | Foundation Model | 领域事实优先级最低 |

知识优先级固定为：实时工具事实 > 当前有效标准和规则 > 组织审核知识 > 已验证经验 > 未验证候选 > 模型参数知识。

### 6.2 多源知识架构

![图 6-1 多源知识与 EvidenceBundle 架构](diagrams/03_knowledge_evidence_architecture.png)

### 6.3 EvidenceBundle

```python
class EvidenceBundle(BaseModel):
    query: str
    items: list[EvidenceItem]
    applicable_rules: list[RuleReference]
    semantic_bindings: list[OntologyBinding]
    inference_traces: list[InferenceTrace]
    conflicts: list[EvidenceConflict]
    missing_evidence: list[str]
    coverage_score: float
    sufficient: bool
```

Planner、Evaluator、Report 和 HITL 消费同一个 EvidenceBundle，防止各 Agent 使用不一致的标准版本。

## 7. 数据标准知识设计

### 7.1 三层标准知识

发布标准同时具有：

1. 原文层：用于引用、解释和审计；
2. 结构层：条款、术语、数据元、值域、引用、版本和适用范围；
3. 执行层：schema、值域、QC、空间政策、语义提示、同义词和派生规则。

领域本体不是第四份重复标准，而是对上述结构层和执行层进行统一概念化、关系化和版本化的运行时语义投影。标准仍是权威来源，本体不得脱离标准来源自行创造强制性要求。

### 7.2 StandardKnowledgePack

```python
class StandardKnowledgePack(BaseModel):
    pack_id: str
    standard_id: str
    version: str
    publisher: str
    effective_period: DateRange
    applicable_regions: list[str]
    applicable_business: list[str]
    clauses: list[ClauseReference]
    data_elements: list[DataElementDefinition]
    terms: list[TermDefinition]
    value_domains: list[ValueDomainDefinition]
    executable_rules: list[ExecutableRule]
    ontology_package_refs: list[OntologyPackageRef]
    concept_scheme_refs: list[str]
    constraint_refs: list[str]
    citations: list[CitationReference]
    supersedes: list[str]
    content_hash: str
    approval_status: str
```

RAG 负责查找和解释原文，可执行规则负责合规判断。单独检索到某段文字不能授权生产数据修改。

### 7.3 Hybrid Retrieval

标准检索流程为：身份和 ACL → 时间/地域/业务/版本过滤 → FTS、pgvector、SQL、图谱、PostGIS、API 和 Memory 并行召回 → RRF → rerank → 权限/有效性/冲突复核 → EvidenceBundle。

第一阶段使用 PostgreSQL FTS、trigram、pgvector HNSW 和现有关系/图谱能力；只有规模和精度基准证明必要时再引入 OpenSearch、Qdrant、专用图数据库或领域 reranker。

### 7.4 本体在 Cognitive Runtime 中的定位

本体是 Cognitive Runtime Knowledge Plane 中的受治理语义骨架，用于回答“领域中有哪些对象、它们是什么关系、哪些约束适用、哪些能力能够处理这些对象”。它不是运行时控制器，也不直接执行生产操作。

| 本体层 | 主要对象 | 主要关系或约束 | 运行时消费者 |
|---|---|---|---|
| 领域语义本体 | 数据集、图层、要素、字段、数据元、术语、值域、CRS、质量规则、空间政策 | is-a、broader/narrower、maps-to、has-value-domain、validated-by | Perception、Retriever、Planner、Evaluator |
| 治理与权威本体 | 标准、版本、发布者、适用地域、有效期、强制性、组织和权限范围 | governed-by、applicable-in、effective-during、supersedes、visible-to | Retriever、Evidence Evaluator、HITL |
| 能力与操作本体 | Capability、Specialist、Tool、Artifact、前置条件、输入输出、副作用和回滚 | requires、accepts、produces、verified-by、fallback-to | Planner、Capability Registry、Execution Evaluator |
| Operational Ontology | ObjectType、PropertyType、LinkType、ActionType、FunctionType、InterfaceType、对象状态 | acts-on、changes-state、authorized-by、implemented-by、writes-back | Runtime、Policy、Application、Action Executor、Audit |

数据标准是本体的权威知识来源之一，但不等于完整本体。数据标准主要定义术语、字段、值域和规则；本体还需要表达跨标准映射、运行资产、能力契约、来源、版本、权限和影响关系。

### 7.5 当前本体资产与生产差距

| 当前资产 | 已有能力 | 可复用价值 | 生产化缺口 |
|---|---|---|---|
| `gis_ontology.yaml` + `OntologyReasoner` | 字段等价、派生公式、条件推断 | 可迁移为初始 GIS 概念、别名和规则候选 | 文件级加载；缺少发布审定、ACL、来源和有效期；匹配置信度固定为 0.85；公式通过 `pd.eval` 执行，不得直接接收未审定规则 |
| `mmfe.semantic_ontology.v1` | 角色、对象类型、字段、值域、标准来源、规则、目标和关系的 JSON 契约 | 可作为 OntologyPackage 契约和下游消费契约的原型 | 当前主要面向 MMFE/TWM 产品；缺少统一 Authority Store、跨域命名空间和运行时版本锁定 |
| Standards Platform | 条款、术语、数据元、值域、引用、派生、发布、回滚和影响图 | 可作为权威写模型和审定工作流基础 | 尚未形成统一 ontology concept/relation/constraint/package 契约 |
| XMI 与影响图 | 数据模型导出、派生/引用/相似条款关系 | 支持互操作和影响分析 | XMI 是数据模型交换格式，不等同于领域本体；影响图仍是面向版本的只读聚合 |

因此目标不是新建一套与现有 Standards Platform 平行的数据，而是增加 Ontology Knowledge Compiler，把已发布的结构化标准资产、现有本体原型和运行语义编译为可验证、可版本化、可回滚的 OntologyPackage。

### 7.6 本体生产架构

![图 7-1 领域本体生产架构](diagrams/08_ontology_production_architecture.png)

生产架构采用“一个权威写模型、多个可重建读投影”：

1. PostgreSQL Authority Store 保存命名空间、概念、关系、约束、映射、版本、来源、ACL、审定状态和父版本；
2. Ontology Knowledge Compiler 从 Standards Platform、GIS YAML、MMFE 本体包和 Capability Registry 生成候选并执行冲突检查；
3. 发布后生成不可变 OntologyPackage，使用 content hash、父版本和适用范围锁定；
4. SQL/ltree、FTS、pgvector、RDF/SHACL 或专用图服务均为读投影，不成为第二权威写源；
5. 投影通过 Transactional Outbox 异步构建，使用 package hash 和 projection checkpoint 对账；
6. Cognitive Runtime 在 run 创建时固定 ontology package/version，运行中不得静默切换。

该设计避免 Standards Platform、图数据库、向量库和 RDF 服务之间出现不可审计的双向同步与“多个真相源”。

### 7.7 运行时契约

```python
class OntologyPackageRef(BaseModel):
    namespace: str
    package_id: str
    version: str
    content_hash: str
    effective_period: DateRange
    applicable_regions: list[str]
    knowledge_scopes: set[str]

class OntologyBinding(BaseModel):
    mention: str
    concept_id: str
    relation_path: list[str]
    mapping_type: Literal["exact", "approved_alias", "broader", "narrower", "candidate"]
    confidence: float
    evidence_ids: list[str]
    ontology_package: OntologyPackageRef
    requires_review: bool

class InferenceTrace(BaseModel):
    rule_id: str
    premises: list[str]
    conclusion: str
    evidence_ids: list[str]
    engine: str
    ontology_version: str
```

本体契约必须保留来源和推理路径。Planner 和 Evaluator 不得只接收“字段 A 等于数据元 B”的裸结论，而必须同时获得映射类型、关系路径、版本、证据和是否需要人工确认。

### 7.8 概念、关系与约束模型

概念至少覆盖 Standard、Clause、Term、DataElement、ValueDomain、Dataset、Layer、FeatureType、Field、CRS、QualityRule、SpatialPolicy、Capability、Tool 和 Artifact。关系必须声明方向、基数、传递性、对称性、作用域、来源和有效期。

| 关系类别 | 示例 | 控制要求 |
|---|---|---|
| 分类关系 | is-a、broader-than、narrower-than | 只有明确声明的关系允许传递推理 |
| 等价与映射 | exact-match、close-match、maps-to、alias-of | `exact-match` 必须经审定；LLM 相似度只能生成 candidate |
| 治理关系 | governed-by、supersedes、applicable-in、effective-during | 必须关联标准版本、地域、时间和发布状态 |
| 数据约束 | has-value-domain、has-datatype、uses-crs、validated-by | 约束执行由安全 DSL/规则引擎完成，不由文本推理替代 |
| 能力关系 | requires-capability、accepts、produces、verified-by、fallback-to | 必须与 CapabilityDefinition 的 schema、权限和副作用一致 |

默认不把 `related-to` 当作可执行推理依据，也不因两个概念的 embedding 接近就声明等价。跨标准映射需要方向、强度、适用范围和冲突状态。

### 7.9 编译、审定、发布和回滚

本体生命周期固定为：来源接入 → 候选提取 → 结构校验 → 冲突/循环/孤儿检测 → 领域审定 → 发布版本 → 编译 OntologyPackage → 构建读投影 → shadow 对比 → 激活 → 监控 → 失效或回滚。

- LLM 可以提出概念、别名、映射和关系候选，但不能直接发布权威本体；
- 原始标准、人工维护项和派生项必须隔离，重新编译不得覆盖人工权威内容；
- 派生公式和条件规则采用 allowlist AST 或声明式安全 DSL，禁止执行任意 Python、SQL 或来自检索文档的表达式；
- 每次发布执行 schema、引用完整性、循环、冲突、权限、版本适用性和回归任务验证；
- 删除采用失效标记和替代关系，不直接破坏历史运行所固定的 OntologyPackage；
- 回滚切换 active package pointer，旧包、旧投影和历史 trace 保持可读。

### 7.10 本体如何驱动认知与行动

运行时解析顺序为：稳定 ID/精确编码 → 当前有效标准绑定 → 已审定别名 → 结构化过滤与关系遍历 → 关键词/向量候选 → 交叉编码器或 LLM 辅助消歧 → 规则和 Evidence Evaluator 复核。低置信或冲突映射进入 HITL，不得自动触发 L3/L4 写操作。

- Perception 使用本体把自然语言目标映射为概念、资产和约束；
- Hybrid Retrieval 使用本体路径扩展检索，但原文和实时工具事实仍作为证据；
- Planner 从概念和目标关系推导 Capability，不直接面对全部底层工具；
- Evaluator 使用数据类型、值域、CRS、拓扑、标准适用性和产物关系验证结果；
- Report 输出概念绑定、推理路径、标准版本、证据和冲突，而不是只输出自然语言结论。

### 7.11 生产级技术选型

| 能力 | 第一选择 | 暂不选择或条件选择 | 决策依据 |
|---|---|---|---|
| 权威写模型 | PostgreSQL 关系表 + JSONB + ltree + Transactional Outbox | 图数据库或 RDF Store 作为主写库 | 复用现有 Standards Platform 的事务、版本、ACL、审定和回滚能力，避免双写 |
| 本体契约 | Pydantic v2 + JSON Schema + 不可变 JSON Package | 只依赖 YAML 或 Prompt | 强类型、可校验、可 hash、便于 Worker/MCP/A2A 传递 |
| 检索与候选生成 | PostgreSQL FTS/trigram + pgvector HNSW + SQL/recursive CTE | 首期 OpenSearch/Qdrant | 当前技术栈已具备；专用引擎必须由容量和质量基准证明 |
| 约束执行 | 声明式安全 DSL + schema/SQL/PostGIS 验证 | `eval`、`pd.eval` 或 LLM 自由解释规则 | 生产规则必须确定、可审计、可测试并限制操作符 |
| 形式语义 | Stage 2 引入 SKOS、SHACL、PROV-O、必要的 GeoSPARQL 词汇；RDFLib + pySHACL 用于构建/验证 | Stage 1 直接上线全套 OWL | 先解决业务契约和治理，再增加标准互操作；避免推理范围失控 |
| 专用语义查询 | Stage 3 条件引入 Apache Jena Fuseki/TDB2 读投影 | 将 Fuseki 设为首期强依赖 | 开源、SPARQL 1.1 和 RDF 生态成熟；只有出现跨域 SPARQL、外部互操作或 PostgreSQL 图查询不达标时引入 |
| 属性图 | Neo4j/Apache AGE 仅作为独立基准候选 | 同时部署 RDF Store 和属性图作为双主库 | 只有运营影响路径、血缘或多跳图算法成为主负载且基准胜出时采用；仍保持只读投影 |
| 逻辑推理 | 确定性规则 + 有界关系遍历；Stage 2 可评估 OWL 2 RL 子集离线物化 | 在线 OWL 2 DL 全量推理 | 保证终止、延迟可控和推理可解释 |

### 7.12 分阶段生产落地

| 阶段 | 技术范围 | 主要交付 | 生产验收门 | 进入下一阶段的触发条件 |
|---|---|---|---|---|
| Stage 1：受治理轻量本体 | PostgreSQL Authority Store、Pydantic/JSON Package、ltree/recursive CTE、FTS/trigram/pgvector、安全 DSL、Outbox 投影 | 统一 namespace/concept/relation/constraint/mapping/version/package 契约；导入 Standards、GIS YAML 和 MMFE；OntologyResolver v1 | active package 唯一；版本/地域/ACL 适用性 100%；未授权返回 0；package hash 与投影一致；历史 run 可按固定版本重放；任意公式执行为 0 | 业务概念和标准映射稳定；代表性治理任务证明本体能改进映射、规划或评价 |
| Stage 2：形式化与互操作 | SKOS 概念体系、SHACL Shapes、PROV-O 来源、必要的 GeoSPARQL 词汇、JSON-LD/Turtle 导出、RDFLib + pySHACL 构建验证 | Standards→RDF/SHACL 编译器、shape registry、外部本体映射、OWL 2 RL 子集离线可行性验证 | 每个发布包通过 SHACL；RDF 与 JSON Package 双向一致；外部 URI 和本地概念映射可追溯；推理结果有 trace | 出现跨系统 RDF/语义互操作、外部 SPARQL 消费或正式语义校验需求 |
| Stage 3：专用语义服务 | Apache Jena Fuseki/TDB2 作为只读 RDF 投影；SPARQL Adapter；蓝绿索引、增量投影和对账 | 独立语义查询服务、服务级缓存、projection lag/一致性监控、故障降级回 PostgreSQL/Package | 在代表性查询集上满足 owner 确认的 p95/p99；projection hash/版本一致；服务故障不阻断安全降级；无双主写入 | PostgreSQL 无法满足已确认 SLO，或跨域 SPARQL/联邦查询成为稳定生产需求 |
| Stage 4：联邦与受控演化 | 多组织 namespace、签名 OntologyPackage、映射注册表、MCP/A2A 交换、Ontology Candidate + Evolution Governor | 跨组织本体协商、候选评测、shadow/canary、影响分析和回滚 | 外部包签名/来源可验证；映射冲突不静默合并；L0-L1 低风险候选受控晋级；权威概念、等价关系和规则仍需 HITL | 多组织共享和持续演化成为已验证业务需求 |

Stage 3 不是必经阶段。如果 Stage 1/2 的 PostgreSQL 和不可变 OntologyPackage 已满足查询、互操作和隔离要求，应继续保持较简单的部署。专用图数据库、RDF Store、OpenSearch 和专用向量库均采用基准触发，而不是按架构时髦程度引入。

### 7.13 本体安全、评测与可观测性

- ACL 在概念解析和关系遍历之前执行，缓存键包含 tenant、user、role、knowledge scope、namespace 和 ontology version；
- 检索文档中的“定义”“规则”只能成为候选证据，不能覆盖已发布本体或运行策略；
- 监控至少包含未识别概念率、候选映射分布、冲突率、HITL 修订率、错误等价率、关系遍历深度、projection lag、package/hash 不一致和回滚次数；
- 评测集同时覆盖精确映射、近义但不等价、过期标准、地域不适用、跨租户、循环关系、孤儿概念、冲突约束、错误规则和投影滞后；
- 映射 precision/recall、未知概念拒绝率和查询延迟的正式阈值为 `needs-owner-input`，必须由 Stage 0 真实/脱敏任务基线确定；
- 版本适用错误、未授权概念/关系返回、未审定规则执行和 projection hash 静默不一致的生产容忍度均为 0。

### 7.14 Operational Ontology 与对象行动闭环

![图 7-2 Operational Ontology 与对象行动闭环](diagrams/09_operational_ontology_action_loop.png)

领域本体解决“对象是什么、关系和规则是什么”；Operational Ontology 进一步解决“真实业务对象当前处于什么状态、谁能执行什么 Action、Action 如何调用 Capability 并改变状态”。它是 Standards Knowledge Brain 与 Execution Plane 之间的操作语义层。

| 类型 | 责任 | 关键约束 |
|---|---|---|
| ObjectTypeDefinition | 定义数据集版本、标准版本、字段映射、质量问题、治理任务、审批任务、治理产物等业务对象 | 稳定 ID、属性 schema、link schema、状态机、来源和版本 |
| PropertyTypeDefinition | 定义对象属性及其敏感等级、值域、可见性和可编辑性 | 属性级 ACL、数据类型、nullable、来源、派生方式 |
| LinkTypeDefinition | 定义对象间有方向、有基数和有权限的关系 | 遍历权限、完整性、级联策略、有效期 |
| ActionTypeDefinition | 定义针对对象可执行的业务动作 | 参数、前置条件、证据、权限、副作用、HITL、幂等、补偿、Evaluator |
| FunctionTypeDefinition | 定义确定性计算、查询和验证逻辑 | 输入输出 schema、版本、纯函数/副作用标记、超时和错误 |
| InterfaceTypeDefinition | 为跨域 ObjectType 提供稳定行为契约 | 兼容性、实现列表、版本和废弃策略 |
| ObjectInstanceRef | 在运行时引用真实对象及固定版本 | tenant、object type、object id、version/etag、可见范围 |
| ChangeSet | 描述执行前预期发生的状态变化 | before/after、lineage、风险、幂等键、补偿和审批 |
| ActionResult | 描述工具实际执行和写回结果 | observation、artifact、actual changes、object refs、failure 和 audit event |

Operational Ontology 不复制业务事实。对象实例仍引用 PostgreSQL/PostGIS、Standards Platform、对象存储、ArcPy 产物或 TWM 状态；Ontology 保存类型、行为、安全和稳定引用语义。

### 7.15 Object-Action-Capability 统一契约

ActionType、CapabilityDefinition 和 Specialist Tool Manifest 不得分别维护互相漂移的动作描述。目标绑定关系为：

```text
ActionTypeDefinition
    → implemented_by CapabilityDefinition(version)
    → executed_by Specialist + Tool Manifest(version)
    → verified_by Evaluator(version)
    → writes ChangeSet / ActionResult
```

```python
class ActionTypeDefinition(BaseModel):
    action_type_id: str
    version: str
    target_object_types: list[str]
    parameter_schema: dict
    preconditions: list[PolicyExpression]
    required_evidence: list[str]
    required_permissions: set[str]
    side_effect_level: Literal["L0", "L1", "L2", "L3", "L4"]
    capability_ref: VersionedCapabilityRef
    expected_change_schema: dict
    approval_policy: ApprovalPolicy
    idempotency_policy: IdempotencyPolicy
    compensation_capability: VersionedCapabilityRef | None
    evaluator_ref: VersionedEvaluatorRef
```

Planner 只能选择已激活、版本兼容且对目标对象适用的 ActionType；Capability Registry 只能执行 ActionType 固定的参数、权限和副作用边界。Tool Manifest 可以更换底层 SQL、PostGIS、ArcPy 或 MCP 实现，但不能扩大 Action 权限和状态转换范围。

### 7.16 动态安全

Policy Decision 输入至少包含 RuntimeIdentity、ObjectInstanceRef、PropertyType、LinkType、ActionType、参数、证据、风险、目标环境和当前对象 etag。授权粒度覆盖：

- 对象是否可见；
- 哪些属性可见、可编辑或必须脱敏；
- 哪些关系允许遍历；
- 哪些 Action 可以发现、规划、审批和执行；
- ActionResult、产物和审计记录由谁可见；
- Agent 生成的上下文是否允许包含相关对象和属性。

授权由确定性 Policy Engine/Adapter 输出 allow、deny 或 requires-approval；LLM 不参与授权决策。是否采用 OPA/Cedar 或继续使用 PostgreSQL/代码策略为 `needs-owner-input`，在 Runtime Kernel 安全基准后通过 ADR 决定。

### 7.17 Typed Consumption Layer

目标建立 OSDK-like 统一消费层，从同一 Object/Action/Capability 契约生成或维护：

- Python SDK；
- TypeScript SDK；
- REST/OpenAPI schema；
- MCP/A2A tool schema；
- 前端 Action 参数表单和审批视图；
- Evaluator 输入输出和错误类型。

SDK 不绕过 RuntimePolicy。UI、外部应用、MCP、A2A 和自动化任务使用同一身份、对象、Action、ChangeSet、ActionResult 和错误语义。生成器版本必须固定并通过契约兼容性测试。

### 7.18 Operational Ontology 发布生命周期

Operational Ontology 采用独立 dev/staging/prod namespace：设计变更 → ontology/action diff → 影响分析 → schema/权限/兼容性回归 → review → shadow → activate → monitor → rollback。

- 删除 Property/Link/Action 前必须证明无活跃 SDK、TaskGraph、UI、MCP 或历史重放依赖；
- Action 参数和结果 schema 默认遵循向后兼容，破坏性变更必须新建 major version；
- 对象状态迁移与 Action 发布分开控制，不能用本体发布隐式改写生产对象；
- Action shadow 默认不产生副作用；canary 必须限定对象范围、用户范围和最大变更预算；
- ontology/action diff、影响对象、依赖消费者和 rollback version 全部进入发布报告。

### 7.19 重型本体的条件目标架构

![图 7-3 重型本体生产平台架构](diagrams/10_heavy_ontology_platform_architecture.png)

重型本体不是图数据库扩容，而是企业级 Semantic + Operational Ontology Platform。它把 Ontology Studio/Governance、Canonical Model Registry、RDF/OWL/SHACL、Operational Object Graph、Semantic Query Gateway、Dynamic Policy Engine、Object & Action Service、Ontology CI/CD、事件传播和生产运维组合为统一平台。

该平台是**条件目标架构**，不是当前实施基线。当前仓库未实现专用 RDF/SHACL/Fuseki、OPA/Cedar、Kafka/Redpanda Ontology Platform。[证据：F040-F042] 在轻量 Stage 1/2 满足业务、互操作和 SLO 时，不进入重型阶段；只有明确准入门通过后，才以独立平台项目启动。

### 7.20 控制面与数据面

| 平面 | 核心职责 | 不可越过的边界 |
|---|---|---|
| 设计与治理控制面 | namespace、URI、概念、关系、Shape、Action、映射、评审和影响分析 | Agent/LLM 只能提交候选，不能独立发布权威语义 |
| 编译与发布控制面 | lint、SHACL、兼容性、安全回归、签名、shadow、activate、rollback | 未通过 competency query、安全和兼容门不得激活 |
| 摄取与传播数据面 | Standards/XMI/JSON-LD/业务元数据摄取，Outbox、Kafka/Redpanda、DLQ 和重放 | 事件不成为新的业务真值；消费者必须幂等 |
| 语义与运营知识面 | RDF/OWL/SHACL、Operational Object Graph、Search/Vector 投影 | 全部为版本化、可重建读模型 |
| 查询与安全运行面 | SQL/SPARQL/Graph/Search 联邦、EvidenceBundle、动态策略、查询预算 | 权限必须下推并在结果返回前二次判定 |
| 对象与行动执行面 | Object/Action/Function/Interface 服务、SDK、ChangeSet、ActionResult 和写回 | 真实状态变更仍经 RuntimePolicy、Capability 和业务事务执行 |

### 7.21 形式语义与推理平台

重型路线采用 SKOS 表达术语和审定映射，SHACL 表达发布和运行约束，PROV-O 表达来源与派生，GeoSPARQL 表达必要空间语义，OWL-Time 表达适用时间；OWL 2 推理优先限制为经过基准验证的 OWL 2 RL 子集。

在线运行默认使用预物化结论、有界关系遍历、查询预算和显式推理 trace。OWL 2 DL 全量在线推理不进入默认架构。大规模几何、拓扑、栅格、轨迹和模型推演继续由 PostGIS、ArcPy、对象存储和 TWM 处理；RDF 保存语义、适用性、对象引用和必要简化几何，不复制全国级空间事实。

### 7.22 多存储一致性与投影对账

重型路线仍遵循“一个权威写入口、多个可重建读投影”：

1. PostgreSQL/PostGIS 保存业务与事务事实，Standards Platform 保存标准审定和发布权威，Canonical Model Registry 保存受治理的本体模型与发布元数据；
2. 权威事务写 Transactional Outbox，事件携带 tenant、namespace、package version、content hash、sequence 和 schema version；
3. Kafka/Redpanda 条件承担变更重放、分区顺序、DLQ 和多投影传播；
4. RDF、Operational Graph、Search 和 Vector 消费者幂等构建投影；
5. Reconciler 比较 authority hash、projection hash、checkpoint 和 lag，不一致时阻断新版本激活、降级到固定 Package 并重建；
6. 历史 Run 始终锁定创建时的 Ontology/Object/Action 版本。

该设计不使用跨数据库双向同步或分布式强事务制造“多个真相源”。

### 7.23 Semantic Query Gateway 与动态策略联邦

Semantic Query Gateway 接收 RuntimeIdentity、租户、ontology version、时间/地域范围、业务目的、查询预算和输出 schema，生成 SQL、SPARQL、Graph、Search 或 Spatial 子查询，并保留来源、版本、冲突和缺失证据。

LLM 可生成候选查询或辅助消歧，但查询必须经过 schema、allowlist、复杂度、超时、结果规模和权限校验。Dynamic Policy Engine 对概念、对象、属性、关系、Action、结果和 AI context 分别输出 allow、deny 或 requires-approval。OPA、Cedar 或现有 Policy Adapter 的最终选择为 `needs-owner-input`，由对象级安全基准和 ADR 决定。

### 7.24 重型生产部署与运维

生产部署至少区分 dev/staging/prod namespace，包含无状态 Model Registry、Query Gateway、Object & Action Service，RDF/SHACL 集群或托管服务，事件流、Schema Registry、DLQ、投影 Worker、PostgreSQL/PostGIS HA、OTel、审计归档、KMS/Secrets、包签名和 mTLS/NetworkPolicy。

平台必须执行 backup/restore、projection rebuild、ontology rollback 和 policy rollback 演练。具体副本数、吞吐、p95/p99、RPO/RTO、跨地域拓扑和保留期为 `needs-owner-input`，由 Heavy H0 容量模型确定。

### 7.25 重型平台技术候选与 ADR 门

| 能力 | 候选 | ADR/PoC 决策门 |
|---|---|---|
| 企业语义平台 | Stardog、GraphDB Enterprise、TopBraid EDG、Neptune、Anzo | 厂商支持、治理、联邦、安全、SLA、迁移和三年 TCO |
| 开源 RDF 服务 | Apache Jena Fuseki/TDB2、Eclipse RDF4J | SPARQL/推理、HA、备份、升级、运维能力和性能 |
| 构建与验证 | RDFLib + pySHACL | Stage 2 CI/离线验证；不单独承担大型在线服务 |
| 事件流 | Kafka、Redpanda | 现有运维能力、吞吐、重放、生态和总成本 |
| 动态策略 | OPA、Cedar、现有 Policy Adapter | 对象/属性/关系/Action 表达力、p99、调试和故障降级 |
| Operational Graph | PostgreSQL/ltree；Neo4j/AGE 条件候选 | 多跳/图算法代表性基准和运维成本 |

技术选型采用相同数据、competency questions、安全集、故障注入和恢复演练进行 PoC。供应商名称不等于最终选择，具体产品和版本为 `needs-owner-input`。

### 7.26 组织门与准入标准

重型平台需要领域/标准 owner、Ontology Engineer、Platform Engineer、Security Engineer、GIS/Data Engineer、SRE 和业务应用 owner 的长期责任。人数、预算、值班和采购为 `needs-owner-input`；没有可持续团队即视为准入失败。

建议至少两项稳定成立并通过 Heavy H0 证明后再启动：跨组织 RDF/SPARQL 互操作；复杂 SHACL/OWL 2 RL 成为审计刚需；多个独立应用依赖统一 Object/Action SDK；对象/属性/关系/Action 动态安全超过轻量策略承载能力；Ontology 需要独立发布组织；轻量路线在已确认 SLO 上失败。Heavy H3 及以后不是必经阶段。

## 8. 规划与执行设计

### 8.1 TaskFrame

Perception 输出目标、数据资产、期望产物、约束、标准范围、空间/时间范围、歧义、缺失输入、风险等级和成功标准。缺少标准版本、目标数据或写权限时必须先澄清。

### 8.2 TaskGraph

```python
class TaskNode(BaseModel):
    node_id: str
    goal: str
    capability: str
    action_type_ref: str | None
    target_object_refs: list[ObjectInstanceRef]
    dependencies: list[str]
    input_refs: list[str]
    preconditions: list[str]
    expected_output_schema: str
    verification_rules: list[str]
    side_effect_level: str
    retry_policy: RetryPolicy
    fallback_capabilities: list[str]
```

计划执行前验证 DAG、Capability 是否存在、权限、证据、输入、预算、副作用和输出契约。

### 8.3 Capability Registry

Planner 选择 Capability，而不是面对全部底层工具。Capability 定义输入输出 schema、权限、副作用、工具集合、specialist、成本、超时、重试和 Evaluator。

当任务涉及运营对象或状态变更时，Planner 先选择 ActionType，再通过固定绑定解析 Capability。只读分析仍可直接选择 L0/L1 Capability，但必须产生版本化 observation 和 object/artifact references。

FrontDoor 只保留少量元能力；普通 Specialist 默认不超过约 10 个主要工具，复杂工具家族使用二级动态加载。

### 8.4 工具副作用等级

| 等级 | 示例 | 策略 |
|---|---|---|
| L0 | 检索、查询、描述 | 自动执行 |
| L1 | 只读分析、临时产物 | 自动执行并审计 |
| L2 | 新建表、数据版本或产物 | 策略检查，可批量审批 |
| L3 | 修改生产数据、发布标准 | 强制 HITL |
| L4 | 删除、覆盖、对外正式发布 | 双重确认和回滚方案 |

## 9. 数据标准驱动治理时序

![图 9-1 数据标准驱动治理时序](diagrams/04_standard_governance_sequence.png)

### 9.1 输入

- 用户治理目标；
- 目标数据资产；
- 标准或业务范围；
- 允许的副作用等级；
- 期望产物。

### 9.2 执行链

数据画像 → 确定有效标准 → 字段与数据元映射 → 差距分析 → 治理方案 → HITL → 创建治理后数据版本 → 标准/QC/空间规则验证 → 证据报告和血缘。

Operational Ontology 视角下，该链路操作 DatasetVersion、StandardVersion、FieldMapping、QualityIssue、RemediationPlan、ApprovalTask 和 GovernedDataset 等对象；每个写步骤使用 ActionType、ChangeSet 和 ActionResult 记录预期变化、实际变化和审计事件。

### 9.3 输出产物

| 产物 | 说明 |
|---|---|
| governed_dataset | 不覆盖原始数据的治理后版本 |
| field_mapping | 实际字段与标准数据元映射 |
| gap_matrix | 字段、类型、值域和规则差距 |
| remediation_plan | 可执行治理方案 |
| quality_report | 数据质量和问题结果 |
| rule_execution_report | 标准、QC 和空间规则执行结果 |
| evidence_manifest | 标准、条款和工具事实证据 |
| lineage_manifest | 输入、转换和输出血缘 |
| run_trace | 目标、计划、工具、评价和终止路径 |

## 10. 评价、恢复与 HITL

### 10.1 五层评价

1. Contract Validator：schema、字段、文件和产物存在性；
2. Evidence Evaluator：证据、引用、版本和覆盖；
3. Domain Rule Evaluator：标准、值域、CRS、拓扑和空间政策；
4. Execution Evaluator：工具轨迹、参数、单位和输入输出一致性；
5. Outcome Evaluator：成功标准和产物可用性。

### 10.2 QualityVerdict

```python
class QualityVerdict(BaseModel):
    decision: Literal[
        "pass", "revise", "retrieve", "replan",
        "retry_tool", "request_hitl", "escalate"
    ]
    score: float
    issues: list[str]
    evidence_gaps: list[str]
    failed_node_ids: list[str]
    next_action: str
    confidence_profile: dict
```

### 10.3 置信度

置信度来自检索覆盖、来源权威性、版本有效性、schema、规则通过率、工具成功率、交叉验证、历史能力成功率、未知输入比例和未解决冲突。模型自报概率不作为校准置信度。

### 10.4 恢复策略

| 失败 | 处理 |
|---|---|
| 缺少有效标准 | 扩大检索或请求指定标准 |
| 标准冲突 | 输出冲突报告并进入 HITL |
| 映射低置信 | 请求人工确认 |
| 工具参数错误 | 在预算内修正并重试 |
| 工具持续失败 | 切换注册的 fallback capability |
| 数据质量阻断 | 停止下游并生成前置治理任务 |
| 计划依赖错误 | 只重规划受影响子图 |
| 连续两轮无改进 | 判定停滞并升级或终止 |
| 权限不足 | 请求授权，不允许绕过策略 |
| 预算耗尽 | 返回已完成工作和 checkpoint |

## 11. 记忆设计

| 记忆类型 | 内容 | 存储 |
|---|---|---|
| Working | 当前目标、计划、证据和预算 | Workspace/Event Store |
| Episodic | 某次任务和结果 | PostgreSQL 结构化事件 |
| Procedural | 成功/失败工具链 | Workflow/Skill Registry |
| Semantic Profile | 稳定用户和组织偏好 | 结构化 Profile + 可选向量索引 |

长期写入前经过 Memory Write Gate，检查重要性、重复、证据、冲突、敏感信息、可见范围、过期时间和是否需要人工确认。原始事件为审计源，结构化记忆、embedding 和压缩摘要均为可重建派生物。

## 12. 受控自我进化设计

![图 12-1 受控自我进化流水线](diagrams/05_self_evolution_pipeline.png)

### 12.1 进化对象

| 风险级别 | 对象 | 晋级方式 |
|---|---|---|
| L0 | 索引、新文档、失效标记 | ingestion 和 ACL 检查后自动 |
| L1 | 经验、候选别名、检索阈值、非权威 related-to 关系 | 候选评测后 canary |
| L2 | Prompt、工具描述、路由、Workflow、Skill、跨标准 close-match 映射 | 回归、shadow、canary；必要时领域复核 |
| L3 | 权威概念、exact-match、本体约束、可执行规则、Evaluator、代码 | 权威依据和 HITL |
| L4 | 模型权重、权限策略 | 独立训练/安全流程和 HITL |

### 12.2 进化证据

进化只能由用户负反馈、Evaluator 失败、工具失败、HITL 修订、新标准、成本异常或已确认业务结果触发。LLM 认为“可以改进”本身不构成生产变更依据。

### 12.3 评测集合

每个候选都执行不可变 Regression Set、触发失败的 Replay Set、未见 Holdout Set，以及安全和权限否决集。候选生成器不得评价自己的候选。

### 12.4 Evolution Governor

Governor 只能输出 reject、revise、shadow、canary 或 promote，并记录通过门、失败门、指标变化、风险等级、HITL 要求和回滚版本。任何权限、安全或核心正确率回归都阻断晋级。

## 13. 核心逻辑数据设计

![图 13-1 Cognitive Runtime 核心逻辑数据模型](diagrams/07_core_data_model.png)

### 13.1 目标实体

| 实体 | 责任 |
|---|---|
| agent_brain_run | 一次认知运行的身份、目标、状态和版本 |
| agent_brain_event | 不可变运行事件 |
| agent_brain_checkpoint | 可恢复状态快照 |
| agent_evidence_item | 证据、来源、权限、有效期和验证状态 |
| agent_memory_item | 结构化长期记忆 |
| agent_evolution_event | 可进化问题的证据记录 |
| agent_evolution_candidate | 候选版本及父版本差异 |
| agent_candidate_eval | 候选评测结果 |
| agent_promotion | shadow、canary、晋级和回滚记录 |
| agent_runtime_version | Prompt、模型、工具、知识、规则和 Evaluator 组合版本 |
| ontology_namespace | 领域/组织命名空间、所有者和隔离范围 |
| ontology_version | 本体版本、父版本、发布状态、适用范围和 content hash |
| ontology_concept | 概念、稳定 ID、类型、标签、来源和有效期 |
| ontology_relation | 有方向、有类型、有来源和作用域的概念关系 |
| ontology_constraint | 数据类型、值域、CRS、基数、规则和安全 DSL 引用 |
| ontology_mapping | 跨标准/跨组织映射、强度、方向、证据和审定状态 |
| ontology_package | 不可变运行时本体包及投影 checkpoint |
| ontology_candidate | 概念、别名、关系、映射或约束的演化候选 |
| ontology_validation_result | schema、SHACL、冲突、回归、安全和权限验证结果 |
| operational_object_type | ObjectType、PropertyType、LinkType 和对象状态机定义 |
| operational_action_type | ActionType、参数、前置条件、权限、副作用和绑定版本 |
| operational_interface_type | 跨 ObjectType 的稳定行为接口和实现关系 |
| operational_object_ref | 对真实对象、版本/etag 和权威数据源的稳定引用 |
| operational_change_set | Action 执行前的预期变更、风险、审批、幂等和补偿 |
| operational_action_result | 工具执行后的实际变更、产物、失败和审计引用 |
| policy_decision_audit | 对象/属性/关系/Action/结果授权决定及策略版本 |

上述实体是目标逻辑模型。最终字段、分区、索引、保留期和迁移策略为 `needs-owner-input`。Runtime Kernel 子项目先确定 run/event/version 契约；Standards Knowledge Brain 子项目再确定 ontology_* 物理 DDL，不允许在本轮文档阶段直接改动现有迁移。

## 14. 关键接口设计

### 14.1 CognitiveRuntime

```python
class CognitiveRuntime:
    async def run(
        self,
        request: AgentRequest,
        identity: RuntimeIdentity,
        policy: RuntimePolicy,
    ) -> AgentRunResult:
        ...
```

### 14.2 Retriever

```python
class Retriever(Protocol):
    def retrieve(
        self,
        query: QueryIntent,
        identity: RuntimeIdentity,
        filters: RetrievalFilters,
    ) -> list[EvidenceItem]: ...
```

### 14.3 OntologyCompiler

```python
class OntologyCompiler(Protocol):
    def compile(
        self,
        source_refs: list[KnowledgeSourceRef],
        identity: RuntimeIdentity,
        target_namespace: str,
        parent_version: str | None,
    ) -> OntologyCandidatePackage: ...
```

Compiler 只生成 candidate。发布、激活和回滚由独立治理服务执行，Compiler 不拥有审批权限。

### 14.4 OntologyResolver

```python
class OntologyResolver(Protocol):
    def resolve(
        self,
        mentions: list[str],
        identity: RuntimeIdentity,
        filters: OntologyFilters,
        package_refs: list[OntologyPackageRef],
    ) -> list[OntologyBinding]: ...
```

Resolver 必须执行 namespace、ACL、版本、地域、时间和业务范围过滤，并返回可解释关系路径、证据和冲突，不允许只返回一个相似度最高的 concept id。

### 14.5 CapabilityDefinition

Capability 定义版本、任务类型、输入输出 schema、权限、副作用、工具、Specialist、成本、超时、重试和 Evaluator。现有 Toolset、Skill、Operator、AgentTool 和 MCP Tool 通过 Adapter 注册。

### 14.6 ActionExecutor

```python
class ActionExecutor(Protocol):
    async def execute(
        self,
        action: PlannedAction,
        identity: RuntimeIdentity,
        expected_change: ChangeSet,
        policy: RuntimePolicy,
    ) -> ActionResult: ...
```

ActionExecutor 先校验对象 etag、ActionType/Capability/Tool 版本、权限、证据、审批、幂等和预算，再调用 Specialist。实际变更超出 ChangeSet、对象版本冲突或结果 schema 不合格时不得静默写回。

## 15. 部署与技术选型

![图 15-1 Cognitive Runtime 部署演进](diagrams/06_deployment_evolution.png)

### 15.1 第一阶段技术栈

| 能力 | 选型 |
|---|---|
| Agent SDK | 继续使用 Google ADK |
| 契约 | Pydantic v2 |
| 状态和真值 | PostgreSQL |
| 本体权威写模型 | PostgreSQL + JSONB + ltree |
| 本体运行契约 | Pydantic v2 + JSON Schema + immutable package |
| 本体约束 | Stage 1 安全 DSL；Stage 2 SHACL/pySHACL |
| 本体互操作 | Stage 2 SKOS/PROV-O/JSON-LD/RDF；Stage 3 条件引入 Fuseki/TDB2 |
| Operational Ontology | Object/Action/Function/Interface typed contracts + PostgreSQL authority |
| 动态策略 | 首期 Policy Adapter；OPA/Cedar 是否引入需 ADR 和安全基准 |
| 统一消费层 | Pydantic/JSON Schema → Python/TypeScript/OpenAPI/MCP/A2A contracts |
| 向量检索 | pgvector HNSW |
| 关键词检索 | PostgreSQL FTS + trigram |
| 融合 | RRF |
| 缓存和租约 | Redis，可选 |
| 事件分发 | Transactional Outbox |
| 长任务 | 复用 Task Queue/Workflow Engine |
| 产物 | 现有对象存储/文件存储 |
| Trace | OTel + Runtime Event Store |
| 模型 | ModelGateway 分层路由 |

### 15.2 重型本体条件技术栈

重型路线在准入门通过后才增加 Canonical Model Registry、Ontology CI/CD、RDF/OWL/SHACL 服务、Semantic Query Gateway、Dynamic Policy Engine、Object & Action Service、Kafka/Redpanda、Projection Reconciler 和 SDK Generator。RDF 平台从 Fuseki/RDF4J 与企业候选的受控 PoC 中选择；策略引擎从 OPA/Cedar/现有 Adapter 中选择。所有产品、版本、SLO 和采购结论均为 `needs-owner-input`。

### 15.3 部署演进原则

先采用模块化单体，随后只将索引、记忆压缩、候选评测和高成本 ArcPy/TWM/模型能力拆为 Worker 或服务，最终通过 MCP/A2A 接入跨组织 Specialist。

本体部署遵循相同原则：Authority Store 和编译治理首先位于模块化单体；RDF/SHACL 构建可作为离线 Worker；只有 Stage 3 进入门通过后才部署独立 Fuseki/TDB2 读服务。任何专用语义服务故障时，Runtime 必须能够降级到固定 OntologyPackage 和 PostgreSQL 查询，而不是跳过语义和权限检查。

## 16. 安全、可观测性与性能

### 16.1 安全要求

- 检索前执行 ACL；
- 本体解析和关系遍历前执行 namespace/ACL/版本/适用范围过滤；
- 对象、属性、关系、Action 和 ActionResult 使用同一动态策略决定；
- tenant/user/role/knowledge scope 进入缓存键；
- 检索文档作为不可信数据，禁止其中指令覆盖系统策略；
- 工具参数经过 schema 和策略校验；
- L3/L4 操作具有 HITL、幂等键、checkpoint 和回滚；
- 写操作必须先形成 ChangeSet，并在写回前比较对象 etag 和实际 ActionResult；
- evolution candidate 在隔离环境运行；
- 本体规则不得执行任意 Python、SQL、shell 或检索文档中的指令；
- 模型不得自行提升权限。

### 16.2 可观测性

Trace 至少包含 route decision、plan revision、evidence、ontology package/version、object/action/capability versions、policy decision、ChangeSet、ActionResult、concept binding、inference trace、memory hit、tool schema/version、guardrail、quality verdict、成本、延迟、产物和最终业务结果。

### 16.3 性能与容量

采用模型分层、fast path、检索缓存、动态工具加载和预算控制。正式并发、p95/p99、RPO/RTO 和保留期为 `needs-owner-input`，不在本版设计中虚构。

## 17. 分阶段实施路线

| 阶段 | 内容 | 退出门 |
|---|---|---|
| Phase 0 | 50-100 个治理基准、版本冻结、安全集 | 能区分检索、理解、规划、工具和结果错误 |
| Phase 1 | RuntimeIdentity、RunnerFactory、Workspace、事件、Router、QualityVerdict | 统一入口、真实回跳、checkpoint、零租户泄露 |
| Phase 2 | StandardKnowledgePack、Domain/Operational Ontology Authority Store、Compiler、Package、Resolver、Object/Action/Function/Interface contracts、Hybrid Retrieval、EvidenceBundle | 版本/地域/权限有效，概念映射、本体包、对象/行动 schema 和动态安全一致性达标 |
| Phase 3 | ActionType↔Capability↔Tool binding、typed SDK、治理对象/行动闭环、ChangeSet/ActionResult、产物、血缘、HITL | 至少一个真实/脱敏数据通过对象发现、Action 规划、审批、执行、评价、写回和回滚 |
| Phase 4 | Memory Write Gate、Episodic/Procedural Memory | 经验能影响计划，错误经验可纠正删除 |
| Phase 5 | EvolutionEvent、Candidate、Replay/Holdout | 自动生成并离线验证候选 |
| Phase 6 | Shadow、Canary、Governor、Rollback | L0-L2 低风险受控自动晋级 |
| Phase 7 | NL2SQL、ArcPy、遥感、DRL、TWM、联邦 Agent | 复用同一 Runtime，不复制大脑内核 |

重型本体采用独立条件路线：H0 业务/架构准入 → H1 Governance & Model Registry → H2 RDF/SHACL build/validation → H3 Semantic Query Gateway → H4 Operational Object/Action Service → H5 多投影对账 → H6 HA/DR/可观测性/SDK/发布治理 → H7 跨组织联邦。H3 以后只有在轻量 Stage 1/2 无法满足已确认需求时才启动，不与 Runtime Kernel 首个实施计划混合。

## 18. 验收指标

### 18.1 Runtime

- 所有入口使用同一 mandatory RuntimePolicy；
- 所有状态转移和模块输出强类型；
- revise/replan 形成真实执行；
- checkpoint 可恢复；
- trace 可重建目标、计划、证据、工具、评价和终止原因；
- 跨租户上下文、记忆和工具泄露为零。

### 18.2 检索

| 指标 | 初始门槛 |
|---|---:|
| 正确标准 Recall@10 | ≥90% |
| 正确条款 Recall@10 | ≥85% |
| 引用支持结论准确率 | ≥95% |
| 标准版本有效性 | 100% |
| 未授权召回 | 0 |
| 未标注使用失效标准 | 0 |

### 18.3 治理与进化

正式结论必须追溯到规则、条款或实时工具事实；所有产物具有 schema、hash、版本和 lineage。候选必须具有来源事件和父版本，安全与权限回归为零，rollback 在晋级前完成演练。

### 18.4 本体

| 指标 | 生产门 |
|---|---|
| OntologyPackage 版本、适用范围和 hash 一致性 | 100% |
| 未授权概念、关系或映射返回 | 0 |
| 未审定规则或任意表达式执行 | 0 |
| 当前有效标准绑定正确性 | 100% |
| 推理结论可追溯到关系、规则和证据 | 100% |
| Projection 与 Authority Store 静默不一致 | 0 |
| 概念映射 precision/recall、未知拒绝率和查询延迟 | `needs-owner-input`：Stage 0 基线后由 owner 批准 |

### 18.5 Operational Ontology 与 Action

- 每个生产 Action 均绑定固定 ObjectType、ActionType、Capability、Tool Manifest、Policy 和 Evaluator 版本；
- 未授权对象/属性/关系/Action/ActionResult 返回为 0；
- 写操作均具有 ChangeSet、幂等键、对象 etag、审批记录和实际 ActionResult；
- Action 实际变更超出 ChangeSet 时自动阻断写回或进入补偿/HITL；
- SDK、REST、MCP、A2A 和 UI 对相同 Action 的 schema 与错误语义一致；
- breaking ontology/action change 未完成影响分析和 major version 发布的生产容忍度为 0。

### 18.6 重型本体条件路线

- H0 必须用 competency questions、容量模型、SLO 候选和 TCO 证明轻量路线存在稳定缺口；
- Model Registry、RDF、Operational Graph、Search 和 Vector 不得形成多个可写真值源；
- 每次发布通过 SHACL、兼容性、安全、competency query、推理一致性、签名和 rollback 门；
- projection hash/checkpoint 静默不一致、跨租户查询泄露和未授权 Action 的生产容忍度为 0；
- RDF/Query Gateway/Policy 故障时可降级到固定 OntologyPackage 和安全只读能力；
- backup restore、projection rebuild、ontology rollback 和 policy rollback 在投产前完成演练；
- 正式 SLO、RPO/RTO、容量和成本阈值均由 H0/H6 owner 批准。

## 19. 风险与应对

| 风险 | 应对 |
|---|---|
| 过度工程化 | 模块化单体和顺序子项目 |
| 伪自治 | 以真实产物和 Evaluator 判定完成 |
| RAG 误解释 | 原文、结构规则和 Evaluator 三重约束 |
| 本体过度工程化 | 从 Standards 驱动的最小业务本体开始，Stage 3 专用服务采用基准触发 |
| 重型平台提前启动 | 设立 H0 业务、SLO、TCO、组织和 competency question 准入门；H3+ 非必经 |
| 错误等价关系 | exact-match 必须审定；向量/LLM 只生成 candidate；保留方向、范围和证据 |
| 推理爆炸或不可终止 | 在线只使用安全 DSL、有界遍历和显式传递关系；OWL 2 RL 仅离线评估/物化 |
| 多存储投影漂移 | PostgreSQL 单一权威写模型、Outbox、package hash、projection checkpoint 和对账 |
| 重型架构形成多真值源 | 区分业务事实、标准权威和 Canonical Model Registry；RDF/图/搜索/向量只做读投影 |
| 平台团队不足 | 重型路线必须具备语义、平台、安全、GIS/Data、SRE 和领域 owner 的长期责任 |
| 知识本体无法驱动业务行动 | 增加 Operational Ontology 和 Object-Action-Capability 统一契约 |
| Action 与工具能力漂移 | ActionType 固定 Capability/Tool/Evaluator 版本，发布时执行契约和影响回归 |
| 动态安全只停留在入口 | 对象、属性、关系、Action、结果和上下文统一 Policy Decision |
| SDK 与运行语义分叉 | 从同一 typed contracts 生成/校验 Python、TypeScript、OpenAPI、MCP/A2A schema |
| 过期标准 | 版本、有效期和替代关系 |
| 越权检索 | 检索前 ACL 和隔离缓存 |
| 工具误操作 | typed invocation、副作用等级、HITL 和回滚 |
| 无限循环 | 预算、尝试指纹和停滞检测 |
| 记忆污染 | 写门、证据、纠错和保留策略 |
| Reward Hacking | 不可变安全集和独立 Evaluator |
| 厂商绑定 | 稳定契约和 Provider Adapter |

## 20. 实施分解与暂缓原则

本设计是总体架构，不应一次性实施。后续拆分为：Runtime Kernel、Standards Knowledge Brain、Governance Pilot、Memory and Experience、Controlled Evolution 五个独立子项目。其中 Domain/Operational Ontology Authority Store、Knowledge Compiler、OntologyPackage、OntologyResolver、Object/Action/Function/Interface contracts、形式语义和本体治理归属 Standards Knowledge Brain；真实 Action 执行、ChangeSet/ActionResult、typed SDK 和业务写回归属 Governance Pilot。两者都不在 Runtime Kernel 首个实施计划中提前实现。

Heavy Ontology Platform 作为独立条件路线 H0-H7 管理，不自动并入上述五个子项目。H0 只形成业务问题、competency questions、容量/SLO/TCO 和 ADR 结论；只有准入门通过后才允许 H1-H7 建设。重型路线不得借机重写 PostGIS、ArcPy、Standards、NL2SQL 或 TWM。

当前阶段仅将这些工作进入 roadmap，不立即对现有核心代码进行大规模改造。第一份实施计划只覆盖 Runtime Kernel，并应在现有 UWM、ArcPy 和其他并行工作稳定合并后，通过独立 worktree 实施。

## 21. 待确认事项

| 项目 | 状态 |
|---|---|
| 生产并发与吞吐 | needs-owner-input |
| p95/p99 延迟 SLO | needs-owner-input |
| RPO/RTO 和异地容灾 | needs-owner-input |
| Trace、Memory、Evidence 和 Artifact 保留期 | needs-owner-input |
| HITL 审批 SLA 和责任人 | needs-owner-input |
| 目标物理 DDL、分区和索引 | Runtime Kernel 子项目确定 |
| OpenSearch/专用向量库/图数据库阈值 | 容量和评测证明后确定 |
| 本体概念映射 precision/recall 和未知拒绝率 | Stage 0 基线后由 owner 批准 |
| 本体领域 owner、审定委员会和变更 SLA | needs-owner-input |
| 组织/行业 namespace、稳定 URI 和跨组织映射政策 | needs-owner-input |
| Stage 3 Fuseki/TDB2 或属性图进入阈值 | 代表性基准和互操作需求证明后确定 |
| Heavy H0 competency questions、业务 sponsor 和三年 TCO | needs-owner-input |
| 重型 RDF/语义平台产品与部署方式 | needs-owner-input：H2/H3 PoC 后 ADR |
| Kafka 或 Redpanda 及 Schema Registry 选型 | needs-owner-input：H5 容量/运维基准后 ADR |
| 重型平台团队编制、预算、值班和供应商支持 | needs-owner-input |
| Operational ObjectType/ActionType 的首批业务对象和状态机 | needs-owner-input：Governance Pilot 立项时确认 |
| 动态策略引擎采用现有代码、OPA 或 Cedar | Runtime Kernel 安全基准后通过 ADR 确定 |
| Action 事务边界、对象 etag、补偿和审批责任 | needs-owner-input |
| Python/TypeScript/OpenAPI/MCP/A2A SDK 兼容性政策 | needs-owner-input |
| 首个真实或脱敏治理数据集 | needs-owner-input |

## 22. 追踪说明

详细证据事实见 `evidence-pack.md`，章节与证据对应关系见 `traceability-matrix.md`，当前实现与目标设计差异见 `design-doc-audit.md`。

## 23. 结论

GIS Data Agent 的大脑应当是模型无关、证据驱动、数据标准和领域本体感知、Capability 驱动的 Cognitive Runtime。Domain Ontology 提供概念、关系、规则和证据语义，Operational Ontology 将这些语义连接到真实对象、Action、Function、动态安全、ChangeSet、ActionResult 和版本化写回。两类本体都不替代 Runtime、RAG、工具或 Evaluator。系统以强类型状态和确定性策略控制专业工具执行，以独立评价验证真实产物和业务结果，以经过治理的记忆积累经验，并通过版本化、可评测、可灰度和可回滚的流程实现受控自我进化。

重型本体平台为跨组织语义、形式推理、多应用对象行动和独立发布治理提供了完整目标，但它不是“大脑必须先有的基础设施”。本设计坚持先用轻量 Stage 1/2 和真实治理试点证明价值，再由 H0 的业务、SLO、TCO 与组织证据决定是否进入重型路线。
