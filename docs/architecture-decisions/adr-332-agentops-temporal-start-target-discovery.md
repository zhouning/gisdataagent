# ADR-332：AgentOps Temporal Start Target 持久登记与 Work Discovery

## 状态

已采纳；migration 242、target authority、discovery worker、disposable PostgreSQL 演练和
live Temporal + PostgreSQL sandbox 联合演练已完成。discovery worker 现在带有原子状态文件、
readiness/liveness CLI 探针和 Prometheus metrics Service；另有显式 two-replica discovery
overlay（RollingUpdate + PDB）供 disposable rehearsal 使用。Kubernetes 多副本和生产 rollout
仍未完成。

## 背景

ADR-325/326 已规定：Temporal start 返回 `started`、`already_exists` 或 `unknown`
时，GDA 必须保留完整 request/result receipt；`unknown` 不能直接当作已有 provider run，
必须观察 Temporal 首个 `WORKFLOW_EXECUTION_STARTED` input 并校验 fingerprint。ADR-329 至
331 已解决 checkpoint/reconciliation 的 PostgreSQL 持久性、lease epoch 和 managed
reconciler 生命周期，但 worker 仍需要在启动配置中指定单个 workflow，start receipt 没有
进入可发现的工作集合。

## 决策

新增 `gda_control.agentops_temporal_start_target`（migration 242）作为 start gateway
到 managed reconciler 的持久交接对象：

- 保存 tenant、namespace、workflow id/type、task queue、idempotency key，以及完整的
  `TemporalWorkflowStartRequest`、`TemporalProviderStartResult` 和可选
  `TemporalStartReconciliation` 原文与 SHA-256；request/result/已结算 reconciliation
  证据不可变。
- target 状态为 `pending_start_reconciliation`、`ready`、`claimed`、`completed`、
  `failed`。`unknown` 或 `unknown_pending` 只能进入 pending；没有 provider run 时不
  允许进入 ready/completed。
- `claim ... FOR UPDATE SKIP LOCKED`、claim lease、renew、lease expiry recovery、
  attach provider run、retry、complete/fail 都由 `SECURITY DEFINER` 函数提供；表启用
  RLS/FORCE RLS，gateway 无直接 INSERT/UPDATE 权限。
- `unknown` target 被领取后只能调用 observation-only 的
  `observe_workflow_input()`。tenant、namespace、workflow 和 start request input
  fingerprint 匹配时才写入 provider run 和 `already_exists_matched` evidence；观察失败
  或 drift 保持 pending，不能自动重新 start。
- discovery worker 领取 target 后复用 ADR-331 的 checkpoint/reconciliation worker，
  所有 history evidence 写入继续经过既有 reconciler lease/fencing。没有 GDA checkpoint
  的 target 只释放 claim 等待下一轮，不能被标记完成。
- `TemporalWorkflowAdapter.start_and_register[_async]()` 是 start receipt 登记入口；
  它不重试 provider start，不创建第二个 scheduler 或消息队列。显式单 target worker
  入口继续保留，用于兼容、迁移和故障定位。

## 取舍

选择既有 PostgreSQL control/evidence ledger，而不是新增队列、event sourcing、CQRS 或
独立 scheduler。这样 claim、审计、RLS 和现有 checkpoint fencing 共用同一数据库边界，
但 discovery 吞吐受 PostgreSQL claim 查询和单库容量约束；只有真实负载证明不足时，才按
ADR-007/AR-8 评估外部队列或分片。

## 证据

- [target authority](../../data_agent/agentops_temporal_start_target_authority.py)
- [migration 242](../../data_agent/migrations/242_agentops_temporal_start_target_authority.sql)
- [discovery worker](../../data_agent/agentops_temporal_reconciler_worker.py)
- [unit contracts](../../data_agent/test_agentops_temporal_start_target_authority.py)
- [PostgreSQL rehearsal](../../data_agent/agentops_temporal_start_target_postgres_rehearsal.py)
- [rehearsal report](../reports/agentops_temporal_start_target_postgres_rehearsal_2026-08-27.json)
- [live rehearsal](../reports/agentops_temporal_start_target_live_rehearsal_2026-08-27.json)
- [discovery worker process failover](adr-333-agentops-discovery-worker-process-failover.md)
- [process failover report](../reports/agentops_temporal_discovery_worker_postgres_rehearsal_2026-08-27.json)
- [sandbox discovery deployment](../../k8s/optional/temporal-agentops-sandbox/discovery-worker.yaml)
- [GDA control access policy](../../k8s/optional/temporal-agentops-discovery-control-access/networkpolicy.yaml)

真实 PostgreSQL disposable 演练 6/6 通过：start receipt 重放幂等、live claim 排他、过期
claim 接管、unknown -> input matched 收敛、旧 worker 不能结算。报告 SHA-256：
`a49f86e6562618b4db91d4dd7eddd57f1c078fc46122111ad0901bccaf5c38cd`。

## 未关闭边界

live Temporal + PostgreSQL sandbox 联合演练 5/5 通过：真实 start 后 transport uncertainty、
`unknown` receipt、PostgreSQL claim、真实 `WORKFLOW_EXECUTION_STARTED` input observation、
input hash 匹配后的 provider run 绑定，以及无 GDA checkpoint 时保持 `ready`。报告：
[live rehearsal](../reports/agentops_temporal_start_target_live_rehearsal_2026-08-27.json)，
SHA-256 `83a2339ac8b976a24ffb751b761288a9fe3339a86126cd1dd17c7fd1e87a8fe3`。

当前证据仍只覆盖 disposable PostgreSQL/Temporal 单副本 sandbox；部署清单已定义默认关闭的
discovery Service、metrics ServiceMonitor、状态文件探针和监控入口；另有
`k8s/overlays/temporal-agentops-discovery-sandbox` 将 discovery 显式调为两个副本、
RollingUpdate 和 PDB，但尚未在集群中启用 discovery 副本。ADR-333 已补齐两个独立本机
进程共享 PostgreSQL authority 的 heartbeat、`SIGKILL`、过期接管、依赖失败释放和恢复，
该报告通过 11/11，内部 SHA-256 为
`66c0b38fc51ec69665a060d51f9493b0105345de80b78262dd67087e0151d619`；它不是集群 HA 证据。
Kubernetes 多副本终止、网络分区、滚动升级、backup/restore、HA、RPO/RTO 和生产
identity/secret rollout 仍未关闭。
