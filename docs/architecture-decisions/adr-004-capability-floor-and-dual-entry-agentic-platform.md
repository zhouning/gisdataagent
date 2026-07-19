# ADR-004：传统平台能力下限、LLM 可选与多入口能力合同

**Status**: Accepted

**Date**: 2026-07-19

**Decision owners**: Product Architecture, Data Platform, GIS Engineering, UX, Security

**Related baseline**: [传统平台能力基线与 Agentic 升维设计](../traditional-platform-baseline-and-agentic-elevation-2026-07-19.md)

**Source reviewed**: `时空数据中台产品详细设计 v3.0.0.0`（2026-07-19 完整审查；重点包括 Gravitino + Iceberg、DolphinScheduler、Spark/Flink、GPA、Canvas/SQL/Notebook/API、CDC、质量、安全、服务和多形态部署）

**Related decisions**: [ADR-001 可插拔地理空间存储、计算与服务边界](adr-001-geospatial-lakehouse-and-postgis-boundary.md) · [ADR-002 统一元数据控制面](adr-002-unified-metadata-control-plane.md) · [ADR-003 统一调度与作业控制面](adr-003-unified-orchestration-and-job-control-plane.md) · [ADR-005 DataOps 与 AgentOps 双运营闭环](adr-005-dataops-and-agentops-operating-loops.md)

## Context

GIS Data Agent 的目标是成为比传统时空数据中台更好用、更强大的下一代 Data Platform。传统平台虽然操作复杂，但已覆盖规划、汇聚、分层、建模、开发、调度、质量、安全、资产、服务、分析、地图、审批和部署运维的完整生命周期。

当前项目的新型智能能力发展快于部分基础平台能力。如果没有明确能力下限，roadmap 会继续优先增加 Agent、模型、工具和领域页面，而遗漏传统平台已经解决的生产任务。另一方面，直接复制旧菜单、微服务和中间件会把原有复杂度带入下一代。

旧平台的技术设计还给出了一个必须继承的工程事实：生产能力不能只存在于自然语言对话中。Canvas、SQL、脚本、Notebook、API、定时任务和审批都能在没有 AI 模型的环境完成完整闭环。GIS Data Agent 的私有化、离线、信创或成本受限 profile 也可能没有可用 LLM；若任何数据治理、开发、发布、运维或 GWM 基础操作因此不可用，就没有达到“下一代数据平台”的下限。

因此，“Agentic”与“调用 LLM”必须解耦。LLM 是可插拔的意图理解、候选生成、解释与诊断能力；它不能成为 capability discovery、权限、definition 编辑、preview、执行、审批、Run 状态、审计或恢复的前置条件。对同一平台能力，UI、API、SDK、CLI、TUI、Notebook 和 Agent tool 必须共享同一个稳定的 typed contract 与执行链路。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. Agent 对话或 LLM 成为唯一入口 | 表面简洁、演示速度快 | LLM/网络不可用即丧失平台能力；隐式定义不可审查、难调试 | 不选 |
| B. 完整复制传统菜单和技术栈后再加 Agent | 能力清单看似完整 | 重复旧复杂度，形成两套交互和多套事实 | 不选 |
| C. UI/API/CLI/TUI/Notebook/Agent 各自实现业务逻辑 | 入口可快速各自迭代 | 权限、版本、执行和审计必然漂移 | 不选 |
| D. 按用户结果定义能力下限，以 typed capability contract 驱动所有入口，LLM 仅为可选适配器 | 保留完整生产能力、无 LLM 可运行、统一治理、可渐进迁移 | 前期要先定义 schema、幂等、preview 与 parity 测试 | **选择** |

## Decision

### 1. 能力等价按结果判定

传统平台的核心用户任务构成 GIS Data Agent 的能力下限。等价不要求相同菜单、组件或数据库，但要求用户能完成相同生命周期，并具备不低于原平台的权限、血缘、审计、恢复和运维证据。

没有完整生命周期的同名 API、类、工具或 Tab 只能标记“局部可用”，不能计入能力覆盖。

### 2. LLM 可选的多入口能力合同

每项生产 capability 必须先定义可机器验证的 `CapabilitySpec`，再生成或接入各入口；不允许以聊天 prompt、页面点击路径或某个 notebook cell 作为唯一接口。`CapabilitySpec` 至少冻结：

```text
capability_id / version / owner / lifecycle
input and output JSON Schema / semantic type
query | command | long_running classification
read-write resource set / side effect / risk class
SubjectContext / PolicyDecision obligation
idempotency key / expected version / dry-run and preview semantics
sync result or RunRef / Artifact and Evidence contract
retry / cancel / compensate / reconcile support
OpenAPI operation / AsyncAPI-CloudEvents envelope / MCP tool mapping
```

入口只负责表达、编辑、调用与呈现；`Capability Gateway -> Policy -> Definition/ChangeSet -> Orchestration -> Artifact/Evidence` 是唯一生产链。所谓“入口等价”是 capability、definition、execution、policy 和 audit 等价，不要求 TUI 复制 Web 地图的像素级呈现，也不允许 Web、Agent 或 Notebook 绕过同一命令。

```text
Web/Map Canvas   API/SDK     gda CLI     gda TUI     Notebook     Agent Tool
       \             |           |           |           |             /
        \------------+-----------+-----------+-----------+------------/
                                     |
                    CapabilitySpec + DefinitionVersion + ChangeSet
                                     |
             SubjectContext -> Policy -> Preview/Approval -> PlatformRun
                                     |
          DolphinScheduler / Temporal / typed executor -> Artifact + Audit
```

#### 2.1 入口职责与技术基线

| 入口 | 适用任务 | 必须具备 | 禁止事项 |
|---|---|---|---|
| Web / Map / Canvas | 发现、可视化建模、地图、审批、运营 | 表单/画布生成 typed definition；可查看 diff、preview、Run、artifact、policy | 浏览器内保留生产 definition 或自行执行特权任务 |
| REST/OpenAPI + SDK | 系统集成、应用开发、GitOps/CI | schema discovery、幂等 command、RunRef、事件订阅和稳定错误码 | 为 SDK 维护独立业务状态机 |
| `gda` CLI | 自动化、离线运维、CI、专家批量操作 | 非交互 JSON/YAML I/O、`--dry-run`、`--wait`、`--output json`、退出码和 credential delegation | 通过 shell 参数逃逸 policy 或 audit |
| `gda` TUI | SSH/堡垒机、受限网络、现场运维和审批 | 目录/搜索、definition diff、Run/日志/进度、质量问题、审批、恢复操作；只调用公开 API | 抓取 Web 页面或复制管理逻辑 |
| Notebook | 探索、调试、可复现实验 | 使用 SDK 生成 definition/change set；发布时固化代码、依赖、镜像和输入版本 | 把交互 kernel 直接当生产 Run |
| MCP/A2A Agent tool | 智能体调用、跨 Agent 协同 | CapabilitySpec 自动映射的 typed tool、least privilege、preview/approval/evidence 返回 | 将自由文本或 LLM 凭据当作授权与执行真值 |

当前 Python 技术栈已具备 `Typer`、`Rich` 和 `Textual` 依赖，因此 `gda` CLI/TUI 采用它们作为薄适配器；HTTP 以 OpenAPI 3.1 为 canonical contract，异步通知以 AsyncAPI/CloudEvents envelope 为 canonical contract，MCP/A2A tool schema 从同一 `CapabilitySpec` 投影。框架选择不引入第二业务层，CLI/TUI 与 Web/API 使用相同 SubjectContext、idempotency、PolicyDecision、DefinitionVersion、PlatformRun 和 Artifact 引用。

#### 2.2 三种运行模式

| 模式 | LLM 要求 | 输入方式 | 适用 | 不变的控制 |
|---|---|---|---|---|
| Direct deterministic | 无 | 表单、Canvas、SQL、CLI/TUI、API、SDK、Notebook | 所有 P0 数据平台和运维能力 | schema、policy、approval、Run、artifact、audit |
| Declarative playbook | 无 | 版本化 Blueprint、schedule、event trigger、rule/template | 可重复 DataOps、治理、质量和运维自动化 | 同上，且由 DolphinScheduler/Temporal 承担 durable execution |
| Agent-assisted | 可用时启用 | 自然语言、上下文、Agent plan | 发现、解释、候选 definition、诊断、受控行动建议 | Agent 只能生成/调用 CapabilitySpec，不能绕过同上控制 |

部署 profile 必须声明 `llm_mode = disabled | optional | required_for_agent_feature`。`disabled` 不得隐藏菜单、API 或 CLI/TUI 命令，也不得使已发布数据产品、质量、调度、审批、服务、地图、GWM 确定性路径或恢复功能失效；仅自然语言理解、生成式解释和 LLM-only Agent enhancement 可以不可用，并须返回稳定的 `LLM_UNAVAILABLE` 能力状态与等价确定性入口。

#### 2.3 Agent 与非 Agent 一致性

所有生产能力至少有一个 non-agent deterministic path 和一个受治理的 Agent tool path。Agent 执行前后必须能把同一 typed input、resolved version、policy decision、RunRef 和 evidence 交还给人类/API/CLI；反之，从专业入口创建的对象也必须可被 Agent 在授权范围内发现、解释、预览与调用。Agent 不拥有第二套隐藏 workflow、metadata、permission 或 result state。

#### 2.4 云盘客户端是一级确定性能力

传统平台的云盘客户端不是普通 Web 文件上传：它在用户设备或边缘环境执行目录发现、分片上传/下载、断点续传、分片与完整文件校验，并将 S3/MinIO、NAS、SMB 等异构文件位置接入平台。GIS Data Agent 保留并升维为 `DriveTransfer` capability family，包含 `DriveEndpoint`、`FolderBinding`、`TransferSession`、`TransferCheckpoint`、`FileRevision`、`IntegrityVerdict`、`ArtifactManifest` 与 `IngestRequest`；客户端本地 checkpoint 仅用于恢复，服务端 session/manifest/审计才是耐久控制事实。

默认对象存储 path 使用受限的 S3 multipart pre-signed URL；NAS/SMB/受限网络通过认证 transfer gateway/provider 适配。分片及全文件 checksum、输入文件 fingerprint、ETag/part receipt、加密、配额、目的 bucket/prefix、actor、policy、scan 和 quarantine verdict 必须被记录。multipart ETag 不能被误当作完整内容 hash。上传完成后对象仍在 quarantine，只有 integrity/安全扫描/格式识别/manifest/权限通过后，DolphinScheduler ingestion process 才能解析并提升为 Landing/Raw；任何部分文件、删除 tombstone 或目录同步冲突不得直接进入 Bronze active snapshot。

`gda drive` CLI/TUI、Web 传输面板、API/SDK 和受控 Agent tool 调用同一 `DriveTransfer` contract。Agent 可提出或提交已授权的 transfer plan，但不得读取用户本地目录、发起下载或扩大同步范围，除非本地客户端显式授予 scoped capability/路径/有效期；没有 LLM 时，客户端同步、上传下载、恢复、审计和入湖链路必须完整可用。

### 3. 四个稳定工作面

产品信息架构收束为 Discover、Build、Operate、Govern 四个工作面；Agent 是跨工作面的上下文助手。领域产品和 GWM 作为 data product/intelligence view 接入，不继续增加彼此孤立的基础平台 Tab。

### 4. 渐进披露而非能力删除

- Easy path 显示推荐配置、影响、成本和风险，适合多数常见任务。
- Pro path 展开 schema、SQL/DAG、资源、partition、policy 和发布参数。
- Ops path 展开 Run/Attempt、logs/traces、SLO、capacity、recovery 和 audit。

三个层级操作同一 Resource/Definition/Run，不复制配置。

### 5. Definition as Code

Source、Blueprint、Model、Contract、TaskGraph、Quality、Policy、Service 和 Projection 都必须版本化、可 diff、可导出、可测试、可 review 和可重放。Agent 输出的是这些对象或 changeset，不是只存在于聊天历史中的指令。

### 6. 能力验收与复杂度验收并行

每个阶段同时通过：

- **Parity gate**：代表任务覆盖传统平台结果。
- **Agentic uplift gate**：步骤/耗时、首跑成功率、问题恢复或复用效果有可重复改进。
- **Control gate**：专业入口、API、CLI/TUI、权限、审计、回滚和非 Agent 重放仍成立。
- **LLM-free gate**：在禁用模型 provider、外网和 Agent runtime 的 profile 中，代表任务仍可通过 Web/API/SDK/CLI/TUI/Notebook 完成并产生相同的 DefinitionVersion、PlatformRun 与 Artifact contract。

## Consequences

### Positive

- roadmap 不再因用户未点名而遗漏基础平台能力。
- Agentic 创新建立在完整生产系统上，而不是替代工程控制。
- 专业用户保留精确控制，普通用户获得更短路径。
- 旧平台能力可以按统一对象模型迁移，不需要复制其技术债。
- 离线、私有化和无 LLM 环境不再是功能降级版；只是少了生成式体验层。

### Negative

- 产品范围比单纯 Agent 应用更大，需要明确优先级和代表任务。
- 前端需要从大量平级 Tab 逐步收束为任务型工作面。
- typed capability、definition、preview、changeset 和多入口一致性增加前期设计成本。

### Mitigation

- 先用自然资源地类图斑产品完成一条全生命周期，不同时建设所有行业和连接器。
- 以 connector/operator/service certification 扩展覆盖面，不默认部署所有中间件。
- 每个能力只建立一个写权威，旧模块通过 adapter 迁移。
- 以 schema conformance test 覆盖 Web/API/SDK/CLI/TUI/Notebook/MCP；P0 capability 的测试矩阵、帮助文本和审计字段从 `CapabilitySpec` 生成，而不是人工维护多份清单。
- 以代表任务和用户测试冻结复杂度目标，避免主观宣称“更好用”。

## Revisit Triggers

- 用户研究证明某类专业入口完全没有使用价值，且 Agent/API 路径可满足审查、调试和恢复要求。
- 新行业场景需要第五个稳定工作面，无法通过领域 view 或扩展包承载。
- 双入口维护成本超过价值，且可通过自动生成 UI/definition editor 降低。
- 某个入口无法表达 capability 的全部 typed contract，或 LLM-free profile 无法完成已承诺的 P0 任务。
