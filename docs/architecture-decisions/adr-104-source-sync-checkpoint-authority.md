# ADR-104: Source Sync Definition, Commit, and Checkpoint Authority

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2
**Amended by**: ADR-160, ADR-164

## Context

平台已经能把真实重庆 OSM、建筑和 DEM 送入受治理的全量 DataOps 链，也建立了
`SourceDefinition`、connector capability 和 schema-drift authority。但是增量摄取仍缺少一个统一的
机器合同：同步模式和写入策略散落在 executor 参数中，cursor/checkpoint 没有唯一写权威，provider
commit 与 `PlatformRun` 没有原子绑定，重试时也无法区分安全重放、陈旧 cursor 和同一源切片写向不同
目标的冲突。

把 Iceberg snapshot、Flink checkpoint 或调度器状态直接当作平台 checkpoint，会把 provider 细节提升为
跨平台真值；把 checkpoint 存在 worker 本地文件，则无法在 worker 重启、跨 run retry 或双租户条件下
可靠恢复。

## Decision

### Provider-Independent Sync Definition

新增不可变 `SourceSyncDefinitionVersion`，显式冻结：

- `full` 或 `incremental` 模式；
- `overwrite`、`append` 或 `merge` 写入策略；
- `none`、字段、provider token 或 offset cursor；
- merge 主键、源端删除策略和 provider-neutral config；
- source/target ResourceURN、源定义 fingerprint 和负责执行的
  `PlatformDefinitionVersion`。

全量同步只能使用 overwrite 且不能声明 cursor；增量同步必须声明 cursor；merge 必须有主键，源端删除
只能由 merge 消费。定义以自身 Resource 和 ResourceVersion 登记，四个对象
`Resource + ResourceVersion + typed definition + initial checkpoint` 在一个事务内创建或回滚。

### Append-Only Commit and CAS Checkpoint

`source_sync_checkpoint` 是每个 sync-definition version 的当前投影，初始为 `state_version=0`。客户端不能
直接更新它。每次成功目标写入形成不可变 `SourceSyncCommit`，绑定：

- previous/next cursor 及各自 SHA-256；
- source-slice SHA-256；
- provider target commit reference 和目标内容 SHA-256；
- read/insert/update/delete/output 对账计数；
- typed workload actor、时间和完整 commit fingerprint；
- exact `PlatformRun` 和 sync-definition version。

唯一写入口 `gda_control.commit_source_sync(...)` 锁定 checkpoint，并以
`from_state_version + previous_cursor` 做 CAS。函数先验证 tenant、sync definition、PlatformRun definition、
`dataops` orchestration class、可提交 run 状态、workload actor 和时间，再判断跨 run 的 source-slice
重放。成功时在同一事务内追加 commit 并把 checkpoint 精确推进一个版本；checkpoint 的
`last_sync_commit_id` 通过复合外键引用同租户 commit。

### Replay and Conflict Semantics

- 相同 commit ID 和完全相同证据返回原 commit，不推进 checkpoint；
- 不同 commit/run ID 但相同 definition、previous/next cursor 和 source slice，在当前 run 仍合法且目标
  证据一致时返回原 commit；
- 同一 source slice 指向不同 target evidence，或 cursor/state_version 陈旧时 fail closed；
- 非法、缺失、错误 definition、错误 actor、非运行状态或跨租户 PlatformRun 不能借用既有 commit
  完成重放。

三张表均启用并强制 tenant RLS。gateway 只能创建/读取 definition 与初始 checkpoint、读取 commit 并
调用受控函数；它没有 checkpoint UPDATE、commit INSERT 或任意账本 mutation 权限。definition 和 commit
不可变，checkpoint DELETE 也被拒绝。

## Evidence

迁移 `104_source_sync_checkpoint_authority` 先在随机临时 PostgreSQL database 中通过真实 authority API
认证，再由专用 migration authority 进入主严格账本。主 Compose 当前为 106/106 applied records，
catalog/database fingerprint 均为
`ec36731518456a7e3d7c27cf1968cd59b9ac92c25abea5601ed5b23bb4eb8362`，无 checksum、identity 或
metadata drift。

`.tmp/source-sync-certification/authority-report.json` 的 17 个行为门全部通过：成功与失败回滚的原子定义
创建、初始 checkpoint、单版本推进、同 ID 重放、跨 run source-slice 恢复、target mismatch、stale
CAS、错误 definition/actor/status/tenant/run、直接 UPDATE/INSERT、append-only、RLS、最小权限和租户
隔离。10 个数据库控制检查全部通过，随机 database 已精确删除。

主库三张 sync 表保持 0 行；三表 RLS/FORCE RLS、checkpoint-to-commit 外键、gateway membership 和最小
权限已复核。source-sync、incremental harness 与 platform-contract 聚焦测试 37 项、Ruff、migration
catalog validation 和 diff whitespace 检查通过，应用 `/health` 返回 200。

同一 ADR 随后用已发布重庆 OSM 道路 `v1.2.0` 完成真实数据面验收，并由 ADR-164 重新认证为受治理
Silver micro-batch。50,366 条道路从受治理 MinIO GeoJSON 写入隔离 Iceberg v2 full baseline snapshot
`4946718755623873398`；第二个 Run 在单次 `MERGE INTO` 中精确执行 1 insert、1 update、1 delete，形成
snapshot `5804234102856417302`，总行数和唯一道路 ID 仍为 50,366。baseline 与 merge 后 snapshot
均按 snapshot ID time travel 回读，删除、更新和新增状态分别符合预期；两个 phase 都绑定独立的 target、
quality、lineage、metadata outbox 和显式零拒绝 quarantine receipt。

两个真实 provider commit 将 checkpoint 从 0 精确推进到 2。第三个合法 Run 通过
`find_source_slice_commit()` 在 provider 写入前命中 delta SHA-256
`4be89dfca1b0b7012ed66ac6046dad8f35177a4f77279e8782898ab1ccff3531`，未启动第三次写入；跨 Run
commit 恢复返回原 commit 及治理/隔离双证据，Iceberg history 与 checkpoint 分别保持 2。12 项端到端
检查全部通过，随机 PostgreSQL database、Iceberg table、MinIO prefix 和工作目录已删除，主库 sync 表
前后均为 0 行。证据：
`.tmp/source-sync-certification/chongqing-osm-report.json`，SHA-256
`211ae24a532dd5060049ce2c139bfc50f6a43c76d42d7a5e54d4aeb908d5f2f5`。

## Consequences

- cursor 不再是 executor 私有状态；每次推进都必须有可审计的 source slice、provider commit 和
  `PlatformRun` 证据。
- Iceberg snapshot、Flink checkpoint、PostGIS transaction 或云 provider version 继续作为
  `target_commit_ref` 的 provider evidence，而不是取代平台权威。
- executor 必须先完成或确认目标 commit，再调用 authority；若 authority 返回既有 source-slice commit，
  executor 不得再生成目标 snapshot。
- 本 ADR 已验证 Spark/Iceberg micro-batch 的 full baseline、insert/update/delete merge、time travel 和
  source-slice replay；不宣称 Flink checkpoint、流式 CDC、迟到/乱序、生产并发、吞吐/freshness SLO 或
  持久化增量数据产品已经完成。
- ADR-160 在不改写历史 fingerprint 的前提下，将标准、模型、质量、分类、保留、schema evolution、
  quarantine 和 promotion 绑定加入同一 `SourceSyncDefinitionVersion` 权威，并要求所有新定义携带该
  治理合同。
- ADR-164 用通用 recorder 将 Spark/Iceberg 两个 micro-batch commit 的显式零拒绝 receipt 与既有治理
  证据原子绑定；这不把一次性本地认证提升为持久环境部署。
