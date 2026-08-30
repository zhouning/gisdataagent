# ADR-120: Flink/Spark Position-delete Write Interoperability

**Status**: Accepted
**Date**: 2026-08-02
**Related decisions**: [ADR-114](adr-114-single-operation-flink-writer-lifecycle.md),
[ADR-116](adr-116-spark-flink-position-delete-read-interoperability.md),
[ADR-119](adr-119-snapshot-bound-equality-delete-versus-insert-conflict-isolation.md)
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-116 证明 Flink 能读取 Spark 生成的 position delete，但没有证明反向 writer 能力。Flink SQL 的
row-level changelog sink 原生表达 equality delete，不提供一个可直接绑定已有 data file path 和 row
position 的 position-delete SQL 合同。因此不能用 `DELETE` SQL 或 equality changelog 冒充 Flink
position-delete writer。

平台仍需要这个能力来支持已掌握 `_file/_pos` 的受控删除、跨引擎维护和后续 position/MOR 冲突隔离。
实现必须在 Flink TaskManager 内运行，使用冻结的 Iceberg provider API 提交，并把低层 adapter 的边界
与通用 Flink SQL 能力明确区分。

## Decision Drivers

- Spark baseline 必须把业务 key 绑定到 Iceberg 隐藏列 `_file/_pos`，不能假设 Parquet 行序；
- writer 必须在 Flink TaskManager 内运行，只有一个 task、一次 `RowDelta.commit()`，且关闭自动重启；
- commit 必须绑定 baseline snapshot，并验证被引用 data file 仍存在且未被删除；
- 独立 Spark 必须验证最终行、baseline time travel、snapshot token 和物理 delete 类型；
- MinIO 必须直接读取 delete Parquet，证明其唯一 `file_path/pos` 与 baseline 绑定完全一致；
- 验收必须保持 classloader safety check 开启，并清理全部隔离资源。

## Decision

对当前冻结版本矩阵，采用专用 Flink position-delete adapter：

- Spark 3.5/Iceberg 1.6.1 创建无分区 format-v2、merge-on-read 表，以一个三行 data file 建立
  baseline，并通过 `_file/_pos` 找到目标 `road_id` 的精确物理引用；
- Flink 作业用单元素 DataStream 和 `executeAndCollect()` 把 writer 代码放入唯一 TaskManager task，
  并设置 `RestartStrategies.noRestart()`，避免 provider commit 失败后由作业框架隐式重放；
- TaskManager 使用冻结的 Iceberg 1.7.2 `GenericAppenderFactory.newPosDeleteWriter()` 写一个 Parquet
  position-delete file；
- 唯一 `RowDelta` 调用 `addDeletes()`、`validateFromSnapshot()`、
  `validateDataFilesExist()`、`validateDeletedFiles()`、目标 key conflict filter，以及 conflicting
  data/delete validations，再携带确定性 commit token 提交；
- JobManager REST 必须只观测到一个 `FINISHED` job 和一个 finished task；
- 独立 Spark 会话验证原 data file 保留、唯一 delete file 为 `content=1`、`record_count=1`、
  `equality_ids=[]`，当前两行、baseline 三行 time travel 和 `append -> delete` chain 均准确；
- MinIO/PyArrow 直接读取 delete Parquet 的 `file_path` 和 `pos`；
- 此 adapter 不推进 SourceSync，不创建 `DataProductVersion`，不声明 Flink SQL position-delete 支持。

## Considered Options

- **使用 Flink SQL DELETE 或 DELETE changelog**：前者没有已认证的 position-delete writer 合同，后者
  产生 equality delete，不采用。
- **在 `flink run` 客户端进程直接调用 Iceberg commit**：不能证明 TaskManager 执行边界，不采用。
- **允许 Flink 自动重启 writer task**：当前没有 checkpoint-bound provider commit 去重协议，可能重复
  提交，不采用。
- **单 TaskManager task + low-level writer + RowDelta validations + 独立三方验证**：物理引用、provider
  commit 和跨引擎消费均可核验，采用。

## Evidence

`scripts/certify_chongqing_osm_flink_spark_position_delete_interop.py` 编排
`scripts/flink/ChongqingOsmIcebergPositionDeleteWriteJob.java` 和
`scripts/spark_chongqing_osm_iceberg_flink_position_delete_interop.py`。输入绑定重庆 OSM 道路 `v1.2.0`
的 50,366 行 Silver GeoParquet，源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，产品 SHA-256 为
`c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164`。

Spark baseline snapshot `3121089764148917328` 以一个三行 Parquet data file 保存道路
`102262017`、`102262020`、`102262024`；隐藏列证明目标 `road_id=102262020` 位于该文件 position
`1`。Flink TaskManager 使用 commit token
`4cb1ccb3caaf35521264084ecfcaff99a206b93401d0d4ca120ec69d71453793` 提交 delete snapshot：

```text
3121089764148917328  # Spark append: one data file, target at position 1
  -> 1910388505160970892  # Flink RowDelta: one position delete file
```

JobManager REST 只观测到一个 `FINISHED` job、一个 finished task、零 failed/canceled task。独立 Spark
确认原三行 data file 保留，唯一 delete file 为 `content=1`、`record_count=1`、`equality_ids=[]`，
当前精确返回两个非目标 key，baseline time travel 精确返回原三行，delete snapshot summary 携带上述
Flink token。

MinIO/PyArrow 直接读取的 1,882-byte delete Parquet 只有 `file_path`、`pos` 两列和一行，精确引用
baseline data file 的 position `1`；文件 SHA-256 为
`e1a6ba9f30d2dbe34ad546bf6fa995ee99529830c6986aa7cf965ebe44a53746`。12 项顶层门全部通过，
JobManager REST 观测 `classloader.check-leaked-classloader=true`。MinIO 形成 2 个 metadata JSON、
4 个 manifest/list AVRO 和 2 个 Parquet，共 8 个对象；inventory manifest SHA-256 为
`0d6b78c05277463ae21480bc853dc2082012caf1fa57f9b499a9d8165a38f2fe`。8 个对象、隔离
Flink/JDBC Catalog 容器和工作目录均已删除，主库 SourceSync 保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-flink-spark-position-delete-interop-report.json`，SHA-256
`ec13afd09a3d8617519c112461009495da8265131cc3b53beb43489549fd95d5`。

## Consequences

- 当前冻结版本矩阵可声明：Flink TaskManager 能通过受控 low-level adapter 写入单 data file、单 row
  的 position delete，Spark 能正确应用并 time travel。
- `compile_flink_job` 允许显式传入 repository-local、已冻结的额外编译 classpath；默认空值保持既有
  Flink 作业行为不变，运行时 artifact 身份仍由验收器逐项校验。
- 平台必须把此能力登记为专用 position-delete adapter，而不是宣称通用 Flink SQL DELETE 已支持。
- 此证据只移除 Flink 侧单文件单行 position-delete writer 缺口。position/MOR 并发冲突、分区/多文件
  delete、通用 SQL `UPDATE/MERGE` 仍未放行。
- 本决策不覆盖自动 retry、checkpoint-bound writer、网络分区、cross-system exactly-once、
  REST/Gravitino、生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- writer 扩展为分区表、多 data/delete file、范围删除或复合业务键；
- Flink SQL 增加并认证原生 position-delete writer，或作业启用 restart/checkpoint；
- 多个引擎并发执行 position/MOR destructive write，或 SourceSync 开始消费该 commit；
- production profile 启用 REST/Gravitino、HA 或 K8s。
