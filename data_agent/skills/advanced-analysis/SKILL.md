---
name: advanced-analysis
description: "高级分析技能。时间序列预测（ARIMA/ETS）、空间趋势分析、假设分析（What-If）、多场景对比、网络中心性、社区检测和可达性分析。"
metadata:
  domain: analysis
  version: "1.0"
  intent_triggers: "时间序列 预测 forecast ARIMA ETS 趋势分析 trend 假设分析 what-if 场景模拟 scenario 网络分析 network centrality 中心性 社区检测 community 可达性 accessibility 时空分析 spatiotemporal"
---

# 高级分析技能

## 技能概述

本技能提供三类高级空间分析能力：

1. **时空分析**：时间序列预测和空间趋势检测
2. **场景模拟**：假设分析和多场景对比
3. **网络分析**：中心性度量、社区检测和可达性评估

所有分析工具均支持空间数据（SHP/GeoJSON/GPKG）和表格数据（CSV/Excel）。

## 时空分析

### 时间序列预测

使用 ARIMA 或指数平滑（ETS）模型对时序数据进行趋势预测。

**典型场景**：
- 人口增长预测
- 土地利用变化趋势
- 环境指标（PM2.5、水质）时序演变
- 经济指标（GDP、房价）区域预测

**方法选择**：

| 方法 | 适用场景 | 说明 |
|------|----------|------|
| auto | 不确定时 | 自动搜索最优 ARIMA 阶数 (p,d,q) |
| arima | 有趋势或季节性 | ARIMA(1,1,1) 适合差分平稳数据 |
| ets | 平滑趋势 | 指数平滑，适合趋势缓慢变化的数据 |

**最少数据要求**：5 个时间点以上。数据越多，预测越可靠。

### 空间趋势分析

通过坐标回归检测空间梯度方向，并用 Moran's I 量化残差的空间聚集程度。

**输出解读**：
- **x_gradient / y_gradient**：空间梯度方向和强度
- **trend_residual**：趋势拟合残差，正值表示高于趋势面
- **Moran's I**：残差的空间自相关，显著则说明趋势面未能完全解释空间变异

## 场景模拟

### What-If 假设分析

对数据列施加变化倍率（multiplier），模拟"如果…会怎样"的问题。

**使用示例**：
```
场景: {"population": 1.3, "income": 0.9}
含义: 人口增长 30%，收入下降 10%
```

### 多场景对比

同时运行多个假设场景并排名对比，输出对比表格和柱状图。

**使用示例**：
```json
[
  {"name": "乐观", "population": 1.3, "investment": 1.5},
  {"name": "基准", "population": 1.1, "investment": 1.0},
  {"name": "悲观", "population": 0.9, "investment": 0.7}
]
```

## 网络分析

### 中心性分析

从空间数据构建拓扑图，识别网络中的关键节点。

**四种中心性指标**：

| 方法 | 含义 | 适用场景 |
|------|------|----------|
| degree | 连接数量 | 直接连通性，如道路交叉口繁忙度 |
| betweenness | 最短路径经过次数 | 桥梁/瓶颈节点，如关键交通枢纽 |
| closeness | 到其他节点的平均距离 | 空间可达性，如服务设施中心度 |
| eigenvector | 连接重要节点的程度 | 影响力传播，如核心城市识别 |

### 社区检测

将空间要素划分为内部联系紧密的子群。

**两种算法**：
- **Louvain**：最大化模块度，适合大网络，结果稳定（推荐默认）
- **Label Propagation**：基于标签传播，速度快但结果可能不稳定

**模块度 (modularity)**：衡量社区划分质量，范围 [-0.5, 1]，> 0.3 通常表示有意义的社区结构。

### 可达性分析

评估每个空间要素到最近设施的距离，计算可达性评分。

**典型应用**：
- 公共服务设施覆盖率评估（学校、医院、公园）
- 商业选址的客户可达性
- 应急设施覆盖范围分析

**阈值设置建议**：

| 设施类型 | 建议阈值 (米) |
|----------|--------------|
| 社区便利店 | 500-1000 |
| 小学/幼儿园 | 1000-2000 |
| 医院 | 3000-5000 |
| 公园绿地 | 500-1500 |

## 标准工作流程

```
1. describe_geodataframe      → 确认数据结构和字段类型
2. 选择分析类型：
   a. 时间序列 → time_series_forecast
   b. 空间趋势 → spatial_trend_analysis
   c. 假设分析 → what_if_analysis / scenario_compare
   d. 网络分析 → network_centrality / community_detection
   e. 可达性  → accessibility_analysis
3. 解读结果并可视化
```

## 可用工具

- `time_series_forecast` — ARIMA/ETS 时间序列预测
- `spatial_trend_analysis` — 空间趋势检测 + Moran's I
- `what_if_analysis` — What-If 假设分析
- `scenario_compare` — 多场景对比分析
- `network_centrality` — 网络中心性分析（degree/betweenness/closeness/eigenvector）
- `community_detection` — 空间社区检测（Louvain/Label Propagation）
- `accessibility_analysis` — 设施可达性评分
