# ADR-284：Spark/Flink mixed-spec equality delete capability probe

**状态**：Capability probe failed / unsupported（2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-282](adr-282-spark-flink-iceberg-partition-evolution.md)、[ADR-283](adr-283-spark-sql-mixed-spec-destructive-write.md)、[ADR-117](adr-117-flink-spark-equality-delete-write-interoperability.md)

## 背景

ADR-282 证明了旧 spec 和新 spec 可以共存，ADR-117 证明了无分区表上的 Flink equality delete 可以被
Spark 读取。下一步要确认这两项能力能否组合：同一个 `road_id` 同时存在于 spec 0 的旧无分区 data file
和 spec 1 的新 identity 分区 data file 时，Flink equality delete 是否能删除两代数据。

## 验证切片

真实切片按以下顺序执行：

1. Spark 用显式 `NOT NULL` schema 创建 format-v2 baseline，并将 `road_id` 注册为 identifier field。
2. Spark 执行 `ADD PARTITION FIELD identity(road_id)`。
3. Flink 1.19.3 append revision=2，使目标道路同时存在于 spec 0 和 spec 1。
4. Flink 1.19.3 提交单键 equality delete；Spark 独立检查最终行集、`table.files`、`delete_files`、identifier
   field id、snapshot parent 和 baseline/Flink time-travel。

真实报告同时记录了容器、artifact、对象图和主库 SourceSync `[0,0,0]` 清理结果。

## 结果

当前 PostgreSQL JDBC Catalog + MinIO/S3FileIO + Spark 3.5/Iceberg 1.6.1 + Flink 1.19/Iceberg 1.7.2
组合的结果是：

- equality-delete Parquet files 已物化，`content=2`、`record_count=1`、`equality_ids=[1]`，且 Flink
  equality-delete job 本身通过；
- evolved spec 的 revision=2 目标行被删除；
- legacy spec 0 的 revision=1 目标行仍然可见，最终 `road_id` 仍存在；
- snapshot operation 实际为 `append -> overwrite -> delete`，不是预设的 `append -> append -> delete`；
- provider 生成两个 equality-delete files，snapshot summary 没有自动携带 commit token。

因此这不是跨 spec equality delete 的通过证据，而是可复现的 provider capability probe 失败。

## 决策

在该版本矩阵下，平台不得把 equality-delete 请求用于包含历史混合 partition spec 的表。写入 admission
必须先确认目标数据只位于当前 evolved spec，或先通过受控 compaction/rewrite 消除旧 spec；否则应
fail-closed，并保留 capability probe receipt。ADR-117 的单一 spec 顺序 equality-delete interoperability
仍然有效，ADR-284 不回滚它。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_mixed_spec_equality_delete.py`  
Spark runner：`scripts/spark_chongqing_osm_iceberg_mixed_spec_equality_delete.py`  
Flink append job：`scripts/flink/ChongqingOsmIcebergPartitionAppendJob.java`  
Flink equality-delete job：`scripts/flink/ChongqingOsmIcebergEqualityDeleteJob.java`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_mixed_spec_equality_delete.py`  
报告：`docs/reports/chongqing_osm_spark_flink_mixed_spec_equality_delete_2026-08-25.json`  
报告 SHA-256：`36f3860cab93d039cb991df2bf7a67eb0478856069f53175fc4c4b5ae4ac56a3`

平台 admission：`data_agent.fusion.lakehouse_publisher.build_iceberg_equality_delete_admission`；
在真实 `data_spec_ids=[0,1]`、`current_spec_id=1` 证据上返回 `rejected`，并记录
`mixed_partition_specs_detected`、`cross_spec_equality_delete_unsupported` 和
`controlled_rewrite_required_before_equality_delete`。

## 放行边界

本 ADR 放行：identifier field 注册、两代 spec 共存、Flink equality-delete file 物化和 evolved-spec
删除结果的真实观测；它不放行跨 partition spec equality delete。

仍未放行：混合 spec UPDATE/MERGE、自动 compaction/rewrite、多个 equality-delete files 的业务语义、
并发 writer、REST/Gravitino conformance、生产 HA/RPO/RTO、Kubernetes、跨系统 exactly-once 和生产 SLO。
