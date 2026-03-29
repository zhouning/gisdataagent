# 空间分析操作参考

## 缓冲区分析 (Buffer)

### 参数说明
| 参数 | 说明 | 示例 |
|------|------|------|
| distance | 缓冲距离（投影坐标系下为米） | 500 |
| resolution | 圆弧段数（默认16） | 32 (更圆滑) |
| cap_style | 端点样式: round/flat/square | round |
| join_style | 连接样式: round/mitre/bevel | round |

### 注意事项
- 必须在投影坐标系下执行（EPSG:4326 下距离单位为度）
- 负缓冲可用于面要素内缩
- 多环缓冲: 依次创建不同距离的缓冲区并做差集

## 叠加分析 (Overlay)

### 操作类型
| 类型 | 说明 | 用途 |
|------|------|------|
| intersection | 相交（取交集） | 提取两图层重叠区域 |
| union | 合并（取并集） | 合并两图层所有区域 |
| difference | 差集（A 减 B） | 从 A 中排除 B 的区域 |
| symmetric_difference | 对称差 | 取非重叠区域 |
| identity | 标识（A 保持完整+B属性） | A 被 B 切割并继承属性 |

### 最佳实践
- 叠加前统一坐标系
- 大数据集建议先用 clip 裁剪到研究区范围
- 叠加后检查碎片多边形（面积过小的切割产物）

## 裁剪 (Clip)
- 输入: 目标图层 + 裁剪范围
- 效果: 仅保留裁剪范围内的部分
- 等同于 `overlay(how='intersection')` 但只保留左表属性

## 面积制表 (Tabulate Area)
- 计算每个分区内各类别的面积
- 输入: 分区图层 + 类别字段
- 输出: 交叉列联表（分区 × 类别 = 面积）

## 空间连接 (Spatial Join)
- 按空间关系（intersects/contains/within）连接两个图层的属性
- `how`: inner/left/right
- `predicate`: intersects (默认), contains, within, touches, crosses
