# ADR-106: PostgreSQL CDC, Flink Recovery and SourceSync Certification Boundary

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

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

验收变更集固定为：三条初始 insert、两次 update、两次 delete 和一条中间 insert。Flink Table/CDC
changelog 必须得到 10 条唯一记录，包括两组 update-before/update-after。首次 attempt 只在 completed
checkpoint 后、处理计数 5 时主动失败；只允许一次 fixed-delay restart。恢复后 FileSink 通过
checkpoint rolling policy 提交隔离的版本化 Bronze 文件，最终以 drain savepoint 停止。

provider 写入前调用 `find_source_slice_commit()`。首个 Run 未命中才启动 PostgreSQL/Flink；成功后用
一个 `SourceSyncCommit` 将平台 checkpoint 从 0 推进到 1。第二个合法 Run 必须在 provider 前命中原
commit，跳过第二次写入。Flink checkpoint、PostgreSQL LSN 和 replication slot 都只是 provider
evidence，平台 cursor 的唯一权威仍是 `SourceSyncCheckpoint`。

本认证使用随机命名的本地短生命周期 Docker 容器，不属于 Docker Compose 常驻服务，也不运行在
Kubernetes。随机控制数据库、PostgreSQL source、Flink cluster、Bronze、checkpoint、savepoint 和编译
目录在核验后必须删除，主 Compose 的 SourceSync 表保持为空。

## Evidence

`scripts/certify_chongqing_osm_postgres_cdc.py` 调用
`scripts/flink/ChongqingOsmPostgresCdcJob.java` 完成真实运行。源 GeoParquet 为 50,366 行，SHA-256
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`；source slice SHA-256
`eddb0debb43294d2ad00b0c61225b07560aba433df9c57043ca5e1a298c023d0`。

connector JAR 为 19,541,037 字节，Maven SHA-1
`a44e29908024ab34ee9923759ef9f26cde67a2f8`，SHA-256
`e47ae8276a4acc10d77325f2a919f445a306d35184e11dcef969f692dbb28002`。Flink runtime image ID 为
`sha256:1bf0a2e91e8640900914dfd54ed605776778b1d978257e72438547004e49c6a9`；Java source 和编译 JAR
SHA-256 分别为 `70e22f439741ede720b1f068ebfec8ab178eb938aec0865ccf4dc7fca1061b4b` 和
`24ff2487698a15ad6e8621783f39053fb56903fded52ccb765ebc1fcc1fd1c25`。

PostgreSQL 初始 LSN 为 `0/19520D0`，施加变更后的 LSN 为 `0/1952660`，slot confirmed flush LSN 为
`0/1952598`。Flink 在 checkpoint `6`、处理计数 `5` 后主动失败，attempt `1` 从 checkpointed count
`3` 恢复，并在 checkpoint `9` 完成 10 条记录。10 条 changelog 全部唯一且与预期集合相等；最终源表
和重建状态均仅保留 2 条道路，内容 SHA-256
`fb29522a568c27150a57fd5ad2678bd3a77110ee95833b4bb754c94b7e18588d`。

SourceSync checkpoint 从 0 精确推进到 1，仅存在一个 commit 和一次 provider write。第二个 Run 在写前
命中原 commit。9 项端到端门和 8 项 provider 行为门全部通过；全部隔离资源已删除，主 Compose 三张
SourceSync 表前后均为 0 行。报告：
`.tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json`，SHA-256
`3776339344874594809293a6e595f22b1fcebe4a421c4cebf068fdbd8653bba7`。

## Consequences

- 现在可以声明 PostgreSQL 16.14 到 Flink 1.19.3 的受控真实 log-based CDC 已覆盖初始快照、WAL
  insert/update/delete、update-before/update-after、checkpoint 后失败恢复、exactly-once filesystem
  commit、LSN/slot 证据、最终状态对账和 SourceSync replay。
- 不声明 Flink/Iceberg interoperability、跨 PostgreSQL 与 sink 的分布式 exactly-once transaction、活跃
  CDC 中的 schema evolution、网络分区/slot retention、生产吞吐/freshness SLO、多集群 HA 或 K8s runtime。
- 默认 Compose 不新增常驻 Flink、Kafka 或 Debezium。只有持续 workload 和 SLO 证明需要时，才冻结常驻
  deployment profile；Kubernetes Operator、外部 state backend 和 HA 需要独立验收。
- AR-2 的下一项批流证据应转向 Flink/Iceberg 精确版本互操作，并覆盖 schema evolution、cancel、
  uncertain commit reconciliation 和 lineage，而不是重复证明 filesystem sink。

## Revisit Triggers

- PostgreSQL 或 Flink CDC connector 升级，或生产源使用不同数据库 major、decoding plugin、publication
  policy、snapshot mode 或 slot lifecycle；
- 生产 freshness、吞吐、WAL retention 或恢复 SLO 要求持续集群、Kafka/event bus 或外部 state backend；
- Flink/Iceberg connector 完成同一 source-slice 下的 create/read/write、schema evolution、recovery、
  cancel/reconcile 和 lineage 认证。
