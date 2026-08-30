# ADR-270：Spark SQL MERGE retry budget 的 fail-closed admission

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-266](adr-266-spark-sql-merge-automatic-fresh-retry.md)、[ADR-269](adr-269-spark-sql-merge-deterministic-auto-deduplication.md)

## 背景

自动 fresh retry 和显式 rank 去重已经有真实证据，但“还能重试几次”必须先于 destructive
MERGE 提交被控制。Iceberg/Spark 失败写入可能进入 task abort，而不是稳定抛出可重试异常；因此
不能把重复提交失败本身当作 retry controller。

本切片验证 admission-level budget：重复 source 在提交前被识别，预算内记录一次拒绝；预算为 1、
调用方强制要求 2 次时，第二次不提交、不启动 destructive MERGE。

## 决策

在 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO 单表 profile 中，真实建立 baseline、
Flink child 和重复 source admission。`retry_budget=1` 时只记录一次
`duplicate_source_rejected_before_merge`，剩余一次标记为 prevented；catalog、行集和 snapshot
保持不变。

预算控制 admission，不负责自动选择 source、退避时间或生产故障恢复；ADR-269 负责确定性 rank
去重，ADR-266 负责成功 fresh retry。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_retry_budget.py`  
Spark wrapper：`scripts/spark_chongqing_osm_iceberg_sql_merge_retry_budget.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_retry_budget.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_retry_budget_2026-08-24.json`  
报告 SHA-256：`8953e1e77f17a171260fa6851460ef5ae1d91927b4a6849513b103fb1b316b3c`

- 11 项顶层检查通过；预算 1、强制需求 2，实际记录 1 次 admission，阻止 1 次超预算提交。
- duplicate source 被识别，未执行 destructive MERGE；行集和 catalog 保持 Flink child。
- 2 个 metadata、4 个 manifest、4 个 Parquet 对象图通过；容器、对象前缀、工作目录清理通过，
  主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表重复 source 的 admission-level retry budget、超预算停止、catalog/row-set
fail-closed 和审计证据。

仍未放行：自适应退避、跨 worker/跨 target budget、失败 Iceberg artifact recovery、成功 retry
后的 budget 组合、SQL UPDATE join/subquery、跨分区/多文件写入、生产 HA/RPO/RTO、Kubernetes
recovery 和跨系统 exactly-once。

## Revisit trigger

当需要第二次真实 destructive retry、跨进程 budget 共享或 provider-specific abort recovery 时，
必须新增 controller lease、attempt ledger、退避/熔断、artifact cleanup 和独立 snapshot 证据。
