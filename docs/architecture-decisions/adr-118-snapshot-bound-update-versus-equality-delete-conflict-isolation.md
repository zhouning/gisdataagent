# ADR-118: Snapshot-bound Update versus Equality-delete Conflict Isolation

**Status**: Accepted
**Date**: 2026-08-02
**Related decisions**: [ADR-113](adr-113-partition-replace-update-conflict-isolation.md),
[ADR-117](adr-117-flink-spark-equality-delete-write-interoperability.md)
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-117 证明 Flink equality delete 能被 Spark 正确读取，但顺序互操作不能证明并发 destructive write
安全。如果 Spark 从 baseline 读取目标 key 并准备更新，而 Flink 随后删除同一个 key，陈旧 Spark
更新若继续提交，就可能隐式复活已经删除的对象。

ADR-113 已建立 snapshot-bound update intent，但其竞争方是同 partition append，不是 row-level
equality delete。equality delete 不重写原 data file；冲突检测必须依赖 Iceberg delete validation，而
不能通过 data-file pointer 变化或最终行数间接推断。

## Decision Drivers

- Spark intent 必须在 Flink delete 提交前绑定 baseline snapshot、目标 key 和 update token；
- Flink equality delete 必须在 Spark release 前成为 JDBC Catalog current snapshot；
- 陈旧 update 必须因 conflicting delete 得到 provider `ValidationException`，不得形成 Spark snapshot；
- fresh-state reconciliation 必须显式执行 delete-wins，不得默认复活缺失 key；
- rejection 和 reconciliation 均不得改变 Flink delete snapshot 或物理 delete file。

## Decision

对 required `road_id` identifier-key 表，采用以下冲突协议：

- Spark 使用 `OverwriteFiles` 建立 conflict-authorization intent，设置目标 key row filter，并调用
  `validateFromSnapshot(baseline)`、同 key `conflictDetectionFilter`、
  `validateNoConflictingData()` 和 `validateNoConflictingDeletes()`；
- intent 落盘 ready marker 后等待，不允许在 Flink commit 前提交；
- Flink bounded single-operation changelog job 对同一 `road_id` 写入 equality delete，JDBC Catalog
  current pointer 确认推进到 delete child 后才释放 Spark；
- Spark intent 必须得到 `ValidationException`。rejection 后 catalog metadata pointer、最终两行、
  equality delete file 和 update token count 必须保持不变；
- 独立 fresh-state reconciliation 读取 Flink snapshot。目标 key 缺失时返回
  `delete-wins-target-absent-no-resurrection` 和 `retry_authorized=false`，不创建 snapshot；
- 另一个独立 Spark verify 会话负责最终读取、baseline time travel 和 snapshot chain 认证；
- 此协议不推进 SourceSync，不创建 `DataProductVersion`。

## Considered Options

- **陈旧 update 直接提交**：可能复活已删除 key，且违反 snapshot-bound authorization，不采用。
- **检测目标缺失后自动 append update payload**：把 update/delete 竞争隐式解释成 resurrection，业务语义
  不明确，不采用。
- **只比较 JDBC metadata pointer**：能发现 catalog 变化，但不能证明 provider 对同 key delete 的冲突
  validation 生效，不采用。
- **snapshot-bound conflict intent + delete-wins fresh reconciliation**：provider 原子拒绝陈旧状态，且
  resurrection 需要后续显式授权，采用。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_equality_delete_conflict.py` 编排
`scripts/spark_chongqing_osm_iceberg_equality_delete_conflict.py` 和 ADR-117 的 Flink equality-delete job。
输入绑定重庆 OSM 道路 `v1.2.0` 的 50,366 行 Silver GeoParquet，源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，产品 SHA-256 为
`c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164`。

Spark intent 绑定 baseline snapshot `5601164474236121380`、目标 road ID `102262020` 和 update token
`62bb39b02fc79c3de9a63f84453a40da23dd01ca83cc97dc746a62365d7a38e6`。Flink 随后提交 equality
delete snapshot `2509358921970080915`，再释放 Spark：

```text
5601164474236121380  # Spark baseline; stale update intent waits
  -> 2509358921970080915  # Flink equality delete; remains current
```

Spark 得到 provider `ValidationException`；异常 message SHA-256 为
`22366168a24c333f8fa5dd8e0b8abb8c73d9fba92ff1b593a93ede0ee83a91c2`，update token snapshot 数为
0。fresh reconciliation 返回 `retry_authorized=false`，没有第三个 snapshot。独立 Spark 回读最终两个
非目标 key，baseline time travel 精确返回原三行。

唯一 delete file 保持 `content=2`、`record_count=1`、`equality_ids=[1]`；MinIO 直接读取的 480-byte
Parquet 仍只包含 `road_id=102262020`。14 项顶层门全部通过，JobManager REST 观测
`classloader.check-leaked-classloader=true`。MinIO 形成 4 个 metadata JSON、4 个 manifest/list AVRO 和
2 个 Parquet，共 10 个对象；inventory manifest SHA-256 为
`36019e1f5843842fb3729c7eeeed1c5390f993791a7d3b1943d3c0519f5767a5`。10 个对象、隔离
Spark/Flink/JDBC Catalog 容器和工作目录均已删除，主库 SourceSync 保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-equality-delete-conflict-report.json`，SHA-256
`7659f665a5a6e3b10bc68213e56f84320bf26964454750f5fec0f4e10e4be9b5`。

## Consequences

- 当前冻结版本矩阵可声明：Spark snapshot-bound same-key update intent 与 Flink equality delete 竞争时，
  陈旧 update fail closed，delete state 保持 current，fresh reconciliation 不隐式 resurrection。
- destructive-write controller 必须把“conflict authorization”“provider commit”和“业务重试授权”分开；
  读到 fresh state 不等于自动获得 resurrection 权限。
- 此证据只移除 update-versus-equality-delete 缺口。equality-delete/insert race、Flink position-delete
  writer、position/MOR 并发冲突和通用 SQL `UPDATE/MERGE` 仍未放行。
- 本决策不覆盖自动 retry、持续 checkpoint stream、网络分区、跨系统 exactly-once、REST/Gravitino、
  生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- equality key 改为复合键/分区键，或冲突方改为 insert、merge、position delete；
- reconciliation policy 允许 resurrection，或 controller 开始自动 retry；
- SourceSync 开始消费 destructive commit，或 production profile 启用 REST/Gravitino、HA、K8s。
