# GIS Data Agent — Roadmap

**Last updated**: 2026-03-18 &nbsp;|&nbsp; **Current version**: v12.0 &nbsp;|&nbsp; **ADK**: v1.27.2

---

## 已完成 (v12.0, 2026-03-18)

- [x] 能力浏览 Tab (CapabilitiesView) — 内置技能/自定义技能/工具集/用户工具聚合展示
- [x] Custom Skills 前端 CRUD — 创建/编辑/删除自定义 Agent
- [x] User-Defined Tools Phase 1 — 声明式工具模板 (http_call / sql_query / file_transform / chain)
- [x] UserToolset — 用户工具暴露给 ADK Agent
- [x] 多 Agent Pipeline 编排 — WorkflowEditor 支持 Skill Agent 节点 + DAG 执行
- [x] 面板拖拽调整宽度 (240-700px)
- [x] DataPanel Tab 横向滚动
- [x] SEC-1: DB 降级后门移除
- [x] SEC-2: 暴力破解防护 (per-username 5次失败锁定15分钟)
- [x] S-1: app.py 拆分 (intent_router.py + pipeline_helpers.py 提取)
- [x] T-4: 路由器 Token 独立追踪
- [x] F-4: React Error Boundaries (三面板独立错误隔离)
- [x] Knowledge Base 前端 UI (知识库 Tab: CRUD + 文档管理 + 语义搜索)
- [x] Bug fixes: arcpy_tools.py 语法错误, test_knowledge_agent.py, APScheduler 安装, chainlit_zh-CN.md, MCP Hub 状态报告
- [x] 文档同步: CLAUDE.md, MEMORY.md, technical-guide.md, 7 个 DITA 源文件, 2 个预览 HTML
- [x] ADK 升级: v1.26.0 → v1.27.2 (Session Rewind, CredentialManager, OpenTelemetry 增强, list_skills_in_dir)

---

## 短期 (1-2 周)

### 安全加固

- [ ] **SEC-3**: 沙箱路径验证改用 `os.path.realpath()` + `os.path.commonpath()`，防止符号链接绕过 ✅ 已修复
- [ ] **SEC-4**: Custom Skill 指令 Prompt 注入防护增强 — 考虑 LLM 语义验证 + 输出隔离
- [ ] **SEC-5**: ContextVar 默认角色从 `analyst` 改为 `anonymous`，强制显式设置 ✅ 已修复

### 前端质量

- [ ] **F-1**: Props drilling → React Context API 或 Zustand 状态管理
  - 优先提取: mapLayers, mapCenter, mapZoom, layerControl 为 MapContext
  - dataFile, userRole 为 AppContext
- [ ] **F-2**: 移除全局回调 `window.__resolveAnnotation()` / `window.__deleteAnnotation()`，改用事件总线或 Context ✅ 已修复 (CustomEvent)

### 代码质量

- [ ] **T-3**: 评测通过率阈值改为环境变量配置 (`EVAL_THRESHOLD_GENERAL=0.7` 等) ✅ 已修复
- [ ] **S-2**: 模块级全局变量 (`_mcp_started`, `_workflow_scheduler`) 改为 ContextVar 或单例类 ✅ 已修复 (threading.Lock)

---

## 中期 (2-4 周)

### User Tools Phase 2: Python 沙箱

- [ ] `user_tools.py` 新增 `validate_python_code()` — AST 解析 + import 白名单 + 危险函数黑名单
- [ ] `user_tool_engines.py` 新增 `execute_python_sandbox()` — subprocess 隔离执行
  - 超时 30s (max 60s)
  - 受限 builtins
  - 环境变量清洗 (剥离 POSTGRES_PASSWORD, CHAINLIT_AUTH_SECRET, GOOGLE_API_KEY 等)
  - stdout/stderr 捕获，100KB 上限
- [ ] 前端: DataPanel CapabilitiesView 工具表单新增 `python_sandbox` 模板类型，monospace 代码编辑器
- [ ] 安全测试: 禁止 import os.system, subprocess, socket; AST 拒绝 exec/eval/__import__

### 基础设施

- [ ] **S-3**: 引入 Alembic 数据库迁移框架
  - 从现有 17 张表的 `CREATE TABLE IF NOT EXISTS` 生成 initial migration
  - 后续 schema 变更通过 `alembic revision --autogenerate`
- [ ] **S-4**: `frontend_api.py` (2330 行) 按功能域拆分 — 进行中
  - ✅ 创建 `api/` 包 + `helpers.py` (共享 auth) + `bundle_routes.py` (技能包)
  - `api/catalog_routes.py` — 数据目录
  - `api/mcp_routes.py` — MCP Hub
  - `api/workflow_routes.py` — 工作流
  - `api/skill_routes.py` — 技能/工具
  - `api/kb_routes.py` — 知识库
  - `api/admin_routes.py` — 管理端点
  - `api/user_routes.py` — 用户端点
  - 保留 `frontend_api.py` 作为路由注册入口

### 前端架构

- [ ] **F-3**: 单文件 CSS (2400+ 行) → CSS Modules 或 Tailwind CSS
  - 按组件拆分: ChatPanel.module.css, MapPanel.module.css, DataPanel.module.css 等
  - 或引入 Tailwind v4 + CSS-first 配置
- [ ] **WorkflowEditor 增强**:
  - 条件节点可视化编辑 (表达式编辑器)
  - 并行分支自动布局算法
  - 实时执行状态展示 (轮询 `/api/workflows/{id}/runs/{run_id}/status`)
  - 步骤结果预览面板

### 能力完善

- [ ] **Skill Bundles 前端 UI** — 组合编排多个 Skill + Toolset 的可视化界面 ✅ 已完成
  - 后端 API 已就绪 (`/api/bundles` CRUD + `/api/bundles/available-tools`)
  - 前端: bundle 列表、创建/编辑表单、toolset/skill 多选 ✅
- [ ] **Knowledge Base GraphRAG UI** — 知识图谱可视化 ✅ 已完成
  - 后端 API 已就绪 (`/api/kb/{id}/build-graph`, `/api/kb/{id}/graph`, `/api/kb/{id}/entities`)
  - 前端: 图构建按钮、实体/关系列表、图谱搜索 ✅

---

## 长期 (1-3 月)

### 平台生态

- [ ] **工具/技能市场**: 用户发布 Skills/Tools 到共享市场，其他用户一键安装
  - 评分/评论系统
  - 安装计数和热度排序
  - 分类标签 (GIS分析, 数据治理, 遥感, 可视化...)
  - 版本管理 (发布新版、回滚)

### 可观测性

- [ ] **Agent 评测面板**: 前端可视化评测结果、工具调用轨迹、Token 消耗分析
  - 管线级通过率图表
  - 工具调用热力图
  - Token 消耗趋势 (日/周/月)
  - 失败模式聚合分析
- [ ] **E-4**: Prometheus 指标标签基数控制 — tool_name 做聚合或采样
- [ ] **成本控制仪表盘**: 按用户/团队/管线维度展示 Token 消耗趋势、预算预警、模型自动降级

### 可扩展性

- [ ] **E-1**: 知识图谱持久化 — 引入 Neo4j 或 Apache AGE (PostGIS 图扩展)
  - 现有 networkx DiGraph 迁移到图数据库
  - 支持大规模实体关系存储 (>10k 节点)
  - 跨会话知识图谱复用
- [ ] **E-3**: Cron 调度持久化 — APScheduler 改为 DB-backed 或外部调度器 (Celery Beat)
- [ ] **E-5**: 多源融合执行计划优化 — 引入代价估算的查询优化器

### 智能增强

- [ ] **对话记忆增强**: 跨会话长期记忆检索，结合 Knowledge Base 做 RAG 增强
  - 自动提取对话中的关键信息存入记忆
  - 语义检索历史对话相关上下文
  - 用户画像累积 (分析偏好、常用数据集)
- [ ] **Agent 自我进化**: 基于 failure_learning 的工具选择优化
  - 聚合跨用户的工具失败模式
  - 自动调整工具推荐权重
  - 生成工具使用最佳实践

### 多模型支持 (Model-Agnostic)

- [ ] **Anthropic LLM 集成**: 利用 ADK v1.27 的 Anthropic PDF + streaming 支持，实现 Claude 作为备选 Agent 模型
  - 配置化模型选择（环境变量或用户偏好）
  - MODEL_TIER_MAP 扩展支持 Anthropic 模型 ID
  - 路由器可配置使用不同 LLM 提供商
- [ ] **LiteLLM 通用适配**: 通过 LiteLLM 支持 OpenAI、Mistral、Llama 等模型
  - output_schema + tools 组合（ADK v1.27 已支持）
  - streaming + reasoning 字段兼容
- [ ] **模型性能对比面板**: 不同 LLM 在相同任务上的效果/成本/延迟对比

### A2A (Agent-to-Agent 互操作)

- [ ] **RemoteA2aAgent 集成**: 利用 ADK v1.27 的 A2aAgentExecutor 实现远程 Agent 调用
  - Data Agent 作为 A2A Server 暴露能力
  - Data Agent 调用外部 A2A Agent（如专业遥感分析 Agent）
  - request interceptors 实现认证和审计
- [ ] **A2A 服务发现**: 注册和发现可用的远程 Agent 服务

### ADK v1.27 新特性采用

- [ ] **Session Rewind**: 在前端添加"撤销"按钮，调用 `Runner.rewind_async()` 回滚到上一次 invocation
- [ ] **ComputerUse Tool**: 评估桌面自动化能力用于 GIS 软件操作（如 ArcGIS Desktop 自动化）
- [ ] **UiWidget (实验性)**: MCP 工具返回 UI 组件，前端直接渲染交互表单
- [ ] **adk optimize**: 自动优化 3 个 YAML prompt 文件，提升 Agent 效果
- [ ] **list_skills_in_dir**: 替代 capabilities.py 中的手动目录遍历
- [ ] **OpenTelemetry 增强**: 集成 agent.version, tool.definitions, error code 等新 span 属性到可观测性体系

- [ ] **Webhook/API 模式**: 无 UI 的纯 API 调用 (pipeline_runner.py 已就绪)
  - RESTful API + API Key 认证
  - 批量任务提交
  - 适配 CI/CD 和第三方系统集成
- [ ] **移动端适配**: 响应式布局 + PWA
  - 地图/聊天面板适配触摸操作
  - 离线缓存常用数据
- [ ] **多语言国际化**: i18n 框架已有，需补齐英文翻译
  - 前端: react-i18next 完整覆盖
  - 后端 prompts: 英文版 YAML
  - Agent 指令: 双语切换

### 协作能力

- [ ] **协作工作区**: 多用户实时协作
  - 共享地图标注实时同步 (WebSocket)
  - 分析结果评论和讨论
  - 团队看板 (任务分配、进度跟踪)

---

## 技术债务追踪

| ID | 问题 | 来源 | 优先级 | 状态 |
|----|------|------|--------|------|
| S-1 | app.py 过大 | §21 | 高 | ✅ 已缓解 (3700→3267, 提取2模块) |
| S-2 | 全局变量非线程安全 | §21 | 中 | 待修复 |
| S-3 | 无 Alembic 迁移 | §21 | 中 | 待修复 |
| S-4 | frontend_api.py 过大 | §21 | 中 | 待修复 |
| SEC-1 | DB fallback admin/admin123 | §21 | 高 | ✅ 已修复 |
| SEC-2 | 无暴力破解防护 | §21 | 中 | ✅ 已修复 |
| SEC-3 | 沙箱 startswith 绕过 | §21 | 中 | 待修复 |
| SEC-4 | Prompt 注入模式匹配 | §21 | 中 | 待修复 |
| SEC-5 | 默认角色过宽松 | §21 | 低 | 待修复 |
| E-1 | 知识图谱纯内存 | §21 | 中 | 待修复 |
| E-2 | 工作流仅顺序 | §21 | 高 | ✅ 已修复 (DAG + custom_skill) |
| E-3 | Cron 基于内存 | §21 | 中 | 部分缓解 |
| E-4 | 指标基数无限 | §21 | 低 | 待修复 |
| E-5 | 融合配对顺序 | §21 | 低 | 待修复 |
| F-1 | Props drilling | §21 | 中 | 待修复 |
| F-2 | window.__* 全局回调 | §21 | 低 | 待修复 |
| F-3 | 单文件 CSS | §21 | 中 | 待修复 |
| F-4 | 缺 Error Boundaries | §21 | 中 | ✅ 已修复 |
| F-5 | REST 轮询地图 | §21 | 低 | 受限 Chainlit |
| T-3 | 评测阈值硬编码 | §21 | 低 | 待修复 |
| T-4 | 路由 Token 未追踪 | §21 | 中 | ✅ 已修复 |

---

*本文档随项目迭代持续更新。每完成一项请移到"已完成"区域并标注日期。*
