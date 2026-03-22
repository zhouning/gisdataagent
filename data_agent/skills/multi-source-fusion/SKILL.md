---
name: multi-source-fusion
description: "多源数据融合技能（Pipeline 模式）。分步执行数据融合：源识别 → 兼容性评估 → Schema 匹配 → 融合执行 → 质量验证，每步设 Gate 需用户确认。"
metadata:
  domain: fusion
  version: "3.0"
  intent_triggers: "fusion, 融合, 多源, merge, join, 关联, 匹配, 数据整合"
---

# 多源数据融合技能（Pipeline 模式 v3.0）

## 概述

本技能采用 **Pipeline 设计模式**——将融合过程拆分为 5 个检查点步骤，
每步完成后向用户展示中间结果并等待确认，避免 LLM 跳步或在错误数据上执行昂贵操作。

## Pipeline Workflow: 5 Steps with Gates

### Step 1: 数据源识别与画像

Load: references/ 中无需额外文档（使用内置 profile 工具）

Actions:
- 对所有输入数据集执行 `profile_datasets` / `describe_geodataframe`
- 输出每个数据源的：格式、CRS、要素数、字段列表、几何类型

**🔶 GATE 1**: Present source summary table to user → user confirms datasets are correct before proceeding.

### Step 2: 兼容性评估

Actions:
- 调用 `assess_compatibility` 检查 CRS 一致性、空间重叠率、字段匹配度
- 根据评估结果推荐融合策略（spatial_join / union / attribute_join / temporal_merge 等）

**🔶 GATE 2**: Present compatibility matrix and recommended strategy → user confirms or overrides strategy choice.

### Step 3: Schema 匹配与对齐

Actions:
- CRS 统一（自动 reproject 到公共坐标系）
- 字段名映射（识别等价字段，处理命名冲突）
- 时间格式标准化（如需）

**🔶 GATE 3**: Present mapping table (field A → field B, CRS changes) → user confirms or adjusts mappings.

### Step 4: 融合执行

Actions:
- 按确认的策略和映射执行 `execute_fusion`
- 记录融合参数和执行日志

⛔ This step may be compute-intensive. Do NOT proceed without Gates 1-3 cleared.

### Step 5: 质量验证

Actions:
- 检查融合结果：匹配率、冲突率、覆盖率、空值引入率
- 对照质量阈值（匹配率 >80%、冲突率 <5%、覆盖率 >90%、空值引入率 <10%）
- 注册结果到数据目录 + 记录血缘关系

**🔶 GATE 5**: Present quality report → user confirms result is acceptable or requests re-execution with different parameters.

## ⛔ Execution Rules

1. **NEVER skip gates** — each gate requires explicit user confirmation
2. **NEVER auto-select strategy** — always present options and wait for user choice
3. **If any quality metric fails threshold** — highlight the issue and ask user whether to proceed or retry
4. **Log all decisions** in `tool_context.state` for auditability

## 十种融合策略

### 空间类
- **spatial_join**: 基于空间关系关联属性 (intersects/within/nearest)
- **union**: 同构数据纵向拼接
- **intersection**: 提取重叠区域
- **overlay**: 完整叠加运算 (union/intersection/difference)

### 属性类
- **attribute_join**: 基于公共键关联 (left_on/right_on)
- **enrich**: 从参考数据集提取统计值

### 时序类
- **temporal_merge**: 多时期数据按时间轴合并

### 数值类
- **interpolation**: 采样点空间插值 (IDW/Kriging/Spline)
- **blend**: 重叠区数值加权混合
- **aggregate**: 细粒度→粗粒度聚合

## 质量验证阈值

| 指标 | 合格阈值 |
|------|---------|
| 匹配率 | > 80% |
| 冲突率 | < 5% |
| 覆盖率 | > 90% |
| 空值引入率 | < 10% |

## 相关工具

- `profile_datasets` / `describe_geodataframe` — 数据画像
- `assess_compatibility` — 兼容性评估
- `execute_fusion` — 融合执行
- `register_data_asset` — 结果注册
- `get_data_lineage` — 血缘查询
