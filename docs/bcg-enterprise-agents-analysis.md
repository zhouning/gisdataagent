# BCG《Building Effective Enterprise Agents》分析报告

> **分析对象**: BCG AI Platforms Group《Building Effective Enterprise Agents》(2025年11月, 54页)
> **对标项目**: GIS Data Agent (ADK Edition) v15.7
> **落地场景**: 上海测绘院质检智能体(首个试点) + 未来更多垂直场景
> **分析日期**: 2026-03-28

---

## 执行摘要

### 核心发现

1. **Data Agent已具备Deep Agent架构(BCG H2级别)**: 三管道设计(Optimization/Governance/General)完全符合BCG的"编排器+专业子Agent"模式
2. **平台化能力完整度70%**: 已有Agent Framework、Memory、MCP Registry、LLMOps基础，但缺少**评估体系**和**Prompt管理**
3. **测绘质检试点可行性高**: DA的工作流引擎、标准注册表、治理工具集天然适配质检场景，主要需要**领域定制**而非架构重建
4. **通用平台扩展性强**: 当前架构(Custom Skills + User Tools + Workflow Editor)支持快速复制到其他垂直场景

### 关键建议

**短期(测绘试点, 1-3个月)**:
- P0: 建立评估harness(质检准确率量化)
- P0: 增强Prompt版本管理(质检规则迭代)
- P1: 工作流SLA监控(任务进度可视化)

**中期(平台能力, 3-6个月)**:
- 强化AI Gateway(成本归因+智能路由)
- 上下文工程优化(动态注入+压缩)
- MCP工具选择规则引擎(fallback链)

**长期(生态扩展, 6-12个月)**:
- 场景模板库(测绘/金融/制造等垂直场景)
- Agent Marketplace(可复用的Skill Bundle)
- 跨场景能力复用机制

---

## 一、BCG文档核心方法论解读

### 1.1 企业级Agent的五大挑战

BCG通过2年实践总结出企业级Agent建设的5个关键障碍:

| 挑战 | 描述 | 对DA的启示 |
|------|------|-----------|
| **数据不可靠** | 孤岛化、低信任度、实时性差的数据使Agent决策脆弱 | DA的DataLakeToolset + SemanticLayer已解决数据统一接入，但需增强**数据质量监控** |
| **治理与审计开销** | 企业从第一天就要求可解释性、合规性、策略遵从 | DA的audit_log + RBAC已有基础，但缺少**决策追踪**(为什么Agent做了这个选择) |
| **运营模式摩擦** | 从PoC到生产需要ownership、事件管理、成本控制、版本管理 | DA缺少**FinOps**(成本归因)和**变更管理**(Prompt版本控制) |
| **棕地集成复杂** | 与遗留系统、异构API、细粒度RBAC的集成带来安全和审批风险 | DA的MCP Hub是正确方向，但需增强**工具调用监控**和**失败重试** |
| **缺乏评估体系** | 复杂推理路径隐藏失败模式，追踪工具调用、红队测试、全面评估非常困难 | **DA最大短板**: 无测试数据集管理、无自动化评估流水线 |

**关键洞察**: BCG强调75%的技术领导担心"silent failure"(花钱没效果)。对DA而言，**评估体系是从试点到规模化的生死线**。

### 1.2 Agent成熟度模型(5 Horizons)

BCG定义了Agent进化的5个阶段:

```
H0: 受约束Agent (Constrained)
    - 预定义规则，单一重复任务
    - 例: 简单客服Q&A机器人
    - 状态: 已大规模应用

H1: 单体Agent (Single)
    - 独立处理多步任务，自主规划
    - 例: 引导用户解决问题的聊天机器人
    - 状态: 应用增长中

H2: Deep Agent (编排型) ← 企业应聚焦
    - 编排器将复杂任务分解给专业子Agent
    - 例: 员工入职Agent(邮箱设置+权限申请+设备配置)
    - 状态: 规模化部署中

H3: 角色型Agent (Role-based)
    - 多Agent团队协作，角色分工
    - 例: 营销活动Agent团队(受众分析+广告创作)
    - 状态: 早期阶段

H4: Agent网格 (Agent Mesh)
    - 自组织Agent网络，动态生成子Agent
    - 例: 供应链优化的跨部门Agent协同
    - 状态: 早期研发
```

**Data Agent定位**: 已达到**H2级别**(Deep Agent)，三管道架构 + 28个Toolset + 18个Skills构成了完整的编排体系。**不应盲目追求H3/H4**，而应深化H2能力。

### 1.3 设计原则: Double Diamond方法

BCG改编经典Double Diamond设计流程:

**Discover阶段**:
1. Source & Triage Ideas: 收集业务痛点
2. Assess Outcome Fit: 评估Agent适用性(复杂度 vs 风险)

**Define阶段**:
3. Experience Visioning: 定义人机协作模式
4. Goal Decomposition: 将业务目标分解为依赖树
5. Agent Design: 设计Agent架构(单体 vs 多Agent)
6. Align Platform Capabilities: 评估平台就绪度

**Develop阶段**:
7. Build Capability & Logic: 开发工具和推理逻辑
8. Evaluate, Iterate & Test: 建立评估harness
9. Environment Build: 集成企业系统

**Deploy阶段**:
10. Rollout & Iterate: 渐进式部署(Shadow → Canary → Full)
11. Performance Optimization: 持续优化
12. Continuously Evolve: 反馈闭环

**关键原则**:
- **从业务结果倒推，不是从流程输出**: "30%更快的贷款审批"而非"自动化文档验证"
- **先简单后复杂**: 单Agent失败后再分解为多Agent，避免过度工程
- **明确人机协作模式**: Agent辅助 / 人在环内 / 人在环上 / 人在环外

### 1.4 Agent Design Card (ADC)标准

BCG提出用Agent Design Card标准化设计，核心字段:

```yaml
agent_goal: "Reduce processing time for loan applications"  # Agent可实现的目标
metrics: "30% reduction in manual exception handling time"  # 可量化指标
trigger: "system-led"  # user-led / system-led / proactive / reactive
inputs: "Loan application data, validation rules"
outputs: "Audit log, exceptions"
skills_tools_capabilities:
  - "Document parsing and field validation"
  - "Cross-system data reconciliation (CRM, Credit Bureau)"
  - "Policy-based reasoning for exception routing"
fallback: "Notify loan officer via workflow system"  # 失败时的降级策略
priority: 1  # 业务优先级
```

**对DA的启示**: Custom Skills应增加结构化元数据(metrics, fallback, priority)，而不只是prompt + toolset。

### 1.5 14个核心构建组件

BCG总结的企业级Agent平台必备能力:

| # | 组件 | BCG要求 | DA现状 | 差距 |
|---|------|---------|--------|------|
| 1 | Agent Dev Lifecycle | ML + SWE开发流程融合 | 有基础CI(pytest + frontend build) | 缺评估阶段 |
| 2 | Data Platform | 结构化+非结构化数据服务 | DataLake + SemanticLayer完整 | ✅ 已满足 |
| 3 | Memory | 短期+长期记忆 | Memory + KB + 知识图谱 | ✅ 已满足 |
| 4 | Evaluation | 持续评估和优化 | **无** | ❌ 关键缺失 |
| 5 | Agent Orchestration | 多Agent协调 + A2A协议 | 三管道 + a2a_server.py | ✅ 已满足 |
| 6 | Prompt Tuning | 版本管理 + 迭代 | 无版本控制 | ❌ 关键缺失 |
| 7 | Agent Platform Build | Buy + Build + Configure混合 | 基于ADK(Buy) + 自建编排 | ✅ 已满足 |
| 8 | Context Engineering | 上下文窗口管理 | 基础RAG | ⚠️ 需增强 |
| 9 | AI Gateway | 模型路由 + 成本管理 | model_tier简单路由 | ⚠️ 需增强 |
| 10 | Environment Design | 企业系统集成 | MCP Hub | ✅ 已满足 |
| 11 | Low vs Pro Code | 低代码+专业代码平衡 | Custom Skills(低代码) + Python(专业) | ✅ 已满足 |
| 12 | Enterprise LLMOps | Prompt管理 + 可观测性 | observability.py(25+指标) | ⚠️ 需增强 |
| 13 | Failure Modes | 护栏 + 失败处理 | circuit_breaker.py | ✅ 已满足 |
| 14 | Regulatory & Compliance | 安全 + 隐私 + 数据使用 | RBAC + audit_log | ✅ 已满足 |

**总结**: DA在**架构层**(2,3,5,7,10,11,13,14)已达到企业级标准，但在**运营层**(4,6,8,9,12)有明显短板。

---

## 二、Data Agent现状深度对标

### 2.1 优势领域分析

#### ✅ **Deep Agent架构(H2级别)**

DA的三管道设计完全符合BCG的Deep Agent模式:

```python
# intent_router.py: 编排器
classify_intent(user_message) → "optimization" | "governance" | "general"

# agent.py: 专业子Agent
Optimization Pipeline:
  ParallelIngestion → DataProcessing → AnalysisQualityLoop → Visualization → Summary

Governance Pipeline:
  GovExploration → GovProcessing → GovernanceReportLoop

General Pipeline:
  GeneralProcessing → GeneralViz → GeneralSummaryLoop
```

**优势**:
- 清晰的职责分离(数据优化 vs 治理审计 vs 通用查询)
- 状态传递机制(output_key)支持跨Agent数据流
- 28个Toolset提供细粒度能力组合

**对标BCG案例**: 类似BCG提到的"贷款申请处理Agent"(文档验证Agent + 补救Agent + 编排器)

#### ✅ **平台化能力完整**

DA已具备BCG定义的Agent Platform核心组件:

| BCG组件 | DA实现 | 代码位置 |
|---------|--------|---------|
| Agent Framework & Runtime | ADK + Chainlit | agent.py + app.py |
| Memory | 三层架构 | MemoryToolset + KnowledgeBase + knowledge_graph.py |
| MCP Registry | 支持20个MCP Server | mcp_hub.py |
| Data Platform | 统一数据湖 | data_catalog.py + semantic_layer.py |
| Monitoring & Logging | 25+ Prometheus指标 | observability.py |
| No/Low Code Builder | 可视化编排 | WorkflowEditor(ReactFlow) + Custom Skills |
| Guardrails | 熔断器 + RBAC | circuit_breaker.py + auth.py |

**优势**: 不是"玩具级"原型，而是**生产级平台**，已有2680+测试、43次数据库迁移、202个REST API。

#### ✅ **企业级特性**

DA在企业级需求上的成熟度:

**多租户隔离**:
```python
# user_context.py: ContextVar传播用户身份
current_user_id = ContextVar("current_user_id")
current_user_role = ContextVar("current_user_role")

# 文件沙箱: uploads/{user_id}/
def get_user_upload_dir() -> str:
    user_id = current_user_id.get()
    return f"data_agent/uploads/{user_id}"
```

**审计追踪**:
- audit_log表记录所有敏感操作
- Pipeline执行历史(pipeline_history表)
- Token使用统计(token_usage表)

**容错机制**:
- circuit_breaker.py: 熔断器防止级联故障
- workflow_engine.py: 节点重试机制
- MCP Hub: 工具调用失败处理

**对标BCG要求**: 符合"Governance & Audit overhead"和"OpModel & Scale frictions"的解决方案。

### 2.2 关键差距分析

#### ❌ **差距1: 评估体系缺失(BCG最强调的能力)**

BCG文档第26-27页专门讲评估harness，并给出了保险客户案例: 6个Sprint内F1从50提升到75(+50%)，直接转化为百万美元收入。

**DA当前状态**:
- ✅ 有2680+单元测试(功能覆盖)
- ❌ 无**Agent行为评估**(Agent做的对不对)
- ❌ 无**测试数据集管理**(golden dataset)
- ❌ 无**LLM-as-judge评估**(输出质量)
- ❌ 无**Trajectory评估**(Agent路径是否最优)
- ❌ 无**Red-teaming安全测试**(对抗性测试)

**BCG定义的评估三层**:
```
Layer 1: Single step accuracy (单步准确率)
  - Router intent分类是否正确?
  - Tool selection是否合理?

Layer 2: Planning & trajectory (规划与轨迹)
  - Agent是否按预期的tool call序列执行?
  - 是否有不必要的loop或死循环?

Layer 3: Final outcome (最终输出)
  - 输出是否完整、事实性、符合格式?
  - 是否触犯guardrail?
```

**影响**: 没有评估体系，**无法向客户证明质检准确率**，无法量化迭代效果，无法支撑验收。

#### ❌ **差距2: Prompt管理缺失(BCG第6点)**

BCG第25页强调LLMOps的核心是Prompt生命周期管理:

**DA当前状态**:
- ✅ 有3个YAML prompt文件(prompts/)
- ✅ Custom Skills支持自定义prompt
- ❌ 无**版本控制**(改了prompt无法回滚)
- ❌ 无**环境隔离**(dev/staging/prod)
- ❌ 无**A/B测试**(新prompt vs 旧prompt对比)
- ❌ 无**变更审计**(谁改了什么prompt)

**影响**: 质检规则会频繁迭代(新增缺陷类型、调整审查策略)，没有版本管理会导致"改了A坏了B"的混乱。

#### ⚠️ **差距3: AI Gateway功能薄弱(BCG第9点)**

BCG第24页描述的统一AI Gateway要求:

**DA当前状态**:
- ✅ model_tier三级路由(FAST/STANDARD/PREMIUM)
- ❌ 无**模型注册表**(metadata: cost/latency/capability)
- ❌ 无**动态路由**(根据任务类型自动选模型)
- ❌ 无**FinOps成本归因**(按用户/项目/任务类型统计)
- ❌ 无**质量监控**(模型输出质量趋势追踪)

**影响**: 多场景落地时，不同客户对成本/质量/延迟的权衡不同。金融客户要高准确率，制造客户要低延迟，没有AI Gateway无法灵活适配。

#### ⚠️ **差距4: 上下文工程不足(BCG第8点)**

BCG强调Context Engineering是Agent性能的关键:

**DA当前状态**:
- ✅ KnowledgeBase RAG检索
- ✅ SemanticLayer数据发现
- ❌ 无**上下文压缩策略**(长对话/大文档场景)
- ❌ 无**动态上下文注入**(根据任务阶段调整)
- ❌ 无**Token预算控制**(防止超限)

**影响**: 测绘质检涉及大量标准文档(GB/T 24356有几百页)，全部塞进context会爆token。需要智能注入。

---

## 三、通用平台能力建设建议

> 以下建议遵循一个核心原则: **上海测绘院只是第一个试点，DA的目标是构建可复用的智能体平台**。因此，所有改进都应设计为**通用能力**，测绘质检只是第一个应用实例。

### 3.1 评估引擎: 通用Agent评估框架

#### 设计目标
构建**场景无关的**Agent评估harness，测绘质检是第一个评估场景。

#### 架构设计

```
data_agent/evaluation/
├── __init__.py
├── dataset.py           # 测试数据集管理(通用)
├── evaluator.py         # 评估引擎(可插拔评估器)
├── metrics.py           # 指标计算(准确率/召回率/F1/BLEU)
├── harness.py           # 评估流水线编排
├── judges/
│   ├── llm_judge.py     # LLM-as-judge(通用)
│   ├── rule_judge.py    # 规则匹配评估(通用)
│   └── human_judge.py   # 人工评估接口(通用)
└── scenarios/
    ├── qc_eval.py       # 测绘质检评估场景(试点)
    └── base.py          # 场景基类(扩展点)
```

#### 核心数据模型

```python
# 通用测试用例结构
class TestCase:
    id: str
    scenario: str          # "surveying_qc" | "finance_audit" | ...
    input_data: dict       # 任意输入
    expected_output: dict  # 期望输出
    tags: list[str]        # ["defect_FMT", "severity_A", ...]
    difficulty: str        # "easy" | "medium" | "hard"

# 通用评估结果
class EvalResult:
    test_case_id: str
    scenario: str
    metrics: dict          # {"accuracy": 0.85, "f1": 0.78, ...}
    trajectory: list[dict] # Agent执行轨迹
    latency_ms: int
    token_count: int
    cost_usd: float

# 数据库表
CREATE TABLE eval_datasets (
    id SERIAL PRIMARY KEY,
    scenario VARCHAR(100),     -- 场景标识
    name VARCHAR(200),
    version VARCHAR(50),
    test_cases JSONB,          -- 测试用例集
    created_by VARCHAR(100),
    created_at TIMESTAMP
);

CREATE TABLE eval_runs (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES eval_datasets(id),
    agent_config JSONB,        -- Agent配置快照(prompt版本/toolset/model)
    results JSONB,             -- 评估结果
    summary_metrics JSONB,     -- 汇总指标
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

#### 通用评估流程(场景无关)

```
1. 选择评估数据集(按scenario过滤)
2. 快照当前Agent配置(prompt版本 + toolset + model)
3. 逐条执行测试用例，记录:
   - Agent输出
   - 执行轨迹(tool calls序列)
   - 耗时 + token消耗
4. 运行评估器(LLM-judge / 规则匹配 / 人工)
5. 计算指标(F1 / 准确率 / 成本效率)
6. 与历史基线对比，判断是否进步/退化
7. 生成评估报告
```

#### 测绘质检场景的第一个实例

```python
# evaluation/scenarios/qc_eval.py
class SurveyingQCEvalScenario:
    """测绘质检评估场景"""

    scenario = "surveying_qc"

    def create_test_case(self, input_file, expected_defects):
        return TestCase(
            scenario=self.scenario,
            input_data={"file_path": input_file, "product_type": "DLG"},
            expected_output={"defects": expected_defects},
            tags=[f"defect_{d['code']}" for d in expected_defects]
        )

    def evaluate(self, actual_output, expected_output):
        """
        评估指标:
        - 缺陷识别准确率(Precision)
        - 缺陷识别召回率(Recall)
        - 按30编码分类的F1
        - 误报率(False Positive Rate)
        """
        actual_defects = set(d["code"] for d in actual_output["defects"])
        expected_defects = set(d["code"] for d in expected_output["defects"])

        tp = len(actual_defects & expected_defects)
        precision = tp / len(actual_defects) if actual_defects else 0
        recall = tp / len(expected_defects) if expected_defects else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

        return {"precision": precision, "recall": recall, "f1": f1}
```

#### REST API(通用，非测绘特定)

```
POST   /api/eval/datasets          # 创建评估数据集
GET    /api/eval/datasets           # 列出评估数据集(支持scenario过滤)
POST   /api/eval/run                # 执行评估
GET    /api/eval/runs               # 列出评估运行记录
GET    /api/eval/runs/{id}/report   # 获取评估报告
GET    /api/eval/compare            # 对比两次评估结果
```

#### 为什么这对平台化至关重要

| 场景 | 评估指标 | 复用的通用能力 |
|------|---------|--------------|
| 测绘质检 | 缺陷识别F1, 修正成功率 | 数据集管理, LLM-judge, 轨迹追踪 |
| 金融审计 | 违规识别准确率, 漏报率 | 数据集管理, 规则匹配, 成本统计 |
| 制造质检 | 缺陷分类准确率, 检测耗时 | 数据集管理, CV结果评估, 延迟监控 |
| 环境监测 | 预警及时率, 误报率 | 数据集管理, 时序评估, 阈值检验 |

---

### 3.2 Prompt Registry: 通用Prompt版本管理

#### 设计目标
构建**场景无关**的Prompt全生命周期管理，支持多场景并行迭代。

#### 数据库模型

```sql
CREATE TABLE prompt_versions (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100),       -- "qc_data_audit" | "finance_checker" | ...
    scenario VARCHAR(100),         -- "surveying_qc" | "finance" | NULL(通用)
    version VARCHAR(50),           -- 语义化版本号 "1.2.3"
    environment VARCHAR(20),       -- "dev" | "staging" | "prod"
    prompt_text TEXT,
    variables JSONB,               -- 可注入变量定义
    metadata JSONB,                -- 关联的eval结果、变更原因
    created_by VARCHAR(100),
    created_at TIMESTAMP,
    deployed_at TIMESTAMP,
    is_active BOOLEAN DEFAULT false
);

CREATE TABLE prompt_deployments (
    id SERIAL PRIMARY KEY,
    prompt_version_id INTEGER REFERENCES prompt_versions(id),
    from_env VARCHAR(20),          -- 从哪个环境
    to_env VARCHAR(20),            -- 部署到哪个环境
    deployment_type VARCHAR(20),   -- "full" | "canary" | "ab_test"
    canary_percentage INTEGER,     -- 金丝雀流量百分比
    eval_run_id INTEGER,           -- 关联的评估运行
    deployed_by VARCHAR(100),
    deployed_at TIMESTAMP
);
```

#### 核心API

```python
class PromptRegistry:
    """通用Prompt注册表"""

    def get_prompt(self, agent_name: str,
                   scenario: str = None,
                   env: str = "prod") -> str:
        """获取当前激活的prompt"""
        pass

    def create_version(self, agent_name: str,
                       prompt_text: str,
                       variables: dict = None,
                       scenario: str = None,
                       change_reason: str = "") -> str:
        """创建新版本(自动递增版本号)"""
        pass

    def deploy(self, version_id: int,
               target_env: str,
               deployment_type: str = "full",
               canary_pct: int = None) -> dict:
        """部署prompt到指定环境"""
        pass

    def rollback(self, agent_name: str,
                 env: str = "prod") -> str:
        """回滚到上一个版本"""
        pass

    def compare(self, version_a: int,
                version_b: int) -> dict:
        """对比两个版本的diff"""
        pass
```

#### 平台价值

不同场景的prompt迭代完全隔离，但共享同一套管理基础设施。测绘质检团队修改"缺陷审查prompt"不会影响金融审计团队的"合规检查prompt"。

---

### 3.3 AI Gateway: 统一模型管理

#### 设计目标
构建**场景无关**的模型管理层，支持多模型、多场景、成本可控。

#### 模型注册表

```python
class ModelRegistry:
    """模型注册表 - 集中管理所有可用模型"""

    models = {
        "gemini-2.0-flash": {
            "provider": "google",
            "cost_per_1k_input_tokens": 0.0001,
            "cost_per_1k_output_tokens": 0.0004,
            "latency_p50_ms": 800,
            "latency_p95_ms": 2000,
            "max_context_tokens": 1000000,
            "capabilities": ["classification", "extraction", "summarization"],
            "quality_tier": "standard",
            "regions": ["us-central1", "asia-east1"]
        },
        "gemini-2.5-pro": {
            "provider": "google",
            "cost_per_1k_input_tokens": 0.00125,
            "cost_per_1k_output_tokens": 0.005,
            "latency_p50_ms": 2500,
            "latency_p95_ms": 8000,
            "max_context_tokens": 2000000,
            "capabilities": ["reasoning", "planning", "coding", "analysis"],
            "quality_tier": "premium",
            "regions": ["us-central1"]
        }
    }
```

#### 智能路由

```python
class ModelRouter:
    """根据任务需求 + 约束条件自动选择模型"""

    def route(self, task: dict) -> str:
        """
        路由策略:
        1. 简单分类任务(intent routing) → Flash(低成本/低延迟)
        2. 复杂推理任务(质检报告生成) → Pro(高质量)
        3. 大上下文任务(标准文档+数据) → 按context size选
        4. 预算约束 → 在预算内选最优
        """
        task_type = task.get("type")
        context_size = task.get("context_tokens", 0)
        budget = task.get("budget_per_call_usd", float("inf"))
        quality_requirement = task.get("quality", "standard")

        candidates = self._filter_capable_models(task_type)
        candidates = self._filter_by_context(candidates, context_size)
        candidates = self._filter_by_budget(candidates, budget)

        if quality_requirement == "premium":
            return self._select_highest_quality(candidates)
        else:
            return self._select_most_cost_effective(candidates)
```

#### FinOps成本追踪

```sql
-- 增强现有token_usage表
CREATE TABLE model_usage (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    project_id VARCHAR(100),     -- 项目归属(测绘院项目A/项目B)
    scenario VARCHAR(100),       -- "surveying_qc" | "general"
    agent_name VARCHAR(100),
    model_name VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd DECIMAL(10, 6),
    latency_ms INTEGER,
    created_at TIMESTAMP
);

-- 成本汇总视图
CREATE VIEW cost_summary AS
SELECT
    scenario,
    project_id,
    DATE_TRUNC('day', created_at) AS day,
    SUM(cost_usd) AS total_cost,
    SUM(input_tokens + output_tokens) AS total_tokens,
    COUNT(*) AS call_count,
    AVG(latency_ms) AS avg_latency
FROM model_usage
GROUP BY scenario, project_id, DATE_TRUNC('day', created_at);
```

---

### 3.4 上下文工程管理器

#### 设计目标
构建**通用的**上下文管理层，根据任务阶段动态注入最相关的上下文。

#### 核心设计

```python
class ContextManager:
    """
    通用上下文管理器
    - 动态注入: 根据任务阶段选择性加载上下文
    - Token预算: 控制上下文总量不超过模型限制
    - 优先级排序: 最相关的上下文优先注入
    - 压缩策略: 超限时自动摘要压缩
    """

    def __init__(self, max_tokens: int = 100000):
        self.max_tokens = max_tokens
        self.providers = {}  # 注册的上下文提供者

    def register_provider(self, name: str, provider: ContextProvider):
        """
        注册上下文提供者(可扩展)
        - 测绘场景: 标准文档、缺陷分类法、历史案例
        - 金融场景: 合规政策、历史审计记录、市场数据
        """
        self.providers[name] = provider

    def prepare(self, task_type: str, step: str,
                user_context: dict = None) -> list[ContextBlock]:
        """
        根据任务+阶段准备上下文

        Returns:
            优先级排序的上下文块列表，总token不超过预算
        """
        candidates = []

        for name, provider in self.providers.items():
            blocks = provider.get_context(task_type, step, user_context)
            candidates.extend(blocks)

        # 按相关性排序
        candidates.sort(key=lambda b: b.relevance_score, reverse=True)

        # Token预算控制
        selected = []
        budget = self.max_tokens
        for block in candidates:
            if block.token_count <= budget:
                selected.append(block)
                budget -= block.token_count

        return selected

class ContextBlock:
    """上下文块"""
    source: str          # "standard_doc" | "case_library" | "user_memory"
    content: str
    token_count: int
    relevance_score: float
    compressible: bool   # 是否可以被摘要压缩
```

#### 测绘质检场景的上下文策略

```python
class SurveyingQCContextProvider(ContextProvider):
    """测绘质检的上下文提供者"""

    def get_context(self, task_type, step, user_context):
        blocks = []

        if step == "data_audit":
            # 数据审查阶段: 注入审查规则
            blocks.append(ContextBlock(
                source="defect_taxonomy",
                content=load_yaml("standards/defect_taxonomy.yaml"),
                relevance_score=1.0
            ))
            # 注入相关历史案例(类似数据类型的审查经验)
            product_type = user_context.get("product_type", "DLG")
            cases = search_cases(product_type=product_type, limit=5)
            blocks.append(ContextBlock(
                source="case_library",
                content=format_cases(cases),
                relevance_score=0.8,
                compressible=True
            ))

        elif step == "precision_check":
            # 精度核验阶段: 注入精度标准
            blocks.append(ContextBlock(
                source="precision_standard",
                content=load_standard("gb_t_24356", section="precision"),
                relevance_score=1.0
            ))

        elif step == "report_generation":
            # 报告生成阶段: 注入报告模板
            blocks.append(ContextBlock(
                source="report_template",
                content=load_template("qc_report_standard"),
                relevance_score=1.0
            ))

        return blocks
```

---

### 3.5 场景模板体系: 快速复制到新场景

#### 设计目标
将"测绘质检"抽象为**场景模板(Scenario Template)**，使未来新场景(金融、制造、环境等)可以通过"模板 + 配置"快速落地。

#### 场景模板结构

```yaml
# data_agent/scenario_templates/surveying_qc.yaml
scenario:
  name: "surveying_qc"
  display_name: "测绘质检智能体"
  version: "1.0.0"
  description: "基于GB/T 24356的测绘成果质量检查"

# 1. 缺陷分类法(每个场景有自己的)
taxonomy:
  source: "standards/defect_taxonomy.yaml"
  categories: ["FMT", "PRE", "TOP", "MIS", "NRM"]

# 2. 工作流模板(每个场景有自己的)
workflows:
  - name: "standard_5step"
    source: "standards/qc_workflow_templates.yaml"
    steps: ["接收", "预处理", "规则审查", "精度核验", "报告生成"]

# 3. Skills预设(每个场景有自己的)
skills:
  - name: "qc_data_audit"
    prompt_template: "prompts/qc_data_audit.yaml"
    toolsets: ["GovernanceToolset", "DataCleaningToolset", "PrecisionToolset"]
  - name: "qc_report_gen"
    prompt_template: "prompts/qc_report.yaml"
    toolsets: ["ReportToolset", "ChartToolset"]

# 4. MCP工具映射(每个场景有自己的)
tools:
  - task: "cad_layer_check"
    primary: "arcgis-mcp"
    fallback: "qgis-mcp"
  - task: "image_quality_check"
    primary: "cv-service-mcp"
    fallback: "gemini-vision"

# 5. 评估数据集(每个场景有自己的)
evaluation:
  golden_dataset: "eval/surveying_qc_golden.json"
  metrics: ["defect_f1", "precision", "recall", "fix_success_rate"]
  acceptance_threshold:
    defect_f1: 0.75
    precision: 0.80

# 6. 上下文策略(每个场景有自己的)
context:
  providers:
    - type: "standard_doc"
      config: {standard: "gb_t_24356"}
    - type: "case_library"
      config: {max_cases: 5}
    - type: "defect_taxonomy"
      config: {full: true}
```

#### 场景模板加载器

```python
class ScenarioLoader:
    """加载场景模板，初始化所有场景特定组件"""

    def load(self, scenario_name: str):
        template = load_yaml(f"scenario_templates/{scenario_name}.yaml")

        # 1. 注册缺陷分类法
        TaxonomyRegistry.register(scenario_name, template["taxonomy"])

        # 2. 注册工作流模板
        for wf in template["workflows"]:
            WorkflowEngine.register_template(scenario_name, wf)

        # 3. 注册Skills
        for skill in template["skills"]:
            SkillRegistry.register(scenario_name, skill)

        # 4. 注册MCP工具规则
        for tool_rule in template["tools"]:
            ToolRuleEngine.register(scenario_name, tool_rule)

        # 5. 加载评估数据集
        EvalEngine.load_dataset(scenario_name, template["evaluation"])

        # 6. 注册上下文提供者
        for provider in template["context"]["providers"]:
            ContextManager.register(scenario_name, provider)
```

#### 扩展到新场景的工作量

| 新场景 | 需要定制的 | 复用平台能力的 |
|--------|----------|--------------|
| 测绘质检 | taxonomy + workflow + prompts + eval数据 | 评估引擎, Prompt管理, AI Gateway, 上下文管理 |
| 金融审计 | compliance rules + audit workflow + prompts + eval数据 | 评估引擎, Prompt管理, AI Gateway, 上下文管理 |
| 制造质检 | defect codes + inspection workflow + prompts + eval数据 | 评估引擎, Prompt管理, AI Gateway, 上下文管理 |

**关键**: 平台能力(评估/Prompt/Gateway/Context)只建设一次，每个新场景只需**配置**，不需要**开发**。

---

## 四、测绘质检试点专项建议

> 以下建议特定于上海测绘院试点项目，是通用平台能力在测绘场景的第一个实例化。

### 4.1 Agent Design Card: 测绘质检Agent

按BCG的ADC标准，为测绘质检Agent定义设计卡:

```yaml
# Agent Design Card: 测绘质检智能体
agent_goal: "实现测绘成果质检从'人工抽检'到'全域智控'的跃迁"

metrics:
  - "缺陷识别F1 ≥ 0.75(首批4类成果)"
  - "常规缺陷自动修正率 ≥ 60%"
  - "质检报告生成时间 ≤ 30分钟(vs 人工2-4小时)"
  - "人工复核工作量降低 50%"

trigger: "system-led"  # 数据提交后自动触发质检流程
autonomy: "human-on-the-loop"  # Agent执行，人可干预

inputs:
  - "测绘成果数据(DLG/DOM/DEM/地形图)"
  - "质检标准(GB/T 24356)"
  - "项目精度要求"
  - "参考控制点数据"

outputs:
  - "质检报告(Word/PDF，符合GB/T 24356格式)"
  - "缺陷明细表(Excel)"
  - "缺陷分布图(GeoJSON)"
  - "审计日志"

skills_tools_capabilities:
  - "GovernanceToolset: 规则审查(格式/完整性/规范性)"
  - "DataCleaningToolset: 数据预处理与清洗"
  - "PrecisionToolset: 几何精度核验"
  - "ReportToolset: 质检报告生成"
  - "arcgis-mcp: ArcGIS专业分析(via MCP)"
  - "cv-service-mcp: CV缺陷检测(via MCP)"

fallback:
  - "简单缺陷: 自动修正 → 记录修正日志"
  - "复杂缺陷: 标记 → 推送人工复核队列 → 等待人工确认"
  - "工具不可用: primary tool → fallback tool → 人工介入"

priority: 1
risk_level: "medium"  # 质检结果影响后续作业，但不直接涉及安全
compliance: "GB/T 24356, CH/T 1004"
```

### 4.2 缺陷分类法深度集成

DA v15.7已有30个缺陷编码(5类)，需增强:

```yaml
# 增强后的defect_taxonomy.yaml结构
defects:
  FMT_001:
    name: "格式错误-坐标系不一致"
    category: "FMT"
    severity: "A"
    # === 新增字段 ===
    auto_fixable: true           # 是否可自动修正
    fix_tool: "coordinate_transform"  # 修正工具
    fix_params:                  # 修正参数模板
      target_epsg: "${project_epsg}"
    detection_method: "rule"     # rule | cv_model | llm | hybrid
    detection_rule:              # 规则检测表达式
      type: "crs_mismatch"
      check: "data.crs != project.crs"
    test_cases:                  # 评估用例(关联evaluation)
      - id: "FMT_001_TC01"
        description: "EPSG:4326数据混入EPSG:3857项目"
        expected_detection: true
        expected_fix: true
    frequency: "high"            # 出现频率(用于优先级排序)
    related_standard: "GB/T 24356 §5.2.1"  # 标准条款引用
```

### 4.3 报告模板专业化

```python
# 建议增强: toolsets/report_tools.py
class QCReportGenerator:
    """
    符合GB/T 24356标准的质检报告生成器
    """

    def generate(self, qc_results: dict,
                 template: str = "standard",
                 output_format: str = "docx"):
        """
        报告结构:
        ┌─────────────────────────────┐
        │ 封面                        │
        │   - 项目名称/委托单位        │
        │   - 质检日期/质检员          │
        │   - 文件编号                │
        ├─────────────────────────────┤
        │ 目录(自动生成)              │
        ├─────────────────────────────┤
        │ 1. 项目概况                 │
        │ 2. 质检依据                 │
        │    2.1 执行标准(GB/T 24356)  │
        │    2.2 精度要求              │
        │ 3. 质检过程                 │
        │    3.1 质检方法              │
        │    3.2 工作流执行记录        │
        │ 4. 质检结果                 │
        │    4.1 数据审查结果          │
        │    4.2 精度核验结果          │
        │    4.3 缺陷统计(按30编码)    │
        │    4.4 缺陷分布图           │
        │ 5. 综合评价                 │
        │    5.1 质量等级判定          │
        │    5.2 整改建议(LLM生成)     │
        ├─────────────────────────────┤
        │ 附表1: 缺陷明细表(Excel)    │
        │ 附表2: 精度统计表           │
        │ 附图1: 缺陷分布图(PNG)      │
        └─────────────────────────────┘
        """
        pass
```

### 4.4 人机协作模式设计

基于BCG的4级自治模型，测绘质检应采用**Human-on-the-loop**:

```
用户提交测绘数据
       │
       ▼
  ┌─────────────┐
  │ 自动接收+预处理│  ← 全自动(无需人工)
  └──────┬──────┘
       ▼
  ┌─────────────┐
  │ 规则审查     │  ← 全自动(30编码规则匹配)
  └──────┬──────┘
       ▼
  ┌─────────────┐
  │ 精度核验     │  ← 全自动(PrecisionToolset)
  └──────┬──────┘
       ▼
  ┌─────────────────────────┐
  │ 缺陷分类                 │
  │  ├─ 简单缺陷(auto_fix)  │ → 自动修正 → 日志
  │  ├─ 中等缺陷(需确认)    │ → 推送人工复核队列 ←── 人在环上
  │  └─ 复杂缺陷(需专家)    │ → 升级到专家审核
  └──────┬──────────────────┘
       ▼
  ┌─────────────┐
  │ 报告生成     │  ← 自动生成，人工审核签发
  └──────┬──────┘
       ▼
  ┌─────────────┐
  │ 归档         │
  └─────────────┘
```

**自动化率目标**:
- 80% 常规缺陷: 自动检测 + 自动/半自动修正
- 15% 中等缺陷: 自动检测 + 人工确认修正方案
- 5% 复杂缺陷: 标记后升级到专家人工处理

---

## 五、不应在Data Agent中实现的能力

根据BCG"Buy vs Build"决策框架(文档第34页)，以下能力**不适合**在DA中实现，应作为独立服务通过MCP/REST集成:

| 能力 | 不在DA中实现的原因 | 建议方案 |
|------|-------------------|---------|
| **CV模型训练/推理** | DA是LLM编排平台，不是ML训练平台。CV需要GPU + TensorRT + MLOps | 独立部署cv-service(FastAPI + YOLOv8)，DA通过MCP调用 |
| **三维模型精度核验** | 需要专业三维分析引擎(CGAL/Open3D)，技术栈完全不同 | 通过blender-mcp或独立cad-parser服务 |
| **边缘-中心算力协同** | 需要K8s集群调度 + 边缘设备管理，超出DA范围 | KubeEdge / K3s独立建设 |
| **内外网隔离** | 基础设施层问题(DMZ + 堡垒机 + 数据交换平台) | 独立网络架构设计 |
| **国产化测绘软件适配** | SuperMap/MapGIS的API适配是独立工程 | 独立MCP Server项目(类似arcgis-mcp) |

**DA的定位**: 测绘质检(以及未来更多场景)的**编排中枢**——连接所有专业服务，提供工作流、评估、监控、报告等平台能力。

---

## 六、实施路线图

### Phase 1: 基础平台 + 试点启动 (1-3个月)

**目标**: 补齐平台核心短板，完成测绘质检试点的首次端到端演示。

| 优先级 | 任务 | 类型 | 工作量 |
|--------|------|------|--------|
| P0 | 评估引擎(通用框架 + 测绘场景实例) | 平台能力 | 2周 |
| P0 | Prompt版本管理 | 平台能力 | 1周 |
| P0 | 与上海测绘院合作标注100个golden test cases | 场景定制 | 2周(含沟通) |
| P1 | 工作流SLA运行时监控 | 平台能力 | 1周 |
| P1 | 缺陷分类法深度集成(auto_fix + detection_method) | 场景定制 | 1周 |
| P1 | 质检报告模板(Word/PDF) | 场景定制 | 1周 |
| P2 | 评估Dashboard前端(EvalTab) | 平台能力 | 1周 |

**里程碑**: 能演示"提交DLG数据 → 自动质检 → 生成报告 → 显示F1指标"的完整流程。

### Phase 2: 深化质检 + 平台增强 (3-6个月)

**目标**: 完成4类测绘成果的质检覆盖，同时增强平台通用能力。

| 优先级 | 任务 | 类型 | 工作量 |
|--------|------|------|--------|
| P0 | AI Gateway(模型注册表 + 智能路由 + FinOps) | 平台能力 | 2周 |
| P0 | 上下文工程管理器 | 平台能力 | 2周 |
| P1 | 扩展到4类成果(DLG/DOM/DEM/地形图) | 场景定制 | 4周 |
| P1 | MCP工具选择规则引擎(fallback链) | 平台能力 | 1周 |
| P1 | 集成cv-service(MCP调用) | 场景集成 | 2周 |
| P1 | 集成arcgis-mcp(ArcPy分析) | 场景集成 | 2周 |
| P2 | 自动修正引擎(简单缺陷) | 场景定制 | 2周 |
| P2 | 案例库经验复用优化 | 平台能力 | 1周 |

**里程碑**: 通过上海测绘院的试点验收(缺陷F1 ≥ 0.75)。

### Phase 3: 场景模板化 + 生态扩展 (6-12个月)

**目标**: 将测绘质检经验抽象为场景模板，快速复制到下一个垂直场景。

| 优先级 | 任务 | 类型 | 工作量 |
|--------|------|------|--------|
| P0 | 场景模板体系(ScenarioTemplate + Loader) | 平台能力 | 2周 |
| P0 | 将测绘质检重构为第一个场景模板 | 平台重构 | 1周 |
| P1 | Agent Marketplace(Skill Bundle + 工具 + 模板) | 平台能力 | 3周 |
| P1 | 第二个场景试点(金融审计/制造质检/环境监测) | 场景扩展 | 4周 |
| P2 | 跨场景能力复用分析 | 平台优化 | 1周 |
| P2 | 场景模板市场(用户可发布/订阅场景模板) | 平台能力 | 3周 |

**里程碑**: 第二个场景在2周内完成从"零"到"可演示"。

---

## 七、关键风险与应对

### 风险1: 过度工程化

**描述**: BCG文档反复强调"先简单后复杂"(Always go with the simplest solution)。DA已经很复杂(3267行app.py, 1370行workflow_engine.py)，再加抽象层可能适得其反。

**应对策略**:
- 先用Custom Skills实现质检场景，验证后再固化到核心代码
- 场景模板体系(Phase 3)在Phase 1/2验证后再建设
- 评估引擎先最小化(数据集 + F1计算)，不做过度抽象

### 风险2: 评估数据不足

**描述**: BCG案例显示，保险客户用6个Sprint积累测试集才达到75 F1。测绘质检缺少标注数据。

**应对策略**:
- 与上海测绘院合作，先人工标注100个典型案例作为golden dataset
- 使用LLM生成合成测试数据(synthetic data)作为补充
- 从试点的实际运行中持续积累真实案例

### 风险3: 客户期望管理

**描述**: BCG强调75%的技术领导担心"silent failure"(花钱没效果)。客户可能期望"全自动质检"。

**应对策略**:
- 在方案中明确"自动化率目标"(80%/15%/5%分级)
- 在方案中明确"Human-on-the-loop"模式，而非"全自动"
- 用评估指标(F1/Precision/Recall)量化进展，避免模糊承诺

### 风险4: MCP工具集成复杂度

**描述**: BCG警告"Vendor tech looks great on paper, but real-world issues persist"。arcgis-mcp/qgis-mcp等工具的实际集成可能远比预期复杂。

**应对策略**:
- 工具集成采用渐进式: 先集成最成熟的(arcgis-mcp，已有ArcPy环境)
- 每个工具MCP Server独立开发、独立测试
- 预留fallback: 工具不可用时降级到纯LLM分析 + 人工复核

### 风险5: 平台通用化 vs 场景深化的矛盾

**描述**: 过早追求通用化会导致测绘场景做不深；过度定制测绘场景会导致难以复制。

**应对策略**:
- Phase 1-2: 允许测绘特定代码存在，但保持模块化
- Phase 3: 回顾哪些是"真正通用的"(评估/Prompt管理/Gateway)，哪些是"看似通用实则特定的"
- 遵循"Rule of Three": 至少在2个场景验证后再抽象为通用模块

---

## 八、总结

### Data Agent的战略定位

**短期**: 上海测绘院质检智能体的**技术底座**，提供工作流编排、标准管理、规则审查、报告生成、人工复核等核心能力。

**长期**: 可复用的**企业级智能体平台**，通过场景模板 + 通用引擎(评估/Prompt/Gateway/Context)的架构，支撑快速落地多个垂直行业。

### BCG文档的核心价值

这份BCG文档最大的价值不是具体技术方案，而是**系统化方法论**:

1. **评估驱动开发**: 没有评估体系，一切优化都是盲目的
2. **从业务结果倒推**: 不是"我有什么能力"，而是"客户需要什么结果"
3. **渐进式复杂度**: 先简单，失败后再复杂，避免过度工程
4. **Buy vs Build清晰边界**: 平台能力自建，专业工具集成

### 最关键的3个行动

1. **立即建立评估体系**: 这是从试点到规模化的生死线，也是客户验收的基础
2. **强化Prompt管理**: 质检规则/场景配置会频繁变化，需要版本控制
3. **设计场景模板体系(但不急于实现)**: Phase 1-2用测绘验证，Phase 3才抽象

---

*文档生成日期: 2026-03-28*
*基于: BCG《Building Effective Enterprise Agents》(2025年11月, 54页)*
*对标项目: GIS Data Agent (ADK Edition) v15.7*

