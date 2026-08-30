# ADR-024: Geospatial Kernel Forecast Closure 边界

**Status**: Accepted; contract implemented; first public-development candidate failed persistence gate

**Date**: 2026-07-27

**Decision owners**: Geospatial World Model, Geospatial Kernel, GIS Compiler, Hydrologic Evaluation

**Related decisions**: [ADR-020](adr-020-geospatial-kernel-v2-nonlinear-manning-reach-storage.md),
[ADR-022](adr-022-geospatial-kernel-causal-state-and-spatial-support.md),
[ADR-023](adr-023-geospatial-kernel-branching-network-and-tributary-boundary.md)

## Context

双系统完整子网盲测显示，Center Hill 和 J. Percy Priest 的完整 branch DAG 都优于 branch-silent
对照，但固定 RouteLink Manning 参数、单一起点 modeled state 和 28 天 open-loop rollout 都没有超过
one-hour persistence。该结果保留 GIS 编译拓扑、typed field role、空间支持和守恒账本，同时否证当前
未校准的预测 closure。

下一实现必须同时满足：用户无需提供新数据；只使用项目主动获取的公开 development data；不能在已评分
窗口上调参；不能让学习器改变权威 feature ID、方向、DAG 或 action attachment；不能用自由 source/sink
残差凭空补水；任何历史观测都必须在 forecast issue time 已经有效且可获得。

## Options Considered

| 方案 | 优点 | 缺点 | 裁决 |
|---|---|---|---|
| 在已评分窗口重调固定 Manning n | 实现最简单，可能快速降低误差 | 直接污染盲测；仍是固定 open-loop closure | 拒绝 |
| 端到端神经网络同时学习拓扑、状态和流量 | 表达能力强 | 可绕过 GIS 方向与守恒；难以定位失败机制 | 拒绝 |
| 向每条 reach 添加自由 learned source/sink | 易拟合系统偏差 | 残差可造水或消水，破坏物理解释 | 拒绝 |
| 因果 analysis update + 受界状态依赖构成律 | 保留硬拓扑与守恒；学习范围明确；可逐项消融 | 表达能力受限；需要单独训练和新盲测 | 采用 |

## Decision

### 1. 三层边界保持不变

```text
GIS Compiler
  authoritative feature identity, direction, DAG, measure, support, evidence
                              ↓ immutable
Conservative Kernel
  state/flux roles, action injection, branch merge, non-negativity, mass ledger
                              ↓ constrained
Forecast Closure
  causal analysis update, state-dependent constitutive law, bounded residual
```

`ForecastClosure` 可以读取 `DirectedReachNetwork`，但不能返回 network。执行前后对 network 的规范 JSON
计算 SHA-256；fingerprint 改变即 fail closed。closure 输出仅包含 analysis state 和与原 feature axis 完全
一致的有效 hydraulic geometry。

### 2. 历史观测只形成显式 analysis increment

每个 issue time、每条 reach 最多传入一条 `CausalDischargeObservation`。必须满足：

- `valid_at <= issue_time`；
- `available_at <= issue_time`；
- age 不超过冻结阈值；
- quality/evidence 被冻结 policy 准入；
- observation role 固定为 `historical_state_update`。

discharge 通过原始 Manning geometry 反演为 observation-equivalent storage，再按冻结 gain 更新局部 state。
修正量逐 reach 记录为 `analysis_increment_m3`，其角色固定为
`external_analysis_increment_not_transition_flux`。它不伪装成 action、forcing 或 transition conservation。

### 3. 首个可学习 closure 是受界状态依赖粗糙度残差

对 reach `i`，以 analysis storage `S_i` 和冻结参考 storage `S_ref,i` 构造：

```text
r_i(S) = a_i + b_i * [log(1 + S_i / S_ref,i) - log(2)]
m_i(S) = exp(clip(r_i, log(m_min), log(m_max)))
n_eff,i = n_RouteLink,i * m_i(S)
```

`a_i`、`b_i` 可以由公开 development windows 估计；`m_min > 0`，且边界必须包含 identity `1`。
raw residual、applied residual、multiplier 和是否 clipped 都进入结果。该 residual 只修改 storage-discharge
构成律，不是外部水量：旧的 `BranchingManningNetworkTransportOperator` 仍把同一 outflow 从上游 storage
扣除并加入下游 storage，或从唯一 outlet 离开。

### 4. 参数时间和证据必须可审计

每个参数 artifact 必须记录 feature axis、reference storage、系数、训练系统、训练起止时间、provenance、
evidence level、是否 outcome calibrated 和 admission。`training_data_end >= issue_time` 时一律拒绝；candidate
参数不得 admitted，未准入参数只能在显式 diagnostic mode 执行。

真实参数只能由明确声明的 public development window 产生。synthetic invariants 只证明合同可执行，
public development 参数也只能用于诊断和下一设计选择，二者都不能代替 untouched validation。

### 5. 完整 forecast cycle 单独闭合质量账

组合执行器调用未修改的 branching solver，并检查：

```text
prior storage
+ explicit analysis increment
+ transition action/forcing inputs
= final storage + outlet volume + numeric residual
```

transition 自身的质量账仍从 analysis state 开始，二者不能混为一个 accuracy 或 conservation claim。

## Public Development Evidence

没有使用 D3 `2022-02-03/2022-03-03` 或双系统 `2022-03-31/2022-04-28` 的 outcome。项目主动补齐更早、
原本已声明为 development 的 Center Hill `2021-12-09T01Z/2022-01-06T01Z` 窗口：435-reach 完整子网、
NWM time chunk `559`、`streamflow × velocity` 初态和逐 reach `q_lateral`。所有初态与 forcing 无 fill，
输入报告 SHA-256 为
`8b6b42ba3cd07403d2c1a7b96d8a521717200758e1d369734aa0f6e21b9cb67c`。

为避免 435 个独立参数过拟合，首个 candidate 只有两个共享自由参数：所有 reach 共用 log-roughness
intercept 和 storage slope，每条 reach 的 reference storage 只由起点 modeled state 与 geometry 决定。
observation gain 固定为 `1`，没有 outcome grid search；USGS hourly interval-sample mean 使用冻结的 1 小时
publication lag，最多保留 2 小时，缺测不插值。实际 operational vintage availability 未被验证，因此
该观测策略仍是 derived development assumption。

前 168 个完整 target hours 拟合得到：

- intercept：`0.0253762411`；
- storage slope：`-0.1099906632`；
- multiplier bounds：`[0.5,2.0]`；
- activation issue time：`2021-12-16T02:00Z`，严格晚于 training end `2021-12-16T01:00Z`。

随后 503 个 development-diagnostic hours 的结果为：

| Scenario | RMSE (m3/s) | NSE | 解释 |
|---|---:|---:|---|
| candidate: update + residual | 46.588 | 0.8155 | 首个完整 closure candidate |
| state update only | 47.179 | 0.8108 | residual 带来 `0.591 m3/s` 小幅改善 |
| residual, no update | 81.959 | 0.4290 | 仅 residual 无法解决 open-loop drift |
| identity, no update | 82.827 | 0.4168 | 同 activation state 的 open-loop control |
| latency-matched persistence | 33.803 | 0.9030 | candidate 未超过 |
| one-hour persistence | 17.415 | 0.9742 | candidate 明显未超过 |

四个 Kernel 情景全部通过完整 forecast-cycle conservation，最大 residual/tolerance ratio 小于
`5.0e-4`。参数与 prediction SHA-256 分别为
`a0bebf3c2625d1ffab60528b9d4b8c78a4eacfaad1600fa2a2e6f35f88236d5d` 和
`4b1a88c0a9437deff5788adb6f4d3266b8a8f8b7bff98c20b56ad6bb96bcfff3`。

该证据保留 closure 架构，但关闭当前 candidate 的验证入口。主要改善来自 causal state update；共享
roughness residual 的独立贡献为正但很小。下一步应先改进低维、多站或图约束状态估计，并解决真实
observation vintage/latency 证据，再决定是否消耗新的多系统 blind window。

## Trade-offs

- 选择构成律残差而不是任意神经 source/sink，放弃一部分拟合自由度，换取守恒和机制可解释性；
- 首版只调整 Manning roughness，不宣称已经覆盖 backwater、分汊、潮汐、闸门或完整 Saint-Venant 动力学；
- 每个 issue time 的局部 observation-to-storage 更新简单、可审计，但不能替代多站联合状态估计；
- 严格训练时间和 feature-axis gate 会增加数据准备工作，但能防止 outcome leakage 和跨水系错轴。

## Consequences

### Positive

- DAM-GK/学习模型获得明确重新接入位置，而不再承担全部地理结构；
- closure 可以改善状态漂移和状态依赖响应，但不能改河流方向或凭空制造水量；
- identity 参数可复现旧 branching solver 的数值路径，便于建立无变化对照；
- analysis increment、constitutive residual 和 transition input 分账，失败原因可以分别审计。

### Negative

- 合同和 public development 通过不等于真实预测有效，仍需更强 development gate 和 untouched validation；
- 逐 reach 参数在数据少时容易过拟合，后续训练必须优先使用共享/分层参数而不是 435 个独立自由参数；
- 仅靠 outlet observation 更新 outlet reach 可能无法识别全网隐藏 state，需要多站或低维状态估计扩展。

## Revisit Triggers

- 公开 development evidence 表明 state-dependent roughness 仍不能超过 persistence 和专业基线；
- 有可靠公开观测支持多站图状态估计、wave celerity closure 或分层跨水系参数；
- backwater、分汊、反向流或控制结构使 dendritic single-downstream 假设失效；
- learned residual 需要作用于 edge flux 时，必须先定义逐边成对扣减/增加合同，禁止退回自由 source/sink。

## Claim Boundary

- `forecast_closure_contract_implemented=true`
- `forecast_closure_topology_mutation_forbidden=true`
- `forecast_closure_causal_observation_gate_implemented=true`
- `forecast_closure_analysis_increment_explicit=true`
- `forecast_closure_constitutive_residual_bounded=true`
- `forecast_closure_constitutive_residual_external_mass=false`
- `forecast_closure_cycle_conservation_implemented=true`
- `forecast_closure_synthetic_invariants_passed=true`
- `forecast_closure_public_parameters_trained=true`
- `forecast_closure_shared_free_parameter_count=2`
- `forecast_closure_development_candidate_beats_state_update_only=true`
- `forecast_closure_development_candidate_beats_latency_matched_persistence=false`
- `forecast_closure_development_candidate_beats_one_hour_persistence=false`
- `forecast_closure_development_gate_passed=false`
- `forecast_closure_real_observation_update_validated=false`
- `forecast_closure_predictive_improvement_validated=false`
- `geospatial_kernel_validated=false`
