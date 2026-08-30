# ADR-095：受治理的 DataOps Invocation 与补数边界

**Status**: Accepted

**Date**: 2026-08-01

**Decision owners**: Data Platform, Data Governance, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1

**Related decisions**: [ADR-003 统一调度与作业控制面](adr-003-unified-orchestration-and-job-control-plane.md) · [ADR-007 DolphinScheduler + Temporal 编排平台](adr-007-dolphinscheduler-temporal-orchestration-platform.md)

**Schedule admission follow-up**:
[ADR-096](adr-096-atomic-dataops-schedule-window-admission.md)

## Context

DolphinScheduler 负责 DataOps process、task、queue 和 backfill，但 GDA 负责
`PlatformRun`、策略、Artifact、质量、血缘和最终 verdict。直接启用 DolphinScheduler
原生 cron 会产生没有 GDA Run、策略证据和唯一 correlation 的执行，破坏控制账本完整性。

固定版本 3.4.2 的 OpenAPI 还存在实现漂移：`start-workflow-instance` 文档把
`scheduleTime` 示例写成逗号分隔时间，实际 controller 使用 `BackfillTime` JSON。使用
start/end 展开补数日期还要求存在 released native schedule；这不能作为当前治理路径。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 直接启用 DolphinScheduler ONLINE schedule | 原生、配置少 | scheduler 可创建账本外执行，无法预绑定策略与 Run | 不选 |
| B. 在 GDA 新建 cron/backfill scheduler | 可先创建 Run | 重复建设 timer、queue 和 retry runtime | 不选 |
| C. invocation 版本化，GDA 建 Run 后投递原生 complement | 保留 DS 执行权威，同时完整绑定治理证据 | 每个逻辑时点需创建一个 Run，需维护 adapter | **选择** |

## Decision

### 1. Invocation 是不可变输入

`manual`、`schedule`、`backfill` 和 `replay` 调用使用
`gda.dataops_invocation.v1` 文档。稳定 ResourceURN 绑定 definition，调用内容形成确定性
`ResourceVersion`，包含 trigger kind、UTC 逻辑窗口、schedule reference、请求者、请求时间
和 content fingerprint。

Run 以 `binding_name=invocation`、
`semantic_type=platform.dataops.invocation` 引用该版本。策略决策的
`resource_version_ids` 必须等于 definition 与全部 Run input versions，因此时间窗自动进入
不可变授权范围，不允许 adapter 从临时 API 参数补写。

### 2. 一个 Run 对应一个 provider 补数实例

新 backfill 使用半开窗口 `[logical_start, logical_end)`，并显式绑定恰好一个
`schedule_time`。多个补数时点必须拆成多个 invocation 和 PlatformRun；不能让多个
DolphinScheduler 实例共享同一 Run correlation。

Adapter 将显式时点按 DeploymentProfile IANA 时区格式化，并发送 3.4.2 实际要求的：

```json
{
  "complementStartDate": "",
  "complementEndDate": "",
  "complementScheduleDateList": "2026-07-01 09:00:00"
}
```

同时固定 `execType=COMPLEMENT_DATA`、`RUN_MODE_SERIAL`、parallelism 1、
`OFF_MODE` 和 `ASC_ORDER`。该路径不创建或发布 native schedule。

### 3. Correlation 与恢复

provider global params 必须包含 Run、tenant、definition、idempotency、invocation version/hash、
trigger kind 和逻辑窗口。扫描历史实例时，先比较基础 Run identity；只有匹配当前 Run 的候选
实例才必须具备完整 invocation correlation，以兼容升级前实例，同时对当前候选失败关闭。

Provider `SUCCESS` 只生成 observation 并把 Run 推进到 `reconciling`。最终成功或失败仍由
GDA 的质量、Artifact 和 lineage 证据决定。terminal Run 的遗留 reconcile command 可由
consumer 幂等完成，但 dispatch command 不得因此静默跳过。

## Trade-offs

- 每个补数时点一个 Run 会增加控制对象数量，但换取明确策略范围、独立失败恢复和唯一实例。
- 当前不提供原生 cron；schedule window 的原子 Run 创建已由 ADR-096 落地，生产触发源、
  cursor、lag 指标和 HA 验收仍是 AR-1 未完成项。
- 依赖 3.4.2 实际 DTO 而不是错误 OpenAPI 示例，升级 DolphinScheduler 时必须重新做 contract
  conformance。
- GDA 只保存调用意图和证据，不接管 DolphinScheduler 的 task queue、worker 或 backfill
  execution state。

## 2026-08-01 Real-data Acceptance

重庆璧山 JQDLTB 正式 backfill Run
`c4c54854-885f-55f0-a445-cb1baf4ab20a` 绑定 invocation version
`5ce38c2a-0f54-55fb-a645-da12bfbad893`，通过 transactional outbox 创建唯一
DolphinScheduler instance `2`。provider metadata 的 `command_type=5` 对应固定版本
`COMPLEMENT_DATA`，schedule time 为 `2026-07-01 09:00:00`，全部 GDA correlation 变量完整。

实例状态为 `SUCCESS`，但全量 1,555 个要素的权威质量结果
`c52f3c74-b203-56e2-aeb1-4376c691f9ec` 仍为 `failed`。Run 事件为
`accepted -> dispatching -> reconciling -> failed`；质量评估版本和 source -> assessment
lineage 已登记，关联 DataProductVersion 为 0。终态重放未新增 observation、ResourceVersion、
lineage 或状态迁移。

首次 comma-delimited 参数探针 Run
`e244322f-3df0-52fd-908e-b849a10217af` 被 3.4.2 在创建实例前明确拒绝，已保留为 failed
证据并由正式 Run 替代；其 outbox command 已全部 terminal，不作为通过样本。

## Revisit Triggers

- DolphinScheduler 新版本提供与实现一致、可携带 GDA invocation 的 schedule API。
- 单个业务补数必须原子覆盖多个 provider schedule time，且“一 Run 一实例”不再满足恢复需求。
- 生产触发源或 DolphinScheduler 新 schedule API 改变 ADR-096 的精确窗口准入边界。
