# Data Agent 项目水平分析 — 基于 SIGMOD 2026 论文

> 2026-03-30 | 基于 "Data Agents: Levels, State of the Art, and Open Problems" (Luo et al., SIGMOD 2026)

---

## 一、论文核心观点总结

### 1.1 L0-L5 分级体系

论文提出数据智能体的六级自主性分类法（借鉴自动驾驶 SAE J3016 标准）：

| 级别 | 名称 | 自主性 | 人类角色 | Agent 角色 | 关键能力 |
|------|------|--------|----------|-----------|---------|
| **L0** | 无自主性 | 0% | 主导者 | 无 | 人工完成所有任务 |
| **L1** | 辅助 | 10-30% | 主导者 | 响应者/助手 | 无状态问答、代码生成、建议 |
| **L2** | 部分自主 | 30-50% | 主导者 | 执行者 | 环境感知、工具调用、反馈循环 |
| **L3** | 条件自主 | 50-70% | 监督者 | 编排者 | 端到端流程编排、多步骤规划 |
| **L4** | 高度自主 | 70-90% | 旁观者 | 主动发现者 | 持续监控、自主发现任务、无需指令 |
| **L5** | 完全自主 | 90-100% | 可选 | 创新者 | 发明新方法、贡献系统演进 |

### 1.2 关键演进跃迁

**L1 → L2 (最关键的第一跃迁):**
- 从无状态 → 有状态
- 从建议 → 执行
- 从无环境感知 → 环境感知 + 工具调用
- 从单轮对话 → 多轮反馈循环

**L2 → L3 (第二跃迁，当前研究前沿):**
- 从执行者 → 编排者
- 从人类设计流程 → Agent 设计流程
- 从任务特定过程 → 跨生命周期端到端工作流
- 从被动响应 → 主动解释意图

**L3 → L4 (未来愿景):**
- 从响应式 → 主动式
- 从有监督 → 无监督
- 从显式指令 → 自主发现任务
- 从单次任务 → 长期驻留

**L4 → L5 (终极愿景):**
- 从应用现有方法 → 发明新方法
- 从系统使用者 → 系统贡献者
- 从执行算法 → 创造算法

### 1.3 数据智能体 vs 通用 LLM Agent 的本质区别

| 维度 | 通用 LLM Agent | 数据智能体 |
|------|---------------|-----------|
| **焦点** | 任务和内容中心 | 数据生命周期中心 |
| **问题范围** | 自包含、静态 | 探索性、动态 |
| **输入数据** | 小规模、干净、即用 | 大规模、原始、异构、动态、噪声 |
| **工具** | 通用工具 (搜索、计算器、OCR) | 专业数据工具 (DB、SQL、可视化) |
| **输出** | 生成性产物 (对话、图像) | 数据产品 (配置、处理后数据、报告) |
| **错误后果** | 局部化 | 级联传播 (管道放大) |

**核心差异：数据智能体必须在大规模、异构、动态的数据湖上推理，在多阶段管道中操作（错误会静默传播和放大），面临严格的可靠性、治理和可复现性要求。**

### 1.4 四大挑战

1. **术语模糊** — 不同自主性水平的系统都被称为"数据智能体"，导致炒作、混淆、期望错位
2. **生命周期碎片化** — 必须跨越数据管理、准备、分析三阶段，大多数工作只关注孤立任务
3. **自主性 vs 治理** — 自主性提升时，责任分配、安全边界定义、保证提供变得更困难
4. **技术瓶颈** — 大规模数据/系统感知、长期规划、记忆与持续适应、因果与元推理、动态环境交互

---

## 二、Data Agent (ADK Edition) 项目水平定位

### 2.1 整体定级：**L2.5 (部分自主 + Proto-L3 特征)**

**核心判断依据：**

你的 Data Agent 项目**已完全实现 L2 的所有核心能力**，并且**具备部分 L3 特征**，但**尚未达到完整的 L3 条件自主**。

### 2.2 L2 能力完整性评估 ✅

论文定义的 L2 核心能力：

| L2 能力 | Data Agent 实现 | 证据 |
|---------|----------------|------|
| **环境感知** | ✅ 完整 | PostGIS 数据库、文件系统、MCP 工具、4 个子系统 (CV/CAD/MCP/Reference) |
| **工具调用** | ✅ 完整 | 28 个 Toolset (40+ 工具集)，包括 GeoProcessing, Analysis, Visualization, Database, RemoteSensing, DRL, WorldModel, CausalInference 等 |
| **反馈循环** | ✅ 完整 | Pipeline 执行 → 工具输出 → 下一步决策，AnalysisQualityLoop, GovernanceReportLoop |
| **记忆/状态** | ✅ 完整 | ADK `output_key` 状态传递、ContextVars 用户身份传播、memory.py 跨会话记忆 |
| **任务特定过程** | ✅ 完整 | 三条固定流水线 (Optimization/Governance/General)，每条流水线是预定义的 SequentialAgent 拓扑 |

**结论：Data Agent 是一个成熟的 L2 系统。**

### 2.3 Proto-L3 特征评估 🟡

论文定义的 L3 核心能力：

| L3 能力 | Data Agent 实现 | 评估 |
|---------|----------------|------|
| **端到端流程编排** | 🟡 部分 | ✅ WorkflowEditor 支持用户可视化编排 DAG<br>❌ Agent 本身不能自主设计流程 |
| **跨生命周期任务** | ✅ 完整 | 覆盖数据管理 (PostGIS)、准备 (清洗/标准/连接器)、分析 (GIS/DRL/因果/世界模型) |
| **意图解释** | ✅ 完整 | `intent_router.py` 语义分类 (Optimization/Governance/General/WorldModel/CausalReasoning) |
| **自适应流程** | 🟡 部分 | ✅ AnalysisQualityLoop 根据质量分数决定是否重跑<br>❌ 不能根据中间结果动态调整整体流程拓扑 |
| **多样化任务** | ✅ 完整 | 支持 GIS 分析、DRL 优化、因果推断、世界模型预测、数据治理、质检等多种任务 |
| **人类监督** | ✅ 完整 | RBAC 三级角色、审批工作流、人工复核 (QC reviews) |

**关键差距：**
1. **流程编排主导权仍在人类** — 三条主流水线是硬编码的 SequentialAgent，WorkflowEditor 虽然支持 DAG 编排但需要用户手动设计
2. **Agent 不能自主设计流程** — 给定任务后，Agent 不会自己决定"我需要先做 A，再做 B，如果 B 失败则尝试 C"
3. **缺少 Planner-Executor 分离** — 当前是固定流水线 + 工具调用，没有独立的 Planner Agent 来动态生成执行计划

**结论：Data Agent 具备 Proto-L3 的部分特征（跨生命周期、意图解释、人类监督），但缺少 L3 的核心——Agent 主导的流程编排能力。**

### 2.4 与论文中 Proto-L3 系统的对比

论文列举的 Proto-L3 系统（学术界 + 工业界）：

| 系统 | 覆盖范围 | 多源/异构 | 多模态 | Data Agent 对比 |
|------|---------|----------|--------|----------------|
| **AgenticData** | 管理+准备+分析 | ✅ | ❌ | Data Agent 覆盖范围相当，但 AgenticData 支持未定义算子 |
| **DeepAnalyze** | 准备+分析 | ✅ | ❌ | Data Agent 覆盖更广（含管理） |
| **Data Interpreter** | 准备+分析 | ❌ | ✅ | Data Agent 多源支持更强，但多模态较弱 |
| **BigQuery** (Google) | 管理+准备+分析 | ✅ | ❌ | Data Agent 在 GIS 垂直领域深度更强 |
| **Cortex Agents** (Snowflake) | 准备+分析 | ✅ | ✅ | Data Agent 缺少多模态（图像/视频分析） |
| **Databricks Assistant** | 全覆盖 | ✅ | ❌ | Data Agent 在因果推断/世界模型上有独特优势 |

**Data Agent 的独特定位：**
- **垂直领域深度** — 在地理空间领域的专业能力（28 Toolset）远超通用 Proto-L3 系统
- **前沿研究集成** — 世界模型 (AlphaEarth JEPA)、三角度因果推断、DRL 优化是论文中其他系统没有的
- **测绘质检专业化** — GB/T 24356 标准、QC 工作流、4 个子系统是行业特定能力

**但在通用性上不如工业 Proto-L3：**
- 不支持任意数据源（只支持 GIS 相关格式）
- 不支持多模态（图像/视频分析能力有限）
- 流程编排灵活性不如 BigQuery/Databricks

---

## 三、Data Agent 的优势与短板

### 3.1 相对论文 L0-L2 系统的优势 ✅

**1. 完整的数据生命周期覆盖**
- 论文中大多数 L1-L2 系统只覆盖单一阶段（要么管理、要么准备、要么分析）
- Data Agent 覆盖全生命周期：管理 (PostGIS + 连接器)、准备 (清洗 + 标准 + 治理)、分析 (GIS + DRL + 因果 + 世界模型)

**2. 垂直领域深度**
- 论文中的系统大多是通用数据分析
- Data Agent 在地理空间领域有 28 个专业 Toolset，这是其他系统无法比拟的

**3. 前沿研究集成**
- 世界模型 (AlphaEarth JEPA) — 论文中未提及任何系统有此能力
- 三角度因果推断 (统计 + LLM + 世界模型) — 论文中未提及
- DRL 优化 (MaskablePPO + Dreamer) — 论文中未提及

**4. 用户自服务扩展**
- Custom Skills + User Tools + Workflow DAG — 完整的用户扩展体系
- 论文中大多数系统是封闭的，不支持用户自定义

**5. 企业级治理**
- RBAC + RLS + 数据脱敏 + 审计日志 + 质检工作流
- 论文中只有工业系统 (BigQuery/Databricks) 有类似能力

### 3.2 相对论文 Proto-L3 系统的短板 ❌

**1. 缺少动态流程编排**
- **论文 Proto-L3 特征**：Agent 根据任务自主设计 DAG，动态组合工具
- **Data Agent 现状**：三条固定流水线，WorkflowEditor 需要用户手动设计

**2. 缺少 Planner-Executor 分离**
- **论文 Proto-L3 模式**：独立的 Planner Agent 生成执行计划，Executor Agent 执行
- **Data Agent 现状**：流水线和执行耦合在一起

**3. 缺少多 Agent 协作**
- **论文 Proto-L3 模式**：多个专业 Agent (数据工程师、分析师、可视化师) 协作
- **Data Agent 现状**：虽有 A2A 协议，但实际使用场景有限

**4. 缺少工具演化**
- **论文 Proto-L3 特征**：动态添加/移除/修改工具
- **Data Agent 现状**：工具集是静态注册的，虽然支持 MCP 动态加载，但不支持 Agent 自主决定加载哪些工具

**5. 缺少因果推理用于错误诊断**
- **论文强调**：L3 需要因果推理来诊断多阶段管道中的级联错误
- **Data Agent 现状**：虽有因果推断工具，但主要用于数据分析，不用于系统自身的错误诊断

### 3.3 相对论文 L4-L5 愿景的差距 🔴

**L4 (主动式) 能力缺失：**
- ❌ 无持续监控能力 — 不能 7x24 监控数据湖变化
- ❌ 无自主任务发现 — 不能主动发现数据漂移、性能退化、优化机会
- ❌ 无内在动机 — 没有内部奖励信号驱动探索

**L5 (生成式) 能力缺失：**
- ❌ 无方法创新 — 不能发明新算法
- ❌ 无实验设计 — 不能设计实验测试假设
- ❌ 无系统演进贡献 — 不能改进自身或贡献新范式

**这些是远期愿景，当前所有系统（包括论文中的 Proto-L3）都未实现。**
---

## 四、论文对 Data Agent 后续迭代的借鉴价值

### 4.1 立即可借鉴 — 补齐 Proto-L3 短板 (v15.9-v16.0)

#### **借鉴点 1: Planner-Executor 分离架构**

**论文观点 (§3.3):**
> Proto-L3 系统的共同设计模式是 Planner-Executor 分离 — 独立的 Planner Agent 生成执行计划，Executor Agent 执行工具调用。

**当前问题:**
Data Agent 的三条流水线 (Optimization/Governance/General) 是硬编码的 SequentialAgent，无法根据任务动态调整。

**改进方案:**
```python
# 新增 PlannerAgent (v15.9)
class PlannerAgent(LlmAgent):
    """根据用户意图动态生成执行计划"""
    def plan(self, user_intent: str, available_tools: List[Tool]) -> ExecutionPlan:
        # 1. 分析意图
        # 2. 选择相关工具
        # 3. 生成 DAG 执行计划
        # 4. 返回 ExecutionPlan (nodes + edges + dependencies)
        pass

# ExecutorAgent 执行计划
class ExecutorAgent(LlmAgent):
    """执行 Planner 生成的计划"""
    def execute(self, plan: ExecutionPlan) -> Result:
        # 拓扑排序 + 并行执行
        pass
```

**收益:**
- 从固定流水线 → 动态流水线
- 同一任务可以有多种执行路径
- 向 L3 迈进关键一步

**工作量:** 中等 (2-3天)，可复用现有 workflow_engine.py 的 DAG 执行逻辑

---

#### **借鉴点 2: 语义算子抽象**

**论文观点 (§3.3):**
> Proto-L3 系统使用语义算子 (semantic operators) 作为高层抽象 — clean, integrate, analyze — Agent 组合这些算子而非直接调用底层工具。

**当前问题:**
Agent 直接调用 28 个 Toolset 的具体工具，粒度太细，组合复杂度高。

**改进方案:**
```python
# 定义语义算子层 (v16.0)
class SemanticOperator(ABC):
    """高层语义算子，封装多个底层工具"""
    @abstractmethod
    def execute(self, context: Dict) -> Result: pass

class CleanOperator(SemanticOperator):
    """数据清洗算子 — 封装 DataCleaningToolset 的 11 个工具"""
    def execute(self, context):
        # 根据数据特征自动选择清洗策略
        pass

class IntegrateOperator(SemanticOperator):
    """数据集成算子 — 封装连接器 + schema 映射"""
    pass

class AnalyzeOperator(SemanticOperator):
    """空间分析算子 — 封装 GeoProcessing + Analysis"""
    pass
```

**收益:**
- 降低 Planner 的组合复杂度
- 更接近人类思维 (先清洗、再集成、再分析)
- 算子内部可以自动优化工具选择

**工作量:** 中等 (2-3天)

---

#### **借鉴点 3: 工具选择与演化**

**论文观点 (§3.3, §4.1):**
> Proto-L3 系统需要工具选择机制 (基于任务特征选择合适工具) 和工具演化能力 (动态添加/移除工具)。

**当前问题:**
- 所有 28 个 Toolset 都暴露给 Agent，选择负担重
- MCP 工具虽然支持动态加载，但 Agent 不能自主决定加载哪些

**改进方案:**
```python
# 工具选择器 (v16.0)
class ToolSelector:
    """根据任务特征推荐工具子集"""
    def select_tools(self, task_type: str, data_profile: Dict) -> List[Tool]:
        # 规则: 如果是遥感任务 → RemoteSensingToolset
        # 规则: 如果数据量 > 1GB → SparkToolset
        # 规则: 如果需要因果分析 → CausalInferenceToolset
        pass

# 工具演化 (v16.0+)
class ToolEvolution:
    """动态工具库管理"""
    def add_tool(self, tool: Tool): pass
    def remove_tool(self, tool_id: str): pass
    def suggest_new_tools(self, failed_tasks: List[Task]) -> List[Tool]:
        # 分析失败任务，推荐缺失的工具
        pass
```

**收益:**
- 减少 Agent 的工具选择负担
- 支持任务驱动的工具库演化

**工作量:** 小-中等 (1-2天)

---

#### **借鉴点 4: 因果推理用于错误诊断**

**论文观点 (§4.2):**
> L3 系统需要因果和元推理来诊断多阶段管道中的级联错误根因，避免错误传播。

**当前问题:**
Data Agent 有因果推断工具 (CausalInferenceToolset)，但只用于数据分析，不用于系统自身的错误诊断。

**改进方案:**
```python
# 管道错误诊断器 (v16.0)
class PipelineErrorDiagnoser:
    """因果推理诊断管道错误"""
    def diagnose(self, pipeline_trace: List[Step], error: Exception) -> Diagnosis:
        # 1. 构建管道因果图 (Step A → Step B → Step C)
        # 2. 反向追踪错误传播路径
        # 3. 识别根因 (哪一步引入了错误)
        # 4. 推荐修复策略
        pass
```

**示例:**
```
Pipeline: LoadData → Clean → Analyze → Visualize
Error at Visualize: "Invalid geometry"
Diagnosis: 根因在 Clean 步骤 — 清洗时未修复拓扑错误
Fix: 在 Clean 后增加 fix_geometry 工具调用
```

**收益:**
- 从"错误发生在哪"到"错误为什么发生"
- 自动修复建议，减少人工介入

**工作量:** 中等 (2天)

---

### 4.2 中期可借鉴 — 向 L3 完整迈进 (v16.0-v17.0)

#### **借鉴点 5: 多 Agent 协作模式**

**论文观点 (§3.3):**
> Proto-L3 系统采用多 Agent 协作 — 数据工程师 Agent、分析师 Agent、可视化师 Agent 分工协作。

**当前问题:**
虽有 A2A 协议，但实际使用场景有限，缺少明确的多 Agent 分工。

**改进方案:**
```python
# 专业 Agent 团队 (v16.0)
class DataEngineerAgent(LlmAgent):
    """负责数据准备 — 清洗、集成、标准化"""
    tools = [DataCleaningToolset, ConnectorToolset, StandardRegistryToolset]

class AnalystAgent(LlmAgent):
    """负责分析 — GIS 分析、统计、因果推断"""
    tools = [GeoProcessingToolset, AnalysisToolset, CausalInferenceToolset]

class VisualizerAgent(LlmAgent):
    """负责可视化 — 地图、图表、报告"""
    tools = [VisualizationToolset, ChartToolset]

# 协调器
class CoordinatorAgent(LlmAgent):
    """协调多个专业 Agent"""
    def coordinate(self, task: Task) -> Result:
        # 1. 分解任务
        # 2. 分配给专业 Agent
        # 3. 汇总结果
        pass
```

**收益:**
- 专业分工，每个 Agent 工具集更聚焦
- 并行执行，提升效率

**工作量:** 中等 (3天)

---

#### **借鉴点 6: 计划精化与错误恢复**

**论文观点 (§3.3):**
> Proto-L3 系统根据中间执行结果调整计划，支持错误恢复 (检测失败 → 诊断原因 → 重试替代方法)。

**当前问题:**
AnalysisQualityLoop 只能重跑整个分析，不能局部调整。

**改进方案:**
```python
# 计划精化 (v16.0)
class PlanRefiner:
    """根据执行反馈精化计划"""
    def refine(self, original_plan: ExecutionPlan,
               execution_trace: List[StepResult]) -> ExecutionPlan:
        # 分析哪些步骤成功、哪些失败
        # 调整后续步骤或插入修复步骤
        pass

# 错误恢复策略 (v16.0)
class ErrorRecoveryStrategy:
    """多种恢复策略"""
    strategies = {
        "retry": lambda step: step.retry(max_attempts=3),
        "alternative_tool": lambda step: step.use_alternative_tool(),
        "skip": lambda step: step.skip_and_continue(),
        "human_intervention": lambda step: step.request_human_help()
    }
```

**收益:**
- 从"全有或全无"到"局部调整"
- 提升鲁棒性

**工作量:** 中等 (2天)

---

### 4.3 远期可借鉴 — L4 主动式愿景 (v17.0+)

#### **借鉴点 7: 持续监控与任务发现**

**论文观点 (§4.3):**
> L4 数据智能体持续监控 Data+AI 生态系统，自主发现问题和机会 (数据漂移、性能退化、缺失索引、有益的物化视图)。

**改进方案 (远期):**
```python
# 监控守护进程 (v17.0+)
class DataLakeMonitor:
    """7x24 监控数据湖"""
    def monitor(self):
        while True:
            # 检测数据漂移
            if self.detect_data_drift():
                self.trigger_task("重新训练模型")

            # 检测性能退化
            if self.detect_performance_regression():
                self.trigger_task("优化查询")

            # 发现优化机会
            if self.discover_optimization_opportunity():
                self.trigger_task("创建索引")

            time.sleep(3600)  # 每小时检查
```

**收益:**
- 从被动响应 → 主动发现
- 无需人工指令

**工作量:** 大 (1-2周)，需要完整的监控基础设施

---

#### **借鉴点 8: 内在动机与探索**

**论文观点 (§4.3):**
> L4 智能体需要内在动机 — 内部奖励信号驱动探索和改进，而非仅响应外部指令。

**改进方案 (远期):**
```python
# 内在动机引擎 (v18.0+)
class IntrinsicMotivation:
    """内部奖励信号"""
    def compute_reward(self, action: Action, outcome: Outcome) -> float:
        reward = 0.0
        # 奖励: 发现新数据源
        if action.type == "discover_data":
            reward += 10.0
        # 奖励: 提升数据质量
        if outcome.quality_improvement > 0:
            reward += outcome.quality_improvement * 5.0
        # 奖励: 减少查询延迟
        if outcome.latency_reduction > 0:
            reward += outcome.latency_reduction * 2.0
        return reward
```

**收益:**
- Agent 自主探索优化空间
- 持续自我改进

**工作量:** 大 (2-3周)，需要强化学习基础设施

---

### 4.4 不适用的论文观点

| 论文观点 | 不适用原因 |
|---------|-----------|
| **L5 生成式能力** (发明新算法) | 超出当前技术边界，所有系统都未实现 |
| **通用数据分析** | Data Agent 是垂直 GIS 平台，不需要通用性 |
| **多模态支持** (图像/视频分析) | GIS 领域主要是矢量/栅格数据，多模态需求有限 |
| **联邦学习** | 单机/小团队场景，不需要跨组织协作 |

---

## 五、行动建议 — Roadmap 调整

### 5.1 v15.9 (近期) — 补齐 Proto-L3 短板

**新增任务 (基于论文):**
1. **Planner-Executor 分离** — 新增 PlannerAgent + ExecutorAgent (2-3天)
2. **工具选择器** — 根据任务特征推荐工具子集 (1天)
3. **管道错误诊断** — 因果推理诊断级联错误 (2天)

**与 DeerFlow 融合任务协同:**
- Planner-Executor 分离 ← 与 D-2 中间件链协同
- 工具选择器 ← 与 D-4 Guardrails 协同

### 5.2 v16.0 (中期) — 完整 L3 能力

**新增任务 (基于论文):**
1. **语义算子层** — Clean/Integrate/Analyze 高层抽象 (2-3天)
2. **多 Agent 协作** — DataEngineer/Analyst/Visualizer 分工 (3天)
3. **计划精化** — 根据执行反馈调整计划 (2天)
4. **工具演化** — 动态工具库管理 (1-2天)

**与遥感智能体并行:**
- 语义算子层可以封装遥感工具
- 多 Agent 协作中增加 RemoteSensingAgent

### 5.3 v17.0+ (远期) — L4 主动式探索

**新增任务 (基于论文):**
1. **持续监控** — DataLakeMonitor 守护进程 (1-2周)
2. **任务发现** — 自主发现数据漂移/性能退化 (1周)
3. **内在动机** — 内部奖励信号驱动探索 (2-3周)

---

## 六、总结

### 6.1 Data Agent 当前水平

**定级: L2.5 (完整 L2 + 部分 Proto-L3)**

- ✅ L2 能力完整 — 环境感知、工具调用、反馈循环、记忆/状态
- 🟡 Proto-L3 部分特征 — 跨生命周期、意图解释、人类监督
- ❌ L3 核心缺失 — Agent 主导的流程编排

### 6.2 相对论文系统的定位

**优势:**
- 垂直领域深度 (28 Toolset) 超越所有通用 Proto-L3 系统
- 前沿研究集成 (世界模型、因果推断、DRL) 是独特优势
- 企业级治理能力与工业系统 (BigQuery/Databricks) 相当

**短板:**
- 动态流程编排能力不如论文中的 Proto-L3 系统
- 缺少 Planner-Executor 分离
- 缺少多 Agent 协作实际应用

### 6.3 论文最有价值的借鉴

**立即可做 (v15.9):**
1. Planner-Executor 分离 — 向 L3 迈进的关键
2. 工具选择器 — 降低 Agent 负担
3. 因果错误诊断 — 提升鲁棒性

**中期目标 (v16.0):**
1. 语义算子层 — 降低组合复杂度
2. 多 Agent 协作 — 专业分工
3. 计划精化 — 动态调整

**远期愿景 (v17.0+):**
1. 持续监控 — 主动发现任务
2. 内在动机 — 自主探索

### 6.4 与 DeerFlow 借鉴的协同

论文借鉴 (L3 能力) + DeerFlow 借鉴 (工程质量) = 完整升级路径：

- **论文** 指明"做什么" (Planner-Executor、语义算子、多 Agent)
- **DeerFlow** 指明"怎么做" (中间件链、Harness/App 分离、上下文摘要)

两者结合，Data Agent 可以在 v16.0 达到**完整 L3 水平**，成为地理空间领域的标杆 Proto-L3 系统。
