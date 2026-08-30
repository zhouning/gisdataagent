# ADR-330：AgentOps Temporal Reconciler 租约、Fencing 与崩溃恢复

- **状态**：已采纳，disposable PostgreSQL 技术基线已验证；worker heartbeat/接管由 ADR-331 补齐，生产 rollout 未完成
- **日期**：2026-08-27
- **范围**：AR-5 AgentOps Runtime

## 背景

ADR-329 已把 GDA checkpoint 和 Temporal reconciliation evidence 放入 PostgreSQL append-only
authority，但 predecessor CAS 只能保证 checkpoint 链不被覆盖，不能阻止一个已失去执行权的
reconciler 在新副本接管后继续提交迟到结果。进程还可能在数据库提交前或提交后退出：前者必须
完整回滚，后者不能因调用方没有收到返回值而盲目重写。

本决策只处理 GDA checkpoint/evidence writer 的并发所有权和未知提交恢复。Temporal 仍然拥有
workflow execution history；GDA 不复制 Temporal 的调度、history 或 worker ownership。

## 方案选择

| 方案 | 结论 | 原因 |
|---|---|---|
| PostgreSQL 租约行 + 单调 fencing epoch | 采用 | 所有权核验与 checkpoint/evidence append 可在同一数据库事务和行锁内完成 |
| 只用进程锁或 Kubernetes leader election | 不采用 | 无法在数据库写入点拒绝已经失去 leadership 的旧进程 |
| 只依赖 lease expiry，不携带 epoch | 不采用 | 旧 worker 的延迟请求无法与同一 owner 名称的新一代租约区分 |
| 为此引入 event sourcing、CQRS 或新 scheduler | 不采用 | 不增加当前写入安全性，并会与 PostgreSQL authority 和 Temporal 边界重叠 |

## 决策

新增 migration `241_agentops_temporal_reconciler_fencing.sql`：

1. 每个 tenant/workflow 只有一行 mutable reconciler lease。首次获取签发 epoch 1；活跃租约只能由
   同一 owner 续期；租约到期后的接管原子递增 epoch。epoch 不因 renew 或 release 改变。
2. fenced checkpoint/reconciliation 写入必须携带数据库签发的 owner 和 epoch。写函数先锁定租约行，
   并在同一事务内核验 tenant、workflow、owner、epoch 和 expiry；核验失败返回 conflict，旧 worker
   不能进入 append-only authority。
3. migration 241 撤销 gateway 对 ADR-329 两个无租约写函数的执行权，只授予 acquire、renew、
   release 和两个 fenced write gateway 的执行权。gateway 对 lease 和 binding 表没有直接写权限。
4. 每个成功的 checkpoint 和 reconciliation write 都原子追加一条不可变 lease binding，记录
   write SHA-256、owner、epoch 和 bound time。相同 write 只有在 binding 也相同时才可幂等返回；
   不同 epoch 不能重新认领旧写入。
5. `resolve_checkpoint_write()` 和 `resolve_reconciliation_write()` 以预期 document 的精确 hash 查询
   append-only record 与 lease binding。调用方在提交结果未知时只做读取恢复，不自动重写，也不重发
   Temporal activity 或其他副作用。
6. lease 只决定哪个 GDA reconciler 可以写 checkpoint/evidence，不改变 Temporal execution authority、
   GDA predecessor CAS、typed contract、RLS 或不可变性边界。

## 崩溃语义

- 写入后、commit 前进程退出：数据库连接中断后事务回滚，checkpoint 和 lease binding 均不存在。
- commit 后、调用方收到返回值前进程退出：checkpoint 和 binding 已同时提交；新进程以精确 hash
  读取并恢复原 sequence/owner/epoch，不产生第二条写入。
- lease 到期后由新 worker 接管：epoch 递增；旧 worker 即使保留原 token，迟到写仍在数据库写入点
  被拒绝。

## 验收证据

实现与入口：

- [migration 241](../../data_agent/migrations/241_agentops_temporal_reconciler_fencing.sql)
- [PostgreSQL authority](../../data_agent/agentops_temporal_checkpoint_authority.py)
- [演练实现](../../data_agent/agentops_temporal_reconciler_fencing_postgres_rehearsal.py)
- [演练入口](../../scripts/rehearse_agentops_temporal_reconciler_fencing.py)

disposable PostgreSQL 演练复用 ADR-328 的真实 checkpoint/observation/reconciliation 文件。worker A
获得 epoch 1，活跃期内 worker B 被拒绝；两个独立子进程分别在 commit 前和 commit 后退出；租约到期
后 worker B 以 epoch 2 接管，worker A 的迟到 checkpoint 被拒绝。最终保存 2 个 checkpoint、2 条
reconciliation，14 项检查全部通过，包括 RLS、无租约 gateway 撤权、renew/release、跨租户隐藏、
binding 不可变和 release 后 token 拒绝。

报告：[agentops_temporal_reconciler_fencing_2026-08-27.json](../reports/agentops_temporal_reconciler_fencing_2026-08-27.json)，
`report_sha256=6fed4f66c13eca393d999d5c7ffb450d0035ea77ccf079b4c4f253a3735295f3`。

本切片相关测试 `7 passed, 1 skipped`；其中 skip 是未注入 `DATABASE_URL` 时的真实数据库测试。
真实演练已通过独立命令执行，不以该 skip 代替 PostgreSQL 证据。

## 边界与下一步

这份证据关闭的是临时 PostgreSQL、单 workflow、两个逻辑 worker、短租约下的数据库写入安全和
进程崩溃窗口，不等于多副本 reconciler 服务已经部署。ADR-331 已把 acquire/heartbeat/fenced
write/release 接入 managed worker，并验证一个独立进程被 `SIGKILL` 后的 epoch 接管；该演练仍使用
已保存的真实 Temporal observation，不是 live Temporal/PostgreSQL 组合故障。Kubernetes 多副本竞争、
滚动升级、数据库连接分区、备份恢复、跨区 RPO/RTO、在线观测、HITL、incident 和 rollback 未完成。

migration 241 会立即撤销旧 gateway 写权限，生产 rollout 必须把 schema/app 兼容顺序、worker drain
和 rollback procedure 纳入变更计划。下一步建立持久 target registration/work discovery，再做 live
Temporal + PostgreSQL、多副本终止/网络分区与数据库恢复演练。
