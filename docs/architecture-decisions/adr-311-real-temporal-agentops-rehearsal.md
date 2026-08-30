# ADR-311: Real Temporal AgentOps Activity Rehearsal

状态：已验证 sandbox vertical slice；生产 AgentOps Runtime 未完成  
日期：2026-08-26  
决策关联：ADR-299、ADR-306、ADR-307、ADR-308、ADR-309、ADR-310

## 背景

ADR-310 已经把 activity schedule 固定为 hash-bound plan，并要求 Temporal SDK
`maximum_attempts=1`，但此前只有 provider-neutral 合同和 fake worker 证据。缺少一次真实
Temporal server、真实 Python SDK worker、真实 activity completion、history 导出和离线 replay
的闭环，无法确认 schedule 映射和 receipt/evidence 能在 provider 边界上工作。

## 决策

在独立 `gda-agentops-sandbox` namespace 使用 disposable Kubernetes profile，完成一条不
注册生产 workflow 的 rehearsal：

1. Server 使用 Docker Hub 实际存在的 `temporalio/auto-setup:1.29.7`，Python worker 使用
   锁定的 `temporalio==1.32.0`；Temporal metadata 使用独立 `postgres:16.4-alpine`。
2. Server 以 `postgres12` driver、内置 `config/dynamicconfig/docker.yaml` 和 `24h` retention
   启动；PostgreSQL/Temporal 容器显式使用官方镜像 UID/GID（70/70、1000/1000），避免
   `runAsNonRoot` 依赖非数字镜像用户名的不可验证行为。
3. 本机一次性 worker 通过 `TemporalioWorkerFactory` 注册独立 workflow
   `gda.agentops.rehearsal.v1` 和 activity `gda.agentops.rehearsal.activity`，task queue 为
   `agentops-gis-rehearsal`，worker identity 为 `workload:gda-agentops-rehearsal-v1`。
4. activity 复用 `TemporalActivityWorkerHandler`，生成确定性
   `TemporalProviderActivityResult`、receipt 和 `TemporalActivityEvidence`；workflow 只允许
   一次 SDK activity attempt，平台 schedule plan 保留 request/activity/schedule hash。
5. workflow 完成后导出原始 history JSON，再从导出 JSON 重建 `WorkflowHistory`，使用
   `Replayer` 离线 replay；history 必须包含恰好一个
   `EVENT_TYPE_ACTIVITY_TASK_SCHEDULED` 和一个 `EVENT_TYPE_ACTIVITY_TASK_COMPLETED`。

## 真实证据

报告与 history：

- [agentops_temporal_rehearsal_2026-08-26.json](../reports/agentops_temporal_rehearsal_2026-08-26.json)
- [agentops_temporal_rehearsal_history_2026-08-26.json](../reports/agentops_temporal_rehearsal_history_2026-08-26.json)

本次执行结果：

| 项目 | 结果 |
|---|---|
| Temporal server / Python SDK | `1.29.7` / `1.32.0` |
| Namespace / workflow / run | `gda-agentops-sandbox` / `gda.agentops.rehearsal.v1` / `gda-agentops-rehearsal-f01a8311-7e0b-4e98-88f1-193cc54040ec` |
| Provider run | `01a039fa-ee36-7b9d-ace6-830804b7efce` |
| Activity schedule / completion | `1` / `1` |
| SDK maximum attempts | `1` |
| History events | `11` |
| Workflow / worker shutdown | `0.079464s` / `0.043624s` |
| History replay | `passed` |
| Request / schedule / result / evidence / history / report hash | `628b9823...08aa6` / `42954234...927e` / `17ac7e43...ecb9` / `9c7c29f9...3b98` / `21a99fd8...f1db` / `e764b7bf...f1a8` |

离线合同与回归：Temporal scoped `47 passed`，完整 AgentOps `92 passed`；Ruff、py_compile、
`uv lock --check` 和 Kustomize render 通过。此次过程中 sandbox 还捕获并修正了五个部署
兼容问题：不存在的 server tag、PostgreSQL/Temporal 非数字用户校验、Temporal 1.29.7 的
`postgres12` driver 名称、dynamic config 路径以及 retention duration 格式；这些约束已写入
manifest contract tests。

## 边界与下一步

该 ADR 证明的是单次 sandbox `start -> schedule -> activity -> receipt -> history export ->
replay`。它不证明生产 worker image、生产 OIDC/workload identity、HITL signal、already-exists
对账、提交后 transport uncertainty、worker termination/restart、heartbeat/cancellation、
多副本 HA、backup/restore、RPO/RTO、online observation、incident/rollback、Agent bundle
评测或 MMFE/GWM 生产 rollout。下一切片是注入 worker termination 和提交后不确定结果，验证
checkpoint/reconciliation；之后再进入 AgentOps bundle deployment、online verdict、incident/
rollback 和 uplift gate。
