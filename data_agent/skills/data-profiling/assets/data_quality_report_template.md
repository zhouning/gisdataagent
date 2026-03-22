# 数据质量评估报告

## 基本信息
- 数据集: {{dataset_name}}
- 记录数: {{row_count}} | 字段数: {{col_count}}
- 坐标参考系: {{crs}}
- 几何类型: {{geometry_types}}
- 文件格式: {{file_format}}
- 评估时间: {{timestamp}}

---

## 四维质量评分

| 维度 | 得分 | 等级 | 说明 |
|------|------|------|------|
| 完整性 (30%) | {{completeness_score}}/100 | {{completeness_grade}} | {{completeness_detail}} |
| 一致性 (25%) | {{consistency_score}}/100 | {{consistency_grade}} | {{consistency_detail}} |
| 准确性 (25%) | {{accuracy_score}}/100 | {{accuracy_grade}} | {{accuracy_detail}} |
| 时效性 (20%) | {{timeliness_score}}/100 | {{timeliness_grade}} | {{timeliness_detail}} |

**综合评级: {{overall_grade}} ({{overall_score}}/100)**

---

## 字段级详情

{{field_details_table}}

---

## 空间质量检查

| 检查项 | 结果 | 详情 |
|--------|------|------|
| 空/无效几何 | {{null_geometry_count}} / {{row_count}} | {{null_geometry_detail}} |
| 重复几何 | {{duplicate_geometry_count}} | {{duplicate_geometry_detail}} |
| 坐标范围异常 | {{coord_anomaly_count}} | {{coord_anomaly_detail}} |
| 混合几何类型 | {{mixed_geometry}} | {{mixed_geometry_detail}} |

---

## 关键问题清单

{{issues_list}}

---

## 改进建议

{{recommendations}}

---

*报告由 GIS Data Agent 自动生成*
