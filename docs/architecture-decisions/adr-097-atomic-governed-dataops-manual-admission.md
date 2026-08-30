# ADR-097：受治理 DataOps 人工触发的原子准入与身份委托

**Status**: Accepted

**Date**: 2026-08-01

**Decision owners**: Data Platform, Data Governance, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1

**Related decisions**: [ADR-003](adr-003-unified-orchestration-and-job-control-plane.md) ·
[ADR-007](adr-007-dolphinscheduler-temporal-orchestration-platform.md) ·
[ADR-095](adr-095-governed-dataops-invocation-and-backfill.md) ·
[ADR-096](adr-096-atomic-dataops-schedule-window-admission.md)

## Context

通用 Run API 可以把认证 principal 直接写入 `PlatformRun.subject_context`，但人工 DataOps
请求不能让 human identity 充当 DolphinScheduler executor，也不能允许请求体自行声明 tenant、
requester、workload 或 policy evaluator。人工提交还需要一个跨进程重启稳定的 retry identity；
若同一请求 ID 被绑定到不同窗口、输入、definition 或 execution plan，平台必须拒绝，而不是创建
第二个 Run。

人工入口不得直接调用 provider，不得新增进程内 background task、队列或第二调度器。它应复用
ADR-096 已验证的 PostgreSQL 原子准入与 transactional outbox。

## Decision

### 1. `client_request_id` 是稳定重试身份

`DataOpsManualTriggerSpec` 要求 tenant-scoped `client_request_id`。tenant 和 request ID 形成稳定的
request identity、advisory lock、Run ID 和 idempotency key；完整不可变 payload 另形成 request
fingerprint。首次准入时间不参与 retry identity。

`client_request_id`、human requester、UTC 半开逻辑窗口和首次数据库准入时间进入不可变
DataOps invocation `ResourceVersion`。同一 tenant/request ID 重放时，Gateway 从已存 invocation
恢复首次 `admitted_at` 并重建全部对象；任一不可变字段不同都返回 conflict。request ID 跨 tenant
不会共享 Run 身份。

### 2. Human requester 与 workload executor 分离

人工 API 从认证 session 派生 tenant 和 `human:<subject>`，请求体不接受这些字段。workload、
workload roles、policy evaluator、policy version 和 invocation owner 只从服务端 admission profile
读取；配置缺失或 evaluator 与 executor 相同均 fail closed。

invocation 的 `requested_by` 保存 human requester。`PlatformRun.subject_context` 使用
`workload:<executor>`，并通过 `delegated_by` 绑定 requester。策略证据对这个 workload subject、
definition、所有输入（包括 invocation version）和 execution plan 求值。未实现执行语义的 policy
obligation 不写入证据；委托关系由现有授权器可完整比较的 `SubjectContext` 承载。

本决定不把应用 session 或 sandbox script 声明外推为生产 OIDC。生产身份 federation、token
audience、workload identity 和密钥轮换仍是 AR-1 退出项。

### 3. Gateway 在一个事务内完成准入

`PlatformGateway.submit_manual_trigger` 在 tenant-scoped 最小权限事务中：

1. 按 tenant/request ID 获取 `pg_advisory_xact_lock`。
2. 按确定性 Run ID 检查已有请求；这也使同一 request ID 更换 definition 时冲突关闭。
3. 使用数据库 `clock_timestamp()` 确定首次准入时间。
4. 原子写入 invocation Resource/ResourceVersion、policy Artifact、PlatformRun、input bindings 和
   DolphinScheduler dispatch outbox command。
5. 缺失 execution plan、授权不匹配或任一步失败时全部回滚，不留下孤立 invocation 或 Run。

advisory lock 只串行化同一人工请求的准入，不承担 worker lease、provider 状态或调度职责。

### 4. Provider correlation 包含人工请求身份

DolphinScheduler 仍通过 `START_PROCESS` 执行，收到 Run、tenant、definition、idempotency、
invocation version/hash、trigger kind、逻辑窗口和 `gda_client_request_id`。provider `SUCCESS` 只
表示执行完成；产品成功仍需要独立质量、Artifact 和血缘证据。

## 2026-08-01 Real-data Acceptance

重庆璧山 JQDLTB 人工请求窗口 `[2026-07-03, 2026-07-04)` 生成：

- client request ID `jqdltb-manual-20260801-001`
- request SHA-256 `89918fc791255d59741e02221817242554a5901eb507c7cd1710b055b203f022`
- PlatformRun `66815080-292b-591c-b161-623d961eadf5`
- invocation version `46988968-5470-5a25-8d32-2077d8206783`
- dispatch command `2414586f-860d-57d8-a09d-3a896a59c29f`
- DolphinScheduler instance `4`

human requester `human:data-platform-operator` 与 workload executor
`workload:dolphinscheduler-gda-dataops` 分离，`delegated_by` 可验证。provider 只有一个匹配实例，
`commandType=START_PROCESS`、`scheduleTime=null`，13 个 GDA/definition/source/manual correlation
变量完整。

实例为 `SUCCESS`，但 1,555 条真实要素的权威质量结果
`e665c90e-8f75-5629-90c1-982d7722e5d6` 为 `failed`，Run 终止为 `failed`，未创建
DataProductVersion。同一人工请求重放时所有原子对象均 `created=false`；终态重放也未新增
observation、assessment version、lineage 或状态迁移。

真实验收报告：
`.tmp/dolphinscheduler-sandbox/manual-v1/jqdltb-manual-acceptance-report.json`，13 项检查全部通过。
相关 control-plane/adapter/worker 测试 159 项通过；真实 PostgreSQL 的角色/RLS、并发双提交、
载荷漂移冲突和失败全事务回滚集成测试 2 项通过。

## Trade-offs

- client request ID 在 tenant 内不可改绑。调用者要执行不同窗口或输入，必须生成新的 request ID。
- 服务端 admission profile 使 API 调用者不能任选 executor，但 profile 的版本化发布、OIDC 绑定和
  多 executor placement 仍需后续实现。
- 当前 sandbox CLI 的 requester 是本地操作员声明，只用于真实数据执行验收；它不是生产身份
  认证证据。生产操作应走认证 API 或后续受签名的 workload delegation token。
- 人工触发已复用同一 outbox 和 provider adapter，但 DataOps UI、cancel、retry 和迟到回调仍未
  完成，不能据此宣称 AR-1 退出。

## Revisit Triggers

- 平台引入可验证的 OIDC token exchange 或 workload delegation token，需要将其不可变声明绑定
  到 invocation/decision Artifact。
- 同一人工请求需要审批后再投递，必须增加独立 Approval Artifact 和恢复协议，而不是修改首次
  invocation。
- manual placement resolver 支持多个 executor，需要把选择依据和 DeploymentProfile 版本加入
  request payload fingerprint。
