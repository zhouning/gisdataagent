# Data Agent 开发者指南

## 1. 架构概览

本项目采用 **Chainlit + Google ADK + React** 三层架构：
*   **前端层**: React 18 三面板 SPA (`frontend/src/`)，通过 `@chainlit/react-client` 连接后端。
*   **交互层**: Chainlit (`data_agent/app.py`)。负责 WebSocket 通信、事件拦截、认证。
*   **核心逻辑层**: Google ADK (`data_agent/agent.py`)。负责智能体编排、工具调用、LLM 推理。
*   **REST API 层**: Starlette (`data_agent/frontend_api.py`)。17 个端点服务前端数据请求。
*   **工具层**: 16 个 BaseToolset 模块 (`data_agent/toolsets/`)，包括 SkillBundle 分组。

## 2. 目录结构
```text
data_agent/
├── app.py                    # Chainlit 入口, 语义路由, 认证, RBAC
├── agent.py                  # ADK Agent 定义与管道编排
├── frontend_api.py           # 17 个 REST API 端点
├── auth.py                   # 密码认证, 注册, 账户删除, OAuth
├── toolsets/                 # 16 个 BaseToolset 模块
│   ├── skill_bundles.py      #   5 个命名工具包 (SkillBundle)
│   ├── visualization_tools.py #  9 工具 (含 NL 图层控制)
│   ├── semantic_layer_tools.py # 9 工具 (语义层浏览)
│   ├── datalake_tools.py     #   8 工具 (数据湖目录)
│   ├── streaming_tools.py    #   5 工具 (实时流)
│   ├── team_tools.py         #   8 工具 (团队协作)
│   └── ...                   #   exploration, geo_processing, analysis, etc.
├── prompts/                  # 3 个 YAML Prompt 文件
│   ├── optimization.yaml     #   优化管道
│   ├── planner.yaml          #   动态规划器
│   └── general.yaml          #   通用管道
├── migrations/               # 16 个 SQL 迁移脚本 (001-016)
├── map_annotations.py        # 协作地图标注 CRUD
├── health.py                 # K8s 健康检查 API
├── observability.py          # 结构化日志 + Prometheus 指标
├── semantic_layer.py         # 语义目录 + 3 级层次 + TTL 缓存
├── data_catalog.py           # 数据湖目录 + 血缘追踪
├── token_tracker.py          # Token 用量追踪 + 管道分布
├── gis_processors.py         # GIS 操作 (网格, 缓冲, 叠加, 裁剪...)
├── drl_engine.py             # DRL 优化环境 (Gymnasium)
├── test_*.py                 # 48 个测试文件 (923+ 测试)
├── run_evaluation.py         # 智能体评估 (含 JSON 摘要输出)
└── eval_set.json             # 评估数据集 (3 个测试用例)

frontend/
├── src/
│   ├── App.tsx               # 主应用: 认证, 三面板, 用户菜单
│   ├── components/
│   │   ├── ChatPanel.tsx     # 聊天面板 + NL 图层控制中继
│   │   ├── MapPanel.tsx      # Leaflet 地图 + 标注 + 底图切换
│   │   ├── DataPanel.tsx     # 5 标签: 文件/CSV/目录/历史/用量
│   │   ├── LoginPage.tsx     # 登录 + 注册切换
│   │   ├── AdminDashboard.tsx # 管理后台
│   │   └── UserSettings.tsx  # 账户设置 + 自助删除
│   └── styles/layout.css     # 全部样式 (~1900 行)
└── package.json

.github/workflows/ci.yml     # CI: 测试 + 前端构建 + 评估
k8s/                          # 11 个 K8s 清单文件
```

## 3. 开发指引

### 3.1 核心架构模式

#### 数据库连接 (`db_engine.py`)
- **单例模式**: `get_engine()` 返回全局唯一的 SQLAlchemy engine
- **所有模块**通过 `from .db_engine import get_engine` 获取连接
- **测试时**: `@patch("data_agent.module.get_engine", return_value=None)` 禁用数据库

#### 语义路由 (`app.py`)
用户消息 → `classify_intent()` (Gemini 2.0 Flash) → 管道分发:
- `optimization` → 优化管道
- `governance` → 治理管道
- `general` → 通用管道

#### NL 图层控制流
1. `control_map_layer()` 工具返回 `{layer_control: {...}}`
2. `app.py` 检测 `layer_control` → 注入 `cl.Message` metadata
3. `ChatPanel` → `onLayerControl` → `App.tsx` state → `MapPanel` useEffect

#### 地图数据流
1. 可视化工具输出 GeoJSON + `.mapconfig.json`
2. `app.py` 检测 `.mapconfig.json` → 添加 `metadata.map_update`
3. `ChatPanel` → `onMapUpdate` → `App.tsx` state → `MapPanel` 渲染图层

#### 前端 API 路由模式
```python
# 必须在 Chainlit catch-all 之前插入路由
Route("/api/path", endpoint=handler, methods=["GET"])
# mount_frontend_api() 自动处理插入顺序
```

### 3.2 工具包系统 (Skill Bundles)
`toolsets/skill_bundles.py` 定义 5 个命名分组:
- `SPATIAL_ANALYSIS` — 空间分析 (6 toolsets)
- `DATA_QUALITY` — 数据质量 (5 toolsets)
- `VISUALIZATION` — 可视化 (1 toolset, 9 tools)
- `DATABASE` — 数据库 (2 toolsets)
- `COLLABORATION` — 协作 (4 toolsets)

使用 `build_toolsets_for_intent(intent)` 按意图动态组装工具集。

### 3.3 添加新工具
1. 在 `toolsets/` 对应模块中编写工具函数
2. 添加到对应 Toolset 的 `_ALL_FUNCS` 列表
3. 在 `prompts/` YAML 中更新 Agent 指令
4. 如需要，在 `skill_bundles.py` 中更新 filter presets
5. 编写单元测试并验证 `test_toolsets.py` 中的工具计数

### 3.4 添加新 API 端点
1. 在 `frontend_api.py` 中编写 async handler 函数
2. 使用 `_get_user_from_request()` 进行认证
3. 使用 `_set_user_context()` 设置 ContextVar
4. 在 `get_frontend_api_routes()` 中添加 `Route()`
5. 更新 `test_frontend_api.py` 中的路由计数测试

### 3.5 添加新前端组件
1. 在 `frontend/src/components/` 中创建 `.tsx` 文件
2. 在 `App.tsx` 中导入并添加状态/回调
3. 在 `layout.css` 中添加样式 (遵循 `--primary`, `--radius-*`, `--shadow-*` 设计令牌)
4. 运行 `cd frontend && npm run build` 验证

### 3.6 DRL 模型集成 (v7)
- **Permutation Invariant**: `ParcelScoringPolicy` 架构，对每个地块独立打分
- **权重加载**: 推理时加载 `scorer_weights_v7.pt`
- **环境逻辑**: `drl_engine.py` 实现成对置换奖励 + 低数量惩罚

## 4. 测试

### 运行测试
```bash
# 全部测试 (923+)
.venv/Scripts/python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q

# 单个模块
.venv/Scripts/python.exe -m pytest data_agent/test_frontend_api.py -v

# 前端构建检查
cd frontend && npm run build
```

### Mock 模式
- 数据库: `@patch("data_agent.module.get_engine", return_value=None)` — 始终在**导入位置**mock
- 认证: `@patch("data_agent.frontend_api._get_user_from_request")`
- 环境变量: `@patch.dict("os.environ", {"KEY": "value"})`

### CI 管道
`.github/workflows/ci.yml`:
- **test**: Ubuntu + PostGIS 服务容器, pytest + JUnit XML
- **frontend**: Node.js 20, `npm ci && npm run build`
- **evaluate**: ADK 评估 (仅 main 分支, 需要 `GOOGLE_API_KEY` secret)

## 5. 依赖管理
项目依赖记录在 `requirements.txt` (根目录, 329 包)。新增库后请更新:
```bash
pip freeze > requirements.txt
```

前端依赖:
```bash
cd frontend && npm install <package>
```
