# ADR-115: Partitioned Copy-on-write Delete Conflict Isolation

**Status**: Accepted
**Date**: 2026-08-02
**Related decisions**: [ADR-112](adr-112-snapshot-bound-key-delete-conflict-isolation.md),
[ADR-114](adr-114-single-operation-flink-writer-lifecycle.md)
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-112 验证了无分区表中“baseline 不存在目标 key、Flink 并发插入、Spark fresh retry 删除”的冲突
隔离，但未覆盖目标 key 已存在且表按该 key 分区的情况。分区表中，baseline revision 1 与 Flink 并发
revision 2 会位于同一个 `road_id` partition；fresh delete 必须删除两条 revision，且不能影响其他分区。

Iceberg `DeleteFiles` 可以在 identity partition 上删除完整匹配的数据文件，但其 API 仍不提供
`validateFromSnapshot` 和 `validateNoConflictingDataFiles`。因此它不能直接承担陈旧 intent 的跨引擎冲突
检测。本决策也不涉及 equality delete file、position delete file 或 merge-on-read。

## Decision Drivers

- 陈旧 delete 必须在 provider commit 边界 fail closed；
- retry 必须基于精确 Flink child snapshot，而不是隐式刷新后继续原 transaction；
- delete 只能移除目标 identity partition，非目标数据和历史 snapshot 必须可验证；
- Flink writer 必须沿用 ADR-114 的 single-operation lifecycle，并保持 classloader safety check 开启。

## Decision

`identity(road_id)`、Iceberg format v2、copy-on-write 表的分区 key delete 使用两段式协议：

- 竞争阶段建立 snapshot-bound `OverwriteFiles` conflict intent，使用目标 key row filter、
  `validateFromSnapshot(baseline)`、相同 conflict filter、`validateNoConflictingData()` 与
  `validateNoConflictingDeletes()`；
- baseline 中目标 key 必须精确存在 revision 1。Flink single-operation job 在同一 partition 追加
  revision 2 并推进 JDBC Catalog 后，才释放 Spark intent；陈旧 intent 必须得到
  `ValidationException`，不得生成 delete snapshot/token；
- fresh retry 重新读取 Flink snapshot，确认 revision 1/2 均存在，再使用
  `DeleteFiles.deleteFromRowFilter(equal(road_id))` 删除目标 partition 的所有匹配 data file；
- 最终只保留两个非目标 partition。baseline 和 Flink 后状态必须通过 snapshot ID time travel 精确回读；
- reject 与 retry 不推进 SourceSync，也不创建 `DataProductVersion`。

## Considered Options

- **直接用 `DeleteFiles` 提交陈旧 delete**：缺少 snapshot-bound conflict validation，不能证明同 partition
  append 会被拒绝，不采用。
- **只删除 revision 1**：会把 delete 解释成单版本清理而不是业务 key tombstone，留下 Flink revision 2，
  不符合本场景语义。
- **使用 equality delete file**：会引入 delete-file read compatibility 和 merge-on-read 语义，需要单独
  跨引擎认证，本阶段不采用。
- **snapshot-bound intent + fresh whole-partition data-file delete**：原子拒绝陈旧状态，retry 边界清晰，
  且不生成 row-level delete file，采用。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_partition_delete_conflict.py` 调用
`scripts/spark_chongqing_osm_iceberg_partition_delete_conflict.py` 和 ADR-114 的 single-operation Flink writer。
输入绑定重庆 OSM 道路 `v1.2.0` 的 50,366 行 Silver GeoParquet，源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`。

Spark 创建三个 identity partition 的 baseline snapshot `7612868055241374956`，目标 road ID
`102262017` 已有 revision 1。Flink 在同 partition 追加 revision 2 并形成 snapshot
`5981088398846074124`。释放 Spark 后，陈旧 delete intent 得到 `ValidationException`，revision 1/2 均
可见，delete token snapshot 数为 0，catalog 保持 Flink child。

独立 retry 从 Flink snapshot 重读后删除目标 partition 的两个 data file，形成带唯一 delete token 的
snapshot `4352072892604373082`。最终两条非目标道路逐行精确保留，内容 SHA-256 为
`04b103512410b84db60cc850437e11770b88584ded82383980874bad4020b3a4`：

```text
7612868055241374956
  -> 5981088398846074124  # Flink appends revision 2 in the target partition
  -> 4352072892604373082  # Spark deletes all target-partition data files
```

13 项顶层门、4 项 baseline 门、9 项冲突门、5 项 retry 门和 8 项独立回读门全部通过；JobManager REST
观测 `classloader.check-leaked-classloader=true`。MinIO 形成 3 个 metadata JSON、7 个 manifest/list AVRO
和 4 个 Parquet，共 14 个对象；inventory manifest SHA-256 为
`08103a00ce3f19e30a1386ee175db66874af4a4392e182fae86d3b01fe3fa145`。14 个对象、全部临时容器和工作
目录均已删除，主库 SourceSync 保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-partition-delete-conflict-report.json`，SHA-256
`77795e9698c7a989b65aa24e33778e18042e7bca9dee7a430be10ad34e441c82`。

## Consequences

- 当前冻结版本矩阵可声明：已有目标 key 的 identity-partitioned copy-on-write delete 与同 partition
  Flink append 竞争时，陈旧 intent fail closed；fresh retry 删除全部目标 revision 且不损失非目标分区。
- destructive-write adapter 必须区分 conflict authorization 和实际 `DeleteFiles` commit，并记录
  baseline、target filter、partition spec、retry source snapshot、token 和最终内容 hash。
- 此证据只移除 roadmap 中 partitioned copy-on-write delete 缺口。equality/position delete file、
  merge-on-read、partition evolution 和跨分区复合 key 仍未放行。
- 本决策不覆盖自动 retry、streaming writer、网络分区、REST/Gravitino、生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO、MinIO 或 partition spec 版本变化；
- delete 改为 equality/position delete file、merge-on-read、SQL DELETE/MERGE 或跨分区 key 变化；
- writer 变为 streaming/checkpoint sink，或 retry 改为 controller 自动执行；
- SourceSync 开始消费 destructive commit，或 production profile 启用 REST/Gravitino、HA、K8s。
