# ADR-363: JQDLTB Human Decision Submission CLI

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-30

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

AR-0 已经能够生成和验证 JQDLTB draft Decision Packet，但没有受约束的提交入口。直接编辑
JSON 容易改变冻结 evidence、漏掉提交人或破坏 packet fingerprint，也无法保证提交失败时
不留下半成品。

## 决策

新增 `submit-decision-packet` CLI 和 `submit_decision_packet()`：

- 输入必须是冻结 draft packet，以及形如 `{"decisions": {"target": { ... }}}` 的人工决定文件；
  target 必须属于固定十项，字段只能覆盖 selected value、owner、语义/规则绑定等决定字段。
- `evidence`、identity、packet id、created metadata 不能被覆盖；每个提交项必须显式给出
  `selected_value` 和 `owner_ref`，提交人必须是 `human:*`，时间必须不早于 packet 创建时间。
- 未出现在决定文件中的 target 保持原有 `pending_business_evidence`；因此可以先提交一部分
  promotion 决定，但 transformation 五项不完整时不会生成 strategy。
- 新 packet 在写入前重新校验 draft identity、全部 evidence、packet fingerprint，以及提交后
  的 semantic admission。任一失败都不创建输出文件。
- 输出状态只能是 `submitted`，后续仍须经过 `prepare_approval()` 和统一 ApprovalCase；该 CLI
  不创建 ApprovalCase、Strategy、层文件或 DataProductVersion。

## 证据

- [submission implementation](../../scripts/manage_chongqing_jqdltb_transformation_approval.py)
- [submission tests](../../data_agent/test_jqdltb_decision_packet_submission.py)
- [Decision Packet contract](../../data_agent/platform_contracts.py)

验证：Decision Packet 相关回归 `15 passed`；未知 target、非法字段、未批准语义来源和输出前
失败均有负向测试。真实 AR-0 packet 仍为 draft，未提交任何业务决定。
