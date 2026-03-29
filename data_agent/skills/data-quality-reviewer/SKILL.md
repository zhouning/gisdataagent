---
name: data-quality-reviewer
description: "数据入库前质量审查技能（Reviewer 模式）。基于可替换检查清单执行结构化审查，确保数据满足入库标准。"
metadata:
  domain: governance
  version: "1.0"
  intent_triggers: "入库审查, 质量审查, 入库前检查, quality review, pre-ingestion, 数据验收"
---

# 数据入库前质量审查技能（Reviewer 模式）

## 技能概述

本技能采用 **Reviewer 设计模式**——在数据入库前执行结构化质量审查。
检查规则存储在 `references/data_ingestion_checklist.md` 中，可替换为
不同场景的检查清单。

## Audit Protocol

### Step 1: 加载检查清单
- Load `references/data_ingestion_checklist.md`
- Identify applicable checks based on data type (vector/raster/tabular)

### Step 2: 逐项执行检查
For EACH checklist item:
1. Execute the specified tool against the input data
2. Record: **PASS** / **WARN** / **FAIL** with evidence (counts, samples)
3. Note severity (CRITICAL / HIGH / MEDIUM / LOW)

### Step 3: 结果评估
1. Group findings by severity: CRITICAL → HIGH → MEDIUM → LOW
2. Calculate pass rate
3. Determine verdict:
   - **可入库**: 无 CRITICAL 失败，pass rate ≥ 90%
   - **需修复**: 无 CRITICAL 失败，pass rate ≥ 70%
   - **不可入库**: 存在 CRITICAL 失败或 pass rate < 70%

### Step 4: 输出审查报告
- 审查概要 + 检查结果表 + 问题清单 + 整改建议
- 推荐清洗工具 (fill_null_values / standardize_crs / rename_fields 等)

## 可用工具

- `describe_geodataframe` — 数据画像
- `check_field_standards` — 字段标准校验（支持 standard_id）
- `check_topology` — 拓扑检查
- `check_completeness` — 完整性检查
- `check_crs_consistency` — CRS 合规
- `validate_field_formulas` — 公式校验
- `classify_data_sensitivity` — 敏感数据检测
- `governance_score` — 综合评分
