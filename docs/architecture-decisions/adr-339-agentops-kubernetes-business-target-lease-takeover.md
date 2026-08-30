# ADR-339：AgentOps Kubernetes 业务 target lease takeover

## 状态

已验证 bounded sandbox slice；不代表 staging/production readiness。

## 背景

ADR-333 验证了两个独立进程共享 PostgreSQL target authority 时的 claim heartbeat、
`SIGKILL` 后过期接管和 stale-worker fencing；ADR-335 验证了 Kubernetes discovery
Deployment 的双副本、Pod replacement、Temporal 依赖降级/恢复、RollingUpdate 和 PDB。
这两项证据仍没有把“真实业务 target 的 lease”放进 Kubernetes Pod 生命周期：没有证据证明
一个实际 workload claim 住 target 后被删除，lease 到期后另一个 managed discovery Pod 会重新
claim，并用 Temporal 的真实 history/input 完成同一个 start receipt 的收敛。

本 ADR 只补这一条业务故障边界。PostgreSQL 仍是 target lifecycle 的唯一权威，Temporal 只
提供 workflow start、history 和 input observation；Kubernetes 只提供 worker 生命周期和
进程身份。

## 决策

1. 演练使用 `gda-agentops-sandbox` 中现有的 Temporal `1.29.7`、Python SDK `1.32.0`、
   PostgreSQL 242 schema 和 `gis-agent-agentops-discovery` Deployment。
2. 注册一个提交后 transport uncertainty 的 Temporal start：provider 返回 `unknown`，但
   Temporal 已接受 start；PostgreSQL 写入完整 start request/result/reconciliation target。
3. 暂时将 managed discovery Deployment 缩到 0，创建一个使用同一镜像、runtime Secret、
   ServiceAccount、数据库连接和 NetworkPolicy-compatible discovery labels 的临时 holder Pod。
   holder 只调用现有 `claim_due_targets`，不复制或修改 target authority。
4. holder 成功 claim 后立即强制删除。恢复一个 managed discovery Pod，等待原 claim 的
   60 秒 lease 到期；新 Pod 通过 PostgreSQL 函数接管 target，读取 Temporal workflow history
   的 immutable input，写入匹配的 provider run/reconciliation evidence。
5. 报告同时保存机器可读 checks 和 Temporal `WorkflowHistory.to_json()`；报告 hash 与 history
   hash 均绑定，`production_readiness_claimed` 固定为 `false`。

## 结果

2026-08-28 在 Docker Desktop Kubernetes sandbox 完成一次真实演练：

- holder identity：`workload:agentops-discovery:gda-agentops-lease-holder-f18a15ffecb3`；
- takeover identity：`workload:agentops-discovery:gis-agent-agentops-discovery-6cd9699dcf-7b78x`；
- target attempt 从 `1` 变为 `2`，lease 等待 `61.481s`；
- target 从未知 start 注册、holder claim、holder Pod 终止、lease 过期到新 Pod 接管，最终
  `ready`；
- takeover worker 观察到的 Temporal input fingerprint 与 registered request 一致；真实
  Temporal history 含 5 个 events，并由 Temporal `Replayer` 重放通过；
- 11/11 checks 通过：`passed=true`，且没有把本次结果标记为生产就绪。

## 证据

- [业务 target rehearsal report](../reports/agentops_temporal_discovery_kubernetes_business_target_2026-08-28.json)
  （`report_sha256=bd1b259db7f5930143ef0be5199f2a788b81db1412130ab857b0ed855532262a`）
- [Temporal history export](../reports/agentops_temporal_discovery_kubernetes_business_target_history_2026-08-28.json)
  （canonical history hash=`e1c77efe3fde01fd798f38466f6ec2c8ab8a285c93e183f3633bd502c729cb68`）
- [rehearsal script](../../scripts/rehearse_agentops_temporal_discovery_kubernetes_business_target.py)
- [contract tests](../../data_agent/test_agentops_temporal_discovery_kubernetes_business_target.py)

## 保留边界

本证据只覆盖单 namespace、单 PostgreSQL、单 Temporal frontend、Docker Desktop sandbox 和
一次 lease takeover。它不覆盖 NetworkPolicy enforcement（当前 kindnet 不执行）、跨节点/可用
区、Temporal HA、数据库 failover/restore、Secret/identity rotation、容量 SLO、staging/
production rollout、backup/restore、RPO/RTO，也不关闭真实 MMFE/GWM provider、HITL 通知/升级、
shadow/canary、online verdict 或 incident/rollback 退出门。
