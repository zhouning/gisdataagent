# ADR-128：空间脱敏 Run 使用确定性 Worker 和回执恢复

**Status**: Accepted

**Date**: 2026-08-03

**Decision owners**: Data Platform, Data Governance, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1 / AR-3

**Related decisions**: [ADR-007](adr-007-dolphinscheduler-temporal-orchestration-platform.md) ·
[ADR-125](adr-125-immutable-security-operation-receipt-reconciliation.md) ·
[ADR-126](adr-126-atomic-spatial-output-and-security-receipt.md) ·
[ADR-127](adr-127-governed-spatial-anonymization-run-admission.md) ·
[ADR-129](adr-129-real-dolphinscheduler-spatial-anonymization-provider.md)

## Context

ADR-127 已将空间脱敏请求、策略证据和 dispatch command 原子绑定到正式 `PlatformRun`，但还缺少
一个能在实际执行边界消费该 Run 的进程。Worker 不能信任调度器临时传入的源表、输出表或脱敏参数，
否则准入阶段的不可变证据无法约束真实数据操作。

空间输出与安全回执已由 ADR-126 原子提交，安全 outcome 则可能因进程退出而缺失。调度器重放时若
再次执行建表，会把“恢复证据”变成“重复副作用”；同一 Run 被两个 worker 同时领取，也会产生相互
矛盾的 success/failure outcome。

## Decision

### 1. Run binding 是唯一参数真值

`SpatialAnonymizationWorker` 只接受 tenant ID 和 Run ID。它从 Gateway 读取 Run，并要求状态属于
`dispatching/running/reconciling`；随后只从唯一的
`security.spatial_anonymization.request` binding 解析源/输出、point/polygon、L1-L4、k 值、字段、
聚合和差分隐私参数。tenant、human delegation、workload identity 或 request metadata 不匹配时
fail closed。

Worker CLI 为：

```bash
python -m data_agent.spatial_anonymization_worker --tenant-id TENANT --run-id RUN_UUID
```

该 CLI 是供正式 provider task 调用的执行入口，不是新的队列或调度器。

### 2. Run 决定稳定 attempt 身份

安全 `attempt_id` 由 Run ID 和版本化命名空间确定性派生。执行前，Worker 使用 PostgreSQL
tenant/attempt advisory transaction lock 获取非阻塞互斥；锁未取得时拒绝重叠执行。锁覆盖请求加载后
的回执检查、空间操作和 outcome 处理，避免两个 worker 同时产生不可协调的结果。

这一互斥会在空间操作期间保持一个控制库事务。它不提供排队、租约或故障检测，实际领取和重试仍由
DolphinScheduler/provider 负责。

### 3. 执行和恢复遵循安全证据状态机

- 无回执、无 outcome：写 `admitted`，调用真实 polygon/point PostGIS 操作；操作必须原子提交输出、
  GiST 和完成回执，Worker 验证回执后写 success outcome。
- 有成功回执、无 outcome：不重复脱敏，只调用 ADR-125 reconciler 补齐 success outcome。
- 有成功回执、有 success outcome：返回 `already_completed`，不重复建表。
- 有 outcome、无回执，或回执与不可变请求不匹配：fail closed，等待人工处置。
- 空间操作抛错或返回失败：写 failure outcome，并返回稳定 Worker 错误。

因此回执是“副作用已经提交”的恢复依据，outcome 是审计结论；两者都不能由返回码替代。

## 2026-08-03 Acceptance

- Ruff 对 Run、Worker、SecurityEventLedger、认证脚本和相关测试通过。
- 扩大回归 `201 passed, 2 skipped`，覆盖准入、Worker、事件/回执、reconciliation 和 polygon/point
  空间脱敏合同。
- `scripts/certify_spatial_anonymization_run_worker.py` 在自动删除的
  `postgis/postgis:16-3.4` 中通过 `13/13`：真实 polygon 输出、行数据、GiST、原子回执、完整事件链、
  重放恢复、稳定 attempt、重叠 worker 拒绝、载荷漂移冲突，以及一套 request version/Run/command。
- 共享 PostgreSQL、现有 `8000` 服务和 DolphinScheduler sandbox 均未修改。

## Limits

- ADR-129 已在开发 sandbox 接通真实 DolphinScheduler process/task 和 provider observation，但尚未完成
  production 部署认证。
- Worker 尚不推进 `PlatformRun` 到 `running/reconciling/succeeded/failed`；Run 终态必须在 provider
  回调、AttemptObservation、Artifact、质量和 lineage 证据齐备后由统一 reconciler 判定。
- 当前一个 Run 只有一个稳定安全 attempt。failure outcome 后的受控 retry、cancel、超时和 operator
  override 合同尚未实现，不能通过删除或覆盖安全事件重试。
- request 仍引用目录资产和物理表名，尚未绑定正式 source `ResourceVersion` / PostGIS snapshot。
- 因此本切片不代表完整安全生命周期、AR-3、AR-4 或下一代 Data Platform 已完成。

## Revisit Triggers

- DolphinScheduler adapter 接入时，process instance 必须关联同一 Run/command，并只向 Worker 传 tenant
  和 Run ID，不能复制业务参数。
- 引入真正 provider attempt 后，应把 provider attempt 身份纳入安全 attempt 派生和 retry policy，且
  保持已有回执重放不重复副作用。
- source snapshot 可用后，将其作为独立 Run binding 和 policy resource，并在执行前验证物理版本仍与
  binding 一致。
