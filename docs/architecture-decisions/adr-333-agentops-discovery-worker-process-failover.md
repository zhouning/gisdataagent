# ADR-333：AgentOps Discovery Worker 进程故障接管与依赖恢复

## 状态

已采纳；两个独立 discovery worker 进程共享 PostgreSQL target authority 的 disposable
故障演练已通过。Docker Desktop Kubernetes 双副本、Pod replacement、依赖恢复、RollingUpdate
和 PDB 已由 ADR-335 验收；NetworkPolicy enforcement 和生产 HA 仍未完成。

## 背景

ADR-332 已把 Temporal start receipt 持久登记为 migration 242 target，并实现 claim、renew、
过期接管和 stale worker fencing。此前 PostgreSQL 演练直接调用 authority，尚未证明运行中的
discovery worker 能在长时间 input observation 期间续租，也没有证明进程被强制终止后，另一
个进程能够接管同一 target。Temporal frontend 健康检查和 status/readiness 已有实现，但也缺少
一次“故障降级、恢复后下一周期成功”的联合证据。

## 决策

- discovery worker 继续使用 migration 242 的 PostgreSQL claim lease。观察 workflow input 和
  history 时保持 heartbeat；进程死亡后不提前回收，必须等最后一次已提交的 claim 到期。
- 接管 worker 只能在旧 claim 到期后领取 target。旧 worker 持有的 target snapshot 不能再执行
  attach、release 或 complete；三条写路径都由数据库 worker identity 和 lease expiry 拒绝。
- input/history observation 的 Temporal transport failure 视为可恢复依赖故障。仍持有 claim 的
  worker 将 target 释放回 pending/ready 并记录错误，不重复 start，也不伪造 provider run。
- 每个 discovery cycle 在 claim 前检查 Temporal frontend health。health failure 将本地 readiness
  状态置为 degraded，并且不领取 target；依赖恢复后下一周期重新检查并恢复 ready。
- 继续复用 PostgreSQL control/evidence ledger，不新增 queue、scheduler、CQRS 或 event sourcing。
  当前负载和故障语义不需要另一套交付状态权威。

## 取舍

数据库租约让 target 状态、租约和 evidence 共享一个事务边界，也能复用 RLS 与现有 fencing；
代价是接管延迟至少等于最后一次 lease 剩余时间，吞吐上限仍受 PostgreSQL claim 查询约束。
若后续容量测试证明单库 claim 成为瓶颈，再以测得的吞吐和恢复目标评估分片或外部队列。

## 验证结果

disposable PostgreSQL 演练通过 11/11：

- worker A 在 observation 延迟期间续租，随后以 `SIGKILL` 终止；
- worker B 在 live lease 期间不能领取，到期后接管同一 target；
- 模拟 Temporal 网络故障安全释放 target，恢复后下一进程完成 input attach 和 checkpoint
  reconciliation；
- target 最终 attempt count 为 3，provider run 只绑定一次，reconciliation evidence 只有 1 条；
- worker A 的 stale attach、release、complete 均被数据库拒绝；
- frontend health failure 使 readiness degraded 且不 claim，恢复后的下一周期回到 ready。

证据：

- [rehearsal implementation](../../data_agent/agentops_temporal_discovery_worker_postgres_rehearsal.py)
- [contract tests](../../data_agent/test_agentops_temporal_discovery_worker_postgres_rehearsal.py)
- [runner](../../scripts/rehearse_agentops_temporal_discovery_worker.py)
- [report](../reports/agentops_temporal_discovery_worker_postgres_rehearsal_2026-08-27.json)

报告内部 SHA-256：
`66c0b38fc51ec69665a060d51f9493b0105345de80b78262dd67087e0151d619`。

## 未关闭边界

这份报告本身只证明本机两个独立 Python 进程和临时 PostgreSQL database 的 bounded recovery。
后续 Docker Desktop Kubernetes 证据见 ADR-335；该证据仍未覆盖业务 target lease takeover、
跨节点调度、NetworkPolicy 强制执行、数据库 failover/restore、跨可用区 HA、RPO/RTO、容量 SLO
或 staging/production rollout，完成这些退出门之前不得把 AR-5 标记为生产就绪。
