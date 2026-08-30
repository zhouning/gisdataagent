# ADR-129：空间脱敏 Run 接入真实 DolphinScheduler provider

**Status**: Accepted

**Date**: 2026-08-03

**Decision owners**: Data Platform, Data Governance, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-1 / AR-3

**Related decisions**: [ADR-007](adr-007-dolphinscheduler-temporal-orchestration-platform.md) ·
[ADR-097](adr-097-atomic-governed-dataops-manual-admission.md) ·
[ADR-127](adr-127-governed-spatial-anonymization-run-admission.md) ·
[ADR-128](adr-128-deterministic-spatial-anonymization-run-worker.md)

## Context

ADR-128 提供了确定性 Worker，但尚未证明真实 DolphinScheduler 能创建 process instance、把不可变 Run
关联变量传到执行边界，并将 provider observation 写回同一平台 Run。直接把源表、输出表、k 值或差分
隐私参数复制进 SHELL task 会形成第二份可漂移的执行真值，不能接受。

DolphinScheduler sandbox 容器不持有 GDA 源码和控制库凭据。现有 DataOps 任务使用带共享 secret 的
最小宿主机 executor API 承接实际工作，这一模式可继续复用，但空间脱敏必须拥有独立 typed command、
严格额外字段拒绝和回执恢复语义。

## Decision

### 1. Provider 只传 Run 引用

`build_spatial_anonymization_definition` 生成版本化 DolphinScheduler SHELL definition。任务调用
`/v1/execute/spatial-anonymization-run`，JSON payload 只包含 `tenant_id` 和 `run_id`。源/输出、类型、
等级、字段、k 值、聚合与差分隐私参数不进入 task definition、global params 或 executor command；
Worker 必须从不可变 request binding 解析它们。

definition、编译指纹、provider workflow code/version 和 execution-plan Artifact 保持一一绑定。URL 只
接受无 credential、path、query 或 fragment 的 HTTP(S) origin；token 继续由只读 secret file 注入，
不进入 definition 或认证报告。

### 2. Typed executor 是执行边界，不是调度器

`SpatialAnonymizationExecutor` 提供独立健康检查和 Bearer 认证 POST。command 使用严格、不可变、禁止
额外字段的合同；认证通过后只调用 ADR-128 Worker。成功返回 attempt、request version、输出、回执和
outcome 引用；非法 command、Worker 合同冲突和执行不可用使用稳定错误分类，DolphinScheduler 根据
HTTP 结果判定 task 状态。

executor 不领取 outbox、不维护 queue/lease/retry，也不决定 PlatformRun 终态。outbox consumer、
DolphinScheduler 和 GDA evidence gate 继续分别拥有各自职责。

### 3. Provider SUCCESS 只能推进到 reconciling

真实 dispatch 先将 Run 从 `accepted` 转为 `dispatching`，创建 provider process instance，并记录
submitted observation。provider 终态通过既有 adapter 写入 success observation；Run 只推进到
`reconciling`。空间输出和安全回执证明副作用完成，但不能替代输出 Artifact、独立 QualityResult 和
输入到输出 LineageEvent，因此不能直接调用 `succeeded`。

### 4. 认证同时验证 provider 侧可达性

认证脚本使用临时 PostGIS 和临时 executor，复用开发 DolphinScheduler 3.4.2 sandbox。dispatch 前必须
同时通过宿主机健康检查和 DolphinScheduler 容器内健康检查，避免宿主机已监听但容器路由尚未可达的
启动竞态。关联变量短暂不可见时只重试这一种明确协议状态，其他 provider 协议错误立即失败。

## 2026-08-03 Acceptance

- Ruff 对 executor、definition builder、Worker、认证脚本和相关测试通过。
- 扩大安全/DataOps/provider 回归 `258 passed, 2 skipped`。
- `scripts/certify_spatial_anonymization_dolphinscheduler.py` 的真实认证通过 `16/16`。DolphinScheduler
  workflow definition `180506926715456` / version `1` 的 process instance `18` 为 `SUCCESS`；同一
  Run 的 provider dispatch/success observation、PostGIS 输出、行数据、GiST、原子回执、安全事件链和
  executor 回执重放全部通过。
- provider variables 精确关联 tenant/Run/definition/invocation，且不包含源表、输出表、k 值、字段或
  差分隐私业务参数；PlatformRun 最终保持 `reconciling`。
- 无敏感认证报告写入
  `.tmp/dolphinscheduler-sandbox/spatial-anonymization-provider-certification.json`。临时 PostGIS 和
  executor 已自动清理；共享 PostgreSQL 与 `8000` 未修改。

## Limits

- 本次是开发 sandbox provider 认证，不代表 production DolphinScheduler 的 OIDC/service identity、HA、
  worker placement、网络策略、secret rotation、容量或 SLO 已通过。
- provider definition 已真实运行，但尚未作为 local-dev/production 发布物写入共享控制库；部署时必须
  通过同一 definition/binding Artifact 流程，不能手工填写未验证的 workflow code。
- `PlatformRun` 成功证据门仍缺正式输出 ResourceVersion/Artifact、独立 passed QualityResult 和
  input-to-output LineageEvent；retry/cancel/timeout 和 provider attempt 版本化也未完成。
- request 仍未绑定 source ResourceVersion/PostGIS snapshot。
- 因此本切片不代表完整安全生命周期、AR-1、AR-3、AR-4 或下一代 Data Platform 已完成。

## Revisit Triggers

- 空间输出资产合同确定后，新增确定性 output ResourceVersion、content-bound Artifact、质量证据和血缘，
  通过现有 `finalize_run_success` 数据库门收敛 Run。
- production 部署前，将 executor 纳入版本化 DeploymentProfile、least-privilege network policy、secret
  rotation、health/readiness 和容量验收。
- 引入 provider retry/cancel 时，必须保持已有成功回执不重复副作用，并将真实 provider attempt 身份
  纳入安全 attempt 合同。
