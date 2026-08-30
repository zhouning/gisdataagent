# ADR-098: Governed DataOps Cancel and Terminal Callback Isolation

**Status**: Accepted  
**Date**: 2026-08-01  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1

## Context

`DolphinSchedulerAdapter.cancel()` 原先可以直接调用 provider STOP，但平台没有取消请求合同、
独立授权证据、原子 Run 状态迁移、outbox 命令或 HTTP 边界。通用 Run transition API 还允许
调用者绕过 provider，直接写入 `cancelling`/`cancelled`。另一方面，provider callback 在 Run
终态后仍会创建 reconcile command；consumer 虽然会跳过终态 Run，但账本没有显式区分迟到
observation 与可执行 reconcile。

## Decision

### Stable Request Identity

`POST /api/platform/v1/runs/{run_id}/cancel` 只接受已认证 human platform role。tenant、requester
从 session 派生，workload 和 policy evaluator 从服务端 profile 派生。`tenant_id + run_id +
client_request_id` 形成稳定 retry identity、command ID 和 advisory lock；完整请求、CAS version、
reason 与服务端 profile 单独形成 immutable request fingerprint。同一 identity 的载荷漂移必须
conflict。

通用 transition API 拒绝 `cancelling` 和 `cancelled`，防止绕过该入口。

### Independent Cancel Authorization

取消不得复用 dispatch policy。gateway 为同一 Run resource scope 生成 action 为
`dolphinscheduler.cancel` 的独立 immutable PolicyDecision Artifact，evaluator 必须独立于 Run
workload，未知 obligations 继续 fail closed。adapter 在 STOP 投递时重新验证 artifact、execution
plan、Run scope、有效期和 configured evaluator。

### Atomic Admission and Delivery

`PlatformGateway.admit_dataops_cancel()` 在一个 tenant-scoped PostgreSQL 事务中：

1. 获取 request advisory lock 并加载 Run、dispatch policy 和 execution plan；
2. 校验 `expected_state_version`，只接受 `dispatching`、`running` 或 `reconciling`；
3. 写 cancel PolicyDecision Artifact；
4. 通过 security-definer CAS transition 写入 `cancelling` 和 RunEvent；
5. 写确定性的 `dolphinscheduler.cancel` outbox command。

任一步失败全部回滚。gateway role 仍只有 `SELECT/INSERT`，不因取消增加表级 UPDATE 权限。

consumer 以 Run workload identity 调 provider STOP。STOP 交付后，它在同一事务中完成 cancel
command 并创建 reconcile command。`READY_STOP` 等非终态继续通过既有 outbox delivery backoff
reconcile；只有 provider `STOP` observation 才允许 `cancelling -> cancelled`。`SUCCESS`、
`FAILURE` 或 `PAUSE` 不等价于取消成功；它们按
[ADR-099](adr-099-data-incident-and-cancellation-convergence.md) 形成 DataIncident，并把 Run
fail closed 为 `failed`。

### Terminal Callback Isolation

认证 callback 继续作为 immutable FrameworkAttemptObservation 留证。若 Run 已是 terminal，gateway
返回 `ignored_terminal=true`，不创建 reconcile command。若 callback 与并发终态迁移竞态，consumer
仍在 provider 调用前检查 terminal Run，任何后续 CAS 也不能从 terminal 状态推进。

## Evidence

- migrations `097_platform_cancel_command` 与 `098_platform_data_incident` 已应用；本机 Compose
  ledger 为 100/100、strict、in sync。
- 相关合同/gateway/adapter/worker/migration 测试 195 项通过，3 项在无数据库的本地进程跳过；真实
  PostgreSQL 集成 2 项通过，覆盖 RLS、并发双提交、载荷漂移、原子状态/outbox、cancel follow-up
  reconcile 和终态迟到 callback 零命令。
- 首轮 sandbox Run `874b4da8-7cdd-5ab5-aa75-bfb97df604b2` / instance `6` 证明 STOP API 被接受，
  但官方 3.4.2 standalone 镜像缺少 `pstree`，worker 无法枚举并终止 shell 进程；实例在观察窗内
  为 `READY_STOP`，随后自然结束为 provider `SUCCESS`。当时平台保持 `reconciling`，未创建
  DataProductVersion；ADR-099 落地后已基于原 observation 收敛为 `failed`，并创建 incident
  `09674ef6-fac8-5a51-9adc-50a478c6b27d`。原始 blocked 证据归档在
  `.tmp/dolphinscheduler-sandbox/cancel-v1/governed-cancel-rehearsal-report-pstree-missing.json`。
- sandbox 镜像补入 `psmisc` 后，新 Run `7ce30152-147c-5cab-b68d-8acb6ec3e48a` / instance `7`
  成功以 SIGINT 终止进程树；DolphinScheduler 却把 exit `130` 投影为 task/workflow `FAILURE`，
  而不是 `STOP`。平台未误标 `cancelled`；ADR-099 落地后已基于原 observation 收敛为 `failed`，
  并创建 incident `0ed1097c-56bc-5f9c-b968-9911d03c1517`。证据在
  `.tmp/dolphinscheduler-sandbox/cancel-v1/governed-cancel-rehearsal-report-pstree-fixed-provider-failure.json`。
- 上游 [issue #18311](https://github.com/apache/dolphinscheduler/issues/18311) 与相关 PR
  [#18312](https://github.com/apache/dolphinscheduler/pull/18312)、
  [#18367](https://github.com/apache/dolphinscheduler/pull/18367) 截至本 ADR 更新时仍为 open；因此真实
  provider terminal cancel **未验证**，平台不得将 `FAILURE` 推断成取消成功。

该 cancel probe 是 provider conformance 长任务，不宣称读取重庆数据。真实数据质量链仍由重庆
JQDLTB 1,555 条全量扫描的 manual/backfill/schedule-window Runs 提供，两种证据不得互相替代。

## Consequences

- 控制面不再允许“API 写 cancelled”或“provider 接受 STOP 即 cancelled”的乐观终态。
- callback 的审计保留与状态推进解耦，迟到消息不能复活产品状态。
- provider 非 `STOP` 终态和取消对账重试耗尽不再无限停留于 `reconciling`；DataIncident 的
  确认/解决也不会改写终态 Run。详细生命周期见 ADR-099。
- 仍需采用已发布且经本平台 conformance 验证的 DolphinScheduler 修复版本，解决 shell kill 后
  `FAILURE`/`READY_STOP` 语义，再在真实 DataOps workflow 上完成 terminal cancel、告警和故障
  注入验收；不得在 provider adapter 内把 `FAILURE` 特判为 `STOP`。semantic retry 也仍未实现。
- 本 ADR 不证明 DolphinScheduler HA、OIDC/workload identity、metadata backup/restore 或 AR-1
  退出。
