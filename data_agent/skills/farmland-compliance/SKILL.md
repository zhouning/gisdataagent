---
name: farmland-compliance
description: "耕地合规审计技能（Reviewer 模式）。基于可替换检查清单执行结构化审查，支持耕地合规、城市规划、生态红线等多种审计场景。"
metadata:
  domain: governance
  version: "3.0"
  intent_triggers: "audit, compliance, 合规, 国土调查, 三调, GB/T 21010, 耕地审计"
---

# 耕地合规审计技能（Reviewer 模式）

## 技能概述

本技能采用 **Reviewer 设计模式**——将"检查什么"（清单）与"如何检查"（审查流程）分离。
检查规则存储在 `references/` 目录的清单文件中，更换清单即可执行不同类型的审计。

## 可用检查清单

| 清单文件 | 适用场景 |
|----------|---------|
| `farmland_compliance_checklist.md` | 耕地合规审计（三调/变更调查） |
| `audit_standards.md` | GB/T 21010 标准参考 |

> 可扩展: 添加 `urban_planning_checklist.md`（城市规划）、`ecological_redline_checklist.md`（生态红线）等。

## Audit Protocol

### Step 1: 加载检查清单
- Load the appropriate checklist from `references/` based on audit type
- Default: `farmland_compliance_checklist.md`

### Step 2: 逐项执行检查
For EACH checklist item:
1. Execute the specified tool against input data
2. Record: **PASS** / **WARN** / **FAIL** with evidence
3. Note severity level (CRITICAL / HIGH / MEDIUM / LOW)

### Step 3: 结果分组与评分
1. Group findings by severity: CRITICAL → HIGH → MEDIUM → LOW
2. Calculate pass rate: `passed / total × 100%`
3. Verdict: 通过 (≥90% + no CRITICAL) / 有条件通过 (≥70%) / 不通过

### Step 4: 输出审计报告
- 审计概要 + 检查结果表 + 问题清单 + 整改建议

## 适用标准

- **GB/T 21010-2017**: 土地利用现状分类（12 大类 73 小类）
- **TD/T 1055-2019**: 第三次全国国土调查技术规程
- **GB/T 33469-2016**: 耕地质量等级

## 可用工具

- `describe_geodataframe` — 数据画像
- `check_field_standards` — 字段标准化检查（支持标准 ID 自动加载）
- `check_topology` — 拓扑合规检查
- `check_gaps` — 间隙检测
- `check_crs_consistency` — CRS 合规检查
- `validate_field_formulas` — 面积公式校验
- `governance_score` — 综合评分
