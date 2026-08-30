# ADR-116: Spark/Flink Position-delete Read Interoperability

**Status**: Accepted
**Date**: 2026-08-02
**Related decisions**: [ADR-107](adr-107-spark-flink-minio-iceberg-interoperability.md),
[ADR-114](adr-114-single-operation-flink-writer-lifecycle.md),
[ADR-115](adr-115-partitioned-copy-on-write-delete-conflict-isolation.md)
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-107 验证了 Spark 3.5/Iceberg 1.6.1 与 Flink 1.19.3/Iceberg 1.7.2 对同一 MinIO Iceberg
表的基础双向互操作，ADR-115 验证了 identity-partitioned copy-on-write delete 的冲突隔离，但两者
均未证明 Flink 能读取由 Spark 产生的 merge-on-read delete file。

仅设置 `write.delete.mode=merge-on-read` 不能证明物理 delete 类型。Spark SQL 仍可能重写 data file，
或未来因版本、分区、谓词和 planner 变化产生不同 delete 表达。因此平台必须同时检查 Iceberg
`data_files`、`delete_files` 和 `position_deletes` 元数据，再允许把验收结果标记为 position delete
互操作。

## Decision Drivers

- delete 类型必须由实际 Iceberg metadata 证明，不能由配置或 SQL 文本推断；
- 原 data file 必须保留，delete file 必须精确引用被删行的 file path 和 position；
- Flink 必须在不推进 catalog 的情况下应用 Spark delete，并保持 classloader safety check 开启；
- 最终状态和 baseline time travel 必须由独立 Spark 会话回读；
- 验收必须绑定真实重庆 OSM 产品，并清理隔离 catalog、计算容器和对象前缀。

## Decision

对当前冻结版本矩阵，采用以下 sequential read-interoperability contract：

- Spark 创建无分区 Iceberg format-v2 表，并通过单个三行 data file 建立 baseline；
- 表设置 `write.delete.mode=merge-on-read`，Spark SQL `DELETE` 精确删除一个真实 `road_id`；
- 只有同时满足以下条件才承认 position delete：当前仍只有原三行 data file；只有一个 Parquet delete
  file；其 `content=1`、`record_count=1`、`equality_ids=[]`；`position_deletes` 只有一行，且其
  `file_path` 指向原 data file、`pos >= 0`；
- Flink single-operation read job 只执行一次聚合查询，必须得到最终两行、目标零行和两个唯一
  `road_id`，且 JDBC Catalog metadata pointer 不得变化；
- 独立 Spark verify 会话必须精确回读最终两行，并通过 baseline snapshot ID 回读原三行；
- 此验收不推进 SourceSync，不创建 `DataProductVersion`。

## Considered Options

- **只检查表属性和 SQL DELETE 成功**：不能区分 copy-on-write、equality delete 和 position delete，
  不采用。
- **只检查 `delete_files` 存在**：不能证明 delete 内容类型及其引用的原 data file，不采用。
- **让同一个 Spark 会话完成创建、删除和最终认证**：会把 session cache 和 writer 自证带入结果，
  不采用。
- **Spark metadata 认证 + Flink 单查询读取 + 独立 Spark time travel**：物理类型、跨引擎可见性和
  历史状态都有独立证据，采用。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_position_delete_interop.py` 编排
`scripts/spark_chongqing_osm_iceberg_position_delete_interop.py` 和
`scripts/flink/ChongqingOsmIcebergPositionDeleteReadJob.java`。输入绑定重庆 OSM 道路 `v1.2.0` 的
50,366 行 Silver GeoParquet，源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，产品 SHA-256 为
`c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164`。

Spark baseline snapshot `1900874321495101054` 包含一个三行 Parquet data file。Spark SQL 删除目标
road ID `102262020` 后形成 delete snapshot `4530004807812808454`，原 data file 保留；新增的唯一
Parquet delete file 为 `content=1`、`record_count=1`、`equality_ids=[]`，其唯一 position delete
指向原 data file 的 position `1`：

```text
1900874321495101054  # Spark append: one data file, three rows
  -> 4530004807812808454  # Spark MOR delete: one position delete file
```

Flink 聚合读取返回 `rows=2`、`target_rows=0`、`distinct_roads=2`，读取前后 catalog pointer 不变；
独立 Spark 回读最终两行并通过 baseline snapshot 回读原三行。10 项顶层门全部通过，JobManager REST
观测 `classloader.check-leaked-classloader=true`。MinIO 形成 2 个 metadata JSON、4 个 manifest/list
AVRO 和 2 个 Parquet，共 8 个对象；inventory manifest SHA-256 为
`1e462144ee7b208ecf80df1309d9d79cb1ca1dea707dd85b75a540660d9791d9`。8 个对象、隔离 Flink/JDBC
Catalog 容器和工作目录均已删除，主库 SourceSync 保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-position-delete-interop-report.json`，SHA-256
`e0a0c5ed96b6e2208a6a2efe05aaba91db37fab1b63cdc5e75e999a340c4eaa5`。

## Consequences

- 当前冻结版本矩阵可声明：Flink 1.19.3/Iceberg 1.7.2 能正确读取 Spark 3.5/Iceberg 1.6.1 在无分区
  format-v2 表上产生的单行 MOR position delete。
- destructive-write 证据模型必须记录 table properties、data/delete file content、equality IDs、
  referenced data file、position、snapshot chain 和跨引擎 readback，不能只记录 SQL 成功。
- 此证据只移除 sequential position-delete/MOR read interoperability 缺口。equality delete、Flink 侧
  position-delete 写入、并发 position-delete conflict isolation 和复杂多 delete-file planning 仍未放行。
- 本决策不覆盖自动 retry、streaming/checkpoint writer、网络分区、REST/Gravitino、生产 SLO、HA 或
  K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- 表改为分区表，delete 谓词改为范围/复合谓词，或一次产生多个 data/delete file；
- Flink 开始写 position/equality delete，或多个引擎并发执行 destructive write；
- SourceSync 开始消费 delete commit，或 production profile 启用 REST/Gravitino、HA、K8s。
