# ADR-276：Spark SQL MERGE 的跨进程 retry budget authority

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-270](adr-270-spark-sql-merge-retry-budget-fail-closed.md)、[ADR-274](adr-274-spark-sql-merge-adaptive-backoff.md)

## 背景

ADR-270 和 ADR-274 证明了单 worker 的预算与退避。多个 worker 如果各自维护内存计数，会同时认为预算
仍有剩余，导致提交次数超过策略上限。需要一个共享、事务锁定、可审计的 admission authority。

## 决策

为 bounded slice 引入 PostgreSQL retry-budget ledger：预算行按 `operation_key` 唯一，worker 在同一
事务中对预算行 `FOR UPDATE`，成功 admission 递增 `attempt_count`，超限 admission 写入 denied event
但不递增。每次 admission 都写 immutable event，attempt number 必须全局唯一且连续。

真实验收使用两个独立 OS worker、同一 operation key、预算 3、每 worker 发起 2 次请求；预期全局只
准入 3 次、第 4 次 fail-closed。验收结束删除专用 schema，不修改主 SourceSync 数据。

## 放行边界

本 ADR 只放行 PostgreSQL 共享 admission ledger 的跨进程预算语义，不代表跨进程 Iceberg destructive
write、provider abort recovery、成功 retry、跨系统 exactly-once、HA/RPO/RTO 或生产 SLO 已完成。

## 真实验证

入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_cross_process_budget.py`  
实现：`data_agent/lakehouse_retry_budget.py`  
测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_cross_process_budget.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_cross_process_budget_2026-08-24.json`
