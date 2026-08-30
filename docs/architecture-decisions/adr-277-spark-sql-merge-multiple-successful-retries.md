# ADR-277：Spark SQL MERGE 的连续成功 fresh retry

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-275](adr-275-spark-sql-merge-successful-retry.md)、[ADR-276](adr-276-spark-sql-merge-cross-process-budget.md)

## 背景

ADR-275 只证明 cardinality rejection 后的一次 fresh-state destructive retry。真实 writer
在第一次成功后还必须能够重新读取当前 snapshot，并在新的 expected revision 上继续提交，不能
把第一次 retry 当成整个 recovery 链的终点。

## 决策

沿用同一隔离 Spark/Iceberg/JDBC Catalog/MinIO slice，在同一 worker 内执行：Flink child 先把
目标 revision 推进到 2；Spark 先经历 stale duplicate-source rejection，再按 fresh source 将
revision 2 更新到 3，随后重新读取 revision 3 并将其更新到 4。每次成功写入都必须生成一个
overwrite snapshot，snapshot parent 严格连接，最终行集和 time-travel 结果按 plan 校验。

## 放行边界

本 ADR 只放行单 worker、单表、单 target、连续两次成功 fresh retry 的 bounded snapshot 链。
不代表跨进程成功 retry、provider abort recovery、跨系统 exactly-once、REST/Gravitino
destructive-write conformance、HA/RPO/RTO 或生产 SLO 已完成。

## 真实验证

入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_multiple_successful_retries.py`  
实现：`scripts/spark_chongqing_osm_iceberg_sql_merge_multiple_successful_retries.py`  
测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_multiple_successful_retries.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_multiple_successful_retries_2026-08-24.json`
SHA-256：`981d132dc581ffc72a8d9b6d4da0f991721232b0193b1b045f5d3f3a130bb873`
