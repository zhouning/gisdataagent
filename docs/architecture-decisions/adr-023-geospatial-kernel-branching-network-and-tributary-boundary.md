# ADR-023: Geospatial Kernel 分支网络与支流边界推进策略

**Status**: Structural decision retained; full-subnetwork milestone complete; uncalibrated Manning predictive instance rejected

**Date**: 2026-07-27

**Decision owners**: Geospatial World Model, Geospatial Kernel, GIS Compiler, Hydrologic Evaluation

**Related decisions**: [ADR-020](adr-020-geospatial-kernel-v2-nonlinear-manning-reach-storage.md),
[ADR-021](adr-021-geospatial-kernel-t-route-mc-professional-baseline.md),
[ADR-022](adr-022-geospatial-kernel-causal-state-and-spatial-support.md)

## Context

Center Hill D3 证明 26-reach 主干链不是完整的 dam-to-gauge 水量系统。USGS NLDI 的测站上游支流
导航在 25.17 km 线性参考有效区间内识别出 19 个直接 off-path tributary confluences；NLDI 完整
reach 导航包络为 28.38 km，这些 feature 全部存在于
NWM v3 feature axis。D3 只消费主干 `q_lateral`，其均值为 `2.008 m3/s`，没有消费这些支流已经路由到
汇入口的流量。

用户不再提供数据并不构成停止条件。NLDI、NHDPlus、NWM RouteLink、NWM retrospective、CWMS 和
NWIS 均是项目可主动获取的公开来源。真正约束是：当前尚未同时取得 19 条支流完整上游 DAG 的 topology、
RouteLink geometry、初始 state 和逐 reach forcing support。较大的 NLDI upstream-tributary 响应也不能
被一次有界请求可靠地编译为完整全子网。

## Options Considered

| 方案 | 优点 | 缺点 | 当前有效条件 |
|---|---|---|---|
| 继续 26-reach 主干链 | 最简单，D0-D3 数据齐全 | 已被 D3 结构性否证；漏掉 19 个支流口 | 只能作为失败基线 |
| 立即执行完整支流子网 | 最接近最终守恒系统；每条支流保持显式 state | topology、参数、初态和 forcing 尚不完整；不完整 DAG 会制造伪守恒 | 全部公开支持编译完成后 |
| 先使用支流口 NWM streamflow boundary | 19/19 feature crosswalk 完整；无需伪造 branch state；能立即验证网络账本 | 不是 ground truth；可能含 NWM nudging；不是端到端独立预测 | 作为开发过渡和机制诊断 |

## Decision

采用两阶段策略：

1. 科学终点保持为 `full_subnetwork_distributed_q_lateral_routing`；
2. 当前首个可执行修复采用 `modeled_tributary_boundary_flux`；
3. 每个边界必须绑定 NLDI confluence、tributary feature ID、receiving mainstem feature ID 和 NWM
   feature index；
4. 边界字段强制 `modeled=true`、`ground_truth=false`、`possible_nudging=true`；
5. 使用该边界时 `independent_end_to_end_prediction=false`，不得把它当 observation、conservation
   oracle 或模型验证证据；
6. Kernel 的守恒恒等式升级为：

```text
initial network storage
+ dam action
+ distributed q_lateral
+ admitted tributary boundary flux
- gauge outlet
= final network storage
```

7. D3 已是公开 falsification/development window。D4 可以在该窗做 outcome-free rollout 后的 post-hoc
   诊断，但不得调参、选择模型或注册通过 gate；
8. 新的预测主张必须在新的冻结 Center Hill 窗口和至少一个第二系统上检验。

实现上新增 `DirectedReachNetwork`、`TributaryConfluence`、
`ModeledTributaryBoundaryFlux` 和 `BranchingManningNetworkTransportOperator`。DAG 使用每个 reach
最多一个 downstream、任意多个 upstream 的有向无环合同；算子按拓扑序汇合 upstream discharge，保存逐
reach storage，并在每个时间步检查全网物理体积守恒。

## Evidence at Decision Time

- D4 topology report 找到 19 个直接支流口，19 个 receiving mainstem features，NWM membership
  `19/19`；需要 `streamflow` chunks `63`、`87`；
- 672 小时 boundary 数据 fill count 为 `0`，总支流口 modeled flow 均值 `63.906 m3/s`、中位数
  `17.265 m3/s`、最大值 `500.480 m3/s`；
- outcome-free D4 rollout 的 mainstem-only 轨迹复现 D3 central，最大绝对差
  `3.98e-13 m3/s`；mainstem 与 boundary 轨迹均通过全网守恒；
- 封存后 post-hoc 诊断中，D4 RMSE 为 `70.545 m3/s`，D3 central 为 `162.753 m3/s`，persistence
  为 `15.058 m3/s`；D4 bias 为 `-21.013 m3/s`；
- 该结果说明漏支流是主要结构问题，但 D4 仍未超过 persistence，且边界来自可能 nudged 的 modeled
  streamflow，因此不构成 validation。

## Trade-offs Accepted

- 接受首阶段不是端到端独立预测，以换取不伪造不完整支流 state 和 forcing；
- 接受 NWM 边界可能继承其同化与路由误差，因此所有报告显式保留 `possible_nudging=true`；
- 接受暂时仍是主干 storage 网络加外部汇入口，而不是完整 branch storage DAG；
- 不接受用 D3 outcome residual 反算额外通量、缩放支流流量或选择 confluence。

## Consequences

### Positive

- D3 的遗漏被落实为 19 条可审计的地理连接，而不是一个自由学习 bias；
- 同一个算子可执行 Y 型/树型真实 DAG，也可在数据未齐时执行显式外部 confluence boundary；
- action、mainstem forcing、tributary boundary、storage 和 outlet 进入同一守恒账；
- D4 改善与 D3 算子变化可以分离，因为 mainstem-only reproduction 已通过。

### Negative

- D4 不能证明 GWM 已学会支流内部传播；
- NWM tributary streamflow 可能携带 nudging，不能与 USGS outcome 等价；
- 仍需主动获取完整 RouteLink/NHDPlus 子网、支流初态和 q_lateral 才能达到科学终点；
- 新冻结评估前，任何 D4 指标都只能是 development diagnostic。

### Mitigation

- 保留逐 tributary 原始 chunk、feature index、汇入口坐标、接收 reach 和 SHA-256；
- 增加 branch removal、wrong-confluence、boundary-zero 和 reversed-edge negative controls；
- 完整子网采用 branch state 和 distributed q_lateral 后，删除对应 mouth boundary，避免双计；
- 未来冻结协议将 modeled-boundary 与 full-subnetwork 作为不同模型族，不允许结果后改选。

## Revisit Triggers

- 完整 branch DAG、RouteLink geometry、initial state 和 q_lateral 支持编译完成；
- NWM 提供更明确的 retrospective assimilation/nudging provenance；
- 新冻结窗口中 mouth-boundary 仍不能超过 persistence；
- 第二系统显示支流口模式存在系统性双计或时序偏差；
- backwater、分汊、反向流或控制结构使 dendritic one-downstream 合同失效。

## Claim Boundary

- `center_hill_direct_off_path_tributary_count=19`
- `center_hill_d4_nwm_boundary_membership=19/19`
- `branching_network_contract_implemented=true`
- `network_conservation_invariant_passed=true`
- `modeled_tributary_boundary_ground_truth=false`
- `modeled_tributary_boundary_possible_nudging=true`
- `independent_end_to_end_prediction=false`
- `full_subnetwork_routing_ready=false`
- `d4_predictive_improvement_validated=false`
- `geospatial_kernel_validated=false`

## 2026-07-27 Revisit: D5 And Two-System Blind Test

The first revisit trigger has now fired. The official NWM v3 RouteLink member
was recovered and verified (`SHA-256=e34e58c875e25b93e6692a286ef7004ff59e86ee48435c5a5e0dfa95d2ccb5f4`).
Center Hill D5 compiles 435 reaches: 26 active mainstem reaches and 409 branch
reaches, including all 19 former tributary mouths and their upstream ancestors.
The mouth-boundary approximation is therefore retired from the primary model;
each branch now has explicit state, RouteLink parameters, distributed
`q_lateral`, and a place in the network conservation ledger.

J. Percy Priest independently compiles 43 reaches: 5 active mainstem reaches
and 38 branch reaches. The control COMID `18401827` is excluded from the state
domain, action enters complete downstream reach `18401881`, and terminal COMID
`18401497` is cut at USGS `03430200`. Both subnetworks have complete NWM v3
feature membership. The truncated 1.8 GiB source archive used to recover the
RouteLink member was deleted after both topology subsets were compiled; the
verified member and hashed repository subsets remain.

The D5 post-hoc D3 diagnostic did not select the blind configuration. Its
full-subnetwork RMSE was `73.251 m3/s`, versus `70.545 m3/s` for D4 and
`15.058 m3/s` for persistence. It nevertheless showed that internal branch
routing removed most of the branch-silent error while avoiding a possibly
nudged tributary streamflow boundary.

A later 672-hour window, `2022-03-31T01:00Z` through
`2022-04-28T01:00Z`, was frozen for Center Hill and J. Percy Priest before
window input access. Both predictions were sealed before either USGS outcome
request. The joint seal is
`98fc3257ffe53c24245db80c36d1a376b9d332ceb0e82300c2ea5a1dbb94526c`.
All actual, branch-silent, and zero-input conservation gates passed.

The predictive gate failed on both systems:

| System | Scored hours | Kernel RMSE | Persistence RMSE | Kernel NSE | Bias |
|---|---:|---:|---:|---:|---:|
| Center Hill | 670 | 82.675 | 16.206 | 0.0419 | -25.116 |
| J. Percy Priest | 668 | 26.543 | 20.903 | 0.8142 | -4.267 |

The full network beats branch-silent on both systems, so branch topology and
distributed branch flux have measurable value. It still loses to one-hour
persistence on both systems. This falsifies the current open-loop,
uncalibrated Manning storage closure as a predictive default. It does not
invalidate the typed topology, linear reference, spatial support, evidence,
or conservation operators.

The protocol also failed strict confirmation conformance because native USGS
sampling cadence was not fully predeclared: Center Hill is 30-minute and J.
Percy Priest is 15-minute. Both were reduced post-seal using the same rule,
the mean of every complete native sample in `(t-1h,t]`, with incomplete hours
left missing. No prediction, metric, baseline, or gate changed, but the result
is a qualified prospective replication rather than a fully conformant
confirmatory validation.

The next decision is therefore not to tune D5 on this window. Keep the GIS
compiler and conservative branching operator as the kernel skeleton; move
forecast skill into a separately typed closure layer trained only on declared
development windows. That layer may include causal observation-state updates,
state-dependent wave-celerity/storage closure, and a constrained residual,
but may not revise authoritative topology or break the mass ledger. A future
test requires a new untouched window, exact native-sampling aggregation in the
protocol, and at least two systems, preferably adding Wolf Creek.

Updated claim boundary:

- `full_subnetwork_routing_ready=true`
- `full_subnetwork_routing_executed_two_systems=true`
- `branch_structure_has_positive_ablation_value=true`
- `uncalibrated_manning_predictive_instance_admitted=false`
- `two_system_predictive_gate_passed=false`
- `strict_confirmatory_validation_passed=false`
- `geospatial_kernel_validated=false`
