# ADR-021：固定提交 t-route MC 作为 Q/V/D 专业基线

**Status**: Accepted with conservation limitation; Center Hill execution blocked

**Date**: 2026-07-26

**Decision owners**: Geospatial World Model, Geospatial Kernel, Hydrologic Evaluation

**Related decisions**: [ADR-019](adr-019-geospatial-kernel-reach-transport-v1-holdout-adjudication.md),
[ADR-020](adr-020-geospatial-kernel-v2-nonlinear-manning-reach-storage.md)

## Context

Kernel v2 已在官方 RouteLink fixture 上通过无 outcome invariant，但它是简化的 nonlinear Manning
reach-storage network，不是 Muskingum-Cunge。科学评估需要一个版本固定、真实可执行的专业路由基线，
而不能用自写的固定 `MusK/MusX` 线性滤波器代替 t-route。

整套 t-route 包含网络、reservoir、diffusive routing、数据同化、NetCDF 和多个 Cython extension。
当前比较只需要单段 MC kernel 和官方定义的上游到下游 Q/V/D 递推。引入完整应用会扩大运行环境和
依赖面，也不会解决 Center Hill 缺少匹配 RouteLink 的问题。

## Decision

固定 `NOAA-OWP/t-route@12a8eae0cdfed437143c590659fa7077605a5e70`，有界采集并逐对象记录 URL、commit、
大小和 SHA-256。只编译以下未修改的官方源文件：

- `varPrecision.f90`；
- `MCsingleSegStime_f2py_NOLOOP.f90`；
- `pyMCsingleSegStime_NoLoop.f90`。

adapter 通过 `ctypes` 调用官方 `bind(C)` 符号 `c_muskingcungenwm`。状态轴严格为逐 reach
`Q/V/D`，每步上游递推严格遵循官方 `reach.pyx`：下一 reach 的 `qup` 使用上游 reach 前一时刻 Q，
`quc` 使用上游 reach 当前 Q。不同 commit、library hash、feature axis 或非法状态均 fail-closed。

RouteLink `ChSlp` 原值原样传给 t-route。固定 Fortran 源码内部使用 `z=1/cs`；因此 GIS Compiler
为 `ReachHydraulicGeometry.side_slope_horizontal_per_vertical` 编译参数时必须使用 `1/ChSlp`。
字段重命名不能替代这个量纲与公式转换。

## Baseline Identity

- source manifest SHA-256：`6bb67aaaeb70cb97ed8795b9a15dd2ef7db2c8db8092393c0a7f824577b25e1d`；
- shared library SHA-256：`9d1cb42b189192007c2d62ac1c9e2e7b6814e967baa4fe147ed5c9a849c4b32b`；
- build manifest SHA-256：`26780f3c6cb9bcc4fa61b608c8e93843b4db2054a469ce0114c3880ba4b6a7f4`；
- compiler：GNU Fortran 13.3.0，Linux/aarch64；
- official Q/V/D conformance errors：`5.96e-8 / 7.45e-9 / 0`；
- 24 小时 dry-state Q/V/D：精确为零。

## Conservation Adjudication

t-route 输出 Q/V/D，并可返回 `ck/cn/X` 诊断量，但该接口没有暴露一个可跨步累计的内部 MC storage。
本固定源码的 lower-interval `X` 计算在当前调用赋值前引用 `intent(out)` 的 `C1/C2/C3/C4`；实际
9-reach rollout 中，返回 `ck/X` 不能重建产生最终 Q 的 MC 方程，最大重建残差为 `105,479 m3`。

用相同源码的 compound geometry 从 depth 推导 `area*length`，得到的正向 horizon residual 为
`160,205 m3`，占输入 `37.08%`。这个推导 volume 不是已暴露的内部 MC storage，所以不能据此断言
官方 MC 方程本身不守恒；同样，也不能把它包装成守恒通过。

因此：

- t-route 准入为专业 Q/V/D、compound-channel 和方向响应基线；
- `official_mc_conservation_verified=false`；
- t-route 暂不作为 conservation oracle；
- nonlinear storage 的 physical volume conservation 继续独立计量，不能用 t-route Q/V/D 替换；
- 后续若取得权威内部 MC storage 或逐步 balance diagnostics，再重新裁决 conservation 身份。

## Outcome-Free Comparison

Hurricane Laura 9-reach fixture、300 秒步长、6 小时 20 m3/s boundary pulse、120 小时 rollout：

| 量 | t-route MC | nonlinear storage |
|---|---:|---:|
| forward/reverse relative L1 | `21.730%` | `2.586%` |
| forward peak Q | `14.827 m3/s` | `10.792 m3/s` |
| Q/V/D 非负有限 | pass | pass |
| compound channel activated/implemented | yes | no |
| physical-volume horizon residual | not verified | `2.09e-7 m3` |

小时 Q/V/D model-family relative L1 discrepancy 分别为 `30.58% / 20.61% / 31.63%`。这些是无
outcome 的模型差异，不是准确率，也不证明 authoritative order 是真实正确方向。

## Consequences

- 专业基线从“待接入”变为可执行、可复现、固定源码身份；
- Kernel v2 不再把简化 storage 模型称为 MC 等价实现；
- `TopWdth/TopWdthCC/nCC` 已在专业基线中实际进入 compound channel，但 nonlinear storage 仍不得
  在缺少独立状态与守恒公式时启用；
- Center Hill feature coverage 仍为 `0/26`，不得迁移 Hurricane Laura 参数；
- 没有 outcome，因此 `benchmark_validated=false`、`geospatial_kernel_validated=false`。

## Revisit Triggers

- t-route 暴露或文档化可审计的内部 MC storage/balance；
- 固定源码升级且 Q/V/D conformance 或方向响应发生变化；
- nonlinear compound-channel 实现可在同一 fixture 上比较状态、Q/V/D 和守恒；
- 获得 Center Hill 或第二系统版本匹配的 RouteLink 与新冻结 outcome。
