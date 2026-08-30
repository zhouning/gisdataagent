# ADR-282：Spark/Flink Iceberg bounded partition-spec evolution

**状态**：Accepted（2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-252](adr-252-flink-gravitino-rest-catalog-interoperability.md)、[ADR-272](adr-272-spark-sql-merge-partition-file-scope.md)

## 背景

AR-2 已经有 identity 分区表上的 Spark/Flink append、copy-on-write 和物理文件范围证据，但这些证据
都从固定 partition spec 开始。湖仓表实际演进时，旧 data file 不会因为新增 partition field 而被重写；
新 writer 必须按新 spec 写入，读路径还要同时解释旧 spec 和新 spec。若只看最终行集，无法确认 provider
是否保留旧文件、是否把新文件写到了新分区，或是否意外重写了历史对象。

## 决策

在真实 PostgreSQL JDBC Catalog、MinIO/S3FileIO、Spark 3.5/Iceberg 1.6.1 和 Flink 1.19/Iceberg 1.7.2
组合中，执行一个 disposable bounded slice：

1. Spark 创建 format-v2、无分区的三行重庆 OSM baseline。
2. Spark 执行 `ALTER TABLE ... ADD PARTITION FIELD identity(road_id)`，要求旧 snapshot 和旧 data
   file 保持不变，当前 spec 只出现 `identity(road_id)`。
3. Flink 单并行度写入一个 revision=2 row，提交必须成为 baseline 的唯一 child snapshot。
4. 独立 Spark 读取最终表和 `table.files`：最终行集、baseline time-travel、snapshot parent 链必须准确；
   spec 0 的旧无分区 file 必须保留，spec 1 的新 file 必须带目标 `road_id` partition，并且两代 spec
   必须同时可读。
5. certifier 记录运行时 artifact hash、catalog/对象图、SourceSync `[0,0,0]`，结束后删除容器、工作目录
   和 acceptance object prefix。

## 取舍

选择“无分区 -> 一个 identity field”是为了把变化范围限制在 provider 的 partition-spec 合同，避免把
schema evolution、MOR delete file 或多并发 writer 混入同一证据。使用 `table.files.spec_id` 和 partition
struct 是因为它能直接证明物理文件的 spec 归属；代价是证据依赖 Iceberg metadata-table schema，并且
不能替代跨 catalog、生产 HA 或大规模 compaction 验收。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_partition_evolution.py`  
Spark runner：`scripts/spark_chongqing_osm_iceberg_partition_evolution.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_partition_evolution.py`  
报告：`docs/reports/chongqing_osm_spark_flink_partition_evolution_2026-08-25.json`

报告 SHA-256：`bb18139dd70686de855ea343d209caaaab12e0060bc0f83c8d4504bc8282fcfb`

## 放行边界

本 ADR 只放行：单表、单次新增 `identity(road_id)` partition field、单并行度 Flink append，以及旧/新
spec 混合读取和 time-travel 的 bounded 证据。

仍未放行：多次或并发 partition evolution、schema evolution、混合 spec destructive write/MOR delete file、
跨 catalog/REST/Gravitino conformance、自动 compaction、生产 HA/RPO/RTO、Kubernetes、跨系统 exactly-once
和生产规模 SLO。
