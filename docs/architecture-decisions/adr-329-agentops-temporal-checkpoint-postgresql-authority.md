# ADR-329：AgentOps Temporal Checkpoint 的 PostgreSQL 持久权威

- **状态**：已采纳，append-only authority 与 disposable PostgreSQL 验证已完成；fencing/crash-window 由 ADR-330 补齐，生产 rollout 与 HA 未完成
- **日期**：2026-08-27
- **范围**：AR-5 AgentOps Runtime

## 背景

ADR-328 已能从真实 Temporal history 生成 provider observation，并与 GDA checkpoint 得出
`provider_behind`、`checkpoint_behind` 或 `matched`。此前 checkpoint 和 reconciliation 仍由进程内
harness 或报告文件持有，服务重启后没有一个数据库控制的恢复入口；并发 writer 也没有
predecessor compare-and-set，无法阻止旧 checkpoint 覆盖新状态。

Temporal 继续拥有 workflow execution history，GDA 继续拥有 AgentRun、TaskStep、ToolCall、
Artifact、policy、checkpoint 和 reconciliation evidence。本切片只解决 GDA 一侧的持久化，
不复制或修改 Temporal history。

## 方案选择

| 方案 | 结论 | 原因 |
|---|---|---|
| PostgreSQL append-only authority | 采用 | 复用既有 control ledger、RLS、gateway role 和备份边界；支持事务 CAS 与 typed readback |
| Event sourcing/CQRS | 不采用 | 当前只有 checkpoint 链和对账证据两种写入，没有独立读写模型或事件重建收益 |
| 只保存 JSON 报告/对象存储文件 | 不采用 | 不能原子执行 predecessor CAS、租户隔离和同 ID 漂移拒绝 |
| 把 checkpoint 写回 Temporal search attribute/history | 不采用 | 会混淆 Temporal execution authority 与 GDA governance/evidence authority |

## 决策

新增 migration `240_agentops_temporal_checkpoint_authority.sql`：

1. `agentops_temporal_checkpoint_history` 按 tenant/workflow 保存递增的 repository sequence、
   predecessor hash、完整 typed checkpoint 和关键查询列；`current` view 只投影链尾。
2. `agentops_temporal_reconciliation_evidence` 保存 provider run/history hash、checkpoint hash、
   完整 history observation 和 reconciliation verdict。外键要求 verdict 引用已存在的 GDA
   checkpoint。
3. 两张表均启用 RLS/FORCE RLS、immutable UPDATE/DELETE trigger；gateway role 只有 SELECT 和
   两个 `SECURITY DEFINER` 函数的 EXECUTE 权限，没有直接 INSERT/UPDATE/DELETE。
4. checkpoint 写函数以 tenant/workflow advisory lock 串行化 writer。首条记录不得有
   predecessor；后续记录必须精确引用当前链尾。相同 hash 与相同 document 幂等返回，identity
   相同但内容不同则 fail closed。链内 `run_id` 和 workflow input 保持不变，run state version
   只能前进或在同一状态补充 execution/evidence，不能倒退或同 version 换状态。
5. PostgreSQL 不只比对 document 内嵌 hash。repository 同时提交平台 canonical JSON fingerprint
   payload，数据库验证 payload 与 JSONB 内容相等，并以 `pgcrypto` 重新计算 SHA-256；篡改
   document 但沿用旧 hash 会在数据库内被拒绝。
6. `PostgresAgentOpsTemporalCheckpointAuthority` 负责 typed write/read。读回时重新执行 Pydantic
   合同及内部 fingerprint 校验，存储损坏不会被当作可恢复状态。

## 已验证证据

disposable PostgreSQL 演练复用了真实 ADR-328 checkpoint、observation 和 reconciliation：

- 2 个 checkpoint 按 predecessor 链写入，旧 predecessor 被拒绝，同一 checkpoint 同 actor 重放
  幂等、actor 漂移被拒绝；
- `checkpoint_behind -> matched` 两条 reconciliation 证据均持久化且重放幂等；
- 独立 Python 进程用新连接恢复 2 个 typed checkpoint 和 2 条 typed reconciliation；
- 跨租户读取为空，篡改 document/旧 hash 被数据库拒绝；
- 同一 reconciliation 的 actor 漂移被拒绝；gateway 直接 INSERT 被拒绝，管理员 UPDATE
  checkpoint 和 DELETE reconciliation 均被
  immutable trigger 拒绝。

报告：[agentops_temporal_checkpoint_postgres_rehearsal_2026-08-27.json](../reports/agentops_temporal_checkpoint_postgres_rehearsal_2026-08-27.json)，
`report_sha256=01464da844774881393d9842193b99586e331bdc09915ec37c3683d29ecad9b8`。

## 边界

这份证据证明的是 disposable PostgreSQL 上的持久合同、CAS、不可变性、RLS 和跨进程恢复，
不等于生产 checkpoint store 已上线。ADR-330 已在同一 authority 上补齐 owner/epoch fencing、
旧 worker 迟到写拒绝以及 commit 前/后进程退出恢复；该证据仍是 bounded disposable rehearsal，
不是已部署的多副本 reconciler。Temporal 与 PostgreSQL 同时故障、真实 worker lease lifecycle、
滚动升级、备份恢复、跨区 RPO/RTO、在线观测、HITL、incident 和 rollback 仍未完成。
