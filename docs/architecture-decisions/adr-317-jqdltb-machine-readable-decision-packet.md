# ADR-317: JQDLTB 业务决定使用可验证 Decision Packet

**状态**: Accepted for AR-0 implementation  
**日期**: 2026-08-26  
**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

AR-0 的剩余阻塞同时包含数据策略（canonical key、面积处理、`SJNF/MSSM`）和组织/环境输入
（业务责任、许可、SLO、staging/production owner）。此前这些输入只出现在 readiness 文本中，
业务方无法提交一个带证据的版本化对象，工程侧也无法在进入 `Strategy` 或 `ApprovalCase` 前
稳定拒绝缺字段、错值和证据身份漂移。

## 决策

- 增加 `JqdltbDecisionPacket`，固定十个 AR-0 决策 target；每项记录当前状态、责任主体、
  selected value（如已提交）、规则/语义绑定和 evidence。
- 每项 evidence 都带 `evidence_ref`、SHA-256、确定性 extraction method，并复制冻结源、标准、
  diagnostic、semantic audit 的完整 identity。packet 自身使用 canonical JSON SHA-256。
- `draft` packet 可以由冻结材料自动生成，不写 authority、不创建 ApprovalCase、不修改源数据。
- `submitted` packet 可以保留责任、许可、SLO 和环境 owner 的 pending 状态；只有 transformation
  五项决定齐全时，才允许在内存中转换为既有 `JqdltbTransformationStrategy`。这些组织/环境项仍由
  promotion gate 单独消费，之后 Strategy 必须经过 semantic admission、`prepare_approval()` 和统一
  ApprovalCase authority。packet 不替代审批系统。
- packet 验证先检查冻结 baseline/evidence identity，再检查提交形态；缺失、格式错误、身份漂移
  或语义来源未获 `accepted/approved` 时 fail closed。

## 取舍

- **继续使用 readiness 文本**：实现简单，但无法由业务提交可重放输入，也无法对每条证据做绑定校验。
- **让 packet 直接创建 ApprovalCase**：链路短，但会把业务输入收集和人类批准混成一个状态机，
  破坏现有 ApprovalCase 的独立责任边界。
- **在现有 Strategy 上继续加字段**：减少类型数量，但会让 pending 业务输入和可执行策略共享
  一个不适合的契约；采用独立 packet，再由严格转换函数连接两者。

## 结果

已从真实 AR-0 冻结材料生成 [`jqdltb_business_decision_packet_2026-08-26.json`](../reports/jqdltb_business_decision_packet_2026-08-26.json)：
10 项均为 `pending_business_evidence`，packet SHA-256 为
`d9fe04814ca66bfcea769e6269c9c532893ef4d94e0e279c628d6f20896e609d`。未分派的责任字段使用
`unassigned:*` 占位，不表示团队已经接受责任。验证器确认 identity bound，列出 10 个 blocker，
未创建 authority state。当前真实业务结论没有被代填。

## 验证

```bash
./.venv/bin/python scripts/manage_chongqing_jqdltb_transformation_approval.py \
  validate-decision-packet \
  --packet docs/reports/jqdltb_business_decision_packet_2026-08-26.json
```

`data_agent/test_jqdltb_decision_packet.py` 覆盖 target 完整性、确定性 fingerprint、pending blocker、
身份漂移拒绝和禁止提前转换；`readiness --decision-packet` 另外复用同一验证器，不会把 draft
packet 误报为可执行策略。AR-0/JQDLTB 聚焦回归保持通过。
