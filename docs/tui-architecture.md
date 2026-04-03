# TUI 终端界面 — 使用场景与架构设计

> Data Agent 的 TUI (Terminal User Interface) 形态分析：与 Web UI 的差异、核心使用场景、架构设计和实施状态。

---

## Web UI vs TUI 的本质差异

| 维度 | Web UI (Chainlit + React) | TUI (Textual + Rich) |
|------|--------------------------|---------------------|
| **文件访问** | 上传到服务端 `uploads/{user_id}/` | 直接读写本地文件系统，零拷贝 |
| **数据规模** | 受上传大小限制（500MB）和服务器内存限制 | 本地 TB 级数据直接处理 |
| **网络依赖** | 必须在线，LLM 调用走网络 | LLM 走网络，但数据处理纯本地 |
| **权限模型** | 多租户沙箱隔离（RBAC: admin/analyst/viewer） | 单用户，继承终端用户的 OS 权限 |
| **集成方式** | 浏览器交互 | 可嵌入 shell 脚本、CI/CD、cron job |
| **可视化** | 完整地图渲染（Leaflet 2D + deck.gl/MapLibre 3D） | 文本报告 + 文件路径输出（可打开浏览器查看地图） |
| **适用场景** | 交互式分析、团队协作、展示汇报 | 批量处理、自动化管线、远程服务器、无 GUI 环境 |
| **启动速度** | 浏览器加载 + WebSocket 连接 | 直接启动 Python 进程，秒级就绪 |
| **会话管理** | 持久化到 PostgreSQL，跨设备恢复 | InMemorySessionService，进程结束即清理 |

**核心区别**不仅仅是"本地文件 vs 上传文件"，而是**使用范式的根本不同**：

- Web UI 是"人在屏幕前交互"
- TUI 是"命令驱动的自动化执行"

---

## 核心使用场景

### 场景 1：批量数据处理

```bash
# 对目录下所有 shapefile 做质量审计
gis-agent run "审计数据质量" --file /data/shapefiles/parcels.shp

# 批量执行
gis-agent run "分析数据质量并修复" --file /data/parcels.shp --output /data/output/
```

GIS 分析师经常面对几十个文件的批量任务。Web UI 逐个上传不现实，CLI 一行命令搞定。

### 场景 2：无 GUI 服务器

```bash
# 在 Linux 生产服务器上跑优化分析
ssh gpu-server
gis-agent run "优化用地布局" --file /mnt/nfs/parcels.gpkg --model premium
```

部署在计算集群上，没有图形界面，只有终端。DRL 优化模型需要 GPU，数据在 NFS 共享存储上。

### 场景 3：CI/CD 集成

```yaml
# GitHub Actions / Jenkins — 空间数据质量门禁
- name: Spatial Quality Gate
  run: |
    gis-agent run "审计空间数据质量" \
      --file ${{ inputs.shapefile }} \
      --format json  # JSON 输出便于自动化解析
```

将空间数据质量检查嵌入 CI/CD 流水线，自动拦截不合格数据。

### 场景 4：定时管线自动化

```bash
# crontab — 每天凌晨自动跑数据治理管线
0 2 * * * gis-agent run "执行标准质检流程" --file /data/daily/*.shp

# 结合 Workflow — 执行预定义工作流
0 3 * * * gis-agent run "执行工作流 daily_audit"
```

无人值守执行，结果通过 Webhook 推送到企业通讯工具。

### 场景 5：大数据本地处理

```bash
# 处理 10GB 的遥感影像 — 不用上传到服务端
gis-agent run "多源融合分析" --file /data/dem_30m.tif --file /data/parcels.gpkg

# 敏感数据不能离开本机
gis-agent run "审计数据质量" --file /data/classified/military_zones.shp
```

数据太大无法上传，或含敏感信息不能离开本机网络。

### 场景 6：交互式 TUI 全屏界面

```bash
# 启动三面板全屏 TUI — 类似 IDE 体验
gis-agent tui --user admin --role admin

# 在 TUI 内交互
gis> 分析这个文件的数据质量 /data/parcels.shp
gis> /catalog          # 浏览数据目录
gis> /sql SELECT ...   # 直接执行 SQL
gis> /status           # 查看 Token 使用统计
```

TUI 提供三面板布局（Chat | Report | Status），适合需要持续交互但无浏览器的环境。

---

## 已实现架构

### 多通道统一架构

```
┌─────────────────────────────────────────────────────────────┐
│                     接入层 (Channels)                        │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Web UI   │  TUI     │  CLI     │  Bot     │  API            │
│ (Chainlit│ (Textual │ (Typer   │ (WeCom/  │  (REST/         │
│  React)  │  全屏)   │  非交互) │  DingTalk)│   Webhook)     │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                Channel Adapter Layer                         │
│   每个 Channel 实现: auth + input + output + file_resolver   │
├─────────────────────────────────────────────────────────────┤
│              pipeline_runner.py (零 UI 依赖)                 │
│   run_pipeline_headless() → PipelineResult                  │
├─────────────────────────────────────────────────────────────┤
│              Agent 编排层 + 工具执行层 (共享)                 │
│   intent_router → Pipeline → Agent → 40 Toolsets            │
└─────────────────────────────────────────────────────────────┘
```

**设计原则**：所有通道共享同一个 Agent 引擎，只在接入层适配差异。`pipeline_runner.py` 是这个架构的枢纽——零 UI 依赖，接收 prompt 和文件路径，返回 `PipelineResult` 数据类。

### TUI 三面板布局（tui.py — 601 行）

```
┌────────────────────────────────────────────────────────────┐
│  GIS Data Agent TUI v16.0                          Ctrl+Q  │
├──────────────┬─────────────────────┬───────────────────────┤
│  Chat (35%)  │   Report (40%)      │   Status (25%)        │
│              │                     │                       │
│ > 我有哪些与 │  ## Analysis Report │ Intent: GENERAL       │
│   重庆相关   │                     │ Agent: GeneralProc    │
│   的数据？   │  检索到 3 条数据:   │ >> query_database()   │
│              │  - 重庆地块.shp     │   #1 ok 返回5条      │
│ [green]      │  - 重庆DEM.tif      │                       │
│ Analysis     │  - 重庆POI.csv      │ Pipeline: general     │
│ complete.    │                     │ Duration: 2.3s        │
│              │  Generated Files:   │ Tokens: 1205in/342out │
│              │  /data/result.csv   │                       │
├──────────────┼─────────────────────┼───────────────────────┤
│ gis> ▏       │                     │                       │
└──────────────┴─────────────────────┴───────────────────────┘
│ Ctrl+Q Quit │ Ctrl+L Clear │ F1 Help │ ↑↓ History          │
└────────────────────────────────────────────────────────────┘
```

- **Chat Panel**：用户输入 + 系统消息（Rich markup 格式化）
- **Report Panel**：分析结果（Markdown 渲染 + Rich Table）
- **Status Panel**：实时 Agent/Tool 执行状态 + Token 统计

### TUI 命令系统

| 命令 | 功能 |
|------|------|
| `/help` | 显示命令帮助 |
| `/status` | Token 使用统计（日/月 + Pipeline 分类） |
| `/catalog [query]` | 浏览/搜索数据目录 |
| `/sql <SQL>` | 执行只读 SQL 查询 |
| `/verbose` | 切换详细输出模式（显示工具调用日志） |
| `/cancel` | 取消运行中的 Pipeline |
| `/clear` | 清空所有面板 |
| `/quit` | 退出 TUI |

快捷键：`Ctrl+Q` 退出、`Ctrl+L` 清屏、`F1` 帮助、`↑↓` 命令历史。

### CLI 命令系统（cli.py — 609 行）

```
gis-agent <command> [options]

命令:
  run <prompt>          单次执行（批量模式）
  chat                  交互式对话模式（多轮）
  tui                   启动全屏 TUI 界面
  catalog list          列出数据目录
  catalog search <q>    搜索数据目录
  skills list           列出自定义 Skills
  skills delete <id>    删除自定义 Skill
  sql <query>           执行 SQL 查询
  status                查看系统状态

通用选项:
  --file, -f <path>     输入文件路径
  --output, -o <dir>    输出目录（默认: 当前目录）
  --model <tier>        模型等级 (fast/standard/premium)
  --format <fmt>        输出格式 (text/json/markdown)
  --verbose, -v         详细输出（含工具调用日志）
  --user <name>         用户名（默认: OS 用户）
  --role <role>         角色 (admin/analyst/viewer)
```

### Pipeline 执行流程（TUI/CLI 共享）

```python
# 1. 设置用户上下文 (ContextVar)
session_id = _set_user_context(user, role)

# 2. 意图分类 — 返回 5 元组（v16.0 新增 language 检测）
intent, reason, router_tokens, tool_cats, lang = classify_intent(
    prompt, previous_pipeline
)

# 3. RBAC 检查
if role == "viewer" and intent in ("OPTIMIZATION", "GOVERNANCE"):
    raise PermissionError(...)

# 4. 选择 Agent + 设置工具类别
agent, pipeline_type = _select_agent(app_mod, intent)
current_tool_categories.set(tool_cats)

# 5. 无头执行 — InMemorySessionService，零 DB 依赖
result = await run_pipeline_headless(
    agent=agent,
    session_service=InMemorySessionService(),
    user_id=user,
    session_id=session_id,
    prompt=prompt,
    pipeline_type=pipeline_type,
    intent=intent,
    router_tokens=router_tokens,
    on_event=tui_event_callback,  # TUI 实时回调
)

# 6. 渲染结果
render_pipeline_result(result)  # Rich Table / Markdown / Panel
```

### Web UI vs TUI 的文件路径对比

```
Web UI 流程:
  用户上传 parcels.shp
    → 拷贝到 uploads/admin/parcels_a1b2c3d4.shp
    → _resolve_path("parcels.shp") → uploads/admin/parcels_a1b2c3d4.shp
    → 输出 → uploads/admin/result_e5f6g7h8.geojson
    → 前端下载

TUI/CLI 流程:
  用户指定 /data/gis/parcels.shp
    → 直接使用 /data/gis/parcels.shp (零拷贝，零上传)
    → _resolve_path("/data/gis/parcels.shp") → /data/gis/parcels.shp
    → 输出 → /data/gis/result_e5f6g7h8.geojson (原地输出)
    → 终端打印路径
```

### 可视化降级策略

TUI 无法内嵌地图，采用分级降级：

| Web UI 输出 | TUI 降级策略 |
|------------|-------------|
| Leaflet 交互式地图 | 生成 HTML 文件 → 浏览器自动打开 |
| deck.gl/MapLibre 3D 渲染 | 同上（生成 HTML），或降级为 2D 静态图 |
| 分级设色地图 | 生成 PNG 静态图 |
| 数据表格 | Rich Table 终端格式化表格 |
| Token 仪表盘 | Rich Table 文本统计 |
| Pipeline 进度 | Status Panel 实时更新 |

---

## 模块就绪度

| 组件 | 状态 | 说明 |
|------|------|------|
| `pipeline_runner.py` | ✅ 已就绪 | 360 行，零 UI 依赖，`PipelineResult` 数据类 |
| `intent_router.py` | ✅ 已就绪 | 251 行，5 元组返回（含 language 检测），零 Chainlit 依赖 |
| `pipeline_helpers.py` | ✅ 已就绪 | 341 行，纯工具函数，零 UI 依赖 |
| `tui.py` | ✅ 已实现 | 601 行，Textual 全屏三面板，命令/历史/Worker/Verbose |
| `cli.py` | ✅ 已实现 | 609 行，Typer + Rich，9 个命令，交互/批量双模式 |
| `tui.tcss` | ✅ 已实现 | Textual CSS 样式表（三面板 35%/40%/25% 布局） |
| Agent/Tools (40 Toolsets) | ✅ 共享 | 通过 ContextVar 自动适配用户身份 |
| 认证 | ✅ 已实现 | TUI/CLI 通过 `--user`/`--role` 参数，继承 OS 用户身份 |
| 文件路径解析 | ✅ 已适配 | TUI/CLI 模式下直接使用本地绝对路径 |
| 终端输出格式化 | ✅ 已实现 | Rich Markdown + Table + Panel + Text markup |
| 可视化降级 | 🔶 部分实现 | 文本报告 + 文件路径输出；HTML 自动打开待完善 |

---

## 技术栈

| 层 | 技术 |
|----|------|
| TUI 框架 | Textual 8.1.1（全屏应用、事件驱动、CSS 布局） |
| 终端渲染 | Rich 14.2.0（Markdown、Table、Panel、Progress） |
| CLI 框架 | Typer 0.24.0（命令解析、参数验证、帮助生成） |
| Pipeline 引擎 | pipeline_runner.py（零 UI 依赖，InMemorySessionService） |
| 意图路由 | intent_router.py（Gemini 2.0 Flash 语义分类） |
| Agent 框架 | Google ADK v1.27（LlmAgent、SequentialAgent） |

---

## 启动方式

```bash
# 全屏 TUI 模式
python -m data_agent tui
python -m data_agent tui --user admin --role admin --verbose

# CLI 单次执行
python -m data_agent run "分析重庆地块数据质量"
python -m data_agent run "审计数据" --file /data/parcels.shp --verbose

# CLI 交互式聊天
python -m data_agent chat

# CLI 工具命令
python -m data_agent catalog list
python -m data_agent sql "SELECT count(*) FROM spatial_data"
python -m data_agent status
```

---

*本文档基于 GIS Data Agent v16.0 架构编写。TUI/CLI 已完整实现并可用。*
