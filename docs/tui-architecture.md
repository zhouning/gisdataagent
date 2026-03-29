# TUI 终端界面 — 使用场景与架构设计

> Data Agent 的 TUI (Terminal User Interface) 形态分析：与 Web UI 的差异、核心使用场景、架构设计和实施路线。

---

## Web UI vs TUI 的本质差异

| 维度 | Web UI (当前) | TUI (终端) |
|------|-------------|-----------|
| **文件访问** | 上传到服务端 `uploads/{user_id}/` | 直接读写本地文件系统，零拷贝 |
| **数据规模** | 受上传大小限制（500MB）和服务器内存限制 | 本地 TB 级数据直接处理 |
| **网络依赖** | 必须在线，LLM 调用走网络 | LLM 走网络，但数据处理纯本地 |
| **权限模型** | 多租户沙箱隔离 | 单用户，继承终端用户的 OS 权限 |
| **集成方式** | 浏览器交互 | 可嵌入 shell 脚本、CI/CD、cron job |
| **可视化** | 完整地图渲染（Leaflet/deck.gl） | 文本报告 + 文件路径输出（可打开浏览器查看地图） |
| **适用场景** | 交互式分析、团队协作、展示汇报 | 批量处理、自动化管线、远程服务器、无 GUI 环境 |
| **启动速度** | 浏览器加载 + WebSocket 连接 | 直接启动 Python 进程，秒级就绪 |
| **会话管理** | 持久化到 PostgreSQL，跨设备恢复 | 内存会话，进程结束即清理（可选持久化） |

**核心区别**不仅仅是"本地文件 vs 上传文件"，而是**使用范式的根本不同**：

- Web UI 是"人在屏幕前交互"
- TUI 是"命令驱动的自动化执行"

---

## 核心使用场景

### 场景 1：批量数据处理

```bash
# 对目录下所有 shapefile 做质量审计
gis-agent audit /data/shapefiles/*.shp --output report.docx

# 批量地理编码
gis-agent geocode /data/addresses.csv --address-col 地址 --output /data/geocoded.shp
```

GIS 分析师经常面对几十个文件的批量任务。Web UI 逐个上传不现实，TUI 一行命令搞定。

### 场景 2：无 GUI 服务器

```bash
# 在 Linux 生产服务器上跑优化分析
ssh gpu-server
gis-agent optimize /mnt/nfs/parcels.gpkg --model premium
```

部署在计算集群上，没有图形界面，只有终端。DRL 优化模型需要 GPU，数据在 NFS 共享存储上。

### 场景 3：CI/CD 集成

```yaml
# GitHub Actions / Jenkins — 空间数据质量门禁
- name: Spatial Quality Gate
  run: |
    gis-agent audit ${{ inputs.shapefile }} \
      --min-score 0.8 \
      --exit-code  # 不达标返回非零退出码，阻断部署
```

将空间数据质量检查嵌入 CI/CD 流水线，自动拦截不合格数据。

### 场景 4：定时管线自动化

```bash
# crontab — 每天凌晨自动跑数据治理管线
0 2 * * * gis-agent workflow run --id 5 --params '{"date": "today"}'

# 结合 User Tools — 调用自定义 HTTP API 推送结果
0 3 * * * gis-agent run "治理完成后推送报告到钉钉" --file /data/daily/*.shp
```

无人值守执行，结果通过 Webhook 推送到企业通讯工具。

### 场景 5：大数据本地处理

```bash
# 处理 10GB 的遥感影像 — 不用上传到服务端
gis-agent fusion /data/dem_30m.tif /data/parcels.gpkg --strategy zonal_statistics

# 敏感数据不能离开本机
gis-agent audit /data/classified/military_zones.shp --output /data/classified/report.docx
```

数据太大无法上传，或含敏感信息不能离开本机网络。

### 场景 6：管道式组合

```bash
# Unix 管道风格 — 数据处理链
cat query.sql | gis-agent sql --format geojson | gis-agent buffer --distance 500 > result.geojson

# 与其他工具配合
ogr2ogr -f GeoJSON /vsistdout/ input.shp | gis-agent analyze --stdin
```

TUI 天然融入 Unix 工具链生态。

---

## 架构设计

### 多通道统一架构

```
┌─────────────────────────────────────────────────────────────┐
│                     接入层 (Channels)                        │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Web UI   │  TUI     │  CLI     │  Bot     │  API            │
│ (Chainlit│ (Rich/   │ (Click   │ (WeCom/  │  (REST/         │
│  React)  │  Textual)│  非交互) │  DingTalk)│   Webhook)     │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                Channel Adapter Layer                         │
│   每个 Channel 实现: auth + input + output + file_resolver   │
├─────────────────────────────────────────────────────────────┤
│              pipeline_runner.py (已有，零 UI 依赖)           │
│   run_pipeline_headless() → PipelineResult                  │
├─────────────────────────────────────────────────────────────┤
│              Agent 编排层 + 工具执行层 (共享)                 │
│   intent_router → Pipeline → Agent → Tools                  │
└─────────────────────────────────────────────────────────────┘
```

**设计原则**：所有通道共享同一个 Agent 引擎，只在接入层适配差异。`pipeline_runner.py` 是这个架构的枢纽——零 UI 依赖，接收 prompt 和文件路径，返回 `PipelineResult` 数据类。

### TUI 适配层设计

```python
class TerminalChannel:
    """终端通道：输入来自 stdin/args，输出到 stdout，文件直接本地路径。"""

    def resolve_file(self, path: str) -> str:
        """TUI 的文件解析 — 直接返回本地绝对路径，零拷贝"""
        return os.path.abspath(path)

    async def run(self, prompt: str, files: list[str]):
        # 设置用户上下文
        current_user_id.set(os.getenv("USER", "cli_user"))
        current_user_role.set("analyst")

        # 意图分类
        intent, reason, tokens, cats = classify_intent(prompt)

        # 选择 Agent
        agent = get_agent_for_intent(intent)

        # 无头执行
        result = await run_pipeline_headless(
            agent=agent,
            session_service=InMemorySessionService(),
            user_id=current_user_id.get(),
            session_id=f"cli_{uuid4().hex[:8]}",
            prompt=prompt,
            pipeline_type=intent.lower(),
        )

        # 终端输出
        self.render_result(result)

    def render_result(self, result: PipelineResult):
        """终端渲染 — Rich 库格式化输出"""
        console.print(Markdown(result.report_text))
        if result.generated_files:
            table = Table(title="生成文件")
            for f in result.generated_files:
                table.add_row(os.path.basename(f), f)
            console.print(table)
```

### Web UI vs TUI 的文件路径对比

```
Web UI 流程:
  用户上传 parcels.shp
    → 拷贝到 uploads/admin/parcels_a1b2c3d4.shp
    → _resolve_path("parcels.shp") → uploads/admin/parcels_a1b2c3d4.shp
    → 输出 → uploads/admin/result_e5f6g7h8.geojson
    → 前端下载

TUI 流程:
  用户指定 /data/gis/parcels.shp
    → 直接使用 /data/gis/parcels.shp (零拷贝，零上传)
    → _resolve_path("/data/gis/parcels.shp") → /data/gis/parcels.shp
    → 输出 → /data/gis/result_e5f6g7h8.geojson (原地输出)
    → 终端打印路径
```

### 交互模式 vs 批量模式

TUI 支持两种使用方式：

```bash
# 1. 交互模式 — 类似 ChatGPT 终端，多轮对话
gis-agent chat
> 分析这个文件的数据质量 /data/parcels.shp
🔍 正在审计数据...
✓ 记录数: 5,432
✓ 几何类型: Polygon
✗ 发现 23 处拓扑错误
> 修复拓扑错误
🔧 修复中...
✓ 已修复，输出: /data/parcels_fixed.shp

# 2. 批量模式 — 一行命令，无交互
gis-agent run "分析数据质量并修复" --file /data/parcels.shp --output /data/output/
```

### 可视化降级策略

TUI 无法内嵌地图，采用分级降级：

| Web UI 输出 | TUI 降级策略 |
|------------|-------------|
| Leaflet 交互式地图 | 生成 HTML 文件 → `xdg-open` / `open` 自动打开浏览器 |
| deck.gl 3D 渲染 | 同上（生成 HTML），或降级为 2D 静态图 |
| 分级设色地图 | 生成 PNG 静态图 → 终端内联显示（kitty/iTerm2 协议） |
| 数据表格 | Rich Table 终端格式化表格 |
| Token 仪表盘 | Rich 进度条 + 文本统计 |
| 进度条 | Rich Progress Bar 实时更新 |

```python
# 可视化输出适配器
def output_map(map_config: dict, channel: str):
    if channel == "web":
        return map_config  # 直接返回 JSON 给前端渲染
    elif channel == "tui":
        # 生成独立 HTML
        html_path = generate_standalone_html(map_config)
        webbrowser.open(f"file://{html_path}")
        return f"地图已在浏览器中打开: {html_path}"
```

---

## 当前基础设施就绪度

| 组件 | 状态 | 说明 |
|------|------|------|
| `pipeline_runner.py` | ✅ 已就绪 | 360 行，零 UI 依赖，`PipelineResult` 数据类 |
| `intent_router.py` | ✅ 已就绪 | 153 行，独立模块，零 Chainlit 依赖 |
| `pipeline_helpers.py` | ✅ 已就绪 | 284 行，纯工具函数，零 UI 依赖 |
| `cli.py` | 🔶 骨架存在 | 基本的 Click 命令框架，需要完善交互模式 |
| Agent/Tools (23 个 Toolset) | ✅ 共享 | 通过 ContextVar 自动适配用户身份 |
| 认证 | 🔴 需要设计 | TUI 认证方式：API Key file / env var / OS user |
| 文件路径解析 | 🔶 需要适配 | `_resolve_path()` 需要 TUI 模式下跳过沙箱检查 |
| 终端输出格式化 | 🔴 需要实现 | Rich/Textual 终端渲染（Markdown、表格、进度条） |
| 可视化降级 | 🔴 需要实现 | HTML 独立文件生成 + 浏览器自动打开 |

**结论**：核心引擎（pipeline_runner + intent_router + pipeline_helpers）已经实现了零 UI 依赖。TUI 真正需要新写的只是终端适配层（输入解析、文件路径、输出渲染、认证），预估 300-500 行代码。

---

## 命令设计（草案）

```
gis-agent <command> [options]

命令:
  chat                  交互式对话模式
  run <prompt>          单次执行（批量模式）
  audit <file>          数据质量审计
  optimize <file>       用地布局优化
  geocode <file>        批量地理编码
  fusion <file1> <file2> 多源数据融合
  workflow run --id <N>  执行工作流
  workflow list          列出工作流

通用选项:
  --file, -f <path>     输入文件路径（可多个）
  --output, -o <dir>    输出目录（默认: 当前目录）
  --model <tier>        模型等级 (fast/standard/premium)
  --format <fmt>        输出格式 (text/json/markdown)
  --verbose, -v         详细输出（含工具调用日志）
  --exit-code           以退出码反映结果（0=成功, 1=失败, 用于 CI）
  --api-key <key>       API Key（或通过 GIS_AGENT_API_KEY 环境变量）
```

---

*本文档基于 GIS Data Agent v12.0 架构分析编写，TUI 功能位于 Roadmap 中期计划。*
