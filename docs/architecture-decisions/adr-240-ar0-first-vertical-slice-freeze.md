# ADR-240: AR-0 首条 Vertical Slice 冻结边界

## Status

Accepted

## Date

2026-08-22

## Context

AR-0 原先把 schema/runtime truth、元数据与调度生产基础、湖仓 profile、GIS 服务矩阵、MMFE/GWM、AgentOps 和客户环境晋级都作为同一个退出门。局部能力持续增加，但没有一个有限的、可由 owner 关闭的终点，技术设计冻结、实现验收和生产 promotion 也被混在一起。

仓库已有一条可复跑的重庆 JQDLTB 标准映射验收：归档和 Shapefile sidecar bundle 身份固定，`llm_mode=disabled`，JQDLTB golden 的 precision/recall gate 通过，两个跨域负向 holdout 没有自动推荐。同时，全量源 onboarding 已明确暴露主键、数值、面积和标准字段推导问题。业务责任、许可和 SLO/on-call 仍是外部决定，不能由工程侧猜测。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 继续扩展全量 AR-0 退出门 | 总体清单看起来完整 | 终点不断移动；局部证据无法形成交付闭环 | 不选 |
| 直接把开发环境技术通过标成生产完成 | 状态立即变绿 | 把开发、技术验收和业务/生产责任混为一谈，造成错误晋级 | 不选 |
| 冻结一条有身份、有分层、有准入门的首条 vertical slice，外部待决单独挂起 | 终点有限、证据可复跑、阻塞可指派 | 首期能力较窄，仍需后续跨 profile/生产扩展 | **选择** |

## Decision

1. AR-0 首期固定为“重庆璧山 JQDLTB -> Raw/ODS/DIM-DWD/DWS(可延期)/ADS PostGIS -> OGC API Features + MVT”的链路，业务域为 `parcel_current`。
2. 归档 checksum、sidecar bundle checksum、released standard 版本、数据分类和 `llm_mode` 是不可变输入身份；身份变化必须创建新 Manifest 版本。
3. Manifest 状态使用 `draft`、`technical_frozen`、`awaiting_business_approval`、`promotable`，技术冻结不得隐含 DataProductVersion 已发布。
4. 目标设计、代码/测试事实和真实运行/晋级事实分层记录。scheduler/provider 成功不能替代独立 QualityResult、Lineage、Artifact 和服务投影证据。
5. `business_steward`、`license_status`、SLO/on-call 和 staging/production environment owner 是显式待决项。Agent 不填充这些组织、合同或客户环境事实。
6. MMFE、GWM、完整 OGC/COG/STAC/3D、跨引擎等价、生产 HA/DR 和 AgentOps 多智能体生产闭环不阻止本次设计冻结，但阻止相应阶段的生产晋级；它们由后续 AR 阶段交付。

## Rationale

- JQDLTB benchmark 已经给出可复跑的技术边界，适合作为第一条垂直切片，而不是继续等待所有领域达到同一成熟度。
- 全量 source-quality 失败被保留为失败证据，能直接驱动修复任务，避免把标准映射 proposal 误写成已发布产品。
- 将外部决定独立列出后，工程工作可以继续进行，但不会越权宣称客户可用或对外分发。

## Trade-offs Accepted

- 首期不证明全量数据产品、DWS 指标、所有 GIS 协议、跨引擎一致性或生产 HA/DR；这些能力仍需自己的真实证据。
- 采用 Lightweight/PostGIS 作为首条可执行 profile 的候选边界，不能据此宣称 Default Lakehouse 或云 profile 已通过。
- Manifest 处于 `awaiting_business_approval` 时，技术开发可继续，但任何 promotion API 必须保持 fail closed。

## Consequences

### Positive

- AR-0 有有限、可审计的下一证据，不再因新增架构主题自动扩张。
- 业务和环境阻塞项有明确 owner 入口；错误输入、许可不明和质量失败不会被文档掩盖。
- 后续实现都能围绕同一个 ProductVersion/Run/Artifact/QualityResult/Lineage 追踪。

### Negative

- 需要业务方和运维方实际提供批准信息；仅靠工程提交无法把状态推进到 `promotable`。
- 首条切片的修复可能暴露更多源数据问题，必须新增 Manifest 版本或附加证据，不能改写历史。

## Revisit Triggers

- `business_steward`、`license_status`、SLO/on-call 和环境 owner 均有可验证批准记录；
- JQDLTB source-quality gate 通过，并以同一 ProductVersion 完成 Raw -> ADS 的真实重建和服务验收；
- 首期输入身份、标准版本、分层合同或服务协议发生变化；
- 需要把 MMFE/GWM、另一数据域、另一 provider profile 或生产 HA 纳入同一验收范围。

## Evidence

- [AR-0 首条 Vertical Slice Freeze Manifest](../freezes/2026-08-22-ar0-first-vertical-slice-freeze.md)
- [AR-0 机器可校验 Manifest](../../config/freezes/ar0-first-vertical-slice-2026-08-22.json)
- [ADR-089 标准版本绑定的智能落标合同](adr-089-standard-version-bound-application-contract.md)
- [重庆标准映射验收协议](../../benchmarks/standard_mapping_chongqing_v0_1/README.md)
- [ADR-239 DataIncident 通知恢复](adr-239-incident-notification-governed-recovery.md)
