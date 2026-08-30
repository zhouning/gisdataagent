# ADR-335：AgentOps Discovery Kubernetes Sandbox 运行验收

## 状态

已采纳；Docker Desktop sandbox 运行门已通过，生产晋级保持关闭。

## 背景

ADR-333 已验证两个独立 Python 进程共享 PostgreSQL target authority 时的 claim 续租、进程
终止接管和 stale-worker fencing。ADR-334 冻结了 Kubernetes 部署前检查，但当时控制库仍是
97/97，双副本 Deployment、runtime Secret 和跨 namespace 数据库策略尚未落地。

本次将控制库迁移到 242/242，使用普通 `agent_user` 部署两个 discovery worker，并在实际
Kubernetes 生命周期中验证探针、metrics、Pod replacement、依赖故障恢复、RollingUpdate 和 PDB。

## 决策与结果

- 通用 overlay 固定镜像 digest
  `sha256:20a7c649473a81c874b5d9197aa92af62da2882d36407c2f17c3dc6f71e74a77`。
  Docker Desktop 专用 overlay 使用同一构建内容的本地 tag 和 `imagePullPolicy: Never`，不进入
  staging/production。
- 控制库 schema ledger 为 242/242，catalog/database fingerprint 同为
  `a7b1688cdae830ae4d42bb97fc533011eee14a0564ff7cf8344a005296992636`；runtime role 没有
  migration ledger 或 AgentOps target 表的直接写权限，写入继续经过受控函数。
- post-apply preflight 在 `--expect-deployed` 下通过；两个 worker 状态为 ready，Temporal
  frontend 可达，cycle 和 last-success metrics 持续更新。
- 删除一个 worker 后，Service ready endpoint 最低为 1，约 7 秒补回新 Pod；存活 worker 的
  discovery cycle 继续增长。由于 `local-dev` 没有 due target，本次只确认 Pod replacement，
  不登记为业务 lease takeover。
- Temporal deployment 临时缩到 0 后，worker 进入 degraded，readiness 失败、liveness 保持；
  Temporal 恢复后 worker 无需重启即可回到 ready。
- RollingUpdate 全程至少保留两个 ready/available Service endpoints，最大 Pod 数为 3，符合
  `maxUnavailable=0,maxSurge=1`。
- PDB `minAvailable=1` 允许第一次 eviction；剩余一个健康副本时，第二次并发 eviction 被 429
  拒绝，Deployment 随后补回两个副本。

## NetworkPolicy 验收边界

当前 Docker Desktop 集群使用 `kindnet`。该 CNI 不强制执行 Kubernetes NetworkPolicy，因此
本环境只能验证策略对象、selector、namespace 和端口合同，不能验证实际丢包。ADR 不接受通过
修改 policy YAML 后仍然可达的结果，也不把 Temporal 缩容故障写成网络分区。

NetworkPolicy 流量隔离仍需在启用 Cilium、Calico 或等价 enforcement 的目标环境执行：阻断
discovery 到 Temporal 7233 和 GDA PostgreSQL 5432，分别观察 readiness 降级、liveness 保持、
零越权写入以及策略恢复后的自动恢复。

## 证据

- [控制库状态](../reports/agentops_control_schema_status_2026-08-28.json)
- [部署后 preflight](../reports/agentops_temporal_discovery_sandbox_post_apply_preflight_live_2026-08-28.json)
- [机器可读验收报告](../reports/agentops_temporal_discovery_kubernetes_sandbox_acceptance_2026-08-28.json)
- [验收摘要](../reports/agentops_temporal_discovery_kubernetes_sandbox_acceptance_2026-08-28.md)
- [通用双副本 overlay](../../k8s/overlays/temporal-agentops-discovery-sandbox/kustomization.yaml)
- [Docker Desktop overlay](../../k8s/overlays/temporal-agentops-discovery-sandbox-docker-desktop/kustomization.yaml)

机器可读验收报告 SHA-256：
`906355505e48afb22de4335ad5b507e568874b4b06e23046489d9d5dc9c27382`。

## 未关闭边界

业务 target 的 Kubernetes lease takeover、NetworkPolicy enforcement、跨节点/可用区调度、
数据库 failover/restore、Secret/identity rotation、容量 SLO、staging/production rollout、HA、
backup/restore 和 RPO/RTO 继续保持未通过。AR-5 仍有多智能体真实执行、HITL、shadow/canary、
online verdict、incident/rollback 和 UX uplift 等更大范围退出门，不能因本切片通过而整体关闭。
