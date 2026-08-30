# ADR-262：Spark SQL MERGE 的多 target row matched-update

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-256](adr-256-spark-sql-merge-stale-conflict-isolation.md)、[ADR-259](adr-259-spark-sql-merge-multi-source-row-conflict-isolation.md)、[ADR-260](adr-260-spark-sql-merge-multi-branch-update-insert.md)、[ADR-261](adr-261-spark-sql-merge-matched-delete.md)

## 背景

此前的 SQL `MERGE` 证据分别覆盖单 target row、重复 source row 的 cardinality rejection、
matched-update + not-matched-insert 和 matched-delete。真实数据产品常在一个批次里更新多个已
存在的道路；如果平台把每个 target 拆成多个提交，就会产生多个 snapshot 和中间可见状态。

## 决策

在 Spark 3.5 / Iceberg 1.6.1 / JDBC Catalog / S3FileIO 版本矩阵下放行一个严格的多 target
slice：

1. 建立三行重庆 OSM baseline，使用 identity(`road_id`) 分区和 format-v2。
2. Flink 先将 `102262017` 写到 revision 2，形成 baseline child snapshot。
3. Spark source 只包含两条唯一 source row：`102262017 + expected_revision=2` 更新到
   revision 3；baseline 中另一条道路 `102262020 + expected_revision=1` 更新到 revision 2。
4. 使用单个 `WHEN MATCHED THEN UPDATE` 的 SQL `MERGE`；两条 source row 必须在同一个 child
   snapshot 中提交，两个 commit token 各出现一次，不能发生部分更新。

source row 的 target、expected revision、result revision、token 和 source row id 均由上游显式
生成。本 ADR 不自动扩展到复杂谓词、跨分区 key 变化或多个 branch。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 每个 target 单独 MERGE | 逻辑简单 | 多 snapshot，消费者可能看到批次中间状态 |
| `INSERT OVERWRITE` 重写整表 | 可一次重建结果 | 放大写入范围，难以证明 target-level branch 语义 |
| 单次 SQL MERGE 更新多个 target row | 单 snapshot、source-to-target 映射清晰、可 time-travel | 当前仅覆盖唯一 source row、简单 ON 谓词和单 matched branch |

选择第三项。复杂谓词、多个 branch、跨分区 destructive write 继续拆分为独立决策和验收。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_multi_target.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_multi_target.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_multi_target.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_multi_target_2026-08-24.json`  
报告 SHA-256：`4096d55f99f5509910d91d75f41f465022b7a089f513a997249b4e25dbbb09be`

- 真实重庆 OSM source 绑定 50,366 个要素，两个 target row 各更新一次。
- snapshot 链为 `append -> append -> overwrite`；两个 token 各出现一次，最终四行内容、baseline/
  Flink/final time-travel、对象图和 SourceSync `[0, 0, 0]` 全部通过。
- 报告 11 项顶层门通过；Catalog/Flink/Spark/MinIO、对象前缀和工作目录清理通过。

## 放行边界

本 ADR 放行：单表、两条唯一 source row、两个不同 target row、简单 ON 谓词、单个 matched-update
branch 的单次 SQL `MERGE`。

仍未放行：重复 source row 自动去重、多个 matched/not-matched branch、delete 与 update/insert
混合分支、复杂谓词/join/subquery、跨分区/多文件 destructive write、自动 retry、streaming recovery、
REST/Gravitino destructive-write conformance、生产 HA/RPO/RTO 和 Kubernetes runtime。

## Revisit trigger

当一个 source batch 需要跨分区 key 变化、branch ordering 或多个 target 的条件更新时，必须新增
cardinality、冲突检测、snapshot、time-travel 和 recovery 证据，不在本 ADR 上扩大范围。
