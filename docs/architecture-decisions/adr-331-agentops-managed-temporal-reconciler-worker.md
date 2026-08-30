# ADR-331：Managed AgentOps Temporal Reconciler Worker

- **状态**：已采纳，worker heartbeat 与进程接管的 disposable PostgreSQL 基线已验证；work discovery、live Temporal 联合演练和生产 rollout 未完成
- **日期**：2026-08-27
- **范围**：AR-5 AgentOps Runtime

## 背景

ADR-330 已在 PostgreSQL 写入口实现 owner/epoch fencing，但当时只有 repository 和故障演练直接调用
lease API。没有实际 worker 负责 acquire、观察期间 renew、fenced reconciliation write、未知提交恢复
和 graceful release，因而无法证明长时间读取 Temporal history 时租约不会过期，也无法证明进程被
终止后接管者能够使用同一运行时代码继续工作。

## 方案选择

| 方案 | 结论 | 原因 |
|---|---|---|
| 每个 reconciliation cycle 短时租约，观察期间 heartbeat | 采用 | 在慢 provider read 期间保持所有权，cycle 后释放，不长期阻塞 checkpoint writer |
| worker 启动后永久持有 workflow 租约 | 不采用 | 单 target worker 空闲时仍占用写权，不利于 checkpoint producer 和滚动升级 |
| 仅依赖 Kubernetes leader election | 不采用 | 不能替代数据库写入点的 epoch 校验，也不能处理旧进程迟到请求 |
| 新增 reconciliation scheduler/消息队列 | 暂不采用 | 当前切片只有明确 target；先验证 worker lifecycle，work discovery 单独设计 |

## 决策

新增 `AgentOpsTemporalReconcilerWorker`：

1. worker target 必须显式绑定 tenant、Temporal namespace、workflow id 和 provider run id；启动配置还
   固定 frontend、typed workload/agent identity、lease TTL、heartbeat、observation timeout 和 poll
   interval。checkpoint namespace 与配置不一致属于硬配置错误，进程 fail closed。
2. 每轮先获取 PostgreSQL lease，再读取当前 checkpoint。读取 Temporal history 时独立 heartbeat
   task 按小于半个 lease TTL 的周期续租；续租失败会取消仍在执行的 observation，本轮不得写证据。
3. provider observation 有显式 timeout。临时 Temporal/database 错误结束本轮并等待下一轮；配置
   漂移不进入永久重试。
4. reconciliation 仍使用 ADR-328 的 provider-neutral `reconcile_temporal_checkpoint()`。写入使用
   ADR-330 的 fenced gateway；数据库在同一事务再次核验 owner/epoch/expiry，进程内 heartbeat 不是
   最终安全边界。
5. 写入前先按 observation/reconciliation 精确 hash 查询已有 immutable binding。这样新 epoch 接管
   后可读取确认旧 epoch 已提交的同一证据，不会为了幂等重放重新认领旧 write。写入返回未知时同样
   先做精确只读恢复。
6. cycle 完成或正常失败后 graceful release；heartbeat 已失败时不再尝试使用可能过期的 token，等待
   数据库 TTL 释放所有权。

## 验收证据

实现与测试：

- [managed worker](../../data_agent/agentops_temporal_reconciler_worker.py)
- [worker tests](../../data_agent/test_agentops_temporal_reconciler_worker.py)
- [多进程 PostgreSQL 演练](../../data_agent/agentops_temporal_reconciler_worker_postgres_rehearsal.py)
- [演练入口](../../scripts/rehearse_agentops_temporal_reconciler_worker.py)

单元层覆盖慢 observation 持续 renew、heartbeat 丢失后零写入、exact existing write 恢复、未知提交
恢复、namespace drift、配置边界和 Temporal 暂时错误的下一轮重试。

disposable PostgreSQL 演练启动独立进程 A。A 获得 epoch 1 后在 observation 阶段持续 heartbeat；数据库
实际观察到 5 个不同的 `lease_updated_at`，超过原始 TTL 后进程 B 仍被拒绝。随后 A 被 `SIGKILL`
（exit `-9`），最后一次续租到期后 B 以 epoch 2 接管，使用正式 worker 代码写入一条 `matched`
reconciliation 并释放租约；A 的 epoch 1 迟到写被拒绝，最终没有重复 evidence。9 项真实数据库检查
全部通过。

报告：[agentops_temporal_reconciler_worker_2026-08-27.json](../reports/agentops_temporal_reconciler_worker_2026-08-27.json)，
`report_sha256=fb75f5c117b687fa83683743a8bc60d9559582cfbd1136e061a54d06b74966f1`。

## 取舍与边界

本切片刻意不新增 reconciliation queue 或 scheduler。当前 worker 一次只处理显式配置的一个 provider
run；这能验证 lease lifecycle，但不是生产 work discovery。演练中的 observation 来自 ADR-328
已经由真实 Temporal `1.29.7` 生成并保存的 immutable 文件，本次没有同时连接 live Temporal server。

因此该证据不代表 Kubernetes 多副本 Deployment、动态 target registration、网络分区、Temporal 与
PostgreSQL 组合故障、滚动升级、worker image、OIDC、备份恢复、HA 或 RPO/RTO 已完成。下一步先建立
start receipt 到 reconciliation target 的持久登记/claim 边界，再运行 live Temporal + PostgreSQL
双后端、两个 worker 副本的终止与网络分区演练。
