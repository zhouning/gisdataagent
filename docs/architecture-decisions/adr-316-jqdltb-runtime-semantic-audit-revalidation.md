# ADR-316: JQDLTB 执行前重新验证语义审计

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-26

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

ADR-315 已把 semantic audit SHA 纳入新 proposal 的 plan、contract fingerprint 和 ApprovalCase
context，但 executor 原先只重新读取 source diagnostic 和最终 derivation rule artifact。若运行环境
缺少 semantic audit，或者字段状态已不再是 `accepted/approved`，执行证据无法证明本次写入仍满足
批准时的 source admission。

## 决策

- 带 `semantic_candidate_audit_sha256` 的 execute contract 必须在运行前获得实际 semantic audit。
- audit 的 canonical fingerprint、archive/bundle/standard identity 必须与 contract 一致。
- audit 顶层 target decision 也必须是 `accepted_candidate_available`、`accepted` 或 `approved`，
  不能只篡改单个候选行的 status。
- `SJNF/MSSM` 的每个 source field 在该 audit 中仍须为 `accepted` 或 `approved`。
- 校验发生在读取源记录和创建输出目录之前；缺文件、内容篡改、身份漂移或字段状态回退均 fail closed。
- DataOps executor 增加 `--jqdltb-transformation-semantic-audit` 装配入口；transformation evidence、
  lineage、artifact 和平台 technical refs 记录实际绑定的 audit SHA。
- 未携带该字段的历史/合成合同保持兼容；公开 `prepare_approval()` 产生的新合同都会携带该字段。

## 取舍

- **只依赖 plan 中的 SHA**：能发现合同篡改，但不能证明运行时仍能取得审批证据，拒绝。
- **只校验最终 rule artifact**：能确认算法字节，不能确认 source field 曾获语义准入，拒绝。
- **运行前同时校验 audit 和 rule artifact**：增加一个只读 JSON 输入，但把“为何允许使用字段”和
  “字段如何计算”分别绑定，采用。

## 结果

真实冻结 audit 仍拒绝现有候选，因此不会产生真实 execute contract。测试使用 disposable accepted
audit 证明成功路径，并验证缺少 audit、指纹篡改、字段状态回退均在零输出状态下拒绝；这些 fixture
不构成业务批准。

## 证据

- [执行合同校验](../../data_agent/platform_contracts.py)
- [JQDLTB executor](../../data_agent/jqdltb_transformation_executor.py)
- [合同测试](../../data_agent/test_jqdltb_transformation_contract.py)
- [执行器测试](../../data_agent/test_jqdltb_transformation_executor.py)
