# 测绘质检智能体 — 全量能力地图

> GIS Data Agent v16.0 测绘质检子系统：Agent 调用路径、工具清单、工作流模板、REST API、数据库表、MCP 子系统。

---

## 1. 主路径：Governance Pipeline

测绘质检的核心请求（"检查拓扑错误"、"数据质量审计"、"缺陷分类"）由 `intent_router.py` 分类为 **GOVERNANCE**，进入治理管线。

```
governance_pipeline (SequentialAgent)
  ├─ GovExploration        (LlmAgent, Standard)
  ├─ GovProcessing         (LlmAgent, Standard)
  ├─ GovernanceViz         (LlmAgent, Standard)
  └─ GovernanceReportLoop  (LoopAgent, max_iterations=3)
       ├─ GovernanceReporter  (LlmAgent, Standard)
       └─ GovernanceChecker   (LlmAgent, Fast)
```

| Agent | 模型 | 工具集 | 质检中的角色 |
|-------|------|--------|------------|
| **GovExploration** | Standard | `ExplorationToolset`(审计子集: describe_geodataframe, check_topology, check_field_standards, check_consistency) · `DatabaseToolset`(只读: query_database, list_tables) · `GovernanceToolset`(4 有效工具†: check_completeness, check_attribute_range, check_crs_consistency, generate_governance_plan) + ArcPy 治理工具 | QC 入口 — 治理检查 + 治理规划 |
| **GovProcessing** | Standard | `ExplorationToolset`(变换子集: reproject_spatial_data, engineer_spatial_features) · `GeoProcessingToolset`(3: polygon_neighbors, add_field, calculate_field) · `LocationToolset`(2: batch_geocode, reverse_geocode) · `FusionToolset` · `GovernanceToolset`(5 工具: check_gaps, check_duplicates, governance_score, governance_summary, classify_defects) · `PrecisionToolset`(全部 5 工具) + ArcPy 修复工具 | 缺陷修复 + 精度核验 + 评分 |
| **GovernanceViz** | Standard | `VisualizationToolset`(3: visualize_interactive_map, generate_choropleth, compose_map) · `ChartToolset` | 审计可视化 — 雷达图 + 问题分布图 |
| **GovernanceReporter** | Standard | `ReportToolset`(3 工具) | QC 报告生成 (Word/PDF/Markdown) |
| **GovernanceChecker** | Fast | `approve_quality` (内置函数) | 质量门控 — 验证报告完整性，不通过则 LoopAgent 重试 |

> † GovExploration 的 GovernanceToolset `tool_filter` 代码中声明了 8 个名称，但其中 `check_topology_integrity` 实际属于 PrecisionToolset，`check_area_consistency`、`check_building_height`、`check_coordinate_precision` 尚未在 GovernanceToolset 中实现，ADK 会静默忽略不匹配的过滤名称。

---

## 2. 辅助路径：Planner 动态编排

复杂质检任务可由 Planner (`planner_agent`) 动态编排，自主选择调用子 Agent：

```
planner_agent (LlmAgent, Standard)
  ├─ PlannerExplorer     → 数据探查
  ├─ PlannerProcessor    → 数据处理
  ├─ PlannerAnalyzer     → 空间分析
  ├─ PlannerVisualizer   → 可视化
  └─ PlannerReporter     → 报告撰写 (Premium)
```

| Agent | 质检相关能力 |
|-------|------------|
| **PlannerExplorer** | 同 GovExploration 的探查能力 (`ExplorationToolset` 审计子集 + `DatabaseToolset` 只读) |
| **DataEngineerAgent** (S-5 工厂) | `OperatorToolset`(clean_data, integrate_data, list_operators — v16.0 语义算子) + `DataCleaningToolset`(11) + `GovernanceToolset`(全部 18) + `PrecisionToolset`(全部 5) + `ExplorationToolset`(审计) + `DatabaseToolset`(只读+describe) + `FileToolset` |
| **PlannerReporter** (Premium) | 复杂质检报告综合撰写 |

S-5 多 Agent 协作工作流中：
- `FullAnalysis` (FADataEngineer→FAAnalyst→FAVisualizer) — 端到端质检分析
- `RSAnalysis` (RemoteSensing→Visualizer) — 遥感质检辅助 (v16.0 Phase 1)

---

## 3. 辅助路径：QC 工作流模板

通过 `POST /api/workflows/from-template` 实例化。定义在 `data_agent/standards/qc_workflow_templates.yaml`。

| 模板 ID | 名称 | 步数 | 适用场景 |
|---------|------|------|---------|
| `surveying_qc_standard` | 标准质检流程 | 5 | 数据接收→预处理→规则审查→精度核验→报告生成 |
| `surveying_qc_quick` | 快速质检 | 2 | 快速审查 + 报告 |
| `surveying_qc_full` | 全量质检 | 7 | 含自动修正 + 人工复核环节 |
| `qc_dlg` | DLG 专项质检 | 7 | 地物分类→拓扑→属性编码→接边→位置精度→报告 |
| `qc_dom` | DOM 专项质检 | 6 | 影像质量→几何精度→接缝拼接→色彩一致性→报告 |
| `qc_dem` | DEM 专项质检 | 6 | 高程精度→地形合理性→格网完整性→接边→报告 |
| `qc_3dmodel` | 三维模型质检 | 6 | 几何质量→纹理质量→位置精度→LOD一致性→报告 |

每步均有 `sla_seconds` 超时控制和 `retry_on_timeout` 配置。全流程有 `sla_total_seconds` 总 SLA。

---

## 4. 质检工具清单

### 4.1 GovernanceToolset（18 工具）

`data_agent/toolsets/governance_tools.py`

| 工具函数 | 功能 |
|---------|------|
| `check_gaps` | 多边形间隙检测（容差可配） |
| `check_completeness` | 属性完整性验证（必填字段非空率） |
| `check_attribute_range` | 字段值域校验（数值/枚举/正则） |
| `check_duplicates` | 重复要素检测（几何 + 属性） |
| `check_crs_consistency` | 坐标系一致性检查（默认 EPSG:4490） |
| `governance_score` | 综合治理评分（6 维雷达: 拓扑/间隙/完整性/属性/重复/坐标系） |
| `governance_summary` | 审计摘要生成（问题 + 建议 + 评分） |
| `list_data_standards` | 列出已注册数据标准 |
| `validate_against_standard` | 按标准全量校验 |
| `validate_field_formulas` | 字段公式/约束校验 |
| `generate_gap_matrix` | 标准-数据差距矩阵 |
| `generate_governance_plan` | 治理整改计划（自动排优先级） |
| `check_logic_consistency` | 逻辑一致性校验（如 TBMJ=CD*KD） |
| `check_temporal_validity` | 时间有效性校验 |
| `check_naming_convention` | 命名规范检查 |
| `classify_defects` | 缺陷分类（按 GB/T 24356, 30 编码） |
| `classify_data_sensitivity` | 数据敏感度分级 |
| `recommend_data_model` | 数据模型建议 |

### 4.2 PrecisionToolset（5 工具）

`data_agent/toolsets/precision_tools.py`

| 工具函数 | 功能 |
|---------|------|
| `compare_coordinates` | 实测坐标 vs 参考坐标比对（RMSE/最大误差/中位数） |
| `check_topology_integrity` | 拓扑完整性（自交/悬挂点/重叠/间隙/Z-ordering） |
| `check_edge_matching` | 相邻图幅接边分析（坐标偏差 + 属性一致性） |
| `precision_score` | 综合精度评分（多维加权 0-100） |
| `overlay_precision_check` | 多图层套合精度检验 |

### 4.3 DataCleaningToolset（11 工具）

`data_agent/toolsets/data_cleaning_tools.py`

| 工具函数 | 功能 |
|---------|------|
| `fill_null_values` | 空值填充（mean/median/mode/ffill/default） |
| `map_field_codes` | 代码映射转换（如 CLCD→GB/T 21010） |
| `rename_fields` | 字段批量重命名 |
| `cast_field_type` | 字段类型转换 |
| `clip_outliers` | 异常值截断（百分位/固定边界） |
| `standardize_crs` | CRS 标准化（自动重投影, 默认 EPSG:4326） |
| `add_missing_fields` | 按标准补齐缺失字段 |
| `mask_sensitive_fields_tool` | 敏感字段脱敏（mask/redact/hash/generalize） |
| `auto_fix_defects` | 自动缺陷修正（自交/悬挂/间隙/无效几何等） |
| `auto_classify_archive` | 自动分类归档 |
| `batch_standardize_crs` | 批量 CRS 标准化（EPSG:4490） |

### 4.4 OperatorToolset（5 工具，v16.0 语义算子）

`data_agent/toolsets/operator_tools.py`

| 工具函数 | 功能 |
|---------|------|
| `clean_data` | 语义清洗算子 — 自动选择清洗策略 |
| `integrate_data` | 语义集成算子 — 多源数据合并 |
| `analyze_data` | 语义分析算子 — 按 analysis_type 自动分派 |
| `visualize_data` | 语义可视化算子 — 按 viz_type 自动选图 |
| `list_operators` | 列出已注册语义算子 |

> DataEngineerAgent 使用 `clean_data` + `integrate_data` + `list_operators` 子集。

### 4.5 ReportToolset（3 工具）

`data_agent/toolsets/report_tools.py`

| 工具函数 | 功能 |
|---------|------|
| `list_report_templates` | 列出报告模板（surveying_qc / data_quality / governance / general_analysis） |
| `generate_quality_report` | QC 报告生成（Word/PDF/Markdown, 含 8 节: 项目概况/检查依据/审查结果/精度核验/缺陷统计/质量评分/整改建议/结论） |
| `export_analysis_report` | 分析报告导出 |

---

## 5. 缺陷分类法

`data_agent/standards/defect_taxonomy.yaml` — GB/T 24356 标准

**5 大类 × 30 编码，3 级严重度：**

| 类别 | 编码范围 | 示例缺陷 | 严重度权重 |
|------|---------|---------|-----------|
| **FMT** (格式错误) | FMT-001 ~ 006 | 坐标系定义错误、字段类型不匹配、编码格式错误 | A=12, B=4, C=1 |
| **PRE** (精度偏差) | PRE-001 ~ 006 | 平面精度超限、高程精度超限、套合精度超限、接边精度超限 | A=12, B=4, C=1 |
| **TOP** (拓扑错误) | TOP-001 ~ 006 | 自交、悬挂点、多边形重叠、多边形间隙、无效几何 | A=12, B=4, C=1 |
| **MIS** (信息缺失) | MIS-001 ~ 006 | 必填属性缺失、必要图层缺失、元数据缺失 | A=12, B=4, C=1 |
| **NRM** (规范违反) | NRM-001 ~ 006 | 图层命名不规范、字段命名不规范、代码值越界 | A=12, B=4, C=1 |

约 57%（17/30）的缺陷支持 `auto_fix_defects` 自动修正（如 crs_auto_detect_and_set、fix_self_intersection、snap_dangles 等策略）。

---

## 6. REST API（22 端点）

`data_agent/api/quality_routes.py`，通过 `get_quality_routes()` 注册到 Starlette。

### 质量规则 CRUD
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/quality-rules` | 列出质量规则 |
| POST | `/api/quality-rules` | 创建规则 |
| POST | `/api/quality-rules/execute` | 批量执行规则 |
| GET | `/api/quality-rules/{id}` | 规则详情 |
| PUT | `/api/quality-rules/{id}` | 更新规则 |
| DELETE | `/api/quality-rules/{id}` | 删除规则 |

### 质量趋势 & 仪表盘
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/quality-trends` | 30 天质量趋势 |
| GET | `/api/resource-overview` | 资源概览统计 |
| GET | `/api/qc/dashboard` | QC 仪表盘聚合统计 |

### 人工复核工作流
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/qc/reviews` | 列出复核项 |
| POST | `/api/qc/reviews` | 创建复核项 |
| PUT | `/api/qc/reviews/{id}` | 更新复核状态（approve/reject/fix） |

### 报告 & 标准 & 缺陷
| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/reports/generate` | 生成 QC 报告 |
| GET | `/api/reports/templates` | 列出报告模板 |
| GET | `/api/standards` | 列出数据标准 |
| GET | `/api/standards/{id}` | 标准详情 |
| GET | `/api/defect-taxonomy` | 缺陷分类法全量 |

### 告警规则
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/alert-rules` | 列出告警规则 |
| POST | `/api/alert-rules` | 创建告警规则 |
| PUT | `/api/alert-rules/{id}` | 更新/启停告警 |
| DELETE | `/api/alert-rules/{id}` | 删除告警规则 |
| GET | `/api/alert-history` | 告警事件历史 |

---

## 7. 数据库表

| 表 | 迁移 | 用途 |
|----|------|------|
| `agent_quality_rules` | 029 | 用户自定义质量规则 |
| `agent_quality_trends` | 030 | 历史质量评分 |
| `agent_workflows` / `agent_workflow_runs` | 039 | 工作流 + 运行记录（含 SLA/timeout） |
| `agent_mcp_tool_rules` | 040 | MCP 工具选择规则（task_type→tool 映射） |
| `agent_alert_rules` / `agent_alert_history` | 041 | 告警配置 + 告警事件 |
| `agent_kb_documents` (case 扩展) | 042 | 案例库（defect_category / product_type / resolution / tags） |
| `agent_qc_reviews` | 043 | 人工复核（pending→approved/rejected/fixed） |

> 总迁移数 048（001-048）。044-048 为 v15.8/v16.0 新增（metadata_system, prompt_registry, model_gateway, eval_scenarios, unify_data_assets），与 QC 无直接关系但支撑 BCG 平台能力。

### 人工复核工作流状态机

```
自动检测 → pending → (assign) → review → approve ──→ resolved_at
                                        └─ reject → fix → resolved_at
```

字段: `workflow_run_id`, `file_path`, `defect_code`, `severity`(A/B/C), `status`, `assigned_to`, `reviewer`, `review_comment`, `fix_description`, `resolved_at`

---

## 8. MCP 子系统

通过 `McpHubToolset` 聚合的 4 个 MCP 子系统，位于 `subsystems/`：

| 子系统 | 路径 | 集成方式 | 质检中的用途 |
|--------|------|---------|------------|
| **cv-service** | `subsystems/cv-service/` | MCP (stdio) | YOLO 图斑缺陷检测（CAD 元素检测 / 栅格质量评估 / 三维模型校验） |
| **cad-parser** | `subsystems/cad-parser/` | MCP (stdio) | DWG/DXF 解析、OBJ/FBX 解析、格式转换、图层/几何校验 |
| **tool-mcp-servers** | `subsystems/tool-mcp-servers/` | MCP (stdio) | arcgis-mcp (本机 ArcPy 高精度拓扑/坐标转换)、qgis-mcp、blender-mcp |
| **reference-data** | `subsystems/reference-data/` | REST + BaseConnector | 控制点查询 / 基准参考 / 坐标精度比对 |

### MCP 工具规则引擎

`ToolRuleEngine` (mcp_hub.py): task_type → MCP 工具声明式映射，支持优先级排序 + 备用链 + 参数模板。

---

## 9. 知识支撑

| 模块 | 用途 |
|------|------|
| **knowledge_agent** (Vertex AI Search) | 检索质检标准文档 |
| **surveying-qc** Skill (`data_agent/skills/surveying-qc/`) | QC 领域专家指令注入 Agent prompt；触发词: 质检/质量检查/测绘检查/成果检验/验收/QC；4 阶段工作流: 任务理解→数据审查→精度核验→报告生成 |
| **data-quality-reviewer** Skill (`data_agent/skills/data-quality-reviewer/`) | 数据质量评审技能 |
| `defect_taxonomy.yaml` (319 行) | 30 缺陷编码、5 类别、A/B/C 严重度、17 个自动修复策略 |
| `qc_workflow_templates.yaml` (462 行) | 7 个预置模板、41 个工作流步骤 |
| `gb_t_24356.yaml` (216 行) | GB/T 24356-2009 测绘质检主标准 |
| `gb_t_21010_2017.yaml` (98 行) | 土地分类标准 |
| `dltb_2023.yaml` (91 行) | DLG 数据规范 |
| `guardrail_policies.yaml` (57 行) | 安全合规护栏 |
| `rs_experience_pool.yaml` (107 行) | 遥感最佳实践 |
| `satellite_presets.yaml` (75 行) | 卫星数据预设 |
| 案例库 (`knowledge_base.py`) | `add_case()` / `search_cases()` — 按缺陷类别/成果类型/语义查询检索历史 QC 案例 |

### 告警引擎

`AlertEngine` (observability.py): 可配置阈值规则 → 多通道推送 (webhook/websocket)，含冷却时间（默认 300s）。25+ Prometheus 指标跨 6 层（LLM / Tool / Pipeline / Cache / HTTP / Circuit Breaker）。

---

## 10. 总结

```
质检能力矩阵
─────────────────────────────────────────────
Agent:       Governance Pipeline 5 个 LlmAgent
             + Planner 可调度 5 个子 Agent（含 DataEngineerAgent）
             + S-5 FullAnalysis / RSAnalysis 多 Agent 工作流
工具:        5 专用 Toolset = 42 工具函数
               GovernanceToolset (18) + PrecisionToolset (5)
               + DataCleaningToolset (11) + ReportToolset (3)
               + OperatorToolset (5, v16.0 语义算子)
工作流模板:   7 个（标准/快速/全量 + DLG/DOM/DEM/3D 专项, 共 41 步）
REST API:    22 端点（规则/趋势/复核/报告/标准/缺陷/告警/概览）
数据库:       7 张 QC 相关表 + 3 张支撑表（总迁移 048）
缺陷分类:     5 类 30 编码，A/B/C 三级，57% (17/30) 可自动修正
MCP 子系统:   4 个（CV 检测 / CAD 解析 / 专业工具 / 参考数据）
知识:         Vertex AI 标准检索 + 2 个 Skill + 案例库 + 8 标准文件
─────────────────────────────────────────────
```

---

*基于 GIS Data Agent v16.0 (agent.py 836 行, quality_routes.py 22 路由, 48 迁移) 代码核验，2026-04-03。*
