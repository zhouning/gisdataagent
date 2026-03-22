# 耕地合规检查清单

本清单可被 farmland-compliance Skill 的审查协议加载。每个检查项包含检查类别、具体规则、严重级别和工具建议。

## 字段标准化检查

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| F1 | DLBM 字段存在 | 必须包含 DLBM（地类编码）字段 | CRITICAL | check_field_standards |
| F2 | DLMC 字段存在 | 必须包含 DLMC（地类名称）字段 | CRITICAL | check_field_standards |
| F3 | TBMJ 字段存在 | 必须包含 TBMJ（图斑面积）字段 | CRITICAL | check_field_standards |
| F4 | DLBM 编码合规 | 所有 DLBM 值必须在 GB/T 21010 编码表中 | HIGH | check_field_standards("gb_t_21010_2017") |
| F5 | DLBM 编码结构 | 耕地编码应为 01xx 格式（4 位） | HIGH | check_field_standards |
| F6 | TBMJ 正值 | 所有面积值必须 > 0 | HIGH | check_attribute_range |

## 拓扑检查

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| T1 | 无自相交 | 所有几何不得自相交 | CRITICAL | check_topology |
| T2 | 无重叠 | 图斑之间不得存在面积重叠 | HIGH | check_topology |
| T3 | 间隙检测 | 图斑之间的间隙面积 < 0.001 km² | MEDIUM | check_gaps |
| T4 | 无多部件 | 每个图斑应为单一几何 | LOW | check_topology |

## 面积校验

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| A1 | 面积公式 | TBDLMJ = TBMJ - KCMJ（容差 0.01㎡） | HIGH | validate_field_formulas |
| A2 | 面积偏差 | 计算面积与属性面积偏差 < 5% | MEDIUM | describe_geodataframe |
| A3 | 微面积检测 | 面积 < 0.1 ㎡ 的图斑标记为疑似 | LOW | check_attribute_range |

## CRS 合规

| # | 检查项 | 规则 | 严重级别 | 工具 |
|---|--------|------|---------|------|
| C1 | CRS 声明 | 数据必须声明坐标参考系 | CRITICAL | describe_geodataframe |
| C2 | CGCS2000 | 应使用 CGCS2000 坐标系（EPSG:4490 或 4526-4554） | HIGH | check_crs_consistency |

## 严重级别说明

- **CRITICAL**: 不通过即阻断，必须修复后才能入库
- **HIGH**: 严重问题，强烈建议修复
- **MEDIUM**: 质量问题，建议修复
- **LOW**: 轻微问题，可忽略或延后修复
