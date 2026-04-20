# 智能体别名管理 + 拓扑 Tab 优化 设计文档

> Date: 2026-04-20
> Branch: feat/v12-extensible-platform
> Scope: 新增 AgentsTab（别名管理）+ 优化 TopologyTab（节点精简 + 详情面板增强）

## 1. 智能体别名管理（AgentsTab）

### 1.1 数据模型

新建 `agent_aliases` 表（migration 064）：

```sql
CREATE TABLE IF NOT EXISTS agent_aliases (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(100) NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    display_name VARCHAR(100),
    pinned BOOLEAN DEFAULT false,
    hidden BOOLEAN DEFAULT false,
    user_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(handle, user_id)
);
CREATE INDEX idx_agent_aliases_user ON agent_aliases(user_id);
CREATE INDEX idx_agent_aliases_handle ON agent_aliases(handle);
```

### 1.2 后端 API

模块：`data_agent/api/agent_management_routes.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agents/mention-targets` | 返回当前用户可见的 @mention 目标（合并 registry + aliases + pinned/hidden） |
| PUT | `/api/agents/{handle}/alias` | 设置别名和显示名 `{ aliases: [...], display_name: "..." }` |
| PUT | `/api/agents/{handle}/pin` | 切换 pinned 状态 |
| PUT | `/api/agents/{handle}/hide` | 切换 hidden 状态 |

### 1.3 mention_registry.py 改动

`build_registry()` 返回时合并 DB 中的 `display_name`、`pinned`、`hidden` 字段到每个 target dict。

`lookup()` 匹配逻辑扩展：
1. 精确匹配 handle（不区分大小写）
2. 精确匹配 display_name
3. 匹配 aliases 数组中任一项

匹配优先级：handle > display_name > alias。

当 `hidden=true` 时，该目标不出现在 @ dropdown 列表中，但仍可通过精确输入 handle 调用（不阻断，只是不推荐）。

### 1.4 前端 AgentsTab

文件：`frontend/src/components/datapanel/AgentsTab.tsx`

**布局**：
- 顶部栏：搜索框 + 分组筛选按钮（All / Pipeline / Sub-Agent / Skill / Custom）
- 主体：卡片列表，每张卡片一行
- 卡片内容：handle（灰色小字）、display_name（主标题）、类型 badge、别名 tags
- 卡片操作：点击展开编辑区（别名输入框、显示名输入框、pin toggle、hide toggle）
- 排序：pinned 置顶 → 按类型分组 → 字母序

**交互**：
- 搜索支持 handle / display_name / alias 模糊匹配
- 编辑后自动保存（debounce 500ms）
- pin/hide 即时生效

### 1.5 ChatPanel @ dropdown 联动

ChatPanel 的 autocomplete 数据源改为 `/api/agents/mention-targets`（替代当前的 `/api/chat/mention-targets`）。dropdown 列表：
- 显示 display_name（有则用，无则 handle）
- 副文本显示 description
- pinned 项置顶
- hidden 项不显示

匹配输入时同时搜索 handle + display_name + aliases。

---

## 2. 拓扑 Tab 优化（TopologyTab）

### 2.1 节点精简

**AgentNode 组件改动**：
- 保留：类型 badge（颜色标签）+ 名称
- 移除：model 文字、tools 标签列表、instruction_snippet
- `minWidth` 从 140 缩小到 100
- padding 从 `8px 12px` 缩小到 `6px 10px`

**ToolsetNode**：保持不变（已经足够简洁）。

### 2.2 布局参数调整

- `COL_WIDTH`：280 → 200
- `ROW_HEIGHT`：90 → 75

### 2.3 详情面板增强

点击节点后下方面板展示：

| 区域 | 内容 |
|------|------|
| 标题行 | 名称 + 类型 badge + 所属 Pipeline 标签 + 关闭按钮 |
| 基本信息 | 类型（中文）、模型名称 |
| 工具集 | tools 列表，每项显示工具集名 + 工具数量 |
| 子节点 | children 列表，可点击跳转（fitView 到该节点并高亮） |
| 指令摘要 | instruction_snippet，默认折叠，点击展开 |
| @mention 状态 | 是否可 @ 调用 + 别名（如果有） |

面板高度从 `maxHeight: 160` 增加到 `maxHeight: 200`。

### 2.4 动态数据增强

**刷新按钮**：legend 栏增加刷新按钮，点击重新 fetch `/api/agent-topology`。

**API 响应扩展**（`topology_routes.py`）：
- 每个 agent 增加 `mentionable: boolean`（是否为 @mention 目标）
- 每个 agent 增加 `pipeline_label: string`（所属 pipeline 中文名）
- 增加 Custom Skill agents 到拓扑数据（从 `custom_skills.list_custom_skills()` 提取）

### 2.5 子节点点击跳转

详情面板中的 children 列表项可点击，点击后：
1. `setCenter()` 将视图平移到目标节点
2. 目标节点短暂高亮（border 闪烁 1.5s）

---

## 3. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `data_agent/migrations/064_agent_aliases.py` | 新建 | 建表 |
| `data_agent/api/agent_management_routes.py` | 新建 | 4 个 REST 端点 |
| `data_agent/mention_registry.py` | 修改 | 别名匹配 + DB 合并 |
| `data_agent/api/topology_routes.py` | 修改 | 增加 mentionable/pipeline_label/custom skills |
| `frontend/src/components/datapanel/AgentsTab.tsx` | 新建 | 智能体管理 UI |
| `frontend/src/components/datapanel/TopologyTab.tsx` | 修改 | 节点精简 + 详情增强 + 刷新 |
| `frontend/src/components/datapanel/index.ts` | 修改 | 注册 AgentsTab |
| `frontend/src/components/ChatPanel.tsx` | 修改 | dropdown 数据源切换 |
| `data_agent/test_agent_management.py` | 新建 | 别名 CRUD + lookup 测试 |

---

## 4. 不做的事

- 不做别名的全局共享（每个用户独立设置自己的别名）
- 不做拓扑的分层折叠展开（保持一次性展示全貌）
- 不给编排节点（ParallelAgent、LoopAgent）设别名
- 不做别名冲突检测跨用户（同一用户内别名唯一即可）
