# ADR-022：Geospatial Kernel 因果状态更新、空间支持与公开数据推进边界

**Status**: Accepted; D0-D2 passed; D3 failed; D4 branching remediation implemented as development diagnostic

**Date**: 2026-07-27

**Decision owners**: Geospatial World Model, Geospatial Kernel, GIS Compiler, Hydrologic Evaluation

**Related decisions**: [ADR-019](adr-019-geospatial-kernel-reach-transport-v1-holdout-adjudication.md),
[ADR-020](adr-020-geospatial-kernel-v2-nonlinear-manning-reach-storage.md),
[ADR-021](adr-021-geospatial-kernel-t-route-mc-professional-baseline.md),
[ADR-023](adr-023-geospatial-kernel-branching-network-and-tributary-boundary.md)

## Context

DAM-GK 的现有参数化没有在当前冻结证据上证明通用优势，但这不等于“把地理规律内置进世界模型”
这一使命失败。真正需要撤回的是把一个神经网络结构等同于全部 Geospatial Kernel、或在数据不足时用
默认参数和合成值提前宣称真实效果的做法。

用户不能再提供私有数据，但公开数据仍可由项目主动获取。公开可得性只解决来源问题，不自动解决
版本匹配、feature axis、预测起点状态、时间可用性、partial reach 空间支持和 evaluation 隔离。

Kernel v2 已有 nonlinear Manning reach-storage 和固定 t-route MC 基线，但还缺两个运行时合同：

1. 如何使用预测时刻已经可用的历史观测修正 state，而不把 outcome 泄漏进 transition；
2. 如何处理只覆盖部分 reach 的路径，使 full-reach forcing 不被静默按长度比例缩放。

## Decision

### 1. 保留 DAM-GK 使命，重定义内核本体

Geospatial Kernel 定义为一套 typed、evidence-gated、可递归的地理算子代数，不等同于任一模型类。
DAM-GK 保留为 learnable operator、residual operator 或 relation/lag candidate；它必须消费与物理算子
相同的状态、拓扑、度量、空间支持和证据合同，并在新冻结评估上通过强基线与消融后才能晋级。

地理规律通过三类机制进入内核：

- GIS 编译的硬结构：方向、邻接、包含、线性参考、CRS、面积、长度和空间支持；
- 不可违反的演化约束：守恒、非负、合法边界通量、因果时间和角色隔离；
- 可从数据估计的残差：状态依赖阻力、关系强度、传播时滞和模型误差。

### 2. transition、observation update、evaluation 三分

三类算子使用不同接口并禁止隐式转换：

- `transition` 消费 prior state、action、forcing 和 admitted geography，产生下一状态与通量账；
- `observation update` 消费 analysis time 之前已经发布的历史观测，产生 analysis state；
- `evaluation` 消费冻结 prediction 与 outcome，只产生指标和科学裁决。

discharge observation 必须分别记录 `valid_at` 和 `available_at`。以下情况 fail closed：

- `valid_at > analysis_time`；
- `available_at > analysis_time`；
- 观测年龄超过冻结阈值；
- quality status 或 evidence level 未准入；
- observation role 不是 `historical_state_update`。

Manning discharge-to-storage 反演只修正观测所在 reach。修正量写入
`analysis_increment_m3`，其质量角色固定为
`external_analysis_increment_not_transition_flux`。analysis increment 不能进入物理 transition 的 action、
forcing 或 conservation flux，也不能用来宣称 transition 自身更准确或更守恒。

### 3. partial-reach forcing 必须有逐 feature 空间支持

`ReachForcingSupport` 绑定：

- 与 active path 完全一致的 feature axis；
- 每个 feature 的 `coverage_fractions`；
- support method、provenance、evidence level 和 admission；
- full reach 的 coverage 必须为 `1`；
- partial reach 上出现非零 full-reach forcing 时，support 缺失或未准入即 fail closed。

Kernel 分别记录：

- `raw_forcing_volume_m3`；
- `applied_forcing_volume_m3`；
- `excluded_forcing_volume_m3`。

只有 applied forcing 进入 transition 守恒账。`effective_length / full_length` 是河段线性比例，不是汇水区
产流或 lateral inflow 的空间覆盖比例，禁止自动猜测。非零 forcing 仅位于完整 reaches 时，不应因路径
中另有一个 forcing 为零的 partial reach 而被误阻断。

### 4. 传统 GIS 是 Kernel compiler，不是被替代的外围工具

传统 GIS 算子与 Kernel 算子都依赖空间对象、拓扑、方向和度量。区别在于：GIS 算子通常对当前图层做
一次确定性变换；Kernel 算子推进显式 state，区分动态字段角色，携带时间可用性和证据 admission，并
在递归执行中维护守恒与不确定性。

因此：

- CRS 转换、线性参考、网络追踪、相交、汇水区切分、栅格重采样继续由成熟 GIS 实现；
- GIS 输出必须带 feature axis、容差、方法、来源和哈希，编译成 Kernel 的 `B/H/M/E` 与 support；
- Kernel 不重新手写 buffer/overlay，也不允许学习模型绕过 GIS 编译的硬结构；
- Kernel 负责 state transition、analysis update、通量账、递归 rollout 和 fail-closed execution。

### 5. 无用户新增数据时主动获取公开数据，但逐门晋级

公开数据获取是默认工程责任。每个系统按以下顺序晋级：

1. **D0 geometry/parameter gate**：官方来源、版本、feature axis、字段、单位和哈希完整；
2. **D1 initial-state gate**：预测起点之前可用的 Q/V/D、storage 或可审计反演状态；
3. **D2 action/forcing gate**：时间支持、空间支持、角色和 raw/applied/excluded ledger 完整；
4. **D3 evaluation gate**：读取 outcome 前冻结新窗口、代码、阈值、基线和数据请求；
5. **D4 claim gate**：优于 persistence、专业模型、zero-action、no-forcing、reversed topology 等强基线。

D0 通过不自动打开 D1-D4。没有真实 initial state 或 partial forcing support 时，只能运行 outcome-free
invariant 和 diagnostic。D0-D2 全部通过后可以开放严格限定的 retrospective transition input
execution，但不能由此打开 operational-online、evaluation 或 benchmark 主张。

## Invariant Evidence

新增 causal/support invariant 使用官方 Hurricane Laura RouteLink geometry 与合成 observation/forcing
probe，不读取真实 outcome、observed action、observed forcing、Center Hill chunk `560` 或 chunk `561`。
已通过：

- future、unavailable、stale 和 provisional-quality fail-closed；
- Manning Q-to-storage 反演；
- analysis increment 独立记账；
- partial forcing 缺 support 与 candidate support fail-closed；
- raw/applied/excluded ledger 闭合；
- projected forcing transition conservation。

这些结果只支持 operator contract invariant，不支持真实 observation update、真实 forcing support、
hydrodynamic validity、benchmark accuracy 或通用 Geospatial Kernel validation。

## Public Data Evidence

NOAA OWP 官方 NWM v3.0 参数分发 README 明确说明 `RouteLink_DOMAIN.nc` 包含河道定义、参数和 USGS
gauge reach 定义，并被 NWM 所有配置使用。获取流程固定：

- README：`https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/README.v3.0.txt`；
- 参数包：`https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/NWM_parameter_files_v3.0.tar.gz`；
- archive content length：`4,678,832,855 bytes`；
- ETag：`"116e152d7-605cc9d2317f0"`；
- Last-Modified：`Wed, 20 Sep 2023 16:10:28 GMT`。

完整 archive、RouteLink member、Center Hill subset 的 SHA-256、字段和 feature coverage 必须由 acquisition
manifest 记录。官方 NWM v3 参数来源与 retrospective 输出版本相符仍不足以证明两个独立分发对象
byte-identical，因此 `retrospective_parameter_identity_verified` 默认保持 false，除非出现额外权威证据。

获取和审计已经完成：

- archive SHA-256：`1d8a7e1eb506ec38a2ff0de64b1b5ebc7472205e0d660ee28080a9e15b6ce38c`；
- member：`v3.0_par/RouteLink_CONUS.nc`，`269,363,375 bytes`；
- member SHA-256：`e34e58c875e25b93e6692a286ef7004ff59e86ee48435c5a5e0dfa95d2ccb5f4`；
- source container：NetCDF4/HDF5，feature count `2,776,734`；
- Center Hill requested coverage：`27/27`；active coverage：`26/26`；
- active `to` topology：逐段连续；10 个必需参数字段全部存在；
- Center Hill subset：`8,588 bytes`，SHA-256
  `ce0e34c12cf6ce4c6c46088ae3311944f71e977ba220d2ec152e17c2ed612502`；
- 完整 4.68 GB archive 在上述身份、成员和子集清单落盘后已删除，不进入仓库。

因此 D0 geometry/parameter gate 已通过，旧的 `center_hill_parameter_coverage=0/26` 已被新证据取代。

D1 initial-state gate 也已通过 retrospective 限定。预测窗前一小时从 NWM v3 retrospective
`streamflow/560.63` 获取 `2022-02-03T00:00:00Z` 的 27/27 feature state；排除有效长度为 0 的
水体/action feature 后得到 26 个 active reaches。原始对象为 `16,161,378 bytes`，SHA-256 为
`588759a8445fc4880a4f77ad2817a59673eb8ff4616718442911460853ba70ed`。状态角色固定为
`modeled_initial_state`、`ground_truth=false`；chunk `561` 和 evaluation outcome 均未读取。因此
`retrospective_modeled_initial_state_available=true`，但
`operational_online_initial_state_available=false`。

D2 terminal partial-reach forcing support 通过，但保留 30 m 量化 bracket。EPA 官方 NHDPlus V2.1
`05a FdrFac` archive 为 `100,777,847 bytes`，SHA-256 为
`f134e77d7d910c32839313063001f7584e524b39afd7eecd85b451a054026d02`。USGS 03424860 的
NLDI measure `16.7207` 投影到 EPSG:5070 后，原点落在 `FAC=120` 的邻接像元；按冻结规则选择
与 `TotDASqKM=6456.858` 相容且距离最近的主槽像元 `(row=11747,col=10831)`，其 FAC 为
`7,109,846`、等效 drainage area 为 `6398.8623 km2`，距 measure 点 `19.639 m`。

沿官方 FDR 链的九个连续主槽像元，split-catchment intersection coverage 从 `0.824203` 单调增加到
`0.984105`；选择像元的重复请求与中心线最近点请求字节完全相同。最终 central coverage 为
`0.842973815499`，上游/下游相邻像元 bracket 为
`[0.827204578700, 0.936645191100]`。未 snap 的 official measure 和原始 USGS 坐标分别只返回
`0.089333` 和 `0.001502`，作为负对照拒绝。编译后的 26-feature `ReachForcingSupport` 对 25 个
full reaches 使用 `1`，terminal reach 使用 central coverage，并强制保留 bracket 与
`subcatchment_q_lateral_values_observed=false`。

由此 D0-D2 已通过，`center_hill_retrospective_transition_input_execution_admitted=true`。这只允许
使用公开 retrospective modeled state/action/forcing 的输入执行；它不自动授予 operational-online
或 benchmark 身份。

## D3 Falsification Result

D3 在读取新窗口值之前冻结于 `2026-07-27T03:26:28Z`。冻结协议 SHA-256 为
`d3675aaadd1274949748da754bc843f11aa7e31bed8e7c4cf74c28fe1e689f8c`，固定：

- `2022-02-03T01Z` 至 `2022-03-03T01Z` 的 672 小时窗口，无 warm-up；
- D1 initial state、D2 central/lower/upper support、NWM v3 RouteLink 与固定提交 t-route；
- nonlinear central、support bracket、zero-action、no-forcing、state-only、reversed-topology、
  t-route、direct-release 和 persistence；
- RMSE 主指标、至少 600 个完整小时和全部因果/守恒 gate。

冻结后才读取 NWM `q_lateral/561.63`。原始对象为 `5,571,472 bytes`，SHA-256 为
`b6873367dd8b30f6acbea07240b5eac442d2e9c67637e8304e05157563d38777`；归一化后的 26-feature、
672-hour forcing 无 fill。outcome-free prediction artifact SHA-256 为
`0a309b2c37b3ca4e503dfea0e2e96832bbe6d06b54f913728cdb2d5da784f074`。七个 nonlinear 情景全部
通过 physical-volume conservation，最大单步 residual/tolerance ratio 为 `6.16e-4`。

预测封存后才读取 USGS 03424860 outcome。USGS 当前官方服务重定向到
`nwis.waterservices.usgs.gov`；新响应缺少 persistence prior 所需的 `00:30Z` 样本，因此只从此前已
哈希封存的同站、同参数、approved `A` 官方响应补入该前置样本，并按 UTC timestamp 去重。没有
插值或 outcome imputation。最终 672/672 小时可评分，结果为：

| 场景 | RMSE (m3/s) | NSE | 结论 |
|---|---:|---:|---|
| persistence | 15.058 | 0.9920 | 强基线 |
| nonlinear central | 162.753 | 0.0696 | 未超过 persistence |
| t-route MC | 167.864 | 0.0103 | central 超过专业基线 |
| no forcing | 166.504 | 0.0262 | forcing ablation 按预期退化 |
| zero action | 334.228 | -2.9236 | action ablation 按预期退化 |
| state only | 336.808 | -2.9845 | 按预期退化 |
| reversed topology | 162.616 | 0.0712 | 未按预期退化，反而略优 |

因此 D3 overall fail。通过的 gate 是 t-route、state-only、zero-action、no-forcing 和全部 nonlinear
守恒；失败 gate 是 persistence 与 reversed topology。30 m upper bracket 的 RMSE 为 `162.737`，虽
略低于 central，也不能在 outcome 打开后改选。评分报告 SHA-256 由当前 artifact 单独记录；
`runtime_adapters` 只规范 `Z`/`+00:00` 等价 UTC 表示并忽略 JSON mapping 顺序，不改变任何数值、
指标或阈值。

失败后的结构诊断显示：observed mean 为 `292.132 m3/s`，CWMS action mean 为 `212.106 m3/s`，
26 个主槽 active reaches 的 NWM q_lateral sum mean 只有 `2.008 m3/s`，central prediction mean 为
`207.263 m3/s`，bias 为 `-84.869 m3/s`。这不能证明缺口全部来自某一条支流，但可以证明当前
linear-referenced mainstem chain 只纳入主槽 reaches 的 q_lateral，按构造遗漏了在 dam-to-gauge
区间汇入主槽的 off-path tributary routed flux。D3 不否证 Kernel 使命；它否证“单一路径就是完整
地理水量系统”的实现假设。

下一轮不得在 D3 同窗调参恢复 hidden-evaluation 身份。必须先由 GIS/NHDPlus/NWM topology 编译
branching DAG、confluence attachment 与 tributary support，再由 Kernel 维护 branch state、汇合通量和
全网守恒账。D3 只可作为公开 development/falsification window；修复后的模型必须使用新窗口和至少
一个第二系统重新冻结。

## D4 Branching Remediation Checkpoint

NLDI 从 USGS 03424860 向上游 30 km 的支流导航覆盖 28.38 km 完整-reach 包络；线性参考后的
action-to-gauge 有效长度为 25.17 km。按
“tributary downstream endpoint 等于 receiving mainstem upstream endpoint”的固定规则，识别出 19 个
直接 off-path tributary confluences，分别进入 19 个主干 features。19/19 tributary IDs 都存在于 NWM
v3 feature axis，涉及 `streamflow` chunks `561.63` 和 `561.87`。

当前没有把不完整的 upstream 响应冒充完整子网。首个可执行模式按照 ADR-023 固定为
`modeled_tributary_boundary_flux`，并强制：

- `modeled=true`；
- `ground_truth=false`；
- `possible_nudging=true`；
- `independent_end_to_end_prediction=false`；
- 不得作为 observation 或 conservation oracle。

672 小时、19 支流口 NWM streamflow 无 fill，合计均值为 `63.906 m3/s`。新增
`BranchingManningNetworkTransportOperator` 在 outcome-free rollout 中以 `3.98e-13 m3/s` 最大绝对差
复现 D3 mainstem central，并在加入支流边界后继续通过全网守恒。封存预测后进行的 post-hoc D3 公共窗
诊断得到：D4 RMSE `70.545 m3/s`、bias `-21.013 m3/s`，相比 D3 central 的 `162.753 m3/s` 和
`-84.869 m3/s` 明显收窄，但仍远差于 persistence 的 `15.058 m3/s`。

这支持“漏支流是主要结构缺口”，但不开放 D4 validation。科学终点仍是完整 branch DAG、branch state
和 distributed q_lateral；D4 窗口不得用于调参或模型选择，新预测主张仍需新冻结窗口与第二系统。

## Consequences

### Positive

- GWM 的地理内核使命不再依赖单一 DAM-GK 参数化是否一次实验成功；
- 物理、GIS、规则和学习算子获得共同的状态与证据边界；
- 历史观测可以因果地更新 state，而不污染 transition conservation；
- partial forcing 不会因长度比例假设而静默进入模型；
- 用户不提供新数据不再是工程停滞理由，公开数据获取成为可复现 pipeline。

### Negative

- 更多 fail-closed gate 会使真实 rollout 比传统 GIS 脚本或宽松 ML pipeline 更晚可运行；
- observation update 需要冻结 gain、age 和 quality policy，不能通过 evaluation outcome 调参；
- NHDPlus 30 m FDR/FAC 会产生不可忽略的相邻像元量化 bracket，单一 central fraction 不能冒充零误差；
- D3 已按冻结协议失败；不能用同窗调参、改选 support bracket 或取消失败 gate 恢复 benchmark claim。

## Revisit Triggers

- 获取逐 subreach/catchment 的权威 forcing allocation；
- NWM/USGS/USACE 提供可按 online availability 审计的初始状态；
- DAM-GK residual 在两个以上系统的新冻结窗口上稳定超过专业和 persistence 基线；
- backwater、分汊、潮汐、控制结构或反向流成为目标机制；
- 新数据证明 RouteLink 参数与 retrospective domain 的更强身份关系。

## Claim Boundary

- `dam_gk_mission_retained=true`
- `dam_gk_current_parameterization_universally_validated=false`
- `causal_observation_update_implemented=true`
- `partial_forcing_support_implemented=true`
- `causal_support_invariants_passed=true`
- `center_hill_route_link_parameter_coverage=26/26`
- `center_hill_geometry_parameter_gate_passed=true`
- `real_observation_update_validated=false`
- `center_hill_retrospective_modeled_initial_state_available=true`
- `center_hill_operational_online_initial_state_available=false`
- `center_hill_terminal_forcing_spatial_support_validated=true`
- `center_hill_terminal_forcing_central_coverage=0.842973815499`
- `center_hill_terminal_forcing_30m_bracket=[0.827204578700,0.936645191100]`
- `center_hill_subcatchment_q_lateral_values_observed=false`
- `center_hill_d2_action_forcing_gate_passed=true`
- `center_hill_retrospective_transition_input_execution_admitted=true`
- `center_hill_operational_online_execution_admitted=false`
- `center_hill_new_evaluation_protocol_frozen=false`
- `center_hill_d3_chunk_561_loaded=true_after_freeze`
- `center_hill_d3_overall_passed=false`
- `center_hill_direct_off_path_tributary_count=19`
- `branching_network_contract_implemented=true`
- `modeled_tributary_boundary_ground_truth=false`
- `modeled_tributary_boundary_possible_nudging=true`
- `full_subnetwork_routing_ready=false`
- `center_hill_d4_predictive_improvement_validated=false`
- `benchmark_validated=false`
- `geospatial_kernel_validated=false`
