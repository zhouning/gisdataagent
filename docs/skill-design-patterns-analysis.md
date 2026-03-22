# 5 种 Agent Skill 设计模式分析 — Data Agent 项目借鉴

> 基于 Google Cloud / Skillmatic AI 发布的 [5 Agent Skill Design Patterns Every ADK Developer Should Know](https://x.com/GoogleCloudTech/status/2033953579824758855) 分析。
> 分析日期：2026-03-21

## 背景

这篇文章由 Skillmatic AI 团队（Shubham Saboo & lavinigam）发布，核心观点是：**Skill 的规范格式已经标准化（SKILL.md + YAML frontmatter），真正的挑战在于 Skill 内部的内容设计**。通过研究 Anthropic、Vercel、Google 内部实践等生态中的 Skill 实现，总结出 5 种反复出现的设计模式。

参考来源：
- [Google Cloud Tech 原推](https://x.com/GoogleCloudTech/status/2033953579824758855)
- [Shubham Saboo 推文](https://x.com/Saboo_Shubham_/status/2033958039359992173)
- [Medium: Following Anthropic, Google Releases 5 Essential Agent Skill Design Patterns](https://ai-engineering-trend.medium.com/following-anthropic-google-releases-5-essential-agent-skill-design-patterns-27aa5fa19b44)
- [深度解析 Google ADK 的 5 类 Agent Skill 设计模式（源码级分析）](https://jimo.studio/blog/deep-dive-into-five-agent-skill-design-patterns-of-google-adk/)
- [skillmatic-ai/awesome-agent-skills (GitHub)](https://github.com/skillmatic-ai/awesome-agent-skills)

---

## 模式概览

| # | 模式 | 核心思想 | ADK 实现成熟度 |
|---|------|---------|---------------|
| 1 | **Tool Wrapper** | 按需注入库/API 专家知识 | 最完整（LoadSkillResourceTool 支撑） |
| 2 | **Generator** | 从可复用模板生成结构化文档 | 不完全（模板填充靠 LLM，框架不校验） |
| 3 | **Reviewer** | 基于检查清单的结构化审查 | 与 Tool Wrapper 共享代码，语义区别 |
| 4 | **Inversion** | Agent 先采访用户再行动 | 严重缺陷（无阶段状态管理/门控） |
| 5 | **Pipeline** | 带检查点的严格多步工作流 | 承诺最大，实现最弱（缺 checkpoint） |

> **重要提醒**：据 [jimo.studio 源码级分析](https://jimo.studio/blog/deep-dive-into-five-agent-skill-design-patterns-of-google-adk/)，ADK 框架层面对 Inversion 和 Pipeline 模式的支撑严重不足，门控逻辑完全依赖 LLM 遵守自然语言指令。企业级落地需要在应用层补充工程保障。

---

## 模式 1: Tool Wrapper — 按需注入库/API 专家知识

### 原理

Skill 监听特定关键词，动态加载 `references/` 中的内部文档作为"绝对真理"注入上下文。不在 system prompt 中硬编码 API 规范，而是打包为 Skill，Agent 仅在实际用到该技术时才加载。是最简单也最成熟的模式。

### 项目现状：已实现，覆盖良好

我们的 18 个 built-in skills 基本都属于 Tool Wrapper 模式：

| Skill | references/ 目录 | 内容 |
|-------|-----------------|------|
| `ecological-assessment` | ✅ | NDVI 分级表、DEM 坡度标准、LULC 分类表 |
| `farmland-compliance` | ✅ | 耕地政策合规规范 |
| `postgis-analysis` | ✅ | PostGIS 函数参考 |
| `coordinate-transform` | ✅ | 坐标系转换参考 |
| `land-fragmentation` | ✅ | FFI 计算方法参考 |
| `spatial-clustering` | ✅ | 聚类算法参考 |
| `geocoding` | ❌ | 无 references |
| `buffer-overlay` | ❌ | 无 references |
| `data-import-export` | ❌ | 无 references |
| `3d-visualization` | ❌ | 无 references |
| ... | ... | ... |

### 改进建议

为缺少 `references/` 的 Skills 补充 L3 参考文档：

```
geocoding/references/
  ├── gaode_geocoding_api.md      # 高德地理编码 API 参数规范
  └── tianditu_geocoding_api.md   # 天地图地理编码 API 规范

buffer-overlay/references/
  └── spatial_operations_guide.md  # 缓冲区/叠加分析参数指南

3d-visualization/references/
  └── deckgl_layer_reference.md    # deck.gl 图层类型与参数参考
```

---

## 模式 2: Generator — 从可复用模板生成结构化文档

### 原理

解决 Agent 每次运行生成不同文档结构的问题。利用两个可选目录：
- `assets/` 存放输出模板（fill-in-the-blank）
- `references/` 存放风格指南

Skill 指令充当"项目经理"——加载模板、读取风格指南、问用户缺啥变量、填充文档。适合生成可预测的 API 文档、标准化提交消息、项目架构脚手架。

### 项目现状：未使用

当前所有 Skill 的输出格式由 LLM 自由生成，结构不固定。

### 建议应用场景

#### 场景 A: 数据质量报告（data-profiling）

```
data-profiling/
  ├── SKILL.md
  ├── assets/
  │   └── data_quality_report_template.md   # 标准报告模板
  └── references/
      └── quality_dimensions.md              # 四维评分标准
```

**报告模板示例** (`assets/data_quality_report_template.md`):
```markdown
# 数据质量评估报告

## 基本信息
- 数据集: {{dataset_name}}
- 记录数: {{row_count}} | 字段数: {{col_count}}
- 评估时间: {{timestamp}}

## 四维评分

| 维度 | 得分 | 等级 | 说明 |
|------|------|------|------|
| 完整性 | {{completeness_score}}/100 | {{completeness_grade}} | {{completeness_detail}} |
| 一致性 | {{consistency_score}}/100 | {{consistency_grade}} | {{consistency_detail}} |
| 准确性 | {{accuracy_score}}/100 | {{accuracy_grade}} | {{accuracy_detail}} |
| 时效性 | {{timeliness_score}}/100 | {{timeliness_grade}} | {{timeliness_detail}} |

## 综合评级: {{overall_grade}}

## 字段级详情
{{field_details_table}}

## 改进建议
{{recommendations}}
```

#### 场景 B: 生态评估报告（ecological-assessment）

```
ecological-assessment/
  ├── SKILL.md
  ├── assets/
  │   └── eco_assessment_report_template.md  # NDVI+DEM+LULC 三维评估模板
  └── references/
      └── ndvi_interpretation.md              # 已有
```

#### 场景 C: 治理报告（Governance Pipeline 输出）

Governance Pipeline 的最终报告可以模板化，确保每次输出包含：数据血缘图、质量评分、合规检查结果、改进建议。

---

## 模式 3: Reviewer — 基于检查清单的结构化审查

### 原理

将"检查什么"与"如何检查"分离。检查规则存储在 `references/review-checklist.md` 中，Skill 指令只负责"加载清单→逐项检查→按严重级别分组输出"。**换一份清单就得到完全不同的专项审计**，复用同一个 Skill 骨架。

### 项目现状：部分实现，但检查规则硬编码

`farmland-compliance` 有合规检查逻辑，但检查项直接写在 SKILL.md 中，无法灵活替换。

### 建议改造

#### 改造 farmland-compliance

```
farmland-compliance/
  ├── SKILL.md                              # 只保留审查流程指令
  └── references/
      ├── farmland_compliance_checklist.md   # 耕地合规检查清单
      ├── urban_planning_checklist.md        # 城市规划合规清单（可替换）
      └── ecological_redline_checklist.md    # 生态红线检查清单（可替换）
```

**SKILL.md 指令改造**:
```markdown
## 审查流程

1. Load the appropriate checklist from references/ based on user's audit type
2. For each checklist item:
   a. Execute the specified check against the input data
   b. Record: PASS / WARN / FAIL with evidence
3. Group findings by severity: CRITICAL → HIGH → MEDIUM → LOW
4. Output structured report with pass rate and priority remediation list
```

#### 新增 Skill: data-quality-reviewer

数据入库前的质量审查：

```
data-quality-reviewer/
  ├── SKILL.md
  └── references/
      └── data_ingestion_checklist.md
```

**检查清单内容**:
- 空值率 > 30% → CRITICAL
- 坐标系未声明 → HIGH
- 几何拓扑错误 → HIGH
- 字段类型不一致 → MEDIUM
- 编码格式非 UTF-8 → LOW

---

## 模式 4: Inversion — Agent 先采访用户再行动

### 原理

翻转交互方向——Agent 作为"采访者"，按阶段提问、收集需求，**在所有阶段完成前拒绝开始执行**。依赖显式门控指令（"DO NOT start building until all phases are complete"）。

### 项目现状：未使用

当前复杂分析任务（选址、碎片化评估）要求用户一次性给出所有参数。参数遗漏时 LLM 自行猜测或报错，体验不理想。

### 建议应用场景

#### 场景 A: site-selection（选址分析）— 最高优先级

```markdown
# site-selection/SKILL.md (Inversion 改造)

---
name: site-selection
description: "选址分析技能（采访模式）..."
metadata:
  domain: gis
  version: "3.0"
  intent_triggers: "选址, site selection, 适宜性, suitability"
---

## Interaction Protocol: Structured Interview

### Phase 1: 目标定义
- Ask: 选址目标用途？(工业/商业/住宅/农业/公共服务)
- Ask: 研究区域范围？(上传 GeoJSON 或输入行政区名)

### Phase 2: 约束条件收集
- Ask: 距离约束？(如：距主干道 < 500m, 距水源 > 200m, 距居民区 > 1km)
- Ask: 地形约束？(坡度 < X°, 海拔 < Ym)
- Ask: 土地利用限制？(排除耕地/林地/水域等)
- Ask: 面积约束？(最小面积、最大面积)

### Phase 3: 权重确认
- Present all collected factors in a table
- Ask user to assign weights (1-10) or confirm default weights
- Ask: 评价方法偏好？(加权叠加 / AHP / TOPSIS)

⛔ GATE: DO NOT execute any spatial analysis until Phases 1-3 are ALL complete.
⛔ If any required parameter is missing, ask the user — do NOT guess or use defaults silently.

### Phase 4: 执行分析
Only after gate passes: run suitability analysis with confirmed parameters.
```

#### 场景 B: land-fragmentation（耕地碎片化评估）

类似改造：Phase 1 确认研究区 → Phase 2 确认评估指标（FFI/边界复杂度/面积变异系数）→ Phase 3 确认 DRL 优化参数 → Gate → Phase 4 执行。

### 框架层面的加固

> **警告**：ADK 源码中没有阶段状态管理或门控逻辑的代码实现。约束完全依赖 LLM 遵守自然语言指令，实测 5-10 轮后可能失效。

**建议用 `before_tool_callback` 实现显式状态机**:

```python
def inversion_gate_callback(callback_context, tool, args, tool_context):
    """在 tool_context.state 中维护 _skill_phase，把"约定"转为"代码"。"""
    phase = tool_context.state.get("_skill_phase", "interviewing")

    if phase == "interviewing":
        # 检查所有必需参数是否已收集
        required = {"target_use", "study_area", "constraints", "weights"}
        collected = set(tool_context.state.get("_collected_params", []))
        if not required.issubset(collected):
            return {"error": "采访阶段未完成，请继续收集参数"}

    return None  # 允许执行
```

---

## 模式 5: Pipeline — 带检查点的严格多步工作流

### 原理

Skill 指令本身就是工作流定义。每步加载不同的 reference 文件和模板，设置"diamond gate"条件（如需用户批准才进入下一步），保持上下文窗口干净。利用所有可选目录，在特定步骤才拉入对应资源。

### 项目现状：架构层已有，Skill 层未应用

项目已有三条 SequentialAgent Pipeline（Optimization/Governance/General）和 WorkflowEditor DAG 编排。但 18 个 built-in Skills 内部都没有采用 Pipeline 模式。

### 建议应用场景

#### 场景 A: multi-source-fusion（多源数据融合）

当前是一个笼统 Skill。改造为 Pipeline 模式：

```markdown
## Workflow Steps

### Step 1: 数据源识别
- Detect all input data sources, formats, CRS, schemas
- Load: references/format_compatibility_matrix.md

🔶 GATE: Present source summary → user confirms proceed

### Step 2: Schema 匹配
- Identify common fields, type conflicts, name mappings
- Load: references/schema_matching_rules.md

🔶 GATE: Present mapping table → user confirms or adjusts

### Step 3: 融合执行
- Execute merge/join/union based on confirmed mapping
- Apply CRS unification, type coercion

### Step 4: 质量验证
- Load: references/fusion_quality_checklist.md
- Check: record count preservation, geometry validity, null introduction
- Output quality report (Generator pattern)

⛔ Each gate requires explicit user confirmation before proceeding.
```

#### 场景 B: data-import-export（大文件导入）

分步检查点避免 LLM 跳步：格式检测 → 编码/CRS 确认 → 采样预览 → 完整导入 → 校验。

### 框架层面的加固

> **警告**：ADK 源码缺少 checkpoint 机制、步骤状态机、步骤校验能力。

**建议方案**:
- **路径 A（推荐）**: 用 `SequentialAgent` + `require_confirmation` 把每步拆成独立 Agent，框架级硬门控
- **路径 B**: 引入外部编排框架（如 LangGraph / Prefect / Temporal）管理步骤状态

---

## 模式可组合性

这 5 种模式并非互斥，可以组合使用：

```
┌─────────────────────────────────────────────────────┐
│  site-selection Skill (组合示例)                      │
│                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐       │
│  │ Inversion │ →  │ Pipeline │ →  │ Generator │      │
│  │ (采访收集  │    │ (分步执行  │    │ (报告输出  │      │
│  │  参数)     │    │  带检查点) │    │  模板化)   │      │
│  └──────────┘    └──────────┘    └──────────┘       │
│                       ↓                              │
│                  ┌──────────┐                        │
│                  │ Reviewer  │                        │
│                  │ (结果质量  │                        │
│                  │  自检)     │                        │
│                  └──────────┘                        │
└─────────────────────────────────────────────────────┘
```

---

## 行动计划

### P0 — 高优先级（最大 ROI）

| 行动项 | 模式 | 目标 Skill | 工作量 | 预期收益 |
|--------|------|-----------|--------|---------|
| 为 `site-selection` 加 Inversion 采访流程 | Inversion | site-selection | 中 | 消除参数猜测，大幅提升分析准确性 |
| 为 `land-fragmentation` 加 Inversion 采访流程 | Inversion | land-fragmentation | 中 | DRL 优化参数确认，避免无效计算 |

### P1 — 中优先级（快速见效）

| 行动项 | 模式 | 目标 Skill | 工作量 | 预期收益 |
|--------|------|-----------|--------|---------|
| 为 `data-profiling` 添加报告模板 | Generator | data-profiling | 小 | 报告格式统一，可比性强 |
| 为 `ecological-assessment` 添加报告模板 | Generator | ecological-assessment | 小 | NDVI+DEM+LULC 三维报告标准化 |
| 提取 `farmland-compliance` 检查规则到 references/ | Reviewer | farmland-compliance | 小 | 检查清单可替换，一个骨架多种审计 |

### P2 — 低优先级（完善补充）

| 行动项 | 模式 | 目标 Skill | 工作量 | 预期收益 |
|--------|------|-----------|--------|---------|
| 为无 references 的 Skills 补充 L3 文档 | Tool Wrapper | geocoding 等 | 小 | L3 层真正发挥作用 |
| `multi-source-fusion` 改造为分步 Pipeline | Pipeline | multi-source-fusion | 大 | 复杂融合流程可控 |
| 新增 `data-quality-reviewer` Skill | Reviewer | 新建 | 中 | 数据入库前质量把关 |

### 通用加固措施

- 在 SkillToolset 外层加缓存避免重复加载
- 对 Generator 和 Reviewer 输出加 Pydantic 结构化校验
- 对 Inversion 模式用 `before_tool_callback` + `tool_context.state` 实现显式状态机
- 对 Pipeline 模式用 `SequentialAgent` + `require_confirmation` 实现硬门控

---

## 核心结论

1. **当前状态**: 18 个 built-in Skills 基本全部是 Tool Wrapper 模式，缺少其他 4 种模式的内容设计变化
2. **最大收益**: Inversion 模式（复杂分析任务先采访再执行），解决参数猜测问题
3. **快速见效**: Generator 模式（标准化报告输出），低成本高可见度
4. **务实分工**: **ADK Skill 定义知识，ADK Agent 编排流程** — 不要让 Skill 承担超出框架能力的编排职责
5. **框架局限**: Inversion 和 Pipeline 的门控需要应用层代码加固，不能纯依赖 LLM 自律
