# ADR-018：Geospatial Kernel 状态相关河段传播候选算子

**Status**: Accepted for diagnostic use; scientific admission pending

**Date**: 2026-07-26

**Decision owners**: Geospatial World Model, Geospatial Kernel, Hydrologic Evaluation

**Related research**: [GWM 公开水文数据基础与 Kernel 2.0 检查点](../research/GWM_PUBLIC_HYDRO_DATA_FOUNDATION_AND_KERNEL_V2_CHECKPOINT_2026-07-26.md)

**Post-acceptance adjudication**: [ADR-019](adr-019-geospatial-kernel-reach-transport-v1-holdout-adjudication.md)
拒绝 v1 scientific promotion，但保留本 ADR 的 diagnostic-use 决定。

## Context

DAM-GK v0.2 的 action transport 将 action change 经过幅度门控后乘一个拟合系数。它没有逐 reach
存量、方向传播、时间支撑或质量守恒，因此不能承担 Geospatial Kernel 的地理规律内核。Kernel 2.0
已经具备线性参考路径、typed action/forcing、时间支撑和 conservative flux projection，但尚未有
从路径与 hydraulic state 生成传播响应的算子。

当前可用公共条件是：Center Hill action-to-gauge 有向路径、逐 reach 有效长度、小时 action、
NWM `q_lateral` 和 NWM river velocity。当前没有经过准入的 flood-wave celerity，也没有逐 reach
断面、坡度、Manning roughness、stage 或 Muskingum-Cunge 参数。用户不提供私有数据，但可以继续
有界获取公共数据。实现必须保持 SI 单位、方向、状态、证据和 claim boundary，且不能用 outcome
后验选择时间标签。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 固定整数 lag 或插值 delay | 最简单，容易拟合 | 不含 reach 状态；速度变化时不更新；易复现 DAM-GK 的后验 lag 问题 | 拒绝 |
| B. 直接实现 Muskingum-Cunge/kinematic wave | 更接近洪水波物理 | 当前缺断面、坡度、糙率和已验证 celerity；补默认值会制造虚假物理 | 延后 |
| C. 神经时空传播核 | 表达力强 | 当前只有 24 小时 smoke；不可辨识且容易由 outcome 绕过地理合同 | 拒绝为首个内核 |
| D. 有向 first-order reach-storage cascade | 使用路径顺序、有效长度和逐时 speed；保存存量并严格守恒；接口可替换 | 是弥散响应近似，不是完整洪水波方程；river velocity 仍只是 proxy | 选择为候选诊断算子 |

## Decision

新增 `StateDependentReachTransportOperator`，按线性参考路径的 active reaches 构造有向控制体级联。
每个时步显式输入 `ReachHydraulicState`，每条 reach 的候选驻留时间为：

\[
K_i(t)=\frac{L_i^{effective}}{c_i(t)}
\]

控制体满足：

\[
\dot S_i=u_i+\frac{S_{i-1}}{K_{i-1}}-\frac{S_i}{K_i}
\]

其中首 reach 没有上游内部项，`u_i` 分离为上游 action boundary 与逐 reach forcing。算子使用
SciPy `expm` 对常输入时步做精确矩阵指数推进，同时积分每条 reach 的累计出流。它不使用显式
Euler 或人为 CFL substep，避免短 NHD reaches 导致不稳定或每小时最多跨一条 reach 的数值假象。

`ReachHydraulicState.quantity` 只能是 `river_velocity_proxy` 或 `flood_wave_celerity`。只有后者且证据
不是 `candidate` 时才能设置 `admitted_as_flood_wave_celerity=true`。整体 admission 采用三重门：
`path_admitted AND hydraulics_admitted AND operator_form_admitted`。任何一项未通过时，默认算子拒绝
执行；显式开启 `allow_unadmitted_components_for_diagnostics` 后可以运行 smoke，但结果强制为
`diagnostic_only=true` 和 `flood_wave_transport_admitted=false`。

线性参考后有效长度为零的 reach 不建立存量控制体，并在结果中列为
`excluded_zero_length_feature_ids`。action 只能进入第一条 active reach。v1 只接收非负 action 和
forcing；withdrawal、反向流、capacity/stage 约束不在此算子中静默近似。

## Rationale

1. 这是当前数据条件下能同时表达方向、有效距离、状态变化、存量和守恒的最小实现。
2. 精确矩阵指数是成熟数值原语，避免为 1.5 m 到 3.9 km 的不均匀 reach 手写时间积分器。
3. hydraulic quantity 与 admission 分离，允许利用公共 NWM velocity 做诊断，同时阻止其成为真实
   flood-wave lag。
4. 算子输出逐 reach 存量和累计出流，可被 action ablation、forcing ablation、方向和守恒 gate
   独立检查；旧 DAM-GK 的单系数 residual 不具备这些可观测状态。

## Trade-offs Accepted

- first-order cascade 的响应是 hypoexponential/弥散的，不保证洪水波的有限传播前沿。
- `K=L/c` 在 proxy 模式下只代表候选 residence scale，不等于 WRF-Hydro 的已验证 Muskingum `K`。
- v1 没有 channel capacity、stage-discharge、backwater、分汊、汇流或 dynamic wave。
- Center Hill 672 小时 rollout 仍从零存量开始，但前 168 小时已冻结为 warm-up；warm-up 输出和
  后续 504 小时 development 输出都未评分。
- 末条 partial gauge reach 的 full-reach `q_lateral` support 仍未解决。

## Consequences

### Positive

- Geospatial Kernel 首次拥有由真实有向路径和逐时状态驱动的递归传播状态，而不是静态 GIS trace
  或事后 lag。
- action、forcing、hydraulics 和 outcome 继续保持类型隔离。
- 单步与全时窗质量守恒可以 fail-closed 验证。
- 后续可以在相同接口下替换为 Muskingum-Cunge、kinematic wave 或校准 response kernel。

### Negative

- 该候选核不能单独证明 flood-wave 机制。
- 7 天 warm-up 只是固定的初始状态处理，不等于已经证明冷启动影响充分消退；该命题仍需敏感性
  分析，且不能用 evaluation outcome 反向选择 warm-up 长度。
- 若用 outcome 校准 celerity scaling 或 dispersion，必须只在冻结训练窗内完成并在留出窗固定。

### Mitigation

- 所有 proxy 运行保留 `diagnostic_only` 与未准入 claims。
- 已扩展与 NWM chunk 对齐的 672 小时公开 companion window，固定前 168 小时 warm-up；其余
  504 小时仍只登记为 development，不得事后切分成 evaluation。
- 专业基线、action/forcing ablation、反向拓扑与守恒 gate 缺一不可。
- 获得 channel geometry 后，将本算子与 Muskingum-Cunge/kinematic-wave 基线并列评估，不以复杂度
  本身作为升级依据。

## Revisit Triggers

出现以下任一情况时重新评审：

- 获得可信逐 reach slope、cross-section、roughness、stage-discharge 或官方 routing 参数。
- 冻结留出实验显示线性级联系统性错过峰值到达、峰宽或退水过程。
- backwater、分汊、潮汐、反向流或控制结构成为目标系统的主要机制。
- 数值规模使 dense matrix exponential 成为稳定瓶颈，需要稀疏 Krylov 或专用路由引擎。
- flood-wave celerity 获得独立证据并满足 admission gate。

## Implementation Evidence

Center Hill 已完成连续 672 步公开输入 rollout。初始河段存量为零，前 168 小时只更新状态，
warm-up 末的 `14,559,668.655 m3` 河段存量不重置地进入后 504 小时 development 段。全窗累计
输入为 `373,061,318.337 m3`，累计 outlet 为 `351,889,061.596 m3`，最终河段存量为
`21,172,256.741 m3`，浮点质量残差为 `2.30e-5 m3`。门限使用算子原有的“绝对基准加当前存量
尺度机器精度”数值容差，并逐步累计，不使用经验放宽系数。

rollout CSV 不包含 outcome 字段；USGS 原始缺测影响的 3 个小时只在上游 development panel 中保留，
没有插补，也没有进入状态转移、参数选择或评分。因此该证据只将实现从 24 小时代码 smoke 推进为
长窗状态递推 diagnostic，不改变本 ADR 的 scientific admission 状态。
