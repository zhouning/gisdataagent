# ADR-018：采用稳定 ID、Checksum 与 Fail-Closed 的 Migration Ledger

**Status**: Accepted

**Date**: 2026-07-24

**Decision owners**: Platform Architecture, Data Platform, SRE

**Related roadmap**: [AR-0 平台事实源](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

原 migration runner 只用三位数字版本判断是否执行，`schema_migrations.version` 具有唯一约束。仓库中 011-017 各存在两份不同 migration，导致同编号的后一份在 SQL 成功后因账本插入冲突而回滚。runner 捕获异常后继续，应用启动和 K8s Job 最终仍返回成功，不同环境因启动历史不同而形成 schema 分叉。

现有账本没有内容 checksum，无法发现已执行 SQL 被修改。部分 migration 还依赖应用 `ensure_*` 隐式创建的表，SQL 链本身不能从正式数据库镜像的空库独立重放。

约束：

- 已发布 migration 文件不能改名或改写，以免失去历史可解释性。
- 既有数据库必须原地升级，保留 version、filename 和 applied_at。
- 空库和遗留库必须由同一 CLI/部署 migration authority 收敛；应用启动只读验证账本并沿用相同 drift 判定。
- 当前只支持项目既有的 PostgreSQL/PostGIS 生产数据库，不为未采用的数据库方言增加抽象。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 保留 version 唯一，继续 warning 后跳过 | 改动最小 | 环境继续分叉，失败不可见 | 拒绝 |
| B. 重编号或改写 011-017 | 目录表面整齐 | 已执行历史无法可靠映射，可能重复执行或永久遗漏 | 拒绝 |
| C. 立即迁移到 Alembic/Flyway/Liquibase | 成熟工具链 | 仍需先解决现有冲突、隐式前置表和历史映射；扩大首个修复包 | 延后评估 |
| D. 完整 filename 作为稳定 ID，checksum 固化内容，显式兼容遗留冲突 | 可前向收敛且不改历史；实现范围受控 | 需要维护少量遗留顺序清单和账本升级代码 | **选择** |

## Decision

1. migration ID 是去掉 `.sql` 后的完整 filename；数字前缀只表达逻辑顺序。
2. 每条 migration 以 SHA-256 checksum 入账。已执行 ID 的 filename、version 或 checksum 不一致时状态为 drift，禁止继续执行。
3. 011-017 的精确 filename 集合是冻结的遗留白名单。新增编号冲突、移除其中单个成员或使用非法文件名时，目录校验失败。
4. 5 个误用旧编号且依赖后续表的 v14 migration 保留原 ID 和内容，通过显式逻辑顺序在依赖建立后执行。
5. 新增幂等 `000_legacy_runtime_prerequisites.sql`，把此前只由应用 helper 创建、但被 SQL migration 依赖的 user tools、MCP 和 knowledge base 表纳入 SQL 权威链。
6. 旧账本原地增加 `migration_id` 与 `checksum`，按 filename 回填；移除 version 唯一约束并增加 migration_id 唯一约束。无法映射、checksum 缺失或重复 ID 均作为 drift。
7. PostgreSQL advisory lock 串行化 runner。每条 migration 独立事务提交；任一 SQL 失败立即回滚并抛错，不处理后续 migration。
8. K8s Job、Compose 一次性 migration service 和 `scripts/migrate.sh` 是唯一结构写入方，均调用同一个 Python runner 并使用管理员角色。应用启动只调用只读 `verify_schema_state()`，不创建/修改表，也不接收管理员凭据；没有配置数据库时允许非 DB 模式，有配置但 ledger 缺失、pending 或 drift 时阻断启动。
9. CLI 提供 `validate`、`migrate`、`status` 和 `compare`，输出 catalog/database fingerprint、pending、unknown、checksum 和 metadata 差异。
10. 历史 `ensure_*` 兼容 helper 不再进入应用/MCP 启动路径。模板 seed、未完成运行恢复和临时 MVT 资源清理仍是独立的运行时数据维护，不拥有平台 schema。

## Consequences

正面影响：

- 同编号的两条历史 migration 都能被独立识别和补齐。
- migration 失败、历史内容漂移和环境不一致变成可观测的部署失败。
- 正式 PostGIS/pgvector 镜像可从空库重放完整 SQL 链，不再依赖应用 helper 的执行时机。
- Web 应用和普通 worker 无管理员凭据，副本扩缩容不再隐式竞争 DDL ownership。
- staging/production 报告可以离线比较，支持发布门禁与事故定位。

负面影响：

- 已配置数据库不可用时，应用不再以“部分 DB 功能失效”模式继续启动。
- 首次升级会信任当前仓库内容为历史行回填 checksum；此后才具备强内容漂移检测。
- runner 中保留项目特定的遗留冲突和逻辑顺序清单，不能宣称为通用 migration framework。

## Verification

- 正式 `gis-postgis-pgvector:16-3.4` 镜像空库完成 92/92 migration，catalog 与 database fingerprint 一致。
- 同库重跑保持 92/92 `in_sync`。
- 旧版 `version UNIQUE` 账本保留 filename/applied_at，成功回填 ID/checksum，并将约束替换为 migration ID 唯一。
- 人工篡改已执行 checksum 后，migrate 在执行 SQL 前以非零退出码阻断；恢复后重新 `in_sync`。
- 单元测试覆盖目录合同、遗留顺序、checksum、pending、drift、回滚和环境报告比较。
- 2026-07-26 Docker Desktop kind 本地验证：新 App/Outbox Pod 使用普通数据库角色且管理员变量为空，应用只读校验 97/97 `in_sync`，启动日志无 table ownership/DDL 错误，`/health` 与 `/ready` 均正常。该结果是本地部署证据，不替代 staging/production 验收。

## Revisit Triggers

- migration 数量、分支并行度或 schema ownership 使项目内 runner 的维护成本明显上升；
- 需要支持 expand/contract、online schema change、自动 downgrade 或多数据库方言；
- 团队选定 Alembic、Flyway 或 Liquibase，此时必须先导入现有稳定 ID/checksum ledger，不能重新假定版本历史；
- PostgreSQL advisory lock 无法满足跨区域或多集群部署的发布协调要求。
