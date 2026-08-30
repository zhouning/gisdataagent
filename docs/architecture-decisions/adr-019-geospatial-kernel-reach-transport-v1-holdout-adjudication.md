# ADR-019：Geospatial Kernel reach transport v1 冻结留出裁决

**Status**: Rejected for scientific promotion; retained as a diagnostic fixture

**Date**: 2026-07-26

**Decision owners**: Geospatial World Model, Geospatial Kernel, Hydrologic Evaluation

**Supersedes**: 不取代 ADR-018 的 diagnostic-use 决定；拒绝的是 v1 的 scientific promotion

## Context

ADR-018 选择有向 first-order reach-storage cascade 作为数据受限条件下的最小候选算子，并要求在
冻结留出中超过基线且通过 action、forcing、方向和守恒 gate。development evidence 完成后，项目
在读取新 outcome 前冻结了 Center Hill temporal holdout：

- acquisition：`[2022-01-06T01Z, 2022-02-03T01Z)`，与 NWM chunk `560` 对齐；
- 前 168 小时只更新状态和提供 persistence 历史；
- 后 504 小时一次性评分；
- candidate、persistence、direct release、zero action、no forcing、reversed active path 和守恒门
  全部预先登记；
- 禁止用 evaluation outcome 改日期、warm-up、velocity scaling、lag、平滑、缺测处理或阈值。

冻结协议 SHA-256 为
`5aff4489afc74a3c759a625a7655f2cee9cab06037a72160b7847dca15b16862`。随后只获取协议规定的 3 个
NWM 对象和 4 个 companion 请求。evaluation 的 672 个 outcome 小时全部各含两个 approved `A`
样本；一个 CWMS inflow context 在 `2022-01-26T19Z` 为原生空值，但该字段不进入 transport
operator，且没有插补。

## Evidence

| 系列 | RMSE (m³/s) | MAE (m³/s) | NSE | gate 含义 |
|---|---:|---:|---:|---|
| candidate v1 | 92.572 | 67.788 | 0.298 | 被裁决对象 |
| outcome persistence | 6.266 | 2.988 | 0.997 | candidate 明显未超过 |
| direct release | 100.611 | 74.660 | 0.171 | candidate 略优于朴素边界值 |
| no forcing | 95.116 | 69.308 | 0.259 | forcing ablation 退化，单项通过 |
| reversed active path | 90.700 | 67.576 | 0.326 | 反向后反而更好，方向 gate 失败 |
| zero action | 无 | 无 | 无 | development 重放时守恒数值门失败 |

candidate 自身 672 个 evaluation 步保持守恒：最大单步残差 `9.14e-7 m3`，全窗残差
`6.03e-5 m3`，小于累计机器精度容差。失败不是由 candidate 主运行的质量泄漏造成，而是：

1. accuracy 没有超过 persistence；
2. reversed topology 没有退化；
3. zero-action 消融无法产生完整守恒序列；
4. non-compensatory overall gate 因此为 `fail`。

## Decision

`StateDependentReachTransportOperator` v1 不得晋级为 scientifically supported Geospatial Kernel，
不得作为 flood-wave transport、benchmark-validated operator 或通用 GWM 内核证据。它保留为：

- typed action/forcing/hydraulics 合同 fixture；
- 线性参考与逐 reach 状态编译 fixture；
- 长窗质量守恒和 artifact lineage fixture；
- 下一算子的负基线。

不得在相同 evaluation 窗上调整 v1 后重新声称独立验证。该窗口现在已经被消费，只能用于失败
分析和 future development，不能再次充当 hidden holdout。

该决定不撤销 Geospatial Kernel 的使命。被否证的是一个具体候选算子，不是“把地理规律内置于
世界模型”这一目标。相反，冻结失败明确提高了下一内核的结构要求。

## Structural Diagnosis

对只受上游 boundary action 驱动的串联线性一阶库，其拉普拉斯传递函数为：

\[
H(s)=\prod_i\frac{1}{1+K_i s}
\]

乘积对 reach 顺序可交换。因此，仅仅把 `K_i=L_i/v_i` 按有向路径排列，并不能保证边界响应对
路径反转敏感。逐 reach lateral forcing、非均匀初始状态会打破完全等价，但本次负控显示这种差异
不足以使 authoritative direction 获得经验支持。这不是 GIS 拓扑排序错误，而是动力学算子族本身
缺乏足够强的非交换方向结构。

persistence 的巨大优势说明目标 hydrograph 在小时尺度高度连续，而 v1 是无 observation update 的
open-loop rollout。GWM 下一版需要明确区分：

- `transition`：由 action、forcing、方向、几何和水力状态驱动；
- `observation update`：只使用当时已经可获得的历史 gauge observation 修正状态；
- `evaluation`：比较 causal online forecast，不能把当前或未来 outcome 写回 transition。

zero-action 失败还说明“candidate 主运行守恒”不足以证明算子在所有合法通量极限下数值稳健。零
action、零 forcing、低流和长退水必须成为 operator-level invariant tests，而不是只在评估脚本中
临时执行。

## Requirements for Kernel v2

下一 transport kernel 至少满足：

1. **非交换方向动力学**：反向拓扑必须改变状态转移，而不是只改变可交换线性库的排列；
2. **公开水力证据**：优先审计 NWM/WRF-Hydro route-link 中的坡度、断面、粗糙率、Muskingum
   参数和 channel geometry，不用无来源默认值制造物理感；
3. **守恒极限稳定**：zero action、zero forcing、低流、长退水和 partial reach 均通过独立数值门；
4. **causal observation update**：若使用历史 gauge assimilation，必须冻结在线可用时间边界，并与
   transition/action mechanism 分开报告；
5. **强基线**：必须超过 outcome persistence、direct release 和专业路由基线；
6. **机制消融**：action、forcing、方向、守恒任何一项失败都不能由 accuracy 补偿；
7. **新留出**：v2 只能在新的未查看 Center Hill chunk 或第二系统上确认，不能复用本次窗口。

## Consequences

### Positive

- 项目首次用先冻结、后取数、一次性评分的流程真正否证了一个 kernel 候选。
- DAM-GK 的使命从抽象愿景转化为可拒绝的算子合同和经验门。
- 下一步不再围绕固定 lag 或更复杂神经网络盲目调参，而是针对方向可辨识、状态更新和公共水力
  证据推进。

### Negative

- 当前没有可晋级的 GeoTransport kernel。
- Center Hill chunk `560` 已不能作为未来 hidden evaluation。
- v2 需要新的公共参数资产和新的留出获取成本。

## Claim Boundary

- `registered_single_system_temporal_holdout_passed=false`
- `empirical_support_for_candidate_operator=false`
- `flood_wave_transport_admitted=false`
- `hydrodynamically_validated=false`
- `benchmark_validated=false`
- `multi_system_generalization_validated=false`
- `geospatial_kernel_validated=false`

## Revisit Triggers

只有在 v2 具备公开可审计水力参数、通过 operator invariant suite、冻结新的 evaluation protocol，并
在新时间窗和至少一个第二系统上超过强基线及全部机制门后，才重新讨论 scientific promotion。
