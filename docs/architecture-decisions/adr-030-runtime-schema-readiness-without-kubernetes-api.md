# ADR-030：运行时以数据库 Ledger 判断 Schema Ready

**Status**: Accepted

**Date**: 2026-07-26

**Decision owners**: Platform Architecture, Data Platform, SRE, Security

**Related decisions**: ADR-018、ADR-029

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

Kubernetes base 原本同时设置 `automountServiceAccountToken: false`，又让 App 和 Outbox Worker 的 init container 运行 `kubectl wait` 查询 migration Job。运行时因此必须重新挂载 ServiceAccount token 并获得 Job 只读 RBAC，导致清单声明与真实 Pod 安全边界矛盾。

migration Job 完成也不是应用真正需要的事实。应用需要的是：当前镜像携带的 checksummed migration catalog 与目标数据库 ledger 完全一致。Job 状态可能过期、被 TTL 清理，或属于不同 revision；数据库 ledger 才是 schema readiness 的权威。

## Decision

1. migration Job 继续作为唯一 schema 写 authority，以管理员数据库角色执行 `migration_runner migrate`。
2. App 和 Outbox Worker 的 `wait-for-migrate` init container 改为使用同一应用镜像，以普通应用数据库角色执行 `python -m data_agent.migration_runner status`。
3. init container 显式清空 `POSTGRES_ADMIN_USER` 和 `POSTGRES_ADMIN_PASSWORD`。ledger 不为 `in_sync` 时进程非零退出，由 Kubernetes 重试且运行容器不会启动。
4. App 和 Outbox Worker 固定 `automountServiceAccountToken: false`，删除仅为查询 migration Job 存在的 Role 和 RoleBinding。
5. 外部部署脚本仍可等待 migration Job 以提供运维反馈，但运行 Pod 不依赖 Job API 或其生命周期。

## Consequences

- schema readiness 与数据库权威直接对齐，不再把 Kubernetes Job 状态当作 schema 事实；
- App 和 Outbox Worker 无 Kubernetes API token、无业务所不需要的 RBAC；
- catalog pending、ledger drift 或数据库不可达时 fail closed；
- init container 与主容器使用同一镜像，registry digest 能覆盖 schema verifier 的代码 revision。

## Verification

- Docker Desktop 实测 App/Outbox 新 Pod 均 `1/1 Running`、零重启；
- 两个 init container 均以应用角色读取到 97/97 `in_sync` ledger；
- 两个运行容器内均不存在 `/var/run/secrets/kubernetes.io/serviceaccount/token`；
- live collector 重新采集得到 `automount_service_account_token=false`；
- 定向测试固定普通角色、管理员凭据清空、无 Role/RoleBinding 和 token automount 合同。
