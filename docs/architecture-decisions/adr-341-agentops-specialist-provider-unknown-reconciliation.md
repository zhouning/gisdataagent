# ADR-341：AgentOps specialist provider unknown/cancellation reconciliation

## 状态

已验证 bounded local Temporal-contract slice；不代表 Temporal server、PostgreSQL/MinIO
receipt authority 或 production cancellation readiness。

## 背景

ADR-340 已经让 MMFE/GWM 在 Temporal activity 中按 Artifact UUID 读取输入并幂等产出
Artifact。但 provider 可能在已经提交操作后丢失响应，或者取消/超时发生在 provider 返回
终态之前。此时 activity 只能知道“结果未知”：重试可能造成重复写入，直接写成功证据会把
未确认的输出提升为平台事实，直接写失败又可能掩盖已经提交的 provider 操作。

## 选项

| 选项 | 优点 | 风险 |
| --- | --- | --- |
| 立即重试 activity | 实现简单 | 可能重复执行 data write，无法证明第一次是否已提交 |
| 把 unknown 当失败 | 状态容易收敛 | 丢失已提交操作，无法解释 provider 事实 |
| 独立 operation receipt + 只读对账 | 不重试未知操作；可从 receipt 和 Artifact authority 收敛 | 需要 provider 暴露可观察回执，生产还需 durable authority |

## 决策

采用第三项，并固化以下合同：

1. 每个 activity attempt 绑定唯一 `provider_operation_ref`，并由独立 operation authority
   登记 hash-bound `SpecialistOperationReceipt`；receipt 与 Temporal activity evidence 分开。
2. provider 已提交但响应丢失时返回 `TemporalActivityOutcome.UNKNOWN`，不自动 retry、不创建
   output Artifact 成功证据。副作用 ToolCall 的 unknown evidence 必须引用 Artifact `EVIDENCE`
   角色的 operation receipt。
3. reconciler 只读观察 operation receipt，并通过同一 Artifact store 校验 deterministic
   output UUID、request SHA-256、provider/operation、输入 lineage、media type 和内容 checksum。
   全部匹配才生成 `matched_succeeded`；provider 明确失败或取消才生成 `definitive_failed`；
   其余保持 `unknown_pending`。
4. unknown observation 与后续 settlement 使用不同 evidence idempotency key；相同 operation
   仍只能有一个终态，冲突时 fail closed。
5. 当前实现提供 bounded `InMemorySpecialistOperationAuthority` 和本地 Artifact evidence
   写入；生产接入必须换成 PostgreSQL append-only receipt authority，并连接真实 Temporal
   history、provider cancellation API、lease/fencing 和跨进程 reconciler。

## 结果

- `BoundSpecialistExecutor` 支持提交后失联和取消超时故障注入。
- MMFE `spatial_join` 的真实输出在 activity 响应丢失后，通过 receipt + output Artifact
  对账收敛成功；同一请求重放读取终态 receipt，不再次执行 MMFE。
- GWM 取消/超时在没有 output Artifact 时保持 `unknown_pending`，不伪造成功。
- output manifest 及内容 checksum、输入 lineage、provider binding 任一冲突都会拒绝收敛。
- adapter 为 unknown 和 settlement 分配不同 evidence key，允许不可变追加收敛证据。

## 证据

- 契约和负向回归：`data_agent/test_agentops_specialist_providers.py`、
  `data_agent/test_agentops_temporal_adapter.py`、`data_agent/test_agentops_temporal_workflow.py`，
  本轮相关集合 `40 passed`。
- bounded rehearsal：
  [agentops_specialist_unknown_reconciliation_2026-08-28.json](../reports/agentops_specialist_unknown_reconciliation_2026-08-28.json)
  （文件 SHA-256：`cf6c5e0e989be805e4b713a6af6b3ab9a485b53cd725a48663d90dd1f2a281d6`；报告内
  `report_sha256=a9f9516ac8e371814f15c2b8d30844e68a4ad914cdadcab57964cb33211736e4`）。
- 演练脚本：`scripts/rehearse_agentops_specialist_unknown_reconciliation.py`。

## 取舍与未完成项

- 本 slice 增加了 operation receipt、evidence Artifact 和 reconciler 状态，换取不重复执行
  未知副作用的安全边界。
- 本地内存 authority 不能证明跨进程持久性、CAS、lease fencing、Temporal worker crash 后的
  自动发现或生产取消 SLA。
- 仍未关闭 PostgreSQL receipt migration、真实 MinIO/S3 evidence version binding、Temporal
  cancellation/history observation、跨 provider conformance、HA/DR、SLO、identity rotation
  和 production readiness。

## 复审触发

接入第一个真实集群 provider 时，必须重新验证 operation receipt 的终态语义、取消 API、
output Artifact authority 事务边界和跨进程 fencing；若 provider 无法提供可验证的 operation
receipt 或 output identity，则该 provider 只能停在 `unknown_pending`，不得进入生产写路径。
