# ADR-090：采用可审计对账与 Fail-Closed 的 Migration Ledger

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Platform Architecture, SRE

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## Context

原 migration runner 只以三位数字版本判断迁移是否执行，单项失败后
`rollback + warning + skip`，外围应用启动又会捕获异常继续运行。仓库还存在
`011` 至 `017` 的历史版本冲突，既有开发库则出现以下事实：

- 代码目录有 93 个 migration ID，旧账本只有 68 条记录；
- 旧记录只有 version、filename 和 applied_at，没有 checksum；
- 24 个 migration 的目标 schema 已经存在但从未入账；
- `091_twm_spatial_policy_rule_derivation` 的 schema probe 未通过，证明它确实未执行；
- 直接重放历史 SQL 会在已被后续版本扩展的约束上产生回退或失败。

这意味着“应用健康”不再能证明 schema 一致，自动补登记也会掩盖真实 drift。
AR-0 要求迁移失败、重复 ID 和 checksum 漂移在部署与启动阶段失败关闭。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 继续按 version 跳过失败 | 改动最小 | 环境继续分叉，健康检查失真 | 拒绝 |
| 自动为旧记录回填当前文件 checksum，并把 pending 全部 baseline | 升级快 | 无法区分“已执行”和“schema 恰好存在”，会掩盖 drift | 拒绝 |
| 立即迁移 Alembic/Flyway/Liquibase | 工具成熟 | 仍需先解决当前冲突、漏账和隐式建表，扩大首个修复包 | 延后评估 |
| 稳定文件 ID + checksum + probe 驱动的显式 reconcile | 保留历史、可审计、可前向收敛 | 需要维护有限的历史 probe 清单 | **选择** |

## Decision

1. 完整 filename 去掉 `.sql` 后是稳定 migration ID；数字前缀只控制顺序。
2. 新增 migration 必须有唯一 ID 和 filename，不能复用数字版本。`011` 至 `017`
   只允许冻结的精确文件集合，新增或删除其中成员都使目录校验失败。
3. 每条 migration 入账 SHA-256 checksum。ID、filename、version 或 checksum 与代码
   不一致时状态为 drift，迁移和应用启动都被阻断。
4. PostgreSQL `pg_try_advisory_lock` 串行化 migration authority；锁竞争立即失败，
   不无限等待。
5. 每条 SQL 在独立事务中执行。任一迁移失败时回滚该迁移、抛出
   `MigrationExecutionError`，不尝试后续迁移。
6. `MigrationReport` 统一输出 catalog/database fingerprint、pending、unknown、
   checksum/metadata drift、probe failure 以及本次 apply/reconcile 结果。
7. CLI 提供 `validate`、`audit/status`、`migrate`、`reconcile` 和 `compare`。
8. 历史账本不自动信任。`reconcile` 必须提供 actor、reason 和显式范围：
   - 已记录但无 checksum 的行标记为 `legacy_checksum_baseline`，并明确记录历史内容
     无法被事后证明；
   - 未记录但 schema 已存在的 migration 只有在代码中有批准的只读 catalog probe，
     且所有 probe 通过后才可标记为 `schema_reconciled`；
   - probe 原子执行，任一失败时不写入任何 baseline；
   - 未配置 probe 的未来 migration 禁止 reconcile，只能真正执行 SQL。
9. `000_legacy_runtime_prerequisites.sql` 将此前仅由应用 `ensure_*` 创建、但被后续
   SQL 依赖的 user-tool、MCP 和 knowledge-base 表纳入正式迁移链。
10. Compose one-shot service、Kubernetes Job 和 `scripts/migrate.sh` 是 schema 写入方。
    应用启动只调用 `verify_schema_state()`，不执行 DDL，也不持有管理员凭据。
11. `MIGRATION_RUNTIME_DB_ROLE` 指定运行时数据库角色，默认是 `agent_user`。migration
    authority 必须确认角色存在、收归 `schema_migrations` 表及其序列的所有权、撤销
    PUBLIC 和运行时角色的既有 ledger 权限，再只授予表 `SELECT`。授权后检查有效权限；
    若角色通过继承、owner 或 superuser 仍能写 ledger，迁移失败关闭。

## Historical Reconciliation Result

2026-07-31 开发库先以普通应用角色执行只读 audit，再以管理员角色显式 reconcile：

- 68 条旧记录补充 checksum 和 reconciliation audit metadata；
- 24 个漏账 migration 通过 schema probes 后入账；
- `091` 因 `spatial_policy_rule` constraint probe 失败而未 baseline，随后由严格 runner
  真正执行并入账；
- 遗留 ledger 原由 `agent_user` 持有且受数据库 default privileges 影响；migration
  authority 已将表和序列 owner 收归 `postgres`，最终 `agent_user` 仅有表 `SELECT`，
  无 INSERT/UPDATE/DELETE 或 sequence USAGE；
- 最终 catalog_count = applied_count = 93，catalog/database fingerprint 均为
  `53ddf178936f4b6ce909bf553e66f33270d9cf815a87458e60de332f69af9ee4`。

同日开发运行环境从 Gemma4 profile 切回主 Compose 时，发现两个 profile 使用不同的
PostgreSQL volume：主 Compose volume 仍是 84 条无 checksum 的旧账本。one-shot
migration 以 drift 状态阻断应用启动；管理员随后以独立 actor/reason 执行相同的 probe
流程，补齐 84 条历史 checksum、对账 8 个已存在 schema，并让未配置 baseline 例外的
`092_std_application_mapping_contract` 真正执行。主 Compose volume 最终同样达到 93/93
和上述 fingerprint；之后 migration no-op 重跑、应用只读启动校验与 HTTP health 均通过。
两个 volume 没有被合并或互相复制，该事件证明 profile/volume identity 也必须进入 AR-0
环境事实清单。

## Trade-offs

- 冻结历史冲突清单是项目特定兼容代码，不是通用 migration framework。
- 首次为旧账本补 checksum 只能证明“操作时的代码内容”，不能事后证明最初执行内容；
  因此必须永久保留 actor、reason 和 `historical_content_unverifiable` 证据。
- 配置数据库但 schema 不一致时，应用不再提供“部分 DB 功能可用”的降级启动；这会
  提高发布阻断频率，但避免向不一致 schema 继续写入业务数据。
- migration authority 成为 ledger owner，运行时角色不能自行补账或修改 checksum；
  运维 audit 仍可由运行时角色执行，但 reconcile/migrate 必须经过管理员入口。

## Consequences

### Positive

- 空库、遗留库和应用运行时使用同一 migration identity 与 drift 判定。
- 失败迁移、历史文件改写、锁竞争和环境 fingerprint 差异成为机器可读的发布失败。
- 应用副本扩缩容不再竞争 DDL 或通过 `ensure_*` 制造账本外 schema。

### Negative

- 新增可对账历史例外时必须同时设计精确 probe，并接受额外评审成本。
- 现有 staging、production 和客户环境仍需分别导出 audit 报告并人工批准 reconcile；
  本决策不把开发库证据外推为所有环境已一致。

## Verification

- 目录、checksum、锁、drift、回滚、probe、最小 ledger 权限、部署和应用启动边界
  定向测试：34 passed，1 skipped。
- PostgreSQL 管理员视角的 `070` 至 `092` schema/constraint 集成测试：67 passed，
  1 skipped。
- 正式 PostGIS/pgvector 容器空库完整执行 93/93，二次执行零变更。
- 按 `docker-db-init.sql` bootstrap 的临时空库再次执行 93/93；`agent_user` 可完成
  只读 audit，但 INSERT 被 PostgreSQL 以 `permission denied` 拒绝。测试库随后删除。
- 三步故障注入：100 成功入账；101 除零失败且建表回滚；102 未执行。
- 篡改临时库 `092` checksum 后，runner 在执行 SQL 前以非零状态阻断。
- 主 Compose 和 Gemma4 demo Compose 都由 one-shot migration authority 先行，app
  不携带管理员变量。开发应用从当前源码镜像重建后，以普通角色验证 93/93，恢复
  healthy，HTTP 首页返回 200。

## Revisit Triggers

- 分支并行度或 expand/contract 需求使项目内 runner 维护成本不可接受；
- 需要 online schema change、自动 downgrade 或多数据库方言；
- 团队选定成熟迁移工具时，必须导入现有稳定 ID、checksum 与 reconciliation evidence，
  不能重新假定数字版本历史。
