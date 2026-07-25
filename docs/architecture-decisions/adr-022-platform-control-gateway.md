# ADR-022：建立最小权限 Platform Control Gateway

**Status**: Accepted

**Date**: 2026-07-24

**Decision owners**: Platform Architecture, Data Platform, DataOps, Security

**Related decisions**: ADR-003、ADR-007、ADR-018、ADR-020、ADR-021、ADR-024、ADR-025

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-020 已建立 `gda_control` 合同和强制 RLS，ADR-021 已冻结旧表 writer 并禁止无证据 backfill，但账本仍没有应用可用的受控写入口。让现有 API、Agent、adapter 或外部平台直接持有表级写权限，会重新形成多写源，并允许调用方绕过 Run CAS 状态机或伪造 RunEvent。

AR-1 需要先建立一个足够小、可测试的入口，再决定首个纵向场景需要哪一套外部 metadata 或 orchestrator。当前代码仍是模块化单体，因此没有理由先拆微服务或同时接入 OpenMetadata、Gravitino、DolphinScheduler 和 Temporal。

约束：

- 所有写入必须处于单一 PostgreSQL 事务，并绑定 tenant session context；
- ResourceVersion、Definition、attempt、Artifact、Lineage 保持 append-only；
- PlatformRun 只能通过 CAS 函数改变状态，调用方不能直接插入 RunEvent；
- HTTP tenant、subject 和 actor 必须来自认证身份，不能信任请求体覆盖；
- 重试必须返回既有等价记录，payload 冲突必须 fail closed；
- 本开发包不能双写旧表，也不把合同测试误写成生产切换完成。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 给现有应用登录授予 `gda_control` 全表写权限 | 改动少 | 可绕过 RLS 意图、append-only 和 Run 状态机 | 拒绝 |
| B. 每个对象建立独立微服务 | 隔离边界显式 | 当前规模下增加部署、鉴权、事务和可观测性成本 | 拒绝 |
| C. 先接外部 catalog/scheduler，再由 adapter 双写 | 可快速展示集成 | 权威、幂等和故障顺序尚未冻结，会产生双写分叉 | 拒绝 |
| D. 模块化单体 transaction-script gateway + 专用数据库角色 | 范围小，事务和授权可由真实 PostgreSQL 验证，保留后续拆分路径 | 暂不提供完整 policy、catalog 或 orchestration 能力 | **选择** |

## Decision

### 1. 专用数据库角色和事务身份

migration `094_platform_control_gateway.sql` 创建 `gda_control_gateway`：`NOLOGIN`、`NOINHERIT`、`NOBYPASSRLS`，没有 `UPDATE`、`DELETE`、schema create 或直接 `platform_run_event` insert 权限。部署登录必须在每个事务中显式 `SET LOCAL ROLE gda_control_gateway`，随后设置 transaction-local `app.current_tenant`。事务结束后角色和 tenant context 自动复位。

角色只获得所需表的 `SELECT/INSERT` 和 `transition_platform_run` 的 `EXECUTE`。Run 初始事件由受控 trigger 生成；后续事件只能由 CAS transition function 追加。

### 2. 单一应用写入口

`data_agent.platform_gateway.PlatformGateway` 是当前唯一批准的新账本写入口，提供：

- Resource 和 ResourceVersion 幂等登记；
- Resource + ResourceVersion + PlatformDefinitionVersion 原子登记；
- PlatformRun + input binding 原子提交、读取和 CAS transition；
- FrameworkAttemptObservation、Artifact 和 LineageEvent 幂等追加。

所有 insert 使用稳定 identity 或 idempotency key 查重，并在返回前比较完整不可变 payload。相同请求返回已有对象；同一 identity/key 对应不同 payload 时整个事务回滚并返回 conflict。它不更新旧资产/workflow/run/lineage 表。

### 3. Versioned HTTP boundary

九个 `/api/platform/v1/...` 路由复用现有应用认证，但只允许 `admin` 和 `platform_operator`。密码身份的 JWT metadata 携带 `tenant_id`；管理员通过独立 user-tenant binding API 显式赋值。现有用户、OAuth/bot 或其他缺少合法 tenant 的身份默认拒绝访问。

Run 的 SubjectContext 和 transition actor 完全由认证 principal 构造。ResourceVersion `created_by`、Artifact `created_by` 和 LineageEvent `producer` 必须与认证 actor 一致；payload tenant 必须与 JWT tenant 一致。响应统一使用 `data/error/request_id` envelope。

### 4. 部署前提

- 执行 migration 094 的数据库主体需要 `CREATEROLE`，或由 DBA 执行等价的受控角色预置步骤；
- 实际应用数据库 login 必须由 DBA/部署系统在仓库外授予 `gda_control_gateway` membership；migration 不创建 login 或凭据；
- 用户在调用平台 API 前必须显式绑定 tenant；不得给历史用户填充猜测的默认 tenant；
- staging 必须验证 migration account、应用 membership、连接池事务复位和双租户拒绝，再允许任何业务 adapter 切换写入口。

## Consequences

正面影响：

- 表级最小授权、RLS、append-only trigger 和应用授权形成分层边界；
- Definition bundle 和 Run input 在单一事务中提交，不会留下半条控制链；
- provider 仍只能追加 attempt evidence，不能自行裁决 PlatformRun 终局；
- 外部 catalog/orchestrator POC 可以复用稳定入口，而不需要直接访问内部表。

限制与缓解：

- 资源级 PolicyDecision/Approval 与 workload SubjectContext 已按 ADR-024 接入 Run 提交和 DolphinScheduler dispatch，但 API 角色仍是 tenant 级 `platform_operator`；生产切换前仍需真实 IAM/OIDC、service credential provisioning 和 provider 侧最小权限验收；
- tenant GUC 是应用登录设置的纵深防御上下文，不是独立加密身份；数据库凭据、role membership 和连接权限仍必须由部署/IAM 控制；
- 当前只有 Run read，没有 catalog/list/search 或 mutation API；这些能力应由后续 metadata fabric 和 policy-aware query facade 提供；
- 生产调用方仍写 legacy 表；本包验证的是新写入口，不是生产数据迁移或旧链退役；
- migration 需要角色管理权限，必须纳入部署 runbook 和托管数据库兼容性验收。

## Verification

- 静态 validator 检查 non-bypass role、最小 grant、transaction-local role/tenant marker、版本化路由和禁止的 `UPDATE/DELETE/RunEvent INSERT`。
- PostgreSQL 权限测试证明 gateway role 无 login/superuser/create/inherit/bypass 能力，只能访问当前 tenant，不能直接更新、删除、伪造 RunEvent 或跨 tenant insert。
- 服务层 PostgreSQL 测试通过真实 `PlatformGateway` 跑通 Definition、ResourceVersion、Run/input、CAS transition、attempt、Artifact 和 Lineage，并验证相同请求幂等重放。
- HTTP 测试覆盖未认证、错误角色、缺失 tenant、tenant/actor spoofing、请求 envelope 和路由注册；认证/API 回归测试保持通过。

## Revisit Triggers

- 新 adapter 需要不同 action、obligation、审批职责分离或 provider policy 下推模型；
- 需要 workload OIDC/service identity，而不再适合复用交互式 Chainlit user；
- metadata/orchestrator POC 需要超出 ADR-025 dispatch/reconcile 范围的 list/search 或异步事件合同；
- 模块化单体在独立扩缩、故障域、吞吐或发布节奏上达到记录过的瓶颈；
- 生产切换需要 legacy 双读比较、迁移审计、rollback 和旧 writer 撤权。
