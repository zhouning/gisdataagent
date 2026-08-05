# ADR-106: PostgreSQL CDC, Flink Recovery and SourceSync Certification Boundary

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2
**Extended by**: ADR-164, ADR-165, ADR-166, ADR-167, ADR-168, ADR-169, ADR-170, ADR-171, ADR-172, ADR-173, ADR-174

## Context

ADR-105 已证明 Flink 1.19.3 的事件时间、checkpoint/restart、迟到/乱序、重复事件、删除和
exactly-once filesystem sink，但输入仍是预制的 filesystem event slice。AR-2 还不能据此声明数据库
增量接入已经覆盖 PostgreSQL WAL、初始快照、update-before/update-after、replication slot 或 LSN。

默认 Compose 只有应用、PostgreSQL、MinIO 和 Redis，不包含常驻 Spark 或 Flink。直接增加 Kafka、
Debezium server 和常驻 Flink 会扩大尚未由生产 freshness/SLO 证明必要的运维面；但继续用模拟事件又
无法关闭 log-based CDC 的证据缺口。

## Decision

以已发布重庆 OSM 道路 `v1.2.0` Silver GeoParquet 为真实数据来源，从 50,366 条道路中确定性选择四条，
在隔离 PostgreSQL 16.14 中建立三条初始记录。PostgreSQL 必须以 `wal_level=logical` 启动，目标表使用
`REPLICA IDENTITY FULL`，并为本次运行创建独立的 publication、`pgoutput` replication slot 和最小只读
replication role。

Flink 使用官方 `flink:1.19.3-scala_2.12-java11` runtime 和
`org.apache.flink:flink-sql-connector-postgres-cdc:3.3.0`。connector JAR 必须在执行前同时匹配 Maven
SHA-1、SHA-256 和字节数；job source、编译 JAR、runtime image ID、初始/最终 LSN、slot flush LSN、
changelog manifest 和 drain savepoint manifest 都进入 provider evidence。

基础变更集为三条初始 insert、两次 update、三次 delete、两条中间 insert，其中最后一组
insert/delete 使用非法 `geometry_sha256`。运行中再增加 nullable `observed_at` 列并更新一条四字段投影，
在三次快速网络抖动、一次 20 秒断网和 20 次高频断连/重连期间分别更新投影，随后把新列收紧为
`NOT NULL`。Flink Table/CDC 必须解码
20 条唯一 changelog，包括六组 update-before/update-after。一个 checkpointed router 将 18 条合法变更
写入版本化 Silver FileSink，把
非法 insert/delete 以 `invalid_geometry_sha256` 原因写入独立 quarantine FileSink；两个 sink 使用相同
checkpoint rolling policy。首次 attempt 只在 completed checkpoint 后、处理计数 5 时主动失败；只允许
一次 fixed-delay restart，最终以 drain savepoint 停止。

additive drift 必须在旧投影保持运行后进入 `observed -> reconciled`。`nullable_tightened` breaking drift
必须进入既有 `SourceSchemaDriftLedger` 和 pending `ApprovalCase`；未到 `reconciled` 的 schema successor
由 `SourceSchemaPromotionDecision` fail-closed，且决定随 commit evidence 持久化。详见 ADR-167。

provider 写入前调用 `find_source_slice_commit()`。首个 Run 未命中才启动 PostgreSQL/Flink；成功后将
Silver target ResourceVersion、output/quality Artifact、独立 passed QualityResult、LineageEvent、
OpenMetadata outbox 和物理 quarantine receipt 登记到既有账本。一个 SourceSync 事务原子绑定治理与
隔离双证据，将平台 checkpoint 从 0 推进到 1。第二个合法 Run 必须在 provider 前命中原 commit，跳过
第二次写入并恢复原双证据。Flink checkpoint、PostgreSQL LSN 和 replication slot 都只是 provider
evidence，平台 cursor 的唯一权威仍是 `SourceSyncCheckpoint`。

本认证使用随机命名的本地短生命周期 Docker 容器，不属于 Docker Compose 常驻服务，也不运行在
Kubernetes。随机控制数据库、PostgreSQL source、Flink cluster、Silver/quarantine、checkpoint、
savepoint 和编译目录在核验后必须删除，主 Compose 的 SourceSync 表保持为空。

## Evidence

`scripts/certify_chongqing_osm_postgres_cdc.py` 调用
`scripts/flink/ChongqingOsmPostgresCdcJob.java` 完成真实运行。源 GeoParquet 为 50,366 行，SHA-256
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`；包含拒绝事件的 source slice
SHA-256 为 `dbb442fa1937cd1539087ddd7b10cd89d1be0506b21a66679bd3049cd10f8a52`。

connector JAR 为 19,541,037 字节，Maven SHA-1
`a44e29908024ab34ee9923759ef9f26cde67a2f8`，SHA-256
`e47ae8276a4acc10d77325f2a919f445a306d35184e11dcef969f692dbb28002`。Flink runtime image ID 为
`sha256:1bf0a2e91e8640900914dfd54ed605776778b1d978257e72438547004e49c6a9`；Java source 和编译 JAR
SHA-256 分别为 `09754c55a7319e4823c90b2af38b15764c9ddb78a9a5ed4bbab36f5501c8b66f` 和
`e024d2a6ba9fef934cd1b831732842f55666d2a32e72b6ade4a56b86d247544c`。

PostgreSQL 初始 LSN 为 `0/19520D0`，最终 breaking DDL LSN 为 `0/1998E48`。同一 publication、slot 和
Flink job 先后经历两个有界网络分区、三次快速断连/重连、一次 20 秒断网和 20 次高频断连/重连。
`base_mutations` 分区持续 3.246 秒，Silver/quarantine 在分区期间保持 `3/0`，slot confirmed flush LSN
保持 `0/1952108`；重连后精确追到目标 `0/1952778`，WAL lag 为 `248 -> 1,648 -> 56` bytes。
`additive_schema_evolution` 分区持续 3.477 秒，期间保持 `10/2`、confirmed LSN 保持 `0/1952778`；
nullable DDL 与投影 DML 已进入 WAL，重连后精确追到 `0/19548E0`，WAL lag 为
`56 -> 8,552 -> 0` bytes。

revision `3 -> 4` 更新在三次 0.5 秒快速 cycle 中产生目标 LSN `0/1954A48`，共持续 4.309 秒；首个
cycle 保持 `12/2`，第二个 cycle 在 slot 仍停滞时通过 checkpoint 显示 `14/2`，最终同一 slot 精确达到
目标，WAL lag 从 278,640-byte 峰值降至 278,280 bytes。revision `4 -> 5` 更新产生目标
`0/1998AB8`；该断网持续 20.310 秒，超过 15 秒 checkpoint timeout，输出保持 `14/2`，重连后
sink 与 slot 在 2.290 秒内共同恢复到 `16/2` 并精确达到目标，满足 60 秒预算。

revision `5 -> 6` 更新在 20 个配置间隔 0.1 秒的物理 cycle 中产生目标 LSN `0/1998C58`，全程持续
16.007 秒。每个 cycle 的 post-detachment LSN 与 disconnected-period LSN 相等，全部 Job 观测保持
`RUNNING`；首个 cycle 输出保持 `16/2`，到第三个 cycle 时 slot 仍停滞且输出已显示 `18/2`。最后一次
重连后 0.107 秒内达到 `18/2` 和 confirmed LSN `0/1998C90`，超过精确目标；残余 WAL 为 0 bytes，低于 1 MiB
预算。drain 后同一 slot inactive。Flink 在 checkpoint `26`、处理计数 `5` 后主动失败，attempt `1`
从 checkpointed count `3` 恢复，并在 checkpoint `165` 至 `214` 观测全部 20 条记录。18 条 Silver
changelog 和 2 条 quarantine changelog 均唯一且与预期集合相等；quarantine 原因精确为
`{"invalid_geometry_sha256": 2}`。最终源表和 Silver 重建状态均仅保留 2 条道路，内容 SHA-256
`b93fe1b834d68bb016e03b574d6dc00df91f6a6e3b28ade445a573c5d5a3bdc7`，changelog manifest SHA-256
为 `f9fa03edefba88af606876977adbe2326400e69520206da9650a4d8bd4f7937d`，SourceSync target content
SHA-256 为 `1b2935fc082f6bfaf5e2a7bf27bb8788137888cc620c87a2c19593dffa0e9a43`。

SourceSync checkpoint 从 0 精确推进到 1，仅存在一个 commit 和一次 provider write。治理证据与两条
物理拒绝记录在同一事务中绑定；同 ID 与第二个合法 Run 都恢复原双证据。18 项端到端门、20 项 provider
行为门和 4 项 schema-governance 门全部通过；全部隔离资源已删除，主 Compose 三张 SourceSync 表前后
均为 0 行。报告：
`.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`，SHA-256
`abd4a89b66cff55a866eeab3187de4e989d69e7127565a0c31936c0ff6b4bb26`。

## Consequences

- 现在可以声明 PostgreSQL 16.14 到 Flink 1.19.3 的受控真实 log-based CDC 已覆盖初始快照、WAL
  insert/update/delete、update-before/update-after、checkpoint 后失败恢复、accepted/quarantine 双
  FileSink commit、同一 slot 的重复有界网络分区与逐阶段目标 LSN catch-up、分区期间 additive DDL/DML WAL
  积压、三次快速断连/重连后的精确 DML LSN 恢复、超过 checkpoint timeout 的 20 秒断网与 60 秒
  sink/slot 联合恢复预算、20-cycle 高频断连/重连的 post-detachment LSN 停滞、精确目标和残余 WAL
  安全预算、active additive schema continuity、breaking successor fail-closed、Silver 治理绑定、非零
  隔离回执、最终状态对账和 SourceSync 双证据重放。
- 不声明 Flink/Iceberg interoperability、跨 PostgreSQL 与 sink 的分布式 exactly-once transaction、
  selected-column type/remove/rename 等更广 schema evolution、reconnect-backoff exhaustion、slot
  自动修复/恢复、生产吞吐/freshness SLO、多集群 HA 或 K8s runtime。
- 默认 Compose 不新增常驻 Flink、Kafka 或 Debezium。只有持续 workload 和 SLO 证明需要时，才冻结常驻
  deployment profile；Kubernetes Operator、外部 state backend 和 HA 需要独立验收。
- ADR-172 已独立证明 slot teardown、物理 absence 与同名新 incarnation 会在 SourceSync 0 状态下
  fail closed；ADR-173 进一步证明有限 `max_slot_wal_keep_size` 下同一槽 WAL `lost` 会在保持磁盘安全
  底线时 fail closed；ADR-174 证明 PostgreSQL 16 真实物理备库已回放、提升且时间线递增，但原 logical
  slot 缺失时仍在 SourceSync 0 状态 fail closed。AR-2 的下一项 CDC 证据应转向 selected-column schema
  migration、reconnect-backoff exhaustion、slot 自动恢复/同步、物理磁盘耗尽和恢复 SLO；已有
  Flink/Iceberg 互操作证据仍不等同于 CDC 直接写入 Iceberg。

## Revisit Triggers

- PostgreSQL 或 Flink CDC connector 升级，或生产源使用不同数据库 major、decoding plugin、publication
  policy、snapshot mode 或 slot lifecycle；
- 生产 freshness、吞吐、WAL retention 或恢复 SLO 要求持续集群、Kafka/event bus 或外部 state backend；
- Flink/Iceberg connector 完成同一 source-slice 下的 create/read/write、schema evolution、recovery、
  cancel/reconcile 和 lineage 认证。
