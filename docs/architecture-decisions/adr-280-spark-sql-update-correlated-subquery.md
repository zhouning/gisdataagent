# ADR-280：Spark SQL UPDATE 的相关 scope 子查询

**状态**：Accepted（2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-273](adr-273-spark-sql-update-subquery-scope.md)、[ADR-268](adr-268-spark-sql-update-complex-predicate.md)

## 背景

ADR-273 已证明不相关 `IN (SELECT ...)` scope。真实数据产品还需要把 scope 行与 UPDATE 的外层 target 行关联，否则 scope 查询和目标集合之间缺少可验证的关联键。

## 决策

在 Spark 3.5、Iceberg 1.6.1、PostgreSQL JDBC Catalog、MinIO S3FileIO 的单表 profile 中执行 bounded 相关子查询：

```sql
UPDATE lakehouse.<namespace>.chongqing_osm_roads
SET revision = 3, writer_engine = ..., commit_token = ...
WHERE EXISTS (
  SELECT 1
  FROM gda_sql_update_scope AS scope
  WHERE scope.scope_road_id = road_id
    AND scope.eligible = true
)
AND revision = expected_revision
```

scope view 包含两个 eligible target 和一个 false guard row。验收先由两个 Flink append 将 target 推进到 revision 2，再执行 stale revision 1 UPDATE，确认整体 fail-closed；随后重新读取 Flink child，以 revision 2 fresh retry，确认两个 target 各更新一次，guard 行不变，且最终 snapshot parent 链和 time-travel 正确。

## 放行边界

本 ADR 只放行单表、两个 target、WHERE 子句中的相关 `EXISTS` scope subquery。仍不放行 UPDATE JOIN、多表写入、SET 表达式中的相关 scalar subquery、跨分区/多文件 destructive write、MOR/delete files、自动 retry budget/backoff、provider abort recovery、REST/Gravitino conformance、HA/RPO/RTO 或生产 SLO。

## 真实验证

入口：`scripts/certify_chongqing_osm_spark_flink_sql_update_correlated_subquery.py`  
worker：`scripts/spark_chongqing_osm_iceberg_sql_update_correlated_subquery.py`  
实现：`scripts/spark_chongqing_osm_iceberg_sql_update_multi_conflict.py`  
测试：`data_agent/test_chongqing_osm_spark_flink_sql_update_correlated_subquery.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_update_correlated_subquery_2026-08-25.json`  
报告 SHA-256：`21aa805de87e29082eb41da2816f3914781b9e862abb06cc620221f3e5f13260`

报告关键事实：相关 predicate 被执行、两个 Flink child 均通过、stale update 被拒绝且 catalog 未改变、fresh retry 和独立 verify 通过、最终 snapshot 数量为 4、guard row 未变，主 SourceSync 仍为 `[0,0,0]`。
