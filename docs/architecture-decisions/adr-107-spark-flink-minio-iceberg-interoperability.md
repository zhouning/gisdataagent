# ADR-107: Spark, Flink and MinIO Iceberg Interoperability Boundary

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-104 已证明 Spark/Iceberg micro-batch、merge、time travel 和 SourceSync replay；ADR-105 与 ADR-106
分别证明 Flink 事件流和 PostgreSQL WAL CDC。但此前 Spark 和 Flink 从未对同一 Iceberg 表执行真实的
跨版本 create/read/write/schema evolution/readback。把 Spark 成功、Flink filesystem sink 成功或 connector
artifact 存在拼接成“Flink/Iceberg 已完成”，无法证明表 metadata、schema ID、snapshot parent chain、
manifest、Parquet 和 S3 FileIO 在两个引擎间兼容。

现有 Spark 3.5 runtime 冻结 Iceberg 1.6.1，而 Flink 1.19 的专用 Iceberg runtime 从 1.7.x 开始发布。
强行让两个引擎加载同一个 engine runtime 会破坏各自的二进制兼容性；因此验收必须显式证明相邻 Iceberg
版本对同一 format-v2 表的兼容，而不是用一个未经支持的统一 JAR 掩盖差异。

## Decision

冻结以下互操作矩阵：

| 引擎 | Iceberg runtime | FileIO / catalog | 作用 |
|---|---|---|---|
| Spark 3.5 | `iceberg-spark-runtime-3.5_2.12:1.6.1` | S3FileIO 1.6.1 / 隔离 JDBC Catalog | 创建基线，最终反向读取与 time travel |
| Flink 1.19.3 | `iceberg-flink-runtime-1.19:1.7.2` | S3FileIO 1.7.2 / 同一隔离 JDBC Catalog | 读取基线，增加列，追加记录 |
| Catalog metadata | PostgreSQL 16.14 | `JdbcCatalog` / JDBC 42.7.4 | 本次验收的可删除共享 catalog，不代表生产 catalog 选择 |
| Table storage | MinIO | 随机 `s3://gis-agent-lakehouse/acceptance/flink-iceberg/...` 前缀 | 保存 format-v2 metadata、manifest 和 Parquet |

Flink 官方基础镜像不内置 Iceberg、AWS SDK、PostgreSQL JDBC 或 Hadoop configuration API。验收器必须在
执行前同时校验 Maven SHA-1、SHA-256 和字节数，并挂载 Iceberg Flink runtime 1.7.2、AWS bundle
1.7.2、PostgreSQL JDBC 42.7.4、Hadoop client API/runtime 3.3.4。Spark 镜像内置的 Iceberg runtime、
AWS bundle 和 JDBC JAR 也必须核对 SHA-256，并显式进入 driver/executor classpath。

输入绑定已发布重庆 OSM 道路 `v1.2.0` 的 50,366 行 Silver GeoParquet，从 ADR-106 的同一 source slice
确定性选择四条道路。Spark 用前三条创建 format-v2 表；Flink 必须先读到 3 行，再增加 nullable
`flink_commit_tag` 字段并追加第四条；Spark 1.6.1 runtime 随后必须读到 5 列、4 行和精确内容，并通过
Flink 写入前的 snapshot ID 回读原 3 行。

本认证使用本地短生命周期 Docker。JDBC catalog 容器、Flink cluster、编译目录和 MinIO 随机前缀在
核验后必须删除；默认 Compose 不新增常驻 Spark、Flink 或 catalog 服务。该边界不运行在 Kubernetes。

## Evidence

`scripts/certify_chongqing_osm_flink_iceberg_interop.py` 调用
`scripts/spark_chongqing_osm_iceberg_interop.py` 和
`scripts/flink/ChongqingOsmIcebergInteropJob.java` 完成真实运行。源 GeoParquet SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，source slice SHA-256 为
`eddb0debb43294d2ad00b0c61225b07560aba433df9c57043ca5e1a298c023d0`。

Spark 基线 snapshot `4841911483547347489` 保存 3 行；Flink 追加形成 child snapshot
`5136003194891216528`，最终保存 4 行。Spark 反向读取确认新增列、精确记录和 parent chain，并通过基线
snapshot time travel 回读 3 行。基线与最终内容 SHA-256 分别为
`f535325b7baf8fdf49a15595c51d0b119b6bec59dab508270032b6f20dd2354b` 和
`e5013db48f93ed0b4519c7abbd49daeb70db12c2b0e07e4a0481aba569b600c3`。

MinIO 中实际形成 3 个 Iceberg metadata JSON、4 个 manifest/list AVRO 和 3 个 data Parquet，共 10 个
对象；对象 inventory manifest SHA-256 为
`d447686c8aec501eb25eca1d669284d56c312040ef00e7dac6985c5b5e5f4c35`。6 项端到端门全部通过；10 个对象、
随机 PostgreSQL catalog、Flink 容器和工作目录全部删除。报告：
`.tmp/source-sync-certification/chongqing-osm-flink-iceberg-report.json`，SHA-256
`778772de0868533c683b042f0d352392c0010a66d654cbce57f0132a863c419c`。

## Consequences

- 现在可以声明 Spark 3.5/Iceberg 1.6.1 与 Flink 1.19.3/Iceberg 1.7.2 在受控真实 MinIO 表上完成了
  create、read、add-column schema evolution、append、snapshot parent chain、反向 readback 和 time travel。
- 不能由此声明 streaming checkpoint recovery into Iceberg、cancel/uncertain commit reconciliation、
  跨引擎并发写隔离、跨系统 exactly-once、生产吞吐/freshness SLO、HA 或 Kubernetes runtime。
- JDBC Catalog 只是隔离共享 metadata provider；它不替代默认生产 Iceberg REST catalog，也不证明
  Gravitino catalog interoperability、备份恢复、权限、多租户或高可用。
- AR-2 下一步不再重复基础 Flink/Iceberg append，应对同一版本矩阵执行 streaming checkpoint failure、
  cancel、uncertain commit reconciliation 和并发写冲突，再单独认证 REST/Gravitino catalog provider。

## Revisit Triggers

- Spark、Flink、Iceberg、Hadoop、AWS SDK、PostgreSQL JDBC 或 MinIO 任一版本升级；
- 默认 TableCatalogProvider 从 JDBC/Hadoop acceptance provider 切换到 REST、Gravitino 或云 catalog；
- schema evolution 扩展到 rename/drop/type widening、partition evolution、delete/update/merge 或并发提交；
- 生产 workload 要求 streaming checkpoint recovery、cancel、HA、DR 或 freshness/throughput SLO。
