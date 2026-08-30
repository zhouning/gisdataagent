# ADR-278：Spark SQL MERGE 的跨进程成功 fresh retry

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-276](adr-276-spark-sql-merge-cross-process-budget.md)、[ADR-277](adr-277-spark-sql-merge-multiple-successful-retries.md)

## 背景

ADR-276 只证明共享 retry-budget admission，ADR-277 只证明同一 worker 内连续成功 retry。
还需要证明第二个独立进程可以读取第一个进程提交的当前 snapshot，并在新的 expected revision
上继续 destructive write，而不是依赖 worker 内存状态。

## 决策

在同一隔离 JDBC Catalog、MinIO 和 Iceberg 表上运行两个独立 Spark 容器。Flink child 先将目标
推进到 revision 2；first worker 处理 stale duplicate source 并提交 revision 3；second worker
重新读取 revision 3 后提交 revision 4。独立 verify 读取 revision 3 中间 snapshot、最终 snapshot
和 baseline/Flink time-travel，校验四段 snapshot parent 链。

## 放行边界

本 ADR 只放行单表、单 target、两个独立 Spark worker 的连续成功 fresh retry。它不代表 provider
abort recovery、跨系统 exactly-once、REST/Gravitino destructive-write conformance、生产
HA/RPO/RTO 或生产 SLO 已完成。

## 真实验证

入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_cross_process_successful_retry.py`  
实现：`scripts/spark_chongqing_osm_iceberg_sql_merge_cross_process_successful_retry.py`  
测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_cross_process_successful_retry.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_cross_process_successful_retry_2026-08-24.json`  
SHA-256：`f58dc0cfc69e848764f4ec45c619278a4fb98d1aebf37656597c6492891ea9b5`
