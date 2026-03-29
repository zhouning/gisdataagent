# 测绘质检智能体架构对比分析

**文档版本**: v1.0
**创建日期**: 2026-03-27
**问题**: 测绘质检智能体与原有 "Agents-Skills-Tools" 实现方式的异同

---

## 核心答案

**本质相同，但层次和组织方式不同**

测绘质检智能体**仍然是**基于 "Agents-Skills-Tools" 架构实现的，只是在此基础上增加了**更高层次的编排和标准化**。

---

## 一、相同点：底层机制一致

### 1.1 都使用 Agent + Tools 模式

```python
# 之前的简单质检
governance_agent = LlmAgent(
    model="gemini-2.5-flash",
    tools=[GovernanceToolset(), PrecisionToolset()],
    instruction="执行质检任务"
)

# 现在的测绘质检（本质相同）
governance_pipeline = SequentialAgent(
    agents=[
        LlmAgent(tools=[GovernanceToolset()]),  # 仍然是 Agent + Tools
        LlmAgent(tools=[PrecisionToolset()]),
    ]
)
```

### 1.2 都通过 Skills 提供场景化指令

- **之前**: `data_agent/skills/` 下的 18 个 Skills（如 `data-quality-check`）
- **现在**: 同样的 Skills，只是通过工作流模板的 `prompt` 字段引用

### 1.3 都使用相同的 Toolsets

- `GovernanceToolset` (18 个工具)
- `PrecisionToolset` (5 个工具)
- `DataCleaningToolset` (11 个工具)

---

## 二、不同点：增加了三层新能力

### 2.1 差异 1：工作流编排层（新增）

#### 之前：用户直接对话，Agent 临时决策

```
用户: "检查这个 DLG 文件的质量"
  ↓
Agent 自由调用工具（无固定流程）
  ↓
返回结果
```

#### 现在：预定义工作流模板，标准化流程

```yaml
# qc_workflow_templates.yaml
- id: qc_dlg
  steps:
    - step_id: data_receive      # 固定步骤 1
    - step_id: topology_check    # 固定步骤 2
    - step_id: attribute_check   # 固定步骤 3
    - step_id: edge_matching     # 固定步骤 4
    - step_id: positional_accuracy  # 固定步骤 5
    - step_id: report            # 固定步骤 6
```

**优势**:
- ✅ 流程可复现（每次执行相同步骤）
- ✅ SLA 可控（每步有超时限制）
- ✅ 可审计（记录每步执行状态）

---

### 2.2 差异 2：标准化知识层（新增）

#### 之前：工具返回自由格式结果

```python
# 之前
def check_topology(file_path):
    return {"errors": ["自相交", "悬挂节点"]}  # 自由格式
```

#### 现在：结果映射到标准缺陷分类法

```python
# 现在
def check_topology(file_path):
    return {
        "defects": [
            {"code": "TOP-001", "severity": "A", "count": 5},  # 标准编码
            {"code": "TOP-002", "severity": "B", "count": 12}
        ]
    }
```

**标准缺陷分类法** (`defect_taxonomy.yaml`):
- 5 大类别: FMT/PRE/TOP/MIS/NRM
- 30 个缺陷编码: TOP-001, TOP-002, ..., NRM-006
- 3 级严重度: A (权重 12), B (权重 4), C (权重 1)
- 基于 GB/T 24356-2009 标准

**优势**:
- ✅ 缺陷可量化评分（A=12分，B=4分，C=1分）
- ✅ 跨项目可对比（都用 GB/T 24356 标准）
- ✅ 知识可积累（案例库按缺陷编码检索）

---

### 2.3 差异 3：子系统集成层（新增）

#### 之前：所有工具都是 Python 函数

```python
# 所有工具在 data_agent/toolsets/ 下
class GovernanceToolset(BaseToolset):
    def check_topology(self, file_path):
        # Python 实现
        gdf = gpd.read_file(file_path)
        # ...
```

#### 现在：通过 MCP 协议集成外部系统

```yaml
# mcp_servers.yaml
- name: arcgis-mcp
  description: "ArcGIS Pro dual-engine: basic arcpy + DL"
  transport: stdio
  command: python.exe
  args: ["subsystems/tool-mcp-servers/arcgis-mcp/server.py"]
  env:
    ARCPY_PYTHON_EXE: "D:/path/to/arcpy/python.exe"
    ARCPY_DL_PYTHON_EXE: "D:/path/to/dl/python.exe"
```

**4 个独立子系统**:
1. **cv-service**: FastAPI + YOLO，视觉检测（纹理质量、缺陷识别）
2. **cad-parser**: ezdxf + trimesh，解析 DWG/DXF/OBJ/STL
3. **arcgis-mcp**: 双引擎（基础 arcpy + DL），9 个工具
4. **reference-data**: PostGIS 参考数据服务

**优势**:
- ✅ 可调用 ArcGIS Pro 的 arcpy（需要独立 Python 环境）
- ✅ 可调用 CV 检测服务（GPU 加速）
- ✅ 可调用 CAD 解析器（处理 DWG/DXF）
- ✅ 松耦合、可独立部署

---

## 三、架构对比图

### 3.1 之前的架构（简单质检）

```
用户对话
  ↓
Intent Router → Governance Pipeline
  ↓
LlmAgent (Gemini 2.5)
  ↓
GovernanceToolset (18 个 Python 工具)
  ↓
返回自由格式结果
```

### 3.2 现在的架构（测绘质检智能体）

```
用户对话 / 工作流模板
  ↓
Intent Router → Governance Pipeline
  ↓
Workflow Engine (YAML 模板驱动)
  ↓
Step 1: LlmAgent + GovernanceToolset
Step 2: LlmAgent + PrecisionToolset (并行)
Step 3: LlmAgent + MCP Tools (arcgis-mcp)
  ↓
结果映射到缺陷分类法 (TOP-001, MIS-001...)
  ↓
质量评分 (A=12, B=4, C=1)
  ↓
生成标准化报告
```

---

## 四、实际代码对比

### 4.1 之前：直接调用工具

```python
# app.py 中的简单调用
@cl.on_message
async def main(message):
    if "质检" in message.content:
        result = await governance_agent.run(message.content)
        await cl.Message(content=result).send()
```

### 4.2 现在：通过工作流引擎

```python
# workflow_engine.py
async def execute_workflow(workflow_id):
    template = load_qc_templates()[workflow_id]

    for step in template['steps']:
        # 1. 加载 Agent
        agent = _make_governance_agent()

        # 2. 执行步骤（带 SLA 监控）
        result = await asyncio.wait_for(
            agent.run(step['prompt']),
            timeout=step['sla_seconds']
        )

        # 3. 映射到缺陷分类法
        defects = classify_defects(result)

        # 4. 记录到数据库
        save_workflow_step(step_id, defects)

        # 5. 检查 SLA 违规
        if elapsed > step['sla_seconds']:
            record_sla_violation(step_id)
```

---

## 五、对比总结表

| 维度 | 之前（简单质检） | 现在（测绘质检智能体） |
|------|-----------------|---------------------|
| **底层机制** | Agents + Skills + Tools | **相同** |
| **流程控制** | Agent 自由决策 | **YAML 模板固定流程** |
| **结果格式** | 自由格式 | **标准缺陷编码 (GB/T 24356)** |
| **工具范围** | Python 工具 | **Python + MCP 外部系统** |
| **可复现性** | 低（每次可能不同） | **高（固定步骤）** |
| **可审计性** | 低（无详细记录） | **高（每步有日志）** |
| **知识积累** | 无 | **有（案例库 + 向量检索）** |
| **SLA 管理** | 无 | **有（每步超时监控）** |
| **质量评分** | 无标准 | **有（加权评分公式）** |
| **报告生成** | 自由格式 | **标准化模板（Word/PDF）** |

---

## 六、结论

测绘质检智能体是在原有 "Agents-Skills-Tools" 架构上的**增强和标准化**，而不是替代。

**核心关系**:
```
测绘质检智能体 = Agents-Skills-Tools (底层)
                + 工作流编排层 (流程标准化)
                + 标准化知识层 (缺陷分类法)
                + 子系统集成层 (MCP 协议)
```

它仍然使用相同的底层机制，但增加了三层新能力，使其从**"临时对话工具"**升级为**"可复现的生产系统"**。

**适用场景**:
- **简单质检**: 适合临时性、探索性的质检任务
- **测绘质检智能体**: 适合生产环境、需要标准化流程、可审计、可复现的质检任务

---

**文档维护**: 本文档应随系统架构演进同步更新
