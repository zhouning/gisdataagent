# ADR-117: Flink/Spark Equality-delete Write Interoperability

**Status**: Accepted
**Date**: 2026-08-02
**Related decisions**: [ADR-114](adr-114-single-operation-flink-writer-lifecycle.md),
[ADR-116](adr-116-spark-flink-position-delete-read-interoperability.md)
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-116 验证了 Spark 产生 position delete、Flink 正确读取的顺序互操作，但没有覆盖反向的 row-level
delete 写入。对 identifier-key 表，Flink upsert sink 通常使用 equality delete；Spark 必须能应用该
delete file，平台也必须证明物理内容确实是 equality key，而不是仅看到最终行数减少。

Flink 1.19 的 batch planner 不接受产生 DELETE changelog 的 table source。因此本场景不能用 batch
runtime 伪装成 row-level changelog；它需要 bounded streaming execution，但输入仍是唯一的内存 DELETE
事件，作业完成后退出。本决策不把该执行方式外推为持续 streaming 或 checkpoint exactly-once 认证。

## Decision Drivers

- Iceberg equality field 必须从表创建开始就是 required identifier，不能通过不兼容 schema promotion
  绕过约束；
- Flink job 只允许一个 provider DML，不在同一作业内自证最终状态；
- equality delete 类型、field ID、record count 和实际 key 均必须由独立证据证明；
- Spark 必须正确应用 delete，并能按 baseline snapshot ID 回读被删前状态；
- 验收必须绑定真实重庆 OSM 产品，保持 classloader safety check 开启，并完全清理隔离资源。

## Decision

对当前冻结版本矩阵，采用以下 sequential equality-delete interoperability contract：

- Spark 通过显式 DDL 创建无分区 Iceberg format-v2 表，`road_id BIGINT NOT NULL`，随后把 `road_id`
  设置为唯一 identifier field，并写入单个三行 data file；
- 表启用 `write.upsert.enabled=true` 和 merge-on-read delete；
- Flink 使用 bounded streaming runtime，把唯一 `RowKind.DELETE` changelog 通过单个 `INSERT INTO`
  provider operation 提交到表；事件 schema 的 primary key 为 `road_id`；
- 独立 Spark verify 必须确认原三行 data file 保留，当前只有一个 Parquet delete file，且
  `content=2`、`record_count=1`、`equality_ids=[road_id field ID]`；
- 验收进程使用已认证的 MinIO client 直接读取物理 delete Parquet，必须只包含目标 `road_id`；
- Spark 当前读取必须精确得到两个非目标 key，baseline snapshot time travel 必须恢复原三行；
- 此验收不推进 SourceSync，不创建 `DataProductVersion`。

## Considered Options

- **在 optional key 上强制 identifier promotion**：Iceberg 正确拒绝；使用
  `allowIncompatibleChanges` 会弱化表契约，不采用。
- **使用 Flink batch runtime 发送 DELETE changelog**：Flink planner 明确拒绝非 insert-only batch
  source，不采用。
- **只验证 Spark 最终少一行**：不能区分 equality delete、position delete 和 data-file rewrite，
  不采用。
- **bounded DELETE changelog + Spark metadata/time travel + MinIO physical Parquet read**：同时覆盖 writer、
  reader、物理类型和 key 内容，采用。

## Evidence

`scripts/certify_chongqing_osm_flink_spark_equality_delete_interop.py` 编排
`scripts/flink/ChongqingOsmIcebergEqualityDeleteJob.java` 和
`scripts/spark_chongqing_osm_iceberg_equality_delete_interop.py`。输入绑定重庆 OSM 道路 `v1.2.0` 的
50,366 行 Silver GeoParquet，源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，产品 SHA-256 为
`c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164`。

Spark baseline snapshot `7612760372706970596` 包含一个三行 Parquet data file，`road_id` 是 required
identifier field ID `1`。Flink 删除目标 road ID `102262020` 后形成 delete snapshot
`5071582648221677531`：

```text
7612760372706970596  # Spark append: one data file, three rows
  -> 5071582648221677531  # Flink bounded changelog: one equality delete file
```

原 data file 保持三行；新增的唯一 Parquet delete file 为 `content=2`、`record_count=1`、
`equality_ids=[1]`。MinIO 直接读取表明该物理文件为 480 bytes、SHA-256
`ea96e4bd540d956813f2672260842df3b999171b748b03c6ab5bea910e2b9db0`，只包含
`road_id=102262020`。Spark 当前读取精确返回两个非目标 key，baseline time travel 精确返回原三行。

10 项顶层门全部通过，JobManager REST 观测 `classloader.check-leaked-classloader=true`。MinIO 形成
4 个 metadata JSON、4 个 manifest/list AVRO 和 2 个 Parquet，共 10 个对象；inventory manifest
SHA-256 为 `abd9a965448ea2d6602761d3924b46969a21d540096c11addd0100462ede239a`。10 个对象、隔离
Flink/JDBC Catalog 容器和工作目录均已删除，主库 SourceSync 保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-flink-spark-equality-delete-interop-report.json`，SHA-256
`bbc1c222460b4c8dbd7724be97c5acdc8910e583c4fb88c999052b620917b49b`。

## Consequences

- 当前冻结版本矩阵可声明：Flink 1.19.3/Iceberg 1.7.2 能以 bounded changelog 写入单 key equality
  delete，Spark 3.5/Iceberg 1.6.1 能正确应用并 time travel。
- identifier/equality-delete adapter 必须记录 required key、identifier field ID、changelog kind、物理
  delete content、equality IDs、key payload、snapshot chain 和跨引擎 readback。
- 此证据只移除 sequential equality-delete write/read interoperability 缺口。并发 equality-delete
  conflict isolation、Flink position-delete writer、复合 equality key 和持续 checkpoint stream 仍未放行。
- 本决策不覆盖自动 retry、网络分区、跨系统 exactly-once、REST/Gravitino、生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- equality key 改为复合键/分区键，或一次提交多个 delete/data file；
- 作业改为持续 stream/checkpoint sink，或多个引擎并发执行 destructive write；
- SourceSync 开始消费 delete commit，或 production profile 启用 REST/Gravitino、HA、K8s。
