# 标杆产品分析：Claude CoWork & Agent Teams

> 分析日期: 2026-02-25
> 目标: 以 Claude CoWork（多智能体协作标杆）为参照，提炼 Multi-Agent 编排、任务协调、质量门控等最佳实践，增强 GIS Data Agent 的架构能力

---

## 一、为什么选择 Claude CoWork 作为标杆

| 维度 | 详情 |
|------|------|
| **代表性** | Anthropic 于 2026 年 2 月随 Claude Opus 4.6 发布的多智能体协作系统，是当前业界最成熟的 Agent Teams 实现之一 |
| **核心理念** | 从"单 Agent 独立工作"到"Agent 团队自组织协作"的范式跃迁 |
| **与我们的关联** | GIS Data Agent 当前是 SequentialAgent 固定流水线 + 可选的 Dynamic Planner 单 Agent 调度；CoWork 的多 Agent 并行协作、任务依赖管理、质量门控等模式可以直接指导我们的架构演进 |
| **双形态** | CoWork（面向知识工作者的桌面产品）+ Agent Teams（面向开发者的 CLI 多 Agent 框架），覆盖了"产品体验"与"架构设计"两个维度 |

**选择逻辑**：我们已有 OpenClaw（个人 Agent 标杆）和 OpenAI Frontier（企业治理标杆）的分析。CoWork 填补了第三个关键维度——**多智能体协作编排**，这恰恰是 GIS Data Agent 从 v4.0 向 v5.0 演进的核心架构挑战。

---

## 二、Claude CoWork 产品概况

### 2.1 双产品形态

| 维度 | CoWork（桌面产品） | Agent Teams（开发者框架） |
|------|-------------------|------------------------|
| **定位** | 面向知识工作者的多步骤任务助手 | 面向开发者的多 Agent 协作编排系统 |
| **发布** | 2026 年 1 月（Research Preview） | 2026 年 2 月 5 日（随 Opus 4.6） |
| **运行环境** | Claude Desktop（无需终端） | Claude Code CLI |
| **核心能力** | 文档生成、研究综合、本地文件访问、子 Agent 协调 | 多个独立 Claude Code 会话协同工作，共享任务列表 |
| **适用用户** | Pro/Max/Team/Enterprise 付费用户 | 开发者 |
| **状态** | Research Preview | Experimental |

### 2.2 Agent Teams vs 传统 Subagent 的关键区别

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   传统 Subagent 模型                Agent Teams 模型             │
│                                                                  │
│       ┌──────┐                        ┌──────┐                   │
│       │ Main │                        │ Lead │                   │
│       │Agent │                        │Agent │                   │
│       └──┬───┘                        └──┬───┘                   │
│          │                               │                       │
│    ┌─────┼─────┐                ┌────────┼────────┐              │
│    ▼     ▼     ▼                ▼        ▼        ▼              │
│  ┌───┐ ┌───┐ ┌───┐          ┌───┐    ┌───┐    ┌───┐            │
│  │Sub│ │Sub│ │Sub│          │ T1│◄──►│ T2│◄──►│ T3│            │
│  │ A │ │ B │ │ C │          │   │    │   │    │   │            │
│  └───┘ └───┘ └───┘          └───┘    └───┘    └───┘            │
│                                                                  │
│  • 结果只回传给 Main          • 各 Teammate 拥有独立上下文窗口    │
│  • Sub 之间无法通信            • Teammate 之间可以直接消息通信      │
│  • Main 管理所有协调           • 共享任务列表，自组织协调           │
│  • 适合聚焦型任务              • 适合需要讨论和协作的复杂任务       │
│  • Token 成本较低              • Token 成本较高                   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、核心设计模式深度提取

### 模式 1：七原语架构（Seven Primitives Architecture）

CoWork Agent Teams 的整个多智能体系统仅由 **7 个原语操作** 构成：

| 原语 | 职责 | 类比 |
|------|------|------|
| `TeamCreate` | 创建团队（目录+配置+任务列表） | "组建项目组" |
| `TaskCreate` | 定义任务（主题、描述、状态、依赖） | "立项分工" |
| `TaskUpdate` | 更新任务状态、分配负责人、设依赖 | "排期协调" |
| `TaskList` | 查看所有任务概况 | "看板视图" |
| `TaskGet` | 获取单个任务详情 | "查看工单" |
| `Task`(spawn) | 生成 Teammate（独立 Claude 实例） | "招聘队员" |
| `SendMessage` | Agent 间消息通信（DM/广播/关停） | "即时通讯" |

```
┌─────────────────────────────────────────────────────┐
│                  Agent Teams 生命周期                 │
│                                                     │
│  Setup ─────────► Execution ─────────► Teardown     │
│                                                     │
│  TeamCreate       TaskList (领任务)     shutdown_req │
│  TaskCreate ×N    TaskUpdate (认领)     shutdown_res │
│  Task (spawn)     工作 + SendMessage    TeamDelete   │
│                   TaskUpdate (完成)                  │
│                   TaskList (下一个)                  │
└─────────────────────────────────────────────────────┘
```

**对 GIS Data Agent 的启示**：
- 当前 ADK 的 `SequentialAgent` 和 `transfer_to_agent` 是**静态编排**——流水线在定义时就固定了
- CoWork 的七原语模型是**动态编排**——任务在运行时创建、分配、依赖解析
- **核心学习：GIS Data Agent 可以引入任务看板机制**，让 Dynamic Planner 不仅决定"调用哪个子 Agent"，还能创建并行任务、设置依赖关系、动态分配资源
- 例如：用户请求"分析北京市适合开咖啡店的区域"时，Planner 可同时创建"获取 POI 数据"、"获取人口数据"、"获取租金数据"三个并行任务，等全部完成后再创建"综合评分"任务

### 模式 2：文件系统即数据库（File-System as Database）

CoWork 的所有协调状态都存储在文件系统中：

```
~/.claude/
├── teams/{team-name}/
│   ├── config.json           # 团队元数据 + 成员列表
│   └── inboxes/
│       ├── lead.json         # Lead 的消息队列
│       ├── researcher.json   # Researcher 的消息队列
│       └── coder.json        # Coder 的消息队列
└── tasks/{team-name}/
    ├── 1.json                # 任务 #1
    ├── 2.json                # 任务 #2
    └── 3.json                # 任务 #3
```

**设计哲学**：
- 无需外部数据库、消息队列或 Redis
- 每个任务是独立 JSON 文件，天然支持并发（文件锁）
- Agent 只需"读文件"即可感知全局状态
- 极简依赖：只要有文件系统就能运行

**对 GIS Data Agent 的启示**：
- 当前我们的 Agent 间状态传递依赖 ADK `Session.state`（内存字典）——一旦进程崩溃，状态丢失
- 可以借鉴 CoWork 的思路，将关键分析中间状态（数据概况、处理结果、分析结论）**持久化到磁盘**
- 这也为"分析任务恢复"提供了基础——用户中断分析后，下次可从中断点继续
- 结合我们现有的 PostgreSQL 后端，可以做得比文件系统更好（`analysis_tasks` 表）

### 模式 3：点对点通信 + 广播抑制（P2P Messaging + Broadcast Restraint）

CoWork 的消息系统有一个关键设计决策：

```
                 消息成本模型

  message (DM)        →  1 次投递     ✓ 默认选择
  broadcast (广播)     →  N 次投递     ✗ 仅紧急情况
  shutdown_request    →  1 次投递     ✓ 优雅关停
```

**核心规则**：
- Teammate 的纯文本输出对其他 Agent **不可见**——必须显式调用 `SendMessage` 才能通信
- **默认用 DM，不用广播**——广播成本随团队规模线性增长
- Agent 空闲时自动通知 Lead（系统行为，非显式消息）
- Peer-to-Peer DM 时，Lead 会收到简短摘要（知情但不干预）

**对 GIS Data Agent 的启示**：
- 当前 ADK Pipeline 中，Agent 只能通过 `output_key` 写入 `Session.state` 来"传话"——这是**单向的、隐式的**
- CoWork 启发我们思考：如果 DataExploration 发现数据质量问题，应该能**主动通知** DataProcessing 调整清洗策略，而不是等整个流水线跑完才发现
- **建议引入 Agent 内部消息机制**：用 `Session.state` 中的一个 `_messages` 列表实现，每个 Agent 在开始执行前检查是否有上游消息

### 模式 4：任务依赖图 + 自动解锁（Task Dependency Graph + Auto-Unblock）

```
  TaskCreate("获取POI数据")          ──┐
  TaskCreate("获取人口数据")          ──┼── blockedBy: [] (可并行)
  TaskCreate("获取租金数据")          ──┘
                                       │
                                       ▼ 全部 completed
  TaskCreate("综合选址评分")          ── blockedBy: [1, 2, 3]
                                       │
                                       ▼ completed
  TaskCreate("生成分析报告")          ── blockedBy: [4]
```

**机制**：
- `addBlocks` / `addBlockedBy` 建立任务间依赖
- 当 blocking 任务完成时，被阻塞的任务**自动解锁**（无需手动干预）
- Teammate 通过 `TaskList` 发现新解锁的任务 → 自行认领 → 执行

**对 GIS Data Agent 的启示**：
- 当前 `SequentialAgent` 是**全串行**——即使数据获取和地理编码可以并行，也只能一步一步来
- Dynamic Planner 的 `transfer_to_agent` 虽然灵活，但仍是**单线程调度**
- **核心架构升级方向**：引入 DAG（有向无环图）任务调度，支持并行分支 + 汇聚
- 这将显著缩短复杂分析的端到端时间（如选址分析从串行 5 步 → 并行 3 步 + 串行 2 步）

### 模式 5：Agent 类型特化 + 工具隔离（Agent Specialization + Tool Isolation）

CoWork 定义了多种 Agent 类型，**关键在于工具权限的差异化**：

| Agent 类型 | 模型 | 工具权限 | 用途 |
|-----------|------|---------|------|
| **Explore** | Haiku（快速） | 只读（无 Write/Edit） | 文件发现、代码搜索 |
| **Plan** | 继承主模型 | 只读（无 Write/Edit） | 方案设计、架构研究 |
| **general-purpose** | 继承主模型 | 全部工具 | 复杂任务、代码修改 |
| **自定义 Agent** | 可配置 | 可白名单 | 按需定义 |

**自定义 Agent 的 Markdown 定义格式**：

```markdown
---
name: security-reviewer
description: Reviews code for security vulnerabilities.
tools: Read, Grep, Glob, Bash       # 工具白名单
model: sonnet                        # 使用更便宜的模型
permissionMode: default
isolation: worktree                  # Git worktree 隔离
memory: user                         # 持久化记忆
---

You are a senior security reviewer. Focus on...
```

**对 GIS Data Agent 的启示**：
- 当前所有 ADK LlmAgent 都使用 Gemini 2.5 Flash，所有 Agent 都有访问全部 tools 的权力
- **应按职责分级**：
  - 数据探索 Agent：只读工具（读文件、查数据库）→ 用更快/更便宜的模型
  - 数据处理 Agent：读写工具（GIS 操作、文件生成）→ 用标准模型
  - DRL 优化 Agent：计算密集型工具 → 限制调用次数
  - 报告生成 Agent：写工具 + 可视化工具 → 用擅长文本的模型
- **工具白名单是安全边界**：防止分析 Agent 误调用数据删除工具

### 模式 6：计划模式 + 审批工作流（Plan Mode + Approval Workflow）

```
┌───────────────────────────────────────────────────────────┐
│                    Plan Mode 工作流                        │
│                                                           │
│  Lead 分配任务                                             │
│      │                                                    │
│      ▼                                                    │
│  Teammate 进入 Plan Mode（只读模式）                       │
│      │                                                    │
│      │  ← 只能使用 Read、Grep、Glob 等只读工具             │
│      │  ← 不能执行 Write、Edit、Bash 等修改操作            │
│      │                                                    │
│      ▼                                                    │
│  Teammate 完成方案设计                                     │
│      │                                                    │
│      ▼                                                    │
│  发送 plan_approval_request 给 Lead                       │
│      │                                                    │
│      ├──► Lead 批准 → Teammate 退出 Plan Mode → 开始实施  │
│      │                                                    │
│      └──► Lead 驳回（附反馈）→ Teammate 修改方案 → 重新提交 │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

**对 GIS Data Agent 的启示**：
- 当前 GIS Agent 的分析流程是"一口气跑完"——用户无法在中途审查分析方案
- **高价值分析应引入"方案确认"环节**：
  - Agent 先生成分析方案（拟采用的方法、数据范围、预期产出）
  - 用户确认后再执行（避免浪费 Token 和时间在错误方向上）
  - 这特别适合 DRL 优化（计算成本高）和治理审计（结果敏感）场景
- 可以利用 Chainlit 的 `cl.AskActionMessage` 实现交互式审批

### 模式 7：Git Worktree 隔离（Code Isolation via Worktrees）

```
主仓库 (./)
    │
    ├── .claude/worktrees/
    │   ├── feature-auth/     # Agent A 的隔离工作区
    │   ├── fix-buffer/       # Agent B 的隔离工作区
    │   └── refactor-viz/     # Agent C 的隔离工作区
    │
    │  每个 worktree = 完整仓库副本 + 独立分支
    │  无修改 → 自动清理
    │  有修改 → 保留分支，用户决定是否合并
```

**机制**：
- 每个 Teammate 可在独立的 Git Worktree 中工作，互不干扰
- 避免多个 Agent 同时编辑同一文件导致冲突
- 适合并行开发场景

**对 GIS Data Agent 的启示**：
- 虽然 GIS Data Agent 不涉及代码修改，但**文件隔离的思想可以迁移到数据处理场景**：
  - 多个分析任务并行时，各自使用独立的临时目录（已通过 UUID 后缀部分实现）
  - 更进一步：每个分析任务有独立的"工作空间"（working directory），包含输入数据副本、中间结果、最终输出
  - 任务完成后，仅保留最终结果，清理中间文件

### 模式 8：质量门控钩子（Quality Gate Hooks）

CoWork 提供了两个关键的质量控制钩子：

| 钩子 | 触发时机 | Exit Code 2 行为 |
|------|---------|-----------------|
| `TeammateIdle` | Teammate 即将空闲 | stderr 作为反馈发回，Teammate 继续工作 |
| `TaskCompleted` | 任务即将标记完成 | **阻止完成**，stderr 作为反馈要求改进 |

**示例：任务完成前必须通过测试**：

```bash
#!/bin/bash
INPUT=$(cat)
TASK_SUBJECT=$(echo "$INPUT" | jq -r '.task_subject')
npm test 2>&1
if [ $? -ne 0 ]; then
  echo "Tests failed. Fix before marking complete." >&2
  exit 2   # 阻止标记完成
fi
exit 0
```

**对 GIS Data Agent 的启示**：
- 当前缺少分析结果的**自动质量验证**——Agent 说"分析完成"就算完成了
- **应引入分析质量门控**：
  - 空间分析完成后，自动检查输出文件是否有效（非空、CRS 正确、要素数量合理）
  - 可视化完成后，检查地图是否正确渲染（文件大小 > 0、HTML 可解析）
  - 地理编码完成后，检查匹配率是否达标（> 80%）
  - 报告生成后，检查是否包含必要章节（方法、数据、结论）
- 实现方式：在 `_self_correction_after_tool` 中增加后验证逻辑

---

## 四、五种多智能体编排模式

CoWork 实践中沉淀出五种架构模式：

### 模式 A：Leader 模式（层级分配）

```
         ┌──────────┐
         │   Lead   │ ← 分解任务、分配、监督
         └────┬─────┘
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
 ┌──────┐ ┌──────┐ ┌──────┐
 │Worker│ │Worker│ │Worker│ ← 各自独立执行
 │  A   │ │  B   │ │  C   │
 └──────┘ └──────┘ └──────┘
```

**适用场景**：标准团队工作流，Lead 全局把控
**GIS 类比**：Planner Agent 分配"数据获取"、"空间分析"、"可视化"给不同 Worker

### 模式 B：Swarm 模式（自组织群体）

```
  ┌──────────────────────────────┐
  │       共享任务池               │
  │  [Task1] [Task2] [Task3] ... │
  └──────┬───────┬───────┬───────┘
         │       │       │
         ▼       ▼       ▼
      ┌──────┐┌──────┐┌──────┐
      │Agent ││Agent ││Agent │ ← 自行领取、自行执行
      │  A   ││  B   ││  C   │
      └──────┘└──────┘└──────┘
```

**适用场景**：大规模并行执行，任务间独立
**GIS 类比**：批量地理编码——100 个地址分给 N 个 Agent 并行处理

### 模式 C：Pipeline 模式（流水线）

```
  [Task 1] ──完成──► [Task 2] ──完成──► [Task 3]
  数据获取            空间处理            可视化
     │                   │                  │
   Agent A            Agent B            Agent C
```

**适用场景**：有严格前后依赖的工作流
**GIS 类比**：当前 SequentialAgent 的增强版——依赖自动解锁

### 模式 D：Council 模式（多视角评审）

```
         ┌──────────────┐
         │   评审议题     │
         └──────┬───────┘
                │
      ┌─────────┼─────────┐
      ▼         ▼         ▼
   ┌──────┐ ┌──────┐ ┌──────┐
   │专家 A│ │专家 B│ │专家 C│
   │数据质│ │方法论│ │业务  │
   │量视角│ │视角  │ │视角  │
   └──┬───┘ └──┬───┘ └──┬───┘
      │        │        │
      └────────┼────────┘
               ▼
         ┌──────────┐
         │ 综合决策   │
         └──────────┘
```

**适用场景**：架构决策、代码审查、方案评估
**GIS 类比**：选址评估——从交通、人口、商业、环境多个维度独立评估后综合

### 模式 E：Watchdog 模式（质量监控）

```
  ┌──────────┐
  │ 执行 Agent│ ←──── 正常工作
  └────┬─────┘
       │ 每完成一个任务
       ▼
  ┌──────────┐
  │ Watchdog │ ←──── 通过 Hook 自动检查
  │  Agent   │
  └────┬─────┘
       │
       ├── 通过 → 任务标记完成
       └── 不通过 → 反馈 + 要求修改
```

**适用场景**：CI/CD 自动化、质量强制
**GIS 类比**：数据治理流水线——每步完成后自动检查数据完整性和合规性

---

## 五、关键最佳实践提炼

### 5.1 任务设计最佳实践

| 原则 | CoWork 的做法 | GIS Data Agent 的应用 |
|------|--------------|---------------------|
| **适度粒度** | 每个 Teammate 5-6 个任务 | 分析任务拆分为可独立验证的步骤（不过细也不过粗） |
| **清晰交付物** | 每个任务有明确的产出（一个函数、一个测试文件） | 每步产出明确文件（Shapefile、CSV、HTML 地图） |
| **ID 顺序执行** | 优先处理低 ID 任务（前序任务往往为后续提供上下文） | 保持分析流程的逻辑顺序 |
| **依赖显式化** | `addBlocks` / `addBlockedBy` 明确声明 | 分析步骤间的依赖关系应可配置而非硬编码 |

### 5.2 团队规模最佳实践

| 场景 | CoWork 建议 | GIS Data Agent 的映射 |
|------|------------|---------------------|
| **简单分析** | 单 Agent 即可 | 单个 Pipeline（当前模式） |
| **标准分析** | 3 个 Teammate | 数据获取 + 空间分析 + 可视化/报告 |
| **复杂分析** | 3-5 个 Teammate | + 数据质量检查 + 多源数据融合 |
| **核心原则** | "3 个专注的 Teammate 胜过 5 个分散的" | 宁可少而精，不要多而杂 |

### 5.3 成本优化最佳实践

```
                    CoWork 的成本分层策略

  ┌─────────────────────────────────────────────────┐
  │  Lead Agent        →  Opus（最强模型）           │
  │  决策、协调、综合     花费高但调用次数少           │
  ├─────────────────────────────────────────────────┤
  │  Worker Agents     →  Sonnet（性价比模型）        │
  │  具体执行任务         花费适中，主力执行           │
  ├─────────────────────────────────────────────────┤
  │  Explore Agents    →  Haiku（快速便宜模型）       │
  │  搜索、浏览、探索     花费极低，频繁调用           │
  └─────────────────────────────────────────────────┘

  关键: 先用 Plan Mode（只读、便宜）确定方案，
       再用 Execute Mode（读写、贵）并行执行
```

**对 GIS Data Agent 的启示**：
- 当前所有 Agent 统一使用 Gemini 2.5 Flash——无差异化
- **应引入模型分层策略**：
  - Router / Planner：使用 Flash（快速分类/调度）✓ 已实现
  - 数据分析 Agent：使用 Pro（复杂推理）
  - 数据探索 Agent：使用 Flash（简单描述）
  - 报告生成 Agent：使用 Pro（高质量文本）
- Gemini 模型族支持这种分层：Flash Lite < Flash < Pro

### 5.4 上下文管理最佳实践

| CoWork 的做法 | 原因 | GIS Data Agent 的应用 |
|--------------|------|---------------------|
| Teammate **不继承** Lead 的对话历史 | 避免上下文污染，降低 Token 消耗 | 子 Agent 应只接收与其任务相关的上下文 |
| CLAUDE.md 自动加载到所有 Teammate | 共享项目级知识 | `prompts.yaml` 充当共享知识库 ✓ 已实现 |
| 任务 description 包含完整需求 | Teammate 自包含，无需回问 | 每个 Agent 的 instruction 应包含足够的任务背景 |
| Spawn prompt 需详细 | 首次进入无额外上下文 | Dynamic Planner 调度子 Agent 时应注入分析需求摘要 |

### 5.5 文件冲突预防

| CoWork 的做法 | GIS Data Agent 的应用 |
|--------------|---------------------|
| 任务拆分使每个 Teammate 操作不同文件 | 每个 Agent 生成不同前缀的输出文件 ✓ 已实现（UUID 后缀） |
| 使用 Worktree 隔离 | 并行分析任务使用独立临时目录 |
| 禁止两个 Teammate 编辑同一文件 | 同一 GeoDataFrame 不应被两个 Agent 同时操作 |

---

## 六、与现有标杆的对照

### 6.1 三维对照表（更新版）

| 设计维度 | OpenClaw (个人) | OpenAI Frontier (企业) | Claude CoWork (协作) | GIS Data Agent 应借鉴 |
|---------|----------------|----------------------|---------------------|---------------------|
| **核心创新** | 消息即界面 | 企业 AI 治理 | **多 Agent 自组织协作** | 从固定流水线到动态任务图 |
| **协调模型** | 单 Agent 独立 | 集中式编排 | **去中心化 + 共享任务列表** | 引入任务依赖 DAG |
| **Agent 通信** | N/A | Agent→平台→Agent | **P2P 直接通信** | Agent 间消息机制 |
| **任务管理** | 用户手动 | 工作流引擎 | **文件系统任务看板** | 分析任务持久化 + 状态追踪 |
| **质量控制** | 无 | 实时评分 | **质量门控钩子** | 分析结果后验证 |
| **隔离机制** | Docker 容器 | 权限沙箱 | **Git Worktree** | 分析任务工作空间隔离 |
| **审批流程** | 无 | 企业审批链 | **Plan Mode + 审批** | 高价值分析方案确认 |
| **成本管理** | 无（教训） | 企业计费 | **模型分层 + Plan先行** | Token 预算分层 ✓ 部分实现 |

### 6.2 CoWork 的独特贡献

相较 OpenClaw 和 Frontier，CoWork 带来了**三个全新维度**：

1. **动态任务编排** — 不是预定义 Pipeline，而是运行时创建任务依赖图
2. **Agent 间直接通信** — 不经过中心调度器，Teammate 之间可以直接对话
3. **质量门控钩子** — 任务完成前的自动验证机制

---

## 七、GIS Data Agent 架构升级建议

基于 CoWork 分析，提出 v5.0 架构升级方向：

### 7.1 核心架构变更

```
┌───────────────────────────────────────────────────────────────┐
│                                                               │
│   GIS Data Agent v4.0 (当前)     →    v5.0 (CoWork 启发)      │
│                                                               │
│   ┌────────────┐                    ┌────────────┐            │
│   │ 固定 3 条   │                    │ Dynamic    │            │
│   │ Sequential  │                    │ Task Graph │            │
│   │ Pipeline    │                    │ (DAG)      │            │
│   └────────────┘                    └────────────┘            │
│                                                               │
│   ┌────────────┐                    ┌────────────┐            │
│   │ Dynamic    │       →            │ Planner +  │            │
│   │ Planner    │                    │ Dependency  │            │
│   │ (串行调度)  │                    │ Resolver   │            │
│   └────────────┘                    └────────────┘            │
│                                                               │
│   ┌────────────┐                    ┌────────────┐            │
│   │ 所有 Agent │                    │ 模型分层   │            │
│   │ 同一模型   │        →           │ Flash/Pro  │            │
│   └────────────┘                    │ 按职责配置  │            │
│                                     └────────────┘            │
│                                                               │
│   ┌────────────┐                    ┌────────────┐            │
│   │ 无分析方案 │                    │ Plan Mode  │            │
│   │ 确认环节   │        →           │ + 用户审批  │            │
│   └────────────┘                    └────────────┘            │
│                                                               │
│   ┌────────────┐                    ┌────────────┐            │
│   │ 自纠错     │                    │ 自纠错 +   │            │
│   │ (3次重试)  │        →           │ 质量门控   │            │
│   └────────────┘                    │ (后验证)   │            │
│                                     └────────────┘            │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 7.2 建议的实施优先级

| 优先级 | 升级项 | CoWork 灵感来源 | 实施复杂度 | 预期收益 |
|:------:|--------|----------------|:---------:|---------|
| **P0** | 分析方案确认（Plan Mode） | Plan Mode + Approval | 低 | 避免无效分析，提升用户信任 |
| **P0** | 分析结果后验证（Quality Gate） | TaskCompleted Hook | 低 | 提升输出质量，减少无效结果 |
| **P1** | 模型分层策略 | Agent 类型特化 | 中 | 降低 Token 成本 20-40% |
| **P1** | Agent 间消息/上下文传递增强 | P2P SendMessage | 中 | 上游发现影响下游决策 |
| **P1** | 分析任务持久化 | 文件系统即数据库 | 中 | 支持任务恢复、历史追溯 |
| **P2** | 并行任务 DAG 调度 | Task Dependency Graph | 高 | 复杂分析速度提升 2-3x |
| **P2** | 工具权限白名单 | Agent Tool Isolation | 中 | 安全隔离、防误操作 |
| **P3** | Multi-Agent 并行执行 | Agent Teams 完整实现 | 高 | 大规模分析、批处理场景 |

### 7.3 P0 实施方案速写

#### 7.3.1 分析方案确认（Plan Mode）

```python
# app.py 中，在 pipeline 执行前插入方案确认环节
async def confirm_analysis_plan(intent, user_prompt, data_profile):
    """高价值分析前的方案确认"""
    plan = await generate_analysis_plan(intent, user_prompt, data_profile)

    actions = [
        cl.Action(name="approve", payload={"plan": plan}, label="✓ 执行此方案"),
        cl.Action(name="modify", payload={"plan": plan}, label="✎ 修改方案"),
        cl.Action(name="cancel", payload={}, label="✗ 取消"),
    ]

    response = await cl.AskActionMessage(
        content=f"**分析方案预览**\n\n{plan}\n\n确认执行？",
        actions=actions
    ).send()

    return response
```

#### 7.3.2 分析结果后验证（Quality Gate）

```python
# agent.py 中，增强 _self_correction_after_tool
def _quality_gate(tool, args, tool_context, result):
    """工具执行后的质量门控"""
    if isinstance(result, dict) and "error" not in str(result):
        # 检查输出文件
        output_path = result.get("output_path", "")
        if output_path and output_path.endswith((".shp", ".geojson", ".gpkg")):
            gdf = gpd.read_file(output_path)
            if len(gdf) == 0:
                return {"error": "输出文件为空，请检查输入数据和分析参数",
                        "_correction_hint": "输出 0 条记录，可能是筛选条件过严或数据范围不匹配"}
            if gdf.geometry.is_empty.any():
                return {"warning": f"输出中有 {gdf.geometry.is_empty.sum()} 条空几何记录"}
    return None  # 通过，不修改结果
```

---

## 八、从 CoWork 提炼的产品设计原则

### 原则 1：显式优于隐式（来自 P2P 通信设计）

> **Agent 之间的信息传递必须是显式的、可追踪的。**

CoWork 的核心设计：Teammate 的纯文本输出对其他 Agent **不可见**，只有 `SendMessage` 才能传递信息。这确保了：
- 每条信息都有明确的发送者和接收者
- 通信可审计、可回溯
- 避免信息在隐式传播中丢失或失真

**对 GIS Data Agent 的要求**：Agent 间不应依赖"碰巧在同一个 Session.state 里"来传信息，而应有明确的数据交接协议。

### 原则 2：先规划再执行（来自 Plan Mode）

> **复杂分析应先用低成本模式制定方案，再用高成本模式执行。**

CoWork 的 Plan Mode 让 Agent 在只读环境中充分探索，方案确认后才开始修改。这不仅节省成本，更重要的是**提升了用户对结果的可预期性**。

**对 GIS Data Agent 的要求**：特别是 DRL 优化和大范围空间分析，应先生成分析方案（预计用时、预计 Token 消耗、拟采用方法）供用户确认。

### 原则 3：任务是一等公民（来自 Task 七原语）

> **"任务"不是 Agent 的内部概念，而是一个独立的、可查询的、有生命周期的实体。**

CoWork 将每个任务持久化为独立 JSON 文件，有状态机（pending → in_progress → completed）、有依赖关系、有责任人。这使得：
- 外部可观测任务进度
- 任务可中断和恢复
- 多个 Agent 可并发操作不同任务

**对 GIS Data Agent 的要求**：分析任务不应只是"一次函数调用"，而应有独立的生命周期管理——创建、执行、验证、归档。

### 原则 4：成本随职责分层（来自 Agent 类型特化）

> **不是所有 Agent 都需要最强的模型和最全的工具。**

CoWork 让探索用 Haiku、执行用 Sonnet、决策用 Opus。这不是妥协，而是**正确匹配资源与需求**。

**对 GIS Data Agent 的要求**：数据探索用 Flash Lite，空间分析用 Flash，报告生成和规划用 Pro。

### 原则 5：质量是可编程的（来自 Quality Gate Hooks）

> **分析质量不应依赖 LLM 的"自觉"，而应通过编程化的检查点强制保证。**

CoWork 的 `TaskCompleted` Hook 可以在任务完成前执行任意脚本——测试不通过就不准标记完成。这是**质量保证从"期望"到"强制"的范式转变**。

**对 GIS Data Agent 的要求**：每个 GIS 工具执行后都应有确定性的验证（输出非空、CRS 一致、面积/长度在合理范围内），而不是仅靠 LLM 判断"结果看起来对"。

---

## 九、MVP 功能优先级更新（综合三份标杆分析）

| 优先级 | 功能 | 灵感来源 | 状态 |
|:------:|------|---------|:----:|
| **P0** | 自然语言 → 地图可视化 | OpenClaw | ✅ 已实现 |
| **P0** | 数据上传 + 自动空间分析 | — | ✅ 已实现 |
| **P0** | 多轮对话式空间探索 | OpenClaw | ✅ 已实现 |
| **P0** | 实时操作反馈/进度指示 | OpenClaw 教训 | ✅ 已实现 |
| **P0** | Token 消费监控与预算上限 | OpenClaw 教训 | ✅ 已实现 |
| **P0 新增** | 分析方案确认（Plan Mode） | **CoWork** | 🔲 待实现 |
| **P0 新增** | 分析结果质量门控 | **CoWork** | 🔲 待实现 |
| **P1** | 空间记忆（区域/偏好/历史） | OpenClaw | ✅ 已实现 |
| **P1** | 分析过程可解释/可回溯 | Frontier | 部分实现 |
| **P1** | 空间分析工具集 | — | ✅ 已实现 |
| **P1 新增** | 模型分层策略 | **CoWork** | 🔲 待实现 |
| **P1 新增** | Agent 间上下文传递增强 | **CoWork** | 🔲 待实现 |
| **P1 新增** | 分析任务持久化与恢复 | **CoWork** | 🔲 待实现 |
| **P2** | 空间语义层（企业版） | Frontier | 🔲 待实现 |
| **P2** | Agent 权限与审计（企业版） | Frontier | 部分实现 |
| **P2 新增** | 并行任务 DAG 调度 | **CoWork** | 🔲 待实现 |
| **P2 新增** | 工具权限白名单 | **CoWork** | 🔲 待实现 |
| **P2** | 分析模板市场 | OpenClaw | 🔲 待实现 |
| **P3** | 微信/飞书/钉钉 Bot 入口 | OpenClaw | 🔲 待实现 |
| **P3** | 私有化部署 + 本地模型 | OpenClaw + Frontier | 🔲 待实现 |
| **P3 新增** | Multi-Agent 并行执行 | **CoWork** | 🔲 待实现 |

---

## 十、竞争定位更新

在三份标杆分析之后，GIS Data Agent 的竞争定位矩阵新增"协作编排"维度：

```
  GIS/空间能力强 ▲
                │
    Esri        │              ★ GIS Data Agent
    ArcGIS AI   │              (你的目标定位)
                │              — 空间能力 + Agent 能力
    CARTO       │              — 动态编排 + 质量门控
    Agentic GIS │              — 多 Agent 协作分析
                │
  Google Earth  │
  + Gemini      │
                │
  ──────────────┼──────────────────────────────────► Agent 能力强
                │
    Power BI    │    Databricks
    Copilot     │                  ┌──────────────┐
                │                  │ Claude CoWork│
    Tableau AI  │    Julius AI     │(多Agent协作  │
                │                  │ 标杆，无GIS) │
                │    Powerdrill    └──────────────┘
                │    Bloom          ┌─────────────┐
                │                   │  OpenAI     │
                │                   │  Frontier   │
                │    ┌───────────┐  └─────────────┘
                │    │ OpenClaw  │
                │    │(个人Agent)│
                │    └───────────┘
  GIS/空间能力弱 │

  说明:
  ★ = GIS Data Agent 目标定位（唯一占据右上角的产品）
  CoWork 的多 Agent 协作编排能力最强，但无 GIS/空间能力
  → GIS Data Agent 可以将 CoWork 的协作编排模式引入 GIS 垂直领域
```

---

## 十一、总结：从 CoWork 到行动

| 维度 | CoWork 的最佳实践 | GIS Data Agent 的行动 |
|------|------------------|---------------------|
| **编排** | 七原语动态任务图 | 从固定 Pipeline 演进到 DAG 任务调度 |
| **通信** | P2P 消息 + 广播抑制 | 增强 Agent 间上下文传递机制 |
| **质量** | Quality Gate Hooks | 分析结果后验证 + 输出文件检查 |
| **审批** | Plan Mode + 用户确认 | 高价值分析前的方案预览 |
| **成本** | 模型分层（Opus/Sonnet/Haiku） | Gemini Pro/Flash/Flash Lite 按职责配置 |
| **隔离** | Git Worktree | 分析任务独立工作空间 |
| **持久化** | 文件系统任务看板 | 分析任务状态持久化到 PostgreSQL |

> **核心结论**：CoWork 证明了"多个专注的 Agent 协作 > 一个全能的 Agent 独立工作"的架构范式。对 GIS Data Agent 而言，最大的启发不是"也做多 Agent 并行"（这需要大量工程投入），而是从 CoWork 中提取**可立即落地的设计模式**——Plan Mode 方案确认、Quality Gate 质量门控、模型分层成本优化——这些都可以在现有 ADK 架构上低成本实现，立竿见影地提升产品质量和用户体验。

---

## 来源

- [Orchestrate teams of Claude Code sessions — Official Docs](https://code.claude.com/docs/en/agent-teams)
- [Create custom subagents — Official Docs](https://code.claude.com/docs/en/sub-agents)
- [Hooks reference — Official Docs](https://code.claude.com/docs/en/hooks)
- [Introducing Cowork — Claude Blog](https://claude.com/blog/cowork-research-preview)
- [Getting started with Cowork — Help Center](https://support.claude.com/en/articles/13345190-getting-started-with-cowork)
- [Introducing Claude Opus 4.6 — Anthropic](https://www.anthropic.com/news/claude-opus-4-6)
- [Building a C Compiler with Agent Teams — Anthropic Engineering](https://www.anthropic.com/engineering/building-c-compiler)
- [Claude Code Agent Teams: The Complete Guide 2026](https://claudefa.st/blog/guide/agents/agent-teams)
- [From Tasks to Swarms: Agent Teams in Claude Code](https://alexop.dev/posts/from-tasks-to-swarms-agent-teams-in-claude-code/)
- [Claude Code's Hidden Multi-Agent System](https://paddo.dev/blog/claude-code-hidden-swarm/)
- [Claude Code Swarms — Addy Osmani](https://addyosmani.com/blog/claude-code-agent-teams/)
- [Claude Code's Custom Agent Framework](https://dev.to/therealmrmumba/claude-codes-custom-agent-framework-changes-everything-4o4m)
- [How to Set Up and Use Claude Code Agent Teams](https://darasoba.medium.com/how-to-set-up-and-use-claude-code-agent-teams-and-actually-get-great-results-9a34f8648f6d)
- [SitePoint: Claude Code Agent Teams Setup & Guide](https://www.sitepoint.com/anthropic-claude-code-agent-teams/)
