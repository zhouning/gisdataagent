# GWM / Geospatial Kernel 阶段性结项决策

日期：2026-08-01

## 决策

停止当前 Center Hill 水库放水 WWM prospective 验证主线，不再增加 Stage、继续调参或使用替代数据填补关键输入。

该决策不等于删除 geospatial kernel。现有实现重新定位为“可审计的空间推演与评测基础设施”，不再表述为已验证成功的通用世界模型。

## 依据

1. TVA 官方应用证明存在 Center Hill 分时机组调度接口，但当前执行环境实际请求返回 Cloudflare HTTP 403 / 1009，未取得可签发的真实未来调度。
2. 原生动作单位是运行机组数，不是物理模型所需的总放流 `m3/s`。
3. 2021–2025 年 `43,825` 个小时的库水位、尾水位和四类放流分量联结表明，事后潜在 1/2/3 机组流量带中位数约为 `110.75 / 226.25 / 337.00 m3/s`，但没有独立机组数标签，不能据此冻结转换。
4. 固定单机流量诊断 RMSE 为 `12.13 m3/s`；同期水头回归 RMSE 为 `11.20 m3/s`，且斜率为负，尾水位不能作为签发前外生输入。
5. `9,687 / 43,825 = 22.1%` 的历史小时至少存在一个非机组放流分量，generator count 不能完整表达总放流。
6. operational NWM forcing 合同、sealed physical forecast receipt、J. Percy Priest 跨系统迁移和可信外部时间戳仍未成立。
7. 至今没有新的 prospective skill 结果，也没有超过 persistence、ARX 或传统水动力方法的正式证据。

## 保留范围

- 空间状态、行动、外部 forcing 和时间支撑合同；
- 河网拓扑、守恒转移和 ensemble 状态估计；
- issue-time 因果隔离、预测封存、成熟 outcome 更新；
- persistence、ARX 和领域传统模型的统一评测门禁；
- TVA 原生动作与物理放流边界的两层合同。

这些能力可以作为 `Geospatial Kernel v0.1` 的工程基础，但其成功标准是可组合、可审计和可复算，不是 kernel 本身战胜 FLUS、HEC-RAS 或 t-route。

## 重新开启条件

只有以下条件同时满足，才重新启动 action-conditioned WWM：

1. 可稳定获取、封存并验证发布时间的未来调度；
2. 有独立机组数/负荷标签、未来水头和非机组分量支持的总放流 `m3/s` 边界；
3. 至少两个水系具有长期 prospective issue/outcome，并能与锁定传统基线共同评分。

在此之前，新的研究任务必须先完成数据准入和传统基线复现，再编写 GWM 学习模型；没有合格数据，不进入模型开发。

## 当前裁决

- Center Hill live WWM v3 issue ready：`false`
- Trusted dual-system campaign ready：`false`
- Physical release boundary ready：`false`
- Candidate promoted：`false`
- Runtime default enabled：`false`
- Geospatial kernel validated：`false`

当前结果是一个可重算的 no-go 和阶段性结项，不是模型成功声明。
