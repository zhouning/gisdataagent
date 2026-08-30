# ADR-271：Spark SQL MERGE 跨 target 的显式 survivorship admission

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-262](adr-262-spark-sql-merge-multi-target-update.md)、[ADR-269](adr-269-spark-sql-merge-deterministic-auto-deduplication.md)

## 背景

ADR-269 已证明单个 target 的重复 source 可以按显式 rank 稳定去重。真实数据产品会在同一批
MERGE 中同时处理多个 target；如果每个 target 的 survivorship 规则不独立绑定，容易出现一个
target 的候选覆盖另一个 target，或未选 candidate token 意外落库。

## 决策

在 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO、identity(`road_id`) 单表 profile 中放行：

1. 对两个 target 各建立两条 candidate source row。
2. 按 `highest_rank_then_source_row_id_per_target` 在每个 target 内独立选择 rank 100 row，
   不跨 target 混用候选。
3. 用两条选中的 source row 执行一次 matched-update MERGE；未选 candidate token 必须缺失。
4. 保留 baseline/Flink/final time-travel 和单次 snapshot 证据。

本 ADR 不放行跨分区/多文件 survivorship，也不把 rank 规则升级为通用业务 survivorship。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_cross_target_survivorship.py`  
Spark wrapper：`scripts/spark_chongqing_osm_iceberg_sql_merge_cross_target_survivorship.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_cross_target_survivorship.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_cross_target_survivorship_2026-08-24.json`  
报告 SHA-256：`8e43422e44d29a0741de60b47f9093943661cdc63d0a832f64cbb9290db36c5d`

- 11 项顶层检查通过，真实重庆 OSM source 绑定 50,366 个要素。
- 4 条 candidate 按 target 独立选择 2 条，未选 token 缺失；最终 4 行、单次 overwrite child。
- baseline/Flink/final time-travel、3 个 metadata、8 个 manifest、6 个 Parquet 对象图通过。
- Spark/Flink/Catalog 容器、17 个对象、工作目录清理通过，主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：两个 target、每 target 两个 candidate、显式 rank 的独立 survivorship admission 和
一次单表 SQL MERGE。

仍未放行：跨分区/多文件 survivorship、跨 target 业务字段合并、缺失/冲突 rank 的自动裁决、
MERGE delete/insert 组合、SQL UPDATE join/subquery、自适应 retry/backoff、provider abort recovery、
生产 HA/RPO/RTO、Kubernetes recovery 和跨系统 exactly-once。

## Revisit trigger

当候选跨 target 共享业务身份、需要字段级合并或涉及多个分区文件时，必须新增 survivorship
definition/version、审批、冲突账本、物理对象和回滚证据；不得复用本 ADR 的 per-target rank 规则。
