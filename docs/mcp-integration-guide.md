# MCP Server 外部 Agent 接入指南

> **版本**: v2.0 &nbsp;|&nbsp; **更新日期**: 2026-03-25
>
> GIS Data Agent 通过 Model Context Protocol (MCP) 向外部 AI Agent 暴露 37+ GIS 分析工具。
> 支持 Claude Desktop、Cursor IDE、Windsurf 等 MCP 兼容客户端。

---

## 快速开始

### 1. 验证 MCP Server 工作正常

```bash
cd D:\adk
.venv\Scripts\python.exe -m data_agent.mcp_server --test
```

预期输出：
```
[MCP Server] Registered 37 GIS tools.
[MCP Self-Test] Tools registered: 37
  [database] 3 tools: describe_table, share_table, import_to_postgis
  [exploration] 5 tools: ...
  [geocoding] 5 tools: ...
  ...
[MCP Self-Test] PASSED — all tools registered successfully.
```

### 2. 配置 Claude Desktop

编辑 Claude Desktop 配置文件：

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "gis-data-agent": {
      "command": "D:\\adk\\.venv\\Scripts\\python.exe",
      "args": ["-m", "data_agent.mcp_server"],
      "cwd": "D:\\adk",
      "env": {
        "MCP_USER": "analyst1",
        "MCP_ROLE": "analyst"
      }
    }
  }
}
```

重启 Claude Desktop，在对话中应看到 GIS Data Agent 工具图标。

### 3. 配置 Cursor IDE

在 Cursor 设置中添加 MCP Server：

**Settings → MCP Servers → Add**

```json
{
  "name": "gis-data-agent",
  "command": "D:\\adk\\.venv\\Scripts\\python.exe",
  "args": ["-m", "data_agent.mcp_server"],
  "cwd": "D:\\adk",
  "env": {
    "MCP_USER": "cursor_user",
    "MCP_ROLE": "analyst"
  }
}
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_USER` | `mcp_user` | 用户标识，决定文件沙箱路径 `uploads/{MCP_USER}/` |
| `MCP_ROLE` | `analyst` | RBAC 角色：`admin` (全部) / `analyst` (分析+查询) / `viewer` (只读) |

数据库和 API 凭证自动从 `data_agent/.env` 加载。

---

## 传输协议

| 模式 | 命令 | 适用场景 |
|------|------|---------|
| **stdio** (默认) | `python -m data_agent.mcp_server` | Claude Desktop, Cursor |
| **SSE** | `python -m data_agent.mcp_server --transport sse` | HTTP 客户端, 远程连接 |

---

## 工具分类 (37+ tools)

| 分类 | 工具数 | 代表工具 | 权限 |
|------|------:|---------|------|
| Exploration | 5 | `explore_dataset`, `describe_raster`, `load_spatial_data` | analyst+ |
| Processing | 6 | `create_buffer`, `overlay_analysis`, `reproject_data` | analyst+ |
| Geocoding | 5 | `batch_geocode`, `reverse_geocode`, `search_poi` | analyst+ |
| Visualization | 3 | `visualize_interactive_map`, `generate_heatmap` | viewer+ |
| Database | 3 | `describe_table`, `share_table`, `import_to_postgis` | analyst+ |
| Remote Sensing | 4 | `calculate_ndvi`, `download_lulc`, `download_dem` | analyst+ |
| Statistics | 3 | `spatial_autocorrelation`, `hotspot_analysis`, `local_moran` | analyst+ |
| Metadata | 6 | `search_catalog`, `get_data_lineage`, `list_skills` | viewer+ |
| Pipeline | 2 | `run_analysis_pipeline`, `list_virtual_sources` | analyst+ |

---

## 使用示例

### 在 Claude Desktop 中使用

```
用户: 帮我查看 uploads/analyst1/buildings.shp 的数据概况

Claude: [调用 explore_dataset 工具]
该数据集包含 2,847 个建筑物多边形...
```

```
用户: 搜索数据目录中关于"土地利用"的资产

Claude: [调用 search_catalog 工具]
找到 5 个相关资产...
```

### 在 Cursor 中使用

在代码编辑器中可直接引用 GIS 分析结果：

```
@gis-data-agent 对 test_data.geojson 做空间自相关分析
```

---

## 文件沙箱

每个 MCP 用户的文件操作限制在 `data_agent/uploads/{MCP_USER}/` 目录内：

- **输入文件**: 必须位于用户上传目录下
- **输出文件**: 自动保存到用户上传目录，返回相对路径
- **路径穿越防护**: `_resolve_path()` 拒绝 `..` 路径组件

---

## 常见问题

### MCP Server 无法启动

```
ModuleNotFoundError: No module named 'data_agent'
```

确保 `cwd` 设置为 `D:\adk`（项目根目录），或设置 `PYTHONPATH=D:\adk`。

### 数据库连接失败

确认 `data_agent/.env` 中 PostgreSQL 连接信息正确：

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=gis_agent
DB_USER=postgres
DB_PASSWORD=your_password
```

### 工具调用超时

长时间运行的工具（DRL 优化、遥感下载）可能超过默认超时。建议：
- 对大数据集先使用 `explore_dataset` 了解数据规模
- DRL 优化建议在 Web UI 中运行（支持异步 + 进度展示）

### 权限不足

如果工具返回"Permission denied"，检查 `MCP_ROLE` 设置。`viewer` 角色无法执行写操作。

---

## 安全注意事项

1. **MCP_USER 仅用于开发环境** — stdio 传输无认证层，生产环境应使用 SSE + API Key
2. **数据库凭证** — 通过 `.env` 文件加载，不要通过 MCP 环境变量传递
3. **文件访问** — 仅限用户沙箱目录，不可访问系统文件
