# ADR-274：Spark SQL MERGE retry budget 的自适应退避

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-266](adr-266-spark-sql-merge-automatic-fresh-retry.md)、[ADR-270](adr-270-spark-sql-merge-retry-budget-fail-closed.md)

## 背景

ADR-266 已验证同 worker 的 fresh retry，ADR-270 已验证 retry budget 耗尽时提交前停止；两者之间
仍缺少可审计的等待策略。没有退避记录时，连续 cardinality rejection 可能在短时间内重复撞击同一
snapshot，且报告无法区分“等待后重试”和“立即重试”。

## 决策

在 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO 的单表 profile 中，增加显式
`retry_backoff_policy`：首个 admission 不等待，后续等待按 `initial_seconds * multiplier^(attempt-2)`
计算并受 `max_seconds` 限制。每次 attempt 记录计划等待、实际等待、冲突 admission 和 snapshot
计数；预算耗尽后仍 fail-closed，不提交下一次 MERGE。

本切片使用 budget=3、强制 4 次、`0/0.01/0.02` 秒退避序列，验证 catalog、行集和 snapshot
在超预算后不变。

## 取舍

退避发生在同 worker 的提交前 admission 层，避免把 provider SDK 的重试或跨进程调度引入本切片。
等待参数写入 immutable plan/report，便于重放和审计；时间值采用短 disposable 预算，只证明顺序和
上限，不代表生产延迟 SLO。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_retry_backoff.py`  
Spark writer：`scripts/spark_chongqing_osm_iceberg_sql_merge_retry_backoff.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_retry_backoff.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_retry_backoff_2026-08-24.json`

## 放行边界

本 ADR 只放行单 worker、单表、重复 source cardinality rejection 后的 bounded adaptive backoff
和 retry budget admission。仍未放行跨进程 budget、provider abort recovery、成功 destructive retry、
跨分区 survivorship、REST/Gravitino conformance、HA/RPO/RTO 和生产 SLO。
