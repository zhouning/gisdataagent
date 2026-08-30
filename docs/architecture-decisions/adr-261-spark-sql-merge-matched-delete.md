# ADR-261：Spark SQL MERGE 的 matched-delete 分支

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-256](adr-256-spark-sql-merge-stale-conflict-isolation.md)、[ADR-259](adr-259-spark-sql-merge-multi-source-row-conflict-isolation.md)、[ADR-260](adr-260-spark-sql-merge-multi-branch-update-insert.md)

## 背景

ADR-260 已验证 matched-update 与 not-matched-insert 的单次 MERGE。对于版本化道路表，删除也
必须绑定 source 的 `expected_revision`，否则会误删同一 `road_id` 的其他版本，或把并发更新
隐藏成成功提交。本切片只验证一个明确的 matched-delete branch。

## 决策

在 Spark 3.5 / Iceberg 1.6.1 / JDBC Catalog / S3FileIO 版本矩阵下放行：

1. 建立三行重庆 OSM baseline，使用 identity(`road_id`) 分区和 format-v2。
2. Flink 先对 `102262017` 提交 revision 2，推进 baseline child snapshot。
3. Spark 使用一条 source row，`road_id=102262017` 且 `expected_revision=2`，执行真实 SQL：
   `MERGE INTO ... WHEN MATCHED THEN DELETE`。
4. 只删除 revision 2；baseline 中同一道路的 revision 1 必须保留。MERGE 产生一个 child
   snapshot，baseline/Flink/final 均可 time-travel 回读。

source row 的 target、expected revision、commit token 和 source row id 均由上游显式生成；本
ADR 不引入自动删除、自动 retry 或跨系统事务。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| `DELETE FROM` 按 road_id 删除 | 语句简单 | 无法表达版本 guard，可能误删历史/并发版本 |
| 直接 Iceberg row-filter delete | provider 冲突控制明确 | 失去 SQL MERGE branch 的 source 语义 |
| `MERGE` 按 road_id + expected_revision matched-delete | source 可审计、版本 guard 清晰、单次 snapshot | 当前只覆盖单 target row、单分支和简单谓词 |

选择第三项。复杂谓词、多 target row、多 matched branch 和跨分区 destructive write 另行验收。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_delete.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_delete.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_delete.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_delete_2026-08-24.json`  
报告 SHA-256：`52da24a731219db83c3881a6fbe8fbac309e3c16bc9f96ddc1cee4598a6057a2`

- 真实重庆 OSM source 绑定 50,366 个要素；Flink revision 2 先提交，Spark 随后删除该 revision。
- 最终 snapshot 链为 `append -> append -> delete`；revision 1 保留、revision 2 不存在，最终三行
  内容 hash、baseline/Flink/final time-travel 和对象图全部通过。
- 报告 10 项顶层门全部通过；Catalog/Flink/Spark/MinIO、对象前缀、工作目录清理通过，主库
  SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、identity(`road_id`) 分区、单 source row、`road_id + expected_revision`
简单 ON 谓词下的 `WHEN MATCHED THEN DELETE`，以及单次 snapshot 和 time-travel 证据。

仍未放行：多个 target row、多个 matched branch、复杂谓词/join/subquery、delete 与 update/insert
混合分支的并发冲突、跨分区/多文件 destructive write、自动去重、自动 retry、streaming recovery、
REST/Gravitino destructive-write conformance、生产 HA/RPO/RTO 和 Kubernetes runtime。

## Revisit trigger

当删除语义需要多个 target、分区级清理或与 update/insert 混合时，必须新增 branch ordering、
cardinality、conflict detection、time-travel 和 recovery contract，不在本 ADR 上扩大范围。
