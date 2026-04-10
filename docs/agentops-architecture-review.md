# GIS Data Agent — AgentOps 架构实现评审

> 评审日期: 2026-04-10 | 版本: v23.0 | 分支: feat/v12-extensible-platform

## 概述

GIS Data Agent 在 AgentOps 方面已建立 **20+ 专职模块、约 6,400 行代码**的完整体系，覆盖可观测性（含 OTel 分布式追踪）、模型路由（多模型网关）、Prompt 版控、评估框架（15 内置评估器）、Token 经济、容错发现、运行时管控（ContextEngine + FeedbackLoop）、API 安全和部署管线九大领域。

---

## 一、六层可观测性体系 + OTel 分布式追踪

**模块**: `observability.py` (602 行) + `otel_tracing.py` (167 行)

| 层级 | Prometheus 指标 | 说明 |
|------|----------------|------|
| LLM | `agent_llm_calls_total`, `_latency`, `_tokens` | 模型调用粒度追踪 |
| Tool | `agent_tool_calls_total`, `_latency`, `_errors` | 工具执行追踪 |
| Pipeline | `agent_pipeline_duration`, `_steps` | 管线端到端耗时 |
| Cache | `agent_cache_hits`, `agent_cache_misses` | 语义缓存命中率 |
| Circuit Breaker | `agent_circuit_breaker_state` | 熔断器状态变化 |
| HTTP | `ObservabilityMiddleware` | 请求级 P50/P99 延迟 |

**OTel 分布式追踪** (v23.0, `otel_tracing.py`):
- 4 级 span 层次: Pipeline → Agent → Tool → LLM
- 优雅降级: OTel SDK 不可用时静默跳过，不影响业务
- Span 属性: user_id, pipeline_type, tool_name, model_name, token_count

**AlertEngine**:
- 基于阈值的告警规则 (DB 持久化: `agent_alert_rules`)
- Webhook 推送 + cooldown 防抖机制
- 告警历史记录 (`agent_alert_history`)

**API 端点**: `GET /metrics` (Prometheus 导出)

---

## 二、统一模型网关

**模块**: `model_gateway.py` (449 行)

- **多模型注册表** (v23.0 大幅扩展):
  - **在线模型**: Gemini 2.0 Flash (低延迟) / 2.5 Flash (平衡) / 2.5 Pro (高质量)
  - **离线模型**: Gemma 4 31B (Gemini API + vLLM 双路径)
  - **LiteLLM 适配**: 统一 API 接口，支持动态注册新模型
- **ModelRouter**: 按 `task_type` + `context_tokens` + `quality_requirement` + `budget` 四维度自动选型
- **ModelConfigManager** (v23.0): DB 持久化管理员模型配置 (`agent_model_configs` 表)，前端交互式切换
- **可配置 Intent Router**: 管理员可切换路由器使用的模型
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

**模块**: `eval_scenario.py` (130 行) + `eval_history.py` (242 行) + `evaluator_registry.py` (665 行)

### 场景化评估
- `EvalScenario` 抽象基类 — 定义评估接口
- `SurveyingQCScenario` 实现 — 测绘质检专用指标:
  - `defect_precision` / `defect_recall` / `defect_f1` / `fix_success_rate`
- Golden Dataset 管理 (`agent_eval_datasets` 表)

### 可插拔评估器注册表 (v23.0)
- `EvaluatorRegistry` — 15 内置评估器，4 大类:
  - **质量**: 输出完整性、格式合规、语义一致性
  - **安全**: Prompt 注入检测、PII 泄露检查、沙箱逃逸检测
  - **性能**: 延迟阈值、Token 效率、工具调用次数
  - **准确性**: 事实核查、空间精度、数值一致性
- 可插拔: 用户可注册自定义评估器

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

### 特性开关 (`feature_flags.py`, 214 行)

- **双源配置**: 环境变量 (`FEATURE_FLAGS=flag1:true,flag2:false`) + DB 持久化 (`agent_feature_flags`)
- **运行时热切换**: `set_flag()` / `delete_flag()` / `reload_flags()`
- **API**: `GET/POST /api/admin/flags`

### ContextEngine 统一上下文引擎 (`context_engine.py`, 583 行, v19.0)

> 替代 v15.8 的 `context_manager.py` (59 行)，从单一 Provider 扩展为 6 个内置 Provider。

- **6 个 ContextProvider**:
  - `SemanticLayerProvider` — 语义目录 + 域层级
  - `KnowledgeBaseProvider` — 知识库文档检索
  - `KnowledgeGraphProvider` — 图谱关系查询
  - `ReferenceQueryProvider` — 历史成功查询 few-shot
  - `SuccessStoryProvider` — 用户正反馈案例
  - `MetricDefinitionProvider` — 指标定义 + 计算公式
- **Token 预算编排**: 按 relevance_score 排序 + 贪心填充 (100k 上限)
- **TTL 缓存**: 3 分钟，相同 query + task_type 命中缓存
- **Per-provider 错误隔离**: 单个 Provider 失败不影响其他

**API**: `GET /api/context/preview`

### FeedbackLoop 反馈飞轮 (`feedback.py`, 368 行, v19.0)

- **FeedbackStore**: 用户 👍👎 反馈持久化 (`agent_feedback` 表)
- **Upvote 路径**: 正反馈查询 → `ReferenceQueryStore` 自动入库 → NL2SQL few-shot 精度提升
- **Downvote 路径**: 负反馈 → `FailureAnalyzer` 分析 → `PromptOptimizer` 改进建议
- **前端**: `FeedbackBar.tsx` (消息级反馈) + `FeedbackTab.tsx` (反馈看板)

**API**: `POST /api/feedback`, `GET /api/feedback/stats` (5 端点)

### ReferenceQueryStore 参考查询库 (`reference_queries.py`, 395 行, v19.0)

- Embedding 语义搜索 (Gemini text-embedding-004, 768 维)
- 自动/手动策展，cosine > 0.92 去重
- ContextEngine 集成: `ReferenceQueryProvider` 注入 few-shot 示例

**API**: CRUD + 搜索 + 批量导入 (6 端点)

### PromptOptimizer 提示词优化 (`prompt_optimizer.py`, 436 行, v23.0)

- 从 `agent_feedback` 收集负反馈 bad cases
- 分类失败模式 (工具选择错误 / 参数错误 / 幻觉 / 格式错误)
- 生成 prompt 改进建议 (可人工审核后应用)

### 无头管线执行 (`pipeline_runner.py`, 360 行)

- `PipelineResult` 数据类 — 零 Chainlit 依赖的结果封装
- `run_pipeline_headless()` — 批处理模式
- `run_pipeline_streaming()` — SSE 流式模式
- 集成 Token 追踪、熔断器、特性开关

### 输入/输出护栏 (`guardrails.py`, 398 行)

- YAML 驱动的工具访问控制
- 请求内容安全检查 (24 模式 `FORBIDDEN_PATTERNS`)
- 响应质量控制

---

## 八、API 安全中间件 (v22.0)

**模块**: `api_middleware.py` (169 行)

### RateLimitMiddleware
- 基于滑动窗口的请求频率限制
- Per-user / per-IP 粒度
- 超限返回 429 Too Many Requests

### CircuitBreakerMiddleware
- Starlette 层熔断器，保护下游服务
- 与 `circuit_breaker.py` 集成
- 自动降级响应

**集成方式**: Starlette 中间件栈，无需 Kong/Nginx 等外部网关。

---

## 九、部署管线

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
| observability.py | 602 | Production | `agent_alert_rules`, `agent_alert_history` |
| otel_tracing.py | 167 | Production | — |
| model_gateway.py | 449 | Production | `agent_model_configs` |
| prompt_registry.py | 159 | Production | `agent_prompt_versions` |
| eval_scenario.py | 130 | Production | `agent_eval_datasets` |
| eval_history.py | 242 | Production | `agent_eval_history` |
| evaluator_registry.py | 665 | Production | — |
| token_tracker.py | 305 | Production | `token_usage` |
| circuit_breaker.py | 150 | Production | — |
| agent_registry.py | 176 | Production | `agent_registry` |
| health.py | 283 | Production | — |
| feature_flags.py | 214 | Production | `agent_feature_flags` |
| pipeline_runner.py | 360 | Production | — |
| context_engine.py | 583 | Production | — |
| feedback.py | 368 | Production | `agent_feedback` |
| reference_queries.py | 395 | Production | `agent_reference_queries` |
| prompt_optimizer.py | 436 | Production | — |
| guardrails.py | 398 | Production | — |
| api_middleware.py | 169 | Production | — |
| lite_mode.py | 206 | Production | — |

**总计**: ~6,400 LOC | **20/20 Production-Ready**

---

## 架构亮点

1. **全链路覆盖**: 六层 Prometheus 指标 + OTel 4 级 span 从 LLM 调用到 HTTP 请求全量采集
2. **安全发布**: Prompt 版本管理 + 环境隔离 = 分级灰度能力
3. **成本可控**: 多模型网关 (Gemini+Gemma+LiteLLM) + Token 预算门控 = 自动选型 + 超限拦截
4. **分布式就绪**: 熔断器 + 心跳发现 + A2A RPC = 微服务扩展基座
5. **无头执行**: `pipeline_runner.py` 支持 CI/CD 和批处理场景
6. **特性开关**: 环境变量 + DB 双源热切换，运维无需重部署
7. **上下文飞轮**: ContextEngine (6 Provider) + FeedbackLoop + ReferenceQueryStore = 越用越准
8. **反馈闭环**: 👍→参考查询自动入库→NL2SQL 精度提升；👎→失败分析→PromptOptimizer 改进
9. **API 安全**: RateLimitMiddleware + CircuitBreakerMiddleware，Starlette 层无需外部网关
10. **评估深度**: 15 内置评估器 (4 大类) + 场景化评估 + Golden Dataset + 回归检测

---

## 可增强方向

| 方向 | 现状 | 建议 | 优先级 | 状态 |
|------|------|------|--------|------|
| 分布式追踪 (Tracing) | ✅ OTel 4 级 span 已实现 (`otel_tracing.py`) | 接入 Jaeger/Tempo 后端 | P3 | v23.0 已实现 |
| 评估场景扩展 | ✅ 15 内置评估器 + `SurveyingQCScenario` | 补充 Optimization/Governance 管线场景 | P3 | v23.0 部分实现 |
| Context Manager 深化 | ✅ ContextEngine 6 Provider 已实现 | 增加 embedding 缓存优化 | P3 | v19.0 已实现 |
| 反馈闭环 | ✅ FeedbackLoop + PromptOptimizer 已实现 | 自动化 prompt 改进审批流程 | P3 | v19.0/v23.0 已实现 |
| A/B Testing | Feature Flags 仅支持开关 | 增加 traffic splitting + 指标对比能力 | P3 | 待实现 |
| Guardrails 联动 | 独立运行 (398 行 YAML 驱动) | 与 Prompt Registry 绑定（版本级护栏策略） | P3 | 待实现 |
| 回归自动化 | `compare_eval_runs()` 仅手动 | CI Pipeline 中自动执行 eval + 回归阻断 | P2 | 待实现 |
| 多模型 A/B | ModelConfigManager 支持切换 | 按流量比例分配模型 + 效果对比 | P3 | 待实现 |

---

## 参考

- BCG "Building Effective Enterprise Agents" 框架 → 已落地 Prompt Registry、统一模型网关、ContextEngine、Eval Scenario + EvaluatorRegistry 四大组件
- Datus.ai 对标 → 已落地 ContextEngine (6 Provider)、FeedbackLoop、ReferenceQueryStore、MetricFlow 语义模型
- CLAUDE.md 中 BCG Platform Features (v15.8) 章节
- `docs/roadmap.md` 全版本规划
