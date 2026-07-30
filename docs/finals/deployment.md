# 决赛部署与验证

## 1. 主机要求

- Docker Desktop 或 Docker Engine + Compose。
- Ollama 已加载精确标签 `Gemma4:26b` 和 embedding 模型。
- Paper9 源码为 `paper9-mnr-offline-package 0.3.3 / paper9v2 2.2.3`。
- Bishan runs 中存在 prepared 数据和 ONNX ensemble。
- 端口 `8000`、`5433` 和 `6379` 可用；冲突时先调整 Compose 映射。

## 2. 配置

```bash
cp .env.finals.example .env.finals
```

填写三个主机绝对路径：

```dotenv
PAPER9_HOST_REPO=/absolute/path/to/paper9-mnr-offline-package
PAPER9_BISHAN_RUNS_HOST=/absolute/path/to/bishan-runs
PAPER9_DONGXING_RUNS_HOST=/absolute/path/to/dongxing-runs
```

`.env.finals` 不提交版本库。

## 3. 只读预检

```bash
.venv/bin/python scripts/check_gemma4_finals_preflight.py \
  --output data_agent/demo_evidence/paper9/finals_20260730/finals_preflight_report.json
```

通过条件：

- `paper9_package_version = 0.3.3`
- `paper9_algorithm_version = 2.2.3`
- Bishan `DLTB_with_slope.shp` 存在
- ONNX 成员数大于 0，当前基线为 3
- Ollama 精确包含 `Gemma4:26b`
- 报告顶层 `ready = true`

## 4. Compose 配置解析

```bash
docker compose --env-file .env.finals \
  -f docker-compose.gemma4-demo.yml config
```

检查解析后的 `/app/paper9-demo` 来源必须是新版 `paper9-mnr-offline-package`，不能是旧 `arcgis-farmland-mpc` 源码目录。

## 5. 启动

```bash
docker compose --env-file .env.finals \
  -f docker-compose.gemma4-demo.yml up -d --build
```

```bash
docker compose --env-file .env.finals \
  -f docker-compose.gemma4-demo.yml ps
```

打开 `http://localhost:8000`。

## 6. 赛前验证顺序

1. 登录并打开运行日志面板。
2. 执行唯一锁定的 NL2Semantic2GeoSQL 问题，保存 SQL、结果和地图截图。
3. 执行 Bishan Paper9 成功提示词。
4. 确认轨迹包含 6 个工具，且顺序完全正确。
5. 确认 UI 显示包版本、算法版本、硬约束校验结果和 verified episode ID。
6. 确认地图显示灰/红/绿 `CHG_FLAG` 图层。
7. 刷新页面并确认关键运行日志仍可查看。
8. 关闭外部网络后再执行一次，确认本地 Ollama 和离线资源可用。

## 7. 当前已验证基线

2026-07-30 已确认：

- Compose 配置解析通过。
- app、PostGIS、Redis 3 个容器均为 `healthy`。
- 主机只读预检 6/6 通过，顶层 `ready = true`。
- 决赛关键测试 73 passed，模型网关与工具过滤兼容测试 52 passed。
- Ruff、Python 编译和前端生产构建通过。

前端仍有大 chunk 和 loader 导出警告；依赖仍有弃用提示。完整范围和命令见 [quality_gate_report.md](quality_gate_report.md)。

## 8. 可靠性基线复跑

```bash
.venv/bin/python scripts/run_paper9_adk_reliability_eval.py \
  --runs-per-scenario 10 \
  --output data_agent/demo_evidence/paper9/finals_20260730/adk_reliability_report.json
```

该命令会调用真实 Gemma 4 + ADK，但使用确定性 Paper9 工具替身。普通 CI 不运行此命令，因为 CI 没有本地 Ollama。

## 9. 停止

```bash
docker compose --env-file .env.finals \
  -f docker-compose.gemma4-demo.yml down
```

不要在赛前使用 `down -v`，避免删除数据库和上传产物卷。
