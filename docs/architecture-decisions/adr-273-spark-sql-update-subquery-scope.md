# ADR-273：Spark SQL UPDATE 的受控 scope 子查询

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-258](adr-258-spark-sql-update-multi-row-conflict-isolation.md)、[ADR-268](adr-268-spark-sql-update-complex-predicate.md)

## 背景

已有 UPDATE 切片覆盖了直接列谓词、复杂 `AND/OR/IN` 谓词和 snapshot guard，但业务数据产品经常
先通过一个受治理 scope 查询确定目标集合，再执行更新。此前路线图对 SQL UPDATE 的
join/subquery 仍没有真实 Spark/Iceberg 证据。

## 决策

在 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO 的单表 profile 中，增加一个 bounded
uncorrelated subquery 合同：

1. worker 建立临时 scope view `gda_sql_update_scope(scope_road_id, eligible)`，其中两个目标
   道路为 `eligible=true`，第三条 guard 道路为 `false`。
2. UPDATE 使用 `road_id IN (SELECT scope_road_id ... WHERE eligible = true)`，并叠加
   `revision = expected_revision`；stale baseline 仍由 snapshot guard 整体拒绝。
3. fresh retry 重读 Flink child 后复用同一 scope 规则，验证两个目标各一次更新、guard 行不变、
   baseline/Flink/final time-travel 和 snapshot 链。

## 取舍

选择不相关 `IN (SELECT ...)` 是因为它能证明 scope 子查询进入 UPDATE 的实际执行计划，同时不引入
跨表 join、相关子查询或多表写入的额外变量。缺少 scope view、scope 字段或 provider 不支持该
语义时直接失败，不降级为字符串拼接的 ID 列表。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_update_subquery.py`  
Spark writer：`scripts/spark_chongqing_osm_iceberg_sql_update_subquery.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_update_subquery.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_update_subquery_2026-08-24.json`

## 放行边界

本 ADR 只放行单表、两个 target、一个不相关 scope subquery 的 UPDATE + stale guard/fresh retry。
仍未放行：相关子查询、UPDATE join、多表写入、跨分区/多文件 destructive write、MOR/delete files、
自动 retry budget/backoff、provider abort recovery、REST/Gravitino conformance、HA/RPO/RTO 和生产 SLO。
