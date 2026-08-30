# ADR-269：Spark SQL MERGE 重复 source 的确定性自动去重

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-259](adr-259-spark-sql-merge-multi-source-row-conflict-isolation.md)、[ADR-266](adr-266-spark-sql-merge-automatic-fresh-retry.md)

## 背景

ADR-259 证明重复 source row 必须先拒绝，ADR-266 证明调用方可以提供一条 fresh source
重试。两者仍把“哪一条 source row 可以代表业务意图”留在上游；如果 worker 自己无规则地选一条，
会把数据治理决策藏进执行器。

本切片只认证一个显式、可审计的去重规则：候选 source row 按 `dedup_rank` 降序排序，rank
相同时按 `source_row_id` 升序稳定裁决。未选候选不得提交 token。

## 决策

在既有 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO 单表 profile 中：

1. 先执行真实重复 source cardinality rejection，catalog 必须保持 Flink child。
2. worker 接收两个带 rank 的 fresh candidates：`fresh-source-deduplicated` rank 100、
   `candidate-lower-priority` rank 10。
3. worker 按 `highest_rank_then_source_row_id` 选择 rank 100 的 row，执行已有 fresh MERGE。
4. 只有被选 row 的 token 可以出现在最终表；未选 token 必须缺失，最终结果仍与 plan 绑定。

去重规则是版本化 plan 的显式输入，不自动推断业务优先级；retry budget、退避和跨分区去重另行
验收。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 继续要求上游先去重 | 执行器简单，业务决策外置 | 每个调用方都要重复实现一致性和证据记录 |
| worker 按显式 rank 稳定选择 | 规则可审计、可重放，未选 token 可验证 | rank 的业务含义仍需上游批准 |
| worker 按到达时间或随机选择 | 接入方便 | 不确定、不可重放，可能造成静默数据漂移 |

选择第二项；没有 rank 的 source 不进入该自动去重 profile。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_auto_dedup.py`  
Spark wrapper：`scripts/spark_chongqing_osm_iceberg_sql_merge_auto_dedup.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_auto_dedup.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_auto_dedup_2026-08-24.json`  
报告 SHA-256：`256749d2d6376b631240d3a77f36c489589f8e8e7db2bc23cc633d9723bf9fb2`

- 10 项顶层检查全部通过，真实重庆 OSM source 绑定 50,366 个要素。
- cardinality rejection 后，两个 candidate 按 rank 选择 `fresh-source-deduplicated`；未选 candidate
  token 未落库。
- fresh snapshot 是 Flink child，最终内容、time-travel、5 个 Parquet/7 个 manifest 对象图均通过。
- Spark/Flink/Catalog 容器、15 个对象、工作目录清理通过，主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、两个重复 source row、显式 rank 稳定选择、未选 token fail-closed，以及选择后
的一次 fresh SQL MERGE。

仍未放行：缺失或冲突 rank 的业务裁决、retry budget/退避、跨 target/跨分区去重、MERGE delete/insert
组合、SQL UPDATE join/subquery、REST/Gravitino destructive-write conformance、生产 HA/RPO/RTO、
Kubernetes recovery 和跨系统 exactly-once。

## Revisit trigger

当同一 source group 跨 target、跨分区或需要业务字段 survivorship 时，必须新增去重规则版本、
审批、冲突证据和回滚验证；不得把本 ADR 的 rank 规则当作通用 survivorship 策略。
