# ADR-259：Spark SQL MERGE 多 source row 冲突隔离

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-256](adr-256-spark-sql-merge-stale-conflict-isolation.md)

## 背景

ADR-256 只覆盖单 source row 的 SQL `MERGE`。真实数据管线可能在同一批 source 中为同一个
`road_id + expected_revision` 产生多条候选记录。如果直接让 MERGE 选择其中一条，结果会依赖
执行计划；如果部分写入，则会破坏 revision 和 lineage 的确定性。

## 决策

对同一 target row 的重复 source row 采用 provider cardinality rejection，并把 fresh retry
建立在显式去重后的 source 上：

1. Spark 在 identity(`road_id`)、format-v2 表建立三行重庆 OSM baseline。
2. Flink 先为同一 `road_id` 提交 revision 2，推进 JDBC Catalog child snapshot。
3. Spark barrier 前准备两条 source row；两条 row 的 `road_id` 和 `expected_revision=1` 相同，
   但 `source_row_id`、new revision 和 commit token 不同。
4. barrier 释放后执行真实 SQL `MERGE INTO`。必须观察到 Spark 的 merge-row cardinality validator
   拒绝，catalog 不新增 snapshot，两个 source token 都不能进入当前数据。
5. fresh retry 只能使用显式去重后的单条 source row，并以 `expected_revision=2` 更新到 revision 3。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 按 source 顺序选第一条 | 实现简单 | 结果依赖排序和执行计划，无法证明业务确定性 |
| 聚合/去重后自动选一条 | 可继续提交 | 去重规则会成为新的业务语义，必须单独设计、审批和验证 |
| provider cardinality rejection，fresh retry 使用显式去重 source | fail-closed，错误不会变成数据；去重规则由上游显式负责 | 当前批次整体失败，需要上游重新生成确定性的 source |

选择第三项。平台先保证数据不被歧义 source 污染，再由上游数据产品定义可审计的去重规则。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_multi_source_conflict.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_multi_source_conflict.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_multi_source_conflict.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_multi_source_conflict_2026-08-24.json`  
报告 SHA-256：`4ec2f8628cfc58ae52d1eb498ee07510ecfb3da80dc82d45444a5e85e3ca3bc3`

- 真实重庆 OSM source 绑定 50,366 个要素，目标道路为 `102262017`。
- 两条重复 source row 均绑定同一 target/revision，Spark `MergeRowsExec` cardinality validator
  拒绝 MERGE；目标仍为 revision 1/2，stale token 数为 0，catalog 保持两条 append snapshot。
- 去重后的 fresh source row 将 revision 2 更新到 revision 3，形成第三条 overwrite snapshot；
  baseline/Flink/final time travel 和最终内容 hash 全部通过。
- 最终对象图为 3 个 metadata、7 个 manifest、5 个 parquet；对象前缀、Spark/Flink/Catalog 容器、
  工作目录清理通过，主库 SourceSync 前后均为 `0/0/0`。

## 放行边界

本 ADR 放行：当前 Spark 3.5/Iceberg 1.6.1/JDBC Catalog/S3FileIO 版本矩阵下，单表、单 target
row、两条重复 source row、`WHEN MATCHED THEN UPDATE` 的 cardinality fail-closed，以及显式去重
后的 fresh retry。

仍未放行：自动去重规则、MERGE insert/delete 分支、多 target row、多分区/跨分区 key 变化、
partition evolution、equality/position delete、MOR、自动 retry/checkpoint recovery、
REST/Gravitino destructive-write conformance、生产 HA/RPO/RTO 和 Kubernetes runtime。

## Revisit trigger

当业务需要平台自动决定重复 source row 的优先级，或 source row 具有合法聚合语义时，必须先新增
可审计的 deduplication contract、质量规则和审批证据，再重新评估是否放宽 cardinality rejection。
