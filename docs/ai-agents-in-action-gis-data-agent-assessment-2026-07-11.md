# 《AI Agents in Action（第二版）》对 GIS Data Agent 的系统评估与改进建议

**评估日期：** 2026-07-11<br>
**评估对象：** `AI_Agents_in_Action_Second_Edition.pdf` 与 GIS Data Agent 当前代码库<br>
**评估性质：** 架构、运行时闭环、安全边界、记忆、评测与发布机制审计<br>
**关联路线图：** [GIS Data Agent Roadmap](roadmap.md)

## 1. 执行结论

GIS Data Agent 的 GIS 能力广度、领域算法深度和工程模块数量已经明显超过书中的教学案例。项目已经具备多智能体工作流、PostGIS grounding、耕地 DRL 优化、WorldModel/MPC、数据治理、可视化、报告、MCP、记忆、上下文、反馈、评测、提示词版本和可观测性等大量基础能力。

当前最值得从本书进一步吸收的，不是继续增加 Agent 或工具，而是四项工程纪律：

1. **强类型通信**：Agent、工作流和工具之间使用可程序判断的 schema，而不是自由文本约定。
2. **真实闭环**：生成、评价、重试、重规划、预算和收敛条件必须全部进入实际控制流。
3. **统一控制面**：所有入口执行相同的安全、权限、预算、追踪和审计策略。
4. **认知工作区**：将规划、证据、失败路径、记忆、预算和置信信号放入共享状态，由确定性路由器决定下一步。

因此，对项目最准确的判断是：**领域能力已经较强，但 Agent Runtime 的闭环完整性和主链接线成熟度落后于功能模块丰富度。** 优化重点应从“继续扩展能力面”转向“收束、接线、验证和可复现发布”。

## 2. 审读与审计范围

### 2.1 书籍审读

本次系统通读了全书 392 页、11 章的结构和章节总结，并重点逐段核对与 GIS Data Agent 直接相关的第 4 至第 11 章：

| 章节 | 重点主题 | 与项目的直接关系 |
|---|---|---|
| 第 4 章，印刷页 91-130 | 多 Agent 架构、typed handoff、guardrail、工具范围 | 工作流边界、Agent 交接、工具膨胀 |
| 第 5 章，印刷页 131-157 | CoT、ReAct、ToT、Reflexion、规划与反思 | 规划、执行、观察、评价和重试 |
| 第 6 章，印刷页 159-195 | RAG、混合检索、知识与记忆 | ContextEngine、知识库、跨会话记忆 |
| 第 7 章，印刷页 197-231 | TDAD、grounding、反馈、稳定性评测 | ADK Eval、反馈飞轮、质量门 |
| 第 8 章，印刷页 233-268 | 部署、前门 Agent、幂等性、安全、可观测性 | UI/headless/MCP/A2A/队列统一运行策略 |
| 第 9 章，印刷页 269-297 | agentic loop、状态累积、预算、停滞检测 | 质量循环、任务循环和收敛条件 |
| 第 10 章，印刷页 299-333 | cognitive workspace、attention、置信度门、主动记忆 | 统一认知控制层 |
| 第 11 章，印刷页 335-353 | 五层实践建议、窄职责、小工具集、版本与运维 | 生产化收束与路线优先级 |

这里没有把“阅读完成”理解为只看目录或摘要。第 4-11 章的关键实现、示例循环、guardrail、memory、evaluation、deployment 和 cognitive architecture 均与项目代码逐项对照。

### 2.2 项目审计

重点检查了以下运行面：

- Agent 与 Workflow 定义；
- UI 与 headless pipeline runner；
- MCP Hub 和工具发现；
- Conversation Memory、Memory Tool、Knowledge Base 与 ContextEngine；
- Task Decomposer、Plan Refiner 与 Workflow Engine；
- ADK Eval、评测 CI、反馈和 failure-to-eval；
- Guardrail、CostGuard、工具重试、Provenance 和 HITL；
- OTel、DecisionTracer、Reasoning、Prompt Registry 和模型配置。

### 2.3 验证证据

本次执行了以下只读或测试验证：

- 相关定向测试：`200 passed, 3 warnings in 3.33s`；
- ADK eval 数据集计数：4 条 pipeline，每条 3 个 case，共 12 个正向案例；
- 运行时工具枚举：GeneralProcessing 315、Planner 63、DataProcessing 34、DataAnalysis 41、GovProcessing 33；
- 直接导入 `from data_agent.pipeline_runner import run_pipeline`：确认触发 `ImportError`。

测试通过不代表下面的问题不存在。现有测试中相当一部分验证的是对象、属性、schema 或辅助函数是否存在，没有验证“不通过后是否真的重跑”“跨入口是否加载同一插件”“不同用户是否可能命中同一上下文缓存”等运行语义。

## 3. 从书中提炼的核心原则

### 3.1 多 Agent 不是数量问题，而是边界问题

第 4 章总结强调：单体 Agent 拆分后，每个节点应承担窄职责，使用精简工具集，并通过 concise typed output 向下游交接。需要重复可靠执行的分支，应使用代码或 schema 检查形成确定性决策点，而不是依赖 LLM 的自由文本判断。

书中明确建议每个 Agent 的工具集保持在少于约 10 个高度相关工具。每个工具都会把名称、说明和参数 schema 带入 LLM 上下文，工具数量本身就是 token、延迟和错误选择成本。

### 3.2 Agentic loop 必须有外部控制器

第 5、7、9 章共同形成了一个明确要求：

```text
Goal -> Plan -> Act -> Observe -> Evaluate -> Replan/Retry -> Terminate
```

控制器必须能读取强类型结果，并同时拥有：

- 目标是否满足；
- 质量分数和问题列表；
- 下一动作；
- 最大迭代数；
- token、成本和工具失败预算；
- 停滞或收益递减检测；
- 人工升级路径。

仅在对象上保存 `max_iterations` 属性，或者顺序执行一次 generator 和 checker，不构成 agentic loop。

### 3.3 记忆应当主动参与规划

第 6 和第 10 章区分了知识与记忆：知识通常是相对静态的外部事实，记忆则来自对话、行动、结果和反馈。生产系统需要在规划前主动检索历史经验，在执行后记录结构化结果，并具备压缩、遗忘、权限控制、冲突处理和检索质量评测。

### 3.4 前门 Agent 应轻，专用 worker 应强

第 8 章建议 front-door/orchestrator 只负责理解意图、选择路径和协调专用 worker。复杂决策和大量工具应下沉到无长历史、强类型、窄职责的 worker。状态、幂等性、安全、版本、追踪和成本控制应属于统一运行平台，而不是某个 UI 入口的局部功能。

### 3.5 Cognitive Agent 的关键是共享状态和注意力路由

第 10 章的核心不是再增加 perception、planning、evaluation 等类，而是让这些模块围绕同一个 cognitive workspace 工作，并由 attention 模块根据任务状态确定下一步。最有生产价值的能力是：置信度门、停滞检测、知识边界意识、主动记忆和优雅降级。

## 4. GIS Data Agent 已有的成熟基础

### 4.1 领域算法与真实工作流

项目已将自然语言 GIS、PostGIS、耕地优化、数据治理、空间统计、遥感、NL2Semantic2SQL 和 WorldModel/MPC 组织为真实工作流。这些不是书中常见的搜索、写作或客服示例，而是有数据契约、空间单位、CRS、约束优化和产物导出的领域系统。

### 4.2 专用 Agent 与 Pipeline 已有良好雏形

[data_agent/agent.py](../data_agent/agent.py) 已拆分 exploration、processing、analysis、visualization、summary、governance、farmland 和 planner 等角色。顺序、并行、专用 Agent、显式 mention 路由和动态 planner 均已有实现基础。

### 4.3 安全与运行时积木较完整

[data_agent/plugins.py](../data_agent/plugins.py) 已提供 CostGuard、工具反思重试、Provenance 和 GuardrailsPlugin；UI 侧还支持 HITL。项目不缺少安全模块，真正问题是这些模块没有成为所有入口不可绕过的默认策略。

### 4.4 记忆、反馈和评测模块已有积累

项目已经拥有 PostgreSQL memory service、用户偏好、分析结果保存、知识库、参考查询、反馈、failure learning、failure-to-eval、评测历史和 evaluator registry。后续重点是接入主链、定义数据契约和验证真实效果，而不是再建一套平行模块。

## 5. 能力状态分类

| 状态 | 能力 |
|---|---|
| 已有且相对成熟 | GIS 领域工具、PostGIS grounding、专用分析工作流、数据产物、模型路由、基础 guardrail、反馈存储 |
| 已有但未完整接线 | 质量 checker、Conversation Memory、ContextEngine、DecisionTracer、OTel span、PlanRefiner、Skill output schema、Prompt Registry 热部署 |
| 需要新增或重构 | 强类型运行契约、真实可回跳质量循环、统一 RunnerFactory、RunWorkspace、AttentionRouter、停滞检测、跨入口策略一致性测试 |

这个分类很重要。项目不应把“已有但未接线”误判成“能力已经闭环”，也不应为解决接线问题继续创建新的同类模块。

## 6. 关键差距与优化建议

### 6.1 P0：三个质量循环实际上不循环

证据位于 [data_agent/agent.py](../data_agent/agent.py) 第 184-206 行。`_quality_gate_workflow()` 只有：

```python
edges=[("START", generator, checker)]
```

源码还明确说明 conditional retry semantics 可以以后再添加。`max_iterations=3` 只是兼容属性，没有参与路由。受影响的包括 AnalysisQualityLoop、GovernanceReportLoop 和 GeneralSummaryLoop。

**风险：** checker 即使发现问题，也不能让 generator 根据问题重做；系统只能“评价一次”，不能“改进到通过”。

**建议：**

- 定义 `GeneratorOutput` 和 `QualityVerdict`；
- `QualityVerdict.decision` 固定为 `pass | revise | escalate`；
- `revise` 条件边回到 generator；
- 保存上一轮问题、修订说明和分数；
- 加入 iteration、token、cost、tool failure 和 stagnation 五类退出门。

### 6.2 P0：核心 Agent 间仍以自由文本为主

ADK 已支持 `input_schema` 和 `output_schema`，但核心 Agent 主要只配置 `output_key`。自定义 Skill 在 [data_agent/custom_skills.py](../data_agent/custom_skills.py) 第 563-568 行注明由 caller 调用 `try_validate_output`，但生产 caller 没有执行该校验。

更关键的是，[data_agent/skill_output_schemas.py](../data_agent/skill_output_schemas.py) 的 best-effort wrapper 在校验失败时返回原始输出。这适合非关键展示，不适合质量门、权限判断和控制流分支。

**建议：** 将契约分成两级：

- `strict`：规划、Agent 交接、质量 verdict、写操作、权限和控制流；失败必须重试、阻断或升级；
- `best_effort`：纯展示、非关键摘要和兼容旧 Skill。

### 6.3 P0/P1：工具面严重膨胀

[GeneralProcessing](../data_agent/agent.py) 同时注册约 30 个 Toolset。运行时动态枚举结果为：

| Agent | 可见工具数 |
|---|---:|
| GeneralProcessing | 315 |
| Planner | 63 |
| DataProcessing | 34 |
| DataAnalysis | 41 |
| GovProcessing | 33 |

尽管部分 Toolset 使用 `intent_tool_predicate`，仍有若干 Toolset 未过滤或单类别本身工具较多。继续扩充分类表不能从根本上解决工具说明占用上下文、相似工具误选和轨迹不稳定问题。

**建议目标：**

- FrontDoor：不超过 6-10 个元工具；
- 普通 specialist：不超过 10 个主要工具；
- 复杂 GIS specialist：超过 10 个时必须通过二级 capability loader 分组加载；
- 每次运行生成 route manifest，记录实际暴露工具及版本；
- MCP 工具先进入 capability catalog，再按任务选择，不直接全量注入。

### 6.4 P0：不同入口执行的安全策略不一致

UI 在 [data_agent/app.py](../data_agent/app.py) 第 1704-1728 行调用 `build_plugin_stack()` 并可加载 HITL；而 [data_agent/pipeline_runner.py](../data_agent/pipeline_runner.py) 第 117-126 行默认使用 `plugins or []`。

Workflow Engine、Task Queue、MCP、A2A、CLI、TUI 和 Bot 等多个入口调用 headless runner 时没有显式传插件，可能绕过 CostGuard、Guardrail、Provenance 和重试策略。

**建议：** 建立唯一 `RunnerFactory` 或 `RuntimePolicyFactory`：

```text
identity + entrypoint + task type + risk level
  -> mandatory plugin stack
  -> session/memory/context services
  -> run budget
  -> trace metadata
  -> Runner
```

调用方只能追加受控插件，不能把必需插件替换为空列表。

### 6.5 P0：MCP Hub 的用户隔离可能被 Agent 工具路径绕过

[data_agent/toolsets/mcp_hub_toolset.py](../data_agent/toolsets/mcp_hub_toolset.py) 第 27-35 行调用 `hub.get_all_tools(pipeline=...)` 时没有传 username。与此同时，[data_agent/mcp_hub.py](../data_agent/mcp_hub.py) 第 711-724 行只有在 username 非空时才过滤其他用户的私有 MCP server。

**建议：**

- MCP 工具发现必须接收 `RuntimeIdentity`，不能把 username 设为可选安全参数；
- 缺失身份时只返回系统级共享 server，默认拒绝私有 server；
- 工具列表缓存必须按 tenant、user、role、pipeline 和 MCP config version 分区；
- 增加两个用户连接不同私有 MCP server 的端到端隔离测试。

### 6.6 P0：ContextEngine 存在缓存作用域风险

[data_agent/context_engine.py](../data_agent/context_engine.py) 第 439-444、573-576 行的缓存键只有 `query + task_type`，但 provider 可能返回用户 KB、成功案例和反馈上下文。相同问题和任务类型可能让不同用户命中同一个缓存结果。

此外，第 592-627 行的 `_apply_embedding_boost()` 当前没有真正调整 score，最终仍把原 score 赋回。Context API 虽传入 `user_id` 字典，但知识库访问控制依赖 `current_user_id` ContextVar，二者不是同一权限通道。

**建议：** 在接入主聊天链前先完成：

- cache key 增加 tenant、user、role、KB scope、provider version 和 ACL digest；
- provider 使用显式 `RuntimeIdentity`，不混用字典和隐式 ContextVar；
- 缓存命中后二次校验可见性；
- 删除 placeholder boost 或实现真实 block embedding rerank；
- 增加跨用户缓存污染和权限回归测试。

### 6.7 P0：Task decomposition 当前运行路径会 ImportError

[data_agent/app.py](../data_agent/app.py) 第 3921-3933 行导入 `run_pipeline`，但 `pipeline_runner.py` 只有 `run_pipeline_headless` 和 `run_pipeline_streaming`。直接导入已确认失败。

同时存在三个语义缺口：

- `TaskNode.agent_hint` 没有用于 specialist 路由；
- 子任务基本重复送入同一 pipeline；
- 完成后只汇报成功/失败数量，没有综合子任务证据和产物；
- PlanRefiner 主要存在于测试，没有进入失败后的运行时重规划。

**建议：** 先修复导入和返回类型，再把任务图变成真正的执行契约：

```text
TaskNode(id, goal, agent_kind, dependencies, input_refs, expected_output_schema)
TaskResult(status, evidence, artifacts, metrics, errors, confidence)
```

最终 synthesis 必须消费所有成功结果、失败原因和证据缺口，而不是只输出数量统计。

### 6.8 P1：跨会话 Memory Service 没有形成主动闭环

[data_agent/conversation_memory.py](../data_agent/conversation_memory.py) 已实现 `add_session_to_memory()` 和 `search_memory()`，但把 memory service 传给 ADK Runner 不会自动完成检索和写入。当前主链没有 PreloadMemoryTool、LoadMemoryTool，也没有显式 session 写回。

目前真正生效的主要是上一轮上下文、用户偏好、最近分析元数据、分析结果保存和自动事实提取。这些有价值，但不等于“规划前检索历史经验”。

**建议将记忆拆成：**

| 类型 | 内容 | 检索时机 |
|---|---|---|
| Episodic | 历史任务、数据画像、结果和评价 | 类似任务规划前 |
| Procedural | 成功或失败的工具链、恢复方式 | 工具选择和重规划前 |
| Semantic | 用户偏好、地域、标准、组织约束 | 意图理解和上下文准备时 |

执行后只保存结构化经验：problem signature、data profile、strategy、tools、outcome、evaluator score、failure/recovery 和版本信息。避免把 2000 字自由文本直接作为主要记忆单元。

### 6.9 P1：缺少统一 Cognitive Workspace

项目已经分别存在 planner、context、memory、reasoning、decision trace、plan refiner 和 evaluator，但它们没有围绕一个共享运行状态形成闭环。

建议新增 `RunWorkspace`，至少包含：

```text
run_id, identity, goal, task_type, complexity
plan, subgoals, dependencies, current_focus
evidence, artifacts, tool_observations
failed_approaches, evaluator_feedback
memory_hits, confidence_signals
iteration_budget, token_budget, cost_budget
attention_signal, termination_reason
prompt_version, model_version, tool_manifest_version
```

`AttentionRouter` 应是确定性状态机，允许的下一动作限定为：fast path、plan、execute、evaluate、replan、retrieve memory、respond、escalate。LLM 可以提供建议，但不能用任意自由文本直接决定高风险控制流。

### 6.10 P1：评测覆盖不足以验证 Agent Runtime

[data_agent/run_evaluation.py](../data_agent/run_evaluation.py) 当前覆盖 optimization、governance、general 和 planner 四条 pipeline，但每条只有 3 个 case，且主要是正向案例。

缺少：

- checker 失败后重跑；
- memory 跨会话检索和写回；
- prompt injection 与权限隔离；
- 工具超时、重试、熔断和预算终止；
- typed handoff schema 错误；
- ContextEngine tenant isolation；
- MCP private tool isolation；
- 不确定性和“我不知道”；
- 多次运行轨迹稳定性；
- 错误答案和 negative examples。

CI 还存在路径和管道问题：评测结果写入 `data_agent/eval_results`，部分 workflow 却读取 `eval_results`；staging 使用 `python ... | tee ...` 而未启用 `pipefail`，非零退出可能被掩盖。

### 6.11 P1/P2：可观测性模块多，但 WHY 和 outcome 没有完整接线

[data_agent/otel_tracing.py](../data_agent/otel_tracing.py) 定义了 pipeline、agent、tool 和 LLM span helper，但主链没有全面使用。DecisionTracer 具备数据结构，API 也尝试从 session 读取 `decision_trace`，但运行时没有稳定创建和写入。

当前 `reasoning.py` 的 confidence 更接近启发式分数，报告长度和工具数量会提高分值，不能视为经过校准的模型置信度。

**建议每个 trace 至少记录：**

- route decision 与原因；
- prompt/model/tool/MCP schema 版本；
- plan revision；
- guardrail 和权限 verdict；
- memory hits；
- evaluator score 与问题；
- confidence trend；
- token、cost、latency；
- final business outcome 和 artifact references。

### 6.12 P2：Prompt Registry 部署不会热更新既有 Agent

[data_agent/prompt_registry.py](../data_agent/prompt_registry.py) 的 `deploy()` 会更新数据库活动版本，但 [data_agent/agent.py](../data_agent/agent.py) 在模块导入时调用 `get_prompt()` 创建模块级 Agent，instruction 已经固化。

因此，prompt deploy 通常需要进程重启才能影响现有 Agent。运行 trace 也缺少稳定的 prompt version 绑定，难以复现某次结果。

**建议：** 使用 per-run 或 per-version Agent factory；发布路径采用 offline eval、shadow、canary、SLO gate 和自动回滚；每次运行固定 prompt、model、tool schema 和 MCP server version。

## 7. 目标运行架构

```text
User / API / Queue / MCP / A2A / Bot
                |
                v
       Unified RunnerFactory
 identity | policy | budget | trace | services
                |
                v
     FrontDoor Agent (<= 6-10 meta tools)
 classify | clarify | retrieve | delegate | inspect | escalate
                |
                v
            RunWorkspace
 goal | plan | evidence | failures | memory | budget | versions
                |
                v
       Deterministic AttentionRouter
 fast | plan | execute | evaluate | replan | retrieve | respond
                |
                v
     Typed Specialist Worker (small tool manifest)
                |
                v
          Typed Quality Evaluator
                |
     pass | revise | retrieve | replan | escalate
```

### 7.1 建议的 QualityVerdict

```python
class QualityVerdict(BaseModel):
    decision: Literal["pass", "revise", "escalate"]
    score: float
    issues: list[str]
    evidence_gaps: list[str]
    next_action: str
    confidence: float
```

### 7.2 建议的停止条件

循环按以下顺序判断：

1. 权限、guardrail 或不可逆操作需要人工审批；
2. 质量达标并满足 grounding；
3. 达到最大迭代或 token/cost 预算；
4. 连续两轮计划和结果无实质变化，判定停滞；
5. 工具连续失败，切换替代工具或降级；
6. 证据不足且无法继续检索，明确说明边界并退出。

## 8. 分阶段实施路线

### 8.1 P0：运行时真实性与安全一致性

目标是先消除“看起来有闭环、实际没有闭环”和“不同入口策略不同”的问题。

| 工作包 | 主要输出 | 验收门 |
|---|---|---|
| Typed quality loop | QualityVerdict、条件回跳、预算和停滞检测 | checker 返回 revise 后 generator 确实重跑；达到上限后可解释退出 |
| Unified RunnerFactory | 所有入口统一插件、服务、预算和 trace | UI、headless、MCP、A2A、queue、CLI 集成测试均看到必需策略 |
| Tenant isolation | MCP、Context、KB、缓存统一 RuntimeIdentity | 双用户隔离测试不存在私有工具或上下文泄露 |
| Task decomposition repair | 正确 runner、agent_hint 路由、TaskResult 和 synthesis | 多依赖任务端到端完成；失败节点进入重规划或最终解释 |

P0 未完成前，不建议把 ContextEngine、自动记忆或自进化进一步扩大到更多生产入口。

### 8.2 P1：工具收束与 Cognitive Runtime

| 工作包 | 主要输出 | 验收门 |
|---|---|---|
| Tool manifest | capability catalog、动态加载和版本记录 | FrontDoor 不超过 10 个工具；specialist 默认不超过 10 个主要工具 |
| RunWorkspace | 统一目标、计划、证据、失败、预算和版本状态 | 每次复杂运行可重放关键状态变化 |
| AttentionRouter | fast/plan/execute/evaluate/replan/retrieve/respond/escalate | 停滞、低置信和工具失败可触发确定性路由 |
| Proactive memory | 规划前检索、评价后记录、TTL/压缩/冲突处理 | 检索命中能改变计划；错误记忆可撤回；跨租户不可见 |

### 8.3 P2：评测、观测与发布飞轮

| 工作包 | 主要输出 | 验收门 |
|---|---|---|
| Cognitive failure benchmark | 五类认知失败、权限、安全和恢复案例 | 每条核心 pipeline 至少覆盖正向、负向、故障和隔离案例，并多次运行 |
| Trace wiring | route、plan、tool、memory、quality、cost、outcome 全链路 | 任一失败可从 trace 定位到决策和版本 |
| Versioned release | prompt/model/tool/MCP schema 版本绑定 | offline eval、shadow、canary 和回滚链路可运行 |
| Feedback-to-eval | trace/feedback/failure 候选集和人工审核 | 生产失败可进入回归集，但不能未经审核自动改生产 prompt |

## 9. 建议的量化指标

| 维度 | 指标 |
|---|---|
| 工具面 | 每次 LLM 调用实际暴露工具数、相似工具冲突率、无效工具选择率 |
| 闭环 | revise 后成功恢复率、平均修订轮数、停滞终止率、预算终止率 |
| 质量 | grounded answer rate、artifact completeness、数值/空间一致性 |
| 稳定性 | 同案例多次运行最终答案和工具轨迹方差 |
| 记忆 | retrieval precision、有效命中率、错误记忆率、压缩率、过期清理率 |
| 安全 | 跨租户泄露为零、prompt injection 阻断率、未授权工具暴露为零 |
| 运维 | p50/p95 延迟、token、成本、工具失败恢复率、版本可复现率 |
| 业务结果 | GIS 产物可用率、人工复核工作量、规划/治理任务完成率 |

## 10. 需要新增的回归基准

书中第 10 章提出的认知失败模式非常适合作为 GIS Data Agent 的专项 benchmark：

1. **Confident wrong answer**：SQL 或空间分析结果错误，但总结非常肯定；
2. **Broken record**：工具失败后重复相同调用和参数；
3. **Rigid plan**：数据、CRS 或权限条件变化后仍坚持原计划；
4. **Overcommitted guess**：缺少数据或证据时继续生成具体数值；
5. **Shallow composition**：能调用单个工具，但不能正确组合数据准备、分析、验证和报告。

GIS 专项还应补充：错误 CRS、geometry/geography 单位混淆、空间连接重复计数、跨层权限、MCP 私有工具、缓存污染和不可逆写操作审批。

## 11. 不建议采取的方向

- 不建议继续给 GeneralProcessing 叠加更多 Toolset；
- 不建议再创建一套与现有 Context、Memory、Reasoning 平行的新模块；
- 不建议用更长 prompt 模拟强类型控制流；
- 不建议用 LLM 自评文本直接控制高风险写操作；
- 不建议在 P0 权限和 Runner 一致性完成前扩大自进化自动发布；
- 不建议把启发式 confidence 直接对外表述为校准概率。

## 12. 审计边界

本次没有修改应用代码，也没有执行外部 Gemini、真实 PostGIS 数据链、远程 MCP server 或完整 UI 业务场景的在线端到端验证。结论建立在：

- 书籍相关章节的系统审读；
- 当前代码和文档的静态审计；
- 本地运行时工具枚举；
- 定向测试和导入验证；
- CI、评测数据集和运行入口的代码级核对。

后续实施时，应为每一项 P0 问题增加能够复现原始运行语义缺口的失败测试，再按 TDD 修复。

## 13. 最终判断

GIS Data Agent 下一阶段不缺更多功能创意，缺的是把现有能力组织成一个可信的 Agent Runtime。书中最值得吸收的主线可以概括为：

> 小工具集、强类型交接、确定性质量门、主动记忆、共享工作区、统一安全策略、可复现评测和版本化发布。

只要先完成 P0 的真实闭环与隔离治理，再建设 P1 的 Cognitive Runtime，项目已有的 GIS、NL2SQL、治理、DRL 和 WorldModel 能力就能从“功能丰富的平台”进一步升级为“可解释、可恢复、可评测、可持续演进的生产级 Agent 系统”。
