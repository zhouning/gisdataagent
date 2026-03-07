# Roadmap v8.0: 用户自助式开放平台

> **Vision**: 从"AI 驱动的 GIS 分析平台"升级为"用户可自主扩展的空间智能开放平台"。
>
> **Philosophy**: "工具即生态，数据即资产，协作即决策，扩展即插件。"

---

## 当前状态 (v7.0 Baseline)

| 指标 | 数值 |
|------|------|
| 测试覆盖 | 1330+ tests, 62 test files |
| 工具集 | 19 BaseToolset, 5 SkillBundle, 113+ 工具 |
| REST API | 31 endpoints |
| 前端组件 | 9 React components |
| 管道 | 3 固定 + 1 动态规划器 (7 子智能体) |
| 数据库迁移 | 19 SQL scripts |
| 融合引擎 | ~2100 行，10 策略，5 模态 |
| 知识图谱 | ~625 行，7 实体类型 |
| 部署方式 | Docker / K8s / 本地 |
| CI | GitHub Actions (test + build + evaluate) |

---

## 已完成版本回顾

| 版本 | 功能集 | 状态 |
|------|--------|------|
| v1.0–v3.2 | 基础 GIS、PostGIS、语义层、多管道架构 | ✅ 完成 |
| v4.0 | 前端三面板 SPA、可观测性、CI/CD、技能包、协作标注 | ✅ 完成 |
| v4.1 | 会话持久化、管道进度可视化、错误恢复、数据预览、i18n | ✅ 完成 |
| v5.1 | MCP 工具市场（引擎 + 前端展示 + 管线过滤） | ✅ 完成 |
| v5.2 | 多模态输入（图片理解 + PDF 解析 + 语音输入） | ✅ 完成 |
| v5.3 | 3D 空间可视化（deck.gl + MapLibre + 2D/3D 切换） | ✅ 完成 |
| v5.4 | 工作流编排（引擎 + Cron + Webhook） | ✅ 完成 |
| v5.5 | 多模态数据融合引擎 MMFE（5 模态、10 策略、语义匹配） | ✅ 完成 |
| v5.6 | MGIM 启发增强（模糊匹配、单位转换、数据感知策略、多源编排） | ✅ 完成 |
| v6.0 | 融合增强（栅格重投影、点云、流数据、语义增强、质量验证） | ✅ 完成 |
| v7.0 | 向量嵌入匹配、LLM 策略路由、地理知识图谱、分布式计算 | ✅ 完成 |

---

## v7.1 — 稳定性增强 + 自助化起步

**目标**: 修复已知问题，为用户自助扩展打下基础。
**周期**: 2-3 周

### 7.1.1 MCP 服务器管理 UI ⭐ 高优先级

**现状**: MCP 引擎已完成（3 种传输协议、4 个 API 端点），但前端仅只读展示，管理员 toggle/reconnect API 未接入 UI。

**方案**:
- 前端 ToolsView 增加"添加自定义 MCP 服务器"表单（URL/命令、描述、管线选择）
- 管理员可在 UI 中 toggle/reconnect
- 新增 CRUD API：`POST/PUT/DELETE /api/mcp/servers`
- 配置持久化到数据库（当前仅 YAML 静态文件）
- 热加载：DB 变更后无需重启应用

**影响范围**: `frontend_api.py`, `mcp_hub.py`, `DataPanel.tsx`, 新迁移脚本

### 7.1.2 WorkflowEditor 组件修复 ⭐ 高优先级

**现状**: `DataPanel.tsx` import 了 `WorkflowEditor` 组件但**文件不存在**，点击"编辑"或"新建工作流"会运行时崩溃。`@xyflow/react` v12 已安装但未使用。

**方案**:
- 创建 `WorkflowEditor.tsx`，基于 React Flow 实现基础编辑器
- 三种节点类型：DataInput、Pipeline、Output
- 属性面板：选择管线类型、编辑 Prompt、配置参数
- 导出 `graph_data` JSON 存入已预留的 JSONB 字段

**影响范围**: 新建 `WorkflowEditor.tsx`, `DataPanel.tsx`

### 7.1.3 用户自定义分析视角（轻量 Skills）

**现状**: Agent 提示词硬编码在 YAML 中，模块加载时一次性创建，运行时不可修改。

**方案**:
- 利用 ADK `global_instruction` 注入用户自定义上下文
- 存入 `agent_memories` 表（`memory_type="custom_focus"`），无需新建 schema
- 前端 UserSettings 增加"我的分析视角"文本区域
- 示例："我是林业规划师，重点关注生态红线和森林覆盖率"

**影响范围**: `agent.py`, `app.py`, `UserSettings.tsx`, ~50 行改动

---

## v7.5 — MCP 市场 + 技能组合

**目标**: 完善 MCP 自助化，开放工具组合能力。
**周期**: 3-4 周

### 7.5.1 MCP 服务器安全加固

- 配置输入校验（防止命令注入）
- Auth token 加密存储（非明文 YAML）
- 操作审计日志（谁添加/删除了服务器）
- 用户配额（每用户最多 N 个自定义服务器）
- 连接前自动测试（Test Connection 按钮）

### 7.5.2 用户自定义技能包组合

**现状**: `skill_bundles.py` 定义了 5 个命名工具组合，但实际未在 Agent 装配中使用。

**方案**:
- 新建 `agent_custom_bundles` 表（用户 ID + 选择的 bundle 列表）
- 前端增加 SkillBuilder 面板：从 5 个 bundle 中勾选组合
- Planner Agent 根据用户配置动态调整可用工具集
- 复用现有 `build_toolsets_for_intent()` 逻辑

**影响范围**: `skill_bundles.py`, `agent.py`, `frontend_api.py`, `DataPanel.tsx`, 新迁移脚本

### 7.5.3 per-User MCP 服务器隔离

- 数据库中 MCP 配置增加 `user_id` 外键
- 全局服务器（admin 创建）对所有用户可见
- 用户私有服务器仅本人可见
- 工具发现按用户范围过滤

---

## v8.0 — 完整自定义 Skills + 可视化工作流

**目标**: 用户可自定义 Agent 专家身份和多步工作流。
**周期**: 6-8 周

### 8.0.1 数据库驱动的自定义 Skills

**现状评估**:
- Agent 在模块加载时创建，提示词烘焙进实例 → 需改为 Agent 工厂模式
- 意图路由硬编码 4 种 → 需扩展支持自定义 intent trigger
- 无 `agent_custom_skills` 表 → 需新建 schema

**方案**:
```sql
CREATE TABLE agent_custom_skills (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    team_id TEXT,                          -- 团队级共享（可选）
    skill_name TEXT NOT NULL,              -- 如 "urban_planner"
    base_agent_type TEXT NOT NULL,         -- general/optimization/governance
    custom_instruction TEXT NOT NULL,      -- 自定义系统提示词
    custom_tools TEXT[] DEFAULT '{}',      -- 工具白名单
    trigger_keywords TEXT[] DEFAULT '{}',  -- 意图触发关键词
    model_config JSONB DEFAULT '{}',       -- 模型、温度等
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

- `agent.py` 重构：静态 Agent → 工厂函数 `_make_custom_agent(skill_id)`
- `app.py` 路由扩展：`classify_intent()` 先检查用户自定义 skill triggers
- 前端 SkillBuilder：Monaco Editor 编辑提示词 + 工具选择器 + 模型参数
- `@专家名称` 唤起语法支持
- 安全：自定义提示词输入校验（防 LLM 注入），工具白名单（排除 admin/破坏性工具）

### 8.0.2 RAG 私有知识库挂载

**现状**: Vertex AI Search 仅用于 optimization pipeline 的 knowledge_agent。

**方案**:
- 用户上传行业 PDF → 系统创建 RAG 知识库
- 知识库绑定到自定义 Skill
- 运行时动态挂载 `VertexAiSearchTool` 到用户 Agent
- 多租户隔离：每用户/团队独立知识库

### 8.0.3 可视化 DAG 工作流引擎

**现状评估**:
- `workflow_engine.py` 为**线性顺序执行器**，无 `depends_on`/条件分支/并行
- `graph_data` JSONB 字段已预留但未使用
- React Flow 依赖已安装但未 import

**方案**:
- 重构执行引擎：顺序 → DAG 拓扑排序
- 步骤间数据传递：前步输出文件自动注入后步 prompt
- 条件分支节点：基于工具输出的 if/else 判断
- 并行执行：ADK `ParallelAgent` 支持
- React Flow 编辑器增强：条件节点、并行分支、循环节点
- 解析 React Flow JSON → ADK Agent 树动态实例化

### 8.0.4 高级分析引擎

- 时空预测（GWR/GTWR，空间趋势预测）
- 场景模拟（Monte Carlo，空间溢出效应）
- 网络分析（等时圈、最优路径、设施覆盖）

---

## v9.0 — 协同智能 + 边缘计算

**目标**: 从单用户工具进化为多用户协同决策平台。
**周期**: 长期

### 9.1 实时协同编辑
- 多用户同时查看同一地图
- CRDT 冲突解决（类 Figma 模式）
- WebRTC 语音/视频协同

### 9.2 边缘部署 + 离线模式
- ONNX Runtime 本地推理（无需 Gemini API）
- PWA 离线缓存
- 野外巡查：GPS + 拍照 + 本地分析 + 回连同步

### 9.3 数据连接器生态

| 连接器 | 协议 | 用途 |
|--------|------|------|
| WMS/WFS/WMTS | OGC 标准 | 直连地图服务 |
| ArcGIS Online | REST API | ESRI 生态对接 |
| Google Earth Engine | Python API | 遥感大数据 |
| 国土"一张图" | 政务接口 | 规划数据 |
| MQTT | IoT 协议 | 传感器实时接入 |

### 9.4 多 Agent 并行协作
- 多 Agent 并行处理不同区域数据
- ADK `ParallelAgent` 并发派发
- "分别分析 A/B/C 三个区县，汇总对比"

---

## 三层扩展架构全景

```
┌─────────────────────────────────────────────────────────┐
│                 用户自助式扩展平台                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  第三层：可视化工作流编排 (v8.0)                           │
│  ┌─────────────────────────────────────────────┐       │
│  │  React Flow 画布 → DAG 拓扑 → ADK Agent 树  │       │
│  │  条件分支 / 并行执行 / 步骤间数据传递          │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第二层：自定义领域专家 Skills (v7.5–v8.0)                │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.1: global_instruction 注入（轻量）       │       │
│  │  v7.5: SkillBundle 组合选择                  │       │
│  │  v8.0: DB 驱动自定义 Agent + RAG 知识库      │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第一层：MCP 工具扩展 (v7.1–v7.5)                        │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.0: 引擎就绪（3 传输协议、工具发现）       │       │
│  │  v7.1: 管理 UI + CRUD API + DB 持久化        │       │
│  │  v7.5: 安全加固 + per-User 隔离              │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  基座：v7.0 已完成能力                                    │
│  19 工具集 · 113+ 工具 · 10 融合策略 · 4 管道 · 31 API   │
└─────────────────────────────────────────────────────────┘
```

---

## 优先级矩阵

```
业务价值 ↑
│
│  ★ v7.1.1 MCP 管理 UI          ★ v8.0.1 自定义 Skills
│  ★ v7.1.2 WorkflowEditor 修复  ★ v8.0.3 DAG 工作流
│  ★ v7.1.3 分析视角注入
│                                 ○ v8.0.2 RAG 知识库
│  ○ v7.5.2 技能包组合            ○ v8.0.4 高级分析
│  ○ v7.5.1 安全加固              ○ v9.x 远期功能
│
└──────────────────────────────────────── 实现复杂度 →
```

## 推荐实施路线

```
Phase 1 (v7.1, 2-3 周) — 修复 + 快速自助化
  ├── 7.1.1 MCP 管理 UI (CRUD API + 前端表单)
  ├── 7.1.2 WorkflowEditor.tsx 创建 (React Flow 基础编辑器)
  └── 7.1.3 用户分析视角注入 (global_instruction)

Phase 2 (v7.5, 3-4 周) — MCP 市场 + 技能组合
  ├── 7.5.1 MCP 安全加固 (校验/加密/审计/配额)
  ├── 7.5.2 自定义技能包组合 (SkillBuilder UI)
  └── 7.5.3 per-User MCP 隔离

Phase 3 (v8.0, 6-8 周) — 完整自定义 + DAG 工作流
  ├── 8.0.1 DB 驱动自定义 Skills (Agent 工厂 + 路由扩展)
  ├── 8.0.2 RAG 私有知识库挂载
  ├── 8.0.3 DAG 工作流引擎 (拓扑排序 + 条件分支)
  └── 8.0.4 高级分析引擎 (GWR/Monte Carlo/网络分析)

Phase 4 (v9.0, 持续迭代) — 协同 + 边缘
  ├── 9.1 实时协同编辑 (CRDT)
  ├── 9.2 边缘部署 + PWA 离线
  ├── 9.3 数据连接器生态
  └── 9.4 多 Agent 并行协作
```

---

## 竞品差异化分析

| 能力维度 | 本平台 (v8.0) | ArcGIS Pro | Julius AI | Carto |
|----------|---------------|------------|-----------|-------|
| NL 交互 | ★★★★★ | ★★☆☆☆ | ★★★★☆ | ★★☆☆☆ |
| GIS 深度 | ★★★★☆ | ★★★★★ | ★☆☆☆☆ | ★★★☆☆ |
| 多模态 | ★★★★☆ | ★★★☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| 用户扩展性 | ★★★★★ (MCP+Skills) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| 开放生态 | ★★★★★ (MCP) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| 私有部署 | ★★★★★ | ★★★★☆ | ☆☆☆☆☆ | ★★☆☆☆ |
| 学习曲线 | 零 (NL) | 高 | 低 | 中 |

**核心壁垒**: "High GIS Capability + High Agent Capability + Open Ecosystem (MCP) + User-Extensible Skills" 四位一体。

---

## 成功指标 (KPIs)

| 指标 | v7.0 实际 | v7.5 目标 | v8.0 目标 |
|------|----------|----------|----------|
| 分析成功率 | > 90% | > 92% | > 95% |
| 首次分析时间 | < 2 min | < 1.5 min | < 1 min |
| MCP 工具接入数 | 1（静态配置） | ≥ 3（自助添加） | ≥ 10 |
| 自定义 Skills 数 | 0 | 束组合可选 | 用户自建 ≥ 5 |
| 工作流复用率 | — | > 20% | > 40% |
| 测试覆盖 | 1330+ tests | 1450+ tests | 1600+ tests |
| REST API 端点 | 31 | 38+ | 45+ |

---

**方案版本**: v2.0
**更新日期**: 2026-03-07
**基于**: `user-self-service-extension-plan.md` 评估结果
