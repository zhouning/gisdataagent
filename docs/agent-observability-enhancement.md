# GIS Data Agent — 智能体可观测性完善方案

> 版本: v1.0 | 日期: 2026-03-21 | 状态: 架构规划

---

## 1. 现状审计

### 1.1 现有可观测性资产清单

| 模块 | 文件 | 能力 | 成熟度 |
|------|------|------|--------|
| 结构化日志 | `observability.py` | JsonFormatter + text 双模式，trace_id/user_id 自动注入 | ★★★★☆ |
| Prometheus 指标 | `observability.py` | 4 个指标：pipeline_runs / tool_calls / auth_events / pipeline_duration | ★★☆☆☆ |
| Agent 生命周期 Hook | `agent_hooks.py` | before/after agent callback，ProgressTracker 百分比追踪 | ★★★☆☆ |
| Token 追踪 | `token_tracker.py` | PostgreSQL 持久化，日/月限额，分 Pipeline 统计 | ★★★★☆ |
| 审计日志 | `audit_logger.py` | 31 种操作类型，JSONB 详情，90 天保留 | ★★★★★ |
| Pipeline 分析 | `pipeline_analytics.py` | 5 个 REST API（延迟分位数/工具成功率/Token 效率/吞吐/Agent 分解） | ★★★★☆ |
| Pipeline 执行追踪 | `pipeline_runner.py` | PipelineResult 含 tool_execution_log + provenance_trail | ★★★☆☆ |
| 错误分类 | `pipeline_helpers.py` | 5 类错误（transient/permission/data_format/config/unknown） | ★★★☆☆ |
| 熔断器状态 | `circuit_breaker.py` | 三态（closed/open/half_open）+ failure/success 计数 | ★★★☆☆ |
| 健康检查 | `health.py` | 5 个子系统（DB/Cloud/Redis/Session/MCP）+ K8s 就绪探针 | ★★★★☆ |
| 成本守卫 Plugin | `plugins.py` | CostGuardPlugin: before/after_model 累计 Token，abort 阈值 | ★★★☆☆ |
| 工具重试 Plugin | `plugins.py` | GISToolRetryPlugin: 错误提取 + 失败学习 | ★★★☆☆ |
| 溯源 Plugin | `plugins.py` | ProvenancePlugin: 决策审计轨迹写入 session state | ★★★☆☆ |
| 自修正回调 | `utils.py` | _self_correction_after_tool: 质量门 + 重试 + 历史失败提示 | ★★★☆☆ |
| Trace ID | `user_context.py` | ContextVar 生成 12 字符 UUID，JSON 日志注入 | ★★☆☆☆ |

### 1.2 关键差距分析

```
                    当前覆盖                               缺失区域
┌─────────────────────────────────┐    ┌─────────────────────────────────────────┐
│ ✅ Pipeline 级别执行追踪        │    │ ❌ 无 OpenTelemetry 分布式追踪           │
│ ✅ Token 消耗记录与限额         │    │ ❌ 无 Agent 思考过程（reasoning）可视化  │
│ ✅ 审计日志（31 种操作）        │    │ ❌ 无 LLM 调用级延迟直方图              │
│ ✅ 4 个 Prometheus 指标         │    │ ❌ 无每工具延迟直方图                    │
│ ✅ Agent before/after hook      │    │ ❌ 无 HTTP API 请求指标                  │
│ ✅ 错误分类 5 类                │    │ ❌ 无缓存命中率指标                      │
│ ✅ 熔断器三态                   │    │ ❌ 无 Agent 决策路径可视化               │
│ ✅ 成本守卫 abort 阈值          │    │ ❌ Trace ID 未传播到外部服务             │
│                                 │    │ ❌ 无实时 Agent 行为 Dashboard           │
│                                 │    │ ❌ 无 Agent 质量评估（幻觉/忠实度）     │
│                                 │    │ ❌ 无 Workflow DAG 执行可视化            │
└─────────────────────────────────┘    └─────────────────────────────────────────┘
```

### 1.3 核心痛点

1. **Agent 黑盒**: 当 Pipeline 耗时异常或产出质量差时，无法定位是哪个 Agent/哪次 LLM 调用/哪个工具拖慢或出错
2. **无端到端追踪链**: trace_id 只在本进程内日志可见，不能串联 Agent → LLM API → Tool → PostGIS → 外部服务
3. **指标粒度不足**: 仅 4 个 Prometheus 指标，缺少 LLM 调用延迟、工具延迟、缓存效率、队列深度等关键运营指标
4. **Agent 决策不透明**: 用户和运维人员无法看到 Agent 为什么选择了某个工具、拒绝了某个路径

---

## 2. ADK 官方可观测性能力

### 2.1 ADK 6 层回调体系

ADK 提供了完整的 Agent 生命周期回调，每一层都可注入可观测性逻辑：

```
┌────────────────────────────────────────────────────────────┐
│  ① before_agent_callback(callback_context)                 │
│     → Agent 开始执行，创建 Span                             │
│                                                            │
│    ┌────────────────────────────────────────────────────┐  │
│    │  ② before_model_callback(callback_context, request) │  │
│    │     → LLM 调用开始，记录 prompt token 估算          │  │
│    │                                                      │  │
│    │     [ Gemini API 调用 ]                              │  │
│    │                                                      │  │
│    │  ③ after_model_callback(callback_context, response)  │  │
│    │     → LLM 调用结束，记录 token/延迟/模型名           │  │
│    └────────────────────────────────────────────────────┘  │
│                                                            │
│    ┌────────────────────────────────────────────────────┐  │
│    │  ④ before_tool_callback(tool, args, tool_context)   │  │
│    │     → 工具调用开始，创建子 Span                      │  │
│    │                                                      │  │
│    │     [ 工具执行 ]                                     │  │
│    │                                                      │  │
│    │  ⑤ after_tool_callback(tool, args, ctx, response)   │  │
│    │     → 工具调用结束，记录延迟/成功/输出大小           │  │
│    └────────────────────────────────────────────────────┘  │
│                                                            │
│  ⑥ after_agent_callback(callback_context)                  │
│     → Agent 完成，关闭 Span，记录总 token/决策路径         │
└────────────────────────────────────────────────────────────┘
```

### 2.2 ADK 官方 OpenTelemetry 集成

ADK Advanced 文档明确指出：

> "ADK supports OpenTelemetry, a powerful framework for observability, allowing integration with various monitoring and tracing platforms — Google Cloud Trace, AgentOps, Arize AX, Phoenix, Weave by WandB."

官方推荐方案：
- **Tracing**: OpenTelemetry → Cloud Trace / Jaeger / Zipkin
- **Logging**: OpenTelemetry → Cloud Logging / ELK / Loki
- **Metrics**: OpenTelemetry → Prometheus / Cloud Monitoring
- **长期存储**: BigQuery（通过 Log Router Sink）
- **可视化**: Looker Studio / Grafana 模板

### 2.3 ADK Plugin 可观测性模式

ADK 文档明确列出 Plugin 的三大可观测性用途：

1. **Logging & Tracing**: 创建 agent/tool/LLM 活动的详细日志
2. **Policy Enforcement**: before_tool_callback 阻止未授权操作
3. **Monitoring & Metrics**: 收集 token 使用、执行时间、调用计数并导出到 Prometheus

---

## 3. 完善方案：Agent 可观测性增强

### 3.1 总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         应用层（ADK Agent）                           │
│                                                                      │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────────────┐  │
│  │ Agent   │  │  LLM     │  │  Tool    │  │  Pipeline/Workflow  │  │
│  │ Hooks   │  │ Callbacks│  │ Callbacks│  │  Lifecycle          │  │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └──────────┬──────────┘  │
│       │            │             │                    │              │
│       └────────────┴─────────────┴────────────────────┘              │
│                              │                                       │
│                    ┌─────────▼──────────┐                            │
│                    │  ObservabilityHub   │ ← 统一采集层               │
│                    │  (新增模块)         │                            │
│                    └─────────┬──────────┘                            │
└──────────────────────────────┼───────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
    ┌─────▼─────┐    ┌────────▼────────┐   ┌──────▼──────┐
    │ OTel Spans │    │ Prometheus      │   │ Structured  │
    │ (Tracing)  │    │ Metrics         │   │ Logs (JSON) │
    └─────┬─────┘    └────────┬────────┘   └──────┬──────┘
          │                   │                    │
    ┌─────▼─────┐    ┌────────▼────────┐   ┌──────▼──────┐
    │ Jaeger /   │    │ Grafana         │   │ ELK / Loki  │
    │ Cloud Trace│    │ Dashboard       │   │             │
    └───────────┘    └─────────────────┘   └─────────────┘
```

### 3.2 新增 Prometheus 指标（从 4 → 25+）

#### 3.2.1 Agent 层指标

```python
# ────────── Agent 层 ──────────
# 已有 (agent_hooks.py):
#   agent_invocations_total{agent_name, pipeline_type}
#   agent_duration_seconds{agent_name, pipeline_type}

# 新增:
agent_llm_calls_total = Counter(
    "agent_llm_calls_total",
    "LLM 调用次数",
    ["agent_name", "model_name"],
)
agent_llm_duration_seconds = Histogram(
    "agent_llm_duration_seconds",
    "LLM 单次调用延迟",
    ["agent_name", "model_name"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
agent_llm_input_tokens = Histogram(
    "agent_llm_input_tokens",
    "LLM 单次调用输入 Token 数",
    ["agent_name", "model_name"],
    buckets=(100, 500, 1000, 2000, 5000, 10000, 50000),
)
agent_llm_output_tokens = Histogram(
    "agent_llm_output_tokens",
    "LLM 单次调用输出 Token 数",
    ["agent_name", "model_name"],
    buckets=(50, 100, 500, 1000, 2000, 5000),
)
agent_transfers_total = Counter(
    "agent_transfers_total",
    "Agent 间转移次数",
    ["from_agent", "to_agent"],
)
agent_loop_iterations_total = Counter(
    "agent_loop_iterations_total",
    "LoopAgent 循环次数",
    ["loop_agent_name", "reason"],     # reason: max_iter / escalation / quality_pass
)
```

#### 3.2.2 Tool 层指标

```python
# ────────── Tool 层 ──────────
# 已有 (observability.py):
#   agent_tool_calls_total{tool_name, status}

# 新增:
agent_tool_duration_seconds = Histogram(
    "agent_tool_duration_seconds",
    "工具单次调用延迟",
    ["tool_name", "agent_name"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
agent_tool_retries_total = Counter(
    "agent_tool_retries_total",
    "工具重试次数",
    ["tool_name", "error_category"],
)
agent_tool_output_bytes = Histogram(
    "agent_tool_output_bytes",
    "工具输出数据大小",
    ["tool_name"],
    buckets=(100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000),
)
agent_tool_quality_gate = Counter(
    "agent_tool_quality_gate",
    "质量门检查结果",
    ["tool_name", "result"],           # result: pass / warn / fail
)
```

#### 3.2.3 Pipeline & 系统层指标

```python
# ────────── Pipeline 层 ──────────
agent_intent_classification_total = Counter(
    "agent_intent_classification_total",
    "意图分类结果",
    ["intent", "language"],
)
agent_intent_duration_seconds = Histogram(
    "agent_intent_duration_seconds",
    "意图分类延迟",
    [],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5),
)
agent_pipeline_steps_total = Counter(
    "agent_pipeline_steps_total",
    "Pipeline 步骤执行",
    ["pipeline_type", "step_name", "status"],
)

# ────────── 缓存层 ──────────
agent_cache_operations_total = Counter(
    "agent_cache_operations_total",
    "缓存操作",
    ["cache_name", "operation"],       # operation: hit / miss / invalidate
)

# ────────── 队列层 ──────────
agent_task_queue_depth = Gauge(
    "agent_task_queue_depth",
    "任务队列深度",
    ["priority"],
)
agent_task_queue_wait_seconds = Histogram(
    "agent_task_queue_wait_seconds",
    "任务在队列中的等待时间",
    [],
    buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 300),
)

# ────────── 熔断器 ──────────
agent_circuit_breaker_state = Gauge(
    "agent_circuit_breaker_state",
    "熔断器状态 (0=closed, 1=open, 2=half_open)",
    ["tool_name"],
)
agent_circuit_breaker_trips_total = Counter(
    "agent_circuit_breaker_trips_total",
    "熔断器跳闸次数",
    ["tool_name"],
)

# ────────── HTTP API ──────────
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "REST API 请求延迟",
    ["method", "path", "status_code"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
http_requests_total = Counter(
    "http_requests_total",
    "REST API 请求总数",
    ["method", "path", "status_code"],
)
```

### 3.3 OpenTelemetry 分布式追踪

#### 3.3.1 新增 `otel_tracing.py`

```python
"""
OpenTelemetry 分布式追踪 — 端到端 Agent 调用链可视化。

Span 层次结构:
  pipeline_run (root span)
  ├── intent_classification
  ├── agent:{agent_name}
  │   ├── llm_call:{model_name}
  │   │   ├── llm_call:{model_name}  (可能多轮)
  │   ├── tool:{tool_name}
  │   │   ├── db_query (如果工具调用 PostGIS)
  │   │   └── file_io (如果工具读写文件)
  │   └── tool:{tool_name}
  └── agent:{agent_name}
      └── ...
"""
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes

from .user_context import current_user_id, current_trace_id, current_session_id


_tracer: Optional[trace.Tracer] = None


def setup_otel_tracing():
    """初始化 OpenTelemetry 追踪 — 在应用启动时调用一次"""
    global _tracer

    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: "gis-data-agent",
        ResourceAttributes.SERVICE_VERSION: "14.3.1",
        "deployment.environment": os.getenv("DEPLOY_ENV", "development"),
    })

    provider = TracerProvider(resource=resource)

    # 根据环境选择 Exporter
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otel_endpoint:
        # 生产: 导出到 Jaeger / Cloud Trace / Tempo
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        exporter = OTLPSpanExporter(endpoint=otel_endpoint)
    else:
        # 开发: 输出到控制台
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("gis-data-agent", "14.3.1")


def get_tracer() -> trace.Tracer:
    """获取 Tracer 实例"""
    global _tracer
    if _tracer is None:
        setup_otel_tracing()
    return _tracer


@asynccontextmanager
async def trace_pipeline_run(pipeline_type: str, intent: str):
    """
    Pipeline 运行的根 Span。

    用法:
        async with trace_pipeline_run("optimization", "land_use") as span:
            result = await run_pipeline(...)
            span.set_attribute("pipeline.tokens.total", result.total_tokens)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"pipeline:{pipeline_type}",
        attributes={
            "pipeline.type": pipeline_type,
            "pipeline.intent": intent,
            "user.id": current_user_id.get("anonymous"),
            "session.id": current_session_id.get("default"),
            "trace.correlation_id": current_trace_id.get(""),
        },
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


@asynccontextmanager
async def trace_agent_run(agent_name: str, pipeline_type: str):
    """Agent 执行 Span"""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"agent:{agent_name}",
        attributes={
            "agent.name": agent_name,
            "agent.pipeline_type": pipeline_type,
        },
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise


@asynccontextmanager
async def trace_llm_call(agent_name: str, model_name: str):
    """LLM 调用 Span — 记录 Token 和延迟"""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"llm:{model_name}",
        attributes={
            "llm.model": model_name,
            "llm.agent": agent_name,
            "llm.provider": "google",
        },
    ) as span:
        start = time.monotonic()
        try:
            yield span
        finally:
            span.set_attribute("llm.duration_ms", (time.monotonic() - start) * 1000)


@asynccontextmanager
async def trace_tool_call(tool_name: str, agent_name: str, args: dict):
    """工具调用 Span"""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"tool:{tool_name}",
        attributes={
            "tool.name": tool_name,
            "tool.agent": agent_name,
            "tool.args_keys": ",".join(args.keys()) if args else "",
        },
    ) as span:
        start = time.monotonic()
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        finally:
            span.set_attribute("tool.duration_ms", (time.monotonic() - start) * 1000)
```

#### 3.3.2 Span 层次示例

一次完整 Pipeline 执行在 Jaeger/Tempo 中的可视化效果：

```
pipeline:optimization                                    [12.4s]
├── intent_classification                                [0.3s]
├── agent:parallel_data_ingestion                        [2.1s]
│   ├── agent:exploration_planner                        [1.8s]
│   │   ├── llm:gemini-2.5-flash                         [0.6s]  tokens: 1200→350
│   │   ├── tool:load_spatial_data                       [0.9s]  file: landuse.shp
│   │   └── tool:describe_spatial_data                   [0.3s]
│   └── agent:semantic_pre_fetch                         [1.5s]
│       ├── llm:gemini-2.5-flash                         [0.4s]  tokens: 800→200
│       └── tool:query_semantic_layer                    [1.1s]  cache: miss
├── agent:data_processing                                [3.2s]
│   ├── llm:gemini-2.5-flash                             [0.8s]  tokens: 3000→500
│   ├── tool:spatial_join                                [1.5s]  rows: 15000
│   └── tool:calculate_area                              [0.9s]
├── agent:analysis_quality_loop                          [4.5s]
│   ├── iteration:1                                      [3.0s]
│   │   ├── agent:analysis_planner                       [2.5s]
│   │   │   ├── llm:gemini-2.5-pro                       [1.2s]  tokens: 5000→800
│   │   │   └── tool:run_optimization                    [1.3s]  ← DRL 推理
│   │   └── agent:quality_checker                        [0.5s]
│   │       └── llm:gemini-2.5-flash                     [0.5s]  verdict: retry
│   └── iteration:2                                      [1.5s]
│       ├── agent:analysis_planner                       [1.0s]
│       └── agent:quality_checker                        [0.5s]
│           └── llm:gemini-2.5-flash                     [0.5s]  verdict: pass ✓
├── agent:data_visualization                             [1.5s]
│   ├── llm:gemini-2.5-flash                             [0.5s]
│   └── tool:create_choropleth_map                       [1.0s]
└── agent:data_summary                                   [0.8s]
    └── llm:gemini-2.5-pro                               [0.8s]  tokens: 4000→1200
```

### 3.4 Agent 决策追踪增强

#### 3.4.1 新增 `agent_decision_tracer.py`

```python
"""
Agent 决策追踪 — 记录 Agent 的推理过程、工具选择理由、拒绝路径。

与 ProvenancePlugin 互补:
  - ProvenancePlugin: 记录 "发生了什么"（事件轨迹）
  - DecisionTracer:   记录 "为什么"（推理过程 + 备选方案）
"""
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DecisionEvent:
    """单个决策事件"""
    timestamp: float
    agent_name: str
    event_type: str          # tool_selection / tool_rejection / transfer / escalation / quality_gate
    decision: str            # 决策描述
    reasoning: str           # 推理依据（从 LLM 响应中提取）
    alternatives: list[str]  # 备选方案
    confidence: float        # 0.0 ~ 1.0 (从 LLM 的选择确定性推断)
    context: dict            # 附加上下文


@dataclass
class DecisionTrace:
    """一次 Pipeline 执行的完整决策轨迹"""
    pipeline_type: str
    trace_id: str
    events: list[DecisionEvent] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    def add_tool_selection(self, agent_name: str, tool_name: str,
                           args: dict, reasoning: str = "",
                           alternatives: list[str] = None):
        """记录 Agent 选择了某个工具"""
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=agent_name,
            event_type="tool_selection",
            decision=f"选择工具 {tool_name}",
            reasoning=reasoning,
            alternatives=alternatives or [],
            confidence=0.0,   # 后续从 LLM logprobs 填充
            context={"tool_name": tool_name, "args_keys": list(args.keys())},
        ))

    def add_tool_rejection(self, agent_name: str, tool_name: str, reason: str):
        """记录 Agent 拒绝了某个工具（来自 before_tool_callback 拦截）"""
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=agent_name,
            event_type="tool_rejection",
            decision=f"拒绝工具 {tool_name}",
            reasoning=reason,
            alternatives=[],
            confidence=0.0,
            context={"tool_name": tool_name},
        ))

    def add_agent_transfer(self, from_agent: str, to_agent: str, reason: str = ""):
        """记录 Agent 间控制转移"""
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=from_agent,
            event_type="transfer",
            decision=f"转移到 {to_agent}",
            reasoning=reason,
            alternatives=[],
            confidence=0.0,
            context={"to_agent": to_agent},
        ))

    def add_quality_gate(self, agent_name: str, verdict: str, feedback: str = ""):
        """记录质量门判定"""
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=agent_name,
            event_type="quality_gate",
            decision=f"质量判定: {verdict}",
            reasoning=feedback,
            alternatives=[],
            confidence=0.0,
            context={"verdict": verdict},
        ))

    def to_dict(self) -> dict:
        """序列化为可存储字典"""
        return {
            "pipeline_type": self.pipeline_type,
            "trace_id": self.trace_id,
            "duration_seconds": time.time() - self.start_time,
            "decision_count": len(self.events),
            "events": [
                {
                    "timestamp": e.timestamp,
                    "agent": e.agent_name,
                    "type": e.event_type,
                    "decision": e.decision,
                    "reasoning": e.reasoning,
                    "alternatives": e.alternatives,
                }
                for e in self.events
            ],
        }

    def to_mermaid_sequence(self) -> str:
        """生成 Mermaid 序列图 — 可嵌入前端可视化"""
        lines = ["sequenceDiagram"]
        lines.append("    participant U as 用户")
        agents_seen = set()
        for e in self.events:
            if e.agent_name not in agents_seen:
                lines.append(f"    participant {e.agent_name}")
                agents_seen.add(e.agent_name)

        for e in self.events:
            if e.event_type == "tool_selection":
                tool = e.context.get("tool_name", "?")
                lines.append(f"    {e.agent_name}->>+{e.agent_name}: 🔧 {tool}")
                lines.append(f"    Note right of {e.agent_name}: {e.reasoning[:40]}")
            elif e.event_type == "transfer":
                to = e.context.get("to_agent", "?")
                lines.append(f"    {e.agent_name}->>{to}: 转移控制")
            elif e.event_type == "quality_gate":
                verdict = e.context.get("verdict", "?")
                lines.append(f"    Note over {e.agent_name}: 质量门: {verdict}")

        return "\n".join(lines)
```

### 3.5 统一可观测性 Plugin

#### 3.5.1 新增 `observability_plugin.py`

```python
"""
ObservabilityPlugin — 统一可观测性 ADK Plugin。

整合 OpenTelemetry 追踪 + Prometheus 指标 + 结构化日志 + 决策追踪。
作为单一 Plugin 挂载到所有 Agent，替代分散的回调注册。
"""
import time
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse

from .observability import get_logger
from .otel_tracing import get_tracer, trace
from .agent_decision_tracer import DecisionTrace

logger = get_logger("observability_plugin")

# ─── Prometheus 指标引用 ───
from .observability_metrics import (
    agent_llm_calls_total,
    agent_llm_duration_seconds,
    agent_llm_input_tokens,
    agent_llm_output_tokens,
    agent_tool_duration_seconds,
    agent_tool_retries_total,
    agent_tool_quality_gate,
    agent_transfers_total,
)


class ObservabilityPlugin:
    """
    可观测性 Plugin — 挂载 6 层 ADK 回调。

    使用方式:
        plugin = ObservabilityPlugin(pipeline_type="optimization")
        agent = LlmAgent(
            ...,
            before_agent_callback=plugin.before_agent,
            after_agent_callback=plugin.after_agent,
            before_model_callback=plugin.before_model,
            after_model_callback=plugin.after_model,
            before_tool_callback=plugin.before_tool,
            after_tool_callback=plugin.after_tool,
        )
    """

    def __init__(self, pipeline_type: str, decision_trace: Optional[DecisionTrace] = None):
        self.pipeline_type = pipeline_type
        self.decision_trace = decision_trace
        self._agent_start_times: dict[str, float] = {}
        self._llm_start_times: dict[str, float] = {}
        self._tool_start_times: dict[str, float] = {}

    # ──────── ① before_agent ────────

    async def before_agent(self, callback_context: CallbackContext):
        agent_name = callback_context.agent_name
        self._agent_start_times[agent_name] = time.monotonic()

        # OTel Span
        tracer = get_tracer()
        span = tracer.start_span(
            f"agent:{agent_name}",
            attributes={
                "agent.name": agent_name,
                "agent.pipeline_type": self.pipeline_type,
            },
        )
        # 存入 callback_context.state 以便 after_agent 关闭
        callback_context.state[f"_otel_span_{agent_name}"] = span

        logger.debug("Agent started", extra={
            "agent": agent_name,
            "pipeline": self.pipeline_type,
        })
        return None

    # ──────── ⑥ after_agent ────────

    async def after_agent(self, callback_context: CallbackContext):
        agent_name = callback_context.agent_name
        duration = time.monotonic() - self._agent_start_times.pop(agent_name, time.monotonic())

        # 关闭 OTel Span
        span = callback_context.state.pop(f"_otel_span_{agent_name}", None)
        if span:
            span.set_attribute("agent.duration_seconds", duration)
            span.end()

        logger.info("Agent completed", extra={
            "agent": agent_name,
            "pipeline": self.pipeline_type,
            "duration_seconds": round(duration, 3),
        })
        return None

    # ──────── ② before_model ────────

    async def before_model(self, callback_context: CallbackContext, llm_request: LlmRequest):
        agent_name = callback_context.agent_name
        call_key = f"{agent_name}_{time.monotonic_ns()}"
        self._llm_start_times[call_key] = time.monotonic()
        callback_context.state["_llm_call_key"] = call_key

        # 记录请求大小 (估算)
        msg_count = len(llm_request.contents) if llm_request.contents else 0
        logger.debug("LLM call started", extra={
            "agent": agent_name,
            "message_count": msg_count,
        })
        return None

    # ──────── ③ after_model ────────

    async def after_model(self, callback_context: CallbackContext, llm_response: LlmResponse):
        agent_name = callback_context.agent_name
        call_key = callback_context.state.pop("_llm_call_key", "")
        duration = time.monotonic() - self._llm_start_times.pop(call_key, time.monotonic())

        # 提取 Token 和模型信息
        model_name = getattr(llm_response, "model", "unknown")
        usage = getattr(llm_response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        # Prometheus 指标
        agent_llm_calls_total.labels(agent_name=agent_name, model_name=model_name).inc()
        agent_llm_duration_seconds.labels(agent_name=agent_name, model_name=model_name).observe(duration)
        if input_tokens:
            agent_llm_input_tokens.labels(agent_name=agent_name, model_name=model_name).observe(input_tokens)
        if output_tokens:
            agent_llm_output_tokens.labels(agent_name=agent_name, model_name=model_name).observe(output_tokens)

        logger.info("LLM call completed", extra={
            "agent": agent_name,
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_seconds": round(duration, 3),
        })
        return None

    # ──────── ④ before_tool ────────

    async def before_tool(self, tool, args, tool_context):
        tool_name = tool.name
        agent_name = getattr(tool_context, "agent_name", "unknown")
        call_key = f"{tool_name}_{time.monotonic_ns()}"
        self._tool_start_times[call_key] = time.monotonic()
        tool_context.state["_tool_call_key"] = call_key

        # 决策追踪
        if self.decision_trace:
            self.decision_trace.add_tool_selection(
                agent_name=agent_name,
                tool_name=tool_name,
                args=args or {},
            )

        logger.debug("Tool call started", extra={
            "tool": tool_name,
            "agent": agent_name,
            "args_keys": list((args or {}).keys()),
        })
        return None

    # ──────── ⑤ after_tool ────────

    async def after_tool(self, tool, args, tool_context, tool_response):
        tool_name = tool.name
        agent_name = getattr(tool_context, "agent_name", "unknown")
        call_key = tool_context.state.pop("_tool_call_key", "")
        duration = time.monotonic() - self._tool_start_times.pop(call_key, time.monotonic())

        # 判断成功/失败
        is_error = False
        if isinstance(tool_response, dict):
            is_error = tool_response.get("status") == "error"

        # Prometheus
        agent_tool_duration_seconds.labels(
            tool_name=tool_name, agent_name=agent_name,
        ).observe(duration)

        if is_error:
            error_msg = tool_response.get("error", "") if isinstance(tool_response, dict) else ""
            logger.warning("Tool call failed", extra={
                "tool": tool_name,
                "agent": agent_name,
                "duration_seconds": round(duration, 3),
                "error": str(error_msg)[:200],
            })
        else:
            logger.info("Tool call completed", extra={
                "tool": tool_name,
                "agent": agent_name,
                "duration_seconds": round(duration, 3),
            })

        return None  # 不修改原始响应
```

#### 3.5.2 挂载到 Agent

在 `agent.py` 中统一注册:

```python
from .observability_plugin import ObservabilityPlugin

def _attach_observability(agent, pipeline_type, decision_trace=None):
    """递归挂载可观测性 Plugin 到 Agent 树"""
    plugin = ObservabilityPlugin(pipeline_type, decision_trace)

    if isinstance(agent, LlmAgent):
        # 保留已有回调，追加可观测性回调
        existing_before_agent = agent.before_agent_callback
        existing_after_agent = agent.after_agent_callback

        async def combined_before_agent(ctx):
            await plugin.before_agent(ctx)
            if existing_before_agent:
                return await existing_before_agent(ctx)
            return None

        async def combined_after_agent(ctx):
            await plugin.after_agent(ctx)
            if existing_after_agent:
                return await existing_after_agent(ctx)
            return None

        agent.before_agent_callback = combined_before_agent
        agent.after_agent_callback = combined_after_agent
        agent.before_model_callback = [plugin.before_model]
        agent.after_model_callback = plugin.after_model
        agent.before_tool_callback = plugin.before_tool
        agent.after_tool_callback = plugin.after_tool

    # 递归处理子 Agent
    if hasattr(agent, "sub_agents"):
        for sub in agent.sub_agents:
            _attach_observability(sub, pipeline_type, decision_trace)
```

### 3.6 前端 Agent 观测仪表盘

#### 3.6.1 新增 DataPanel 标签页: AgentObservabilityTab

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Agent 可观测性                                            [实时] [历史]  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────── Pipeline 执行瀑布图 ───────────────────────────────┐  │
│  │                                                                    │  │
│  │  ▓▓ intent_classification         [0.3s]                          │  │
│  │  ▓▓▓▓▓▓▓ exploration_planner      [1.8s]  ♦2 tools  🎯1200 tok  │  │
│  │  ▓▓▓▓▓ semantic_pre_fetch         [1.5s]  ♦1 tool   🎯800 tok   │  │
│  │  ▓▓▓▓▓▓▓▓▓▓ data_processing       [3.2s]  ♦2 tools  🎯3000 tok  │  │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓ analysis_loop(×2)  [4.5s]  ♦3 tools  🎯5000 tok  │  │
│  │  ▓▓▓▓▓ data_visualization          [1.5s]  ♦1 tool   🎯500 tok   │  │
│  │  ▓▓▓ data_summary                  [0.8s]              🎯4000 tok  │  │
│  │                                                                    │  │
│  │  总计: 12.4s │ 14,500 tokens │ 9 tool calls │ 1 retry             │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌── Agent 决策路径 ──────────────────────┐  ┌── 工具热力图 ──────────┐ │
│  │                                        │  │                        │ │
│  │  exploration_planner                   │  │ load_spatial  ▓▓▓ 0.9s │ │
│  │  ├→ 🔧 load_spatial_data (landuse.shp) │  │ spatial_join  ▓▓▓▓ 1.5s│ │
│  │  ├→ 🔧 describe_spatial_data           │  │ calculate_area ▓▓ 0.9s │ │
│  │  │                                    │  │ optimization  ▓▓▓ 1.3s │ │
│  │  data_processing                       │  │ choropleth    ▓▓ 1.0s  │ │
│  │  ├→ 🔧 spatial_join                   │  │                        │ │
│  │  ├→ 🔧 calculate_area                 │  │ 成功率: 100%           │ │
│  │  │                                    │  │ 重试率: 11%            │ │
│  │  quality_loop                          │  │ 平均延迟: 1.12s       │ │
│  │  ├→ iter 1: ✗ 质量不合格              │  └────────────────────────┘ │
│  │  └→ iter 2: ✓ 通过                    │                             │
│  └────────────────────────────────────────┘                             │
│                                                                          │
│  ┌── Token 消耗分解 ──────────────────────────────────────────────────┐  │
│  │  exploration_planner  ████░░░░░░   1,550 (11%)  gemini-2.5-flash   │  │
│  │  semantic_pre_fetch   ███░░░░░░░   1,000 (7%)   gemini-2.5-flash   │  │
│  │  data_processing      ████████░░   3,500 (24%)  gemini-2.5-flash   │  │
│  │  analysis_loop        ██████████   5,800 (40%)  gemini-2.5-pro     │  │
│  │  data_visualization   ██░░░░░░░░     500 (3%)   gemini-2.5-flash   │  │
│  │  data_summary         █████░░░░░   2,200 (15%)  gemini-2.5-pro     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 3.6.2 新增 REST API 端点

```python
# frontend_api.py 新增

@app.get("/api/observability/pipeline/{run_id}/trace")
async def get_pipeline_trace(run_id: str, request: Request):
    """获取单次 Pipeline 执行的完整追踪数据（瀑布图 + 决策路径）"""
    # 从 audit_log.details 提取 tool_execution_log + provenance_trail + decision_trace
    pass

@app.get("/api/observability/agents/metrics")
async def get_agent_metrics(request: Request, days: int = 7):
    """获取 Agent 级聚合指标 — 喂给前端仪表盘"""
    # 每个 Agent 的: 调用次数、平均延迟、Token 消耗、错误率
    pass

@app.get("/api/observability/tools/heatmap")
async def get_tool_heatmap(request: Request, days: int = 7):
    """工具调用热力图数据 — 延迟 × 频率 × 错误率"""
    pass

@app.get("/api/observability/realtime/stream")
async def realtime_agent_stream(request: Request):
    """SSE 实时流 — 推送当前正在执行的 Agent 事件"""
    # Server-Sent Events，前端 EventSource 订阅
    pass

@app.get("/api/observability/decision-trace/{run_id}")
async def get_decision_trace(run_id: str, request: Request):
    """获取决策追踪 — 返回 Mermaid 序列图 + 原始事件"""
    pass
```

---

## 4. HTTP API 可观测性中间件

### 4.1 Starlette Middleware

```python
"""
HTTP 请求观测中间件 — 为 frontend_api.py 的 123 个端点添加指标。
"""
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .observability_metrics import http_request_duration_seconds, http_requests_total
from .observability import get_logger

logger = get_logger("http")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        method = request.method
        path = self._normalize_path(request.url.path)

        try:
            response: Response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            status = "500"
            raise
        finally:
            duration = time.monotonic() - start
            http_request_duration_seconds.labels(
                method=method, path=path, status_code=status,
            ).observe(duration)
            http_requests_total.labels(
                method=method, path=path, status_code=status,
            ).inc()

            if duration > 2.0:
                logger.warning("Slow API request", extra={
                    "method": method,
                    "path": request.url.path,
                    "status": status,
                    "duration_seconds": round(duration, 3),
                })

        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """路径归一化 — 去除动态 ID 段，避免 Prometheus 基数爆炸"""
        import re
        # /api/workflows/123 → /api/workflows/{id}
        path = re.sub(r"/\d+", "/{id}", path)
        # /api/user-tools/abc-def-123 → /api/user-tools/{id}
        path = re.sub(r"/[0-9a-f-]{8,}", "/{id}", path)
        return path
```

在 `app.py` 中挂载:

```python
from .http_observability import ObservabilityMiddleware
app.add_middleware(ObservabilityMiddleware)
```

---

## 5. 缓存可观测性

### 5.1 为 semantic_layer.py 增加缓存命中指标

```python
# semantic_layer.py 修改
from .observability_metrics import agent_cache_operations_total

class SemanticLayer:
    async def get_cached_or_fetch(self, key: str):
        if key in self._cache and not self._is_expired(key):
            agent_cache_operations_total.labels(
                cache_name="semantic_layer", operation="hit"
            ).inc()
            return self._cache[key]
        else:
            agent_cache_operations_total.labels(
                cache_name="semantic_layer", operation="miss"
            ).inc()
            value = await self._fetch(key)
            self._cache[key] = value
            return value

    def invalidate(self, key: str = None):
        agent_cache_operations_total.labels(
            cache_name="semantic_layer", operation="invalidate"
        ).inc()
        # ... existing invalidation logic
```

同样模式应用于: `memory.py`（Memory 缓存）、`data_catalog.py`（Catalog 缓存）。

---

## 6. Grafana Dashboard 模板

### 6.1 Agent Overview Dashboard

```json
{
  "title": "GIS Data Agent — Agent 可观测性",
  "panels": [
    {
      "title": "Pipeline 执行 QPS",
      "type": "timeseries",
      "targets": [{"expr": "rate(agent_pipeline_runs_total[5m])"}]
    },
    {
      "title": "Pipeline P95 延迟",
      "type": "timeseries",
      "targets": [{"expr": "histogram_quantile(0.95, rate(agent_pipeline_duration_seconds_bucket[5m]))"}]
    },
    {
      "title": "Agent LLM 调用延迟分布",
      "type": "heatmap",
      "targets": [{"expr": "rate(agent_llm_duration_seconds_bucket[5m])"}]
    },
    {
      "title": "Token 消耗速率 (by Agent)",
      "type": "timeseries",
      "targets": [{"expr": "rate(agent_llm_input_tokens_sum[5m])"}]
    },
    {
      "title": "工具调用成功率",
      "type": "gauge",
      "targets": [{
        "expr": "sum(rate(agent_tool_calls_total{status='success'}[1h])) / sum(rate(agent_tool_calls_total[1h]))"
      }]
    },
    {
      "title": "工具延迟 Top 10",
      "type": "bar",
      "targets": [{
        "expr": "topk(10, histogram_quantile(0.95, rate(agent_tool_duration_seconds_bucket[1h])))"
      }]
    },
    {
      "title": "熔断器状态",
      "type": "stat",
      "targets": [{"expr": "agent_circuit_breaker_state"}]
    },
    {
      "title": "缓存命中率",
      "type": "gauge",
      "targets": [{
        "expr": "sum(rate(agent_cache_operations_total{operation='hit'}[1h])) / sum(rate(agent_cache_operations_total{operation=~'hit|miss'}[1h]))"
      }]
    },
    {
      "title": "HTTP API P99 延迟",
      "type": "timeseries",
      "targets": [{
        "expr": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))"
      }]
    },
    {
      "title": "任务队列深度",
      "type": "timeseries",
      "targets": [{"expr": "agent_task_queue_depth"}]
    }
  ]
}
```

### 6.2 关键 Alert 规则

```yaml
# prometheus_alerts.yml
groups:
  - name: gis_agent_alerts
    rules:
      # Pipeline 延迟告警
      - alert: PipelineSlowExecution
        expr: histogram_quantile(0.95, rate(agent_pipeline_duration_seconds_bucket[15m])) > 60
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "Pipeline P95 延迟超过 60 秒"

      # LLM 调用高延迟
      - alert: LLMHighLatency
        expr: histogram_quantile(0.95, rate(agent_llm_duration_seconds_bucket[10m])) > 10
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "LLM 调用 P95 延迟超过 10 秒 (Agent: {{ $labels.agent_name }})"

      # 工具错误率飙升
      - alert: ToolHighErrorRate
        expr: |
          sum(rate(agent_tool_calls_total{status="error"}[15m])) by (tool_name)
          / sum(rate(agent_tool_calls_total[15m])) by (tool_name) > 0.2
        for: 5m
        labels: { severity: critical }
        annotations:
          summary: "工具 {{ $labels.tool_name }} 错误率超过 20%"

      # 熔断器打开
      - alert: CircuitBreakerOpen
        expr: agent_circuit_breaker_state == 1
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "熔断器打开: {{ $labels.tool_name }}"

      # Token 消耗异常
      - alert: TokenBudgetBurn
        expr: sum(rate(agent_llm_input_tokens_sum[1h])) + sum(rate(agent_llm_output_tokens_sum[1h])) > 100000
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Token 消耗速率异常 (> 100K/h)"

      # 缓存命中率过低
      - alert: CacheHitRateLow
        expr: |
          sum(rate(agent_cache_operations_total{operation="hit"}[30m]))
          / sum(rate(agent_cache_operations_total{operation=~"hit|miss"}[30m])) < 0.5
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "缓存命中率低于 50% ({{ $labels.cache_name }})"

      # 队列积压
      - alert: TaskQueueBacklog
        expr: agent_task_queue_depth > 10
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "任务队列积压超过 10 个"
```

---

## 7. Agent 质量评估（进阶）

### 7.1 输出质量监控维度

| 维度 | 检测方法 | 指标 |
|------|---------|------|
| **忠实度 (Faithfulness)** | 答案是否基于工具返回的数据 | 引用率: 答案中可溯源到工具输出的比例 |
| **相关性 (Relevance)** | 答案是否回答了用户问题 | 用户后续追问率（低 = 好） |
| **完整性 (Completeness)** | 是否覆盖所有数据维度 | 工具输出利用率: 被引用的工具结果比例 |
| **幻觉检测 (Hallucination)** | 答案中是否有工具未提供的数据 | LLM 输出中的数值/地名与工具输出的交叉验证 |
| **一致性 (Consistency)** | 同一问题多次回答是否一致 | 回归测试: ADK Evaluation 框架 |

### 7.2 实现方式

```python
# quality_monitor.py — Agent 输出质量抽样检测

class AgentQualityMonitor:
    """
    轻量级质量监控 — 不阻塞主流程，异步抽样评估。

    采样率: 10% (可配置)
    评估方式: 用 Gemini Flash 对 Agent 输出进行打分
    """

    SAMPLE_RATE = float(os.getenv("QUALITY_SAMPLE_RATE", "0.1"))

    EVAL_PROMPT = """
    请评估以下 AI 分析报告的质量（1-5 分）:

    用户问题: {user_query}
    工具输出摘要: {tool_outputs}
    AI 生成报告: {agent_report}

    评估维度:
    1. 忠实度: 报告内容是否基于工具输出数据？(1=完全编造, 5=完全可溯源)
    2. 相关性: 报告是否回答了用户问题？(1=离题, 5=精准回答)
    3. 完整性: 是否充分利用了工具输出的数据？(1=严重遗漏, 5=全面)

    以 JSON 格式返回: {"faithfulness": int, "relevance": int, "completeness": int, "issues": ["..."]}
    """

    async def maybe_evaluate(self, user_query: str, tool_outputs: list[dict],
                              agent_report: str, pipeline_type: str):
        """概率性抽样评估"""
        import random
        if random.random() > self.SAMPLE_RATE:
            return  # 不抽样

        # 异步评估，不阻塞主流程
        asyncio.create_task(
            self._evaluate(user_query, tool_outputs, agent_report, pipeline_type)
        )

    async def _evaluate(self, user_query, tool_outputs, agent_report, pipeline_type):
        try:
            # 调用 Gemini Flash 进行评估
            scores = await self._call_evaluator(user_query, tool_outputs, agent_report)
            # 记录到 Prometheus
            for dim in ("faithfulness", "relevance", "completeness"):
                agent_quality_score.labels(
                    pipeline_type=pipeline_type, dimension=dim,
                ).observe(scores.get(dim, 0))
            # 低分告警
            if any(v < 3 for v in scores.values() if isinstance(v, int)):
                logger.warning("Agent output quality issue", extra={
                    "pipeline_type": pipeline_type,
                    "scores": scores,
                    "issues": scores.get("issues", []),
                })
        except Exception as e:
            logger.debug(f"Quality evaluation skipped: {e}")
```

---

## 8. 现有模块改造清单

| 文件 | 改造内容 | 工作量 |
|------|---------|--------|
| `observability.py` | 新增 20+ Prometheus 指标定义 | 小 |
| `agent_hooks.py` | 合并到 `ObservabilityPlugin`，增加 before/after_model 回调 | 中 |
| `agent.py` | `_attach_observability()` 递归挂载 Plugin | 小 |
| `app.py` | 添加 `ObservabilityMiddleware`；Pipeline 执行处增加 OTel root span | 中 |
| `pipeline_runner.py` | 写入 `decision_trace` 到 `PipelineResult` | 小 |
| `semantic_layer.py` | 缓存操作增加 hit/miss 指标 | 小 |
| `circuit_breaker.py` | 暴露 Prometheus Gauge（状态）+ Counter（跳闸） | 小 |
| `task_queue.py` | 暴露 Gauge（队列深度）+ Histogram（等待时间） | 小 |
| `workflow_engine.py` | DAG 节点执行增加 OTel span | 中 |
| `frontend_api.py` | 新增 5 个 `/api/observability/*` 端点 | 中 |
| `frontend/DataPanel` | 新增 AgentObservabilityTab 组件 | 大 |

---

## 9. 新增依赖

```txt
# requirements.txt 新增
opentelemetry-api>=1.25.0
opentelemetry-sdk>=1.25.0
opentelemetry-exporter-otlp-proto-grpc>=1.25.0
opentelemetry-instrumentation-httpx>=0.46b0       # httpx 自动插桩
opentelemetry-instrumentation-sqlalchemy>=0.46b0   # SQLAlchemy 自动插桩
```

环境变量:

```env
# .env 新增
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # Jaeger/Tempo gRPC
OTEL_SERVICE_NAME=gis-data-agent
QUALITY_SAMPLE_RATE=0.1                              # 质量评估采样率
```

---

## 10. 演进路线

### Phase 1: 指标 + 日志增强 (1-2 周)

```
├─ observability.py 扩展到 25+ Prometheus 指标
├─ ObservabilityPlugin 统一 6 层 ADK 回调
├─ HTTP ObservabilityMiddleware 中间件
├─ 缓存命中率指标 (semantic_layer / memory / catalog)
├─ 熔断器 + 队列 Prometheus Gauge
└─ Grafana Dashboard JSON 模板
```

### Phase 2: 分布式追踪 (2-3 周)

```
├─ otel_tracing.py — OpenTelemetry 初始化 + Span 上下文管理器
├─ Pipeline root span + Agent span + Tool span 三级嵌套
├─ SQLAlchemy + httpx 自动插桩
├─ Trace ID 从 ContextVar 传播到 OTel Span
├─ Jaeger/Tempo 部署 + 集成测试
└─ 前端 "追踪详情" 链接（跳转 Jaeger UI）
```

### Phase 3: 决策可视化 (2-3 周)

```
├─ agent_decision_tracer.py — 决策事件采集
├─ Mermaid 序列图生成（前端内嵌渲染）
├─ Pipeline 执行瀑布图前端组件
├─ /api/observability/* 5 个新端点
├─ DataPanel AgentObservabilityTab
└─ 实时 SSE 推送正在执行的 Agent 事件
```

### Phase 4: 质量评估 (1-2 周)

```
├─ quality_monitor.py — 异步抽样评估
├─ 忠实度 / 相关性 / 完整性 三维打分
├─ 低分告警规则
├─ ADK Evaluation 框架集成（CI 回归测试）
└─ 质量趋势 Dashboard 面板
```

---

## 11. 总结

| 维度 | 当前 | 目标 |
|------|------|------|
| Prometheus 指标 | 4 个 | 25+ 个 |
| ADK 回调覆盖 | before/after agent 仅 2 层 | 6 层全覆盖 (agent + model + tool) |
| 追踪 | 12 字符 trace_id 仅日志可见 | OpenTelemetry 分布式追踪 (Jaeger/Tempo) |
| Agent 决策 | ProvenancePlugin 事件列表 | 决策追踪 + Mermaid 序列图 + 瀑布图 |
| 工具可观测性 | 成功/失败计数 | 延迟直方图 + 错误分类 + 重试统计 + 质量门 |
| LLM 可观测性 | Token 累计 (pipeline 粒度) | 每次调用的延迟/token/模型名 (agent 粒度) |
| HTTP API | 无指标 | 请求延迟 + QPS + 错误率 |
| 缓存 | 无指标 | 命中率 + 失效率 |
| 质量评估 | 无 | 异步抽样 (忠实度/相关性/完整性) |
| 告警 | 无 | 8 条 Prometheus 告警规则 |

**核心理念**: 智能体系统的可观测性不只是"能看到日志"，而是要能回答 **"这次分析为什么慢/为什么错/为什么贵"** —— 需要从 Pipeline → Agent → LLM 调用 → 工具执行四个层次逐级下钻，才能真正实现 Agent 的白盒化运维。
