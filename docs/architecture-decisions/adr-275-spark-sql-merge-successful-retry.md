# ADR-275：Spark SQL MERGE 退避后的成功 fresh retry

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-266](adr-266-spark-sql-merge-automatic-fresh-retry.md)、[ADR-269](adr-269-spark-sql-merge-deterministic-auto-deduplication.md)、[ADR-274](adr-274-spark-sql-merge-adaptive-backoff.md)

## 背景

已有证据分别覆盖 cardinality rejection 后的 fresh retry，以及 retry budget 耗尽时的退避和停止，
但还没有证明“发生退避后，仍可在正确 snapshot 上完成一次成功的 destructive retry”。

## 决策

在单表、单 target、同 worker profile 中，重复 source cardinality admission 失败后：

1. 保持 Flink child snapshot 和当前行集不变。
2. 按 plan 中的 `delay_seconds=0.01` 等待，记录实际等待时间。
3. 使用 fresh Flink revision 的单条 deduplicated source 执行一次 MERGE。
4. 验证最终 token 只出现一次、snapshot parent 为 Flink child、baseline/Flink/final time-travel
   和未选 source token 约束仍成立。

## 取舍

本切片只证明一次有界成功 retry，避免把多次 destructive retry、跨进程 budget 或 provider abort
recovery 混入同一证据。等待参数固定且很短，只用于证明 admission 顺序，不代表生产退避 SLO。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_successful_retry.py`  
Spark writer：`scripts/spark_chongqing_osm_iceberg_sql_merge_successful_retry.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_successful_retry.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_successful_retry_2026-08-24.json`

## 放行边界

本 ADR 只放行单 worker、单表、单 target 的一次退避后成功 fresh MERGE retry。仍未放行多次成功
retry、跨进程 budget、provider abort recovery、跨分区 survivorship、REST/Gravitino conformance、
HA/RPO/RTO 和生产 SLO。
