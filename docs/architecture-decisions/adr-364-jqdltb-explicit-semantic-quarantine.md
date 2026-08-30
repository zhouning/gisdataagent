# ADR-364: JQDLTB Explicit Semantic Quarantine

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-30

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

JQDLTB 的 `SJNF` 和 `MSSM` 没有可采纳的权威来源。业务可以明确要求“在权威规则出现前
继续隔离”，但原有 Decision Packet 只有 `pending_business_evidence`，无法区分“尚未决定”
和“已经决定隔离”。如果把隔离写成普通 submitted semantic derivation，又会被误当成已经
具备可执行映射。

## 决策

允许 `SJNF`/`MSSM` 使用明确的 `deferred` 决定；同样允许已选择
`business_correction` 但尚未收到 artifact 的面积策略进入 `deferred`：

- `selected_value` 固定为 `quarantine_until_authority_exists`；必须绑定人工或团队 owner，
  但不得携带 source fields、semantic contract、规则 SHA-256 或默认值。
- `nonpositive_area_policy` 的 deferred 值固定为 `business_correction`；在该状态不得携带
  correction ResourceVersion 或 SHA-256，待 artifact 到位后再增量解析为普通 submitted 决定。
- 只有 `SJNF`/`MSSM` 和 `nonpositive_area_policy` 可以进入该状态；其他 target 的 deferred
  决定直接拒绝。
- `deferred` 仍是 readiness blocker，阻止 `to_strategy()`、ApprovalCase、executable
  transformation contract、层物化和 `DataProductVersion`。它表达的是业务处置决定，不是
  语义准入。
- 后续出现版本化权威来源时，增量 packet 可以把 deferred target 解析为普通 submitted
  semantic decision；已提交的其他 target 不得被覆盖，packet 时间必须递增。
- 所有 packet identity 和 frozen evidence 仍在每次提交前后重验。

## 证据

- [Decision Packet contract](../../data_agent/platform_contracts.py)
- [Submission and incremental-update CLI](../../scripts/manage_chongqing_jqdltb_transformation_approval.py)
- [Regression tests](../../data_agent/test_jqdltb_decision_packet_submission.py)
- 2026-08-30 实际 packet v3：`nonpositive_area_policy=business_correction (deferred)`、
  `SJNF/MSSM=quarantine_until_authority_exists (deferred)`，validation SHA-256
  `04573bbe8cdd8ff562075cd327f1096e2ab864eb85cf4f699d2bb17af19832ff`，readiness SHA-256
  `25909bc34e2dd519f22e76114a7ab215fb290449519d0f8b166d2c49517e40cb`。

该决定没有创建 ApprovalCase、Strategy、层文件或 `DataProductVersion`。
