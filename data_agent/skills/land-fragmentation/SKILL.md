---
name: land-fragmentation
description: "土地碎片化分析与DRL优化技能（采访模式）。通过结构化参数收集确认研究区、评估指标和优化参数后，计算FFI碎片化指数并运行深度强化学习模型优化用地布局。"
metadata:
  domain: gis
  version: "3.0"
  intent_triggers: "fragmentation, FFI, 碎片化, 优化, DRL, 用地优化, 布局优化"
---

# 土地碎片化分析与 DRL 优化技能（Inversion 采访模式）

## 技能概述

土地碎片化是制约农业规模化经营和生态连通性的关键问题。本技能采用 **Inversion 设计模式**——
先通过结构化采访确认全部分析参数，再执行碎片化评估和 DRL 优化。

## Interaction Protocol: Structured Interview

You MUST follow this 4-phase protocol. Do NOT skip phases or guess parameters.

### Phase 1: 研究区确认
Ask the user:
- **研究区数据**: 请上传包含地类编码的矢量数据（Shapefile/GeoJSON/GPKG）
- **地类字段名**: 哪个字段包含土地利用分类编码？（如 DLBM、landuse、class）
- **研究区名称**: 分析区域名称（用于报告标题）

### Phase 2: 评估指标确认
- **碎片化指标选择**: FFI 综合指数（默认）/ LSI 景观形状指数 / AI 聚集度指数？
- **分地类统计**: 是否需要分别计算各地类的碎片化指数？（推荐开启）
- **是否进行 DRL 优化**: 仅评估碎片化 / 评估 + 优化？

### Phase 3: DRL 优化参数确认（仅当选择优化时）
Present parameter table with defaults, ask user to confirm or adjust:
- **max_conversions**: 最大交换地块数（默认：总地块数的 10%）
  - 保守 5% / 平衡 10-15% / 激进 20-30%
- **目标地类对**: 耕地-林地配对（默认）/ 其他地类对
- **坡度约束**: 坡度 > 25° 的地块是否排除？（默认是）
- **优化场景**: 耕地优化 / 城市绿地 / 设施选址 / 交通网络 / 综合规划

### ⛔ EXECUTION GATE

**DO NOT execute any analysis tools until Phases 1-3 are ALL completed.**
**If the user's data lacks a land-use field, ASK which field to use — do NOT guess.**

Checklist before execution:
- [ ] 研究区数据已上传且可读
- [ ] 地类字段名已确认
- [ ] 评估指标已选择
- [ ] DRL 参数已确认（如需优化）

### Phase 4: 执行分析

```
1. describe_geodataframe  → 数据画像，确认地类字段和几何信息
2. reproject_spatial_data  → 统一到投影坐标系（FFI 需要面积/距离）
3. ffi                    → 计算基线 FFI（优化前碎片化指数）
4. drl_model              → 运行 DRL 优化（使用确认的参数）
5. ffi                    → 计算优化后 FFI
6. 对比分析               → FFI 变化 + 空间布局差异
7. 可视化                 → 优化前后对比地图（分类着色）
```

## FFI 碎片化指数

详见 references/ffi_methodology.md。

| FFI 范围 | 等级 | 含义 |
|----------|------|------|
| < 0.3 | 低 | 地块集中连片，适合规模化 |
| 0.3-0.6 | 中 | 存在碎片化，有优化空间 |
| 0.6-0.9 | 高 | 碎片化严重，影响效率 |
| > 0.9 | 极高 | 急需布局调整 |

## 优化效果预期

- FFI 降低 0.1-0.2: 显著改善
- FFI 降低 0.05-0.1: 中等改善
- FFI 降低 < 0.05: 当前布局已较优或约束过紧

## 常见问题与陷阱

- **坐标系**: FFI 需投影坐标系，地理坐标系会导致面积/距离不准
- **地块数量不足**: 耕地或林地斑块 < 10 个时优化效果有限
- **地类比例失衡**: 单一地类占比 > 90% 时可交换配对极少
- **DRL 结果是建议**: 实际调整还需考虑权属、政策等非空间因素

## 可用工具

- `describe_geodataframe` — 数据画像
- `ffi` — 碎片化指数计算
- `drl_model` — DRL 优化引擎
- `reproject_spatial_data` — 坐标系转换
- `visualize_geodataframe` — 分类着色可视化
