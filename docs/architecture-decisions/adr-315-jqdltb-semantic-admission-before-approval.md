# ADR-315: JQDLTB 语义证据必须先于审批准入

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-26

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

`ADR-314` 已将冻结源中的 `PZWH`、`SM`、`DLBZ`、`JQDLMC` 标为拒绝或待业务证据，但
transformation readiness 原先只检查字段是否出现在诊断候选列表中。调用方可以因此得到 proposal
预览，甚至直接调用 `prepare` 生成 pending ApprovalCase。

## 决策

- readiness 从语义审计读取每个 target 的字段状态；只有 `accepted` 或 `approved` 才是可用来源。
- `rejected`、`pending_business_evidence` 和未登记字段在 proposal 前拒绝。
- `prepare` 重新读取 Manifest、diagnostic 和 semantic audit，并执行同一来源准入；不能绕过
  readiness 直接创建 proposal 或 ApprovalCase。
- 公开 `prepare_approval()` 是唯一受支持的生产构造入口：它先运行完整 Freeze verifier，再校验
  diagnostic 指纹、semantic audit、Manifest 指向的完整 baseline 及 source admission。纯 hash 构造下沉为私有
  `_build_approval()`，只供不声称业务准入的下游合成测试使用。
- 通过准入的 proposal/execute contract 将 `semantic_candidate_audit_sha256` 纳入
  `plan_sha256`、完整 contract fingerprint 和 ApprovalCase request context；旧的
  `approval_required` baseline 在该字段为空时保留原有指纹。
- 当前冻结语义审计没有可用来源，所以 readiness 明确报告
  `semantic_derivation_evidence_missing.SJNF` 和 `.MSSM`；这不会改变源质量或业务批准结论。

## 取舍

- **只在 executor 拒绝**：审批对象已经产生，责任人可能批准一个已知错误来源，拒绝。
- **只检查字段存在性**：把技术候选误当语义证据，拒绝。
- **只封 CLI**：直接 Python 调用仍能跳过 semantic admission，拒绝。
- **在 readiness 和公开 prepare 复用同一状态机**：多一次 Freeze/绑定校验，但 proposal、
  ApprovalCase 和运行规则共享同一语义门，采用。

## 结果

真实冻结报告仍不产生任何审批状态。未来业务材料到达后，必须更新内容寻址 semantic audit，重新
绑定 Manifest，再由 readiness/prepare 生成带语义审计指纹的 proposal；executor 仍按 ADR-313
校验最终 rule artifact。

## 证据

- [审批准入实现](../../scripts/manage_chongqing_jqdltb_transformation_approval.py)
- [审批流程测试](../../data_agent/test_jqdltb_transformation_approval_workflow.py)
- 当前默认 readiness SHA-256：`b0322495824050293aee52ba23976026582ebb1617cf98840e417ead5077eb77`
- AR-0/JQDLTB 聚焦回归 `47 passed, 1 skipped`；跳过项仅因未配置外部
  `JQDLTB_RELEASE_DATABASE_URL`。Ruff、Python compile 和 31 项 Freeze machine checks 通过。
