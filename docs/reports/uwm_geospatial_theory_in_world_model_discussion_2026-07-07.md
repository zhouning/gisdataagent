# UWM 中融入地理空间理论与 GIS 理论的讨论

日期：2026-07-07

## 1. 这个命题是否比较新

把地理空间理论、地理学理论或 GIScience 理论融入世界模型，是一个相对新的命题，但需要分层理解。

不新的部分是：GIScience 和地理学理论本身已经很成熟。例如空间自相关、距离衰减、空间异质性、尺度效应、MAUP、邻域效应、网络可达性等，都是长期存在的理论和方法。GeoAI 也已经发展多年。

新的部分是：把这些地理理论不是作为事后解释或单独分析模块，而是直接嵌入世界模型的状态表示、模拟器、规划器和渲染器中，让智能体在带有空间规律的城市环境中进行反事实推演和行动规划。这个方向仍在形成中。近年的 GeoAI foundation model、geospatial reasoning、spatial AI 等研究也说明，通用 AI 直接理解几何、拓扑、空间异质性和多模态地理数据仍然是难点。

因此，严格说：

- GIS / 地理学理论本身不是新命题；
- GeoAI 也不是新命题；
- 但把 GIScience 理论作为世界模型的 inductive bias、状态约束、转移机制和规划约束，是一个较新的前沿方向。

## 2. 当前 UWM 中已经融入的能力

目前 UWM 已经融入了一部分 GIS 和地理空间理论能力，不是完全没有。

### 2.1 空间邻接与 Tobler 第一定律的工程化

UWM 已经使用重庆 1,017 个乡镇/街道行政单元构建真实行政边界邻接图。

这意味着 UWM 的 simulator 和 planner 不再只看单个行政单元的静态指标，而可以考虑邻接单元之间的空间外溢。

最新新增的 `data_calibrated_spatial_spillover_kernel` 使用以下真实空间字段生成方向性空间传播边：

- shared-boundary length；
- 节点 degree；
- admin livability target panel 中的宜居性需求；
- 暴露优先级字段。

当前空间传播核生成 227 条方向性空间传播边，最大传播因子为 `0.191122072`。

### 2.2 空间异质性

UWM 的状态输入不是全城一个平均值，而是行政单元级状态。

每个行政单元都有不同的：

- 热风险；
- PM2.5 暴露；
- 服务可达性；
- 公平性；
- 宜居性需求。

因此 UWM 的 planner 可以针对不同空间单元选择不同动作，而不是全城套一个统一策略。

### 2.3 网络与可达性思想

UWM 已经引入 OSM 服务点、essential service 和 admin service accessibility。

传统方法可以计算静态服务缺口，而 UWM 进一步把服务改善作为可行动作纳入 simulator 和 planner。

这使 UWM 的输出不只是“哪里缺服务”，而是能够输出“在哪些单元补充服务会带来怎样的反事实变化”。

### 2.4 空间外溢评估

UWM 已有 `spatial_spillover_planner_evaluator`。

它比较 UWM 多步规划和传统静态单步方法在邻近单元上的收益。

当前结果中，UWM 的邻近宜居性变化优势为：

```text
neighbor_livability_delta_advantage = 0.272680076
```

这是传统静态指标排序无法直接获得的输出。

### 2.5 不确定性和空间 holdout

UWM 已接入 scene-aligned gridded PM2.5 holdout 和 conformal uncertainty。

planner 的风险校正收益不是随意设定，而是用同一个 PM2.5 不确定性惩罚同时作用于 UWM 和传统静态基线。

当前最终决策包中的风险校正优势为：

```text
risk_adjusted_advantage_over_static = 0.012777213
```

## 3. 当前仍然缺失的能力

UWM 目前还没有完整吸收所有 GIS 和地理学理论能力。

主要缺口包括：

- 多尺度建模：街区、网格、行政区、都市圈之间的尺度转换还不充分；
- MAUP 显式处理：当前主要是行政单元粒度，还没有系统评估边界划分对结论的影响；
- 真实交通网络 travel-time accessibility：当前服务可达性仍然偏 proxy，不是完整路网时间成本模型；
- 3D 城市形态：已有 building floor morphology，但还不是完整 3D 城市世界；
- 真实政策 outcome 因果验证：当前是 bounded model-based replay，不是已观测政策实施效果；
- 训练型 RL policy：当前是 model-based graph search / replay planning，不是 PPO/SAC 这类已训练完成的策略网络。

## 4. 结论

把地理学和 GIS 理论嵌入世界模型，是一个有前沿性的方向。

当前 UWM 已经在以下方面有初步但真实的融入：

- 空间邻接；
- 空间外溢；
- 空间异质性；
- 可达性；
- 空间不确定性；
- 行政单元级反事实规划。

但 UWM 还没有达到完整地理空间世界模型的程度。

当前最准确的判断是：

```text
UWM 已经具备地理空间世界模型的早期核心能力，
但仍处在 bounded model-based planning 阶段，
尚未完成多尺度 GIScience 理论、3D 城市状态、真实交通网络、政策 outcome 因果验证和训练型 RL policy 的完整融合。
```
