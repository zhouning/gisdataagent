# ADR-318: Decision Packet 作为 JQDLTB Readiness 输入

**状态**: Accepted for AR-0 implementation  
**日期**: 2026-08-26  
**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

ADR-317 把十项 JQDLTB 业务输入固化为可验证的 Decision Packet，但 `readiness` 仍只接受
`Strategy` 文件。业务提交 packet 后，工程侧必须再手工转换成 strategy 才能看到同一份
transformation preview，容易造成 packet、策略和 readiness 结果漂移。

## 决策

- `readiness` 增加与 `--strategy` 互斥的 `--decision-packet` 输入。
- readiness 先重新读取 Manifest、baseline、diagnostic、semantic audit 及 packet evidence，
  再按 `validate_decision_packet()` 的 identity、fingerprint 和 semantic admission 规则校验；
  readiness 不信任 packet 外部传入的验证结果。
- `draft` 或 transformation 决定不完整的 packet 只输出分层 blockers，不生成 Strategy 或
  proposal preview；输出包含 packet status、packet SHA-256 和 validation SHA-256。
- `submitted` packet 的五项 transformation 决定完整且语义证据已获 `accepted/approved` 时，
  只在内存中转换为既有 `JqdltbTransformationStrategy`，复用现有 dry-run proposal/plan
  preview。五项 promotion 决定仍独立进入 promotion blockers，不能把 packet submission 当成
  ApprovalCase、DataProductVersion 或生产晋级。
- readiness 输出路径不得覆盖 manifest、baseline、诊断、semantic audit、strategy 或 packet
  输入；整个命令保持只读，不创建 authority state。
- draft packet 的未分派责任使用 `unassigned:*`，避免把建议责任主体误报为已接受的团队。

## 取舍

- **只保留 `--strategy`**：调用简单，但业务 packet 不能成为可重放的 readiness 输入。
- **packet 直接创建 proposal/ApprovalCase**：链路更短，但会越过现有 semantic admission 和
  ApprovalCase authority，混淆业务收集与审批状态机。
- **让 readiness 读取 packet 内的 validation 结果**：性能略好，但允许 stale/tampered 结果
  进入决策；选择每次从本地证据重算，保持 fail closed。

## 验证

- draft packet readiness：报告 packet status/SHA、五项 transformation 和五项 promotion
  blockers，`strategy_ready=false`，未创建 authority state。
- accepted semantic fixture：五项 transformation 决定可生成 proposal preview，promotion
  blockers 仍保留，且 preview 的 `plan_sha256` 与 `approval_context` 一致。
- packet identity drift、输入输出覆盖和原有 `--strategy` readiness 回归均通过。
