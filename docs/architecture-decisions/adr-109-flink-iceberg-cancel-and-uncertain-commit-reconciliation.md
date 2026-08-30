# ADR-109: Flink/Iceberg Cancel and Uncertain Commit Reconciliation

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-108 已证明 Flink task 在 completed checkpoint 后失败时，可以从精确 source offset 恢复并向
Iceberg 无重复追加。但它没有覆盖两个不同窗口：控制器在首个 checkpoint 前取消运行，以及 Iceberg
commit 已成功、控制器却没有收到成功确认。后者若直接重跑 provider，可能为同一 source slice 创建
重复 snapshot；若在没有 provider 证据时推进 checkpoint，又会丢数据。任何一种情况都不能直接创建
`DataProductVersion`。

## Decision

新增 fail-closed `IcebergCommitIntent -> IcebergSnapshotEvidence ->
IcebergReconciliationDecision` 合同。dispatch 前将真实 source slice SHA-256 同时冻结为 commit token，
并记录 baseline snapshot、预期终态行数、该 token 的事件数和终态内容 SHA-256。Spark 使用独立 Iceberg
runtime 对每个 snapshot 做 time-travel 回读；Flink 进程日志或客户端返回值不能单独证明提交成功。

对账规则如下：

- provider 明确返回 `CANCELED` 且不存在带 token 的 snapshot 时，结论为
  `cancelled_uncommitted`，禁止重试原运行、推进 SourceSync 或发布产品版本；
- 同一 token 可以出现在合法的中间 checkpoint snapshot，但只有事件数、终态行数、operation 和内容
  SHA-256 全部匹配的唯一终态 snapshot 才能得出 `committed_unacknowledged`；
- 终态 snapshot 缺失时保持 `not_committed`，允许上层按策略重试；终态证据不一致或出现多个终态
  snapshot 时 fail closed，必须人工处置；
- 找回唯一终态 snapshot 后，使用该 snapshot/parent/source-slice/content evidence 原子写入既有
  `SourceSyncCommit` 并推进 `SourceSyncCheckpoint` 一个版本；后续 Run 必须先调用 source-slice
  preflight，命中原 commit 后跳过 provider；
- provider commit reconciliation 不是质量、审批或发布，`publish_data_product` 固定为 false。

本次继续使用 ADR-107 冻结的 Spark 3.5/Iceberg 1.6.1、Flink 1.19.3/Iceberg 1.7.2、Hadoop 3.3.4、
PostgreSQL JDBC 42.7.4、隔离 JDBC Catalog 与 MinIO S3FileIO。默认 Compose 不增加常驻 Spark/Flink，
也不使用 Kubernetes。

## Evidence

`scripts/certify_chongqing_osm_flink_iceberg_reconciliation.py` 使用
`scripts/flink/ChongqingOsmIcebergReconciliationJob.java`、
`scripts/spark_chongqing_osm_iceberg_reconciliation.py` 和
`data_agent/iceberg_commit_reconciliation.py` 运行真实验收。输入绑定重庆 OSM 道路 `v1.2.0` 的
50,366 行 Silver GeoParquet；source slice/commit token SHA-256 为
`eddb0debb43294d2ad00b0c61225b07560aba433df9c57043ca5e1a298c023d0`。

Spark 先创建三行基线 snapshot `1013146210116708962`。取消作业已向 source 注入四行，但在 60 秒
checkpoint 周期前被真实取消；Flink REST 终态为 `CANCELED`，completed checkpoint 为 0，Spark 仍只
看到基线 snapshot。取消 Run 进入 `cancelled`，SourceSync state version/commit count 与
DataProductVersion count 均为 0。

第二个 Flink Run 在 checkpoint `1` 的 offset 3 先形成合法部分 snapshot
`7060419133769638540`，再在 checkpoint `2` 的 offset 4 形成唯一终态 snapshot
`4702256631119578052`；精确终态为七行，内容 SHA-256 为
`efcd82634e96093304cc26d5506948f33632c8f6676f303727d6ced2c96443cc`。验收故意不把 provider
成功确认交给控制面；此时 SourceSync 仍为 version 0。独立 Spark probe 找回该 snapshot 后，
SourceSync 原子推进 `0 -> 1` 且只产生一个 commit。第三个合法 Run 的 preflight 命中原 commit，未再次
执行 Flink；前后 snapshot chain 与内容 hash 完全一致，DataProductVersion count 始终为 0。

14 项端到端门全部通过。MinIO 实际形成 3 个 metadata JSON、6 个 manifest/list AVRO 和 5 个 Parquet，
共 14 个对象；inventory manifest SHA-256 为
`dd5da8d10b212b08649eaa26608e441ac17302f7b94559571a2cd3abfec13a96`。对象、随机控制数据库、
JDBC Catalog、Flink 容器、checkpoint 和工作目录全部删除，主库三张 SourceSync 表保持 `0/0/0`。
报告：`.tmp/source-sync-certification/chongqing-osm-flink-iceberg-reconciliation-report.json`，
SHA-256 `f3478cc12e1b0f71ae7bbee3095c70e17da9843000cd3f3d05b7ace671ae20ef`。

## Consequences

- 现在可以声明受控单 job、单并行度、单表 append 场景已覆盖 checkpoint 前 cancel，以及“provider
  已提交但控制面确认丢失”的确定性 reconciliation；重试不会创建重复 snapshot，SourceSync 只推进
  一次，DataProductVersion 不会被 provider commit 越权创建。
- 不能把本证据外推为 kill -9、网络分区、进程在 catalog pointer 更新期间崩溃、跨引擎并发写、
  跨系统 exactly-once、自动产品发布、REST/Gravitino catalog、生产 SLO、HA 或 Kubernetes runtime。
- 取消可能留下未被 catalog 引用的 staged object；生产 adapter 仍需提供有 retention 边界的 orphan-file
  maintenance，不能在 reconcile 前删除候选证据。
- AR-2 下一项 Iceberg 写可靠性证据聚焦跨引擎并发冲突；kill/network 分区窗口与 REST/Gravitino
  catalog 需要单独认证。

## Revisit Triggers

- sink 改为 upsert/delete/merge、partition/schema evolution 或并行 writer；
- commit token 不再能写入受治理列或 snapshot property；
- catalog、Flink/Iceberg runtime、checkpoint backend 或 object store 版本变化；
- production profile 启用 Flink Kubernetes Operator、REST/Gravitino catalog 或多集群运行。
