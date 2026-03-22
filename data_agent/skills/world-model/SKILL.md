---
name: world-model
description: "地理空间世界模型技能（Tech Preview）。基于 Google AlphaEarth 嵌入 + LatentDynamicsNet 残差 CNN，在潜空间中自回归预测土地利用变化趋势。支持 5 种情景模拟，构成 JEPA 架构的地理空间世界模型。"
metadata:
  domain: gis
  version: "1.0"
  intent_triggers: "world model, 世界模型, 土地利用预测, land use prediction, 变化预测, 情景模拟, scenario simulation, LULC forecast, 未来预测, 城市蔓延, 生态修复"
---

## 技能概述

本技能调用地理空间世界模型（Plan D），基于 Google AlphaEarth Foundations 的 64 维嵌入向量在潜空间中进行自回归预测。模型学习了 2017-2024 年卫星嵌入的年际变化规律，能推演指定区域在不同政策情景下未来 1-50 年的土地利用演变。

底层技术：AlphaEarth (冻结编码器) → LatentDynamicsNet (学习到的残差动力学) → LULC 线性解码。

## Interaction Protocol: Structured Interview

### Phase 1: 区域定义
- Ask: 请提供研究区域。可以是：
  - 边界框坐标 (minx,miny,maxx,maxy)，例如 `121.2,31.0,121.3,31.1`
  - GeoJSON 文件路径
  - 行政区名称（我会帮您转换为坐标）
- 注意：区域不宜过大（建议 0.1°×0.1° 以内，约 10km×10km），否则 GEE 提取耗时较长

### Phase 2: 情景选择
- 首先调用 `world_model_scenarios` 获取可用情景列表
- 向用户展示 5 个情景及其描述：
  - 🏙️ urban_sprawl — 城市蔓延：高城镇化增速
  - 🌿 ecological_restoration — 生态修复：退耕还林还湿
  - 🌾 agricultural_intensification — 农业集约化：耕地整合扩张
  - 🌊 climate_adaptation — 气候适应：地形依赖型防灾调整
  - 📊 baseline — 基线趋势：现状惯性延续
- Ask: 请选择一个模拟情景

### Phase 3: 时间参数确认
- Ask: 起始年份？（默认 2023，范围 2017-2024）
- Ask: 预测年数？（默认 5 年，范围 1-50）
- 向用户确认所有参数汇总表

⛔ **EXECUTION GATE**
**DO NOT execute `world_model_predict` until Phases 1-3 are ALL completed.**
**If any required parameter is missing or ambiguous, ASK the user — do NOT guess.**

Required checklist:
- [ ] 区域边界框已确认
- [ ] 情景已选择
- [ ] 起始年份和预测年数已确认

### Phase 4: 执行预测

1. 调用 `world_model_predict` 传入 bbox、scenario、start_year、n_years
2. 等待结果（可能需要 10-60 秒，取决于区域大小和预测年数）
3. 将结果分 3 块呈现给用户：
   - **面积分布趋势**：各土地类型百分比随时间变化
   - **转移矩阵**：起始类别→终止类别的像素转换统计
   - **总结**：关键发现和趋势描述

## 常见问题与陷阱

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| GEE 连接失败 | 未认证或网络问题 | 提示用户运行 `earthengine authenticate` |
| 首次运行很慢 | 自动训练模型权重 | 正常现象，约需 2-5 分钟 |
| 预测结果不合理 | 区域超出训练范围 | 建议使用中国境内区域（训练数据覆盖） |

## 可用工具

- `world_model_predict` — 执行世界模型预测
- `world_model_scenarios` — 列出可用情景
- `world_model_status` — 查询模型状态
