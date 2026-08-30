# GIS Data Agent Cognitive Runtime Evidence Pack

**Evidence baseline commit:** `1421e005b227524ce35d537688a140bd2d8d16e7`
**Design source:** `docs/superpowers/specs/2026-07-15-gis-data-agent-cognitive-runtime-design.md`
**Reference DOCX:** `docs/semantic_fusion_engine_technical_spec.docx`（仅用于版式参考，不作为 Cognitive Runtime 行为证据）

## Evidence Facts

| ID | Type | Fact | Source | Confidence | Supports |
|---|---|---|---|---|---|
| F001 | design | Cognitive Runtime 被用户确认为目标架构，采用受监督自治和受控自我进化 | `docs/superpowers/specs/2026-07-15-gis-data-agent-cognitive-runtime-design.md` | verified | 1-16 |
| F002 | workflow | 当前代码支持顺序 Workflow 和 fan-out/fan-in Workflow | `data_agent/agent.py:160-181` | verified | 3, 7 |
| F003 | workflow-gap | 当前 `_quality_gate_workflow` 仅执行 generator→checker，`max_iterations` 未形成回跳控制流 | `data_agent/agent.py:184-206` | verified | 2, 7, 13 |
| F004 | agent | 当前已拆分数据探查、处理、分析、治理、可视化、报告和 Planner 等角色 | `data_agent/agent.py:282-410, 493-581, 629-995` | verified | 2, 3, 8 |
| F005 | tool-surface | GeneralProcessing 同时注册大量 Toolset；目标设计需要 capability manifest 和动态加载 | `data_agent/agent.py:587-626` | verified | 3, 8, 13 |
| F006 | planner | Planner 已使用 Skill、Operator、ToolEvolution 和 specialist sub-agents，具备能力化改造基础 | `data_agent/agent.py:971-995` | verified | 3, 8, 15 |
| F007 | runner | Headless Runner 显式设置用户 ContextVar，但插件默认为 `plugins or []` | `data_agent/pipeline_runner.py:69-126` | verified | 2, 6, 13 |
| F008 | policy | 已存在 CostGuard、工具重试、Provenance 和 GuardrailsPlugin 组装能力 | `data_agent/plugins.py:35-190, 247-333` | verified | 6, 10, 13 |
| F009 | context | ContextEngine 可聚合多个 provider、排序和截断上下文 | `data_agent/context_engine.py:397-493` | verified | 4, 5 |
| F010 | context-gap | ContextEngine 缓存键只包含 query 和 task_type；embedding boost 当前未改变分数 | `data_agent/context_engine.py:573-629` | verified | 4, 10, 13 |
| F011 | memory | PostgresMemoryService 已实现 session/event 写入和 memory 搜索接口 | `data_agent/conversation_memory.py:129-240` | verified | 9 |
| F012 | memory-gap | 仅向 Runner 传入 memory service 不等于主动检索和写回；目标设计需要显式 Memory Write Gate | `data_agent/pipeline_runner.py:124-126`, `data_agent/conversation_memory.py` | inferred | 9, 13 |
| F013 | standards-rag | 标准起草引用助手并行查询 pgvector、知识库和网页快照，然后执行 LLM rerank | `data_agent/standards_platform/drafting/citation_assistant.py:27-55` | verified | 4, 5, 11 |
| F014 | standards-vector | 标准条款、数据元和术语使用 pgvector 余弦检索 | `data_agent/standards_platform/drafting/citation_sources.py:30-90` | verified | 4, 5 |
| F015 | standards-structure | Standards Platform 可为条款、术语和数据元生成 embedding | `data_agent/standards_platform/analysis/embedder.py:18-61` | verified | 4, 5, 11 |
| F016 | standards-derivation | Standards Platform 已具备多种结构化派生策略和 derivation runner | `data_agent/standards_platform/derivation/runner.py`, `derivation/strategies/` | verified | 4, 11 |
| F017 | standards-review | 标准引用、审定、发布、版本和派生状态已有结构化表与流程 | `data_agent/standards_platform/review/`, `publishing/`, migrations `067-085` | verified | 10, 11 |
| F018 | evolution | 项目已有 self evolution、tool evolution、prompt optimizer、failure learning 等模块 | `data_agent/self_evolution.py`, `tool_evolution.py`, `prompt_optimizer.py`, `failure_learning.py` | verified | 12, 15 |
| F019 | failure-eval | `failure_to_eval.py` 能将生产失败转换为 eval case，但当前可直接写入评测文件，缺少候选审核与晋级治理 | `data_agent/failure_to_eval.py:49-134` | verified | 12, 13 |
| F020 | eval-history | `agent_eval_history` 持久化模型、commit、分数、通过率和评测明细 | `data_agent/eval_history.py:19-115` | verified | 12, 14 |
| F021 | observability | 项目已有 OTel pipeline/agent/tool/LLM span helper 和 Prometheus 指标基础 | `data_agent/otel_tracing.py`, `data_agent/observability.py` | verified | 6, 14 |
| F022 | mcp | 项目已支持 MCP Hub、MCP Toolset 和外部 ArcPy 能力接入 | `data_agent/mcp_hub.py`, `data_agent/toolsets/mcp_hub_toolset.py`, `data_agent/agent.py:989` | verified | 8, 15 |
| F023 | deployment | 项目已有 Docker、Docker Compose、PostGIS/pgvector 镜像和 Kubernetes overlays | `Dockerfile`, `docker-compose.yml`, `docker/postgis-pgvector/`, `k8s/` | verified | 14 |
| F024 | target-schema | `RuntimeIdentity`、`RunWorkspace`、`EvidenceBundle`、`TaskGraph`、`QualityVerdict` 和 Evolution contracts 是目标设计，当前未作为统一生产契约实现 | design spec versus current code search | verified | 2-12 |
| F025 | target-storage | `agent_brain_*`、`agent_evolution_*` 等统一数据模型是目标逻辑模型，物理 DDL 尚未设计 | design spec | needs-owner-input | 5, 14 |
| F026 | nfr | 业务并发、数据规模、RPO/RTO、知识保留期、审批 SLA 和正式性能 SLO 未由现有输入确定 | available repository evidence | needs-owner-input | 14, 16 |
| F027 | template | 参考 DOCX 具有中文标题层级、表格和正式技术文档风格，但无图片 | inventory `inventory.md` | verified | document style |
| F028 | ontology-prototype | `OntologyReasoner` 从 `gis_ontology.yaml` 加载等价组、派生和推断规则，支持字段匹配、派生字段和条件分类 | `data_agent/fusion/ontology.py:17-64,70-208`, `data_agent/standards/gis_ontology.yaml` | verified | 2, 6, 7 |
| F029 | ontology-gap | 当前 YAML Reasoner 的 ontology match 使用固定 0.85 confidence，派生公式通过 `pd.eval` 执行；缺少统一发布审定、ACL、来源和有效期契约 | `data_agent/fusion/ontology.py:88-130,232-247` | verified | 2, 7, 16, 19 |
| F030 | ontology-package | MMFE 已实现并测试 `mmfe.semantic_ontology.v1` JSON 包，覆盖概念、关系、治理契约、消费契约和运行绑定 | `data_agent/fusion/semantic_ontology.py:19-175`, `data_agent/test_fusion_semantic_ontology.py:10-111` | verified | 2, 6, 7, 14 |
| F031 | ontology-authority-foundation | Standards Platform 已有 clause、term、value domain、data element、reference、derived link、review、publish 和 version 等权威结构化资产 | migrations `071-082`, `data_agent/standards_platform/review/`, `publishing/`, `derivation/` | verified | 2, 7, 13 |
| F032 | ontology-graph-foundation | Standards impact graph 聚合 derivation、reference 和 similar-clause 边；XMI exporter 提供稳定 ID 的 UML 数据模型交换 | `data_agent/standards_platform/analysis/impact_graph.py:21-309`, `derivation/data_model_xmi_exporter.py:17-140` | verified | 2, 7, 13 |
| F033 | ontology-dependency-gap | 当前项目依赖中没有 RDFLib、pySHACL、Jena/Fuseki、Neo4j 或其他 RDF/本体服务依赖 | `pyproject.toml`, `requirements.txt`, `uv.lock` search | verified | 7, 15, 17 |
| F034 | ontology-target | 用户要求将本体作为智能体大脑的领域语义骨架融入正式设计，并形成严格的分阶段生产落地路线 | current user instruction; V1.1 design | verified design | 1, 3, 6, 7, 12-21 |
| F035 | ontology-storage | `ontology_*` Authority Store、OntologyPackage、Resolver、RDF/SHACL 和专用语义服务是目标设计；物理 DDL、容量/SLO 和 Stage 3 进入阈值尚未实施或确认 | V1.1 target design versus current repository | needs-owner-input | 7, 13, 15, 17-21 |
| F036 | external-benchmark | Palantir 官方公开体系由 Foundry 数据平台、Ontology operational layer、AIP、应用工作流、geospatial 和企业运维治理构成 | `docs/twm-vs-palantir-technical-system-comparison.md`（2026-06-21，含官方来源） | verified external baseline | 1, 3, 7, 15, 19 |
| F037 | benchmark-gap | Palantir Ontology 强调 object/property/link/action/function/dynamic security；GIS Data Agent 当前本体原型主要覆盖标准、概念、字段、规则和关系，尚无统一 Operational Ontology 主链 | Palantir official baseline versus F028-F032 and current code search | verified comparison | 2, 3, 7, 8, 13-18 |
| F038 | target-operational-ontology | ObjectType/PropertyType/LinkType/ActionType/FunctionType/InterfaceType、ObjectInstanceRef、ChangeSet、ActionResult、动态安全和 typed consumption layer 是 V1.2 目标设计 | user-requested Palantir comparison adoption; V1.2 design | verified design | 3-21 |
| F039 | implementation-gap | 当前 Capability、Toolset、Skill、Operator、MCP、REST 和 UI contract 分散，尚未以统一 ActionType 和 SDK schema 约束 | code inventory and current design audit | verified/inferred | 2, 7, 8, 14, 17-20 |
| F040 | heavy-ontology-target | 用户要求明确说明本体在生产环境采用“重型方式”时的完整技术实现架构，并刷新正式设计和 roadmap | current user instruction; `docs/reports/gis-data-agent-heavy-ontology-production-architecture-2026-07-15.md` | verified design | 1, 3, 7, 15-23 |
| F041 | heavy-platform-gap | 当前仓库未发现 RDFLib/pySHACL/Fuseki/RDF4J、OPA/Cedar、Kafka/Redpanda 等组成专用重型 Ontology Platform 的依赖或部署配置 | `pyproject.toml`, `requirements*.txt`, Docker/K8s and repository search on 2026-07-15 | verified | 2, 7, 15-21 |
| F042 | heavy-entry-gate | 重型本体平台是条件目标设计；具体产品、版本、SLO、RPO/RTO、容量、预算、团队和 H3+ 进入决定缺少 owner 证据 | V1.3 target design and available repository evidence | needs-owner-input | 7, 15-21 |

## Confidence Summary

- `verified`：当前代码、配置、迁移、测试、已确认设计或 inventory 可直接支持。
- `inferred`：由 ADK 运行语义和当前调用方式合理推断，正式实施前需以集成测试确认。
- `needs-owner-input`：缺少业务容量、SLO、保留期或物理模型决策，不在文档中伪造。
