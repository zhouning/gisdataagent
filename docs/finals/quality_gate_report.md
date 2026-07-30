# 决赛质量检查报告

验证日期：2026-07-30

本报告记录决赛关键链路的可重复检查。它不把局部测试集合表述为整个仓库的零缺陷证明，也不把模型编排评测表述为底层规划算法重复运行。

## 1. 结论

| 检查项 | 结果 | 覆盖范围 |
|---|---:|---|
| 最终镜像运行时回归 | 236 passed | NL2SQL、WorldModel、Paper9 治理、预检、路由、展示与验证器 |
| 仓库交付契约 | 6 passed | Compose、环境模板、模型配置、Agent instruction 和脚本入口 |
| 真实提示词验收 | 2/2 场景 passed | 最终 NL2SQL 连续 3 次；Paper9 锁定路径两次通过且最终代码状态末次通过 |
| 决赛关键 Python 测试 | 73 passed | Paper9 服务、ADK 工具、治理、展示、路由、预检和部署契约 |
| 模型网关与工具过滤兼容测试 | 52 passed | thinking 参数、离线模型路由、六字段意图路由和工具分类 |
| 确定性行为契约 | 5/5 | 首次成功、一次恢复、二次失败转人工、版本阻断、禁止未审计写入 |
| Ruff | passed | 9 个决赛关键模块与脚本，包含 PPT 构建器 |
| Python 编译 | passed | 9 个决赛关键模块与脚本，包含 PPT 构建器 |
| 前端生产构建 | passed | TypeScript + Vite，4,134 个模块完成转换 |
| Compose 配置解析 | passed | `docker-compose.gemma4-demo.yml` |
| 运行中容器 | 3/3 healthy | app、PostGIS、Redis |
| 主机只读预检 | 6/6 passed | Paper9 版本、prepared、ONNX ensemble、Gemma 4 标签 |
| PPT/PDF 包完整性 | passed | 11 页、11/11 speaker notes、11/11 视觉检查；业务截图与 406 结果一致，PPTX/PDF 哈希校验通过 |
| `git diff --check` | passed | 决赛范围差异的空白与冲突标记检查 |

## 2. 精确测试集合

最终镜像运行时回归：

```bash
docker exec gisdataagent-app-1 python -m pytest \
  data_agent/test_finals_demo_verifier.py \
  data_agent/test_finals_preflight.py \
  data_agent/test_nl2sql_executor.py \
  data_agent/test_nl2sql_semantic_rewrite.py \
  data_agent/test_nl2sql_tools.py \
  data_agent/test_nl2sql_toolset_registration.py \
  data_agent/test_paper9_agent_evaluation.py \
  data_agent/test_paper9_agent_governance.py \
  data_agent/test_world_model_v21.py \
  data_agent/test_world_model_v21_presentation.py \
  data_agent/test_world_model_v21_routes.py \
  data_agent/test_world_model_v21_tools.py -q
```

结果：`236 passed, 5 warnings`。仓库根文件不打包进运行镜像，因此部署契约在宿主仓库单独运行，
结果为 `6 passed`；没有用 skip 掩盖测试分层。

精确真实提示词验收：

```bash
docker exec gisdataagent-app-1 python scripts/verify_gemma4_finals_demo.py \
  --nl2sql-repeats 3 \
  --paper9-timeout 360 \
  --output /tmp/verified_finals_demo_report.json
```

最终报告 `passed=true`：NL2SQL 三次均为 `35`；县域耕地规划 Agent 严格六次函数调用，指标来自
同一个最终运行目录，硬约束校验、空间产物和已验证经验写入全部通过。历史锁定路径耗时为
`93.490s / 112.940s`；新版中文 UI 浏览器运行总用时 `88.6s`、MPC 规划 `73.7s`，业务指标一致。

决赛关键测试命令：

```bash
.venv/bin/python -m pytest -q \
  data_agent/test_world_model_v21.py \
  data_agent/test_world_model_v21_tools.py \
  data_agent/test_world_model_v21_presentation.py \
  data_agent/test_world_model_v21_routes.py \
  data_agent/test_paper9_agent_governance.py \
  data_agent/test_paper9_agent_evaluation.py \
  data_agent/test_finals_preflight.py \
  data_agent/test_finals_deployment_contract.py
```

结果：`73 passed, 1 warning`。警告来自 OpenTelemetry 依赖的弃用提示，不影响测试结论。

接口兼容测试命令：

```bash
.venv/bin/python -m pytest -q \
  data_agent/test_model_gateway.py \
  data_agent/test_tool_filter.py
```

结果：`52 passed, 3 warnings`。测试已与当前 DeepSeek thinking 配置、Gemma 4 离线优选和六字段意图路由接口对齐。

## 3. 其他可重复检查

```bash
uvx ruff check \
  data_agent/finals_preflight.py \
  data_agent/paper9_agent_governance.py \
  data_agent/paper9_agent_evaluation.py \
  data_agent/paper9_agent_prompt.py \
  data_agent/world_model_v21_presentation.py \
  scripts/check_gemma4_finals_preflight.py \
  scripts/run_paper9_adk_reliability_eval.py \
  scripts/run_paper9_finals_contract_eval.py \
  scripts/build_gemma4_finals_ppt.py
```

结果：`All checks passed!`

```bash
.venv/bin/python scripts/run_paper9_finals_contract_eval.py
```

结果：`5/5`，报告写入 `data_agent/demo_evidence/paper9/finals_20260730/behavior_contract_report.json`。

```bash
cd frontend && npm run build
```

结果：构建成功。当前仍有 loader `spawn` 导出提示和大于 500 kB 的 chunk 警告，因此不能表述为“零警告构建”。

```bash
docker compose -f docker-compose.gemma4-demo.yml config --quiet
docker compose -f docker-compose.gemma4-demo.yml ps
```

结果：配置解析通过；app、db、redis 均为 `healthy`。正式换机时仍应先复制 `.env.finals.example` 为 `.env.finals` 并填写主机绝对路径。

PPT 交付检查：

```bash
uv run python scripts/build_gemma4_finals_ppt.py
unzip -t docs/finals/GIS_Data_Agent_Gemma4_Finals_CN.pptx
pdfinfo docs/finals/GIS_Data_Agent_Gemma4_Finals_CN.pdf
```

结果：PPTX 为 11 页且 11 页均含 speaker notes；ZIP 包无损坏；LibreOffice 成功导出 11 页、
16:9 PDF。主 6 页与附录 5 页逐页检查无重叠和裁切，主路演不含旧版指标或未解释的内部代号；
`release_manifest.sha256` 已按最终 PPTX/PDF 重建并通过校验。

## 4. 与模型和算法证据的关系

| 证据 | 数量 | 证明对象 |
|---|---:|---|
| 确定性行为契约 | 5/5 | 治理状态机和经验写入规则 |
| 真实 Gemma 4 26B + ADK | 30/30 | 三类受控场景中的工具选择、停止和恢复 |
| 真实 MPC 规划 | 锁定路径 2 次 + 新版浏览器 1 次 | 当前 0.3.3 / 2.2.3 代码绑定、MPC 执行、空间产物、硬约束校验和经验写入 |

30/30 的总体 Wilson 95% 区间为 88.65%–100%，规划工具在该评测中使用确定性替身。真实 MPC 运行复用了历史数据准备与 ONNX 产物。详细主张边界见 [claim_register.md](claim_register.md)。

## 5. 已知非阻断项

- 前端主包较大，赛后应继续拆分；当前不影响本机决赛演示。
- 运行时回归保留 5 个 ADK/asyncio 依赖弃用警告；真实 MPC 保留空分组除法 RuntimeWarning，均未中止验收，不能表述为零警告。
- 恢复的数据库卷含非决赛 UWM migration ownership 日志；不能描述为全仓库零警告运行。
- 仍需按 [rehearsal_log.md](rehearsal_log.md) 完成真实投影设备上的三轮计时彩排。
- 完整六次函数调用与非空地图截图已自动留存；该截图生成于快速调用耗时精度调整前，只作链路证据。五个视频尚未录制，最终录制前需按最新版演示脚本人工复跑并覆盖截图。
