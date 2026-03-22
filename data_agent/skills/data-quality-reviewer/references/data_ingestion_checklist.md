# 数据入库前质量检查清单

本清单定义数据入库前必须通过的质量检查项。每个检查项包含检查类别、具体规则、严重级别和推荐工具。

## 基础结构检查

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| S1 | CRS 声明 | 数据必须声明坐标参考系 | CRITICAL | describe_geodataframe |
| S2 | 几何有效性 | 无 null/空几何 | CRITICAL | describe_geodataframe |
| S3 | 几何类型一致 | 不应混合点/线/面类型 | HIGH | describe_geodataframe |
| S4 | 记录数 > 0 | 数据集不能为空 | CRITICAL | describe_geodataframe |

## 属性质量检查

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| A1 | 空值率 | 任何字段空值率不超过 30% | HIGH | check_completeness |
| A2 | 重复记录 | 几何重复率 < 1% | MEDIUM | describe_geodataframe |
| A3 | 字段编码 | 编码字段值在合法枚举内 | HIGH | check_field_standards |
| A4 | 数值范围 | 数值字段无明显异常值 | MEDIUM | describe_geodataframe |

## 拓扑质量检查

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| T1 | 无自相交 | 所有几何不得自相交 | HIGH | check_topology |
| T2 | 无重叠 | 面要素之间不得重叠 | MEDIUM | check_topology |
| T3 | 间隙 | 面要素间隙面积 < 阈值 | LOW | check_gaps |

## 合规性检查

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| C1 | CRS 合规 | 应使用 CGCS2000 (EPSG:4490) | HIGH | check_crs_consistency |
| C2 | 敏感数据 | 不应包含暴露的 PII | MEDIUM | classify_data_sensitivity |

## 严重级别说明

- **CRITICAL**: 阻断入库，必须修复
- **HIGH**: 强烈建议修复
- **MEDIUM**: 建议修复
- **LOW**: 可忽略
