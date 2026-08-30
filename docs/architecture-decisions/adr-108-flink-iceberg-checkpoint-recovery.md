# ADR-108: Flink Checkpoint Recovery into Iceberg

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-107 已证明 Spark 3.5/Iceberg 1.6.1 与 Flink 1.19.3/Iceberg 1.7.2 可以对同一真实 MinIO 表完成
create/read/add-column/append/readback/time travel，但 Flink 作业是一次无故障 bounded append。它不能证明
Iceberg sink commit 与 Flink checkpoint 对齐，也不能排除 task restart 后的记录重复、丢失、断裂 snapshot
parent chain 或无法回看故障前版本。

ADR-105 的 filesystem sink recovery 和 ADR-106 的 PostgreSQL CDC recovery 也不能替代该证据：Iceberg
sink 包含 metadata JSON、manifest/list、data file 和 catalog pointer 的多对象提交协议，失败窗口与普通
filesystem part-file commit 不同。

## Decision

复用 ADR-107 冻结的运行矩阵与供应链 artifact：Spark 3.5/Iceberg 1.6.1、Flink 1.19.3/Iceberg 1.7.2、
AWS bundle、Hadoop client 3.3.4、PostgreSQL JDBC 42.7.4、隔离 PostgreSQL 16.14 JDBC Catalog 和 MinIO
S3FileIO。版本或哈希变化必须重新认证。

输入仍绑定重庆 OSM 道路 `v1.2.0` 的 50,366 行 Silver GeoParquet和同一四道路 source slice。Spark 先
创建三行 format-v2 基线；Flink 再增加 `stream_event_id` 与 `flink_commit_tag` 字段，并用 checkpointed
source 发送四条真实道路事件。每个事件具有确定性唯一 ID。

首次 Flink attempt 在 source offset 2 已进入 completed checkpoint 后主动失败。source offset 由 operator
state 保存，fixed-delay restart 只允许一次；第二次 attempt 必须从 offset 2 恢复，并在 offset 4 形成
completed checkpoint 后结束。Iceberg sink 使用 Flink checkpoint 提交，最终由 Spark 1.6.1 runtime
执行独立反向核验：

- 三条基线加四条流事件必须精确等于七行；
- 四个 `stream_event_id` 必须唯一，无重复和丢失；
- 所有 Iceberg snapshot 必须形成连续 parent chain；
- Spark 必须看到 Flink 新增 schema，并可 time travel 回故障恢复前的三行基线 snapshot；
- metadata、manifest 和 Parquet 对象图必须真实物化。

本认证只证明单 Flink job、单并行度、单 Iceberg 表内的 checkpoint recovery。它不是 PostgreSQL、Flink、
Iceberg 和 SourceSync 之间的分布式事务，也不证明 cancel 或不确定提交 reconciliation。

## Evidence

`scripts/certify_chongqing_osm_flink_iceberg_recovery.py` 调用
`scripts/flink/ChongqingOsmIcebergRecoveryJob.java` 和
`scripts/spark_chongqing_osm_iceberg_interop.py` 完成真实运行。源 GeoParquet SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，source slice SHA-256 为
`eddb0debb43294d2ad00b0c61225b07560aba433df9c57043ca5e1a298c023d0`。

Flink completed checkpoint 序列为 offset `1、2、4、4`。首次 attempt 在 checkpoint `2`、offset `2`
后主动失败；attempt `1` 从 offset `2` 恢复并完成 offset `4`。Spark 最终读取 7 行和 4 个唯一 stream
event，精确内容 SHA-256 为
`6257f6dd1eb75d5a8128cc1e04ea576b7b8ce8539b8d59e8271bf742bf74b96a`。

基线与三次有效 Flink append 形成连续 snapshot chain：

```text
347377323884820520
  -> 4389079590599987681
  -> 5630125049925351274
  -> 7385841676241407068
```

Spark 通过首个 snapshot time travel 回读原三行。MinIO 实际形成 6 个 metadata JSON、9 个 manifest/list
AVRO 和 5 个 data Parquet，共 20 个对象；inventory manifest SHA-256 为
`6cb41c2be62141330463d4945536fb77f1b0c0f45be4e9952d7b73e02cc84cab`。6 项端到端门、3 项 Flink
recovery 门和 7 项 Spark readback 门全部通过。20 个对象、随机 JDBC catalog、Flink 容器、checkpoint
和工作目录全部删除。报告：
`.tmp/source-sync-certification/chongqing-osm-flink-iceberg-recovery-report.json`，SHA-256
`8fd1e3727af3864df4f19720c7e312b3d23d5468301cd718324b082415d1e473`。

## Consequences

- 现在可以声明受控的 Flink 1.19.3/Iceberg 1.7.2 单表流写入覆盖 completed checkpoint 后 task failure、
  精确 source offset 恢复、无重复/丢失 Iceberg append、连续 snapshot chain 和 Spark 反向 time travel。
- 不能声明 cancel、kill -9/网络分区时的 uncertain commit reconciliation、跨引擎并发写、跨系统
  exactly-once、REST/Gravitino catalog、生产 SLO、HA 或 Kubernetes runtime 已完成。
- 默认 Compose 不新增常驻 Flink；本次仍使用短生命周期本地 Docker 和随机 catalog/warehouse。
- AR-2 下一项 Iceberg 可靠性证据应聚焦 cancel 与“提交已发生但控制面未确认”的 reconciliation，并验证
  重试不会产生重复 snapshot 或错误推进 SourceSync/DataProductVersion。

## Revisit Triggers

- Flink、Iceberg、Hadoop、AWS SDK、catalog 或 MinIO 版本升级；
- sink 从 append 扩展到 upsert/delete/merge、partition evolution 或多 writer；
- production profile 使用 REST/Gravitino、Kubernetes Operator、外部 state backend 或多并行度；
- workload 需要 cancel、uncertain commit、并发冲突、HA、DR、吞吐或 freshness SLO。
