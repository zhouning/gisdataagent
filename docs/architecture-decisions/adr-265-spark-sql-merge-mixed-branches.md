# ADR-265：Spark SQL MERGE 的混合 matched/not-matched branch 组合

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-263](adr-263-spark-sql-merge-multiple-matched-branches.md)、[ADR-264](adr-264-spark-sql-merge-multiple-not-matched-branches.md)

## 背景

ADR-263 和 ADR-264 分别验证了 matched branch 组合和 not-matched branch 组合，但真实批次
通常会同时处理删除、更新和新要素插入。若把这些动作拆成多次写入，消费者会看到中间状态，
也无法证明 branch ordering 和单批次原子性。本切片把四种 bounded branch 放进同一个 SQL
`MERGE`，验证混合 branch 的确定性选择和单 snapshot 提交。

## 决策

在 Spark 3.5 / Iceberg 1.6.1 / JDBC Catalog / S3FileIO 版本矩阵下放行一个 bounded slice：

1. 建立三行重庆 OSM baseline，使用 identity(`road_id`) 分区和 format-v2。
2. Flink 先将 `102262017` 写到 revision 2，形成 baseline child snapshot。
3. Spark source 包含四条唯一 row：`102262017 + action=delete`、`102262020 + action=update`、
   `102262028 + action=insert_priority`、`102262030 + action=insert_default`。
4. 单个 SQL `MERGE` 的 branch 顺序固定为：条件 matched-delete、默认 matched-update、条件
   not-matched-insert、默认 not-matched-insert。
5. delete 只移除 Flink revision 2；update 将 `102262020` 写为 revision 2；两个未匹配 road
   各插入一次。四个动作必须在同一个 child snapshot 中提交，不能部分落库。

source row 的 action、expected revision、result revision、token 和 source row id 均由上游
显式生成。本 ADR 不放行自动 branch 推断或复杂匹配谓词。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| delete/update/insert 分开写入 | 各步容易调试 | 多 snapshot，批次产生中间状态 |
| 上游先拆分为多张表 | provider 逻辑简单 | branch 选择移出平台，难以验证批次原子性 |
| 一个 SQL MERGE 统一执行四类 branch | action、顺序、token 和 snapshot 可审计 | 当前仅覆盖四条 source row、简单 key 谓词 |

选择第三项。phase report 同时记录 branch token、最终 row 集合、snapshot 链、time-travel 和对象图。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_mixed_branches.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_mixed_branches.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_mixed_branches.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_mixed_branches_2026-08-24.json`  
报告 SHA-256：`ff281f846a80375c154a93f3778392d91641e61cb4692019cd1870e29e819356`

- 真实重庆 OSM source 绑定 50,366 个要素；两个 insert road 均不在 Flink target state。
- 最终状态为 5 行：baseline road 1 行保留、Flink revision 2 被删除、另一条 baseline road 更新为
  revision 2、两个新 road 各插入 1 行。
- snapshot 链为 `append -> append -> overwrite`；delete token 为 0，update/两个 insert token
  各为 1；baseline/Flink/final time-travel、7 个 parquet、8 个 manifest、3 个 metadata 对象均通过。
- 报告 10 项顶层检查通过；容器、对象前缀、工作目录清理通过，主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、四条唯一 source row、一个条件 matched-delete、一个默认 matched-update、
一个条件 not-matched-insert、一个默认 not-matched-insert、简单 ON 谓词和单次 SQL `MERGE`。

仍未放行：更多 branch 或 source row、复杂谓词/join/subquery、跨分区/多文件 destructive write、
自动去重、自动 retry、streaming recovery、REST/Gravitino destructive-write conformance、生产
HA/RPO/RTO 和 Kubernetes runtime。

## Revisit trigger

当 branch 优先级、source cardinality、跨分区 key 变化或条件复杂度增加时，必须重新定义 branch
ordering、冲突检测、snapshot、time-travel 和 recovery contract，不在本 ADR 上扩大范围。
