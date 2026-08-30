# ADR-094：用临时 Physical Slot 与 Streamed WAL 验证有界 PITR，不冒充持续灾备

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Platform Architecture, SRE

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## Context

ADR-092 证明了 PostgreSQL logical dump 和 MinIO 内容可以恢复，ADR-093 将耗时固化为单次
SLI 观测，但 logical restore 不能证明物理 base backup、WAL 连续性或恢复到指定 transaction
之前且排除后续 transaction。主 Compose PostgreSQL 16.14 当前为 `wal_level=replica`、
`max_wal_senders=10`、`max_replication_slots=10`，具备物理复制基础；但
`archive_mode=off`，生产 override 也只有每日 logical dump。

直接打开 `archive_mode`、修改现有 HBA 或把本地 volume 说成生产 WAL archive，都会在没有
异地、加密、保留、slot 监控和 RPO 审批的情况下制造虚假的持续灾备能力。AR-0 当前需要先
证明 PostgreSQL 的 point-in-time recovery 机制对真实重庆数据有效，同时保持源库和权限
变化最小、可清理、可审计。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 继续只做 logical dump restore | 已验证、实现简单 | 不能恢复到指定 transaction | 拒绝 |
| 立即在主库启用本地 archive volume | 接近持续 PITR | 同故障域、未加密、无保留/监控，需重启 | 延后 |
| 临时修改 `pg_hba.conf` 开放 Compose 子网 replication | 可运行标准 client | 扩大权限面，异常退出可能遗留规则 | 拒绝 |
| 只在空 scratch cluster 测 PITR | 风险低 | 不能证明 6.6 GB 真实 PostGIS/TWM 状态 | 拒绝 |
| 临时 physical slot + loopback client + 隔离恢复 | 无 HBA/PGDATA 配置变更，真实数据可验 | 只证明短窗口，不是持续归档 | **选择** |

## Decision

1. 新增一次性 `ComposePITRRehearsal`，复用 DeploymentProfile、live verifier、恢复合同和
   统一数据库逻辑身份采集器，不新增 backup registry、scheduler、数据库表或常驻服务。
2. 每次运行生成随机、受正则约束的 probe database、physical replication slot 与四个临时
   container。probe 位于独立数据库，不向 `gis_agent` 业务表写测试标记。
3. `pg_basebackup -X stream` 使用临时 physical slot 生成 plain physical backup，并强制
   SHA-256 backup manifest；`pg_verifybackup` 完整通过后才允许进入 WAL 阶段。
4. 临时 client 使用 `--network container:<db-id>` 共享数据库网络命名空间，从
   `127.0.0.1` 命中现有 loopback replication HBA。不得修改 `pg_hba.conf`，不得向 Compose
   子网新增 replication 规则，也不得挂载源 PGDATA。
5. base backup 完成后启动 `pg_receivewal --synchronous`。probe 先提交 `target` transaction，
   再提交 later transaction 并强制 `pg_switch_wal()`；physical slot 的 `restart_lsn` 必须
   越过 later LSN，且至少形成一个完整 WAL segment，才可停止 receiver。
6. 恢复目标追加 `recovery.signal` 和精确 `recovery_target_time`，使用只读 WAL 介质并以
   `--network none` 启动。恢复实例必须包含 target 状态、排除 later 状态、完成 promote，
   且与源库 migration、标准、扩展、geometry column 和重庆 TWM 代表表逻辑身份一致。
7. 无论成功失败，都先停止 receiver，再按随机精确名称删除 container、slot 和 probe
   database。成功报告只有在源端计数为零、container 不存在后才可声明 cleanup=true。
8. 报告和版本化 seal 不保存 password、slot/probe 名、WAL 文件名、host path 或样本值。
   seal 绑定报告规范化 SHA-256、Compose config、manifest、WAL inventory 和数据库逻辑
   身份；内容漂移、时间线倒置、cleanup 降级或注入 RPO/RTO 数值均 fail closed。
9. 本演练明确是
   `bounded_streamed_wal_observation_not_continuous_pitr_slo`。`archive_mode=off`、
   `rpo_status=not_defined`、`rto_status=not_approved` 和 `promotion_ready=false` 固定保留。

## Development Runtime Result

2026-07-31 对主 Compose 与真实重庆/TWM 集群完成演练：

- source PostgreSQL 为 6,655,269,911 bytes；physical backup 为 6,723,246,396 bytes；
- base backup 12.982 秒，SHA-256 manifest verification 4.700 秒；
- base backup 结束后 streamed WAL 形成 2 个完整 segment、33,554,432 bytes，内容 inventory
  SHA-256 已绑定；target 与 later transaction 相隔 1.188492 秒；
- network-isolated target recovery 1.901 秒，包含 target、排除 later 并完成 promote；
- source/restored 均为 93 migrations、174 released standard 数据元、4 geometry columns，
  `twm_state_object=777332`、`twm_state_relation=1433322`、`twm_evidence_item=29556`；
- end-to-end 24.994 秒，临时 container、slot、probe database 和介质全部清理；主应用
  health/ready 保持 ok；
- 版本化 evidence seal 的 profile、Compose config、治理、报告 hash 和完整重建五项检查
  全部通过，最终 `technical_pass=true`、`promotion_ready=false`。

实现过程中 fail-closed 运行先后暴露无效 `pg_basebackup` 长参数和缺少 Compose 子网
replication HBA。前者修正为标准 `--pgdata`；后者没有通过放宽 HBA 绕过，而是采用已有
loopback replication 边界。每次失败后 slot、probe 和 container 都恢复为零。

## Consequences

### Positive

- PostgreSQL PITR 从配置推断升级为真实数据、真实 WAL、真实 target/later transaction 证据。
- 物理恢复和 logical restore 共用同一 migration/标准/TWM 身份合同。
- 不修改主库 HBA、PGDATA 配置、业务 schema 或现有 named volume。
- 失败阶段脱敏分类，不通过跳过 manifest、忽略 later 状态或只检查进程启动来放行。

### Negative

- 临时 streamed WAL 只覆盖约 2 秒窗口，不能证明 7x24 archive durability 或任何 RPO。
- 介质与源库仍在同一开发机，不证明 KMS、异地、区域故障或凭据恢复。
- PostgreSQL target 与 MinIO/Iceberg/STAC/DataProductVersion 尚无联合 consistency marker。

## Verification

- contract/pgpass 脱敏、恢复配置、WAL 内容 inventory、错误分类、失败报告、seal 漂移、
  时间线和 cleanup proof 定向测试通过。
- 完整 live rehearsal、默认离线 seal verifier、应用 health/ready 和资源零残留检查通过。
- Ruff、Python compile、JSON parse、敏感信息扫描与 `git diff --check` 纳入回归。

## Revisit Triggers

- 为 production/staging/customer DeploymentProfile 选择并批准 WAL archive provider、KMS、
  retention、replication slot alert 和容量阈值后，验证持续恢复窗口；
- 业务 owner/SRE 批准 RPO/RTO 后，增加独立 objective/approval 合同，不修改本 observation；
- MinIO versioning/replication 与 cross-system consistency marker 建立后，执行联合时间点恢复；
- failover/cutover、DNS/consumer reconnect 和 rollback 纳入服务恢复后，测量完整 RTO SLI。
