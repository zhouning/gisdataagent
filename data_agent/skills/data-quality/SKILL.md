---
name: data-quality
description: "数据治理、审计与质量检查技能。依据国家标准进行合规审计，包括拓扑检查、字段标准化、语义层浏览和数据目录管理。"
metadata:
  domain: governance
  version: "1.0"
  intent_triggers: "governance, audit, quality"
---

# 数据质量技能

## 核心能力

1. **合规审计**: `check_topology` 拓扑检查（重叠/自相交/间隙）、`check_field_standards` 字段标准化比对（GB/T 21010 国标）、`check_consistency` 图文一致性校验
2. **数据探查**: `describe_geodataframe` 完整数据画像（字段类型、空值率、几何有效性、CRS）
3. **数据库检查**: `query_database` SQL 查询、`list_tables` 表清单、`describe_table` 表结构描述
4. **语义层浏览**: `resolve_semantic_context` 语义上下文解析、`discover_column_equivalences` 字段等价发现、`export_semantic_model` 语义模型导出
5. **数据目录**: `list_data_assets` 资产列表、`describe_data_asset` 资产描述、`search_data_assets` 资产搜索

## 审计标准

- 参照《第三次全国国土调查》标准进行字段标准化（DLBM、DLMC、TBMJ 等必备字段）
- 拓扑检查容差: 0.001m
- 坐标系验证: 确认 CGCS2000/WGS84 兼容性
- 面积校验: 图斑面积与属性面积偏差 ≤5%

## 参考资源

- 加载 `references/audit_standards.md` 获取审计标准详情
