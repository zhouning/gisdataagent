# GIS Data Agent 是否需要接入 ARD 的评估结论

> 评估日期：2026-06-19  
> 对象：Agentic Resource Discovery (ARD) 与 GIS Data Agent

## 结论

GIS Data Agent 当前阶段**不需要把 ARD 作为核心依赖接入**。ARD 更适合作为后续的“对外生态互操作层”或“跨 Agent 资源发现门面”，而不是替换当前系统的 ADK 编排、MCP Hub、自定义 Skills/User Tools、Workflow、数据目录或语义层。

建议优先级：

1. **短期不做完整 ARD Registry**，避免分散当前 A2A、MCP、权限、任务状态机等关键工程精力。
2. **中期先做只读 `/.well-known/ai-catalog.json`**，把 GIS Data Agent 的 MCP Server、A2A Agent Card、内置 Skills、核心工作流摘要暴露为标准 AI Catalog entries。
3. **长期再实现 `POST /search` / `POST /explore` / `GET /agents`**，将现有能力目录、MCP Hub、Skill Marketplace 和语义检索包装成 ARD 发现服务。

一句话判断：**ARD 对 GIS Data Agent 不是必须安装的底座，而是在进入跨 Agent 生态、Agent 市场或企业 Agent 联邦时值得补上的标准发现接口。**

## ARD 是什么

ARD 是 Agentic Resource Discovery 的开放发现协议。它回答的是：

> 对于当前任务，有哪些 Agentic Resource 可用？

这里的 Agentic Resource 可以是 Agent、MCP Server、Skill、API、Plugin、Workflow 等。

ARD 的关键点：

- 它是**发现层**，不是执行运行时。
- 它不替代 MCP、A2A、Skills 或 API。
- 它通过 `/.well-known/ai-catalog.json` 描述可发现资源。
- 它通过 `POST /search` 等接口支持按任务搜索资源。
- 找到资源后，仍然通过资源自己的原生协议调用，例如 MCP、A2A、Skill 安装或 REST API。

核心接口：

| 接口 | 作用 | 是否必需 |
|---|---|---|
| `/.well-known/ai-catalog.json` | 发布资源清单 | AI Catalog 的标准入口 |
| `POST /search` | 按自然语言任务搜索资源 | ARD 发现服务必需 |
| `POST /explore` | 浏览和过滤资源集合 | 可选 |
| `GET /agents` | 列出资源集合 | 可选 |

## GIS Data Agent 当前已有能力

GIS Data Agent 已经具备一套内部能力发现与接入机制：

- ADK 语义路由：将用户请求分发到 Governance、Optimization、General 等 Pipeline。
- Custom Skills：用户可创建自定义 LlmAgent，配置 instruction、toolsets、触发词和模型层级。
- User-Defined Tools：支持 `http_call`、`sql_query`、`file_transform`、`chain` 等声明式工具。
- Workflow Editor：支持多 Agent pipeline 和 DAG 编排。
- MCP Hub：支持 DB + YAML 配置、stdio/SSE/streamable HTTP、多用户隔离、动态启停。
- `/api/capabilities`：聚合内置 Skills 和 Toolsets，用于前端能力展示。
- MCP Server 外部接入：已能向 Claude Desktop、Cursor、Windsurf 等 MCP 兼容客户端暴露 GIS 工具。
- 数据目录、语义层和知识库：已经承担业务数据和领域能力的内部检索。

因此，ARD 当前不是补齐“系统无法运行”的缺口，而是补齐“标准化对外发现”的能力。

## 什么时候需要接入 ARD

以下场景下，ARD 的价值会明显上升：

1. **发布到 Agent 市场或企业 Agent 目录**
   - 希望第三方 Agent 自动发现 GIS Data Agent。
   - 希望平台以标准 `ai-catalog.json` 方式暴露 GIS 能力。

2. **跨组织、多部门、多城市 Agent 联邦**
   - 省级 Agent 需要发现各市 GIS Data Agent。
   - 自然资源、环保、交通、审批等多个专业 Agent 需要互相发现。

3. **GIS Data Agent 作为 Client 动态找外部能力**
   - 当前系统主要依赖管理员或用户手动配置 MCP Server。
   - 如果希望 Agent 在运行时自动搜索“气象 Agent”“交通 Agent”“文档审查 Agent”等外部能力，ARD 可以作为发现入口。

4. **补齐 A2A 生态中的服务发现**
   - 当前 A2A 文档已指出缺少标准发现端点和服务发现/注册中心。
   - ARD 可以作为 A2A Agent Card 之外的资源发现层。

5. **客户要求开放互操作标准**
   - 面向政企客户、生态集成商、第三方插件市场时，标准发现协议比私有 API 更容易被接受。

## 什么时候不需要优先做

以下情况下，不建议优先投入完整 ARD：

- 当前主要目标是本地演示、单租户部署或封闭试点。
- 外部工具数量较少，MCP Hub 手动配置足够。
- 当前痛点是 A2A 执行合规、权限认证、任务状态、观测性、工具稳定性，而不是资源发现。
- 尚未形成可发布的稳定 Agent Card、MCP Server manifest、Skill 包格式和权限策略。
- 没有明确的外部 Agent 消费方。

## 与现有架构的关系

ARD 应作为 GIS Data Agent 的**外层标准发现接口**，不应替换现有内部模块。

推荐映射关系：

| GIS Data Agent 现有模块 | ARD/AI Catalog 映射 |
|---|---|
| A2A Agent Card | `application/a2a-agent-card+json` entry |
| MCP Server | `application/mcp-server+json` entry |
| 内置 ADK Skill | `application/ai-skill` 或自定义 Skill entry |
| Custom Skill Bundle | `application/ai-catalog+json` 或 Skill bundle entry |
| Workflow | Workflow/API resource entry |
| `/api/capabilities` | ARD `/agents` 和 `/search` 的数据来源之一 |
| MCP Hub | ARD Client 侧发现结果的安装/接入目标 |
| 语义层/数据目录 | ARD 搜索 ranking 与 filtering 的增强信号 |

## 推荐路线

### Phase 0：不改核心链路

目标：保持当前 ADK/MCP/A2A 架构稳定。

工作重点：

- 完善 MCP Hub、MCP Server 和外部客户端接入。
- 补齐 A2A 标准端点、任务状态机、认证和异步执行。
- 保持 `/api/capabilities` 作为内部能力聚合接口。

### Phase 1：发布只读 AI Catalog

目标：让 GIS Data Agent 可以被标准发现系统索引。

新增：

- `GET /.well-known/ai-catalog.json`
- `GET /api/ard/catalog` 可选，供内部调试

数据来源：

- A2A Agent Card
- MCP Server 对外入口
- 内置 Skills 元数据
- 核心工作流和工具集摘要

最小 entry 示例：

```json
{
  "identifier": "urn:ai:gis-data-agent:agent:gis-analysis",
  "displayName": "GIS Data Agent",
  "type": "application/a2a-agent-card+json",
  "url": "https://example.com/.well-known/agent.json",
  "description": "Geospatial analysis agent for data governance, spatial analysis, visualization, and land-use optimization.",
  "tags": ["gis", "geospatial", "mcp", "a2a", "postgis"],
  "representativeQueries": [
    "analyze land use change in this county",
    "check topology defects in a cadastral dataset",
    "find suitable farmland consolidation parcels"
  ]
}
```

### Phase 2：实现内部 ARD Registry

目标：把 GIS Data Agent 的能力集合包装成可搜索发现服务。

新增：

- `POST /search`
- `GET /agents`
- 可选 `POST /explore`

实现策略：

- 第一版用规则和关键词过滤，不引入复杂向量索引。
- 后续接入语义层、知识库、使用反馈和代表查询。
- `score` 仅表示语义相关性，不表示安全、可信或合规。

### Phase 3：作为 ARD Client 发现外部资源

目标：让 GIS Data Agent 能按任务发现外部 Agent/MCP/Skill。

新增：

- 可信 discovery endpoint allowlist。
- 搜索外部 ARD 服务。
- 验证 `trustManifest`、publisher domain、签名和合规声明。
- 将选中的 MCP/A2A 资源导入 MCP Hub 或 A2A Client。

注意：外部资源发现必须经过权限、审计、人工确认或管理员审批，不能让 LLM 自动安装未知执行资源。

## 风险与注意事项

1. **安全风险**
   - ARD 发现到的外部资源不等于可信资源。
   - 必须校验域名、publisher、trust manifest、认证方式和权限范围。

2. **产品复杂度**
   - 完整 Registry 会引入搜索、排序、分页、过滤、联邦、缓存和信任验证。
   - 在没有外部生态消费方前，收益有限。

3. **协议成熟度**
   - ARD v0.9 仍处于 draft/proposal 状态。
   - 建议先做松耦合适配，不把内部核心模型强绑定到 ARD schema。

4. **不要混淆发现与执行**
   - ARD 只负责“找什么”。
   - MCP/A2A/API 仍负责“怎么调用”。

## 最终建议

当前 GIS Data Agent 最优动作是：

1. **不把 ARD 纳入核心运行时依赖。**
2. **优先补齐 A2A server 合规、MCP Hub 稳定性和权限审计。**
3. **新增一个轻量 `/.well-known/ai-catalog.json` 作为对外标准名片。**
4. **当出现跨组织 Agent 联邦或客户要求 Agent 目录时，再实现完整 ARD `/search`。**

这条路线工程风险低、对现有架构侵入小，同时为后续进入 Agent 市场和企业 Agent 生态预留标准接口。

## 参考来源

- ARD Home: https://agenticresourcediscovery.org/
- How ARD works: https://agenticresourcediscovery.org/how_ard_works/
- ARD Specification: https://agenticresourcediscovery.org/spec/
- AI Catalog Standard: https://agenticresourcediscovery.org/ai_catalog_spec/
- GIS Data Agent 项目文档：
  - `CLAUDE.md`
  - `docs/mcp-integration-guide.md`
  - `docs/a2a-capabilities.md`
  - `docs/user-self-service-extension-plan.md`
  - `data_agent/capabilities.py`
  - `data_agent/mcp_hub.py`
