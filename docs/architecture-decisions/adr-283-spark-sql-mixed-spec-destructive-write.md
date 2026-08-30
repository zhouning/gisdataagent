# ADR-283：Spark SQL mixed-spec destructive write 的 COW provider 边界

**状态**：Accepted（2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-282](adr-282-spark-flink-iceberg-partition-evolution.md)、[ADR-272](adr-272-spark-sql-merge-partition-file-scope.md)

## 背景

ADR-282 只证明了旧 spec 和新 spec 可以共存并被读取。下一步需要确认 destructive write 在两代 spec
同时存在时是否扩大物理影响范围。这个问题不能只看最终行集：目标道路在 spec 0 的旧无分区 file 和
spec 1 的新 identity 分区 file 中各有一行，guard 道路仍在旧 file 中；一次 SQL `DELETE` 必须能把
目标两代数据一起处理，同时保留 guard。

## 决策

在真实 PostgreSQL JDBC Catalog、MinIO/S3FileIO、Spark 3.5/Iceberg 1.6.1 和 Flink 1.19/Iceberg 1.7.2
组合中，执行一个 bounded destructive-write slice：

1. Spark 创建 format-v2 表并请求 `write.delete.mode=merge-on-read`，写入三行 baseline。
2. Spark 新增 `identity(road_id)` partition field；Flink 单并行度 append 目标道路 revision=2，形成
   spec 1 文件，使目标道路同时存在于 spec 0 和 spec 1。
3. Spark 执行 `DELETE FROM table WHERE road_id = target`，记录删除前后的 `table.files`、隐藏列
   `_file/_pos`、snapshot parent 和最终行集。
4. 通过条件为：目标涉及的两个旧 data file 被精确移除、非目标 guard file 保留、只产生一个 delete
   snapshot、baseline/Flink time-travel 保持准确，并且没有额外 delete file。

这里的“没有 delete file”是 provider 的真实结果，不是测试绕过：当前版本矩阵把该 SQL DELETE 落成
copy-on-write，即使表属性请求了 merge-on-read。证据因此放行 COW 物理范围，不把请求属性误报成 MOR
实现。

## 取舍

选择一个同时跨 spec 的逻辑 key，能把 partition evolution、destructive admission 和物理文件范围放进
同一条 snapshot 链；代价是只覆盖 SQL DELETE，不代表 UPDATE/MERGE、compaction 或并发 writer。保留
`write.delete.mode=merge-on-read` 请求并记录 provider 实际 COW 行为，是为了让后续 MOR conformance
有可复现的失败基线。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_mixed_spec_mor_delete.py`  
Spark runner：`scripts/spark_chongqing_osm_iceberg_mixed_spec_mor_delete.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_mixed_spec_mor_delete.py`  
报告：`docs/reports/chongqing_osm_spark_flink_mixed_spec_mor_delete_2026-08-25.json`  
报告 SHA-256：`1b8843b2cc511817c8cd3c45668412dd643881523a895f7dbe3e9d5f710858d1`

## 放行边界

本 ADR 放行：单表、一次 `identity(road_id)` evolution、单并行度 Flink append、一次跨 spec SQL DELETE
的 copy-on-write 文件范围对账，以及旧/Flink/final time-travel。

仍未放行：MOR delete-file 物理写入、跨 spec UPDATE/MERGE、多次或并发 evolution、并发 destructive writer、
compaction、REST/Gravitino conformance、生产 HA/RPO/RTO、Kubernetes、跨系统 exactly-once 和生产规模 SLO。
