# ADR-112: Snapshot-bound Key Delete Conflict Isolation

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-111 已证明 snapshot-bound 全表 overwrite 可以拒绝并发 Flink append，但 delete 的业务语义更窄：
一个 tombstone 只应删除匹配业务键的行，不能误删其他道路。若 Spark 在三行 baseline 上准备删除一个尚未
出现的道路 ID，而 Flink 随后插入该 ID，陈旧 delete 静默成功或成为 no-op 都会产生不一致结果。

Iceberg 1.6.1 的 `DeleteFiles` 支持 `deleteFromRowFilter`，但没有 `validateFromSnapshot` 或
`validateNoConflictingDataFiles`。因此它适合无并发窗口的 fresh-state commit，不能直接承担陈旧 delete
的跨引擎冲突检测。

## Decision

无分区、copy-on-write 表的受治理业务键 delete 使用两段式协议：

- 竞争阶段把 `road_id` tombstone 表达为 snapshot-bound `OverwriteFiles` intent；使用
  `overwriteByRowFilter(equal(road_id))`、`validateFromSnapshot(baseline)`、相同 key conflict filter、
  `validateNoConflictingData()` 和 `validateNoConflictingDeletes()`；
- intent 必须冻结 baseline snapshot、目标 road ID 和 delete commit token。Flink 并发追加同一 road ID
  并推进 JDBC Catalog 后才允许 Spark commit；provider 必须返回 `ValidationException`，不得创建 delete
  snapshot 或写入 delete token；
- 冲突后保留 Flink child snapshot 和四行状态。retry 是独立阶段，必须重新读取该 fresh state 并确认
  catalog 未漂移；
- 无并发 retry 使用 `DeleteFiles.deleteFromRowFilter(equal(road_id))` 删除目标 key，并把
  `gda.commit-token` 与操作语义写入 snapshot summary；最终必须精确恢复三条 baseline 非目标道路；
- reject 和 retry 都不推进 SourceSync，也不创建 `DataProductVersion`。

该决策只放行当前版本矩阵上的单表、无分区、copy-on-write、目标 key 在 baseline 缺失且与并发 insert
竞争的 delete。目标已存在、partitioned delete、equality/position delete 和 merge-on-read 必须单独认证。

## Considered Options

- **直接使用 `DeleteFiles` 做陈旧提交**：缺少 snapshot-bound 冲突验证 API，不能证明并发 insert 会被
  拒绝，不采用。
- **仅使用外部互斥锁**：无法约束独立 Flink writer，不能替代 catalog transaction validation。
- **`OverwriteFiles` conflict intent + fresh `DeleteFiles` commit**：冲突阶段获得 provider 原子校验，
  retry 阶段保留原生 delete operation 和 snapshot token，采用该方案。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_delete_conflict.py` 调用
`scripts/spark_chongqing_osm_iceberg_delete_conflict.py` 与 ADR-110 冻结的 Flink append job。输入绑定重庆
OSM 道路 `v1.2.0` 的 50,366 行 Silver GeoParquet；源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`。

Spark 创建三行 baseline snapshot `3852183994777434043`，目标 road ID `102262026` 在 baseline 中缺失。
Spark 建立绑定 baseline 的 key-delete intent 后，Flink 插入该道路并形成 child snapshot
`7418138220035788993`。释放 Spark 得到 `ValidationException`；delete 未提交、delete token snapshot 数为
0，catalog metadata location/SHA-256 与四行内容保持不变，目标 Flink 行精确存在一次。

独立 Spark retry 先读取四行 fresh state，再按 road ID 删除目标行，形成 delete snapshot
`5679521477579463743`；delete token 在 snapshot summary 中精确出现一次。最终三行内容与 baseline SHA-256
均为 `dc4a154bcfc8cf5fb76df5e7d23d4d4456e43e207b9ca7a90092010e821b273e`：

```text
3852183994777434043
  -> 7418138220035788993  # Flink inserts the target road
  -> 5679521477579463743  # Spark fresh-state key delete
```

12 项顶层门、8 项冲突门、5 项 retry 门和 8 项独立回读门全部通过。MinIO 实际形成 3 个 metadata JSON、
6 个 manifest/list AVRO 和 3 个 Parquet，共 12 个对象；inventory manifest SHA-256 为
`e67b1858f485f7f785e9dd51eed5ffc8200f49117ef69641b38d6d19687917da`。12 个对象、Spark/Flink/Catalog
容器和工作目录均已删除，主库三张 SourceSync 表保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-delete-conflict-report.json`，SHA-256
`f32cd1bf6dfd786637cfd876c273b76a931d2b21bf8922aa26cd76cc1d3cbf8c`。

## Consequences

- 现在可以声明当前冻结版本矩阵在受控 key-delete 与同 key Flink insert 竞争时，陈旧 Spark intent fail
  closed；fresh retry 只删除目标道路，不损失任何非目标行。
- destructive-write adapter 必须根据 mutation 类型选择 provider transaction；`DeleteFiles` 的 API
  能力不足时，不能用最终 job success 冒充 snapshot-bound 隔离。
- delete token 位于 snapshot summary 而不是幸存数据行；对账必须同时检查 snapshot parent、operation、
  target key、token 和最终内容 hash。
- 本证据不覆盖目标已存在时的并发 update、partitioned/equality/position delete、merge-on-read、row-level
  update/merge、自动 retry、streaming writer、网络分区、REST/Gravitino、生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- 表引入 partition evolution、delete file、merge-on-read、branch/tag 或复合业务键；
- delete retry 改为 controller 自动执行，或 SourceSync 开始消费 destructive commit；
- production profile 启用 REST/Gravitino、Kubernetes Operator、HA 或多集群 writer。
