# UWM 作为 Geospatial World Model 如何融入地理空间知识

日期：2026-07-08

## 1. 核心问题

UWM 作为 geospatial world model 在城市领域的实例，不是把“地理空间知识”作为一句自然语言提示词加入模型，而是通过状态表示、空间图、渲染器、模拟器、规划器和证据门，把地理学中的空间依赖、空间异质性、距离衰减、网络可达性和空间外溢结构化地固化进 world model。

最核心的地理学基本定律是 Tobler 第一定律：

```text
万事万物相互关联，但近的事物比远的事物更相关。
```

UWM 对这一点的实现不是口头引用，而是把“近的更相关”变成可计算的空间关系、状态更新机制和规划约束。

## 2. 在状态空间中体现地理学知识

UWM 的状态不是普通表格，而是 admin unit、grid、road、POI、building、air-quality 等多源地理对象的空间状态向量。每个空间单元都包含：

- 环境暴露：PM2.5、热风险、天气、绿地等；
- 服务可达：POI、essential services、道路上下文、travel-time proxy；
- 形态结构：建筑、楼层、建成区；
- 人群和公平：人口、脆弱性、暴露公平；
- 空间位置和邻接关系。

这对应地理学中的基本认识：地方不是独立样本。每个空间单元都带有位置、邻域、尺度、网络连接和上下游关系。

## 3. 在空间图中体现 Tobler 第一定律

UWM 用行政边界邻接图、道路网络、POI 距离和 spatial spillover kernel，把“近的更相关”变成模型结构：

- 相邻 admin units 之间有 graph edges；
- 相似地理配置 admin units 之间有 geographic-configuration similarity edges；
- 相邻区域之间存在 spillover；
- 交通、污染、热风险、服务改善都不是只影响单点；
- GraphDQN 和 graph-MDP 使用邻接和消息传播，而不是把每个行政单元当作 iid 样本。

因此，Tobler 定律进入了 UWM 的 `graph_mdp_state`、spatial spillover、GraphDQN message passing 和 planner rollout。

2026-07-08 的实现更新进一步补齐了“相似地理配置”：

```text
geographic_similarity_kernel_2026_07_08
panel_unit_count = 1017
similarity_edge_count = 5085
non_adjacent_similarity_edge_count = 4835
rotated_target_similarity_control_passed = true
uses_coordinates_as_similarity_features = false
```

该 kernel 用 full-admin livability panel 中的服务、道路、暴露和宜居需求配置生成 kNN 相似边；行政边界邻接只用于诊断“相似边是否也相邻”，不是相似特征本身。因此它不是把第一定律重复一遍，而是在工程上表达“地理配置相似的地方也可能发生可迁移的城市过程”。

## 4. 在模拟器中体现空间扩散和外溢

传统宜居性分析通常是静态加权：

```text
livability = w1 * air + w2 * service + w3 * green + ...
```

UWM 不是这样。UWM 模拟动作后的状态变化：

```text
action -> local delta -> neighbor spillover -> updated livability state
```

例如增加公共服务，不只改变目标单元的 service accessibility，也会通过邻接关系和可达性结构影响周边单元。交通管控、绿地建设、污染暴露变化也都有空间外溢。

这体现的是地理过程的空间依赖，而不是普通机器学习中的特征相关。

## 5. 在规划器中体现地理约束

UWM 的 planner 不是在抽象 action list 中任意选择动作，而是在真实空间图上选择治理动作：

- action 只能作用于真实行政单元；
- action eligibility 受当前空间状态约束；
- reward 包含目标单元收益、邻域收益、风险和 equity；
- full-admin graph planner 在 1017 个行政单元、7932 条图边上运行，其中 2847 条是行政边界邻接，5085 条是地理配置相似边；
- 动作序列评估考虑空间外溢和风险校正。

这让 UWM 具备了一个关键的 geospatial world model 特征：城市治理行动必须发生在具体空间位置，并产生空间传播。

## 6. 对其他地理学基本规律的体现

除 Tobler 第一定律外，UWM 还体现了以下地理学原则。

### 6.1 空间异质性

不同区域不是同一套参数。UWM 中每个行政单元的状态向量、风险、服务缺口、人口暴露和公平状态都不同。

### 6.2 距离衰减

最近 essential service 距离、estimated travel-time proxy、道路上下文进入 service surface。服务可达性不只由设施数量决定，还受距离和通行条件约束。

### 6.3 空间外部性

一个单元的干预会影响邻居。UWM 的 spatial spillover kernel、graph rollout 和 neighbor benefit 评估都体现了这种外部性。

### 6.4 尺度效应与 MAUP 风险

当前 UWM 明确标注 admin-unit 级别，不把它说成街区、建筑或个体级结论。这是对尺度效应和 MAUP 风险的约束。

### 6.5 网络约束

服务可达性不只看欧氏距离，还引入 OSM road context。full-admin service accessibility surface 使用本地 Gaode POI、OSM roads、nearest essential service distance 和 road-speed travel-time proxy。

### 6.6 相似地理配置

空间关系不只来自“近”，也来自配置相似。UWM 现在通过 `geographic_similarity_kernel` 把服务结构、道路上下文、暴露优先级和宜居需求相近的行政单元连接起来，让 GraphDQN 和 planner 的图状态同时包含近邻边和相似配置边。这对应“相似地理配置可能有相似地理过程”的建模假设。

### 6.7 地方情境性

重庆中心城区的 POI、道路、建筑、空气质量、行政边界共同构成当前 world model 的地理语境。UWM 的结论必须绑定这一数据和场景边界。

## 7. UWM 的“地理学理解”是什么

UWM 对地理学基本规律的理解，不是语言模型式理解，而是工程上的结构化理解：

```text
地理对象 -> 空间状态
邻接 / 距离 / 网络 -> 空间关系
机制表 / 外溢核 -> 地理过程
planner / RL -> 空间行动选择
evidence gate -> 防止越界声称
```

所以 UWM 不是把传统宜居性指数包装成 world model，而是把地理学中的空间依赖、空间异质性、距离衰减、网络可达和空间外溢，变成 renderer-simulator-planner 的核心计算结构。

## 8. 当前边界

当前 UWM 仍不能声称它已经完全理解真实城市的一切地理规律，原因包括：

- 缺少真实政策实施后的 observed outcome；
- service travel-time 仍是 OSM-speed proxy，不是观测出行时间；
- full-admin service surface 不是权威服务清册；
- station-calibrated scene air-quality holdout 仍未完成；
- 真实干预日志、OPE 和因果验证仍是剩余 gate。

因此，当前可以说：

```text
UWM 已经把地理学基本规律结构化进入 geospatial world model 的状态、图关系、模拟器和规划器中，
并在真实全量本地数据基础上形成 bounded support。
```

但不能说：

```text
UWM 已经证明真实城市治理政策实施后优于传统方法。
```
