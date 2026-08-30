# ADR-334：AgentOps Discovery Sandbox 部署前置检查

## 状态

已采纳；镜像、manifest、控制库、Secret、跨 namespace policy 和部署后双副本检查的
检查方法已冻结。由于 specialist receipt authority 新增 migration 246，旧的 242/242
报告不能继续作为当前 preflight 证据；生产晋级仍为 blocked。

## 决策

在启用 `temporal-agentops-discovery-sandbox` 双副本 overlay 前，必须执行只读
`scripts/preflight_agentops_temporal_discovery_sandbox.py`。检查分为三组：

1. 渲染后的 overlay 必须包含 discovery 双副本、`RollingUpdate(maxUnavailable=0,
   maxSurge=1)`、`minAvailable=1` PDB、外置 runtime Secret 的两个 key 引用，以及单独的
   control-database NetworkPolicy；不得在仓库中内嵌 Secret。
2. 控制库必须提供授权的 `migration_runner status` JSON，并且 migration 240、241、242、246
   均已登记、无 checksum/metadata drift。preflight 不执行 migration，也不接收数据库密码。
   specialist Artifact backend 必须显式配置：filesystem 需要绝对 content/materialization
   路径，S3/MinIO 需要 bucket、绝对 materialization 路径和 `VersionId=true`。
3. 目标集群必须实际存在 sandbox namespace、runtime Secret（仅检查 key 名，不输出值）和
   跨 namespace policy。`ServiceMonitor` 属于独立的可选 observability package；只有启用该
   package 时才检查其 CRD。部署后复核再使用 `--expect-deployed` 要求 discovery Deployment
   为两副本且 `observedGeneration`、ready、available、updated 均收敛；同时读取实际
   ConfigMap，防止运行时 backend 配置漂移。部署前不把 Deployment 尚未创建误判为失败。
   集群观察失败直接阻断。

`--static-only` 只检查本地 manifest，适合 CI；默认模式才读取目标集群。Prometheus
`ServiceMonitor` 已拆为 `temporal-agentops-discovery-observability` 可选 package，不属于核心
worker 部署门。脚本不创建、更新或删除任何 Kubernetes 资源，因此通过它只代表“允许 operator
继续审核”，不代表部署成功。

## 证据

- [preflight script](../../scripts/preflight_agentops_temporal_discovery_sandbox.py)
- [preflight tests](../../data_agent/test_agentops_temporal_discovery_sandbox_preflight.py)
- [blocked static report](../reports/agentops_temporal_discovery_sandbox_preflight_2026-08-27.json)
- [live blocked preflight](../reports/agentops_temporal_discovery_sandbox_preflight_live_2026-08-27.json)
- [observed control-schema status](../reports/agentops_control_schema_status_2026-08-27.json)
- [242/242 control-schema status](../reports/agentops_control_schema_status_2026-08-28.json)
- [post-apply live preflight](../reports/agentops_temporal_discovery_sandbox_post_apply_preflight_live_2026-08-28.json)
- [Kubernetes runtime acceptance](adr-335-agentops-discovery-kubernetes-sandbox-runtime-acceptance.md)
- [server dry-run report](../reports/agentops_temporal_discovery_sandbox_server_dry_run_2026-08-27.md)
- [container contract tests](../../data_agent/test_agentops_temporal_container_contract.py)
- 通用 overlay 固定已验证镜像 digest
  `sha256:20a7c649473a81c874b5d9197aa92af62da2882d36407c2f17c3dc6f71e74a77`；Docker Desktop
  专用 overlay 使用同内容的本地 tag `gis-data-agent:agentops-discovery-20260827-v3`。

## 当前边界

截至 2026-08-28，历史部署后报告只覆盖 242/242；当前 worker 还要求 migration 246、显式
specialist Artifact backend 和可写 materialization mount，因此必须重新生成 schema status、
重新执行 preflight 并重新做 runtime acceptance，不能沿用旧报告。ServiceMonitor 继续作为可选
package；核心 metrics Service 已验收。Pod termination、Temporal 依赖中断、RollingUpdate 和
PDB 结果见 ADR-335。`kindnet` 无法执行 NetworkPolicy 流量隔离，业务 lease takeover、数据库
恢复、identity rotation、容量 SLO、HA、backup/restore 和 RPO/RTO 仍保持未通过。
