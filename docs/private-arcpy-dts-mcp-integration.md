# ArcPy 与 DTS 私有 MCP Server 接入说明

**日期：** 2026-08-18（首次接入：2026-08-05）
**目标应用：** GIS Data Agent
**接入源：** `codex-arcpy-mcp-plugin`、`codex-dts-mcp-plugin`

## 1. 接入结论

两个已在 Codex 中验证的私有 Streamable HTTP MCP Server 已接入 GIS Data Agent 的 MCP Hub，并同时开放给 `general` 和 `planner` 管道。

真实 Agent 侧验收结果：

| Server | 状态 | 工具数 | Agent 工具前缀 |
|---|---|---:|---|
| ArcPy MCP | connected | 34 | `arcpy_mcp_` |
| DTS MCP | connected | 14 | `dts_mcp_` |
| `general` 管道合计 | available | 48 | 两个命名空间 |

认证令牌只在连接时从进程环境读取。配置文件、数据库、API 状态响应、测试输出和本文档均不保存令牌值。

## 2. 架构位置

接入复用了现有 MCP Hub，没有在 Agent 内建立第二套专用连接管理器：

```text
mcp_servers.yaml / agent_mcp_servers
                |
                v
          McpHubManager
      auth + private CA + lifecycle
                |
                v
       ADK McpToolset per server
                |
                v
  McpHubToolset(general / planner)
                |
                v
 GeneralProcessing / PlannerProcessor
```

配置加载仍遵循项目原有顺序：数据库是主配置源，YAML 是首次安装的种子和数据库不可用时的回退。YAML 中的新 Server 会被写入 `agent_mcp_servers`；数据库已有同名记录时，以数据库记录为准。

## 3. Server 配置

两个 Server 均采用：

- 传输：`streamable_http`
- TLS：各自插件提供的私有 CA，仅作用于对应 HTTPX 客户端
- 认证：Bearer token 环境变量引用
- 状态：默认启用
- 管道：`general`、`planner`
- 连接超时：15 秒

当前私有网关地址：

| Server | MCP URL | Engine 兼容性 |
|---|---|---|
| ArcPy MCP | `https://192.168.50.170:8765/mcp` | ArcGIS Pro/ArcPy |
| DTS MCP | `https://192.168.8.117:8770/mcp` | DTS Engine 6.1/7.0 |

环境变量名：

```text
ARCPY_MCP_TOKEN
DTS_MCP_TOKEN
```

令牌必须由启动 GIS Data Agent 的进程继承。本机通过 macOS Keychain 与 LaunchAgent 注入；容器环境应使用容器 Secret 或其他部署 Secret 机制。不要把真实值写入仓库或环境文件。

私有 CA 当前从两个本机插件 checkout 读取：

```text
/Users/zhouning/codex-arcpy-mcp-plugin/plugins/arcpy-mcp/assets/arcpy-mcp-ca.crt
/Users/zhouning/codex-dts-mcp-plugin/plugins/dts-mcp/assets/dts-mcp-ca.crt
```

## 4. Hub 改造

`McpServerConfig` 新增两个非秘密字段：

- `bearer_token_env_var`：保存环境变量名，不保存令牌
- `ca_cert`：保存 Server 专属 CA 路径

连接时执行以下步骤：

1. 展开配置中的环境变量和用户目录引用。
2. 检查 CA 文件存在。
3. 从指定环境变量读取令牌并构造 Authorization header。
4. 为该 Server 创建独立 HTTPX 客户端，将 CA 作为 `verify` 参数。
5. 创建 ADK `McpToolset` 并发现工具。
6. 通过 ADK 的 `get_tools_with_prefix()` 暴露带 Server 前缀的工具。
7. 将连接状态、工具数和工具名写入内存状态，但不回传令牌或 CA 路径。

连接、重新发现工具和关闭会话都有硬超时。多个已启用 Server 并发启动；某一个 Server 失败只会把该 Server 标记为 `error`，不会阻断其他 GIS 工具集。

数据库表 `agent_mcp_servers` 通过幂等迁移增加相应字段。旧版 15 列查询结果仍可读取，不要求一次性迁移所有测试或旧部署数据。

## 5. Agent 工具面

### 5.1 ArcPy MCP

Agent 可见的 34 个工具包括：

```text
arcpy_mcp_health_check
arcpy_mcp_get_capabilities
arcpy_mcp_search_tools
arcpy_mcp_describe_tool
arcpy_mcp_create_upload
arcpy_mcp_get_upload_status
arcpy_mcp_renew_upload
arcpy_mcp_complete_upload
arcpy_mcp_list_artifacts
arcpy_mcp_create_download
arcpy_mcp_delete_artifact
arcpy_mcp_submit_job
arcpy_mcp_get_job
arcpy_mcp_list_jobs
arcpy_mcp_cancel_job
arcpy_mcp_get_job_log
arcpy_mcp_inspect_dataset
arcpy_mcp_buffer_features
arcpy_mcp_clip_features
arcpy_mcp_project_features
arcpy_mcp_dissolve_features
arcpy_mcp_intersect_features
arcpy_mcp_spatial_join
arcpy_mcp_check_geometry
arcpy_mcp_repair_geometry
arcpy_mcp_clip_raster
arcpy_mcp_project_raster
arcpy_mcp_calculate_slope
arcpy_mcp_zonal_statistics
arcpy_mcp_export_map_layout
arcpy_mcp_detect_objects
arcpy_mcp_classify_pixels
arcpy_mcp_classify_objects
arcpy_mcp_detect_change
```

### 5.2 DTS MCP

Agent 可见的 14 个工具为：

```text
dts_mcp_dts_ping
dts_mcp_dts_list_pipelines
dts_mcp_dts_explain_error
dts_mcp_dts_create_upload
dts_mcp_dts_complete_upload
dts_mcp_dts_artifact_status
dts_mcp_dts_list_artifacts
dts_mcp_dts_delete_artifact
dts_mcp_dts_publish
dts_mcp_dts_publish_osgb
dts_mcp_dts_get_job
dts_mcp_dts_list_jobs
dts_mcp_dts_cancel_job
dts_mcp_dts_download_output
```

前缀只用于 Agent 函数声明。实际 MCP 调用仍使用 Server 声明的原始工具 ID，因此不会改变远端协议。

## 6. Agent 操作约束

`general` 和 `planner` 提示词已加入以下运行规则：

- ArcPy 第一次操作先执行健康检查；需要扩展能力时查询 capabilities。
- ArcPy 新数据先检查，再执行具体处理。
- DTS 第一次操作先执行 ping 和 pipeline 枚举。
- DTS 目前只有 `road` 完成端到端验证；其他 pipeline 作为 best-effort。
- 远端路径参数只使用 artifact ID 与 artifact 内相对路径。
- 不传 Windows 绝对路径、盘符、UNC 路径或父目录穿越。
- 任务必须轮询至终态，只有 `succeeded` 才能报告成功。
- 不在回复、日志或后续参数中复述 bearer token、签名 URL 或服务端绝对路径。

## 7. API 与运维状态

MCP 管理 API 现在能创建和测试包含环境令牌引用及私有 CA 的 Server 配置。连接测试的规范路径为：

```text
POST /api/mcp/servers/test
```

原路径 `POST /api/mcp/test` 继续保留为兼容别名。

Server 状态响应只增加以下脱敏信息：

- token 环境变量名
- token 当前是否可用（布尔值）
- 是否配置 CA（布尔值）

不会返回 token 值或 CA 文件内容。

## 8. 验证过程

### 8.1 静态和单元验证

- 编辑模块 Python 编译通过。
- `mcp_servers.yaml` 解析通过。
- 两个 CA 文件均存在。
- MCP Hub 聚焦测试通过，覆盖配置解析、环境令牌、私有 CA、数据库兼容、生命周期超时、前缀和 API 路径。

### 8.2 网络分层验证

不携带认证的 HTTPS 探测分别得到 ArcPy 的方法限制响应和 DTS 的未认证响应。这证明 TCP、TLS 和私有 CA 信任链可用，同时没有在命令参数中传递令牌。

普通沙箱内的 Python 网络探测会被环境策略阻止，表现为连接失败；这不是 Server 或配置故障。随后用获准访问内网的 GIS Data Agent Python 进程完成真实验收。

### 8.3 Agent 侧真实验收

2026-08-05 的首次接入验收同时连接 ArcPy 和 DTS，确认 `general` 管道可获得 48 个带命名空间的工具。2026-08-18 的 DTS 网关迁移复验只加载当前 `dts-mcp` 配置，然后：

1. 启动 `McpHubManager` 并读取数据库中的活动配置。
2. 使用环境令牌和私有 CA 建立 Streamable HTTP 会话。
3. 确认 Server 状态为 `connected`，发现 14 个工具。
4. 确认 Agent 工具包含 `dts_mcp_dts_ping` 等 DTS 命名空间。
5. 执行 `dts_mcp_dts_ping`，返回 `ok=true`，Engine 版本为 `7.0.0814.5654`。
6. 关闭会话，并验证关闭超时不会阻塞进程。

ADK 启动时可能输出 Google ADC/mTLS 自动配置警告。该警告来自 ADK 的可选 Google 认证探测，与使用自有 Bearer token 和私有 CA 的 MCP 连接无关。

## 9. DTS road 已验证流程

DTS `road` 管道已经独立完成真实数据的上传、发布、任务轮询、输出下载和 SHA-256 校验。输入是 85 条 EPSG:32648 道路、DOM 和 DEM，DTS Engine 任务以退出码 0 完成，产出了 `output.3dt` 与 `DataInfor.txt`。

完整过程和结果证据见：

- [DTS road 端到端测试报告](/Users/zhouning/dts-road-test-20260805/road-test-report.md)
- [DTS road 输出](/Users/zhouning/dts-road-test-20260805/result/output.3dt)

本次 GIS Data Agent 接入验收验证的是连接、发现、命名空间、Agent 管道暴露和只读健康调用，没有重复提交第二个 road 发布任务。

## 10. 已知边界

- 当前 CA 路径绑定本机插件 checkout。迁移到容器或其他主机时，应改为只读挂载路径。
- 数据库中若已存在同名 Server，数据库配置优先于 YAML；修改 YAML 后需要同步数据库记录或删除旧种子记录再重建。
- 远端上传、下载和作业属于多步 artifact 工作流。Agent 提示词已加入安全顺序，但生产场景仍应保留审计和高风险操作确认。
- DTS 除 `road` 外的 pipeline 尚未获得同等级端到端证据。
- ArcPy CPU 深度学习依赖与 ArcGIS Pro 版本兼容的 DLPK/EMD，且可能长时间运行。

## 11. 相关文件

- `data_agent/mcp_hub.py`：连接、认证、CA、生命周期和工具聚合
- `data_agent/mcp_servers.yaml`：两个 Server 的种子配置
- `data_agent/toolsets/mcp_hub_toolset.py`：Agent 工具入口
- `data_agent/api/mcp_routes.py`：活动 MCP 管理 API
- `data_agent/frontend_api.py`：兼容 API 构造与校验
- `data_agent/prompts/general.yaml`：通用管道 MCP 操作约束
- `data_agent/prompts/planner.yaml`：Planner 处理器 MCP 操作约束
- `data_agent/test_mcp_hub.py`：单元与契约测试
