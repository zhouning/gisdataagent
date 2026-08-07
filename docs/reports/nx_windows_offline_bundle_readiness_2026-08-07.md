# 宁夏 GIS Data Agent Windows 离线包交付就绪度

**日期**：2026-08-07
**目标**：物理隔离、无容器、无预装运行环境的 Windows x64 主机

## 本轮已交付

- `deploy/windows-standalone/bundle-manifest.json`：固定 Python 3.11、GIS wheelhouse、自然资源本体 2.3、Paper9、PostgreSQL/PostGIS/pgvector、MinIO、JRE/Fuseki、Ollama/模型、可选 Prometheus/Grafana 及其安装边界。
- `deploy/windows-standalone/build_offline_bundle.py`：只收集 staging 目录中的真实材料；缺少 required artifact、直接依赖 wheel、最小文件数/字节数，或 wheel 不是 CPython 3.11 `win_amd64`/纯 Python `any` 时返回 `blocked`，不生成 ZIP。
- `deploy/windows-standalone/install_offline_bundle.ps1`：校验 SHA-256、安装 Python 和离线 wheel，初始化 DuckDB/文件湖/日志目录，并按 production profile 安装原生中间件。
- `deploy/windows-standalone/start_gda.ps1` / `stop_gda.ps1`：启动/停止原生进程和 Windows 采集 worker，统一输出日志，启动前调用验收脚本。
- `deploy/windows-standalone/register_tasks.ps1` / `unregister_tasks.ps1`：使用 Windows Task Scheduler 做断电自动恢复，不依赖 DolphinScheduler 或容器。
- `scripts/verify_windows_offline_bundle.py`：输出 JSON/Markdown 验收报告，检查 manifest、哈希、Python、GIS 驱动、本体、合同、Paper9/模型及生产服务端口。
- `data_agent/lite_mode.py`：新增 `GDA_DUCKDB_PATH`，使控制库可以放在数据盘，不随应用版本目录升级或回滚。
- 安装链路复核：PostgreSQL 迁移由临时 `postgres` 超级用户执行，`agent_user` 仅作运行时角色；
  pgvector 支持 ZIP 展开和 DLL/control/SQL 三项校验；Java/Ollama 路径持久化；Ollama LLM 与
  embedding 标签在运行验收时核对；Task Scheduler 监督进程支持断电恢复。

## 本机验证

- `23 passed`：Lite/DuckDB、Windows 入湖 worker、Windows 预检和 GIS runtime 回归测试。
- Ruff、Python 编译、manifest JSON、profile 引用和构建器缺件阻断测试通过。
- 本机无 `pwsh`/Windows x64，未声称 PowerShell 语法、原生安装器、驱动 DLL 或模型服务已经现场验收。

## 当前不能声称已经生成最终 ZIP 的原因

本开发机是 macOS ARM64，不能把 macOS native wheel 或本机 Python 解释器伪装成 Windows x64。仓库也没有完整的 Windows wheelhouse、PostGIS DLL、MinIO/JRE/Fuseki/Ollama 安装介质及批准的 Gemma/embedding/Paper9 权重。因此当前交付的是**可失败闭环的构建器和安装器**，不是一个缺文件的假离线包。

最终 ZIP 必须在联网 Windows x64 staging 机完成：

1. 用 `requirements-windows-core.txt` 和 `requirements-windows-production.txt` 下载 CPython 3.11 / `win_amd64` 的全量 wheel（包含 transitive dependencies）。
2. 放入 manifest 约定的 PostgreSQL 16、PostGIS 3.4、pgvector、MinIO、OpenJDK 17、Apache Jena Fuseki、Ollama、Gemma 4 26B、nomic embedding 和 Paper9 介质/权重。
3. 分别构建 `core` 和 `production` ZIP；构建器缺一个 required artifact 就会阻断。
4. 在一台无开发环境的 Windows 验收机解压后执行安装器和 `verify_windows_offline_bundle.py`，保存 `SHA256SUMS`、验收 JSON/Markdown 和安装日志。

## 现场启动边界

`core` 可以在候选合同状态下完成原始入湖、画像、质量、标准化、本体结构查看和诊断导出；本体权威绑定和自然语言问数保持 `review/blocked`。`production` 只有在 EA/数据标准合同已经由责任人签署为 `authority=ea_standard`、`review_status=approved`、`production_ready=true`，并且真实模型权重与 Paper9 版本验收通过后才允许启动。这个门禁是为了避免把重庆样例、截图字段或候选标准误当成宁夏权威数据。
