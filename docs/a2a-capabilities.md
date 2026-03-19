# Data Agent A2A (Agent-to-Agent) 能力与应用场景

> A2A 协议让不同 AI Agent 系统之间能够发现彼此、协商能力、协作完成任务。每个 Agent 保持内部实现不透明，通过标准协议交互。

---

## Data Agent 的 A2A 定位

Data Agent 是一个 **GIS 领域的专业 Agent**。在 A2A 生态中，它同时扮演两个角色：

### 作为 Server（被调用）

其他 Agent 请求 Data Agent 执行空间分析：

```
遥感分析 Agent → [A2A] → Data Agent: "对这个区域做土地利用变化检测"
智慧城市 Agent → [A2A] → Data Agent: "分析这5个候选地块的选址适宜性"
环保监测 Agent → [A2A] → Data Agent: "计算这个流域的 NDVI 植被指数"
```

### 作为 Client（调用别人）

Data Agent 调用其他领域的专业 Agent 补充自身能力：

```
Data Agent → [A2A] → 气象 Agent: "获取这个区域近30天降水数据"
Data Agent → [A2A] → 交通 Agent: "计算这些地块到最近高速入口的驾车时间"
Data Agent → [A2A] → 文档审查 Agent: "检查这份土地利用规划报告的合规性"
```

---

## 应用场景

### 场景 1：跨系统智能分析链

```
用户在智慧城市平台提问: "福禄镇适合建一个垃圾处理厂吗？"
    │
    ▼
智慧城市 Agent (编排器)
    ├── [A2A] → Data Agent: "福禄镇的地形坡度和土地利用分布"
    │         → 返回: DEM坡度图 + 用地分类
    ├── [A2A] → 环保 Agent: "福禄镇周边5km的水源保护区"
    │         → 返回: 保护区边界
    ├── [A2A] → 交通 Agent: "候选地块到县城的运输路线"
    │         → 返回: 路线距离和时间
    └── 综合分析 → 用户: "推荐3个候选地块，理由..."
```

Data Agent 只负责它擅长的空间分析，其他领域由专业 Agent 各自完成。

### 场景 2：组织内多 Agent 协作

```
自然资源局内部 Agent 生态:
    ├── Data Agent (空间分析) — 本系统
    ├── 档案 Agent (文档管理)
    ├── 审批 Agent (流程审批)
    └── 统计 Agent (报表生成)

业务流程: "处理一个建设用地审批"
    审批 Agent → [A2A] → Data Agent: "检查这个地块是否在耕地保护范围内"
    Data Agent → 返回: 与永久基本农田的叠加分析结果
    审批 Agent → [A2A] → 档案 Agent: "调取该地块的历史审批记录"
    审批 Agent → 综合判断 → 审批意见
```

### 场景 3：多区域联合分析

```
省级 Agent 需要汇总各市数据:
    省级编排 Agent
    ├── [A2A] → 城市A的 Data Agent: "统计城市A的耕地面积变化"
    ├── [A2A] → 城市B的 Data Agent: "统计城市B的耕地面积变化"
    ├── [A2A] → 城市C的 Data Agent: "统计城市C的耕地面积变化"
    └── 汇总 → 全省耕地变化报告
```

每个城市部署自己的 Data Agent 实例和本地数据，省级 Agent 通过 A2A 协调。

### 场景 4：AI Agent 市场

```
Data Agent 在 Agent 目录中注册:
    Agent Card:
    {
        name: "GIS Data Agent",
        skills: [
            {id: "spatial-analysis", ...},
            {id: "data-governance", ...},
            {id: "land-optimization", ...},
            {id: "visualization", ...},
            {id: "data-fusion", ...},
        ]
    }

任何第三方 Agent 通过 Agent Card 发现 Data Agent 的能力，按需调用空间分析服务。
```

---

## 当前实现状态

### 已实现

| 组件 | 文件 | 说明 |
|------|------|------|
| Agent Card | `a2a_server.py:30-77` | 5 个 skill 描述（空间分析/治理/优化/可视化/融合） |
| 任务执行 | `a2a_server.py:84-144` | 接收文本 → classify_intent → run_pipeline_headless → 返回结果 |
| 服务状态 | `a2a_server.py:154-167` | enabled/uptime/default_role |
| REST API | `frontend_api.py` | `GET /api/a2a/card` + `GET /api/a2a/status` |
| 前端展示 | `AdminDashboard.tsx` | A2A tab 展示 Agent Card + 状态 + 技能列表 |
| 环境控制 | `a2a_server.py:22` | `A2A_ENABLED` 环境变量（默认关闭） |
| 测试 | `test_a2a_server.py` | Agent Card 构建 + 状态 + 路由注册 |

### 缺失（对照 A2A 协议标准）

| 能力 | A2A 标准 | 当前状态 |
|------|---------|---------|
| JSON-RPC 2.0 | 标准通信协议 | 当前用 REST |
| `/.well-known/agent.json` | 标准发现端点 | 只有 `/api/a2a/card` |
| `tasks/send` | 任务提交 | 无（内部函数未暴露为 HTTP） |
| `tasks/get` | 任务查询 | 无 |
| `tasks/cancel` | 任务取消 | 无 |
| `tasks/sendSubscribe` | SSE 流式 | 无（pipeline_runner SSE 可复用） |
| Task 状态机 | submitted→working→completed/failed | 同步执行，无状态机 |
| Push Notifications | 异步回调 | 无 |
| Client 调用 | 调用外部 Agent | 无（ADK v1.27 RemoteA2aAgent 待集成） |
| 服务发现 | Agent 目录/注册中心 | 无 |
| A2A 认证 | OAuth2/API Key | 无专用认证 |
| Artifact 传输 | 文件/结构化数据 | 只返回文本+文件路径 |

### 覆盖率评估：约 15-20%

---

## 实现路线

### Phase 1：Server 合规

- 标准化 Agent Card schema + `/.well-known/agent.json` 路由
- JSON-RPC `tasks/send` 端点 → 异步执行 + Task 状态机
- `tasks/sendSubscribe` SSE 流式（复用 `run_pipeline_streaming`）
- Task 生命周期管理（submitted → working → completed/failed）

### Phase 2：Client 能力

- 集成 ADK v1.27 的 `RemoteA2aAgent`
- Agent 目录：注册/发现外部 Agent
- 前端 UI：浏览外部 Agent、手动调用、查看结果
- Request Interceptors 实现认证和审计

### Phase 3：生态集成

- 认证：OAuth2 / API Key 双模式
- Push Notifications + Webhook 回调
- 多 Agent 编排：Planner 自动选择调用本地或远程 Agent
- 服务发现注册中心

---

*本文档基于 GIS Data Agent v12.0 (ADK v1.27.2) 编写。*
