# TWM 算法模型相对 GeoSOS-FLUS 的对比分析

日期：2026-07-02

## 1. 结论边界

当前 TWM 不能被表述为“全面超越 GeoSOS-FLUS”。更准确的表述是：

> 在当前 Dynamic World 100-case 严格评估协议下，TWM 的 geospatial dynamics simulator 在变化检测指标上超过 FLUS，但在整体地图分类指标上仍落后于 FLUS。

最近最佳 strict 候选为：

`twm_pair_topology_support_contrast_strict_false_alarm_churn_guarded_persistence_forecast_demand`

100-case aggregate 结果：

| 指标 | TWM | FLUS | TWM - FLUS |
|---|---:|---:|---:|
| Change FoM | 0.195662 | 0.150955 | +0.044707 |
| Change F1 | 0.324579 | 0.254339 | +0.070240 |
| Overall Accuracy | 0.900997 | 0.918396 | -0.017399 |
| Kappa | 0.770697 | 0.810473 | -0.039776 |
| Macro-F1 | 0.484675 | 0.505526 | -0.020851 |

因此，TWM 当前优势主要体现在 **变化发生位置的识别与排序能力**，不是整体地图一致性全面领先。

## 2. 为什么 TWM 能在变化指标上超过 FLUS

TWM 这次超过 FLUS 的核心原因，不是渲染能力，也不是上层规划能力，而是模拟器核心中的 geospatial transition allocation 能力更贴近当前评估目标。

### 2.1 TWM 显式学习历史变化

TWM 使用 `train_start -> train_end` 的历史变化做 train-only replay，识别：

- 哪些 source class -> target class 转移更可靠；
- 哪些转移在训练 replay 中容易产生 false alarm；
- 哪些地块处于变化前沿、目标地类邻域或稳定内部区。

这些信息只来自训练期，不使用 holdout 标签。

### 2.2 TWM 强制满足 forecast demand

TWM 的 score allocation 会严格满足 projected forecast demand，所以 target-demand absolute error 为 0。

FLUS 使用同一类需求输入，但 CA 模拟输出不一定精确达到目标地类计数。因此，TWM 在这个协议下具有更强的目标需求守恒能力。

### 2.3 TWM 加入 geospatial topology guard

最近几轮迭代加入了多层 geospatial guard：

- `train_topology_stability_score_guard.v1`：抑制稳定地类内部不合理变化；
- `train_unsupported_transition_pressure_score_guard.v1`：惩罚缺少训练变化前沿或目标邻域支撑的变化；
- `train_pair_unsupported_transition_pressure_score_guard.v1`：针对高误报 source->target pair 做更细粒度惩罚；
- `train_pair_topology_support_contrast_score_guard.v1`：对高误报 pair 中的 unsupported cells 降分，同时对 supported cells 加分。

最新 contrast guard 的直接效果是：

| 项目 | Pair support | Pair support contrast |
|---|---:|---:|
| Predicted changes | 214,572 | 214,572 |
| Change hits | 80,548 | 80,738 |
| Change false alarms | 134,024 | 133,834 |
| Change misses | 167,559 | 167,369 |

这说明 contrast guard 没有靠增加变化总量刷指标，而是在固定变化配额下改善了空间排序。

## 3. 是否使用同一份输入数据进行公平对比

在最近的 Dynamic World + FLUS-console 100-case 对比中，整体评估协议是公平的：

- 使用同一批 Dynamic World annual 100m raster cases；
- 使用同一 rolling split：`train_start -> train_end` 训练，`train_end -> holdout` 评估；
- holdout 只用于 evaluation，不进入 TWM training；
- TWM 和 FLUS 面对同一个 initial map、同一个 holdout map、同一个 evaluation mask；
- TWM 与 FLUS 的 forecast candidates 都在同一 formal forecast comparison 中聚合；
- 后续 TWM 迭代复用固定 FLUS 输出，避免每次重新运行 FLUS 引入随机性。

但公平性也有边界：

1. **两者内部机制不同。**
   FLUS 是 ANN suitability + CA allocation 的模型路径；TWM 是 transition scoring + topology guard + demand-constrained allocation 的模型路径。

2. **不是完全相同的内部特征张量。**
   公平点在数据来源、时间切分、评估目标和 holdout 隔离一致，而不是要求两个模型使用完全相同的内部特征表达。

3. **当前不是“全参数调优后的 FLUS 最强版本”声明。**
   现有结论应表述为：在当前项目固定 FLUS-console baseline 与 Dynamic World 100-case 协议下，TWM 在变化指标上超过 FLUS。

## 4. 属于 TWM 的渲染器、模拟器、规划器中的哪一部分

本次与 GeoSOS-FLUS 对比的能力属于：

> TWM simulator / geospatial dynamics model / transition allocation engine

不是 renderer，也不是 planner。

| TWM 部分 | 是否是本次对比核心 | 说明 |
|---|---:|---|
| Renderer | 否 | 只负责地图、变化图、指标和轨迹的可视化，不决定预测结果 |
| Simulator | 是 | 从历史变化中学习转移机制，并预测未来空间变化 |
| Planner | 间接相关 | 规划器消费 simulator 输出做方案比较、约束检查和行动推荐，但本次不是规划器对比 |

本次对比具体评估的是 TWM 的 L1 geospatial dynamics forecasting 能力：

- transition dynamics scoring；
- demand-constrained allocation；
- adaptive change-budget scale；
- topology stability guard；
- pair-specific topology support contrast；
- train-only replay calibration。

## 5. 与 FLUS 的能力差异

FLUS 当前在整体地图保持方面更强：

- Overall Accuracy 更高；
- Kappa 更高；
- Macro-F1 更高；
- false alarm 数量更少。

TWM 当前在变化发现方面更强：

- predicted changes 更接近 actual changes；
- change hits 显著更多；
- change FoM 和 change F1 更高；
- target demand conservation 更严格。

这也解释了为什么二者指标会分化：FLUS 更保守，整体地图准确率高；TWM 更积极模拟变化，变化指标更高，但也带来更多 false alarms。

## 6. 对外表述建议

严谨表述：

> TWM 当前 geospatial dynamics simulator 在 Dynamic World 100-case 严格协议下，在 change FoM 和 change F1 上超过固定 FLUS-console baseline；其优势来自 train-only transition replay、demand-constrained allocation 和 pair-specific topology support contrast。TWM 尚未在 OA、Kappa、Macro-F1 上全面超过 FLUS，因此当前结论应限定为变化预测能力优势，而不是整体地图模拟能力全面领先。

不建议表述：

> TWM 已全面超越 GeoSOS-FLUS。

更适合的研究路线表述：

> TWM 相比传统 CA/ANN 土地利用模拟器的突破点，在于把土地变化模拟从单一适宜性 + 邻域 CA，升级为具有训练 replay、空间拓扑约束、地类转移对可靠性和需求守恒机制的 geospatial world model simulator。
