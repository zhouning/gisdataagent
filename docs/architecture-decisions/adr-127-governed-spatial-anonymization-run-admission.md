# ADR-127：空间脱敏请求进入统一 DataOps Run 的原子准入

**Status**: Accepted

**Date**: 2026-08-03

**Decision owners**: Data Platform, Data Governance, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1 / AR-3

**Related decisions**: [ADR-007](adr-007-dolphinscheduler-temporal-orchestration-platform.md) ·
[ADR-097](adr-097-atomic-governed-dataops-manual-admission.md) ·
[ADR-123](adr-123-spatial-anonymization-security-boundary.md) ·
[ADR-126](adr-126-atomic-spatial-output-and-security-receipt.md) ·
[ADR-128](adr-128-deterministic-spatial-anonymization-run-worker.md)

## Context

现有 `/api/classification/anonymize` 在 HTTP 请求内完成 PostGIS 空间脱敏，已经具备资产可见性、
不可变安全事件和输出/回执原子性，但它仍是同步工具入口：没有正式 `PlatformRun`、策略 Artifact、
DolphinScheduler dispatch outbox，也不能用统一 Run API 查询异步状态。

不能把脱敏参数放入临时 provider 参数或可变 execution plan。源表、输出表、数据类型、脱敏等级、
k 值、字段保留、聚合策略和差分隐私参数必须成为可验证的不可变输入。API 提交成功也不能提前写
`admitted` 安全事件，因为此时 worker 尚未开始真实数据操作。

## Decision

### 1. 脱敏业务请求是不可变 ResourceVersion

`SpatialAnonymizationRequest` 固化 tenant/client request、human requester、目录资产引用、源/输出
PostGIS 表、point/polygon 类型、L1-L4、k-anonymity、属性聚合和差分隐私参数。完整内容形成
request SHA-256 和确定性 `ResourceVersion`，Run 以
`security.spatial_anonymization.request` 绑定该版本。

tenant 与 `client_request_id` 只形成稳定重试身份。相同身份修改任一不可变字段时，Gateway 返回
conflict，不创建第二个请求版本或 Run。API 不接受 tenant、requester、workload、policy evaluator、
definition 或 execution plan 等客户端自报字段。

### 2. API 只准入，不执行空间操作

新增 `/api/classification/anonymize/submit`，保留原同步接口用于兼容。异步入口先完成认证角色、tenant、
identifier、源资产可见性和输出表不存在检查，然后返回 `202` 及 request version、Run 和 command ID。

提交阶段不调用 `grid_anonymize_pg` / `poi_grid_aggregate_pg`，也不写执行 `admitted` 事件。权限或输入
被拒绝时仍可写 `denied`；真实 `admitted -> atomic output + receipt -> outcome` 必须由后续
DolphinScheduler worker 在实际执行边界完成。

### 3. 一个 Gateway 事务写完全部准入对象

`PlatformGateway.submit_spatial_anonymization_run` 按请求身份获取 tenant-scoped advisory lock，并在
同一最小权限事务中写入：

1. 空间脱敏 request Resource / ResourceVersion；
2. manual DataOps invocation Resource / ResourceVersion；
3. policy decision Artifact；
4. `PlatformRun` 及 request/invocation input bindings；
5. DolphinScheduler dispatch outbox command。

通用人工 Run 的事务主体被提取为内部方法，以复用已有授权和 outbox 合同，不新增本地队列、后台线程
或第二调度器。execution plan 缺失、外键失败或任一步异常时，全部对象一起回滚。

空间脱敏当前没有用户声明的数据时间窗口。为兼容既有 manual DataOps invocation 合同，invocation
使用首次数据库准入时间形成一微秒半开事件窗口；这只表示请求事件，不表示源数据覆盖期。源数据和
输出语义以不可变 request version 为准。

### 4. 运行身份和配置只来自服务端

definition version、execution plan、workload identity、roles、policy version/evaluator、TTL 和 owner
由 `GDA_SPATIAL_ANONYMIZATION_*` 服务端配置提供；workload/policy 配置可显式回退到已部署的 manual
DataOps profile。缺失、UUID 错误或 evaluator 与 executor 相同均 fail closed。

## 2026-08-03 Acceptance

- 合同、API、安全边界和既有 Platform Gateway 聚焦回归 `70 passed`。
- Ruff 对本切片相关实现和测试全部通过。
- 隔离临时 PostgreSQL 16 中，真实 gateway/RLS/外键/advisory-lock 集成测试通过：并发双提交只创建
  一套 request version、Run 和 dispatch command；同 request ID 修改 k 值返回 conflict，数据库中仍
  只有一个请求版本。
- 临时 PostgreSQL 容器测试后已删除；共享 PostgreSQL、现有 `8000` 服务和 DolphinScheduler sandbox
  均未修改。

## Limits

- 本决定只完成正式 Run **准入**。ADR-128 后续提供了确定性 Worker 和回执恢复，但真实
  DolphinScheduler task/provider 实例验收、Run `running/succeeded/failed` 自动收敛、retry/cancel 或
  UI 仍未完成。
- API 提交时的“输出表不存在”只是早期冲突检查；worker 仍必须在执行事务中再次检查，不能依赖准入
  时快照。
- request version 绑定目录资产引用和物理表名，但尚未绑定正式 OpenMetadata/Gravitino 资产版本或
  PostGIS snapshot。
- 因此本切片不代表完整安全生命周期、AR-3、AR-4 或下一代 Data Platform 已完成。

## Revisit Triggers

- 引入正式 source `ResourceVersion` / snapshot 后，将其作为独立 Run binding 和 policy resource，
  不再只放在 request document 中。
- DolphinScheduler worker 接通后，attempt ID 必须由 Run/attempt 确定性派生，并以 request binding
  为唯一参数真值；已有 operation receipt 时只能对账，不得重复脱敏。
- 若空间任务需要真实业务时间窗口，应升级 invocation 合同并显式绑定 source snapshot 时间语义，
  不复用当前请求事件窗口。
