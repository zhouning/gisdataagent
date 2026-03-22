---
name: data-profiling
description: "空间数据画像与质量评估技能（Generator 模式）。对空间数据进行全面画像分析，按标准化模板输出四维质量评估报告。"
metadata:
  domain: governance
  version: "3.0"
  intent_triggers: "profile, 画像, 数据质量, describe, 探查, 概览, 数据评估"
---

# 空间数据画像与质量评估技能（Generator 模式）

## 技能概述

数据画像是所有空间分析的第一步。本技能采用 **Generator 设计模式**——
使用标准化报告模板（assets/data_quality_report_template.md）和四维评分标准
（references/quality_dimensions.md）确保每次输出格式统一、可比较。
和空间维度的全面评估。

## 画像分析维度

### 基础结构维度

| 检查项       | 内容                                     | 关注点               |
|--------------|------------------------------------------|----------------------|
| 要素数量     | 总记录数、有效记录数                     | 空记录占比           |
| 字段清单     | 字段名、数据类型、示例值                 | 类型是否合理         |
| 几何类型     | Point/LineString/Polygon/Multi*          | 是否存在混合几何     |
| 坐标参考系   | EPSG 代码、投影类型                      | 是否适合目标分析     |
| 坐标范围     | xmin/ymin/xmax/ymax                      | 是否在合理地理范围内 |
| 文件大小     | 磁盘占用、内存占用估算                   | 是否需要分块处理     |

### 属性质量维度

对每个字段进行以下统计：

- **空值率**：NULL 或空字符串的比例
- **唯一值数**：基数（cardinality），判断是否为分类字段
- **值域分布**：数值型字段的 min/max/mean/std/median/Q1/Q3
- **频率分布**：分类字段的 top-N 值及占比
- **异常值检测**：基于 IQR 方法识别离群值（Q1-1.5*IQR, Q3+1.5*IQR）

### 空间质量维度

- **几何有效性**：is_valid 检查，识别自相交、环方向错误等
- **空几何**：geometry 为 None 或 EMPTY 的记录
- **几何复杂度**：顶点数分布，识别过度简化或过度复杂的几何
- **空间分布**：要素的空间聚集程度，是否存在明显的空间偏差

## 数据质量评分体系

采用四维度加权评分（总分 100 分）：

### 完整性（Completeness）— 30分
```
得分 = 30 × (1 - 平均空值率)
阈值：空值率 > 20% 的字段标记 warning
      空值率 > 50% 的字段标记 error
      必填字段空值率 > 0% 标记 error
```

### 一致性（Consistency）— 25分
```
检查项：
- 编码字段值是否在有效值域内
- 关联字段是否逻辑一致（如 DLBM 与 DLMC 对应关系）
- 数值字段是否在合理范围内
- 日期字段格式是否统一
```

### 准确性（Accuracy）— 25分
```
检查项：
- 几何有效性比例（无效几何 > 5% 标记 error）
- 坐标范围是否在中国国境内（经度 73°-135°，纬度 3°-54°）
- 面积属性与几何计算面积的偏差
- 拓扑错误数量
```

### 时效性（Timeliness）— 20分
```
检查项：
- 数据是否包含时间戳字段
- 最新记录的时间距今是否超过预期更新周期
- 是否存在未来日期（数据录入错误）
```

## 常见数据问题

### 混合几何类型
同一图层中同时包含 Polygon 和 MultiPolygon（或 Point 和 MultiPoint）。
大多数空间分析工具要求统一几何类型。解决方案：使用 `explode()` 拆分
多部件几何，或使用 `multi()` 统一为多部件类型。

### 空几何记录
geometry 为 None 的记录会导致空间操作报错。应在分析前过滤或标记。
常见原因：属性表与几何表连接时的不匹配记录。

### 坐标超出范围
WGS84 坐标中经度超过 180° 或纬度超过 90° 表示数据错误。
投影坐标中出现负值或极大值可能是 CRS 标注错误。

### 编码不一致
同一字段中混用不同编码标准（如 GB/T 21010-2007 与 2017 版），
或中英文混用、全半角混用。需在画像阶段识别并统一。

## 标准工作流程

```
1. describe_geodataframe  → 获取完整数据画像
2. 评估质量得分           → 四维度打分，识别主要问题
3. 定位问题字段           → 空值率高、异常值多的字段
4. 检查空间质量           → 几何有效性、CRS 合理性
5. 给出改进建议           → 按优先级排列的修复建议清单
```

## 质量阈值速查

| 指标             | 正常     | 警告      | 错误      |
|------------------|----------|-----------|-----------|
| 字段空值率       | ≤ 5%     | 5%-20%    | > 20%     |
| 无效几何比例     | 0%       | 0%-5%     | > 5%      |
| 面积偏差         | ≤ 1%     | 1%-5%     | > 5%      |
| 编码合规率       | ≥ 99%    | 95%-99%   | < 95%     |
| 重复记录比例     | 0%       | 0%-1%     | > 1%      |

## 可用工具

- `describe_geodataframe` — 核心画像工具，输出字段统计与空间摘要
- `check_field_standards` — 字段标准化检查（配合画像结果使用）
- `check_topology` — 空间质量的拓扑维度检查

## Generator 输出协议

When generating data quality assessment results, you MUST:

1. **Load the report template** from `assets/data_quality_report_template.md`
2. **Load scoring standards** from `references/quality_dimensions.md`
3. Run `describe_geodataframe` to collect raw profile data
4. Calculate four-dimension scores using the scoring rubric
5. **Fill all {{variable}} placeholders** in the template with actual values
6. Output the completed report in Markdown format

Do NOT invent your own report structure — always use the template to ensure consistency across assessments.
- `check_consistency` — 属性一致性校验
