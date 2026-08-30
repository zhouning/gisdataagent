# ADR-319: Decision Packet 绑定 JQDLTB DataProduct 发布门

**状态**: Accepted for AR-0 implementation  
**日期**: 2026-08-26  
**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

Decision Packet 已能作为 readiness 输入，但 release plan 仍可以只携带 transformation contract
和 operating contract。这样会留下两套业务字段：packet 记录一套决定，发布计划再填写一套责任、许可和
运行值，审批后可能出现无法追溯的漂移。

## 决策

- `JqdltbDataProductReleasePlan` 增加可选 `decision_packet`。packet 存在时必须为 `submitted`，十项
  决定全部已提交或接受。
- packet identity 必须与 executable transformation contract 的 source、archive、bundle、standard、
  diagnostic 和 semantic audit identity 完全一致。
- canonical key、面积策略、规则/语义字段、业务 steward、license、on-call 以及 staging/production
  owner 逐项与 transformation/operating contract 比对；任何漂移在构造 release plan 时 fail closed。
- packet SHA-256 同时写入 mapping binding、layered distribution manifest、release ApprovalCase context
  和不可变 registry binding。它是可追溯证据，不等同于 transformation 或 release ApprovalCase。
- development synthetic fixture 为兼容现状可不带 packet；staging/production release 必须带 submitted packet。
  数据库 deferred trigger 对 DataProductVersion 再检查四个发布面和环境硬门，不能通过直接 registry 写入绕过。

## 结果

发布计划、产品版本和 registry 行现在只能引用同一份 packet fingerprint。业务仍需在人类审批流程中提交
策略和运营责任；当前真实 packet 仍为 draft，AR-0 仍是 `awaiting_business_approval`，没有因此生成真实
DataProductVersion 或生产发布。

## 验证

- release contract 回归覆盖 packet 成功绑定、identity/策略/责任人漂移和 staging/production 缺 packet。
- migration 234 增加 `decision_packet_sha256`、格式约束和 deferred binding trigger；PostgreSQL 认证
  使用同一 authority 表和 RLS/不可变约束。认证报告为
  `.tmp/jqdltb-data-product-release/acceptance-report.json`，SHA-256 为
  `b3e9ddf5f2a44b47d347ea3fd03e986953c9c48c83d37ec827393ab80657b8c2`；报告明确标记
  `production_claim=false`、`real_business_approval_claim=false`。
