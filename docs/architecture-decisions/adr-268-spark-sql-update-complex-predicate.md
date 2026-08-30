# ADR-268：Spark SQL UPDATE 复杂 AND/OR/IN 谓词的 bounded 语义

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-257](adr-257-spark-sql-update-snapshot-guard.md)、[ADR-258](adr-258-spark-sql-update-multi-row-conflict-isolation.md)、[ADR-267](adr-267-spark-sql-merge-complex-predicate.md)

## 背景

ADR-257 和 ADR-258 已覆盖单行及两个目标的简单 `IN` 谓词 snapshot guard。生产 UPDATE
通常还会组合版本条件、目标集合和 writer/state 条件；只验证 `road_id IN (...) AND
revision = ...` 不能证明组合条件不会误触及 guard row。

本切片在同一张 Iceberg 表上验证以下计划绑定谓词：

```sql
revision = expected_revision
AND (
  road_id IN (first_target)
  OR (road_id = second_target AND writer_engine = 'flink-1.19.3')
)
```

`102262017` 和 `102262020` 是两个有效 target；`102262024` 是 guard row，预期保持
baseline revision 1。

## 决策

在 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO、identity(`road_id`) 分区的版本矩阵下，
放行单表、单次 SQL UPDATE 的复杂谓词切片：

1. 建立三行真实重庆 OSM baseline。
2. Flink 对两个 target 各追加 revision 2，Spark stale UPDATE 在 barrier 释放后由 snapshot
   guard 拒绝，catalog 不推进。
3. Spark fresh retry 使用上述 `AND/OR/IN` 谓词，将两个 Flink revision 2 行一次更新到 revision 3。
4. `102262024` 不被更新；baseline、Flink child 和 final snapshot 均可独立 time-travel 回读。

谓词来自版本化 plan，不由用户字符串直接拼接；本 ADR 不新增 retry policy、deduplication 或
跨分区写入语义。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 只认证等值和简单 `IN` | 实现简单，已有基线 | 无法覆盖条件组合造成的误更新风险 |
| 单表认证 `AND/OR/IN` 计划谓词 | 覆盖常见组合，guard row 可明确验收 | 仍不覆盖 join/subquery、跨表和跨分区物理写入 |
| 同时认证 join、分区写入和生产 recovery | 一次覆盖面更大 | 无法把谓词、物理布局和恢复失败边界分开定位 |

选择第二项，保持 conformance slice 可复现、可归因。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_update_complex_predicate.py`  
Spark wrapper：`scripts/spark_chongqing_osm_iceberg_sql_update_complex_predicate.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_update_complex_predicate.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_update_complex_predicate_2026-08-24.json`  
报告 SHA-256：`b1541e9a2113426c7f18055fd02a61585c4de2911b073e7cfa144b091134385a`

- 13 项顶层检查全部通过，真实重庆 OSM source 绑定 50,366 个要素。
- stale UPDATE 未提交、catalog 保持 Flink child；两个 fresh token 各出现一次。
- guard road `102262024` 保持 revision 1，最终内容、baseline/Flink/final time-travel 全部精确。
- 4 个 metadata、10 个 manifest、7 个 Parquet 对象图通过；Spark/Flink/Catalog 容器、21 个对象、
  工作目录清理通过，主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、两个 target、一次复杂 `AND/OR/IN` SQL UPDATE 的 snapshot guard、fresh
retry 和 guard-row fail-closed 语义。

仍未放行：SQL UPDATE join/subquery、多表、跨分区/多文件写入、SQL MERGE 复杂谓词之外的组合、
自动 retry budget/退避、自动 deduplication、delete/MOR、REST/Gravitino destructive-write
conformance、生产 HA/RPO/RTO、Kubernetes recovery 和跨系统 exactly-once。

## Revisit trigger

当 UPDATE 谓词依赖 join/subquery、跨表状态或分区裁剪时，必须新增对应的计划绑定、冲突隔离、
物理对象和回滚证据；不得把本 ADR 的单表结果扩展成通用 UPDATE 或生产 writer recovery 承诺。
