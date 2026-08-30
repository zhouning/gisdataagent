# ADR-020：Geospatial Kernel v2 非线性 Manning reach-storage 研究算子

**Status**: Accepted for implementation and invariant testing; Center Hill execution blocked

**Date**: 2026-07-26

**Decision owners**: Geospatial World Model, Geospatial Kernel, Hydrologic Evaluation

**Related decisions**: [ADR-018](adr-018-geospatial-kernel-state-dependent-reach-transport.md),
[ADR-019](adr-019-geospatial-kernel-reach-transport-v1-holdout-adjudication.md),
[ADR-021](adr-021-geospatial-kernel-t-route-mc-professional-baseline.md)

## Context

冻结 holdout 已否证 v1 的科学晋级。失败包含两个彼此独立的问题：

1. first-order cascade 没有超过 persistence，且 reversed active path 没有退化；
2. zero-action development 重放在第 131 小时触发质量守恒数值门。

第二项已经在不读取 action、panel 或 outcome 的条件下独立复现。`2021-12-14T11Z` 的原始矩阵
指数质量残差只有 `3.91e-11 m3`，但算子将 7 个 reach storage 分量各自按同一个全局容差清零，
共删除 `1.046e-6 m3`，略超过 `1.004e-6 m3` 的全局容差。这个结果说明 v1 的该处异常来自
componentwise cleanup，而不是状态物理发散；它不撤销 accuracy 和 direction gate 的失败，也不允许
修改 v1 后复用已消费的 holdout。

公开参数审计随后固定到两个官方仓库 commit：

- `NCAR/wrf_hydro_nwm_public@4510c28c9afc72b42062158125a56b6d9dc6c057` 的
  `Route_Link.cdl` 给出字段合同；
- `NOAA-OWP/t-route@12a8eae0cdfed437143c590659fa7077605a5e70` 的 Hurricane Laura 和
  Lower Colorado RouteLink 给出真实区域参数 fixture。

两份 NetCDF 均完整包含 `Length/BtmWdth/TopWdth/TopWdthCC/ChSlp/So/n/nCC`，也包含
`MusK/MusX`。但它们对 Center Hill 的 26 个 active feature ID 覆盖均为 `0/26`。因此它们可以验证
参数合同和算子 invariant，不能充当 Center Hill 参数。将某区域的宽度、坡度或糙率复制到另一区域
违反参数 provenance 和地理机制要求。

官方 `t-route` 的 Muskingum-Cunge reach kernel 接收上一时刻上游/本段流量、流速、深度，以及
`qlat, dt, dx, bw, tw, twcc, n, ncc, cs, s0`。它调用编译的 Fortran kernel，而不是只把 RouteLink
中的固定 `MusK=3600`、`MusX=0.2` 当作线性滤波器。当前项目没有已构建、版本固定的 t-route runtime，
也没有 Center Hill 的相应参数和初始水力状态。随后完成的 runtime adapter 与专业基线裁决记录在
ADR-021；Center Hill 参数缺口没有因此改变。

## Options Considered

| 方案 | 优点 | 主要问题 | 决定 |
|---|---|---|---|
| A. 修正 v1 清零后继续晋级 | 改动小 | 不能解决 persistence 和 direction 失败；会污染冻结裁决 | 拒绝 |
| B. 直接用固定 `MusK/MusX` 线性 Muskingum 链 | 字段已存在，计算简单 | 标量 LTI filters 对顺序仍可交换；fixture 的 K/X 还是常数 | 拒绝为 v2 |
| C. 把 t-route MC 直接嵌入当前内核 | 专业实现、参数语义完整 | 需要 Fortran/Cython runtime、初始 Q/V/D、版本集成和 Center Hill 参数 | 保留为专业基线与后续 adapter |
| D. 非线性 Manning reach-storage 网络 | 使用真实长度、断面、坡度、糙率和存量；最小、可审计、一般不交换 | 不是完整 MC/kinematic-wave PDE；仍需 hidden evaluation | 选择为 v2 研究算子 |
| E. 无参数神经传播核 | 表达力强 | 在当前单系统证据下不可辨识，容易绕开地理合同 | 拒绝为下一步 |

## Decision

实现 `NonlinearManningReachTransportOperator`，但只授予 research/invariant 身份。每个有向 reach 保存
体积状态 `S_i`，以有效长度 `L_i` 得到梯形断面面积 `A_i=S_i/L_i`。由 bottom width `b_i` 和 side
slope `z_i` 解出水深 `y_i`：

\[
A_i=b_i y_i+z_i y_i^2
\]

再用 Manning 关系计算出流：

\[
Q_i(S_i)=\frac{1}{n_i}A_iR_i^{2/3}\sqrt{S_{0,i}}
\]

有向状态转移为：

\[
\dot S_1=a+f_1-Q_1(S_1),\qquad
\dot S_i=Q_{i-1}(S_{i-1})+f_i-Q_i(S_i)
\]

其中 `a` 只能是第一条 active reach 的 action boundary，`f_i` 是逐 reach forcing。每个 300 秒
子步采用单调隐式有限体积更新，沿有向路径逐 reach 解：

\[
S_i^{k+1}+\Delta t Q_i(S_i^{k+1})
=S_i^k+\Delta t\left(I_i+Q_{i-1}(S_{i-1}^{k+1})\right)
\]

右侧非负且 `Q_i(S)` 单调，因此在 `[0, right-hand-side]` 上存在唯一非负根；使用 SciPy `brentq`
求解。该离散式逐 reach 守恒、干床精确保持零，并避免通用 ODE solver 在长退水极限返回微小负
storage。不得用逐分量近零清零；原始求解状态和返回状态必须是同一个守恒状态。根求解失败、负
storage 或全局残差超限均 fail-closed。

该模型是 nonlinear Manning reach-storage network，不得称为 Muskingum-Cunge、kinematic-wave PDE、
diffusive wave 或 hydrodynamic solver。官方 t-route MC 是后续必须并列的专业基线，不因本算子较轻量
而被替代。

## Admission Boundary

新增的 hydraulic geometry contract 至少包含同 feature 顺序的：

- bottom width；
- channel side slope；
- bed slope；
- Manning roughness；
- 参数来源、证据等级和 admission 状态。

`side slope` 必须带公式语义。RouteLink `ChSlp` 传给固定 t-route kernel 后由其计算
`z=1/ChSlp`；本合同的字段为 H:V，因此 GIS Compiler 必须写入 `1/ChSlp`，不能直接复制原字段。

只有 `path_admitted AND geometry_admitted AND operator_form_admitted` 才能产生 admitted transition。
公开区域 fixture 可在显式 diagnostic mode 下运行 invariant；由于 feature ID 不匹配，它们永远不能
为 Center Hill 设置 `geometry_admitted=true`。

partial reach 的几何参数可以沿用同一 feature 的断面属性，但 full-reach `q_lateral` 不能自动按长度
比例裁切。任何含 partial reach 且 forcing 非零的运行还必须通过独立的 forcing-support admission；
否则 fail-closed。

observation update 不属于该 transition operator。历史 gauge 可由未来单独的 causal state-estimator
更新 `S(t)`，但当前或未来 outcome 不得作为 action、forcing、geometry 或同一步 transition 输入。

## Invariant Suite

实现先在官方区域 RouteLink fixture 上通过以下无 outcome tests：

1. zero action + zero forcing：零状态保持零；
2. positive action：状态非负且逐步/全窗质量守恒；
3. zero action + lateral forcing：完整长窗不崩溃；
4. long recession：无 componentwise cleanup 质量损失；
5. low-flow 极限：不产生 NaN、负水深或负出流；
6. reversed heterogeneous geometry：响应必须与 authoritative order 有实质差异；
7. homogeneous/degenerate control：方向差异不得被伪造为测试常数；
8. partial reach + nonzero full-reach forcing：在 support 未 admitted 时必须拒绝；
9. observation/action/forcing 类型隔离。

官方 9-reach fixture 的 invariant 阈值固定为 reversed-order outlet series 相对 L1 差异至少 `0.5%`；
同质三段对照最多 `1e-8`。首次报告曾把 RouteLink `ChSlp` 直接当作 H:V，得到 `0.976%`；固定
t-route 源码对照随后证明正确编译为 `1/ChSlp`。在未读取 outcome 的条件下重生成后，方向差异为
`2.541%`，原报告与哈希被替换。`0.5%` 仍只排除数值噪声和伪方向，不是 hidden evaluation 的
科学 direction gate。

方向 invariant 只证明算子族能表达非交换方向，不证明真实河流方向机制已经验证。科学晋级仍要求
新 hidden evaluation 中 authoritative direction 优于 reversed direction。

## Evaluation Lock

- Center Hill chunk `560` 只可用于失败诊断和 development，不能再次称为 hidden holdout。
- Center Hill v2 transition 在版本匹配 RouteLink 或独立权威逐 reach 参数取得前禁止执行。
- 取得参数后，必须在读取 outcome 前冻结新 chunk `561` 或更晚窗口。
- 至少增加一个第二系统，并登记 persistence、direct action、t-route MC、zero-action、no-forcing、
  reversed topology、守恒和 parameter-provenance gates。
- 不允许用新的 evaluation outcome 选择 solver tolerance、warm-up、geometry scaling、forcing support
  或 observation-update 强度。

## Trade-offs Accepted

- v2 research operator 比专业 MC 简单，只承担“真实几何约束的最小非线性有向状态转移”。
- `brentq` 是成熟数值原语，但逐 reach、逐子步隐式求根比闭式线性推进昂贵；当前 10--30 reach
  路径规模可接受。
- 暂时无法在 Center Hill 上运行不是项目停止，而是 admission 正常工作：数据可以继续公开获取，
  但不能用错误区域参数填空。
- `TopWdth/TopWdthCC/nCC` 已获取并保留，第一实现不声称已经模拟 compound channel；后续只有在公式
  和专业 baseline 对齐后才启用。

## Consequences

### Positive

- Kernel v2 的方向性来自拓扑与异质、非线性水力状态的组合，不再依赖可交换的线性滤波链。
- 真实公共 RouteLink 参数进入可执行 invariant，而不是停留在字段清单。
- 参数缺失会阻断具体系统运行，不会被默认值掩盖。
- transition、observation update 和 evaluation outcome 的边界被明确分开。

### Negative

- 当前仍没有可在 Center Hill 晋级的 v2 预测结果。
- t-route runtime adapter 已实现；但 Center Hill 初始 Q/V/D 和匹配参数仍缺失，nonlinear storage
  的 compound-channel physics 尚未实现。
- 第二系统与新 hidden holdout 仍需后续公开数据获取。

## Revisit Triggers

- 获得与当前 NWM feature axis/version 匹配的 Center Hill Route_Link；
- t-route 可以作为固定版本 runtime 在项目 CI 中复现；
- nonlinear storage 与 t-route MC 在公开 fixture 上出现不可解释的方向或守恒差异；
- backwater、分汊、潮汐、反向流或控制结构成为目标机制；
- 新 holdout 显示该算子仍不能超过强基线或 reversed direction 不退化。

## Implementation Evidence

本 ADR 随后完成实现。`ReachHydraulicGeometry` 将 bottom width、side slope、bed slope、Manning n、
feature axis、provenance 和 evidence admission 编译为独立合同；
`NonlinearManningReachTransportOperator` 实现单调隐式有向状态推进。transition API 不接受
`ObservationField`，action 仍只能进入第一条 active reach；partial reach 的非零 forcing 在 support
未准入时 fail-closed。

官方 Hurricane Laura NWM v2.1 RouteLink 中固定了一条 9-reach 连续路径，并在不读取 outcome、
observed action 或 observed forcing 的条件下完成 invariant：

| invariant | 结果 |
|---|---:|
| zero action + zero forcing | 120/120 小时，storage/outlet/residual 全为 0 |
| action pulse + long recession | 120/120 小时，horizon residual `1.90e-7 m3` |
| reversed action pulse | 120/120 小时，horizon residual `8.43e-7 m3` |
| lateral forcing + recession | 48/48 小时，horizon residual `6.00e-10 m3` |
| low-flow recession | 48/48 小时，无负值、NaN 或 componentwise cleanup |
| heterogeneous reversed order | outlet relative L1 difference `2.541%` |
| homogeneous reversed control | outlet relative L1 difference `0` |

全部 invariant gates 为 pass。该结果只证明算子形式能够表达非交换方向并在合法通量极限稳定守恒；
没有真实 outcome，因此不证明 authoritative direction、预测精度或 hydrodynamic validity。Center Hill
参数覆盖仍为 `0/26`，相应 execution admission 保持 false。

固定 t-route MC 专业基线随后完成。它通过官方 Q/V/D 样例和 24 小时 dry-state invariant，在相同
9-reach synthetic pulse 上产生 `21.730%` 的正/反向差异；当前 nonlinear storage 的 300 秒对照为
`2.586%`。二者小时 Q/V/D discrepancy 约为 `30.58% / 20.61% / 31.63%`，不是等价实现。
t-route 返回接口没有暴露可跨步累计的内部 MC storage，返回 `ck/X` 也不能重建最终 Q 的蓄量方程，
所以其 `official_mc_conservation_verified=false`。详见 ADR-021。

## Claim Boundary

- `public_route_link_schema_acquired=true`
- `public_real_parameter_fixtures_acquired=true`
- `center_hill_parameter_coverage=0/26`
- `center_hill_muskingum_cunge_admitted=false`
- `nonlinear_manning_reach_storage_implemented=true`
- `operator_invariants_passed=true`
- `operator_can_express_noncommutative_direction=true`
- `official_t_route_kernel_executed=true`
- `professional_baseline_available_on_official_fixture=true`
- `official_mc_conservation_verified=false`
- `authoritative_real_world_direction_validated=false`
- `center_hill_execution_admitted=false`
- `hydrodynamically_validated=false`
- `benchmark_validated=false`
- `geospatial_kernel_validated=false`
