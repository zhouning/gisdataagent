# GIS Data Agent — AgentOps 架构实现评审

> 评审日期: 2026-04-02 | 版本: v16.0 | 分支: feat/v12-extensible-platform

## 概述

GIS Data Agent 在 AgentOps 方面已建立 **12 个专职模块、约 2,800 行代码**的完整体系，覆盖可观测性、模型路由、Prompt 版控、评估框架、Token 经济、容错发现、运行时管控和部署管线八大领域。

---

## 一、六层可观测性体系

**模块**: `observability.py` (567 行)

| 层级 | Prometheus 指标 | 说明 |
|------|----------------|------|
| LLM | `agent_llm_calls_total`, `_latency`, `_tokens` | 模型调用粒度追踪 |
| Tool | `agent_tool_calls_total`, `_latency`, `_errors` | 工具执行追踪 |
| Pipeline | `agent_pipeline_duration`, `_steps` | 管线端到端耗时 |
| Cache | `agent_cache_hits`, `agent_cache_misses` | 语义缓存命中率 |
| Circuit Breaker | `agent_circuit_breaker_state` | 熔断器状态变化 |
| HTTP | `ObservabilityMiddleware` | 请求级 P50/P99 延迟 |

**AlertEngine**:
- 基于阈值的告警规则 (DB 持久化: `agent_alert_rules`)
- Webhook 推送 + cooldown 防抖机制
- 告警历史记录 (`agent_alert_history`)

**API 端点**: `GET /metrics` (Prometheus 导出)

---

## 二、模型路由

**模块**: `model_gateway.py` (101 行)

- **模型注册表**: 3 个 Gemini 模型
  - `gemini-2.0-flash` — 低延迟/低成本
  - `gemini-2.5-flash` — 平衡型
  - `gemini-2.5-pro` — 高质量推理
- **ModelRouter**: 按 `task_type` + `context_tokens` + `quality_requirement` + `budget` 四维度自动选型
- 成本追踪归因到 scenario / project_id

**API 端点**: `GET /api/gateway/models`, `GET /api/gateway/cost-summary`

---

## 三、Prompt 版本管理

**模块**: `prompt_registry.py` (160 行)

- **环境隔离**: dev / staging / prod 三环境独立部署
- **存储**: DB (`agent_prompt_versions`) + YAML fallback (DB 不可用时降级)
- **生命周期**: `create_version()` → `deploy()` → `rollback()`
- 支持按 agent_name + environment 查询版本历史

**API 端点**: `GET /api/prompts/versions`, `POST /api/prompts/deploy`

---

## 四、评估框架

**模块**: `eval_scenario.py` (131 行) + `eval_history.py` (243 行)

### 场景化评估
- `EvalScenario` 抽象基类 — 定义评估接口
- `SurveyingQCScenario` 实现 — 测绘质检专用指标:
  - `defect_precision` / `defect_recall` / `defect_f1` / `fix_success_rate`
- Golden Dataset 管理 (`agent_eval_datasets` 表)

### 评估历史
- `record_eval_result()` — 写入评估结果 (`agent_eval_history`)
- `get_eval_trend()` — 趋势分析
- `compare_eval_runs()` — 跨轮次 delta 对比，回归检测

**API 端点**: `POST /api/eval/datasets`, `POST /api/eval/run`, `GET /api/eval/scenarios`

---

## 五、Token 经济

**模块**: `token_tracker.py` (306 行)

| 能力 | 函数 | 说明 |
|------|------|------|
| 成本计算 | `calculate_cost_usd()` | 模型感知的 USD 定价 |
| 事前预估 | `estimate_pipeline_cost()` | Pipeline 运行前成本预估 |
| 记录消费 | `record_usage()` | per-user / per-pipeline / per-scenario 归因 |
| 预算门控 | `check_usage_limit()` | 超限拦截 |
| 汇总报表 | `get_usage_summary()` | 按时间/用户/管线聚合 |
| 拆分明细 | `get_pipeline_breakdown()` | 管线内各步骤消费 |

**DB 表**: `token_usage` (含 scenario、project_id 归因字段)

---

## 六、容错与服务发现

### 熔断器 (`circuit_breaker.py`, 151 行)

- **三态状态机**: `closed` → `open` → `half_open`
- 参数: failure_threshold=5, cooldown=120s, window=300s
- 线程安全 (`threading.Lock`)
- 状态变化上报 Prometheus

### Agent 注册 (`agent_registry.py`, 177 行)

- **注册**: `register_agent()` — 写入 `agent_registry` 表
- **发现**: `discover_agents()` — 按能力过滤可用 Agent
- **心跳**: `heartbeat()` — 定期刷新存活状态
- **远程调用**: `invoke_remote_agent()` — A2A RPC
- **过期清理**: `mark_stale_agents()` — 标记超时节点

### 健康检查 (`health.py`, 288 行)

- **K8s 探针**: `GET /health/live` (liveness), `GET /health/ready` (readiness)
- **组件诊断**: `check_database()`, `check_cloud_storage()`, `check_redis()`
- **启动摘要**: `format_startup_summary()` — 系统状态一览

---

## 七、运行时管控

### 特性开关 (`feature_flags.py`, 215 行)

- **双源配置**: 环境变量 (`FEATURE_FLAGS=flag1:true,flag2:false`) + DB 持久化 (`agent_feature_flags`)
- **运行时热切换**: `set_flag()` / `delete_flag()` / `reload_flags()`
- **API**: `GET/POST /api/admin/flags`

### Context 预算管理 (`context_manager.py`, 96 行)

- `ContextBlock` — 结构化上下文块 (content + relevance + token_count)
- `ContextProvider` ABC — 可插拔上下文源
- `SemanticProvider` — 包装 `semantic_layer.py`
- `ContextManager` — Token 预算编排 + 相关性优先级裁剪

**API**: `GET /api/context/preview`

### 无头管线执行 (`pipeline_runner.py`, 361 行)

- `PipelineResult` 数据类 — 零 Chainlit 依赖的结果封装
- `run_pipeline_headless()` — 批处理模式
- `run_pipeline_streaming()` — SSE 流式模式
- 集成 Token 追踪、熔断器、特性开关

### 输入/输出护栏 (`guardrails.py`)

- 请求内容安全检查
- 响应质量控制

---

## 八、部署管线

| 文件 | 用途 |
|------|------|
| `docker-compose.staging.yml` | Staging 环境编排 |
| `.github/workflows/cd-staging.yml` | Staging 持续部署 |
| `.github/workflows/cd-production.yml` | Production 持续部署 |
| `terraform/main.tf` | 基础设施即代码 (IaC) |

---

## 模块成熟度矩阵

| 模块 | 行数 | 成熟度 | DB 表 |
|------|------|--------|-------|
| observability.py | 567 | Production | `agent_alert_rules`, `agent_alert_history` |
| model_gateway.py | 101 | Production | — |
| prompt_registry.py | 160 | Production | `agent_prompt_versions` |
| eval_scenario.py | 131 | Production | `agent_eval_datasets` |
| eval_history.py | 243 | Production | `agent_eval_history` |
| token_tracker.py | 306 | Production | `token_usage` |
| circuit_breaker.py | 151 | Production | — |
| agent_registry.py | 177 | Production | `agent_registry` |
| health.py | 288 | Production | — |
| feature_flags.py | 215 | Production | `agent_feature_flags` |
| pipeline_runner.py | 361 | Production | — |
| context_manager.py | 96 | Tech Preview | — |

**总计**: ~2,800 LOC | **10/12 Production-Ready** | **2/12 Tech Preview**

---

## 架构亮点

1. **全链路覆盖**: 六层 Prometheus 指标从 LLM 调用到 HTTP 请求全量采集
2. **安全发布**: Prompt 版本管理 + 环境隔离 = 分级灰度能力
3. **成本可控**: 模型路由 + Token 预算门控 = 自动选型 + 超限拦截
4. **分布式就绪**: 熔断器 + 心跳发现 + A2A RPC = 微服务扩展基座
5. **无头执行**: `pipeline_runner.py` 支持 CI/CD 和批处理场景
6. **特性开关**: 环境变量 + DB 双源热切换，运维无需重部署

---

## 可增强方向

| 方向 | 现状 | 建议 | 优先级 | Roadmap |
|------|------|------|--------|---------|
| 分布式追踪 (Tracing) | Metrics 完整但缺少 OpenTelemetry span 级追踪 | 引入 OTel SDK，Pipeline/Tool 级 span 注入 | P1 | v21.0+ |
| 评估场景扩展 | 仅 `SurveyingQCScenario` | 补充 Optimization/General/Governance 管线场景 | P2 | — |
| Context Manager 深化 | 框架骨架在，SemanticProvider 功能有限 | 增加 KnowledgeGraph/Memory 作为 ContextProvider | P2 | — |
| A/B Testing | Feature Flags 仅支持开关 | 增加 traffic splitting + 指标对比能力 | P3 | — |
| Guardrails 联动 | 独立运行 | 与 Prompt Registry 绑定（版本级护栏策略） | P3 | — |
| 回归自动化 | `compare_eval_runs()` 仅手动 | CI Pipeline 中自动执行 eval + 回归阻断 | P2 | — |

---

## 参考

- BCG "Building Effective Enterprise Agents" 框架 → 已落地 Prompt Registry、Model Gateway、Context Manager、Eval Scenario 四大组件
- CLAUDE.md 中 BCG Platform Features (v15.8) 章节
- `docs/roadmap.md` v18.0-v21.0 分布式架构规划
