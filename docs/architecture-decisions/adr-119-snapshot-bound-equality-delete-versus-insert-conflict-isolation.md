# ADR-119: Snapshot-bound Equality-delete versus Insert Conflict Isolation

**Status**: Accepted
**Date**: 2026-08-02
**Related decisions**: [ADR-112](adr-112-snapshot-bound-key-delete-conflict-isolation.md),
[ADR-117](adr-117-flink-spark-equality-delete-write-interoperability.md),
[ADR-118](adr-118-snapshot-bound-update-versus-equality-delete-conflict-isolation.md)
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-112 证明无分区 copy-on-write key delete 能拒绝同 key insert，ADR-117 证明 Flink equality delete
能被 Spark 正确读取，ADR-118 则证明 Spark update intent 能拒绝并发 equality delete。三者都没有覆盖
相反方向的 row-level 风险：Spark 在目标 key 尚不存在时授权删除，Flink 随后插入该 key，陈旧删除若仍
被允许提交，就会删除授权建立之后才出现的新对象。

此场景还要求把普通 insert 与 upsert 明确区分。若表启用 Flink upsert，`INSERT INTO` 会形成
overwrite 并预先产生 equality delete，无法证明干净的 append-versus-delete 冲突链。

## Decision Drivers

- delete intent 必须在 Flink insert 前绑定 baseline snapshot、缺失的目标 key 和 authorization token；
- Flink insert 必须是单次 provider append，不能通过 upsert/overwrite 预先产生 delete file；
- 陈旧 delete authorization 必须得到 provider `ValidationException`，且不得形成 delete snapshot；
- fresh-state authorization 必须由独立 Spark 会话读取 insert snapshot，且授权动作本身不创建 snapshot；
- 实际 equality delete 必须由单独的 Flink bounded job 提交，并由 Spark、Iceberg metadata 和 MinIO
  物理文件三方验证。

## Decision

对 required `road_id` identifier-key 的无分区 Iceberg format-v2 表，采用以下协议：

- baseline 显式设置 `write.upsert.enabled=false` 和 merge-on-read delete，保证 Flink 普通
  `INSERT INTO` 形成 append snapshot；
- Spark 使用 `OverwriteFiles` 建立 conflict-authorization intent，设置目标 key row filter，并调用
  `validateFromSnapshot(baseline)`、同 key `conflictDetectionFilter`、
  `validateNoConflictingData()` 和 `validateNoConflictingDeletes()`；
- intent 落盘 ready marker 后等待。Flink single-operation insert 提交目标 key，JDBC Catalog current
  pointer 确认推进到 append child 后才释放 Spark；
- Spark intent 必须得到 `ValidationException`。rejection 后 insert snapshot、四行内容和 authorization
  token count 必须保持不变；
- 独立 Spark 会话精确读取 insert snapshot，并显式返回 `retry_authorized=true`；授权阶段不得生成 snapshot；
- 另一个 Flink bounded single-operation DELETE changelog job 提交 equality delete；独立 Spark 验证
  当前三行、baseline/insert time travel 和 `append -> append -> delete` 链；
- MinIO 直接读取唯一 delete Parquet，必须只包含目标 `road_id`；
- 此协议不推进 SourceSync，不创建 `DataProductVersion`。

## Considered Options

- **保持 `write.upsert.enabled=true` 执行 insert**：实际形成 overwrite 并提前产生 equality delete，污染
  预期冲突链，不采用。
- **陈旧 authorization 继续删除新插入 key**：删除了授权快照之后出现的对象，违反 snapshot-bound
  admission，不采用。
- **冲突后由同一 Spark 会话直接删除**：混合 rejection、reconciliation 与 provider commit，无法证明
  fresh-state 边界，不采用。
- **fail-closed intent + 独立 fresh authorization + 单独 Flink equality delete**：每个责任边界均有独立
  evidence，采用。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_equality_delete_insert_conflict.py` 编排
`scripts/spark_chongqing_osm_iceberg_equality_delete_insert_conflict.py`、
`scripts/flink/ChongqingOsmIcebergSingleInsertJob.java` 和 ADR-117 的 Flink equality-delete job。输入绑定
重庆 OSM 道路 `v1.2.0` 的 50,366 行 Silver GeoParquet，源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，产品 SHA-256 为
`c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164`。

Spark intent 绑定 baseline snapshot `1782047989754050381`、缺失的目标 road ID `102262026` 和
authorization token `5099f88b4a668d63e48347acdcbb523202d267b731c81b293a8640e48f9dbadd`。Flink insert
使用 token `e8e24612f6cf6da2c05cb6e6cab22cdeb170531c05d7bf41cb511227901f0341` 提交 append snapshot
`5470072260186311897` 后才释放 Spark。陈旧 intent 得到 provider `ValidationException`，异常 message
SHA-256 为 `f3a2efc27d1c81d5f48ac3a1b09f2f4dedee6c1f20b2c4c1b4b700d7c4a8464f`，没有形成
authorization snapshot。fresh-state 会话读取四行并授权重试，但未创建 snapshot。Flink 随后使用 token
`f2fd96d8f185863812e40cfddde848ab7f69733b3f04ef1f652443e824727a22` 提交 delete snapshot：

```text
1782047989754050381  # Spark baseline; target absent; stale delete intent waits
  -> 5470072260186311897  # Flink append; target appears exactly once
    -> 8032818360618988207  # Flink equality delete after fresh authorization
```

独立 Spark 当前读取精确恢复 baseline 三行，baseline 与 insert snapshot time travel 分别精确返回三行和
四行。唯一 delete file 为 `content=2`、`record_count=1`、`equality_ids=[1]`；MinIO 直接读取的
2,260-byte Parquet 只包含 `road_id=102262026`，文件 SHA-256 为
`f1225622c066670701bf6a01e458338c8ae81035561f50dc88645653723452e1`。

16 项顶层门全部通过，JobManager REST 观测 `classloader.check-leaked-classloader=true`。MinIO 形成
5 个 metadata JSON、6 个 manifest/list AVRO 和 3 个 Parquet，共 14 个对象；inventory manifest
SHA-256 为 `5b9bcbde99402fa30e53f334cc2bc0be0b8003d67f0ac1f23b37d0524cb5f128`。14 个对象、隔离
Spark/Flink/JDBC Catalog 容器和工作目录均已删除，主库 SourceSync 保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-equality-delete-insert-conflict-report.json`，
SHA-256 `af051adf8d4e54c467b29d42db0b33f7d1c0bd21c965c303d606a8a26398bafe`。

## Consequences

- 当前冻结版本矩阵可声明：snapshot-bound same-key equality-delete authorization 与 Flink append insert
  竞争时，陈旧删除 fail closed；在独立 fresh authorization 后，Flink equality delete 可安全提交并被
  Spark 正确应用。
- insert adapter 必须显式区分 append 与 upsert；普通 insert 不能因表级 upsert 设置隐式制造 delete file。
- destructive-write controller 必须把 conflict authorization、fresh-state retry authorization 和 provider
  commit 分开记录，不能把冲突后的 fresh read 等同于自动执行删除。
- 此证据只移除 equality-delete/insert race 缺口。Flink position-delete writer、position/MOR 并发冲突和
  通用 SQL `UPDATE/MERGE` 仍未放行。
- 本决策不覆盖自动 retry、持续 checkpoint stream、网络分区、跨系统 exactly-once、REST/Gravitino、
  生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- equality key 改为复合键/分区键，或 insert 改为 upsert、merge、持续 stream；
- controller 自动执行 retry/delete，或 authorization 与 provider commit 合并；
- SourceSync 开始消费 destructive commit，或 production profile 启用 REST/Gravitino、HA、K8s。
